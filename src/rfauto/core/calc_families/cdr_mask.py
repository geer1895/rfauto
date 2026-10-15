"""cdr_mask 族（DR-8 CDR 抖动传函/容限 mask 键面，SG 部分件残差收口）。

内核在 core/cdr_jitter_mask.py（闭式线性相位模型，#118 双锚内证：
JT(fc)=√2、高频平台→1、低频 −20dB/dec、peaking 闭式；测试钉
tests/unit/test_dr_stream_seat6.py），本模块只做注册薄壳（同
rx_impairments 惯例）。单键 cdr_jitter_mask：一阶/二阶 CDR 环路
JT(ω) 容限曲线 + 可选标准 mask 余量（mask 点列由调用方按所引标准给入，
本核不 ship 标准门限数值——#122 同纪律）。DR-8 登记语义"CALC+1"的键面
兑现（池/任务书双 ID：规格 round16 DR-8=任务书 DR-9，同核）。
"""

from __future__ import annotations

from typing import Any

from .registry import register_calculator


@register_calculator(
    "cdr_jitter_mask",
    "抖动容限曲线：DR-8 CDR 抖动容限 JT 曲线+mask 余量（线性相位模型，JT0=1 UI 归一）："
    "order='first' 走 H(s)=ωc/(s+ωc)，JT=√(ω²+ωc²)/ω（锚 JT(fc)=√2、高频"
    "平台→1、低频 −20dB/dec）；order='second' 走二阶 H(s)=ωn²/(s²+2ζωn·s"
    "+ωn²)（peaking |H|max=1/(2ζ√(1−ζ²))，ζ≥1/√2 无峰如实=1）。可选 "
    "mask=[[f,UI],...]（调用方按所引标准给入点列，对数-线性插值）：逐点 "
    "margin_db=20(log10 mask−log10 JT)，worst 点+verdict（pass/fail）。"
    "域守卫：freq 全正（JT 在 f→0 发散不外推直流）、ζ∈(0,2)、mask 点全正",
    (("freq_hz", "list[float] Hz 频率点列（>=2 点，全正；升序推荐）"),
     ("order", "str 'first'/'second'（缺省 'first'）"),
     ("fc_hz", "float Hz 一阶环路角频（order='first' 必填）"),
     ("fn_hz", "float Hz 二阶自然频率（order='second' 必填）"),
     ("zeta", "float 阻尼比（order='second' 必填，(0,2)）"),
     ("mask", "list[[f_hz, ui]] 可选标准 mask 点对（>=2 点，全正）")),
    required=("freq_hz",),
)
def cdr_jitter_mask(freq_hz: list[float], order: str = "first",
                    fc_hz: float | None = None, fn_hz: float | None = None,
                    zeta: float | None = None,
                    mask: list[list[float]] | None = None) -> dict:
    from rfauto.core.cdr_jitter_mask import (
        cdr_jitter_transfer_first_order,
        cdr_jitter_transfer_second_order,
        cdr_mask_margin,
        cdr_peaking_factor,
    )

    if order not in ("first", "second"):
        raise ValueError(f"order 只收 'first'/'second'，得 {order!r}")
    freq_list = [float(f) for f in (freq_hz or [])]
    if len(freq_list) < 2:
        raise ValueError(f"freq_hz 须 >=2 点（容限曲线非点值），得 {len(freq_list)}")
    if order == "first":
        if fc_hz is None:
            raise ValueError("order='first' 必须给 fc_hz")
        jt = cdr_jitter_transfer_first_order(freq_list, fc_hz)
        peaking = None  # 一阶无峰（|H|max=1，无 peaking 量）
    else:
        if fn_hz is None or zeta is None:
            raise ValueError("order='second' 必须给 fn_hz 与 zeta")
        jt = cdr_jitter_transfer_second_order(freq_list, fn_hz, zeta)
        peaking = cdr_peaking_factor(zeta)

    freq_out = [float(f) for f in freq_list]
    jt_out = [float(x) for x in jt]
    out: dict[str, Any] = {
        "order": order,
        "freq_hz": freq_out,
        "jt_ui": jt_out,
        "peaking": peaking,
        "jt_fc_ui": (float(cdr_jitter_transfer_first_order([fc_hz], fc_hz)[0])
                     if order == "first" else None),
    }
    if mask is not None:
        margin = cdr_mask_margin(freq_out, jt_out,
                                 [(m[0], m[1]) for m in mask])
        # numpy 数组 → JSON 契约面（list[float]；service JSON 进出）
        out["mask"] = {
            "mask_freq_hz": [float(x) for x in margin["mask_freq_hz"]],
            "mask_ui": [float(x) for x in margin["mask_ui"]],
            "jt_at_mask_ui": [float(x) for x in margin["jt_at_mask_ui"]],
            "margins_db": [float(x) for x in margin["margins_db"]],
            "worst_margin_db": margin["worst_margin_db"],
            "worst_freq_hz": margin["worst_freq_hz"],
            "verdict": margin["verdict"],
        }
    return out
