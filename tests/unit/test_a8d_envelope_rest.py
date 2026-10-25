"""A8-D（aurora72）REST 信封一致性抽查回归钉：ui/server.py 信封收编 + 400 守卫。

背景（aurora72 A8-D 抽查实测，2026-10-12）：
- 抽 61 个 /api/* 端点（TestClient 实测）：ok/错误面基本齐备，发现两类缺口——
  ①``/api/tune/status`` 成功响应缺 ``ok`` 键（信封成功面缺失）；
  ②limit=abc 等 11 个端点的非法查询/请求参数在 handler 内 int()/float()
  裸解析抛 ValueError → Starlette 500 纯文本，失败面无信封。
本文件钉住收编后的形状：ParamError→400 error 信封、tune_status 补 ok 面、
server.py 裸 ``return {"ok"...}`` 字面量清零（构造器单源）、hfss_import
空路径快速 400（不真启 AEDT）。全部 tmp cwd 隔离（#144），不触真实 runs/。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

# aurora_d UI-R1 拆分后 handler 分域入 routes/——信封守卫扫描面随面走
# （server.py 装配壳 + routes/* + csp.py 全 .py）。
_UI_PACKAGE_DIR = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui"


def _ui_package_source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _isolated(isolated_cache_off, monkeypatch):
    """隔离体收编 tests/conftest.py::isolated_cache_off（T5 批5 单源化）
    + 专用增量（RFAUTO_REGISTRY_DB 清位）。
    """
    monkeypatch.delenv("RFAUTO_REGISTRY_DB", raising=False)
    yield


@pytest.fixture()
def client():
    from rfauto.ui.server import create_ui_app

    return TestClient(create_ui_app(include_runs_mount=False))


class TestParamErrorEnvelope:
    """非法查询/请求参数 → 400 ``{"ok": False, "errors": [...]}``（非 500 裸崩）。"""

    @pytest.mark.parametrize(
        "url",
        [
            "/api/runs?limit=abc",
            "/api/inbox?limit=abc",
            "/api/loop/boards?limit=abc",
            "/api/farfield?limit=abc",
            "/api/field?limit=abc",
            "/api/pareto_runs?limit=abc",
            "/api/uq/samples?limit=abc",
            "/api/datasets/__nope__/preview?limit=abc",
        ],
    )
    def test_limit_abc_returns_400_envelope(self, client, url):
        r = client.get(url)
        assert r.status_code == 400, r.text
        body = r.json()
        assert body["ok"] is False
        assert isinstance(body["errors"], list) and body["errors"]
        assert "limit" in body["errors"][0]

    def test_feasibility_grid_n_abc_400(self, client):
        r = client.get("/api/runs/x/feasibility?x_param=a&y_param=b&grid_n=abc")
        assert r.status_code == 400
        body = r.json()
        assert body["ok"] is False and "grid_n" in body["errors"][0]

    def test_field_levels_abc_400(self, client):
        r = client.get("/api/field/x?levels=abc")
        assert r.status_code == 400
        body = r.json()
        assert body["ok"] is False and "levels" in body["errors"][0]

    def test_field_slice_index_abc_400(self, client):
        r = client.get("/api/field/x?sx=abc")
        assert r.status_code == 400
        body = r.json()
        assert body["ok"] is False and "sx" in body["errors"][0]

    def test_uq_yield_n_abc_400(self, client):
        r = client.post(
            "/api/uq/yield",
            json={"samples_path": "x.json", "tolerances": {"g": 0.01}, "n": "abc"},
        )
        assert r.status_code == 400
        body = r.json()
        assert body["ok"] is False and "n" in body["errors"][0]

    def test_valid_limit_still_works(self, client):
        """合法 limit 行为不变（收编只补失败面，不动成功路径）。"""
        r = client.get("/api/runs?limit=3")
        assert r.status_code == 200
        assert r.json()["ok"] is True


class TestTuneStatusOkFace:
    """``/api/tune/status`` 补 ok=True 成功面；历史四键原样保留。"""

    def test_status_carries_ok_and_legacy_keys(self, client):
        body = client.get("/api/tune/status").json()
        assert body["ok"] is True
        assert next(iter(body)) == "ok"  # 信封惯例：ok 恒首键
        for legacy_key in ("running", "result", "error", "started_at"):
            assert legacy_key in body

    def test_busy_tune_start_keeps_singular_legacy_face(self, client, monkeypatch):
        """busy 分支单数 error 遗留族形状保持（契约 §3：按域升版才统一）。"""
        from rfauto.ui import server as server_mod

        monkeypatch.setitem(server_mod._TUNE_STATE, "running", True)
        r = client.post("/api/tune/start", json={"path": "nope.yaml"})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert body["error"] == "已有调参任务在运行"
        assert "errors" not in body  # 单数键不改形（前端消费面兼容）


class TestHfssImportEmptyGuard:
    """空工程路径快速 400：不真启 AEDT（抽查实证此前 ok=True 空规格误导）。"""

    def test_empty_project_400_singular_error(self, client):
        r = client.post("/api/hfss/import", json={"project": "  "})
        assert r.status_code == 400
        body = r.json()
        # 本端点既有失败面=单数 error（前端 pages.js 读 importSpec.error）
        assert body["ok"] is False
        assert isinstance(body["error"], str) and body["error"]
        assert "路径为空" in body["error"]


class TestEnvelopeConstructorSingleSource:
    """server.py 裸 ``return {"ok"...}`` 字面量清零（信封构造器单源收编）。"""

    def test_no_bare_ok_return_literals(self):
        # aurora_d UI-R1 拆分后扫描面=ui 包全 .py（守卫随面走，防 routes/
        # 分域模块回潮裸 return {"ok"...}）；**campaign_app.py 豁免**——
        # UX-B6 逐字节拆分的既有面，_campaign_remote_block 的裸块是带
        # machine/mtls 富键的历史单数失败族（A8-D 收编当时即未触），归
        # UX-B6 面，不在本席拆分范围。
        srcs = [_ui_package_source(p)
                for p in sorted(_UI_PACKAGE_DIR.rglob("*.py"))
                if p.name != "campaign_app.py"]
        bare = re.findall(r'return \{"ok"', "\n".join(srcs))
        assert bare == [], f"UI 包出现裸 ok 信封 return: {len(bare)} 处"

    def test_chat_prompt_ok_first_key(self, client):
        body = client.get("/api/chat/prompt").json()
        assert body["ok"] is True
        assert next(iter(body)) == "ok"
        assert isinstance(body["prompt"], str) and body["prompt"]


class TestCalculatorMismatchMessage:
    """参数不匹配错误附必填参数清单（裸 TypeError 串 → 可操作消息）。"""

    def test_mismatch_lists_required_params(self):
        from rfauto.service.calculator_service import (
            CALCULATOR_REGISTRY,
            run_calculator,
        )

        name = "albersheim_detection_snr"
        required = list(CALCULATOR_REGISTRY.get(name).required)
        params: dict = {k: 1.0 for k in required}
        params["__bogus_param__"] = 1
        out = run_calculator(name, params)
        assert out["ok"] is False
        assert "参数不匹配" in out["error"]  # 既有断言口径（子串）兼容
        assert "可接受参数" in out["error"]
        assert out["error"].count("[") >= 1  # 参数名清单在消息里
        assert "required" not in out  # 键形不变：单数 error 遗留族
