"""F1 席（UI 域，review_aurora_next 审查修复批，2026-10-13）回归钉。

对象：src/rfauto/ui/{server.py, campaign_app.py, params.py} 与
src/rfauto/ui/static/{pages.js, plotcard.js}。五块：

1. **P0-A（A6 P0-1，R6 F-3 尾款）**：工程导入版本下拉曾钉死 2023.1/2026.1
   且显式透传，把 server 缺省钉整个旁路（现网注册表仅 v251=2025 R1，真机必
   请求未安装的 AEDT——A7-C 席"误钉 2026.1 致导入失败"即此坑）——前端改
   "服务端缺省（2025.1）"缺省项+自定义输入框，空值不透传 version 键；四处
   版本旧叙事中性化（与 index.html:795 已修脚注同口径"以实装版本为准"）。
2. **P0-B（A6 P0-2）**：campaign dashboard ``grid_n=abc`` 500 裸崩 → 400
   信封（A8-D 守卫族收编，守卫单源迁 rfauto/ui/params.py）。
3. **P0-C（A4 P0-3）**：ui/server.py 全部 POST 路由坏 JSON 体 → 400 信封
   （_json_body 守卫 + JSONDecodeError exception handler 保险环，与程序化面
   rest_api.py 同款）。
4. **P1-D（A6 P1-3）**：plotCard 同容器重建先 dispose 旧实例+摘旧 resize
   监听（实例/监听无界累积清偿；壳层装配面 node 不可驱，走源码钉惯例）。
5. **P1-F（A6 P1-5）**：Mount(/runs) 相对 cwd → RUNS_DIR 同源绝对解析+缺席
   降级关闭（非仓根 cwd ``rfauto ui`` 启动冒烟）。

不依赖 runs/ 存量、不触网络、不启动 AEDT（hfss_import_recipe monkeypatch）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from starlette.testclient import TestClient

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
# 架构批 UI-R2（2026-10-14）：pages.js 拆分为薄入口 + pages/ 域模块（零构建
# ESM）——源码钉读"入口+全部域模块"并集，行为断言逐字不变（拆分前=单文件）。
def _pages_union_text() -> str:
    parts = [_STATIC / "pages.js"]
    parts += sorted((_STATIC / "pages").glob("*.js"))
    return "\n".join(p.read_text(encoding="utf-8") for p in parts)

_PAGES = _pages_union_text()

_PLOTCARD = (_STATIC / "plotcard.js").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _isolated(isolated_cache_off):
    """隔离体收编 tests/conftest.py::isolated_cache_off（T5 批4 单源化）。"""
    yield


@pytest.fixture()
def client():
    from rfauto.ui.server import create_ui_app

    return TestClient(create_ui_app(include_runs_mount=False))


# ────────────────── P0-C：坏 JSON 请求体 → 400 信封 ──────────────────

class TestServerJsonBodyGuard:
    """A4 P0-3：POST 路由裸 ``await request.json()`` 对畸形体 500 裸崩 →
    _json_body 守卫归一 400 error 信封（抽样面覆盖 A4 报告点名的路由）。"""

    @pytest.mark.parametrize("url", [
        "/api/recipe",               # api_recipe_save
        "/api/run",                  # api_run
        "/api/tune/start",           # api_tune_start
        "/api/sandbox/promote",      # api_sandbox_promote
        "/api/inbox/approve",        # api_inbox_approve
        "/api/chat",                 # api_chat
        "/api/hfss/import",          # api_hfss_import（不得真启 AEDT）
        "/api/calculators/run",      # api_calculators_run
        "/api/sparams/external",     # api_sparams_external
        "/api/loop/control",         # api_loop_control
        "/api/uq/yield",             # api_uq_yield
        "/api/playground/predict",   # api_playground_predict
        "/api/smith/external",       # api_smith_external
        "/api/model3d",              # api_model3d POST 分支
        "/api/chat/settings",        # api_chat_settings POST 分支
    ])
    def test_bad_json_body_400_envelope(self, client, url):
        r = client.post(url, content="{invalid json",
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 400, f"{url}: {r.text[:200]}"
        body = r.json()
        assert body["ok"] is False
        assert isinstance(body["errors"], list) and body["errors"]

    def test_non_object_json_body_400(self, client):
        # 非对象体（数组/标量）旧形态同样 500（body.get AttributeError）；
        # rest_api 同款归一"请求体必须是 JSON 对象"。
        r = client.post("/api/run", json=[1, 2, 3])
        assert r.status_code == 400
        assert "JSON 对象" in r.json()["errors"][0]

    def test_valid_json_body_success_path_unchanged(self, client, tmp_path):
        # 收编只补失败面：合法体行为不变（照 test_ui.py save roundtrip 形态）
        path = tmp_path / "recipe.yaml"
        path.write_text(yaml.safe_dump({
            "model": "wilkinson_power_divider", "schema_version": 1,
            "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
        }), encoding="utf-8")
        r = client.post("/api/recipe", json={
            "path": str(path), "updates": {"params": {"arm_len_mm": 19.0}}})
        assert r.status_code == 200 and r.json()["ok"] is True

    def test_tune_body_bad_int_400_not_fake_start(self, client, monkeypatch):
        # A6 P0-2 同族：n_gen 等 body int 此前在后台线程内裸 int()（坏值=
        # 任务槽已占+error 态假启动）——提前到路由层 _int_param 守卫。
        started = {}
        import rfauto.ui.server as server_mod

        monkeypatch.setitem(server_mod._TUNE_STATE, "running", False)
        monkeypatch.setattr(
            "rfauto.service.api.start_tune",
            lambda *a, **kw: started.update(kw) or {"ok": True})
        r = client.post("/api/tune/start", json={"path": "x.yaml", "max_trials": "abc"})
        assert r.status_code == 400
        assert "max_trials" in r.json()["errors"][0]
        assert not started  # 守卫拒绝：不占任务槽、不进线程

    def test_json_decode_error_exception_handler_belt(self, client):
        # 保险环：JSONDecodeError 直挂 exception_handlers——未来新增调用点
        # 漏过 _json_body 时仍 400 信封（非 500 纯文本）。
        from rfauto.ui.server import _param_error_handler, create_ui_app

        app = create_ui_app(include_runs_mount=False)
        assert json.JSONDecodeError in app.exception_handlers
        assert app.exception_handlers[json.JSONDecodeError] is _param_error_handler


# ────────────────── P0-B：campaign dashboard grid_n 守卫 ──────────────────

class TestCampaignGridNGuard:
    """A6 P0-2：``?grid_n=abc`` 此前 int() 裸解析 ValueError → 500 纯文本
    （A8-D 收编族漏网端点，campaign_app UX-B6 机械拆分时未跟进）。"""

    def test_grid_n_abc_400_envelope(self, client):
        r = client.get("/api/runs/whatever/dashboard?grid_n=abc")
        assert r.status_code == 400, r.text
        body = r.json()
        assert body["ok"] is False
        assert "grid_n" in body["errors"][0]

    def test_grid_n_empty_uses_default(self, client):
        # 空串/缺席=缺省 12（守卫缺省语义）→ 走 service（run 缺席=200 业务信封）
        r = client.get("/api/runs/whatever/dashboard?grid_n=")
        assert r.status_code == 200
        assert r.json()["ok"] is False  # "run 不存在"业务面，非参数 500

    def test_edb_and_runs_diff_have_no_numeric_query_params(self):
        # 同族自查（座位任务书）：edb_app.py/runs_diff.py 无裸 int()/float()
        # 查询参数（前者只透传 root 字符串，后者是纯 re-export 壳）。
        import ast

        for name in ("edb_app.py", "runs_diff.py"):
            src = (Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui"
                   / name).read_text(encoding="utf-8")
            tree = ast.parse(src)
            calls = [n for n in ast.walk(tree)
                     if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Name)
                     and n.func.id in ("int", "float")]
            assert not calls, f"{name} 出现裸 int()/float() 调用"


# ────────────────── P0-A：导入版本下拉 + 版本叙事 ──────────────────

class TestHfssImportVersionServerFace:
    """P0-A 服务端口径：缺省钉 2025.1 只在请求未带/空串 version 时生效
    （端到端链的 server 半边；前端半边见 TestImportUiVersionNarrative）。"""

    @pytest.fixture()
    def captured(self, monkeypatch):
        cap: dict = {}

        def _fake(project, design=None, version="__unset__", out=None):
            cap.update(project=project, design=design, version=version, out=out)
            return {"ok": True, "spec": {"variables": {}}, "recipe": {}}

        monkeypatch.setattr("rfauto.service.v3_services.hfss_import_recipe", _fake)
        return cap

    def test_default_import_uses_server_default_2025_1(self, client, captured):
        r = client.post("/api/hfss/import", json={"project": "p.aedt"})
        assert r.status_code == 200 and r.json()["ok"] is True
        assert captured["version"] == "2025.1"

    def test_empty_version_string_falls_back_to_default(self, client, captured):
        # 前端下拉空值不透传 version 键；即便直调带空串也归缺省钉（or 链）
        client.post("/api/hfss/import", json={"project": "p.aedt", "version": ""})
        assert captured["version"] == "2025.1"

    def test_explicit_version_passthrough(self, client, captured):
        client.post("/api/hfss/import", json={"project": "p.aedt", "version": "2024.2"})
        assert captured["version"] == "2024.2"


class TestImportUiVersionNarrative:
    """P0-A 前端半边（源码钉，与 test_w8d_ui_p2_followup 的 index.html 钉
    同口径；pages.js 属本席文件面）+ 四处版本旧叙事中性化（A6 P1-4）。"""

    def test_no_stale_version_literals(self):
        for stale in ("2023.1", "2026.1"):
            assert stale not in _PAGES, f"pages.js 残留旧版本字面 {stale!r}"

    def test_dropdown_defaults_to_server_default(self):
        # 缺省项=空值（跟随服务端缺省，不透传显式版本）+ 如实列出当前可用
        # 版本（本机实测 2025 R1/v251）+ 自定义输入框（无版本清单接口形态）
        # S1 发布令批：下拉展示文案迁词表（import.ver_default/ver_custom，
        # zh 值同笔）；value 协议哨兵（空值/2025.1/__custom__）钉不变
        assert ("<select id='imp-version'><option value=''>"
                '${t("import.ver_default")}</option>') in _PAGES
        assert "<option value='2025.1'>2025.1</option>" in _PAGES
        assert '<option value=\'__custom__\'>${t("import.ver_custom")}</option>' in _PAGES
        assert "imp-version-custom" in _PAGES
        # 自定义输入随下拉显隐
        assert 'T.$("imp-version").value === "__custom__"' in _PAGES

    def test_requests_omit_version_when_unset(self):
        # 两次导入请求（读取工程/保存草稿）都走条件装配：空值不带 version 键
        assert _PAGES.count("if (ver) body.version = ver;") == 2
        assert 'version: T.$("imp-version").value' not in _PAGES

    def test_stale_narrative_neutralized(self):
        # A6 P1-4 四处（dashboard 求解器 widget/guide FAQ/import help/solvers
        # help）统一中性化（照 index.html:795 已修脚注口径）
        for stale in ("verified 真机通道", "issue #7410", "已验证真机通道",
                      "已验证通道"):
            assert stale not in _PAGES, f"版本旧叙事残留: {stale!r}"
        assert _PAGES.count("以实装版本为准") >= 3


# ────────────────── P1-D：plotCard 图表生命周期 ──────────────────

class TestPlotCardLifecycle:
    """A6 P1-3：同容器重建先 dispose 旧实例+摘旧 resize 监听（壳层装配面
    node 不可驱——echarts/DOM 缺席，走源码钉惯例，同 test_ui_lifecycle）。"""

    def test_same_container_dispose_and_unbind_before_rebuild(self):
        assert "_plotShells = new WeakMap()" in _PLOTCARD  # 容器 → 实例壳
        assert "prevShell.chart.isDisposed()" in _PLOTCARD
        assert "prevShell.chart.dispose()" in _PLOTCARD
        assert ('window.removeEventListener("resize", prevShell.onResize)'
                in _PLOTCARD)

    def test_new_listener_has_dispose_guard_and_registry(self):
        assert "if (!chart.isDisposed()) chart.resize();" in _PLOTCARD
        assert 'window.addEventListener("resize", onResize)' in _PLOTCARD
        # UI-R5（2026-10-14）：壳登记改为 {chart, onResize, props, ctx} 记录
        # （复用路径换代 props / 主题联动重放消费；职责同前，登记形态加宽）
        assert "_plotShells.set(el, shell);" in _PLOTCARD

    def test_call_sites_untouched(self):
        # 座位约束：不改 12 个调用点（与 test_ui_plotcard/test_ui_lifecycle
        # 计数钉同源复述；本钉先红=包装入口被误改）
        assert _PAGES.count("T.plotCard(") == 16  # 12 + W3-S12 四管线逃生舱迁移


# ────────────────── P1-F：Mount(/runs) 非仓根 cwd 冒烟 ──────────────────

class TestRunsMountCwdSmoke:
    """A6 P1-5：Mount 目录此前字面 "runs" 相对 cwd——非仓库根目录
    ``rfauto ui`` 启动即 RuntimeError。改为与 service 层 RUNS_DIR 同源的
    绝对解析；目录缺席降级关闭挂载+stderr 提示（R2-B-05 缺省关语义）。"""

    def test_app_builds_without_runs_dir(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)  # 非仓库根 cwd 且无 runs/
        from rfauto.ui.server import create_ui_app

        app = create_ui_app(include_runs_mount=True)  # 此处曾 RuntimeError
        paths = [getattr(r, "path", "") for r in app.routes]
        assert "/runs" not in paths  # 降级：不挂载（对齐缺省关语义）
        assert "/api/runs" in paths  # API 面不受影响
        assert "runs" in capsys.readouterr().err  # stderr 提示

    def test_mount_serves_cwd_runs_dir(self, tmp_path, monkeypatch):
        runs = tmp_path / "runs"
        runs.mkdir()
        monkeypatch.chdir(tmp_path)
        from rfauto.ui.server import create_ui_app

        app = create_ui_app(include_runs_mount=True)
        assert "/runs" in [getattr(r, "path", "") for r in app.routes]
        (runs / "hello.txt").write_text("ok", encoding="utf-8")
        r = TestClient(app).get("/runs/hello.txt")
        assert r.status_code == 200 and r.text == "ok"

    def test_mount_dir_matches_service_runs_dir(self, tmp_path, monkeypatch):
        # 同源性：挂载目录=service 层 RUNS_DIR 的 cwd 绝对解析（同一进程内
        # 一个 runs 根口径——报告 P1-5 指出的双口径不一致清偿）
        runs = tmp_path / "runs"
        runs.mkdir()
        monkeypatch.chdir(tmp_path)
        from rfauto.service.ui_service import RUNS_DIR
        from rfauto.ui.server import create_ui_app

        create_ui_app(include_runs_mount=True)
        assert Path(RUNS_DIR).absolute() == runs


# ────────────────── 信封/守卫形状互证 ──────────────────

class TestGuardSingleSource:
    """守卫单源迁移后的引用路径保持（#116：re-export 不许尾部重定义）。"""

    def test_server_reexports_params_single_source(self):
        import rfauto.ui.params as params_mod
        import rfauto.ui.server as server_mod

        assert server_mod.ParamError is params_mod.ParamError
        assert server_mod._int_param is params_mod._int_param
        assert server_mod._json_body is params_mod._json_body

    def test_server_has_no_bare_request_json_left(self):
        # P0-C 清零钉：UI handler 面不再保留裸 await request.json() 调用点
        # （架构批 UI-R1 拆分后扫描面=ui 包全 .py，**除 params.py**——
        # 守卫单源 _json_body 自身的内部调用是合法实现面，docstring 提法
        # 亦非调用点；campaign_app/edb_app 实测零命中无需豁免）
        ui_dir = (Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui")
        src = "\n".join(
            p.read_text(encoding="utf-8") for p in sorted(ui_dir.rglob("*.py"))
            if p.name != "params.py")
        assert not re.findall(r"await request\.json\(\)", src)
        assert src.count("await _json_body(request)") >= 15
