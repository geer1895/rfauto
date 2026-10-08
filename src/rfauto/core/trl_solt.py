"""TRL/SOLT 校准提取内核（TH-2 尾程项 12 前半：标准件原始测量 → 二端口误差箱）。

定位（#122 边界承接）：core/thz_vna.py 模块 docstring 明言"Thru/Reflect/
Line 原始测量到误差箱的提取（TRL/SOLT 校准解）不在本内核，属调用方校准
引擎"——本模块即该校准引擎：SOLT 四标准件（理想短路/开路/匹配/直通）与
TRL 三标准件（直通/反射/线）的原始测量反解，产出 TH-2 消费端形态的误差
箱 dict {"ed","es","e12","e21"}（端口 p 误差箱 S=[[Ed,e12],[e21,Es]]，
端口 2 侧 Es 语义=load match），并提供 apply_calibration(raw, model)=
TH-2 八项闭式修正 S=(M·G−E)^{-1}(D−M·F)（直接复用
thz_vna.extender_correct_twoport，修正口径单一事实源）。

级联口径与记号（与 thz_vna 八项级联系数同源推导）::

    C_p = (1/e21_p)·[[r_p − d_p·s_p, d_p], [−s_p, 1]]，r_p = e12_p·e21_p
    （= thz_vna 级联系数 X·K，K=对换阵；w_p=[b_mp;a_mp]=C_p·[b_dp;a_dp]）

    DUT 传输阵 Td(S) = (1/S12)·[[S22, −detS],[1, −S11]]
    级联测量阵 R = C2·Td·C1^{-1}（w2 = R·w1，对任意系统状态成立）

    仪器口径测量矩阵恒等式（对任意 DUT 逐项成立，并与
    extender_forward_twoport 数值互证，见 test_trl_solt.py）::
        M11 = −R22/R21    M22 = R11/R21
        M21 = −detR/R21   M12 = +1/R21
    其中 M12=1/R21（反向传输=级联元倒数）为一切"绝对定标"的锚——
    单个标准件的 4 个测量复数即完全定其 R（无逐标准件标度自由度）。

SOLT（Short-Open-Load-Thru → 八项提取向）::
    一端口三项闭式（Pozar Microwave Engineering VNA 校准章同款；理想
    短路 Γs=−1、开路 Γo=+1、负载 Γl=0）：d = m_load、N_s=m_short−d、
    N_o=m_open−d、ρ=N_o/N_s::

        Es = (ρ+1)/(ρ−1)，Er = 2·N_o·N_s/(N_s−N_o)

    端口 1 消费正向反射 M11、端口 2 消费反向反射 M22（各自三项）；Er
    即跟踪 r_p。Thru 定分裂与归一常数：由 R_thru = C2·K·C1^{-1} 的
    R21 元 = k·(1−s1·s2) 与恒等式 R21 = 1/M12^thru::

        k ≡ e21_1/(e21_2·r_1) = 1/(M12^thru·(1 − s1·s2))

    规范（gauge）固定 e21_2 = 1 → e21_1 = k·r1、e12_1 = 1/k、e12_2 = r2。
    8 项 vs 12 项：本内核=八项口径（TH-2 消费面）；十二项的隔离度/串扰
    四项不建模（理想标准件+无泄漏假设，#122 如实声明）。

TRL（Thru-Reflect-Line → 七项）::
    Thru: Td=K；Line: Td=[[0,λ],[1/λ,0]]（λ=e^{−γl} 为 line 传输系数，
    未知由测量定，Engen–Hoer 1979 口径）。R_thru、R_line 由恒等式绝对
    可定，相似变换::

        Q = R_line·R_thru^{-1} = C2·diag(λ, 1/λ)·C2^{-1}

    → Q 特征值={λ, 1/λ}、特征向量=C2 之列（各差任意复标度）；再
    C1 = R_thru^{-1}·C2·K。Reflect（两端口同一未知 γ）定余下自由度
    （对角标度比 u=β/α 与 γ）：反射响应的 Möbius 形（C 阵元表示，
    由三项模型直代入）::

        M11r = (C1_11·γ + C1_12)/(C1_21·γ + C1_22)
        M22r = (C2_11·γ + C2_12)/(C2_21·γ + C2_22)

    依次线性反解 w ≡ u·γ 与 u（两式均 Möbius/线性可逆），γ=u·(ς 比例，
    代码记号)；u²=w/ς 出 ±(u, γ) 根对——即经典 TRL reflect 相位歧义
    （Engen & Hoer, "'Thru-Reflect-Line': An Improved Technique…",
    IEEE T-MTT MTT-27(12), 1979；short/open 相位不可辨）。选根口径：
    调用方声明 reflect_kind（"short"→取 Re γ<0 支；"open"→Re γ>0 支），
    文献语义=reflect 相位已知 ±90°内、|Γ|≥0.3（Keysight "Applying Error
    Correction to Vector Network Analyzer Measurements" 应用笔记口径，
    亦即 Marks 1991 七项模型族 reflect 半已知约定）；|γ|<0.3 显式拒绝
    （<0.2 病态、0.2–0.3 低于文献判据，均不静默）；|Re γ| 相对 |γ| 过小
    （相位落在 ±90° 判别边界）如实拒绝。line 选根：arg∈(−π,0) 优先
    （e^{−γl} 延迟约定，兼容无耗 |λ|=1），实根退化取 |λ|<1（有耗）；
    **line 电长度 θ=βl 须 ∈(0,π)（电长度 <半波长，经典 TRL 约束）**：
    θ∈(π,2π) 时 arg λ 卷绕进上半平面、延迟半平面判别把倒数根 1/λ 当成
    λ——有耗情形 |λ_选中|>1 且 |λ_另一根|<1 的无源性签名显式拒绝
    （_select_line_root）；无耗两根同模、该签名不可见，属测量信息论上
    不可辨（与 ±γ reflect 歧义同族），由调用方按"line 电长度 <λ/2"声明
    排除（多线 TRL 校准件按频段换线即此惯例）；有耗情形的检测签名=
    选中根 |λ|>1+容差且对根 |λ|<1−容差（_LINE_PASSIVE_MARGIN=1e-9，
    吸收无耗线特征根 ~1e-15 数值噪声；αl≲1e-9 近无耗线低于签名地板，
    与无耗同归声明排除）；λ²=1（line 电长度 0 或
    半波长整数倍，line 与 thru 测量重合零信息）特征根简并，显式报错。

规范自由度与消费端对齐（thz_vna docstring"归一常数 k"语义）::
    (e21_1, e21_2) → (α·e21_1, α·e21_2) 下八项合成 M 逐点不变（D/E/F/G
    同时缩放 α），故 S 参数修正与该规范无关；d_p、s_p、r_p 为规范不
    变量。SOLT 固定 e21_2=1、TRL 固定特征向量归一（α=1 支）——两法
    规范不同但修正等价（SOLT↔TRL 交叉对拍钉，1e-9）；分裂 e12/e21 的
    绝对值须接收机功率/幅度校准方可定（七项模型固有边界，如实声明）。

零 IO、纯函数；逐频点独立提取（n 点标准件测量 → n 点误差箱）；S 全
线性复数域运算（dB 域禁入内核）；复数经 JSON 通道一律 [re,im] 对。
守卫=结构奇异 exact-zero 拒绝（近奇异病态不设容差门，校准质量归调用
方——与 thz_vna exact-zero 口径一致）；两处例外为任务明文指定的阈值
判据：reflect 幅值（0.2/0.3）与 line 特征根简并容差（λ=±1 的简并只经
舍入残差显现，exact-zero 抓不住，1e-9×局部分析尺度见
_LINE_DEGENERATE_RTOL 注）。理想箱回收/病态拒绝/SOLT↔TRL 交叉对拍见
tests/unit/test_trl_solt.py（#118：注入已知误差箱 → TH-2 前向合成
标准件 → 提取 → 真值回收，容差 1e-9）。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from rfauto.core.thz_vna import extender_correct_twoport

__all__ = ["apply_calibration", "solt_extract", "trl_extract"]

# reflect 幅值判据（任务指定阈值）：|Γref|<0.2 病态硬错；0.2–0.3 低于
# 文献选根判据（Keysight ≥0.3 口径）同样显式拒绝（不静默采信）
_REFLECT_MAG_PATHOLOGIC = 0.2
_REFLECT_MAG_LITERATURE = 0.3
# reflect 相位半平面判别的相对边界：|Re γ|/|γ| 低于此 = 相位落在 ±90°
# 判别边界上，short/open 声明不可辨，如实拒绝
_REFLECT_PHASE_EDGE_RTOL = 1e-12
# line 无源性签名判别地板：选中根 |λ|>1+此容差且对根 |λ|<1−此容差才判
# "arg λ 按 2π 卷绕（电长度跨半波长）"——无耗线 |λ|=|1/λ|=1 的特征根
# 数值噪声 ~1e-15 不得误伤；αl≲1e-9 的近无耗跨半波线低于签名地板，
# 与无耗同归"调用方保证电长度 ∈(0,π)"声明排除（见 _select_line_root）
_LINE_PASSIVE_MARGIN = 1e-9
# line 退化判别容差：λ=±1（line 电长度 0/半波长整数倍）时 Q=R_thru·
# R_thru^{-1} 的简并只通过舍入残差显现（disc ≈ 舍入级而非精确 0，
# exact-zero 守卫抓不住），任务明文要求"非 0 非 λ/2 校验+明确报错"——
# disc 特征根间隔容差 = 1e-9×局部分析尺度（|tr|≈2|cosθ|、det≈1 →
# eps≈4e-9）；合法 line 相位 ≥1e-4 rad 时 disc ≈ 4θ² ≈ 4e-8，一个数量
# 级裕度（数值实测拒绝边界 θ≈3.2e-5 rad，见 tests/unit/test_trl_solt.py）
_LINE_DEGENERATE_RTOL = 1e-9

_SWAP_K = np.array([[0.0 + 0.0j, 1.0 + 0.0j],
                    [1.0 + 0.0j, 0.0 + 0.0j]])


# ────────────────────────── 入参收敛与守卫 ──────────────────────────
def _matrix_series(value: Any, name: str,
                   n: int | None = None) -> np.ndarray:
    """(n,2,2) 复数矩阵列 / 单 (2,2) 复数矩阵 / [re,im] 对形态（(4,2) 单
    矩阵或 (n,4,2) 列）→ (n,2,2) 复数 ndarray（thz_vna._as_matrix_series
    同口径收敛，本模块自带收敛面以防跨模块私有耦合）。"""
    arr = np.asarray(value)
    if arr.dtype.kind != "c":
        try:
            arr_p = np.asarray(value, dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} 不是可转 [re,im] 对的数值列：{exc}") \
                from exc
        if arr_p.ndim == 2 and arr_p.shape == (4, 2):
            arr = (arr_p[:, 0] + 1j * arr_p[:, 1]).reshape(2, 2)
        elif arr_p.ndim == 3 and arr_p.shape[1:] == (4, 2):
            arr = (arr_p[:, :, 0] + 1j * arr_p[:, :, 1]).reshape(
                arr_p.shape[0], 2, 2)
        else:
            raise ValueError(f"{name} 须为 (n,2,2) 复数矩阵列、单个 (2,2) "
                             f"复数矩阵或 [re,im] 对形态，得 shape "
                             f"{np.shape(value)}")
    if arr.ndim == 2 and arr.shape == (2, 2):
        arr = arr.reshape(1, 2, 2)
    if arr.ndim != 3 or arr.shape[1:] != (2, 2):
        raise ValueError(f"{name} 须为 (n,2,2) 复数矩阵列或单个 (2,2) 矩阵，"
                         f"得 shape {np.shape(value)}")
    if arr.shape[0] < 1:
        raise ValueError(f"{name} 须为非空矩阵列（n>=1）")
    if n is not None and arr.shape[0] not in (1, n):
        raise ValueError(f"{name} 点数须为 1（带级广播）或 {n}，得 "
                         f"{arr.shape[0]}")
    return arr


def _broadcast_n(arr: np.ndarray, n: int) -> np.ndarray:
    return np.repeat(arr, n, axis=0) if arr.shape[0] == 1 else arr


def _as_complex_loose(value: Any, name: str) -> np.ndarray:
    """复数标量 / 一维复数列 / [re,im] 对或其对列 → 一维复数（长度 1 或
    n，具体 n 由消费端 thz_vna 带级广播口径裁定）。"""
    arr = np.asarray(value)
    if arr.dtype.kind == "c":
        if arr.ndim == 0:
            return arr.reshape(1)
        if arr.ndim == 1:
            return arr
        raise ValueError(f"{name} 复数直传须标量或一维，得 shape "
                         f"{np.shape(value)}")
    try:
        arr_f = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 不是可转 [re,im] 的数值列：{exc}") from exc
    if arr_f.ndim == 1 and arr_f.shape == (2,):
        arr_f = arr_f.reshape(1, 2)
    if arr_f.ndim != 2 or arr_f.shape[1] != 2:
        raise ValueError(f"{name} 须为 [re,im] 对或其对列，得 shape "
                         f"{np.shape(value)}")
    return arr_f[:, 0] + 1j * arr_f[:, 1]


def _pairs(a: Any) -> list[list[float]]:
    return [[float(v.real), float(v.imag)] for v in np.asarray(a)]


def _pairs_box(box: dict[str, np.ndarray]) -> dict[str, list[list[float]]]:
    return {key: _pairs(val) for key, val in box.items()}


# ────────────────────── 级联测量阵 R 与其仪器口径恒等式 ──────────────────────
def _r_from_measured(m: np.ndarray, tag: str) -> np.ndarray:
    """单频点标准件测量矩阵（仪器口径 2×2）→ 级联测量阵 R（恒等式
    M11=−R22/R21、M22=R11/R21、M21=−detR/R21、M12=1/R21 的反演）。"""
    m11, m12 = complex(m[0, 0]), complex(m[0, 1])
    m21, m22 = complex(m[1, 0]), complex(m[1, 1])
    if m12 == 0.0:
        raise ValueError(f"{tag}：反向传输 M12=0（R21 不可定），级联测量阵 "
                         "R 如实拒绝")
    if m21 == 0.0:
        raise ValueError(f"{tag}：M21=0（det R=0 级联退化），如实拒绝")
    r21 = 1.0 / m12
    return np.array([[m22 / m12, m21 - m11 * m22 / m12],
                     [r21, -m11 / m12]])


def _inv2(m: np.ndarray, tag: str) -> np.ndarray:
    det = m[0, 0] * m[1, 1] - m[0, 1] * m[1, 0]
    if det == 0.0:
        raise ValueError(f"{tag}：2×2 矩阵奇异（det=0），如实拒绝")
    return np.array([[m[1, 1], -m[0, 1]], [-m[1, 0], m[0, 0]]]) / det


# ──────────────────────────── SOLT 提取 ────────────────────────────
def _oneport_three_term(m_short: np.ndarray, m_open: np.ndarray,
                        m_load: np.ndarray,
                        tag: str) -> tuple[np.ndarray, np.ndarray,
                                           np.ndarray]:
    """一端口三项闭式反解（理想 Γs=−1/Γo=+1/Γl=0；Pozar VNA 校准章
    同款）：返回 (d=directivity, es=source match, er=reflection
    tracking)。病态（短路≡负载、开路≡短路、tracking 零）显式拒绝。"""
    d = m_load
    n_s = m_short - d
    n_o = m_open - d
    if np.any(n_s == 0.0):
        raise ValueError(f"{tag}：短路响应与负载响应重合（N_s=0），一端口"
                         "三项不可辨，如实拒绝")
    if np.any(n_o == n_s):
        raise ValueError(f"{tag}：开路与短路响应重合（ρ=N_o/N_s=1），"
                         "source match 不可辨，如实拒绝")
    rho = n_o / n_s
    es = (rho + 1.0) / (rho - 1.0)
    er = 2.0 * n_o * n_s / (n_s - n_o)
    if np.any(er == 0.0):
        raise ValueError(f"{tag}：reflection tracking 为零（误差箱失效），"
                         "如实拒绝")
    return d, es, er


def solt_extract(short_p1: Any, open_p1: Any, load_p1: Any,
                 short_p2: Any, open_p2: Any, load_p2: Any,
                 thru: Any) -> dict[str, Any]:
    """SOLT 校准提取：四理想标准件原始测量 → TH-2 八项误差箱（逐频点）。

    参数（各为仪器口径原始 S 矩阵：(n,2,2) 复数列 / 单 (2,2) /
    [re,im] 对形态，单点矩阵按带级广播口径允许 (1,2,2)）：
    short_p1/open_p1/load_p1=端口 1 接短路/开路/匹配时的原始测量
    （消费正向反射 M11）；short_p2/open_p2/load_p2=端口 2 接同款标准件
    （消费反向反射 M22）；thru=直通（消费全部四元）。标准件定义（理想）：
    短路 Γ=−1、开路 Γ=+1、匹配 Γ=0、直通 S=[[0,1],[1,0]]。

    返回 dict：method="solt"、n_points、k（归一常数 e21_1/(e21_2·r1)，
    规范固定 e21_2=1）、box1/box2={"ed","es","e12","e21"}（[re,im] 对列，
    直通 thz_vna.extender_correct_twoport/extender_forward_twoport 消费）。
    口径与病态守卫见模块 docstring。
    """
    ms1 = _matrix_series(short_p1, "short_p1")
    n_pts = ms1.shape[0]
    mo1 = _broadcast_n(_matrix_series(open_p1, "open_p1", n_pts), n_pts)
    ml1 = _broadcast_n(_matrix_series(load_p1, "load_p1", n_pts), n_pts)
    ms2 = _broadcast_n(_matrix_series(short_p2, "short_p2", n_pts), n_pts)
    mo2 = _broadcast_n(_matrix_series(open_p2, "open_p2", n_pts), n_pts)
    ml2 = _broadcast_n(_matrix_series(load_p2, "load_p2", n_pts), n_pts)
    mt = _broadcast_n(_matrix_series(thru, "thru", n_pts), n_pts)

    d1, s1, r1 = _oneport_three_term(ms1[:, 0, 0], mo1[:, 0, 0],
                                     ml1[:, 0, 0], "端口 1 一端口校准")
    d2, s2, r2 = _oneport_three_term(ms2[:, 1, 1], mo2[:, 1, 1],
                                     ml2[:, 1, 1], "端口 2 一端口校准")
    m12_t = mt[:, 0, 1]
    if np.any(m12_t == 0.0):
        raise ValueError("thru 反向传输 M12=0（归一常数 k 不可定），如实拒绝")
    den = 1.0 - s1 * s2
    if np.any(den == 0.0):
        raise ValueError("1−s1·s2=0（thru 级联 R21 元奇异），如实拒绝")
    k = 1.0 / (m12_t * den)
    box1: dict[str, np.ndarray] = {"ed": d1, "es": s1,
                                   "e12": 1.0 / k, "e21": k * r1}
    box2: dict[str, np.ndarray] = {"ed": d2, "es": s2, "e12": r2,
                                   "e21": np.ones(n_pts, dtype=complex)}
    return {
        "method": "solt",
        "n_points": int(n_pts),
        "k": _pairs(k),
        "box1": _pairs_box(box1),
        "box2": _pairs_box(box2),
    }


# ──────────────────────────── TRL 提取 ────────────────────────────
def _select_line_root(mu_a: complex, mu_b: complex,
                      tag: str) -> tuple[complex, complex]:
    """line 传输系数选根（返回 (λ, 另一根)）：arg∈(−π,0) 优先（e^{−γl}
    延迟约定，无耗 |λ|=1 时唯一可辨），实根退化取 |λ|<1（有耗）；λ²=1
    （line 电长度 0 或半波长整数倍）显式拒绝。

    无源性一致性守卫：无源线 |λ|≤1，若选中根 |λ|>1+容差而对根
    |λ|<1−容差（_LINE_PASSIVE_MARGIN，吸收无耗线特征根 ~1e-15 数值
    噪声），说明 arg λ 已按 2π 卷绕（line 电长度 θ∈(π,2π)，延迟半平面
    判别把倒数根 1/λ 当成了 λ，静默错根会给出 plausible-but-wrong 误差
    箱）——显式拒绝。无耗（|λ|=1）两根同模、此签名不可见，αl≲1e-9 的
    近无耗线低于签名地板，均属信息不可辨（经典 TRL 线长约束），由调用
    方按"电长度 <λ/2"声明排除（见模块 docstring）。"""
    for mu in (mu_a, mu_b):
        if mu * mu == 1.0:
            raise ValueError(f"{tag}：line 电长度为 0 或半波长整数倍"
                             "（λ²=1，line 与 thru 测量重合零信息），如实拒绝")
    a_ok = -np.pi < np.angle(mu_a) < 0.0
    b_ok = -np.pi < np.angle(mu_b) < 0.0
    if a_ok and not b_ok:
        lam, other = mu_a, mu_b
    elif b_ok and not a_ok:
        lam, other = mu_b, mu_a
    elif abs(mu_a) != abs(mu_b):
        lam, other = ((mu_a, mu_b) if abs(mu_a) < abs(mu_b)
                      else (mu_b, mu_a))
    else:
        raise ValueError(f"{tag}：line 根不可辨（两根同模且均不在延迟半平面），"
                         "如实拒绝")
    if (abs(lam) > 1.0 + _LINE_PASSIVE_MARGIN
            and abs(other) < 1.0 - _LINE_PASSIVE_MARGIN):
        raise ValueError(
            f"{tag}：line 传输系数 |λ|={abs(lam):.6g}>1 而对根 "
            f"|1/λ|={abs(other):.6g}<1（无源线不可能）——line 电长度超过"
            "半波长（arg λ 按 2π 卷绕，选根落在倒数根上），如实拒绝；"
            "无耗线此签名不可见，须由调用方保证 line 电长度 ∈(0,π)")
    return lam, other


def _eigvec2(q: np.ndarray, mu: complex, tag: str) -> np.ndarray:
    """2×2 复矩阵特征向量（闭式：取数值较大的行构造垂直向量）。"""
    r0 = abs(q[0, 0] - mu) ** 2 + abs(q[0, 1]) ** 2
    r1 = abs(q[1, 0]) ** 2 + abs(q[1, 1] - mu) ** 2
    v = (np.array([q[0, 1], mu - q[0, 0]]) if r0 >= r1
         else np.array([mu - q[1, 1], q[1, 0]]))
    if np.abs(v[0]) == 0.0 and np.abs(v[1]) == 0.0:
        raise ValueError(f"{tag}：特征向量退化（Q 缺特征结构），如实拒绝")
    return v


def _box_from_c(c: np.ndarray, tag: str) -> tuple[dict[str, complex],
                                                  complex]:
    """级联系数 C=[[r−ds, d],[−s, 1]]/e21（模块 docstring 记号）→ 误差箱
    dict 与跟踪积 r（规范：e21=1/C[1,1]，d/s/r 为规范不变量）。"""
    c22 = complex(c[1, 1])
    if c22 == 0.0:
        raise ValueError(f"{tag}：级联系数 C[1,1]=0（误差箱失效），如实拒绝")
    e21 = 1.0 / c22
    ed = complex(c[0, 1]) / c22
    es = -complex(c[1, 0]) / c22
    r = complex(c[0, 0]) / c22 - complex(c[0, 1]) * complex(c[1, 0]) / (c22 * c22)
    if r == 0.0:
        raise ValueError(f"{tag}：reflection tracking 为零（误差箱失效），"
                         "如实拒绝")
    return {"ed": ed, "es": es, "e12": r / e21, "e21": e21}, r


def trl_extract(thru: Any, reflect_p1: Any, reflect_p2: Any, line: Any,
                reflect_kind: str = "short") -> dict[str, Any]:
    """TRL 校准提取（Engen–Hoer 1979）：三标准件原始测量 → 七项误差箱
    （逐频点；TH-2 消费形态 = 八项箱 + 规范说明，见模块 docstring）。

    参数：thru=直通原始测量（理想 0 长，S=[[0,1],[1,0]]）；reflect_p1/
    reflect_p2=同一 reflect 标准件分别接端口 1/2 的原始测量（两端口
    同一未知 γ，消费 M11/M22）；line=线标准件原始测量（匹配线
    S=[[0,λ],[λ,0]]，λ 未知由测量定，**电长度须 ∈(0,π)**——非 0 非
    λ/2 且不跨半波长：跨半波长的有耗线经无源性签名拒绝、无耗线信息
    不可辨须调用方保证，见模块 docstring"line 选根"节）；reflect_kind=
    reflect 选根声明（"short"→Re γ<0 支 / "open"→Re γ>0 支；经典 ±γ
    相位歧义的 ±90° 相位先验，Keysight |Γ|≥0.3 口径）。

    返回 dict：method="trl"、n_points、reflect_kind、line_lambda（提取的
    λ）、reflect_gamma（提取的 γ）、box1/box2（[re,im] 对列，与 SOLT 同
    消费面；规范为特征向量归一 α=1 支，与 SOLT 规范相差公共标度——S
    参数修正等价）。病态守卫见模块 docstring。
    """
    if reflect_kind not in ("short", "open"):
        raise ValueError(f"reflect_kind 须为 'short' 或 'open'（reflect "
                         f"±90° 相位先验声明），得 {reflect_kind!r}")
    mt = _matrix_series(thru, "thru")
    n_pts = mt.shape[0]
    mr1 = _broadcast_n(_matrix_series(reflect_p1, "reflect_p1", n_pts), n_pts)
    mr2 = _broadcast_n(_matrix_series(reflect_p2, "reflect_p2", n_pts), n_pts)
    ml = _broadcast_n(_matrix_series(line, "line", n_pts), n_pts)

    lam_arr = np.empty(n_pts, dtype=complex)
    gam_arr = np.empty(n_pts, dtype=complex)
    b1_list: list[dict[str, complex]] = []
    b2_list: list[dict[str, complex]] = []
    for i in range(n_pts):
        tag = f"TRL[{i}]"
        r_thru = _r_from_measured(mt[i], f"{tag} thru")
        r_line = _r_from_measured(ml[i], f"{tag} line")
        r_thru_inv = _inv2(r_thru, f"{tag} R_thru")
        q = r_line @ r_thru_inv
        tr = q[0, 0] + q[1, 1]
        dt = q[0, 0] * q[1, 1] - q[0, 1] * q[1, 0]
        disc = tr * tr - 4.0 * dt
        disc_eps = _LINE_DEGENERATE_RTOL * max(1.0, abs(tr) ** 2, 4.0 * abs(dt))
        if abs(disc) <= disc_eps:
            raise ValueError(f"{tag}：line 标准件电长度退化（特征根简并："
                             "line 电长度 0 或半波长整数倍，与 thru 测量"
                             "重合零信息），如实拒绝")
        sq = np.sqrt(disc)
        mu_a, mu_b = (tr + sq) / 2.0, (tr - sq) / 2.0
        lam, mu_other = _select_line_root(mu_a, mu_b, tag)
        v_lo = _eigvec2(q, lam, tag)
        v_hi = _eigvec2(q, mu_other, tag)
        v_mat = np.column_stack([v_lo, v_hi])  # = C2（差 diag(α,β) 标度）
        c1_base = r_thru_inv @ v_mat @ _SWAP_K
        m11_r = complex(mr1[i, 0, 0])
        m22_r = complex(mr2[i, 1, 1])
        w_den = m11_r * c1_base[1, 0] - c1_base[0, 0]
        if w_den == 0.0:
            raise ValueError(f"{tag}：reflect 反演 w 项分母为零（端口 1 "
                             "Möbius 退化），如实拒绝")
        w = (c1_base[0, 1] - m11_r * c1_base[1, 1]) / w_den
        s_den = m22_r * v_mat[1, 0] - v_mat[0, 0]
        if s_den == 0.0:
            raise ValueError(f"{tag}：reflect 反演 ς 项分母为零（端口 2 "
                             "Möbius 退化），如实拒绝")
        sigma = (v_mat[0, 1] - m22_r * v_mat[1, 1]) / s_den
        if w == 0.0 or sigma == 0.0:
            raise ValueError(f"{tag}：reflect 反演退化（w=0 或 ς=0，端口 "
                             "标度不可定），如实拒绝")
        u = np.sqrt(w / sigma)  # 复主枝；±(u, γ) 根对=reflect 相位歧义
        gamma = sigma * u
        mag = abs(gamma)
        if mag < _REFLECT_MAG_PATHOLOGIC:
            raise ValueError(f"{tag}：|Γref|={mag:.6g}<{_REFLECT_MAG_PATHOLOGIC}"
                             "（reflect 病态，校准不可信），如实拒绝")
        if mag < _REFLECT_MAG_LITERATURE:
            raise ValueError(f"{tag}：|Γref|={mag:.6g} 低于文献选根判据 "
                             f"|Γ|≥{_REFLECT_MAG_LITERATURE}（Keysight "
                             "TRL 口径），如实拒绝")
        if abs(gamma.real) <= _REFLECT_PHASE_EDGE_RTOL * mag:
            raise ValueError(f"{tag}：reflect 相位落在 ±90° 判别边界上"
                             "（|Re γ|/|γ| 过小，short/open 声明不可辨），"
                             "如实拒绝")
        flip = ((reflect_kind == "short" and gamma.real > 0.0)
                or (reflect_kind == "open" and gamma.real < 0.0))
        if flip:
            u, gamma = -u, -gamma
        c2_f = v_mat @ np.diag([1.0 + 0.0j, u])
        c1_f = c1_base @ np.diag([u, 1.0 + 0.0j])
        b1, _ = _box_from_c(c1_f, f"{tag} box1")
        b2, _ = _box_from_c(c2_f, f"{tag} box2")
        lam_arr[i] = lam
        gam_arr[i] = gamma
        b1_list.append(b1)
        b2_list.append(b2)

    def _box_series(boxes: list[dict[str, complex]]) -> dict[str, np.ndarray]:
        return {key: np.array([b[key] for b in boxes], dtype=complex)
                for key in ("ed", "es", "e12", "e21")}

    return {
        "method": "trl",
        "n_points": int(n_pts),
        "reflect_kind": reflect_kind,
        "line_lambda": _pairs(lam_arr),
        "reflect_gamma": _pairs(gam_arr),
        "box1": _pairs_box(_box_series(b1_list)),
        "box2": _pairs_box(_box_series(b2_list)),
    }


# ──────────────────────── 误差模型反演修正 ────────────────────────
def _converge_box(box: Any, tag: str) -> dict[str, np.ndarray]:
    if not isinstance(box, dict):
        raise ValueError(f"{tag} 须为 dict（ed/es/e12/e21）")
    out: dict[str, np.ndarray] = {}
    for key in ("ed", "es", "e12", "e21"):
        if key not in box:
            raise ValueError(f"{tag}.{key} 缺失（误差箱须含 ed/es/e12/e21）")
        out[key] = _as_complex_loose(box[key], f"{tag}.{key}")
    return out


def apply_calibration(raw_sparams: Any, model: Any) -> np.ndarray:
    """误差模型反演修正：原始测量矩阵 → DUT 真值 S 参数（(n,2,2) 复数）。

    model=solt_extract/trl_extract 产物（至少含 box1/box2，[re,im] 列或
    复数列皆收）；修正闭式=TH-2 八项 S=(M·G−E)^{-1}(D−M·F)，直接复用
    thz_vna.extender_correct_twoport（消费端单一事实源；e21 零点/修正
    行列式奇异在该处 exact-zero 拒绝）。规范说明：七项模型的 (e21_1,
    e21_2) 公共标度不影响修正结果（模块 docstring"规范自由度"节）。
    """
    if not isinstance(model, dict) or "box1" not in model or "box2" not in model:
        raise ValueError("model 须为 solt_extract/trl_extract 产物"
                         "（至少含 box1/box2 误差箱）")
    box1 = _converge_box(model["box1"], "box1")
    box2 = _converge_box(model["box2"], "box2")
    return extender_correct_twoport(raw_sparams, box1, box2)
