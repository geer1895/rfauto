"""二端口网络矩阵换算 CALC 键（aurora_l G1，2026-10-23）。

一键：twoport_matrix_convert（S↔Z↔Y↔ABCD 全对全换算，参考阻抗 Z0
可调——微波网络分析的基本代数面；#222 triple-grep 证据：kuroda_
identity_abcd=Kuroda 恒等式 ABCD 校验（滤波器实现域，无 S/Z/Y 换算
面）、deembed_thru_metrics=THRU 去嵌指标、balanced_pair_sparams=平衡
对 S 矩阵——二端口四表示互换的独立键面全仓空白）。

物理口径（#1c/#300 出处纪律；docstring 写死）
--------------------------------------------------------
- S→Z：Z = Z0·(I+S)(I−S)^{−1}；S→Y：Y = (1/Z0)·(I−S)(I+S)^{−1}
  （1 端口极限 Z=Z0(1+Γ)/(1−Γ)、Y=(1/Z0)(1−Γ)/(1+Γ) 可单口自证——
  短路 Γ=−1 → Z=0、开路 Γ=+1 → Z→∞ 恒等）。
- ABCD→S（等 Z0 对称参考）：den=A+B/Z0+C·Z0+D，
      S11=(A+B/Z0−C·Z0−D)/den；S21=2/den；
      S12=2(AD−BC)/den；S22=(−A+B/Z0−C·Z0+D)/den
  S→ABCD 为其逆（S21≠0 前提，S21≈0 显式拒绝——|den|→∞ 奇异）。
- Z→S=(Z−Z0I)(Z+Z0I)^{−1}、Y→S=(I−Z0Y)(I+Z0Y)^{−1}（互为镜像；
  Pozar《Microwave Engineering》§4.4 网络分析阻抗/导纳/ABCD/散射
  矩阵互换表口径）。
- 精度类：精确（线性代数恒等式，无近似）；互易性 S=Sᵀ 与 det(ABCD)=1
  （互易无耗网络reciprocal/invariant 口径）作为标注字段如实输出。

锚（tests/unit/test_g1_calc_coverage_keys.py）：
λ/4 线 ABCD=[0,jZ0;j/Z0,0] → S11=S22=0、S21=S12=−j；串联 z=30+j10
ABCD=[1,z;0,1] → S11=z/(2Z0+z)、S21=2Z0/(2Z0+z)；随机互易有耗网络
S→Z→S / S→Y→S / S→ABCD→S 全往返 ≤1e-8；Π 网络（shunt 50Ω+series
50Ω）ABCD 与 Y 路径 S 逐元素同值（1e-12）。

守卫：from_type ∈ {"S","Z","Y","ABCD"}；matrix=2×2 复数矩阵（[[re,im]
×4 行主序]，元素有限）；z0_ohm>0；S→Z/Y 需 I∓S 可逆（奇异显式拒绝）；
S→ABCD 需 |S21|>1e-12；越界一律显式拒绝。

接口：纯函数零 IO；numpy 线性代数（2×2 解析逆）；复数按服务 [re,im]
嵌套列表约定；无 ``__all__``（公开 API 快照口径）。

出处：
- twoport_matrix_convert：二端口 S/Z/Y/ABCD 互换恒等式（Pozar
  Microwave Engineering §4.4 网络分析——散射/阻抗/导纳/ABCD 矩阵
  互换表，章节级转引通行形态）。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .registry import register_calculator
from .thermal import _finite

_FROM_TYPES = ("S", "Z", "Y", "ABCD")


def _parse_matrix(value: Any, tag: str) -> np.ndarray:
    """2×2 复数矩阵解析（[[re,im]×4 行主序]；有限性守卫）。"""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(
            f"{tag}: matrix 须 2×2 复数矩阵（[[re,im]×2 列]×2 行），得到 "
            f"{type(value).__name__} 长 {len(value) if isinstance(value, (list, tuple)) else '—'}")
    rows: list[list[complex]] = []
    for r_i, row in enumerate(value):
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            raise ValueError(
                f"{tag}: matrix 第 {r_i} 行须 [re,im] 对（2 元），得到 {row!r}")
        parsed_row: list[complex] = []
        for c_i, cell in enumerate(row):
            if not isinstance(cell, (list, tuple)) or len(cell) != 2:
                raise ValueError(
                    f"{tag}: matrix[{r_i}][{c_i}] 须 [re,im] 对，得到 {cell!r}")
            re_v = _finite(cell[0], f"{tag}.matrix[{r_i}][{c_i}].re")
            im_v = _finite(cell[1], f"{tag}.matrix[{r_i}][{c_i}].im")
            parsed_row.append(complex(re_v, im_v))
        rows.append(parsed_row)
    return np.array(rows, dtype=complex)


def _pack(mat: np.ndarray) -> list[list[list[float]]]:
    """复数矩阵 → [[re,im]×4] 嵌套列表（JSON 契约）。"""
    return [[[round(float(v.real), 12), round(float(v.imag), 12)]
             for v in row] for row in mat]


def _inv2(mat: np.ndarray, tag: str) -> np.ndarray:
    """2×2 解析逆（奇异显式拒绝——numpy LinAlgError 翻译成 ValueError）。"""
    det = mat[0, 0] * mat[1, 1] - mat[0, 1] * mat[1, 0]
    if abs(det) < 1e-300:
        raise ValueError(
            f"{tag}: 矩阵奇异（行列式模 {abs(det):.3e} <1e-300）——该表示"
            "在此参考阻抗下不存在，显式拒绝")
    return np.array([
        [mat[1, 1], -mat[0, 1]],
        [-mat[1, 0], mat[0, 0]],
    ], dtype=complex) / det


def s_to_z(s_mat: np.ndarray, z0: float) -> np.ndarray:
    """S→Z：Z=Z0(I+S)(I−S)^{−1}（1 端口极限短路 Γ=−1→Z=0 恒等口径）。"""
    eye = np.eye(2, dtype=complex)
    return z0 * (eye + s_mat) @ _inv2(eye - s_mat, "s_to_z")


def s_to_y(s_mat: np.ndarray, z0: float) -> np.ndarray:
    """S→Y：Y=(1/Z0)(I−S)(I+S)^{−1}（开路 Γ=+1→Y=0 恒等口径）。"""
    eye = np.eye(2, dtype=complex)
    return (eye - s_mat) @ _inv2(eye + s_mat, "s_to_y") / z0


def z_to_s(z_mat: np.ndarray, z0: float) -> np.ndarray:
    """Z→S：S=(Z−Z0I)(Z+Z0I)^{−1}。"""
    eye = np.eye(2, dtype=complex)
    return (z_mat - z0 * eye) @ _inv2(z_mat + z0 * eye, "z_to_s")


def y_to_s(y_mat: np.ndarray, z0: float) -> np.ndarray:
    """Y→S：S=(I−Z0Y)(I+Z0Y)^{−1}。"""
    eye = np.eye(2, dtype=complex)
    return (eye - z0 * y_mat) @ _inv2(eye + z0 * y_mat, "y_to_s")


def abcd_to_s(m_mat: np.ndarray, z0: float) -> np.ndarray:
    """ABCD→S（等 Z0 对称参考；S21≠0 前提）。"""
    a_m, b_m, c_m, d_m = m_mat[0, 0], m_mat[0, 1], m_mat[1, 0], m_mat[1, 1]
    den = a_m + b_m / z0 + c_m * z0 + d_m
    if abs(den) < 1e-300:
        raise ValueError(
            "abcd_to_s: A+B/Z0+C·Z0+D≈0（S21 奇异）——该 ABCD 在此参考阻抗"
            "下 S 表示不存在，显式拒绝")
    det = a_m * d_m - b_m * c_m
    return np.array([
        [(a_m + b_m / z0 - c_m * z0 - d_m) / den, 2.0 * det / den],
        [2.0 / den, (-a_m + b_m / z0 - c_m * z0 + d_m) / den],
    ], dtype=complex)


def s_to_abcd(s_mat: np.ndarray, z0: float) -> np.ndarray:
    """S→ABCD（abcd_to_s 之逆；S21≈0 显式拒绝）。"""
    if abs(s_mat[1, 0]) < 1e-12:
        raise ValueError(
            "s_to_abcd: |S21|<1e-12（ABCD 表示含 1/S21 奇异）——显式拒绝")
    inv_s21 = 1.0 / s_mat[1, 0]
    a_m = ((1.0 + s_mat[0, 0]) * (1.0 - s_mat[1, 1])
           + s_mat[0, 1] * s_mat[1, 0]) * inv_s21 / 2.0
    b_m = z0 * ((1.0 + s_mat[0, 0]) * (1.0 + s_mat[1, 1])
                - s_mat[0, 1] * s_mat[1, 0]) * inv_s21 / 2.0
    c_m = ((1.0 - s_mat[0, 0]) * (1.0 - s_mat[1, 1])
           - s_mat[0, 1] * s_mat[1, 0]) * inv_s21 / (2.0 * z0)
    d_m = ((1.0 - s_mat[0, 0]) * (1.0 + s_mat[1, 1])
           + s_mat[0, 1] * s_mat[1, 0]) * inv_s21 / 2.0
    return np.array([[a_m, b_m], [c_m, d_m]], dtype=complex)


@register_calculator(
    "twoport_matrix_convert",
    "二端口网络矩阵全对全换算（Pozar §4.4）：S/Z/Y/ABCD 任一表示（2×2 "
    "复数 [re,im] 行主序）→ 全部四种表示+互易 S=Sᵀ/det(ABCD) 标注；"
    "S→Z=Z0(I+S)(I−S)⁻¹（短路 Γ=−1→Z=0 口径）、S→Y=(I−S)(I+S)⁻¹/Z0、"
    "ABCD→S 等参考对称式（den=A+B/Z0+CZ0+D）；S21≈0 与表示奇异显式拒绝"
    "；精确线性代数无近似。Kuroda 恒等式=滤波器实现域、deembed=去嵌面"
    "不撞",
    (("matrix", "list 2×2 复数矩阵（[[[re,im],[re,im]],[[re,im],[re,im]]]"
      " 行主序）"),
     ("from_type", "str 输入表示 'S'|'Z'|'Y'|'ABCD'"),
     ("z0_ohm", "float Ω 参考阻抗（>0，缺省 50）")),
    required=("matrix", "from_type"),
)
def twoport_matrix_convert(matrix: Any, from_type: str,
                           z0_ohm: float = 50.0) -> dict[str, Any]:
    """二端口 S/Z/Y/ABCD 全对全换算（精确线性代数）。"""
    tag = "twoport_matrix_convert"
    m_mat = _parse_matrix(matrix, tag)
    ftype = str(from_type)
    if ftype not in _FROM_TYPES:
        raise ValueError(
            f"{tag}: from_type 须 {'|'.join(_FROM_TYPES)}，得到 {from_type!r}")
    z0 = _finite(z0_ohm, f"{tag}.z0_ohm")
    if z0 <= 0.0:
        raise ValueError(f"{tag}: z0_ohm 必须 >0，得到 {z0_ohm!r}")

    if ftype == "S":
        s_mat = m_mat
    elif ftype == "Z":
        s_mat = z_to_s(m_mat, z0)
    elif ftype == "Y":
        s_mat = y_to_s(m_mat, z0)
    else:  # ABCD
        s_mat = abcd_to_s(m_mat, z0)
    # 其余表示 best-effort：纯串联/并联单元的 Z/Y 矩阵天然奇异（如串联
    # 元件 2 端口开路→无定义）、S21≈0 的 ABCD 奇异——如实记 null+原因，
    # 不整体拒绝（vswr_convert 的回损 null 同款"如实"口径；主表示恒在）
    z_mat: np.ndarray | None
    y_mat: np.ndarray | None
    a_mat: np.ndarray | None
    missing: list[str] = []
    try:
        z_mat = s_to_z(s_mat, z0)
    except ValueError as exc:
        z_mat, _ = None, missing.append(f"Z:{exc}")
    try:
        y_mat = s_to_y(s_mat, z0)
    except ValueError as exc:
        y_mat, _ = None, missing.append(f"Y:{exc}")
    try:
        a_mat = s_to_abcd(s_mat, z0)
    except ValueError as exc:
        a_mat, _ = None, missing.append(f"ABCD:{exc}")

    reciprocal = bool(np.max(np.abs(s_mat - s_mat.T)) < 1e-12)
    det_abcd: list[float] | None
    det_unit: bool | None
    if a_mat is not None:
        det_c = complex(a_mat[0, 0] * a_mat[1, 1] - a_mat[0, 1] * a_mat[1, 0])
        det_abcd = [round(det_c.real, 12), round(det_c.imag, 12)]
        det_unit = bool(abs(det_c - 1.0) < 1e-9)
    else:
        det_abcd, det_unit = None, None
    return {
        "from_type": ftype,
        "z0_ohm": z0,
        "s_matrix": _pack(s_mat),
        "z_matrix": None if z_mat is None else _pack(z_mat),
        "y_matrix": None if y_mat is None else _pack(y_mat),
        "abcd_matrix": None if a_mat is None else _pack(a_mat),
        "missing_representations": missing,
        "reciprocal_sst": reciprocal,
        "det_abcd": det_abcd,
        "det_abcd_unit": det_unit,
        "note": (
            "精确线性代数（2×2 解析逆，无近似）；reciprocal_sst=|S−Sᵀ|max"
            "<1e-12 判定；det_abcd_unit=|det(ABCD)−1|<1e-9（互易无耗网络"
            "不变量，有耗互易网络 det≠1 属正常）；纯串联/并联单元的 Z/Y "
            "矩阵天然奇异（端口开路/短路退化）、S21≈0 的 ABCD 奇异——对"
            "应表示如实记 null+missing_representations 原因（vswr_convert "
            "回损 null 同款口径），主表示恒在"),
        "source": (
            "Pozar Microwave Engineering §4.4 网络分析：二端口散射/阻抗/"
            "导纳/ABCD 矩阵互换恒等式（章节级转引通行形态；1 端口极限"
            "短路/开路口径自证）"),
    }
