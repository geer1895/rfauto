"""XC-P 精度档案（specs 规格深案 §B-3，2026-10-02）。

精度声明单源 + 查询函数：kernel 级"典型偏差分档 + 有效域 + 域外行为"三要素，
供 CALC 合成入口守卫（消费点 v1 ①，preflight 第 0 门归 XC-F 另件）与能力卡
"精度域"节（消费点 v1 ②，本模块出数据面、渲染在卡面）消费。

三载体（规格载体裁决，缺一即漂移）：
1. knowledge/precision_profiles.yaml —— 机器可消费单源（schema 见 YAML 头注）；
2. 各内核模块 docstring 的「精度档案」镜像行 —— 人读面；收集器一致性测试
   （tests/unit/test_precision_profiles.py，KD-1 同款）逐条对照防漂移；
3. 本模块 —— 路径发现/schema 校验/域判查询/能力卡数据面 + kernel_id→模块
   映射（KERNEL_MODULES）。

路径发现顺序（resolve_precision_profiles_yaml_path，与 core/materials 同型）：
显式入参 > ``RFAUTO_PRECISION_PROFILES_YAML`` 环境变量（设置即信，不存在
直接 FileNotFoundError 不静默回退）> canonical（本模块 parents[3]/knowledge/，
editable 安装兜底逐级向上到盘根）。

行为语义（域外三分支，schema 字段 out_of_domain_behavior）：
- REFUSE：precision_profile 对确认域外的 point 抛 ValueError（CALC 入口守卫口径）；
- WARN：返回 dict（in_domain=False + warning 注记，调用方自知后仍可继续）；
- UNVERIFIED：返回 dict（in_domain=False + unverified 注记，如实不判不编数）。
point 缺域变量（in_domain=None 不可判）一律不抛——"无法确认域内"不得伪装成
"确认域外"，返回 dict 交调用方裁决（note 说明缺哪个变量）。

分层：core 叶子（import yaml 与同层内核模块仅经 importlib 惰性——KERNEL_MODULES
是字符串映射，加载发生在函数内，避免环 import 与重依赖）；不定义 ``__all__``
（公开 API 金快照只钉带 __all__ 模块，shield_cavity_mode 先例）。

铁律 7 合规：本模块零数值产出——典型偏差分档只从各内核 docstring/测试容差
提炼（YAML 内登记），docstring 没有的一律 UNVERIFIED；查询函数只搬运声明与
判域，不产生物理数字。
"""

from __future__ import annotations

import importlib
import os
import re
from pathlib import Path
from typing import Any

import yaml

#: 精度档案路径覆盖环境变量（设置即信；空串含纯空白视同未设置）。
PRECISION_PROFILES_ENV = "RFAUTO_PRECISION_PROFILES_YAML"

#: canonical 缺省：本模块位于 <root>/src/rfauto/core/，parents[3]=仓根。
_CANONICAL_PARENT_DEPTH = 3
_DEFAULT_RELPATH = Path("knowledge") / "precision_profiles.yaml"

#: 域外行为三分支（schema 枚举）。
OUT_OF_DOMAIN_BEHAVIORS = ("REFUSE", "WARN", "UNVERIFIED")

#: 机器可判域条件支持的关系算子。
CONDITION_OPS = (">", ">=", "<", "<=", "==")

#: direction 受控词表（防漂移：自由文本方向会碎成同义串）。
DIRECTION_VOCAB = (
    "overestimate",   # 高估（如 ridged kc 遗漏杂散电容）
    "underestimate",  # 低估（如 KJ 平行线 k 相对 NGSolve）
    "none",           # 无方向语义（代数恒等/自洽口径）
    "known_sign_only",  # 只知符号方向，幅值未定级（如蚀刻 ΔZ）
    "unknown",        # 方向未声明
    "bound_only",     # 只声明"是界"（实际可达性差于界，差距未定级）
)

#: kernel_id → 模块点路径（docstring 镜像收集器与能力卡数据面的桥；
#: YAML 键集与此映射键集双向一致由收集器测试钉死）。
KERNEL_MODULES: dict[str, str] = {
    "ridged_waveguide": "rfauto.core.ridged_waveguide",
    "etch_trapezoid": "rfauto.core.etch_trapezoid",
    "conductor_loss": "rfauto.core.conductor_loss",
    "dielectric_extract": "rfauto.core.dielectric_extract",
    "synthesis.forward_z0": "rfauto.core.synthesis",
    "coupled_microstrip": "rfauto.core.coupled_microstrip",
    "high_power": "rfauto.core.high_power",
    "bounds": "rfauto.core.bounds",
    "thermal_iteration": "rfauto.core.thermal_iteration",
    "shield_cavity_mode": "rfauto.core.shield_cavity_mode",
}

#: docstring 镜像行规范（knowledge/precision_profiles.yaml 头注同步）：唯一
#: 机器可识别形态；收集器与能力卡数据面共用此正则，禁两处各写一套。
PRECISION_MARKER_RE = re.compile(
    r"精度档案[：:]\s*knowledge/precision_profiles\.yaml"
    r"#(?P<kernel_id>[A-Za-z0-9_.\-]+)"
    r"（行为=(?P<behavior>REFUSE|WARN|UNVERIFIED)，"
    r"last_verified=(?P<date>\d{4}-\d{2}-\d{2})）"
)

#: schema 允许键（多键/缺键即 PrecisionProfileSchemaError——schema 负例锚）。
_KERNEL_REQUIRED_KEYS = (
    "quantities",
    "valid_domain",
    "typical_deviation",
    "refs",
    "out_of_domain_behavior",
    "last_verified",
)
_DOMAIN_ALLOWED_KEYS = ("point_params", "conditions", "note")
_DEVIATION_REQUIRED_KEYS = ("band", "direction", "condition", "unverified")
_DEVIATION_ALLOWED_KEYS = ("quantity", *_DEVIATION_REQUIRED_KEYS)


class PrecisionProfileSchemaError(ValueError):
    """精度档案 YAML 违反 schema（负例测试的预期异常类型）。"""


def default_precision_profiles_yaml_path() -> Path:
    """canonical 缺省路径（<root>/knowledge/precision_profiles.yaml；不查存在性）。"""
    return Path(__file__).resolve().parents[_CANONICAL_PARENT_DEPTH] / _DEFAULT_RELPATH


def resolve_precision_profiles_yaml_path(path: str | Path | None = None) -> Path:
    """显式入参 > env（设置即信）> canonical（editable 兜底逐级向上）。（纯路径，不读档）"""
    if path is not None:
        return Path(path)
    env = os.environ.get(PRECISION_PROFILES_ENV, "")
    if env.strip():
        return Path(env)
    anchor = Path(__file__).resolve()
    parents = anchor.parents
    depth = min(_CANONICAL_PARENT_DEPTH, max(len(parents) - 1, 0))
    for i in range(depth, len(parents)):
        candidate = parents[i] / _DEFAULT_RELPATH
        if candidate.is_file():
            return candidate
    return default_precision_profiles_yaml_path()


def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise PrecisionProfileSchemaError(msg)


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_kernel(kernel_id: str, spec: Any) -> dict[str, Any]:
    """单 kernel 条目 schema 校验（负例锚的判定单点）。"""
    _need(isinstance(kernel_id, str) and kernel_id != "",
          f"kernel 键须为非空 str，得到 {kernel_id!r}")
    _need(isinstance(spec, dict), f"{kernel_id}: 条目须为 mapping，得到 {type(spec).__name__}")
    keys = set(spec)
    missing = [k for k in _KERNEL_REQUIRED_KEYS if k not in keys]
    extra = sorted(keys - set(_KERNEL_REQUIRED_KEYS))
    _need(not missing, f"{kernel_id}: 缺 schema 必需键 {missing}")
    _need(not extra, f"{kernel_id}: schema 不允许多余键 {extra}")

    quantities = spec["quantities"]
    _need(isinstance(quantities, list) and quantities,
          f"{kernel_id}: quantities 须为非空 list")
    _need(all(isinstance(q, str) and q for q in quantities),
          f"{kernel_id}: quantities 元素须为非空 str")
    _need(len(set(quantities)) == len(quantities),
          f"{kernel_id}: quantities 须唯一（去重后 {sorted(set(quantities))}）")

    domain = spec["valid_domain"]
    _need(isinstance(domain, dict), f"{kernel_id}: valid_domain 须为 mapping")
    d_extra = sorted(set(domain) - set(_DOMAIN_ALLOWED_KEYS))
    _need(not d_extra, f"{kernel_id}: valid_domain 不允许键 {d_extra}")
    conditions = domain.get("conditions", [])
    _need(isinstance(conditions, list), f"{kernel_id}: conditions 须为 list")
    for i, cond in enumerate(conditions):
        _need(isinstance(cond, dict) and set(cond) == {"param", "op", "value"},
              f"{kernel_id}: conditions[{i}] 须为 {{param,op,value}} mapping")
        _need(isinstance(cond["param"], str) and cond["param"],
              f"{kernel_id}: conditions[{i}].param 须为非空 str")
        _need(cond["op"] in CONDITION_OPS,
              f"{kernel_id}: conditions[{i}].op {cond['op']!r} 不在 {CONDITION_OPS}")
        _need(_is_num(cond["value"]),
              f"{kernel_id}: conditions[{i}].value 须为数值（bool 拒收）")
    point_params = domain.get("point_params", [])
    _need(isinstance(point_params, list)
          and all(isinstance(p, str) and p for p in point_params),
          f"{kernel_id}: point_params 须为非空 str list")
    note = domain.get("note", "")
    _need(isinstance(note, str), f"{kernel_id}: note 须为 str")
    _need(bool(conditions) or bool(note),
          f"{kernel_id}: valid_domain 至少要有 conditions 或 note 之一（纯空域声明=漂移）")

    deviations = spec["typical_deviation"]
    _need(isinstance(deviations, list) and deviations,
          f"{kernel_id}: typical_deviation 须为非空 list")
    for i, dev in enumerate(deviations):
        _need(isinstance(dev, dict), f"{kernel_id}: typical_deviation[{i}] 须为 mapping")
        dkeys = set(dev)
        miss = [k for k in _DEVIATION_REQUIRED_KEYS if k not in dkeys]
        ext = sorted(dkeys - set(_DEVIATION_ALLOWED_KEYS))
        _need(not miss, f"{kernel_id}: typical_deviation[{i}] 缺键 {miss}")
        _need(not ext, f"{kernel_id}: typical_deviation[{i}] 不允许键 {ext}")
        quantity = dev["quantity"]
        _need(quantity is None or (isinstance(quantity, str) and quantity),
              f"{kernel_id}: typical_deviation[{i}].quantity 须为 null 或非空 str")
        if isinstance(quantity, str):
            _need(quantity in quantities,
                  f"{kernel_id}: typical_deviation[{i}].quantity {quantity!r} "
                  f"不在 quantities 内")
        _need(isinstance(dev["band"], str) and dev["band"],
              f"{kernel_id}: typical_deviation[{i}].band 须为非空 str")
        _need(dev["direction"] in DIRECTION_VOCAB,
              f"{kernel_id}: typical_deviation[{i}].direction {dev['direction']!r} "
              f"不在受控词表 {DIRECTION_VOCAB}")
        _need(isinstance(dev["condition"], str) and dev["condition"],
              f"{kernel_id}: typical_deviation[{i}].condition 须为非空 str")
        _need(isinstance(dev["unverified"], bool),
              f"{kernel_id}: typical_deviation[{i}].unverified 须为 bool（#364④："
              f"bool 语义字段禁真值化）")
        # 铁律 7 双向钉：band="UNVERIFIED" ⟺ unverified=true
        _need((dev["band"] == "UNVERIFIED") == dev["unverified"],
              f"{kernel_id}: typical_deviation[{i}] band='UNVERIFIED' 必须与 "
              f"unverified=true 双向一致")

    refs = spec["refs"]
    _need(isinstance(refs, list) and refs and all(isinstance(r, str) and r for r in refs),
          f"{kernel_id}: refs 须为非空 str list")

    behavior = spec["out_of_domain_behavior"]
    _need(behavior in OUT_OF_DOMAIN_BEHAVIORS,
          f"{kernel_id}: out_of_domain_behavior {behavior!r} 不在 {OUT_OF_DOMAIN_BEHAVIORS}")

    last_verified = spec["last_verified"]
    _need(isinstance(last_verified, str)
          and re.fullmatch(r"\d{4}-\d{2}-\d{2}", last_verified) is not None,
          f"{kernel_id}: last_verified 须为 YYYY-MM-DD str")
    import datetime as _dt
    try:
        _dt.date.fromisoformat(last_verified)
    except ValueError as exc:
        raise PrecisionProfileSchemaError(
            f"{kernel_id}: last_verified {last_verified!r} 非合法日期") from exc

    return {
        "quantities": list(quantities),
        "valid_domain": {
            "point_params": list(point_params),
            "conditions": [dict(c) for c in conditions],
            "note": note,
        },
        "typical_deviation": [dict(d) for d in deviations],
        "refs": list(refs),
        "out_of_domain_behavior": behavior,
        "last_verified": last_verified,
    }


def load_precision_profiles(path: str | Path | None = None) -> dict[str, Any]:
    """读档+schema 校验，返回 {schema_version, kernels: {kernel_id: 规范化条目}}。

    Args:
        path: YAML 路径覆盖（缺省走 resolve_precision_profiles_yaml_path）。

    Raises:
        FileNotFoundError: 路径不存在（env 显式路径不静默回退）。
        PrecisionProfileSchemaError: schema 违例（负例锚判定单点）。
    """
    resolved = resolve_precision_profiles_yaml_path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"precision_profiles.yaml 不存在: {resolved}")
    data = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    _need(isinstance(data, dict), "顶层须为 mapping")
    kernels = data.get("kernels")
    _need(isinstance(kernels, dict) and kernels,
          "kernels 须为非空 mapping")
    version = data.get("schema_version", 1)
    _need(isinstance(version, int) and not isinstance(version, bool) and version >= 1,
          f"schema_version 须为 >=1 整数，得到 {version!r}")
    normalized = {kid: _validate_kernel(kid, spec) for kid, spec in kernels.items()}
    return {"schema_version": version, "kernels": normalized}


def domain_ok(point: Any, valid_domain: dict[str, Any]) -> bool | None:
    """机器可判域检查（纯函数）：True 域内 / False 确认域外 / None 不可判。

    不可判=conditions 引用的 point 变量缺失或 point 非 mapping（无 conditions
    时恒 None——域只做了人读声明，未声明机器判据）。#364④：数值可达 0 的面
    禁 ``or`` 缺省惯语，缺失一律显式判。
    """
    conditions = valid_domain.get("conditions") or []
    if not conditions:
        return None
    if not isinstance(point, dict):
        return None
    for cond in conditions:
        value = point.get(cond["param"])
        if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        bound = cond["value"]
        op = cond["op"]
        if op == ">" and not value > bound:
            return False
        if op == ">=" and not value >= bound:
            return False
        if op == "<" and not value < bound:
            return False
        if op == "<=" and not value <= bound:
            return False
        if op == "==" and value != bound:
            return False
    return True


def _load_cached(path: str | Path | None, profiles: dict[str, Any] | None) -> dict[str, Any]:
    if profiles is not None:
        return profiles
    return load_precision_profiles(path)


def precision_profile(
    kernel_id: str,
    quantity: str,
    point: Any = None,
    *,
    profiles: dict[str, Any] | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """CALC 合成入口守卫的查询函数（消费点 v1 ①；本函数只搬运声明与判域，
    零数值产出——铁律 7）。

    Args:
        kernel_id: 精度档案键（如 "ridged_waveguide"、"synthesis.forward_z0"）。
        quantity: 该内核 quantities 内的量名。
        point: 域变量点（mapping，键=valid_domain.point_params）；None/缺变量
            = in_domain None（不可判，不抛）。
        profiles: 已加载档案注入（测试/批量调用免重复读档）。
        path: YAML 路径覆盖（profiles 未注入时生效）。

    Returns:
        {kernel_id, quantity, in_domain, behavior, typical_dev, unverified,
        warning, note}。behavior：域内="in_domain"；域外=档案
        out_of_domain_behavior（REFUSE 分支不走返回——直接抛 ValueError）。

    Raises:
        ValueError: 未知 kernel_id/quantity；或确认域外且 behavior=REFUSE。
    """
    data = _load_cached(path, profiles)
    kernels = data["kernels"]
    kernel_id = str(kernel_id)
    if kernel_id not in kernels:
        raise ValueError(
            f"精度档案无 kernel {kernel_id!r}（可用: {sorted(kernels)}）")
    spec = kernels[kernel_id]
    quantity = str(quantity)
    if quantity not in spec["quantities"]:
        raise ValueError(
            f"kernel {kernel_id!r} 无 quantity {quantity!r}"
            f"（可用: {spec['quantities']}）")

    status = domain_ok(point, spec["valid_domain"])
    matched = [d for d in spec["typical_deviation"]
               if d["quantity"] is None or d["quantity"] == quantity]
    behavior = spec["out_of_domain_behavior"]
    note = spec["valid_domain"]["note"]

    if status is True:
        return {
            "kernel_id": kernel_id,
            "quantity": quantity,
            "in_domain": True,
            "behavior": "in_domain",
            "typical_dev": matched,
            "unverified": all(d["unverified"] for d in matched) if matched else True,
            "warning": None,
            "note": note,
        }

    if status is False:
        if behavior == "REFUSE":
            raise ValueError(
                f"{kernel_id}.{quantity} 确认域外（point={point!r}，"
                f"域条件={spec['valid_domain']['conditions']}）——精度档案 REFUSE")
        unverified_flag = behavior == "UNVERIFIED"
        return {
            "kernel_id": kernel_id,
            "quantity": quantity,
            "in_domain": False,
            "behavior": behavior,
            "typical_dev": matched,
            "unverified": True,
            "warning": None if unverified_flag else (
                f"{kernel_id}.{quantity} 域外（point={point!r}）——典型偏差分档"
                f"不适用，调用方自知"),
            "note": note,
        }

    # status is None：缺域变量/无条件可判——不抛（不可判≠确认域外），如实交调用方。
    return {
        "kernel_id": kernel_id,
        "quantity": quantity,
        "in_domain": None,
        "behavior": behavior,
        "typical_dev": matched,
        "unverified": all(d["unverified"] for d in matched) if matched else True,
        "warning": None,
        "note": note,
    }


def docstring_marker_line(module: Any) -> dict[str, Any] | None:
    """读模块 docstring 的「精度档案」镜像行（人读面收集口径，KD-1 同款）。

    Returns:
        {kernel_id, behavior, last_verified, line} 或 None（无镜像行——
        收集器测试会把"缺行/多行/内容漂移"判红；本函数如实返回不抛）。
    """
    doc = getattr(module, "__doc__", None)
    if not doc:
        return None
    matches = list(PRECISION_MARKER_RE.finditer(doc))
    if len(matches) != 1:
        return None
    m = matches[0]
    line = next(ln.strip() for ln in doc.splitlines() if PRECISION_MARKER_RE.search(ln))
    return {
        "kernel_id": m.group("kernel_id"),
        "behavior": m.group("behavior"),
        "last_verified": m.group("date"),
        "line": line,
    }


def capability_card_precision_section(
    kernel_id: str,
    *,
    profiles: dict[str, Any] | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """能力卡「精度域」节的数据面（消费点 v1 ②；只读组装，渲染在卡面）。

    docstring 镜像读取为 best-effort（#105：观测性不得成为主路径故障点）：
    模块导入失败/无镜像行如实 ok=False，不抛。
    """
    data = _load_cached(path, profiles)
    kernels = data["kernels"]
    kernel_id = str(kernel_id)
    if kernel_id not in kernels:
        return {"ok": False, "error": f"精度档案无 kernel {kernel_id!r}",
                "available": sorted(kernels)}
    spec = kernels[kernel_id]
    mirror: dict[str, Any] = {"module": KERNEL_MODULES.get(kernel_id), "ok": False}
    dotted = KERNEL_MODULES.get(kernel_id)
    if dotted is not None:
        try:
            module = importlib.import_module(dotted)
            marker = docstring_marker_line(module)
            if marker is not None and marker["kernel_id"] == kernel_id:
                mirror = {"module": dotted, "ok": True, **marker}
        except Exception as exc:  # pragma: no cover - 导入面环境故障如实降级
            mirror = {"module": dotted, "ok": False, "error": repr(exc)}
    return {
        "ok": True,
        "section": "精度域",
        "kernel_id": kernel_id,
        "quantities": spec["quantities"],
        "valid_domain": spec["valid_domain"],
        "typical_deviation": spec["typical_deviation"],
        "refs": spec["refs"],
        "out_of_domain_behavior": spec["out_of_domain_behavior"],
        "last_verified": spec["last_verified"],
        "docstring_mirror": mirror,
    }
