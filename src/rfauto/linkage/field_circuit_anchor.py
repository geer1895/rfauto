"""WP4.3 场路协同端到端回归锚（§10.22 补强16）。

链路口径（方案行原文）
----------------------
"端到端回归锚：openEMS/HFSS Touchstone → ADS 电路 → 反标注参数 → 一致性；
接 D13 宏模型"，验收列："1 例 branchline S 参数进 ADS 级联 vs skrf 级联
FSV ≥VG"。

四段链路与裁判
--------------
1. **EM 数据段**：branchline .s4p（真机用法 = openEMS/HFSS export_touchstone
   的产物；离线回归 = ``build_branchline_touchstone`` 的闭式传输线网络基准，
   与 ADS/skrf 两侧无共享代码路径，作"EM 参考"替身）。
2. **电路级联段**：同一 .s4p 进 ADS（SnP + 两段 TLIN + Port×4——branchline
   3/4 口接 P3/P4 作 50Ω 匹配终止，S 参数定义即"其余端口匹配"，不引入
   额外元件类型；hpeesofsim B 档真机链，复用 ADR-0009 已实证的 SnP 语法；
   真机实证：`Term:` 网表模型名不存在，不可用）与 skrf 参考
   （``skrf.media.DistributedCircuit`` 电长度线 + 匹配终止子阵 + ``**`` 级联）。
   ADS TLIN 的 E/F 参数语义（电长度在 F 处标定、随频率线性缩放）与 skrf
   ``line(d, unit='deg', f0=...)`` 同口径——这是两侧可比的物理前提，
   由真机冒烟 + :data:`tests.unit.test_field_circuit_anchor` 双侧钉死。
3. **裁判**：合成 S11/S21 的 dB 幅度曲线交 D12 FSV 内核（IEEE 1597.1），
   判定 ``at_least_vg`` = 每个被测参数的 gdm_mean 等级 ≤ VG。
4. **D13 宏模型桥 + 反标注**：``macromodel_bridge`` 把 .s4p 拟合成有理宏模型
   并以宏模型替身重走 skrf 级联（模型级联 vs 参考级联再过一遍 FSV）；
   ``check_back_annotation_consistency`` 钉死 BackAnnotator 线性/反线性
   变换的闭式一致性与往返恢复误差。

诚实边界
--------
- 离线单测中"ADS 侧"用注入 ``ads_runner`` 的合成 payload，只验管线不充当
  裁判；验收数字（FSV ≥VG）由真机 hpeesofsim 运行承载
  （tests/real_edt/test_field_circuit_anchor_real.py + runs/ 证据）。
- 闭式 branchline 是无耗理想网络（εr→∞薄理想线），非 openEMS/HFSS 真机
  响应替身的保真声明；它只保证"同一数据文件进两条电路链"时链路自身
  的回归锚定。真机 EM 数据接入不改动本模块下游任何代码。
- 匹配负载终止 4 端口取 2×2 子阵是精确等式（Γ_L=0 时 S'ij = Sij），
  仅对 50Ω 匹配终止成立，不做一般负载推广。

分层：linkage 层，可 import adapters/core/同层 linkage；不 import service 以上。
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import skrf

from rfauto.core.fsv import GRADE_CODES, fsv, grade_index_of
from rfauto.core.macromodel import _DB_FLOOR, request_from_touchstone

logger = logging.getLogger(__name__)

#: 默认中心频率（branchline 名义频率，与 openems_templates branchline 默认一致）。
DEFAULT_F0_HZ = 2.4e9
#: 默认频点数（FSV MIN_POINTS=16 的富余供给，与真机 Touchstone 导出惯例对齐）。
DEFAULT_N_POINTS = 401
#: 默认频带（±33%，覆盖 branchline 主响应摆动）。
DEFAULT_FREQ_BAND_HZ = (1.6e9, 3.2e9)
#: 级联输入/输出线的电长度（度，@f0）。两侧故意不对称：S12≠S21，
#: 端口顺序接错时 FSV 与幅相检查都会显式失败。
DEFAULT_THETA_IN_DEG = 90.0
DEFAULT_THETA_OUT_DEG = 45.0
#: ADS 级联中线阻抗（branchline 外馈线 50Ω）。
DEFAULT_Z_LINE = 50.0
#: 闭式 branchline 基准的每四分之一波长均匀衰减（Np，≈0.17dB/臂，
#: 真实微带 branchline@2.4GHz 量级；见 branchline_smatrix docstring 的
#: 无源性边界讨论）。
DEFAULT_LOSS_NP_PER_QW = 0.02

#: 反标注一致性判定的相对误差门限（闭式浮点运算，实际 ~1e-15）。
BACK_ANNOTATION_RTOL = 1e-12


# --------------------------------------------------------------------------- #
# 1. EM 数据段：闭式 branchline 基准 + Touchstone 写出
# --------------------------------------------------------------------------- #

def _line_yparams(
    z_c: float, gamma_l: np.ndarray | complex,
) -> tuple[np.ndarray, np.ndarray]:
    """均匀有耗线的二端口导纳参数（γl = αl + jθ 复传播量 × 电长度）。

    y11 = coth(γl)/Zc，y12 = -csch(γl)/Zc（教科书闭式，由
    ABCD=[cosh γl, Zc·sinh γl; sinh γl/Zc, cosh γl] 经
    Y=(1/B)[[D, BC-AD],[-1, A]] 导出）；γl=jθ 时退化为
    y11 = -j·cot(θ)/Zc，y12 = j·csc(θ)/Zc。
    """
    gl = np.asarray(gamma_l, dtype=complex)
    y11 = 1.0 / np.tanh(gl) / z_c
    y12 = -1.0 / np.sinh(gl) / z_c
    return y11, y12


def branchline_smatrix(
    freq_hz: object,
    f0_hz: float = DEFAULT_F0_HZ,
    z0: float = 50.0,
    loss_np_per_qw: float = DEFAULT_LOSS_NP_PER_QW,
) -> np.ndarray:
    """3dB 90° 分支线耦合器 S 参数（闭式传输线网络，确定性）。

    拓扑（端口编号沿 openEMS/HFSS branchline 模板约定）：
    1=输入（左上）2=直通（右上）3=耦合（右下）4=隔离（左下）；
    串联臂 1-2、4-3 为 Z0/√2 四分之一波长线，并联臂 1-4、2-3 为 Z0
    四分之一波长线（电长度在 f0 处 90°、随频率线性缩放）。

    ``loss_np_per_qw``：每四分之一波长线的均匀衰减（Np，随频率线性缩放，
    与电长度同律）。缺省 0.02 Np（≈0.17dB/臂）——真实微带 branchline 在
    2.4GHz 的量级；同时使参考严格无源（σ_max<1），避免理想无耗模型压在
    无源性边界（σ=1）上导致 D13 拟合的 passivity_enforce 被数值噪声误触发
    （无耗版实测：拟合 RMS −42dB 达标，enforce 后劣化到 −32dB/FSV=VP）。
    传 0 复现理想无耗版。

    组网方式：四段线的导纳参数装入 4×4 节点导纳矩阵 Y，
    归一化 y = z0·Y 后 S = (I+y)^{-1}(I-y)。

    f0 处教科书值（loss=0 时精确，tests/unit 钉死）：|S11|=|S41|=0，
    |S21|=|S31|=1/√2（-3.0103dB），S21 = -j/√2（直通滞后 90°），
    S31 = -1/√2（耦合 180°）。
    """
    f = np.atleast_1d(np.asarray(freq_hz, dtype=float))
    ratio = f / float(f0_hz)
    gamma_l = complex(loss_np_per_qw) * ratio + 1j * (np.pi / 2.0) * ratio
    z_series = float(z0) / math.sqrt(2.0)
    z_shunt = float(z0)
    n = f.size
    s = np.zeros((n, 4, 4), dtype=complex)
    for k in range(n):
        y = np.zeros((4, 4), dtype=complex)
        for a, b, z_c in ((0, 1, z_series), (3, 2, z_series), (0, 3, z_shunt), (1, 2, z_shunt)):
            y11, y12 = _line_yparams(z_c, gamma_l[k])
            y[a, a] += y11
            y[b, b] += y11
            y[a, b] += y12
            y[b, a] += y12
        y_norm = y * float(z0)
        eye = np.eye(4, dtype=complex)
        s[k] = np.linalg.inv(eye + y_norm) @ (eye - y_norm)
    return s


def build_branchline_touchstone(
    path: str | Path,
    *,
    f0_hz: float = DEFAULT_F0_HZ,
    band_hz: tuple[float, float] = DEFAULT_FREQ_BAND_HZ,
    n_points: int = DEFAULT_N_POINTS,
    z0: float = 50.0,
    loss_np_per_qw: float = DEFAULT_LOSS_NP_PER_QW,
) -> Path:
    """闭式 branchline 基准 → .s4p（真机链与离线回归共用的"EM 数据"形态）。

    真机用法：把 openEMS/HFSS export_touchstone 的 .s4p 放在同一路径位即可，
    下游（级联/裁判/宏模型/反标注）零改动。
    """
    freq = np.linspace(band_hz[0], band_hz[1], int(n_points))
    s = branchline_smatrix(freq, f0_hz=f0_hz, z0=z0, loss_np_per_qw=loss_np_per_qw)
    network = skrf.Network(
        frequency=skrf.Frequency.from_f(freq, unit="Hz"), s=s, z0=float(z0),
        name="branchline_ref",
    )
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    network.write_touchstone(str(out), form="db")
    logger.info("branchline 基准已写出: %s (%d 点, f0=%.3gHz)", out, n_points, f0_hz)
    return out


# --------------------------------------------------------------------------- #
# 2. skrf 参考级联
# --------------------------------------------------------------------------- #

def _terminated_two_port(net4: skrf.Network) -> skrf.Network:
    """4 端口 → 前 2 端口 2×2 视图（其余端口 50Ω 匹配终止）。

    Γ_L=0 时 S'ij = Sij（精确等式，见模块 docstring 诚实边界），
    故直接取子阵；仅适用于匹配终止，不做一般负载推广。
    """
    if net4.nports != 4:
        raise ValueError(f"期望 4 端口网络，得到 {net4.nports} 端口")
    return skrf.Network(
        frequency=net4.frequency, s=net4.s[:, :2, :2], z0=net4.z0[:, :2], name=net4.name,
    )


def compose_reference_cascade(
    net4: skrf.Network,
    *,
    f0_hz: float = DEFAULT_F0_HZ,
    theta_in_deg: float = DEFAULT_THETA_IN_DEG,
    theta_out_deg: float = DEFAULT_THETA_OUT_DEG,
    z_line: float = DEFAULT_Z_LINE,
) -> skrf.Network:
    """skrf 参考级联：入线 → （匹配终止的 branchline 2×2 视图）→ 出线。

    电长度线用 ``skrf.media.DistributedCircuit``（无耗电报方程：Z0=√(L/C)
    恒定、β∝f 线性相位），``line(d, unit='deg', f0=f0_hz)`` 与 ADS TLIN 的
    E@F 语义同口径（电长度在 f0 标定、随频率线性缩放）。
    """
    media = skrf.media.DistributedCircuit(
        frequency=net4.frequency, L=z_line * 1e-9, C=1e-9 / z_line,
    )
    line_in = media.line(d=theta_in_deg, unit="deg", f0=f0_hz)
    line_out = media.line(d=theta_out_deg, unit="deg", f0=f0_hz)
    block = _terminated_two_port(net4)
    return line_in ** block ** line_out


def skrf_reference_cascade(
    snp_path: str | Path,
    *,
    f0_hz: float = DEFAULT_F0_HZ,
    theta_in_deg: float = DEFAULT_THETA_IN_DEG,
    theta_out_deg: float = DEFAULT_THETA_OUT_DEG,
    z_line: float = DEFAULT_Z_LINE,
) -> skrf.Network:
    """读 .sNp → skrf 参考级联合成 2 端口（裁判基准侧）。"""
    net4 = skrf.Network(str(snp_path))
    return compose_reference_cascade(
        net4, f0_hz=f0_hz, theta_in_deg=theta_in_deg, theta_out_deg=theta_out_deg, z_line=z_line,
    )


# --------------------------------------------------------------------------- #
# 3. ADS 电路级联（B 档真机链；ads_runner 可注入离线回归）
# --------------------------------------------------------------------------- #

_TPL_DIR = Path(__file__).resolve().parent / "templates" / "ads"
_CASCADE_TEMPLATE = _TPL_DIR / "branchline_cascade.net"


def render_cascade_netlist(
    snp_path: str | Path,
    output_path: str | Path,
    *,
    f0_hz: float = DEFAULT_F0_HZ,
    theta_in_deg: float = DEFAULT_THETA_IN_DEG,
    theta_out_deg: float = DEFAULT_THETA_OUT_DEG,
    z_line: float = DEFAULT_Z_LINE,
    z0: float = 50.0,
    frequency_unit: str = "GHz",
    template_path: str | Path | None = None,
) -> Path:
    """渲染 branchline 级联 ADS 网表（SnP + TLIN×2 + Port×4，ADR-0009 SnP 语法）。

    内部终止不引入额外元件类型：branchline 的 3/4 口直接接 Port P3/P4（Z=z0），
    S 参数定义本身即"其余端口匹配终止"，数据集 S[i,j]（i,j∈{1,2}）就是合成
    2 端口。（`Term:...` 网表模型名在 hpeesofsim 中不存在——实测
    "`TERM1' is an instance of an undefined model `Term'"，见模块 docstring。）
    """
    from rfauto.adapters import ads_netlist

    snp_path = Path(snp_path)
    output_path = Path(output_path)
    template_path = Path(template_path) if template_path else _CASCADE_TEMPLATE
    if not template_path.exists():
        raise FileNotFoundError(f"网表模板不存在: {template_path}")
    meta = ads_netlist.snp_meta_for_netlist(snp_path)
    if meta["n_ports"] != 4:
        raise ValueError(f"branchline 级联期望 4 端口 Touchstone，得到 {meta['n_ports']}")
    unit_scale = {"GHz": 1e9, "MHz": 1e6, "kHz": 1e3, "Hz": 1.0}[frequency_unit]
    f0_unit = float(f0_hz) / unit_scale

    port_lines = [
        f"Port:P1  N_A 0 Num=1 Z={z0:g} Ohm Noise=yes",
        f"Port:P2  N_D 0 Num=2 Z={z0:g} Ohm Noise=yes",
        f"Port:P3  N_T1 0 Num=3 Z={z0:g} Ohm Noise=yes",
        f"Port:P4  N_T2 0 Num=4 Z={z0:g} Ohm Noise=yes",
    ]
    snp_line = (
        f'SnP:SNP1  N_B N_C N_T1 N_T2 NumPorts=4 File="{snp_path.resolve()}" '
        f'Type="touchstone" InterpMode="linear" InterpDom="" ExtrapMode="constant" '
        f"Temp=27.0 CheckPassivity=0"
    )
    line_in = f"TLIN:TLIN1  N_A N_B  Z={z_line:g} Ohm E={theta_in_deg:g} F={f0_unit:g} {frequency_unit}"
    line_out = f"TLIN:TLIN2  N_C N_D  Z={z_line:g} Ohm E={theta_out_deg:g} F={f0_unit:g} {frequency_unit}"
    repl = {
        "{{FSTART}}": f"{meta['fstart_hz'] / unit_scale:g}",
        "{{FSTOP}}": f"{meta['fstop_hz'] / unit_scale:g}",
        "{{NPOINTS}}": str(meta["npoints"]),
        "{{FREQ_UNIT}}": frequency_unit,
        "{{PORTS}}": "\n".join(port_lines),
        "{{LINE_IN}}": line_in,
        "{{SNP_LINE}}": snp_line,
        "{{LINE_OUT}}": line_out,
    }
    text = template_path.read_text(encoding="utf-8")
    for key, val in repl.items():
        text = text.replace(key, val)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="ascii", errors="ignore")
    logger.info("branchline 级联网表已生成: %s", output_path)
    return output_path


def composite_network_from_payload(payload: dict[str, Any]) -> skrf.Network:
    """ADS .ds 探针 payload → 合成级联 2 端口 skrf.Network。

    端口定位：优先按名字找 P1/P2（合成 2 端口的入/出口），终止口 P3/P4 不参与；
    找不到时按前两端口兜底（并在返回 dict 由调用方记录）。
    """
    names = [str(x) for x in payload.get("port_names") or []]
    s_map = payload["s"]
    if "P1" in names and "P2" in names:
        i1, i2 = names.index("P1"), names.index("P2")
    else:
        i1, i2 = 0, 1
    freq = np.asarray(payload["frequency_hz"], dtype=float)
    n = freq.size

    def _resp(a: int, b: int) -> np.ndarray:
        key = f"{a + 1}_{b + 1}"
        vals = s_map.get(key)
        if vals is None:
            raise KeyError(f"ADS payload 缺少 S[{key}]（现有键: {sorted(s_map)}）")
        return np.array([complex(v[0], v[1]) for v in vals[:n]], dtype=complex)

    s = np.zeros((n, 2, 2), dtype=complex)
    s[:, 0, 0] = _resp(i1, i1)
    s[:, 1, 0] = _resp(i2, i1)
    s[:, 0, 1] = _resp(i1, i2)
    s[:, 1, 1] = _resp(i2, i2)
    port_z = payload.get("port_z") or [[50.0, 0.0], [50.0, 0.0]]
    z0 = [float(complex(v[0], v[1]).real) for v in port_z[:2]] or [50.0, 50.0]
    return skrf.Network(frequency=skrf.Frequency.from_f(freq, unit="Hz"), s=s, z0=z0, name="ads_cascade")


def run_ads_cascade(
    snp_path: str | Path,
    out_dir: str | Path,
    *,
    f0_hz: float = DEFAULT_F0_HZ,
    theta_in_deg: float = DEFAULT_THETA_IN_DEG,
    theta_out_deg: float = DEFAULT_THETA_OUT_DEG,
    z_line: float = DEFAULT_Z_LINE,
    ads_dir: str | Path | None = None,
    ads_runner: Callable[[Path], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """branchline .sNp → ADS 级联合成 2 端口。

    默认真机 B 档：render → hpeesofsim → keysight.ads.dataset 探针 → payload
    （复用 adapters/ads_netlist 既有链）。``ads_runner(netlist_path) -> payload``
    可注入（离线回归：合成 payload 只验管线，不充当裁判）。
    """
    from rfauto.adapters import ads_netlist

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    netlist = render_cascade_netlist(
        snp_path, out_dir / "cascade_netlist.txt",
        f0_hz=f0_hz, theta_in_deg=theta_in_deg, theta_out_deg=theta_out_deg, z_line=z_line,
    )
    render_s = time.time() - t0
    if ads_runner is not None:
        payload = ads_runner(netlist)
    else:
        t1 = time.time()
        ads_netlist.run_hpeesofsim(netlist, ads_dir=ads_dir)
        sim_s = time.time() - t1
        t2 = time.time()
        payload = ads_netlist.parse_dataset(Path(f"{netlist}.ds"), ads_dir=ads_dir)
        payload["_sim_time_s"] = sim_s
        payload["_parse_time_s"] = time.time() - t2
    network = composite_network_from_payload(payload)
    return {
        "netlist": netlist,
        "payload": payload,
        "network": network,
        "render_time_s": render_s,
    }


# --------------------------------------------------------------------------- #
# 4. FSV 裁判（D12 内核）
# --------------------------------------------------------------------------- #

def _db_curve(net: skrf.Network, i: int, j: int) -> np.ndarray:
    """S_ij 的 dB 幅度曲线（floor 与 core/macromodel 的 FSV 口径一致）。"""
    return 20.0 * np.log10(np.maximum(np.abs(net.s[:, i, j]), _DB_FLOOR))


#: 相位一致检查的缺省门限（度）。对称 branchline 的 |S21|=|S31|（dB 曲线
#: 完全相同），直通↔耦合端口接错、TLIN 电长度错位等错误 FSV(dB) 探不到，
#: 必须由相位护栏兜底（见 fsv_cascade_report docstring）。
DEFAULT_PHASE_TOL_DEG = 1.0
#: 相位检查的幅度地板（dB）：|S| 低于此值的频点相位无意义（深零点附近）。
_PHASE_FLOOR_DB = -40.0


def _wrapped_phase_diff_deg(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """两复数曲线的逐点相位差（度，wrap 到 (−180,180]）。"""
    d = np.angle(a * np.conj(b))
    return np.degrees(d)


def fsv_cascade_report(
    net_a: skrf.Network,
    net_b: skrf.Network,
    params: tuple[str, ...] = ("S11", "S21"),
    *,
    at_level: str = "VG",
    phase_params: tuple[str, ...] = ("S21",),
    phase_tol_deg: float = DEFAULT_PHASE_TOL_DEG,
) -> dict[str, Any]:
    """两条级联响应的对比报告：dB 幅度 FSV（D12 IEEE 1597.1 口径）+ 相位护栏。

    判定 ``at_least_vg``（或 ``at_level`` 指定等级）：每个参数的 gdm_mean
    等级 ≤ 指定等级（GRADE_CODES 下标比较）。

    **相位护栏**（``phase_consistent``）：dB 幅度 FSV 对"幅度相同、相位错位"
    的错误不敏感——对称 branchline 的 |S21(f)|=|S31(f)| 逐点相等（结构对称），
    直通↔耦合端口接错后 dB 曲线不变；级联链上匹配线段互换/电长度错位同样
    不改幅度（匹配级联的传输项可交换）。故对 ``phase_params`` 逐频点算
    相位差 wrap 到 (−180,180] 的最大绝对值，全带 ≤ ``phase_tol_deg`` 才算
    一致；|S| 低于 −40dB 的频点（深零点附近相位无意义）不参与统计，若有效
    频点不足 8 个则记 None（不可判定，不谎报一致）。
    """
    level_idx = GRADE_CODES.index(at_level)
    fa = np.asarray(net_a.f, dtype=float)
    fb = np.asarray(net_b.f, dtype=float)
    per: dict[str, Any] = {}
    worst_idx = 0
    for name in params:
        i, j = int(name[1]) - 1, int(name[2]) - 1
        r = fsv(fa, _db_curve(net_a, i, j), fb, _db_curve(net_b, i, j))
        idx = grade_index_of(float(r["gdm_mean"]))
        per[name] = {
            "gdm_mean": float(r["gdm_mean"]),
            "adm_mean": float(r["adm_mean"]),
            "fdm_mean_abs": float(r["fdm_mean_abs"]),
            "gdm_grade": r["gdm_grade"],
            "gdm_grade_level": int(r["gdm_grade_level"]),
            "gdm_spread": int(r["gdm_spread"]),
            "n_points": int(r["n_points"]),
        }
        worst_idx = max(worst_idx, idx)

    phase_checks: dict[str, Any] = {}
    phase_consistent: bool | None = True
    for name in phase_params:
        i, j = int(name[1]) - 1, int(name[2]) - 1
        sa = net_a.s[:, i, j]
        sb = net_b.s[:, i, j]
        floor = 10.0 ** (_PHASE_FLOOR_DB / 20.0)
        valid = (np.abs(sa) > floor) & (np.abs(sb) > floor)
        if int(valid.sum()) < 8:
            phase_checks[name] = {"max_abs_deg": None, "n_valid": int(valid.sum())}
            phase_consistent = None
            continue
        max_deg = float(np.max(np.abs(_wrapped_phase_diff_deg(sa[valid], sb[valid]))))
        ok = bool(max_deg <= phase_tol_deg)
        phase_checks[name] = {"max_abs_deg": max_deg, "n_valid": int(valid.sum()), "ok": ok}
        if phase_consistent is not None:
            phase_consistent = phase_consistent and ok

    return {
        "params": per,
        "worst_gdm_grade": GRADE_CODES[worst_idx],
        "at_least_vg": bool(worst_idx <= level_idx),
        "at_level": at_level,
        "phase_checks": phase_checks,
        "phase_consistent": phase_consistent,
        "phase_tol_deg": float(phase_tol_deg),
    }


# --------------------------------------------------------------------------- #
# 5. D13 宏模型桥
# --------------------------------------------------------------------------- #

def model_s_from_fit(fit_result: dict[str, Any]) -> np.ndarray:
    """fit_macromodel 结果（极点/留数/常数 JSON）→ 模型 S 矩阵 (nf, n, n)。

    复现 skrf ``VectorFitting.get_model_response`` 的口径（skrf 2.1.0 源码逐行）：
    实极点项 res_k/(s−p_k)；**共轭极点对在 poles 里只存一个**，
    skrf 显式补共轭项 res_k/(s−p_k) + conj(res_k)/(s−conj(p_k))；
    外加 constant_coeff[i·n+j]（macromodel 内核固定 fit_proportional=False，
    比例项恒 0）。
    自证：``macromodel_bridge`` 会用 D12 FSV 复算并与 fit_macromodel 上报的
    逐响应 gdm_mean 对拍（见返回值 ``reconstruction_verified``）。
    """
    n_ports = int(fit_result["n_ports"])
    freq = np.asarray(fit_result["freq_hz"], dtype=float)
    poles = np.array([complex(p[0], p[1]) for p in fit_result["poles_rad_s"]], dtype=complex)
    flat_const = fit_result["constant_coeff"]
    const = np.array([complex(v[0], v[1]) for v in flat_const], dtype=complex)
    s = np.zeros((freq.size, n_ports, n_ports), dtype=complex)
    w = 2j * np.pi * freq
    for i in range(n_ports):
        for j in range(n_ports):
            res = np.array(
                [complex(v[0], v[1]) for v in fit_result["residues"][i * n_ports + j]],
                dtype=complex,
            )
            acc = np.zeros(freq.size, dtype=complex)
            for k in range(poles.size):
                acc = acc + res[k] / (w - poles[k])
                if poles[k].imag != 0.0:  # skrf：共轭极点只存一个，显式补共轭项
                    acc = acc + np.conjugate(res[k]) / (w - np.conjugate(poles[k]))
            s[:, i, j] = acc + const[i * n_ports + j]
    return s


def _fsv_from_arrays(freq: np.ndarray, s_a: np.ndarray, s_b: np.ndarray, n_ports: int) -> dict[str, Any]:
    """逐响应 dB-FSV 摘要（与 core/macromodel._fsv_section 同口径，供对拍）。"""
    per: dict[str, float] = {}
    for i in range(n_ports):
        for j in range(n_ports):
            ra = 20.0 * np.log10(np.maximum(np.abs(s_a[:, i, j]), _DB_FLOOR))
            rb = 20.0 * np.log10(np.maximum(np.abs(s_b[:, i, j]), _DB_FLOOR))
            r = fsv(freq, ra, freq, rb)
            per[f"s{i + 1}{j + 1}"] = float(r["gdm_mean"])
    return per


#: branchline 宏模型桥的缺省定阶（2 实极点 + 4 复极点，共 6）。
#: 依据：四段线 branchline 闭式网络的每响应有理阶 ~4，(2,4) 实测
#: RMS −109.9dB 且严格无源（σ=0.9931，不触发 enforce）。低于此阶
#: （core.macromodel 默认阶梯首格 (1,2)，3 极点）虽以 −42dB 过 RMS 阈，
#: 但贴无源性边界（σ=1.0009）触发 passivity_enforce，实测劣化到
#: −34.5dB / FSV=F（macromodel docstring 已登记的 enforce 劣化行为）。
BRANCHLINE_MACROMODEL_ORDER: list[tuple[int, int]] = [(2, 4)]


def macromodel_bridge(
    snp_path: str | Path,
    *,
    order_ladder: list[tuple[int, int]] | None = None,
    rms_threshold_db: float = -40.0,
    **fit_overrides: Any,
) -> dict[str, Any]:
    """D13 宏模型桥：.sNp → fit_macromodel → 模型 S 重建 → 对拍自证。

    定阶：缺省 :data:`BRANCHLINE_MACROMODEL_ORDER`（branchline 锚口径）；
    其他器件族显式传 ``order_ladder``（交 fit_macromodel 的确定性阶梯）。

    返回 fit_macromodel 的完整结果外加：
    - ``model_network``：重建模型 S 的 skrf.Network（供级联替身）；
    - ``reconstruction_gdm``：重建模型 vs 原始的逐响应 gdm_mean；
    - ``reconstruction_verified``：与 fit_macromodel 上报 fsv.gdm_mean 的
      最大绝对偏差 ≤ 1e-9（钉死重建与 skrf 口径一致）。
    """
    request = request_from_touchstone(snp_path)
    request["rms_threshold_db"] = float(rms_threshold_db)
    ladder = order_ladder if order_ladder is not None else BRANCHLINE_MACROMODEL_ORDER
    request["order_ladder"] = [list(x) for x in ladder]
    request.update(fit_overrides)
    from rfauto.core.macromodel import fit_macromodel

    fit = fit_macromodel(request)
    s_model = model_s_from_fit(fit)
    freq = np.asarray(fit["freq_hz"], dtype=float)
    z0 = fit["z0_ohm"]
    z0_vec = z0 if isinstance(z0, list) else [float(z0)] * fit["n_ports"]
    network = skrf.Network(
        frequency=skrf.Frequency.from_f(freq, unit="Hz"), s=s_model, z0=z0_vec, name="macromodel",
    )
    reported = {k: v["gdm_mean"] for k, v in fit["fsv"]["per_response"].items()}
    # fit_macromodel 未回传原始 S 矩阵，用 request 里的原始 S 复算对拍
    s_orig = _request_s_array(request, fit["n_ports"])
    recon = _fsv_from_arrays(freq, s_orig, s_model, fit["n_ports"])
    max_dev = max(abs(recon[k] - reported[k]) for k in reported)
    fit["model_network"] = network
    fit["reconstruction_gdm"] = recon
    fit["reconstruction_max_dev"] = float(max_dev)
    fit["reconstruction_verified"] = bool(max_dev <= 1e-9)
    return fit


def _request_s_array(request: dict[str, Any], n_ports: int) -> np.ndarray:
    """把 request["s"]（[re,im] 嵌套）还原为复数数组。"""
    raw = np.asarray(request["s"], dtype=float)
    freq_n = raw.shape[0]
    s = np.zeros((freq_n, n_ports, n_ports), dtype=complex)
    if raw.ndim == 4 and raw.shape[-1] == 2:
        s = raw[..., 0] + 1j * raw[..., 1]
    elif raw.ndim == 3 and raw.shape[-1] == 2:  # [nf][n*n][2] 扁平
        s = (raw[..., 0] + 1j * raw[..., 1]).reshape(freq_n, n_ports, n_ports)
    else:
        raise ValueError(f"无法识别的 request['s'] 形状: {raw.shape}")
    return s


# --------------------------------------------------------------------------- #
# 6. 反标注一致性
# --------------------------------------------------------------------------- #

#: branchline 反标注规则（ADS 电路值 → EM 变量）。
#: 名义参考取 openems_templates branchline 默认（arm_len 20.5 / series_w 1.87 /
#: shunt_w 1.11 mm）与级联 TLIN 名义值（35.355Ω 串联臂 / 50Ω 并联臂 / 90°）。
BRANCHLINE_BACK_ANNOTATION_RULES: list[dict[str, Any]] = [
    {
        "ads_component": "series_line_z_ohm",
        "hfss_variable": "series_w_mm",
        "transform": "inverse_linear",  # Z 越高线越窄：W ∝ 1/Z
        "reference": {"series_line_z_ohm": 50.0 / math.sqrt(2.0), "series_w_mm": 1.87},
    },
    {
        "ads_component": "shunt_line_z_ohm",
        "hfss_variable": "shunt_w_mm",
        "transform": "inverse_linear",
        "reference": {"shunt_line_z_ohm": 50.0, "shunt_w_mm": 1.11},
    },
    {
        "ads_component": "line_theta_deg",
        "hfss_variable": "arm_len_mm",
        "transform": "linear",  # 电长度 ∝ 臂长
        "reference": {"line_theta_deg": 90.0, "arm_len_mm": 20.5},
    },
]


def _closed_form_transform(ads_value: float, transform: str, reference: dict[str, Any]) -> float:
    """BackAnnotator 变换的闭式期望值（linear / inverse_linear）。"""
    ref_ads, ref_hfss = reference.values()
    if transform == "linear":
        return ads_value * (ref_hfss / ref_ads)
    if transform == "inverse_linear":
        return ref_ads * ref_hfss / ads_value
    raise ValueError(f"未知变换类型: {transform!r}")


def _closed_form_inverse(hfss_value: float, transform: str, reference: dict[str, Any]) -> float:
    """闭式正变换（hfss → ads），供往返恢复。"""
    ref_ads, ref_hfss = reference.values()
    if transform == "linear":
        return hfss_value * (ref_ads / ref_hfss)
    if transform == "inverse_linear":
        return ref_ads * ref_hfss / hfss_value
    raise ValueError(f"未知变换类型: {transform!r}")


def check_back_annotation_consistency(
    rules: list[dict[str, Any]] | None = None,
    *,
    rtol: float = BACK_ANNOTATION_RTOL,
) -> dict[str, Any]:
    """反标注一致性：闭式期望对拍 + 往返恢复，逐规则量化。

    一致性定义（本锚口径）：对每条规则，
    (a) BackAnnotator 反标值 = 闭式期望值（相对误差 ≤ rtol）；
    (b) 闭式正变换作用于反标值恢复原 ADS 值（相对误差 ≤ rtol）。
    """
    from rfauto.linkage.back_annotation import BackAnnotator

    rules = rules if rules is not None else BRANCHLINE_BACK_ANNOTATION_RULES
    # 规则必须装进 BackAnnotator 的映射表才会被 ads_to_hfss_params 消费
    # （其 mapping 键 = ads_component 名，与 DEFAULT_MAPPING 同约定）。
    annotator = BackAnnotator(mapping={r["ads_component"]: r for r in rules})
    per_rule: dict[str, Any] = {}
    consistent = True
    for rule in rules:
        key = rule["ads_component"]
        ref = rule["reference"]
        ref_ads = next(iter(ref.values()))
        samples = [ref_ads, ref_ads * 1.05, ref_ads * 0.9]
        rows = []
        rule_ok = True
        for v in samples:
            got = annotator.ads_to_hfss_params({key: v})
            hfss_var = rule["hfss_variable"]
            if hfss_var not in got:
                rows.append({"ads_value": v, "error": "反标未产出目标变量"})
                rule_ok = False
                continue
            got_val = float(got[hfss_var])
            expect = _closed_form_transform(v, rule["transform"], ref)
            recovered = _closed_form_inverse(got_val, rule["transform"], ref)
            err = abs(got_val - expect) / abs(expect)
            rt_err = abs(recovered - v) / abs(v)
            ok = err <= rtol and rt_err <= rtol
            rule_ok = rule_ok and ok
            rows.append({
                "ads_value": float(v), "back_annotated": got_val,
                "closed_form": expect, "rel_err": float(err),
                "round_trip_value": float(recovered), "round_trip_rel_err": float(rt_err),
                "ok": bool(ok),
            })
        consistent = consistent and rule_ok
        per_rule[key] = {"hfss_variable": rule["hfss_variable"], "transform": rule["transform"], "ok": bool(rule_ok), "samples": rows}
    return {"consistent": bool(consistent), "rules": per_rule, "rtol": rtol}


# --------------------------------------------------------------------------- #
# 7. 端到端编排
# --------------------------------------------------------------------------- #

def run_field_circuit_anchor(
    snp_path: str | Path,
    out_dir: str | Path,
    *,
    f0_hz: float = DEFAULT_F0_HZ,
    theta_in_deg: float = DEFAULT_THETA_IN_DEG,
    theta_out_deg: float = DEFAULT_THETA_OUT_DEG,
    z_line: float = DEFAULT_Z_LINE,
    z0: float = 50.0,
    ads_dir: str | Path | None = None,
    ads_runner: Callable[[Path], dict[str, Any]] | None = None,
    fsv_params: tuple[str, ...] = ("S11", "S21"),
    with_macromodel: bool = True,
    back_annotation_rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """端到端回归锚：EM Touchstone → ADS 级联 vs skrf 级联 → FSV ≥VG
    → D13 宏模型桥 → 反标注一致性。

    返回 JSON 原生 summary 并写 ``<out_dir>/anchor_report.json``。
    ``ok`` = ADS 段成功 且 FSV ≥VG 且 宏模型桥通过 且 反标注一致；
    任一段失败如实降级记录（不掩盖、不抛出，锚是裁判不是业务主路径）。
    """
    snp_path = Path(snp_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {
        "source": {"snp_path": str(snp_path), "f0_hz": float(f0_hz)},
        "cascade_params": {
            "theta_in_deg": float(theta_in_deg),
            "theta_out_deg": float(theta_out_deg),
            "z_line": float(z_line),
        },
    }
    ok = snp_path.exists()
    if not ok:
        summary["source"]["error"] = f"Touchstone 不存在: {snp_path}"

    reference_net = None
    if ok:
        reference_net = skrf_reference_cascade(
            snp_path, f0_hz=f0_hz, theta_in_deg=theta_in_deg,
            theta_out_deg=theta_out_deg, z_line=z_line,
        )
        summary["reference"] = {
            "n_points": int(reference_net.f.size),
            "f_min_hz": float(reference_net.f[0]),
            "f_max_hz": float(reference_net.f[-1]),
        }

    # --- ADS 级联段 ---
    ads_ok = False
    if ok:
        try:
            ads = run_ads_cascade(
                snp_path, out_dir, f0_hz=f0_hz, theta_in_deg=theta_in_deg,
                theta_out_deg=theta_out_deg, z_line=z_line, ads_dir=ads_dir,
                ads_runner=ads_runner,
            )
            ads_net = ads["network"]
            ads_ok = True
            summary["ads"] = {
                "status": "ok",
                "netlist": str(ads["netlist"]),
                "n_points": int(ads_net.f.size),
                "sim_time_s": float(ads["payload"].get("_sim_time_s", float("nan"))),
            }
        except Exception as exc:
            # 观测性 best-effort：把求解器 stdout/stderr 尾巴带进错误串，
            # 许可/语法类失败的正文（如 "Linear features are not licensed"）可溯源。
            det = getattr(exc, "details", None)
            tail = ""
            if isinstance(det, dict):
                tail = str(det.get("stdout") or det.get("stderr") or "")[-400:]
            summary["ads"] = {
                "status": "error",
                "error": f"{type(exc).__name__}: {exc} {tail}".strip(),
            }
            ok = False
    else:
        summary["ads"] = {"status": "skipped"}

    # --- FSV 裁判段 ---
    if ads_ok and reference_net is not None:
        try:
            report = fsv_cascade_report(
                ads_net, reference_net, params=fsv_params,
            )
            summary["fsv"] = report
            ok = ok and report["at_least_vg"] and report["phase_consistent"] is not False
        except Exception as exc:
            summary["fsv"] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            ok = False
    else:
        summary["fsv"] = {"status": "skipped"}

    # --- D13 宏模型桥 ---
    if ok and with_macromodel:
        try:
            fit = macromodel_bridge(snp_path)
            model_net = fit.pop("model_network")
            summary["macromodel"] = {
                "ok": bool(fit["ok"]),
                "rms_db_final": fit["fit"]["rms_db_final"],
                "worst_gdm_grade": fit["fsv"]["worst_gdm_grade"],
                "passive_in_band": fit["passivity"]["after"]["passive_in_band"],
                "reconstruction_verified": fit["reconstruction_verified"],
                "reconstruction_max_dev": fit["reconstruction_max_dev"],
                "n_poles_total": fit["order"]["n_poles_total"],
            }
            model_cascade = compose_reference_cascade(
                model_net, f0_hz=f0_hz, theta_in_deg=theta_in_deg,
                theta_out_deg=theta_out_deg, z_line=z_line,
            )
            mm_report = fsv_cascade_report(model_cascade, reference_net, params=fsv_params)
            summary["macromodel"]["cascade_fsv"] = {
                k: v for k, v in mm_report.items() if k != "params"
            }
            summary["macromodel"]["cascade_params"] = {
                k: {"gdm_mean": v["gdm_mean"], "gdm_grade": v["gdm_grade"]}
                for k, v in mm_report["params"].items()
            }
            ok = (
                ok and bool(fit["ok"]) and bool(fit["reconstruction_verified"])
                and mm_report["at_least_vg"] and mm_report["phase_consistent"] is not False
            )
        except Exception as exc:
            summary["macromodel"] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
            ok = False
    elif not with_macromodel:
        summary["macromodel"] = {"status": "skipped"}

    # --- 反标注一致性 ---
    try:
        ba = check_back_annotation_consistency(back_annotation_rules)
        summary["back_annotation"] = ba
        ok = ok and ba["consistent"]
    except Exception as exc:
        summary["back_annotation"] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
        ok = False

    summary["ok"] = bool(ok)
    report_path = out_dir / "anchor_report.json"
    report_path.write_text(
        json.dumps(_jsonable(summary), ensure_ascii=False, indent=2), encoding="utf-8",
    )
    logger.info("场路协同回归锚完成: ok=%s 报告=%s", ok, report_path)
    return summary


def _jsonable(value: Any) -> Any:
    """summary → JSON 原生（numpy 标量收敛）。"""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, np.floating):
        v = float(value)
        return None if not math.isfinite(v) else v
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value
