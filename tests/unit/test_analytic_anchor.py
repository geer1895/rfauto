"""XA-10 analytic-anchor 锚族测试（register_analytic_anchor helper + 覆盖统计面）。

规格：研究扩充 round18 XA-10（内核侧 analytic-
anchor 轻条目；与 XC-T 模板侧锚注册划界）。closedform-v1 形态先例=ge8 TA
三批 10 锚（2026-10-02，schiffman/qwt_multisection/sicl/nway_wilkinson/
diplexer/ridged_wg 六族）。

锚树：
1. helper 形态——closedform-v1 同构（kind=constant / engine_pair.calibrated=
   closedform / uncertainty kind=identity / quantity.name=f"{family}_{quantity}"
   / status=experimental / fallback=closed_form），产出过 AnchorRecord.
   from_dict 构造期校验（坏段 fail-fast，不产出不可装载条目）；
2. 消费链（XC-A 回归）——helper 产出锚可被 AnchorSet.find_anchors 与
   apply_anchor_correction 消费：identity band=0 过不确定度门；percent /
   absolute 双修正路径；rounding_band 覆盖形态同样过门；
3. 覆盖统计——anchor_coverage 按族统计（多族锚重复计席/通配 "*" 桶/
   空 family "<none>" 桶/确定性排序）；
4. 真仓一致性——注册表 .closedform-v* 锚与 helper 规范形逐键一致；
   closedform_total=26（ge8 TA 三批 10+ge8b WA 席1 hmsiw 1+ge8b WB 席B9 2
   +ge8e X5 批 13，后随批次更新）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rfauto.core.anchors import (
    EXPECTED_ANCHOR_COUNT,
    AnchorRecord,
    AnchorSet,
    anchor_coverage,
    apply_anchor_correction,
    find_anchors,
    register_analytic_anchor,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]

_SEM = "恒等：闭式回代单测钉（abs=1e-9）；真机首判窗 ±5%（XA-10 测试语义）"


def _live_anchor_set() -> AnchorSet:
    from rfauto.infra.anchors_store import load_anchors

    return load_anchors()


# ── 1. helper 形态（closedform-v1 规范形）──────────────────────────────────

def test_helper_canonical_closedform_v1_shape() -> None:
    raw = register_analytic_anchor("demo", "f0_ghz", 2.45, _SEM, unit="GHz")
    assert raw["anchor_id"] == "demo.f0_ghz.closedform-v1"
    assert raw["kind"] == "constant"  # 不开新 ANCHOR_KINDS（规格口径）
    assert raw["template_family"] == ["demo"]
    assert raw["engine_pair"] == {"calibrated": "closedform", "referee": None}
    assert raw["quantity"] == {
        "name": "demo_f0_ghz", "unit": "GHz", "semantics": _SEM}
    assert raw["value"] == 2.45
    assert raw["uncertainty"] == {
        "value": 0.0, "kind": "identity",
        "note": "闭式恒等锚（analytic light entry）"}
    assert raw["status"] == "experimental"  # 真机首判前如实状态（TA 批先例）
    assert raw["fallback"] == "closed_form"
    assert raw["domain"] is None and raw["provenance"] == {}
    assert raw["consumers"] == []
    rec = AnchorRecord.from_dict(raw)  # 注册表装载同源校验
    assert rec.version == 1 and rec.kind == "constant"


def test_helper_quantity_name_and_version_overrides() -> None:
    raw = register_analytic_anchor("demo", "q2", 1.0, _SEM,
                                   quantity_name="custom_name", version=2)
    assert raw["anchor_id"] == "demo.q2.closedform-v2"
    assert raw["quantity"]["name"] == "custom_name"
    assert AnchorRecord.from_dict(raw).version == 2


def test_helper_uncertainty_override_rounding_band() -> None:
    # sicl 先例同款：rounding_band 覆盖 identity（4 位舍入回代带）
    unc = {"value": 0.005, "kind": "rounding_band", "note": "4 位舍入回代"}
    raw = register_analytic_anchor("demo", "z0_ohm", 50.0, _SEM,
                                   unit="ohm", uncertainty=unc)
    assert raw["uncertainty"] == unc


def test_helper_fail_fast_bad_segments_and_fields() -> None:
    with pytest.raises(ValueError, match="family"):
        register_analytic_anchor("Bad-Family", "q", 1.0, _SEM)
    with pytest.raises(ValueError, match="quantity"):
        register_analytic_anchor("demo", "a.b", 1.0, _SEM)
    with pytest.raises(ValueError, match="source"):
        register_analytic_anchor("demo", "q", 1.0, _SEM, source="ClosedForm")
    with pytest.raises(ValueError, match="semantics"):
        register_analytic_anchor("demo", "q", 1.0, "   ")
    with pytest.raises(ValueError, match="version"):
        register_analytic_anchor("demo", "q", 1.0, _SEM, version=0)
    with pytest.raises(ValueError, match="status"):
        register_analytic_anchor("demo", "q", 1.0, _SEM, status="bogus")


# ── 2. 消费链（XC-A 回归：find_anchors / apply_anchor_correction）──────────

def _demo_set() -> AnchorSet:
    # active 形态（AGREE 仲裁翻 active 后的规范消费形态——XC-A 修正链只认
    # active，experimental 席被 gate 2 如实拒绝，见下方专属测试）。
    return AnchorSet([
        register_analytic_anchor("demo", "bias_pct", 1.5, _SEM,
                                 unit="percent", status="active"),
        register_analytic_anchor("demo", "f0_ghz", 2.45, _SEM, unit="GHz",
                                 status="active"),
        register_analytic_anchor("demo", "z0_ohm", 50.0, _SEM, unit="ohm",
                                 status="active",
                                 uncertainty={"value": 0.005,
                                              "kind": "rounding_band"}),
    ])


def test_helper_anchor_findable_by_id_segment_and_quantity_name() -> None:
    aset = _demo_set()
    # anchor_id 中段命中
    assert [r.anchor_id for r in find_anchors("demo", "f0_ghz",
                                              anchor_set=aset)] == [
        "demo.f0_ghz.closedform-v1"]
    # quantity.name 命中（f"{family}_{quantity}" 缺省构词）
    assert [r.anchor_id for r in find_anchors("demo", "demo_bias_pct",
                                              anchor_set=aset)] == [
        "demo.bias_pct.closedform-v1"]
    # 其他族查询零命中（不串族）
    assert find_anchors("other", "f0_ghz", anchor_set=aset) == []


def test_helper_experimental_anchor_hidden_by_default_active_only() -> None:
    # 缺省 active_only=True：experimental 恒等锚不进消费投影（真机首判前
    # 不冒充可消费锚——TA 批先例语义）；active_only=False 如实可见。
    aset = AnchorSet([register_analytic_anchor("demo", "f0_ghz", 2.45, _SEM,
                                               unit="GHz")])
    assert find_anchors("demo", "f0_ghz", anchor_set=aset) == []
    found = find_anchors("demo", "f0_ghz", active_only=False,
                         anchor_set=aset)
    assert [r.anchor_id for r in found] == ["demo.f0_ghz.closedform-v1"]
    assert found[0].status == "experimental"


def test_xca_correction_identity_band_zero_passes_gate() -> None:
    env = apply_anchor_correction("demo", "f0_ghz", params={},
                                  design_value=2.40,
                                  anchor_set=_demo_set())
    assert env["applied"] is True
    assert env["delta_kind"] == "absolute"
    assert env["delta"] == pytest.approx(0.05)
    assert env["band"] == 0.0  # identity 恒等锚零带宽
    assert env["reason"] is None


def test_xca_correction_percent_unit_path() -> None:
    env = apply_anchor_correction("demo", "bias_pct", anchor_set=_demo_set())
    assert env["applied"] is True
    assert env["delta_kind"] == "percent"
    assert env["delta"] == 1.5  # percent 锚 Δ=锚值本身


def test_xca_correction_rounding_band_within_gate() -> None:
    # 0.005/50 = 1e-4 ≤ 0.10 → 过不确定度门（sicl 先例量级）
    env = apply_anchor_correction("demo", "z0_ohm", design_value=50.0,
                                  anchor_set=_demo_set())
    assert env["applied"] is True
    assert env["band"] == pytest.approx(0.005)
    assert env["band_rel"] == pytest.approx(1e-4)


def test_xca_correction_active_only_default_excludes_experimental() -> None:
    # experimental 恒等锚如实被拒（status_not_active——真机首判前不修正）；
    # 锚注册翻 active 后修正链即通——「注册链默认动作」的消费语义。
    raw_exp = register_analytic_anchor("demo", "f0_ghz", 2.45, _SEM,
                                       unit="GHz")
    env = apply_anchor_correction("demo", "f0_ghz", design_value=2.4,
                                  anchor_set=AnchorSet([raw_exp]))
    assert env["applied"] is False and env["reason"] == "status_not_active"
    assert env["candidates"][0]["rejected_reason"] == "status:experimental"
    raw_active = register_analytic_anchor("demo", "f0_ghz", 2.45, _SEM,
                                          unit="GHz", status="active")
    env2 = apply_anchor_correction("demo", "f0_ghz", design_value=2.40,
                                   anchor_set=AnchorSet([raw_active]))
    assert env2["applied"] is True


# ── 3. 覆盖统计面（anchor_coverage）────────────────────────────────────────

def _coverage_fixture_set() -> AnchorSet:
    a1 = register_analytic_anchor("fam_a", "q1", 1.0, _SEM, status="active")
    a2 = register_analytic_anchor("fam_a", "q2", 2.0, _SEM)
    b1 = register_analytic_anchor("fam_b", "q1", 3.0, _SEM)
    multi = register_analytic_anchor("fam_c", "q1", 4.0, _SEM)
    multi["template_family"] = ["fam_a", "fam_b"]  # 多族锚：两族各计一席
    wild = register_analytic_anchor("wild", "q9", 5.0, _SEM)
    wild["template_family"] = ["*"]  # 通配族单列
    orphan = register_analytic_anchor("tmp", "qx", 6.0, _SEM)
    orphan["template_family"] = []  # 空 family → "<none>" 桶
    return AnchorSet([a1, a2, b1, multi, wild, orphan])


def test_coverage_counts_families_with_repeat_seats() -> None:
    cov = anchor_coverage(_coverage_fixture_set())
    assert cov["total_anchors"] == 6
    assert set(cov["families"]) == {"*", "<none>", "fam_a", "fam_b"}
    assert cov["family_count"] == 4
    fam_a = cov["families"]["fam_a"]
    assert fam_a["total"] == 3  # a1/a2 + multi 重复计席
    assert fam_a["active"] == 1
    assert fam_a["closedform"] == 3
    assert fam_a["anchor_ids"] == sorted(fam_a["anchor_ids"])
    # 族席之和 >= 总锚数（多族重复计席如实口径）
    assert sum(f["total"] for f in cov["families"].values()) >= \
        cov["total_anchors"]
    # 多族锚在 fam_b 也计席（b1 + multi）
    assert cov["families"]["fam_b"]["total"] == 2


def test_coverage_deterministic_sorted() -> None:
    cov1 = anchor_coverage(_coverage_fixture_set())
    cov2 = anchor_coverage(_coverage_fixture_set())
    assert cov1 == cov2
    assert list(cov1["families"]) == sorted(cov1["families"])


def test_coverage_live_registry_single_source_and_closedform_family() -> None:
    cov = anchor_coverage(_live_anchor_set())
    assert cov["total_anchors"] == EXPECTED_ANCHOR_COUNT  # 单源对账（#231）
    # ge8 TA 三批恒等锚：closedform_total=25，族分席在档（后随批次更新）
    assert cov["closedform_total"] == 37  # Phase 6 W6-F +1（cpw 二义核验裁 A）# 历史：ge8e X5 批 +13（atten×4/ratrace×2/stripline×2/slotline/siw/monopole/coil_nfc/pyramid_horn）→ Phase 4 W4-E 批 +10（cps×2/suspended_stripline×2/cheb_g×5/msl_cpw）
    fams = cov["families"]
    for fam, n in (("schiffman", 1), ("qwt_multisection", 1), ("sicl", 2),
                   ("nway_wilkinson", 2), ("diplexer", 2), ("ridged_wg", 2)):
        assert fams[fam]["closedform"] == n, fam
        assert fams[fam]["total"] == n, fam
    # 恒等锚全 experimental（真机首判前如实状态：六族均零 active）
    assert all(fams[f]["by_status"].get("active", 0) == 0
               for f in ("schiffman", "qwt_multisection", "sicl",
                         "nway_wilkinson", "diplexer", "ridged_wg"))


# ── 4. 真仓一致性：注册表 .closedform-v* 锚与 helper 规范形逐键一致 ────────

def test_live_closedform_anchors_conform_to_helper_canonical_form() -> None:
    live = _live_anchor_set()
    closed = [r for r in live.records if ".closedform-v" in r.anchor_id]
    assert len(closed) == 37  # Phase 6 W6-F +1（cpw.z0_ohm 二义核验裁 A=CPWG/50Ω）# 上一行历史：ge8 TA 三批（schiffman/qwt/sicl×2/nway×2/diplexer×2/ridged×2）+ ge8b WA 席1（hmsiw.fc_ghz）+ ge8b WB 席B9（isl_shielded.eps_eff+vivaldi_tsa.f_low）+ ge8e X5 批 +13 → Phase 4 W4-E 批 +10（cps×2/suspended_stripline×2/cheb_g×5/msl_cpw）
    for rec in closed:
        segs = rec.anchor_id.split(".")
        fam, qty = segs[0], segs[1]
        rebuilt = register_analytic_anchor(
            fam, qty, rec.value, "semantics 不对拍（自由文本）",
            unit=rec.raw["quantity"].get("unit"),
            quantity_name=rec.raw["quantity"]["name"],
            uncertainty=rec.raw["uncertainty"],
            status=rec.status,
            consumers=rec.consumers,
            domain=rec.raw["domain"],  # X5 批起 closedform 锚可带域盒
        )
        for key in ("anchor_id", "kind", "template_family", "engine_pair",
                    "value", "status", "fallback", "domain", "uncertainty"):
            assert rebuilt[key] == rec.raw[key], (rec.anchor_id, key)
        assert rebuilt["quantity"]["name"] == rec.raw["quantity"]["name"]
