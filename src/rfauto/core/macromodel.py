"""S 参数宏模型内核（向量拟合 + 无源性 + SPICE 导出 + FSV 保真裁判）。

目标是把频域 S 参数
（Touchstone / 仿真归档）转成"电路可用宏模型"：有理极点-留数模型 + 无源性
处理 + SPICE 子电路 + 保真判定。

分层与依赖
----------
本模块属 core 层叶子：只依赖 numpy + scikit-rf（skrf 是既有核心依赖，见
core/synthesis.py）+ 同层 core/errors、core/fsv。不做 IO 编排、不起服务、
不 import 任何上层。

外部算法（不自造）
------------------
有理拟合全链使用 skrf 2.1.0 自带 ``skrf.vectorFitting.VectorFitting``
（Gustavsen 向量拟合实现）：
- ``vector_fit(n_poles_real, n_poles_cmplx, ...)``：固定阶数拟合，**确定性**
  （无随机初值；本模块只用它，不用随机初始化）；
- ``get_model_response(i, j, f)``：取模型响应，用于本模块自算 RMS 与 FSV；
- ``passivity_test()``：Gustavsen-Semlyen 半尺寸测试矩阵，返回违规频段；
- ``passivity_enforce()``：奇异值扰动无源化；
- ``write_spice_subcircuit_s()``：状态空间直接综合的 N 端口等效子电路。
所有函数签名以本仓 venv 实测的 skrf 2.1.0 ``inspect.signature`` 为准。

裁判设计（不自证）
------------------
1. 合成已知网络：测试用闭式 Y/Z 矩阵构造有理网络（series RLC / 串联电感 /
   电感星形四端口），原始 S 由闭式公式给出，与拟合器无共享代码路径；
2. FSV：拟合响应 vs 原始响应交给 **core/fsv.py 内核**（IEEE 1597.1
   独立实现）给 ADM/FDM/GDM 等级，目标 GDM ≤ Good（等级下标 ≤ 2）；
3. 无源性另设**独立于 skrf 半尺寸测试的直判**：在数据频带内密集重采样，
   直接对模型 S 矩阵做 SVD 取最大奇异值（``sigma_max_in_band``）。
skrf 自带的 ``get_rms_error`` 只作诊断旁证（本模块主口径是逐响应归一化 RMS），
不作裁判。

数值口径
--------
- ``rms``：``sqrt(mean_{i,j,k} |S_ij(f_k) - Sfit_ij(f_k)|^2)``（逐响应 + 逐频点
  归一，N 端口之间可比）；``rms_db = 20*log10(rms)``，阈值默认 -40 dB。
  skrf 的 ``get_rms_error()`` 是"逐响应均值再求和开方"（随端口数放大），
  本模块另存于 ``fit.skrf_get_rms_error`` 供溯源。
- 频率单位一律 Hz，极点/留数用 rad/s（skrf 口径）。
- 拟合确定性：同一 request 两次调用输出逐字节一致（固定阶数、无随机）。

无源性口径（重要）
------------------
``passivity_test()`` 在**全频轴**（含外推，上界可为 +inf）判违规；数值模型的
外推段常出现伪违规。物理上无源化只要求在**模型有效频带**（数据频带
``[f_min, f_max]``）内成立——这也是 skrf ``passivity_enforce`` 文档对 ``f_max``
的定义（"usually equals the highest sample frequency of the fitted Network"）。
故本模块同时报告全轴结果与带内结果，并以**带内直判 SVD**（``passive_in_band``）
作为无源性结论：频段与数据带有交集即为带内违规，``passivity_enforce`` 仅在此
情况下触发。

诚实的边界
----------
- **SPICE 回放是"回放自检"，不是第三方 SPICE 等价验证**：
  ``replay_spice_subcircuit_s`` 用本模块内置的**纯 Python 复数 MNA（AC）
  求解器**按标准 SPICE 元素语义（R/L/C/V/I/G/E/F/H）求解导出网表、提取
  端口 Y→S 参数：它能证明"导出网表在标准 SPICE 元素语义下重现模型与原始
  S 参数"（实测回放 vs 模型 max|ΔS| ~ 1e-15），**不能**替代
  ngspice/LTspice/Xyce 等第三方仿真器的交叉验证。调用方不得把
  ``spice_replay.status=="ok"`` 读成"第三方 SPICE 仿真通过"。
- **第三方交叉验证（ngspice .AC 对拍）在 adapters 层**（core 禁 import
  adapters，分层不可破）：本机 ngspice-47 可用（``tools/ngspice``，
  2026-09-15 真机标定 .AC/wrdata 复数输出格式，见
  ``adapters/spice_netlist.py`` 模块 docstring）——
  ``adapters.spice_netlist.xval_macromodel_spice`` 渲染 .AC deck → 逐端口
  1V 激励真跑 → wrdata 复数解析 → Y→S → FSV（fsv.py 内核）评级；Xyce 仍无
  二进制，维持探测钩子。``fit_macromodel`` 主链**不缺省依赖 ngspice**
  （存量测环境无该工具，#139 精神：缺工具时 best-effort 跳过，不炸主链）。
- ``passivity_enforce`` 是 skrf 的启发式迭代，实践中可能（a）改不动带内违规，
  或（b）大幅劣化带内精度。本模块如实同时返回 enforce 前/后 RMS 与 SVD，
  不隐藏劣化，也不用"enforce 后过"覆盖"拟合退化"。
- 带内直判只在 ``passivity_samples`` 个密集采样点上做 SVD，极窄违规带可能
  被漏检；``skrf_violation_bands_hz`` 同时给出半尺寸测试的解析频段边界。

JSON 接口（``fit_macromodel`` 的 request）
-----------------------------------------
``freq_hz``      : 必填，list[float]，Hz，严格递增，长度 ≥ 16（FSV 下限）
``s``            : 必填，复数 S 矩阵；每个元素取以下三选一：
                   - ``[re, im]`` 二元序列（推荐，JSON 原生）
                   - ``{"re": .., "im": ..}``（或 real/imag 键）
                   - 实数（虚部按 0）
                   结构可为 ``[nf][n][n]``，或 ``[nf][n*n]`` 扁平（按 n² 推断
                   n），或 pairwise ``[nf][n][n][2]``。
``s_real``+``s_imag`` : 可选，替代 ``s`` 的显式实/虚 3D 数组（无歧义）
``z0``           : 可选，实数或 list[float]（长度 n）或 n×n；缺省 50
``spice_path``   : 可选，写出 SPICE 子电路的文件路径；父目录自动创建
``subckt_name``  : 可选，.SUBCKT 名，缺省 ``s_equivalent``
``n_poles_real`` / ``n_poles_cmplx`` : 可选；**同时给出**表示显式定阶
                   （单次拟合，RMS 未达阈值则显式报错"极点不足"）；缺省走
                   确定性阶梯 ``DEFAULT_ORDER_LADDER``（逐级升阶直到达标或
                   用尽，取 RMS 最优者，不抛错）
``rms_threshold_db`` : 可选，缺省 -40.0
``require_rms``  : 可选 bool，缺省 = 是否显式定阶
``enforce_passivity`` : 可选 bool，缺省 True
``enforce_samples``   : 可选 int，``passivity_enforce`` 采样数，缺省 1000
``passivity_samples`` : 可选 int，带内直判 SVD 采样数，缺省 401
``order_ladder`` : 可选，自定义阶梯，如 ``[[1,2],[2,4]]``

返回值见 ``fit_macromodel`` docstring。全部为 JSON 原生类型（numpy 标量已
转 float/int；+inf 频段上界写 ``null``）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import skrf
from skrf.vectorFitting import VectorFitting

from rfauto.core.errors import RFAutoError
from rfauto.core.fsv import GRADE_CODES, fsv, grade_index_of

__all__ = [
    "DEFAULT_ENFORCE_SAMPLES",
    "DEFAULT_ORDER_LADDER",
    "DEFAULT_REPLAY_CONSISTENCY_TOL",
    "DEFAULT_RMS_THRESHOLD_DB",
    "GRADE_INDEX_GOOD",
    "MIN_FREQ_POINTS",
    "MacromodelError",
    "MacromodelFitError",
    "MacromodelInputError",
    "compare_s_matrices",
    "fit_macromodel",
    "model_response",
    "replay_spice_ac_response",
    "replay_spice_subcircuit_s",
    "request_from_touchstone",
    "spice_subcircuit_port_info",
    "validate_spice_subcircuit",
]

#: fit RMS（dB 口径）默认阈值：-40 dB。
DEFAULT_RMS_THRESHOLD_DB = -40.0
#: FSV 等级下标 <= 该值即"≥ Good"（Ex=0, VG=1, G=2）。
GRADE_INDEX_GOOD = 2
#: 最少频点数（与 fsv.MIN_POINTS 对齐：FSV 裁判需 ≥16 点）。
MIN_FREQ_POINTS = 16
#: 缺省确定性升阶梯（n_poles_real, n_poles_cmplx）；只升不随机。
DEFAULT_ORDER_LADDER: tuple[tuple[int, int], ...] = ((1, 2), (2, 4), (4, 8))
#: 缺省 passivity_enforce 采样数（skrf 缺省 200 偏小，实测易失败）。
DEFAULT_ENFORCE_SAMPLES = 1000
#: 带内无源直判容差（SVD 最大奇异值 <= 1 + tol 判无源）。
_PASSIVITY_TOL = 1e-6
#: 带内无源直判默认采样数。
_DENSE_PASSIVITY_SAMPLES = 401
#: dB 下限（|S|=0 时的保护，避免 -inf 参与 JSON）。
_DB_FLOOR = 1e-30
#: S 参数等效子电路至少应含的元素类型（R/G/V/C）。
_REQUIRED_SPICE_TYPES = ("R", "G", "V", "C")
#: 两节点 + 一个数值元素的节点数口径。
_SPICE_NODES_2 = frozenset({"R", "L", "C", "V", "I"})
#: 四节点受控源（VCCS/VCVS）。
_SPICE_NODES_4 = frozenset({"G", "E"})
#: name n+ n- Vctrl value 型受控源。
_SPICE_CONTROLLED = frozenset({"F", "H"})


class MacromodelError(RFAutoError):
    """宏模型内核异常基类。"""

    error_type = "MacromodelError"


class MacromodelInputError(MacromodelError):
    """输入非法（频率轴/S 矩阵维度/z0/频点数等）→ 直接拒绝。"""

    error_type = "MacromodelInputError"


class MacromodelFitError(MacromodelError):
    """拟合失败或**显式定阶**下极点不足（RMS 未达阈值）→ 显式报错。"""

    error_type = "MacromodelFitError"


# --------------------------------------------------------------------------- #
# 输入收敛（JSON -> ndarray）
# --------------------------------------------------------------------------- #

def _convert_object(value: Any) -> Any:
    """把 dict 形复数叶子 / 嵌套 list 递归转成 Python complex 嵌套结构。"""
    if isinstance(value, dict):
        if "re" in value or "real" in value:
            re_ = float(value.get("re", value.get("real")))
            im_ = float(value.get("im", value.get("imag", 0.0)))
            return complex(re_, im_)
        raise MacromodelInputError(f"复数 dict 需含 're'/'im'（或 'real'/'imag'），得到键 {sorted(value)}")
    if isinstance(value, (list, tuple)):
        return [_convert_object(v) for v in value]
    if isinstance(value, complex):
        return value
    if isinstance(value, (int, float, np.integer, np.floating)):
        return complex(float(value))
    raise MacromodelInputError(f"S 参数元素类型非法: {type(value).__name__}")


def _to_complex_array(raw: Any, name: str) -> np.ndarray:
    """S 参数原始结构 -> 复数 ndarray（[nf][n][n] 或 [nf][n*n] 或 pairwise）。"""
    arr = np.asarray(raw)
    if arr.dtype == object:
        return np.asarray(_convert_object(raw), dtype=complex)
    if not np.issubdtype(arr.dtype, np.number):
        raise MacromodelInputError(f"{name}: 元素类型非法（dtype={arr.dtype}）")
    if np.iscomplexobj(arr):
        return arr.astype(complex)
    arr = arr.astype(float)
    if arr.ndim == 4 and arr.shape[-1] == 2:
        return arr[..., 0] + 1j * arr[..., 1]
    return arr.astype(complex)


def _coerce_z0(raw: Any, n_ports: int) -> Any:
    """z0 -> 标量 float / 长度 n 向量 / n×n 实矩阵（拒绝复数 z0）。"""
    if raw is None:
        return 50.0
    arr = np.asarray(raw)
    if np.iscomplexobj(arr) and np.any(np.abs(arr.imag) > 0.0):
        raise MacromodelInputError("z0 必须是实数（本内核不支持复数参考阻抗）")
    arr = np.asarray(raw, dtype=float)
    if arr.ndim == 0:
        if not np.isfinite(arr) or float(arr) <= 0.0:
            raise MacromodelInputError(f"z0 必须是有限正实数，得到 {raw!r}")
        return float(arr)
    if arr.ndim == 1:
        if arr.size != n_ports:
            raise MacromodelInputError(f"z0 向量长度 {arr.size} != 端口数 {n_ports}")
        if not np.all(np.isfinite(arr)) or np.any(arr <= 0.0):
            raise MacromodelInputError("z0 向量必须全为有限正实数")
        return arr
    if arr.ndim == 2 and arr.shape == (n_ports, n_ports):
        if not np.all(np.isfinite(arr)) or np.any(arr <= 0.0):
            raise MacromodelInputError("z0 矩阵必须全为有限正实数")
        return arr
    raise MacromodelInputError(f"z0 形状非法: {arr.shape}（需标量 / 长度 {n_ports} 向量 / {n_ports}x{n_ports} 矩阵）")


def _normalize_request(request: Any) -> tuple[np.ndarray, np.ndarray, Any, int]:
    """request dict -> (freq_hz, s[nf,n,n], z0, n_ports)；非法输入显式报错。"""
    if not isinstance(request, dict):
        raise MacromodelInputError(f"request 必须是 dict，得到 {type(request).__name__}")

    freq_raw = request.get("freq_hz", request.get("freq"))
    if freq_raw is None:
        raise MacromodelInputError("缺少频率轴：需要 'freq_hz'（Hz）或 'freq'")
    freq = np.asarray(freq_raw, dtype=float).ravel()
    if freq.size < MIN_FREQ_POINTS:
        raise MacromodelInputError(
            f"频点数 {freq.size} < MIN_FREQ_POINTS={MIN_FREQ_POINTS}（FSV 保真裁判要求 ≥16 点）"
        )
    if not np.all(np.isfinite(freq)):
        raise MacromodelInputError("频率轴含 NaN/Inf")
    if np.any(np.diff(freq) <= 0.0):
        raise MacromodelInputError("频率轴必须严格递增（不支持重复点/乱序）")
    n_freq = int(freq.size)

    s_raw = request.get("s")
    if s_raw is None:
        re_raw = request.get("s_real")
        im_raw = request.get("s_imag")
        if re_raw is None or im_raw is None:
            raise MacromodelInputError(
                "缺少 S 参数：需要 's'（[re, im] 对 / {'re','im'} / 实数）或 's_real'+'s_imag'"
            )
        re_arr = np.asarray(re_raw, dtype=float)
        im_arr = np.asarray(im_raw, dtype=float)
        if re_arr.shape != im_arr.shape:
            raise MacromodelInputError(f"s_real{re_arr.shape} 与 s_imag{im_arr.shape} 形状不一致")
        s = re_arr + 1j * im_arr
    else:
        s = _to_complex_array(s_raw, "s")

    if s.ndim == 3:
        if int(s.shape[0]) != n_freq:
            raise MacromodelInputError(f"S 矩阵频率维 {s.shape[0]} != 频点数 {n_freq}")
        if int(s.shape[1]) != int(s.shape[2]):
            raise MacromodelInputError(f"S 矩阵必须是 n×n 方阵，得到 {s.shape[1]}x{s.shape[2]}")
        n_ports = int(s.shape[1])
    elif s.ndim == 2:
        if int(s.shape[0]) != n_freq:
            raise MacromodelInputError(f"S 矩阵行数 {s.shape[0]} != 频点数 {n_freq}")
        k = int(s.shape[1])
        root = round(np.sqrt(k))
        if root < 1 or root * root != k:
            raise MacromodelInputError(f"扁平 S 矩阵每行 {k} 个元素不是完全平方数（无法推断端口数）")
        n_ports = root
        s = s.reshape(n_freq, n_ports, n_ports)
    else:
        raise MacromodelInputError(f"S 参数维度非法: ndim={s.ndim}（需 2 或 3，pairwise 为 4）")

    if not np.all(np.isfinite(s)):
        raise MacromodelInputError("S 参数含 NaN/Inf")

    n_ports_key = request.get("n_ports")
    if n_ports_key is not None and int(n_ports_key) != n_ports:
        raise MacromodelInputError(f"声明的 n_ports={n_ports_key} 与 S 矩阵推断的 {n_ports} 不一致")

    z0 = _coerce_z0(request.get("z0"), n_ports)
    return freq, s, z0, n_ports


# --------------------------------------------------------------------------- #
# 模型响应 / 拟合 RMS
# --------------------------------------------------------------------------- #

def model_response(vf: VectorFitting, freq: np.ndarray, n_ports: int) -> np.ndarray:
    """取 VF 模型在给定频点的全 S 矩阵（[nf, n, n]，确定性）。"""
    f = np.asarray(freq, dtype=float).ravel()
    out = np.zeros((f.size, n_ports, n_ports), dtype=complex)
    for i in range(n_ports):
        for j in range(n_ports):
            out[:, i, j] = np.asarray(vf.get_model_response(i, j, f), dtype=complex).ravel()
    return out


def _fit_rms(vf: VectorFitting, freq: np.ndarray, s_orig: np.ndarray, n_ports: int) -> tuple[float, float]:
    """逐响应+逐频点归一化 RMS（线性幅度）与其 dB 值。"""
    s_fit = model_response(vf, freq, n_ports)
    err2 = float(np.sum(np.abs(s_orig - s_fit) ** 2))
    total = int(freq.size) * n_ports * n_ports
    rms = float(np.sqrt(err2 / total))
    rms_db = float(20.0 * np.log10(max(rms, _DB_FLOOR)))
    return rms, rms_db


# --------------------------------------------------------------------------- #
# 无源性
# --------------------------------------------------------------------------- #

def _json_band(band: Any) -> list[float | None]:
    """频段 -> JSON 安全形式（+inf 上界写 null）。"""
    lo, hi = float(band[0]), float(band[1])
    return [lo, None if np.isinf(hi) else hi]


def _passivity_state(vf: VectorFitting, freq: np.ndarray, n_ports: int, n_dense: int) -> dict[str, Any]:
    """无源性状态：skrf 半尺寸测试（全轴）+ 带内直判 SVD（裁判口径）。"""
    bands: np.ndarray | None = None
    test_error: str | None = None
    try:
        raw_bands = np.asarray(vf.passivity_test(), dtype=float)
        bands = raw_bands.reshape(-1, 2) if raw_bands.size else np.zeros((0, 2), dtype=float)
    except Exception as exc:  # skrf 半尺寸测试可因 (D±I) 奇异而失败，如实上报
        test_error = f"{type(exc).__name__}: {exc}"

    f_min, f_max = float(freq[0]), float(freq[-1])
    in_band: list[list[float | None]] = []
    if bands is not None:
        in_band = [_json_band(b) for b in bands if float(b[1]) > f_min and float(b[0]) < f_max]

    n_pts = max(int(n_dense), 2)
    fg = np.linspace(f_min, f_max, n_pts)
    s_dense = model_response(vf, fg, n_ports)
    sigma_max = float(max(np.linalg.svd(s_dense[k], compute_uv=False).max() for k in range(n_pts)))

    return {
        "skrf_passive_full_band": None if bands is None else bool(bands.shape[0] == 0),
        "skrf_violation_bands_hz": None if bands is None else [_json_band(b) for b in bands],
        "skrf_test_error": test_error,
        "violation_bands_in_band_hz": in_band,
        "passive_in_band_skrf": None if bands is None else bool(not in_band),
        "sigma_max_in_band": sigma_max,
        "passive_in_band": bool(sigma_max <= 1.0 + _PASSIVITY_TOL),
        "n_dense": n_pts,
    }


# --------------------------------------------------------------------------- #
# SPICE 子电路结构校验
# --------------------------------------------------------------------------- #

def _spice_node_arity(key: str) -> int | None:
    """元素首字母 -> 需要解析的节点/控制源令牌数（不含元素名与数值）。"""
    if key in _SPICE_NODES_2:
        return 2
    if key in _SPICE_NODES_4:
        return 4
    if key in _SPICE_CONTROLLED:
        return 3
    return None


def validate_spice_subcircuit(
    path: str | Path,
    *,
    expected_ports: int | None = None,
    expected_name: str | None = None,
) -> dict[str, Any]:
    """对 skrf 写出的 SPICE 子电路做**结构校验**（不做网表仿真）。

    校验项：.SUBCKT 名 / 端口节点数与命名 / .ENDS / 必需元素类型（R/G/V/C）/
    元素行令牌元数 / 元素名唯一性 / 未知元素类型。
    """
    p = Path(path)
    info: dict[str, Any] = {
        "path": str(p),
        "exists": p.is_file(),
        "subckt_name": None,
        "nodes": [],
        "n_ports": None,
        "element_counts": {},
        "n_elements": 0,
        "has_ends": False,
        "pin_names_ok": None,
        "valid": False,
        "errors": [],
    }
    errors: list[str] = info["errors"]
    if not p.is_file():
        errors.append(f"文件不存在: {p}")
        return info

    text = p.read_text(encoding="utf-8", errors="replace")
    counts: dict[str, int] = {}
    seen_names: set[str] = set()
    for lineno, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("*"):
            continue
        low = line.lower()
        tokens = line.split()
        if low.startswith(".subckt"):
            if len(tokens) < 3:
                errors.append(f"第 {lineno} 行 .SUBCKT 定义不完整: {line!r}")
                continue
            if info["subckt_name"] is not None:
                errors.append(f"第 {lineno} 行出现第二个 .SUBCKT（应为单子电路文件）")
            info["subckt_name"] = tokens[1]
            info["nodes"] = tokens[2:]
            info["n_ports"] = len(tokens[2:])
            continue
        if low.startswith(".ends"):
            info["has_ends"] = True
            continue
        if line.startswith("."):
            continue
        key = tokens[0][0].upper()
        counts[key] = counts.get(key, 0) + 1
        arity = _spice_node_arity(key)
        if arity is None:
            errors.append(f"第 {lineno} 行未知元素类型 {key!r}: {line!r}")
        elif len(tokens) < arity + 2:
            errors.append(f"第 {lineno} 行元素令牌不足（{key} 需 ≥{arity + 2} 个）: {line!r}")
        if tokens[0] in seen_names:
            errors.append(f"第 {lineno} 行元素名重复: {tokens[0]}")
        seen_names.add(tokens[0])

    info["element_counts"] = counts
    info["n_elements"] = int(sum(counts.values()))

    if info["subckt_name"] is None:
        errors.append("未找到 .SUBCKT 定义")
    if not info["has_ends"]:
        errors.append("缺少 .ENDS 结束行")
    for etype in _REQUIRED_SPICE_TYPES:
        if counts.get(etype, 0) == 0:
            errors.append(f"缺少必需元素类型 {etype}")
    if expected_name is not None and info["subckt_name"] != expected_name:
        errors.append(f"子电路名不符：实际 {info['subckt_name']!r}，期望 {expected_name!r}")
    if expected_ports is not None:
        if info["n_ports"] != int(expected_ports):
            errors.append(f"端口数不符：节点 {info['n_ports']}，期望 {expected_ports}")
        pins = info["nodes"]
        plain = [f"p{k + 1}" for k in range(int(expected_ports))]
        ref_pins = [x for k in range(int(expected_ports)) for x in (f"p{k + 1}", f"p{k + 1}_ref")]
        ok = pins in (plain, ref_pins)
        info["pin_names_ok"] = bool(ok)
        if not ok:
            errors.append(f"端口节点命名不符：{pins!r}（期望 {plain!r} 或参考针形式）")

    info["valid"] = bool(not errors)
    return info


# --------------------------------------------------------------------------- #
# SPICE 回放自检（纯 Python 复数 MNA AC 求解；不依赖 ngspice.exe）
# --------------------------------------------------------------------------- #

#: 回放响应 vs 模型响应的一致性容差（逐元素 max|ΔS|，ok 门使用）。
DEFAULT_REPLAY_CONSISTENCY_TOL = 1e-6
#: 回放线性解的相对残差门：近奇异时 numpy 不报错只返回垃圾，须显式验证解。
_REPLAY_RESIDUAL_TOL = 1e-6
#: gmin（每节点对地最小电导，与 ngspice 缺省一致）：仅当直接求解奇异时作为
#: 重试手段，用于解锁"浮动公共模"网表（如 skrf 参考针形式的端口网络）。
_REPLAY_GMIN = 1e-12
#: 回放求解器支持的元素类型 -> 节点令牌数（不含元素名/控制源/数值）。
_REPLAY_KIND_NODE_ARITY: dict[str, int] = {"R": 2, "L": 2, "C": 2, "V": 2, "I": 2, "G": 4, "E": 4}
#: 受控源（name n+ n- 控制源 数值）。
_REPLAY_CONTROLLED_KINDS = frozenset({"F", "H"})
#: 带电流未知量的电压源类元件（MNA 增广分支）。
_REPLAY_BRANCH_KINDS = frozenset({"V", "E", "H"})
#: SPICE 数值后缀因子（先匹配双字母 meg/mil，再单字母；skrf 导出只写纯浮点，
#: 后缀支持用于人工网表的兼容）。
_REPLAY_SCALE_FACTORS: tuple[tuple[str, float], ...] = (
    ("meg", 1e6),
    ("mil", 25.4e-6),
    ("t", 1e12),
    ("g", 1e9),
    ("k", 1e3),
    ("m", 1e-3),
    ("u", 1e-6),
    ("n", 1e-9),
    ("p", 1e-12),
    ("f", 1e-15),
)
_REPLAY_NUMBER_RE = re.compile(r"^([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)([A-Za-z]*)$")
#: 回放自检的定性声明（随结果返回，防误读为第三方 SPICE 等价）。
_REPLAY_DISCLAIMER = (
    "回放自检（replay-selfcheck）：由本仓库纯 Python 复数 MNA（AC）求解器按标准 SPICE "
    "元素语义（R/L/C/V/I/G/E/F/H）求解导出网表并提取端口 S 参数；它验证的是『导出网表在"
    "标准 SPICE 语义下重现模型/原始 S 参数』，不是 ngspice/LTspice/Xyce 等第三方 SPICE "
    "仿真器的等价验证；第三方等价对拍另走 adapters.spice_netlist 的 ngspice .AC 通道"
    "（xval_macromodel_spice，与回放自检是两条独立证据链）；"
    "不得把 status=='ok' 读作第三方仿真通过。"
)


@dataclass(frozen=True)
class _SpiceElement:
    """一条网表元件行（语法层解析结果）。"""

    name: str
    kind: str
    nodes: tuple[str, ...]
    value: float
    control: str | None = None


def _parse_spice_number(token: str, where: str) -> float:
    """SPICE 数值令牌 -> float（支持科学计数与 t/g/meg/k/m/u/n/p/f/mil 后缀）。"""
    m = _REPLAY_NUMBER_RE.match(token.strip())
    if m is None:
        raise MacromodelInputError(f"{where}: SPICE 数值无法解析: {token!r}")
    value = float(m.group(1))
    suffix = m.group(2).lower()
    if not suffix:
        return value
    for prefix, factor in _REPLAY_SCALE_FACTORS:
        if suffix.startswith(prefix):
            return value * factor
    raise MacromodelInputError(f"{where}: 未知 SPICE 数值后缀 {m.group(2)!r}（token={token!r}）")


#: 回放解析器接受的点指令白名单（其余一律显式报错——原实现静默忽略会让
#: .PARAM 丢失静默改元件值，属不诚实行为，2026-09-15 升级）。
_REPLAY_DIRECTIVE_WHITELIST = frozenset({".subckt", ".ends", ".param", ".inc", ".include"})
#: 参数名/裸标识符形态（.PARAM 引用与 `{name}` 单参数引用的合法性检查）。
_REPLAY_IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _parse_param_assignments(line: str, lineno: int) -> dict[str, float]:
    """解析 .PARAM 行的 ``name=value`` 赋值（等号两侧空格可有可无）。

    仅支持**数字字面量**（含 SPICE 后缀）；表达式/函数/参数链式引用显式报错
    （.PARAM 丢失会静默改元件值，宁拒绝不猜）。
    """
    parts = line.split(None, 1)
    body = parts[1] if len(parts) > 1 else ""
    flat = body.replace("=", " = ").split()
    if not flat:
        raise MacromodelInputError(f"第 {lineno} 行 .PARAM 缺少赋值: {line!r}")
    out: dict[str, float] = {}
    i = 0
    while i < len(flat):
        if i + 2 > len(flat) or flat[i + 1] != "=":
            raise MacromodelInputError(
                f"第 {lineno} 行 .PARAM 赋值语法非法（需 name=value）: {line!r}"
            )
        name_token, value_token = flat[i], flat[i + 2]
        key = name_token.lower()
        if not _REPLAY_IDENT_RE.match(name_token):
            raise MacromodelInputError(f"第 {lineno} 行 .PARAM 参数名非法: {name_token!r}")
        if key in out:
            raise MacromodelInputError(f"第 {lineno} 行 .PARAM 参数重复定义: {name_token!r}")
        if _REPLAY_IDENT_RE.match(value_token) or value_token.startswith("{"):
            raise MacromodelInputError(
                f"第 {lineno} 行 .PARAM 值 {value_token!r} 是表达式/函数/参数引用："
                "回放解析器只支持数字字面量（含 t/g/meg/k/m/u/n/p/f/mil 后缀）"
            )
        out[key] = _parse_spice_number(value_token, f"第 {lineno} 行 .PARAM {name_token}")
        i += 3
    return out


def _resolve_replay_value(token: str, params: dict[str, float], where: str) -> float:
    """元件数值令牌解析：数字字面量 / .PARAM 名 / ``{参数名}`` 单参数引用。

    表达式（``{2*3}``、函数调用等）与未定义参数显式报错，不静默取 0/跳过。
    """
    t = token.strip()
    if t.startswith("{") and t.endswith("}"):
        inner = t[1:-1].strip()
        if _REPLAY_IDENT_RE.match(inner) and inner.lower() in params:
            return params[inner.lower()]
        raise MacromodelInputError(
            f"{where}: 元件值 {token!r} 中的花括号表达式不被支持"
            "（只支持 {参数名} 单参数引用且该参数已由 .PARAM 定义）"
        )
    if _REPLAY_IDENT_RE.match(t):
        key = t.lower()
        if key in params:
            return params[key]
        raise MacromodelInputError(f"{where}: 引用了未定义的 .PARAM 参数 {token!r}")
    return _parse_spice_number(t, where)


def _parse_spice_netlist(path: str | Path) -> dict[str, Any]:
    """解析 SPICE 子电路（语法层）：.SUBCKT 名/端口、元件行、续行、指令行。

    指令白名单：``.SUBCKT/.ENDS/.PARAM/.INCLUDE(.INC)``——白名单外显式报错
    （不再静默忽略）。``.PARAM`` 只支持数字字面量并做元件值替换（表达式/函数
    显式报错）；``.INCLUDE`` 只支持单层内联（含防循环引用），内联后整体仍限
    单个 .SUBCKT/.ENDS。
    """
    p = Path(path)
    if not p.is_file():
        raise MacromodelInputError(f"SPICE 网表不存在: {p}")

    elements: list[_SpiceElement] = []
    subckt_name: str | None = None
    pins: list[str] = []
    has_ends = False
    params: dict[str, float] = {}
    seen_names: set[str] = set()
    state = {"pending": None, "pending_lineno": 0}  # type: dict[str, Any]

    def emit(tokens: list[str], lineno: int) -> None:
        name = tokens[0]
        kind = name[0].upper()
        if name in seen_names:
            raise MacromodelInputError(f"第 {lineno} 行元素名重复: {name!r}")
        seen_names.add(name)
        if kind in _REPLAY_CONTROLLED_KINDS:
            if len(tokens) < 5:
                raise MacromodelInputError(
                    f"第 {lineno} 行受控源令牌不足（需 name n+ n- 控制源 数值）: {tokens!r}"
                )
            control = tokens[3]
            nodes = (tokens[1], tokens[2])
            value = _resolve_replay_value(tokens[4], params, f"第 {lineno} 行 {name}")
        else:
            arity = _REPLAY_KIND_NODE_ARITY.get(kind)
            if arity is None:
                raise MacromodelInputError(
                    f"第 {lineno} 行元素类型 {kind!r} 不被回放求解器支持"
                    f"（支持 R/L/C/V/I/G/E/F/H）: {tokens!r}"
                )
            if len(tokens) < arity + 2:
                raise MacromodelInputError(f"第 {lineno} 行元素令牌不足（{kind} 需 ≥{arity + 2} 个）: {tokens!r}")
            control = None
            nodes = tuple(tokens[1 : 1 + arity])
            value = _resolve_replay_value(tokens[1 + arity], params, f"第 {lineno} 行 {name}")
        elements.append(_SpiceElement(name=name, kind=kind, nodes=nodes, value=value, control=control))

    def consume_lines(lines: list[tuple[int, str]], origin: Path, depth: int, visited: set[Path]) -> None:
        nonlocal subckt_name, pins, has_ends
        for lineno, raw in lines:
            line = raw.strip()
            if not line or line.startswith("*"):
                continue
            if line.startswith("+"):  # 续行（skrf 导出不产生；兼容人工网表）
                if state["pending"] is None:
                    raise MacromodelInputError(f"第 {lineno} 行以 '+' 续行开头，但前面没有可续的元素行")
                state["pending"].extend(line[1:].split())
                continue
            if state["pending"] is not None:
                emit(state["pending"], state["pending_lineno"])
                state["pending"] = None
            tokens = line.split()
            head = tokens[0].lower()
            if not line.startswith("."):
                state["pending"] = tokens
                state["pending_lineno"] = lineno
                continue
            if head not in _REPLAY_DIRECTIVE_WHITELIST:
                raise MacromodelInputError(
                    f"第 {lineno} 行未知指令 {tokens[0]!r}：回放解析器仅支持 "
                    ".SUBCKT/.ENDS/.PARAM/.INCLUDE（原实现对此静默忽略会静默丢失 "
                    ".PARAM 元件值，现已显式报错）"
                )
            if head == ".subckt":
                if len(tokens) < 3:
                    raise MacromodelInputError(f"第 {lineno} 行 .SUBCKT 定义不完整: {line!r}")
                if subckt_name is not None:
                    raise MacromodelInputError(f"第 {lineno} 行出现第二个 .SUBCKT（回放只支持单子电路文件）")
                subckt_name = tokens[1]
                pins = tokens[2:]
            elif head == ".ends":
                has_ends = True
            elif head == ".param":
                params.update(_parse_param_assignments(line, lineno))
            else:  # .inc / .include：单层内联 + 防循环引用
                if depth >= 1:
                    raise MacromodelInputError(
                        f"第 {lineno} 行嵌套 .INCLUDE：回放解析器只支持单层内联"
                        "（被包含文件中不得再出现 .INCLUDE）"
                    )
                if len(tokens) < 2:
                    raise MacromodelInputError(f"第 {lineno} 行 {tokens[0]} 缺少文件路径: {line!r}")
                inc = Path(tokens[1].strip('"').strip("'"))
                if not inc.is_absolute():
                    inc = origin.parent / inc
                inc_resolved = inc.resolve()
                if inc_resolved in visited:
                    raise MacromodelInputError(
                        f"第 {lineno} 行 .INCLUDE 循环引用: {tokens[1]!r}（已在包含链中）"
                    )
                if not inc_resolved.is_file():
                    raise MacromodelInputError(f"第 {lineno} 行 .INCLUDE 文件不存在: {inc_resolved}")
                visited.add(inc_resolved)
                inc_text = inc_resolved.read_text(encoding="utf-8", errors="replace")
                consume_lines(
                    list(enumerate(inc_text.splitlines(), 1)), inc_resolved, depth + 1, visited
                )

    visited = {p.resolve()}
    consume_lines(list(enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1)), p, 0, visited)
    if state["pending"] is not None:
        emit(state["pending"], state["pending_lineno"])

    if subckt_name is None:
        raise MacromodelInputError(f"网表中未找到 .SUBCKT 定义: {p}")
    if not has_ends:
        raise MacromodelInputError(f"网表缺少 .ENDS 结束行: {p}")
    if not elements:
        raise MacromodelInputError(f"网表中没有任何元件行: {p}")
    if "0" in pins:
        raise MacromodelInputError(f".SUBCKT 端口不能是地节点 '0': {pins!r}")
    return {
        "path": p,
        "subckt_name": subckt_name,
        "pins": pins,
        "elements": elements,
        "params": params,
    }


def _replay_port_layout(pins: list[str]) -> tuple[list[str], list[str | None], int]:
    """端口布局：``p1..pN``（参考=全局地）或 ``p1 p1_ref p2 p2_ref ...``（差分参考针）。

    返回 (端口正极节点, 各端口参考节点（None=全局地）, 端口数)。
    """
    n = len(pins)
    if n > 0 and n % 2 == 0 and all(
        pins[2 * k] == f"p{k + 1}" and pins[2 * k + 1] == f"p{k + 1}_ref" for k in range(n // 2)
    ):
        return [pins[2 * k] for k in range(n // 2)], [pins[2 * k + 1] for k in range(n // 2)], n // 2
    return list(pins), [None] * n, n


def _resolve_replay_z0(z0: Any, elements: list[_SpiceElement], n_ports: int) -> tuple[list[float], str]:
    """回放参考阻抗：显式给定（标量/长度 N 序列）或从网表端口参考电阻 R1..RN 推断。"""
    if z0 is None:
        by_name = {el.name.upper(): el for el in elements}
        z0_list: list[float] = []
        for k in range(n_ports):
            el = by_name.get(f"R{k + 1}")
            if el is None or el.kind != "R" or not np.isfinite(el.value) or el.value <= 0.0:
                raise MacromodelInputError(
                    f"无法从网表推断端口 {k + 1} 的参考阻抗（缺少正有限值的端口参考电阻 R{k + 1}）；请显式传 z0"
                )
            z0_list.append(el.value)
        return z0_list, "inferred_from_R_i"
    arr = np.asarray(z0, dtype=float).ravel()
    if arr.size == 1:
        arr = np.full(n_ports, float(arr[0]))
    if arr.size != n_ports:
        raise MacromodelInputError(f"z0 长度 {arr.size} != 回放端口数 {n_ports}")
    if not np.all(np.isfinite(arr)) or np.any(arr <= 0.0):
        raise MacromodelInputError("z0 必须全为有限正实数")
    return [float(x) for x in arr], "explicit"


def _stamp_admittance(a_mat: np.ndarray, gm: complex, na: int | None, nb: int | None) -> None:
    """二端导纳 gm 的 MNA KCL 戳（na/nb 为节点索引，None=全局地）。"""
    if na is not None:
        a_mat[na, na] += gm
        if nb is not None:
            a_mat[na, nb] -= gm
    if nb is not None:
        a_mat[nb, nb] += gm
        if na is not None:
            a_mat[nb, na] -= gm


def _node_volts(vmat: np.ndarray, node_idx: dict[str, int], name: str, n_port: int) -> np.ndarray:
    """取某节点在全部激励列上的电压（地节点 '0' 返回零向量）。"""
    idx = node_idx.get(name)
    return vmat[idx] if idx is not None else np.zeros(n_port, dtype=complex)


def _solve_equilibrated(a_full: np.ndarray, rhs_full: np.ndarray) -> np.ndarray:
    """行/列均衡化后 LU 求解再反缩放（数学上与直接求解等价）。

    skrf 综合网表的取值跨 ~46 个数量级（Rp 低至 1e-23 Ω、跨导高至 1e21），
    均衡化改善 LU 主元选取的数值稳健性。
    """
    r_max = np.max(np.abs(a_full), axis=1)
    r_max[r_max == 0.0] = 1.0
    a_scaled = a_full / r_max[:, None]
    rhs_scaled = rhs_full / r_max[:, None]
    c_max = np.max(np.abs(a_scaled), axis=0)
    c_max[c_max == 0.0] = 1.0
    sol = np.linalg.solve(a_scaled / c_max[None, :], rhs_scaled)
    return sol / c_max[:, None]


def _assert_replay_zero_sources(elements: list[_SpiceElement]) -> None:
    """S 参数提取入口的零输入校验：非零独立源显式拒绝（有源回放走
    ``replay_spice_ac_response``）。"""
    for el in elements:
        if el.kind in ("V", "I") and el.value != 0.0:
            raise MacromodelInputError(
                f"独立源 {el.name}（{el.kind}）数值必须为 0：回放按零输入线性响应提取 S 参数，"
                "V=0 电流采样器可用；非零独立激励会污染端口电流提取"
                "（有源网表请用 replay_spice_ac_response）"
            )


def _mna_build_frequency_system(
    elements: list[_SpiceElement],
    node_idx: dict[str, int],
    branch_index: dict[str, int],
    w: float,
    n_rhs: int,
    n_extra_rows: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """单频点元件 MNA 戳（不含端口激励支路）：返回 (a_mat, rhs)。

    独立源数值直接进 rhs（零输入 S 提取时恒 0；有源 AC 回放时数值=复数激励
    幅值，相位 0）。``n_extra_rows`` 为调用方预留的激励支路行列数（S 提取
    = 端口数，AC 回放 = 0）。含 0 Hz 且网表含 L 时显式报错（1/(jωL) 奇异）。
    """
    n_nodes = len(node_idx)
    size = n_nodes + len(branch_index) + n_extra_rows
    a_mat = np.zeros((size, size), dtype=complex)
    rhs = np.zeros((size, n_rhs), dtype=complex)
    if w == 0.0 and any(el.kind == "L" for el in elements):
        raise MacromodelInputError("频率轴含 0 Hz 且网表含电感 L（1/(jωL) 奇异）；回放频率请 > 0 Hz")

    for el in elements:
        nd = el.nodes
        na = node_idx.get(nd[0])
        nb = node_idx.get(nd[1]) if len(nd) > 1 else None
        if el.kind in ("R", "C", "L"):
            if el.kind == "R":
                gm = 1.0 / el.value
            elif el.kind == "C":
                gm = 1j * w * el.value
            else:
                gm = 1.0 / (1j * w * el.value)
            _stamp_admittance(a_mat, gm, na, nb)
        elif el.kind == "V":
            k = branch_index[el.name]
            if na is not None:
                a_mat[na, k] += 1.0
                a_mat[k, na] = 1.0
            if nb is not None:
                a_mat[nb, k] -= 1.0
                a_mat[k, nb] = -1.0
            rhs[k, :] = el.value
        elif el.kind == "I":
            if na is not None:
                rhs[na, :] -= el.value
            if nb is not None:
                rhs[nb, :] += el.value
        elif el.kind == "G":
            gm = el.value
            nc = node_idx.get(nd[2])
            nd_ = node_idx.get(nd[3])
            if na is not None:
                if nc is not None:
                    a_mat[na, nc] += gm
                if nd_ is not None:
                    a_mat[na, nd_] -= gm
            if nb is not None:
                if nc is not None:
                    a_mat[nb, nc] -= gm
                if nd_ is not None:
                    a_mat[nb, nd_] += gm
        elif el.kind == "F":
            kc = branch_index[el.control]
            if na is not None:
                a_mat[na, kc] += el.value
            if nb is not None:
                a_mat[nb, kc] -= el.value
        elif el.kind == "E":
            k = branch_index[el.name]
            nc = node_idx.get(nd[2])
            nd_ = node_idx.get(nd[3])
            if na is not None:
                a_mat[na, k] += 1.0
                a_mat[k, na] = 1.0
            if nb is not None:
                a_mat[nb, k] -= 1.0
                a_mat[k, nb] = -1.0
            if nc is not None:
                a_mat[k, nc] -= el.value
            if nd_ is not None:
                a_mat[k, nd_] += el.value
        else:  # H（CCVS）
            k = branch_index[el.name]
            kc = branch_index[el.control]
            if na is not None:
                a_mat[na, k] += 1.0
                a_mat[k, na] = 1.0
            if nb is not None:
                a_mat[nb, k] -= 1.0
                a_mat[k, nb] = -1.0
            a_mat[k, kc] -= el.value
    return a_mat, rhs


def _solve_mna_validated(
    a_mat: np.ndarray, rhs: np.ndarray, f_hz: float, n_nodes: int
) -> np.ndarray:
    """均衡化求解 + 奇异时按 ngspice gmin 惯例重试一次 + 残差自检。

    gmin 只加在节点对角元（非分支行），用于解锁浮动公共模网表（如 skrf
    参考针形式的端口网络 {p_i, s_i, p_i_ref} 无对地双边导纳——差分行为与
    公共模无关，gmin 以 ~gmin/G（约 1e-10 相对）的微压换取可解性）。
    """
    a_used = a_mat
    try:
        sol = _solve_equilibrated(a_mat, rhs)
    except np.linalg.LinAlgError:
        a_used = a_mat.copy()
        node_arange = np.arange(n_nodes)
        a_used[node_arange, node_arange] += _REPLAY_GMIN
        try:
            sol = _solve_equilibrated(a_used, rhs)
        except np.linalg.LinAlgError as exc:
            raise MacromodelError(
                f"回放 MNA 在 f={f_hz:.6g} Hz 矩阵奇异（含 gmin={_REPLAY_GMIN:g} 重试）："
                f"网表结构退化或元素取值矛盾: {exc}"
            ) from exc
    applied = a_used @ sol  # 解的残差自检（近奇异时 numpy 静默返回垃圾，须显式验证）
    residual = float(np.max(np.abs(applied - rhs)))
    residual_scale = float(np.max(np.abs(rhs))) + float(np.max(np.abs(applied)))
    if residual > _REPLAY_RESIDUAL_TOL * max(residual_scale, 1.0):
        raise MacromodelError(
            f"回放 MNA 在 f={f_hz:.6g} Hz 的线性解相对残差过大（{residual:.3e}），结果不可信；"
            "矩阵条件数过大，请检查网表数值"
        )
    return sol


def _mna_replay_indices(elements: list[_SpiceElement]) -> tuple[dict[str, int], list[_SpiceElement], dict[str, int]]:
    """回放 MNA 的节点/分支索引装配（S 提取与有源 AC 回放共用）。"""
    node_names: set[str] = set()
    for el in elements:
        node_names.update(el.nodes)
    node_names.discard("0")
    node_idx = {name: i for i, name in enumerate(sorted(node_names))}
    branch_elements = [el for el in elements if el.kind in _REPLAY_BRANCH_KINDS]
    branch_index = {el.name: len(node_idx) + k for k, el in enumerate(branch_elements)}
    return node_idx, branch_elements, branch_index


def _assert_replay_solvable(elements: list[_SpiceElement], branch_elements: list[_SpiceElement]) -> None:
    """求解器能力校验（一次性）：0Ω 电阻 / 0H 电感 / 受控源控制源悬空显式拒绝。"""
    branch_names = {el.name for el in branch_elements}
    for el in elements:
        if el.kind == "R" and el.value == 0.0:
            raise MacromodelInputError(f"电阻 {el.name} 值为 0，回放求解器不支持 0Ω 电阻")
        if el.kind == "L" and el.value == 0.0:
            raise MacromodelInputError(f"电感 {el.name} 值为 0，回放求解器不支持 0H 电感")
        if el.control is not None and el.control not in branch_names:
            raise MacromodelInputError(
                f"受控源 {el.name} 的控制源 {el.control!r} 不存在或不是 V/E/H 电压源"
            )


def _mna_ac_s(
    elements: list[_SpiceElement],
    port_nodes: list[str],
    ref_nodes: list[str | None],
    freq: np.ndarray,
    z0_list: list[float],
) -> np.ndarray:
    """复数 MNA（AC）求解端口 Y 矩阵并转换为参考阻抗 z0 下的 S 矩阵。

    语义口径（标准 SPICE）：
    - R/C/L：二端导纳 1/R、jωC、1/(jωL)；
    - V：独立电压源（增广分支电流 I，方向 n+→n-）；值必须为 0（电流采样器，
      由 ``_assert_replay_zero_sources`` 在 S 提取入口校验）；
    - I：独立电流源（值必须为 0，同上）；
    - G：VCCS，电流 n+→n- = gm·(V(c+)-V(c-))；
    - F：CCCS，电流 n+→n- = gain·I(控制 V/E/H)；
    - E：VCVS，V(n+)-V(n-) = gain·(V(c+)-V(c-))（增广分支电流）；
    - H：CCVS，V(n+)-V(n-) = rm·I(控制 V/E/H)（增广分支电流）。
    端口电流由网表元件电流逐一求和（不经激励源支路），Y[i,j] = 端口 i 流入电流
    / 端口 j 单位激励；S = D⁻¹(I−Z₀Y)(I+Z₀Y)⁻¹D（D=diag(√z₀)，均匀 z0 退化为
    教科书式 (I−Z₀Y)(I+Z₀Y)⁻¹）。行/列均衡化用于对抗 skrf 综合网表的宽动态
    范围（实测 Rp ~ 1e-23 Ω、跨导 ~ 1e21）；直接求解奇异时按 ngspice gmin
    惯例（每节点对地 1e-12 S）重试一次，用于解锁浮动公共模网表。
    """
    n_port = len(port_nodes)
    node_idx_base, branch_elements, _ = _mna_replay_indices(elements)
    _assert_replay_solvable(elements, branch_elements)
    node_names = set(node_idx_base)
    node_names.update(port_nodes)
    node_names.update(r for r in ref_nodes if r is not None)
    node_idx = {name: i for i, name in enumerate(sorted(node_names))}
    branch_index = {el.name: len(node_idx) + k for k, el in enumerate(branch_elements)}
    n_nodes = len(node_idx)

    n_freq = int(freq.size)
    s_out = np.zeros((n_freq, n_port, n_port), dtype=complex)
    ident = np.eye(n_port)
    z0_arr = np.asarray(z0_list, dtype=float)
    d_root = np.sqrt(z0_arr)
    z0d = np.diag(z0_arr)

    for fi in range(n_freq):
        f_hz = float(freq[fi])
        w = 2.0 * np.pi * f_hz

        a_mat, rhs = _mna_build_frequency_system(elements, node_idx, branch_index, w, n_port, n_extra_rows=n_port)

        # 激励支路：端口 j 施加单位电压（参考 = 全局地或参考针）
        for j in range(n_port):
            k = n_nodes + len(branch_elements) + j
            kp = node_idx[port_nodes[j]]
            a_mat[kp, k] += 1.0
            a_mat[k, kp] = 1.0
            ref = ref_nodes[j]
            if ref is not None:
                rb = node_idx[ref]
                a_mat[rb, k] -= 1.0
                a_mat[k, rb] = -1.0
            rhs[k, j] = 1.0

        sol = _solve_mna_validated(a_mat, rhs, f_hz, n_nodes)

        # 端口电流 = 该端口节点上全部网表元件电流之和（不经激励源支路）
        vmat = sol[:n_nodes, :]
        i_into = np.zeros((n_port, n_port), dtype=complex)
        port_pos = {name: i for i, name in enumerate(port_nodes)}
        for el in elements:
            nd = el.nodes
            if el.kind in _REPLAY_BRANCH_KINDS:
                currents = sol[branch_index[el.name]]
            elif el.kind == "R":
                currents = (_node_volts(vmat, node_idx, nd[0], n_port) - _node_volts(vmat, node_idx, nd[1], n_port)) / el.value
            elif el.kind == "C":
                currents = (
                    1j
                    * w
                    * el.value
                    * (_node_volts(vmat, node_idx, nd[0], n_port) - _node_volts(vmat, node_idx, nd[1], n_port))
                )
            elif el.kind == "L":
                currents = (_node_volts(vmat, node_idx, nd[0], n_port) - _node_volts(vmat, node_idx, nd[1], n_port)) / (
                    1j * w * el.value
                )
            elif el.kind == "G":
                currents = el.value * (
                    _node_volts(vmat, node_idx, nd[2], n_port) - _node_volts(vmat, node_idx, nd[3], n_port)
                )
            elif el.kind == "F":
                currents = el.value * sol[branch_index[el.control]]
            else:  # 独立电流源（值必为 0，已校验）
                currents = np.full(n_port, el.value, dtype=complex)
            pa = port_pos.get(nd[0])
            if pa is not None:
                i_into[pa] += currents
            pb = port_pos.get(nd[1]) if len(nd) > 1 else None
            if pb is not None:
                i_into[pb] -= currents

        y_mat = i_into  # y[i, j] = 端口 i 流入电流 / 端口 j 单位激励（i_into 已按 [pin, 激励列] 排布）
        try:
            x_mat = np.linalg.solve((ident + z0d @ y_mat).T, (ident - z0d @ y_mat).T).T
        except np.linalg.LinAlgError as exc:
            raise MacromodelError(f"回放 Y→S 转换在 f={f_hz:.6g} Hz 奇异（I+Z0Y 不可逆）: {exc}") from exc
        s_out[fi] = x_mat * (d_root[None, :] / d_root[:, None])
    return s_out


def replay_spice_subcircuit_s(
    path: str | Path,
    freq_hz: Any,
    z0: Any = None,
    *,
    n_ports: int | None = None,
) -> dict[str, Any]:
    """对导出的 SPICE 子电路做频域 AC 回放（纯 Python 复数 MNA；**回放自检**）。

    不依赖 ngspice.exe：按标准 SPICE 元素语义（R/L/C/V/I/G/E/F/H）装配复数
    MNA 方程组，在每个频点对各端口做单位电压激励求解，提取端口导纳 Y 并转换
    为参考阻抗 ``z0`` 下的 S 矩阵。这是**回放自检**：验证"导出网表在标准 SPICE
    元素语义下重现 S 参数"；**不是** ngspice/LTspice/Xyce 等第三方 SPICE 仿真器
    的等价验证（本机无该工具，见模块 docstring"诚实的边界"）。

    参数：
    ``path``    : .sp 子电路文件（skrf ``write_spice_subcircuit_s`` 导出格式，
                  也接受同语义的人工网表；不支持非零独立源/子电路嵌套）
    ``freq_hz`` : 回放频点（Hz，有限且 ≥0；含 0 且网表含 L 时报错）
    ``z0``      : 参考阻抗（欧姆）；缺省从网表端口参考电阻 R1..RN 推断
                  （skrf 导出必含），也可给标量或长度 N 序列
    ``n_ports`` : 可选，期望端口数（与网表端口数不符则报错）

    返回 dict：``subckt_name`` / ``port_nodes`` / ``ref_nodes`` / ``n_ports`` /
    ``n_elements`` / ``element_counts`` / ``freq_hz`` / ``z0_ohm`` / ``z0_source`` /
    ``s``（复数 ndarray，[nf, n, n]）/ ``solver`` / ``disclaimer``。
    """
    parsed = _parse_spice_netlist(path)
    _assert_replay_zero_sources(parsed["elements"])  # 零输入语义限定在 S 参数提取入口
    port_nodes, ref_nodes, n_detected = _replay_port_layout(parsed["pins"])
    if n_detected == 0:
        raise MacromodelInputError(f".SUBCKT 未声明任何端口节点: {parsed['pins']!r}")
    if n_ports is not None and int(n_ports) != n_detected:
        raise MacromodelInputError(f"回放端口数不符：网表 {n_detected}，期望 {int(n_ports)}")

    freq = np.asarray(freq_hz, dtype=float).ravel()
    if freq.size == 0:
        raise MacromodelInputError("回放频率轴为空")
    if not np.all(np.isfinite(freq)):
        raise MacromodelInputError("回放频率轴含 NaN/Inf")
    if np.any(freq < 0.0):
        raise MacromodelInputError("回放频率必须 ≥ 0 Hz")

    z0_list, z0_source = _resolve_replay_z0(z0, parsed["elements"], n_detected)
    s_matrix = _mna_ac_s(parsed["elements"], port_nodes, ref_nodes, freq, z0_list)
    if not np.all(np.isfinite(s_matrix.view(float))):
        raise MacromodelError("回放 S 参数含 NaN/Inf（求解数值发散）")

    counts: dict[str, int] = {}
    for el in parsed["elements"]:
        counts[el.kind] = counts.get(el.kind, 0) + 1
    return {
        "path": str(parsed["path"]),
        "subckt_name": parsed["subckt_name"],
        "port_nodes": port_nodes,
        "ref_nodes": ref_nodes,
        "n_ports": n_detected,
        "n_elements": len(parsed["elements"]),
        "element_counts": counts,
        "freq_hz": [float(x) for x in freq],
        "z0_ohm": z0_list,
        "z0_source": z0_source,
        "s": s_matrix,
        "solver": "rfauto-core pure-python complex MNA (AC)",
        "disclaimer": _REPLAY_DISCLAIMER,
    }


def replay_spice_ac_response(path: str | Path, freq_hz: Any) -> dict[str, Any]:
    """有源 SPICE 网表的频域 AC 回放（纯 Python 复数 MNA；**回放自检**）。

    与 ``replay_spice_subcircuit_s``（S 参数提取、要求零输入）相对：本入口
    **放行非零独立源 V/I**（MNA rhs 本就支持非零源，只需把零输入校验限定在
    S 参数提取入口），以网表自身源为激励求解并返回全部节点电压与电压源类
    支路电流。AC 语义口径：独立源元素数值解释为**复数激励幅值（相位 0）**；
    支路电流方向为标准 SPICE 约定（从 n+ 经源流向 n-，与 ngspice ``i(vx)``
    同号——2026-09-15 真机标定，见 adapters/spice_netlist.py）。

    参数：
    ``path``    : .sp 网表（单 .SUBCKT；支持 .PARAM 数字字面量 / 单层 .INCLUDE）
    ``freq_hz`` : 回放频点（Hz，有限且 ≥0；含 0 且网表含 L 时报错）

    返回 dict：``path`` / ``subckt_name`` / ``pins`` / ``n_nodes`` /
    ``n_branches`` / ``element_counts`` / ``freq_hz`` /
    ``node_voltages``（{节点名: 复数 ndarray[nf]}，地节点 '0' 不在列）/
    ``branch_currents``（{V/E/H 名: 复数 ndarray[nf]}）/
    ``ac_source_semantics`` / ``solver`` / ``disclaimer``。
    """
    parsed = _parse_spice_netlist(path)
    freq = np.asarray(freq_hz, dtype=float).ravel()
    if freq.size == 0:
        raise MacromodelInputError("回放频率轴为空")
    if not np.all(np.isfinite(freq)):
        raise MacromodelInputError("回放频率轴含 NaN/Inf")
    if np.any(freq < 0.0):
        raise MacromodelInputError("回放频率必须 ≥ 0 Hz")

    elements = parsed["elements"]
    node_idx, branch_elements, branch_index = _mna_replay_indices(elements)
    _assert_replay_solvable(elements, branch_elements)
    n_nodes = len(node_idx)

    v_full = np.zeros((n_nodes, int(freq.size)), dtype=complex)
    i_full = np.zeros((len(branch_elements), int(freq.size)), dtype=complex)
    for fi in range(int(freq.size)):
        f_hz = float(freq[fi])
        w = 2.0 * np.pi * f_hz
        a_mat, rhs = _mna_build_frequency_system(elements, node_idx, branch_index, w, 1)
        sol = _solve_mna_validated(a_mat, rhs, f_hz, n_nodes)
        v_full[:, fi] = sol[:n_nodes, 0]
        i_full[:, fi] = sol[n_nodes:, 0]

    if not np.all(np.isfinite(v_full.view(float))) or not np.all(np.isfinite(i_full.view(float))):
        raise MacromodelError("有源 AC 回放结果含 NaN/Inf（求解数值发散）")

    counts: dict[str, int] = {}
    for el in elements:
        counts[el.kind] = counts.get(el.kind, 0) + 1
    return {
        "path": str(parsed["path"]),
        "subckt_name": parsed["subckt_name"],
        "pins": parsed["pins"],
        "n_nodes": n_nodes,
        "n_branches": len(branch_elements),
        "element_counts": counts,
        "freq_hz": [float(x) for x in freq],
        "node_voltages": {name: v_full[idx] for name, idx in node_idx.items()},
        "branch_currents": {el.name: i_full[k] for k, el in enumerate(branch_elements)},
        "ac_source_semantics": (
            "独立源（V/I）元素数值在 AC 回放中解释为复数激励幅值（相位 0）；"
            "支路电流方向 = 标准 SPICE 约定（n+ 经源流向 n-，与 ngspice i(vx) 同号）"
        ),
        "solver": "rfauto-core pure-python complex MNA (AC, active sources)",
        "disclaimer": _REPLAY_DISCLAIMER,
    }


def _replay_error_metrics(s_ref: np.ndarray, s_test: np.ndarray) -> dict[str, float]:
    """逐元素复数误差摘要（rms 口径与 ``_fit_rms`` 一致：nf·n² 归一）。"""
    delta = np.abs(np.asarray(s_ref, dtype=complex) - np.asarray(s_test, dtype=complex))
    rms = float(np.sqrt(float(np.sum(delta**2)) / delta.size))
    return {
        "rms_abs": rms,
        "rms_db": float(20.0 * np.log10(max(rms, _DB_FLOOR))),
        "max_abs": float(np.max(delta)),
    }


def spice_subcircuit_port_info(path: str | Path, z0: Any = None) -> dict[str, Any]:
    """解析 .sp 子电路的端口布局与参考阻抗（与回放自检**同一口径**）。

    供 adapters 层第三方对拍通道（ngspice .AC）复用：端口正极/参考节点的
    判定规则（``p1..pN`` 或 ``p1 p1_ref ...``）与 z0 推断（显式或 R1..RN）
    完全同源，保证两条证据链对"端口"的定义一致。含 .PARAM/.INCLUDE 支持与
    指令白名单校验（非法网表显式报错）。
    """
    parsed = _parse_spice_netlist(path)
    port_nodes, ref_nodes, n_ports = _replay_port_layout(parsed["pins"])
    if n_ports == 0:
        raise MacromodelInputError(f".SUBCKT 未声明任何端口节点: {parsed['pins']!r}")
    z0_list, z0_source = _resolve_replay_z0(z0, parsed["elements"], n_ports)
    counts: dict[str, int] = {}
    for el in parsed["elements"]:
        counts[el.kind] = counts.get(el.kind, 0) + 1
    return {
        "path": str(parsed["path"]),
        "subckt_name": parsed["subckt_name"],
        "pins": list(parsed["pins"]),
        "port_nodes": port_nodes,
        "ref_nodes": ref_nodes,
        "n_ports": n_ports,
        "n_elements": len(parsed["elements"]),
        "element_counts": counts,
        "z0_ohm": z0_list,
        "z0_source": z0_source,
    }


def compare_s_matrices(freq_hz: Any, s_reference: Any, s_test: Any) -> dict[str, Any]:
    """S 矩阵对拍裁判：FSV 逐响应评级（同 ``fit_macromodel.fsv`` 口径）+ 误差摘要。

    ``s_reference``/``s_test``：复数 ndarray ``[nf, n, n]``；返回
    ``{"fsv": {...per_response/worst_gdm_grade/gdm_at_least_good...},
    "error": {rms_abs/rms_db/max_abs}, "n_ports", "n_points"}``（JSON 原生）。
    频点数 < ``MIN_FREQ_POINTS`` 时 FSV 内核显式报错（不做静默降级）。
    """
    freq = np.asarray(freq_hz, dtype=float).ravel()
    s_ref = np.asarray(s_reference, dtype=complex)
    s_tst = np.asarray(s_test, dtype=complex)
    if s_ref.ndim != 3 or s_ref.shape[1] != s_ref.shape[2]:
        raise MacromodelInputError(f"s_reference 需为 [nf, n, n]，得到 {s_ref.shape}")
    if s_tst.shape != s_ref.shape:
        raise MacromodelInputError(f"s_test 形状 {s_tst.shape} 与 s_reference {s_ref.shape} 不一致")
    if int(s_ref.shape[0]) != int(freq.size):
        raise MacromodelInputError(f"S 矩阵频率维 {s_ref.shape[0]} != 频点数 {freq.size}")
    n_ports = int(s_ref.shape[1])
    return {
        "fsv": _fsv_section(freq, s_ref, s_tst, n_ports),
        "error": _replay_error_metrics(s_ref, s_tst),
        "n_ports": n_ports,
        "n_points": int(freq.size),
    }


# --------------------------------------------------------------------------- #
# Touchstone 读取（便捷入口，供 demo / 调用方复用）
# --------------------------------------------------------------------------- #

def request_from_touchstone(path: str | Path) -> dict[str, Any]:
    """读 Touchstone -> ``fit_macromodel`` 的 request 片段（Hz，[re, im] 复数）。

    仅支持恒定（可逐端口不同）参考阻抗：VF 的 SPICE 综合内部也只用 z0[0]，
    频率相关 z0 会显式报错而不是静默取首点。
    """
    p = Path(path)
    if not p.is_file():
        raise MacromodelInputError(f"Touchstone 文件不存在: {p}")
    nw = skrf.Network(str(p))
    z0 = np.real(np.asarray(nw.z0))
    ref = z0[0]
    if z0.ndim != 2 or not np.allclose(z0, ref, rtol=1e-9, atol=1e-9):
        raise MacromodelInputError(f"参考阻抗随频率变化（{p}），本内核只支持恒定 z0")
    return {
        "freq_hz": [float(x) for x in np.asarray(nw.f, dtype=float)],
        "s": [
            [[[float(v.real), float(v.imag)] for v in row] for row in mat]
            for mat in np.asarray(nw.s, dtype=complex)
        ],
        "z0": [float(x) for x in np.asarray(ref, dtype=float)],
        "n_ports": int(nw.nports),
        "source_path": str(p),
        "name": str(nw.name),
    }


# --------------------------------------------------------------------------- #
# FSV 保真裁判
# --------------------------------------------------------------------------- #

def _fsv_section(freq: np.ndarray, s_orig: np.ndarray, s_model: np.ndarray, n_ports: int) -> dict[str, Any]:
    """逐响应 dB 幅度 FSV（fsv.py 内核）-> 最差 GDM 等级与判定。"""
    per_response: dict[str, Any] = {}
    worst_idx = 0
    worst_key: str | None = None
    first_key: str | None = None
    for i in range(n_ports):
        for j in range(n_ports):
            key = f"s{i + 1}{j + 1}"
            if first_key is None:
                first_key = key
            mag_a = 20.0 * np.log10(np.maximum(np.abs(s_orig[:, i, j]), _DB_FLOOR))
            mag_b = 20.0 * np.log10(np.maximum(np.abs(s_model[:, i, j]), _DB_FLOOR))
            r = fsv(freq, mag_a, freq, mag_b)
            idx = grade_index_of(float(r["gdm_mean"]))
            per_response[key] = {
                "adm_grade": r["adm_grade"],
                "fdm_grade": r["fdm_grade"],
                "gdm_grade": r["gdm_grade"],
                "adm_mean": float(r["adm_mean"]),
                "fdm_mean_abs": float(r["fdm_mean_abs"]),
                "gdm_mean": float(r["gdm_mean"]),
                "gdm_grade_level": int(r["gdm_grade_level"]),
                "gdm_spread": int(r["gdm_spread"]),
            }
            if idx > worst_idx:
                worst_idx, worst_key = idx, key
    return {
        "per_response": per_response,
        "worst_gdm_grade": GRADE_CODES[worst_idx],
        "worst_response": worst_key if worst_key is not None else first_key,
        "gdm_at_least_good": bool(worst_idx <= GRADE_INDEX_GOOD),
        "max_grade_index_for_good": GRADE_INDEX_GOOD,
        "n_responses": int(n_ports * n_ports),
    }


# --------------------------------------------------------------------------- #
# 主入口
# --------------------------------------------------------------------------- #

def _poles_residues(vf: VectorFitting, n_ports: int) -> dict[str, Any]:
    """极点/留数/常数项摘要（全量极点 + 全量留数，索引口径随文档）。"""
    poles = np.asarray(vf.poles, dtype=complex)
    residues = np.asarray(vf.residues, dtype=complex)
    const = np.asarray(vf.constant_coeff, dtype=complex).reshape(n_ports, n_ports)
    n_poles = int(poles.size)
    n_real = int(np.sum(poles.imag == 0.0))
    return {
        "poles_rad_s": [[float(z.real), float(z.imag)] for z in poles],
        "poles_summary": {
            "n_poles": n_poles,
            "n_real_poles": n_real,
            "n_complex_pairs": int((n_poles - n_real) // 2),
            "max_abs_pole_rad_s": float(np.max(np.abs(poles))) if n_poles else 0.0,
        },
        "residues": [[[float(z.real), float(z.imag)] for z in residues[idx]] for idx in range(residues.shape[0])],
        "residues_summary": {
            "shape": [int(residues.shape[0]), int(residues.shape[1])],
            "indexing": "residues[i*n_ports + j][k] = 第 (i+1,j+1) 响应第 k 个留数；极点/留数在 rad/s",
            "abs_max": float(np.max(np.abs(residues))) if residues.size else 0.0,
            "abs_mean": float(np.mean(np.abs(residues))) if residues.size else 0.0,
        },
        "constant_coeff": [[float(z.real), float(z.imag)] for z in const.reshape(-1)],
        "constant_coeff_shape": [n_ports, n_ports],
    }


def _jsonify(value: Any) -> Any:
    """递归把 numpy 标量/数组转成 JSON 原生类型（数值不改）。"""
    if isinstance(value, dict):
        return {str(k): _jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonify(v) for v in value]
    if isinstance(value, np.ndarray):
        return [_jsonify(v) for v in value.tolist()]
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


def fit_macromodel(request: dict[str, Any]) -> dict[str, Any]:
    """S 参数 -> 宏模型（JSON 进 / JSON 出，确定性）。

    流程：确定性定阶向量拟合 -> 拟合 RMS（dB）-> 带内无源性判定 ->
    （带内违规时）passivity_enforce -> 复测 -> SPICE 子电路导出 + 结构校验 ->
    SPICE 回放自检（纯 Python MNA，非第三方 SPICE 等价）->
    FSV 保真裁判（拟合响应 vs 原始响应）。

    返回 dict（JSON 原生类型）：
    ``n_ports`` / ``n_points`` / ``freq_hz`` / ``z0_ohm`` /
    ``order``（阶数请求、每次尝试的 RMS、实际极点数）/
    ``poles_rad_s`` / ``poles_summary`` / ``residues`` / ``residues_summary`` /
    ``constant_coeff`` /
    ``fit``（rms_abs/rms_db 拟合口径 + rms_abs_final/rms_db_final 无源化后）/
    ``passivity``（before/after 两套 + enforced/enforce_error）/
    ``spice``（None 或结构校验结果）/
    ``spice_replay``（None / 回放自检结果 / {"status": "error", ...}；仅导出
    SPICE 且未显式关闭（request["spice_replay"]=False）时执行：回放 vs 原始/
    模型的 rms_db 与 max_abs + 回放 S 矩阵；``consistent`` = 回放 vs 模型
    max|ΔS| ≤ ``replay_consistency_tol_abs``（缺省 1e-6））/
    ``fsv``（逐响应 ADM/FDM/GDM 等级 + worst_gdm_grade + gdm_at_least_good）/
    ``ok``（最终 RMS ≤ 阈值 且 带内无源 且 SPICE 结构有效 且 FSV ≥ Good
    且（若执行了回放自检）回放 vs 模型一致）。
    """
    freq, s_orig, z0, n_ports = _normalize_request(request)

    threshold_db = float(request.get("rms_threshold_db", DEFAULT_RMS_THRESHOLD_DB))
    enforce_passivity = bool(request.get("enforce_passivity", True))
    enforce_samples = int(request.get("enforce_samples", DEFAULT_ENFORCE_SAMPLES))
    n_dense = int(request.get("passivity_samples", _DENSE_PASSIVITY_SAMPLES))
    subckt_name = str(request.get("subckt_name", "s_equivalent"))
    spice_path = request.get("spice_path")

    explicit = request.get("n_poles_real") is not None or request.get("n_poles_cmplx") is not None
    if explicit:
        if request.get("n_poles_real") is None or request.get("n_poles_cmplx") is None:
            raise MacromodelInputError("显式定阶需同时给出 'n_poles_real' 与 'n_poles_cmplx'")
        orders = [(int(request["n_poles_real"]), int(request["n_poles_cmplx"]))]
    else:
        ladder = request.get("order_ladder", DEFAULT_ORDER_LADDER)
        orders = [(int(a), int(b)) for a, b in ladder]
        if not orders:
            raise MacromodelInputError("order_ladder 不能为空")
    require_rms = request.get("require_rms")
    require_rms = explicit if require_rms is None else bool(require_rms)

    network = skrf.Network(frequency=freq, s=s_orig, z0=z0)
    attempts: list[dict[str, Any]] = []
    best: tuple[float, float, int, int, VectorFitting] | None = None
    for n_real, n_cmplx in orders:
        vf = VectorFitting(network)
        try:
            vf.vector_fit(n_poles_real=n_real, n_poles_cmplx=n_cmplx)
        except Exception as exc:  # skrf 内部可抛 LinAlgError/ValueError，如实归类
            attempts.append({
                "n_poles_real": n_real,
                "n_poles_cmplx": n_cmplx,
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue
        rms, rms_db = _fit_rms(vf, freq, s_orig, n_ports)
        attempts.append({
            "n_poles_real": n_real,
            "n_poles_cmplx": n_cmplx,
            "n_poles_total": int(np.size(vf.poles)),
            "rms_abs": rms,
            "rms_db": rms_db,
            "passed": bool(rms_db <= threshold_db),
        })
        if best is None or rms < best[0]:
            best = (rms, rms_db, n_real, n_cmplx, vf)
        if rms_db <= threshold_db:
            break

    if best is None:
        detail = "; ".join(
            f"({a['n_poles_real']},{a['n_poles_cmplx']}): {a.get('error')}" for a in attempts
        )
        raise MacromodelFitError(f"所有阶数的向量拟合均失败：{detail}")

    fit_rms, fit_rms_db, n_real, n_cmplx, vf = best
    if require_rms and fit_rms_db > threshold_db:
        raise MacromodelFitError(
            f"极点不足：阶数 (n_poles_real={n_real}, n_poles_cmplx={n_cmplx}) 的拟合 "
            f"RMS={fit_rms_db:.1f} dB 未达阈值 {threshold_db:.1f} dB；"
            f"请提高阶数，或省略 n_poles_real/n_poles_cmplx 走自动升阶阶梯。"
        )

    before = _passivity_state(vf, freq, n_ports, n_dense)
    enforced = False
    enforce_error: str | None = None
    if enforce_passivity and not before["passive_in_band"]:
        try:
            vf.passivity_enforce(n_samples=enforce_samples, f_max=float(freq[-1]))
            enforced = True
        except Exception as exc:  # skrf 无源化内部可抛，如实上报不掩盖
            enforce_error = f"{type(exc).__name__}: {exc}"
        after = _passivity_state(vf, freq, n_ports, n_dense)
    else:
        after = before

    rms_final, rms_final_db = _fit_rms(vf, freq, s_orig, n_ports)

    spice_info: dict[str, Any] | None = None
    if spice_path:
        sp = Path(str(spice_path))
        sp.parent.mkdir(parents=True, exist_ok=True)
        vf.write_spice_subcircuit_s(str(sp), fitted_model_name=subckt_name)
        spice_info = validate_spice_subcircuit(sp, expected_ports=n_ports, expected_name=subckt_name)

    s_model = model_response(vf, freq, n_ports)
    fsv_info = _fsv_section(freq, s_orig, s_model, n_ports)

    # SPICE 回放自检：导出网表 -> 纯 Python MNA AC 回放 -> 与原始/模型 S 参数对照。
    # 这是"回放自检"而非第三方 SPICE 等价验证（第三方 ngspice .AC 对拍在
    # adapters.spice_netlist.xval_macromodel_spice，与主链解耦，见模块 docstring）；
    # 求解失败如实记 status=error 并使 ok=False（验证面不可用即不得宣称交付链可信）。
    spice_replay: dict[str, Any] | None = None
    if spice_path and bool(request.get("spice_replay", True)):
        z0_net = np.real(np.asarray(network.z0, dtype=complex))
        z0_first = z0_net[0]
        if z0_first.ndim > 1:  # 防御：skrf 网络对象保留了矩阵形 z0
            z0_first = np.diag(z0_first)
        try:
            replay = replay_spice_subcircuit_s(sp, freq, z0=z0_first, n_ports=n_ports)
            s_replay: np.ndarray = replay["s"]
            replay_tol = float(request.get("replay_consistency_tol_abs", DEFAULT_REPLAY_CONSISTENCY_TOL))
            vs_original = _replay_error_metrics(s_orig, s_replay)
            vs_model = _replay_error_metrics(s_model, s_replay)
            spice_replay = {
                "status": "ok",
                "verifier": "replay_selfcheck",
                "solver": replay["solver"],
                "disclaimer": replay["disclaimer"],
                "subckt_name": replay["subckt_name"],
                "port_nodes": replay["port_nodes"],
                "n_elements": replay["n_elements"],
                "element_counts": replay["element_counts"],
                "freq_points": int(freq.size),
                "z0_ohm": replay["z0_ohm"],
                "z0_source": replay["z0_source"],
                "replay_vs_original": vs_original,
                "replay_vs_model": vs_model,
                "consistency_tol_abs": replay_tol,
                "consistent": bool(vs_model["max_abs"] <= replay_tol),
                "s": [
                    [[[float(v.real), float(v.imag)] for v in row] for row in mat] for mat in s_replay
                ],
            }
        except Exception as exc:  # 回放自检失败不阻塞主结果，但如实记录并判 ok=False
            spice_replay = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}

    z0_out: Any = float(z0) if np.ndim(z0) == 0 else np.asarray(z0, dtype=float).tolist()
    ok = bool(
        rms_final_db <= threshold_db
        and after["passive_in_band"]
        and (spice_info is None or spice_info["valid"])
        and fsv_info["gdm_at_least_good"]
        and (spice_replay is None or bool(spice_replay.get("consistent")))
    )

    result: dict[str, Any] = {
        "n_ports": n_ports,
        "n_points": int(freq.size),
        "freq_hz": [float(x) for x in freq],
        "z0_ohm": z0_out,
        "source": {
            "source_path": request.get("source_path"),
            "name": request.get("name"),
        },
        "order": {
            "explicit": bool(explicit),
            "require_rms": bool(require_rms),
            "used": {"n_poles_real": int(n_real), "n_poles_cmplx": int(n_cmplx)},
            "n_poles_total": int(np.size(vf.poles)),
            "attempts": attempts,
        },
        "fit": {
            "rms_abs": fit_rms,
            "rms_db": fit_rms_db,
            "skrf_get_rms_error": float(vf.get_rms_error()),
            "rms_abs_final": rms_final,
            "rms_db_final": rms_final_db,
            "threshold_db": threshold_db,
            "passed": bool(fit_rms_db <= threshold_db),
            "passed_final": bool(rms_final_db <= threshold_db),
        },
        "passivity": {
            "before": before,
            "after": after,
            "enforced": bool(enforced),
            "enforce_error": enforce_error,
            "enforce_samples": int(enforce_samples),
            "criterion": (
                "passive_in_band = 数据频带内密集采样模型 S 矩阵的最大奇异值 <= 1 + 1e-6；"
                "全轴 skrf 半尺寸测试结果另存 skrf_* 字段"
            ),
        },
        "spice": spice_info,
        "spice_replay": spice_replay,
        "fsv": fsv_info,
        "ok": ok,
    }
    result.update(_poles_residues(vf, n_ports))
    return _jsonify(result)
