"""Touchstone 扩展互操作测试（ME-10：TS2.1 写出 + HFSS 注释块读取）。

覆盖三面：

- 件 1 ``write_touchstone_v2``：skrf 2.1.0 原生 2.1 版关键字写出 +
  provenance 注释注入；读回 roundtrip（rtol/atol 1e-12 判据主门）。
- 件 2 ``read_hfss_touchstone_comments``：合成最小 HFSS 注释块样例（无
  真实文件也全绿）+ runs/ 真实 HFSS 2025.1 导出样例（skipif 探测，
  只读；注释行字面一致性断言）。
- skrf 2.0 破坏面冒烟：惰性加载移除后显式导入可用、setup_pylab 已移除、
  network 面基本操作可用。

HFSS 注释语义（真实 corpus 数值互证，见模块 docstring）：``! Gamma`` 两列
是逐模传播常数 γ=α+jβ 的实/虚部（非反射系数）；``! Port Impedance`` 两列
是 Zpi 口径端口阻抗的实/虚部（恒 Zpi 不按 CharImp，#254）。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pytest
import skrf as rf

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.adapters.touchstone_interop import (
    read_hfss_touchstone_comments,
    write_touchstone_v2,
)

_RTOL = 1e-12
_ATOL = 1e-12


def _synth_network(n_ports: int, n_freq: int, seed: int = 42) -> rf.Network:
    """skrf 合成 n 端口网络（确定性随机 S，z0=50，不含物理含义）。"""
    freq = rf.Frequency(1, 3, n_freq, "GHz")
    rng = np.random.default_rng(seed + n_ports)
    s = (rng.standard_normal((n_freq, n_ports, n_ports))
         + 1j * rng.standard_normal((n_freq, n_ports, n_ports))) * 0.3
    return rf.Network(frequency=freq, s=s, z0=50.0)


def _ext(n_ports: int) -> str:
    return f".s{n_ports}p"


# ─── 件 1：TS 2.1 写出（roundtrip 判据主门） ─────────────────────────────


class TestWriteTouchstoneV2:
    @pytest.mark.parametrize("n_freq", [1, 7])
    @pytest.mark.parametrize("n_ports", [1, 2, 3, 4])
    def test_roundtrip_s_and_freq_within_1e12(self, tmp_path, n_ports, n_freq):
        net = _synth_network(n_ports, n_freq)
        path = write_touchstone_v2(net, tmp_path / f"net{_ext(n_ports)}")
        back = rf.Network(str(path))
        np.testing.assert_allclose(back.s, net.s, rtol=_RTOL, atol=_ATOL)
        np.testing.assert_allclose(back.f, net.f, rtol=_RTOL, atol=_ATOL)
        np.testing.assert_allclose(back.z0, net.z0, rtol=_RTOL, atol=_ATOL)

    def test_ts21_keyword_structure(self, tmp_path):
        path = write_touchstone_v2(_synth_network(2, 3), tmp_path / "kw.s2p")
        lines = path.read_text(encoding="ISO-8859-1").splitlines()
        meaningful = [line.strip() for line in lines
                      if line.strip() and not line.strip().startswith("!")]
        assert meaningful[0] == "[Version] 2.1"
        joined = "\n".join(meaningful)
        for keyword in ("[Number of Ports] 2", "[Number of Frequencies] 3",
                        "[Reference]", "[Network Data]", "[End]"):
            assert keyword in joined
        assert meaningful[-1] == "[End]"

    def test_provenance_block_injected(self, tmp_path):
        path = write_touchstone_v2(
            _synth_network(2, 3), tmp_path / "prov.s2p",
            comments=["custom note line", "second note"],
            run_id="ME10-X",
        )
        text = path.read_text(encoding="ISO-8859-1")
        lines = text.splitlines()
        assert lines[0].startswith("! rfauto touchstone_interop.write_touchstone_v2")
        assert re.search(r"skrf=\S+ format=touchstone-2\.1", text)
        assert re.search(
            r"generated=\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00", text)
        assert "run_id=ME10-X" in text
        assert "! custom note line" in lines
        assert "! second note" in lines
        # provenance 在 skrf banner 之前，且不破坏读取（roundtrip 仍逐位）
        back = rf.Network(str(path))
        np.testing.assert_allclose(
            back.s, _synth_network(2, 3).s, rtol=_RTOL, atol=_ATOL)

    def test_non_ascii_comment_falls_back_utf8(self, tmp_path):
        net = _synth_network(2, 2)
        path = write_touchstone_v2(
            net, tmp_path / "utf8.s2p", comments=["中文注释：通道 S 参数"])
        assert "中文注释：通道 S 参数" in path.read_text(encoding="utf-8")
        back = rf.Network(str(path))
        np.testing.assert_allclose(back.s, net.s, rtol=_RTOL, atol=_ATOL)

    def test_ma_form_roundtrip_near_lossless(self, tmp_path):
        net = _synth_network(2, 5)
        path = write_touchstone_v2(net, tmp_path / "ma.s2p", form="ma")
        back = rf.Network(str(path))
        np.testing.assert_allclose(back.s, net.s, rtol=1e-9, atol=1e-9)

    def test_write_z0_false_roundtrip(self, tmp_path):
        net = _synth_network(3, 4)
        path = write_touchstone_v2(
            net, tmp_path / "noz0.s3p", write_z0=False)
        back = rf.Network(str(path))
        np.testing.assert_allclose(back.s, net.s, rtol=_RTOL, atol=_ATOL)


# ─── 件 2：HFSS 注释块读取（合成样例，无真实文件也全绿） ─────────────────


_HFSS_SYNTHETIC = """\
! Touchstone file exported from HFSS 2025.1.0
!        File:           C:/proj/dev.aedt
!        Generated:      10:31:45 AM Sep 19, 2026
!        Design:         dev
!        Setup:          Setup1
!
!Data is not renormalized
! Terminal data exported
! Port[1] = P1sheetP
! Port[2] = P2sheetP
! Gamma         0.0530712446981517 54.3985472418686 0.0529216771735167 54.3576788427241
! Port Impedance         124.508419923945 0.118158499611523 123.420787286298 0.117243616912253
! Gamma         0.0531383846661528 54.4666304440237 0.0529886297481866 54.4257108689338
! Port Impedance         124.507429694236 0.118162008837496 123.419809796638 0.117247075148764
# GHZ S MA R 50
!Freq          magS11           angS11
2.0 0.5 -10.0 0.7 30.0 0.7 30.0 0.4 5.0
2.5 0.5 -12.0 0.7 28.0 0.7 28.0 0.4 6.0
"""


class TestReadHfssCommentsSynthetic:
    def _write(self, tmp_path, text):
        path = tmp_path / "hfss_style.s2p"
        path.write_text(text, encoding="utf-8")
        return path

    def test_full_comment_block(self, tmp_path):
        info = read_hfss_touchstone_comments(
            self._write(tmp_path, _HFSS_SYNTHETIC))
        assert info["n_ports"] == 2
        assert info["n_freqs"] == 2
        assert info["renormalized"] is False
        assert info["renormalize_ohm"] is None
        assert info["port_names"] == ["P1sheetP", "P2sheetP"]
        assert info["header"]["Design"] == "dev"
        assert info["header"]["File"] == "C:/proj/dev.aedt"
        # Gamma 两列 = γ 的实部 α 与虚部 β（rad/m），非 mag/deg
        np.testing.assert_allclose(
            info["gamma"][0], [0.0530712446981517 + 54.3985472418686j,
                               0.0529216771735167 + 54.3576788427241j],
            rtol=0, atol=0)
        # Port Impedance 两列 = re/im
        np.testing.assert_allclose(
            info["port_zpi"][1],
            [124.507429694236 + 0.118162008837496j,
             123.419809796638 + 0.117247075148764j],
            rtol=0, atol=0)
        assert info["raw"][0] == "! Touchstone file exported from HFSS 2025.1.0"
        assert len(info["raw"]) == 15  # 含数据区前的 !Freq 列头注释行

    def test_renormalizing_to_variant(self, tmp_path):
        text = _HFSS_SYNTHETIC.replace(
            "!Data is not renormalized", "! Renormalizing to 50 Ohm")
        info = read_hfss_touchstone_comments(self._write(tmp_path, text))
        assert info["renormalized"] is True
        assert info["renormalize_ohm"] == 50.0

    def test_no_comment_block_plain_skrf_file(self, tmp_path):
        net = _synth_network(2, 3)
        path = tmp_path / "plain.s2p"
        net.write_touchstone(str(path))  # write_z0 默认 False，无 Port Impedance 行
        info = read_hfss_touchstone_comments(path)
        assert info["n_ports"] is None
        assert info["n_freqs"] is None
        assert info["gamma"] is None
        assert info["port_zpi"] is None
        assert isinstance(info["raw"], list) and info["raw"]

    def test_skrf_write_z0_output_is_readable_symmetry(self, tmp_path):
        """skrf write_z0=True 产出的 ! Port Impedance 行同关键字可读回。"""
        net = _synth_network(2, 3)
        path = tmp_path / "skrf_z0.s2p"
        net.write_touchstone(str(path), write_z0=True)
        info = read_hfss_touchstone_comments(path)
        assert info["n_ports"] == 2
        assert info["n_freqs"] == 3
        assert info["gamma"] is None
        assert info["renormalized"] is False
        np.testing.assert_allclose(info["port_zpi"], net.z0, atol=_ATOL)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_hfss_touchstone_comments(tmp_path / "nope.s2p")

    def test_gamma_zpi_row_count_mismatch_raises(self, tmp_path):
        text = _HFSS_SYNTHETIC.replace(
            "! Port Impedance         124.507429694236 0.118162008837496"
            " 123.419809796638 0.117247075148764\n", "")
        with pytest.raises(ValueError, match="行数"):
            read_hfss_touchstone_comments(self._write(tmp_path, text))

    def test_odd_token_count_raises(self, tmp_path):
        text = _HFSS_SYNTHETIC.replace(
            "! Gamma         0.0531383846661528 54.4666304440237"
            " 0.0529886297481866 54.4257108689338",
            "! Gamma         1.0 2.0 3.0")
        with pytest.raises(ValueError, match="奇数"):
            read_hfss_touchstone_comments(self._write(tmp_path, text))

    def test_port_count_mismatch_between_rows_raises(self, tmp_path):
        text = _HFSS_SYNTHETIC.replace(
            "! Gamma         0.0531383846661528 54.4666304440237"
            " 0.0529886297481866 54.4257108689338",
            "! Gamma         1.0 2.0")
        with pytest.raises(ValueError, match="不一致"):
            read_hfss_touchstone_comments(self._write(tmp_path, text))


# ─── 件 2：真实 HFSS 导出样例（runs/ 只读，skipif 探测函数化） ────────────

_REPO_ROOT = Path(__file__).parent.parent.parent
_RUNS_DIR = _REPO_ROOT / "runs"
_SAMPLE_GLOBS = (
    "cps_hfss_arbitration/hfss/*_gamma.s2p",
    "slotline_arbitration/hfss/*_gamma.s2p",
)


def probe_hfss_gamma_samples() -> list[Path]:
    """路径探测函数化：runs/ 下含真实 HFSS Gamma 注释块的导出样例（只读）。"""
    if not _RUNS_DIR.is_dir():
        return []
    found: list[Path] = []
    for pattern in _SAMPLE_GLOBS:
        found.extend(p for p in sorted(_RUNS_DIR.glob(pattern)) if p.is_file())
    return found


def _first_comment_values(path: Path, keyword: str) -> list[float]:
    """独立重解析指定关键字的第一个注释行（与被测实现互为独立来源）。"""
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("!") and stripped[1:].strip().upper().startswith(keyword):
            rest = stripped[1:].strip()[len(keyword):]
            return [float(token) for token in rest.split()]
    raise AssertionError(f"{path} 未找到 {keyword} 注释行")


@pytest.mark.skipif(not probe_hfss_gamma_samples(),
                    reason="runs/ 无真实 HFSS Gamma 导出样例（干净环境诚实 skip）")
class TestRealHfssSamples:
    def test_first_sample_literal_consistency(self):
        path = probe_hfss_gamma_samples()[0]
        info = read_hfss_touchstone_comments(path)
        assert info["n_ports"] == 2
        assert info["renormalized"] is False
        # 首行字面一致（与被测实现独立的解析路径，逐位相等）
        gv = _first_comment_values(path, "GAMMA")
        expect_gamma = np.array(gv, dtype=float).reshape(-1, 2)
        np.testing.assert_array_equal(
            info["gamma"][0],
            expect_gamma[:, 0] + 1j * expect_gamma[:, 1])
        zv = _first_comment_values(path, "PORT IMPEDANCE")
        expect_zpi = np.array(zv, dtype=float).reshape(-1, 2)
        np.testing.assert_array_equal(
            info["port_zpi"][0],
            expect_zpi[:, 0] + 1j * expect_zpi[:, 1])

    @pytest.mark.parametrize("path", probe_hfss_gamma_samples())
    def test_all_samples_structure_and_physics(self, path):
        info = read_hfss_touchstone_comments(path)
        assert info["n_ports"] == 2
        assert info["gamma"] is not None and info["port_zpi"] is not None
        n_freqs = info["n_freqs"]
        assert n_freqs == info["gamma"].shape[0] == info["port_zpi"].shape[0]
        assert info["raw"] and info["raw"][0].lstrip().startswith("!")
        assert np.all(np.isfinite(info["gamma"].view(float)))
        assert np.all(np.isfinite(info["port_zpi"].view(float)))
        # 注释行行序=频率序：Gamma/Port Impedance 行数与 S 数据行数一一对应
        data_rows = [line for line in
                     path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
                     if line.strip() and not line.strip().startswith(("!", "#"))]
        assert len(data_rows) == n_freqs
        # 传播常数语义互证（γ=α+jβ，α/β>0）；β/f 带内比值作色散软守卫：
        # corpus 实测（10 样例）CPS 族 ≤1.01、slotline 族 ≤1.62（窄缝
        # narrow5w 近截止色散）——上界 2.0 只拦灾难性误读（如 mag/deg
        # 反射解读），不钉色散物理。
        alpha = info["gamma"].real
        beta = info["gamma"].imag
        assert np.all(alpha > 0) and np.all(beta > 0)
        freqs = np.array([float(row.split()[0]) for row in data_rows])
        ratio = beta / freqs[:, None]
        assert float(ratio.max() / ratio.min()) < 2.0

    def test_propagation_constant_not_reflection_semantics(self):
        """Gamma 行若按 mag/deg 反射解读将与 Zpi 行矛盾——钉住 re/im 语义。"""
        path = probe_hfss_gamma_samples()[0]
        info = read_hfss_touchstone_comments(path)
        zpi0 = info["port_zpi"][0, 0]
        gamma_reflection = (zpi0 - 50) / (zpi0 + 50)
        gamma_line = info["gamma"][0, 0]
        # 真实 Gamma（β≈54 rad/m 量级）与 50Ω 反射系数（|Γ|<1 量级）完全不同
        assert abs(gamma_line) > 10 * abs(gamma_reflection) or \
            abs(np.angle(gamma_line) - np.angle(gamma_reflection)) > 0.1


# ─── skrf 2.0 破坏面冒烟（惰性加载/setup_pylab 移除） ─────────────────────


class TestSkrfV2BreakingSurface:
    def test_skrf_v2_surface_smoke(self):
        assert int(rf.__version__.split(".")[0]) == 2
        # v2.0 移除 setup_pylab——调用方依赖即破坏（回归钉）
        assert not hasattr(rf, "setup_pylab")
        # 惰性加载移除后，子模块显式导入可用（interchange.py 依赖面）
        from skrf.io import Citi, Mdif  # noqa: F401
        from skrf.networkSet import NetworkSet  # noqa: F401
        # network 面基本操作可用
        freq = rf.Frequency(1, 2, 3, "ghz")
        net = rf.Network(frequency=freq, s=np.zeros((3, 2, 2), dtype=complex))
        assert net.nports == 2


class TestCommentInjectionDefense:
    """审查轨 C P1-2：注释换行注入防御——数据区零注入。"""

    def test_newline_comment_split_and_prefixed(self, tmp_path):
        freq = rf.Frequency(1, 2, 2, "ghz")
        n = rf.Network(frequency=freq, z0=50)
        n.s = np.zeros((2, 2, 2), dtype=complex)
        out = tmp_path / "inj.ts"
        injected = "hello" + chr(10) + "1.0 1.0 0 0 1.0 1.0 0 0 1.0 1.0"
        write_touchstone_v2(n, out, comments=[injected])
        text = out.read_text(encoding="utf-8")
        data_zone = [ln for ln in text.splitlines()
                     if ln.strip() and not ln.lstrip().startswith(("!", "#", "["))]
        for ln in data_zone:
            assert "hello" not in ln

    def test_run_id_newline_rejected(self, tmp_path):
        freq = rf.Frequency(1, 2, 2, "ghz")
        n = rf.Network(frequency=freq, z0=50)
        n.s = np.zeros((2, 2, 2), dtype=complex)
        with pytest.raises(ValueError, match="换行"):
            write_touchstone_v2(n, tmp_path / "x.ts", run_id="a" + chr(10) + "b")


# ─── ME-10' service 接线（interop_service：JSON 信封薄壳） ────────────────


class TestInteropServiceTs21Write:
    def test_envelope_roundtrip_and_version_key(self, tmp_path):
        from rfauto.service.interop_service import ts21_write

        net = _synth_network(2, 5)
        src = tmp_path / "src.s2p"
        net.write_touchstone(str(src))
        result = ts21_write(str(src), str(tmp_path / "out.s2p"),
                            run_id="ME10-SVC", comments=["svc note"])
        assert result["ok"] is True
        d = result["data"]
        assert d["n_ports"] == 2 and d["n_freqs"] == 5
        assert d["form"] == "ri"
        assert d["version_key"] == "[Version] 2.1"
        assert d["version_declared"] == "2.1"
        assert d["run_id"] == "ME10-SVC"
        assert d["roundtrip_max_abs_err"] <= 1e-12
        assert (tmp_path / "out.s2p").is_file()

    def test_missing_input_envelope(self, tmp_path):
        from rfauto.service.interop_service import ts21_write

        result = ts21_write(str(tmp_path / "nope.s2p"),
                            str(tmp_path / "out.s2p"))
        assert result["ok"] is False and "不存在" in result["error"]

    def test_bad_form_envelope(self, tmp_path):
        from rfauto.service.interop_service import ts21_write

        net = _synth_network(1, 3)
        src = tmp_path / "src.s1p"
        net.write_touchstone(str(src))
        result = ts21_write(str(src), str(tmp_path / "out.s1p"), form="bogus")
        assert result["ok"] is False


class TestInteropServiceHfssComments:
    def test_envelope_json_native_and_headers(self, tmp_path):
        from rfauto.service.interop_service import hfss_touchstone_comments

        path = tmp_path / "hfss.s2p"
        path.write_text(_HFSS_SYNTHETIC, encoding="utf-8")
        result = hfss_touchstone_comments(str(path))
        assert result["ok"] is True
        d = result["data"]
        assert d["n_ports"] == 2 and d["n_freqs"] == 2
        # numpy 复数矩阵 → JSON 原生 [[re, im], ...]（逐频点）
        assert d["gamma"][0] == [[0.0530712446981517, 54.3985472418686],
                                 [0.0529216771735167, 54.3576788427241]]
        assert d["port_zpi"][1] == [[124.507429694236, 0.118162008837496],
                                    [123.419809796638, 0.117247075148764]]
        assert d["renormalized"] is False
        assert d["port_names"] == ["P1sheetP", "P2sheetP"]
        assert d["header"]["Design"] == "dev"
        assert isinstance(d["raw"], list)
        json.dumps(result)  # 全信封必须 JSON 原生（信封契约硬门）

    def test_missing_file_envelope(self, tmp_path):
        from rfauto.service.interop_service import hfss_touchstone_comments

        result = hfss_touchstone_comments(str(tmp_path / "nope.s2p"))
        assert result["ok"] is False

    def test_struct_corruption_envelope(self, tmp_path):
        from rfauto.service.interop_service import hfss_touchstone_comments

        text = _HFSS_SYNTHETIC.replace(
            "! Gamma         0.0531383846661528 54.4666304440237"
            " 0.0529886297481866 54.4257108689338",
            "! Gamma         1.0 2.0 3.0")
        path = tmp_path / "corrupt.s2p"
        path.write_text(text, encoding="utf-8")
        result = hfss_touchstone_comments(str(path))
        assert result["ok"] is False and "奇数" in result["error"]
