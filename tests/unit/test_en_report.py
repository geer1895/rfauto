"""DP-11 P2：En 相关性内核（criteria.md G5/G6/G7）。

- G5 合成回收逐位钉：GUM u_c 与闭式逐位；x_lab=x_ref±c·U → En≡∓c 逐位
  （3-4-5 精确构造：u_l=3,u_r=4 → √(9+16)=5 精确，二进制无舍入）；
- G6 深谷双分支钉：lab/ref 同时 <−40dB 自动切线性域，dB 域如实
  not_evaluable；
- G7 频轴对齐钉（#287/#294）：argmin 最近邻 + ulp 容差；异栅诚实拒配；
  乱序频率轴错位负例（searchsorted 实现会错位）。
"""

from __future__ import annotations

import math

import numpy as np
import pytest
import skrf

from rfauto.measurement.en_report import (
    DEFAULT_DEEP_VALLEY_DB,
    MIN_U_DB,
    align_frequency_axes,
    compute_en_report,
    compute_en_trace,
    en_core,
    gum_combined_uncertainty,
    load_budget,
    render_markdown,
    resolve_u_sim,
)


class TestGumBudget:
    """GUM u_c 与闭式逐位（G5①）。"""

    def test_combined_uncertainty_bitwise_closed_form(self):
        comps = [
            {"name": "a", "u": 0.5, "c": 1.0},
            {"name": "b", "u": 1.0, "c": 1.0},
            {"name": "c", "u": 1.5, "c": 2.0},
        ]
        out = gum_combined_uncertainty(comps, k=2.0)
        expected = math.sqrt(0.5**2 + 1.0**2 + (2.0 * 1.5) ** 2)
        assert out["u_c"] == expected          # 逐位（同一算式）
        assert out["U"] == 2.0 * expected      # k·u_c 逐位

    def test_temperature_drift_component_scaled_by_delta_t(self):
        comps = [{"name": "drift", "u": 0.02, "unit": "dB/°C",
                  "c": 1.0, "per_c": True}]
        out = gum_combined_uncertainty(comps, delta_t_c=5.0)
        assert out["contributions"][0]["effective_u"] == 0.1
        assert out["u_c"] == math.sqrt(0.1**2)

    def test_sensitivity_coefficient_applied(self):
        comps = [{"name": "x", "u": 2.0, "c": 0.5}]
        out = gum_combined_uncertainty(comps)
        assert out["u_c"] == math.sqrt((2.0 * 0.5) ** 2)

    def test_default_budget_template_loads(self):
        budget = load_budget()  # configs/uncertainty_budgets.yaml（仓根锚定）
        assert budget["name"] == "default_vna"
        assert budget["k"] == 2.0
        names = {c["name"] for c in budget["components"]}
        # 规格书 §3 分量清单：残余直接度/连接器重复性/温漂/IF 噪声/calkit
        assert {"residual_directivity", "connector_repeatability",
                "temperature_drift", "if_noise",
                "calkit_standard"} <= names
        # 连接器重复性 0.005 dB、温漂 0.02 dB/°C（规格书钉值）
        by_name = {c["name"]: c for c in budget["components"]}
        assert by_name["connector_repeatability"]["u"] == 0.005
        assert by_name["temperature_drift"]["u"] == 0.02
        assert by_name["temperature_drift"]["per_c"] is True


class TestEnBitwiseRecovery:
    """En 合成回收逐位钉（G5②）：3-4-5 精确构造，无舍入路径。"""

    def test_en_identity_positive_and_negative(self):
        x_ref = np.array([8.0, 4.0, -2.0])
        u_l = np.array([3.0, 0.75, 3.0])   # √(9+16)=5、√(0.75²+1²)=1.25 精确
        u_r = np.array([4.0, 1.0, 4.0])
        denom = np.sqrt(u_l**2 + u_r**2)
        assert np.all(denom == np.array([5.0, 1.25, 5.0]))
        s_lin = np.full(3, 0.5)            # 远高于深谷阈值 → dB 域
        for c in (4.0, 1.0, 0.25):
            en, dom, ev = en_core(x_ref + c * denom, x_ref, s_lin, s_lin,
                                  u_l, u_r)
            assert np.all(en == c), (c, en)
            assert np.all(dom == "db") and np.all(ev)
            en_neg, _, _ = en_core(x_ref - c * denom, x_ref, s_lin, s_lin,
                                   u_l, u_r)
            assert np.all(en_neg == -c)

    def test_u_floor_clamped(self):
        """U 低于 1e-3 dB 抬到下限（防除零）。"""
        x_ref = np.array([8.0])
        en, _, _ = en_core(np.array([8.0 + 2 * math.sqrt(2) * MIN_U_DB]),
                           x_ref, np.array([0.5]), np.array([0.0]),
                           np.array([MIN_U_DB]), np.array([MIN_U_DB]))
        # 两侧都钳到 1e-3 → denom=√2·1e-3（1e-3 二进制不可精确表示，
        # 用紧容差而非逐位）
        assert en[0] == pytest.approx(2.0, rel=1e-12)

    def test_clamp_changes_result_when_below_floor(self):
        # u=0 输入被钳到 MIN_U_DB，不会除零
        en, _, _ = en_core(np.array([10.0]), np.array([8.0]),
                           np.array([0.5]), np.array([0.5]),
                           np.array([0.0]), np.array([0.0]))
        assert en[0] == 2.0 / math.sqrt(2 * MIN_U_DB**2)


class TestDeepValleyBranch:
    """深谷双分支钉（G6，#370/#371）。"""

    def test_linear_domain_recovery(self):
        thr_lin = 10.0 ** (DEFAULT_DEEP_VALLEY_DB / 20.0)
        sr = np.full(1, 0.5 * thr_lin)      # 两侧同时入谷
        u = np.full(1, 0.25)
        k = math.log(10.0) / 20.0
        # 不动点迭代构造 sl 使线性域 En = 2（内核 U_lin 依赖 sl，闭合构造无解析）
        s = sr.copy()
        for _ in range(80):
            s = sr + 2.0 * np.sqrt((s * k * u) ** 2 + (sr * k * u) ** 2)
        en, dom, ev = en_core(20 * np.log10(s), 20 * np.log10(sr), s, sr,
                              u, u)
        assert dom[0] == "linear"
        assert not bool(ev[0])             # dB 域如实 not_evaluable
        assert abs(en[0] - 2.0) < 1e-9     # 线性域回收（紧容差）

    def test_mixed_domain_segmentation(self):
        """同迹线：谷内点线性域 + 谷外点 dB 域，evaluable 分界正确。"""
        thr_lin = 10.0 ** (-40.0 / 20.0)
        sr = np.array([0.5, 0.5 * thr_lin, 0.5])
        sl = np.array([0.55, 0.55 * thr_lin, 0.45])
        u = np.full(3, 0.25)
        en, dom, ev = en_core(20 * np.log10(sl), 20 * np.log10(sr), sl, sr,
                              u, u)
        assert list(dom) == ["db", "linear", "db"]
        assert list(ev) == [True, False, True]
        # dB 域两点手算对照（sqrt(2)·0.25 合成）
        denom = math.sqrt(2) * 0.25
        assert en[0] == pytest.approx((20 * math.log10(0.55)
                                       - 20 * math.log10(0.5)) / denom)
        assert en[2] == pytest.approx((20 * math.log10(0.45)
                                       - 20 * math.log10(0.5)) / denom)

    def test_one_side_outside_valley_stays_db(self):
        """仅一侧入谷（另一侧 ≥−40dB）：dB 差仍是物理量 → 不切线性域。"""
        sl = np.array([1e-3])       # −60 dB（入谷）
        sr = np.array([0.02])       # −34 dB（谷外 → dB 域仍物理）
        _en, dom, ev = en_core(20 * np.log10(sl), 20 * np.log10(sr), sl, sr,
                              np.array([0.25]), np.array([0.25]))
        assert dom[0] == "db" and bool(ev[0]) is True


class TestFrequencyAlignment:
    """频轴对齐钉（G7，#287/#294 禁 searchsorted）。"""

    def test_same_grid_with_ulp_noise_pairs(self):
        f = np.linspace(1e9, 3e9, 5)
        f_noisy = f + 2.4e-7   # #287 实测 ulp 级频移
        il, ir, nun = align_frequency_axes(f_noisy, f)
        assert nun == 0
        assert np.all(il == ir)

    def test_different_grid_rejects_honest(self):
        f = np.linspace(1e9, 3e9, 5)
        f_coarse = np.linspace(1e9, 3e9, 3)
        il, _ir, nun = align_frequency_axes(f, f_coarse)
        assert nun == 2                     # 半步距点诚实拒配
        assert len(il) == 3

    def test_unsorted_frequencies_pair_correctly(self):
        """乱序轴 argmin 最近邻逐频正确（searchsorted 实现会错位）。"""
        f_ref = np.array([1e9, 2e9, 3e9])
        f_lab = np.array([3e9, 1e9, 2e9])   # 乱序
        _il, ir, nun = align_frequency_axes(f_lab, f_ref)
        assert nun == 0
        assert np.all(f_ref[ir] == f_lab)   # 每点找到的就是自身

    def test_empty_axes(self):
        il, _ir, nun = align_frequency_axes(np.empty(0), np.array([1e9]))
        assert il.size == 0 and nun == 0


class TestEndToEnd:
    """网络输入面 + 报告输出。"""

    @staticmethod
    def _net(s11_vals, n=5):
        freq = skrf.Frequency(1.0, 3.0, n, "ghz")
        s = np.zeros((n, 2, 2), dtype=complex)
        s[:, 0, 0] = s11_vals
        s[:, 1, 0] = 0.9
        s[:, 0, 1] = 0.9
        s[:, 1, 1] = 0.1
        return skrf.Network(frequency=freq, s=s)

    def test_identical_networks_pass(self):
        net = self._net(np.full(5, 0.2))
        report = compute_en_report(net, net, 0.02, 0.02)
        assert report["ok"] is True
        assert report["summary"]["traces_passed"] == 2
        assert "markdown" in report

    def test_out_of_spec_segments_merged(self):
        ref = self._net(np.full(7, 0.2), n=7)
        lab_freq = skrf.Frequency(1.0, 3.0, 7, "ghz")
        lab = skrf.Network(frequency=lab_freq, s=ref.s.copy())
        lab.s[2:5, 0, 0] = 0.4   # 连续 3 点 +6 dB 超差段
        result = compute_en_trace(
            lab.f, lab.s[:, 0, 0], ref.f, ref.s[:, 0, 0], 0.02, 0.02,
            trace="S11")
        assert result.ok is False
        assert len(result.segments) == 1
        seg = result.segments[0]
        assert seg["n_points"] == 3
        assert seg["max_abs_en"] > 1.0
        assert pytest.approx(seg["start_ghz"], abs=1e-6) == float(lab.f[2]) / 1e9

    def test_deep_valley_report_marks_not_evaluable(self):
        ref = self._net(np.full(5, 0.2))
        ref.s[2, 0, 0] = 1e-3
        lab = ref.copy()
        lab.s[2, 0, 0] = 1.1e-3
        report = compute_en_report(lab, ref, 0.02, 0.02)
        t = report["traces"]["S11"]
        assert t["domain"][2] == "linear"
        assert t["n_evaluable"] == 4
        assert t["n_linear_domain"] == 1
        # 谷内 dB 域不评估 → 门只看其余点，但 |Δ|~10% 幅度差在线性域超差
        assert report["ok"] is False

    def test_type_guard(self):
        with pytest.raises(TypeError, match=r"skrf\.Network"):
            compute_en_report("x", "y", 0.02, 0.02)

    def test_resolve_u_sim_priority_and_fallback(self):
        assert resolve_u_sim(anchor_uncertainty_db=0.1) == (0.1, "anchor")
        assert resolve_u_sim(hfss_residual_db=0.2) == (0.2, "hfss_arbitration")
        u, src = resolve_u_sim()
        assert src == "fallback"
        assert u == 0.5

    def test_markdown_renders_segments(self):
        ref = self._net(np.full(5, 0.2))
        lab = ref.copy()
        lab.s[3:, 0, 0] = 0.5
        report = compute_en_report(lab, ref, 0.02, 0.02)
        md = render_markdown(report)
        assert "En 相关性报告" in md
        assert "超差频段" in md
