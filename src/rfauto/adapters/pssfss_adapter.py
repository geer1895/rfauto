"""EC-20 PyPSSFSS 严格快通道适配器（EMSolverRegistry 第 13 注册键，W2-F）。

定位（规格 runs/research_seats_20261004/sa_specs2/SPECS.md §三）：PSSFSS.jl
（RWG MoM+GSM 周期结构专用，Julia，MIT）经 pypssfss 桥接入 EMSolverRegistry，
成为 FSS/超表面 ms_* 族的"严格快档"（分钟级，介于 LC 闭式与 openEMS 单胞
全波之间），同时把 metasurface 模板"J3 vs PSSFSS"文献值判读升级为仓内可
复跑裁判（#300 合法化）。

诚实边界（#122 如实）
--------------------
- **单胞无限阵 Floquet 口径**（周期边界由方法内建）：有限阵列/斜入射扫描
  面不在本通道（斜入射经 steering 透传 θ/φ，缺省法向）；
- **v1 模板面 = ms_cross / ms_jcross / ms_patch 三模板**（规格 §3.4 首批
  锚判据面 + smoke 面；ms_ring_patch/ms_array_NxN 归 followUp）；
- **Floquet 模式数旋钮**：PSSFSS 1.14.2 analyze 无 neff 类关键字
  （kwarg_decl 实测=outlist/logfile/resultfile/showprogress/fastsweep）——
  模式数由引擎按光栅瓣判据自动管理；geometry 传 n_floquet_modes≠None
  显式报错（不虚报旋钮，B2 版本漂移纪律）；
- **EC 初值口径**：本通道的闭式互证锚是设计值口径（半波/EC 带），不是
  绝对精度裁判——绝对锚 = ms_cross 10.152GHz PSSFSS 参考值（#300 升级
  路径）与 HFSS Floquet 终裁（scripts/hfss_floquet_anchor.py 通道）。

sheet 映射表（与仓内可复跑裁判 runs/dp10_j2j3/judge_pssfss.jl 逐构造参数
同源——该驱动即 ge5/ge6 归档参考值 10.152GHz 的产生器，2026-10-01 起
载板口径；本适配器=其 Python 面合法化，#154 同名参数语义逐对钉）：
- ms_cross（带阻十字偶极子贴片）→ ``jerusalemcross`` all-filled 实心十字
  （P=period, L1=2·arm_len, L2=arm_w, **A=arm_w/2**, B=arm_w, w=arm_w,
  clas='J'）。**A 必须异于 L2**：A==L2 → xrequired 出现重复值 → 零宽
  网格 → analyze 抛 "matrix contains Infs or NaNs"（原驱动 :75-77 同款
  哨兵注释；2026-10-05 本席 probe 实证复现）；
- ms_jcross（带通 JC 缝）→ ``pixels`` class='M' 孔径位图（npix 缺省 96，
  缝=0 像素；**主缝沿 x 的 90° 旋转等价器件**，(v,v)=耦合极化读出——
  judge_pssfss.jl :51-68 同款掩码 + audit §H.2 极化重钉；方胞 90° 旋转
  在法向入射下 S 参数等价）；
- ms_patch（接地方贴片反射阵单元）→ ``rectstrip`` + ``pecsheet`` 接地板
  （strata：air / patch / substrate / PEC / air；设计锚 =Hammerstad 不动点
  名义边长，量级互证口径）。

Julia depot 钉 E 盘:首次 use 触发 Julia+
PSSFSS 自动安装编译（分钟-十分钟级）；本模块在 import pypssfss **之前**
显式设 ``JULIA_DEPOT_PATH``（缺省 E:\\julia_depot，用户已设值时尊重不
覆盖），不依赖 shell env。缺装环境 is_available()=False 显式报缺
（qucsator fail-closed 同款，不静默）。

分层：adapters，惰性 import pypssfss/juliacall（裸环境 ``import
rfauto.adapters`` 安全）；供 service 判读链与 scripts/pssfss_ms_judge.py
（#300 复跑裁判）调用。
"""

from __future__ import annotations

import csv
import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

#: v1 模板面（诚实声明——能力表 supported_templates 从此实测导入）。
#: **位置纪律**：必须前置于 ``em_solver_base`` import——后者尾部能力表经
#: 本元组实测导入（防手写漂移）；循环 import 回调时本模块只执行到 import
#: 行，元组若在其后则能力表拿到空表（2026-10-05 W2-F 实证）。
SUPPORTED_TEMPLATES: tuple[str, ...] = ("ms_cross", "ms_jcross", "ms_patch")

from rfauto.adapters.em_solver_base import (  # noqa: E402 —— 见上，位置纪律
    EMSolverAdapter,
    EMSolverConfig,
    EMSolverResult,
)

_TOUCHSTONE_NAME = "pssfss.s2p"
_SPARAMS_CSV_NAME = "sparams.csv"
_META_NAME = "pssfss_meta.json"

#: openEMS 同构 5 列 schema（health_service._parse_sparams_csv_masked 零改动
#: 可消费；全 2×2 与双极化在 Touchstone/meta 承载，mmt 先例）。
_SPARAMS_CSV_HEADER = ("freq_hz", "re_S11", "im_S11", "re_S21", "im_S21")

#: Julia depot 缺省钉 E 盘（硬规则 1）；用户已设 JULIA_DEPOT_PATH 时尊重。
_JULIA_DEPOT_DEFAULT = r"E:\julia_depot"

#: #300 文献回收钉（judge 口径 §3.3.2）：ms_cross 无限阵 Floquet 参考值。
#: 出处=knowledge/anchors.yaml ms_cross.wg_resonance.openems-hfss-v1
#: semantics 引 PSSFSS 10.152GHz（ge6 裁判链 10.150 格点值在档）；
#: |Δf|≤1% 门=规格 §3.3.2 预声明。
MS_CROSS_PSSFSS_REF_GHZ = 10.152
MS_CROSS_GATE_REL = 0.01
#: ms_jcross 原判读门（render_metasurface.py:1156 原文）：Δf ≤0.3GHz 或 ≤5%。
MS_JCROSS_GATE_ABS_GHZ = 0.3
MS_JCROSS_GATE_REL = 0.05
#: 判读窗缺省（与 ms_* meta f0=10GHz 设计带一致；judge_pssfss.jl band=(7,12)）
_JUDGE_BAND_GHZ = (7.0, 12.0)
_NFREQ_DEFAULT = 41
_NPIX_DEFAULT = 96
_NTRI_DEFAULT = 1500


class PssfssError(ValueError):
    """PSSFSS 几何/配置显式错误（契约违反不静默）。"""


# --------------------------------------------------------------------------- #
# Julia depot 面钉 E 盘（import pypssfss 之前必须生效）
# --------------------------------------------------------------------------- #


def ensure_julia_depot_env() -> str:
    """显式钉 ``JULIA_DEPOT_PATH``（缺省 E:\\julia_depot，硬规则 1）。

    juliacall/juliapkg 在 import 期读 depot——本函数必须在首次 ``import
    pypssfss`` 之前调用。用户已设值时尊重不覆盖（返回现值如实）。
    """
    depot = os.environ.get("JULIA_DEPOT_PATH") or _JULIA_DEPOT_DEFAULT
    os.environ["JULIA_DEPOT_PATH"] = depot
    return depot


def load_pypssfss() -> Any | None:
    """惰性加载 pypssfss 模块（先钉 depot）；缺装返回 None 不抛。"""
    ensure_julia_depot_env()
    try:
        import pypssfss
    except ImportError:
        return None
    return pypssfss


def is_pypssfss_installed() -> bool:
    """pypssfss 可 import（缺装 fail-closed 显式报缺的第一判据）。"""
    return load_pypssfss() is not None


_MISSING_HINT = (
    "pypssfss 未安装（pip install rfauto[pssfss]）；首次 use 会自动安装并"
    "编译 Julia+PSSFSS（分钟-十分钟级，JULIA_DEPOT_PATH 已钉 "
    f"{_JULIA_DEPOT_DEFAULT}）"
)


# --------------------------------------------------------------------------- #
# 几何映射纯函数（mm 口径，零 julia 依赖——单测可钉确定性）
# --------------------------------------------------------------------------- #


def _req_f(params: dict[str, Any], key: str, ctx: str) -> float:
    if key not in params:
        raise PssfssError(f"{ctx}: 缺必填参数 {key}")
    v = float(params[key])
    if not math.isfinite(v) or v <= 0.0:
        raise PssfssError(f"{ctx}: 参数 {key}={params[key]!r} 必须为正有限数")
    return v


def nominal_params(template: str) -> dict[str, Any]:
    """模板名义参数（TEMPLATE_NOMINAL 单源，禁手抄毫米数 #1c/#252）。"""
    from rfauto.adapters.openems_templates import TEMPLATE_NOMINAL

    if template not in TEMPLATE_NOMINAL:
        raise PssfssError(
            f"未知模板 {template!r}（PSSFSS v1 支持 {SUPPORTED_TEMPLATES}）")
    return dict(TEMPLATE_NOMINAL[template])


def cross_sheet_spec(params: dict[str, Any]) -> dict[str, Any]:
    """ms_cross → jerusalemcross all-filled 实心十字构造规格（纯函数）。

    返回 kwargs 字典（数值 mm 口径 + clas；units 由 solve 面套 pypssfss.mm）。
    A=arm_w/2 哨兵：A 必须异于 L2（重复值 → 零宽网格 → 引擎 Infs/NaNs，
    judge_pssfss.jl :75-77 与本席 2026-10-05 probe 双实证）。
    """
    span = 2.0 * _req_f(params, "arm_len_mm", "ms_cross")
    aw = _req_f(params, "arm_w_mm", "ms_cross")
    period = _req_f(params, "period_mm", "ms_cross")
    if span >= period:
        raise PssfssError(
            f"ms_cross: 臂总跨 {span}mm 必须 < 周期 {period}mm（不 touching）")
    if aw >= span / 2.0:
        raise PssfssError(f"ms_cross: 臂宽 {aw}mm 必须 < 总跨之半 {span / 2}mm")
    return {"P": period, "L1": span, "L2": aw, "A": aw / 2.0, "B": aw,
            "w": aw, "clas": "J", "ntri": int(params.get("ntri",
                                                         _NTRI_DEFAULT))}


def jcross_pixel_mask(params: dict[str, Any], npix: int = _NPIX_DEFAULT,
                      ) -> np.ndarray:
    """ms_jcross → pixels class='M' 孔径位图（纯函数，judge_pssfss.jl :55-67
    同款掩码：主缝沿 **x** 的 90° 旋转等价器件，(v,v)=耦合极化）。

    mat[i,j]=True → 金属像素；False → 缝孔径。像素 (i,j) 中心
    (x,y)=((j-1/2)d, P-(i-1/2)d)，d=P/npix（pypssfss docs 口径）。
    主缝=|x|≤S/2 且 |y|≤w/2；端枝=主缝端 w 段内、|y|∈[w/2, w/2+T]（±y 四枝）。
    """
    P = _req_f(params, "period_mm", "ms_jcross")
    S = _req_f(params, "slot_len_mm", "ms_jcross")
    w = _req_f(params, "slot_w_mm", "ms_jcross")
    T = _req_f(params, "stub_len_mm", "ms_jcross")
    if not (0 < w < S):
        raise PssfssError(f"ms_jcross: 要求 0<slot_w<slot_len，得 {w}/{S}")
    if S >= P:
        raise PssfssError(f"ms_jcross: 主缝全长 {S}mm 必须 < 周期 {P}mm")
    if w / 2.0 + T >= P / 2.0:
        raise PssfssError(
            f"ms_jcross: 端枝越界（w/2+T={w / 2 + T}mm ≥ P/2={P / 2}mm）")
    if npix < 8:
        raise PssfssError(f"npix={npix} 过粗（<8 像素栅格不合法）")
    d = P / npix
    half = P / 2.0
    # 像素中心网格：x 沿 j、y 沿 i 反向（docs 口径）
    xs = (np.arange(npix) + 0.5) * d - half
    ys = half - (np.arange(npix) + 0.5) * d
    xc = np.abs(xs)[None, :]
    yc = np.abs(ys)[:, None]
    in_main = (xc <= S / 2.0) & (yc <= w / 2.0)
    in_stub = ((S / 2.0 - w <= xc) & (xc <= S / 2.0)
               & (w / 2.0 <= yc) & (yc <= w / 2.0 + T))
    metal = ~(in_main | in_stub)  # 缝=False、金属=True
    return metal


JCROSS_POL_READOUT = (
    "(v,v)=耦合极化读出（掩码主缝沿 x 的 90° 旋转等价器件；方胞法向入射下"
    "与 openEMS 模板主缝沿 y、E∥x 器件 S 参数等价——judge_pssfss.jl :33-39 "
    "极化重钉/audit §H.2 口径）")


def patch_sheet_spec(params: dict[str, Any]) -> dict[str, Any]:
    """ms_patch → rectstrip 方贴片构造规格（纯函数；Nx/Ny=网格分段数）。"""
    px = _req_f(params, "px_mm", "ms_patch")
    py = _req_f(params, "py_mm", "ms_patch")
    period = _req_f(params, "period_mm", "ms_patch")
    if max(px, py) >= period:
        raise PssfssError(
            f"ms_patch: 贴片 {px}x{py}mm 必须 < 周期 {period}mm（不 touching）")
    return {"Lx": px, "Ly": py, "Px": period, "Py": period,
            "Nx": max(2, math.ceil(px / 2.0)),
            "Ny": max(2, math.ceil(py / 2.0)), "clas": "J"}


def strata_order(template: str) -> list[str]:
    """层叠顺序描述（meta 用；真对象由 solve 面构造）。

    cross/jcross=自由屏载单侧基板（judge_pssfss.jl :107：strata 自下而上
    air / substrate / SHEET / air）；patch=接地反射阵单元（air / patch /
    substrate / PEC / air）。
    """
    if template in ("ms_cross", "ms_jcross"):
        return ["air", "substrate", "sheet", "air"]
    return ["air", "sheet", "substrate", "pec_ground", "air"]


def freqs_from_geometry(geometry: dict[str, Any],
                        config: EMSolverConfig) -> np.ndarray:
    """频网解析（GHz；mmt 同构契约）：freqs_ghz 显式优先，缺省均匀网格。"""
    fs = geometry.get("freqs_ghz")
    if fs is not None:
        if not isinstance(fs, (list, tuple)) or len(fs) < 2:
            raise PssfssError("freqs_ghz 必须为 ≥2 点列表")
        freqs = np.asarray([float(f) for f in fs], dtype=float)
    else:
        n = int(geometry.get("n_freq", _NFREQ_DEFAULT))
        lo, hi = geometry.get("freq_start_ghz"), geometry.get("freq_stop_ghz")
        if lo is None or hi is None:
            lo, hi = config.freq_range_ghz
        freqs = np.linspace(float(lo), float(hi), n)
    if np.any(~np.isfinite(freqs)) or np.any(freqs <= 0):
        raise PssfssError(f"频点必须为正有限数: {freqs[:5].tolist()}")
    if np.any(np.diff(freqs) <= 0):
        raise PssfssError(f"频点网格须严格递增: {freqs[:5].tolist()}")
    return freqs


def resolve_geometry(geometry: dict[str, Any],
                     config: EMSolverConfig) -> dict[str, Any]:
    """geometry JSON → 解析后契约（纯函数；非法显式 PssfssError）。

    契约：
        template: "ms_cross"|"ms_jcross"|"ms_patch"   —— 必填
        params: {...}        —— 可选，缺省 TEMPLATE_NOMINAL（#1c 单源）
        substrate: {er, tan_d, h_mm}                  —— 可选，缺省名义 er/
          tan_d/h_mm（载板口径，judge_pssfss.jl :105-107）
        freqs_ghz / freq_start_ghz+freq_stop_ghz+n_freq —— 频网（缺省
          config.freq_range_ghz 均匀 41 点）
        steering: {theta_deg, phi_deg}                —— 可选，缺省 0/0
        fast_sweep: bool     —— 可选，缺省 True（PSSFSS 理性插值快扫档，
          spec §3.2「缺省开」；引擎 1.14.2 fastsweep kwarg 实测在）
        npix / ntri          —— jcross 像素栅格边长（96）/cross 三角数（1500）
        n_floquet_modes      —— 仅接受 None（引擎无此旋钮，传值显式报错）
        z0_ref: float        —— 可选端口参考阻抗（缺省 50）
    """
    if not isinstance(geometry, dict):
        raise PssfssError("geometry 必须为对象")
    template = str(geometry.get("template", ""))
    if template not in SUPPORTED_TEMPLATES:
        raise PssfssError(
            f"template={template!r} 不在 PSSFSS 支持面 {SUPPORTED_TEMPLATES}"
            "（非 FSS 域 recipe 请走 openEMS/HFSS 通道——防误用）")
    params = dict(nominal_params(template))
    user_params = geometry.get("params") or {}
    if not isinstance(user_params, dict):
        raise PssfssError("params 必须为对象")
    params.update(user_params)
    if int(params.get("ntri", _NTRI_DEFAULT)) != _NTRI_DEFAULT:
        params["ntri"] = int(params["ntri"])  # 显式透传
    sub = dict(geometry.get("substrate") or {})
    substrate = {"er": float(sub.get("er", params.get("er", 1.0))),
                 "tan_d": float(sub.get("tan_d", params.get("tan_d", 0.0))),
                 "h_mm": float(sub.get("h_mm", params.get("h_mm", 0.0)))}
    if substrate["er"] < 1.0 or substrate["h_mm"] < 0.0:
        raise PssfssError(f"substrate 非法: {substrate}")
    if float(params.get("h_mm", substrate["h_mm"])) <= 0.0 and template in (
            "ms_cross", "ms_jcross"):
        raise PssfssError("载板 h_mm 必须为正（载板参考口径）")
    steering = dict(geometry.get("steering") or {})
    theta = float(steering.get("theta_deg", 0.0))
    phi = float(steering.get("phi_deg", 0.0))
    if not all(math.isfinite(v) for v in (theta, phi)):
        raise PssfssError("steering 角必须为有限数")
    nfm = geometry.get("n_floquet_modes")
    if nfm is not None:
        raise PssfssError(
            "n_floquet_modes 在 PSSFSS 1.14.x 无对应旋钮（模式数由引擎按"
            "光栅瓣判据自动管理）——如实拒绝，不虚报")
    z0_ref = float(geometry.get("z0_ref", 50.0))
    if not (math.isfinite(z0_ref) and z0_ref > 0.0):
        raise PssfssError(f"z0_ref 必须为正实数，得到 {z0_ref!r}")
    freqs = freqs_from_geometry(geometry, config)
    return {
        "template": template,
        "params": params,
        "substrate": substrate,
        "freqs_ghz": freqs,
        "theta_deg": theta,
        "phi_deg": phi,
        "fast_sweep": bool(geometry.get("fast_sweep", True)),
        "npix": int(geometry.get("npix", _NPIX_DEFAULT)),
        "ntri": int(params.get("ntri", _NTRI_DEFAULT)),
        "z0_ref": z0_ref,
    }


# --------------------------------------------------------------------------- #
# #300 判读纯函数（谷/峰位估计器=judge_mscross.py 同款口径：线性域 2 邻域
# 严格局部极小集合 + argmin 一致性 + dB 域三点抛物线细化）
# --------------------------------------------------------------------------- #


def valley_f_ghz(freq_ghz: np.ndarray, s21_db: np.ndarray,
                 band_ghz: tuple[float, float] | None = None) -> dict[str, Any]:
    """|S21| dB 谷位（带内 argmin + 局部极小一致性 + 抛物线细化）。"""
    return _extremum_f_ghz(freq_ghz, s21_db, band_ghz, kind="valley")


def peak_f_ghz(freq_ghz: np.ndarray, s21_db: np.ndarray,
               band_ghz: tuple[float, float] | None = None) -> dict[str, Any]:
    """|S21| dB 峰位（带通主判；估计器与谷位同构取反）。"""
    return _extremum_f_ghz(freq_ghz, s21_db, band_ghz, kind="peak")


def _extremum_f_ghz(freq_ghz: np.ndarray, s21_db: np.ndarray,
                    band_ghz: tuple[float, float] | None,
                    kind: str) -> dict[str, Any]:
    f = np.asarray(freq_ghz, dtype=float)
    db = np.asarray(s21_db, dtype=float)
    if f.shape != db.shape or f.ndim != 1 or f.size < 5:
        raise PssfssError("判读输入须为同长 1 维数组且 ≥5 点")
    lo, hi = 0, f.size - 1
    if band_ghz is not None:
        lo = int(np.searchsorted(f, band_ghz[0]))
        hi = int(np.searchsorted(f, band_ghz[1])) - 1
        if hi - lo < 4:
            raise PssfssError(f"判读带 {band_ghz} 内频点不足")
    work = -db if kind == "peak" else db  # 峰位=取反后的谷位
    seg = work[lo:hi + 1]
    ia = lo + int(np.argmin(seg))
    loc: list[int] = []
    for i in range(lo + 2, hi - 1):
        if (work[i] < work[i - 1] and work[i] < work[i + 1]
                and work[i] < work[i - 2] and work[i] < work[i + 2]):
            loc.append(i)
    refined = None
    if loc:
        i = min(loc, key=lambda k: work[k])
        if lo < i < hi:
            d1, d2, d3 = db[i - 1], db[i], db[i + 1]
            den = d1 - 2.0 * d2 + d3
            if den > 1e-12:
                shift = 0.5 * (d1 - d3) / den
                if abs(shift) <= 1.0:
                    refined = float(f[i] + shift * (f[i + 1] - f[i - 1]))
        return {"f_ghz": float(f[i]), "f_ghz_refined": refined,
                "s21_db": float(db[i]), "n_local_extrema": len(loc),
                "argmin_is_best_local": bool(i == ia)}
    return {"f_ghz": float(f[ia]), "f_ghz_refined": refined,
            "s21_db": float(db[ia]), "n_local_extrema": 0,
            "argmin_is_best_local": True}


def judge_ms_cross(f_notch_ghz: float,
                   ref_f_ghz: float = MS_CROSS_PSSFSS_REF_GHZ,
                   gate_rel: float = MS_CROSS_GATE_REL) -> dict[str, Any]:
    """ms_cross 判读（规格 §3.3.2）：|Δf| ≤1% vs PSSFSS 参考值（文献回收
    钉 #118 家法；成功后锚 provenance 升 engine_pair 的复跑面）。"""
    df = float(f_notch_ghz) - float(ref_f_ghz)
    rel = abs(df) / float(ref_f_ghz)
    return {"template": "ms_cross", "metric": "f_notch_ghz",
            "f_ghz": float(f_notch_ghz), "ref_f_ghz": float(ref_f_ghz),
            "delta_ghz": df, "delta_rel": rel, "gate_rel": gate_rel,
            "verdict": "PASS" if rel <= gate_rel else "FAIL"}


def judge_ms_jcross(f_peak_ghz: float, f0_ghz: float = 10.0,
                    gate_abs_ghz: float = MS_JCROSS_GATE_ABS_GHZ,
                    gate_rel: float = MS_JCROSS_GATE_REL) -> dict[str, Any]:
    """ms_jcross 判读（render_metasurface.py:1156 原门）：Δf ≤0.3GHz **或**
    ≤5%（首次从文献值变仓内可复跑——#300 主锚；MoM 确定性 ⇒ 同几何两次
    跑逐位一致，判分一致性自检见单测）。"""
    df = float(f_peak_ghz) - float(f0_ghz)
    rel = abs(df) / float(f0_ghz)
    ok = abs(df) <= gate_abs_ghz or rel <= gate_rel
    return {"template": "ms_jcross", "metric": "f_peak_ghz",
            "f_ghz": float(f_peak_ghz), "f0_ghz": float(f0_ghz),
            "delta_ghz": df, "delta_rel": rel,
            "gate_abs_ghz": gate_abs_ghz, "gate_rel": gate_rel,
            "verdict": "PASS" if ok else "FAIL"}


# --------------------------------------------------------------------------- #
# 适配器
# --------------------------------------------------------------------------- #


class PssfssAdapter(EMSolverAdapter):
    """PSSFSS.jl RWG MoM 周期结构快档适配器（ms_* 族单胞 Floquet）。

    能力声明集中在 em_solver_base._SOLVER_CAPABILITY_SPECS（单一事实源，
    openEMS 先例——本类不设 CAPABILITIES 类属性，避免两处漂移）。
    """

    def __init__(self, config: EMSolverConfig):
        super().__init__(config)
        self._resolved: dict[str, Any] | None = None
        self._freqs_hz: np.ndarray | None = None
        self._s_full: np.ndarray | None = None  # (n,2,2) complex，耦合极化基
        self._network: Any | None = None
        self._last_meta: dict[str, Any] | None = None
        self._last_error: str | None = None

    # ── 生命周期 ────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        pf = load_pypssfss()
        if pf is None:
            self._last_error = _MISSING_HINT
            logger.error("%s", self._last_error)
            return False
        self._connected = True
        return True

    def is_available(self) -> bool:
        return is_pypssfss_installed()

    # ── 配置生成 ────────────────────────────────────────────────────────────

    def build_geometry(self, geometry: dict[str, Any]) -> bool:
        """解析 geometry 契约到内部规格（不触引擎；solve 时消费）。"""
        self._last_error = None
        try:
            resolved = resolve_geometry(geometry, self._config)
        except PssfssError as exc:
            self._last_error = f"PSSFSS geometry 解析失败: {exc}"
            logger.error("%s", self._last_error)
            return False
        self._resolved = resolved
        self._freqs_hz = resolved["freqs_ghz"] * 1e9
        return True

    # ── 求解与产物 ──────────────────────────────────────────────────────────

    def solve(self) -> EMSolverResult:
        """strata → analyze（fastsweep 缺省开）→ 复 S（双极化）→ 产物落盘。

        引擎调用失败 fail-closed：success=False + message 带原文（缺装显式
        报缺指路 extras）。
        """
        if self._resolved is None or self._freqs_hz is None:
            return EMSolverResult(success=False,
                                  message="build_geometry() 未解析 geometry")
        t0 = time.time()
        try:
            meta = self._solve_engine()
        except Exception as exc:
            self._last_error = f"PSSFSS solve 失败: {type(exc).__name__}: {exc}"
            logger.error("%s", self._last_error)
            return EMSolverResult(success=False,
                                  wall_time_s=round(time.time() - t0, 3),
                                  message=self._last_error)
        wall = round(time.time() - t0, 3)
        freqs_hz = self._freqs_hz
        self._write_products(Path(self._config.working_dir or "."), meta, wall)
        self._last_meta = meta
        fs_eff = "fastsweep=on" if meta["fast_sweep_effective"] else \
            "fastsweep=off"
        return EMSolverResult(
            success=True, freq_ghz=freqs_hz / 1e9, s_params=self._s_full,
            measured_mask=np.ones((2, 2), dtype=bool),
            field_data={"polarizations": meta["polarizations"],
                        "engine": meta["engine"]},
            convergence_iterations=0, wall_time_s=wall,
            message=(f"PSSFSS solve ok（{meta['template']}，{freqs_hz.size} 点，"
                     f"{fs_eff}，{meta['engine']['pssfss_version']}）；"
                     "单胞无限阵 Floquet 口径"),
        )

    def _solve_engine(self) -> dict[str, Any]:
        """引擎面（惰性 import 后构造 strata→analyze→extract）。"""
        r = self._resolved
        assert r is not None
        pf = load_pypssfss()
        if pf is None:  # pragma: no cover —— build/solve 间卸载的极端态
            raise RuntimeError(_MISSING_HINT)
        from pypssfss.pypssfss import jl

        template = r["template"]
        params = r["params"]
        sub = r["substrate"]
        mm = pf.mm
        # pypssfss fixsheetargs 对 clas 只改名不转型——Python 单字符 str 传给
        # pixels 报 "expected Char, got String"；juliacall convert 到 Char 才
        # 被接受（seval 包装的 AnyValue 仍按 String 落型，2026-10-05 真跑
        # 三变体实证）——统一 juliacall convert。
        from juliacall import convert as _jl_char_convert

        def _jchar(ch: str) -> Any:
            return _jl_char_convert(jl.Char, ch)

        if template == "ms_cross":
            spec = cross_sheet_spec(params)
            kw = {k: v for k, v in spec.items() if k != "clas"}
            sheet = pf.jerusalemcross(units=mm, clas=_jchar("J"), **kw)
            # all-filled 十字的正交臂在方胞下双极化同频（judge :40-41）
            pol_coupling, pol_ortho = ("v", "v"), ("h", "h")
        elif template == "ms_jcross":
            mask = jcross_pixel_mask(params, npix=r["npix"])
            # pypssfss fixsheetargs 只做 Vector（1 维）转换——2 维位图须先
            # 自转 Julia Matrix{Bool}，否则 (Vector)(::PyArray{Bool,2})
            # MethodError（2026-10-05 真跑实证）
            mat_jl = _jl_char_convert(jl.Matrix,
                                      np.ascontiguousarray(mask, dtype=bool))
            sheet = pf.pixels(P=float(params["period_mm"]),
                              patternmat=mat_jl, units=mm,
                              clas=_jchar("M"), sym=True)
            pol_coupling, pol_ortho = ("v", "v"), ("h", "h")
        else:  # ms_patch
            spec = patch_sheet_spec(params)
            kw = {k: v for k, v in spec.items() if k != "clas"}
            sheet = pf.rectstrip(units=mm, clas=_jchar("J"), **kw)
            pol_coupling, pol_ortho = ("v", "v"), ("h", "h")

        layers: list[Any] = [pf.Layer()]
        if template in ("ms_cross", "ms_jcross"):
            # 自由屏载单侧基板（judge :104-107：air / substrate / SHEET / air）
            layers.append(pf.Layer(width=sub["h_mm"] * mm,
                                   epsr=sub["er"], tandel=sub["tan_d"]))
            layers.append(sheet)
        else:
            # 接地反射阵单元：air / patch / substrate / PEC / air。
            # pypssfss 0.1.0 上游 bug：pf.pecsheet() 是 docstring-only 存根
            # （函数体无 return → None 入 strata，接地板静默丢失、|S11| 塌到
            # 0.5-0.8——2026-10-05 真跑实证）——按 pmcsheet 同款直调 Julia
            # 侧 RWGSheet(jl.pecsheet()) 规避。
            from pypssfss.sheets import RWGSheet

            layers.append(sheet)
            layers.append(pf.Layer(width=sub["h_mm"] * mm,
                                   epsr=sub["er"], tandel=sub["tan_d"]))
            layers.append(RWGSheet(jl.pecsheet()))
        layers.append(pf.Layer())
        strata = layers

        freqs_ghz = r["freqs_ghz"]
        workdir = Path(self._config.working_dir or ".")
        workdir.mkdir(parents=True, exist_ok=True)
        logfile = str(workdir / "pssfss_run.log")
        resultfile = str(workdir / "pssfss_run.res")
        results = pf.analyze(strata, [float(f) for f in freqs_ghz],
                             pf.ThetaPhi(r["theta_deg"], r["phi_deg"]),
                             logfile=logfile, resultfile=resultfile,
                             showprogress=False,
                             fastsweep=bool(r["fast_sweep"]))
        outreq = pf.atoutputs(
            "fghz s11(v,v) s21(v,v) s12(v,v) s22(v,v)"
            " s11(h,h) s21(h,h) s12(h,h) s22(h,h)")
        arr = np.asarray(pf.extract_result(results, outreq), dtype=complex)
        if arr.ndim != 2 or arr.shape[1] != 9:
            raise RuntimeError(f"extract_result 形态异常: {arr.shape}")
        f_out = arr[:, 0].real
        s_v = arr[:, 1:5]
        s_h = arr[:, 5:9]
        n = f_out.size
        s_full = np.empty((n, 2, 2), dtype=complex)
        s_full[:, 0, 0] = s_v[:, 0]
        s_full[:, 1, 0] = s_v[:, 1]
        s_full[:, 0, 1] = s_v[:, 2]
        s_full[:, 1, 1] = s_v[:, 3]
        self._s_full = s_full
        import skrf

        self._network = skrf.Network(
            frequency=skrf.Frequency.from_f(f_out * 1e9, unit="Hz"),
            s=s_full, z0=r["z0_ref"],
        )
        db = 20.0 * np.log10(np.maximum(np.abs(s_full[:, 1, 0]), 1e-12))
        # 正交极化 |S21| 全带（ms_cross 双极化谷位同频的旁证面，judge :40-41）
        s21_db_ortho = [round(float(v), 4) for v in
                        20.0 * np.log10(np.maximum(np.abs(s_h[:, 1]), 1e-12))]
        band = (_JUDGE_BAND_GHZ[0], _JUDGE_BAND_GHZ[1])
        in_band = (f_out >= min(band)) & (f_out <= max(band))
        extremum: dict[str, Any] | None
        try:
            if template == "ms_jcross":
                extremum = peak_f_ghz(f_out[in_band], db[in_band])
            else:
                extremum = valley_f_ghz(f_out[in_band], db[in_band])
        except PssfssError as exc:  # 判读是报告面——点数不足不阻塞主路（#105）
            extremum = {"unavailable": str(exc)}
        return {
            "template": template,
            "params_echo": {k: (float(v) if isinstance(v, (int, float))
                                else v) for k, v in params.items()
                            if not isinstance(v, (dict, list))},
            "substrate": sub,
            "strata_order": strata_order(template),
            "freqs_ghz": [float(f) for f in f_out],
            "n_freq": int(n),
            "steering_deg": {"theta": r["theta_deg"], "phi": r["phi_deg"]},
            "fast_sweep_requested": bool(r["fast_sweep"]),
            "fast_sweep_effective": bool(r["fast_sweep"]),
            "npix": (r["npix"] if template == "ms_jcross" else None),
            "npix_quantization_note": (
                f"pixels 边长 {r['npix']}，像素 d="
                f"{float(params['period_mm']) / r['npix']:.6f}mm，边缘偏置"
                "~d/2（judge 口径）" if template == "ms_jcross" else None),
            "ntri": (spec["ntri"] if template == "ms_cross" else None),
            "polarizations": {
                "coupling": pol_coupling,
                "ortho": pol_ortho,
                "s21_db_ortho": s21_db_ortho,
                "note": JCROSS_POL_READOUT if template == "ms_jcross" else
                        "方胞正交双臂/贴片双极化同频，判读极化不敏感",
            },
            "engine": {
                "pssfss_version": str(jl.seval(
                    "string(pkgversion(PSSFSS))")),
                "julia_version": str(jl.seval("string(VERSION)")),
            },
            "extremum": extremum,
            "z0_ref": r["z0_ref"],
            "logfile": logfile,
        }

    def _write_products(self, workdir: Path, meta: dict[str, Any],
                        wall: float) -> None:
        """openEMS 同构产物落盘（best-effort 观测面不阻塞主路，#105）：
        sparams.csv（5 列掩码契约）+ pssfss.s2p（skrf）+ pssfss_meta.json。"""
        workdir.mkdir(parents=True, exist_ok=True)
        freqs_hz = np.asarray(meta["freqs_ghz"], dtype=float) * 1e9
        s = self._s_full
        try:
            with open(workdir / _SPARAMS_CSV_NAME, "w", newline="",
                      encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(_SPARAMS_CSV_HEADER)
                for i in range(freqs_hz.size):
                    w.writerow([freqs_hz[i], s[i, 0, 0].real, s[i, 0, 0].imag,
                                s[i, 1, 0].real, s[i, 1, 0].imag])
        except OSError as exc:
            logger.warning("sparams.csv 写出失败（S 主路保留）: %s", exc)
        if self._network is not None:
            try:
                self._network.write_touchstone(str(workdir / _TOUCHSTONE_NAME),
                                               form="ri")
            except Exception as exc:
                logger.warning("Touchstone 导出失败（CSV/meta 保留）: %s", exc)
        meta_out = {**meta, "wall_time_s": wall, "solver": "pssfss",
                    "adapter": "pssfss", "schema": "rfauto-pssfss/v1"}
        try:
            (workdir / _META_NAME).write_text(
                json.dumps(meta_out, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except OSError as exc:
            logger.warning("pssfss_meta.json 写出失败: %s", exc)

    # ── 读取面 ──────────────────────────────────────────────────────────────

    def get_sparams(self) -> tuple[np.ndarray, np.ndarray]:
        """S 参数（EMSolver 面契约：(freq_ghz, s(n,2,2))；耦合极化基）。"""
        if self._s_full is None or self._freqs_hz is None:
            result = self.solve()
            if not result.success:
                raise RuntimeError(result.message)
        return self._freqs_hz / 1e9, self._s_full

    def get_meta(self) -> dict[str, Any] | None:
        """最近一次 solve 的 meta（pssfss_meta.json 内容）。"""
        return self._last_meta

    def export_touchstone(self, path: str | Path,
                          contract: Any = None) -> Path:
        if self._network is None:
            raise RuntimeError("尚未求解，请先调用 solve()")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._network.write_touchstone(str(path), form="ri")
        return path

    def close(self) -> None:
        self._connected = False
        self._resolved = None
        self._freqs_hz = None
        self._s_full = None
        self._network = None
        self._last_meta = None

    # ── 6g 产物视图协议 ────────────────────────────────────────────────────

    def visualizations(self) -> list[dict[str, Any]]:
        workdir = self._config.working_dir or "."
        return [
            {"kind": "sparams",
             "spec": {"file": str(Path(workdir) / _SPARAMS_CSV_NAME)}},
            {"kind": "circuit",
             "spec": {"file": str(Path(workdir) / _META_NAME),
                      "format": "pssfss-meta-json"}},
        ]

    def supported_output_formats(self) -> list[str]:
        return ["touchstone", "csv"]


# --------------------------------------------------------------------------- #
# 注册（EMSolverType.PSSFSS 第 13 注册键；导入即注册，mmt 同款幂等模式）
# --------------------------------------------------------------------------- #


def register_pssfss(registry: Any = None) -> None:
    """注册到全局/指定 EMSolverRegistry（导入即注册模式，幂等同键覆盖）。"""
    from rfauto.adapters.em_solver_base import (
        EMSolverType,
        get_global_registry,
    )

    target = registry if registry is not None else get_global_registry()
    target.register(EMSolverType.PSSFSS, PssfssAdapter)


try:  # 注册失败只 warning 不阻塞 import（#105）
    register_pssfss()
except Exception:  # pragma: no cover —— 防御性（注册表面异常）
    logger.warning("PssfssAdapter 全局注册失败", exc_info=True)
