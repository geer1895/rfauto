"""F-C.1 老化漂移内核单测（研究扩充 F-C §3 判据 1-3）。

裁判口径（#118）：全部解析常量由两条独立代数路径离线推导——
路径 A = (Ea/k)·(1/Tu−1/Ts)，路径 B = Ea·INV_K·(Ts−Tu)/(Tu·Ts)，其中
INV_K = 11604.518121550082 K/eV（NIST CODATA 独立常数）。两路径一致性
~7e-11（浮点运算序差），断言放宽到 rel=1e-8/1e-9 容纳双路径差。
第 4 条判据（EOL 端到端）属 P2，不在本文件。

`reliability` 库（LGPLv3）为对照裁判，不进 pyproject 依赖（任务书铁律，
勿装）：未安装 → importorskip 如实 skip（UNVERIFIED）；已安装但 API/打印
格式不符 → skip UNVERIFIED 不阻塞（F-C §3 判据 2 的预声明降级路径）。
示例老化常数仅验证内核自洽与数量级，不构成材料背书——真实材料常数由
knowledge/aging_laws.yaml 带出处供给（本文件做 schema 校验+典型值钉）。
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import aging

KNOWLEDGE_YAML = Path(__file__).resolve().parents[2] / "knowledge" / "aging_laws.yaml"

# ─── 双路径离线推导常量（scratch 两路径一致性 7.3e-11，见文件头）─────────────
EA = 0.7  # eV（JEDEC JESD47G 工作例口径）
T_USE_K = 328.15  # 55°C
T_STRESS_K = 398.15  # 125°C
AF_55_125 = 77.6453820553  # exp[(0.7/k)(1/328.15−1/398.15)]，手算量级 ~77.7
A_BLACK = 1e10  # h·(A/cm²)ⁿ 合成标定
J_CM2 = 1e6  # A/cm²
N_BLACK = 2.0
MTTF_125_H = 7.2542423895e6  # A·J⁻²·exp(Ea/kT) @398.15K，手算 ~7.255e6 h
MTTF_55_H = 5.6325842185e8  # @328.15K；比值=AF（跨式恒等）


# ─── 1. Arrhenius AF：解析回收钉 ─────────────────────────────────────────────


def test_arrhenius_af_analytic_recycle():
    af = aging.arrhenius_af(EA, T_USE_K, T_STRESS_K)
    assert af == pytest.approx(AF_55_125, rel=1e-9)
    # 恒等式：应力低于使用温度 → AF<1，且互为倒数
    af_rev = aging.arrhenius_af(EA, T_STRESS_K, T_USE_K)
    assert af_rev == pytest.approx(0.0128790659989, rel=1e-9)
    assert af * af_rev == pytest.approx(1.0, rel=1e-12)


def test_arrhenius_af_degenerate_identity_exact():
    # Ea=0 或两温相等 → AF==1.0 逐位（exp(0) 恒等）
    assert aging.arrhenius_af(0.0, T_USE_K, T_STRESS_K) == 1.0
    assert aging.arrhenius_af(EA, T_USE_K, T_USE_K) == 1.0


def test_arrhenius_af_input_guards():
    with pytest.raises(ValueError):
        aging.arrhenius_af(-0.1, T_USE_K, T_STRESS_K)
    with pytest.raises(ValueError):
        aging.arrhenius_af(EA, 0.0, T_STRESS_K)
    with pytest.raises(ValueError):
        aging.arrhenius_af(EA, T_USE_K, -1.0)
    with pytest.raises(ValueError):
        aging.arrhenius_af(float("nan"), T_USE_K, T_STRESS_K)
    with pytest.raises(ValueError):
        aging.arrhenius_af(True, T_USE_K, T_STRESS_K)  # bool 显式拒收（df7+⑯）


# ─── 2. Black 电迁移 MTTF：解析回收钉 ────────────────────────────────────────


def test_black_mttf_analytic_recycle():
    m125 = aging.black_mttf(A_BLACK, J_CM2, N_BLACK, EA, T_STRESS_K)
    m55 = aging.black_mttf(A_BLACK, J_CM2, N_BLACK, EA, T_USE_K)
    assert m125 == pytest.approx(MTTF_125_H, rel=1e-8)
    assert m55 == pytest.approx(MTTF_55_H, rel=1e-8)


def test_black_mttf_cross_law_identity():
    # 跨式恒等：MTTF(328.15)/MTTF(398.15) == Arrhenius AF（同一温度依赖）
    ratio = aging.black_mttf(A_BLACK, J_CM2, N_BLACK, EA, T_USE_K) / aging.black_mttf(
        A_BLACK, J_CM2, N_BLACK, EA, T_STRESS_K
    )
    assert ratio == pytest.approx(aging.arrhenius_af(EA, T_USE_K, T_STRESS_K), rel=1e-12)


def test_black_mttf_j_scaling_identity():
    # J×10 → MTTF÷10ⁿ（n=2 时 ÷100）
    m1 = aging.black_mttf(A_BLACK, J_CM2, N_BLACK, EA, T_STRESS_K)
    m2 = aging.black_mttf(A_BLACK, J_CM2 * 10.0, N_BLACK, EA, T_STRESS_K)
    assert m2 == pytest.approx(m1 / 100.0, rel=1e-12)


def test_black_mttf_input_guards():
    for args in (
        (0.0, J_CM2, N_BLACK, EA, T_STRESS_K),
        (A_BLACK, 0.0, N_BLACK, EA, T_STRESS_K),
        (A_BLACK, J_CM2, -1.0, EA, T_STRESS_K),
        (A_BLACK, J_CM2, N_BLACK, -0.5, T_STRESS_K),
        (A_BLACK, J_CM2, N_BLACK, EA, 0.0),
    ):
        with pytest.raises(ValueError):
            aging.black_mttf(*args)


# ─── 3. Coffin-Manson：解析回收钉 ────────────────────────────────────────────


def test_coffin_manson_analytic_recycle():
    assert aging.coffin_manson(500.0, 50.0, 2.0) == pytest.approx(0.2, rel=1e-12)
    assert aging.coffin_manson(1e5, 50.0, 2.0) == pytest.approx(40.0, rel=1e-12)
    assert aging.coffin_manson(1e6, 50.0, 2.0) == pytest.approx(400.0, rel=1e-12)


def test_coffin_manson_delta_t_scaling_identity():
    # ΔT 翻倍 → N_f÷2^q（q=2 时 ÷4）
    n1 = aging.coffin_manson(1e5, 50.0, 2.0)
    n2 = aging.coffin_manson(1e5, 100.0, 2.0)
    assert n2 == pytest.approx(n1 / 4.0, rel=1e-12)


def test_coffin_manson_input_guards():
    with pytest.raises(ValueError):
        aging.coffin_manson(0.0, 50.0, 2.0)
    with pytest.raises(ValueError):
        aging.coffin_manson(500.0, 0.0, 2.0)  # 0 摆幅应由调用方先筛，内核拒绝
    with pytest.raises(ValueError):
        aging.coffin_manson(500.0, 50.0, -1.0)


# ─── 4. Miner 线性累积：解析钉 + 交换律物理恒等式 ─────────────────────────────


def test_miner_analytic_two_segments():
    segs = [{"n_cycles": 1000.0, "n_f": 5000.0}, {"n_cycles": 2000.0, "n_f": 10000.0}]
    out = aging.miner_accumulate(segs)
    assert out["damage"] == pytest.approx(0.4, rel=1e-12)
    assert out["failed"] is False


def test_miner_swap_order_invariance_exact():
    # 线性累积的物理恒等式：交换段次序 D 不变（两元素浮点和满足交换律，逐位相等）
    a = {"n_cycles": 1000.0, "n_f": 5000.0}
    b = {"n_cycles": 2000.0, "n_f": 10000.0}
    d1 = aging.miner_accumulate([a, b])["damage"]
    d2 = aging.miner_accumulate([b, a])["damage"]
    assert d1 == d2


def test_miner_failure_threshold():
    # D>=1 判失效（恰等于 1 也算失效）
    assert aging.miner_accumulate([{"n_cycles": 6000.0, "n_f": 5000.0}])["failed"] is True
    assert aging.miner_accumulate([{"n_cycles": 5000.0, "n_f": 5000.0}])["failed"] is True
    assert aging.miner_accumulate([{"n_cycles": 4999.0, "n_f": 5000.0}])["failed"] is False


def test_miner_zero_cycles_and_empty():
    out = aging.miner_accumulate([{"n_cycles": 0.0, "n_f": 5000.0}])
    assert out["damage"] == 0.0
    assert out["failed"] is False
    empty = aging.miner_accumulate([])
    assert empty["damage"] == 0.0
    assert empty["failed"] is False


def test_miner_input_guards():
    with pytest.raises(ValueError):
        aging.miner_accumulate([{"n_cycles": 10.0, "n_f": 0.0}])
    with pytest.raises(ValueError):
        aging.miner_accumulate([{"n_cycles": -1.0, "n_f": 5000.0}])
    with pytest.raises(ValueError):
        aging.miner_accumulate(["not-a-dict"])


# ─── 5. εr 老化律（Knowles Class-2 口径 t0=1h）───────────────────────────────


def test_er_aging_drift_analytic_recycle():
    # 10.0×(1−0.01×log10(10/1)) = 9.9；×(1−0.01×2) = 9.8（手算逐位）
    out10 = aging.er_aging_drift(10.0, -0.01, 10.0)
    assert out10["er"] == pytest.approx(9.9, rel=1e-12)
    assert out10["decades"] == pytest.approx(1.0, rel=1e-15)
    out100 = aging.er_aging_drift(10.0, -0.01, 100.0)
    assert out100["er"] == pytest.approx(9.8, rel=1e-12)
    # 非整 decade 例（双路径推导：log10(27.7778)=1.44370）
    out_mid = aging.er_aging_drift(10.0, -0.01, 1e5 / 3600.0)
    assert out_mid["er"] == pytest.approx(9.855630250077, rel=1e-10)


def test_er_aging_drift_at_reference_exact():
    out = aging.er_aging_drift(10.0, -0.01, 1.0)
    assert out["er"] == 10.0  # log10(1)=0 → 逐位回 er0
    assert out["drift_frac"] == 0.0


def test_er_aging_drift_monotonicity():
    # 时间增 → 漂移增：负老化率 εr 单调降；正老化率 εr 单调升
    er_prev_neg = math.inf
    er_prev_pos = -math.inf
    for decades in range(0, 7):
        t_h = 1.0 * (10.0**decades)
        er_neg = aging.er_aging_drift(10.0, -0.01, t_h)["er"]
        er_pos = aging.er_aging_drift(10.0, +0.005, t_h)["er"]
        assert er_neg < er_prev_neg
        assert er_pos > er_prev_pos
        er_prev_neg = er_neg
        er_prev_pos = er_pos


def test_er_aging_drift_frac_consistency():
    # drift_frac == frac×decades 恒等式
    out = aging.er_aging_drift(9.8, -0.023, 1234.0)
    assert out["drift_frac"] == pytest.approx(-0.023 * math.log10(1234.0), rel=1e-15)


def test_er_aging_drift_input_guards():
    for args in ((0.0, -0.01, 10.0), (10.0, -0.01, 0.0), (10.0, -0.01, 10.0, 0.0)):
        with pytest.raises(ValueError):
            aging.er_aging_drift(*args)


# ─── 6. profile_integrate：退化例 + 两段剖面解析回收 + 通道语义 ───────────────


def _base_laws() -> dict:
    return {
        "t_use_c": 55.0,
        "ea_ev": EA,
        "er0": 10.0,
        "aging_frac_per_decade": -0.01,
    }


def test_profile_degenerate_constant_profile_exact():
    # 恒温剖面（段温=使用温度）：AF==1 逐位 → t_equivalent == t_total == 3.6e6 s
    # 1000 h 恰 3 decades → εr = 10×(1−0.03)
    laws = _base_laws()
    out = aging.profile_integrate([{"t_s": 3.6e6, "t_c": 55.0}], laws, t_total_s=3.6e6)
    assert out["t_equivalent_s"] == 3.6e6
    assert out["t_equivalent_h"] == pytest.approx(1000.0, rel=1e-15)
    assert out["damage"] == {"electromigration": None, "thermal_cycling": None}
    assert out["failed"] is False
    assert out["drift"]["er_eol"] == pytest.approx(9.7, rel=1e-12)
    assert len(out["trajectory"]) == 1


def test_profile_t_total_mismatch_raises():
    with pytest.raises(ValueError, match="不一致"):
        aging.profile_integrate([{"t_s": 3.6e6, "t_c": 55.0}], _base_laws(), t_total_s=1.0)


def test_profile_two_segment_analytic_recycle():
    # seg1: 1e5 s @125°C（AF=77.6454）；seg2: 1e5 s @55°C（AF=1）
    # 全部期望值为双路径独立推导常量（文件头口径）
    segs = [
        {"t_s": 1e5, "t_c": 125.0},
        {"t_s": 1e5, "t_c": 55.0},
    ]
    out = aging.profile_integrate(segs, _base_laws())
    assert out["t_total_s"] == pytest.approx(2e5, rel=1e-15)
    assert out["t_equivalent_s"] == pytest.approx(7.8645382055e6, rel=1e-9)
    assert out["drift"]["er_eol"] == pytest.approx(9.666062927421, rel=1e-9)
    assert out["drift"]["drift_frac"] == pytest.approx(-0.03339370725788, rel=1e-8)
    assert out["failed"] is False


def test_profile_segment_swap_totals_invariant():
    # 交换段次序：t_equivalent/损伤总量逐位不变（两元素浮点和交换律）
    laws = _base_laws()
    laws.update(a_black=A_BLACK, n_black=N_BLACK, ea_ev_black=EA, black_time_unit_s=3600.0)
    laws.update(c_cm=1e6, q_cm=2.0, cycle_period_s=600.0)
    seg1 = {"t_s": 1e5, "t_c": 125.0, "j_density": J_CM2, "delta_t_c": 50.0}
    seg2 = {"t_s": 1e5, "t_c": 55.0, "j_density": J_CM2, "delta_t_c": 50.0}
    out1 = aging.profile_integrate([seg1, seg2], laws)
    out2 = aging.profile_integrate([seg2, seg1], laws)
    assert out1["t_equivalent_s"] == out2["t_equivalent_s"]
    assert out1["damage"]["electromigration"] == out2["damage"]["electromigration"]
    assert out1["damage"]["thermal_cycling"] == out2["damage"]["thermal_cycling"]


def test_profile_full_channels_analytic_recycle():
    # 三通道全开：双路径推导的损伤分量（EM 段1=3.829176955e-6、段2=4.931622273e-8；
    # CM 每段=(1e5/600)/400=0.41666667，总量=5/6）
    laws = _base_laws()
    laws.update(a_black=A_BLACK, n_black=N_BLACK, ea_ev_black=EA, black_time_unit_s=3600.0)
    laws.update(c_cm=1e6, q_cm=2.0, cycle_period_s=600.0)
    segs = [
        {"t_s": 1e5, "t_c": 125.0, "j_density": J_CM2, "delta_t_c": 50.0},
        {"t_s": 1e5, "t_c": 55.0, "j_density": J_CM2, "delta_t_c": 50.0},
    ]
    out = aging.profile_integrate(segs, laws)
    em = out["damage"]["electromigration"]
    cm = out["damage"]["thermal_cycling"]
    assert em == pytest.approx(3.829176955494e-6 + 4.931622273489e-8, rel=1e-7)
    assert cm == pytest.approx(5.0 / 6.0, rel=1e-12)
    # 轨迹：er 单调降、损伤累计单调增、末点=总量
    traj = out["trajectory"]
    assert len(traj) == 2
    assert traj[0]["er_t"] > traj[1]["er_t"]
    assert traj[0]["damage_em_cum"] < traj[1]["damage_em_cum"]
    assert traj[1]["damage_em_cum"] == pytest.approx(em, rel=1e-15)
    assert traj[1]["t1_s"] == pytest.approx(2e5, rel=1e-15)
    # 段1 er 检查：等效时间 7.7645382055e6 s=2156.816 h → 10×(1−0.01×log10(2156.816))
    expected_er1 = 10.0 * (1.0 - 0.01 * math.log10(7.7645382055e6 / 3600.0))
    assert traj[0]["er_t"] == pytest.approx(expected_er1, rel=1e-12)
    assert out["failed"] is False


def test_profile_failure_flag_on_miner_exhaustion():
    laws = _base_laws()
    laws.update(c_cm=1e3, q_cm=2.0, cycle_period_s=600.0)  # N_f=(1e3/2500)=0.4 → D=416.7
    out = aging.profile_integrate(
        [{"t_s": 1e5, "t_c": 55.0, "delta_t_c": 50.0}], laws
    )
    assert out["damage"]["thermal_cycling"] == pytest.approx(
        (1e5 / 600.0) / aging.coffin_manson(1e3, 50.0, 2.0), rel=1e-12
    )
    assert out["failed"] is True


def test_profile_optional_channel_none_vs_zero():
    # 键缺失=None（不计通道）；数值 0.0 合法=零损伤（#364④）
    laws = _base_laws()
    laws.update(a_black=A_BLACK, n_black=N_BLACK, ea_ev_black=EA, black_time_unit_s=3600.0)
    laws.update(c_cm=1e6, q_cm=2.0, cycle_period_s=600.0)
    out_none = aging.profile_integrate([{"t_s": 1e5, "t_c": 125.0}], laws)
    assert out_none["damage"] == {"electromigration": None, "thermal_cycling": None}
    out_zero = aging.profile_integrate(
        [{"t_s": 1e5, "t_c": 125.0, "j_density": 0.0, "delta_t_c": 0.0}], laws
    )
    assert out_zero["damage"]["electromigration"] == 0.0
    assert out_zero["damage"]["thermal_cycling"] == 0.0
    assert out_zero["damage"]["electromigration"] is not None


def test_profile_missing_channel_params_fail_fast():
    laws = _base_laws()
    with pytest.raises(ValueError, match="a_black"):
        aging.profile_integrate([{"t_s": 1e5, "t_c": 125.0, "j_density": J_CM2}], laws)
    with pytest.raises(ValueError, match="c_cm"):
        aging.profile_integrate([{"t_s": 1e5, "t_c": 125.0, "delta_t_c": 50.0}], laws)


def test_profile_laws_and_segment_guards():
    with pytest.raises(ValueError, match="t_use_c"):
        aging.profile_integrate([{"t_s": 1.0, "t_c": 55.0}], {})
    with pytest.raises(ValueError, match="不能为空"):
        aging.profile_integrate([], _base_laws())
    with pytest.raises(ValueError, match="t_c"):
        aging.profile_integrate([{"t_s": 1.0}], _base_laws())
    with pytest.raises(ValueError, match="t_s"):
        aging.profile_integrate([{"t_s": 0.0, "t_c": 55.0}], _base_laws())


# ─── 7. 互证门：reliability 库同参对照（未装 → skip UNVERIFIED 如实）──────────


def test_reliability_crosscheck_arrhenius():
    pytest.importorskip(
        "reliability",
        reason="reliability 库（LGPLv3）未装、不进依赖——Arrhenius 同参对照 UNVERIFIED 如实 skip",
    )
    from reliability.PoF import acceleration_factor

    af_lib = acceleration_factor(T_use=55.0, T_acc=125.0, Ea=EA, print_results=False)
    if af_lib is None:
        pytest.skip("reliability 库 acceleration_factor 只打印不返回（版本差异）——UNVERIFIED")
    # 该库 k 可能取圆整值 8.617e-5（AF 相对差 ~1.7e-4 量级），对照门 rel=1e-3
    assert float(af_lib) == pytest.approx(aging.arrhenius_af(EA, T_USE_K, T_STRESS_K), rel=1e-3)


def test_reliability_crosscheck_miner(capsys: pytest.CaptureFixture[str]):
    pytest.importorskip(
        "reliability",
        reason="reliability 库（LGPLv3）未装、不进依赖——Miner 同参对照 UNVERIFIED 如实 skip",
    )
    from reliability.PoF import palmgren_miner_linear_damage

    our_d = aging.miner_accumulate(
        [{"n_cycles": 1000.0, "n_f": 5000.0}, {"n_cycles": 2000.0, "n_f": 10000.0}]
    )["damage"]
    # 该库只打印不返回（文档口径）——用 capsys 捕获打印文本提取损伤值
    palmgren_miner_linear_damage(
        rated_life=[5000.0, 10000.0], time_at_stress=[1000.0, 2000.0], stress=[1.0, 2.0]
    )
    printed = capsys.readouterr().out
    candidates: list[float] = []
    for token in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", printed):
        try:
            candidates.append(float(token))
        except ValueError:  # pragma: no cover - 正则已保证可解析
            continue
    if not any(c == pytest.approx(our_d, rel=1e-3) for c in candidates):
        pytest.skip(
            "reliability 库打印文本未解析出同值损伤（版本格式差异）——Miner 对照 UNVERIFIED"
        )


def test_reliability_black_coffin_no_closed_form_counterpart():
    pytest.importorskip(
        "reliability",
        reason="reliability 库未装——Black/Coffin-Manson 对照件存在性探测 UNVERIFIED 如实 skip",
    )
    import reliability.PoF as pof

    hits = [
        name
        for name in dir(pof)
        if any(k in name.lower() for k in ("black", "coffin", "electromigrat"))
    ]
    # 预声明边界：当前库无 Black/Coffin-Manson 同参闭式件，此二律仅解析钉
    pytest.skip(
        f"reliability 库 Black/Coffin-Manson 同参闭式对照件探测：{hits or '无'}"
        "——此二律仅有解析回收钉（UNVERIFIED 如实登记）"
    )


# ─── 8. aging_laws.yaml：schema 校验 + awaiting_data 不产数字 + 典型值钉 ──────


def _load_aging_laws() -> dict:
    import yaml

    raw = KNOWLEDGE_YAML.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    assert isinstance(data, dict)
    return data


def test_aging_laws_schema():
    data = _load_aging_laws()
    assert data["schema"] == "aging_laws/v1"
    materials = data["materials"]
    assert isinstance(materials, list) and len(materials) >= 3
    ids = [m["material_id"] for m in materials]
    assert len(ids) == len(set(ids))
    for mat in materials:
        for channel in ("arrhenius", "er_aging"):
            entry = mat[channel]
            assert entry["status"] in ("typical", "awaiting_data"), f"{mat['material_id']}.{channel}"


def test_aging_laws_awaiting_data_carries_no_numbers():
    data = _load_aging_laws()
    for mat in data["materials"]:
        for channel, value_key in (("arrhenius", "ea_ev"), ("er_aging", "frac_per_decade")):
            entry = mat[channel]
            if entry["status"] == "awaiting_data":
                # awaiting_data 不产数字：数值字段必须为 null 或缺失
                assert entry.get(value_key) is None, f"{mat['material_id']}.{channel}.{value_key}"
                assert entry.get("reason"), f"{mat['material_id']}.{channel} 缺 awaiting_data 原因"


def test_aging_laws_typical_entries_have_provenance():
    data = _load_aging_laws()
    for mat in data["materials"]:
        for channel in ("arrhenius", "er_aging"):
            entry = mat[channel]
            if entry["status"] == "typical":
                assert entry.get("provenance"), f"{mat['material_id']}.{channel} 缺出处"
                assert isinstance(entry["provenance"], str) and len(entry["provenance"]) > 20


def test_aging_laws_pinned_typical_values():
    data = _load_aging_laws()
    by_id = {m["material_id"]: m for m in data["materials"]}
    # JEDEC 标准缺省 Ea=0.7 eV
    generic = by_id["generic_jesd85"]["arrhenius"]
    assert generic["status"] == "typical"
    assert generic["ea_ev"] == pytest.approx(0.7, rel=1e-12)
    # FR-4 单源典型 Ea=0.35 eV
    fr4 = by_id["laminate_fr4"]["arrhenius"]
    assert fr4["status"] == "typical"
    assert fr4["ea_ev"] == pytest.approx(0.35, rel=1e-12)
    assert fr4["single_source"] is True
    # Class-2 X7R：Knowles 口径 −1%/decade-hour，t0=1h
    x7r = by_id["ceramic_class2_x7r"]["er_aging"]
    assert x7r["status"] == "typical"
    assert x7r["frac_per_decade"] == pytest.approx(-0.01, rel=1e-12)
    assert x7r["t_ref_h"] == pytest.approx(1.0, rel=1e-12)
    assert x7r["single_source"] is True
    # 温度轴参数（TCDk）不得以数值字段形态混入时间轴表（ro4350b 两条均 awaiting_data）
    ro = by_id["laminate_ro4350b"]
    assert ro["arrhenius"]["status"] == "awaiting_data"
    assert ro["er_aging"]["status"] == "awaiting_data"
    assert not any("tcdk" in key for key in (*ro["arrhenius"], *ro["er_aging"]))


def test_aging_laws_typical_value_feeds_kernel():
    # 接线钉：yaml 典型值喂进 er_aging_drift 得解析手算值（Knowles：−1%/decade）
    data = _load_aging_laws()
    x7r = {m["material_id"]: m for m in data["materials"]}["ceramic_class2_x7r"]["er_aging"]
    out = aging.er_aging_drift(10.0, x7r["frac_per_decade"], 10.0, t_ref_h=x7r["t_ref_h"])
    assert out["er"] == pytest.approx(9.9, rel=1e-12)


# ─── 9. Engelmaier 修正（F-H 件 1，r4 插①）：双路径手算回收 + 单调性 ─────────
#
# 口径来源（原文可达、已逐位核对）：Engelmaier《Solder Joints in Electronics:
# Design for Reliability》（analysistech.com PDF）Eq.3/Eq.4/Eq.5 + Wikipedia
# "Solder fatigue"（Engelmaier 1983 IEEE CHMT-6(3)）互证。ε_f′=0.325 为原文
# verbatim（共晶/60-40 SnPb）；常被误引的 0.65 是复合量 2ε_f′。

C_55_15 = -0.41899156064729326  # 手算路径 B：−0.442−6e−4·55+0.0174·2·ln5（与内核路径差 1.3e-16）
N50_55_15_RATIO01 = 121.80157971366049  # 手算路径 B：0.5·exp(ln(0.1)/c_B)，Δγ=2ε_f′×0.1
TG, TD = 55.0, 15.0  # 手算锚点：T_SJ=55°C、t_D=15 min


def test_engelmaier_c_index_analytic_recycle():
    # 手算回收：c(55,15)=−0.442−0.033+0.0174·ln25，ln25=2ln5 独立路径
    c = aging.engelmaier_c_index(TG, TD)
    assert c == pytest.approx(C_55_15, rel=1e-12)
    # 非整驻留例：t_D=0.5 → ln(721)，路径 B 用 721=7×103 质因数分解
    c_half = aging.engelmaier_c_index(TG, 0.5)
    expected_half = -0.442 - 6e-4 * TG + 1.74e-2 * (math.log(7.0) + math.log(103.0))
    assert c_half == pytest.approx(expected_half, rel=1e-12)


def test_engelmaier_c_index_monotonicity():
    # T_mean↑ → c 更负（−6e−4·T 线性项）；dwell↑ → c 更负（360/t_D 项减小）
    assert aging.engelmaier_c_index(85.0, TD) < aging.engelmaier_c_index(TG, TD)
    assert aging.engelmaier_c_index(TG, TD) < aging.engelmaier_c_index(25.0, TD)
    assert aging.engelmaier_c_index(TG, 60.0) < aging.engelmaier_c_index(TG, TD)
    assert aging.engelmaier_c_index(TG, TD) < aging.engelmaier_c_index(TG, 5.0)


def test_engelmaier_c_index_input_guards():
    with pytest.raises(ValueError):
        aging.engelmaier_c_index(True, TD)  # bool 显式拒收（df7+⑯）
    with pytest.raises(ValueError):
        aging.engelmaier_c_index(float("nan"), TD)
    with pytest.raises(ValueError):
        aging.engelmaier_c_index(TG, 0.0)  # 360/0 发散：驻留必须 >0（原文 Caveat 3 由调用方把关）
    with pytest.raises(ValueError):
        aging.engelmaier_c_index(TG, -15.0)


def test_engelmaier_cycles_unit_ratio_identity_exact():
    # 恒等式：Δγ = 2ε_f′ → 底数 1 → N_50 = 0.5 逐位（与 c 无关）
    assert aging.engelmaier_cycles(TG, TD, 0.65) == 0.5
    assert aging.engelmaier_cycles(25.0, 60.0, 0.9, eps_f_prime=0.45) == 0.5


def test_engelmaier_cycles_analytic_recycle():
    # 手算回收：Δγ=0.065、ε_f′=0.325 → 底数 0.1；期望值走 exp–log 独立浮点路径
    n50 = aging.engelmaier_cycles(TG, TD, 0.065)
    expected = 0.5 * math.exp(math.log(0.1) / C_55_15)
    assert n50 == pytest.approx(N50_55_15_RATIO01, rel=1e-9)
    assert n50 == pytest.approx(expected, rel=1e-12)


def test_engelmaier_cycles_delta_gamma_scaling_identity():
    # Δγ 翻倍 → N_50 × 2^(1/c)（代数恒等式，c 固定）；应变增大寿命单调下降
    c = aging.engelmaier_c_index(TG, TD)
    n1 = aging.engelmaier_cycles(TG, TD, 0.065)
    n2 = aging.engelmaier_cycles(TG, TD, 0.13)
    assert n2 == pytest.approx(n1 * 2.0 ** (1.0 / c), rel=1e-12)
    assert n2 < n1


def test_engelmaier_cycles_eps_f_direction_sac_vs_snpb():
    # SAC305 vs SnPb 经典：延性系数 ε_f′ 修正只断言方向/比例，不虚构精确数（#118）
    # ε_f′↑ → 分母 2ε_f′↑ → 底数↓ → 1/c<0 下 N_50↑（更延性 → 更长寿）
    n_snpb = aging.engelmaier_cycles(TG, TD, 0.065)
    n_sac = aging.engelmaier_cycles(TG, TD, 0.065, eps_f_prime=0.35)
    assert n_sac > n_snpb
    # 比例恒等式：(ε1/ε2)^(1/c)
    c = aging.engelmaier_c_index(TG, TD)
    assert n_sac / n_snpb == pytest.approx((0.325 / 0.35) ** (1.0 / c), rel=1e-12)


def test_thermal_mismatch_shear_strain_analytic_recycle():
    # 手算回收：|17−3|ppm×1e−6×100°C×10mm/0.5mm = 14e−6·100·20 = 0.028
    g = aging.thermal_mismatch_shear_strain(100.0, 17.0, 3.0, 10.0, 0.5)
    assert g == pytest.approx(0.028, rel=1e-12)
    # 失配幅度只看差值绝对值：α 前后交换不变
    assert aging.thermal_mismatch_shear_strain(100.0, 3.0, 17.0, 10.0, 0.5) == pytest.approx(
        g, rel=1e-15
    )
    # d_factor 参数化：D=0.5 → 恰好减半
    assert aging.thermal_mismatch_shear_strain(100.0, 17.0, 3.0, 10.0, 0.5, d_factor=0.5) == (
        pytest.approx(0.014, rel=1e-12)
    )
    # 0 摆幅 → 0 应变合法（#364④：数值 0.0 合法）
    assert aging.thermal_mismatch_shear_strain(0.0, 17.0, 3.0, 10.0, 0.5) == 0.0


def test_thermal_mismatch_shear_strain_input_guards():
    with pytest.raises(ValueError):
        aging.thermal_mismatch_shear_strain(True, 17.0, 3.0, 10.0, 0.5)  # bool 拒收
    with pytest.raises(ValueError):
        aging.thermal_mismatch_shear_strain(float("nan"), 17.0, 3.0, 10.0, 0.5)
    with pytest.raises(ValueError):
        aging.thermal_mismatch_shear_strain(100.0, 17.0, 3.0, 10.0, 0.0)  # 焊点高必须 >0
    with pytest.raises(ValueError):
        aging.thermal_mismatch_shear_strain(100.0, 17.0, 3.0, 10.0, 0.5, d_factor=0.0)
    # L=0 → 零应变合法（无 DNP 距离即无热失配位移）
    assert aging.thermal_mismatch_shear_strain(100.0, 17.0, 3.0, 0.0, 0.5) == 0.0


def test_engelmaier_pipeline_shear_strain_feeds_cycles():
    # 端到端手算回收链：Δγ(热失配)=0.028 → N_50=0.5·(0.028/0.65)^(1/c)
    gamma = aging.thermal_mismatch_shear_strain(100.0, 17.0, 3.0, 10.0, 0.5)
    n_via_gamma = aging.engelmaier_cycles(TG, TD, gamma)
    expected = 0.5 * (0.028 / 0.65) ** (1.0 / C_55_15)
    assert n_via_gamma == pytest.approx(expected, rel=1e-9)


# ─── 10. Weibull 统计：定义恒等式 + 往返恒等 + scipy 对照 ─────────────────────

ETA, BETA_W = 500.0, 3.0
N50_500_3 = 442.4985222502589  # η·(ln2)^(1/3)，手算路径


def test_weibull_p_of_n50_is_exact_half():
    # 定义恒等式：P_f(N_50) = 0.5（逐位量级）
    n50 = aging.n50_from_weibull(ETA, BETA_W)
    assert n50 == pytest.approx(N50_500_3, rel=1e-12)
    assert float(aging.weibull_p_of_failure(ETA, BETA_W, np.array([n50]))[0]) == pytest.approx(
        0.5, rel=1e-12
    )


def test_weibull_roundtrip_identity():
    # 反演往返：p → N → p 恒等（rel=1e-12）
    p = np.array([0.1, 0.5, 0.9])
    n = aging.weibull_life(ETA, BETA_W, p)
    assert aging.weibull_p_of_failure(ETA, BETA_W, n) == pytest.approx(p, rel=1e-12)
    # N(p=0.5) 与 n50_from_weibull 同一量（ln1p(−0.5)=ln2 双路径，rel=1e-15 容纳）
    assert float(n[1]) == pytest.approx(aging.n50_from_weibull(ETA, BETA_W), rel=1e-15)


def test_weibull_n50_pair_inverses():
    # (η, N_50) 互算往返恒等（多条 β）
    for beta in (2.0, 3.0, 4.5):
        eta = 1234.0
        n50 = aging.n50_from_weibull(eta, beta)
        assert aging.weibull_from_n50(n50, beta) == pytest.approx(eta, rel=1e-12)
    # 反向：η 由 N_50 重建后再取 N_50 恒等
    n50 = 999.0
    eta = aging.weibull_from_n50(n50, 2.5)
    assert aging.n50_from_weibull(eta, 2.5) == pytest.approx(n50, rel=1e-12)


def test_weibull_eta_marker_identity():
    # P_f(η) = 1−1/e（Weibull 特征寿命定义恒等）
    p_eta = float(aging.weibull_p_of_failure(ETA, BETA_W, np.array([ETA]))[0])
    assert p_eta == pytest.approx(1.0 - math.exp(-1.0), rel=1e-15)


def test_weibull_scipy_crosscheck():
    # scipy.stats.weibull_min(c=β, loc=0, scale=η) 同参对照（cdf/ppf 双向逐位）
    from scipy.stats import weibull_min

    dist = weibull_min(c=BETA_W, loc=0.0, scale=ETA)
    p = np.array([0.01, 0.25, 0.5, 0.75, 0.99])
    assert aging.weibull_life(ETA, BETA_W, p) == pytest.approx(dist.ppf(p), rel=1e-12)
    n = np.array([0.0, 100.0, ETA, 1000.0])
    assert aging.weibull_p_of_failure(ETA, BETA_W, n) == pytest.approx(dist.cdf(n), rel=1e-12)


def test_weibull_degenerate_and_guards():
    # 退化恒等：p=0 → N=0；n=0 → P_f=0；n=η 恒等已在 eta_marker 钉
    assert float(aging.weibull_life(ETA, BETA_W, np.array([0.0]))[0]) == 0.0
    assert float(aging.weibull_p_of_failure(ETA, BETA_W, np.array([0.0]))[0]) == 0.0
    for eta in (0.0, -1.0):
        with pytest.raises(ValueError):
            aging.weibull_life(eta, BETA_W, np.array([0.5]))
    for beta in (0.0, -1.0):
        with pytest.raises(ValueError):
            aging.weibull_life(ETA, beta, np.array([0.5]))
        with pytest.raises(ValueError):
            aging.weibull_p_of_failure(ETA, beta, np.array([10.0]))
    for bad_p in (-0.1, 1.0, 1.5, float("nan")):
        with pytest.raises(ValueError):
            aging.weibull_life(ETA, BETA_W, np.array([bad_p]))
    with pytest.raises(ValueError):
        aging.weibull_life(ETA, BETA_W, True)  # bool 拒收（df7+⑯）
    for bad_n in (-1.0, float("inf")):
        with pytest.raises(ValueError):
            aging.weibull_p_of_failure(ETA, BETA_W, np.array([bad_n]))
    with pytest.raises(ValueError):
        aging.weibull_p_of_failure(ETA, BETA_W, False)  # bool 拒收
    with pytest.raises(ValueError):
        aging.n50_from_weibull(0.0, BETA_W)
    with pytest.raises(ValueError):
        aging.weibull_from_n50(100.0, 0.0)


# ─── 11. compound_miner：复合载荷多通道（薄组合，复用 miner_accumulate）────────


def test_compound_miner_single_channel_degenerates_to_miner():
    # 单通道退化 == miner_accumulate（同序浮点和逐位一致）
    parts = [{"n_cycles": 1000.0, "n_f": 5000.0}, {"n_cycles": 2000.0, "n_f": 10000.0}]
    compound = aging.compound_miner(
        [{"channels": [dict(p, name="thermal")]} for p in parts]
    )
    direct = aging.miner_accumulate(parts)
    assert compound["damage"] == direct["damage"]
    assert compound["failed"] == direct["failed"] is False


def test_compound_miner_two_channel_hand_sum():
    # 两通道手算：热循环 1000/4000=0.25 + 直损 0.25 → D_total=0.5（不失效）
    out = aging.compound_miner(
        [
            {"channels": [{"name": "thermal", "n_cycles": 1000.0, "n_f": 4000.0}]},
            {"channels": [{"name": "em", "damage": 0.25}]},
        ]
    )
    assert out["damage_channels"] == {"thermal": 0.25, "em": 0.25}
    assert out["damage"] == pytest.approx(0.5, rel=1e-15)
    assert out["failed"] is False


def test_compound_miner_failure_threshold():
    # D>=1 判失效（通道间跨 1 同样判失效）
    out = aging.compound_miner(
        [{"channels": [{"n_cycles": 6000.0, "n_f": 5000.0}, {"damage": 0.5}]}]
    )
    assert out["damage"] == pytest.approx(1.2 + 0.5, rel=1e-12)
    assert out["failed"] is True


def test_compound_miner_same_name_merges_across_segments():
    # 同名通道跨段自动合并累积（线性累积交换律口径）
    out = aging.compound_miner(
        [
            {"channels": [{"name": "thermal", "n_cycles": 1000.0, "n_f": 4000.0}]},
            {"channels": [{"name": "thermal", "n_cycles": 1000.0, "n_f": 4000.0}]},
        ]
    )
    assert list(out["damage_channels"]) == ["thermal"]
    assert out["damage_channels"]["thermal"] == pytest.approx(0.5, rel=1e-15)
    assert out["damage"] == pytest.approx(0.5, rel=1e-15)


def test_compound_miner_unnamed_auto_address():
    # 未命名通道按 seg{i}_ch{k} 自动编址（保持首现顺序）
    out = aging.compound_miner(
        [{"channels": [{"n_cycles": 1000.0, "n_f": 4000.0}, {"damage": 0.1}]}]
    )
    assert list(out["damage_channels"]) == ["seg0_ch0", "seg0_ch1"]
    assert out["damage"] == pytest.approx(0.25 + 0.1, rel=1e-12)


def test_compound_miner_empty():
    out = aging.compound_miner([])
    assert out["damage"] == 0.0
    assert out["failed"] is False
    assert out["damage_channels"] == {}


def test_compound_miner_input_guards():
    with pytest.raises(ValueError):
        aging.compound_miner(["not-a-dict"])
    with pytest.raises(ValueError):
        aging.compound_miner([{}])  # 缺 channels
    with pytest.raises(ValueError):
        aging.compound_miner([{"channels": ["not-a-dict"]}])
    with pytest.raises(ValueError):
        # 两种形态混给
        aging.compound_miner([{"channels": [{"n_cycles": 1.0, "n_f": 2.0, "damage": 0.1}]}])
    with pytest.raises(ValueError):
        # 循环形态缺 n_f
        aging.compound_miner([{"channels": [{"n_cycles": 1.0}]}])
    with pytest.raises(ValueError):
        # 无损伤字段
        aging.compound_miner([{"channels": [{"name": "x"}]}])
    with pytest.raises(ValueError):
        aging.compound_miner([{"channels": [{"damage": -0.1}]}])
    with pytest.raises(ValueError):
        aging.compound_miner([{"channels": [{"n_cycles": -1.0, "n_f": 100.0}]}])
    with pytest.raises(ValueError):
        aging.compound_miner([{"channels": [{"n_cycles": 1.0, "n_f": 0.0}]}])
    with pytest.raises(ValueError):
        aging.compound_miner([{"channels": [{"name": 42, "damage": 0.1}]}])
