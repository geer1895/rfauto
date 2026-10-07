"""MP-5 环境试验条件表内核单测（core/environment_tables.py，round15 :88）。

裁判 = 外部独立来源（#118：不是被测实现的自我推导）：
  * JESD22-A110/A118 HAST：110 °C / 85 %RH / 水汽压 1.2×10⁵ Pa（无偏/加偏
    两变体）——JEDEC 条件表通引值；
  * JESD22-A101 THB：85/85 加偏（业界常用 1000 h 只进 notes 不进条件值——
    时长协议随采购文件变化的语义与条件值分离的 schema 口径由本组钉）；
  * JESD22-A102 autoclave：121 °C / 100 %RH / 15 psi 表压——
    15×6894.757293168=103421.36 Pa（1 psi=6894.757293168 Pa 精确换算手算）；
  * IPC-TM-650 2.3.25 ROSE：75/25 IPA/DI 萃取液 + ≤1.56 µg/cm² NaCl 当量
    （=10.0645 µg/in²，1 in²=6.4516 cm² 精确换算手算）；
  * IEC 60068-2-27 半正弦冲击优先等级抽检四档（150/11、300/18、500/11、
    1000/6 m/s²·ms）+ g 换算参照恒等式（150 m/s²=150/9.80665=15.30 g，
    证明 SI 主口径而非严格整数 g——模块声明的诚实口径由本例钉）；
  * 温度循环剖面：周期时长闭式手算（Test Nb：2·125/10+20=45 min；
    Test Na：30+30+2·3=66 min）+ schema 域守卫负例；
  * 规格边界：「入口不产寿命结论」守卫显式拒绝（NotImplementedError）。

确定性：无网络、无真机、无文件 IO、无随机。
"""

from __future__ import annotations

import pytest

from rfauto.core.environment_tables import (
    GN_M_PER_S2,
    PA_PER_PSI,
    get_condition,
    life_from_condition,
    list_conditions,
    list_families,
    list_standards,
    make_temperature_cycle_profile,
    sample_temperature_cycle_profiles,
    validate_temperature_cycle_profile,
)

# ---------------------------------------------------------------- 条件表值


class TestTableSpotChecks:
    """表值抽检（公开标准通引值；规格段只给标准号，值源=标准知识）。"""

    def test_hast_unbiased_a110(self) -> None:
        e = get_condition("hast_unbiased_jesd22_a110")
        assert e["standard"] == "JESD22-A110"
        assert e["condition"]["temperature_c"] == pytest.approx(110.0)
        assert e["condition"]["relative_humidity_percent"] == pytest.approx(
            85.0)
        assert e["condition"]["water_vapor_pressure_pa"] == pytest.approx(
            1.2e5, rel=1e-12)
        assert e["condition"]["bias"] == "unbiased"
        assert e["verified"] is True

    def test_hast_biased_a118(self) -> None:
        e = get_condition("hast_biased_jesd22_a118")
        assert e["standard"] == "JESD22-A118"
        assert e["condition"]["bias"] == "dc_biased"
        assert e["condition"]["temperature_c"] == pytest.approx(110.0)
        assert e["condition"]["relative_humidity_percent"] == pytest.approx(
            85.0)

    def test_thb_85_85_a101_duration_in_notes_not_condition(self) -> None:
        e = get_condition("thb_85_85_jesd22_a101")
        assert e["condition"]["temperature_c"] == pytest.approx(85.0)
        assert e["condition"]["relative_humidity_percent"] == pytest.approx(
            85.0)
        assert e["condition"]["bias"] == "dc_biased"
        # schema 口径：时长协议不进条件数值面（只在 notes 提示按协议）
        assert "1000" in e["notes"]
        assert all("duration" not in k for k in e["condition"])

    def test_autoclave_a102_psi_conversion_hand(self) -> None:
        e = get_condition("autoclave_unbiased_jesd22_a102")
        assert e["condition"]["temperature_c"] == pytest.approx(121.0)
        assert e["condition"]["relative_humidity_percent"] == pytest.approx(
            100.0)
        # 手算：15 psi × 6894.757293168 Pa/psi = 103421.36 Pa
        assert e["condition"]["chamber_pressure_gauge_psi"] == pytest.approx(
            15.0)
        assert e["condition"]["chamber_pressure_gauge_pa"] == pytest.approx(
            15.0 * PA_PER_PSI, rel=1e-7)  # 表存 2 位小数舍入口径
        assert e["condition"]["chamber_pressure_gauge_pa"] == pytest.approx(
            103421.36, rel=1e-5)

    def test_rose_ipc_tm_650_solvent_and_limit(self) -> None:
        e = get_condition("rose_ipc_tm_650_2_3_25")
        cond = e["condition"]
        assert cond["solvent_ipa_volume_percent"] == pytest.approx(75.0)
        assert cond["solvent_di_water_volume_percent"] == pytest.approx(25.0)
        assert cond["solvent_ipa_volume_percent"] + \
            cond["solvent_di_water_volume_percent"] == pytest.approx(100.0)
        # ≤1.56 µg/cm² NaCl 当量；手算换算 1.56×6.4516=10.0645 µg/in²
        assert cond["nacl_equivalent_limit_ug_per_cm2"] == pytest.approx(
            1.56)
        # 手算：1.56×6.4516 = 10.064496 µg/in²
        assert pytest.approx(10.064496, rel=1e-12) == 1.56 * 6.4516

    def test_shock_iec_60068_2_27_severities(self) -> None:
        e = get_condition("shock_half_sine_iec_60068_2_27")
        assert e["condition"]["waveform"] == "half_sine"
        sev = [(s["peak_accel_m_per_s2"], s["duration_ms"])
               for s in e["condition"]["severities"]]
        assert sev == [(150.0, 11.0), (300.0, 18.0), (500.0, 11.0),
                       (1000.0, 6.0)]
        # g 换算参照恒等式：150 m/s² = 15.30 g（SI 主口径，非严格 15 g）
        assert pytest.approx(15.2957, rel=1e-4) == 150.0 / GN_M_PER_S2
        assert pytest.approx(101.9716, rel=1e-4) == 1000.0 / GN_M_PER_S2


# ---------------------------------------------------------------- 查询面


class TestQuerySurface:
    """schema 完整性 + 过滤查询 + 拷贝隔离 + 未知名显式报错。"""

    def test_table_schema_integrity(self) -> None:
        rows = list_conditions()
        assert len(rows) >= 6
        ids = [r["id"] for r in rows]
        assert len(ids) == len(set(ids))  # id 唯一
        for row in rows:
            assert row["verified"] is True  # 本批只录有公开出处的值
            assert row["source"]
            assert row["condition"]
            assert set(row) >= {"id", "family", "standard", "title",
                                "condition", "notes", "source", "verified"}

    def test_filters_and_lists(self) -> None:
        assert set(list_families()) >= {"hast", "thb", "autoclave",
                                        "ionic_contamination", "shock"}
        assert set(list_standards()) >= {"JESD22-A110", "JESD22-A118",
                                         "JESD22-A101", "JESD22-A102",
                                         "IPC-TM-650 2.3.25",
                                         "IEC 60068-2-27"}
        hast = list_conditions(family="hast")
        assert {r["standard"] for r in hast} == {"JESD22-A110",
                                                 "JESD22-A118"}
        rose = list_conditions(standard="IPC-TM-650 2.3.25")
        assert len(rose) == 1
        assert rose[0]["id"] == "rose_ipc_tm_650_2_3_25"
        assert list_conditions(family="nonexistent") == []

    def test_returns_copies_not_live_table(self) -> None:
        row = get_condition("hast_unbiased_jesd22_a110")
        row["condition"]["temperature_c"] = 999.0
        row["condition"]["severities"] = []
        fresh = get_condition("hast_unbiased_jesd22_a110")
        assert fresh["condition"]["temperature_c"] == pytest.approx(110.0)

    def test_unknown_id_explicit_keyerror(self) -> None:
        with pytest.raises(KeyError, match="未收录"):
            get_condition("no_such_condition")


# ------------------------------------------------- 温度循环剖面 schema


class TestTemperatureCycleProfile:
    """剖面 schema：周期时长闭式手算 + 校验 + 示例剖面诚实标注。"""

    def test_nb_ramp_cycle_time_closed_form(self) -> None:
        # Test Nb（斜率法）：t_cycle = 2·(85−(−40))/10 + 10 + 10 = 45 min
        p = make_temperature_cycle_profile(
            -40.0, 85.0, rate_k_per_min=10.0,
            dwell_low_min=10.0, dwell_high_min=10.0, n_cycles=100)
        assert p["ramp_min_per_leg"] == pytest.approx(12.5, rel=1e-12)
        assert p["cycle_time_min"] == pytest.approx(45.0, rel=1e-12)
        assert p["total_time_min"] == pytest.approx(4500.0, rel=1e-12)

    def test_na_transfer_cycle_time_closed_form(self) -> None:
        # Test Na（转移时间法）：t_cycle = 30 + 30 + 2·3 = 66 min
        p = make_temperature_cycle_profile(
            -40.0, 85.0, dwell_low_min=30.0, dwell_high_min=30.0,
            transfer_min=3.0, n_cycles=25)
        assert p["cycle_time_min"] == pytest.approx(66.0, rel=1e-12)
        assert p["total_time_min"] == pytest.approx(1650.0, rel=1e-12)

    def test_envelope_only_profile(self) -> None:
        # 斜率/转移都不给 → 纯包络剖面（cycle_time=None 不臆造）
        p = make_temperature_cycle_profile(-55.0, 125.0)
        assert p["cycle_time_min"] is None
        assert p["total_time_min"] is None
        validate_temperature_cycle_profile(p)  # schema 自身可回验

    def test_samples_marked_example_not_standard(self) -> None:
        samples = sample_temperature_cycle_profiles()
        assert samples
        for p in samples.values():
            assert p["example"] is True
            assert "非标准规定值" in p["note"]
            validate_temperature_cycle_profile(p)

    def test_schema_domain_guards(self) -> None:
        with pytest.raises(ValueError, match="严格大于"):
            make_temperature_cycle_profile(85.0, -40.0)  # 高低温倒挂
        with pytest.raises(ValueError, match="严格大于"):
            make_temperature_cycle_profile(85.0, 85.0)  # 零摆幅
        with pytest.raises(ValueError, match=">0"):
            make_temperature_cycle_profile(-40.0, 85.0, rate_k_per_min=0.0)
        with pytest.raises(ValueError, match=">=0"):
            make_temperature_cycle_profile(-40.0, 85.0, dwell_low_min=-1.0)
        with pytest.raises(ValueError, match="≥1"):
            make_temperature_cycle_profile(-40.0, 85.0, n_cycles=0)
        with pytest.raises(ValueError, match="有限"):
            make_temperature_cycle_profile(float("nan"), 85.0)


# ------------------------------------------------- 寿命结论守卫（规格边界）


class TestLifeConclusionGuard:
    """「纯表+入口不产寿命结论」守卫（round15 :88 规格字面落地）。"""

    def test_life_from_condition_explicitly_refused(self) -> None:
        with pytest.raises(NotImplementedError, match="不产寿命结论"):
            life_from_condition(get_condition("thb_85_85_jesd22_a101"))
