"""rf_matrix —— 理想传输线矩阵闭式族：分支线耦合器频响（Q-X83，aurora_q）。

动机（em_bench branchline-campaign as-recorded FAIL，Q-X55 登记面）：fake
位阶注记（aurora_r 合流笔 2026-11-10）：本模块自 calc_families/ 移入
  core/ 层——未注册 CALC 键的公式内核按 core/synthesis.py 同位阶居
  core 层（业务层 adapters/service 经 core 合规消费，规避
  calc-families-no-direct-consumption 契约；contract 棘轮只收不放不
  加白名单行）。原位阶=calc_families/rf_matrix.py（Q-X83 交付）。
adapter 的 branchline 解析模型为粗档手调包络（adapters/fake_adapter/
coupler_family._branchline_sparams，"真机校准版"：S11 系数 0.34 手调+
单包络近似，等分偏差 75.4%/S11 −8.1dB）。本模块给**理想 TL 矩阵闭式**
四端口逐频点 S 矩阵：分支线耦合器四臂全 λ/4（Pozar Microwave
Engineering §7 分支线耦合器节，奇偶模分析）——水平镜像半电路（含串联
臂全段 Z1、并联臂半桩 Z2）在偶/奇边界（对称面开路/短路）下 ABCD 级联
→ 2 端口 S（Γe/Γo/Te/To）→ 奇偶叠加合成 4×4（Pozar 奇偶叠加式章节级
转引）：
    S11=(Γe+Γo)/2  S21=(Te+To)/2  S31=(Te−To)/2  S41=(Γe−Γo)/2。
f0 处 3dB 设计退化为教科书理想值：S21=−j/√2（直通 −90°）、S31=−1/√2
（耦合 180°）、S11=S41=0，与 branchline_coupler_design（aurora_l G1，
奇偶模**节点导纳矩阵**解析合成的中心频率闭式）同构互证——两条独立推
导路径（半电路 ABCD 级联 vs 节点导纳矩阵合成）在锚测试逐元素 ≤1e-10
互证（#118 家法：独立来源解析值当裁判）。

物理口径
--------------------------------------------------------
- 端口编号（与 fake adapter/branchline_coupler_design/em_bench 一致）：
  1=输入、2=直通、3=耦合、4=隔离；串联臂 Z1（1-2、4-3）、并联臂 Z2
  （1-4、2-3）。
- 设计闭式（耦合系数 c=|S21| 直通电压系数，0<c<1）：
      Z1 = c·Z0；  Z2 = Z0·c/√(1−c²)
  3dB（c=1/√2）：Z1=Z0/√2≈35.36Ω、Z2=Z0（教科书经典值）。
- 电长度（每段显式式）：θ(f) = 2π·f·√εeff·L/c；λ/4 设计长度从设计频率
  反解 L = c/(4·f0·√εeff)——各臂用**各自线宽的 εeff**（XA-3 迭代序，
  与 core/synthesis.synthesize_branchline 同口径；35Ω 串联臂 εeff 高于
  50Ω 并联臂 → 物理臂长更短）。线宽/εeff 走 core/synthesis inverse_width
  +forward_z0（HJ 链，铁律 1c 唯一介质口径），反解越括号 fail-closed。
- 偶/奇半电路：镜像面横切两并联臂于中点——偶模边界=开路（半桩输入导纳
  Y_e=jY2·tan(θ/2)）、奇模=短路（Y_o=−jY2·cot(θ/2)）；半电路 ABCD =
  并联(Y)·TL(Z1,θ)·并联(Y)（emi_filter.abcd_parallel/abcd_cascade 级联、
  even_odd_split.transmission_line_abcd 教科书均匀线矩阵——复用既有
  工具零重实现；abcd_to_s=skrf a2s 逐位同式的伪波归一）。
- 无耗/互易/幺正由构造保证（理想 TEM 线级联，无损耗项）；色散/微带不
  连续（拐角/T 结）/损耗不在面——已知口径限制如实声明，物理实现走模板
  级 synthesize_branchline + EM。

精度类：理想精确（中心频率闭式+全频段 TL 级联；带宽内形状=TL 物理响应
非近似包络）。

守卫（fail-closed）：freq_ghz 非空正有限数组；z0_ohm/f0_ghz/h_mm/
z_ref_ohm/显式臂阻抗 >0；er ≥1（微带介质下限）；coupling_c ∈(0,1)
（缺省 3dB=1/√2）；bool 入参显式拒收（df7+⑯）；臂阻抗反解越括号
（inverse_width status=needs_calibration）显式报错。

接口：纯函数零 IO 零随机；返回 (n,4,4) complex ndarray；无 ``__all__``
（公开 API 快照口径）；不注册 CALC 键（注册序/金快照零漂移——接线消费
=fake adapter/em_bench 迁移，后续席位事项）。

出处：
- 分支线耦合器奇偶模分析与半电路 S 合成：Pozar Microwave Engineering
  §7 功分器与定向耦合器——分支线耦合器节（式 7.59 同款叠加式，章节级
  转引）；均匀线 ABCD 教科书恒等式（Pozar §4.4）。
- 各臂 λ/4 各自 εeff 口径：core/synthesis.synthesize_branchline（XA-3
  迭代序修正，2026-10-02）同源承袭。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

# 光速 mm·GHz（core/synthesis.synthesize_branchline 同源常数口径）
_C_MM_GHZ = 299.792458
_3DB_C = 1.0 / math.sqrt(2.0)


def _pos_finite(value: Any, name: str) -> float:
    """正有限实数守卫（bool 显式拒收，df7+⑯ 家法）。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 不接受 bool（缺省语义歧义），得到 {value!r}")
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须是实数，得到 {value!r}") from exc
    if not math.isfinite(v):
        raise ValueError(f"{name} 必须有限，得到 {value!r}")
    if v <= 0.0:
        raise ValueError(f"{name} 必须 >0，得到 {value!r}")
    return v


def _er_guard(er: Any) -> float:
    """介电常数守卫：实数、有限、≥1（微带介质下限；bool 显式拒收）。"""
    if isinstance(er, bool):
        raise ValueError(f"er 不接受 bool（缺省语义歧义），得到 {er!r}")
    try:
        v = float(er)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"er 必须是实数，得到 {er!r}") from exc
    if not math.isfinite(v) or v < 1.0:
        raise ValueError(f"er 必须 ≥1（微带介质下限），得到 {er!r}")
    return v


def branchline_arm_impedances(
    z0_ohm: float = 50.0,
    coupling_c: float | None = None,
) -> tuple[float, float]:
    """分支线耦合器臂阻抗设计闭式：Z1=c·Z0、Z2=Z0·c/√(1−c²)。

    Args:
        z0_ohm: 端口/馈线特性阻抗（>0，缺省 50）。
        coupling_c: 直通电压系数 |S21|（0<c<1；None=3dB 缺省 1/√2）。

    Returns:
        (series_z_ohm, shunt_z_ohm)——串联臂（1-2、4-3）与并联臂（1-4、
        2-3）特征阻抗。3dB → (Z0/√2, Z0) 教科书经典值（与
        branchline_coupler_design/synthesize_branchline 同值互证）。

    Raises:
        ValueError: z0 非正有限/bool、coupling_c 越开区间 (0,1)/bool。
    """
    z0 = _pos_finite(z0_ohm, "z0_ohm")
    if coupling_c is None:
        c_v = _3DB_C
    else:
        if isinstance(coupling_c, bool):
            raise ValueError(
                f"coupling_c 不接受 bool（缺省语义歧义），得到 {coupling_c!r}")
        c_v = _pos_finite(coupling_c, "coupling_c")
        if c_v >= 1.0:
            raise ValueError(
                f"coupling_c=|S21| 须 ∈(0,1)（c→1 并联臂→∞ 退化），"
                f"得到 {coupling_c!r}")
    z1 = c_v * z0
    z2 = z0 * c_v / math.sqrt(1.0 - c_v * c_v)
    return z1, z2


def branchline_arm_media(
    series_z_ohm: float,
    shunt_z_ohm: float,
    f0_ghz: float,
    er: float,
    h_mm: float,
) -> dict[str, float]:
    """两臂微带介质解析：目标阻抗 → HJ 反解线宽 → εeff → λ/4 物理臂长。

    XA-3 口径（synthesize_branchline 同源）：各臂 λ/4 用各自线宽的 εeff
    （inverse_width→forward_z0）；L = c/(4·f0·√εeff)（mm，f0 为 GHz）。
    反解越括号（目标阻抗超出 [Z(w_min), Z(w_max)]）fail-closed 报错
    （理想模型不做静默钳位）。

    Returns:
        dict：{series,shunt}×{z_ohm,w_mm,er_eff,len_mm}。

    Raises:
        ValueError: 参数非法或 inverse_width 状态 needs_calibration。
    """
    from rfauto.core.synthesis import Stackup, forward_z0, inverse_width

    zs = _pos_finite(series_z_ohm, "series_z_ohm")
    zh = _pos_finite(shunt_z_ohm, "shunt_z_ohm")
    f0 = _pos_finite(f0_ghz, "f0_ghz")
    er_num = _er_guard(er)
    h = _pos_finite(h_mm, "h_mm")
    stackup = Stackup(name="rf_matrix_branchline",
                      epsilon_r=er_num, thickness_mm=h)
    out: dict[str, float] = {}
    for tag, z_t in (("series", zs), ("shunt", zh)):
        w_mm, _z_act, status = inverse_width(z_t, f0, stackup)
        if status != "ok":
            raise ValueError(
                f"branchline_arm_media: {tag} 臂 {z_t}Ω 线宽反解越括号"
                f"（w∈[0.05,20]mm 可达阻抗面外）——理想模型 fail-closed，"
                f"status={status!r}")
        media = forward_z0(w_mm, f0, stackup)
        out[f"{tag}_z_ohm"] = z_t
        out[f"{tag}_w_mm"] = float(w_mm)
        out[f"{tag}_er_eff"] = float(media.er_eff)
        out[f"{tag}_len_mm"] = _C_MM_GHZ / (4.0 * f0
                                            * math.sqrt(media.er_eff))
    return out


def branchline_ideal_sparams(
    freq_ghz: Any,
    z0_ohm: float = 50.0,
    f0_ghz: float = 2.4,
    er: float = 3.66,
    h_mm: float = 0.508,
    coupling_c: float | None = None,
    series_z_ohm: float | None = None,
    shunt_z_ohm: float | None = None,
    z_ref_ohm: float | None = None,
) -> np.ndarray:
    """理想分支线耦合器逐频点 4×4 复 S 矩阵（TL 半电路 ABCD 闭式）。

    四臂全 λ/4 @f0（各臂各自 εeff 定物理长，电长 θ(f0)=90° 精确）；
    偶/奇半电路 ABCD 级联 → Γe/Γo/Te/To → Pozar 式叠加合成 4×4。
    f0 处 3dB 设计：|S21|=|S31|=1/√2（−3.0103dB 功率等分）、S21 相位
    −90°、S31 相位 180°、S11=S41=0（机器精度级，幺正由构造保证）。

    Args:
        freq_ghz: 频点（GHz；标量或非空一维数组，全 >0 有限）。
        z0_ohm: 端口/馈线特性阻抗（>0）。
        f0_ghz: 设计中心频率（GHz，>0；λ/4 臂长反解基准）。
        er: 基板相对介电常数（≥1）。
        h_mm: 基板厚度（mm，>0）。
        coupling_c: 直通电压系数 |S21|（0<c<1；None=3dB 1/√2）。
        series_z_ohm: 串联臂阻抗显式覆盖（None=设计闭式 c·Z0）。
        shunt_z_ohm: 并联臂阻抗显式覆盖（None=设计闭式 Z0·c/√(1−c²)）。
        z_ref_ohm: S 参数参考阻抗（None=z0_ohm）。

    Returns:
        (n,4,4) complex128：s[k, i, j]=频点 k 端口 i 响应/端口 j 激励
        （1/2/3/4=输入/直通/耦合/隔离）。

    Raises:
        ValueError: 任何入参越守卫域（fail-closed，见模块 docstring）。
    """
    f_arr = np.asarray(freq_ghz, dtype=float)
    if f_arr.ndim == 0:
        f_arr = f_arr.reshape(1)
    f_arr = f_arr.reshape(-1)
    if f_arr.size == 0:
        raise ValueError("freq_ghz 必须非空（标量或一维数组）")
    if not np.all(np.isfinite(f_arr)):
        raise ValueError(f"freq_ghz 必须全为有限数，得到 {freq_ghz!r}")
    if np.any(f_arr <= 0.0):
        raise ValueError(
            f"freq_ghz 必须 >0（f→0 奇模半桩导纳奇异，fail-closed），"
            f"得到 {freq_ghz!r}")
    z0 = _pos_finite(z0_ohm, "z0_ohm")
    f0 = _pos_finite(f0_ghz, "f0_ghz")
    er_num = _er_guard(er)
    _ = _pos_finite(h_mm, "h_mm")
    z1_d, z2_d = branchline_arm_impedances(z0, coupling_c)
    z1 = (z1_d if series_z_ohm is None
          else _pos_finite(series_z_ohm, "series_z_ohm"))
    z2 = (z2_d if shunt_z_ohm is None
          else _pos_finite(shunt_z_ohm, "shunt_z_ohm"))
    z_ref = z0 if z_ref_ohm is None else _pos_finite(z_ref_ohm, "z_ref_ohm")

    media = branchline_arm_media(z1, z2, f0, er_num, h_mm)

    from rfauto.core.emi_filter import abcd_cascade, abcd_parallel, abcd_to_s
    from rfauto.core.even_odd_split import transmission_line_abcd

    # 电长度显式式 θ=2πf√εeff·L/c（λ/4 反解保证 θ(f0)=π/2 精确）
    th_ser = 2.0 * math.pi * f_arr * math.sqrt(media["series_er_eff"]) \
        * media["series_len_mm"] / _C_MM_GHZ
    th_sh2 = (2.0 * math.pi * f_arr * math.sqrt(media["shunt_er_eff"])
              * media["shunt_len_mm"] / _C_MM_GHZ) / 2.0
    y2 = 1.0 / z2
    tan_h = np.tan(th_sh2)
    y_e = 1j * y2 * tan_h                       # 偶模：对称面开路半桩
    y_o = -1j * y2 / tan_h                      # 奇模：对称面短路半桩

    tl = np.stack([np.asarray(transmission_line_abcd(z1, float(t)),
                              dtype=complex) for t in th_ser])
    half_e = abcd_cascade(abcd_parallel(y_e),
                          abcd_cascade(tl, abcd_parallel(y_e)))
    half_o = abcd_cascade(abcd_parallel(y_o),
                          abcd_cascade(tl, abcd_parallel(y_o)))
    s_e = abcd_to_s(half_e, z_ref, z_ref)
    s_o = abcd_to_s(half_o, z_ref, z_ref)

    g_e, t_e = s_e[:, 0, 0], s_e[:, 1, 0]
    g_o, t_o = s_o[:, 0, 0], s_o[:, 1, 0]
    g_avg = (g_e + g_o) / 2.0      # S11=S22=S33=S44
    g_dif = (g_e - g_o) / 2.0      # S41=S14=S32=S23（隔离对）
    t_sum = (t_e + t_o) / 2.0      # S21=S12=S34=S43（直通对）
    t_dif = (t_e - t_o) / 2.0      # S31=S13=S24=S42（耦合对）

    n = f_arr.size
    s = np.empty((n, 4, 4), dtype=complex)
    for i in range(4):
        s[:, i, i] = g_avg
    for i, j in ((0, 1), (1, 0), (2, 3), (3, 2)):
        s[:, i, j] = t_sum
    for i, j in ((0, 2), (2, 0), (1, 3), (3, 1)):
        s[:, i, j] = t_dif
    for i, j in ((0, 3), (3, 0), (1, 2), (2, 1)):
        s[:, i, j] = g_dif
    return s


def branchline_ideal_design(
    z0_ohm: float = 50.0,
    f0_ghz: float = 2.4,
    er: float = 3.66,
    h_mm: float = 0.508,
    coupling_c: float | None = None,
) -> dict[str, Any]:
    """理想分支线耦合器设计元数据（接线/报表用，零 S 矩阵展开）。

    臂阻抗设计闭式 + 两臂 HJ 介质解析（线宽/εeff/λ/4 物理臂长）+ f0
    电长度复核（θ=2πf0√εeff·L/c 应逐位 =π/2）。纯函数零 IO。

    Raises:
        ValueError: 入参越守卫域（同 branchline_ideal_sparams）。
    """
    z1, z2 = branchline_arm_impedances(z0_ohm, coupling_c)
    f0 = _pos_finite(f0_ghz, "f0_ghz")
    media = branchline_arm_media(z1, z2, f0, er, h_mm)
    theta_ser_deg = math.degrees(
        2.0 * math.pi * f0 * math.sqrt(media["series_er_eff"])
        * media["series_len_mm"] / _C_MM_GHZ)
    theta_sh_deg = math.degrees(
        2.0 * math.pi * f0 * math.sqrt(media["shunt_er_eff"])
        * media["shunt_len_mm"] / _C_MM_GHZ)
    return {
        "z0_ohm": z0_ohm,
        "f0_ghz": f0,
        "coupling_c": round(_3DB_C if coupling_c is None
                            else float(coupling_c), 15),
        "series_z_ohm": z1,
        "shunt_z_ohm": z2,
        "series_w_mm": media["series_w_mm"],
        "series_er_eff": media["series_er_eff"],
        "series_len_mm": media["series_len_mm"],
        "shunt_w_mm": media["shunt_w_mm"],
        "shunt_er_eff": media["shunt_er_eff"],
        "shunt_len_mm": media["shunt_len_mm"],
        "series_theta_deg_at_f0": theta_ser_deg,
        "shunt_theta_deg_at_f0": theta_sh_deg,
        "note": (
            "理想 TL 闭式（四臂 λ/4 各臂各自 εeff，XA-3 口径承袭"
            "synthesize_branchline）；色散/微带不连续/损耗不在面；S 矩阵"
            "频响=branchline_ideal_sparams（奇偶半电路 ABCD 级联闭式）"),
    }
