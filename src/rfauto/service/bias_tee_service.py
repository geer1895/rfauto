"""M-6 bias tee service 面（JSON 进出，规则 4；CLI/MCP 是薄壳）。

消费 core/bias_tee.py 内核（综合闭式 + 三端口频响 + 泄漏带 + vendor 联动），
本服务零物理公式，全部数字出自确定性内核（规则 7）。

- :func:`bias_tee_report`：拐点/系统阻抗 (+可选 DC 电流选型下界) → 综合 +
  频响面（插损/RF-DC 隔离度/DC 馈通插损 dB 序列）+ 泄漏带边缘 + 解析
  恒等式对照（f_hi_edge vs 解析式）。
- 诚实边界：频响为理想 LC + 显式寄生 RLC 模型（与 vendor_passives 同式），
  非电磁仿真；两拐点同落 f_corner 的最小阶设计在带内近拐点处隔离度差
  是拓扑本性（内核 docstring 如实登记），报告按数值呈现不粉饰。

schema_version 语义区分（#106）：本服务 BIAS_TEE_SERVICE_SCHEMA_VERSION。
"""

from __future__ import annotations

import math
from typing import Any

from rfauto.core import bias_tee as bt

# F-13 批1：_num 并入 service/_helpers 单源（别名 import 保调用名/调用点零
# 改动；本地副本按 #116 治理纪律删净防遮蔽；W2-G 批 1 语义冻结钉
# tests/unit/test_w2_g_f13_batch1.py）。
from rfauto.service._helpers import parse_num as _num
from rfauto.service.envelope import error_envelope, ok_envelope

BIAS_TEE_SERVICE_SCHEMA_VERSION = "1.0"

#: 缺省频响轴：(start, stop, npts)，倍频程口径（×f_corner）
_DEFAULT_FREQ_SPAN = (0.01, 100.0, 801)
#: 响应面 JSON 抽样上限（点）
_MAX_SAMPLE_POINTS = 400


def _err(errors: list[str]) -> dict[str, Any]:
    return error_envelope(list(errors))


def bias_tee_report(payload: Any) -> dict[str, Any]:
    """bias tee 综合与频响报告。

    Args（payload 键）:
        f_corner_hz: 设计拐点（Hz，>0，必填）；
        z0_ohm: 系统阻抗（缺省 50）；
        dc_current_a: DC 馈电电流（A，可选 → required_isat_a 选型下界）；
        isat_margin: 饱和电流裕量（缺省 0.2）；
        freq_span: [start, stop, npts]（×f_corner 倍数，缺省 [0.01, 100, 801]）；
        threshold_db: 泄漏带门限（缺省 40 dB 隔离度）；
        parasitics: {choke_esr_ohm, choke_cp_f, block_esr_ohm, block_esl_h}（可选）。

    Returns:
        dict: {ok, schema_version, synthesis, faces: {f_ghz, insertion_loss_db,
        rf_dc_isolation_db, dc_feed_il_db}, leakage_band, analytic_hi_corner_hz,
        identity: {corner_ratio, impedance_ratio}}；参数缺失/非法 → ok=False。
    """
    errors: list[str] = []
    if not isinstance(payload, dict):
        return _err([f"payload 必须是 JSON 对象，实际 {type(payload).__name__}"])

    f_corner = _num(payload.get("f_corner_hz"), "f_corner_hz", errors, positive=True)
    z0 = _num(payload.get("z0_ohm", bt.DEFAULT_Z0), "z0_ohm", errors, positive=True)
    dc_current = payload.get("dc_current_a")
    if dc_current is not None:
        dc_current = _num(dc_current, "dc_current_a", errors, positive=True)
    isat_margin = _num(
        payload.get("isat_margin", bt.DEFAULT_ISAT_MARGIN), "isat_margin", errors
    )
    if errors or f_corner is None or z0 is None:
        return _err(errors or ["f_corner_hz 缺失"])

    try:
        syn = bt.synthesize_bias_tee(
            f_corner,
            z0,
            dc_current_a=dc_current,
            isat_margin=bt.DEFAULT_ISAT_MARGIN if isat_margin is None else isat_margin,
        )
    except ValueError as exc:
        return _err([str(exc)])

    span = payload.get("freq_span")
    if span is not None:
        if (
            not isinstance(span, (list, tuple))
            or len(span) != 3
            or isinstance(span[2], bool)
            or _num(span[0], "freq_span[0]", errors, positive=True) is None
            or _num(span[1], "freq_span[1]", errors, positive=True) is None
            or not isinstance(span[2], int)
            or span[2] < 2
        ):
            return _err(["freq_span 须为 [start, stop, npts]（npts≥2 整数，start/stop>0）"])
        start_f, stop_f, npts = float(span[0]), float(span[1]), int(span[2])
        if start_f >= stop_f:
            return _err(["freq_span 须 start < stop"])
    else:
        start_f, stop_f, npts = _DEFAULT_FREQ_SPAN
    threshold = _num(payload.get("threshold_db", 40.0), "threshold_db", errors)
    if errors or threshold is None:
        return _err(errors or ["threshold_db 非法"])
    par_in = payload.get("parasitics")
    try:
        par = bt.BiasTeeParasitics.from_dict(par_in if isinstance(par_in, dict) else None)
    except ValueError as exc:
        return _err([f"parasitics 非法: {exc}"])

    import numpy as np

    freqs = np.geomspace(start_f * f_corner, stop_f * f_corner, npts)
    try:
        s = bt.bias_tee_s(freqs, syn.l_choke_h, syn.c_block_f, par, z0)
    except ValueError as exc:
        return _err([str(exc)])
    band = bt.leakage_band(freqs, s, threshold)
    analytic_hi = bt.rf_dc_isolation_high_corner(syn.l_choke_h, z0, threshold)

    step = max(1, math.ceil(npts / _MAX_SAMPLE_POINTS))
    idx = list(range(0, npts, step))
    if idx[-1] != npts - 1:
        idx.append(npts - 1)
    sub = np.asarray(idx)
    faces = {
        "f_ghz": [float(freqs[i] / 1e9) for i in idx],
        "insertion_loss_db": [float(v) for v in bt.face_db(s, "rf", "comb")[sub]],
        "rf_dc_isolation_db": [float(v) for v in bt.face_db(s, "rf", "dc")[sub]],
        "dc_feed_il_db": [float(v) for v in bt.face_db(s, "comb", "dc")[sub]],
    }
    return ok_envelope(
        schema_version=BIAS_TEE_SERVICE_SCHEMA_VERSION,
        synthesis=syn.to_dict(),
        parasitics=par.to_dict(),
        port_order=list(bt.PORT_ORDER),
        faces=faces,
        leakage_band=band,
        analytic_hi_corner_hz=analytic_hi,
        identity={
            "corner_ratio": 1.0 / (2.0 * math.pi * math.sqrt(syn.l_choke_h * syn.c_block_f)) / f_corner,
            "impedance_ratio": math.sqrt(syn.l_choke_h / syn.c_block_f) / z0,
            "note": "理想回收恒等式（两比值恒为 1）；泄漏带上缘 ≈ 10^(thr/20)×f_corner",
        },
        disclaimer="理想 LC + 显式寄生 RLC 闭式模型（与 vendor_passives 同式），非电磁仿真",
    )
