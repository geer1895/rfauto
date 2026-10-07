"""Touchstone 扩展互操作：TS 2.1 写出 + HFSS 注释块读取（ME-10）。

与 :mod:`rfauto.adapters.interchange` 的 G16 互操作矩阵（1.0/2.0/MDIF/CITI）
互补，提供两件能力：

- :func:`write_touchstone_v2`：Touchstone 2.1 格式写出。skrf 2.1.0 的
  ``Network.write_touchstone`` 已原生支持 ``version="2.1"``（写出
  ``[Version] 2.1`` 关键字与完整 TS2 关键字结构，实测读回逐位恒等），
  本函数做薄封装并注入 provenance 注释块（工具版本/生成时间/run id/
  自定义行），供互操作下游追溯数据来源。
- :func:`read_hfss_touchstone_comments`：解析 HFSS ExportNetworkData 落盘
  文件的 ``!`` 注释块——``! Gamma``（逐模传播常数）与 ``! Port Impedance``
  （Zpi 口径端口阻抗），KJ-P2 测量面修复的模态基直读抓手：HFSS 2025.1
  Modal Solution Data 不再暴露 Zpi/Zpv/Zvi 类别（df6⑪）时，注释块是
  这些模态量的唯一直读来源。

破环面回归口径：skrf 2.0 移除惰性加载与 ``setup_pylab``，本模块只用
显式导入的 ``skrf`` 顶层与公开 IO 面，不触碰任何 v2.0 已移除符号。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import skrf

logger = logging.getLogger(__name__)

#: 本模块写出的 Touchstone 版本档（skrf 原生支持的三个档之一）。
TOUCHSTONE_VERSION_V2 = "2.1"

#: TS2 关键字结构（ITC/IPC Touchstone 2.0/2.1 规范公开口径；2.1 档在
#: [Version] 关键字处写 "2.1"，其余关键字结构与 2.0 相同）。
#: skrf 写出器按 ``version="2.1"`` 产出该结构并自带 [End]。
_TS21_FIRST_KEYWORD = "[Version] 2.1"

#: provenance 注释块首行（工具标识行前缀）。
_PROVENANCE_TOOL_LINE = "! rfauto touchstone_interop.write_touchstone_v2"

# ---------------------------------------------------------------------------
# 件 1：Touchstone 2.1 写出（skrf 原生薄封装 + provenance 注释注入）
# ---------------------------------------------------------------------------


def write_touchstone_v2(
    network: skrf.Network,
    path: str | Path,
    *,
    comments: Sequence[str] | None = None,
    run_id: str | None = None,
    write_z0: bool = True,
    form: str = "ri",
    parameter: str = "S",
) -> Path:
    """以 Touchstone 2.1 格式写出网络并注入 provenance 注释块。

    skrf 2.1.0 原生支持 2.1 版关键字（``Network.write_touchstone`` 的
    ``version`` 参数，实测 ``[Version] 2.1`` 结构写出并逐位读回），本函数
    薄封装之：先由 skrf 写出正文，再把 provenance 注释行插到文件最顶部
    （``!`` 注释行先于 TS2 首关键字合法，skrf 读取端实测逐位读回不受影响）。

    数据档默认 ``form="ri"``（实部/虚部）——唯一无损档；``"ma"``/``"db"``
    经幅度/相位重构造有双精度舍入损失，roundtrip 只保证 ≪1e-12 而非逐位。

    Parameters
    ----------
    network : skrf.Network
        待写出的网络（任意端口数；TS2 无 2 端口序列歧义问题）。
    path : str | Path
        输出文件路径（扩展名建议按端口数 .sNp 命名，本函数不改正名）。
    comments : Sequence[str], optional
        追加的自定义注释行（每行以 ``! `` 前缀写出）。
    run_id : str, optional
        关联的 run 标识（如 workflow/战役 id），写入 provenance 行。
    write_z0 : bool, optional
        是否写出参考阻抗（``[Reference]`` 关键字 + 逐频点
        ``! Port Impedance`` 注释行，默认 True）。
    form : str, optional
        数据档："ri"（默认，无损）/ "ma" / "db"。
    parameter : str, optional
        参数类型："S"（默认）/ "Y" / "Z" / "G" / "H"。

    Returns
    -------
    Path
        导出文件路径。

    Raises
    ------
    ValueError
        form/parameter 不被 skrf 接受（原样透传 skrf 的校验）。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(
        "导出 Touchstone 2.1 文件: %s (nports=%d, form=%s)", path,
        network.nports, form,
    )
    network.write_touchstone(
        str(path),
        version=TOUCHSTONE_VERSION_V2,
        write_z0=write_z0,
        form=form,
        parameter=parameter,
    )

    body = path.read_text(encoding="ISO-8859-1")
    provenance = _provenance_lines(comments, run_id)
    full_text = "".join(line + "\n" for line in provenance) + body

    # skrf 正文恒为 ASCII；provenance 可含非 ASCII（自定义注释）——有非
    # ASCII 时整文件降级 utf-8（skrf 2.1 读取端自动猜编码，实测可读回）。
    try:
        data = full_text.encode("ISO-8859-1")
    except UnicodeEncodeError:
        data = full_text.encode("utf-8")
    path.write_bytes(data)
    return path


def _provenance_lines(
    comments: Sequence[str] | None, run_id: str | None
) -> list[str]:
    """构造 provenance 注释行（工具版本/UTC 生成时间/run id/自定义行）。

    审查轨 C P1-2：含 ``\\n`` 的注释字符串会把裸数据行注入 TS2 数据区——
    写端静默损坏、读端才炸。逐条防御：换行拆成多行、每段强制 `!` 前缀
    （数据区零注入）；run_id 含换行显式拒绝。
    """
    lines = [
        _PROVENANCE_TOOL_LINE,
        f"! skrf={skrf.__version__} format=touchstone-{TOUCHSTONE_VERSION_V2}",
        "! generated="
        + datetime.now(timezone.utc).isoformat(timespec="seconds"),
    ]
    if run_id:
        if "\n" in str(run_id):
            raise ValueError("run_id 不允许包含换行（会注入 Touchstone 数据区）")
        lines.append(f"! run_id={run_id}")
    for comment in (comments or []):
        text = str(comment)
        for seg in (text.splitlines() or [""]):
            seg = seg.rstrip("\r")
            lines.append(seg if seg.startswith("!") else f"! {seg}")
    return lines


# ---------------------------------------------------------------------------
# 件 2：HFSS Touchstone 注释块读取（Gamma 传播常数 + Zpi 端口阻抗）
# ---------------------------------------------------------------------------


def read_hfss_touchstone_comments(path: str | Path) -> dict[str, Any]:
    """解析 HFSS 导出 Touchstone 文件的 ``!`` 注释块（模态基直读）。

    解析 HFSS ExportNetworkData 逐频点写出的两组注释行（每组 2N 个数值，
    N=端口/模数）：

    - ``! Gamma   <re> <im> ×N``：逐模传播常数 **γ = α + jβ**（Np/m,
      rad/m）的实/虚部。**不是反射系数**——真实 corpus 数值互证（
      runs/cps_hfss_arbitration 2025.1 导出）：β/f 跨频点恒定（β∝f），
      而若按 mag/deg 反射解读则与同频 ``! Port Impedance`` 行相对 50 Ω
      的反射系数（0.427∠0.077°）矛盾。
    - ``! Port Impedance   <re> <im> ×N``：端口阻抗 **Zpi 口径**（功率-
      电流定义）的实/虚部。**恒为 Zpi，不按 CharImp 写出**（#254）——
      需要特性阻抗语义的消费者（KJ-P2 模态 Zo 架构）必须自行判定 Zpi
      的适用性；宽端口三定义互差 ~2.5% 属准 TEM 截面的真实分歧
      （df7+⑲），本函数按字面读出不作语义修正。

    其余注释面：重归一旗标（``!Data is not renormalized`` /
    ``! Renormalizing to <X> <unit>``）、端口名（``! Port[k] = 名``）、
    ``Key: Value`` 形态的头部元数据（File/Design/Setup/...），以及全部
    注释行原文（raw，保真留痕）。

    行序即频率序（与 S 数据行一一对应）；本函数不读 S 数据（skrf 负责），
    只消费 ``!`` 注释行——对 skrf ``write_touchstone(write_z0=True)`` 产出
    的同关键字 ``! Port Impedance`` 行同样可读（互操作对称）。

    Parameters
    ----------
    path : str | Path
        HFSS 导出的 .sNp 文件路径。

    Returns
    -------
    dict
        - ``n_ports`` : int | None —— 注释行推断的端口/模数（无 Gamma 与
          Port Impedance 行时 None）。
        - ``n_freqs`` : int | None —— 注释行覆盖的频点数（同上为 None）。
        - ``port_zpi`` : np.ndarray | None —— shape (n_freqs, n_ports)
          complex，Zpi 口径逐频点端口阻抗。
        - ``gamma`` : np.ndarray | None —— 同形状，逐模传播常数 γ=α+jβ。
        - ``renormalized`` : bool | None —— 重归一旗标（未声明为 None）。
        - ``renormalize_ohm`` : float | None —— "Renormalizing to X" 的 X。
        - ``port_names`` : list[str] | None —— 按 Port[k] 索引排序的名称。
        - ``header`` : dict[str, str] —— "Key: Value" 形态头部元数据。
        - ``raw`` : list[str] —— 全部注释行原文（保真，含前导空白）。

    Raises
    ------
    FileNotFoundError
        文件不存在。
    ValueError
        注释行数值结构与已解析行矛盾（端口数不一致/频点数不一致/奇数个
        数值 token）——数据面矛盾显式报，不静默放行（#316 方向）。
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Touchstone 文件不存在: {path}")
    text = path.read_text(encoding="utf-8-sig", errors="replace")

    raw = [line for line in text.splitlines() if line.lstrip().startswith("!")]
    header: dict[str, str] = {}
    port_names: dict[int, str] = {}
    gamma_rows: list[np.ndarray] = []
    zpi_rows: list[np.ndarray] = []
    renormalized: bool | None = None
    renormalize_ohm: float | None = None

    for line in raw:
        stripped = line.lstrip()[1:].strip()  # 去掉 '!' 与后续空白

        if stripped.upper().startswith("GAMMA"):
            gamma_rows.append(_parse_comment_pairs(stripped[len("GAMMA"):],
                                                   path, "Gamma"))
            continue
        if stripped.upper().startswith("PORT IMPEDANCE"):
            zpi_rows.append(_parse_comment_pairs(
                stripped[len("PORT IMPEDANCE"):], path, "Port Impedance"))
            continue

        lowered = stripped.lower()
        if "renormaliz" in lowered:
            if "not renormalized" in lowered:
                renormalized = False
            else:
                renormalized = True
                match = re.search(
                    r"renormaliz\w*\s+to\s+([0-9.eE+-]+)", lowered)
                if match:
                    renormalize_ohm = float(match.group(1))
            continue

        match = re.match(r"Port\[(\d+)\]\s*=\s*(.+)$", stripped)
        if match:
            port_names[int(match.group(1))] = match.group(2).strip()
            continue

        match = re.match(r"([A-Za-z][A-Za-z0-9 _()]*?)\s*:\s+(.+)$", stripped)
        if match:
            header[match.group(1).strip()] = match.group(2).strip()

    n_ports: int | None = None
    n_freqs: int | None = None
    port_zpi: np.ndarray | None = None
    gamma: np.ndarray | None = None

    if gamma_rows or zpi_rows:
        if gamma_rows and zpi_rows and len(gamma_rows) != len(zpi_rows):
            raise ValueError(
                f"HFSS 注释块 Gamma 行数({len(gamma_rows)})与 Port Impedance "
                f"行数({len(zpi_rows)})不一致: {path}"
            )
        widths = {row.shape[0] for row in gamma_rows + zpi_rows}
        if len(widths) != 1:
            raise ValueError(
                f"HFSS 注释块端口/模数在行间不一致（每组应为 2N 个）: {path}"
            )
        n_ports = widths.pop()
        n_freqs = len(gamma_rows or zpi_rows)
        if gamma_rows:
            gamma = np.asarray(gamma_rows, dtype=complex)
        if zpi_rows:
            port_zpi = np.asarray(zpi_rows, dtype=complex)

    logger.info(
        "解析 HFSS 注释块: %s (n_ports=%s, n_freqs=%s, gamma=%s, zpi=%s)",
        path, n_ports, n_freqs, gamma is not None, port_zpi is not None,
    )
    return {
        "n_ports": n_ports,
        "n_freqs": n_freqs,
        "port_zpi": port_zpi,
        "gamma": gamma,
        "renormalized": renormalized,
        "renormalize_ohm": renormalize_ohm,
        "port_names": (
            [port_names[k] for k in sorted(port_names)]
            if port_names else None
        ),
        "header": header,
        "raw": raw,
    }


def _parse_comment_pairs(rest: str, path: Path, label: str) -> np.ndarray:
    """把注释关键字后的数值串解析成 (n_ports,) 复数数组。

    HFSS 惯例：数值成对出现（Gamma 为 γ 的 α/β 两列，Port Impedance 为
    Z 的 re/im 两列）。奇数个 token 属结构损坏，显式报错。
    """
    tokens = rest.split()
    try:
        values = np.asarray([float(token) for token in tokens], dtype=float)
    except ValueError:
        raise ValueError(
            f"HFSS 注释块 {label} 行含非数值 token: {path} -> {rest[:80]!r}"
        ) from None
    if values.size == 0 or values.size % 2:
        raise ValueError(
            f"HFSS 注释块 {label} 行数值 token 数为奇数（应为 2N 个）: {path}"
        )
    pairs = values.reshape(-1, 2)
    return pairs[:, 0] + 1j * pairs[:, 1]
