"""SPICE 网表渲染/解析单测（adapters/spice_netlist，全离线，不跑二进制）。

- 渲染：元件行数值/拓扑、SIN 相位→TD 换算、.tran/.four/.meas 结构、
  ASCII 纪律、EM N 端口显式拒绝；
- 解析：真机 ngspice-47 输出原文夹具（纯弦标定实验捕获，2026-09-14）
  → Fourier 表/Meas 行结构化；
- .AC S 参数通道（D13 第三方 xval）：deck 渲染断言、wrdata AC 复数输出
  原文夹具（2026-09-15 真机标定捕获）→ Y 装配（Y[i,j]=-i(v_i) 符号约定）
  → S 闭式对拍（全离线）；
- exe 解析：env/目录/落空三态（monkeypatch，不依赖本机安装状态）。
"""

import numpy as np
import pytest

from rfauto.adapters import spice_netlist as sn
from rfauto.core.circuit_hb import (
    HBCapacitor,
    HBCircuit,
    HBDiode,
    HBEmNPort,
    HBInductor,
    HBResistor,
    HBVSource,
)

# 真机 ngspice-47 批处理输出原文片段（1V 正弦 / 50+50 分压标定，cal3.cir）
_REAL_NGSPICE_STDOUT = """
  Measurements for Transient Analysis

vdc                 =  -1.23160e-11 from=  3.00000e-06 to=  4.00000e-06

Fourier analysis for v(out):
  No. Harmonics: 10, THD: 5.02282e-10 %, Gridsize: 200, Interpolation Degree: 1, No. Periods: 1

Harmonic Frequency   Magnitude   Phase       Norm. Mag   Norm. Phase
-------- ---------   ---------   -----       ---------   -----------
 0       0           -5.4301e-13 0           0           0
 1       1e+06       0.5         4.35087e-11 1           0
 2       2e+06       1.65305e-13 85.1407     3.30609e-13 85.1407

Total analysis time (seconds) = 0.425512
"""

# 真机 ngspice-47 wrdata AC 复数输出原文（2026-09-15 标定捕获，set numdgt=15；
# DUT = 25Ω+3nH 串联二端口，逐端口 1V AC 激励，请求 i(v1) i(v2)）。
# 每向量三列 (freq, real, imag)，空格分隔、无表头；本例与闭式 Y=(1/Z)[[1,-1],[-1,1]]
# 逐点吻合（符号约定 Y[i,j]=-i(v_i)，见 adapters/spice_netlist.py 模块 docstring）。
_REAL_NGSPICE_WRDATA_AC = """ 1.390625000000000e+09 -1.905337151921443e-02  1.997758480195656e-02  1.390625000000000e+09  1.905337151921443e-02 -1.997758480195656e-02
 1.984375000000000e+09 -1.235114908666494e-02  1.847958548522053e-02  1.984375000000000e+09  1.235114908666494e-02 -1.847958548522053e-02
 5.546875000000000e+09 -2.163194054722324e-03  9.047007995492590e-03  5.546875000000000e+09  2.163194054722322e-03 -9.047007995492590e-03
"""

#: 上述夹具对应的标定 DUT（25Ω + 3nH 串联二端口）与其频率轴。
_WRDATA_FIXTURE_FREQ = np.array([1.390625e9, 1.984375e9, 5.546875e9])
_WRDATA_FIXTURE_R = 25.0
_WRDATA_FIXTURE_L = 3e-9


@pytest.fixture()
def tiny_circuit():
    c = HBCircuit(n_nodes=6, f0_hz=1e9)
    c.add(HBVSource(1, 0, 0.0, 1.0, phase_deg=-90.0))
    c.add(HBResistor(1, 2, 50.0))
    c.add(HBInductor(2, 3, 7.9e-9))
    c.add(HBResistor(3, 4, 0.5))
    c.add(HBCapacitor(4, 0, 1.6e-12))
    c.add(HBDiode(4, 5, 1e-14, emission_n=1.0))
    c.add(HBResistor(5, 0, 10e3))
    c.add(HBCapacitor(5, 0, 50e-12))
    return c


class TestRender:
    def test_element_lines_and_structure(self, tiny_circuit, tmp_path):
        out = sn.render_ngspice_netlist(
            tiny_circuit,
            tmp_path / "ref.cir",
            ["0", "src", "p1", "px", "p2", "out"],
            tstop_s=2e-6,
            tmax_s=2.5e-12,
            meas_from_s=1.5e-6,
            four_nodes=["p2", "out"],
            meas_avg={"vdc_out": "out"},
        )
        text = out.read_text(encoding="ascii")
        assert "V1 src 0 DC 0 SIN(0 1 1000000000 0)" in text  # −90° → TD=0
        assert "R1 src p1 50" in text
        assert "L1 p1 px 7.9e-09" in text
        assert "R2 px p2 0.5" in text
        assert "C1 p2 0 1.6e-12" in text
        assert "D1 p2 out DMOD1" in text
        assert ".model DMOD1 D(Is=1e-14 N=1)" in text
        assert ".tran 2.5e-12 2e-06 0 2.5e-12" in text
        assert ".meas tran vdc_out AVG v(out) from=1.5e-06 to=2e-06" in text
        assert ".four 1000000000 v(p2) v(out)" in text
        assert text.strip().endswith(".end")

    def test_phase_to_td_mapping(self, tiny_circuit, tmp_path):
        """余弦参考相位 → SIN TD：φ=0° → TD=−T/4；φ=−90° → TD=0。"""
        c = HBCircuit(n_nodes=3, f0_hz=1e6)
        c.add(HBVSource(1, 0, 0.0, 1.0, phase_deg=0.0))
        c.add(HBResistor(1, 2, 50.0))
        c.add(HBResistor(2, 0, 50.0))
        out = sn.render_ngspice_netlist(c, tmp_path / "p.cir", ["0", "a", "b"], tstop_s=4e-6, tmax_s=1e-9)
        assert "SIN(0 1 1000000 -2.5e-07)" in out.read_text(encoding="ascii")

    def test_rejects_em_nport(self, tmp_path):
        c = HBCircuit(n_nodes=4, f0_hz=1e6)
        c.add(HBVSource(1, 0, 0.0, 1.0))
        c.add(HBEmNPort((2, 3), __import__("numpy").zeros((1, 2, 2))))
        with pytest.raises(TypeError, match="不支持元件"):
            sn.render_ngspice_netlist(c, tmp_path / "x.cir", ["0", "a", "b", "c"], tstop_s=1e-6, tmax_s=1e-9)

    def test_ground_name_guard(self, tiny_circuit, tmp_path):
        with pytest.raises(ValueError, match="地"):
            sn.render_ngspice_netlist(
                tiny_circuit, tmp_path / "g.cir", ["gnd", "src"], tstop_s=1e-6, tmax_s=1e-9,
            )


class TestParse:
    def test_real_output_fixture(self):
        parsed = sn.parse_ngspice_output(_REAL_NGSPICE_STDOUT)
        sig = parsed["fourier"]["out"]
        assert sig["dc"] == pytest.approx(-5.4301e-13, abs=1e-16)
        assert sig["harmonics"][1]["magnitude"] == pytest.approx(0.5)
        assert sig["harmonics"][1]["phase_deg"] == pytest.approx(4.35087e-11, abs=1e-9)
        assert sig["harmonics"][2]["frequency_hz"] == pytest.approx(2e6)
        assert sig["harmonics"][2]["phase_deg"] == pytest.approx(85.1407)
        assert parsed["meas"]["vdc"] == pytest.approx(-1.2316e-11)

    def test_missing_fourier_window_flagged_as_empty(self):
        parsed = sn.parse_ngspice_output("Error: (1 * wavelength) longer than time span\n")
        assert parsed["fourier"] == {}
        assert parsed["meas"] == {}

    def test_phase_convention_sin_reference_to_cosine(self):
        """标定：1V 正弦源 .four 报 phase=0°（正弦参考）→ 余弦参考应为 −90°。"""
        assert sn.ngspice_phase_to_cosine(0.0) == pytest.approx(-90.0)
        assert sn.ngspice_phase_to_cosine(90.0) == pytest.approx(0.0)
        assert sn.ngspice_phase_to_cosine(180.0) == pytest.approx(90.0)


class TestExeResolution:
    def test_env_var_exe_file(self, tmp_path, monkeypatch):
        fake = tmp_path / "myng" / "ngspice_con.exe"
        fake.parent.mkdir()
        fake.write_text("")
        monkeypatch.setenv("RFAUTO_NGSPICE_BIN", str(fake))
        assert sn.resolve_ngspice_exe() == fake

    def test_env_var_directory(self, tmp_path, monkeypatch):
        d = tmp_path / "ngdir"
        d.mkdir()
        (d / "ngspice_con.exe").write_text("")
        monkeypatch.setenv("RFAUTO_NGSPICE_BIN", str(d))
        assert sn.resolve_ngspice_exe() == d / "ngspice_con.exe"

    def test_explicit_arg_wins(self, tmp_path, monkeypatch):
        fake = tmp_path / "explicit" / "ngspice.exe"
        fake.parent.mkdir()
        fake.write_text("")
        monkeypatch.setenv("RFAUTO_NGSPICE_BIN", str(tmp_path / "other"))
        assert sn.resolve_ngspice_exe(fake) == fake

    def test_not_found_raises_with_guidance(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RFAUTO_NGSPICE_BIN", str(tmp_path / "nonexistent"))
        monkeypatch.setattr(sn, "_WORKSPACE_NGSPICE", tmp_path / "nope")
        monkeypatch.setattr(sn.shutil, "which", lambda name: None)
        with pytest.raises(FileNotFoundError, match="RFAUTO_NGSPICE_BIN"):
            sn.resolve_ngspice_exe()

    def test_availability_never_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RFAUTO_NGSPICE_BIN", str(tmp_path / "nonexistent"))
        monkeypatch.setattr(sn, "_WORKSPACE_NGSPICE", tmp_path / "nope")
        monkeypatch.setattr(sn.shutil, "which", lambda name: None)
        assert sn.ngspice_available() is False

    def test_xyce_probe_honest_when_absent(self, tmp_path, monkeypatch):
        """本机无 Xyce：探测钩子如实报不可用（渲染器留待对照官方手册）。"""
        monkeypatch.delenv("RFAUTO_XYCE_BIN", raising=False)
        monkeypatch.setattr(sn.shutil, "which", lambda name: None)
        assert sn.xyce_available() is False
        with pytest.raises(FileNotFoundError, match="RFAUTO_XYCE_BIN"):
            sn.resolve_xyce_exe()

    def test_xyce_probe_available_when_env_bin_has_exe(self, tmp_path, monkeypatch):
        """探测钩子可用态（mock）：RFAUTO_XYCE_BIN 指向含 Xyce.exe 的目录。"""
        (tmp_path / "bin").mkdir()
        fake = tmp_path / "bin" / "Xyce.exe"
        fake.write_text("")
        monkeypatch.setenv("RFAUTO_XYCE_BIN", str(tmp_path / "bin"))
        assert sn.resolve_xyce_exe() == fake
        assert sn.xyce_available() is True

    def test_xyce_probe_available_via_path_lookup(self, tmp_path, monkeypatch):
        """探测钩子可用态（mock）：无 env 时回落 PATH 探测（shutil.which）。"""
        monkeypatch.delenv("RFAUTO_XYCE_BIN", raising=False)
        fake = tmp_path / "Xyce.exe"
        fake.write_text("")
        monkeypatch.setattr(sn.shutil, "which",
                            lambda name: str(fake) if name == "Xyce.exe" else None)
        assert sn.resolve_xyce_exe() == fake
        assert sn.xyce_available() is True

    def test_xyce_probe_env_dir_without_exe_falls_to_path(self, tmp_path, monkeypatch):
        """RFAUTO_XYCE_BIN 指向目录但无候选 exe → 继续回落 PATH，不误报可用。"""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        monkeypatch.setenv("RFAUTO_XYCE_BIN", str(empty_dir))
        monkeypatch.setattr(sn.shutil, "which", lambda name: None)
        assert sn.xyce_available() is False
        with pytest.raises(FileNotFoundError):
            sn.resolve_xyce_exe()


class TestTransientPlan:
    def test_meas_window_is_integer_periods(self):
        plan = sn.transient_plan_for(1e9, n_periods_total=2000, n_periods_meas=500)
        period = 1e-9
        assert plan["tstop_s"] == pytest.approx(2000 * period)
        assert plan["meas_from_s"] == pytest.approx(1500 * period)
        assert plan["tmax_s"] == pytest.approx(period / 400.0)
        span = plan["tstop_s"] - plan["meas_from_s"]
        assert span / period == pytest.approx(500.0)  # 整周期 → DC 均值无偏


# --------------------------------------------------------------------------- #
# .AC S 参数通道（D13 第三方 xval）：deck 渲染 / wrdata 解析 / Y→S 装配 / R 改写
# --------------------------------------------------------------------------- #

class TestRenderAcSparamDeck:
    def test_deck_structure_plain_ports(self, tmp_path):
        freq = [1.390625e9, 5.546875e9]
        out = sn.render_ngspice_ac_sparam_deck(
            tmp_path / "d.cir", subckt_include="dut.sp", subckt_name="dut",
            pins=["p1", "p2"], port_nodes=["p1", "p2"], ref_nodes=[None, None],
            freq_hz=freq, excited_port=0, wrdata_name="p1.data",
        )
        text = out.read_text(encoding="ascii")
        assert text.startswith("* rfauto D13 third-party SPICE .AC xval")
        assert ".include dut.sp" in text
        assert "X1 p1 p2 dut" in text  # 实例节点序 = 子电路 pin 序
        assert "V1 p1 0 AC 1" in text  # 激励端口 1V
        assert "V2 p2 0 AC 0" in text  # 其余端口理想短路
        assert "set numdgt=15" in text
        assert "set appendwrite" in text
        # 逐频字面量 ac（%.17g，不走 compose/$& 向量展开——$& 只保 6 位有效数字）
        assert f"ac lin 1 {freq[0]:.17g} {freq[0]:.17g}" in text
        assert f"ac lin 1 {freq[1]:.17g} {freq[1]:.17g}" in text
        assert text.count("wrdata p1.data i(v1) i(v2)") == 2
        assert text.strip().splitlines()[-3:] == ["quit", ".endc", ".end"]

    def test_deck_reference_pin_mode(self, tmp_path):
        """参考针形式（p1 p1_ref ...）：激励源跨 p_i—p_i_ref 差分。"""
        sn.render_ngspice_ac_sparam_deck(
            tmp_path / "r.cir", subckt_include="dut.sp", subckt_name="dut",
            pins=["p1", "p1_ref"], port_nodes=["p1"], ref_nodes=["p1_ref"],
            freq_hz=[1e9], excited_port=0, wrdata_name="p1.data",
        )
        text = (tmp_path / "r.cir").read_text(encoding="ascii")
        assert "X1 p1 p1_ref dut" in text
        assert "V1 p1 p1_ref AC 1" in text

    def test_deck_excited_port_out_of_range(self, tmp_path):
        with pytest.raises(sn.NgspiceAcError, match="excited_port"):
            sn.render_ngspice_ac_sparam_deck(
                tmp_path / "x.cir", subckt_include="d.sp", subckt_name="d",
                pins=["p1"], port_nodes=["p1"], ref_nodes=[None],
                freq_hz=[1e9], excited_port=3, wrdata_name="w.data",
            )

    @pytest.mark.parametrize("freq", [[], [0.0], [-1e9], [float("nan")], [float("inf")]])
    def test_deck_rejects_bad_freq_axis(self, tmp_path, freq):
        with pytest.raises(sn.NgspiceAcError, match="freq_hz"):
            sn.render_ngspice_ac_sparam_deck(
                tmp_path / "x.cir", subckt_include="d.sp", subckt_name="d",
                pins=["p1"], port_nodes=["p1"], ref_nodes=[None],
                freq_hz=freq, excited_port=0, wrdata_name="w.data",
            )


class TestParseWrdataAc:
    def test_real_fixture_roundtrip(self):
        freq, vals = sn.parse_ngspice_wrdata_ac(_REAL_NGSPICE_WRDATA_AC, n_vectors=2)
        assert freq.shape == (3,)
        np.testing.assert_array_equal(freq, _WRDATA_FIXTURE_FREQ)  # 15 位有效数字逐位一致
        assert vals.shape == (2, 3)
        # 第 1 行第 1 向量 = i(v1)@1.390625GHz（原文逐位）
        assert vals[0, 0] == complex(-1.905337151921443e-02, 1.997758480195656e-02)
        assert vals[1, 2] == complex(2.163194054722322e-03, -9.047007995492590e-03)

    def test_row_vector_freq_consistency_enforced(self):
        text = " 1e9 1 0 2e9 0 1 \n"  # 行内两向量 freq 列不一致
        with pytest.raises(sn.NgspiceAcError, match="频率列"):
            sn.parse_ngspice_wrdata_ac(text)

    def test_ragged_rows_rejected(self):
        with pytest.raises(sn.NgspiceAcError, match="列数"):
            sn.parse_ngspice_wrdata_ac(" 1e9 0 0 \n 1e9 0 0 1 2 \n")

    def test_non_multiple_of_three_columns_rejected(self):
        with pytest.raises(sn.NgspiceAcError, match="3 的倍数"):
            sn.parse_ngspice_wrdata_ac(" 1e9 0 \n")

    def test_vector_count_mismatch_rejected(self):
        with pytest.raises(sn.NgspiceAcError, match="向量数"):
            sn.parse_ngspice_wrdata_ac(" 1e9 0 0 \n", n_vectors=2)

    def test_empty_and_garbage(self):
        with pytest.raises(sn.NgspiceAcError, match="为空"):
            sn.parse_ngspice_wrdata_ac("\n \n")
        with pytest.raises(sn.NgspiceAcError, match="非数值"):
            sn.parse_ngspice_wrdata_ac(" 1e9 abc def \n")


class TestAssembleSFromWrdata:
    """夹具 → Y（Y[i,j]=-i(v_i)）→ S：与串联 R-L 闭式 S 对拍（全离线）。"""

    def _closed_form_s(self, freq: np.ndarray) -> np.ndarray:
        w = 2.0 * np.pi * freq
        z = _WRDATA_FIXTURE_R + 1j * w * _WRDATA_FIXTURE_L
        den = 100.0 + z  # 2*z0, z0=50
        s = np.zeros((freq.size, 2, 2), dtype=complex)
        s[:, 0, 0] = s[:, 1, 1] = z / den
        s[:, 0, 1] = s[:, 1, 0] = 100.0 / den
        return s

    def test_fixture_to_s_matches_closed_form(self):
        freq, vals = sn.parse_ngspice_wrdata_ac(_REAL_NGSPICE_WRDATA_AC, n_vectors=2)
        y = np.zeros((freq.size, 2, 2), dtype=complex)
        y[:, :, 0] = -vals.T  # 激励端口 1：Y[:,1] = -i(v_i)（逐端口一次运行取一列）
        # 本夹具只有端口 1 激励数据；用对称性补第 2 列（串联 R-L 互易对称 Y 矩阵）后转 S 验证
        y[:, :, 1] = y[:, ::-1, 0]
        s = sn._y_to_s_same_as_replay(y, [50.0, 50.0])
        assert np.max(np.abs(s - self._closed_form_s(freq))) < 1e-14

    def test_y_column_matches_closed_form_admittance(self):
        """Y[i,j] = -i(v_i) 符号约定本身与闭式导纳逐点对拍（标定核心）。"""
        _, vals = sn.parse_ngspice_wrdata_ac(_REAL_NGSPICE_WRDATA_AC, n_vectors=2)
        w = 2.0 * np.pi * _WRDATA_FIXTURE_FREQ
        z = _WRDATA_FIXTURE_R + 1j * w * _WRDATA_FIXTURE_L
        y11_expect = 1.0 / z
        y21_expect = -1.0 / z
        y11 = -vals[0]  # -i(v1)
        y21 = -vals[1]  # -i(v2)
        assert np.max(np.abs(y11 - y11_expect)) < 1e-15
        assert np.max(np.abs(y21 - y21_expect)) < 1e-15


class TestRewriteSubfloorResistors:
    def test_tiny_resistors_become_self_controlled_vccs(self):
        text = (
            "* comment Rp below floor\n"
            ".SUBCKT d p1\n"
            "V1 p1 s1 0\n"
            "R1 s1 0 50.0\n"
            "Rp1_a1 0 x1 4.311356730512539e-24\n"
            "Rp_neg x2 0 -5e-13\n"
            ".ENDS d\n"
        )
        new_text, items = sn.rewrite_subfloor_resistors(text)
        assert "Rp1_a1 0 x1 4.311356730512539e-24" not in new_text
        assert f"Grw_Rp1_a1 0 x1 0 x1 {1.0 / 4.311356730512539e-24:.17g}" in new_text
        assert "Grw_Rp_neg x2 0 x2 0" in new_text  # 负值同样改写（gm=1/R 为负）
        assert "R1 s1 0 50.0" in new_text  # 正常电阻原样保留
        assert [it["name"] for it in items] == ["Rp1_a1", "Rp_neg"]
        assert all(it["replaced_by"].startswith("Grw_") for it in items)

    def test_normal_and_unparseable_lines_untouched(self):
        text = "Rbig a b 1e-11\nRweird a b 1k\n* Rcomment a b 1e-24\nC1 a b 1p\n"
        new_text, items = sn.rewrite_subfloor_resistors(text)
        assert new_text == text  # 全部原样（1e-11 >= floor；1k 非纯浮点；注释行不动）
        assert items == []

    def test_floor_matches_ngspice_clamp_constant(self):
        assert sn.NGSPICE_RESISTOR_FLOOR_OHM == 1e-12


class TestAcSparamRunPlumbing:
    """run_ngspice_ac_sparam 编排（run_ngspice 打桩：真二进制路径在 real_edt）。"""

    @staticmethod
    def _fake_run_ngspice_closed_form(wrdata: dict):
        """按 deck 里 excite 的端口与 wrdata 文件名，写闭式 Y 的 -i(v_i) 复数列。"""

        def _fake(deck_path, *, exe=None, timeout_s=300.0):
            deck_text = deck_path.read_text(encoding="ascii")
            exc = None
            for ln in deck_text.splitlines():
                if ln.startswith("V") and ln.endswith("AC 1"):
                    exc = int(ln.split()[0][1:]) - 1
            wr_name = next(
                ln.split()[1] for ln in deck_text.splitlines() if ln.strip().startswith("wrdata")
            )
            freqs = [
                float(ln.split()[3])
                for ln in deck_text.splitlines()
                if ln.strip().startswith("ac lin 1 ")
            ]
            y = wrdata["y"]  # [nf, n, n] 闭式
            n = y.shape[1]
            lines = []
            for k, f in enumerate(freqs):
                cells = []
                for i in range(n):
                    iv = -y[k, i, exc]  # ngspice 标定：i(v_i) = -Y[i,j]
                    cells += [f, iv.real, iv.imag]
                lines.append(" " + "  ".join(f"{c:.17g}" for c in cells))
            out = deck_path.parent / wr_name
            out.write_text("\n".join(lines) + "\n", encoding="ascii")
            return {"stdout": "", "stderr": "", "returncode": 0, "errors": []}

        return _fake

    @staticmethod
    def _setup_dut(tmp_path) -> tuple[object, np.ndarray, np.ndarray]:
        freq = np.linspace(1e9, 20e9, 17)
        w = 2.0 * np.pi * freq
        z = 3.0 + 1j * w * 3e-9
        den = 100.0 + z
        s = np.zeros((freq.size, 2, 2), dtype=complex)
        s[:, 0, 0] = s[:, 1, 1] = z / den
        s[:, 0, 1] = s[:, 1, 0] = 100.0 / den
        y = np.zeros_like(s)
        for k in range(freq.size):
            ymat = np.array([[1.0 / z[k], -1.0 / z[k]], [-1.0 / z[k], 1.0 / z[k]]])
            s_expect = sn._y_to_s_same_as_replay(ymat.reshape(1, 2, 2), [50.0, 50.0])[0]
            assert np.allclose(s_expect, s[k], atol=1e-12)  # 闭式自洽
            y[k] = ymat
        sp = tmp_path / "dut.sp"
        sp.write_text(
            ".SUBCKT dut p1 p2\nR1 p1 m 3.0\nL1 m p2 3e-9\n.ENDS dut\n", encoding="ascii"
        )
        return sp, freq, y

    def test_run_ngspice_ac_sparam_assembles_s(self, tmp_path, monkeypatch):
        sp, freq, y = self._setup_dut(tmp_path)
        monkeypatch.setattr(sn, "run_ngspice", self._fake_run_ngspice_closed_form({"y": y}))
        res = sn.run_ngspice_ac_sparam(sp, freq, [50.0, 50.0], work_dir=tmp_path / "wd")
        assert res["status"] == "ok"
        assert res["n_ports"] == 2
        assert res["subckt_name"] == "dut"
        assert [r["port"] for r in res["runs"]] == [1, 2]
        assert res["resistor_rewrite"] == {
            "enabled": True, "floor_ohm": 1e-12, "n_rewritten": 0, "items": [],
        }
        assert np.max(np.abs(res["y"] - y)) < 1e-12
        w = 2.0 * np.pi * freq
        z_series = 3.0 + 1j * w * 3e-9
        den = 100.0 + z_series
        s_expect = np.zeros_like(y)
        s_expect[:, 0, 0] = s_expect[:, 1, 1] = z_series / den
        s_expect[:, 0, 1] = s_expect[:, 1, 0] = 100.0 / den
        assert np.max(np.abs(res["s"] - s_expect)) < 1e-11

    def test_run_fails_loudly_on_ngspice_error(self, tmp_path, monkeypatch):
        sp, freq, _ = self._setup_dut(tmp_path)

        def _bad(deck_path, *, exe=None, timeout_s=300.0):
            return {"stdout": "Error: unknown device", "stderr": "", "returncode": 0,
                    "errors": ["Error: unknown device"]}

        monkeypatch.setattr(sn, "run_ngspice", _bad)
        with pytest.raises(sn.NgspiceAcError, match="运行失败"):
            sn.run_ngspice_ac_sparam(sp, freq, [50.0, 50.0], work_dir=tmp_path / "wd")

    def test_run_fails_when_wrdata_missing(self, tmp_path, monkeypatch):
        sp, freq, _ = self._setup_dut(tmp_path)

        def _silent(deck_path, *, exe=None, timeout_s=300.0):
            return {"stdout": "", "stderr": "", "returncode": 0, "errors": []}

        monkeypatch.setattr(sn, "run_ngspice", _silent)
        with pytest.raises(sn.NgspiceAcError, match="wrdata"):
            sn.run_ngspice_ac_sparam(sp, freq, [50.0, 50.0], work_dir=tmp_path / "wd")

    def test_xval_wraps_infrastructure_failure_as_error_status(self, tmp_path, monkeypatch):
        sp, freq, _ = self._setup_dut(tmp_path)

        def _no_exe(deck_path, *, exe=None, timeout_s=300.0):
            raise FileNotFoundError("未找到 ngspice 可执行文件")

        monkeypatch.setattr(sn, "run_ngspice", _no_exe)
        x = sn.xval_macromodel_spice(
            np.zeros((freq.size, 2, 2), dtype=complex), freq, sp,
            z0=[50.0, 50.0], work_dir=tmp_path / "wd",
        )
        assert x["status"] == "error"
        assert "FileNotFoundError" in x["error"]
        assert x["gdm_at_least_good"] is False
        assert x["verifier"] == sn.XVAL_VERIFIER_NGSPICE_AC

    def test_xval_missing_subckt_is_error_not_crash(self, tmp_path):
        freq = np.linspace(1e9, 5e9, 17)
        x = sn.xval_macromodel_spice(
            np.zeros((freq.size, 2, 2), dtype=complex), freq, tmp_path / "nope.sp",
            work_dir=tmp_path / "wd",
        )
        assert x["status"] == "error"
        assert "不存在" in x["error"]
