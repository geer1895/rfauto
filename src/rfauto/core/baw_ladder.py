"""BAW 梯形/格型滤波器综合内核（PK-2，规格深案 §A-2）。

纯函数零 IO 零外部进程（铁律 7 合规）；参照 core/rwg_mmt.py 与
core/acoustic_resonator.py（PK-1）先例**不进** @register_calculator 注册表
（免 #231/#304 注册表消费者连动），导出函数供后续 service 层直调，CLI/MCP
薄壳是后续分期面。测试=tests/unit/test_baw_ladder.py（锚树预声明见该文件
docstring，#122）。

拓扑与带缘口径
--------------
n_sections 节梯形：每节=串臂+并臂 L 网络，总 ABCD=(M_s@M_p)^n（左累积乘，
节点矩阵逐频装配）。臂=无损 BVD 单端口频域闭式（时谐 e^{+jωt}，与
acoustic_resonator/rwg_mmt 一致）::

    Z(f) = (1/(jωC0))·(f²−fs²)/(f²−fa²)

极限钉形：f→0 得 1/(jω(C0+Cm))（静态 C0 与动态 Cm 串联相加）、f→∞ 得
1/(jωC0)（动态臂开路）——若误写 (1−f²/fs²)/(1−f²/fa²) 会多出 (1+Cm/C0)
因子，被测试 A6 的 mbvd_impedance 独立实现对拍当场抓出（#118 双链裁判
的实证价值）。fa=fs·√(1+Cm/C0) 与 acoustic_resonator.bvd_resonances 同式
（数值交叉核对与 keff2 守卫复用见下）；Cm=c·C0、Lm=1/(ωs²Cm)。

- 串臂：fs_s=fs_series_hz、fa_s=fs_s·√(1+c)
- 并臂：fs_p=fs_series_hz·√(f_area_ratio)、fa_p=fs_p·√(1+c)
- 传输零点/带缘：并臂串联谐振 fs_p=低侧零（并臂短路）、串臂反谐振
  fa_s=高侧零（串臂开路），通带=(fs_p, fa_s)。这是 BAW/SAW 梯形滤波器
  "通带落在并臂串联谐振与串臂反谐振之间"的教科书口径（出处带，未逐页
  核对页码）。
- 带通判据：通带内两臂电抗反号 ⟺ fs_p<fs_s ⟺ f_area_ratio<1；r≥1 退化
  为带阻形态（两零之间的区域两臂同号），ValueError 拒绝。

fs_p=fs_series·√(f_area_ratio) 的口径与物理警示
------------------------------------------------
该映射系规格 §A-2 verbatim 约定（面积比作并臂频率映射旋钮）。物理口径
面积律只标度阻抗（Z∝1/A，C0/Cm∝A），谐振频率由声学厚度决定——真机
频率搬移另有质量加载/减薄手段，此处按规格把频移折进面积比旋钮。方向
（r<1，并臂频率低于串臂）由锚语义钉死：S21@fs_s=0dB 要求并臂反谐振对齐
串臂串联谐振（fa_p=fs_s ⟺ r=1/(1+c)），此即本实现的缺省工作点。

相对带宽上限（工程口径）与守卫（策略声明）
------------------------------------------
keff²=keff2(fs_s,fa_s,exact=False)=1−(fs_s/fa_s)²=c/(1+c)（PK-1 复用）。
工程通则："梯形滤波器相对带宽上限 ~keff² 量级"（Lakin/Ruby 口径，出处
带）。本实现的精确上限取 fa_p=fs_s 最大透射对齐态：请求相对带宽
(fa_s−fs_p)/fs_s=√(1+c)−√r ≤ c/√(1+c)=keff²·√(1+c)——比工程口径 keff²
大 √(1+c) 因子，如实注明不抹平。守卫策略（declared）：请求带宽超上限
→ValueError（不 warning、不夹持）；c∉(0,0.3]、r∉[1/(1+c),1)、
n_sections<1、z0≤0 同样 ValueError。

阻抗尺度与奇异点
----------------
C0=1/(2π·f_c·z0)、f_c=√(fs_p·fa_s)（带心臂电抗量级≈z0 的工程选择；
fa_p=fs_s 对齐态下 f_c=fs_s）。无损极点（fs_p、fa_p、fa_s，见返回值
pole_freqs_hz）上闭式分母为零：网格点恰落极点 → inf/nan（无损模型奇点，
模块内 errstate 吸收除零警告）；极点邻近取 ε 偏置采样即可（相对 1e-9
偏置零深已 <−200dB）。r=1 的 fs_s 重合角点已被 r<1 守卫排除。

格型变体（lattice_variant）
---------------------------
四臂格型（Za=串臂谐振器、Zb=并臂谐振器）::

    ABCD = 1/(1−t)·[[1+t, 2Za], [2Yb, 1+t]]，t=Za/Zb=Za·Yb
    Zi = √(Za·Zb) = √(Za/Yb)（格型镜像阻抗经典式）

Za=0、Yb=0 的 fs_s 对齐点 ABCD=I、S21=1 精确；带内两臂反号 → Zi 实值。
极点角点（fs_p、fa_s 恰落网格）nan，同上 ε 偏置。

原语复用说明：并臂矩阵逐字复用 metasurface_lut._abcd_shunt（导纳入参按
1/Y 还原阻抗后调用）；串臂 [[1,Z],[0,1]] 在 metasurface_lut 无对应原语
（_abcd_tl 是传输线原语，θ→0 退化为单位阵而非串臂），本地 _abcd_series
两行实现并在测试钉与原语同构。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import skrf

from rfauto.core.acoustic_resonator import keff2
from rfauto.core.metasurface_lut import _abcd_shunt

_TWO_PI = 2.0 * math.pi

#: Cm/C0 上限（与 acoustic_resonator._CMRATIO_MAX 同值，mBVD 可信耦合域）
_CM_C0_MAX = 0.3
#: 缺省 Cm/C0（AlN FBAR 典型量级，对应电路口径 keff²≈7.4%；材料表不在本件，
#: 规格 §A-1 E「材料表 UNVERIFIED_band」同原则）
_DEFAULT_CM_C0_RATIO = 0.08
#: 带宽守卫浮点容差（相对，仅吸收 ulp 级边界抖动）
_GUARD_TOL = 1e-12


def baw_arm_impedance(
    f_hz: float | np.ndarray,
    fs_hz: float,
    fa_hz: float,
    c0_f: float,
) -> complex | np.ndarray:
    """无损 BVD 臂阻抗 Z(f)（Ω）闭式：(1/(jωC0))·(f²−fs²)/(f²−fa²)。

    形式由极限钉死：f→0 得 1/(jω(C0+Cm))（C0 与 Cm 串联）、f→∞ 得
    1/(jωC0)；误写 (1−f²/fs²)/(1−f²/fa²) 会多 (1+Cm/C0) 因子（测试 A6
    mbvd_impedance 独立实现对拍钉住，#118）。
    纯虚数构造（实部恒 0、虚部走实数除法）——极点 fa_hz 处虚部 ±inf，
    规避复数乘法里 0·inf→nan 的污染；f=fs_hz 处 Z 精确为 0（分子精确
    相消）。标量入参返回 complex，数组入参返回 complex ndarray。
    极点恰落采样点产生 inf/nan 属无损模型奇点，调用方按 pole_freqs_hz
    掩膜或 ε 偏置。fs_hz/fa_hz/c0_f 须 >0 且 fs_hz<fa_hz。
    """
    fs = float(fs_hz)
    fa = float(fa_hz)
    c0 = float(c0_f)
    if fs <= 0.0 or fa <= 0.0 or c0 <= 0.0:
        raise ValueError(f"fs_hz/fa_hz/c0_f 须 >0，得 ({fs_hz}, {fa_hz}, {c0_f})")
    if not fa > fs:
        raise ValueError(f"须 fs_hz < fa_hz（fs≥fa 非物理），得 fs={fs_hz}, fa={fa_hz}")
    scalar = np.ndim(f_hz) == 0
    f = np.atleast_1d(np.asarray(f_hz, dtype=float))
    w = _TWO_PI * f
    with np.errstate(divide="ignore", invalid="ignore"):
        g = ((f * f) - (fs * fs)) / ((f * f) - (fa * fa))
        z = np.zeros(f.shape, dtype=complex)
        z.imag = -g / (w * c0)
    if scalar:
        return complex(z[0])
    return z


def baw_arm_admittance(
    f_hz: float | np.ndarray,
    fs_hz: float,
    fa_hz: float,
    c0_f: float,
) -> complex | np.ndarray:
    """无损 BVD 臂导纳 Y(f)（S）= 1/Z(f)，极点安全形式：jωC0·(1−f²/fa²)/(1−f²/fs²)。

    与 :func:`baw_arm_impedance` 互为倒数但极点位置不同（fs_hz 处导纳极点、
    fa_hz 处导纳零点），按需取用使各自工作频率上零点精确相消。参数约束同上。
    """
    fs = float(fs_hz)
    fa = float(fa_hz)
    c0 = float(c0_f)
    if fs <= 0.0 or fa <= 0.0 or c0 <= 0.0:
        raise ValueError(f"fs_hz/fa_hz/c0_f 须 >0，得 ({fs_hz}, {fa_hz}, {c0_f})")
    if not fa > fs:
        raise ValueError(f"须 fs_hz < fa_hz（fs≥fa 非物理），得 fs={fs_hz}, fa={fa_hz}")
    scalar = np.ndim(f_hz) == 0
    f = np.atleast_1d(np.asarray(f_hz, dtype=float))
    w = _TWO_PI * f
    with np.errstate(divide="ignore", invalid="ignore"):
        h = ((f * f) - (fa * fa)) / ((f * f) - (fs * fs))
        y = np.zeros(f.shape, dtype=complex)
        y.imag = w * c0 * h
    if scalar:
        return complex(y[0])
    return y


def _abcd_series(z: complex) -> np.ndarray:
    """串臂 ABCD=[[1,Z],[0,1]]（metasurface_lut 无对应原语，见模块 docstring）。"""
    return np.array([[1.0, z], [0.0, 1.0]], dtype=complex)


def _validated_design(
    fs_series_hz: float,
    f_area_ratio: float,
    cm_c0_ratio: float,
    z0_ohm: float,
) -> dict[str, float]:
    """公共入参校验与派生量（fs/fa 四频、C0、keff²、带宽与上限）。

    守卫策略（declared）：全部违反即 ValueError，不 warning 不夹持。
    """
    fs_s = float(fs_series_hz)
    if not fs_s > 0.0:
        raise ValueError(f"fs_series_hz 须 >0，得 {fs_series_hz}")
    c = float(cm_c0_ratio)
    if not 0.0 < c <= _CM_C0_MAX:
        raise ValueError(
            f"cm_c0_ratio 须 ∈ (0, {_CM_C0_MAX}]（mBVD 可信耦合域），得 {cm_c0_ratio}")
    r = float(f_area_ratio)
    if not r > 0.0:
        raise ValueError(f"f_area_ratio 须 >0，得 {f_area_ratio}")
    z0 = float(z0_ohm)
    if not z0 > 0.0:
        raise ValueError(f"z0_ohm 须 >0，得 {z0_ohm}")

    fa_s = fs_s * math.sqrt(1.0 + c)
    k2 = keff2(fs_s, fa_s, exact=False)  # PK-1 复用：c/(1+c)，兼带 0<fs<fa 守卫
    fs_p = fs_s * math.sqrt(r)
    # 带通判据：通带内两臂电抗反号 ⟺ fs_p < fs_s
    if not r < 1.0:
        raise ValueError(
            f"f_area_ratio={r} ≥1 退化为带阻形态（fs_p≥fs_s，通带内两臂同号），"
            "带通要求 <1")
    bw = (fa_s - fs_p) / fs_s
    bw_max = k2 * math.sqrt(1.0 + c)  # = c/√(1+c)，fa_p=fs_s 最大透射对齐态
    if bw > bw_max * (1.0 + _GUARD_TOL):
        raise ValueError(
            f"请求相对带宽 {bw:.6g} 超上限 {bw_max:.6g}（=keff²·√(1+c)，工程口径 "
            f"keff²={k2:.6g}）：f_area_ratio 须 ≥ {1.0 / (1.0 + c):.6g}")
    fa_p = fs_p * math.sqrt(1.0 + c)
    f_center = math.sqrt(fs_p * fa_s)
    c0 = 1.0 / (_TWO_PI * f_center * z0)
    return {
        "fs_s": fs_s,
        "fa_s": fa_s,
        "fs_p": fs_p,
        "fa_p": fa_p,
        "c": c,
        "r": r,
        "z0": z0,
        "c0": c0,
        "keff2": k2,
        "bw": bw,
        "bw_max": bw_max,
        "f_center": f_center,
    }


def _validated_grid(f_grid: np.ndarray) -> np.ndarray:
    """频栅校验：1-D、非空、有限、全正（PK-1 mbvd_* 同口径）。"""
    f = np.asarray(f_grid, dtype=float)
    if f.ndim != 1 or f.size == 0:
        raise ValueError(f"f_grid 须为非空 1-D 数组，得 shape={np.shape(f_grid)}")
    if not np.all(np.isfinite(f)) or np.any(f <= 0.0):
        raise ValueError(f"f_grid 须全为有限正值，得 min={f.min()}")
    return f


def _abcd_to_s(abcd: np.ndarray, z0: float) -> np.ndarray:
    """批量 ABCD→S（双端 z0 终接标准式；den 表达式顺序是锚测试逐位对拍的契约）。"""
    a = abcd[:, 0, 0]
    b = abcd[:, 0, 1]
    c_mat = abcd[:, 1, 0]
    d = abcd[:, 1, 1]
    s = np.empty(abcd.shape, dtype=complex)
    with np.errstate(divide="ignore", invalid="ignore"):
        den = a + b / z0 + c_mat * z0 + d
        det = a * d - b * c_mat
        s[:, 0, 0] = (a + b / z0 - c_mat * z0 - d) / den
        s[:, 1, 0] = 2.0 / den
        s[:, 0, 1] = 2.0 * det / den
        s[:, 1, 1] = (-a + b / z0 - c_mat * z0 + d) / den
    return s


def _design_metadata(design: dict[str, float], n_sections: int) -> dict[str, Any]:
    """公共返回元数据（标量面）。"""
    return {
        "fs_series_hz": design["fs_s"],
        "fa_series_hz": design["fa_s"],
        "fs_shunt_hz": design["fs_p"],
        "fa_shunt_hz": design["fa_p"],
        "f_center_hz": design["f_center"],
        "c0_f": design["c0"],
        "cm_c0_ratio": design["c"],
        "keff2": design["keff2"],
        "bw_rel": design["bw"],
        "bw_rel_max": design["bw_max"],
        "z0_ohm": design["z0"],
        "pole_freqs_hz": np.array([design["fs_p"], design["fa_p"], design["fa_s"]]),
    }


def ladder_filter_synthesis(
    fs_series_hz: float,
    f_area_ratio: float,
    n_sections: int,
    f_grid: np.ndarray,
    z0_ohm: float = 50.0,
    cm_c0_ratio: float = _DEFAULT_CM_C0_RATIO,
) -> dict[str, Any]:
    """BAW 梯形带通滤波器综合：n_sections 节串/并臂 L 网络级联。

    参数
    ----
    fs_series_hz : 串臂谐振器串联谐振频率（Hz），须 >0。
    f_area_ratio : 并臂频率映射旋钮（规格 §A-2 约定 fs_p=fs_series·√r），
        带通有效域 [1/(1+c), 1)：下界=带宽上限（fa_p=fs_s 对齐态），上界=
        带通判据（fs_p<fs_s）；缺省工作点建议 r=1/(1+c)（S21@fs_s=0dB）。
    n_sections : 节数（每节=串臂+并臂），≥1。
    f_grid : 频栅（Hz），1-D 非空有限正值；**内部升序排序后求值**（返回
        f_hz 与 abcd/s/network 全按排序栅格对齐）；恰落极点（pole_freqs_hz）
        的样本为 inf/nan，见模块 docstring「奇异点」。
    z0_ohm : 端接阻抗（Ω），>0，缺省 50。
    cm_c0_ratio : Cm/C0（无损 BVD 耦合度量），(0, 0.3]，缺省 0.08（AlN FBAR
        典型量级）；相对带宽上限 keff²·√(1+c) 随之而定。

    返回
    ----
    dict：abcd (nf,2,2)、s (nf,2,2)、network（skrf.Network，Touchstone 导出
    可用）、f_hz 与元数据（fs_shunt_hz=低侧零=通带下缘、fa_series_hz=高侧
    零=通带上缘、c0_f、keff2、bw_rel、bw_rel_max、pole_freqs_hz 等）。
    守卫策略与物理口径见模块 docstring（规格 §A-2；纯函数不进注册表，PK-1 同例）。
    """
    if not isinstance(n_sections, (int, np.integer)) or isinstance(n_sections, bool):
        raise ValueError(f"n_sections 须为整数，得 {type(n_sections).__name__}")
    n_sec = int(n_sections)
    if n_sec < 1:
        raise ValueError(f"n_sections 须 ≥1，得 {n_sections}")
    design = _validated_design(fs_series_hz, f_area_ratio, cm_c0_ratio, z0_ohm)
    f = np.sort(_validated_grid(f_grid))
    nf = f.size
    c0 = design["c0"]
    z0 = design["z0"]

    zs = baw_arm_impedance(f, design["fs_s"], design["fa_s"], c0)
    yp = baw_arm_admittance(f, design["fs_p"], design["fa_p"], c0)
    abcd = np.empty((nf, 2, 2), dtype=complex)
    with np.errstate(divide="ignore", invalid="ignore"):
        for i in range(nf):
            # 并臂矩阵逐字复用 metasurface_lut._abcd_shunt（导纳入参按 1/Y 还原阻抗）
            m_p = _abcd_shunt(1.0 / yp[i])
            section = _abcd_series(zs[i]) @ m_p
            total = section
            for _ in range(n_sec - 1):
                total = total @ section
            abcd[i] = total
    s = _abcd_to_s(abcd, z0)
    network = skrf.Network(
        frequency=skrf.Frequency.from_f(f, unit="hz"), s=s, z0=z0)
    out: dict[str, Any] = _design_metadata(design, n_sec)
    out.update({
        "abcd": abcd,
        "s": s,
        "network": network,
        "f_hz": f,
        "n_sections": n_sec,
    })
    return out


def lattice_variant(
    fs_series_hz: float,
    f_area_ratio: float,
    f_grid: np.ndarray,
    z0_ohm: float = 50.0,
    cm_c0_ratio: float = _DEFAULT_CM_C0_RATIO,
) -> dict[str, Any]:
    """BAW 格型（bridge）变体：四臂 Za=串臂谐振器、Zb=并臂谐振器，Zi=√(Za·Zb)。

    与梯形共用臂参数、带缘与全部守卫（模块 docstring；f_grid 同样内部升序
    排序）；单格型节，无节数。
    ABCD=(1/(1−t))·[[1+t,2Za],[2Yb,1+t]]（t=Za·Yb=Za/Zb，极点角点见模块
    docstring）；fs_s 对齐点 Za=0、Yb=0 → ABCD=I、S21≈1（ulp 级）。返回在
    梯形元数据基础上追加 zi（镜像阻抗 (nf,) complex，np.sqrt 主枝）。
    """
    design = _validated_design(fs_series_hz, f_area_ratio, cm_c0_ratio, z0_ohm)
    f = np.sort(_validated_grid(f_grid))
    nf = f.size
    c0 = design["c0"]
    z0 = design["z0"]

    za = baw_arm_impedance(f, design["fs_s"], design["fa_s"], c0)
    yb = baw_arm_admittance(f, design["fs_p"], design["fa_p"], c0)
    abcd = np.empty((nf, 2, 2), dtype=complex)
    with np.errstate(divide="ignore", invalid="ignore"):
        for i in range(nf):
            t = za[i] * yb[i]
            one_m = 1.0 - t
            m = np.empty((2, 2), dtype=complex)
            m[0, 0] = (1.0 + t) / one_m
            m[0, 1] = 2.0 * za[i] / one_m
            m[1, 0] = 2.0 * yb[i] / one_m
            m[1, 1] = m[0, 0]
            abcd[i] = m
        zi = np.sqrt(za / yb)  # Zi=√(Za·Zb)=√(Za/Yb)
    s = _abcd_to_s(abcd, z0)
    network = skrf.Network(
        frequency=skrf.Frequency.from_f(f, unit="hz"), s=s, z0=z0)
    out: dict[str, Any] = _design_metadata(design, 1)
    out.update({
        "abcd": abcd,
        "s": s,
        "network": network,
        "f_hz": f,
        "zi": zi,
    })
    return out
