"""df7 T2：SI 通道一键报告 service 面（JSON 进出，规则 4；CLI/MCP 是薄壳）。

纯后处理吃现成 sparams 资产（Touchstone 文件或 run 目录），零新几何模板。
四检查段（方案池 docs/plan_expansion_pool_20260924.md T2）：

- **passivity 无源性**：全频段逐频 σmax(S)（numpy SVD），判据
  max σmax ≤ 1+tol（违规频点列 TOP N）；
- **causality 因果性**（IEEE P370 风格自实现，口径与局限如实标注）：
  ①带限 IFFT 冲激响应的负时间（循环尾窗）能量占比；②低频相位斜率
  视在群延迟——负值即时域超前（时间提前的"预冲"是 P370 典型非因果
  注入）。skrf 2.1.0 无现成 P370 因果性函数（grep 实测），故自实现；
  局限：延迟 τ0 + 响应宽度须 ≪ 1/df（循环周期），否则如实 unknown；
- **TDR 阶跃阻抗剖面**：S11 阶跃响应（冲激响应 cumsum，等价频域积分）
  → Z(t)=Z0·(1+Γ)/(1−Γ)，输出前 2ns 均值/全程 min/max/平坦度 + 降采样
  剖面。时域原语复用 core/si_channel（resample_s21/impulse_response/
  step_response 单源，含直流常数保持的显式近似口径）；
- **COM**（IEEE 802.3-22 Annex 93A 冻结口径，PyChOpMarg 参考实现）：
  4 端口文件可用（THRU=本文件，FEXT/NEXT 可选附加文件列表）；2 端口
  如实 not_applicable（COM 定义在 4 端口差分测量）；pychopmarg 缺装/
  失败时该段 degraded 报缺不抛（惰性 import，#105）。

pychopmarg 3.1.2 参数口径（预声明，provenance 留痕）：包内自带 preset
（config/ieee_8023by.py、ieee_8023dj.py）与该版 COMParams 字段 schema
不匹配（C_d/L_s 旧版平铺 vs 3.1.2 梯形嵌套，R_d 需 Tx/Rx 两元——实测
COM(IEEE_8023by, ...) 在 sDie 处 TypeError），故按 3.1.2 schema 以关键
字参数重建 93A（100GBASE-KR4 类）口径：fb/M/T_r/R_0/A_v/A_fe/A_ne/噪声
/CTLE 取 ieee_8023by 原值；Tx FFE 3 taps×0.05 步进（93A 前/主/后抽头
结构）；die/package 梯形按旧 preset 变体值映射为 Tx/Rx 嵌套段（映射关
系见 _com_params_93a 注释）。COM 数值以 pychopmarg 内核为权威，本服务
不自证精确值。

数值只在确定性内核（规则 7）：本服务全部数字出自 numpy/skrf/
core.si_channel/pychopmarg 确定性计算，LLM/agent 只消费报告。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np

#: 报告 schema 版本
SI_CHANNEL_REPORT_SCHEMA_VERSION = "1.0"

#: 判据缺省（预声明；CLI/MCP 可覆盖）
_PASSIVITY_TOL_DEFAULT = 0.01
_VIOLATION_TOP_N_DEFAULT = 10
_CAUSALITY_THRESHOLD_DEFAULT = 0.02
_PRE_CURSOR_GUARD_NS_DEFAULT = 1.0
_TDR_WINDOW_NS_DEFAULT = 2.0

#: 视在群延迟负值门（s）：低于此值判时域超前（非因果）
_NEG_DELAY_GUARD_S = 1e-10

#: 时域段可用最小频点数（低于则如实 degraded：时域分辨率不足）
_MIN_FREQ_POINTS_TIME_DOMAIN = 64

#: Γ 非物理保护（|Γ|≥ 该值时 Z(t) 记 NaN 不进统计）
_GAMMA_CLIP = 0.9999

#: TDR 剖面降采样上限点数
_TDR_PROFILE_MAX_POINTS = 1001

#: Touchstone 扩展名 → 端口数（skrf 读面）
_TOUCHSTONE_SUFFIXES = (".s2p", ".s3p", ".s4p", ".s5p", ".s6p",
                        ".s7p", ".s8p", ".s9p", ".s10p")


# ---------------------------------------------------------------------------
# 源读取（Touchstone 文件 / run 目录；csv 优先 = #314 掩码载体口径）
# ---------------------------------------------------------------------------

def _network_from_csv(freq_hz: np.ndarray, s: np.ndarray,
                      mask: np.ndarray) -> tuple[Any, str]:
    """openEMS sparams.csv 矩阵 → skrf.Network（50Ω 基，openEMS 惯例）。"""
    import skrf

    net = skrf.Network(
        frequency=skrf.Frequency.from_f(np.asarray(freq_hz, dtype=float),
                                        unit="hz"),
        s=np.asarray(s, dtype=complex),
        z0=50.0,
    )
    return net, ("measured_mask:" + "".join(
        "1" if bool(v) else "0" for row in np.asarray(mask) for v in row))


def _load_source(source: str | Path) -> dict[str, Any]:
    """读源 → {kind, path, network, n_ports, freq_hz, s, mask, z0, notes}。

    文件：Touchstone（.sNp，skrf 读）。目录：sparams.csv 优先（#314 掩码
    载体；复用 health_service 单源解析器），否则 rglob Touchstone（复用
    health_service._load_touchstone 的候选序）。
    """
    import skrf

    from rfauto.service.health_service import _load_sparams_csv, _load_touchstone

    p = Path(source)
    notes: list[str] = []
    if p.is_file():
        if p.suffix.lower() not in _TOUCHSTONE_SUFFIXES:
            raise ValueError(
                f"不支持的源文件类型 {p.suffix!r}（须为 Touchstone "
                f"{_TOUCHSTONE_SUFFIXES} 或 run 目录）: {p}")
        net = skrf.Network(str(p))
        return {"kind": "touchstone", "path": str(p), "network": net,
                "n_ports": int(net.nports),
                "freq_hz": np.asarray(net.f, dtype=float),
                "s": np.asarray(net.s, dtype=complex), "mask": None,
                "z0": float(np.real(np.asarray(net.z0).ravel()[0])),
                "notes": notes}
    if p.is_dir():
        errors: list[str] = []
        try:
            parsed = _load_sparams_csv(p, errors)
        except Exception as exc:  # 掩码载体损坏（#316）：不回退 Touchstone
            raise ValueError(
                f"run 目录 sparams.csv 存在但全部不可解析（不回退 "
                f"Touchstone，#316 口径）: {exc}") from exc
        if parsed is not None:
            freq_hz, s, mask = parsed
            net, mask_tag = _network_from_csv(freq_hz, s, mask)
            notes.append("源为 openEMS 掩码 sparams.csv（部分矩阵，单激励"
                         f"口径；{mask_tag}）")
            return {"kind": "sparams_csv", "path": str(p), "network": net,
                    "n_ports": int(net.nports),
                    "freq_hz": np.asarray(freq_hz, dtype=float),
                    "s": np.asarray(s, dtype=complex),
                    "mask": np.asarray(mask, dtype=bool), "z0": 50.0,
                    "notes": notes}
        net_pair = _load_touchstone(p, errors)
        if net_pair is not None:
            freq_hz, s = net_pair
            n_ports = int(s.shape[1])
            # 候选序与 health_service 一致；首个成功者即为源
            cands = sorted((p / "results").glob("params.s*p"))
            cands += [q for q in sorted(p.rglob("*.s2p")) + sorted(p.rglob("*.s3p"))
                      + sorted(p.rglob("*.s4p")) if q not in cands]
            src_file = cands[0] if cands else p
            net = skrf.Network(str(src_file))
            return {"kind": "run_dir_touchstone", "path": str(src_file),
                    "network": net, "n_ports": n_ports,
                    "freq_hz": np.asarray(freq_hz, dtype=float),
                    "s": np.asarray(s, dtype=complex), "mask": None,
                    "z0": float(np.real(np.asarray(net.z0).ravel()[0])),
                    "notes": notes}
        raise ValueError(
            f"run 目录内未找到 sparams.csv 或 Touchstone 产物: {p} "
            f"（errors: {errors or '无'}）")
    raise ValueError(f"源不存在: {p}")


# ---------------------------------------------------------------------------
# 直流起步等间隔网格（复用 core/si_channel resample 口径，矩阵版）
# ---------------------------------------------------------------------------

def _dc_first_grid(freq_hz: np.ndarray, s: np.ndarray
                   ) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """（可能不含直流的）S 矩阵 → 含直流等间隔单边网格 (f, S, notes)。

    口径同 core/si_channel.resample_s21（显式近似）：0 Hz 用首点常数保持；
    不超出源末端外推。源已是 [0, df, 2df…] 网格时恒等直通。
    """
    from rfauto.core.si_channel import resample_s21

    f = np.asarray(freq_hz, dtype=float)
    notes: list[str] = []
    if f.size < 3:
        raise ValueError(f"频点数不足（{f.size} < 3）")
    if f[0] <= 0.0:
        # 已含直流：仅校验等间隔（core impulse_response 会再校验）
        df = float(f[1] - f[0])
        if not np.allclose(np.diff(f), df, rtol=1e-6,
                           atol=1e-9 * max(1.0, abs(df))):
            raise ValueError("频率网格必须等间隔（IFFT 口径）")
        return f, np.asarray(s, dtype=complex), notes
    n_out = f.size + 1 if abs(f[0] - (f[-1] / f.size)) <= 1e-6 * f[-1] / f.size \
        else f.size
    # n_out=f.size+1：均匀网格 [df, 2df, …]（DC 直接补首点=恒等+直流）；
    # 其余（非均匀/起点≠df）：linspace(0, fmax, n) 重采样（显式近似）
    grid = np.empty(n_out, dtype=float)
    s_dc = np.empty((n_out, *s.shape[1:]), dtype=complex)
    for i in range(s.shape[1]):
        for j in range(s.shape[2]):
            g, s_r = resample_s21(f, s[:, i, j], n_points=n_out)
            if i == 0 and j == 0:
                grid = g
            s_dc[:, i, j] = s_r
    if n_out == f.size + 1:
        notes.append("直流点按首点常数保持补入（resample_s21 口径），"
                     "其余网格恒等")
    else:
        notes.append("源网格非均匀/起点非 df：已线性重采样到含直流等间隔"
                     "网格（实部/虚部分别插值，显式近似）")
    return grid, s_dc, notes


# ---------------------------------------------------------------------------
# 检查段 1：无源性
# ---------------------------------------------------------------------------

def _check_passivity(freq_hz: np.ndarray, s: np.ndarray,
                     mask: np.ndarray | None, *, tol: float,
                     top_n: int) -> dict[str, Any]:
    """全频段 σmax(S) ≤ 1+tol（全矩阵 SVD）；部分矩阵按已测元上界如实降级。"""
    f = np.asarray(freq_hz, dtype=float)
    s_arr = np.asarray(s, dtype=complex)
    if mask is None:
        sig = np.linalg.svd(s_arr, compute_uv=False)  # (n_f, min(n,n))
        sigma_max = sig[:, 0]
        basis = "full_matrix_svd"
    else:
        m = np.asarray(mask, dtype=bool)
        mag = np.abs(s_arr)
        sigma_max = np.array(
            [float(np.max(mag[k][m])) if np.any(m) else 0.0
             for k in range(mag.shape[0])])
        basis = "measured_entries_upper_bound"
    k_max = int(np.argmax(sigma_max))
    viol_idx = np.nonzero(sigma_max > 1.0 + tol)[0]
    order = viol_idx[np.argsort(sigma_max[viol_idx])[::-1]][:top_n]
    violations = [{"freq_hz": float(f[k]), "sigma_max": float(sigma_max[k])}
                  for k in order]
    if basis != "full_matrix_svd":
        # 部分矩阵：有违规照判 FAIL（已测元越界即铁证），无违规只能
        # inconclusive（未测元素不背书，不冒充 PASS，#314 口径）
        status = "fail" if violations else "inconclusive"
    else:
        status = "fail" if violations else "pass"
    section: dict[str, Any] = {
        "status": status,
        "criterion": "max sigma_max(S) <= 1 + tol",
        "tol": float(tol),
        "basis": basis,
        "max_sigma_max": float(sigma_max[k_max]),
        "max_sigma_max_freq_hz": float(f[k_max]),
        "n_violations": int(viol_idx.size),
        "violations_top": violations,
    }
    if mask is not None:
        section["note"] = ("部分矩阵（掩码载体，#314）：σmax 不可全矩阵计，"
                           "以上为已测元素 |S_ij| 上界；无违规也只能记 "
                           "inconclusive（未测元素不背书），不冒充 PASS")
    return section


# ---------------------------------------------------------------------------
# 检查段 2：因果性（IEEE P370 风格自实现）
# ---------------------------------------------------------------------------

def _group_delay_low_freq(freq_dc: np.ndarray, s21: np.ndarray) -> float | None:
    """低频段（前 10%，≥5 点）S21 相位斜率 → 视在群延迟 (s)；点数不足 None。"""
    n_band = max(5, int(freq_dc.size * 0.1))
    n_band = min(n_band, freq_dc.size - 1)
    if n_band < 5:
        return None
    f_band = freq_dc[1:n_band + 1]
    ph = np.unwrap(np.angle(s21[1:n_band + 1]))
    coef = np.polyfit(f_band, ph, 1)
    return float(-coef[0] / (2.0 * np.pi))


def _check_causality(freq_dc: np.ndarray, s_dc: np.ndarray, *,
                     threshold: float, guard_ns: float) -> dict[str, Any]:
    """P370 风格：带限 IFFT 冲激响应负时间（循环尾窗）能量占比 + 低频视
    在群延迟符号。经路径 = S21（port2←port1；sdd_21 "1→2/3→4" 端口序的
    单端直通亦此路径）。局限如实：τ0+响应宽度 ≫ 1/df 时循环卷绕污染尾窗
    → unknown；带限泄漏地板决定 threshold（非 0 判据）。"""
    from rfauto.core.si_channel import impulse_response, impulse_time_axis_s

    s21 = np.ascontiguousarray(s_dc[:, 1, 0])
    h, dt = impulse_response(freq_dc, s21)
    t = impulse_time_axis_s(h, dt)
    period_s = float(t[-1] + dt)
    energy = float(np.sum(np.abs(h) ** 2))
    guard_s = float(guard_ns) * 1e-9
    tail_mask = t >= (period_s - guard_s)
    tail_frac = (float(np.sum(np.abs(h[tail_mask]) ** 2)) / energy
                 if energy > 0.0 else 0.0)
    tau_est = _group_delay_low_freq(freq_dc, s21)

    reasons: list[str] = []
    status = "pass"
    if energy <= 0.0:
        status = "unknown"
        reasons.append("冲激响应能量为 0（全零 S21？），无法判据")
    if tau_est is None:
        status = "unknown"
        reasons.append("低频相位斜率点数不足，视在群延迟不可估")
    else:
        if tau_est * 2.0 >= period_s:
            status = "unknown"
            reasons.append(
                f"视在群延迟 {tau_est:.3e}s ≥ 循环周期之半 "
                f"{period_s / 2:.3e}s：响应可能循环卷绕，尾窗判据失效")
        elif tau_est < -_NEG_DELAY_GUARD_S:
            status = "fail"
            reasons.append(
                f"低频视在群延迟为负（{tau_est:.3e}s < "
                f"-{_NEG_DELAY_GUARD_S:.1e}s）= 时域超前，非因果")
    if status != "fail" and tail_frac > threshold:
        status = "fail"
        reasons.append(
            f"负时间（循环尾窗 t≥{period_s - guard_s:.3e}s）能量占比 "
            f"{tail_frac:.3e} > 阈值 {threshold:.3e}")
    section: dict[str, Any] = {
        "status": status,
        "method": "ieee_p370_style_self_implemented",
        "criterion": (f"tail_energy_frac(t >= T-{guard_ns:.1f}ns) <= "
                      f"{threshold:g} 且 视在群延迟 >= "
                      f"-{_NEG_DELAY_GUARD_S * 1e9:.1f}ns"),
        "path": "S21 (port2<-port1)",
        "pre_cursor_energy_frac": tail_frac,
        "pre_cursor_guard_ns": float(guard_ns),
        "threshold": float(threshold),
        "apparent_group_delay_s": tau_est,
        "ifft_period_s": period_s,
        "ifft_dt_s": float(dt),
        "note": ("skrf 2.1.0 无现成 P370 因果性检查（实测 grep），本段为 "
                 "P370 风格自实现：带限 IFFT 循环尾窗能量 + 低频相位斜率"
                 "延迟符号；带限泄漏地板决定阈值非零，非严格 0 判据"),
    }
    if reasons:
        section["reasons"] = reasons
    return section


# ---------------------------------------------------------------------------
# 检查段 3：TDR 阶跃阻抗剖面
# ---------------------------------------------------------------------------

def _check_tdr(freq_dc: np.ndarray, s_dc: np.ndarray, *, z0: float,
               window_ns: float) -> dict[str, Any]:
    """S11 阶跃响应 → Z(t)=Z0(1+Γ)/(1−Γ)；统计 + 降采样剖面（报告面，
    无 pass/fail 判据——剖面判读交消费方）。"""
    from rfauto.core.si_channel import impulse_time_axis_s, step_response

    s11 = np.ascontiguousarray(s_dc[:, 0, 0])
    gamma_step, dt = step_response(freq_dc, s11)
    t = impulse_time_axis_s(gamma_step, dt)
    gamma_max = float(np.max(np.abs(gamma_step))) if gamma_step.size else 0.0
    ok_mask = np.abs(gamma_step) < _GAMMA_CLIP
    z = np.full(gamma_step.shape, np.nan)
    z[ok_mask] = (z0 * (1.0 + gamma_step[ok_mask])
                  / (1.0 - gamma_step[ok_mask]))
    n_nonphysical = int(np.count_nonzero(~ok_mask))
    win_s = float(window_ns) * 1e-9
    m_first = (t > 0.0) & (t <= win_s) & ok_mask
    # 到达时刻 = |Γ_step| 首次超过 1% 峰值（全匹配 → 无到达 → 从 0 计）
    peak = float(np.max(np.abs(gamma_step))) if gamma_step.size else 0.0
    arr_idx = (int(np.argmax(np.abs(gamma_step) > 0.01 * peak))
               if peak > 1e-12 else 0)
    m_arr = (t >= t[arr_idx]) & (t <= t[arr_idx] + win_s) & ok_mask
    z_valid = z[ok_mask]
    stats: dict[str, Any] = {
        "z0_ref_ohm": float(z0),
        "tdr_window_ns": float(window_ns),
        "z_mean_first_window_from_zero_ohm":
            float(np.mean(z[m_first])) if np.any(m_first) else None,
        "arrival_time_ns": float(t[arr_idx]) * 1e9,
        "z_mean_first_window_from_arrival_ohm":
            float(np.mean(z[m_arr])) if np.any(m_arr) else None,
        "z_min_ohm": float(np.min(z_valid)) if z_valid.size else None,
        "z_max_ohm": float(np.max(z_valid)) if z_valid.size else None,
        "z_median_ohm": float(np.median(z_valid)) if z_valid.size else None,
        "flatness_rel": ((float(np.max(z_valid)) - float(np.min(z_valid)))
                         / abs(float(np.median(z_valid)))
                         if z_valid.size and float(np.median(z_valid)) != 0.0
                         else None),
        "gamma_step_max": gamma_max,
        "n_nonphysical_gamma": n_nonphysical,
    }
    idx = np.linspace(0, t.size - 1,
                      min(t.size, _TDR_PROFILE_MAX_POINTS)).astype(int)
    profile = {
        "t_ns": [round(float(t[k]) * 1e9, 6) for k in idx],
        "z_ohm": [None if not np.isfinite(z[k]) else round(float(z[k]), 4)
                  for k in idx],
    }
    status = "ok" if z_valid.size else "degraded"
    section = {"status": status, **stats, "profile": profile}
    if status == "degraded":
        section["note"] = "Z(t) 全程非物理（|Γ|≥0.9999），无有效统计"
    return section


# ---------------------------------------------------------------------------
# 检查段 4：COM（PyChOpMarg，IEEE 93A 冻结口径）
# ---------------------------------------------------------------------------

def _com_params_93a() -> tuple[Any, str]:
    """按 pychopmarg 3.1.2 COMParams schema 重建 93A 口径参数（见模块
    docstring 预声明；数值出处=包内 ieee_8023by preset 原值映射）。

    映射：C_d/L_s 旧平铺变体值 → Tx/Rx 梯形嵌套段；R_d [55] → [55, 55]
    （Tx/Rx 两元，gamma1_[Tx|Rx] 索引要求）；C_p [1.8e-4] → Tx/Rx 各半
    分配；Tx FFE 3 taps（93A 前/主/后结构，步进 0.1 → 21 组合，实测
    ~60s/次；0.05 步进 → 数百组合 ~11min 不可用）；CTLE g_DC 7 档
    （-12..0 步 2）；dfe 1 tap。
    """
    from pychopmarg.config.template import COMParams

    fb = 25.78125  # GBaud（100GBASE-KR4 类，ieee_8023by 原值）
    params = COMParams(
        fb=fb, fstep=0.01, L=2, M=32, DER_0=1e-5, T_r=0.010, RLM=1.0,
        A_v=0.4, A_fe=0.4, A_ne=0.6, R_0=50.0,
        A_DD=0.05, SNR_TX=27, eta_0=5.2e-8, sigma_Rj=0.01,
        f_z=fb / 4, f_p1=fb / 4, f_p2=fb, f_LF=1.0,
        g_DC=[-float(n) for n in range(0, 13, 2)], g_DC2=[0.0],
        tx_taps_min=[-0.3, 0.7, -0.3], tx_taps_max=[0.0, 1.0, 0.0],
        tx_taps_step=[0.1, 0.1, 0.1], c0_min=0.0,
        f_r=0.75,
        dfe_min=np.array([-1.0]), dfe_max=np.array([1.0]),
        rx_taps_min=np.array([0.0]), rx_taps_max=np.array([1.0]), dw=0,
        R_d=np.array([55.0, 55.0]),
        C_d=np.array([[4.0e-5, 9.0e-4, 1.1e-4], [4.0e-5, 9.0e-4, 1.1e-4]]),
        C_b=[0.0, 0.0], C_p=[1.8e-4, 1.8e-4],
        L_s=np.array([[0.13], [0.15]]), z_c=[87.5, 92.5], z_p=[12.0, 33.0],
        gamma0=5.0e-4, a1=8.9e-4, a2=2.0e-4, tau=6.141e-3,
    )
    note = ("pychopmarg 3.1.2 schema 关键字重建（包内 ieee_8023by preset 与"
            "该版 COMParams 不匹配，实测 TypeError）：93A 值映射见 "
            "_com_params_93a docstring；COM 数值以 pychopmarg 内核为权威")
    return params, note


def _check_com(thru_path: str, n_ports: int, *,
               fext_paths: list[str] | None,
               next_paths: list[str] | None) -> dict[str, Any]:
    """COM 段：4 端口文件可跑（THRU=源文件，FEXT/NEXT 可选）；2 端口
    not_applicable；缺装/失败 degraded（#105，不阻塞其余段）。"""
    if n_ports != 4:
        return {
            "status": "not_applicable",
            "note": (f"COM 定义在 4 端口差分测量（THRU+FEXT/NEXT），源为 "
                     f"{n_ports} 端口——如实不适用"),
        }
    try:
        from pychopmarg.com import COM  # 惰性 import（#105：缺装如实降级）
    except Exception as exc:
        return {"status": "degraded",
                "note": f"pychopmarg 不可用（{exc}）——COM 段降级不阻塞"}
    try:
        params, params_note = _com_params_93a()
        channels = {
            "THRU": [Path(thru_path)],
            "FEXT": [Path(x) for x in (fext_paths or [])],
            "NEXT": [Path(x) for x in (next_paths or [])],
        }
        t0 = time.perf_counter()
        the_com = COM(params, channels)
        com_db = float(the_com())
        wall = time.perf_counter() - t0
        return {
            "status": "ok",
            "com_db": com_db,
            "fb_gbaud": float(params.fb),
            "n_tx_combs": int(the_com.num_tx_combs),
            "cursor_ix": int(getattr(the_com, "cursor_ix", -1)),
            "wall_time_s": round(wall, 3),
            "fext_files": list(fext_paths or []),
            "next_files": list(next_paths or []),
            "params_note": params_note,
        }
    except Exception as exc:
        return {"status": "degraded",
                "note": f"pychopmarg COM 计算失败（{type(exc).__name__}: "
                        f"{exc}）——COM 段降级不阻塞（#105）"}


# ---------------------------------------------------------------------------
# 报告组装 + markdown 渲染（前端只渲染原则 #90：markdown 在 service 层）
# ---------------------------------------------------------------------------

def si_channel_report(
    source: str | Path,
    *,
    passivity_tol: float = _PASSIVITY_TOL_DEFAULT,
    violation_top_n: int = _VIOLATION_TOP_N_DEFAULT,
    causality_threshold: float = _CAUSALITY_THRESHOLD_DEFAULT,
    pre_cursor_guard_ns: float = _PRE_CURSOR_GUARD_NS_DEFAULT,
    tdr_window_ns: float = _TDR_WINDOW_NS_DEFAULT,
    fext_paths: list[str] | None = None,
    next_paths: list[str] | None = None,
    markdown: bool = False,
) -> dict[str, Any]:
    """SI 通道一键报告（JSON 进出）：无源性/因果性/TDR/COM 四段。

    Args:
        source: Touchstone 文件路径（.sNp）或 run 目录（含 sparams.csv →
            掩码口径优先，或 Touchstone 产物）。
        passivity_tol: 无源性容差（max σmax ≤ 1+tol）。
        violation_top_n: 违规频点 TOP N 列表上限。
        causality_threshold: 负时间能量占比阈值。
        pre_cursor_guard_ns: 循环尾窗宽度（负时间判定窗）。
        tdr_window_ns: TDR 统计窗（从 0 与从到达时刻各一）。
        fext_paths: COM 远端串扰 4 端口文件列表（可选）。
        next_paths: COM 近端串扰 4 端口文件列表（可选）。
        markdown: True 时附带 markdown 渲染文本。

    Returns:
        {ok, errors, warnings, source, passivity, causality, tdr, com,
        provenance, markdown?}；ok=False 仅当源不可读/不可解析。
    """
    errors: list[str] = []
    warnings: list[str] = []
    try:
        src = _load_source(source)
    except Exception as exc:
        return {"ok": False, "schema_version": SI_CHANNEL_REPORT_SCHEMA_VERSION,
                "errors": [f"源读取失败: {exc}"], "warnings": []}

    freq_hz = src["freq_hz"]
    s = src["s"]
    mask = src["mask"]
    n_ports = src["n_ports"]
    z0 = float(src["z0"])
    warnings.extend(src["notes"])

    # 直流起步网格（时域段共用）
    freq_dc, s_dc, grid_notes = _dc_first_grid(freq_hz, s)
    warnings.extend(grid_notes)
    time_domain_ok = freq_dc.size >= _MIN_FREQ_POINTS_TIME_DOMAIN

    passivity = _check_passivity(freq_hz, s, mask, tol=passivity_tol,
                                 top_n=violation_top_n)
    if n_ports < 2:
        causality = {"status": "not_applicable",
                     "note": f"{n_ports} 端口文件无通过路径 S21（需 ≥2 端口）"}
    elif time_domain_ok:
        causality = _check_causality(
            freq_dc, s_dc, threshold=causality_threshold,
            guard_ns=pre_cursor_guard_ns)
    else:
        causality = {"status": "degraded",
                     "note": f"频点数 {freq_dc.size} < "
                             f"{_MIN_FREQ_POINTS_TIME_DOMAIN}，时域分辨率不足"}
    if time_domain_ok:
        tdr = _check_tdr(freq_dc, s_dc, z0=z0, window_ns=tdr_window_ns)
    else:
        tdr = {"status": "degraded",
               "note": f"频点数 {freq_dc.size} < "
                       f"{_MIN_FREQ_POINTS_TIME_DOMAIN}，时域分辨率不足"}

    com = _check_com(src["path"], n_ports, fext_paths=fext_paths,
                     next_paths=next_paths)

    report: dict[str, Any] = {
        "ok": True,
        "schema_version": SI_CHANNEL_REPORT_SCHEMA_VERSION,
        "errors": errors,
        "warnings": warnings,
        "source": {
            "kind": src["kind"],
            "path": src["path"],
            "n_ports": n_ports,
            "n_freqs": int(freq_hz.size),
            "f_min_hz": float(freq_hz[0]),
            "f_max_hz": float(freq_hz[-1]),
            "z0_ref_ohm": z0,
            "partial_matrix": bool(mask is not None),
        },
        "passivity": passivity,
        "causality": causality,
        "tdr": tdr,
        "com": com,
        "provenance": _provenance({
            "passivity_tol": passivity_tol,
            "violation_top_n": violation_top_n,
            "causality_threshold": causality_threshold,
            "pre_cursor_guard_ns": pre_cursor_guard_ns,
            "tdr_window_ns": tdr_window_ns,
            "fext_paths": list(fext_paths or []),
            "next_paths": list(next_paths or []),
        }),
    }
    if markdown:
        report["markdown"] = render_si_channel_markdown(report)
    return report


def _provenance(params: dict[str, Any]) -> dict[str, Any]:
    """工具版本+参数+时间戳（#105 best-effort：缺失如实 unknown，不阻塞）。"""
    import datetime

    prov: dict[str, Any] = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "numpy_version": np.__version__,
        "params": params,
        "skrf_version": "unknown",
        "pychopmarg_version": None,
    }
    try:
        import skrf

        prov["skrf_version"] = str(skrf.__version__)
    except Exception:
        pass
    try:
        from pychopmarg import __version__ as com_ver

        prov["pychopmarg_version"] = str(com_ver)
    except Exception:
        pass
    return prov


def _status_line(section: str, data: dict[str, Any]) -> str:
    status = data.get("status", "unknown")
    return f"### {section}\n\nstatus: `{status}`\n"


def render_si_channel_markdown(report: dict[str, Any]) -> str:
    """报告 dict → markdown 文本（service 层渲染，CLI 薄壳直出，#90）。"""
    src = report.get("source") or {}
    lines: list[str] = ["# SI 通道报告", ""]
    lines.append(f"- 源: `{src.get('path')}` ({src.get('kind')})")
    lines.append(f"- 端口数: {src.get('n_ports')}  频点: {src.get('n_freqs')}"
                 f"  频段: {src.get('f_min_hz', 0):.3e} – "
                 f"{src.get('f_max_hz', 0):.3e} Hz  Z0: {src.get('z0_ref_ohm')} Ω")
    if src.get("partial_matrix"):
        lines.append("- 部分矩阵（掩码 sparams.csv）：判据口径如实降级")
    lines.append("")

    pas = report.get("passivity") or {}
    lines.append(_status_line("无源性 (passivity)", pas))
    lines.append(f"- 判据: {pas.get('criterion')}  tol={pas.get('tol')}")
    lines.append(f"- max σmax = {pas.get('max_sigma_max'):.6f} @ "
                 f"{pas.get('max_sigma_max_freq_hz'):.4e} Hz"
                 f"（口径 {pas.get('basis')}）")
    lines.append(f"- 违规频点数: {pas.get('n_violations')}")
    for v in (pas.get("violations_top") or [])[:5]:
        lines.append(f"  - {v['freq_hz']:.6e} Hz: σmax={v['sigma_max']:.6f}")
    if pas.get("note"):
        lines.append(f"- note: {pas['note']}")
    lines.append("")

    cau = report.get("causality") or {}
    lines.append(_status_line("因果性 (causality, IEEE P370 风格)", cau))
    if cau.get("method"):
        lines.append(f"- {cau['method']}: {cau.get('criterion')}")
    if cau.get("pre_cursor_energy_frac") is not None:
        lines.append(f"- 负时间能量占比: {cau['pre_cursor_energy_frac']:.3e} "
                     f"(阈值 {cau.get('threshold')})")
    if cau.get("apparent_group_delay_s") is not None:
        lines.append(f"- 低频视在群延迟: {cau['apparent_group_delay_s']:.4e} s")
    for r in cau.get("reasons") or []:
        lines.append(f"- reason: {r}")
    if cau.get("note"):
        lines.append(f"- note: {cau['note']}")
    lines.append("")

    tdr = report.get("tdr") or {}
    lines.append(_status_line("TDR 阶跃阻抗剖面", tdr))
    if tdr.get("status") == "ok":
        lines.append(f"- Z(前 {tdr.get('tdr_window_ns')}ns, 从 0): "
                     f"{tdr.get('z_mean_first_window_from_zero_ohm'):.3f} Ω"
                     f"  从到达({tdr.get('arrival_time_ns'):.3f}ns): "
                     f"{tdr.get('z_mean_first_window_from_arrival_ohm'):.3f} Ω")
        lines.append(f"- 全程 min/max/中位: {tdr.get('z_min_ohm'):.3f} / "
                     f"{tdr.get('z_max_ohm'):.3f} / "
                     f"{tdr.get('z_median_ohm'):.3f} Ω"
                     f"  平坦度: {tdr.get('flatness_rel'):.4f}")
        prof = tdr.get("profile") or {}
        ts = prof.get("t_ns") or []
        zs = prof.get("z_ohm") or []
        lines.append("")
        lines.append("| t (ns) | Z (Ω) |")
        lines.append("| --- | --- |")
        for tk, zk in zip(ts, zs, strict=True):
            lines.append(f"| {tk} | {zk} |")
    else:
        lines.append(f"- note: {tdr.get('note')}")
    lines.append("")

    com = report.get("com") or {}
    lines.append(_status_line("COM (IEEE 93A 口径, PyChOpMarg)", com))
    if com.get("status") == "ok":
        lines.append(f"- COM = {com.get('com_db'):.3f} dB"
                     f"  (fb={com.get('fb_gbaud')} GBaud, "
                     f"tx_combs={com.get('n_tx_combs')}, "
                     f"wall={com.get('wall_time_s')}s)")
    if com.get("note"):
        lines.append(f"- note: {com['note']}")
    if com.get("params_note"):
        lines.append(f"- params: {com['params_note']}")
    lines.append("")

    prov = report.get("provenance") or {}
    lines.append("### provenance\n")
    lines.append(f"- timestamp: {prov.get('timestamp')}  "
                 f"skrf: {prov.get('skrf_version')}  "
                 f"pychopmarg: {prov.get('pychopmarg_version')}  "
                 f"numpy: {prov.get('numpy_version')}")
    return "\n".join(lines) + "\n"
