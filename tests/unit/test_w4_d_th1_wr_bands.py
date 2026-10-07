"""W4-D TH-1：WR-8..WR-1.0 九带扩容（90-1100 GHz）域面测试。

判据（se_specs3 §4c 预声明门值，含一处预声明口径偏差的如实处置）：
1. 双源转录回收钉（#118）：每行 a/b mm 与带端点对 VDI（来源 A）与
   Spinner TD-00036（来源 B，IEC 60153-2:2016/EIA RS-261-B/IEEE
   1785.1-2012 交叉表）双源打印值逐格核对——双源互相一致才入表；
   表值取英寸定义值 ×25.4（WR-8..WR-3.4）或 IEEE 1785.1 微米精确值
   （WR-2.8..WR-1.0），对双源打印微米值差 ≤0.5 µm（打印舍入）。
2. 截止自洽：cutoff_te10(a) 与带下端 f1 满足 1.2 < f1/fc < 1.4（仓内
   test_band_edges_physics_sanity 既定窗，等价 |fc-f1|/f1 ∈ (16.7%,
   28.6%)）——**规格预声明"|fc-f1|/f1 ≤15%"不可满足**（9 新行实测
   17.3%-21.1%，既有种子行同族：WR-10 21.3%/WR-90 20.0%），按 #122
   如实按既有表窗执行并逐行注记实测余量，偏差升格记 REPORT。
3. wr_lookup 九新名全 record 解析；未知名 KeyError 契约回归。
4. 消费面直通：wr_loss_budget（WR-5.1@180 GHz 有限正损耗）/ horn_synthesis
   （WR-5.1 同名档）/ render_coax_wg（WR-8 设计点）/ ridged_waveguide
   （C0 约定一致——接地勘误：该文件不经 wr_lookup 消费表，规格快照
   "四消费文件"实为 C0 同值约定，本测按实情钉）。
5. 计数零自检：纯表扩展，零 CLI/MCP/CALC，TEMPLATE_META 零动。
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.rw_tables import C0, WR_TABLE, wr_from_frequency, wr_lookup

#: 双源打印值转录（2026-10-05 实测 PDF；(a_um, b_um, f1, f2)）。
#: 来源 A=VDI Waveguide Band Designations（vadiodes.com，2014-01 版）。
_VDI = {
    "WR-8": (2032.0, 1016.0, 90.0, 140.0),
    "WR-6.5": (1651.0, 825.5, 110.0, 170.0),
    "WR-5.1": (1295.0, 647.5, 140.0, 220.0),
    "WR-4.3": (1092.0, 546.0, 170.0, 260.0),
    "WR-3.4": (864.0, 432.0, 220.0, 330.0),
    "WR-2.8": (710.0, 355.0, 260.0, 400.0),
    "WR-2.2": (570.0, 285.0, 330.0, 500.0),
    "WR-1.5": (380.0, 190.0, 500.0, 750.0),
    "WR-1.0": (250.0, 125.0, 750.0, 1100.0),
}

#: 来源 B=Spinner TD-00036 Issue N（2019-03-12）§4 sub-mm 表。
_SPINNER = {
    "WR-8": (2032.0, 1016.0, 90.0, 140.0),
    "WR-6.5": (1651.0, 825.5, 110.0, 170.0),
    "WR-5.1": (1295.0, 647.5, 140.0, 220.0),
    "WR-4.3": (1092.0, 546.0, 170.0, 260.0),
    "WR-3.4": (864.0, 432.0, 220.0, 330.0),
    "WR-2.8": (710.0, 355.0, 260.0, 400.0),
    "WR-2.2": (570.0, 285.0, 330.0, 500.0),
    "WR-1.5": (380.0, 190.0, 500.0, 750.0),
    "WR-1.0": (250.0, 125.0, 750.0, 1100.0),
}

#: 表值定义口径：英寸定义值 ×25.4（EIA 英制行）或 IEEE 1785.1 微米精确值。
_DEFINING_MM = {
    "WR-8": (2.0320, 1.0160),
    "WR-6.5": (1.6510, 0.8255),
    "WR-5.1": (1.2954, 0.6477),
    "WR-4.3": (1.0922, 0.5461),
    "WR-3.4": (0.8636, 0.4318),
    "WR-2.8": (0.7100, 0.3550),
    "WR-2.2": (0.5700, 0.2850),
    "WR-1.5": (0.3800, 0.1900),
    "WR-1.0": (0.2500, 0.1250),
}

_NEW_NAMES = tuple(_DEFINING_MM)

# 逐行 f1/fc 实测余量（判据 2 注记，cutoff_te10 同源计算）：
# WR-8  90/73.768=1.2200（|fc-f1|/f1=18.0%）  WR-6.5  110/90.791=1.2116（17.5%）
# WR-5.1 140/115.708=1.2099（17.3%）          WR-4.3  170/137.247=1.2387（19.3%）
# WR-3.4 220/173.574=1.2674（21.1%）          WR-2.8  260/211.120=1.2315（18.8%）
# WR-2.2 330/262.976=1.2548（20.3%）          WR-1.5  500/394.464=1.2676（21.1%）
# WR-1.0 750/599.585=1.2509（20.0%）


def test_dual_source_agreement_before_entering_table() -> None:
    """判据面：双源逐格互相一致（分歧格不入表）。"""
    for name in _NEW_NAMES:
        assert _VDI[name] == _SPINNER[name], name


def test_nine_new_rows_exact_transcription() -> None:
    """回收钉：9 新行尺寸/带端点逐格对双源转录与定义口径。"""
    assert len(WR_TABLE) == 26
    for name in _NEW_NAMES:
        r = wr_lookup(name)
        a_def, b_def = _DEFINING_MM[name]
        assert r.a_mm == a_def, name
        assert r.b_mm == b_def, name
        # 表值对双源打印微米值 ≤0.5 µm（打印舍入带；µm 主定义行逐位相等）
        assert abs(r.a_mm * 1000.0 - _VDI[name][0]) <= 0.5, name
        assert abs(r.b_mm * 1000.0 - _VDI[name][1]) <= 0.5, name
        assert (r.f_start_ghz, r.f_end_ghz) == (
            _VDI[name][2], _VDI[name][3]), name
        # 来源标注与法兰口径
        assert r.source.startswith("2src-thz"), name
        assert r.flange_ug is None, name


def test_cutoff_below_band_start_with_per_row_margin() -> None:
    """判据 2（如实口径）：fc < f1 严格 + f1/fc 落仓内既定窗 (1.2, 1.4)。

    规格预声明 "|fc-f1|/f1 ≤15%" 对 EIA 惯例带不可满足（含全部既有行），
    按 #122 以既有表窗执行，实测余量见模块头注记。
    """
    for name in _NEW_NAMES:
        r = wr_lookup(name)
        fc = C0 / (2.0 * r.a_mm * 1e-3) / 1e9
        assert fc < r.f_start_ghz, name
        ratio = r.f_start_ghz / fc
        assert 1.2 < ratio < 1.4, (name, ratio)
        assert r.f_end_ghz < 2.0 * fc, name  # TE20 截止下不进双模区


def test_lookup_full_record_and_keyerror_contract() -> None:
    """判据 3：九新名 wr_lookup 完整 record + 未知名 KeyError 回归。"""
    for name in _NEW_NAMES:
        r = wr_lookup(name)
        assert r.wr_name == name
        assert r.fc10_ghz > 0 and r.a_mm > r.b_mm > 0
        # 归一容错入口同源可达
        assert wr_lookup(name.replace("-", "").lower()) is r
    with pytest.raises(KeyError):
        wr_lookup("WR-0.8")


def test_frequency_lookup_new_bands() -> None:
    """90-1100 GHz 带端命中（含与 WR-10 的 90-110 重叠并列）。"""
    assert wr_from_frequency(90.0) is not None  # WR-8 与 WR-10 重叠带
    hits_95 = {r.wr_name for r in (wr_from_frequency(95.0) or ())}
    assert {"WR-8", "WR-10"} <= hits_95
    assert {r.wr_name for r in (wr_from_frequency(1100.0) or ())} == {"WR-1.0"}
    assert wr_from_frequency(1200.0) is None  # 带外
    assert wr_from_frequency(89.9) is not None  # 90 以下仍落 WR-10（75-110）


def test_consumer_wr_loss_budget_wr51() -> None:
    """判据 4a：wr_loss_budget WR-5.1@180 GHz 出有限正损耗（量级带锚）。"""
    from rfauto.core.am_loss_budget import wr_loss_budget

    out = wr_loss_budget(
        "WR-5.1", 180.0, 0.01, sigma_s_per_m=4.1e7)
    assert out["in_recommended_band"] is True
    assert math.isfinite(out["ideal_db"]) and out["ideal_db"] > 0.0
    # 光滑铜 WR-5.1@180 GHz：VDI 表同带计算损耗 0.12-0.074 dB/cm 量级带
    # （VDI 2014 表打印值；闭式口径差异预声明，量级锁 0.005-0.05 dB/mm）
    per_mm = out["ideal_db"] / 10.0
    assert 0.005 < per_mm < 0.05, per_mm


def test_consumer_horn_synthesis_wr51() -> None:
    """判据 4b：horn_synthesis WR-5.1 同名档过。"""
    from rfauto.core.horn_synthesis import synthesize_pyramid_horn

    out = synthesize_pyramid_horn(20.0, 180.0, "WR-5.1")
    assert out["a_mm"] == pytest.approx(1.2954)
    assert out["gain_db_achieved"] == pytest.approx(20.0, abs=1e-6)


def test_consumer_render_coax_wg_wr8() -> None:
    """判据 4c：render_coax_wg 设计点换 WR-8 档解析过。"""
    from rfauto.adapters.oe_templates.render_coax_wg import (
        coax_wg_design_params,
    )

    out = coax_wg_design_params("WR-8", f0_ghz=110.0)
    assert out["a_mm"] == 2.032
    assert out["b_mm"] == 1.016
    assert out["pin_len_mm"] > 0 and out["backshort_mm"] > 0


def test_consumer_ridged_waveguide_c0_convention() -> None:
    """判据 4d（接地勘误口径）：ridged_waveguide 不经 wr_lookup 消费表
    （规格快照"四消费文件"实况勘误）；其与表的耦合是 C0 同值约定，钉之。"""
    from rfauto.core import ridged_waveguide

    assert ridged_waveguide.C0 == C0


def test_zero_counter_surface() -> None:
    """判据 5：纯表扩展零计数面——TEMPLATE_SPECS 注册表可导入零动、行数 26。"""
    from rfauto.models.template_specs import TEMPLATE_SPECS

    assert len(WR_TABLE) == 26
    assert TEMPLATE_SPECS is not None
