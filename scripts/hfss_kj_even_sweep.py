"""P-KJ-EVEN P2 — HFSS 全模型宽端口扫描战役驱动（发射面，本件只备妥不发射）。

判据预声明：runs/df7_kjeven/p2_criteria_v2.md（**v2 测量面架构**，先写后
跑；判读冲突如实记 FAIL/UNKNOWN 不事后改门 #122/#286）。v1 判据
p2_criteria.md 零改写留档；v1 战役 7 点全 UNKNOWN 归因见战役档案（P2 criteria 同目录留档）：
CharImp 三定义重建 Z0 互差在准 TEM 宽端口 0.09~14%（物理路径分歧，≤1% 门
不可达）+ gate0 0.5% 绝对步进门边缘假警报。P1 输入：runs/df7_kjeven/
p1_audit.md（H2 成立：半模型小波端口横向截断偶模场尾）。

路线 B 端口方案裁定（预声明，详见 criteria v1 §一）：**多模 2 端口**——耦合
对全长度直通板端，每端一条波端口横跨两导体（modes=2，一次解同时出
even/odd），零过渡寄生、模可观测量直接；宽度阶梯 {W0,1.5W0,2W0} 直接监测
P1 截断病理。4 端口 + Γe=S11+S31（df6 _route_b 已验证）保留为后备（模序
混淆/IntLine 编辑失效时改道，判据不变）。

**v2 测量架构**（criteria v2 §一）：
- 主判 = Modal Solution Data **直读 Zo(Port)（每模）+ Gamma**，直读定义
  **CharImp=Zvi**（准 TEM bracketing：v1 实测 Zpi 高估/Zpv 低估/Zvi=
  √(Zpi·Zpv) TEM 等效居中——四五三笔 7 点证据）；解算数 7→5（撤销 Zpv/Zvi
  换档子解）。
- 单线基准换算（#307 解析，随端口拓扑/IntLine 声明定）：even 端口电流=
  2×单线电流 → Z0e_single=2·Z_modal；odd 端口电压=2×单线电压 →
  Z0o_single=Z_modal/2。主判一律消费换算后单线值，换算证据落 point.json。
- 校验 = 参考阻抗无关反演 Z0=Zr·(1−x)/(1+x), x=Γ_in·e^{+2γL}（Zr=同解直
  读）与直读互证 ≤2%（门 2v2）；**基准确认门**：route_ratio ∈
  {1.0,0.5,2.0} ±2%（门 B，不在格点=测量面无效先修再判）——"mode_z0 乘 2
  与否"的显式判定（v1 even 反演 ~35=KJ 69.37 之半的基准因子疑点在此闭环）。
- 模序逐档按 β 排序识别（β 大=even；IntLine 交换后解算器模号重排免疫），
  识别与声明相反时 props 编辑交换 IntLine（与 HfssPortDriver.
  _set_ports_char_imp 同款机制，#263/#265/#285/#308 口径全沿用）。
- gate0 v2：主判观测量步进单调递减 + 末档 <1% 双条件（criteria v2 §二）。

每点解算 5 次：ΔS 阶梯 (0.02/12,0.01/18,0.005/24) @W0/Zvi + 宽度档 W1/W2
@末档/Zvi。断点续跑：point.json 存在且 status=ok 且
verdict∈{PASS,FAIL} 才跳（UNKNOWN 视为未完档重跑；v1 档已挪
p2_sweep_v1_archive/，v2 断点键自然失效全点重跑）。
fail-closed 互斥查：任何 ansysedt 存活=中止（不代杀）；含本脚本标记的外部
python 驱动=中止（自排除自身进程链，#261 互斥自锁教训）。--dry-run 零真机。

真机坑位口径（沿用）：pyaedt 1.x ansys.aedt.core 命名空间（B2）；Hfss
project 绝对路径（#243）；薄片金属 assign_perfecte_to_sheets（#356①）；
get_face_center 模型单位+非空守卫（#285）；多模端口
integration_line=[起点列表,终点列表]（#308）；finally release_desktop_capped
（#265）；watchdog 超时 fail-closed（#145）；solo 单飞（#246）。

JSON 记录约定：复数={"re","im"}；模键一律字符串 "1"/"2"（JSON 往返稳定）。
"""
from __future__ import annotations

import argparse
import cmath
import contextlib
import json
import math
import os
import sys
import time
from itertools import pairwise
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

WORK = REPO / "runs" / "df7_kjeven"
OUT_DIR = WORK / "p2_sweep"
CRITERIA = WORK / "p2_criteria_v2.md"
CRITERIA_REL = "runs/df7_kjeven/p2_criteria_v2.md"

VERSION = "2025.1"
F_PROBE_GHZ = 2.5
H_MM = 0.508
ER = 3.66
C0 = 299792458.0

L_LINE_MM = 30.0            # 耦合对全长度（直通端口面）
AIR_TOP_H = 10.0            # 空气域高（=端口高）
MARGIN_H = 10.0             # 主判端口横向每边余量（h 单位）
LADDER_MULT = (1.0, 1.5, 2.0)
LEVELS = ((0.02, 12), (0.01, 18), (0.005, 24))   # (MaxDeltaS, MaximumPasses)
READ_CHAR_IMP = "Zvi"       # v2 直读定义（准 TEM 等效口径，criteria v2 §一）
SOLVE_TIMEOUT_S = 1800.0
HALF_LADDER_MM = (6.0, 10.0, 15.0, 20.0)         # P1 §8.2 半模型宽度阶梯
HALF_PORT_H = 4.0           # 半模型端口高（P1 even_z 同族 4h）
HALF_DS, HALF_MP = 0.005, 20                     # P1 z 阶梯固定 ΔS 口径

# KJ 文献域（qucs-doc technical/microstrip.tex，P1 源 C；闭域含边界）
KJ_DOMAIN = (0.1, 10.0, 0.1, 10.0)

# 门阈值（criteria v2 §二，写死再跑）
TOL_MAIN = 0.01           # even 主判 / odd 控制组
TOL_STEP_LAST = 0.01      # gate0 v2：末档步进（配步进单调递减双条件）
TOL_CROSSCHECK = 0.02     # 门 2v2：直读-反演互证
TOL_BASIS = 0.02          # 门 B：基准确认格点容差
BASIS_LATTICE = (1.0, 0.5, 2.0)   # #307 路间基准因子格点
SINGLE_LINE_FACTOR = {"even": 2.0, "odd": 0.5}   # 模基→KJ 单线基准（解析）
TOL_EXTRAP_LAST2 = 0.003  # 外推有效性：末两档差
TOL_CROSS = 0.01          # 跨模纯度（线性）
TOL_SYM = 1e-2            # 镜像/互易（线性，df6 gate4 口径）
TOL_EPS_ROUTE = 0.01      # εeff 双路互证
TOL_REF_INFO = 0.02       # 域外参考点信息带

# 点表（毫米值写死；u/g 为名义值，w=u·h / s=g·h 精确换算；bpf 用综合链实测值）
POINTS: tuple[dict, ...] = (
    {"tag": "y1", "u": 1.8195, "g": 0.1614, "w_mm": 0.924306, "s_mm": 0.081991,
     "in_domain": True,
     "note": "df6 Y1 仲裁工作点（w=u·h, s=g·h 精确换算）"},
    {"tag": "lange", "u": 0.329, "g": 0.0760, "w_mm": 0.167132, "s_mm": 0.038608,
     "in_domain": False, "note": "lange 3dB 综合链（P1 §4 表；域外参考点）"},
    {"tag": "cline6", "u": 1.355, "g": 0.0394, "w_mm": 0.688340, "s_mm": 0.020015,
     "in_domain": False, "note": "cline_coupler 6dB（P1 §4 表；域外参考点）"},
    {"tag": "bpf", "u": 1.2322, "g": 0.0885, "w_mm": 0.625946, "s_mm": 0.044955,
     "in_domain": False,
     "note": "coupled_bpf N=2 FBW10% 最紧缝段综合链实测值（域外参考点）"},
    {"tag": "edge_a", "u": 0.1, "g": 0.1, "w_mm": 0.050800, "s_mm": 0.050800,
     "in_domain": True, "note": "KJ 域角 (0.1,0.1)"},
    {"tag": "edge_b", "u": 10.0, "g": 0.1, "w_mm": 5.080000, "s_mm": 0.050800,
     "in_domain": True, "note": "域缘 (10,0.1)：宽带强耦"},
    {"tag": "edge_c", "u": 10.0, "g": 10.0, "w_mm": 5.080000, "s_mm": 5.080000,
     "in_domain": True, "note": "域角 (10,10)：宽带弱耦"},
)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ── 离线纯函数面（零真机可测）────────────────────────────────────────────


def kj_anchor(w_mm: float, s_mm: float, freq_ghz: float = F_PROBE_GHZ,
              er: float = ER, h_mm: float = H_MM) -> dict:
    """KJ 锚（repo 内核运行时重算，数值只在确定性内核 #7，禁转写 #118）。"""
    from rfauto.core.coupled_microstrip import coupled_microstrip_even_odd_ohm

    z0e, z0o, ee, eo = coupled_microstrip_even_odd_ohm(w_mm, s_mm, freq_ghz, er, h_mm)
    return {"z0e_ohm": z0e, "z0o_ohm": z0o, "eps_eff_e": ee, "eps_eff_o": eo}


def eps_envelope(w_mm: float, s_mm: float, freq_ghz: float = F_PROBE_GHZ,
                 er: float = ER, h_mm: float = H_MM) -> tuple[float, float]:
    """εeff_e 物理包络 [εeff_HJ(w), 1.01·εeff_HJ(2w+s)]（P1 §8.3；Y1=[2.816,3.024]）。"""
    from rfauto.core.synthesis import Stackup, forward_z0

    st = Stackup(name="kj_even_p2", epsilon_r=float(er), thickness_mm=float(h_mm))
    _, e_w = forward_z0(float(w_mm), float(freq_ghz), st)
    _, e_2ws = forward_z0(2.0 * float(w_mm) + float(s_mm), float(freq_ghz), st)
    return (e_w, 1.01 * e_2ws)


def port_widths(w_mm: float, s_mm: float) -> tuple[float, float, float]:
    """宽度阶梯 W0=2w+s+20h，{1×, 1.5×, 2×}（P1 截断病理监测同族）。"""
    w0 = 2.0 * w_mm + s_mm + 2.0 * MARGIN_H * H_MM
    return (round(w0 * LADDER_MULT[0], 6), round(w0 * LADDER_MULT[1], 6),
            round(w0 * LADDER_MULT[2], 6))


def point_geom(w_mm: float, s_mm: float) -> dict:
    """点几何单源（mm 字面预计算 #218 口径；全部 mm）。"""
    w0, w1, w2 = port_widths(w_mm, s_mm)
    return {
        "w_mm": w_mm, "s_mm": s_mm, "l_mm": L_LINE_MM,
        "xa_mm": -(w_mm + s_mm) / 2.0, "xb_mm": (w_mm + s_mm) / 2.0,
        "port_w_mm": [w0, w1, w2], "air_x_half_mm": w2 / 2.0 + 2.0 * H_MM,
        "air_top_mm": AIR_TOP_H * H_MM, "h_mm": H_MM,
        "er": ER, "lossless": True,
    }


def build_point_plan(point: dict) -> dict:
    """点完整计划：几何 + KJ 锚 + 包络 + 解算数（dry-run/驱动共用单源）。"""
    geom = point_geom(point["w_mm"], point["s_mm"])
    solves = len(LEVELS) + (len(LADDER_MULT) - 1)
    return {
        "tag": point["tag"], "u": point["u"], "g": point["g"],
        "w_mm": point["w_mm"], "s_mm": point["s_mm"],
        "in_domain": point["in_domain"], "note": point["note"],
        "geom": geom, "kj": kj_anchor(point["w_mm"], point["s_mm"]),
        "eps_envelope": list(eps_envelope(point["w_mm"], point["s_mm"])),
        "solves_per_point": solves,
    }


def identify_modes(gammas: dict[int, complex]) -> tuple[int, int]:
    """(even_mode, odd_mode)：β 大者=even（εeff_e>εeff_o 排序恒等式，P1 B3）。

    HFSS 多模端口模序不保证（按截断/收敛排序），禁止按 Mode1=even 臆断。
    """
    if set(gammas) != {1, 2}:
        raise ValueError(f"模 Γ 读数须含 mode 1/2，实得 {sorted(gammas)}")
    b1, b2 = gammas[1].imag, gammas[2].imag
    return (1, 2) if b1 >= b2 else (2, 1)


def mode_pair(level: dict | None) -> tuple[int, int] | None:
    """单档 (even_mode, odd_mode)：按**该档** Γ 的 β 排序识别（v2 §一.4）。

    IntLine 交换后解算器模号可能重排——逐档识别对重排免疫；Γ 读数缺失
    →None（fail-closed，判读层落 UNKNOWN）。
    """
    if not level:
        return None
    pd1 = (level.get("port_data") or {}).get("P1") or {}
    g1 = _cx((pd1.get("Gamma") or {}).get("1"))
    g2 = _cx((pd1.get("Gamma") or {}).get("2"))
    if g1 is None or g2 is None:
        return None
    return identify_modes({1: g1, 2: g2})


def single_line_ohm(z_modal: float, role: str) -> float:
    """模基阻抗 → KJ 单线基准（#307 换算，解析因子随端口拓扑定，v2 §一.3）。

    even（双线同电位）：端口电流=2×单线电流 → Z0e_single=2·Z_modal；
    odd（IntLine=带到带）：端口电压=2×单线电压 → Z0o_single=Z_modal/2。
    """
    return abs(z_modal) * SINGLE_LINE_FACTOR[role]


def basis_confirm(z_inv: float, z_direct: float,
                  tol: float = TOL_BASIS) -> dict:
    """反演 Z0 vs 直读 Zo 的基准确认（#307 模基准显式钉，v2 门 B）。

    route_ratio=|Z0^inv|/|Zo^直读| 必须落在格点 {1.0, 0.5, 2.0}（±tol）；
    检出 0.5/2.0 = 两路存在基准因子差 → 按 #307 换算（f 折进门 2 互证）后
    采信；不在格点（如 0.7）= 测量面无效（先修再判）。读数缺失/为零 →
    ok=None（fail-closed）。
    """
    if z_inv is None or z_direct is None or z_direct == 0 or z_inv == 0:
        return {"route_ratio": None, "factor": None, "factor_dev_pct": None,
                "ok": None, "reason": "直读/反演读数缺失"}
    ratio = abs(z_inv) / abs(z_direct)
    factor = min(BASIS_LATTICE, key=lambda f_: abs(ratio - f_) / f_)
    dev = abs(ratio - factor) / factor
    return {"route_ratio": ratio, "factor": factor,
            "factor_dev_pct": dev * 100.0, "ok": bool(dev <= tol)}


def unwrap_gl(t_coef: complex, beta: float, length_m: float) -> complex:
    """T=e^{−γL} → γL；相位整周分支按 Γ 直读 β 定（双路互证前提）。"""
    if abs(t_coef) < 1e-300:
        raise ValueError("T=0（解坏或读数错），γL 不可提取")
    gl = -cmath.log(t_coef)
    target = float(beta) * float(length_m)
    n = round((gl.imag - target) / (2.0 * math.pi))
    return gl - 1j * 2.0 * math.pi * n


def z0_from_gamma(zr: complex, gamma_in: complex, gl: complex) -> dict:
    """均匀线 Γ 反演（参考阻抗无关）：
    x=Γe^{+2γL}=(Zr−Z0)/(Zr+Z0) → Z0=Zr(1−x)/(1+x)。

    Zr 与 Γ 同源自洽 → 无论 HFSS 模阻抗基准取 Z0e 还是 Z0e/2（#307），
    反演恒为物理线阻抗；CharImp 三定义互差的数学基础（criteria 门 2）。
    附不带 e^{2γL} 修正的捷径值 z0_naive（诊断，非判读量）。
    """
    if abs(1.0 + gamma_in) < 1e-12:
        raise ValueError("Γ≈−1 反演退化")
    x = gamma_in * cmath.exp(2.0 * gl)
    if abs(1.0 + x) < 1e-12:
        raise ValueError("x≈−1 反演退化（Z0→∞ 非物理）")
    return {"z0": zr * (1.0 - x) / (1.0 + x),
            "z0_naive": zr * (1.0 - gamma_in) / (1.0 + gamma_in),
            "rho_load": x}


def _cx(d) -> complex | None:
    """JSON 复数 {"re","im"}（或原生 complex/float）→ complex；缺失→None。"""
    if d is None:
        return None
    if isinstance(d, complex):
        return d
    if isinstance(d, (int, float)):
        return complex(d)
    if isinstance(d, dict) and "re" in d and "im" in d:
        return complex(float(d["re"]), float(d["im"]))
    return None


def _k0_rad_m() -> float:
    return 2.0 * math.pi * F_PROBE_GHZ * 1e9 / C0


def mode_scalars(level: dict, mode: int, length_m: float) -> dict | None:
    """单档单模标量组（JSON 形态记录 → 纯判读）：直读 Zo、Zr、Γ、γL、Z0^inv、
    εeff 双路。

    量语义：port Gamma 读数=该模传播常数 γ（β=Im Γ，εeff_Γ=(β/k0)²）；
    **z_direct=Zo 直读（v2 主判可观测量，criteria v2 §一.2）**；
    反射系数 Γ_in 取 S(P1:m,P1:m)（广义模基，参考=端口 CharImp 定义）；
    T 取 S(P2:m,P1:m)=e^{−γL}（γL 相位按 β 直读定整周分支）；
    Z0^inv = Zr·(1−x)/(1+x)，x=Γ_in·e^{+2γL}（参考阻抗无关，校验路线
    criteria v2 §一.5；与 z_direct 的基准则由 basis_confirm 显式解析）。

    level 形态＝_extract_all_modal 的 JSON 化：port_data[P]["Zo"|"Gamma"][str(mode)]
    ={"re","im"}，s_data["S(Pa:ma,Pb:mb)"]={"re","im"}。必需读数缺失→None。
    """
    pd1 = (level.get("port_data") or {}).get("P1") or {}
    zo = _cx((pd1.get("Zo") or {}).get(str(mode)))
    gam = _cx((pd1.get("Gamma") or {}).get(str(mode)))
    sd = level.get("s_data") or {}
    t = _cx(sd.get(f"S(P2:{mode},P1:{mode})"))
    s11 = _cx(sd.get(f"S(P1:{mode},P1:{mode})"))
    if zo is None or gam is None or t is None or s11 is None:
        return None
    beta = gam.imag
    if beta <= 0.0:
        return None
    try:
        gl = unwrap_gl(t, beta, length_m)
        inv = z0_from_gamma(zo, s11, gl)
    except ValueError:
        return None
    k0 = _k0_rad_m()
    eps_gamma = (beta / k0) ** 2
    eps_s = (gl.imag / float(length_m) / k0) ** 2
    return {"zr": zo, "z_direct": abs(zo), "gamma": gam, "gl": gl,
            "beta": beta,
            "z0": inv["z0"], "z0_naive": inv["z0_naive"],
            "eps_gamma": eps_gamma, "eps_s": eps_s,
            "eps_route_rel": abs(eps_gamma - eps_s) / eps_gamma}


def extrap_inv_w(widths: list[float], values: list[float]) -> dict:
    """1/W 线性外推（末两档）：Z∞=Z2−a·x2，a=(Z2−Z1)/(x2−x1)，x=1/W。

    有效性（criteria 门 4，写死）：末两档差 ≤0.3% 且单调
    （(Z1−Z0)(Z2−Z1)>0；三档无单调证据时 monotone=None 不因缺证而否）；
    减速比 |Z2−Z1|/|Z1−Z0| 记录不设门。
    """
    if len(widths) != len(values) or len(values) < 2:
        raise ValueError("外推须 ≥2 档等长序列")
    z1, z2 = float(values[-2]), float(values[-1])
    z0_ = float(values[-3]) if len(values) >= 3 else None
    x1, x2 = 1.0 / float(widths[-2]), 1.0 / float(widths[-1])
    a = (z2 - z1) / (x2 - x1) if x2 != x1 else 0.0
    out: dict = {"z_inf": z2 - a * x2, "slope": a,
                 "rel_last2": abs(z2 - z1) / abs(z2) if z2 else None,
                 "monotone": None, "decel_ratio": None, "valid": False}
    if z0_ is not None:
        d01, d12 = z1 - z0_, z2 - z1
        out["monotone"] = bool(d01 * d12 > 0.0)
        out["decel_ratio"] = abs(d12) / abs(d01) if abs(d01) > 0 else None
    rel = out["rel_last2"]
    ok_rel = rel is not None and rel <= TOL_EXTRAP_LAST2
    out["valid"] = bool(ok_rel and out["monotone"] is not False)
    return out


def _rel(a: float, b: float) -> float:
    return abs(a - b) / abs(b) if b else float("inf")


def _configs(rec: dict) -> list[tuple[dict | None, str]]:
    """判读配置序列 [(level, 标签)]：W0（ΔS 末档 @W0）+ 宽度档 W1/W2。"""
    cfgs: list[tuple[dict | None, str]] = []
    levels = rec.get("levels") or []
    cfgs.append((levels[-1] if levels else None, "W0"))
    for i, wr in enumerate(rec.get("width_runs") or []):
        cfgs.append((wr, str(wr.get("label") or f"W{i + 1}")))
    return cfgs


def judge_point(rec: dict) -> dict:
    """点级判读（criteria v2 §二门 0-7+B；纯函数，读数缺失→UNKNOWN fail-closed）。"""
    kj = rec["kj"]
    env = rec["eps_envelope"]
    geom = rec["geom"]
    length_m = geom["l_mm"] * 1e-3
    widths = [float(w) for w in geom["port_w_mm"]]
    levels = rec.get("levels") or []
    out: dict = {"gates": {}}

    # 模序声明记录（首档 β；判读消费一律走逐档 mode_pair，v2 §一.4）
    mp0 = mode_pair(levels[0] if levels else None)
    if mp0 is None:
        return {"gates": {}, "verdict": "UNKNOWN", "reason": "模序识别读数缺失"}
    out["mode_map"] = {"even": mp0[0], "odd": mp0[1]}

    # 各配置标量组 [(label, pair, even_scalars, odd_scalars)]（逐档识别模号）
    scal_by_cfg: list[tuple[str, tuple[int, int] | None, dict | None,
                            dict | None]] = []
    for lv, label in _configs(rec):
        pair = mode_pair(lv) if lv is not None else None
        se = mode_scalars(lv, pair[0], length_m) if pair else None
        so = mode_scalars(lv, pair[1], length_m) if pair else None
        scal_by_cfg.append((label, pair, se, so))
    scal_e = {lb: se for lb, _p, se, _o in scal_by_cfg}

    # ── 门 0：ΔS 阶梯收敛 v2（#335；主判观测量步进单调递减+末档<1%双条件）──
    g0: dict = {"note": "末两档步进 s2<s1（单调降）且 s2≤1%；末档 ΔS 达标未触顶",
                "steps": {}}
    ok0 = len(levels) == len(LEVELS)
    if ok0:
        seq: dict[str, list[float]] = {"even_z0": [], "odd_z0": [], "eps_e": []}
        for lv in levels:
            pair = mode_pair(lv)
            se = mode_scalars(lv, pair[0], length_m) if pair else None
            so = mode_scalars(lv, pair[1], length_m) if pair else None
            if se is None or so is None:
                ok0 = False
                g0["reason"] = "阶梯档标量缺失"
                break
            seq["even_z0"].append(single_line_ohm(se["z_direct"], "even"))
            seq["odd_z0"].append(single_line_ohm(so["z_direct"], "odd"))
            seq["eps_e"].append(se["eps_gamma"])
        if ok0:
            steps = {k: [_rel(v[i + 1], v[i]) for i in range(len(v) - 1)]
                     for k, v in seq.items()}
            g0["steps"] = {k: [round(s, 6) for s in v] for k, v in steps.items()}
            for k in ("even_z0", "odd_z0"):
                s1, s2 = steps[k]
                g0[f"{k}_monotone"] = bool(s2 < s1)
                ok0 = ok0 and s2 < s1 and s2 <= TOL_STEP_LAST
            s2e = steps["eps_e"][-1]
            g0["eps_e_last_step_rel"] = s2e
            ok0 = ok0 and s2e <= TOL_STEP_LAST
            fin = levels[-1]
            g0["final_converged"] = bool(fin.get("converged"))
            g0["final_hit_max_passes"] = bool(fin.get("hit_max_passes"))
            ok0 = ok0 and g0["final_converged"] and not g0["final_hit_max_passes"]
    else:
        g0["reason"] = "ΔS 阶梯档数不足"
    g0["ok"] = bool(ok0)
    out["gates"]["gate0_convergence"] = g0

    # ── 门 1：跨模纯度 ────────────────────────────────────────────────
    g1: dict = {"entries": {}, "ok": None}
    worst_cross, have_cross = 0.0, False
    for lv, label in _configs(rec):
        if lv is None:
            continue
        pair = mode_pair(lv)
        if pair is None:
            continue
        me_, mo_ = pair
        sd = lv.get("s_data") or {}
        for key in (f"S(P2:{mo_},P1:{me_})", f"S(P2:{me_},P1:{mo_})",
                    f"S(P1:{mo_},P1:{me_})"):
            v = _cx(sd.get(key))
            if v is None:
                continue
            have_cross = True
            worst_cross = max(worst_cross, abs(v))
            g1["entries"][f"{label}:{key}"] = abs(v)
    g1["worst"] = worst_cross
    g1["ok"] = bool(worst_cross <= TOL_CROSS) if have_cross else None
    out["gates"]["gate1_mode_purity"] = g1

    # ── 门 B：基准确认（#307 显式钉；route_ratio ∈ {1,0.5,2} ±2%）────────
    _lab0, _pair0, se0, so0 = scal_by_cfg[0]
    gB: dict = {"note": "反演/直读 route_ratio 须落基准格点；检出 0.5/2.0 时"
                        "按 #307 换算后进主判（criteria v2 §二门 B）",
                "modes": {}, "ok": None}
    factors: dict[str, float] = {}
    oksB: list[bool | None] = []
    for mtag, sc0 in (("even", se0), ("odd", so0)):
        if sc0 is None:
            gB["modes"][mtag] = {"ok": None, "reason": "W0 末档标量缺失"}
            oksB.append(None)
            continue
        bc = basis_confirm(abs(sc0["z0"]), sc0["z_direct"])
        if bc["ok"]:
            factors[mtag] = bc["factor"]
        gB["modes"][mtag] = bc
        oksB.append(bc["ok"])
    gB["ok"] = None if any(o is None for o in oksB) else bool(all(oksB))
    # #307 单线基准换算证据（换算因子解析随模角色；换算前后值留痕）
    conv: dict = {"note": "模基→KJ 单线基准换算（解析因子，criteria v2 §一.3）",
                  "factors": dict(SINGLE_LINE_FACTOR), "modes": {}}
    for mtag, sc0 in (("even", se0), ("odd", so0)):
        if sc0 is None:
            continue
        conv["modes"][mtag] = {
            "z_direct_modal": sc0["z_direct"],
            "z_direct_single": single_line_ohm(sc0["z_direct"], mtag),
            "z_inv_modal": abs(sc0["z0"]),
            "route_factor": gB["modes"][mtag].get("factor"),
        }
    gB["single_line_conversion"] = conv
    out["gates"]["gate_basis_confirm"] = gB

    # ── 门 2：直读-反演互证（收敛档 ×双模；替代旧 gate2_charimp_triple）──
    g2: dict = {"note": "|Z0inv/f−Z直读|/Z直读 ≤2%（f=门 B 检出，criteria v2）",
                "entries": {}, "ok": None}
    bad2: list[bool | None] = []
    for lb, _pair, se, so in scal_by_cfg:
        for mtag, sc in (("even", se), ("odd", so)):
            key = f"{lb}:{mtag}"
            if sc is None:
                g2["entries"][key] = {"ok": None, "reason": "标量缺失"}
                bad2.append(None)
                continue
            f_ = factors.get(mtag)
            if f_ is None:
                g2["entries"][key] = {"ok": None,
                                      "reason": "基准因子未检出（门 B 未过/未判）"}
                bad2.append(None)
                continue
            zd = sc["z_direct"]
            rel = abs(abs(sc["z0"]) / f_ - zd) / zd if zd else float("inf")
            g2["entries"][key] = {"route_rel_pct": rel * 100.0, "factor": f_,
                                  "ok": bool(rel <= TOL_CROSSCHECK)}
            bad2.append(rel <= TOL_CROSSCHECK)
    g2["ok"] = None if any(b is None for b in bad2) else bool(all(bad2))
    out["gates"]["gate2_modal_crosscheck"] = g2

    # ── 门 3：奇模控制组（换算单线直读，末档全部已解宽度档）─────────────
    g3: dict = {"entries": {}, "ok": None}
    o3: list[bool] = []
    for lb, _pair, _se, so in scal_by_cfg:
        if so is None:
            continue
        z1 = single_line_ohm(so["z_direct"], "odd")
        dev = _rel(z1, kj["z0o_ohm"])
        g3["entries"][lb] = {"z0o_single": z1, "kj": kj["z0o_ohm"],
                             "dev_pct": dev * 100.0}
        o3.append(dev <= TOL_MAIN)
    g3["ok"] = bool(all(o3)) if o3 else None
    out["gates"]["gate3_odd_control"] = g3

    # ── 门 4：偶模主判（换算单线直读；W2 ≤1% 或 1/W 外推 ≤1%）────────────
    g4: dict = {"widths_mm": widths, "z0e_by_rung": {}, "kj_z0e": kj["z0e_ohm"],
                "ok": None}
    zs: list[float] = []
    ws: list[float] = []
    for i, (lb, _pair, se, _so) in enumerate(scal_by_cfg):
        if se is None or i >= len(widths):
            continue
        z1 = single_line_ohm(se["z_direct"], "even")
        dev = _rel(z1, kj["z0e_ohm"])
        g4["z0e_by_rung"][f"{lb}@{widths[i]:.3f}mm"] = {
            "z0e_single": z1, "dev_pct": dev * 100.0}
        zs.append(z1)
        ws.append(widths[i])
    if len(zs) == len(widths) and len(zs) >= 2:
        dev_w2 = _rel(zs[-1], kj["z0e_ohm"])
        g4["dev_w2_pct"] = dev_w2 * 100.0
        if dev_w2 <= TOL_MAIN:
            g4["route"] = "widest_rung"
            g4["ok"] = True
        else:
            ex = extrap_inv_w(ws, zs)
            g4["extrap"] = {k: ex[k] for k in
                            ("z_inf", "rel_last2", "monotone", "decel_ratio", "valid")}
            g4["extrap"]["dev_pct"] = _rel(abs(ex["z_inf"]), kj["z0e_ohm"]) * 100.0
            g4["route"] = "extrap_inv_w"
            g4["ok"] = bool(ex["valid"]
                            and _rel(abs(ex["z_inf"]), kj["z0e_ohm"]) <= TOL_MAIN)
    elif zs:
        g4["reason"] = "宽度档读数不全（W2 须在列）"
    else:
        g4["reason"] = "宽度档标量全缺"
    out["gates"]["gate4_even_main"] = g4

    # ── 门 5：εeff 包络（解坏判据）＋门 6：双路互证（W2 档）─────────────
    se_w2 = scal_e.get("W2")
    g5: dict = {"envelope": env, "ok": None}
    g6: dict = {"tol": TOL_EPS_ROUTE, "ok": None}
    if se_w2 is not None:
        g5["eps_gamma"] = se_w2["eps_gamma"]
        g5["ok"] = bool(env[0] <= g5["eps_gamma"] <= env[1])
        g6["eps_gamma"] = se_w2["eps_gamma"]
        g6["eps_s_phase"] = se_w2["eps_s"]
        g6["route_rel"] = se_w2["eps_route_rel"]
        g6["ok"] = bool(se_w2["eps_route_rel"] <= TOL_EPS_ROUTE)
    else:
        g5["reason"] = g6["reason"] = "W2 档标量缺失"
    out["gates"]["gate5_eps_envelope"] = g5
    out["gates"]["gate6_eps_dual_route"] = g6

    # ── 门 7：镜像/互易自检（每模，W0 末档）────────────────────────────
    g7: dict = {"entries": {}, "ok": None}
    lv0 = levels[-1] if levels else None
    if lv0 is not None:
        pair0 = mode_pair(lv0)
        sd = lv0.get("s_data") or {}
        bad = []
        if pair0 is None:
            g7["reason"] = "模 Γ 读数缺失"
            g7["ok"] = None
        else:
            for mtag in ("even", "odd"):
                m = pair0[0] if mtag == "even" else pair0[1]
                s11 = _cx(sd.get(f"S(P1:{m},P1:{m})"))
                s22 = _cx(sd.get(f"S(P2:{m},P2:{m})"))
                s12 = _cx(sd.get(f"S(P1:{m},P2:{m})"))
                s21 = _cx(sd.get(f"S(P2:{m},P1:{m})"))
                if None in (s11, s22, s12, s21):
                    g7["entries"][mtag] = {"ok": None, "reason": "S 读数缺失"}
                    bad.append(None)
                    continue
                mir, rec_ = abs(s11 - s22), abs(s12 - s21)
                g7["entries"][mtag] = {"mirror": mir, "reciprocal": rec_,
                                       "ok": bool(mir <= TOL_SYM and rec_ <= TOL_SYM)}
                bad.append(g7["entries"][mtag]["ok"])
            g7["ok"] = None if any(b is None for b in bad) else bool(all(bad))
    else:
        g7["reason"] = "W0 末档记录缺失"
    out["gates"]["gate7_symmetry"] = g7

    # ── 聚合（criteria v2：门 0/2/B 测量面·收敛 False→UNKNOWN；测得违反→FAIL；
    #     读数缺失→UNKNOWN；fail-closed 不凑 PASS 不冒充 FAIL #316）───────
    names = ["gate0_convergence", "gate1_mode_purity", "gate2_modal_crosscheck",
             "gate_basis_confirm", "gate3_odd_control", "gate4_even_main",
             "gate5_eps_envelope", "gate6_eps_dual_route", "gate7_symmetry"]
    unknown_gate = [n for n in ("gate0_convergence", "gate2_modal_crosscheck",
                                "gate_basis_confirm")
                    if out["gates"][n].get("ok") is False]
    if unknown_gate:
        out["verdict"] = "UNKNOWN"
        out["unknown"] = unknown_gate + [n for n in names
                                         if out["gates"][n].get("ok") is None]
        out["reason"] = "收敛未饱和或测量面无效 → 先修再判（criteria v2 §二）"
    else:
        failed = [n for n in names if out["gates"][n].get("ok") is False]
        unknown = [n for n in names if out["gates"][n].get("ok") is None]
        if failed:
            out["verdict"] = "FAIL"
            out["failed"] = failed
        elif unknown:
            out["verdict"] = "UNKNOWN"
            out["unknown"] = unknown
        else:
            out["verdict"] = "PASS"
    if not (rec.get("point") or {}).get("in_domain", True):
        out["informational"] = True
        if scal_e.get("W2") is not None:
            out["info_band_pct"] = _rel(
                single_line_ohm(scal_e["W2"]["z_direct"], "even"),
                kj["z0e_ohm"]) * 100.0
            out["info_within_2pct"] = bool(out["info_band_pct"] <= TOL_REF_INFO * 100.0)
    return out


def judge_half_model(rec: dict) -> dict:
    """半模型对照档判读（criteria §四：对照非主判；回答 P1 悬案）。"""
    kj = rec["kj"]
    widths = [float(w) for w in rec["widths_mm"]]
    vals: list[float] = []
    entries: dict = {}
    for w, lv in zip(widths, rec.get("levels") or [], strict=False):
        pd1 = (lv.get("port_data") or {}).get("P1") or {}
        zo = _cx((pd1.get("Zo") or {}).get("1"))
        gam = _cx((pd1.get("Gamma") or {}).get("1"))
        if zo is None:
            entries[f"{w:.1f}mm"] = {"ok": False, "reason": "Zo 读数缺失"}
            vals.append(float("nan"))
            continue
        dev = _rel(abs(zo), kj["z0e_ohm"])
        eps = (((gam.imag) / _k0_rad_m()) ** 2
               if gam is not None and gam.imag > 0 else None)
        entries[f"{w:.1f}mm"] = {"z0_zpv": abs(zo), "dev_pct": dev * 100.0,
                                 "eps_gamma": eps}
        vals.append(abs(zo))
    good = [v for v in vals if not math.isnan(v)]
    out: dict = {"widths_mm": widths, "entries": entries,
                 "kj_z0e": kj["z0e_ohm"], "ladder_monotone": None,
                 "note": "对照非主判（P1 §8.2 悬案：半模型读数随宽是否收敛）"}
    if len(good) == len(widths) and len(good) >= 2:
        d = [vals[i + 1] - vals[i] for i in range(len(vals) - 1)]
        out["ladder_monotone"] = bool(all(a * b > 0 for a, b in pairwise(d)))
        ex = extrap_inv_w(widths, vals)
        out["extrap"] = {k: ex[k] for k in
                         ("z_inf", "rel_last2", "monotone", "valid")}
        out["extrap_dev_pct"] = _rel(abs(ex["z_inf"]), kj["z0e_ohm"]) * 100.0
        out["widest_dev_pct"] = _rel(vals[-1], kj["z0e_ohm"]) * 100.0
    out["verdict"] = ("PASS" if (len(good) == len(widths)
                                 and out.get("widest_dev_pct", 1e9) <= 1.0)
                      else "RECORDED")
    return out


def budget_estimate(n_points: int, solves_per_point: int,
                    per_solve_min: tuple[float, float] = (2.0, 5.0),
                    margin: float = 1.5) -> dict:
    """预算（criteria §四：每解 2–5min × 解数，×1.5 余量）。"""
    lo = n_points * solves_per_point * per_solve_min[0]
    hi = n_points * solves_per_point * per_solve_min[1]
    return {"n_points": n_points, "solves_per_point": solves_per_point,
            "n_solves": n_points * solves_per_point,
            "core_min": [lo, hi],
            "band_min_with_margin": [lo * margin, hi * margin],
            "band_h_with_margin": [lo * margin / 60.0, hi * margin / 60.0],
            "expected_min": (lo + hi) / 2.0 * margin}


def solves_per_point() -> int:
    return len(LEVELS) + (len(LADDER_MULT) - 1)


def record_schema() -> dict:
    """point.json 顶层 schema（dry-run 留档 + 单测钉；v2：无 charimp_runs）。"""
    return {
        "gate": "kj_even_p2_sweep", "criteria": CRITERIA_REL,
        "tag": "str", "point": {"u": "f", "g": "f", "w_mm": "f", "s_mm": "f",
                                "in_domain": "b", "note": "str"},
        "geom": "point_geom() 输出", "kj": "kj_anchor() 输出",
        "eps_envelope": "[lo, hi]", "mode_map": {"even": "1|2", "odd": "1|2"},
        "mode_line_swap": "b",
        "levels": "[ΔS 阶梯 @W0/Zvi ×3：port_data/s_data/converged/…]",
        "width_runs": "[W1/W2 @末档/Zvi]",
        "gates": "judge_point() 输出（含 gate_basis_confirm 换算证据）",
        "verdict": "PASS|FAIL|UNKNOWN",
        "status": "ok|error", "budget": {"wall_min": "f"},
    }


# ── 互斥查（fail-closed，不代杀）─────────────────────────────────────────

DRIVER_MARKER = "hfss_kj_even_sweep"


def _filter_self_pids(pids: set[int]) -> set[int]:
    """自排除（#261 互斥自锁教训）：自身 PID + 父进程（.venv shim 同命令行
    双 PID，df4⑦）。"""
    return {p for p in pids if p not in (os.getpid(), os.getppid())}


def mutex_check() -> dict:
    """发射前互斥：任何 ansysedt 存活（含孤儿）→中止；他驱动 python→中止。
    枚举失败即中止（fail-closed，#245 不盲动）。本函数**不杀任何进程**。"""
    from rfauto.infra.desktop_guard import list_ansysedt_processes

    procs = list_ansysedt_processes()
    if procs:
        raise RuntimeError(
            "互斥拦截：存在 ansysedt 进程（含孤儿；pid/ppid="
            f"{[(p['pid'], p['ppid']) for p in procs]}）——先人工裁决，"
            "本脚本不代杀（任务纪律）")
    drivers = _list_driver_pythons()
    if drivers:
        raise RuntimeError(f"互斥拦截：他驱动 python 在跑：{drivers}")
    return {"ansysedt": 0, "drivers": 0, "checked_at": time.strftime("%H:%M:%S")}


def _list_driver_pythons() -> list[dict]:
    """枚举 python 进程命令行，按本脚本标记匹配（自进程链排除）。"""
    import subprocess

    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" "
         "| ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }"],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(
            f"python 进程枚举失败（fail-closed）: {(r.stderr or '').strip()[:200]}")
    hits = []
    for line in (r.stdout or "").splitlines():
        if DRIVER_MARKER not in line:
            continue
        pid_str, _, cmd = line.strip().partition("|")
        if pid_str.isdigit() and int(pid_str) in _filter_self_pids({int(pid_str)}):
            hits.append({"pid": int(pid_str), "cmdline": cmd[:160]})
    return hits


# ── 真机面（惰性 import，dry-run 零触发）─────────────────────────────────


def _new_project(tag: str, pdir: Path):
    """每点全新项目（df6 _new_design 同款全量重建；绝对路径 #243）。"""
    import shutil

    from ansys.aedt.core import Hfss

    proj = pdir / f"{tag}.aedt"
    for stale in (proj, proj.with_suffix(".aedtresults"),
                  pdir / (proj.stem + ".pyaedt"),
                  pdir / (proj.name + ".lock")):
        if stale.is_dir():
            shutil.rmtree(stale, ignore_errors=True)
        elif stale.exists():
            with contextlib.suppress(Exception):
                stale.unlink()
    log(f"项目已清理重建: {proj.name}")
    return Hfss(project=str(proj), design=f"kj2_{tag}", solution_type="DrivenModal",
                version=VERSION, non_graphical=True, new_desktop=True)


def _release(h) -> None:
    from rfauto.infra.desktop_guard import release_desktop_capped

    with contextlib.suppress(Exception):
        release_desktop_capped(
            lambda: h.release_desktop(close_projects=True, close_desktop=True))


def _radiate(h, air_x_half: float, air_top: float) -> None:
    """顶面 + x 两侧墙辐射（df6 口径：get_face_center 模型单位 mm + 非空守卫）。"""
    faces = h.modeler.get_object_faces("Air")
    open_faces = []
    for f in faces:
        cx, _cy, cz = (float(v) for v in h.modeler.get_face_center(f))
        if abs(cz - air_top) < 1e-6 or abs(abs(cx) - air_x_half) < 1e-6:
            open_faces.append(f)
    if not open_faces:
        raise RuntimeError("辐射面过滤为空（#285 非空守卫）")
    h.assign_radiation_boundary_to_faces(assignment=open_faces, name="Rad")


def _int_lines(geom: dict, y_mm: float) -> list[list[str]]:
    """每模积分线（#308 列表格式 [[起点×2],[终点×2]]）：
    mode1 假定=even：地→导带上缘竖直线（df6⑪ 口径，不穿金属）；
    mode2 假定=odd：带到带水平线 x∈[xa,xb] @z=h（奇模电压路径）。
    模序经首解 β 识别，反序时 props 编辑交换（_set_ports_int_line_swap）。"""
    xa, xb, hgt = geom["xa_mm"], geom["xb_mm"], geom["h_mm"]
    ln_even = [f"{xa:.6f}mm", f"{y_mm:.6f}mm", "0mm",
               f"{xa:.6f}mm", f"{y_mm:.6f}mm", f"{hgt:.6f}mm"]
    ln_odd = [f"{xa:.6f}mm", f"{y_mm:.6f}mm", f"{hgt:.6f}mm",
              f"{xb:.6f}mm", f"{y_mm:.6f}mm", f"{hgt:.6f}mm"]
    return [ln_even, ln_odd]


def _add_material(h) -> None:
    with contextlib.suppress(Exception):
        h.materials.add_material("rfauto_m366_kjp2", properties={
            "permittivity": ER})   # 无耗（tand=0，与 KJ 锚 Stackup 同口径）


def _build_pair(h, geom: dict) -> None:
    """耦合对全模型（criteria §三几何单源）：基板+地板+双薄条+空气域+双多模端口。"""
    _add_material(h)
    h.modeler.model_units = "mm"
    ax, ay, top = geom["air_x_half_mm"], geom["l_mm"] / 2.0, geom["air_top_mm"]
    hgt = geom["h_mm"]
    h.modeler.create_box(origin=[f"{-ax}mm", f"{-ay}mm", "0mm"],
                         sizes=[f"{2 * ax}mm", f"{2 * ay}mm", f"{hgt}mm"],
                         name="Sub", material="rfauto_m366_kjp2")
    h.modeler["Sub"].solve_inside = True
    h.modeler.create_box(origin=[f"{-ax}mm", f"{-ay}mm", "0mm"],
                         sizes=[f"{2 * ax}mm", f"{2 * ay}mm", "0mm"],
                         name="Gnd", material="pec")
    for nm, xc in (("lineA", geom["xa_mm"]), ("lineB", geom["xb_mm"])):
        h.modeler.create_box(origin=[f"{xc - geom['w_mm'] / 2.0}mm", f"{-ay}mm",
                                     f"{hgt}mm"],
                             sizes=[f"{geom['w_mm']}mm", f"{2 * ay}mm", "0mm"],
                             name=nm, material="pec")
    h.assign_perfecte_to_sheets(assignment=["Gnd", "lineA", "lineB"],
                                name="MetalPEC")   # #356①：薄片导电必须 PerfectE
    h.modeler.create_box(origin=[f"{-ax}mm", f"{-ay}mm", "0mm"],
                         sizes=[f"{2 * ax}mm", f"{2 * ay}mm", f"{top}mm"],
                         name="Air", material="vacuum")
    h.modeler.subtract("Air", ["Sub", "Gnd", "lineA", "lineB"])
    h.modeler["Air"].solve_inside = True
    _radiate(h, ax, top)
    # 多模端口 ×2（#263：sheet 面；#308：多模积分线列表；CharImp 初值=直读
    # 定义 Zvi，逐解经 _set_ports_char_imp 再声明，criteria v2 §一.2）
    h["pw"] = f"{geom['port_w_mm'][0]:.6f}mm"
    for name, y_mm in (("P1", -ay), ("P2", ay)):
        h.modeler.create_rectangle(
            orientation="ZX",
            origin=["-pw/2", f"{y_mm}mm", "0mm"],
            sizes=[f"{top}mm", "pw"], name=name + "sheet")
        port_face = h.modeler.get_object_faces(name + "sheet")[0]
        lines = _int_lines(geom, y_mm)
        h.wave_port(assignment=port_face, name=name, modes=2, impedance=50.0,
                    renormalize=False, characteristic_impedance=["Zvi", "Zvi"],
                    integration_line=[[lines[0][0:3], lines[1][0:3]],
                                      [lines[0][3:6], lines[1][3:6]]])
    setup = h.create_setup(name="Setup1")
    setup.props["Frequency"] = f"{F_PROBE_GHZ}GHz"
    setup.props["MaxDeltaS"] = LEVELS[0][0]
    setup.props["MaximumPasses"] = LEVELS[0][1]
    setup.update()


def _extract_all_modal(hfss, setup_name: str, port_names: tuple[str, ...],
                       modes: tuple[int, ...] = (1, 2)) -> dict:
    """Modal Solution Data 直读（v2 主判提取路径，criteria v2 §一.2）：
    port_data[P][cat][mode]（cat ∈ {"Zo","Gamma"}，每模直读）+
    s_data["S(Pa:ma,Pb:mb)"]（含跨模对）。port_gate_service 的多模推广，
    脚本本地版不改共享解析器 #315。

    pyaedt 1.x API 名对安装版实名核对（2026-09-26，
    PostProcessorCommon.available_quantities_categories /
    available_report_quantities / get_solution_data 均存在；v1 战役 49 解
    实测该读数链全程可用，四五三笔）；惰性 import，dry-run 期零触发。"""
    import re

    import numpy as np

    sol_name = f"{setup_name} : LastAdaptive"
    out: dict = {"solution": sol_name, "categories": [], "errors": [],
                 "port_data": {pn: {"Zo": {}, "Gamma": {}} for pn in port_names},
                 "s_data": {}}
    try:
        cats = hfss.post.available_quantities_categories(
            report_category="Modal Solution Data", solution=sol_name) or []
    except Exception as exc:
        out["errors"].append(f"categories 枚举失败 {exc!r}")
        return out
    out["categories"] = sorted({str(c) for c in cats})
    wanted = [c for c in out["categories"]
              if c in ("Gamma", "Port Zo", "S Parameter")]
    cat_prefix = {"Gamma": "Gamma", "Port Zo": "Zo", "S Parameter": "S"}
    pat = re.compile(r"^(?P<cat>[A-Za-z]+)\((?P<args>[^)]*)\)$")
    matched: dict[str, tuple] = {}
    for cat in wanted:
        try:
            qs = hfss.post.available_report_quantities(
                report_category="Modal Solution Data", solution=sol_name,
                quantities_category=cat)
        except Exception as exc:
            out["errors"].append(f"{cat}: quantities 枚举失败 {exc!r}")
            continue
        for q in list(qs or []):
            m = pat.match(str(q))
            if m is None or m.group("cat") != cat_prefix[cat]:
                continue
            parsed = []
            for a in [x.strip() for x in m.group("args").split(",")]:
                pn, _, ms = a.partition(":")
                parsed.append((pn, int(ms) if ms else 1))
            if any(mode not in modes for _, mode in parsed):
                continue
            names = tuple(pn for pn, _ in parsed)
            if cat == "S Parameter":
                if len(names) == 2 and names[0] in port_names \
                        and names[1] in port_names:
                    key = f"S({names[0]}:{parsed[0][1]},{names[1]}:{parsed[1][1]})"
                    matched[str(q)] = ("S", names[0], key)
            elif len(names) == 1 and names[0] in port_names:
                matched[str(q)] = (cat_prefix[cat], names[0], parsed[0][1])
    if not matched:
        out["errors"].append("LastAdaptive 无可解析量（端口名不匹配或类别缺失）")
        return out
    sol = hfss.post.get_solution_data(
        expressions=list(matched), setup_sweep_name=sol_name,
        report_category="Modal Solution Data")
    if sol is None:
        out["errors"].append("get_solution_data None")
        return out
    for q, (cat, pn, key) in matched.items():
        try:
            _x, re_ = sol.get_expression_data(q, formula="real")
            _x, im_ = sol.get_expression_data(q, formula="imag")
            val = complex(float(np.ravel(re_)[0]), float(np.ravel(im_)[0]))
        except Exception as exc:
            out["errors"].append(f"{q}: 读数失败 {exc!r}")
            continue
        if cat == "S":
            out["s_data"][key] = val
        else:
            out["port_data"][pn][cat][key] = val   # key=mode int
    return out


def _fmt_c(z) -> dict | None:
    if z is None:
        return None
    z = complex(z)
    return {"re": round(z.real, 9), "im": round(z.imag, 9)}


def _jsonify_level(ext: dict, passes, delta_s, hit: bool, extra: dict) -> dict:
    """读数 JSON 化（复数→{"re","im"}；模键→str；#105 观测面 best-effort）。"""
    lv = dict(extra)
    lv["converged"] = bool(delta_s is not None
                           and delta_s <= lv.get("max_delta_s", 1.0))
    lv["delta_s_final"] = delta_s
    lv["passes"] = passes
    lv["hit_max_passes"] = hit
    lv["errors"] = ext.get("errors", [])
    lv["port_data"] = {pn: {cat: {str(m): _fmt_c(v) for m, v in d.items()}
                            for cat, d in pd.items()}
                       for pn, pd in ext.get("port_data", {}).items()}
    lv["s_data"] = {k: _fmt_c(v) for k, v in ext.get("s_data", {}).items()}
    return lv


def _solve_read(h, ds: float, mp: int, char_imp: str, label: str,
                ports: tuple[str, ...] = ("P1", "P2"),
                n_modes: int = 2) -> dict:
    """单次解+读（CharImp 声明→analyze→Modal Solution Data 直读+收敛元数据；
    #145 看门狗）。v2 主判路由 char_imp=Zvi（criteria v2 §一.2）。

    n_modes=CharImp 声明与读数的模数（主判路由=2；半模型对照档=1——
    其端口只有 Mode1，对 Mode2 声明会抛"缺 Mode2 props"（fail-closed））。"""
    from rfauto.adapters.hfss_adapter import HfssAdapter
    from rfauto.infra.desktop_guard import run_with_watchdog
    from rfauto.service.port_gate_service import HfssPortDriver

    setup = h.get_setup("Setup1")
    setup.props["Frequency"] = f"{F_PROBE_GHZ}GHz"
    setup.props["MaxDeltaS"] = ds
    setup.props["MaximumPasses"] = mp
    setup.update()
    for mi in range(1, n_modes + 1):
        HfssPortDriver._set_ports_char_imp(h, ports, char_imp, mode_index=mi)
    t0 = time.time()
    run_with_watchdog(lambda: h.analyze(setup="Setup1"),
                      timeout_s=SOLVE_TIMEOUT_S,
                      what=f"{label} ΔS={ds} [{char_imp}]")
    passes, delta_s = HfssAdapter._extract_convergence(setup)
    hit = bool(passes and mp and passes >= mp)
    ext = _extract_all_modal(h, "Setup1", ports,
                             modes=tuple(range(1, n_modes + 1)))
    rec = _jsonify_level(ext, passes, delta_s, hit,
                         {"label": label, "max_delta_s": ds, "max_passes": mp,
                          "char_imp": char_imp,
                          "wall_s": round(time.time() - t0, 1)})
    log(f"{label} ΔS={ds} [{char_imp}]: delta_s={delta_s} passes={passes} "
        f"wall={rec['wall_s']}s errors={ext.get('errors', [])[:2]}")
    return rec


def _set_ports_int_line_swap(h, ports: tuple[str, ...]) -> None:
    """识别为反序时交换每端口 Mode1/Mode2 的 IntLine（与
    HfssPortDriver._set_ports_char_imp 同款 props 编辑机制；失败即抛=fail-closed）。"""
    targets = {str(n) for n in ports}
    hit = set()
    for b in (getattr(h, "boundaries", None) or []):
        nm = str(getattr(b, "name", ""))
        if nm not in targets:
            continue
        modes = (getattr(b, "props", None) or {}).get("Modes") or {}
        m1, m2 = modes.get("Mode1"), modes.get("Mode2")
        if not m1 or not m2 or "IntLine" not in m1 or "IntLine" not in m2:
            raise RuntimeError(f"端口 {nm} 缺 Mode1/2 IntLine props（交换失败）")
        m1["IntLine"], m2["IntLine"] = m2["IntLine"], m1["IntLine"]
        if not b.update():
            raise RuntimeError(f"端口 {nm} IntLine 交换 update 失败")
        hit.add(nm)
    if hit != targets:
        raise RuntimeError(f"端口边界未找到: {sorted(targets - hit)}")


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                    encoding="utf-8")


def run_point(point: dict) -> dict:
    """单点全流程（断点续跑：point.json status=ok 且 PASS/FAIL 即跳）。"""
    plan = build_point_plan(point)
    tag = plan["tag"]
    pdir = OUT_DIR / tag
    pdir.mkdir(parents=True, exist_ok=True)
    out_json = pdir / "point.json"
    if out_json.exists():
        with contextlib.suppress(Exception):
            prev = json.loads(out_json.read_text(encoding="utf-8"))
            if prev.get("status") == "ok" and prev.get("verdict") in ("PASS", "FAIL"):
                log(f"[{tag}] 已有完档（{prev.get('verdict')}），跳过（断点续跑）")
                return prev
    t0 = time.time()
    rec: dict = {"gate": "kj_even_p2_sweep",
                 "criteria": CRITERIA_REL, "tag": tag,
                 "point": {k: plan[k] for k in
                           ("u", "g", "w_mm", "s_mm", "in_domain", "note")},
                 "geom": plan["geom"], "kj": plan["kj"],
                 "eps_envelope": plan["eps_envelope"],
                 "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    h = None
    try:
        h = _new_project(tag, pdir)
        _build_pair(h, plan["geom"])
        levels = []
        for ds, mp in LEVELS:
            levels.append(_solve_read(h, ds, mp, READ_CHAR_IMP, "W0"))
            rec["levels"] = levels
            _write_json(out_json, rec)
        # 模序识别（β 大=even）；反序则交换 IntLine（逐档识别对交换后模号
        # 重排免疫，v2 §一.4；IntLine 与模物理角色配对仍须正确——Zvi 读数
        # 消费电压路径）
        pd1 = levels[0]["port_data"]["P1"]["Gamma"]
        me, mo = identify_modes({1: _cx(pd1.get("1")), 2: _cx(pd1.get("2"))})
        rec["mode_map"] = {"even": me, "odd": mo}
        rec["mode_line_swap"] = (me != 1)
        if me != 1:
            _set_ports_int_line_swap(h, ("P1", "P2"))
            log(f"[{tag}] 模序与声明相反 → IntLine 已交换（even=Mode{me}）")
        width_runs = []
        for i in (1, 2):
            h["pw"] = f"{plan['geom']['port_w_mm'][i]:.6f}mm"
            width_runs.append(_solve_read(h, *LEVELS[-1], READ_CHAR_IMP, f"W{i}"))
            rec["width_runs"] = width_runs
            _write_json(out_json, rec)
        rec.update(judge_point(rec))
        rec["status"] = "ok"
    except Exception as exc:
        rec["status"] = "error"
        rec["fatal"] = repr(exc)
        rec["verdict"] = "UNKNOWN"
        log(f"[{tag}] ERROR: {exc!r}")
    finally:
        if h is not None:
            _release(h)
    rec["budget"] = {"wall_min": round((time.time() - t0) / 60.0, 1)}
    rec["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _write_json(out_json, rec)
    log(f"[{tag}] verdict={rec.get('verdict')} wall={rec['budget']['wall_min']}min")
    return rec


def _build_z_half(h, geom: dict) -> None:
    """z 半模型（P1 even_z 同族几何：仅耦合段+PMC 墙+端口切耦合线），
    宽度阶梯为设计变量 zport_w；本档为对照非主判。"""
    _add_material(h)
    h.modeler.model_units = "mm"
    w, s = geom["w_mm"], geom["s_mm"]
    w0 = geom["port_w_mm"][0]
    ax = w0 / 2.0 + 2.0 * H_MM
    top = AIR_TOP_H * H_MM
    ay = L_LINE_MM / 2.0
    h.modeler.create_box(origin=[f"{-ax}mm", f"{-ay}mm", "0mm"],
                         sizes=[f"{ax}mm", f"{2 * ay}mm", f"{H_MM}mm"],
                         name="Sub", material="rfauto_m366_kjp2")
    h.modeler.create_box(origin=[f"{-ax}mm", f"{-ay}mm", "0mm"],
                         sizes=[f"{ax}mm", f"{2 * ay}mm", "0mm"],
                         name="Gnd", material="pec")
    xa = -(w + s) / 2.0
    h.modeler.create_box(origin=[f"{xa - w / 2.0}mm", f"{-ay}mm", f"{H_MM}mm"],
                         sizes=[f"{w}mm", f"{2 * ay}mm", "0mm"],
                         name="line_a", material="pec")
    h.assign_perfecte_to_sheets(assignment=["Gnd", "line_a"], name="MetalPEC")
    h.modeler.create_rectangle(orientation="YZ", origin=["0mm", f"{-ay}mm", "0mm"],
                               sizes=[f"{2 * ay}mm", f"{top}mm"], name="SymWall")
    h.assign_perfecth_to_sheets(assignment=["SymWall"], name="SymH")
    h.modeler.create_box(origin=[f"{-ax}mm", f"{-ay}mm", "0mm"],
                         sizes=[f"{ax}mm", f"{2 * ay}mm", f"{top}mm"],
                         name="Air", material="vacuum")
    h.modeler.subtract("Air", ["Sub", "Gnd", "line_a"])
    h.modeler["Air"].solve_inside = True
    _radiate(h, ax, top)
    h["zport_w"] = f"{HALF_LADDER_MM[0]:.6f}mm"
    hgt = HALF_PORT_H * H_MM
    for name, y_mm in (("P1", -ay), ("P2", ay)):
        h.modeler.create_rectangle(orientation="ZX",
                                   origin=["-zport_w", f"{y_mm}mm", "0mm"],
                                   sizes=[f"{hgt}mm", "zport_w"],
                                   name=name + "sheet")
        port_face = h.modeler.get_object_faces(name + "sheet")[0]
        h.wave_port(assignment=port_face, name=name, modes=1, impedance=50.0,
                    renormalize=False, characteristic_impedance="Zpv",
                    integration_line=[[f"{xa}mm", f"{y_mm}mm", "0mm"],
                                      [f"{xa}mm", f"{y_mm}mm", f"{H_MM}mm"]])
    setup = h.create_setup(name="Setup1")
    setup.props["Frequency"] = f"{F_PROBE_GHZ}GHz"
    setup.props["MaxDeltaS"] = HALF_DS
    setup.props["MaximumPasses"] = HALF_MP
    setup.update()


def run_half_model(point: dict) -> dict:
    """可选对照档：Y1 z 半模型 {6,10,15,20}mm 阶梯（P1 even_z 同族，对照非主判）。"""
    plan = build_point_plan(point)
    tag = f"{plan['tag']}_half"
    pdir = OUT_DIR / tag
    pdir.mkdir(parents=True, exist_ok=True)
    out_json = pdir / "point.json"
    if out_json.exists():
        with contextlib.suppress(Exception):
            prev = json.loads(out_json.read_text(encoding="utf-8"))
            if prev.get("status") == "ok":
                log(f"[{tag}] 已有完档，跳过")
                return prev
    t0 = time.time()
    rec: dict = {"gate": "kj_even_p2_half",
                 "criteria": CRITERIA_REL, "tag": tag,
                 "kj": plan["kj"], "geom": plan["geom"],
                 "widths_mm": list(HALF_LADDER_MM),
                 "note": "对照非主判（P1 §8.2 悬案：半模型读数随宽是否收敛）",
                 "started": time.strftime("%H:%M:%S")}
    h = None
    try:
        h = _new_project(tag, pdir)
        _build_z_half(h, plan["geom"])
        levels = []
        rec["levels"] = levels
        rec["charimp_runs"] = {}
        for i, w in enumerate(HALF_LADDER_MM):
            h["zport_w"] = f"{w:.6f}mm"
            cis = ("Zpv",) if i < len(HALF_LADDER_MM) - 1 \
                else ("Zpv", "Zpi", "Zvi")
            for ci in cis:
                lv = _solve_read(h, HALF_DS, HALF_MP, ci, f"W{w:g}",
                                 n_modes=1)
                lv["port_w_mm"] = w
                if ci == "Zpv":
                    levels.append(lv)
                rec["charimp_runs"][f"W{w:g}:{ci}"] = lv
                _write_json(out_json, rec)
        rec.update(judge_half_model(rec))
        rec["status"] = "ok"
    except Exception as exc:
        rec["status"] = "error"
        rec["fatal"] = repr(exc)
        log(f"[{tag}] ERROR: {exc!r}")
    finally:
        if h is not None:
            _release(h)
    rec["budget"] = {"wall_min": round((time.time() - t0) / 60.0, 1)}
    _write_json(out_json, rec)
    log(f"[{tag}] verdict={rec.get('verdict')} wall={rec['budget']['wall_min']}min")
    return rec


# ── dry-run / 聚合 / CLI ─────────────────────────────────────────────────


def dry_run(selected: list[dict]) -> dict:
    """只渲染点表+预算+schema，零 HFSS import（主代理冒烟用）。"""
    plans = [build_point_plan(p) for p in selected]
    payload = {
        "gate": "kj_even_p2_dryrun", "criteria": CRITERIA_REL,
        "read_char_imp": READ_CHAR_IMP,
        "hfss_touched": False, "version": VERSION, "f_ghz": F_PROBE_GHZ,
        "levels": [list(x) for x in LEVELS],
        "points": plans, "budget": budget_estimate(len(plans), solves_per_point()),
        "half_model_budget": budget_estimate(
            1, len(HALF_LADDER_MM) + 2),
        "schema": record_schema(),
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "p2_dryrun.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    log("=== P2 dry-run 点表（零真机）===")
    for p in plans:
        g = p["geom"]
        log(f"{p['tag']:8s} w={p['w_mm']:.6f} s={p['s_mm']:.6f} "
            f"域内={p['in_domain']} W0={g['port_w_mm'][0]:.3f} "
            f"W2={g['port_w_mm'][2]:.3f}mm "
            f"KJ Z0e={p['kj']['z0e_ohm']:.4f} Z0o={p['kj']['z0o_ohm']:.4f} "
            f"env=[{p['eps_envelope'][0]:.4f},{p['eps_envelope'][1]:.4f}] "
            f"solves={p['solves_per_point']}")
    b = payload["budget"]
    log(f"预算：{b['n_solves']} 解 → 核心 {b['core_min'][0]:.0f}–"
        f"{b['core_min'][1]:.0f}min ×1.5 → "
        f"{b['band_min_with_margin'][0]:.0f}–{b['band_min_with_margin'][1]:.0f}min "
        f"（预期 {b['expected_min']:.0f}min）")
    log(f"dry-run JSON 已落盘: {WORK / 'p2_dryrun.json'}")
    return payload


def summarize(results: list[dict]) -> dict:
    """战役聚合（criteria §三判定聚合；域内 4 点主判，域外 3 点参考）。"""
    main = [r for r in results if r.get("point", {}).get("in_domain")]
    ref = [r for r in results if not r.get("point", {}).get("in_domain")]
    v_main = [r.get("verdict") for r in main]
    overall = ("PASS" if v_main and all(v == "PASS" for v in v_main)
               else "FAIL" if any(v == "FAIL" for v in v_main) else "UNKNOWN")
    return {
        "gate": "kj_even_p2_summary",
        "criteria": CRITERIA_REL,
        "main_points": {r["tag"]: {"verdict": r.get("verdict"),
                                   "failed": r.get("failed"),
                                   "unknown": r.get("unknown")} for r in main},
        "reference_points": {r["tag"]: {"verdict": r.get("verdict"),
                                        "info_within_2pct":
                                            r.get("info_within_2pct")}
                             for r in ref},
        "errors": [r["tag"] for r in results if r.get("status") == "error"],
        "overall_verdict": overall,
        "interpretation": {
            "PASS": "HFSS 宽端口收敛到 KJ ±1% → P3 走锚域盒注册+越域告警（P1 §8.5）",
            "FAIL": "P3 再议全波修正系数——须先复跑源 A（Elmer）≥3 点排除"
                    "有限厚度/有限板效应",
            "UNKNOWN": "不判定不发令（测量面/收敛未过，按门注修后重跑）",
        }[overall],
        "finished": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def judge_only(selected: list[dict]) -> dict:
    """--judge-only：纯离线重判已落档点（零求解零 HFSS import）。"""
    results = []
    for p in selected:
        f = OUT_DIR / p["tag"] / "point.json"
        if not f.exists():
            log(f"[{p['tag']}] 无 point.json，跳过")
            continue
        rec = json.loads(f.read_text(encoding="utf-8"))
        for k in ("gates", "verdict", "failed", "unknown", "reason",
                  "informational", "info_band_pct", "info_within_2pct"):
            rec.pop(k, None)
        rec.update(judge_point(rec))
        rec.setdefault("status", "ok")
        _write_json(f, rec)
        results.append(rec)
    summary = summarize(results) if results else {"overall_verdict": "UNKNOWN",
                                                  "criteria": CRITERIA_REL}
    _write_json(WORK / "p2_summary.json", summary)
    log(f"JUDGE_ONLY overall={summary['overall_verdict']}")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="P-KJ-EVEN P2 HFSS 宽端口扫描战役驱动（发射面）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只渲染点表+预算，不启动 HFSS（冒烟用）")
    ap.add_argument("--points", default="all",
                    help="逗号分隔 tag 列表或 all（默认 all）")
    ap.add_argument("--half-model", action="store_true",
                    help="附加 z 半模型对照档（Y1 点，对照非主判）")
    ap.add_argument("--judge-only", action="store_true",
                    help="纯离线重判已落档点（零求解）")
    args = ap.parse_args(argv)

    by_tag = {p["tag"]: p for p in POINTS}
    if args.points == "all":
        selected = list(POINTS)
    else:
        req = [t.strip() for t in args.points.split(",") if t.strip()]
        bad = [t for t in req if t not in by_tag]
        if bad:
            raise SystemExit(f"未知点 tag: {bad}（可选：{sorted(by_tag)}）")
        selected = [by_tag[t] for t in req]

    if args.dry_run:
        dry_run(selected)
        return 0
    if args.judge_only:
        judge_only(selected)
        return 0

    mutex_check()
    log(f"互斥查通过（ansysedt=0 / 他驱动=0）——发射 {len(selected)} 点 × "
        f"{solves_per_point()} 解/点")
    t_start = time.time()
    results = [run_point(p) for p in selected]
    if args.half_model:
        results.append(run_half_model(by_tag["y1"]))
    summary = summarize(results)
    summary["budget"] = {"wall_min": round((time.time() - t_start) / 60.0, 1)}
    _write_json(WORK / "p2_summary.json", summary)
    log(f"OVERALL={summary['overall_verdict']} "
        f"wall={summary['budget']['wall_min']}min")
    print(f"KJP2_{summary['overall_verdict']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
