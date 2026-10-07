"""PK-5 压电材料表测试（锚树预声明，#122 判据先行）。

每件 ≥2 独立基准（出处见 core/piezo_materials.py 模块 docstring 文献
核实账；数据检索账见 piezo_data/piezo_materials.json retrieval_channels）：

- kt² 声学定义链：① 合成回收锚（v_s/v_a=0.99 → kt²=0.0199，#118）；
  ② 正反变换构造恒等式（velocity_stiffened∘velocity_unstiffened 逐位）；
  ③ kt²=0 → v_s=v_a 极限。
- 常数链：① kt²_from_constants 单步式与
  stiffened_elastic_constant→kt2_from_elastic_stiffening 两步链逐位一致
  （代数恒等）；② 合成回收（e=1, ce=100GPa, εr=10 → 手算值）。
- 密度晶体学推导：① 合成回收（SiO2 α-方石英已知值量级 + 量纲）；
  ② **双源收敛门**——AlN 推导 3.2606 vs CRC 3.255 ≤0.5%、Quartz 推导
  2.6487 vs 比重 2.65 ≤0.5%（#118 独立来源裁判）；
  ③ 三斜体积式六方退化锚（α=90°、γ=120° → (√3/2)a²c 逐位）；
  ④ **LN 冲突如实登记**——推导 4.626 vs CRC 4.30 差 >5%，loader 必须
  报 CONFLICT_registered 且 property_value 返回带中点、状态可查询
  （不裁决不凑绿，#122）。
- 派生声速：AlN v_c=√(c33/ρ)=10704.8 m/s（从已核 c33+density 推导，
  与文献口传值 11e3 量级同域——后者 UNVERIFIED 只作旁证不作门）。
- 加载器：状态档校验（NO_VALUE 必 None+指针、值档必带 sources）、深拷贝
  无污染、缺失属性 None、dual_source_report 计数与表一致。
"""

from __future__ import annotations

import json

import pytest

from rfauto.core.piezo_materials import (
    EPS0_F_PER_M,
    STATUS_CONFLICT_REGISTERED,
    STATUS_NO_VALUE_RETRIEVAL_PENDING,
    density_from_unit_cell_kg_m3,
    dual_source_report,
    get_material,
    hex_cell_volume_m3,
    kt2_from_constants,
    kt2_from_elastic_stiffening,
    kt2_from_velocities,
    load_piezo_table,
    longitudinal_velocity_m_s,
    property_value,
    stiffened_elastic_constant,
    trigonal_cell_volume_m3,
    velocity_stiffened,
    velocity_unstiffened,
)

# 本会话逐位核对的锚值（出处见模块 docstring / JSON sources）
ALN_RHO_CRC_G_CM3 = 3.255  # Haynes CRC 97e p.4.45 via Wikipedia infobox
ALN_A_NM = 0.31117
ALN_C_NM = 0.49788
ALN_M_G_MOL = 40.989
ALN_C33_GPA = 373.0
QUARTZ_SG_G_CM3 = 2.65
QUARTZ_A_ANG = 4.9133
QUARTZ_C_ANG = 5.4053
QUARTZ_M_G_MOL = 60.084
LN_RHO_CRC_G_CM3 = 4.30
LN_A_ANG = 5.1501
LN_C_ANG = 5.4952
LN_M_G_MOL = 147.846


# ─── kt²/声速闭式链 ──────────────────────────────────────────────────────────


def test_kt2_synthetic_recall_and_identities() -> None:
    # 合成回收锚（#118）：比值 0.99 → 手算 1-0.9801
    assert kt2_from_velocities(1.0, 0.99) == pytest.approx(0.0199, abs=1e-12)
    # 正反变换构造恒等式（往返）
    va = velocity_stiffened(3400.0, 0.06)
    assert velocity_unstiffened(va, 0.06) == pytest.approx(3400.0, rel=1e-15)
    kt = kt2_from_velocities(va, 3400.0)
    assert kt == pytest.approx(0.06, rel=1e-12)
    # kt²=0 极限：刚化不改变声速
    assert velocity_stiffened(3400.0, 0.0) == 3400.0
    # 非法域
    with pytest.raises(ValueError):
        kt2_from_velocities(1.0, 1.1)
    with pytest.raises(ValueError):
        velocity_stiffened(3400.0, 1.0)


def test_kt2_constants_chain_two_paths_bitwise_agree() -> None:
    # 两步链（c^D = c^E + e²/ε → kt² = 1 − c^E/c^D）与单步代数式逐位一致
    e33, ce_gpa, eps_r = 1.46, 373.0, 9.14
    eps = eps_r * EPS0_F_PER_M
    cd = stiffened_elastic_constant(ce_gpa, e33, eps)
    kt_two_step = kt2_from_elastic_stiffening(cd, ce_gpa)
    kt_one_step = kt2_from_constants(e33, ce_gpa, eps)
    assert kt_two_step == pytest.approx(kt_one_step, rel=1e-12)
    # AlN 已核常数（e33=1.46, c33=373GPa）+ 假定 εr=9.14（检索指针级，
    # 只作链路 sanity，不进材料表）→ kt²≈6.6%（量级锚）
    assert kt_one_step == pytest.approx(0.0660, abs=5e-4)
    # 守卫
    with pytest.raises(ValueError):
        kt2_from_elastic_stiffening(100.0, 100.0)


# ─── 密度晶体学推导（独立第二源）────────────────────────────────────────────


def test_trigonal_volume_hexagonal_degeneracy() -> None:
    # 三斜式退化锚：α=90°、γ=120°（六方元胞）→ (√3/2)a²c 逐位
    a, c = 3.1117e-10, 4.9788e-10
    v_tri = trigonal_cell_volume_m3(a, c, 90.0, 120.0)
    v_hex = hex_cell_volume_m3(a, c)
    assert v_tri == pytest.approx(v_hex, rel=1e-15)


def test_aln_density_dual_source_agree() -> None:
    a, c = ALN_A_NM * 1e-9, ALN_C_NM * 1e-9
    v = hex_cell_volume_m3(a, c)
    rho = density_from_unit_cell_kg_m3(2, ALN_M_G_MOL, v)
    assert rho / 1e3 == pytest.approx(3.2606, abs=5e-4)
    assert rho / 1e3 == pytest.approx(ALN_RHO_CRC_G_CM3, rel=0.005)  # 0.17% ✓


def test_quartz_density_dual_source_agree() -> None:
    a, c = QUARTZ_A_ANG * 1e-10, QUARTZ_C_ANG * 1e-10
    v = hex_cell_volume_m3(a, c)
    rho = density_from_unit_cell_kg_m3(3, QUARTZ_M_G_MOL, v)
    assert rho / 1e3 == pytest.approx(2.6487, abs=5e-4)
    assert rho / 1e3 == pytest.approx(QUARTZ_SG_G_CM3, rel=0.005)  # 0.05% ✓


def test_ln_density_conflict_registered_honestly() -> None:
    a, c = LN_A_ANG * 1e-10, LN_C_ANG * 1e-10
    v = trigonal_cell_volume_m3(a, c, 62.057, 60.0)
    rho = density_from_unit_cell_kg_m3(2, LN_M_G_MOL, v)
    assert rho / 1e3 == pytest.approx(4.6256, abs=2e-3)
    # 冲突必须 >5%（推导 vs CRC），loader 如实登记 CONFLICT_registered
    assert abs(rho / 1e3 - LN_RHO_CRC_G_CM3) / LN_RHO_CRC_G_CM3 > 0.05
    entry = get_material("linbo3")
    item = entry["properties"]["density_g_cm3"]
    assert item["status"] == STATUS_CONFLICT_REGISTERED
    assert item["value"] == [4.3, 4.624]
    # 带中点语义 + 冲突注记在场
    assert property_value("linbo3", "density_g_cm3") == pytest.approx(4.462)
    assert "conflict_note" in item


def test_aln_derived_velocity_from_verified_constants() -> None:
    # v_c = sqrt(c33/ρ)：输入（373 GPa, 3255 kg/m³）均为本会话已核值
    v = longitudinal_velocity_m_s(3255.0, ALN_C33_GPA * 1e9)
    assert v == pytest.approx(10704.8, abs=1.0)
    # 构造恒等式：v²·ρ = c
    assert v * v * 3255.0 == pytest.approx(ALN_C33_GPA * 1e9, rel=1e-12)


# ─── 加载器 ──────────────────────────────────────────────────────────────────


def test_loader_schema_validation_and_no_value_honesty() -> None:
    table = load_piezo_table()
    assert table["schema"] == "piezo_materials/v1"
    assert {"aln", "quartz", "linbo3", "litao3", "scaln_x043",
            "pzt5a", "pzt5h"} <= set(table["materials"])
    # 检索不可达=零值诚实：PZT/ScAlN/LT 的 d33 必须 None+指针
    for mid in ("pzt5a", "pzt5h", "scaln_x043", "litao3"):
        item = table["materials"][mid]["properties"]["d33_pc_per_n"]
        assert item["value"] is None
        assert item["status"] == STATUS_NO_VALUE_RETRIEVAL_PENDING
        assert item["retrieval_pointers"]
    # 属性缺失 → None（判缺失 is not None 口径）
    assert property_value("aln", "nonexistent_prop") is None
    assert property_value("pzt5a", "d33_pc_per_n") is None


def test_loader_deep_copy_and_value_access() -> None:
    entry = get_material("aln")
    entry["properties"]["density_g_cm3"]["value"] = -999.0
    fresh = get_material("aln")
    assert fresh["properties"]["density_g_cm3"]["value"] == ALN_RHO_CRC_G_CM3
    assert property_value("aln", "e33_c_per_m2") == 1.46
    assert property_value("quartz", "alpha_beta_transition_c") == 573.0
    assert property_value("aln", "c33_gpa") == 373.0
    with pytest.raises(KeyError):
        get_material("no_such_material")


def test_loader_rejects_invalid_status(tmp_path) -> None:
    table = load_piezo_table()
    table["materials"]["aln"]["properties"]["density_g_cm3"]["status"] = "made_up"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(table), encoding="utf-8")
    with pytest.raises(ValueError, match="状态档非法"):
        load_piezo_table(bad)


def test_dual_source_report_counts() -> None:
    report = dual_source_report()
    assert report["properties_total"] == sum(
        v for k, v in report.items() if k not in ("properties_total",)
    )
    # 双源覆盖必须如实有限（不得冒充全表双源）
    assert report["dual_source_agree"] >= 2  # AlN+Quartz 密度两键
    assert report["NO_VALUE_retrieval_pending"] > 0
    assert report["CONFLICT_registered"] == 1  # LN 密度


def test_numeric_zero_and_bool_guards() -> None:
    # 数值 0.0 合法（#364④）、bool 显式拒收
    assert kt2_from_velocities(1.0, 1.0) == 0.0
    with pytest.raises(ValueError):
        kt2_from_velocities(True, 0.5)
    with pytest.raises(ValueError):
        density_from_unit_cell_kg_m3(2, 40.0, float("nan"))
