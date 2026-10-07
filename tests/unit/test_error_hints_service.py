"""XC 错误信息工程锚树（错误消息→可行动提示映射层）。

判据：映射表条目全部对**本仓真实错误指纹**（内核守卫/引擎报错原文）；
命中=子串或正则匹配；severity 排序 error<warn；未命中如实空表；
零 I/O 零物理数字（提示内阈值指回内核守卫原文）。
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.service import error_hints_service as eh


class TestKnownFingerprints:
    def test_mesh_guard_message(self):
        # render_siw 真实守卫原文（本席接地探针实测复现过）
        msg = ("siw_layout: 网格欠分辨——过孔直径 d=0.6mm < 4·NEAR=1mm"
               "（BASE=1mm；收紧 mesh_resolution_mm）")
        out = eh.hint_for_message(msg)
        assert out["ok"] is True
        assert out["n_hits"] >= 1
        assert any("#311" in h["refs"] for h in out["hits"])

    def test_s11_truncation_family(self):
        out = eh.hint_for_message("max |S11| = 1.32 > 1 非物理（FC 窗截断）")
        assert out["n_hits"] >= 1
        assert any("#262" in h["refs"] for h in out["hits"])
        assert all(h["severity"] in ("error", "warn") for h in out["hits"])

    def test_grpc_exception_regex(self):
        exc = RuntimeError("GrpcApiError: export timed out")
        out = eh.hint_for_exception(exc)
        assert out["exception_type"] == "RuntimeError"
        assert any("outdir" in h["hint"] for h in out["hits"])

    def test_compose_guard(self):
        out = eh.hint_for_message("P3 阻抗失配（p_a→p_b）：z_ref=50Ω vs 40Ω")
        assert out["n_hits"] >= 1
        assert "allow_mismatch" in out["hits"][0]["hint"]

    def test_precision_kernel_hint(self):
        out = eh.hint_for_message(
            "精度档案无 kernel 'nope'（可用: [...]）")
        assert out["n_hits"] >= 1
        assert "precision_profiles" in out["hits"][0]["refs"]

    def test_severity_ordering_error_first(self):
        # 同时命中 error（网格欠分辨）与 warn（|S11|）→ error 在前
        msg = "网格欠分辨 …… |S11| 越界附记"
        out = eh.hint_for_message(msg)
        sevs = [h["severity"] for h in out["hits"]]
        assert sevs == sorted(sevs, key=lambda s: {"error": 0, "warn": 1,
                                                   "info": 2}[s])


class TestHonesty:
    def test_unknown_message_empty_hits(self):
        out = eh.hint_for_message("完全未知的新错误 XYZZY")
        assert out["ok"] is True
        assert out["hits"] == []
        assert out["n_hits"] == 0

    def test_non_string_rejected(self):
        out = eh.hint_for_message(123)
        assert out["ok"] is False


class TestRegistry:
    def test_rules_all_have_hint_and_refs(self):
        out = eh.list_hint_rules()
        assert out["ok"] is True
        assert out["n_rules"] >= 10
        for rule in out["rules"]:
            assert rule["hint"] and rule["refs"]
            assert rule["severity"] in ("error", "warn", "info")
            assert rule["match"] in ("substring", "regex")

    def test_regex_branch_actually_used(self):
        assert any(r["match"] == "regex" for r in eh.list_hint_rules()["rules"])
