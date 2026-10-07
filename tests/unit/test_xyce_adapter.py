"""F-L.2 xyce_adapter 离线单测（全 mock/fixture，零 WSL 依赖——#139 纪律）。

钉面：
- exe 解析链（显式 > RFAUTO_XYCE_EXE > 缺省；verify 不可达显式报错指引
  tools/xyce_stack_build.sh；version best-effort）；
- WSL 桥工具（windows_to_wsl_path 盘符护栏 df5 E-MED-6、decode_wsl_bytes
  UTF-16LE #271 口径、run_xyce 命令形态/超时面）；
- 网表渲染（rlc_lowpass AC 锚逐 token 钉 + tran/dc 结构钉 + 校验拒绝）；
- prn 解析器（真机 7.11 fixture：AC 复数 Re/Im 双列、tran/dc 实数单列、
  footer 跳过、坏文件显式报错 #316 方向）；
- 适配器生命周期（connect/build_geometry/solve 全链 mock run_xyce；
  solve 产物=电压传函非 S 参数的诚实口径）；
- 注册面（EMSolverType.XYCE + 全局/新注册表 + 能力声明如实）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

# WSL 桥（盘符→/mnt、wsl.exe 发射）是 Windows 侧功能：POSIX 上 Path 对
# 盘符串/POSIX tmp 目录无盘符语义（parts[0] 非盘符段），桥护栏按设计拒绝
# ——诚实跳过（skip-not-fail；Linux 侧 Xyce 原生接入属新适配器范畴）。
_WSL_BRIDGE = os.name == "nt"
_SKIP_NON_NT = pytest.mark.skipif(
    not _WSL_BRIDGE,
    reason="WSL 桥为 Windows 侧功能（盘符/wsl.exe 语义 POSIX 不成立）")

import rfauto.adapters.xyce_adapter as mod
from rfauto.adapters.xyce_adapter import (
    DEFAULT_WSL_DISTRO,
    DEFAULT_XYCE_WSL_EXE,
    RLC_ANCHOR_DEFAULTS,
    XyceAdapter,
    XyceError,
    XyceRunResult,
    decode_wsl_bytes,
    parse_prn,
    prn_path_for,
    read_prn,
    render_divider_dc_netlist,
    render_netlist,
    render_rc_tran_netlist,
    render_rlc_ac_netlist,
    resolve_xyce_exe,
    rlc_lowpass_transfer,
    run_xyce,
    verify_xyce_reachable,
    windows_to_wsl_path,
    xyce_version,
)

# ── 真机 fixture（2026-09-29 Xyce 7.11 probe 实测文本，10 点缩样）───────────

_AC_PRN_FIXTURE = """Index       FREQ            Re(V(3))          Im(V(3))
0        1.00000000e+03    1.00392354e+00   -6.33283869e-03
1        2.15443469e+03    1.01847264e+00   -1.40441193e-02
2        4.64158883e+03    1.09185094e+00   -3.48028068e-02
3        1.00000000e+04    1.63468446e+00   -1.69708474e-01
4        2.15443469e+04   -1.17035869e+00   -1.90320970e-01
5        4.64158883e+04   -1.33037111e-01   -5.16948634e-03
6        1.00000000e+05   -2.59816670e-02   -4.24257644e-04
7        2.15443469e+05   -5.48688905e-03   -4.07558091e-05
8        4.64158883e+05   -1.17709828e-03   -4.04089069e-06
9        1.00000000e+06   -2.53366496e-04   -4.03347471e-07
End of Xyce(TM) Simulation
"""

_TRAN_PRN_FIXTURE = """Index       TIME              V(2)
0        0.00000000e+00    0.00000000e+00
1        5.00000000e-09    0.00000000e+00
2        1.50000000e-08    0.00000000e+00
3        3.50000000e-08    0.00000000e+00
4        1.00000000e-05    9.99918764e-01
End of Xyce(TM) Simulation
"""

_DC_PRN_FIXTURE = """Index       V(2)
0        0.00000000e+00
1        5.00000000e-01
2        1.00000000e+00
3        1.50000000e+00
4        5.00000000e+00
End of Xyce(TM) Simulation
"""


def _proc(rc: int = 0, stdout: bytes = b"", stderr: bytes = b""):
    return subprocess.CompletedProcess([], rc, stdout, stderr)


# ── exe 解析链 ────────────────────────────────────────────────────────────────

class TestResolveExe:
    def test_default_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("RFAUTO_XYCE_EXE", raising=False)
        spec = resolve_xyce_exe()
        assert spec.wsl_path == DEFAULT_XYCE_WSL_EXE
        assert spec.distro == DEFAULT_WSL_DISTRO

    def test_env_override_and_explicit_wins(self, monkeypatch):
        monkeypatch.setenv("RFAUTO_XYCE_EXE", "/opt/xyce/bin/Xyce")
        assert resolve_xyce_exe().wsl_path == "/opt/xyce/bin/Xyce"
        assert resolve_xyce_exe("/usr/local/bin/Xyce").wsl_path == "/usr/local/bin/Xyce"

    def test_distro_param(self, monkeypatch):
        monkeypatch.delenv("RFAUTO_XYCE_EXE", raising=False)
        assert resolve_xyce_exe(distro="rfauto-ubuntu").distro == "rfauto-ubuntu"

    def test_blank_env_falls_to_default_blank_explicit_rejected(
        self, monkeypatch
    ):
        monkeypatch.setenv("RFAUTO_XYCE_EXE", "   ")
        assert resolve_xyce_exe().wsl_path == DEFAULT_XYCE_WSL_EXE
        with pytest.raises(XyceError, match="空白"):
            resolve_xyce_exe("  ")


class TestVerifyReachable:
    def test_reachable_returns_spec(self, monkeypatch):
        calls = []

        def fake_runner(argv, timeout_s):
            calls.append(argv)
            return _proc(0)

        spec = verify_xyce_reachable(runner=fake_runner)
        assert spec.wsl_path == DEFAULT_XYCE_WSL_EXE
        assert calls and calls[0][0] == "wsl.exe" and "test -x" in calls[0][-1]

    def test_unreachable_raises_with_build_hint(self):
        def fail_runner(argv, timeout_s):
            return _proc(1)

        with pytest.raises(FileNotFoundError) as ei:
            verify_xyce_reachable(runner=fail_runner)
        msg = str(ei.value)
        assert "RFAUTO_XYCE_EXE" in msg and "tools/xyce_stack_build.sh" in msg

    def test_version_best_effort_never_raises(self):
        def boom(argv, timeout_s):
            raise OSError("wsl down")

        assert xyce_version(runner=boom) is None

    def test_version_parses(self):
        out = b"Xyce DEVELOPMENT-202609290042-(UNKNOWN)-opensource\n"
        assert xyce_version(runner=lambda a, t: _proc(0, stdout=out)) == (
            "Xyce DEVELOPMENT-202609290042-(UNKNOWN)-opensource"
        )


# ── WSL 桥工具 ────────────────────────────────────────────────────────────────

class TestBridgeUtils:
    @_SKIP_NON_NT
    def test_windows_to_wsl_path(self):
        assert windows_to_wsl_path("E:\\a\\b.cir") == "/mnt/e/a/b.cir"
        assert windows_to_wsl_path("E:/") == "/mnt/e"

    def test_windows_to_wsl_path_rejects_non_drive(self):
        for bad in ("relative/dir", "/home/pc/x", "\\\\srv\\share", ""):
            with pytest.raises(ValueError):
                windows_to_wsl_path(bad)

    def test_decode_utf8_plain(self):
        assert decode_wsl_bytes(b"hello\n") == "hello\n"

    def test_decode_utf16le_with_bom(self):
        assert decode_wsl_bytes("héllo\n".encode("utf-16-le")) == "héllo\n"

    def test_decode_utf16le_nul_stripped(self):
        raw = "ok\r\n".encode("utf-16-le")
        assert decode_wsl_bytes(raw) == "ok\r\n"
        assert decode_wsl_bytes(b"") == ""


class TestRunXyce:
    @_SKIP_NON_NT
    def test_command_shape_and_quoting(self, tmp_path):
        cir = tmp_path / "x.cir"
        cir.write_bytes(b"* t\n.end\n")
        seen = {}

        def fake_runner(argv, timeout_s):
            seen["argv"] = argv
            return _proc(0, stdout=b"out", stderr=b"err")

        res = run_xyce(cir, timeout_s=10.0, extra_args=("-r", "x.raw"),
                       runner=fake_runner)
        argv = seen["argv"]
        assert argv[:5] == ["wsl.exe", "-d", DEFAULT_WSL_DISTRO, "--exec", "bash"]
        script = argv[-1]
        assert script.startswith("cd /mnt/") and cir.name in script
        assert "-r x.raw" in script
        assert res.rc == 0 and res.stdout == "out" and res.stderr == "err"
        assert res.netlist_path == cir and not res.timed_out

    def test_missing_netlist_raises(self, tmp_path):
        with pytest.raises(XyceError, match="网表不存在"):
            run_xyce(tmp_path / "nope.cir", runner=lambda a, t: _proc(0))

    @_SKIP_NON_NT
    def test_timeout_returns_flagged_result(self, tmp_path):
        cir = tmp_path / "x.cir"
        cir.write_bytes(b".end\n")

        def slow_runner(argv, timeout_s):
            raise subprocess.TimeoutExpired(cmd=argv, timeout=timeout_s)

        res = run_xyce(cir, runner=slow_runner)
        assert res.timed_out and res.rc == -1

    @_SKIP_NON_NT
    def test_utf16_output_decoded(self, tmp_path):
        cir = tmp_path / "x.cir"
        cir.write_bytes(b".end\n")
        res = run_xyce(
            cir, runner=lambda a, t: _proc(0, stdout="完成\n".encode("utf-16-le")),
        )
        assert res.stdout == "完成\n"


# ── 网表渲染 ──────────────────────────────────────────────────────────────────

class TestRender:
    def test_ac_anchor_tokens_calibrated(self):
        text = render_rlc_ac_netlist(10.0, 1e-3, 1e-7)
        lines = text.splitlines()
        assert lines[0] == "* rfauto F-L.2 Xyce rlc_lowpass ac anchor"
        assert "V1 1 0 AC 1" in lines
        assert "R1 1 2 10" in lines
        assert "L1 2 3 0.001" in lines
        assert "C1 3 0 9.9999999999999995e-08" in lines
        assert ".AC dec 49 1000 1000000" in lines
        assert ".print ac v(3)" in lines
        assert lines[-1] == ".end"
        assert "\r" not in text and text.endswith(".end\n")

    def test_ac_render_deterministic(self):
        assert (render_rlc_ac_netlist(10.0, 1e-3, 1e-7)
                == render_rlc_ac_netlist(10.0, 1e-3, 1e-7))

    def test_ac_validation_rejects_bad_inputs(self):
        with pytest.raises(ValueError):
            render_rlc_ac_netlist(0.0, 1e-3, 1e-7)
        with pytest.raises(ValueError):
            render_rlc_ac_netlist(10.0, -1e-3, 1e-7)
        with pytest.raises(ValueError):
            render_rlc_ac_netlist(10.0, 1e-3, 0.0)
        with pytest.raises(ValueError):
            render_rlc_ac_netlist(10.0, 1e-3, 1e-7, fstart_hz=1e6, fstop_hz=1e3)
        with pytest.raises(ValueError):
            render_rlc_ac_netlist(10.0, 1e-3, 1e-7, points_per_decade=0)

    def test_tran_structural_pins(self):
        text = render_rc_tran_netlist()
        assert "PWL(0 0 9.9999999999999986e-10 0 1.9999999999999997e-09 1 " in text
        assert "R1 1 2 1000" in text
        assert "C1 2 0 1.0000000000000001e-09" in text
        assert ".tran 9.9999999999999995e-08 1.0000000000000001e-05" in text
        assert ".print tran v(2)" in text

    def test_dc_structural_pins(self):
        text = render_divider_dc_netlist()
        assert ".DC V1 0 10 1" in text
        assert "R1 1 2 1000" in text
        assert "R2 2 0 1000" in text
        assert ".print dc v(2)" in text

    def test_non_ascii_title_rejected_at_encode_boundary(self):
        text = render_netlist(title="中文标题", element_lines=["R1 1 0 1"],
                              analysis_lines=[".DC V1 0 1 1"],
                              print_lines=[".print dc v(1)"])
        with pytest.raises(UnicodeEncodeError):
            text.encode("ascii")

    def test_transfer_closed_form_reference_points(self):
        # 手推锚点：f0=ω0/2π=15915.494…Hz（ω0=1/√(LC)=1e5 rad/s）处 |H|=Q=10
        # 且相移 -90°；带外 1MHz 处 |H|≈1/(ω²LC)=2.5337e-4（-71.93dB）。
        f0 = 1e5 / (2.0 * np.pi)
        h = rlc_lowpass_transfer(np.array([1e3, f0, 1e6]), **RLC_ANCHOR_DEFAULTS)
        assert h[0] == pytest.approx(1.003923540879982 - 0.00633283868661794j)
        assert abs(h[1]) == pytest.approx(10.0, rel=1e-12)
        assert np.degrees(np.angle(h[1])) == pytest.approx(-90.0)
        assert abs(h[2]) == pytest.approx(2.533668166963305e-4, rel=1e-6)


# ── prn 解析器 ────────────────────────────────────────────────────────────────

class TestParsePrn:
    def test_ac_complex_columns_fixture(self):
        out = parse_prn(_AC_PRN_FIXTURE)
        assert out["indep"] == "FREQ"
        assert out["vars"] == ["V(3)"]
        assert len(out["index"]) == 10
        assert out["data"]["FREQ"][0].real == pytest.approx(1e3)
        assert out["data"]["FREQ"][-1].real == pytest.approx(1e6)
        assert out["data"]["V(3)"][0] == pytest.approx(1.00392354 - 6.33283869e-3j)
        assert out["data"]["V(3)"][9] == pytest.approx(
            -2.53366496e-4 - 4.03347471e-7j)

    def test_tran_real_column_fixture(self):
        out = parse_prn(_TRAN_PRN_FIXTURE)
        assert out["indep"] == "TIME"
        assert out["vars"] == ["V(2)"]
        assert out["data"]["V(2)"][-1].real == pytest.approx(9.99918764e-1)
        assert np.all(out["data"]["V(2)"].imag == 0.0)

    def test_dc_no_indep_fixture(self):
        out = parse_prn(_DC_PRN_FIXTURE)
        assert out["indep"] is None
        assert out["vars"] == ["V(2)"]
        assert out["data"]["V(2)"][4].real == pytest.approx(5.0)

    def test_footer_and_blank_lines_skipped(self):
        text = "Index FREQ Re(V(1)) Im(V(1))\n\n0 1.0 1.0 0.0\n\nEnd of Xyce(TM) Simulation\n"
        out = parse_prn(text)
        assert len(out["index"]) == 1
        assert out["data"]["V(1)"][0] == 1.0 + 0j

    @pytest.mark.parametrize("bad", [
        "",                      # 空文件
        "NoIndex FREQ\n0 1 2\n",  # 表头首列非 Index
        "Index FREQ Re(V(1))\n0 1.0 1.0\n",  # Re 缺 Im 配对
        "Index Im(V(1))\n0 1.0\n",           # Im 缺前导 Re
        "Index FREQ Re(V(1)) Im(V(1))\n0 1.0 1.0\n",      # 行列数不足
        "Index FREQ Re(V(1)) Im(V(1))\n0 1.0 x 2.0\n",    # 非数值令牌
        "Index FREQ Re(V(1)) Im(V(1))\n",                 # 无数据行
    ])
    def test_corrupt_inputs_raise(self, bad):
        with pytest.raises(XyceError):
            parse_prn(bad)

    def test_read_prn_file_entry(self, tmp_path):
        p = tmp_path / "a.cir.FD.prn"
        p.write_text(_AC_PRN_FIXTURE, encoding="ascii")
        assert len(read_prn(p)["index"]) == 10

    def test_duplicate_column_names_raise(self):
        """P3-6③：重复列名显式报错（cols.index 首列命中的静默别名禁绝，
        #316 多报方向）——实数双列与复数对重复两形态。"""
        with pytest.raises(XyceError, match="重复列名"):
            parse_prn("Index FREQ V(1) V(1)\n0 1.0 1.0 2.0\n")
        with pytest.raises(XyceError, match="重复列名"):
            parse_prn(
                "Index FREQ Re(V(1)) Im(V(1)) Re(V(1)) Im(V(1))\n"
                "0 1.0 1.0 1.0 2.0 2.0\n"
            )
        with pytest.raises(XyceError, match="重复列名"):
            parse_prn("Index FREQ V(1) Re(V(1)) Im(V(1))\n0 1.0 1.0 1.0\n")

    def test_prn_path_for_naming_calibrated(self):
        assert prn_path_for(Path("d/x.cir"), ac=True).name == "x.cir.FD.prn"
        assert prn_path_for(Path("d/x.cir"), ac=False).name == "x.cir.prn"


# ── 适配器生命周期（mock run_xyce 边界）──────────────────────────────────────

def _make_solver(tmp_path: Path, **extra) -> XyceAdapter:
    from rfauto.adapters.em_solver_base import EMSolverConfig
    cfg = EMSolverConfig(solver_type="xyce", working_dir=str(tmp_path / "run"),
                         extra_params=extra)
    return XyceAdapter(cfg)


def _fake_run_xyce_factory(prn_text: str = _AC_PRN_FIXTURE, *, rc: int = 0,
                           timed_out: bool = False):
    """替换 run_xyce：按 netlist_path 落 prn fixture（真产物文件面语义）。"""

    def fake_run(netlist_path, **kwargs):
        prn = prn_path_for(netlist_path, ac=True)
        if rc == 0 and not timed_out:
            prn.write_text(prn_text, encoding="ascii")
        return XyceRunResult(rc=rc, stdout="", stderr="engine stderr tail",
                             wall_time_s=0.1, netlist_path=Path(netlist_path),
                             timed_out=timed_out)

    return fake_run


class TestAdapterLifecycle:
    def test_connect_unavailable_false_never_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "verify_xyce_reachable",
                            lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("x")))
        s = _make_solver(tmp_path)
        assert s.connect() is False
        assert s.is_available() is False

    def test_connect_ok_via_mocked_verify(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "verify_xyce_reachable",
                            lambda *a, **k: resolve_xyce_exe())
        s = _make_solver(tmp_path)
        assert s.connect() is True
        assert s.is_available() is True

    def test_build_geometry_rejects_unknown_template(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "verify_xyce_reachable",
                            lambda *a, **k: resolve_xyce_exe())
        s = _make_solver(tmp_path)
        assert s.connect()
        assert s.build_geometry({"template": "patch"}) is False
        assert "NOT_SUPPORTED" in (s._last_error or "")
        assert ".HB" in (s._last_error or "")  # HB 登记面指引

    def test_build_geometry_rejects_bad_params(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "verify_xyce_reachable",
                            lambda *a, **k: resolve_xyce_exe())
        s = _make_solver(tmp_path)
        assert s.connect()
        assert s.build_geometry({"params": {"r_ohm": -1.0}}) is False

    def test_solve_before_build_geometry(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "verify_xyce_reachable",
                            lambda *a, **k: resolve_xyce_exe())
        s = _make_solver(tmp_path)
        assert s.connect()
        r = s.solve()
        assert not r.success and "build_geometry()" in r.message

    def test_solve_happy_path_transfer_products(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "verify_xyce_reachable",
                            lambda *a, **k: resolve_xyce_exe())
        monkeypatch.setattr(mod, "run_xyce", _fake_run_xyce_factory())
        # P1-2：engine 版本观测同步 mock——本文件"全 mock 零 WSL"声明不被
        # solve() 成功消息里的 xyce_version 真子进程穿透。
        monkeypatch.setattr(mod, "xyce_version",
                            lambda *a, **k: "Xyce mock 7.11")
        s = _make_solver(tmp_path)
        assert s.connect()
        assert s.build_geometry({})
        netlist = Path(s._config.working_dir) / "xyce_rlc_ac.cir"
        raw = netlist.read_bytes()
        assert b"\r" not in raw and raw.endswith(b".end\n")  # LF 字节面
        r = s.solve()
        assert r.success, r.message
        f_hz = r.field_data["freq_hz"]
        h = r.field_data["transfer_h"]
        assert len(f_hz) == 10 and f_hz[0] == pytest.approx(1e3)
        assert h[0] == pytest.approx(1.00392354 - 6.33283869e-3j)
        assert r.freq_ghz[0] == pytest.approx(1e-6)
        assert r.s_params is None          # 传函非 S 参数（诚实口径）
        assert "非 S 参数" in r.message
        assert "engine=Xyce mock 7.11" in r.message  # 版本走注入 mock 面
        csv_path = Path(s._config.working_dir) / "xyce_rlc_transfer.csv"
        assert csv_path.is_file()
        head = csv_path.read_text(encoding="utf-8").splitlines()[0]
        assert head == "freq_hz,re_H,im_H,db_H"
        assert s.get_sparams() is None

    def test_solve_engine_version_unknown_without_wsl(self, tmp_path,
                                                      monkeypatch):
        """P1-2：无 WSL 环境（版本探测 None）不抛——engine=unknown 降级，
        solve 成功路径不受观测失败牵连。"""
        monkeypatch.setattr(mod, "verify_xyce_reachable",
                            lambda *a, **k: resolve_xyce_exe())
        monkeypatch.setattr(mod, "run_xyce", _fake_run_xyce_factory())
        monkeypatch.setattr(mod, "xyce_version", lambda *a, **k: None)
        s = _make_solver(tmp_path)
        assert s.connect() and s.build_geometry({})
        r = s.solve()
        assert r.success, r.message
        assert "engine=unknown" in r.message

    def test_solve_stale_prn_cleared_before_run(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "verify_xyce_reachable",
                            lambda *a, **k: resolve_xyce_exe())
        s = _make_solver(tmp_path)
        assert s.connect()
        assert s.build_geometry({})
        netlist = Path(s._config.working_dir) / "xyce_rlc_ac.cir"
        prn = prn_path_for(netlist, ac=True)
        prn.parent.mkdir(parents=True, exist_ok=True)
        prn.write_text("stale", encoding="ascii")
        monkeypatch.setattr(mod, "run_xyce",
                            _fake_run_xyce_factory(rc=1))  # 失败运行不产 prn
        r = s.solve()
        assert not r.success
        assert "rc=1" in r.message and "engine stderr tail" in r.message

    def test_solve_timeout_mapped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "verify_xyce_reachable",
                            lambda *a, **k: resolve_xyce_exe())
        monkeypatch.setattr(mod, "run_xyce", _fake_run_xyce_factory(timed_out=True))
        s = _make_solver(tmp_path)
        assert s.connect() and s.build_geometry({})
        r = s.solve()
        assert not r.success and "超时" in r.message

    def test_solve_corrupt_prn_mapped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "verify_xyce_reachable",
                            lambda *a, **k: resolve_xyce_exe())
        monkeypatch.setattr(mod, "run_xyce",
                            _fake_run_xyce_factory(prn_text="Index FREQ\nnot numbers\n"))
        s = _make_solver(tmp_path)
        assert s.connect() and s.build_geometry({})
        r = s.solve()
        assert not r.success and "prn 解析失败" in r.message

    def test_visualizations_and_formats(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "verify_xyce_reachable",
                            lambda *a, **k: resolve_xyce_exe())
        s = _make_solver(tmp_path)
        assert s.connect()
        kinds = [v["kind"] for v in s.visualizations()]
        assert kinds == ["circuit", "sparams"]
        assert s.supported_output_formats() == ["csv"]
        s.close()
        assert s._netlist_path is None


# ── 能力声明与注册面 ──────────────────────────────────────────────────────────

class TestCapabilitiesAndRegistration:
    def test_caps_truthful(self):
        from rfauto.adapters.em_solver_base import MATERIAL_MODELS
        caps = XyceAdapter.CAPABILITIES
        assert caps.solver_type == "xyce"
        assert caps.dimension == "circuit"
        assert caps.supports_touchstone_export is False   # 传函非 S 参数
        assert caps.supports_wave_port is False
        assert caps.supports_lumped_port is False
        assert caps.supports_headless_solve is True
        assert caps.supports_nf2ff is False and caps.supports_sar is False
        assert caps.requires_license is False
        assert caps.supported_templates == ("rlc_lowpass",)
        assert set(caps.material_models) <= MATERIAL_MODELS
        assert caps.parallel_backends == ()  # 不虚报引擎理论并行能力

    def test_capability_method_requirements_consistent(self):
        from rfauto.adapters.em_solver_base import CAPABILITY_METHOD_REQUIREMENTS
        caps = XyceAdapter.CAPABILITIES
        for key, methods in CAPABILITY_METHOD_REQUIREMENTS.items():
            if getattr(caps, key):
                assert any(hasattr(XyceAdapter, m) for m in methods), key

    def test_enum_member_and_value(self):
        from rfauto.adapters.em_solver_base import EMSolverType
        assert EMSolverType.XYCE.value == "xyce"

    def test_register_into_fresh_registry(self):
        from rfauto.adapters.em_solver_base import EMSolverRegistry, EMSolverType
        fresh = EMSolverRegistry()
        assert mod.register_xyce(registry=fresh) is True
        assert fresh.is_registered(EMSolverType.XYCE)
        solver = fresh.create(EMSolverType.XYCE,
                              _dummy_config())
        assert isinstance(solver, XyceAdapter)

    def test_global_registry_has_xyce_after_import(self):
        from rfauto.adapters.em_solver_base import (
            EMSolverType,
            get_global_registry,
        )
        assert get_global_registry().is_registered(EMSolverType.XYCE)

    def test_capabilities_for_xyce_declared(self):
        from rfauto.adapters.em_solver_base import solver_capabilities_for
        caps = solver_capabilities_for("xyce")
        assert caps.solver_type == "xyce"
        assert caps.dimension == "circuit"

    def test_solvers_yaml_entry_consumable(self):
        from rfauto.adapters.em_solver_base import load_solvers_config
        cfg = load_solvers_config().get("xyce")
        assert cfg is not None
        assert str(getattr(cfg.solver_type, "value", cfg.solver_type)) == "xyce"


def _dummy_config():
    from rfauto.adapters.em_solver_base import EMSolverConfig
    return EMSolverConfig(solver_type="xyce")
