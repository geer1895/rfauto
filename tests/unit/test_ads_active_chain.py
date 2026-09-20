"""C14 有源链路 ADS 通道与 service 编排单测（离线纪律）。

覆盖:
- 匹配链网表渲染（Port/SnP 语法族与 field_circuit_anchor 同款, 真机实证;
  占位符全量填充 / ASCII 无 BOM / 频段交集 / 端口数契约）;
- payload→网络恢复、注入 ads_runner 的管线验证与诚实降级
  （离线注入只验管线不充当裁判, 与 test_field_circuit_anchor 同口径）;
- 手工口径对比器（同数据恒等 / 扰动劣化判定）;
- load-pull HB 网表渲染（HB/Port 源/复数 Z/aele 语法 2026-09-18 真机实证,
  文本断言钉住三条真机修正; 渲染确定性）+ HB payload→点结果 / 闭式参考 /
  对拍 / 注入 ads_runner 的单点管线;
- service 两入口 JSON 进出 + 落盘 + Cripps 合理性全绿。

离线纪律: 本文件不跑 hpeesofsim（真机通道由 tests/real_edt 与
runs/rm_ads_c14/ 承载）。
"""

import json
from pathlib import Path

import numpy as np
import pytest
import skrf

from rfauto.core.active_chain import HybridPiModel, LoadPullDevice
from rfauto.core.matching import synthesize_l_match, to_skrf_network
from rfauto.linkage import ads_active_chain as aac
from rfauto.service import active_chain_service as acs

F0_HZ = 2.0e9
#: 稳定 LNA 器件（与 test_active_chain 同参数, K=2.70）。
_LNA = dict(gm_s=0.02, rds_ohm=300.0, cgs_f=0.5e-12, cds_f=0.12e-12,
            cgd_f=2e-15, rg_ohm=5.0)


def _write_match_snp(tmp_path: Path, n_points: int = 41) -> Path:
    """匹配网络 Touchstone（生产 = HFSS/openEMS EM 导出; 此处闭式 L 型替身）。"""
    res = synthesize_l_match(z_source=50.0, z_load=15.0, f0_ghz=2.0)
    net = to_skrf_network(res, freqs_ghz=np.linspace(1.8, 2.2, n_points))
    net.renormalize([50.0, 50.0])
    p = tmp_path / "match.s2p"
    net.write_touchstone(str(p), form="ri")
    return p


def _write_device_snp(
    tmp_path: Path, n_points: int = 41, band=(1.8e9, 2.2e9), params=None,
) -> Path:
    """混合π合成器件 Touchstone。"""
    model = HybridPiModel(**(params or _LNA))
    freqs = np.linspace(band[0], band[1], n_points)
    s = np.stack([model.to_sparams(f) for f in freqs])
    net = skrf.Network(frequency=skrf.Frequency.from_f(freqs, unit="Hz"), s=s, z0=50)
    p = tmp_path / "device.s2p"
    net.write_touchstone(str(p), form="ri")
    return p


def _fake_ads_runner(match_snp: Path, device_snp: Path):
    """离线 ADS 替身: skrf 重算级联打包成 .ds 探针 payload（只验管线）。"""

    def _run(netlist_path: Path) -> dict:
        _, _, cascade = aac.chain_manual_reference(match_snp, device_snp)
        payload = {
            "ok": True,
            "frequency_hz": cascade.f.tolist(),
            "port_names": ["P1", "P2"],
            "s": {},
            "port_z": [[50.0, 0.0], [50.0, 0.0]],
        }
        for i in range(2):
            for j in range(2):
                payload["s"][f"{i + 1}_{j + 1}"] = [
                    [v.real, v.imag] for v in cascade.s[:, i, j]
                ]
        return payload

    return _run


class TestRenderChainNetlist:
    def test_content_and_ascii(self, tmp_path):
        m, d = _write_match_snp(tmp_path), _write_device_snp(tmp_path)
        out = tmp_path / "nl" / "chain_netlist.txt"
        aac.render_chain_netlist(m, d, out)
        raw = out.read_bytes()
        assert raw[:3] != b"\xef\xbb\xbf"
        text = raw.decode("ascii")  # 非 ASCII 直接抛异常
        assert "Port:P1  N_IN 0 Num=1 Z=50 Ohm Noise=yes" in text
        assert "Port:P2  N_OUT 0 Num=2 Z=50 Ohm Noise=yes" in text
        assert f'SnP:MN  N_IN N_MID NumPorts=2 File="{m.resolve()}"' in text
        assert f'SnP:DEV  N_MID N_OUT NumPorts=2 File="{d.resolve()}"' in text
        assert "CalcNoise=yes" in text
        assert "{{" not in text

    def test_frequency_intersection_and_min_points(self, tmp_path):
        m = _write_match_snp(tmp_path, n_points=41)
        d = _write_device_snp(tmp_path, n_points=21, band=(1.9e9, 2.5e9))
        out = tmp_path / "nl2" / "chain_netlist.txt"
        aac.render_chain_netlist(m, d, out)
        text = out.read_text("ascii")
        assert "Start=1.9 GHz" in text
        assert "Stop=2.2 GHz" in text
        assert "Lin=21" in text

    def test_disjoint_bands_rejected(self, tmp_path):
        m = _write_match_snp(tmp_path)
        d = _write_device_snp(tmp_path, band=(3.0e9, 4.0e9))
        with pytest.raises(ValueError, match="无交集"):
            aac.render_chain_netlist(m, d, tmp_path / "nl3" / "n.txt")

    def test_non_2port_rejected(self, tmp_path):
        m = _write_match_snp(tmp_path)
        net = skrf.Network(
            frequency=skrf.Frequency(1.8, 2.2, 41, "GHz"),
            s=np.zeros((41, 3, 3), dtype=complex), z0=50,
        )
        p3 = tmp_path / "three.s3p"
        net.write_touchstone(str(p3), form="ri")
        with pytest.raises(ValueError, match="2 端口"):
            aac.render_chain_netlist(m, p3, tmp_path / "nl4" / "n.txt")

    def test_missing_template_raises(self, tmp_path):
        m, d = _write_match_snp(tmp_path), _write_device_snp(tmp_path)
        with pytest.raises(FileNotFoundError):
            aac.render_chain_netlist(m, d, tmp_path / "n.txt",
                                     template_path=tmp_path / "nope.net")


class TestChainRunAndCompare:
    def test_injected_runner_pipeline_consistent(self, tmp_path):
        """注入替身: ADS 侧数据 == 手工口径数据 → 对拍恒等（管线验证）。"""
        m, d = _write_match_snp(tmp_path), _write_device_snp(tmp_path)
        result = aac.run_ads_chain(m, d, tmp_path / "run", ads_runner=_fake_ads_runner(m, d))
        assert result["status"] == "ok"
        ads_net = aac.payload_to_network(result["payload"])
        _, _, manual = aac.chain_manual_reference(m, d)
        cmp_res = aac.compare_chain_with_manual(ads_net, manual, tol_db=0.1)
        assert cmp_res["consistent"] is True
        assert cmp_res["max_abs_db"] < 1e-9

    def test_payload_port_permutation_resolved(self, tmp_path):
        m, d = _write_match_snp(tmp_path), _write_device_snp(tmp_path)
        payload = _fake_ads_runner(m, d)(tmp_path / "x.net")
        payload["port_names"] = ["P2", "P1"]
        s_backup = {k: list(v) for k, v in payload["s"].items()}
        net = aac.payload_to_network(payload)
        # 端口名乱序时按名字对号（P2 在前）: 网络端口 0 应恢复原 S22 行为
        _, _, manual = aac.chain_manual_reference(m, d)
        assert np.max(np.abs(net.s[:, 0, 0] - manual.s[:, 1, 1])) < 1e-12
        assert np.max(np.abs(net.s[:, 1, 0] - manual.s[:, 0, 1])) < 1e-12
        assert s_backup["2_1"]  # 防误删占位

    def test_broken_runner_degrades_honestly(self, tmp_path):
        m, d = _write_match_snp(tmp_path), _write_device_snp(tmp_path)

        def boom(netlist_path):
            raise RuntimeError("simulated ads failure")

        def _run(netlist_path):
            raise FileNotFoundError("no hpeesofsim")

        from rfauto.core.errors import SimulationFailedError

        def _run2(netlist_path):
            raise SimulationFailedError("license blocked")

        # FileNotFoundError / SimulationFailedError → 诚实 error 段（不抛出）
        for runner in (_run, _run2):
            result = aac.run_ads_chain(m, d, tmp_path / "r", ads_runner=runner)
            assert result["status"] == "error"
            assert "error" in result
        # 其他异常不吞（编程错误照常上抛）
        with pytest.raises(RuntimeError):
            aac.run_ads_chain(m, d, tmp_path / "r2", ads_runner=boom)

    def test_perturbed_ads_fails_consistency(self, tmp_path):
        m, d = _write_match_snp(tmp_path), _write_device_snp(tmp_path)
        _, _, manual = aac.chain_manual_reference(m, d)

        def shifted_runner(netlist_path):
            payload = _fake_ads_runner(m, d)(netlist_path)
            payload["s"]["2_1"] = [[v[0] * 1.3, v[1] * 1.3] for v in payload["s"]["2_1"]]
            return payload

        result = aac.run_ads_chain(m, d, tmp_path / "r3", ads_runner=shifted_runner)
        ads_net = aac.payload_to_network(result["payload"])
        cmp_res = aac.compare_chain_with_manual(ads_net, manual, tol_db=0.1)
        assert cmp_res["consistent"] is False

    def test_frequency_ulp_mismatch_is_not_a_disagreement(self, tmp_path):
        """真机实证钉子: ADS 数据集频率比 skrf 网格低 1 ulp 时,
        旧 searchsorted 越位一格把 0 差报成 0.0236 dB; 最近邻对齐须报 ~0。"""
        m, d = _write_match_snp(tmp_path), _write_device_snp(tmp_path)
        _, _, manual = aac.chain_manual_reference(m, d)
        f = np.asarray(manual.f, dtype=float).copy()
        f[::2] = np.nextafter(f[::2], 0.0)       # 偶数点低 1 ulp
        f[1::2] = np.nextafter(f[1::2], np.inf)  # 奇数点高 1 ulp
        ads_net = skrf.Network(frequency=skrf.Frequency.from_f(f, unit="Hz"),
                               s=manual.s.copy(), z0=50)
        cmp_res = aac.compare_chain_with_manual(ads_net, manual, tol_db=0.1)
        assert cmp_res["n_freq"] == manual.frequency.npoints
        assert cmp_res["max_abs_db"] < 1e-12
        assert cmp_res["consistent"] is True

    def test_whole_step_frequency_shift_still_detected(self, tmp_path):
        """最近邻不掩盖真失配: 整格平移的频轴仍报出 斜率×步长 量级差。"""
        m, d = _write_match_snp(tmp_path), _write_device_snp(tmp_path)
        _, _, manual = aac.chain_manual_reference(m, d)
        step = float(manual.f[1] - manual.f[0])
        ads_net = skrf.Network(
            frequency=skrf.Frequency.from_f(np.asarray(manual.f) + step, unit="Hz"),
            s=manual.s.copy(), z0=50,
        )
        cmp_res = aac.compare_chain_with_manual(ads_net, manual, tol_db=0.1)
        assert cmp_res["n_freq"] == manual.frequency.npoints - 1
        assert cmp_res["per_param_max_abs_db"]["S21_db"] > 1e-3


class TestChainGainAtF0:
    def test_gain_family_values(self, tmp_path):
        m, d = _write_match_snp(tmp_path), _write_device_snp(tmp_path)
        _, _, cascade = aac.chain_manual_reference(m, d)
        g = aac.chain_gain_at_f0(cascade, F0_HZ)
        assert g["f0_hz"] == F0_HZ
        assert g["gt_50ohm_db"] == pytest.approx(g["s21_db"], abs=1e-9)
        assert 0.0 <= g["s11_mag"] <= 1.0


class TestRenderLoadpullNetlist:
    def test_deterministic_content(self, tmp_path):
        d = _write_device_snp(tmp_path)
        out1 = tmp_path / "lp1" / "n.net"
        out2 = tmp_path / "lp2" / "n.net"
        aac.render_loadpull_netlist(d, out1, f0_hz=2.4e9, power_dbm=28.0,
                                    z_load=19.9 + 8.5j, harmonic_order=7)
        aac.render_loadpull_netlist(d, out2, f0_hz=2.4e9, power_dbm=28.0,
                                    z_load=19.9 + 8.5j, harmonic_order=7)
        t1, t2 = out1.read_bytes(), out2.read_bytes()
        assert t1 == t2
        text = t1.decode("ascii")
        # 真机实证语法（2026-09-18）: HB 基波/阶数带谐波索引
        assert "HB:HB1 Freq[1]=2.4 GHz Order[1]=7 StatusLevel=2" in text
        # P_1Tone 网表模型名 = Port, 功率/频率带 [1] 索引, 自带源阻抗
        assert "Port:SRC  N_IN 0 Num=1 Z=50 Ohm P[1]=dbmtow(28) Freq[1]=2.4 GHz" in text
        # 复数负载阻抗 re+j*(im)
        assert "Port:P2  N_OUT 0 Num=2 Z=19.9+j*(8.5)" in text
        # aele 测量方程（数据集成块 aele_N.HB1.HB）
        assert "aele Pout_W=0.5*real(N_OUT[1]*conj(N_OUT[1]/(19.9+j*(8.5))));" in text
        assert "Pout_dBm=10*log10(Pout_W)+30; Gain_dB=Pout_dBm-(28);" in text
        assert "Z_RE" not in text and "{{" not in text

    def test_regression_pins_for_real_machine_errors(self, tmp_path):
        """钉住两条真机报错的旧语法不再出现（v0 unexpected '[' / v1 undefined model）。"""
        d = _write_device_snp(tmp_path)
        out = tmp_path / "n.net"
        aac.render_loadpull_netlist(d, out, f0_hz=F0_HZ, power_dbm=20.0, z_load=15 - 8.5j)
        text = out.read_text("ascii")
        assert "Z=[" not in text and "*im" not in text
        assert "P_1Tone:" not in text and "Power=" not in text
        assert "SweepPlan" not in text and "Port:P1" not in text
        # 负虚部靠括号保持可解析
        assert "Z=15+j*(-8.5)" in text
        assert text.count("Port:") == 2
        lines = [ln for ln in text.splitlines() if ln.strip()]
        assert len(lines) == 6

    def test_non_2port_device_rejected(self, tmp_path):
        net = skrf.Network(
            frequency=skrf.Frequency(1.8, 2.2, 41, "GHz"),
            s=np.zeros((41, 4, 4), dtype=complex), z0=50,
        )
        p4 = tmp_path / "four.s4p"
        net.write_touchstone(str(p4), form="ri")
        with pytest.raises(ValueError, match="2 端口"):
            aac.render_loadpull_netlist(p4, tmp_path / "n.net",
                                        f0_hz=F0_HZ, power_dbm=28.0, z_load=50.0)


class TestLoadpullPointReference:
    def test_optimum_point_hits_pmax(self):
        dev = LoadPullDevice(vdd_v=5.0, imax_a=0.2, cout_f=1.2e-12, vknee_v=0.3)
        gamma_opt = dev.optimal_gamma(2.4e9)
        z_opt = dev.optimal_load_impedance(2.4e9)
        ref = aac.loadpull_point_reference(2.4e9, z_opt, dev, drive_dbm=30.0)
        assert ref["power_dbm_cripps"] == pytest.approx(dev.max_power_dbm(), abs=1e-4)
        assert abs(ref["gamma_load"]["re"] - gamma_opt.real) < 1e-5


def _hb_payload_from_waves(device_snp: Path, f0_hz: float, power_dbm: float,
                           z_load: complex, *, with_aele: bool = True) -> dict:
    """离线 HB 替身: 用波代数（独立于内核 transducer_gain_db）合成基波相量 payload。

    ΓS=0 源可用功率 P_av, b2 = S21·a1/(1−S22·ΓL), V_peak = √2·√Z0·b2·(1+ΓL);
    真机数据集形态（HB1.HB 块: mix 0=DC / 1=基波 ...; aele 块标量）同款。
    """
    net = skrf.Network(str(device_snp))
    idx = int(np.argmin(np.abs(net.f - f0_hz)))
    s = net.s[idx]
    z0 = 50.0
    gl = (z_load - z0) / (z_load + z0)
    a1 = np.sqrt(10 ** (power_dbm / 10) * 1e-3)
    b2 = s[1, 0] * a1 / (1 - s[1, 1] * gl)
    v_peak = np.sqrt(2) * np.sqrt(z0) * b2 * (1 + gl)
    p_w = abs(b2) ** 2 * (1 - abs(gl) ** 2)
    harmonics = [{"freq_hz": 0.0, "mix": 0, "nodes": {"N_IN": [0.0, 0.0], "N_OUT": [0.0, 0.0]}},
                 {"freq_hz": f0_hz, "mix": 1,
                  "nodes": {"N_IN": [1.0, 0.0], "N_OUT": [float(v_peak.real), float(v_peak.imag)]}}]
    harmonics += [{"freq_hz": f0_hz * k, "mix": k, "nodes": {"N_IN": [0.0, 0.0], "N_OUT": [0.0, 0.0]}}
                  for k in range(2, 6)]
    meas = {}
    if with_aele:
        p_dbm = 10 * np.log10(p_w * 1e3)
        meas = {"Pout_W": float(p_w), "Pout_dBm": float(p_dbm), "Gain_dB": float(p_dbm - power_dbm)}
    return {"ok": True, "key": "HB1.HB", "harmonics": harmonics, "measurements": meas,
            "keys": ["HB1.HB"] + [f"aele_{i}.HB1.HB" for i in range(len(meas))]}


class TestLoadpullHbPoint:
    @pytest.mark.parametrize("z_load", [50 + 0j, 15 + 8.5j, 15 - 8.5j, 100 - 50j])
    def test_payload_point_matches_closed_form(self, tmp_path, z_load):
        d = _write_device_snp(tmp_path)
        payload = _hb_payload_from_waves(d, F0_HZ, 20.0, z_load)
        pt = aac.hb_payload_to_point(payload, z_load=z_load, power_dbm=20.0)
        ref = aac.loadpull_point_closed_form(d, f0_hz=F0_HZ, power_dbm=20.0, z_load=z_load)
        # aele 值（波代数）vs 节点相量复算（½Re(V·conj(V/Z))）vs 内核 GT 三方一致
        assert pt["source"] == "aele"
        assert abs(pt["pout_self_check_db"]) < 1e-9
        assert pt["pout_dbm"] == pytest.approx(ref["pout_dbm"], abs=1e-9)
        assert pt["gain_db"] == pytest.approx(ref["gt_db"], abs=1e-9)
        assert pt["n_harmonics"] == 6 and pt["f0_hz"] == F0_HZ
        cmp_ = aac.compare_loadpull_point(pt, ref, tol_db=0.05)
        assert cmp_["consistent"] is True and cmp_["abs_delta_db"] < 1e-9

    def test_payload_without_aele_falls_back_to_node(self, tmp_path):
        d = _write_device_snp(tmp_path)
        payload = _hb_payload_from_waves(d, F0_HZ, 20.0, 30 + 20j, with_aele=False)
        pt = aac.hb_payload_to_point(payload, z_load=30 + 20j, power_dbm=20.0)
        ref = aac.loadpull_point_closed_form(d, f0_hz=F0_HZ, power_dbm=20.0, z_load=30 + 20j)
        assert pt["source"] == "node"
        assert pt["pout_dbm"] == pytest.approx(ref["pout_dbm"], abs=1e-9)
        assert pt["gain_db"] == pytest.approx(pt["pout_dbm"] - 20.0, abs=1e-12)

    def test_payload_missing_fundamental_rejected(self):
        payload = {"harmonics": [{"freq_hz": 0.0, "mix": 0, "nodes": {"N_OUT": [0, 0]}}],
                   "measurements": {}}
        with pytest.raises(KeyError, match="mix=1"):
            aac.hb_payload_to_point(payload, z_load=50.0, power_dbm=0.0)

    def test_closed_form_at_50ohm_is_s21_squared(self, tmp_path):
        d = _write_device_snp(tmp_path)
        net = skrf.Network(str(d))
        idx = int(np.argmin(np.abs(net.f - F0_HZ)))
        s21_db = 20 * np.log10(abs(net.s[idx, 1, 0]))
        ref = aac.loadpull_point_closed_form(d, f0_hz=F0_HZ, power_dbm=20.0, z_load=50.0)
        assert ref["gt_db"] == pytest.approx(s21_db, abs=1e-9)
        assert ref["pout_dbm"] == pytest.approx(20.0 + s21_db, abs=1e-9)
        assert ref["gamma_load"] == {"re": 0.0, "im": 0.0}

    def test_closed_form_rejects_non_2port(self, tmp_path):
        net = skrf.Network(frequency=skrf.Frequency(1.8, 2.2, 41, "GHz"),
                           s=np.zeros((41, 4, 4), dtype=complex), z0=50)
        p4 = tmp_path / "four.s4p"
        net.write_touchstone(str(p4), form="ri")
        with pytest.raises(ValueError, match="2 端口"):
            aac.loadpull_point_closed_form(p4, f0_hz=F0_HZ, power_dbm=20.0, z_load=50.0)

    def test_compare_inconsistent_when_off_by_more_than_tol(self):
        cmp_ = aac.compare_loadpull_point({"pout_dbm": 20.3}, {"pout_dbm": 20.0}, tol_db=0.05)
        assert cmp_["consistent"] is False
        assert cmp_["delta_db"] == pytest.approx(0.3)

    def test_run_point_offline_pipeline(self, tmp_path):
        d = _write_device_snp(tmp_path)
        z_load = 15 + 8.5j
        seen = {}

        def _runner(netlist_path: Path) -> dict:
            seen["netlist"] = netlist_path.read_text("ascii")
            return _hb_payload_from_waves(d, F0_HZ, 20.0, z_load)

        res = aac.run_ads_loadpull_point(d, tmp_path / "lp", f0_hz=F0_HZ, power_dbm=20.0,
                                         z_load=z_load, ads_runner=_runner)
        assert res["status"] == "ok"
        assert "Z=15+j*(8.5)" in seen["netlist"]
        ref = aac.loadpull_point_closed_form(d, f0_hz=F0_HZ, power_dbm=20.0, z_load=z_load)
        assert res["point"]["pout_dbm"] == pytest.approx(ref["pout_dbm"], abs=1e-9)
        assert Path(res["netlist"]).name == "loadpull_point.txt"

    def test_run_point_honest_error_on_bad_payload(self, tmp_path):
        d = _write_device_snp(tmp_path)
        res = aac.run_ads_loadpull_point(
            d, tmp_path / "lp", f0_hz=F0_HZ, power_dbm=20.0, z_load=50.0,
            ads_runner=lambda _p: {"harmonics": [], "measurements": {}},
        )
        assert res["status"] == "error"
        assert "mix=1" in res["error"]


class TestRunLnaChainService:
    def test_end_to_end_offline_ok(self, tmp_path):
        m, d = _write_match_snp(tmp_path), _write_device_snp(tmp_path)
        out = tmp_path / "run"
        summary = acs.run_lna_chain(m, d, 2.0, ads_runner=_fake_ads_runner(m, d),
                                    out_dir=out)
        assert summary["status"] == "ok"
        assert summary["verdict"]["ads_vs_manual"] is True
        assert summary["verdict"]["device_unconditionally_stable"] is True
        assert summary["verdict"]["chain_unconditionally_stable"] is True
        assert summary["manual"]["device_conjugate_match"]["gt_max_db"] > 0
        assert (out / "active_chain_summary.json").exists()
        text = (out / "active_chain_summary.json").read_text(encoding="utf-8")
        parsed = json.loads(text)  # 严格 JSON（Infinity 非法值会被拒）
        assert parsed["status"] == "ok"

    def test_noise_section(self, tmp_path):
        m, d = _write_match_snp(tmp_path), _write_device_snp(tmp_path)
        summary = acs.run_lna_chain(
            m, d, 2.0, ads_runner=_fake_ads_runner(m, d),
            noise_params={"fmin_db": 0.5, "gamma_opt_re": 0.3,
                          "gamma_opt_im": 0.2, "rn_norm": 0.4},
        )
        assert summary["noise"]["status"] == "ok"
        assert summary["noise"]["f_at_gamma_opt_db"] == pytest.approx(0.5, abs=1e-9)
        assert summary["noise"]["f_at_50ohm_db"] > 0.5

    def test_ads_failure_reported_not_crash(self, tmp_path):
        m, d = _write_match_snp(tmp_path), _write_device_snp(tmp_path)

        def _run(netlist_path):
            from rfauto.core.errors import SimulationFailedError
            raise SimulationFailedError("license blocked")

        summary = acs.run_lna_chain(m, d, 2.0, ads_runner=_run)
        assert summary["status"] == "ok"  # 手工口径段仍完整
        assert summary["ads"]["status"] == "error"
        assert summary["verdict"]["ads_vs_manual"] is None

    def test_unstable_device_skips_conj_match(self, tmp_path):
        m = _write_match_snp(tmp_path)
        d = _write_device_snp(tmp_path, params=dict(
            gm_s=0.05, rds_ohm=300.0, cgs_f=0.5e-12, cds_f=0.12e-12,
            cgd_f=0.02e-12, rg_ohm=0.0,
        ))
        summary = acs.run_lna_chain(m, d, 2.0, ads_runner=_fake_ads_runner(m, d))
        assert summary["verdict"]["device_unconditionally_stable"] is False
        assert summary["manual"]["device_conjugate_match"]["status"] == "unavailable"


class TestRunPaLoadpullService:
    def test_loadpull_full_verdict(self, tmp_path):
        summary = acs.run_pa_loadpull(
            5.0, 0.2, 1.2, 2.4, n_grid=61, out_dir=tmp_path / "lp",
        )
        assert summary["status"] == "ok"
        assert summary["verdict"]["loadpull_plausible"] is True
        assert summary["verdict"]["n_contours"] == 3
        assert summary["optimum"]["gamma_dist"] < 0.05
        assert abs(summary["device"]["max_power_dbm"] - 26.721) < 0.01
        assert (tmp_path / "lp" / "loadpull_summary.json").exists()
        parsed = json.loads((tmp_path / "lp" / "loadpull_summary.json").read_text("utf-8"))
        assert parsed["plausibility"]["plausible"] is True

    def test_with_device_snp_gain_section(self, tmp_path):
        d = _write_device_snp(tmp_path)
        summary = acs.run_pa_loadpull(5.0, 0.2, 1.2, 2.0, n_grid=61, device_snp=d)
        assert summary["gain"]["device_stability"]["unconditionally_stable"] is True
        assert summary["gain"]["gt_max_db"] > 0

    def test_ads_point_netlists_rendered(self, tmp_path):
        d = _write_device_snp(tmp_path)
        summary = acs.run_pa_loadpull(
            5.0, 0.2, 1.2, 2.4, n_grid=41, backoff_db=(2.0,),
            device_snp=d, out_dir=tmp_path / "lp2", render_ads_points=True,
        )
        netlists = summary["ads_point_netlists"]
        assert len(netlists) > 0
        for p in netlists:
            assert Path(p).exists()
            assert "{{" not in Path(p).read_text("ascii")


class TestSyntheticDeviceSparams:
    def test_json_shape_and_stability(self):
        out = acs.synthetic_device_sparams(20.0, 300.0, 0.5, 0.12, 2.0)
        assert out["stability"]["unconditionally_stable"] is True
        assert len(out["s"]) == 2 and len(out["s"][0]) == 2
        json.dumps(out)  # 可序列化

    def test_unstable_flagged(self):
        out = acs.synthetic_device_sparams(50.0, 300.0, 0.5, 0.12, 2.0,
                                           cgd_pf=0.02, rg_ohm=0.0)
        assert out["stability"]["unconditionally_stable"] is False
