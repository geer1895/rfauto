"""aia_joint：有源集成天线/联合设计接口（AA-1，round19 P2 前半，接口原型级）。

**接口原型级**（ge8c 席C5 口径）：schema + 编排面 + 合成数据验证；零真机、
零 LLM 通道（#139）。两条链全部消费既有已合流内核（硬规则 7：零新物理
数字）——

1. **filtenna 链**（天线作滤波器/PA 终端的联合综合）：
   ``core.mask_filter_synthesis``（MaskSpec/min_order_for_mask/synthesize_
   from_mask，round14 已合流）。filtenna 惯例已破 50Ω 单一参考
   （S1434841125004625，2025 无缝滤波——round19 来源清单），故 z0_ref
   是显式入参不写死。天线失配吃掉回损预算：**一阶失配预算**
   M_total ≈ M_net + M_ant（dB 加性；M_db = −10·log10(1−|Γ|²)）——
   无耗互易匹配网络 + 天线负载的级联失配因子首阶预算口径，交叉反射项
   未计（原型边界，docstring 如实登记）。

2. **reactively loaded small antenna 链**（Chu 界验收）：
   ``core.bounds``（bbox_to_ka/chu_q_bound，McLean 1996 严格式，仓内
   已 #118 接地）。加载电抗只移谐振不破 Chu 下界——给定 bbox 的天线
   声称 Q < Q_min(ka) 即非物理（原型一致性判据）。

Q 提取链（本面不重跑）：调用方从 Z(ω) 数据给 q_actual；合成验证用
串联 RLC 闭式构造（Q 已知），半功率匹配带宽口径 Q = f0/BW_frac 的
|Γ|²=1/2 推导见 :func:`matched_bw_q`（教科书级恒等式，窄带近似）。

#118 双基准：①失配预算算术恒等式（Γ→dB 数值例逐位可复算）；
②Chu 界（独立内核）+ RLC 构造回收（已知 Q 回收比对）。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core.bounds import bbox_to_ka, chu_q_bound
from rfauto.core.mask_filter_synthesis import MaskSpec, min_order_for_mask
from rfauto.service.envelope import ok_envelope

_SOURCE = "rfauto.service.aia_joint_service"


def _num(value: Any, name: str, *, positive: bool = False,
         nonneg: bool = False) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} 必须为数值，得到 {value!r}") from exc
    if not math.isfinite(v):
        raise ValueError(f"{name} 必须有限，得到 {v!r}")
    if positive and v <= 0:
        raise ValueError(f"{name} 必须 >0，得到 {v!r}")
    if nonneg and v < 0:
        raise ValueError(f"{name} 必须 ≥0，得到 {v!r}")
    return v


def gamma_of_impedance(z: complex, z0_ref: float) -> complex:
    """负载阻抗 → 电压波反射系数 Γ=(Z−Z0)/(Z+Z0)（教科书口径，z0_ref>0）。"""
    if z0_ref <= 0:
        raise ValueError("z0_ref 必须 >0")
    return (z - z0_ref) / (z + z0_ref)


def mismatch_loss_db(gamma_abs: float) -> float:
    """失配损耗 M = −10·log10(1−|Γ|²)（dB，≥0；|Γ|≥1 非物理显式报错）。"""
    g = _num(gamma_abs, "gamma_abs", nonneg=True)
    if g >= 1.0:
        raise ValueError(f"|Γ|={g} ≥1 非物理（无源终端）")
    return -10.0 * math.log10(1.0 - g * g)


def rl_db_of_gamma(gamma_abs: float) -> float:
    """回损 RL = −20·log10|Γ|（dB，>0；|Γ|=0 → +inf 口径交调用方）。"""
    g = _num(gamma_abs, "gamma_abs", nonneg=True)
    if g == 0.0:
        return math.inf
    if g >= 1.0:
        raise ValueError(f"|Γ|={g} ≥1 非物理（无源终端）")
    return -20.0 * math.log10(g)


def rl_antenna_from_z_data(z_data: list[dict[str, Any]], z0_ref: float,
                           *, worst: bool = True) -> dict[str, Any]:
    """天线 Z(ω) 数据 → 带内最坏失配 RL（|Γ| 逐点取最坏）。

    z_data 元素 = {"freq_hz": float, "z_re": float, "z_im": float}（调用方
    从测量/仿真导出链带入；本面零 IO 零求解）。
    """
    if not z_data:
        return {"ok": False, "reason": "z_data 为空", "source": _SOURCE}
    z0 = _num(z0_ref, "z0_ref", positive=True)
    gammas: list[tuple[float, Any]] = []
    for i, row in enumerate(z_data):
        try:
            z = complex(_num(row["z_re"], f"z_data[{i}].z_re"),
                        _num(row["z_im"], f"z_data[{i}].z_im"))
        except (KeyError, TypeError, ValueError) as exc:
            return {"ok": False, "reason": f"z_data[{i}] 非法: {exc}",
                    "source": _SOURCE}
        g = abs(gamma_of_impedance(z, z0))
        if g >= 1.0:
            return {"ok": False,
                    "reason": f"z_data[{i}] |Γ|={g:.4g} ≥1 非物理（z0_ref "
                              f"口径失配；检查单位/有源性）",
                    "source": _SOURCE}
        gammas.append((g, row.get("freq_hz")))
    pick = max if worst else min
    worst_gamma, worst_at = pick(gammas, key=lambda t: t[0])
    n_pts = len(gammas)
    return ok_envelope(
        source=_SOURCE,
        n_points=n_pts,
        z0_ref=z0,
        gamma_abs=worst_gamma,
        gamma_abs_at_hz=worst_at,
        rl_antenna_db=rl_db_of_gamma(worst_gamma),
        mismatch_loss_db=mismatch_loss_db(worst_gamma),
        criterion="worst" if worst else "best",
    )


def filtenna_match_budget(payload: dict[str, Any]) -> dict[str, Any]:
    """filtenna 联合预算：天线失配 + 联合回损目标 → 网络侧 RL 需求 → 最小阶。

    Args（payload 键）:
        rl_antenna_db 或 z_data+z0_ref：天线带内失配（二选一；前者直接给
            回损，后者走 :func:`rl_antenna_from_z_data` 逐点算）；
        rl_total_db: 联合（网络+天线级联）带内回损目标（dB，>0）；
        mask: MaskSpec.to_dict() 形态的遮罩规格（rl_db 字段被网络侧 RL
            需求覆写——联合预算语义）；缺 segments 时显式报错不猜。

    Returns:
        {ok, rl_net_db, m_net_db, m_total_db, order, min_order, ...}；
        ok=False 时 reason 如实（预算不可达/入参非法）。
    """
    p = payload if isinstance(payload, dict) else {}
    z0 = _num(p.get("z0_ref", 50.0), "z0_ref", positive=True)
    if p.get("rl_antenna_db") is not None:
        rl_ant = _num(p["rl_antenna_db"], "rl_antenna_db", positive=True)
        gamma_ant = 10.0 ** (-rl_ant / 20.0)
        ant_detail: dict[str, Any] = {"ok": True, "gamma_abs": gamma_ant,
                                      "rl_antenna_db": rl_ant,
                                      "mismatch_loss_db":
                                          mismatch_loss_db(gamma_ant)}
    elif p.get("z_data") is not None:
        ant_detail = rl_antenna_from_z_data(p["z_data"], z0)
        if not ant_detail.get("ok"):
            return {**ant_detail, "stage": "rl_antenna_from_z_data"}
        rl_ant = ant_detail["rl_antenna_db"]
    else:
        return {"ok": False, "source": _SOURCE,
                "reason": "rl_antenna_db 与 z_data 二选一必给"}
    rl_total = _num(p.get("rl_total_db"), "rl_total_db", positive=True)
    # 一阶失配预算（dB 加性）：M_total ≈ M_net + M_ant
    m_total = mismatch_loss_db(10.0 ** (-rl_total / 20.0))
    m_net = m_total - ant_detail["mismatch_loss_db"]
    if m_net <= 0:
        return {"ok": False, "source": _SOURCE,
                "reason": f"预算不可达：天线失配 M_ant="
                          f"{ant_detail['mismatch_loss_db']:.4g} dB 已吃满/超"
                          f"联合目标 M_total={m_total:.4g} dB（rl_total_db="
                          f"{rl_total}）——匹配网络无预算可分",
                "rl_antenna_db": rl_ant, "rl_total_db": rl_total,
                "m_total_db": m_total}
    # 网络侧 RL 需求 → 覆写 mask rl_db → 复用最小阶闭式（round14 内核）
    gamma_net = math.sqrt(1.0 - 10.0 ** (-m_net / 10.0))
    rl_net = rl_db_of_gamma(gamma_net)
    mask_data = p.get("mask")
    if not isinstance(mask_data, dict):
        return {"ok": False, "source": _SOURCE,
                "reason": "mask 缺失（MaskSpec.to_dict() 形态，含 segments）"}
    mask_data = {**mask_data, "rl_db": rl_net}
    try:
        mask = MaskSpec.from_dict(mask_data)
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "source": _SOURCE,
                "reason": f"mask 非法: {exc}"}
    min_order = min_order_for_mask(mask)
    return ok_envelope(
        source=_SOURCE,
        z0_ref=z0,
        rl_antenna_db=round(rl_ant, 9),
        mismatch_loss_db_ant=round(ant_detail["mismatch_loss_db"], 9),
        rl_total_db=round(rl_total, 9),
        m_total_db=round(m_total, 9),
        m_net_db=round(m_net, 9),
        rl_net_db=round(rl_net, 9),
        budget_model="一阶失配预算 M_total ≈ M_net + M_ant（dB 加性，"
                            "交叉反射未计——原型边界，见模块 docstring）",
        min_order=min_order,
        gamma_ant_abs=round(ant_detail["gamma_abs"], 12),
        gamma_net_abs=round(gamma_net, 12),
    )


def matched_bw_q(f0_hz: float, bw_matched_hz: float) -> float:
    """匹配半功率带宽（两 |Γ|²=1/2 穿越点的全宽）→ Q（串联 RLC 窄带恒等式）。

    口径推导（窄带 |ω/ω0 − ω0/ω| ≈ 2δ，δ=单边相对失谐）：|Γ|² = X²/(4R²+X²)，
    半功率 |Γ|²=1/2 ⇔ |X|=2R ⇔ 2δ·ω0L = 2R = 2ω0L/Q ⇔ δ=1/Q。两穿越点
    全宽 BW = 2δω0 = 2ω0/Q ⇒ **Q = 2·f0/BW_matched**。（构造 RLC 已知 Q
    的回收比对为基准①；经典"半功率带宽 BW=ω0/Q"是电流衰落口径 |X|=R，
    与反射匹配口径 |X|=2R 差 2 倍——两口径勿混。）
    """
    f0 = _num(f0_hz, "f0_hz", positive=True)
    bw = _num(bw_matched_hz, "bw_matched_hz", positive=True)
    return 2.0 * f0 / bw


def series_rlc_impedance(freq_hz: list[float], r_ohm: float, l_h: float,
                         c_f: float) -> list[dict[str, Any]]:
    """串联 RLC 阻抗合成（验证数据构造器：Z = R + j(ωL − 1/(ωC))，已知 Q）。"""
    r = _num(r_ohm, "r_ohm", positive=True)
    l_h = _num(l_h, "l_h", positive=True)
    c = _num(c_f, "c_f", positive=True)
    out: list[dict[str, Any]] = []
    for f in freq_hz:
        f = _num(f, "freq_hz", positive=True)
        w = 2.0 * math.pi * f
        x = w * l_h - 1.0 / (w * c)
        out.append({"freq_hz": f, "z_re": r, "z_im": x})
    return out


def reactive_load_chu_check(payload: dict[str, Any]) -> dict[str, Any]:
    """reactively loaded small antenna：Chu 界一致性验收（bounds.py 复用）。

    Args（payload 键）:
        bbox_m: 天线包围盒 [dx,dy,dz]（米，>0）；f_hz: 工作频率（Hz）；
        q_actual: 天线 Q（调用方从 Z(ω) 提取链带入；合成验证用
            matched_bw_q 回收）；polarization: "linear"|"circular"（可选）。

    Returns:
        {ok, ka, q_min_chu, q_actual, verdict: "physically_consistent"|
        "violates_chu_bound", margin_ratio}。Chu 界为下界：q_actual ≥
        Q_min 才物理一致（Q_min 无耗下界口径，含损修正未实现——
        bounds.py docstring 同口径）。
    """
    p = payload if isinstance(payload, dict) else {}
    try:
        bbox = [float(v) for v in p["bbox_m"]]
        f = _num(p["f_hz"], "f_hz", positive=True)
        q_actual = _num(p.get("q_actual"), "q_actual", positive=True)
    except (KeyError, TypeError, ValueError) as exc:
        return {"ok": False, "source": _SOURCE, "reason": f"入参非法: {exc}"}
    try:
        ka = bbox_to_ka(bbox, f)
        bound = chu_q_bound(ka, polarization=str(p.get("polarization",
                                                       "linear")))
    except ValueError as exc:
        return {"ok": False, "source": _SOURCE, "reason": f"Chu 界入参非法: {exc}"}
    q_min = float(bound.limit_value)
    return ok_envelope(
        source=_SOURCE,
        ka=round(ka, 12),
        q_min_chu=q_min,
        q_actual=q_actual,
        margin_ratio=q_actual / q_min,
        verdict="physically_consistent" if q_actual >= q_min
                        else "violates_chu_bound",
        bound_name=bound.name,
        note="Chu-Harrington 下界（McLean 1996 严格式，core.bounds "
                    "复用）；q_actual < Q_min ⇒ 该 bbox 尺寸下非物理",
    )
