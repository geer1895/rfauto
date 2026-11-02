"""QM-12 GCI 试点（ge8b 席B8）：历史 ΔS/网格阶梯消费 solve_health 第 10 因子。

三层钉：
1. 纯数学钉（嵌入字面量，零 runs/ 依赖，干净环境可跑）——lange/cline 的
   观察阶 p 与 PASS/WARN 判读、网格阶梯振荡×非恒定比的诚实不可估（#316）；
2. 提取器对档钉（skipif：runs/ 归档在本机在场时）——脚本提取序列与嵌入
   字面量逐位一致（#144 判真口径：只读归档零改写）；
3. 试点档 schema 钉（runs/qm12_gci/summary.json 在场时）——落档形态稳定。

数值出处：runs/hfss_c4_arbitration/{pass1,verdict_conv,verdict_conv3}.json
（#335 判读先例同源）与 runs/audit_mesh_conv/m*/sparams.csv（2.5GHz 直读）。
"""
from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_SCRIPT = REPO / "scripts" / "qm12_gci_pilot.py"

_spec = importlib.util.spec_from_file_location("qm12_gci_pilot", _SCRIPT)
qm12 = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(qm12)

from rfauto.core.solve_health import (
    FACTOR_GRID_CONVERGENCE,
    solve_health_check,
)

#: runs/hfss_c4_arbitration 三档实测值（ΔS 0.02/0.01/0.005，r=2 恒定）
_LANGE_F = (-2.3119576567030196, -2.8142090054018434, -3.1054661175194314)
_CLINE_F = (-8.752295316959621, -9.726498696566207, -9.996245874370114)
_DS = (0.02, 0.01, 0.005)

#: runs/audit_mesh_conv 三档 2.5GHz 直读（h 0.3/0.5/0.8mm，r 非恒定）
_MESH_H = (0.3, 0.5, 0.8)
_MESH_S21 = (-3.515282, -3.727884, -3.492022)


def _grid_factor(h_seq, f_seq):
    report = solve_health_check(grid_convergence={
        "h_seq": list(h_seq), "f_seq": list(f_seq)})
    found = [f for f in report["factors"]
             if f.get("factor") == FACTOR_GRID_CONVERGENCE]
    assert len(found) == 1
    return found[0]


def test_lange_ladder_convergent_but_wide_band() -> None:
    """ΔS 阶梯 r=2 恒定：lange p≈0.786、相对带 ~16%>5% → WARN（#335 量化）。"""
    f = _grid_factor(_DS, _LANGE_F)
    assert f["status"] == "WARN"
    gci = f["evidence"]
    assert gci["convergent"] is True
    assert gci["r_constant"] is True
    assert math.isclose(gci["r"], 2.0, rel_tol=1e-12)
    assert gci["p"] == pytest.approx(0.7861, abs=2e-3)
    assert gci["gci_fine_rel"] == pytest.approx(0.1618, abs=2e-3)


def test_cline_ladder_pass() -> None:
    """cline p≈1.853、相对带 ~1.3%≤5% → PASS（外推带 ±0.129dB）。"""
    f = _grid_factor(_DS, _CLINE_F)
    assert f["status"] == "PASS"
    gci = f["evidence"]
    assert gci["convergent"] is True
    assert gci["p"] == pytest.approx(1.853, abs=2e-3)
    assert gci["gci_fine_rel"] == pytest.approx(0.0129, abs=2e-3)


def test_mesh_ladder_oscillatory_nonconstant_honest() -> None:
    """网格阶梯 0.3/0.5/0.8mm（r 非恒定）且逐级差变号 → 如实不可估不虚构。"""
    f = _grid_factor(_MESH_H, _MESH_S21)
    assert f["status"] == "FAIL"  # #316 方向：不可估多报不放过
    gci = f["evidence"]
    assert gci["convergent"] is False
    assert gci["status"] == "oscillatory"
    assert gci["reason"] == "oscillatory_requires_constant_refinement_ratio"
    assert gci["gci_fine"] is None and gci["band"] is None


@pytest.mark.skipif(
    not (REPO / "runs" / "hfss_c4_arbitration" / "pass1" / "verdict.json")
    .is_file() or not (REPO / "runs" / "audit_mesh_conv" / "m0.3")
    .is_dir(), reason="runs/ 历史归档不在本机")
def test_extractors_match_archived_literals() -> None:
    """提取器直读归档 ≡ 嵌入字面量（数值单源=归档产物，测试只钉一致）。"""
    lange = qm12.extract_hfss_ladder(REPO / "runs", "lange")
    assert lange["missing"] == []
    assert tuple(lange["f_seq"]) == pytest.approx(_LANGE_F, abs=1e-12)
    assert sorted(lange["h_seq"]) == sorted(_DS)
    mesh = qm12.extract_mesh_ladder(REPO / "runs", "s21_db")
    assert mesh["missing"] == []
    assert tuple(mesh["f_seq"]) == pytest.approx(_MESH_S21, abs=5e-6)
    assert tuple(mesh["h_seq"]) == _MESH_H


@pytest.mark.skipif(not (REPO / "runs" / "qm12_gci" / "summary.json").is_file(),
                    reason="试点档未落档（先跑 scripts/qm12_gci_pilot.py）")
def test_pilot_archive_schema() -> None:
    """落档形态钉：4 试点全可估、判读方向与数学钉一致、零改写归档。"""
    summary = json.loads(
        (REPO / "runs" / "qm12_gci" / "summary.json").read_text(
            encoding="utf-8"))
    assert summary["schema"] == "rfauto-qm12-gci-summary-v1"
    assert summary["n_pilots"] == 4 and summary["n_ok"] == 4
    assert summary["pilots"]["hfss_c4_lange_s31_db"]["status"] == "WARN"
    assert summary["pilots"]["hfss_c4_cline_s31_db"]["status"] == "PASS"
    for pid in ("openems_audit_mesh_s21_db", "openems_audit_mesh_s11_db"):
        assert summary["pilots"][pid]["status"] == "FAIL"
        art = json.loads((REPO / "runs" / "qm12_gci" / f"{pid}.json")
                         .read_text(encoding="utf-8"))
        assert art["schema"] == "rfauto-qm12-gci-pilot-v1"
        assert art["gci"]["convergent"] is False
