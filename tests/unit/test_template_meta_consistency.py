"""元数据漂移收口：TEMPLATE_META/TEMPLATE_NOMINAL ↔ docs meta.yaml 一致性钉。

背景（离线几何审计发现）：src 元数据表与 docs/templates/<t>/meta.yaml
静态文档存在四处漂移——① patch 幽灵参数 feed_w_mm（已修：替换为渲染实读
的 feed_offset_mm）；② wilkinson nominal 疑复制 branchline（1.87/1.1/18.4
→真值 0.604/1.113/18.1）；③ ratrace 缺 r_ring_mm 且 w_ring 0.6035 为 gysel
臂宽串位（→0.604 + 补 r_ring_mm 17.344）；④ 多模板 mesh_resolution
yaml=1.0 vs meta=0.0。②③④ 的 docs 侧修复与原 KNOWN_* 台账清偿已完成
（2026-09-15，docs-ledger-meta-clear 项），本文件不再保留任何白名单。

本文件与 test_template_geometry_audit 的既有测试分工（不重复造）：
- 那边管"声明即生效"（参数扰动改变几何）与条目集/identity；
- 这边管"字段级漂移"（params 键集、nominal 键集与数值、mesh 值的逐模板
  对账），src ↔ docs 两侧全部严格相等——任何一侧再漂移即红，防新旧数字
  并存（#97）；另钉 patch 配方不得回流幽灵几何参数。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters.openems_templates import TEMPLATE_META, TEMPLATE_NOMINAL
from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES  # 协同：冻结集复用

TEMPLATES = sorted(EXPECTED_TEMPLATES)


def _meta_yaml(template: str) -> dict:
    path = REPO / "docs" / "templates" / template / "meta.yaml"
    assert path.exists(), path
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ─── src 侧自洽（严格，无白名单）─────────────────────────────────────────────

def test_src_declared_params_have_nominal_values():
    """TEMPLATE_META.params 每个声明键在 TEMPLATE_NOMINAL 有标称值（自洽）。"""
    for t in TEMPLATES:
        missing = set(TEMPLATE_META[t]["params"]) - set(TEMPLATE_NOMINAL[t])
        assert not missing, f"{t}: 声明参数缺标称值 {sorted(missing)}"


def test_src_patch_has_no_ghost_param():
    """回归钉：patch 声明渲染实读的 feed_offset_mm，幽灵 feed_w_mm 不得回流。"""
    assert "feed_offset_mm" in TEMPLATE_META["patch"]["params"]
    assert "feed_w_mm" not in TEMPLATE_META["patch"]["params"]
    assert "feed_w_mm" not in TEMPLATE_NOMINAL["patch"]
    assert TEMPLATE_NOMINAL["patch"]["feed_offset_mm"] == 10.0  # 对齐 fake/schema/docs


def test_patch_recipe_has_no_dead_geometric_param():
    """回归钉：patch 配方几何键 ⊆ TEMPLATE_META[patch].params。

    recipes/patch_antenna_v1.yaml 的幽灵 feed_w_mm 已删（全仓 grep 无消费者，
    仅配方自身残留）；本钉防其回流，也防配方再引入渲染不读的几何键。
    非几何键（f0_ghz/z0_ohm/substrate）不在约束内。
    """
    path = REPO / "recipes" / "patch_antenna_v1.yaml"
    assert path.exists(), path
    recipe = yaml.safe_load(path.read_text(encoding="utf-8"))
    keys = set(recipe.get("params") or {})
    assert "feed_w_mm" not in keys, "patch 配方幽灵参数 feed_w_mm 回流"
    ghost = {k for k in keys if k.endswith("_mm")} - set(TEMPLATE_META["patch"]["params"])
    assert not ghost, (
        f"patch_antenna_v1.yaml 出现 TEMPLATE_META[patch].params 之外的几何键 "
        f"{sorted(ghost)}——渲染不消费即幽灵参数，禁止回流"
    )


# ─── src ↔ docs 字段级对账 ───────────────────────────────────────────────────

@pytest.mark.parametrize("template", TEMPLATES)
def test_params_key_set_matches_docs(template):
    """params 键集 src ↔ docs 完全一致（修复后 18 模板无一漂移）。"""
    data = _meta_yaml(template)
    src_keys = set(TEMPLATE_META[template]["params"])
    yaml_keys = set(data.get("params") or [])
    assert src_keys == yaml_keys, (
        f"{template}: params 键集漂移 src-only={sorted(src_keys - yaml_keys)} "
        f"yaml-only={sorted(yaml_keys - src_keys)}"
    )


@pytest.mark.parametrize("template", TEMPLATES)
def test_nominal_key_set_matches_docs(template):
    """nominal 键集 src ↔ docs 完全一致（台账已清偿，无白名单）。"""
    data = _meta_yaml(template)
    src_keys = set(TEMPLATE_NOMINAL[template])
    yaml_keys = set(data.get("nominal_params") or {})
    assert src_keys == yaml_keys, (
        f"{template}: nominal 键集漂移 src-only={sorted(src_keys - yaml_keys)} "
        f"yaml-only={sorted(yaml_keys - src_keys)}"
    )


def _num(v):
    """标量 → float；列表（coupled_bpf widths_mm/gaps_mm）→ 逐项 float 元组；
    dict/嵌套列表（ms_array_NxN cell_map 逐胞参数表）→ 结构化归一元组
    （键排序递归，数值叶 float、字符串叶原样）——既有标量/浮点列表行为
    不变（严格超集）。"""
    if isinstance(v, dict):
        return tuple(sorted((k, _num(x)) for k, x in v.items()))
    if isinstance(v, (list, tuple)):
        return tuple(_num(x) for x in v)
    if isinstance(v, str):
        return v
    return float(v)


def _close(a, b) -> bool:
    if isinstance(a, tuple) or isinstance(b, tuple):
        return (isinstance(a, tuple) and isinstance(b, tuple) and len(a) == len(b)
                and all(_close(x, y) for x, y in zip(a, b, strict=True)))
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    return abs(a - b) <= 1e-9 * max(1.0, abs(a))


@pytest.mark.parametrize("template", TEMPLATES)
def test_nominal_values_match_docs(template):
    """共享键数值 src ↔ docs 严格一致（台账已清偿，无白名单）。"""
    data = _meta_yaml(template)
    src_vals = {k: _num(v) for k, v in TEMPLATE_NOMINAL[template].items()}
    yaml_vals = {k: _num(v) for k, v in (data.get("nominal_params") or {}).items()}
    for key in sorted(set(src_vals) & set(yaml_vals)):
        assert _close(src_vals[key], yaml_vals[key]), (
            f"{template}.{key}: src={src_vals[key]} yaml={yaml_vals[key]} 漂移"
        )


@pytest.mark.parametrize("template", TEMPLATES)
def test_mesh_resolution_matches_docs(template):
    """mesh_resolution_mm src ↔ docs 严格一致（台账已清偿，无白名单）。"""
    data = _meta_yaml(template)
    src_mesh = float(TEMPLATE_META[template]["mesh_resolution_mm"])
    yaml_mesh = data.get("mesh_resolution_mm")
    assert yaml_mesh is None or float(yaml_mesh) == src_mesh, (
        f"{template}: mesh_resolution src={src_mesh} yaml={yaml_mesh} 漂移"
    )


# ─── 拓扑受限模板能力位（2026-09-18 收口：先期只覆盖了新模板
#     hairpin_alt，同向本体漏标）──────────────────────────────────────────────────

#: 拓扑受限（战役精算不可用）模板名单=docs 侧 campaign_capable=false 的唯一台账：
#: 名单内模板 meta.yaml 必须带 campaign_capable: false + campaign_capable_reasons +
#: campaign_unlock_criteria 三键（与 docs/templates/hairpin_alt/meta.yaml 同构）。
#: 入选判据=真机/闭式证据证明参数空间无自洽设计点（hairpin：同向相邻臂开路端对齐
#: →电/磁耦合反号相消，k_EM 非单调且上限 0.0155≪k_KJ 0.0515，FBW5% 名义无自洽点）。
#: 维护规则：新受限模板→meta 补三键+进本名单；解锁须先过其
#: campaign_unlock_criteria 并同步 topology_service.FILTER_FAMILY_REGISTRY 与 fake
#: 派发口径，campaign_capable 翻 true 后从本名单移除（下方 sweep/名单双向钉会强制）。
CAMPAIGN_RESTRICTED_TEMPLATES = ("hairpin", "hairpin_alt")


@pytest.mark.parametrize("template", CAMPAIGN_RESTRICTED_TEMPLATES)
def test_campaign_restricted_template_has_capability_flag(template):
    """受限模板 docs meta.yaml 必须显式 campaign_capable=false + 原因 + 解锁判据。"""
    data = _meta_yaml(template)
    assert data.get("campaign_capable") is False, (
        f"{template}: 受限名单内模板 campaign_capable 必须显式 false（解锁先过 "
        f"campaign_unlock_criteria 并同步 FILTER_FAMILY_REGISTRY，再移出名单）"
    )
    reasons = data.get("campaign_capable_reasons") or []
    assert reasons and all(isinstance(r, str) and r for r in reasons), (
        f"{template}: campaign_capable_reasons 必须为非空字符串列表"
    )
    criteria = data.get("campaign_unlock_criteria")
    assert isinstance(criteria, dict) and criteria, (
        f"{template}: 必须登记 campaign_unlock_criteria（解锁路径或无解锁路径的显式声明）"
    )


def test_campaign_restricted_templates_are_registered():
    """名单必须是注册集子集（防名单漂移指向不存在/未注册模板）。"""
    unknown = set(CAMPAIGN_RESTRICTED_TEMPLATES) - set(TEMPLATES)
    assert not unknown, f"受限名单含未注册模板 {sorted(unknown)}"


def test_campaign_restricted_sweep_declared_false_all_registered():
    """sweep：docs 声明 campaign_capable=false 的模板必须都进名单（名单=唯一台账）。

    新受限模板（reasons 含"无自洽"类签名或任何形式的能力位标注）落 docs 时若漏进
    名单，此处即红——防止"只标新模板、本体漏标"式缺陷再现。
    """
    declared_false = set()
    for t in TEMPLATES:
        data = _meta_yaml(t)
        if data.get("campaign_capable") is False:
            declared_false.add(t)
    missing = declared_false - set(CAMPAIGN_RESTRICTED_TEMPLATES)
    assert not missing, (
        f"{sorted(missing)}: docs meta.yaml 声明 campaign_capable=false 但未进 "
        f"CAMPAIGN_RESTRICTED_TEMPLATES——请补名单（唯一台账，防本体漏标）"
    )


def test_campaign_restricted_src_registry_consistency():
    """名单内模板若属 FILTER_FAMILY_REGISTRY 家族，src 能力位必须同为 false（双向防漂移）。"""
    from rfauto.service.topology_service import FILTER_FAMILY_REGISTRY

    for t in CAMPAIGN_RESTRICTED_TEMPLATES:
        if t in FILTER_FAMILY_REGISTRY:
            assert FILTER_FAMILY_REGISTRY[t]["campaign_capable"] is False, (
                f"{t}: docs 受限标注与 src FILTER_FAMILY_REGISTRY 能力位漂移——"
                f"解锁/维持两侧必须同步"
            )
