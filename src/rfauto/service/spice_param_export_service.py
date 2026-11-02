"""SPICE 导出随参数插值服务（aurora_p D4；JSON 进出，规则 4）。

设计闭环（参数→曲线→SPICE 网表交付）：对任意参数点 θ——
参数化宏模型（``vf_parametric``：D2 多端口 ``predict_matrix`` / v1 单端口
``predict_curve``）预测 S(θ,ω) 栅格 → ``core.macromodel.fit_macromodel``
向量拟合（定阶阶梯或显式定阶）+ 带内无源判定/无源化 + skrf 状态空间直接综合
SPICE 子电路 + 结构校验 + 内核回放自检 → 网表头注（θ/频带/声明，纯 ``*``
注释）→ **对交付文件本体**再回放（栅上 + 栅间中点）→ 四门 → 原子交付。

模型来源=**现场拟合**（samples+config；设计半页 runs/aurora_p/d4/DESIGN.md）：
仓内常驻持久化面（optimization/model_registry：pickle blob 落
``runs/.model_store``）属湖写面且代理类无 save/load 契约；param_vf 拟合为
闭式 LS（零随机），同输入现场拟合即确定性等价工件（surrogate_export_service
"现场重拟合"同口径）。

门（全部读 core.macromodel 既有容差常量，零新口径）：
    G1 内核综合判定 ``fit_macromodel(...)["ok"]``（终态拟合 RMS≤阈值 ∧ 带内
       无源 ∧ 网表结构有效 ∧ FSV≥Good ∧ 内核回放 vs 模型 max|ΔS| ≤
       ``DEFAULT_REPLAY_CONSISTENCY_TOL``）；
    G2 交付文件回放 vs 内核回放 max|ΔS| ≤ ``DEFAULT_REPLAY_CONSISTENCY_TOL``
       （头注入不得改语义——交付的就是验过的）；
    G3/G4 交付文件回放 vs 预测 S 的 RMS（内核口径：nf·n² 归一，dB）≤
       ``DEFAULT_RMS_THRESHOLD_DB``（栅上 / 栅间中点）。阈值只许收紧不许放宽。
逐频误差向量（每频点条目最大 |ΔS|）随信封如实透出（``per_freq_max_abs``）。

诚实的边界（沿用 core.macromodel 模块 docstring 红线）：
    **回放是"回放自检"，不是第三方 SPICE 等价验证**——回放由本仓纯 Python
    复数 MNA（AC）求解器按标准 SPICE 元素语义求解导出网表，证明"交付网表在
    标准 SPICE 语义下重现预测 S"；**不能**替代 ngspice/LTspice/Xyce 交叉验证
    （第三方对拍另走 adapters.spice_netlist 的 ngspice .AC 通道，与本服务
    解耦）。调用方不得把 ``verdict=="PASS"`` 读作"第三方 SPICE 仿真通过"——
    信封 ``verification``（``third_party_spice_equivalence=False`` + 内核单源
    声明串）与网表头注两处在场。网表只在模型训练频带内有效（VF 无源性亦只在
    带内判定）；θ 落样本凸包外时透出 ``param_extrapolation=extrapolation_warn``
    （param_vf 同款 warn 语义，不阻断）。

拓扑一致性：VF 极点重定位可翻转实/复类型（#286），缺省阶梯下同族两 θ 的网表
拓扑可能不同——``topology.signature``（去数值元件名+节点 sha256）如实报告；
结构上锁拓扑请显式定阶（如单实极点族 ``order={"n_poles_real":1,
"n_poles_cmplx":0}``：1×1 重定位特征值必为实）。

交付语义：同目录 staging + ``os.replace`` 原子替换（同卷，不落系统临时盘）；
``ok`` ⇔ 四门全过且已交付。FAIL=零写面（staging 删除、本次新建的父目录回滚；
目标路径既存文件不动）；失败信封带全部诊断字段（#122 如实，不静默）。

确定性：拟合/预测/VF/综合全链零随机；网表头注无时间戳、浮点用 repr、参数按
名排序、行尾统一 LF——同输入两跑网表逐字节一致、信封逐键一致。

数值纪律（铁律 7）：本模块零数值产出——预测（param_vf）、拟合/综合/回放
（core.macromodel）全在确定性内核；本模块只编排、比对与组装信封。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
import warnings
from pathlib import Path
from typing import Any

import numpy as np

from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = ["spice_param_export"]

#: 信封 schema 标识（形状变更时升位）。
SPICE_PARAM_EXPORT_SCHEMA = "rfauto-spice-param-export-v1"
#: 缺省 .SUBCKT 名。
DEFAULT_SUBCKT_NAME = "param_s_equivalent"
#: 唯一支持的参数化模型键（D2 多端口 / v1 单端口同键）。
SUPPORTED_MODEL_KIND = "vf_parametric"
#: .SUBCKT 名合法形态（SPICE 标识符）。
_SUBCKT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
#: 网表头注中可裸写的参数名形态（其余经 ascii() 转义，杜绝注入非注释行）。
_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
#: 导出栅格与模型训练带的端点相对容差（只吸收浮点端点误差）。
_BAND_REL_TOL = 1e-9
#: dB 下限保护（与 core.macromodel 回放误差口径同值）。
_DB_FLOOR = 1e-30


# ─── 输入收敛 ─────────────────────────────────────────────────────────────────


def _pairs_to_complex(raw: Any, expect_ndim: int) -> np.ndarray | None:
    """JSON [re, im] 对数组 → 复数数组；非该形态返回 None（原样交给 param_vf）。

    判据无歧义：复数栈维数 expect_ndim（单端口曲线 1 / 多端口矩阵 3），实数
    且多一维、末维 2 才视为 [re, im] 对。其余形态（复数数组/畸形）不在此处
    裁决——param_vf 按基类契约跳过并计数。
    """
    try:
        arr = np.asarray(raw)
    except (TypeError, ValueError):
        return None
    if arr.dtype == object or np.iscomplexobj(arr):
        return None
    if not np.issubdtype(arr.dtype, np.number):
        return None
    if arr.ndim != expect_ndim + 1 or arr.shape[-1] != 2:
        return None
    arr = arr.astype(float)
    return arr[..., 0] + 1j * arr[..., 1]


def _decode_samples(samples: list[dict[str, Any]], key: str,
                    expect_ndim: int) -> list[dict[str, Any]]:
    """样本响应键的 [re, im] 对 → 复数（浅拷贝，不改调用方对象）。"""
    out: list[dict[str, Any]] = []
    for sample in samples:
        metrics = sample.get("metrics")
        if isinstance(metrics, dict) and key in metrics:
            arr = _pairs_to_complex(metrics[key], expect_ndim)
            if arr is not None:
                sample = {**sample, "metrics": {**metrics, key: arr}}
        out.append(sample)
    return out


def _load_samples(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """samples（内联）与 samples_path（JSON 文件）二选一 → 样本列表。"""
    samples = payload.get("samples")
    samples_path = payload.get("samples_path")
    if samples is not None and samples_path:
        raise ValueError("samples 与 samples_path 只能二选一")
    if samples is None:
        if not samples_path:
            raise ValueError("samples 与 samples_path 二选一必填")
        p = Path(str(samples_path))
        if not p.is_file():
            raise ValueError(f"样本 JSON 不存在: {p}")
        try:
            samples = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"样本 JSON 不可读: {exc}") from exc
    if not isinstance(samples, list):
        raise ValueError("samples 须为列表（[{params, metrics}, ...]）")
    for idx, sample in enumerate(samples):
        if not isinstance(sample, dict):
            raise ValueError(f"samples[{idx}] 须为 dict（{{params, metrics}}）")
    return samples


def _threshold_db(payload: dict[str, Any], default_db: float) -> float:
    """拟合/回放对拍阈值：缺省=内核单源；只许收紧（更负），放宽=输入错误。"""
    raw = payload.get("rms_threshold_db")
    if raw is None:
        return float(default_db)
    thr = float(raw)
    if not np.isfinite(thr):
        raise ValueError(f"rms_threshold_db 须为有限数，得到 {raw!r}")
    if thr > float(default_db):
        raise ValueError(
            f"rms_threshold_db={thr} 宽于内核单源 DEFAULT_RMS_THRESHOLD_DB="
            f"{default_db}：容差只许收紧不许放宽")
    return thr


def _order_request(payload: dict[str, Any]) -> dict[str, Any]:
    """定阶透传：显式 order 与 order_ladder 互斥（语义同 fit_macromodel）。"""
    order = payload.get("order")
    ladder = payload.get("order_ladder")
    if order is not None and ladder is not None:
        raise ValueError("order（显式定阶）与 order_ladder（阶梯）只能二选一")
    if order is not None:
        if not isinstance(order, dict):
            raise ValueError("order 须为 {n_poles_real, n_poles_cmplx}")
        try:
            n_real = int(order["n_poles_real"])
            n_cmplx = int(order["n_poles_cmplx"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "order 须同时给出整数 n_poles_real 与 n_poles_cmplx") from exc
        if n_real < 0 or n_cmplx < 0 or n_real + n_cmplx < 1:
            raise ValueError(
                f"order 阶数非法：n_poles_real={n_real}, n_poles_cmplx="
                f"{n_cmplx}（均 ≥0 且至少 1 个极点）")
        return {"n_poles_real": n_real, "n_poles_cmplx": n_cmplx}
    if ladder is not None:
        try:
            pairs = [[int(a), int(b)] for a, b in ladder]
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "order_ladder 须为 [[n_poles_real, n_poles_cmplx], ...]") from exc
        if not pairs:
            raise ValueError("order_ladder 不能为空")
        return {"order_ladder": pairs}
    return {}


def _z0_list(raw: Any, n_ports: int) -> list[float]:
    """参考阻抗 → 逐端口列表（标量广播；有限正实数）。"""
    arr = np.asarray(50.0 if raw is None else raw, dtype=float).ravel()
    if arr.size == 1:
        arr = np.full(n_ports, float(arr[0]))
    if arr.size != n_ports:
        raise ValueError(f"z0_ohm 长度 {arr.size} != 端口数 {n_ports}")
    if not np.all(np.isfinite(arr)) or np.any(arr <= 0.0):
        raise ValueError("z0_ohm 须全为有限正实数")
    return [float(x) for x in arr]


def _freq_grid(payload: dict[str, Any], model: Any,
               min_points: int) -> tuple[np.ndarray, np.ndarray | None, str]:
    """导出频栅：缺省=模型训练栅格；显式 freq_ghz 须严格递增、≥min_points、
    落在模型训练带内（带外=频率外推，不交付）。

    返回 (freq_hz, freq_ghz_for_predict（None=训练栅格逐位）, source)。
    """
    raw = payload.get("freq_ghz")
    if raw is None:
        freq_hz = np.linspace(model.f_lo_hz, model.f_hi_hz, model.n_freq)
        return freq_hz, None, "model_training_grid"
    f_ghz = np.asarray(raw, dtype=float).ravel()
    if f_ghz.size < min_points:
        raise ValueError(
            f"freq_ghz 点数 {f_ghz.size} < MIN_FREQ_POINTS={min_points}"
            "（VF/FSV 下限，内核单源）")
    if not np.all(np.isfinite(f_ghz)) or np.any(np.diff(f_ghz) <= 0.0):
        raise ValueError("freq_ghz 须为有限且严格递增")
    freq_hz = f_ghz * 1e9  # 与 param_vf 内部换算同式（逐位一致）
    lo = model.f_lo_hz * (1.0 - _BAND_REL_TOL)
    hi = model.f_hi_hz * (1.0 + _BAND_REL_TOL)
    if freq_hz[0] < lo or freq_hz[-1] > hi:
        raise ValueError(
            f"freq_ghz [{f_ghz[0]}, {f_ghz[-1]}] 越出模型训练带 "
            f"[{model.f_lo_hz / 1e9}, {model.f_hi_hz / 1e9}] GHz："
            "频率外推预测不作交付")
    return freq_hz, f_ghz, "explicit"


# ─── 预测 / 比对 / 网表文本 ─────────────────────────────────────────────────


def _predict_stack(model: Any, params: dict[str, float],
                   f_ghz: np.ndarray | None) -> np.ndarray:
    """参数化模型预测 → 复数 S 栈 (n_freq, P, P)（单端口曲线升维）。"""
    if int(model.n_ports) == 1:
        curve = model.predict_curve(params, f_ghz)
        return np.asarray(curve, dtype=complex).reshape(-1, 1, 1)
    return np.asarray(model.predict_matrix(params, f_ghz), dtype=complex)


def _error_metrics(freq_hz: np.ndarray, s_ref: np.ndarray,
                   s_test: np.ndarray) -> dict[str, Any]:
    """误差摘要——RMS 与 core.macromodel 回放误差同口径（nf·n² 归一：
    rms_abs=sqrt(Σ|ΔS|²/size)，rms_db=20·log10(max(rms,1e-30))，max_abs），
    另给逐频误差向量 per_freq_max_abs[k]=max_ij|ΔS_ij(f_k)| 与最差频点。"""
    delta = np.abs(np.asarray(s_ref, dtype=complex)
                   - np.asarray(s_test, dtype=complex))
    rms = float(np.sqrt(float(np.sum(delta ** 2)) / delta.size))
    per_freq = delta.reshape(delta.shape[0], -1).max(axis=1)
    worst = int(np.argmax(per_freq))
    return {
        "rms_abs": rms,
        "rms_db": float(20.0 * np.log10(max(rms, _DB_FLOOR))),
        "max_abs": float(delta.max()),
        "per_freq_max_abs": [float(x) for x in per_freq],
        "worst_freq_hz": float(freq_hz[worst]),
        "n_points": int(delta.shape[0]),
    }


def _pairs_array(nested: Any) -> np.ndarray:
    """内核 JSON 原生 [re, im] 嵌套 → 复数数组。"""
    arr = np.asarray(nested, dtype=float)
    return arr[..., 0] + 1j * arr[..., 1]


def _num(value: Any) -> float | None:
    """数值字段 JSON 化：缺失如实透出 None（#117：不以 or 缺省顶替）。"""
    return None if value is None else float(value)


def _header_token(name: str) -> str:
    """头注参数名：安全字符裸写，其余 ascii() 转义（换行等不得穿出注释行）。"""
    return name if _HEADER_NAME_RE.match(name) else ascii(name)


def _netlist_header(params: dict[str, float], freq_hz: np.ndarray,
                    z0_list: list[float], n_ports: int,
                    pole_counts: dict[str, int]) -> str:
    """网表头注（纯 ``*`` 注释、ASCII、确定性：无时间戳/repr 浮点/参数名排序）。"""
    theta = " ".join(f"{_header_token(k)}={float(params[k])!r}"
                     for k in sorted(params))
    lines = [
        "* rfauto spice_param_export: parametric S-model -> vector fit -> "
        "SPICE subcircuit",
        f"* params: {theta}",
        f"* band_hz: {float(freq_hz[0])!r} .. {float(freq_hz[-1])!r} "
        f"({int(freq_hz.size)} points), ports={int(n_ports)}, "
        f"z0_ohm={z0_list!r}",
        f"* vector fit poles stored: {pole_counts['n_poles_stored']} "
        f"(real {pole_counts['n_real_poles']} + complex-pair "
        f"{pole_counts['n_complex_pairs']})",
        "* verification: replay self-check by rfauto pure-python complex MNA "
        "(AC);",
        "*   NOT a third-party SPICE (ngspice/LTspice/Xyce) equivalence check",
        "*",
    ]
    return "\n".join(lines) + "\n"


def _inject_header(path: Path, header: str) -> None:
    """头注前置 + 行尾统一 LF（跨平台逐字节确定；只增注释行不改元件行）。"""
    text = path.read_text(encoding="utf-8")
    path.write_text(header + text, encoding="utf-8", newline="\n")


def _topology_signature(text: str) -> str:
    """拓扑签名：去数值（元件行去末令牌值；指令行全留；注释跳过）的 sha256 前 16。

    skrf 导出无续行；同签名 ⇔ 同元件名集+同节点连接（只差元件值）。
    """
    rows: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        toks = line.split()
        rows.append(" ".join(toks if line.startswith(".") else toks[:-1]))
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()[:16]


def _pole_counts(poles_rad_s: list[list[float]]) -> dict[str, int]:
    """极点类型计数（skrf 共轭对只存一个：存储复极点数=复共轭对数）。"""
    n_real = sum(1 for _re, im in poles_rad_s if float(im) == 0.0)
    n_stored = len(poles_rad_s)
    n_pairs = n_stored - n_real
    return {"n_poles_stored": n_stored, "n_real_poles": n_real,
            "n_complex_pairs": n_pairs,
            "effective_order": n_real + 2 * n_pairs}


def _missing_parents(path: Path) -> list[Path]:
    """目标父链中当前不存在的目录（深→浅），供 FAIL 零写面回滚。"""
    missing: list[Path] = []
    p = path.parent
    while not p.exists():
        missing.append(p)
        if p.parent == p:
            break
        p = p.parent
    return missing


def _rollback_dirs(missing: list[Path]) -> None:
    """回滚本次新建且仍为空的目录（深→浅；非空/占用即停，不误删）。"""
    for d in missing:
        try:
            d.rmdir()
        except OSError:
            break


def _warning_lines(caught: list[warnings.WarningMessage]) -> list[str]:
    """拟合期告警 → 去重首行摘要（保首现序，确定性）。"""
    seen: list[str] = []
    for w in caught:
        first = str(w.message).strip().splitlines()
        line = f"{w.category.__name__}: {first[0] if first else ''}"
        if line not in seen:
            seen.append(line)
    return seen


def _fail(stage: str, errors: Any, **fields: Any) -> dict[str, Any]:
    """失败信封（零交付语义恒带 verdict/delivered/netlist_path）。"""
    return error_envelope(
        errors, stage=stage, schema=SPICE_PARAM_EXPORT_SCHEMA,
        verdict="FAIL", delivered=False, netlist_path=None, **fields)


def _gate_reasons(fit: dict[str, Any], gates: dict[str, bool],
                  g2_max: float, vs_pred: dict[str, Any],
                  vs_mid: dict[str, Any], thr: float,
                  tol: float) -> list[str]:
    """门失败原因（如实分项，#122）。"""
    reasons: list[str] = []
    fit_sec = fit.get("fit") or {}
    pas = fit.get("passivity") or {}
    before = pas.get("before") or {}
    after = pas.get("after") or {}
    if not gates["G1_kernel_ok"]:
        if not before.get("passive_in_band", True):
            reasons.append(
                "G1 无源性：VF 模型带内非无源（无源化前 σmax="
                f"{before.get('sigma_max_in_band')!r}；"
                f"enforced={pas.get('enforced')!r}，enforce_error="
                f"{pas.get('enforce_error')!r}；无源化后 passive_in_band="
                f"{after.get('passive_in_band')!r} σmax="
                f"{after.get('sigma_max_in_band')!r}）")
        elif not after.get("passive_in_band", True):
            reasons.append(
                "G1 无源性：带内非无源 σmax="
                f"{after.get('sigma_max_in_band')!r}")
        if not fit_sec.get("passed_final", True):
            reasons.append(
                f"G1 拟合：终态 RMS {fit_sec.get('rms_db_final')!r} dB > "
                f"阈值 {thr!r} dB")
        spice = fit.get("spice") or {}
        if not spice.get("valid", False):
            reasons.append(f"G1 网表结构校验失败：{spice.get('errors')!r}")
        fsv = fit.get("fsv") or {}
        if not fsv.get("gdm_at_least_good", False):
            reasons.append(
                f"G1 FSV 保真等级 {fsv.get('worst_gdm_grade')!r} 劣于 Good")
        rep = fit.get("spice_replay") or {}
        if rep.get("status") != "ok":
            reasons.append(f"G1 内核回放自检失败：{rep.get('error')!r}")
        elif not rep.get("consistent", False):
            reasons.append(
                "G1 内核回放 vs 模型 max|ΔS|="
                f"{(rep.get('replay_vs_model') or {}).get('max_abs')!r} > {tol!r}")
        if len(reasons) == 0:
            reasons.append("G1 内核综合判定 ok=False")
    if not gates["G2_delivered_replay_consistent"]:
        reasons.append(
            f"G2 交付文件回放 vs 内核回放 max|ΔS|={g2_max!r} > {tol!r}"
            "（交付文件与已验文件语义不一致）")
    if not gates["G3_replay_vs_prediction"]:
        reasons.append(
            f"G3 交付网表回放 vs 预测 S（栅上）RMS {vs_pred['rms_db']!r} dB > "
            f"阈值 {thr!r} dB")
    if not gates["G4_replay_vs_prediction_offgrid"]:
        reasons.append(
            f"G4 交付网表回放 vs 预测 S（栅间中点）RMS {vs_mid['rms_db']!r} dB"
            f" > 阈值 {thr!r} dB")
    return reasons


# ─── 服务入口 ─────────────────────────────────────────────────────────────────


def spice_param_export(payload: dict[str, Any]) -> dict[str, Any]:
    """θ → S(θ,ω) 预测 → VF → SPICE 子电路 → 回放自检 → 网表交付（服务层单源）。

    **回放是"回放自检"（本仓纯 Python 复数 MNA），不是第三方 SPICE 等价验证**
    ——``verdict=="PASS"`` 不得读作 ngspice/LTspice/Xyce 仿真通过（信封
    ``verification`` 字段 + 网表头注同声明）。

    payload 键：
        config（必填）: ``vf_parametric`` 代理 config（bounds/freq_grid_ghz/
            n_freq/n_ports/n_real_poles/n_cmplx_pairs/...，语义同
            ParamVFSurrogate；n_ports 缺省 1=单端口 s11_curve 路径）；
        samples / samples_path（二选一必填）: 样本列表或其 JSON 文件
            （``[{"params": {...}, "metrics": {"s_matrix"|"s11_curve": ...}}]``；
            响应可为复数数组或 JSON ``[re, im]`` 对）；
        params（必填）: 参数点 θ（键集须与 bounds 一致）；
        out_path（必填）: 网表交付路径（只在 PASS 时原子写入）；
        freq_ghz（可选）: 导出栅格（GHz，严格递增、≥16 点、落训练带内；
            缺省=模型训练栅格）；
        z0_ohm（可选）: 参考阻抗（标量或逐端口列表，缺省 50）；
        subckt_name（可选）: .SUBCKT 名（SPICE 标识符，缺省
            ``param_s_equivalent``）；
        order（可选）: 显式定阶 ``{"n_poles_real", "n_poles_cmplx"}``
            （未达阈值=内核显式报错；可结构上锁拓扑）；
        order_ladder（可选）: 定阶阶梯 ``[[n_real, n_cmplx], ...]``（与 order
            互斥；缺省=内核 DEFAULT_ORDER_LADDER）；
        rms_threshold_db（可选）: 拟合/对拍 RMS 阈值，缺省=内核
            DEFAULT_RMS_THRESHOLD_DB，只许收紧。

    Returns:
        ok=True（verdict=PASS 且已交付）：``netlist_path``/``netlist_sha256``/
        ``params``/``n_ports``/``z0_ohm``/``freq_grid``/``param_model``（拟合
        摘要+外推判据+预测无源性）/``vector_fit``（阶数/极点计数/RMS/无源性）/
        ``replay``（内核回放一致性 + 交付文件回放 vs 预测 栅上/栅间 RMS 与
        逐频误差向量）/``gates``（G1-G4）/``topology``（签名+元件计数）/
        ``verification``（回放自检声明，单源）/``fit_warnings``。
        ok=False：``errors``（分项原因）+``stage``（input/param_fit/
        predict/vector_fit/replay/gates/deliver）+ 已得诊断字段；
        ``delivered=False``、``netlist_path=None``（零写面）。
    """
    from rfauto.core.macromodel import (
        DEFAULT_REPLAY_CONSISTENCY_TOL,
        DEFAULT_RMS_THRESHOLD_DB,
        MIN_FREQ_POINTS,
        fit_macromodel,
        replay_spice_subcircuit_s,
    )
    from rfauto.optimization.surrogate.green_operator import RESPONSE_KEY
    from rfauto.optimization.surrogate.param_vf import ParamVFSurrogate
    from rfauto.optimization.surrogate.pole_residue import (
        CURVE_KEY,
        passivity_verdict,
    )

    # ── 1. 输入收敛（stage=input） ──
    if not isinstance(payload, dict):
        return _fail("input", f"payload 须为 dict，得到 {type(payload).__name__}")
    cfg = payload.get("config")
    params = payload.get("params")
    out_raw = payload.get("out_path")
    if not isinstance(cfg, dict) or not cfg:
        return _fail("input", "config 必填且须为非空 dict（vf_parametric 契约）")
    if not isinstance(params, dict) or not params:
        return _fail("input", "params 必填且须为非空 dict（参数点 θ）")
    if not out_raw:
        return _fail("input", "out_path 必填")
    out = Path(str(out_raw))
    if out.is_dir():
        return _fail("input", f"out_path 是既存目录: {out}")
    subckt_name = str(payload.get("subckt_name") or DEFAULT_SUBCKT_NAME)
    if not _SUBCKT_RE.match(subckt_name):
        return _fail("input",
                     f"subckt_name 非法 SPICE 标识符: {subckt_name!r}")
    try:
        samples = _load_samples(payload)
        thr = _threshold_db(payload, DEFAULT_RMS_THRESHOLD_DB)
        order_req = _order_request(payload)
    except (TypeError, ValueError) as exc:
        return _fail("input", str(exc))

    # ── 2. 参数化模型现场拟合（stage=param_fit） ──
    try:
        model = ParamVFSurrogate(dict(cfg))
        n_ports = int(model.n_ports)
        key, ndim = (CURVE_KEY, 1) if n_ports == 1 else (RESPONSE_KEY, 3)
        fit_info = model.fit(_decode_samples(samples, key, ndim))
    except Exception as exc:  # 契约异常如实归类（类型+消息，不吞）
        return _fail("param_fit", f"参数化模型拟合失败: "
                                  f"{type(exc).__name__}: {exc}")
    try:
        z0_list = _z0_list(payload.get("z0_ohm"), n_ports)
        freq_hz, f_ghz, grid_source = _freq_grid(payload, model,
                                                 MIN_FREQ_POINTS)
    except (TypeError, ValueError) as exc:
        return _fail("input", str(exc))
    params_f = {str(k): params[k] for k in params}

    # ── 3. 预测 S(θ,ω)：栅上 + 栅间中点（stage=predict） ──
    mid_hz = 0.5 * (freq_hz[1:] + freq_hz[:-1])
    try:
        s_pred = _predict_stack(model, params_f, f_ghz)
        s_pred_mid = _predict_stack(model, params_f, mid_hz / 1e9)
        extrap = model.param_extrapolation_verdict(params_f)
    except Exception as exc:
        return _fail("predict", f"参数化模型预测失败: "
                                f"{type(exc).__name__}: {exc}")
    if not (np.all(np.isfinite(s_pred)) and np.all(np.isfinite(s_pred_mid))):
        return _fail("predict", "预测 S 含 NaN/Inf")
    pred_pas = passivity_verdict(s_pred)
    params_out = {k: float(params_f[k]) for k in sorted(params_f)}
    param_model = {
        "kind": SUPPORTED_MODEL_KIND,
        "fit_mode": "live_fit_from_samples",
        "n_curves": int(fit_info.get("n_curves", 0)),
        "n_skipped": int(fit_info.get("n_skipped", 0)),
        "n_param_dims": int(fit_info.get("n_param_dims", 0)),
        "pole_basis_size": int(model.n_real_poles + 2 * model.n_cmplx_pairs),
        "k_eff": int(fit_info.get("k_eff", 0)),
        "max_fit_rms": _num(fit_info.get("max_fit_rms")),
        "training_passive": bool((fit_info.get("passivity") or {})
                                 .get("passive", False)),
        "param_extrapolation": {
            "param_extrapolation": str(extrap["param_extrapolation"]),
            "hull_kind": str(extrap["hull_kind"]),
            "margin": float(extrap["margin"]),
        },
        "prediction_passivity": {
            "passive": bool(pred_pas["passive"]),
            "sigma_max_in_band": float(pred_pas["sigma_max_in_band"]),
            "tol": float(pred_pas["tol"]),
        },
    }
    freq_grid = {"f_lo_hz": float(freq_hz[0]), "f_hi_hz": float(freq_hz[-1]),
                 "n_points": int(freq_hz.size), "source": grid_source,
                 "model_band_hz": [float(model.f_lo_hz),
                                   float(model.f_hi_hz)]}
    diag: dict[str, Any] = {
        "subckt_name": subckt_name, "params": params_out, "n_ports": n_ports,
        "z0_ohm": z0_list, "freq_grid": freq_grid, "param_model": param_model,
    }

    # ── 4-8. VF+综合（staging）→ 头注 → 交付文件回放 → 门 → 原子交付 ──
    missing = _missing_parents(out)
    staging: Path | None = None
    delivered = False
    try:
        try:  # 同目录唯一 staging（同卷原子替换；并发调用互不覆盖）
            out.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{out.name}.", suffix=".staging", dir=out.parent)
            os.close(fd)
        except OSError as exc:
            return _fail("deliver", f"交付目录不可写: {exc}", **diag)
        sp = staging = Path(tmp_name)
        request: dict[str, Any] = {
            "freq_hz": [float(x) for x in freq_hz],
            "s_real": s_pred.real.tolist(), "s_imag": s_pred.imag.tolist(),
            "z0": z0_list, "spice_path": str(sp),
            "subckt_name": subckt_name, "rms_threshold_db": thr,
            **order_req,
        }
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                fit = fit_macromodel(request)
        except Exception as exc:
            return _fail("vector_fit", f"VF/SPICE 综合失败: "
                                       f"{type(exc).__name__}: {exc}", **diag)
        fit_warnings = _warning_lines(caught)
        counts = _pole_counts(fit.get("poles_rad_s") or [])
        pas = fit.get("passivity") or {}
        before = pas.get("before") or {}
        after = pas.get("after") or {}
        vector_fit = {
            "order_used": dict((fit.get("order") or {}).get("used") or {}),
            "order_explicit": bool((fit.get("order") or {}).get("explicit")),
            "poles": counts,
            "rms_db": _num((fit.get("fit") or {}).get("rms_db")),
            "rms_db_final": _num((fit.get("fit") or {}).get("rms_db_final")),
            "threshold_db": thr,
            "passivity": {
                "passive_in_band_before": bool(before.get("passive_in_band")),
                "sigma_max_before": _num(before.get("sigma_max_in_band")),
                "enforced": bool(pas.get("enforced")),
                "enforce_error": pas.get("enforce_error"),
                "passive_in_band_after": bool(after.get("passive_in_band")),
                "sigma_max_after": _num(after.get("sigma_max_in_band")),
            },
            "spice_valid": bool((fit.get("spice") or {}).get("valid")),
            "fsv_worst_gdm_grade": (fit.get("fsv") or {}).get(
                "worst_gdm_grade"),
            "kernel_ok": bool(fit.get("ok")),
        }
        diag.update(vector_fit=vector_fit, fit_warnings=fit_warnings)
        kernel_rep = fit.get("spice_replay") or {}
        if kernel_rep.get("status") != "ok" or not sp.is_file():
            return _fail("replay", f"内核回放自检不可用: "
                                   f"{kernel_rep.get('error')!r}", **diag)

        _inject_header(sp, _netlist_header(params_out, freq_hz, z0_list,
                                           n_ports, counts))
        try:
            rp = replay_spice_subcircuit_s(sp, freq_hz, z0=z0_list,
                                           n_ports=n_ports)
            rp_mid = replay_spice_subcircuit_s(sp, mid_hz, z0=z0_list,
                                               n_ports=n_ports)
        except Exception as exc:
            return _fail("replay", f"交付文件回放失败: "
                                   f"{type(exc).__name__}: {exc}", **diag)
        tol = float(DEFAULT_REPLAY_CONSISTENCY_TOL)
        g2_max = float(np.max(np.abs(
            rp["s"] - _pairs_array(kernel_rep["s"]))))
        vs_pred = _error_metrics(freq_hz, s_pred, rp["s"])
        vs_mid = _error_metrics(mid_hz, s_pred_mid, rp_mid["s"])
        gates = {
            "G1_kernel_ok": bool(fit.get("ok")),
            "G2_delivered_replay_consistent": bool(g2_max <= tol),
            "G3_replay_vs_prediction": bool(vs_pred["rms_db"] <= thr),
            "G4_replay_vs_prediction_offgrid": bool(vs_mid["rms_db"] <= thr),
        }
        text = sp.read_text(encoding="utf-8")
        elem_counts: dict[str, int] = {}
        for k, v in (rp.get("element_counts") or {}).items():
            elem_counts[str(k)] = int(v)
        diag.update(
            replay={
                "verifier": "replay_selfcheck",
                "kernel_replay_vs_model_max_abs": _num(
                    (kernel_rep.get("replay_vs_model") or {}).get("max_abs")),
                "delivered_vs_kernel_replay_max_abs": g2_max,
                "consistency_tol_abs": tol,
                "vs_prediction": vs_pred,
                "vs_prediction_offgrid": vs_mid,
                "rms_threshold_db": thr,
            },
            gates=gates,
            topology={"signature": _topology_signature(text),
                      "n_elements": int(rp.get("n_elements", 0)),
                      "element_counts": dict(sorted(elem_counts.items()))},
            verification={
                "kind": "replay_selfcheck",
                "third_party_spice_equivalence": False,
                "solver": str(rp.get("solver")),
                "disclaimer": str(rp.get("disclaimer")),
            },
        )
        if not all(gates.values()):
            return _fail("gates", _gate_reasons(fit, gates, g2_max, vs_pred,
                                                vs_mid, thr, tol), **diag)

        # ── 交付（stage=deliver）：同卷原子替换 ──
        data = sp.read_bytes()
        try:
            os.replace(sp, out)
        except OSError as exc:
            return _fail("deliver", f"网表交付失败: {exc}", **diag)
        delivered = True
        return ok_envelope(
            schema=SPICE_PARAM_EXPORT_SCHEMA, verdict="PASS", delivered=True,
            netlist_path=str(out),
            netlist_sha256=hashlib.sha256(data).hexdigest(), **diag)
    finally:
        if staging is not None and staging.exists():
            with contextlib.suppress(OSError):
                staging.unlink()
        if not delivered:
            _rollback_dirs(missing)
