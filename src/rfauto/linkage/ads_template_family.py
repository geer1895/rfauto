"""ADS 网表参数化模板族（wilkinson_snp / branchline_cascade，TODO 0bn④）。

动机
----
linkage/templates/ads 下的两张共享 .net 模板各有一个专用渲染器
（adapters/ads_netlist.generate_netlist 与 linkage/field_circuit_anchor.
render_cascade_netlist），自由度分别绑死在"Touchstone 元信息"与"锚默认值"上。
本模块把两个拓扑收进**一个参数化模板族**：全部自由度（频扫、端口阻抗、SnP
数据源、级联线段电长度/阻抗/标定频率）由 JSON 原生参数字典显式给出，确定性
纯文本生成器渲染；**不改动共享 .net 模板**（防并发冲突，0bn④ 原话）。
服务层 JSON 进出见 service/ads_template_service.py。

族定义
------
- ``wilkinson_snp``：N 端口 SnP 直通扫频（Port×N + SnP）。generate_netlist
  的显式参数版——频扫可与 Touchstone 频带不同（SnP InterpMode=linear /
  ExtrapMode=constant 兜底），端口数可显式给或从 Touchstone 读。
- ``branchline_cascade``：入线 TLIN(E=θ_in @F=f0) → 4 端口 SnP（3/4 口接
  匹配 Port 终止）→ 出线 TLIN(E=θ_out)，与 field_circuit_anchor 的锚网表
  **同拓扑同语法**（tests/unit 钉死"同参数同文本"）；TLIN E@F 语义=电长度在
  f0 标定、随频率线性缩放，与 skrf ``line(d, unit='deg', f0)`` 同口径。

语法铁律（ADR-0009 + WP4.3 真机实证）
--------------------------------------
每条语句独占一行；SnP 节点恰好 NumPorts 个、不含地；Type="touchstone"；
文件纯 ASCII 无 BOM；``Term:`` 模型在 hpeesofsim 中不存在（用 Port 终止，
S 参数定义本身即"其余端口匹配"）。

闭式 Wilkinson 参考（``wilkinson_smatrix``）
--------------------------------------------
等分 Wilkinson：1→2、1→3 两段 √2·Z0 四分之一波长线 + 2-3 间 2·Z0 隔离电阻，
节点导纳法组网（与 field_circuit_anchor.branchline_smatrix 同法）。f0 处
教科书值：S11=S22=S33=0、|S21|=|S31|=1/√2、S23=0（理想隔离）。用途与
branchline 闭式基准相同：真机链与离线回归共用的"EM 数据"形态替身，不是
任何 EM 引擎响应的保真声明。

分层：linkage 层，可 import adapters/core/同层；不 import service 以上。
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

import numpy as np
import skrf

logger = logging.getLogger(__name__)

#: 模板族成员名。
FAMILIES: tuple[str, ...] = ("wilkinson_snp", "branchline_cascade")

#: 频率单位 → Hz 换算（与 adapters/ads_netlist._frequency_scale 同表）。
_UNIT_SCALE = {"GHz": 1e9, "MHz": 1e6, "kHz": 1e3, "Hz": 1.0}

#: 网表公共头（与共享模板逐字一致：Options / S_Param / SweepPlan / OutputPlan）。
_HEADER = (
    "Options ResourceUsage=yes UseNutmegFormat=no EnableOptim=no\n"
    'S_Param:SP1 CalcS=yes CalcY=no CalcZ=no StatusLevel=2 SweepVar="freq" '
    'SweepPlan="SP1_stim" OutputPlan="SP1_Output"\n'
    "SweepPlan: SP1_stim Start={fstart:g} {unit} Stop={fstop:g} {unit} Lin={npoints}\n"
    'OutputPlan:SP1_Output Type="Output" EquationNestLevel=2 SavedEquationNestLevel=2\n'
)

#: branchline_cascade 的锚默认参数（与 field_circuit_anchor DEFAULT_* 同值）。
BRANCHLINE_CASCADE_DEFAULTS: dict[str, float] = {
    "f0_hz": 2.4e9,
    "theta_in_deg": 90.0,
    "theta_out_deg": 45.0,
    "z_line": 50.0,
    "z0": 50.0,
}


# --------------------------------------------------------------------------- #
# 频扫参数解析
# --------------------------------------------------------------------------- #

def resolve_sweep(
    snp_path: str | Path | None,
    sweep: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """频扫参数：显式 ``sweep``（fstart/fstop/npoints/unit）优先，缺项从 Touchstone 读。

    返回 {"fstart", "fstop"（单位制下数值）, "npoints", "unit", "fstart_hz",
    "fstop_hz", "source": "explicit"|"touchstone"|"mixed"}。
    """
    sweep = dict(sweep or {})
    unit = str(sweep.get("unit", "GHz"))
    if unit not in _UNIT_SCALE:
        raise ValueError(f"未知频率单位 {unit!r}（可选 {sorted(_UNIT_SCALE)}）")
    scale = _UNIT_SCALE[unit]
    need_file = any(k not in sweep for k in ("fstart", "fstop", "npoints"))
    meta: dict[str, Any] | None = None
    if need_file:
        if snp_path is None:
            raise ValueError("sweep 未完整给出 fstart/fstop/npoints，且无 Touchstone 可读")
        from rfauto.adapters import ads_netlist

        meta = ads_netlist.snp_meta_for_netlist(snp_path)
    fstart = float(sweep["fstart"]) if "fstart" in sweep else meta["fstart_hz"] / scale
    fstop = float(sweep["fstop"]) if "fstop" in sweep else meta["fstop_hz"] / scale
    npoints = int(sweep["npoints"]) if "npoints" in sweep else int(meta["npoints"])
    if not (fstop > fstart > 0):
        raise ValueError(f"频扫非法: fstart={fstart} fstop={fstop} {unit}")
    if npoints < 2:
        raise ValueError(f"频点数必须 ≥ 2，实际 {npoints}")
    explicit = sum(k in sweep for k in ("fstart", "fstop", "npoints"))
    source = "explicit" if explicit == 3 else ("touchstone" if explicit == 0 else "mixed")
    return {
        "fstart": fstart, "fstop": fstop, "npoints": npoints, "unit": unit,
        "fstart_hz": fstart * scale, "fstop_hz": fstop * scale, "source": source,
    }


def _resolve_n_ports(snp_path: str | Path | None, n_ports: int | None) -> int:
    if n_ports is not None:
        n = int(n_ports)
        if n < 1:
            raise ValueError(f"端口数必须 ≥ 1，实际 {n}")
        return n
    if snp_path is None:
        raise ValueError("未给 n_ports 且无 Touchstone 可读")
    from rfauto.adapters import ads_netlist

    return int(ads_netlist.snp_meta_for_netlist(snp_path)["n_ports"])


def _snp_line(snp_path: str | Path, nodes: list[str]) -> str:
    """SnP 组件行（ADR-0009 实证语法；节点恰好 NumPorts 个、不含地）。"""
    return (
        f'SnP:SNP1  {" ".join(nodes)} NumPorts={len(nodes)} File="{Path(snp_path).resolve()}" '
        f'Type="touchstone" InterpMode="linear" InterpDom="" ExtrapMode="constant" '
        f"Temp=27.0 CheckPassivity=0"
    )


def _header(sweep: dict[str, Any]) -> str:
    return _HEADER.format(
        fstart=sweep["fstart"], fstop=sweep["fstop"], unit=sweep["unit"], npoints=sweep["npoints"],
    )


# --------------------------------------------------------------------------- #
# 族成员 1：wilkinson_snp（N 端口 SnP 直通扫频）
# --------------------------------------------------------------------------- #

def render_wilkinson_snp(
    snp_path: str | Path,
    *,
    sweep: dict[str, Any] | None = None,
    n_ports: int | None = None,
    z0: float = 50.0,
) -> str:
    """N 端口 SnP 直通扫频网表文本（Port×N + SnP；generate_netlist 的显式参数版）。

    Port 节点名 P1..PN 与 SnP 节点一一对应；Z 统一 ``z0``；频扫见
    :func:`resolve_sweep`。返回纯 ASCII 文本（末尾换行）。
    """
    sw = resolve_sweep(snp_path, sweep)
    n = _resolve_n_ports(snp_path, n_ports)
    nodes = [f"P{i}" for i in range(1, n + 1)]
    ports = [f"Port:P{i}  P{i} 0 Num={i} Z={float(z0):g} Ohm Noise=yes" for i in range(1, n + 1)]
    text = _header(sw) + "\n".join(ports) + "\n" + _snp_line(snp_path, nodes) + "\n"
    _assert_ascii(text)
    return text


# --------------------------------------------------------------------------- #
# 族成员 2：branchline_cascade（TLIN → 4 端口 SnP → TLIN）
# --------------------------------------------------------------------------- #

def render_branchline_cascade(
    snp_path: str | Path,
    *,
    sweep: dict[str, Any] | None = None,
    f0_hz: float = BRANCHLINE_CASCADE_DEFAULTS["f0_hz"],
    theta_in_deg: float = BRANCHLINE_CASCADE_DEFAULTS["theta_in_deg"],
    theta_out_deg: float = BRANCHLINE_CASCADE_DEFAULTS["theta_out_deg"],
    z_line: float = BRANCHLINE_CASCADE_DEFAULTS["z_line"],
    z0: float = BRANCHLINE_CASCADE_DEFAULTS["z0"],
    n_ports: int | None = None,
) -> str:
    """branchline 级联网表文本：P1 →TLIN1→ SnP(4 口) →TLIN2→ P2，3/4 口接 P3/P4 终止。

    与 field_circuit_anchor.render_cascade_netlist 同拓扑同语法（单测钉死同参数
    同文本），额外允许显式 ``sweep``（锚渲染器固定取 Touchstone 频带）。
    """
    n = _resolve_n_ports(snp_path, n_ports)
    if n != 4:
        raise ValueError(f"branchline_cascade 期望 4 端口 Touchstone，得到 {n}")
    sw = resolve_sweep(snp_path, sweep)
    unit = sw["unit"]
    f0_unit = float(f0_hz) / _UNIT_SCALE[unit]
    if f0_unit <= 0:
        raise ValueError(f"f0_hz 必须 > 0，实际 {f0_hz}")
    ports = [
        f"Port:P1  N_A 0 Num=1 Z={float(z0):g} Ohm Noise=yes",
        f"Port:P2  N_D 0 Num=2 Z={float(z0):g} Ohm Noise=yes",
        f"Port:P3  N_T1 0 Num=3 Z={float(z0):g} Ohm Noise=yes",
        f"Port:P4  N_T2 0 Num=4 Z={float(z0):g} Ohm Noise=yes",
    ]
    line_in = f"TLIN:TLIN1  N_A N_B  Z={float(z_line):g} Ohm E={float(theta_in_deg):g} F={f0_unit:g} {unit}"
    line_out = f"TLIN:TLIN2  N_C N_D  Z={float(z_line):g} Ohm E={float(theta_out_deg):g} F={f0_unit:g} {unit}"
    body = "\n".join([*ports, line_in, _snp_line(snp_path, ["N_B", "N_C", "N_T1", "N_T2"]), line_out])
    text = _header(sw) + body + "\n"
    _assert_ascii(text)
    return text


# --------------------------------------------------------------------------- #
# 族入口 + 写盘
# --------------------------------------------------------------------------- #

def render_family(family: str, snp_path: str | Path, params: dict[str, Any] | None = None) -> str:
    """按族名分派渲染（``params`` 为对应渲染器的关键字参数，JSON 原生）。"""
    params = dict(params or {})
    if family == "wilkinson_snp":
        return render_wilkinson_snp(snp_path, **params)
    if family == "branchline_cascade":
        return render_branchline_cascade(snp_path, **params)
    raise ValueError(f"未知模板族 {family!r}（可选 {list(FAMILIES)}）")


def write_netlist(text: str, output_path: str | Path) -> Path:
    """写网表（纯 ASCII、无 BOM、LF 换行）；返回路径。"""
    _assert_ascii(text)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(text.encode("ascii"))
    logger.info("ADS 模板族网表已写出: %s (%d 行)", out, text.count("\n"))
    return out


def _assert_ascii(text: str) -> None:
    try:
        text.encode("ascii")
    except UnicodeEncodeError as exc:  # 路径含非 ASCII 字符等
        raise ValueError(f"ADS 网表必须纯 ASCII: {exc}") from exc


# --------------------------------------------------------------------------- #
# 闭式 Wilkinson 参考（wilkinson_snp 族的"EM 数据"替身）
# --------------------------------------------------------------------------- #

def _line_yparams(z_c: float, gamma_l: complex) -> tuple[complex, complex]:
    """均匀有耗线二端口导纳（y11=coth(γl)/Zc，y12=−csch(γl)/Zc；与
    field_circuit_anchor 同式，本地复刻避免依赖同层私有名）。"""
    gl = complex(gamma_l)
    return 1.0 / np.tanh(gl) / z_c, -1.0 / np.sinh(gl) / z_c


def wilkinson_smatrix(
    freq_hz: object,
    f0_hz: float = 2.4e9,
    z0: float = 50.0,
    loss_np_per_qw: float = 0.0,
) -> np.ndarray:
    """等分 Wilkinson 功分器 3 端口 S 参数（闭式传输线网络，确定性）。

    端口：1=输入 2/3=输出。1-2、1-3 各一段 √2·Z0 四分之一波长线（电长度在 f0
    处 90°、随频率线性缩放），2-3 间隔离电阻 2·Z0。节点导纳法：Y 装配后
    y=z0·Y，S=(I+y)^{-1}(I−y)。``loss_np_per_qw`` 为每段线的均匀衰减（Np，
    随频率线性缩放；缺省 0 = 理想无耗）。
    """
    f = np.atleast_1d(np.asarray(freq_hz, dtype=float))
    ratio = f / float(f0_hz)
    gamma_l = complex(loss_np_per_qw) * ratio + 1j * (np.pi / 2.0) * ratio
    z_arm = float(z0) * math.sqrt(2.0)
    g_iso = 1.0 / (2.0 * float(z0))
    n = f.size
    s = np.zeros((n, 3, 3), dtype=complex)
    eye = np.eye(3, dtype=complex)
    for k in range(n):
        y = np.zeros((3, 3), dtype=complex)
        for a, b in ((0, 1), (0, 2)):
            y11, y12 = _line_yparams(z_arm, gamma_l[k])
            y[a, a] += y11
            y[b, b] += y11
            y[a, b] += y12
            y[b, a] += y12
        y[1, 1] += g_iso
        y[2, 2] += g_iso
        y[1, 2] -= g_iso
        y[2, 1] -= g_iso
        y_norm = y * float(z0)
        s[k] = np.linalg.inv(eye + y_norm) @ (eye - y_norm)
    return s


def build_wilkinson_touchstone(
    path: str | Path,
    *,
    f0_hz: float = 2.4e9,
    band_hz: tuple[float, float] = (1.6e9, 3.2e9),
    n_points: int = 401,
    z0: float = 50.0,
    loss_np_per_qw: float = 0.0,
) -> Path:
    """闭式 Wilkinson 基准 → .s3p（wilkinson_snp 族真机链/离线回归共用的数据形态）。"""
    freq = np.linspace(band_hz[0], band_hz[1], int(n_points))
    s = wilkinson_smatrix(freq, f0_hz=f0_hz, z0=z0, loss_np_per_qw=loss_np_per_qw)
    net = skrf.Network(
        frequency=skrf.Frequency.from_f(freq, unit="Hz"), s=s, z0=float(z0), name="wilkinson_ref",
    )
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    net.write_touchstone(str(out), form="db")
    logger.info("wilkinson 基准已写出: %s (%d 点, f0=%.3gHz)", out, n_points, f0_hz)
    return out


# --------------------------------------------------------------------------- #
# 真机结果对拍（确定性数值，服务层与 runs/ 证据共用）
# --------------------------------------------------------------------------- #

def payload_to_network(payload: dict[str, Any]) -> skrf.Network:
    """ads_netlist.parse_dataset 的 payload → skrf.Network（端口按 Num 顺序）。"""
    freq = np.asarray(payload["frequency_hz"], dtype=float)
    names = [str(x) for x in payload.get("port_names") or []]
    keys = list(payload["s"])
    n = len(names) if names else int(max(int(k.split("_")[0]) for k in keys))
    s = np.zeros((freq.size, n, n), dtype=complex)
    for key, vals in payload["s"].items():
        i, j = (int(x) for x in key.split("_"))
        s[:, i - 1, j - 1] = [complex(v[0], v[1]) for v in vals[: freq.size]]
    port_z = payload.get("port_z") or []
    z0 = [float(complex(v[0], v[1]).real) for v in port_z[:n]] or [50.0] * n
    return skrf.Network(frequency=skrf.Frequency.from_f(freq, unit="Hz"), s=s, z0=z0, name="ads")


def align_to_grid(ref: skrf.Network, target: skrf.Frequency) -> skrf.Network:
    """参考网络对齐到目标频栅：同栅（rtol 1e-9）直接换频轴，否则线性插值。

    Touchstone 写出/读回的频率有 ~1e-7 Hz 量级浮点噪声（实测 1.6e9 →
    1600000000.0000005），与显式频扫的精确端点相差一个 ulp 就会触发 scipy
    bounds 错误——同栅走快路径，异栅允许端点微量外推（bounds_error=False）。
    """
    fr = np.asarray(ref.f, dtype=float)
    ft = np.asarray(target.f, dtype=float)
    if fr.size == ft.size and np.allclose(fr, ft, rtol=1e-9, atol=0.0):
        return skrf.Network(frequency=target, s=ref.s, z0=ref.z0, name=ref.name)
    return ref.interpolate(target, kind="linear", bounds_error=False, fill_value="extrapolate")


def compare_family_result(
    family: str,
    snp_path: str | Path,
    payload: dict[str, Any],
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """ADS 结果 vs 确定性参考的逐点对拍（max|ΔS|，全响应），JSON 原生。

    - ``wilkinson_snp``：参考 = Touchstone 自身（skrf 读入并对齐到 ADS 频栅）
      ——SnP 直通即"数据穿透"，max|ΔS| 量级应为 Touchstone 写出精度；
    - ``branchline_cascade``：参考 = field_circuit_anchor.compose_reference_cascade
      （skrf DistributedCircuit 电长度线 + 匹配终止 2×2 子阵），比较合成 2 端口
      的全部 4 个响应，另附 D12 FSV 摘要（S11/S21 dB 幅度 + S21 相位护栏）。
    """
    params = dict(params or {})
    ads_net = payload_to_network(payload)
    ref4 = skrf.Network(str(snp_path))
    if family == "wilkinson_snp":
        ref = align_to_grid(ref4, ads_net.frequency)
        cmp_net = ads_net
        extra: dict[str, Any] = {}
    elif family == "branchline_cascade":
        from rfauto.linkage import field_circuit_anchor as fca

        d = {**BRANCHLINE_CASCADE_DEFAULTS, **{k: params[k] for k in params if k in BRANCHLINE_CASCADE_DEFAULTS}}
        ref_full = fca.compose_reference_cascade(
            ref4, f0_hz=float(d["f0_hz"]), theta_in_deg=float(d["theta_in_deg"]),
            theta_out_deg=float(d["theta_out_deg"]), z_line=float(d["z_line"]),
        )
        ref = align_to_grid(ref_full, ads_net.frequency)
        cmp_net = fca.composite_network_from_payload(payload)
        extra = {"fsv": fca.fsv_cascade_report(cmp_net, ref)}
    else:
        raise ValueError(f"未知模板族 {family!r}（可选 {list(FAMILIES)}）")
    if cmp_net.nports != ref.nports:
        raise ValueError(f"端口数不一致: ADS {cmp_net.nports} vs 参考 {ref.nports}")
    diff = np.abs(cmp_net.s - ref.s)
    per: dict[str, float] = {}
    for i in range(ref.nports):
        for j in range(ref.nports):
            per[f"S{i + 1}{j + 1}"] = float(np.max(diff[:, i, j]))
    return {
        "family": family,
        "n_points": int(ads_net.f.size),
        "n_ports_compared": int(ref.nports),
        "max_abs_delta_s": float(np.max(diff)),
        "per_response_max_abs_delta_s": per,
        **extra,
    }
