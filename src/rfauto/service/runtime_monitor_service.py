"""运行时验证 monitor（R8）——长跑 run 目录体检周期面（增量消费 port_ut/et 事件流）。

R8 规格（池十五 R8 / 月计划 carry-over §二.2）：把 |S11|>1 / NrTS 触顶 /
能量停滞写成**时序性质**，monitor 增量消费 port_ut/et 事件流——长跑实时
红绿而非事后判读（#268/#262 家族的运行时版）。事后判读仍归
core/solve_health.solve_health_check（完成态全量体检，职责不重叠）。

坑账依据（本模块的判据语义直接来自这三条，缺一即盲判）：
- #268：et/ht 文件 mtime 停止≠卡死（stdio 缓冲伪象）——真实进度只认
  port_ut_* 末行时间轴。本模块永不以 mtime 判停滞。
- #262：窄 FC 窗 + NrTS 截断脉冲 → |S11|>1 假象——激励尾值仍在峰值
  量级 = 截断**嫌疑**（FC 窗/NrTS 覆盖核查提示），sparams 未出前不判
  非物理，也不判收敛。
- #323/#344：能量尾部衰减率必须实测（设计 Q 外推失真可达 12×）——
  本模块从 port_ut 电压尾段（激励结束后窗口）直接估衰减率（dB/ns），
  供人工对照收敛预算；近零衰减=停滞嫌疑（高 Q 或激励未歇）。

服务层 JSON 进出（规则 4）：返回值走 envelope 三态（ok/skipped/error）；
单文件损坏只降级该检查项，不传染其余检查（#105 best-effort）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "monitor_cycle",
    "monitor_run_dir",
]

#: et 全量解析行数上限（防超大 run 内存/耗时失控；触顶如实降级其余判据）
_MAX_PARSE_LINES = 2_000_000


def _parse_series_text(text: str) -> tuple[np.ndarray, np.ndarray]:
    """解析 openEMS 两列时序文本（% 注释头；空白分隔 t/s 与值）。

    坏行静默跳过（观测面不阻塞主路径，#105）；全部坏行返回空数组。
    """
    ts: list[float] = []
    vs: list[float] = []
    for n, raw in enumerate(text.splitlines()):
        if n >= _MAX_PARSE_LINES:
            break
        line = raw.strip()
        if not line or line.startswith(("%", "#")):
            continue
        parts = line.replace(",", " ").split()
        if len(parts) < 2:
            continue
        try:
            ts.append(float(parts[0]))
            vs.append(float(parts[1]))
        except ValueError:
            continue
    return np.asarray(ts, dtype=float), np.asarray(vs, dtype=float)


def _read_series(path: Path, *, tail_bytes: int | None) -> np.ndarray | None:
    """读文本时序（tail_bytes 给定时只读文件尾部），返回 (t, v) 或 None。

    只读尾部时丢弃首个可能残缺的整行；解码失败/空数据返回 None（跳过语义）。
    """
    try:
        if tail_bytes is not None and path.stat().st_size > tail_bytes:
            with path.open("rb") as fh:
                fh.seek(-tail_bytes, 2)
                blob = fh.read()
            text = blob.decode("utf-8", errors="replace")
            first_nl = text.find("\n")
            if first_nl >= 0:
                text = text[first_nl + 1:]
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    t, v = _parse_series_text(text)
    if t.size == 0:
        return None
    return np.stack([t, v])


def _resolve_art_dir(run_dir: Path) -> Path:
    """openEMS 产物目录：fdtd/ 子目录优先（真机惯例），回退 run_dir 本身。"""
    fdtd = run_dir / "fdtd"
    return fdtd if fdtd.is_dir() else run_dir


def _energy_decay_check(
    t: np.ndarray,
    v: np.ndarray,
    t_excite_end: float | None,
    floor_db_per_ns: float,
) -> dict[str, Any] | None:
    """激励结束后窗口的电压 RMS 衰减率估计（dB/ns，幅度口径 20·log10）。

    合成回收锚：v(t)=A·e^(−αt) 时理论衰减率 = 20·log10(e)·α（闭式）；
    检查实现把窗口对半、逐半取 RMS（同形状波形的 RMS 比值=幅度比值），
    两中心时刻差为分母。窗口 <8 点或 rms2=0 时放弃估计（None，不硬判）。
    """
    if t_excite_end is not None:
        mask = t > t_excite_end
        t_w, v_w = t[mask], v[mask]
    else:
        t_w, v_w = t, v
    if t_w.size < 8:
        return None
    mid = t_w.size // 2
    rms1 = float(np.sqrt(np.mean(v_w[:mid] ** 2)))
    rms2 = float(np.sqrt(np.mean(v_w[mid:] ** 2)))
    if rms1 <= 0.0 or rms2 <= 0.0:
        return None
    dt_center = float(t_w[mid:].mean() - t_w[:mid].mean())
    if dt_center <= 0.0:
        return None
    decay_db_per_s = 20.0 * float(np.log10(rms1 / rms2)) / dt_center
    decay_db_per_ns = decay_db_per_s * 1e-9
    checks: dict[str, Any] = {
        "decay_db_per_ns": decay_db_per_ns,
        "window_points": int(t_w.size),
        "window_end_s": float(t_w[-1]),
    }
    if decay_db_per_ns < 0.0:
        checks["level"] = "yellow"
        checks["reason"] = (
            f"激励结束后能量增长（衰减率 {decay_db_per_ns:.4g} dB/ns < 0，"
            "发散/未歇嫌疑）")
    elif decay_db_per_ns < floor_db_per_ns:
        checks["level"] = "yellow"
        checks["reason"] = (
            f"能量停滞嫌疑（衰减率 {decay_db_per_ns:.4g} dB/ns < 下限 "
            f"{floor_db_per_ns:.4g}；高 Q 长尾或激励未歇，#323 实测口径）")
    else:
        checks["level"] = "green"
    return checks


def monitor_run_dir(
    run_dir: str | Path,
    *,
    nr_ts: int | None = None,
    tail_bytes: int = 262_144,
    full_bytes: int = 67_108_864,
    truncation_ratio: float = 0.1,
    decay_floor_db_per_ns: float = 0.001,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """单 run 目录周期体检：进度/截断嫌疑/NrTS 触顶/能量停滞四类时序判据。

    Args:
        run_dir: run 目录（产物在 ``run_dir`` 或 ``run_dir/fdtd``）。
        nr_ts: 引擎 NrTS 上限（来自 meta/config；给了才做触顶判据）。
        tail_bytes: port_ut 尾读字节数（大文件只读尾部，增量消费语义）。
        full_bytes: et 全读字节上限（超限跳过截断/行数判据并如实注记）。
        truncation_ratio: et 末值/峰值超过该比例记截断嫌疑（#262 口径）。
        decay_floor_db_per_ns: 能量衰减率下限（低于记停滞嫌疑）。
        previous: 上轮 ``monitor_run_dir`` 返回的时间轴快照（可选，算增量）。

    Returns:
        envelope：``{ok, run_id, verdict: green|yellow|red|unknown,
        checks: {...}, reasons: [...]}``；目录无时域产物时 verdict=unknown。
    """
    root = Path(run_dir)
    if not root.is_dir():
        return error_envelope([f"run 目录不存在: {root}"], run_id=root.name)
    art = _resolve_art_dir(root)

    et_path = art / "et"
    et_arr: np.ndarray | None = None
    et_skipped = False
    if et_path.exists():
        try:
            if et_path.stat().st_size <= full_bytes:
                et_arr = _read_series(et_path, tail_bytes=None)
            else:
                et_skipped = True
        except OSError:
            et_skipped = True

    port_files = sorted(art.glob("port_ut_*"))
    ports: dict[str, Any] = {}
    t_excite_end = float(et_arr[0][-1]) if et_arr is not None else None
    decay_check: dict[str, Any] | None = None
    for pf in port_files:
        arr = _read_series(pf, tail_bytes=tail_bytes)
        if arr is None:
            ports[pf.name] = {"status": "unreadable"}
            continue
        t, v = arr[0], arr[1]
        entry: dict[str, Any] = {
            "status": "ok",
            "t_last_s": float(t[-1]),
            "n_rows_tail": int(t.size),
        }
        prev = (previous or {}).get("checks", {}).get("ports") \
            or (previous or {}).get("ports", {})
        prev_entry = prev.get(pf.name)
        if prev_entry is not None and "t_last_s" in prev_entry:
            entry["progress_delta_s"] = float(t[-1]) - \
                float(prev_entry["t_last_s"])
        ports[pf.name] = entry
        # 衰减率取末行时间轴最长的可读端口（最长观测窗）。
        # 硬前提：必须有 et 激励参照（t_excite_end）——无参照时响应段与
        # 激励段不可分，衰减估计会把激励上升段误判为"能量增长"。
        if (t_excite_end is not None
                and (decay_check is None
                     or t[-1] > decay_check.get("_t_end", -1.0))):
            candidate = _energy_decay_check(
                t, v, t_excite_end, decay_floor_db_per_ns)
            if candidate is not None:
                candidate["_t_end"] = float(t[-1])
                decay_check = candidate

    checks: dict[str, Any] = {"ports": ports}
    reasons: list[str] = []
    level = "green"

    # 判据 1（#268）：真实进度=port_ut 末行时间轴；增量全零=停滞嫌疑
    t_ends = [e["t_last_s"] for e in ports.values() if e.get("status") == "ok"]
    if t_ends:
        checks["progress_t_end_s"] = max(t_ends)
        deltas = [e.get("progress_delta_s") for e in ports.values()
                  if e.get("progress_delta_s") is not None]
        if deltas and all(d <= 0.0 for d in deltas):
            checks["level_progress"] = "yellow"
            reasons.append("port_ut 时间轴增量全非正（停滞嫌疑，#268 口径）")
            level = "yellow"
    elif port_files:
        checks["level_progress"] = "yellow"
        reasons.append("port_ut 文件存在但全部不可读（缓冲未刷或损坏）")
        level = "yellow"

    # 判据 2（#262）：激励尾值/峰值 > 比例阈值 = 截断嫌疑（不判非物理）
    if et_arr is not None:
        t_et, v_et = et_arr[0], et_arr[1]
        checks["et_rows"] = int(t_et.size)
        checks["et_t_end_s"] = float(t_et[-1])
        v_peak = float(np.max(np.abs(v_et)))
        if v_peak > 0.0:
            tail_ratio = float(abs(v_et[-1])) / v_peak
            checks["et_tail_peak_ratio"] = tail_ratio
            if tail_ratio > truncation_ratio:
                checks["level_truncation"] = "yellow"
                reasons.append(
                    f"激励尾值/峰值={tail_ratio:.3g} > {truncation_ratio}（"
                    "#262 截断嫌疑：FC 窗/NrTS 覆盖核查；不判非物理）")
                level = "yellow"
        if nr_ts is not None and t_et.size >= int(nr_ts):
            checks["level_nrts"] = "red"
            reasons.append(
                f"et 行数 {t_et.size} >= NrTS {nr_ts}（触顶，步数预算耗尽）")
            level = "red"
    elif et_skipped:
        checks["level_truncation"] = "unknown"
        reasons.append("et 文件超全读上限，截断/NrTS 判据本轮跳过")

    # 判据 3（#323/#344）：实测能量衰减率（需 et 参照；无参照如实跳过）
    if decay_check is not None:
        decay = {k: v for k, v in decay_check.items() if k != "_t_end"}
        checks["energy_decay"] = decay
        if decay.get("level") == "yellow":
            reasons.append(str(decay.get("reason", "")))
            level = "yellow"
    elif t_excite_end is None and t_ends and et_arr is None and not et_skipped:
        checks["energy_decay"] = {
            "status": "skipped",
            "reason": "无 et 激励参照，衰减判据跳过（响应/激励段不可分）",
        }

    if not port_files and et_arr is None and not et_skipped:
        return ok_envelope(
            run_id=root.name, verdict="unknown",
            reasons=["无 port_ut/et 时域产物（run 未开始或非时域 run）"],
            checks=checks)
    return ok_envelope(run_id=root.name, verdict=level, reasons=reasons,
                       checks=checks)


def monitor_cycle(
    runs_dir: str | Path,
    *,
    previous: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """周期面：对 runs_dir 下的 run 目录逐个体检并聚合红绿名单。

    run 目录判定：子目录含 meta.json / fdtd/ / port_ut_* 任一即入选；
    其余目录忽略。previous 为上轮 ``monitor_cycle`` 返回的
    ``snapshots``（run_id → monitor 结果），透传给单 run 体检算增量。

    Returns:
        envelope：``{ok, n_monitored, verdicts, red, yellow, unknown,
        snapshots}``；单 run 体检失败只计入该 run（#105 不传染）。
    """
    root = Path(runs_dir)
    if not root.is_dir():
        return error_envelope([f"runs 目录不存在: {root}"])
    verdicts: dict[str, str] = {}
    red: list[str] = []
    yellow: list[str] = []
    unknown: list[str] = []
    failed: dict[str, str] = {}
    snapshots: dict[str, Any] = {}
    for child in sorted(p for p in root.iterdir() if p.is_dir()):
        has_art = (child / "meta.json").exists() or (child / "fdtd").is_dir() \
            or any(child.glob("port_ut_*")) or (child / "et").exists()
        if not has_art:
            continue
        prev = (previous or {}).get("snapshots", {}).get(child.name)
        try:
            out = monitor_run_dir(child, previous=prev, **kwargs)
        except Exception as exc:
            failed[child.name] = f"{type(exc).__name__}: {exc}"
            continue
        verdict = str(out.get("verdict", "unknown"))
        verdicts[child.name] = verdict
        if verdict == "red":
            red.append(child.name)
        elif verdict == "yellow":
            yellow.append(child.name)
        else:
            unknown.append(child.name)
        snapshots[child.name] = out
    return ok_envelope(
        n_monitored=len(verdicts), verdicts=verdicts, red=red, yellow=yellow,
        unknown=unknown, failed=failed, snapshots=snapshots)
