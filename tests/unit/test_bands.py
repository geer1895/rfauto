"""D9 标准频段/法规掩模注册表单测。

覆盖：种子表完整性（唯一键/lo<hi/出处非空）、查表显式报错、包含查找、
过滤、to_spec_bounds 结构与 SpecEvaluator（core/objectives.py，只读参照）
联动、service 层 JSON 契约与参数校验（负频率拒绝）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core.bands import (
    BANDS,
    ENVIRONMENTS,
    BandEntry,
    BandKind,
    EnvEntry,
    EnvKind,
    band_keys,
    env_delta_t_bounds,
    env_keys,
    env_temperature_points,
    env_to_delta_t,
    env_to_uq_axis,
    find_bands,
    find_envs,
    get_band,
    get_env,
    search,
    search_env,
    to_spec_bounds,
    validate_env_registry,
    validate_registry,
)
from rfauto.core.objectives import MetricOp, Objective, SpecEvaluator
from rfauto.service.bands_service import (
    bands_env_delta_t,
    bands_env_find,
    bands_env_get,
    bands_env_list,
    bands_env_points,
    bands_env_uq_axis,
    bands_find,
    bands_get,
    bands_list,
    bands_spec_bounds,
)

# ─── 种子表完整性（D9 验收：每条 lo<hi、source 非空、key 唯一）────────────────

def test_seed_registry_integrity():
    assert validate_registry() == []
    keys = band_keys()
    assert len(keys) == len(set(keys)), "key 必须唯一"
    assert len(keys) >= 20, f"种子表规模异常: {len(keys)}"


def test_seed_required_coverage():
    """最小覆盖面要求：ISM/Wi-Fi/UWB/3GPP/CN/SRD/GNSS/EMC 限值线。"""
    required = {
        "ism_2g4", "ism_5g8",                     # ITU-R RR 5.150
        "wifi_2g4", "wifi_unii1", "wifi6e_us",    # Wi-Fi 2.4/5/6E
        "uwb_fcc",                                # 3.1–10.6 GHz
        "gpp_n41", "gpp_n78",                     # TS 38.101-1
        "cn_5g_3g3_3g6",                          # 工信部 3.3–3.6 GHz
        "srd_868m_eu", "ism_915m_us",             # 868/915 MHz SRD
        "gnss_l1",                                # 1559–1610 MHz
        "cispr32_classb_rad_30m_230m",
        "cispr32_classb_rad_230m_1g",             # CISPR 32 Class B
    }
    missing = required - set(BANDS)
    assert not missing, f"种子表缺条目: {missing}"


def test_seed_entry_standards_cited():
    """每条出处必须含标准号要素（编号数字或 CFR/ITU/EC/工信部 关键词）。"""
    for e in BANDS.values():
        assert e.source and e.standard, f"{e.key}: 出处为空"
        token = (e.source + e.standard).lower()
        assert any(t in token for t in ("itu", "3gpp", "38.101", "cfr", "cispr",
                                        "802.11", "erc", "ec decision", "工信部",
                                        "2021/1067")), f"{e.key}: 出处不像标准号: {e.source}"


# ─── 查表 get_band ───────────────────────────────────────────────────────────

def test_get_band_known_returns_entry_with_standard_values():
    e = get_band("gpp_n78")
    assert isinstance(e, BandEntry)
    assert e.f_low_ghz == 3.3 and e.f_high_ghz == 3.8  # TS 38.101-1 Table 5.2-1
    assert "38.101" in e.standard
    assert e.kind is BandKind.LICENSED
    uwb = get_band("uwb_fcc")
    assert (uwb.f_low_ghz, uwb.f_high_ghz) == (3.1, 10.6)  # 47 CFR §15.505


def test_get_band_unknown_keyerror_lists_available():
    with pytest.raises(KeyError) as ei:
        get_band("no_such_band")
    msg = str(ei.value)
    assert "no_such_band" in msg
    assert "gpp_n78" in msg, "报错必须带可用键列表"


# ─── 包含查找 find_bands ─────────────────────────────────────────────────────

def test_find_bands_returns_all_overlapping_entries():
    at_3g5 = {e.key for e in find_bands(3.5)}
    assert {"gpp_n78", "cn_5g_3g3_3g6"} <= at_3g5          # n78 与中国划分重叠
    assert "ism_2g4" not in at_3g5
    at_5g8 = {e.key for e in find_bands(5.8)}
    assert {"ism_5g8", "wifi_unii3"} <= at_5g8               # ISM 与 U-NII-3 重叠段


def test_find_bands_boundary_inclusive():
    at_low = find_bands(2.4)
    at_high = find_bands(2.5)
    assert "ism_2g4" in {e.key for e in at_low}             # 2400 下端含
    assert "ism_2g4" in {e.key for e in at_high}            # 2500 上端含


def test_find_bands_validation_and_empty():
    with pytest.raises(ValueError):
        find_bands(0.0)
    with pytest.raises(ValueError):
        find_bands(-1.5)
    assert find_bands(10.7) == []                            # UWB 上端之上无条目


# ─── 过滤 search ─────────────────────────────────────────────────────────────

def test_search_by_kind_emc_returns_limit_lines():
    emc = search(kind="emc")
    assert len(emc) >= 6
    for e in emc:
        assert e.kind is BandKind.EMC
        assert "dBμV/m" in e.notes and "@3m" in e.notes, "EMC 条目 notes 必须带限值/距离"
    # CISPR 32 Class B 数值口径：40（30–230）/47（230–1000）dBμV/m@3m
    by_key = {e.key: e for e in emc}
    assert "40" in by_key["cispr32_classb_rad_30m_230m"].notes
    assert "47" in by_key["cispr32_classb_rad_230m_1g"].notes


def test_search_standard_substring_case_insensitive():
    n_bands = {e.key for e in search(standard="38.101")}
    assert n_bands == {"gpp_n41", "gpp_n78", "gpp_n79"}
    cispr = search(standard="cispr")                          # 小写子串
    assert {e.key for e in cispr} >= {"cispr32_classb_rad_30m_230m"}


def test_search_region_and_combined():
    cn = search(region="cn")
    assert [e.key for e in cn] == ["cn_5g_3g3_3g6"]
    combo = {e.key for e in search(standard="cfr", kind="emc", region="us")}
    assert combo == {"fcc15b_rad_30m_88m", "fcc15b_rad_88m_216m",
                     "fcc15b_rad_216m_960m", "fcc15b_rad_above_960m"}
    assert len(search()) == len(BANDS)                        # 无过滤=全表
    with pytest.raises(ValueError):
        search(kind="not_a_kind")                             # 非法 kind 显式报错


# ─── to_spec_bounds 与 SpecEvaluator 联动（结构测试，不改 objectives.py）──────

def test_to_spec_bounds_structure():
    assert to_spec_bounds("gpp_n78") == {"band": [3.3, 3.8]}
    with pytest.raises(KeyError):
        to_spec_bounds("no_such_band")


def test_to_spec_bounds_feeds_spec_evaluator_band_masking():
    """registry bounds 平铺进 Objective.band 后，SpecEvaluator 带内掩模生效。"""
    import numpy as np
    import skrf as rf

    freq = rf.Frequency(1, 6, 101, unit="GHz")
    s = np.full((101, 1, 1), 10 ** (-3 / 20), dtype=complex)   # 带外 -3 dB
    f_ghz = freq.f * 1e-9
    in_band = (f_ghz >= 3.3) & (f_ghz <= 3.8)
    # n78 带内线性渐变 -20→-40 dB：min/max 双端点均与带外 -3 dB 远离，
    # 证明 band 掩模只取了注册表区间内的采样点
    s[in_band, 0, 0] = 10 ** (np.linspace(-20, -40, int(in_band.sum())) / 20)
    ntwk = rf.Network(frequency=freq, s=s)

    obj = Objective(metric="s11_db_min", band=to_spec_bounds("gpp_n78")["band"],
                    op=MetricOp.MAX_BELOW, value=-10)
    metrics = SpecEvaluator.compute_metrics(ntwk, [obj])
    assert metrics["s11_db_min_in_band"] == pytest.approx(-40, abs=0.5)
    assert metrics["s11_db_max_in_band"] == pytest.approx(-20, abs=0.5)
    # 谷深（带内最差 -20 dB）达标（≤ -10），加权 cost 为 0
    assert SpecEvaluator.evaluate_objectives(metrics, [obj]) == pytest.approx(0.0, abs=1e-9)


# ─── service 层 JSON 契约与参数校验 ─────────────────────────────────────────

def test_service_bands_get_contract():
    r = bands_get("gpp_n78")
    assert r["ok"] is True
    band = r["band"]
    assert band["key"] == "gpp_n78" and band["f_low_ghz"] == 3.3
    assert band["kind"] == "licensed" and band["source"]
    json.dumps(r)                                              # 可直接 JSON 序列化
    bad = bands_get("no_such_band")
    assert bad["ok"] is False and "gpp_n78" in bad["error"]
    assert bands_get("")["ok"] is False
    assert bands_get(None)["ok"] is False                      # 非字符串 key 显式拒绝


def test_service_bands_list_filters_and_json():
    r = bands_list()
    assert r["ok"] is True and r["count"] == r["total"] == len(BANDS)
    emc = bands_list(kind="emc")
    assert emc["ok"] is True and emc["count"] == len(search(kind="emc"))
    assert bands_list(kind="bogus")["ok"] is False             # 非法 kind → 显式报错
    assert bands_list(standard="38.101")["count"] == 3
    json.dumps(bands_list())                                   # JSON 契约


def test_service_bands_find_param_validation():
    ok = bands_find(3.5)
    assert ok["ok"] is True and ok["count"] >= 2
    assert {b["key"] for b in ok["bands"]} >= {"gpp_n78", "cn_5g_3g3_3g6"}
    for bad_freq in (-1.0, 0, "2.4", None, True):              # 负数/零/字符串/None/bool 拒绝
        r = bands_find(bad_freq)
        assert r["ok"] is False, f"freq={bad_freq!r} 应被拒绝"
        assert "error" in r


def test_service_bands_spec_bounds():
    r = bands_spec_bounds("gpp_n78")
    assert r["ok"] is True
    assert r["spec_bounds"] == {"band": [3.3, 3.8]}
    # 结构可直接平铺进 Objective（service→core 口径一致）
    obj = Objective(metric="s21_db", **r["spec_bounds"])
    assert obj.band == [3.3, 3.8]
    bad = bands_spec_bounds("no_such_band")
    assert bad["ok"] is False and "no_such_band" in bad["error"]


# ═══════════════════════════════════════════════════════════════════════════════
# D9 环境包络注册表（§10.21 D9 强化）：温度/试验等级一等对象 + ΔT 转换接口
# ═══════════════════════════════════════════════════════════════════════════════

def test_env_seed_registry_integrity():
    assert validate_env_registry() == []
    keys = env_keys()
    assert len(keys) == len(set(keys)) == len(ENVIRONMENTS)
    assert len(keys) >= 10, f"环境包络表规模异常: {len(keys)}"
    for k in keys:
        e = get_env(k)
        assert isinstance(e, EnvEntry) and e.source and e.standard and e.name


def test_env_builder_rejects_inconsistent_seed():
    """重名/温区倒置/严酷等级端点不符一律导入期显式报错（fail fast）。"""
    from rfauto.core.bands import _build_env_registry

    dup = (ENVIRONMENTS[env_keys()[0]],) * 2
    with pytest.raises(RuntimeError, match="重名"):
        _build_env_registry(dup)
    bad_sev = EnvEntry(key="bad_sev", standard="S", name="n", kind=EnvKind.TEST,
                       t_min_c=-10.0, t_max_c=10.0,
                       severities_c=(-10.0, -5.0, 5.0))
    with pytest.raises(RuntimeError, match="端点"):
        _build_env_registry((bad_sev,))
    bad_order = EnvEntry(key="bad_order", standard="S", name="n",
                         kind=EnvKind.TEST, t_min_c=10.0, t_max_c=-10.0)
    with pytest.raises(RuntimeError, match="t_min_c"):
        _build_env_registry((bad_order,))
    no_source = EnvEntry(key="no_source", standard="S", name="n",
                         kind=EnvKind.TEST, t_min_c=-1.0, t_max_c=1.0)
    with pytest.raises(RuntimeError, match="source"):
        _build_env_registry((no_source,))


def test_env_seed_standard_values():
    """端点值逐一对照标准文本（AEC-Q100 / ECSS-Q-ST-60-13C）。"""
    industrial = get_env("industrial_grade_40_85")
    assert industrial.kind is EnvKind.INDUSTRIAL
    assert (industrial.t_min_c, industrial.t_max_c) == (-40.0, 85.0)

    grades = {"aec_q100_grade0": (-40.0, 150.0),
              "aec_q100_grade1": (-40.0, 125.0),
              "aec_q100_grade2": (-40.0, 105.0),
              "aec_q100_grade3": (-40.0, 85.0)}
    for k, (lo, hi) in grades.items():
        e = get_env(k)
        assert e.kind is EnvKind.AUTOMOTIVE
        assert (e.t_min_c, e.t_max_c) == (lo, hi)
        assert "AEC-Q100" in e.standard and "AEC-Q100" in e.source

    eee = get_env("ecss_commercial_eee_40_85")
    assert eee.kind is EnvKind.SPACE
    assert (eee.t_min_c, eee.t_max_c) == (-40.0, 85.0)
    assert "4.2.2.6d" in eee.source and "ECSS-Q-ST-60-13C" in eee.standard
    cap = get_env("ecss_ceramic_capacitor_40_125")
    assert (cap.t_min_c, cap.t_max_c) == (-40.0, 125.0)
    cyc = get_env("ecss_thermal_cycling_55_125")
    assert (cyc.t_min_c, cyc.t_max_c) == (-55.0, 125.0)

    kinds = {e.kind for e in ENVIRONMENTS.values()}
    assert kinds == {EnvKind.INDUSTRIAL, EnvKind.AUTOMOTIVE,
                     EnvKind.SPACE, EnvKind.TEST}


def test_env_seed_iec60068_severities():
    """IEC 60068 试验严酷等级集合（GB/T 2423.x 等同采用）。"""
    cold = get_env("iec60068_2_1_cold")
    assert cold.kind is EnvKind.TEST
    assert cold.severities_c == (-65.0, -55.0, -40.0, -25.0, -10.0, -5.0, 5.0)
    assert (cold.t_min_c, cold.t_max_c) == (cold.severities_c[0],
                                            cold.severities_c[-1])
    heat = get_env("iec60068_2_2_dry_heat")
    assert heat.severities_c[0] == 30.0
    assert heat.severities_c[-1] == 1000.0
    assert list(heat.severities_c) == sorted(heat.severities_c)
    assert (heat.t_min_c, heat.t_max_c) == (30.0, 1000.0)
    assert "60068-2-1" in cold.standard and "60068-2-2" in heat.standard


def test_env_get_unknown_and_search_kind_standard():
    with pytest.raises(KeyError) as ei:
        get_env("no_such_env")
    msg = str(ei.value)
    assert "no_such_env" in msg and "aec_q100_grade1" in msg

    auto = search_env(kind="automotive")
    assert {e.key for e in auto} == {f"aec_q100_grade{i}" for i in range(4)}
    assert all(e.kind is EnvKind.AUTOMOTIVE for e in auto)
    with pytest.raises(ValueError):
        search_env(kind="bogus")
    assert {e.key for e in search_env(standard="ECSS-Q-ST-60")} == {
        "ecss_commercial_eee_40_85", "ecss_ceramic_capacitor_40_125",
        "ecss_thermal_cycling_55_125"}
    assert len(search_env()) == len(ENVIRONMENTS)


def test_env_find_covering_envelopes():
    at_minus40 = {e.key for e in find_envs(-40.0)}
    assert {"industrial_grade_40_85", "aec_q100_grade0", "aec_q100_grade1",
            "aec_q100_grade2", "aec_q100_grade3",
            "ecss_commercial_eee_40_85"} <= at_minus40
    assert "iec60068_2_1_cold" in {e.key for e in find_envs(-65.0)}
    at150 = {e.key for e in find_envs(150.0)}
    assert "aec_q100_grade0" in at150                    # Grade 0 上端 = +150
    assert "aec_q100_grade1" not in at150                # Grade 1 上端 = +125
    assert "iec60068_2_2_dry_heat" in {e.key for e in find_envs(1000.0)}
    assert find_envs(-70.0) == []
    with pytest.raises(ValueError):
        find_envs(float("nan"))


def test_env_to_delta_t_with_reference():
    d = env_to_delta_t("aec_q100_grade1")
    assert d["t_ref_c"] == 25.0
    assert d["delta_t_min_c"] == -65.0 and d["delta_t_max_c"] == 100.0
    assert d["delta_t_span_c"] == 165.0
    # 显式参考温度（应用点 85 °C）
    d85 = env_to_delta_t("aec_q100_grade1", t_ref_c=85.0)
    assert (d85["delta_t_min_c"], d85["delta_t_max_c"]) == (-125.0, 40.0)
    assert env_delta_t_bounds("industrial_grade_40_85") == (-65.0, 60.0)
    cold = env_to_delta_t("iec60068_2_1_cold")
    assert (cold["delta_t_min_c"], cold["delta_t_max_c"]) == (-90.0, -20.0)


def test_env_to_delta_t_validation():
    with pytest.raises(KeyError):
        env_to_delta_t("no_such_env")
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            env_to_delta_t("aec_q100_grade1", t_ref_c=bad)


def test_env_temperature_points_deterministic_grid():
    pts = env_temperature_points("aec_q100_grade2", 5)
    assert pts == [-40.0, -3.75, 32.5, 68.75, 105.0]
    assert pts[0] == get_env("aec_q100_grade2").t_min_c
    assert pts[-1] == get_env("aec_q100_grade2").t_max_c
    assert env_temperature_points("aec_q100_grade2", 5) == pts
    for bad in (1, 0, -3, True, 2.5, "5"):
        with pytest.raises(ValueError):
            env_temperature_points("aec_q100_grade2", bad)
    with pytest.raises(KeyError):
        env_temperature_points("no_such_env", 3)


def test_env_registry_coexists_with_band_registry():
    """环境包络与频段条目共存不冲突（独立 registry，频段语义不变）。"""
    assert validate_registry() == [] and validate_env_registry() == []
    assert len(BANDS) >= 25
    assert not (set(BANDS) & set(ENVIRONMENTS))
    assert {e.key for e in find_bands(3.5)} >= {"gpp_n78", "cn_5g_3g3_3g6"}
    assert len(search()) == len(BANDS)
    assert len(search(kind="emc")) >= 6


def test_service_env_list_and_get_contract():
    r = bands_env_list()
    assert r["ok"] is True and r["count"] == r["total"] == len(ENVIRONMENTS)
    json.dumps(r)
    auto = bands_env_list(kind="automotive")
    assert auto["ok"] is True and auto["count"] == 4
    assert bands_env_list(kind="bogus")["ok"] is False
    g = bands_env_get("aec_q100_grade1")
    assert g["ok"] is True
    env = g["environment"]
    assert env["key"] == "aec_q100_grade1" and env["t_max_c"] == 125.0
    assert env["kind"] == "automotive" and env["source"]
    json.dumps(g)
    bad = bands_env_get("no_such_env")
    assert bad["ok"] is False and "aec_q100_grade1" in bad["error"]
    assert bands_env_get("")["ok"] is False
    assert bands_env_get(None)["ok"] is False
    f = bands_env_find(-40.0)
    assert f["ok"] is True and f["count"] >= 6
    assert {b["key"] for b in f["environments"]} >= {"aec_q100_grade1"}
    for bad_t in ("25", None, True):                      # 非数字显式拒绝
        assert bands_env_find(bad_t)["ok"] is False
    assert bands_env_find(-1e9)["ok"] is True             # 合法温度但无覆盖 → 空集
    assert bands_env_find(-1e9)["count"] == 0


def test_service_env_delta_t_json_and_repeatability():
    a = bands_env_delta_t("aec_q100_grade1")
    b = bands_env_delta_t("aec_q100_grade1")
    assert a["ok"] is True
    assert a["delta_t_min_c"] == -65.0 and a["delta_t_max_c"] == 100.0
    assert json.dumps(a) == json.dumps(b)              # 同输入两次逐字节一致
    ref = bands_env_delta_t("aec_q100_grade1", t_ref_c=85)
    assert ref["ok"] is True and ref["delta_t_min_c"] == -125.0
    assert bands_env_delta_t("aec_q100_grade1", t_ref_c="25")["ok"] is False
    assert bands_env_delta_t("no_such_env")["ok"] is False
    pts = bands_env_points("aec_q100_grade2", 5)
    assert pts["ok"] is True and pts["temperatures_c"][0] == -40.0
    assert pts["temperatures_c"][-1] == 105.0
    assert bands_env_points("aec_q100_grade2", 1)["ok"] is False


def test_env_uq_axis_service_contract():
    a = bands_env_uq_axis("industrial_grade_40_85")
    b = bands_env_uq_axis("industrial_grade_40_85")
    assert a["ok"] is True and a["param"] == "t_c"
    assert a["nominal_c"] == 25.0 and a["k_sigma"] == 3.0
    assert a["half_range_c"] == 65.0
    assert a["sigma_c"] == pytest.approx(65.0 / 3.0)
    assert json.dumps(a) == json.dumps(b)
    assert bands_env_uq_axis("industrial_grade_40_85", k_sigma=0)["ok"] is False
    assert bands_env_uq_axis("industrial_grade_40_85", k_sigma=True)["ok"] is False
    assert bands_env_uq_axis("no_such_env")["ok"] is False


def test_env_delta_t_bounds_feed_d3_thermal_drift_sweep():
    """D3 温区扫描消费：温区 → ΔT 网格 → 谐振温漂闭式内核。"""
    from rfauto.core.calculators import resonator_thermal_drift

    env = get_env("aec_q100_grade1")
    d = env_to_delta_t(env.key)
    temps = env_temperature_points(env.key, 5)
    dts = [t - env.t_ref_c for t in temps]
    assert dts[0] == d["delta_t_min_c"]
    assert dts[-1] == d["delta_t_max_c"]
    assert env_delta_t_bounds(env.key) == (dts[0], dts[-1])

    ratios = [resonator_thermal_drift(2.45, dt, 16.0, 30.0)["df_over_f"]
              for dt in dts]
    assert ratios == sorted(ratios, reverse=True)      # 温升单调下漂
    assert ratios[0] > 0.0 and ratios[-1] < 0.0        # 冷却上漂 / 加热下漂
    # 端点闭环：Δf/f = −(CTE + TCDk/2)·1e-6·ΔT
    end = resonator_thermal_drift(2.45, dts[-1], 16.0, 30.0)
    assert end["df_over_f"] == pytest.approx(
        -(16.0 + 0.5 * 30.0) * 1e-6 * dts[-1], abs=1e-15)


def test_env_delta_t_axis_feeds_d8_uq_surrogate(tmp_path):
    """D8 UQ 消费：环境包络 → 温度轴 σ → 代理蒙特卡洛良率（确定性）。"""
    import numpy as np

    from rfauto.service.uq_service import surrogate_yield

    axis = env_to_uq_axis("aec_q100_grade1", k_sigma=3.0)
    env = get_env("aec_q100_grade1")
    ts = np.linspace(env.t_min_c, env.t_max_c, 26)
    samples = []
    for t in ts:
        s11 = -20.0 + 1.0e-3 * (float(t) - axis["nominal_c"]) ** 2
        samples.append({"params": {"t_c": float(t)},
                        "metrics": {"s11_db_max_in_band": float(s11)}})
    samples[0] = {"params": {"t_c": axis["nominal_c"]},
                  "metrics": {"s11_db_max_in_band": -20.0}}
    data = {"bounds": {"t_c": [env.t_min_c, env.t_max_c]},
            "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                            "op": "max_below", "value": -15.0}],
            "samples": samples}
    p = tmp_path / "env_uq_samples.json"
    p.write_text(json.dumps(data), encoding="utf-8")

    kw = {"n": 300, "seed": 5, "ridge_lambda": 1e-6}
    r1 = surrogate_yield(str(p), {"t_c": axis["sigma_c"]}, **kw)
    r2 = surrogate_yield(str(p), {"t_c": axis["sigma_c"]}, **kw)
    assert r1["ok"], r1.get("errors")
    assert r1["nominal_params"]["t_c"] == pytest.approx(axis["nominal_c"])
    assert 0.0 < r1["yield_rate"] < 1.0
    assert json.dumps(r1) == json.dumps(r2)            # 同输入两次逐字节一致

    # 更宽温区（Grade 0）→ σ 更大 → 良率不升（包络确实驱动 UQ 结果）
    wide = env_to_uq_axis("aec_q100_grade0", k_sigma=3.0)
    assert wide["sigma_c"] > axis["sigma_c"]
    r3 = surrogate_yield(str(p), {"t_c": wide["sigma_c"]}, **kw)
    assert r3["ok"] and r3["yield_rate"] <= r1["yield_rate"]


def test_env_delta_t_axis_feeds_wp42_yield_analyzer():
    """WP4.2 良率消费：环境包络 σ → ToleranceAnalyzer Monte Carlo（同种子确定性）。"""
    from rfauto.optimization.tolerance import ToleranceAnalyzer

    axis = env_to_uq_axis("aec_q100_grade1", k_sigma=3.0)

    def objective_fn(params: dict[str, float]) -> dict[str, float]:
        # 温漂一阶模型：−(CTE + TCDk/2) = −31 ppm/K
        return {"f0_dev_ppm": -31.0 * (params["t_c"] - axis["nominal_c"])}

    specs = {"f0_dev_ppm": {"min": -1000.0, "max": 1000.0}}
    results = []
    for _ in range(2):
        analyzer = ToleranceAnalyzer(n_samples=200, seed=3)
        results.append(analyzer.analyze(
            {"t_c": axis["nominal_c"]},
            {"t_c": axis["half_range_c"]}, objective_fn, specs))
    r1, r2 = results
    assert r1["ok"] is True and r1["n_samples"] == 200
    assert 0.0 < r1["yield_rate"] < 1.0
    assert r1["yield_rate"] == r2["yield_rate"]         # 同种子确定性

    # 更宽温区（Grade 0）→ ±3σ 半宽更大 → 良率不升
    wide = env_to_uq_axis("aec_q100_grade0", k_sigma=3.0)
    analyzer = ToleranceAnalyzer(n_samples=200, seed=3)
    r3 = analyzer.analyze({"t_c": wide["nominal_c"]},
                          {"t_c": wide["half_range_c"]}, objective_fn, specs)
    assert r3["yield_rate"] <= r1["yield_rate"]

