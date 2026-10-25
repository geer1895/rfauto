"""multiline TRL εr/tan_d 不确定度传播（EC-2，aurora_e W2-S9，2026-10-18）。

出处（不确定度传播规范+多线 TRL 文献，正文方法面节转录）：
- mtrl_er_tand_uncertainty：GUM 一阶线性传播（JCGM 100:2008）+
  蒙特卡洛对照方法学（JCGM 101）；multiline TRL 主对模型（R. B. Marks,
  "A multiline method of network analyzer calibration", IEEE Trans.
  MTT 39(7), 1991；DeGroot-Jargon-Marks 2002 完整协方差属上游面外，
  主对一阶只宽不窄如实声明）。

方法面（任务口径："multiline TRL 的 εr/tan_d 提取不确定度传播（GUM 律）"
——输入=TRL 标准件尺寸公差/线损测量噪声，输出=εr/tan_d 带区间，喂锚 gate）
--------------------------------------------------------------------------
- **GUM 一阶线性传播**（JCGM 100:2008）：γ→(εr, tanδ) 链对两类输入的
  一阶敏感度合成。
- **蒙特卡洛对照**（JCGM 101 方法学 + #118 双来源纪律）：合成 mTRL 夹具
  （skrf MLine 解析正向，与 dielectric_extract G1 同口径）加性扰动全链
  重提，经验带覆盖 GUM 区间 ≥95% 为验证门。

不确定度通道（docstring 写死，一阶主对模型）
--------------------------------------------
mTRL 的 β 由线对差分相位提取（NIST 多线全对最小二乘的一阶主项=最长-最短
线对，**主对模型如实声明**；DeGroot-Jargon-Marks 2002 算法的完整协方差
传播属上游 skrf 面外）：

- **尺寸公差通道**：β ≈ Δφ/ΔL（ΔL=主对线长差）→ u_β_L = β·u_c，
  u_c = u_ΔL/ΔL，u_ΔL = sqrt(u_L1²+u_L2²)（逐线独立）；α 通道同型
  u_α_L = α·u_c。
- **测量噪声通道**：加性复高斯噪声（逐分量 std σ_S）下线相位误差 std
  ≈ σ_S/|S21| = σ_S·e^{αL}，线对差分 σ_Δφ = σ_S·sqrt(e^{2αL1}+e^{2αL2})
  → u_β_n = σ_Δφ/ΔL（α 通道同型：α=−ln|S21|/L 的 **ln 域**幅度误差 std
  同为 σ_S/|S21| = σ_S·e^{αL}——线性域 |S21| 绝对扰动 σ_S 勿读作"α 通道
  不加 e^{αL} 放大"；u_α 噪声项与相位通道同取 σ_Δφ/ΔL，实现同项入 RSS）。
- **相关传播修正（tand 长度通道）**：Δα 与 Δβ 由**同一** ΔL 相对误差
  c 驱动（完全相关，一阶 Δα=α·c、Δβ=β·c），tanδ ≈ 2α_d/(β·q) 的
  ∂t/∂β·β 与 ∂t/∂α·α 反号相消—— tand 长度通道必须用**组合系数**
  |∂t/∂β·β + ∂t/∂α·α|·u_c，逐项 RSS 会高估一个量级（合成夹具实测
  10×；二阶残差=经 er(β)→q(εr) 的弱耦合）。噪声通道 β/α 驱动源不同
  （相位/幅度正交分量），按独立 RSS（声明）。
- 链传播（数值中心差分敏感度，经 dielectric_extract 反演单源）：
  u(εeff)/εeff = 2·u_β/β（**精确恒等式**，εeff=(βc/ω)² 平方律）；
  u(εr) = |∂er/∂β|·u_β（er 只依赖 β）。
- **单误差项支配渐近式**（任务口径）：尺寸公差支配时 u(εeff)/εeff →
  2·u_ΔL/ΔL（精确）；噪声支配时 u(εeff)/εeff → 2·σ_Δφ/(β·ΔL)。逐频点
  报 dominant_channel 与两通道分解。
- **保守性声明（预声明，#122）**：主对一阶模型不含 NIST 多线全对
  最小二乘的方差稀释，**只宽不窄**——合成夹具实测 GUM/MC 标准差比
  1.4~3.5（er/tand 双链×3 频点参考夹具实测，2026-10-18，固定 seed
  20261018/n=150）；对锚 gate 消费该方向安全（判据带宁宽勿窄）。需要
  紧带时消费 MC 块经验 std（固定 seed 完全可复现）。

锚 gate 消费建议（任务口径）
----------------------------
锚 gate/verdict 消费 ``u_er_gum``/``u_tand_gum`` 的 k=2 区间作判据带宽
（G4 语义）：达标判据比较"标称值 ± 2u 与锚值"——带内=AGREE_WITH_ANCHOR；
u(εr)/εr 与 u(tanδ)/tanδ 的相对量与 dominant_channel 一起入 provenance
（公差预算归因抓手）。注册键 ``mtrl_er_tand_uncertainty`` 即该消费面。

判据预声明（先写后跑，#122；测试=tests/unit/test_aurora_e_s9_mtrl_uc.py）
------------------------------------------------------------------------
- G4-MC 门：k=2 GUM 区间对 MC 抽样的覆盖率 ≥95%（JCGM 101 验证语义）；
- GUM/MC 标准差比 ∈ [1.0, 4.0]（下界=带不窄于经验 std 的保守方向
  声明，上界=保守倍数上限；主对模型不含多线全对方差稀释——实测
  1.4~3.5）；
- εeff 通道恒等式：长度通道 u(εeff)/εeff = 2·u_ΔL/ΔL 逐位；
- 名义链合成回收 = 机器精度（er/tanδ 回收，dielectric_extract G1 同款）。

无 ``__all__``（公开 API 快照口径，taper_classic.py 先例）。
时谐约定：γ = α + jβ（e^{+jωt}），α≥0、β≥0（dielectric_extract 同口径）。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from rfauto.core.dielectric_extract import (
    C0,
    er_eff_to_er,
    extract_er_tand_profile,
    extract_gamma_mtrl,
    tan_d_from_alpha_d,
)

from .registry import register_calculator

_MC_DEFAULT_SEED = 20261018
#: GUM/MC 标准差比预声明域：**下界 1.0 = 带不窄于经验 std（保守方向，
#: 见 docstring 保守性声明——主对模型不含多线全对方差稀释）**；上界 4.0
#: = 保守倍数声明上限（参考夹具 3 频点×er/tand 双链实测 1.4~3.5，取整
#: 留裕量）。偏离即模型域外如实红（不凑绿）。
_MC_RATIO_RANGE = (1.0, 4.0)
#: G4-MC 覆盖率门（k=2 区间，JCGM 101 验证语义）
_COVERAGE_MIN = 0.95


def _forward_beta_alpha(
    f_hz: float, w_mm: float, h_mm: float, er: float, tan_d: float,
) -> tuple[float, float]:
    """名义正向 β/α（skrf MLine HJ 口径，t=0 无耗导体=纯介质损耗）。"""
    import skrf
    from skrf.media import MLine

    m = MLine(
        frequency=skrf.Frequency(float(f_hz), float(f_hz), 1, unit="Hz"),
        w=float(w_mm) * 1e-3,
        h=float(h_mm) * 1e-3,
        ep_r=float(er),
        tand=float(tan_d),
        model="hammerstadjensen",
    )
    beta = 2.0 * math.pi * float(f_hz) * math.sqrt(
        float(np.real(m.ep_reff_f[0]))) / C0
    alpha = float(np.real(m.alpha_dielectric[0]))
    return beta, alpha


def _er_of_beta(beta: float, f_hz: float, w_mm: float, h_mm: float,
                tan_d: float) -> float:
    """β→εr 提取链（er_eff_to_er 反演单源）。"""
    omega = 2.0 * math.pi * float(f_hz)
    er_eff = (float(beta) * C0 / omega) ** 2
    return er_eff_to_er(er_eff, w_mm, h_mm, f_hz, tand=tan_d)


def _tand_of(beta: float, alpha: float, f_hz: float, w_mm: float,
             h_mm: float) -> float:
    """(β, α)→tanδ 提取链（er(β) 耦合 + tan_d_from_alpha_d 反演单源）。"""
    er_i = _er_of_beta(beta, f_hz, w_mm, h_mm, 0.0)
    return tan_d_from_alpha_d(float(alpha), w_mm, h_mm, f_hz, er_i)


def _parse_lengths(
    line_lengths_m: Any, u_lengths_m: Any, tag: str,
) -> tuple[list[float], list[float]]:
    if not isinstance(line_lengths_m, (list, tuple)) or \
            len(line_lengths_m) < 2:
        raise ValueError(
            f"{tag}: line_lengths_m 须为 ≥2 元素 list（mTRL 至少两根不同"
            f"长度线），得到 {line_lengths_m!r}")
    lengths = [float(v) for v in line_lengths_m]
    if any(not math.isfinite(v) or v <= 0.0 for v in lengths):
        raise ValueError(f"{tag}: 线长必须 >0 有限，得到 {lengths!r}")
    if len(set(lengths)) != len(lengths):
        raise ValueError(f"{tag}: 线长必须互异（mTRL 主对要求 ΔL>0）")
    if u_lengths_m is None:
        raise ValueError(f"{tag}: u_lengths_m 必填（逐线长度标准不确定度）")
    if isinstance(u_lengths_m, (int, float)) and \
            not isinstance(u_lengths_m, bool):
        u_list = [float(u_lengths_m)] * len(lengths)
    elif isinstance(u_lengths_m, (list, tuple)):
        u_list = [float(v) for v in u_lengths_m]
        if len(u_list) != len(lengths):
            raise ValueError(
                f"{tag}: u_lengths_m 元素数 {len(u_list)} 与线数 "
                f"{len(lengths)} 不一致")
    else:
        raise ValueError(
            f"{tag}: u_lengths_m 须为标量或逐线 list，得到 {u_lengths_m!r}")
    if any(not math.isfinite(v) or v < 0.0 for v in u_list):
        raise ValueError(f"{tag}: 长度标准不确定度必须 >=0 有限，得到 {u_list!r}")
    return lengths, u_list


def mtrl_er_tand_gum(
    f_hz: Any,
    w_mm: float,
    h_mm: float,
    er: float,
    tan_d: float,
    line_lengths_m: Any,
    u_lengths_m: Any,
    sigma_s: float,
) -> dict[str, Any]:
    """GUM 一阶线性传播核（逐频点；无 MC——MC 见 mtrl_er_tand_montecarlo）。

    Returns:
        dict: 逐频数组 {freq_hz, beta_rad_m, alpha_np_m, er_eff, er_nom,
        tan_d_nom, u_beta, u_alpha, u_er_gum, u_tand_gum,
        u_er_channel_length, u_er_channel_noise, u_eps_eff_rel,
        u_eps_eff_rel_length, u_eps_eff_rel_noise, dominant_channel}
        + 口径元数据（u_delta_l、sigma_dphi、主对线长、声明注记）。
    """
    tag = "mtrl_er_tand_gum"
    f_arr = np.atleast_1d(np.asarray(f_hz, dtype=float))
    if f_arr.size == 0 or np.any(f_arr <= 0.0) or \
            not np.all(np.isfinite(f_arr)):
        raise ValueError(f"{tag}: freq_hz 须为非空正有限数组，得到 {f_hz!r}")
    for name, val in (("w_mm", w_mm), ("h_mm", h_mm), ("er", er),
                      ("tan_d", tan_d)):
        if isinstance(val, bool) or not math.isfinite(float(val)) \
                or float(val) <= 0.0:
            raise ValueError(f"{tag}: {name} 必须 >0 有限，得到 {val!r}")
    if isinstance(sigma_s, bool) or not math.isfinite(float(sigma_s)) \
            or float(sigma_s) < 0.0:
        raise ValueError(
            f"{tag}: sigma_s（S 参数逐分量噪声 std）必须 >=0 有限，"
            f"得到 {sigma_s!r}")
    lengths, u_list = _parse_lengths(line_lengths_m, u_lengths_m, tag)
    # 主对=最长-最短线（NIST 多线一阶主项；声明见模块 docstring）
    i_min = int(np.argmin(lengths))
    i_max = int(np.argmax(lengths))
    dl = lengths[i_max] - lengths[i_min]
    u_dl = math.sqrt(u_list[i_min] ** 2 + u_list[i_max] ** 2)

    n = f_arr.size
    out = {
        "freq_hz": f_arr.copy(),
        "beta_rad_m": np.empty(n),
        "alpha_np_m": np.empty(n),
        "er_eff": np.empty(n),
        "er_nom": np.empty(n),
        "tan_d_nom": np.empty(n),
        "u_beta": np.empty(n),
        "u_alpha": np.empty(n),
        "u_er_gum": np.empty(n),
        "u_tand_gum": np.empty(n),
        "u_er_channel_length": np.empty(n),
        "u_er_channel_noise": np.empty(n),
        "u_eps_eff_rel": np.empty(n),
        "u_eps_eff_rel_length": np.empty(n),
        "u_eps_eff_rel_noise": np.empty(n),
        "dominant_channel": [],
    }
    for i, f in enumerate(f_arr):
        beta, alpha = _forward_beta_alpha(float(f), w_mm, h_mm, er, tan_d)
        sigma_dphi = float(sigma_s) * math.sqrt(
            math.exp(2.0 * alpha * lengths[i_min])
            + math.exp(2.0 * alpha * lengths[i_max]))
        u_beta = math.sqrt((beta * u_dl / dl) ** 2 + (sigma_dphi / dl) ** 2)
        u_alpha = math.sqrt((alpha * u_dl / dl) ** 2 + (sigma_dphi / dl) ** 2)
        er_eff = (beta * C0 / (2.0 * math.pi * float(f))) ** 2
        # 数值中心差分敏感度（步长=1e-6 相对；反演单调光滑域）
        h_beta = 1e-6 * beta
        h_alpha = 1e-6 * max(alpha, 1e-12)
        der_dbeta = (_er_of_beta(beta + h_beta, float(f), w_mm, h_mm, tan_d)
                     - _er_of_beta(beta - h_beta, float(f), w_mm, h_mm,
                                   tan_d)) / (2.0 * h_beta)
        dt_dbeta = (_tand_of(beta + h_beta, alpha, float(f), w_mm, h_mm)
                    - _tand_of(beta - h_beta, alpha, float(f), w_mm, h_mm)
                    ) / (2.0 * h_beta)
        dt_dalpha = (_tand_of(beta, alpha + h_alpha, float(f), w_mm, h_mm)
                     - _tand_of(beta, alpha - h_alpha, float(f), w_mm, h_mm)
                     ) / (2.0 * h_alpha)
        u_er_length = abs(der_dbeta) * beta * u_dl / dl
        u_er_noise = abs(der_dbeta) * sigma_dphi / dl
        u_er = math.sqrt(u_er_length ** 2 + u_er_noise ** 2)
        # tand 长度通道：Δα/Δβ 由同一 ΔL 相对误差 c 完全相关驱动——
        # 组合系数（∂t/∂β·β 与 ∂t/∂α·α 反号相消，见模块 docstring）
        comb_len = dt_dbeta * beta + dt_dalpha * alpha
        u_td_len = abs(comb_len) * u_dl / dl
        # 噪声通道：β/α 噪声驱动源正交（相位/幅度），独立 RSS（声明）
        u_td_noise = (sigma_dphi / dl) * math.sqrt(
            dt_dbeta ** 2 + dt_dalpha ** 2)
        u_td = math.sqrt(u_td_len ** 2 + u_td_noise ** 2)
        out["beta_rad_m"][i] = beta
        out["alpha_np_m"][i] = alpha
        out["er_eff"][i] = er_eff
        out["er_nom"][i] = er
        out["tan_d_nom"][i] = tan_d
        out["u_beta"][i] = u_beta
        out["u_alpha"][i] = u_alpha
        out["u_er_gum"][i] = u_er
        out["u_tand_gum"][i] = u_td
        out["u_er_channel_length"][i] = u_er_length
        out["u_er_channel_noise"][i] = u_er_noise
        out["u_eps_eff_rel"][i] = 2.0 * u_beta / beta
        out["u_eps_eff_rel_length"][i] = 2.0 * u_dl / dl
        out["u_eps_eff_rel_noise"][i] = 2.0 * sigma_dphi / (beta * dl)
        out["dominant_channel"].append(
            "length" if u_er_length >= u_er_noise else "noise")
    out["metadata"] = {
        "dominant_pair_m": [lengths[i_min], lengths[i_max]],
        "delta_l_m": dl,
        "u_delta_l_m": u_dl,
        "model": "主对一阶线性（GUM JCGM 100:2008）；NIST 多线全对最小"
                 "二乘的完整协方差传播不在口径（如实声明）",
    }
    return out


def mtrl_er_tand_montecarlo(
    f_ghz: Any,
    w_mm: float,
    h_mm: float,
    er: float,
    tan_d: float,
    line_lengths_m: Any,
    u_lengths_m: Any,
    sigma_s: float,
    n_mc: int = 120,
    seed: int = _MC_DEFAULT_SEED,
    er_est: float | None = None,
) -> dict[str, Any]:
    """蒙特卡洛对照核（JCGM 101）：合成 mTRL 夹具加性扰动全链重提。

    扰动口径：逐线长度 N(L, u_L) + S 参数加性复高斯（逐分量 std sigma_s，
    E|n|²=2σ²）；链 = extract_gamma_mtrl（skrf NISTMultilineTRL 单源）→
    extract_er_tand_profile。固定 seed 完全可复现。
    """
    import skrf
    from skrf.media import MLine

    tag = "mtrl_er_tand_montecarlo"
    f_arr = np.atleast_1d(np.asarray(f_ghz, dtype=float))
    if f_arr.size == 0 or np.any(f_arr <= 0.0) or \
            not np.all(np.isfinite(f_arr)):
        raise ValueError(f"{tag}: freq_ghz 须为非空正有限数组，得到 {f_ghz!r}")
    n_mc = int(n_mc)
    if not 2 <= n_mc <= 2000:
        raise ValueError(f"{tag}: n_mc 须在 2..2000，实际 {n_mc!r}")
    lengths, u_list = _parse_lengths(line_lengths_m, u_lengths_m, tag)
    if isinstance(sigma_s, bool) or not math.isfinite(float(sigma_s)) \
            or float(sigma_s) < 0.0:
        raise ValueError(f"{tag}: sigma_s 必须 >=0 有限，得到 {sigma_s!r}")

    freq = skrf.Frequency(float(f_arr[0]), float(f_arr[-1]), f_arr.size,
                          unit="GHz")
    mline = MLine(frequency=freq, w=float(w_mm) * 1e-3,
                  h=float(h_mm) * 1e-3, ep_r=float(er), tand=float(tan_d),
                  model="hammerstadjensen")
    thru = mline.thru()
    reflect = mline.short(nports=2)
    rng = np.random.default_rng(int(seed))
    ers = np.empty((n_mc, f_arr.size))
    tds = np.empty((n_mc, f_arr.size))
    for k in range(n_mc):
        lines_k = []
        lengths_k = []
        for length, u_l in zip(lengths, u_list, strict=True):
            net = mline.line(length, unit="m")
            if float(sigma_s) > 0.0 or u_l > 0.0:
                s = np.asarray(net.s)
                s = s + (float(sigma_s) / math.sqrt(2.0)) * (
                    rng.standard_normal(s.shape)
                    + 1j * rng.standard_normal(s.shape))
                net.s = s
            lines_k.append(net)
            lengths_k.append(length + float(rng.normal(0.0, u_l)))
        er_prior = float(er_est) if er_est is not None else float(er)
        g = extract_gamma_mtrl(lines_k, lengths_k, thru=thru, reflect=reflect,
                               er_est=complex(er_prior, -float(tan_d)))
        prof = extract_er_tand_profile(g.gamma, g.frequency_hz, w_mm, h_mm)
        ers[k] = prof.er
        tds[k] = prof.tan_d
    return {
        "freq_ghz": f_arr.copy(),
        "er_mc_mean": ers.mean(axis=0),
        "er_mc_std": ers.std(axis=0, ddof=1),
        "tan_d_mc_mean": tds.mean(axis=0),
        "tan_d_mc_std": tds.std(axis=0, ddof=1),
        "er_draws": ers,
        "tan_d_draws": tds,
        "n_mc": n_mc,
        "seed": int(seed),
    }


@register_calculator(
    "mtrl_er_tand_uncertainty",
    "mTRL εr/tanδ 不确定度传播：EC-2 尺寸公差+测量噪声双通道 "
    "GUM 一阶线性传播（u(εeff)/εeff=2u_β/β 精确恒等；主对模型如实声明）"
    "+ 蒙特卡洛对照（JCGM 101，k=2 区间覆盖率门 ≥95% 预声明，固定 seed）；"
    "输出逐频 u_er/u_tand 带区间+通道分解+支配通道——锚 gate 消费面",
    (("freq_ghz", "array GHz 频率轴（非空，>0）"),
     ("w_mm", "float mm 微带导带宽度（>0）"),
     ("h_mm", "float mm 基板厚度（>0）"),
     ("er", "float 名义相对介电常数（>0，正向与锚点）"),
     ("tan_d", "float 名义损耗正切（>0）"),
     ("line_lengths_m", "array m mTRL 线长（≥2 根互异，>0）"),
     ("u_lengths_m", "float|array m 逐线长度标准不确定度（标量广播或逐线）"),
     ("sigma_s", "float S 参数加性复高斯逐分量 std（>=0；0=纯公差通道）"),
     ("n_mc", "int MC 抽样数 0=关（GUM only）/2..2000（缺省 120）"),
     ("seed", "int MC 种子（缺省 20261018，完全可复现）"),
     ("er_est", "float - γ 根选择 εeff 先验（缺省=er 名义值）")),
    required=("freq_ghz", "w_mm", "h_mm", "er", "tan_d", "line_lengths_m",
              "u_lengths_m", "sigma_s"),
)
def mtrl_er_tand_uncertainty(
    freq_ghz: list,
    w_mm: float,
    h_mm: float,
    er: float,
    tan_d: float,
    line_lengths_m: list,
    u_lengths_m: Any,
    sigma_s: float,
    n_mc: int = 120,
    seed: int = _MC_DEFAULT_SEED,
    er_est: float | None = None,
) -> dict[str, Any]:
    """组合编排：名义回收 + GUM 双通道传播 +（可选）MC 对照与覆盖门。"""
    tag = "mtrl_er_tand_uncertainty"
    f_arr = np.atleast_1d(np.asarray(freq_ghz, dtype=float))
    if f_arr.size == 0 or np.any(f_arr <= 0.0):
        raise ValueError(f"{tag}: freq_ghz 须为非空正数组，得到 {freq_ghz!r}")
    n_mc = int(n_mc)
    if n_mc != 0 and not 2 <= n_mc <= 2000:
        raise ValueError(
            f"{tag}: n_mc 须为 0（关 MC）或 2..2000，实际 {n_mc!r}")

    gum = mtrl_er_tand_gum(f_arr * 1e9, w_mm, h_mm, er, tan_d,
                           line_lengths_m, u_lengths_m, sigma_s)

    result: dict[str, Any] = {
        "freq_ghz": [round(float(v), 9) for v in f_arr],
        "w_mm": w_mm,
        "h_mm": h_mm,
        "er": er,
        "tan_d": tan_d,
        "line_lengths_m": [float(v) for v in np.atleast_1d(
            np.asarray(line_lengths_m, dtype=float))],
        "u_lengths_m": (float(u_lengths_m) if isinstance(u_lengths_m,
                                                         (int, float))
                        and not isinstance(u_lengths_m, bool)
                        else [float(v) for v in u_lengths_m]),
        "sigma_s": float(sigma_s),
        "n_mc": n_mc,
        "beta_rad_m": [round(float(v), 12) for v in gum["beta_rad_m"]],
        "alpha_np_m": [round(float(v), 12) for v in gum["alpha_np_m"]],
        "er_eff": [round(float(v), 12) for v in gum["er_eff"]],
        "u_er_gum": [round(float(v), 15) for v in gum["u_er_gum"]],
        "u_tand_gum": [round(float(v), 15) for v in gum["u_tand_gum"]],
        "u_er_rel": [round(float(v), 15) for v in
                     gum["u_er_gum"] / np.maximum(gum["er_nom"], 1e-300)],
        "u_tand_rel": [round(float(v), 15) for v in
                       gum["u_tand_gum"] / max(tan_d, 1e-300)],
        "u_er_channel_length": [round(float(v), 15)
                                for v in gum["u_er_channel_length"]],
        "u_er_channel_noise": [round(float(v), 15)
                               for v in gum["u_er_channel_noise"]],
        "u_eps_eff_rel": [round(float(v), 15) for v in gum["u_eps_eff_rel"]],
        "u_eps_eff_rel_length": [round(float(v), 15)
                                 for v in gum["u_eps_eff_rel_length"]],
        "u_eps_eff_rel_noise": [round(float(v), 15)
                                for v in gum["u_eps_eff_rel_noise"]],
        "dominant_channel": list(gum["dominant_channel"]),
        "gum_metadata": gum["metadata"],
        "anchor_gate_note": (
            "锚 gate 消费建议：判据带宽=标称值 ± 2·u_er_gum / ± 2·"
            "u_tand_gum（k=2，G4 语义）；dominant_channel 与 u_*_rel 入 "
            "provenance 作公差预算归因"),
        "source": (
            "GUM：JCGM 100:2008 一阶线性传播；MC 验证：JCGM 101；γ 提取："
            "skrf NISTMultilineTRL（DeGroot-Jargon-Marks 2002，经 "
            "core/dielectric_extract 单源）；正向：skrf MLine "
            "hammerstadjensen（与综合链同模型口径）"),
    }

    if n_mc == 0:
        result["mc"] = None
        result["note"] = "n_mc=0：仅 GUM 双通道传播（MC 对照未运行）"
        return result

    mc = mtrl_er_tand_montecarlo(f_arr, w_mm, h_mm, er, tan_d,
                                 line_lengths_m, u_lengths_m, sigma_s,
                                 n_mc=n_mc, seed=seed, er_est=er_est)
    # JCGM 101 覆盖门：MC 抽样落入标称 ± k·u_GUM 的比例（逐频，k=2）
    k_cover = 2.0
    er_draws = mc["er_draws"]
    td_draws = mc["tan_d_draws"]
    u_er = np.asarray(gum["u_er_gum"])
    u_td = np.asarray(gum["u_tand_gum"])
    cov_er = np.mean(np.abs(er_draws - er) <= k_cover * u_er[None, :],
                     axis=0)
    cov_td = np.mean(np.abs(td_draws - tan_d) <= k_cover * u_td[None, :],
                     axis=0)
    ratio_er = u_er / np.maximum(mc["er_mc_std"], 1e-300)
    ratio_td = u_td / np.maximum(mc["tan_d_mc_std"], 1e-300)
    mc_block = {
        "n_mc": n_mc,
        "seed": int(seed),
        "er_mc_mean": [round(float(v), 15) for v in mc["er_mc_mean"]],
        "er_mc_std": [round(float(v), 15) for v in mc["er_mc_std"]],
        "tan_d_mc_mean": [round(float(v), 15) for v in mc["tan_d_mc_mean"]],
        "tan_d_mc_std": [round(float(v), 15) for v in mc["tan_d_mc_std"]],
        "coverage_er_k2": [round(float(v), 6) for v in cov_er],
        "coverage_tand_k2": [round(float(v), 6) for v in cov_td],
        "coverage_min_declared": _COVERAGE_MIN,
        "coverage_er_pass": bool(np.all(cov_er >= _COVERAGE_MIN)),
        "coverage_tand_pass": bool(np.all(cov_td >= _COVERAGE_MIN)),
        "gum_over_mc_ratio_er": [round(float(v), 9) for v in ratio_er],
        "gum_over_mc_ratio_tand": [round(float(v), 9) for v in ratio_td],
        "ratio_range_declared": list(_MC_RATIO_RANGE),
        "ratio_er_in_domain": bool(np.all(
            (_MC_RATIO_RANGE[0] <= ratio_er)
            & (ratio_er <= _MC_RATIO_RANGE[1]))),
        "ratio_tand_in_domain": bool(np.all(
            (_MC_RATIO_RANGE[0] <= ratio_td)
            & (ratio_td <= _MC_RATIO_RANGE[1]))),
    }
    result["mc"] = mc_block
    result["mc_pass"] = bool(mc_block["coverage_er_pass"]
                             and mc_block["coverage_tand_pass"]
                             and mc_block["ratio_er_in_domain"]
                             and mc_block["ratio_tand_in_domain"])
    result["note"] = (
        "GUM 双通道+MC 对照（JCGM 101 覆盖门+标准差比域，预声明阈值见 mc "
        "块 *_declared 字段）；固定 seed 完全可复现")
    return result
