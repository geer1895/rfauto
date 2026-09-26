"""DP-1 P2：MMT 秒级求解服务薄壳（JSON 进出，CLI/MCP 是薄壳；#4）。

单入口 :func:`solve_mmt`：payload（sections 段表 mm + freqs_ghz 网格 +
mode_policy）→ **经全局注册表** create(EMSolverType.MMT)（判据 G-P2-1
注册全链即此路径）→ build_geometry → solve（solve_chain → renormalize
z0_ref=50Ω → skrf Network → openEMS 同构产物）→ JSON 信封。

诚实口径（#122；P1 判据 runs/df6_dp1mmt/criteria.md §0 继承）：
- undetermined 频点 S=null 不外推、逐点列进 undetermined_freqs_ghz；
- converged/warnings 原样透传不掩盖；
- 膜片/阶梯绝对 S 值 UNDECIDABLE（absolute_s_note 随信封返回），
  绝对值裁决归 G1 HFSS 仲裁（P3）。
失败路径 ok=False + errors（不抛异常不静默）；工作目录缺省临时目录，
调用方给 work_dir 时产物落指定处（runs/ 真档不由本服务自作主张写入）。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

#: 信封携带的诚实声明（与 adapters/mmt_adapter 同源文案，单一出处）
_ABSOLUTE_S_NOTE = (
    "膜片/阶梯的绝对 S 值 UNDECIDABLE（P1 判据 runs/df6_dp1mmt/criteria.md "
    "§0）：连续性/无源/互易/×2 收敛门已过，绝对值归 G1 HFSS 仲裁（P3）"
)


def solve_mmt(payload: dict[str, Any],
              *, work_dir: str | Path | None = None) -> dict[str, Any]:
    """MMT 段表求解（JSON 进出）。

    payload 契约（mm 口径，见 adapters/mmt_adapter.build_geometry docstring）：
        sections: [uniform|hstep|iris, ...]（必填）
        freqs_ghz: [f1, ...] 或 freq_start_ghz/freq_stop_ghz/n_freq
        eps_r/tan_d/sigma_s_m：顶层材质缺省（段内可覆盖）
        mode_policy: core.ModePolicy 同名键（可选）
        z0_ref: 端口参考阻抗（缺省 50）

    返回 dict：ok/status/engine/work_dir/freqs_ghz/s11/s21/s12/s22/
    z_pv_ports/beta_te10_ports/converged/warnings/undetermined_freqs_ghz/
    n_modes/artifacts/absolute_s_note/message；失败 ok=False + errors。
    """
    if not isinstance(payload, dict):
        return {"ok": False, "status": "bad_request",
                "errors": [f"payload 必须为对象，得到 {type(payload).__name__}"]}
    sections = payload.get("sections")
    if not isinstance(sections, list) or not sections:
        return {"ok": False, "status": "bad_request",
                "errors": ["payload.sections 必须为非空段表列表"]}
    wd = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="rfauto_mmt_"))
    wd.mkdir(parents=True, exist_ok=True)

    from rfauto.adapters.em_solver_base import (
        EMSolverConfig,
        EMSolverType,
        get_global_registry,
    )

    config = EMSolverConfig(solver_type=EMSolverType.MMT, working_dir=str(wd))
    try:
        adapter = get_global_registry().create(EMSolverType.MMT, config)
    except ValueError as exc:
        return {"ok": False, "status": "unregistered", "errors": [str(exc)]}
    geometry = {k: v for k, v in payload.items() if k != "work_dir"}
    if not adapter.build_geometry(geometry):
        reason = getattr(adapter, "_last_error", None) or "build_geometry 失败"
        return {"ok": False,
                "status": ("bad_request" if "解析失败" in str(reason)
                           else "build_failed"),
                "errors": [str(reason)]}
    result = adapter.solve()
    if not result.success:
        return {"ok": False, "status": "solve_failed",
                "errors": [str(result.message)]}
    meta = dict(adapter.get_meta() or {})
    return {
        "ok": True,
        "status": "ok",
        "engine": "mmt",
        "work_dir": str(wd),
        "freqs_ghz": meta.get("freqs_ghz", []),
        "s11": meta.get("s11", []),
        "s21": meta.get("s21", []),
        "s12": meta.get("s12", []),
        "s22": meta.get("s22", []),
        "z_pv_ports": meta.get("z_pv_ports", []),
        "beta_te10_ports": meta.get("beta_te10_ports", []),
        "converged": bool(meta.get("converged", False)),
        "n_modes": meta.get("n_modes", []),
        "warnings": meta.get("warnings", []),
        "n_determined": meta.get("n_determined", 0),
        "n_undetermined": meta.get("n_undetermined", 0),
        "undetermined_freqs_ghz": meta.get("undetermined_freqs_ghz", []),
        "sections": meta.get("sections", []),
        "z0_ref": meta.get("z0_ref", 50.0),
        "artifacts": {
            "sparams_csv": str(wd / "sparams.csv"),
            "touchstone": str(wd / "mmt.s2p"),
            "meta": str(wd / "mmt_meta.json"),
        },
        "absolute_s_note": _ABSOLUTE_S_NOTE,
        "message": str(result.message),
    }


def solve_mmt_from_file(sections_path: str | Path,
                        *, work_dir: str | Path | None = None,
                        **overrides: Any) -> dict[str, Any]:
    """文件入口：段表 JSON 文件 → :func:`solve_mmt`（CLI --sections-file 用）。"""
    path = Path(sections_path)
    if not path.is_file():
        return {"ok": False, "status": "bad_request",
                "errors": [f"段表文件不存在: {path}"]}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "status": "bad_request",
                "errors": [f"段表文件解析失败: {exc}"]}
    if isinstance(payload, dict):
        payload = {**payload, **overrides}
    return solve_mmt(payload, work_dir=work_dir)


def iris_refinement_report(payload: dict[str, Any]) -> dict[str, Any]:
    """DP-1④ 膜片精化对照 + G1 触发判定报告（JSON 进出薄壳；#4）。

    编排 core.rwg_mmt.iris_refinement_comparison（缺省腿恒走 solve_chain
    原路径；精化腿仅 refined 段表 + status="active" 槽位同时在场才产数）
    与 g1_systematic_bias_check（带符号偏差方向系统性判定，可选）。
    JSON→chain 解析复用 adapters/mmt_adapter.parse_sections 等既有纯函数
    （零逻辑重复）；core 返回值本就 JSON 可序列化，原样透传不掩盖。

    **MCP/CLI 本项不接**（五钉清单不扩张，接线留后续批次登记）；
    本函数先落 service 面 + 合成链单测。

    payload 契约（段表 mm 口径同 :func:`solve_mmt`）：
        sections         : [uniform|hstep|iris, ...]（必填，缺省腿）
        freqs_ghz        : [f1, ...] 或 freq_start_ghz/freq_stop_ghz/n_freq
        eps_r/tan_d/sigma_s_m：顶层材质缺省（段内可覆盖）
        refined_sections : 精化腿段表（可选；与 refinement_slot 配对）
        refinement_slot  : {formula_id, status("blocked"|"active"),
                            candidate_formula, source, verification_note}
                           （可选；blocked=公式候选登记在案未核对，禁数值）
        mode_policy      : core.ModePolicy 同名键（可选）
        g1               : {signed_dev_db: [...], judged: [bool]|null,
                            sign_fraction_threshold, tie_db}（可选；
                            signed_dev_db 与频网同长）

    返回 dict：ok/status/engine/comparison（core 对照 dict，schema
    rfauto-mmt-refinement/v1，含 refinement 槽位元数据透传与 blocked
    语义）/g1（判定 dict 或 null）。blocked 槽位 + refined 段表、或无槽位
    裸 refined 段表 → ok=False（core ValueError 消息透传进 errors，
    #122 不冒充）；段表/频网/g1 形状非法、refinement_slot 非对象或
    status 非法（core ValueError → 信封，不抛 #175 严格校验）→
    bad_request 信封（不抛异常）；g1.judged 元素严格 bool 校验
    （禁 bool() 强转：bool("no")/bool(0.0) 类静默翻转一律拒绝）。
    """
    if not isinstance(payload, dict):
        return {"ok": False, "status": "bad_request",
                "errors": [f"payload 必须为对象，得到 {type(payload).__name__}"]}
    sections = payload.get("sections")
    if not isinstance(sections, list) or not sections:
        return {"ok": False, "status": "bad_request",
                "errors": ["payload.sections 必须为非空段表列表"]}

    import numpy as np

    from rfauto.adapters.em_solver_base import EMSolverConfig, EMSolverType
    from rfauto.adapters.mmt_adapter import (
        MmtError,
        freqs_from_json,
        mode_policy_from_json,
        parse_sections,
    )
    from rfauto.core.rwg_mmt import (
        RefinementSlot,
        g1_systematic_bias_check,
        iris_refinement_comparison,
    )

    defaults = {k: payload[k] for k in ("eps_r", "tan_d", "sigma_s_m")
                if payload.get(k) is not None}
    # refinement_slot 契约（P2）：非对象 → bad_request 信封（此前
    # slot_raw.get 对非 dict 裸抛 AttributeError 击穿信封契约）；
    # RefinementSlot 构造的裸 ValueError（status 非法等）同样转信封。
    slot_raw = payload.get("refinement_slot")
    if slot_raw is not None and not isinstance(slot_raw, dict):
        return {"ok": False, "status": "bad_request",
                "errors": [f"payload.refinement_slot 必须为对象，得到 "
                           f"{type(slot_raw).__name__}"]}
    try:
        chain = parse_sections(sections, defaults)
        refined_raw = payload.get("refined_sections")
        refined_chain = (parse_sections(refined_raw, defaults)
                         if refined_raw is not None else None)
        try:
            slot = (RefinementSlot(
                formula_id=str(slot_raw.get("formula_id", "")),
                status=str(slot_raw.get("status", "")),
                candidate_formula=str(slot_raw.get("candidate_formula", "")),
                source=str(slot_raw.get("source", "")),
                verification_note=str(slot_raw.get("verification_note", "")),
            ) if slot_raw is not None else None)
        except ValueError as exc:
            return {"ok": False, "status": "bad_request",
                    "errors": [f"refinement_slot: {exc}"]}
        freqs_hz = freqs_from_json(
            payload, EMSolverConfig(solver_type=EMSolverType.MMT))
        policy = mode_policy_from_json(payload.get("mode_policy"))
    except MmtError as exc:
        return {"ok": False, "status": "bad_request", "errors": [str(exc)]}

    try:
        comparison = iris_refinement_comparison(
            chain, freqs_hz, policy,
            refined_chain=refined_chain, refinement_slot=slot)
    except ValueError as exc:
        # blocked 槽位 + refined 数值 / 无槽位裸 refined —— core 显式拒绝
        # 的语义违规，消息透传进信封（不冒充不吞，#122）
        return {"ok": False, "status": "refinement_violation",
                "errors": [str(exc)], "comparison": None, "g1": None}

    g1_out = None
    g1_raw = payload.get("g1")
    if g1_raw is not None:
        if not isinstance(g1_raw, dict):
            return {"ok": False, "status": "bad_request",
                    "errors": ["payload.g1 必须为对象"]}
        dev_raw = g1_raw.get("signed_dev_db")
        if not isinstance(dev_raw, list):
            return {"ok": False, "status": "bad_request",
                    "errors": ["payload.g1.signed_dev_db 必须为数值列表"]}
        try:
            dev = np.asarray([float(x) for x in dev_raw], dtype=float)
        except (TypeError, ValueError) as exc:
            return {"ok": False, "status": "bad_request",
                    "errors": [f"g1.signed_dev_db 含非数值元素: {exc}"]}
        if dev.size != freqs_hz.size:
            return {"ok": False, "status": "bad_request",
                    "errors": [f"g1.signed_dev_db 长度 {dev.size} 与频网 "
                               f"{freqs_hz.size} 不一致"]}
        judged_raw = g1_raw.get("judged")
        if judged_raw is not None:
            if not isinstance(judged_raw, list) or len(judged_raw) != freqs_hz.size:
                return {"ok": False, "status": "bad_request",
                        "errors": ["g1.judged 须为与频网同长的布尔列表"]}
            # P2 严格 bool 校验（禁 bool() 强转 #175）：bool("no")/bool(0.0)
            # 类静默翻转一律 bad_request，元素必须是真 bool。
            bad_idx = [i for i, x in enumerate(judged_raw)
                       if not isinstance(x, bool)]
            if bad_idx:
                return {"ok": False, "status": "bad_request",
                        "errors": [f"g1.judged 含非布尔元素（严格 bool 校验，"
                                   f"禁 bool() 强转）: idx={bad_idx[0]} 值 "
                                   f"{judged_raw[bad_idx[0]]!r}，共 "
                                   f"{len(bad_idx)} 处"]}
            judged = np.asarray(judged_raw, dtype=bool)
        else:
            judged = None
        try:
            verdict = g1_systematic_bias_check(
                freqs_hz, dev, judged,
                sign_fraction_threshold=float(
                    g1_raw.get("sign_fraction_threshold", 0.8)),
                tie_db=float(g1_raw.get("tie_db", 0.05)),
            )
        except ValueError as exc:
            return {"ok": False, "status": "bad_request",
                    "errors": [f"g1: {exc}"]}
        g1_out = verdict.to_json_dict()

    return {"ok": True, "status": "ok", "engine": "mmt",
            "comparison": comparison, "g1": g1_out}
