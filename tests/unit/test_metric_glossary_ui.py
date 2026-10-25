"""指标词典 REST 端点测试（aurora_i W2-S2，R3 设计 M2）。

照 test_edb_status_ui.py 先例（TestClient + create_ui_app，真仓资产只读
无 tmp 树诉求——词典是仓内静态知识文件非 runs 产物）：
- GET /api/metric-glossary          → 全量清单信封（39 键=38 数据湖键
  + q_factor 判读语义增补，aurora_k K2 2026-10-23）
单键查询走 service 层 get_metric（test_metric_glossary.TestMetricGlossary
Service 同笔）——REST 面不设未消费路由（UI 契约门 C 向只收不放）。
"""

from __future__ import annotations

import pytest

from rfauto.ui.server import create_ui_app


@pytest.fixture()
def client():
    from starlette.testclient import TestClient
    return TestClient(create_ui_app())


class TestMetricGlossaryEndpoints:
    def test_list_ok_envelope(self, client):
        r = client.get("/api/metric-glossary")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["count"] == 39  # 38 数据湖键 + q_factor 判读语义增补（aurora_k K2）
        assert body["schema"] == "metric-glossary/v1"
        assert "s11_db_max_in_band" in body["keys"]
        # 词条负载抽查：白话+判据+坑号三件在位（tooltip 数据契约）
        e = next(x for x in body["entries"]
                 if x["metric_id"] == "s11_db_max_in_band")
        assert e["plain_zh"].strip()
        assert e["good_when"].strip()
        assert "#195" in (e.get("pitfall_refs") or [])

    def test_single_key_route_absent(self):
        """REST 面无单键路由（消费面=前端全量拉取+service get_metric；
        未消费路由=UI 契约门 C 向违例，登记面只可删不可加）。"""
        import inspect

        from rfauto.ui import server as ui_server
        src = inspect.getsource(ui_server)
        assert "/api/metric-glossary/{key}" not in src

    def test_route_registered_once(self):
        """路由面单注册（照猫画虎 ui/server.py route 表；重复注册=星装
        多匹配歧义面）。"""
        import inspect

        from rfauto.ui import server as ui_server
        src = inspect.getsource(ui_server)
        assert src.count('"/api/metric-glossary"') == 1
