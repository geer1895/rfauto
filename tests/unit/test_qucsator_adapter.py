"""N7 QucsatorAdapter 适配器测试（DP-14 §14.2）。

离线、确定性为主（无真机不红）：
- exe 解析链（env/settings/工作区/E 盘安装点/PATH + FileNotFoundError）；
- 网表渲染（SUBST+MLIN+Pac+.SP 语法标定、SI 数值、校验拒绝、确定性）；
- dataset 解析（真机 fixture 冻结格式：复数单 token re±jim / 纯实数）；
- β 相位提取（含 2π 分支选择）与三方对照泛化内核；
- NOT_SUPPORTED 显式拒绝（非 mline 模板）；
- mock exe 求解链（全 S 矩阵装配 + 产物落盘 + 重读）；
- 注册面双树态（QUCSATOR 枚举缺失=跳过不污染；存在=注册枚举键）；
- HJ 腿 vs openEMS 金锚（runs/benchmark/mline_mauto 冻结值，两腿 ≤2%）
  + 与 test_meep_adapter._OPENEMS_GOLDEN 互检防漂移。

真机通道（qucsator_rf 本机已装 E:\\tools\\qucsatorRF）：skipif 钉住
qucsator_available()——缺席环境如实 skip 不假绿（#122）；真跑判据=
三方互差 ≤0.05 + 同网表两次运行 dataset 逐字节相同。
"""

from __future__ import annotations

import stat
import sys

import numpy as np
import pytest

sys.path.insert(0, "src")

# ── 冻结 fixture（2026-09-24 qucsator_rf 26.1.1 真机 3 频点 dataset，逐字节）──

_FIXTURE_DATASET = """<Qucs Dataset 1.0.7>
<indep frequency 3>
  +2.25000000000000000000e+09
  +2.50000000000000000000e+09
  +2.75000000000000000000e+09
</indep>
<dep S[1,1] frequency>
  -2.79635705177705103704e-04-j5.92970404995070421439e-04
  -3.26599643536152998979e-03-j7.45876821575613795090e-03
  -9.99241556595296780141e-03-j1.07526612543428472940e-02
</dep>
<dep S[1,2] frequency>
  -9.87682755298038839165e-01+j2.70677423720884317848e-02
  -9.16559831548845460603e-01+j3.66411965126424432615e-01
  -7.32607257498512187688e-01+j6.60055920469288959218e-01
</dep>
<dep S[2,1] frequency>
  -9.87682755298038839165e-01+j2.70677423720884317848e-02
  -9.16559831548845460603e-01+j3.66411965126424432615e-01
  -7.32607257498512187688e-01+j6.60055920469288959218e-01
</dep>
<dep S[2,2] frequency>
  -2.79635705177705103704e-04-j5.92970404995070421439e-04
  -3.26599643536152998979e-03-j7.45876821575613795090e-03
  -9.99241556595296780141e-03-j1.07526612543428472940e-02
</dep>
"""

_FREQS_HZ = [2.25e9, 2.5e9, 2.75e9]

# 金锚源：runs/benchmark/mline_mauto/port_beta.csv（#162 β 金标准），与
# tests/unit/test_meep_adapter.py::_OPENEMS_GOLDEN 同一冻结值。
_OPENEMS_GOLDEN = {2.25: 80.55376868947421, 2.5: 89.50940246779182,
                   2.75: 98.45637105318495}


def _default_stackup():
    from rfauto.core.synthesis import Stackup
    return Stackup(name="rogers4350b", epsilon_r=3.66, thickness_mm=0.508,
                   loss_tangent=0.0037, rho=1.724e-8)


# ── exe 解析链 ────────────────────────────────────────────────────────────────

class TestExeResolution:
    def test_env_var_file_and_dir(self, tmp_path, monkeypatch):
        from rfauto.adapters.qucsator_adapter import resolve_qucsator_exe
        exe = tmp_path / "qucsator_rf.exe"
        exe.write_bytes(b"")
        monkeypatch.setenv("RFAUTO_QUCSATOR_BIN", str(exe))
        assert resolve_qucsator_exe() == exe
        monkeypatch.setenv("RFAUTO_QUCSATOR_BIN", str(tmp_path))
        assert resolve_qucsator_exe() == exe

    def test_explicit_overrides_env(self, tmp_path, monkeypatch):
        from rfauto.adapters.qucsator_adapter import resolve_qucsator_exe
        a = tmp_path / "a.exe"
        b = tmp_path / "b.exe"
        a.write_bytes(b"")
        b.write_bytes(b"")
        monkeypatch.setenv("RFAUTO_QUCSATOR_BIN", str(b))
        assert resolve_qucsator_exe(a) == a

    def test_settings_yaml_entry_used_when_env_unset(self, tmp_path, monkeypatch):
        import rfauto.adapters.qucsator_adapter as mod
        yaml_exe = tmp_path / "from_yaml.exe"
        yaml_exe.write_bytes(b"")
        monkeypatch.delenv("RFAUTO_QUCSATOR_BIN", raising=False)
        monkeypatch.setattr(mod, "_exe_from_solvers_yaml", lambda: yaml_exe)
        # 工作区/E 盘安装点在 tmp 用例里不可达时才轮到 settings——把后续候选也屏蔽
        monkeypatch.setattr(mod, "_WORKSPACE_QUCSATOR", tmp_path / "nope_dir")
        monkeypatch.setattr(mod, "_DRIVE_INSTALL_QUCSATOR",
                            (tmp_path / "nope1", tmp_path / "nope2"))
        assert mod.resolve_qucsator_exe() == yaml_exe

    def test_missing_everywhere_raises_with_hint(self, tmp_path, monkeypatch):
        import rfauto.adapters.qucsator_adapter as mod
        monkeypatch.delenv("RFAUTO_QUCSATOR_BIN", raising=False)
        monkeypatch.setattr(mod, "_exe_from_solvers_yaml", lambda: None)
        monkeypatch.setattr(mod, "_WORKSPACE_QUCSATOR", tmp_path / "nope")
        monkeypatch.setattr(mod, "_DRIVE_INSTALL_QUCSATOR",
                            (tmp_path / "nope1", tmp_path / "nope2"))
        monkeypatch.setattr(mod, "_QUCSATOR_EXE_CANDIDATES", ("definitely_not_on_path_xyz",))
        with pytest.raises(FileNotFoundError, match="RFAUTO_QUCSATOR_BIN"):
            mod.resolve_qucsator_exe()

    def test_available_never_raises(self, tmp_path, monkeypatch):
        import rfauto.adapters.qucsator_adapter as mod
        monkeypatch.setattr(mod, "resolve_qucsator_exe",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        assert mod.qucsator_available() is False


# ── 网表渲染 ─────────────────────────────────────────────────────────────────

class TestRenderMlineNetlist:
    def test_syntax_tokens_calibrated(self):
        from rfauto.adapters.qucsator_adapter import render_mline_netlist
        text = render_mline_netlist(1.113, 40.0, _default_stackup(), list(_FREQS_HZ))
        assert text.splitlines()[0].startswith("# ")
        assert "SUBST:SUB1 er=" in text and "tand=0.0037" in text
        assert 'Subst="SUB1" Model="Hammerstad" DispModel="Kirschning"' in text
        # SP 动作必须带点前缀（parse_netlist.ypp ActionLine 语法标定）
        assert '.SP:SP1 Type="lin" Start=2250000000 Stop=2750000000 Points=3' in text
        # SP 分析必须有显式 Pac 端口（缺 Pac = checker error）
        assert "Pac:P1 _net0 gnd Num=1 Z=50" in text
        assert "Pac:P2 _net1 gnd Num=2 Z=50" in text
        # rho 走 SI（Ω·m）——Ω·mm²/m 口径会让导体损耗模型爆掉（真机标定）
        assert "rho=1.724" in text
        # 纯 ASCII（网表以 ascii 落盘）
        text.encode("ascii")

    def test_deterministic_render(self):
        from rfauto.adapters.qucsator_adapter import render_mline_netlist
        a = render_mline_netlist(1.113, 40.0, _default_stackup(), list(_FREQS_HZ))
        b = render_mline_netlist(1.113, 40.0, _default_stackup(), list(_FREQS_HZ))
        assert a == b

    def test_validation_rejects_bad_inputs(self):
        from dataclasses import replace

        from rfauto.adapters.qucsator_adapter import render_mline_netlist
        st = _default_stackup()
        with pytest.raises(ValueError):
            render_mline_netlist(0.0, 40.0, st, list(_FREQS_HZ))
        with pytest.raises(ValueError):
            render_mline_netlist(1.113, -1.0, st, list(_FREQS_HZ))
        with pytest.raises(ValueError, match="er"):
            render_mline_netlist(1.113, 40.0, replace(st, epsilon_r=0.5), list(_FREQS_HZ))
        with pytest.raises(ValueError):
            render_mline_netlist(1.113, 40.0, st, [2.5e9])            # 单频点
        with pytest.raises(ValueError):
            render_mline_netlist(1.113, 40.0, st, [2.5e9, 2.25e9])    # 非递增
        with pytest.raises(ValueError):
            render_mline_netlist(1.113, 40.0, replace(st, rho=0.0), list(_FREQS_HZ))
        with pytest.raises(ValueError):
            render_mline_netlist(1.113, 40.0, replace(st, loss_tangent=-0.1), list(_FREQS_HZ))


# ── dataset 解析 ─────────────────────────────────────────────────────────────

class TestParseQucsDataset:
    def test_real_fixture_full_matrix(self):
        from rfauto.adapters.qucsator_adapter import parse_qucs_dataset
        out = parse_qucs_dataset(_FIXTURE_DATASET)
        assert out["freq_hz"].tolist() == _FREQS_HZ
        assert set(out["S"]) == {(1, 1), (1, 2), (2, 1), (2, 2)}
        s21 = out["S"][(2, 1)]
        assert abs(s21[0]) == pytest.approx(0.988055, rel=1e-4)
        assert out["S"][(1, 1)][0] == complex(-2.79635705177705103704e-04,
                                             -5.92970404995070421439e-04)

    def test_pure_real_dep_values_accepted(self):
        from rfauto.adapters.qucsator_adapter import parse_qucs_dataset
        text = ("<Qucs Dataset 1.0.7>\n<indep frequency 2>\n+1e9\n+2e9\n</indep>\n"
                "<dep S[1,1] frequency>\n+0.5\n-0.25\n</dep>\n")
        out = parse_qucs_dataset(text)
        assert out["S"][(1, 1)][1] == complex(-0.25, 0.0)

    def test_non_s_dep_block_skipped(self):
        from rfauto.adapters.qucsator_adapter import parse_qucs_dataset
        text = ("<indep frequency 1>\n+1e9\n</indep>\n"
                "<dep S[1,1] frequency>\n+0.1\n</dep>\n"
                "<dep V[1] frequency>\n+0.9\n</dep>\n")
        out = parse_qucs_dataset(text)
        assert set(out["S"]) == {(1, 1)}

    def test_corrupt_count_and_empty_raise(self):
        from rfauto.adapters.qucsator_adapter import QucsatorError, parse_qucs_dataset
        with pytest.raises(QucsatorError, match="无频点"):
            parse_qucs_dataset("<Qucs Dataset 1.0.7>\n")
        bad = ("<indep frequency 2>\n+1e9\n+2e9\n</indep>\n"
               "<dep S[1,1] frequency>\n+0.1\n</dep>\n")
        with pytest.raises(QucsatorError, match="损坏"):
            parse_qucs_dataset(bad)
        with pytest.raises(QucsatorError, match="无法解析"):
            parse_qucs_dataset("<indep frequency 1>\n+1e9\n</indep>\n"
                               "<dep S[1,1] frequency>\n+junk\n</dep>\n")


# ── β 提取与三方内核 ─────────────────────────────────────────────────────────

class TestBetaFromS21:
    def test_short_line_direct_recovery(self):
        from rfauto.adapters.qucsator_adapter import beta_from_s21
        freqs = np.array([2.25e9, 2.5e9, 2.75e9])
        beta_true = np.array([80.0, 88.9, 97.8])
        length = 0.005  # 5mm：βL<π 无卷绕
        s21 = np.exp(-1j * beta_true * length)
        beta = beta_from_s21(freqs, s21, length)
        assert beta == pytest.approx(beta_true, rel=1e-9)

    def test_long_line_branch_selection_with_hj_ref(self):
        from rfauto.adapters.qucsator_adapter import beta_from_s21
        freqs = np.array([2.25e9, 2.5e9, 2.75e9])
        beta_true = np.array([80.0, 88.9, 97.8])
        length = 0.1    # 0.1m：βL>2π（首点卷绕）但步进 0.89<π（unwrap 前提内）
        s21 = np.exp(-1j * beta_true * length)
        no_ref = beta_from_s21(freqs, s21, length)
        assert np.all(np.abs(no_ref - beta_true) > 1.0)   # 无参照时整体差 2πk/L
        beta = beta_from_s21(freqs, s21, length, beta_branch_ref_ghz=beta_true)
        assert beta == pytest.approx(beta_true, rel=1e-9)  # HJ 参照只定分支

    def test_validation(self):
        from rfauto.adapters.qucsator_adapter import beta_from_s21
        freqs = np.array([2.25e9, 2.5e9])
        s21 = np.array([1 + 0j, 1 + 0j])
        with pytest.raises(ValueError):
            beta_from_s21(freqs, s21, 0.0)
        with pytest.raises(ValueError):
            beta_from_s21(freqs, np.array([1 + 0j]), 0.04)
        with pytest.raises(ValueError, match="零点"):
            beta_from_s21(freqs, np.array([1 + 0j, 0j]), 0.04)


class TestCompareBetaTriad:
    def test_consistent_pass_and_labels(self):
        from rfauto.adapters.qucsator_adapter import compare_beta_triad
        rep = compare_beta_triad([2.25, 2.5, 2.75],
                                 {"hj": [79.7, 88.5, 97.3],
                                  "openems": [80.6, 89.5, 98.5],
                                  "qucsator": [80.1, 88.9, 97.9]})
        assert rep.passed is True
        assert rep.max_pairwise_rel < 0.05
        assert set(rep.per_pair_max_rel) == {"hj-openems", "hj-qucsator",
                                             "openems-qucsator"}
        d = rep.to_dict()
        assert d["passed"] is True and d["n_freq"] == 3 and d["tol_rel"] == 0.05

    def test_outlier_fails_with_culprit(self):
        from rfauto.adapters.qucsator_adapter import compare_beta_triad
        rep = compare_beta_triad([2.5], {"hj": [88.5], "openems": [89.5],
                                         "qucsator": [96.5]})
        assert rep.passed is False
        assert rep.culprit_pair == "qucsator-openems" or rep.culprit_pair == "hj-qucsator"
        assert rep.worst_freq_ghz == 2.5

    def test_validation(self):
        from rfauto.adapters.qucsator_adapter import compare_beta_triad
        with pytest.raises(ValueError):
            compare_beta_triad([2.5], {"a": [1.0]})
        with pytest.raises(ValueError):
            compare_beta_triad([2.5], {"a": [1.0], "b": [1.0, 2.0]})
        with pytest.raises(ValueError):
            compare_beta_triad([], {"a": [], "b": []})
        with pytest.raises(ValueError, match="NaN"):
            compare_beta_triad([2.5], {"a": [float("nan")], "b": [1.0]})
        with pytest.raises(ValueError, match="非正"):
            compare_beta_triad([2.5], {"a": [-1.0], "b": [1.0]})


# ── HJ 腿 + 金锚（离线；与 meep 测试同源互检）────────────────────────────────

class TestHjLegAndGolden:
    def test_hj_series_vs_openems_golden_within_2pct(self):
        from rfauto.adapters.meep_adapter import hj_beta_series
        betas = hj_beta_series(1.113, list(_OPENEMS_GOLDEN), _default_stackup())
        for (f, gold), b in zip(_OPENEMS_GOLDEN.items(), betas, strict=True):
            assert abs(float(b) - gold) / gold < 0.02, (f, b, gold)

    def test_golden_table_matches_meep_test_constant(self):
        import tests.unit.test_meep_adapter as meep_tests
        assert meep_tests._OPENEMS_GOLDEN == _OPENEMS_GOLDEN

    def test_adapter_golden_accessor_returns_copy(self):
        from rfauto.adapters.qucsator_adapter import openems_golden_beta_mline
        g = openems_golden_beta_mline()
        g[2.5] = 0.0
        assert openems_golden_beta_mline()[2.5] == pytest.approx(89.50940246779182)


# ── NOT_SUPPORTED 与能力声明 ──────────────────────────────────────────────────

def _make_dummy_solver(tmp_path):
    from rfauto.adapters.em_solver_base import EMSolverConfig
    from rfauto.adapters.qucsator_adapter import QucsatorAdapter
    exe = tmp_path / "qucsator_rf.exe"
    exe.write_bytes(b"")
    if sys.platform != "win32":
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    cfg = EMSolverConfig(solver_type="qucsator", exe_path=str(exe),
                         working_dir=str(tmp_path / "run"))
    return QucsatorAdapter(cfg)


class TestNotSupported:
    def test_non_mline_template_explicit_rejection(self, tmp_path):
        solver = _make_dummy_solver(tmp_path)
        assert solver.connect()
        assert not solver.build_geometry({"template": "patch"})
        assert "NOT_SUPPORTED" in (solver._last_error or "")

    def test_unsupported_element_list_declared(self):
        from rfauto.adapters.qucsator_adapter import NOT_SUPPORTED_ELEMENTS, SUPPORTED_TEMPLATES
        for name in ("MSTEP", "MTEE", "MCROS", "MBEND", "MCOUPLED"):
            assert name in NOT_SUPPORTED_ELEMENTS
        assert SUPPORTED_TEMPLATES == ("mline",)


class TestCapabilities:
    def test_caps_truthful(self):
        from rfauto.adapters.em_solver_base import MATERIAL_MODELS
        from rfauto.adapters.qucsator_adapter import QucsatorAdapter
        caps = QucsatorAdapter.CAPABILITIES
        assert caps.solver_type == "qucsator"
        assert caps.dimension == "circuit"          # 电路级，非 2d/3d 场求解
        assert caps.supports_touchstone_export is True
        assert caps.supports_wave_port is False     # Pac 电路端口，非 EM 端口
        assert caps.supports_lumped_port is False
        assert caps.supports_nf2ff is False and caps.supports_sar is False
        assert caps.requires_license is False
        assert caps.supported_templates == ("mline",)
        assert set(caps.material_models) <= MATERIAL_MODELS
        assert "pec" not in caps.material_models    # 金属走 rho，非 PEC 边界


# ── 注册面（双树态）──────────────────────────────────────────────────────────

class TestRegistration:
    def test_no_string_key_pollution_in_current_tree_state(self):
        """hunk 未合入（无 QUCSATOR 枚举成员）→ 全局注册跳过，无字符串键污染。

        字符串键会让 r3_services.list_registered_solvers 的 stype.value 崩
        （宁缺不脏）；hunk 已合入的树态下本断言自动切换为"已注册枚举键"。
        """
        import rfauto.adapters.em_solver_base as base
        import rfauto.adapters.qucsator_adapter as mod
        has_member = hasattr(base.EMSolverType, "QUCSATOR")
        registered = mod.register_qucsator()
        assert registered is has_member
        keys = {getattr(k, "value", k) for k in base.get_global_registry().list_available()}
        if has_member:
            assert "qucsator" in keys
        else:
            assert "qucsator" not in keys
            assert all(isinstance(k, base.EMSolverType)
                       for k in base.get_global_registry().list_available())

    def test_registry_registers_into_fresh_after_hunk(self):
        """hunk 合入后语义（2026-09-25 主代理接线）：枚举成员 QUCSATOR 已在
        EMSolverType，register_qucsator 对任意注册表成功注册。"""
        import rfauto.adapters.qucsator_adapter as mod
        from rfauto.adapters.em_solver_base import EMSolverRegistry, EMSolverType
        fresh = EMSolverRegistry()
        assert mod.register_qucsator(registry=fresh) is True
        assert fresh.is_registered(EMSolverType.QUCSATOR)

    def test_enum_key_branch_registers_into_fresh_registry(self, monkeypatch):
        import rfauto.adapters.qucsator_adapter as mod
        from rfauto.adapters.em_solver_base import EMSolverRegistry

        key = object()  # 枚举成员替身（hunk 合入后为 EMSolverType.QUCSATOR）
        monkeypatch.setattr(mod, "_resolve_solver_type_key", lambda: key)
        fresh = EMSolverRegistry()
        assert mod.register_qucsator(registry=fresh) is True
        assert fresh.is_registered(key)
        solver = fresh.create(key, _make_dummy_config())
        assert isinstance(solver, mod.QucsatorAdapter)


def _make_dummy_config():
    from rfauto.adapters.em_solver_base import EMSolverConfig
    return EMSolverConfig(solver_type="qucsator")


# ── 求解链路（mock exe 产出 fixture dataset）────────────────────────────────

def _make_mock_exe(workdir, mode: str = "ok"):
    (workdir / "tpl_dataset.dat").write_text(_FIXTURE_DATASET, encoding="utf-8")
    if sys.platform == "win32":
        exe = workdir / "qucsator_rf.cmd"
        if mode == "ok":
            exe.write_text(
                "@echo off\r\ncopy /y tpl_dataset.dat qucsator_dataset.dat >nul\r\n",
                encoding="ascii")
        elif mode == "fail":
            exe.write_text("@echo off\r\nexit /b 127\r\n", encoding="ascii")
        else:
            exe.write_text("@echo off\r\nexit /b 0\r\n", encoding="ascii")
    else:
        exe = workdir / "qucsator_rf.sh"
        body = "#!/bin/sh\ncp tpl_dataset.dat qucsator_dataset.dat\n"
        if mode == "fail":
            body = "#!/bin/sh\nexit 127\n"
        elif mode == "empty":
            body = "#!/bin/sh\nexit 0\n"
        exe.write_text(body, encoding="ascii")
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe


def _make_mock_solver(tmp_path, mode: str = "ok"):
    from rfauto.adapters.em_solver_base import EMSolverConfig
    from rfauto.adapters.qucsator_adapter import QucsatorAdapter
    workdir = tmp_path / "run"
    workdir.mkdir()
    exe = _make_mock_exe(workdir, mode)
    cfg = EMSolverConfig(solver_type="qucsator", exe_path=str(exe),
                         working_dir=str(workdir), freq_range_ghz=(2.25, 2.75))
    return QucsatorAdapter(cfg), workdir


class TestSolveMock:
    def test_solve_assembles_s_matrix_products_and_reread(self, tmp_path):
        solver, workdir = _make_mock_solver(tmp_path)
        assert solver.connect()
        assert solver.build_geometry({"freqs_ghz": [2.25, 2.5, 2.75]})
        result = solver.solve()
        assert result.success, result.message
        assert result.freq_ghz.tolist() == pytest.approx([2.25, 2.5, 2.75])
        s = result.s_params
        assert s.shape == (3, 2, 2)
        assert s[0, 1, 0] == pytest.approx(complex(-0.987682755298038839165,
                                                   2.70677423720884317848e-02))
        fd = result.field_data
        # β 由 fixture S21 相位提取（L=40mm）：unwrap 后 -angle/L，HJ 只定分支
        beta = fd["beta_rad_per_m"]
        assert beta[1] == pytest.approx(88.0, rel=2e-2)
        assert all(1.0 < e < 3.66 for e in fd["epsilon_eff"])
        # 同构产物齐备 + get_sparams/get_beta 重读一致
        for name in ("qucsator_sparams.csv", "qucsator_port_beta.csv",
                     "qucsator_mline.s2p", "qucsator_dataset.dat"):
            assert (workdir / name).is_file(), name
        freq_g, s2 = solver.get_sparams()
        assert freq_g.tolist() == pytest.approx([2.25, 2.5, 2.75])
        assert s2[0, 1, 0] == pytest.approx(s[0, 1, 0])
        bf, bb = solver.get_beta()
        assert bf.tolist() == pytest.approx([2.25, 2.5, 2.75])
        assert bb.tolist() == pytest.approx(beta.tolist())

    def test_solve_without_connection_or_netlist_fails_cleanly(self, tmp_path):
        solver, _wd = _make_mock_solver(tmp_path)
        assert not solver.solve().success            # 未连接
        solver.connect()
        assert not solver.solve().success            # 未 build_geometry
        # 独立实例再验 build→solve 全链
        (tmp_path / "b").mkdir()
        solver2, _wd2 = _make_mock_solver(tmp_path / "b")
        assert solver2.connect()
        assert solver2.build_geometry({"freqs_ghz": [2.25, 2.5, 2.75]})
        assert solver2.solve().success

    def test_nonzero_exit_fails_with_message(self, tmp_path):
        solver, _wd = _make_mock_solver(tmp_path, mode="fail")
        solver.connect()
        solver.build_geometry({"freqs_ghz": [2.25, 2.5, 2.75]})
        result = solver.solve()
        assert not result.success
        assert "运行失败" in result.message or "退出码" in result.message

    def test_zero_exit_without_dataset_fails_cleanly(self, tmp_path):
        solver, _wd = _make_mock_solver(tmp_path, mode="empty")
        solver.connect()
        solver.build_geometry({"freqs_ghz": [2.25, 2.5, 2.75]})
        result = solver.solve()
        assert not result.success
        assert "运行失败" in result.message


# ── 真机通道（qucsator_rf 已装；缺席环境如实 skip）───────────────────────────

def _real_available() -> bool:
    from rfauto.adapters.qucsator_adapter import qucsator_available
    return qucsator_available()


@pytest.mark.skipif(not _real_available(), reason="qucsator_rf 不可用（真机通道）")
class TestRealEngine:
    def test_threeway_mline_nominal_within_tol(self, tmp_path):
        """判据 4a：qucsator vs openEMS 金锚 vs HJ，互差 ≤0.05（Meep 先例口径）。"""
        from rfauto.adapters.em_solver_base import EMSolverConfig
        from rfauto.adapters.meep_adapter import hj_beta_series
        from rfauto.adapters.qucsator_adapter import (
            _OPENEMS_GOLDEN_MLINE,
            QucsatorAdapter,
            compare_beta_triad,
        )
        workdir = tmp_path / "run"
        cfg = EMSolverConfig(solver_type="qucsator", working_dir=str(workdir))
        solver = QucsatorAdapter(cfg)
        assert solver.connect()
        assert solver.build_geometry({"freqs_ghz": [2.25, 2.5, 2.75]})
        result = solver.solve()
        assert result.success, result.message
        freqs = [float(f) for f in result.freq_ghz]
        beta_q = result.field_data["beta_rad_per_m"]
        beta_hj = hj_beta_series(1.113, freqs, _default_stackup())
        ems = [_OPENEMS_GOLDEN_MLINE[f] for f in freqs]
        rep = compare_beta_triad(freqs, {"hj": beta_hj, "openems": ems,
                                         "qucsator": beta_q}, tol_rel=0.05)
        assert rep.passed, rep.to_dict()
        # 侧证：近匹配线 |S21|≈1、εeff∈(1, er)
        assert abs(result.s_params[1, 1, 0]) > 0.9
        assert np.all((result.field_data["epsilon_eff"] > 1.0)
                      & (result.field_data["epsilon_eff"] < 3.66))

    def test_deterministic_rerun_byte_identical(self, tmp_path):
        """判据 4b：同网表两次运行 dataset 逐字节相同（真机标定口径）。"""
        from rfauto.adapters.em_solver_base import EMSolverConfig
        from rfauto.adapters.qucsator_adapter import QucsatorAdapter
        texts = []
        for i in (1, 2):
            cfg = EMSolverConfig(solver_type="qucsator",
                                 working_dir=str(tmp_path / f"run{i}"))
            solver = QucsatorAdapter(cfg)
            assert solver.connect()
            assert solver.build_geometry({"freqs_ghz": [2.25, 2.5, 2.75]})
            res = solver.solve()
            assert res.success
            texts.append((tmp_path / f"run{i}" / "qucsator_dataset.dat").read_bytes())
        assert texts[0] == texts[1]

    def test_not_supported_template_end_to_end(self, tmp_path):
        """判据 4c：真机链上非 mline 模板仍显式 NOT_SUPPORTED，不静默。"""
        from rfauto.adapters.em_solver_base import EMSolverConfig
        from rfauto.adapters.qucsator_adapter import QucsatorAdapter
        cfg = EMSolverConfig(solver_type="qucsator", working_dir=str(tmp_path / "run"))
        solver = QucsatorAdapter(cfg)
        assert solver.connect()
        assert not solver.build_geometry({"template": "wilkinson"})
        assert "NOT_SUPPORTED" in (solver._last_error or "")

    def test_service_three_way_json(self, tmp_path):
        """service 薄壳 JSON 进出 + 判据 4a 通过 + 口径差单独成账。"""
        from rfauto.service.qucsator_service import solve_mline_three_way
        out = solve_mline_three_way(freqs_ghz=[2.25, 2.5, 2.75],
                                    work_dir=str(tmp_path / "svc"))
        assert out["ok"], out.get("errors")
        tw = out["threeway"]
        assert tw["verdict"]["passed"] is True
        assert tw["verdict"]["max_pairwise_rel"] <= 0.05
        assert any("qucsator" in k for k in tw["verdict"]["per_pair_max_rel"])
        assert "口径差" in tw["kj_vs_hj_note"]
        # KJ−HJ 口径差如实分账（色散项，2.5GHz·0.5mm 量级下为小量但非零）
        assert tw["verdict"]["kj_vs_hj_rel"] is not None
