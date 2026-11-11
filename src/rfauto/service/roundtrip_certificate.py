"""round-trip 二值证书通用件（T-Q23，验证闭环方法论显性化）。

来源与定位：CAD-Agent 交接文档 §8.3 验证闭环 + §12.5 Weave 思想
（arXiv 2607.03835："round-trip 逐 net 比对给二值正确性证书"）——
**任何"生成 → 回读 → 比对"闭环的确定性判据**，不绑具体格式解析。
首个仓内实例=``service/kicad_sch_service.py`` 的 kicad_sch 证书
（T-Q22/Q-CAD-1）：spec → render → readback_nets → 逐 net 比对。

通用件只提供三件（铁律 7：零数值生产，比对逻辑纯函数）：

1. :class:`RoundtripCertificate`——通用证书结构（六字段 schema，
   ``pass`` 判定权在结构层强制与 diff 一致，杜绝"diff 非空却 pass"
   的不一致证书被构造出来）；
2. :func:`fold_diff`——比对 fold：三族 diff（missing/extra/mismatch）
   确定性排序（族序 missing→extra→mismatch，族内按 key 字典序；
   mismatch 条目的对称差逐侧 ``sorted()``）+ :func:`is_pass` 判定。
   **不绑 kicad 专用解析**（回读属 adapters 层，比对键词表经
   :class:`DiffNaming` 注入——kicad 实例传 ``missing_net/extra_net/
   pin_mismatch`` 词表即逐字节复现其既有 diff 形态）；
3. :func:`build_certificate`——expected/readback 两个 keyed 集合 →
   中立词表六字段证书 dict（新消费者默认入口）。

确定性契约：fold 保证**条目顺序**确定；条目内 items 列表**按调用方
原样收录**（missing/extra 侧）——调用方必须自带确定性排序（kicad 实例
两侧均预排序）；mismatch 侧对称差由 fold 排序。零行为变化锚：kicad
实例改造后同输入证书逐字节同（runs/aurora_q/qcad2/ 快照双跑实证，
tests/unit/test_kicad_sch_gen.py 53 测零回归）。
"""

from __future__ import annotations

import hashlib
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "NEUTRAL_NAMING",
    "DiffNaming",
    "RoundtripCertificate",
    "build_certificate",
    "digest_text",
    "fold_diff",
    "is_pass",
]


# ---------------------------------------------------------------------------
# 词表（diff 条目键名/种类名——域实例按需覆写，缺省=中立形态）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiffNaming:
    """diff 条目词表：三族 kind 名 + key 字段名 + items 字段名。

    缺省中立形态::

        {"kind": "missing_key",  "key": K, "expected_items": [...]}
        {"kind": "extra_key",    "key": K, "readback_items": [...]}
        {"kind": "item_mismatch", "key": K,
         "missing_items": [...], "extra_items": [...]}

    域实例覆写示例（kicad_sch，与 T-Q22 既有证书逐字段同形）::
        DiffNaming(key_name="net", missing_kind="missing_net",
                   extra_kind="extra_net", mismatch_kind="pin_mismatch",
                   expected_items_name="expected_pins",
                   readback_items_name="readback_pins",
                   mismatch_missing_items_name="missing_pins",
                   mismatch_extra_items_name="extra_pins")
    """

    key_name: str = "key"
    missing_kind: str = "missing_key"
    extra_kind: str = "extra_key"
    mismatch_kind: str = "item_mismatch"
    #: missing 条目的 items 字段名（expected 侧全集）。
    expected_items_name: str = "expected_items"
    #: extra 条目的 items 字段名（readback 侧全集，原样收录）。
    readback_items_name: str = "readback_items"
    #: mismatch 条目的 expected 独有 items 字段名（fold 排序）。
    mismatch_missing_items_name: str = "missing_items"
    #: mismatch 条目的 readback 独有 items 字段名（fold 排序）。
    mismatch_extra_items_name: str = "extra_items"


#: 缺省中立词表（新消费者直接用）。
NEUTRAL_NAMING = DiffNaming()


# ---------------------------------------------------------------------------
# 比对 fold（确定性三族 diff + pass 判定）
# ---------------------------------------------------------------------------


def fold_diff(
    expected: Mapping[str, Sequence[Hashable]],
    readback: Mapping[str, Sequence[Hashable]],
    *,
    naming: DiffNaming = NEUTRAL_NAMING,
) -> list[dict[str, Any]]:
    """expected vs readback 两个 keyed 集合 → 三族 diff（确定性排序）。

    族序固定 **missing → extra → mismatch**，族内按 key 字典序；
    mismatch=两侧同 key 但 items 集不等，对称差逐侧 ``sorted()`` 列出。
    missing/extra 条目的 items **原样收录**调用方序列（调用方自带确定性
    排序——见模块 docstring 契约）；同输入同输出（纯函数，零数值生产）。
    """
    n = naming
    exp_keys, rb_keys = set(expected), set(readback)
    diff: list[dict[str, Any]] = []
    for key in sorted(exp_keys - rb_keys):
        diff.append({"kind": n.missing_kind, n.key_name: key,
                     n.expected_items_name: list(expected[key])})
    for key in sorted(rb_keys - exp_keys):
        diff.append({"kind": n.extra_kind, n.key_name: key,
                     n.readback_items_name: list(readback[key])})
    for key in sorted(exp_keys & rb_keys):
        exp, got = set(expected[key]), set(readback[key])
        if exp != got:
            diff.append({"kind": n.mismatch_kind, n.key_name: key,
                         n.mismatch_missing_items_name: sorted(exp - got),
                         n.mismatch_extra_items_name: sorted(got - exp)})
    return diff


def is_pass(diff: Sequence[Mapping[str, Any]]) -> bool:
    """pass 判定单源：diff 空 = PASS（二值，不凑绿——#122 同纪律）。"""
    return not diff


# ---------------------------------------------------------------------------
# 通用证书结构（六字段 schema；pass 与 diff 一致性结构层强制）
# ---------------------------------------------------------------------------


class RoundtripCertificate(BaseModel):
    """round-trip 二值证书通用结构（任务书钉死的六字段形态）。

    ``pass`` 字段经别名暴露（``passed`` 是 Python 侧合法名）；缺省由
    diff 推导，且**恒强制 ``pass == (diff 为空)``**——不一致输入在
    构造期即拒绝。序列化用 :meth:`to_dict`（键序=字段序，含 ``pass``）。
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    input_digest: str | None = None
    readback_digest: str | None = None
    diff: list[dict[str, Any]] = Field(default_factory=list)
    passed: bool = Field(alias="pass")
    checked_items: int = Field(default=0, ge=0)
    checked_at_runtime: bool = False

    @model_validator(mode="before")
    @classmethod
    def _derive_pass(cls, data: Any) -> Any:
        """``pass`` 缺省=由 diff 推导（显式传入值不覆盖）。"""
        if isinstance(data, dict) and "pass" not in data \
                and "passed" not in data:
            data = {**data, "pass": not (data.get("diff") or [])}
        return data

    @model_validator(mode="after")
    def _pass_must_match_diff(self) -> RoundtripCertificate:
        if self.passed != (not self.diff):
            raise ValueError(
                "pass 判定必须与 diff 一致（pass = diff 为空）；不一致证书"
                "禁止构造（二值判定权在 fold，不凑绿）")
        return self

    def to_dict(self) -> dict[str, Any]:
        """六字段 dict（键 ``pass``，键序=字段序；service 层 JSON 进出）。"""
        return self.model_dump(by_alias=True)


def digest_text(text: str) -> str:
    """文本 SHA-256 摘要（input/readback digest 的单源；纯函数）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 构造入口（新消费者默认路径）
# ---------------------------------------------------------------------------


def build_certificate(
    expected: Mapping[str, Sequence[Hashable]],
    readback: Mapping[str, Sequence[Hashable]],
    *,
    input_digest: str | None = None,
    readback_digest: str | None = None,
    checked_at_runtime: bool = False,
    checked_items: int | None = None,
    naming: DiffNaming = NEUTRAL_NAMING,
) -> dict[str, Any]:
    """比对 fold → 六字段证书 dict（中立词表）。

    ``checked_items`` 缺省=被查 key 总数（``|expected ∪ readback|``）；
    ``checked_at_runtime`` 由调用方声明（真机/运行时回读=True，离线
    静态比对=False——诚实上报口径，与 #122 不凑绿同源）。
    """
    diff = fold_diff(expected, readback, naming=naming)
    cert = RoundtripCertificate(
        input_digest=input_digest,
        readback_digest=readback_digest,
        diff=diff,
        passed=is_pass(diff),
        checked_items=(len(set(expected) | set(readback))
                       if checked_items is None else checked_items),
        checked_at_runtime=checked_at_runtime,
    )
    return cert.to_dict()
