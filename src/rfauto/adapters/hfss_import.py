"""HFSS 工程导入器（.aedt → 配方草稿 + 设计规格 JSON）。

用户拿着自建 HFSS 工程（魔改结构、非典型拓扑）时，不必手写配方：
本模块用 PyAEDT 打开工程，读取设计变量、Optimetrics 扫参范围、Setup/Sweep
与端口，生成 rfauto 配方草稿（hfss_var_map + 参数范围），供 UI 展示与
agent 提案-审批链路继续调优。

PyAEDT 为可选依赖（延迟 import，缺失时报可读错误，#105 best-effort 原则）。
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _open_hfss(project_path: str, design_name: str | None, version: str,
               non_graphical: bool):
    """打开工程（复用已连 Desktop 或新建），返回 Hfss 对象。调用方负责 release。"""
    from ansys.aedt.core import Hfss

    return Hfss(
        project=project_path,
        design=design_name,
        version=version,
        non_graphical=non_graphical,
        new_desktop=False,
    )


def _read_variables(hfss: Any) -> dict[str, dict[str, Any]]:
    """读取设计变量 + 工程级 $ 变量（名称/表达式/数值/单位），标记依赖变量。

    兼容 PyAEDT 差异：design_variable_names 等在部分版本是属性、部分是方法；
    numeric_value 为 None 时从表达式前缀解析数值（如 "0.265mm" → 0.265）。
    """
    out: dict[str, dict[str, Any]] = {}

    def _names(prop: str) -> list[str]:
        obj = getattr(vm, prop, None)
        if obj is None:
            return []
        if callable(obj):
            obj = obj()
        return list(obj)

    def _vars_dict(prop: str) -> dict:
        obj = getattr(vm, prop, None)
        if callable(obj):
            obj = obj()
        return obj or {}

    try:
        vm = hfss.variable_manager
        entries: list[tuple[str, dict[str, Any], bool]] = []
        for name in _names("design_variable_names"):
            entries.append((name, _vars_dict("design_variables").get(name), False))
        for name in _names("project_variable_names"):
            entries.append((name, _vars_dict("project_variables").get(name), False))
        for name, info, _dep in entries:
            if name in out:
                continue
            try:
                expression = str(getattr(info, "expression", "") if info else "")
                numeric = getattr(info, "numeric_value", None) if info else None
                value = repr(numeric) if numeric is not None else _parse_leading_float(expression)
                out[name] = {
                    "expression": expression,
                    "value": value,
                    "units": str(getattr(info, "units", "") if info else ""),
                    "dependent": bool(getattr(info, "is_dependent", False)
                                      or name.startswith("$")),
                }
            except Exception as exc:  # 单变量读取失败不阻塞整体（#105）
                logger.warning("读取变量 %s 失败: %s", name, exc)
    except Exception as exc:
        logger.warning("variable_manager 读取失败: %s", exc)
    return out


def _parse_leading_float(expression: str) -> str:
    """从表达式前缀解析数值（"0.265mm" → "0.265"）；失败返回 "None"。"""
    import re as _re

    m = _re.match(r"\s*[-+]?\d*\.?\d+([eE][-+]?\d+)?", str(expression))
    return m.group(0).strip() if m else "None"


def _read_setup_sweep(hfss: Any) -> dict[str, Any]:
    """读取第一个 Setup 与其 Sweep（名称/频率范围/点数）。"""
    spec: dict[str, Any] = {}
    try:
        setups = hfss.setups or []
        if not setups:
            return spec
        su = setups[0]
        spec["setup_name"] = su.name
        props = getattr(su, "props", {}) or {}
        # HFSS Solution Setup：频率属性名随求解类型不同，尽力提取
        for key in ("Frequency", "Solution Freq", "Adaptive Freq"):
            if key in props:
                spec["freq_str"] = str(props[key])
                break
        sweeps = []
        for sw in getattr(su, "sweeps", []) or []:
            sp = getattr(sw, "props", {}) or {}
            sweeps.append({
                "name": getattr(sw, "name", ""),
                "type": str(sp.get("Type", "Interpolating")),
                "range_start": str(sp.get("RangeStart", sp.get("Start", ""))),
                "range_end": str(sp.get("RangeEnd", sp.get("End", ""))),
                "step": str(sp.get("RangeStep", sp.get("Step", ""))),
                "count": str(sp.get("RangeCount", sp.get("Count", ""))),
            })
        spec["sweeps"] = sweeps
    except Exception as exc:
        logger.warning("Setup/Sweep 读取失败: %s", exc)
    return spec


def _read_ports(hfss: Any) -> list[dict[str, Any]]:
    """读取边界/端口（名称+类型），端口即激励边界。"""
    ports: list[dict[str, Any]] = []
    try:
        for b in hfss.boundaries or []:
            ports.append({
                "name": getattr(b, "name", ""),
                "type": str(getattr(b, "type", "")),
            })
    except Exception as exc:
        logger.warning("边界/端口读取失败: %s", exc)
    return ports


def _read_parametrics(hfss: Any) -> dict[str, dict[str, str]]:
    """读取 Optimetrics 参数化扫参（变量 → start/stop/step），即用户已设范围。"""
    ranges: dict[str, dict[str, str]] = {}
    try:
        for p in hfss.parametrics or []:
            props = getattr(p, "props", {}) or {}
            var = str(props.get("Variable", ""))
            if var:
                ranges[var] = {
                    "start": str(props.get("Start", "")),
                    "stop": str(props.get("Stop", "")),
                    "step": str(props.get("Step", "")),
                }
    except Exception as exc:
        logger.warning("Optimetrics 参数化读取失败: %s", exc)
    return ranges


def _prune_ansysem_env(version: str) -> None:
    """多版本 ANSYSEM_ROOTxxx 并存会使 PyAEDT 混淆（issue #7410）——只保留
    与目标版本匹配的环境变量（"2023.1"→ROOT231，"2026.1"→ROOT261）。"""
    digits = version.split(".")
    want = ("ANSYSEM_ROOT" + digits[0][-2:] + digits[1] if len(digits) >= 2
            else "ANSYSEM_ROOT" + version[-3:])
    for k in list(os.environ):
        if k.startswith("ANSYSEM_ROOT") and k != want:
            logger.info("移除冲突环境变量 %s（目标 %s）", k, want)
            del os.environ[k]


def import_project_spec(
    project_path: str,
    design_name: str | None = None,
    *,
    version: str = "2023.1",
    non_graphical: bool = True,
) -> dict[str, Any]:
    """读取 HFSS 工程的设计规格（变量/扫参/Setup/端口）。

    注意：默认 2023.1——PyAEDT 1.4.0 对 AEDT 2026.1 存在未修复兼容问题
    （issue #7410，WNUA 挂死/OpenProject 失败），2023.1 实测可开 2021 老工程。

    Returns
    -------
    dict
        {"ok": bool, "project":..., "design":..., "variables": {...},
         "parametrics": {...}, "setup": {...}, "ports": [...], "error"?: str}
    """
    if not Path(project_path).exists():
        return {"ok": False, "error": f"工程文件不存在: {project_path}"}
    if Path(str(project_path) + ".lock").exists():
        return {"ok": False, "error":
                f"工程被锁定（{project_path}.lock 存在）：先关闭占用它的 AEDT"
                " 会话；若是残留锁可手动删除该 .lock 目录"}
    _prune_ansysem_env(version)
    try:
        hfss = _open_hfss(project_path, design_name, version, non_graphical)
    except Exception as exc:
        return {"ok": False, "error": f"打开 HFSS 工程失败: {exc}"}

    try:
        return {
            "ok": True,
            "project": project_path,
            "design": getattr(hfss, "design_name", design_name),
            "variables": _read_variables(hfss),
            "parametrics": _read_parametrics(hfss),
            "setup": _read_setup_sweep(hfss),
            "ports": _read_ports(hfss),
        }
    finally:
        with contextlib.suppress(Exception):
            hfss.release()


def spec_to_recipe_draft(spec: dict[str, Any], *, model_name: str = "custom_hfss",
                         default_range_frac: float = 0.2) -> dict[str, Any]:
    """把 import_project_spec 的输出转成 rfauto 配方草稿。

    参数范围优先取 Optimetrics 扫参范围（用户在 HFSS 里设的），没有的独立
    变量给 ±default_range_frac 对称范围（数值型才有；依赖变量不进优化空间）。
    """
    if not spec.get("ok"):
        return {"ok": False, "error": spec.get("error", "spec 无效")}
    variables = spec.get("variables", {})
    ranges = spec.get("parametrics", {})

    params: dict[str, dict[str, Any]] = {}
    var_map: dict[str, str] = {}
    for name, info in variables.items():
        if info.get("dependent"):
            continue  # 依赖变量由表达式驱动，不可独立调
        var_map[name] = name
        rng = ranges.get(name)
        try:
            value = float(info.get("value", "") or 0.0)
        except (TypeError, ValueError):
            continue  # 非数值变量（字符串/开关）不进优化空间
        if rng:
            lo = _to_float_mm(rng["start"])
            hi = _to_float_mm(rng["stop"])
            if lo is None or hi is None:
                continue
            params[name] = {"value": value, "low": lo, "high": hi}
        else:
            params[name] = {"value": value,
                            "low": round(value * (1 - default_range_frac), 6),
                            "high": round(value * (1 + default_range_frac), 6)}

    setup = spec.get("setup", {})
    freq_range = _freq_range_from(setup, spec)
    recipe: dict[str, Any] = {
        "recipe_version": 1,
        "schema_version": 1,
        "model": model_name,
        "source_project": spec.get("project"),
        "source_design": spec.get("design"),
        "hfss_var_map": var_map,
        "params": params,
        "setup": {"freq_range_ghz": freq_range, "points": 101},
        "objectives": [],  # 留待用户/agent 在 UI 上定义
    }
    return {"ok": True, "recipe": recipe}


def _freq_range_from(setup: dict[str, Any], spec: dict[str, Any]) -> list[float]:
    """尽力从 Sweep/Setup 提取频率范围（GHz）；失败给 1-10GHz 默认。"""
    try:
        for sw in setup.get("sweeps", []):
            start, end = sw.get("range_start", ""), sw.get("range_end", "")
            if start and end:
                return [float(_strip_units(start)) / 1e9,
                        float(_strip_units(end)) / 1e9]
        freq_str = setup.get("freq_str", "")
        if freq_str:
            f0 = float(_strip_units(freq_str))
            return [max(0.1, f0 / 1e9 * 0.5), f0 / 1e9 * 1.5]
    except (ValueError, TypeError):
        pass
    return [1.0, 10.0]


def _to_float_mm(s: str) -> float | None:
    """HFSS 长度串（"17mm"/"500um"/"2cm"/"0.019"）→ mm 数值；解析失败 None。"""
    t = str(s).strip().lower()
    try:
        if t.endswith("mm"):
            return float(t[:-2])
        if t.endswith("um"):
            return float(t[:-2]) / 1000.0
        if t.endswith("cm"):
            return float(t[:-2]) * 10.0
        if t.endswith("m"):
            return float(t[:-1]) * 1000.0
        return float(t)
    except (ValueError, TypeError):
        return None


def _strip_units(s: str) -> str:
    """HFSS 频率串（"2.4GHz"/"500MHz"/"1e9"）→ 以 Hz 计的数值串。"""
    t = str(s).strip()
    tl = t.lower()
    try:
        if tl.endswith("ghz"):
            return repr(float(tl[:-3]) * 1e9)
        if tl.endswith("mhz"):
            return repr(float(tl[:-3]) * 1e6)
        if tl.endswith("hz"):
            return repr(float(tl[:-2]))
        return repr(float(t))
    except ValueError:
        return t


# ─── B-27：真实 .aedt → spec → 配方草案端到端（只读副本 + 渲染往返）──────────
#
# 真机安全（B-27）：打开的是工程**副本**，用户 .aedt 不可能被改；
# 独立 new_desktop 会话 + remove_lock=False；读完 release（pyaedt 1.4.0 无
# .release()，旧调用被 suppress 吞成静默泄漏，见 _release_hfss）；副本即删。
# 硬超时由 scripts/hfss_import_roundtrip.py 的父子进程看门狗兜底；库内 timeout_s
# 只做尽力而为的线程级守卫（AEDT 的阻塞调用本身不可中断）。

_READONLY_TIMEOUT_S = 300.0


def _resolve_aedt_version(version: str | None) -> str:
    """版本串解析：显式优先 → infra 探测本机 AEDT → 兜底 2023.1。"""
    if version:
        return str(version)
    try:
        from rfauto.infra.version_probe import resolve_aedt_install

        install = resolve_aedt_install()
        if install and install.get("aedt_version"):
            return str(install["aedt_version"])
    except Exception as exc:  # best-effort：探测失败不阻塞（#105）
        logger.info("AEDT 版本探测失败，回退默认版本: %s", exc)
    return "2023.1"


def _open_hfss_readonly(project_path: str, design_name: str | None, version: str,
                        non_graphical: bool):
    """只读打开工程副本（独立非图形会话，不附着用户桌面、不碰锁）。"""
    from ansys.aedt.core import Hfss

    # 真机实证：不要开 settings.use_multi_desktop——开了之后
    # variable_manager 读回 0 个变量（design 能开、变量全丢）；默认路径实测
    # 稳定读回 35 个变量。安全性由"只打开副本"保证，不靠会话隔离。
    return Hfss(
        project=project_path,
        design=design_name,
        version=version,
        non_graphical=non_graphical,
        new_desktop=True,
        close_on_exit=False,
        remove_lock=False,
    )


def _release_hfss(hfss: Any) -> None:
    """释放 AEDT 会话，绝不保存工程（best-effort，异常不外抛）。

    pyaedt 1.4.0 的 Hfss 没有 .release()——旧代码 hfss.release() 被
    contextlib.suppress 吞掉，等于从不释放（B-27 真机实证）。
    正确收尾是 release_desktop() / close_desktop()（内部 CloseProject
    不落盘）；仅老版本才回退 .release()。
    """
    for name, kwargs in (
        ("release_desktop", {"close_projects": False, "close_desktop": True}),
        ("close_desktop", {}),
    ):
        fn = getattr(hfss, name, None)
        if callable(fn):
            try:
                fn(**kwargs)
            except Exception as exc:  # pragma: no cover - 收尾失败不阻塞
                logger.warning("释放 HFSS 会话失败（%s）: %s", name, exc)
            return
    fn = getattr(hfss, "release", None)  # pragma: no cover - 老版本回退
    if callable(fn):
        with contextlib.suppress(Exception):
            fn()


def _collect_spec(hfss: Any) -> dict[str, Any]:
    """从已打开的 Hfss 会话收集设计规格（变量/扫参/Setup/端口）。"""
    return {
        "design": getattr(hfss, "design_name", None),
        "variables": _read_variables(hfss),
        "parametrics": _read_parametrics(hfss),
        "setup": _read_setup_sweep(hfss),
        "ports": _read_ports(hfss),
    }


def import_project_spec_readonly(
    project_path: str,
    design_name: str | None = None,
    *,
    version: str | None = None,
    non_graphical: bool = True,
    timeout_s: float = _READONLY_TIMEOUT_S,
) -> dict[str, Any]:
    """只读导入 .aedt 设计规格（B-27）：先复制再打开，用户工程零风险。

    与 import_project_spec 的差别：
    1. 打开的是临时目录里的**副本**——任何意外保存都落在副本，原件不动；
    2. 源目录的 .lock 不影响读取（副本不带锁）；
    3. 独立 new_desktop 会话 + remove_lock=False；
    4. timeout_s 内未返回即报超时（后台线程自行释放并清理副本）。

    返回结构与 import_project_spec 一致，额外 read_only_copy=True /
    source_locked；project 保留用户原始路径（provenance 不指向副本）。
    """
    src = Path(project_path)
    if not src.exists():
        return {"ok": False, "error": f"工程文件不存在: {project_path}"}
    ver = _resolve_aedt_version(version)
    _prune_ansysem_env(ver)

    tmp_dir = tempfile.mkdtemp(prefix="rfauto_hfss_import_")
    copy_path = Path(tmp_dir) / src.name
    box: dict[str, Any] = {}

    def _worker() -> None:
        try:
            try:
                shutil.copy2(src, copy_path)
                hfss = _open_hfss_readonly(str(copy_path), design_name, ver,
                                           non_graphical)
            except Exception as exc:
                box["error"] = f"打开 HFSS 工程副本失败: {exc}"
                return
            try:
                with contextlib.suppress(Exception):
                    hfss.autosave_disable()  # 双保险：连副本的自动保存也关掉
                box["spec"] = _collect_spec(hfss)
            finally:
                _release_hfss(hfss)
        finally:
            with contextlib.suppress(Exception):
                shutil.rmtree(tmp_dir, ignore_errors=True)

    worker = threading.Thread(target=_worker, name="hfss-import-readonly",
                              daemon=True)
    worker.start()
    worker.join(timeout_s)
    if worker.is_alive():
        return {"ok": False, "error":
                f"读取超时（>{timeout_s:.0f}s）：AEDT 会话未在期限内返回；"
                "后台线程仍会释放会话并清理临时副本"}
    if "error" in box:
        return {"ok": False, "error": box["error"]}
    spec = dict(box.get("spec") or {})
    if not spec:
        return {"ok": False, "error": "读取结果为空（会话未返回任何设计信息）"}
    spec.update({
        "ok": True,
        "project": str(src),
        "design": spec.get("design") or design_name,
        "read_only_copy": True,
        "source_locked": Path(str(project_path) + ".lock").exists(),
    })
    return spec


_NAME_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")


def detect_derived_variables(spec: dict[str, Any]) -> list[str]:
    """从变量表达式检测"派生变量"（表达式引用了同工程其他变量）。

    这是 is_dependent 漏检的兜底：pyaedt 1.4.0 对 h2=h1+hmetal*2+hsub2 这类
    表达式变量实测 is_dependent=False（B-27 真机实证），只靠它会把
    派生量当独立可调参数放进草案——写回 HFSS 时会覆盖原公式，必须剔除。
    """
    variables = spec.get("variables") or {}
    names = set(variables)
    derived: list[str] = []
    for name in sorted(names):
        expr = str((variables.get(name) or {}).get("expression", "")).strip()
        if not expr:
            continue
        tokens = set(_NAME_TOKEN_RE.findall(expr))
        if tokens & (names - {name}):
            derived.append(name)
    return derived


def draft_to_hfss_variables(recipe: dict[str, Any]) -> dict[str, str]:
    """配方草案 → HFSS 设计变量表达式（复用 ParameterSystem 同一条通道）。

    输出即 HfssAdapter.set_variables 的入参 {设计变量名: "18.1mm"}——优化器/
    sweep_backend 写 HFSS 走的就是 get_hfss_vars(name_map=hfss_var_map)，
    因此这一步是草案"能否落地"的真实渲染，而不是另造一套拼接。
    """
    from rfauto.core.parameters import ParameterSystem, ParamValue

    params: dict[str, ParamValue] = {}
    for name, info in (recipe.get("params") or {}).items():
        if not isinstance(info, dict):
            continue
        low, high = info.get("low"), info.get("high")
        bounds = None
        if isinstance(low, (int, float)) and isinstance(high, (int, float)):
            bounds = (float(low), float(high))
        params[str(name)] = ParamValue(
            name=str(name),
            value=info.get("value", 0.0),
            unit=str(info.get("unit", "mm")),
            bounds=bounds,
        )
    name_map = {str(k): str(v)
                for k, v in (recipe.get("hfss_var_map") or {}).items()}
    return ParameterSystem(params).get_hfss_vars(only_dirty=False,
                                                 name_map=name_map)


def validate_recipe_draft(recipe: dict[str, Any]) -> dict[str, Any]:
    """配方草案落地校验（B-27 渲染往返，全离线确定性）。

    四道判据：
    1. 字段完整性：model / params / setup 与频率范围合法；
    2. 参数范围一致：low <= value <= high（顺序颠倒=错误，初值越界/范围退化=警告）；
    3. 变量映射：hfss_var_map 是否覆盖每个参数（缺映射回退同名=警告）；
    4. 渲染往返：(a) ParameterSystem 通道产出的 HFSS 表达式解析回数值与 value
       一致；(b) 草案 YAML 序列化→反序列化等值（G16 格式面）。
    """
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(recipe, dict):
        return {"ok": False, "errors": ["配方草案必须是映射（键值对）"],
                "warnings": [], "hfss_variables": {}, "recipe_yaml": ""}

    for field in ("model", "params", "setup"):
        if field not in recipe:
            errors.append(f"缺少 '{field}' 字段")

    params = recipe.get("params") or {}
    var_map = recipe.get("hfss_var_map") or {}
    if not isinstance(params, dict) or not params:
        errors.append("params 为空：草案没有可落地参数")

    for name in sorted(params):
        info = params[name]
        if not isinstance(info, dict):
            errors.append(f"参数 {name} 的值必须是映射（含 value/low/high）")
            continue
        low, high, value = info.get("low"), info.get("high"), info.get("value")
        if not all(isinstance(v, (int, float)) for v in (low, high, value)):
            errors.append(f"参数 {name} 的 value/low/high 必须都是数值")
            continue
        if low > high:
            errors.append(f"参数 {name} 范围颠倒：low={low} > high={high}")
        elif low == high:
            warnings.append(f"参数 {name} 范围退化（low == high == {low}）：无可搜索空间")
        elif not (low <= value <= high):
            warnings.append(f"参数 {name} 初值 {value} 不在 [{low}, {high}] 内")
        if name not in var_map:
            warnings.append(f"参数 {name} 未在 hfss_var_map 声明，落地时按同名写入")

    setup = recipe.get("setup") or {}
    freq = setup.get("freq_range_ghz") if isinstance(setup, dict) else None
    if not (isinstance(freq, (list, tuple)) and len(freq) == 2
            and all(isinstance(f, (int, float)) for f in freq)
            and freq[0] < freq[1]):
        errors.append(
            f"setup.freq_range_ghz 非法: {freq!r}（需 [f_low, f_high], f_low < f_high）")

    # 4a. HFSS 变量表达式往返（渲染 → 解析回数值）
    hfss_vars: dict[str, str] = {}
    try:
        hfss_vars = draft_to_hfss_variables(recipe)
    except Exception as exc:
        errors.append(f"渲染 HFSS 变量失败: {exc}")
    for name in sorted(params):
        info = params[name]
        if not isinstance(info, dict):
            continue
        design_var = str(var_map.get(name, name))
        expr = hfss_vars.get(design_var)
        if expr is None:
            errors.append(f"参数 {name} 未能渲染出 HFSS 变量 {design_var}")
            continue
        back = _to_float_mm(expr)
        value = info.get("value")
        if (back is None or not isinstance(value, (int, float))
                or abs(back - float(value)) > 1e-9):
            errors.append(
                f"渲染往返失配：{design_var}={expr!r} → {back}，草案值 {value!r}")

    # 4b. YAML 格式往返（G16 格式面）
    recipe_yaml = ""
    try:
        import yaml
        recipe_yaml = yaml.safe_dump(recipe, allow_unicode=True, sort_keys=False)
        if yaml.safe_load(recipe_yaml) != recipe:
            errors.append("YAML 格式往返不等值（草案含不可序列化/有损字段）")
    except Exception as exc:
        errors.append(f"YAML 序列化失败: {exc}")

    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "hfss_variables": hfss_vars, "recipe_yaml": recipe_yaml}


def import_project_recipe(
    project_path: str,
    design_name: str | None = None,
    *,
    version: str | None = None,
    non_graphical: bool = True,
    model_name: str = "custom_hfss",
    default_range_frac: float = 0.2,
    timeout_s: float = _READONLY_TIMEOUT_S,
) -> dict[str, Any]:
    """端到端（B-27）：.aedt（只读副本）→ spec → 配方草案 → 渲染往返校验。

    Returns
    -------
    dict
        {"ok", "spec", "recipe", "validation", "excluded_derived", "error"}；
        任一步失败即 ok=False 且 error 显式说明（不返回半成品配方）。
    """
    spec = import_project_spec_readonly(project_path, design_name, version=version,
                                        non_graphical=non_graphical,
                                        timeout_s=timeout_s)
    if not spec.get("ok"):
        return {"ok": False, "error": spec.get("error", "spec 导入失败"),
                "spec": spec, "recipe": None, "validation": None}
    draft = spec_to_recipe_draft(spec, model_name=model_name,
                                 default_range_frac=default_range_frac)
    if not draft.get("ok"):
        return {"ok": False, "error": draft.get("error", "配方草案生成失败"),
                "spec": spec, "recipe": None, "validation": None}
    recipe = draft["recipe"]
    # 派生变量兜底剔除：is_dependent 实测漏检表达式变量（见 detect_derived_variables），
    # 留着它们会让优化器把公式改成常数。
    derived = set(detect_derived_variables(spec))
    excluded = sorted(name for name in recipe.get("params", {}) if name in derived)
    if excluded:
        for name in excluded:
            recipe["params"].pop(name, None)
        recipe["hfss_var_map"] = {
            k: v for k, v in recipe.get("hfss_var_map", {}).items()
            if k in recipe["params"]
        }
    validation = validate_recipe_draft(recipe)
    if excluded:
        validation["warnings"].append(
            "已剔除表达式派生变量（is_dependent 漏检、不可独立调）: "
            + ", ".join(excluded))
    return {
        "ok": bool(validation.get("ok")),
        "spec": spec,
        "recipe": recipe,
        "validation": validation,
        "excluded_derived": excluded,
        "error": None if validation.get("ok")
        else "; ".join(validation.get("errors", [])),
    }
