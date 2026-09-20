"""C14 有源链路 ADS 通道：匹配网络 EM S2P × 器件 S2P 联合链 + load-pull 网表。

方案依据:
    "LNA/PA 匹配网络 EM 提取+ADS 非线性/噪声协同（场-路：EM S 参数进 ADS
    电路层）；PA 验收含 ADS 负载牵引仿真口径（谐波平衡 load-pull，无需硬件）"

两段通道
--------
1. 匹配链（B 档, ADR-0009 已实证语法族）:
   匹配网络 Touchstone（真机用法 = HFSS/openEMS export_touchstone 产物）与
   器件 S2P 各作 SnP 块, 网表级首尾相连（Port P1 → SnP:MN → SnP:DEV →
   Port P2）, S_Param 控制器带 CalcNoise=yes（噪声协同口）。
   hpeesofsim 求解 → keysight.ads.dataset 探针 → payload → skrf 网络,
   与"手工口径"（skrf 级联 + core.active_chain 闭式增益）对拍。
   `Port:`/`SnP:` 语法与 field_circuit_anchor 同族（真机实证 `Term:` 不存在,
   不可用, 见 field_circuit_anchor docstring）。本模块模板已在真机
   hpeesofsim 650.shp 上通过 netlist parsing + flattening（
   license 门前最后一步, 真机冒烟证据存档）;
   求解本身被 license 拦截（"Linear features are not licensed / 0 tokens"）,
   真机对拍数字待许可恢复（skip-not-fail, 与 real_edt 同口径）。
2. load-pull 网表（谐波平衡口径）:
   `render_loadpull_netlist` 按 (f0, 功率, 复数负载 Z) 渲染单点 HB 网表,
   逐点扫 Z 由上层循环（避开 hpeesofsim 复数扫参语法风险）;
   `run_ads_loadpull_point` = 渲染 → hpeesofsim → `parse_hb_dataset` → 点结果
   （Pout/增益/基波相量）, `loadpull_point_closed_form` 给线性 S2P 器件的
   确定性参考（转换增益 GT(ΓS=0, ΓL)）, `compare_loadpull_point` 对拍。
   **HB/P_1Tone/复数 Z 语法已真机实证**（ADS 2027 hpeesofsim
   650.shp 真机实证, 输出数据集解析证据存档）, 三条修正:
   ① 复数端口阻抗写 ``Z=re+j*(im)``（官方 Term/P_1Tone 文档 "use 1+j*0 for
   complex"; 旧 ``Z=[re Ohm + im Ohm*im]`` 报 "syntax error, unexpected '['"）;
   ② P_1Tone 原理图件网表模型名是 ``Port``, 功率/频率参数带谐波索引
   ``P[1]=dbmtow(x) Freq[1]=f``（oalibs/rf/ads_sources/%P_1%Tone/itemdef.ael
   create_item netlistData="Port"; 旧 ``P_1Tone:SRC ... Power=`` 报 "instance
   of an undefined model `P_1Tone'"）, 且 P_1Tone 自带源阻抗, 不再并联 Port:P1;
   ③ HB 控制器基波/阶数写 ``Freq[1]=f Order[1]=n``（官方 HB Configuration -
   Frequencies "Name in Netlist"）; 孤儿 SweepPlan 删除。测量方程用
   ``aele name=expr; ...``（MeasEqn itemdef 格式）, 数据集成块
   ``aele_N.HB1.HB``。线性 S2P 器件 HB 基波 Pout 与闭式 GT 一致到 1e-13 dB。

分层: linkage 层, 可 import adapters/core/同层 linkage; 不 import service 以上。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import skrf

from rfauto.adapters import ads_netlist
from rfauto.core.active_chain import DEFAULT_Z0, transducer_gain_db

logger = logging.getLogger(__name__)

_TPL_DIR = Path(__file__).resolve().parent / "templates" / "ads"
#: 匹配链 S 参数网表模板（ADR-0009 SnP/Port 语法族, 已实证）。
CHAIN_TEMPLATE = _TPL_DIR / "active_chain_sparam.net"
#: load-pull 谐波平衡网表模板（HB/Port 源/复数 Z/aele 语法真机实证）。
LOADPULL_TEMPLATE = _TPL_DIR / "loadpull_hb.net"

_UNIT_SCALE = {"GHz": 1e9, "MHz": 1e6, "kHz": 1e3, "Hz": 1.0}


def _snp_line(inst: str, n1: str, n2: str, snp_path: Path) -> str:
    """单条 SnP 网表行（2 端口, ADR-0009 语法, 每语句独占一行）。"""
    return (
        f"SnP:{inst}  {n1} {n2} NumPorts=2 File=\"{snp_path.resolve()}\" "
        f"Type=\"touchstone\" InterpMode=\"linear\" InterpDom=\"\" "
        f"ExtrapMode=\"constant\" Temp=27.0 CheckPassivity=0"
    )


def _read_snp_meta_checked(snp_path: Path, name: str) -> dict[str, Any]:
    """读 Touchstone 元信息并断言 2 端口（链路两侧都必须是 2 端口）。"""
    meta = ads_netlist.snp_meta_for_netlist(snp_path)
    if meta["n_ports"] != 2:
        raise ValueError(f"{name} 期望 2 端口 Touchstone, 得到 {meta['n_ports']} 端口: {snp_path}")
    return meta


def render_chain_netlist(
    match_snp: str | Path,
    device_snp: str | Path,
    output_path: str | Path,
    *,
    frequency_unit: str = "GHz",
    npoints: int | None = None,
    z0: float = DEFAULT_Z0,
    template_path: str | Path | None = None,
) -> Path:
    """渲染 匹配网络×器件 联合链 ADS S 参数网表。

    频段/点数: 默认取两份 Touchstone 频段的交集（无交集 ValueError）,
    npoints 缺省取两者较小值（ADS SnP 线性插值, 语义与导出口径一致）。
    契约: 两侧都必须是 2 端口; 模板占位符全量填充, 无 BOM、纯 ASCII。
    """
    match_snp = Path(match_snp)
    device_snp = Path(device_snp)
    output_path = Path(output_path)
    tpl = Path(template_path) if template_path else CHAIN_TEMPLATE
    if not tpl.exists():
        raise FileNotFoundError(f"网表模板不存在: {tpl}")
    m_meta = _read_snp_meta_checked(match_snp, "匹配网络")
    d_meta = _read_snp_meta_checked(device_snp, "器件")
    f_lo = max(m_meta["fstart_hz"], d_meta["fstart_hz"])
    f_hi = min(m_meta["fstop_hz"], d_meta["fstop_hz"])
    if f_lo >= f_hi:
        raise ValueError(
            f"两侧 Touchstone 频段无交集: 匹配 [{m_meta['fstart_hz']:.3g},{m_meta['fstop_hz']:.3g}]"
            f" vs 器件 [{d_meta['fstart_hz']:.3g},{d_meta['fstop_hz']:.3g}]"
        )
    if npoints is None:
        npoints = min(m_meta["npoints"], d_meta["npoints"])
    scale = _UNIT_SCALE[frequency_unit]

    text = tpl.read_text(encoding="utf-8")
    for key, val in {
        "{{FSTART}}": f"{f_lo / scale:g}",
        "{{FSTOP}}": f"{f_hi / scale:g}",
        "{{NPOINTS}}": str(npoints),
        "{{FREQ_UNIT}}": frequency_unit,
        "{{Z0}}": f"{z0:g}",
        "{{SNP_MATCH}}": _snp_line("MN", "N_IN", "N_MID", match_snp),
        "{{SNP_DEVICE}}": _snp_line("DEV", "N_MID", "N_OUT", device_snp),
    }.items():
        text = text.replace(key, val)
    if "{{" in text:
        raise ValueError(f"模板占位符未全量填充: {tpl}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="ascii", errors="ignore")
    logger.info("有源链路网表已生成: %s", output_path)
    return output_path


def payload_to_network(payload: dict[str, Any]) -> skrf.Network:
    """ADS .ds 探针 payload → 2 端口 skrf.Network（链路 S 参数恢复）。

    端口定位: 优先按 port_names 找 P1/P2（数据集端口序 ≠ 网络端口序时
    纠偏, 与 field_circuit_anchor 同款）; 找不到时按数据集前两端口兜底。
    """
    freq = np.asarray(payload["frequency_hz"], dtype=float)
    s_map = payload["s"]
    names = [str(x) for x in payload.get("port_names") or []]
    if "P1" in names and "P2" in names:
        i1, i2 = names.index("P1"), names.index("P2")
    else:
        i1, i2 = 0, 1

    def _resp(a: int, b: int) -> np.ndarray:
        key = f"{a + 1}_{b + 1}"
        if key not in s_map:
            raise KeyError(f"ADS payload 缺少 S[{key}]（现有键: {sorted(s_map)}）")
        return np.array([complex(v[0], v[1]) for v in s_map[key]], dtype=complex)

    s = np.zeros((len(freq), 2, 2), dtype=complex)
    s[:, 0, 0] = _resp(i1, i1)
    s[:, 1, 0] = _resp(i2, i1)
    s[:, 0, 1] = _resp(i1, i2)
    s[:, 1, 1] = _resp(i2, i2)
    port_z = payload.get("port_z") or [[50.0, 0.0], [50.0, 0.0]]
    z0 = [float(complex(v[0], v[1]).real) for v in port_z[:2]] or [DEFAULT_Z0] * 2
    return skrf.Network(
        frequency=skrf.Frequency.from_f(freq, unit="Hz"), s=s, z0=z0, name="ads_chain",
    )


def run_ads_chain(
    match_snp: str | Path,
    device_snp: str | Path,
    out_dir: str | Path,
    *,
    ads_dir: str | Path | None = None,
    ads_runner: Callable[[Path], dict[str, Any]] | None = None,
    frequency_unit: str = "GHz",
    npoints: int | None = None,
    z0: float = DEFAULT_Z0,
) -> dict[str, Any]:
    """匹配链 B 档: 渲染网表 → hpeesofsim → .ds 探针 → payload。

    ``ads_runner(netlist_path) -> payload`` 可注入（离线回归只验管线,
    与 field_circuit_anchor 同款纪律）; 默认真机链 =
    ads_netlist.run_hpeesofsim + parse_dataset。
    失败时返回 {"status": "error", "error": ...}（观测性 best-effort,
    不抛出阻塞上层, 错误信息完整保留）。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    netlist = render_chain_netlist(
        match_snp, device_snp, out_dir / "chain_netlist.txt",
        frequency_unit=frequency_unit, npoints=npoints, z0=z0,
    )
    t0 = time.time()
    from rfauto.core.errors import SimulationFailedError

    try:
        if ads_runner is not None:
            payload = ads_runner(netlist)
        else:
            ads_netlist.run_hpeesofsim(netlist, ads_dir=ads_dir)
            payload = ads_netlist.parse_dataset(
                out_dir / "chain_netlist.txt.ds", ads_dir=ads_dir,
            )
    except (SimulationFailedError, FileNotFoundError) as exc:
        # 错误串附 stdout 尾巴（license 欠配等信息在 stdout 里,
        # 供上层 skip-not-fail 判定与诊断; best-effort 观测性）
        detail = ""
        if isinstance(exc, SimulationFailedError):
            stdout = str((exc.details or {}).get("stdout", ""))
            if stdout:
                detail = stdout[-500:]
        err = f"{exc}{('; ' + detail) if detail else ''}"
        logger.warning("ADS 链路仿真受阻: %s", err)
        return {
            "status": "error", "error": err,
            "netlist": str(netlist), "sim_time_s": round(time.time() - t0, 3),
        }
    return {
        "status": "ok", "netlist": str(netlist), "payload": payload,
        "sim_time_s": round(time.time() - t0, 3),
    }


def compare_chain_with_manual(
    ads_net: skrf.Network,
    manual_net: skrf.Network,
    *,
    tol_db: float = 0.1,
) -> dict[str, Any]:
    """ADS 链路 vs 手工口径（skrf 级联）的 dB 幅度对拍。

    返回各 S 参数最大 |ΔdB| 与判定（≤tol_db 判 consistent）。
    频轴不一致时取公共频段按**真最近邻**重采样（网表导出与 skrf 同源频轴时
    应恒等）。真机实证: ADS 数据集频率可比
    skrf 网格低 1 ulp（2.38e-7 Hz @2 GHz, 41 点中 22 点）, 旧 ``searchsorted``
    在此越位一格, 把逐频 1e-16 dB 的真差报成 斜率×步长 = 0.0236 dB（S21）;
    最近邻索引不受 ulp 噪声影响（#287 家族）。
    """
    f_ads = np.asarray(ads_net.f, dtype=float)
    f_man = np.asarray(manual_net.f, dtype=float)
    lo = max(f_ads.min(), f_man.min())
    hi = min(f_ads.max(), f_man.max())
    # 公共频段边界也按 ulp 容差放宽, 否则端点会因 1 ulp 之差被剔除
    eps = np.spacing(max(abs(lo), abs(hi), 1.0)) * 4
    mask = (f_man >= lo - eps) & (f_man <= hi + eps)
    f_common = f_man[mask]
    idx_ads = np.abs(f_ads[None, :] - f_common[:, None]).argmin(axis=1)
    per_param: dict[str, float] = {}
    for i in range(2):
        for j in range(2):
            a = 20.0 * np.log10(np.abs(ads_net.s[idx_ads, i, j]) + 1e-30)
            b = 20.0 * np.log10(np.abs(manual_net.s[mask, i, j]) + 1e-30)
            per_param[f"S{i + 1}{j + 1}_db"] = round(float(np.max(np.abs(a - b))), 12)
    max_dev = max(per_param.values())
    return {
        "per_param_max_abs_db": per_param,
        "max_abs_db": max_dev,
        "tol_db": tol_db,
        "consistent": bool(max_dev <= tol_db),
        "n_freq": len(f_common),
    }


def chain_manual_reference(
    match_snp: str | Path,
    device_snp: str | Path,
) -> tuple[skrf.Network, skrf.Network, skrf.Network]:
    """手工口径: 读两份 Touchstone → (匹配网络, 器件, skrf 级联网络)。

    级联用 skrf ``**`` 运算（与 ADS 网表级联物理同义、代码路径独立）。
    """
    match_net = skrf.Network(str(match_snp))
    device_net = skrf.Network(str(device_snp))
    return match_net, device_net, match_net ** device_net


def render_loadpull_netlist(
    device_snp: str | Path,
    output_path: str | Path,
    *,
    f0_hz: float,
    power_dbm: float,
    z_load: complex,
    harmonic_order: int = 5,
    z0: float = DEFAULT_Z0,
    frequency_unit: str = "GHz",
    template_path: str | Path | None = None,
) -> Path:
    """渲染单点谐波平衡 load-pull 网表（B 档逐点扫 Z, 上层循环）。

    语法已真机实证（见模块 docstring 第 2 节三条修正）; 渲染本身确定性、
    离线可测。负载阻抗按 ``re+j*(im)`` ADS 复数表达式注入（负虚部靠括号
    ``j*(-x)`` 保持可解析）, 同一表达式同时进 Port:P2 与 aele 测量方程。
    """
    device_snp = Path(device_snp)
    output_path = Path(output_path)
    tpl = Path(template_path) if template_path else LOADPULL_TEMPLATE
    if not tpl.exists():
        raise FileNotFoundError(f"网表模板不存在: {tpl}")
    _read_snp_meta_checked(device_snp, "器件")
    scale = _UNIT_SCALE[frequency_unit]
    z_load = complex(z_load)
    text = tpl.read_text(encoding="utf-8")
    for key, val in {
        "{{ORDER}}": str(harmonic_order),
        "{{F0}}": f"{f0_hz / scale:g}",
        "{{FREQ_UNIT}}": frequency_unit,
        "{{POWER_DBM}}": f"{power_dbm:g}",
        "{{Z0}}": f"{z0:g}",
        "{{Z_RE}}": f"{z_load.real:g}",
        "{{Z_IM}}": f"{z_load.imag:g}",
        "{{SNP_LINE}}": _snp_line("DEV", "N_IN", "N_OUT", device_snp),
    }.items():
        text = text.replace(key, val)
    if "{{" in text:
        raise ValueError(f"模板占位符未全量填充: {tpl}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="ascii", errors="ignore")
    logger.info("load-pull 网表已生成: %s (Z=%.3g%+.3gj)", output_path, z_load.real, z_load.imag)
    return output_path


def hb_payload_to_point(
    payload: dict[str, Any],
    *,
    z_load: complex,
    power_dbm: float,
    out_node: str = "N_OUT",
) -> dict[str, Any]:
    """HB 数据集 payload（parse_hb_dataset）→ 单点 load-pull 结果。

    优先取网表 ``aele`` 测量方程值（Pout_W/Pout_dBm/Gain_dB, ADS 自算）;
    同时按基波节点相量独立复算 ``P = ½·Re(V·conj(V/Z_L))``（确定性内核,
    与 ADS 侧互证; 二者差记 ``pout_self_check_db``）。基波 = ``mix == 1``
    的谐波行（0 为 DC）。
    """
    z_load = complex(z_load)
    harmonics = payload.get("harmonics") or []
    fund = next((h for h in harmonics if h.get("mix") == 1), None)
    if fund is None or out_node not in (fund.get("nodes") or {}):
        raise KeyError(
            f"HB payload 缺少基波 (mix=1) 节点 {out_node}（现有: "
            f"{[h.get('mix') for h in harmonics]} / {sorted((fund or {}).get('nodes', {}))}）"
        )
    v = fund["nodes"][out_node]
    v_out = complex(float(v[0]), float(v[1]))
    p_w_calc = 0.5 * (v_out * np.conj(v_out / z_load)).real
    p_dbm_calc = 10.0 * np.log10(max(p_w_calc, 1e-300) * 1e3)
    meas = payload.get("measurements") or {}
    p_dbm_ads = meas.get("Pout_dBm")
    p_dbm = float(p_dbm_ads) if isinstance(p_dbm_ads, (int, float)) else float(p_dbm_calc)
    p_w_ads = meas.get("Pout_W")
    p_w = float(p_w_ads) if isinstance(p_w_ads, (int, float)) else float(p_w_calc)
    gain_ads = meas.get("Gain_dB")
    gain_db = float(gain_ads) if isinstance(gain_ads, (int, float)) else p_dbm - power_dbm
    return {
        "f0_hz": float(fund.get("freq_hz", 0.0)),
        "power_dbm": power_dbm,
        "z_load": {"re": z_load.real, "im": z_load.imag},
        "v_out_fund": {"re": v_out.real, "im": v_out.imag},
        "pout_dbm": round(p_dbm, 9),
        "pout_w": round(p_w, 12),
        "gain_db": round(gain_db, 9),
        "pout_dbm_from_node": round(float(p_dbm_calc), 9),
        "pout_self_check_db": round(float(p_dbm - p_dbm_calc), 12),
        "n_harmonics": len(harmonics),
        "source": "aele" if isinstance(p_dbm_ads, (int, float)) else "node",
    }


def loadpull_point_closed_form(
    device_snp: str | Path,
    *,
    f0_hz: float,
    power_dbm: float,
    z_load: complex,
    z0: float = DEFAULT_Z0,
) -> dict[str, Any]:
    """线性 S2P 器件的单点 load-pull 确定性参考（HB 基波 ≡ 线性转换增益）。

    源 = 可用功率 power_dbm、内阻 z0（ΓS=0）; 负载 ΓL=(Z_L−z0)/(Z_L+z0);
    Pout = power_dbm + GT(ΓS=0, ΓL) dB。取最接近 f0 的频点（网表 SnP 线性
    插值, f0 落网格点时无插值误差）。
    """
    net = skrf.Network(str(device_snp))
    if net.nports != 2:
        raise ValueError(f"期望 2 端口 Touchstone, 得到 {net.nports}: {device_snp}")
    idx = int(np.argmin(np.abs(np.asarray(net.f) - f0_hz)))
    z_load = complex(z_load)
    gamma_l = (z_load - z0) / (z_load + z0)
    gt_db = transducer_gain_db(net.s[idx], 0.0, gamma_l)
    return {
        "f0_hz": float(net.f[idx]),
        "power_dbm": power_dbm,
        "z_load": {"re": z_load.real, "im": z_load.imag},
        "gamma_load": {"re": float(gamma_l.real), "im": float(gamma_l.imag)},
        "gt_db": round(float(gt_db), 9),
        "pout_dbm": round(float(power_dbm + gt_db), 9),
    }


def compare_loadpull_point(
    ads_point: dict[str, Any],
    ref_point: dict[str, Any],
    *,
    tol_db: float = 0.05,
) -> dict[str, Any]:
    """ADS HB 单点 Pout vs 确定性参考的 dB 对拍（≤tol_db 判 consistent）。"""
    delta = float(ads_point["pout_dbm"]) - float(ref_point["pout_dbm"])
    return {
        "pout_ads_dbm": float(ads_point["pout_dbm"]),
        "pout_ref_dbm": float(ref_point["pout_dbm"]),
        "delta_db": round(delta, 12),
        "abs_delta_db": round(abs(delta), 12),
        "tol_db": tol_db,
        "consistent": bool(abs(delta) <= tol_db),
    }


def run_ads_loadpull_point(
    device_snp: str | Path,
    out_dir: str | Path,
    *,
    f0_hz: float,
    power_dbm: float,
    z_load: complex,
    harmonic_order: int = 5,
    z0: float = DEFAULT_Z0,
    ads_dir: str | Path | None = None,
    ads_runner: Callable[[Path], dict[str, Any]] | None = None,
    netlist_name: str = "loadpull_point.txt",
) -> dict[str, Any]:
    """单点 HB load-pull B 档: 渲染网表 → hpeesofsim → parse_hb_dataset → 点结果。

    ``ads_runner(netlist_path) -> hb_payload`` 可注入（离线只验管线）; 默认
    真机链 = ads_netlist.run_hpeesofsim + parse_hb_dataset。失败返回
    {"status": "error", ...} 不抛出（与 run_ads_chain 同纪律）。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    z_load = complex(z_load)
    netlist = render_loadpull_netlist(
        device_snp, out_dir / netlist_name, f0_hz=f0_hz, power_dbm=power_dbm,
        z_load=z_load, harmonic_order=harmonic_order, z0=z0,
    )
    t0 = time.time()
    from rfauto.core.errors import SimulationFailedError

    try:
        if ads_runner is not None:
            payload = ads_runner(netlist)
        else:
            ads_netlist.run_hpeesofsim(netlist, ads_dir=ads_dir)
            payload = ads_netlist.parse_hb_dataset(
                out_dir / f"{netlist_name}.ds", ads_dir=ads_dir,
            )
        point = hb_payload_to_point(payload, z_load=z_load, power_dbm=power_dbm)
    except (SimulationFailedError, FileNotFoundError, KeyError) as exc:
        detail = ""
        if isinstance(exc, SimulationFailedError):
            stdout = str((exc.details or {}).get("stdout", ""))
            if stdout:
                detail = stdout[-500:]
        err = f"{exc}{('; ' + detail) if detail else ''}"
        logger.warning("ADS load-pull 单点仿真受阻: %s", err)
        return {
            "status": "error", "error": err, "netlist": str(netlist),
            "sim_time_s": round(time.time() - t0, 3),
        }
    return {
        "status": "ok", "netlist": str(netlist), "point": point,
        "sim_time_s": round(time.time() - t0, 3),
    }


def loadpull_point_reference(
    f0_hz: float,
    z_load: complex,
    device: Any,
    drive_dbm: float,
    z0: float = DEFAULT_Z0,
) -> dict[str, Any]:
    """单点 load-pull 的离线确定性参考（Cripps 内核, 与 ADS 点对点）。

    返回该负载点的功率/最优点距离/负载阻抗, 供 ADS HB 真机点对点对拍
    （真机通道恢复后无需改本函数）。
    """
    from rfauto.core.active_chain import load_pull_power_dbm

    gamma = (z_load - z0) / (z_load + z0)
    p_dbm = float(np.asarray(load_pull_power_dbm(gamma, device, f0_hz, z0)))
    return {
        "f0_hz": f0_hz,
        "z_load": {"re": round(z_load.real, 6), "im": round(z_load.imag, 6)},
        "gamma_load": {"re": round(gamma.real, 6), "im": round(gamma.imag, 6)},
        "power_dbm_cripps": round(p_dbm, 4),
        "drive_dbm": drive_dbm,
        "z0": z0,
    }


def chain_gain_at_f0(
    chain_net: skrf.Network,
    f0_hz: float,
    *,
    z0: float = DEFAULT_Z0,
) -> dict[str, Any]:
    """链路在 f0 的手工口径增益族（闭式内核 vs 链路 S 参数, 同源对比）。"""
    idx = int(np.argmin(np.abs(np.asarray(chain_net.f) - f0_hz)))
    s = chain_net.s[idx]
    s21_db = 20.0 * np.log10(abs(s[1, 0]) + 1e-30)
    gt_50 = transducer_gain_db(s, 0.0, 0.0)
    return {
        "f0_hz": float(chain_net.f[idx]),
        "s21_db": round(float(s21_db), 6),
        "gt_50ohm_db": round(gt_50, 6),
        "s11_mag": round(float(abs(s[0, 0])), 6),
    }
