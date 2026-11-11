"""STDF 解析服务包装（aurora_q 席位 Q-X88，2026-11-08）。

:mod:`rfauto.core.stdf_parser`（单源解析内核）的规则 4 JSON 进出薄
包装——信封走 :mod:`rfauto.service.envelope` 构造器（AU-2 契约，禁
裸 dict），零数值逻辑（记录流状态机/字节序自描述/链读全在 core 确
定性内核；铁律 7）。

三函数（与 CLI 薄壳同源同名消费；无 MCP 面——本席任务书未含工具叶）：

- :func:`parse_stdf_file`：全结构化解析（far/mir_summary/parts/
  parametric_tests/functional_tests/counts/stats）——``stdf parse
  --json`` 信封即本函数全量返回；
- :func:`stdf_report`：盘点报告（yield 两口径 + fail parts + 记录
  计数）——``stdf report --json`` 消费面；
- :func:`stdf_test_detail`：按 test_num 的 PTR 测量值序列明细——
  查询只读面（test_num 未知 → error 信封，errors 带 hint）。

错误归一（任务书口径）：文件不存在/不可读（OSError）/垃圾流或 FAR
缺失或 CPU_TYPE fail-closed（StdfParseError）→ error 信封（errors 恒
list[str]），CLI 层 exit 1；**流中截断不是 error**——fail-soft 已收
面随 ``truncated=True`` + warnings 如实带回（ATE 崩溃中途落盘的半截
STDF 是常态，noonchen/stdfFixer 存在本身即此证据；任务书只钉
"FAR 缺失→ok=False"）。纯只读：不落盘、零网络、零真机。

本模块不设 ``__all__``（无 __all__ 的非门面文件不进
tests/gold/public_api.json——verilog_netlist_service 同款先例，新模块
零金快照漂移）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.core.stdf_parser import (
    StdfParseError,
    parse_stdf_bytes,
    stdf_fail_parts,
    stdf_test_lookup,
    stdf_yield,
)
from rfauto.service.envelope import error_envelope, ok_envelope


def _load_doc(
    path: str | Path,
) -> tuple[dict[str, Any], None] | tuple[None, dict[str, Any]]:
    """读+解析 → (doc, None) 或 (None, error_envelope)。

    错误分型（任务书口径）：不存在/不可读（OSError）/垃圾流·FAR 缺失·
    CPU_TYPE 非 1/2（StdfParseError）→ error 信封；流中截断不是错误
    （fail-soft truncated=True 已收面如实保留）。gdsii_service 两步合
    成同款。
    """
    p = Path(path)
    if not p.exists():
        return None, error_envelope(f"STDF 文件不存在: {p}")
    try:
        data = p.read_bytes()
    except OSError as exc:
        return None, error_envelope(f"STDF 文件不可读: {exc}")
    try:
        doc = parse_stdf_bytes(data)
    except StdfParseError as exc:
        return None, error_envelope(f"STDF 解析失败: {exc}")
    return doc, None


def parse_stdf_file(path: str | Path) -> dict[str, Any]:
    """STDF 文件 → 全结构化信封（far/mir_summary/两测试面/counts/stats）。

    信封：``{"ok": True, "path", "far", "atr_records", "mir_summary",
    "pcr_records", "parts", "parametric_tests", "functional_tests",
    "counts", "stats", "warnings", "truncated"}`` / error 信封（errors
    恒 list[str]）。纯只读：不落盘、零网络、零真机。
    """
    doc, err = _load_doc(path)
    if err is not None:
        return err
    return ok_envelope(
        path=str(path),
        far=doc["far"],
        atr_records=doc["atr_records"],
        mir_summary=doc["mir_summary"],
        pcr_records=doc["pcr_records"],
        parts=doc["parts"],
        parametric_tests=doc["parametric_tests"],
        functional_tests=doc["functional_tests"],
        counts=doc["counts"],
        stats=doc["stats"],
        warnings=doc["warnings"],
        truncated=doc["truncated"],
    )


def stdf_report(path: str | Path) -> dict[str, Any]:
    """STDF 文件 → 盘点报告信封（yield 两口径 + fail parts + 计数）。

    ``stdf report`` 叶消费面：far 摘要、mir lot/part、yield（core
    :func:`rfauto.core.stdf_parser.stdf_yield` PCR 优先 PRR 兜底两口
    径）、fail parts 清单、深解记录计数与流统计。截断态随
    ``truncated`` 如实披露。
    """
    doc, err = _load_doc(path)
    if err is not None:
        return err
    far = doc.get("far") or {}
    mir = doc.get("mir_summary") or {}
    return ok_envelope(
        path=str(path),
        far=far,
        lot_id=mir.get("lot_id"),
        part_typ=mir.get("part_typ"),
        oper_nam=mir.get("oper_nam"),
        mode_cod=mir.get("mode_cod"),
        yield_stats=stdf_yield(doc),
        fail_parts=stdf_fail_parts(doc),
        counts=doc["counts"],
        stats=doc["stats"],
        warnings=doc["warnings"],
        truncated=doc["truncated"],
    )


def stdf_test_detail(path: str | Path, test_num: int) -> dict[str, Any]:
    """STDF 文件 → 按 test_num 的 PTR 测量值序列明细信封。

    ``test_num`` 在该文件无 PTR 记录 → error 信封（可用性提示随
    errors 给出——消费方不猜）。命中 → ok 信封带 ``points``（流序：
    meas_val/pass/units/lo_limit/hi_limit/head_num/site_num）与
    ``n_points``。
    """
    doc, err = _load_doc(path)
    if err is not None:
        return err
    points = stdf_test_lookup(doc, test_num)
    if not points:
        n_tests = len(doc.get("parametric_tests") or [])
        return error_envelope(
            f"测试号 {test_num} 在本文件无 PTR 记录"
            f"（parametric 记录总数 {n_tests}）")
    return ok_envelope(
        path=str(path),
        test_num=test_num,
        points=points,
        n_points=len(points),
        counts=doc["counts"],
        stats=doc["stats"],
        warnings=doc["warnings"],
        truncated=doc["truncated"],
    )
