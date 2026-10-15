"""PK-1 Q3D 对拍发射面离线面定向门（SB22-RES 席，2026-10-13）。

scripts/q3d_package_chain_case.py 的离线可验证面（真发射被 SP1 前置阻塞，
发射体不在本批）：①案例定义与闭式期望全部消费 core 单源内核（TEM 恒等式
L'C'=μ0ε0εeff 与同轴闭式独立复核，#118 双裁判）②判读器纯函数三态
（PASS/FAIL/INCONCLUSIVE；None→INCONCLUSIVE 不伪造 #316 方向；expected
缺键→INCONCLUSIVE 行不静默跳过 #331 族）③提取归一算术。
脚本经 importlib 按路径装载（scripts/ 非 package，仓内既有先例）。
"""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "q3d_package_chain_case.py"

_MU0 = 4.0e-7 * math.pi
_EPS0 = 8.854187817e-12


def _load_script():
    spec = importlib.util.spec_from_file_location("q3d_pkg_chain_case", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("q3d_pkg_chain_case", mod)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def script():
    return _load_script()


@pytest.fixture(scope="module")
def expected(script):
    return script.expected_values()


# ─── 案例定义与闭式期望（内核消费+独立恒等式复核）────────────────────────────


class TestExpectedValues:
    def test_case_a_tem_identity(self, expected):
        """case A 锚的 L'C'=μ0ε0·εeff（TEM 恒等式，独立于锚实现路径）。"""
        exp = expected["case_a_rdl"]["expected"]
        l_h_per_m = exp["l_nh_per_mm"] * 1e-6
        c_f_per_m = exp["c_pf_per_mm"] * 1e-9
        assert l_h_per_m * c_f_per_m == pytest.approx(
            _MU0 * _EPS0 * exp["eps_eff"], rel=1e-9)

    def test_case_a_rdl_scale_z0_in_printed_band(self, expected):
        """RDL 行印刷带 [40,70] Ω（lit 表行 4 口径）——z0 锚落带内。"""
        z0 = expected["case_a_rdl"]["expected"]["z0_ohm"]
        assert 40.0 <= z0 <= 70.0

    def test_case_b_tgv_closed_form_independent(self, expected):
        """case B 期望与教科书闭式手算独立复核：
        L'=μ0/(2π)·ln(3)、C'=2πε0εr/ln(3)、z0=√(L'/C')。"""
        exp = expected["case_b_tgv"]["expected"]
        length_m = expected["case_b_tgv"]["spec"]["length_m"]
        l_per_m = _MU0 / (2.0 * math.pi) * math.log(3.0)
        c_per_m = 2.0 * math.pi * _EPS0 * 6.0 / math.log(3.0)
        assert exp["l_total_nh"] == pytest.approx(
            l_per_m * length_m * 1e9, rel=1e-9)
        assert exp["c_total_ff"] == pytest.approx(
            c_per_m * length_m * 1e15, rel=1e-9)
        assert exp["z0_coax_ohm"] == pytest.approx(
            math.sqrt(l_per_m / c_per_m), rel=1e-9)

    def test_case_b_matches_lit_test_row3_band(self, expected):
        """case B 总量落 lit 表行 3 同一 ±30% 带（[0.07,0.65] nH /
        [70,650] fF），且 C 总量与 lit 测试手算 152 fF 同值带。"""
        exp = expected["case_b_tgv"]["expected"]
        assert 0.07 <= exp["l_total_nh"] <= 0.65
        assert 70.0 <= exp["c_total_ff"] <= 650.0

    def test_return_path_declared_per_case(self, expected):
        """返回路径约定逐案显式声明（Q3D 对拍协议核心，缺声明即对不上）。"""
        assert "return_path" in expected["case_b_tgv"]
        assert "3r_via" in expected["case_b_tgv"]["return_path"]


# ─── 判读器三态 ──────────────────────────────────────────────────────────────


class TestVerdict:
    def test_kernel_self_extraction_all_pass(self, script, expected):
        """判读器自检：闭式期望对自身判读 → 全 PASS（恒等面）。"""
        extract = {
            "case_a_rdl": expected["case_a_rdl"]["expected"],
            "case_b_tgv": expected["case_b_tgv"]["expected"],
        }
        verdict = script.build_verdict(extract, expected)
        assert verdict["verdict"] == "PASS"
        assert verdict["n_fail"] == 0
        assert verdict["n_pass"] == len(verdict["rows"])

    def test_out_of_band_value_fails(self, script, expected):
        """越带值 → 该行 FAIL（如 L×10 假提取）。"""
        extract = {
            "case_a_rdl": expected["case_a_rdl"]["expected"],
            "case_b_tgv": {**expected["case_b_tgv"]["expected"],
                           "l_total_nh": expected["case_b_tgv"]
                           ["expected"]["l_total_nh"] * 10.0},
        }
        verdict = script.build_verdict(extract, expected)
        assert verdict["verdict"] == "FAIL"
        bad = [r for r in verdict["rows"] if r["verdict"] == "FAIL"]
        assert len(bad) == 1 and bad[0]["name"] == "case_b.l_total_nh"

    def test_missing_extraction_inconclusive_not_fail(self, script, expected):
        """提取面缺失 → INCONCLUSIVE（如实不伪造，#316 方向：宁多报）。"""
        verdict = script.build_verdict(None, expected)
        assert verdict["verdict"] == "INCONCLUSIVE"
        assert all(r["verdict"] == "INCONCLUSIVE"
                   for r in verdict["rows"])

    def test_partially_missing_row_inconclusive(self, script, expected):
        """单行缺失（如 case A z0 未导出）→ 仅该行 INCONCLUSIVE。"""
        extract = {
            "case_a_rdl": {**expected["case_a_rdl"]["expected"],
                           "z0_ohm": None},
            "case_b_tgv": expected["case_b_tgv"]["expected"],
        }
        verdict = script.build_verdict(extract, expected)
        assert verdict["verdict"] == "INCONCLUSIVE"
        z0_row = [r for r in verdict["rows"] if r["name"] == "case_a.z0_ohm"]
        assert z0_row[0]["verdict"] == "INCONCLUSIVE"
        assert verdict["n_fail"] == 0

    def test_expected_missing_key_gets_explicit_row(self, script, expected):
        """expected 缺键 → 显式 INCONCLUSIVE 行（不静默跳过，#331 族）。"""
        broken = {"case_a_rdl": {"expected": {"z0_ohm": 50.0},
                                 "gate": {"tolerance": 0.05,
                                          "basis": "x"}},
                  "case_b_tgv": expected["case_b_tgv"]}
        verdict = script.build_verdict({}, broken)
        names = [r["name"] for r in verdict["rows"]]
        assert "case_a.l_nh_per_mm" in names
        assert "case_a.c_pf_per_mm" in names
        assert verdict["verdict"] == "INCONCLUSIVE"


# ─── 提取归一算术 ────────────────────────────────────────────────────────────


class TestExtractNormalization:
    def test_per_mm_normalization_and_z0(self, script, expected):
        """1mm 规格：l_total_nh 即每 mm 值；z0=√(L/C) 换算。"""
        exp_a = expected["case_a_rdl"]["expected"]
        got = script._extract_from_result(
            {"case_a_rdl": {"l_total_nh": exp_a["l_nh_per_mm"],
                            "c_total_pf": exp_a["c_pf_per_mm"],
                            "z0_ohm": exp_a["z0_ohm"]},
             "case_b_tgv": expected["case_b_tgv"]["expected"]},
            expected["case_a_rdl"]["spec"],
            expected["case_b_tgv"]["spec"])
        assert got["case_a_rdl"]["l_nh_per_mm"] == pytest.approx(
            exp_a["l_nh_per_mm"], rel=1e-14)
        assert got["case_a_rdl"]["c_pf_per_mm"] == pytest.approx(
            exp_a["c_pf_per_mm"], rel=1e-14)
        b = got["case_b_tgv"]
        assert b["z0_coax_ohm"] == pytest.approx(
            math.sqrt(b["l_total_nh"] * 1e-9 / (b["c_total_ff"] * 1e-15)),
            rel=1e-12)

    def test_empty_field_data_gives_none(self, script, expected):
        assert script._extract_from_result(None,
                                           expected["case_a_rdl"]["spec"],
                                           expected["case_b_tgv"]["spec"]) \
            is None
        assert script._extract_from_result({},
                                           expected["case_a_rdl"]["spec"],
                                           expected["case_b_tgv"]["spec"]) \
            is None

    def test_real_launch_refused_this_batch(self, script):
        """真发射路径本批显式拒绝（SP1 前置；防误发射协议钉）。"""
        with pytest.raises(RuntimeError, match="SP1"):
            script.run_real()
