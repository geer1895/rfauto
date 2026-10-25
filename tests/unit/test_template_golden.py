"""EC-8 全模板 golden 几何回归仓（W2-S8，aurora_e）。

钉面：TEMPLATE_META 全部注册族的缺省档渲染产物 vs
tests/golden/template_geometry/<族>.yaml golden 快照——渲染脚本全文
sha256 + CSX 几何段摘要（原语计数+逐原语 nm 级包围盒哈希）+ 网格摘要 +
端口集合。几何/网格/脚本文本任一漂移即红，差异摘要直接给出漂移键。

分工（不重复造）：test_template_geometry_audit 管"画法正确性"（原语非零
体积/进网格/连通性/域声明一致）；本文件管"不漂移"（与首建基线逐字节对
账，openEMS 模板几何的 EC-8 全仓 golden 口径——补 audit 只判性质不钉值
的缺口，patrol §二明证：此前只有 meta 健康审计非几何 golden）。

再生成（显式意图门，防误吞真回归，二选一）：
    RFAUTO_REGEN_GOLDEN=1 环境变量跑本文件（test_golden_regression 先例）；
    或 ``rfauto templates golden-diff --accept``（同笔 service 单源）。

覆盖边界（如实登记）：7 族缺省档被渲染守卫拒绝（combline/interdigital/
sir_bpf/ring_resonator/xcheb_bpf4 缝分辨、isl_shielded/sicl 孔径分辨），
golden 记 status=guard_blocked——其守卫原文与"仍被拒"状态被钉，几何哈希
面如实留白（不绕守卫、不伪造哈希）；geometry_audit 以审计档网格对这 7
族保有性质面覆盖。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters.openems_templates import TEMPLATE_META
from rfauto.service.template_golden_service import (
    GOLDEN_SCHEMA_VERSION,
    compute_template_digest,
    diff_template_golden,
    golden_dir,
    golden_path,
)

#: 再生意图门（显式环境变量；test_golden_regression 同款先例）
_REGEN_ENV = "RFAUTO_REGEN_GOLDEN"

TEMPLATES = sorted(TEMPLATE_META)


def _load_golden(template: str) -> dict:
    path = golden_path(template)
    assert path.exists(), (
        f"{template}: golden 快照缺失（{path}）——首建走 "
        f"`rfauto templates golden-diff --accept` 或 {_REGEN_ENV}=1")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and data.get("template") == template, path
    return data


@pytest.fixture(scope="module")
def tree_diff() -> dict:
    """全树 diff 一次（渲染+exec 约 1-6s），逐族断言消费同一报告。"""
    return diff_template_golden()


def test_golden_coverage_locked():
    """覆盖数锁定：golden 文件集 == TEMPLATE_META 注册集（缺一/多一即红）。"""
    files = {p.stem for p in golden_dir().glob("*.yaml")}
    assert files == set(TEMPLATES), (
        f"golden 覆盖漂移：缺 {sorted(set(TEMPLATES) - files)}，"
        f"多 {sorted(files - set(TEMPLATES))}")
    for name in TEMPLATES:
        data = _load_golden(name)
        assert data.get("schema") == GOLDEN_SCHEMA_VERSION, name
        assert data.get("digest_version") == 1, name


def test_guard_blocked_ledger_is_honest():
    """guard_blocked 族：golden 必无哈希面且 guard_error 原文在档（不伪造）。"""
    for name in TEMPLATES:
        data = _load_golden(name)
        if data.get("status") != "guard_blocked":
            continue
        assert data.get("guard_error"), f"{name}: guard_blocked 缺守卫原文"
        assert "script_sha256" not in data and "csx" not in data, (
            f"{name}: guard_blocked 族不得伪造哈希面")
        current = compute_template_digest(name)
        assert current["status"] == "guard_blocked", (
            f"{name}: golden 记守卫拒绝但当前渲染成功——守卫/缺省档变更，"
            "请评审后 --accept 重钉")
        assert current["guard_error"] == data["guard_error"], (
            f"{name}: 守卫原文漂移（守卫阈值/文案变更）")


@pytest.mark.parametrize("template", TEMPLATES)
def test_template_golden_matches_current(tree_diff, template):
    """逐族：当前渲染 vs golden 逐字节对账（漂移即红+差异摘要）。"""
    if os.environ.get(_REGEN_ENV) == "1":
        from rfauto.service.template_golden_service import (
            accept_template_golden,
        )

        accept_template_golden([template])
        pytest.skip(f"{template}: golden 已按当前渲染重写（{_REGEN_ENV}=1）")
    stored = _load_golden(template)
    current = compute_template_digest(template)
    from rfauto.service.template_golden_service import _diff_one

    diffs = _diff_one(stored, current)
    assert not diffs, (
        f"{template}: golden 几何漂移 {len(diffs)} 项——{diffs}。"
        f"若为有意变更，跑 `rfauto templates golden-diff --accept` "
        f"或 {_REGEN_ENV}=1 重钉（显式评审动作）")
    assert template not in tree_diff["drifts"], tree_diff["drifts"][template]


def test_tree_diff_verdict_clean(tree_diff):
    """CLI 消费面同口径：全树 diff verdict=clean（72 族零漂移零缺失）。"""
    assert tree_diff["verdict"] == "clean", (
        f"verdict={tree_diff['verdict']} drift={sorted(tree_diff['drifts'])} "
        f"missing={tree_diff['missing']} error={tree_diff['errors']}")
    assert tree_diff["n_total"] == len(TEMPLATES)
    # n_clean 含 guard_blocked-clean 族（守卫拒绝且原文一致=零漂移）
    assert tree_diff["n_clean"] == len(TEMPLATES)
    assert tree_diff["n_drift"] == 0 and tree_diff["n_missing"] == 0
    assert tree_diff["n_error"] == 0
