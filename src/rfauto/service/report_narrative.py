"""设计报告叙述生成器：LLM 执笔 + 数字白名单（数值铁律）。

合规形态（「数值只在确定性内核」）：

1. **数字白名单**：从 runs/ 产物或调用方传入的确定性数据递归抽取数字，每个
   条目携带 **value / unit / source(provenance) / label / 容差**；
2. **叙述校验与净化**：从 LLM 叙述里抽出所有数字，逐一比对白名单——命中者
   替换为**带 provenance 的 canonical 形式**，未命中者进入 violations
   （含原文定位），调用方据此**拒绝**；
3. **模板回退**：无 LLM（默认 `llm_fn=None`）时用确定性模板生成
   「决策依据 / 权衡 / 结论」骨架，数字全部取自白名单；
4. **LLM 只作可注入接口**：本模块**不发起任何网络调用**，也不引入 LLM SDK；
   测试通过 monkeypatch 钉住通道（#139）。

设计要点：

- 数字抽取带边界守卫：`S11` / `s11_db_max_in_band` / `v3.12` /
  `20260101_120000_abcd1234` 这类标识符内的数字**不算数字**，避免把
  标签误报为未授权数字；已知单位词表决定单位归属。
- 容差只在白名单条目上声明（默认 0 = 精确）：LLM 把 2.4701 写成 2.47 时，
  只有显式声明 `rel_tol`/`abs_tol` 的条目才接受，且 canonical 化后
  回填的是**内核值** 2.4701，不是 LLM 的近似值。
- provenance 是 best-effort 观测面，但校验是主路径：`check_narrative`
  仅对非法输入类型抛异常，未授权数字一律以数据形式返回，不静默删除。
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

# ─── 单位词表与数字抽取 ──────────────────────────────────────────────────────

# 已知单位（小写归一比较）。未列入的字母串不会吞进单位，避免 "2.4 and" 之类
# 把后续单词当单位。
_KNOWN_UNITS = frozenset(
    {
        "hz", "khz", "mhz", "ghz", "thz",
        "db", "dbi", "dbc", "dbm", "dbv", "dbuv",
        "mm", "cm", "um", "\u00b5m", "nm", "mil", "m", "in",
        "ns", "ps", "us", "\u00b5s", "ms", "s",
        "ohm", "ohms", "\u03a9", "kohm", "mohm",
        "v", "mv", "uv", "kv", "a", "ma", "ua", "w", "mw", "uw", "kw",
        "pf", "nf", "uf", "\u00b5f", "ff", "h", "nh", "uh", "ph",
        "deg", "\u00b0", "%", "ppm",
        "bps", "kbps", "mbps", "gbps",
    }
)

# 数字 token：可带符号、小数、科学计数法。
_NUMBER_RE = re.compile(r"[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?")

# 单位 token：字母/度/微/百分号起头，后接字母数字。
_UNIT_RE = re.compile(r"[A-Za-z\u00b0\u00b5%][A-Za-z0-9\u00b0\u00b5%]*")

# 数字后允许作为“单位起始”的空白。
_SPACE_CHARS = " \t\u00a0"


@dataclass(frozen=True)
class NumberOccurrence:
    """叙述文本里抽到的一个数字及其（可选）单位。"""

    value: float
    text: str
    start: int
    end: int
    unit: str = ""
    unit_start: int = -1
    unit_end: int = -1

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "unit": self.unit,
        }


def _unit_after(text: str, pos: int, *, allow_space: bool) -> tuple[str, int, int]:
    """在 pos 处解析已知单位；返回 `(unit, unit_start, unit_end)`。

    非已知单位返回 `("", -1, -1)`——不消费该 token。
    """
    k = pos
    if allow_space:
        while k < len(text) and text[k] in _SPACE_CHARS:
            k += 1
    m = _UNIT_RE.match(text, k)
    if m is None:
        return "", -1, -1
    token = m.group()
    if token.lower() not in _KNOWN_UNITS:
        return "", -1, -1
    return token, k, m.end()


def extract_numbers(text: str) -> tuple[NumberOccurrence, ...]:
    """从文本抽出所有数字（带边界守卫与单位归属）。

    边界规则（防空转/防误报）：

    - 数字前一个字符是字母/数字/下划线/点 → 视为标识符的一部分，跳过
      （`S11`、`s21_db_mean_in_band`、`v3.12`）；
    - 数字后紧跟字母/数字/下划线且**不是**已知单位 → 跳过
      （`20260101_...` 的下划线续、`12abc`）；
    - 数字后紧跟 `-` / `/` 且再后是数字 → 视为编号（`2026-09-12`），跳过；
    - 数字后紧跟点且再后是数字 → 视为畸形小数点，跳过。

    非 str 输入抛 `TypeError`；空串返回 `()`。
    """
    if not isinstance(text, str):
        raise TypeError("text must be str")
    if not text:
        return ()
    found: list[NumberOccurrence] = []
    for m in _NUMBER_RE.finditer(text):
        start, end = m.start(), m.end()
        if start > 0 and (text[start - 1].isalnum() or text[start - 1] in "_."):
            continue
        nxt = text[end : end + 1]
        if nxt and (nxt.isalnum() or nxt == "_"):
            unit, us, ue = _unit_after(text, end, allow_space=False)
            if not unit:
                continue
        elif nxt in "-/." and text[end + 1 : end + 2].isdigit():
            continue
        else:
            unit, us, ue = _unit_after(text, end, allow_space=True)
        try:
            value = float(m.group())
        except ValueError:  # pragma: no cover - 正则已保证可解析
            continue
        if not math.isfinite(value):
            continue
        found.append(
            NumberOccurrence(
                value=value,
                text=m.group(),
                start=start,
                end=end,
                unit=unit,
                unit_start=us,
                unit_end=ue,
            )
        )
    return tuple(found)


# ─── 白名单数据模型 ──────────────────────────────────────────────────────────


def format_number(value: float | int) -> str:
    """canonical 数字格式：整数去小数点，其余用 shortest round-trip repr。"""
    v = float(value)
    if not math.isfinite(v):
        return str(v)
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))
    return repr(v)


def _normalize_unit(unit: str) -> str:
    return str(unit).strip().lower()


def _units_compatible(entry_unit: str, token_unit: str) -> bool:
    """条目单位与文本单位兼容：任一为空则兼容，否则小写归一后相等。"""
    a, b = _normalize_unit(entry_unit), _normalize_unit(token_unit)
    if not a or not b:
        return True
    return a == b


@dataclass(frozen=True)
class NumberEntry:
    """白名单里的一个授权数字（确定性内核产出）。"""

    value: float
    unit: str = ""
    source: str = ""
    label: str = ""
    rel_tol: float = 0.0
    abs_tol: float = 0.0

    def tolerance(self) -> float:
        return max(abs(float(self.abs_tol)), abs(float(self.rel_tol)) * abs(float(self.value)))

    def numeric_match(self, value: float) -> bool:
        tol = self.tolerance()
        if tol == 0.0:
            return float(value) == float(self.value)
        return abs(float(value) - float(self.value)) <= tol

    def matches(self, value: float, unit: str = "") -> bool:
        return _units_compatible(self.unit, unit) and self.numeric_match(value)

    def canonical(self) -> str:
        return format_number(self.value) + (f" {self.unit}" if self.unit else "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": float(self.value),
            "unit": self.unit,
            "source": self.source,
            "label": self.label,
            "rel_tol": float(self.rel_tol),
            "abs_tol": float(self.abs_tol),
        }


@dataclass(frozen=True)
class NumberWhitelist:
    """授权数字集合；`match` 优先精确条目，再退到带容差条目。"""

    entries: tuple[NumberEntry, ...] = ()

    def match(self, value: float, unit: str = "") -> NumberEntry | None:
        for e in self.entries:
            if e.tolerance() == 0.0 and e.matches(value, unit):
                return e
        for e in self.entries:
            if e.matches(value, unit):
                return e
        return None

    def values(self) -> tuple[float, ...]:
        return tuple(float(e.value) for e in self.entries)

    def add(self, *entries: NumberEntry) -> NumberWhitelist:
        return NumberWhitelist(self.entries + tuple(entries))

    def merge(self, other: NumberWhitelist) -> NumberWhitelist:
        return NumberWhitelist(self.entries + tuple(other.entries))

    def to_dict(self) -> dict[str, Any]:
        return {"entries": [e.to_dict() for e in self.entries]}

    def __len__(self) -> int:
        return len(self.entries)


def _collect_numbers(
    node: Any,
    *,
    prefix: str,
    source: str,
    units: Mapping[str, str],
    rel_tol: float,
    abs_tol: float,
    out: list[NumberEntry],
) -> None:
    if isinstance(node, Mapping):
        for key, child in node.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            _collect_numbers(
                child,
                prefix=path,
                source=source,
                units=units,
                rel_tol=rel_tol,
                abs_tol=abs_tol,
                out=out,
            )
    elif isinstance(node, (list, tuple)):
        for i, item in enumerate(node):
            path = f"{prefix}.{i}" if prefix else str(i)
            _collect_numbers(
                item,
                prefix=path,
                source=source,
                units=units,
                rel_tol=rel_tol,
                abs_tol=abs_tol,
                out=out,
            )
    elif isinstance(node, bool) or node is None:
        return
    elif isinstance(node, (int, float)):
        value = float(node)
        if not math.isfinite(value):
            return
        out.append(
            NumberEntry(
                value=value,
                unit=str(units.get(prefix, "")) if units else "",
                source=f"{source}:{prefix}" if prefix else source,
                label=prefix,
                rel_tol=rel_tol,
                abs_tol=abs_tol,
            )
        )


def build_whitelist(
    data: Mapping[str, Any] | None,
    *,
    source: str = "deterministic",
    units: Mapping[str, str] | None = None,
    rel_tol: float = 0.0,
    abs_tol: float = 0.0,
) -> NumberWhitelist:
    """从确定性数据递归构建数字白名单（含 provenance）。

    - 数值叶子 → `NumberEntry`，`label` = 点分路径，`source` =
      `f"{source}:{label}"`；
    - 布尔/None/字符串/非有限浮点（nan/inf）不入白名单；
    - `units` 以 `label` 为键补充单位。
    """
    out: list[NumberEntry] = []
    if isinstance(data, Mapping):
        _collect_numbers(
            data,
            prefix="",
            source=source,
            units=units or {},
            rel_tol=rel_tol,
            abs_tol=abs_tol,
            out=out,
        )
    return NumberWhitelist(tuple(out))


def build_whitelist_from_run(
    run_dir: str | Path,
    *,
    units: Mapping[str, str] | None = None,
    rel_tol: float = 0.0,
    abs_tol: float = 0.0,
) -> NumberWhitelist:
    """从 `runs/<run_id>/meta.json` 构建白名单（确定性产物可溯）。

    provenance 为 `runs/<run_id>/meta.json:<点分路径>`。缺 `meta.json` 抛
    `FileNotFoundError`（run 未结束/路径错是调用方契约问题，不静默空转）。
    """
    path = Path(run_dir) / "meta.json"
    if not path.is_file():
        raise FileNotFoundError(f"run meta.json not found: {path}")
    meta = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(meta, Mapping):
        raise ValueError(f"meta.json must be a JSON object: {path}")
    run_id = str(meta.get("run_id") or Path(run_dir).name)
    source = f"runs/{run_id}/meta.json"
    picked = {
        key: meta[key]
        for key in ("metrics", "params", "recipe", "objectives", "objective_value")
        if key in meta
    }
    return build_whitelist(picked, source=source, units=units, rel_tol=rel_tol, abs_tol=abs_tol)


# ─── 叙述校验 / 净化 ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Violation:
    """未授权数字（拒绝依据）。`start`/`end` 定位**输入文本**下标。"""

    text: str
    value: float
    start: int
    end: int
    reason: str
    unit: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "value": self.value,
            "start": self.start,
            "end": self.end,
            "reason": self.reason,
            "unit": self.unit,
        }


@dataclass(frozen=True)
class NumberProvenance:
    """canonical 叙述中一个数字的 provenance；`start`/`end` 定位 canonical 文本。"""

    value: float
    text: str
    start: int
    end: int
    source: str
    label: str = ""
    unit: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": float(self.value),
            "text": self.text,
            "start": self.start,
            "end": self.end,
            "source": self.source,
            "label": self.label,
            "unit": self.unit,
        }


@dataclass(frozen=True)
class NarrativeCheck:
    """校验结果：`ok` = 无未授权数字；`text` = canonical 化后的叙述。"""

    ok: bool
    text: str
    violations: tuple[Violation, ...] = ()
    provenance: tuple[NumberProvenance, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "text": self.text,
            "violations": [v.to_dict() for v in self.violations],
            "provenance": [p.to_dict() for p in self.provenance],
        }


def _lookup(value: float, unit: str, whitelist: NumberWhitelist) -> tuple[NumberEntry | None, str]:
    entry = whitelist.match(value, unit)
    if entry is not None:
        return entry, ""
    for candidate in whitelist.entries:
        if candidate.numeric_match(value):
            return None, "unit_mismatch"
    return None, "unauthorized"


def check_narrative(text: str, whitelist: NumberWhitelist) -> NarrativeCheck:
    """校验并 canonical 化叙述。

    - 授权数字 → 替换为 `format_number(内核值) + 单位`；单位缺失时补白名单单位；
    - 未授权数字 → 进 `violations`（定位输入文本下标），`ok=False`，文本
      原样保留该数字（不静默删除——拒绝由调用方决定）；
    - 非 str 文本或 None 白名单抛 `TypeError`。
    """
    if not isinstance(text, str):
        raise TypeError("text must be str")
    if not isinstance(whitelist, NumberWhitelist):
        raise TypeError("whitelist must be NumberWhitelist")
    occurrences = extract_numbers(text)
    violations: list[Violation] = []
    provenance: list[NumberProvenance] = []
    pieces: list[str] = []
    cursor = 0
    out_len = 0
    for occ in occurrences:
        entry, reason = _lookup(occ.value, occ.unit, whitelist)
        if entry is None:
            violations.append(
                Violation(
                    text=occ.text,
                    value=occ.value,
                    start=occ.start,
                    end=occ.end,
                    reason=reason,
                    unit=occ.unit,
                )
            )
            continue
        if occ.unit or not entry.unit:
            repl = format_number(entry.value)
        else:
            repl = f"{format_number(entry.value)} {entry.unit}"
        head = text[cursor : occ.start]
        pieces.append(head)
        out_len += len(head)
        pieces.append(repl)
        provenance.append(
            NumberProvenance(
                value=float(entry.value),
                text=repl,
                start=out_len,
                end=out_len + len(repl),
                source=entry.source,
                label=entry.label,
                unit=entry.unit or occ.unit,
            )
        )
        out_len += len(repl)
        cursor = occ.end
    pieces.append(text[cursor:])
    return NarrativeCheck(
        ok=not violations,
        text="".join(pieces),
        violations=tuple(violations),
        provenance=tuple(provenance),
    )


def audit_narrative(text: str, whitelist: NumberWhitelist) -> dict[str, Any]:
    """JSON 友好的数字审计报告（服务层 JSON 进出约定）。"""
    check = check_narrative(text, whitelist)
    return {
        "ok": check.ok,
        "n_numbers": len(check.provenance) + len(check.violations),
        "n_authorized": len(check.provenance),
        "violations": [v.to_dict() for v in check.violations],
        "provenance": [p.to_dict() for p in check.provenance],
        "canonical_text": check.text,
    }


# ─── 模板回退（确定性骨架） ──────────────────────────────────────────────────


def _safe_text(value: Any) -> str:
    """只保留不含“独立数字 token”的文本，防止模板自造未授权数字。"""
    if value is None:
        return ""
    s = str(value).strip()
    if not s or extract_numbers(s):
        return ""
    return s


def _display_label(label: str) -> str:
    s = str(label) if label else ""
    if not s or extract_numbers(s):
        return "metric"
    return s


def _report_entries(whitelist: NumberWhitelist, data: Mapping[str, Any]) -> list[NumberEntry]:
    if "metrics" in data and isinstance(data.get("metrics"), Mapping):
        metrics = [e for e in whitelist.entries if e.label.startswith("metrics.")]
        if metrics:
            return metrics
    return list(whitelist.entries)


def render_template_narrative(
    deterministic: Mapping[str, Any] | None,
    whitelist: NumberWhitelist,
    *,
    source: str = "deterministic",
) -> str:
    """无 LLM 时的确定性叙述模板（决策依据 / 权衡 / 结论）。

    所有数字取自白名单 canonical 值；任何可能夹带未授权数字的自由文本
    （模型名/通道/source）先过 `_safe_text` 守卫。
    """
    data = deterministic if isinstance(deterministic, Mapping) else {}
    lines: list[str] = ["## 决策依据"]
    header: list[str] = []
    model = _safe_text(data.get("model"))
    adapter = _safe_text(data.get("adapter"))
    if model:
        header.append(f"模型：{model}")
    if adapter:
        header.append(f"求解通道：{adapter}")
    if header:
        lines.append("- " + "；".join(header) + "。")
    src_text = _safe_text(source)
    if src_text:
        lines.append(f"- 数据来源：{src_text}。")
    else:
        lines.append("- 数据来源：确定性内核产物；逐数字 provenance 见结构化 provenance 表。")

    lines.append("")
    lines.append("## 关键指标")
    entries = _report_entries(whitelist, data)
    if entries:
        for e in entries:
            label = _display_label(e.label)
            lines.append(f"- {label} = {e.canonical()}（来源：{label}）")
    else:
        lines.append("- 无确定性指标可引用；本叙述不引入任何数字。")

    lines.append("")
    lines.append("## 权衡")
    lines.append("- 指标取值以确定性内核产物为准，叙述层不新造、不换算任何数字。")
    lines.append("")
    lines.append("## 结论")
    lines.append("- 报告数字均可溯至确定性来源；未授权数字在生成时即被拒绝。")
    return "\n".join(lines) + "\n"


# ─── LLM 注入接口 + 生成编排 ─────────────────────────────────────────────────

LlmFn = Callable[[str], str]

# 默认可注入 LLM：None = 模板路径（本模块绝不自行联网/引入 SDK）。测试用
# monkeypatch.setattr 钉住此通道（#139）。
_DEFAULT_LLM: LlmFn | None = None

_ON_UNAUTHORIZED = ("reject", "fallback")


def build_prompt(
    deterministic: Mapping[str, Any] | None,
    whitelist: NumberWhitelist,
    *,
    source: str = "deterministic",
) -> str:
    """构造确定性提示词：把白名单与 provenance 明示给 LLM。"""
    data = deterministic if isinstance(deterministic, Mapping) else {}
    lines = [
        "你是射频设计报告叙述助手。只允许引用下列白名单中的数字（含单位），",
        "禁止计算、换算、四舍五入或引入任何新数字。",
        f"数据来源：{source}",
    ]
    model = _safe_text(data.get("model"))
    adapter = _safe_text(data.get("adapter"))
    if model:
        lines.append(f"模型：{model}")
    if adapter:
        lines.append(f"求解通道：{adapter}")
    lines.append("可用数字（label = canonical | provenance）：")
    if whitelist.entries:
        for e in whitelist.entries:
            lines.append(f"- {e.label or 'value'} = {e.canonical()} | {e.source}")
    else:
        lines.append("- （无：叙述中不得出现任何数字）")
    lines.append("请用中文撰写三段：决策依据 / 权衡 / 结论。")
    return "\n".join(lines)


@dataclass(frozen=True)
class NarrativeResult:
    """生成结果：`ok` = 最终叙述通过数字白名单校验。"""

    ok: bool
    narrative: str
    used_template: bool
    source: str
    violations: tuple[Violation, ...] = ()
    provenance: tuple[NumberProvenance, ...] = ()
    whitelist: NumberWhitelist = field(default_factory=NumberWhitelist)
    fallback_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "narrative": self.narrative,
            "used_template": self.used_template,
            "source": self.source,
            "fallback_reason": self.fallback_reason,
            "violations": [v.to_dict() for v in self.violations],
            "provenance": [p.to_dict() for p in self.provenance],
            "whitelist": self.whitelist.to_dict(),
        }


def _template_result(
    data: Mapping[str, Any],
    whitelist: NumberWhitelist,
    *,
    source: str,
) -> NarrativeResult:
    text = render_template_narrative(data, whitelist, source=source)
    check = check_narrative(text, whitelist)
    return NarrativeResult(
        ok=check.ok,
        narrative=text,
        used_template=True,
        source=source,
        violations=check.violations,
        provenance=check.provenance,
        whitelist=whitelist,
    )


def generate_narrative(
    deterministic: Mapping[str, Any] | None,
    *,
    llm_fn: LlmFn | None = None,
    source: str = "deterministic",
    units: Mapping[str, str] | None = None,
    whitelist: NumberWhitelist | None = None,
    extra_entries: Sequence[NumberEntry] = (),
    on_unauthorized: str = "reject",
) -> NarrativeResult:
    """生成设计报告叙述（LLM 可注入；默认模板），并强制数字白名单。

    - `llm_fn=None`（默认）→ 确定性模板，`used_template=True`；
    - 注入 `llm_fn` → 调用后校验：命中白名单则 canonical 化返回；出现未授权
      数字时 `on_unauthorized="reject"` 返回 `ok=False` + violations，
      `"fallback"` 则回退模板（violations 仍保留，`fallback_reason` 标注）；
    - `llm_fn` 返回非 str/空白 → 模板回退，`fallback_reason="invalid_llm_output"`。
    """
    if on_unauthorized not in _ON_UNAUTHORIZED:
        raise ValueError(f"on_unauthorized must be one of {_ON_UNAUTHORIZED}")
    data: Mapping[str, Any] = dict(deterministic) if isinstance(deterministic, Mapping) else {}
    if whitelist is None:
        wl = build_whitelist(data, source=source, units=units)
    elif isinstance(whitelist, NumberWhitelist):
        wl = whitelist
    else:
        raise TypeError("whitelist must be NumberWhitelist")
    if extra_entries:
        wl = wl.add(*extra_entries)

    fn = llm_fn if llm_fn is not None else _DEFAULT_LLM
    if fn is None:
        return _template_result(data, wl, source=source)

    prompt = build_prompt(data, wl, source=source)
    raw = fn(prompt)
    if not isinstance(raw, str) or not raw.strip():
        return replace(
            _template_result(data, wl, source=source),
            fallback_reason="invalid_llm_output",
        )

    check = check_narrative(raw, wl)
    if check.ok:
        return NarrativeResult(
            ok=True,
            narrative=check.text,
            used_template=False,
            source=source,
            provenance=check.provenance,
            whitelist=wl,
        )
    if on_unauthorized == "fallback":
        return replace(
            _template_result(data, wl, source=source),
            violations=check.violations,
            fallback_reason="unauthorized_numbers",
        )
    return NarrativeResult(
        ok=False,
        narrative=raw,
        used_template=False,
        source=source,
        violations=check.violations,
        provenance=check.provenance,
        whitelist=wl,
    )


# ─── F9 报告叙述位（接 CLI/MCP/report）────────────────────────


def report_narrative_for_run(
    run_id: str,
    *,
    narrative: str | None = None,
    runs_dir: str | Path = "runs",
    units: Mapping[str, str] | None = None,
    llm_fn: LlmFn | None = None,
    on_unauthorized: str = "reject",
) -> dict[str, Any]:
    """已完成 run → 叙述位内容（JSON 进出，CLI/MCP 薄壳与 report 叙述位共用）。

    - `narrative=None`：按 `runs/<run_id>/meta.json` 白名单生成叙述——缺省
      确定性模板（不触发任何 LLM）；显式注入 `llm_fn` 才走 LLM 并强制白名单
      校验（unauthorized 数字按 on_unauthorized reject/fallback 处置）；
    - `narrative` 给定：对外来叙述做数字审计（canonical 化 + violations 定位），
      `ok` 即「可安全填入报告叙述位」。
    meta.json 缺失/非对象 → ok=False + errors（run 未结束/路径错不静默空转）。
    """
    run_dir = Path(runs_dir) / str(run_id)
    try:
        whitelist = build_whitelist_from_run(run_dir, units=units)
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError) as exc:
        return {"ok": False, "run_id": str(run_id), "errors": [str(exc)]}
    source = f"runs/{run_id}/meta.json"
    deterministic = {
        key: meta[key]
        for key in ("model", "adapter", "metrics", "params", "objectives",
                    "objective_value")
        if key in meta
    }
    if narrative is not None:
        audit = audit_narrative(str(narrative), whitelist)
        return {"ok": bool(audit["ok"]), "run_id": str(run_id), "mode": "audit",
                "source": source, "narrative": audit["canonical_text"],
                **{k: v for k, v in audit.items() if k != "canonical_text"}}
    result = generate_narrative(
        deterministic, llm_fn=llm_fn, source=source, whitelist=whitelist,
        on_unauthorized=on_unauthorized)
    out = result.to_dict()
    out.pop("whitelist", None)  # 白名单条目可能很长，叙述位消费方不需要
    out.update({"run_id": str(run_id), "mode": "generate",
                "n_whitelist": len(whitelist.entries)})
    return out
