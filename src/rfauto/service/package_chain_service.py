"""SB22-PK-1 封装互连链装配器 service 面（JSON 进出，规则 4；无 CLI/MCP）。

薄壳定位：段表 DSL → core/package_chain 段工厂 → cable_channel 级联单源
→ JSON 报告。零数值逻辑（铁律 7：全部物理数字出自确定性内核）。

消费面（登记原文动机，2026-10-08 PK-2 席兑现）：通道 S 参数链喂
si_channel_service（IEEE370 报告面）——:func:`chain_si_channel_report`
一段式薄口（链 Network → 瞬态 s2p → si_channel_report；COM 定义在
4 端口差分测量，2 端口合成链的 COM 段 not_applicable 如实透传不伪装）。
com_pam4（COM 数值权威在 si_channel_service）受理 4 端口 s4p，2 端口
合成链不在其输入域，如实不接——调用方持 4 端口实测/仿真 s4p 时直调
com_pam4_run（最小接线原则，不过度设计）。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from rfauto.core.package_chain import (
    bondwire_network,
    bump_array_mutual_matrix,
    bump_pi_network,
    diff_pair_chain_report,
    quasi_tem_line_network,
    solder_ball_network,
    tgv_line_network,
)

_SEGMENT_KINDS = ("bondwire", "bump", "ball", "tgv", "line")


def _require(payload: dict[str, Any], key: str, where: str) -> Any:
    if key not in payload:
        raise ValueError(f"{where} 缺必填键 {key!r}")
    return payload[key]


def _freq_axis_from(payload: dict[str, Any]) -> np.ndarray:
    freq = np.asarray(_require(payload, "freq_hz", "payload"), dtype=float)
    if freq.ndim != 1 or freq.size == 0 or not np.all(np.isfinite(freq)) \
            or np.any(freq <= 0.0) or (freq.size > 1 and not np.all(np.diff(freq) > 0.0)):
        raise ValueError("freq_hz 必须是一维严格递增正实数组")
    return freq


def _stackup_from(raw: Any) -> Any:
    """stackup dict → synthesis.Stackup（RDL 单源消费；缺 tan_d/rho/rough 缺省）。"""
    from rfauto.core.synthesis import Stackup

    if not isinstance(raw, dict):
        raise ValueError("stackup 必须是 dict（epsilon_r/thickness_mm/...）")
    return Stackup(
        name=str(raw.get("name", "package_chain_rdl")),
        epsilon_r=float(_require(raw, "epsilon_r", "stackup")),
        thickness_mm=float(_require(raw, "thickness_mm", "stackup")),
        loss_tangent=float(raw.get("loss_tangent", 0.0)),
        rho=float(raw.get("rho", 1.724e-8)),
        rough_mm=float(raw.get("rough_mm", 0.0)),
    )


def _line_segment_networks(freq: np.ndarray, seg: dict[str, Any],
                           z_ref: float) -> tuple[Any, dict[str, Any]]:
    """line 段：RDL 消费走 synthesis 单源（width_mm+stackup → z0/εeff）或直给。

    设计频点单值口径（准静态参数无色散声明）：z0/εeff 在
    design_freq_ghz（缺省=频率轴中点）经 forward_z0（HJ 单源）评估，
    全频轴沿用（色散偏差随声明，#122）。
    """
    if "width_mm" in seg:
        from rfauto.core.synthesis import forward_z0

        stackup = _stackup_from(_require(seg, "stackup", "line 段"))
        f_design_ghz = float(seg.get(
            "design_freq_ghz", 0.5 * (float(freq[0]) + float(freq[-1])) * 1e-9))
        media = forward_z0(float(seg["width_mm"]), f_design_ghz, stackup)
        z0_ohm, eps_eff = media.z0, media.er_eff
        design_note = (f"synthesis.forward_z0(HJ 单源)@{f_design_ghz:.6g} GHz"
                       f" → z0={z0_ohm:.4f} Ω, εeff={eps_eff:.6f}")
    else:
        z0_ohm = float(_require(seg, "z0_ohm", "line 段"))
        eps_eff = float(_require(seg, "eps_eff", "line 段"))
        design_note = "调用方直给 z0/εeff（单源责任在调用方）"
    out = quasi_tem_line_network(
        freq,
        z0_ohm=z0_ohm,
        eps_eff=eps_eff,
        length_m=float(_require(seg, "length_m", "line 段")),
        tan_d=float(seg.get("tan_d", 0.0)),
        r_ohm_per_m=float(seg.get("r_ohm_per_m", 0.0)),
        z_ref_ohm=z_ref,
    )
    out["design_note"] = design_note
    return out["network"], out


def _segment_network(freq: np.ndarray, seg: dict[str, Any], z_ref: float,
                     index: int) -> tuple[Any, dict[str, Any]]:
    """段表条目 → (Network, 元数据)（kind 分派到 core 段工厂）。"""
    if not isinstance(seg, dict):
        raise ValueError(f"segments[{index}] 必须是 dict，收到 {type(seg).__name__}")
    kind = seg.get("kind")
    if kind not in _SEGMENT_KINDS:
        raise ValueError(
            f"segments[{index}].kind 必须是 {_SEGMENT_KINDS} 之一，收到 {kind!r}")
    if kind == "bondwire":
        out = bondwire_network(
            freq,
            length_m=float(_require(seg, "length_m", f"segments[{index}]")),
            radius_m=float(_require(seg, "radius_m", f"segments[{index}]")),
            sigma_s_per_m=float(seg.get("sigma_s_per_m", 4.11e7)),  # 金 22°C
            z_ref_ohm=z_ref,
        )
        meta = {k: out[k] for k in
                ("l_total_nh", "r_dc_ohm", "l_over_r", "in_declared_scope", "source")}
        meta["r_ac_ohm"] = [float(x) for x in out["r_ac_ohm"]]
    elif kind in ("bump", "ball"):
        builder = bump_pi_network if kind == "bump" else solder_ball_network
        out = builder(
            freq,
            height_m=float(_require(seg, "height_m", f"segments[{index}]")),
            diameter_m=float(_require(seg, "diameter_m", f"segments[{index}]")),
            pad_diameter_m=float(_require(seg, "pad_diameter_m", f"segments[{index}]")),
            er_between=float(_require(seg, "er_between", f"segments[{index}]")),
            **({"sigma_s_per_m": float(seg["sigma_s_per_m"])}
               if "sigma_s_per_m" in seg else {}),
            z_ref_ohm=z_ref,
        )
        meta = {k: out[k] for k in
                ("l_total_ph", "c_total_ff", "height_over_diameter",
                 "in_declared_scope", "source")}
        meta["r_ac_ohm"] = [float(x) for x in out["r_ac_ohm"]]
    elif kind == "tgv":
        out = tgv_line_network(
            freq,
            r_via_m=float(_require(seg, "r_via_m", f"segments[{index}]")),
            r_shield_m=float(_require(seg, "r_shield_m", f"segments[{index}]")),
            length_m=float(_require(seg, "length_m", f"segments[{index}]")),
            er_glass=float(_require(seg, "er_glass", f"segments[{index}]")),
            tan_d=float(seg.get("tan_d", 0.0)),
            **({"sigma_s_per_m": float(seg["sigma_s_per_m"])}
               if "sigma_s_per_m" in seg else {}),
            z_ref_ohm=z_ref,
        )
        meta = {k: out[k] for k in
                ("l_per_length_nh_per_mm", "c_per_length_ff_per_mm",
                 "z0_coax_ohm", "t_delay_ps", "source")}
    else:  # line
        return _line_segment_networks(freq, seg, z_ref)
    return out["network"], meta


def _build_chain_networks(
    payload: dict[str, Any],
) -> tuple[list[Any], list[dict[str, Any]], Any, float]:
    """payload 校验 → (段 Network 列表, 段元数据, 频轴, z_ref)。

    build_package_chain_report / chain_si_channel_report 共用的装配前置
    （段工厂分派零数值逻辑；级联本体仍各自走 assemble_chain 单源）。
    """
    if not isinstance(payload, dict):
        raise ValueError("payload 必须是 dict")
    freq = _freq_axis_from(payload)
    z_ref = float(payload.get("z_ref_ohm", 50.0))
    if not (math.isfinite(z_ref) and z_ref > 0.0):
        raise ValueError(f"z_ref_ohm 必须为正有限数，得到 {z_ref!r}")
    segs = _require(payload, "segments", "payload")
    if not isinstance(segs, (list, tuple)) or not segs:
        raise ValueError("segments 必须是非空段表")
    networks: list[Any] = []
    metas: list[dict[str, Any]] = []
    for i, seg in enumerate(segs):
        net, meta = _segment_network(freq, seg, z_ref, i)
        networks.append(net)
        metas.append({"index": i, "kind": seg.get("kind"), **meta})
    return networks, metas, freq, z_ref


def build_package_chain_report(payload: dict[str, Any]) -> dict[str, Any]:
    """封装互连链装配报告（JSON 进出）。

    payload：
        freq_hz: list[float]（严格递增正实数）；
        z_ref_ohm: 缺省 50.0；
        segments: [{kind: bondwire|bump|ball|tgv|line, ...段参数}, ...]
            （信号流向序；line 段支持 width_mm+stackup 走 synthesis 单源
            或直给 z0_ohm+eps_eff）。

    Returns:
        dict（il_db/rl_db 谱 + min/mean + passive + 逐段元数据；network
        对象不序列化——重建走同 payload 重放，确定性零随机）。
    """
    networks, metas, _freq, z_ref = _build_chain_networks(payload)
    from rfauto.core.package_chain import assemble_chain

    chain = assemble_chain(networks, z_ref_ohm=z_ref)
    rep = chain["report"]
    return {
        "freq_hz": [float(x) for x in rep["freq_hz"]],
        "il_db": [float(x) for x in rep["il_db"]],
        "rl_db": [float(x) for x in rep["rl_db"]],
        "min_il_db": rep["min_il_db"],
        "min_il_freq_hz": rep["min_il_freq_hz"],
        "mean_il_db": rep["mean_il_db"],
        "passive": rep["passive"],
        "n_segments": len(metas),
        "z_ref_ohm": z_ref,
        "segments_meta": metas,
    }


def chain_si_channel_report(payload: dict[str, Any],
                            *, markdown: bool = False) -> dict[str, Any]:
    """封装互连链 → si_channel_service 一段式喂入薄口（JSON 进出）。

    链段表（同 :func:`build_package_chain_report` 的 payload 口径）级联
    成 2 端口 Network → **瞬态** .s2p（tempfile，报告返回即清理，不落
    工作区）→ si_channel_report（无源性/因果性/TDR/COM 四段）。零数值
    逻辑（铁律 7）；COM 定义在 4 端口差分测量，2 端口链的 COM 段
    not_applicable 如实透传（si_channel_service 既有口径，不伪装）。

    Returns:
        si_channel_report 的 ok 信封（构造器单源）增广两键：``chain``
        （min_il_db/mean_il_db/passive/n_segments/segments_meta/il_db/
        rl_db/f_hz/z_ref_ohm 摘要）与 ``note``（喂入语义+COM not_
        applicable 如实声明）；链段表契约错误（缺键/非法段）按本模块
        既有口径抛 ValueError。
    """
    networks, metas, _freq, z_ref = _build_chain_networks(payload)
    from rfauto.core.package_chain import assemble_chain
    from rfauto.service.si_channel_service import si_channel_report

    chain = assemble_chain(networks, z_ref_ohm=z_ref)
    rep = chain["report"]
    chain_summary: dict[str, Any] = {
        "freq_hz": [float(x) for x in rep["freq_hz"]],
        "il_db": [float(x) for x in rep["il_db"]],
        "rl_db": [float(x) for x in rep["rl_db"]],
        "min_il_db": rep["min_il_db"],
        "min_il_freq_hz": rep["min_il_freq_hz"],
        "mean_il_db": rep["mean_il_db"],
        "passive": rep["passive"],
        "n_segments": len(metas),
        "z_ref_ohm": z_ref,
        "segments_meta": metas,
    }
    import tempfile

    with tempfile.TemporaryDirectory(prefix="rfauto_chain_si_") as tmp:
        s2p_path = Path(tmp) / "package_chain.s2p"
        chain["network"].write_touchstone(str(s2p_path))
        si = si_channel_report(str(s2p_path), markdown=markdown)
    # 增广 si 报告（其 ok 信封已走 envelope 构造器——本薄口不再造新信封，
    # 契约 §4）：链摘要与喂入语义挂同级键，消费面单信封直读。
    si["chain"] = chain_summary
    si["note"] = ("链 Network 以瞬态 s2p 喂 si_channel_report（IEEE370 报告"
                  "面）；2 端口合成链的 COM 段 not_applicable 如实（COM 定"
                  "义在 4 端口差分测量），com_pam4 受理 4 端口 s4p 不在本"
                  "薄口输入域")
    return si


def build_diff_pair_report(payload: dict[str, Any]) -> dict[str, Any]:
    """对称差分对模链混合模报告（JSON 进出）。

    payload：freq_hz / z_ref_ohm（缺省 50）/
    odd_segments / even_segments：各为 [{z0_mode_ohm, eps_eff, length_m,
    tan_d?, r_ohm_per_m?}, ...]（Z0e/Z0o 来源单源在调用方——mtl_modes.
    symmetric_pair_even_odd 或场解）。

    模型边界：对称对假设 → Sdc/Scd 恒等零（inf dB）；非对称对 v1 范围外。
    """
    if not isinstance(payload, dict):
        raise ValueError("payload 必须是 dict")
    freq = _freq_axis_from(payload)
    out = diff_pair_chain_report(
        freq,
        odd_segments=list(_require(payload, "odd_segments", "payload")),
        even_segments=list(_require(payload, "even_segments", "payload")),
        z_ref_ohm=float(payload.get("z_ref_ohm", 50.0)),
    )
    return {
        "freq_hz": [float(x) for x in out["freq_hz"]],
        "sdd11_db": [float(x) for x in out["sdd11_db"]],
        "sdd21_db": [float(x) for x in out["sdd21_db"]],
        "scc11_db": [float(x) for x in out["scc11_db"]],
        "scc21_db": [float(x) for x in out["scc21_db"]],
        "mode_conversion_max_linear": out["mode_conversion_max_linear"],
        "basis": out["basis"],
        "passive": out["passive"],
        "source": out["source"],
    }


def bump_array_crosstalk_report(payload: dict[str, Any]) -> dict[str, Any]:
    """凸点阵互感/串扰邻对报告（JSON 进出；PK-7 filament exact 阵列化）。"""
    if not isinstance(payload, dict):
        raise ValueError("payload 必须是 dict")
    out = bump_array_mutual_matrix(
        int(_require(payload, "n_bumps", "payload")),
        height_m=float(_require(payload, "height_m", "payload")),
        diameter_m=float(_require(payload, "diameter_m", "payload")),
        pitch_m=float(_require(payload, "pitch_m", "payload")),
    )
    mutual = np.asarray(out["mutual_h"], dtype=float)
    k_mat = np.asarray(out["k_matrix"], dtype=float)
    return {
        "n_bumps": out["n_bumps"],
        "l_self_h": out["l_self_h"],
        "l_self_ph": out["l_self_h"] * 1e12,
        "mutual_ph": (mutual * 1e12).tolist(),
        "k_matrix": k_mat.tolist(),
        "k_neighbor": out["k_neighbor"],
        "in_declared_scope": out["in_declared_scope"],
        "source": out["source"],
    }
