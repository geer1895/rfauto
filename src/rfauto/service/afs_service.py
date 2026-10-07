"""M-3+SV-5 AFS 自适应频扫 service 接线（JSON 进出，CLI/MCP 壳共享）。

内核（core/afs.afs_sample）SV-5 升级为伪误差自适应频扫（arXiv 2504.09942v1
六步：半自适应初始点 + Loewner 双阶核 + 伪误差选点 + 记忆 3 停机；legacy
中点加密保留为 algorithm="midpoint" 对比档）；本模块把它接到服务面：

- :func:`afs_sweep_plan`：**纯计划面**——给定频带/容差/点数上限，产出
  初始采样频点表、六步协议描述与 §10.20 补强⑩验收判据（不求解、零回调
  调用，生产侧可先拿计划再做求解预算）；
- :func:`afs_sweep`：**回调注入型**——``evaluate`` 由调用方注入
  （``f_hz -> {"s": complex | [re, im] | p×p 嵌套序列}``；每次调用计一次
  求解），本模块只做回调契约适配与异常到 JSON 信封的翻译，不绑死任何
  EM 引擎（HFSS/openEMS/合成函数皆可注入，离线合成测试可跑全链）；矩阵
  ``"s"`` 进入多响应联合单门模式（谱范数）；
- :func:`synthetic_multiresonance_response`：确定性合成多谐振响应
  （解析有理函数族），供 CLI ``--synthetic`` 端到端演示与离线测试，
  零真机零随机。

数值只在确定性内核（铁律 7）：一切物理数字（频点/响应/FSV 等级/缩减比）
来自 core/afs + core/fsv；本模块不产生物理数字，只做契约适配与判据消费。

信封契约（与 calculator_service/slotline_service 同族）：ok=False + error
字符串绝不抛出；AFS 未收敛是**合法结果**（status 如实标注，指标照给），
不是错误——验收门（acceptance）FAIL 也照实返回，由调用方决定处置。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np

from rfauto.service.envelope import ok_envelope

#: 数值内核/回调期可预期的异常族（进信封；AFSError 在函数内并入）。
_JSON_ERRORS = (TypeError, ValueError, ZeroDivisionError, OverflowError,
                ArithmeticError)

#: §10.20 补强⑩验收判据①：AFS solve 数相对全扫密集参考缩减 >= 50%。
REDUCTION_RATIO_MIN = 0.5

#: §10.20 补强⑩验收判据②：重建 vs 全扫 FSV >= VG（GDM 等级下标 <= 1）。
FSV_MIN_GRADE = "VG"


def _band_hz(band: Sequence[float]) -> tuple[float, float]:
    """频带入参收敛：(f_min, f_max) 两元素、有限、严格递增（#140 Path 同族）。

    bool 显式拒收（float(True)=1.0 静默污染，df7+⑯）。"""
    if band is None or isinstance(band, (str, bytes, Mapping)):
        raise ValueError(f"band 须为 [f_min, f_max] 两元素序列，得到 {band!r}")
    seq = list(band)
    if len(seq) != 2:
        raise ValueError(f"band 须为 [f_min, f_max] 两元素，得到 {len(seq)} 个")
    f_min, f_max = (float(v) for v in seq)
    if isinstance(band[0], bool) or isinstance(band[1], bool):
        raise ValueError("band 频点不接受 bool（数值入参显式拒收 bool）")
    if not (math.isfinite(f_min) and math.isfinite(f_max)) or not f_max > f_min:
        raise ValueError(f"频带非法（须有限且 f_min < f_max）: [{f_min!r}, {f_max!r}]")
    return f_min, f_max


def _tol_float(tol: float | None, default: float) -> float:
    """容差收敛：None 落回内核缺省；bool 拒收；非正拒绝。"""
    value = default if tol is None else float(tol)
    if isinstance(tol, bool):
        raise ValueError("tol 不接受 bool（数值入参显式拒收 bool）")
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"tol 须为正有限数，得到 {tol!r}")
    return value


def _tol_db_float(tol_db: float | None) -> float | None:
    """dB 容差收敛（SV-5 主口径）：None 放行（落内核缺省）；bool 拒收；
    非有限拒绝（dB 可为任意有限值，不设正负号约束）。"""
    if tol_db is None:
        return None
    if isinstance(tol_db, bool):
        raise ValueError("tol_db 不接受 bool（数值入参显式拒收 bool）")
    value = float(tol_db)
    if not math.isfinite(value):
        raise ValueError(f"tol_db 须为有限数，得到 {tol_db!r}")
    return value


def _electrical_size_pair(
    trace_length_m: float | None, n_ports: int | None
) -> tuple[float, int] | None:
    """半自适应电尺寸入参收敛（原文 Eq.13 需 l 与 p，成对给定）。"""
    if trace_length_m is None and n_ports is None:
        return None
    if trace_length_m is None or n_ports is None:
        raise ValueError(
            "trace_length_m 与 n_ports 须成对给定（Eq.13 需 l 与 p）")
    if isinstance(trace_length_m, bool) or isinstance(n_ports, bool):
        raise ValueError("trace_length_m/n_ports 不接受 bool")
    l_m = float(trace_length_m)
    p_n = int(n_ports)
    if not math.isfinite(l_m) or l_m <= 0.0:
        raise ValueError(f"trace_length_m 须为正有限数，得到 {trace_length_m!r}")
    if p_n < 1:
        raise ValueError(f"n_ports 须 >= 1，得到 {n_ports!r}")
    return l_m, p_n


def _algorithm_name(algorithm: str) -> str:
    """算法档收敛：loewner（SV-5 缺省）| midpoint（legacy 对比档）。"""
    value = str(algorithm)
    if value not in ("loewner", "midpoint"):
        raise ValueError(f"algorithm 须为 'loewner' | 'midpoint'，得到 {algorithm!r}")
    return value


def _cell_complex(value: Any, f_hz: float) -> complex:
    """矩阵元 -> complex（数或 [re, im] 二元序列；bool 显式拒收）。"""
    if isinstance(value, bool):
        raise ValueError(f"evaluate({f_hz!r}) 的 's' 矩阵元不接受 bool")
    if isinstance(value, (list, tuple)):
        if len(value) != 2:
            raise ValueError(
                f"evaluate({f_hz!r}) 的 's' 矩阵元序列形须为 [re, im] 两元素")
        return complex(float(value[0]), float(value[1]))
    return complex(value)


def _s_from_result(raw: Any, f_hz: float) -> complex | np.ndarray:
    """evaluate 回调返回值 -> complex（标量）或 p×p complex 矩阵。

    契约：evaluate(f_hz) -> dict，必须含 ``"s"`` 键。``"s"`` 形：
    complex / float / ``[re, im]`` 二元序列（标量响应，旧契约逐字节
    兼容）或 **p×p 嵌套序列**（SV-5 多响应联合单门；元=数或 [re, im]，
    如 2×2：``[[[re,im],[re,im]],[[re,im],[re,im]]]`` 或实数
    ``[[a,b],[c,d]]``）；额外键放行供回调方携带旁证，本模块不消费。
    宽容面：直接返回（非 dict 包裹的）上述形也收（简化合成回调）。
    """
    if isinstance(raw, dict):
        if "s" not in raw:
            raise ValueError(
                f"evaluate({f_hz!r}) 返回 dict 缺少 's' 键"
                "（契约: {'s': complex | [re, im] | p×p 嵌套序列}）")
        value = raw["s"]
    else:
        value = raw
    if isinstance(value, bool):
        raise ValueError(f"evaluate({f_hz!r}) 的 's' 不接受 bool")
    if isinstance(value, (list, tuple)):
        if len(value) == 2 and not any(
                isinstance(v, (list, tuple, np.ndarray)) for v in value):
            # 旧 [re, im] 对（标量响应；原契约兼容分支）
            return complex(float(value[0]), float(value[1]))
        # SV-5 矩阵形：p 行 × p 元（元=数或 [re, im]），谱范数联合单门
        p = len(value)
        if p == 0:
            raise ValueError(f"evaluate({f_hz!r}) 的 's' 矩阵形不允许为空")
        rows = []
        for r_i, row in enumerate(value):
            if not isinstance(row, (list, tuple)):
                raise ValueError(
                    f"evaluate({f_hz!r}) 的 's' 矩阵形第 {r_i} 行不是序列"
                    "（契约: p×p 嵌套序列，元=数或 [re, im]）")
            if len(row) != p:
                raise ValueError(
                    f"evaluate({f_hz!r}) 的 's' 矩阵形须为 p×p 方阵"
                    f"（第 {r_i} 行长度 {len(row)} ≠ {p}）")
            rows.append([_cell_complex(cell, f_hz) for cell in row])
        return np.array(rows, dtype=complex)
    return complex(value)


def afs_sweep_plan(
    band: Sequence[float],
    tol: float | None = None,
    max_points: int = 96,
    *,
    n_init: int = 7,
    max_rounds: int = 12,
    n_dense: int = 401,
    tol_db: float | None = None,
    trace_length_m: float | None = None,
    n_ports: int | None = None,
    algorithm: str = "loewner",
) -> dict[str, Any]:
    """AFS 扫频计划（纯计划面：不求解、不调 evaluate，确定性零副作用）。

    Args:
        band: ``[f_min_hz, f_max_hz]``（Hz，f_min < f_max）。
        tol: 旧线性收敛容差（谱范数比）；None 落回内核缺省
            （core.afs.DEFAULT_TOL，与 tol_db 缺省 -40 dB 等价）。
        tol_db: SV-5 主口径容差（dB，20log10 谱范数比；显式给定时优先）。
        max_points: 采样点上限（终止保护）。
        n_init: 初始点数下限（>= 3；trace_length_m/n_ports 给定时被
            Eq.13 公式取代）。
        max_rounds: 加密轮数上限（终止保护）。
        n_dense: 重建/判分/伪误差选点密集频轴点数。
        trace_length_m / n_ports: 半自适应初始点（原文 Eq.13）的走线总长
            （m）与端口数，须成对给定。
        algorithm: ``"loewner"``（SV-5 六步，缺省）| ``"midpoint"``
            （legacy 中点加密对比档）。

    Returns:
        JSON 原生 dict：ok=False + error（频带/参数非法）；ok=True 时
        ``plan`` 含初始频点表（algorithm=loewner 为 Eq.14 对数密置高频
        布点）、六步协议、Loewner 双阶参数（q1/q2/df/记忆）与验收判据
        （reduction_ratio_min=0.5 + FSV >= VG）与 evaluate 回调契约。
    """
    from rfauto.core.afs import (
        DEFAULT_ORDER_LADDER,
        DEFAULT_RMS_THRESHOLD_DB,
        DEFAULT_TOL,
        DELTA_F_HZ,
        LOEWNER_Q1,
        LOEWNER_Q2,
        MEMORY_LIMIT,
        _semi_adaptive_n0,
        afs_initial_grid,
    )

    try:
        f_min, f_max = _band_hz(band)
        tol_f = _tol_float(tol, DEFAULT_TOL)
        tol_db_v = _tol_db_float(tol_db)
        algo = _algorithm_name(algorithm)
        electrical = _electrical_size_pair(trace_length_m, n_ports)
        n_init_i, max_points_i = int(n_init), int(max_points)
        max_rounds_i, n_dense_i = int(max_rounds), int(n_dense)
        if n_init_i < 3:
            raise ValueError(f"n_init 必须 >= 3，得到 {n_init_i}")
        if max_points_i < n_init_i:
            raise ValueError(f"max_points({max_points_i}) 不能小于 n_init({n_init_i})")
        if max_rounds_i < 1:
            raise ValueError(f"max_rounds 必须 >= 1，得到 {max_rounds_i}")
        if n_dense_i < 2:
            raise ValueError(f"n_dense 必须 >= 2，得到 {n_dense_i}")
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}

    if electrical is not None:
        l_m, p_n = electrical
        n_points = _semi_adaptive_n0(l_m, p_n, f_max)
        initial = afs_initial_grid(f_min, f_max, n_points)
        init_mode = "semi_adaptive_electrical_size"
    elif algo == "loewner":
        n_points = n_init_i
        initial = afs_initial_grid(f_min, f_max, n_points)
        init_mode = "log_dense_high"
    else:
        n_points = n_init_i
        initial = np.linspace(f_min, f_max, n_points)
        init_mode = "uniform"

    eff_db = tol_db_v if tol_db_v is not None else 20.0 * math.log10(tol_f)
    plan: dict[str, Any] = {
        "band_hz": [f_min, f_max],
        "tol": tol_f if tol_db_v is None else float(10.0 ** (eff_db / 20.0)),
        "tol_db": float(eff_db),
        "algorithm": algo,
        "init_mode": init_mode,
        "n_init": n_points,
        "n_init_requested": n_init_i,
        "max_points": max_points_i,
        "max_rounds": max_rounds_i,
        "n_dense": n_dense_i,
        "initial_frequencies_hz": [float(f) for f in initial],
        "order_ladder": [[int(nr), int(nc)] for nr, nc in DEFAULT_ORDER_LADDER],
        "fit_rms_threshold_db": float(DEFAULT_RMS_THRESHOLD_DB),
        # protocol.name 为消费面稳定标识符（test_mcp_server 钉
        # "afs_midpoint_refinement"）；SV-5 算法身份以 algorithm 键为准。
        "protocol": {
            "name": "afs_midpoint_refinement",
            "algorithm": algo,
            "steps": [
                "① 初始点：n0=ceil(15*l*f_max/(p*c))（Eq.13，l/p 给定时）"
                " 按 f0=(2fmax+fmin)-10^linspace(log10(2fmax),"
                " log10(fmax+fmin), n0) 对数密置高频（Eq.14）",
                "② Loewner 切向插值态空间模型：even/odd 分块+共轭增广"
                "（Eq.15）-> 块 Loewner/移位 Loewner（Eq.9）-> SVD 截断"
                "（Eq.16/17）",
                f"③ 双模型 q1={LOEWNER_Q1}/q2={LOEWNER_Q2}（Eq.19 能量比"
                f" > 1-10^-q）+ 频轴摄动 df={DELTA_F_HZ} Hz（H2 在"
                " s'=j2pi(f+df) 求值）",
                "④ 伪误差 E_pseu=||H2(s')-H1(s)||_2/||H1(s)||_2（Eq.20，"
                "谱范数=多响应联合判据）",
                "⑤ f_new=argmax E_pseu（Eq.21，密集判分栅上剔除既有采样点）",
                f"⑥ 连续 {MEMORY_LIMIT} 新点 E_act<=tol_db 才停"
                "（Algorithm-1 memory，超标清零；E_act 按 Eq.22 谱范数比）",
                f"终止保护：max_rounds={max_rounds_i} / max_points={max_points_i}"
                "（触发时 status 如实标注未收敛）",
            ],
        },
        "acceptance_criteria": {
            "reduction_ratio_min": REDUCTION_RATIO_MIN,
            "fsv_min_grade": FSV_MIN_GRADE,
            "note": "§10.20 补强⑩：solve 数相对全扫密集参考缩减 >= 50% 且"
                    "重建 vs 全扫 FSV >= VG（GDM 等级下标 <= 1）；"
                    "full_response 缺省时只出指标不判门",
        },
        "evaluate_contract": {
            "signature": "evaluate(f_hz: float) -> dict",
            "returns": {"s": "complex | float | [re, im] | p×p 嵌套序列"
                        "（元=数或 [re, im]；矩阵=多响应联合单门）"},
            "billing": "每次 evaluate 调用计一次求解（生产中=一次 FEM 单点求解）",
        },
    }
    if electrical is not None:
        plan["n0_formula"] = {
            "trace_length_m": electrical[0],
            "n_ports": electrical[1],
            "c_light_m_s": 3.0e8,
            "n0": n_points,
        }
    return ok_envelope(plan=plan)


def afs_sweep(
    evaluate: Callable[[float], dict[str, Any]],
    band: Sequence[float],
    tol: float | None = None,
    max_iter: int = 12,
    *,
    n_init: int = 7,
    max_points: int = 96,
    n_dense: int = 401,
    full_response: Callable[[np.ndarray], np.ndarray] | None = None,
    tol_db: float | None = None,
    trace_length_m: float | None = None,
    n_ports: int | None = None,
    algorithm: str = "loewner",
) -> dict[str, Any]:
    """AFS 自适应频扫（回调注入型：evaluate 由调用方注入，不绑死 EM 引擎）。

    Args:
        evaluate: 真响应回调 ``f_hz -> dict``（必须含 ``"s"``：complex /
            float / ``[re, im]`` / p×p 嵌套序列）；每次调用计一次求解。
            生产中即一次 FEM 单点求解；离线测试/演示注入合成解析函数即可
            跑全链。矩阵 ``"s"`` 进入多响应联合单门模式（谱范数）。
        band: ``[f_min_hz, f_max_hz]``（Hz）。
        tol: 旧线性收敛容差（None 落回内核缺省；与 tol_db 都缺省 = -40 dB）。
        tol_db: SV-5 主口径容差（dB，20log10 谱范数比；显式给定时优先）。
        max_iter: 加密轮数上限（透传内核 max_rounds）。
        n_init / max_points / n_dense: 初始点数 / 采样点上限 / 密集参考
            与判分点数。
        full_response: 可选，全扫参考 ``freqs(Hz) -> (n,) 复数 | (n,p,p)``
            （已归档密集数据，*不计入* solve 计费）。提供时结果附
            ``vs_full``（FSV 裁判；矩阵形逐元 FSV 取最差元进门）与
            ``acceptance``（验收判据消费）；缺省时只出采样/重建指标，
            不判门。
        trace_length_m / n_ports: 半自适应初始点（原文 Eq.13/14）走线总长
            （m）与端口数，须成对给定；给定后点数走公式（n_init 被取代）。
        algorithm: ``"loewner"``（SV-5 六步，缺省）| ``"midpoint"``
            （legacy 中点加密，仅 SISO）。

    Returns:
        JSON 原生信封：ok=False + error（参数非法/回调异常/拟合全败，含
        ``n_solves_before_abort`` 计费留痕）；ok=True 时 ``result`` 为内核
        summary（n_solves 计费/采样点/收敛状态/e_act_db_series/密集重建/
        vs_full FSV）+ ``acceptance``（full_response 提供时：reduction>=0.5
        且 FSV>=VG）。未收敛是合法结果（status 如实，不进 error）。
    """
    from rfauto.core.afs import DEFAULT_TOL, AFSError, afs_sample

    try:
        f_min, f_max = _band_hz(band)
        tol_db_v = _tol_db_float(tol_db)
        if tol is not None or tol_db_v is None:
            tol_f: float | None = _tol_float(tol, DEFAULT_TOL)
        else:
            tol_f = None
        algo = _algorithm_name(algorithm)
        electrical = _electrical_size_pair(trace_length_m, n_ports)
    except _JSON_ERRORS as exc:
        return {"ok": False, "error": str(exc)}
    if not callable(evaluate):
        return {"ok": False,
                "error": "evaluate 必须为可调用对象 f_hz -> dict（含 's'）"}

    solves = {"n": 0}

    def _evaluate(f: float) -> Any:
        solves["n"] += 1
        try:
            raw = evaluate(float(f))
        except Exception as exc:  # 回调是外部注入代码，异常族不可枚举→如实进信封
            raise AFSError(
                f"evaluate({f!r}) 抛出 {type(exc).__name__}: {exc}") from exc
        try:
            return _s_from_result(raw, f)
        except _JSON_ERRORS as exc:
            raise AFSError(f"evaluate({f!r}) 返回值违背契约: {exc}") from exc

    try:
        summary = afs_sample(
            _evaluate, f_min, f_max,
            n_init=int(n_init), tol=tol_f, tol_db=tol_db_v,
            max_points=int(max_points),
            max_rounds=int(max_iter), n_dense=int(n_dense),
            full_response=full_response,
            algorithm=algo,
            trace_length_m=(electrical[0] if electrical is not None else None),
            n_ports=(electrical[1] if electrical is not None else None),
        )
    except (*_JSON_ERRORS, AFSError) as exc:
        return {"ok": False, "error": str(exc),
                "n_solves_before_abort": solves["n"]}

    vs = summary.get("vs_full")
    if isinstance(vs, dict):
        fsv = vs.get("fsv") or {}
        reduction_ok = bool(
            float(vs.get("reduction_ratio", 0.0)) >= REDUCTION_RATIO_MIN)
        fsv_ok = bool(fsv.get("at_least_vg"))
        summary["acceptance"] = {
            "reduction_ratio_min": REDUCTION_RATIO_MIN,
            "reduction_ok": reduction_ok,
            "fsv_min_grade": FSV_MIN_GRADE,
            "fsv_ok": fsv_ok,
            "passed": bool(reduction_ok and fsv_ok),
        }
    return ok_envelope(result=summary, n_solves=solves["n"])


def synthetic_multiresonance_response(
    spec: str,
    f_min_hz: float,
    f_max_hz: float,
) -> tuple[Callable[[np.ndarray], np.ndarray], dict[str, Any]]:
    """确定性合成多谐振响应（解析有理函数族；CLI --synthetic 演示与测试用）。

    规格（``;`` 分隔，逐段 ``f0_ghz:q_pole[:q_zero]`` 或 ``key=value``）::

        "2.4:40;3.1:60"             两个陷波谐振（f0_ghz:q_pole，q_zero 缺省 200）
        "2.4:40:150;3.1:60;ripple=0.02"  显式 q_zero + 带内余弦纹波（非有理成分）

    响应 = Π_i (s² + (ω_i/q_zero_i)·s + ω_i²) / (s² + (ω_i/q_pole_i)·s + ω_i²)
    （零对浅阻尼=陷波，极对定宽度；s= jω，e^{+jωt} 口径），乘纹波因子
    ``1 - amp·(0.5 + 0.5·cos(2π(f-f_min)/period))``（period 缺省 180 MHz，
    非有理成分，驱动多轮加密）。

    Returns:
        (response, spec_dict)：``response(freqs_hz) -> complex array`` 与
        规格回显（JSON 原生，进结果 provenance）。

    Raises:
        ValueError: 规格段解析失败/参数非法（零谐振、Q<=0、ripple 出界等）。
    """
    resonances: list[tuple[float, float, float]] = []
    ripple_amp = 0.0
    period_hz = 180.0e6
    text = str(spec).strip()
    if not text:
        raise ValueError("synthetic 规格为空（示例: '2.4:40;3.1:60'）")
    for seg in text.split(";"):
        seg = seg.strip()
        if not seg:
            continue
        if "=" in seg:
            key, _, raw = seg.partition("=")
            key = key.strip().lower()
            value = float(raw)
            if key == "ripple":
                if not 0.0 <= value < 1.0:
                    raise ValueError(f"ripple 幅度须在 [0, 1)，得到 {value}")
                ripple_amp = value
            elif key in ("period_mhz", "period"):
                if value <= 0.0:
                    raise ValueError(f"纹波周期须 >0，得到 {value}")
                period_hz = value * 1e6 if key == "period_mhz" else value
            else:
                raise ValueError(f"synthetic 规格未知键: {key!r}（支持 ripple/period_mhz）")
            continue
        parts = seg.split(":")
        if len(parts) not in (2, 3):
            raise ValueError(
                f"synthetic 谐振段须为 f0_ghz:q_pole[:q_zero]，得到 {seg!r}")
        f0_ghz = float(parts[0])
        q_pole = float(parts[1])
        q_zero = float(parts[2]) if len(parts) == 3 else 200.0
        if f0_ghz <= 0.0 or q_pole <= 0.0 or q_zero <= 0.0:
            raise ValueError(f"synthetic 谐振参数须 >0，得到 {seg!r}")
        resonances.append((f0_ghz * 1e9, q_pole, q_zero))
    if not resonances:
        raise ValueError("synthetic 规格无谐振段（示例: '2.4:40;3.1:60'）")
    f_min_hz = float(f_min_hz)
    f_max_hz = float(f_max_hz)
    if not (math.isfinite(f_min_hz) and math.isfinite(f_max_hz)) \
            or not f_max_hz > f_min_hz:
        raise ValueError(f"频带非法: [{f_min_hz!r}, {f_max_hz!r}]")

    def response(freqs_hz: np.ndarray) -> np.ndarray:
        f = np.asarray(freqs_hz, dtype=float)
        s = 1j * 2.0 * np.pi * f
        out = np.ones(f.shape, dtype=complex)
        for f0, q_pole, q_zero in resonances:
            w0 = 2.0 * np.pi * f0
            out = out * ((s**2 + (w0 / q_zero) * s + w0**2)
                         / (s**2 + (w0 / q_pole) * s + w0**2))
        if ripple_amp > 0.0:
            out = out * (1.0 - ripple_amp
                         * (0.5 + 0.5 * np.cos(
                             2.0 * np.pi * (f - f_min_hz) / period_hz)))
        return out

    spec_dict = {
        "resonances": [
            {"f0_ghz": f0 / 1e9, "q_pole": qp, "q_zero": qz}
            for f0, qp, qz in resonances
        ],
        "ripple_amp": ripple_amp,
        "period_hz": period_hz,
        "band_hz": [f_min_hz, f_max_hz],
    }
    return response, spec_dict
