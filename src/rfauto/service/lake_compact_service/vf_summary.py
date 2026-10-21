"""lake_compact_service.vf_summary —— ③ sparams VF 有界摘要（生成/读回/盘点）。

自 service/lake_compact_service.py 单文件巨石按职责域拆分（架构批 W3-S1，
T2 范式/AU-1 工艺）：代码体自原节「③ sparams VF 有界摘要」逐字节搬迁
（复用 core/macromodel 拟合，误差界是摘要组成部分——不带误差界的摘要
不落盘），零逻辑改动。
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

from .common import (
    _git_head_short,
    _meta_file,
    _read_json_object,
    _repo_root_guess,
)

# ---------------------------------------------------------------------------
# ③ sparams VF 有界摘要
# ---------------------------------------------------------------------------

#: 摘要 schema 版本（演进锚）
VF_SUMMARY_SCHEMA = "rfauto-sparams-vf-summary-v1"

#: 摘要文件名（run 目录内，与 sparams.csv 并排）
VF_SUMMARY_NAME = "sparams.vf.json"

#: lossless_equivalent 门槛（spec §5.3 判据 2：L∞_linear ≤5e-3 ≈ ≤0.05dB）
LINF_LOSSLESS_THRESHOLD = 5e-3


def _fit_request_from_sparams_csv(
    csv_path: Path,
) -> tuple[dict[str, Any], Any, Any, int] | None:
    """sparams.csv → fit_macromodel request 片段 + (freq, s, mask)。

    复用 health_service._parse_sparams_csv_masked（#314 掩码单源，零新解
    析器）；未测元素零填充进拟合输入（fit_macromodel 要求全矩阵），误差
    裁判只对掩码内元素计——部分矩阵语义见模块 docstring。坏 csv（loadtxt
    ValueError/OSError）同样 None（调用方零写面拒绝）。
    """
    from rfauto.service.health_service import _parse_sparams_csv_masked

    try:
        parsed = _parse_sparams_csv_masked(csv_path)
    except (OSError, ValueError):
        return None
    if parsed is None:
        return None
    freq, s, mask = parsed
    n = int(s.shape[1])
    request = {
        "freq_hz": [float(x) for x in freq],
        "s": [[[[float(v.real), float(v.imag)] for v in row] for row in mat]
              for mat in s],
        "z0": [50.0] * n,
        "n_ports": n,
        "source_path": str(csv_path),
        "spice_replay": False,
    }
    return request, freq, mask, n


def _rational_response(
    poles: list[list[float]],
    residues: list[list[list[float]]],
    d_coeff: list[list[list[float]]],
    freq_hz: Any,
    n_ports: int,
) -> Any:
    """存档系数 → 有理分式模型 S 矩阵重建（[nf, n, n] 复数）。

    口径=skrf VectorFitting.get_model_response（安装版实测逐行对照）：
    ``S_ij(s) = d_ij + Σ_k residues[i*n+j][k]/(s − poles[k])``，且**复数
    极点隐式带共轭项**（skrf 存 n_poles_cmplx 个单支复极点，响应求值时
    自动补 conj(residues)/（s−conj(poles))——非共轭对显式存储）；无比例项
    （fit_macromodel 全链 proportional=False）。与内核 model_response 的
    等价性由单测钉（W3-A test_w3_a_*.py，#118 独立回收口径）。
    """
    import numpy as np

    f = np.asarray(freq_hz, dtype=float).ravel()
    s = 2j * np.pi * f
    out = np.zeros((f.size, n_ports, n_ports), dtype=complex)
    poles_c = [complex(re_, im_) for re_, im_ in poles]
    for i in range(n_ports):
        for j in range(n_ports):
            resp = np.full(f.size, complex(d_coeff[i][j][0],
                                           d_coeff[i][j][1]), dtype=complex)
            beta = residues[i * n_ports + j]
            for k, pole in enumerate(poles_c):
                term = complex(beta[k][0], beta[k][1]) / (s - pole)
                if pole.imag == 0.0:
                    resp = resp + term
                else:
                    resp = resp + term + np.conjugate(
                        complex(beta[k][0], beta[k][1])) / (s - pole.conjugate())
            out[:, i, j] = resp
    return out


def s_model_from_summary(summary: dict[str, Any], freq_hz: Any) -> Any:
    """摘要 JSON → 模型 S 矩阵重建（冷层消费面：零 csv 解压零重拟合）。"""
    return _rational_response(
        summary.get("poles") or [],
        summary.get("residues") or [],
        summary.get("d_coeff") or [],
        freq_hz,
        int(summary.get("n_ports") or 0))


def sparams_summary(
    run_dir: str | Path,
    *,
    write: bool = True,
    fit_commit: str | None = None,
    order_ladder: list[tuple[int, int]] | None = None,
    rms_threshold_db: float = -60.0,
) -> dict[str, Any]:
    """run 目录 sparams.csv → VF 有界摘要 ``sparams.vf.json``（spec ③）。

    误差界为摘要组成部分（铁律 7 变体）：L∞/rms 只对已测元素（#314 掩码）
    计；linf ≤ LINF_LOSSLESS_THRESHOLD → fidelity_class=lossless_equivalent，
    否则 bounded_lossy 带 linf 值如实（深谷族不硬压，#370 教训的压缩版）。
    拟合失败/源不可解析 → error 信封且**零写面**（不带误差界的摘要不落盘）。
    ``rms_threshold_db`` 缺省 -60（比内核 SPICE 导出缺省 -40 深一档：本门
    是 L∞≤5e-3 口径，实测 -40dB rms 档 L∞ 峰可到 ~2e-2，阶梯需推进到更
    深档才进 lossless 界——合成回收实证，见 W3-A 单测 fixture）。

    Returns:
        dict: {"ok", "summary_path"?, "fidelity_class"?, "linf_error_linear"?,
        "rms_error"?, "n_poles"?, **errors?}——summary 正文即落盘 JSON。
    """
    import numpy as np

    from rfauto.core.macromodel import fit_macromodel

    rd = Path(run_dir)
    base: dict[str, Any] = {"run_dir": str(rd)}
    csv_path = rd / "sparams.csv"
    if not csv_path.is_file():
        return error_envelope([f"sparams.csv 不存在: {csv_path}"], **base)
    built = _fit_request_from_sparams_csv(csv_path)
    if built is None:
        return error_envelope([f"sparams.csv 不可解析: {csv_path}"], **base)
    request, freq, mask, n_ports = built
    if order_ladder:
        request["order_ladder"] = [(int(a), int(b))
                                   for a, b in order_ladder]
    request["rms_threshold_db"] = float(rms_threshold_db)
    # 部分矩阵（单激励零填充）不做无源化强制：零填充元素使全矩阵天然非
    # 无源，enforce 只会为迁就零元素扭曲已测元素的拟合（且 enforcement
    # 失败时残差反被恶化）；摘要=检索加速面，passivity_state 如实记录。
    if not bool(mask.all()):
        request["enforce_passivity"] = False
    try:
        fit = fit_macromodel(request)
    except Exception as exc:
        return error_envelope([f"VF 拟合失败（零写面）: "
                               f"{type(exc).__name__}: {exc}"], **base)

    s_raw = np.asarray(request["s"], dtype=float)
    s_orig = s_raw[..., 0] + 1j * s_raw[..., 1]  # [re,im] 嵌套 → 复数矩阵
    poles = fit.get("poles_rad_s") or []
    residues = fit.get("residues") or []
    d_coeff_flat = fit.get("constant_coeff") or []
    try:
        d_coeff = [[list(d_coeff_flat[i * n_ports + j])
                    for j in range(n_ports)] for i in range(n_ports)]
        s_model = _rational_response(poles, residues, d_coeff, freq, n_ports)
    except Exception as exc:
        return error_envelope([f"摘要重建失败（零写面）: {exc}"], **base)
    diff = np.abs(s_model - s_orig)
    linf_linear = float(diff[:, mask].max()) if mask.any() else float(np.max(diff))
    rms_linear = float(np.sqrt(np.mean(diff[:, mask] ** 2))) if mask.any() \
        else float(np.sqrt(np.mean(diff ** 2)))
    linf_db = float(20.0 * np.log10(max(linf_linear, 1e-12)))
    fidelity_class = ("lossless_equivalent"
                      if linf_linear <= LINF_LOSSLESS_THRESHOLD
                      else "bounded_lossy")
    passivity = fit.get("passivity") or {}
    after = passivity.get("after") or {}
    csv_sha = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    commit = fit_commit if fit_commit is not None \
        else _git_head_short(_repo_root_guess())
    summary = {
        "schema_version": VF_SUMMARY_SCHEMA,
        "run_dir": str(rd),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_ports": int(n_ports),
        "n_points": int(np.asarray(freq).size),
        "n_poles": len(poles),
        "poles": poles,
        "residues": residues,
        "d_coeff": d_coeff,
        "freq_band": [float(np.asarray(freq).min()),
                      float(np.asarray(freq).max())],
        "linf_error_linear": linf_linear,
        "linf_error_db": linf_db,
        "rms_error": rms_linear,
        "linf_threshold_linear": LINF_LOSSLESS_THRESHOLD,
        "fidelity_class": fidelity_class,
        "partial_matrix": bool(not mask.all()),
        "n_measured_entries": int(mask.sum()),
        "n_total_entries": int(mask.size),
        "passivity_state": {
            "passive_in_band": after.get("passive_in_band"),
            "sigma_max_in_band": after.get("sigma_max_in_band"),
            "enforced": passivity.get("enforced"),
            "enforce_error": passivity.get("enforce_error"),
        },
        "provenance": {
            "fit_commit": commit,
            "source_csv_sha256": csv_sha,
            "source_path": str(csv_path),
            "kernel": "core.macromodel.fit_macromodel（request_from_"
                      "touchstone 同族链；本摘要走 sparams.csv 掩码面）",
        },
    }
    out_path = rd / VF_SUMMARY_NAME
    if write:
        # 落盘前断言误差界在档（不带误差界的摘要不落盘——结构性守卫；
        # NaN 不满足 >= 0 即拒）
        if not (linf_linear >= 0.0):
            return error_envelope(["误差界异常（NaN?），拒绝落盘"], **base)
        out_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8")
    return ok_envelope(
        summary_path=str(out_path),
        fidelity_class=fidelity_class,
        linf_error_linear=linf_linear,
        linf_error_db=linf_db,
        rms_error=rms_linear,
        n_poles=len(poles),
        summary=summary if not write else None,
        **base)


def read_sparams_summary(run_dir: str | Path) -> dict[str, Any]:
    """读 run 目录摘要（零解压读面；缺/坏如实 ok=False）。"""
    path = Path(run_dir) / VF_SUMMARY_NAME
    data = _read_json_object(path)
    if data is None:
        return error_envelope([f"摘要不存在或不可解析: {path}"],
                              run_dir=str(run_dir))
    return ok_envelope(summary=data, summary_path=str(path),
                       run_dir=str(run_dir))


def plan_sparams_summaries(
    runs_root: str | Path = "runs",
    *,
    max_rows: int = 200,
) -> dict[str, Any]:
    """摘要生成机会盘点（**纯读**——真湖生成等用户窗，W3-A criteria）。

    资格口径：sparams.csv 在档 + meta 在档 + 尚无 sparams.vf.json。
    """
    root = Path(runs_root).resolve()
    base: dict[str, Any] = {"runs_root": str(root)}
    if not root.is_dir():
        return error_envelope([f"runs 根不存在: {root}"], **base)
    eligible: list[dict[str, Any]] = []
    n_csv = 0
    n_existing = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        if "sparams.csv" in filenames:
            n_csv += 1
            if VF_SUMMARY_NAME in filenames:
                n_existing += 1
                continue
            if _meta_file(here) is None:
                continue
            eligible.append({"path": here.relative_to(root).as_posix()})
    listed = eligible[:max_rows]
    return ok_envelope(
        n_sparams_csv=n_csv, n_summary_existing=n_existing,
        n_eligible=len(eligible), eligible=listed,
        eligible_truncated=max(0, len(eligible) - len(listed)),
        note="真湖摘要生成属写面（run 目录内新增文件），等用户窗放量；"
             "本盘点纯读零写", **base)
