"""r4 HS-2：残桩/背钻 notch 门单测（core.check_stub_resonance/
check_backdrill + service.check_stub_backdrill_dfm，挂 fab DFM）。

手算锚独立于实现（fres=c/(4L√εr)，c=299792458 m/s，L 单位 mm）：
- L=10mm、εr_eff=4.0 → 299792458/(4×0.010×2)=3.747405725 GHz（逐位）；
- L=20mm、εr_eff=4.0 → 299792458/(4×0.020×2)=1.8737028625 GHz
  （nyquist 比对用）；
- L=1mm、εr_eff=4.0 → 37.47405725 GHz（正常背钻例）；
- Simonovich EDN RoT#17 量级互证：0.5in≈12.7mm、εr≈4 → ≈2.95GHz
  （"3GHz 残桩"惯例）。
"""

from __future__ import annotations

import pytest

from rfauto.core.fab_check import (
    FabProfileError,
    check_backdrill,
    check_stub_resonance,
    stub_resonance_ghz,
)
from rfauto.service.fab_service import check_stub_backdrill_dfm

#: 手算锚（GHz，见模块 docstring 逐位推导）
ANCHOR_10MM_ER4 = 3.747405725
ANCHOR_20MM_ER4 = 1.8737028625
ANCHOR_2MM_ER4 = 18.737028625
ANCHOR_1MM_ER4 = 37.47405725


# ── stub_resonance_ghz：闭式锚 + 输入守卫 ────────────────────────


def test_stub_resonance_anchor_exact() -> None:
    assert stub_resonance_ghz(10.0, 4.0) == pytest.approx(
        ANCHOR_10MM_ER4, rel=1e-12)


def test_stub_resonance_simonovich_scale() -> None:
    # 0.5in≈12.7mm FR-4 → ≈2.95GHz："3GHz 残桩"量级互证
    f = stub_resonance_ghz(12.7, 4.0)
    assert f == pytest.approx(2.9507, rel=1e-4)
    assert 2.9 < f < 3.0


@pytest.mark.parametrize("bad_len", [0.0, -1.0, "abc", None, True, False])
def test_stub_resonance_rejects_bad_len(bad_len: object) -> None:
    with pytest.raises(FabProfileError):
        stub_resonance_ghz(bad_len, 4.0)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad_er", [0.0, -2.0, "x", None, True])
def test_stub_resonance_rejects_bad_er(bad_er: object) -> None:
    with pytest.raises(FabProfileError):
        stub_resonance_ghz(10.0, bad_er)  # type: ignore[arg-type]


# ── check_stub_resonance：带内/带外/门限余量/信息行 ────────────────


def test_check_stub_violation_below_nyquist() -> None:
    rows = check_stub_resonance(20.0, 4.0, nyquist_ghz=2.5)
    assert len(rows) == 1
    v = rows[0]
    assert v["code"] == "STUB_RES"
    assert v["field"] == "fres_ghz"
    assert v["value"] == pytest.approx(ANCHOR_20MM_ER4, rel=1e-9)
    assert v["limit"] == pytest.approx(2.5, rel=1e-12)
    assert "notch" in v["detail"]


def test_check_stub_pass_above_nyquist() -> None:
    assert check_stub_resonance(20.0, 4.0, nyquist_ghz=1.0) == []


def test_check_stub_margin_frac() -> None:
    # fres=1.8737：1.0×1.6=1.6 → 过；1.2×1.6=1.92 → 违规
    assert check_stub_resonance(20.0, 4.0, nyquist_ghz=1.6) == []
    rows = check_stub_resonance(20.0, 4.0, nyquist_ghz=1.6, margin_frac=1.2)
    assert len(rows) == 1
    assert rows[0]["code"] == "STUB_RES"
    assert rows[0]["limit"] == pytest.approx(1.92, rel=1e-12)


def test_check_stub_info_without_nyquist() -> None:
    # nyquist=None → 只报信息行不算违规（聚合方按 _INFO 后缀分离）
    rows = check_stub_resonance(20.0, 4.0)
    assert len(rows) == 1
    v = rows[0]
    assert v["code"] == "STUB_RES_INFO"
    assert v["code"].endswith("_INFO")
    assert v["value"] == pytest.approx(ANCHOR_20MM_ER4, rel=1e-9)


@pytest.mark.parametrize("bad_nyq", [0.0, -1.0, True])
def test_check_stub_rejects_bad_nyquist(bad_nyq: object) -> None:
    with pytest.raises(FabProfileError):
        check_stub_resonance(20.0, 4.0, nyquist_ghz=bad_nyq)  # type: ignore[arg-type]


def test_check_stub_rejects_bad_margin() -> None:
    with pytest.raises(FabProfileError):
        check_stub_resonance(20.0, 4.0, nyquist_ghz=1.0, margin_frac=True)
    with pytest.raises(FabProfileError):
        check_stub_resonance(20.0, 4.0, nyquist_ghz=1.0, margin_frac=0.0)


# ── check_backdrill：正常 / over-drill / under-drill / 链路一致 ────


def test_backdrill_normal_pass() -> None:
    # 残余 1.0mm ≥ 0.5；fres=37.474GHz ≥ 2.5 → 零违规
    assert check_backdrill(4.0, 3.0, 0.5, 4.0, nyquist_ghz=2.5) == []


def test_backdrill_normal_info_chain() -> None:
    # 无 nyquist → 链路只产信息行（残余 1.0mm → fres=37.474GHz）
    rows = check_backdrill(4.0, 3.0, 0.5, 4.0)
    assert len(rows) == 1
    assert rows[0]["code"] == "STUB_RES_INFO"
    assert rows[0]["value"] == pytest.approx(ANCHOR_1MM_ER4, rel=1e-9)


def test_backdrill_over_drill() -> None:
    rows = check_backdrill(2.0, 2.5, 0.5, 4.0, nyquist_ghz=2.5)
    assert len(rows) == 1
    v = rows[0]
    assert v["code"] == "BACKDRILL_OD"
    assert v["field"] == "backdrill_depth_mm"
    assert v["value"] == pytest.approx(2.5)
    assert v["limit"] == pytest.approx(2.0)


def test_backdrill_depth_equals_span_zero_residual() -> None:
    # 深度==跨度 → 残余 0：不抛（谐振面跳过），只报余量面
    rows = check_backdrill(2.0, 2.0, 0.5, 4.0, nyquist_ghz=2.5)
    assert [v["code"] for v in rows] == ["BACKDRILL_UNDER"]


def test_backdrill_under_drill_with_resonance_chain() -> None:
    # 残余 2.0mm < 3.5 → UNDER；fres=18.737 < 20 → STUB_RES 同报
    rows = check_backdrill(4.0, 2.0, 3.5, 4.0, nyquist_ghz=20.0)
    codes = {v["code"] for v in rows}
    assert codes == {"BACKDRILL_UNDER", "STUB_RES"}
    under = next(v for v in rows if v["code"] == "BACKDRILL_UNDER")
    assert under["value"] == pytest.approx(2.0)
    assert under["limit"] == pytest.approx(3.5)
    stub = next(v for v in rows if v["code"] == "STUB_RES")
    assert stub["value"] == pytest.approx(ANCHOR_2MM_ER4, rel=1e-9)


def test_backdrill_zero_depth_equals_plain_stub() -> None:
    # 深度 0 = 未背钻：残余=全跨度，等价于直接对跨度做残桩门
    assert check_backdrill(4.0, 0, 0.5, 4.0, nyquist_ghz=5.0) == []


@pytest.mark.parametrize("args", [
    (True, 1.0, 0.5),  # span bool
    (4.0, True, 0.5),  # depth bool
    (4.0, -0.1, 0.5),  # depth 负
    (4.0, 1.0, 0.0),  # min_remaining 0
    (4.0, 1.0, True),  # min_remaining bool
    (0.0, 1.0, 0.5),  # span 0
])
def test_backdrill_rejects_invalid(args: tuple[object, ...]) -> None:
    span, depth, min_rem = args
    with pytest.raises(FabProfileError):
        check_backdrill(span, depth, min_rem, 4.0,  # type: ignore[arg-type]
                        nyquist_ghz=2.5)


# ── service.check_stub_backdrill_dfm：JSON 进出薄壳 ───────────────


def test_service_stub_backdrill_violation() -> None:
    # 残余 2.0mm → fres=18.737GHz < 20 → STUB_RES 违规
    out = check_stub_backdrill_dfm(4.0, 2.0, 1.0, 4.0, nyquist_ghz=20.0)
    assert out["ran"] is True
    assert out["ok"] is False
    assert out["residual_stub_mm"] == pytest.approx(2.0)
    assert out["fres_ghz"] == pytest.approx(ANCHOR_2MM_ER4, rel=1e-9)
    assert [v["code"] for v in out["violations"]] == ["STUB_RES"]
    assert out["info"] == []
    assert out["checked"]["nyquist_ghz"] == 20.0


def test_service_stub_backdrill_pass() -> None:
    out = check_stub_backdrill_dfm(4.0, 3.0, 0.5, 4.0, nyquist_ghz=2.5)
    assert out["ran"] is True
    assert out["ok"] is True
    assert out["violations"] == []
    assert out["fres_ghz"] == pytest.approx(ANCHOR_1MM_ER4, rel=1e-9)


def test_service_stub_backdrill_info_not_violation() -> None:
    # 无 nyquist：信息行落 info 不算违规，ok 仍 True
    out = check_stub_backdrill_dfm(4.0, 3.0, 0.5, 4.0)
    assert out["ran"] is True
    assert out["ok"] is True
    assert out["violations"] == []
    assert len(out["info"]) == 1
    assert out["info"][0]["code"] == "STUB_RES_INFO"
    assert out["fres_ghz"] == pytest.approx(ANCHOR_1MM_ER4, rel=1e-9)


def test_service_stub_backdrill_over_drill() -> None:
    out = check_stub_backdrill_dfm(2.0, 2.5, 0.5, 4.0, nyquist_ghz=2.5)
    assert out["ran"] is True
    assert out["ok"] is False
    assert [v["code"] for v in out["violations"]] == ["BACKDRILL_OD"]
    assert "fres_ghz" not in out
    assert out["residual_stub_mm"] == 0.0


def test_service_stub_backdrill_invalid_input() -> None:
    out = check_stub_backdrill_dfm(True, 1.0, 0.5, 4.0)
    assert out["ran"] is False
    assert out["ok"] is None
    assert out["errors"]
