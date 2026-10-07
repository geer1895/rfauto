"""F-B P2：pdn_service 三入口单测（判据预声明见 service 模块 docstring，#122）。

覆盖（先写后跑）：
① analyze：合成小网（2 decap+VRM）Z 谱/逐频裕量/worst vs core 直算逐位；
   反谐振峰频 vs LC 解析式逐位（无损峰恰落栅格点）；库缺件 ok=False 列缺件；
   库引用 count 展开/挂载电感覆盖逐位；DC-bias 折减透传逐位；腔模面；
② select：合成需求可行+全带裕量≥0；不可行 infeasible 如实透传（不凑解）；
   与 core.greedy_decap_select 同输入同解（薄壳不改语义）；
③ gate：plane 缺→UNKNOWN；带内落腔模→FAIL 正例；无腔模带→PASS；
   角部安装位（一切模的波腹）→ mount_too_close；阻抗门聚合与 UNKNOWN 规则；
④ CLI 三命令冒烟（payload json → exit 0；缺文件 exit 2；库缺件 exit 1）
   + MCP 工具注册冒烟。
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest
from typer.testing import CliRunner

from rfauto.cli.main import app
from rfauto.core.pdn import (
    DecapSpec,
    VrmModel,
    greedy_decap_select,
    load_decap_library,
    pdn_impedance_profile,
    target_impedance_freq,
)
from rfauto.service.pdn_service import pdn_analyze, pdn_gate, pdn_select

runner = CliRunner()

_PROV = "typical_engineering_value: 待 vendor 实测替换"


def _spec(part: str, c: float, esr: float, esl: float, lm: float) -> DecapSpec:
    return DecapSpec(part=part, c_f=c, esr_ohm=esr, esl_h=esl,
                     mount_l_h=lm, provenance=_PROV)


def _inline(part: str, c: float, esr: float, esl: float, lm: float) -> dict:
    return {"part": part, "c_f": c, "esr_ohm": esr, "esl_h": esl, "mount_l_h": lm}


# ─── ① analyze ───────────────────────────────────────────────────────────────


class TestPdnAnalyze:
    def test_small_net_bitwise_vs_core(self) -> None:
        f = [1.0e5, 3.0e5, 1.0e6, 3.0e6, 1.0e7, 3.0e7, 1.0e8]
        payload = {
            "decaps": [
                _inline("d10u", 1.0e-5, 0.010, 4.5e-10, 4.0e-10),
                _inline("d100n", 1.0e-7, 0.020, 4.0e-10, 4.0e-10),
            ],
            "vrm": {"r0": 2.0e-3, "l0": 50.0e-9, "r1": 0.05, "l1": 1.0e-9},
            "target": {"v_ripple_v": 0.05, "delta_i_a": 2.0},
            "f_axis": f,
        }
        r = pdn_analyze(payload)
        assert r["ok"] is True
        freqs = np.asarray(f, dtype=float)
        expected = pdn_impedance_profile(
            VrmModel(2.0e-3, 50.0e-9, 0.05, 1.0e-9), None,
            [(1.0e-5, 0.010, 4.5e-10, 4.0e-10), (1.0e-7, 0.020, 4.0e-10, 4.0e-10)],
            freqs)
        np.testing.assert_array_equal(r["z_re_ohm"], expected.real)  # 逐位
        np.testing.assert_array_equal(r["z_im_ohm"], expected.imag)  # 逐位
        # 裕量与 worst：同式（20log10(Z_target/|Z|)）同内核 → 逐位
        zt = target_impedance_freq(freqs, 0.05, 2.0, "flat")
        expect_margin = 20.0 * np.log10(zt / np.abs(expected))
        np.testing.assert_array_equal(np.asarray(r["margin_db"], dtype=float), expect_margin)
        i = int(np.argmin(expect_margin))
        assert r["worst_margin"]["f_hz"] == freqs[i]
        assert r["worst_margin"]["margin_db"] == expect_margin[i]
        assert r["worst_margin"]["z_target_ohm"] == 0.05 / 2.0

    def test_antiresonance_peak_recovers_lc_analytic_bitwise(self) -> None:
        # 理想无损双电容：f_peak=sqrt((C1+C2)/(C1·C2·(L1+L2)))/(2π)（core 判据 1 同式）；
        # 解析峰位作为栅格点 → 峰清单首位逐位回收（|Z|=inf 如实峰、z_ohm/q_est=None）
        c1, l1 = 1.0e-7, 4.0e-10
        c2, l2 = 1.0e-5, 2.0e-9
        f_peak = math.sqrt((c1 + c2) / (c1 * c2 * (l1 + l2))) / (2.0 * math.pi)
        grid = [*np.geomspace(1.0e6, f_peak / 2.0, 40).tolist(), f_peak,
                *np.geomspace(f_peak * 2.0, 1.0e8, 40).tolist()]
        payload = {
            "decaps": [
                _inline("a", c1, 0.0, l1, 0.0),
                _inline("b", c2, 0.0, l2, 0.0),
            ],
            "f_axis": grid,
        }
        r = pdn_analyze(payload)
        assert r["ok"] is True
        peaks = r["anti_resonances"]
        assert peaks, "无损双电容应检出反谐振峰"
        assert peaks[0]["f_hz"] == f_peak  # 逐位：回收峰=解析峰
        # 理想无损对消在浮点上留近零导纳残留 → |Z| 巨值有限（非严格 inf）；
        # Q 估计为栅格受限的正数（-3dB 边沿由邻点插值，如实为估计量）
        assert peaks[0]["z_ohm"] > 1.0e12
        assert peaks[0]["q_est"] is not None and peaks[0]["q_est"] > 10.0

    def test_antiresonance_lossy_peak_q_drops_with_esr(self) -> None:
        c1, l1 = 1.0e-7, 4.0e-10
        c2, l2 = 1.0e-5, 2.0e-9
        f_peak = math.sqrt((c1 + c2) / (c1 * c2 * (l1 + l2))) / (2.0 * math.pi)
        grid = [*np.geomspace(1.0e6, f_peak / 1.5, 60).tolist(),
                *np.geomspace(f_peak * 1.5, 1.0e8, 60).tolist()]
        q_by_esr: dict[float, float] = {}
        for esr in (0.001, 0.02):
            payload = {
                "decaps": [
                    _inline("a", c1, esr, l1, 0.0),
                    _inline("b", c2, esr, l2, 0.0),
                ],
                "f_axis": grid,
            }
            r = pdn_analyze(payload)
            assert r["ok"] is True
            peaks = r["anti_resonances"]
            assert peaks and peaks[0]["z_ohm"] is not None
            q = peaks[0]["q_est"]
            assert q is not None and q > 0.0  # 有耗峰 -3dB 带宽有限 → Q 估计有限正数
            q_by_esr[esr] = q
        # 物理方向：ESR 增大 → 反谐振峰阻尼加大 → Q 估计单调下降
        assert q_by_esr[0.001] > q_by_esr[0.02]

    def test_library_missing_part_ok_false_lists_missing(self) -> None:
        r = pdn_analyze({"decaps": ["gen_0402_1u", "ghost_part", "another_ghost"],
                         "f_start": 1.0e5, "f_stop": 1.0e8})
        assert r["ok"] is False
        joined = json.dumps(r["errors"], ensure_ascii=False)
        assert "ghost_part" in joined and "another_ghost" in joined

    def test_library_lookup_count_expansion_bitwise(self) -> None:
        payload = {"decaps": [{"part_id": "gen_0402_1u", "count": 3}],
                   "f_start": 1.0e6, "f_stop": 1.0e8, "n_points": 9}
        r = pdn_analyze(payload)
        assert r["ok"] is True
        spec = load_decap_library()["gen_0402_1u"]
        freqs = np.geomspace(1.0e6, 1.0e8, 9)
        expected = pdn_impedance_profile(None, None, [spec] * 3, freqs)
        np.testing.assert_array_equal(r["z_re_ohm"], expected.real)  # 逐位
        assert r["branch_details"]["decaps"][0]["count"] == 3
        assert r["n_decap_branches"] == 3
        assert r["branch_details"]["decaps"][0]["source"] == "library_ref"

    def test_mount_l_override_bitwise(self) -> None:
        payload = {"decaps": [{"part_id": "gen_0402_1u", "mount_l_h": 2.0e-9}],
                   "f_start": 1.0e6, "f_stop": 1.0e8, "n_points": 7}
        r = pdn_analyze(payload)
        assert r["ok"] is True
        base = load_decap_library()["gen_0402_1u"]
        overridden = DecapSpec(part=base.part, c_f=base.c_f, esr_ohm=base.esr_ohm,
                               esl_h=base.esl_h, mount_l_h=2.0e-9, provenance=base.provenance)
        freqs = np.geomspace(1.0e6, 1.0e8, 7)
        expected = pdn_impedance_profile(None, None, [overridden], freqs)
        np.testing.assert_array_equal(r["z_re_ohm"], expected.real)  # 逐位

    def test_v_bias_derating_passthrough_bitwise(self) -> None:
        # gen_0402_10u_x5r 曲线 5V 端点夹持 → 4.8e-6（core 判据 4 已钉曲线；
        # 此处钉服务链把折减等效 spec 正确透传进合成，逐位）
        payload = {"decaps": ["gen_0402_10u_x5r"], "v_bias_v": 5.0,
                   "f_start": 1.0e6, "f_stop": 1.0e8, "n_points": 9}
        r = pdn_analyze(payload)
        assert r["ok"] is True
        detail = r["branch_details"]["decaps"][0]
        assert detail["derating"] == "derated"
        assert detail["c_effective"] == 4.8e-6
        expected = pdn_impedance_profile(None, None,
                                         [(4.8e-6, 0.010, 4.5e-10, 4.0e-10)],
                                         np.geomspace(1.0e6, 1.0e8, 9))
        np.testing.assert_array_equal(r["z_re_ohm"], expected.real)  # 逐位

    def test_cavity_modes_present_when_plane_given(self) -> None:
        a, b, er = 0.05, 0.04, 4.4
        payload = {"decaps": ["gen_0402_1u"], "f_start": 1.0e6, "f_stop": 1.0e8,
                   "n_points": 5, "plane": {"a_m": a, "b_m": b, "er": er,
                                            "m_max": 2, "n_max": 3}}
        r = pdn_analyze(payload)
        assert r["ok"] is True
        modes = r["cavity_modes"]
        assert len(modes) == (2 + 1) * (3 + 1) - 1  # (0,0) 直流模排除
        f10 = next(m["f_hz"] for m in modes if (m["m"], m["n"]) == (1, 0))
        assert f10 == pytest.approx(299792458.0 / (2.0 * math.sqrt(er) * a), rel=1.0e-15)

    def test_cavity_modes_none_without_plane(self) -> None:
        r = pdn_analyze({"decaps": ["gen_0402_1u"], "f_start": 1.0e6,
                         "f_stop": 1.0e7, "n_points": 4})
        assert r["ok"] is True
        assert r["cavity_modes"] is None

    def test_smith_profile_target_passthrough(self) -> None:
        freqs = np.geomspace(1.0e5, 1.0e9, 100)
        payload = {"decaps": ["gen_0402_1u"],
                   "target": {"v_ripple_v": 0.05, "delta_i_a": 2.0,
                              "profile": "smith", "fc_hz": 1.0e7},
                   "f_axis": freqs.tolist()}
        r = pdn_analyze(payload)
        assert r["ok"] is True
        expected = target_impedance_freq(freqs, 0.05, 2.0, "smith", corner_freq_hz=1.0e7)
        assert r["z_target_ohm"] == expected.tolist()  # 逐位

    def test_bad_payload_shape_ok_false(self) -> None:
        assert pdn_analyze(["not", "a", "dict"])["ok"] is False
        r = pdn_analyze({"decaps": "gen_0402_1u", "f_start": 1e6, "f_stop": 1e7})
        assert r["ok"] is False
        r2 = pdn_analyze({"decaps": ["gen_0402_1u"], "f_start": 1e8, "f_stop": 1e6})
        assert r2["ok"] is False and any("f_stop" in e for e in r2["errors"])


# ─── ② select ────────────────────────────────────────────────────────────────


def _pool_payload() -> dict:
    """core test_greedy 同款合成场景（同质 cost=1 池+VRM/散装基线，可行域已验证）。"""
    return {
        "candidates": ([_inline("10uF", 1.0e-5, 0.010, 4.5e-10, 4.0e-10)] * 3
                       + [_inline("1uF", 1.0e-6, 0.015, 4.0e-10, 4.0e-10)] * 3
                       + [_inline("100nF", 1.0e-7, 0.020, 4.0e-10, 4.0e-10)] * 6),
        "vrm": {"r0": 5.0e-3, "l0": 20.0e-9, "r1": 0.02, "l1": 1.0e-9},
        "bulk": [_inline("bulk100", 1.0e-4, 0.01, 2.0e-9, 1.0e-9)],
        "f_start": 1.0e5, "f_stop": 1.0e8, "n_points": 80,
    }


def _core_pool() -> list[DecapSpec]:
    pool: list[DecapSpec] = []
    for part, c, esr, esl in (("10uF", 1.0e-5, 0.010, 4.5e-10),
                              ("1uF", 1.0e-6, 0.015, 4.0e-10),
                              ("100nF", 1.0e-7, 0.020, 4.0e-10)):
        pool.extend(_spec(part, c, esr, esl, 4.0e-10) for _ in range(3 if part != "100nF" else 6))
    return pool


class TestPdnSelect:
    def test_feasible_full_band_margins(self) -> None:
        payload = _pool_payload()
        payload["budget"] = 12
        payload["target"] = {"v_ripple_v": 0.1, "delta_i_a": 1.0}
        r = pdn_select(payload)
        assert r["ok"] is True
        assert r["feasible"] is True and r["infeasible"] is False
        assert r["excess"] == 0.0
        assert 0 < r["n_selected"] <= 12
        assert r["total_cost"] <= 12.0
        margins = [m for m in r["margin_db"] if m is not None]
        assert len(margins) == 80  # 全带达标 → 全部裕量有限非负
        assert min(margins) >= 0.0
        assert r["worst_margin"]["margin_db"] == min(margins)

    def test_same_solution_as_core_direct(self) -> None:
        # 薄壳不改变语义：同输入（同 specs/同 target/同基线）与 core 直算同解
        payload = _pool_payload()
        payload["budget"] = 12
        payload["target"] = {"v_ripple_v": 0.1, "delta_i_a": 1.0}
        r = pdn_select(payload)
        assert r["ok"] is True
        freqs = np.geomspace(1.0e5, 1.0e8, 80)
        core = greedy_decap_select(
            _core_pool(), 0.1, freqs, 12.0,
            baseline_vrm=VrmModel(5.0e-3, 20.0e-9, 0.02, 1.0e-9),
            baseline_caps=[(1.0e-4, 0.01, 2.0e-9, 1.0e-9)])
        assert [s["part"] for s in r["selected"]] == [s.part for s in core.selected]
        assert r["n_selected"] == core.n_selected
        assert r["total_cost"] == core.total_cost  # 逐位
        assert r["z_target_ohm"] == core.z_target.tolist()
        np.testing.assert_array_equal(r["z_mag_ohm"], np.abs(core.z_profile))  # 逐位

    def test_infeasible_passthrough_honest(self) -> None:
        # 不可行需求（0.1mΩ 全带）：候选全加完仍超标 → infeasible 如实透传，不凑解
        payload = _pool_payload()
        payload["budget"] = 99
        payload["target"] = {"v_ripple_v": 1.0e-4, "delta_i_a": 1.0}
        r = pdn_select(payload)
        assert r["ok"] is True  # infeasible 是正常结果不是错误
        assert r["infeasible"] is True and r["feasible"] is False
        assert r["excess"] > 0.0
        assert r["n_selected"] == 12  # 预算足够吞下全池：改善用尽后如实停
        assert r["total_cost"] == 12.0

    def test_missing_budget_or_target_ok_false(self) -> None:
        payload = _pool_payload()
        payload["target"] = {"v_ripple_v": 0.1, "delta_i_a": 1.0}
        r = pdn_select(payload)  # 缺 budget
        assert r["ok"] is False and any("budget" in e for e in r["errors"])
        payload2 = _pool_payload()
        payload2["budget"] = 12  # 缺 target
        r2 = pdn_select(payload2)
        assert r2["ok"] is False and any("target" in e for e in r2["errors"])

    def test_v_bias_derated_candidates_visible(self) -> None:
        payload = _pool_payload()
        payload["budget"] = 2
        payload["target"] = {"v_ripple_v": 0.1, "delta_i_a": 1.0}
        payload["candidates"] = [{"part_id": "gen_0402_10u_x5r", "count": 2}]
        payload["v_bias_v"] = 5.0
        r = pdn_select(payload)
        assert r["ok"] is True
        assert r["candidate_details"][0]["derating"] == "derated"
        assert r["candidate_details"][0]["c_effective"] == 4.8e-6
        for item in r["selected"]:
            assert item["derating"] == "derated"
            assert item["c_f"] == 4.8e-6


# ─── ③ gate ──────────────────────────────────────────────────────────────────

_A_M, _B_M, _ER = 0.05, 0.04, 4.4
_F10_HZ = 299792458.0 / (2.0 * math.sqrt(_ER) * _A_M)  # ≈1.429 GHz


class TestPdnGate:
    def test_plane_missing_unknown(self) -> None:
        r = pdn_gate({})
        assert r["ok"] is True
        assert r["gate"] == "pdn_ac_pi"
        assert r["verdict"] == "UNKNOWN"
        assert r["unknown_reason"] and "plane" in r["unknown_reason"]

    def test_band_missing_with_plane_unknown(self) -> None:
        r = pdn_gate({"plane": {"a_m": _A_M, "b_m": _B_M, "er": _ER}})
        assert r["verdict"] == "UNKNOWN"
        assert r["unknown_reason"] and "interest_band" in r["unknown_reason"]

    def test_mode_in_band_fail(self) -> None:
        # (1,0) 模 f10≈1.429GHz 落入带 → FAIL 正例（时钟谐波带落腔模）
        r = pdn_gate({"plane": {"a_m": _A_M, "b_m": _B_M, "er": _ER},
                      "interest_band": {"f_lo_hz": 1.4e9, "f_hi_hz": 1.45e9}})
        assert r["ok"] is True
        assert r["verdict"] == "FAIL"
        codes = {v["code"] for v in r["violations"]}
        assert "cavity_mode_in_band" in codes
        assert (1, 0) in {(m["m"], m["n"]) for m in r["modes_in_band"]}
        assert r["modes_in_band"][0]["f_hz"] == pytest.approx(_F10_HZ, rel=1.0e-12)

    def test_clear_band_pass(self) -> None:
        # 带取在全部腔模以下（m_max 缺省 4，最低模 f10≈1.429GHz）→ PASS
        r = pdn_gate({"plane": {"a_m": _A_M, "b_m": _B_M, "er": _ER},
                      "interest_band": {"f_lo_hz": 1.0e3, "f_hi_hz": 1.0e6}})
        assert r["verdict"] == "PASS"
        assert r["n_violations"] == 0
        assert r["modes_in_band"] == []

    def test_mount_at_antinode_too_close(self) -> None:
        # 角点 (0,0) 是一切模的波腹 → 距离 0 < 任意避让半径 → mount_too_close
        r = pdn_gate({"plane": {"a_m": _A_M, "b_m": _B_M, "er": _ER},
                      "interest_band": {"f_lo_hz": 1.4e9, "f_hi_hz": 1.45e9},
                      "mount_positions": [{"x_m": 0.0, "y_m": 0.0}]})
        codes = {v["code"] for v in r["violations"]}
        assert "mount_too_close" in codes
        assert r["verdict"] == "FAIL"
        row = r["mount_clearances"][0]
        assert row["verdict"] == "too_close"
        assert row["distance_m"] == 0.0
        assert row["f_eval_hz"] == 1.45e9  # λ_eff 在关注带上缘评估（预声明）

    def test_impedance_gate_aggregates_into_fail(self) -> None:
        # 带内无腔模（该检查 PASS）但 Z 谱违标 → 聚合 FAIL
        r = pdn_gate({
            "plane": {"a_m": _A_M, "b_m": _B_M, "er": _ER},
            "interest_band": {"f_lo_hz": 1.0e3, "f_hi_hz": 1.0e6},
            "impedance": {"decaps": ["gen_0402_1u"],
                          "target": {"v_ripple_v": 0.05, "delta_i_a": 2.0},
                          "f_start": 1.0e5, "f_stop": 1.0e8, "n_points": 10},
        })
        assert r["verdict"] == "FAIL"
        codes = {v["code"] for v in r["violations"]}
        assert codes == {"impedance_exceeds_target"}
        assert r["impedance_gate"]["ok"] is True
        assert r["impedance_gate"]["worst_margin"]["margin_db"] < 0.0

    def test_impedance_only_still_unknown_but_reported(self) -> None:
        # plane 缺 → UNKNOWN 如实（任务书口径）；R3 结果照报不丢、不升级 verdict
        r = pdn_gate({"impedance": {"decaps": ["gen_0402_1u"],
                                    "target": {"v_ripple_v": 0.05, "delta_i_a": 2.0},
                                    "f_start": 1.0e5, "f_stop": 1.0e8, "n_points": 10}})
        assert r["verdict"] == "UNKNOWN"
        assert r["impedance_gate"]["ok"] is True
        assert r["impedance_gate"]["worst_margin"]["margin_db"] < 0.0

    def test_bad_band_shape_ok_false(self) -> None:
        r = pdn_gate({"interest_band": {"f_lo_hz": 1e9, "f_hi_hz": 1e8}})
        assert r["ok"] is False
        assert any("f_hi_hz" in e for e in r["errors"])


# ─── ④ CLI / MCP 冒烟 ────────────────────────────────────────────────────────


def _payload_file(tmp_path, payload: dict) -> str:
    p = tmp_path / "payload.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return str(p)


class TestPdnCli:
    def test_analyze_ok(self, tmp_path) -> None:
        payload = {"decaps": ["gen_0402_1u"],
                   "vrm": {"r0": 2e-3, "l0": 50e-9, "r1": 0.05, "l1": 1e-9},
                   "target": {"v_ripple_v": 0.05, "delta_i_a": 2.0},
                   "f_start": 1.0e6, "f_stop": 1.0e8, "n_points": 12}
        result = runner.invoke(app, ["pdn", "analyze", _payload_file(tmp_path, payload)])
        assert result.exit_code == 0, result.output
        assert '"ok": true' in result.output
        assert '"worst_margin"' in result.output

    def test_analyze_missing_file_exit_2(self) -> None:
        result = runner.invoke(app, ["pdn", "analyze", "no_such_payload.json"])
        assert result.exit_code == 2

    def test_analyze_missing_library_part_exit_1(self, tmp_path) -> None:
        payload = {"decaps": ["ghost_part"], "f_start": 1.0e6, "f_stop": 1.0e7}
        result = runner.invoke(app, ["pdn", "analyze", _payload_file(tmp_path, payload)])
        assert result.exit_code == 1
        assert "ghost_part" in result.output

    def test_select_ok(self, tmp_path) -> None:
        payload = _pool_payload()
        payload["budget"] = 6
        payload["target"] = {"v_ripple_v": 0.1, "delta_i_a": 1.0}
        result = runner.invoke(app, ["pdn", "select", _payload_file(tmp_path, payload)])
        assert result.exit_code == 0, result.output
        assert '"feasible": true' in result.output

    def test_gate_ok(self, tmp_path) -> None:
        payload = {"plane": {"a_m": _A_M, "b_m": _B_M, "er": _ER},
                   "interest_band": {"f_lo_hz": 1.4e9, "f_hi_hz": 1.45e9}}
        result = runner.invoke(app, ["pdn", "gate", _payload_file(tmp_path, payload)])
        assert result.exit_code == 0, result.output
        assert '"verdict": "FAIL"' in result.output

    def test_gate_infeasible_payload_exit_1(self, tmp_path) -> None:
        payload = {"plane": {"a_m": -1.0, "b_m": _B_M, "er": _ER},
                   "interest_band": {"f_lo_hz": 1.0e3, "f_hi_hz": 1.0e6}}
        result = runner.invoke(app, ["pdn", "gate", _payload_file(tmp_path, payload)])
        assert result.exit_code == 1
        assert "a_m" in result.output


class TestPdnMcpRegistration:
    def test_pdn_tools_registered(self) -> None:
        import asyncio

        from rfauto.mcp_server import mcp as server
        tools = asyncio.run(server.list_tools())
        names = {t.name for t in tools}
        assert {"pdn_analyze", "pdn_select", "pdn_gate"} <= names

    def test_mcp_tool_callable_envelope(self) -> None:
        # 直接调 service 同源函数的 MCP 薄壳语义：坏 payload → ok=False 信封不抛
        from rfauto.mcp_server import pdn_gate as mcp_pdn_gate
        result = mcp_pdn_gate({"plane": {"a_m": "x", "b_m": 0.04, "er": 4.4}})
        assert result["ok"] is False


class TestReviewTrackCFixes:
    """审查轨 C P1 修复回归钉（2026-09-27）。"""

    def test_gate_bool_plane_rejected(self):
        """P1-3：plane 数值字段 bool 污染必须显式拒绝（df7+⑯）。

        F-13 批 2（W6-E）：文案随单源统一为「不接受 bool（float(True)=1.0
        静默污染）」（原 pdn 本地副本「不接受布尔值」）——拒收语义逐位
        不变，仅文案统一（已声明）。
        """
        r = pdn_gate({"plane": {"a_m": True, "b_m": 0.1, "er": 4.4}})
        assert r["ok"] is False
        assert any("bool" in e for e in r["errors"]), r["errors"]

    def test_gate_impedance_subgate_failure_is_unknown(self):
        """P1-4：请求了 R3 子门但子分析失败 → UNKNOWN（fail-closed），
        不得静默 PASS；unknown_reason 归因到子门。"""
        r = pdn_gate({
            "plane": {"a_m": 0.05, "b_m": 0.04, "er": 4.4},
            "interest_band": {"f_lo_hz": 1e6, "f_hi_hz": 1e8},
            "impedance": {
                "decaps": ["ghost_part"],
                "target": {"v_ripple_v": 0.1, "delta_i_a": 1.0},
                "f_start": 1e5, "f_stop": 1e8, "n_points": 50}})
        assert r["ok"] is True
        assert r["verdict"] == "UNKNOWN"
        assert "impedance 子门" in (r.get("unknown_reason") or "")

    def test_load_library_bad_yaml_enveloped(self, tmp_path):
        """P1-1：malformed YAML / 目录路径 → 结构化 errors 不抛出。"""
        bad = tmp_path / "bad.yaml"
        bad.write_text("{[unbalanced", encoding="utf-8")
        r = pdn_analyze({"library_path": str(bad), "decaps": ["x"]})
        assert r["ok"] is False
        assert any("decap 库加载失败" in e for e in r["errors"])
        r2 = pdn_analyze({"library_path": str(tmp_path), "decaps": ["x"]})
        assert r2["ok"] is False

    def test_gate_catchall_envelope_uniform(self):
        """P2-11：catch-all 信封与校验路径同键形（errors 列表+schema_version）。"""
        r = pdn_gate({"plane": {"a_m": True, "b_m": 0.1, "er": 4.4}})
        assert "schema_version" in r
        assert isinstance(r.get("errors"), list)
