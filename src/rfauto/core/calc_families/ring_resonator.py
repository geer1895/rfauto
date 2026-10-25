"""微带环形谐振器综合内核（aurora_f W3-S11 席域，R2_core_tier3 §⑤ F3 设计案）。

两键：ring_resonator_synthesize（f1/w/gap → 环平均半径 r_mean + εeff + 50Ω
馈线宽 + 间隙耦合 Qe 设计式）/ ring_resonator_response（模阶谱 + Q 分解
+ 传输频响）。此前 f1→r_mean 链全在
adapters/oe_templates/render_ring.py:74（core 零模块零键零卡，build_kernel_
cards docstring 点名留缺）。本模块为**提升式重构**：``ring_resonator_
design_params`` 函数体自 render_ring 原样下沉（逐字节未动），render_ring
改为消费 core（再导出零改动，#116 不留本地遮蔽副本）；提升前后同参输出
逐位一致（字节级对拍钉 tests/unit/test_w3s11_ring.py，重构前基线
runs/aurora_f/w3s11_ring_parity_baseline.json）。

物理口径（docstring 写死，#1c/#300 出处纪律）
--------------------------------------------------------
- 谐振恒等式（综合正向）：闭环周长 = n·λg → 基模（n=1）
  r_mean = c/(2π·f1·√εeff(f1))，εeff 取微带 HJ 正向（core/synthesis.
  forward_z0，铁律 1c 唯一线宽/介质口径）——render_ring 链逐字节提升。
  近似级别如实（render_ring 段头注同源）：εeff 未含曲率/色散修正（v1）。
  反方向提取 = core/dielectric_extract.ring_resonator_f0_to_er
  （εeff_n = (n·c/(2π·r_mean·f_n))² → er_eff_to_er 反演；两向同仓双源，
  测试回收钉 #118——正演 forward_z0 与反演 er_eff_to_er 色散口径差实测
  ≈0.5%，回收按独立模型如实给带不凑逐位）。
- 间隙耦合 Qe 设计式（串联隙=J-反相器口径，三段链逐段口径）：
  ① 隙电容档：C_g = ε0·εh·w²/g，εh=(1+εr)/2（基板旋转等价，厚基板准
  静态；Gupta 微带不均匀性口径）。**系数 1 量纲估计档，UNVERIFIED 如实
  标**（R2 F3 设计案预授权的「简化电容模型档」v1 落地）：单调性/极限
  行为正确（g→0 对数发散档外按 1/g 发散、g→∞→0、w→0→0），系数非场解
  精度——Benedek-Silvester/Garg-Bahl 拟合与共形场解不在本面（无仓内已
  验证出处，禁凭记忆写常数 #1c），精度由 G2+HFSS 仲裁另批兑现；实测/
  标定注入走 c_gap_ff/qe_per_port 覆盖档（模型链被显式跳过并注记）。
  ② 串联隙 = J-反相器：J = ω0·C_g（MYJ §8.5/Pozar §8.6 小隙口径）。
  ③ 外载 Q（每端口）：Q_e = (π/2)·(Z0/Z_r)/x²，x = J·Z0（与
  calc_families/coupled_line_bpf.py「Q_e=(π/2)(Z0/Z_r)/x_01²」同式同仓
  双源；环带按 Z_r = Z0 设计 → Q_e = (π/2)/x²）。等价串联电容直载分析
  （馈线 Z0 经 1/jωC_g 载入谐振器并联口）给出同式 Q_e=π/(2x²)——两
  推导路径互证。反方向设计：目标 Qe → x = sqrt((π/2)·(Z0/Z_r)/Qe) →
  C_g 目标 → brentq 反解隙宽（C_g 随 g 单调降，测试钉单调性）。
- 模阶谱（response 键）：f_n = n·c/(2π·r_mean·√εeff(f_n))（逐模不动点
  迭代，εeff 按 HJ 正向在模频取值——HJ 弱色散使高次模 f_n 略高于 n·f1，
  偏差随值如实并列；无色散档（εeff 常数）恒等 f_n = n·f1 精确回收）。
- Q 分解（render_ring 段头注模板口径 1/Q_L = 1/Q_d + 1/Q_c + 1/Q_r）：
  Q_d = 1/(tanδ·q·εr/εeff)，q = (εeff−1)/(εr−1)（微带介质损耗填充因子
  式，Gupta/Bahl；均匀介质极限 q·εr/εeff→1 → Q_d→1/tanδ 精确）；
  Q_c = β/(2α_c)，α_c = Rs/(2·Z0·h)·∂lnZ0/∂lnh（Wheeler 增量电感规则，
  导数经 forward_z0 HJ 正向数值中心差分——零新电感公式，单一介质口径
  自洽；光滑壁档，粗糙度修正不在 v1 如实）；β = k0·√εeff（与谐振恒等
  式同 εeff，准静态档自洽）；Q_r（辐射/表面波残差）v1 不建模记零贡献
  （如实），实测注入走 qe_per_port 覆盖档。
- 频响（响应键）：每模 ≡ λ/2 传输谐振器在馈点场腹处的并联等效（模板
  段头注「对置 180° 馈点对各次模均为场腹（全 n 模可激励）」同源）——
  G0,n = π/(2·Z_r·Q0,n) 并联支路跨 J-反相器两端口级联，ABCD 精确化简 =
  串联支路 Z_s = Y/J²（Y = G0·(1+jQ0(f/f_n−f_n/f)) 并联 RLC 精确式），
  S21 = 2Z0/(2Z0+Z_s)、S11 = Z_s/(2Z0+Z_s)。谐振峰闭式
  S21pk = 1/(1+Qe/(2Q0))（对 ABCD 网络数值逐位闭合，#118 双路线钉）；
  Q_L = 1/(1/Q0 + 2/Qe)。频轴按基模（n=1）档评估（理想裁判口径，
  coupled_line_bpf Qe 面同族窄带理想化）；多模复合响应与隙电容加载失谐
  （线环网络实测名义点 −1.6%，dielectric_extract P1 口径同族"开路耦合隙
  相位移出"声明）v1 不建模如实登记，模点走 modes 表。

边界防撞（#222 triple-grep，2026-10-18 实测）
--------------------------------------------------------
- ratrace=环行功分器拓扑（3+1 口网络，非传输谐振器）、
  dielectric_extract=材料提取反方向面（本族综合正向，与其中
  ring_resonator_f0_to_er 同仓双源互证不重复）、combline_resonator/
  coaxial_cavity=腔谐振、cavity_unloaded_q=腔 Q 面——本族只做
  **传输型微带环形谐振器设计**两键。

出处
----
- 环谐振恒等式与 Q 分离口径：render_ring.py §F-A 段头注（F-A M3 方案锚
  docs/research_expansion_20260926.md；环形谐振器标准口径 Joler 2022
  Sensors，经 render_ring 二级转引）。
- 反方向提取：core/dielectric_extract.ring_resonator_f0_to_er docstring
  （同上 Joler 口径）。
- εh=(1+εr)/2 基板旋转等价：Gupta, Microstrip Lines and Slotlines（仓内
  #302 CPS 批同族口径）。
- J-反相器与 Qe 式：MYJ §8.5 / Pozar 4th ed. §8.6；Q_e=(π/2)(Z0/Z_r)/x²
  与 coupled_line_bpf 同式（同仓双源）。
- Wheeler 增量电感规则：H. A. Wheeler, Proc. IRE 1942（教科书转引口径，
  经 Gupta 微带损耗章；数值导数实现自 core/synthesis.forward_z0）。

守卫：f1/r_mean/w/gap/h/z0/频率 >0 且 er>1、tand≥0、n_modes 整数 1..64、
c_gap_ff/qe_target/qe_per_port >0（若给）；response 频轴非空；全部越界
显式 ValueError。

出处（MYJ §8.5；Pozar 4th ed. §8.6；同仓双源）：
- ring_resonator_design_params/ring_resonator_response/
  ring_resonator_synthesize：λ/2 谐振条件 εeff_n 反演两向同仓双源互证
  （模块 docstring 全推导在档）；串联隙 J-反相器 J=ω0·C_g 与
  Q_e=(π/2)(Z0/Z_r)/x²=MYJ §8.5/Pozar §8.6 小隙口径（#122 文献锚在档）。
"""

from __future__ import annotations

import math
from typing import Any

from .registry import C_MM_GHZ, register_calculator
from .thermal import _finite

__all__ = [
    "ring_resonator_design_params",
    "ring_resonator_response",
    "ring_resonator_synthesize",
]

#: 真空光速（m/s）——与 render_ring 提升 source 同名同值常量（单值口径）
_C0_M_S = 299792458.0

#: 真空介电常数（F/m）——隙电容量纲估计档
_EPS0_F_M = 8.8541878128e-12

#: 铜电阻率（Ω·m）——Wheeler α_c 档（core/synthesis.Stackup.rho 缺省同源）
_RHO_CU_OHM_M = 1.724e-8

#: 真空磁导率（H/m）——Wheeler α_c 档
_MU0_H_M = 1.25663706127e-6

#: 50Ω HJ 名义馈线/环带线宽 @2.5GHz rogers4350b（mline/gysel 同源档；
#: 与 render_ring.RING_RESONATOR_W_MM 同值——core 不 import adapters，
#: 双侧以测试互证钉住，50Ω 字面量普查守卫按命名常量豁免）
RING_RESONATOR_W_MM = 1.1134


# ─── 提升面：render_ring 设计链逐字节下沉（单一事实源）──────────────────────

def ring_resonator_design_params(
    f1_ghz: float = 2.5,
    w_mm: float = RING_RESONATOR_W_MM,
    gap_mm: float = 0.4,
    z0_ohm: float = 50.0,
) -> dict[str, Any]:
    """环形谐振器名义设计点（HJ 精算单源，#1c——名义值禁手算捷径）。

    设计链（方案 F-A M3 闭式）：目标基模 f1 → 50Ω 馈线宽（inverse_width HJ
    自洽回代）→ 环带线宽名义档下 εeff(f1)（forward_z0 HJ）→
    r_mean = c/(2π·f1·√εeff(f1))（基模 n=1：闭环周长=λg）。
    恒等式由 test_ring_resonator_template 综合反解自洽测试钉住（rtol 1e-9）。
    近似级别：εeff 取直微带 HJ 值，未含曲率/色散修正（v1，见段头注）。
    """
    from rfauto.core.synthesis import Stackup, forward_z0, inverse_width

    sub = Stackup.from_materials_yaml("rogers4350b_h0.508")
    w_feed, _, status = inverse_width(z0_ohm, f1_ghz, sub)
    if status != "ok":
        raise ValueError(f"ring_resonator 馈线宽反解未收敛: {status}")
    _, eeff = forward_z0(w_mm, f1_ghz, sub)
    r_mean_mm = (_C0_M_S / (2.0 * math.pi * f1_ghz * 1e9
                            * math.sqrt(eeff)) * 1e3)
    return {
        "r_mean_mm": r_mean_mm,
        "w_mm": w_mm,
        "gap_mm": gap_mm,
        "feed_w_mm": round(w_feed, 4),
    }


# ─── 间隙耦合/Q 分解闭式（本族内部单源，两键共用）───────────────────────────

def _gap_capacitance_model(gap_mm: float, w_mm: float, er: float) -> float:
    """串联隙电容（F）：C_g = ε0·εh·w²/g，εh=(1+εr)/2——系数 1 量纲估计档
    （UNVERIFIED 如实标，见模块头口径①；单调性/极限行为正确，精度待仲裁
    批兑现）。"""
    eh = 0.5 * (1.0 + er)
    return _EPS0_F_M * eh * (w_mm * w_mm) / gap_mm * 1e-3


def _gap_coupling_block(gap_mm: float, w_mm: float, f_ghz: float,
                        z0_ohm: float, er: float,
                        c_gap_ff: float | None) -> dict[str, Any]:
    """间隙耦合链（C_g → J=ω0·C_g → x=J·Z0 → Q_e=(π/2)/x²，Z_r=Z0 口径）。
    c_gap_ff 覆盖档给出时模型链被显式跳过（model_used=False 注记）。"""
    if c_gap_ff is not None:
        cg = float(c_gap_ff) * 1e-15
        model_used = False
    else:
        cg = _gap_capacitance_model(gap_mm, w_mm, er)
        model_used = True
    j_inv = 2.0 * math.pi * f_ghz * 1e9 * cg
    x_jz0 = j_inv * z0_ohm
    qe = 0.5 * math.pi / (x_jz0 * x_jz0)
    return {"c_gap_f": cg, "j_inv_s": j_inv, "x_jz0": x_jz0,
            "qe_per_port": qe, "model_used": model_used}


def _wheeler_alpha_c_np_m(w_mm: float, f_ghz: float, er: float,
                          h_mm: float) -> float:
    """微带导体衰减 α_c（Np/m）：Wheeler 增量电感规则
    α_c = Rs/(2·Z0·h)·∂lnZ0/∂lnh——∂lnZ0/∂lnh 经 forward_z0 HJ 正向
    中心差分（tand=0 直构叠层=无损 Z0 口径，增量电感规则惯例）；光滑壁档
    （粗糙度不进 v1，如实）。"""
    from rfauto.core.synthesis import Stackup, forward_z0

    z0_ref = float(forward_z0(w_mm, f_ghz, Stackup(
        name="ring_alpha_c", epsilon_r=er, thickness_mm=h_mm))[0])
    rel = 1e-3
    z_hi = float(forward_z0(w_mm, f_ghz, Stackup(
        name="ring_alpha_c", epsilon_r=er,
        thickness_mm=h_mm * (1.0 + rel)))[0])
    z_lo = float(forward_z0(w_mm, f_ghz, Stackup(
        name="ring_alpha_c", epsilon_r=er,
        thickness_mm=h_mm * (1.0 - rel)))[0])
    dlnz_dlnh = ((math.log(z_hi) - math.log(z_lo))
                 / (math.log(1.0 + rel) - math.log(1.0 - rel)))
    rs = math.sqrt(math.pi * f_ghz * 1e9 * _MU0_H_M * _RHO_CU_OHM_M)
    return rs / (2.0 * z0_ref * h_mm * 1e-3) * dlnz_dlnh


def _mode_q_decomposition(w_mm: float, f_n_ghz: float, er: float,
                          h_mm: float, tand: float) -> tuple[float, float, float]:
    """单模 Q 分解（Q_d, Q_c, Q_0）。Q_d 走填充因子式、Q_c 走 Wheeler；
    Q_0 = 1/(1/Q_d + 1/Q_c)（Q_r 残差 v1 记零贡献）。"""
    from rfauto.core.synthesis import Stackup, forward_z0

    _, eeff = forward_z0(w_mm, f_n_ghz, Stackup(
        name="ring_q", epsilon_r=er, thickness_mm=h_mm, loss_tangent=tand))
    g_d = 0.0
    if tand > 0.0 and er > 1.0 and eeff > 1.0:
        fill = (eeff - 1.0) / (er - 1.0)
        g_d = float(tand) * fill * er / eeff
    q_d = 1.0 / g_d if g_d > 0.0 else math.inf
    beta = 2.0 * math.pi * f_n_ghz * 1e9 / _C0_M_S * math.sqrt(eeff)
    q_c = beta / (2.0 * _wheeler_alpha_c_np_m(w_mm, f_n_ghz, er, h_mm))
    inv = 0.0
    if math.isfinite(q_d):
        inv += 1.0 / q_d
    inv += 1.0 / q_c
    return q_d, q_c, 1.0 / inv


def _ring_mode_fixed_point(r_mean_mm: float, w_mm: float, n: int,
                           er: float, h_mm: float, tand: float,
                           f_start_ghz: float) -> tuple[float, float]:
    """第 n 模自洽不动点：f_n = n·c/(2π·r_mean·√εeff(f_n))——εeff 按 HJ
    正向在模频取值（弱色散收缩映射，60 次上限、1e-13 收敛阈，确定性）；
    超限未收敛显式 ValueError（W7-S25 P3-2：病态输入不静默出口未自洽
    值——HJ 弱色散下正常域必收敛，此守卫只拦极端 er/h 组合）。"""
    from rfauto.core.synthesis import Stackup, forward_z0

    f = float(f_start_ghz)
    eeff = float(er)
    for _ in range(60):
        eeff = float(forward_z0(w_mm, f, Stackup(
            name="ring_mode", epsilon_r=er, thickness_mm=h_mm,
            loss_tangent=tand))[1])
        f_new = (n * _C0_M_S
                 / (2.0 * math.pi * r_mean_mm * 1e-3 * math.sqrt(eeff))
                 / 1e9)
        if abs(f_new - f) < 1e-13:
            return f_new, eeff
        f = f_new
    raise ValueError(
        "ring_resonator: 模阶不动点 60 次迭代未收敛（末步 |Δf|="
        f"{abs(f - f_start_ghz):.3e} GHz，r_mean={r_mean_mm!r}mm/"
        f"w={w_mm!r}mm/n={n}/er={er!r}/h={h_mm!r}）——病态输入显式拒绝"
        "（不静默出口未自洽值，W7-S25 P3-2）")


# ─── 键 1：ring_resonator_synthesize（f1/w/gap → r_mean + Qe 设计式）────────

@register_calculator(
    "ring_resonator_synthesize",
    "微带环形谐振器综合：目标基模 f1 → 50Ω 馈线宽（inverse_width HJ）→ "
    "εeff(f1)（forward_z0 HJ）→ 环平均半径 r_mean=c/(2π·f1·√εeff)（闭环周长"
    "=λg 恒等式，残差随值报告）+ 间隙耦合 Qe 设计式（串联隙=J-反相器：C_g="
    "ε0·εh·w²/g 系数 1 量纲估计档 UNVERIFIED 如实标（c_gap_ff 覆盖档跳过模型"
    "链）→ J=ω0·C_g → Q_e=(π/2)/x²，与 coupled_line_bpf 同式同仓双源；"
    "qe_target 反解隙宽 brentq）。εeff v1 未含曲率/色散修正。缺省叠层 "
    "rogers4350b（er=3.66/h=0.508/tand=0.0037）与 render_ring 设计链"
    "（materials.yaml）逐位一致（钉）",
    (("f1_ghz", "float GHz 目标基模频率（n=1 闭环周长=λg，>0）"),
     ("w_mm", "float mm 环带线宽（εeff 随之，>0）"),
     ("gap_mm", "float mm 馈线-环带间隙（>0；c_gap_ff/qe_target 覆盖档给出"
      "时仍为几何档评估输入，反解隙宽走 required_gap_mm 出口）"),
     ("z0_ohm", "float Ω 端口/馈线/环带特征阻抗（>0，缺省 50）"),
     ("er", "float 基板相对介电常数（>1，缺省 3.66 rogers4350b）"),
     ("h_mm", "float mm 基板厚度（>0，缺省 0.508）"),
     ("tand", "float 介质损耗正切（≥0，缺省 0.0037 rogers4350b；入 εeff 链"
      "与模板叠层同口径）"),
     ("c_gap_ff", "float 实测/标定隙电容覆盖档（fF，>0，可选）——给出时跳过"
      "量纲估计模型链（model_used=False 注记）"),
     ("qe_target", "float 目标外载 Q（每端口，>0，可选）——给出时反解所需"
      "隙宽 required_gap_mm")),
    required=("f1_ghz", "w_mm", "gap_mm"),
)
def ring_resonator_synthesize(
    f1_ghz: float, w_mm: float, gap_mm: float, z0_ohm: float = 50.0,
    *, er: float = 3.66, h_mm: float = 0.508, tand: float = 0.0037,
    c_gap_ff: float | None = None, qe_target: float | None = None,
) -> dict[str, Any]:
    """CALC 键入口：几何链走提升函数（缺省叠层与 yaml 链逐位一致）+ 间隙
    耦合 Qe 设计式（评估 qe_per_port + 可选设计 required_gap_mm）。"""
    f1 = _finite(f1_ghz, "f1_ghz")
    if f1 <= 0.0:
        raise ValueError(
            f"ring_resonator_synthesize: f1_ghz 必须 >0，得到 {f1!r}")
    w = _finite(w_mm, "w_mm")
    if w <= 0.0:
        raise ValueError(f"ring_resonator_synthesize: w_mm 必须 >0，得到 {w!r}")
    gap = _finite(gap_mm, "gap_mm")
    if gap <= 0.0:
        raise ValueError(
            f"ring_resonator_synthesize: gap_mm 必须 >0，得到 {gap!r}")
    z0 = _finite(z0_ohm, "z0_ohm")
    if z0 <= 0.0:
        raise ValueError(
            f"ring_resonator_synthesize: z0_ohm 必须 >0，得到 {z0!r}")
    er_v = _finite(er, "er")
    if er_v <= 1.0:
        raise ValueError(
            f"ring_resonator_synthesize: er 必须 >1，得到 {er_v!r}")
    h = _finite(h_mm, "h_mm")
    if h <= 0.0:
        raise ValueError(
            f"ring_resonator_synthesize: h_mm 必须 >0，得到 {h!r}")
    tand_v = _finite(tand, "tand")
    if tand_v < 0.0:
        raise ValueError(
            f"ring_resonator_synthesize: tand 必须 ≥0，得到 {tand_v!r}")
    if c_gap_ff is not None:
        cg_ov = _finite(c_gap_ff, "c_gap_ff")
        if cg_ov <= 0.0:
            raise ValueError(
                f"ring_resonator_synthesize: c_gap_ff 必须 >0，得到 {cg_ov!r}")
    if qe_target is not None:
        qe_t = _finite(qe_target, "qe_target")
        if qe_t <= 0.0:
            raise ValueError(
                f"ring_resonator_synthesize: qe_target 必须 >0，得到 {qe_t!r}")

    geom = ring_resonator_design_params(f1, w, gap, z0)
    r_mean = float(geom["r_mean_mm"])
    from rfauto.core.synthesis import Stackup, forward_z0

    _, eeff = forward_z0(w, f1, Stackup(name="ring_synth", epsilon_r=er_v,
                                        thickness_mm=h, loss_tangent=tand_v))
    resid = abs(2.0 * math.pi * (r_mean * 1e-3) * f1 * 1e9
                * math.sqrt(eeff) - _C0_M_S) / _C0_M_S

    coup = _gap_coupling_block(gap, w, f1, z0, er_v, c_gap_ff)
    cg, qe = coup["c_gap_f"], coup["qe_per_port"]

    required_gap: float | None = None
    if qe_target is not None:
        cg_t = (math.sqrt(0.5 * math.pi / float(qe_target)) / z0
                / (2.0 * math.pi * f1 * 1e9))

        def _cg_of(g: float) -> float:
            return _gap_capacitance_model(g, w, er_v)

        lo, hi = 1e-6, w
        if coup["model_used"] is False or _cg_of(lo) < cg_t:
            raise ValueError(
                f"ring_resonator_synthesize: qe_target={float(qe_target):.1f}"
                " 反解不可达（隙宽下限 "
                f"{lo}mm 处模型 C_g={_cg_of(lo) * 1e15:.3f}fF 仍低于目标 "
                f"{cg_t * 1e15:.3f}fF——欠耦合极限；c_gap_ff 覆盖档与反解"
                "互斥）")
        while _cg_of(hi) > cg_t:
            hi *= 2.0
            if hi > 1e4:
                raise ValueError(
                    f"ring_resonator_synthesize: qe_target="
                    f"{float(qe_target):.1f} 超出可达域（隙宽上限发散仍欠耦合）")
        from scipy.optimize import brentq

        required_gap = float(brentq(lambda g: _cg_of(g) - cg_t, lo, hi,
                                    xtol=1e-9))

    notes = [
        f"几何链（提升函数，缺省叠层与 render_ring materials.yaml 链逐位"
        f"一致）：εeff(w={w:.4f}mm, {f1:.4f}GHz)={eeff:.15g} → "
        f"r_mean={r_mean:.12f}mm、馈线宽 {geom['feed_w_mm']:.4f}mm；"
        f"恒等式 2π·r_mean·f1·√εeff=c 残差 {resid:.3e}（构造位精确）",
        "间隙耦合（串联隙=J-反相器口径，"
        + ("c_gap_ff 覆盖档，模型链跳过" if coup["model_used"] is False
           else "C_g=ε0·εh·w²/g 系数 1 量纲估计档 UNVERIFIED")
        + f"）：C_g={cg * 1e15:.3f}fF → J=ω0·C_g={coup['j_inv_s']:.6e}S → "
        f"x=J·Z0={coup['x_jz0']:.6f} → Q_e={qe:.1f}/端口（Z_r=Z0 口径；"
        "两端口对称注入 2/Qe）",
        "近似级别如实：εeff 未含曲率/色散修正（render_ring v1 段头注同源）；"
        "隙电容系数非场解精度（Benedek-Silvester/Garg-Bahl 拟合与共形场解"
        "不在本面，禁凭记忆写常数），精度由 G2+HFSS 仲裁另批兑现；Qe↔隙宽"
        "反解在同模型内自洽",
    ]
    if required_gap is not None:
        notes.append(
            f"设计方向：目标 Qe={float(qe_target):.1f}/端口 → 所需隙宽 "
            f"required_gap_mm={required_gap:.6f}（brentq，模型 C_g 随 g 单调降）")
    return {
        "f1_ghz": f1, "w_mm": w, "gap_mm": gap, "z0_ohm": z0,
        "er": er_v, "h_mm": h, "tand": tand_v,
        "r_mean_mm": r_mean, "feed_w_mm": float(geom["feed_w_mm"]),
        "eeff": eeff, "identity_residual": resid,
        "c_gap_ff": cg * 1e15, "j_inv_s": coup["j_inv_s"],
        "x_jz0": coup["x_jz0"], "qe_per_port": qe,
        "gap_model_used": coup["model_used"],
        "required_gap_mm": required_gap,
        "notes": notes,
    }


# ─── 键 2：ring_resonator_response（模阶谱 + Q 分解 + 传输频响）─────────────

@register_calculator(
    "ring_resonator_response",
    "微带环形谐振器响应：模阶谱 f_n=n·c/(2π·r_mean·√εeff(f_n))（逐模不动点"
    "，HJ 弱色散偏差如实并列）+ Q 分解（1/Q_L=1/Q_d+1/Q_c+1/Q_r，Q_d 填充"
    "因子式/Q_c Wheeler 增量电感规则经 forward_z0 数值导数/Q_r v1 记零）+ "
    "传输频响（每模 ≡ λ/2 谐振器跨 J-反相器两端口，ABCD 精确化简为串联支路"
    "求和；谐振峰闭式 S21pk=1/(1+Qe/(2Q0)) 与网络数值逐位闭合 #118 双路线；"
    "Q_L=1/(1/Q0+2/Qe)）。幅度 dB 标量面（G15 口径）",
    (("r_mean_mm", "float mm 环平均半径（ring_resonator_synthesize 出口或"
      "实测几何，>0）"),
     ("w_mm", "float mm 环带线宽（>0）"),
     ("freq_ghz", "array GHz 频率轴（>0 非空；基模 n=1 档响应评估域——理想"
      "裁判口径，多模谐振点走 modes 表）"),
     ("er", "float 基板相对介电常数（>1，缺省 3.66）"),
     ("h_mm", "float mm 基板厚度（>0，缺省 0.508）"),
     ("tand", "float 介质损耗正切（≥0，缺省 0.0037）"),
     ("z0_ohm", "float Ω 端口/环带特征阻抗（>0，缺省 50）"),
     ("gap_mm", "float mm 馈线-环带间隙（>0，缺省 0.4；仅入 Qe 量纲估计档，"
      "qe_per_port/c_gap_ff 覆盖档给出时不进 Qe 链）"),
     ("n_modes", "int 模阶数上限（整数 1..64，缺省 3）"),
     ("c_gap_ff", "float 实测/标定隙电容覆盖档（fF，>0，可选）"),
     ("qe_per_port", "float 每端口外载 Q 覆盖档（>0，可选——实测耦合注入，"
      "优先级高于 c_gap_ff/隙模型）")),
    required=("r_mean_mm", "w_mm", "freq_ghz"),
)
def ring_resonator_response(
    r_mean_mm: float, w_mm: float, freq_ghz: list,
    *, er: float = 3.66, h_mm: float = 0.508, tand: float = 0.0037,
    z0_ohm: float = 50.0, gap_mm: float = 0.4, n_modes: int = 3,
    c_gap_ff: float | None = None, qe_per_port: float | None = None,
) -> dict[str, Any]:
    """模阶谱 + Q 分解 + 复合传输响应（幅度 dB 面，谐振点/Q 随值并列）。"""
    rm = _finite(r_mean_mm, "r_mean_mm")
    if rm <= 0.0:
        raise ValueError(
            f"ring_resonator_response: r_mean_mm 必须 >0，得到 {rm!r}")
    w = _finite(w_mm, "w_mm")
    if w <= 0.0:
        raise ValueError(f"ring_resonator_response: w_mm 必须 >0，得到 {w!r}")
    er_v = _finite(er, "er")
    if er_v <= 1.0:
        raise ValueError(f"ring_resonator_response: er 必须 >1，得到 {er_v!r}")
    h = _finite(h_mm, "h_mm")
    if h <= 0.0:
        raise ValueError(f"ring_resonator_response: h_mm 必须 >0，得到 {h!r}")
    tand_v = _finite(tand, "tand")
    if tand_v < 0.0:
        raise ValueError(
            f"ring_resonator_response: tand 必须 ≥0，得到 {tand_v!r}")
    z0 = _finite(z0_ohm, "z0_ohm")
    if z0 <= 0.0:
        raise ValueError(
            f"ring_resonator_response: z0_ohm 必须 >0，得到 {z0!r}")
    gap = _finite(gap_mm, "gap_mm")
    if gap <= 0.0:
        raise ValueError(
            f"ring_resonator_response: gap_mm 必须 >0，得到 {gap!r}")
    if not isinstance(n_modes, int) or isinstance(n_modes, bool) \
            or not 1 <= n_modes <= 64:
        raise ValueError(
            f"ring_resonator_response: n_modes 须整数 1..64，得到 {n_modes!r}")
    if c_gap_ff is not None:
        cg_ov = _finite(c_gap_ff, "c_gap_ff")
        if cg_ov <= 0.0:
            raise ValueError(
                f"ring_resonator_response: c_gap_ff 必须 >0，得到 {cg_ov!r}")
    if qe_per_port is not None:
        qe_ov = _finite(qe_per_port, "qe_per_port")
        if qe_ov <= 0.0:
            raise ValueError(
                f"ring_resonator_response: qe_per_port 必须 >0，得到 {qe_ov!r}")
    freqs = [float(v) for v in freq_ghz]
    if not freqs:
        raise ValueError("ring_resonator_response: freq_ghz 不能为空")
    if any(f <= 0.0 for f in freqs):
        raise ValueError("ring_resonator_response: 频率须 >0")

    # 基模不动点（n=1），随后各模自 n·f1 起步
    f_start = C_MM_GHZ / (2.0 * math.pi * rm * math.sqrt(er_v))
    f1, _eeff1 = _ring_mode_fixed_point(rm, w, 1, er_v, h, tand_v, f_start)

    coup = _gap_coupling_block(gap, w, f1, z0, er_v, c_gap_ff)
    qe_source = ("qe_per_port 实测覆盖档" if qe_per_port is not None else
                 ("c_gap_ff 覆盖档，模型链跳过" if c_gap_ff is not None else
                  "C_g=ε0·εh·w²/g 系数 1 量纲估计档 UNVERIFIED"))

    modes: list[dict[str, Any]] = []
    for n in range(1, n_modes + 1):
        f_n, eeff_n = _ring_mode_fixed_point(rm, w, n, er_v, h, tand_v,
                                             n * f1)
        q_d, q_c, q0 = _mode_q_decomposition(w, f_n, er_v, h, tand_v)
        if qe_per_port is not None:
            qe = float(qe_per_port)
        else:
            x_n = 2.0 * math.pi * f_n * 1e9 * coup["c_gap_f"] * z0
            qe = 0.5 * math.pi / (x_n * x_n)
        q_l = 1.0 / (1.0 / q0 + 2.0 / qe)
        # 串联支路口径下的谐振峰（=ABCD 网络数值，闭式互证见 s21_pk_closed）
        g0 = math.pi / (2.0 * z0 * q0)
        x = math.sqrt(0.5 * math.pi / qe)  # 由 Qe=(π/2)/x² 反演（Z_r=Z0）
        j_inv = x / z0
        s21_pk = abs(2.0 * z0 / (2.0 * z0 + g0 / (j_inv * j_inv)))
        s21_pk_closed = 1.0 / (1.0 + qe / (2.0 * q0))
        modes.append({
            "n": n, "f_n_ghz": f_n, "eeff": eeff_n,
            "q_d": None if not math.isfinite(q_d) else q_d, "q_c": q_c,
            "q0": q0, "qe_per_port": qe, "q_l": q_l,
            "bw_mhz": f_n / q_l,
            "s21_pk": s21_pk, "s21_pk_closed": s21_pk_closed,
            "s21_pk_rel_dev": abs(s21_pk - s21_pk_closed) / s21_pk_closed,
        })
    base = modes[0]

    # 复合响应＝基模（n=1）档 ABCD 网络（理想裁判口径，见模块头「频响」节）
    f_b, q0_b, qe_b = f1, float(base["q0"]), float(base["qe_per_port"])
    g0_b = math.pi / (2.0 * z0 * q0_b)
    x_b = math.sqrt(0.5 * math.pi / qe_b)
    j2_b = (x_b / z0) ** 2
    s21_db: list[float] = []
    s11_db: list[float] = []
    passivity_dev = 0.0
    for f in freqs:
        y_b = g0_b * (1.0 + 1j * q0_b * (f / f_b - f_b / f))
        zs = y_b / j2_b
        s21 = 2.0 * z0 / (2.0 * z0 + zs)
        s11 = zs / (2.0 * z0 + zs)
        s21_db.append(20.0 * math.log10(max(abs(s21), 1e-300)))
        s11_db.append(20.0 * math.log10(max(abs(s11), 1e-300)))
        passivity_dev = max(passivity_dev,
                            1.0 - (abs(s11) ** 2 + abs(s21) ** 2))
    passivity_dev = max(passivity_dev, 0.0)

    disp_dev = [(float(m["f_n_ghz"]) / (float(m["n"]) * f1) - 1.0) * 100.0
                for m in modes]
    notes = [
        f"基模不动点 f1={f1:.9f}GHz（n=1 恒等式构造位精确；r_mean={rm:.9f}"
        f"mm、εeff(f1)={base['eeff']:.9f}）；模阶谱色散偏差（HJ 弱色散，"
        f"f_n 相对 n·f1）："
        + "、".join(f"n={m['n']}:{d:+.3f}%" for m, d in zip(modes, disp_dev,
                                                            strict=True)),
        f"Q 分解（基模）：1/Q_L=1/Q_d+1/Q_c+1/Q_r → Q_d="
        f"{base['q_d'] if base['q_d'] is not None else '∞（无损档）'}、"
        f"Q_c={base['q_c']:.1f}（Wheeler 增量电感规则，光滑壁）、Q0="
        f"{base['q0']:.1f}、Q_e={base['qe_per_port']:.1f}/端口（{qe_source}）、"
        f"Q_L={base['q_l']:.1f}、谐振峰 S21pk={base['s21_pk_closed']:.6f}"
        f"（{20.0 * math.log10(base['s21_pk_closed']):.2f}dB；闭式 1/(1+"
        f"Qe/2Q0) 与 ABCD 网络数值逐位闭合，rel_dev="
        f"{base['s21_pk_rel_dev']:.1e}）",
        "近似级别如实：εeff 未含曲率修正（render_ring v1 同源）；隙电容系数"
        "非场解精度（Garg-Bahl 拟合与共形场解不在本面，实测注入走 c_gap_ff/"
        "qe_per_port 覆盖档）；Q_r（辐射/表面波残差）v1 记零贡献；频响=基模"
        "档理想裁判（隙电容加载失谐与多模复合响应 v1 不建模——线环网络实测"
        "名义点失谐 −1.6%，dielectric_extract P1「开路耦合隙相位移出」同族"
        "声明；模点见 modes 表）",
    ]
    return {
        "r_mean_mm": rm, "w_mm": w, "er": er_v, "h_mm": h, "tand": tand_v,
        "z0_ohm": z0, "gap_mm": gap, "n_modes": n_modes,
        "f1_ghz": f1,
        "q_d_base": base["q_d"], "q_c_base": base["q_c"],
        "q0_base": base["q0"], "qe_per_port_base": base["qe_per_port"],
        "q_l_base": base["q_l"],
        "s21_pk_base": base["s21_pk"],
        "s21_pk_closed_base": base["s21_pk_closed"],
        "s21_pk_rel_dev_base": base["s21_pk_rel_dev"],
        "modes": modes,
        "n_points": len(freqs), "freq_ghz": freqs,
        "s21_db": s21_db, "s11_db": s11_db,
        "passivity_residual_max": passivity_dev,
        "notes": notes,
    }
