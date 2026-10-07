"""MA-7 材料库工程内核单测（round17 §六 MA-7）。

裁判口径（#118/#122 先行）：数据表值不进物理判据——本文件钉的是
**schema 结构、域守卫、插值代数恒等与来源等级诚实位**：
- 插值恒等：中点线性精确回收、端点逐位、域外显式报错（extrapolate
  forbidden 锚先例）、单点表语义。
- 温度模型：T=T_ref 逐位回收、线性系数代数锚（测试侧独立推导）。
- 数据诚实位：全部官方条目 source_level 在枚举内且带非空 sources；
  FR-4 generic 走 UNVERIFIED_band 且**无** dk_design（design 档取用
  显式报错，不冒充）。
- 跨面一致性：RO4350B design Dk 3.66 与本仓 configs/materials.yaml
  epsilon_r（2026-09-25 verified-web）逐位一致（第三方面互证）；
  C10D 锚 id 与 core/anchors.EXPECTED_ANCHORS 注册集一致。
- 推荐器：确定性排序（主序 dk 相对差、次序 tanδ、末序 id）、
  max_df 硬过滤、UNVERIFIED 标记透传。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import material_library as mlib
from rfauto.core.materials import load_materials_yaml

# ─── 测试侧独立常量（手算，非被测实现产物）───────────────────────────────────
# Dk(T)=Dk·(1+tc·1e-6·(T−T_ref))：3.0·(1+(−3e-6)·(123−23)) = 3.0·(1−3e-4)
DK_T_ANCHOR = 2.9991


# ─── schema 与数据诚实位 ─────────────────────────────────────────────────────


def test_all_entries_pass_schema_validation():
    assert len(mlib.VENDOR_LAMINATES) == 7
    for key, entry in mlib.VENDOR_LAMINATES.items():
        assert mlib.validate_material_entry(entry) is entry
        assert entry["id"] == key
        assert entry["sources"], f"{key} sources 不得为空"


def test_source_levels_within_enum():
    for entry in mlib.VENDOR_LAMINATES.values():
        assert entry["source_level"] in mlib.SOURCE_LEVELS
        dk_d = entry.get("dk_design")
        if dk_d is not None:
            assert dk_d.get("source_level", entry["source_level"]) in (
                mlib.SOURCE_DATASHEET_VERIFIED,
                mlib.SOURCE_WEB_VERIFIED,
                mlib.SOURCE_REPO_VERIFIED_WEB,
            )


def test_official_rogers_entries_not_unverified():
    for key in ("rogers_ro3003", "rogers_ro3035", "rogers_ro3006",
                "rogers_ro3010", "rogers_ro4003c", "rogers_ro4350b"):
        entry = mlib.get_laminate(key)
        assert entry["status"]["unverified"] is False
        # 官方条目必须双源（datasheet+web 或 web+repo 互证）
        assert len(entry["sources"]) >= 2, f"{key} 单源不合规（双源核对口径）"


def test_fr4_unverified_band_honesty():
    entry = mlib.get_laminate("fr4_generic")
    assert entry["status"]["unverified"] is True
    assert entry["source_level"] == mlib.SOURCE_UNVERIFIED_BAND
    assert "dk_design" not in entry  # 带值条目不冒充 Design 值（#118）
    with pytest.raises(ValueError, match="未登记 dk_design"):
        mlib.laminate_dk("fr4_generic", dk_kind="design")
    band = mlib.dk_tolerance_band("fr4_generic")
    assert band["kind"] == "band"
    assert band["low"] == pytest.approx(4.2)
    assert band["high"] == pytest.approx(4.8)


def test_validate_rejects_bad_entries():
    good = dict(mlib.get_laminate("rogers_ro3035"))
    # 非法来源等级
    bad = dict(good, id="x1", source_level="made_up_level")
    with pytest.raises(ValueError, match="source_level"):
        mlib.validate_material_entry(bad)
    # design 档禁二手来源冒充
    bad2 = json.loads(json.dumps(good))
    bad2["id"] = "x2"
    bad2["dk_design"]["source_level"] = mlib.SOURCE_LITERATURE_SECONDARY
    with pytest.raises(ValueError, match="禁二手"):
        mlib.validate_material_entry(bad2)
    # 容差负数
    bad3 = json.loads(json.dumps(good))
    bad3["id"] = "x3"
    bad3["dk_process"]["tol"] = -0.01
    with pytest.raises(ValueError, match="tol"):
        mlib.validate_material_entry(bad3)
    # 频点表频率重复（冲突值禁同表并存）
    bad4 = json.loads(json.dumps(good))
    bad4["id"] = "x4"
    bad4["dk_vs_f"] = [
        {"f_ghz": 10.0, "value": 3.5},
        {"f_ghz": 10.0, "value": 3.6},
    ]
    with pytest.raises(ValueError, match="频率重复"):
        mlib.validate_material_entry(bad4)
    # bool 拒收（df7+⑯）——深拷贝构造，禁污染 VENDOR_LAMINATES 共享嵌套 dict
    bad5 = json.loads(json.dumps(good))
    bad5["id"] = "x5"
    bad5["dk_process"]["tol"] = True
    with pytest.raises(ValueError, match="bool"):
        mlib.validate_material_entry(bad5)
    # 非法 f_band（lo>=hi）
    bad6 = json.loads(json.dumps(good))
    bad6["id"] = "x6"
    bad6["dk_design"]["f_band_ghz"] = [40.0, 8.0]
    with pytest.raises(ValueError, match="lo<hi"):
        mlib.validate_material_entry(bad6)


def test_get_laminate_unknown_id_raises():
    with pytest.raises(KeyError, match="未知板材"):
        mlib.get_laminate("no_such_board")


def test_list_laminates_sorted_and_complete():
    rows = mlib.list_laminates()
    assert [r["id"] for r in rows] == sorted(mlib.VENDOR_LAMINATES)
    assert len(rows) == len(mlib.VENDOR_LAMINATES)
    assert all({"id", "vendor", "product", "source_level",
                "unverified"} <= set(r) for r in rows)


# ─── 跨面一致性（本仓既档 verified-web 三方互证）────────────────────────────


def test_ro4350b_design_dk_matches_repo_materials_yaml():
    """库内 design Dk 与 configs/materials.yaml epsilon_r 逐位一致。"""
    data = load_materials_yaml()
    mat = data["materials"]["rogers4350b_h0.508"]
    dk = mlib.laminate_dk("rogers_ro4350b")
    assert dk["dk"] == float(mat["epsilon_r"]) == pytest.approx(3.66)
    proc = mlib.laminate_dk("rogers_ro4350b", dk_kind="process")
    assert proc["dk"] == pytest.approx(3.48)
    assert proc["f_within_design_domain"] is None  # 无官方频带声明→如实 None


def test_ro3003_datasheet_values():
    dk = mlib.laminate_dk("rogers_ro3003")
    assert dk["dk"] == pytest.approx(3.00)
    assert dk["f_band_ghz"] == [8.0, 40.0]
    proc = mlib.laminate_dk("rogers_ro3003", dk_kind="process")
    assert proc["dk"] == pytest.approx(3.00)
    df = mlib.laminate_df("rogers_ro3003")
    assert df["df"] == pytest.approx(0.0010)


def test_ro3003_conflict_notes_recorded_not_silently_resolved():
    entry = mlib.get_laminate("rogers_ro3003")
    notes = entry["status"]["conflict_notes"]
    assert any("3.1629" in n for n in notes), "官网工具 Design 值须记冲突"
    assert any("0.047" in n for n in notes), "页面容差歧义须记冲突"


# ─── 频域域守卫（Design Dk 锚语义）──────────────────────────────────────────


def test_design_domain_guard_forbids_78ghz_extrapolation():
    """datasheet design 域 8–40 GHz 出域（78GHz）必须显式报错并指锚。"""
    with pytest.raises(ValueError, match="ro3003-oe-hfss-v2"):
        mlib.laminate_dk("rogers_ro3003", f_ghz=78.0)
    # 域内合法
    ok = mlib.laminate_dk("rogers_ro3003", f_ghz=10.0)
    assert ok["f_within_design_domain"] is True
    assert ok["dk"] == pytest.approx(3.00)
    # 域端点合法（8/40 GHz）
    assert mlib.laminate_dk("rogers_ro3003", f_ghz=8.0)["f_within_design_domain"] is True
    assert mlib.laminate_dk("rogers_ro3003", f_ghz=40.0)["f_within_design_domain"] is True


def test_process_kind_has_no_frequency_domain_semantics():
    """process 档只回测量点标注（process 值无官方频带语义，不设域守卫）。"""
    out = mlib.laminate_dk("rogers_ro3003", f_ghz=78.0, dk_kind="process")
    assert out["dk"] == pytest.approx(3.00)
    assert out["f_within_design_domain"] is None
    assert out["measured_f_ghz"] == pytest.approx(10.0)


# ─── 频点表插值恒等 ──────────────────────────────────────────────────────────


_TABLE = [
    {"f_ghz": 1.0, "value": 3.0},
    {"f_ghz": 10.0, "value": 3.16},
    {"f_ghz": 40.0, "value": 3.20},
]


def test_interpolate_midpoint_exact_linear():
    # (1,3.0)-(10,3.16)：f=5.5 → 3.0+0.16·4.5/9 = 3.08（手算锚）
    assert mlib.interpolate_vs_frequency(_TABLE, 5.5) == pytest.approx(3.08)
    assert mlib.interpolate_vs_frequency(_TABLE, 25.0) == pytest.approx(
        3.16 + (3.20 - 3.16) * 15.0 / 30.0)


def test_interpolate_endpoints_bitwise():
    assert mlib.interpolate_vs_frequency(_TABLE, 1.0) == 3.0
    assert mlib.interpolate_vs_frequency(_TABLE, 10.0) == 3.16
    assert mlib.interpolate_vs_frequency(_TABLE, 40.0) == 3.20


def test_interpolate_domain_guard_and_extrapolate_flag():
    with pytest.raises(ValueError, match="外推禁用"):
        mlib.interpolate_vs_frequency(_TABLE, 78.0)
    # 显式意图才放行（最近段斜率外推）
    out = mlib.interpolate_vs_frequency(_TABLE, 41.0, allow_extrapolate=True)
    assert out == pytest.approx(3.20 + (3.20 - 3.16) * 1.0 / 30.0)


def test_interpolate_single_point_table():
    single = [{"f_ghz": 10.0, "value": 3.0}]
    assert mlib.interpolate_vs_frequency(single, 10.0) == 3.0
    with pytest.raises(ValueError, match="超出表域"):
        mlib.interpolate_vs_frequency(single, 12.0)
    with pytest.raises(ValueError, match="无斜率"):
        mlib.interpolate_vs_frequency(single, 12.0, allow_extrapolate=True)


def test_interpolate_order_independent_and_guards():
    rev = list(reversed(_TABLE))
    assert mlib.interpolate_vs_frequency(rev, 5.5) == pytest.approx(3.08)
    with pytest.raises(ValueError, match="f_ghz"):
        mlib.interpolate_vs_frequency([{"f_ghz": -1.0, "value": 3.0}], 1.0)


# ─── 温度模型 ────────────────────────────────────────────────────────────────


def test_dk_at_temperature_identity_and_linear_anchor():
    # T=T_ref 逐位回收（构造性恒等）
    assert mlib.dk_at_temperature(3.0, -3.0, 23.0) == 3.0
    # 线性系数代数锚（测试侧独立推导 3.0·(1−3e-4)）
    out = mlib.dk_at_temperature(3.0, -3.0, 123.0)
    assert out == pytest.approx(DK_T_ANCHOR, rel=1e-12)
    # RO3006 高系数档（−262 ppm/°C）：100°C 漂移 = −2.62%
    out6 = mlib.dk_at_temperature(6.15, -262.0, 123.0)
    assert out6 == pytest.approx(6.15 * (1.0 - 262e-6 * 100.0), rel=1e-12)


def test_dk_at_temperature_domain_guard():
    with pytest.raises(ValueError, match="适用域"):
        mlib.dk_at_temperature(3.0, -3.0, 200.0, domain_c=[-50.0, 150.0])
    # 域端点合法
    assert mlib.dk_at_temperature(3.0, -3.0, -50.0,
                                  domain_c=[-50.0, 150.0]) == pytest.approx(
        3.0 * (1.0 + 3e-6 * 73.0))


def test_laminate_dk_temperature_path_and_missing_coeff_honesty():
    out = mlib.laminate_dk("rogers_ro3003", t_c=123.0)
    assert out["dk"] == pytest.approx(DK_T_ANCHOR, rel=1e-12)
    assert out["applied_temp_coeff_ppm_c"] == pytest.approx(-3.0)
    # fr4 无系数：design 档先报缺档；process 档走到温度面才报不编数
    with pytest.raises(ValueError, match="未登记 dk_design"):
        mlib.laminate_dk("fr4_generic", t_c=50.0)
    with pytest.raises(ValueError, match="不编数"):
        mlib.laminate_dk("fr4_generic", dk_kind="process", t_c=50.0)


# ─── 容差带 ─────────────────────────────────────────────────────────────────


def test_dk_tolerance_band_process_semantics():
    band = mlib.dk_tolerance_band("rogers_ro3003")
    assert band["kind"] == "plus_minus_tol"
    assert band["low"] == pytest.approx(2.96)
    assert band["high"] == pytest.approx(3.04)
    assert band["half_width"] == pytest.approx(0.04)
    # 相对半宽 = 0.04/3.00（±1.33%，78GHz 案例的输入量级）
    assert band["relative_half_width_pct"] == pytest.approx(0.04 / 3.00 * 100.0)


# ─── 替代推荐（确定性打分）───────────────────────────────────────────────────


def test_recommend_substitutes_exact_target_first():
    out = mlib.recommend_substitutes(3.00, top_n=3)
    assert out[0]["id"] == "rogers_ro3003"
    assert out[0]["dk_rel_err"] == pytest.approx(0.0)
    # 主序=dk 相对差升序
    errs = [r["dk_rel_err"] for r in out]
    assert errs == sorted(errs)


def test_recommend_substitutes_max_df_filter():
    out = mlib.recommend_substitutes(3.0, max_df=0.002, top_n=10)
    ids = [r["id"] for r in out]
    assert "rogers_ro4003c" not in ids  # df 0.0027 > cap
    assert "rogers_ro4350b" not in ids  # df 0.0037 > cap
    assert "rogers_ro3003" in ids       # df 0.0010 ≤ cap
    assert "rogers_ro3035" in ids       # df 0.0015 ≤ cap


def test_recommend_substitutes_unverified_flag_and_determinism():
    loose = mlib.recommend_substitutes(4.5, top_n=7)
    fr4 = [r for r in loose if r["id"] == "fr4_generic"]
    assert fr4 and fr4[0]["unverified"] is True
    # 全确定性：同参重跑逐位一致
    again = mlib.recommend_substitutes(4.5, top_n=7)
    assert json.dumps(loose, sort_keys=True) == json.dumps(again, sort_keys=True)


def test_recommend_substitutes_domain_coverage_annotation():
    out = mlib.recommend_substitutes(3.0, f_ghz=78.0, top_n=7)
    ro3003 = next(r for r in out if r["id"] == "rogers_ro3003")
    assert ro3003["design_domain_covered"] is False  # 8–40 GHz 不含 78
    ro4350 = next(r for r in out if r["id"] == "rogers_ro4350b")
    assert ro4350["design_domain_covered"] is None   # 无带声明→如实 None


def test_recommend_substitutes_guards():
    with pytest.raises(ValueError, match="max_df"):
        mlib.recommend_substitutes(3.0, max_df=-0.1)
    with pytest.raises(ValueError, match="top_n"):
        mlib.recommend_substitutes(3.0, top_n=0)
    with pytest.raises(ValueError, match="bool"):
        mlib.recommend_substitutes(True)


# ─── JSON 可序列化（service 面契约）─────────────────────────────────────────


def test_outputs_json_serializable():
    payload = {
        "dk": mlib.laminate_dk("rogers_ro3003"),
        "df": mlib.laminate_df("rogers_ro3003"),
        "band": mlib.dk_tolerance_band("rogers_ro3003"),
        "subs": mlib.recommend_substitutes(3.0, f_ghz=10.0),
        "rows": mlib.list_laminates(),
    }
    json.dumps(payload)  # 不抛即过：输出面可 JSON 化
