"""补强⑩+SV-5 AFS 自适应频扫（伪误差自适应频扫）确定性内核。

历史口径（续跑计划 §10.20 补强清单第 10 行）：
    "AFS 自适应频扫：向量拟合（D13）驱动选频点，收敛即停——每频点一次
    FEM 求解、每次占席位，省席位-小时。HFSS 插值扫频同思路；skrf VF。
    验收：平行板/mline 案例频点数减半且 vs 全扫 FSV >= VG。"

SV-5 升级（规格深案 §C-4；算法逐式核到
arXiv 2504.09942v1 "Fully-Adaptive and Semi-Adaptive Frequency Sweep
Algorithm Exploiting Loewner-State Model for EM Simulation of Multiport
Systems"（Shilpa T. N. & Rakesh Sinha，IEEE TMTT 2025，
DOI 10.1109/TMTT.2025.3557208）——六步算法（原文式号随注）：

    ① 初始点（半自适应，Eq.13/14）：n0 = ceil(15*l*f_max/(p*c))
       （l=走线总长 m、p=端口数、c=3e8 m/s），频点按
       ``f0 = (2*fmax + fmin) - 10**linspace(log10(2*fmax),
       log10(fmax + fmin), n0)`` 对数密置高频（比均匀采样高频更密，
       原文 Fig.4/Table I 实证误差更低）；原文例：l=40mm、8GHz、2 端口
       → n0=8。``trace_length_m``/``n_ports`` 成对给定时点数走公式；
       未给时点数取 n_init、布点仍按 Eq.14（``init_mode=
       "log_dense_high"``，高频更密是该算法签名初始形态；midpoint 档
       保持均匀布点兼容旧语义）。
    ② Loewner 切向插值态空间模型（Eq.8/9 MFTI 矢量化 + Eq.15 even/odd
       分块含共轭增广 + Eq.16/17 SVD 截断 + Eq.19 定阶）；
    ③ 双模型 q1=8 / q2=12（Eq.19 奇异值累积能量比 > 1-10^-q）+ 频轴
       摄动 df=1e-5 Hz（H2 在 s'=j2pi(f+df) 求值）；
    ④ 伪误差（Eq.20）``E_pseu = ||H2(s') - H1(s)||_2 / ||H1(s)||_2``，
       谱范数 = 多响应（p×p 矩阵）联合判据（原文写平方比 |.|^2/|.|^2，
       |H|^2=max(sigma)，argmax 等价；本模块按范数比实现、dB 报告按
       20log10）；
    ⑤ ``f_new = argmax E_pseu``（Eq.21，在密集判分栅上、剔除既有采样
       点邻域）；
    ⑥ 连续 3 新点 E_act <= tol 才停（Algorithm-1 memory=3，超标清零；
       E_act 按 Eq.22 = ||H1(s_new) - H(s_new)||_2 / ||H(s_new)||_2）。

tol 口径改 dB（SV-5）：新键 ``tol_db`` 缺省 :data:`DEFAULT_TOL_DB` = -40 dB
（谱范数比的 20log10；与旧线性缺省 :data:`DEFAULT_TOL` = 1e-2 严格等价，
``tol`` 线性入参继续接受、内部换算）。计费口径不变：每次 evaluate 回调
= 1 次求解（solve 包装原样）。vs_full FSV 判分面零改（p=1 标量路径同
口径；p>1 矩阵路径逐元 FSV 取最差元进门，:func:`rfauto.core.fsv.fsv`
本体未动）。

多响应（2×2 联合收敛单门，§C-4 锚）：evaluate 返回 p×p 复数矩阵（或经
service 契约的嵌套列表）即进入矩阵模式；E_act/E_pseu 全程谱范数联合
单门，逐口 E_act 进 summary（``per_response_e_act_db``）只报告不进门
（谱范数掩盖弱口的如实披露，§C-4 风险条）。

算法边界（如实）
----------------
* 共轭增广（Eq.15 的 s̄k ↦ conj(H(fk))）对实有理 S 参数（EM 响应的
  Hermitian 对称性）是精确恒等式；对带非 Hermitian 成分的合成响应
  （带内余弦纹波等）是近似——模型被约束为实有理（Hermitian 对称），
  真实频率处的拟合由自适应环加点补偿（锚测试实证收敛）。
* odd 采样数：原文 Eq.15 的 odd 方案让 sa/sb 共享末点（同频插值点使
  Loewner 块 0/0 退化），本实现取"截偶"路线：odd n 只用前 n-1 个样本
  做 even/odd 分块（方阵、零退化；被舍样本保留在样本集，append 翻转
  奇偶后照常参与后续轮建模）。
* 估计器盲区（如实诊断，不改行为）：数据满数值秩时 Eq.19 双阶无截断差
  （原文自注"for small n, the parameter q does not have any effect"），
  E_pseu 退化为 df 斜率信号——按原文 Eq.20/21 照常选点（斜率峰=特征
  最陡处，实测合成纹波案例该信号仍把采样导向陷波沿/纹波陡区并收敛到
  FSV Ex），盲态记入 fit info（``blind`` 键）供上层诊断，不进门。
* 纯实/纯虚响应的偶对称退化（已知局限，如实暴露不粉饰）：增广数据集
  在 ±s_k 上携带相同值 → 插值条件重复 → 实现"插值样本点合格、样本间
  剧烈振荡"（E_act 逐轮 +N dB/-90 dB 振荡，收敛慢或不收敛）。复数
  S 参数（EM 响应的正常形态）不触发；插值残差守卫（_fit_pair，>0.5
  判构建失败走回退）只兜"采样点上就坏"的更重病态，管不住样本间振荡。
  纯实/纯虚载体（无耗 Z 参数族）建议先转复数口径再入 AFS。
* VF 回退档：Loewner 构建失败（病态/非有限，§C-4 风险条"SVD 截断+
  回退 VF"）时 SISO 回退 skrf VF（旧中点法拟合器原样保留）；回退档
  双模型 = 阶梯相邻两档（阶梯耗尽则同模型 df 摄动，伪误差退化为
  斜率选点语义）；矩阵响应无 VF 回退档（MFTI 本身吃全矩阵数据，失败
  如实 AFSError）。
* 旧"中点加密"主循环完整保留为 ``algorithm="midpoint"`` 档（对比锚：
  合成多谐振上新法 n_solves <= 0.7x 旧法的旧法基准面），缺省
  ``algorithm="loewner"``。
* 归一化：插值点按 s̃ = j*f/f_scale（f_scale=f_max）无量纲化进入
  Loewner 框架（数学上与原 s 域同一有理函数的精确重标度，改善 SVD
  条件数；原文 Table II 实测量纲 s 域条件数 ~1e13）。
* 真机验收（平行板/mline 频点减半 + HFSS/Palace 对拍，P3 真机窗）需
  真机批次执行；本模块单测以合成有理/非有理函数当真响应零仿真验证。

分层：core 层叶子，仅依赖 numpy + scikit-rf + 同层 core.fsv（与
core/macromodel.py 同口径）；无 IO、无随机、无墙钟。
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Callable
from typing import Any

import numpy as np
import skrf
from skrf.vectorFitting import VectorFitting

from rfauto.core.fsv import GRADE_CODES, fsv, grade_index_of

__all__ = [
    "DEFAULT_ORDER_LADDER",
    "DEFAULT_RMS_THRESHOLD_DB",
    "DEFAULT_TOL",
    "DEFAULT_TOL_DB",
    "DELTA_F_HZ",
    "LOEWNER_Q1",
    "LOEWNER_Q2",
    "MEMORY_LIMIT",
    "AFSError",
    "afs_initial_grid",
    "afs_sample",
]

#: 缺省确定性升阶阶梯（n_poles_real, n_poles_cmplx）。VF 档（回退面与
#: legacy midpoint 法）专用：谐振类 S 参数由复极点对主导，从 (0,1) 纯复
#: 极点档起步，逐级加档到 (4,8)。
DEFAULT_ORDER_LADDER: tuple[tuple[int, int], ...] = (
    (0, 1), (0, 2), (1, 2), (2, 4), (4, 8),
)
#: 样本点拟合 RMS（dB）达标阈值，与 macromodel 同款（VF 档专用）。
DEFAULT_RMS_THRESHOLD_DB = -40.0
#: 旧中点收敛容差（线性复幅差；保留为兼容别名：20*log10(1e-2)=-40 dB
#: 与 :data:`DEFAULT_TOL_DB` 严格等价）。
DEFAULT_TOL = 1e-2
#: SV-5 收敛容差缺省（dB，谱范数比 20log10 口径；Algorithm-1 tol）。
DEFAULT_TOL_DB = -40.0
#: 频轴摄动 df（Hz，原文 Eq.20 上下文："In this work, df = 1e-5 Hz"）。
DELTA_F_HZ = 1e-5
#: 双阶 SVD 定阶能量参数（原文 Eq.19：累积奇异值比 > 1-10^-q，q1=8/q2=12）。
LOEWNER_Q1 = 8
LOEWNER_Q2 = 12
#: 连续达标记忆（原文 Algorithm-1：memory < 3 终止条件，超标清零）。
MEMORY_LIMIT = 3
#: 光速（m/s，原文 Eq.13 口径 c = 3e8）。
_C_LIGHT = 3.0e8
#: 半自适应 n0 下限（防御电小结构的退化小模型；n0>=4 保证 even/odd 分块
#: 有意义的双阶差）。
_N0_FLOOR = 4
#: 复数 dB 地板（|S|=0 保护）。
_DB_FLOOR = 1e-30


class AFSError(Exception):
    """AFS 内核异常（拟合全败 / 参数非法 / 矩阵回退缺失）。"""


# --------------------------------------------------------------------------- #
# 通用小工具
# --------------------------------------------------------------------------- #


def _jsonify(value: Any) -> Any:
    """numpy -> JSON 原生（不改数值）。"""
    if isinstance(value, dict):
        return {str(k): _jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonify(v) for v in value]
    if isinstance(value, np.ndarray):
        return [_jsonify(v) for v in value.tolist()]
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


def _spec_norm(m: np.ndarray) -> float:
    """谱范数（最大奇异值；原文 |H|^2 = max(sigma) 的范数口径）。"""
    return float(np.linalg.norm(np.asarray(m, dtype=complex), ord=2))


def _to_db(ratio: float) -> float:
    """范数比 -> dB（零比保护）。"""
    return float(20.0 * math.log10(max(float(ratio), _DB_FLOOR)))


def _resolve_tol_db(tol: float | None, tol_db: float | None) -> float:
    """tol（线性，兼容）/ tol_db（SV-5 主口径）-> 有效 dB 容差。

    tol_db 显式给定时优先（SV-5 主口径）；否则 tol 线性换算
    （20*log10）；都缺省落 :data:`DEFAULT_TOL_DB`。bool 显式拒收
    （#140 数值入参族）。"""
    for name, value in (("tol", tol), ("tol_db", tol_db)):
        if isinstance(value, bool):
            raise AFSError(f"{name} 不接受 bool（数值入参显式拒收 bool）")
    if tol_db is not None:
        value = float(tol_db)
        if not math.isfinite(value):
            raise AFSError(f"tol_db 须为有限数，得到 {tol_db!r}")
        return value
    if tol is not None:
        value = float(tol)
        if not math.isfinite(value) or value <= 0.0:
            raise AFSError(f"tol 须为正有限数（线性域），得到 {tol!r}")
        return 20.0 * math.log10(value)
    return DEFAULT_TOL_DB


# --------------------------------------------------------------------------- #
# VF 拟合器（回退档 + legacy midpoint 法；原 _fit_best 逐字节保留）
# --------------------------------------------------------------------------- #


def _fit_best(
    freq: np.ndarray,
    s: np.ndarray,
    order_ladder: tuple[tuple[int, int], ...],
    rms_threshold_db: float,
) -> tuple[Callable[[np.ndarray], np.ndarray], dict[str, Any]]:
    """Hz 频轴上的向量拟合（确定性，先达标先停）。

    返回 ``(model, info)``：``model(frequencies_hz) -> complex array`` 是
    拟合好的模型响应求值器；``info`` 为拟合摘要。skrf VF 内部自带按平均
    频率的自归一化（实测 GHz 频段 Hz 轴拟合 ~1e-15 rms），不再额外做
    无量纲化（实测 [0,1] 归一轴反而让极点迁移退化，极点坍缩到原点）。
    阶梯从 (0,1) 起步：谐振类 S 参数由复极点对主导，先给纯复极点档，
    实极点档靠后（实测 (1,2) 起步会在单谐振系统上引入坏实极点）。
    skrf VF 的极点迁移 RuntimeWarning 捕获计数记入 attempts（不掩盖，
    阶梯按 RMS 取最优不受其影响）。

    SV-5 起本函数降为回退档（Loewner 病态时 SISO 回退）与 legacy
    ``algorithm="midpoint"`` 档的拟合器，主体六步算法走 :func:`_fit_pair`。
    """
    network = skrf.Network(
        frequency=np.asarray(freq, dtype=float), s=s, z0=50.0
    )
    attempts: list[dict[str, Any]] = []
    best: tuple[float, float, VectorFitting, int, int] | None = None
    for n_real, n_cmplx in order_ladder:
        vf = VectorFitting(network)
        warnings_history: list[str] = []
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", RuntimeWarning)
            try:
                vf.vector_fit(n_poles_real=n_real, n_poles_cmplx=n_cmplx)
            except Exception as exc:  # skrf 内部可抛 LinAlgError/ValueError，如实记录
                attempts.append(
                    {"n_poles_real": n_real, "n_poles_cmplx": n_cmplx,
                     "error": f"{type(exc).__name__}: {exc}"}
                )
                continue
            warnings_history = [str(w.message) for w in caught]
        s_fit = np.asarray(
            vf.get_model_response(0, 0, network.f), dtype=complex
        ).ravel()
        rms = float(np.sqrt(np.mean(np.abs(s - s_fit) ** 2)))
        rms_db = float(20.0 * np.log10(max(rms, _DB_FLOOR)))
        attempts.append(
            {"n_poles_real": n_real, "n_poles_cmplx": n_cmplx,
             "rms_db": rms_db, "passed": bool(rms_db <= rms_threshold_db),
             "n_vf_warnings": len(warnings_history)}
        )
        if best is None or rms < best[0]:
            best = (rms, rms_db, vf, n_real, n_cmplx)
        if rms_db <= rms_threshold_db:
            break
    if best is None:
        raise AFSError(f"所有阶数的向量拟合均失败: {attempts}")
    rms, rms_db, vf, n_real, n_cmplx = best

    def model(frequencies_hz: np.ndarray) -> np.ndarray:
        return np.asarray(
            vf.get_model_response(0, 0, np.asarray(frequencies_hz, dtype=float)),
            dtype=complex,
        ).ravel()

    info = {
        "n_poles_real": n_real,
        "n_poles_cmplx": n_cmplx,
        "n_poles_total": int(np.size(vf.poles)),
        "rms_db_at_samples": rms_db,
        "attempts": attempts,
    }
    return model, info


# --------------------------------------------------------------------------- #
# Loewner 双阶核（SV-5 六步之②③；arXiv 2504.09942v1 Eq.8/9/15-19）
# --------------------------------------------------------------------------- #


def _partition_even_odd(
    freqs_norm: np.ndarray, mats: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """even/odd 分块 + 共轭增广（原文 Eq.15；odd n 截偶路线，见模块 docstring）。

    返回 ``(sa, ha, sb, hb)``：右/左插值点（归一化 s̃ 域）与对应 p×p 响应。
    共轭点数据 ``H(s̄) := conj(H(f))``（实有理 EM 响应的精确恒等式；
    非 Hermitian 成分为近似，见模块 docstring 算法边界）。
    """
    n = freqs_norm.size
    if n % 2 == 1:  # 截偶：odd 方案的共享末点会产生 0/0 退化块（模块 docstring）
        freqs_norm = freqs_norm[: n - 1]
        mats = mats[: n - 1]
        n = freqs_norm.size
    idx_b = np.arange(0, n, 2)   # 1-based 奇数位：1,3,...
    idx_a = np.arange(1, n, 2)   # 1-based 偶数位：2,4,...
    s = 1j * freqs_norm
    sb = np.concatenate([s[idx_b], np.conj(s[idx_b])])
    hb = np.concatenate([mats[idx_b], np.conj(mats[idx_b])], axis=0)
    sa = np.concatenate([s[idx_a], np.conj(s[idx_a])])
    ha = np.concatenate([mats[idx_a], np.conj(mats[idx_a])], axis=0)
    return sa, ha, sb, hb


def _loewner_matrices(
    sa: np.ndarray, ha: np.ndarray, sb: np.ndarray, hb: np.ndarray, p: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """块 Loewner 矩阵（原文 Eq.9，MFTI 矢量化）与 B/C 数据面（Eq.8）。

    ``L_ij = (Ha_j - Hb_i)/(sa_j - sb_i)``、
    ``sL_ij = (sa_j*Ha_j - sb_i*Hb_i)/(sa_j - sb_i)``（p×p 块）；
    ``C = W = [Ha_1 ... Ha_na]``（p × na*p）、``B = V = [Hb_1;...;Hb_nb]``
    （nb*p × p）。"""
    denom = sa[None, :] - sb[:, None]                      # (nb, na)
    if not np.all(np.abs(denom) > 1e-14):
        raise ValueError("Loewner 分块出现重合插值点（sa_j == sb_i）")
    ha_j = ha[None, :, :, :]                               # (1, na, p, p)
    hb_i = hb[:, None, :, :]                               # (nb, 1, p, p)
    l_blocks = (ha_j - hb_i) / denom[:, :, None, None]
    sl_blocks = (sa[None, :, None, None] * ha_j - sb[:, None, None, None] * hb_i) \
        / denom[:, :, None, None]
    nb, na = denom.shape
    L = l_blocks.transpose(0, 2, 1, 3).reshape(nb * p, na * p)
    sL = sl_blocks.transpose(0, 2, 1, 3).reshape(nb * p, na * p)
    # C = W = [Ha_1 ... Ha_na] 横向块拼接：W[:, k*p:(k+1)*p] = Ha_k
    big_c = ha.transpose(1, 0, 2).reshape(p, na * p)
    # B = V = [Hb_1; ...; Hb_nb] 纵向块拼接：V[i*p:(i+1)*p, :] = Hb_i
    big_b = hb.reshape(nb * p, p)
    return L, sL, big_c, big_b


def _select_order(svals: np.ndarray, q: int) -> int:
    """SVD 截断定阶（原文 Eq.19）：最小 r 使累积奇异值比 > 1-10^-q。"""
    total = float(np.sum(svals))
    if not math.isfinite(total) or total <= 0.0:
        return 1
    cum = np.cumsum(svals) / total
    r = int(np.searchsorted(cum, 1.0 - 10.0 ** (-int(q)), side="right")) + 1
    return max(1, min(r, int(svals.size)))


def _loewner_model(
    freqs_norm: np.ndarray,
    mats: np.ndarray,
    f_scale: float,
    d_mat: np.ndarray,
    q: int,
) -> tuple[Callable[[np.ndarray], np.ndarray], dict[str, Any]]:
    """单阶 Loewner 有理模型（原文 Eq.15-19）：数据 -> 截断态空间 -> 求值器。

    返回 ``(model, info)``；``model(f_hz_array) -> (n, p, p)`` 复数矩阵
    （含 D 直通面：原文 Algorithm-1 的 H←H−D 入模、H←H+D 出模）。
    """
    p = d_mat.shape[0]
    sa, ha, sb, hb = _partition_even_odd(freqs_norm, mats - d_mat[None, :, :])
    L, sL, big_c, big_b = _loewner_matrices(sa, ha, sb, hb, p)
    # SVD 铅笔 P = x*L - sL（原文 Eq.16；x 取中位样本的归一化频率，
    # 原文口径"x 可为数据集中任一复频点、只需非铅笔特征值"）。
    x = 1j * float(freqs_norm[freqs_norm.size // 2])
    u_mat, svals, vh = np.linalg.svd(x * L - sL)
    r = _select_order(svals, q)
    r_max = int(min(u_mat.shape))
    xr = vh.conj().T[:, :r]        # X̂（原文 Eq.16 的 X 前 r 列）
    yr = u_mat[:, :r]              # Ŷ（原文 Eq.16 的 Y 前 r 列）
    yh = yr.conj().T
    e_r = -(yh @ L @ xr)           # 原文 Eq.17a
    a_r = -(yh @ sL @ xr)          # 原文 Eq.17b
    b_r = yh @ big_b               # 原文 Eq.17c
    c_r = big_c @ xr               # 原文 Eq.17d

    def model(frequencies_hz: np.ndarray) -> np.ndarray:
        f = np.atleast_1d(np.asarray(frequencies_hz, dtype=float))
        out = np.empty((f.size, p, p), dtype=complex)
        for k in range(f.size):
            st = 1j * f[k] / f_scale
            # Ĥr(s) = Ĉr (s Êr - Âr)^-1 B̂r + D（原文 Eq.18 + D 直通）
            out[k] = c_r @ np.linalg.solve(st * e_r - a_r, b_r) + d_mat
        return out

    used = float(np.sum(svals[:r]))
    total = float(np.sum(svals))
    info = {
        "r_order": int(r),
        "n_states": int(r),
        "r_max": r_max,
        "sv_energy_ratio": float(used / total) if total > 0 else 0.0,
        "q": int(q),
        "sv_top": float(svals[0]) if svals.size else 0.0,
        "partition": "even_odd_conjugate",
        "n_samples_in_model": int(freqs_norm.size - (freqs_norm.size % 2)),
    }
    return model, info


def _loewner_pair(
    freqs: np.ndarray,
    mats: np.ndarray,
    f_scale: float,
    d_mat: np.ndarray,
    q1: int,
    q2: int,
    delta_f_hz: float,
) -> tuple[Callable[[np.ndarray], np.ndarray], Callable[[np.ndarray], np.ndarray],
           dict[str, Any]]:
    """双阶 Loewner 模型对（六步之③）：r1(q1) 在 s、r2(q2) 在 s'=j2pi(f+df)。

    返回 ``(model1, model2, info)``；构建/求值异常向上抛（由
    :func:`_fit_pair` 决定回退或如实报错）。
    """
    freqs_norm = np.asarray(freqs, dtype=float) / f_scale
    model1, info1 = _loewner_model(freqs_norm, mats, f_scale, d_mat, q1)
    model2, info2 = _loewner_model(freqs_norm, mats, f_scale, d_mat, q2)

    def model2_perturbed(frequencies_hz: np.ndarray) -> np.ndarray:
        return model2(np.asarray(frequencies_hz, dtype=float) + delta_f_hz)

    info = {
        "method": "loewner",
        "r1": info1,
        "r2": info2,
        # 盲区诊断：双阶都取满（Eq.19 在小 n 下无截断差，原文自注"for
        # small n, the parameter q does not have any effect"）→ 伪误差
        # 退化为 df 斜率信号。按原文 Eq.20/21 照常选点（不改行为），
        # 盲态只作诊断报告（模块 docstring"估计器盲区"节）。
        "blind": bool(info1["r_order"] == info1["r_max"]
                      and info2["r_order"] == info2["r_max"]),
        "delta_f_hz": float(delta_f_hz),
        "q1": int(q1),
        "q2": int(q2),
    }
    return model1, model2_perturbed, info


def _fit_pair(
    grid: np.ndarray,
    mats: np.ndarray,
    *,
    f_scale: float,
    d_mat: np.ndarray,
    q1: int,
    q2: int,
    delta_f_hz: float,
    order_ladder: tuple[tuple[int, int], ...],
    fit_rms_threshold_db: float,
) -> tuple[Callable[[np.ndarray], np.ndarray], Callable[[np.ndarray], np.ndarray],
           dict[str, Any]]:
    """本轮双模型拟合器：Loewner 双阶核优先，SISO 病态回退 VF 档。

    返回 ``(model1, model2, info)``，二者均为 ``f_array -> (n, p, p)``。
    矩阵响应（p>1）Loewner 失败时如实 AFSError（无 VF 回退档，模块
    docstring 算法边界）。"""
    p = int(mats.shape[1])
    try:
        model1, model2, info = _loewner_pair(
            grid, mats, f_scale, d_mat, q1, q2, delta_f_hz)
        probe = model1(np.asarray(grid, dtype=float))
        if not np.all(np.isfinite(probe)):
            raise ValueError("Loewner 模型在采样点非有限")
        # 插值残差守卫：Eq.19 能量比截断的合法采样点残差 ~1e-8 级；>0.5 =
        # 结构性退化实现（纯实/纯虚响应的偶对称秩亏等，症状为逐轮质量
        # 剧烈振荡），按构建失败处理走回退/如实报错。
        den = np.maximum(
            np.array([_spec_norm(m) for m in mats]), _DB_FLOOR)
        rel = np.array(
            [_spec_norm(pm - m) for pm, m in zip(probe, mats, strict=True)]) / den
        if float(np.max(rel)) > 0.5:
            raise ValueError(
                f"Loewner 模型插值残差异常（max rel {float(np.max(rel)):.3g}，"
                "结构性退化）")
        return model1, model2, info
    except Exception as exc:
        if p > 1:
            raise AFSError(
                f"Loewner 构建失败且矩阵响应无 VF 回退档: "
                f"{type(exc).__name__}: {exc}") from exc
        # SISO 回退档：VF 阶梯最优档 + 下一档（耗尽则同模型 df 摄动）。
        s1 = mats[:, 0, 0]
        model1_1d, info_vf = _fit_best(
            grid, s1, order_ladder, fit_rms_threshold_db)

        def model1(freqs: np.ndarray) -> np.ndarray:
            return np.asarray(model1_1d(freqs), dtype=complex).reshape(-1, 1, 1)

        attempts = info_vf.get("attempts", [])
        idx_best = next(
            (i for i, a in enumerate(attempts) if a.get("passed")),
            max(len(attempts) - 1, 0))
        model2 = model1
        vf2_info: dict[str, Any] = {"mode": "delta_f_shift"}
        if idx_best + 1 < len(order_ladder):
            n_real, n_cmplx = order_ladder[idx_best + 1]
            try:
                model2_1d, _ = _fit_best(
                    grid, s1, ((n_real, n_cmplx),), fit_rms_threshold_db)

                def model2(freqs: np.ndarray) -> np.ndarray:
                    return np.asarray(model2_1d(freqs), dtype=complex) \
                        .reshape(-1, 1, 1)

                vf2_info = {"mode": "next_rung",
                            "n_poles_real": n_real, "n_poles_cmplx": n_cmplx}
            except Exception:  # 下一档拟合失败 -> 同模型 df 摄动（斜率选点语义）
                pass
        info = {
            "method": "vf_fallback",
            "loewner_error": f"{type(exc).__name__}: {exc}",
            "vf": info_vf,
            "vf_second_model": vf2_info,
            # 同模型 df 摄动档双模型无阶差 -> 盲区（诊断报告，见
            # _loewner_pair info["blind"] 注）
            "blind": bool(vf2_info.get("mode") == "delta_f_shift"),
        }
        return model1, model2, info


def _select_new_point(
    model1: Callable[[np.ndarray], np.ndarray],
    model2: Callable[[np.ndarray], np.ndarray],
    dense_grid: np.ndarray,
    existing: np.ndarray,
    delta_f_hz: float,
) -> tuple[float, float]:
    """伪误差选点（六步之④⑤，原文 Eq.20/21）。

    在密集判分栅上剔除既有采样点邻域（1e-12 相对带宽，浮点安全）后取
    ``argmax E_pseu``；判分栅耗尽/模型求值病态等退化场景回退既有采样点
    最大间隙中点（保证前进的确定性兜底）。返回 ``(f_new, e_pseu_db)``。

    注：双阶无截断差（blind，见 _loewner_pair info）时 E_pseu 退化为
    df 斜率信号——按原文口径照常使用（斜率峰=特征最陡处，选点仍有效；
    盲区只作 fit info 诊断报告，不改变算法行为）。"""
    def _gap_midpoint() -> float:
        se = np.sort(existing)
        if se.size >= 2:
            gaps = np.diff(se)
            k = int(np.argmax(gaps))
            return float(0.5 * (se[k] + se[k + 1]))
        return float(dense_grid[dense_grid.size // 2])

    band = float(dense_grid[-1] - dense_grid[0])
    eps = 1e-12 * band
    dist = np.abs(dense_grid[:, None] - existing[None, :]).min(axis=1)
    cand = dense_grid[dist > eps]
    if cand.size == 0:
        return _gap_midpoint(), float("inf")
    try:
        m1 = model1(cand)
        m2 = model2(cand + delta_f_hz)
        num = np.array([_spec_norm(b - a) for a, b in zip(m1, m2, strict=True)])
        den = np.maximum(np.array([_spec_norm(a) for a in m1]), _DB_FLOOR)
        epseu = num / den
    except Exception:  # 铅笔奇异等数值病态：退最大间隙中点（确定性兜底）
        return _gap_midpoint(), float("inf")
    epseu = np.where(np.isfinite(epseu), epseu, -np.inf)
    k = int(np.argmax(epseu))
    return float(cand[k]), _to_db(float(epseu[k]))


# --------------------------------------------------------------------------- #
# 主循环：伪误差选点（SV-5 六步缺省档）与中点加密（legacy 对比档）
# --------------------------------------------------------------------------- #


def _loop_pseudo_error(
    solve: Callable[[float], np.ndarray],
    samples: dict[float, np.ndarray],
    *,
    f_min: float,
    f_max: float,
    tol_db: float,
    max_points: int,
    max_rounds: int,
    n_dense: int,
    f_scale: float,
    d_mat: np.ndarray,
    q1: int,
    q2: int,
    delta_f_hz: float,
    order_ladder: tuple[tuple[int, int], ...],
    fit_rms_threshold_db: float,
) -> dict[str, Any]:
    """六步主循环（原文 Algorithm-1）：每轮双模型 -> 伪误差 argmax 一个
    新点 -> 求解计费 -> E_act 记忆 3 停机（超标清零）。"""
    dense_grid = np.linspace(f_min, f_max, int(n_dense))
    memory = 0
    e_series: list[float] = []
    epseu_series: list[float] = []
    per_response_last: list[list[float]] | None = None
    rounds = 0
    converged = False
    status = "max_rounds"
    fit_info: dict[str, Any] = {}
    for _ in range(int(max_rounds)):
        rounds += 1
        grid = np.array(sorted(samples))
        mats = np.array([samples[float(f)] for f in grid], dtype=complex)
        model1, model2, fit_info = _fit_pair(
            grid, mats, f_scale=f_scale, d_mat=d_mat, q1=q1, q2=q2,
            delta_f_hz=delta_f_hz, order_ladder=order_ladder,
            fit_rms_threshold_db=fit_rms_threshold_db)
        f_new, e_pseu_db = _select_new_point(
            model1, model2, dense_grid, grid, delta_f_hz)
        epseu_series.append(float(e_pseu_db))
        # 六步之⑥（原文 Eq.22）：新点真解 vs r1 模型，谱范数联合单门。
        h_new = solve(float(f_new))
        try:
            model_at_new = model1(np.array([float(f_new)]))[0]
            err = _spec_norm(model_at_new - h_new)
            denom = max(_spec_norm(h_new), _DB_FLOOR)
            e_act_db = _to_db(err / denom)
        except Exception:  # 模型求值病态：如实记发散（memory 清零，点照收）
            e_act_db = float("inf")
        e_series.append(e_act_db)
        if h_new.shape[0] > 1:
            per = np.abs(model_at_new - h_new) / np.maximum(
                np.abs(h_new), _DB_FLOOR)
            per_response_last = [
                [_to_db(float(v)) for v in row] for row in per]
        if e_act_db <= tol_db:
            memory += 1
        else:
            memory = 0
        samples[float(f_new)] = h_new
        if memory >= MEMORY_LIMIT:
            converged = True
            status = "converged"
            break
        if len(samples) >= int(max_points):
            status = "max_points"
            break
    return {
        "rounds": rounds,
        "converged": converged,
        "status": status,
        "e_act_db_series": e_series,
        "epseu_db_series": epseu_series,
        "per_response_e_act_db": per_response_last,
        "fit_info": fit_info,
    }


def _loop_midpoint(
    solve: Callable[[float], np.ndarray],
    samples: dict[float, np.ndarray],
    *,
    tol_linear: float,
    max_points: int,
    max_rounds: int,
    order_ladder: tuple[tuple[int, int], ...],
    fit_rms_threshold_db: float,
) -> dict[str, Any]:
    """legacy 中点加密主循环（SV-5 前的缺省算法，原 :229-247 原样保留）。

    仅 SISO（VF 拟合器单通道）；每轮对全部相邻中点做"模型预测 vs 真解"
    比对（每中点一次求解计费），超差中点入样加密，全过即停。保留面：
    新旧法 n_solves 对比锚（0.7x 基准）与 ``algorithm="midpoint"`` 消费者。"""
    converged = False
    status = "max_rounds"
    rounds = 0
    max_mid_error = float("inf")
    fit_info: dict[str, Any] = {}
    for _ in range(int(max_rounds)):
        rounds += 1
        grid = np.array(sorted(samples))
        s_vals = np.array([samples[float(f)][0, 0] for f in grid], dtype=complex)
        model, fit_info = _fit_best(grid, s_vals, order_ladder,
                                    fit_rms_threshold_db)
        mids = (grid[:-1] + grid[1:]) / 2.0
        if mids.size == 0:
            converged = True
            status = "converged"
            break
        model_at_mids = model(mids)
        errs: list[tuple[float, float, complex]] = []
        for mid, model_val in zip(mids, model_at_mids, strict=True):
            actual = solve(float(mid))[0, 0]
            errs.append((float(mid), abs(actual - model_val), actual))
        max_mid_error = max(e[1] for e in errs)
        failing = [(f, a) for f, err, a in errs if err > tol_linear]
        if not failing:
            converged = True
            status = "converged"
            break
        for f, actual in failing:
            samples[float(f)] = np.array([[actual]], dtype=complex)
        if len(samples) >= int(max_points):
            status = "max_points"
            break
    return {
        "rounds": rounds,
        "converged": converged,
        "status": status,
        "max_midpoint_error": max_mid_error,
        "fit_info": fit_info,
    }


# --------------------------------------------------------------------------- #
# 初始采样（六步之①：半自适应 Eq.13/14 或均匀）
# --------------------------------------------------------------------------- #


def _semi_adaptive_n0(
    trace_length_m: float, n_ports: int, f_max: float
) -> int:
    """初始点数（原文 Eq.13）：n0 = ceil(15*l*f_max/(p*c))，下限防御。"""
    n0 = math.ceil(15.0 * float(trace_length_m) * float(f_max)
                   / (float(n_ports) * _C_LIGHT))
    return max(int(n0), _N0_FLOOR)


def afs_initial_grid(f_min: float, f_max: float, n_points: int) -> np.ndarray:
    """初始频点布点（六步之①，原文 Eq.14）：对数密置高频。

    ``f0 = (2*fmax + fmin) - 10**linspace(log10(2*fmax),
    log10(fmax + fmin), n)``——两端精确落界、单调、高频更密。service
    plan 面与执行面共用本函数（单源防漂移）。"""
    n = int(n_points)
    if n < 2:
        raise AFSError(f"布点数须 >= 2，得到 {n_points!r}")
    u = np.linspace(math.log10(2.0 * f_max), math.log10(f_max + f_min), n)
    f0 = (2.0 * f_max + f_min) - np.power(10.0, u)
    f0 = np.clip(f0, f_min, f_max)
    return np.unique(f0)


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #


def afs_sample(
    evaluate: Callable[[float], Any],
    f_min: float,
    f_max: float,
    *,
    n_init: int = 7,
    tol: float | None = None,
    tol_db: float | None = None,
    max_points: int = 96,
    max_rounds: int = 12,
    order_ladder: tuple[tuple[int, int], ...] = DEFAULT_ORDER_LADDER,
    fit_rms_threshold_db: float = DEFAULT_RMS_THRESHOLD_DB,
    n_dense: int = 401,
    full_response: Callable[[np.ndarray], np.ndarray] | None = None,
    algorithm: str = "loewner",
    trace_length_m: float | None = None,
    n_ports: int | None = None,
) -> dict[str, Any]:
    """自适应选点采样 + Loewner 双阶核重建（SV-5 六步，确定性，零真机）。

    参数
    ----
    evaluate : 真响应回调 ``f_hz -> complex | (p,p) 复数矩阵``；每次调用
        计一次求解（计费口径不变）。矩阵即多响应联合单门模式。
    f_min, f_max : 频带（Hz，f_min < f_max）。
    n_init : 初始均匀采样点数（>= 3；``trace_length_m``/``n_ports`` 给定
        时被半自适应公式取代）。
    tol : 旧线性容差（复幅差/谱范数比）；与 ``tol_db`` 二选一，都给时
        ``tol_db`` 优先；都缺省落 -40 dB。
    tol_db : SV-5 主口径容差（dB，20log10 谱范数比；Algorithm-1 tol）。
    max_points / max_rounds : 终止保护（触发时 status 如实标注未收敛）。
    order_ladder / fit_rms_threshold_db : VF 回退档定阶阶梯与 RMS 阈值。
    n_dense : 重建/判分/伪误差选点的密集频轴点数。
    full_response : 可选全扫参考；标量形 ``freqs -> (n,)``（*不计入*
        solve 计费），提供时 summary 附 ``vs_full``（FSV 裁判，判分面
        零改）；矩阵形 ``freqs -> (n, p, p)`` 走逐元 FSV 最差元进门。
    algorithm : ``"loewner"``（SV-5 缺省六步）| ``"midpoint"``（legacy
        中点加密，仅 SISO；新旧法对比基准面）。
    trace_length_m / n_ports : 半自适应初始点（原文 Eq.13/14）的走线总长
        （m）与端口数；二者必须成对给定，给定后 n0 公式取代 ``n_init``。

    返回
    ----
    JSON 原生 dict：solve 计费（n_solves）、采样点（frequencies_hz）、
    收敛状态、逐轮 E_act（e_act_db_series）、拟合阶（fit：Loewner
    r1/r2 或 VF 档）、密集重建（dense）、以及 ``vs_full`` 中的缩减比与
    FSV 等级（full_response 提供时）。
    """
    f_min_f = float(f_min)
    f_max_f = float(f_max)
    if not (np.isfinite(f_min_f) and np.isfinite(f_max_f)) or not f_max_f > f_min_f:
        raise AFSError(f"频带非法: [{f_min!r}, {f_max!r}]")
    if not callable(evaluate):
        raise AFSError("evaluate 必须为可调用对象 f_hz -> complex")
    n_init = int(n_init)
    if n_init < 3:
        raise AFSError(f"n_init 必须 >= 3，得到 {n_init}")
    algo = str(algorithm)
    if algo not in ("loewner", "midpoint"):
        raise AFSError(f"algorithm 须为 'loewner' | 'midpoint'，得到 {algorithm!r}")

    semi = (trace_length_m is not None) or (n_ports is not None)
    if semi and (trace_length_m is None or n_ports is None):
        raise AFSError(
            "半自适应初始点须成对给定 trace_length_m 与 n_ports"
            "（原文 Eq.13 需 l 与 p）")
    init_mode = "uniform"
    if semi:
        if isinstance(trace_length_m, bool) or isinstance(n_ports, bool):
            raise AFSError("trace_length_m/n_ports 不接受 bool")
        l_m = float(trace_length_m)  # type: ignore[arg-type]
        p_user = int(n_ports)  # type: ignore[arg-type]
        if not math.isfinite(l_m) or l_m <= 0.0:
            raise AFSError(f"trace_length_m 须为正有限数，得到 {trace_length_m!r}")
        if p_user < 1:
            raise AFSError(f"n_ports 须 >= 1，得到 {n_ports!r}")
        n0 = _semi_adaptive_n0(l_m, p_user, f_max_f)
        freqs = afs_initial_grid(f_min_f, f_max_f, n0)
        init_mode = "semi_adaptive_electrical_size"
    elif algo == "loewner":
        # 六步之①布点形态：对数密置高频（原文 Eq.14；电尺寸未给时点数
        # 取 n_init、布点仍按 Eq.14——高频更密是该算法的签名初始形态）。
        freqs = afs_initial_grid(f_min_f, f_max_f, n_init)
        init_mode = "log_dense_high"
    else:
        freqs = np.linspace(f_min_f, f_max_f, n_init)

    if int(max_points) < int(freqs.size):
        raise AFSError(
            f"max_points({max_points}) 不能小于初始采样点数({freqs.size})")

    eff_tol_db = _resolve_tol_db(tol, tol_db)
    tol_linear = float(10.0 ** (eff_tol_db / 20.0))

    solves = 0
    port_count: int | None = None

    def solve(f: float) -> np.ndarray:
        """计费包装（口径不变：每次回调 = 1 次求解）+ 矩阵形归一。"""
        nonlocal solves, port_count
        solves += 1
        val = evaluate(float(f))
        arr = np.asarray(val, dtype=complex)
        if arr.ndim == 0:
            m = np.array([[complex(arr)]], dtype=complex)
        elif arr.ndim == 2 and arr.shape[0] == arr.shape[1] and arr.shape[0] >= 1:
            m = arr.astype(complex, copy=True)
        elif arr.ndim == 1 and arr.size == 1:
            m = arr.astype(complex, copy=True).reshape(1, 1)
        else:
            raise AFSError(
                f"evaluate({f!r}) 返回须为标量复数或 p×p 复数矩阵，"
                f"得到 shape {arr.shape}")
        if port_count is None:
            port_count = int(m.shape[0])
        elif int(m.shape[0]) != port_count:
            raise AFSError(
                f"evaluate 端口数不一致：首轮 {port_count}，"
                f"f={f!r} 处 {m.shape[0]}")
        return m

    samples: dict[float, np.ndarray] = {float(f): solve(f) for f in freqs}
    p = int(port_count or 1)
    d_mat = np.ones((p, p), dtype=complex)  # 原文 Algorithm-1：D=ones 直通面
    f_scale = f_max_f

    if algo == "midpoint":
        if p > 1:
            raise AFSError("algorithm='midpoint' 仅支持 SISO（VF 单通道）")
        loop = _loop_midpoint(
            solve, samples, tol_linear=tol_linear, max_points=int(max_points),
            max_rounds=int(max_rounds), order_ladder=order_ladder,
            fit_rms_threshold_db=float(fit_rms_threshold_db))
        model1d, fit_info = _fit_best(
            np.array(sorted(samples)),
            np.array([samples[float(f)][0, 0] for f in sorted(samples)],
                     dtype=complex),
            order_ladder, float(fit_rms_threshold_db))
        dense_model = np.asarray(
            model1d(np.linspace(f_min_f, f_max_f, int(n_dense))),
            dtype=complex).ravel()
        fit_out = fit_info
        per_response = None
    else:
        loop = _loop_pseudo_error(
            solve, samples, f_min=f_min_f, f_max=f_max_f, tol_db=eff_tol_db,
            max_points=int(max_points), max_rounds=int(max_rounds),
            n_dense=int(n_dense), f_scale=f_scale, d_mat=d_mat,
            q1=LOEWNER_Q1, q2=LOEWNER_Q2, delta_f_hz=DELTA_F_HZ,
            order_ladder=order_ladder,
            fit_rms_threshold_db=float(fit_rms_threshold_db))
        # 终模型重建（原文 Algorithm-1 尾部：停机后以 r1 重建 H(f)）。
        grid = np.array(sorted(samples))
        mats = np.array([samples[float(f)] for f in grid], dtype=complex)
        model_final, _, fit_out = _fit_pair(
            grid, mats, f_scale=f_scale, d_mat=d_mat, q1=LOEWNER_Q1,
            q2=LOEWNER_Q2, delta_f_hz=DELTA_F_HZ, order_ladder=order_ladder,
            fit_rms_threshold_db=float(fit_rms_threshold_db))
        dense_model = model_final(np.linspace(f_min_f, f_max_f, int(n_dense)))
        if p == 1:
            dense_model = dense_model.reshape(-1)
        per_response = loop.get("per_response_e_act_db")

    rounds = int(loop["rounds"])
    status = str(loop["status"])
    converged = bool(loop["converged"])
    # midpoint 档无逐轮 E_act 记账（其误差面是每轮全体中点，见
    # max_midpoint_error）；置空保持 summary 键集稳定。
    e_series = list(loop.get("e_act_db_series", []))

    dense_freq = np.linspace(f_min_f, f_max_f, int(n_dense))
    matrix_mode = p > 1

    summary: dict[str, Any] = {
        "status": status,
        "converged": converged,
        "algorithm": algo,
        "init_mode": init_mode,
        "tol": float(10.0 ** (eff_tol_db / 20.0)),
        "tol_db": float(eff_tol_db),
        "n_init": int(freqs.size),
        "rounds": rounds,
        "n_solves": solves,
        "n_accepted": len(samples),
        "frequencies_hz": [float(f) for f in sorted(samples)],
        "e_act_db_series": e_series,
        "e_act_db_last": e_series[-1] if e_series else None,
        "max_actual_error_db": max(e_series) if e_series else None,
        # 兼容消费面（CLI _afs_sweep_summary）：新算法语义 = 被采纳新点上的
        # 最大线性 E_act；midpoint 档保持旧中点误差语义。
        "max_midpoint_error": (
            loop.get("max_midpoint_error") if algo == "midpoint"
            else max((10.0 ** (db / 20.0) for db in e_series), default=None)),
        "fit": fit_out,
        "dense": {
            "n_points": int(n_dense),
            "freq_hz": [float(f) for f in dense_freq],
            "s_model": (
                [[[[float(c.real), float(c.imag)] for c in row]
                  for row in block] for block in dense_model]
                if matrix_mode else
                [[float(v.real), float(v.imag)] for v in dense_model]
            ),
        },
    }
    if matrix_mode:
        summary["dense"]["shape"] = [int(n_dense), p, p]
        summary["n_ports"] = p
        if per_response is not None:
            summary["per_response_e_act_db"] = per_response
    if init_mode == "semi_adaptive_electrical_size":
        summary["n0_formula"] = {
            "trace_length_m": float(trace_length_m),  # type: ignore[arg-type]
            "n_ports": int(n_ports),  # type: ignore[arg-type]
            "c_light_m_s": _C_LIGHT,
            "n0": int(freqs.size),
        }

    if full_response is not None:
        dense_true = np.asarray(full_response(dense_freq), dtype=complex)
        if matrix_mode:
            if dense_true.shape != (int(n_dense), p, p):
                raise AFSError(
                    f"full_response 返回形状须为 ({n_dense}, {p}, {p})，"
                    f"得到 {dense_true.shape}")
            abs_err = np.abs(dense_true - dense_model)
            per_entry = []
            for i in range(p):
                for j in range(p):
                    mag_t = 20.0 * np.log10(np.maximum(
                        np.abs(dense_true[:, i, j]), _DB_FLOOR))
                    mag_m = 20.0 * np.log10(np.maximum(
                        np.abs(dense_model[:, i, j]), _DB_FLOOR))
                    fr = fsv(dense_freq, mag_t, dense_freq, mag_m)
                    gi = grade_index_of(float(fr["gdm_mean"]))
                    per_entry.append({
                        "row": i, "col": j,
                        "gdm_mean": float(fr["gdm_mean"]),
                        "gdm_grade": fr["gdm_grade"],
                        "gdm_grade_level": int(fr["gdm_grade_level"]),
                        "at_least_vg": bool(gi <= 1),
                        "fsv": {
                            "adm_mean": float(fr["adm_mean"]),
                            "fdm_mean_abs": float(fr["fdm_mean_abs"]),
                            "gdm_mean": float(fr["gdm_mean"]),
                            "adm_grade": fr["adm_grade"],
                            "fdm_grade": fr["fdm_grade"],
                            "gdm_grade": fr["gdm_grade"],
                            "gdm_grade_level": int(fr["gdm_grade_level"]),
                            "gdm_spread": int(fr["gdm_spread"]),
                            "at_least_vg": bool(gi <= 1),
                            "at_least_good": bool(gi <= 2),
                            "scale": GRADE_CODES,
                        },
                    })
            worst = max(per_entry, key=lambda e: e["gdm_mean"])
            summary["vs_full"] = {
                "n_full": int(n_dense),
                "n_solves": solves,
                "reduction_ratio": float(1.0 - solves / float(n_dense)),
                "max_abs_err": float(np.max(abs_err)),
                "rms_abs_err": float(np.sqrt(np.mean(abs_err**2))),
                "shape": [int(n_dense), p, p],
                "aggregate": "worst_entry",
                "fsv": {**worst["fsv"], "entry": [worst["row"], worst["col"]]},
                "per_entry": [
                    {k: v for k, v in e.items() if k != "fsv"}
                    for e in per_entry
                ],
            }
        else:
            dense_true = dense_true.ravel()
            if dense_true.size != dense_freq.size:
                raise AFSError("full_response 返回长度与密集频轴不一致")
            abs_err = np.abs(dense_true - dense_model)
            rms = float(np.sqrt(np.mean(abs_err**2)))
            mag_true_db = 20.0 * np.log10(np.maximum(np.abs(dense_true), _DB_FLOOR))
            mag_model_db = 20.0 * np.log10(np.maximum(np.abs(dense_model), _DB_FLOOR))
            fsv_result = fsv(dense_freq, mag_true_db, dense_freq, mag_model_db)
            gdm_grade_index = grade_index_of(float(fsv_result["gdm_mean"]))
            summary["vs_full"] = {
                "n_full": int(n_dense),
                "n_solves": solves,
                "reduction_ratio": float(1.0 - solves / float(n_dense)),
                "max_abs_err": float(np.max(abs_err)),
                "rms_abs_err": rms,
                "fsv": {
                    "adm_mean": float(fsv_result["adm_mean"]),
                    "fdm_mean_abs": float(fsv_result["fdm_mean_abs"]),
                    "gdm_mean": float(fsv_result["gdm_mean"]),
                    "adm_grade": fsv_result["adm_grade"],
                    "fdm_grade": fsv_result["fdm_grade"],
                    "gdm_grade": fsv_result["gdm_grade"],
                    "gdm_grade_level": int(fsv_result["gdm_grade_level"]),
                    "gdm_spread": int(fsv_result["gdm_spread"]),
                    # §10.20 补强⑩验收口径：vs 全扫 FSV >= VG（等级下标 <= 1）；
                    # >= Good（下标 <= 2）一并给出供放宽口径使用。
                    "at_least_vg": bool(gdm_grade_index <= 1),
                    "at_least_good": bool(gdm_grade_index <= 2),
                    "scale": GRADE_CODES,
                },
            }
    return _jsonify(summary)
