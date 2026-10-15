"""EDB 快车道状态页单测：/api/edb_status 端点 + edb_app 薄壳契约。

照 test_campaign_queue_ui.py 先例（TestClient + tmp 资产树 chdir 隔离，
#144）：service/edb_lane_service.edb_status 纯离线文件扫描，fake 资产树
即 fake service 数据面；另钉 handler 薄壳两条——服务 error 信封原样透传
（不吞不包装）、server re-export 与 edb_app 同一对象（UX-B6 同款身份钉）。
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest


@pytest.fixture()
def edb_root(tmp_path, monkeypatch):
    """tmp runs/edb_lane fake 资产树（chdir 隔离，#144）。"""
    monkeypatch.chdir(tmp_path)
    d = tmp_path / "runs" / "edb_lane"
    d.mkdir(parents=True)
    (d / "bl.aedb").mkdir()
    (d / "bl_config.json").write_text("{}", encoding="utf-8")
    (d / "ansysedt_batch_bl.log").write_text("x", encoding="utf-8")
    (d / "bl_export.s4p").write_text("!", encoding="utf-8")
    return d


@pytest.fixture()
def client(edb_root):
    from starlette.testclient import TestClient

    from rfauto.ui.server import create_ui_app

    return TestClient(create_ui_app())


class TestEdbStatusEndpoint:
    def test_lists_lane_assets(self, client, edb_root):
        r = client.get("/api/edb_status").json()
        assert r["ok"] is True
        # 信封 root=查询参原样（Path 分隔符归一，服务不解析绝对路径）
        assert r["root"] == str(Path("runs") / "edb_lane")
        assert r["n_projects"] == 1
        (row,) = r["items"]
        assert row["stem"] == "bl"
        assert row["aedb"] == str(Path("runs") / "edb_lane" / "bl.aedb")
        assert row["config_json"] == str(
            Path("runs") / "edb_lane" / "bl_config.json")
        assert row["solved"] is True
        assert row["touchstone"] == str(
            Path("runs") / "edb_lane" / "bl_export.s4p")
        # 五族模板能力面随信封透出（免试错发现能力；四支持族+lange 声明不支持）
        got = {t["template"] for t in r["templates"]}
        assert {"edb_branchline", "edb_coupled_line", "edb_power_divider",
                "edb_ratrace", "edb_lange"} <= got

    def test_root_query_param_passthrough(self, client, edb_root, tmp_path):
        other = tmp_path / "runs" / "other_lane"
        other.mkdir()
        (other / "pd_export.s2p").write_text("!", encoding="utf-8")
        r = client.get("/api/edb_status?root=runs/other_lane").json()
        assert r["ok"] is True and r["n_projects"] == 1
        (row,) = r["items"]
        assert row["stem"] == "pd"
        assert row["touchstone"] == str(
            Path("runs") / "other_lane" / "pd_export.s2p")

    def test_missing_root_ok_empty(self, client):
        """目录不存在=服务契约 ok True+空表（不臆造，handler 不改判）。"""
        r = client.get("/api/edb_status?root=runs/no_such_lane").json()
        assert r["ok"] is True
        assert r["n_projects"] == 0 and r["items"] == []

    def test_service_error_envelope_passthrough(self, client, monkeypatch):
        """薄壳不改判：服务 error 信封原样 JSON 透传（不抛裸异常炸会话）。"""
        from rfauto.service import edb_lane_service as lane

        def fake(root):
            return {"ok": False, "errors": [f"产物根目录不可读: {root}"],
                    "root": str(root)}

        monkeypatch.setattr(lane, "edb_status", fake)
        r = client.get("/api/edb_status").json()
        assert r["ok"] is False
        assert r["errors"] == ["产物根目录不可读: runs/edb_lane"]


class TestEdbAppThinShell:
    def test_module_structure(self):
        from rfauto.ui import edb_app

        assert inspect.iscoroutinefunction(edb_app.api_edb_status)

    def test_server_reexport_identity(self):
        """薄壳 re-export 同一性：server 拿到的就是 edb_app 定义的对象。"""
        from rfauto.ui import edb_app, server

        assert server.api_edb_status is edb_app.api_edb_status


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
