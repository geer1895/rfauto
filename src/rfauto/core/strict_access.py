"""严格结果访问器层（VB-3，aurora_r R-12，2026-11-10）——读边界响亮失败。

思想级吸收（Q-X40 提案表 VB-3，runs/aurora_q/qx40_vbridge/PROPOSALS.md）：
对照 virtuoso-bridge-lite ``spectre/psf.py`` 的 result_file/scalar/vector/
frequency_hz 四访问器机制，按 rfauto 错误体系独立重写（无署名义务）。把
#248（skrf 扩展名推断）、#287/#294（dB 往返频率 ulp 噪声）、#314（部分
矩阵掩码）族教训下沉为**读取边界**的确定性守卫：读到的东西要么"就是那份
数据且数值合法"，要么带文件名+违例规则名响亮失败——绝不静默修复、绝不
回退别名。

与 G11 健康门的分工（不互相替代）：
- 本层（读边界）：管"读到的是不是那份数据、数值是否合法"——唯一结果
  文件、实数有限非空向量、严格递增频轴（ULP 级近重复显式报出）、精确
  端口/键名。数据一进门就验，违例=ValueError 子类家族。
- ``core/solve_health``（G11，读入后）：管"物理上是否可信"——无源性/
  互易性（#314 掩码口径不变）/功率守恒/热合理性。访问器不判物理，
  健康门不验读取合法性。
- 铁律 7：本模块零 LLM 零网络，全部判据为确定性数值规则。

访问器清单（全部纯函数，唯一例外 :func:`resolve_unique_result_file` 的
glob+resolve 即"路径解析"本身）：
- :func:`resolve_unique_result_file`——根目录下恰一个匹配文件；拒绝
  ``..``/绝对路径/解析越界/符号链接逃逸（规则 path_containment /
  symlink_escape / unique_file_match）。
- :func:`require_finite_vector` / :func:`require_finite_array`——实数、
  有限（NaN/Inf 逐一报出）、非空（规则 finite_nonempty_vector）。
- :func:`require_strictly_increasing`——实数严格递增频轴；倒退/重复频点
  报 strictly_increasing_freq，**严格递增但相邻差 ≤ ULP_NEAR_DUPLICATE_
  TOLERANCE 倍 ulp 的"ULP 级近重复"单独报出**（规则 ulp_near_duplicate_
  freq，#287/#294 族指纹：疑经有损 dB/单位往返，非真扫描点）。
- :func:`require_exact_port` / :func:`require_exact_key`——精确端口序号/
  键名匹配，不做类型强转、不猜别名、不做大小写/模糊回退（规则 exact_key）。
- :func:`validate_network_strict`——skrf.Network 组合校验缝（频轴+S 矩阵+
  z0 全有限、频轴严格递增），供 ``adapters/interchange.read_touchstone``
  的 ``strict=True`` 选通调用。

挂账（无 CLI/MCP 叶）：本层为纯内核函数，无 CLI 命令、无 MCP 工具叶；
后续席位若暴露消费者入口须按仓规带 ``--json``。

本模块不设 ``__all__``（无 __all__ 的非门面文件不进
tests/gold/public_api.json——touchstone_parser/stdf_parser 同款先例，
新模块零金快照漂移；公开面以本 docstring 访问器清单申报）。
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import numpy as np

#: ULP 级近重复判定容差（倍 ulp 数）：相邻差 >0 且 ≤ 该倍数即判"近重复"。
#: 取 8 的依据：#287 实测 dB 写出/读回频率噪声 ~1e-7 Hz，在 GHz 量级为
#: 亚 ulp～1 ulp；真扫描点间隔 ≥ kHz 量级（>1e6 ulp），中间留 3 个量级
#: 安全带。属调度性判定常数，非物理数值（铁律 7 不适用面）。
ULP_NEAR_DUPLICATE_TOLERANCE = 8

#: 唯一文件解析错误消息里最多列出的候选文件数（防巨目录刷屏）。
_MAX_CANDIDATES_SHOWN = 8


# ── 类型化错误家族（ValueError 子类；消息恒含文件名 + 违例规则名） ───────────


class StrictAccessError(ValueError):
    """严格结果访问器违例基类（ValueError 子类家族根）。

    str(exc) 恒为 ``"[<规则名>] <文件名>: <细节>"`` 形态；``.rule`` 与
    ``.source`` 属性供程序化分流。
    """

    rule = "strict_access"

    def __init__(self, source: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        self.source = str(source)
        self.details: dict[str, Any] = dict(details or {})
        super().__init__(f"[{self.rule}] {self.source}: {message}")


class StrictPathRejectedError(StrictAccessError):
    """路径形态违例（规则 path_containment）：``..`` 段/绝对路径/解析越界。"""

    rule = "path_containment"


class StrictSymlinkEscapeError(StrictAccessError):
    """符号链接逃逸（规则 symlink_escape）：匹配项 realpath 落在根之外。"""

    rule = "symlink_escape"


class StrictUniqueFileError(StrictAccessError):
    """唯一结果文件违例（规则 unique_file_match）：0 个或 ≥2 个匹配。"""

    rule = "unique_file_match"


class StrictFiniteVectorError(StrictAccessError):
    """有限非空向量违例（规则 finite_nonempty_vector）：空/非实数/NaN/Inf。"""

    rule = "finite_nonempty_vector"


class StrictMonotonicFreqError(StrictAccessError):
    """严格递增违例（规则 strictly_increasing_freq）：倒退或重复频点。"""

    rule = "strictly_increasing_freq"


class StrictUlpNearDuplicateError(StrictAccessError):
    """ULP 级近重复（规则 ulp_near_duplicate_freq）——#287/#294 族显式报出。

    频轴严格递增、但相邻差落在 ULP_NEAR_DUPLICATE_TOLERANCE 倍 ulp 内：
    数值上"几乎同一频点"，典型成因是有损格式（dB/截短有效位）往返的
    舍入噪声。不静默放行也不并入普通非单调，单独成规则供调用方分流。
    """

    rule = "ulp_near_duplicate_freq"


class StrictExactKeyError(StrictAccessError):
    """精确端口/键名违例（规则 exact_key）：不存在即报错，不回退别名。"""

    rule = "exact_key"


# ── 唯一结果文件解析（模块内唯一触文件系统者） ───────────────────────────────


def resolve_unique_result_file(root: str | Path, pattern: str) -> Path:
    """解析"根目录下恰一个匹配"的结果文件（VB-3 读取边界第一访问器）。

    Parameters
    ----------
    root : str | Path
        结果根目录（必须存在且为目录）。
    pattern : str
        相对 glob 模式（如 ``"results/*.s2p"``）；拒绝 ``..`` 段、绝对
        路径、盘符/根前导（规则 path_containment）。

    Returns
    -------
    Path
        唯一匹配的文件路径。

    Raises
    ------
    StrictPathRejectedError
        pattern 含 ``..`` 段、为绝对路径或带盘符/根前导。
    StrictSymlinkEscapeError
        匹配项 realpath 解析后落在 root 之外（符号链接逃逸/越界）。
    StrictUniqueFileError
        root 不存在/非目录、无文件型匹配（目录匹配不计）或匹配数 ≥2。
    """
    root_path = Path(root)
    source_label = f"{root_path} / {pattern}"
    _reject_unsafe_pattern(pattern, source_label)

    if not root_path.is_dir():
        raise StrictUniqueFileError(
            source_label,
            f"结果根目录不存在或不是目录: {root_path}",
            details={"root": str(root_path), "pattern": pattern},
        )

    matches = [p for p in sorted(root_path.glob(pattern)) if p.is_file()]
    root_resolved = root_path.resolve()
    for match in matches:
        match_resolved = match.resolve()
        if not match_resolved.is_relative_to(root_resolved):
            raise StrictSymlinkEscapeError(
                source_label,
                f"匹配项解析后越出根目录（符号链接逃逸）: {match} -> {match_resolved}",
                details={"match": str(match), "resolved": str(match_resolved)},
            )

    if not matches:
        raise StrictUniqueFileError(
            source_label,
            "根目录下未找到匹配的结果文件（恰需一个）",
            details={"root": str(root_path), "pattern": pattern, "n_matches": 0},
        )
    if len(matches) > 1:
        shown = [p.name for p in matches[:_MAX_CANDIDATES_SHOWN]]
        raise StrictUniqueFileError(
            source_label,
            f"根目录下匹配到 {len(matches)} 个结果文件（恰需一个）: {shown}",
            details={"root": str(root_path), "pattern": pattern,
                     "n_matches": len(matches), "candidates": shown},
        )
    return matches[0]


def _reject_unsafe_pattern(pattern: str, source_label: str) -> None:
    """pattern 形态守卫：``..``/绝对路径/盘符/根前导一律拒（path_containment）。"""
    text = str(pattern)
    if not text.strip():
        raise StrictPathRejectedError(source_label, "glob 模式为空")
    candidate = Path(text)
    if candidate.is_absolute() or candidate.drive or text.startswith(("/", "\\")):
        raise StrictPathRejectedError(
            source_label, f"glob 模式必须是相对路径（拒绝绝对路径/盘符/根前导）: {pattern!r}")
    if ".." in candidate.parts:
        raise StrictPathRejectedError(
            source_label, f"glob 模式含 '..' 段（拒绝目录穿越）: {pattern!r}")


# ── 实数有限非空向量 / 严格递增频轴 ─────────────────────────────────────────


def require_finite_vector(values: Any, *, source: str, name: str) -> np.ndarray:
    """实数、有限、非空的一维向量访问器（规则 finite_nonempty_vector）。

    实数口径：频轴/标量序列类向量必须为实数——复数与非数值输入一律拒绝
    （不做虚部丢弃、不做实部截取）。复数量（S 矩阵/z0）走
    :func:`require_finite_array`（验有限性，不验实数性）。

    Parameters
    ----------
    values : array_like
        待验序列。
    source : str
        数据来源标签（文件名），进错误消息。
    name : str
        向量名（如 "frequency_hz"），进错误消息。

    Returns
    -------
    np.ndarray
        float64 一维数组（不修复任何值）。
    """
    return _require_finite_array(values, source=source, name=name, ndim=1, allow_complex=False)


def require_finite_array(values: Any, *, source: str, name: str) -> np.ndarray:
    """有限、非空的 N 维数组访问器（规则 finite_nonempty_vector）。

    与 :func:`require_finite_vector` 同规则但**允许复数**（S 矩阵/z0 本是
    complex 量，验 NaN/Inf 有限性，不验实数性），维度不限于 1。
    """
    return _require_finite_array(values, source=source, name=name, ndim=None, allow_complex=True)


def _require_finite_array(
    values: Any,
    *,
    source: str,
    name: str,
    ndim: int | None,
    allow_complex: bool,
) -> np.ndarray:
    """有限非空访问器共同实现（NaN/Inf 分别计数，首个坏元素带索引报出）。"""
    label = f"{name}"
    try:
        arr = np.asarray(values)
        if np.iscomplexobj(arr):
            if not allow_complex:
                raise StrictFiniteVectorError(
                    source, f"{label} 必须是实数（收到复数 dtype={arr.dtype}，不做虚部丢弃）",
                    details={"name": name, "dtype": str(arr.dtype)})
        else:
            arr = arr.astype(np.float64)
    except StrictAccessError:
        raise
    except (TypeError, ValueError) as exc:
        raise StrictFiniteVectorError(
            source, f"{label} 无法解析为实数数组: {exc}", details={"name": name}) from None
    if ndim is not None and arr.ndim != ndim:
        raise StrictFiniteVectorError(
            source, f"{label} 必须是一维向量（收到 ndim={arr.ndim}）",
            details={"name": name, "ndim": arr.ndim})
    if arr.size == 0:
        raise StrictFiniteVectorError(
            source, f"{label} 为空向量（拒绝空数据）", details={"name": name, "size": 0})
    nan_mask = np.isnan(arr)
    inf_mask = np.isinf(arr)
    if nan_mask.any() or inf_mask.any():
        n_nan = int(nan_mask.sum())
        n_inf = int(inf_mask.sum())
        first_flat = int(np.flatnonzero(~np.isfinite(arr))[0])
        first_index = tuple(int(i) for i in np.unravel_index(first_flat, arr.shape))
        raise StrictFiniteVectorError(
            source,
            f"{label} 含非有限值: NaN×{n_nan} + Inf×{n_inf}，首个坏元素索引 {list(first_index)}",
            details={"name": name, "n_nan": n_nan, "n_inf": n_inf,
                     "first_bad_index": list(first_index)},
        )
    return arr


def _advance_ulp(value: float, steps: int) -> float:
    """把浮点值沿 +inf 方向精确推进 steps 个 ulp（math.nextafter 逐步，无舍入歧义）。"""
    out = float(value)
    for _ in range(int(steps)):
        out = math.nextafter(out, math.inf)
    return out


def require_strictly_increasing(
    values: Any,
    *,
    source: str,
    name: str = "frequency_hz",
) -> np.ndarray:
    """实数严格递增频轴访问器（VB-3 核心；ULP 级近重复显式报出）。

    判定（按最左违例间隙一次分类）：
    - 有限非空前置校验（:func:`require_finite_vector`，规则先报）；
    - 相邻差 <0（倒退）或 ==0（重复频点）→ StrictMonotonicFreqError；
    - 相邻差 >0 且 ≤ ``ULP_NEAR_DUPLICATE_TOLERANCE`` 倍 ulp（按两点中
      绝对值较大者的 ulp 计）→ StrictUlpNearDuplicateError（#287/#294 族
      指纹，疑经有损 dB/单位往返）；
    - 单点轴（len==1）平凡满足严格递增，直接放行。

    Returns
    -------
    np.ndarray
        校验通过的 float64 一维数组。
    """
    arr = require_finite_vector(values, source=source, name=name)
    if arr.size < 2:
        return arr
    diffs = np.diff(arr)
    for idx in range(diffs.size):
        gap = float(diffs[idx])
        lo = float(arr[idx])
        hi = float(arr[idx + 1])
        if gap <= 0.0:
            kind = "重复频点（差恰为 0）" if gap == 0.0 else "倒退（差为负）"
            raise StrictMonotonicFreqError(
                source,
                f"{name} 非严格递增@索引 {idx}: f[{idx}]={lo!r} -> f[{idx + 1}]={hi!r}，{kind}",
                details={"name": name, "index": idx, "f_lo": lo, "f_hi": hi},
            )
        ulp_ref = math.ulp(max(abs(lo), abs(hi)))
        if gap <= ULP_NEAR_DUPLICATE_TOLERANCE * ulp_ref:
            raise StrictUlpNearDuplicateError(
                source,
                f"{name} 严格递增但索引 {idx} 相邻差 {gap!r} Hz ≤ "
                f"{ULP_NEAR_DUPLICATE_TOLERANCE}×ulp({max(abs(lo), abs(hi))!r})="
                f"{ULP_NEAR_DUPLICATE_TOLERANCE * ulp_ref!r} Hz（ULP 级近重复，"
                "#287/#294 族：疑经有损 dB/单位往返，非真扫描点）",
                details={"name": name, "index": idx, "gap_hz": gap,
                         "ulp_tolerance_hz": ULP_NEAR_DUPLICATE_TOLERANCE * ulp_ref},
            )
    return arr


# ── 精确端口/键名（不猜别名） ───────────────────────────────────────────────


def require_exact_port(port: Any, n_ports: int, *, source: str) -> int:
    """精确端口序号访问器（规则 exact_key）——不做类型强转、不猜别名。

    只接受 ``0 <= port < n_ports`` 的真整数；字符串 ``"1"``、浮点 ``1.0``、
    布尔 ``True`` 一律拒绝（端口标识是离散名，不是可解析值）。

    Returns
    -------
    int
        校验通过的端口序号。
    """
    label = f"port[{port!r}]"
    if isinstance(port, bool) or not isinstance(port, (int, np.integer)):
        raise StrictExactKeyError(
            source,
            f"{label} 必须是整数端口序号（收到 {type(port).__name__}；"
            "不做字符串/浮点强转，不猜别名）",
            details={"kind": "port", "received_type": type(port).__name__},
        )
    port_int = int(port)
    n_ports_int = int(n_ports)
    if not 0 <= port_int < n_ports_int:
        raise StrictExactKeyError(
            source,
            f"{label} 超出有效范围 [0, {n_ports_int})",
            details={"kind": "port", "port": port_int, "n_ports": n_ports_int},
        )
    return port_int


def require_exact_key(
    key: Any,
    available: Iterable[str],
    *,
    source: str,
    kind: str = "键",
) -> str:
    """精确键名访问器（规则 exact_key）——精确匹配，不回退别名/大小写/模糊。

    Parameters
    ----------
    key : Any
        请求的键名；必须为 str 且与 available 中某项**逐字符相等**。
    available : Iterable[str]
        可用键名集合。
    kind : str, optional
        键种类描述（如 "端口名"/"列名"），进错误消息。

    Returns
    -------
    str
        校验通过的键名（原样返回）。
    """
    if not isinstance(key, str):
        raise StrictExactKeyError(
            source,
            f"{kind}名必须是字符串（收到 {type(key).__name__}；不做类型强转）",
            details={"kind": kind},
        )
    available_list = [str(item) for item in available]
    if key not in available_list:
        shown = sorted(available_list)[:_MAX_CANDIDATES_SHOWN]
        raise StrictExactKeyError(
            source,
            f"请求的{kind}名 {key!r} 不存在（精确匹配不回退别名）；可用{kind}名: {shown}",
            details={"kind": kind, "requested": key, "available": shown},
        )
    return key


# ── skrf.Network 组合校验缝（interchange strict 选通唯一消费点） ─────────────


def validate_network_strict(network: Any, *, source: str) -> None:
    """对已加载的 skrf.Network 做读取边界全套严格校验（VB-3 组合缝）。

    校验项（违例即抛对应类型化错误，消息含 source 文件名+规则名）：
    1. 频轴：实数有限非空 + 严格递增 + ULP 级近重复显式报出；
    2. S 矩阵：三维非空（n_freq≥1、n_ports≥1）且全有限（NaN/Inf 报出）；
    3. 参考阻抗 z0：全有限。

    与 G11 分工：本函数只验"读取合法性"，不判无源性/互易性等物理可信面
    （那归 ``core/solve_health``；#314 掩码口径在彼处不变）。

    Parameters
    ----------
    network : skrf.Network（duck-type：取 ``.f``/``.s``/``.z0``）
        已加载的网络对象。
    source : str
        文件名标签，进全部错误消息。
    """
    freq = require_strictly_increasing(
        np.asarray(network.f, dtype=float), source=source, name="frequency_hz")
    s = require_finite_array(network.s, source=source, name="s_matrix")
    if s.ndim != 3 or s.shape[0] != freq.size or s.shape[1] < 1 or s.shape[2] < 1:
        raise StrictFiniteVectorError(
            source,
            f"S 矩阵形状非法: {s.shape}（期望 (n_freq, n_ports, n_ports) 且 n_freq={freq.size}）",
            details={"name": "s_matrix", "shape": list(s.shape), "n_freq": int(freq.size)},
        )
    require_finite_array(network.z0, source=source, name="z0")
