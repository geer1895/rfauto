"""F-J.5 过孔工艺参数面单测（round5 §三件 5 判据）。

判据锚（#122 先行）：
- 背钻联动与 HS-2 面逐位一致：fres 包装与 ``fab_check.stub_resonance_ghz``
  同输入同输出（同一实现，手算锚 L=10mm/εr_eff=4 → 3.747405725 GHz，
  tests/unit/test_fab_stub_gate.py 同源）；verdict 判定行由
  check_stub_resonance/check_backdrill 产出、本面只聚合——codes/rows
  与直接调用 fab_check 完全相等；
- 区间判定边界恒等式（恰等上界=PASS 一种口径钉死）：drill==min、
  纵横比==上限、孔铜==类下限均 PASS；fres==门限 → outside_band
  （fab_check 的 ``fres < limit`` 违规判据同向）；
- 可选几何判缺失 is not None：缺省检查记 skipped（不静默）；数值 0.0
  是合法给定值（按 0.0 判 FAIL，#364④）。
"""

from __future__ import annotations

import json
import math

import pytest

from rfauto.core import via_process_params as vpp
from rfauto.core.fab_check import check_backdrill, check_stub_resonance, stub_resonance_ghz
from rfauto.core.via_process_params import (
    HOLE_COPPER_UM_BY_CLASS,
    IPC4761_TYPE_VII,
    IPC4761_VIA_PROTECTION_TYPES,
    LASER_DRILL_CO2,
    LASER_DRILL_UV,
    MECHANICAL_DRILL,
    backdrill_fres_verdict,
    backdrill_residual_len_mm,
    backdrill_verdict_from_span,
    check_via_manufacturability,
    residual_stub_fres_ghz,
)

#: 手算锚（与 test_fab_stub_gate.py 同源：fres=c/(4L√εr)）
ANCHOR_10MM_ER4 = 3.747405725


# ─── 1. 能力表登记面 ───────────────────────────────────────────────────────────


def test_capability_tables_sanity():
    assert MECHANICAL_DRILL.advanced_min_drill_mm < MECHANICAL_DRILL.min_drill_mm
    assert MECHANICAL_DRILL.max_aspect_ratio < MECHANICAL_DRILL.advanced_max_aspect_ratio
    assert MECHANICAL_DRILL.finished_hole_tol_mm > 0.0
    assert MECHANICAL_DRILL.source and "UNVERIFIED" in MECHANICAL_DRILL.source
    # 激光钻：UV 孔径域整体小于 CO2
    assert LASER_DRILL_UV.min_drill_mm < LASER_DRILL_CO2.min_drill_mm
    assert LASER_DRILL_UV.max_drill_mm <= LASER_DRILL_CO2.max_drill_mm
    assert LASER_DRILL_UV.max_aspect_ratio == 1.0
    d = MECHANICAL_DRILL.to_dict()
    assert d["min_drill_mm"] == MECHANICAL_DRILL.min_drill_mm and "source" in d
    # 埋盲孔叠构约束登记面
    c = vpp.BLIND_BURIED_STACKUP_CONSTRAINTS
    assert c["laser_microvia_max_aspect_ratio"] == 1.0 and "source" in c


def test_hole_copper_band_20_25():
    # 20–25µm 带 = round5 规格给定（IPC-6012 Class 2/3 最小平均口径）
    assert HOLE_COPPER_UM_BY_CLASS["class_2"] == 20.0
    assert HOLE_COPPER_UM_BY_CLASS["class_3"] == 25.0
    assert HOLE_COPPER_UM_BY_CLASS["class_2"] < HOLE_COPPER_UM_BY_CLASS["class_3"]


# ─── 2. 背钻联动：与 HS-2 面逐位一致 ──────────────────────────────────────────


@pytest.mark.parametrize(
    "length,er", [(10.0, 4.0), (12.7, 4.0), (1.0, 4.0), (6.0, 3.61), (20.0, 4.4)]
)
def test_fres_bitwise_identity_with_fab_check(length, er):
    # 同一实现：逐位一致（==）
    assert residual_stub_fres_ghz(length, er) == stub_resonance_ghz(length, er)


def test_fres_hand_anchor():
    # L=10mm、εr_eff=4 → 299792458/(4×0.010×2)/1e9 = 3.747405725 GHz（逐位）
    assert residual_stub_fres_ghz(10.0, 4.0) == pytest.approx(ANCHOR_10MM_ER4, rel=1e-12)


def test_backdrill_fres_verdict_notch_risk():
    # L=12.7mm/εr=4 → fres≈2.95GHz；nyquist=3.0 → fres<门限 → notch_risk
    verdict = backdrill_fres_verdict(12.7, 4.0, nyquist_ghz=3.0)
    assert verdict["ok"] is False
    assert verdict["verdict"] == "notch_risk"
    assert verdict["in_band"] is True
    assert verdict["limit_ghz"] == 1.0 * 3.0  # 门限=mf×nyq（逐位）
    # 判定行与直接调 fab_check 完全一致
    rows = check_stub_resonance(12.7, 4.0, nyquist_ghz=3.0)
    assert verdict["rows"] == rows
    assert any(r["code"] == "STUB_RES" for r in rows)


def test_backdrill_fres_verdict_outside_band():
    # L=1mm → fres≈37.47GHz；nyquist=10 → 带外
    verdict = backdrill_fres_verdict(1.0, 4.0, nyquist_ghz=10.0)
    assert verdict["ok"] is True
    assert verdict["verdict"] == "outside_band"
    assert verdict["in_band"] is False
    assert verdict["fres_ghz"] == stub_resonance_ghz(1.0, 4.0)
    # margin 折算门限逐位
    v2 = backdrill_fres_verdict(1.0, 4.0, nyquist_ghz=10.0, margin_frac=2.0)
    assert v2["limit_ghz"] == 2.0 * 10.0
    assert v2["verdict"] == "outside_band"  # 37.47 ≫ 20


def test_verdict_boundary_equality_pass():
    # 恰等上界=PASS 口径钉死：nyquist 取 fres 本身 → fres == limit
    fres = residual_stub_fres_ghz(10.0, 4.0)
    verdict = backdrill_fres_verdict(10.0, 4.0, nyquist_ghz=fres)
    assert verdict["limit_ghz"] == fres  # mf=1.0 乘法恒等
    assert verdict["verdict"] == "outside_band"  # 恰等 → PASS（fres < limit 为 False）
    assert verdict["ok"] is True
    # 与 fab_check 判据同向：恰等时 check_stub_resonance 无违规行
    assert check_stub_resonance(10.0, 4.0, nyquist_ghz=fres) == []
    # 恰等下界（margin<1）：fres == 0.5×(2×fres) 同向
    v_low = backdrill_fres_verdict(10.0, 4.0, nyquist_ghz=2.0 * fres, margin_frac=0.5)
    assert v_low["verdict"] == "outside_band"


def test_backdrill_residual_len_formula():
    assert backdrill_residual_len_mm(10.0, 4.0) == 6.0
    assert backdrill_residual_len_mm(4.0, 10.0) == 0.0  # over-drill 截 0
    assert backdrill_residual_len_mm(5.0, 5.0) == 0.0  # 恰等截 0
    with pytest.raises(ValueError):
        backdrill_residual_len_mm(0.0, 1.0)  # span 必须 >0
    with pytest.raises(ValueError):
        backdrill_residual_len_mm(10.0, -1.0)  # depth 必须 ≥0
    with pytest.raises(ValueError, match="bool"):
        backdrill_residual_len_mm(True, 1.0)  # df7+⑯


def _rows_equal(rows_a, rows_b):
    """行清单 NaN 感知相等（fab_check 行内 limit 可为 nan——nan != nan）。"""
    if len(rows_a) != len(rows_b):
        return False
    for ra, rb in zip(rows_a, rows_b, strict=True):
        if set(ra) != set(rb):
            return False
        for k in ra:
            va, vb = ra[k], rb[k]
            if isinstance(va, float) and isinstance(vb, float) and math.isnan(va) and math.isnan(vb):
                continue
            if va != vb:
                return False
    return True


@pytest.mark.parametrize(
    "span,depth,min_rem,er,nyq",
    [
        (10.0, 4.0, 1.0, 4.0, None),  # 正常：仅信息行
        (10.0, 12.0, 1.0, 4.0, None),  # over-drill
        (10.0, 9.5, 1.0, 4.0, 30.0),  # under-drill + 带外谐振
        (10.0, 2.0, 0.5, 4.0, 5.0),  # 残段 8mm → fres≈4.68GHz 带内
        (5.0, 5.0, 1.0, 4.0, 3.0),  # 残段恰 0：无谐振行
    ],
)
def test_backdrill_from_span_codes_identical(span, depth, min_rem, er, nyq):
    wrapper = backdrill_verdict_from_span(span, depth, min_rem, er, nyquist_ghz=nyq)
    direct = check_backdrill(span, depth, min_rem, er, nyquist_ghz=nyq)
    # 同输入同输出（逐位一致）：rows 原样透传（同一实现产出行，nan 感知比对）
    assert _rows_equal(wrapper["rows"], direct)
    assert wrapper["codes"] == [r["code"] for r in direct]
    hard = [r for r in direct if not r["code"].endswith("_INFO")]
    assert wrapper["ok"] is (not hard)
    # residual/fres 聚合视图与 fab_check 口径一致
    residual = max(span - depth, 0.0)
    assert wrapper["residual_len_mm"] == residual
    if residual > 0.0:
        assert wrapper["fres_ghz"] == stub_resonance_ghz(residual, er)
    else:
        assert wrapper["fres_ghz"] is None  # 残段 0 不做谐振比对（同 fab_check）


def test_backdrill_from_span_od_case():
    out = backdrill_verdict_from_span(10.0, 12.0, 1.0, 4.0)
    assert out["ok"] is False
    assert out["codes"] == ["BACKDRILL_OD"]
    assert out["residual_len_mm"] == 0.0
    assert out["fres_ghz"] is None


# ─── 3. 可制造性判定面：区间判定恰等上界=PASS ─────────────────────────────────


def test_mfg_pass_boundaries_exact():
    # 恰等上界 = PASS（口径钉死一种）
    r = check_via_manufacturability(0.15)  # drill == min
    assert r.ok is True
    checks = {c["check"]: c for c in r.checks}
    assert checks["min_drill_mm"]["verdict"] == "pass"
    # 纵横比恰等上限：1.2/0.15 = 8.0 == max_aspect_ratio
    r2 = check_via_manufacturability(0.15, board_thickness_mm=1.2)
    assert r2.ok is True
    assert {c["check"]: c for c in r2.checks}["aspect_ratio"]["verdict"] == "pass"
    # 孔铜恰等类下限（class_2=20 / class_3=25）
    r3 = check_via_manufacturability(0.2, hole_copper_um=20.0, ipc_class="class_2")
    r4 = check_via_manufacturability(0.2, hole_copper_um=25.0, ipc_class="class_3")
    assert r3.ok is True and r4.ok is True
    assert r4.ipc_class == "class_3"


def test_mfg_fail_rows():
    r = check_via_manufacturability(
        0.12, board_thickness_mm=1.6, hole_copper_um=15.0, ipc_class="class_2"
    )
    assert r.ok is False
    checks = {c["check"]: c for c in r.checks}
    assert checks["min_drill_mm"]["verdict"] == "fail"
    assert checks["min_drill_mm"]["code"] == "DRILL_BELOW_MIN"
    assert checks["aspect_ratio"]["verdict"] == "fail"  # 1.6/0.12≈13.3 > 8
    assert checks["aspect_ratio"]["code"] == "ASPECT_RATIO_ABOVE_MAX"
    assert checks["hole_copper_um"]["verdict"] == "fail"
    assert checks["hole_copper_um"]["code"] == "HOLE_COPPER_BELOW_MIN"
    assert checks["hole_copper_um"]["limit"] == 20.0
    # 全过对照
    ok_case = check_via_manufacturability(0.2, board_thickness_mm=1.6, hole_copper_um=25.0)
    assert ok_case.ok is True


def test_mfg_skipped_missing():
    # 可选几何判缺失 is not None：缺省检查 skipped 留痕，不静默
    r = check_via_manufacturability(0.2)
    checks = {c["check"]: c for c in r.checks}
    assert checks["aspect_ratio"]["verdict"] == "skipped"
    assert checks["hole_copper_um"]["verdict"] == "skipped"
    assert checks["aspect_ratio"]["value"] is None
    assert r.ok is True  # skipped 不算 FAIL
    # 数值 0.0 是合法给定值（#364④）：按 0.0 判 FAIL
    r0 = check_via_manufacturability(0.2, hole_copper_um=0.0)
    c0 = {c["check"]: c for c in r0.checks}["hole_copper_um"]
    assert c0["verdict"] == "fail" and c0["value"] == 0.0


def test_mfg_ipc_class_validation():
    with pytest.raises(ValueError, match="ipc_class"):
        check_via_manufacturability(0.2, ipc_class="class_9")
    with pytest.raises(ValueError, match="bool"):
        check_via_manufacturability(True)  # df7+⑯
    with pytest.raises(ValueError, match="bool"):
        check_via_manufacturability(0.2, board_thickness_mm=False)
    with pytest.raises(ValueError, match="bool"):
        check_via_manufacturability(0.2, hole_copper_um=True)
    with pytest.raises(ValueError, match="drill_mm"):
        check_via_manufacturability(0.0)  # 孔径必须 >0
    # capability 可整体替换（对接 fab 剖面能力的路径）
    custom = vpp.MechanicalDrillCapability(
        min_drill_mm=0.2,
        advanced_min_drill_mm=0.15,
        finished_hole_tol_mm=0.08,
        max_aspect_ratio=8.0,
        advanced_max_aspect_ratio=10.0,
        source="test-vendor",
    )
    rep = check_via_manufacturability(0.15, capability=custom)
    assert rep.ok is False  # 0.15 < 自定义 min 0.2
    assert rep.capability["source"] == "test-vendor"


# ─── 4. IPC-4761 覆围面登记 ───────────────────────────────────────────────────


def test_ipc4761_registry():
    assert len(IPC4761_VIA_PROTECTION_TYPES) == 7
    labels = [entry["label"] for entry in IPC4761_VIA_PROTECTION_TYPES.values()]
    assert labels == ["Type I", "Type II", "Type III", "Type IV", "Type V", "Type VI", "Type VII"]
    for key, entry in IPC4761_VIA_PROTECTION_TYPES.items():
        assert key == entry["label"].lower().replace(" ", "_")  # 键=label 规范形
        assert entry["en"] and entry["zh"]
        assert isinstance(entry["filled"], bool) and isinstance(entry["capped"], bool)
    # Type VII=填充+帽盖（盘内孔/BGA 惯例要求），登记面含设计注记
    assert IPC4761_TYPE_VII is IPC4761_VIA_PROTECTION_TYPES["type_vii"]
    assert IPC4761_TYPE_VII["filled"] is True and IPC4761_TYPE_VII["capped"] is True
    assert "盘内孔" in IPC4761_TYPE_VII["design_note"]
    # 单调性：VII 是唯一 filled+capped 组合
    both = [k for k, e in IPC4761_VIA_PROTECTION_TYPES.items() if e["filled"] and e["capped"]]
    assert both == ["type_vii"]


# ─── 5. JSON 可序列化（dataclass+to_dict） ───────────────────────────────────


def test_report_json_roundtrip():
    rep = check_via_manufacturability(0.2, board_thickness_mm=1.6, hole_copper_um=22.5)
    text = json.dumps(rep.to_dict(), ensure_ascii=False)
    assert '"ok": true' in text
    # verdict dict 含 None（fres 缺席路径）同样可序列化
    out = backdrill_verdict_from_span(10.0, 12.0, 1.0, 4.0)
    assert json.dumps(out, ensure_ascii=False)
    verdict = backdrill_fres_verdict(1.0, 4.0, nyquist_ghz=10.0)
    assert json.dumps(verdict, ensure_ascii=False)
