"""antenna2 天线族 II（monopole/pifa/ifa/loop/helix/slot）（AU-1 自 openems_templates.py 机械拆分，2026-09-30；函数体逐字节未动）。"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass
from . import _nominal_width  # 50Ω 标称线宽单源（XC-W，惰性：取属性才算）
from .closedform import _ant2_eps_eff
from .registry import _DEFAULT_SUB, TEMPLATE_META, TEMPLATE_NOMINAL

# ═══════════════════════════════════════════════════════════════════════════════
# §10.3 C1 天线族 II：单极子(monopole)/PIFA/IFA/环形(loop)/螺旋(helix)/缝隙(slot)
# ——贴片锚向变形扩展的六个辐射模板（2026-09-14 增量；同日合流轮正式注册进
# TEMPLATE_META/TEMPLATE_NOMINAL——注册四件套 docs/templates/<t>/meta.yaml、
# test_template_geometry_audit.EXPECTED_TEMPLATES、fake_adapter 派发
# _antenna2_sparams、models/template_specs _register_antenna2 已补齐；注册动作
# 见 ANTENNA2_NOMINAL 之后的赋值块，钉在 test_antenna2_templates.py::
# test_antenna2_registered_in_registry）
# ═══════════════════════════════════════════════════════════════════════════════
# ── 理论核验轮（口径/来源逐条；裁判=独立闭式，不自证；#206 纪律）──
# 1) 单极子：像理论（Balanis《Antenna Theory》4ed monopole = PEC 地面上方
#    半偶极子）⇒ 一阶谐振长 λ0/4：L = c/(4·f0)。细带端效应使真机谷位低于
#    设计频率（同 dipole 58mm 口径）——设计式不做预补偿，冒烟实测偏差如实
#    记录（#190 范式：引擎常数须经仲裁才能进设计公式）。
#    真机实测（runs/antenna2_smoke/monopole，2026-09-14）：谷 −17.39dB @
#    2.135GHz，端效应偏移 −11.0%（设计点 2.4GHz），窗 ±12% 内 PASS。
# 2) PIFA：**L 路径式定版（2026-09-16）** L = λ0/(4·√εeff(W))（εeff 取 skrf
#    HJ @W，与 patch 谐振轴同口径，铁律 1c）。文献通式 L + W − Ws ≈ λ/4
#    （Ollikainen 1999 / Zürcher & Gardiol）**前提是角部短路板**（电流自短路
#    板沿贴片宽度绕行再折向开路边）；本布局短路板居中（Ws=2 于 W=8 中央），
#    电流不绕行，有效路径≈L——两轮真机实证（
#    antenna2 坑③）：通式标称 L=11.0785 谐振在 2.9GHz 之上 FAIL，L 路径式
#    override 17.08 → −8.79dB@2.26GHz PASS（runs/antenna2_smoke/pifa_override）。
#    Ws 仍是几何输入（短路板宽定馈阻抗/带宽），不进谐振式。馈针位置定匹配
#    （近短路板低阻、远离升高）：标称 pin_back=2mm、pin_y=W/4。
# 3) IFA：PIFA 通式的窄臂退化（W→臂宽）：臂长（自短路板起算）≈ λ0/(4·√εeff)
#    （HJ @臂宽）；馈针-短路板间距 s 定输入阻抗（s 小→低阻），标称 s=2mm，
#    冒烟判读。
# 4) 环形：**自由空间口径（2026-09-16 改造）**——一周长自谐振环 C ≈ λ0
#    （Balanis §5 大环口径；小环电容加载不在本模板）⇒ 方环中心线边
#    a = λ0/4（εeff→1：无基板无地，dipole 同款底 MUR + 域 z 向下延 λ0/4，
#    环面 z=0）；馈口 = 底边中央断口 LumpedPort（dipole 中央馈口同型）。
#    改造动因（像理论，真机实证）：旧贴地口径（z=h 环贴 PEC 地 0.508mm=
#    0.004λ0）镜像反向电流抵消辐射 → R=0.56Ω（电抗过零 2.3825GHz 对但不
#    辐射，runs/antenna2_smoke/loop）。判据改电抗过零（f0±12%）+ 过零处
#    R ≥ 20Ω（对照旧 0.56Ω；S11 −5dB 作次级）——一周长环馈阻抗文献口径
#    ≈100-200Ω，对 50Ω 固有失配，谷深不是谐振判据。
# 5) 螺旋：法向模螺旋单极子（Balanis §9 helical antennas 法向模区）：一阶
#    口径 = 总导线长 k_helix·λ0/4（k_helix=1.3615，2026-09-17 HFSS 同几何仲裁
#    AGREE 定版：λ0/4 口径真机 f_x=3.31GHz（openEMS）/3.2675GHz（HFSS）≠2.4，
#    即 λ0/4 线长高估电长度、谐振偏高——与"慢波使谐振更低"的初始预期相反；
#    K_HELIX 常量与证据链见 helix_pitch_mm 段）；方截面 staircase 渲染（每圈
#    4 直段、四角 1/4 螺距竖板逐级上升——单导线连续路径，无双并联回路）；
#    p = (k_helix·λ0/4 − 4·d·N)/N ≥ 1mm 守卫（d 太大则设计非法，显式报错不静默）。
# 6) 缝隙：地面谐振缝 L = λ0/(2·√εeff_slot)（Balanis §14 slot antennas；
#    Booker 互补原理：缝↔偶极子对偶）；介质单侧加载有效 ε 一阶取半空间
#    均值 (1+εr)/2。真机标定（runs/antenna2_smoke/slot[_override]，
#    2026-09-14，两点）：L=40.9168mm→S21 辐射凹 −16.4dB@2.70GHz
#    （隐含 εeff 1.84）；L=46.036mm→−21.8dB@2.6275GHz（隐含 εeff 1.54，
#    窗内 PASS）——辐射凹指标与缝长非线性，k_slot ∈ [0.66, 0.79]·(1+εr)/2
#    待 HFSS 仲裁后才进设计公式（#190；场偏空气侧=薄基底单侧加载）。
#    锚签名（实证）：过缝辐射负载使 S11 全带平坦（−0.5~-2.8dB，功率辐射
#    不反射）——谐振判据=S21 辐射凹位置+深度，非 S11 谷。
#    地面 = z=0 有限金属板（4 盒拼合、槽区留空）+ 底边界 MUR + z 向下延
#    λ0/4（dipole 同款——槽向下半空间也辐射，PEC 底边界会短路槽）；微带
#    馈线垂直跨槽中心，双 MSLPort 板边端接。
# 通用口径：PIFA/IFA 介质板下方 z-min PEC = 无限大地（patch 官方口径）；
# monopole/helix 无介质板（PEC 地面悬空导体）；loop 自由空间（无板无地、底
# MUR、域 z 向下延 λ0/4，dipole 同款）；六模板全部辐射器件
# （AIR_TOP/AIR_SIDE = λ0/4）。端口铁律自查：馈口盒边全部进网格（#198）、
# 激励向跨度 >0（#174）、单端口模板 _port2=_port1 fallback（patch 口径）。

_ANT2_C_MM_GHZ = 299.792458   # mm·GHz（真空光速，与 core/_HAIRPIN 段同口径）
ANTENNA2_TEMPLATES: tuple[str, ...] = (
    "monopole", "pifa", "ifa", "loop", "helix", "slot")
# 立体器件（无介质板 + 竖直元 → 专项 z 网格/无基板块）
_ANTENNA2_TALL_TEMPLATES: tuple[str, ...] = ("monopole", "helix")
# 自由空间器件（无介质板、无地：底 MUR + 域 z 向下延 λ0/4，dipole 同款）
_ANTENNA2_FREE_SPACE_TEMPLATES: tuple[str, ...] = ("loop",)


# ─── 闭式设计函数（确定性内核：谐振尺寸只由公式给出，非手数）────────────────

def monopole_len_mm(f0_ghz: float) -> float:
    """单极子一阶谐振长 λ0/4（像理论，Balanis monopole = 半偶极子）。"""
    if not float(f0_ghz) > 0.0:
        raise ValueError(f"f0 须正，得 {f0_ghz}")
    return _ANT2_C_MM_GHZ / (4.0 * float(f0_ghz))


def pifa_l_mm(f0_ghz: float, w_mm: float, w_short_mm: float,
              er: float = 3.66, h_mm: float = 0.508) -> float:
    """PIFA 贴片长 L = λ0/(4·√εeff(W))（L 路径式定版，HJ @W）。

    居中短路板下有效电流路径≈L（段首理论核验 2；真机两轮实证），文献通式
    L+W−Ws 的 +W−Ws 项不适用。w_short_mm 只做合法性守卫（Ws≤W 由布局守
    卫），不进谐振式——签名保留以稳住 template_specs/单测调用契约。
    """
    if not (float(f0_ghz) > 0.0 and float(w_mm) > 0.0
            and float(w_short_mm) > 0.0):
        raise ValueError("f0/W/Ws 须正")
    return _ANT2_C_MM_GHZ / (
        4.0 * float(f0_ghz)
        * math.sqrt(_ant2_eps_eff(float(w_mm), float(f0_ghz),
                                  float(er), float(h_mm))))


def ifa_arm_len_mm(f0_ghz: float, w_mm: float = 1.0,
                   er: float = 3.66, h_mm: float = 0.508) -> float:
    """IFA 臂长（短路板起算）≈ λ0/(4·√εeff)（HJ @臂宽；PIFA 窄臂退化）。"""
    if not float(w_mm) > 0.0:
        raise ValueError("臂宽须正")
    return _ANT2_C_MM_GHZ / (
        4.0 * float(f0_ghz)
        * math.sqrt(_ant2_eps_eff(float(w_mm), float(f0_ghz),
                                  float(er), float(h_mm))))


def loop_side_mm(f0_ghz: float, w_mm: float = 1.0,
                 er: float = 3.66, h_mm: float = 0.508) -> float:
    """一周长谐振环方环中心线边 a = λ0/4（自由空间口径 C=4a≈λ0，εeff→1）。

    2026-09-16 自由空间改造：无基板无地（段首理论核验 4），介质加载项退出
    ——w_mm/er/h_mm 保留在签名（守卫 + template_specs/单测调用契约），不进
    谐振式。
    """
    if not (float(f0_ghz) > 0.0 and float(w_mm) > 0.0):
        raise ValueError("f0/环带宽须正")
    return _ANT2_C_MM_GHZ / (4.0 * float(f0_ghz))


#: 法向模螺旋慢波系数（HFSS 同几何仲裁定版，2026-09-17 收尾批，#190 范式）：
#: λ0/4 总线长口径的真机电抗过零 f_x=3.2675GHz（HFSS，真实三维盒/unite/0.3mm）
#: vs 3.3146GHz（openEMS，自动/0.35mm 网格、16.7/50mm 域三重稳健）偏差 1.44% ≤5%
#: ⇒ AGREE；k_helix=f_x(HFSS)/f0=3.2675/2.4（openEMS 基 1.3811 同在门内）。总线长
#: 设计式 = k_helix·λ0/4（谐振随线长一阶反比）。证据链 runs/helix_arbitration/。
K_HELIX = 1.3615


def helix_pitch_mm(f0_ghz: float, d_mm: float, n_turns: int) -> float:
    """法向模螺旋螺距：总导线长 k_helix·λ0/4 = N·(4d + p) 反解 p（守卫 p ≥ 1mm）。"""
    wire = K_HELIX * _ANT2_C_MM_GHZ / (4.0 * float(f0_ghz))
    if not (float(d_mm) > 0.0 and int(n_turns) >= 1):
        raise ValueError("d 须正且 N ≥ 1")
    pitch = (wire - 4.0 * float(d_mm) * int(n_turns)) / int(n_turns)
    if pitch < 1.0:
        raise ValueError(
            f"螺旋设计非法：p={pitch:.3f}mm < 1mm（d·N 过大，压不下 k_helix·λ0/4）")
    return pitch


def slot_len_mm(f0_ghz: float, er: float = 3.66) -> float:
    """地面谐振缝长 λ0/(2·√((1+εr)/2))（Booker 对偶 + 半空间均值口径）。"""
    if not float(er) >= 1.0:
        raise ValueError("εr 须 ≥ 1")
    eps = 0.5 * (1.0 + float(er))
    return _ANT2_C_MM_GHZ / (2.0 * float(f0_ghz) * math.sqrt(eps))


# 各模板标称设计点 @2.4GHz（与闭式设计函数 4 位舍入一致，单测互检；
# 贴片/臂/环带宽=设计输入，εeff 由 HJ 随动）
ANTENNA2_NOMINAL: dict[str, dict[str, Any]] = {
    "monopole": {
        # λ0/4 @2.4GHz = 31.2284（monopole_len_mm 4 位舍入）
        "mon_len_mm": 31.2284, "mon_w_mm": 1.0, "feed_gap_mm": 2.0,
    },
    "pifa": {
        # L = λ0/(4√εeff(8mm)=3.3435) = 17.0785（L 路径式定版；旧通式
        # 17.0785 − 8 + 2 = 11.0785 真机 FAIL，见段注）
        "pifa_l_mm": 17.0785, "pifa_w_mm": 8.0, "pifa_ws_mm": 2.0,
        "pin_back_mm": 2.0, "pin_y_mm": 2.0,
    },
    "ifa": {
        # 臂长 = λ0/(4√εeff(1mm)=2.8336) = 18.5515
        "ifa_arm_mm": 18.5515, "ifa_w_mm": 1.0, "feed_off_mm": 2.0,
    },
    "loop": {
        # 中心线方边 = λ0/4（自由空间口径，monopole 同数）= 31.2284；旧贴地
        # λg/4=18.5515 口径 R=0.56Ω 不辐射（见段注）
        "loop_side_mm": 31.2284, "loop_w_mm": 1.0, "loop_gap_mm": 1.0,
    },
    "helix": {
        # p = (k_helix·31.2284 − 4·3·2)/2 = (42.5174 − 24)/2 = 9.2587（守卫 ≥1mm 过）
        # 旧 λ0/4 口径 3.6142（真机 f_x 3.27-3.31GHz ≠ 2.4，HFSS 仲裁 AGREE 后定版）
        "helix_d_mm": 3.0, "helix_turns": 2, "helix_pitch_mm": 9.2587,
        "helix_w_mm": 0.6, "feed_gap_mm": 2.0,
    },
    "slot": {
        # 缝长 = λ0/(2√2.33) = 40.9168；馈线 = 50Ω HJ 宽
        "slot_l_mm": 40.9168, "slot_w_mm": 2.0,
        # feed_w_mm=50Ω 馈线宽（XC-W 单源：_nominal_width.W50_MM @2.5GHz
        # rogers4350b 逐位同值档；此处字面量落表避免模块导入期 brentq）
        "feed_w_mm": 1.1134, "feed_margin_mm": 12.0,
    },
}

# 各模板元数据（TEMPLATE_META 公约字段；f0=2.4GHz 设计点；单端口集总馈
# n_ports=1、slot 双 MSLPort n_ports=2）。
# ── 真机冒烟判读（runs/antenna2_smoke/<t>/sparams.csv，2026-09-14，扫频
#    1.9-2.9GHz，判据 scripts/smoke_antenna2_anchor.py：谷深门 + f0±12% 窗）──
#   monopole PASS：S11 −17.39dB @2.135GHz（−11.0%，端效应）；Zin 电抗过零
#     2.110GHz R=37.3Ω（Balanis 单极子 36.5Ω 口径吻合）。
#   ifa  PASS：S11 −8.48dB @2.44GHz（+1.7%）；并联型谐振 Zin@谷=103−24jΩ
#     （馈针距短路板 2mm ⇒ R_peak≈100Ω，对 50Ω 过耦合限住谷深；feed_off
#     再近可压向 50Ω）。带外 R≈0 是无耗短路桩馈结构的正常反应，非端口短路
#     （首判"端口被针盒短路→PARTIAL"已被去针复跑证伪：v1/v2 逐点一致）。
#   pifa 旧通式标称 L=11.0785 FAIL：|S11|≥−0.02dB 全带，Zin=0.0+j(3.9→8.6)Ω
#     随 f 线性=纯短路桩电感 ⇒ 谐振在 2.9GHz 之上。**根因（真机实证，两轮）**：
#     ① 去掉同体积金属针盒后 S11 逐点不变——"PEC 针盒短路端口"假设证伪；
#     ② override pifa_l_mm=17.08（=λ0/(4√εeff(W))，仅 L 路径口径）→ S11
#     −8.79dB @2.26GHz（−5.8%）PASS、Zin@谷=105−14jΩ、solve 264s（vs 非谐振
#     34s）。即 L+W−Ws=λ/4 通式假定角部短路板（电流绕行贴片宽度），而本
#     布局短路板居中（Ws=2 于 W=8 中央）电流不绕行，有效路径≈L。
#     **定版（2026-09-16）**：设计式改 L 路径式 pifa_l_mm=λ0/(4√εeff(W))，
#     标称 17.0785（与 PASS 的 override 17.08 差 0.0015mm=0.009%，真机证据
#     直接沿用，runs/antenna2_smoke/pifa_override），fake 逆/单测/meta 同步。
#   loop 旧贴地口径（λg/4=18.5515，z=h 贴 PEC 地）FAIL：S11 −0.19dB；Zin 电抗
#     过零 2.3825GHz（−0.7%，谐振长度口径正确）但 R=0.56Ω。**归因（像理论）**：
#     水平环贴 PEC 地 0.508mm（0.004λ0），镜像反向电流抵消辐射 → R_rad→0。
#     **改造（2026-09-16）**：自由空间口径（无板无地、底 MUR、域下延 λ0/4、
#     环面 z=0、a=λ0/4=31.2284），判据改电抗过零 f0±12% + 过零处 R≥20Ω；
#     v2 真机结果见 docs/templates/loop/meta.yaml smoke_note
#     （runs/antenna2_smoke/loop_v2）。
#   helix FAIL：S11 ≤−1.22dB；Zin 全带容性 X∈[−156,−44]Ω 且随 f 单调升
#     → 谐振在 2.9GHz 之上（与段首"慢波使谐振更低"预期相反：λ0/4 总线长
#     口径高估电长度）；R=1.8~6.2Ω 与电小天线 395(h/λ)²≈2Ω 一致——即便谐振
#     也对 50Ω 失配，S11 谷深判据不适用，应改判电抗过零。扩带/仲裁进展见
#     docs/templates/helix/meta.yaml smoke_note（scripts/hfss_helix_arbitration.py）。
#   slot PASS×2：S21 辐射凹 −16.41dB @2.665GHz（L=40.9168）/ −21.76dB @
#     2.6275GHz（L=46.036 override）。Σ|S|² 带边 >1 **已排查（2026-09-16，
#     runs/antenna2_smoke/slot/sparams.csv 实测）**：1.9GHz=1.212、2.9GHz=
#     1.128；>1.02 的点全部落在 1.9-2.08 与 2.82-2.9 两侧，f0±12% 判读窗
#     （2.112-2.688GHz）内 ≤1.008——越限恰在 SetGaussExcite(F0,FC) 高斯激励
#     −20dB 带边（评估带=激励带，uf_inc 归一化分母趋零放大数值噪声），是
#     归一化伪象而非 MSLPort/有限地物理错。判读窗收内带 f0±0.4GHz（激励带
#     内 80%）+ Σ|S|²>1.02 点剔除（smoke_antenna2_anchor.py 全模板通用；slot
#     掩模后 307/321 点，凹位/深度不变），全局 FC 不动（f_max 进 base_m 网格
#     预算，改激励带会漂全部模板网格锚）。
ANTENNA2_META: dict[str, dict[str, Any]] = {
    "monopole": {
        "f0_ghz": 2.4, "n_ports": 1,
        "extraction": "S11 @ LumpedPort 1（PEC 地面 λ0/4 竖直细带单极子：谷位/"
                      "谷深；真机 −17.39dB@2.135GHz，端效应 −11%）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["mon_len_mm", "mon_w_mm", "feed_gap_mm"],
        "topology": "单极子（§10.3 C1 天线族 II）：竖直零厚细带（x 向宽 mon_w，"
                    "y=0 面）自馈口顶 z=feed_gap 起立 λ0/4；馈口=地面 z=0 → 细带"
                    "底缘 LumpedPort（patch 底馈探针同型）；无介质板（像理论口径）",
        "param_semantics": "mon_len_mm=细带长（一阶谐振 λ0/4=c/(4f0)，像理论），"
                           "mon_w_mm=细带宽，feed_gap_mm=馈口高（地面到细带底缘，"
                           "LumpedPort 激励向 z 跨度）",
        "mesh_note": "辐射器件：上方/侧向空气隙 λ0/4；z 网格专项（馈口顶/元件顶"
                     "精确入网，_ANTENNA2_TALL_TEMPLATES）",
    },
    "pifa": {
        "f0_ghz": 2.4, "n_ports": 1,
        "extraction": "S11 @ LumpedPort 1（PIFA 居中短路板 λ/4：谷位/谷深；L 路径式"
                      "定版标称 17.0785 ≈ 真机 override 17.08 → −8.79dB@2.26GHz"
                      "（−5.8%）PASS，Zin@谷=105−14jΩ，见段注）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["pifa_l_mm", "pifa_w_mm", "pifa_ws_mm", "pin_back_mm",
                   "pin_y_mm"],
        "topology": "PIFA（§10.3 C1）：贴片 z=h（L×W）+ +x 边短路板（宽 Ws，z 0→h"
                    " 触地）+ 馈针（距短路板 pin_back，y 偏 pin_y，针顶触贴片、针底"
                    "触地）；LumpedPort 沿针 z 向；基板 + z-min PEC 无限大地",
        "param_semantics": "pifa_l_mm=贴片长 L（L 路径式定版 L=λ0/(4√εeff(W))，HJ"
                           " @W；居中短路板电流不绕行，文献通式 L+W−Ws 的 +W−Ws 项"
                           "不适用，真机两轮实证），pifa_w_mm=贴片宽 W，pifa_ws_mm="
                           "短路板宽 Ws（≤W，几何输入不进谐振式），pin_back_mm=馈针"
                           "距短路板（定匹配），pin_y_mm=馈针 y 偏置（<W）",
        "mesh_note": "辐射器件：上方/侧向空气隙 λ0/4；贴片/短路板/针缘精确入网",
    },
    "ifa": {
        "f0_ghz": 2.4, "n_ports": 1,
        "extraction": "S11 @ LumpedPort 1（IFA λ/4 窄臂：谷位/谷深；真机 −8.48dB"
                      "@2.44GHz（+1.7%）PASS，并联型谐振 R_peak≈103Ω 限谷深）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["ifa_arm_mm", "ifa_w_mm", "feed_off_mm"],
        "topology": "IFA（§10.3 C1，PIFA 窄臂退化）：短路板 x∈[−1,0]（z 0→h）+ 臂"
                    " z=h 自短路板 −x 向伸出 λ/4 + 馈针 x=−feed_off（顶触臂、底"
                    "触地）；LumpedPort 沿针 z 向；基板 + z-min PEC 地",
        "param_semantics": "ifa_arm_mm=臂长（短路板起算 ≈λ0/(4√εeff)，HJ @臂宽），"
                           "ifa_w_mm=臂宽，feed_off_mm=馈针-短路板间距（>1.5mm，"
                           "定输入阻抗）",
        "mesh_note": "辐射器件：上方/侧向空气隙 λ0/4；臂/短路板/针缘精确入网",
    },
    "loop": {
        "f0_ghz": 2.4, "n_ports": 1,
        "extraction": "S11 @ LumpedPort 1（一周长方环，自由空间口径：判据=Zin 电抗"
                      "过零 f0±12% + 过零处 R≥20Ω，S11 −5dB 次级；v2 真机 "
                      "2.6774GHz R=112.02Ω PASS（v1 贴地 0.56Ω 镜像抵消 FAIL），"
                      "见 meta.yaml smoke_note）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["loop_side_mm", "loop_w_mm", "loop_gap_mm"],
        "topology": "环形（§10.3 C1，2026-09-16 自由空间改造）：z=0 方环（中心线边 a、"
                    "带宽 w，顶/左/右全跨含角）+ 底边中央断口 g（馈口位）LumpedPort"
                    " 跨断口（E 沿 x，dipole 中央馈口同型）；无基板无地：底 MUR + "
                    "域 z 向下延 λ0/4（dipole 同款）",
        "param_semantics": "loop_side_mm=方环中心线边 a（一周长 C=4a≈λ0，自由空间"
                           " a=λ0/4，εeff→1），loop_w_mm=环带宽，loop_gap_mm=底边"
                           "断口宽（<a，激励向 x 跨度）",
        "mesh_note": "辐射器件：上方/侧向/下方空气隙 λ0/4；环带缘/断口缘精确入网",
    },
    "helix": {
        "f0_ghz": 2.4, "n_ports": 1,
        "extraction": "S11 @ LumpedPort 1（法向模方螺旋：判据=Zin 电抗容→感上穿 f_x，"
                      "R 电小失配谷深不适用；旧 λ0/4 口径真机 f_x 3.31GHz，HFSS 同几何"
                      "仲裁 3.2675GHz 偏差 1.44% AGREE → k_helix=1.3615 定版，见段注）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["helix_d_mm", "helix_turns", "helix_pitch_mm", "helix_w_mm",
                   "feed_gap_mm"],
        "topology": "螺旋（§10.3 C1）：单导线 staircase 方螺旋（每圈 4 直段各 1/4"
                    " 螺距上升 + 角部竖板，无双并联回路），首圈 A 段即馈口顶，"
                    "总线长 4·d·N + N·p = k_helix·λ0/4（k_helix=1.3615 HFSS 仲裁）；"
                    "馈口=地面 z=0 → 角 A 柱底 LumpedPort；无介质板（PEC 地面悬空导体）",
        "param_semantics": "helix_d_mm=方截面中心线边 d，helix_turns=圈数 N（整数，"
                           "int() 截断），helix_pitch_mm=螺距 p（=(k_helix·λ0/4−4dN)/N "
                           "反解，守卫 ≥1mm），helix_w_mm=导带宽，feed_gap_mm=馈口高",
        "mesh_note": "辐射器件：上方/侧向空气隙 λ0/4；z 网格专项（各圈 1/4 螺距面"
                     "全部入网，_ANTENNA2_TALL_TEMPLATES）",
    },
    "slot": {
        "f0_ghz": 2.4, "n_ports": 2,
        "extraction": "S11/S21 @ MSLPort 1-2（地面谐振缝：S21 辐射凹位置+深度=谐振"
                      "判据，过缝辐射负载使 S11 全带平坦不适用；真机 −16.41dB@"
                      "2.665GHz PASS；判读窗收内带 f0±0.4GHz + Σ|S|²>1.02 点剔除——"
                      "带边 Σ|S|²>1 为高斯激励 −20dB 带边归一化伪象，见段注）",
        "max_time_ns": 30.0, "mesh_resolution_mm": 0.0, "n_segments": None,
        "params": ["slot_l_mm", "slot_w_mm", "feed_w_mm", "feed_margin_mm"],
        "topology": "缝隙（§10.3 C1）：z=0 有限金属地（4 盒拼合、槽 L×Ws 留空）+"
                    " z=h 50Ω 微带馈线 y 向垂直跨槽居中 + 双 MSLPort 板边端接"
                    "（y=∓BOARD，单轴 PML）；底 MUR + z 向下延 λ0/4（槽向下半空间"
                    "也辐射，PEC 底会短路槽）",
        "param_semantics": "slot_l_mm=缝长（λ0/(2√((1+εr)/2))，Booker 对偶+半空间"
                           "均值口径），slot_w_mm=缝宽，feed_w_mm=馈线宽（50Ω HJ），"
                           "feed_margin_mm=板边到馈线手画段起点的馈段长（MSLPort"
                           " 自画，MeasPlaneShift=margin/3）",
        "mesh_note": "辐射器件：上方/侧向/下方空气隙 λ0/4；地缘/槽缘/馈线缘精确入网",
    },
}

# ── 注册（2026-09-14 合流轮）：天线族 II 六模板升格为正式注册模板 ──
# 四处同步：① docs/templates/<t>/meta.yaml ×6；② test_template_geometry_audit
# .EXPECTED_TEMPLATES（18→25，含 coupled_bpf）；③ fake_adapter 派发分支
# （_antenna2_sparams：闭式设计函数精确逆 → 串联谐振一阶模型 / slot 串联
# 并联 RLC 辐射凹）；④ models/template_specs（_register_antenna2）。
# 同对象注册（非拷贝）钉死单一事实源；渲染段零改动。
for _ant2_name in ANTENNA2_TEMPLATES:
    TEMPLATE_META[_ant2_name] = ANTENNA2_META[_ant2_name]
    TEMPLATE_NOMINAL[_ant2_name] = ANTENNA2_NOMINAL[_ant2_name]
del _ant2_name


def antenna2_meta(template: str) -> dict[str, Any]:
    """返回天线族 II 某模板元数据（与 template_meta(t) 同构的便捷别名）。"""
    if template not in ANTENNA2_TEMPLATES:
        raise KeyError(f"非 antenna2 模板: {template}（可用 {ANTENNA2_TEMPLATES}）")
    meta = dict(ANTENNA2_META[template])
    meta["template"] = template
    meta["substrate"] = dict(_DEFAULT_SUB)
    meta["nominal_params"] = dict(ANTENNA2_NOMINAL[template])
    return meta


def _ant2_layout(
    template: str,
    params: dict[str, Any],
    sub: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """C1 天线族 II 单一事实源（mm）：金属盒 / 端口 / z 网格线 / 元件顶。

    渲染段（_ant2_body）、近场加密（_near_points 分支）、z 网格预算
    （render_script z_mesh_block）与离线审计测试（test_antenna2_templates）
    四方消费——单源防漂移（hairpin _hairpin_layout 同制度）。
    盒元组 = (金属属性名, 盒名, x0, y0, z0, x1, y1, z1)；零厚度面合法
    （官方金属面口径），端口激励向跨度恒 >0（#174）。
    """
    sub = sub or _DEFAULT_SUB
    er = float(sub["er"])
    h = float(sub["h_mm"])
    boxes: list[tuple[str, str, float, float, float, float, float, float]] = []
    ports: list[dict[str, Any]] = []
    z_lines: list[float] = []
    element_top = h
    if template == "monopole":
        w = float(params.get("mon_w_mm", 1.0))
        ln = float(params.get("mon_len_mm", 31.2284))
        g = float(params.get("feed_gap_mm", 2.0))
        if not (ln > 0.0 and w > 0.0 and g > 0.0):
            raise ValueError("monopole 几何须正")
        # 竖直细带：x 向宽 w、y=0 零厚面、z 自馈口顶起 λ0/4
        boxes.append(("monopole_strip", "strip", -w / 2, 0.0, g, w / 2, 0.0, g + ln))
        # 馈口：地面（z=0 PEC 边界）→ 细带底缘（patch 底馈探针同型）
        ports.append({"kind": "lumped", "nr": 1, "R": 50.0,
                      "start_mm": (-w / 2, -w / 2, 0.0),
                      "stop_mm": (w / 2, w / 2, g),
                      "exc_dir": "z", "excite": 1})
        z_lines = [0.0, g, g + ln]
        element_top = g + ln
    elif template == "pifa":
        ln = float(params.get("pifa_l_mm", 11.0785))
        w = float(params.get("pifa_w_mm", 8.0))
        ws = float(params.get("pifa_ws_mm", 2.0))
        back = float(params.get("pin_back_mm", 2.0))
        py = float(params.get("pin_y_mm", w / 4))
        t = 1.0   # 短路板厚/馈针边长（mm）
        if not (ln > 0.0 and w > 0.0 and 0.0 < ws <= w and 0.0 < back < ln
                and 0.0 < py < w):
            raise ValueError("pifa 几何超界")
        # 贴片（z=h 顶面）
        boxes.append(("pifa_patch", "patch", -ln / 2, -w / 2, h, ln / 2, w / 2, h))
        # 短路板（+x 边缘，z 0→h 触地）
        boxes.append(("pifa_short", "short", ln / 2 - t, -ws / 2, 0.0,
                      ln / 2, ws / 2, h))
        # 馈针 = LumpedPort 本身（距短路板 back，y 偏 py；端口顶触贴片、底触地
        # ——patch 官方口径"端口即探针"）。不另画同体积金属针盒：2026-09-14
        # 真机 v1（有针盒）/v2（无针盒）S11 逐点一致，针盒对结果无影响，去掉
        # 只为消除"金属盖端口体元"的口径歧义（回归钉 test_pifa_ifa_feed_pin_
        # and_short_touch_ground_line）。标称 FAIL 的真根因见 ANTENNA2_META 段注
        # （居中短路板 ⇒ 有效路径≈L，L+W−Ws 通式不适用）。
        px = ln / 2 - back
        ports.append({"kind": "lumped", "nr": 1, "R": 50.0,
                      "start_mm": (px - t / 2, py - t / 2, 0.0),
                      "stop_mm": (px + t / 2, py + t / 2, h),
                      "exc_dir": "z", "excite": 1})
        z_lines = [0.0, h]
    elif template == "ifa":
        ln = float(params.get("ifa_arm_mm", 18.5515))
        w = float(params.get("ifa_w_mm", 1.0))
        s = float(params.get("feed_off_mm", 2.0))
        t = 1.0
        if not (ln > 0.0 and w > 0.0 and s > 1.5 * t):
            raise ValueError("ifa 几何超界（馈针须与短路板净距 >1.5mm）")
        # 短路板（x∈[−t,0]，z 0→h 触地）
        boxes.append(("ifa_short", "short", -t, -w / 2, 0.0, 0.0, w / 2, h))
        # 臂（z=h 顶面，自短路板 −x 向伸出 λ/4）
        boxes.append(("ifa_arm", "arm", -ln, -w / 2, h, 0.0, w / 2, h))
        # 馈针 = LumpedPort 本身（x=−s，端口顶触臂、底触地；同 pifa 不另画金属
        # 针盒——真机 v1/v2 逐点一致 −8.5dB@2.44GHz，针盒无影响）
        ports.append({"kind": "lumped", "nr": 1, "R": 50.0,
                      "start_mm": (-s - t / 2, -t / 2, 0.0),
                      "stop_mm": (-s + t / 2, t / 2, h),
                      "exc_dir": "z", "excite": 1})
        z_lines = [0.0, h]
    elif template == "loop":
        a = float(params.get("loop_side_mm", 31.2284))
        w = float(params.get("loop_w_mm", 1.0))
        g = float(params.get("loop_gap_mm", 1.0))
        if not (a > 0.0 and w > 0.0 and 0.0 < g < a):
            raise ValueError("loop 几何须 0 < gap < side")
        # 自由空间口径（2026-09-16 改造）：环面 z=0（dipole 振子面同款，无基板
        # 无地、底 MUR、域 z 向下延 λ0/4——旧 z=h 贴 PEC 地口径镜像抵消辐射
        # R=0.56Ω，见 ANTENNA2_META 段注）。方环（中心线 ±a/2，带宽 w）：顶边/
        # 左右竖边全跨（含角），底边中央断口 g（馈口位）
        zl = 0.0
        boxes.append(("loop_top", "top", -a / 2 - w / 2, a / 2 - w / 2, zl,
                      a / 2 + w / 2, a / 2 + w / 2, zl))
        boxes.append(("loop_left", "left", -a / 2 - w / 2, -a / 2 - w / 2, zl,
                      -a / 2 + w / 2, a / 2 + w / 2, zl))
        boxes.append(("loop_right", "right", a / 2 - w / 2, -a / 2 - w / 2, zl,
                      a / 2 + w / 2, a / 2 + w / 2, zl))
        boxes.append(("loop_bot_l", "bot_l", -a / 2 - w / 2, -a / 2 - w / 2, zl,
                      -g / 2, -a / 2 + w / 2, zl))
        boxes.append(("loop_bot_r", "bot_r", g / 2, -a / 2 - w / 2, zl,
                      a / 2 + w / 2, -a / 2 + w / 2, zl))
        # 馈口跨断口（dipole 中央馈口同型零厚面；激励向 x 跨度 = g > 0）
        ports.append({"kind": "lumped", "nr": 1, "R": 50.0,
                      "start_mm": (-g / 2, -a / 2, zl),
                      "stop_mm": (g / 2, -a / 2, zl),
                      "exc_dir": "x", "excite": 1})
        z_lines = [zl]
        element_top = zl
    elif template == "helix":
        d = float(params.get("helix_d_mm", 3.0))
        n = int(params.get("helix_turns", 2))
        p = float(params.get("helix_pitch_mm", 9.2587))
        w = float(params.get("helix_w_mm", 0.6))
        g = float(params.get("feed_gap_mm", 2.0))
        if not (d > 0.0 and n >= 1 and p >= 1.0 and w > 0.0 and g > 0.0):
            raise ValueError("helix 几何须正且螺距 ≥ 1mm")
        # 单导线连续 staircase 螺旋：每圈 4 直段各占 1/4 螺距上升、
        # 角部竖板连接（无双并联回路——closed-ring+单 riser 拓扑是错画）。
        # 中心线方边 d；角 A=(−d/2,−d/2) B=(+d/2,−d/2) C=(+d/2,+d/2)
        # D=(−d/2,+d/2)；turn k 基平面 z_k = g + k·p（首圈 A 段即馈口顶，
        # 无引入段——总线长恰 = 4dN + Np = λ0/4，设计式精确成立）。
        z_a = g
        for k in range(n):
            za = z_a + k * p
            # A 段（沿 +x，y=−d/2 面，z=za）
            boxes.append(("helix", f"t{k}_a", -d / 2, -d / 2 - w / 2, za,
                          d / 2, -d / 2 + w / 2, za))
            # AB 竖板（角 B，z za→za+p/4）
            boxes.append(("helix", f"t{k}_ab", d / 2 - w / 2, -d / 2, za,
                          d / 2 + w / 2, -d / 2, za + p / 4))
            # B 段（沿 +y，x=+d/2 面，z=za+p/4）
            boxes.append(("helix", f"t{k}_b", d / 2 - w / 2, -d / 2,
                          za + p / 4, d / 2 + w / 2, d / 2, za + p / 4))
            # BC 竖板（角 C）
            boxes.append(("helix", f"t{k}_bc", d / 2 - w / 2, d / 2,
                          za + p / 4, d / 2 + w / 2, d / 2, za + p / 2))
            # C 段（沿 −x，y=+d/2 面，z=za+p/2）
            boxes.append(("helix", f"t{k}_c", -d / 2, d / 2 - w / 2,
                          za + p / 2, d / 2, d / 2 + w / 2, za + p / 2))
            # CD 竖板（角 D）
            boxes.append(("helix", f"t{k}_cd", -d / 2 - w / 2, d / 2,
                          za + p / 2, -d / 2 + w / 2, d / 2, za + 3 * p / 4))
            # D 段（沿 −y，x=−d/2 面，z=za+3p/4；终点接下一圈基面）
            boxes.append(("helix", f"t{k}_d", -d / 2 - w / 2, -d / 2,
                          za + 3 * p / 4, -d / 2 + w / 2, d / 2,
                          za + p))
        ports.append({"kind": "lumped", "nr": 1, "R": 50.0,
                      "start_mm": (-d / 2 - w / 2, -d / 2 - w / 2, 0.0),
                      "stop_mm": (-d / 2 + w / 2, -d / 2 + w / 2, g),
                      "exc_dir": "z", "excite": 1})
        z_lines = [0.0, g]
        for k in range(n):
            base = z_a + k * p
            z_lines += [base + p / 4, base + p / 2, base + 3 * p / 4,
                        base + p]
        element_top = z_a + n * p
    elif template == "slot":
        ln = float(params.get("slot_l_mm", 40.9168))
        ws = float(params.get("slot_w_mm", 2.0))
        wf = float(params.get("feed_w_mm", _nominal_width.W50_MM))
        m = float(params.get("feed_margin_mm", 12.0))
        if not (ln > 0.0 and ws > 0.0 and wf > 0.0 and m > 0.0):
            raise ValueError("slot 几何须正")
        # 有限地面（z=0，4 盒拼合、槽区 [±ln/2]×[±ws/2] 留空）
        boxes.append(("slot_gnd", "gnd_ym", -60.0, -60.0, 0.0,
                      60.0, -ws / 2, 0.0))
        boxes.append(("slot_gnd", "gnd_yp", -60.0, ws / 2, 0.0,
                      60.0, 60.0, 0.0))
        boxes.append(("slot_gnd", "gnd_xm", -60.0, -ws / 2, 0.0,
                      -ln / 2, ws / 2, 0.0))
        boxes.append(("slot_gnd", "gnd_xp", ln / 2, -ws / 2, 0.0,
                      60.0, ws / 2, 0.0))
        # 50Ω 微带馈线（z=h 顶面，y 向跨槽居中，两端留 m 馈段给 MSLPort 自画）
        y1 = 60.0 - m
        boxes.append(("slot_feed", "feed_line", -wf / 2, -y1, h,
                      wf / 2, y1, h))
        ports.append({"kind": "msl", "nr": 1, "metal_prop": "slot_feed",
                      "start_mm": (wf / 2, -60.0, h),
                      "stop_mm": (-wf / 2, -y1, 0.0),
                      "prop_dir": "y", "exc_dir": "z", "excite": 1,
                      "meas_shift_mm": m / 3.0})
        ports.append({"kind": "msl", "nr": 2, "metal_prop": "slot_feed",
                      "start_mm": (-wf / 2, 60.0, h),
                      "stop_mm": (wf / 2, y1, 0.0),
                      "prop_dir": "y", "exc_dir": "z", "excite": 0,
                      "meas_shift_mm": m / 3.0})
        z_lines = [0.0, h]
        element_top = h
    else:
        raise ValueError(f"未知 antenna2 模板: {template}")
    return {
        "boxes": boxes,
        "ports": ports,
        "z_lines_mm": sorted(set(z_lines)),
        "element_top_mm": element_top,
        "air_below": template in ("slot", *_ANTENNA2_FREE_SPACE_TEMPLATES),
        "substrate": (template not in _ANTENNA2_TALL_TEMPLATES
                      and template not in _ANTENNA2_FREE_SPACE_TEMPLATES),
        "ground": template not in ("slot", *_ANTENNA2_FREE_SPACE_TEMPLATES),
        "er": er, "h_mm": h,
    }


def _ant2_body(template: str, p: dict[str, Any]) -> str:
    """由 _ant2_layout 单源渲染几何段（金属盒 + 端口 + priority 收口）。

    坐标全部走布局字面量（米），渲染==布局==审计三方一致；单端口模板
    _port2=_port1（patch 单端口 fallback 口径）。
    """
    lay = _ant2_layout(template, p)
    out: list[str] = []
    m = lambda v: repr(float(v) * 1e-3)   # noqa: E731  mm→m 字面量
    metal_names: list[str] = []
    for box in lay["boxes"]:
        prop = box[0]
        if prop not in metal_names:
            metal_names.append(prop)
    for prop in metal_names:
        out.append(f'{prop} = CSX.AddMetal("{prop}")')
    for (prop, name, x0, y0, z0, x1, y1, z1) in lay["boxes"]:
        out.append(f'{prop}.AddBox(({m(x0)}, {m(y0)}, {m(z0)}), '
                   f'({m(x1)}, {m(y1)}, {m(z1)}), priority=10)  # {name}')
    for port in lay["ports"]:
        s, t = port["start_mm"], port["stop_mm"]
        nr = int(port["nr"])
        if port["kind"] == "lumped":
            out.append(
                f'_port{nr} = LumpedPort(CSX, port_nr={nr}, R={port["R"]!r},\n'
                f'                    start=np.array([{m(s[0])}, {m(s[1])}, '
                f'{m(s[2])}]),\n'
                f'                    stop=np.array([{m(t[0])}, {m(t[1])}, '
                f'{m(t[2])}]),\n'
                f'                    exc_dir="{port["exc_dir"]}", '
                f'excite={int(port["excite"])}, priority=5)')
        else:
            out.append(
                f'_port{nr} = MSLPort(CSX, port_nr={nr}, '
                f'metal_prop={port["metal_prop"]},\n'
                f'                 start=np.array([{m(s[0])}, {m(s[1])}, '
                f'{m(s[2])}]),\n'
                f'                 stop=np.array([{m(t[0])}, {m(t[1])}, '
                f'{m(t[2])}]),\n'
                f'                 prop_dir="{port["prop_dir"]}", '
                f'exc_dir="{port["exc_dir"]}", excite={int(port["excite"])},\n'
                f'                 FeedShift=10 * NEAR, '
                f'MeasPlaneShift={float(port["meas_shift_mm"]) * 1e-3!r},\n'
                f'                 priority=10)')
    if len(lay["ports"]) == 1:
        out.append('_port2 = _port1   # 单端口模板：footer fallback 口径')
    for prop in metal_names:
        out.append(f'for _prim in {prop}.GetAllPrimitives():\n'
                   '    if _prim.GetPriority() < 10:\n'
                   '        _prim.SetPriority(10)')
    return "\n".join(out) + "\n"


def _monopole_lines(p: dict[str, Any]) -> str:
    # §10.3 C1 单极子：竖直细带 λ0/4 于 PEC 地面（像理论口径），LumpedPort
    # 底馈（patch 探针同型）；设计式/布局/审计单源 _ant2_layout。
    return _ant2_body("monopole", p)


def _pifa_lines(p: dict[str, Any]) -> str:
    # §10.3 C1 PIFA：贴片+短路板（+x 边）+馈针（patch 底馈同型），
    # 短路板态 λ/4 通式定长（见段首理论核验 2）。
    return _ant2_body("pifa", p)


def _ifa_lines(p: dict[str, Any]) -> str:
    # §10.3 C1 IFA：窄臂+短路板+馈针（PIFA 窄臂退化，λ/4 口径见段首 3）。
    return _ant2_body("ifa", p)


def _loop_lines(p: dict[str, Any]) -> str:
    # §10.3 C1 环形：一周长方环 + 底边中央断口 LumpedPort（dipole 馈口
    # 同型；C≈λ 大环自谐振口径见段首 4）。
    return _ant2_body("loop", p)


def _helix_lines(p: dict[str, Any]) -> str:
    # §10.3 C1 螺旋：单导线 staircase 方螺旋（λ0/4 总线长口径见段首 5；
    # 每圈 4 直段 1/4 螺距逐级上升，无双并联回路）。
    return _ant2_body("helix", p)


def _slot_lines(p: dict[str, Any]) -> str:
    # §10.3 C1 缝隙：有限地面（槽区留空）+ 微带馈线跨槽 + 双 MSLPort
    # （λ0/2 缝谐振口径见段首 6；底 MUR + z 下延由 render_script 专项）。
    return _ant2_body("slot", p)
