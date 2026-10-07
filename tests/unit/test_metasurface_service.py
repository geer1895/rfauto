"""W7 台账①态接线批 X3：metasurface_service（coding_metasurface 内核）单测。

接线面（2026-10-04，W7 台账行 3 coding_metasurface→新建 metasurface_service）：
- ``coding_pattern_summary``：编码矩阵 → 方向图摘要（峰位/量化损失理论档）；
- ``quant_loss_compute``：量化损失理论+实测双报。

裁判口径（#118 不自证）：全 0 码 (M×N) 方向图峰=|AF|max=M·N（均匀阵 DFT
恒等，normalize=False 独立键入）；量化损失理论档用公开文献锚 1-bit=3.92 dB
（sinc²(1/2^b) 口径，metasurface_lut 单源）；实测-理论收敛锚 |delta|≤0.05 dB
（core 大阵收敛锚口径，16×16 阵以内放宽带）；峰位 (u,v)=(0,0)（全 0 码
broadside 恒等）。信封纪律：errors 恒 list[str]、绝不抛异常；core 自身
测试（test_coding_metasurface）不重复。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.service.metasurface_service import (
    METASURFACE_SERVICE_SCHEMA_VERSION,
    coding_pattern_summary,
    quant_loss_compute,
)


class TestCodingPatternSummary:
    def test_uniform_code_peak_identity(self) -> None:
        """全 0 码 8×8：峰在 broadside (0,0)、peak=M·N=64（均匀阵 DFT 恒等）。"""
        out = coding_pattern_summary(
            [[0] * 8] * 8, 1, 5e-3, 10.0, pad=4, normalize=False)
        assert out["ok"] is True
        assert out["schema_version"] == METASURFACE_SERVICE_SCHEMA_VERSION
        res = out["result"]
        assert res["n_m"] == 8 and res["n_n"] == 8
        assert res["u_peak"] == pytest.approx(0.0, abs=1e-12)
        assert res["v_peak"] == pytest.approx(0.0, abs=1e-12)
        assert res["peak_abs"] == pytest.approx(64.0, rel=1e-9)
        # d/λ = 5mm·10GHz/c
        assert res["spacing_lambda"] == pytest.approx(
            5e-3 * 10e9 / 299792458.0, rel=1e-12)
        assert res["quant_loss_theory_db"] == pytest.approx(3.9224, abs=1e-3)
        assert out["provenance"]["kernel"] == "rfauto.core.coding_metasurface"

    def test_normalized_checkerboard_beam_off_broadside(self) -> None:
        """归一化棋盘码（2×2，1-bit）：峰归一 1、离开 broadside（相位梯度）。"""
        out = coding_pattern_summary([[0, 1], [1, 0]], 1, 5e-3, 10.0)
        assert out["ok"] is True
        res = out["result"]
        assert res["normalized"] is True
        assert res["peak_abs"] == pytest.approx(1.0, rel=1e-9)
        assert abs(res["u_peak"]) > 0.1  # 棋盘码主瓣离开 broadside

    def test_json_roundtrip(self) -> None:
        out = coding_pattern_summary([[0, 0], [0, 0]], 1, 5e-3, 10.0)
        revived = json.loads(json.dumps(out))
        assert revived == out


class TestQuantLossCompute:
    def test_theory_anchor_and_delta_band(self) -> None:
        """1-bit 理论=3.92 dB 公开锚；16×16 实测-理论 |delta|≤0.5 dB 收敛带。"""
        out = quant_loss_compute(16, 1, 0.3, 0.2, 5e-3, 10.0)
        assert out["ok"] is True
        res = out["result"]
        assert res["loss_theory_db"] == pytest.approx(3.9224, abs=1e-3)
        assert abs(res["delta_db"]) <= 0.5  # 大阵收敛锚（core 钉 ≤0.05 dB 放宽带）
        assert res["loss_measured_db"] > 0.0  # 正值=损失（口径）
        assert out["provenance"]["kernel"] == "rfauto.core.coding_metasurface"

    def test_two_bit_loss_below_one_bit(self) -> None:
        """2-bit 理论损失 < 1-bit（0.91 vs 3.92 dB，量化越细损失越低）。"""
        b1 = quant_loss_compute(16, 1, 0.3, 0.2, 5e-3, 10.0)
        b2 = quant_loss_compute(16, 2, 0.3, 0.2, 5e-3, 10.0)
        assert b2["result"]["loss_theory_db"] == pytest.approx(0.915, abs=1e-2)
        assert b2["result"]["loss_theory_db"] < b1["result"]["loss_theory_db"]


class TestEnvelopeDiscipline:
    def test_code_value_out_of_range_to_envelope(self) -> None:
        """1-bit 码矩阵含码值 5（越界）→ 内核 ValueError 折信封。"""
        out = coding_pattern_summary([[0, 5]], 1, 5e-3, 10.0)
        assert out["ok"] is False
        assert isinstance(out["errors"], list) and "码值越界" in out["errors"][0]

    def test_bool_bits_and_bad_matrix_shape_rejected(self) -> None:
        out = coding_pattern_summary([[0, 1], [1, 0]], True, 5e-3, 10.0)
        assert out["ok"] is False
        assert any("bits" in e for e in out["errors"])
        out2 = coding_pattern_summary([0, 1], 1, 5e-3, 10.0)  # 一维列表
        assert out2["ok"] is False
        assert any("code_matrix" in e for e in out2["errors"])

    def test_quant_loss_invalid_args_rejected(self) -> None:
        out = quant_loss_compute(0, 1, 0.3, 0.2, 5e-3, 10.0)  # n=0
        assert out["ok"] is False
        assert any("n_elements" in e for e in out["errors"])
        out2 = quant_loss_compute(16, 1, 2.0, 0.2, 5e-3, 10.0)  # u 越可见区
        assert out2["ok"] is False
        assert isinstance(out2["errors"], list) and out2["errors"]

    def test_non_positive_period_rejected(self) -> None:
        out = coding_pattern_summary([[0, 0]], 1, 0.0, 10.0)
        assert out["ok"] is False
        assert any("period_m" in e for e in out["errors"])


# ─── MCP 薄壳冒烟（facade 直调，单位换算锚 µm→m）────────────────────────────


def test_mcp_metasurface_tools_registered():
    import asyncio

    from rfauto.mcp_server import mcp

    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"metasurface_coding_pattern", "metasurface_quant_loss_db"} <= names


def test_mcp_metasurface_tools_callable_envelope():
    from rfauto.mcp_server import (
        metasurface_coding_pattern,
        metasurface_quant_loss_db,
    )

    out = metasurface_coding_pattern(
        [[0] * 8] * 8, bits=1, period_um=5000.0, f0_ghz=10.0,
        pad=4, normalize=False)
    assert out["ok"] is True
    assert out["result"]["peak_abs"] == pytest.approx(64.0, rel=1e-9)
    assert out["result"]["spacing_lambda"] == pytest.approx(
        5e-3 * 10e9 / 299792458.0, rel=1e-12)  # µm→m 薄壳换算
    ql = metasurface_quant_loss_db(
        n_elements=16, bits=1, u_beam=0.3, v_beam=0.2,
        period_um=5000.0, f0_ghz=10.0)
    assert ql["ok"] is True
    assert ql["result"]["loss_theory_db"] == pytest.approx(3.9224, abs=1e-3)
    # 非法入参 → ok=False 信封不抛出
    assert metasurface_coding_pattern(
        [[0, 5]], bits=1, period_um=5000.0, f0_ghz=10.0)["ok"] is False
    assert metasurface_quant_loss_db(
        n_elements=0, bits=1, u_beam=0.3, v_beam=0.2,
        period_um=5000.0, f0_ghz=10.0)["ok"] is False
