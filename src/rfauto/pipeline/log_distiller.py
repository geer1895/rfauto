"""工件语义化 LogDistiller。

把 openEMS stdout / HFSS(PyAEDT) 日志 / 审计 JSON 解析压缩为结构化 digest
（rc / errors / warnings / 关键指标 / 失败签名），供最小自愈环、MCP 工具
与 UI 消费（LLM 先读语义压缩工件可显著省 token）。

设计约束：
- 纯规则、确定性、best-effort：**解析失败/输入损坏绝不向调用方抛异常**
  （#105：观测性代码不得成为业务主路径的故障点）。
- 只用标准库（re/json/pathlib），不引入新依赖，不联网、不碰真机。
- 不产生物理数字：digest 里所有数值都取自日志原文，只做单位标量转换，
  不做任何物理推断（数值只在确定性内核）。
- 失败签名只做"指纹识别"（本模块）；根因判定与建议动作属确定性 critique，
  在 pipeline/self_heal.critique_failure（LLM 只解释不判定）。

报告结构（JSON 友好）::

    {
      "ok": bool,                # 是否产出了可用 digest（空/异常类型输入为 False）
      "source": "openems" | "hfss" | "audit_json" | "generic" | "empty" | "unparsed",
      "rc": int | None,
      "errors": [str, ...],      # 上限 _MAX_ERRORS 条（语义压缩）
      "warnings": [str, ...],
      "metrics": {name: float},  # 关键指标（最后一次出现=最终值）
      "signatures": [str, ...],  # 已知失败签名 id
      "n_lines": int,
      "truncated": bool,
      "notes": [str, ...],
    }
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 常量：数据源 / 失败签名 / 阈值
# ---------------------------------------------------------------------------

SOURCE_OPENEMS = "openems"
SOURCE_HFSS = "hfss"
SOURCE_AUDIT_JSON = "audit_json"
SOURCE_GENERIC = "generic"
SOURCE_EMPTY = "empty"
SOURCE_UNPARSED = "unparsed"

_SOURCES = (
    SOURCE_OPENEMS,
    SOURCE_HFSS,
    SOURCE_AUDIT_JSON,
    SOURCE_GENERIC,
    SOURCE_EMPTY,
    SOURCE_UNPARSED,
)

# 失败签名（纯解析指纹；根因/建议见 pipeline/self_heal._ROOT_CAUSE_CATALOG）
SIG_TIMESTEP_COLLAPSE = "timestep_collapse"
SIG_NEAR_COINCIDENT_MESH = "near_coincident_mesh"
SIG_CALCPORT_INDEX_ERROR = "calcport_index_error"
SIG_EXCITATION_DEAD = "excitation_dead"
SIG_WAVE_PORT_OFFICIAL = "wave_port_official_mismatch"
SIG_LICENSE_UNAVAILABLE = "license_unavailable"
SIG_SESSION_LOST = "hfss_session_lost"
SIG_NONCONVERGENCE = "solver_nonconvergence"
SIG_GEOMETRY_BUILD = "geometry_build_failure"
SIG_NONPHYSICAL_GAIN = "nonphysical_gain"
SIG_NONZERO_EXIT = "nonzero_exit"

# CFL 时间步塌缩地板（#152）：正常 FDTD 步长 1e-12~1e-13，塌缩后 <1e-16
TIMESTEP_COLLAPSE_FLOOR_S = 1e-15
# 非物理增益阈值（与 core.objectives 无源性 1% 容差同族）
MAX_ABS_S_TOLERANCE = 1.01

_MAX_ERRORS = 20
_MAX_WARNINGS = 20
_MAX_LINES = 20000
_MAX_ITEM_CHARS = 300

# 文本指纹规则：(签名 id, 正则)。多行用 [\s\S]{0,400}? 连接（同一指纹常跨行）。
_SIGNATURE_RULES: tuple[tuple[str, str], ...] = (
    (SIG_CALCPORT_INDEX_ERROR,
     r"calcport[\s\S]{0,400}?indexerror|indexerror[\s\S]{0,400}?calcport"),
    (SIG_NEAR_COINCIDENT_MESH,
     r"near[-\s]coincident|minimum\s+(?:grid\s+)?spacing|min(?:imum)?\.?\s+grid\s+spacing"),
    (SIG_EXCITATION_DEAD,
     r"all values are zero|excitation[\s\S]{0,60}?\bzero\b|no energy deposited"),
    (SIG_WAVE_PORT_OFFICIAL,
     r"wave\s*port[\s\S]{0,80}?(?:size|dimension|too small|larger than|official|cutoff)"
     r"|port[\s\S]{0,40}?dimension[\s\S]{0,40}?(?:too small|exceed)"),
    (SIG_LICENSE_UNAVAILABLE,
     r"license[\s\S]{0,80}?(?:not available|unavailable|denied|cannot checkout|no such feature|expired)"
     r"|flexlm|license\s+error"),
    (SIG_SESSION_LOST,
     r"\bgrpc\b|connection dropped|session lost|connection\s+reset"),
    (SIG_NONCONVERGENCE,
     r"did not converge|not converged|non-?convergence|\bnan\b|diverged"),
    (SIG_GEOMETRY_BUILD,
     r"object name[\s\S]{0,40}?(?:conflict|exist)|already exists"
     r"|boolean[\s\S]{0,30}?failed|invalid geometry"),
)

# 指标抽取规则：(canonical 名, 正则)。取最后一次匹配=最终值。
_METRIC_PATTERNS: tuple[tuple[str, str], ...] = (
    ("timestep_s",
     r"(?:time\s*step|timestep|dt)\s*[:=]?\s*([0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)(?:\s*s\b)?"),
    ("max_timesteps",
     r"(?:max(?:imum)?\.?\s*(?:number\s+of\s+)?|number\s+of\s+)?timesteps?\s*[:=]?\s*(\d{3,})"),
    ("courant", r"courant\s*(?:factor|number)?\s*[:=]?\s*([0-9]*\.?[0-9]+)"),
    ("delta_s",
     r"(?:max(?:imum)?\s*)?delta\s*s\s*[:=]?\s*([0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)"),
    ("adaptive_passes", r"adaptive\s*pass\s*[:=#]?\s*(\d+)"),
    ("solve_time_s",
     r"(?:total\s*)?(?:solve|elapsed|simulation)\s*time\s*[:=]?\s*([0-9]*\.?[0-9]+)\s*s"),
)

_S_PARAM_RE = re.compile(
    r"\bS(\d)(\d)\b(?:[^\n]{0,30}?)(-?\d+(?:\.\d+)?)\s*dB"
    r"|\bS(\d)(\d)\s*[:=]\s*(-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)

_RC_RES = (
    re.compile(r"return\s*code\s*[:=]?\s*(-?\d+)", re.IGNORECASE),
    re.compile(r"exit\s*code\s*[:=]?\s*(-?\d+)", re.IGNORECASE),
    re.compile(r"\brc\s*[:=]\s*(-?\d+)", re.IGNORECASE),
)

_ERROR_LINE_RE = re.compile(
    r"(^\s*\[?\s*(?:error|fatal|critical|exception|traceback)\b)"
    r"|(\berror\b\s*[:：])|(\[\s*error\s*\])",
    re.IGNORECASE,
)
_WARN_LINE_RE = re.compile(r"\bwarn(?:ing)?\b", re.IGNORECASE)

_KNOWN_METRIC_KEYS = (
    "timestep_s",
    "max_timesteps",
    "courant",
    "delta_s",
    "adaptive_passes",
    "solve_time_s",
    "max_abs_s",
    "s11_db",
    "s21_db",
    "s11_db_min",
    "f0_ghz",
)


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _as_float(value: Any) -> float | None:
    """尽力转 float（排除 bool），失败/非有限返回 None。"""
    if isinstance(value, bool) or value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _clip(text: str) -> str:
    text = str(text).strip()
    return text if len(text) <= _MAX_ITEM_CHARS else text[:_MAX_ITEM_CHARS] + "…"


def _strings(value: Any) -> list[str]:
    """把任意值展平为字符串列表（best-effort，不抛）。"""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(_strings(item))
        return out
    if isinstance(value, dict):
        try:
            return [json.dumps(value, ensure_ascii=False, default=str)]
        except Exception:
            return [str(value)]
    return [str(value)]


def _dedupe(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _empty_digest(source: str, notes: list[str] | None = None) -> dict[str, Any]:
    return {
        "ok": False,
        "source": source,
        "rc": None,
        "errors": [],
        "warnings": [],
        "metrics": {},
        "signatures": [],
        "n_lines": 0,
        "truncated": False,
        "notes": list(notes or []),
    }


# ---------------------------------------------------------------------------
# 结构化输入（审计 JSON / 已解析 digest）
# ---------------------------------------------------------------------------

def _metrics_from_mapping(obj: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    metrics = obj.get("metrics")
    if isinstance(metrics, dict):
        for key, val in metrics.items():
            num = _as_float(val)
            if num is not None:
                out[str(key)] = num
    for key in _KNOWN_METRIC_KEYS:
        if key in obj:
            num = _as_float(obj[key])
            if num is not None:
                out[key] = num
    return out


def _rc_from_mapping(obj: dict[str, Any]) -> int | None:
    for key in ("rc", "returncode", "return_code", "exit_code", "exitcode"):
        if key in obj:
            num = _as_float(obj[key])
            if num is not None:
                return int(num)
    return None


def _scan_text(text: str) -> tuple[list[str], list[str], dict[str, float], int | None, bool]:
    """文本扫描：返回 (errors, warnings, metrics, rc, truncated)。"""
    lines = text.splitlines()
    truncated = len(lines) > _MAX_LINES
    if truncated:
        lines = lines[-_MAX_LINES:]

    errors: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, float] = {}

    for line in lines:
        if _ERROR_LINE_RE.search(line):
            errors.append(_clip(line))
        elif _WARN_LINE_RE.search(line):
            warnings.append(_clip(line))

    for name, pattern in _METRIC_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            num = _as_float(match.group(1))
            if num is not None:
                metrics[name] = num  # 最后一次匹配=最终值

    for match in _S_PARAM_RE.finditer(text):
        if match.group(1) is not None:
            key = f"s{match.group(1)}{match.group(2)}_db"
            num = _as_float(match.group(3))
        else:
            key = f"s{match.group(4)}{match.group(5)}_db"
            num = _as_float(match.group(6))
        if num is not None:
            metrics[key] = num

    rc: int | None = None
    for pattern in _RC_RES:
        found = pattern.search(text)
        if found:
            num = _as_float(found.group(1))
            if num is not None:
                rc = int(num)
                break

    return _dedupe(errors), _dedupe(warnings), metrics, rc, truncated


def _detect_source(text: str) -> str:
    low = text.lower()
    if "openems" in low or "csxcad" in low:
        return SOURCE_OPENEMS
    if "pyaedt" in low or "ansys" in low or "hfss" in low:
        return SOURCE_HFSS
    return SOURCE_GENERIC


def _collect_signatures(text: str, metrics: dict[str, float], rc: int | None) -> list[str]:
    signatures: list[str] = []
    for sig, pattern in _SIGNATURE_RULES:
        if re.search(pattern, text, re.IGNORECASE):
            signatures.append(sig)
    timestep = metrics.get("timestep_s")
    if timestep is not None and timestep < TIMESTEP_COLLAPSE_FLOOR_S:
        signatures.append(SIG_TIMESTEP_COLLAPSE)
    max_abs_s = metrics.get("max_abs_s")
    if max_abs_s is not None and max_abs_s > MAX_ABS_S_TOLERANCE:
        signatures.append(SIG_NONPHYSICAL_GAIN)
    if rc is not None and rc != 0:
        signatures.append(SIG_NONZERO_EXIT)
    return _dedupe(signatures)


def _mapping_to_text(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        return str(obj)


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------

def distill_log(
    raw: Any,
    *,
    source: str = "auto",
    max_lines: int = _MAX_LINES,
) -> dict[str, Any]:
    """把日志/审计产物压缩为结构化 digest（纯规则、确定性、best-effort）。

    参数：
        raw: openEMS stdout（str）/ HFSS(PyAEDT) 日志（str）/ 审计 JSON
            （dict 或 JSON 文本）/ bytes / 行列表；None/空串等返回降级 digest。
        source: 强制数据源标识；"auto"（默认）按内容指纹判定。
        max_lines: 文本扫描上限（超出保留尾部=最近输出，并置 truncated）。

    返回：见模块 docstring。任何内部异常都被吞掉并降级为 ok=False，
    绝不向调用方抛（#105）。
    """
    try:
        return _distill(raw, source=source, max_lines=max_lines)
    except Exception as exc:  # pragma: no cover - 兜底路径，正常输入不触发
        return _empty_digest(SOURCE_UNPARSED, notes=[f"distill 内部异常（已降级）: {exc!r}"])


def _distill(raw: Any, *, source: str, max_lines: int) -> dict[str, Any]:
    if raw is None:
        return _empty_digest(SOURCE_EMPTY, notes=["空输入（None）"])

    if isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw).decode("utf-8", errors="replace")

    errors: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, float] = {}
    rc: int | None = None
    n_lines = 0
    truncated = False
    notes: list[str] = []
    detected = source

    if isinstance(raw, dict):
        rc = _rc_from_mapping(raw)
        errors.extend(_strings(raw.get("errors", raw.get("error"))))
        warnings.extend(_strings(raw.get("warnings", raw.get("warning"))))
        metrics.update(_metrics_from_mapping(raw))
        text = _mapping_to_text(raw)
        if source == "auto":
            detected = SOURCE_AUDIT_JSON
    elif isinstance(raw, list):
        text_parts: list[str] = []
        for item in raw:
            if isinstance(item, dict):
                if rc is None:
                    rc = _rc_from_mapping(item)
                errors.extend(_strings(item.get("errors", item.get("error"))))
                warnings.extend(_strings(item.get("warnings", item.get("warning"))))
                metrics.update(_metrics_from_mapping(item))
                text_parts.append(_mapping_to_text(item))
            else:
                errors.extend(_strings(item))
                text_parts.append(str(item))
        text = "\n".join(text_parts)
        if source == "auto":
            detected = SOURCE_AUDIT_JSON
    elif isinstance(raw, str):
        text = raw
        if not text.strip():
            return _empty_digest(SOURCE_EMPTY, notes=["空输入（空白字符串）"])
        stripped = text.lstrip()
        if stripped[:1] in "{[":  # 疑似 JSON：解析成功则走结构化口径
            try:
                parsed = json.loads(text)
            except (ValueError, TypeError):
                parsed = None
            if isinstance(parsed, (dict, list)):
                return _distill(parsed, source=source, max_lines=max_lines)
            notes.append("疑似 JSON 但解析失败，按纯文本扫描（best-effort）")
        if source == "auto":
            detected = _detect_source(text)
    else:
        return _empty_digest(
            SOURCE_UNPARSED,
            notes=[f"不支持的输入类型: {type(raw).__name__}（best-effort 降级）"],
        )

    if max_lines > 0 and max_lines != _MAX_LINES:
        lines = text.splitlines()
        if len(lines) > max_lines:
            text = "\n".join(lines[-max_lines:])
            truncated = True

    t_errors, t_warnings, t_metrics, t_rc, t_truncated = _scan_text(text)
    errors.extend(t_errors)
    warnings.extend(t_warnings)
    for key, val in t_metrics.items():
        metrics.setdefault(key, val)
    if rc is None:
        rc = t_rc
    truncated = truncated or t_truncated
    n_lines = len(text.splitlines())

    errors = _dedupe(errors)
    warnings = _dedupe(warnings)
    if len(errors) > _MAX_ERRORS:
        notes.append(f"errors 截断：{len(errors)} → {_MAX_ERRORS}（语义压缩）")
        errors = errors[:_MAX_ERRORS]
    if len(warnings) > _MAX_WARNINGS:
        notes.append(f"warnings 截断：{len(warnings)} → {_MAX_WARNINGS}（语义压缩）")
        warnings = warnings[:_MAX_WARNINGS]

    signatures = _collect_signatures(text, metrics, rc)
    return {
        "ok": True,
        "source": detected,
        "rc": rc,
        "errors": errors,
        "warnings": warnings,
        "metrics": metrics,
        "signatures": signatures,
        "n_lines": n_lines,
        "truncated": truncated,
        "notes": notes,
    }


def distill_file(path: str | Path, *, source: str = "auto",
                 max_lines: int = _MAX_LINES) -> dict[str, Any]:
    """读取文件并蒸馏（best-effort：读失败返回降级 digest，不抛）。"""
    try:
        p = Path(path)  # #140：注解写 Path 不代表调用方传 Path
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return _empty_digest(SOURCE_UNPARSED, notes=[f"读取失败（已降级）: {exc!r}"])
    return distill_log(text, source=source, max_lines=max_lines)
