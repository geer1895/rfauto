"""verdict.json → 人读摘要面（aurora_g W8-S4，2026-10-19）。

runs/ 下的 verdict.json 是各战役自研 schema 的判定档案（219 份在档，
形态分家：aurora_c_oe/aurora_d 族=平铺 dict（status + g1_render/g3_*
/g5_health 等门键 + 数值标量）；k2/五点族=points/attempts 嵌套；
designs_verify 族=arms.checks 嵌套）——此前只有 JSON 面无人读汇总出口，
审计/收官对账要逐份手开。本模块给确定性提取层（零 LLM、零臆测）：

- ``verdict_summary(verdict_path) -> dict``：结构化提取（ok 信封）——
  总判定（status/verdict 键原文）、门清单（gates）、关键指标
  （key_metrics）、元信息（meta）；
- ``verdict_summary_md(verdict_path) -> str``：同一提取的结构化
  Markdown 渲染（表格式，任务书契约签名）。

规则 4：JSON 进出（md 面是渲染层，数据只来自 verdict 原文）；铁律 7：
本模块零新数值语义——所有数字均为 verdict 原文透传（浮点仅 ``.6g``
显示格式化，不改值）。只读：不写任何文件、不触发求解。

门识别口径（确定性、文档化，宁漏不猜）：
- 布尔值且键名命中门形态（``g<数字>*`` 前缀 / 含 ``gate`` / ``check``
  词根 / ``_ok|_success|_pass`` 后缀 / 恰名 ``ok|success|pass``）→
  布尔门（pass=值本身）；
- dict 值含布尔 ``ok`` 键（g5_health/nrts_converged/cleanup 惯例）→
  复合门（pass=该 ok，evidence=verdict/reason/detail 首个字符串）；
- dict 值键名自身命中门形态且无 ok 键（``checks`` 容器惯例）→ 直属
  布尔叶全收为门（叶键名不限，c1_flag_accepted 族）；
- 整数值且键名恰 ``rc`` 或 ``_rc`` 后缀（exec_rc 惯例）→ 退出码门
  （pass=rc==0）。

关键指标：深度 ≤3 的数值叶子（bool 不算数值），剔除退出码与端口/
seed 类配置噪声，按点路径排序；上限 80 条截断并如实计数。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

#: 总判定键（按序取首个字符串值；原文透传不归一）
_STATUS_KEYS = ("status", "verdict", "result")

#: 元信息键（标量直通；其余嵌套/数值进 gates/key_metrics 面）
_META_KEYS = ("schema", "template", "model", "adapter", "machine",
              "task", "started", "judged_at", "mitigation", "server_subdir")

#: 门键形态：g<数字> 前缀（g1_render/g3_finite 族）、gate/check 词根、
#: _ok/_success/_pass 后缀、恰名 ok/success/pass
_GATE_KEY_RE = re.compile(
    r"^(g\d[\w.]*|ok|success|pass)$|gate|check|_ok$|_success$|_pass$")

#: 退出码键（恰 rc 或 _rc 后缀；int 值 pass=rc==0）
_RC_KEY_RE = re.compile(r"^(rc|[\w.]*_rc)$")

#: 指标噪声键（端口/连接类配置数字，非判读指标）
_METRIC_EXCLUDE = {"grpc_port", "port", "seed", "optuna_seed"}

#: 指标/门收集深度上限（嵌套族防爆炸；arms.checks 恰在深度 3 内）
_MAX_DEPTH = 3

#: key_metrics 截断上限（摘要面不搬全文）
_MAX_METRICS = 80

#: 复合门 evidence 取键序（首个存在的字符串值）
_EVIDENCE_KEYS = ("verdict", "reason", "detail", "criteria", "context")


def _resolve_verdict_path(verdict_path: str | Path) -> Path | None:
    """verdict 定位：存在文件直用；否则按 runs 内相对 run 路径解释
    （``<run_id>`` 或 ``<战役>/<run>`` → ``runs/<...>/verdict.json``）。

    双根收敛走 infra/runs_paths（cwd 根优先，仓内子目录 chdir 收敛回
    仓库 runs/，与 batch_ops/health_check 同款）。穿越段（``..``）与
    绝对路径不落 runs 根的一律拒绝（只读面防逃逸）。找不到返回 None。
    """
    p = Path(verdict_path)
    if p.is_file():
        return p
    name = str(verdict_path).strip()
    parts = Path(name).parts
    if not name or p.is_absolute() or not parts \
            or any(seg in ("", ".", "..") for seg in parts):
        return None
    from rfauto.infra.runs_paths import resolve_runs_dir

    cand = resolve_runs_dir("runs").joinpath(*parts) / "verdict.json"
    return cand if cand.is_file() else None


def _load_verdict(path: Path) -> dict[str, Any] | None:
    """读 verdict.json；缺失/坏 JSON/非对象一律 None（调用方如实报错）。"""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _evidence_of(d: dict[str, Any]) -> str:
    """复合门说明串：_EVIDENCE_KEYS 首个非空标量，缺省空串。"""
    for k in _EVIDENCE_KEYS:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return f"{k}={v:g}"
    return ""


def _collect_gates(node: Any, path: str, depth: int,
                   out: list[dict[str, Any]]) -> None:
    """递归收集门（深度 ≤3，确定序=先键序递归）。

    - 布尔门：键命中门形态；
    - 复合门：dict 含布尔 ok 键（键名不限——g5_health/nrts_converged/
      cleanup 等 ok 惯例载体全收，ok 是唯一判定字段）；
    - 退出码门：int 且键为 rc 形态；
    - dict 无 ok 键 → 继续下钻（checks/arms 容器）。
    """
    if depth > _MAX_DEPTH or not isinstance(node, dict):
        return
    for key in sorted(node, key=str):
        val = node[key]
        p = f"{path}.{key}" if path else str(key)
        if isinstance(val, bool):
            if _GATE_KEY_RE.search(str(key)):
                out.append({"name": str(key), "path": p, "kind": "bool",
                            "ok": val, "evidence": ""})
        elif isinstance(val, dict):
            ok = val.get("ok")
            if isinstance(ok, bool):
                out.append({"name": str(key), "path": p, "kind": "dict_ok",
                            "ok": ok, "evidence": _evidence_of(val)})
            elif _GATE_KEY_RE.search(str(key)):
                # 门容器（checks 惯例）：键名命中门形态且无 ok 判定键 →
                # 直属布尔叶全收（叶键名不限——c1_flag_accepted 族）
                for leaf in sorted(val, key=str):
                    lv = val[leaf]
                    if isinstance(lv, bool):
                        lp = f"{p}.{leaf}"
                        out.append({"name": str(leaf), "path": lp,
                                    "kind": "bool", "ok": lv, "evidence": ""})
            else:
                _collect_gates(val, p, depth + 1, out)
        elif isinstance(val, int) and not isinstance(val, bool) \
                and _RC_KEY_RE.fullmatch(str(key)):
            out.append({"name": str(key), "path": p, "kind": "rc",
                        "ok": val == 0, "evidence": f"rc={val}"})


def _collect_metrics(node: Any, path: str, depth: int,
                     out: list[dict[str, Any]]) -> None:
    """递归收集数值叶子（深度 ≤3；bool/退出码/噪声键/门键不算指标）。"""
    if depth > _MAX_DEPTH or not isinstance(node, dict):
        return
    for key in sorted(node, key=str):
        val = node[key]
        p = f"{path}.{key}" if path else str(key)
        if isinstance(val, dict):
            _collect_metrics(val, p, depth + 1, out)
            continue
        if isinstance(val, bool):
            continue
        if isinstance(val, (int, float)):
            ks = str(key)
            if ks in _METRIC_EXCLUDE or _RC_KEY_RE.fullmatch(ks) \
                    or _GATE_KEY_RE.fullmatch(ks):
                continue
            out.append({"path": p, "value": val})
        # 字符串/None/list：非指标，不下钻（list 语义=整体，与 runs_diff 同口径）


def verdict_summary(verdict_path: str | Path) -> dict[str, Any]:
    """verdict.json 结构化提取（CLI/UI/Agent 共用数据层，规则 4）。

    Returns:
        ok 信封：``status``（总判定原文，无判定键时空串）、
        ``meta``（元信息标量直通）、``gates``（门清单，确定序）、
        ``n_gates_pass`` / ``n_gates_fail``、``key_metrics``、
        ``n_metrics``、``truncated``、``source``、``run_id``（按
        run_id 形态解析时有值）。找不到/不可读 → ok=False 如实报错。
    """
    raw = str(verdict_path).strip()
    if not raw:
        return error_envelope(["verdict_path 为空"])
    path = _resolve_verdict_path(raw)
    if path is None:
        return error_envelope(
            [f"verdict 不存在: {raw}（既非现存文件，也无 runs/<id>/verdict.json）"])
    data = _load_verdict(path)
    if data is None:
        return error_envelope([f"verdict 不可读（坏 JSON 或非对象）: {path}"])

    status, status_key = "", ""
    for k in _STATUS_KEYS:
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            status, status_key = v.strip(), k
            break

    meta = {k: data[k] for k in _META_KEYS
            if isinstance(data.get(k), (str, int, float))
            and not isinstance(data.get(k), bool)}

    gates: list[dict[str, Any]] = []
    _collect_gates(data, "", 0, gates)
    metrics: list[dict[str, Any]] = []
    _collect_metrics(data, "", 0, metrics)
    truncated = len(metrics) > _MAX_METRICS

    return ok_envelope(
        source=str(path),
        run_id=path.parent.name if path.name == "verdict.json" else None,
        status=status,
        status_key=status_key,
        meta=meta,
        gates=gates,
        n_gates=len(gates),
        n_gates_pass=sum(1 for g in gates if g["ok"] is True),
        n_gates_fail=sum(1 for g in gates if g["ok"] is False),
        key_metrics=metrics[:_MAX_METRICS],
        n_metrics=len(metrics),
        truncated=truncated,
    )


def _fmt_val(v: Any) -> str:
    """指标显示格式：浮点 ``.6g``（显示层，不改值），其余 str 直转；
    管道符转义（Markdown 表格安全）。"""
    s = f"{v:.6g}" if isinstance(v, float) else str(v)
    return s.replace("|", "\\|").replace("\n", " ")


def verdict_summary_md(verdict_path: str | Path) -> str:
    """verdict.json → 结构化 Markdown 摘要（任务书契约签名 → str）。

    提取层=verdict_summary 单源；本函数只做确定性渲染（表格化，零 LLM、
    零时间戳——同输入逐字节同输出）。不可读/不存在时返回以
    ``verdict 摘要不可用`` 起头的单行说明（渲染层不抛，供人读面直嵌；
    需要错误语义的调用方走 verdict_summary）。
    """
    r = verdict_summary(verdict_path)
    if not r.get("ok"):
        return ("verdict 摘要不可用\n\n"
                + "\n".join(f"- {e}" for e in r.get("errors") or []) + "\n")
    lines: list[str] = []
    status = str(r.get("status") or "（无总判定键）")
    status_disp = status.replace("|", "\\|")
    lines.append(f"# verdict 摘要 — {status_disp}")
    lines.append("")
    lines.append(f"- 判定来源: `{r.get('source')}`"
                 + (f"（run_id: `{r.get('run_id')}`）"
                    if r.get("run_id") else ""))
    if r.get("status_key"):
        lines.append(f"- 总判定键: `{r['status_key']}`")
    meta = r.get("meta") or {}
    if meta:
        kv = "；".join(f"{k}=`{_fmt_val(v)}`" for k, v in meta.items())
        lines.append(f"- 元信息: {kv}")
    gates = r.get("gates") or []
    np_, nf = r.get("n_gates_pass"), r.get("n_gates_fail")
    lines.append(f"- 门通过: {np_}/{r.get('n_gates', 0)}"
                 + (f"（fail {nf}）" if nf else ""))
    lines.append("")
    if gates:
        lines.append("## 门检查")
        lines.append("")
        lines.append("| 门 | 结果 | 说明 |")
        lines.append("|---|---|---|")
        for g in gates:
            ok = g.get("ok")
            mark = "PASS" if ok is True else ("FAIL" if ok is False else "-")
            ev = _fmt_val(g.get("evidence") or "")
            lines.append(f"| `{g['path']}` | {mark} | {ev} |")
        lines.append("")
    metrics = r.get("key_metrics") or []
    if metrics:
        lines.append("## 关键指标")
        lines.append("")
        lines.append("| 指标 | 值 |")
        lines.append("|---|---|")
        for m in metrics:
            lines.append(f"| `{m['path']}` | {_fmt_val(m['value'])} |")
        lines.append("")
        if r.get("truncated"):
            lines.append(f"> 指标共 {r.get('n_metrics')} 项，摘要截断前 "
                         f"{_MAX_METRICS} 项（截断计数如实，正文不掺数）。")
        lines.append("")
    if not gates and not metrics:
        lines.append("（无门键与数值指标可提取——该 verdict 为纯档案形态，"
                     "原文见判定来源。）")
        lines.append("")
    return "\n".join(lines)
