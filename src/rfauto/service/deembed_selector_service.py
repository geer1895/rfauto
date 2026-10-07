"""MS-3 去嵌方法选择裁判服务（SB22-4a，2026-10-05 W4-D）。

从"这次去嵌好不好"（core/deembed_referee 已答）升到"这个夹具该用哪种
去嵌"：五法统一入口 × 合成夹具真值（core/synthetic_fixture）→ 逐法
s_error_max（vs 已知真值）+ 适用域守卫（inapplicable 如实不硬算，#122）
+ 排名 + 无去嵌劣化地板参照。

方法族（五法 + 变体，method id → 实现面）：
- ``afr_2xthru``：自研 AFR（measurement/afr_2xthru.deembed_2xthru，
  IEEEP370 NZC 包装+预检门）；
- ``p370_nzc``：skrf IEEEP370_SE_NZC_2xThru 直连（core/deembed_referee
  同款 DC 预处理链，无预检门）；
- ``p370_zc``：IEEEP370_SE_ZC_2xThru（需 fix-dut-fix 第二实测件；合成
  语料不达标为 DP-15 C2 在档结论——结果照出、gated=False 不设门）；
- ``split_tee`` / ``split_pi``：skrf SplitTee/SplitPi 对切（对称夹具
  +集总等效域前提：分布线夹具超域时数值如实变差，排名自然沉底）；
- ``inhouse_gamma_diff``：自研 γ 差分链（core/deembed_referee 同款，
  无先验=50Ω 假设——ΔZ 劣化的敏感面）；
- ``z0_prior_inhouse``：阻抗先验混合档（同链+fixture 阻抗先验：夹具
  ABCD 以先验 Z0 重建在 50Ω 参考域——先验正确时失配回收，先验缺失时
  不可用）。

适用域守卫（预声明）：
- split_tee/split_pi：2x-thru 对称性 |S11−S22| ≤ sym_tol（缺省 1e-3，
  线性域）——不对称夹具显式 inapplicable，不产数值（判据 3）；
- p370_zc：缺 fix-dut-fix 实测件 → inapplicable；
- 其余方法无结构前提（预检失败走 ok=False + error 字段，照出）。

判读口径（规格 §4a.4 ② 预声明）：输出含无去嵌劣化地板
``baseline_s_error_max``（DUT 直读 vs 真值），方法优劣只对
``vs_baseline_ratio``（比地板好多少）下结论。排名=适用且成功的
方法按 s_error_max 升序。全部确定性：同输入两次运行逐位一致（判据 4）。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import skrf

from rfauto.core.deembed import _as_network, _positive_finite
from rfauto.core.deembed_referee import (
    DEFAULT_DC_MODE,
    DEFAULT_S_ERROR_FUNCTION,
    s_error_max,
)
from rfauto.core.synthetic_fixture import s_param_asymmetry
from rfauto.measurement.afr_2xthru import DEFAULT_SYM_TOL, deembed_2xthru
from rfauto.service.envelope import (
    error_envelope,
    ok_envelope,
    skipped_envelope,
)

#: 方法注册面（五法族 + γ 差分基线变体；名称稳定性随 1.0 服务面冻结）。
DEEMBED_METHODS: tuple[str, ...] = (
    "afr_2xthru",
    "p370_nzc",
    "p370_zc",
    "split_tee",
    "split_pi",
    "inhouse_gamma_diff",
    "z0_prior_inhouse",
)

#: 对切法（SplitTee/SplitPi）族成员。
SPLIT_METHODS: tuple[str, ...] = ("split_tee", "split_pi")


def _dc_preprocess(net: skrf.Network, dc_mode: str | None) -> skrf.Network:
    """P370 输入 DC 预处理（沿 core/deembed_referee 同款白名单）。"""
    from skrf.calibration.deembedding import IEEEP370_SE_NZC_2xThru

    if dc_mode is None:
        return net
    if dc_mode == "extrapolate_to_dc":
        return IEEEP370_SE_NZC_2xThru.extrapolate_to_dc(net)
    if dc_mode == "add_dc":
        return IEEEP370_SE_NZC_2xThru.add_dc(net)
    raise ValueError(
        f"dc_mode 只能是 'extrapolate_to_dc'/'add_dc'/None，实际 {dc_mode!r}")


def _back_to_grid(net: skrf.Network, freq: skrf.Frequency) -> skrf.Network:
    """P370/ZC 结果栅格插值回原栅格。"""
    if net.frequency == freq:
        return net
    return net.interpolate(freq)


def _fixture_abcd_network(
    freq: skrf.Frequency,
    gamma: np.ndarray,
    z0_line: float,
    length_m: float,
    z0_ref: float = 50.0,
) -> skrf.Network:
    """夹具线以先验 Z0 重建在公共 z0_ref 参考域（ABCD→S 标准式）。

    失配先验的正确口径：线本体 Z0=z0_line，但网络参考阻抗必须与被测件
    一致（z0_ref）——失配反射显式进入 S 参量后级联才物理正确（直接
    Network(z0=z0_line) 再 ``**`` 级联会静默漏掉参考面失配反射）。
    """
    from rfauto.core.synthetic_fixture import _a2s

    gl = gamma * length_m
    ch = np.cosh(gl)
    sh = np.sinh(gl)
    ab = np.empty((np.asarray(gamma).size, 2, 2), dtype=complex)
    ab[:, 0, 0] = ch
    ab[:, 0, 1] = z0_line * sh
    ab[:, 1, 0] = sh / z0_line
    ab[:, 1, 1] = ch
    return skrf.Network(frequency=freq, s=_a2s(ab, z0_ref), z0=z0_ref)


def _deembed_inhouse(
    dut_fdf: skrf.Network,
    twoxthru: skrf.Network,
    fixture_length_m: float,
    z0_prior_ohm: float | None,
) -> skrf.Network:
    """自研 γ 差分链（referee 同款）+ 可选阻抗先验（服务层重建口径）。"""
    from rfauto.core.deembed import (
        deembed_reference_plane,
        extract_line_gamma,
        ideal_line_network,
    )

    freq = dut_fdf.frequency
    identity = ideal_line_network(freq, 0.0, 0.0, z0=50.0)
    gamma = extract_line_gamma(identity, twoxthru, 2.0 * fixture_length_m)
    if z0_prior_ohm is None:
        fix = ideal_line_network(freq, fixture_length_m, gamma, z0=50.0)
    else:
        fix = _fixture_abcd_network(freq, gamma, float(z0_prior_ohm),
                                    fixture_length_m)
    out = deembed_reference_plane(dut_fdf, fix, side="input")
    return deembed_reference_plane(out, fix, side="output")


def _run_method(
    method: str,
    networks: Mapping[str, Any],
    opts: dict[str, Any],
) -> dict[str, Any]:
    """单方法执行：返回 {applicable, inapplicable_reason?, ok, error?,
    network?}（s_error 由调用方统一评）。"""
    dut_fdf: skrf.Network = networks["dut_fdf"]
    twoxthru: skrf.Network = networks["twoxthru"]
    dc_mode = opts.get("dc_mode", DEFAULT_DC_MODE)

    if method in SPLIT_METHODS:
        sym = s_param_asymmetry(twoxthru)
        sym_tol = float(opts.get("sym_tol", DEFAULT_SYM_TOL))
        if sym > sym_tol:
            text = (f"对切法要求对称夹具前提：2x-thru max|S11-S22|={sym:.3e} "
                    f"> sym_tol={sym_tol:.1e}"
                    "（两侧不对称，等效电路撕裂不成立）")
            return skipped_envelope(
                text, applicable=False, method=method,
                inapplicable_reason=text)
    if method == "p370_zc" and networks.get("zc_fix_dut_fix") is None:
        return skipped_envelope(
            "ZC 变体需 fix-dut-fix 第二实测件（zc_fix_dut_fix 缺失）",
            applicable=False, method=method,
            inapplicable_reason=(
                "ZC 变体需 fix-dut-fix 第二实测件（zc_fix_dut_fix 缺失）"))
    if method in ("inhouse_gamma_diff", "z0_prior_inhouse") and (
            opts.get("fixture_length_m") is None):
        return skipped_envelope(
            "自研 γ 差分链需 fixture_length_m（单侧夹具几何先验）",
            applicable=False, method=method,
            inapplicable_reason="自研 γ 差分链需 fixture_length_m（单侧夹具几何先验）")
    if method == "z0_prior_inhouse" and (
            opts.get("fixture_z0_prior_ohm") is None):
        return skipped_envelope(
            "阻抗先验混合档需 fixture_z0_prior_ohm（无先验走 inhouse_gamma_diff）",
            applicable=False, method=method,
            inapplicable_reason=(
                "阻抗先验混合档需 fixture_z0_prior_ohm（无先验走 "
                "inhouse_gamma_diff）"))

    try:
        if method == "afr_2xthru":
            kwargs: dict[str, Any] = {}
            if "dc_mode" in opts:
                kwargs["dc_mode"] = opts["dc_mode"]
            if "sym_tol" in opts:
                kwargs["sym_tol"] = opts["sym_tol"]
            if "smooth_tol_db" in opts:
                kwargs["smooth_tol_db"] = opts["smooth_tol_db"]
            res = deembed_2xthru(dut_fdf, twoxthru, **kwargs)
            if not res["ok"]:
                return error_envelope(
                    str(res.get("error", "AFR 预检不过")),
                    applicable=True, method=method, gated=False,
                    precheck=res.get("precheck"))
            return ok_envelope(applicable=True, method=method, gated=True,
                               network=res["network"])
        if method == "p370_nzc":
            from skrf.calibration.deembedding import IEEEP370_SE_NZC_2xThru

            th = _dc_preprocess(twoxthru, dc_mode)
            ff = _dc_preprocess(dut_fdf, dc_mode)
            deembedder = IEEEP370_SE_NZC_2xThru(
                dummy_2xthru=th, name="rfauto_ms3_nzc",
                z0=float(np.real(np.mean(dut_fdf.z0[:, 0]))))
            return ok_envelope(
                applicable=True, method=method, gated=True,
                network=_back_to_grid(deembedder.deembed(ff),
                                      dut_fdf.frequency))
        if method == "p370_zc":
            from skrf.calibration.deembedding import IEEEP370_SE_ZC_2xThru

            zc_in = _as_network(networks["zc_fix_dut_fix"], "zc_fix_dut_fix")
            th = _dc_preprocess(twoxthru, dc_mode)
            ff = _dc_preprocess(zc_in, dc_mode)
            zc = IEEEP370_SE_ZC_2xThru(
                dummy_2xthru=th, dummy_fix_dut_fix=ff,
                name="rfauto_ms3_zc",
                z0=float(np.real(np.mean(zc_in.z0[:, 0]))))
            # DP-15 C2 在档结论：合成解析语料 ZC 不达标，结果照出不设门
            return ok_envelope(
                applicable=True, method=method, gated=False,
                network=_back_to_grid(zc.deembed(ff), dut_fdf.frequency))
        if method in SPLIT_METHODS:
            from skrf.calibration.deembedding import SplitPi, SplitTee

            cls = SplitTee if method == "split_tee" else SplitPi
            deembedder = cls(twoxthru, name=f"rfauto_ms3_{method}")
            return ok_envelope(applicable=True, method=method, gated=True,
                               network=deembedder.deembed(dut_fdf))
        if method == "inhouse_gamma_diff":
            length = _positive_finite(opts["fixture_length_m"],
                                      "fixture_length_m")
            return ok_envelope(
                applicable=True, method=method, gated=True,
                network=_deembed_inhouse(dut_fdf, twoxthru, length, None))
        if method == "z0_prior_inhouse":
            length = _positive_finite(opts["fixture_length_m"],
                                      "fixture_length_m")
            prior = _positive_finite(opts["fixture_z0_prior_ohm"],
                                     "fixture_z0_prior_ohm")
            return ok_envelope(
                applicable=True, method=method, gated=True,
                network=_deembed_inhouse(dut_fdf, twoxthru, length, prior))
    except Exception as exc:  # 方法级失败如实透出，不终裁（BLE001 有意豁免）
        return error_envelope(f"{type(exc).__name__}: {exc}",
                              applicable=True, method=method, gated=False)
    raise ValueError(f"未知方法 {method!r}（注册面: {', '.join(DEEMBED_METHODS)}）")


def select_deembed_method(
    networks: Mapping[str, Any],
    options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """五法统一入口：逐法适用域守卫+回收误差+排名（纯 JSON 信封）。

    Args:
        networks: {dut_fdf, twoxthru, dut_reference, zc_fix_dut_fix?}——
            全部 skrf.Network 同栅格 2 端口；dut_reference=已知真值
            （合成语料由 core/synthetic_fixture 产出；实测场景不可得时
            传 None，则 s_error/ranking 如实缺省，只出适用域结论）。
        options: {gate_threshold=1e-6, sym_tol=1e-3, dc_mode, s_error_function,
            fixture_length_m（inhouse 族必填）, fixture_z0_prior_ohm
            （z0_prior_inhouse 必填）, methods（子集选择）}。

    Returns:
        {baseline_s_error_max, methods: [{method, applicable,
        inapplicable_reason?, ok, error?, gated, s_error_max?,
        vs_baseline_ratio?, rank?}], ranking: [method...], gate_threshold,
        n_points, note}
    """
    opts = dict(options or {})
    dut_fdf = _as_network(networks["dut_fdf"], "dut_fdf")
    twoxthru = _as_network(networks["twoxthru"], "twoxthru")
    reference = networks.get("dut_reference")
    if reference is not None:
        reference = _as_network(reference, "dut_reference")
        if reference.nports != dut_fdf.nports:
            raise ValueError("dut_reference 与 dut_fdf 端口数不一致")
        if reference.frequency != dut_fdf.frequency:
            raise ValueError("dut_reference 与 dut_fdf 频率栅格不一致")
    if dut_fdf.nports != 2 or twoxthru.nports != 2:
        raise ValueError("本裁判面只支持 2 端口语料")
    if twoxthru.frequency != dut_fdf.frequency:
        raise ValueError("twoxthru 与 dut_fdf 频率栅格不一致")
    gate = _positive_finite(opts.get("gate_threshold", 1e-6), "gate_threshold",
                            allow_zero=True)
    err_fn = str(opts.get("s_error_function", DEFAULT_S_ERROR_FUNCTION))

    baseline = (
        float(s_error_max(dut_fdf, reference, err_fn))
        if reference is not None else None)

    method_ids = tuple(opts.get("methods", DEEMBED_METHODS))
    unknown = [m for m in method_ids if m not in DEEMBED_METHODS]
    if unknown:
        raise ValueError(
            f"未知方法 {unknown}（注册面: {', '.join(DEEMBED_METHODS)}）")

    entries: list[dict[str, Any]] = []
    for method in method_ids:
        run = _run_method(method, networks, opts)
        if run.get("skipped") is True:
            entries.append(skipped_envelope(
                str(run.get("reason", "")),
                method=method, applicable=False,
                inapplicable_reason=str(
                    run.get("inapplicable_reason", ""))))
            continue
        if run.get("ok") is False:
            entries.append(error_envelope(
                run.get("errors"), method=method, applicable=True,
                gated=False,
                **({"precheck": run["precheck"]} if "precheck" in run else {})))
            continue
        net: skrf.Network = run["network"]
        gated = bool(run.get("gated", False))
        fields: dict[str, Any] = {}
        if reference is not None:
            s_err = float(s_error_max(net, reference, err_fn))
            fields["s_error_max"] = s_err
            fields["meets_gate"] = bool(s_err < gate) and gated
            if baseline is not None and baseline > 0.0:
                fields["vs_baseline_ratio"] = s_err / baseline
        entries.append(ok_envelope(method=method, applicable=True,
                                   gated=gated, **fields))

    if reference is not None:
        ranked = sorted(
            (e for e in entries
             if e["applicable"] and e["ok"] and e.get("s_error_max") is not None),
            key=lambda e: e["s_error_max"])
        for i, e in enumerate(ranked):
            e["rank"] = i + 1
        ranking = [e["method"] for e in ranked]
    else:
        ranking = []

    return ok_envelope(
        baseline_s_error_max=baseline,
        methods=entries,
        ranking=ranking,
        gate_threshold=gate,
        n_points=int(np.asarray(dut_fdf.f).size),
        note="劣化地板=无去嵌 DUT 直读 vs 真值；方法优劣只对 vs_baseline_ratio "
        "下结论（规格 §4a.4 预声明）；p370_zc gated=False（DP-15 C2 合成语料 "
        "不达标在档结论，结果照出不设门）；对切法守卫=2x-thru 对称性"
        "（S11 vs S22 线性域）",
    )
