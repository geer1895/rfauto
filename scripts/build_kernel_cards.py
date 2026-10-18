#!/usr/bin/env python3
"""XA-8 内核域文档卡生成器（round18 规格 XA-8 首批 5 张 + aurora_e W3-S13
知识面批扩容批一 11 张 + aurora_e W4-S19 知识面批扩容批二 8 张，共 24 张）。

从三源机读聚合生成 docs_site/kernel_cards/<kernel_id>.md（人读聚合面）：
  1. XC-P 精度档案  knowledge/precision_profiles.yaml（首批 10 内核）；
  2. KD-1 出处注册  knowledge/formula_provenance.yaml（按 kernel_file 过滤）；
  3. 内核模块 docstring/AST（物理语义、公式原文、使用边界、公开符号），
     辅以 knowledge/anchors.yaml（analytic-anchor 命中）与 tests/unit、
     service/adapters 的引用扫描（消费拓扑）。

同源纪律（#97 零手写数字 / #122 如实标注 / 铁律 7）：
- 卡内一切计数（KD-1 条目数、公开符号数、test 函数数、XC-P 键清单、
  锚命中数）均构建时实测，禁止手写；
- 手写段仅两处——公式 LaTeX 转写与使用边界注记，每条必须携带 docstring
  **逐字引文**（quote），构建时断言引文在模块源文件中存在（防漂移钉）；
  引文是机器核对载体，LaTeX 与注记是其人读转写；
- 批一 11 卡（W3-S13）按「CALC 键+teaching 块+锚覆盖」数据源完备性选族：
  同源 synthesis.py 七族（mline/wilkinson/branchline/ratrace/patch/hairpin/
  cpw，共享机械节如实重复渲染）+ 专用模块四卡（slotline/coupled_microstrip/
  calc_families.finline/calc_families.wilkinson_unequal，子包 stem 以
  「calc_families/名」形态书写，卡内模块路径/引用扫描自动归一）；
  coupled_microstrip 已入 XC-P——精度域节走「已建档」完整渲染支路（首批
  5 内核仍走「未收录 + UNVERIFIED + 建档入口」支路，不编造分档数字）。
- 批二 8 卡（W4-S19）按任务书点名优先序取「专属 CALC 键或 synthesis 面」
  完备族：atten_pi/atten_t/qwt_multisection/nway_wilkinson/schiffman
  （synthesis.py 同源面+rf_match CALC 键）+ bethe_hole_coupler/gysel_core/
  coupled_line_bpf（calc_families 注册计算器三族）；ring_resonator 留缺
  （无专属综合内核——meta 恒等式+dielectric_extract M3 反方向提取面，
  与 lange/stepped_impedance 批一留缺理由同族）。

用法（venv 内、仓根执行）：
    python scripts/build_kernel_cards.py           # 原地重建全部卡
    python scripts/build_kernel_cards.py --check   # 漂移检查（退出码 1=需重建）

产物确定性：不写时间戳/环境相关内容；键序、遍历序全部显式排序，
tests/unit/test_kernel_cards.py 按「重渲染 == 已提交字节」钉保鲜。
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
XCP_YAML = REPO_ROOT / "knowledge" / "precision_profiles.yaml"
KD1_YAML = REPO_ROOT / "knowledge" / "formula_provenance.yaml"
ANCHORS_YAML = REPO_ROOT / "knowledge" / "anchors.yaml"
TESTS_UNIT_DIR = REPO_ROOT / "tests" / "unit"
CORE_DIR = REPO_ROOT / "src" / "rfauto" / "core"
CONSUMER_DIRS: tuple[tuple[str, Path], ...] = (
    ("service", REPO_ROOT / "src" / "rfauto" / "service"),
    ("adapters", REPO_ROOT / "src" / "rfauto" / "adapters"),
)
CARDS_DIR = REPO_ROOT / "docs_site" / "kernel_cards"
COLLECTOR_TEST_REL = "tests/unit/test_precision_profiles.py"

CARD_BANNER = (
    "<!-- XA-8 内核域文档卡：scripts/build_kernel_cards.py 生成（round18 规格"
    " XA-8）。\n     三源机读聚合：XC-P 精度档案 + KD-1 出处注册 + 模块 "
    "docstring/AST；\n     公式 LaTeX 与使用边界为人工转写段，每条带 docstring "
    "逐字引文钉。\n     勿手改本文件——改源（YAML/docstring/测试面）后重跑生成器，\n"
    "     保鲜门=tests/unit/test_kernel_cards.py（重渲染逐字节比对）。 -->\n"
)


# ─── 手写段载体（每条带逐字引文；构建时断言引文存在于模块源文件） ────────────


@dataclass(frozen=True)
class Formula:
    """一条公式卡目：LaTeX 转写 + docstring 逐字引文（防漂移钉）+ 出处指向。"""

    title: str
    latex: str
    quote: str
    cite: str
    #: "docstring 原文转写"（默认）或 "口径示意（非 docstring 原式，读代码为准）"
    kind: str = "docstring 原文转写"
    quote2: str | None = None  # 可选第二引文（跨行原式拆两条单行引文）


@dataclass(frozen=True)
class Boundary:
    """一条使用边界：docstring 逐字引文 + 人读注记。"""

    quote: str
    note: str


@dataclass(frozen=True)
class DocRef:
    """判据书/规格指针：docstring 引文 + 路径（tracked=True 则测试断存在）。"""

    path: str
    quote: str
    tracked: bool


@dataclass(frozen=True)
class CardSpec:
    kernel_id: str
    tagline: str  # 人工一句物理语义（不含数字）
    modules: tuple[str, ...]  # core 模块 stem（首个=主模块；子包用 calc_families/名）
    primary_entries: tuple[tuple[str, str], ...]  # (module_stem, symbol)
    formulas: tuple[Formula, ...]
    boundaries: tuple[Boundary, ...]
    doc_refs: tuple[DocRef, ...]
    #: 测试面引用扫描的附加命中串（如 CALC 键名——经 run_calculator 间接
    #: 消费、无 import 面的子包内核用；缺省空=纯 import 面扫描）。
    test_face_needles: tuple[str, ...] = ()


# ─── 首批五卡选题（round18 规格 XA-8：macromodel/rwg_mmt/pdn/pce/cascade） ──

SPECS: tuple[CardSpec, ...] = (
    CardSpec(
        kernel_id="macromodel",
        tagline=(
            "把频域 S 参数档案变成电路仿真器可直接挂载的有理极点-留数宏模型，"
            "并用相互独立的裁判（FSV 保真、带内 SVD 无源性、SPICE 回放自检）"
            "回答\u201c这个模型还能不能信\u201d。"
        ),
        modules=("macromodel",),
        primary_entries=(
            ("macromodel", "fit_macromodel"),
            ("macromodel", "model_response"),
            ("macromodel", "replay_spice_subcircuit_s"),
            ("macromodel", "compare_s_matrices"),
            ("macromodel", "request_from_touchstone"),
            ("macromodel", "validate_spice_subcircuit"),
        ),
        formulas=(
            Formula(
                title="向量拟合有理模型（skrf VectorFitting，Gustavsen 谱系）",
                latex=(
                    "S_{ij}(s)=\\sum_{n=1}^{N}\\frac{c_{ij,n}}{s-p_n}"
                    "+d_{ij}+s\\,e_{ij}"
                ),
                quote=(
                    "有理拟合全链使用 skrf 2.1.0 自带 "
                    "``skrf.vectorFitting.VectorFitting``"
                ),
                cite=(
                    "skrf 2.1.0 ``inspect.signature`` 实测口径；确定性"
                    "（固定阶数、无随机初值）——模块 docstring「外部算法（不自造）」节"
                ),
            ),
            Formula(
                title="拟合 RMS（本仓主口径，逐响应+逐频点归一）",
                latex=(
                    "\\mathrm{rms}=\\sqrt{\\mathrm{mean}_{i,j,k}\\,"
                    "\\left|S_{ij}(f_k)-\\hat S_{ij}(f_k)\\right|^2},\\quad"
                    "\\mathrm{rms}_{\\mathrm{dB}}=20\\log_{10}(\\mathrm{rms})"
                ),
                quote=(
                    "``rms``：``sqrt(mean_{i,j,k} |S_ij(f_k) - "
                    "Sfit_ij(f_k)|^2)``（逐响应 + 逐频点"
                ),
                cite=(
                    "模块 docstring「数值口径」节；阈值缺省 -40 dB；"
                    "skrf get_rms_error 只作诊断旁证另存溯源"
                ),
            ),
            Formula(
                title="无源性带内直判（独立于 skrf 半尺寸测试）",
                latex=(
                    "\\sigma_{\\max}\\!\\big(\\mathbf S(f)\\big)\\le 1,"
                    "\\quad \\forall f\\in[f_{\\min},f_{\\max}]"
                ),
                quote="直接对模型 S 矩阵做 SVD 取最大奇异值（``sigma_max_in_band``）",
                cite=(
                    "模块 docstring「无源性口径」节——无源化只要求模型有效频带内"
                    "成立；passivity_enforce 仅带内违规时触发"
                ),
            ),
            Formula(
                title="FSV 保真裁判（D12 内核，IEEE 1597.1）",
                latex="\\mathrm{GDM}\\le\\mathrm{Good}\\ (\\text{等级下标}\\le 2)",
                quote="目标 GDM ≤ Good（等级下标 ≤ 2）",
                cite=(
                    "core/fsv.py（IEEE 1597.1 独立实现）——模块 docstring"
                    "「裁判设计（不自证）」节"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="SPICE 回放是\"回放自检\"，不是第三方 SPICE 等价验证",
                note=(
                    "内置纯 Python 复数 MNA 求解器只证明导出网表在标准 SPICE "
                    "元素语义下重现模型；不得把 spice_replay.status=='ok' 读成"
                    "第三方 SPICE 仿真通过——ngspice .AC 对拍在 adapters 层"
                    "（core 禁 import adapters）。"
                ),
            ),
            Boundary(
                quote="``fit_macromodel`` 主链**不缺省依赖 ngspice**",
                note=(
                    "第三方交叉验证是缺工具时 best-effort 跳过（#139 精神），"
                    "不炸主链、不假装验证过。"
                ),
            ),
            Boundary(
                quote="物理上无源化只要求在**模型有效频带**",
                note=(
                    "全频轴（含外推）判违规会把数值模型外推段的伪违规当真；"
                    "本模块同时报告全轴与带内结果，以带内直判为无源性结论。"
                ),
            ),
            Boundary(
                quote="``passivity_enforce`` 是 skrf 的启发式迭代",
                note=(
                    "可能改不动带内违规、也可能大幅劣化带内精度——enforce 前/后 "
                    "RMS 与 SVD 同时返回，不隐藏劣化。"
                ),
            ),
            Boundary(
                quote="带内直判只在 ``passivity_samples`` 个密集采样点上做 SVD",
                note="极窄违规带可能被漏检；skrf 半尺寸测试的解析频段边界同时给出。",
            ),
        ),
        doc_refs=(
            DocRef(
                path="延续计划（仓内规划档，不随公开分发）",
                quote="任务来源：延续计划 §10.3 D13 / §10.19 第 2 条。",
                tracked=False,
            ),
        ),
    ),
    CardSpec(
        kernel_id="rwg_mmt",
        tagline=(
            "在矩形波导 TE_m0 解析模基上用模匹配（GSM）闭式链解 H 面阶梯/"
            "膜片/均匀段的过传响应——全波求解之前的解析快速通道，带自检锚、"
            "规格书勘误留痕与近截止诚实降级。"
        ),
        modules=("rwg_mmt",),
        primary_entries=(
            ("rwg_mmt", "mode_basis"),
            ("rwg_mmt", "junction_gsm"),
            ("rwg_mmt", "section_gsm"),
            ("rwg_mmt", "gsm_cascade"),
            ("rwg_mmt", "solve_chain"),
            ("rwg_mmt", "inductive_post_susceptance"),
            ("rwg_mmt", "resonant_window_susceptance"),
            ("rwg_mmt", "g1_systematic_bias_check"),
        ),
        formulas=(
            Formula(
                title="TE_m0 模基与色散（功率归一）",
                latex=(
                    "k_c=\\frac{m\\pi}{a},\\quad "
                    "f_c=\\frac{c\\,m}{2a\\sqrt{\\varepsilon_r}},\\quad "
                    "\\beta=\\sqrt{k^2-k_c^2},\\quad "
                    "Z^{\\mathrm{TE}}=\\frac{\\omega\\mu}{\\beta}"
                ),
                quote="k_c=mπ/a、fc=c·m/(2a√εr)、β=√(k²−k_c²)（k=k0√εr）；Z^TE=ωμ/β",
                cite=(
                    "Pozar §3 场分量式口径（模块 docstring「数学口径」节，"
                    "#1b 先验模型，推导在档）"
                ),
            ),
            Formula(
                title="结面 GSM（功率波归一，规格勘误后口径）",
                latex=(
                    "\\hat C=D_1^{-1}H^{\\mathsf T}D_2,\\quad "
                    "M=\\hat C\\hat C^{\\mathsf T},\\quad "
                    "N=\\hat C^{\\mathsf T}\\hat C;"
                ),
                quote="**Ĉ=D1⁻¹·Hᵀ·D2**，H_nm=",
                quote2=(
                    "S11=(M−I)(M+I)⁻¹、S21=2Ĉᵀ(I+M)⁻¹、S12=2(I+M)⁻¹Ĉ、"
                    "S22=(I−N)(I+N)⁻¹"
                ),
                cite=(
                    "规格 docs/plan_deepdive_specs_20260924.md DP-1 §2.3"
                    "（投影域勘误后变体）；两侧同时激励消元，纯转置无共轭"
                ),
            ),
            Formula(
                title="阶梯耦合积分（半角稳定形式；规格书 §2.2 原式勘误）",
                latex=(
                    "\\int_{x_0}^{x_0+w}\\!\\cos(\\pi\\Delta x)\\,dx="
                    "w\\cos(\\pi\\Delta x_c)\\,"
                    "\\mathrm{sinc}\\!\\big(\\pi\\Delta w/2/\\pi\\big),"
                    "\\quad x_c=x_0+\\tfrac{w}{2}"
                ),
                quote="∫_{x0}^{x0+w} cos(πΔx)dx = w·cos(πΔ·x_c)·sinc(πΔw/2/π)",
                cite=(
                    "Wexler 1967 / Masterman-Clarricoats 1971 矩形闭式特例；"
                    "cos-分子显式式系规格书笔误（#1b 动工前裁决），半角形式"
                    "Δ→0 极限自动精确"
                ),
            ),
            Formula(
                title="损耗闭式（TE10 微扰口径）",
                latex=(
                    "\\alpha_c=\\frac{R_s}{b\\,\\eta\\,"
                    "\\sqrt{1-(f_c/f)^2}}"
                    "\\Big(1+\\tfrac{2b}{a}\\tfrac{f_c^2}{f^2}\\Big),"
                    "\\qquad \\alpha_d=\\frac{k^2\\tan\\delta}{2\\beta}"
                ),
                quote="损耗闭式（规格 §2.6，TE10 微扰口径）：α_c=Rs/(b·η·√(1−(fc/f)²))·",
                quote2="(1+2b/a·(fc/f)²)、α_d=k²·tanδ/(2β)",
                cite=(
                    "规格 §2.6；作为均匀衰减因子作用于段传输指数"
                    "（高阶倏逝模微扰损耗可忽略——已声明近似）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="TE_{m0} 单族，H 面首例域",
                note=(
                    "模基是 TE_m0 单族、H 面结构首例——E 面阶梯/多族模不在"
                    "本内核声明域内。"
                ),
            ),
            Boundary(
                quote="# 近截止病态带半宽（规格 §2.5 风险⑤：<5% 频点显式标 undetermined 不外推）",
                note=(
                    "距截止 <5% 的频点处于近截止病态带，显式标 undetermined "
                    "不外推（_NEAR_CUTOFF_FRAC=0.05）。"
                ),
            ),
            Boundary(
                quote="**规格书 §2.2 原式勘误（#1b，动工前裁决）**",
                note=(
                    "规格书 cos-分子显式式代入平凡自检得 0 而积分真值 a/2，"
                    "属笔误——实现用数学等价的半角稳定形式，勘误留痕在档。"
                ),
            ),
            Boundary(
                quote="自检锚：同波导 H=I→S11=S22=0、S21=I",
                note=(
                    "自检锚族：同波导恒等、单模台阶 Γ 闭式一致、宽口径膜片对 "
                    "Marcuvitz 一阶旁证——解析可信度的来源先于真机仲裁。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="docs/plan_deepdive_specs_20260924.md",
                quote="规格 = docs/plan_deepdive_specs_20260924.md DP-1 §2；",
                tracked=False,
            ),
            DocRef(
                path="runs/df6_dp1mmt/criteria.md",
                quote="判据预声明 = runs/df6_dp1mmt/criteria.md（先写后跑，#122）。",
                tracked=False,
            ),
        ),
    ),
    CardSpec(
        kernel_id="pdn",
        tagline=(
            "从 VRM、去耦电容、安装电感到平面腔模的电源分配网络阻抗闭式合成"
            "与去耦选型筛查——目标阻抗口径的工程快判内核，全场精算不在声明域。"
        ),
        modules=("pdn",),
        primary_entries=(
            ("pdn", "target_impedance"),
            ("pdn", "target_impedance_freq"),
            ("pdn", "decap_impedance"),
            ("pdn", "mount_inductance"),
            ("pdn", "vrm_model"),
            ("pdn", "plane_cavity_modes"),
            ("pdn", "mount_position_clearance"),
            ("pdn", "dc_bias_effective_c"),
            ("pdn", "pdn_impedance_profile"),
            ("pdn", "greedy_decap_select"),
            ("pdn", "load_decap_library"),
        ),
        formulas=(
            Formula(
                title="恒定目标阻抗（Smith 1999 口径）",
                latex="Z_{\\mathrm{target}}=\\frac{V_{\\mathrm{ripple}}}{\\Delta I}",
                quote="恒定口径目标阻抗 Z_target = V_ripple / ΔI（Smith 1999 IEEE TAP 口径）",
                cite=(
                    "L. D. Smith et al., IEEE Trans. Adv. Packag. 22(3):284-291, "
                    "1999——KD-1 条目 pdn:<module>:01（source_doi "
                    "10.1109/6040.784476）"
                ),
            ),
            Formula(
                title="频率依赖目标阻抗（Smith/Novak 分段包络）",
                latex=(
                    "Z_{\\mathrm{target}}(f)=\\begin{cases}Z_0, & f\\le f_k\\\\"
                    "Z_0\\,f_k/f, & f>f_k\\end{cases}"
                    "\\quad(\\text{高频 }-20\\,\\mathrm{dB/dec})"
                ),
                quote="（频率依赖分段包络，Smith/Novak 谱系：低频平坦+高频 −20dB/dec，拐点频率为参数）",
                cite=(
                    "模块 docstring 模块面节（target_impedance_freq 行）；"
                    "上式为分段形状的口径示意转写——实现以 "
                    "src/rfauto/core/pdn.py:target_impedance_freq 为准"
                ),
                kind="口径示意（非 docstring 原式，读代码为准）",
            ),
            Formula(
                title="去耦电容单件阻抗（C+ESR+ESL）",
                latex=(
                    "Z_{\\mathrm{cap}}(\\omega)=R_{\\mathrm{ESR}}+j\\Big("
                    "\\omega L_{\\mathrm{ESL}}-\\frac{1}{\\omega C}\\Big)"
                ),
                quote="阻抗 Z=ESR+j(ωL−1/(ωC))；并联一律导纳求和",
                cite="Kundert 去耦网络方法论（C+ESR+ESL 三件模型，反谐振峰机理）",
            ),
            Formula(
                title="整网合成（并联导纳求和）",
                latex=(
                    "Y_{\\mathrm{tot}}(\\omega)=\\sum_i\\frac{1}{Z_i(\\omega)},"
                    "\\qquad Z_{\\mathrm{tot}}=\\frac{1}{Y_{\\mathrm{tot}}}"
                ),
                quote="整网合成：pdn_impedance_profile（VRM 与全部电容的并联导纳求和 Y=Σ1/Zᵢ）",
                cite="模块 docstring 数值口径节（复数除法数值稳定；空网 Z=∞ 显式处理）",
            ),
            Formula(
                title="安装电感两贡献项（过孔对回路+径向扩张）",
                latex=(
                    "L'_{\\mathrm{via}}=\\frac{\\mu_0}{\\pi}\\,"
                    "\\mathrm{arcosh}\\!\\Big(\\frac{s}{2r}\\Big),"
                    "\\qquad L_{\\mathrm{spread}}=\\frac{\\mu_0 h_d}{2\\pi}"
                    "\\ln\\frac{r_2}{r_1}"
                ),
                quote="L'=μ0/π·arcosh(s/2r)",
                quote2="L_spread=μ0·h_d/(2π)·ln(r2/r1)",
                cite=(
                    "Rosa/Grover 双线闭式 + Novak & Miller 平行板径向流扩张电感"
                    "（Artech House 2007）——Archambeault 安装回路分解口径组装"
                ),
            ),
            Formula(
                title="矩形平面腔模频率（TM 闭式筛查）",
                latex=(
                    "f_{mn}=\\frac{c}{2\\sqrt{\\varepsilon_r}}"
                    "\\sqrt{\\Big(\\frac{m}{a}\\Big)^2+"
                    "\\Big(\\frac{n}{b}\\Big)^2}"
                ),
                quote="f_mn=c/(2√εr)·√((m/a)²+(n/b)²)",
                cite=(
                    "矩形谐振腔 TM 闭式标准式（Pozar 腔体谐振器章同形口径；"
                    "与 shield_cavity_mode 内核同源共享腔模闭式族）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="量级用于选型筛查非精算",
                note=(
                    "安装电感两闭式均忽略有限长端部效应与过孔焊盘回流不对称——"
                    "工程简化模型的量级筛查语义，非精算声明。"
                ),
            ),
            Boundary(
                quote="v1 仅频率筛查",
                note="平面腔模 v1 只做频率闭式筛查，不做全场 TMM（docstring 模块面节同口径）。",
            ),
            Boundary(
                quote="无曲线如实标 no_derating",
                note=(
                    "DC-bias 折减只有查表+线性插值；无曲线即如实标 no_derating，"
                    "不虚构曲线（铁律 7）。"
                ),
            ),
            Boundary(
                quote="禁止虚构 vendor 实测数字",
                note=(
                    "decap 库 provenance 字段强制：首批条目一律 "
                    "typical_engineering_value 标注；vendor 实测曲线入 "
                    "dc_bias_curve 键并带出处（单条不合法即 ValueError 硬错）。"
                ),
            ),
            Boundary(
                quote="全频段无任何支路时 Y=0 → Z=∞ 显式处理",
                note="空网显式返回 inf+0j，不静默吞除零（numpy 警告在函数内抑制）。",
            ),
            Boundary(
                quote="全加完仍超标→显式 infeasible，不凑解",
                note="贪心选型是确定性改善/成本比贪心；不凑解——超标即显式 infeasible。",
            ),
        ),
        doc_refs=(
            DocRef(
                path="docs/research_expansion_20260926.md",
                quote="§F-B 第 4 节（先写后跑，#122）；本文件交付判据 1-5",
                tracked=False,
            ),
        ),
    ),
    CardSpec(
        kernel_id="pce",
        tagline=(
            "把响应面拟合成正交多项式混沌展开（纯 numpy 确定性），从展开系数"
            "直接读 Sobol 全局敏感度、worst-case 角与设计中心——代理模型的"
            "适用边界同样如实声明。"
        ),
        modules=("pce", "sparse_pce"),
        primary_entries=(
            ("pce", "fit_pce"),
            ("pce", "pce_sobol"),
            ("pce", "worst_case"),
            ("pce", "corner_worst_case"),
            ("pce", "design_centering"),
            ("pce", "tolerance_yield"),
            ("sparse_pce", "fit_sparse_pce"),
            ("sparse_pce", "sparse_pce_sobol"),
            ("sparse_pce", "ishigami_sobol_analytic"),
        ),
        formulas=(
            Formula(
                title="一维正交归一基（Legendre/Hermite）",
                latex=(
                    "\\psi_n^{\\mathrm{Leg}}(\\xi)=\\sqrt{2n+1}\\,"
                    "P_n(\\xi),\\qquad "
                    "\\psi_n^{\\mathrm{Her}}(\\xi)=\\frac{He_n(\\xi)}{\\sqrt{n!}}"
                ),
                quote="Legendre（均匀输入）：psi_n(xi)=sqrt(2n+1)*P_n(xi)，xi∈[-1,1] 上",
                cite=(
                    "E[psi_m psi_n]=delta_mn 归一口径（模块 docstring「机制」节）；"
                    "多维基=各维基函数乘积，多指标 graded-lex 序"
                ),
            ),
            Formula(
                title="Sobol 指数系数直读（无需再采样）",
                latex=(
                    "V=\\sum_{\\alpha\\ne 0}c_\\alpha^2,\\qquad "
                    "S_{1,i}=\\frac{1}{V}\\!"
                    "\\sum_{\\alpha:\\,\\alpha_i>0,\\,\\alpha_{j\\ne i}=0}"
                    "c_\\alpha^2,\\qquad "
                    "S_{\\mathrm{T},i}=\\frac{1}{V}"
                    "\\sum_{\\alpha:\\,\\alpha_i>0}c_\\alpha^2"
                ),
                quote="V = sum_{alpha != 0} c_alpha^2；",
                quote2="ST_i = sum_{alpha: a_i>0} c_alpha^2 / V。",
                cite=(
                    "输入独立+基正交归一 ⇒ 系数平方和即该子空间方差贡献"
                    "（较 Saltelli 采样省 1-2 量级——docstring「依据」节）"
                ),
            ),
            Formula(
                title="稀疏回归（OMP 确定性路径）",
                latex=(
                    "\\min_\\theta \\lVert y-\\Psi\\theta\\rVert_2^2"
                    "\\ \\ \\text{s.t. } \\mathrm{supp}(\\theta)"
                    "\\text{ 由 OMP 路径给出}"
                ),
                quote="OMP（正交匹配追踪，确定性并列取最小下标），常数项强制入选；",
                cite=(
                    "停止条件=残差 2 范数 ≤ tol 或非零项达 max_terms；"
                    "上式为口径示意转写——实现以 src/rfauto/core/pce.py:omp_fit 为准"
                ),
                kind="口径示意（非 docstring 原式，读代码为准）",
            ),
        ),
        boundaries=(
            Boundary(
                quote="PCE 是全局多项式代理；强不连续/多峰/窄带谐振（如 patch 谷深）收敛慢，",
                note=(
                    "Sobol 直读反映的是代理的方差分解——代理不准则指数不准"
                    "（深谐振谷族先扫谷深再定口径，#370 族教训）。"
                ),
            ),
            Boundary(
                quote="本模块不读 runs/、不联网、不依赖 scipy/optuna（core 零依赖叶子约束）",
                note=(
                    "core 叶子只依赖 numpy；与 sensitivity/Saltelli 的互证在"
                    "测试层做（#118 双路径裁判），不在内核内互调。"
                ),
            ),
            Boundary(
                quote="corner_worst_case 穷举容差角点（均匀=low/high，正态=mean±kσ）；",
                note=(
                    "worst-case 两口径：角点穷举（确定性）与 PCE 上多起点 "
                    "确定性 pattern search（可命中内部极值）。"
                ),
            ),
            Boundary(
                quote="Saltelli 互证 ±10%（§10.15）",
                note=(
                    "验收口径=patch 公差问题 PCE-Sobol vs 既有 Saltelli 互证 "
                    "±10%（规划档 §10.15 预声明）。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="延续计划（仓内规划档，不随公开分发）",
                quote="延续计划 §10.4 D8：稀疏 PCE（ChaosPy/OpenTURNS）",
                tracked=False,
            ),
        ),
    ),
    CardSpec(
        kernel_id="cascade",
        tagline=(
            "链路预算级联闭式（Friis 噪声/IIP3/P1dB/噪声底/SFDR/灵敏度）"
            "+ 混频杂散全阶枚举——纯 math 确定性内核，规格书笔误在动工前"
            "勘误并钉解析恒等式锚。"
        ),
        modules=("cascade",),
        primary_entries=(
            ("cascade", "cascade_budget"),
            ("cascade", "spur_search"),
            ("cascade", "if_plan_sweep"),
            ("cascade", "cascade_ipn_merge"),
            ("cascade", "cascade_compression_scan"),
            ("cascade", "cascade_am_pm"),
            ("cascade", "cascade_nonlinear_scan"),
            ("cascade", "p1db_from_oip3"),
        ),
        formulas=(
            Formula(
                title="Friis 级联噪声（功率域线性）",
                latex=(
                    "F_{\\mathrm{tot}}=F_1+\\frac{F_2-1}{G_1}"
                    "+\\frac{F_3-1}{G_1G_2}+\\cdots"
                ),
                quote="Friis 噪声级联（功率域线性）：F_tot = F₁ + (F₂−1)/G₁ + (F₃−1)/(G₁G₂) + …",
                cite="模块 docstring「公式口径（§0，含规格书勘误 1 处）」节",
            ),
            Formula(
                title="IIP3 级联（功率域求和式；规格书字面式勘误）",
                latex=(
                    "\\frac{1}{\\mathrm{IIP3}_{\\mathrm{tot}}}=\\sum_i"
                    "\\frac{G_{\\mathrm{pre},i}}{\\mathrm{IIP3}_i},\\qquad "
                    "\\mathrm{OIP3}_{\\mathrm{tot}}="
                    "\\mathrm{IIP3}_{\\mathrm{tot}}+G_{\\mathrm{tot}}"
                ),
                quote="1/IIP3_tot = Σᵢ G_pre,i / IIP3ᵢ",
                quote2="OIP3_tot = IIP3_tot + G_tot（恒等式）",
                cite=(
                    "教科书口径（Pozar 级联非线性；core/budget.py LinkBudget "
                    "同口径且已有单测）——规格书 §2 字面式增益落分母系笔误；"
                    "criteria.md §0 解析恒等式锚（IIP3_tot ≡ −7.0 dBm）"
                ),
            ),
            Formula(
                title="噪声底 / 灵敏度 / SFDR",
                latex=(
                    "N_{\\mathrm{floor}}=10\\log_{10}(k_B T\\,10^{3})"
                    "+10\\log_{10}B+\\mathrm{NF}_{\\mathrm{tot}}\\ "
                    "[\\mathrm{dBm}],\\quad "
                    "\\mathrm{SFDR}=\\tfrac{2}{3}\\big("
                    "\\mathrm{IIP3}_{\\mathrm{tot}}-N_{\\mathrm{floor}}\\big),"
                    "\\quad P_{\\mathrm{sens}}=N_{\\mathrm{floor}}"
                    "+\\mathrm{SNR}_{\\min}"
                ),
                quote="SFDR = (2/3)·(IIP3_tot − N_floor)；灵敏度 P_sens = N_floor + SNR_min；",
                cite=(
                    "k_B=1.380649e-23（SI 精确值）、T 缺省 290 K；带宽解析顺序 "
                    "显式入参 > 末级 stage bw_hz > 显式报错（docstring §0）"
                ),
            ),
            Formula(
                title="P1dB 级联（工程惯例口径，非教科书闭式）",
                latex=(
                    "\\frac{1}{P1\\mathrm{dB}_{\\mathrm{out}}}=\\sum_i"
                    "\\frac{1}{\\mathrm{OP1dB}_i+G_{\\mathrm{after},i}}"
                ),
                quote="1/P1dB_out = Σᵢ 1/(OP1dBᵢ + G_after,i)",
                cite="与级联 IP3 同形的饱和功率叠加工程惯例；p1db_dbm 约定=该级输出 1dB 压缩点",
            ),
            Formula(
                title="混频杂散全阶枚举",
                latex="f_{\\mathrm{spur}}=\\big|m f_{\\mathrm{RF}}\\pm n f_{\\mathrm{LO}}\\big|",
                quote="f_spur = |m·f_RF ± n·f_LO| 全阶枚举（缺省 m+n ≤ max_order=7）；",
                cite=(
                    "带内判据=矩形近似卷积；危险等级=阶数反比（≤3 high、≤5 medium、"
                    "其余 low）——docstring spur search 节"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="P1dB 级联为**经验口径**（无教科书闭式，如实标注）",
                note="P1dB 级联是工程惯例叠加式，如实标注经验口径——不冒充闭式推导。",
            ),
            Boundary(
                quote="只报频率落带不报电平（幅度需器件特性，out-of-scope）",
                note="杂散搜索只报频率落带与危险等级；电平需器件特性，显式 out-of-scope。",
            ),
            Boundary(
                quote="无源级（filter/atten/cable）缺省 NF = −gain_db（T0 口径无源损耗 NF=插损）；",
                note=(
                    "无源级缺省 NF=插损（T0 口径）；amp/mixer 的 nf_db 缺失显式报错"
                    "——skrf 实取插损的解析在 service 层（core 零 IO）。"
                ),
            ),
            Boundary(
                quote="规格书 §2 字面写作 ``1/(IIP3ᵢ·Π_{j<i}G_j)``（增益落分母）",
                note=(
                    "规格书字面式与教科书推导相反（后级 IIP3 折算到链路输入应"
                    "除以前级增益）——本模块按教科书口径实现，勘误与解析锚在档。"
                ),
            ),
            Boundary(
                quote="零 IO、不 import numpy/scipy/skrf（纯 math）——铁律 7 合规",
                note="纯 math 微秒级确定性内核；不 import numpy/scipy/skrf、零 IO。",
            ),
        ),
        doc_refs=(
            DocRef(
                path="docs/plan_deepdive_specs_20260924.md",
                quote="规格：docs/plan_deepdive_specs_20260924.md §DP-5；判据书：",
                tracked=False,
            ),
            DocRef(
                path="runs/df6_dp5cascade/criteria.md",
                quote="runs/df6_dp5cascade/criteria.md（回收钉锚值与来源）。",
                tracked=False,
            ),
        ),
    ),
    # ─── aurora_e W3-S13 知识面批 扩容批一（11 张；按「CALC 键+teaching 块+
    # 锚覆盖」数据源完备性选族；公式与边界全部 quote 钉在模块源文件） ──────
    CardSpec(
        kernel_id="mline",
        tagline=(
            "微带线综合主干：skrf Hammerstad-Jensen 正向算 Z0/εeff，brentq 反解"
            "线宽并回代自洽——全仓 50Ω 标称线宽与各族 λ/4 臂长的唯一计算源"
            "（XC-W 单源），εeff 通道来源与回退显式标记。"
        ),
        modules=("synthesis",),
        primary_entries=(
            ("synthesis", "synthesize_mline"),
            ("synthesis", "inverse_width"),
            ("synthesis", "forward_media"),
            ("synthesis", "forward_z0"),
            ("synthesis", "nominal_width_mm"),
            ("synthesis", "lossless_width_mm"),
            ("synthesis", "synthesize_mline_model"),
        ),
        formulas=(
            Formula(
                title="正向 HJ 模型（skrf MLine，hammerstadjensen 锁死）",
                latex=(
                    "(Z_0,\\ \\varepsilon_{\\mathrm{eff}})"
                    "=\\mathrm{MLine}_{\\mathrm{HJ}}"
                    "\\bigl(w,h,\\varepsilon_r,\\tan\\delta,\\rho,"
                    "\\mathrm{rough}\\bigr)"
                ),
                quote="使用 skrf MLine (Hammerstad-Jensen) 模型（与 G0 验证一致）",
                cite=(
                    "core/synthesis.py 模块头「设计决策」节（正向锁死 "
                    "model='hammerstadjensen'）；XC-P 精度档案 "
                    "synthesis.forward_z0 已建档（行为=WARN）"
                ),
            ),
            Formula(
                title="反解（brentq 求逆 + 回代自洽断言）",
                latex=(
                    "w^{*}=\\operatorname{brentq}_{w}\\,"
                    "\\bigl[Z_0(w)-Z_{0,\\mathrm{target}}\\bigr],\\quad"
                    "\\bigl|Z_0(w^{*})-Z_{0,\\mathrm{target}}\\bigr|<0.5\\,"
                    "\\Omega"
                ),
                quote="使用 brentq 求逆，反解结果回代正向做自洽断言。",
                cite=(
                    "core/synthesis.inverse_width docstring；自洽阈与三态状态机"
                    "（ok/er_eff_fallback/needs_calibration）见模块头「验收」节"
                ),
            ),
            Formula(
                title="λ/4 臂长恒等式（各臂自身 εeff 口径，XA-3 迭代序）",
                latex=(
                    "L_{\\lambda/4}=\\frac{c}{4 f_0"
                    "\\sqrt{\\varepsilon_{\\mathrm{eff}}(w_{\\mathrm{arm}})}}"
                ),
                quote="arm_len = lambda/4 = c / (4 * f0 * sqrt(epsilon_eff))",
                cite=(
                    "synthesize_wilkinson docstring「闭式公式」节；XA-3 迭代序="
                    "εeff 取臂线宽自身（inverse_width→forward_z0 链），旧近似"
                    "偏差量化同节在档"
                ),
            ),
            Formula(
                title="锚模板三重身份（mline 锚链）",
                latex=(
                    "\\text{校准件}\\;+\\;"
                    "\\text{引擎仲裁探针}\\;+\\;\\text{数据工厂}"
                ),
                quote="锚模板三重身份：校准件 + 引擎仲裁探针（S21 相位斜率→εeff，β 金",
                cite=(
                    "synthesize_mline_model docstring（β 金标准 #162；线宽绝不"
                    "沿用文档毫米数，铁律 1c）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="④ 超限标 needs_calibration 而非静默通过",
                note=(
                    "状态机三态（ok/er_eff_fallback/needs_calibration）全部显式"
                    "下泄给消费面——回代失败与 εeff 回退两真并存时保留更严重的"
                    "前者。"
                ),
            ),
            Boundary(
                quote="``.z0/.er_eff/.source`` 属性。εeff 回退体介电常数的通道显式见",
                note=(
                    "εeff 回退体介电常数时长度系设计不可信——来源标记"
                    "（.source）随量下泄，不静默（#316 多报方向）。"
                ),
            ),
            Boundary(
                quote="「50Ω 馈线宽」缺省档的唯一计算点：inverse_width(50)@各 (εr,h,f) 即权威",
                note=(
                    "XC-W 单源：历史五档 50Ω 宽字面量副本已收敛到本计算点，"
                    "归档字面量只做逐位一致性钉扎（tests/unit/"
                    "test_width_single_source.py）。"
                ),
            ),
            Boundary(
                quote="是参数系不同，非同参漂移，一致性测试分系钉住）。",
                note=(
                    "yaml 层叠档与无耗裸层叠档两系并存是参数系不同"
                    "（tanδ 是否进正向），不是同参漂移——跨档缺省有守卫。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="configs/materials.yaml",
                quote="层叠复用 configs/materials.yaml（带 source/verified_by）",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="wilkinson",
        tagline=(
            "等分 Wilkinson 功分器综合：两臂 λ/4、臂阻抗 √2·Z0，臂长按臂线宽"
            "自身 εeff 精算（XA-3 迭代序），隔离电阻是集总件不进线宽链——"
            "series/shunt 口径与注册表/fake 单源对齐（#154）。"
        ),
        modules=("synthesis",),
        primary_entries=(
            ("synthesis", "synthesize_wilkinson"),
        ),
        formulas=(
            Formula(
                title="两臂 λ/4 与臂阻抗 √2·Z0",
                latex=(
                    "Z_t=\\sqrt{2}\\,Z_0,\\qquad "
                    "L_{\\mathrm{arm}}=\\frac{c}{4 f_0"
                    "\\sqrt{\\varepsilon_{\\mathrm{eff}}(w_{\\mathrm{arm}})}}"
                ),
                quote="arm_len = lambda/4 = c / (4 * f0 * sqrt(epsilon_eff))",
                quote2=(
                    "series_w: Z0*sqrt(2) ≈ 70.7Ω λ/4 臂线宽（标准 Wilkinson 两臂，比馈线窄；"
                ),
                cite=(
                    "synthesize_wilkinson docstring「闭式公式」节；隔离电阻 "
                    "2Z0 接两臂末端（集总件，不是线宽）"
                ),
            ),
            Formula(
                title="XA-3 迭代序（臂长 εeff 取臂线宽自身）",
                latex=(
                    "\\mathrm{inverse\\_width}(\\sqrt{2}Z_0)\\to"
                    "\\mathrm{forward\\_z0}(w_{\\mathrm{arm}})\\to"
                    "\\varepsilon_{\\mathrm{eff}}(w_{\\mathrm{arm}})\\to"
                    "\\lambda/4"
                ),
                quote="inverse_width(70.7Ω)→forward_z0(w_series)→εeff(w_series)→λ/4；旧口径",
                cite=(
                    "synthesize_wilkinson docstring「XA-3 迭代序修正」节；旧口径"
                    "εeff@w=1mm 近似的名义点偏差量化与 XA-5 数值锚同节在档"
                ),
                kind="口径示意（非 docstring 原式，读代码为准）",
            ),
            Formula(
                title="#154 语义对齐（series/shunt 单源口径）",
                latex=(
                    "w_{\\mathrm{series}}:\\ \\sqrt{2}Z_0"
                    "\\ \\text{臂（窄）},\\qquad "
                    "w_{\\mathrm{shunt}}:\\ Z_0\\ \\text{馈线（宽）}"
                ),
                quote="#154 语义对齐：series/shunt 口径与 TEMPLATE_META.param_semantics、",
                quote2="（series=70.7Ω 臂窄、shunt=50Ω 馈线宽，2026-09-04 统一口径）。",
                cite=(
                    "synthesize_wilkinson docstring #154 节——同名参数跨通道"
                    "（注册表/模型/fake）单源语义，防同键异义家族分裂"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="隔离电阻 2*Z0=100Ω 接两臂末端，不是线宽）",
                note="隔离电阻是集总件，不参与线宽综合——线宽链只有两臂与馈线。",
            ),
            Boundary(
                quote="arm_len 的 εeff 必须取臂线宽自身——",
                note=(
                    "旧 εeff@w=1mm 近似已被 XA-3 迭代序替换；名义点偏差量化与"
                    "数值锚（tests/unit/test_synthesis_patch_anchor.py）在档。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_synthesis_patch_anchor.py",
                quote="tests/unit/test_synthesis_patch_anchor.py）。",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="branchline",
        tagline=(
            "分支线耦合器综合：Z0/√2 串联臂与 Z0 并联臂各按自身线宽 εeff 取 "
            "λ/4（XA-3 迭代序）——两臂 εeff 差数个百分点，不可共用同一臂长；"
            "旧 arm_len 键保留为弃用别名（#315 兼容）。"
        ),
        modules=("synthesis",),
        primary_entries=(
            ("synthesis", "synthesize_branchline"),
        ),
        formulas=(
            Formula(
                title="两臂各自 λ/4（自身 εeff）",
                latex=(
                    "L_{s}=\\frac{c}{4f_0\\sqrt{\\varepsilon_{\\mathrm{eff}}(w_s)}},"
                    "\\; w_s:\\ Z_0/\\sqrt{2};\\qquad "
                    "L_{h}=\\frac{c}{4f_0\\sqrt{\\varepsilon_{\\mathrm{eff}}(w_h)}},"
                    "\\; w_h:\\ Z_0"
                ),
                quote="series_len = λ/4 @ εeff(inverse_width(Z0/√2))——35.35Ω series 臂按自身",
                quote2="series_w: 35.35Ω (Z0/sqrt(2)) line width for series arms",
                cite=(
                    "synthesize_branchline docstring「闭式公式（XA-3 迭代序修正）」节；"
                    "shunt 臂同式按自身 εeff"
                ),
            ),
            Formula(
                title="两臂 εeff 差异（不可共用臂长）",
                latex=(
                    "\\varepsilon_{\\mathrm{eff}}(w_s)\\ne"
                    "\\varepsilon_{\\mathrm{eff}}(w_h)\\;\\Rightarrow\\;"
                    "L_s\\ne L_h"
                ),
                quote="两臂 εeff 差数个百分点，不可再共用同一臂长（旧口径",
                cite=(
                    "synthesize_branchline docstring——旧口径 "
                    "arm_len=λ/4@εeff(w=1mm) 对两臂都是双重近似"
                ),
                kind="口径示意（非 docstring 原式，读代码为准）",
            ),
            Formula(
                title="#315 弃用别名",
                latex=(
                    "\\texttt{arm\\_len\\_mm}\\equiv"
                    "\\texttt{series\\_len\\_mm}"
                    "\\ \\text{（弃用别名）}"
                ),
                quote="#315 兼容：arm_len_mm 保留为弃用别名（=series_len_mm），旧消费方",
                cite="synthesize_branchline docstring #315 节",
            ),
        ),
        boundaries=(
            Boundary(
                quote="透传双键，属渲染层改动不在本批（报告主代理）。",
                note=(
                    "series/shunt 严格设计（方环变矩形环）需渲染透传双键——"
                    "综合内核已双键齐备，渲染层改动另行立项。"
                ),
            ),
        ),
        doc_refs=(),
    ),
    CardSpec(
        kernel_id="ratrace",
        tagline=(
            "环形电桥（rat-race）综合：环阻抗 √2·Z0、周长 1.5λg（环线自身 "
            "εeff）闭式定环半径，环线宽 inverse_width 精算——与 Wilkinson 臂"
            "同手法的多来源确证口径。"
        ),
        modules=("synthesis",),
        primary_entries=(
            ("synthesis", "synthesize_ratrace_model"),
        ),
        formulas=(
            Formula(
                title="环阻抗 / 周长 / 半径闭式",
                latex=(
                    "Z_{\\mathrm{ring}}=\\sqrt{2}\\,Z_0,\\qquad "
                    "C_{\\mathrm{ring}}=1.5\\,\\lambda_g,\\qquad "
                    "R_{\\mathrm{ring}}=\\frac{C_{\\mathrm{ring}}}{2\\pi}"
                ),
                quote="环阻抗 = √2·Z0（70.7Ω@50Ω，多来源确证），周长 = 1.5λg(环线)，",
                quote2="R = 周长/(2π)。环线宽 inverse_width 精算（同 wilkinson 臂手法）。",
                cite="synthesize_ratrace_model docstring（WP2.3）；环线 λg 用环线宽自身 εeff（forward_z0）",
            ),
        ),
        boundaries=(
            Boundary(
                quote="环阻抗 = √2·Z0（70.7Ω@50Ω，多来源确证），周长 = 1.5λg(环线)，",
                note=(
                    "环线宽/半径全走 inverse_width/forward_z0 精算链——无手抄"
                    "毫米数（铁律 1c）；同名环形几何在 ring_resonator 模板按 "
                    "#198 同法栅格化。"
                ),
            ),
        ),
        doc_refs=(),
    ),
    CardSpec(
        kernel_id="patch",
        tagline=(
            "矩形贴片天线综合（Hammerstad 模型）：宽/长闭式 + 边缘馈电阻抗的 "
            "sin² 腔体驻波变换定馈点，附带 Balanis 腔模读数面板（Q 分解/分数"
            "带宽/方向性/辐射效率）——ΔL 与 Rin_edge 全仓单源。"
        ),
        modules=("synthesis",),
        primary_entries=(
            ("synthesis", "synthesize_patch"),
            ("synthesis", "patch_fringing_delta_l"),
            ("synthesis", "patch_rin_edge_balanis"),
            ("synthesis", "patch_cavity_metrics"),
        ),
        formulas=(
            Formula(
                title="贴片宽/长（Hammerstad 口径）",
                latex=(
                    "W=\\frac{c}{2f_0}\\sqrt{\\frac{2}{\\varepsilon_r+1}},"
                    "\\qquad "
                    "L=\\frac{c}{2f_0\\sqrt{\\varepsilon_{\\mathrm{eff}}}}-2\\,dL"
                ),
                quote="W = c / (2*f0) * sqrt(2/(er+1))",
                quote2="L = c/(2*f0*sqrt(er_eff)) - 2*dL   [总扣口径=4ΔL（三副本一致，历史",
                cite=(
                    "synthesize_patch docstring「闭式公式」节；总扣语义仲裁 "
                    "INCONCLUSIVE 在档，语义终裁挂 L5 v2 批"
                ),
            ),
            Formula(
                title="边缘等效伸长 ΔL（Hammerstad 1975 原式，全仓单源）",
                latex=(
                    "\\frac{\\Delta L}{h}=\\frac{0.412\\,"
                    "(\\varepsilon_{\\mathrm{eff}}+0.3)(w/h+0.264)}"
                    "{(\\varepsilon_{\\mathrm{eff}}-0.258)(w/h+0.8)}"
                ),
                quote="ΔL/h = 0.412·(εeff+0.3)(w/h+0.264) / [(εeff−0.258)(w/h+0.8)]",
                cite=(
                    "patch_fringing_delta_l docstring（Hammerstad 1975；Pozar "
                    "eq.4.23 同口径）；XA-1/PV-016 三副本收敛，本函数是全仓唯一 "
                    "ΔL 算术单源"
                ),
            ),
            Formula(
                title="馈点位置（腔体驻波 sin² 变换，XA-2 闭式）",
                latex=(
                    "R_{\\mathrm{in}}(\\mathrm{off})=R_{\\mathrm{in,edge}}"
                    "\\sin^2\\!\\Bigl(\\frac{\\pi\\,\\mathrm{off}}{L}\\Bigr),"
                    "\\qquad \\mathrm{off}=\\frac{L}{\\pi}\\arcsin"
                    "\\sqrt{\\frac{R_{\\mathrm{in,t}}}{R_{\\mathrm{in,edge}}}}"
                ),
                quote="Rin(off) = Rin_edge·sin²(π·off/L)      （腔体驻波，off 自中心）",
                quote2="off = (L/π)·arcsin√(Rin_t/Rin_edge)    ≡ L/2 − y0",
                cite=(
                    "synthesize_patch docstring XA-2 节；Rin_edge 由 "
                    "patch_rin_edge_balanis 闭式（Balanis 4th §14-8 口径）；"
                    "输出口径=自贴片中心沿谐振轴偏移（#154 单源化）"
                ),
            ),
            Formula(
                title="腔模读数面板（Balanis 4th Ch.14 式链）",
                latex=(
                    "\\frac{1}{Q_t}=\\frac{1}{Q_{\\mathrm{rad}}}+"
                    "\\frac{1}{Q_c}+\\frac{1}{Q_d},\\qquad "
                    "\\mathrm{BW}=\\frac{\\mathrm{VSWR}-1}{Q_t\\sqrt{\\mathrm{VSWR}}},"
                    "\\qquad e_{\\mathrm{cds}}=\\frac{Q_t}{Q_{\\mathrm{rad}}}"
                ),
                quote="1/Qt = 1/Qrad + 1/Qc + 1/Qd",
                quote2="- 分数带宽（式 14-88a）：BW = (VSWR−1)/(Qt·√VSWR)；",
                cite=(
                    "patch_cavity_metrics docstring（#1c 原文核对：Balanis 4th "
                    "ed. Ch.14 原文页 852-854 + Table 14.2 逐式核对）；方向性 "
                    "D0 式 14-55 经 Jacobi-Anger 降维一维确定性求积"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="物理有效域 0 < Rin_t ≤ Rin_edge（馈点只能从中心向边缘提阻；",
                note=(
                    "越域显式 ValueError 不外推（=Rin_edge 退化边缘馈 "
                    "off=L/2）；off∈(0, L/2] 由 arcsin 值域自动保证。"
                ),
            ),
            Boundary(
                quote="原文逐位核对，引用该出处前必须回原文核验，不冒充已核）。",
                note=(
                    "Rin_edge 出处页码/式号 UNVERIFIED 待核——章节级引用可用，"
                    "页码级声称必须先回原文（#122）。"
                ),
            ),
            Boundary(
                quote="离线锚仲裁判 INCONCLUSIVE：两语义",
                note=(
                    "ΔL 总扣语义（2ΔL vs 4ΔL）离线锚仲裁 INCONCLUSIVE——现行"
                    "口径零行为维持，不凑裁决；语义翻转需联动多面另批。"
                ),
            ),
            Boundary(
                quote="适用域：k0·h ≪ 1（守卫同 patch_rin_edge_balanis <0.3，腔模口径）。",
                note="腔模口径是薄基板假设——厚基板越域显式报错不外推。",
            ),
        ),
        doc_refs=(
            DocRef(
                path="runs/xa1_arbitration/l5_sweep/criteria.md",
                quote="仲裁 INCONCLUSIVE 在档 runs/xa1_arbitration/；语义终裁挂 L5 v2 批，",
                tracked=False,
            ),
        ),
    ),
    CardSpec(
        kernel_id="hairpin",
        tagline=(
            "Hairpin 滤波器综合：C13 耦合矩阵 → 逐缝 KJ 反解（可选 hairpin "
            "结构经验修正 c(gap)，opt-in）+ 抽头 τ 闭式——矩阵综合与几何映射"
            "分层，闭式零经验常数、经验常数真机溯源。"
        ),
        modules=("synthesis", "coupled_microstrip"),
        primary_entries=(
            ("synthesis", "hairpin_design_from_order"),
            ("synthesis", "synthesize_hairpin_model"),
            ("coupled_microstrip", "hairpin_gap_mm_from_k"),
            ("coupled_microstrip", "hairpin_arm_len_mm"),
            ("coupled_microstrip", "hairpin_tap_frac_from_qe"),
        ),
        formulas=(
            Formula(
                title="耦合系数与外部 Q（Hong §5.2/§5.3）",
                latex=(
                    "k_{i,i+1}=\\mathrm{FBW}\\,|M_{i,i+1}|,\\qquad "
                    "Q_e=\\frac{1}{\\mathrm{FBW}\\,|M_{0,1}|^2}"
                ),
                quote="k_{i,i+1}=FBW·|M_{i,i+1}|、Q_e=1/(FBW·|M_{0,1}|²)（Hong §5.2/§5.3），",
                cite="hairpin_design_from_order docstring；再经 KJ 反解得缝、经抽头闭式得 τ",
            ),
            Formula(
                title="臂长 λg/2 与抽头 τ",
                latex=(
                    "L_{\\mathrm{arm}}=\\frac{c}{2f_0"
                    "\\sqrt{\\varepsilon_{\\mathrm{eff}}}},\\qquad "
                    "Q_e=\\frac{\\pi}{2}\\frac{Z_0}{Z_r}\\sec^2(\\pi\\tau)"
                ),
                quote="展开半波长臂长 λg/2=c/(2·f0·√εeff)（Pozar；与 core/thermo_mech 同式）。",
                quote2="- 抽头外部 Q：Q_e=(π/2)(Z0/Z_r)sec²(πτ)（本仓派生，单测以精确分布参数 Y_res(ω)",
                cite=(
                    "coupled_microstrip 模块 docstring（hairpin 收口 ⑦ 升格面）；"
                    "Q_e 闭式以精确分布参数 Y_res(ω) 数值微分独立校核（#118）"
                ),
            ),
            Formula(
                title="hairpin 结构经验修正 c(gap)（opt-in，W4④）",
                latex="c(s)\\,k_{\\mathrm{KJ}}(s)=k_{\\mathrm{EM}}",
                quote="kgap_corrected=True（W4④，2026-09-17）：缝反解改用 hairpin 结构经验修正映射",
                quote2="c(gap)·k_KJ(gap)=k（core/coupled_microstrip.hairpin_gap_mm_from_k structural_",
                cite=(
                    "hairpin_design_from_order docstring W4④ 节；常数全部出自"
                    "本战役 openEMS N=2 弱抽头双谐振器真机（铁律 7），并附 "
                    "gaps_mm_kj 纯 KJ 反解供对照"
                ),
                kind="口径示意（非 docstring 原式，读代码为准）",
            ),
        ),
        boundaries=(
            Boundary(
                quote="order=1（单谐振器双抽头探针，B1 Q 标定）无耦合缝：k_list=[]、gaps_mm=[]、",
                note="order=1 无耦合缝（gap_mm=None 不进 params）——不再 IndexError。",
            ),
            Boundary(
                quote="自耦远小于互耦，旧默认 1.0 反超是四轮 FAIL 的结构性根因，pt1 实证）。",
                note="arm_gap_mm 名义定版=同臂自耦须远小于互耦——结构性根因有真机实证。",
            ),
            Boundary(
                quote="域外/不可达如实 ValueError），并附 gaps_mm_kj（纯 KJ 反解）供对照。",
                note=(
                    "k_EM 非单调——修正反解只搜单调设计支，k 超支内可达范围"
                    "显式报可达上/下限不外推（拓扑能力问题如实报错）。"
                ),
            ),
            Boundary(
                quote="默认 False 保持名义链（HAIRPIN_NOMINAL 冻结口径）逐位不变。",
                note="结构修正显式 opt-in——名义链缺省口径零漂移。",
            ),
        ),
        doc_refs=(
            DocRef(
                path="src/rfauto/adapters/openems_templates.py",
                quote="再经 KJ 反解得缝、经抽头闭式得 τ（口径见 adapters/openems_templates 文末",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="cpw",
        tagline=(
            "共面波导综合（底接地 CPWG 口径）：共形映射闭式 εeff/Z0 + brentq "
            "反解线宽——合成参照系必须与真实结构同口径（#193 参照系错位教训）。"
        ),
        modules=("synthesis",),
        primary_entries=(
            ("synthesis", "synthesize_cpw_model"),
        ),
        formulas=(
            Formula(
                title="CPWG 共形映射闭式（_cpwg_ri 单源）",
                latex=(
                    "\\bigl(\\varepsilon_{\\mathrm{eff}},\\ Z_0\\bigr)"
                    "=f_{\\mathrm{CPWG}}"
                    "\\bigl(w,\\mathrm{gap},h,\\varepsilon_r\\bigr),"
                    "\\qquad w=\\operatorname{brentq}_{w}"
                    "\\bigl[Z_0(w)-Z_{0,\\mathrm{target}}\\bigr]"
                ),
                quote="core/calculators._cpwg_ri（实测 εeff/S11 双锚校验，#198）。",
                cite=(
                    "synthesize_cpw_model docstring；共形映射闭式在 "
                    "core/calculators._cpwg_ri，Z0 随 w 单调递减反解后回代自洽；"
                    "CALC 键 cpw_synthesis/cpw_analysis（calc_families/rf_line）"
                    "同族面"
                ),
                kind="口径示意（非 docstring 原式，读代码为准）",
            ),
            Formula(
                title="#193 参照系错位教训",
                latex=(
                    "Z_0^{\\mathrm{CPW_{open}}}\\ne Z_0^{\\mathrm{CPWG}}"
                    "\\;\\Rightarrow\\;"
                    "\\text{无地口径合成线在真实接地结构中失配}"
                ),
                quote="必须同口径（#193 参照系错位教训：skrf CPW 无地口径合成的 50Ω 线",
                cite="synthesize_cpw_model docstring #193 节（在真实结构里失配的具体量化同节）",
                kind="口径示意（非 docstring 原式，读代码为准）",
            ),
        ),
        boundaries=(
            Boundary(
                quote="Z0 随 w 单调递减；brentq 反解后回代自洽。gap 为固定参数",
                note="gap 固定参与反解存在性——越界显式报错，不做静默延拓。",
            ),
        ),
        doc_refs=(
            DocRef(
                path="src/rfauto/core/calculators.py",
                quote="在真实结构里是 18Ω，|S11| 卡 −6.5dB）。共形映射闭式见",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="slotline",
        tagline=(
            "槽线闭式裁判面：Janaswamy–Schaubert 1986 曲线拟合式分段落地"
            "（常数三源逐位互证），段界外显式 ValueError 不外推——转录未闭环"
            "的分段如实登记不解锁，禁止凭记忆补常数。"
        ),
        modules=("slotline",),
        primary_entries=(
            ("slotline", "slotline_closed_form"),
            ("slotline", "slotline_segment"),
            ("slotline", "slotline_wide_low"),
            ("slotline", "slotline_z0"),
            ("slotline", "slotline_beta"),
            ("slotline", "slotline_eps_eff"),
        ),
        formulas=(
            Formula(
                title="窄槽段 λ'/λ0（式 (8)，低 εr 段）",
                latex=(
                    "\\frac{\\lambda'}{\\lambda_0}=1.045-0.365\\ln\\varepsilon_r"
                    "+\\frac{6.3\\,(W/d)\\,\\varepsilon_r^{0.945}}"
                    "{238.64+100\\,W/d}"
                    "-\\Bigl[0.148-\\frac{8.81(\\varepsilon_r+0.95)}"
                    "{100\\,\\varepsilon_r}\\Bigr]\\ln\\frac{d}{\\lambda_0}"
                ),
                quote="λ'/λ0 = 1.045 − 0.365 ln εr + 6.3 (W/d) εr^0.945 / (238.64 + 100 W/d)",
                quote2="− [0.148 − 8.81 (εr + 0.95) / (100 εr)] ln(d/λ0)",
                cite=(
                    "_lambda_ratio_low docstring（Janaswamy–Schaubert MTT-34(8):"
                    "900-902 式 (8)；原文拟合误差 Av 0.37% / Max 2.2% 同节照录）"
                ),
            ),
            Formula(
                title="窄槽段 Z0（式 (9)，低 εr 段）",
                latex=(
                    "Z_0=60+3.69\\sin\\frac{(\\varepsilon_r-2.22)\\pi}{2.36}"
                    "+133.5\\ln(10\\,\\varepsilon_r)\\sqrt{W/\\lambda_0}+\\cdots"
                ),
                quote="Z0 = 60 + 3.69 sin[(εr − 2.22)π/2.36] + 133.5 ln(10 εr) √(W/λ0)",
                cite=(
                    "_z0_low docstring（式 (9)；常数三源核对——NTRS OCR/"
                    "Majumdar-Verma/NJIT FORTRAN 逐位闭合，见模块头）"
                ),
            ),
            Formula(
                title="εeff / β / Z0 口径（功率-电压定义）",
                latex=(
                    "\\varepsilon_{\\mathrm{eff}}=\\Bigl("
                    "\\frac{\\lambda_0}{\\lambda'}\\Bigr)^{\\!2},\\quad "
                    "\\beta=k_0\\sqrt{\\varepsilon_{\\mathrm{eff}}},\\quad "
                    "Z_0=\\frac{|V_0|^2}{2P}"
                ),
                quote="输出：λ'/λ0（槽波长比）、εeff=(λ0/λ')²、β=k0·√εeff、Z0（功率-电压定义",
                quote2="Z0=|V0|²/(2P)，Janaswamy 式 (1)，与 NGSolve 模场后处理口径一致）。",
                cite="模块 docstring「几何/记号」节",
            ),
        ),
        boundaries=(
            Boundary(
                quote="- 0.006 ≤ d/λ0 ≤ 0.06（全部式子共同前提）",
                note="有效域三条件（d/λ0、W/λ0 段、εr 段）同时满足，任一越界 ValueError 不外推。",
            ),
            Boundary(
                quote="系数未取得可双源核对的文本，禁止凭记忆写常数；2026-10-05 W4-B 复查：O'Reilly/",
                note="高 εr 段（Garg–Gupta 1976 式）未实现——各通道不可达即维持显式拒绝（#122）。",
            ),
            Boundary(
                quote="证据状态记档不凭记忆补常数（#122 如实）。",
                note=(
                    "宽槽 Z0 式 (11)/(14)/(15) 三个独立转录源互相冲突、段界"
                    "连续性裁判无法闭环——如实未实现，不凑闭环。"
                ),
            ),
            Boundary(
                quote="式 (10)（2.22 ≤ εr ≤ 3.8 宽槽 λ'/λ0）**已实现**（`slotline_wide_low`）。",
                note=(
                    "宽槽低 εr 档已落地：系数三源逐位一致 + 与窄槽式 (8) 段界"
                    "对拍的独立判据（#118）在档。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w4_b_p3_slotline_wide.py",
                quote="tests/unit/test_w4_b_p3_slotline_wide.py 钉）。",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="coupled_microstrip",
        tagline=(
            "耦合微带闭式内核：Kirschning-Jansen 1984 准静态偶/奇模阻抗与"
            "频变 εeff 色散层（Getsinger 型）+ hairpin 结构经验修正 c(gap)"
            "（显式 opt-in）——闭式部分零经验常数，经验常数真机溯源、域外"
            "不外推。"
        ),
        modules=("coupled_microstrip",),
        primary_entries=(
            ("coupled_microstrip", "coupled_microstrip_even_odd_ohm"),
            ("coupled_microstrip", "coupled_microstrip_eps_disp"),
            ("coupled_microstrip", "hairpin_gap_mm_from_k"),
            ("coupled_microstrip", "hairpin_kgap_correction"),
            ("coupled_microstrip", "hairpin_arm_len_mm"),
            ("coupled_microstrip", "hairpin_tap_frac_from_qe"),
        ),
        formulas=(
            Formula(
                title="KJ 1984 准静态偶/奇模阻抗",
                latex=(
                    "Z_{0e},\\,Z_{0o}=f_{\\mathrm{KJ}}(u,g,\\varepsilon_r),"
                    "\\qquad u=\\frac{w}{h},\\; g=\\frac{s}{h}"
                ),
                quote="耦合微带准静态偶/奇模阻抗（Kirschning-Jansen 1984 闭式；零厚/无盖）。",
                cite=(
                    "coupled_microstrip_even_odd_ohm docstring；单线量取 skrf "
                    "HJ 正向（core/synthesis.forward_z0），与 Qucs/transcalc "
                    "c_microstrip.cpp 零厚无盖分支逐式对应"
                ),
            ),
            Formula(
                title="频变偶/奇 εeff（Getsinger 型色散层，W4-A/P1）",
                latex=(
                    "\\varepsilon_{\\mathrm{eff},e/o}(f)=\\varepsilon_r-"
                    "\\frac{\\varepsilon_r-\\varepsilon_{\\mathrm{eff},e/o}(0)}"
                    "{1+F_{e/o}}"
                ),
                quote="Getsinger 型 εeff,e/o(f)=εr−(εr−εeff,e/o(0))/(1+F_e/o)、P1-P15 色散系数），",
                cite=(
                    "模块 docstring W4-A/P1 节（KJ 1984 论文式 (2)-(7)）；式面"
                    "与三独立源逐式核对（Wcalc/Qucs 技术文档/qucs-core），P1 "
                    "加式形态以论文原文影印定谳"
                ),
            ),
            Formula(
                title="耦合系数与缝反解",
                latex=(
                    "k=\\frac{Z_{0e}-Z_{0o}}{Z_{0e}+Z_{0o}}"
                    "\\;\\xrightarrow[\\;\\mathrm{brentq}\\;]{}\\; s"
                ),
                quote="- 平行耦合半波谐振器耦合系数 k=(Z0e−Z0o)/(Z0e+Z0o)（Hong §5.4）及 brentq 反解；",
                cite="模块 docstring；hairpin_gap_mm_from_k 单调性单测钉住，xtol=1e-12mm",
                kind="口径示意（非 docstring 原式，读代码为准）",
            ),
            Formula(
                title="抽头外部 Q（本仓派生，独立校核）",
                latex=(
                    "Q_e=\\frac{\\pi}{2}\\frac{Z_0}{Z_r}\\sec^2(\\pi\\tau),"
                    "\\qquad \\tau=\\frac{1}{\\pi}\\arccos"
                    "\\sqrt{\\frac{(\\pi/2)(Z_0/Z_r)}{Q_e}}"
                ),
                quote="- 抽头外部 Q：Q_e=(π/2)(Z0/Z_r)sec²(πτ)（本仓派生，单测以精确分布参数 Y_res(ω)",
                cite="模块 docstring（#118 独立校核：单测以精确分布参数 Y_res(ω) 数值微分对拍）",
            ),
        ),
        boundaries=(
            Boundary(
                quote="阻抗色散（论文式 (10)/(11)）**不实现**——",
                note=(
                    "wcalc 与 qucs-core 在 Q18 常数上互斥且原文不可达——"
                    "#1c/#122 如实登记不解锁。"
                ),
            ),
            Boundary(
                quote="有效域（论文式 (1)+p.85，域外显式 ValueError 不外推）：0.1≤u≤10、",
                note="KJ 域盒（u/g/εr/fn）域外显式拒绝——论文精度声明仅覆盖域内。",
            ),
            Boundary(
                quote="故修正只作用于 hairpin 通道、显式 opt-in",
                note=(
                    "c(gap) 结构修正是 hairpin 专属经验层——闭式本体已由 "
                    "NGSolve 2D 独立核实（k_NG/k_KJ 比值在档），修正不污染"
                    "平行线口径。"
                ),
            ),
            Boundary(
                quote="适用域见 HAIRPIN_KGAP_CALIB，域外不外推（设计反解 raise；fake 前向可显式 clamp）。",
                note="经验修正域外两通道不同语义显式分道：设计反解 raise、fake 前向显式 clamp。",
            ),
        ),
        doc_refs=(
            DocRef(
                path="runs/hairpin_kgap/offline_kj_vs_ngsolve.json",
                quote="偶/奇模 k_NG/k_KJ=1.003/1.018/1.049 @gap 0.8/1.1328/1.6，runs/hairpin_kgap/",
                tracked=False,
            ),
        ),
    ),
    CardSpec(
        kernel_id="finline",
        tagline=(
            "鳍线渐变过渡（波导内 E 面结构）：TE10 导波 β 口径（声明近似档）"
            "+ 小反射剖面反射闭式（指数 sinc/线性 Ei，与 taper_classic 单源"
            "共享）——基模等效经验档因系数原文不可达如实放弃。"
        ),
        modules=("calc_families/finline",),
        primary_entries=(
            ("calc_families/finline", "finline_taper_response"),
            ("calc_families/finline", "finline_taper_length"),
        ),
        test_face_needles=("finline_taper_response", "finline_taper_length"),
        formulas=(
            Formula(
                title="导波相位常数（TE10 截止口径，声明近似档）",
                latex=(
                    "\\beta=k_0\\sqrt{\\varepsilon_{\\mathrm{eff}}}"
                    "\\,\\sqrt{1-\\bigl(f_{c10}/f\\bigr)^2},"
                    "\\qquad f_{c10}=\\frac{c_0}{2a}"
                ),
                quote="β = k0·sqrt(εeff)·",
                quote2="sqrt(1−(fc10/f)²)，fc10 = c0/(2a)（TE10 截止恒等式，与 core/rwg_mmt",
                cite=(
                    "模块 docstring「物理口径」节（empirical 级近似如实声明；"
                    "εeff 缺省 1.0=未加载 TE10 导波口径，调用方可传精化）"
                ),
            ),
            Formula(
                title="小反射剖面反射闭式（精确，共享单源）",
                latex=(
                    "\\Gamma=\\frac{1}{2}\\int\\frac{d(\\ln Z)}{dx}"
                    "\\,e^{-2j\\beta x}\\,dx"
                ),
                quote="Γ = ∫½·d(lnZ)/dx·e^(−2jβx)dx（Pozar 4th ed §5.9）——指数剖面 sinc 闭",
                cite=(
                    "模块 docstring；_gamma_closed/_gamma_quadrature 经 "
                    "taper_classic 单源复用不复制公式（闭式 vs 剖面核数值积分"
                    "双路线残差 1e-15 量级）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="f/fc10 < 1.05 显式拒绝（截止附近 β→0、λg 发散，bethe_hole_coupler 同",
                note="近截止病态带显式拒绝——与 rwg_mmt 近截止降级同哲学。",
            ),
            Boundary(
                quote="非公开可达——硬编码记忆系数即伪造（#122 如实原则），该档如实放弃，",
                note=(
                    "Meier 1974/Sharma-Hoefer 1983 基模等效档未落地——系数原文"
                    "非公开可达，留待拿到原文系数表再立键。"
                ),
            ),
            Boundary(
                quote="——该参数属半经验输入，empirical 性质如实声明。",
                note="epsilon_eff 精化参数是半经验输入，不是闭式输出——性质显式声明。",
            ),
        ),
        doc_refs=(
            DocRef(
                path="src/rfauto/core/calc_families/taper_classic.py",
                quote="式 / 线性剖面 Ei 指数积分闭式，经 core/calc_families/taper_classic 的",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="wilkinson_unequal",
        tagline=(
            "二路不等分 Wilkinson 综合（Pozar K 口径）：功分比 K → 两臂 λ/4 "
            "特性阻抗 + 隔离电阻（含臂端电阻分配）+ 几何均值输出变换段——"
            "闭式与节点导纳网络解算互为独立裁判（#118）。"
        ),
        modules=("calc_families/wilkinson_unequal",),
        primary_entries=(
            ("calc_families/wilkinson_unequal", "unequal_split_wilkinson"),
        ),
        test_face_needles=("unequal_split_wilkinson",),
        formulas=(
            Formula(
                title="功分比与两臂 λ/4 特性阻抗",
                latex=(
                    "K^2=\\frac{P_3}{P_2},\\qquad "
                    "Z_{02}=Z_0\\sqrt{K(1+K^2)},\\qquad "
                    "Z_{03}=Z_0\\sqrt{\\frac{1+K^2}{K^3}}=\\frac{Z_{02}}{K^2}"
                ),
                quote="Z02 = Z0·√(K(1+K²))",
                quote2="Z03 = Z0·√((1+K²)/K³) = Z02/K²（端口 3 臂）",
                cite=(
                    "模块 docstring「公式口径」节（Pozar 4th ed. §7.3 不等分节；"
                    "受惠端=低阻臂，由 λ/4 臂功率流与隔离等压条件直接导出）"
                ),
            ),
            Formula(
                title="隔离电阻与臂端分配（Parad–Moynihan）",
                latex=(
                    "R=Z_0\\frac{1+K^2}{K},\\qquad "
                    "R_2=\\frac{Z_0}{K},\\qquad R_3=K\\,Z_0,"
                    "\\qquad R_2+R_3=R"
                ),
                quote="R  = Z0(1+K²)/K",
                quote2="R2 = Z0/K（端口 2 臂端）、R3 = K·Z0（端口 3 臂端），R2+R3=R",
                cite=(
                    "模块 docstring（两端电阻分配取 Parad–Moynihan 原文约定："
                    "受惠臂端=低阻端；中心频率 S 矩阵只依赖总串联 R）"
                ),
            ),
            Formula(
                title="输出变换段（几何均值选型）",
                latex=(
                    "Z_{04}=Z_0\\sqrt{K},\\qquad "
                    "Z_{05}=\\frac{Z_0}{\\sqrt{K}},\\qquad "
                    "Z_{04}\\,Z_{05}=Z_0^2"
                ),
                quote="Z04 = Z0·√K （端口 2 侧）、Z05 = Z0/√K （端口 3 侧）",
                cite="模块 docstring（Parad–Moynihan 几何均值选型，带宽最优化）",
            ),
        ),
        boundaries=(
            Boundary(
                quote="结果字段 practical_split=False 如实标注，不拒绝）。",
                note=(
                    "K 无上限——超大 K 的臂/电阻比超常规微带可实现域时 "
                    "practical_split=False 如实标注，不拒绝不外推。"
                ),
            ),
            Boundary(
                quote="独立重算全 S 矩阵作裁判（#118：网络解算器与设计闭式互为独立来源）。",
                note="闭式之外以通用节点导纳分析（λ/4 线 j/Z 倒纳网络）独立重算全 S 矩阵作裁判。",
            ),
            Boundary(
                quote="K=1 退化锚 = 经典等分 Wilkinson：两臂 √2·Z0、R=2·Z0、变换段=Z0（同书",
                note="K=1 精确退化到经典等分 Wilkinson——退化锚与文献锚（Microwaves101）都在档。",
            ),
            Boundary(
                quote="带宽内隔离/回损按臂电长度 90° 设计点随频退化（本键只出 f0 闭式）。",
                note="只出中心频率理论量（说明字段）——带内频率响应不在本键声明域。",
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w3a_unsplit_bethe.py",
                quote="50Ω、P2/P3=2（K=1/√2）→ ZA=51.5Ω、ZB=103Ω、R=106.07Ω、变换段",
                tracked=True,
            ),
        ),
    ),
    # ─── aurora_e W4-S19 知识面批 扩容批二（8 张；优先任务书点名的
    # 「专属 CALC 键或 synthesis 面」完备族；引文全部钉在模块源文件） ────
    CardSpec(
        kernel_id="atten_pi",
        tagline=(
            "π 型电阻衰减器综合：目标衰减+系统阻抗 → 中串/两端对地三电阻 "
            "E4 闭式（匹配+分压两条件导出），线宽走 XC-W 单源、shunt 布局"
            "电共位口径——集总闭式裁判与分布式失配的族界在档。"
        ),
        modules=("synthesis", "calc_families/rf_match"),
        primary_entries=(
            ("synthesis", "synthesize_atten_pi_model"),
            ("calc_families/rf_match", "attenuator_pi"),
        ),
        test_face_needles=("attenuator_pi",),
        formulas=(
            Formula(
                title="π 型三电阻 E4 闭式（匹配+分压两条件）",
                latex=(
                    "N=10^{A/20},\\quad "
                    "R_{\\mathrm{ser}}=Z_0\\frac{N^2-1}{2N},\\quad "
                    "R_{\\mathrm{sh}}=Z_0\\frac{N+1}{N-1}"
                ),
                quote="N=电压比=10^(A/20)，推导自匹配+分压两条件",
                quote2="（3dB 锚，经典值：中串 17.612Ω/端并 292.48Ω）",
                cite=(
                    "calc_families/rf_match.attenuator_pi docstring（AU-1 自 "
                    "core/calculators 机械拆分；ABCD 校验有单测）"
                ),
            ),
            Formula(
                title="线宽单源（XC-W，随频率精算）",
                latex="w_{50\\Omega}=\\mathrm{inverse\\_width}(Z_0@f_0)",
                quote=(
                    "w_mm 单源（XC-W）：随 freq_ghz 精算（缺省 2.5GHz 档逐位"
                    "=旧字面量 1.1134）"
                ),
                cite=(
                    "synthesize_atten_pi_model docstring——50Ω 馈线宽唯一计算"
                    "点（test_width_single_source 普查守卫）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="|S21| mean_within ±0.5dB（平坦衰减，均值语义匹配响应形态）",
                note=(
                    "判据统计量匹配响应形态（#195）：平坦衰减用均值语义、"
                    "窄带谐振器件禁用带内 max（常数陷阱族）。"
                ),
            ),
            Boundary(
                quote="shunt_off_mm 缺省 0.75mm=shunt 与串臂断口缘齐贴的电共位布局",
                note=(
                    "集总闭式裁判前提=电共位布局；W7-A 残座批 D=6mm 分布式"
                    "失配定谳——布局偏离共位即出集总模型声明域。"
                ),
            ),
            Boundary(
                quote="衰减量必须 >0 dB",
                note="非正衰减显式拒绝（E4 闭式 N→1 除零域），不静默夹逼。",
            ),
        ),
        doc_refs=(),
    ),
    CardSpec(
        kernel_id="atten_t",
        tagline=(
            "T 型电阻衰减器综合：π 型的横向变体——两臂串阻+中点对地并阻，"
            "同一 E4 电压比闭式族（3dB 经典锚在档），判据与布局口径与 π 型"
            "同源共享。"
        ),
        modules=("synthesis", "calc_families/rf_match"),
        primary_entries=(
            ("synthesis", "synthesize_atten_t_model"),
            ("calc_families/rf_match", "attenuator_t"),
        ),
        test_face_needles=("attenuator_t",),
        formulas=(
            Formula(
                title="T 型三电阻 E4 闭式",
                latex=(
                    "N=10^{A/20},\\quad "
                    "R_{\\mathrm{arm}}=Z_0\\frac{N-1}{N+1},\\quad "
                    "R_{\\mathrm{mid}}=\\frac{2Z_0 N}{N^2-1}"
                ),
                quote="N=电压比=10^(A/20)（经典 3dB 锚：串臂 8.550Ω/中并 141.93Ω）",
                quote2="T 型：上下臂各串 r_series_arm，中点对地 r_shunt_mid",
                cite="calc_families/rf_match.attenuator_t docstring（ABCD 校验有单测）",
            ),
            Formula(
                title="与 π 型的族界（同一电压比 N，电阻分配不同）",
                latex=(
                    "\\pi:\\ R_{\\mathrm{ser}}\\propto\\frac{N^2-1}{2N}"
                    "\\;\\leftrightarrow\\;"
                    "T:\\ R_{\\mathrm{arm}}\\propto\\frac{N-1}{N+1}"
                ),
                quote="T 型衰减器综合（WP2.3 横向变体）：目标衰减 → 三电阻（E4 闭式）。",
                cite=(
                    "synthesize_atten_t_model docstring——objectives 同 atten_pi"
                    "（平坦均值+匹配门）"
                ),
                kind="口径示意（非 docstring 原式，读代码为准）",
            ),
        ),
        boundaries=(
            Boundary(
                quote="电阻值=E4 attenuator_t 闭式（ABCD 校验）：两臂各串 r_series_arm、",
                note="中点对地 r_shunt_mid——电阻值全部出自闭式，零手抄。",
            ),
            Boundary(
                quote="shunt_off_mm 缺省 0.75mm=串臂与中点 shunt 缘齐贴的电共位布局",
                note="同 π 型：集总闭式裁判前提=电共位布局（W7-A 定谳后改）。",
            ),
        ),
        doc_refs=(),
    ),
    CardSpec(
        kernel_id="qwt_multisection",
        tagline=(
            "多节 λ/4 阻抗变换器综合（binomial/chebyshev 表驱动）：一阶小反射"
            "对数域结点增量累积出节阻抗谱系（对称恒等式+中心精确匹配），"
            "f0 给出时走 HJ 链产线宽/物理长度，缺省诚实留空。"
        ),
        modules=("synthesis", "calc_families/rf_match"),
        primary_entries=(
            ("synthesis", "synthesize_multisection_quarter_wave"),
            ("calc_families/rf_match", "quarter_wave_transformer"),
        ),
        test_face_needles=("quarter_wave_transformer",),
        formulas=(
            Formula(
                title="binomial 结点对数增量（一阶小反射表驱动）",
                latex=(
                    "\\delta_i=\\ln\\frac{Z_L}{Z_0}\\cdot"
                    "\\frac{\\binom{N}{i}}{2^N},\\qquad "
                    "Z_i=Z_0\\exp\\Bigl(\\ln\\tfrac{Z_L}{Z_0}"
                    "\\sum_{k<i}\\delta_k\\Bigr)"
                ),
                quote="binomial: δ_i = ln(ZL/Z0)·C(N,i)/2^N（Pozar 4ed binomial 节，N=2 锚",
                quote2="50→100 → 59.4604/84.0896Ω）",
                cite=(
                    "synthesize_multisection_quarter_wave docstring「闭式公式」"
                    "节；chebyshev 走 T_N(secθ0·cosθ) 展开结点权重表"
                ),
            ),
            Formula(
                title="谱系恒等式与中心匹配",
                latex=(
                    "Z_i\\,Z_{N+1-i}=Z_0 Z_L,\\qquad "
                    "Z_{\\mathrm{mid}}=\\sqrt{Z_0 Z_L}\\ "
                    "(N\\ \\text{奇}),\\qquad |S_{11}(f_0)|\\approx 0"
                ),
                quote="谱系恒等式（表构造保证）：Z_i·Z_{N+1-i}=Z0·ZL（对称）；N 奇时中节=√(Z0·ZL)；",
                cite=(
                    "docstring 同节（中心频率精确匹配：全节 λ/4 级联 ABCD；"
                    "chebyshev 偶 N 中心为纹波峰 |S11(f0)|≈Γm 如实声明）"
                ),
            ),
            Formula(
                title="单节 λ/4 变换（rf_match CALC 键）",
                latex="z_{0,\\mathrm{sect}}=\\sqrt{Z_s Z_l},\\quad "
                      "L=\\lambda_g/4",
                quote="λ/4 阻抗变换器：段特性阻抗 z0=sqrt(Zs·Zl)；给 εeff/频率时附物理长度",
                cite="calc_families/rf_match.quarter_wave_transformer 注册描述",
            ),
        ),
        boundaries=(
            Boundary(
                quote="缺省 None → 长度留 None（禁虚构 εeff，#1c）",
                note=(
                    "f0_ghz 未给时只出阻抗级（长度诚实留空）——不虚构介质"
                    "通道（铁律 1c）。"
                ),
            ),
            Boundary(
                quote="chebyshev 权重表仅内嵌 N≤4（表驱动范围），got N=",
                note=(
                    "chebyshev N>4 属精确综合（Riblet/Ozaki-Ishii 数值迭代，"
                    "TF-5 标注可选）——未实现显式 ValueError，不硬凑。"
                ),
            ),
            Boundary(
                quote="无需/无法综合该变换器",
                note=(
                    "ripple 电平不低于原始失配 Γδ 时显式拒绝（无需/无法综合"
                    "的边界显式，不静默返回恒等变换）。"
                ),
            ),
        ),
        doc_refs=(),
    ),
    CardSpec(
        kernel_id="nway_wilkinson",
        tagline=(
            "N-way Wilkinson 功分器阻抗级综合：star（Pon 1961 星形，臂 "
            "√N·Z0）与 tree（2^k 树形，每级经典 2-way 单元）双拓扑闭式——"
            "端口口径等价而臂/隔离电阻不同，N≥3 星形隔离近似级别如实声明。"
        ),
        modules=("synthesis",),
        primary_entries=(
            ("synthesis", "synthesize_nway_wilkinson"),
        ),
        formulas=(
            Formula(
                title="star 星形（Pon 1961）",
                latex=(
                    "Z_{\\mathrm{arm}}=\\sqrt{N}\\,Z_0,\\qquad "
                    "R_{\\mathrm{iso}}=Z_0\\ (\\text{每支，星形公共浮点节点})"
                ),
                quote="star（Pon 1961 星形）：N 支 λ/4 臂各 Z_arm=√N·Z0（N 臂并联于输入结=Z0 闭式",
                quote2="匹配）；N 支隔离电阻各 R=Z0，星形接各输出口与公共浮点节点。N=2 退化为经典",
                cite="synthesize_nway_wilkinson docstring「闭式公式」节",
            ),
            Formula(
                title="tree 树形（2^k）",
                latex=(
                    "n=2^k,\\quad k=\\log_2 n,\\quad "
                    "\\text{每级}=\\sqrt{2}Z_0\\ \\text{臂}+2Z_0\\ "
                    "\\text{隔离}"
                ),
                quote="tree（树形）：仅 n=2^k；每级为既有 2-way 单元（臂 √2·Z0、隔离 R=2·Z0，与",
                quote2="synthesize_wilkinson 同口径），共 k=log2(n) 级、2n-2 支臂、n-1 支隔离电阻。",
                cite="synthesize_nway_wilkinson docstring「闭式公式」节",
            ),
            Formula(
                title="N=2 退化锚（与经典 Wilkinson 同解）",
                latex=(
                    "N=2:\\ Z_{\\mathrm{arm}}=\\sqrt{2}Z_0,\\quad "
                    "R_{\\mathrm{iso}}=2Z_0"
                ),
                quote="N=2 退化为经典 2-way：两支 Z0 串联=隔离 2·Z0=",
                cite=(
                    "synthesize_nway_wilkinson notes——与 synthesize_wilkinson"
                    "（70.7Ω 臂 + 100Ω 隔离）同解"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="但 N>2 时臂阻抗与隔离电阻不同（star N=4：臂 2·Z0=100Ω + R=Z0×4；tree N=4：",
                note=(
                    "两拓扑端口阻抗口径等价、臂/隔离电阻不同——消费方必读"
                    "口径差异（docstring「口径差异」节）。"
                ),
            ),
            Boundary(
                quote="且 N≥3 星形隔离为经典近似（Pon 1961 口径，",
                note=(
                    "N≥3 星形非理想两两隔离、随 N 退化——需理想两两隔离用 "
                    "topology='tree'（近似级别如实声明）。"
                ),
            ),
            Boundary(
                quote="tree 拓扑要求 n 为 2 的幂（2^k），got n=",
                note="非 2 幂显式拒绝并指引 star——不静默取整。",
            ),
            Boundary(
                quote="阻抗级设计，无 f0 不产线宽/臂长",
                note=(
                    "本键只出阻抗级设计——物理尺寸需 f0_ghz+层叠另行精算"
                    "（与 λ/4 臂长链的分界显式）。"
                ),
            ),
        ),
        doc_refs=(),
    ),
    CardSpec(
        kernel_id="schiffman",
        tagline=(
            "Schiffman 90° 定差移相器闭式综合：耦合 U 形全通段与参考直通段的"
            "差分相移恒等式 Δφ=β_ref·L_ref−Φ_c 对 L_ref 线性、一步精确反解——"
            "KJ 反演几何与带宽窗平坦度分析同键产出。"
        ),
        modules=("synthesis",),
        primary_entries=(
            ("synthesis", "synthesize_schiffman"),
        ),
        formulas=(
            Formula(
                title="参考段一步精确反解",
                latex=(
                    "\\Delta\\varphi=\\beta_{\\mathrm{ref}}L_{\\mathrm{ref}}"
                    "-\\Phi_c(f_0),\\qquad "
                    "L_{\\mathrm{ref}}=\\frac{\\Phi_c(f_0)+\\delta_{"
                    "\\mathrm{rad}}}{\\beta_{\\mathrm{ref}}(f_0)}"
                ),
                quote="L_ref = (Φ_c(f0) + δ_rad)/β_ref(f0)。",
                cite=(
                    "synthesize_schiffman docstring（Δφ 对 L_ref 线性、一步"
                    "精确反解；schiffman_delta_phase 同源注释）"
                ),
            ),
            Formula(
                title="耦合段电长度口径",
                latex="\\theta_0=\\mathrm{ratio}\\cdot 90^\\circ",
                quote="耦合段长度取耦合长度比语义：f0 处偶/奇模",
                quote2="平均电长度 θ0 = coupling_length_ratio·90°（1.0 = 经典 λ/4 耦合段）；",
                cite="synthesize_schiffman docstring（模型：耦合段=平行耦合 U 形全通段，Schiffman 1958 口径）",
            ),
        ),
        boundaries=(
            Boundary(
                quote="- 准静态 εeff 逐模常数化（KJ 反演联动，不含色散）；",
                note="v1 闭式口径显式声明：不含色散/近场/宽度渐变修正。",
            ),
            Boundary(
                quote="参考段 εeff 取模平均相速口径；近场/色散/宽度渐变修正不做。",
                note="参考段 εeff=偶/奇模平均相速口径——与内核 v1 同一假设面。",
            ),
            Boundary(
                quote="Z0e 须大于 Z0o（耦合线偶/奇模阻抗物理序）",
                note="偶/奇模物理序守卫（反序显式拒绝，不外推）。",
            ),
            Boundary(
                quote="coupling_length_ratio 须在 (0, 2]（θ0=ratio·90°，越域不外推），got ",
                note="耦合长度比越域显式拒绝（(0,2] 值域）。",
            ),
        ),
        doc_refs=(),
    ),
    CardSpec(
        kernel_id="bethe_hole_coupler",
        tagline=(
            "Bethe 孔定向耦合器（矩形波导共宽壁中心圆孔）：小孔极化率偶/奇"
            "支路 E+M/E−M 结构给出耦合/隔离/方向性闭式，综合方向 c∝d³ 反解"
            "三次式——Cohn 有限壁厚修正 opt-in、近似层级与守卫逐条声明。"
        ),
        modules=("calc_families/bethe_hole",),
        primary_entries=(
            ("calc_families/bethe_hole", "bethe_hole_coupler"),
        ),
        test_face_needles=("bethe_hole_coupler",),
        formulas=(
            Formula(
                title="Bethe 小孔极化率（零厚无限屏）",
                latex="\\alpha_e=\\tfrac{2r^3}{3},\\qquad \\alpha_m=\\tfrac{4r^3}{3}",
                quote="αe=2r³/3、αm=4r³/3（H. A. Bethe,",
                quote2='"Theory of Diffraction by Small Holes", Phys. Rev. 66:66, 1944；',
                cite=(
                    "模块 docstring「物理口径」节（与 "
                    "core/aperture_coupling.bethe_polarizability_circle 同源"
                    "单源消费）"
                ),
            ),
            Formula(
                title="耦合/隔离幅值（E、M 支路同相相加/反相相消）",
                latex=(
                    "|c_{\\mathrm{coup}}|=\\tfrac{2\\omega}{ab}"
                    "\\bigl(\\varepsilon_0\\alpha_e Z_{10}"
                    "+\\mu_0\\alpha_m/Z_{10}\\bigr),\\quad "
                    "|c_{\\mathrm{iso}}|=\\tfrac{2\\omega}{ab}"
                    "\\bigl|\\varepsilon_0\\alpha_e Z_{10}"
                    "-\\mu_0\\alpha_m/Z_{10}\\bigr|"
                ),
                quote="|c_耦合| = (2ω/(ab))·(ε0αe·Z10 + μ0αm/Z10)    （E、M 同相相加）",
                quote2="|c_隔离| = (2ω/(ab))·|ε0αe·Z10 − μ0αm/Z10|    （反相相消）",
                cite=(
                    "模块 docstring（功率归一化模反应式；两项同量纲、乘积"
                    "无量纲幅值比已核实）"
                ),
            ),
            Formula(
                title="方向性极值（设计频率 E/M 平衡）",
                latex=(
                    "\\frac{M}{E}=2\\Bigl(\\frac{\\beta}{k_0}\\Bigr)^{\\!2},"
                    "\\quad f=\\frac{c_0}{\\sqrt{2}\\,a}\\Rightarrow "
                    "D\\to\\infty"
                ),
                quote="M/E 比 = (αm/αe)·(η0/Z10)² = 2(β/k0)²：f = c0/(√2·a)（λg=2a）时隔离",
                cite=(
                    "模块 docstring（隔离向严格相消→单孔方向性无究大；偏离"
                    "设计频率 D=20lg[(E+M)/|E−M|] 退化，窄带单孔特性）"
                ),
            ),
            Formula(
                title="Cohn 有限壁厚修正（opt-in）",
                latex="R=\\frac{1}{1-(f/f_{\\mathrm{res}})^2},\\quad "
                      "e^{-\\alpha_{\\mathrm{cut}}t}",
                quote="①孔口共振增强因子 R=1/(1−(f/f_res)²)，f_res 取对应圆波导截止常数",
                cite=(
                    "模块 docstring（f_res,m=c0/(1.706d) TE11 型、f_res,e="
                    "c0/(1.305d) TM01 型；孔颈截止衰减 Collin 截止波导节；"
                    "近似层级如实声明）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="- f ≤ fc10 或 f/fc < 1.05（截止附近 λg 发散，Bethe 场系数失真）；",
                note="近截止病态带显式拒绝（finline/rwg_mmt 同哲学）。",
            ),
            Boundary(
                quote="d>λ0/3（小孔假设 d≪λ0）；",
                note="一阶小孔假设域守卫（d>0.8·b 窄边比例上限同守卫族）。",
            ),
            Boundary(
                quote="Cohn 域 f≥0.9·f_res,m 显式拒绝（共振因子发散）；",
                note="修正因子发散域显式拒绝——不外推共振奇点。",
            ),
            Boundary(
                quote="（|c|≪1，不迭代加载修正）、无孔间互耦（多孔阵口径只给 λg/4 间距）。",
                note="弱耦合单孔口径：不迭代加载修正、多孔阵只给间距口径。",
            ),
        ),
        doc_refs=(),
    ),
    CardSpec(
        kernel_id="gysel_core",
        tagline=(
            "Gysel 功分器 core 电气闭式族：六 λ/4 电气段拓扑（桥带 λ/2 中点="
            "对称面真实节点）+偶/奇模半电路验证+五线六节点导纳网络精确频响"
            "——隔离负载外置可独立散热，是与内嵌电阻 Wilkinson 的族界。"
        ),
        modules=("calc_families/gysel_core",),
        primary_entries=(
            ("calc_families/gysel_core", "gysel_core_synthesize"),
            ("calc_families/gysel_core", "gysel_frequency_response"),
        ),
        test_face_needles=("gysel_core_synthesize", "gysel_frequency_response"),
        formulas=(
            Formula(
                title="六 λ/4 电气段拓扑（#206 定版）",
                latex=(
                    "P_1\\xrightarrow{\\sqrt{2}Z_0}P_{2/3},\\quad "
                    "P_{2/3}\\xrightarrow{Z_0}\\Delta_{1/2},\\quad "
                    "\\Delta_1\\xrightarrow{Z_0\\,\\lambda/2}\\\\\\Delta_2"
                ),
                quote="拓扑（六 λ/4 电气段）：P1—[√2·Z0 臂]—P2 与 P1—[√2·Z0 臂]—P3；",
                quote2="P2—[Z0 隔离线]—Δ1 与 P3—[Z0 隔离线]—Δ2；Δ1—[Z0 λ/2 桥带，中点 M]—",
                cite="模块 docstring「物理口径」节（Δ1/Δ2 各端接 Z0 负载，可独立散热=大功率口径）",
            ),
            Formula(
                title="偶/奇模半电路验证（Γe=Γo=0）",
                latex="\\Gamma_e=\\Gamma_o=0,\\quad S_{22}=S_{32}=0",
                quote="偶模：臂 λ/4 把 2Z0 变换为 Z0（Γe=0）；桥带半段 λ/4 端接虚开路→短",
                quote2="奇模：P1/M=虚地，臂与桥带半段 λ/4 变开路；输出只见 λ/4 隔离线端接",
                cite="模块 docstring（对称面虚开路/虚地；f0 精确匹配+隔离闭式）",
            ),
            Formula(
                title="理想 f0 三口 S 矩阵",
                latex="S_{21}=S_{31}=-\\tfrac{j}{\\sqrt{2}},\\quad "
                      "S_{32}=0",
                quote="理想 f0 三口 S 矩阵：S21=S31=−j/√2（臂 −90°+均分 3.0103dB）、全对角",
                quote2="与 S32=0（互易 S=Sᵀ；内负载吸收→非无耗不幺正，如实注记）。",
                cite="模块 docstring（−3.0103dB 恒等；互易非幺正如实注记）",
            ),
            Formula(
                title="五线六节点导纳网络精确频响",
                latex="Y_{\\mathrm{self}}=-j\\frac{\\cot\\theta}{Z_c},"
                      "\\quad Y_{\\mathrm{mutual}}=\\frac{j}{Z_c\\sin\\theta}",
                quote="Y_self=−j·cotθ/Zc、Y_mutual=j/(Zc·sinθ)（λ/4 反解 Z_in=Zc²/ZL 由该",
                cite=(
                    "模块 docstring（内节点消元得 3 口 Y_red；耗散守恒 "
                    "|a1|²=Σ|b_k|²+|V_Δ1|²/Z0+|V_Δ2|²/Z0 残差字段构造恒成立）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="判废锚（#206）：无桥带朴素拓扑带心 S21≈−6.5dB——λ/2 桥带",
                note="λ/2 桥带是隔离的必要环节（判废对照字段在键，#206 同口径）。",
            ),
            Boundary(
                quote="守卫：z0_ohm>0；freq_ghz/f0_ghz>0 且避开线节 θ=kπ 奇异点（f=2k·f0 显",
                note="频域奇异守卫：f=2k·f0 线节 θ=kπ 显式拒绝（桥带按 M 拆两段规避 f0 奇异）。",
            ),
            Boundary(
                quote="（纯电气闭式，无叠层依赖；频响键补全 f0 以外的带宽行为，模板/裁判均",
                note=(
                    "族界三层：模板级（synthesize_gysel_model 出几何）/裁判级"
                    "（fake 理想 S）/本族=core 注册计算器级（纯电气+频响带宽面）。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_a6b_multisection_gysel.py",
                quote="tests/unit/test_a6b_multisection_gysel.py",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="coupled_line_bpf",
        tagline=(
            "平行耦合线带通滤波器实现族：全极点切比雪夫 g 值→J 倒置器→逐节 "
            "(Z0e,Z0o)→KJ 二维反解微带 (w,s)——耦合矩阵级（C13）之下的"
            "器件实现尺寸级，Pozar Example 8.7 阻抗表逐位锚。"
        ),
        modules=("calc_families/coupled_line_bpf",),
        primary_entries=(
            ("calc_families/coupled_line_bpf", "coupled_line_bpf_synthesize"),
            ("calc_families/coupled_line_bpf", "coupled_line_bpf_response"),
        ),
        test_face_needles=(
            "coupled_line_bpf_synthesize",
            "coupled_line_bpf_response",
        ),
        formulas=(
            Formula(
                title="J 倒置器（Pozar §8.6，MYJ ch.8 同源）",
                latex=(
                    "x_{01}=\\sqrt{\\frac{\\pi\\delta}{2g_0g_1}},\\quad "
                    "x_j=\\frac{\\pi\\delta/2}{\\sqrt{g_jg_{j+1}}},\\quad "
                    "x_n=\\sqrt{\\frac{\\pi\\delta}{2g_ng_{n+1}}}"
                ),
                quote="x_01 = J_01/Z0 = sqrt(π·δ/(2·g_0·g_1))          （端节）",
                quote2="x_j  = J_j,j+1/Z0 = (π·δ/2)/sqrt(g_j·g_{j+1})   （内节，j=1..n−1）",
                cite=(
                    "模块 docstring「物理口径」节（g 值走 "
                    "core/matching.chebyshev_g_values，Pozar 表 8.4 递推）"
                ),
            ),
            Formula(
                title="逐节奇偶模阻抗（Pozar 式 8.13x 精确形）",
                latex="Z_{0e}=Z_0(1+x+x^2),\\qquad "
                      "Z_{0o}=Z_0(1-x+x^2)",
                quote="Z0e = Z0·(1 + x + x²)，  Z0o = Z0·(1 − x + x²)",
                cite=(
                    "模块 docstring（反解恒等式 x=(Z0e−Z0o)/(2Z0) 测试钉；"
                    "同步 TEM 极限下中心频率精确）"
                ),
            ),
            Formula(
                title="段长/谐振器长（KJ 正向回代+开路端修正）",
                latex="L=\\frac{\\lambda_0}{4}\\sqrt{\\frac{2}{\\varepsilon_e"
                      "+\\varepsilon_o}},\\quad "
                      "L_{\\mathrm{res}}=\\lambda_g/2-2\\Delta l",
                quote="正向回代出 εeff_e/εeff_o → 段长 = λ0/4·sqrt(2/(εe+εo))；谐振器 =",
                quote2="λg/2（两邻段平均 εeff）− 2×Δl（Hammerstad 开路端修正，core",
                cite=(
                    "模块 docstring（(Z0e,Z0o)→(w,s) 稳健二维数值反解，正向="
                    "coupled_microstrip_even_odd_ohm KJ 1984 闭式）"
                ),
            ),
            Formula(
                title="频响（偶/奇模叠加 4 端口+交叉口压缩）",
                latex="S^{(4\\square)}=\\tfrac{1}{2}(S^e+S^o)"
                      "\\xrightarrow{\\Gamma=+1}S^{(2\\square)}"
                      "\\xrightarrow{\\mathrm{ABCD}}S",
                quote="每节 = 偶/奇模各自 2 端口线 S 叠加构造 4 端口 S（构造恒满足无耗/互易），",
                cite=(
                    "模块 docstring「频响键口径」节（交叉口 Γ=+1 开路端接压缩"
                    "2 端口，S→ABCD 按 Pozar Table 4.2）"
                ),
                kind="口径示意（非 docstring 原式，读代码为准）",
            ),
        ),
        boundaries=(
            Boundary(
                quote="f0=2 GHz、δ=10%、Z0=50 → (Z0e,Z0o) = (70.61,39.24)/(56.64,44.77)/",
                note=(
                    "Pozar Example 8.7（p.435 4th ed）文献例逐位复现锚"
                    "（εr/h 无关）；g 值 vs 教科书表 1.5963/1.0967。"
                ),
            ),
            Boundary(
                quote="（带缘倒置器频率依赖的二阶偏差，实测 ~0.28 dB）；带心 |S21|=0 dB、带内",
                note="倒置器 λ/4 实现的二阶修正是带内偏差来源——如实锚定 ~0.28dB。",
            ),
            Boundary(
                quote="order 为 ≥2 整数；0<fbw≤1；ripple_db>0；z0_ohm>0；epsilon_r≥1；",
                note="规格域守卫族；KJ 反解越域（极宽/极窄带不可实现）显式拒绝并附节序号。",
            ),
            Boundary(
                quote="（Mathaei-Pollard-Feit ch.8 / Pozar §8.6.2 口径）。",
                note=(
                    "族界：C13=耦合矩阵级（无物理尺寸）、模板渲染级=KJ 反解链"
                    "绑定渲染管线——本族=core 注册键面的器件实现尺寸级"
                    "（无 TZ、无折叠/箭头拓扑）。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_a3c_coupled_interdigital.py",
                quote="tests/unit/test_a3c_coupled_interdigital.py",
                tracked=True,
            ),
        ),
    ),
)


def _sanitize_cite(text: str) -> str:
    """收敛手写 cite 字段（防御性：折叠意外换行/多空格，保证卡内单行渲染）。"""
    return re.sub(r"\s+", " ", text).strip()


# ─── 三源与代码面装载 ────────────────────────────────────────────────────────


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def module_path(stem: str) -> Path:
    return CORE_DIR / f"{stem}.py"


def module_text(stem: str) -> str:
    return module_path(stem).read_text(encoding="utf-8")


def module_docstring(stem: str) -> str:
    doc = ast.get_docstring(ast.parse(module_text(stem)))
    if not doc:
        raise RuntimeError(f"{stem}.py 无模块 docstring")
    return doc


def docstring_first_line(stem: str) -> str:
    return module_docstring(stem).strip().splitlines()[0].strip()


def public_symbols(stem: str) -> list[str]:
    """顶层 def/class 公开符号（无下划线前缀），按源码出现序。"""
    tree = ast.parse(module_text(stem))
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and not node.name.startswith("_"):
            names.append(node.name)
    return names


def has_calculator_decorator(stem: str) -> bool:
    """AST 判定是否挂 @register_calculator（docstring 提及不算）。"""
    tree = ast.parse(module_text(stem))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            continue
        for dec in node.decorator_list:
            name = dec.func.id if isinstance(dec, ast.Call) else getattr(dec, "id", None)
            if name == "register_calculator":
                return True
    return False


def _references_module(text: str, stem: str) -> bool:
    # 子包 stem（calc_families/名）归一为点分模块路径后匹配；顶层 stem
    # 行为与历史逐字节一致（dot_stem==stem）。
    dot_stem = stem.replace("/", ".")
    if f"rfauto.core.{dot_stem}" in text:
        return True
    parent, _, tail = dot_stem.rpartition(".")
    if parent:
        pat = (
            rf"from rfauto\.core\.{re.escape(parent)} import "
            rf"[^\n]*\b{re.escape(tail)}\b"
        )
    else:
        pat = rf"from rfauto\.core import [^\n]*\b{re.escape(stem)}\b"
    return re.search(pat, text) is not None


def referencing_tests(
    stem: str, extra_needles: tuple[str, ...] = ()
) -> list[tuple[str, int]]:
    """tests/unit 下引用本模块的测试文件（排序）+ def test_ 计数。

    extra_needles：CALC 键名等附加命中串——经 run_calculator 间接消费、
    无 import 面的子包内核（如 finline/wilkinson_unequal）的测试面靠它
    显式收录；命中串是显式声明面，不做任何猜测式扩展。

    test_kernel_cards.py 自身排除（#330 自录行教训同族）：保鲜门测试的
    CARD_KERNELS 选题集含卡 id 字面量——当卡 id 恰为 CALC 键名（如
    bethe_hole_coupler）时会把「本生成器的选题裁决」误计成消费面。
    """
    out: list[tuple[str, int]] = []
    for path in sorted(TESTS_UNIT_DIR.glob("test_*.py")):
        if path.name == "test_kernel_cards.py":
            continue
        text = path.read_text(encoding="utf-8")
        if _references_module(text, stem) or any(n in text for n in extra_needles):
            out.append((path.name, len(re.findall(r"def (test_\w+)", text))))
    return out


def test_face_rows(spec: CardSpec) -> list[tuple[str, int]]:
    """卡测试面单源（render_card 与保鲜门测试共用，防双实现漂移）。"""
    seen: list[tuple[str, int]] = []
    for mod_stem in spec.modules:
        for name, count in referencing_tests(mod_stem, spec.test_face_needles):
            if (name, count) not in seen:
                seen.append((name, count))
    return seen


def consumers(stem: str) -> list[tuple[str, str]]:
    """service/adapters 消费面（目录组、相对 repo 的文件路径）。"""
    found: list[tuple[str, str]] = []
    for label, base in CONSUMER_DIRS:
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if _references_module(path.read_text(encoding="utf-8"), stem):
                found.append((label, path.relative_to(REPO_ROOT).as_posix()))
    return found


def kd1_entries(kernel_file: str) -> list[dict[str, Any]]:
    data = _load_yaml(KD1_YAML)
    entries = [e for e in data.get("entries", []) if e.get("kernel_file") == kernel_file]
    return sorted(entries, key=lambda e: str(e.get("formula_id", "")))


def xcp_kernels() -> dict[str, Any]:
    data = _load_yaml(XCP_YAML)
    kernels = data.get("kernels")
    if not isinstance(kernels, dict) or not kernels:
        raise RuntimeError("precision_profiles.yaml 缺 kernels 键或为空")
    return kernels


def anchor_entries() -> list[dict[str, Any]]:
    data = _load_yaml(ANCHORS_YAML)
    found: list[dict[str, Any]] = []

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            if "anchor_id" in node:
                found.append(node)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(data)
    return found


def anchors_for(stem: str) -> list[dict[str, Any]]:
    needle = f"core/{stem}."
    matched = [
        e for e in anchor_entries()
        if needle in json.dumps(e, ensure_ascii=False)
    ]
    return sorted(matched, key=lambda e: str(e.get("anchor_id", "")))


# ─── 渲染 ────────────────────────────────────────────────────────────────────


def _md_cell(text: str) -> str:
    """表格单元格安全化（竖线转义、换行折叠）。"""
    return str(text).replace("|", "\\|").replace("\n", " ")


def _md_text(text: str) -> str:
    """行文安全化（仅折叠换行，不转义竖线——竖线转义只用于表格）。"""
    return str(text).replace("\n", " ")


def _quote_lines(quote: str, quote2: str | None) -> str:
    parts = [f'"{_md_text(quote)}"']
    if quote2:
        parts.append(f'"{_md_text(quote2)}"')
    return " + ".join(parts)


def _render_kd1_section(stem: str) -> list[str]:
    kernel_file = f"src/rfauto/core/{stem}.py"
    entries = kd1_entries(kernel_file)
    lines = [
        f"### KD-1 出处注册（`{kernel_file}`，knowledge/formula_provenance.yaml 过滤）",
        "",
    ]
    if not entries:
        lines += [
            "命中 **0 条**——该模块 docstring 无「出处见/出处（」收集标记命中"
            "或未逐式登记。出处以模块 docstring 为单源（上方公式引文即逐字"
            "出自 docstring）；登记缺口如实呈现，属 XA-6 出处断链巡检门的"
            "巡检范围，不在本卡掩饰。",
        ]
        return lines
    lines += [
        f"命中 **{len(entries)}** 条：",
        "",
        "| formula_id | symbol | kind | source_doi | refs |",
        "|---|---|---|---|---|",
    ]
    for e in entries:
        refs = "；".join(str(r) for r in (e.get("refs") or [])) or "—"
        doi = str(e.get("source_doi") or "—")
        lines.append(
            f"| {e.get('formula_id', '—')} | {e.get('symbol', '—')} | "
            f"{e.get('kind', '—')} | {_md_cell(doi)} | {_md_cell(refs)} |"
        )
    return lines


def _render_xcp_section(kernel_id: str) -> list[str]:
    kernels = xcp_kernels()
    if kernel_id in kernels:
        profile = kernels[kernel_id]
        # 已建档内核走完整渲染（首批 5 内核暂不走此支路；保留以供扩卡复用）
        lines = [
            f"XC-P 已建档（knowledge/precision_profiles.yaml#{kernel_id}），"
            f"out_of_domain_behavior=`{profile.get('out_of_domain_behavior')}`、"
            f"last_verified={profile.get('last_verified')}。",
            "",
            "| quantity | band | direction | unverified | condition |",
            "|---|---|---|---|---|",
        ]
        for dev in profile.get("typical_deviation", []):
            lines.append(
                f"| {dev.get('quantity') or '（全量）'} | "
                f"{_md_cell(str(dev.get('band')))} | "
                f"{dev.get('direction')} | {dev.get('unverified')} | "
                f"{_md_cell(str(dev.get('condition')))} |"
            )
        note = str(profile["valid_domain"].get("note", ""))
        lines += ["", f"域声明 note：{_md_cell(note)}"]
        return lines
    keys = sorted(kernels)
    return [
        f"**未收录**：XC-P 首批建档内核共 **{len(keys)}** 个"
        f"（{'、'.join(keys)}），不含 `{kernel_id}`。因此：",
        "",
        "- 典型偏差分档：**UNVERIFIED**（无档案即无分档；本卡不编造任何"
        "精度数字——铁律 7 / #122 如实标注）；",
        "- 域判查询：`core/precision_profiles.py` 对未知 kernel 如实降级"
        f"（收集器=`{COLLECTOR_TEST_REL}` 逐条对照防漂移）；",
        "- 建档入口：precision_profiles.yaml 增键（schema 见该文件头）+ "
        "`KERNEL_MODULES` 映射 + 模块 docstring 末尾「精度档案」镜像行 + "
        "重跑本生成器。",
    ]


def render_card(spec: CardSpec) -> str:
    """渲染单张文档卡（确定性：键序/遍历序显式、无时间戳）。"""
    main_mod = spec.modules[0]
    lines: list[str] = [CARD_BANNER, f"# 内核文档卡：{spec.kernel_id}", ""]

    doc_first = docstring_first_line(main_mod)
    kd1_count = len(kd1_entries(f"src/rfauto/core/{main_mod}.py"))
    extra_mods = "、".join(f"`src/rfauto/core/{m}.py`" for m in spec.modules[1:])
    reg = (
        "已注册 @register_calculator"
        if has_calculator_decorator(main_mod)
        else (
            "未注册（AST 无 @register_calculator 装饰器——service 直调型内核，"
            "免 #231 注册表消费者三表同步）"
        )
    )
    lines += [
        f"> {doc_first}",
        "",
        "| 字段 | 值 |",
        "|---|---|",
        f"| 内核 ID | `{spec.kernel_id}` |",
        f"| 主模块 | `src/rfauto/core/{main_mod}.py`"
        f"（`rfauto.core.{main_mod.replace('/', '.')}`） |",
    ]
    if extra_mods:
        lines.append(f"| 同族模块 | {extra_mods} |")
    lines += [
        f"| 计算器注册表 | {reg} |",
        f"| KD-1 出处注册 | {kd1_count} 条（kernel_file=src/rfauto/core/{main_mod}.py） |",
        "| XC-P 精度档案 | 见下方「精度域」节（机读判定） |",
        "| 数据来源 | XC-P + KD-1 + 模块 docstring/AST + anchors.yaml + tests/service 扫描 |",
        "",
    ]

    # 物理语义
    lines += [
        "## 物理语义",
        "",
        spec.tagline,
        "",
        f"模块自述（docstring 首行，机读）：{doc_first}",
        "",
    ]

    # 公式与口径
    lines += ["## 公式与口径", ""]
    for f in spec.formulas:
        lines += [
            f"### {f.title}",
            "",
            f"（{f.kind}）",
            "",
            "```latex",
            f.latex,
            "```",
            "",
            f"出处：{_sanitize_cite(f.cite)}。",
            "",
            f"docstring 逐字引文（防漂移钉）：{_quote_lines(f.quote, f.quote2)}",
            "",
        ]
    lines += _render_kd1_section(main_mod)
    lines.append("")

    # 精度域
    lines += ["## 精度域（XC-P 精度档案）", ""]
    lines += _render_xcp_section(spec.kernel_id)
    lines += [
        "",
        "> 本节为机读聚合：XC-P 收录状态与键清单构建时实测；"
        "本内核建档后此节自动展开为分档表（渲染支路已备）。",
        "",
    ]

    # 使用边界
    lines += ["## 使用边界", ""]
    for b in spec.boundaries:
        lines += [
            f"- {b.note}",
            f"  - docstring 逐字引文：{_quote_lines(b.quote, None)}",
        ]
    lines.append("")

    # 代码入口
    lines += ["## 代码入口", "", "主入口（file:symbol，AST 校验存在）：", ""]
    for mod_stem, sym in spec.primary_entries:
        lines.append(f"- `src/rfauto/core/{mod_stem}.py:{sym}`")
    lines.append("")
    for mod_stem in spec.modules:
        syms = public_symbols(mod_stem)
        rendered = "、".join(f"`{s}`" for s in syms)
        lines += [
            f"src/rfauto/core/{mod_stem}.py 公开符号 **{len(syms)}** 个（AST 机读）：",
            "",
            rendered,
            "",
        ]
    cons = [(label, rel) for m in spec.modules for (label, rel) in consumers(m)]
    if cons:
        lines += ["消费面（service/adapters 引用扫描，机读）：", ""]
        for label, rel in cons:
            lines.append(f"- {label}：`{rel}`")
        lines.append("")

    # 锚与测试入口
    lines += ["## 锚与测试入口", ""]
    anchors = [a for m in spec.modules for a in anchors_for(m)]
    if anchors:
        lines += [
            "analytic-anchor（knowledge/anchors.yaml 机读命中）：",
            "",
            "| anchor_id | quantity |",
            "|---|---|",
        ]
        for a in anchors:
            qname = (a.get("quantity") or {}).get("name", "—")
            lines.append(f"| `{a.get('anchor_id', '—')}` | {qname} |")
        lines.append("")
    else:
        lines += [
            "analytic-anchor：knowledge/anchors.yaml 机读命中 **0 条**"
            "（XA-10「已双路径互证内核登记 analytic-anchor 轻条目」的延伸项——"
            "登记后重跑本生成器）。",
            "",
        ]
    if spec.doc_refs:
        lines += ["判据书/规格指针（docstring 逐字引文钉）：", ""]
        for ref in spec.doc_refs:
            exist_note = "" if ref.tracked else "（仓内档，公开分发视图不随附，存在性不作测试断言）"
            lines.append(f"- `{ref.path}`{exist_note}——引文：\"{_md_text(ref.quote)}\"")
        lines.append("")
    all_tests = test_face_rows(spec)
    total = sum(c for _, c in all_tests)
    lines += [
        f"测试面（tests/unit 引用扫描，机读；合计 **{total}** 个 test 函数）：",
        "",
        "| 测试文件 | test 函数数 |",
        "|---|---|",
    ]
    for name, count in all_tests:
        lines.append(f"| `tests/unit/{name}` | {count} |")
    lines += [
        "",
        f"XC-P 精度档案收集器（防漂移对照面）：`{COLLECTOR_TEST_REL}`；"
        "本卡保鲜门：`tests/unit/test_kernel_cards.py`。",
        "",
    ]

    # 关联
    others = "、".join(
        f"[{s.kernel_id}]({s.kernel_id}.md)" for s in SPECS if s.kernel_id != spec.kernel_id
    )
    lines += [
        "## 关联",
        "",
        "- [架构与方法论（锚体系/判据先行）](../architecture/methodology.md)",
        "- [分层架构](../explanation/layered-architecture.md)",
        "- [计算器注册表](../reference/calculators.md)——本内核的注册状态见元数据表",
        f"- 同批内核卡：{others}",
        "",
    ]
    return "\n".join(lines) + "\n"


# ─── 构建期校验（引文钉/入口存在性——写卡前先自证） ─────────────────────────


def validate_spec(spec: CardSpec) -> list[str]:
    problems: list[str] = []
    texts: dict[str, str] = {}
    for mod_stem in spec.modules:
        path = module_path(mod_stem)
        if not path.is_file():
            problems.append(f"模块不存在：{path}")
            continue
        texts[mod_stem] = module_text(mod_stem)
    # 引文钉：引文须存在于规格内任一同族模块源文件（引文钉在其来源 docstring）
    union = "\n".join(texts.values())
    where = "/".join(texts)
    for f in spec.formulas:
        for q in (f.quote, f.quote2):
            if q and q not in union:
                problems.append(f"{spec.kernel_id}: 公式引文不在 {where}：{q!r}")
    for b in spec.boundaries:
        if b.quote not in union:
            problems.append(f"{spec.kernel_id}: 边界引文不在 {where}：{b.quote!r}")
    for ref in spec.doc_refs:
        if ref.quote not in union:
            problems.append(f"{spec.kernel_id}: 指针引文不在 {where}：{ref.quote!r}")
        if ref.tracked and not (REPO_ROOT / ref.path).is_file():
            problems.append(f"{spec.kernel_id}: tracked 指针不存在：{ref.path}")
    for mod_stem, text in texts.items():
        tree = ast.parse(text)
        top_names = {
            n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
        }
        for entry_mod, sym in spec.primary_entries:
            if entry_mod == mod_stem and sym not in top_names:
                problems.append(f"{spec.kernel_id}: 入口符号不存在 {mod_stem}.py:{sym}")
    if not docstring_first_line(spec.modules[0]):
        problems.append(f"{spec.kernel_id}: docstring 首行为空")
    return problems


def validate_all() -> None:
    problems: list[str] = []
    for spec in SPECS:
        problems.extend(validate_spec(spec))
    if problems:
        raise RuntimeError("构建期校验失败（引文钉/入口存在性）——\n" + "\n".join(problems))


# ─── CLI ─────────────────────────────────────────────────────────────────────


def render_all() -> dict[str, str]:
    validate_all()
    return {spec.kernel_id: render_card(spec) for spec in SPECS}


def build(target_dir: Path) -> list[str]:
    rendered = render_all()
    target_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for kernel_id, content in rendered.items():
        out = target_dir / f"{kernel_id}.md"
        out.write_text(content, encoding="utf-8", newline="\n")
        try:
            written.append(str(out.relative_to(REPO_ROOT)))
        except ValueError:  # 域外目标（测试 tmp_path）：回退绝对路径，不炸构建
            written.append(str(out))
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="XA-8 内核域文档卡生成器（首批 5 张 + W3-S13 批一 11 张 + W4-S19 批二 8 张）")
    parser.add_argument(
        "--check", action="store_true",
        help="漂移检查：重渲染与已提交卡逐字节比对，漂移即退出码 1（不写文件）",
    )
    parser.add_argument(
        "--out", type=str, default=None,
        help="输出目录（缺省 docs_site/kernel_cards；测试隔离用）",
    )
    args = parser.parse_args(argv)
    target = Path(args.out) if args.out else CARDS_DIR
    if args.check:
        rendered = render_all()
        drifted = [
            kernel_id for kernel_id, content in rendered.items()
            if (target / f"{kernel_id}.md").read_text(encoding="utf-8") != content
        ]
        if drifted:
            print(f"[kernel-cards] 漂移：{drifted}——重跑 python scripts/build_kernel_cards.py")
            return 1
        print(f"[kernel-cards] OK：{len(rendered)} 张卡与三源同步")
        return 0
    written = build(target)
    print(f"[kernel-cards] 写出 {len(written)} 张卡：{written}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
