"""EMC service 面（JSON 进出，规则 4；CLI/MCP 是薄壳）。

W7 台账①态接线批 X3（2026-10-04）：承载两个零消费内核的查询面——

- **CISPR 16-1-1 检波器**（core/cispr_detector，MS-4 深审 PASS）：
  ``cispr_band_params``（Table 1 四参数表查询）+ ``cispr_detect_compute``
  （时域波形 → Peak/QP/Avg 三检波器读数，dBµV）；
- **共模辐射预算**（core/common_mode，EM-5 深审 PASS）：
  ``ground_spacing_check``（接地拓扑 λ/20 频域判据）+
  ``cm_radiated_budget_compute``（浮地-机壳耦合电容 → I_CM → Ott 辐射场
  全链预算）。

信封纪律（同 adc_budget_service/_err 模式）：入参校验错误收集进
``errors: list[str]``，内核 ValueError 同样转 ``ok=False``，绝不抛异常；
数值只在确定性内核（规则 7），本模块零物理公式、只做 list→ndarray 与
异常到 JSON 信封的翻译。
"""

from __future__ import annotations

from functools import partial
from typing import Any

import numpy as np

# F-13 批 2（W6-E）：_num 单源委托（partial 绑定 accept_str=False 保
# emc 严格 isinstance 语义；#116 旧副本删净）。
from rfauto.service._helpers import parse_num
from rfauto.service.envelope import error_envelope, ok_envelope

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）
EMC_SERVICE_SCHEMA_VERSION = "1.0"

#: 内核法源（provenance 透出）
_CISPR_PROVENANCE = {
    "kernel": "rfauto.core.cispr_detector",
    "sources": (
        "CISPR 16-1-1:2006+A1:2006 Table 1（双源互证：iTeh 镜像 PDF + "
        "Schwarzbeck 接收机总览表）；读数口径与验证锚见内核 docstring"
    ),
}

_CM_PROVENANCE = {
    "kernel": "rfauto.core.common_mode",
    "sources": (
        "Ott《EMC Engineering》2009 接地拓扑 λ/20 惯例（页码 UNVERIFIED，"
        "恒等面单测钉）+ core/emc_radiated.cm_radiated_field 辐射链复用"
    ),
}


def _err(errors: list[str]) -> dict[str, Any]:
    return error_envelope(errors)


# _num 单源委托（F-13 批 2，W6-E）：functools.partial 绑定 accept_str=False
# 保严格 isinstance 语义（数字字符串拒收，SPECS §3.2 批 2 策略参）。
# 文案统一（已声明）：数字字符串/None 的报错文案随单源（「缺失」/
# 「必须是实数」），bool 报错随单源 bool 分支（「不接受 bool…」）；
# ok=False 收敛语义逐位不变。
_num = partial(parse_num, accept_str=False)


# ── CISPR 16-1-1（core/cispr_detector）──────────────────────────────────────


def cispr_band_params(band: str) -> dict[str, Any]:
    """CISPR 16-1-1 Table 1 四参数表查询（Band A-D，双源核对）。

    成功：{"ok": True, "schema_version", "result"（band/f_min/f_max/bw6/
    充放表头时间常数/过载系数/source/definition）, "provenance"}；
    band 非法 → {"ok": False, "errors": [str]}，不抛异常。
    """
    if not isinstance(band, str):
        return _err([f"band 必须是字符串（A/B/C/D），实际 {type(band).__name__}"])
    try:
        result = dict(_cispr_band_params(band))
    except ValueError as exc:
        return _err([str(exc)])
    return ok_envelope(
        schema_version=EMC_SERVICE_SCHEMA_VERSION,
        result=result,
        provenance=dict(_CISPR_PROVENANCE),
    )


def _cispr_band_params(band: str) -> dict[str, Any]:
    """惰性 import 薄封装（模块级 import 会拖 numpy 全链进轻消费路径）。"""
    from rfauto.core.cispr_detector import band_params

    return band_params(band)  # type: ignore[no-any-return]


def cispr_detect_compute(
    samples: list[float],
    fs_hz: float,
    band: str,
    f_center_hz: float | None = None,
    unit_dbuv_ref: float | None = None,
) -> dict[str, Any]:
    """CISPR 16-1-1 Peak/QP/Avg 三检波器读数（单通道时域波形 → dBµV）。

    链路与读数口径全在内核（6 dB 带宽等效滤波 → 解析包络 → 一阶非对称
    RC 充放 → 二阶临界阻尼表头）；本函数只做 list→ndarray 与信封翻译。

    Args:
        samples: 实值时域波形（线性单位，一维，有限值；全零拒收）。
        fs_hz: 采样率 Hz（守卫 fs ≥ 4×B6 且 f_center±B6/2 ≤ fs/2）。
        band: "A"/"B"/"C"/"D"。
        f_center_hz: 接收机调谐频率（None 时取 |FFT| 峰）。
        unit_dbuv_ref: 线性读数→dBµV 偏移；None=输入为伏特（+120）。

    Returns:
        {"ok": True, "schema_version", "result"（peak/qp/avg dBµV +
        qp_settling_ok + 参数回显）, "provenance"}；入参/内核 ValueError →
        {"ok": False, "errors": [str]}，不抛异常。
    """
    from rfauto.core.cispr_detector import cispr_detect

    errors: list[str] = []
    if not isinstance(samples, list) or not samples:
        errors.append(f"samples 必须是非空数值列表，实际 {type(samples).__name__}")
    else:
        bad = [i for i, v in enumerate(samples)
               if isinstance(v, bool) or not isinstance(v, (int, float))]
        if bad:
            errors.append(
                f"samples 含非数值元素（前 3 处下标 {bad[:3]}，共 {len(bad)}）")
    fs_val = _num(fs_hz, "fs_hz", errors, positive=True)
    if not isinstance(band, str):
        errors.append(f"band 必须是字符串（A/B/C/D），实际 {type(band).__name__}")
    fc_val: float | None = None
    if f_center_hz is not None:
        fc_val = _num(f_center_hz, "f_center_hz", errors, positive=True)
    ref_val: float | None = None
    if unit_dbuv_ref is not None:
        ref_val = _num(unit_dbuv_ref, "unit_dbuv_ref", errors)
    if errors:
        return _err(errors)
    arr = np.asarray([float(v) for v in samples], dtype=float)
    try:
        result = cispr_detect(
            arr, fs_val, band,  # type: ignore[arg-type]
            f_center_hz=fc_val, unit_dbuv_ref=ref_val)
    except ValueError as exc:
        return _err([str(exc)])
    return ok_envelope(
        schema_version=EMC_SERVICE_SCHEMA_VERSION,
        result=dict(result),
        provenance=dict(_CISPR_PROVENANCE),
    )


# ── 共模辐射预算（core/common_mode）─────────────────────────────────────────


def ground_spacing_check(spacing_m: float, f_mhz: float) -> dict[str, Any]:
    """接地拓扑频域判据：间距 s 是否 < λ/20（Ott/Paul 口径，严格不等号）。

    s < λ/20 → "equipotential"（等电位）；s ≥ λ/20 → "electrically_long"
    （地结构电长化，按 CM 辐射预算路径评估）。判据全在内核。

    Returns:
        {"ok": True, "schema_version", "result"（to_dict 面：wavelength/
        lambda20/spacing_over_lambda20/critical_f_mhz/verdict/notes）,
        "provenance"}；非法入参 → {"ok": False, "errors": [str]}。
    """
    from rfauto.core.common_mode import ground_spacing_criterion

    errors: list[str] = []
    s_val = _num(spacing_m, "spacing_m", errors, positive=True)
    f_val = _num(f_mhz, "f_mhz", errors, positive=True)
    if errors:
        return _err(errors)
    try:
        result = ground_spacing_criterion(s_val, f_val).to_dict()
    except ValueError as exc:
        return _err([str(exc)])
    return ok_envelope(
        schema_version=EMC_SERVICE_SCHEMA_VERSION,
        result=result,
        provenance=dict(_CM_PROVENANCE),
    )


def cm_radiated_budget_compute(
    f_mhz: float,
    length_m: float,
    distance_m: float,
    v_cm_v: float,
    *,
    c_f: float | None = None,
    coupling_area_m2: float | None = None,
    coupling_distance_m: float | None = None,
    l_path_h: float = 0.0,
    r_path_ohm: float = 0.0,
    er: float = 1.0,
    with_ground_image: bool = True,
) -> dict[str, Any]:
    """浮地-机壳耦合电容路径的 CM 辐射预算（耦合电容 → I_CM → Ott 辐射场）。

    电容来源二选一（单一事实来源，同给 → errors）：c_f 直给，或
    coupling_area_m2 + coupling_distance_m（+er）平行板闭式估计。I_CM 喂
    core/emc_radiated.cm_radiated_field（Ott 短偶极 + 镜像 + 偶极上限 +
    限值面全链复用既有内核，不重复实现）。

    Returns:
        {"ok": True, "schema_version", "result"（floating_ground + radiated
        两段 to_dict）, "provenance"}；非法入参（含电容双给/缺一）→
        {"ok": False, "errors": [str]}，不抛异常。
    """
    from rfauto.core.common_mode import cm_radiated_via_chassis

    errors: list[str] = []
    f_val = _num(f_mhz, "f_mhz", errors, nonneg=True)
    len_val = _num(length_m, "length_m", errors, positive=True)
    dist_val = _num(distance_m, "distance_m", errors, positive=True)
    v_val = _num(v_cm_v, "v_cm_v", errors, nonneg=True)
    c_val: float | None = None
    if c_f is not None:
        c_val = _num(c_f, "c_f", errors, positive=True)
    area_val: float | None = None
    if coupling_area_m2 is not None:
        area_val = _num(coupling_area_m2, "coupling_area_m2", errors, positive=True)
    cd_val: float | None = None
    if coupling_distance_m is not None:
        cd_val = _num(coupling_distance_m, "coupling_distance_m", errors, positive=True)
    l_val = _num(l_path_h, "l_path_h", errors, nonneg=True)
    r_val = _num(r_path_ohm, "r_path_ohm", errors, nonneg=True)
    er_val = _num(er, "er", errors)
    if errors:
        return _err(errors)
    try:
        budget = cm_radiated_via_chassis(
            f_val, len_val, dist_val, v_val,  # type: ignore[arg-type]
            c_f=c_val, l_path_h=l_val, r_path_ohm=r_val,
            coupling_area_m2=area_val, coupling_distance_m=cd_val,
            er=er_val,  # type: ignore[arg-type]
            with_ground_image=with_ground_image,
        )
    except ValueError as exc:
        return _err([str(exc)])
    return ok_envelope(
        schema_version=EMC_SERVICE_SCHEMA_VERSION,
        result=budget.to_dict(),
        provenance=dict(_CM_PROVENANCE),
    )
