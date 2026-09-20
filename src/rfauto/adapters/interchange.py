"""Touchstone 读写 + 契约校验（§8.2）。

两端软件之间的数据交换介质只有 Touchstone 文件。
interchange.py 在导入与导出两侧都做契约校验，确保端口顺序和参考阻抗一致。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

import numpy as np
import skrf
from skrf.io import Citi, Mdif
from skrf.networkSet import NetworkSet

from rfauto.core.contracts import TouchstoneContract
from rfauto.core.errors import ContractViolationError

logger = logging.getLogger(__name__)

#: 支持的 Touchstone 版本（skrf 2.1.0 另支持 "2.1"；G16 矩阵只验收 1.0/2.0）。
TOUCHSTONE_VERSIONS = ("1.0", "2.0")

#: G16 互操作矩阵覆盖的格式标识。
INTERCHANGE_FORMATS = ("touchstone1", "touchstone2", "mdif", "citi")


def read_touchstone(
    path: str | Path,
    contract: TouchstoneContract | None = None,
) -> skrf.Network:
    """读取 Touchstone 文件并可选进行契约校验。

    Parameters
    ----------
    path : str | Path
        .sNp 文件路径。
    contract : TouchstoneContract, optional
        交换契约，提供时进行端口数和参考阻抗校验。

    Returns
    -------
    skrf.Network
        读取的 S 参数网络。

    Raises
    ------
    FileNotFoundError
        文件不存在。
    ContractViolationError
        契约校验失败（端口数或参考阻抗不匹配）。
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Touchstone 文件不存在: {path}")

    # 读取 Touchstone 文件
    logger.info("读取 Touchstone 文件: %s", path)
    network = skrf.Network(str(path))

    # 契约校验
    if contract is not None:
        _validate_network_against_contract(network, contract, str(path))

    return network


def export_touchstone(
    network: skrf.Network,
    path: str | Path,
    contract: TouchstoneContract | None = None,
    *,
    version: str = "1.0",
    write_z0: bool = False,
) -> Path:
    """导出 Touchstone 文件并进行契约合规校验。

    Parameters
    ----------
    network : skrf.Network
        要导出的 S 参数网络。
    path : str | Path
        输出 .sNp 文件路径。
    contract : TouchstoneContract, optional
        交换契约，提供时进行端口数和参考阻抗校验。
    version : str, optional
        Touchstone 版本，"1.0"（默认）或 "2.0"。
    write_z0 : bool, optional
        是否写出显式参考阻抗块（透传 skrf write_touchstone 同名参数）。

    Returns
    -------
    Path
        导出文件的路径。

    Raises
    ------
    ValueError
        version 不在 TOUCHSTONE_VERSIONS 内。
    ContractViolationError
        契约校验失败。
    """
    path = Path(path)

    # 导出前校验
    if contract is not None:
        _validate_network_against_contract(network, contract, "export_source")

    # 确保输出目录存在
    path.parent.mkdir(parents=True, exist_ok=True)

    if version not in TOUCHSTONE_VERSIONS:
        raise ValueError(f"不支持的 Touchstone 版本: {version!r}；支持 {TOUCHSTONE_VERSIONS}")

    # 导出 Touchstone
    logger.info("导出 Touchstone 文件: %s (version=%s)", path, version)
    network.write_touchstone(str(path), version=version, write_z0=write_z0)

    # 导出后重新读取验证
    if contract is not None:
        try:
            verification_net = skrf.Network(str(path))
            _validate_network_against_contract(verification_net, contract, str(path))
        except Exception as exc:
            logger.warning("导出文件验证失败: %s", exc)
            raise

    return path


def _validate_network_against_contract(
    network: skrf.Network,
    contract: TouchstoneContract,
    source_label: str,
) -> None:
    """验证网络是否符合契约要求。

    Parameters
    ----------
    network : skrf.Network
        S 参数网络。
    contract : TouchstoneContract
        交换契约。
    source_label : str
        数据来源标签（用于错误消息）。

    Raises
    ------
    ContractViolationError
        端口数或参考阻抗不匹配。
    """
    # 校验端口数
    actual_ports = network.number_of_ports
    expected_ports = len(contract.port_order)
    if actual_ports != expected_ports:
        raise ContractViolationError(
            f"Touchstone 端口数不匹配（来源: {source_label}）：\n"
            f"  契约要求: {expected_ports} 端口 {contract.port_order}\n"
            f"  实际文件: {actual_ports} 端口",
            details={
                "expected_ports": expected_ports,
                "actual_ports": actual_ports,
                "port_order": contract.port_order,
                "source": source_label,
            },
        )

    # 校验参考阻抗
    expected_z0 = contract.renormalization_ohm
    # z0 可能是多维数组 (n_freqs, n_ports)，需要正确提取标量值
    try:
        if hasattr(network.z0, '__len__'):
            # 取第一个端口的参考阻抗（实部）
            actual_z0 = float(network.z0[0].real) if hasattr(network.z0[0], 'real') else float(network.z0[0])
        else:
            actual_z0 = float(network.z0.real) if hasattr(network.z0, 'real') else float(network.z0)
    except (TypeError, ValueError):
        # 如果转换失败，尝试直接取第一个元素
        actual_z0 = float(network.z0.flat[0].real) if hasattr(network.z0, 'flat') else float(network.z0)
    if abs(actual_z0 - expected_z0) > 0.01:
        raise ContractViolationError(
            f"参考阻抗不匹配（来源: {source_label}）：\n"
            f"  契约要求: {expected_z0} Ω\n"
            f"  实际文件: {actual_z0} Ω",
            details={
                "expected_z0": expected_z0,
                "actual_z0": actual_z0,
                "source": source_label,
            },
        )

    logger.debug(
        "契约校验通过（%s）: %d 端口, %.1f Ω",
        source_label, actual_ports, actual_z0,
    )


def validate_frequency_range(
    network: skrf.Network,
    freq_min_ghz: float,
    freq_max_ghz: float,
) -> bool:
    """验证网络频率范围是否覆盖要求的区间。

    Parameters
    ----------
    network : skrf.Network
        S 参数网络。
    freq_min_ghz : float
        要求的最低频率（GHz）。
    freq_max_ghz : float
        要求的最高频率（GHz）。

    Returns
    -------
    bool
        True 表示频率范围满足要求。
    """
    freqs_ghz = network.f / 1e9  # skrf 默认 Hz → GHz
    return float(freqs_ghz.min()) <= freq_min_ghz and float(freqs_ghz.max()) >= freq_max_ghz


# ---------------------------------------------------------------------------
# G16 EDA 数据格式互操作矩阵：Touchstone / MDIF / CITI 统一读写
# ---------------------------------------------------------------------------


def max_complex_delta(reference, actual) -> float:
    """返回两个复数 S 矩阵逐元素之差的绝对值上界。

    Parameters
    ----------
    reference, actual : array_like
        形状一致的复数数组（通常是 shape=(n_freqs, n_ports, n_ports) 的 S 矩阵）。

    Returns
    -------
    float
        max(abs(reference - actual))；空数组返回 0.0。

    Raises
    ------
    ValueError
        两个数组形状不一致。
    """
    ref = np.asarray(reference, dtype=complex)
    act = np.asarray(actual, dtype=complex)
    if ref.shape != act.shape:
        raise ValueError(f"S 矩阵形状不一致: {ref.shape} vs {act.shape}")
    if ref.size == 0:
        return 0.0
    return float(np.max(np.abs(ref - act)))


def read_mdif(path: str | Path) -> list[skrf.Network]:
    """读取 GMDIF（ADS/PathWave .mdf）文件。

    Parameters
    ----------
    path : str | Path
        .mdf 文件路径。

    Returns
    -------
    list[skrf.Network]
        每个参数块对应一个 Network；MDIF 变量值存放在 Network.params。

    Raises
    ------
    FileNotFoundError
        文件不存在。
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"MDIF 文件不存在: {path}")
    logger.info("读取 MDIF 文件: %s", path)
    return list(Mdif(str(path)).networks)


def export_mdif(networks, path: str | Path, comments=None) -> Path:
    """导出 GMDIF（ADS/PathWave .mdf）文件。

    用 skrf.io.Mdif.write 写出，并对 skrf 2.1.0 的已知缺陷做最小修复：
    端口数 >= 3 时 Mdif.write 生成的 %F 数据类型头会折行，而续行缺少 %
    前缀，导致 Mdif 自己都读不回（续行被当作数据行解析，报
    "could not convert string to float: 'n21x'"）。本函数给该头部区间内的
    续行补上 % 前缀（AWR 文档规定头部每行以 % 起始），使 N=1/2/3/4 端口
    均可无损往返。

    Parameters
    ----------
    networks : skrf.Network | skrf.NetworkSet | Sequence[skrf.Network]
        待导出的网络；多个网络写成多个 ACDATA 块。
    path : str | Path
        输出 .mdf 文件路径。
    comments : Sequence[str], optional
        写入文件头部的注释行。

    Returns
    -------
    Path
        导出文件路径。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    network_set = _as_network_set(networks)
    logger.info("导出 MDIF 文件: %s", path)
    Mdif.write(network_set, str(path), comments=list(comments or []))
    _repair_mdif_option_header(path)
    return path


def read_citi(path: str | Path) -> list[skrf.Network]:
    """读取 CITI（.cti）文件。

    Parameters
    ----------
    path : str | Path
        .cti 文件路径。

    Returns
    -------
    list[skrf.Network]
        CITI 文件中每组参数取值对应一个 Network。

    Raises
    ------
    FileNotFoundError
        文件不存在。
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"CITI 文件不存在: {path}")
    logger.info("读取 CITI 文件: %s", path)
    return list(Citi(str(path)).networks)


#: CITI 数据格式档：API 键 → CITI 文件内的格式 token。
#: skrf Citi 读取器（skrf/io/citi.py _parse_citi）只认 RI / MAGANGLE / DBANGLE 三种。
CITI_DATA_FORMATS = {"RI": "RI", "MA": "MAGANGLE", "DB": "DBANGLE"}


def export_citi(
    network: skrf.Network,
    path: str | Path,
    comments=None,
    *,
    data_format: str = "RI",
) -> Path:
    """导出单网络 CITI（.cti）文件。

    skrf 2.1.0 只提供 CITI 读取器（skrf.io.Citi），没有写出器；本函数按
    CITI A.01.01 规范写出 VAR FREQ + DATA S[i,j] 与 DATA PortZ[i] 数据块，
    保证频率轴、端口顺序、S 矩阵与参考阻抗都能被 Citi 读者无损读回。

    data_format 选择数据档（skrf Citi 读取器支持的全部三种）：``"RI"``
    （默认，实部/虚部，逐位无损）、``"MA"``（幅度/相位角 deg，文件档
    MAGANGLE）、``"DB"``（dB 幅度/相位角 deg，文件档 DBANGLE）。MA/DB 档
    读回经幅度/相位重构造，|ΔS| 在双精度舍入量级（≪1e-12）。

    注释以 "! " 行写出——skrf 的 Citi 解析器只识别 "#"/"!" 起始的注释行，
    CITI 规范里的 COMMENT 关键字不被 skrf 读取（该格按"丢失"如实声明）。

    Parameters
    ----------
    network : skrf.Network
        待导出的单个网络。
    path : str | Path
        输出 .cti 文件路径。
    comments : Sequence[str], optional
        注释行内容。
    data_format : str, optional
        数据档："RI"（默认）/ "MA" / "DB"，大小写不敏感。

    Returns
    -------
    Path
        导出文件路径。

    Raises
    ------
    TypeError
        传入的不是单个 skrf.Network。
    ValueError
        data_format 不在 CITI_DATA_FORMATS 内。
    """
    if not isinstance(network, skrf.Network):
        raise TypeError(f"CITI 导出仅支持单个 skrf.Network，收到: {type(network).__name__}")

    fmt_key = str(data_format).upper()
    if fmt_key not in CITI_DATA_FORMATS:
        raise ValueError(
            f"不支持的 CITI 数据格式档: {data_format!r}；支持 {sorted(CITI_DATA_FORMATS)}"
        )
    citi_token = CITI_DATA_FORMATS[fmt_key]

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    n_ports = network.nports
    freqs = np.asarray(network.frequency.f, dtype=float)
    s_params = np.asarray(network.s, dtype=complex)
    z0 = np.asarray(network.z0, dtype=complex)

    lines = ["CITIFILE A.01.01", f"NAME {network.name}"]
    lines += [f"! {comment}" for comment in (comments or [])]
    lines.append(f"VAR FREQ MAG {len(freqs)}")
    for i in range(n_ports):
        for j in range(n_ports):
            lines.append(f"DATA S[{i + 1},{j + 1}] {citi_token}")
    for i in range(n_ports):
        lines.append(f"DATA PortZ[{i + 1}] {citi_token}")

    lines.append("VAR_LIST_BEGIN")
    lines += [_format_lossless(freq) for freq in freqs]
    lines.append("VAR_LIST_END")

    for i in range(n_ports):
        for j in range(n_ports):
            lines.append(f"BEGIN S[{i + 1},{j + 1}] {citi_token}")
            lines += [
                "{},{}".format(*_citi_pair(s_params[k, i, j], fmt_key))
                for k in range(len(freqs))
            ]
            lines.append("END")

    for i in range(n_ports):
        lines.append(f"BEGIN PortZ[{i + 1}] {citi_token}")
        lines += [
            "{},{}".format(*_citi_pair(z0[k, i], fmt_key))
            for k in range(len(freqs))
        ]
        lines.append("END")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("导出 CITI 文件: %s (data_format=%s)", path, fmt_key)
    return path


def _citi_pair(value, fmt_key: str) -> tuple[float, float]:
    """把复数值转成 CITI 数据行的两列（按所选数据档）。"""
    value = complex(value)
    if fmt_key == "RI":
        return value.real, value.imag
    magnitude = abs(value)
    angle_deg = math.degrees(math.atan2(value.imag, value.real))
    if fmt_key == "MA":
        return magnitude, angle_deg
    # DB：20·log10(|S|) 是 S 参量幅度 dB 的标准口径；零幅度写 -inf（读回即 0）。
    db = 20.0 * math.log10(magnitude) if magnitude > 0.0 else float("-inf")
    return db, angle_deg


def export_interchange(
    network: skrf.Network,
    path: str | Path,
    fmt: str,
    *,
    comments=None,
) -> Path:
    """按格式标识导出互操作文件（G16 矩阵统一出口）。

    Parameters
    ----------
    network : skrf.Network
        待导出的网络。
    path : str | Path
        输出文件路径。
    fmt : str
        见 INTERCHANGE_FORMATS。
    comments : Sequence[str], optional
        注释（MDIF/CITI 使用）。

    Returns
    -------
    Path
        导出文件路径。

    Raises
    ------
    ValueError
        未知格式标识。
    """
    fmt = fmt.lower()
    if fmt == "touchstone1":
        return export_touchstone(network, path, version="1.0")
    if fmt == "touchstone2":
        return export_touchstone(network, path, version="2.0")
    if fmt == "mdif":
        return export_mdif(network, path, comments=comments)
    if fmt == "citi":
        return export_citi(network, path, comments=comments)
    raise ValueError(f"不支持的互操作格式: {fmt!r}；支持 {INTERCHANGE_FORMATS}")


def read_interchange(path: str | Path, fmt: str) -> list[skrf.Network]:
    """按格式标识读取互操作文件（G16 矩阵统一入口）。

    Parameters
    ----------
    path : str | Path
        输入文件路径。
    fmt : str
        见 INTERCHANGE_FORMATS。

    Returns
    -------
    list[skrf.Network]
        解析出的网络列表（Touchstone 恒为单元素）。

    Raises
    ------
    ValueError
        未知格式标识。
    FileNotFoundError
        文件不存在。
    """
    fmt = fmt.lower()
    if fmt in ("touchstone1", "touchstone2"):
        return [read_touchstone(path)]
    if fmt == "mdif":
        return read_mdif(path)
    if fmt == "citi":
        return read_citi(path)
    raise ValueError(f"不支持的互操作格式: {fmt!r}；支持 {INTERCHANGE_FORMATS}")


def _as_network_set(networks) -> NetworkSet:
    """把单个 Network / 序列 / NetworkSet 统一收敛为 NetworkSet。"""
    if isinstance(networks, NetworkSet):
        return networks
    if isinstance(networks, skrf.Network):
        return NetworkSet([networks])
    return NetworkSet(list(networks))


def _repair_mdif_option_header(path: Path) -> None:
    """给 skrf 生成的折行 %F 头补上续行 % 前缀（仅在头部区间内）。

    skrf 2.1.0 的 Mdif.write 在端口数 >= 3 时把 %F 数据类型头折行，但续行
    没有 % 前缀；Mdif 解析器把续行当数据行，直接抛 ValueError。此修复只在
    %F 起始行到 # 选项行之间生效，不触碰真实数据行。
    """
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    repaired: list[str] = []
    in_option_header = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("%F"):
            in_option_header = True
            repaired.append(line)
            continue
        if in_option_header:
            if stripped.startswith("#"):
                in_option_header = False
                repaired.append(line)
                continue
            if stripped and not stripped.startswith(("%", "!", "#")):
                repaired.append("% " + line)
                continue
        repaired.append(line)
    path.write_text("".join(repaired), encoding="utf-8")


def _format_lossless(value: float) -> str:
    """无损数值格式化：17 位有效数字保证 IEEE-754 double 精确往返（读回逐位相等）。"""
    return format(float(value), ".17g")


# ---------------------------------------------------------------------------
# Tabular MDIF（ADS 数据集变体）：BEGIN/END 块 + % 列头 + 逗号/空白分隔数值行
# ---------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class MdifTable:
    """Tabular MDIF 的单个数据块。

    ADS 数据目录导出的 .mdf（如仓库内 IMPORT_TO_ADS.mdf）不是 skrf 可解的
    GMDIF，而是简单表格变体：``BEGIN <块名>`` / ``%列头`` / 逗号或空白
    分隔的数值行 / ``END``。``data`` 形状 ``(n_rows, n_cols)``，列序与
    ``columns`` 一致；无单位的原始数值按 float64 保存。
    """

    name: str
    columns: tuple[str, ...]
    data: np.ndarray

    def column(self, name: str) -> np.ndarray:
        """按列名取一列。

        Raises
        ------
        ValueError
            列名不存在。
        """
        try:
            index = self.columns.index(name)
        except ValueError:
            raise ValueError(
                f"MDIF 表 {self.name!r} 不含列 {name!r}；现有列: {list(self.columns)}"
            ) from None
        return self.data[:, index]


def read_mdif_table(path: str | Path) -> list[MdifTable]:
    """读取 Tabular MDIF（ADS 数据集变体）文件的全部数据块。

    与 ``read_mdif``（skrf GMDIF 读取器）互补：GMDIF 解析不了的
    "BEGIN/END + % 列头 + 逗号分隔数值行" 简单表格变体由本函数解析。
    逐行单遍流式读取（文件对象迭代），不把整个文件载入内存后再切分。
    空行与 ``!`` 行跳过；``#`` 选项行不是该变体的语法，遇到即显式报错。

    Parameters
    ----------
    path : str | Path
        .mdf 文件路径。

    Returns
    -------
    list[MdifTable]
        按文件出现顺序解析出的全部数据块。

    Raises
    ------
    FileNotFoundError
        文件不存在。
    ValueError
        文件不含任何数据块，或块结构/列头/数值行非法（消息含文件与行号）。
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"MDIF 文件不存在: {path}")
    logger.info("读取 Tabular MDIF 文件: %s", path)
    tables: list[MdifTable] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as fid:
        _parse_tabular_mdif(fid, path, tables)
    return tables


def export_mdif_table(
    path: str | Path,
    name: str,
    columns,
    data,
    *,
    comments=None,
) -> Path:
    """导出 Tabular MDIF（ADS 数据集变体）单数据块文件。

    与 :func:`read_mdif_table` 互为逆操作：``BEGIN <name>`` + ``%列头`` +
    逗号分隔数值行 + ``END``。数值按 17 位有效数字写出，IEEE-754 double
    逐位无损往返（读回 max|Δ| == 0，远严于 1e-12 口径）。

    Parameters
    ----------
    path : str | Path
        输出 .mdf 文件路径。
    name : str
        数据块名（单个非空 token，不含空白）。
    columns : Sequence[str]
        列名序列（每个为单个非空 token），如 ``("Freq(1)", "dBS21(1)")``。
    data : array_like
        形状 ``(n_rows, len(columns))`` 的数值表；一维序列按单列处理。
    comments : Sequence[str], optional
        以 ``! `` 行写出的注释。

    Returns
    -------
    Path
        导出文件路径。

    Raises
    ------
    ValueError
        块名/列名含空白、列数为零或与数据列数不一致、数据非二维。
    """
    path = Path(path)
    block_name = str(name)
    if not block_name or any(ch.isspace() for ch in block_name):
        raise ValueError(f"MDIF 块名必须是单个非空 token: {name!r}")
    names = tuple(str(column) for column in columns)
    if not names:
        raise ValueError("MDIF 表至少需要一列")
    for column in names:
        if not column or any(ch.isspace() for ch in column):
            raise ValueError(f"MDIF 列名必须是单个非空 token: {column!r}")
    array = np.asarray(data, dtype=float)
    if array.ndim == 1:
        array = array.reshape(-1, 1)
    if array.ndim != 2:
        raise ValueError(f"MDIF 表数据必须是二维（收到 ndim={array.ndim}）")
    if array.shape[1] != len(names):
        raise ValueError(
            f"MDIF 列数不匹配: {len(names)} 个列名 vs 数据 {array.shape[1]} 列"
        )

    lines = [f"! {comment}" for comment in (comments or [])]
    lines.append(f"BEGIN {block_name}")
    lines.append(" ".join(["%" + names[0], *names[1:]]))
    lines += [",".join(_format_lossless(value) for value in row) for row in array]
    lines.append("END")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("导出 Tabular MDIF 文件: %s", path)
    return path


def db_to_linear_magnitude(db) -> np.ndarray:
    """dB 幅度 → 线性幅度（10^(dB/20)）的确定性内核转换。

    供 Tabular MDIF 里的 ``dBSxx`` 之类 dB 列消费为线性幅度。只做幅度
    换算，不含任何相位合成——dB-only 数据没有相位信息，重建复数 S 属于
    数据捏造，不在本层提供。
    """
    return np.power(10.0, np.asarray(db, dtype=float) / 20.0)


def _tabular_mdif_error(path: Path, lineno: int, message: str) -> ValueError:
    """带文件与行号的 Tabular MDIF 解析错误。"""
    return ValueError(f"Tabular MDIF 解析失败（{path}:{lineno}）: {message}")


def _parse_tabular_mdif(fid: TextIO, path: Path, tables: list[MdifTable]) -> None:
    """逐行单遍解析 Tabular MDIF 流，结果追加进 tables。"""
    block_name: str | None = None
    columns: tuple[str, ...] | None = None
    rows: list[list[float]] = []
    lineno = 0

    for lineno, raw in enumerate(fid, start=1):
        line = raw.strip()
        if not line or line.startswith("!"):
            continue
        upper = line.upper()
        if upper == "END":
            if block_name is None:
                raise _tabular_mdif_error(path, lineno, "块外出现孤立 END")
            if columns is None:
                raise _tabular_mdif_error(path, lineno, "数据块缺少 % 列头")
            data = np.asarray(rows, dtype=float).reshape(len(rows), len(columns))
            tables.append(MdifTable(name=block_name, columns=columns, data=data))
            block_name = None
            columns = None
            rows = []
            continue
        if upper.startswith("BEGIN"):
            if block_name is not None:
                raise _tabular_mdif_error(path, lineno, "BEGIN 嵌套（上一块未 END）")
            parts = line.split()
            if len(parts) != 2:
                raise _tabular_mdif_error(path, lineno, f"BEGIN 行需要恰好一个块名: {line!r}")
            block_name = parts[1]
            columns = None
            rows = []
            continue
        if upper.startswith("#"):
            raise _tabular_mdif_error(
                path, lineno, "tabular 变体不支持 # 选项行（那是 Touchstone/GMDIF 语法）"
            )
        if upper.startswith("%"):
            if block_name is None:
                raise _tabular_mdif_error(path, lineno, "% 列头出现在 BEGIN 之前")
            if columns is not None:
                raise _tabular_mdif_error(path, lineno, "重复的 % 列头")
            tokens = line.split()
            first = tokens[0][1:] if tokens[0].startswith("%") else tokens[0]
            names = (first, *tokens[1:])
            for column in names:
                if not column or any(ch.isspace() for ch in column):
                    raise _tabular_mdif_error(path, lineno, f"非法列名: {column!r}")
            columns = names
            rows = []
            continue
        if block_name is None:
            raise _tabular_mdif_error(path, lineno, f"块外出现无法识别的行: {line!r}")
        if columns is None:
            raise _tabular_mdif_error(path, lineno, f"数据行出现在 % 列头之前: {line!r}")
        tokens = line.replace(",", " ").split()
        if len(tokens) != len(columns):
            raise _tabular_mdif_error(
                path,
                lineno,
                f"列数不匹配: 期望 {len(columns)} 列，实际 {len(tokens)} 列",
            )
        try:
            rows.append([float(token) for token in tokens])
        except ValueError:
            raise _tabular_mdif_error(path, lineno, f"非数值数据行: {line!r}") from None

    if block_name is not None:
        raise _tabular_mdif_error(path, lineno, "BEGIN 未闭合（文件结束仍缺 END）")
    if not tables:
        raise ValueError(f"Tabular MDIF 中未找到任何 BEGIN/END 数据块: {path}")
