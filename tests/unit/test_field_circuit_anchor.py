"""WP4.3 场路协同回归锚离线单测（§10.22 补强16）。

覆盖链路四段：
- 闭式 branchline 基准（教科书值/无源性/互易性）与 Touchstone 往返；
- skrf 参考级联（f0 幅相、不对称设计对端口顺序的敏感度）；
- ADS 级联网表渲染 + payload→网络恢复（含端口名乱序）；
- FSV 裁判（同曲线=Ex、扰动劣化）、D13 宏模型桥（重建对拍 + 级联替身）、
  反标注一致性、run_field_circuit_anchor 编排（含诚实降级路径）。

离线纪律：本文件不跑 hpeesofsim——"ADS 侧"用注入 ads_runner 的合成
payload，只验管线；真机 FSV ≥VG 验收由 tests/real_edt/test_field_circuit_anchor_real.py
与 runs/ 证据承载。
"""

import json

import numpy as np
import pytest
import skrf

from rfauto.linkage import field_circuit_anchor as fca


def _make_touchstone(tmp_path, n_points=401, loss=None):
    kw = {} if loss is None else {"loss_np_per_qw": loss}
    return fca.build_branchline_touchstone(
        tmp_path / "branchline.s4p", n_points=n_points, **kw
    )


def _payload_from_network(net, port_names=("P1", "P2")):
    """把 skrf 2 端口网络包成 ADS .ds 探针 payload 形态（离线管线替身）。

    网络端口序即数据集端口序（port_names[k] 是网络端口 k 的名字）。
    """
    names = list(port_names)
    return {
        "ok": True,
        "frequency_hz": np.asarray(net.f, dtype=float).tolist(),
        "port_names": names,
        "port_z": [[50.0, 0.0]] * len(names),
        "s": {
            f"{a + 1}_{b + 1}": [[complex(v).real, complex(v).imag] for v in net.s[:, a, b]]
            for a in range(len(names))
            for b in range(len(names))
        },
    }


class TestBranchlineClosedForm:
    def test_lossless_f0_textbook_values(self):
        """无耗极限（loss=0）在 f0 处逐项对齐教科书：等分/-90°/隔离/匹配。"""
        f0 = 2.4e9
        s = fca.branchline_smatrix([f0], loss_np_per_qw=0.0)[0]
        assert abs(s[0, 0]) < 1e-10  # S11 匹配
        assert abs(s[3, 0]) < 1e-10  # S41 隔离
        assert abs(abs(s[1, 0]) - 1 / np.sqrt(2)) < 1e-12  # S21 直通等分
        assert abs(abs(s[2, 0]) - 1 / np.sqrt(2)) < 1e-12  # S31 耦合等分
        phase_diff = np.angle(s[1, 0] / s[2, 0])  # wrap 安全的相位差
        assert abs(phase_diff - (np.pi / 2)) < 1e-12  # 直通超前耦合 90°（直通滞后输入 90°、耦合 180°）

    def test_lossy_f0_realistic_magnitudes(self):
        """缺省损耗版 f0 处：等分保留、匹配/隔离有限（真实微带量级）。"""
        f0 = 2.4e9
        s = fca.branchline_smatrix([f0])[0]
        db = [20 * np.log10(abs(s[i, 0])) for i in range(4)]
        assert -3.7 < db[1] < -3.3  # S21
        assert -3.8 < db[2] < -3.3  # S31
        assert db[0] < -25.0  # S11
        assert db[3] < -25.0  # S41

    def test_passive_and_reciprocal_across_band(self):
        freq = np.linspace(1.6e9, 3.2e9, 61)
        s = fca.branchline_smatrix(freq)
        sigma_max = np.max(np.linalg.svd(s, compute_uv=False))
        assert sigma_max < 1.0 + 1e-9  # 严格无源（有耗版不压无源性边界）
        for k in range(freq.size):
            assert np.allclose(s[k], s[k].T, atol=1e-12)  # 互易

    def test_touchstone_roundtrip(self, tmp_path):
        snp = _make_touchstone(tmp_path, n_points=41)
        net = skrf.Network(str(snp))
        assert net.nports == 4
        assert net.frequency.npoints == 41
        ref = fca.branchline_smatrix(np.asarray(net.f))
        assert np.allclose(np.abs(net.s), np.abs(ref), rtol=2e-3, atol=2e-4)


class TestSkrfReferenceCascade:
    def test_f0_magnitude_and_phase(self, tmp_path):
        snp = _make_touchstone(tmp_path)
        ref = fca.skrf_reference_cascade(snp)
        k = int(np.searchsorted(ref.f, 2.4e9))
        block = fca.branchline_smatrix([2.4e9])[0]
        # 匹配无耗线不改幅度：合成 |S21| = branchline |S21| @f0
        assert abs(abs(ref.s[k, 1, 0]) - abs(block[1, 0])) < 1e-12
        # 相位 = branchline(-90°) - θ_in(90°) - θ_out(45°) → +135°（mod 360）
        assert abs(np.angle(ref.s[k, 1, 0]) - np.radians(135)) < 1e-9

    def test_line_phase_semantics(self, tmp_path):
        """电长度语义钉死：θ_out 差 Δ 时 S21 相位差恰为 −Δ（匹配级联的
        dB 幅度不变，错位只能从相位看出——相位护栏存在的物理依据）。"""
        snp = _make_touchstone(tmp_path)
        ref = fca.skrf_reference_cascade(snp)
        shifted = fca.skrf_reference_cascade(snp, theta_out_deg=10.0)
        k = int(np.searchsorted(ref.f, 2.4e9))
        d_phase = np.angle(shifted.s[k, 1, 0] / ref.s[k, 1, 0])
        assert abs(np.degrees(d_phase) - 35.0) < 1e-9  # −(10−45)° = +35°

    def test_line_impedance_mismatch_degrades_fsv(self, tmp_path):
        """线阻抗错配（50→40Ω）产生反射，dB 幅度特征改变，FSV 离开 Ex。"""
        snp = _make_touchstone(tmp_path)
        ref = fca.skrf_reference_cascade(snp)
        bad = fca.skrf_reference_cascade(snp, z_line=40.0)
        report = fca.fsv_cascade_report(bad, ref)
        assert report["worst_gdm_grade"] != "Ex"
        assert report["params"]["S21"]["gdm_mean"] > 0.02

    def test_rejects_non_4port(self, tmp_path):
        f = skrf.Frequency(1.6, 3.2, 41, "GHz")
        net2 = skrf.Network(frequency=f, s=np.zeros((41, 2, 2), complex), z0=50)
        with pytest.raises(ValueError, match="4 端口"):
            fca.compose_reference_cascade(net2)


class TestRenderCascadeNetlist:
    def test_netlist_content(self, tmp_path):
        snp = _make_touchstone(tmp_path)
        out = fca.render_cascade_netlist(snp, tmp_path / "nl.txt")
        text = out.read_text(encoding="ascii")
        assert "TLIN:TLIN1  N_A N_B  Z=50 Ohm E=90 F=2.4 GHz" in text
        assert "TLIN:TLIN2  N_C N_D  Z=50 Ohm E=45 F=2.4 GHz" in text
        assert "SnP:SNP1  N_B N_C N_T1 N_T2 NumPorts=4" in text
        assert f'File="{snp.resolve()}"' in text
        assert "Port:P1  N_A 0 Num=1" in text
        assert "Port:P2  N_D 0 Num=2" in text
        assert "Port:P3  N_T1 0 Num=3" in text  # 终止口（S 参数定义即其余端口匹配）
        assert "Port:P4  N_T2 0 Num=4" in text
        assert "Term:" not in text  # hpeesofsim 无 Term 网表模型（真机实证）
        assert "Lin=401" in text
        assert "{{" not in text  # 占位符全部替换

    def test_rejects_wrong_port_count(self, tmp_path):
        f = skrf.Frequency(1.6, 3.2, 41, "GHz")
        net2 = skrf.Network(frequency=f, s=np.zeros((41, 2, 2), complex), z0=50)
        snp2 = tmp_path / "two.s2p"
        net2.write_touchstone(str(snp2), form="db")
        with pytest.raises(ValueError, match="4 端口"):
            fca.render_cascade_netlist(snp2, tmp_path / "nl.txt")


class TestCompositeNetworkFromPayload:
    def test_roundtrip_identity(self, tmp_path):
        snp = _make_touchstone(tmp_path)
        ref = fca.skrf_reference_cascade(snp)
        payload = _payload_from_network(ref)
        got = fca.composite_network_from_payload(payload)
        assert np.max(np.abs(got.s - ref.s)) < 1e-12

    def test_port_name_permutation_resolved(self, tmp_path):
        """port_names=['P2','P1']（数据集序 ≠ 电路序）时按名字正确还原。"""
        snp = _make_touchstone(tmp_path)
        ref = fca.skrf_reference_cascade(snp)
        # 数据集端口 1 = P2、端口 2 = P1 的 payload（S 键按数据集序）
        s = ref.s
        payload = {
            "ok": True,
            "frequency_hz": np.asarray(ref.f, dtype=float).tolist(),
            "port_names": ["P2", "P1"],
            "port_z": [[50.0, 0.0], [50.0, 0.0]],
            "s": {
                "1_1": [[v.real, v.imag] for v in s[:, 1, 1]],
                "1_2": [[v.real, v.imag] for v in s[:, 1, 0]],
                "2_1": [[v.real, v.imag] for v in s[:, 0, 1]],
                "2_2": [[v.real, v.imag] for v in s[:, 0, 0]],
            },
        }
        got = fca.composite_network_from_payload(payload)
        assert np.max(np.abs(got.s - ref.s)) < 1e-12

    def test_missing_response_raises(self, tmp_path):
        snp = _make_touchstone(tmp_path)
        ref = fca.skrf_reference_cascade(snp)
        payload = _payload_from_network(ref)
        del payload["s"]["2_1"]
        with pytest.raises(KeyError, match="2_1"):
            fca.composite_network_from_payload(payload)


class TestFsvCascadeReport:
    def test_identical_is_excellent_and_phase_ok(self, tmp_path):
        snp = _make_touchstone(tmp_path)
        ref = fca.skrf_reference_cascade(snp)
        report = fca.fsv_cascade_report(ref, ref)
        assert report["at_least_vg"] is True
        assert report["worst_gdm_grade"] == "Ex"
        assert report["phase_consistent"] is True
        for v in report["params"].values():
            assert v["gdm_mean"] < 1e-9

    def test_phase_only_error_caught_by_guard_not_fsv(self, tmp_path):
        """θ_out 45°→10°：dB 幅度逐点不变（FSV 仍 Ex），相位护栏必须抓到
        （+35° 错位）——这是护栏存在性的回归钉。"""
        snp = _make_touchstone(tmp_path)
        ref = fca.skrf_reference_cascade(snp)
        shifted = fca.skrf_reference_cascade(snp, theta_out_deg=10.0)
        report = fca.fsv_cascade_report(shifted, ref)
        assert report["at_least_vg"] is True  # FSV(dB) 对纯相位错误盲
        assert report["phase_consistent"] is False
        # 电长度随频率线性缩放：最大错位在带边缘 = 35°·(3.2/2.4)
        assert report["phase_checks"]["S21"]["max_abs_deg"] == pytest.approx(
            35.0 * 3.2 / 2.4, abs=1e-6,
        )

    def test_phase_undecidable_near_null(self, tmp_path):
        """|S| 全带低于幅度地板（深零点）→ 相位不可判定记 None，不谎报。"""
        f = skrf.Frequency(1.6, 3.2, 41, "GHz")
        tiny = np.full((41, 2, 2), 1e-9, dtype=complex)
        net = skrf.Network(frequency=f, s=tiny, z0=50)
        report = fca.fsv_cascade_report(net, net)
        assert report["phase_checks"]["S21"]["max_abs_deg"] is None
        assert report["phase_consistent"] is None


class TestMacromodelBridge:
    def test_fit_reconstruction_and_cascade(self, tmp_path):
        snp = _make_touchstone(tmp_path)
        fit = fca.macromodel_bridge(snp)
        assert fit["ok"] is True
        assert fit["reconstruction_verified"] is True
        assert fit["reconstruction_max_dev"] <= 1e-9
        assert fit["passivity"]["after"]["passive_in_band"] is True
        assert not fit["passivity"]["enforced"]  # (2,4) 定阶不触发 enforce
        # 宏模型替身重走级联：模型级联 vs 参考级联 FSV ≥VG
        model_cascade = fca.compose_reference_cascade(fit["model_network"])
        ref = fca.skrf_reference_cascade(snp)
        report = fca.fsv_cascade_report(model_cascade, ref)
        assert report["at_least_vg"] is True


class TestBackAnnotationConsistency:
    def test_default_rules_consistent(self):
        report = fca.check_back_annotation_consistency()
        assert report["consistent"] is True
        for rule in report["rules"].values():
            assert rule["ok"] is True
            for row in rule["samples"]:
                assert row["rel_err"] <= fca.BACK_ANNOTATION_RTOL
                assert row["round_trip_rel_err"] <= fca.BACK_ANNOTATION_RTOL

    def test_unknown_transform_raises(self):
        bad = [{
            "ads_component": "x", "hfss_variable": "y",
            "transform": "bogus", "reference": {"x": 1.0, "y": 2.0},
        }]
        with pytest.raises(ValueError, match="未知变换"):
            fca.check_back_annotation_consistency(bad)


class TestRunAnchorOffline:
    def test_end_to_end_offline_ok(self, tmp_path):
        """注入合成 payload（与参考同源）：只验管线，FSV 数字不作裁判。"""
        snp = _make_touchstone(tmp_path)
        ref = fca.skrf_reference_cascade(snp)
        summary = fca.run_field_circuit_anchor(
            snp, tmp_path / "out",
            ads_runner=lambda nl: _payload_from_network(ref),
        )
        assert summary["ok"] is True
        assert summary["ads"]["status"] == "ok"
        assert summary["fsv"]["at_least_vg"] is True
        assert summary["macromodel"]["ok"] is True
        assert summary["macromodel"]["cascade_fsv"]["at_least_vg"] is True
        assert summary["back_annotation"]["consistent"] is True
        report = json.loads((tmp_path / "out" / "anchor_report.json").read_text(encoding="utf-8"))
        assert report["ok"] is True

    def test_ads_failure_degrades_honestly(self, tmp_path):
        """ADS 段失败 → status=error、ok=False，报告仍落盘（不掩盖）。"""
        snp = _make_touchstone(tmp_path)

        def boom(netlist):
            raise RuntimeError("hpeesofsim 模拟失败")

        summary = fca.run_field_circuit_anchor(snp, tmp_path / "out", ads_runner=boom)
        assert summary["ok"] is False
        assert summary["ads"]["status"] == "error"
        assert "hpeesofsim 模拟失败" in summary["ads"]["error"]
        assert summary["fsv"]["status"] == "skipped"
        assert (tmp_path / "out" / "anchor_report.json").exists()

    def test_missing_source_fails_without_crash(self, tmp_path):
        summary = fca.run_field_circuit_anchor(
            tmp_path / "nope.s4p", tmp_path / "out",
            ads_runner=lambda nl: {},
        )
        assert summary["ok"] is False
        assert "不存在" in summary["source"]["error"]

    def test_macromodel_skippable(self, tmp_path):
        snp = _make_touchstone(tmp_path)
        ref = fca.skrf_reference_cascade(snp)
        summary = fca.run_field_circuit_anchor(
            snp, tmp_path / "out", with_macromodel=False,
            ads_runner=lambda nl: _payload_from_network(ref),
        )
        assert summary["macromodel"]["status"] == "skipped"
        assert summary["ok"] is True
