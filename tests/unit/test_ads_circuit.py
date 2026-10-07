"""P3: ads_circuit 系统指标计算 + render_netlist 委托（纯 skrf, 无 license）。"""


import numpy as np
import pytest
import skrf

from rfauto.core.contracts import AdsExchangeContract, TouchstoneContract
from rfauto.linkage import ads_circuit as ac


def _ideal_divider(npts=5, freq=(1.5e9, 3.5e9)):
    f = skrf.Frequency.from_f(np.linspace(freq[0], freq[1], npts), unit="Hz")
    s = np.zeros((npts, 3, 3), dtype=complex)
    s[:, 0, 0] = 0.12
    s[:, 1, 0] = 1 / np.sqrt(2)
    s[:, 0, 1] = 1 / np.sqrt(2)
    s[:, 2, 0] = 1 / np.sqrt(2)
    s[:, 0, 2] = 1 / np.sqrt(2)
    s[:, 2, 1] = 0.05
    s[:, 1, 2] = 0.05
    return skrf.Network(frequency=f, s=s, z0=50)


class TestComputeSystemMetrics:
    def test_gain_and_vswr(self):
        net = _ideal_divider()
        m = ac.compute_system_metrics(net, ["system_gain_db", "input_vswr"])
        assert m["system_gain_db"] == pytest.approx(-3.0103, abs=1e-3)
        assert m["input_vswr"] == pytest.approx(1.2727, abs=1e-3)

    def test_amplitude_balance_even_split_zero(self):
        net = _ideal_divider()
        m = ac.compute_system_metrics(net, ["amplitude_balance_db"])
        assert m["amplitude_balance_db"] == pytest.approx(0.0, abs=1e-6)

    def test_amplitude_balance_uneven(self):
        net = _ideal_divider()
        s = np.asarray(net.s)
        s[:, 2, 0] = 10 ** (-6 / 20)
        net2 = skrf.Network(frequency=net.frequency, s=s, z0=50)
        m = ac.compute_system_metrics(net2, ["amplitude_balance_db"])
        assert m["amplitude_balance_db"] == pytest.approx(2.9897, abs=1e-3)

    def test_s_param_db_metrics(self):
        net = _ideal_divider()
        m = ac.compute_system_metrics(net, ["S11_db", "S21_db", "S23_db"])
        assert m["S11_db"] == pytest.approx(20 * np.log10(0.12), abs=1e-3)
        assert m["S21_db"] == pytest.approx(-3.0103, abs=1e-3)
        assert m["S23_db"] == pytest.approx(20 * np.log10(0.05), abs=1e-3)

    def test_unknown_metric_raises(self):
        net = _ideal_divider()
        with pytest.raises(ValueError):
            ac.compute_system_metrics(net, ["nope_db"])


class TestBalanceMetricsCircularAndPerPoint:
    """B-2/S3 回归钉：相位平衡圆均值 + 幅度平衡逐点绝对差带内均值。"""

    @staticmethod
    def _net_with(d21_phase_deg, d31_phase_deg, mag21=10 ** (-3 / 20),
                  mag31=10 ** (-3 / 20), npts=2):
        f = skrf.Frequency.from_f(np.linspace(1.5e9, 3.5e9, npts), unit="Hz")
        s = np.zeros((npts, 3, 3), dtype=complex)
        m21 = np.broadcast_to(np.asarray(mag21, dtype=float), (npts,))
        m31 = np.broadcast_to(np.asarray(mag31, dtype=float), (npts,))
        p21 = np.broadcast_to(np.asarray(d21_phase_deg, dtype=float), (npts,))
        p31 = np.broadcast_to(np.asarray(d31_phase_deg, dtype=float), (npts,))
        s[:, 1, 0] = m21 * np.exp(1j * np.radians(p21))
        s[:, 2, 0] = m31 * np.exp(1j * np.radians(p31))
        return skrf.Network(frequency=f, s=s, z0=50)

    def test_phase_wraparound_circular_mean(self):
        # Δφ 逐点 +179°/−179°（跨 ±180 绕圈）：线性均值=0（失真），
        # 圆均值=180°（真值）——S21/S31 相位各取 179.5/−179.5 与 0.5/−0.5
        # 使 np.angle 差恰为 ±179
        net = self._net_with(
            d21_phase_deg=[179.5, -179.5], d31_phase_deg=[0.5, -0.5])
        m = ac.compute_system_metrics(net, ["output_phase_balance"])
        assert abs(abs(m["output_phase_balance"]) - 180.0) < 0.5

    def test_phase_balance_small_difference_unchanged(self):
        # 小相位差（无绕圈）与线性口径一致（无回归）
        net = self._net_with(d21_phase_deg=30.0, d31_phase_deg=-30.0)
        m = ac.compute_system_metrics(net, ["output_phase_balance"])
        assert m["output_phase_balance"] == pytest.approx(60.0, abs=1e-6)

    def test_amplitude_ripple_cancellation_exposed(self):
        # 逐点 |ΔdB| 交替 ±1：|均值−均值|=0（纹波对消掩盖失衡），
        # 逐点均值=1.0——docstring 契约口径
        net = self._net_with(
            d21_phase_deg=0.0, d31_phase_deg=0.0,
            mag21=[10 ** (-3 / 20), 10 ** (-4 / 20)],
            mag31=[10 ** (-4 / 20), 10 ** (-3 / 20)])
        m = ac.compute_system_metrics(net, ["amplitude_balance_db"])
        assert m["amplitude_balance_db"] == pytest.approx(1.0, abs=1e-6)


class TestRenderNetlistDelegate:
    def test_render_netlist_3port(self, tmp_path):
        f = skrf.Frequency(1.5, 3.5, 41, "GHz")
        s = np.zeros((f.npoints, 3, 3), dtype=complex)
        s[:, 1, 0] = 1 / np.sqrt(2)
        net = skrf.Network(frequency=f, s=s, z0=50)
        snp = tmp_path / "t.s3p"
        net.write_touchstone(str(snp), form="db")
        recipe = ac.AdsCircuitRecipe(topology="wilkinson_snp")
        contract = AdsExchangeContract(touchstone=TouchstoneContract(port_order=["input", "output_1", "output_2"]))
        out = tmp_path / "nl" / "netlist.txt"
        ac.render_netlist(recipe, snp, out, contract)
        text = out.read_text(encoding="ascii")
        assert "SnP:SNP1  P1 P2 P3 NumPorts=3" in text
        assert 'Type="touchstone"' in text
