"""WP3.9 MVP followUps 单测（followUps 内核——零真机）。

覆盖面：
1. ③ 深零点判据内核：带宽积分（band_power_avg_db）与深零点邻域
   （deep_null_neighborhood_db）对零点频率网格漂移的鲁棒性
   （合成 Lorentzian 零点，平移零点前后单频谷深 vs 带指标对照）；
2. ④ 谷位标定内核：locate_dip_ghz 抛物线细分（合成扫频）、端点/
   单调剖面 refined=False 退化、dip_constant/recenter_length_for_target
   常数定标（99.8/76.8 引擎漂移参考口径）；
3. ①档合并契约：merge_factory_with_replay（HFSS 回代指标进 best、
   工厂 openEMS 指标留 factory_extra、回代评估独立记账）+ 与
   judge_problem_pair 端到端（合成 pass/fail 两例）；
4. 运行器离线件：_s_db_at 插值取模、count_eval_rows 保守 CSV 计数、
   ratrace_null 档的 analyze_null_file（tmp 合成 .s4p，skrf）与
   run_ratrace_null_tier 端到端、optislang_probe 返回契约；
5. judge 汇总档 run_judge_tier 对 tmp outdir 的聚合契约。

真机路径（probe/factory/replay/native/patch_calib）不在单测范围——
单测零真机零 runs/ 依赖（真机证据走 runs/ 下战役归档 JSON）。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
for p in (str(REPO / "scripts"), str(REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import wp39_followup_run as runner
from rfauto.service.wp39_benchmark import (
    band_power_avg_db,
    deep_null_neighborhood_db,
    dip_constant,
    judge_problem_pair,
    locate_dip_ghz,
    merge_factory_with_replay,
    recenter_length_for_target,
)

# ── 合成扫频工具 ─────────────────────────────────────────────────────────────


def _null_sweep(f_null_ghz: float, depth_db: float = -50.0,
                floor_db: float = -12.0, q_inv_ghz: float = 0.004,
                f_lo: float = 2.3, f_hi: float = 2.7,
                n: int = 401) -> tuple[np.ndarray, np.ndarray]:
    """Lorentzian 型深零点扫频：功率域 P(f) = P_floor − (P_floor−P_null)
    /(1+((f−f0)/w)²)——谷位 f_null 处 P=P_null（深谷），远离谷位回到
    平底 P_floor（③ 网格漂移敏感性合成基准，谷位可任意平移）。"""
    f = np.linspace(f_lo, f_hi, n)
    p_floor = 10.0 ** (floor_db / 10.0)
    p_null = 10.0 ** (depth_db / 10.0)
    power = p_floor - (p_floor - p_null) / (
        1.0 + ((f - f_null_ghz) / q_inv_ghz) ** 2)
    return f, 10.0 * np.log10(power)


# ── ③ 深零点判据 ─────────────────────────────────────────────────────────────


class TestBandPowerAvgDb:
    def test_constant_curve_is_exact(self):
        f = np.linspace(2.4, 2.6, 21)
        v = np.full_like(f, -20.0)
        assert band_power_avg_db(f, v, 2.4, 2.6) == pytest.approx(-20.0)

    def test_power_domain_not_db_domain(self):
        # −10dB 与 −30dB 等样本：功率平均 = 10log10((0.1+0.001)/2)
        f = np.array([2.4, 2.5])
        v = np.array([-10.0, -30.0])
        expect = 10 * math.log10((10 ** -1.0 + 10 ** -3.0) / 2)
        assert band_power_avg_db(f, v, 2.4, 2.5) == pytest.approx(expect)

    def test_empty_band_raises(self):
        f = np.linspace(2.0, 2.1, 11)
        with pytest.raises(ValueError, match="无频率样本"):
            band_power_avg_db(f, np.full_like(f, -20.0), 3.0, 4.0)

    def test_deep_null_contributes_little(self):
        # 单个 −60dB 窄零点 vs 全带 −20dB 平底：带积分只被零点轻微拉低
        f = np.linspace(2.4, 2.6, 401)
        flat = np.full_like(f, -20.0)
        with_null = flat.copy()
        with_null[200] = -60.0
        base = band_power_avg_db(f, flat, 2.4, 2.6)
        v = band_power_avg_db(f, with_null, 2.4, 2.6)
        assert v < base  # 方向正确
        assert base - v < 0.5  # 但影响 < 0.5dB（功率域份额小）


class TestDeepNullRobustness:
    def test_single_freq_sensitive_band_metric_robust(self):
        """③ 立项动机的合成对照：零点平移半个细网格步时——
        单频谷深判读大幅摆动；深零点邻域/带宽积分几乎不动。"""
        f0_true = 2.465
        step = 0.001  # 401 点 2.3–2.7 的栅格步
        f_a, v_a = _null_sweep(f0_true)
        f_b, v_b = _null_sweep(f0_true + 2 * step)  # 零点挪两个栅格
        # 单频判读（在固定 f0 取值）：两网格谷位不同 → 判读差大
        fixed = float(v_a[np.argmin(np.abs(f_a - f0_true))])
        fixed_b = float(v_b[np.argmin(np.abs(f_b - f0_true))])
        assert abs(fixed - fixed_b) > 6.0  # 单频敏感（dB 级摆动）
        # 邻域/带宽积分判读：几乎不变
        nb_a = deep_null_neighborhood_db(f_a, v_a, 2.3, 2.7, 0.025)
        nb_b = deep_null_neighborhood_db(f_b, v_b, 2.3, 2.7, 0.025)
        assert abs(nb_a - nb_b) < 0.5
        bd_a = band_power_avg_db(f_a, v_a, f0_true - 0.025, f0_true + 0.025)
        bd_b = band_power_avg_db(f_b, v_b, f0_true - 0.025, f0_true + 0.025)
        assert abs(bd_a - bd_b) < 0.5

    def test_neighborhood_between_null_and_floor(self):
        f, v = _null_sweep(2.5, depth_db=-50.0, floor_db=-12.0)
        nb = deep_null_neighborhood_db(f, v, 2.3, 2.7, 0.01)
        assert -50.0 < nb < -12.0  # 判读落在谷深与平底之间
        wide = deep_null_neighborhood_db(f, v, 2.3, 2.7, 0.05)
        assert wide > nb  # 窗越宽越接近平底（能量份额）

    def test_no_sample_in_search_band_raises(self):
        f = np.linspace(2.0, 2.1, 11)
        with pytest.raises(ValueError, match="搜索带"):
            deep_null_neighborhood_db(f, np.full_like(f, -20.0),
                                      3.0, 4.0, 0.01)


# ── ④ 谷位标定 ───────────────────────────────────────────────────────────────


class TestLocateDip:
    def test_parabolic_refinement_recovers_true_dip(self):
        f_true = 2.465
        f, v = _null_sweep(f_true, n=801)
        f_dip, meta = locate_dip_ghz(f, v)
        assert meta["refined"] is True
        assert f_dip == pytest.approx(f_true, abs=2e-4)
        assert meta["dip_db"] == pytest.approx(min(v), abs=0.5)

    def test_edge_minimum_not_refined(self):
        # 单调下降剖面：argmin 在末端，无内点抛物线 → refined=False
        f = np.linspace(2.3, 2.7, 41)
        v = -f * 10.0
        f_dip, meta = locate_dip_ghz(f, v)
        assert meta["refined"] is False
        assert f_dip == pytest.approx(float(f[-1]))

    def test_too_few_points_raises(self):
        with pytest.raises(ValueError, match="3 个"):
            locate_dip_ghz([2.0, 2.1], [-10.0, -11.0])


class TestDipCalibration:
    def test_constant_arithmetic(self):
        # wp39 归档口径：probe.s1p f_dip=2.495GHz @ L=40 → 99.8
        assert dip_constant(2.495, 40.0) == pytest.approx(99.8)
        assert dip_constant(1.92, 40.0) == pytest.approx(76.8)

    def test_recenter_length_for_target(self):
        # HFSS 常数 99.8 定标 2.45GHz → L*=40.7347mm（openEMS 76.8 → 31.35mm）
        assert recenter_length_for_target(2.45, 99.8) == \
            pytest.approx(40.7347, abs=1e-3)
        assert recenter_length_for_target(2.45, 76.8) == \
            pytest.approx(31.3469, abs=1e-3)

    def test_engine_drift_changes_design_point(self):
        # ④ 立项口径：两引擎常数漂移 1.30× → 同目标设计点差 9.4mm——
        # 直接沿用他引擎常数会让优化目标落空（wp39 首轮 patch 根因）
        l_hfss = recenter_length_for_target(2.45, 99.8)
        l_oems = recenter_length_for_target(2.45, 76.8)
        assert l_hfss - l_oems == pytest.approx(9.3878, abs=1e-2)

    def test_nonpositive_target_raises(self):
        with pytest.raises(ValueError, match="正"):
            recenter_length_for_target(0.0, 99.8)


# ── ①档合并契约 ──────────────────────────────────────────────────────────────


def _factory_kernel_json(metric_openems: float = -30.0,
                         w: float = 1.05,
                         n_evals: int = 11,
                         opt_s: float = 640.0) -> dict:
    return {
        "problem": "mline",
        "best": {"params": {"w_mm": w},
                 "metrics": {"s11_f0_db": metric_openems},
                 "cost": metric_openems + 1e6},
        "n_attempts": n_evals,
        "wall_s": {"optimization_s": opt_s},
    }


class TestMergeFactoryWithReplay:
    def test_replay_metric_wins_and_factory_bookkept(self):
        factory = _factory_kernel_json(metric_openems=-30.0)
        replay = {"params": {"w_mm": 1.05},
                  "metrics": {"s11_f0_db": -39.0}, "n_evals": 1,
                  "wall_s": {"eval_s": 40.0}}
        cand = merge_factory_with_replay(factory, replay,
                                         metric_name="s11_f0_db")
        assert cand["best"]["metric"] == pytest.approx(-39.0)  # HFSS 回代
        assert cand["best"]["metric"] != pytest.approx(-30.0)  # 非 openEMS
        assert cand["n_evals"] == 11                      # 工厂预算口径
        assert cand["wall_s"]["optimization_s"] == pytest.approx(640.0)
        assert cand["factory_extra"]["cost_source"] == "hfss_replay"
        assert cand["factory_extra"]["factory_metric"] == \
            pytest.approx(-30.0)
        assert cand["factory_extra"]["replay_n_evals"] == 1

    def test_end_to_end_judge_pass_case(self):
        factory = _factory_kernel_json(opt_s=120.0)
        replay = {"params": {"w_mm": 1.05},
                  "metrics": {"s11_f0_db": -37.5}, "n_evals": 1}
        cand = merge_factory_with_replay(factory, replay,
                                         metric_name="s11_f0_db")
        baseline = {"problem": "mline",
                    "best": {"params": {"w_mm": 1.113},
                             "metric": -38.05, "cost": 0.0},
                    "n_evals": 9,
                    "wall_s": {"optimization_s": 296.88}}
        v = judge_problem_pair(baseline, cand)
        # wall 120/296.88=0.404 ≤0.5；劣化 (−37.5+38.05)/38.05=+1.45% ≤5%
        assert v["verdict"] == "PASS"
        assert v["wallclock_ratio"] == pytest.approx(0.4043, abs=1e-3)
        assert v["degradation_pct"] == pytest.approx(1.4455, abs=1e-3)

    def test_end_to_end_judge_wall_fail_case(self):
        factory = _factory_kernel_json(opt_s=640.0)
        replay = {"params": {"w_mm": 1.05},
                  "metrics": {"s11_f0_db": -39.0}, "n_evals": 1}
        cand = merge_factory_with_replay(factory, replay,
                                         metric_name="s11_f0_db")
        baseline = {"problem": "mline",
                    "best": {"params": {"w_mm": 1.113},
                             "metric": -38.05, "cost": 0.0},
                    "n_evals": 9,
                    "wall_s": {"optimization_s": 296.88}}
        v = judge_problem_pair(baseline, cand)
        assert v["verdict"] == "FAIL"
        assert not v["wallclock_ok"]
        assert v["cost_ok"]  # cost 过门但 wall 超门——分项如实

    def test_missing_factory_best_raises(self):
        with pytest.raises(ValueError, match="best"):
            merge_factory_with_replay(
                {"problem": "mline", "best": None},
                {"metrics": {"s11_f0_db": -39.0}}, metric_name="s11_f0_db")

    def test_missing_replay_metric_raises(self):
        with pytest.raises(ValueError, match="回代指标"):
            merge_factory_with_replay(
                _factory_kernel_json(), {"metrics": {}},
                metric_name="s11_f0_db")

    def test_accepts_elapsed_s_fallback(self):
        factory = _factory_kernel_json()
        del factory["wall_s"]
        factory["elapsed_s"] = 512.5
        cand = merge_factory_with_replay(
            factory, {"metrics": {"s11_f0_db": -39.0}},
            metric_name="s11_f0_db")
        assert cand["wall_s"]["optimization_s"] == pytest.approx(512.5)


# ── 运行器离线件 ─────────────────────────────────────────────────────────────


class TestRunnerOfflinePieces:
    def test_s_db_at_interp(self):
        # 同相两点插值：|s|=0.5 恒定 → 任意 f0 处 −6.02dB（插值不改变模）
        f = np.array([2.0, 3.0])
        s = np.array([0.5 + 0j, 0.5 + 0j])
        assert runner._s_db_at(f, s, 2.5) == \
            pytest.approx(20 * math.log10(0.5), abs=1e-9)
        # 实部/虚部各自线性（2.5GHz 处 = 0.25+0.5j）
        s2 = np.array([0.5 + 0j, 0.0 + 1.0j])
        assert runner._s_db_at(f, s2, 2.5) == \
            pytest.approx(20 * math.log10(math.hypot(0.25, 0.5)), abs=1e-9)

    def test_count_eval_rows_contract(self):
        assert runner.count_eval_rows("a,b\n1,2\n3,4\n") == 2
        assert runner.count_eval_rows("a,b\n1,2\n3\n") is None  # 行宽不一致
        assert runner.count_eval_rows("a\n1\n") is None  # 字段 <2
        assert runner.count_eval_rows("only header\n") is None
        assert runner.count_eval_rows("") is None

    def test_optislang_probe_contract(self):
        payload = runner.probe_optislang(scan_roots=["Z:\\definitely_absent"])
        assert payload["schema"] == "wp39_followup_optislang_probe_v1"
        assert isinstance(payload["available"], bool)
        assert set(payload["checks"]) >= {"python_bridge", "path_exe",
                                          "install_dirs"}
        # 扫描根不存在 → 安装目录检查 False（探测面非崩溃）
        assert payload["checks"]["install_dirs"]["available"] is False

    def test_parse_optimetrics_profile(self, tmp_path):
        # 真机 profile 行格式（opti0_0.profile 实录摘录，timestamp 为
        # AEDT 内部时基，W 为内部 SI 值米）
        p = tmp_path / "opti0_0.profile"
        p.write_text(
            "$begin 'Profile Header'\n"
            "\tvi('W', '1.113mm', '0.5mm', '2mm')\n"
            "\tp(1.789282933188000e+12, 1.789282983021000e+12, '', "
            "'Local Machine', 1.113000000000000e-03)\n"
            "\tp(1.789282983024000e+12, 1.789283011215000e+12, '', "
            "'Local Machine', 1.168650000000000e-03)\n"
            "$end 'Profile'\n", encoding="utf-8")
        parsed = runner.parse_optimetrics_profile(p)
        assert parsed["n_evals"] == 2
        assert parsed["w_trajectory_mm"] == pytest.approx([1.113, 1.16865])
        assert len(parsed["per_eval_dt_raw"]) == 2
        assert parsed["profile"].endswith("opti0_0.profile")

    def test_parse_optimetrics_profile_empty(self, tmp_path):
        p = tmp_path / "opti0_0.profile"
        p.write_text("$begin 'Profile Header'\n\t'Solve#'=0\n",
                     encoding="utf-8")
        parsed = runner.parse_optimetrics_profile(p)
        assert parsed["n_evals"] is None


class TestRatraceNullTier:
    def _synth_s4p(self, path: Path, f_null: float, seed: int = 0) -> None:
        """合成 4 端口 .s4p：S31 深零点 @f_null，其余通道浅响应。

        n=801（0.5MHz 步）保证窄零点（半宽 4MHz）被采样栅格解析。"""
        skrf = pytest.importorskip("skrf")
        f, s31_db = _null_sweep(f_null, n=801)
        s31 = 10 ** (s31_db / 20.0)
        rng = np.random.default_rng(seed)
        s = (0.05 * (rng.random((len(f), 4, 4)) - 0.5)
             + 0.05j * (rng.random((len(f), 4, 4)) - 0.5))
        s[:, 2, 0] = s31
        net = skrf.Network(frequency=skrf.Frequency.from_f(f, "ghz"),
                           s=s)
        net.write_touchstone(str(path))

    def test_analyze_null_file_metrics(self, tmp_path):
        pytest.importorskip("skrf")
        p = tmp_path / "syn.s4p"
        self._synth_s4p(p, f_null=2.465)
        entry = runner.analyze_null_file(
            p, [2.45, 2.465, 2.5], (2.3, 2.7), [0.01, 0.025, 0.05])
        assert entry["null"]["f_null_ghz"] == pytest.approx(2.465, abs=2e-3)
        assert entry["null"]["dip_db"] < -45
        # 邻域积分读数落在谷深与平底之间（判读平缓化）
        assert -45.0 < entry["deep_null_neighborhood_db"]["hw10MHz"] < -12.0

    def test_tier_end_to_end_fixed_f0_sensitivity(self, tmp_path,
                                                  monkeypatch):
        pytest.importorskip("skrf")
        hf = tmp_path / "hfss.s4p"
        oe = tmp_path / "openems.s4p"
        self._synth_s4p(hf, f_null=2.465, seed=1)
        self._synth_s4p(oe, f_null=2.470, seed=2)  # 零点漂 5MHz（跨引擎口径）
        monkeypatch.setattr(
            runner, "RATRACE_NULL_SEARCH", (2.3, 2.7))
        out = runner.run_ratrace_null_tier(tmp_path, {
            "hfss": (str(hf), 2.465), "openems": (str(oe), 2.5)},
            f0_anchor=2.465)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["schema"] == "wp39_followup_ratrace_null_v1"
        assert set(data["entries"]) == {"hfss", "openems"}
        cross = data["cross_engine"]
        assert cross["null_freq_delta_mhz"] == pytest.approx(5.0, abs=0.6)
        # ③ 判据语义：锚点固定频点单频读数差（零点漂 5MHz 直接进读数）
        # 远大于邻域积分读数差（漂移不改变邻域能量）
        assert cross["fixed_f0_delta_db"] > 20.0
        assert cross["neighborhood_hw25MHz_delta_db"] < 2.0
        assert cross["robustness_ratio"] > 10.0

    def test_judge_tier_aggregates(self, tmp_path):
        (tmp_path / "replay.json").write_text(json.dumps({
            "schema": "wp39_followup_replay_v1",
            "verdict": {"verdict": "FAIL", "reasons": ["x"]}}),
            encoding="utf-8")
        (tmp_path / "native.json").write_text(json.dumps({
            "schema": "wp39_followup_native_v1",
            "eval_count": {"n_evals": 17, "source": "export_csv_rows"},
            "best_var": {"w_mm": 1.087}}), encoding="utf-8")
        out = runner.run_judge_tier(tmp_path)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["schema"] == "wp39_followup_summary_v1"
        assert data["factory_tier_verdict"] == "FAIL"
        assert data["tiers"]["replay"]["available"] is True
        assert data["tiers"]["native"]["n_evals_extracted"] == 17
        assert data["tiers"]["probe"]["available"] is False  # 缺档如实


# ── 换判据档离线件（wp39-factory-verdict-next）─────────────────────────────────


class TestVerdictNextOfflinePieces:
    def test_guard_refuses_archive_dirs(self):
        with pytest.raises(RuntimeError, match="禁止写入既有归档"):
            runner._guard_next_outdir(runner.DEFAULT_OUTDIR)
        with pytest.raises(RuntimeError, match="禁止写入既有归档"):
            runner._guard_next_outdir(runner.BASELINE_DIR)
        runner._guard_next_outdir(runner.NEXT_OUTDIR)  # 新目录放行

    def test_hj_closed_form_matches_anchor(self):
        # 副锚源：HJ 闭式 w=1.113 rogers4350b → 2.85264（anchor_verdict 文档值）
        z0, eps = runner.hj_closed_form(1.113)
        assert eps == pytest.approx(2.85264, abs=2e-5)
        assert z0 == pytest.approx(50.0, abs=0.1)

    def test_read_port_beta_csv(self, tmp_path):
        p = tmp_path / "port_beta.csv"
        p.write_text("freq_hz,beta_rad_per_m\n2.4e9,84.88\n2.5e9,88.4\n",
                     encoding="utf-8")
        bf, bb = runner.read_port_beta_csv(p)
        assert bf.tolist() == pytest.approx([2.4e9, 2.5e9])
        assert bb.tolist() == pytest.approx([84.88, 88.4])
        (tmp_path / "empty.csv").write_text("freq_hz,beta_rad_per_m\n",
                                            encoding="utf-8")
        with pytest.raises(ValueError, match="空"):
            runner.read_port_beta_csv(tmp_path / "empty.csv")

    def test_native_campaign_view_contract(self):
        native = {"best_var": {"raw": "1.16865mm", "w_mm": 1.16865},
                  "replay": {"metrics": {"s11_f0_db": -49.44}},
                  "eval_count": {"n_evals": 9, "source": "opti_profile"},
                  "wall_s": {"optimization_s": 283.45},
                  "props_readback": {"optimizer": "Pattern Search"}}
        view = runner.native_campaign_view(native)
        assert view["best"]["metric"] == pytest.approx(-49.44)
        assert view["best"]["params"]["w_mm"] == pytest.approx(1.16865)
        assert view["n_evals"] == 9 and view["n_evals_source"] == "opti_profile"
        assert view["wall_s"]["optimization_s"] == pytest.approx(283.45)
        # 归档口径复现：对 scripted 基线 296.88s/−38.05dB 判定 → wall 0.955>0.5 FAIL
        base = {"problem": "mline",
                "best": {"params": {"w_mm": 1.113}, "metric": -38.05},
                "n_evals": 9, "wall_s": {"optimization_s": 296.88}}
        v = judge_problem_pair(base, view)
        assert v["verdict"] == "FAIL" and not v["wallclock_ok"]
        assert v["cost_ok"]  # −49.44 优于 −38.05（劣化为负）
        assert v["wallclock_ratio"] == pytest.approx(283.45 / 296.88, abs=1e-3)
        # 提取不到 → best None（judge 记"最优指标缺失"，不猜）
        assert runner.native_campaign_view({})["best"] is None

    def test_summary_next_tier_aggregates(self, tmp_path):
        out = tmp_path / "next"
        out.mkdir()
        followup = tmp_path / "followup"
        followup.mkdir()
        baseline = tmp_path / "baseline"
        baseline.mkdir()
        (out / "replay_eps.json").write_text(json.dumps({
            "schema": "wp39_followup_replay_eps_v1",
            "verdict": {"problem": "mline_eps", "verdict": "FAIL",
                        "reasons": ["wall-clock 超门"]},
            "replay": {"metrics": {"eps_eff_abs_err": 0.01}}}),
            encoding="utf-8")
        for eng, metric, n, wall in (("pattern_search", -40.0, 14, 600.0),
                                     ("sbo", -39.5, 11, 780.0)):
            (out / f"ratrace_null__{eng}.json").write_text(json.dumps({
                "problem": "ratrace_null",
                "best": {"params": {"r_mm": 17.0}, "metric": metric},
                "n_evals": n, "wall_s": {"optimization_s": wall},
                "stop_reason": "min_step", "hfss": {"setup": {"type": "x"}}}),
                encoding="utf-8")
        (followup / "native.json").write_text(json.dumps({
            "best_var": {"w_mm": 1.16865},
            "replay": {"metrics": {"s11_f0_db": -49.44}},
            "eval_count": {"n_evals": 9, "source": "opti_profile"},
            "wall_s": {"optimization_s": 283.45}}), encoding="utf-8")
        (followup / "optislang_probe.json").write_text(json.dumps({
            "available": False}), encoding="utf-8")
        (baseline / "mline__pattern_search.json").write_text(json.dumps({
            "problem": "mline",
            "best": {"params": {"w_mm": 1.113}, "metric": -38.05},
            "n_evals": 9, "wall_s": {"optimization_s": 296.88}}),
            encoding="utf-8")
        path = runner.run_summary_next_tier(out, followup_dir=followup,
                                            baseline_dir=baseline)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema"] == "wp39_followup_verdict_next_summary_v1"
        assert set(data["problems"]) == {"mline_eps_factory", "ratrace_null"}
        assert data["problems"]["mline_eps_factory"]["verdict"] == "FAIL"
        # ratrace_null：wall 780/600=1.3>0.5 FAIL，cost 劣化 +1.25% 过门
        rn = data["problems"]["ratrace_null"]
        assert rn["verdict"] == "FAIL" and rn["cost_ok"] and not rn["wallclock_ok"]
        assert rn["wallclock_ratio"] == pytest.approx(1.3, abs=1e-3)
        assert data["summary"]["overall"] == "FAIL"
        assert data["summary"]["n_problems"] == 2  # 决策输入不进 overall
        di = data["decision_inputs"]
        assert di["native_vs_scripted_mline"]["verdict"]["verdict"] == "FAIL"
        assert di["optislang_mop"]["status"] == "NOT_RUN"
        assert di["optislang_mop"]["available"] is False
        assert data["probe_eps"] is None and data["factory_eps"] is None

    def test_summary_next_refuses_archive_dir(self):
        with pytest.raises(RuntimeError, match="禁止写入既有归档"):
            runner.run_summary_next_tier(runner.DEFAULT_OUTDIR)
