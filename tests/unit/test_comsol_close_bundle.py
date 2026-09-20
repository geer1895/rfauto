"""COMSOL 收口包离线门（零 COMSOL/license/JVM）。

覆盖（对应 scripts/comsol_afs_realcase.py、scripts/comsol_mline_tem_benchmark.py
--port-sweep 腿、scripts/comsol_microwave_oven.py Figure 3 字段）：
A. 持久模型单频重解（comsol_adapter.resolve_s21_at_frequency）Java 序列钉官方
   口径：freq 步 plist 单点 → study.run → EvalGlobal 唯一 tag（先 remove 兜底）
   → 复数 S21 回读 + 频率一致性守卫；
B. AFS 真机 harness 内核离线跑（合成/闭式回调当真响应）：run_afs_core 全链
   （含 §10.20⑩ at_least_vg 判据消费）+ judge_afs 判据边界 + 未收敛诚实路径
   （#122：不凑绿）；
C. TEM×Parametric 端口扫描腿参数面：全矩阵无源/互易判据纯函数、study 步序
   硬校验（bma1/bma2/param 均在 freq 前）、CLI 参数与产物路径存在性；
D. oven 报告新字段 t_center_series_c（官方 Figure 3 对照数据）+ 中心温度曲线
   PNG 渲染（matplotlib Agg）+ --fig3-curve 接线存在性。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest

from rfauto.adapters import comsol_adapter as ca
from rfauto.adapters.comsol_adapter import (
    ComsolAdapter,
    tl_section_sparams,
)
from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import comsol_afs_realcase as afs_mod
import comsol_microwave_oven as mo
import comsol_mline_tem_benchmark as bench_mod

# ─── Java 链式调用录制桩（test_comsol_tail 同模式，EvalGlobal 单频 2 行数据）──


class _JavaRecorder:
    """任意属性 → 可调用 → 返回子桩；getReal/getImag 回放预置数据。"""

    def __init__(self, calls: list, data: dict, path: str = ""):
        self._calls = calls
        self._data = data
        self._path = path

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)

        def _call(*args):
            full = f"{self._path}.{name}" if self._path else name
            self._calls.append((full, args))
            if name == "getReal":
                return self._data["real"]
            if name == "getImag":
                return self._data["imag"]
            if name == "tags":  # dataset().tags()：装配循环遍历的解数据集
                return list(self._data.get("tags", ["dset1"]))
            return _JavaRecorder(self._calls, self._data, full)

        return _call


class _FakeModel:
    def __init__(self, calls, data):
        self.java = _JavaRecorder(calls, data)
        self.saved: list[str] = []

    def save(self, path):
        self.saved.append(str(path))


class _FakeClient:
    def __init__(self, data):
        self.calls: list = []
        self.data = data

    def create(self, name):
        return _FakeModel(self.calls, self.data)

    def remove(self, model):
        pass


def _calls_named(calls, suffix):
    return [(n, a) for n, a in calls if n.endswith(suffix)]


def _full_eval_data(freqs_ghz, eps_eff=2.85264, z_line=50.0, length_mm=40.0):
    """6 行 EvalGlobal 数据（freq/PortName/S11/S21/S12/S22），列=解（独立行对象）。

    test_comsol_tail._full_eval_data 的单文件版：端口 1 列只定义 S11/S21、
    端口 2 列只定义 S12/S22（非本激励值填哨兵 9/8，装配不得采用）。
    """
    f = np.asarray(freqs_ghz, float)
    s = tl_section_sparams(f, eps_eff, z_line, length_mm)
    n = len(f)
    real = [[] for _ in range(6)]
    imag = [[] for _ in range(6)]
    for col in range(2 * n):
        k, exc = (col, 1) if col < n else (col - n, 2)
        real[0].append(f[k] * 1e9)
        real[1].append(float(exc))
        imag[0].append(0.0)
        imag[1].append(0.0)
        if exc == 1:
            vals = [s[k, 0, 0], s[k, 1, 0], 9.0 + 9.0j, 9.0 + 9.0j]
        else:
            vals = [8.0 + 8.0j, 8.0 + 8.0j, s[k, 0, 1], s[k, 1, 1]]
        for r, v in enumerate(vals, start=2):
            real[r].append(float(np.real(v)))
            imag[r].append(float(np.imag(v)))
    return {"real": real, "imag": imag}


@pytest.fixture
def oven_spec():
    return mo.normalize_oven_params(None)


# ─── A: 持久模型单频重解 ─────────────────────────────────────────────────────


class TestResolveS21AtFrequency:
    DATA: ClassVar[dict] = {"real": [[2.5e9], [0.9]], "imag": [[0.0], [-0.3]]}

    def _resolved(self, monkeypatch, data=None):
        monkeypatch.setattr(ca, "mph_installed", lambda: True)
        cfg = EMSolverConfig(
            solver_type=EMSolverType.COMSOL,
            working_dir="work",
            freq_range_ghz=(2.3, 2.7),
            mesh_resolution_mm=0.5,
            extra_params={},
        )
        adapter = ComsolAdapter(cfg, client_factory=lambda: None)
        calls: list = []
        model = _FakeModel(calls, data or self.DATA)
        val = adapter.resolve_s21_at_frequency(model, 2.5)
        return adapter, calls, val

    def test_java_sequence_matches_official_chain(self, monkeypatch):
        _adapter, calls, val = self._resolved(monkeypatch)
        # 回读值=复数 S21（getReal/getImag 各取 S21 行）
        assert val == pytest.approx(complex(0.9, -0.3))
        sets = [a for _, a in _calls_named(calls, ".set")]
        # ① freq 步 plist 重写为单点（显式单位）
        assert ("plist", "2.5[GHz]") in sets
        # ② EvalGlobal 只读 freq + S21 两行
        assert ("expr", ["freq", "comp1.emw.S21"]) in sets
        # 时序：plist set → study.run → remove（兜底）→ create（唯一 tag）
        idx_plist = next(i for i, (n, a) in enumerate(calls)
                         if n.endswith(".set") and a[:1] == ("plist",))
        idx_run = next(i for i, (n, _a) in enumerate(calls)
                       if n.endswith("study.run"))
        idx_rm = next(i for i, (n, a) in enumerate(calls)
                      if n.endswith("numerical.remove"))
        idx_create = next(i for i, (n, a) in enumerate(calls)
                          if n.endswith("numerical.create"))
        assert idx_plist < idx_run < idx_rm < idx_create
        assert calls[idx_rm][1] == ("gev_s21_r1",)
        assert calls[idx_create][1] == ("gev_s21_r1", "EvalGlobal")

    def test_eval_tag_unique_across_calls(self, monkeypatch):
        adapter, calls, _val = self._resolved(monkeypatch)
        model = _FakeModel(calls, {"real": [[2.4e9], [0.8]],
                                   "imag": [[0.0], [0.1]]})
        assert adapter.resolve_s21_at_frequency(model, 2.4) == pytest.approx(
            complex(0.8, 0.1))
        tags = [a[0] for n, a in calls if n.endswith("numerical.create")]
        assert tags == ["gev_s21_r1", "gev_s21_r2"]  # 自增后缀不撞名

    def test_freq_consistency_guard(self, monkeypatch):
        bad = {"real": [[2.0e9], [0.9]], "imag": [[0.0], [-0.3]]}
        with pytest.raises(RuntimeError, match="不一致"):
            self._resolved(monkeypatch, data=bad)

    def test_none_model_rejected(self):
        monkeypatch_free = ca.ComsolAdapter.__new__(ca.ComsolAdapter)
        with pytest.raises(RuntimeError, match="持久模型不可用"):
            monkeypatch_free.resolve_s21_at_frequency(None, 2.5)

    def test_shape_guard(self, monkeypatch):
        bad_shape = {"real": [[2.5e9, 0.9]], "imag": [[0.0, -0.3]]}
        with pytest.raises(RuntimeError, match="形状异常"):
            self._resolved(monkeypatch, data=bad_shape)


# ─── B: AFS 真机 harness 内核（离线合成回调）──────────────────────────────────


class TestAfsRealcaseCore:
    FREQS_FULL: ClassVar[np.ndarray] = np.linspace(2.3, 2.7, 41)

    @staticmethod
    def _lossy_s21(freqs: np.ndarray) -> np.ndarray:
        """真实量级有耗 mline S21 合成：介质损耗 ~-0.05dB@2.5GHz ×(f/2.5)。

        量级口径：rogers4350b tanδ=0.0037 → α_d≈1.25dB/m@2.5GHz → 40mm 段
        -0.05 dB（跨带 span ~0.01 dB），叠加微失配端口纹波（|S11|~-33dB）。
        离线审计实证（模块 docstring）：此形态下 VF 模型幅度误差 ~6e-4 dB、
        FSV Ex；纯无耗平线则 FSV 结构性退化（见退化边界测试）。
        """
        s = tl_section_sparams(freqs, 2.85264, 51.8, 40.0)
        att_db = -0.05 * (freqs / 2.5)
        return s[:, 1, 0] * 10 ** (att_db / 20.0)

    def _evaluate(self, s21: np.ndarray):
        f_ghz = self.FREQS_FULL

        def evaluate(f_hz: float) -> complex:
            g = f_hz / 1e9
            return complex(np.interp(g, f_ghz, s21.real)
                           + 1j * np.interp(g, f_ghz, s21.imag))

        return evaluate

    def test_core_runs_full_chain_on_synthetic_callback(self):
        s21 = self._lossy_s21(self.FREQS_FULL)
        summary = afs_mod.run_afs_core(
            self._evaluate(s21),
            afs_mod.full_scan_interpolator(self.FREQS_FULL, s21),
            float(self.FREQS_FULL[0] * 1e9), float(self.FREQS_FULL[-1] * 1e9),
            n_full=41)
        # §10.20⑩ 冻结判据在真实量级合成回调上全过（harness 逻辑离线实证）
        assert summary["status"] == "converged"
        vs = summary["vs_full"]
        assert vs["n_full"] == 41
        assert vs["fsv"]["at_least_vg"] is True
        assert vs["reduction_ratio"] >= 0.5
        assert afs_mod.judge_afs(summary)["verdict"] == "PASS"

    def test_lossless_flat_reference_degenerates_fsv_honestly(self):
        # 退化边界（离线审计留证，#195 同族常数陷阱）：纯无耗匹配线
        # |S21| dB 恒 ≈ 0（跨带 span ~1e-7 dB）→ FSV 归一化分母近零 →
        # 结构性非 VG。判据如实 FAIL 是正确行为——这正是真机必建 tanδ 的
        # 依据（模块 docstring），非 harness 缺陷。
        s21 = tl_section_sparams(self.FREQS_FULL, 2.85264, 50.011,
                                 40.0)[:, 1, 0]
        db_span = float(np.ptp(20 * np.log10(np.abs(s21))))
        assert db_span < 1e-5  # 真值参考确为平线（退化前提成立）
        summary = afs_mod.run_afs_core(
            self._evaluate(s21),
            afs_mod.full_scan_interpolator(self.FREQS_FULL, s21),
            float(self.FREQS_FULL[0] * 1e9), float(self.FREQS_FULL[-1] * 1e9),
            n_full=41)
        assert summary["converged"] is True  # 拟合本身收敛
        assert summary["vs_full"]["fsv"]["at_least_vg"] is False
        assert afs_mod.judge_afs(summary)["verdict"] == "FAIL"

    def test_judge_afs_criterion_boundaries(self):
        good = {
            "converged": True, "status": "converged",
            "vs_full": {"n_full": 41, "n_solves": 9,
                        "reduction_ratio": 1 - 9 / 41,
                        "fsv": {"at_least_vg": True, "gdm_mean": 0.05,
                                "gdm_grade": "VG"}},
        }
        assert afs_mod.judge_afs(good)["verdict"] == "PASS"
        # FSV 不足 VG → FAIL 且给原因
        low_fsv = {**good, "vs_full": {**good["vs_full"],
                                       "fsv": {"at_least_vg": False,
                                               "gdm_mean": 0.6,
                                               "gdm_grade": "G"}}}
        out = afs_mod.judge_afs(low_fsv)
        assert out["verdict"] == "FAIL"
        assert any("FSV" in r for r in out["reasons"])
        # 缩减比不足（n_solves > n_full/2）→ FAIL
        low_red = {**good, "vs_full": {**good["vs_full"], "n_solves": 25,
                                       "reduction_ratio": 1 - 25 / 41}}
        out = afs_mod.judge_afs(low_red)
        assert out["verdict"] == "FAIL"
        assert any("缩减比" in r for r in out["reasons"])
        # 未提供全扫参考 → FAIL（不静默）
        out = afs_mod.judge_afs({"converged": True, "status": "converged"})
        assert out["verdict"] == "FAIL"
        assert any("vs_full" in r for r in out["reasons"])

    def test_non_convergent_case_is_honest_fail(self):
        # 紧 tol × 纹波成分 → 未收敛，judge 如实 FAIL（#122：不重试凑绿）
        f_ghz = self.FREQS_FULL
        base = tl_section_sparams(f_ghz, 2.85264, 50.011, 40.0)[:, 1, 0]
        ripple = 1.0 - 0.08 * (0.5 + 0.5 * np.cos(
            2 * np.pi * (f_ghz - f_ghz[0]) / 0.09))
        s21 = base * ripple

        def evaluate(f_hz: float) -> complex:
            g = f_hz / 1e9
            return complex(np.interp(g, f_ghz, s21.real)
                           + 1j * np.interp(g, f_ghz, s21.imag))

        summary = afs_mod.run_afs_core(
            evaluate, afs_mod.full_scan_interpolator(f_ghz, s21),
            float(f_ghz[0] * 1e9), float(f_ghz[-1] * 1e9),
            n_full=41, max_points=24, tol=1e-6)
        assert summary["converged"] is False
        out = afs_mod.judge_afs(summary)
        assert out["verdict"] == "FAIL"
        assert any("未收敛" in r for r in out["reasons"])

    def test_interpolator_roundtrips_samples(self):
        s21 = self._lossy_s21(self.FREQS_FULL)
        resp = afs_mod.full_scan_interpolator(self.FREQS_FULL, s21)
        dense = resp(self.FREQS_FULL * 1e9)
        assert np.allclose(dense, s21, atol=1e-12)  # 节点处精确回放
        assert resp(np.array([2.5e9])).shape == (1,)


class TestAfsScriptSurface:
    def test_script_pins_official_chain_and_criterion(self):
        src = (Path(__file__).resolve().parents[2]
               / "scripts" / "comsol_afs_realcase.py").read_text(
                   encoding="utf-8")
        assert "resolve_s21_at_frequency" in src  # 单频重解回调
        assert "at_least_vg" in src  # §10.20⑩ 冻结判据
        assert "mline_port_chain" in src and '"tem"' in src
        assert '"6.3"' in src  # 版本钉扎（#215）
        assert "--n-full" in src and "41" in src
        assert "--loss-tangent" in src  # 判据非退化前提：tanδ 必建
        assert afs_mod.LOSS_TANGENT_DEFAULT == 0.0037

    def test_dry_run_offline(self, capsys):
        assert afs_mod.main(["--dry-run"]) == 0
        out = capsys.readouterr().out
        assert "dry-run" in out
        assert "2.3" in out and "2.7" in out
        assert "0.0037" in out  # 默认 tanδ 进计划


# ─── C: TEM×Parametric 端口扫描腿参数面 ───────────────────────────────────────


class TestPortSweepLeg:
    def test_assembly_ignores_bma_zero_columns(self):
        # 回归（2026-09-15 tem×Parametric 真机实证，#26②）：TEM 链的 bma 步
        # （modeFreq=带中值）产生带 freq/PortName 的解数据集，其 S 表达式
        # 未定义回读精确 0——曾覆盖 2.5 GHz 行 S12/S22 真值（互易残差 0.98
        # 假象，原生 Touchstone 同频点完整）。装配必须跳过全零列且首有效
        # 列不被覆盖。
        freqs = [2.3, 2.5, 2.7]
        data = _full_eval_data(freqs)
        # 注入 bma 零列（freq=2.5e9、PortName=2、S11..S22 全 0）——列追加
        # 到 6 行末尾（行=表达式：freq/PortName/S11/S21/S12/S22）
        for row, value in zip(data["real"], [2.5e9, 2.0, 0.0, 0.0, 0.0, 0.0],
                              strict=True):
            row.append(value)
        for row in data["imag"]:
            row.append(0.0)
        model = _FakeModel([], data)
        _f_ghz, s = ComsolAdapter._extract_sparams_full(model, freqs)
        assert np.all(np.isfinite(s))
        expected = tl_section_sparams(np.asarray(freqs), 2.85264, 50.0, 40.0)
        assert np.allclose(s, expected, atol=1e-12)  # 2.5 行不被零列污染

    def test_extra_checks_passivity_reciprocity(self):
        freqs = np.linspace(2.3, 2.7, 5)
        s = tl_section_sparams(freqs, 2.85264, 50.011, 40.0)
        checks = bench_mod.parametric_extra_checks(s)
        assert checks["passive_ok"] is True
        assert checks["reciprocity_ok"] is True
        assert checks["max_abs_s"] == pytest.approx(1.0, abs=1e-6)
        # 增益（|S|>1+tol）→ 无源性 FAIL
        bad = bench_mod.parametric_extra_checks(s * 1.05)
        assert bad["passive_ok"] is False
        # 非互易扰动 → 互易 FAIL
        nr = s.copy()
        nr[:, 0, 1] *= 1.1
        bad = bench_mod.parametric_extra_checks(nr)
        assert bad["reciprocity_ok"] is False

    def test_parametric_step_order_guard(self):
        bench_mod._assert_parametric_step_order(
            ["bma1", "bma2", "param", "freq"])
        bench_mod._assert_parametric_step_order(
            ["param", "bma1", "bma2", "freq"])
        with pytest.raises(RuntimeError, match="步序非法"):
            bench_mod._assert_parametric_step_order(
                ["freq", "bma1", "bma2", "param"])
        with pytest.raises(RuntimeError, match="为空"):
            bench_mod._assert_parametric_step_order([])

    def test_script_surface_pins_parametric_leg(self):
        src = (Path(__file__).resolve().parents[2] / "scripts"
               / "comsol_mline_tem_benchmark.py").read_text(encoding="utf-8")
        assert "--port-sweep" in src
        assert "mline_tem_parametric" in src
        assert "_assert_parametric_step_order" in src
        assert "comsol_native" in src  # Touchstone 原生导出核验
        # probe-only 腿支持 port_sweep（零席位验步序）
        assert "def probe_only(loss_tangent" in src
        assert "port_sweep" in src


# ─── D: oven Figure 3 对照面 ─────────────────────────────────────────────────


class TestOvenFigure3:
    OPTS: ClassVar[dict] = {
        "thermal": "transient", "h_conv_w_m2k": 10.0, "t_ext_degc": 8.0,
        "mesh_hmax_mm": 15.0, "potato_hmax_mm": 3.0,
        "t_list": "range(0,1,5)",
    }

    def test_report_carries_center_temperature_series(self, oven_spec):
        m = mo.potato_mass_kg(oven_spec)
        predicted = 631.0 * 5.0 / (m * mo.POTATO_CP_J_KG_K)
        t_avg = 8.0 + predicted
        series = [8.0 + predicted * (0.4 + 0.6 * k) for k in range(6)]
        series[-1] = 8.0 + predicted * 2.5  # 中心峰化保持（末点 ≥2.5×）
        # 读数序：P_abs, T_max, T_min, T_avg, 中心截点 T 序列（transient）
        model = _CloseStubModel(
            [[[631.0]], [[t_avg + 40.0]], [[t_avg - 5.0]], [[t_avg]],
             [series]])
        report, _ = mo.evaluate_oven(model, oven_spec, self.OPTS,
                                     wall_time_s=1.0)
        got = report["center_probe"]["t_center_series_c"]
        assert got == pytest.approx(series)
        assert len(got) == 6  # range(0,1,5) → 6 输出时刻（官方 Figure 3 口径）
        assert report["center_probe"]["t_center_c"] == pytest.approx(
            series[-1])
        # 既有字段零回归
        assert report["temperature_anchor"]["times_s"] == [0.0, 1, 2, 3, 4, 5]
        assert report["checks"]["center_peaked"] is True

    def test_center_curve_png_rendered_deterministically(self, tmp_path,
                                                         oven_spec):
        times = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
        temps = [8.0, 15.0, 25.0, 40.0, 55.0, 65.0]
        path = tmp_path / "fig3" / "center_curve_fig3.png"
        out = mo.render_center_curve_png(times, temps, path)
        assert out == str(path)
        assert path.exists() and path.stat().st_size > 0
        # 再次渲染同尺寸（确定性输出）
        size_first = path.stat().st_size
        mo.render_center_curve_png(times, temps, path)
        assert path.stat().st_size == size_first

    def test_fig3_curve_wiring_present(self):
        src = (Path(__file__).resolve().parents[2] / "scripts"
               / "comsol_microwave_oven.py").read_text(encoding="utf-8")
        assert "--fig3-curve" in src
        assert "render_center_curve_png" in src
        assert "t_center_series_c" in src


class _CloseStubModel:
    """读数队列桩（test_comsol_microwave_oven._Recorder 的单文件最小版）。

    real 队列按 getReal 调用序弹出；无 getImag 消费（本组用例全部实数读数）。
    """

    def __init__(self, real_queue):
        self._real = list(real_queue)
        self.java = _QueueRecorder(self._real)

    def datasets(self):
        return []

    def evaluate(self, expression, unit=None, dataset=None):
        return None  # temperature_field best-effort → None（不阻塞主路径）


class _QueueRecorder:
    def __init__(self, real_queue):
        self._real = real_queue

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)

        def _call(*args):
            if name == "getReal":
                return self._real.pop(0)
            return self

        return _call
