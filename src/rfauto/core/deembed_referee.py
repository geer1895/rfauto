"""DP-15 C2：skrf 2.x 新能力接入——2x-thru 双路去嵌裁判面 + s_error 包装。

定位（不改既有面）
------------------
自研去嵌链 ``core/deembed.py`` 是参考面/理想线去嵌（几何先验驱动），本模块
**不替换它**，而是给它配一条独立第三方对照路（IEEEP370 2x-thru 夹具去嵌，
skrf 2.1.0 ``skrf.calibration.deembedding`` 实现，runs/df6_a3/skrf2x_audit.md
审计：该类不在 ``skrf.calibration`` 顶层）并输出逐频连续差（s_error 口径）：

- 自研路：``extract_line_gamma``（identity/thru 差分提 γ）→
  ``ideal_line_network`` 重建 fixture → ``deembed_reference_plane`` 两侧平移；
- P370 路：``IEEEP370_SE_NZC_2xThru.deembed``（NZC=无夹具先验，仅 2x-thru
  实测件；可选 ZC 变体 opt-in，见下）。

DC 预处理（规格书坑预声明）：P370 内部 IFFT/时域剥离对带限合成网络缺 DC
敏感，裁判面缺省做 ``extrapolate_to_dc``（可选 "add_dc" / None）。2026-09-24
实测（runs/df6_dp15c2/criteria.md §0.2）：在 IEEE370 合规语料上三模式无差
异（坑未显现，守卫保留）；窄带违规语料（2x-thru<3λg）失效主因是 3λg 条件
本身，DC 预处理救不回。

诚实边界
--------
1. 自研路是"匹配线先验"：fixture 失配（Z0≠参考阻抗）时该先验不可表达，
   ``fixture_z0_ohm`` 可显式给先验但 γ 差分在失配下本就有偏——两路在大失配
   语料上发散是**裁判的判别力**（tests 钉行为不钉数值）。
2. ZC 变体（需 fix-dut-fix 第二实测件）opt-in，输出只进 ``zc_variant`` 子
   字典且 ``gated=False``：2026-09-24 合成解析语料全参数扫不达标（最好
   0.23、典型 1.41 非物理），不设门（#122 不凑绿）；ZC 目标域是实测件，
   本批不裁决 ZC 算法质量。
3. 本模块全部确定性：纯 numpy + skrf，无随机、无网络、无全局状态。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import skrf

#: s_error 支持的误差函数白名单（skrf 2.1.0 docstring/源码实测集）。
#: 字符串比较大小写不敏感（skrf 内部亦 lower）。
S_ERROR_FUNCTIONS: tuple[str, ...] = (
    "average_l1_norm",
    "average_l2_norm",
    "maximum_l1_norm",
    "average_normalized_l1_norm",
)

#: 裁判面缺省误差口径（规格书 G1–G3 同口径；average_l2_norm = 逐频
#: |ΔS|² 的矩阵平均，无量纲）
DEFAULT_S_ERROR_FUNCTION = "average_l2_norm"

#: DC 预处理缺省值（规格书坑预声明：P370 IFFT 对合成网络 DC 敏感，
#: 显式预处理；本语料实测三模式同值，见模块 docstring）
DEFAULT_DC_MODE = "extrapolate_to_dc"


# ---------------------------------------------------------------------------
# 件2：skrf.network.s_error 的仓内薄包装（确定性、显式守卫）
# ---------------------------------------------------------------------------

def s_error_metric(
    ntwkA: skrf.Network,
    ntwkB: skrf.Network,
    error_function: str = DEFAULT_S_ERROR_FUNCTION,
) -> np.ndarray:
    """两网络 S 参数逐频误差（skrf.network.s_error 的仓内薄包装）。

    守卫显式化（不等 skrf 晚报）：Network 类型、端口数一致、频率栅格一致、
    ``error_function`` 必须在 :data:`S_ERROR_FUNCTIONS` 白名单（大小写不
    敏感）。计算委托给 ``skrf.network`` 模块级函数（审计 §1：函数+方法双
    形态，此处钉模块级形态），版本钉 ``skrf.__version__ == "2.1.0"`` 见
    tests/unit/test_deembed_referee.py。

    Returns:
        形状 (nfreq,) 的 float ndarray；average_l2_norm 口径 = 逐频
        mean(|ΔS_ij|²)（skrf 定义无开方，量级即均方误差）。
    """
    from rfauto.core.deembed import _as_network

    a = _as_network(ntwkA, "ntwkA")
    b = _as_network(ntwkB, "ntwkB")
    if a.nports != b.nports:
        raise ValueError(
            f"两网络端口数不一致：{a.nports} vs {b.nports}",
        )
    if a.frequency != b.frequency:
        raise ValueError(
            f"两网络频率栅格不一致：{len(a.f)} 点 vs {len(b.f)} 点",
        )
    ef = str(error_function).lower()
    if ef not in S_ERROR_FUNCTIONS:
        raise ValueError(
            f"未知 error_function {error_function!r}（支持: "
            f"{', '.join(S_ERROR_FUNCTIONS)}）",
        )
    from skrf.network import s_error

    return np.asarray(s_error(a, b, error_function=ef), dtype=float)


def s_error_max(
    ntwkA: skrf.Network,
    ntwkB: skrf.Network,
    error_function: str = DEFAULT_S_ERROR_FUNCTION,
) -> float:
    """s_error_metric 的带内最大值标量（门判定口径 G1–G3）。"""
    return float(s_error_metric(ntwkA, ntwkB, error_function).max())


# ---------------------------------------------------------------------------
# 件1：2x-thru 双路去嵌裁判
# ---------------------------------------------------------------------------

def _dc_preprocess(
    net: skrf.Network,
    dc_mode: str | None,
) -> skrf.Network:
    """P370 输入的 DC 预处理（坑预声明的显式口）。

    dc_mode: "extrapolate_to_dc" | "add_dc" | None。两种模式的实现来自
    IEEEP370 基类（skrf 官方推荐带限数据走 extrapolate_to_dc）。
    """
    from skrf.calibration.deembedding import IEEEP370_SE_NZC_2xThru

    if dc_mode is None:
        return net
    if dc_mode == "extrapolate_to_dc":
        return IEEEP370_SE_NZC_2xThru.extrapolate_to_dc(net)
    if dc_mode == "add_dc":
        return IEEEP370_SE_NZC_2xThru.add_dc(net)
    raise ValueError(
        f"dc_mode 只能是 'extrapolate_to_dc'/'add_dc'/None，实际 {dc_mode!r}",
    )


def _back_to_grid(net: skrf.Network, freq: skrf.Frequency) -> skrf.Network:
    """P370/ZC 结果（DC 扩展栅格 / NRP 平移栅格）插值回原栅格。"""
    if net.frequency == freq:
        return net
    return net.interpolate(freq)


def referee_2xthru_deembed(
    dut_fdf: skrf.Network,
    dummy_2xthru: skrf.Network,
    dut_reference: skrf.Network,
    fixture_length_m: float,
    *,
    z0: float = 50.0,
    gate_threshold: float = 1e-6,
    s_error_function: str = DEFAULT_S_ERROR_FUNCTION,
    dc_mode: str | None = DEFAULT_DC_MODE,
    fixture_z0_ohm: float | None = None,
    zc_fix_dut_fix: skrf.Network | None = None,
) -> dict[str, Any]:
    """2x-thru 夹具去嵌双路裁判：自研链 vs IEEEP370 NZC（→纯 JSON 字典）。

    Args:
        dut_fdf: 夹具-DUT-夹具复合测量（合成语料=FIX ** DUT ** FIX）。
        dummy_2xthru: 2x-thru 实测件（FIX ** FIX）。
        dut_reference: 去嵌目标真值（合成语料的合成 DUT；实测场景不可得时
            传任一同栅格网络，则 *_vs_reference 两列如实失真，ok 无意义）。
        fixture_length_m: 单侧夹具物理长度 (m)——自研路的几何先验。
        z0: 参考阻抗 (Ω)。
        gate_threshold: 门阈值（规格书：理想情形 < 1e-6，s_error 口径）。
        s_error_function: 误差口径（见 :data:`S_ERROR_FUNCTIONS`）。
        dc_mode: P370 输入 DC 预处理（见 :data:`DEFAULT_DC_MODE`）。
        fixture_z0_ohm: 自研路 fixture 阻抗先验（缺省 = z0，即匹配先验；
            失配 fixture 显式给值可减轻失配误差，γ 差分偏差仍在）。
        zc_fix_dut_fix: opt-in——ZC 变体所需 fix-dut-fix 实测件；传入则
            追加 ``zc_variant`` 子字典（gated=False，见模块 docstring 3）。

    Returns:
        ok / referee_max_s_error（G1 两路差）/ inhouse_vs_reference_max（G2）
        / p370_vs_reference_max（G3）/ gate_threshold / dc_mode / n_points
        等纯 JSON 标量；门 = 三者均 < gate_threshold。
    """
    from skrf.calibration.deembedding import IEEEP370_SE_NZC_2xThru

    from rfauto.core.deembed import (
        _as_network,
        _positive_finite,
        _require_2port_pair,
        deembed_reference_plane,
        extract_line_gamma,
        ideal_line_network,
    )

    dut_fdf = _as_network(dut_fdf, "dut_fdf")
    dummy_2xthru = _as_network(dummy_2xthru, "dummy_2xthru")
    dut_reference = _as_network(dut_reference, "dut_reference")
    _require_2port_pair(dut_fdf, dummy_2xthru, "dut_fdf", "dummy_2xthru")
    _require_2port_pair(dut_fdf, dut_reference, "dut_fdf", "dut_reference")
    length = _positive_finite(fixture_length_m, "fixture_length_m (m)")
    threshold = _positive_finite(gate_threshold, "gate_threshold",
                                 allow_zero=True)
    z0_val = _positive_finite(z0, "z0 (Ω)")
    freq = dut_fdf.frequency

    # ── 自研路：几何先验（γ 差分 + 理想线重建 + 两侧参考面平移）───────────
    identity = ideal_line_network(freq, 0.0, 0.0, z0=z0_val)
    gamma = extract_line_gamma(identity, dummy_2xthru, 2.0 * length)
    fix_z0 = z0_val if fixture_z0_ohm is None else _positive_finite(
        fixture_z0_ohm, "fixture_z0_ohm (Ω)")
    fix = ideal_line_network(freq, length, gamma, z0=fix_z0)
    inhouse = deembed_reference_plane(dut_fdf, fix, side="input")
    inhouse = deembed_reference_plane(inhouse, fix, side="output")

    # ── P370 路：IEEEP370_SE_NZC_2xThru（DC 预处理 → deembed → 回原栅格）──
    th = _dc_preprocess(dummy_2xthru, dc_mode)
    ff = _dc_preprocess(dut_fdf, dc_mode)
    deembedder = IEEEP370_SE_NZC_2xThru(
        dummy_2xthru=th, name="rfauto_referee_nzc", z0=z0_val,
    )
    p370 = _back_to_grid(deembedder.deembed(ff), freq)

    # ── 裁判量（G1 两路连续差 / G2 G3 对合成真值回收）────────────────────
    e_referee = s_error_max(inhouse, p370, s_error_function)
    e_inhouse = s_error_max(inhouse, dut_reference, s_error_function)
    e_p370 = s_error_max(p370, dut_reference, s_error_function)
    ok = bool(e_referee < threshold and e_inhouse < threshold
              and e_p370 < threshold)

    out: dict[str, Any] = {
        "ok": ok,
        "gate_threshold": threshold,
        "n_points": int(np.asarray(freq.f).size),
        "dc_mode": dc_mode,
        "s_error_function": s_error_function,
        "fixture_length_m": length,
        "z0_ohm": z0_val,
        "fixture_z0_ohm": fix_z0,
        "referee_max_s_error": e_referee,
        "inhouse_vs_reference_max": e_inhouse,
        "p370_vs_reference_max": e_p370,
        "zc_variant": None,
        "note": "G1=referee(自研 vs P370)、G2=inhouse、G3=p370 对合成真值；"
                "自研路=几何先验（γ 差分+理想线重建），P370=无先验剥离；"
                "失配/窄带违规语料两路发散是判别力不是缺陷",
    }

    # ── ZC 变体（opt-in，只记不门）────────────────────────────────────────
    if zc_fix_dut_fix is not None:
        from skrf.calibration.deembedding import IEEEP370_SE_ZC_2xThru

        zc_in = _as_network(zc_fix_dut_fix, "zc_fix_dut_fix")
        _require_2port_pair(zc_in, dut_fdf, "zc_fix_dut_fix", "dut_fdf")
        th_z = _dc_preprocess(dummy_2xthru, dc_mode)
        ff_z = _dc_preprocess(zc_in, dc_mode)
        zc_deembedder = IEEEP370_SE_ZC_2xThru(
            dummy_2xthru=th_z, dummy_fix_dut_fix=ff_z,
            name="rfauto_referee_zc", z0=z0_val,
        )
        zc_res = _back_to_grid(zc_deembedder.deembed(ff_z), freq)
        out["zc_variant"] = {
            "ran": True,
            "gated": False,
            "vs_reference_max": s_error_max(
                zc_res, dut_reference, s_error_function),
            "vs_inhouse_max": s_error_max(
                zc_res, inhouse, s_error_function),
            "note": "ZC 需第二实测件；合成解析语料不达标如实记录（#122），"
                    "本批不裁决 ZC 算法质量",
        }
    return out
