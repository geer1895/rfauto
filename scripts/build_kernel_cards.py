#!/usr/bin/env python3
"""XA-8 内核域文档卡生成器（round18 规格 XA-8：内核域文档卡首批 5 张）。

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
- XA-8 首批 5 内核（macromodel/rwg_mmt/pdn/pce/cascade）均不在 XC-P
  首批 10 内核——精度域节如实呈现「未收录 + UNVERIFIED + 建档入口」，
  不编造分档数字。

用法（venv 内、仓根执行）：
    python scripts/build_kernel_cards.py           # 原地重建 5 张卡
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
    modules: tuple[str, ...]  # core 模块 stem（首个=主模块）
    primary_entries: tuple[tuple[str, str], ...]  # (module_stem, symbol)
    formulas: tuple[Formula, ...]
    boundaries: tuple[Boundary, ...]
    doc_refs: tuple[DocRef, ...]


# ─── 五张卡的选题（round18 规格 XA-8：macromodel/rwg_mmt/pdn/pce/cascade） ──

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
                path="docs/续跑计划",
                quote="任务来源：续跑计划 §10.3 D13 / §10.19 第 2 条。",
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
                    "规格 规格深案 DP-1 §2.3"
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
                path="规格深案",
                quote="规格 = 规格深案 DP-1 §2；",
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
                path="研究扩充",
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
                    "±10%（续跑计划 §10.15 预声明）。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="docs/续跑计划",
                quote="docs/续跑计划.md §10.4 D8：稀疏 PCE（ChaosPy/OpenTURNS）",
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
                path="规格深案",
                quote="规格：规格深案 §DP-5；判据书：",
                tracked=False,
            ),
            DocRef(
                path="runs/df6_dp5cascade/criteria.md",
                quote="runs/df6_dp5cascade/criteria.md（回收钉锚值与来源）。",
                tracked=False,
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
    if f"rfauto.core.{stem}" in text:
        return True
    pat = rf"from rfauto\.core import [^\n]*\b{stem}\b"
    return re.search(pat, text) is not None


def referencing_tests(stem: str) -> list[tuple[str, int]]:
    """tests/unit 下引用本模块的测试文件（排序）+ def test_ 计数。"""
    out: list[tuple[str, int]] = []
    for path in sorted(TESTS_UNIT_DIR.glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        if _references_module(text, stem):
            out.append((path.name, len(re.findall(r"def (test_\w+)", text))))
    return out


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
        f"| 主模块 | `src/rfauto/core/{main_mod}.py`（`rfauto.core.{main_mod}`） |",
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
            exist_note = "" if ref.tracked else "（runs/ 证据面，gitignored，存在性不作测试断言）"
            lines.append(f"- `{ref.path}`{exist_note}——引文：\"{_md_text(ref.quote)}\"")
        lines.append("")
    all_tests: list[tuple[str, int]] = []
    for mod_stem in spec.modules:
        for name, count in referencing_tests(mod_stem):
            if (name, count) not in all_tests:
                all_tests.append((name, count))
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
    parser = argparse.ArgumentParser(description="XA-8 内核域文档卡生成器（首批 5 张）")
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
