#!/usr/bin/env python3
"""XA-8 内核域文档卡生成器（round18 规格 XA-8 首批 5 张 + aurora_e W3-S13
知识面批扩容批一 11 张 + aurora_e W4-S19 知识面批扩容批二 8 张 + aurora_f
W1-S3 内核前置批 2 张 + aurora_f W3-S11 前置批收官 1 张 + aurora_f W6-S22
内核卡扩面批 9 张 + aurora_g W1-S3 内核卡批三 9 张 + aurora_g W2-S3 内核卡
批四 9 张 + aurora_g W3-S3 内核卡批五 6 张 + aurora_g W6-S4 内核卡
批六 6 张 + aurora_g W8-S1 内核卡批七 3 张 + aurora_g W12-S2 内核卡
终批 5 张（gnss_geometry/radar_clutter/microstrip_disc/open_wire_line/
wg_cavity_bpf；同笔 fmcw_radar 卡扩至全族 4 键），共 74 张）。

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
  coupled_line_bpf（calc_families 注册计算器三族）。
- aurora_f W1-S3 内核前置批 2 卡（2026-10-18）：lange（R2 §⑤ F1——core
  提升式重构解锁）/stepped_impedance（R2 §⑤ F2——综合两键解锁），
  批一 docstring 所记两族「无专属综合内核」留缺理由就此关闭；ring_resonator
  留缺已由 W3-S11 前置批收官关闭（R2 §⑤ F3——render_ring 设计链提升
  + 间隙耦合 Qe 设计式 + 模阶谱/Q 分解/基模频响两键，2026-10-18）。
- aurora_f W6-S22 内核卡扩面批 9 卡（2026-10-18）：照 cascade/rwg_mmt/
  ring_resonator 纯 CALC 键族卡先例——mixer_conversion/ruthroff_balun/
  gd_equalizer/measurement_drift/agc_loop/cal_kit_verify/six_port/
  iss_on_wafer/source_power_cal（数据源完备性盘点 9/9 全出：注册键+模块
  docstring「物理口径/出处」节+锚树测试面 needles 三面齐备；anchors.yaml/
  formula_provenance.yaml 零命中如实渲染「0 条」诚实支路，同 ring_resonator
  先例）。
- aurora_g W1-S3 内核卡批三 9 卡（2026-10-19，R2_core_tier4 §⑤ 余量表 A 组
  READY 7 族+CALC-only 2 族）：combline/cps/interdigital/siw/slot/stripline/
  suspended_stripline/dipole/helix——照 W6-S22 纯 CALC 键族卡先例；rf_line
  三线（cps/stripline/suspended_stripline）与 slotline_siw siw 半族为 C 组
  兄弟卡部分覆盖的剩余键面（slotline 半族已由既有 slotline 卡覆盖，防重复
  出卡）；9 族 docstring 出处句全部在源（零补写）。
- aurora_g W2-S3 内核卡批四 9 卡（2026-10-19，R2_core_tier4 §④ 卡批 A 全量
  （directional_bridge/rf_switch/kuroda_identities/pll_lock_time/
  multisection_coupler——aurora_f 新增 16 族漏卡五族）+W1-S2 新核 2 族
  （link_limits/fec_codes——R2 §③ C1/C2 落地族）+A 组 2 族（itu_link/link
  ——注册薄壳+纯函数内核双模块卡）：注册键+docstring「物理口径/出处」节
  引文钉+锚树测试面 needles 三面齐备；102 条引文经预验探针
  内部证据档 一次全命中（零补写）；anchors/KD-1
  零命中如实渲染同 W6-S22 先例。
- aurora_g W3-S3 内核卡批五 6 卡（2026-10-19，R2_core_tier4 §③ 新核
  三族 C3/C4/C6 落地族 dgs/if_digitizer/wg_dielectric_window + §④ 卡批 C
  波导族三卡 waveguide_closed_form/waveguide_iris/hybrid_junction）：照
  W2-S3 纯 CALC 键族卡先例——注册键+docstring「物理口径/出处」节引文钉
  +锚树测试面 needles 三面齐备；68 条引文经预验探针
  内部证据档 一次全命中（零补写）；anchors/KD-1
  零命中如实渲染同 W6-S22 先例。
- aurora_g W6-S4 内核卡批六 6 卡（2026-10-19，R2_core_tier4 §④ 卡批 E
  头两族 radar_eq/modulation_ber + 卡批 D 头一族 coax_line + W4-S4 内核
  余量三族 analog_modulation/si_ctle/propagation）：照 W2-S3/W3-S3 纯
  CALC 键族卡先例——注册键+docstring「物理口径/出处」节引文钉+锚树测试
  面 needles 三面齐备；71 条引文经预验探针 内部证据档
  .py 一次全命中（零补写）、19 CALC 键数值抽查 内部证据档
  w6s4_numeric_probe.py docstring 锦点全 PASS；propagation=注册薄壳+纯
  函数内核双模块卡（同 itu_link 先例）；anchors 零命中/KD-1 按
  formula_provenance 实测渲染（coax_line/analog_modulation 各 1 条、
  propagation 薄壳 0 条、余 0 条）如实。

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
                path="内部证据档",
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
                quote="判据预声明 = 内部证据档（先写后跑，#122）。",
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
                    "±10%（延续计划 §10.15 预声明）。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="内部证据档",
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
                quote="内部证据档（回收钉锚值与来源）。",
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
                quote="在真实结构里是 18Ω，|S11| 卡 −6.5dB）。共形映射闭式见",
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
            DocRef(path="src/rfauto/core/calculators.py", quote="在真实结构里是 18Ω，|S11| 卡 −6.5dB）。共形映射闭式见",
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
            DocRef(path="tests/unit/test_w4_b_p3_slotline_wide.py", quote="权威口径（铁律 1c：常数逐个有出处、分段声明有效范围、超范围显式报错不外推）",
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
            DocRef(path="runs/hairpin_kgap/offline_kj_vs_ngsolve.json", quote="偶/奇模 k_NG/k_KJ=1.003/1.018/1.049 @gap 0.8/1.1328/1.6，内部证据档",
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
    # ─── aurora_f W1-S3 内核前置批（2026-10-18，R2_core_tier3 §⑤ F1/F2
    # 设计案；lange/stepped_impedance 批一留缺理由就此关闭）──────────────────
    CardSpec(
        kernel_id="lange",
        tagline=(
            "Lange 电桥专属综合内核：C(dB)→相邻对 (Z0e,Z0o) 四指设计式→四线"
            "等效 (Ze4,Zo4)→KJ 二维反解 (w,s)→指长 λ/4——render_c4 全链的"
            "提升式重构单一事实源（字节级对拍钉），附四线等效偶/奇模频响裁判。"
        ),
        modules=("calc_families/lange",),
        primary_entries=(
            ("calc_families/lange", "lange_synthesize"),
            ("calc_families/lange", "lange_response"),
            ("calc_families/lange", "lange_design"),
            ("calc_families/lange", "lange_pair_zee_zoo"),
            ("calc_families/lange", "lange_equivalent_zee_zoo"),
        ),
        test_face_needles=("lange_synthesize", "lange_response"),
        formulas=(
            Formula(
                title="四指设计式（Pozar §7.6 Lange 节）",
                latex=(
                    "Z_{0e}=\\frac{Z_0(4C-3+\\sqrt{9-8C^2})}{2C"
                    "\\sqrt{\\frac{1-C}{1+C}}},\\quad "
                    "Z_{0o}=\\frac{Z_0(4C+3-\\sqrt{9-8C^2})}{2C"
                    "\\sqrt{\\frac{1+C}{1-C}}}"
                ),
                quote="Z0e=Z0(4C−3+√(9−8C²))/(2C√((1−C)/(1+C)))、",
                quote2="Z0o=Z0(4C+3−√(9−8C²))/(2C√((1+C)/(1−C)))，须 8C²<9",
                cite=(
                    "模块 docstring「物理口径」节（原始 J. Lange IEEE-MTT "
                    "1969 二级转引；C=10^(−C_dB/20)）"
                ),
            ),
            Formula(
                title="四线等效两线（Pozar §7.6）",
                latex=(
                    "Z_{e4}=\\frac{Z_{0e}(Z_{0o}+Z_{0e})}{3Z_{0o}+Z_{0e}},"
                    "\\quad Z_{o4}=\\frac{Z_{0o}(Z_{0o}+Z_{0e})}{3Z_{0e}+Z_{0o}},"
                    "\\quad C=\\frac{Z_{e4}-Z_{o4}}{Z_{e4}+Z_{o4}},\\quad "
                    "Z_0=\\sqrt{Z_{e4}Z_{o4}}"
                ),
                quote="Ze4=Z0e(Z0o+Z0e)/(3Z0o+Z0e)、Zo4=Z0o(Z0o+Z0e)/(3Z0e+Z0o)；",
                quote2="耦合 C=(Ze4−Zo4)/(Ze4+Zo4)、Z0=√(Ze4·Zo4)",
                cite=(
                    "模块 docstring（回代自证逐位闭合；3dB 闭合链 "
                    "(176.216,52.609)→(120.71,20.71)Ω 教科书锚在测试侧）"
                ),
            ),
            Formula(
                title="几何链（KJ 二维反解+HJ 精算）",
                latex=(
                    "(w,s)=f^{-1}_{\\mathrm{KJ}}(Z_{0e},Z_{0o}),\\quad "
                    "L_{\\mathrm{finger}}=\\frac{c}{4f_0\\sqrt{"
                    "\\tfrac{\\varepsilon_{e}+\\varepsilon_{o}}{2}}}"
                ),
                quote="→ 指长 λ/4 @ (εeff_e+εeff_o)/2；馈线宽 inverse_width（skrf HJ，",
                cite=(
                    "模块 docstring「几何链」行（(w,s) 走 "
                    "core/coupled_microstrip.coupled_bpf_width_gap_from_zee_zoo"
                    "——本席同批提升；铁律 1c 唯一线宽口径）"
                ),
            ),
            Formula(
                title="频响（四线等效偶/奇模叠加裁判）",
                latex=(
                    "S^{(4\\square)}=\\tfrac{1}{2}(S^{e}+S^{o}),\\quad "
                    "\\theta_{e/o}=k_0L\\sqrt{\\varepsilon_{e/o}}"
                ),
                quote="偶/奇模各自 2 端口线 S 叠加构造 4 端口（(Se+So)/2 口径——与",
                cite=(
                    "模块 docstring「频响键」行（与 adapters._coupled_section_s4 "
                    "同构造异路线，测试互证 ≤1e-12 #118）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="非相邻指耦合忽略（一阶 Lange 设计口径）**如实登记。",
                note=(
                    "一阶设计口径：非相邻指耦合与桥缝耦合寄生于理想裁判之外"
                    "（render_c4 §C4 口径 3 同源）。"
                ),
            ),
            Boundary(
                quote="相邻对 KJ εeff_e/εeff_o 不是四线等效模相速（多导体模式，Ou 1975）——拿来",
                note=(
                    "同步 TEM 档（缺省）取平均 εeff 给理想裁判；真非同步相速"
                    "属多导体模式问题，不做修正即如实声明（ Ou 1975 口径）。"
                ),
            ),
            Boundary(
                quote="h=0.508 反解 s=0.0386mm → g=s/h=0.076 略低于 KJ 标称有效域下限 0.1",
                note=(
                    "KJ 有效域提示（g=s/h 下限 0.1）：3dB 设计于本叠层略出域，"
                    "如实记录不拦截。"
                ),
            ),
            Boundary(
                quote="函数体自 render_c4 原样下沉（逐字节未动），render_c4 改为",
                note=(
                    "提升式重构单一事实源：adapters/render_c4 与 "
                    "openems_templates 的同名入口=core 同一函数对象（字节级"
                    "对拍钉，基线 runs/aurora_f/）。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w1s3_lange_stepped.py",
                quote="runs/aurora_f/w1s3_lange_parity_baseline.json",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="stepped_impedance",
        tagline=(
            "阶梯阻抗低通滤波器综合：原型 g_k 阶梯→感性高阻/容性低阻短线电长"
            "（fc 等电抗 arctan 设计式）→HJ 逐段线宽/εeff 精算——模板名义值"
            "手设留缺的补口，附 ABCD 级联频响与 fc−3dB 回收。"
        ),
        modules=("calc_families/stepped_impedance",),
        primary_entries=(
            ("calc_families/stepped_impedance",
             "stepped_impedance_lpf_synthesize"),
            ("calc_families/stepped_impedance", "stepped_impedance_response"),
        ),
        test_face_needles=("stepped_impedance_lpf_synthesize",
                           "stepped_impedance_response"),
        formulas=(
            Formula(
                title="原型 g 值（双源：精确闭式 + 同仓表单源）",
                latex=(
                    "g_k=2\\sin\\frac{(2k-1)\\pi}{2N}"
                    "\\ (\\text{binomial}),\\qquad "
                    "g^{\\mathrm{Cheb}}_k=\\text{MYJ Table 4.05-1}"
                ),
                quote="binomial（最平坦）：g_k = 2·sin((2k−1)π/(2N))（精确闭式，Pozar 4th ed.",
                quote2="chebyshev（等纹波）：**单源复用** core/synthesis.chebyshev_lpf_g_values",
                cite=(
                    "模块 docstring「原型 g 值」行（chebyshev 透传同仓 MYJ 表，"
                    "本面零公式复制 #116；N≤4 奇数=表域+等端接约束）"
                ),
            ),
            Formula(
                title="阶梯实现（Pozar §8.3 fc 等电抗设计式）",
                latex=(
                    "\\theta_L=\\arctan\\frac{g_k Z_0}{Z_{\\mathrm{high}}},"
                    "\\qquad "
                    "\\theta_C=\\arctan\\frac{g_k Z_{\\mathrm{low}}}{Z_0}"
                ),
                quote="Z_high·tanθ_L = g_k·Z0 → θ_L = arctan(g_k·Z0/Z_high)；并联电容（偶位）",
                quote2="tanθ_C = g_k·Z_low/Z0 → θ_C = arctan(g_k·Z_low/Z0)。",
                cite=(
                    "模块 docstring「阶梯实现」行（Pozar Example 8.2 设计式"
                    "口径：N=5 最平坦、fc=2GHz、50Ω、150/10Ω——印刷值未回"
                    "原文不硬钉，闭式直算锚在测试侧 #122）"
                ),
            ),
            Formula(
                title="物理长（各段自身 εeff 独立精算）",
                latex="l_i=\\frac{\\theta_i\\,c}{2\\pi f_c"
                      "\\sqrt{\\varepsilon_{\\mathrm{eff},i}}}",
                quote="l_i = θ_i·λ_g,i/(2π) = θ_i·c/(2π·fc·√εeff_i)，εeff_i 取该段",
                cite=(
                    "模块 docstring「物理长」行（skrf HJ 唯一介质口径，铁律 "
                    "1c；XA-3 迭代序同款——各段按自身线宽 εeff 独立精算）"
                ),
            ),
            Formula(
                title="响应（ABCD 级联+fc−3dB 回收）",
                latex="|S_{11}|^2+|S_{21}|^2=1,\\quad "
                      "f_{c,3\\mathrm{dB}}=\\text{首次穿越}(-3\\mathrm{dB})"
                      "\\text{线性插值}",
                quote="无耗互易由构造保证（|S11|²+|S21|²=1 残差随值报告）。fc−3dB=自低频段",
                cite=(
                    "模块 docstring「响应键」行（离散段化固有偏差如实并列："
                    "实测 +6.1%@阻抗比 15、随比单调收敛）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="等端接约束：chebyshev 偶数节原型 g_{N+1}≠1（不等端接），与两端口等",
                note=(
                    "chebyshev 偶数节与等 Z0 端接实现语义冲突——显式拒绝"
                    "（binomial 任意 N 放行，g_{N+1}=1 恒成立）。"
                ),
            ),
            Boundary(
                quote="阶梯近似精度随 Z_high/Z_low 比值增大而改善（段长趋短），βL > π/4 时",
                note=(
                    "阶梯近似是 Z_high/Z_low→∞ 的渐近等价——βL>π/4 劣化如实"
                    "记 note 不拦截；带内 vs 集总梯偏差随比单调收敛（实测锚）。"
                ),
            ),
            Boundary(
                quote="fc−3dB=自低频段\n  首次穿越 −3dB 的插值回收；离散段化固有偏差（arctan 等电抗近似+色散）",
                note=(
                    "fc 回收偏差是离散段化固有量：+15%/+6.1%/+1.7%/+0.4% "
                    "@阻抗比 5/15/60/240（本席实测，如实并列不冒充精确）。"
                ),
            ),
            Boundary(
                quote="lc_filter/mask_filter=集总/规格级、synthesize_commensurate_line（core/",
                note=(
                    "族界：lc/mask=集总与规格级、matching.synthesize_"
                    "commensurate_line=Richards 全 λ/4 变换（同名阶梯异域）、"
                    "stepped_impedance 模板=实现级渲染通道——本族=综合两键。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w1s3_lange_stepped.py",
                quote="口径参照：N=5 最平坦、fc=2GHz、50Ω、Z_high=150Ω、",
                tracked=True,
            ),
        ),
    ),
    # ─── aurora_f W3-S11 前置批收官（2026-10-18，R2_core_tier3 §⑤ F3
    # 设计案；build_kernel_cards 批一 docstring 所记 ring_resonator 留缺
    # 就此关闭，前置三族全部出卡）────────────────────────────────────────
    CardSpec(
        kernel_id="ring_resonator",
        tagline=(
            "微带环形谐振器专属综合内核：目标基模 f1→HJ εeff→环平均半径"
            " r_mean=c/(2π·f1·√εeff)（闭环周长=λg 恒等式——render_ring 设计"
            "链的提升式重构单一事实源，字节级对拍钉），附间隙耦合 Qe 设计式"
            "（串联隙=J-反相器）与模阶谱/Q 分解/基模频响两键。"
        ),
        modules=("calc_families/ring_resonator",),
        primary_entries=(
            ("calc_families/ring_resonator", "ring_resonator_synthesize"),
            ("calc_families/ring_resonator", "ring_resonator_response"),
            ("calc_families/ring_resonator", "ring_resonator_design_params"),
        ),
        test_face_needles=("ring_resonator_synthesize",
                           "ring_resonator_response"),
        formulas=(
            Formula(
                title="谐振恒等式（综合正向，render_ring 链逐字节提升）",
                latex="r_{\\mathrm{mean}}=\\frac{c}{2\\pi f_1"
                      "\\sqrt{\\varepsilon_{\\mathrm{eff}}(f_1)}}",
                quote="r_mean = c/(2π·f1·√εeff(f1))，εeff 取微带 HJ 正向（core/synthesis.",
                cite=(
                    "模块 docstring「谐振恒等式」节（闭环周长=λg；基线 "
                    "runs/aurora_f/w3s11_ring_parity_baseline.json 字节对拍钉；"
                    "反方向=core/dielectric_extract.ring_resonator_f0_to_er "
                    "同仓双源，回收带 −0.52% 如实）"
                ),
            ),
            Formula(
                title="间隙耦合 Qe 设计式（串联隙=J-反相器）",
                latex="J=\\omega_0 C_g,\\quad x=JZ_0,\\quad "
                      "Q_e=\\tfrac{\\pi}{2}\\frac{Z_0/Z_r}{x^2}",
                quote="② 串联隙 = J-反相器：J = ω0·C_g（MYJ §8.5/Pozar §8.6 小隙口径）。",
                quote2="Q_e = (π/2)·(Z0/Z_r)/x²，x = J·Z0（与",
                cite=(
                    "模块 docstring「间隙耦合 Qe 设计式」节（与 "
                    "coupled_line_bpf 同式同仓双源；qe_target 反解隙宽 "
                    "brentq 回代闭环）"
                ),
            ),
            Formula(
                title="模阶谱（逐模不动点，HJ 弱色散）",
                latex="f_n=\\frac{n\\,c}{2\\pi r_{\\mathrm{mean}}"
                      "\\sqrt{\\varepsilon_{\\mathrm{eff}}(f_n)}}",
                quote="f_n = n·c/(2π·r_mean·√εeff(f_n))（逐模不动点",
                cite=(
                    "模块 docstring「模阶谱」节（基模 n=1 与综合恒等式同式"
                    "构造位精确；HJ 弱色散偏差 n=2/3 实测 +0.073%/+0.115% "
                    "随档如实）"
                ),
            ),
            Formula(
                title="频响与谐振峰（Q 分解+ABCD 双路线）",
                latex="\\frac{1}{Q_L}=\\frac{1}{Q_d}+\\frac{1}{Q_c}"
                      "+\\frac{1}{Q_r},\\quad "
                      "S_{21,\\mathrm{pk}}=\\frac{1}{1+Q_e/(2Q_0)}",
                quote="S21pk = 1/(1+Qe/(2Q0))（对 ABCD 网络",
                quote2="Q_L = 1/(1/Q0 + 2/Qe)。频轴按基模（n=1）档评估（理想裁判口径，",
                cite=(
                    "模块 docstring「Q 分解」「频响」节（Q_d 填充因子式/"
                    "Q_c Wheeler 增量电感规则经 forward_z0 数值导数；闭式与"
                    "网络数值逐位闭合 #118 双路线）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="系数 1 量纲估计档，UNVERIFIED 如实",
                note=(
                    "隙电容 C_g=ε0·εh·w²/g 为 R2 F3 设计案预授权的简化电容"
                    "模型档：单调性/极限行为正确、系数非场解精度——Garg-Bahl"
                    " 拟合与共形场解无仓内验证出处不入面（禁凭记忆写常数），"
                    "实测注入走 c_gap_ff/qe_per_port 覆盖档。"
                ),
            ),
            Boundary(
                quote="εeff 未含曲率/色散修正（v1）。",
                note=(
                    "近似级别与 render_ring 段头注同源：v1 闭式未含曲率/"
                    "色散修正，精度由 G2 闭环+HFSS 仲裁另批兑现。"
                ),
            ),
            Boundary(
                quote="多模复合响应与隙电容加载失谐",
                note=(
                    "频响=基模档理想裁判（coupled_line_bpf Qe 面同族窄带"
                    "理想化）：线环网络实测隙加载失谐名义点 −1.6%（"
                    "dielectric_extract P1「开路耦合隙相位移出」同族声明），"
                    "模点走 modes 表。"
                ),
            ),
            Boundary(
                quote="Q_r（辐射/表面波残差）v1 不建模记零贡献",
                note=(
                    "Q 分解 v1 面：Q_d 填充因子式、Q_c Wheeler 光滑壁档"
                    "（粗糙度修正不做）、Q_r 记零——实测注入走 qe_per_port "
                    "覆盖档。"
                ),
            ),
            Boundary(
                quote="coaxial_cavity=腔谐振、cavity_unloaded_q=腔 Q 面——本族只做",
                note=(
                    "族界：ratrace=环行功分器拓扑、dielectric_extract=提取"
                    "反方向面（同仓双源互证不重复）、combline_resonator/"
                    "coaxial_cavity/cavity_unloaded_q=腔谐振面——本族=传输"
                    "型环形谐振器综合两键。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w3s11_ring.py",
                quote="runs/aurora_f/w3s11_ring_parity_baseline.json",
                tracked=True,
            ),
        ),
    ),
    # ─── aurora_f W6-S22 内核卡扩面批（9 张；照 cascade/rwg_mmt/ring_resonator
    # 纯 CALC 键族卡先例——数据源完备性盘点 9/9 全出：注册键+docstring「物理
    # 口径/出处」节+锚树测试面 needles 三面齐备；anchors/KD-1 零命中如实渲染）──
    CardSpec(
        kernel_id="mixer_conversion",
        tagline=(
            "混频器变换面：镜像噪声折入 SSB-NF 精确恒等式、变频损耗 SSB/DSB "
            "口径换算与无源混频噪声地板、镜像频率规划与 IQ 失衡 IRR 同式复算"
            "——级联噪声预算上游的变换记账内核。"
        ),
        modules=("calc_families/mixer_conversion",),
        primary_entries=(
            ("calc_families/mixer_conversion", "mixer_ssb_nf"),
            ("calc_families/mixer_conversion", "mixer_conversion_loss"),
            ("calc_families/mixer_conversion", "mixer_image_plan"),
        ),
        test_face_needles=("mixer_ssb_nf", "mixer_conversion_loss",
                           "mixer_image_plan"),
        formulas=(
            Formula(
                title="镜像噪声折入精确恒等式（消元闭式）",
                latex=(
                    "F_{\\mathrm{SSB}}=(1+g\\,t)\\,F_{\\mathrm{DSB}},\\quad "
                    "g=10^{-IR/10},\\ t=T_{\\mathrm{im}}/T_0"
                ),
                quote="**F_SSB = (1 + g·t)·F_DSB**",
                quote2="**NF_SSB = NF_DSB + 3.0103 dB** 教科书 3dB 折入极限",
                cite=(
                    "模块 docstring「镜像噪声折入（image noise fold）」节"
                    "（两式消 N_int 与 F_m；t=1 档对混频器噪声分配无假设依赖；"
                    "Pozar Ch.12 口径，出处节在档）"
                ),
            ),
            Formula(
                title="变频损耗 SSB/DSB 等分恒等式",
                latex="CL_{\\mathrm{DSB}}=CL_{\\mathrm{SSB}}-3.0103\\,"
                      "\\mathrm{dB}",
                quote="（CL_DSB = CL_SSB − 3.0103 dB，等分恒等式）",
                cite="模块 docstring「变频损耗 SSB/DSB 口径」行（DSB 两带都载信号 → 增益 +3.0103 dB）",
            ),
            Formula(
                title="无源混频噪声地板（衰减器同构）",
                latex=(
                    "F_{\\mathrm{DSB}}=\\tfrac{CL_{\\mathrm{lin}}}{2},"
                    "\\quad F_{\\mathrm{SSB}}=CL_{\\mathrm{lin}},\\quad "
                    "NF_{\\mathrm{SSB}}^{\\mathrm{ideal\\,passive}}"
                    "=CL_{\\mathrm{SSB}}"
                ),
                quote="F_DSB=CL_lin/2、",
                quote2="即 **NF_SSB(理想无源) = CL_SSB**（与 mixer_ssb_nf 键",
                cite=(
                    "模块 docstring「无源混频噪声地板」节（与 mixer_ssb_nf 键"
                    "跨键双源互证：F_SSB=2·(CL_lin/2)=CL_lin）"
                ),
            ),
            Formula(
                title="镜像规划与 IQ 失衡 IRR",
                latex=(
                    "f_{im}^{\\mathrm{low}}=f_{LO}-f_{IF},\\ "
                    "f_{im}^{\\mathrm{high}}=f_{LO}+f_{IF},\\ "
                    "|f_{im}-f_{RF}|=2f_{IF};\\quad "
                    "\\mathrm{IRR}=\\frac{1+\\varepsilon^2+2\\varepsilon"
                    "\\cos\\varphi}{1+\\varepsilon^2-2\\varepsilon"
                    "\\cos\\varphi}"
                ),
                quote="镜像距信号 **2·f_IF**（预选滤波器设计依据）",
                quote2="Razavi 式 IRR=(1+ε²+2εcosφ)/(1+ε²−2εcosφ)",
                cite=(
                    "模块 docstring「镜像规划」「IQ 失衡→IRR」行（IRR 与 "
                    "rx_impairments 同式独立复算，#118 同仓双源）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="t≠1 时本键按镜像支路与信号支路",
                note=(
                    "t≠1 档的等噪声贡献假设如实注记（t=1 档消元精确不受影响）"
                    "——实际器件以手册 SSB 实测为准。"
                ),
            ),
            Boundary(
                quote="真实有源/二极管混频器的 NF 高于该地板",
                note=(
                    "无源地板是下界参考——超出量=器件质量指标（手册如实），"
                    "不冒充典型值。"
                ),
            ),
            Boundary(
                quote="本族只做**变换损耗+镜像噪声记账+镜像几何规划**",
                note=(
                    "族界：cascade 杂散面（m·f_RF±n·f_LO 乘积域）与 "
                    "BlockSpec.conversion_loss_db=模型层参数槽；IRR 消费面归 "
                    "rx_impairments（同式独立复算互证不重写）。"
                ),
            ),
            Boundary(
                quote="越界一律显式 ValueError",
                note=(
                    "守卫面：nf/损耗有限非负、IR≥0（None=完美镜像抑制）、"
                    "t∈[0,1]、f_RF≠f_LO（零中频镜像=信号本身显式拒绝）。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w2s6_mixer_bridge_switch.py",
                quote="aurora_f W2-S6 席域，R2_core_tier3 §③ D2 立项",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="ruthroff_balun",
        tagline=(
            "Ruthroff 直通+延迟求和传输线巴伦：单磁芯 n²:1 阻抗比设计（每线"
            "最优 Z0=√(r_in·r_out) 一阶带宽定理、电短线设计口径=匹配带缘 "
            "|S11|≤0.1 判据）与 4 端子差分导纳精确解（W7-S25 P1-1 物理"
            "修正体）——guanella_tlt 拒绝注记指向的等延迟族缺口补全。"
        ),
        modules=("calc_families/ruthroff_balun",),
        primary_entries=(
            ("calc_families/ruthroff_balun", "ruthroff_balun_design"),
            ("calc_families/ruthroff_balun", "ruthroff_balun_response"),
        ),
        test_face_needles=("ruthroff_balun_design", "ruthroff_balun_response"),
        formulas=(
            Formula(
                title="Z_in 闭式与低电长区匹配（Ranzani 式(3) 锚）",
                latex=(
                    "Z_{in}(\\theta)=Z_0\\,"
                    "\\frac{2\\rho(1+\\cos\\theta)+j\\sin\\theta}"
                    "{\\cos\\theta+j\\rho\\sin\\theta},\\ "
                    "\\rho=\\tfrac{R_{out}}{Z_0};\\quad "
                    "Z_{in}(\\theta\\to 0)=4R_{out}"
                ),
                quote="Z_in(θ) = Z0·[2ρ(1+cosθ) + j·sinθ]/[cosθ + jρ·sinθ]（高阻口视入阻抗",
                quote2="低电长匹配锚：θ→0 处 Z_in→4R_out=R_in（Ranzani 式(3) 低频极限",
                cite=(
                    "模块 docstring「闭式恒等式」节（W7-S25 P1-1 修正后重"
                    "导；等价半角形式 (4R_out+2jZ0·tan(θ/2))/(1−tan²(θ/2)"
                    "+2jρ·tan(θ/2))；θ=π 处 Z_in→0 传输零点）"
                ),
            ),
            Formula(
                title="变换增益闭式与 θ=π 传输零点",
                latex=(
                    "G(\\theta)=\\frac{16\\rho^2(1+\\cos\\theta)^2}"
                    "{(1+4\\rho^2)^2\\sin^2\\theta+4\\rho^2(1+3\\cos\\theta)^2},"
                    "\\quad G\\to 1\\ (\\theta\\to 0),\\ "
                    "G\\to 0\\ (\\theta\\to\\pi)"
                ),
                quote="G(θ)=|S21|² = 16ρ²(1+cosθ)²/[(1+4ρ²)²·sin²θ+4ρ²(1+3cosθ)²]；",
                quote2="θ=π 传输零点：Z_in→0、G→0（NIST 文",
                cite=(
                    "模块 docstring「闭式恒等式」节（θ=π 零点=NIST Ranzani "
                    "2012 \"the transformation ratio goes to zero\" 实证口"
                    "径；G 关于 θ 单调下降——旧 θ↔π−θ 单峰对称系错误模型"
                    "产物已废）"
                ),
            ),
            Formula(
                title="最优 Z0 一阶带宽定理与匹配带缘判据（设计口径）",
                latex=(
                    "Z_0=\\sqrt{R_{in}R_{out}}=2R_{out}\\ (4{:}1),\\quad "
                    "Z_{in}\\approx 4R_{out}+R_{out}\\theta^2"
                    "+jZ_0\\theta(1-4\\rho^2);\\quad "
                    "|S_{11}|^2=\\frac{(1-\\cos\\theta)^2}"
                    "{(1+3\\cos\\theta)^2+4\\sin^2\\theta}"
                ),
                quote="最优 Z0=√(R_in·R_out)=2R_out（ρ=1/2）**一阶带宽定理**：小电长展开",
                quote2="ρ=1/2 档 |S11|² = (1−cosθ)²/[(1+3cosθ)² + 4sin²θ]；",
                cite=(
                    "模块 docstring「闭式恒等式」「设计口径」节（ρ=1/2 唯"
                    "一消去 O(θ) 虚部=匹配带一阶最优；带缘判据 |S11|≤0.1 "
                    "精确二次根 (1−5γ²)u²+16γ²u−16γ²=0 → θ_bd≈48.30° 定 "
                    "l_max；θ=90° 非匹配反向锚 |S11|=√0.2——旧「λ/4 匹配"
                    "点」口径已弃用）"
                ),
            ),
            Formula(
                title="4 端子差分盖章与不等参考标度（W7-S25 修正体）",
                latex=(
                    "Y_{self}=-j\\cot\\theta/Z_0,\\ "
                    "Y_{mut}=j\\csc\\theta/Z_0;\\quad "
                    "\\mathbf Y_{2p}=\\begin{bmatrix}Y_s&Y_m-Y_s\\\\"
                    "Y_m-Y_s&2(Y_s-Y_m)\\end{bmatrix};\\quad "
                    "\\mathbf S=(\\mathbf I-\\mathbf DY\\mathbf D)"
                    "(\\mathbf I+\\mathbf DY\\mathbf D)^{-1}"
                ),
                quote="Y₂ₚ=[[Ys, Ym−Ys],[Ym−Ys, 2(Ys−Ym)]]，",
                quote2="S=(I−D·Y·D)(I+D·Y·D)⁻¹、D=diag(√R_in,√R_out)（guanella",
                cite=(
                    "模块 docstring「盖章」节（Yd=Ys−Ym=−j·cot(θ/2)/Z0 半"
                    "角项=互耦机构本体；旧 [[Ys,Ym],[Ym,2Ys]] 无互耦已废；"
                    "锚树 KCL/congruence 真双路线互证）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="低频磁化电感拐角依赖磁芯 L_m 数据，本族**不冒充**",
                note=(
                    "纯差分 TL 模型在模型内低频保持 4:1（θ→0 精确匹配，"
                    "Ranzani 式(3)）；真实器件低频拐角由有限磁化电感承载"
                    "——无磁芯数据不虚构频响（UNVERIFIED 如实登记）。"
                ),
            ),
            Boundary(
                quote="≥16:1 复合拓扑无权威",
                note=(
                    "9:1=四线双对 NIST 扩展口径（设计键 n∈{2,3}）；频响键 "
                    "n=2 单对精确解——9:1 双对复合不在解析口径如实拒绝。"
                ),
            ),
            Boundary(
                quote="**Ruthroff 等延迟族**（单磁芯单线对，输出电压=直通电压+延迟电压相量和",
                note=(
                    "族界：guanella_tlt=等比族（比值随线数 n² 增长）、"
                    "Marchand=模板级双槽臂、quarter_wave/taper=单线匹配、"
                    "t_match/rf_match=集总——均非直通+延迟求和拓扑不并入。"
                ),
            ),
            Boundary(
                quote="线 Y 参量奇异显式拒绝（扫频域避开）",
                note=(
                    "θ=kπ（含 f→0）线 Y 参量 cscθ 奇异显式拒绝；数值 0.0 "
                    "合法（判缺失 is not None，#364④）。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w2s7_ruthroff_gd_drift.py",
                quote="tests/unit/test_w2s7_ruthroff_gd_drift.py",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="gd_equalizer",
        tagline=(
            "群时延均衡器综合面：一阶/二阶全通节零极点镜像构造与级联逐频响应"
            "——由目标时延构造传输零极点的纯综合内核（信道提取面的反向消费方）。"
        ),
        modules=("calc_families/gd_equalizer",),
        primary_entries=(
            ("calc_families/gd_equalizer", "gd_allpass_section_synthesize"),
            ("calc_families/gd_equalizer",
             "gd_equalizer_cascade_response"),
        ),
        test_face_needles=("gd_allpass_section_synthesize",
                           "gd_equalizer_cascade_response"),
        formulas=(
            Formula(
                title="一阶全通节（零极点镜像构造）",
                latex="H(s)=\\frac{s-a}{s+a},\\ "
                      "\\tau_g(\\omega)=\\frac{2a}{a^2+\\omega^2},\\ "
                      "\\tau_{dc}=\\frac{2}{a},\\ |H|\\equiv 1",
                quote="H(s)=(s−a)/(s+a)（a>0：极点 −a、零点 +a=极点关于原",
                quote2="τ_g(ω)=2a/(a²+ω²)；直流时延 τ_dc=2/a",
                cite="模块 docstring「一阶全通节」行（τ_dc 参数化 a=2/τ_dc；|H|≡1 全通定义恒等式）",
            ),
            Formula(
                title="二阶全通节（双参数化）",
                latex="\\tau_{pk}=\\tau_g(\\omega_0)=\\frac{4Q}"
                      "{\\omega_0},\\quad \\tau_{dc}=\\frac{2}{Q\\omega_0}",
                quote="τ_pk=τ_g(ω0)=4Q/ω0；直流时延 τ_dc=2/(Qω0)",
                cite=(
                    "模块 docstring「二阶全通节」行（f0×Q 或 f0×τ_peak 双档"
                    "恰给其一，τ_peak 档 Q=τ_pk·ω0/4）"
                ),
            ),
            Formula(
                title="级联可加性与相位总旋转恒等式",
                latex="H=\\prod_i H_i,\\ \\tau_g=\\sum_i \\tau_{g,i},\\ "
                      "|S_{21}|\\equiv 1;\\quad "
                      "\\int_0^{\\infty}\\tau_g\\,d\\omega="
                      "\\varphi(0)-\\varphi(\\infty)=\\mathrm{order}\\,\\pi",
                quote="∫₀^∞ τ_g dω = φ(0)−φ(∞) = order·π（一阶 π/二阶 2π——相位总旋转量恒",
                quote2="级联时延可加性",
                cite=(
                    "模块 docstring「级联」「群时延曲线积分语义」行（任务书锚；"
                    "测试侧数值积分钉+零极点镜像逐位 0 残差）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="本族只到**传输零极点/频响层**",
                note=(
                    "Cauer 桥 T 集总实现元件值依赖终端阻抗与实现拓扑——无终端"
                    "阻抗口径不虚构（UNVERIFIED 如实不做）。"
                ),
            ),
            Boundary(
                quote="本族=**均衡器综合面**（由目标时延构造全通零极点）",
                note=(
                    "族界：si_channel/kqe=信道提取面、objectives/mask_filter="
                    "幅度规格面——方向相反不并入；既有 all_pass 命中均为布尔"
                    "语义误中。"
                ),
            ),
            Boundary(
                quote="上限 32（防滥用）",
                note=(
                    "级联 sections 非空、节数上限 32 防滥用守卫；数值 0.0 合法"
                    "（判缺失 is not None，#364④）。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w2s7_ruthroff_gd_drift.py",
                quote="tests/unit/test_w2s7_ruthroff_gd_drift.py",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="measurement_drift",
        tagline=(
            "测量系统漂移建模：参考对 OLS 线性漂移率估计+置信带+去趋势校正 "
            "GUM 预算，与测量链 EWMA+CUSUM 控制图监控（复用 anchor_drift_spc "
            "统计内核的同仓双源组合）。"
        ),
        modules=("calc_families/measurement_drift",),
        primary_entries=(
            ("calc_families/measurement_drift",
             "measurement_drift_estimate"),
            ("calc_families/measurement_drift",
             "measurement_drift_monitor"),
        ),
        test_face_needles=("measurement_drift_estimate",
                           "measurement_drift_monitor"),
        formulas=(
            Formula(
                title="OLS 线性漂移率估计（等间隔索引）",
                latex="\\hat\\beta=\\frac{\\sum(t-\\bar t)(y-\\bar y)}"
                      "{\\sum(t-\\bar t)^2},\\quad "
                      "\\mathrm{se}(\\hat\\beta)=\\sigma/\\sqrt{S_{xx}}",
                quote="β̂=Σ(t−t̄)(y−ȳ)/Σ(t−t̄)²、截距 ȳ−β̂·t̄；斜率标准误",
                quote2="se(β̂)=σ/√Sxx",
                cite=(
                    "模块 docstring「线性漂移率估计」行（σ=调用方显式声明走"
                    "正态 z 带；缺省 s/√Sxx 残差档 t 带 df=n−2）"
                ),
            ),
            Formula(
                title="去趋势校正与 GUM 逐点不确定度",
                latex="y_{corr,i}=y_i-\\hat\\beta\\,(i-\\bar t),\\quad "
                      "u_i=\\sqrt{\\sigma^2+\\mathrm{se}^2(i-\\bar t)^2}",
                quote="u_i=√(σ²+se²·(i−t̄)²)（GUM 独立贡献平方合成：测量散布+校正杠杆臂",
                cite=(
                    "模块 docstring「线性漂移率估计」行（校正序列去线性趋势、"
                    "均值保持；测量散布+校正杠杆臂两项 GUM 合成）"
                ),
            ),
            Formula(
                title="EWMA/CUSUM 控制图（复用 anchor_drift_spc 内核）",
                latex="z_i=\\lambda x_i+(1-\\lambda)z_{i-1},\\quad "
                      "\\mathrm{UCL}_i=\\bar z\\pm L\\sigma"
                      "\\sqrt{\\tfrac{\\lambda}{2-\\lambda}"
                      "\\bigl(1-(1-\\lambda)^{2i}\\bigr)}",
                quote="z_i=λx_i+(1−λ)z_{i−1}、控制限 z̄±L·σ·√(λ/(2−λ)·(1−(1−λ)^{2i}))",
                cite=(
                    "模块 docstring「SPC 控制图」行（复用 anchor_drift_spc "
                    "机器同仓双源；控制限恒等式自检 ≤1e-12 构造级锚）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="σ 必须显式声明（短序列不内估，",
                note=(
                    "短序列不内估 σ——anchor_drift_spc #118 家族纪律同款；"
                    "监控键 sigma 必填 >0。"
                ),
            ),
            Boundary(
                quote="三证据组合判定：EWMA/CUSUM/线性趋势三线，≥2 →",
                note=(
                    "drifted/warning/stable 三态组合判定（anchor_drift_spc "
                    "组合规则同构；线有效性下限随线自报不硬算）。"
                ),
            ),
            Boundary(
                quote="本族=**测量系统漂移**",
                note=(
                    "族界：anchor_drift/anchor_drift_spc=锚面漂移、"
                    "filter_temp_drift=器件温漂——本族=测量链读数序列"
                    "（漂移率估计/校正预算/控制图告警），SPC 统计内核组合"
                    "复用不替代。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w2s7_ruthroff_gd_drift.py",
                quote="tests/unit/test_w2s7_ruthroff_gd_drift.py",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="agc_loop",
        tagline=(
            "AGC 环路动力学：对数域一阶环线性化闭环常数（环路带宽/attack-"
            "release 时间常数/稳态误差）与阶跃扰动时域轨迹——rx_impairments "
            "预声明排除面的动态半边补全。"
        ),
        modules=("calc_families/agc_loop",),
        primary_entries=(
            ("calc_families/agc_loop", "agc_loop_dynamics"),
            ("calc_families/agc_loop", "agc_loop_response"),
        ),
        test_face_needles=("agc_loop_dynamics", "agc_loop_response"),
        formulas=(
            Formula(
                title="开环对数增益与扰动方程",
                latex="T=A\\,K_d\\,K_v,\\quad "
                      "\\tau_L\\frac{d\\delta}{dt}+(1+T)\\,\\delta=\\delta_{in}",
                quote="τ_L·dδ/dt + (1+T)·δ = δ_in",
                quote2="T = A·K_d·K_v（量纲 dB/V·V/dB 相消，无量纲）",
                cite=(
                    "模块 docstring「链路模型」「开环对数增益」行（控制论一阶环"
                    "线性化口径；负反馈极性=输出过高→V_c↑→增益↓）"
                ),
            ),
            Formula(
                title="闭环常数闭式（一阶环恒等式，测试锚主判）",
                latex="\\omega_p=\\frac{1+T}{\\tau_L},\\ "
                      "f_{loop}=\\frac{1+T}{2\\pi\\tau_L},\\ "
                      "\\tau_a=\\frac{\\tau_L}{1+T},\\ "
                      "\\varepsilon=\\frac{1}{1+T}",
                quote="闭环极点 ω_p=(1+T)/τ_L [rad/s]；环路带宽 f_loop=(1+T)/(2π·τ_L)",
                quote2="ε=1/(1+T)；阶跃暂态衰减到份额 α 的建立时间 t_s=−τ·ln(α)",
                cite=(
                    "模块 docstring「闭环常数闭式」节（release 档 "
                    "τ_r=ρ·τ_L/(1+T) 带宽再除 ρ；建立时间一阶标准口径）"
                ),
            ),
            Formula(
                title="阶跃响应闭式（attack/release 双档）",
                latex="\\delta(t)=\\frac{\\delta_{in}}{1+T}"
                      "\\bigl(1+T\\,e^{-t/\\tau_{eff}}\\bigr)",
                quote="δ(t) = δ_in/(1+T)·(1 + T·e^{−t/τ_eff})",
                cite=(
                    "模块 docstring「阶跃响应闭式」节（正阶跃=attack 快档、"
                    "负阶跃=release 慢档语义如实回显）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="线性化对数域一阶环——检波器理想对数律",
                note=(
                    "诚实边界：检波理想对数律/VGA dB 线性/单极点滤波——高阶"
                    "滤波与时延稳定性裕度面（时延相位侵蚀可致振荡）不在本域。"
                ),
            ),
            Boundary(
                quote="无 AGC 退化=T→0（A→0 极限）：",
                note=(
                    "A→0⁺ 数值极限档=开环直通恒等（τ→τ_L、ε→1）——"
                    "loop_gain_a>0 守卫下的退化锚。"
                ),
            ),
            Boundary(
                quote="P1dB 裕量/压缩后 NF 等静态线性度面仍归 rx_impairments",
                note=(
                    "静态线性度归 rx_impairments（预声明注记已改指路本模块）；"
                    "PLL 环路滤波器综合走 pll_loop_filter——同族不同对象"
                    "边界互指。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w3s10_agc_calkit_sixport.py",
                quote="aurora_f W3-S10 席域，R2_core_tier3 §③ D3 立项",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="cal_kit_verify",
        tagline=(
            "校准件完整性验证：机械 SOLT 标准件一阶模型响应闭式与工程验收"
            "判据、校准后 verification 纹波法正反双解——校准件「使用链」之外的"
            "模型核验与质量验收端。"
        ),
        modules=("calc_families/cal_kit_verify",),
        primary_entries=(
            ("calc_families/cal_kit_verify", "cal_kit_standard_response"),
            ("calc_families/cal_kit_verify", "cal_kit_verify_ripple"),
        ),
        test_face_needles=("cal_kit_standard_response",
                           "cal_kit_verify_ripple"),
        formulas=(
            Formula(
                title="offset 传输线因子（机械件统一模型）",
                latex="\\beta=\\frac{2\\pi f\\sqrt{\\varepsilon_r}}{c},\\ "
                      "\\alpha_{\\mathrm{dB/m}}=L_1\\sqrt{f_{\\mathrm{GHz}}},"
                      "\\quad e^{-2(\\alpha_{np}+j\\beta)l}"
                      "\\ (\\alpha_{np}=A_{\\mathrm{dB}}/8.6859)",
                quote="β=2πf√εr/c（TEM 色散-free 档）、衰减系数按趋肤 √f 标度",
                quote2="（α_np=A_dB/8.6859）",
                cite=(
                    "模块 docstring「offset 传输线因子」节（参考面在连接器；"
                    "反射路径往返因子作用于各标准件闭式）"
                ),
            ),
            Formula(
                title="各标准件一阶闭式",
                latex="\\Gamma_{short}=-e^{-2(\\alpha+j\\beta)l},\\quad "
                      "\\Gamma_{open}=\\frac{1-j\\omega C_f Z_0}"
                      "{1+j\\omega C_f Z_0}e^{-2(\\alpha+j\\beta)l},\\quad "
                      "\\Gamma_{load}=\\frac{\\mathrm{ratio}-1}"
                      "{\\mathrm{ratio}+1}",
                quote="short：Γ=−e^{−2(α+jβ)l}（理想 l=0/无耗 → |Γ|=1、相位 180°；",
                quote2="load：Z_L=ratio·Z0 → Γ₀=(ratio−1)/(ratio+1)（实数），偏置时",
                cite=(
                    "模块 docstring「各标准件一阶闭式」节（open 边缘电容/through "
                    "损耗时延同节；load 失配地板 RL=−20lg|Γ₀| 理想档 None JSON "
                    "契约）"
                ),
            ),
            Formula(
                title="verification 纹波法（正反双解）",
                latex="pp_{\\mathrm{dB}}=20\\lg\\frac{g+d}{g-d},\\quad "
                      "d=g\\,\\frac{10^{pp/20}-1}{10^{pp/20}+1},\\quad "
                      "|\\Gamma_{meas}|\\in[|g-d|,\\,g+d]",
                quote="纹波峰峰 pp_dB = 20lg((g+d)/(g−d))，反向 d = g·(10^(pp/20)−1)",
                quote2="/(10^(pp/20)+1)。",
                cite=(
                    "模块 docstring「纹波法」节（残余方向性 d=10^(D_db/20)；"
                    "与 directional_bridge/vna_reflection_uncertainty 回损地板"
                    "恒等式同仓双源三方互证）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="（工程档缺省=计量级惯例带，调用方可覆写；非特定",
                note=(
                    "验收判据=计量级惯例档（调用方可覆写）——非特定厂商 spec "
                    "不冒充（#300 归属纪律）；pass=适用判据合取，不适用判据"
                    "如实 not_applicable。"
                ),
            ),
            Boundary(
                quote="一阶模型——offset 线 Z0 失配/连接器重复性/",
                note=(
                    "辐射开路频率相关电容高阶项（多参数拟合面）不在本域——"
                    "iss_on_wafer 族=该频率多项式面（边界互补互指）；纹波法"
                    "只含方向性单误差项（高阶纹波面归 vna_uncertainty）。"
                ),
            ),
            Boundary(
                quote="（g>0）=|Γ_meas| 圆环包围原点、相位回绕域——纹波窗仍给但回损",
                note=(
                    "包围旗标+回损判据按不通过如实记，不外推假窗；d=g 恰过零 "
                    "dB 域峰峰无定义走 None JSON 契约。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w3s10_agc_calkit_sixport.py",
                quote="aurora_f W3-S10 席域，R2_core_tier3 §③ D5 立项",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="six_port",
        tagline=(
            "六端口反射计反演架构：功率读数→Γ 最小二乘闭式反演与已知负载→"
            "q 点校准常数提取——4 路功率检波干涉法的圆交点反演（桥式检波器件面"
            "之外的架构层）。"
        ),
        modules=("calc_families/six_port",),
        primary_entries=(
            ("calc_families/six_port", "six_port_gamma_solve"),
            ("calc_families/six_port", "six_port_cal_extract"),
        ),
        test_face_needles=("six_port_gamma_solve", "six_port_cal_extract"),
        formulas=(
            Formula(
                title="六端口状态方程（Engen 反射计口径）",
                latex="P_i=K_i\\,|a|^2\\,|\\Gamma-q_i|^2",
                quote="P_i = K_i·|a|²·|Γ − q_i|²",
                cite=(
                    "模块 docstring「六端口状态方程」节（Γ=b/a、q_i=第 i 路"
                    "检波器等效波源复数位置；Engen IEEE TTT 25(12) 1977 "
                    "二级转引，trl_standards 同源引注背书）"
                ),
            ),
            Formula(
                title="Γ 最小二乘反演闭式（4×3 过定线性系统）",
                latex="|\\Gamma-q_i|^2=X-2(u_i x+v_i y)+|q_i|^2"
                      "\\ \\Rightarrow\\ "
                      "X-2u_i x-2v_i y=p_i-|q_i|^2",
                quote="X − 2u_i·x − 2v_i·y = p_i − |q_i|²   （i=3..6，4×3 线性系统）",
                cite=(
                    "模块 docstring「Γ 最小二乘反演闭式」节（记 Γ=x+jy、X=|Γ|²；"
                    "正规方程 AᵀA·z=Aᵀb 纯 python 高斯消元；多余第 4 方程=过定"
                    "冗余校验面）"
                ),
            ),
            Formula(
                title="q 点校准提取闭式（恰定直解/OLS）",
                latex="|q_i|^2-2x_j u_i-2y_j v_i=p_{ij}-|\\Gamma_j|^2",
                quote="|q_i|² − 2x_j·u_i − 2y_j·v_i = p_ij − |Γ_j|²",
                cite=(
                    "模块 docstring「q 点校准提取闭式」节（N=3 恰定=直解残差"
                    "机器精度、N>3 过定=最小二乘；extract→solve 合成回收="
                    "校准↔测量闭合成环 #118 锚树主判）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="口径 p_i = P_i/(K_i·|a|²) 由调用方完成——实测 K_i≠1/检波律修正/",
                note=(
                    "理想平方律 K_i=1 归一化由调用方完成——实测检波律/温漂走 "
                    "detector_device 与 power_cal_chain 补偿后归一（单源"
                    "不重复）。"
                ),
            ),
            Boundary(
                quote="q 点全等/设计矩阵奇异 → 显式 ValueError（退化 q 面）。",
                note=(
                    "退化面守卫：q 点全等/负载共线（设计矩阵奇异）显式拒绝——"
                    "校准键要求 ≥3 线性独立负载点。"
                ),
            ),
            Boundary(
                quote="Hoer 1979 TRL 口径走 trl_standards 面）不在本族；|Γ|>1（有源",
                note=(
                    "功率检波噪声加权 OLS/结非理想高阶项/双六端口 TRL 扩展不在"
                    "本族；|Γ|>1 有源 DUT 不设界如实回显 flag。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w3s10_agc_calkit_sixport.py",
                quote="aurora_f W3-S10 席域，R2_core_tier3 §③ D7 立项",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="iss_on_wafer",
        tagline=(
            "在片 ISS 校准件族：共面开路/短路/负载/直通的频率多项式寄生模型"
            "闭式响应与一端口三项误差模型提取——任意非理想标准定义下 Ed/Es/Er "
            "闭式线性反解。"
        ),
        modules=("calc_families/iss_on_wafer",),
        primary_entries=(
            ("calc_families/iss_on_wafer", "iss_standard_response"),
            ("calc_families/iss_on_wafer", "iss_oneport_cal_extract"),
        ),
        test_face_needles=("iss_standard_response",
                           "iss_oneport_cal_extract"),
        formulas=(
            Formula(
                title="开路/短路频率多项式（套件定义惯例格式）",
                latex="C(f)=c_0+c_1f+c_2f^2+c_3f^3\\ "
                      "(\\mathrm{fF}),\\quad "
                      "L(f)=l_0+l_1f+l_2f^2+l_3f^3\\ (\\mathrm{pH})",
                quote="C(f) = c₀ + c₁·f + c₂·f² +",
                quote2="L(f) = l₀ + l₁·f + l₂·f² +",
                cite=(
                    "模块 docstring「开路」「短路」节（Keysight 机械/在片套件"
                    "定义 C0..C3/L0..L3 多项式惯例格式二级转引——格式出处"
                    "而非厂商数值）"
                ),
            ),
            Formula(
                title="一端口三项误差模型（Cramer 闭式）",
                latex="\\Gamma_{meas}=E_d+\\frac{E_r\\Gamma}{1-E_s\\Gamma}"
                      "\\ \\Rightarrow\\ "
                      "\\Gamma=\\frac{m-E_d}{E_r+E_s(m-E_d)}",
                quote="Γ_meas = Ed + Er·Γ/(1 − Es·Γ)。给定三个已知标准定义 Γ_i 与原",
                quote2="DUT 回收：Γ = (m − Ed)/(Er + Es·(m − Ed))。",
                cite=(
                    "模块 docstring「一端口三项误差模型」节（恒等变形 "
                    "m_i=Ed+Er′·Γ_i+Es·(m_i·Γ_i)、Er′=Er−Ed·Es 的 3×3 线性"
                    "方程组 Cramer 闭式；Pozar VNA 校准章同款）"
                ),
            ),
            Formula(
                title="直通匹配线（损耗时延恒等式）",
                latex="S_{21}=e^{-(\\alpha_{np}+j\\beta)l},\\quad "
                      "\\tau=\\frac{l\\sqrt{\\varepsilon_{eff}}}{c},\\quad "
                      "|S_{21}|=10^{-IL/20}",
                quote="τ = l·√εeff/c（ns）；|S21| = 10^(−IL/20) 恒等式；理想 l=0 → S21=1。",
                cite=(
                    "模块 docstring「直通」节（α_np=IL/(20·log10 e) 精确 "
                    "dB→Np 换算，平损耗档）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="②多项式系数值须调用",
                note=(
                    "套件定义来源自负——不冒充任何厂商 spec 数值（#122/#300）；"
                    "逐频点代入值必须 ≥0（无源性检验，负值显式拒绝）。"
                ),
            ),
            Boundary(
                quote="本族=**共面在片件**",
                note=(
                    "分工面：cal_kit_verify=同轴机械 SOLT 件验证端（连接器/"
                    "offset 空气线）、trl_solt=使用链理想档——本族=共面在片件"
                    "多项式寄生面；理想标准档退化回 trl_solt 同式逐位互证。"
                ),
            ),
            Boundary(
                quote="差模型不含串扰/漂移项（八项以上归 trl_solt/thz_vna 级联域）；",
                note=(
                    "三项误差模型不含串扰/漂移项；deembed=OpenShort 去嵌泛用件"
                    "不重复实现（探针垫去嵌半边如实不并）。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w5s18_core_edge.py",
                quote="aurora_f W5-S18 席域，R2_core_tier3 边际池立项",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="source_power_cal",
        tagline=(
            "源功率校准闭环：功率计参考面修正读数→offset 表→源编程设定闭式"
            "（参考面交付功率平坦档），附平坦设定对照档与不确定度 1:1 传播——"
            "源编程端与功率测量链的交付恒等式互补。"
        ),
        modules=("calc_families/source_power_cal",),
        primary_entries=(
            ("calc_families/source_power_cal", "source_power_cal_table"),
        ),
        test_face_needles=("source_power_cal_table",),
        formulas=(
            Formula(
                title="闭环方程（offset 表→源编程设定）",
                latex="\\mathrm{offset}(f)=p_{meas}(f)-p_{set},\\quad "
                      "\\mathrm{program}(f)=p_{target}-\\mathrm{offset}(f)",
                quote="offset(f) = p_meas(f) − p_set            （测量端传递/损耗表，dB）",
                quote2="program(f) = p_target − offset(f)        （源编程设定表，dBm）",
                cite=(
                    "模块 docstring「闭环方程」节（交付恒等式 program(f)+"
                    "offset(f)=p_target 逐位；Keysight \"Source Power "
                    "Calibration\" 语义二级转引）"
                ),
            ),
            Formula(
                title="flat-falling 双读法（方向旗标如实自报）",
                latex="p_{flat}(f)=p_{target}+\\mathrm{offset}(f)"
                      "\\ \\Rightarrow\\ "
                      "\\mathrm{delivered}=p_{flat}+\\mathrm{offset}"
                      "\\ (\\text{随 }f\\text{ 下坠})",
                quote="② 平坦设定对照档 p_flat(f) = p_target + offset(f)",
                cite=(
                    "模块 docstring「flat-falling 双读法」节（平坦交付档与"
                    "平坦设定对照档两档逐频列表与 span/单调方向全部落盘）"
                ),
            ),
            Formula(
                title="不确定度传播（dB 域 1:1 线性）",
                latex="u_{program}(f)=u_{meas}(f),\\quad U=k{=}2\\cdot u",
                quote="u_program(f) = u_meas(f)（参考面",
                cite=(
                    "模块 docstring「不确定度传播」节（功率计链 GUM 预算见 "
                    "power_cal_chain 的 u_components 面，单源不重复）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="读数端校准因子/失配补偿不在本键（输入必须已是参考",
                note=(
                    "输入语义=power_cal_chain 输出（参考面修正后读数）——"
                    "原始读数先走该链（#118 语义单一事实源）。"
                ),
            ),
            Boundary(
                quote="①逐频点独立闭式（无跨频拟合/插值面，源平滑",
                note=(
                    "逐频点独立闭式、无跨频拟合/插值面（源平滑约束不在本域）；"
                    "接收机频响线性度（dB 域叠加）由调用方保证。"
                ),
            ),
            Boundary(
                quote="源功率上限触顶时平坦交付不可达，如实不裁剪",
                note=(
                    "可选源上限超限点记 infeasible+超限 dB——不裁剪不冒充"
                    "可达。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w5s18_core_edge.py",
                quote="aurora_f W5-S18 席域，R2_core_tier3 边际池立项",
                tracked=True,
            ),
        ),
    ),
    # ─── aurora_g W1-S3 内核卡批三（9 张；R2_core_tier4 §⑤ 余量表 A 组 READY
    # 7 族 + CALC-only 2 族——照 W6-S22 纯 CALC 键族卡先例：注册键+docstring
    # 「物理口径/出处」节引文钉+锚树测试面 needles 三面齐备；rf_line 三线
    # 与 slotline_siw siw 半族为 C 组兄弟卡部分覆盖的剩余键面，slotline 半族
    # 已由既有 slotline 卡覆盖不重复出卡；anchors/KD-1 零命中如实渲染）──
    CardSpec(
        kernel_id="combline",
        tagline=(
            "combline 杆与同轴腔谐振器频率/Q 闭式：短路线加载电容串联谐振"
            "双向互解（给定频率解杆长/给定杆长解频率）、同轴腔 TEM 半波与"
            "四分之一波双向互解带高阶模截止筛查、无载 Q 导体/介质串联合成"
            "——滤波器实现族的谐振器级底座。"
        ),
        modules=("calc_families/combline_resonator",),
        primary_entries=(
            ("calc_families/combline_resonator", "combline_resonance"),
            ("calc_families/combline_resonator", "coaxial_cavity_resonance"),
            ("calc_families/combline_resonator", "cavity_unloaded_q"),
        ),
        test_face_needles=(
            "combline_resonance",
            "coaxial_cavity_resonance",
            "cavity_unloaded_q",
        ),
        formulas=(
            Formula(
                title="combline 谐振条件与双向互解（感性杆+集总电容）",
                latex=(
                    "X_L(\\omega_0)=Z_r\\tan\\theta_0=\\frac{1}{\\omega_0 C}"
                    "\\ \\Leftrightarrow\\ \\omega_0 C Z_r\\tan\\theta_0=1,"
                    "\\quad \\theta_0=\\arctan\\frac{1}{\\omega_0 C Z_r}"
                ),
                quote="ω₀·C·Zr·tan(θ₀) = 1",
                quote2="综合（给 f₀）：θ₀ = arctan(1/(ω₀·C·Zr))（闭式，0<θ₀<90°）",
                cite=(
                    "模块 docstring「公式口径」节（Matthaei–Young–Jones ch.8 "
                    "combline 等效电路口径；杆长 l=θ₀·c₀/(2π·f₀·√εeff) 反解与"
                    "分析给杆长的单调二分同节在档）"
                ),
            ),
            Formula(
                title="同轴腔 TEM 谐振（Z0 闭式与半波/四分之一波双向）",
                latex=(
                    "Z_0=\\frac{60}{\\sqrt{\\varepsilon_r}}\\ln\\frac{b}{a},"
                    "\\quad f_0=\\frac{c_0}{2l\\sqrt{\\varepsilon_r}}"
                    "\\ (\\lambda/2),\\quad "
                    "f_0=\\frac{c_0}{4l\\sqrt{\\varepsilon_r}}\\ (\\lambda/4)"
                ),
                quote="特性阻抗 Z0 = (60/√εr)·ln(b/a) Ω（TEM 精确闭式）",
                quote2="f₀ = c₀/(2·l·√εr)，λ/4 短路-开路腔 f₀ = c₀/(4·l·√εr)（双向互解）",
                cite=(
                    "模块 docstring（Pozar Microwave Engineering §6.6 同轴线"
                    "谐振器；短路-短路/短路-开路两腔型双向互解）"
                ),
            ),
            Formula(
                title="首个高阶模 TE11 截止（保角映射近似）",
                latex="f_{c,TE11}=\\frac{c_0}{\\pi\\,(a+b)\\,\\sqrt{\\varepsilon_r}}",
                quote="f_c,TE11 = c₀ / (π·(a+b)·√εr)",
                cite="模块 docstring（保角映射近似 kc≈2/(a+b)，λc=π(a+b)——单模 TEM 假设的截止筛查面）",
            ),
            Formula(
                title="无载 Q 合成（趋肤电阻口径）",
                latex=(
                    "R_s=\\sqrt{\\pi f\\mu/\\sigma},\\quad "
                    "Q_c=\\frac{\\omega\\mu\\ln(b/a)}{R_s\\,(1/a+1/b)},"
                    "\\quad Q_d=\\frac{1}{\\tan\\delta},\\quad "
                    "\\frac{1}{Q_u}=\\frac{1}{Q_c}+\\frac{1}{Q_d}"
                ),
                quote="Qc = ω·μ·ln(b/a) / ( Rs·(1/a + 1/b) )",
                quote2="1/Qu = 1/Qc + 1/Qd  →  Qu = Qc·Qd/(Qc+Qd)",
                cite=(
                    "模块 docstring（Pozar §6.6 谐振器 Q；由场积分法与 "
                    "β/(2α) 衰减关系两条路线同解自洽，测试互证）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="f₀ ≥ f_c,TE11 时单模 TEM 假设失效——如实 note 不拒绝（TEM 谐振式",
                note=(
                    "高阶模越界=单模口径失效，如实注记不拒绝——TEM 谐振式"
                    "本身仍成立，判定交消费面。"
                ),
            ),
            Boundary(
                quote="tanδ=0 → Qd=∞ 如实返 null",
                note="无耗介质档 Qd 无穷如实返 null，不虚构有限 Q。",
            ),
            Boundary(
                quote="C→0 时 θ₀→90°，l→λg/4——退化为 λ/4 短路线自谐振。",
                note=(
                    "加载电容极限档：C→0 退化为 λ/4 短路线自谐振（测试钉）；"
                    "分析给杆长的根唯一性由 g(f) 导数式保证。"
                ),
            ),
            Boundary(
                quote="守卫：zr_ohm>0；cap_ff>0；epsilon_r ≥ 1；f0_ghz>0 / length_mm>0 恰给",
                note=(
                    "双向互解 f0/length 恰给其一、同轴 a<b 同给且 mode 两档——"
                    "越界一律显式拒绝不外推。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w5a_doa_combline.py",
                quote="数值锚（#118 独立来源；锚树 tests/unit/test_w5a_doa_combline.py）",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="cps",
        tagline=(
            "共面带（双带无地）准静态闭式：空气线椭圆积分精确解+有限厚基板 "
            "tanh 部分电容映射，叠加拉普拉斯 FD 定标的有效厚度因子与角落"
            "二维修正（显式 opt-in）——无地薄基板场泄漏导致的裸映射系统性"
            "低估已定标校正，定标域边界如实预声明。"
        ),
        modules=("calc_families/rf_line",),
        primary_entries=(
            ("calc_families/rf_line", "cps_analysis"),
            ("calc_families/rf_line", "cps_synthesis"),
        ),
        test_face_needles=("cps_analysis", "cps_synthesis"),
        formulas=(
            Formula(
                title="空气线 CPS 精确闭式（椭圆积分比）",
                latex=(
                    "Z_{0}=\\frac{120\\pi}{\\sqrt{\\varepsilon_{\\mathrm{eff}}}}"
                    "\\frac{K(k_1)}{K'(k_1)},\\quad k_1=\\frac{a}{b},"
                    "\\quad a=\\tfrac{gap}{2},\\ b=\\tfrac{gap}{2}+w"
                ),
                quote="Z0 = 120π·K(k1)/K'(k1)/√εeff，k1=a/b",
                cite=(
                    "模块 docstring _cps_ri「出处」节（Wadell TLDH p.83 "
                    "eqs 3.4.6.x；MathWorks RF PCB Toolbox 官方例 MoM 对拍；"
                    "与 CPW 互补对偶 Z_CPS·Z_CPW=η0²/4 自洽）"
                ),
            ),
            Formula(
                title="有限厚基板部分电容合成（tanh 映射）",
                latex=(
                    "C=\\frac{\\varepsilon_0}{r_1}+(\\varepsilon_r-1)"
                    "\\frac{\\varepsilon_0}{2\\,r_3},\\quad "
                    "\\varepsilon_{\\mathrm{eff}}=\\frac{C}{C_{\\mathrm{air}}},"
                    "\\quad k_3=\\frac{\\tanh(\\pi a/2h_{\\mathrm{eff}})}"
                    "{\\tanh(\\pi b/2h_{\\mathrm{eff}})}"
                ),
                quote="C = ε0/r1 + (εr−1)·ε0/(2·r3)，εeff = C/C_air = 1+(εr−1)·r1/(2·r3)。",
                cite=(
                    "模块 docstring _cps_ri「出处」节（Gupta/Ghione 部分电容"
                    "技术，与 _cpwg_ri 同框架——介质超额项走接地板 tanh 映射）"
                ),
            ),
            Formula(
                title="FD 定标有效厚度（无地薄基板场泄漏校正）",
                latex=(
                    "h_{\\mathrm{eff}}=\\gamma(\\varepsilon_r)\\,h,\\quad "
                    "\\gamma(\\varepsilon_r)=1+C\\,\\varepsilon_r^{-P}"
                ),
                quote="γ(εr) = 1 + 0.9014·εr^(−0.6361)（εr→∞ 场受限 γ→1，εr=3.66 γ=1.395）",
                cite=(
                    "模块 docstring「FD 定标」节（quasistatic_fd.py 裁判逐 εr "
                    "最小二乘+幂律拟合；值源优先 cps.gamma_er.fdref-v1 公式锚、"
                    "回退闭式与锚逐位相等）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="定标域 a/h≲1 且 b/h≲3 之外（宽带缝角落）γ(εr) 单参数修正**数据不支持**",
                note=(
                    "定标域外单参数 γ 修正数据不支持（逐点最优 γ 是二维曲面，"
                    "不硬凑）——域外闭式低估幅度如实注记在档。"
                ),
            ),
            Boundary(
                quote="角落区按 160 点在档 FD 拟合 log E2 全二次面",
                note=(
                    "角落二维修正为 corner2d=True 显式 opt-in——缺省路径与"
                    "定标域内钉住的证据表逐位一致。"
                ),
            ),
            Boundary(
                quote="极限自洽（有单测，定标不改变）：h→0 εeff→1；h→∞ εeff→(1+εr)/2（Wen",
                note=(
                    "两端点极限与单调性有单测钉（定标不改变）：h→0 全空气、"
                    "h→∞ Wen 半空间口径；gap 两端与 Z0 随宽单调同节。"
                ),
            ),
            Boundary(
                quote="CPS 闭式定义域：w>0、gap>0、h>0、εr≥1",
                note=(
                    "定义域守卫显式 ValueError；k1 数值退化（gap/w 比例超出"
                    "准静态共形映射适用域）显式拒绝。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="docs/rf_template_references.md",
                quote="出处（docs/rf_template_references.md §11.1）：",
                tracked=True,
            ),
            DocRef(
                path="scripts/fd_laplace_tline_referee.py",
                quote="复现：scripts/fd_laplace_tline_referee.py --refit-cps-gamma）",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="interdigital",
        tagline=(
            "交指/梳状杆滤波器实现族：零厚度耦合杆条带线偶/奇模电容共形映射"
            "精确闭式、Getsinger 等效网络综合（g 值→倒置器→逐节电容目标→"
            "杆宽缝反解→四分之一波长杆长）与 combline 耦合缝半边（归一化"
            "耦合↔缝宽闭环、装载斜率双档）——与 combline_resonator 谐振器"
            "级键面语义互补不重复。"
        ),
        modules=("calc_families/interdigital_bpf",),
        primary_entries=(
            ("calc_families/interdigital_bpf", "interdigital_bars_capacitance"),
            ("calc_families/interdigital_bpf", "interdigital_bpf_synthesize"),
            ("calc_families/interdigital_bpf", "combline_coupling_gap"),
        ),
        test_face_needles=(
            "interdigital_bars_capacitance",
            "interdigital_bpf_synthesize",
            "combline_coupling_gap",
        ),
        formulas=(
            Formula(
                title="零厚度耦合杆条带线共形映射（偶/奇模）",
                latex=(
                    "k_e=\\tanh x\\,\\tanh y,\\quad "
                    "k_o=\\frac{\\tanh x}{\\tanh y},\\quad "
                    "Z_{0m}=\\frac{30\\pi}{\\sqrt{\\varepsilon_r}\\,r_m},"
                    "\\quad r_m=\\frac{K(k_m)}{K'(k_m)}"
                    "=\\frac{\\mathrm{AGM}(1,k_m)}{\\mathrm{AGM}(1,k_m')}"
                ),
                quote="k_e = tanh(x)·tanh(y)，  k_e' = sqrt(cosh²y + sinh²x)/(cosh x·cosh y)",
                quote2="Z0m = 30π/(√εr·r_m)，r_m = K(k_m)/K'(k_m) = AGM(1,k_m)/AGM(1,k_m')",
                cite=(
                    "模块 docstring「物理口径」节（Getsinger IRE Trans. "
                    "MTT-10(1) 1962 薄条极限；Gupta 耦合带状线同式；k' 平方根"
                    "消相消稳定形与 AGM 恒等式，s→∞/s→0 双极限锚跨键钉）"
                ),
            ),
            Formula(
                title="倒置器与耦合系数（TEM 恒等）",
                latex=(
                    "J_{m,m+1}=\\frac{v}{2}\\,(C_o-C_e),\\quad "
                    "k_{\\mathrm{phys}}=\\frac{C_o-C_e}{C_o+C_e}"
                    "\\equiv\\frac{Z_{0e}-Z_{0o}}{Z_{0e}+Z_{0o}}"
                ),
                quote="J_m,m+1 = v·(C_o − C_e)/2   [S]（v=c₀/√εr）",
                quote2="k_phys = (C_o − C_e)/(C_o + C_e) ≡ (Z0e − Z0o)/(Z0e + Z0o)（TEM 恒等）",
                cite=(
                    "模块 docstring（Getsinger 等效网络，MYJ ch.10 口径；"
                    "电容口径与阻抗口径恒等逐位测试钉）"
                ),
            ),
            Formula(
                title="逐节电容目标（几何均值约束，闭式精确）",
                latex=(
                    "C_{e,o}=\\frac{\\sqrt{\\Delta C^2+4C_0^2}\\mp\\Delta C}{2},"
                    "\\quad \\Delta C=\\frac{2J}{v},\\quad "
                    "C_0=\\frac{1}{v Z_r}"
                ),
                quote="C_e,o = (√(ΔC² + 4C_0²) ∓ ΔC)/2，ΔC = 2J/v，C_0 = 1/(v·Z_r)",
                cite=(
                    "模块 docstring（几何均值约束 sqrt(C_e·C_o)=1/(v·Z_r) ⇔ "
                    "Z0e·Z0o=Z_r²；(C_e,C_o)→(w,s) 嵌套 brentq 二维反解，"
                    "杆长=λ/4@√εr 均匀介质 TEM 精确）"
                ),
            ),
            Formula(
                title="combline 半边（k↔缝闭环与装载斜率双档）",
                latex=(
                    "J_{ij}=b_s k_{ij},\\quad "
                    "b_s=\\frac{\\cot\\theta_0+\\theta_0\\csc^2\\theta_0}{2 Z_r},"
                    "\\quad \\theta_0=\\arctan\\frac{1}{\\omega_0 C Z_r}"
                ),
                quote="J_ij = b_s·k_ij（窄带倒置器-耦合关系，MYJ ch.8/10）",
                quote2="b_s = [cotθ₀ + θ₀·csc²θ₀]/(2·Z_r)，  θ₀=arctan(1/(ω₀C·Z_r))",
                cite=(
                    "模块 docstring「combline 半边」节（装载斜率为本仓 MYJ "
                    "ch.8 等效电路第一性推导，实现前独立复算在档；θ₀→90° "
                    "退化=空载档恒等锚树钉、与 combline_resonance 跨键同解）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="有限杆厚/端电容（Getsinger 有限厚度修正）不在 v1 口径（零厚度极限，如实",
                note="零厚度极限档：有限杆厚/端电容修正不在 v1 口径，如实注记不做。",
            ),
            Boundary(
                quote="限 / 极弱耦合越上限）显式拒绝（附节序号与残差）",
                note=(
                    "缝反解越域（极强耦合达缝下限/极弱耦合越上限）显式拒绝，"
                    "附节序号与残差——不静默夹持。"
                ),
            ),
            Boundary(
                quote="s 上限 12b（tanh 饱和阈 y=πs/2b≲19，#334 同族——超界=数值上等价无",
                note=(
                    "弱耦合上限=数值饱和阈（超界等价无穷远）显式拒绝——"
                    "饱和域不是物理无穷远（#334 同族纪律）。"
                ),
            ),
            Boundary(
                quote="cap_ff/f0_ghz 成对给（单给显式拒绝）。",
                note=(
                    "装载斜率双档互斥语义：给装载电容与频率成对参数走 combline "
                    "装载档，否则空载档——单给显式拒绝。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_a3c_coupled_interdigital.py",
                quote="锚树 tests/unit/test_a3c_coupled_interdigital.py 与",
                tracked=True,
            ),
            DocRef(
                path="tests/unit/test_aurora_d_core7.py",
                quote="tests/unit/test_aurora_d_core7.py）。",
                tracked=True,
            ),
            DocRef(
                path="runs/aurora_d/_core7_verify_derivation.py",
                quote="前独立复算：k roundtrip ≤1e-15、k↔J 代数互逆恒等式、跨键结构锚（同参",
                tracked=False,
            ),
        ),
    ),
    CardSpec(
        kernel_id="siw",
        tagline=(
            "基片集成波导闭式：Cassivi 等效宽度+同宽介质矩形波导 TE10 等效"
            "（截止/色散/波阻抗），过孔藩篱设计规则复核（孔不重叠/泄漏上界/"
            "电小直径）显式把关——SIW 半族独立出卡，槽线半族见 slotline 卡。"
        ),
        modules=("calc_families/slotline_siw",),
        primary_entries=(
            ("calc_families/slotline_siw", "siw_analysis"),
            ("calc_families/slotline_siw", "siw_synthesis"),
        ),
        test_face_needles=("siw_analysis", "siw_synthesis"),
        formulas=(
            Formula(
                title="Cassivi 等效宽度",
                latex="w_{\\mathrm{eff}}=w-\\frac{d^2}{0.95\\,s}",
                quote="Cassivi 2002 等效宽度（mm）：w_eff = w − d²/(0.95·s)。",
                cite=(
                    "模块头「SIW」注记（来源 A：Cassivi et al. 2002 MWCL "
                    "12(9):333-335 / Bozzi 2011 IET 综述；来源 B：Wu–Deslandes"
                    "–Cassivi TELSIKS 2003——双源核实；值源优先 siw.w_eff."
                    "lit-v1 公式锚，回退闭式与锚逐位相等）"
                ),
            ),
            Formula(
                title="TE10 等效截止与色散（介质矩形波导等效）",
                latex=(
                    "f_{c10}=\\frac{c}{2 w_{\\mathrm{eff}}\\sqrt{\\varepsilon_r}},"
                    "\\quad \\beta=\\sqrt{(n k_0)^2-\\Big(\\frac{\\pi}"
                    "{w_{\\mathrm{eff}}}\\Big)^2},\\quad n=\\sqrt{\\varepsilon_r}"
                ),
                quote="fc10 = c/(2·w_eff·√εr)，β(f) = √((n·k0)² − (π/w_eff)²)，n=√εr，kc=π/w_eff。",
                cite=(
                    "模块头「SIW」注记（按同宽 w_eff 同填充的介质矩形波导等效"
                    "——来源 A 明文；截止下 β 虚数如实返 NaN 并附倏逝衰减"
                    "系数供调用方处理）"
                ),
            ),
            Formula(
                title="波阻抗口径（u/i 与功率-电压两定义）",
                latex="Z_{TE}=\\frac{\\omega\\mu_0}{\\beta},\\quad "
                      "Z_{PV}=\\frac{2 b\\,Z_{TE}}{w_{\\mathrm{eff}}}",
                quote="波导阻抗口径（确定性内核非手数，#7）：TE10 波阻抗 Z_TE=ωμ0/β（u/i 定义），",
                cite=(
                    "模块头「SIW」注记（功率-电压定义消元推导同节；截止/"
                    "色散/波阻抗与基板厚无关，Z_PV 需基板厚时由渲染层按模板"
                    "换算——本键只出与厚无关的量）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="设计规则（过孔藩篱泄漏控制，来源 B[1]/C 双源）：s ≤ 2·d 且 d < λ_sub/5",
                note=(
                    "设计规则双源口径：孔不重叠（s>d）、泄漏控制上界（s≤2d）、"
                    "电小直径（d<λ_sub/5，取较严 λ_sub 口径）——违规显式 "
                    "ValueError 并返回实测比值表供判读留痕。"
                ),
            ),
            Boundary(
                quote="回收基准（#118/#300，test_siw_template 钉死）：d→0 极限 w_eff→w 逐位；",
                note=(
                    "回收基准：过孔直径趋零退化为实体波导（等效宽度逐位）、"
                    "空气填充复现 WR-90 教科书截止值——锚树钉死。"
                ),
            ),
            Boundary(
                quote="w = w_eff + d²/(0.95·s)（Cassivi 式反解）；设计规则检查用 fc10（带内最松",
                note=(
                    "综合为 Cassivi 式反解+回代自洽（残差超带显式硬错）；"
                    "设计规则检查用截止频率带内最松端，工作频率端的电小直径"
                    "条件由分析键按实查频率把关。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(path="runs/siw_family/criteria.md", quote="# 双源核实与全部常数出处：内部证据档 §1（铁律 1c）——",
                tracked=False,
            ),
            DocRef(
                path="tests/unit/test_siw_template.py",
                quote="回收基准（#118/#300，test_siw_template 钉死）：d→0 极限 w_eff→w 逐位；",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="slot",
        tagline=(
            "矩形波导宽壁纵向缝 Stevenson 族：谐振缝并联相对电导正反解"
            "（含波导尺寸比与驻波因子两修正）与谐振（驻波）阵综合（导电率"
            "阶梯→逐缝偏置/交替换边/短路位）——行波阵与有限壁厚修正不在"
            "键面，理想化偏差方向注记在档。"
        ),
        modules=("calc_families/slot_array",),
        primary_entries=(
            ("calc_families/slot_array", "slot_stevenson_conductance"),
            ("calc_families/slot_array", "slot_array_synthesis_resonant"),
        ),
        test_face_needles=(
            "slot_stevenson_conductance",
            "slot_array_synthesis_resonant",
        ),
        formulas=(
            Formula(
                title="Stevenson 谐振缝并联相对电导",
                latex=(
                    "g(x)=\\frac{G}{G_0}=2.09\\,\\frac{a}{b}\\,"
                    "\\frac{\\lambda_g}{\\lambda_0}"
                    "\\cos^2\\!\\Big(\\frac{\\pi\\lambda_0}{2\\lambda_g}\\Big)"
                    "\\sin^2\\!\\Big(\\frac{\\pi x}{a}\\Big)"
                ),
                quote="g(x) = G/G0 = 2.09·(a/b)·(λg/λ0)·cos²(π·λ0/(2·λg))·sin²(π·x/a)",
                cite=(
                    "模块 docstring「物理口径」节（法源 Stevenson 1948 J. "
                    "Appl. Phys. 19——原文 closed 式号不可考禁编造，式形态经"
                    "四路独立二手源逐字互证+WR90 数值逐位复算，RESOLVED 裁决"
                    "与勘误表在档）"
                ),
            ),
            Formula(
                title="偏置反解与可达上限",
                latex=(
                    "x=\\frac{a}{\\pi}\\arcsin\\sqrt{\\frac{g}{g_{\\max}}},"
                    "\\quad g_{\\max}(f)=2.09\\,\\frac{a}{b}\\,"
                    "\\frac{\\lambda_g}{\\lambda_0}"
                    "\\cos^2\\!\\Big(\\frac{\\pi\\lambda_0}{2\\lambda_g}\\Big)"
                ),
                quote="x = (a/π)·arcsin(sqrt(g/g_max))，其中",
                quote2="g_max(f) = 2.09·(a/b)·(λg/λ0)·cos²(πλ0/(2λg))。g > g_max 显式拒绝",
                cite=(
                    "模块 docstring（与 PIER C 56 (2015) 式 (4) 同形态；"
                    "g 超可达上限显式拒绝——高频端单缝匹配不可达是公式行为"
                    "非缺陷，边界频率同节在档）"
                ),
            ),
            Formula(
                title="谐振（驻波）阵综合口径",
                latex=(
                    "g_n=g_{\\mathrm{total}}\\frac{w_n^2}{\\sum_i w_i^2},"
                    "\\quad d=\\frac{\\lambda_g}{2},\\quad "
                    "l_{\\mathrm{res}}\\approx\\frac{\\lambda_0}{2}"
                ),
                quote="各缝同相功率叠加口径 gn = g_total·wn²/Σw²",
                cite=(
                    "模块 docstring「谐振（驻波）阵综合」节（缝间距半导波波长"
                    "相邻交替换边保证同相、末缝后四分之一导波波长短路；理想"
                    "缝长口径的 kl≈π 假设显式化，实测缩短文献带附注）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="行波（非谐振）阵的",
                note=(
                    "族界：行波（非谐振）阵 Elliott 迭代综合、有限壁厚/缝宽"
                    "修正（实测曲线数字化不可自证）、窄壁斜缝表不在键面——"
                    "如实登记续作，不冒充已实现。"
                ),
            ),
            Boundary(
                quote="有限壁厚使 Stevenson 式**高估**电导——",
                note=(
                    "理想化偏差方向注记：有限壁厚使电导恒定高估（WR90 全波"
                    "标定在档，方向与 Oliner 变分处理一致）——修正不在键面。"
                ),
            ),
            Boundary(
                quote="0 ≤ x ≤ a/2（x=0 恰值接受输出 g=0 缝退化无扰动；x=a/2 恰值接受",
                note=(
                    "偏置域两恰值端点接受（零偏置退化缝/缝缘上限）；公式对 "
                    "偏置偶函数，负偏置取绝对值、相位符号由交替换边承担。"
                ),
            ),
            Boundary(
                quote="gn ≤ g_max（超限显式拒绝并提示降 g_total/收窄幅度锥度）。",
                note="单缝电导超可达上限显式拒绝并给出可行出路提示——不静默裁剪。",
            ),
        ),
        doc_refs=(
            DocRef(path="runs/aurora_c/batch_b_wave3_specs/G16_slot_array_stevenson_RESOLVED.md", quote="边界防撞（R7 §③ 三重搜索证据沿用规格包）",
                tracked=False,
            ),
            DocRef(
                path="tests/unit/test_b_wave3_yagi_slot.py",
                quote="（锚树 tests/unit/test_b_wave3_yagi_slot.py）。",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="stripline",
        tagline=(
            "对称带状线（零厚度）共形映射精确闭式：AGM 椭圆积分比无相消"
            "形态——宽带域 tanh 双精度饱和不再静默塌零，分析与综合双向"
            "（brentq 求逆+回代自洽保险带）。"
        ),
        modules=("calc_families/rf_line",),
        primary_entries=(
            ("calc_families/rf_line", "stripline_analysis"),
            ("calc_families/rf_line", "stripline_synthesis"),
        ),
        test_face_needles=("stripline_analysis", "stripline_synthesis"),
        formulas=(
            Formula(
                title="零厚度对称带状线精确闭式（Cohn 共形映射）",
                latex=(
                    "Z_0=\\frac{30\\pi}{\\sqrt{\\varepsilon_r}}"
                    "\\frac{K(k')}{K(k)},\\quad k=\\tanh\\frac{\\pi w}{2b},"
                    "\\quad K(k)=\\frac{\\pi}{2\\,\\mathrm{AGM}(1,k')}"
                ),
                quote="零厚度对称带状线共形映射精确解：Z0 = 30π/√εr · K(k')/K(k)。",
                quote2="k = tanh(πw/2b)；K(k)=π/(2·agm(1,k'))、K'(k)=π/(2·agm(1,k))（AGM 恒等式）",
                cite=(
                    "模块 docstring _stripline_z0（Cohn 椭圆积分共形映射精确解；"
                    "AGM 恒等式形态——比值无需 π，k'=sech(x) 直取避免相消）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="旧实现直调 scipy ellipk：w/b ≳ 12.1 后 tanh 双精度饱和（k≡1）→",
                note=(
                    "旧 ellipk 直调在宽带域 tanh 饱和致 Z0 静默返零（本仓审查"
                    "在档）——AGM 形态两式数学恒等、饱和域不塌（#333 同款"
                    "先例）。"
                ),
            ),
            Boundary(
                quote="（w=0 时 Z0→∞ 非有限静默透传，审查 R1-3）",
                note=(
                    "定义域守卫：线宽/板距非正与 εr<1 显式拒绝——退化极限"
                    "（细条高阻/宽带低阻）不做静默透传。"
                ),
            ),
            Boundary(
                quote="回代自洽保险带（A-18，siw_synthesis 同款形态）：brentq 解出的 w 回代",
                note=(
                    "综合回代自洽保险带：brentq 解回代正问题须复得目标阻抗，"
                    "保险带只在内核真坏（饱和域塌缩类）时触发；括号越界"
                    "显式报可达范围。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(path="runs/review_ge8e/r1_calculators/REPORT.md", quote="R1-1，内部证据档）；AGM 形态两式数学",
                tracked=False,
            ),
        ),
    ),
    CardSpec(
        kernel_id="suspended_stripline",
        tagline=(
            "悬置带线（基板居中对称填充）闭式：空气线共形电容比基准加 "
            "softmin 串联饱和修正族——平行份额式对中段 εeff 的系统性高估"
            "由拉普拉斯 FD 定标校正，两端点极限精确、全域单调性网格验证。"
        ),
        modules=("calc_families/rf_line",),
        primary_entries=(
            ("calc_families/rf_line", "suspended_stripline_analysis"),
            ("calc_families/rf_line", "suspended_stripline_synthesis"),
        ),
        test_face_needles=(
            "suspended_stripline_analysis",
            "suspended_stripline_synthesis",
        ),
        formulas=(
            Formula(
                title="εeff 结构式（softmin 串联饱和修正族）",
                latex=(
                    "\\varepsilon_{\\mathrm{eff}}=1+\\big(\\Delta^{-p}+D^{-p}"
                    "\\big)^{-1/p},\\quad \\Delta=(\\varepsilon_r-1)\\,\\tilde q,"
                    "\\quad Z_0=\\frac{Z_{0,\\mathrm{air}}(w,b)}"
                    "{\\sqrt{\\varepsilon_{\\mathrm{eff}}}}"
                ),
                quote="悬置带线（suspended substrate stripline，基板对称居中）闭式：(εeff, Z0)。",
                quote2="单调性：h↑ → εeff↑（严格，FD 域内 2001 点网格零违例），εeff∈[1, εr]。",
                cite=(
                    "模块 docstring _suspended_stripline_ri（结构式与修正常数"
                    "注记见同文件 SSL 常数块——介质份额实际沿场路径串联成分，"
                    "εr 升高时有效份额饱和下降，softmin 分母表达该饱和）"
                ),
                kind="口径示意（非 docstring 原式，读代码为准）",
            ),
            Formula(
                title="两支精确极限锚（定标不改变）",
                latex=(
                    "h\\to 0:\\ \\bigl(1,\\ Z_{0,\\mathrm{air}}\\bigr),"
                    "\\qquad h\\to b:\\ \\bigl(\\varepsilon_r,\\ "
                    "Z_{0,\\mathrm{full}}\\bigr)"
                ),
                quote="h→0 → 空气带状线 (1, _stripline_z0(w,b,1))；",
                quote2="h→b → 全填充 (εr, _stripline_z0(w,b,εr))。",
                cite=(
                    "模块 docstring（两支精确极限锚=零厚度对称带状线共形闭式 "
                    "_stripline_z0——空气线与全填充两支，两端点极限精确）"
                ),
            ),
            Formula(
                title="FD 重定标（quasistatic_fd 裁判）",
                latex=(
                    "\\tilde q=q\\cdot G(u,s),\\quad "
                    "D=D_0(1+u)^{d_1}\\bigl(4s(1-s)\\bigr)^{d_2},"
                    "\\quad p=p_0+p_1 s"
                ),
                quote="裸 q 式把介质份额按平行份额计，中段系统性高估（标称几何 +26%；",
                cite=(
                    "模块 docstring「FD 重定标」注记（裸平行份额式中段高估，"
                    "旧口径误表已撤；修正常数定标源、独立验证族精度与适用域"
                    "见 SSL 常数块注记；Z0 空气侧 Cohn 共形对拍未动）"
                ),
                kind="口径示意（非 docstring 原式，读代码为准）",
            ),
        ),
        boundaries=(
            Boundary(
                quote="u∈[0.1,1]、s∈[0.0625,0.9]、εr∈[1.5,12.9]；域外为外推（两端点极限仍精确、",
                note=(
                    "定标适用域外为外推（如实预声明）；两端点极限仍精确、"
                    "全域单调性经稠密网格验证零违例。"
                ),
            ),
            Boundary(
                quote="（基板不得越出接地板腔）",
                note="几何守卫：基板厚不得越出接地板腔（非负且不超腔高）——越界显式 ValueError。",
            ),
            Boundary(
                quote="悬置带线闭式定义域：w>0、b>0、εr≥1",
                note=(
                    "定义域与基板厚域两道显式守卫；极薄基板数值极限（份额"
                    "趋零）精确退化空气线，不做静默外推。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="scripts/fd_laplace_tline_referee.py",
                quote="复现：scripts/fd_laplace_tline_referee.py --refit-ssl-q）",
                tracked=True,
            ),
            DocRef(
                path="docs/rf_template_references.md",
                quote="出处（docs/rf_template_references.md §11）：",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="dipole",
        tagline=(
            "线天线/环输入阻抗族：有限长偶极辐射功率积分电阻+感应电动势法"
            "电抗经典闭式（谐振长度域内二分）、折合偶极两模并联（等粗谐振"
            "四倍阻抗恒等）与小环辐射电阻三式恒等+趋肤损耗/效率/Q——"
            "细线闭式档，矩量法曲线不在键面。"
        ),
        modules=("calc_families/linear_antenna_zin",),
        primary_entries=(
            ("calc_families/linear_antenna_zin", "dipole_emf_zin"),
            ("calc_families/linear_antenna_zin", "folded_dipole_zin"),
            ("calc_families/linear_antenna_zin", "small_loop_zin"),
        ),
        test_face_needles=(
            "dipole_emf_zin",
            "folded_dipole_zin",
            "small_loop_zin",
        ),
        formulas=(
            Formula(
                title="偶极输入电阻（正弦电流辐射功率积分）",
                latex=(
                    "R_{\\mathrm{in}}=\\frac{\\eta}{2\\pi\\sin^2(kh)}"
                    "\\int_0^{\\pi}\\frac{\\big(\\cos(kh\\cos\\theta)-\\cos kh"
                    "\\big)^2}{\\sin\\theta}\\,d\\theta"
                ),
                quote="R_in = η/(2π·sin²(kh))·∫₀^π [cos(kh·cosθ)−cos(kh)]²/sinθ dθ",
                cite=(
                    "模块 docstring「物理口径」节（对正弦电流分布假设精确的"
                    "功率积分路线，定精度确定式；短偶极渐近与半波教科书"
                    "常数双锚测试钉）"
                ),
            ),
            Formula(
                title="偶极输入电抗（感应电动势法经典闭式）",
                latex=(
                    "X=\\frac{\\eta}{4\\pi}\\Big\\{2\\,\\mathrm{Si}(kl)"
                    "+\\cos(kl)\\big[2\\,\\mathrm{Si}(kl)-\\mathrm{Si}(2kl)"
                    "\\big]-\\sin(kl)\\big[2\\,\\mathrm{Ci}(kl)-\\mathrm{Ci}(2kl)"
                    "-\\mathrm{Ci}(2ka^2/l)\\big]\\Big\\}"
                ),
                quote="X = (η/4π)·{2Si(kl) + cos(kl)·[2Si(kl)−Si(2kl)]",
                quote2="− sin(kl)·[2Ci(kl)−Ci(2kl)−Ci(2ka²/l)]}",
                cite=(
                    "模块 docstring（感应电动势法经典闭式，Balanis §8.4 "
                    "印刷形；谐振长度 X=0 域内二分与细线锚带同节）"
                ),
            ),
            Formula(
                title="折合偶极两模并联（天线模+传输线模）",
                latex=(
                    "Z_{\\mathrm{in}}=\\frac{4 Z_d\\cdot 2j Z_t\\tan(kl/2)}"
                    "{4 Z_d+2j Z_t\\tan(kl/2)},\\quad "
                    "Z_t=\\frac{\\eta}{\\pi}\\,\\mathrm{acosh}\\frac{s}{2a}"
                ),
                quote="Z_in = 4Z_d·(2jZ_t·tan(kl/2))/(4Z_d + 2jZ_t·tan(kl/2))",
                cite=(
                    "模块 docstring「折合偶极」节（Balanis 传输线法两模分解；"
                    "半波谐振处线模支路开路 → 阻抗为等效偶极四倍——等粗线径/"
                    "间距在谐振点约去=恒等锚）"
                ),
            ),
            Formula(
                title="小环输入阻抗分解（三式恒等+趋肤损耗）",
                latex=(
                    "R_r=320\\pi^4 N^2\\big(A/\\lambda^2\\big)^2"
                    "\\equiv 20\\pi^2 N^2(C/\\lambda)^4,\\quad "
                    "L=\\mu_0 b\\big[\\ln(8b/a)-2\\big],\\quad "
                    "Q=\\frac{X}{R_r+R_L}"
                ),
                quote="Rr = 320π⁴·N²·(A/λ²)²（A=πb²）≡ 20π²·N²·(C/λ)⁴（C=2πb）",
                quote2="L = μ0·b·[ln(8b/a) − 2]，X = 2πf·N²·L（密绕 N² 近似，匝间",
                cite=(
                    "模块 docstring「小环」节（面积/周长/数值三式恒等测试钉；"
                    "趋肤电阻损耗口径+Grover 单匝圆环电感闭式；Q 为输入阻抗"
                    "分解副产品，与天线 Q 面语义不同）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="守卫：length_mm ∈ (0, λ)（单瓣正弦电流假设域；l=λ 全波馈点电流节点",
                note=(
                    "单瓣正弦电流假设域内有效；全波馈点电流节点阻抗发散属"
                    "模型奇点显式拒绝——域外不外推。"
                ),
            ),
            Boundary(
                quote="为工程近似档（感应电动势法），精度不及矩量法。",
                note=(
                    "电抗闭式在半波点与归一重合、远离谐振区为工程近似档"
                    "（感应电动势法）——精度不及矩量法如实注记。"
                ),
            ),
            Boundary(
                quote="细偶极 King 数值逼近/矩量法曲线档不在本键口径（Sin-King 曲线的",
                note=(
                    "细偶极 King 数值逼近/矩量法曲线属经验档，如实不做——"
                    "电阻路线对正弦电流分布假设是精确积分（口径边界自明）。"
                ),
            ),
            Boundary(
                quote="不等线径 Mushiake 精确步升比不在本键口径",
                note=(
                    "折合偶极只做等线径档（谐振点线径/间距约去=恒等锚）；"
                    "不等线径 Mushiake 步升比不在键面，如实不做。"
                ),
            ),
            Boundary(
                quote="守卫（超出电小假设如实拒绝）。",
                note="小环电小判据守卫——超出电小假设如实拒绝，不外推。",
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_a3b_stub_antenna.py",
                quote="（aurora72 A3-B 席域 2，R7 第二梯队 T4）",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="helix",
        tagline=(
            "轴向模螺旋天线 Kraus 经验闭式注册面：性能/反设计/带宽三键薄"
            "包装（物理公式单源在内核根模块，本模块只注册不实现零复制）"
            "——经验域判定与失效域 verdict 由内核单一语义源透传。"
        ),
        modules=("calc_families/helix_axial_reg",),
        primary_entries=(
            ("calc_families/helix_axial_reg", "helix_axial_performance"),
            ("calc_families/helix_axial_reg", "helix_axial_design"),
            ("calc_families/helix_axial_reg", "helix_axial_bandwidth"),
        ),
        test_face_needles=(
            "helix_axial_performance",
            "helix_axial_design",
            "helix_axial_bandwidth",
        ),
        formulas=(
            Formula(
                title="Kraus 经验闭式（性能面）",
                latex=(
                    "\\mathrm{HPBW}=\\frac{52}{C_\\lambda\\sqrt{N S_\\lambda}},"
                    "\\quad \\mathrm{FNBW}=\\frac{115}{C_\\lambda\\sqrt{N S_\\lambda}},"
                    "\\quad Z_{\\mathrm{in}}\\approx 140\\,C_\\lambda\\ \\Omega"
                ),
                quote="物理公式单源在 ``rfauto.core.helix_axial``（B2 器件族批交付的 Kraus 闭式",
                quote2="（=140·C_λ 恒等）；AR(N=8)=1.0625（=1+1/2N）。",
                cite=(
                    "薄注册包装：公式零复制——Kraus 闭式常数（Balanis "
                    "§10.3.1 转引）单源在 rfauto.core.helix_axial；锚值与"
                    "阻抗/轴比恒等式见本模块 docstring（Balanis 工作例）"
                ),
                kind="口径示意（非 docstring 原式，读代码为准）",
            ),
            Formula(
                title="薄度守卫（wrapper 恒等）",
                latex="\\mathrm{wrapper}(x)\\equiv \\mathrm{core}(x)"
                      "\\ \\text{（逐字段逐位）}",
                quote="薄度守卫 = wrapper 输出与 core 直调逐位一致**",
                cite=(
                    "模块 docstring「薄注册纪律」节（wrapper 纯委托：参数"
                    "单位换算+字段映射，不做任何数值变换、不 round——"
                    "逐字段相等测试钉）"
                ),
                kind="口径示意（非 docstring 原式，读代码为准）",
            ),
        ),
        boundaries=(
            Boundary(
                quote="本模块**只注册不实现**，零公式复制（#116 死副本",
                note=(
                    "薄注册纪律：本模块只注册不实现、零公式复制（#116 死副本"
                    "教训——本地副本遮蔽 re-export 即死代码）。"
                ),
            ),
            Boundary(
                quote="§10.3.1 转引；有效域 0.75<C_λ<4/3、12°<α<14°、N>3 严格；锚树",
                note=(
                    "Kraus 经验域严格判定（周长波长比/螺距角/圈数三条件）"
                    "由内核侧透传——失效域内仍可计算但 verdict 带失效标记。"
                ),
            ),
            Boundary(
                quote="不自行判域。",
                note=(
                    "域判定/失效域警告/恰等出域 verdict 全部由内核侧原样"
                    "透传（单一语义源），本包装模块不自行判域。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_b_wave3_helix_reg.py",
                quote="（tests/unit/test_b_wave3_helix_reg.py 逐字段 ``==`` 钉）",
                tracked=True,
            ),
            DocRef(
                path="tests/unit/test_helix_axial.py",
                quote="tests/unit/test_helix_axial.py H1-H6 已 #118 合规在库——本席不重造",
                tracked=True,
            ),
            DocRef(path="runs/aurora_c/batch_b_wave3_specs/G17_helical_axial.md", quote="**薄注册纪律（规格包 内部证据档）**：",
                tracked=False,
            ),
        ),
    ),
    # ─── aurora_g W2-S3 内核卡批四（9 张；R2_core_tier4 §④ 卡批 A 全量 + W1-S2
    # 新核 2 族 + 测量/链路 A 组 2 族——照 W6-S22/W1-S3 纯 CALC 键族卡先例：
    # 注册键+docstring「物理口径/出处」节引文钉+锚树测试面 needles 三面齐备
    # （102 条引文预验探针 内部证据档 一次全命中）；
    # itu_link/link 为注册薄壳+纯函数内核双模块卡（主模块=注册面，同族模块
    # =内核面）；anchors/KD-1 零命中如实渲染）──
    CardSpec(
        kernel_id="link_limits",
        tagline=(
            "链路极限面：Shannon 容量与频谱效率恒等式、FSPL 真空基准闭式、"
            "Friis dB 形逐项可加链路账与余量——容量口径物理下界（极限 Eb/N0 面）"
            "的独立键位，环境统计路损模型显式端口化不并入本族。"
        ),
        modules=("calc_families/link_limits",),
        primary_entries=(
            ("calc_families/link_limits", "shannon_capacity"),
            ("calc_families/link_limits", "free_space_path_loss"),
            ("calc_families/link_limits", "link_margin_calc"),
        ),
        test_face_needles=(
            "shannon_capacity",
            "free_space_path_loss",
            "link_margin_calc",
        ),
        formulas=(
            Formula(
                title="Shannon 容量与频谱效率恒等式（AWGN 带限信道）",
                latex=(
                    "C=B\\,\\log_2(1+\\mathrm{SNR})\\ [\\mathrm{bps}],"
                    "\\quad \\eta=\\frac{C}{B}=\\log_2(1+\\mathrm{SNR})"
                    "\\ [\\mathrm{bit/s/Hz}]"
                ),
                quote="C = B·log2(1 + SNR)",
                quote2="η = C/B = log2(1 + SNR)",
                cite=(
                    "模块 docstring「公式口径」节（Cover & Thomas *Elements of "
                    "Information Theory* 2nd ed. ch.5；Shannon 1948/1949 原文"
                    "口径；SNR 线性/dB 双口径互斥显式择一同节）"
                ),
            ),
            Formula(
                title="容量极限 Eb/N0 反演面（Shannon 极限）",
                latex=(
                    "\\mathrm{Eb/N0}_{\\min}=\\frac{2^{\\eta}-1}{\\eta},"
                    "\\quad \\lim_{\\eta\\to 0}\\mathrm{Eb/N0}_{\\min}=\\ln 2"
                    "\\approx -1.5918\\ \\mathrm{dB}"
                ),
                quote="Eb/N0_min = (2^η − 1)/η",
                quote2="η→0 极限 = ln2 = −1.59175 dB（Shannon 极限，逐位锚）；η=1 → 0 dB、",
                cite=(
                    "模块 docstring（η=2 → 1.76091 dB 教科书点同段；输出物理"
                    "下界——实现调制需求面走 required_ebn0，margin=需求−极限"
                    "由调用方相减）"
                ),
            ),
            Formula(
                title="自由空间路损（Friis 1946 / ITU-R P.525 dB 形）",
                latex=(
                    "\\mathrm{FSPL}=\\left(\\frac{4\\pi d}{\\lambda}\\right)^2,"
                    "\\ \\lambda=\\frac{c}{f},\\quad"
                    "\\mathrm{FSPL}_{dB}=20\\lg(4\\pi d f/c)"
                ),
                quote="FSPL = (4πd/λ)²，λ = c/f",
                quote2="FSPL_dB = 20·lg(4πd·f/c)",
                cite=(
                    "模块 docstring（1km@1GHz=92.4478 dB、1m@1GHz=32.4478 dB "
                    "精确 SI 光速锚；教科书 32.44 常数形=c≈3e8 圆化口径差 "
                    "6.0mdB 如实；真空恒等式 20lg(d/λ)+20lg(4π) 随 identity "
                    "残差字段自检）"
                ),
            ),
            Formula(
                title="Friis dB 形逐项可加链路账与余量",
                latex=(
                    "P_r=P_t+G_t+G_r-\\mathrm{FSPL}_{dB}-L_{misc}"
                    "\\ [\\mathrm{dBm}],\\quad"
                    "\\mathrm{margin}=P_r-P_{sensitivity}\\ [\\mathrm{dB}]"
                ),
                quote="P_r = P_t + G_t + G_r − FSPL_dB − L_misc",
                quote2="margin = P_r − P_sensitivity",
                cite=(
                    "模块 docstring（与 Friis 线性式 P_r/P_t=G_t·G_r·(λ/4πd)² "
                    "逐位等价，10lg 换算恒等非近似；margin 恒等式随残差字段"
                    "自检；rfid_forward_link 前向链内嵌式同仓双源对拍钉）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="随输出 identity 残差字段自检。**环境修正不做预设档**（#1c 禁凭记忆",
                note=(
                    "环境（城市/室内）损耗以 excess_loss_db 显式加性端口透传，"
                    "不预设经验档——统计环境模型本体走 propagation.hata_cost231/"
                    "tr38901（边界防撞节）。"
                ),
            ),
            Boundary(
                quote="mimo.mimo_channel_capacity=矩阵容量 log₂det(I+γHH†)（本族只做标量",
                note=(
                    "边界防撞：mimo=矩阵容量+注水（本族只做标量链）、"
                    "required_ebn0=实现调制需求面（本族输出容量极限面，"
                    "margin 判读=需求−极限由调用方相减）、satellite/itu_link="
                    "卫星与气象细项、gt_ratio=G/T 优值——互指不互代。"
                ),
            ),
            Boundary(
                quote="- 链路账：d 加倍 → margin 精确 −6.0206 dB；灵敏度 +X dB → margin −X",
                note=(
                    "数值锚面（#118 独立来源）：d/f 加倍恒 +6.0205999 dB、"
                    "dB 双口径同参一致（<1e-12）、对 rfid_forward_link 同参"
                    "对拍 p_tag=P_r——锚树 tests/unit/test_w1s2_link_fec.py。"
                ),
            ),
            Boundary(
                quote="守卫：bandwidth_hz>0、SNR 线性值>0、snr_db ∈ (−∞, 3000]",
                note=(
                    "全部越界显式 ValueError（距离/频率>0、损耗/功率/增益/灵敏度"
                    "有限）；SNR 双口径同给=口径歧义显式拒绝；snr_db 上限="
                    "10**(db/10) 双精度溢出面收缩（W3-S1 审查 P3-3）。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w1s2_link_fec.py",
                quote="数值锚（#118 独立来源；锚树 tests/unit/test_w1s2_link_fec.py）",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="fec_codes",
        tagline=(
            "FEC 块码编码增益产生面：Hamming 完全码球填充界判定、RS MDS 纠错"
            "能力闭式与硬判 union bound 编码后 BER 反解的目标误码率净编码增益"
            "——coded_ber_estimate 输入参数（官方声明缺口）的产生面闭环。"
        ),
        modules=("calc_families/fec_codes",),
        primary_entries=(
            ("calc_families/fec_codes", "hamming_code_design"),
            ("calc_families/fec_codes", "reed_solomon_capacity"),
            ("calc_families/fec_codes", "coded_ebn0_requirement"),
        ),
        test_face_needles=(
            "hamming_code_design",
            "reed_solomon_capacity",
            "coded_ebn0_requirement",
        ),
        formulas=(
            Formula(
                title="Hamming 码参数与完全码球填充界",
                latex=(
                    "n=2^m-1,\\ k=n-m,\\ d_{\\min}=3,\\ t=1;\\quad"
                    "2^k\\sum_{i=0}^{t}\\binom{n}{i}\\le 2^n"
                ),
                quote="n = 2^m − 1，k = n − m，d_min = 3，t = ⌊(d_min−1)/2⌋ = 1",
                quote2="Hamming bound（球填充界）2^k·Σ_{i=0}^{t}C(n,i) ≤ 2^n：t=1 时",
                cite=(
                    "模块 docstring「公式口径」节（Hamming BSTJ 1950；"
                    "Lin & Costello 2nd ed. ch.3；n=2^m−1 全系完全码取等，"
                    "perfect 判定逐位整数算术零浮点）"
                ),
            ),
            Formula(
                title="RS MDS 纠错能力（Singleton 界取等）",
                latex=(
                    "d_{\\min}=n-k+1,\\quad t=\\left\\lfloor\\frac{n-k}{2}"
                    "\\right\\rfloor,\\quad 2e+f\\le n-k"
                ),
                quote="d_min = n − k + 1（Singleton 恒等式 n−k ≥ d_min−1 取等=MDS）",
                quote2="锚：RS(255,223)（GF(256)，NASA/CCSDS 标准码）d=33 → t=16 逐位。",
                cite=(
                    "模块 docstring（Reed & Solomon 1960；Singleton 1964 界"
                    "取等=MDS；e 错+擦除 f 并行纠正与连续突发保证最坏对齐口径"
                    "同节）"
                ),
            ),
            Formula(
                title="编码增益产生面（硬判 union bound 反解）",
                latex=(
                    "P_b\\le\\frac{1}{n}\\sum_{i=t+1}^{n} i\\binom{n}{i}"
                    "p^i(1-p)^{n-i},\\quad"
                    "G=\\gamma_b^{\\mathrm{unc}}-\\gamma_b^{\\mathrm{coded}}"
                    "(P_b{=}target)"
                ),
                quote="P_b ≤ (1/n)·Σ_{i=t+1}^{n} i·C(n,i)·p^i·(1−p)^(n−i)",
                quote2="G = γ_b^uncoded(target) − γ_b^coded(target)",
                cite=(
                    "模块 docstring「编码增益产生面」节（Lin & Costello 2ed / "
                    "Clark & Cain 1981 硬判 union bound 一阶口径；码率能量扩张后"
                    "信道原始误码率 p 单源复用 modulation_ber BER 闭式；P_b 对 "
                    "γ_b 单调降→dB 域二分反解）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="**诚实口径**：union bound 高估剩余误码 → G 为真增益的**保守下界估",
                note=(
                    "union bound 高估剩余误码→G 为保守下界估计（note+source "
                    "双写死）；瀑布区实际增益高于本口径，下界方向恒成立。"
                ),
            ),
            Boundary(
                quote="软判/打孔/交织/迭代译码（LDPC/Turbo 瀑布区）不在本面如实",
                note=(
                    "软判/迭代译码族如实不建模（UNVERIFIED 不凑）；d=1 恒等锚："
                    "k=n 退化档截断均值恒等还原二项均值→G≡0（精确到浮点）。"
                ),
            ),
            Boundary(
                quote="modulation_ber.coded_ber_estimate=G 的**消费面**（输入参数，docstring",
                note=(
                    "消费链握手：G 语义=码率扩张后信道上的增益——本键双口径显式"
                    "分列（净增益与回灌面差=码率扩张记账项，防双计）；G 回灌 "
                    "coded_ber_estimate 闭环复现 target（接线钉，物理量级由"
                    "独立实现互证另钉）。"
                ),
            ),
            Boundary(
                quote="守卫：parity_bits_m 整数 [2,16]；n_sym/k_sym 整数 0<k<n≤2^m−1；block_n",
                note=(
                    "整数守卫 bool 显式拒收；block_n 上沿 1020（1021–1024 的 "
                    "i·C(n,i) int→float 转换必 OverflowError，域收缩——W3-S1 "
                    "审查 P2-1）；t_correct 超 (n−k)/2 必要条件显式"
                    "拒绝（d_min≥2t+1 与 Singleton 上界联立）；反解端点不可解"
                    "显式拒绝（同 required_ebn0 口径）。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w1s2_link_fec.py",
                quote="数值锚（#118 独立来源；锚树 tests/unit/test_w1s2_link_fec.py）",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="directional_bridge",
        tagline=(
            "Wheatstone 电阻反射计桥器件面：三参考臂节点分析精确 S 矩阵"
            "（理想对称档直通/反射耦合、三口全匹配、方向性无穷）与反射计响应"
            "闭式（方向性-源匹配残差→被测 Γ 误差双界与回损测量链地板恒等式）。"
        ),
        modules=("calc_families/directional_bridge",),
        primary_entries=(
            ("calc_families/directional_bridge", "directional_bridge_s_matrix"),
            ("calc_families/directional_bridge", "directional_bridge_response"),
        ),
        test_face_needles=(
            "directional_bridge_s_matrix",
            "directional_bridge_response",
        ),
        formulas=(
            Formula(
                title="理想对称桥 S 矩阵（节点分析精确解）",
                latex=(
                    "\\mathbf S=\\begin{bmatrix}0&0.5&0\\\\0.5&0&-0.5\\\\"
                    "0&-0.5&0\\end{bmatrix}"
                ),
                quote="直通 6.02 dB（|S21|=0.5）、反射耦合 6.02 dB（|S32|=0.5，乘积",
                quote2="三口全匹配（S11=S22=S33=0——",
                cite=(
                    "模块 docstring「理想 S 矩阵闭式」节（对称四臂、端口 3 Z0 "
                    "端接；第 2 行功率和 0.25+0+0.25=0.5<1=臂电阻耗散 50%；"
                    "反射路径总预算=乘积 0.25；方向性 ∞=S31=0 机器精度）"
                ),
            ),
            Formula(
                title="反射计响应与归一去嵌",
                latex=(
                    "b_3/a_1=S_{31}+\\frac{S_{32}S_{21}\\Gamma}{1-S_{22}\\Gamma},"
                    "\\quad \\Gamma_{\\mathrm{meas}}=\\frac{\\Gamma}{1-\\Gamma s}+d"
                ),
                quote="b3/a1 = S31 + S32·S21·Γ/(1−S22·Γ)；按耦合积 k=|S32·S21| 归一去嵌：",
                quote2="Γ_meas = Γ/(1−Γ·s) + d",
                cite=(
                    "模块 docstring「反射计响应闭式」节（s=S22 源匹配误差项"
                    "二阶小量 |Γ²s|、d=S31/k 剩余方向性矢量 |d|=10^(−D/20)；"
                    "误差矢量相位未知→同相/反相双界如实报告）"
                ),
            ),
            Formula(
                title="完美负载回损地板（方向性恒等式）",
                latex=(
                    "|\\Gamma|=0\\Rightarrow RL_{\\mathrm{meas}}=D,\\quad"
                    "D\\to\\infty\\Rightarrow"
                    "\\Gamma_{\\mathrm{meas}}\\to\\frac{\\Gamma}{1-\\Gamma s}"
                ),
                quote="完美负载（Γ=0）读回损=D（方向性地板",
                quote2="同仓双源）；D→∞ 残差→0，只剩源匹配项 Γ/(1−Γs)；|Γ|≪1 单误差项",
                cite=(
                    "模块 docstring（与 vna_reflection_uncertainty 的回损地板="
                    "−directivity_db 同仓双源；Γ_meas≈Γ+d+s·Γ² 一阶展开=Rytting "
                    "单端口误差模型的器件级特例）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="multisection_coupler/bethe_hole/coupled_line=定向**耦合器**族（线",
                note=(
                    "边界防撞：multisection_coupler/bethe_hole/coupled_line="
                    "定向耦合器族（线耦合孔耦机构）、isolator_circulator=非互易"
                    "件——本族只做电阻桥反射计件（Wheatstone 平衡方向性机构）。"
                ),
            ),
            Boundary(
                quote="本族=两端口差分检波电阻桥器件面，语义不同域共存互指不互代；",
                note=(
                    "six_port=六端口反演架构（多端口功率检波干涉法）——本族可"
                    "为其供前级 S 矩阵，反演只在 six_port 层；vna_uncertainty="
                    "误差箱传播/不确定度面（本族的下游预算面）。"
                ),
            ),
            Boundary(
                quote="对称四臂 S 矩阵闭式为本席节点分析推导落地（键内对称档逐位自检，",
                note=(
                    "出处分级：对称四臂闭式=本席节点分析推导落地（键内对称档"
                    "自检+测试侧独立重算 #118）；Pozar Ch.12 反射计测量口径"
                    "二级转引如实标注。"
                ),
            ),
            Boundary(
                quote="守卫：z0_ohm>0；arm_tolerance_pct∈[0,0.2]（工程容差档，0=理想平衡）；",
                note=(
                    "容差档 arm_tolerance_pct 工程上限、gamma_mag∈[0,1]、"
                    "directivity_db>0 或 None=完美——越界一律显式 ValueError。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w2s6_mixer_bridge_switch.py",
                quote="定向电桥/反射计桥（aurora_f W2-S6 席域，R2_core_tier3 §③ D4 立项）。",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="rf_switch",
        tagline=(
            "射频开关器件面：PIN 串/并联元件导通/截止两态 S 参数与 cutoff "
            "品质因数、λ/4 并联二极管 SPDT 频响（开关带宽语义）、开关链二态"
            "插损/隔离 dB 可加预算与失配纹波界。"
        ),
        modules=("calc_families/rf_switch",),
        primary_entries=(
            ("calc_families/rf_switch", "pin_switch_s2p"),
            ("calc_families/rf_switch", "rf_switch_spdt_quarter_wave"),
            ("calc_families/rf_switch", "rf_switch_matrix_path"),
        ),
        test_face_needles=(
            "pin_switch_s2p",
            "rf_switch_spdt_quarter_wave",
            "rf_switch_matrix_path",
        ),
        formulas=(
            Formula(
                title="PIN 元件两态模型与 cutoff 品质因数",
                latex=(
                    "S_{21}^{\\mathrm{on}}=\\frac{2Z_0}{2Z_0+R_{\\mathrm{on}}},"
                    "\\quad S_{21}^{\\mathrm{off}}=\\frac{2Z_0}{2Z_0+1/j\\omega C_{\\mathrm{off}}},"
                    "\\quad f_c=\\frac{1}{2\\pi R_{\\mathrm{on}}C_{\\mathrm{off}}}"
                ),
                quote="导通（R_on）=直通态 S21=2Z0/(2Z0+R_on)、S11=R_on/(2Z0+",
                quote2="截止（C_off）=隔离态 S21=2Z0/(2Z0+1/jωC_off)——低频渐近",
                cite=(
                    "模块 docstring「PIN 元件两态模型」节（串联拓扑口径；并联"
                    "拓扑与 f_c=1/(2π·R_on·C_off) FOM 同节——R_on·C_off 乘积"
                    "单值标度，测试按乘积标度恒等钉）"
                ),
            ),
            Formula(
                title="λ/4 并联二极管 SPDT（switched line）",
                latex=(
                    "Z_{\\mathrm{in}}=Z_0\\frac{Z_L+jZ_0\\tan\\theta}"
                    "{Z_0+jZ_L\\tan\\theta},\\quad"
                    "\\theta=2\\pi f\\sqrt{\\varepsilon_{\\mathrm{eff}}}L/c"
                ),
                quote="Z_in(线)=Z0(Z_L+jZ0·tanθ)/(Z0+jZ_L·tanθ)，θ=2πf·√εeff·L/c",
                quote2="偏离 f0 时 tanθ 失谐→隔离/匹配退化（**开关带宽语义**：λ/4 线窄带",
                cite=(
                    "模块 docstring「λ/4 并联二极管 SPDT」节（选中臂截止=匹配、"
                    "非选中臂导通近短路经 λ/4 变换高阻挂结点；Pozar Ch.12 / "
                    "微波控制器件文献二级转引）"
                ),
            ),
            Formula(
                title="开关链二态预算（dB 可加与失配纹波界）",
                latex=(
                    "IL_{\\mathrm{tot}}=\\sum_i IL_i,\\quad"
                    "ISO_{\\mathrm{tot}}=\\sum_j ISO_j,\\quad"
                    "\\Delta\\le\\sum_i 20\\log_{10}(1+\\gamma_i\\gamma_{i+1})"
                ),
                quote="（ΣIL_dB——dB 域级联定义恒等式）；路径隔离=各离选支路隔离 dB 可加。",
                quote2="失配纹波界（教科书级联口径）：相邻端口对 γ_i、γ_{i+1} 交互最坏",
                cite=(
                    "模块 docstring「开关链二态预算」节（20log10(1+γ_iγ_{i+1}) "
                    "逐对叠加；吸收式=严格界、反射式=一阶近似 flag 如实透传）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="switch_pa_efficiency=开关**模 PA 效率**（D/E 类调制域）、phase_shifter",
                note=(
                    "边界防撞：switch_pa_efficiency=开关模 PA 效率、"
                    "phase_shifter switched_line=移相网络（态间相位差面）、"
                    "pa_arch pin_diode_limiter=限幅器、step_attenuator_design="
                    "步进衰减——本族只做 SPnT 开关器件级（插损/隔离/带宽口径）。"
                ),
            ),
            Boundary(
                quote="（离选臂内置 Z0 端接）无再反射——纹波界对吸收式为严格界，对反射式",
                note=(
                    "吸收式 vs 反射式语义：反射式离选臂把功率反射回源（二阶再"
                    "反射项本键不计如实注记）——纹波界对吸收式为严格界、对"
                    "反射式为一阶近似（flag 如实透传）。"
                ),
            ),
            Boundary(
                quote="rf 矩阵列换面（N×M 交叉点拓扑）不在本层——本键按路径元件列表面",
                note=(
                    "拓扑语义：矩阵列换面不在本层——路径预算按元件列表面消费"
                    "（可加性口径与拓扑无关）。"
                ),
            ),
            Boundary(
                quote="守卫：r_on_ohm>0、c_off_f>0、z0_ohm>0、频率>0；topology∈{series,shunt}；",
                note=(
                    "elements 表逐项 il_db/iso_db ≥0 且有限、γ∈[0,1)——越界一律"
                    "显式 ValueError。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w2s6_mixer_bridge_switch.py",
                quote="射频开关件面（aurora_f W2-S6 席域，R2_core_tier3 §③ D8 立项）。",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="kuroda_identities",
        tagline=(
            "Kuroda 恒等式：单位元与短截线四恒等式的两侧 ABCD 逐位精确等效"
            "变换（Pozar Table 8.7）与三阶低通原型 Richards 变换+恒等式两端化"
            "并联全链实现（Example 8.5 文献数值锚）。"
        ),
        modules=("calc_families/kuroda_identities",),
        primary_entries=(
            ("calc_families/kuroda_identities", "kuroda_identity_abcd"),
            ("calc_families/kuroda_identities", "kuroda_shunt_realize"),
        ),
        test_face_needles=("kuroda_identity_abcd", "kuroda_shunt_realize"),
        formulas=(
            Formula(
                title="网络基元 ABCD（commensurate 公共电长）",
                latex=(
                    "[\\mathrm{UE}]=\\begin{bmatrix}\\cos\\theta&jZ\\sin\\theta\\\\"
                    "j\\sin\\theta/Z&\\cos\\theta\\end{bmatrix},\\quad"
                    "Z_{\\mathrm{in}}^{short}=jZ\\tan\\theta,\\ "
                    "Z_{\\mathrm{in}}^{open}=-jZ\\cot\\theta"
                ),
                quote="λ/8@ωc 传输线 Z）[cosθ, jZ·sinθ; j·sinθ/Z, cosθ]；串联短路线段",
                quote2="四恒等式在**任意公共电长 θ**（commensurate）下两侧 ABCD 逐位相等",
                cite=(
                    "模块 docstring「物理口径」节（Pozar Table 4.1 基元同式；"
                    "§8.5 式 (8.79)-(8.80) 以 Ω=tanβℓ 因式分解的证明口径，"
                    "本族数值实现逐位复核）"
                ),
            ),
            Formula(
                title="四恒等式（Pozar Table 8.7，精确等效变换）",
                latex=(
                    "(a)\\,\\frac{[\\parallel stub][ue]}{\\text{左}}\\equiv"
                    "\\frac{[ue/n^2][\\text{串联短路}\\,ue/n^2]}{\\text{右}},"
                    "\\quad n^2=1+\\frac{Z_2}{Z_1}"
                ),
                quote="(a) [并联开路 stub] · [UE ue] ≡ [UE stub/n²] · [串联短路 ue/n²]，n²=1+stub/ue",
                quote2="(b) [串联短路 stub] · [UE ue] ≡ [UE n²·stub] · [并联开路 n²·ue]，n²=1+ue/stub",
                cite=(
                    "模块 docstring「四恒等式」节（行语义按 stub/ue 显式命名"
                    "消除错位、输出回显元素清单；(a)(b) 无变压器=串联↔并联、"
                    "开路↔短路双转换；(c)(d) 同型换位+变压器阻抗重整）"
                ),
            ),
            Formula(
                title="三阶低通全并联实现（Example 8.5 全链）",
                latex=(
                    "g\\to\\mathrm{Richards}(\\lambda/8@\\omega_c)"
                    "\\to+UE\\to(b)\\times 2\\to Z_0\\ \\mathrm{定标}"
                ),
                quote="文献数值锚（#122）：g=(3.3487, 0.7117, 3.3487)、Z₀=50Ω",
                quote2="→ 并联短截线 64.9/70.3/64.9Ω、连接线 217.5Ω（Pozar 图 8.36(e) 三位",
                cite=(
                    "模块 docstring「三阶低通全并联实现」节（本族精确值 "
                    "64.931/70.254/64.931/217.435，圆整窗 0.5% 内一致；"
                    "全链 ABCD 等价残差字段）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="- 全仓 grep（kuroda）src/tests 零命中（R2 §③ D9 附注同证）；本族为该域",
                note=(
                    "域首键：全仓 grep（kuroda）注册键面此前零命中——本族为该域"
                    "首批注册键（R2 §③ D9 附注同证）。"
                ),
            ),
            Boundary(
                quote="Richards 变换本体已在 core/stub_k_inverter.py（richards_omega/",
                note=(
                    "Richards 变换本体单源 core/stub_k_inverter（P.I. Richards "
                    "1948 同源）——本族不重复实现，仅输出 Ω=tan(θ) 映射值供"
                    "互查；stub_filter_design=短截线 BPF 综合不同对象。"
                ),
            ),
            Boundary(
                quote="一般 N 阶的级联恒等式迭代化实现不在本键（留续作，",
                note=(
                    "一般 N 阶的级联恒等式迭代化实现留续作——N=3 两端化="
                    "Pozar 原例口径如实声明（不冒充一般阶完备面）。"
                ),
            ),
            Boundary(
                quote="守卫：identity ∈{1,2,3,4}；z1/z2>0；θ∈(0,π) 且 sinθ≠0（θ=0/π 线段零",
                note=(
                    "θ=0/π 线段零长奇异显式拒绝；realize 键 g 须 3 元全正、"
                    "z0>0——越界一律显式 ValueError。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w4s14_core_edge.py",
                quote="Kuroda 恒等式族（aurora_f W4-S14 席域 2，R2_core_tier3 边际池立项）。",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="pll_lock_time",
        tagline=(
            "PLL 锁定/捕获时间：二阶 II 型环频率阶跃的线性锁定精确包络闭式与"
            "非线性 pull-in 近似档、lock-in/pull-out 范围档位判别——环路滤波器"
            "综合（ω_n/ζ 供给端）与相噪预算面之间的捕获动力学键。"
        ),
        modules=("calc_families/pll_lock_time",),
        primary_entries=(("calc_families/pll_lock_time", "pll_lock_time"),),
        test_face_needles=("pll_lock_time",),
        formulas=(
            Formula(
                title="误差传函与频率阶跃精确暂态（Gardner Ch.3）",
                latex=(
                    "E(s)=\\frac{s^2}{s^2+2\\zeta\\omega_n s+\\omega_n^2},"
                    "\\quad \\phi_e(t)=\\frac{\\Delta\\omega}{\\omega_d}"
                    "e^{-\\zeta\\omega_n t}\\sin(\\omega_d t),\\ "
                    "\\omega_d=\\omega_n\\sqrt{1-\\zeta^2}"
                ),
                quote="H(s)=(2ζω_n·s+ω_n²)/(s²+2ζω_n·s+ω_n²)，误差传函",
                quote2="ζ<1：φ_e(t)=(Δω/ω_d)·e^{−ζω_n t}·sin(ω_d t)，ω_d=ω_n√(1−ζ²)",
                cite=(
                    "模块 docstring「线性模型」节（Gardner Phaselock Techniques "
                    "Ch.3 标准形式；ζ=1 临界阻尼/ζ>1 双指数精确式同节；"
                    "II 型环频率阶跃稳态误差恒 0——终值定理，测试锚）"
                ),
            ),
            Formula(
                title="线性锁定时间（包络精确闭式）",
                latex=(
                    "t_{\\mathrm{lock}}=\\frac{\\ln\\big(\\Delta\\omega/"
                    "(\\varphi_{\\mathrm{tol}}\\,\\omega_d)\\big)}{\\zeta\\omega_n}"
                    "\\ (\\zeta<1),\\quad \\zeta\\ge 1\\ \\text{精确暂态二分求根}"
                ),
                quote="t_lock=ln(Δω/(φ_tol·ω_d))/(ζω_n)（ζ<1）；ζ≥1 对精确暂态二分求根",
                cite=(
                    "模块 docstring「线性锁定时间」节（包络口径精确闭式；"
                    "ζ≥1 对精确暂态二分求根=确定性，包络不适用如实声明）"
                ),
            ),
            Formula(
                title="捕获档（lock-in/pull-in/pull-out，近似与仿真档如实标）",
                latex=(
                    "\\Delta\\omega_L\\approx 2\\zeta\\omega_n,\\ "
                    "T_L\\approx\\frac{2\\pi}{\\omega_n},\\quad"
                    "T_P=\\frac{\\pi^2\\Delta\\omega_0^2}{16\\,\\zeta\\omega_n^3},"
                    "\\quad \\Delta\\omega_{PO}\\approx 1.8\\omega_n(\\zeta+1)"
                ),
                quote="高环路增益三滤波器统一 Δω_L≈2ζω_n；lock-in 时间 T_L≈1/f_n=2π/ω_n",
                quote2="T_P=(π²/16)·Δω₀²/(ζ·ω_n³)——近似档；文献锚（#122）：GT L060 例",
                cite=(
                    "模块 docstring「pull-in 时间」节（Best 4th ed. App.A/GT "
                    "L060 同式；文献例 f_n=3Hz、ζ=0.7、Δf=30Hz → T_P=4.675s "
                    "本键逐位复现窗 0.5%；pull-out=仿真经验档如实标）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="- pll_loop_filter=三阶环路滤波器**综合**（T1/T2/T3→元件值，ω_n/ζ 上游",
                note=(
                    "边界防撞：pll_loop_filter=滤波器综合（ω_n/ζ 上游供给端）、"
                    "pll_budget=相噪/抖动预算面、clock_noise=相噪谱积分——均"
                    "不做捕获动力学，边界互指见各模块 docstring。"
                ),
            ),
            Boundary(
                quote="档位判别**：|Δf|≤Δf_L=ζω_n/π → 线性档（t_lock 有效，无周期滑移）；",
                note=(
                    "档位判别三档：线性档（t_lock 有效）/非线性捕获档（t_lock "
                    "不适用如实标记报 T_P 近似）/超出 pull-out 档位提示（可能"
                    "失锁，II 型环仍可慢速拉入的定性注记）。"
                ),
            ),
            Boundary(
                quote="无环路增益输入时 pull-in 范围不判（II 型有源 PI 环",
                note=(
                    "无环路增益输入时 pull-in 范围不判（II 型有源 PI 环理论上 "
                    "Δω_P→∞，如实注记不虚构有限范围）。"
                ),
            ),
            Boundary(
                quote="守卫：fn_hz>0；zeta>0；df_hz≥0；tol_deg∈(0,180)；loop_gain 可选>0。",
                note="越界一律显式 ValueError（tol_deg 半相位窗开区间）。",
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w4s14_core_edge.py",
                quote="一键：pll_lock_time（二阶 II 型 PLL 频率阶跃的线性锁定时间精确包络闭式+",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="multisection_coupler",
        tagline=(
            "多节对称定向耦合器：二项式（中心最大平坦）与等纹波 Chebyshev "
            "两成员综合（结点权→节耦合→逐节偶/奇阻抗）与偶/奇模精确级联四端口"
            "频响——构造恒无耗互易、f0 隔离口精确零。"
        ),
        modules=("calc_families/multisection_coupler",),
        primary_entries=(
            ("calc_families/multisection_coupler", "multisection_coupler_binomial"),
            ("calc_families/multisection_coupler", "multisection_coupler_response"),
            ("calc_families/multisection_coupler", "multisection_coupler_equiripple"),
        ),
        test_face_needles=(
            "multisection_coupler_binomial",
            "multisection_coupler_response",
            "multisection_coupler_equiripple",
        ),
        formulas=(
            Formula(
                title="偶/奇模精确级联四端口构造（Pozar §7.6 同源）",
                latex=(
                    "S_{11}=\\tfrac{S_{e11}+S_{o11}}{2},\\ "
                    "S_{21}=\\tfrac{S_{e21}+S_{o21}}{2},\\ "
                    "S_{31}=\\tfrac{S_{e11}-S_{o11}}{2},\\ "
                    "S_{41}=\\tfrac{S_{e21}-S_{o21}}{2}"
                ),
                quote="S11=(Se11+So11)/2   S21=(Se21+So21)/2（直通）",
                quote2="S31=(Se11−So11)/2（耦合）   S41=(Se21−So21)/2（隔离）",
                cite=(
                    "模块 docstring「偶/奇模精确级联」节（偶/奇模各为 2 端口"
                    "级联链端接 Z0；该构造恒满足无耗 |S11|²+|S21|²+|S31|²+"
                    "|S41|²=1 与互易——测试钉）"
                ),
            ),
            Formula(
                title="单节精确闭式（N=1 退化裁判）",
                latex=(
                    "|S_{31}|=\\frac{c\\sin\\theta}{\\sqrt{1-c^2\\cos^2\\theta}},"
                    "\\quad c=\\frac{2g}{1+g^2},\\ "
                    "g=\\frac{Z_{0e}-Z_0}{Z_{0e}+Z_0},\\quad"
                    "|S_{31}(90^\\circ)|=c"
                ),
                quote="S31=Γe，|S31|=c·sinθ/√(1−c²cos²θ)，c=2g/(1+g²)、g=(Z0e−Z0)/(Z0e+Z0)",
                cite=(
                    "模块 docstring「单节精确闭式」节（Z0e·Z0o=Z0² 配对下 "
                    "Γ0o=−Γ0e 故 S31=Γe；θ=90° 处恰=c 精确非近似——f0 隔离口"
                    "精确零）"
                ),
            ),
            Formula(
                title="二项式结点权（中心最大平坦一阶小反射）",
                latex=(
                    "g(x)\\propto\\int_0^x(1-t^2)^M\\,\\mathrm{d}t="
                    "\\sum_k\\frac{(-1)^k\\binom{M}{k}}{2k+1}x^{2k+1}"
                ),
                quote="g(x) ∝ ∫₀ˣ(1−t²)^M dt = Σ_k (−1)^k·C(M,k)/(2k+1)·x^(2k+1)",
                quote2="三角分解解线性方程组即 Γ_i（N=3 → 结点比 1:9:9:1、节耦合比 1:10:1；",
                cite=(
                    "模块 docstring「二项式」节（N=2M+1 奇数节镜像对称；与 "
                    "sin 多项式按 x 奇次展开三角分解解线性方程组；电平归一对"
                    "精确偶/奇级联在 θ=90° 二分求根——f0 精确命中目标耦合）"
                ),
            ),
            Formula(
                title="等纹波成员与 (Z0e,Z0o) 配对闭式",
                latex=(
                    "Q_M(y)=1+\\varepsilon(-1)^M T_M(1-2y/Y),\\quad"
                    "Z_{0e}=Z_0\\sqrt{\\tfrac{1+c}{1-c}},\\ "
                    "Z_{0o}=Z_0\\sqrt{\\tfrac{1-c}{1+c}}"
                ),
                quote="multisection_coupler_equiripple（等纹波 Chebyshev 成员：Q_M=1+ε·T_M(1−",
                quote2="（Z0e=Z0√((1+c)/(1−c))、Z0o=Z0√((1−c)/(1+c))，恒 Z0e·Z0o=Z0²——该",
                cite=(
                    "模块 docstring（等纹波 Chebyshev 成员=Q_M 母多项式三角"
                    "分解，与二项式成员 flatness 语义分派字段；(Z0e,Z0o) 同 "
                    "core/slotline_transitions.even_odd_from_coupling 闭式，"
                    "配对性质给出 f0 隔离口精确零）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="- 全仓 grep（multisection|multi_section|levy|n_section.*coupl）注册键面",
                note=(
                    "域首键：全仓 grep 注册键面此前零命中（R7 G5 余量）；"
                    "synthesis.py synthesize_multisection_quarter_wave=λ/4 "
                    "阻抗变换器匹配域（同名非耦合器）不并入。"
                ),
            ),
            Boundary(
                quote="变换器**匹配**域（同名 multisection 非耦合器）；bethe_hole_coupler=",
                note=(
                    "边界防撞：bethe_hole_coupler=波导孔耦合单节综合、"
                    "coupled_line_bpf_*=带通谐振器实现（交叉口开路端接非直通 "
                    "4 口）——本族补多节级联直通四端口（单节=N=1 退化档互证）。"
                ),
            ),
            Boundary(
                quote="- 精确级联 vs 一阶：θ=90° |S31|−目标 ≤0.1dB（10dB/3 节档）；能量守恒",
                note=(
                    "数值锚面（#118 独立来源）：精确级联 vs 一阶口径差如实并列"
                    "报告（有限耦合二阶差 0.1–0.5dB 量级 @10dB 不隐藏）；能量"
                    "守恒残差 ≤1e-12 全频轴；|S31(90°−δ)| 对称残差 ≤1e-12。"
                ),
            ),
            Boundary(
                quote="守卫：n_sections 为正奇整数（≤15）；coupling_db∈(0,60]；逐节 c_i<0.99",
                note=(
                    "过耦不可实现显式拒绝；response 键列表同长 ≥1、Z0e>Z0o>0、"
                    "freq>0 且避开任一节 θ=kπ 奇异点（显式拒绝，"
                    "coupled_line_bpf_response 同口径）。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_a6b_multisection_gysel.py",
                quote="数值锚（#118 独立来源；锚树 tests/unit/test_a6b_multisection_gysel.py）",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="itu_link",
        tagline=(
            "ITU-R 大气/雨衰键面：P.676-13 逐线大气气体 specific attenuation、"
            "P.838-3 Gauss 和式雨衰减与 P.618-13 长期雨衰全链（逐中间量留痕）"
            "——系数表逐值录入并经官方 Table 5 全量频点对拍。"
        ),
        modules=("calc_families/itu_link", "itu_atmosphere"),
        primary_entries=(
            ("calc_families/itu_link", "gaseous_attenuation"),
            ("calc_families/itu_link", "rain_specific_attenuation"),
            ("calc_families/itu_link", "rain_attenuation_r001"),
        ),
        test_face_needles=(
            "gaseous_attenuation",
            "rain_specific_attenuation",
            "rain_attenuation_r001",
        ),
        formulas=(
            Formula(
                title="大气气体 specific attenuation（P.676-13 Annex 1 逐线求和）",
                latex=(
                    "\\gamma=0.1820\\,f\\,N''(f)\\ [\\mathrm{dB/km}],\\quad"
                    "N''=N''_{\\mathrm{Oxygen}}+N''_{\\mathrm{WaterVapour}}"
                ),
                quote="γ=0.1820·f·N″(f)；p_hpa 为干空气分压（总压 ptot=p+e）、θ=300/T、",
                quote2="逐线求和：O2 44 行+H2O 35 行谱线+干空气连续谱，式(1)-(9) 原文式号",
                cite=(
                    "模块 docstring（itu_atmosphere 式面已逐式对照官方 PDF "
                    "视觉核verify——Table 1 全 44 行+Table 2 全 35 行经 pypdf "
                    "机械抽取+前席 dump 553 值对拍 all-equal；有效域 "
                    "f∈(0,1000]GHz）"
                ),
            ),
            Formula(
                title="雨衰特征衰减（P.838-3 Gauss 和式）",
                latex=(
                    "\\gamma_R=k\\,R^{\\alpha}\\ [\\mathrm{dB/km}],\\quad"
                    "\\log_{10}k=\\textstyle\\sum_j a_j"
                    "e^{-\\left(\\frac{\\log_{10}f-b_j}{c_j}\\right)^2}"
                    "+m_k\\log_{10}f+c_k"
                ),
                quote="γ_R=k·R^α；式(2)/(3) Gauss 和式给 kH/kV/αH/αV，Tables 1-4 系数经官方",
                quote2="Table 5 全量 116 频点对拍 max rel dev 0.112%，证据 runs/ap8/）。",
                cite=(
                    "模块 docstring rain_specific_attenuation 键面（系数经官方 "
                    "Table 5 全量频点对拍=≤4 位有效数字印刷舍入界；pol 只收 "
                    "h/v 线极化直取档，插值式不注册）"
                ),
            ),
            Formula(
                title="长期雨衰全链（P.618-13 §2.2.1.1 Step1-9）",
                latex=(
                    "h_R=h_0+0.36,\\ "
                    "L_s=\\tfrac{h_R-h_s}{\\sin\\theta},\\ "
                    "r_{0.01}=\\tfrac{1}{1+0.78\\sqrt{L_G\\gamma_R/f}"
                    "-0.38(1-e^{-2L_G})},\\ "
                    "A_{0.01}=\\gamma_R L_E"
                ),
                quote="hR=h0+0.36→Ls（θ≥5° 式(1)/θ<5° 式(2)）→LG=Ls·cosθ→γR（P.838-3",
                quote2="r0.01 = 1/(1+0.78√(LG·γR/f)−0.38(1−e^{−2LG}))（式(5)）",
                cite=(
                    "模块 docstring（Step1-9 逐中间量留痕——l_s/l_g/γR/r0.01/"
                    "ζ/χ/ν0.01/L_E 全链对拍面；A0.01=γR·LE 式(7)；Step10 "
                    "Ap 换算纯辅助走 core.rain_attenuation_ap 组合消费）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="R0.01/h0 维持调用方显式输入（P.837/P.839 数字地图数据文件 PV-011 不捆",
                note=(
                    "数据面边界：P.837 雨率图与 P.839 冻结层高度均为 ITU 数字"
                    "地图数据文件（PV-011 不捆绑）——R0.01/h0 调用方显式输入，"
                    "本地实测/气象数据直接进链，公式面零数据依赖可用。"
                ),
            ),
            Boundary(
                quote="P.837 R0.01 系数仍 UNVERIFIED（ITU 数据",
                note=(
                    "rain_rate_r001_mmh 占位显式 ValueError 语义不变（P.837 "
                    "系数 UNVERIFIED 如实不建模——#122 如实口径）；"
                    "hR<=hs 或 R0.01=0 走原文零分支 a001_db=0+zero_reason。"
                ),
            ),
            Boundary(
                quote="pol 只收 'h'/'v'（线极化直取；任意仰角/倾角插值式(4)/(5) 不注册——",
                note=(
                    "极化域：任意仰角/倾角插值式（圆/线极化转换）不注册——"
                    "P.618 链路面只消费 h/v 直取档（链路面与插值面边界如实）。"
                ),
            ),
            Boundary(
                quote="由 core.rain_attenuation_ap 组合消费（sat_link 链路面）。",
                note=(
                    "输出 a001_db 后由 core.rain_attenuation_ap 组合消费"
                    "（sat_link 链路面）——本族只做键面收口，内核式面在 "
                    "core/itu_atmosphere（纯函数零 IO）。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_ap6_dr8_calculator_keys.py",
                quote="Tables 1-4 系数已由 AP-8 批逐值录入，验证链见该模块 docstring 与",
                tracked=True,
            ),
            DocRef(path="tests/unit/test_w4_c_p10_itu_p618.py", quote="出处（ITU-R 建议书原文逐值转写，系数录入验证链见 core/itu_atmosphere.py",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="link",
        tagline=(
            "G/T 组合优值（ITU-R S.733-2 定义口径）：T_sys 三路径显式择一"
            "（直接给定/级联总 NF 换算/y 因子链等效输入噪声温度）——"
            "cascade_budget 输出字段同名直连的接收优值键。"
        ),
        modules=("calc_families/link", "gt_link"),
        primary_entries=(("calc_families/link", "gt_ratio"),),
        test_face_needles=("gt_ratio",),
        formulas=(
            Formula(
                title="G/T 定义（ITU-R S.733-2 口径）",
                latex="G/T=G_{\\mathrm{dB}}-10\\lg(T_{\\mathrm{sys}})\\ [\\mathrm{dB/K}]",
                quote="（ITU-R S.733-2 定义口径）：G/T = G_dB − ",
                quote2="10·log10(T_sys) [dB/K]。T_sys 三路径显式择一：t_sys_k 直接给定 /",
                cite=(
                    "模块 docstring（ITU-R S.733-2 定义级引用；T0=290K IEEE "
                    "噪声温度基准与 nf_measurement.T0_K 同源同值）"
                ),
            ),
            Formula(
                title="T_sys 三路径（显式互斥择一）",
                latex=(
                    "T_{\\mathrm{sys}}=t_{\\mathrm{ant}}+T_e,\\quad"
                    "T_e=T_0(F-1)\\ (NF\\ \\text{路径}),\\quad"
                    "T_{\\mathrm{sys}}=t_{\\mathrm{ant}}"
                    "\\ (\\mathrm{antenna\\_only})"
                ),
                quote="nf_db（=cascade_budget.nf_total_db 直连，Te=T0·(F−1)）/ t_e_k",
                quote2="温度，三者全缺省时退化为 antenna_only（T_sys=t_ant_k，如实标注）。",
                cite=(
                    "模块 docstring「三条 T_sys 路径」节（直接给定/级联总 NF "
                    "换算/y 因子链等效输入噪声温度显式互斥选择；同给按优先级"
                    "取用并如实报告冗余）"
                ),
            ),
            Formula(
                title="消费面同名直连（级联输出即输入）",
                latex=(
                    "G/T\\leftarrow\\mathrm{cascade\\_budget}."
                    "(gain\\_total\\_db,\\ nf\\_total\\_db)"
                ),
                quote="（gain_total_db/nf_total_db）同名直连——级联面输出即本键输入。",
                cite=(
                    "模块 docstring（消费面设计：级联输出直接喂本键；Te 亦可"
                    "取自 nf_measurement.y_factor→te_from_y 链）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="边界语义：G/T 分母 T_sys>0 域守卫（T_sys≤0 显式 ValueError）；数值",
                note=(
                    "T_sys>0 域守卫（≤0 显式 ValueError）；数值合法性检查 "
                    "bool 显式拒收、有限数（0.0 合法）。"
                ),
            ),
            Boundary(
                quote="内核在 core/gt_link.py（纯函数零 IO），本模块只做注册薄壳",
                note=(
                    "薄注册纪律：内核在 core/gt_link（纯函数零 IO），本模块只"
                    "注册不实现、零公式复制（同 exposure_limits/t_match 惯例）。"
                ),
            ),
            Boundary(
                quote="（定义级引用；数值锚=恒等式回收，见 tests/unit/test_gt_link_calculators.py）。",
                note=(
                    "数值锚=恒等式回收（T_sys 路径往返/G−10lgT 恒等），非文献"
                    "转引数值——定义级引用如实标注，锚树见判据书指针。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(path="tests/unit/test_gt_link_calculators.py", quote="出处（出处逐字见内核 core/gt_link.py docstring——本模块只做注册薄壳）：",
                tracked=True,
            ),
        ),
    ),
    # ─── aurora_g W3-S3 内核卡批五（2026-10-19，R2_core_tier4 §③ 新核
    # 三族 C3/C4/C6 落地族 + §④ 卡批 C 波导族三卡）——照 W2-S3 纯 CALC
    # 键族卡先例：注册键+docstring「物理口径/出处」节引文钉+锚树测试面
    # needles 三面齐备（68 条引文预验探针 内部证据档
    # 一次全命中）；anchors/KD-1 零命中如实渲染 ──
    CardSpec(
        kernel_id="dgs",
        tagline=(
            "哑铃形缺陷接地结构面：陷波/截止双条件反演一阶等效电感电容与"
            "陷波响应逐频再生（同文件双路径闭环）——全仓最后一个零命中 "
            "PCB 器件域的首批键位，几何经验拟合面如实留白待文献复读。"
        ),
        modules=("calc_families/dgs",),
        primary_entries=(
            ("calc_families/dgs", "dgs_dumbbell_lc_extract"),
            ("calc_families/dgs", "dgs_notch_response"),
        ),
        test_face_needles=("dgs_dumbbell_lc_extract", "dgs_notch_response"),
        formulas=(
            Formula(
                title="哑铃 DGS 一阶等效提取（陷波+3dB 两条件联立）",
                latex=(
                    "C=\\frac{2(\\omega_0^2-\\omega_c^2)}"
                    "{Z_0\\omega_0^2\\omega_c}"
                    "=\\frac{2}{Z_0\\omega_c}\\left(1-\\frac{\\omega_c^2}"
                    "{\\omega_0^2}\\right),\\quad"
                    "L=\\frac{1}{\\omega_0^2 C}"
                    "=\\frac{Z_0\\omega_c}{2(\\omega_0^2-\\omega_c^2)}"
                ),
                quote="C = 2(ω0² − ωc²)/(Z0·ω0²·ωc) = (2/(Z0·ωc))·(1 − (ωc/ω0)²)",
                quote2="L = 1/(ω0²·C) = Z0·ωc/(2(ω0² − ωc²))",
                cite=(
                    "模块 docstring「物理口径」节（陷波条件 X(ω0)=0 与 3dB "
                    "条件 |X(ωc)|=Z0/2 由无损并联元件传输式令 =1/2 解出——"
                    "第一性推导联立；文献族口径 Lim/Ahn IEEE MTT 2000-2002，"
                    "UNVERIFIED 如实预声明）"
                ),
            ),
            Formula(
                title="陷波/低通响应再生（同文件双路径）",
                latex=(
                    "|S_{21}(f)|=\\frac{2|X|}{\\sqrt{Z_0^2+4X^2}},"
                    "\\quad X(f)=2\\pi fL-\\frac{1}{2\\pi fC}"
                ),
                quote="|S21(f)| = 2|X|/√(Z0²+4X²)",
                quote2="X(f)=2πfL − 1/(2πfC)",
                cite=(
                    "模块 docstring「响应再生」节（低频 X→−∞ 直通、f=f0 全"
                    "陷波、f=fc 恰 −3.0102999dB 构造恒等式；extract→response "
                    "roundtrip #118 同文件双路径）"
                ),
            ),
            Formula(
                title="两条提取条件（第一性推导源）",
                latex=(
                    "X(\\omega_0)=0\\ \\left(\\omega_0=\\frac{1}{\\sqrt{LC}}"
                    "\\right),\\quad"
                    "|S_{21}|^2=\\frac{4X^2}{Z_0^2+4X^2}=\\frac{1}{2}"
                    "\\ \\Rightarrow\\ |X(\\omega_c)|=\\frac{Z_0}{2}"
                ),
                quote="X(ω0) = 0 ⇔ ω0 = 1/√(LC)",
                quote2="|S21|² = 4X²/(Z0²+4X²) 令 =1/2 解出",
                cite=(
                    "模块 docstring「物理口径」节（并联支路 Z_g(jω)=jX(ω) "
                    "串联回路面；X(ωc)=−Z0/2 与 ω0²=1/(LC) 回代残差随输出"
                    "自检）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="记忆写式；文献原文页码级复读未做，如实登记 UNVERIFIED——同",
                note=(
                    "出处分级（#122）：两条件联立=第一性推导（构造恒等式锚）"
                    "，文献族口径 Lim/Ahn IEEE MTT 2000-2002 原文页码级复读"
                    "未做 UNVERIFIED 如实登记（circulator_synthesis "
                    "Wu-Rosenbaum 先例同口径）。"
                ),
            ),
            Boundary(
                quote="几何→LC 的经验拟合式（哑铃边长/槽缝宽 → L/C 的文献拟合族）不做（#1c",
                note=(
                    "几何面留白：哑铃边长/槽缝宽→L/C 的文献拟合经验常数不入"
                    "键面（#1c 禁凭记忆写经验常数）——f0/fc 由调用方 EM 提取"
                    "供给（真机仲裁链）。"
                ),
            ),
            Boundary(
                quote="- vendor_passives=器件级 RLC（磁珠/电容 ESR 模型）——本族=地面缺陷结构",
                note=(
                    "边界防撞：vendor_passives=分立器件、homogenization=体"
                    "超材料、amc_mushroom=表面型 EBG、crlh=周期单元阵列——"
                    "本族=离散地面缺陷单元；慢波等效面 R2 预声明登记不建模"
                    "如实留白。"
                ),
            ),
            Boundary(
                quote="自洽性：ω0 > ωc（陷波在截止之上）时 C>0、L>0 恒成立；f0 ≤ f3db 时",
                note=(
                    "模型自洽守卫：f0≤f3db 时支路呈感性无低通语义显式拒绝；"
                    "dB 输出对理想全陷波取 −300dB 地板+below_floor 旗标"
                    "（JSON 严格序列化禁 inf 信封契约）；全键越界显式 "
                    "ValueError。"
                ),
            ),
            Boundary(
                quote="守卫：f0_ghz/f3db_ghz/z0_ohm>0 且 f0>f3db；l_nh/c_pf>0；freq_ghz 列表",
                note=(
                    "数值锚面（#118 独立算术）：(2.4GHz, 1.8GHz, 50Ω) → "
                    "C=1.5473pF、L=2.8421nH 逐位；X(ωc)=−Z0/2 与 ω0²=1/(LC) "
                    "回代残差 ~1e-16；无耗 |S21|≤1 全扫描——锚树判据书。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w2s2_core_tier4.py",
                quote="tests/unit/test_w2s2_core_tier4.py）",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="if_digitizer",
        tagline=(
            "测量接收机中频数字化面：带通采样可行区间规划（区号/最小采样率"
            "/推荐点折叠像与两端保护带）与候选采样率混叠折叠核验三态判定——"
            "噪声合成面与杂散落带面两邻之间的采样规划半边。"
        ),
        modules=("calc_families/if_digitizer",),
        primary_entries=(
            ("calc_families/if_digitizer", "bandpass_sampling_plan"),
            ("calc_families/if_digitizer", "alias_fold_check"),
        ),
        test_face_needles=("bandpass_sampling_plan", "alias_fold_check"),
        formulas=(
            Formula(
                title="带通采样可行区间（VSW 1991 不等式）",
                latex=(
                    "m=1:\\ f_s\\ge 2f_H,\\quad"
                    "m\\ge 2:\\ \\frac{2f_H}{m}\\le f_s\\le"
                    "\\frac{2f_L}{m-1},\\quad"
                    "m=1..M,\\ M=\\lfloor f_H/BW\\rfloor"
                ),
                quote="2·f_H/m ≤ fs ≤ 2·f_L/(m−1)",
                quote2="最小可行采样率 = 2·f_H/M（最高区号档）。",
                cite=(
                    "模块 docstring「物理口径」节（Vaughan-Scott-White 1991 "
                    "IEEE Trans. SP 39(9) 带通采样定理；区间非空 ⇔ m ≤ f_H/BW "
                    "与 M 上界自洽；m=1 基带退化档 fs≥2f_H 无上界同节）"
                ),
            ),
            Formula(
                title="混叠折叠恒等式与防混叠判据",
                latex=(
                    "f'\\equiv\\left|f-\\mathrm{round}\\!\\left("
                    "\\frac{f}{f_s}\\right)f_s\\right|\\in"
                    "\\left[0,\\frac{f_s}{2}\\right],\\quad"
                    "\\text{无混叠}\\Leftrightarrow[f_L,f_H]"
                    "\\text{ 不跨 }kf_s/2\\text{ 边界}"
                ),
                quote="f' ≡ |f − round(f/fs)·fs| ∈ [0, fs/2]",
                quote2="混叠不发生 ⇔ [f_L, f_H] 不跨越任何 k·fs/2 边界。三态判定（如实三分，",
                cite=(
                    "模块 docstring（折叠恒等式第一性逐频严格成立；三态 "
                    "alias_free_strict/boundary_touching/alias_overlap 如实"
                    "三分，#122 不凑绿口径）"
                ),
            ),
            Formula(
                title="孔径抖动 SNR 消费面（单源复用）",
                latex=(
                    "\\mathrm{SNR}_{\\mathrm{jitter}}=-20\\lg"
                    "\\left(2\\pi f_{\\mathrm{in}}\\sigma_j\\right),"
                    "\\quad f_{\\mathrm{in}}=f_H"
                    "\\ (\\text{模拟最高频率})"
                ),
                quote="孔径抖动 SNR 直接消费 adc_budget.snr_jitter_db 同式（MT-007 口径",
                quote2="−20lg(2π·f_in·σ_j)；f_in 取模拟输入最高频率 f_H——欠采样 ADC 的 dv/dt",
                cite=(
                    "模块 docstring（导入复用零公式复制——欠采样 ADC 的 dv/dt "
                    "由模拟频率决定非折叠后 IF；σ_j=0 → inf 以旗标透出，"
                    "JSON 禁 inf）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="boundary_touching ：带缘恰落 k·fs/2（零保护带理论点，fs 微扰即混叠，",
                note=(
                    "三态如实：alias_free_strict=严格单区内（保护带 >0）、"
                    "boundary_touching=零保护带理论点不判绿（fs 微扰即混叠）"
                    "、alias_overlap=真实混叠拒绝；m=M 档两端相等即边界触碰"
                    "档如实标注。"
                ),
            ),
            Boundary(
                quote="- adc_budget=ADC 噪声合成面（孔径抖动/量化/kTC+ENOB）——本族=采样规划",
                note=(
                    "边界防撞：adc_budget=噪声合成面（规划键出 f_H、噪声键给 "
                    "SNR 消费衔接）、budget.if_plan_sweep=混频杂散落带面、"
                    "cispr_detector=EMC 检波、cdr_jitter_mask=SI 抖动——本族"
                    "只做采样/折叠区规划（抗混叠滤波器设计不在口径）。"
                ),
            ),
            Boundary(
                quote="- fs=54MHz（m=3 档内点）→ 原带居第 3 Nyquist 区（54–81MHz），折叠像",
                note=(
                    "数值锚面（#118 独立算术）：fc=70MHz/BW=20MHz → M=4 区；"
                    "fs=54MHz 折叠像 [6,26]MHz 保护带 6/1MHz；fs=40MHz 边界"
                    "触碰、fs=50MHz 跨界混叠三态齐验；VSW 区号回查逐档对拍——"
                    "锚树判据书。"
                ),
            ),
            Boundary(
                quote="守卫：f_center_hz>BW/2（f_L>0）、bw_hz>0、fs_hz>0、sigma_jitter_s≥0；",
                note=(
                    "全键越界显式 ValueError（f_L≤0 非物理拒绝）；bool 入参"
                    "显式拒收（_finite_nb，fec_codes._as_int 同族先例——"
                    "W3-S1 审查 P3-2）。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w2s2_core_tier4.py",
                quote="tests/unit/test_w2s2_core_tier4.py）",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="wg_dielectric_window",
        tagline=(
            "矩形波导介质窗（真空密封窗介质形态）：介质片半波长全传输谐振"
            "设计与给定厚度核验双档、逐频扫描带宽面——与薄膜片谐振窗成族"
            "补全阻抗变换/电纳对消两口径。"
        ),
        modules=("calc_families/wg_dielectric_window",),
        primary_entries=(
            ("calc_families/wg_dielectric_window", "wg_dielectric_window"),
        ),
        test_face_needles=("wg_dielectric_window",),
        formulas=(
            Formula(
                title="TE10 介质片传播面（空气段/介质段）",
                latex=(
                    "\\beta_a=\\frac{2\\pi f}{c}"
                    "\\sqrt{1-(f_c/f)^2},\\quad"
                    "\\beta_d=\\frac{2\\pi f}{c}"
                    "\\sqrt{\\varepsilon_r-(f_c/f)^2},\\quad"
                    "\\frac{Z_d}{Z_a}=\\frac{\\beta_a}{\\beta_d}"
                    "=\\frac{\\lambda_{g,\\mathrm{slab}}}"
                    "{\\lambda_{g,\\mathrm{air}}}"
                ),
                quote="β_d = (2πf/c)·√(εr − (fc/f)²)",
                quote2="λg,air = 2π/β_a，λg,slab = 2π/β_d",
                cite=(
                    "模块 docstring「物理口径」节（TE 模阻抗 Z_TE=ωμ/β → "
                    "阻抗比=λg 比同 μ 口径，与工作频率无关；介质填充只改 β "
                    "与 Z_TE、截止形状同）"
                ),
            ),
            Formula(
                title="半波长全传输谐振（双界面反射对消）",
                latex=(
                    "\\Gamma_{\\mathrm{in}}=\\Gamma_{01}"
                    "\\frac{1-e^{-2j\\beta_d t}}"
                    "{1-\\Gamma_{01}^2 e^{-2j\\beta_d t}},\\quad"
                    "\\beta_d t=m\\pi\\ "
                    "(t=m\\lambda_{g,\\mathrm{slab}}/2)"
                    "\\ \\Rightarrow\\ \\Gamma_{\\mathrm{in}}=0"
                ),
                quote="Γ_in = Γ01·(1 − e^{−2jβ_d t})/(1 − Γ01²·e^{−2jβ_d t})",
                quote2="β_d·t = mπ（t = m·λg,slab/2，m=1,2,...）时 e^{−2jβ_d t} = 1 → Γ_in = 0",
                cite=(
                    "模块 docstring（界面反射 Γ01=(Z_d−Z_a)/(Z_d+Z_a)；"
                    "半波长段 ABCD=[−1,0;0,−1] 与恒等矩阵仅差符号——构造级"
                    "恒等式；设计档取最薄阶 m_order=1 工程惯例）"
                ),
            ),
            Formula(
                title="传输系数与能量守恒",
                latex=(
                    "S_{21}=\\frac{(1-\\Gamma_{01}^2)e^{-j\\beta_d t}}"
                    "{1-\\Gamma_{01}^2 e^{-2j\\beta_d t}},\\quad"
                    "|S_{11}|^2+|S_{21}|^2=1"
                ),
                quote="构造级恒等式）；传输系数 S21 = (1−Γ01²)·e^{−jβ_d t}/(1−Γ01²·e^{−2jβ_d t})",
                quote2="（无损，|S11|²+|S21|²=1 恒等式随 residual 字段自检）。",
                cite=(
                    "模块 docstring（无损口径能量守恒随 residual 字段自检；"
                    "λ/4 厚度档 |Γ_in|=(Z_d²−Z_a²)/(Z_d²+Z_a²) 变换器反射"
                    "闭式独立路线对拍锚）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="- waveguide_iris.wg_resonant_window=感/容薄膜片组合谐振窗（电纳对消",
                note=(
                    "成族边界：wg_resonant_window=电纳对消口径膜片型窗——"
                    "本键=阻抗变换口径介质段半波长谐振，两形态互指成族不并；"
                    "waveguide_closed_form=模谱、rwg_mmt=数值模匹配仲裁路径"
                    "（本键=工程闭式档）。"
                ),
            ),
            Boundary(
                quote="退化自检：εr=1 → Z_d=Z_a → Γ01=0 → 任意 t 全直通（无窗退化档，如实",
                note=(
                    "εr=1 无窗退化档全直通如实输出不拒绝、εr<1 非物理显式"
                    "拒绝；verify 档残余反射如实不凑零；无损口径复 εr/材料"
                    "损耗项不在键面。"
                ),
            ),
            Boundary(
                quote="- multipactor=介质窗倍增放电面（其 docstring 边界注记即本键的下游不",
                note=(
                    "multipactor 倍增放电面不在本键（其 docstring「介质窗 "
                    "multipactor 未建模」边界注记=本键的下游不覆盖声明）——"
                    "本键只做窗传输设计；平板介质谐振器/天线罩语义不并入。"
                ),
            ),
            Boundary(
                quote="守卫：a_mm>0；f_ghz>TE10 截止（空气段传播守卫）；eps_r≥1（=1 无窗退",
                note=(
                    "空气段截止以下无传播显式拒绝（窗谐振语义失效）；m_order"
                    "≥1 整数、t_mm>0；数值锚 WR-90/10GHz/εr=2.2 逐位+t=λg/4 "
                    "对拍 λ/4 变换器闭式（#118 锚树判据书）——越界一律显式 "
                    "ValueError。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w2s2_core_tier4.py",
                quote="tests/unit/test_w2s2_core_tier4.py）",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="waveguide_closed_form",
        tagline=(
            "波导/腔体任意模式闭式谱：圆柱腔与矩形腔谐振谱、模式图主模切换"
            "交叉点二分求根、任意模式无载 Q 闭式与数值积分双路线互证——"
            "腔体微扰测量与材料提取面的上游模式谱供给。"
        ),
        modules=("calc_families/waveguide_closed_form",),
        primary_entries=(
            ("calc_families/waveguide_closed_form", "circular_cavity_mode_spectrum"),
            ("calc_families/waveguide_closed_form", "circular_cavity_mode_chart"),
            ("calc_families/waveguide_closed_form", "circular_cavity_mode_q"),
            ("calc_families/waveguide_closed_form", "circular_waveguide_mode_prop"),
            ("calc_families/waveguide_closed_form", "rectangular_cavity_mode_spectrum"),
            ("calc_families/waveguide_closed_form", "rectangular_cavity_mode_q"),
        ),
        test_face_needles=(
            "circular_cavity_mode_spectrum",
            "circular_cavity_mode_chart",
            "circular_cavity_mode_q",
            "circular_waveguide_mode_prop",
            "rectangular_cavity_mode_spectrum",
            "rectangular_cavity_mode_q",
        ),
        formulas=(
            Formula(
                title="圆柱腔 TE/TM_mnp 谐振谱（Bessel 零点闭式）",
                latex=(
                    "f_{\\mathrm{TE}_{mnp}}=\\frac{c_0}{2\\pi"
                    "\\sqrt{\\varepsilon_r}}"
                    "\\sqrt{\\left(\\frac{x'_{mn}}{a}\\right)^2"
                    "+\\left(\\frac{p\\pi}{L}\\right)^2},\\quad"
                    "f_{\\mathrm{TM}_{mnp}}=\\frac{c_0}{2\\pi"
                    "\\sqrt{\\varepsilon_r}}"
                    "\\sqrt{\\left(\\frac{x_{mn}}{a}\\right)^2"
                    "+\\left(\\frac{p\\pi}{L}\\right)^2}"
                ),
                quote="TE_mnp: f = c₀/(2π√εr)·√((x'_mn/a)² + (pπ/L)²)   x'_mn = J_m'(x)",
                quote2="TM_mnp: f = c₀/(2π√εr)·√((x_mn/a)² + (pπ/L)²)    x_mn = J_m(x)",
                cite=(
                    "模块 docstring「物理口径」节（Pozar Microwave Engineering "
                    "§6.4 圆柱腔/Collin；TE 的 p≥1——p=0 时 E_t≡0 非物理显式"
                    "拒绝、TM 的 p≥0 允许 TM010 经典例）"
                ),
            ),
            Formula(
                title="主模判据与模式图交叉点",
                latex=(
                    "\\frac{l}{2a}=\\frac{\\pi}{2\\sqrt{x_{01}^2-x'^2_{11}}}"
                    "\\approx 1.0154"
                    "\\ (\\text{TM010}/\\text{TE111 主模切换交叉})"
                ),
                quote="主模判据（计算判读非假定）：全谱最低频模式。经典口径 l<2a → TM010、",
                quote2="l>2a → TE111，交叉长径比 l/2a = π/(2·√(x_01²−x'_11²)) ≈ 1.0154",
                cite=(
                    "模块 docstring（模式图=归一化频率-长径比曲线族，主模切换"
                    "点在相邻网格间二分求根——交叉点为模式图键输出、测试侧"
                    "独立常数式钉）"
                ),
            ),
            Formula(
                title="无载 Q：闭式与数值积分双路线互证",
                latex=(
                    "Q_c=\\frac{\\omega U}{P_c},\\quad"
                    "Q_{c,\\mathrm{TM010}}=\\frac{\\eta k_0 a}{2R_s}"
                    "\\cdot\\frac{L}{L+a},\\quad"
                    "\\frac{1}{Q_u}=\\frac{1}{Q_c}+\\frac{1}{Q_d}"
                ),
                quote="TM010 极限（测试钉，测试侧独立重算）：Qc = (η·k0·a/2Rs)·L/(L+a)",
                quote2="等式）——q_xcheck_rel_dev 应为 quad 精度级（<1e-9），双路线失配即",
                cite=(
                    "模块 docstring（导体微扰 Q=ωU/P_c，Pozar §6.4/Collin "
                    "微扰法本席从场表达式独立推导；数值路线 "
                    "scipy.integrate.quad 不消费 Bessel 恒等式——双路线失配即"
                    "推导有误的显式证据；介质 Q=1/tanδ 串联合成同 "
                    "cavity_unloaded_q 口径）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="它们的**上游模式谱供给**（先定模式再提取）；TE011 空腔频率与",
                note=(
                    "上游语义：cavity/cavity_perturbation_shift=腔体微扰测量"
                    "面、material_characterization=分裂腔/Courtney 材料提取面"
                    "——本族是它们的模式谱供给（TE011 空腔频率与其 "
                    "_sc_empty_f0 同仓双源测试互证）；rwg_mmt=模基 GSM 数值、"
                    "rw_tables=EIA 尺寸表、combline=同轴腔 TEM 单模不并入。"
                ),
            ),
            Boundary(
                quote="第 n 个正零点（m≥0, n≥1, p≥1——p=0 时 E_t≡0 非物理，显式拒绝）",
                note=(
                    "模阶域守卫：TE 的 p≥1（p=0 非物理）、TM 的 p≥0 允许"
                    "（TM010 经典例）；模式名白名单解析（形如 'TE011'/"
                    "'TM010'，类型+mnp 三位数字），非法/越界显式拒绝。"
                ),
            ),
            Boundary(
                quote="- εr 标度：全谱频率 ÷√εr（εr=4 → ÷2 逐位）。",
                note=(
                    "数值锚面（#118 独立来源）：TM010 a=10mm→11.4743GHz"
                    "（x_01 测试侧独立常数）；TE011/TM111 简并同频逐位；Qc "
                    "闭式 vs 数值 <1e-9、Qc∝1/Rs；主模判据经典口径复现——"
                    "锚树判据书。"
                ),
            ),
            Boundary(
                quote="整型 1..500（超限显式拒绝要求收窄频段）；模式名形如 'TE011'/'TM010'",
                note=(
                    "枚举规模守卫（max_modes 整型上限、防组合爆炸超限拒绝"
                    "要求收窄频段）；radius/length>0、0<f_min<f_max、"
                    "epsilon_r≥1、conductivity>0、tan_delta≥0——越界一律"
                    "显式 ValueError。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_a2c_coax_waveguide.py",
                quote="数值锚（#118 独立来源；锚树 tests/unit/test_a2c_coax_waveguide.py）",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="waveguide_iris",
        tagline=(
            "矩形波导薄膜片面：感性/容性膜片归一化电纳正反解、感容组合"
            "谐振窗全传输条件与单膜片匹配双分支闭式——工程薄膜片近似档，"
            "数值模匹配为真机仲裁路径。"
        ),
        modules=("calc_families/waveguide_iris",),
        primary_entries=(
            ("calc_families/waveguide_iris", "wg_iris_susceptance"),
            ("calc_families/waveguide_iris", "wg_resonant_window"),
            ("calc_families/waveguide_iris", "wg_iris_match"),
            ("calc_families/waveguide_iris", "waveguide_lambda_g"),
        ),
        test_face_needles=(
            "wg_iris_susceptance",
            "wg_resonant_window",
            "wg_iris_match",
            "waveguide_lambda_g",
        ),
        formulas=(
            Formula(
                title="对称感性/容性薄膜片归一化电纳",
                latex=(
                    "\\frac{B_i}{Y_0}=-\\frac{\\lambda_g}{a}"
                    "\\cot^2\\!\\left(\\frac{\\pi d}{2a}\\right),\\quad"
                    "\\frac{B_c}{Y_0}=\\frac{4b}{\\lambda_0}"
                    "\\ln\\csc\\!\\left(\\frac{\\pi d}{2b}\\right)"
                ),
                quote="B/Y0 = −(λg/a)·cot²(πd/(2a))",
                quote2="B/Y0 = (4b/λ0)·ln csc(πd/(2b))，",
                cite=(
                    "模块 docstring「物理口径」节（感性式用 λg、容性式用 λ0"
                    "——两式 λ 依赖不同是通行工程式的真实不对称如实照录；"
                    "极限自检 d→a 电纳趋零、d→0 感性 −∞/容性 +∞ 方向符号"
                    "自洽）"
                ),
            ),
            Formula(
                title="谐振窗全传输条件（感容组合总电纳归零）",
                latex=(
                    "\\ln\\csc\\!\\left(\\frac{\\pi d_c}{2b}\\right)"
                    "=\\frac{\\lambda_g b}{4a\\lambda_0}"
                    "\\cot^2\\!\\left(\\frac{\\pi d_i}{2a}\\right)"
                ),
                quote="谐振窗：感性+容性膜片组合总电纳 B/Y0=0（f0 处全传输），给定感性开口",
                quote2="d_i 反解容性开口 d_c：ln csc(πd_c/2b) = (λg·b)/(4aλ0)·cot²(πd_i/2a)，",
                cite=(
                    "模块 docstring（cot²≥0 → sin(πd_c/2b)=exp(−·)∈(0,1] 恒"
                    "可解；指数下溢（感性开口过小所需容性电纳超出闭式可达）"
                    "显式拒绝）"
                ),
            ),
            Formula(
                title="单膜片匹配（并联电纳调配的波导实现）",
                latex=(
                    "y(\\ell)=\\frac{y_L+jt}{1+jy_L t},\\ "
                    "t=\\tan(\\beta\\ell);\\quad"
                    "(b^2+g^2-g)t^2-2bt+(1-g)=0"
                ),
                quote="(b²+g²−g)t² − 2b·t + (1−g) = 0（判别式 g[b²+(1−g)²]≥0 恒两实根，g>0",
                quote2="口反解 d=(2a/π)·arctan√(−a/(b_iλg))、b_i>0 → 容性反解",
                cite=(
                    "模块 docstring「单膜片匹配」节（b_i=−Im{y(ℓ)}；感性分支"
                    "标工程优先（功率容量/易实现惯例）双分支如实并列；匹配解 "
                    "ABCD 回代 |Γin|≈0 构造级残差锚）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="级文献通行式转引——原文页码未逐位复读，如实登记；厚膜片/有限厚度修",
                note=(
                    "出处分级（#122）：Marcuvitz Waveguide Handbook 闭式首阶"
                    "形、经 Rizzi《Microwave Engineering: Passive Circuits》 "
                    "ch.4 二级文献通行式转引——原文页码未逐位复读如实登记；"
                    "厚膜片/有限厚度修正项不在本族口径。"
                ),
            ),
            Boundary(
                quote="- core/rwg_mmt.py=**数值模匹配**工具（H 面阶梯/膜片=阶梯构件级联的广义",
                note=(
                    "语义分层：rwg_mmt=数值模匹配（真机窗仲裁路径）、"
                    "rw_tables=EIA 尺寸表、hybrid_junction=结器件 S 矩阵、"
                    "stub_tuner=通用传输线支节调配——本族=工程薄膜片电纳"
                    "闭式（膜片近似档）；λg 抽键与 slot_array 内嵌式/"
                    "microstrip 准 TEM 三层不撞。"
                ),
            ),
            Boundary(
                quote="数值锚（#118 独立路线）：极限恒等（开口=全波导 → 电纳 0）；匹配解",
                note=(
                    "数值锚面（#118 独立路线）：开口=全波导电纳 0 极限恒等；"
                    "匹配解 ABCD 回代 |Γin|≈0、谐振窗回代 |B总|≈0 构造级"
                    "残差；λg 对 fc 标度恒等式测试侧独立重解——锚树判据书。"
                ),
            ),
            Boundary(
                quote="守卫：a_mm/b_mm>0 且 b_mm≤a_mm（标准矩形波导口径）；f_ghz>0 且>fc10；",
                note=(
                    "截止以下无传播显式拒绝（膜片电纳语义失效）；d_mm 与 "
                    "b_norm 恰给其一（正解/反解互斥双给拒绝）；|Γ|≥1 非物理"
                    "拒绝——越界一律显式 ValueError。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_a7b_iris_guanella.py",
                quote="tests/unit/test_a7b_iris_guanella.py 与 tests/unit/test_aurora_d_core8.py）",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="hybrid_junction",
        tagline=(
            "混合结器件面：魔 T 理想四口 S 矩阵（和差臂隔离/均分/相位行为"
            "四约束钉死）、并联星形与串联环形三口结功率波闭式、和差合成"
            "能量守恒——结器件理想口径，不出波导尺寸综合。"
        ),
        modules=("calc_families/hybrid_junction",),
        primary_entries=(
            ("calc_families/hybrid_junction", "magic_tee_s_matrix"),
            ("calc_families/hybrid_junction", "waveguide_tee_s_matrix"),
            ("calc_families/hybrid_junction", "hybrid_sum_difference"),
        ),
        test_face_needles=(
            "magic_tee_s_matrix",
            "waveguide_tee_s_matrix",
            "hybrid_sum_difference",
        ),
        formulas=(
            Formula(
                title="魔 T 理想四口 S 矩阵（四约束钉死）",
                latex=(
                    "\\mathbf S=\\frac{1}{\\sqrt{2}}\\begin{bmatrix}"
                    "0&1&1&0\\\\1&0&0&1\\\\1&0&0&-1\\\\0&1&-1&0"
                    "\\end{bmatrix}"
                ),
                quote="S = (1/√2)·[[0, 1, 1, 0],",
                quote2="四约束钉死：①幺正（无耗）②S14=S41=0（E/H 臂隔离）③匹配 S_ii=0",
                cite=(
                    "模块 docstring「物理口径」节（Pozar §7.5 混合结口径；"
                    "④和差相位行为——激励和口侧臂同相各 1/√2、差口反相各 "
                    "1/√2；符号约定写死上式口径，测试侧幺正+隔离+3dB+相位"
                    "四约束独立复核）"
                ),
            ),
            Formula(
                title="H 面/E 面三口结功率波闭式（KCL/KVL 对偶）",
                latex=(
                    "\\text{H 面（并联星形）}:\\ S_{ii}=-\\frac{1}{3},\\ "
                    "S_{ij}=+\\frac{2}{3};\\quad"
                    "\\text{E 面（串联环形）}:\\ S_{ii}=+\\frac{1}{3},\\ "
                    "S_{ij}=-\\frac{2}{3}"
                ),
                quote="并联星形结（H 面，共电压节点，KCL 推导）：S_ii=−1/3、S_ij=+2/3；",
                quote2="串联环形结（E 面，KVL 对偶）：S_ii=+1/3、S_ij=−2/3。",
                cite=(
                    "模块 docstring（理想对称无耗互易功率波口径第一性推导；"
                    "幺正+互易+镜像对称+E/H 对偶四约束钉死；侧臂均分 "
                    "20lg(2/3)=−3.5218dB、支臂回损 9.5424dB 常数）"
                ),
            ),
            Formula(
                title="和差合成与能量守恒（幺正推论）",
                latex=(
                    "b_{\\mathrm{sum}}=\\frac{a_2+a_3}{\\sqrt{2}},\\quad"
                    "b_{\\mathrm{diff}}=\\frac{a_2-a_3}{\\sqrt{2}},\\quad"
                    "|b_{\\mathrm{sum}}|^2+|b_{\\mathrm{diff}}|^2"
                    "=|a_2|^2+|a_3|^2"
                ),
                quote="和差合成：b_sum=(a2+a3)/√2、b_diff=(a2−a3)/√2；能量守恒",
                quote2="|b_sum|²+|b_diff|²=|a2|²+|a3|² 恒等（幺正推论）；等幅同相→差口零",
                cite=(
                    "模块 docstring（等幅同相→隔离 null、反相→和口零、正交→"
                    "恰各半 −3.0103dB 恒等；和差键与四口矩阵乘 b=S·a 匹配"
                    "负载口径跨键逐位互证）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="④对偶 S_E=−S_H。无耗互易三口**全匹配不可能**（S11=±1/3 是拓扑必然",
                note=(
                    "拓扑必然性：无耗互易三口全匹配不可能（匹配三端口需非互易"
                    "，环行器另域）——S11=±1/3 是拓扑必然非实现缺陷，如实按"
                    "四约束口径落定。"
                ),
            ),
            Boundary(
                quote="（端口参考方向选择所致，部分 ±1/2 表违反幺正），本实现按四约束口径",
                note=(
                    "符号约定纪律：印刷矩阵各文献符号约定不一（端口参考方向"
                    "选择所致，部分 ±1/2 表违反幺正）——本实现按幺正四约束"
                    "口径写死，测试侧 KCL/KVL 线性方程组独立重解异路线互证。"
                ),
            ),
            Boundary(
                quote="- unequal_split_wilkinson/bethe_hole_coupler=电阻功分/孔耦合**综合**键",
                note=(
                    "边界防撞：unequal_split_wilkinson/bethe_hole_coupler="
                    "综合键（出几何尺寸）、ratrace=模板锚判读、butler_matrix "
                    "内嵌 90° 混合环块（本族为 180° 混合结）——本族只做结"
                    "器件理想 S 矩阵口径，E/H 臂口径尺寸设计属波导模板域"
                    "如实不做。"
                ),
            ),
            Boundary(
                quote="守卫：excite_port∈{1,2,3,4}；tee_type∈{h_plane,e_plane}；p2_dbm/p3_dbm",
                note=(
                    "excite_port/tee_type 白名单、功率幅值域界（幅值下溢"
                    "防呆）；隔离 null 份额口径 frac<1e-24 → dBm 如实 None"
                    "（浮点理想零不冒充伪精确值）——越界一律显式 ValueError。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_a5a_saw_hybrid.py",
                quote="（KCL/KVL 独立重解见锚树）；'3dB 均分'直觉属失配理想化——无耗",
                tracked=True,
            ),
        ),
    ),
    # ─── aurora_g W6-S4 内核卡批六 6 卡（R2_core_tier4 §④ 卡批 E 头两族
    # + 卡批 D 头一族 + W4-S4 内核余量三族；引文经 内部证据档
    # w6s4_quote_probe.py 预验 71/71 一次全命中，数值抽查
    # 内部证据档 19 CALC 键 docstring 锦点全 PASS）──
    CardSpec(
        kernel_id="radar_eq",
        tagline=(
            "雷达方程与检测统计面：基本雷达方程 SI/dB 双口径互斥闭式、"
            "Albersheim 检测因子三量互算经验式（Swerling 0 如实不冒充）、"
            "CA-CFAR 门限因子与 Swerling 1 检测概率闭式——雷达链路预算"
            "三件套。"
        ),
        modules=("calc_families/radar_eq",),
        primary_entries=(
            ("calc_families/radar_eq", "radar_range_equation"),
            ("calc_families/radar_eq", "albersheim_detection_snr"),
            ("calc_families/radar_eq", "ca_cfar_threshold"),
        ),
        test_face_needles=(
            "radar_range_equation",
            "albersheim_detection_snr",
            "ca_cfar_threshold",
        ),
        formulas=(
            Formula(
                title="基本雷达方程（单基地同天线、匹配接收）",
                latex=(
                    "P_r=\\frac{P_t G^2 \\lambda^2 \\sigma}"
                    "{(4\\pi)^3 R^4 L}"
                ),
                quote="Pr = Pt·G²·λ²·σ / ((4π)³·R⁴·L)",
                quote2="两口径互斥（显式二选一，跨口径参数混给显式拒绝）；dB 路径内部",
                cite=(
                    "模块 docstring（Skolnik *Introduction to Radar Systems* "
                    "3rd ed. ch.2 / Richards FRSP ch.1 通用口径；dB 路径 λ 经 "
                    "registry.C_MM_GHZ 单源、内部归一 SI 同式计算，同参一致性"
                    "测试钉）"
                ),
            ),
            Formula(
                title="Albersheim 检测因子经验式（三量互算）",
                latex=(
                    "A=\\ln(0.62/P_{fa}),\\ B=\\ln\\!\\tfrac{P_d}{1-P_d},\\quad"
                    "\\mathrm{SNR}_{dB}=-5\\lg N+\\left(6.2+\\tfrac{4.54}"
                    "{\\sqrt{N+0.44}}\\right)\\lg(A+0.12AB+1.7B)"
                ),
                quote="A = ln(0.62/Pfa)、B = ln(Pd/(1−Pd))",
                quote2="SNR_dB = −5·lg(N) + (6.2 + 4.54/√(N+0.44))·lg(A + 0.12·A·B + 1.7·B)",
                cite=(
                    "模块 docstring（原式 W. J. Albersheim IEEE Trans. AES "
                    "1981；转引 Skolnik 3ed ch.2；Pfa+Pd→SNR 前向、Pfa+SNR→Pd/"
                    "Pd+SNR→Pfa 宗量线性闭式反解）"
                ),
            ),
            Formula(
                title="CA-CFAR 门限因子（指数噪声单元）",
                latex=(
                    "P_{fa}=(1+\\beta)^{-N}\\Rightarrow"
                    "\\ \\alpha=N\\big(P_{fa}^{-1/N}-1\\big)"
                ),
                quote="Pfa = (1+β)^(−N)   →   β = Pfa^(−1/N) − 1   （对参考窗求和）",
                quote2="α = N·β = N·(Pfa^(−1/N) − 1)                （对参考窗平均）",
                cite=(
                    "模块 docstring（Richards FRSP ch.6 CA-CFAR 节标准结果；"
                    "门限 T=β·Σx_i=α·(Σx_i/N)；保护单元只改窗几何不进 α；"
                    "可选 SW1 检测概率 Pd=(1+β/(1+S))^(−N) 闭式）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="Swerling 1-4 起伏目标检测因子不在 Albersheim 覆盖内，",
                note=(
                    "#122 如实口径：Albersheim 只覆盖 Swerling 0 非起伏目标"
                    "（线性检波、N 脉冲非相干积累），SW1-4 起伏目标检测因子"
                    "不冒充；分母 √(N+0.44) 取原式形态（二手 √(N+1) 简化"
                    "与本键差 0.5~0.8 dB 不采用）。"
                ),
            ),
            Boundary(
                quote="窗外计算照常、extrapolated=True 如实标注（硬域仍为 0<Pfa<1、",
                note=(
                    "拟合窗 Pd∈[0.1,0.9]、Pfa∈[1e-7,1e-3]（文献 ±0.2 dB 精度"
                    "声明窗）——窗外照算但 extrapolated=True 如实标注；硬域 "
                    "0<Pfa/Pd<1 越界显式拒绝。"
                ),
            ),
            Boundary(
                quote="守卫：Pt（pt_w>0 / pt_dbm 有限）、G>0（线性）/有限（dB）、λ>0、",
                note=(
                    "全键域盒显式守卫（Pt/G/λ/f/σ/R/L、n_pulses 正整数、"
                    "0<Pfa/Pd<1）；SI/dB 跨口径参数混给显式拒绝——越界一律 "
                    "ValueError。"
                ),
            ),
            Boundary(
                quote="- Albersheim：Pfa=1e-6/Pd=0.9/N=1 → 13.1145 dB，与线性检波 Marcum-Q",
                note=(
                    "数值锚面（#118 独立路线）：Albersheim 对 Marcum-Q 精确"
                    "反解 |Δ|≤0.07 dB、雷达方程 R 加倍 Pr 精确 ÷16 恒等、"
                    "SI/dB 同参一致 <1e-9、CFAR 闭式回代逐位+蒙特卡洛独立"
                    "裁判——锚树判据书。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w4a_mod_radar.py",
                quote="数值锚（#118 独立来源；锚树 tests/unit/test_w4a_mod_radar.py）",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="modulation_ber",
        tagline=(
            "数字调制理论误码率面：BPSK/QPSK 闭式与 square M-QAM 精确和式、"
            "目标 BER→所需 Eb/N0 单调二分反解、级联编码一阶粗估——通信链"
            "「调制→编码」数字面与 fec_codes 编码增益产生面互为消费。"
        ),
        modules=("calc_families/modulation_ber",),
        primary_entries=(
            ("calc_families/modulation_ber", "modulation_ber_curve"),
            ("calc_families/modulation_ber", "required_ebn0"),
            ("calc_families/modulation_ber", "coded_ber_estimate"),
        ),
        test_face_needles=(
            "modulation_ber_curve",
            "required_ebn0",
            "coded_ber_estimate",
        ),
        formulas=(
            Formula(
                title="BPSK/QPSK 相干解调 BER（Gray 映射、比特能量口径）",
                latex="P_b=Q\\!\\left(\\sqrt{2\\gamma_b}\\right)",
                quote="Pb = Q(√(2·γb))",
                quote2="QPSK 与 BPSK 在同比特能量口径下 BER 逐位相等（QPSK 每支路即 BPSK、",
                cite=(
                    "模块 docstring（相干 AWGN；QPSK≡BPSK 物理恒等——Es/N0="
                    "2·Eb/N0，全 γ 扫描逐位测试钉；Q 函数单源 _qfunc 全族"
                    "唯一实现）"
                ),
            ),
            Formula(
                title="square M-QAM 精确和式（M=16/64）",
                latex=(
                    "P_b=\\frac{4(1-1/\\sqrt{M})}{k}\\sum_{i=1}^{\\sqrt{M}/2}"
                    "Q\\!\\left((2i-1)\\sqrt{\\tfrac{3k\\gamma_b}{M-1}}\\right),"
                    "\\quad k=\\log_2 M"
                ),
                quote="Pb = 4(1−1/√M)/k · Σ_{i=1}^{√M/2} Q((2i−1)·√(3k·γb/(M−1)))，",
                quote2="（Proakis, *Digital Communications* 5th ed. QAM 节；Cho & Kim,",
                cite=(
                    "模块 docstring（Proakis 5ed QAM 节/Cho & Kim IEEE Comm. "
                    "Lett. 2005 同形逐项式；M=4 退化回 BPSK 闭式）"
                ),
            ),
            Formula(
                title="级联编码一阶粗估（码率扩张+固定净增益偏移）",
                latex=(
                    "\\gamma_{b,\\mathrm{eff}}=\\gamma_b+10\\lg R_c+G_{\\mathrm{coding}}"
                    "\\ \\Rightarrow\\ P_b=\\mathrm{BER}_{\\mathrm{theory}}"
                    "(\\gamma_{b,\\mathrm{eff}})"
                ),
                quote="γb_eff = γb + 10·lg(R_c) + G_coding    →  Pb = BER_theory(γb_eff)",
                quote2="不建模打孔/交织/迭代译码瀑布区（G_coding 必须取目标 BER 点的净",
                cite=(
                    "模块 docstring（一阶粗估口径 docstring 与输出 note 双写死；"
                    "G_coding 输入由 fec_codes 编码增益族产生——同仓消费链 "
                    "#122 不冒充精确）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="- Q 函数单源：Q(x) = 0.5·erfc(x/√2)（本模块 _qfunc，全族唯一实现，",
                note=(
                    "Q 函数单源纪律：全族唯一实现 _qfunc=0.5·erfc(x/√2)，"
                    "禁止第二份 erfc/Q 形态（双实现漂移防线）。"
                ),
            ),
            Boundary(
                quote="反解：γb→Pb 在域内严格单调降（Q 单调 + 正系数和式），dB 域二分",
                note=(
                    "反解口径：单调性成立（Q 单调+正系数和式），dB 域二分 "
                    "200 轮（区间收敛 ~1e-60，纯 math 零依赖，同 bethe_hole "
                    "反解惯例）。"
                ),
            ),
            Boundary(
                quote="双精度下 BER 有效下限 1e-15（erfc 深尾下溢地板之上），target_ber",
                note=(
                    "数值域界：双精度 BER 有效下限 1e-15（erfc 深尾下溢地板"
                    "之上），target_ber 低于此显式拒绝；target_ber>0.1 给 "
                    "low_confidence 标注不拒绝（#122 如实三分）。"
                ),
            ),
            Boundary(
                quote="守卫：ebn0_db 必须有限（标量或非空列表逐点校验）；target_ber ∈",
                note=(
                    "域盒守卫：ebn0_db 有限（标量/列表逐点）、target_ber∈"
                    "[1e-15, 0.5)、scheme 未知名显式拒绝、code_rate∈(0,1]、"
                    "coding_gain_db 有限——越界一律 ValueError。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w4a_mod_radar.py",
                quote="数值锚（#118 独立来源；锚树 tests/unit/test_w4a_mod_radar.py）",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="coax_line",
        tagline=(
            "标准圆同轴传输线通用件：TEM 特性阻抗双向解（分析/综合/ratio）、"
            "导体+介质行波衰减分解与线 Q 场积分路线互证、内导体表面场强"
            "功率容量与 30Ω/76.7Ω 经典最优比、截止波导衰减器倏逝模——"
            "与 combline 谐振腔面语义防撞。"
        ),
        modules=("calc_families/coax_line",),
        primary_entries=(
            ("calc_families/coax_line", "coax_line_z0"),
            ("calc_families/coax_line", "coax_line_attenuation"),
            ("calc_families/coax_line", "coax_line_power_capacity"),
            ("calc_families/coax_line", "coax_line_cutoff_attenuator"),
        ),
        test_face_needles=(
            "coax_line_z0",
            "coax_line_attenuation",
            "coax_line_power_capacity",
            "coax_line_cutoff_attenuator",
        ),
        formulas=(
            Formula(
                title="TEM 特性阻抗精确闭式（分析/综合双向）",
                latex="Z_0=\\frac{60}{\\sqrt{\\varepsilon_r}}\\ln\\frac{b}{a},"
                      "\\quad b/a=\\exp\\!\\big(Z_0\\sqrt{\\varepsilon_r}/60\\big)",
                quote="Z0 = (60/√εr)·ln(b/a) Ω（非磁性；a=内导体半径、b=外导体内半径；",
                quote2="单位长度电容/电感：C' = 2πε/ln(b/a)（ε=ε0εr）、L' = (μ/2π)·ln(b/a)，",
                cite=(
                    "模块 docstring（Pozar §2.2 同轴线；60=工程惯例记号、"
                    "精确常数 η0/2π=59.9585——损耗/Q 链按精确常数、阻抗面按"
                    "惯例 60，记号差 ~0.07% 如实注记；L'·C'=με 恒等测试钉）"
                ),
            ),
            Formula(
                title="行波衰减分解（导体趋肤+介质）",
                latex="\\alpha_c=\\frac{R_s(1/a+1/b)}{4\\pi Z_0},\\quad"
                      "\\alpha_d=\\frac{\\beta\\tan\\delta}{2},\\quad"
                      "\\alpha_{dB/m}=8.686(\\alpha_c+\\alpha_d)",
                quote="αc = Rs·(1/a + 1/b)/(4π·Z0)   [Np/m]",
                quote2="αd = (β·tanδ)/2 = π·f·√(εr·μr)·tanδ/c₀   [Np/m]",
                cite=(
                    "模块 docstring（Pozar §2.7/Ramo-Whinnery-Van Duzer；"
                    "线 Q=β/(2α) 与场积分路线解析同解，跨键测试互证 ≤1e-12；"
                    "αc∝√f、αc∝1/√σ 标度恒等测试钉）"
                ),
            ),
            Formula(
                title="峰值功率容量（内导体表面场强上限）",
                latex="V_{\\max}=E_{br}\\,a\\ln\\frac{b}{a},\\quad"
                      "P_{\\max}=\\frac{V_{\\max}^2}{2Z_0}"
                      "=\\frac{E_{br}^2 a^2 \\ln(b/a)\\sqrt{\\varepsilon_r}}{120}",
                quote="P_max = V_max²/(2·Z0) = E_br²·a²·ln(b/a)·√εr/120  [W，峰值/匹配线]",
                quote2="经典最优比（外径 b 固定）：功率容量最大 b/a=√e → Z0=30/√εr；",
                cite=(
                    "模块 docstring（TEM 场分布 E(ρ)=V/(ρ·ln(b/a))；衰减最小 "
                    "b/a≈3.59112 → Z0≈76.7/√εr——两最优比常数作输出字段与"
                    "测试锚）"
                ),
            ),
            Formula(
                title="截止波导衰减器（TE11 以下倏逝模）",
                latex="\\alpha=k_c\\sqrt{1-(f/f_c)^2},\\quad"
                      "k_c\\approx\\frac{2}{a+b}",
                quote="- coax_line_cutoff_attenuator：Pozar §3 波导一般理论倏逝模",
                cite=(
                    "模块 docstring 出处节（保角映射截止常数 kc≈2/(a+b) 与 "
                    "TE11 截止同式；f≥f_c 单模 TEM 假设失效如实 note）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="- combline_resonator.coaxial_cavity_resonance = **同轴谐振腔**（TEM 谐振",
                note=(
                    "语义防撞（R7 三重搜索证据）：combline=同轴谐振腔（λ/2·λ/4 "
                    "腔长综合/腔 Q 驻波口径）、SICL/rf_trace_geometry=异形/印制"
                    "截面——本族只做标准圆同轴行波通用件（阻抗/每米损耗/击穿"
                    "功率/倏逝衰减）。"
                ),
            ),
            Boundary(
                quote="首个高阶模 TE11 截止（保角映射 kc≈2/(a+b)）：f_c = c₀/(π(a+b)√εr)，",
                note=(
                    "单模边界：f ≥ TE11 截止时单模 TEM 假设失效（同 combline "
                    "腔键口径如实 note）；保角映射 kc 为一阶近似非精确根。"
                ),
            ),
            Boundary(
                quote="（STP；同轴内导体场非均匀，工程需按海拔/湿度/安全系数降额，如实",
                note=(
                    "E_br 缺省 3.0e6 V/m=均匀场空气击穿参考值（STP）——同轴"
                    "内导体场非均匀，工程按海拔/湿度/安全系数降额，不冒充"
                    "精确击穿预测（#122 如实）。"
                ),
            ),
            Boundary(
                quote="守卫：分析路线 a_mm>0、b_mm>a_mm（a≥b 非物理显式拒绝）；综合路线",
                note=(
                    "路线互斥守卫：分析 a/b 恰给其一（同给或全缺显式拒绝）、"
                    "a≥b 非物理拒绝；epsilon_r≥1、f>0、σ>0、μr>0、tanδ≥0、"
                    "E_br>0、p_op≥0——越界一律 ValueError。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_a2c_coax_waveguide.py",
                quote="数值锚（#118 独立来源；锚树 tests/unit/test_a2c_coax_waveguide.py）",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="analog_modulation",
        tagline=(
            "模拟调制域三闭式：FM/PM Carson 带宽规则、FM 处理增益 "
            "3β²(β+1) 与捕获门限三态标记、AM DSB-LC 功率分配与 PEP——"
            "数字链既有面（modulation BER/rx_impairments）的模拟姊妹面。"
        ),
        modules=("calc_families/analog_modulation",),
        primary_entries=(
            ("calc_families/analog_modulation", "carson_bandwidth"),
            ("calc_families/analog_modulation", "fm_processing_gain"),
            ("calc_families/analog_modulation", "am_power_split"),
        ),
        test_face_needles=(
            "carson_bandwidth",
            "fm_processing_gain",
            "am_power_split",
        ),
        formulas=(
            Formula(
                title="Carson 带宽规则（FM/PM）",
                latex="B\\approx 2(\\Delta f+f_m)=2(\\beta+1)f_m,\\quad"
                      "\\beta=\\Delta f/f_m;\\quad"
                      "B_{PM}\\approx 2(\\Delta\\phi+1)f_m",
                quote="FM：B ≈ 2·(Δf + f_m) = 2·(β + 1)·f_m，β = Δf/f_m",
                quote2="PM：B ≈ 2·(Δφ + 1)·f_m（Δφ = 峰值相偏 rad，等效 Δf = Δφ·f_m）",
                cite=(
                    "模块 docstring（Carson 1922；Rappaport 2nd ed §5.3.1 承载；"
                    "98% 功率容纳口径经验规则非精确边界——FM 广播 β=5→B=180kHz "
                    "教科书点逐位锚）"
                ),
            ),
            Formula(
                title="FM 处理增益（鉴频器抛物线噪声积分）",
                latex="G=\\frac{\\mathrm{SNR}_{out}}{\\mathrm{CNR}_{RF}}"
                      "=3\\beta^2(\\beta+1)",
                quote="SNR_out = (3/2)·β²·C/(N₀·W)         （鉴频器抛物线噪声积分）",
                quote2='出处：Rappaport §5.3.2 "FM improvement factor" I=3β²(β+1)；',
                cite=(
                    "模块 docstring（Rappaport §5.3.2 FM improvement factor；"
                    "(3/2)β²·C/(N₀W) 形见 Haykin/Couch 标准推导；多步独立算术"
                    "路径数值代回收 G=450@β=5，非同一公式两次抄写）"
                ),
            ),
            Formula(
                title="AM DSB-LC 功率分配与 PEP",
                latex="P_{sb}=\\frac{P_c m^2}{2},\\quad"
                      "\\eta=\\frac{m^2}{2+m^2},\\quad"
                      "\\mathrm{PEP}=P_c(1+m)^2",
                quote="载波 P_c；边带 P_sb = P_c·m²/2；总 P = P_c·(1 + m²/2)",
                quote2="功率效率 η = P_sb/P = m²/(2 + m²)；PEP = P_c·(1 + m)²",
                cite=(
                    "模块 docstring（任何模拟通信教科书/Rappaport §5.2 同族；"
                    "m=1 → η=1/3 最大效率逐位、PEP=4P_c）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="98% 功率容纳口径的经验规则（非精确边界）；β→0 退化 B→2f_m（窄带",
                note=(
                    "Carson 规则是 98% 功率容纳的经验规则非精确边界；β→0 退化 "
                    "B→2f_m（窄带 FM 与 AM DSB 同宽——结构恒等式锚），PM 与 "
                    "FM 在 Δφ≡β 数值同构。"
                ),
            ),
            Boundary(
                quote="10dB 标记位如实三态——门限本体的统计模型不做，UNVERIFIED 如实）。",
                note=(
                    "门限效应：CNR 低于 ~10dB 时处理增益式失效（FM 捕获门限，"
                    "工程惯例 7–12dB 区间）——本键取 10dB 标记位如实三态，"
                    "门限本体的统计模型不做（UNVERIFIED 如实，#122）。"
                ),
            ),
            Boundary(
                quote="- modulation_ber=数字调制 BER/编码增益面（本族只做模拟 FM/PM/AM）；",
                note=(
                    "边界防撞（#222 triple-grep）：modulation_ber=数字 BER 面、"
                    "rx_impairments.phase_noise_evm=EVM 损伤面、pll_budget="
                    "锁相环相噪、fading=衰落统计、link_limits=链路极限——"
                    "本族只做模拟调制三闭式。"
                ),
            ),
            Boundary(
                quote="守卫：deviation/mod_freq>0、Δφ>0、β>0、cnr_db 有限、m∈(0,1]——全部",
                note=(
                    "域盒守卫：deviation/mod_freq/Δφ/β 正、cnr_db 有限、"
                    "m∈(0,1]（m>1 过调制包络失真域外显式拒绝）——越界一律 "
                    "ValueError。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w4s4_core_margin.py",
                quote="数值锚（#118 独立来源；锚树 tests/unit/test_w4s4_core_margin.py）",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="si_ctle",
        tagline=(
            "CTLE 连续时间线性均衡器独立面：1 零 2 极传输函数的 Nyquist "
            "增益/内禀峰值闭式、目标增益反解主极点（独立综合档）、任意频点"
            "复增益评估——通用零极点代数，规格档位产生不做（com_pam4 消费"
            "面语义防撞）。"
        ),
        modules=("calc_families/si_ctle",),
        primary_entries=(
            ("calc_families/si_ctle", "ctle_nyquist_gain"),
            ("calc_families/si_ctle", "ctle_pole_from_boost"),
            ("calc_families/si_ctle", "ctle_gain_at"),
        ),
        test_face_needles=(
            "ctle_nyquist_gain",
            "ctle_pole_from_boost",
            "ctle_gain_at",
        ),
        formulas=(
            Formula(
                title="CTLE 一阶形态传输函数（1 零 2 极+直流增益）",
                latex="H(f)=\\frac{g(1+jf/f_z)}"
                      "{(1+jf/f_{p1})(1+jf/f_{p2})}",
                quote="H(f) = g·(1 + j·f/f_z) / [(1 + j·f/f_p1)(1 + j·f/f_p2)]",
                quote2="|H(f)|² = g²·(1+(f/f_z)²) / [(1+(f/f_p1)²)(1+(f/f_p2)²)]",
                cite=(
                    "模块 docstring（802.3 COM 的 CTLE 每级拓扑同构，本族按"
                    "通用零极点代数实现、规格常数不进键面；f_p2 缺省 None="
                    "单极档单调升至渐近台无内禀峰）"
                ),
            ),
            Formula(
                title="内禀峰值（|H|² 对 u=f² 求导闭式）",
                latex="u^*=\\sqrt{(p_1^2-z^2)(p_2^2-z^2)}-z^2,\\quad"
                      "f_{peak}=\\sqrt{u^*}",
                quote="u* = √((p1²−z²)(p2²−z²)) − z²，f_peak = √(u*)",
                quote2="u* > 0 才有内禀峰（z 深低于 p1 时成立）；u* ≤ 0 → 单调降，峰值=DC。",
                cite=(
                    "模块 docstring（驻点方程 u²+2z²u+z²(p1²+p2²)−p1²p2²=0 "
                    "正根；重极对退化 p1=p2=p → f_peak=√(p²−2z²) 闭式代入档"
                    "逐位锚）"
                ),
            ),
            Formula(
                title="反解主极点（目标 Nyquist 增益综合档）",
                latex="f_{p1}=\\frac{f}{\\sqrt{RHS-1}},\\quad"
                      "RHS=\\frac{(1+(f/z)^2)\\,g^2}{b^2 K},\\ "
                      "K=1\\ \\text{或}\\ 1+(f/p_2)^2",
                quote="1+(f/p1)² = (1+(f/z)²)·g² / (b²·K)，K = 1（单极）或 1+(f/p2)²",
                quote2="f_p1 = f / √(RHS − 1)",
                cite=(
                    "模块 docstring（RHS≤1 → 目标超纯零点增益上限显式拒绝；"
                    "解得 f_p1<f_z → 低于 boost 域下限显式拒绝；achievability "
                    "区间由域盒自然导出）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="域约定：0 < f_z ≤ f_p1 ≤ f_p2（boost CTLE：零在极点前）；f_p2 缺省",
                note=(
                    "域约定：0 < f_z ≤ f_p1 ≤ f_p2（boost CTLE 零在极点前）；"
                    "f_p2 缺省 None=单极档（增益单调升至渐近台 g·f_p1/f_z，"
                    "无内禀峰）。"
                ),
            ),
            Boundary(
                quote="**独立零极点闭式评估/综合键面零**（R2_core_tier4 §② 方向 4 判据原文",
                note=(
                    "立项判据（#222 triple-grep）：R2 方向 4 判据原文「独立 "
                    "CTLE 双二阶零极点→Nyquist 峰值增益闭式综合零命中」——"
                    "R2「数据源薄」风险经口径选择消解：只做传输函数代数与"
                    "反解，不做 802.3 规格档位产生。"
                ),
            ),
            Boundary(
                quote="- com_pam4=COM 规格包裹（pychopmarg 数值权威，g_DC 档位扫描——本族不",
                note=(
                    "边界防撞：com_pam4=COM 规格档位扫描（pychopmarg 数值"
                    "权威）、si_channel.preemphasis_taps=Tx FFE 时域抽头、"
                    "gd_equalizer=群时延全通（幅度平坦）、stepped_impedance/"
                    "coupled_line_bpf=微波滤波器面——本族=Rx CTLE 频域零极点"
                    "搁架面。"
                ),
            ),
            Boundary(
                quote="- 守卫族：f_z>f_p1、非正频率、RHS≤1（超上限）、f_p1<f_z（低于下限）",
                note=(
                    "域盒守卫：f_z>f_p1 违序、非正频率、RHS≤1（目标超上限）、"
                    "f_p1<f_z（低于 boost 域下限）显式拒绝——越界一律 "
                    "ValueError。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w4s4_core_margin.py",
                quote="数值锚（#118 独立来源；锚树 tests/unit/test_w4s4_core_margin.py）",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="propagation",
        tagline=(
            "传播基础闭式包：双径干涉（Fresnel 反射系数+断点距离）、刃形"
            "绕射 exact/approx/lee 三档（J(0) 勘误如实并存）、Hata+COST-231 "
            "统一域盒路损、COST-231 Walfisch-Ikegami 视距/非视距三分量——"
            "注册薄壳+纯函数内核双模块。"
        ),
        modules=("calc_families/propagation", "propagation"),
        primary_entries=(
            ("calc_families/propagation", "two_ray_loss"),
            ("calc_families/propagation", "knife_edge_loss"),
            ("calc_families/propagation", "hata_cost231"),
            ("calc_families/propagation", "walfisch_ikegami_los"),
            ("calc_families/propagation", "walfisch_ikegami_nlos"),
        ),
        test_face_needles=(
            "two_ray_loss",
            "knife_edge_loss",
            "hata_cost231",
            "walfisch_ikegami_los",
            "walfisch_ikegami_nlos",
        ),
        formulas=(
            Formula(
                title="双径干涉路损（镜反射相干和+断点距离）",
                latex="L=\\mathrm{FSPL}(d_{los})-20\\log_{10}\\!"
                      "\\left|1+\\Gamma e^{j\\Delta\\phi}\\right|,\\quad"
                      "d_{break}=\\frac{4 h_{tx} h_{rx}}{\\lambda}",
                quote="L=FSPL(d_los)−20log10|1+Γe^{jΔφ}|；附断点距离 d_break=4·h_tx·h_rx/λ、",
                quote2="d_break = 4·h_tx·h_rx/λ（第一菲涅尔半径明区判据，§4.6 惯例），",
                cite=(
                    "模块 docstring（Rappaport 2nd ed §4.6 口径：Fresnel 平面波"
                    "反射系数 Γ_v/Γ_h、σ=0 纯介电 eps_r 单参数；d>>d_break 后"
                    "包络 −40dB/dec 渐近）"
                ),
            ),
            Formula(
                title="刃形绕射三档（exact/approx/lee 并存互检）",
                latex="J(v)=6.9+20\\log_{10}\\!\\left(\\sqrt{(v-0.1)^2+1}+v-0.1"
                      "\\right),\\quad v>-0.78",
                quote="J(v) = 6.9 + 20·log10(√((v−0.1)²+1) + v − 0.1)（P.526-15 式(60)族，",
                quote2='精确 J(0) = 6.02dB（经典"擦顶 6dB"），闭式 J(0) = 6.03dB（6.9 是',
                cite=(
                    "模块 docstring（ITU-R P.526-15 §4 Fresnel-Kirchhoff 参数 v；"
                    "exact=Fresnel 积分 scipy.special、approx=P.526 闭式、"
                    "lee=Rappaport §4.11 分段式三档并存互检）"
                ),
            ),
            Formula(
                title="Hata+COST-231 统一域盒路损（频段分段）",
                latex="150\\!-\\!1500\\,\\mathrm{MHz}:\\ \\mathrm{Okumura\\!-\\!Hata};"
                      "\\quad 1500\\!-\\!2000\\,\\mathrm{MHz}:\\ \\mathrm{COST\\!-\\!231}",
                quote="- Hata/COST-231：Rappaport §4.10 承载——150–1500MHz 走 Okumura-Hata",
                quote2="ValueError。两段在 f=1500MHz 接缝存在模型级不连续（两套拟合常数",
                cite=(
                    "模块 docstring（域盒 150–2000MHz/1–20km/30–200m/1–10m；"
                    "两段接缝模型级不连续实测 urban=4.33dB/suburban=1.33dB、"
                    "test 锚 hata_seam；COST 段城郊修正外推档如实 UNVERIFIED）"
                ),
            ),
            Formula(
                title="Walfisch-Ikegami 视距/非视距（COST 231 ch.4.4）",
                latex="L_{LOS}=42.6+26\\lg d_{km}+20\\lg f_{MHz};\\quad"
                      "L_{NLOS}=L_f+L_{rts}+L_{msd}",
                quote="教科书点 2000MHz/1km=108.62dB",
                quote2="metropolitan=−4+0.7(f/925−1)、medium=−4+1.5(f/925−1)，f=925MHz 时 ",
                cite=(
                    "模块 docstring（COST 231 final report ch.4.4 式(27)/"
                    "ITU-R P.1411 同式承载；NLOS 三分量逐项分列、h_bs≤h_roof 档"
                    "k_a=54/k_d=18−15·Δh_b/h_roof；h_bs>h_roof 内插档原文未复读"
                    "不做显式拒绝——#1c 禁凭记忆写常数）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="knife_edge_loss_lee_db（v>2.4 档 20log(0.225/v)），三档并存互检。",
                note=(
                    "实测勘误纪律（#118 裁判=独立来源）：任务书把闭式归 "
                    "「Lee 近似」且记 J(0)=−6.9dB——实现后实测精确 J(0)=6.02dB/"
                    "闭式 6.03dB（6.9 是电平偏置常数不是 J(0) 值）；Lee 分段式"
                    "另立第三档，三档并存互检。"
                ),
            ),
            Boundary(
                quote="F_n = √(n·λ·d1·d2/(d1+d2))（几何光学定义式）；",
                note=(
                    "菲涅尔区半径与净空：F_n 几何光学定义式+0.6·F1 净空判据"
                    "（链路工程惯例 ITU-R P.530 系列口径）——辅助纯函数不注册，"
                    "链路预算组合面 sat_link AP-9 消费。"
                ),
            ),
            Boundary(
                quote="（链路预算组合面，sat_link AP-9 消费）。",
                note=(
                    "薄壳分层：calc_families/propagation=注册薄壳（同 link/"
                    "exposure_limits 惯例）、core/propagation.py=纯函数零 IO "
                    "内核；零求解器依赖（§A 包跨件裁决）、返回 JSON 可序列化值。"
                ),
            ),
            Boundary(
                quote="零 ITU 数据文件捆绑，无再分发阻碍。",
                note=(
                    "再分发口径（PV-011 ITU CC BY-NC-SA）：本件只用手算闭式与"
                    "公式常数（事实性数值+出处标注），零 ITU 数据文件捆绑；"
                    "域盒外显式 ValueError（Hata/WI 两式域盒各自显式）。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(path="tests/unit/test_propagation.py", quote="出处（标准模型原文逐字转写+教科书同族二级转引，键内描述同源）：",
                tracked=True,
            ),
        ),
    ),
    # ─── aurora_g W8-S1 内核卡批七（W7-S3 新核三族：HF 天波/FMCW/SAR） ───────
    CardSpec(
        kernel_id="hf_skywave",
        tagline=(
            "HF 3-30MHz 电离层传播机理三键：等离子体频率/临界频率恒等式、"
            "割线定律 MUF（平地单跳几何档）、冷等离子体折射指数标度——"
            "全频段维度唯一整段空白的补口件（传播机理面，不做处理链）。"
        ),
        modules=("calc_families/hf_skywave",),
        primary_entries=(
            ("calc_families/hf_skywave", "critical_frequency"),
            ("calc_families/hf_skywave", "secant_law_muf"),
            ("calc_families/hf_skywave", "ionospheric_plasma_frequency"),
        ),
        # needle 刻意不含 "critical_frequency"——它是
        # grounding_critical_frequency_hz（common_mode 接地面）的子串，
        # 会把 test_common_mode.py 误计入本族测试面（#222 误中剔除同源）。
        test_face_needles=("secant_law_muf", "ionospheric_plasma_frequency"),
        formulas=(
            Formula(
                title="等离子体频率/临界频率（冷等离子体无磁场极限）",
                latex=(
                    "f_p=\\frac{1}{2\\pi}\\sqrt{\\frac{N_e e^2}{m_e"
                    "\\,\\varepsilon_0}}=8.978663\\sqrt{N_e}"
                ),
                quote=(
                    "f_p = (1/2π)·√(N_e·e²/(m_e·ε₀)) = 8.978663·√(N_e)"
                    "  [Hz，N_e m⁻³]"
                ),
                cite=(
                    "Davies《Ionospheric Radio》(IEE 1990) ch.1/ITU-R P.531 "
                    "通用口径（SI 2019+CODATA 2018 常数；系数开工日数值锤 "
                    "8.978662820487434 Hz·m^1.5，教科书 9√Ne [kHz, cm⁻³] "
                    "同值圆化）"
                ),
            ),
            Formula(
                title="割线定律 MUF+平地单跳几何档",
                latex=(
                    "MUF=f_o\\sec i,\\quad "
                    "\\sin i=\\frac{d/2}{\\sqrt{h^2+(d/2)^2}}"
                ),
                quote="MUF = f_o·sec(i) = f_o/cos(i)",
                quote2="sin(i) = (d/2) / √(h² + (d/2)²)",
                cite=(
                    "Davies ch.5/Skolnik HF 天波章通用口径；i→0 退化 "
                    "MUF=f_o 逐位、i≥90° cos≤0 显式拒绝（发散守卫）；"
                    "hop_km+virtual_height_km 同给走平地几何档"
                ),
            ),
            Formula(
                title="冷等离子体折射指数标度（Appleton-Hartree 单轴极限）",
                latex=(
                    "n^2=1-\\left(\\frac{f_p}{f}\\right)^2,\\quad "
                    "v_{ph}=\\frac{c}{n},\\ v_g=c\\,n"
                ),
                quote="n² = 1 − (f_p/f)²",
                quote2=(
                    "f>f_p 传播档（n 实；相速 v_ph=c/n、群速 v_g=c·n、"
                    "v_ph·v_g=c² 恒等"
                ),
                cite=(
                    "Davies ch.1 同式；v_ph·v_g=c² 逐位恒等（相速超光速为"
                    "色散介质正常属性非违例——数值锤实测 v_ph·v_g/c²=1.0）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="i 直给档与几何档互斥（双给/缺省显式拒绝）。",
                note=(
                    "incidence_deg 直给档与 hop_km+virtual_height_km 平地"
                    "几何档二选一（部分给显式拒绝）；球形地球 M(3000)F2 "
                    "曲线修正不在本键口径如实声明。"
                ),
            ),
            Boundary(
                quote="如实）；f<f_p 渐消档（n²<0，n=None 不出 NaN——#122 如实）",
                note=(
                    "f=f_p 截止档 n=0、f<f_p 渐消档 n=None——不产出 NaN 假数；"
                    "法拉第旋转/O-X 波双折射（磁场项）不在本键口径。"
                ),
            ),
            Boundary(
                quote="半经验表，本次环境不可达不 ship（#122 如实缺席）。",
                note=(
                    "NVIS 档/M(3000)F2 因子曲线/P.368 场强/P.372 噪声带等"
                    "半经验表原文本次环境不可达，如实缺席不凑卡。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w7s3_core_domains.py",
                quote="物理口径（#1c/#300 出处纪律；教科书恒等式，2026-10-19 数值锤独立实测）",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="fmcw_radar",
        tagline=(
            "三角调制 FMCW 波形→观测量映射四键：拍频正反解（距离/多普勒"
            "解耦恒等式）、带宽→距离分辨率/IF 带宽量程面、chirp 参数设计"
            "（正问题链逆解面，W11-S4 扩展）与 IF 信号链规划（混频→LPF→"
            "ADC→距离 FFT，W11-S4 扩展）——ISAC/车载最主流波形的指标面"
            "延长线（不做 FFT 处理链/动目标检测链）。"
        ),
        modules=("calc_families/fmcw_radar",),
        primary_entries=(
            ("calc_families/fmcw_radar", "fmcw_range_doppler"),
            ("calc_families/fmcw_radar",
             "fmcw_bandwidth_range_resolution"),
            ("calc_families/fmcw_radar", "fmcw_chirp_design"),
            ("calc_families/fmcw_radar", "fmcw_if_signal_chain"),
        ),
        test_face_needles=(
            "fmcw_range_doppler",
            "fmcw_bandwidth_range_resolution",
            "fmcw_chirp_design",
            "fmcw_if_signal_chain",
        ),
        formulas=(
            Formula(
                title="三角调制拍频分解（距离拍频+多普勒）",
                latex=(
                    "f_{b,R}=S\\tau=\\frac{2SR}{c},\\quad "
                    "f_D=\\frac{2vf_c}{c},\\quad "
                    "f_{up}=f_{b,R}-f_D,\\ f_{down}=f_{b,R}+f_D"
                ),
                quote="f_b,R = S·τ = 2·S·R/c",
                quote2="上扫：f_up = f_b,R − f_D",
                cite=(
                    "Skolnik IRS ch.14/Richards FRSP ch.3 车载雷达教科书"
                    "通用口径（S=B/T 扫频斜率、τ=2R/c 往返时延、v>0 逼近"
                    "约定）"
                ),
            ),
            Formula(
                title="解耦恒等式与正反解",
                latex=(
                    "\\frac{f_{up}+f_{down}}{2}=\\frac{2SR}{c}\\Rightarrow "
                    "R=\\frac{c(f_{up}+f_{down})}{4S};\\quad "
                    "\\frac{f_{down}-f_{up}}{2}=f_D\\Rightarrow "
                    "v=\\frac{c\\,f_D}{2f_c}=\\frac{\\lambda f_D}{2}"
                ),
                quote="(f_up+f_down)/2 = 2·S·R/c → R = c·(f_up+f_down)/(4·S)",
                quote2="(f_down−f_up)/2 = f_D   → v = c·f_D/(2·f_c) = λ·f_D/2",
                cite=(
                    "同章通用口径；mode=forward（距离/速度→拍频）/inverse"
                    "（拍频→距离/速度）roundtrip 逐位闭环（#118 锚树钉，"
                    "数值锤 150m/10m/s@77GHz 回收逐位）"
                ),
            ),
            Formula(
                title="带宽-距离分辨率恒等式",
                latex="\\Delta R=\\frac{c}{2B}",
                quote="ΔR = c/(2B)",
                cite=(
                    "Skolnik/Richards 教科书恒等式（1GHz→14.99cm/4GHz→"
                    "3.75cm 车载口径；数值锤实测逐位）"
                ),
            ),
            Formula(
                title="IF 带宽量程面（饱和恒等）",
                latex=(
                    "R_{max}=\\frac{c\\,\\mathrm{BW_{IF}}}{2S},\\quad "
                    "f_b(R_{max})=\\mathrm{BW_{IF}},\\quad T_{chirp}=B/S"
                ),
                quote="R_max = c·BW_IF/(2·S)",
                quote2="f_b(R_max) = BW_IF",
                cite=(
                    "同章通用口径；饱和恒等=量程处拍频恰满 IF 带（数值锤 "
                    "50MHz IF/5e13 Hz/s → R_max=149.90m、f_b(R_max)=50MHz "
                    "逐位）；T_chirp=B/S 半程 chirp 时长随带"
                ),
            ),
            Formula(
                title="chirp 参数设计（正问题链逆解面，W11-S4）",
                latex=(
                    "B=\\frac{c}{2\\Delta R},\\quad "
                    "S=\\frac{c\\,\\mathrm{BW_{IF}}}{2R_{max}}"
                    "\\ \\text{或}\\ S=\\frac{c\\,f_s}{4R_{max}},\\quad "
                    "T_{chirp}=B/S,\\quad f_{s,\\min}=2f_b(R_{max})"
                ),
                quote="B = c/(2·ΔR)",
                quote2="IF 带限档：S = c·BW_IF/(2·R_max)",
                cite=(
                    "同章通用口径的逆解面；三斜率定档互斥（部分给/多给/全缺"
                    "显式拒绝），IF 带限与实采样 Nyquist 档在 BW_IF=fs/2 时"
                    "斜率逐位一致（跨档一致性锚）"
                ),
            ),
            Formula(
                title="IF 信号链规划（混频→LPF→ADC→距离 FFT，W11-S4）",
                latex=(
                    "R_{adc}=\\frac{c\\,f_s}{4S},\\quad "
                    "R_{lpf}=\\frac{c\\,f_{lpf}}{2S},\\quad "
                    "\\Delta R_{obs}=\\frac{c}{2B_{eff}}"
                    "=\\frac{c\\,f_s}{2SN},\\quad "
                    "G_{proc}=10\\lg N\\ \\mathrm{dB}"
                ),
                quote="R_adc = c·fs/(4·S)",
                quote2="ΔR_obs = c/(2·B_eff) = c·fs/(2·S·N)",
                cite=(
                    "同章通用口径+Richards FRSP ch.1 相参积累增益 N 口径"
                    "（bins=⌊N/2⌋、处理增益 10·lg(N) dB；观测分辨率=矩形窗"
                    "距离 bin 宽恒等式逐位）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="（|f_D|>f_b,R 时解耦模型折叠，显式拒绝）。",
                note=(
                    "拍频非负守卫：一阶解耦模型域=拍频内多普勒-距离耦合 "
                    "O(τ·f_D) 忽略（v≪c 恒成立）；|f_D|>f_b,R 时模型折叠，"
                    "显式拒绝不出伪数。"
                ),
            ),
            Boundary(
                quote="静止目标（v=0）f_up=f_down 逐位对称恒等；正反解双向（mode=forward/",
                note=(
                    "静止目标 f_up=f_down 逐位对称；远离目标（v<0）f_up>"
                    "f_down 方向恒等；inverse 出速度需 carrier_hz 同给。"
                ),
            ),
            Boundary(
                quote="波形（快慢时间 MIMO）/FFT 处理链不在本键口径（isac no-go 同源尊重）。",
                note=(
                    "本族只做波形→观测量映射闭式；发射泄漏/相位噪声对分辨率"
                    "的退化不在键口径；isac_ambiguity「只做指标不做处理链」"
                    "no-go 同源尊重。"
                ),
            ),
            Boundary(
                quote="三斜率定档互斥（if_bandwidth_hz/adc_sample_rate_hz/slope_hz_per_s",
                note=(
                    "chirp 设计三档互斥：部分给/多给/全缺显式拒绝；IF 带限与"
                    "实采样 Nyquist 档在 BW_IF=fs/2 时斜率逐位一致（跨档一致性"
                    "锚）。"
                ),
            ),
            Boundary(
                quote="折叠守卫：设计量程拍频超 Nyquist（|f_D|=0 一阶域）与观测窗超 chirp",
                note=(
                    "IF 链折叠守卫：设计量程拍频超 Nyquist 与观测窗超 chirp "
                    "时长（B_eff>B 非物理）显式拒绝；多普勒维处理链不在本键"
                    "口径（no-go 同源尊重）。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w7s3_core_domains.py",
                quote="物理口径（#1c/#300 出处纪律；三角波几何恒等式，2026-10-19 数值锤独立",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="sar_geometry",
        tagline=(
            "SAR 合成孔径几何指标两键：聚焦方位分辨率 δ_az=D/2「悖论」恒等"
            "式（真实孔径对照面）与条带几何/PRF 不模糊窗/天线照明面——"
            "遥感场景收官件（成像几何指标，不做成像处理链）。"
        ),
        modules=("calc_families/sar_geometry",),
        primary_entries=(
            ("calc_families/sar_geometry", "sar_azimuth_resolution"),
            ("calc_families/sar_geometry", "sar_swath_coverage"),
        ),
        test_face_needles=("sar_azimuth_resolution", "sar_swath_coverage"),
        formulas=(
            Formula(
                title="聚焦 SAR 方位分辨率（「悖论」恒等式）",
                latex=(
                    "\\delta_{az}=\\frac{D}{2},\\quad "
                    "L_{sa}=\\frac{R\\lambda}{D},\\quad "
                    "T_{sa}=\\frac{L_{sa}}{v}"
                ),
                quote="δ_az = D/2",
                quote2="L_sa=R·λ/D 随 R、λ 变而分辨率不变——变更 R/λ 输出 δ_az 逐位不变，",
                cite=(
                    "Curlander & McDonough (Wiley 1991) ch.1/Skolnik IRS "
                    "ch.21 教科书「悖论」恒等式——与作用距离 R、波长 λ 无关"
                    "（变更 R/λ 输出逐位不变=本族头号测试锚，数值锤实测）"
                ),
            ),
            Formula(
                title="真实孔径（非聚焦）对照面",
                latex="\\theta_{az}=\\frac{\\lambda}{D},\\quad "
                      "\\delta_{ra}=\\frac{R\\lambda}{D}",
                quote="真实孔径波束宽 θ_az = λ/D  [rad]",
                quote2="真实孔径（非聚焦）分辨率 δ_ra = R·λ/D",
                cite=(
                    "同章通用口径（可选 range_m+wavelength_m 同给走对照面；"
                    "数值锤 2m 天线/0.03m 波长@800km：θ_az=0.859°、"
                    "δ_ra=L_sa=12km）"
                ),
            ),
            Formula(
                title="条带几何（平地近似，正侧视，角自星下点）",
                latex=(
                    "R_{slant}=\\frac{h}{\\cos\\theta},\\quad "
                    "G=h\\tan\\theta,\\quad "
                    "W_{ground}=h(\\tan\\theta_{far}-\\tan\\theta_{near}),"
                    "\\quad W_{slant}=R_{far}-R_{near}"
                ),
                quote="R_slant(θ) = h/cos(θ)",
                quote2="W_ground = h·(tan θ_far − tan θ_near)",
                cite=(
                    "Curlander & McDonough ch.1 几何口径；数值锤 800km/"
                    "20°–40°：R_near=851.3km、W_ground=380.1km、"
                    "W_slant=193.0km（独立算术逐位）"
                ),
            ),
            Formula(
                title="PRF 不模糊窗+天线照明面",
                latex=(
                    "z_{amb}=\\frac{c}{2\\,\\mathrm{PRF}},\\quad "
                    "\\beta=\\frac{\\lambda}{D_w},\\quad "
                    "W_{beam}=\\frac{R_{mid}\\,\\beta}{\\cos\\theta_{mid}}"
                ),
                quote="z_amb = c/(2·PRF)",
                quote2="W_beam = R_mid·β/cos(θ_mid)",
                cite=(
                    "同章几何口径；W_slant ≤ z_amb=相邻脉冲回波混叠判据"
                    "（数值锤 PRF 2kHz → z_amb=74.9km，193km 条带如实判 "
                    "within=False）；β=λ/D_w 波束宽、W_beam 中角照明幅宽"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="地球修正不在本键口径如实声明。",
                note=(
                    "条带几何平地近似；球形地球修正/聚束/TOPS 模式/距离徙动"
                    "校正不在本键口径如实声明（DBS 多普勒梯度同缺席）。"
                ),
            ),
            Boundary(
                quote='风险锚"）；DBS 多普勒梯度/聚束/TOPS 模式/距离徙动校正不在本键口径。',
                note=(
                    "零新引源（R3 报告预声明「教科书级零风险锚」）；出处以"
                    "模块 docstring 单源（Curlander & McDonough 1991+"
                    "Skolnik IRS ch.21 同口径）。"
                ),
            ),
            Boundary(
                quote="面）no-go 同源尊重——本族只做**成像几何指标**，不做成像处理链；",
                note=(
                    "雷达场景分工：rcs_targets/radar_eq/radar_detection_ext/"
                    "radar_clutter 为场景其余件；isac_ambiguity 波形指标面 "
                    "no-go 同源尊重——本族只做成像几何指标收官遥感场景。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w7s3_core_domains.py",
                quote="物理口径（#1c/#300 出处纪律；Curlander & McDonough 教科书几何恒等式，",
                tracked=True,
            ),
        ),
    ),
    # ─── aurora_g W12-S2 内核卡终批（5 张：R3_domain_expansion 立族的
    # aurora_g 新核五族收官——gnss_geometry/radar_clutter/microstrip_disc/
    # open_wire_line/wg_cavity_bpf，逐族三面盘点（注册键+docstring 出处节
    # 引文钉+锚树测试面 needles）全齐备；同笔 fmcw_radar 卡扩至全族 4 键
    # （W11-S4 扩展 2 键入 primary_entries/needles/公式/边界）。KD-1 各
    # 1 条实测渲染、anchors 零命中如实渲染（W6-S22 先例））──
    CardSpec(
        kernel_id="gnss_geometry",
        tagline=(
            "GNSS 定位几何三键：卫星视线几何→DOP 因子全族（GDOP/PDOP/"
            "HDOP/VDOP/TDOP）、方位角/仰角档同一 H 构建单源与 UERE→定位/"
            "授时误差恒等式+RSS 分解——导航接收机误差预算的几何底座"
            "（不做星历/轨道递推）。"
        ),
        modules=("calc_families/gnss_geometry",),
        primary_entries=(
            ("calc_families/gnss_geometry", "gdop_dop"),
            ("calc_families/gnss_geometry", "dop_from_satellite_geometry"),
            ("calc_families/gnss_geometry", "uere_to_position_error"),
        ),
        test_face_needles=(
            "gdop_dop",
            "dop_from_satellite_geometry",
            "uere_to_position_error",
        ),
        formulas=(
            Formula(
                title="几何矩阵与 DOP 因子全族",
                latex=(
                    "\\mathbf Q=(\\mathbf H^{\\mathsf T}\\mathbf H)^{-1},"
                    "\\quad \\mathrm{GDOP}=\\sqrt{\\mathrm{tr}\\,\\mathbf Q},"
                    "\\quad \\mathrm{PDOP}=\\sqrt{Q_{xx}+Q_{yy}+Q_{zz}}"
                ),
                quote="Q = (HᵀH)⁻¹，  DOP 因子 = Q 对角元开方：",
                quote2="GDOP=√tr(Q)、PDOP=√(Q_xx+Q_yy+Q_zz)、HDOP=√(Q_xx+Q_yy)、",
                cite=(
                    "Misra & Enge, Global Positioning System ch.6 / "
                    "Parkinson & Spilker v.1 ch.11 教科书口径；H 每行 "
                    "[u_x, u_y, u_z, 1]（u=用户→卫星单位视线矢量）"
                ),
            ),
            Formula(
                title="方位角/仰角→视线矢量（ENU 惯例，同一 H 单源）",
                latex="\\mathbf u=[\\cos el\\,\\sin az,\\ \\cos el\\,\\cos az,\\ \\sin el]",
                quote="u = [cos(el)·sin(az), cos(el)·cos(az), sin(el)]",
                quote2="与位置矢量档共享同一 H 构建与求逆单源（_dop_report）",
                cite=(
                    "同章 ENU 惯例；两档对同一几何给同一 DOP 面（锚树 "
                    "rel 1e-12 对照，#118 双路径）"
                ),
            ),
            Formula(
                title="UERE→定位/授时误差与 RSS 分解恒等式",
                latex=(
                    "\\sigma_{3d}=\\mathrm{GDOP}\\cdot\\mathrm{UERE},"
                    "\\quad \\sigma_{3d}^2=\\sigma_{horiz}^2+\\sigma_{vert}^2"
                    "+\\sigma_{time}^2c^2"
                ),
                quote="σ_3d=GDOP·UERE、σ_horiz=HDOP·UERE、σ_vert=VDOP·UERE、",
                quote2="GDOP²=PDOP²+TDOP²、PDOP²=HDOP²+VDOP²",
                cite=(
                    "Misra & Enge ch.6 等UERE 独立伪距误差口径；RSS 分解="
                    "tr(Q) 逐项恒等式"
                ),
            ),
            Formula(
                title="理想几何最小值（4 星正四面体）",
                latex="\\mathrm{GDOP}_{\\min}=\\sqrt{5/2}\\approx 1.5811",
                quote="GDOP_min=√(5/2)≈1.5811、PDOP=3/2、HDOP=√(3/2)、VDOP=√3/2、TDOP=1/2",
                cite=(
                    "Kihara & Okada 1984 IEEE Trans.AES 4 星最优几何经典结果；"
                    "任意单星追加 GDOP 单调不增（Sherman-Morrison，锚树数值钉）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="本族只做**定位几何/DOP/误差预算**，不做",
                note=(
                    "星历/轨道递推与 Klobuchar 电离层延迟系数表不在本族"
                    "（R3 审计列可弃，#122 如实缺席不凑）。"
                ),
            ),
            Boundary(
                quote="本族位置矢量档建议 ENU",
                note=(
                    "HDOP/VDOP 的水平/垂直语义只在 ENU（x=East、y=North、"
                    "z=Up）系下有物理意义；系旋转不变性=Q 对角元不变"
                    "（GDOP/PDOP 迹量任意直角系逐位一致）。"
                ),
            ),
            Boundary(
                quote="⇒ GDOP 单调不增",
                note=(
                    "任意单星追加使 HᵀH 加 PSD 秩一项 ⇒ Q Loewner 非增"
                    "（锚树数值钉）——加星不劣化是几何恒等不是经验。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w9s2_core_domains.py",
                quote="#222 triple-grep 证据（2026-10-19 本席开工实测）",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="radar_clutter",
        tagline=(
            "雷达杂波环境与 MTI 滤波五键：双脉冲对消器频响+盲速、Gaussian "
            "杂波谱改善因子（闭式+数值积分双路径）、面杂波 σ0 常数/γ 双档+"
            "杂波单元 RCS、Weibull 杂波幅度分布参数化与 CA-CFAR 滑窗检测链"
            "——雷达场景第五件（方程/起伏/RCS/波形指标之后的杂波面）。"
        ),
        modules=("calc_families/radar_clutter",),
        primary_entries=(
            ("calc_families/radar_clutter", "mti_frequency_response"),
            ("calc_families/radar_clutter", "mti_improvement_factor"),
            ("calc_families/radar_clutter", "clutter_sigma0_model"),
            ("calc_families/radar_clutter", "weibull_clutter_model"),
            ("calc_families/radar_clutter", "cell_averaging_cfar"),
        ),
        test_face_needles=(
            "mti_frequency_response",
            "mti_improvement_factor",
            "clutter_sigma0_model",
            "weibull_clutter_model",
            "cell_averaging_cfar",
        ),
        formulas=(
            Formula(
                title="双脉冲对消器频响与盲速",
                latex=(
                    "|H(f)|=2\\left|\\sin(\\pi f T_r)\\right|,\\quad "
                    "v_n=\\frac{n\\lambda\\,\\mathrm{PRF}}{2}"
                ),
                quote="H(f) = 1 − e^{−j2πfTr} = 2j·sin(πfTr)·e^{−jπfTr}",
                quote2="v_n = f_D·λ/2 = n·λ/(2Tr) = n·λ·PRF/2（多普勒",
                cite=(
                    "Skolnik IRS ch.15 MTI/Richards FRSP ch.2 教科书口径；"
                    "凹口 f=k·PRF 逐位、峰值 |H|=2 于 f=(k+1/2)·PRF 逐位、"
                    "周期恒等 H(f+PRF)=H(f)"
                ),
            ),
            Formula(
                title="Gaussian 杂波谱改善因子",
                latex=(
                    "P_{out}=2P_c(1-\\rho),\\quad "
                    "\\rho=e^{-2\\pi^2\\sigma_f^2T_r^2},\\quad "
                    "I=\\frac{1}{1-\\rho}"
                ),
                quote="P_out = ∫|H(f)|²·S(f)df = 2·P_c·(1−ρ)，  ρ = exp(−2π²·σ_f²·Tr²)",
                quote2="⇒ **I = 1/(1−ρ)**",
                cite=(
                    "Skolnik MTI 章口径；本键同文件数值积分独立复算 P_out"
                    "（#118 双路径：闭式 vs 复化梯形积分）；SCV=I−所需输出 "
                    "SCNR（Richards 口径）"
                ),
            ),
            Formula(
                title="面杂波 σ0 双档与杂波单元 RCS",
                latex=(
                    "\\sigma^0=\\gamma\\sin\\psi,\\quad "
                    "A_c=R\\,\\rho_R\\,\\theta_{az}\\sec\\psi,\\quad "
                    "\\sigma_c=\\sigma^0A_c"
                ),
                quote="σ0 = γ·sin(ψ)（Skolnik/Richards/Nathanson 通用",
                quote2="Ac = R·ρ_R·θ_az·sec(ψ)（Greco 讲义 slide 7",
                cite=(
                    "constant-γ 低角地杂波通用模型（ψ→0⁺ ⇒ σ0→0、ψ=90° ⇒ "
                    "σ0=γ 逐位）；杂波 RCS 恒等式 σc=σ0·Ac"
                ),
            ),
            Formula(
                title="Weibull 杂波幅度分布（2 参参数化）",
                latex=(
                    "f(x)=\\frac{k}{\\lambda}\\left(\\frac{x}{\\lambda}"
                    "\\right)^{k-1}e^{-(x/\\lambda)^k},\\quad "
                    "\\mathrm{mean}=\\lambda\\,\\Gamma(1+1/k)"
                ),
                quote="f(x) = (k/λ)·(x/λ)^{k−1}·exp(−(x/λ)^k)，  F(x) = 1−exp(−(x/λ)^k)",
                quote2="mean=λ·Γ(1+1/k)、var=λ²·[Γ(1+2/k)−Γ²(1+1/k)]；",
                cite=(
                    "Fay-Clarke-Peters 1977 海杂波 Weibull 首提+Skolnik/"
                    "Richards 教科书口径；k=1 退化指数、k=2 退化 Rayleigh "
                    "逐位锚"
                ),
            ),
            Formula(
                title="CA-CFAR 滑窗门限（参考窗+保护带）",
                latex=(
                    "T=\\alpha\\,\\mathrm{mean}(Z)=\\beta\\Sigma Z,\\quad "
                    "\\beta=\\mathrm{Pfa}^{-1/N}-1,\\quad \\alpha=N\\beta"
                ),
                quote="T = α·mean(Z) = β·ΣZ，  β = Pfa^{−1/N} − 1，  α = N·β",
                cite=(
                    "Richards FRSP 2ed ch.6 指数噪声单元标准结果；与 "
                    "radar_eq.ca_cfar_threshold 同式双源（#118 同仓双锚："
                    "彼键=纯因子/Pd 闭式、本键=实测窗+保护带几何+判决链）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="本键同文件数值积分独立复算 P_out（#118 双路径：闭式 vs 复化梯形积分，",
                note=(
                    "改善因子闭式与数值积分双路径互证（非同一公式的两次"
                    "抄写）。"
                ),
            ),
            Boundary(
                quote="（Greco 讲义只给结构不给逐字系数表）——按 finline",
                note=(
                    "GIT 海杂波档缺席如实声明（多区域插值系数表原表不可达，"
                    "#122 不凑）；本键不做表插值——表数字化属数据面。"
                ),
            ),
            Boundary(
                quote="本键只做杂波幅度统计参数化。",
                note=(
                    "core/aging、core/probability_paper、alt_planning 的 "
                    "Weibull=可靠性寿命/作图回归域（同名异域不撞）。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w6s3_core_domains.py",
                quote="雷达杂波与 MTI 滤波族（aurora_g W6-S3 席立族，R3_domain_expansion 视角4",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="microstrip_disc",
        tagline=(
            "微带全族闭式十键：不连续寄生七件——直角弯（未切角/50% "
            "切角双档 Kirschning）、T 接头（Hammerstad-Bekkadal）、"
            "宽度阶跃（Garg-Bahl）、最优切角百分式（Douville-James）、"
            "串联间隙（Garg-Bahl π 网络，W11-S4）、开路端效应（HB/KJK "
            "双档，W11-S4）与十字结四口网络（W15-S2）+损耗/接地过渡"
            "三件——线衰减率（Hammerstad-Jensen，W15-S2）、接地过孔"
            "（Goldfarb-Pucel，W15-S2）与开路端辐射电导（Balanis 两"
            "极限，W15-S2）——PCB layout 节点的寄生参数实体与损耗面"
            "（fake 裁判面「弯角寄生零」的对拍锚）。"
        ),
        modules=("calc_families/microstrip_disc",
                 "calc_families/microstrip_extra"),
        primary_entries=(
            ("calc_families/microstrip_disc", "microstrip_bend_parasitics"),
            ("calc_families/microstrip_disc",
             "microstrip_t_junction_parasitics"),
            ("calc_families/microstrip_disc", "microstrip_step_parasitics"),
            ("calc_families/microstrip_disc", "microstrip_optimal_miter"),
            ("calc_families/microstrip_disc",
             "microstrip_open_end_parasitics"),
            ("calc_families/microstrip_disc", "microstrip_gap_parasitics"),
            ("calc_families/microstrip_extra",
             "microstrip_cross_parasitics"),
            ("calc_families/microstrip_extra", "microstrip_attenuation"),
            ("calc_families/microstrip_extra", "microstrip_via_short"),
            ("calc_families/microstrip_extra",
             "microstrip_open_end_radiation"),
        ),
        test_face_needles=(
            "microstrip_bend_parasitics",
            "microstrip_t_junction_parasitics",
            "microstrip_step_parasitics",
            "microstrip_optimal_miter",
            "microstrip_open_end_parasitics",
            "microstrip_gap_parasitics",
            "microstrip_cross_parasitics",
            "microstrip_attenuation",
            "microstrip_via_short",
            "microstrip_open_end_radiation",
        ),
        formulas=(
            Formula(
                title="未切角直角弯寄生 L/C（Kirschning 1983）",
                latex=(
                    "C=W\\left[(10.35\\,\\varepsilon_r+2.5)\\tfrac{W}{h}"
                    "+(2.6\\,\\varepsilon_r+5.64)\\right]\\ \\mathrm{pF},"
                    "\\quad L=220h\\left(1-1.35\\,e^{-0.18(W/h)^{1.39}}"
                    "\\right)\\ \\mathrm{nH}"
                ),
                quote="C = W·[(10.35·εr+2.5)·(W/h) + (2.6·εr+5.64)]    pF（W 取 m）",
                quote2="L = 220·h·(1 − 1.35·exp(−0.18·(W/h)^1.39))      nH（h 取 m）",
                cite=(
                    "Kirschning 1983 MTT-S 式(20)(21) 逐字（经 Poole-Darwazeh "
                    "2015 Lecture 3 与 TU/e van Meeteren thesis 双源）；"
                    "W/h≲1.4 负值=拟合域外显式拒绝"
                ),
            ),
            Formula(
                title="50% 切角直角弯（同源式(22)(23)，qucsator 同式）",
                latex=(
                    "C=W\\left[(3.93\\,\\varepsilon_r+0.62)\\tfrac{W}{h}"
                    "+(7.6\\,\\varepsilon_r+3.80)\\right]\\ \\mathrm{pF},"
                    "\\quad L=440h\\left(1-1.062\\,e^{-0.177(W/h)^{0.947}}"
                    "\\right)\\ \\mathrm{nH}"
                ),
                quote="C = W·[(3.93·εr+0.62)·(W/h) + (7.6·εr+3.80)]    pF（W 取 m）",
                quote2="L = 440·h·(1 − 1.062·exp(−0.177·(W/h)^0.947))   nH（h 取 m）",
                cite=(
                    "同源式(22)(23) 逐字（=qucsator msmbend.cpp 可执行同式）；"
                    "Douville-James 1978 实测结论：50% 切角对全部宽度/高度/"
                    "介电常数/频率均改善反射（Visser 2007 EuCAP 转述）"
                ),
            ),
            Formula(
                title="T 接头臂长修正与并联电纳（Hammerstad-Bekkadal）",
                latex=(
                    "d_{a,db}=0.055\\,D_3\\tfrac{Z_{a,b}}{Z_3}"
                    "\\left(1-2\\tfrac{Z_{a,b}}{Z_3}\\tfrac{f^2}{f_p^2}"
                    "\\right),\\quad L_{a,b}=\\tfrac{W_3}{2}-d_{a,db}"
                ),
                quote="da,db = 0.055·D_3·(Z_{a,b}/Z_3)·(1 − 2·(Z_{a,b}/Z_3)·(f/f_p)^2)",
                cite=(
                    "HB 1975 ELAB STF44 A74169（经 qucsator mstee.cpp 可执行"
                    "逐字转录）；负长度修正=参考面伸入结区簿记值，放行并输出 "
                    "reference_planes_crossed 标记位；da·db<0 显式拒绝"
                ),
            ),
            Formula(
                title="宽度阶跃等效 L/C（Garg-Bahl，只收收窄阶跃）",
                latex=(
                    "C_s=\\sqrt{W_1W_2}\\left[(10.1\\lg\\varepsilon_r+2.33)"
                    "\\tfrac{W_1}{W_2}-12.6\\lg\\varepsilon_r-3.17\\right]"
                    "\\ \\mathrm{pF}"
                ),
                quote="Cs = √(W1·W2)·[(10.1·lg εr+2.33)·(W1/W2) − 12.6·lg εr − 3.17]  pF",
                quote2="Ls = h·[(r−1)·(40.5+0.2·(r−1)) − 75·lg r]（r=W1/W2）           nH",
                cite=(
                    "Garg-Bahl 1978（经 qucsator msstep.cpp 可执行逐字，"
                    "Qucs 手册引 Gupta [38]）；W1≤W2 时 Cs 括号为负=拟合域外"
                    "显式拒绝；W1=W2 时 Ls≡0 逐位（直通退化恒等经同文件"
                    "双路径锚）"
                ),
            ),
            Formula(
                title="串联间隙 π 网络电容（Garg-Bahl，W11-S4）",
                latex=(
                    "C_s=5\\!\\times\\!10^{-10}h\\,e^{-1.86\\,s/h}"
                    "\\,Q_1\\left[1+4.19\\left(1-e^{-0.785\\sqrt{1/W_1'}W_2'}"
                    "\\right)\\right]\\ \\mathrm{F}"
                ),
                quote="Cs = 5e-10·h·e^(−1.86·s')·Q1·[1+4.19·(1−e^(−0.785·√(1/W1')·W2'))]",
                cite=(
                    "Garg-Bahl（经 qucsator msgap.cpp 可执行逐字转录，"
                    "Qucs 手册 §Microstrip gap）；等宽特化与 Bahl《Microstrip "
                    "Lines and Slotlines》口径第三方转写互证；宽比 >3 显式"
                    "拒绝（validity 注释原文）"
                ),
            ),
            Formula(
                title="开路端效应 Δl 双档与等效电容（HB/KJK，W11-S4）",
                latex=(
                    "C_{end}=\\frac{\\Delta l\\sqrt{\\varepsilon_{eff}}}"
                    "{Z_0c_0},\\quad "
                    "\\frac{|\\Delta l_K-\\Delta l_{HB}|}{\\Delta l_{HB}}"
                    "\\le 5\\%\\ (w/h\\le 2;\\ \\varepsilon_r{\\ge}9\\ \\text{full})"
                ),
                quote="C_end = Δl·√εeff/(Z0·c0)",
                quote2="≤5% 一致带包络随 εr 渐宽——εr≤5 W/h≤2.0、εr 6–7 W/h≤2.5",
                cite=(
                    "HB 0.412 档=仓内单源 slotline_transitions 复用+"
                    "Kirschning-Jansen-Koster 1981 档（经 qucsator msopen.cpp "
                    "calcCend 逐字）；双档横向一致性带如实记带锚不凑逐位"
                ),
            ),
            Formula(
                title="十字结臂并联电容与中心电感（HB 系拟合，W15-S2）",
                latex=(
                    "C_i=10^{-12}W_i\\left(0.25X\\,W_{1h}^{-1/3}-60+"
                    "\\tfrac{0.5}{W_{2h}}-0.375W_{1h}(1-W_{2h})\\right),"
                    "\\quad L_5\\leftarrow 0.8\\,L_5"
                ),
                quote="C_i = 1e-12·W_i·(0.25·X·W1h^(−1/3) − 60 + 0.5/W2h",
                quote2="L5 ← L5·0.8（手册明示经验改进",
                cite=(
                    "qucsator mscross.cpp 可执行逐字+Qucs 手册 §Microstrip "
                    "cross 式(11.226)-(11.231) 双源（基准 εr=9.9、精度 5%）；"
                    "L5<0=手册明示模型固有（标记位放行）；εr=9.9 时式(11.231) "
                    "修正恒 1.0 逐位"
                ),
            ),
            Formula(
                title="微带导体/介质衰减率（Hammerstad-Jensen，W15-S2）",
                latex=(
                    "\\alpha_c=\\frac{R_s}{Z_0W}K_iK_r,\\quad "
                    "K_i=e^{-1.2(Z_0/\\eta_0)^{0.7}},\\quad "
                    "\\alpha_d=\\tfrac{\\pi}{\\lambda_0}\\tfrac{\\varepsilon_r}"
                    "{\\sqrt{\\varepsilon_{eff}}}\\tfrac{\\varepsilon_{eff}-1}"
                    "{\\varepsilon_r-1}\\tan\\delta"
                ),
                quote="αc = Rs/(Z0·W)·Ki·Kr                 （导体衰减 Np/m，11.80）",
                quote2="αd = (π/λ0)·(εr/√εeff)·((εeff−1)/(εr−1))·tanδ",
                cite=(
                    "qucsator msline.cpp analyseLoss 可执行逐字+Qucs 手册 "
                    "式(11.79)-(11.83) 双源；αd 同式同仓双源=thermal_iteration"
                    "（εeff 源不同如实注记）；Ki 档 t>3δ 越窗标记"
                ),
            ),
            Formula(
                title="接地过孔 L/R（Goldfarb-Pucel 1991，W15-S2）",
                latex=(
                    "R_{dc}=\\frac{\\rho h}{\\pi(r^2-(r-t)^2)},\\quad "
                    "R(f)=R_{dc}\\sqrt{1+f/f_\\delta},\\quad "
                    "L=\\tfrac{\\mu_0}{2\\pi}\\left[h\\ln\\tfrac{h+"
                    "\\sqrt{r^2+h^2}}{r}+\\tfrac{3}{2}(r-\\sqrt{r^2+h^2})"
                    "\\right]"
                ),
                quote="R_dc = ρ·h/(π·(r²−(r−t)²))           （空心圆柱 DC 电阻）",
                quote2="L    = (μ0/2π)·[h·ln((h+√(r²+h²))/r) + 1.5·(r−√(r²+h²))]（11.232）",
                cite=(
                    "Qucs 手册 式(11.232)-(11.234)+finetune.co.jp 独立转录"
                    "双源；qucsator msvia.cpp 电感漏除 2π 偏差如实注记（数值"
                    "锤：2mil GaAs D/H=0.5 手册形态 ~9.4pH 与 Microwaves101 "
                    "工程口径相合，qucsator 形态 ~66pH 矛盾）；h<0.03λ0 守卫"
                ),
            ),
            Formula(
                title="开路端辐射电导分段式（Balanis 两极限，W15-S2）",
                latex=(
                    "G_r=\\begin{cases}\\tfrac{1}{90}(W/\\lambda_0)^2 & "
                    "W/\\lambda_0\\le1\\\\[2pt]\\tfrac{1}{120}(W/\\lambda_0) "
                    "& W/\\lambda_0\\ge2\\end{cases},\\quad "
                    "\\tan\\delta_{open}=\\frac{G_r}{\\omega C_{end}}"
                ),
                quote="G_r = (1/90)·(W/λ0)²                 （W/λ0 ≤ 1）",
                quote2="G_r = (1/120)·(W/λ0)                 （W/λ0 ≥ 2）",
                cite=(
                    "Balanis 4th Ch.14 槽辐射电导两极限（SDSMT 讲义逐字+"
                    "AWR 教程引 Bahl-Bhartia 1980 p.51 同式）；1<x<2 线性"
                    "内插=本键声明工程约定（Balanis 只给极限，如实记档）；"
                    "宽槽档与 patch_rin_edge_balanis 积分式 k0h→0 同仓渐近"
                    "对拍"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="本族只做微带不连续寄生参数闭式（L/C/参考面修正/频响面）。",
                note=(
                    "rf_line=均匀线正反解（本族 T 接/阶跃内部复用同源 Z_i/"
                    "εeff_i 不另立口径）；pcell_dsl/rf_trace_geometry=切角"
                    "几何基元；coupled_microstrip=HB ΔW 均匀线线宽修正；"
                    "patch_fringing_delta_l=patch 每边缘 fringing（仍归 "
                    "synthesis 单源）；fake_adapter=理想裁判面（寄生零）。"
                ),
            ),
            Boundary(
                quote="本键放行并输出 reference_planes_crossed 标记位如实呈现；da·db<0",
                note=(
                    "负长度修正（规范几何下即出现）=参考面伸入结区的簿记值"
                    "（qucsator 无守卫照常装配同构）；da·db<0（f 过近高阶模"
                    "截止、√(da·db) 结构破裂）显式 ValueError。"
                ),
            ),
            Boundary(
                quote='validity（qucsator msgap.cpp 注释原文 "equations are valid for',
                note=(
                    "间隙拟合式宽比域 1≤W2/W1≤3（注释原文），超域显式拒绝；"
                    "g→∞ 时 Cs 指数归零、等宽 W1=W2 时 C1==C2 逐位（flip "
                    "恒等锚）。"
                ),
            ),
            Boundary(
                quote="**qucsator 可执行偏差如实注记**：msvia.cpp",
                note=(
                    "接地过孔电感：qucsator msvia.cpp `ind = MU0·(...)` 漏除 "
                    "2π（手册 11.232=μ0/2π、finetune.co.jp 转录同式；"
                    "constants.h 实测 MU0=4πe-7）——本键按手册/G-P 形态"
                    "落地并注记偏差（数值锤 2mil GaAs ~9.4pH 相合）。"
                ),
            ),
            Boundary(
                quote="1<x<2 线性内插（工程惯例；Balanis 只给两极限不设内插条款，",
                note=(
                    "开路端辐射电导：两极限为 Balanis 逐字、1<x<2 内插=本键"
                    "声明工程约定档（Bahl 系通行形态）——约定面如实记档不冒充"
                    "原文条款（#122）。"
                ),
            ),
            Boundary(
                quote="不物理，qucsator 无守卫照常装配，本键放行并输出",
                note=(
                    "十字结中心电感 L5<0=手册明示模型固有（脱离外部微带线"
                    "不物理）——qucsator 同构放行+center_inductance_negative "
                    "标记位；L 拟合域 [0.5,2] 越窗标记不硬拒。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w6s3_core_domains.py",
                quote="微带不连续寄生闭式族（aurora_g W6-S3 席，R3_domain_expansion 视角1 A1",
                tracked=True,
            ),
            DocRef(
                path="tests/unit/test_w15s2_core_domains.py",
                quote="微带全族扩展四键（aurora_g W15-S2 席，R3_domain_expansion §④ A1 余量",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="open_wire_line",
        tagline=(
            "平衡开线两键：开架双线（双极坐标精确式）与单线对地（镜像定理"
            "精确式）的 Z0/C′/L′/延迟/趋肤衰减——rf_line 六型基板线之外"
            "唯一无基板开架平行线（模型域全域精确，非细线近似档）。"
        ),
        modules=("calc_families/open_wire_line",),
        primary_entries=(
            ("calc_families/open_wire_line", "open_two_wire_line"),
            ("calc_families/open_wire_line", "open_wire_over_ground"),
        ),
        test_face_needles=("open_two_wire_line", "open_wire_over_ground"),
        formulas=(
            Formula(
                title="开架双线（双极坐标精确式）",
                latex=(
                    "Z_0=\\frac{\\eta_0}{\\pi\\sqrt{\\varepsilon_r}}"
                    "\\,\\mathrm{acosh}\\!\\frac{D}{2a},\\quad "
                    "C'=\\frac{\\pi\\varepsilon_0\\varepsilon_r}"
                    "{\\mathrm{acosh}(D/2a)}"
                ),
                quote="Z0 = (η0/(π·√εr))·acosh(D/(2a))",
                quote2="C' = π·ε0·εr/acosh(D/(2a))",
                cite=(
                    "Ramo-Whinnery-Van Duzer §2.6 / Pozar 4th ed eq.(2.74)"
                    "（与 core/corona.py two_wire 几何因子 arcosh(D/2r) 同核"
                    "双源）；D≫a 渐近对数式与 acosh 式逐位同值（同式双形态锚）"
                ),
            ),
            Formula(
                title="单线对地（镜像定理精确式）",
                latex=(
                    "Z_0=\\frac{\\eta_0}{2\\pi\\sqrt{\\varepsilon_r}}"
                    "\\,\\mathrm{acosh}\\!\\frac{h}{a}\\approx"
                    "\\frac{60}{\\sqrt{\\varepsilon_r}}\\ln\\frac{2h}{a}"
                ),
                quote="Z0 = (η0/(2π·√εr))·acosh(h/a)     ≈ (60/√εr)·ln(2h/a)（h≫a）",
                quote2="C' = 2π·ε0·εr/acosh(h/a)",
                cite=(
                    "镜像定理（wire+镜像电荷 −q 恰为 D=2h 双线奇激励半问题，"
                    "midplane 精确等位面；Jackson §2.2 级教科书恒等式）"
                ),
            ),
            Formula(
                title="镜像退化恒等式（跨键）",
                latex="Z_{0,\\mathrm{wg}}(h)=\\tfrac{1}{2}Z_{0,\\mathrm{2w}}(D=2h)",
                quote="Z0_wg(h) = Z0_two_wire(D=2h)/2——激励",
                cite=(
                    "#118 跨键恒等（对地电压=差分电压之半）逐位可验；h→a⁺ "
                    "时 acosh→0 → Z0→0（导线触地=短路，物理极限行为正确）"
                ),
            ),
            Formula(
                title="趋肤衰减面（freq+conductivity 同给时）",
                latex=(
                    "R'=\\frac{R_s}{2\\pi a},\\quad "
                    "\\alpha_c=\\frac{R'}{2Z_0}\\ \\mathrm{Np/m}"
                ),
                quote="R'=Rs/(2πa)，双线回路两导体串联",
                quote2="αc=R'/(2Z0) Np/m",
                cite=(
                    "Rs=√(πfμ0/σ)（与 core/coax_line/conductor_loss 同核"
                    "三源）；低损线通用式（Pozar eq.(2.87) 口径）→dB=8.686·Np"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote="本族只做开架平行线单位长参数（Z0/C'/L'/延迟/趋肤衰减）。",
                note=(
                    "rf_line=基板线六型（有基板口径）；coax_line=同轴嵌套；"
                    "corona=电晕起始场强判据（arcosh 仅几何因子同核、量纲 "
                    "Ω·m）；wirebond=键合线部分电感（无传输线参数面）。"
                ),
            ),
            Boundary(
                quote="邻近效应修正不建模（如实边界；σ=None 或 freq=None 不出衰减面）。",
                note=(
                    "近距双线的邻近效应修正不建模；σ=None 或 freq=None 不出"
                    "衰减面（如实缺档）。"
                ),
            ),
            Boundary(
                quote="故本键拒绝该误形态——h/a 为半径口径，直径口径 2h/d 与",
                note=(
                    "arccosh(2h/a) 形态在 h→a 给非零 Z0=非物理，显式拒绝；"
                    "h/a 半径口径与 2h/d 直径口径等价。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w10s4_core_domains.py",
                quote="平衡开线族（aurora_g W10-S4 席，R3_domain_expansion 视角1 A2——rf_line",
                tracked=True,
            ),
        ),
    ),
    CardSpec(
        kernel_id="wg_cavity_bpf",
        tagline=(
            "波导膜片耦合腔带通滤波器综合链两键：g_k→J 倒置器→感性膜片"
            "电纳/开口/腔长全链综合与膜片电纳 λg 标度+腔电角逐频 ABCD 级联"
            "频响——滤波器实现族的波导腔体侧（Cohn 1957 原文链全文逐字"
            "核验）。"
        ),
        modules=("calc_families/wg_cavity_bpf",),
        primary_entries=(
            ("calc_families/wg_cavity_bpf", "wg_cavity_bpf_synthesize"),
            ("calc_families/wg_cavity_bpf", "wg_cavity_bpf_response"),
        ),
        test_face_needles=("wg_cavity_bpf_synthesize", "wg_cavity_bpf_response"),
        formulas=(
            Formula(
                title="设计变量=导内波长带限（Cohn 原文口径）",
                latex=(
                    "\\lambda_{g0}=\\frac{\\lambda_{g1}+\\lambda_{g2}}{2},"
                    "\\quad w=\\frac{\\lambda_{g1}-\\lambda_{g2}}"
                    "{\\lambda_{g0}}"
                ),
                quote="λg0 = (λg1 + λg2)/2                    （Cohn eq.(19) 算术均值）",
                quote2="w = (λg1 − λg2)/λg0                    （导内波长域相对带宽）",
                cite=(
                    "S.B. Cohn, Direct-Coupled-Resonator Filters, Proc. IRE "
                    "45(2) 1957 pp.187-196（Fig.5 设计公式族全文逐字核验；"
                    "「the desired guide-wavelength passband limits」原文口径）"
                ),
            ),
            Formula(
                title="J 倒置器（πw/2 公式族）",
                latex=(
                    "\\frac{J_{01}}{Z_0}=\\sqrt{\\frac{\\pi w}{2g_0g_1}},"
                    "\\quad \\frac{J_{j,j+1}}{Z_0}=\\frac{\\pi w/2}"
                    "{\\sqrt{g_jg_{j+1}}}"
                ),
                quote="J01/Z0 = √(πw/(2·g0·g1))",
                quote2="Jj,j+1/Z0 = (πw/2)/√(gj·gj+1)（内部 j=1..N−1）",
                cite=(
                    "与 coupled_line_bpf/Pozar §8.6.2 同形（已双源在案）；"
                    "g_k 走 core/matching.chebyshev_g_values 单源"
                ),
            ),
            Formula(
                title="膜片归一化电抗与开口反解",
                latex=(
                    "x_j=\\frac{J_j/Z_0}{1-(J_j/Z_0)^2},\\quad "
                    "d=\\frac{2a}{\\pi}\\arctan\\sqrt{\\frac{\\lambda_{g0}x}{a}}"
                ),
                quote="x_j = (J_j/Z0)/(1−(J_j/Z0)²)      （感性膜片，x>0）",
                quote2="d=(2a/π)·arctan(√(λg0·x/a))，正反解",
                cite=(
                    "Cohn Fig.13(e) 设计反演式；膜片开口=消费 "
                    "wg_iris_susceptance 同一薄膜片闭式反解（roundtrip 逐位）"
                ),
            ),
            Formula(
                title="腔长（Cohn Fig.5 φi 式）",
                latex=(
                    "\\theta_i=\\pi-\\tfrac{1}{2}\\left[\\arctan(2x_{i-1,i})"
                    "+\\arctan(2x_{i,i+1})\\right],\\quad "
                    "l_i=\\frac{\\theta_i\\lambda_{g0}}{2\\pi}"
                ),
                quote="θ_i = π − ½[arctan(2x_{i−1,i}) + arctan(2x_{i,i+1})]",
                quote2="l_i = θ_i·λg0/(2π)",
                cite=(
                    "负线长簿记 θi+½(φ_{i−1}+φ_i)=180°（Cohn 原文口径）"
                ),
            ),
            Formula(
                title="频响面：膜片电抗 λg 反比标度+腔电角逐频级联",
                latex=(
                    "x\\propto\\frac{\\lambda_{g0}}{\\lambda_g(f)},\\quad "
                    "\\psi_i(f)=\\frac{2\\pi l_i}{\\lambda_g(f)}"
                ),
                quote="The iris reactance is assumed to vary in inverse proportion to guide",
                quote2="b ∝ λg ⟹ x ∝ λg0/λg(f)，",
                cite=(
                    "Cohn 原文逐字（λg 标度）——与薄膜片闭式自身 λg 依赖同"
                    "标度（两路径逐位同值=#118 同文件双路径）；ABCD→S 级联"
                    "在 λg 轴对称（Cohn 原文性质）"
                ),
            ),
        ),
        boundaries=(
            Boundary(
                quote='least 20 percent in guide wavelength"——域内高档通带纹波畸变渐显（原文',
                note=(
                    "精度域 w≤0.2 显式守卫（Cohn 原文 good results with "
                    "bandwidths of at least 20 percent）；域内高档纹波畸变"
                    "渐显（原文 Fig.8/9 同行为），消费者须以响应键全带复核。"
                ),
            ),
            Boundary(
                quote="薄膜片近似（零厚度感性窗，wg_iris_susceptance 同口径）；厚膜片/销钉/",
                note=(
                    "厚膜片/销钉/谐振窗结构不在此口径；无耗假设（Q→∞），"
                    "有限 Q 插损面不入键面。"
                ),
            ),
            Boundary(
                quote="f≤TE10 截止显式拒绝（_frequency 守卫同源）。",
                note=(
                    "f≤TE10 截止显式拒绝（与 wg_iris/waveguide_closed_form "
                    "同源守卫）。"
                ),
            ),
        ),
        doc_refs=(
            DocRef(
                path="tests/unit/test_w10s4_core_domains.py",
                quote="波导膜片耦合腔带通滤波器综合链（aurora_g W10-S4 席，R3_domain_expansion",
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
    for name, text in _test_texts().items():
        if name == "test_kernel_cards.py":
            continue
        if _references_module(text, stem) or any(n in text for n in extra_needles):
            out.append((name, len(re.findall(r"def (test_\w+)", text))))
    return out


_TESTS_TEXT_CACHE: dict[str, str] | None = None


def _test_texts() -> dict[str, str]:
    """tests/unit 全量文本的进程级快照（单次装载）。

    生成器对每张卡的每个模块都调 referencing_tests()——零缓存时
    6 测试×74 specs×~1090 文件 ≈48 万次全树读，是 kernel_cards 六件
    门测各 64-83s 与预检 docs 再生面 466s 的主因（aurora_h R3 #1）。
    dict 保插入序=sorted(glob) 序，下游遍历序与旧实现逐字节一致；
    单进程内文本不可变假设=生成器只读树（测试进程同一性成立）。
    """
    global _TESTS_TEXT_CACHE
    if _TESTS_TEXT_CACHE is None:
        _TESTS_TEXT_CACHE = {
            p.name: p.read_text(encoding="utf-8")
            for p in sorted(TESTS_UNIT_DIR.glob("test_*.py"))
        }
    return _TESTS_TEXT_CACHE


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
        for rel, text in sorted(_consumer_texts(base).items()):
            if _references_module(text, stem):
                found.append((label, rel))
    return found


_CONSUMER_TEXT_CACHE: dict[Path, dict[str, str]] = {}


def _consumer_texts(base: Path) -> dict[str, str]:
    """消费面目录全 .py 文本快照（目录级一次装载，同 _test_texts 动机）。"""
    snap = _CONSUMER_TEXT_CACHE.get(base)
    if snap is None:
        snap = {
            p.relative_to(REPO_ROOT).as_posix(): p.read_text(encoding="utf-8")
            for p in sorted(base.rglob("*.py"))
        }
        _CONSUMER_TEXT_CACHE[base] = snap
    return snap


_KD1_DATA_CACHE: list[dict[str, Any]] | None = None


def kd1_entries(kernel_file: str) -> list[dict[str, Any]]:
    # KD1 大表（formula_provenance.yaml ~300 条目级嵌套）逐卡重解析是
    # 六件门测 44-58s 的真瓶颈（aurora_h R3 #1+本席 profile 实证 379 次
    # safe_load=145s）——进程级解析一次按 kernel_file 过滤。
    global _KD1_DATA_CACHE
    if _KD1_DATA_CACHE is None:
        _KD1_DATA_CACHE = list(_load_yaml(KD1_YAML).get("entries", []))
    entries = [e for e in _KD1_DATA_CACHE
               if e.get("kernel_file") == kernel_file]
    return sorted(entries, key=lambda e: str(e.get("formula_id", "")))


_XCP_CACHE: dict[str, Any] | None = None


def xcp_kernels() -> dict[str, Any]:
    global _XCP_CACHE
    if _XCP_CACHE is None:
        data = _load_yaml(XCP_YAML)
        kernels = data.get("kernels")
        if not isinstance(kernels, dict) or not kernels:
            raise RuntimeError("precision_profiles.yaml 缺 kernels 键或为空")
        _XCP_CACHE = kernels
    return _XCP_CACHE


_ANCHOR_ENTRIES_CACHE: list[dict[str, Any]] | None = None


def anchor_entries() -> list[dict[str, Any]]:
    # 同 kd1_entries：anchors.yaml 逐卡重解析+全树 walk 是门测热点，
    # 进程级解析一次（walk 结果缓存，调用方只读）。
    global _ANCHOR_ENTRIES_CACHE
    if _ANCHOR_ENTRIES_CACHE is None:
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
        _ANCHOR_ENTRIES_CACHE = found
    return _ANCHOR_ENTRIES_CACHE


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
            exist_note = "" if ref.tracked else "（runs/ 证据面，gitignored，存在性不作测试断言）"
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
        description="XA-8 内核域文档卡生成器（首批 5 张 + W3-S13 批一 11 张 + "
                    "W4-S19 批二 8 张 + aurora_f 前置批 3 张 + W6-S22 扩面 9 张"
                    " + aurora_g W1-S3 批三 9 张 + aurora_g W2-S3 批四 9 张"
                    " + aurora_g W3-S3 批五 6 张 + aurora_g W6-S4 批六 6 张"
                    " + aurora_g W8-S1 批七 3 张 + aurora_g W12-S2 终批 5 张）")
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
