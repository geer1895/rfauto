"""EM-9 EMI 诊断知识库测试（round17，C 流）。

锚树（任务书口径）：
- 知识条目完整性：域×条数与 id 全名单封闭断言（扩库=显式改锚，#231 注册表
  消费者文化）+ 字段完备（symptom/cause/evidence_check/remedy/source 非空）
  + 出处等级如实（standard 级必引标准号；坑号 #NNN 全库集合封闭钉）；
- 特征词表封闭：FEATURE_CATALOG/FEATURE_ORIGIN 键集一致 + 来源域分布钉；
- 合成观测→预期诊断命中：谱签名四态（时钟奇次族/偶次对称破坏/宽带包/宽带
  底噪抬升）+ CM/DM + 近场三板斧 + ESD 四路径，命中 id 与排序全钉；
- 确定性：同输入两次输出逐位一致（JSON sort_keys 往返逐字节同，premortem
  同纪律）；
- 观测面：spectrum_peaks 峰表（窄/宽带分类+带缘削边 undetermined 如实）+
  margin_observations 只读消费 emi_filter.margin_report（violation 广泛/
  孤立/贴线/带外，#364④ is-not-None 纪律）；
- 负例：未知观测特征 ValueError（不静默降级）/未知域 ValueError/零命中 []/
  平底无峰谱零命中（宽带抬升判据要求可分峰结构——如实不判）。
"""

from __future__ import annotations

import json
import math
import re

import numpy as np
import pytest

from rfauto.core.emi_diagnostics import (
    BROADBAND_HOT_FRACTION,
    CATEGORY_LABELS,
    CATEGORY_PREFIXES,
    DEFAULT_PEAK_PROMINENCE_DB,
    DIAGNOSTIC_CATEGORIES,
    DIAGNOSTIC_LIBRARY,
    EMI_DIAGNOSTICS_SCHEMA,
    FEATURE_CATALOG,
    FEATURE_ORIGIN,
    FEATURE_ORIGINS,
    SOURCE_LEVELS,
    emi_diagnose,
    margin_observations,
    spectrum_observations,
    spectrum_peaks,
)
from rfauto.core.emi_filter import fcc_limits_part15, margin_report

#: 域×条数显式钉（扩库必须显式改此锚——防"顺手加一条"不审出处）。
EXPECTED_CATEGORY_COUNTS: dict[str, int] = {
    "spectrum_signature": 7,
    "cm_dm_split": 4,
    "near_field": 4,
    "esd_path": 4,
}

#: 域×条目 id 全名单封闭钉（顺序=entry_id 字典序）。
EXPECTED_ENTRY_IDS: dict[str, list[str]] = {
    "spectrum_signature": [f"SIG-{i:02d}" for i in range(1, 8)],
    "cm_dm_split": [f"CMD-{i:02d}" for i in range(1, 5)],
    "near_field": [f"NF-{i:02d}" for i in range(1, 5)],
    "esd_path": [f"ESD-{i:02d}" for i in range(1, 5)],
}

#: 条目 dict 键契约（JSON 消费面稳定钉；cause/evidence_check/remedy_ref 为
#: 任务书查询面必含键）。
ENTRY_DICT_KEYS = {
    "entry_id", "category", "symptom", "trigger_features", "cause",
    "evidence_check", "remedy", "remedy_ref", "source", "source_level",
    "lesson_refs",
}

#: 出处等级词根钉（standard 级 source 必须命中其一；测试侧独立钉，防书级
#: 知识冒充标准条文）。
STANDARD_NAME_TOKENS = ("IEC", "CISPR", "47 CFR", "ETSI", "MIL-STD")

#: 全库坑号背书集合封闭钉（新坑号=显式改锚）。
EXPECTED_LESSON_REFS = {"#298", "#281"}

#: 特征词表规模与来源域分布钉。
EXPECTED_FEATURE_COUNT = 30
EXPECTED_ORIGIN_COUNTS = {
    "auto_spectrum": 10,
    "auto_margin": 7,
    "instrument": 4,
    "checklist": 9,
}

_PIT_RE = re.compile(r"^#\w+$")


# ---------------------------------------------------------------------------
# 合成谱构造（确定性；单音=单栅格点置峰，隆起=升余弦 sqrt 剖面宽包）
# ---------------------------------------------------------------------------


def _tone_spectrum(tone_freqs: list[float], f_max: float, df: float = 1e5,
                   floor_db: float = -50.0, peak_db: float = 0.0,
                   ) -> tuple[np.ndarray, np.ndarray]:
    """单栅格点窄音谱（音间距 ≥ 数十栅格，互不粘连；频率轴从正值起）。"""
    n = round(f_max / df) + 1
    f = df * (1.0 + np.arange(n, dtype=float))
    amp = np.full(n, floor_db)
    for ft in tone_freqs:
        amp[round(ft / df) - 1] = peak_db  # f[i]=(i+1)·df，音位回退一格
    return f, amp


def _hump_spectrum(width_bins: int, n: int = 201, df: float = 1e6,
                   center: int = 100, floor_db: float = -20.0, peak_db: float = 20.0,
                   ) -> tuple[np.ndarray, np.ndarray]:
    """升余弦 sqrt 剖面宽带包（单调自中心下降，单一局部极大，确定性）。"""
    f = df * (1.0 + np.arange(n, dtype=float))
    amp = np.full(n, floor_db)
    for j in range(-width_bins, width_bins + 1):
        idx = center + j
        if 0 <= idx < n:
            profile = (0.5 * (1.0 + math.cos(math.pi * j / width_bins))) ** 0.5
            amp[idx] = floor_db + (peak_db - floor_db) * profile
    return f, amp


# ---------------------------------------------------------------------------
# 知识条目完整性（封闭断言）
# ---------------------------------------------------------------------------


def test_library_shape_pinned() -> None:
    """域×条数+id 全名单封闭：扩库必须显式改锚。"""
    assert EMI_DIAGNOSTICS_SCHEMA == "rfauto-emi-diagnostics-v1"
    assert DIAGNOSTIC_CATEGORIES == ("spectrum_signature", "cm_dm_split", "near_field", "esd_path")
    by_cat: dict[str, list[str]] = {c: [] for c in DIAGNOSTIC_CATEGORIES}
    for e in DIAGNOSTIC_LIBRARY:
        by_cat[e.category].append(e.entry_id)
    for cat, n in EXPECTED_CATEGORY_COUNTS.items():
        assert len(by_cat[cat]) == n, f"{cat} 条数漂移（扩库显式改锚）"
        assert sorted(by_cat[cat]) == EXPECTED_ENTRY_IDS[cat]
    assert len({e.entry_id for e in DIAGNOSTIC_LIBRARY}) == len(DIAGNOSTIC_LIBRARY)


def test_entry_fields_complete_and_honest() -> None:
    """字段完备+出处等级如实：standard 级必引标准号；坑号集合封闭。"""
    all_lessons: set[str] = set()
    for e in DIAGNOSTIC_LIBRARY:
        assert e.symptom and e.cause and e.remedy and e.remedy_ref
        assert e.evidence_check and all(s.strip() for s in e.evidence_check)
        assert len(e.source) >= 15, f"{e.entry_id}: 出处过短（等级自洽要求实质引用）"
        assert e.source_level in SOURCE_LEVELS
        assert e.trigger_features and all(t in FEATURE_CATALOG for t in e.trigger_features)
        assert e.entry_id.startswith(CATEGORY_PREFIXES[e.category])
        assert e.category in CATEGORY_LABELS
        if e.source_level == "standard":
            assert any(tok in e.source for tok in STANDARD_NAME_TOKENS), (
                f"{e.entry_id}: standard 级出处未引标准号")
        for ref in e.lesson_refs:
            assert _PIT_RE.match(ref), f"{e.entry_id}: 坑号格式 {ref!r} 不合规"
            all_lessons.add(ref)
    assert all_lessons == EXPECTED_LESSON_REFS


def test_entry_to_dict_keys_pinned() -> None:
    """to_dict 键契约（含任务书查询面必含的 cause/evidence_check/remedy_ref）。"""
    for e in DIAGNOSTIC_LIBRARY:
        assert set(e.to_dict()) == ENTRY_DICT_KEYS


def test_feature_catalog_pinned() -> None:
    """特征词表封闭：规模+来源域分布+目录/来源两表键集一致。"""
    assert len(FEATURE_CATALOG) == EXPECTED_FEATURE_COUNT
    assert set(FEATURE_ORIGIN) == set(FEATURE_CATALOG)
    assert all(doc.strip() for doc in FEATURE_CATALOG.values())
    assert set(FEATURE_ORIGINS) == set(FEATURE_ORIGIN.values())
    counts = {o: 0 for o in FEATURE_ORIGINS}
    for origin in FEATURE_ORIGIN.values():
        counts[origin] += 1
    assert counts == EXPECTED_ORIGIN_COUNTS


# ---------------------------------------------------------------------------
# 查询面：合成观测→预期诊断命中 + 确定性 + 负例
# ---------------------------------------------------------------------------


def test_diagnose_clock_harmonics_hit_and_order() -> None:
    """时钟谐波合成观测：SIG-01 特异度居首+同域同特异度按 id 序。"""
    obs = {
        "narrowband_peaks_present": True,
        "harmonic_series_present": True,
        "odd_harmonics_only": True,
    }
    hits = emi_diagnose(obs)
    assert [h["entry_id"] for h in hits] == ["SIG-01", "SIG-05", "SIG-06"]
    for key in ("cause", "evidence_check", "remedy_ref"):
        assert key in hits[0]
    assert hits[0]["source_level"] == "textbook"
    assert hits[0]["lesson_refs"] == ["#298"]


def test_diagnose_dcdc_broadband_hit() -> None:
    """宽带底噪抬升：SIG-02 命中且不误报时钟族。"""
    hits = emi_diagnose({"broadband_floor_rise": True})
    assert [h["entry_id"] for h in hits] == ["SIG-02"]


def test_diagnose_even_harmonics_symmetry_hit() -> None:
    """偶次谐波=对称性破坏（任务书典型条目）。"""
    hits = emi_diagnose({"even_harmonics_only": True})
    assert [h["entry_id"] for h in hits] == ["SIG-04"]


def test_diagnose_manual_observations_hits() -> None:
    """CM/DM + 近场三板斧 + ESD 合成观测逐例命中（AND 同击语义）。"""
    cases: list[tuple[dict[str, object], list[str]]] = [
        ({"cm_dm_split_cm_dominant": True}, ["CMD-01"]),
        ({"cm_current_microamp_class": True}, ["CMD-02"]),
        ({"cm_dm_split_dm_dominant": True}, ["CMD-03"]),
        ({"cm_choke_applied_reduced": True}, ["CMD-04"]),
        ({"nf_h_probe_peak": True, "nf_e_probe_quiet": True}, ["NF-01"]),
        ({"nf_e_probe_peak": True, "nf_h_probe_quiet": True}, ["NF-02"]),
        ({"nf_peak_follows_cable": True}, ["NF-03"]),
        ({"nf_e_probe_peak": True, "nf_h_probe_peak": True}, ["NF-04"]),
        ({"esd_contact_fail": True}, ["ESD-01"]),
        ({"esd_air_fail_only": True}, ["ESD-02"]),
        ({"esd_fail_disappears_cable_removed": True}, ["ESD-03"]),
        ({"esd_soft_reset_only": True}, ["ESD-04"]),
    ]
    for obs, expected in cases:
        hits = emi_diagnose(obs)
        assert [h["entry_id"] for h in hits] == expected, f"obs={obs}"


def test_diagnose_cross_face_and_conjunction() -> None:
    """跨观测面 AND 合击（SIG-07）+ 特异度排序（双特征条目先于单特征）。"""
    obs = {"violations_widespread": True, "broadband_floor_rise": True,
           "broadband_peaks_present": True}
    hits = emi_diagnose(obs)
    assert [h["entry_id"] for h in hits] == ["SIG-07", "SIG-02", "SIG-03"]


def test_diagnose_deterministic_byte_identical() -> None:
    """同输入两次输出逐位一致（JSON sort_keys 往返逐字节同）。"""
    obs = {"narrowband_peaks_present": True, "harmonic_series_present": True,
           "broadband_floor_rise": True}
    a = json.dumps(emi_diagnose(obs), ensure_ascii=False, sort_keys=True)
    b = json.dumps(emi_diagnose(obs), ensure_ascii=False, sort_keys=True)
    assert a == b


def test_diagnose_empty_observations_and_falsy_values() -> None:
    """空观测/全假值/纯信息型特征（int 计数）→ 零命中（如实空表）。"""
    assert emi_diagnose({}) == []
    assert emi_diagnose({"narrowband_peaks_present": False, "harmonic_series_present": 0}) == []
    assert emi_diagnose({"spectrum_peak_count": 3}) == []
    assert emi_diagnose({"spectrum_peak_count": 0}) == []


def test_diagnose_negative_unknown_feature_and_bad_types() -> None:
    """负例契约：未知特征/未知域 ValueError（不静默降级）；非 Mapping TypeError。"""
    with pytest.raises(ValueError, match="未知观测特征"):
        emi_diagnose({"narrowband_peakz": True})  # 错别字必须炸，不静默零命中
    with pytest.raises(ValueError, match="未知诊断域"):
        emi_diagnose({"esd_contact_fail": True}, categories=("nonexistent",))
    with pytest.raises(TypeError):
        emi_diagnose(["narrowband_peaks_present"])  # type: ignore[arg-type]


def test_diagnose_categories_filter() -> None:
    """域过滤：限定 esd_path 时谱签名命中被排除；单域合法值可用。"""
    obs = {"narrowband_peaks_present": True, "harmonic_series_present": True,
           "esd_contact_fail": True}
    assert [h["entry_id"] for h in emi_diagnose(obs, categories=("esd_path",))] == ["ESD-01"]
    assert emi_diagnose(obs, categories=DIAGNOSTIC_CATEGORIES) == emi_diagnose(obs)


# ---------------------------------------------------------------------------
# 观测面 A：谱签名特征提取
# ---------------------------------------------------------------------------


def test_spectrum_clock_odd_harmonics() -> None:
    """时钟奇次谐波谱：窄带+谐波族+奇次模式逐项钉死。"""
    f, amp = _tone_spectrum([10e6 * k for k in (1, 3, 5, 7, 9, 11)], f_max=121e6)
    obs = spectrum_observations(f, amp)
    assert obs["peaks_present"] is True
    assert obs["spectrum_peak_count"] == 6
    assert obs["narrowband_peaks_present"] is True
    assert obs["broadband_peaks_present"] is False
    assert obs["broadband_floor_rise"] is False
    assert obs["harmonic_series_present"] is True
    assert obs["harmonic_max_order"] == 11
    assert obs["odd_harmonics_only"] is True
    assert obs["even_harmonics_only"] is False
    assert obs["harmonic_parity_mixed"] is False
    # 管道：谱特征直接喂诊断面
    hits = emi_diagnose(obs)
    assert [h["entry_id"] for h in hits] == ["SIG-01", "SIG-05", "SIG-06"]


def test_spectrum_even_harmonics_symmetry_breaking() -> None:
    """偶次谱（基频+2/4/6 次）→ even_harmonics_only → SIG-04。"""
    f, amp = _tone_spectrum([10e6 * k for k in (1, 2, 4, 6)], f_max=71e6)
    obs = spectrum_observations(f, amp)
    assert obs["harmonic_series_present"] is True
    assert obs["even_harmonics_only"] is True
    assert obs["harmonic_max_order"] == 6
    # 管道：窄带+谐波族特征同样在场 → SIG-01 并击（特异度序），SIG-04/SIG-06 随后
    assert [h["entry_id"] for h in emi_diagnose(obs)] == ["SIG-01", "SIG-04", "SIG-06"]


def test_spectrum_mixed_parity_and_single_tone() -> None:
    """奇偶混合谱→mixed；单音+非整倍频伴峰→不成族（SIG-06 闭环）。"""
    f, amp = _tone_spectrum([10e6 * k for k in (1, 2, 3)], f_max=41e6)
    obs = spectrum_observations(f, amp)
    assert obs["harmonic_parity_mixed"] is True
    assert obs["harmonic_max_order"] == 3
    f2, amp2 = _tone_spectrum([10e6, 23e6], f_max=41e6)  # 23 非任何 k×10 落容差
    obs2 = spectrum_observations(f2, amp2)
    assert obs2["narrowband_peaks_present"] is True
    assert obs2["harmonic_series_present"] is False
    assert obs2["harmonic_max_order"] == 0
    assert [h["entry_id"] for h in emi_diagnose(obs2)] == ["SIG-06"]


def test_spectrum_broadband_hump_vs_floor_rise() -> None:
    """宽带包两态：窄包（W=40）→broad 无抬升（SIG-03）；宽包（W=70）→抬升（SIG-02+03）。"""
    f, amp = _hump_spectrum(width_bins=40)
    obs = spectrum_observations(f, amp)
    assert obs["peaks_present"] is True and obs["spectrum_peak_count"] == 1
    assert obs["broadband_peaks_present"] is True
    assert obs["narrowband_peaks_present"] is False
    assert obs["broadband_floor_rise"] is False  # 热点占比 29/201 < 0.2
    assert [h["entry_id"] for h in emi_diagnose(obs)] == ["SIG-03"]
    f2, amp2 = _hump_spectrum(width_bins=70)
    obs2 = spectrum_observations(f2, amp2)
    assert obs2["broadband_floor_rise"] is True  # 热点占比 49/201 ≥ 0.2
    assert obs2["broadband_peaks_present"] is True
    # 同特异度同域按 entry_id 字典序：SIG-02 先于 SIG-03
    assert [h["entry_id"] for h in emi_diagnose(obs2)] == ["SIG-02", "SIG-03"]


def test_spectrum_flat_floor_no_peaks_negative() -> None:
    """纯平底无峰谱：零命中（宽带抬升要求可分峰结构——如实不判不凑）。"""
    f = 1e5 * (1.0 + np.arange(301, dtype=float))
    amp = np.full(301, -50.0)
    obs = spectrum_observations(f, amp)
    assert obs["peaks_present"] is False
    assert obs["spectrum_peak_count"] == 0
    assert obs["broadband_floor_rise"] is False
    assert emi_diagnose(obs) == []


def test_spectrum_peaks_table_and_edge_clipping() -> None:
    """峰表字段+带缘削边 undetermined（如实不猜，不参与窄/宽带计数）。"""
    f, amp = _tone_spectrum([10e6, 30e6], f_max=41e6)
    peaks = spectrum_peaks(f, amp)
    assert [p["f_hz"] for p in peaks] == [10e6, 30e6]
    assert all(p["bandwidth_class"] == "narrow" for p in peaks)
    assert all(p["clipped"] is False for p in peaks)
    assert peaks[0]["prominence_db"] == pytest.approx(50.0)
    # 带缘削边：左缘 −6dB 台肩使 −6dB 走查触阵列端 → clipped+undetermined
    f2 = 1e5 * (1.0 + np.arange(201, dtype=float))
    amp2 = np.full(201, -50.0)
    amp2[0] = -6.0  # 峰左邻=峰顶−6dB：prominence 恰 6.0（≥门）且宽度走查触端
    amp2[1] = 0.0
    peaks2 = spectrum_peaks(f2, amp2)
    assert len(peaks2) == 1
    assert peaks2[0]["clipped"] is True
    assert peaks2[0]["bandwidth_class"] == "undetermined"
    obs2 = spectrum_observations(f2, amp2)
    assert obs2["narrowband_peaks_present"] is False
    assert obs2["broadband_peaks_present"] is False
    assert obs2["spectrum_peak_count"] == 1


def test_spectrum_observations_deterministic() -> None:
    """观测面确定性：同输入两次逐位一致（含峰表浮点）。"""
    f, amp = _tone_spectrum([10e6 * k for k in (1, 3, 5)], f_max=51e6)
    a = json.dumps([spectrum_observations(f, amp), spectrum_peaks(f, amp)],
                   ensure_ascii=False, sort_keys=True)
    b = json.dumps([spectrum_observations(f, amp), spectrum_peaks(f, amp)],
                   ensure_ascii=False, sort_keys=True)
    assert a == b


def test_spectrum_input_validation() -> None:
    """入参校验：长度不一致/非有限/点数不足/非法旋钮 → ValueError。"""
    f = 1e5 * (1.0 + np.arange(10, dtype=float))
    with pytest.raises(ValueError, match="长度必须一致"):
        spectrum_observations(f, np.full(9, -50.0))
    with pytest.raises(ValueError, match="正有限"):
        spectrum_observations(np.full(10, -1.0), np.full(10, -50.0))
    with pytest.raises(ValueError, match="全为有限数"):
        spectrum_observations(f, np.full(10, np.nan))
    with pytest.raises(ValueError, match="≥3"):
        spectrum_observations([1.0, 2.0], [0.0, 1.0])
    with pytest.raises(ValueError, match="peak_prominence_db"):
        spectrum_observations(f, np.full(10, -50.0), peak_prominence_db=0.0)
    with pytest.raises(ValueError, match="rbw_hz"):
        spectrum_observations(f, np.full(10, -50.0), rbw_hz=-1.0)
    with pytest.raises(ValueError, match="harmonic_order_max"):
        spectrum_observations(f, np.full(10, -50.0), harmonic_order_max=1)


# ---------------------------------------------------------------------------
# 观测面 B：margin_report 只读消费
# ---------------------------------------------------------------------------


def _report(measured: list[float]) -> dict[str, object]:
    """走真实 emi_filter.margin_report 面（Class B Avg 限值 dict 口径）。"""
    f_hz = np.array([0.2e6, 1e6, 2e6, 10e6, 20e6])
    return margin_report(f_hz, np.asarray(measured, dtype=float), fcc_limits_part15())


def test_margin_observations_widespread_vs_isolated() -> None:
    """违限广泛（5 点）vs 孤立（1 点）：特征互斥钉死+管道喂 SIG 面。"""
    obs = margin_observations(_report([60.0, 60.0, 60.0, 60.0, 60.0]))
    assert obs["limit_violations_present"] is True
    assert obs["violation_count"] == 5
    assert obs["violations_widespread"] is True
    assert obs["violations_isolated"] is False
    assert obs["min_margin_negative"] is True
    obs2 = margin_observations(_report([30.0, 30.0, 30.0, 30.0, 65.0]))
    assert obs2["violation_count"] == 1
    assert obs2["violations_isolated"] is True
    assert obs2["violations_widespread"] is False


def test_margin_observations_tight_and_out_of_band() -> None:
    """贴线余量（0≤margin<6）与带外点如实报告；全带外 min_margin=None 不误判。"""
    obs = margin_observations(_report([30.0, 30.0, 30.0, 45.0, 30.0]))
    assert obs["min_margin_tight"] is True
    assert obs["limit_violations_present"] is False
    assert obs["min_margin_negative"] is False
    f_hz = np.array([0.1e6, 1e6])  # 0.1 MHz 在限值表下界外
    rep = margin_report(f_hz, np.array([0.0, 0.0]), fcc_limits_part15())
    obs2 = margin_observations(rep)
    assert obs2["out_of_band_points_present"] is True
    rep_all_out = margin_report(np.array([1e4, 2e4]), np.array([0.0, 0.0]), fcc_limits_part15())
    obs3 = margin_observations(rep_all_out)
    assert obs3["min_margin_negative"] is False  # None 用 is-not-None 判（#364④）
    assert obs3["min_margin_tight"] is False


def test_margin_missing_key_rejected() -> None:
    """非 margin_report schema 的 dict → ValueError（负例契约）。"""
    with pytest.raises(ValueError, match="缺键"):
        margin_observations({"n_violations": 1})


def test_pipeline_spectrum_plus_margin_cross_face_diagnosis() -> None:
    """跨观测面管道：违限广泛+宽带底噪抬升 → SIG-07 特异度居首。"""
    f, amp = _hump_spectrum(width_bins=70)
    obs = {**spectrum_observations(f, amp), **margin_observations(
        _report([60.0, 60.0, 60.0, 60.0, 60.0]))}
    hits = emi_diagnose(obs)
    assert hits[0]["entry_id"] == "SIG-07"
    assert hits[0]["remedy_ref"] == "core.emi_filter.lc_filter_il"


def test_default_prominence_constant_pinned() -> None:
    """判据常量钉值（改缺省=显式改锚）。"""
    assert DEFAULT_PEAK_PROMINENCE_DB == 6.0
    assert BROADBAND_HOT_FRACTION == 0.2
