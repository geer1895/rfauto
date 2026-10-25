"""em diff 服务面：run 目录级四面对比（aurora_k K18 席，2026-10-23；反馈 P17/F13）。

用户实战病灶（P17 原文）：为了定位 13:05 旧端口/端口面 Radiation/植球短路，
用户**手工 diff .aedt 文本**（RectangleParameters、Faces、IntLine）和对象
bbox——这些信息本可自动对比。本模块给两个 run 目录出一份结构化 diff：

- ``params``  ：meta.json ``params`` 字段逐键 diff（新增/删除/变更，数值
  带旧→新；网格档参数键名含 "mesh" 者自然在内——K16 档位证据同源）；
- ``manifest``：K5 模型清单（em_doctor 清单形态，用户手工导出时存 run
  目录）按 name 对齐逐项 diff——对象/端口/叠层/keepout 的增删改+关键数值
  字段变化（**aperture z 0–190 → 0–295.2 正是此面抓的验收靶**）；
- ``sparams`` ：两 run 的 Touchstone（results/params.sNp，skrf 读入）同栅
  对齐 → 逐频 dB 差最大频点 + ``--at-ghz`` 定点读数（S11/S21 差表）；
- ``freshness``：K4 ``runs_verify_service.verify_run`` 两侧状态行交叉
  （恒出，不随 --sections 裁剪——交付错配防线近乎零成本）。

复用清单（防重复建设）：清单装载/校验=``em_doctor_service.
load_model_manifest``（K5 单源，只读 import）；新鲜度=``runs_verify_service.
verify_run``（K4 单源，只读 import）；Touchstone 发现/读入形态=K16
``em_metrics_service`` 同款 glob（results/params.s*p）；与 ``runs compare``
（service/api/analysis.compare_runs）的分工=那边是 run_id 级 metrics/cost
对账（runs 湖注册面），本面是**目录级**几何/端口/曲线对比，S 参数对拍
仓内无现成核（compare_runs 不碰 Touchstone），频栅对齐按 #287/#294 家法
自实现（同栅 rtol=1e-9 直通；异栅 argmin|Δf| 真最近邻+ulp 级容差带）。

v2 登记不硬凑（#122）：.aedt 文本活体解析（Faces/IntLine/RectangleParameters、
端口面辐射边界清单=用户"6 面辐射→5 面"的活体面）、对象体积（unite 后真体
对账）、全 S 矩阵逐对 diff（v1 只 S11/S21 主口径）。

刻意不带 ``__all__``（em_doctor_service 同例：check_public_api 金快照不翻面）。
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

# ─── 节名全集与缺省（CLI --sections 消费面） ────────────────────────────────

#: 全部可选节（顺序=输出顺序；freshness 恒出，列此处供显式请求校验）。
DIFF_SECTIONS = ("params", "manifest", "sparams", "freshness")
#: 缺省节（freshness 恒出故不占缺省位）。
DEFAULT_SECTIONS = ("params", "manifest", "sparams")

#: 模型清单候选文件名（run 目录根直下；K5 导出示例形态 model_manifest.json）。
_MANIFEST_CANDIDATES = (
    "model_manifest.json", "model_manifest.yaml", "model_manifest.yml")

#: manifest 各分组逐项 diff 的字段白名单（group → 可变字段；name 为对齐键）。
_MANIFEST_GROUPS: dict[str, tuple[str, ...]] = {
    "objects": ("kind", "net", "material", "bbox", "thickness_z"),
    "ports": ("plane", "aperture_bbox", "integration_line", "num_modes",
              "on_boundary", "gap"),
    "stackup": ("thickness", "material", "z_range", "bbox"),
    "keepouts": ("rect", "z_range", "clearance", "applies_to"),
}

#: 分组中文标签（人读面）。
_GROUP_LABELS = {"objects": "对象", "ports": "端口", "stackup": "叠层",
                 "keepouts": "keepout"}

# 频栅对齐容差（#287/#294 家法）：同栅判定 np.allclose(rtol=…)；异栅最近邻
# 接受带 |Δf| ≤ max(|f|·_FREQ_RTOL, _FREQ_ATOL)——#294 实测 ADS 栅漂移
# ~2.4e-7 Hz @2GHz 属 ulp 级，_FREQ_RTOL=1e-9 在 GHz 段给 ~Hz 级接受带，
# 半格错位（MHz 级）必拒。
_FREQ_RTOL = 1e-9
_FREQ_ATOL = 1e-6

#: dB 化的幅度地板（|S|=0 不进 log；-300 dB 足够深）。
_DB_FLOOR = 1e-15


# ─── 通用值比较（同 run 自 diff 必须恒零，NaN 恒等、bool 不吃 int） ──────────


def _values_equal(a: Any, b: Any) -> bool:
    """导出值语义等价（bool 与数值分型；数值 NaN==NaN；容器逐元素）。"""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        fa, fb = float(a), float(b)
        if math.isnan(fa) and math.isnan(fb):
            return True
        return fa == fb
    if isinstance(a, Mapping) and isinstance(b, Mapping):
        return set(a) == set(b) and all(
            _values_equal(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(
            _values_equal(x, y) for x, y in zip(a, b, strict=True))
    if type(a) is not type(b):
        # None vs 值 / str vs 数等跨型=变更（同一清单字段类型应稳定）
        return False
    return a == b


def _is_number(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)))


# ─── params 节 ──────────────────────────────────────────────────────────────


def _load_meta(run_dir: Path) -> dict[str, Any] | None:
    """读 run 目录 meta.json（不存在/不可解析 → None）。"""
    path = run_dir / "meta.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _load_meta_params(run_dir: Path) -> tuple[dict[str, Any] | None, str | None]:
    """meta.json params 映射读取（K16 `_mesh_params_from_meta` 的全量版）。

    Returns:
        (params 映射或 None, 跳过原因或 None)。
    """
    meta = _load_meta(run_dir)
    if meta is None:
        return None, "meta.json 不存在或不可解析"
    params = meta.get("params")
    if not isinstance(params, Mapping):
        return None, "meta.json 无 params 映射"
    return dict(params), None


def _diff_params(pa: Mapping[str, Any], pb: Mapping[str, Any]) -> list[dict[str, Any]]:
    """params 逐键 diff（并集键序；added/removed/changed，旧→新直带）。"""
    rows: list[dict[str, Any]] = []
    for key in sorted(set(pa) | set(pb), key=str):
        in_a, in_b = key in pa, key in pb
        if in_a and not in_b:
            rows.append({"key": key, "kind": "removed",
                         "old": pa[key], "new": None})
        elif in_b and not in_a:
            rows.append({"key": key, "kind": "added",
                         "old": None, "new": pb[key]})
        elif not _values_equal(pa[key], pb[key]):
            rows.append({"key": key, "kind": "changed",
                         "old": pa[key], "new": pb[key]})
    return rows


# ─── manifest 节 ────────────────────────────────────────────────────────────


def _find_manifest(run_dir: Path) -> Path | None:
    """run 目录根直下找 K5 模型清单（候选名序；找不到 None）。"""
    for name in _MANIFEST_CANDIDATES:
        p = run_dir / name
        if p.is_file():
            return p
    return None


def _load_manifest_file(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """K5 清单装载（复用 em_doctor_service.load_model_manifest 校验单源）。

    Returns:
        (清单 dict 或 None, 错误信封的 errors 列表或 None)。
    """
    from rfauto.service.em_doctor_service import load_model_manifest

    loaded = load_model_manifest(path)
    if not loaded.get("ok"):
        return None, [str(e) for e in loaded.get("errors", [])]
    return loaded.get("manifest"), None


def _diff_named_group(group: str, items_a: Any, items_b: Any,
                      fields: Sequence[str]) -> list[dict[str, Any]]:
    """一组清单条目按 name 对齐 diff（增/删/字段级变更）。

    条目非映射/缺 name 如实跳过（不猜名；清单校验层已拦多数畸形）。
    """
    def _index(items: Any) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        if isinstance(items, list):
            for it in items:
                if isinstance(it, Mapping) and it.get("name") is not None:
                    out[str(it["name"])] = dict(it)
        return out

    ia, ib = _index(items_a), _index(items_b)
    rows: list[dict[str, Any]] = []
    for name in sorted(set(ia) - set(ib)):
        rows.append({"kind": "remove", "group": group, "name": name,
                     "fields": {}})
    for name in sorted(set(ib) - set(ia)):
        rows.append({"kind": "add", "group": group, "name": name,
                     "fields": {}})
    for name in sorted(set(ia) & set(ib)):
        field_changes: dict[str, dict[str, Any]] = {}
        for field in fields:
            va, vb = ia[name].get(field), ib[name].get(field)
            if not _values_equal(va, vb):
                field_changes[field] = {"old": va, "new": vb}
        if field_changes:
            rows.append({"kind": "change", "group": group, "name": name,
                         "fields": field_changes})
    return rows


def _diff_manifest(ma: Mapping[str, Any], mb: Mapping[str, Any]) -> list[dict[str, Any]]:
    """清单四组逐项 diff（groups 顺序=渲染顺序）。"""
    rows: list[dict[str, Any]] = []
    for group, fields in _MANIFEST_GROUPS.items():
        rows.extend(_diff_named_group(group, ma.get(group), mb.get(group),
                                      fields))
    return rows


# ─── sparams 节 ─────────────────────────────────────────────────────────────


def _find_touchstone(run_dir: Path) -> Path | None:
    """run 产物 Touchstone（K16 同款 glob 口径，取序首）。"""
    files = sorted(run_dir.glob("results/params.s*p"))
    return files[0] if files else None


def _load_touchstone(path: Path) -> tuple[Any | None, str | None]:
    """skrf 读入（失败原因直带；skrf 缺失如实）。"""
    try:
        import skrf
    except ImportError:
        return None, "skrf 不可用"
    try:
        return skrf.Network(str(path)), None
    except Exception as exc:  # 解析错误族宽（touchstone 形态多样）
        return None, f"Touchstone 解析失败: {exc}"


def _tracked_sparams(nports: int) -> list[str]:
    """v1 追踪口径：1 端口=S11；≥2 端口=S11+S21（全矩阵 v2）。"""
    if nports == 1:
        return ["S11"]
    return ["S11", "S21"]


def _sparam_db(net: Any, name: str) -> Any | None:
    """网络指定 S 参数的 dB 曲线（越界/退化 → None）。"""
    import numpy as np

    i, j = int(name[1]) - 1, int(name[2]) - 1
    if net.s.ndim != 3 or net.s.shape[1] <= max(i, j):
        return None
    mag = np.abs(net.s[:, i, j])
    with np.errstate(divide="ignore", invalid="ignore"):
        db = 20.0 * np.log10(np.maximum(mag, _DB_FLOOR))
    return db


def _align_freqs(fa: Any, fb: Any) -> tuple[str, Any, Any]:
    """频栅对齐（#287/#294 家法）。

    - 同栅（等长 + np.allclose rtol=_FREQ_RTOL）→ ("same_grid", 恒等映射)；
    - 异栅 → ("nearest_neighbor", A 每点取 B 的 argmin|Δf| 真最近邻，
      接受带 max(|f|·_FREQ_RTOL, _FREQ_ATOL)，半格错位点拒收)；
    - 零配对 → ("none", 空映射)。
    """
    import numpy as np

    if len(fa) == len(fb) and np.allclose(fa, fb, rtol=_FREQ_RTOL, atol=0.0):
        idx = np.arange(len(fa))
        return "same_grid", idx, idx
    ia_list: list[int] = []
    ib_list: list[int] = []
    for i, f in enumerate(fa):
        j = int(np.argmin(np.abs(fb - f)))
        if abs(float(fb[j]) - float(f)) <= max(
                abs(float(f)) * _FREQ_RTOL, _FREQ_ATOL):
            ia_list.append(i)
            ib_list.append(j)
    if not ia_list:
        return "none", np.array([], dtype=int), np.array([], dtype=int)
    return ("nearest_neighbor", np.array(ia_list, dtype=int),
            np.array(ib_list, dtype=int))


def _diff_sparams(net_a: Any, net_b: Any, at_hz: Sequence[float]) -> dict[str, Any]:
    """S 参数节 diff 核（对齐→逐频 dB 差→最大频点+定点读数）。"""
    import numpy as np

    if net_a.nports != net_b.nports:
        return {"status": "skip",
                "reason": (f"端口数不同（A={net_a.nports} vs B={net_b.nports}"
                           "）——结构级差异，S 参数不可逐频对拍")}
    # 空频栅守卫：空数组进对拍核会 IndexError/ValueError（skip 理由读 f[0]
    # /同栅 allclose 假真/空 argmin 炸）——前置如实 skip 带说明（#316 方向：
    # 数据缺席多报不硬凑）。
    n_fa, n_fb = len(net_a.f), len(net_b.f)
    if n_fa == 0 or n_fb == 0:
        return {"status": "skip",
                "reason": (f"频点为空（A {n_fa} 点 vs B {n_fb} 点）——空曲线"
                           "不可对拍，如实跳过")}
    tracked = _tracked_sparams(net_a.nports)
    curves_a = {name: _sparam_db(net_a, name) for name in tracked}
    curves_b = {name: _sparam_db(net_b, name) for name in tracked}
    missing = [n for n in tracked if curves_a[n] is None or curves_b[n] is None]
    if missing:
        return {"status": "skip",
                "reason": f"端口矩阵缺 {','.join(missing)} 曲线（nports="
                          f"{net_a.nports}）"}
    alignment, ia, ib = _align_freqs(net_a.f, net_b.f)
    if alignment == "none":
        return {"status": "skip",
                "reason": ("频栅不相交（最近邻配对零命中；A "
                           f"{net_a.f[0]:.6g}–{net_a.f[-1]:.6g} Hz vs B "
                           f"{net_b.f[0]:.6g}–{net_b.f[-1]:.6g} Hz）")}
    notes: list[str] = []
    per_sparam: dict[str, dict[str, Any]] = {}
    worst_name, worst_freq, worst_dev = None, None, -1.0
    for name in tracked:
        dev = np.abs(curves_b[name][ib] - curves_a[name][ia])
        k = int(np.argmax(dev))
        f_worst = float(net_a.f[ia][k])
        per_sparam[name] = {"worst_freq_hz": f_worst,
                            "worst_dev_db": float(dev[k])}
        if float(dev[k]) > worst_dev:
            worst_name, worst_freq, worst_dev = name, f_worst, float(dev[k])
    # 定点读数：--at-ghz 各点取配对栅里最近邻（实际落点频率如实回带）。
    matched_f = np.asarray(net_a.f)[ia]
    at_points: list[dict[str, Any]] = []
    for f_req in at_hz:
        k = int(np.argmin(np.abs(matched_f - f_req)))
        row: dict[str, Any] = {
            "kind": "requested", "requested_hz": float(f_req),
            "freq_hz": float(matched_f[k])}
        for name in tracked:
            row[f"{name.lower()}_db_a"] = float(curves_a[name][ia][k])
            row[f"{name.lower()}_db_b"] = float(curves_b[name][ib][k])
            row[f"{name.lower()}_dev_db"] = float(
                abs(curves_b[name][ib][k] - curves_a[name][ia][k]))
        if abs(float(matched_f[k]) - float(f_req)) > max(
                abs(float(f_req)) * _FREQ_RTOL, _FREQ_ATOL):
            row["note"] = "请求频点未精确落栅，取最近配对栅点"
        at_points.append(row)
    # 差异最大频点恒入定点表（人读面"一眼"位）。
    k = int(np.argmin(np.abs(matched_f - worst_freq)))
    worst_row: dict[str, Any] = {"kind": "worst", "requested_hz": None,
                                 "freq_hz": float(matched_f[k])}
    for name in tracked:
        worst_row[f"{name.lower()}_db_a"] = float(curves_a[name][ia][k])
        worst_row[f"{name.lower()}_db_b"] = float(curves_b[name][ib][k])
        worst_row[f"{name.lower()}_dev_db"] = float(
            abs(curves_b[name][ib][k] - curves_a[name][ia][k]))
    at_points.append(worst_row)
    if len(ia) < len(net_a.f):
        notes.append(f"异栅最近邻配对：A {len(net_a.f)} 点中 {len(ia)} 点"
                     "进入对拍（半格错位点拒收）")
    return {
        "status": "ok",
        "alignment": alignment,
        "n_points_a": len(net_a.f),
        "n_points_b": len(net_b.f),
        "n_matched": len(ia),
        "tracked": tracked,
        "worst_sparam": worst_name,
        "worst_freq_hz": worst_freq,
        "worst_dev_db": worst_dev,
        "per_sparam": per_sparam,
        "at_points": at_points,
        "notes": notes,
    }


def _sparams_section(run_a: Path, run_b: Path,
                     at_hz: Sequence[float]) -> tuple[dict[str, Any], dict[str, Any]]:
    """S 参数节装配（发现→读入→diff 核；缺文件/结构差异如实 skip）。"""
    files = {"a": _find_touchstone(run_a), "b": _find_touchstone(run_b)}
    skip: dict[str, Any] = {"status": "skip"}
    for side, path in files.items():
        if path is None:
            skip["reason"] = (
                f"{side.upper()} 侧无 Touchstone 产物（results/params.s*p）")
            return skip, files
    net_a, err_a = _load_touchstone(files["a"])
    net_b, err_b = _load_touchstone(files["b"])
    if err_a or err_b:
        skip["reason"] = "；".join(e for e in (err_a, err_b) if e)
        return skip, files
    return _diff_sparams(net_a, net_b, at_hz), files


# ─── freshness 节（K4 交叉） ────────────────────────────────────────────────


def _freshness_side(run_dir: Path) -> dict[str, Any]:
    """单侧 K4 verify_run 状态行（只读 import；异常如实 unknown）。"""
    from rfauto.service.runs_verify_service import verify_run

    try:
        verdict = verify_run(run_dir)
    except Exception as exc:  # 新鲜度是观测面，不阻塞 diff 主路径（#105）
        return {"status": "unknown", "ok": None, "run_id": run_dir.name,
                "note": f"verify_run 异常: {exc}"}
    return {
        "status": str(verdict.get("status", "unknown")),
        "ok": verdict.get("ok"),
        "run_id": verdict.get("run_id", run_dir.name),
        "issues_n": len(verdict.get("issues") or []),
        "note": str(verdict.get("note", "") or ""),
    }


# ─── 汇总入口 ───────────────────────────────────────────────────────────────


def diff_runs(
    run_a: str | Path, run_b: str | Path, *,
    sections: Sequence[str] = DEFAULT_SECTIONS,
    at_ghz: Sequence[float] = (),
) -> dict[str, Any]:
    """两个 run 目录的四节 diff（规则 4：JSON 进出信封）。

    Args:
        run_a/run_b: run 目录路径（目录级，**不是** runs 湖 run_id——
            那是 ``runs compare`` 的口径）。
        sections: 参与对比的节（``DIFF_SECTIONS`` 子集；未知节名=error
            信封。freshness 恒出，不随裁剪）。
        at_ghz: S 参数定点读数频率（GHz；可多点）。

    Returns:
        ok 信封：``run_a/run_b``（解析后路径）、``params_changes``/
        ``model_changes``（空列表=无变更）、``sparam_diff``（含
        status/alignment/worst_freq_hz/worst_dev_db/at_points）、
        ``freshness={a,b}``、``summary``（计数账）、``meta_summary``
        （两侧 adapter/model/status 头信息，best-effort）。缺节如实
        skip（``*_status="skip"``+原因），不伪造空 diff 冒充可比。
    """
    # #140：PathLike 入参第一行收敛
    path_a, path_b = Path(run_a), Path(run_b)
    if not path_a.is_dir():
        return error_envelope(f"run 目录 A 不存在: {path_a}", run_a=str(path_a))
    if not path_b.is_dir():
        return error_envelope(f"run 目录 B 不存在: {path_b}", run_b=str(path_b))
    requested = [str(s).strip().lower() for s in sections]
    unknown = [s for s in requested if s not in DIFF_SECTIONS]
    if unknown:
        return error_envelope(
            f"未知对比节: {', '.join(unknown)}（可选：{', '.join(DIFF_SECTIONS)}）",
            requested_sections=requested)
    try:
        at_hz = [float(g) * 1e9 for g in at_ghz]
    except (TypeError, ValueError):
        return error_envelope(f"--at-ghz 必须是数字（GHz），实际 {at_ghz!r}")

    out: dict[str, Any] = ok_envelope(
        command="em diff",
        run_a=str(path_a), run_b=str(path_b),
        requested_sections=[s for s in DIFF_SECTIONS if s in requested],
    )

    # 头信息（best-effort：adapter/model/status 一眼可比）
    meta_summary: dict[str, Any] = {}
    for side, path in (("a", path_a), ("b", path_b)):
        meta = _load_meta(path) or {}
        meta_summary[side] = {
            "adapter": meta.get("adapter"), "model": meta.get("model"),
            "status": meta.get("status"),
        }
    out["meta_summary"] = meta_summary

    # params 节
    if "params" in requested:
        pa, err_a = _load_meta_params(path_a)
        pb, err_b = _load_meta_params(path_b)
        if err_a or err_b:
            out["params_changes"] = []
            out["params_status"] = "skip"
            out["params_skip_reason"] = "；".join(
                f"{side} 侧 {e}" for side, e in (("A", err_a), ("B", err_b))
                if e)
        else:
            out["params_changes"] = _diff_params(pa or {}, pb or {})
            out["params_status"] = "ok"
    else:
        out["params_changes"] = []
        out["params_status"] = "not_requested"

    # manifest 节
    out["manifest_files"] = {"a": None, "b": None}
    if "manifest" in requested:
        man_a, man_b = _find_manifest(path_a), _find_manifest(path_b)
        out["manifest_files"] = {
            "a": str(man_a) if man_a else None,
            "b": str(man_b) if man_b else None,
        }
        if man_a is None and man_b is None:
            out["model_changes"] = []
            out["model_status"] = "skip"
            out["model_skip_reason"] = (
                "两侧均无模型清单（model_manifest.json/yaml，em doctor 导出"
                "形态）——.aedt 活体解析暂未提供")
        elif man_a is None or man_b is None:
            missing_side = "A" if man_a is None else "B"
            other = man_b if man_a is None else man_a
            out["model_changes"] = []
            out["model_status"] = "skip"
            out["model_skip_reason"] = (
                f"仅 {'B' if missing_side == 'A' else 'A'} 侧有模型清单，"
                f"{missing_side} 侧无（{other.name}）——不可比，跳过该节")
        else:
            loaded_a, errs_a = _load_manifest_file(man_a)
            loaded_b, errs_b = _load_manifest_file(man_b)
            if errs_a or errs_b:
                out["model_changes"] = []
                out["model_status"] = "skip"
                out["model_skip_reason"] = "；".join(
                    f"{side} 侧清单装载失败: {'; '.join(errs)}"
                    for side, errs in (("A", errs_a), ("B", errs_b)) if errs)
            else:
                out["model_changes"] = _diff_manifest(loaded_a or {},
                                                      loaded_b or {})
                out["model_status"] = "ok"
    else:
        out["model_changes"] = []
        out["model_status"] = "not_requested"

    # sparams 节
    if "sparams" in requested:
        result, files = _sparams_section(path_a, path_b, at_hz)
        out["sparam_diff"] = result
        if files["a"] or files["b"]:
            out["sparam_files"] = {k: str(v) if v else None
                                   for k, v in files.items()}
    else:
        out["sparam_diff"] = {"status": "not_requested"}

    # freshness 节（恒出；显式请求只影响 requested_sections 记账）
    out["freshness"] = {"a": _freshness_side(path_a),
                        "b": _freshness_side(path_b)}

    # 计数账（一眼判定面）
    sparam = out["sparam_diff"]
    out["summary"] = {
        "n_param_changes": len(out["params_changes"]),
        "n_model_changes": len(out["model_changes"]),
        "sparam_status": sparam.get("status"),
        "sparam_worst_dev_db": (sparam.get("worst_dev_db")
                                if sparam.get("status") == "ok" else None),
        "freshness": {k: v["status"] for k, v in out["freshness"].items()},
    }
    return out


# ─── 人读渲染（to_text：纯文本，一眼可读；禁 rich markup 方括号） ────────────


def _fmt_val(value: Any) -> str:
    """人读值格式化（有限数值 .6g；其余 str；None=—；em metrics 叶同口径）。"""
    if value is None:
        return "—"
    if _is_number(value):
        return format(float(value), ".6g")
    return str(value)


_AXIS_LABELS = ("x", "y", "z")


def _render_bbox_change(old: Any, new: Any) -> str | None:
    """bbox 类字段变更渲染：只列变化的轴（"z: 0–190 → 0–295.2"）。

    6 元 bbox=xy(z) 对；2 元=z_range；4 元 rect=xy 对；非数值/异形 → None
    （退回整值渲染）。零变化轴不列（一眼看差异轴）。
    """
    def _pairs(vals: Any, n_axes: int) -> list[tuple[Any, Any]] | None:
        if not isinstance(vals, (list, tuple)) or len(vals) != 2 * n_axes:
            return None
        if not all(_is_number(v) for v in vals):
            return None
        return [(vals[k], vals[k + n_axes]) for k in range(n_axes)]

    n_axes = {6: 3, 2: 1, 4: 2}.get(
        len(old) if isinstance(old, (list, tuple)) else 0, 0)
    if not n_axes:
        return None
    pa, pb = _pairs(old, n_axes), _pairs(new, n_axes)
    if pa is None or pb is None:
        return None
    labels = _AXIS_LABELS if n_axes == 3 else (
        ("z",) if n_axes == 1 else ("x", "y"))
    parts = []
    for axis, (a0, a1), (b0, b1) in zip(labels, pa, pb, strict=True):
        if _values_equal((a0, a1), (b0, b1)):
            continue
        parts.append(f"{axis}: {_fmt_val(a0)}–{_fmt_val(a1)} → "
                     f"{_fmt_val(b0)}–{_fmt_val(b1)}")
    return "  ".join(parts) if parts else None


def _render_field_change(field: str, old: Any, new: Any) -> str:
    """单字段变更渲染（bbox 走变化轴紧凑形，其余 整值 old → new）。"""
    if isinstance(old, (list, tuple)) and isinstance(new, (list, tuple)) \
            and len(old) == len(new):
        compact = _render_bbox_change(old, new)
        if compact:
            return f"{field} {compact}"
    return f"{field}: {_fmt_val(old)} → {_fmt_val(new)}"


def _render_section_skip(status: Any, reason: Any, indent: str) -> list[str]:
    """skip/not_requested 节的人读行。"""
    if status == "skip":
        return [f"{indent}（本节跳过：{reason}）"]
    if status == "not_requested":
        return [f"{indent}（本节未选——--sections 可加）"]
    return []


def to_text(diff: Mapping[str, Any]) -> str:
    """diff 信封 → 人话文本（变更按节分组+差异最大频点突出；纯文本）。"""
    lines: list[str] = [
        f"em diff  A={diff.get('run_a')}  B={diff.get('run_b')}",
    ]
    meta = diff.get("meta_summary") or {}
    if meta:
        bits = []
        for side in ("a", "b"):
            m = meta.get(side) or {}
            bits.append(f"{side.upper()}: adapter={_fmt_val(m.get('adapter'))}"
                        f" model={_fmt_val(m.get('model'))}"
                        f" status={_fmt_val(m.get('status'))}")
        lines.append(f"  meta  {' / '.join(bits)}")

    # params 节
    changes = diff.get("params_changes") or []
    status = diff.get("params_status")
    if status in ("skip", "not_requested"):
        lines += _render_section_skip(status, diff.get("params_skip_reason"),
                                      "  参数/网格档: ")
    else:
        lines.append(f"  参数/网格档: {len(changes)} 处变更")
        for row in changes:
            kind, key = row.get("kind"), row.get("key")
            if kind == "added":
                lines.append(f"    + {key}: （B 新增）{_fmt_val(row.get('new'))}")
            elif kind == "removed":
                lines.append(f"    - {key}: （B 无此键）{_fmt_val(row.get('old'))}")
            else:
                lines.append(f"    ~ {key}: {_fmt_val(row.get('old'))} → "
                             f"{_fmt_val(row.get('new'))}")

    # manifest 节
    changes = diff.get("model_changes") or []
    status = diff.get("model_status")
    if status in ("skip", "not_requested"):
        lines += _render_section_skip(status, diff.get("model_skip_reason"),
                                      "  模型清单: ")
    else:
        by_group: dict[str, list[dict[str, Any]]] = {}
        for row in changes:
            by_group.setdefault(str(row.get("group")), []).append(row)
        head = "、".join(
            f"{_GROUP_LABELS.get(g, g)} {len(rows)}"
            for g, rows in sorted(by_group.items()))
        lines.append(f"  模型清单: {len(changes)} 处变更"
                     + (f"（{head}）" if head else ""))
        for group in ("ports", "objects", "stackup", "keepouts"):
            for row in by_group.get(group, []):
                label = _GROUP_LABELS.get(group, group)
                kind = row.get("kind")
                name = row.get("name")
                if kind == "add":
                    lines.append(f"    {label} {name}: B 新增")
                elif kind == "remove":
                    lines.append(f"    {label} {name}: B 无此条（A 独有）")
                else:
                    rendered = "；".join(
                        _render_field_change(f, ch["old"], ch["new"])
                        for f, ch in (row.get("fields") or {}).items())
                    lines.append(f"    {label} {name}: {rendered}")

    # sparams 节
    sparam = diff.get("sparam_diff") or {}
    sp_status = sparam.get("status")
    if sp_status == "not_requested":
        lines.append("  S 参数: （本节未选——--sections 可加）")
    elif sp_status == "skip":
        lines.append(f"  S 参数: （本节跳过：{sparam.get('reason')}）")
    elif sp_status == "ok":
        align = sparam.get("alignment")
        n_matched = sparam.get("n_matched")
        worst_name = sparam.get("worst_sparam")
        worst_dev = sparam.get("worst_dev_db")
        worst_freq = sparam.get("worst_freq_hz")
        lines.append(
            f"  S 参数: 最大偏差 {_fmt_val(worst_dev)} dB"
            f"（{worst_name} @ {_fmt_val(worst_freq)} Hz；"
            f"对齐={align} {n_matched} 点）")
        for row in sparam.get("at_points") or []:
            bits = []
            for name in sparam.get("tracked") or []:
                key = name.lower()
                bits.append(
                    f"{name} {_fmt_val(row.get(f'{key}_db_a'))} → "
                    f"{_fmt_val(row.get(f'{key}_db_b'))}"
                    f"（Δ{_fmt_val(row.get(f'{key}_dev_db'))} dB）")
            head = (f"@{row.get('requested_hz') / 1e9:.6g} GHz"
                    if row.get("requested_hz") is not None
                    else f"@{_fmt_val(row.get('freq_hz'))} Hz")
            tag = "最差点 " if row.get("kind") == "worst" else ""
            note = f"（{row['note']}）" if row.get("note") else ""
            lines.append(f"    {tag}{head}: " + "｜".join(bits) + note)
        for note in sparam.get("notes") or []:
            lines.append(f"    注: {note}")
    else:
        lines.append(f"  S 参数: （未知状态 {sp_status}）")

    # freshness 节（恒出）
    fresh = diff.get("freshness") or {}
    fresh_bits = []
    for side in ("a", "b"):
        f = fresh.get(side) or {}
        line = f"{side.upper()}={_fmt_val(f.get('status'))}"
        if f.get("issues_n"):
            line += f"（issues {f['issues_n']} 条）"
        if f.get("note"):
            line += f"：{f['note']}"
        fresh_bits.append(line)
    lines.append(f"  新鲜度: {' / '.join(fresh_bits)}")
    return "\n".join(lines)
