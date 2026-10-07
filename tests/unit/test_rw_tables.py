"""ME-4 WR 波导标准表单测（月度增强计划 ME-4）。

覆盖：主自洽判据（fc10==c/2a 恒等式扫全表 rtol 1e-9）、教科书锚
（WR-90/WR-28+自选 3 行 a/b/fc/带端点）、wr_lookup 容错与显式报错、
wr_from_frequency 带内/重叠并列/带外/边界/非法入参、λg 手算例
（f=2fc 闭式 2a/√3）与 f≤fc 显式 ValueError、bands 同构联动（字段名/
to_dict 键集对齐 BandEntry、只读不注册）、rwg_mmt.Waveguide 跨模块
截止频率一致性。
"""
from __future__ import annotations

import dataclasses
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import bands as bands_mod
from rfauto.core import rw_tables as rw
from rfauto.core.rw_tables import (
    C0,
    WR_TABLE,
    cutoff_te10,
    wavelength_g,
    wr_bands,
    wr_from_frequency,
    wr_lookup,
)

# 任务书点名的最低覆盖型号（8.2-40 GHz 主流 + mmWave 四行）
_REQUIRED_NAMES = {
    "WR-28", "WR-42", "WR-62", "WR-75", "WR-90", "WR-112",
    "WR-137", "WR-187", "WR-284", "WR-430",
    "WR-10", "WR-12", "WR-15", "WR-22",
}


def _norm(name: str) -> str:
    return name.strip().upper().replace("-", "").replace(" ", "").replace("_", "")


# ── 表结构与覆盖 ──────────────────────────────────────────────────────────────

def test_table_size_and_required_coverage() -> None:
    # TH-1（2026-10-05）：种子 17 行 + WR-8..WR-1.0 九行扩容，地板 15→26 防回退。
    assert len(WR_TABLE) >= 26
    names = {r.wr_name for r in WR_TABLE}
    assert names >= _REQUIRED_NAMES


def test_table_rows_structure() -> None:
    keys = [_norm(r.wr_name) for r in WR_TABLE]
    assert len(keys) == len(set(keys)), "型号归一后必须唯一"
    for r in WR_TABLE:
        assert math.isfinite(r.a_mm) and r.a_mm > 0
        assert math.isfinite(r.b_mm) and r.b_mm > 0
        assert r.b_mm < r.a_mm, "窄边必须小于宽边"
        assert 0.3 < r.b_mm / r.a_mm < 0.56, "标准矩形波导高宽比合理窗"
        assert math.isfinite(r.f_start_ghz) and math.isfinite(r.f_end_ghz)
        assert r.f_start_ghz < r.f_end_ghz
        assert r.source.startswith(("3src", "2src")), "逐行来源等级标注必填"
        assert "#" not in r.source, "数据行禁半角井号行内引注"


def test_band_edges_physics_sanity() -> None:
    """带端点物理合理性：下端高于 TE10 截止（~25% 规则窗）、上端低于 TE20 截止（=2·fc）。"""
    for r in WR_TABLE:
        ratio = r.f_start_ghz / r.fc10_ghz
        assert 1.2 < ratio < 1.4, f"{r.wr_name} 带下端/截止比 {ratio:.3f} 越出 ~25% 规则窗"
        assert r.f_end_ghz < 2.0 * r.fc10_ghz, f"{r.wr_name} 带上端进入 TE20 传播区"


# ── 主自洽判据：fc=c/2a 恒等式扫全表 ─────────────────────────────────────────

def test_fc10_identity_full_table() -> None:
    for r in WR_TABLE:
        fc_ref_ghz = C0 / (2.0 * r.a_mm * 1e-3) / 1e9
        assert math.isclose(r.fc10_ghz, fc_ref_ghz, rel_tol=1e-9), (
            f"{r.wr_name}: fc10_ghz={r.fc10_ghz} 违背 TE10 恒等式 {fc_ref_ghz}"
        )


def test_cross_module_rwg_mmt_consistency() -> None:
    """与 core/rwg_mmt.Waveguide（SI 米制）跨模块一致：fc_mn(1) == fc10。"""
    from rfauto.core.rwg_mmt import Waveguide

    for r in WR_TABLE:
        wg = Waveguide(a=r.a_mm * 1e-3, b=r.b_mm * 1e-3)
        assert math.isclose(wg.fc_mn(1), r.fc10_ghz * 1e9, rel_tol=1e-9), r.wr_name
        assert math.isclose(wg.fc_mn(2), 2.0 * r.fc10_ghz * 1e9, rel_tol=1e-9), r.wr_name


# ── 教科书锚（a/b/fc/带端点逐位；fc 经 venv Python 独立复核 c/2a）────────────

def test_anchor_wr90() -> None:
    r = wr_lookup("WR-90")
    assert r.a_mm == 22.86
    assert r.b_mm == 10.16
    assert round(r.fc10_ghz, 4) == 6.5571
    assert (r.f_start_ghz, r.f_end_ghz) == (8.2, 12.4)
    assert r.flange_ug == "UG-39/U"


def test_anchor_wr28() -> None:
    # 注：任务书锚写 fc=21.0772 GHz，与恒等式 c/2a 不符（a=7.112 mm 反推
    # 2a=c/f 得 7.11125 mm）；独立复核精确值 21.076523 GHz（4 位 21.0765，
    # 3 位 21.077 与 Pozar/维基教科书引用值一致）。按 1b 规以恒等式为准。
    r = wr_lookup("WR-28")
    assert r.a_mm == 7.112
    assert r.b_mm == 3.556
    assert round(r.fc10_ghz, 4) == 21.0765
    assert round(r.fc10_ghz, 3) == 21.077
    assert (r.f_start_ghz, r.f_end_ghz) == (26.5, 40.0)
    assert r.flange_ug == "UG-599/U"


def test_anchor_wr10() -> None:
    r = wr_lookup("WR-10")
    assert r.a_mm == 2.54
    assert r.b_mm == 1.27
    assert round(r.fc10_ghz, 4) == 59.0143
    assert (r.f_start_ghz, r.f_end_ghz) == (75.0, 110.0)
    assert r.flange_ug == "UG-387/U-M"


def test_anchor_wr62() -> None:
    r = wr_lookup("WR-62")
    assert r.a_mm == 15.7988
    assert r.b_mm == 7.8994
    assert round(r.fc10_ghz, 4) == 9.4878
    assert (r.f_start_ghz, r.f_end_ghz) == (12.4, 18.0)
    assert r.flange_ug == "UG-419/U"


def test_anchor_wr42() -> None:
    r = wr_lookup("WR-42")
    assert r.a_mm == 10.668
    assert r.b_mm == 4.318
    assert round(r.fc10_ghz, 4) == 14.0510
    assert (r.f_start_ghz, r.f_end_ghz) == (18.0, 26.5)
    assert r.flange_ug == "UG-595/U"


# ── wr_lookup 容错与显式报错 ─────────────────────────────────────────────────

def test_wr_lookup_case_and_prefix_tolerant() -> None:
    ref = wr_lookup("WR-90")
    for variant in ("wr90", "Wr-90", "WR_90", " wr-90 ", "WR 90", "90"):
        assert wr_lookup(variant) is ref, f"变体 {variant!r} 应解析到 WR-90"


def test_wr_lookup_unknown_raises() -> None:
    for bad in ("WR-999", "X90", "", "2"):
        with pytest.raises(KeyError):
            wr_lookup(bad)


def test_wr_lookup_non_string_raises() -> None:
    with pytest.raises(KeyError):
        wr_lookup(90)  # type: ignore[arg-type]


# ── wr_from_frequency：带内/重叠并列/带外/边界/非法入参 ──────────────────────

def test_wr_from_frequency_unique_hit() -> None:
    hits = wr_from_frequency(30.0)
    assert hits is not None and len(hits) == 1
    assert hits[0].wr_name == "WR-28"


def test_wr_from_frequency_overlap_explicit() -> None:
    # 9.5 GHz 同落 WR-112（7.05-10）与 WR-90（8.2-12.4）：重叠显式并列
    hits = wr_from_frequency(9.5)
    assert hits is not None
    assert {h.wr_name for h in hits} == {"WR-112", "WR-90"}


def test_wr_from_frequency_out_of_band_none() -> None:
    # TH-1 扩容后 118 GHz 已落 WR-6.5 推荐带（110-170）——带外探针上移到
    # 全表上端（WR-1.0 上端 1100 GHz）之外。
    assert wr_from_frequency(1200.0) is None  # 高于全表上端
    assert wr_from_frequency(1.0) is None  # 低于 WR-650 带下端


def test_wr_from_frequency_boundary_closed_interval() -> None:
    # 闭区间口径显式：端点频率命中全部共享该点的标准（12.4 为 WR-90 上端、
    # WR-75 带内、WR-62 下端三点共享，工程上任一皆可选，如实三行并列）
    hits_124 = wr_from_frequency(12.4)
    assert hits_124 is not None
    assert {h.wr_name for h in hits_124} == {"WR-90", "WR-75", "WR-62"}
    hits_265 = wr_from_frequency(26.5)
    assert hits_265 is not None
    assert {h.wr_name for h in hits_265} == {"WR-42", "WR-28"}


def test_wr_from_frequency_invalid_input() -> None:
    for bad in (0.0, -5.0, float("nan"), float("inf"), True):
        with pytest.raises(ValueError):
            wr_from_frequency(bad)


# ── cutoff_te10 / wavelength_g ──────────────────────────────────────────────

def test_cutoff_te10_exact_identity() -> None:
    assert math.isclose(cutoff_te10(0.02286), C0 / (2.0 * 0.02286), rel_tol=1e-12)
    assert math.isclose(cutoff_te10(0.007112) / 1e9, 21.076523, abs_tol=5e-5)


def test_cutoff_te10_invalid_input() -> None:
    for bad in (0.0, -0.01, float("nan"), float("inf"), True):
        with pytest.raises(ValueError):
            cutoff_te10(bad)


def test_wavelength_g_hand_case_two_fc() -> None:
    """f=2fc 手算例：λ0 恰为 a，λg = a/√(1−1/4) = 2a/√3（闭式独立推导）。"""
    fc90 = wr_lookup("WR-90").fc10_ghz
    lg = wavelength_g(2.0 * fc90, 22.86)
    expected = 2.0 * 22.86 / math.sqrt(3.0)
    assert math.isclose(lg, expected, rel_tol=1e-12)
    # 独立数值锚（venv Python 复核）：26.3965 mm（4 位）
    assert round(lg, 4) == 26.3965


def test_wavelength_g_numeric_anchor_x_band() -> None:
    """WR-90 @10 GHz：λg=39.7071 mm（β=√(k0²−kc²) 独立复核）。"""
    lg = wavelength_g(10.0, 22.86)
    assert round(lg, 4) == 39.7071
    lam0_mm = C0 / 10e9 * 1e3
    assert lg > lam0_mm, "导波波长恒大于自由空间波长"


def test_wavelength_g_high_frequency_approaches_lambda0() -> None:
    lg = wavelength_g(300.0, 22.86)
    lam0_mm = C0 / 300e9 * 1e3
    assert abs(lg - lam0_mm) / lam0_mm < 1e-3


def test_wavelength_g_below_cutoff_raises() -> None:
    with pytest.raises(ValueError):
        wavelength_g(5.0, 22.86)  # 5 GHz < fc=6.557 GHz
    with pytest.raises(ValueError):
        wavelength_g(wr_lookup("WR-90").fc10_ghz, 22.86)  # f==fc 同样拒绝
    with pytest.raises(ValueError):
        wavelength_g(float("nan"), 22.86)


# ── bands 联动：同构适配 + 只读不注册 ────────────────────────────────────────

def test_wr_bands_structural_isomorphism_with_band_entry() -> None:
    band_fields = [f.name for f in dataclasses.fields(bands_mod.BandEntry)]
    wr_fields = [f.name for f in dataclasses.fields(rw.WRBandEntry)]
    assert wr_fields == band_fields, "字段名须与 BandEntry 逐一 alignment"

    seed = bands_mod.get_band(bands_mod.band_keys()[0])
    assert set(seed.to_dict().keys()) == set(rw.WRBandEntry(
        key="k", standard="s", name="n",
        f_low_ghz=1.0, f_high_ghz=2.0,
    ).to_dict().keys()), "to_dict 键集须与 BandEntry.to_dict 对齐"


def test_wr_bands_values_and_readonly() -> None:
    keys_before = set(bands_mod.band_keys())
    entries = wr_bands()
    assert len(entries) == len(WR_TABLE)
    assert len({e.key for e in entries}) == len(entries), "适配键唯一"
    for entry, rec in zip(entries, WR_TABLE, strict=True):
        assert entry.key == _norm(rec.wr_name).lower() + "_waveguide"
        assert entry.f_low_ghz == rec.f_start_ghz
        assert entry.f_high_ghz == rec.f_end_ghz
        assert entry.kind == "waveguide"
        assert entry.source == rec.source
    # 只读消费：不写入 bands 注册表（禁改 bands.py 的行为面佐证）
    assert set(bands_mod.band_keys()) == keys_before
    assert "wr90_waveguide" not in bands_mod.band_keys()
    with pytest.raises(KeyError):
        bands_mod.get_band("wr90_waveguide")


def test_wr_bands_display_field_values() -> None:
    """wr_bands 展示字段逐值钉死（mutmut 盲区补测：key/频端之外此前零断言）。

    standard/name/region/notes 是 docs/UI 消费面契约（IEC 60153-2 引注、
    法兰注记分支），变异测试实证整字段置 None/篡改全部存活——值级钉死；
    fc10 四位小数值沿用 test_anchor_wr90/wr10 的 venv 独立复核锚。
    """
    entries = wr_bands()
    by_key = {e.key: e for e in entries}
    # standard：全行同一字符串（含 IEC 60153-2 引注字样）
    for entry in entries:
        assert entry.standard == "EIA WR 矩形波导标准尺寸系（IEC 60153-2 系）"
        assert "IEC 60153-2" in entry.standard
    # name："{型号} 推荐工作带 {f_low:g}-{f_high:g} GHz"（%g 格式：整数不带小数点）
    assert by_key["wr90_waveguide"].name == "WR-90 推荐工作带 8.2-12.4 GHz"
    assert by_key["wr10_waveguide"].name == "WR-10 推荐工作带 75-110 GHz"
    # region/kind 常量（region 非监管语义、"waveguide" 扩值契约）
    for entry in entries:
        assert entry.region == "global"
        assert entry.kind == "waveguide"
    # notes：TE10 截止（4 位小数）+ 法兰注记两分支（有法兰/无法兰行都覆盖）
    assert by_key["wr90_waveguide"].notes == (
        "TE10 截止 6.5571 GHz；物理波导标准推荐带（非监管频段）；法兰 UG-39/U"
    )
    assert by_key["wr10_waveguide"].notes == (
        "TE10 截止 59.0143 GHz；物理波导标准推荐带（非监管频段）；法兰 UG-387/U-M"
    )
    # 无法兰行（WR-12，fc12=48.3723 由 c/2a 恒等式独立复核）：无"；法兰"后缀
    assert by_key["wr12_waveguide"].notes == (
        "TE10 截止 48.3723 GHz；物理波导标准推荐带（非监管频段）"
    )
    # to_dict 透传这些字段（消费面走 dict）
    d90 = by_key["wr90_waveguide"].to_dict()
    assert d90["standard"] == by_key["wr90_waveguide"].standard
    assert d90["name"] == by_key["wr90_waveguide"].name
    assert d90["notes"] == by_key["wr90_waveguide"].notes


# ── 守卫消息体契约（mutmut B6-1 余量：23 条消息/参数名标签类变异）────────────

def test_guard_message_contract() -> None:
    """守卫与查表报错的消息体整串契约钉死（消息升级为对外契约）。

    背景（runs/mutmut_pilot/fix_report.md）：pytest.raises(ValueError) 裸
    raises 对消息体 XX 包裹类变异零判别力，23 条"守卫消息/参数名标签"变异
    因此假性存活。本测试把消息体按整串相等纳入契约（入参名/入参值/期望边界
    全部在消息内）；报文措辞变更必须连带改本测试——即消息消费方知情。
    断言取 exc.args[0]（KeyError 的 str() 会包引号，args[0] 才是原文）。
    """
    # _reject_non_positive_finite 两分支（经 cutoff_te10 透传，name="a_m"）
    with pytest.raises(ValueError) as exc_info:
        cutoff_te10(True)
    assert exc_info.value.args[0] == "a_m 必须为正有限数，得到 bool True"
    with pytest.raises(ValueError) as exc_info:
        cutoff_te10(0.0)
    assert exc_info.value.args[0] == "a_m 必须为正有限数，得到 0.0"
    # wavelength_g 参数名标签（f_ghz / a_mm）与无传播解消息（入参值+截止边界）
    with pytest.raises(ValueError) as exc_info:
        wavelength_g(-1.0, 22.86)
    assert exc_info.value.args[0] == "f_ghz 必须为正有限数，得到 -1.0"
    with pytest.raises(ValueError) as exc_info:
        wavelength_g(10.0, 0.0)
    assert exc_info.value.args[0] == "a_mm 必须为正有限数，得到 0.0"
    with pytest.raises(ValueError) as exc_info:
        wavelength_g(5.0, 22.86)
    fc_text = f"{C0 / (2.0 * 22.86e-3) / 1e9:.6f}"
    assert exc_info.value.args[0] == (
        f"f=5 GHz 不高于 TE10 截止 {fc_text} GHz（a=22.86 mm），无传播解")
    # wr_lookup 两路报错：非字符串类型名 + 未知名（含型号原文与可用清单）
    with pytest.raises(KeyError) as exc_info:
        wr_lookup(90)  # type: ignore[arg-type]
    assert exc_info.value.args[0] == "WR 型号必须为字符串，得到 int"
    with pytest.raises(KeyError) as exc_info:
        wr_lookup("WR-999")
    available = ", ".join(r.wr_name for r in WR_TABLE)
    assert exc_info.value.args[0] == (
        "未知 WR 型号 'WR-999'；可用型号：" + available)
    # wr_from_frequency 参数名标签（f_ghz，独立调用面）
    with pytest.raises(ValueError) as exc_info:
        wr_from_frequency(float("nan"))
    assert exc_info.value.args[0] == "f_ghz 必须为正有限数，得到 nan"
