"""DP-4 P3 互耦档编排离线判据（2026-09-24）：manifest 合成回归 + Γ_act 端到端
合成例 + rotation far_field 透传（stub 子进程全链）+ σmax 装配门。

判据对应 runs/df6_dp4p3/criteria.md：J9（rotation 透传）、J10（manifest 合成
回归，#320 显式引用/缺件如实 skipped）、J11（Γ_act 定义式逐位/合成 S→manifest→
superposition→coupled_tier_solve(launch=False) 全链）、J12（两档路由注入）。
J4 真机门（σmax≤1.005 硬门）在合成侧只钉判据逻辑（幺正 S→PASS；放大→FAIL），
真机数字不采信、不凑绿（criteria.md 预声明）。

全程零真机、零网络：rotation 真跑路径以 monkeypatch subprocess 桩替——
桩按轮号写合成 9 列 sparams.csv + farfield3d_cplx.csv，装配/断点缓存/EEP
判读全链照常走真实代码。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters import openems_templates as ot
from rfauto.core.array_scan import (
    active_reflection,
    reflection_from_impedance,
    scan_impedance,
)
from rfauto.core.farfield import write_farfield_3d_cplx_csv
from rfauto.service.array_service import (
    EEP_SIGMA_MAX_LIMIT,
    collect_eep_manifest,
    coupled_tier_solve,
)

F0 = 5.8
FREQ_GHZ = np.linspace(5.55, 6.05, 11)
C_MM_GHZ = 299.792458
#: 合成 EEP 角网格（上半球即可覆盖判据面；闭式单元域 θ≤90°）
TH = np.arange(0.0, 91.0, 30.0)
PH = np.arange(0.0, 360.0, 45.0)


# ─── 合成 fixture ────────────────────────────────────────────────────────────

def _synthetic_smatrix(n: int = 4, seed: int = 7, unitary: bool = False):
    """合成 N×N S（互易对称；unitary=True 时 QR 幺正化→无耗 σmax≡1）。"""
    rng = np.random.default_rng(seed)
    a = (rng.standard_normal((n, n)) + 1j * rng.standard_normal((n, n))) * 0.12
    s = a + a.T
    np.fill_diagonal(s, 0.35 - 0.08j)
    if unitary:
        q, r = np.linalg.qr(rng.standard_normal((n, n))
                            + 1j * rng.standard_normal((n, n)))
        s = q * (np.diag(r) / np.abs(np.diag(r)))
    return s


def _synthetic_eep(template: str, params: dict, port: int):
    """合成 EEPₙ(θ,φ) = 闭式贴片单元 × 位置相位 exp(j·k0·r̂·rₙ)（J3 口径，
    元间距/位置取模板标称行主序——与 _eep_layout 同序，见 test_eep_templates）。"""
    from rfauto.core.array_synthesis import patch_element_field

    lam0_mm = C_MM_GHZ / F0
    sx = float(params["spacing_x_mm"])
    if template == "patch_eep_1x4":
        pos = [((i - 1.5) * sx, 0.0) for i in range(4)]
    else:
        sy = float(params["spacing_y_mm"])
        pos = [(sx * (mx - 0.5), sy * (my - 0.5))
               for mx in (-0.5, 0.5) for my in (-0.5, 0.5)]
    th = TH[:, None]
    ph = PH[None, :]
    et = np.asarray(patch_element_field(
        th, ph, len_mm=float(params["elem_len_mm"]),
        width_mm=float(params["elem_w_mm"]), freq_ghz=F0, axis="y",
        component="theta"), dtype=float)
    ep = np.asarray(patch_element_field(
        th, ph, len_mm=float(params["elem_len_mm"]),
        width_mm=float(params["elem_w_mm"]), freq_ghz=F0, axis="y",
        component="phi"), dtype=float)
    x, y = pos[port - 1]
    # 全局原点在阵面中心 (0, 20mm)；θ 绕 z、φ 自 x——r̂·rₙ = sinθ·(x·cosφ +
    # y·sinφ) + 0（z=0）；与 core.array_scan.position_phase 同记账口径
    rdot = np.sin(np.radians(th)) * (x * np.cos(np.radians(ph))
                                     + y * np.sin(np.radians(ph)))
    phase = np.exp(1j * 2.0 * np.pi / lam0_mm * rdot)
    return (et + ep) * phase


def make_round_fixture(root: Path, template: str = "patch_eep_2x2",
                       s_matrix=None, n_ports: int = 4,
                       write_meta: bool = True,
                       skip_curve_ports: tuple[int, ...] = ()) -> dict:
    """合成 rotation run fixture：p1..pN 轮列 sparams.csv + farfield3d_cplx.csv。

    s_matrix：缺省合成（互易近邻耦合，频不变，逐频广播）；返回
    {"freq_ghz", "s_matrix"(nf,N,N), "eeps"(缺省端口为 None)}。"""
    nom = dict(ot.EEP_NOMINAL[template])
    if s_matrix is None:
        s_matrix = _synthetic_smatrix(n_ports)
    s_full = np.broadcast_to(np.asarray(s_matrix, dtype=complex),
                             (len(FREQ_GHZ), n_ports, n_ports)).copy()
    eeps: list = [None] * n_ports
    for k in range(1, n_ports + 1):
        wk = root / f"p{k}"
        wk.mkdir(parents=True, exist_ok=True)
        rows = [["freq_hz"] + [f"re_S{i + 1}" for i in range(n_ports)]
                + [f"im_S{i + 1}" for i in range(n_ports)]]
        rows[0] = (["freq_hz"]
                   + [x for i in range(n_ports)
                      for x in (f"re_S{i + 1}", f"im_S{i + 1}")])
        with open(wk / "sparams.csv", "w", encoding="utf-8") as fh:
            fh.write(",".join(rows[0]) + "\n")
            for fi, fv in enumerate(FREQ_GHZ):
                vals = [f"{fv * 1e9:.6f}"]
                for i in range(n_ports):
                    c = s_full[fi, i, k - 1]
                    vals += [f"{c.real:.12e}", f"{c.imag:.12e}"]
                fh.write(",".join(vals) + "\n")
        if k not in skip_curve_ports:
            eep = _synthetic_eep(template, nom, k)
            eeps[k - 1] = eep
            write_farfield_3d_cplx_csv(
                wk / "farfield3d_cplx.csv", TH, PH,
                eep, np.zeros_like(eep))
        if write_meta:
            (wk / "farfield_meta.json").write_text(json.dumps({
                "ok": True, "template": template, "eep": True,
                "excite_port": k, "f_res_ghz": F0, "f_res_mode": "fixed_F0",
                "grid_theta_deg": list(TH), "grid_phi_deg": list(PH),
            }, ensure_ascii=False), encoding="utf-8")
    return {"freq_ghz": FREQ_GHZ, "s_matrix": s_full, "eeps": eeps,
            "nominal": nom}


# ─── J10：collect_eep_manifest 合成回归 ─────────────────────────────────────

class TestCollectEepManifest:
    def test_work_root_layout_default_refs(self, tmp_path):
        make_round_fixture(tmp_path)
        man = collect_eep_manifest([str(tmp_path)], 4)
        assert man["ok"] is True and man["layout"] == "work_root"
        assert man["n_skipped"] == 0
        for k in ("1", "2", "3", "4"):
            entry = man["ports"][k]
            assert entry["exists"] is True
            assert entry["curve_ref"] == f"p{k}/farfield3d_cplx.csv"
            assert entry["sha256"] and len(entry["sha256"]) == 64
            assert entry["rows"] == len(TH) * len(PH)
            assert entry["meta"]["excite_port"] == int(k)
            assert entry["meta"]["f_res_mode"] == "fixed_F0"
            assert man["rounds"][k]["exists"] is True

    def test_per_port_layout_and_explicit_refs(self, tmp_path):
        make_round_fixture(tmp_path)
        man = collect_eep_manifest(
            [str(tmp_path / f"p{k}") for k in range(1, 5)], 4,
            curve_refs={2: "farfield3d_cplx.csv"})
        assert man["ok"] is True and man["layout"] == "per_port"
        assert man["ports"]["2"]["curve_ref"] == "farfield3d_cplx.csv"
        assert man["n_skipped"] == 0

    def test_missing_port_skipped_honestly(self, tmp_path):
        make_round_fixture(tmp_path, skip_curve_ports=(3,))
        man = collect_eep_manifest([str(tmp_path)], 4)
        assert man["n_skipped"] == 1
        sk = man["skipped"][0]
        assert sk["port"] == 3 and sk["kind"] == "eep_curve"
        assert "不存在" in sk["reason"]
        assert man["ports"]["3"]["exists"] is False
        assert "sha256" not in man["ports"]["3"]   # 不猜不补

    def test_contract_errors(self, tmp_path):
        make_round_fixture(tmp_path)
        with pytest.raises(ValueError, match="run_dirs 长度须为 1"):
            collect_eep_manifest([str(tmp_path)] * 2, 4)
        bad = collect_eep_manifest([str(tmp_path / "nope")], 4)
        assert bad["ok"] is False and "不存在" in bad["error"]


# ─── J11：Γ_act 端到端合成例 + σmax 门逻辑 ───────────────────────────────────

class TestCoupledTierSolveSynthetic:
    def _request(self, root: Path, **kw):
        req = {"template": "patch_eep_2x2", "work_root": str(root),
               "launch": False, "f0_ghz": F0}
        req.update(kw)
        return req

    def test_gamma_act_matches_definition_bitwise(self, tmp_path):
        fix = make_round_fixture(tmp_path)
        res = coupled_tier_solve(self._request(tmp_path))
        assert res["ok"] is True, res.get("error")
        r = res["result"]
        a = np.asarray([complex(p[0], p[1]) for p in r["excitations"]],
                       dtype=complex)
        # S 载体=服务自身 s_matrix_f0（CSV 载体 12 位有效数字——与判读同源，
        # 逐位口径；对合成地面真值的保真度另查 ≤1e-10）
        s0 = np.asarray([complex(p[0], p[1]) for p in r["s_matrix_f0"]],
                        dtype=complex).reshape(4, 4)
        assert np.allclose(s0, fix["s_matrix"][r["f0_index"]],
                           rtol=0, atol=1e-10)
        gamma = active_reflection(s0, a)
        got = np.asarray([complex(p[0], p[1]) for p in r["gamma_act_f0"]],
                         dtype=complex)
        assert np.array_equal(got, gamma)   # 同核同载体 → 逐位
        # 定义式显式循环（行=观测口 n、列=激励口 m）
        for n in range(4):
            expect = sum(s0[n, m] * a[m] / a[n] for m in range(4))
            assert got[n] == pytest.approx(expect, rel=1e-14)
        # Z↔Γ 往返 ≤1e-12
        z0 = r["z0_ohm"]
        for n in range(4):
            z_pair = r["z_scan_f0"][n]
            if z_pair is None:
                continue
            gamma_rt = reflection_from_impedance(scan_impedance(
                gamma[n:n + 1], z0), z0)[0]
            assert gamma_rt == pytest.approx(gamma[n], rel=1e-12)

    def test_sigma_gate_pass_on_unitary_fail_on_scaled(self, tmp_path):
        make_round_fixture(tmp_path, s_matrix=_synthetic_smatrix(unitary=True))
        res = coupled_tier_solve(self._request(tmp_path))
        gate = res["result"]["sigma_max_gate"]
        assert gate["pass"] is True
        assert gate["max"] <= EEP_SIGMA_MAX_LIMIT
        # 放大 1.01× → 无源性破坏 → 门红如实（不凑绿）
        s_bad = _synthetic_smatrix(unitary=True) * 1.01
        root2 = tmp_path / "scaled"
        make_round_fixture(root2, s_matrix=s_bad)
        res2 = coupled_tier_solve(self._request(root2))
        gate2 = res2["result"]["sigma_max_gate"]
        assert gate2["pass"] is False
        assert gate2["max"] > EEP_SIGMA_MAX_LIMIT

    def test_pattern_superposition_and_positions(self, tmp_path):
        fix = make_round_fixture(tmp_path)
        res = coupled_tier_solve(self._request(tmp_path))
        r = res["result"]
        a = np.asarray([complex(p[0], p[1]) for p in r["excitations"]],
                       dtype=complex)
        # 侧射（scan 0°）：叠加 vs 直算（fixture 合成 EEP）全网格一致
        f_direct = sum(a[k] * fix["eeps"][k] for k in range(4))
        f_db = np.asarray(r["pattern"]["f_db"], dtype=float)
        pdb_direct = 20 * np.log10(np.abs(f_direct)
                                   / np.abs(f_direct).max() + 1e-300)
        assert np.allclose(f_db, pdb_direct, atol=1e-9)
        # 峰值解码（it/ip 行主序）与独立 argmax 逐位一致
        flat = int(np.argmax(np.abs(f_direct)))
        th_arr = np.asarray(r["pattern"]["theta_deg"])
        ph_arr = np.asarray(r["pattern"]["phi_deg"])
        assert r["pattern"]["peak_theta_deg"] == \
            pytest.approx(th_arr[flat // ph_arr.size], abs=1e-12)
        assert r["pattern"]["peak_phi_deg"] == \
            pytest.approx(ph_arr[flat % ph_arr.size], abs=1e-12)
        # 天顶格绝对账：EEP 天顶模=1（闭式归一）×位置相位 1 → |F|=|Σaₙ|
        direct0 = sum(a[k] * fix["eeps"][k][0, 0] for k in range(4))
        assert abs(direct0) == pytest.approx(abs(a.sum()), rel=1e-12)
        # 位置（mm）行主序与模板布局一致（端口次序契约；服务层为相对阵面
        # 中心的平移不变坐标，模板布局为板面绝对坐标——居中后逐位一致）
        lay = ot._eep_layout("patch_eep_2x2", dict(ot.EEP_NOMINAL["patch_eep_2x2"]))
        got_pos = np.asarray(r["layout"]["positions_mm"], dtype=float)
        want_pos = np.asarray(lay["elements_mm"], dtype=float)
        assert np.allclose(got_pos - got_pos.mean(axis=0),
                           want_pos - want_pos.mean(axis=0), atol=1e-9)
        # J4b 报告门在场（gate=None，报告统计可分辨）
        cmp13 = r["fast_tier_compare"]
        assert cmp13["gate"] is None and cmp13["n_points"] > 0
        assert "dev_db_median" in cmp13 and "J4b" in cmp13["criteria"]

    def test_missing_curve_honest_and_partial(self, tmp_path):
        make_round_fixture(tmp_path, skip_curve_ports=(4,))
        res = coupled_tier_solve(self._request(tmp_path))
        assert res["ok"] is False
        assert "缺失端口 [4]" in res["error"]
        assert "#320" in res["error"]
        # allow_partial：Γ_act 可产出、方向图不可叠加（如实 partial）
        res2 = coupled_tier_solve(self._request(tmp_path, allow_partial=True))
        assert res2["ok"] is True
        r2 = res2["result"]
        assert r2["pattern"] is None
        assert r2["partial"]["missing_ports"] == [4]
        assert r2["gamma_act_f0"] is not None

    def test_route_via_array_pattern_injection(self, tmp_path):
        """P2 注入契约：array_pattern 的 coupled 路径返回
        {"ok": True, "result": coupled_solver(request)}——solver 返回值整体
        作为 result（P2 定义，零改动）。"""
        make_round_fixture(tmp_path)
        from rfauto.service.array_service import array_pattern

        req = self._request(tmp_path)
        req["tier"] = "coupled"
        res = array_pattern(req, coupled_solver=coupled_tier_solve)
        assert res["ok"] is True
        assert res["result"]["ok"] is True
        assert res["result"]["result"]["tier"] == "coupled"


# ─── J9：rotation far_field 透传（stub 子进程全链）───────────────────────────

_S9_HEADER = ("freq_hz,re_S11,im_S11,re_S21,im_S21,re_S31,im_S31,"
              "re_S41,im_S41")


def _fake_subprocess_run(s_matrix, freq_ghz, far_field_marker: bool):
    """stub subprocess.run：按 cwd 轮号 k 写合成第 k 列 9 列 CSV（+ff 产物）。"""
    import subprocess as _sp

    s_full = np.broadcast_to(np.asarray(s_matrix, dtype=complex),
                             (len(freq_ghz), 4, 4))

    def _run(cmd, capture_output, text, timeout, cwd):
        wk = Path(cwd)
        k = int(wk.name[1:])
        lines = [_S9_HEADER]
        col = s_full[:, :, k - 1]
        for fi, fv in enumerate(freq_ghz):
            vals = [f"{fv * 1e9:.6f}"]
            for i in range(4):
                c = col[fi, i]
                vals += [f"{c.real:.12e}", f"{c.imag:.12e}"]
            lines.append(",".join(vals))
        (wk / "sparams.csv").write_text("\n".join(lines) + "\n",
                                        encoding="utf-8")
        script = (wk / "simulation.py").read_text(encoding="utf-8")
        assert ("CreateNF2FFBox" in script) == far_field_marker
        if far_field_marker:
            write_farfield_3d_cplx_csv(
                wk / "farfield3d_cplx.csv", np.array([0.0, 45.0]),
                np.array([0.0, 90.0]),
                np.array([[1 + 0j, 0.5j], [0.5, 0.1 - 0.1j]]),
                np.zeros((2, 2), dtype=complex))
        return _sp.CompletedProcess(cmd, 0, stdout="", stderr="")

    return _run


class TestRotationFarFieldPassthrough:
    def test_far_field_true_passthrough_and_assembly(self, tmp_path, monkeypatch):
        import rfauto.adapters.openems_rotation as rot

        s_gt = _synthetic_smatrix()
        monkeypatch.setattr(
            rot.subprocess, "run",
            _fake_subprocess_run(s_gt, FREQ_GHZ, far_field_marker=True))
        res = rot.solve_smatrix_openems(
            tmp_path, template="patch_eep_2x2",
            params=dict(ot.EEP_NOMINAL["patch_eep_2x2"]),
            freq_range_ghz=(5.55, 6.05), n_ports=4,
            far_field=True, resume=False)
        assert res["ok"] is True, res.get("errors")
        assert res["far_field"] is True
        # 装配矩阵与地面真值逐位一致（轮列槽位语义：S[i,k]=第 k 激励列）
        got = np.asarray(res["s_params"], dtype=complex)
        assert np.allclose(got, s_gt, rtol=0, atol=1e-12)
        assert all(Path(p).is_file() for p in res["eep_curves"].values())
        # 脚本含 ff 块（透传真实发生）
        assert "CreateNF2FFBox" in (tmp_path / "p1" / "simulation.py").read_text(encoding="utf-8")
        # 断点缓存重入：脚本逐字节一致 → 四轮全复用（cache=False 走逐轮
        # resume 路径；cache=True 命中装配缓存，message 侧"缓存复用"另计）
        res2 = rot.solve_smatrix_openems(
            tmp_path, template="patch_eep_2x2",
            params=dict(ot.EEP_NOMINAL["patch_eep_2x2"]),
            freq_range_ghz=(5.55, 6.05), n_ports=4,
            far_field=True, resume=True, cache=False)
        assert res2["n_reused"] == 4 and res2["elapsed_s"] == 0.0
        assert res2["far_field"] is True

    def test_far_field_false_keeps_default_bytes(self, tmp_path, monkeypatch):
        import rfauto.adapters.openems_rotation as rot

        monkeypatch.setattr(
            rot.subprocess, "run",
            _fake_subprocess_run(_synthetic_smatrix(), FREQ_GHZ,
                                 far_field_marker=False))
        res = rot.solve_smatrix_openems(
            tmp_path, template="patch_eep_2x2",
            params=dict(ot.EEP_NOMINAL["patch_eep_2x2"]),
            freq_range_ghz=(5.55, 6.05), n_ports=4, resume=False)
        assert res["ok"] is True
        assert "far_field" not in res
        assert "CreateNF2FFBox" not in (tmp_path / "p1" / "simulation.py").read_text(encoding="utf-8")

    def test_coupled_tier_solve_launch_path_with_stub(self, tmp_path,
                                                      monkeypatch):
        """launch=True 全链（stub 真跑）：solver 信息 + manifest + 判读一体。"""
        import rfauto.adapters.openems_rotation as rot

        s_gt = _synthetic_smatrix()
        s_gt_f = np.broadcast_to(s_gt, (len(FREQ_GHZ), 4, 4))
        monkeypatch.setattr(
            rot.subprocess, "run",
            _fake_subprocess_run(s_gt, FREQ_GHZ, far_field_marker=True))
        res = coupled_tier_solve({
            "template": "patch_eep_2x2", "work_root": str(tmp_path),
            "params": dict(ot.EEP_NOMINAL["patch_eep_2x2"]),
            "freq_range_ghz": [5.55, 6.05], "f0_ghz": F0,
        })
        assert res["ok"] is True, res.get("error")
        r = res["result"]
        assert r["launch"] is True
        assert r["solver"]["far_field"] is True
        assert r["manifest"]["n_skipped"] == 0
        got = np.asarray([complex(p[0], p[1])
                          for p in r["s_matrix_f0"]],
                         dtype=complex).reshape(4, 4)
        i0 = r["f0_index"]
        assert np.allclose(got, s_gt_f[i0], rtol=0, atol=1e-12)
