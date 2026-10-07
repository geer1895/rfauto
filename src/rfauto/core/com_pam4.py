"""DR-1（round16）：COM 参数化与 PAM4 确定性内核（pychopmarg 包裹 + 纯闭式子集）。

定位
----
IEEE 802.3 Channel Operating Margin（COM）的参数化面：93A→802.3dj 多 preset、
L=4 PAM4 电平语义、fb/抽头 sweep。规格钉的子集（round16 DR-1）——COM 完整
实现是 L 级，本模块不做完整闭式重实现；路线 = **pychopmarg 包裹（数值权威）
+ 结果 schema 化**，外加不依赖可选包的纯闭式分项（电平/RLM/符号方差/分项
噪声→COM 换算），供锚定与负例。

实测口径（pychopmarg 3.1.2，本机 venv，预声明 provenance）
----------------------------------------------------------
- COMParams dataclass 43 字段（fb…z_pB）；**包内 preset（ieee_8023by/dj）与
  消费面错位**（df7⑥ 家族新形态）：C_d/L_s 数据类注解与 preset 都是平铺
  list[float]，但 sDie 消费 ``C_d[ix]``/``L_s[ix]`` 的**每端列表**（float 无
  len() → TypeError 实测）——本模块照消费面重建为 Tx/Rx 两行嵌套；
- R_d 须 Tx/Rx 两元（gamma1_Tx/gamma1_Rx 索引 _gamma1[0]/[1]）；
- M ∈ [32, 256]（构造期 check_range；M=16 ValueError 实测）；
- Tx FFE 组合 = arange(min, max+step, step) 直积，恒先验插入零向量组合，再过
  ``(1-|v|.sum()) >= c0_min`` 滤波——**钉抽头（min=max=v）必须同时 c0_min=0**
  （探针实测：c0_min=0.5 时钉组合 [0,1,0] 被滤掉只剩零向量 = 静默"无 FFE"），
  且钉向量须 |v|.sum() ≤ 1（c0_min=0 时滤波式的可行域）；
- g_DC/g_DC2 全档直积扫描分钟级（df7⑥）——粗档旋钮 g_dc_stride/g_dc2_stride；
- ``opt_eq(do_opt_eq=False)`` 的 tx_taps 实参实际不进频响（3.1.2 固定走
  _tx_combs[0]=零向量）——抽头扫描不走该路线，改"重建参数钉抽头+整体优化"
  路线（每点确定性、秒级）；
- COM 主值 = 20·log10(As/Ani)（calc_noise 终算，此时 rx_taps 已按主抽头归一）；
  fom_rslts 的分项方差（varTx/varISI/varJ/varXT/varN，93A-31/32/36）是优化
  时刻值——**FOM 语义随 opt_mode 变**：PRZF（93A 规格路线，本模块缺省）时
  fom_db = 93A-36、与分项复算恒等；MMSE（包缺省）时 fom_db 是 MMSE 选择
  目标、与 93A-36 分解不等（实测差数 dB）——schema 两列并报不自证一致。
- **com_db_from_terms 是优化 FOM 复算、非标准 final-COM（审查 C2-1）**：
  93A-36 case-1 口径缺 DER/Ani/BER 目标因子，final-COM 以 pychopmarg COM
  调用返回值为权威（run_com 的 com_db 列）——函数 docstring 同口径。

诚实边界
--------
- COM 数值权威 = pychopmarg 内核，本模块不自证精确值；
- **802-COM 公开测试向量对照面 UNVERIFIED**（Matlab 参考实现为外部资源，
  本批未对照；DR-1 完整验收"偏差 <0.1 dB"是后续项）——全部结果 schema 带
  verification 标记；
- 802.3ck preset 未随包发布（包内只有 by/dj）——注册表如实不含 3ck，
  不凭记忆造数值（规则 7 / 引用纪律）；
- .s32p 直通路线在 3.1.2 有缺陷（str 无 .exists() → AttributeError）——
  只走 s4p 字典路线。

数值只在确定性内核（规则 7）：本模块全部数字出自 numpy/pychopmarg 确定性
计算；纯闭式分项（93A-29/31/32/36 口径）逐条带公式号。
"""

from __future__ import annotations

import dataclasses
import importlib.metadata
import math
import time
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np

#: 结果 schema 版本
COM_PAM4_SCHEMA_VERSION = "1.0"

#: 对照面标记（诚实边界：802-COM 公开测试向量对照未做）
UNVERIFIED_VS_802COM = "unverified_vs_802com_vectors"

#: 源通道带宽下限系数：f_max ≥ fb×该值才受理（否则采样率不足，显式拒绝）
MIN_COVERAGE_FACTOR = 1.0

#: 随包发布的 preset 名（3.1.2 实测只有这两个；802.3ck 未随包 → 不注册）
AVAILABLE_PRESETS: tuple[str, ...] = ("8023by", "8023dj")

#: PAM4 Gray 编码映射：电平序号（升序 0..3）→ 2 bit 码字 (MSB, LSB)。
#: 相邻电平恰差 1 bit（00↔01↔11↔10）——PAM4 Gray 语义。
PAM4_GRAY_MAP: tuple[tuple[int, int], ...] = ((0, 0), (0, 1), (1, 1), (1, 0))


# ---------------------------------------------------------------------------
# PAM4 电平语义（纯闭式，无可选依赖）
# ---------------------------------------------------------------------------

def pam4_levels(swing: float = 1.0) -> np.ndarray:
    """PAM4 理想 4 电平（升序）：±1/3、±1 × swing/2 外摆。

    swing = 最外电平峰峰摆幅；理想等间距电平的三段眼高各 = swing/3。
    """
    if not (swing > 0.0):
        raise ValueError(f"swing 须为正，得 {swing!r}")
    return np.array([-1.0, -1.0 / 3.0, 1.0 / 3.0, 1.0]) * (swing / 2.0)


def _validate_pam4_levels(levels: np.ndarray) -> np.ndarray:
    lv = np.asarray(levels, dtype=float)
    if lv.shape != (4,):
        raise ValueError(f"PAM4 电平须为 4 个（升序），得 shape {lv.shape}")
    if not np.all(np.diff(lv) > 0.0):
        raise ValueError(f"PAM4 电平须严格升序，得 {lv.tolist()}")
    return lv


def pam4_eye_heights(levels: np.ndarray) -> np.ndarray:
    """PAM4 三段眼高（相邻电平间距，升序）。"""
    lv = _validate_pam4_levels(levels)
    return np.diff(lv)


def pam4_rlm(levels: np.ndarray) -> float:
    """电平分离失配比 RLM = min(眼高) / 平均眼高（802.3cd 口径）。

    平均眼高 = (最高电平 − 最低电平)/3；理想等间距电平 → 1.0；
    不等间距 → <1.0（min ≤ mean 恒成立）。
    """
    lv = _validate_pam4_levels(levels)
    seps = np.diff(lv)
    avg = (lv[-1] - lv[0]) / 3.0
    if not (avg > 0.0):
        raise ValueError(f"平均眼高非正（{avg!r}），无法定义 RLM")
    return float(seps.min() / avg)


def pam4_symbol_variance(n_levels: int) -> float:
    """等概率 L 电平符号方差（93A-29 口径）：(L²−1)/(3(L−1)²)。

    L=2（NRZ）→ 1.0；L=4（PAM4）→ 5/9。L<2 无定义。
    """
    if n_levels < 2:
        raise ValueError(f"电平数 L 须 ≥2，得 {n_levels}")
    return (n_levels**2 - 1.0) / (3.0 * (n_levels - 1.0) ** 2)


def gray_adjacency_ok(mapping: tuple[tuple[int, int], ...]) -> bool:
    """校验 Gray 映射：相邻电平码字恰差 1 bit（逐对异或 popcount=1）。"""
    if len(mapping) < 2:
        return False
    for a, b in pairwise(mapping):
        diff = (a[0] ^ b[0]) + (a[1] ^ b[1])
        if diff != 1:
            return False
    return True


def com_db_from_terms(as_v: float, var_tx: float, var_isi: float, var_j: float,
                      var_xt: float, var_n: float) -> float:
    """分项噪声方差 → 优化 FOM（dB）：20·log10(As/√Σvar)（93A-36 口径）。

    As = 眼信号幅值（V）；var_* = Tx 噪声/ISI/抖动/串扰/热噪声方差（V²）。
    纯换算，不自证任何分项的物理来源。

    口径注记（审查 C2-1，**非标准 final-COM**）：本函数是 pychopmarg
    均衡**优化循环 FOM**（fom_rslts["FOM"]，93A-36 case-1）的闭式复算，
    不是 IEEE 802.3 final-COM——缺 DER（确定性抖动半展宽）、Ani（干扰
    噪声）与 BER 目标因子（ER/fBER 换算）三项；final-COM 数值以
    pychopmarg COM 对象调用返回值为权威（本模块 run_com 结果 schema 的
    ``com_db`` 列），``fom_db_recalc``（本函数）与 ``com_db`` 两列并报、
    不自证一致（MMSE 模式下两者天然不等，见模块 docstring FOM 语义节）。
    """
    if not (as_v > 0.0):
        raise ValueError(f"信号幅值 As 须为正，得 {as_v!r}")
    var_terms = (var_tx, var_isi, var_j, var_xt, var_n)
    if any(v < 0.0 for v in var_terms):
        raise ValueError(f"噪声方差须非负，得 {var_terms}")
    total = math.fsum(var_terms)
    if not (total > 0.0):
        raise ValueError("噪声方差总和为零，COM 无定义")
    return float(20.0 * math.log10(as_v / math.sqrt(total)))


# ---------------------------------------------------------------------------
# 预设参数化（pychopmarg 3.1.2 schema 安全重建；可选依赖惰性 import）
# ---------------------------------------------------------------------------

def pychopmarg_version() -> str | None:
    """已装 pychopmarg 版本号；缺装/破损装 → None（如实，不猜）。"""
    try:
        return importlib.metadata.version("pychopmarg")
    except Exception:  # 可选依赖缺装/破损装（import 期任意异常，AU-3① 口径）
        return None


def _load_preset(preset: str) -> Any:
    if preset not in AVAILABLE_PRESETS:
        raise ValueError(
            f"未知 preset {preset!r}；随包可用 = {AVAILABLE_PRESETS}"
            f"（802.3ck 未随 pychopmarg 3.1.x 发布，不凭记忆造数值）")
    mod = importlib.import_module(f"pychopmarg.config.ieee_{preset}")
    return getattr(mod, f"IEEE_{preset}")


def pam4_com_params(
    preset: str = "8023dj",
    *,
    fb_gbaud: float | None = None,
    g_dc_stride: int = 1,
    g_dc2_stride: int = 1,
    tx_taps_step: float | None = None,
    pinned_taps: tuple[float, ...] | None = None,
) -> tuple[Any, str]:
    """按随包 preset 值重建 COMParams（照 3.1.2 **消费面**嵌套格式），附 provenance。

    旋钮（粗档，df7⑥：全档直积扫描分钟级不可用）：
    - fb_gbaud：覆盖波特率（sweep 用）；
    - g_dc_stride / g_dc2_stride：CTLE 档等距抽稀（≥1）；
    - tx_taps_step：Tx FFE 步进覆盖（更粗网格）；
    - pinned_taps：钉死 Tx FFE 全部抽头（min=max=v、c0_min=0）——抽头扫描
      路线；向量须 |v|.sum() ≤ 1（COM 归一可行域），长度须 = preset 抽头数。

    Returns:
        (COMParams, provenance_note)。

    Raises:
        ValueError: preset 未注册 / 旋钮非法 / 钉向量非法。
        Exception: pychopmarg 缺装或 preset 值本身过不了 3.1.2 构造期校验
            （如实上抛，不静默降级——参数面错误不是运行面错误）。
    """
    if g_dc_stride < 1 or g_dc2_stride < 1:
        raise ValueError(
            f"g_dc_stride/g_dc2_stride 须 ≥1，得 ({g_dc_stride}, {g_dc2_stride})")
    src = _load_preset(preset)
    n_taps = len(src.tx_taps_min)
    updates: dict[str, Any] = {}
    if fb_gbaud is not None:
        if not (fb_gbaud > 0.0):
            raise ValueError(f"fb_gbaud 须为正，得 {fb_gbaud!r}")
        updates["fb"] = float(fb_gbaud)
    updates["g_DC"] = list(src.g_DC)[::g_dc_stride]
    updates["g_DC2"] = list(src.g_DC2)[::g_dc2_stride]
    if tx_taps_step is not None:
        if not (tx_taps_step > 0.0):
            raise ValueError(f"tx_taps_step 须为正，得 {tx_taps_step!r}")
        updates["tx_taps_step"] = [float(tx_taps_step)] * n_taps
    if pinned_taps is not None:
        pins = [float(v) for v in pinned_taps]
        if len(pins) != n_taps:
            raise ValueError(
                f"pinned_taps 长度须 = preset 抽头数 {n_taps}，得 {len(pins)}")
        if sum(abs(v) for v in pins) > 1.0 + 1e-9:
            raise ValueError(
                f"pinned_taps 的 |v|.sum() 须 ≤1（c0_min=0 可行域），得 {pins}")
        # step 须 >0（mk_combs：step=0 → 恒 [0.0]，与钉值无关——实测口径）
        updates["tx_taps_min"] = list(pins)
        updates["tx_taps_max"] = list(pins)
        updates["tx_taps_step"] = [0.1] * n_taps
        updates["c0_min"] = 0.0
    # 平铺 → Tx/Rx 嵌套（sDie 消费面要求：C_d[ix]/L_s[ix] 须可 len() 且可
    # /1e9 → 二维 numpy 数组；preset 平铺值两端复制，provenance 留痕）
    updates["C_d"] = np.array([list(src.C_d), list(src.C_d)], dtype=float)
    updates["L_s"] = np.array([list(src.L_s), list(src.L_s)], dtype=float)
    updates["C_b"] = [src.C_b[0], src.C_b[0]]
    updates["C_p"] = [src.C_p[0], src.C_p[0]]
    r_d = np.asarray(src.R_d, dtype=float).ravel()
    updates["R_d"] = np.array([r_d[0], r_d[-1]])
    params = dataclasses.replace(src, **updates)
    note = (
        f"preset={preset}（随包值重建；C_d/L_s 平铺→Tx/Rx 嵌套两端复制，"
        f"C_b/C_p/R_d 同法两元）；knobs(fb={fb_gbaud}, g_dc_stride={g_dc_stride},"
        f" g_dc2_stride={g_dc2_stride}, tx_taps_step={tx_taps_step},"
        f" pinned_taps={pinned_taps})；pychopmarg={pychopmarg_version()}；"
        f"{UNVERIFIED_VS_802COM}")
    return params, note


# ---------------------------------------------------------------------------
# COM 运行包裹（结果 schema 化；校验错误显式抛，运行面错误如实降级）
# ---------------------------------------------------------------------------

def _validate_s4p(path: Path) -> tuple[Any, dict[str, Any]]:
    """存在性/类型/端口数校验 → (skrf.Network, 元信息)。非法即显式抛。"""
    if not path.is_file():
        raise FileNotFoundError(f"通道文件不存在: {path}")
    if path.suffix.lower() != ".s4p":
        raise ValueError(
            f"只受理 .s4p（3.1.2 的 .s32p 直通路线有缺陷，见模块 docstring）: {path}")
    import skrf  # 惰性（#105 惯例）

    net = skrf.Network(str(path))
    if net.nports != 4:
        raise ValueError(
            f"{path.name} 为 {net.nports} 端口，COM 定义在 4 端口差分测量")
    return net, {"path": str(path), "n_ports": 4,
                 "f_min_hz": float(net.f[0]), "f_max_hz": float(net.f[-1]),
                 "n_freqs": int(net.f.size)}


def _coverage_check(net: Any, params: Any) -> str | None:
    """源带宽守卫：f_max ≥ fb×MIN_COVERAGE_FACTOR 才受理；低于内核网格
    Nyquist（fb·M/2）→ 返回外推 note（interpolate+pad 惯例，非错误）。"""
    f_max = float(net.f[-1])
    fb_hz = float(params.fb) * 1e9
    if f_max < MIN_COVERAGE_FACTOR * fb_hz:
        raise ValueError(
            f"采样率不足：源 f_max={f_max / 1e9:.3g} GHz < fb×"
            f"{MIN_COVERAGE_FACTOR}={MIN_COVERAGE_FACTOR * float(params.fb):.3g} GHz"
            f"（脉冲响应在该波特率下无可信谱内容）")
    nyq_internal = fb_hz * int(params.M) / 2.0
    if f_max < nyq_internal:
        return (f"源 f_max={f_max / 1e9:.3g} GHz 低于内核网格 Nyquist "
                f"{nyq_internal / 1e9:.3g} GHz——超出频段按 pychopmarg 惯例外推")
    return None


def run_com(
    thru_s4p: str | Path,
    *,
    fext_s4p: tuple[str | Path, ...] = (),
    next_s4p: tuple[str | Path, ...] = (),
    params: Any,
    params_note: str = "",
    opt_mode: str = "przf",
) -> dict[str, Any]:
    """单点 COM 运行（pychopmarg 权威）→ schema 化结果。

    opt_mode：均衡选择目标（"przf" | "mmse"）。**PRZF 是 93A 规格路线**，
    此时 fom_db = 93A-36（20·log10(As/√Σvar)，与分项复算恒等）；MMSE 时
    fom_db 是 MMSE 选择目标、与 93A-36 分解**不等**（3.1.2 实测口径，
    schema 如实两列并报不自证一致）。

    契约：
    - 输入面错误（文件缺失/非 s4p/端口数≠4/带宽不足/参数非法/opt_mode
      未知名）→ 显式抛（调用方的契约错误，负例锚）；
    - pychopmarg 缺装 → ``status="unavailable"`` 不抛；
    - pychopmarg 计算失败 → ``status="degraded"`` 不抛（#105 惯例）。

    Returns:
        ok/status/com_db/fom_db/fom_db_recalc/as_v/sigma_v(分项)/eq(均衡
        终态)/coverage/verification=UNVERIFIED_VS_802COM/provenance。
    """
    thru_path = Path(thru_s4p)
    net, src_meta = _validate_s4p(thru_path)
    for p in (*fext_s4p, *next_s4p):
        _validate_s4p(Path(p))
    coverage_note = _coverage_check(net, params)

    try:
        from pychopmarg.com import COM  # 惰性（#105）
        from pychopmarg.common import OptMode
    except Exception as exc:
        return {"ok": True, "schema_version": COM_PAM4_SCHEMA_VERSION,
                "status": "unavailable", "com_db": None,
                "note": f"pychopmarg 不可用（{type(exc).__name__}: {exc}）",
                "verification": UNVERIFIED_VS_802COM,
                "pychopmarg_version": pychopmarg_version()}
    try:
        opt_mode_enum = OptMode[opt_mode.upper()]
    except KeyError as exc:
        raise ValueError(
            f"未知 opt_mode {opt_mode!r}（可用：{[m.name for m in OptMode]}）"
        ) from exc

    channels = {"THRU": [thru_path],
                "FEXT": [Path(p) for p in fext_s4p],
                "NEXT": [Path(p) for p in next_s4p]}
    t0 = time.perf_counter()
    try:
        the_com = COM(params, channels)
        com_db = float(the_com(opt_mode=opt_mode_enum))
        fom = dict(the_com.fom_rslts)
    except Exception as exc:
        return {"ok": True, "schema_version": COM_PAM4_SCHEMA_VERSION,
                "status": "degraded", "com_db": None,
                "note": f"pychopmarg COM 计算失败（{type(exc).__name__}: {exc}）"
                        f"——降级不阻塞（#105）",
                "verification": UNVERIFIED_VS_802COM,
                "pychopmarg_version": pychopmarg_version()}
    wall = time.perf_counter() - t0

    as_v = float(fom["As"])
    sigma = {"tx": float(fom["sigma_Tx"]), "isi": float(fom["sigma_ISI"]),
             "jitter": float(fom["sigma_J"]), "xt": float(fom["sigma_XT"]),
             "thermal": float(fom["sigma_N"])}
    var = {k: v * v for k, v in sigma.items()}
    # 分项闭式换算（93A-36）与内核 FOM 互洽（同源数字，恒等复算非独立裁判）
    fom_db_recalc = com_db_from_terms(as_v, var["tx"], var["isi"], var["jitter"],
                                      var["xt"], var["thermal"])
    return {
        "ok": True,
        "schema_version": COM_PAM4_SCHEMA_VERSION,
        "status": "ok",
        "com_db": com_db,
        "fom_db": float(fom["FOM"]),
        "fom_db_recalc": fom_db_recalc,
        "as_v": as_v,
        "sigma_v": sigma,
        "cursor_ix": int(fom["cursor_ix"]),
        "eq": {
            "g_dc": float(the_com.gDC),
            "g_dc2": float(the_com.gDC2),
            "tx_taps_ix": int(the_com.tx_ix),
            "n_tx_combs": int(the_com.num_tx_combs),
            "rx_taps": [round(float(v), 9) for v in np.asarray(the_com.rx_taps)],
            "dfe_taps": [round(float(v), 9)
                         for v in np.asarray(the_com.dfe_taps).ravel()],
        },
        "params": {
            "fb_gbaud": float(params.fb), "L": int(params.L),
            "RLM": float(params.RLM), "M": int(params.M),
            "n_g_dc": len(params.g_DC), "n_g_dc2": len(params.g_DC2),
            "opt_mode": opt_mode_enum.name,
            "note": params_note,
        },
        "source": {**src_meta,
                   "n_fext": len(fext_s4p), "n_next": len(next_s4p)},
        "coverage_note": coverage_note,
        "wall_time_s": round(wall, 3),
        "verification": UNVERIFIED_VS_802COM,
        "pychopmarg_version": pychopmarg_version(),
    }


# ---------------------------------------------------------------------------
# fb / 抽头 sweep（每点独立确定性；单点失败降级不阻塞整列）
# ---------------------------------------------------------------------------

def sweep_fb(
    thru_s4p: str | Path,
    *,
    fb_list_gbaud: tuple[float, ...],
    params_factory: Callable[[float], Any],
    fext_s4p: tuple[str | Path, ...] = (),
    next_s4p: tuple[str | Path, ...] = (),
) -> list[dict[str, Any]]:
    """fb 扫描：每个波特率经 params_factory(fb_gbaud) 重建参数后跑单点 COM。

    返回行 = {"fb_gbaud", "status", "com_db", "note"?}；fb 列表为空 →
    ValueError（空扫描是调用方笔误，不是空结果）。
    """
    if not fb_list_gbaud:
        raise ValueError("fb_list_gbaud 为空——空扫描是调用方笔误")
    rows: list[dict[str, Any]] = []
    for fb in fb_list_gbaud:
        try:
            params = params_factory(float(fb))
            rslt = run_com(thru_s4p, fext_s4p=fext_s4p, next_s4p=next_s4p,
                           params=params)
            rows.append({"fb_gbaud": float(fb), "status": rslt["status"],
                         "com_db": rslt["com_db"],
                         **({"note": rslt["note"]} if "note" in rslt else {})})
        except Exception as exc:
            rows.append({"fb_gbaud": float(fb), "status": "degraded",
                         "com_db": None, "note": f"{type(exc).__name__}: {exc}"})
    return rows


def sweep_tx_tap(
    thru_s4p: str | Path,
    *,
    tap_ix: int,
    values: tuple[float, ...],
    base_params: Any,
    base_taps: tuple[float, ...] | None = None,
    fext_s4p: tuple[str | Path, ...] = (),
    next_s4p: tuple[str | Path, ...] = (),
) -> list[dict[str, Any]]:
    """Tx FFE 单抽头扫描：其余抽头钉在 base_taps，被扫抽头逐值钉死
    （min=max=v、c0_min=0；整体优化路线，每点确定性）。

    base_taps 缺省 = 主抽头位（tap_ix 处）1、其余 0（与 preset 抽头数同长）。
    每个扫描值都做 |v|.sum() ≤1 预检（不可行的钉组合会被 mk_combs 静默滤成
    零向量 = "无 FFE"，宁可显式拒绝），任一值不可行 → ValueError 整列拒绝。
    行 = {"tap_ix", "tap_value", "tx_taps", "status", "com_db", "note"?}。
    """
    n_taps = len(base_params.tx_taps_min)
    if not (0 <= tap_ix < n_taps):
        raise ValueError(f"tap_ix 须在 [0, {n_taps})，得 {tap_ix}")
    if base_taps is None:
        pins = [0.0] * n_taps
        pins[min(tap_ix, n_taps - 1)] = 1.0
    else:
        pins = [float(v) for v in base_taps]
        if len(pins) != n_taps:
            raise ValueError(
                f"base_taps 长度须 = 抽头数 {n_taps}，得 {len(pins)}")
    trials = [list(pins) for _ in values]
    for trial, val in zip(trials, values, strict=True):
        trial[tap_ix] = float(val)
        # 预检可行域：不满足则该钉组合被 mk_combs 滤掉只剩零向量（静默
        # "无 FFE"），宁可显式拒绝也不产 silently-wrong 行
        if sum(abs(v) for v in trial) > 1.0 + 1e-9:
            raise ValueError(
                f"扫描值 {val!r} 使钉向量 |v|.sum() >1（c0_min=0 可行域），"
                f"trial={trial}")
    rows: list[dict[str, Any]] = []
    for trial, val in zip(trials, values, strict=True):
        try:
            params = dataclasses.replace(
                base_params, tx_taps_min=list(trial), tx_taps_max=list(trial),
                tx_taps_step=[0.1] * n_taps, c0_min=0.0)
            rslt = run_com(thru_s4p, fext_s4p=fext_s4p, next_s4p=next_s4p,
                           params=params)
            rows.append({"tap_ix": int(tap_ix), "tap_value": float(val),
                         "tx_taps": [round(v, 9) for v in trial],
                         "status": rslt["status"], "com_db": rslt["com_db"],
                         **({"note": rslt["note"]} if "note" in rslt else {})})
        except Exception as exc:
            rows.append({"tap_ix": int(tap_ix), "tap_value": float(val),
                         "tx_taps": [round(v, 9) for v in trial],
                         "status": "degraded", "com_db": None,
                         "note": f"{type(exc).__name__}: {exc}"})
    return rows
