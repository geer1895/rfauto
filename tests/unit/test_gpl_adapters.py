"""SV-1/SV-2：scuff-em / PyPO GPL 隔离适配器单元测试（全离线面）。

fail-closed 许可门（任务书 SV-1 原文"license/许可边界写死 fail-closed"）：

1. 门语义：缺省拒绝；只认 1/true/yes/on（大小写不敏感）；单工具 env
   优先级高于全局；任何其余值（0/false/空/拼写错）=拒绝——不猜意图；
2. scuff 通道：connect 前置门（拒绝时 LicenseRefusedError 含 remedy 与
   环境变量名）；opt-in 后 exe 解析链（env → PATH）；scuffgeo/freqfile
   文本生成（确定性 + 校验）；scuff-scatter 命令行构造；
   parse_sparam_pairs 待证档 fail-closed（合法 fixture 往返 + 列数/
   端口号/残块全拒）；
3. pypo 通道：门 + 可选依赖双门（缺包显式报错指路 extras pypo）；
   parabolic_reflector_config 校验（边缘角闭式 θ_e=2·atan(D/4f)）；
4. 闭式互证裁判（SV-2 验收我方锚，解析锚）：Ruze σ=0 → η=1、单调降、
   σ=λ/4π → η=e^{-1}；均匀口径增益 D=10λ、η=1 → (10π)² → 10log10 ≈
   24.99 dBi；η 反解带判定 in_band；
5. 注册表：import rfauto.adapters.gpl → 全局注册表含 "scuff"/"pypo"
   自定义字符串键（EMSolverConfig 自定义类型通道）；能力声明被
   solver_capabilities 消费契约（capabilities() 类型+键名一致）；
   全局注册表快照还原（不外泄本文件注册副作用）。

真机面（scuff-scatter/Pypy 真跑）= env 显式意图门 opt-in（本机未装，
skipif 生效验证）。铁律 7：闭式裁判=解析公式独立锚（#118）。
"""

from __future__ import annotations

import itertools
import math
from typing import TYPE_CHECKING

import pytest

from rfauto.adapters.em_solver_base import (
    EMSolverConfig,
    SolverCapabilities,
    get_global_registry,
)

if TYPE_CHECKING:  # ruff F821 面：符号由 _lazy_gpl_names fixture 注入
    from rfauto.adapters.gpl.license_gate import (
        ALLOW_ENV,
        LicenseRefusedError,
        gpl_gate_decision,
    )
    from rfauto.adapters.gpl.pypo_adapter import (
        PypoAdapter,
        aperture_efficiency_band,
        parabolic_reflector_config,
        pypo_importable,
        ruze_surface_efficiency,
        uniform_aperture_gain_db,
    )
    from rfauto.adapters.gpl.scuff_adapter import (
        SCUFF_ENV_VAR,
        ScuffAdapter,
        build_scatter_command,
        parse_sparam_pairs,
        resolve_scuff_exe,
        write_freq_file,
        write_scuffgeo,
    )


@pytest.fixture(autouse=True)
def _restore_global_registry():
    """全局注册表快照还原（#362② 同族治理）。

    本文件**全部 gpl 导入走函数级惰性**（含 license_gate——子模块导入
    会先执行包 __init__，而 __init__ 导入即注册两通道）。pytest-randomly
    随机排序下，模块级导入的注册副作用可能先于
    test_adapters_registry_completeness 的 stray 键断言执行（#221②
    家族的测试序变体）。首个惰性导入落在本 fixture 保护的用例窗口内，
    之后模块缓存命中零重复注册——会话零外泄。"""
    reg = get_global_registry()
    snapshot = dict(reg._solvers)
    yield
    reg._solvers.clear()
    reg._solvers.update(snapshot)


def _register_into_global() -> None:
    """用例内触发 import-time 同款注册（gpl/__init__ 模块级调用同路径）。"""
    from rfauto.adapters.gpl.pypo_adapter import register_pypo
    from rfauto.adapters.gpl.scuff_adapter import register_scuff

    register_scuff()
    register_pypo()


#: 用例引用的 gpl 符号按子模块分组（fixture 首跑时注入模块 globals——
#: 惰性导入落受保护窗口，之后模块缓存命中零重复注册）


@pytest.fixture(autouse=True)
def _lazy_gpl_names(_restore_global_registry):
    """首个用例前把 gpl 符号注入本模块 globals（模块级导入会经包
    __init__ 触发注册，pytest-randomly 随机排序下可能外泄到
    test_adapters_registry_completeness 的 stray 键断言——#221② 家族
    的测试序变体；惰性后首个导入落在 _restore_global_registry 保护的
    窗口内——参数显式依赖保证快照先于导入）。"""
    import importlib

    for sub, names in (
        ("license_gate", ("ALLOW_ENV", "LicenseRefusedError",
                          "gpl_gate_decision")),
        ("scuff_adapter", ("SCUFF_ENV_VAR", "ScuffAdapter",
                           "build_scatter_command", "parse_sparam_pairs",
                           "resolve_scuff_exe", "write_freq_file",
                           "write_scuffgeo")),
        ("pypo_adapter", ("PypoAdapter", "aperture_efficiency_band",
                          "parabolic_reflector_config", "pypo_importable",
                          "ruze_surface_efficiency",
                          "uniform_aperture_gain_db")),
    ):
        mod = importlib.import_module(f"rfauto.adapters.gpl.{sub}")
        for name in names:
            globals().setdefault(name, getattr(mod, name))


class TestLicenseGate:
    def test_default_refused(self):
        allowed, reason = gpl_gate_decision("scuff", environ={})
        assert allowed is False
        assert "RFAUTO_ALLOW_SCUFF" in reason

    def test_unknown_tool_refused(self):
        allowed, reason = gpl_gate_decision("cst", environ={})
        assert allowed is False
        assert "fail-closed" in reason

    @pytest.mark.parametrize("token", ["1", "true", "TRUE", "Yes", "on"])
    def test_true_tokens_pass(self, token):
        per_tool, _ = gpl_gate_decision(
            "pypo", environ={"RFAUTO_ALLOW_PYPO": token})
        assert per_tool is True
        glob, _ = gpl_gate_decision("scuff", environ={ALLOW_ENV: token})
        assert glob is True

    @pytest.mark.parametrize("token", ["0", "false", "", "ok", "1.0"])
    def test_non_true_tokens_refused(self, token):
        allowed, _ = gpl_gate_decision(
            "scuff", environ={"RFAUTO_ALLOW_SCUFF": token})
        assert allowed is False

    def test_per_tool_overrides_global_refusal(self):
        allowed, reason = gpl_gate_decision("pypo", environ={
            ALLOW_ENV: "1", "RFAUTO_ALLOW_PYPO": "0"})
        assert allowed is False  # 单工具显式拒绝压过全局放行
        assert "RFAUTO_ALLOW_PYPO" in reason


class TestScuffChannel:
    def test_global_registry_key(self):
        _register_into_global()
        reg = get_global_registry()
        assert reg.lookup("scuff") is ScuffAdapter

    def test_capabilities_declared(self):
        adapter = ScuffAdapter(EMSolverConfig(solver_type="scuff"))
        caps = adapter.capabilities()
        assert isinstance(caps, SolverCapabilities)
        assert caps.solver_type == "scuff"
        assert caps.requires_license is False

    def test_connect_refused_without_optin(self):
        adapter = ScuffAdapter(EMSolverConfig(solver_type="scuff"))
        with pytest.raises(LicenseRefusedError, match="fail-closed"):
            adapter.connect()

    def test_exe_resolution_chain(self, monkeypatch):
        monkeypatch.delenv(SCUFF_ENV_VAR, raising=False)
        assert resolve_scuff_exe(environ={}) is None
        # env 指向不存在路径 → 忽略继续 which → 无引擎 → None
        assert resolve_scuff_exe(
            environ={SCUFF_ENV_VAR: "/no/such/scuff"}) is None

    def test_scuffgeo_and_freq_generation(self, tmp_path):
        geo = write_scuffgeo(tmp_path / "a.scuffgeo", [
            {"name": "plate", "mesh_file": "mesh/plate.msh"}])
        text = geo.read_text(encoding="utf-8")
        assert "SURFACE plate" in text and "MESHFILE mesh/plate.msh" in text
        assert "ENDSURFACE" in text
        freq = write_freq_file(tmp_path / "f.dat", (1.0, 3.0, 5))
        lines = freq.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 5
        assert lines[0].split()[0] == "1.0"
        assert lines[-1].split()[0] == "3.0"
        with pytest.raises(ValueError, match="surfaces"):
            write_scuffgeo(tmp_path / "bad.scuffgeo", [])
        with pytest.raises(ValueError, match="扫频参数"):
            write_freq_file(tmp_path / "bad.freq", (3.0, 1.0, 5))

    def test_command_construction(self, tmp_path):
        cmd = build_scatter_command(
            "scuff-scatter", tmp_path / "g.scuffgeo",
            tmp_path / "f.dat", tmp_path)
        assert cmd[0] == "scuff-scatter"
        assert "--FOM" in cmd and "SParams" in cmd
        assert "--geometry" in cmd and "--freqfile" in cmd

    def test_sparams_parser_roundtrip(self):
        n_ports = 2
        fixture = (
            "# kPort kPort' Re{S} Im{S}\n"
            "1 1 0.5 -0.1\n1 2 0.3 0.2\n2 1 0.3 -0.2\n2 2 0.5 0.1\n"
            "1 1 0.4 0.0\n1 2 0.25 0.1\n2 1 0.25 -0.1\n2 2 0.4 0.0\n")
        s = parse_sparam_pairs(fixture, n_ports)
        assert s.shape == (2, 2, 2)
        assert s[0, 0, 0] == complex(0.5, -0.1)
        assert s[0, 0, 1] == complex(0.3, 0.2)
        assert s[1, 0, 1] == complex(0.25, 0.1)
        assert s[1, 1, 0] == complex(0.25, -0.1)
        assert s[1, 1, 1] == complex(0.4, 0.0)

    @pytest.mark.parametrize("bad", [
        "1 1 0.5\n",                      # 列数不对
        "1 3 0.5 0.0\n",                  # 端口号越界
        "1 1 abc 0.0\n",                  # 非数值
        "1 1 0.5 0.0\n1 2 0.1 0.0\n",     # 残块（不足 n_ports² 行）
    ])
    def test_sparams_parser_fail_closed(self, bad):
        with pytest.raises(ValueError):
            parse_sparam_pairs(bad, 2)

    def test_real_engine_optin_smoke_skipped(self, tmp_path, monkeypatch):
        """真机冒烟=env 显式意图门（引擎未装 → skipif 生效验证）。"""
        if resolve_scuff_exe() is None:
            pytest.skip("scuff-em 未安装（真机 opt-in 面；离线门/解析面"
                        "已由本文件其余用例覆盖）")
        monkeypatch.setenv("RFAUTO_ALLOW_SCUFF", "1")
        adapter = ScuffAdapter(EMSolverConfig(
            solver_type="scuff", working_dir=str(tmp_path)))
        assert adapter.connect() is True


class TestPypoChannel:
    def test_global_registry_key(self):
        _register_into_global()
        reg = get_global_registry()
        assert reg.lookup("pypo") is PypoAdapter

    def test_config_edge_angle_closed_form(self):
        cfg = parabolic_reflector_config(
            diameter_m=2.0, focal_length_m=0.8,
            freq_ghz=(10.0, 12.0, 21))
        theta = 2.0 * math.atan(2.0 / (4.0 * 0.8))
        assert cfg["edge_angle_rad"] == pytest.approx(theta)
        assert cfg["freq_ghz"] == (10.0, 12.0, 21)
        with pytest.raises(ValueError, match="edge_taper"):
            parabolic_reflector_config(
                diameter_m=1.0, focal_length_m=0.5,
                freq_ghz=(10.0, 10.0, 1), edge_taper_db=3.0)
        with pytest.raises(ValueError, match="频栅非法"):
            parabolic_reflector_config(
                diameter_m=1.0, focal_length_m=0.5, freq_ghz=(12.0, 10.0, 3))

    def test_connect_requires_package_and_optin(self, monkeypatch):
        adapter = PypoAdapter(EMSolverConfig(solver_type="pypo"))
        # 缺省：许可门拒绝
        with pytest.raises(LicenseRefusedError):
            adapter.connect()
        # 许可门过、包缺：双门第二道显式报错指路 extras
        monkeypatch.setenv("RFAUTO_ALLOW_PYPO", "1")
        if pypo_importable():
            assert adapter.connect() is True
        else:
            with pytest.raises(RuntimeError, match=r"rfauto\[pypo\]"):
                adapter.connect()
        # solve 的 fail 路径（门/依赖任一不过 → success=False 不裸抛）
        result = PypoAdapter(EMSolverConfig(solver_type="pypo")).solve()
        assert result.success is False
        assert "pypopy" in result.message or "许可" in result.message

    def test_ruze_closed_form(self):
        assert ruze_surface_efficiency(0.0, 1.0) == 1.0
        assert ruze_surface_efficiency(1.0 / (4.0 * math.pi), 1.0) == \
            pytest.approx(math.exp(-1.0))
        vals = [ruze_surface_efficiency(s / 100.0, 1.0) for s in range(50)]
        assert all(a >= b for a, b in itertools.pairwise(vals))
        with pytest.raises(ValueError):
            ruze_surface_efficiency(-0.1, 1.0)

    def test_uniform_aperture_gain_anchor(self):
        # D=10λ、η=1 → G=(10π)² → 10·log10 ≈ 24.99 dBi（解析锚）
        assert uniform_aperture_gain_db(10.0, 1.0, 1.0) == pytest.approx(
            10.0 * math.log10((10.0 * math.pi) ** 2), rel=1e-12)
        assert uniform_aperture_gain_db(10.0, 1.0, 0.5) == pytest.approx(
            uniform_aperture_gain_db(10.0, 1.0, 1.0) - 10.0 * math.log10(2.0))

    def test_aperture_efficiency_band(self):
        verdict = aperture_efficiency_band(
            uniform_aperture_gain_db(10.0, 1.0, 0.55), 10.0, 1.0)
        assert verdict["in_band"] is True
        assert verdict["eta_measured"] == pytest.approx(0.55, rel=1e-9)
        low = aperture_efficiency_band(0.0, 10.0, 1.0)   # η_meas≈0
        assert low["in_band"] is False

    def test_get_sparams_rejected_honest(self):
        adapter = PypoAdapter(EMSolverConfig(solver_type="pypo"))
        with pytest.raises(RuntimeError, match="S 参数"):
            adapter.get_sparams()
