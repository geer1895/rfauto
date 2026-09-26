"""DP-2 耦合矩阵诊断 service（JSON 进出，服务层只编排——算法全在
core/calculators 的 5 个注册键，本模块零数值逻辑，#7 数值只在确定性内核）。

三件套：
- Q 双通道（q_factor_vf 极点法 × q_factor_circle 圆拟合）+ 互证 verdict
  （|ΔQu|/Qu≤10% → AGREE，超阈 UNDECIDABLE #122）+ skrf.qfactor 第三方仲裁
  （装了就用，三方极差 ≤15% 如实报）；
- CM 反向提取（cm_extract_vf 段一 + cm_refine_lm 段二）+ 可选目标矩阵逐元素
  偏差表 + ok 门；
- CAT 调谐 critique（cat_critique，Dishal 顺序调谐 issues+typed fixes）。

CLI ``rfauto diagnose`` 与 MCP ``cm_diagnose_q``/``cm_extract_refine``/
``cm_cat_critique`` 是本模块的薄壳。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rfauto.service.calculator_service import run_calculator

_CROSS_TOL = 0.10   # Q 双通道互证门（规格 §2b）
_THIRD_TOL = 0.15   # 三方极差门（判据族 ④）


def _load_touchstone(path: str, need_s21: bool) -> dict[str, Any]:
    """Touchstone → {freq_ghz, s11[, s21]}（skrf 只按 .sNp 扩展名推 rank，#248：
    调用方按端口数自证，rank 不足时显式报错不猜）。"""
    import skrf as skrf

    p = Path(path)
    if not p.is_file():
        raise ValueError(f"Touchstone 文件不存在: {path}")
    ntwk = skrf.Network(str(p))
    n_ports = ntwk.s.shape[1]
    if n_ports < 1:
        raise ValueError("Touchstone 无端口数据")
    freq_ghz = [round(float(v) / 1e9, 12) for v in ntwk.frequency.f]
    out: dict[str, Any] = {
        "freq_ghz": freq_ghz,
        "s11": [[complex(v).real, complex(v).imag]
                for v in ntwk.s[:, 0, 0]]}
    if need_s21:
        if n_ports < 2:
            raise ValueError("CM/透射诊断须 2 端口 Touchstone（.s2p 及以上）")
        out["s21"] = [[complex(v).real, complex(v).imag]
                      for v in ntwk.s[:, 1, 0]]
    return out


def _data_ports(request: dict[str, Any], need_s11: bool = True,
                need_s21: bool = False) -> dict[str, Any]:
    """输入归一：touchstone_path 或 freq_ghz+所需端口数组 二选一。"""
    path = request.get("touchstone_path")
    if path:
        return _load_touchstone(str(path), need_s21)
    freq = request.get("freq_ghz")
    if not freq:
        raise ValueError("须给 touchstone_path 或 freq_ghz+端口数据")
    s11 = request.get("s11")
    s21 = request.get("s21")
    if need_s11 and s11 is None:
        raise ValueError("该诊断模式须给 s11（或 touchstone_path）")
    if need_s21 and s21 is None:
        raise ValueError("该诊断模式须给 s21（或 touchstone_path）")
    out: dict[str, Any] = {"freq_ghz": [float(v) for v in freq]}
    if s11 is not None:
        out["s11"] = s11
    if s21 is not None:
        out["s21"] = s21
    return out


def _skrf_third_opinion(freq_ghz: list, s11: list) -> dict[str, Any] | None:
    """skrf.qfactor.Qfactor 第三方仲裁（NPL MAT58 NLQFIT）；缺席/失败如实
    返回 None，不阻塞主判定（#105 观测面 best-effort）。"""
    try:
        import numpy as np
        import skrf as skrf
        from skrf.qfactor import Qfactor

        g = np.array([complex(a, b) for a, b in s11])
        ntwk = skrf.Network(
            frequency=np.asarray(freq_ghz) * 1e9,
            s=g.reshape(-1, 1, 1), z0=50.0)
        qf = Qfactor(ntwk, res_type="reflection")
        res = qf.fit()
        return {"q_unloaded": round(float(qf.Q_unloaded(res)), 6),
                "q_loaded": round(float(res.Q_L), 6),
                "f_ghz": round(float(res.f_L) / 1e9, 9),
                "source": "skrf.qfactor.Qfactor(reflection)"}
    except Exception as exc:
        return {"source": "skrf.qfactor.Qfactor(reflection)",
                "unavailable": True, "error": str(exc)}


def diagnose_q(request: dict[str, Any]) -> dict[str, Any]:
    """Q 双通道 + 互证 verdict + skrf 第三方仲裁（JSON 进出）。"""
    data = _data_ports(request, need_s21=False)
    common = {"freq_ghz": data["freq_ghz"], "s11": data["s11"]}
    vf_req = dict(common)
    if request.get("f0_hint_ghz"):
        vf_req["f0_hint_ghz"] = float(request["f0_hint_ghz"])
    if request.get("q_e"):
        vf_req["q_e"] = request["q_e"]
    vf = run_calculator("q_factor_vf", vf_req)
    circle = run_calculator("q_factor_circle", dict(common))
    if not vf["ok"] or not circle["ok"]:
        return {"ok": False, "error": "Q 双通道执行失败: "
                f"vf={vf.get('error') or vf.get('result', {}).get('ok')}; "
                f"circle={circle.get('error') or circle.get('result', {}).get('ok')}"}
    rv, rc = vf["result"], circle["result"]
    qv = rv.get("q_unloaded")
    qc = rc.get("q_unloaded")
    verdict = "UNDECIDABLE"
    diff_pct = None
    if qv is not None and qc is not None and qc > 0:
        diff_pct = abs(qv - qc) / qc
        verdict = ("AGREE" if diff_pct <= _CROSS_TOL else "UNDECIDABLE")
    third = _skrf_third_opinion(data["freq_ghz"], data["s11"])
    third_note = None
    if verdict == "AGREE" and qv is not None and third \
            and not third.get("unavailable"):
        range_pct = max(qv, qc, third["q_unloaded"]) \
            - min(qv, qc, third["q_unloaded"])
        range_pct /= max(qv, qc, third["q_unloaded"])
        third_note = {"range_pct": round(range_pct, 6),
                      "within_15pct": bool(range_pct <= _THIRD_TOL)}
    return {"ok": True, "result": {
        "vf": rv, "circle": rc,
        "verdict": verdict,
        "cross_diff_pct": (round(diff_pct, 6) if diff_pct is not None
                           else None),
        "cross_tol": _CROSS_TOL,
        "third_opinion": third,
        "third_check": third_note,
        "method": "q_dual_channel+skrf_arbitration"}}


def diagnose_cm(request: dict[str, Any]) -> dict[str, Any]:
    """CM 反向提取（VF 段一 + LM 段二）+ 可选目标逐元素偏差表（JSON 进出）。"""
    data = _data_ports(request, need_s21=True)
    common = {"freq_ghz": data["freq_ghz"], "s11": data["s11"],
              "s21": data["s21"]}
    if request.get("f0_ghz"):
        common["f0_ghz"] = float(request["f0_ghz"])
    if request.get("fbw"):
        common["fbw"] = float(request["fbw"])
    if request.get("order") is not None:
        common["order"] = int(request["order"])
    ext = run_calculator("cm_extract_vf", dict(
        common, topology=request.get("topology", "folded")))
    if not ext["ok"]:
        return {"ok": False, "error": f"cm_extract_vf 失败: {ext.get('error')}"}
    rext = ext["result"]
    refine_req = dict(common)
    refine_req.update({
        "matrix": rext["coupling_matrix"],
        "f0_ghz": rext["f0_ghz"], "fbw": rext["fbw"],
        "topology": rext["topology"],
        "transmission_zeros_norm": rext["transmission_zeros_norm"]})
    ref = run_calculator("cm_refine_lm", refine_req)
    if not ref["ok"]:
        return {"ok": False, "error": f"cm_refine_lm 失败: {ref.get('error')}"}
    rref = ref["result"]
    out: dict[str, Any] = {"extract": rext, "refine": rref}
    target = request.get("target_matrix")
    if target:
        from rfauto.core.calculators import (
            _cm_from_list,
            _cm_reduce_folded,
            _cm_sign_normalize,
        )

        m_hat = _cm_from_list(rref["coupling_matrix"])
        m_tgt, _ = _cm_reduce_folded(_cm_from_list(target))
        m_hat_n, _ = _cm_sign_normalize(m_hat)
        m_tgt_n, _ = _cm_sign_normalize(m_tgt)
        devs = []
        n2 = m_tgt_n.shape[0]
        for i in range(n2):
            for j in range(i + 1, n2):
                if abs(m_tgt_n[i, j]) <= 1e-9:
                    continue
                dev = abs(m_hat_n[i, j] - m_tgt_n[i, j]) / abs(m_tgt_n[i, j])
                devs.append({"i": i, "j": j,
                             "target": [round(m_tgt_n[i, j].real, 9),
                                        round(m_tgt_n[i, j].imag, 9)],
                             "refined": [round(m_hat_n[i, j].real, 9),
                                         round(m_hat_n[i, j].imag, 9)],
                             "rel_dev": round(float(dev), 6)})
        max_dev = max((d["rel_dev"] for d in devs), default=0.0)
        out["target_check"] = {
            "elements": devs, "max_rel_dev": max_dev,
            "tol": 0.05, "pass": bool(max_dev <= 0.05)}
    return {"ok": True, "result": out}


def diagnose_cat(request: dict[str, Any]) -> dict[str, Any]:
    """Dishal 顺序调谐 critique 薄壳（JSON 进出）。s21 透射口径（C=2）缺省，
    显式给 s11 走反射口径（C=4，见 calculators 模块头 C 系数裁决）。"""
    use_reflection = request.get("s11") is not None \
        and not request.get("touchstone_path")
    data = _data_ports(request, need_s11=use_reflection,
                       need_s21=not use_reflection)
    req: dict[str, Any] = {
        "freq_ghz": data["freq_ghz"], "f0_ghz": float(request["f0_ghz"]),
        "fbw": float(request["fbw"]),
        "target_matrix": request["target_matrix"]}
    if use_reflection:
        req["s11"] = data["s11"]
    else:
        req["s21"] = data["s21"]
    for key in ("current_params", "bounds"):
        if request.get(key):
            req[key] = request[key]
    if request.get("max_step_pct") is not None:
        req["max_step_pct"] = float(request["max_step_pct"])
    if request.get("tol") is not None:
        req["tol"] = float(request["tol"])
    return run_calculator("cat_critique", req)


def run_diagnosis(request: dict[str, Any]) -> dict[str, Any]:
    """DP-2 诊断总入口（mode 分派，缺省 full=Q 双通道+CM 反提，CAT 需 s21+目标）。

    request: {mode: "full"|"q"|"cm"|"cat", touchstone_path | freq_ghz+s11+s21,
              f0_ghz/fbw/order/topology/target_matrix/q_e/...}
    """
    if not isinstance(request, dict):
        return {"ok": False, "error": "request 须为 dict"}
    mode = request.get("mode", "full")
    try:
        if mode == "q":
            return diagnose_q(request)
        if mode == "cm":
            return diagnose_cm(request)
        if mode == "cat":
            if not request.get("target_matrix"):
                raise ValueError("cat 模式须给 target_matrix")
            if request.get("f0_ghz") is None or request.get("fbw") is None:
                raise ValueError("cat 模式须给 f0_ghz 与 fbw")
            return diagnose_cat(request)
        if mode == "full":
            out: dict[str, Any] = {"ok": True, "result": {}}
            out["result"]["q"] = diagnose_q(request)
            cm_req = {k: v for k, v in request.items() if k != "q_e"}
            out["result"]["cm"] = diagnose_cm(cm_req)
            if request.get("target_matrix") and request.get("fbw") \
                    and request.get("f0_ghz"):
                try:
                    out["result"]["cat"] = diagnose_cat(request)
                except (ValueError, KeyError) as exc:
                    out["result"]["cat"] = {"ok": False, "error": str(exc)}
            return out
        return {"ok": False, "error": f"未知 mode: {mode}（full|q|cm|cat）"}
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
