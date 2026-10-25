"""dataset_service.workdir_params —— 工作目录参数 JSON 写出端与
键路径解析簇（import_workdir_runs 契约的单一事实源）。

自 workdir.py 域内二次分域（aurora_g W7-S1 T2：workdir 835 行
超 800 棘轮，参数写出/解析簇自洽成叶）；代码体逐字节搬迁。
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

_WORKDIR_PARAM_PATHS = (
    "params", "calib_params", "design_params", "design_point", "design",
    "geometry", "geom.nominal", "nominal",
)
_WORKDIR_JSON_MAX_BYTES = 4 * 1024 * 1024


def write_workdir_params_json(
    point_dir: str | Path,
    params: dict[str, Any],
    *,
    curve: str | Path | None = None,
    filename: str | None = None,
) -> Path:
    """战役脚本侧设计参数落盘——import_workdir_runs 键路径契约的**写出端**
    （与读取端 :func:`_params_from_json` 同模块单一事实源，契约不漂移）。

    在 ``point_dir``（点目录；多曲线工作目录传工作目录根）写参数 JSON，
    顶层 ``{"params": {标量 dict}}``——即 :data:`_WORKDIR_PARAM_PATHS` 最高
    优先级键路径，值全 python 标量（str/int/float/bool）。写出前经
    :func:`rfauto.infra.recipe_guard.sanitize_numpy_scalars` 收敛 np 标量
    （综合内核 np.float64 泄漏在写出端拦截）；非标量/非有限 float 显式抛
    TypeError/ValueError，不静默丢弃（#320 教训：落盘的必须是"该点实跑
    几何"，宁可在战役侧失败也不产出不可归属/不可信的参数）。

    curve：该点曲线产物路径（可选）。给定时
    ① 缺省文件名 = 曲线同名 stem.json——多曲线工作目录（hfss_marchand_anchor
    根级多 sNp 形态）靠读取端"同名 stem"归属；
    ② JSON 额外嵌 "curve" 键（相对 point_dir=JSON 所在目录的 posix 路径，
    读取端 :func:`_json_mentions_path` 显式引用双保险）。曲线在 point_dir
    内 → 相对路径不带 ``..``；在 point_dir 外 → 回退
    ``os.path.relpath`` 相对路径（R3-C-03：多子目录同名 stem 时纯文件名
    引用有歧义，如 ``../batch_a/pt1.s2p`` vs ``../batch_b/pt1.s2p``）；
    仅当相对路径不可达（Windows 跨盘符等 relpath 抛 ValueError）才退回纯
    文件名，并嵌显著字段 ``curve_ref_ambiguous: true`` 不静默。
    filename 显式给定时覆盖 ①（单曲线点目录缺省 "params.json"，传
    curve=None 即可）。

    返回写出的 JSON 路径。参数落盘是数据集入库的业务路径（非观测性），
    失败直接抛、不 best-effort。
    """
    if not isinstance(params, dict) or not params:
        raise TypeError("params 必须是非空 dict")
    from rfauto.infra.recipe_guard import sanitize_numpy_scalars

    clean = sanitize_numpy_scalars(dict(params))
    bad = {str(k): type(v).__name__ for k, v in clean.items()
           if not isinstance(v, (str, int, float, bool))}
    if bad:
        raise TypeError(f"params 含非标量值（只收 str/int/float/bool）: {bad}")
    nonfinite = sorted(k for k, v in clean.items()
                       if isinstance(v, float) and not math.isfinite(v))
    if nonfinite:
        raise ValueError(f"params 含非有限值（NaN/±Inf）: {nonfinite}")
    payload: dict[str, Any] = {"params": clean}
    if curve is not None:
        c = Path(curve)
        base = Path(point_dir).resolve()
        ambiguous = False
        try:
            ref = c.resolve().relative_to(base).as_posix()
        except ValueError:
            # 曲线在 point_dir（=JSON 所在目录）外：回退相对路径引用，
            # 多子目录同名 stem 时纯文件名有歧义（R3-C-03）。
            try:
                ref = Path(os.path.relpath(c.resolve(), base)).as_posix()
            except ValueError:
                # Windows 跨盘符等 relpath 不可达：保留纯文件名旧行为，
                # 加显著字段不静默。
                ref = c.name
                ambiguous = True
        payload["curve"] = ref
        if ambiguous:
            payload["curve_ref_ambiguous"] = True
        if filename is None:
            filename = f"{c.stem}.json"
    if filename is None:
        filename = "params.json"
    out = Path(point_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / filename
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, allow_nan=False) + "\n",
        encoding="utf-8")
    return path


def _scalar_items(obj: Any) -> dict[str, Any]:
    """dict 顶层标量项（str/int/float/bool，含非有限 float，交由调用方处置）。"""
    if not isinstance(obj, dict):
        return {}
    return {str(k): v for k, v in obj.items()
            if isinstance(v, (str, int, float, bool))}


def _dig_path(obj: Any, dotted: str) -> Any:
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _params_from_json(data: dict[str, Any]) -> tuple[dict[str, Any], str] | None:
    """按 _WORKDIR_PARAM_PATHS 优先级取首个非空标量 dict → (params, 键路径)。"""
    for key_path in _WORKDIR_PARAM_PATHS:
        node = _dig_path(data, key_path)
        if isinstance(node, dict):
            scalars = _scalar_items(node)
            if scalars:
                return scalars, key_path
    return None


def _json_mentions_path(obj: Any, rel: str) -> bool:
    """JSON 任一字符串值是否以 rel（posix 相对路径）结尾——整段路径分量匹配，
    '/' 与 '\\' 同认（helix 仲裁 JSON 的 s1p 键是绝对 Windows 路径）。"""
    if isinstance(obj, str):
        s = obj.replace("\\", "/")
        return s == rel or s.endswith("/" + rel)
    if isinstance(obj, dict):
        return any(_json_mentions_path(v, rel) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return any(_json_mentions_path(v, rel) for v in obj)
    return False


def _load_json_dict(path: Path) -> dict[str, Any] | None:
    """读 JSON 对象（超 _WORKDIR_JSON_MAX_BYTES / 解析失败 / 非对象 → None）。"""
    try:
        if path.stat().st_size > _WORKDIR_JSON_MAX_BYTES:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _resolve_workdir_params(
    artifact: Path, workdir: Path, n_curves_in_dir: int,
) -> tuple[dict[str, Any], dict[str, Any], Path, str] | None:
    """曲线产物 → (params, metrics, 参数出处 JSON 路径, 键路径)；无可归属 → None。

    逐级上溯（曲线目录 → … → 工作目录根），每级两遍：① 显式引用/同名 stem
    的 JSON；② 仅单曲线目录认无引用 JSON。见模块段注释"归属规则"。
    """
    single = n_curves_in_dir == 1
    stem = artifact.stem.lower()
    level = artifact.parent
    while True:
        try:
            jsons = sorted((p for p in level.iterdir()
                            if p.is_file() and p.suffix.lower() == ".json"),
                           key=lambda p: p.name.lower())
        except OSError:
            jsons = []
        loaded: list[tuple[Path, dict[str, Any]]] = []
        for jp in jsons:
            data = _load_json_dict(jp)
            if data is not None:
                loaded.append((jp, data))
        rel_from_level = artifact.relative_to(level).as_posix()
        for jp, data in loaded:
            if jp.stem.lower() == stem or _json_mentions_path(data, rel_from_level):
                hit = _params_from_json(data)
                if hit is not None:
                    return hit[0], _scalar_items(data), jp, hit[1]
        if single:
            for jp, data in loaded:
                hit = _params_from_json(data)
                if hit is not None:
                    return hit[0], _scalar_items(data), jp, hit[1]
        if level == workdir:
            return None
        parent = level.parent
        if parent == level:
            return None
        level = parent
