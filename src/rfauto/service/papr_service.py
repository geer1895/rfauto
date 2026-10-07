"""F-E.5 PAPR service 面（JSON 进出，规则 4；CLI/MCP 是薄壳）。

消费 core/papr.py 内核（全部数字出自确定性内核，规则 7；本服务零物理
公式）。四入口（方案 研究扩充 round3 F-E 表
件 5；参照 service/aging_service.py 信封口径）：

- :func:`papr_ccdf_eval`：γ_dB（标量或列表）+ N + α → 解析 CCDF；
- :func:`papr_threshold_eval`：目标概率 p（标量或列表）+ N + α → 门限
  γ_p（dB，含 PRNT 语义）；
- :func:`papr_monte_carlo_eval`：合成 OFDM MC 对照（固定 seed；符号数
  上限封顶防误用）；
- :func:`papr_cfr_eval`：样点波形（[re, im] 对列表，长度封顶）+ 目标
  PAPR → 软削峰达标判定 + EVM 代价（削后波形不进 JSON，只回标量面）。

任何入参/内核异常 → ``{"ok": False, "errors": [...]}``，不向调用方抛
（ok=False 不产数字；判缺失一律 is not None，#364④）。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from rfauto.core import papr
from rfauto.service.envelope import error_envelope, ok_envelope

#: service schema 版本（recipe_version 与 schema_version 语义区分，#106）
PAPR_SERVICE_SCHEMA_VERSION = "1.0"

#: MC 符号数上限（单测/服务防误用封顶；更大规模走脚本批处理）
_MAX_MC_SYMBOLS = 200_000

#: CFR 波形样点上限（JSON 载荷防膨胀）
_MAX_CFR_SAMPLES = 1 << 16


def _err(errors: list[str]) -> dict[str, Any]:
    return error_envelope(list(errors))


def _payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"payload 必须是 JSON 对象，实际 {type(payload).__name__}")
    return payload


def _num(value: Any, name: str) -> float:
    """服务层入参收敛：只收 int/float（拒 bool/str/None），有限性由内核兜底。

    非 _helpers 族（F-13 批 2 处置注记）：raise 式契约+不做有限性检查
    （有限性由内核兜底），并入 parse_num 会加严行为——本地保留。
    """
    if value is None:
        raise ValueError(f"{name} 缺失")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须是数字，实际 {value!r}")
    return float(value)


def _int(value: Any, name: str) -> int:
    if value is None:
        raise ValueError(f"{name} 缺失")
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} 必须是整数，实际 {value!r}")
    return int(value)


def _opt_alpha(payload: dict[str, Any]) -> float:
    """可选 alpha：键缺失/None → 1.0（临界采样缺省；数值 0.0 合法但会被内核边界拒绝）。"""
    raw = payload.get("alpha")
    return 1.0 if raw is None else _num(raw, "alpha")


def papr_ccdf_eval(payload: Any) -> dict[str, Any]:
    """解析 CCDF：payload = {gamma_db: 数|列表, n_subcarriers: int, alpha?: 数}。"""
    try:
        p = _payload(payload)
        n = _int(p.get("n_subcarriers"), "n_subcarriers")
        alpha = _opt_alpha(p)
        raw_gamma = p.get("gamma_db")
        if raw_gamma is None:
            raise ValueError("gamma_db 缺失")
        if isinstance(raw_gamma, list):
            ccdf = [papr.ccdf_analytic(_num(g, "gamma_db"), n, alpha) for g in raw_gamma]
            return ok_envelope(schema_version=PAPR_SERVICE_SCHEMA_VERSION, ccdf=ccdf, n_subcarriers=n, alpha=alpha)
        gamma_db = _num(raw_gamma, "gamma_db")
        return ok_envelope(
                   schema_version=PAPR_SERVICE_SCHEMA_VERSION,
                   ccdf=papr.ccdf_analytic(gamma_db, n, alpha),
                   n_subcarriers=n,
                   alpha=alpha,
               )
    except (ValueError, TypeError) as exc:
        return _err([str(exc)])


def papr_threshold_eval(payload: Any) -> dict[str, Any]:
    """门限求逆：payload = {prob: 数|列表, n_subcarriers: int, alpha?: 数}。

    概率列表含 1e-4 时即 PRNT（0.01%）口径；数值/闭式双路在内核与测试
    侧互证，服务面只出闭式主口径。
    """
    try:
        p = _payload(payload)
        n = _int(p.get("n_subcarriers"), "n_subcarriers")
        alpha = _opt_alpha(p)
        raw_prob = p.get("prob")
        if raw_prob is None:
            raise ValueError("prob 缺失")
        if isinstance(raw_prob, list):
            gamma_db = [papr.papr_threshold_db(_num(q, "prob"), n, alpha) for q in raw_prob]
            return ok_envelope(
                       schema_version=PAPR_SERVICE_SCHEMA_VERSION,
                       papr_db=gamma_db,
                       n_subcarriers=n,
                       alpha=alpha,
                   )
        prob = _num(raw_prob, "prob")
        return ok_envelope(
                   schema_version=PAPR_SERVICE_SCHEMA_VERSION,
                   papr_db=papr.papr_threshold_db(prob, n, alpha),
                   n_subcarriers=n,
                   alpha=alpha,
               )
    except (ValueError, TypeError) as exc:
        return _err([str(exc)])


def papr_monte_carlo_eval(payload: Any) -> dict[str, Any]:
    """MC 对照：payload = {n_subcarriers: int, n_symbols?: int, oversampling?: int,
    modulation?: "qpsk"|"16qam", seed?: int, p_grid?: [数,...]}。"""
    try:
        p = _payload(payload)
        n = _int(p.get("n_subcarriers"), "n_subcarriers")
        n_sym = 2000 if p.get("n_symbols") is None else _int(p.get("n_symbols"), "n_symbols")
        if n_sym > _MAX_MC_SYMBOLS:
            raise ValueError(f"n_symbols 超过服务上限 {_MAX_MC_SYMBOLS}，实际 {n_sym}")
        osf = 1 if p.get("oversampling") is None else _int(p.get("oversampling"), "oversampling")
        mod = "qpsk" if p.get("modulation") is None else p["modulation"]
        if not isinstance(mod, str):
            raise ValueError(f"modulation 必须是字符串，实际 {mod!r}")
        seed = papr.PAPR_MC_DEFAULT_SEED if p.get("seed") is None else _int(p.get("seed"), "seed")
        raw_grid = p.get("p_grid")
        if raw_grid is None:
            grid = papr.PAPR_PROB_GRID
        else:
            if not isinstance(raw_grid, list):
                raise ValueError("p_grid 必须是数组")
            grid = tuple(_num(q, "p_grid") for q in raw_grid)
        result = papr.ccdf_monte_carlo(n, n_sym, osf, mod, seed, p_grid=grid)
        return ok_envelope(schema_version=PAPR_SERVICE_SCHEMA_VERSION, result=result.to_dict())
    except (ValueError, TypeError) as exc:
        return _err([str(exc)])


def _waveform_of(payload: dict[str, Any]) -> np.ndarray:
    """samples（[re, im] 对列表）→ 一维复样点数组（长度封顶、逐点数值校验）。"""
    raw = payload.get("samples")
    if raw is None:
        raise ValueError("samples 缺失")
    if not isinstance(raw, list) or not raw:
        raise ValueError("samples 必须是非空数组")
    if len(raw) > _MAX_CFR_SAMPLES:
        raise ValueError(f"samples 长度超过服务上限 {_MAX_CFR_SAMPLES}，实际 {len(raw)}")
    flat: list[float] = []
    for i, item in enumerate(raw):
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError(f"samples[{i}] 必须是 [re, im] 二元组，实际 {item!r}")
        flat.append(_num(item[0], f"samples[{i}].re"))
        flat.append(_num(item[1], f"samples[{i}].im"))
    arr = np.asarray(flat, dtype=float).reshape(-1, 2)
    return arr[:, 0] + 1j * arr[:, 1]


def papr_cfr_eval(payload: Any) -> dict[str, Any]:
    """CFR 软削峰：payload = {samples: [[re, im], ...], papr_target_db: 数}。

    返回标量面（削后波形不进 JSON；需要波形走 core 直调）。
    """
    try:
        p = _payload(payload)
        samples = _waveform_of(p)
        target_db = _num(p.get("papr_target_db"), "papr_target_db")
        result = papr.cfr_soft_clip(samples, target_db)
        return ok_envelope(schema_version=PAPR_SERVICE_SCHEMA_VERSION, result=result.to_dict())
    except (ValueError, TypeError) as exc:
        return _err([str(exc)])
