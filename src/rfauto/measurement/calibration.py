"""E9b 校准框架（扩展方案 §E9b）。

TRL/SOLT 校准支持：
- 使用 skrf.calibration 进行标准件校准
- 无标准件时只能"原样比对"并标注 cal=None

设计决策：
- 色散 PCB 夹具必须走 TRL/SOLT 标准件测量集
- "夹具级联求逆"只对频率无关夹具成立（v1 技术错误修正）

MS-3 修复（规格 D-1，2026-10-02）：
- apply_solt/apply_trl 的 measured 语义=各标准件实测 Network 列表
  （与 calkit 标准件同序同长）；校验失败显式 ValueError 上抛，不再被
  except 吞成 is_calibrated=False（原三连病灶：ndarray 逐频切片 /
  apply_cal() 缺参 / cal.network 属性不存在，SOLT/TRL 为静默死路）
- TRL（EightTerm 子类）补 switch_terms 透传
- legacy 单 MeasurementData 调用形态（vna_capture 链）如实返回
  is_calibrated=False + error_terms 显式原因

MS-1 扩容（规格 D-2，2026-10-02）：
- CalibrationMethod 枚举扩容至 skrf 2.1.0 实测存在的全部透传类
  （SOLT/TwelveTerm/EightTerm/TRL/NISTMultilineTRL/TUGMultilineTRL/
  UnknownThru/LRM/LRRM/SixteenTerm/MultiportSOLT）；规格清单中的
  MultilineTRL 在 skrf 2.1.0 是 TRL 的别名（``MultilineTRL is TRL``
  实测），不单设枚举成员
- :func:`apply_generic_calibration` 统一透传入口：每方法固定标准件
  顺序契约 + method_params 原样透传 skrf 构造参数
- :func:`build_calibration_diagnostics` 残差诊断报告（residual_networks/
  error_terms 四参数正反向分列/thresholds/verdict），经
  service.vna_service 落 ``calibration_diagnostics.json``
- load_calkit standards 值升 v2 dict 形态（file + offset_* 偏置线
  参数，DefinedGammaZ0 合成非理想件），旧 v1 字符串形态零改动兼容
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import skrf

from rfauto.measurement.import_data import MeasurementData


class CalibrationMethod(str, Enum):
    """校准方法（MS-1 扩容，规格 D-2；透传类以 venv 实测 skrf 2.1.0 存在性为准）。

    枚举值=小写方法名，与 calkit catalog ``method`` 键一致。规格清单中的
    ``MultilineTRL`` 在 skrf 2.1.0 是 :class:`TRL` 的别名（实测
    ``MultilineTRL is TRL``），不单设成员。
    """
    TRL = "trl"                      # Through-Reflect-Line（=skrf TRL/MultilineTRL）
    SOLT = "solt"                    # Short-Open-Load-Through
    NONE = "none"                    # 无校准（原样比对/响应式）
    TWELVE_TERM = "twelve_term"      # skrf TwelveTerm（经典 12 项）
    EIGHT_TERM = "eight_term"        # skrf EightTerm（误差盒+开关项）
    NIST_MULTILINE_TRL = "nist_multiline_trl"   # 严格序 [Thru, Reflects, Lines]
    TUG_MULTILINE_TRL = "tug_multiline_trl"     # line_meas/line_lengths/er_est
    UNKNOWN_THRU = "unknown_thru"    # 未知直通自校准（thru 必须末位）
    LRM = "lrm"                      # Line-Reflect-Match
    LRRM = "lrrm"                    # Line-Reflect-Reflect-Match
    SIXTEEN_TERM = "sixteen_term"    # 16 项（含串扰）
    MULTIPORT_SOLT = "multiport_solt"           # 多端口（≥3）SOLT 族


@dataclass
class CalibrationStandard:
    """校准标准件。"""
    name: str
    network: skrf.Network
    standard_type: str  # "through", "reflect", "line", "short", "open", "load"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.standard_type,
            "n_ports": self.network.nports,
            "freq_range_ghz": [
                float(self.network.f[0]) / 1e9,
                float(self.network.f[-1]) / 1e9,
            ],
        }


@dataclass
class CalibrationKit:
    """校准套件。"""
    name: str
    method: CalibrationMethod
    standards: list[CalibrationStandard]
    metadata: dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "method": self.method.value,
            "n_standards": len(self.standards),
            "standards": [s.to_dict() for s in self.standards],
            "metadata": self.metadata,
        }


@dataclass
class CalibrationResult:
    """校准结果。"""
    method: CalibrationMethod
    calkit: CalibrationKit | None
    calibrated_network: skrf.Network | None
    error_terms: dict[str, Any] = None
    is_calibrated: bool = False
    # dut 为 Network 列表（apply_cal_to_list 路径）时的逐个校准结果
    calibrated_networks: list[skrf.Network] | None = None
    # skrf Calibration 对象句柄（残差/误差项诊断用，故意不进 to_dict）
    skrf_cal: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method.value,
            "is_calibrated": self.is_calibrated,
            "calkit_name": self.calkit.name if self.calkit else None,
            "error_terms": self.error_terms,
        }


# 标准件固定顺序（skrf 契约：SOLT thru 必须在末位；TRL 必须 [Thru, Reflect, Line]；
# LRM/LRRM 按 skrf docstring 的 L-R-M / L-R-R-M 序；UnknownThru 与 SOLT 同序
# ——thru 末位，末位理想件只用于开方取号）
_SOLT_ORDER: tuple[str, ...] = ("short", "open", "load", "through")
_TRL_ORDER: tuple[str, ...] = ("through", "reflect", "line")
_LRM_ORDER: tuple[str, ...] = ("line", "reflect", "match")
_LRRM_ORDER: tuple[str, ...] = ("line", "reflect", "reflect2", "match")
# 反射件类型（理想定义允许 1-port 文件，构建时归一为双端口）；match/reflect2
# 是 LRM/LRRM 顺序契约中的反射件键，同享 1-port 理想定义归一
_REFLECT_TYPES = frozenset(
    {"short", "open", "load", "reflect", "reflect2", "match"})


def _two_port_same_reflect(net: skrf.Network) -> skrf.Network:
    """1-port 反射件理想定义 → 双端口同反射 2-port。

    skrf SOLT/TRL 契约要求反射件可读 s11/s22（TwelveTerm.run 双端口
    逐件建 OnePort）；diag(Γ,Γ) 与 skrf ``media.short(nports=2)`` 的双端口
    同反射语义一致，是 1-port 理想定义的唯一规范双端口表示。只用于
    ideals（定义面）；measured（实测面）不归一——实测必须双端口，
    否则 skrf 显式报错（不替用户造数据）。
    """
    s = np.zeros((len(net.f), 2, 2), dtype=complex)
    s[:, 0, 0] = net.s[:, 0, 0]
    s[:, 1, 1] = net.s[:, 0, 0]
    # S-1 C-04 2026-10-04：复 z0 显式校验——旧实现 float(net.z0[0][0])
    # 对复 dtype 会以 TypeError/静默截断形态丢虚部，理想定义归一面不消费
    # 复参考阻抗；|imag|>1e-9 容差显式 ValueError（带实测值回显），容差内
    # 按实数舍入残差处理、显式取实部。
    z0_raw = complex(np.asarray(net.z0)[0, 0])
    if abs(z0_raw.imag) > 1e-9:
        raise ValueError(
            f"反射件 {net.name!r} 的 z0 为复数（实测 {z0_raw!r}，"
            f"|imag|={abs(z0_raw.imag):.3e} > 1e-9）——双端口同反射理想"
            "归一不消费复参考阻抗，请先 renormalize 到实 z0")
    return skrf.Network(frequency=net.frequency, s=s, z0=z0_raw.real,
                        name=net.name)


def _normalize_measured_input(measured: Any) -> list[skrf.Network]:
    """measured 入参归一（MS-3 语义，规格 D-1；MS-1 透传面共用）。

    单 Network 包成 [network]；MeasurementData 按其 ``.network`` 归一
    （legacy DUT 形态不含标准件实测数据，数量校验会显式报错）；序列转列表。
    """
    if isinstance(measured, skrf.Network):
        return [measured]
    if isinstance(measured, MeasurementData):
        return [measured.network]
    return list(measured)


def _validate_measured_against_ideals(
    measured_list: list[skrf.Network],
    ideals: list[skrf.Network],
    order: tuple[str, ...],
) -> None:
    """measured 列表 vs ideals 的类型/数量/频率显式校验（失败 ValueError 上抛）。"""
    if not measured_list:
        raise ValueError("measured 为空: 请提供各标准件实测 Network 列表")
    for i, m in enumerate(measured_list):
        if not isinstance(m, skrf.Network):
            raise ValueError(
                f"measured[{i}] 不是 skrf.Network（got {type(m).__name__}）: "
                "measured 语义=各标准件实测 Network 列表（与 calkit 标准件"
                f"同序同长，顺序 {list(order)}）")
    if len(measured_list) != len(ideals):
        raise ValueError(
            f"measured 长度与标准件数不等: {len(measured_list)} != "
            f"{len(ideals)}（measured 应为各标准件实测 Network 列表，"
            f"顺序 {list(order)}）")
    for i, (m, ideal) in enumerate(zip(measured_list, ideals, strict=True)):
        if m.frequency != ideal.frequency:
            raise ValueError(
                f"measured[{i}] 与标准件 {order[i]} 频率不齐: "
                f"{float(m.f[0]):g}-{float(m.f[-1]):g} GHz/{len(m.f)} 点 vs "
                f"{float(ideal.f[0]):g}-{float(ideal.f[-1]):g} GHz/"
                f"{len(ideal.f)} 点")


def _calkit_standards_by_type(calkit: CalibrationKit) -> dict[str, skrf.Network]:
    """calkit 标准件键 → Network（保持声明序，重复键后写覆盖）。"""
    return {s.standard_type: s.network for s in calkit.standards}


def _ideals_for_order(by_type: dict[str, skrf.Network],
                      order: tuple[str, ...]) -> list[skrf.Network]:
    """按顺序契约取标准件理想定义（1-port 反射件归一双端口）。"""
    ideals: list[skrf.Network] = []
    for std_type in order:
        if std_type not in by_type:
            raise ValueError(f"缺少校准标准件: {std_type}")
        net = by_type[std_type]
        if std_type in _REFLECT_TYPES and net.nports == 1:
            net = _two_port_same_reflect(net)
        ideals.append(net)
    return ideals


def _multiline_line_keys(by_type: dict[str, skrf.Network]) -> tuple[str, ...]:
    """多线方法的 line 标准件键序（"line" 在前，其余 line2/line3… 按序号）。"""
    keys = [k for k in by_type
            if k == "line" or (k.startswith("line") and k[4:].isdigit())]
    if not keys:
        raise ValueError("多线 TRL 方法至少需要一个 line 标准件"
                         "（line/line2/…）")
    keys.sort(key=lambda k: (k != "line", int(k[4:]) if k != "line" else 0))
    return tuple(keys)


def _order_for_method(method: CalibrationMethod,
                      by_type: dict[str, skrf.Network]) -> tuple[str, ...]:
    """方法 → 标准件顺序契约（skrf 严格序，规格 D-2 参数面）。

    - NISTMultilineTRL 严格序 [Thru, Reflects, Lines]（reflect 必需，
      Grefls 与之一一对应；skrf docstring 契约）
    - TUGMultilineTRL 首条线=Thru（line_lengths[0]=0），reflect 可选
      （缺省只保证 S21/S12 正确，skrf docstring 口径）
    - SixteenTerm/MultiportSOLT 无固定契约，按 calkit 声明序对齐
    """
    if method in (CalibrationMethod.SOLT, CalibrationMethod.TWELVE_TERM,
                  CalibrationMethod.UNKNOWN_THRU):
        return _SOLT_ORDER
    if method in (CalibrationMethod.TRL, CalibrationMethod.EIGHT_TERM):
        return _TRL_ORDER
    if method is CalibrationMethod.LRM:
        return _LRM_ORDER
    if method is CalibrationMethod.LRRM:
        return _LRRM_ORDER
    if method is CalibrationMethod.NIST_MULTILINE_TRL:
        if "through" not in by_type:
            raise ValueError("NISTMultilineTRL 需要 through 标准件"
                             "（严格序 [Thru, Reflects, Lines]）")
        if "reflect" not in by_type:
            raise ValueError("NISTMultilineTRL 需要 reflect 标准件"
                             "（严格序 [Thru, Reflects, Lines]，Grefls "
                             "与 Reflects 一一对应）")
        return ("through", "reflect", *_multiline_line_keys(by_type))
    if method is CalibrationMethod.TUG_MULTILINE_TRL:
        if "through" not in by_type:
            raise ValueError("TUGMultilineTRL 需要 through 标准件"
                             "（首条线=Thru，line_lengths[0]=0）")
        return ("through", *_multiline_line_keys(by_type))
    return tuple(by_type)


def _validate_standard_lists(
    measured: Any,
    calkit: CalibrationKit,
    order: tuple[str, ...],
) -> tuple[list[skrf.Network], list[skrf.Network]]:
    """标准件实测入参归一与显式校验（MS-3 修复，规格 D-1）。

    归一（向后兼容，docstring 同款语义）：单 Network 包成 [network]；
    MeasurementData 按其 ``.network`` 归一（legacy DUT 形态不含标准件实测
    数据，数量校验会显式报错）。

    校验失败一律 ValueError 上抛，不再被 except 吞成 is_calibrated=False。

    Returns:
        (measured 列表, 与之同序同长的 ideals 列表)
    """
    measured_list = _normalize_measured_input(measured)
    by_type = _calkit_standards_by_type(calkit)
    ideals = _ideals_for_order(by_type, order)
    _validate_measured_against_ideals(measured_list, ideals, order)
    return measured_list, ideals


def _normalize_dut(
    dut: skrf.Network | MeasurementData | Sequence[skrf.Network] | None,
) -> skrf.Network | list[skrf.Network] | None:
    """dut 入参归一：None / 单 Network（MeasurementData 容器取 .network）/ 列表。"""
    if dut is None:
        return None
    if isinstance(dut, MeasurementData):
        return dut.network
    if isinstance(dut, skrf.Network):
        return dut
    return list(dut)


def _finalize_result(
    method: CalibrationMethod,
    calkit: CalibrationKit,
    cal: Any,
    dut: skrf.Network | MeasurementData | Sequence[skrf.Network] | None,
) -> CalibrationResult:
    """运行校准并按 dut 形态应用（apply_cal / apply_cal_to_list）。"""
    cal.run()
    cal_dut = _normalize_dut(dut)
    calibrated: skrf.Network | None = None
    calibrated_list: list[skrf.Network] | None = None
    if cal_dut is None:
        pass
    elif isinstance(cal_dut, skrf.Network):
        calibrated = cal.apply_cal(cal_dut)
    else:
        calibrated_list = cal.apply_cal_to_list(cal_dut)

    switch_terms = getattr(cal, "switch_terms", None)
    # MultiportSOLT（MultiportCal 族）无 nstandards/frequency 属性——
    # 摘要字段如实缺省（观测性 best-effort，#105：不得阻塞真机求解面）
    nstandards = getattr(cal, "nstandards", None)
    error_terms: dict[str, Any] = {"skrf_family": getattr(cal, "family", None)}
    if nstandards is not None:
        error_terms["n_standards"] = int(nstandards)
    frequency = getattr(cal, "frequency", None)
    if frequency is not None:
        error_terms["frequency_points"] = len(frequency)
    error_terms["switch_terms"] = None if switch_terms is None \
        else bool(switch_terms)
    return CalibrationResult(
        method=method, calkit=calkit,
        calibrated_network=calibrated,
        calibrated_networks=calibrated_list,
        error_terms=error_terms,
        is_calibrated=True,
        skrf_cal=cal,
    )


def _legacy_uncalibrated(
    method: CalibrationMethod,
    calkit: CalibrationKit,
    measured: MeasurementData,
) -> CalibrationResult:
    """legacy DUT-only 形态的如实未校准结果（规格 D-1：不再吞异常）。

    vna_capture 的 apply_cal_kit/replay 链只传单个 DUT MeasurementData，
    该形态不含标准件实测数据、无法建立 SOLT/TRL 校准——如实返回
    is_calibrated=False 并在 error_terms 写明原因（原实现是把 skrf 异常
    吞掉后返回同一个假"未校准"）。
    """
    return CalibrationResult(
        method=method, calkit=calkit,
        calibrated_network=measured.network,
        error_terms={"error": (
            "legacy 调用形态（measured=单个 DUT MeasurementData）不含各"
            "标准件实测数据，无法建立 SOLT/TRL 校准；请传 measured=[各"
            "标准件实测 Network 列表]（与 calkit 标准件同序同长）并给 "
            "dut=待校准网络")},
        is_calibrated=False,
    )


def apply_solt_calibration(
    measured: Sequence[skrf.Network] | skrf.Network | MeasurementData,
    calkit: CalibrationKit,
    dut: skrf.Network | MeasurementData | Sequence[skrf.Network] | None = None,
) -> CalibrationResult:
    """应用 SOLT 校准（MS-3 修复，规格 D-1）。

    Args:
        measured: **各标准件的实测** Network 列表，与 calkit 标准件同序
            同长，固定顺序 [short, open, load, through]（skrf 契约：thru
            必须末位）。反射件必须双端口实测（skrf SOLT 对 1-port 实测
            显式报错；calkit 中 1-port 反射件**理想定义**由本函数归一为
            双端口同反射，见 _two_port_same_reflect）。向后兼容归一：传
            单个 Network 时包成 [network] 处理；传 MeasurementData 按
            其 .network 归一——两者数量不足时由显式校验报 ValueError。
        calkit: 校准套件（必须包含 Short/Open/Load/Through 标准件）
        dut: 待校准 DUT（可选）。单个 Network（或 MeasurementData 容器）
            走 skrf ``apply_cal(dut)``；Network 列表走
            ``apply_cal_to_list()``（结果落 ``calibrated_networks``）。
            None 时只建立校准（误差盒），不校准任何 DUT。

    Returns:
        CalibrationResult。is_calibrated=True 表示校准建立成功；
        ``skrf_cal`` 字段携带 skrf Calibration 对象（residual_ntwks/coefs
        诊断入口）；全部校验失败以 ValueError 上抛，不再被 except 吞成
        is_calibrated=False。

    Raises:
        ValueError: measured 数量与标准件不等 / 频率不齐 / 元素类型非法 /
            缺标准件 / 方法不匹配。
    """
    if calkit.method != CalibrationMethod.SOLT:
        raise ValueError(f"校准套件方法不匹配: {calkit.method.value} != solt")

    measured_list, ideals = _validate_standard_lists(measured, calkit, _SOLT_ORDER)
    cal = skrf.calibration.SOLT(ideals=ideals, measured=measured_list, n_thrus=1)
    return _finalize_result(CalibrationMethod.SOLT, calkit, cal, dut)


def apply_trl_calibration(
    measured: Sequence[skrf.Network] | skrf.Network | MeasurementData,
    calkit: CalibrationKit,
    dut: skrf.Network | MeasurementData | Sequence[skrf.Network] | None = None,
    switch_terms: tuple[skrf.Network, skrf.Network] | None = None,
) -> CalibrationResult:
    """应用 TRL 校准（MS-3 修复，规格 D-1）。

    Args:
        measured: 各标准件实测 Network 列表，固定顺序
            [through, reflect, line]（skrf TRL 契约，顺序严格）。
            向后兼容归一同 apply_solt_calibration。
        calkit: 校准套件（必须包含 Through/Reflect/Line 标准件）
        dut: 待校准 DUT（可选），语义同 apply_solt_calibration。
        switch_terms: (forward, reverse) 两个 1-port 开关项实测。TRL 是
            EightTerm 子类，开关项透传给 skrf（规格 D-1）；None 时 skrf
            假定理想开关并发 UserWarning。

    Returns:
        CalibrationResult，语义同 apply_solt_calibration。

    Raises:
        ValueError: measured 数量与标准件不等 / 频率不齐 / 元素类型非法 /
            缺标准件 / 方法不匹配。
    """
    if calkit.method != CalibrationMethod.TRL:
        raise ValueError(f"校准套件方法不匹配: {calkit.method.value} != trl")

    measured_list, ideals = _validate_standard_lists(measured, calkit, _TRL_ORDER)
    cal = skrf.calibration.TRL(
        ideals=ideals, measured=measured_list, switch_terms=switch_terms)
    return _finalize_result(CalibrationMethod.TRL, calkit, cal, dut)


# ─── MS-1 透传扩容（规格 D-2）：统一入口 + method_params 原样透传 ─────────────


def _resolve_multiport_method(method_arg: Any) -> Any:
    """MultiportSOLT 的 ``method`` 参数归一：字符串按两端口方法表查，类直通。"""
    import skrf.calibration as _cal

    if isinstance(method_arg, str):
        key = method_arg.lower()
        mapping = {
            "solt": _cal.SOLT, "twelve_term": _cal.TwelveTerm,
            "eight_term": _cal.EightTerm, "unknown_thru": _cal.UnknownThru,
        }
        if key not in mapping:
            raise ValueError(
                f"MultiportSOLT 不支持两端口子方法 {method_arg!r}，"
                f"可选: {sorted(mapping)}")
        return mapping[key]
    return method_arg


def _build_skrf_cal(
    method: CalibrationMethod,
    calkit: CalibrationKit,
    measured_list: list[skrf.Network],
    ideals: list[skrf.Network],
    switch_terms: tuple[skrf.Network, skrf.Network] | None,
    method_params: dict[str, Any],
) -> Any:
    """按方法实例化 skrf 校准对象（method_params 原样透传构造参数）。

    参数面（规格 D-2，skrf 2.1.0 实测签名）：
    - NISTMultilineTRL(measured, Grefls, l, er_est, z0_ref, …)：严格序
      [Thru, Reflects, Lines]；Grefls/l 为必需方法参数
    - TUGMultilineTRL(line_meas, line_lengths, er_est, reflect_meas, …)：
      首条线=Thru；line_lengths 为必需方法参数；reflect_meas 缺省取
      calkit reflect 标准件（实测链路请用 method_params 显式传实测）
    - LRM/LRRM/UnknownThru/SixteenTerm/EightTerm/TRL：switch_terms 透传
      （EightTerm 族），其余参数经 method_params
    """
    cal_mod = skrf.calibration
    mp = dict(method_params or {})
    if method is CalibrationMethod.SOLT:
        return cal_mod.SOLT(ideals=ideals, measured=measured_list,
                            n_thrus=mp.pop("n_thrus", 1), **mp)
    if method is CalibrationMethod.TWELVE_TERM:
        return cal_mod.TwelveTerm(measured=measured_list, ideals=ideals, **mp)
    if method is CalibrationMethod.TRL:
        return cal_mod.TRL(ideals=ideals, measured=measured_list,
                           switch_terms=switch_terms, **mp)
    if method is CalibrationMethod.EIGHT_TERM:
        return cal_mod.EightTerm(measured=measured_list, ideals=ideals,
                                 switch_terms=switch_terms, **mp)
    if method is CalibrationMethod.NIST_MULTILINE_TRL:
        for req in ("Grefls", "l"):
            if req not in mp:
                raise ValueError(
                    f"NISTMultilineTRL 缺少必需方法参数 {req}"
                    "（Grefls=反射件估计反射系数，l=Thru+各线长度 m，"
                    "与严格序 [Thru, Reflects, Lines] 对应）")
        grefls = mp["Grefls"]
        n_reflects = len(grefls) if isinstance(grefls, (list, tuple)) else 1
        expected = 1 + n_reflects + (len(mp["l"]) - 1)
        if len(measured_list) != expected:
            raise ValueError(
                f"NISTMultilineTRL 标准件数与参数面不齐: len(measured)="
                f"{len(measured_list)}，按 Grefls({n_reflects})+l("
                f"{len(mp['l'])}) 期望 {expected}（[Thru, Reflects, Lines]）")
        return cal_mod.NISTMultilineTRL(measured=measured_list,
                                        switch_terms=switch_terms, **mp)
    if method is CalibrationMethod.TUG_MULTILINE_TRL:
        if "line_lengths" not in mp:
            raise ValueError(
                "TUGMultilineTRL 缺少必需方法参数 line_lengths"
                "（与 line_meas 同序、单位 m，首条线=Thru 时首项为 0）")
        if len(mp["line_lengths"]) != len(measured_list):
            raise ValueError(
                f"TUGMultilineTRL line_lengths 与实测线数不等: "
                f"{len(mp['line_lengths'])} != {len(measured_list)}")
        if mp.get("reflect_meas") is None:
            by_type = _calkit_standards_by_type(calkit)
            if "reflect" in by_type:
                rnet = by_type["reflect"]
                mp["reflect_meas"] = (_two_port_same_reflect(rnet)
                                      if rnet.nports == 1 else rnet)
        if mp.get("reflect_meas") is not None \
                and "reflect_est" not in mp:
            raise ValueError(
                "TUGMultilineTRL 给定 reflect_meas 时需要方法参数 "
                "reflect_est（反射件反射系数估计，如 -1=短路）")
        return cal_mod.TUGMultilineTRL(line_meas=measured_list,
                                       switch_terms=switch_terms, **mp)
    if method is CalibrationMethod.UNKNOWN_THRU:
        return cal_mod.UnknownThru(measured=measured_list, ideals=ideals,
                                   switch_terms=switch_terms, **mp)
    if method is CalibrationMethod.LRM:
        return cal_mod.LRM(measured=measured_list, ideals=ideals,
                           switch_terms=switch_terms, **mp)
    if method is CalibrationMethod.LRRM:
        return cal_mod.LRRM(measured=measured_list, ideals=ideals,
                            switch_terms=switch_terms, **mp)
    if method is CalibrationMethod.SIXTEEN_TERM:
        return cal_mod.SixteenTerm(measured=measured_list, ideals=ideals,
                                   switch_terms=switch_terms, **mp)
    if method is CalibrationMethod.MULTIPORT_SOLT:
        method_arg = _resolve_multiport_method(mp.pop("method", "solt"))
        return cal_mod.MultiportSOLT(method_arg, measured_list, ideals, **mp)
    raise ValueError(f"不支持的校准方法: {method}")


def apply_generic_calibration(
    measured: Sequence[skrf.Network] | skrf.Network | MeasurementData,
    calkit: CalibrationKit,
    dut: skrf.Network | MeasurementData | Sequence[skrf.Network] | None = None,
    *,
    switch_terms: tuple[skrf.Network, skrf.Network] | None = None,
    method_params: dict[str, Any] | None = None,
    ideals: Sequence[skrf.Network] | None = None,
) -> CalibrationResult:
    """通用透传校准入口（MS-1 扩容，规格 D-2）。

    按 ``calkit.method`` 选择 skrf 透传类（枚举成员即 skrf 类别名，见
    :class:`CalibrationMethod` docstring 的实测存在性表），
    ``method_params`` 原样透传 skrf 构造参数。

    Args:
        measured: 各标准件实测 Network 列表，与方法顺序契约同序同长
            （SOLT 族 [short,open,load,through]、TRL/EightTerm
            [through,reflect,line]、LRM [line,reflect,match]、LRRM
            [line,reflect,reflect2,match]、NIST [thru,reflect,lines…]、
            TUG [thru,lines…]、SixteenTerm/MultiportSOLT 按 calkit
            声明序）。向后兼容归一同 apply_solt_calibration。
        calkit: 校准套件（method 不得为 NONE）。
        dut: 待校准 DUT（可选），语义同 apply_solt_calibration。
        switch_terms: (forward, reverse) 开关项（EightTerm 族透传；
            NIST/TUG/TRL/LRM/LRRM/UnknownThru/SixteenTerm 均 skrf
            switch_terms 口径。MultiportSOLT 的开关项是 N 端口列表，
            请经 method_params["switch_terms"] 传入）。
        method_params: skrf 构造参数原样透传（NIST Grefls/l/er_est/
            z0_ref、TUG line_lengths/er_est/reflect_meas、LRRM z0/
            match_fit、SOLT n_thrus、MultiportSOLT method/isolation/
            switch_terms 等）。
        ideals: 显式理想件列表（可选）。给定时不经 calkit 顺序契约，
            按原序与 measured 对齐（专家路径；缺省从 calkit 标准件按
            方法顺序契约构建）。

    Returns:
        CalibrationResult，语义同 apply_solt_calibration。

    Raises:
        ValueError: 方法不支持 / 缺标准件 / 数量频率不齐 / 必需方法
            参数缺失 / 参数面与标准件数不齐。
    """
    if calkit.method is CalibrationMethod.NONE:
        raise ValueError("apply_generic_calibration 不支持 NONE 方法"
                         "（响应式归一走 apply_response_calibration）")
    mp = dict(method_params or {})
    if ideals is not None:
        measured_list = _normalize_measured_input(measured)
        ideals_list = list(ideals)
        order_hint = tuple(range(len(ideals_list)))
        _validate_measured_against_ideals(measured_list, ideals_list, order_hint)
    else:
        by_type = _calkit_standards_by_type(calkit)
        order = _order_for_method(calkit.method, by_type)
        measured_list, ideals_list = _validate_standard_lists(
            measured, calkit, order)
    cal = _build_skrf_cal(calkit.method, calkit, measured_list, ideals_list,
                          switch_terms, mp)
    return _finalize_result(calkit.method, calkit, cal, dut)


# ─── MS-1 残差诊断（规格 D-2）：residuals + 四参数误差项 + verdict ────────────

#: 残差门限（dB）：全部标准件残差曲线的最大值不得超过
DEFAULT_RESIDUAL_MAX_DB = -40.0
#: 跟踪纹波门限（dB）：tracking 曲线带内峰峰值的上限
DEFAULT_TRACKING_RIPPLE_DB = 1.0
#: dB 曲线地板（JSON 安全；|系数|→0 时 20log10 发散，钳位到该地板）
_DB_FLOOR_DB = -300.0
_DB_FLOOR_LINEAR = 10.0 ** (_DB_FLOOR_DB / 20.0)

#: 四参数报告键 → coefs_12term 正/反向键（规格 D-2 schema）
_ERROR_TERM_PARAMS: tuple[tuple[str, str, str], ...] = (
    ("directivity_db", "forward directivity", "reverse directivity"),
    ("source_match_db", "forward source match", "reverse source match"),
    ("load_match_db", "forward load match", "reverse load match"),
    ("tracking_db", "forward reflection tracking", "reverse reflection tracking"),
)
#: 12 项模型独有的透射跟踪（附加报告键；8 项模型经 skrf 转换同样可得）
_TRANSMISSION_TRACKING_PARAM = ("transmission_tracking_db",
                                "forward transmission tracking",
                                "reverse transmission tracking")


def _db_curve(values: Any) -> list[float]:
    """复数序列 → 20log10 幅度 dB 曲线（钳位 _DB_FLOOR_DB，JSON 安全）。"""
    mag = np.abs(np.asarray(values, dtype=complex))
    db = 20.0 * np.log10(np.maximum(mag, _DB_FLOOR_LINEAR))
    return [float(x) for x in db]


def build_calibration_diagnostics(
    result: CalibrationResult,
    *,
    residual_max_db: float = DEFAULT_RESIDUAL_MAX_DB,
    tracking_ripple_db: float = DEFAULT_TRACKING_RIPPLE_DB,
) -> dict[str, Any]:
    """校准残差诊断报告（规格 D-2 schema，纯函数 JSON 可序列化）。

    Schema::

        {ok, method, freq_ghz,
         residual_networks: [{standard, db_curve}],     # 各标准件残差 dB 曲线
         residual_semantics: self_consistency|correction_vs_measured,
         error_terms: {                                  # 四参数正反向分列
           directivity_db/source_match_db/load_match_db/tracking_db:
             {forward: [...], reverse: [...]},
           transmission_tracking_db: {forward, reverse}  # 12 项模型附加键
         },
         error_terms_available, error_terms_reason?,
         skrf_error_estimates: {biased_db, unbiased_db, total_db, available},
         thresholds: {residual_max_db, tracking_ripple_db, db_floor_db},
         verdict: {status, residual_max_observed_db, residual_pass,
                   tracking_ripple_observed_db, tracking_pass, failures}}

    口径说明：
    - db_curve = 20log10|系数/残差|；残差取逐频 S 矩阵最大元素幅度；
      |系数|=0（理想恒等校准）按地板 _DB_FLOOR_DB 钳位（JSON 禁 ±inf）。
    - residual_semantics：多数方法残差=「校准后标准件 vs 理想定义」自洽
      残差（residual 门判据）；NIST/TUG 多线 TRL 在 skrf 内部
      ideals:=measured，残差=修正量（correction_vs_measured）——该语义下
      residual 门如实不判（residual_pass=None），曲线仅作参考。
    - 四参数=skrf ``coefs_12term`` 各系数各自组单系数 dB 曲线（8 项模型
      经 skrf convert_8term_2_12term 同源可得；8/12 项命名 skrf :145-170
      口径）。
    - skrf biased/unbiased/total_error（skrf :849/:887 口径）叠加报告；
      过定不足（每标准件单次连接）时 unbiased 恒 0（如实地板，非无误差
      证明）。
    - verdict：可用检查全过且至少一项可用 → "pass"；任一可用检查不过 →
      "fail"；全部不可用 → "unknown"（不伪造）。

    Args:
        result: :func:`apply_solt_calibration` / :func:`apply_trl_calibration`
            / :func:`apply_generic_calibration` 的返回（需携带 skrf_cal）。
        residual_max_db: 残差门限（缺省 -40 dB，规格 D-2）。
        tracking_ripple_db: 跟踪纹波门限（缺省 1.0 dB，规格 D-2）。
    """
    method = result.method.value if isinstance(result.method, CalibrationMethod) \
        else str(result.method)
    out: dict[str, Any] = {
        "ok": False,
        "method": method,
        "thresholds": {
            "residual_max_db": float(residual_max_db),
            "tracking_ripple_db": float(tracking_ripple_db),
            "db_floor_db": _DB_FLOOR_DB,
        },
    }
    cal = getattr(result, "skrf_cal", None)
    if cal is None or not result.is_calibrated:
        out["reason"] = "skrf_cal 不可用（未建立校准或 legacy 形态）"
        return out

    try:
        out["freq_ghz"] = [float(x) / 1e9 for x in np.asarray(cal.frequency.f)]
    except Exception as exc:  # 观测性 best-effort（#105）：缺频率轴不阻塞残差
        out["freq_ghz"] = []
        out["freq_error"] = str(exc)

    # ① 各标准件残差 dB 曲线
    # 残差语义守卫：NIST/TUG 多线 TRL 在 skrf 内部 ideals:=measured
    # （skrf calibration.py NISTMultilineTRL.run `ideals = measured`），
    # 此时 residual_ntwks=「校准对实测的修正量」而非自洽残差——如实改标
    # 语义并退出 residual 门判（不伪造 pass/fail），verdict 只看其余检查。
    residual_networks: list[dict[str, Any]] = []
    residual_error = ""
    residual_self_consistent = True
    try:
        residual_self_consistent = not all(
            np.array_equal(np.asarray(i.s), np.asarray(m.s))
            for i, m in zip(cal.ideals, cal.measured, strict=True))
    except Exception:
        residual_self_consistent = False
    try:
        ideal_names = [s.name or f"standard_{i}"
                       for i, s in enumerate(cal.ideals)]
        for i, rnet in enumerate(cal.residual_ntwks):
            mag = np.max(np.abs(np.asarray(rnet.s)), axis=(1, 2))
            residual_networks.append({
                "standard": str(ideal_names[i]) if i < len(ideal_names)
                else f"standard_{i}",
                "db_curve": _db_curve(mag),
            })
    except Exception as exc:
        residual_error = f"残差网络不可用: {exc}"
    out["residual_networks"] = residual_networks
    out["residual_semantics"] = ("self_consistency" if residual_self_consistent
                                 else "correction_vs_measured")
    if residual_error:
        out["residual_error"] = residual_error

    # ② 四参数误差项（正反向分列）
    error_terms: dict[str, Any] = {}
    error_reason = ""
    try:
        c12 = cal.coefs_12term
        for key, fk, rk in (*_ERROR_TERM_PARAMS, _TRANSMISSION_TRACKING_PARAM):
            try:
                error_terms[key] = {"forward": _db_curve(c12[fk]),
                                    "reverse": _db_curve(c12[rk])}
            except KeyError as exc:
                error_terms[key] = None
                error_reason = f"缺少系数 {exc}"
    except Exception as exc:
        error_terms = {}
        error_reason = f"12 项系数不可用: {exc}"
    out["error_terms"] = error_terms
    out["error_terms_available"] = bool(error_terms)
    if error_reason:
        out["error_terms_reason"] = error_reason

    # ③ skrf biased/unbiased/total_error 叠加（过定不足/无名标准件时如实降级）
    estimates: dict[str, Any] = {}
    for key, attr in (("biased_db", "biased_error"),
                      ("unbiased_db", "unbiased_error"),
                      ("total_db", "total_error")):
        try:
            net = getattr(cal, attr)
            # biased/unbiased/total 返回的 Network 其 s 已是幅度谱
            estimates[key] = _db_curve(np.asarray(net.s).flatten())
        except Exception as exc:
            estimates[key] = None
            estimates[f"{key}_reason"] = str(exc)
    estimates["available"] = any(estimates[k] is not None
                                 for k in ("biased_db", "unbiased_db", "total_db"))
    out["skrf_error_estimates"] = estimates

    # ④ verdict（判据先写后跑，规格 D-2 门限原文）
    failures: list[str] = []
    residual_max_obs = max((max(e["db_curve"]) for e in residual_networks),
                           default=None)
    residual_pass: bool | None = None
    if not residual_self_consistent:
        residual_pass = None   # 修正量语义：不判 residual 门（不伪造）
    elif residual_max_obs is not None:
        residual_pass = bool(residual_max_obs <= residual_max_db)
        if residual_pass is False:
            failures.append(
                f"残差 {residual_max_obs:.2f}dB > 门限 {residual_max_db}dB")
    tracking = error_terms.get("tracking_db")
    ripple: dict[str, float] | None = None
    tracking_pass: bool | None = None
    if tracking:
        ripple = {d: float(max(c) - min(c)) for d, c in tracking.items()}
        tracking_pass = all(v <= tracking_ripple_db for v in ripple.values())
        if tracking_pass is False:
            failures.append(
                f"跟踪纹波 {max(ripple.values()):.2f}dB > 门限 "
                f"{tracking_ripple_db}dB")
    checks = [p for p in (residual_pass, tracking_pass) if p is not None]
    if not checks:
        status = "unknown"
    elif all(checks):
        status = "pass"
    else:
        status = "fail"
    out["verdict"] = {
        "status": status,
        "residual_max_observed_db": (float(residual_max_obs)
                                     if residual_max_obs is not None else None),
        "residual_pass": residual_pass,
        "tracking_ripple_observed_db": ripple,
        "tracking_pass": tracking_pass,
        "failures": failures,
    }
    out["ok"] = status in ("pass", "fail")
    return out


def apply_calibration(
    measured: MeasurementData | skrf.Network | Sequence[skrf.Network],
    calkit: CalibrationKit | None,
    dut: skrf.Network | MeasurementData | Sequence[skrf.Network] | None = None,
    *,
    switch_terms: tuple[skrf.Network, skrf.Network] | None = None,
    method_params: dict[str, Any] | None = None,
) -> CalibrationResult:
    """应用校准（自动选择方法）。

    三种调用形态：

    - **新形态**（规格 D-1）：measured=各标准件实测 Network 列表（与
      calkit 标准件同序同长），dut=待校准网络（可选）——SOLT/TRL 走
      专用入口（MS-3 语义），其余透传方法（MS-1 扩容）走
      :func:`apply_generic_calibration`。
    - **legacy 形态**（向后兼容，vna_capture 消费）：measured=单个
      MeasurementData（DUT 测量）且未给 dut——该形态不含标准件实测数据，
      真校准方法如实返回 is_calibrated=False + error_terms 显式原因
      （不再静默吞异常）；响应式（NONE）路径行为不变。
    - **无 calkit**：返回未校准结果（原样比对）。

    Args:
        measured: 新形态=标准件实测列表；legacy=单个 DUT MeasurementData。
        calkit: 校准套件（None = 无校准）。
        dut: 待校准网络（可选，仅新形态消费）。
        switch_terms: 开关项（EightTerm 族透传，MS-1）。
        method_params: skrf 构造参数透传（MS-1，仅透传方法消费）。

    Returns:
        CalibrationResult
    """
    if calkit is None:
        return CalibrationResult(
            method=CalibrationMethod.NONE,
            calkit=None,
            calibrated_network=(measured.network if isinstance(measured, MeasurementData)
                                else measured if isinstance(measured, skrf.Network)
                                else None),
            is_calibrated=False,
        )

    if calkit.method == CalibrationMethod.SOLT:
        if isinstance(measured, MeasurementData) and dut is None:
            return _legacy_uncalibrated(CalibrationMethod.SOLT, calkit, measured)
        return apply_solt_calibration(measured, calkit, dut=dut)
    elif calkit.method == CalibrationMethod.TRL:
        if isinstance(measured, MeasurementData) and dut is None:
            return _legacy_uncalibrated(CalibrationMethod.TRL, calkit, measured)
        return apply_trl_calibration(measured, calkit, dut=dut,
                                     switch_terms=switch_terms)
    elif calkit.method == CalibrationMethod.NONE:
        return CalibrationResult(
            method=CalibrationMethod.NONE,
            calkit=calkit,
            calibrated_network=(measured.network if isinstance(measured, MeasurementData)
                                else measured if isinstance(measured, skrf.Network)
                                else None),
            is_calibrated=False,
        )
    else:
        # MS-1 扩容透传方法（twelve_term/eight_term/多线 TRL/自校准族）
        if isinstance(measured, MeasurementData) and dut is None:
            return _legacy_uncalibrated(calkit.method, calkit, measured)
        return apply_generic_calibration(measured, calkit, dut=dut,
                                         switch_terms=switch_terms,
                                         method_params=method_params)


# ─── cal kit 知识库（方向 3：按 ID 引用，不硬编码路径）───────────────────────

_DEFAULT_CALKIT_DIR = Path(__file__).resolve().parents[3] / "knowledge" / "calkits"

# catalog standards 键 → CalibrationStandard.standard_type 语义
_STANDARD_TYPE_MAP = {
    "thru": "through", "line": "line", "reflect": "reflect",
    "short": "short", "open": "open", "load": "load",
}

#: catalog v2 standards 值允许的偏置线参数键（规格 D-2 schema v2）
_OFFSET_KEYS = ("offset_delay_ps", "offset_loss_db_per_mm", "offset_z0_ohm")

#: catalog schema 版本（#106 语义：v1 缺省；v2 standards 值可升 dict 形态）
_CATALOG_SCHEMA_VERSION = 2

_LIGHT_SPEED = 299792458.0


def _parse_standard_def(value: Any, kit_id: str, key: str) -> tuple[str, dict[str, float]]:
    """standards 值归一：v1 字符串（文件名）或 v2 dict（file + offset_*）。

    Returns:
        (文件名, 偏置参数 dict)——偏置参数只保留 _OFFSET_KEYS 中的已知键。
    """
    if isinstance(value, str):
        return value, {}
    if isinstance(value, dict):
        fname = value.get("file")
        if not fname or not isinstance(fname, str):
            raise KeyError(
                f"catalog v2 标准件缺 file 键: kit={kit_id} standard={key}")
        offsets = {k: float(value[k]) for k in _OFFSET_KEYS if k in value}
        return fname, offsets
    raise KeyError(
        f"catalog 标准件值形态非法（应为文件名字符串或 v2 dict）: "
        f"kit={kit_id} standard={key}")


def _synthesize_offset_standard(net: skrf.Network,
                                offsets: dict[str, float]) -> skrf.Network:
    """理想标准件定义 + 偏置线 → 非理想物理标准件（catalog v2，规格 D-2）。

    DefinedGammaZ0 合成：偏置线为 air-equivalent 传输线（er_eff=1，
    β=ω/c，线长 ℓ=c0·τ 由 offset_delay_ps 给出），分布损耗
    α=(offset_loss_db_per_mm→dB/m)/8.686（电压 Np/m，|S21|dB=−αℓ·8.686），
    特性阻抗 offset_z0_ohm（缺省 50）。

    - 1-port 标准件：偏置线级联在终止件前（``line ** term``，输入反射
      Γ_in = Γ_term·e^(−2γℓ) 的广义形）；
    - 2-port（thru）：偏置线本身（时延/损耗即 thru 的非理想性）。
    偏置线特性阻抗≠定义面参考阻抗时先 renormalize 到参考阻抗再级联
    （无损线不改变 |Γ|——失配纹波只经 renormalize 进入 S 口径）；
    合成结果参考阻抗保持定义面原值。
    """
    tau_s = float(offsets.get("offset_delay_ps", 0.0)) * 1e-12
    loss_db_per_mm = float(offsets.get("offset_loss_db_per_mm", 0.0))
    z0_off = float(offsets.get("offset_z0_ohm", 50.0))
    length_m = _LIGHT_SPEED * tau_s
    alpha_nep = (loss_db_per_mm * 1000.0 / 8.686) if loss_db_per_mm else 0.0
    beta = 2.0 * np.pi * np.asarray(net.frequency.f) / _LIGHT_SPEED
    med = skrf.media.DefinedGammaZ0(
        frequency=net.frequency, z0=z0_off, gamma=alpha_nep + 1j * beta)
    out = med.line(d=length_m, unit="m", name=net.name)
    z_ref = complex(np.asarray(net.z0).ravel()[0])
    if z_ref != 0 and not np.isclose(z0_off, abs(z_ref)):
        out.renormalize(z_ref)
    if net.nports == 1:
        out = out ** net
    out.z0 = net.z0
    return out


def load_calkit(calkit_id: str, directory: str | Path | None = None) -> CalibrationKit:
    """按 ID 从 knowledge/calkits/catalog.yaml 加载校准套件。

    标准件 Touchstone 文件与 catalog 同目录；响应式（response）kit 只含
    thru，加载为 CalibrationMethod.NONE 语义的透传件（配合 skrf 归一化）。

    catalog schema（#106 语义：schema_version 只升不破旧档读面）：
    - v1（缺省）：``standards: {键: 文件名字符串}``——逐字节原样加载；
    - v2（``schema_version: 2``）：standards 值可升 dict
      ``{file, offset_delay_ps?, offset_loss_db_per_mm?, offset_z0_ohm?}``
      ——file 为基础定义文件，offset_* 经 DefinedGammaZ0 合成非理想
      物理件（见 :func:`_synthesize_offset_standard`）；v1 字符串形态在
      v2 档内仍合法（逐标准件独立归一）。

    Raises:
        KeyError: catalog 中无此 ID / 标准件文件缺失 / v2 值形态非法 /
            ``method`` 未识别（S-1 C-05：非枚举值且非 ``response`` 别名
            显式列合法值清单，不再静默降级 NONE）。
    """
    import yaml

    d = Path(directory) if directory else _DEFAULT_CALKIT_DIR
    catalog_path = d / "catalog.yaml"
    if not catalog_path.exists():
        raise KeyError(f"cal kit 目录不存在 catalog.yaml: {d}")
    data = yaml.safe_load(catalog_path.read_text(encoding="utf-8")) or {}
    entry = (data.get("calkits") or {}).get(calkit_id)
    if entry is None:
        raise KeyError(f"catalog 中无此校准套件: {calkit_id}")

    # S-1 C-05 2026-10-04：未识别 method 显式 KeyError（列合法值清单）——
    # 旧实现任何非枚举值（含大小写笔误 "SOLT"、废弃串）都静默降级 NONE，
    # 症状是"校准从未发生"而无迹可查。三形态合法：①枚举成员（小写）；
    # ②"response" 响应式 kit（docstring 声明的 NONE 透传别名，真实
    # catalog wl_2g5_response 即此）；③method 键缺省（v1 schema 兼容）→
    # NONE。其余一律 KeyError。
    _RESPONSE_METHOD_ALIASES = ("response",)
    valid_methods = {m.value for m in CalibrationMethod} - {CalibrationMethod.NONE.value}
    declared = entry.get("method")
    if declared is None:
        method = CalibrationMethod.NONE
    elif declared in valid_methods:
        method = CalibrationMethod(declared)
    elif str(declared).strip().lower() in _RESPONSE_METHOD_ALIASES:
        method = CalibrationMethod.NONE
    else:
        raise KeyError(
            f"校准套件 {calkit_id} 的 method 未识别: {declared!r}"
            f"（合法值: {sorted(valid_methods)}；'response'=响应式透传"
            "（NONE 语义）；缺省键=NONE）")
    schema_version = int(entry.get("schema_version", 1))
    standards = []
    offsets_audit: dict[str, dict[str, float]] = {}
    for key, value in (entry.get("standards") or {}).items():
        fname, offsets = _parse_standard_def(value, calkit_id, key)
        fpath = d / fname
        if not fpath.exists():
            raise KeyError(f"标准件文件缺失: {fname}（kit {calkit_id}）")
        net = skrf.Network(str(fpath))
        if offsets:
            net = _synthesize_offset_standard(net, offsets)
            offsets_audit[key] = offsets
        standards.append(CalibrationStandard(
            name=f"{calkit_id}.{key}", network=net,
            standard_type=_STANDARD_TYPE_MAP.get(key, key)))
    return CalibrationKit(
        name=calkit_id, method=method, standards=standards,
        metadata={"description": entry.get("description", ""),
                  "directory": str(d),
                  "schema_version": schema_version,
                  "offsets": offsets_audit})


def apply_response_calibration(
    measured: MeasurementData,
    thru_network: skrf.Network,
) -> CalibrationResult:
    """响应式（归一化）校准：measured ** thru⁻¹ 去嵌直通参考面。

    适合无标准件实测数据时的冒烟级校准；全 SOLT/TRL 语义见上方两函数。
    """
    try:
        corrected = measured.network ** thru_network.inv
        return CalibrationResult(
            method=CalibrationMethod.NONE, calkit=None,
            calibrated_network=corrected,
            error_terms={"method": "response_normalization"},
            is_calibrated=True,
        )
    except Exception as e:
        return CalibrationResult(
            method=CalibrationMethod.NONE, calkit=None,
            calibrated_network=measured.network,
            error_terms={"error": str(e)}, is_calibrated=False,
        )
