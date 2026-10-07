"""双 run 只读对比（PR-4 报告页深化 ③，规格 §D-8 2026-10-02 批；SN-15 迁 service）。

service 唯一事实源（SN-15，W6-A 2026-10-06 自 ui/runs_diff.py 迁入，
函数体逐字节未动）：``GET /api/runs/diff``（ui/server.py 薄壳经
ui/runs_diff.py re-export 消费）与 ``rfauto runs diff`` CLI 叶同源。
分层契约 .importlinter：ui→service 合法，cli 侧直取本模块（业务不落
ui 层）。只读：不写任何文件、不触发求解。

返回（ok 信封）：
- a / b：两侧摘要（run_id、model、adapter、status、metrics）
- same_model / same_adapter：口径一致性（UI 据此渲染"口径不同"警示）
- params_recursive_diff：两侧 recipe.snapshot.yaml 的叶子级递归 diff
  （path/kind=added|removed|changed/a/b；标量与 list 整体比较）
- metrics_delta：指标并集逐键 {a, b, delta}（delta 仅数值键，b−a）
- sparams_a / sparams_b：|S| dB 曲线（复用 ui_service.sparams_series，
  mode="db"，与 S 参数分析页同口径；无 Touchstone 时空曲线+警告）
- verdict_hints：确定性判读提示串（模型/通道一致性、带内 S11 方向——
  「S11 越低越好」为仓内既有 UI 口径；其余指标只报差值不臆测方向）
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope
from rfauto.service.ui_service import RUNS_DIR, sparams_series


def _plain(v: Any) -> Any:
    """YAML/JSON 值 → JSON 可序列化（datetime/date 转 isoformat，其余原样；
    兜底 str——diff 面是展示面，不因不可序列化标量炸整个端点）。"""
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    try:
        json.dumps(v)
        return v
    except (TypeError, ValueError):
        return str(v)


def _read_meta(run_dir: Path) -> dict[str, Any]:
    """meta.json 摘要（run 判读铁律：adapter/study 字段在 meta，#144）。"""
    p = run_dir / "meta.json"
    if not p.is_file():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return d if isinstance(d, dict) else {}


def _read_snapshot(run_dir: Path) -> dict[str, Any]:
    """recipe.snapshot.yaml 全文档（params 递归 diff 的数据源）。"""
    import yaml

    p = run_dir / "recipe.snapshot.yaml"
    if not p.is_file():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            d = yaml.safe_load(f) or {}
    except Exception:
        return {}
    return d if isinstance(d, dict) else {}


def recursive_diff(a: Any, b: Any, prefix: str = "") -> list[dict[str, Any]]:
    """叶子级递归 diff：dict 逐键递归；list/标量整体比较（不等即 changed）。

    返回条目 {path, kind: added|removed|changed, a, b}（path 点分；list
    不下钻——配方节点的 list 语义是整体，逐元素 diff 会把重排当变更）。
    """
    out: list[dict[str, Any]] = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            p = f"{prefix}.{k}" if prefix else str(k)
            if k not in a:
                out.append({"path": p, "kind": "added", "a": None, "b": _plain(b[k])})
            elif k not in b:
                out.append({"path": p, "kind": "removed", "a": _plain(a[k]), "b": None})
            else:
                out.extend(recursive_diff(a[k], b[k], p))
        return out
    if _plain(a) != _plain(b):
        out.append({"path": prefix, "kind": "changed", "a": _plain(a), "b": _plain(b)})
    return out


def _metrics_of(run_dir: Path, meta: dict[str, Any]) -> dict[str, Any]:
    """指标：meta.json 内嵌优先，缺省回退 results/metrics.json（run_detail 同源）。"""
    m = meta.get("metrics")
    if isinstance(m, dict) and m:
        return m
    p = run_dir / "results" / "metrics.json"
    if p.is_file():
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return d
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def _sparams_of(run_id: str) -> dict[str, Any]:
    """|S| dB 曲线（sparams_series 复用，与 S 参数分析页同口径）。"""
    r = sparams_series(run_id, "db")
    if not r.get("ok"):
        return {"curves": [], "warning": "; ".join(r.get("errors", []))}
    return {"curves": r.get("curves") or [], "warning": r.get("warning")}


def _metrics_delta(ma: dict[str, Any], mb: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """指标并集逐键 Δ（b−a；非数值键 delta=None，不臆测）。"""
    out: dict[str, dict[str, Any]] = {}
    for k in sorted(set(ma) | set(mb), key=str):
        va, vb = ma.get(k), mb.get(k)
        delta = None
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)) \
                and not isinstance(va, bool) and not isinstance(vb, bool):
            delta = vb - va
        out[k] = {"a": _plain(va), "b": _plain(vb), "delta": delta}
    return out


def _hints(
    a_meta: dict[str, Any], b_meta: dict[str, Any],
    same_model: bool, same_adapter: bool, params_diff: list[dict[str, Any]],
    metrics_delta: dict[str, dict[str, Any]],
) -> list[str]:
    """确定性判读提示（只说可证的话：一致性与既有 UI 口径的 S11 方向）。"""
    hints: list[str] = []
    ma, mb = a_meta.get("model"), b_meta.get("model")
    aa, ab = a_meta.get("adapter"), b_meta.get("adapter")
    if ma and mb and not same_model:
        hints.append(f"模型不同（口径不同）：a={ma} vs b={mb}——指标不可直接比较")
    if aa and ab and not same_adapter:
        hints.append(f"通道不同：a={aa} vs b={ab}——保真度不同，结论以高保真侧为准")
    if same_model and same_adapter:
        hints.append("同模型同通道，指标可比")
    s11 = metrics_delta.get("s11_db_max_in_band")
    if s11 and isinstance(s11.get("delta"), (int, float)):
        # 「S11 越低越好」= 总览页既有 UI 口径；更负=更好
        d = s11["delta"]
        better = "b" if d < 0 else ("a" if d > 0 else None)
        if better:
            hints.append(
                f"带内 S11：a={s11['a']:.2f} dB → b={s11['b']:.2f} dB"
                f"（{better} 好 {-d if d < 0 else d:.2f} dB）")
        else:
            hints.append("带内 S11 持平")
    n_changed = sum(1 for e in params_diff if e["path"].startswith("params"))
    if params_diff:
        hints.append(f"配方快照差异 {len(params_diff)} 处（其中 params 节 {n_changed} 处）")
    else:
        hints.append("配方快照无差异（同配置复跑）")
    return hints


def runs_diff(run_id_a: str, run_id_b: str) -> dict[str, Any]:
    """双 run 只读对比主入口（ui/server.py GET /api/runs/diff 薄壳消费）。"""
    a, b = str(run_id_a).strip(), str(run_id_b).strip()
    errs: list[str] = []
    if not a or "/" in a or "\\" in a or a in (".", ".."):
        errs.append(f"非法 run_id a: {a!r}")
    if not b or "/" in b or "\\" in b or b in (".", ".."):
        errs.append(f"非法 run_id b: {b!r}")
    if errs:
        return error_envelope(errs)
    dir_a, dir_b = RUNS_DIR / a, RUNS_DIR / b
    if not dir_a.is_dir():
        return error_envelope([f"run 不存在: {a}"])
    if not dir_b.is_dir():
        return error_envelope([f"run 不存在: {b}"])

    meta_a, meta_b = _read_meta(dir_a), _read_meta(dir_b)
    snap_a, snap_b = _read_snapshot(dir_a), _read_snapshot(dir_b)
    params_diff = recursive_diff(snap_a, snap_b)
    delta = _metrics_delta(_metrics_of(dir_a, meta_a), _metrics_of(dir_b, meta_b))
    same_model = bool(meta_a.get("model")) and \
        meta_a.get("model") == meta_b.get("model")
    same_adapter = bool(meta_a.get("adapter")) and \
        meta_a.get("adapter") == meta_b.get("adapter")

    def _side(run_id: str, run_dir: Path, meta: dict[str, Any]) -> dict[str, Any]:
        return {
            "run_id": run_id,
            "model": meta.get("model"),
            "adapter": meta.get("adapter"),
            "status": meta.get("status"),
            "timestamp": meta.get("timestamp"),
            "has_snapshot": (run_dir / "recipe.snapshot.yaml").is_file(),
            "metrics": _plain(_metrics_of(run_dir, meta)),
        }

    return ok_envelope(
        a=_side(a, dir_a, meta_a),
        b=_side(b, dir_b, meta_b),
        same_model=same_model,
        same_adapter=same_adapter,
        params_recursive_diff=params_diff,
        metrics_delta=_plain(delta),
        sparams_a=_sparams_of(a),
        sparams_b=_sparams_of(b),
        verdict_hints=_hints(meta_a, meta_b, same_model, same_adapter,
                             params_diff, delta),
    )
