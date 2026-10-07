"""NX-9 CISPR 25 限值数据面单测（2026-10-03）。

锚树口径（#118/#122）：
- 双源一致格逐位钉（Tekbox p.14 vs EMCCalc，检索 2026-10-03）：
  CEV LW/MW/SW 三段 PK/QP/AV 九值 + CB/VHF 30-54 + TV-I PK/AV。
- 分歧格弃录语义：88-108 AVG 在 CEV 表 = None（not_defined）。
- 段边界/重叠：多段重叠取最严（TV-I 41-88 与 VHF mobile 68-87 在
  76-87 重叠——CEV 侧 PK 34 vs 38 取 34）；表外 no_band。
- RE ALSE：TU Dortmund 点核格（FM avg=18、RKE-300 avg=18）双源标记。
- provenance 拷贝面：改外部常量不影响出口（深拷贝语义）。
"""
from __future__ import annotations

import pytest

from rfauto.core import cispr25_limits as c25


def test_cev_dual_source_cells():
    """CEV 双源一致格逐位钉（Tekbox=EMCCalc，检索 2026-10-03）。"""
    expect = {
        (0.15, 0.30): (70.0, 57.0, 50.0),   # LW
        (0.53, 1.8): (54.0, 41.0, 34.0),    # MW
        (5.9, 6.2): (53.0, 40.0, 33.0),     # SW
        (26.0, 28.0): (44.0, 31.0, 24.0),   # CB
        (30.0, 54.0): (44.0, 31.0, 24.0),   # VHF 30-54
    }
    segs = {(s["f_lo_mhz"], s["f_hi_mhz"]): s
            for s in c25.CISPR25_CEV_CLASS5}
    for key, (pk, qp, avg) in expect.items():
        seg = segs[key]
        assert (seg["peak"], seg["qp"], seg["avg"]) == (pk, qp, avg)
        assert seg["dual_source"] is True
    # TV Band I：PK/AV 双源，QP 分歧弃录
    tv = segs[(41.0, 88.0)]
    assert tv["peak"] == 34.0 and tv["avg"] == 24.0
    assert tv["qp"] is None
    assert tv["dual_source"] is True


def test_cev_disputed_cells_omitted():
    """分歧格弃录：CEV 88-108 AVG=None；provenance 记录分歧。"""
    fm = next(s for s in c25.CISPR25_CEV_CLASS5 if s["f_hi_mhz"] == 108.0)
    assert fm["peak"] == 38.0 and fm["qp"] == 25.0
    assert fm["avg"] is None  # 28 vs 18 分歧 → 弃录
    prov = c25.cispr25_class5_cev()["provenance"]
    assert any("88-108" in d for d in prov["disputed_omitted"])


def test_re_alse_tu_dortmund_crosschecked_cells():
    """RE：TU Dortmund 点核格（FM/RKE avg=18）双源标记。"""
    segs = {(s["f_lo_mhz"], s["f_hi_mhz"]): s
            for s in c25.CISPR25_RE_ALSE_CLASS5}
    fm = segs[(76.0, 108.0)]
    rke = segs[(300.0, 330.0)]
    assert fm["avg"] == 18.0 and fm["dual_source"] is True
    assert rke["avg"] == 18.0 and rke["dual_source"] is True
    # 单源格标记如实
    lw = segs[(0.15, 0.30)]
    assert lw["dual_source"] is False


def test_margin_report_overlap_takes_strictest():
    """重叠区取最严：CEV f=80 MHz 落 TV-I(34) 与 VHF 68-87(38) → 34。"""
    out = c25.cispr25_margin_report("cev", 80.0, 30.0, "peak")
    assert out["verdict"] == "pass"
    assert out["worst_limit"] == 34.0
    assert out["margin_db"] == pytest.approx(4.0)
    assert out["n_bands"] == 3  # TV-I + VHF 68-87 + FM 76-108 三段重叠


def test_margin_report_pass_fail_and_no_band():
    fail = c25.cispr25_margin_report("re_alse", 98.0, 45.0, "peak")
    assert fail["verdict"] == "fail"
    assert fail["worst_limit"] == 38.0
    assert fail["margin_db"] == pytest.approx(-7.0)
    nb = c25.cispr25_margin_report("re_alse", 3.0, 20.0, "peak")
    assert nb["verdict"] == "no_band"


def test_margin_report_not_defined_detector():
    """段内检波器无格 → not_defined（GPS L1 peak 无格）。"""
    out = c25.cispr25_margin_report("re_alse", 1575.0, 12.0, "peak")
    assert out["verdict"] == "not_defined"
    out2 = c25.cispr25_margin_report("cev", 90.0, 30.0, "avg")  # FM avg 弃录
    assert out2["verdict"] == "not_defined"


def test_copy_face_isolation():
    """出口为拷贝面：改返回段表不影响常量。"""
    face = c25.cispr25_class5_re_alse()
    face["segments"][0]["peak"] = 0.0
    assert c25.CISPR25_RE_ALSE_CLASS5[0]["peak"] == 46.0


def test_invalid_inputs_rejected():
    with pytest.raises(ValueError):
        c25.cispr25_margin_report("xxx", 100.0, 30.0, "peak")
    with pytest.raises(ValueError):
        c25.cispr25_margin_report("cev", 100.0, 30.0, "rms")
    with pytest.raises(ValueError):
        c25.cispr25_margin_report("cev", -1.0, 30.0, "peak")


def test_units_and_alse_note():
    assert c25.cispr25_class5_cev()["unit"] == "dBuV"
    assert c25.cispr25_class5_re_alse()["distance_m"] == 1.0
    assert "ISO 11452-2" in c25.ALSE_1M_NOTE
