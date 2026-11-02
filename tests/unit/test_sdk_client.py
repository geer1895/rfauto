"""RfautoClient 线形契约与错误路径缺口测试（aurora_n 零覆盖治理席，2026-10-30）。

W0-2 影响面映射曾把 service/sdk.py 误判 zero-coverage（映射器 ImportFrom
候选翻倍 bug + "sdk" 短 stem 被 grep 过滤；回归钉见 test_build_impact_map.py）。
实测 tests/unit/test_rest_api.py 直连消费覆盖 84%，本文件补齐其余缺口：

- 各端点方法可选参数 → 请求体/查询串的线形契约（记录型传输逐字段钉，
  含既有测试只走单侧的 if-true/false 分支）；
- HttpTransport 查询串拼接、JSON Content-Type、非 JSON 错误体兜底
  （urllib.request.urlopen 打桩，零真实网络——sdk 模块 docstring 设计口径）；
- _error_from 非信封兜底（HTTP {status} 形）与 openapi 非 2xx 抛错。
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from rfauto.service import sdk


class _RecordingTransport:
    """记录请求并回放统一成功信封（_Transport 协议最小实现）。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None, dict | None]] = []

    def request(self, method, path, *, params=None, json_body=None):
        self.calls.append((method, path, params, json_body))
        return 200, {"ok": True, "data": {"echo": True}}


class TestSdkWireFormat:
    def test_every_endpoint_full_optional_params_forwarded(self):
        """全端点"可选参数全给"形态：线形契约逐字段钉（true 分支面）。"""
        t = _RecordingTransport()
        c = sdk.RfautoClient(transport=t)

        assert c.list_runs(limit=5) == {"echo": True}
        assert c.list_calculators(include_experimental=False) == {"echo": True}
        assert c.calculate("k", {"a": 1}, allow_experimental=False) == {"echo": True}
        assert c.query_dataset(
            "d", where="a>1", columns=["x"], limit=3, model="m",
            study_name="s") == {"echo": True}
        assert c.dataset_coverage("d", bins=8) == {"echo": True}
        assert c.annotate_ground_truth("d", threshold=10) == {"echo": True}
        assert c.neural_operator_readiness("d", threshold=10) == {"echo": True}
        assert c.set_dataset_visibility("d", "public") == {"echo": True}
        assert c.export_hf_dataset(
            "d", license="cc-by-4.0", allow_private=True) == {"echo": True}
        assert c.register_public_dataset(
            "d", source="zenodo", license="cc-by-4.0", promote=True) == {"echo": True}
        assert c.db_query("SELECT 1", ["a"], limit=2, db_path="p") == {"echo": True}
        assert c.rag_query("q", top_k=3, runs_limit=7) == {"echo": True}
        assert c.rag_explain("q", top_k=3, runs_limit=7) == {"echo": True}
        assert c.discover_workdir("runs", ["a", "b"]) == {"echo": True}
        assert c.msl_slot_transition(
            2.4, 0.5, 4.4, 0.2, tan_d=0.02, z_msl_target=50.0) == {"echo": True}
        assert c.marchand_balun(
            2.4, 0.5, 4.4, 0.2, tan_d=0.02, z_msl_target=50.0) == {"echo": True}
        assert c.marchand_two_section(
            f0_ghz=2.4, z_unbal_ohm=50.0, z_bal_diff_ohm=100.0, er=4.4,
            h_mm=0.5, tan_d=0.02, s_min_mm=0.1, w_max_mm=1.0, z_c_ohm=70.0,
            band_ghz=[2.0, 3.0]) == {"echo": True}

        expected = [
            ("GET", "/api/v1/runs", {"limit": 5}, None),
            ("GET", "/api/v1/calculators", {"include_experimental": "false"}, None),
            ("POST", "/api/v1/calculators/k/run", None,
             {"params": {"a": 1}, "allow_experimental": False}),
            ("POST", "/api/v1/datasets/query", None,
             {"name": "d", "where": "a>1", "columns": ["x"], "limit": 3,
              "model": "m", "study_name": "s"}),
            ("POST", "/api/v1/datasets/coverage", None, {"name": "d", "bins": 8}),
            ("POST", "/api/v1/datasets/ground-truth/annotate", None,
             {"name": "d", "threshold": 10}),
            ("POST", "/api/v1/datasets/neural-operator-readiness", None,
             {"name": "d", "threshold": 10}),
            ("POST", "/api/v1/datasets/visibility", None,
             {"name": "d", "visibility": "public"}),
            ("POST", "/api/v1/datasets/export-hf", None,
             {"name": "d", "license": "cc-by-4.0", "allow_private": True}),
            ("POST", "/api/v1/datasets/public/register", None,
             {"name": "d", "source": "zenodo", "license": "cc-by-4.0",
              "promote": True}),
            ("POST", "/api/v1/db/query", None,
             {"sql": "SELECT 1", "params": ["a"], "limit": 2, "db_path": "p"}),
            ("POST", "/api/v1/rag/query", None,
             {"text": "q", "docs_dir": "docs", "runs_dir": "runs",
              "top_k": 3, "runs_limit": 7}),
            ("POST", "/api/v1/rag/explain", None,
             {"text": "q", "docs_dir": "docs", "runs_dir": "runs",
              "top_k": 3, "runs_limit": 7}),
            ("GET", "/api/v1/datasets/discover-workdir",
             {"runs_root": "runs", "models": "a,b"}, None),
            ("POST", "/api/v1/transitions/msl-slot", None,
             {"f0_ghz": 2.4, "h_mm": 0.5, "er": 4.4, "w_slot_mm": 0.2,
              "tan_d": 0.02, "z_msl_target": 50.0}),
            ("POST", "/api/v1/transitions/marchand-balun", None,
             {"f0_ghz": 2.4, "h_mm": 0.5, "er": 4.4, "w_slot_mm": 0.2,
              "tan_d": 0.02, "z_msl_target": 50.0}),
            ("POST", "/api/v1/transitions/marchand-two-section", None,
             {"f0_ghz": 2.4, "z_unbal_ohm": 50.0, "z_bal_diff_ohm": 100.0,
              "er": 4.4, "h_mm": 0.5, "tan_d": 0.02, "s_min_mm": 0.1,
              "w_max_mm": 1.0, "z_c_ohm": 70.0, "band_ghz": [2.0, 3.0]}),
        ]
        assert t.calls == expected

    def test_optional_params_omitted_keep_minimal_body(self):
        """全端点"可选参数全缺省"形态：请求体不含缺省键（false 分支面）。"""
        t = _RecordingTransport()
        c = sdk.RfautoClient(transport=t)

        assert c.dataset_coverage("d") == {"echo": True}
        assert c.annotate_ground_truth("d") == {"echo": True}
        assert c.marchand_balun(2.4, 0.5, 4.4, 0.2) == {"echo": True}
        assert c.marchand_two_section() == {"echo": True}

        assert t.calls == [
            ("POST", "/api/v1/datasets/coverage", None, {"name": "d"}),
            ("POST", "/api/v1/datasets/ground-truth/annotate", None,
             {"name": "d"}),
            ("POST", "/api/v1/transitions/marchand-balun", None,
             {"f0_ghz": 2.4, "h_mm": 0.5, "er": 4.4, "w_slot_mm": 0.2}),
            ("POST", "/api/v1/transitions/marchand-two-section", None, {}),
        ]


class TestSdkHttpTransport:
    """HttpTransport 线形面（urlopen 打桩，零真实网络）。"""

    def _install_fake(self, monkeypatch, handler):
        captured = {}

        def fake_urlopen(request, *args, **kwargs):
            captured["request"] = request
            return handler(request)

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        return captured

    def test_query_string_and_json_content_type(self, monkeypatch):
        class _FakeResponse:
            status = 200

            def __init__(self):
                self._body = json.dumps(
                    {"ok": True, "data": {"echo": True}}).encode("utf-8")

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        captured = self._install_fake(
            monkeypatch, lambda _req: _FakeResponse())
        c = sdk.RfautoClient(base_url="http://127.0.0.1:9999")
        c.list_calculators(include_experimental=False)
        assert (captured["request"].full_url ==
                "http://127.0.0.1:9999/api/v1/calculators"
                "?include_experimental=false")
        # GET 无 body：不写 Content-Type
        assert captured["request"].get_header("Content-type") is None

        c.calculate("k", {"a": 1})
        # POST 带 json body：Content-Type 逐字钉（urllib 存键首字母大写）
        assert (captured["request"].get_header("Content-type") ==
                "application/json")

    def test_non_json_error_body_falls_back_to_envelope(self, monkeypatch):
        """HTTPError 非 JSON 体：兜底重构 REST 错误信封喂 _error_from
        （test_rest_envelope_ratchet 结构性豁免台账同一条目）。"""

        def raise_http_error(request):
            raise urllib.error.HTTPError(
                request.full_url, 502, "Bad Gateway", {},
                io.BytesIO(b"<html>bad gateway</html>"))

        self._install_fake(monkeypatch, raise_http_error)
        c = sdk.RfautoClient(base_url="http://127.0.0.1:9999")
        with pytest.raises(sdk.RfautoApiError) as excinfo:
            c.health()
        assert excinfo.value.status_code == 502
        assert excinfo.value.code == "http_error"
        assert excinfo.value.message == "<html>bad gateway</html>"

    def test_empty_error_body_message_is_http_code(self, monkeypatch):
        """HTTPError 空 body：message 回退 "HTTP {code}"。"""

        def raise_http_error(request):
            raise urllib.error.HTTPError(
                request.full_url, 503, "Service Unavailable", {},
                io.BytesIO(b""))

        self._install_fake(monkeypatch, raise_http_error)
        c = sdk.RfautoClient(base_url="http://127.0.0.1:9999")
        with pytest.raises(sdk.RfautoApiError) as excinfo:
            c.health()
        assert excinfo.value.status_code == 503
        assert excinfo.value.code == "http_error"
        assert excinfo.value.message == "HTTP 503"


class TestSdkErrorPaths:
    def test_non_envelope_payload_raises_http_fallback(self):
        """状态 >=400 且 payload 无 error 信封：_error_from 兜底形态。"""
        t = _RecordingTransport()

        def reply(method, path, *, params=None, json_body=None):
            t.calls.append((method, path, params, json_body))
            return 400, {"unexpected": True}

        t.request = reply
        c = sdk.RfautoClient(transport=t)
        with pytest.raises(sdk.RfautoApiError) as excinfo:
            c.health()
        assert excinfo.value.status_code == 400
        assert excinfo.value.code == "http_error"
        assert excinfo.value.message == "HTTP 400"

    def test_non_dict_payload_raises_http_fallback(self):
        t = _RecordingTransport()

        def reply(method, path, *, params=None, json_body=None):
            t.calls.append((method, path, params, json_body))
            return 400, [1, 2]

        t.request = reply
        c = sdk.RfautoClient(transport=t)
        with pytest.raises(sdk.RfautoApiError) as excinfo:
            c.health()
        assert excinfo.value.status_code == 400
        assert excinfo.value.code == "http_error"
        assert excinfo.value.message == "HTTP 400"

    def test_openapi_non_2xx_raises(self):
        """openapi 不走 _call 信封解包：状态 >=400 直接抛。"""
        t = _RecordingTransport()

        def reply(method, path, *, params=None, json_body=None):
            t.calls.append((method, path, params, json_body))
            return 500, "<html>boom</html>"

        t.request = reply
        c = sdk.RfautoClient(transport=t)
        with pytest.raises(sdk.RfautoApiError) as excinfo:
            c.openapi()
        assert excinfo.value.status_code == 500
        assert excinfo.value.code == "http_error"
        assert excinfo.value.message == "HTTP 500"
        assert t.calls == [("GET", "/api/v1/openapi.json", None, None)]
