"""Touchstone 解析服务包装（aurora_q Q-X64）。

:mod:`rfauto.core.touchstone_parser`（单源解析内核）的规则 4 JSON 进出薄
包装——信封走 :mod:`rfauto.service.envelope` 构造器（AU-2 契约，禁裸 dict
错误路径），零数值逻辑（格式嗅探、rank 三规则、三格式解码、频轴对齐、
Σ模数形状判定与矩阵健康统计全在 core 确定性内核；铁律 7）。

三函数（无 MCP 面——本席任务书未含工具叶；CLI 薄壳见
cli/domains/touchstone.py，main.py 接线由主代合流统一）：

- :func:`touchstone_info`：格式 + 端口数 rank 三规则证据 + 冲突报告
  （``touchstone info`` 信封；JSON 安全，无矩阵数值）；
- :func:`parse_touchstone_file`：全结构化解析（格式/端口/频段/port_z/
  noise 登记/s_matrix JSON 化+健康统计）——矩阵复杂值以 ``[re, im]``
  对嵌套落信封（``_S_MATRIX_COMPLEX_CAP`` 上限防信封爆炸，截断态带
  ``s_matrix_truncated`` 旗标如实）；
- :func:`touchstone_report`：格式+端口+频段+矩阵健康摘要（无源性
  ``|max eig|≤1+ε`` 如实统计不做硬门）。

错误归一：文件不存在/不可读（OSError）/空文件/无 option line/结构违规
/rank 冲突不可解析（TouchstoneParseError，ValueError 子类 fail-closed）
→ error 信封（errors 恒 list[str]）。解码链=utf-8-sig 优先（BOM 剥离）、
Latin-1 兜底（core 同款；spef/verilog_netlist/sdf service 先例）。纯只
读：不落盘、零网络、零真机、run 湖零写入。

本模块不设 ``__all__``（无 __all__ 的非门面文件不进
tests/gold/public_api.json——sdf_service 同款先例，新模块零金快照漂移）。
"""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from typing import Any

from rfauto.core.touchstone_parser import (
    TouchstoneParseError,
    matrix_health,
    parse_touchstone,
    sniff_touchstone,
)
from rfauto.service.envelope import error_envelope, ok_envelope

#: 信封内 s_matrix 复杂值（[re, im] 对个数）上限——超过则只落首频点
#: preview + truncated 旗标（信封体积守卫，截断态如实声明不静默）。
_S_MATRIX_COMPLEX_CAP = 4096


def _load_sniff(path: str | Path) -> tuple[dict[str, Any], None] | tuple[None, dict[str, Any]]:
    """嗅探 → (sniff, None) 或 (None, error_envelope)。

    错误分型：不存在 / 不可读（OSError）/ 空文件 / 无 option line
    （TouchstoneParseError）→ error 信封。
    """
    try:
        return sniff_touchstone(path), None
    except TouchstoneParseError as exc:
        return None, error_envelope(f"Touchstone 嗅探失败: {exc}")


def _s_matrix_json(
    s_matrix: Any, n_freqs: int, n_ports: int,
) -> dict[str, Any]:
    """np 复矩阵 → JSON 安全形态（[re, im] 对嵌套；超 cap 截断如实）。"""
    if s_matrix is None:
        return {"s_matrix": None, "s_matrix_truncated": False,
                "s_matrix_cap": _S_MATRIX_COMPLEX_CAP,
                "s_matrix_preview": None}
    total = n_freqs * n_ports * n_ports
    if total <= _S_MATRIX_COMPLEX_CAP:
        body: Any = [
            [
                [[float(v.real), float(v.imag)] for v in row]
                for row in point.tolist()
            ]
            for point in s_matrix
        ]
        return {"s_matrix": body, "s_matrix_truncated": False,
                "s_matrix_cap": _S_MATRIX_COMPLEX_CAP,
                "s_matrix_preview": body[0] if body else None}
    preview = [
        [[float(v.real), float(v.imag)] for v in row]
        for row in s_matrix[0].tolist()
    ]
    return {"s_matrix": None, "s_matrix_truncated": True,
            "s_matrix_cap": _S_MATRIX_COMPLEX_CAP,
            "s_matrix_preview": preview,
            "s_matrix_note": (
                f"全矩阵 {total} 复杂值 > cap {_S_MATRIX_COMPLEX_CAP}"
                "——信封只落首频点 preview；全量数值走 core/"
                "touchstone_parser.parse_touchstone（内存态）或 skrf 桥")}


def touchstone_info(path: str | Path) -> dict[str, Any]:
    """格式 + rank 三规则证据 + 冲突报告（``touchstone info`` 信封面）。

    info 是**查询面**：rank 冲突不是查询失败而是查询答案——ok=True 且
    带全量三规则证据 + disagreements（``n_ports=None`` 如实）。结构违规
    （TouchstoneParseError）才是失败态 → error 信封仍带格式+rank 证据。
    """
    sniff, err = _load_sniff(path)
    if err is not None:
        return err
    rank = sniff["rank"]
    freqs: list[float] | None = None
    n_freqs: int | None = None
    band: dict[str, Any] = {"f_min_hz": None, "f_max_hz": None}
    parse_error: str | None = None
    try:
        parsed = parse_touchstone(sniff["path"])
        freqs = parsed["freqs_hz"]
        n_freqs = parsed["n_freqs"]
        if freqs:
            band = {"f_min_hz": min(freqs), "f_max_hz": max(freqs)}
    except TouchstoneParseError as exc:
        # 结构违规态：info 面仍给格式+rank 证据，解析失败如实登记
        parse_error = str(exc)
    return ok_envelope(
        path=str(path),
        format=_format_json(sniff),
        rank=rank,
        n_ports=rank["n_ports"],
        n_freqs=n_freqs,
        freqs_hz=freqs,
        band=band,
        disagreements=rank["disagreements"],
        parse_error=parse_error,
    )


def _format_json(sniff: dict[str, Any]) -> dict[str, Any]:
    """sniff → 信封 format 块（JSON 安全子集）。"""
    return {
        "version": sniff["version"],
        "version_source": sniff["version_source"],
        "freq_unit": sniff["freq_unit"],
        "param_type": sniff["param_type"],
        "data_format": sniff["data_format"],
        "r_ref": sniff["r_ref"],
        "noise_flag": sniff["noise_flag"],
        "mixed_mode": sniff["mixed_mode"],
        "option_line_raw": sniff["option_line_raw"],
        "v2": sniff["v2"],
    }


def parse_touchstone_file(path: str | Path) -> dict[str, Any]:
    """Touchstone 文件 → 全结构化信封（格式/端口/频段/矩阵 JSON 化/健康统计）。

    不存在/空/无 option line/结构违规/rank 冲突 → ok=False 信封（任务书
    契约：rank 冲突=不可解析面，s_matrix 缺失即不产信封成功态——宁
    UNKNOWN 不误判）。矩阵复杂值超 cap → 截断态如实（见
    :func:`_s_matrix_json`）。纯只读。
    """
    try:
        parsed = parse_touchstone(path)
    except TouchstoneParseError as exc:
        return error_envelope(f"Touchstone 解析失败: {exc}")
    if parsed["n_ports"] is None:
        return error_envelope(
            "Touchstone rank 推断冲突/不可解（宁 UNKNOWN 不误判）——"
            "n_ports=None，不产解析成功态",
            path=str(path),
            format=_format_from_parsed(parsed),
            rank=parsed["rank"],
            disagreements=parsed["rank"]["disagreements"],
        )
    n_ports = int(parsed["n_ports"])
    n_freqs = int(parsed["n_freqs"])
    freqs = parsed["freqs_hz"]
    health = matrix_health(parsed["s_matrix"])
    matrix_json = _s_matrix_json(parsed["s_matrix"], n_freqs, n_ports)
    band = {"f_min_hz": min(freqs) if freqs else None,
            "f_max_hz": max(freqs) if freqs else None}
    return ok_envelope(
        path=str(path),
        format=_sniff_like(parsed),
        rank=parsed["rank"],
        n_ports=n_ports,
        n_freqs=n_freqs,
        freqs_hz=freqs,
        band=band,
        port_z=parsed["port_z"],
        noise=parsed["noise"],
        health=health,
        **matrix_json,
        warnings=parsed["warnings"],
    )


def _sniff_like(parsed: dict[str, Any]) -> dict[str, Any]:
    """parse 结果 → 信封 format 块（与 touchstone_info 同形）。"""
    return _format_from_parsed(parsed)


def _format_from_parsed(parsed: dict[str, Any]) -> dict[str, Any]:
    """parse 结果 format 块 → 信封形态（JSON 安全子集，直通零变形）。"""
    fmt = parsed["format"]
    return {
        "version": fmt["version"],
        "version_source": fmt.get("version_source"),
        "freq_unit": fmt["freq_unit"],
        "param_type": fmt["param_type"],
        "data_format": fmt["data_format"],
        "r_ref": fmt["r_ref"],
        "noise_flag": fmt.get("noise_flag"),
        "mixed_mode": fmt.get("mixed_mode"),
        "option_line_raw": fmt["option_line_raw"],
        "v2": fmt["v2"],
    }


def touchstone_report(path: str | Path) -> dict[str, Any]:
    """格式+端口+频段+矩阵健康摘要信封（无源性如实统计不做硬门）。"""
    try:
        parsed = parse_touchstone(path)
    except TouchstoneParseError as exc:
        return error_envelope(f"Touchstone 解析失败: {exc}")
    if parsed["n_ports"] is None:
        return error_envelope(
            "Touchstone rank 推断冲突/不可解（宁 UNKNOWN 不误判）——不产报告",
            path=str(path),
            rank=parsed["rank"],
            disagreements=parsed["rank"]["disagreements"],
        )
    freqs = parsed["freqs_hz"]
    health = matrix_health(parsed["s_matrix"])
    step_stats: dict[str, Any] = {"n_steps": 0, "step_min_hz": None,
                                  "step_max_hz": None}
    if len(freqs) >= 2:
        steps = [b - a for a, b in pairwise(freqs)]
        step_stats = {
            "n_steps": len(steps),
            "step_min_hz": min(steps),
            "step_max_hz": max(steps),
        }
    return ok_envelope(
        path=str(path),
        format={
            "version": parsed["format"]["version"],
            "freq_unit": parsed["format"]["freq_unit"],
            "param_type": parsed["format"]["param_type"],
            "data_format": parsed["format"]["data_format"],
            "r_ref": parsed["format"]["r_ref"],
            "option_line_raw": parsed["format"]["option_line_raw"],
        },
        rank=parsed["rank"],
        n_ports=parsed["n_ports"],
        n_freqs=parsed["n_freqs"],
        band={"f_min_hz": min(freqs) if freqs else None,
              "f_max_hz": max(freqs) if freqs else None},
        freq_step=step_stats,
        port_z=parsed["port_z"],
        health=health,
        noise={"present": parsed["noise"]["present"],
               "n_points": parsed["noise"]["n_points"],
               "note": parsed["noise"]["note"]},
        n_warnings=len(parsed["warnings"]),
        warnings=parsed["warnings"],
    )
