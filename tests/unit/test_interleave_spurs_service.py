"""W7 台账①态接线批 X3：adc_budget_service 扩面（interleave_spurs 内核）单测。

接线面（2026-10-04，W7 台账行 5 interleave_spurs→adc_budget_service）：
- ``interleave_spur_table_compute``：M 路交错 ADC 失配杂散表薄消费；
- ``jitter_budget_compute``：JESD204C 确定性抖动预算薄消费。

裁判口径（#118 不自证）：杂散位置锚用交错经典结论独立键入——M=2 时
fs/2±fin 折叠、M=4 时 fs/4±fin（core 模块 docstring 钉值）；Q(BER) 用
公开习惯值 Q(1e-12)≈7.0345（scipy 数值权威的公开对照）；SNR 换算
20log10(1/(2·TJ)) 手算回收。信封纪律：errors 恒 list[str]、绝不抛异常
（service 契约），core 内核自身测试（test_dr_stream_seat6 等）不重复。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.service.adc_budget_service import (
    ADC_BUDGET_SERVICE_SCHEMA_VERSION,
    interleave_spur_table_compute,
    jitter_budget_compute,
)

# ─── 功能小算例（杂散位置独立键入锚）────────────────────────────────────────


class TestInterleaveSpurTable:
    def test_m2_classic_spurs_fold_to_nyquist(self) -> None:
        """M=2：杂散族 fs/2±fin（交错经典位置，独立键入锚）。

        fs=4 GHz、fin=1 GHz：raw 候选 3 GHz（=fs/2+fin）与 1 GHz（=fs/2−fin），
        3 GHz 折叠进第一奈奎斯特区后 =1 GHz——两raw 折叠重合，表内恰 1 行
        （内核按折叠频率去重，首见 k=1 侧保留）。
        """
        out = interleave_spur_table_compute(
            {"fs_hz": 4e9, "fin_hz": 1e9, "n_lanes": 2})
        assert out["ok"] is True
        assert out["schema_version"] == ADC_BUDGET_SERVICE_SCHEMA_VERSION
        res = out["result"]
        assert res["ok"] is True
        assert res["n_lanes"] == 2
        assert res["nyquist_hz"] == 2e9
        freqs = [row["freq_hz"] for row in res["spurs"]]
        # fs/2±fin = 3 GHz / 1 GHz，3 GHz 折叠 |3−4|=1 GHz → 恒 1 GHz
        assert freqs == [1e9]
        assert out["provenance"]["kernel"] == "rfauto.core.interleave_spurs"

    def test_m4_spurs_at_fs4(self) -> None:
        """M=4：fs/4±fin（交错经典位置）；折叠重合的杂散按内核口径去重。"""
        fs, fin = 4e9, 0.5e9
        out = interleave_spur_table_compute(
            {"fs_hz": fs, "fin_hz": fin, "n_lanes": 4, "n_orders": 2})
        assert out["ok"] is True
        res = out["result"]
        # k=1：fs/4±fin = 1±0.5 → 0.5 / 1.5 GHz；k=2：2±0.5 → 1.5（与 k=1+
        # 折叠重合，去重）/ 2.5 GHz（折叠 |2.5−4|=1.5 GHz，亦重合去重）
        assert res["n_spurs"] == 2
        assert [r["freq_hz"] for r in res["spurs"]] == [0.5e9, 1.5e9]
        labels = {r["label"] for r in res["spurs"]}
        assert labels == {"IM1-", "IM1+"}

    def test_json_roundtrip(self) -> None:
        """结果 JSON 可序列化（service 层 JSON 进出契约）。"""
        out = interleave_spur_table_compute(
            {"fs_hz": 4e9, "fin_hz": 1e9, "n_lanes": 2})
        revived = json.loads(json.dumps(out))
        assert revived == out


# ─── 抖动预算（Q/SNR 手算回收）──────────────────────────────────────────────


class TestJitterBudget:
    def test_tj_snr_handcalc_recovery(self) -> None:
        """TJ=Q·RJ+DJ 与 SNR=20log10(1/(2TJ)) 手算回收（Q(1e-12) 公开值）。"""
        out = jitter_budget_compute({"rj_rms_ui": 0.01, "dj_ui": 0.05})
        assert out["ok"] is True
        res = out["result"]
        assert res["q_factor"] == pytest.approx(7.0345, abs=1e-3)
        tj = 7.0345 * 0.01 + 0.05
        assert res["tj_ui"] == pytest.approx(tj, rel=1e-3)
        assert res["snr_db"] == pytest.approx(
            20.0 * math.log10(1.0 / (2.0 * tj)), rel=1e-3)

    def test_dj_dominates_linear_identity(self) -> None:
        """RJ=0 时 TJ=DJ 线性恒等（独立键入手算）。"""
        out = jitter_budget_compute({"rj_rms_ui": 0.0, "dj_ui": 0.1, "ber": 1e-15})
        assert out["ok"] is True
        res = out["result"]
        assert res["tj_ui"] == pytest.approx(0.1, rel=1e-12)
        assert res["snr_db"] == pytest.approx(20.0 * math.log10(5.0), rel=1e-12)
        assert res["ber"] == 1e-15


# ─── 信封/边界（errors 恒 list、绝不抛）─────────────────────────────────────


class TestEnvelopeDiscipline:
    def test_missing_and_bad_fields_collect_errors(self) -> None:
        """缺键/负值/bool 污染逐字段收集进 errors（不抛异常）。"""
        out = interleave_spur_table_compute({"fs_hz": -1.0})
        assert out["ok"] is False
        assert isinstance(out["errors"], list)
        joined = " ".join(out["errors"])
        assert "fs_hz" in joined and "fin_hz" in joined and "n_lanes" in joined

    def test_bool_rejected_for_n_lanes(self) -> None:
        out = interleave_spur_table_compute(
            {"fs_hz": 4e9, "fin_hz": 1e9, "n_lanes": True})
        assert out["ok"] is False
        assert any("bool" in e for e in out["errors"])

    def test_kernel_domain_errors_fold_to_envelope(self) -> None:
        """内核 ValueError（fin≥fs/2 / RJ=DJ=0）转 ok=False 不抛。"""
        out = interleave_spur_table_compute(
            {"fs_hz": 2e9, "fin_hz": 1.5e9, "n_lanes": 2})
        assert out["ok"] is False
        assert any("奈奎斯特" in e for e in out["errors"])
        out2 = jitter_budget_compute({"rj_rms_ui": 0.0, "dj_ui": 0.0})
        assert out2["ok"] is False
        assert any("TJ" in e for e in out2["errors"])

    def test_non_object_payload_rejected(self) -> None:
        for bad in ("str", 42, [1, 2], None):
            out = interleave_spur_table_compute(bad)
            assert out["ok"] is False
            assert "JSON 对象" in out["errors"][0]


# ─── MCP 薄壳冒烟（facade 直调，单位换算 MHz→Hz 锚）─────────────────────────


def test_mcp_adc_tools_registered():
    import asyncio

    from rfauto.mcp_server import mcp

    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"adc_interleave_spurs", "jitter_budget_snr"} <= names


def test_mcp_adc_tools_callable_envelope():
    from rfauto.mcp_server import adc_interleave_spurs, jitter_budget_snr

    out = adc_interleave_spurs(fs_mhz=4000.0, fin_mhz=1000.0, n_lanes=2)
    assert out["ok"] is True
    assert out["result"]["fs_hz"] == pytest.approx(4e9)  # MHz→Hz 薄壳换算
    assert [r["freq_hz"] for r in out["result"]["spurs"]] == [1e9]
    jb = jitter_budget_snr(rj_rms_ui=0.01, dj_ui=0.05)
    assert jb["ok"] is True
    assert jb["result"]["snr_db"] == pytest.approx(12.3709, abs=1e-3)
    # 非法入参 → ok=False 信封不抛出（不炸会话）
    assert adc_interleave_spurs(fs_mhz=-1.0, fin_mhz=1.0, n_lanes=2)["ok"] is False
    assert jitter_budget_snr(rj_rms_ui=-0.1, dj_ui=0.0)["ok"] is False
