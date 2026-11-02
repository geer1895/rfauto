"""diagram_annotation_service —— 评审标注双层 .drawio 生成入口（T-O8，2026-11-01）。

"算画同源"评审面：底图（既有 rfauto .drawio / 外部 PNG/JPEG 位图）+
标注 JSON → **双层评审图**——底图层锁定（draw.io 编辑器行为级：选中/
拖动被拒；XML 手改不可防=诚实边界，spec §1.2）+ 标注层（三色圈/
编号/右侧意见栏/虚线关联）。横切能力独立成模块（不侵入 T-O1/T-O4/T-O6
三个图服务——PLAN_DRAFT T-O8 行裁决）。

- 装配内核 = core/review_annotation.py（spec 形态单源：
  runs/aurora_o/design_specs/T-O8_ANNOTATION_SPEC.md；标注 JSON 是唯一
  数据源，意见文本/坐标原样标注零换算——铁律 7）；
- 本模块只做：写面纪律（只读 source、只写 out_path——评审原稿不可变，
  与"底图锁定"语义同源的文件系统级对应）→ 内核调用 → 落盘 → JSON
  信封（规则 4：JSON 进出，CLI/MCP 是薄壳）。

确定性：同输入两次调用逐字节同文件（内核 XML 确定性 + 零时间戳）。
负例（schema 违约/target 指错/体积红线/source==out_path 等）显式报错
——以 ok=False 错误信封出（CLI --json 消费同构信封；不静默、不凑绿）。

多评审人合并（aurora_p A4，T-O8 spec §六.3 v2 位）：:func:
`merge_annotate_diagram` 读多份标注（dict/list payload 或 JSON 文件
路径——读盘在本层，core 零 IO 纪律不变）→ core :func:
`merge_annotation_plans`（合并语义单源=runs/aurora_p/a4/MERGE_DESIGN.md：
按 reviewer 名排序稳定合并/评审人调色描边/全局顺序号重编号/逐评审人
计数）→ 落盘单一 .drawio。写面纪律增量：out_path 亦不得与任何标注
JSON 输入同路径。既有 :func:`annotate_diagram` 单评审人路径零变化。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from rfauto.core.review_annotation import (
    build_annotation_plan,
    merge_annotation_plans,
)
from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = ["annotate_diagram", "merge_annotate_diagram"]


def _same_path(a: Any, b: Any) -> bool:
    """同路径判定（Windows 大小写/分隔符不敏感——normcase+#105 .lower()
    双保险；#318 写面守卫家法）。"""
    na = os.path.normcase(os.path.abspath(str(a))).lower()
    nb = os.path.normcase(os.path.abspath(str(b))).lower()
    return na == nb


def annotate_diagram(
    source_path: Any,
    annotations: Any,
    out_path: Any,
    *,
    reviewer: str | None = None,
    image_size: tuple[Any, Any] | None = None,
    image: bool | None = None,
) -> dict[str, Any]:
    """生成评审标注双层 .drawio 文件（底图锁定 + 标注层三件组）。

    Args:
        source_path: 底图路径（.drawio=形态 A 层级锁定 / .png|.jpg|.jpeg=
            形态 B 位图底图；**只读**——评审原稿不可变）。
        annotations: 标注表（顶层 summary+annotations 两键或裸数组；
            标注卡严格六键 id/region/priority/label/comment/target——
            schema 全文见 core/review_annotation.normalize_annotations）。
        out_path: 输出 .drawio 路径（父目录须已存在，不自动建目录；
            **禁与 source 同路径**——覆盖原稿显式报错）。
        reviewer: 评审人署名（写入意见卡/圈 reviewer 属性，可省）。
        image_size: 形态 B 显式像素宽高 ``(w, h)``（图片头解析失败兜底）。
        image: 分型覆盖（None=按后缀自动；True=强制形态 B；False=强制
            形态 A）。

    Returns:
        成功信封::

            {"ok": True, "out_path": str, "n_annotations": int,
             "layers": {"base": "1", "annot": "annot"},
             "base_locked": True, "warnings": [str, ...]}

        ``warnings`` 逐条可断言（零标注/输入 id 撞底图 id/形态 B target
        忽略/图片体积警戒）。失败信封（校验负例/IO 错误）：
        ``{"ok": False, "errors": [str...]}``。
    """
    try:
        src = Path(source_path)  # PathLike 入参第一行收敛（#140）
        out = Path(out_path)
        if _same_path(src, out):
            raise ValueError(
                f"source 与 out_path 同路径（{src}）：评审原稿不可覆盖，"
                "请另给输出路径（写面纪律=只读 source、只写 out_path）")
        plan = build_annotation_plan(
            src, annotations, reviewer=reviewer,
            image_size=image_size, image=image)
        if out.parent and not out.parent.exists():
            raise ValueError(
                f"输出目录不存在：{out.parent}（请先建目录，不自动补救）")
        out.write_text(plan["xml"], encoding="utf-8")
    except (ValueError, TypeError, OSError) as exc:
        return error_envelope(f"{type(exc).__name__}: {exc}")

    return ok_envelope(
        out_path=str(out),
        n_annotations=plan["n_annotations"],
        n_target_edges=plan["n_target_edges"],
        form=plan["form"],
        layers=plan["layers"],
        base_locked=plan["base_locked"],
        warnings=plan["warnings"],
    )


def _resolve_annotations(index: int, payload: Any) -> Any:
    """标注输入收敛（合并入口专用）：dict/list=payload 原样；str/Path=
    JSON 文件路径（必须存在——读盘在本层，core 零 IO 纪律不变）；其余
    显式报错（不静默猜 JSON 字面量，消歧边界钉死）。"""
    if isinstance(payload, (dict, list)):
        return payload
    if isinstance(payload, (str, Path)):
        p = Path(payload)
        if not p.is_file():
            raise ValueError(
                f"entries[{index}] 标注路径不存在或不是文件：{p}"
                "（传 dict/list payload 或存在的 .json 文件路径）")
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"entries[{index}] 标注 JSON 读取失败 {p}："
                f"{type(exc).__name__}: {exc}") from exc
    raise ValueError(
        f"entries[{index}] 的 annotations 必须是 dict/list payload 或 "
        f"JSON 文件路径，收到 {type(payload)!r}")


def merge_annotate_diagram(
    source_path: Any,
    entries: Any,
    out_path: Any,
    *,
    image_size: tuple[Any, Any] | None = None,
    image: bool | None = None,
) -> dict[str, Any]:
    """多评审人标注合并生成单一 .drawio 文件（同一底图多人评审合入）。

    Args:
        source_path: 共用底图路径（.drawio=形态 A / .png|.jpg|.jpeg=形态 B；
            **只读**——评审原稿不可变）。
        entries: ``[(reviewer, annotations), ...]`` 非空序列——reviewer
            必须是非空字符串；annotations 为 dict/list payload 或存在的
            JSON 文件路径（合并语义见 core/review_annotation.
            merge_annotation_plans，设计单源=runs/aurora_p/a4/
            MERGE_DESIGN.md）。
        out_path: 输出 .drawio 路径（父目录须已存在；**禁与 source 或任何
            标注 JSON 输入同路径**——覆盖显式报错）。
        image_size: 形态 B 显式像素宽高 ``(w, h)``。
        image: 分型覆盖（None=按后缀自动；True=强制形态 B；False=强制
            形态 A）。

    Returns:
        成功信封::

            {"ok": True, "out_path": str, "n_annotations": int,
             "n_reviewers": int, "reviewers": [str, ...],
             "per_reviewer": {rev: {total, high, medium, low}},
             "reviewer_colors": {rev: "#hex"}, "n_target_edges": int,
             "form": "A"|"B", "layers": {...}, "base_locked": True,
             "warnings": [str, ...]}

        失败信封：``{"ok": False, "errors": [str...]}``。
    """
    try:
        src = Path(source_path)  # PathLike 入参第一行收敛（#140）
        out = Path(out_path)
        if _same_path(src, out):
            raise ValueError(
                f"source 与 out_path 同路径（{src}）：评审原稿不可覆盖，"
                "请另给输出路径（写面纪律=只读 source、只写 out_path）")
        if not isinstance(entries, (list, tuple)) or not entries:
            raise ValueError(
                "entries 必须是非空 [(reviewer, annotations), ...] 序列，"
                f"收到 {entries!r}")
        resolved: list[tuple[str, Any]] = []
        for k, entry in enumerate(entries):
            if isinstance(entry, (str, bytes)) or not isinstance(
                    entry, (list, tuple)) or len(entry) != 2:
                raise ValueError(
                    f"entries[{k}] 必须是 (reviewer, annotations) 二元组，"
                    f"收到 {entry!r}")
            reviewer, payload = entry
            if isinstance(payload, (str, Path)) and _same_path(payload, out):
                raise ValueError(
                    f"entries[{k}] 标注 JSON 与 out_path 同路径（{out}）："
                    "输出不可覆盖输入")
            resolved.append((reviewer, _resolve_annotations(k, payload)))
        plan = merge_annotation_plans(
            src, resolved, image_size=image_size, image=image)
        if out.parent and not out.parent.exists():
            raise ValueError(
                f"输出目录不存在：{out.parent}（请先建目录，不自动补救）")
        out.write_text(plan["xml"], encoding="utf-8")
    except (ValueError, TypeError, OSError) as exc:
        return error_envelope(f"{type(exc).__name__}: {exc}")

    return ok_envelope(
        out_path=str(out),
        n_annotations=plan["n_annotations"],
        n_reviewers=plan["n_reviewers"],
        reviewers=plan["reviewers"],
        per_reviewer=plan["per_reviewer"],
        reviewer_colors=plan["reviewer_colors"],
        n_target_edges=plan["n_target_edges"],
        form=plan["form"],
        layers=plan["layers"],
        base_locked=plan["base_locked"],
        warnings=plan["warnings"],
    )
