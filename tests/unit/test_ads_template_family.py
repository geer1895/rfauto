"""ADS 参数化模板族（wilkinson_snp / branchline_cascade）离线钉死。

覆盖：闭式 Wilkinson 教科书值、频扫解析、两族网表纯文本断言（每语句独占一行 /
SnP 节点数 / 无 Term / 纯 ASCII 无 BOM / 确定性）、branchline 族与
field_circuit_anchor 锚渲染器"同参数同文本"、对拍内核、service JSON 进出
（ads_runner 注入，不依赖真机；真机数字见 runs/rm_ads_wp43/）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import skrf

from rfauto.linkage import ads_template_family as atf
from rfauto.linkage import field_circuit_anchor as fca
from rfauto.service import ads_template_service as svc

F0 = 2.4e9


def _payload_from_network(net: skrf.Network) -> dict:
    """skrf.Network → ads_netlist.parse_dataset 同形 payload（离线管线替身）。"""
    n = net.nports
    s = {}
    for i in range(n):
        for j in range(n):
            s[f"{i + 1}_{j + 1}"] = [[float(v.real), float(v.imag)] for v in net.s[:, i, j]]
    return {
        "ok": True, "key": "SP1.SP", "frequency_hz": [float(f) for f in net.f], "s": s,
        "port_names": [f"P{k + 1}" for k in range(n)], "port_z": [[50.0, 0.0]] * n,
    }


@pytest.fixture()
def wilk_s3p(tmp_path: Path) -> Path:
    return atf.build_wilkinson_touchstone(tmp_path / "wilk.s3p", n_points=41)


@pytest.fixture()
def bl_s4p(tmp_path: Path) -> Path:
    return fca.build_branchline_touchstone(tmp_path / "bl.s4p", n_points=41)


# --------------------------------------------------------------------------- #
# 闭式 Wilkinson
# --------------------------------------------------------------------------- #

class TestWilkinsonClosedForm:
    def test_textbook_values_at_f0(self):
        s = atf.wilkinson_smatrix(np.array([F0]), f0_hz=F0)[0]
        for i in range(3):
            assert abs(s[i, i]) < 1e-12, f"S{i + 1}{i + 1} 应为 0"
        assert abs(abs(s[1, 0]) - 1 / np.sqrt(2)) < 1e-12
        assert abs(abs(s[2, 0]) - 1 / np.sqrt(2)) < 1e-12
        assert abs(s[1, 2]) < 1e-12, "f0 处理想隔离"
        assert abs(s[1, 0] - s[2, 0]) < 1e-12, "等分同相"
        # 输出滞后 90°（λ/4 线）
        assert abs(np.angle(s[1, 0], deg=True) + 90.0) < 1e-9

    def test_reciprocal_and_lossless_unitarity_off_f0(self):
        f = np.linspace(1.6e9, 3.2e9, 9)
        s = atf.wilkinson_smatrix(f, f0_hz=F0)
        for k in range(f.size):
            assert np.allclose(s[k], s[k].T, atol=1e-12)
        # 无耗线 + 隔离电阻：功率守恒不等式 σmax ≤ 1（电阻可吸收功率）
        sig = np.linalg.svd(s, compute_uv=False)
        assert np.all(sig <= 1 + 1e-9)
        # 输入端：入射功率全部转移或被电阻吸收，|S11|²+|S21|²+|S31|² = 1（对称激励无电阻耗散）
        p = np.abs(s[:, 0, 0]) ** 2 + np.abs(s[:, 1, 0]) ** 2 + np.abs(s[:, 2, 0]) ** 2
        assert np.allclose(p, 1.0, atol=1e-9)

    def test_loss_reduces_transmission(self):
        s0 = atf.wilkinson_smatrix(np.array([F0]), loss_np_per_qw=0.0)[0]
        s1 = atf.wilkinson_smatrix(np.array([F0]), loss_np_per_qw=0.05)[0]
        assert abs(s1[1, 0]) < abs(s0[1, 0])

    def test_touchstone_written_3port(self, wilk_s3p):
        net = skrf.Network(str(wilk_s3p))
        assert net.nports == 3
        assert net.f.size == 41
        k = int(np.argmin(np.abs(net.f - F0)))
        assert abs(20 * np.log10(abs(net.s[k, 1, 0])) + 3.0103) < 0.05


# --------------------------------------------------------------------------- #
# 频扫解析
# --------------------------------------------------------------------------- #

class TestResolveSweep:
    def test_explicit_needs_no_file(self, tmp_path):
        sw = atf.resolve_sweep(tmp_path / "missing.s3p", {"fstart": 1, "fstop": 3, "npoints": 21})
        assert sw["source"] == "explicit"
        assert sw["fstart_hz"] == 1e9 and sw["fstop_hz"] == 3e9 and sw["npoints"] == 21

    def test_touchstone_fallback(self, wilk_s3p):
        sw = atf.resolve_sweep(wilk_s3p, None)
        assert sw["source"] == "touchstone"
        assert sw["unit"] == "GHz"
        assert abs(sw["fstart"] - 1.6) < 1e-9 and abs(sw["fstop"] - 3.2) < 1e-9
        assert sw["npoints"] == 41

    def test_mixed_and_unit(self, wilk_s3p):
        sw = atf.resolve_sweep(wilk_s3p, {"npoints": 5, "unit": "MHz"})
        assert sw["source"] == "mixed" and sw["npoints"] == 5
        assert abs(sw["fstart"] - 1600.0) < 1e-6

    @pytest.mark.parametrize("bad", [
        {"fstart": 3, "fstop": 1, "npoints": 5},
        {"fstart": 1, "fstop": 3, "npoints": 1},
        {"fstart": 1, "fstop": 3, "npoints": 5, "unit": "THz"},
    ])
    def test_rejects_bad_sweep(self, tmp_path, bad):
        with pytest.raises(ValueError):
            atf.resolve_sweep(tmp_path / "x.s3p", bad)

    def test_missing_file_without_explicit(self, tmp_path):
        with pytest.raises((OSError, ValueError)):
            atf.resolve_sweep(tmp_path / "missing.s3p", {"fstart": 1})


# --------------------------------------------------------------------------- #
# 族成员 1：wilkinson_snp
# --------------------------------------------------------------------------- #

class TestWilkinsonSnpNetlist:
    def test_structure_from_touchstone(self, wilk_s3p):
        text = atf.render_wilkinson_snp(wilk_s3p)
        lines = text.splitlines()
        assert text.endswith("\n")
        assert lines[0].startswith("Options ")
        assert lines[1].startswith("S_Param:SP1 ")
        assert lines[2] == "SweepPlan: SP1_stim Start=1.6 GHz Stop=3.2 GHz Lin=41"
        assert lines[3].startswith("OutputPlan:SP1_Output ")
        ports = [ln for ln in lines if ln.startswith("Port:")]
        assert len(ports) == 3
        for i in (1, 2, 3):
            assert f"Port:P{i}  P{i} 0 Num={i} Z=50 Ohm Noise=yes" in lines
        snp = [ln for ln in lines if ln.startswith("SnP:")]
        assert len(snp) == 1
        assert snp[0].startswith("SnP:SNP1  P1 P2 P3 NumPorts=3 File=")
        assert 'Type="touchstone"' in snp[0] and "CheckPassivity=0" in snp[0]
        assert str(wilk_s3p.resolve()) in snp[0]
        assert "Term:" not in text
        assert len(lines) == 4 + 3 + 1  # 每语句独占一行

    def test_explicit_params_pure_text(self, tmp_path):
        """显式 sweep + n_ports：不读文件（路径可不存在），纯文本确定性。"""
        p = tmp_path / "nofile.s2p"
        a = atf.render_wilkinson_snp(p, sweep={"fstart": 0.5, "fstop": 6, "npoints": 111, "unit": "GHz"}, n_ports=2, z0=75)
        b = atf.render_wilkinson_snp(p, sweep={"fstart": 0.5, "fstop": 6, "npoints": 111, "unit": "GHz"}, n_ports=2, z0=75)
        assert a == b
        assert "Start=0.5 GHz Stop=6 GHz Lin=111" in a
        assert "Port:P2  P2 0 Num=2 Z=75 Ohm Noise=yes" in a
        assert "NumPorts=2" in a and "P3" not in a

    def test_ascii_only_no_bom(self, wilk_s3p, tmp_path):
        text = atf.render_wilkinson_snp(wilk_s3p)
        out = atf.write_netlist(text, tmp_path / "nl" / "w.txt")
        raw = out.read_bytes()
        assert raw[:3] != b"\xef\xbb\xbf"
        raw.decode("ascii")
        assert b"\r\n" not in raw

    def test_non_ascii_path_rejected(self, tmp_path):
        p = tmp_path / "数据.s2p"
        with pytest.raises(ValueError):
            atf.render_wilkinson_snp(p, sweep={"fstart": 1, "fstop": 2, "npoints": 3}, n_ports=2)


# --------------------------------------------------------------------------- #
# 族成员 2：branchline_cascade
# --------------------------------------------------------------------------- #

class TestBranchlineCascadeNetlist:
    def test_parity_with_anchor_renderer(self, bl_s4p, tmp_path):
        """同参数 → 与 field_circuit_anchor.render_cascade_netlist 逐字节同文本。"""
        anchor = fca.render_cascade_netlist(bl_s4p, tmp_path / "anchor.txt")
        mine = atf.render_branchline_cascade(bl_s4p)
        assert mine == anchor.read_text(encoding="ascii")

    def test_parity_with_custom_params(self, bl_s4p, tmp_path):
        kw = dict(f0_hz=2.0e9, theta_in_deg=30.0, theta_out_deg=120.0, z_line=35.0, z0=50.0)
        anchor = fca.render_cascade_netlist(bl_s4p, tmp_path / "anchor.txt", **kw)
        assert atf.render_branchline_cascade(bl_s4p, **kw) == anchor.read_text(encoding="ascii")

    def test_lines_and_topology(self, bl_s4p):
        text = atf.render_branchline_cascade(bl_s4p, theta_in_deg=60, theta_out_deg=30, z_line=45)
        lines = text.splitlines()
        assert len(lines) == 4 + 4 + 3
        assert "TLIN:TLIN1  N_A N_B  Z=45 Ohm E=60 F=2.4 GHz" in lines
        assert "TLIN:TLIN2  N_C N_D  Z=45 Ohm E=30 F=2.4 GHz" in lines
        snp = next(ln for ln in lines if ln.startswith("SnP:"))
        assert snp.startswith("SnP:SNP1  N_B N_C N_T1 N_T2 NumPorts=4 ")
        assert "Port:P3  N_T1 0 Num=3 Z=50 Ohm Noise=yes" in lines
        assert "Port:P4  N_T2 0 Num=4 Z=50 Ohm Noise=yes" in lines
        assert "Term:" not in text

    def test_explicit_sweep_override_and_unit(self, bl_s4p):
        text = atf.render_branchline_cascade(
            bl_s4p, sweep={"fstart": 1000, "fstop": 4000, "npoints": 301, "unit": "MHz"},
        )
        assert "Start=1000 MHz Stop=4000 MHz Lin=301" in text
        assert "F=2400 MHz" in text  # f0 随单位换算

    def test_rejects_non_4port(self, wilk_s3p):
        with pytest.raises(ValueError, match="4 端口"):
            atf.render_branchline_cascade(wilk_s3p)

    def test_render_family_dispatch(self, bl_s4p, wilk_s3p):
        assert atf.render_family("branchline_cascade", bl_s4p) == atf.render_branchline_cascade(bl_s4p)
        assert atf.render_family("wilkinson_snp", wilk_s3p) == atf.render_wilkinson_snp(wilk_s3p)
        with pytest.raises(ValueError, match="未知模板族"):
            atf.render_family("ratrace", bl_s4p)


# --------------------------------------------------------------------------- #
# 对拍内核
# --------------------------------------------------------------------------- #

class TestCompare:
    def test_align_same_grid_with_ulp_noise(self, wilk_s3p):
        """Touchstone 读回频率带 ~1e-7 Hz 浮点噪声时不得触发 scipy bounds 错误。"""
        net = skrf.Network(str(wilk_s3p))
        noisy = skrf.Network(
            frequency=skrf.Frequency.from_f(net.f * (1 + 3e-16) + 5e-7, unit="Hz"), s=net.s, z0=50,
        )
        aligned = atf.align_to_grid(noisy, net.frequency)
        assert np.array_equal(aligned.f, net.f)
        assert np.max(np.abs(aligned.s - net.s)) < 1e-15

    def test_align_different_grid_interpolates(self, wilk_s3p):
        net = skrf.Network(str(wilk_s3p))
        target = skrf.Frequency(1.6, 3.2, 21, "GHz")
        aligned = atf.align_to_grid(net, target)
        assert aligned.f.size == 21
        exact = atf.wilkinson_smatrix(target.f)
        assert np.max(np.abs(aligned.s - exact)) < 5e-3  # 线性插值 41→21 点

    def test_wilkinson_passthrough_zero_delta(self, wilk_s3p):
        net = skrf.Network(str(wilk_s3p))
        cmp = atf.compare_family_result("wilkinson_snp", wilk_s3p, _payload_from_network(net))
        assert cmp["n_ports_compared"] == 3 and cmp["n_points"] == 41
        assert cmp["max_abs_delta_s"] < 1e-12
        assert set(cmp["per_response_max_abs_delta_s"]) == {f"S{i}{j}" for i in "123" for j in "123"}

    def test_wilkinson_detects_perturbation(self, wilk_s3p):
        net = skrf.Network(str(wilk_s3p))
        payload = _payload_from_network(net)
        payload["s"]["2_1"][5][0] += 0.05
        cmp = atf.compare_family_result("wilkinson_snp", wilk_s3p, payload)
        assert abs(cmp["max_abs_delta_s"] - 0.05) < 1e-9
        assert abs(cmp["per_response_max_abs_delta_s"]["S21"] - 0.05) < 1e-9

    def test_branchline_reference_cascade_zero_delta(self, bl_s4p):
        net4 = skrf.Network(str(bl_s4p))
        ref = fca.compose_reference_cascade(net4)
        # 4 端口 payload：P1/P2 = 合成 2 端口，P3/P4 终止口占位（对拍只取 P1/P2）
        s4 = np.zeros((ref.f.size, 4, 4), dtype=complex)
        s4[:, :2, :2] = ref.s
        big = skrf.Network(frequency=ref.frequency, s=s4, z0=50)
        cmp = atf.compare_family_result("branchline_cascade", bl_s4p, _payload_from_network(big))
        assert cmp["n_ports_compared"] == 2
        assert cmp["max_abs_delta_s"] < 1e-12
        assert cmp["fsv"]["at_least_vg"] is True
        assert cmp["fsv"]["phase_consistent"] is True

    def test_branchline_params_forwarded(self, bl_s4p):
        net4 = skrf.Network(str(bl_s4p))
        ref = fca.compose_reference_cascade(net4, theta_in_deg=30.0, theta_out_deg=60.0)
        s4 = np.zeros((ref.f.size, 4, 4), dtype=complex)
        s4[:, :2, :2] = ref.s
        big = skrf.Network(frequency=ref.frequency, s=s4, z0=50)
        payload = _payload_from_network(big)
        ok = atf.compare_family_result(
            "branchline_cascade", bl_s4p, payload, {"theta_in_deg": 30.0, "theta_out_deg": 60.0},
        )
        wrong = atf.compare_family_result("branchline_cascade", bl_s4p, payload)  # 锚默认 90/45
        assert ok["max_abs_delta_s"] < 1e-12
        assert wrong["max_abs_delta_s"] > 1e-3


# --------------------------------------------------------------------------- #
# service（JSON 进出，ads_runner 注入）
# --------------------------------------------------------------------------- #

class TestService:
    def test_render_json_in_out(self, wilk_s3p, tmp_path):
        r = svc.render_ads_template({
            "family": "wilkinson_snp", "snp_path": str(wilk_s3p),
            "output_path": str(tmp_path / "o" / "w.txt"),
            "params": {"sweep": {"fstart": 1, "fstop": 3, "npoints": 21}},
        })
        assert r["ok"] is True and Path(r["netlist_path"]).exists()
        assert r["sweep"]["source"] == "explicit" and r["n_lines"] == 8
        assert isinstance(r["snp_path"], str)

    def test_render_missing_field_and_unknown_family(self, wilk_s3p, tmp_path):
        with pytest.raises(ValueError, match="缺少必填"):
            svc.render_ads_template({"family": "wilkinson_snp"})
        with pytest.raises(ValueError, match="未知模板族"):
            svc.render_ads_template({"family": "x", "snp_path": str(wilk_s3p), "output_path": str(tmp_path / "n.txt")})
        with pytest.raises(FileNotFoundError):
            svc.render_ads_template({"family": "wilkinson_snp", "snp_path": str(tmp_path / "no.s3p"), "output_path": str(tmp_path / "n.txt")})

    def test_run_with_injected_runner(self, wilk_s3p, tmp_path):
        net = skrf.Network(str(wilk_s3p))
        seen: dict = {}

        def runner(netlist: Path) -> dict:
            seen["netlist"] = netlist
            return _payload_from_network(net)

        r = svc.run_ads_template(
            {"family": "wilkinson_snp", "snp_path": str(wilk_s3p), "out_dir": str(tmp_path / "run")},
            ads_runner=runner,
        )
        assert seen["netlist"].name == "wilkinson_snp_netlist.txt"
        assert r["ok"] is True
        assert r["ads"]["status"] == "ok" and r["ads"]["runner"] == "injected"
        assert r["ads"]["n_points"] == 41 and r["ads"]["port_names"] == ["P1", "P2", "P3"]
        assert r["compare"]["gate_ok"] is True and r["compare"]["max_abs_delta_s"] < 1e-12
        assert (tmp_path / "run" / "wilkinson_snp_result.json").exists()

    def test_run_branchline_with_injected_runner(self, bl_s4p, tmp_path):
        net4 = skrf.Network(str(bl_s4p))
        ref = fca.compose_reference_cascade(net4)
        s4 = np.zeros((ref.f.size, 4, 4), dtype=complex)
        s4[:, :2, :2] = ref.s
        big = skrf.Network(frequency=ref.frequency, s=s4, z0=50)
        r = svc.run_ads_template(
            {"family": "branchline_cascade", "snp_path": str(bl_s4p), "out_dir": str(tmp_path / "run")},
            ads_runner=lambda _p: _payload_from_network(big),
        )
        assert r["ok"] is True
        assert r["compare"]["fsv"]["at_least_vg"] is True

    def test_run_gate_fails_honestly(self, wilk_s3p, tmp_path):
        net = skrf.Network(str(wilk_s3p))
        payload = _payload_from_network(net)
        payload["s"]["1_1"][0][0] += 0.1
        r = svc.run_ads_template(
            {"family": "wilkinson_snp", "snp_path": str(wilk_s3p), "out_dir": str(tmp_path / "run")},
            ads_runner=lambda _p: payload,
        )
        assert r["ok"] is False
        assert r["ads"]["status"] == "ok"
        assert r["compare"]["gate_ok"] is False

    def test_run_ads_failure_recorded_not_raised(self, wilk_s3p, tmp_path):
        def boom(_p: Path) -> dict:
            raise RuntimeError("Linear features are not licensed (0 tokens)")

        r = svc.run_ads_template(
            {"family": "wilkinson_snp", "snp_path": str(wilk_s3p), "out_dir": str(tmp_path / "run")},
            ads_runner=boom,
        )
        assert r["ok"] is False
        assert r["ads"]["status"] == "error" and "not licensed" in r["ads"]["error"]
        assert "compare" not in r

    def test_run_compare_off(self, wilk_s3p, tmp_path):
        net = skrf.Network(str(wilk_s3p))
        r = svc.run_ads_template(
            {"family": "wilkinson_snp", "snp_path": str(wilk_s3p), "out_dir": str(tmp_path / "run"), "compare": False},
            ads_runner=lambda _p: _payload_from_network(net),
        )
        assert r["ok"] is True and r["compare"] == {"status": "skipped"}

    def test_reference_snp_path_honored(self, wilk_s3p, tmp_path):
        """D13 桥用法：snp_path=替身进 ADS，reference_snp_path=原始数据参考。"""
        net = skrf.Network(str(wilk_s3p))
        pert = net.copy()
        pert.s[:, 0, 0] += 0.03
        pert_path = tmp_path / "pert.s3p"
        pert.write_touchstone(str(pert_path), form="ri")
        base = {"family": "wilkinson_snp", "snp_path": str(wilk_s3p), "max_abs_delta_s_gate": 0.02}
        r_self = svc.run_ads_template(
            {**base, "out_dir": str(tmp_path / "a")}, ads_runner=lambda _p: _payload_from_network(net),
        )
        r_ref = svc.run_ads_template(
            {**base, "out_dir": str(tmp_path / "b"), "reference_snp_path": str(pert_path)},
            ads_runner=lambda _p: _payload_from_network(net),
        )
        assert r_self["reference_snp_path"] == str(wilk_s3p) and r_self["compare"]["gate_ok"] is True
        assert r_ref["reference_snp_path"] == str(pert_path)
        assert abs(r_ref["compare"]["max_abs_delta_s"] - 0.03) < 1e-6
        assert r_ref["compare"]["gate_ok"] is False and r_ref["ok"] is False
