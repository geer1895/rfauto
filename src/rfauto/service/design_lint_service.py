"""design_lint：统一设计体检门面（W4，`rfauto lint` 的 service 面）。

**lint=聚合器不是新判据**：每个子检查只调用既有 service/core 函数
（Z3 渲染约束 / fab DFM / bounds 信息界 / PDN 腔模门 / stub 谐振），
本模块不新增任何物理判据（铁律 7：数值只在确定性内核）。子检查注册表
模块内自持（仿 core/error_budget.BUDGET_REGISTRY 惯例），新增子检查
实现同签名函数并 ``@LINT_REGISTRY.register("名字")`` 即接入。

payload 契约（JSON 进出，全部键可选）::

    {
      "checks": ["constraints", "fab", "bounds", "pdn", "stub"]?,
          # 只跑子集；未知名 → ValueError（程序性错误，如实抛出）
      "template": "mline"?,      # 有 → fab 子检查（模板名义几何 DFM 门）
      "params": {...}?,          # 模板参数覆盖（fab 消费）
      "fab": {"profile"?, "material"?, "copper_oz"?,
              "surface_finish"?, "board_thickness_mm"?}?,
      "constraints": {...}?,     # evaluate_render_constraints config 透传；
                                 # 缺省回退收集顶层 mesh/gap 约束键
      "bounds": {"bbox_m": [米], "f_hz" | "f_ghz", "polarization"?}?,
                                 # 天线电尺寸信息界（Chu Q/方向性），**不设门**
      "pdn": {...}?,             # pdn_gate payload 透传（plane/interest_band...）
      "stub": {"stub_len_mm", "er_eff", "nyquist_ghz"?, "margin_frac"?}?,
    }

输出契约::

    {"ok": True,                      # lint 本身跑通（与检出无关）
     "checks": [{name, status, detail, source, result?}, ...],
     "summary": {"pass": n, "fail": n, "warn": n, "unknown": n, "info": n},
     "verdict": "clean" | "issues" | "attention"}

status 语义：
- ``pass``   子检查跑通且无检出；
- ``fail``   检出违规/非法输入（门面聚合 best-effort，但检出项必须拦）；
- ``warn``   无硬违规但可信度降级（如模板未登记几何事实表走保守扫描）；
- ``unknown`` 参数不足/基础设施缺装（z3 缺装降级）/底层三值 UNKNOWN——
  #105：absent/参数不足→unknown 不炸，**unknown 不算 fail**；
- ``info``   信息性界（bounds：极限界是设计参考非违规，verdict 不受影响）。

verdict 语义（CLI exit code 同源）：fail>0→``issues``（exit 1）；
warn/unknown>0→``attention``；否则 ``clean``（均 exit 0）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rfauto.service.envelope import ok_envelope

__all__ = ["LINT_REGISTRY", "LintCheckRegistry", "design_lint"]

_LINT_CHECK_NAMES = ("constraints", "fab", "bounds", "pdn", "stub")
"""子检查全集（注册表一致性由测试钉住）。"""


class LintCheckRegistry:
    """子检查注册表（仿 BUDGET_REGISTRY：注册+按名运行，门面不自持判据）。"""

    def __init__(self) -> None:
        self._checks: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}

    def register(
        self, name: str
    ) -> Callable[[Callable[[dict[str, Any]], dict[str, Any]]],
                   Callable[[dict[str, Any]], dict[str, Any]]]:
        """注册子检查函数（签名 payload→check row）。同名覆盖视为编程错误。"""
        if name in self._checks:
            raise ValueError(f"子检查重复注册: {name}")

        def deco(fn: Callable[[dict[str, Any]], dict[str, Any]]
                 ) -> Callable[[dict[str, Any]], dict[str, Any]]:
            self._checks[name] = fn
            return fn

        return deco

    def names(self) -> list[str]:
        return sorted(self._checks)

    def is_registered(self, name: str) -> bool:
        return name in self._checks

    def run(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        fn = self._checks.get(name)
        if fn is None:
            raise ValueError(f"未知子检查: {name}（可用: {self.names()}）")
        return fn(payload)


LINT_REGISTRY = LintCheckRegistry()


def _row(name: str, status: str, detail: str, source: str,
         result: dict[str, Any] | None = None) -> dict[str, Any]:
    """统一 check row（四规范键 + 可选 result 供消费方下钻）。"""
    row: dict[str, Any] = {"name": name, "status": status,
                           "detail": detail, "source": source}
    if result is not None:
        row["result"] = result
    return row


# ─── constraints（Z3 渲染前声明式约束，R4） ──────────────────────────────────

_CONSTRAINT_SERVICE = "rfauto.service.render_constraint_service.evaluate_render_constraints"

_CONSTRAINT_TOP_KEYS = (
    "mesh_resolution_mm", "near_ratio", "gaps_mm", "min_gap_mm",
    "gap_cells_min", "min_line_spacing_mm", "mesh_lines_mm",
    "param_bounds", "max_conflict_groups",
)
"""顶层可直接携带约束参数的键（constraints 配置缺省时的回退收集面）。"""


@LINT_REGISTRY.register("constraints")
def _check_constraints(payload: dict[str, Any]) -> dict[str, Any]:
    cfg = payload.get("constraints")
    if not isinstance(cfg, dict):
        cfg = {k: payload[k] for k in _CONSTRAINT_TOP_KEYS if k in payload}
    if not cfg:
        return _row("constraints", "unknown",
                    "未提供约束参数（constraints 配置与顶层 mesh/gap 键均缺）",
                    _CONSTRAINT_SERVICE)
    from rfauto.service.render_constraint_service import evaluate_render_constraints

    try:
        result = evaluate_render_constraints(cfg)
    except (KeyError, TypeError, ValueError) as exc:
        return _row("constraints", "fail", f"约束配置非法: {exc}",
                    _CONSTRAINT_SERVICE)
    status = result.get("status")
    if status == "sat":
        return _row("constraints", "pass",
                    f"z3 一次求解可行（{result.get('reason') or 'SAT'}）",
                    _CONSTRAINT_SERVICE, result=result)
    if status == "unsat":
        ids = result.get("conflict_rule_ids") or []
        n_groups = len(result.get("conflict_groups") or [])
        return _row("constraints", "fail",
                    f"约束冲突（UNSAT）：冲突规则 {ids}；冲突组 {n_groups} 组",
                    _CONSTRAINT_SERVICE, result=result)
    # unavailable（z3 缺装）/error/unknown → 基础设施或求解未定，如实 unknown
    return _row("constraints", "unknown",
                f"求解未定或不可用（status={status}，"
                f"reason={result.get('reason')}）",
                _CONSTRAINT_SERVICE, result=result)


# ─── fab（模板名义几何 DFM 门，HS 系） ───────────────────────────────────────

_FAB_SERVICE = "rfauto.service.fab_service.check_template_dfm"


@LINT_REGISTRY.register("fab")
def _check_fab(payload: dict[str, Any]) -> dict[str, Any]:
    template = payload.get("template")
    if not template:
        return _row("fab", "unknown",
                    "未提供 template（DFM 门按模板名义几何运行）", _FAB_SERVICE)
    from rfauto.service.fab_service import check_template_dfm

    opts = payload.get("fab") or {}
    if not isinstance(opts, dict):
        return _row("fab", "fail", "fab 选项必须是对象", _FAB_SERVICE)
    try:
        result = check_template_dfm(
            str(template), payload.get("params"),
            profile=str(opts.get("profile", "jlcpcb")),
            material=str(opts.get("material", "rogers4350b_h0.508")),
            copper_oz=float(opts.get("copper_oz", 1.0)),
            surface_finish=opts.get("surface_finish"),
            board_thickness_mm=opts.get("board_thickness_mm"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return _row("fab", "fail", f"DFM 输入非法: {exc}", _FAB_SERVICE)
    if result.get("ran") is not True:
        # 未知模板/剖面缺失：check_template_dfm 以 {"ok": False, "errors": [...]}
        # 返回且不带 ran=True——属检出问题（拦），不是基础设施缺装。
        errs = "；".join(str(e) for e in result.get("errors") or ["DFM 检查失败"])
        return _row("fab", "fail", errs, _FAB_SERVICE, result=result)
    violations = result.get("violations") or []
    codes = [str(v.get("code")) for v in violations]
    scan_note = bool((result.get("facts") or {}).get("scan_note"))
    if violations:
        return _row("fab", "fail",
                    f"{len(violations)} 项 DFM 违规: {codes}",
                    _FAB_SERVICE, result=result)
    if scan_note:
        return _row("fab", "warn",
                    "无违规，但模板未登记 FAB_GEOMETRY_FACTS，走保守后缀扫描"
                    "（几何事实可信度降级）",
                    _FAB_SERVICE, result=result)
    return _row("fab", "pass", "无 DFM 违规", _FAB_SERVICE, result=result)


# ─── bounds（天线电尺寸信息界：Chu Q / 方向性；信息级不设门） ─────────────────

_BOUNDS_SERVICE = "rfauto.core.bounds.bbox_to_ka+chu_q_bound+directivity_bounds"


@LINT_REGISTRY.register("bounds")
def _check_bounds(payload: dict[str, Any]) -> dict[str, Any]:
    b = payload.get("bounds")
    if not isinstance(b, dict):
        b = {k: payload[k] for k in ("bbox_m", "f_hz", "f_ghz",
                                     "polarization") if k in payload}
    bbox = b.get("bbox_m")
    f_hz = b.get("f_hz")
    f_ghz = b.get("f_ghz")
    if not bbox or (f_hz is None and f_ghz is None):
        return _row("bounds", "unknown",
                    "参数不足：需 bounds.bbox_m（米，≥2 维）+ f_hz 或 f_ghz",
                    _BOUNDS_SERVICE)
    from rfauto.core.bounds import bbox_to_ka, chu_q_bound, directivity_bounds

    try:
        freq = float(f_hz) if f_hz is not None else float(f_ghz) * 1e9
        ka = bbox_to_ka(bbox, freq)
        pol = b.get("polarization", "linear")
        chu = chu_q_bound(ka, pol).to_dict()
        dirs = {k: v.to_dict() for k, v in directivity_bounds(ka=ka).items()}
    except (KeyError, TypeError, ValueError) as exc:
        # 垃圾入参 fail-fast（core 口径）：门面如实记 fail 拦下
        return _row("bounds", "fail", f"天线几何参数非法: {exc}",
                    _BOUNDS_SERVICE)
    detail = (f"ka={ka:.4g}: Chu Q_min={chu.get('limit_value')}; "
              f"球包络 D≤{dirs.get('sphere_directivity', {}).get('limit_value')}"
              f"（信息性界，不设门）")
    return _row("bounds", "info", detail, _BOUNDS_SERVICE,
                result={"ka": ka, "chu": chu, "directivity": dirs})


# ─── pdn（KiCad AC-PI 门：腔模/避让/Z 裕量，F-B P2） ─────────────────────────

_PDN_SERVICE = "rfauto.service.pdn_service.pdn_gate"


@LINT_REGISTRY.register("pdn")
def _check_pdn(payload: dict[str, Any]) -> dict[str, Any]:
    p = payload.get("pdn")
    if p is None:
        return _row("pdn", "unknown",
                    "未提供 pdn 参数（plane/interest_band/target）",
                    _PDN_SERVICE)
    if not isinstance(p, dict):
        return _row("pdn", "fail",
                    "pdn 必须是对象（键见 service.pdn_service.pdn_gate）",
                    _PDN_SERVICE)
    from rfauto.service.pdn_service import pdn_gate

    try:
        result = pdn_gate(p)
    except (KeyError, TypeError, ValueError) as exc:
        return _row("pdn", "fail", f"pdn payload 非法: {exc}", _PDN_SERVICE)
    if result.get("ok") is False and result.get("errors"):
        errs = "；".join(str(e) for e in result["errors"])
        return _row("pdn", "fail", errs, _PDN_SERVICE, result=result)
    verdict = result.get("verdict")
    if verdict == "PASS":
        return _row("pdn", "pass", "平面腔模/安装避让/Z 裕量门 PASS",
                    _PDN_SERVICE, result=result)
    if verdict == "FAIL":
        codes = [str(v.get("code")) for v in result.get("violations") or []]
        return _row("pdn", "fail",
                    f"PDN 门 FAIL: {codes}", _PDN_SERVICE, result=result)
    reason = result.get("unknown_reason") or "底层三值 UNKNOWN"
    return _row("pdn", "unknown", reason, _PDN_SERVICE, result=result)


# ─── stub（残桩谐振 vs 奈奎斯特带，HS-2） ────────────────────────────────────

_STUB_SERVICE = "rfauto.core.fab_check.check_stub_resonance"


@LINT_REGISTRY.register("stub")
def _check_stub(payload: dict[str, Any]) -> dict[str, Any]:
    s = payload.get("stub")
    if not isinstance(s, dict) or not s:
        return _row("stub", "unknown",
                    "未提供 stub 参数（stub_len_mm、er_eff 必给；"
                    "nyquist_ghz 可选）",
                    _STUB_SERVICE)
    from rfauto.core.fab_check import check_stub_resonance

    if s.get("stub_len_mm") is None or s.get("er_eff") is None:
        return _row("stub", "unknown",
                    "stub 参数不足：stub_len_mm 与 er_eff 必给"
                    "（nyquist_ghz 缺省只出信息行）",
                    _STUB_SERVICE)
    try:
        violations = check_stub_resonance(
            s["stub_len_mm"], s["er_eff"],
            nyquist_ghz=s.get("nyquist_ghz"),
            margin_frac=s.get("margin_frac", 1.0),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return _row("stub", "fail", f"stub 参数非法: {exc}", _STUB_SERVICE)
    hard = [v for v in violations
            if not str(v.get("code", "")).endswith("_INFO")]
    infos = [v for v in violations
             if str(v.get("code", "")).endswith("_INFO")]
    if hard:
        return _row("stub", "fail",
                    f"残桩谐振带内风险: "
                    f"{[str(v.get('code')) for v in hard]}",
                    _STUB_SERVICE, result={"violations": violations})
    if infos:
        return _row("stub", "info",
                    str(infos[0].get("detail") or "残桩谐振信息行"),
                    _STUB_SERVICE, result={"violations": violations})
    return _row("stub", "pass", "残桩谐振在奈奎斯特带外", _STUB_SERVICE,
                result={"violations": violations})


# ─── 聚合入口 ────────────────────────────────────────────────────────────────


def design_lint(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """统一设计体检：payload → {checks, summary, verdict}（JSON 进出薄面）。

    缺省全跑注册表内子检查；``checks`` 给子集时只跑子集（未知名抛
    ValueError——程序性错误，由调用方/CLI 如实上报）。任何子检查内部
    的 absent/参数不足都归一为 unknown 行，不中断其余子检查（#105
    best-effort 聚合；检出 fail 照常拦）。
    """
    payload = dict(payload or {})
    requested = payload.get("checks")
    if requested is None:
        names = LINT_REGISTRY.names()
    else:
        if not isinstance(requested, list) or \
                not all(isinstance(n, str) for n in requested):
            raise ValueError("checks 必须是字符串列表")
        unknown_names = [n for n in requested if not LINT_REGISTRY.is_registered(n)]
        if unknown_names:
            raise ValueError(
                f"未知子检查: {unknown_names}（可用: {LINT_REGISTRY.names()}）")
        names = list(requested)
    rows = [LINT_REGISTRY.run(name, payload) for name in names]
    summary: dict[str, int] = {"pass": 0, "fail": 0, "warn": 0,
                               "unknown": 0, "info": 0}
    for row in rows:
        st = str(row["status"])
        summary[st] = summary.get(st, 0) + 1
    if summary["fail"] > 0:
        verdict = "issues"
    elif summary["warn"] > 0 or summary["unknown"] > 0:
        verdict = "attention"
    else:
        verdict = "clean"
    return ok_envelope(checks=rows, summary=summary, verdict=verdict)
