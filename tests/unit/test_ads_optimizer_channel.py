"""ads 优化通道钉（aurora_p B3 席）——注册/映射/#154 语义/离线 e2e/确定性。

钉面：
- 注册面：channel_names 含 "ads"（linkage.ads_optimizer_channel 导入即
  注册，linkage→optimization 合法向下 import）；create_via_channel("ads")
  出 AdsOptAdapter（version="ads"）；负例（缺 family/snp_path/未知
  adapter_kwargs/族不存在/文件不存在）→ (None, "") 不静默；
- #154 参数映射：显式映射表 ADS_CIRCUIT_PARAM_MAP 逐键语义——
  映射键 ⊆ 渲染器签名键（sweep 展开叶 ⊆ resolve_sweep 已知键）；
  ADS_OPT_METRIC_NAMES ↔ service.METRIC_NAMES 两 MVP 族双向一致性钉
  （#231 注册表消费者家法）；ghz_to_hz/identity/to_int 三变换行为；
  bool 拒；映射有效性端到端钉（变量表达式 → 网表 F=/Z= 数字）；
- 适配器协议：solve→SolveReport/get_sparams→skrf.Network/last_metrics
  单源键集/unconsumed_variables 透明面/runner 异常→失败报告不炸；
- 离线 e2e（零真机）：fake runner 注入（合成响应模型=2 参数谷形）→
  run_optimization(adapter_name="ads") 迷你优化 ≤10 步 cost 改善
  （判据写死数值）；同 seed 两跑轨迹逐位同（#158 确定性）；
- #144 runs/ 湖零污染：全模块 chdir 沙箱（cwd=tmp_path，run 目录/optuna
  db/评估产物全落 tmp）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

import rfauto.linkage.ads_optimizer_channel  # noqa: F401  # 导入即注册 ads 通道
from rfauto.linkage import ads_optimizer_channel as aoc
from rfauto.optimization.adapter_channels import (
    channel_names,
    create_via_channel,
)
from rfauto.optimization.optimizer import run_optimization

# 导入即注册的模块级消费（import 时机与真实用户一致，注册幂等）
aoc.register_ads_channel()

_SKRF = pytest.importorskip("skrf")


# --------------------------------------------------------------------------- #
# 沙箱与合成数据（#144：优化循环类单测禁污染真实 runs/）
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _sandbox(tmp_path, monkeypatch):
    """chdir 沙箱 + 临时 optuna storage（#144：本文件全部测试 autouse——
    优化环 run 目录/评估产物全落 tmp，真实 runs/ 湖零污染）。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    db_dir = tmp_path / "runs" / ".optuna"
    db_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "rfauto.optimization.optimizer.get_storage_path",
        lambda: f"sqlite:///{(db_dir / 'optuna.db').as_posix()}",
    )
    yield


def _write_device_snp(path: Path, *, n_ports: int = 4) -> Path:
    """合成无源器件 Touchstone（4 端口=branchline_cascade 渲染器契约）。"""
    freq = _SKRF.Frequency(2.0, 2.8, 41, unit="ghz")
    s = np.zeros((len(freq.f), n_ports, n_ports), dtype=complex)
    for i in range(n_ports):
        s[:, i, i] = 0.08 * (1 + 0.1j)          # 小反射
    s[:, 1, 0] = s[:, 0, 1] = 0.7 * (1 - 0.05j)  # 直通
    net = _SKRF.Network(frequency=freq, s=s, z0=[50.0] * n_ports, name="device")
    net.write_touchstone(str(path))
    return path


def _branchline_fake_runner_factory(capture: list[str] | None = None):
    """合成响应 runner（离线验收通道，#139 家法）。

    从渲染网表文本读回映射结果（F=/E=/Z= 与频扫 Start/Stop/Lin）→
    2 参数谷形响应（f0_map→2.4 GHz、z0_map→50 Ω 处 S11 谷最深）→
    branchline 合成 2 端口 payload（P1/P2 形态，composite_network_from_
    payload 同消费口径）。capture 非空时逐评估追加网表原文（映射钉）。
    """
    def runner(netlist_path: Path) -> dict[str, Any]:
        text = Path(netlist_path).read_text(encoding="ascii")
        if capture is not None:
            capture.append(text)
        f0_map = float(re.search(r"TLIN:TLIN1\s+\S+\s+\S+\s+Z=\S+\s+Ohm\s+E=\S+\s+F=([\d.eE+-]+)", text).group(1))
        z0_map = float(re.search(r"Port:P1\s+\S+\s+0\s+Num=1\s+Z=([\d.eE+-]+)", text).group(1))
        sw = re.search(r"SweepPlan:\s*\S+\s+Start=([\d.eE+-]+)\s+\S+\s+Stop=([\d.eE+-]+)\s+\S+\s+Lin=(\d+)", text)
        f_lo, f_hi, n_pts = float(sw.group(1)), float(sw.group(2)), int(sw.group(3))
        f_ghz = np.linspace(f_lo, f_hi, n_pts)
        f_hz = f_ghz * 1e9
        floor = (-1.0 - 12.0 * np.exp(-(((f0_map - 2.4) / 0.25) ** 2))
                 - 10.0 * np.exp(-(((z0_map - 50.0) / 15.0) ** 2)))
        depth = 40.0 * np.exp(-(((f0_map - 2.4) / 0.18) ** 2)
                              - (((z0_map - 50.0) / 18.0) ** 2))
        s11_db = floor - depth * np.exp(-(((f_ghz - 2.4) / 0.06) ** 2))
        s11 = 10 ** (s11_db / 20.0)
        s21 = 0.93 * np.ones_like(f_ghz)
        s = {
            "1_1": [[float(v.real), float(v.imag)] for v in s11],
            "2_1": [[float(v), 0.0] for v in s21],
            "1_2": [[float(v), 0.0] for v in s21],
            "2_2": [[0.1, 0.02] for _ in f_ghz],
        }
        return {
            "frequency_hz": [float(x) for x in f_hz],
            "port_names": ["P1", "P2"],
            "port_z": [[50.0, 0.0], [50.0, 0.0]],
            "s": s,
        }
    return runner


def _branchline_recipe() -> dict[str, Any]:
    """branchline 优化配方（参数=f0_ghz/z0_ohm——hfss_var_map 别名 f0/z0
    到达适配器，映射表别名钉的消费形态）。"""
    return {
        "model": "branchline_coupler",
        "params": {
            "f0_ghz": {"value": 2.4, "unit": "GHz"},
            "z0_ohm": {"value": 50.0, "unit": "Ohm"},
        },
        "setup": {"freq_range_ghz": [2.0, 2.8], "points": 41},
        "objectives": [
            # 谷深语义（#195 显式统计量名）+ max_below：s11_db_min ≤ -25
            # （带内谷深达 25dB 即达标；cost=max(0, val-threshold)，
            # 浅谷正罚、达标域 cost=0——min_above 会反向惩罚深谷，勿改）
            {"metric": "s11_db_min", "band": [2.3, 2.5], "op": "max_below",
             "value": -25},
        ],
        "optimization": {
            "params": {
                "f0_ghz": {"low": 2.0, "high": 2.8},
                "z0_ohm": {"low": 40.0, "high": 60.0},
            },
        },
    }


# --------------------------------------------------------------------------- #
# 注册面
# --------------------------------------------------------------------------- #


class TestRegistry:
    def test_ads_channel_registered(self):
        assert "ads" in channel_names()
        assert set(channel_names()) >= {"fake", "hfss", "openems", "ads"}

    def test_create_via_channel_returns_adapter(self, tmp_path):
        snp = _write_device_snp(tmp_path / "device.s4p")
        adapter, version = create_via_channel(
            "ads", setup_cfg={"freq_range_ghz": [2.0, 2.8], "points": 41},
            freq_range=[2.0, 2.8], freq_points=41,
            adapter_kwargs={
                "family": "branchline_cascade", "snp_path": str(snp),
                "runner": _branchline_fake_runner_factory(),
                "work_root": tmp_path / "ads_evals",
            },
            recipe_data={"model": "branchline_coupler"})
        try:
            assert version == "ads"
            assert isinstance(adapter, aoc.AdsOptAdapter)
            assert adapter.family == "branchline_cascade"
            assert adapter.health_check() is True
        finally:
            adapter.close()

    @pytest.mark.parametrize(
        "kwargs",
        [
            {},  # 缺 family
            {"family": "branchline_cascade"},  # 缺 snp_path
            {"family": "no_such_family", "snp_path": "x.s4p"},  # 族不存在
            {"family": "active_chain_sparam", "snp_path": "x.s4p"},  # MVP 外族显式拒
            {"family": "branchline_cascade", "snp_path": "x.s4p", "bogus": 1},  # 未知键
        ],
    )
    def test_factory_negative_returns_none_tuple(self, tmp_path, kwargs):
        if "snp_path" in kwargs and kwargs["snp_path"] == "x.s4p":
            kwargs = {**kwargs, "snp_path": str(tmp_path / "missing.s4p")}
        got = create_via_channel(
            "ads", setup_cfg={}, freq_range=[1.5, 3.5], freq_points=21,
            adapter_kwargs=kwargs, recipe_data={})
        assert got == (None, "")


# --------------------------------------------------------------------------- #
# #154 参数映射：显式表 + 渲染器签名核对 + 双向一致性钉
# --------------------------------------------------------------------------- #


class TestParamMapping:
    def test_mapped_keys_subset_of_renderer_signature(self):
        """映射表电路键 ⊆ 渲染器签名键（sweep 展开叶 ⊆ resolve_sweep 已知键）。

        #231 家法参数版：渲染器签名漂移而映射表未跟即红。
        """
        import inspect

        from rfauto.linkage import ads_template_family as atf

        sweep_known = {"fstart", "fstop", "npoints", "unit"}
        sig_br = set(inspect.signature(atf.render_branchline_cascade).parameters)
        sig_wk = set(inspect.signature(atf.render_wilkinson_snp).parameters)
        for family, sig in (("branchline_cascade", sig_br), ("wilkinson_snp", sig_wk)):
            for alias, (key, _transform) in aoc.ADS_CIRCUIT_PARAM_MAP[family].items():
                if key.startswith("sweep."):
                    assert key[len("sweep."):] in sweep_known, (family, alias, key)
                else:
                    assert key in sig, (family, alias, key)

    def test_metric_names_pinned_to_service_single_source(self):
        """ADS_OPT_METRIC_NAMES ↔ service.METRIC_NAMES 两 MVP 族逐键一致。

        （#231 双向一致性钉：测试属注册表消费者，service 侧表漂移即红。）
        """
        from rfauto.service.circuit_sim_service import METRIC_NAMES

        for family in ("wilkinson_snp", "branchline_cascade"):
            assert list(aoc.ADS_OPT_METRIC_NAMES[family]) == list(METRIC_NAMES[family])

    def test_transform_semantics_per_key(self):
        table = aoc.ADS_CIRCUIT_PARAM_MAP["branchline_cascade"]
        # f0：GHz 数值 → Hz（2.4 → 2.4e9；与 HFSS 通道 f0 变量同一物理量）
        assert table["f0_ghz"] == ("f0_hz", "ghz_to_hz")
        assert aoc._transform("ghz_to_hz", 2.4, "f0_ghz") == 2.4e9
        # z0/z_line/theta：ohm/deg 恒等（与 HFSS 通道同名变量同语义）
        assert table["z0_ohm"] == ("z0", "identity")
        assert aoc._transform("identity", 50.0, "z0_ohm") == 50.0
        # npoints：整数化
        assert aoc._transform("to_int", 41.0, "sweep.npoints") == 41
        assert isinstance(aoc._transform("to_int", 41.4, "sweep.npoints"), int)

    def test_bool_and_garbage_rejected_loud(self):
        with pytest.raises(ValueError, match="bool"):
            aoc._transform("identity", True, "z0_ohm")
        with pytest.raises(ValueError, match="无法按"):
            aoc._transform("ghz_to_hz", "not-a-number", "f0_ghz")

    def test_unknown_alias_lands_in_unconsumed(self, tmp_path):
        """插件 EM 几何变量（arm_len 等）合法路过但不进渲染（#154 透明面）。"""
        snp = _write_device_snp(tmp_path / "device.s4p")
        adapter = aoc.AdsOptAdapter(
            (2.0, 2.8), 41, family="branchline_cascade", snp_path=snp,
            runner=_branchline_fake_runner_factory(),
            work_root=tmp_path / "ads_evals")
        adapter.set_variables({"arm_len": "20.5mm", "f0": "2.4GHz"})
        assert adapter.unconsumed_variables == {"arm_len": 20.5}
        assert adapter.get_variables()["f0"] == 2.4

    def test_mapping_effectiveness_reaches_netlist(self, tmp_path):
        """端到端映射钉：变量表达式 → 渲染网表 F=/Z= 数字（#368 家法——
        映射表"效力断言"必须落在渲染产物上，不是只对表内键自说自话）。"""
        snp = _write_device_snp(tmp_path / "device.s4p")
        capture: list[str] = []
        adapter = aoc.AdsOptAdapter(
            (2.0, 2.8), 41, family="branchline_cascade", snp_path=snp,
            runner=_branchline_fake_runner_factory(capture),
            work_root=tmp_path / "ads_evals")
        adapter.set_variables({"f0": "2.45GHz", "z0": "52Ohm",
                               "arm_len": "20.5mm"})
        report = adapter.solve()
        assert report.success, report.message
        text = capture[-1]
        assert "F=2.45" in text  # f0(GHz) → TLIN F=(Hz/1e9)
        assert "Z=52" in text    # z0(Ohm) → Port Z
        params = adapter.last_circuit_params
        assert params["f0_hz"] == pytest.approx(2.45e9)
        assert params["z0"] == 52.0
        assert params["sweep"]["fstart"] == 2.0 and params["sweep"]["fstop"] == 2.8
        assert params["sweep"]["npoints"] == 41 and params["sweep"]["unit"] == "GHz"

    def test_sweep_override_params_win_over_setup_baseline(self, tmp_path):
        snp = _write_device_snp(tmp_path / "device.s4p")
        adapter = aoc.AdsOptAdapter(
            (2.0, 2.8), 41, family="branchline_cascade", snp_path=snp,
            runner=_branchline_fake_runner_factory(),
            work_root=tmp_path / "ads_evals")
        adapter.set_variables({"sweep.fstart_ghz": "2.1GHz",
                               "sweep.npoints": "61"})
        params = adapter._mapped_circuit_params()
        assert params["sweep"]["fstart"] == pytest.approx(2.1)  # 映射键覆盖基线
        assert params["sweep"]["npoints"] == 61
        assert params["sweep"]["fstop"] == 2.8  # 未覆盖键保基线


# --------------------------------------------------------------------------- #
# 适配器协议
# --------------------------------------------------------------------------- #


class TestAdapterProtocol:
    def _adapter(self, tmp_path, **kw):
        snp = _write_device_snp(tmp_path / "device.s4p")
        return aoc.AdsOptAdapter(
            (2.0, 2.8), 41, family=kw.pop("family", "branchline_cascade"),
            snp_path=snp, runner=kw.pop("runner", _branchline_fake_runner_factory()),
            work_root=tmp_path / "ads_evals", **kw)

    def test_solve_returns_report_and_network(self, tmp_path):
        adapter = self._adapter(tmp_path)
        adapter.set_variables({"f0": "2.4GHz", "z0": "50Ohm"})
        report = adapter.solve()
        assert report.success, report.message
        net = adapter.get_sparams()
        assert net.s.shape == (len(net.f), 2, 2)
        metrics = adapter.last_metrics
        assert metrics is not None
        assert set(metrics) == set(aoc.ADS_OPT_METRIC_NAMES["branchline_cascade"])
        adapter.close()

    def test_get_sparams_before_solve_raises(self, tmp_path):
        adapter = self._adapter(tmp_path)
        with pytest.raises(RuntimeError, match="无可用解"):
            adapter.get_sparams()

    def test_runner_failure_is_failure_report_not_raise(self, tmp_path):
        def bad_runner(_netlist: Path) -> dict[str, Any]:
            raise RuntimeError("注入求解器故障")
        adapter = self._adapter(tmp_path, runner=bad_runner)
        report = adapter.solve()
        assert report.success is False
        assert "注入求解器故障" in report.message
        adapter.close()

    def test_runner_non_dict_rejected(self, tmp_path):
        adapter = self._adapter(tmp_path, runner=lambda _p: "not-a-dict")
        report = adapter.solve()
        assert report.success is False
        assert "payload dict" in report.message

    def test_wilkinson_family_metrics_full_set(self, tmp_path):
        """wilkinson_snp 族：≥3 端口 payload → 四系统指标全产出（含平衡双键）。

        器件文件用 4 端口（skrf 原生可写回读；3 端口 skrf 写出自读即炸
        #248 家族），payload 4 端口（指标面只消费端口 1/2/3）。
        """
        snp = _write_device_snp(tmp_path / "device.s4p")
        freq_ghz = np.linspace(2.0, 2.8, 41)
        payload = {
            "frequency_hz": [float(f * 1e9) for f in freq_ghz],
            "port_names": ["P1", "P2", "P3", "P4"],
            "port_z": [[50.0, 0.0], [50.0, 0.0], [50.0, 0.0], [50.0, 0.0]],
            "s": {
                "1_1": [[0.1, 0.0] for _ in freq_ghz],
                "2_1": [[0.65, 0.0] for _ in freq_ghz],
                "3_1": [[0.65, 0.0] for _ in freq_ghz],
            },
        }

        def runner(_netlist: Path) -> dict[str, Any]:
            return payload

        adapter = aoc.AdsOptAdapter(
            (2.0, 2.8), 41, family="wilkinson_snp", snp_path=snp,
            runner=runner, work_root=tmp_path / "ads_evals")
        adapter.set_variables({"z0": "50Ohm"})
        report = adapter.solve()
        assert report.success, report.message
        metrics = adapter.last_metrics
        assert set(metrics) == set(aoc.ADS_OPT_METRIC_NAMES["wilkinson_snp"])
        assert metrics["system_gain_db"] == pytest.approx(-3.7, abs=0.2)

    def test_eval_artifacts_landed(self, tmp_path):
        snp = _write_device_snp(tmp_path / "device.s4p")
        root = tmp_path / "ads_evals"
        adapter = aoc.AdsOptAdapter(
            (2.0, 2.8), 41, family="branchline_cascade", snp_path=snp,
            runner=_branchline_fake_runner_factory(), work_root=root)
        adapter.solve()
        eval_dir = adapter.last_eval_dir
        assert (eval_dir / "branchline_cascade_netlist.txt").exists()

    def test_real_hpeesofsim_chain_skip_not_fail(self, tmp_path, monkeypatch):
        """真机链冒烟（可选，solo 预算 1 次 hpeesofsim；env 缺失→skip）。

        #295 家法：settings 相对 cwd 解析——沙箱 chdir 会丢 configs/
        settings.local.yaml，本测试改回仓根解析 ADS 安装（真机正规形态）；
        评估产物仍落 tmp 显式 work_root。
        """
        from rfauto.adapters import ads_netlist

        monkeypatch.chdir(src_dir.parent)  # 仓根（#295：settings 相对 cwd）
        try:
            ads_dir = ads_netlist._resolve_ads_dir(None)
        except Exception as exc:  # env 缺失如实 skip（skip-not-fail）
            pytest.skip(f"ADS env 不可解析: {exc}")
        if not (Path(ads_dir) / "bin" / "hpeesofsim.exe").exists():
            pytest.skip(f"hpeesofsim.exe 不存在: {ads_dir}")
        snp = _write_device_snp(tmp_path / "device.s4p")
        adapter = aoc.AdsOptAdapter(
            (2.0, 2.8), 41, family="branchline_cascade", snp_path=snp,
            runner=None, ads_dir=ads_dir, work_root=tmp_path / "ads_evals_real")
        adapter.set_variables({"f0": "2.4GHz", "z0": "50Ohm"})
        report = adapter.solve()
        assert report.success, report.message
        assert adapter.last_metrics is not None


# --------------------------------------------------------------------------- #
# 离线 e2e：迷你优化 + 确定性（判据写死数值）
# --------------------------------------------------------------------------- #


class TestOfflineE2E:
    def test_mini_optimization_cost_improves(self, tmp_path):
        recipe_path = tmp_path / "ads_br_recipe.yaml"
        recipe_path.write_text(
            yaml.safe_dump(_branchline_recipe(), allow_unicode=True),
            encoding="utf-8")
        snp = _write_device_snp(tmp_path / "device.s4p")
        result = run_optimization(
            recipe_path, adapter_name="ads", max_trials=8, seed=7,
            study_name="ads_channel_e2e",
            adapter_kwargs={
                "family": "branchline_cascade", "snp_path": str(snp),
                "runner": _branchline_fake_runner_factory(),
                "work_root": tmp_path / "ads_evals",
            })
        assert result["ok"], result.get("errors")
        assert result["trials_completed"] >= 6  # 罚路径未吞没评估
        # 预声明判据（写死）：谷形响应下 8 步内 best_cost 收敛到 0（谷深
        # ≥25dB 目标带达成）；初轮随机起点 cost>0（搜索真的在走）
        assert result["best_cost"] is not None
        assert result["best_cost"] <= 0.0
        best = result["best_params"]
        # best 落在谷区（0-cost 域宽 df≈±0.2/dz≈±6，容差留边界余量）
        assert abs(best["f0_ghz"] - 2.4) <= 0.25
        assert abs(best["z0_ohm"] - 50.0) <= 9.0

    def test_same_seed_two_runs_bitwise_identical(self, tmp_path):
        recipe_path = tmp_path / "ads_br_recipe.yaml"
        recipe_path.write_text(
            yaml.safe_dump(_branchline_recipe(), allow_unicode=True),
            encoding="utf-8")
        snp = _write_device_snp(tmp_path / "device.s4p")
        kw = dict(
            adapter_name="ads", max_trials=8, seed=7,
            adapter_kwargs={
                "family": "branchline_cascade", "snp_path": str(snp),
                "runner": _branchline_fake_runner_factory(),
                "work_root": tmp_path / "ads_evals",
            })
        r1 = run_optimization(recipe_path, study_name="ads_det_a", **kw)
        r2 = run_optimization(recipe_path, study_name="ads_det_b", **kw)
        assert r1["ok"] and r2["ok"]
        assert r1["best_cost"] == r2["best_cost"]
        assert r1["best_params"] == r2["best_params"]

    def test_unknown_channel_still_none_tuple(self):
        """未注册名 fallthrough 语义不受 ads 注册影响（既有钉同域复验）。"""
        assert create_via_channel(
            "nope", setup_cfg={}, freq_range=[1.5, 3.5], freq_points=21,
            adapter_kwargs=None, recipe_data={}) == (None, "")

    def test_service_bootstrap_registers_ads_channel(self):
        """主代理合流笔：service 调优入口惰性注册引导（tuning._ensure_ads_channel）。

        分层链：optimization 禁静态 import linkage——注册引导住 service
        start_tune（B3 席遗留 1 的合流清偿）。
        """
        from rfauto.optimization.adapter_channels import channel_names
        from rfauto.service.api.tuning import _ensure_ads_channel

        _ensure_ads_channel()
        assert "ads" in channel_names()
