"""design_diff_service：设计版本差异报告（XC 差异报告面，round18 EP-2 相邻件）。

**语义 diff 报告面**：两份设计版本声明（params/substrate/setup/objectives
等嵌套 dict）→ 增/删/改完全报告 + 变更分类（数值参数/物理口径/结构面）
+ verdict（identical | compatible_params | changed | structural）。
与 layout_diff_service（LC-6 PCB 图元面）分工：那边 diff 几何图元，这边
diff **设计声明**（配方/名义参数/基板/判据配置）——版本对账、重跑判定、
 注册快照对账（df5 批"公开仓同步按 commit 范围对账"的服务化落点）。

变更分类（预声明，#122）：
- ``numeric``：双侧数值且值变化（附相对变化率）；
- ``added`` / ``removed``：单侧存在；
- ``type_change``：双侧都在但类型（数值↔非数值）翻转；
- ``value_change``：非数值标量值变化；
- ``nested``：子树进入递归（容器对容器）。
结构性变更（added/removed/type_change 任一）翻 verdict=``structural``。

零 I/O（dict 进出）；文件入口 :func:`design_version_diff_from_files`
（YAML/JSON 双支持，供 meta.yaml 对账用）。
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

_SOURCE = "rfauto.service.design_diff_service"


def _numeric(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) \
        and math.isfinite(float(x))


def _diff_tree(a: Any, b: Any, path: str,
               out: list[dict[str, Any]]) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            sub = f"{path}.{key}" if path else str(key)
            if key not in a:
                out.append({"path": sub, "kind": "added", "b": b[key]})
            elif key not in b:
                out.append({"path": sub, "kind": "removed", "a": a[key]})
            else:
                _diff_tree(a[key], b[key], sub, out)
        return
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append({"path": path, "kind": "value_change",
                        "a": a, "b": b,
                        "note": f"列表长度 {len(a)}→{len(b)}"})
            return
        for i, (xa, xb) in enumerate(zip(a, b, strict=True)):
            _diff_tree(xa, xb, f"{path}[{i}]", out)
        return
    if _numeric(a) and _numeric(b):
        fa, fb = float(a), float(b)
        if fa == fb:
            return
        rel = (fb - fa) / abs(fa) if fa != 0 else None
        out.append({"path": path, "kind": "numeric", "a": fa, "b": fb,
                    "rel_change": rel})
        return
    numeric_a, numeric_b = _numeric(a), _numeric(b)
    if numeric_a != numeric_b or type(a) is not type(b):
        # 数值↔非数值翻转，或标量类型翻转（bool≠int：_numeric 已排除 bool）
        out.append({"path": path, "kind": "type_change", "a": a, "b": b})
        return
    if a != b:
        out.append({"path": path, "kind": "value_change", "a": a, "b": b})


_STRUCTURAL_KINDS = ("added", "removed", "type_change")


def design_version_diff(a: dict[str, Any] | None = None,
                        b: dict[str, Any] | None = None, *,
                        labels: tuple[str, str] = ("a", "b"),
                        ) -> dict[str, Any]:
    """两版设计声明差异报告（JSON 进出；a/b 必须为映射）。

    Returns::

        {"ok": True, "labels": [la, lb],
         "changes": [{path, kind, a?, b?, rel_change?}...]（按 path 排序）,
         "summary": {kind: n...},
         "verdict": "identical" | "changed" | "structural"}
    """
    if not isinstance(a, dict) or not isinstance(b, dict):
        return error_envelope(["a 与 b 必须都是映射（设计版本声明 dict）"])
    changes: list[dict[str, Any]] = []
    _diff_tree(a, b, "", changes)
    changes.sort(key=lambda c: c["path"])
    summary: dict[str, int] = {}
    for c in changes:
        summary[c["kind"]] = summary.get(c["kind"], 0) + 1
    if not changes:
        verdict = "identical"
    elif any(c["kind"] in _STRUCTURAL_KINDS for c in changes):
        verdict = "structural"
    else:
        verdict = "changed"
    return ok_envelope(
        labels=[str(labels[0]), str(labels[1])],
        changes=changes,
        summary=summary,
        verdict=verdict,
        source=_SOURCE,
    )


def render_design_diff_markdown(report: dict[str, Any]) -> str:
    """差异报告 → 人读 markdown（逐变更行：kind path a→b（rel% 随行）。"""
    if report.get("ok") is not True:
        errs = "；".join(str(e) for e in report.get("errors") or [])
        return f"# 设计差异报告\n\n- 不可比：{errs}\n"
    la, lb = report["labels"]
    lines = [f"# 设计差异报告（{la} → {lb}）", "",
             f"- verdict: **{report['verdict']}**，"
             f"共 {len(report['changes'])} 处变更", ""]
    for c in report["changes"]:
        rel = c.get("rel_change")
        rel_s = f"（相对 {rel * 100:+.3g}%）" if rel is not None else ""
        lines.append(f"- `{c['path']}` {c['kind']}: "
                     f"{c.get('a')!r} → {c.get('b')!r}{rel_s}")
        if c.get("note"):
            lines.append(f"  - {c['note']}")
    return "\n".join(lines) + "\n"


def design_version_diff_from_files(a_path: str | Path,
                                   b_path: str | Path,
                                   ) -> dict[str, Any]:
    """文件入口：YAML/JSON 双支持（meta.yaml 对账主用例）。"""
    def _load(p: str | Path) -> dict[str, Any]:
        path = Path(p)
        if not path.exists():
            raise FileNotFoundError(f"设计声明文件不存在: {path}")
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() in (".yaml", ".yml"):
            import yaml

            data = yaml.safe_load(text)
        else:
            data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError(f"设计声明必须是映射，得到 {type(data)!r}: {path}")
        return data

    try:
        a = _load(a_path)
        b = _load(b_path)
    except (OSError, ValueError) as exc:
        return error_envelope([str(exc)])
    return design_version_diff(a, b,
                               labels=(str(a_path), str(b_path)))
