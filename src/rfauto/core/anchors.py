"""DP-3 物理标定锚注册表——纯求值内核（零 IO）。

规格：规格深案 §DP-3。锚 = (模板族 × 引擎对 ×
域) → (常量 | 曲线 | 公式 | 指针)，描述引擎对系统偏差（PDK corner/compact
model类比）。pointer 锚=双值分歧指针（值在模型档案不就地求值，HFSS 窗
B→A 批启用）。本模块只做求值与域守卫，一切 IO（YAML 装载/provenance 路径核对）
在 infra/anchors_store.py，JSON 薄面在 service/anchors_service.py。

核心语义（消费者 API）：
- ``AnchorSet.resolve_anchor(anchor_id, params)`` ->
  ``{hit, value, source: anchor|fallback, version, domain_ok, ...}``；
  域外/未知/非 active 一律 source=fallback（结构化回退闭式，不抛）；
- ``AnchorSet.note_anchor_residual(anchor_id, point, observed)``：漂移检测，
  |残差| > max(3σ, 5%·|锚值|) → 内存面翻 stale + 告警字段（注册表运行时
  只读，落盘回填走人工 commit——Agent 写面隔离， 规则 6）；
- ``find_anchors(template_family, quantity)`` / ``apply_anchor_correction(
  family, quantity, params)``（XC-A，规格 §B-2）：族×量投影查询 + 偏差面
  设计修正（三拒绝门 + 修正量包络）——与 warm_start（参数面优化起点）
  分层不混，详见 UNCERTAINTY_REL_MAX_DEFAULT 常量旁的分层声明；
- ``register_analytic_anchor(family, quantity, value, semantics)`` /
  ``anchor_coverage(anchor_set)``（XA-10，round18）：analytic-anchor 轻条目
  注册 helper（closedform-v1 形态纯构造，零 IO——写面归注册链批次）与
  锚覆盖按族统计面，详见节内划界声明。

求值安全（铁律 6/7 同源）：公式锚表达式只允许 build_library 词表能产出的
语法（常量/已声明变量/四则/幂、sqrt/log），复用 0cz register_symbolic_formula
的 AST 白名单校验器（core/calculators._validate_symbolic_node，单一白名单
源）后才 eval；拒绝任何经表达式字符串进入的任意代码。

曲线锚：pchip（Fritsch-Carlson 保单调三次插值，自含实现零 scipy 依赖）
+ 构造期单调断言 + ``extrapolate: forbidden`` 域外显式 ValueError
（cps_corner2d"不外推"同款）。

单源计数：EXPECTED_ANCHORS / EXPECTED_ANCHOR_COUNT 与 knowledge/anchors.yaml
同步维护（#231/#304 注册表消费者纪律；check_numbers 绑定建议见
runs/df6_dp3anchors/criteria.md 判据 d2）。
"""

from __future__ import annotations

import ast
import math
import re
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# 首批锚单源（DP-3 P1，2026-09-24）：与 knowledge/anchors.yaml 逐条对应。
# 新增/退役锚：先改 anchors.yaml 再同步本单源 + 定向测试。
# HFSS 窗 B→A 批（wf:anchor-register，2026-09-29）+6：constant 2 席
# （wilkinson.f_match/gysel.s32_iso，verdict AGREE 门值定锚）+ pointer 4 席
# （DISAGREE 双值指针，experimental，消费面不接）。
# 补批（wf:anchor-register-p1x4，2026-09-29）+1：patch_array_1x4.f_res
# constant active（verdict AGREE_JUDGE f_min 偏差 0.292068%，7a9ed9f 落档）。
# 指针补批（wf:anchor-pointer-register，2026-09-29）+1：patch_array.f_res
# 族级 pointer experimental（席 8 2x2 timeout-env 重跑 DISAGREE 双值
# {oe 4.976, hfss 5.6898}GHz，99a44e6 落档；H-tree 折弯链拓扑注记随锚）。
# P-KJ-EVEN P3 批（wf:goal-t5，2026-09-30）+1：coupled_microstrip.
# kj_even_domain.lit-v1 constant active——KJ even 闭式适用域盒锚（域盒
# u/g/er=[0.1,10]²×[1,18] 文献声明 qucs-doc，域内基准 0.66%=域内观测最大
# 偏差上界；两条域缘 MARGINAL 注记随 provenance.domain_note；域盒经标准
# domain 字段表达 schema 零扩展；0795b2a T3 核验解锁，P1 §8.5 主路线兑现）。
# Goal 批 T14（wf:goal-t14，2026-09-30）+2：mmt.inductive_post_b.hfss-v1 /
# mmt.resonant_window_fres.hfss-v1 constant active——ME-5 MMT 销钉/谐振窗
# HFSS 仲裁锚（sim_host 远程仲裁，runs/mmt_anchor_20260930/criteria.md
# §6；两案 AGREE_HFSS：闭式偏感性方向 100% 系统，偏差常量 9.224%/16.600%
# 随工作点 domain 钉死；单点锚 consumers=[] 零接线如实）。
# ge6 Wave1 锚注册批（wf:ge6-anchor，2026-10-01）+2：ring.design_dk.
# openems-hfss-v1 pointer experimental（FA3 Design Dk 战役 六百八十
# 九/f0ce39a 预备稿兑现——双引擎 DISAGREE f1 互差 +2.479% 超预声明 1.5% 门，
# 双值 {oe 3.5333, hfss 3.3425}；基准式依赖引擎几何表征=禁 constant 物理根
# 据）+ mmwave.design_dk.ro3003-oe-v1 pointer experimental（OE 单引擎单点
# 封档：既有真跑谷位反推 er_design=3.1434，C10d 离线复判 PASS
# runs/ge6_anchor/verdict.json；constant 待 78GHz HFSS 仲裁腿）。
# ge6 A22 批（wf:ge6-a22，2026-10-01）+1：ms_cross.wg_resonance.
# openems-hfss-v1 pointer experimental——ge6 Wave1 席 2 HFSS 仲裁分支 A
# 收敛判读（runs/ge6_hfsswin/seat2_mscross/：同几何谷位互差 0.180GHz ≤
# 预声明 0.30GHz 门，verdict=BRANCH_A_OPENEMS_ENGINE_FAITHFUL），双值
# {openems 11.675, hfss 11.4951}GHz；偏离 Floquet 属 wg 模拟器前提差，
# 禁产 constant，A 级判据走 T22「收敛仲裁 AGREE」分支（主代理裁定）。
EXPECTED_ANCHORS = frozenset({
    "c3.l_via_h.openems-hfss-v1",
    "patch.f_dip_l.openems-v1",
    "patch.f_dip_l.hfss-v1",
    "cps.gamma_er.fdref-v1",
    "siw.w_eff.lit-v1",
    "c3.k_of_g.openems-hfss-v1",
    "wilkinson.f_match.openems-hfss-v1",
    "gysel.s32_iso.openems-hfss-v1",
    "stepped_impedance.f_pass.openems-hfss-v1",
    "coupled_line.s31_coupling.openems-hfss-v1",
    "marchand.f_null.openems-hfss-v1",
    "branchline.f_match.openems-hfss-v1",
    "patch_array_1x4.f_res.openems-hfss-v1",
    "patch_array.f_res.openems-hfss-v1",
    "coupled_microstrip.kj_even_domain.lit-v1",
    "mmt.inductive_post_b.hfss-v1",
    "mmt.resonant_window_fres.hfss-v1",
    "ring.design_dk.openems-hfss-v1",
    "mmwave.design_dk.ro3003-oe-v1",
    "ms_cross.wg_resonance.openems-hfss-v1",
    # ge8 TA 批（2026-10-02）：内核恒等锚 experimental，真机首判窗随 K 窗
    "schiffman.delta_phase.closedform-v1",
    "qwt_multisection.s11_f0.closedform-v1",
    # ge8 TA 批二（2026-10-02）：sicl/nway_wilkinson 内核恒等锚 experimental
    "sicl.z0_ohm.closedform-v1",
    "sicl.eps_eff.closedform-v1",
    "nway_wilkinson.arm_z_ohm.closedform-v1",
    "nway_wilkinson.isolation_r_ohm.closedform-v1",
    # ge8 TA 批三（2026-10-02）：diplexer/ridged_wg 内核恒等锚 experimental
    "diplexer.crossover_ghz.closedform-v1",
    "diplexer.s21_power_f0.closedform-v1",
    "ridged_wg.fc_ghz.closedform-v1",
    "ridged_wg.evanescent_atten_db_0p8fc.closedform-v1",
    # ge8 K-4 dk78r 双引擎 AGREE（2026-10-02）：78GHz Design Dk 常量锚 active
    "mmwave.design_dk.ro3003-oe-hfss-v2",
    # ge8b Wave A 席 1（2026-10-03）：TA-7/8/9 内核恒等锚 experimental
    # （inverted_ms/fgcpw=FD 裁判反演回代 fdref；hmsiw=Lai-Fumeaux 2009
    # T-MTT 式 (8)-(14) 链 closedform）
    "inverted_ms.z0_ohm.fdref-v1",
    "hmsiw.fc_ghz.closedform-v1",
    "fgcpw.z0_ohm.fdref-v1",
    # ge8b Wave B 席 B9（2026-10-03）：TA-10/AP-11 内核恒等锚 experimental
    # （isl_shielded=准静态双半腔链 4 位舍入；vivaldi_tsa=口面半波准则回代）
    "isl_shielded.eps_eff.closedform-v1",
    "vivaldi_tsa.f_low_ghz.closedform-v1",
    # ge8e X5 解析档锚批（wf:review-ge8e-x5，2026-10-04）+13：首批 analytic
    # 锚扩面（无锚闭式内核模板族补解析档，36→49 席）——atten_pi/atten_t
    # 电阻衰减器 4 席（经典表值+独立重算）/ratrace 2 席（Pozar §7.5）/stripline
    # 2 席（Cohn AGM+TEM εeff=εr）/slotline（Janaswamy-Schaubert 式 9）/siw
    # （Cassivi w_eff×TE10 双链）/monopole（λ0/4 像理论）/coil_nfc（Mohan
    # JSSC 1999 current-sheet）/pyramid_horn（Orfanidis×Balanis 最优 σ）——
    # 逐锚 #118 双源与独立重算钉见 tests/unit/test_x5_analytic_anchors.py
    # 与 runs/review_ge8e/x5_analytic_anchors/REPORT.md；cpw（skrf-CPW vs
    # _cpwg_ri 模型二义）与 mline（HJ 系数无仓内已核原文）落 followUp。
    "atten_pi.r_series_mid_ohm.closedform-v1",
    "atten_pi.r_shunt_end_ohm.closedform-v1",
    "atten_t.r_series_arm_ohm.closedform-v1",
    "atten_t.r_shunt_mid_ohm.closedform-v1",
    "ratrace.ring_z_ohm.closedform-v1",
    "ratrace.r_ring_mm.closedform-v1",
    "stripline.z0_ohm.closedform-v1",
    "stripline.eps_eff.closedform-v1",
    "slotline.z0_ohm.closedform-v1",
    "siw.fc_te10_ghz.closedform-v1",
    "monopole.mon_len_mm.closedform-v1",
    "coil_nfc.l_uh.closedform-v1",
    "pyramid_horn.gain_db.closedform-v1",
    # Phase 4 W4-E 锚批（ra_criteria §七 UX-B1 档①+X5 analytic 二批，
    # 2026-10-05）+10：cps 2 席（Wadell/Gupta-Ghione 共形链×C9 γ(εr) FD
    # 定标）/suspended_stripline 2 席（Cohn+softmin 串联饱和修正族）/
    # cheb_g 5 席（coupled_bpf/xcheb_bpf4/hairpin/hairpin_alt/varactor_bpf，
    # MYJ Table 4.05-1 0.1dB 档表值×Pozar §8.4 递推双源）/msl_cpw 1 席
    # （同阻异模理想级联 S11(f0)=0）——逐锚 #118 独立重算与首判窗见
    # tests/unit/test_w4_w4e_anchors.py 与 runs/w4_phase4/w4e/REPORT.md；
    # cpw（模型二义，两候选并列证据档 runs/w4_phase4/w4e/
    # cpw_ambiguity_evidence.md，裁决权在用户）与 mline（HJ 系数无仓内
    # 已核原文，#df6-⑬）仍缓——裁决后各 +1。
    "cps.z0_ohm.closedform-v1",
    "cps.eps_eff.closedform-v1",
    "suspended_stripline.z0_ohm.closedform-v1",
    "suspended_stripline.eps_eff.closedform-v1",
    "coupled_bpf.cheb_g.closedform-v1",
    "xcheb_bpf4.cheb_g.closedform-v1",
    "hairpin.cheb_g.closedform-v1",
    "hairpin_alt.cheb_g.closedform-v1",
    "varactor_bpf.cheb_g.closedform-v1",
    "msl_cpw.s11_f0.closedform-v1",
    # Phase 6 W6-F cpw 二义裁决落锚（2026-10-06，用户条件裁 A=CPWG/50Ω，
    # 几何核验优先：渲染侧地贯穿 render_tl.py:61-62+底 MUR 白名单外=PEC
    # render_core.py:1899-1906+综合链 _cpwg_ri 同源 49.9999816 双源）——
    # B 口径（skrf 无地 CPW 67.44Ω）作对照注记进 semantics；证据档
    # runs/w4_phase4/w4e/cpw_ambiguity_evidence.md + runs/w6_phase6/w6f/。
    "cpw.z0_ohm.closedform-v1",
})
EXPECTED_ANCHOR_COUNT = len(EXPECTED_ANCHORS)

#: 锚型与状态枚举（awaiting_data 为 P1 批预声明扩展：骨架锚 data 未回填）。
ANCHOR_KINDS = ("constant", "curve", "formula", "pointer")
ANCHOR_STATUSES = ("active", "stale", "experimental", "retired",
                   "awaiting_data")

#: anchor_id 形如 <族>.<量>.<引擎对|来源>-v<N>（引擎段允许连字符）。
_ANCHOR_ID_RE = re.compile(r"^[a-z0-9_]+(?:\.[a-z0-9_][a-z0-9_\-]*)+-v\d+$")

#: 漂移检测门：|残差| > max(3σ, 5%·|锚值|) → stale（规格书 §3 口径）。
_RESIDUAL_SIGMA_FACTOR = 3.0
_RESIDUAL_REL_FLOOR = 0.05

_UNCERTAINTY_RELATIVE_KINDS = frozenset({"relative"})

# ── XC-A 锚→设计自动修正（规格 规格深案 §B-2）──
# 分层声明（规格原文口径，勿混层）：
# - warm_start（optimization/warm_start.py 的 Jaccard 相似度门）= **参数面**
#   ——历史优化样本经相似度筛选后作新战役的优化起点；
# - XC-A（本节 find_anchors/apply_anchor_correction）= **偏差面**——引擎对
#   系统偏差锚修正综合闭式输出（注入综合初值或收缩 bounds）；
# - XC-A 产物（修正后初值/收缩后的 bounds）可作 warm_start 候选输入（上层
#   自行喂给 warm_start_points/kickoff），但锚修正永不直接改优化器状态——
#   两层边界由本模块签名钉死：只产出修正包络，零优化器 IO。

#: XC-A 修正门 1（规格 §B-2）：锚不确定度相对值（σ_abs/|锚值|）超过该阈
#: → 拒绝修正（缺省 10%）。仲裁包络型 uncertainty（如 wilkinson 3% 门宽
#: 对 1.13% 锚值）会如实被此门拒——弱约束锚不做修正，不凑。
UNCERTAINTY_REL_MAX_DEFAULT = 0.10

#: 修正量单位为"percent"的偏差型锚：Δ 即锚值本身（%），调用方按 (1±Δ/100)
#: 缩放综合初值或收缩 bounds；其余单位为绝对量纲锚：Δ = 锚值 − design_value
#: （同量纲设计侧估计，由调用方按 quantity 语义给出，如 patch f_dip·L 的
#: 设计侧估计 = f0 × L_cf）。
_PERCENT_UNITS = frozenset({"percent", "%", "pct", "rel_pct"})


# ── 公式锚：AST 白名单（复用 0cz 校验器，单一白名单源）────────────────────

def compile_anchor_formula(expr: str, variables: Sequence[str]) -> Any:
    """把公式锚表达式编译为可求值代码对象（^→** 归一后过 0cz 白名单）。

    词表与 core/calculators.register_symbolic_formula 完全一致：数值常量、
    已声明变量、+ - * / **、一元 ±、sqrt/log 单参调用；其余一律 ValueError
    （显式拒绝，不静默降级）。
    """
    from rfauto.core.calculators import _validate_symbolic_node

    try:
        tree = ast.parse(str(expr).replace("^", "**"), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"公式锚表达式语法错误: {expr!r}（{exc}）") from exc
    _validate_symbolic_node(tree, frozenset(variables))
    return compile(tree, f"<anchor:{expr}>", "eval")


def eval_anchor_formula(code: Any, namespace: Mapping[str, float]) -> float:
    """确定性求值公式锚（纯 float 闭式；sqrt/log 来自 math，无内建）。

    env 无 __builtins__、代码对象已过 AST 白名单——eval 面只暴露白名单
    词表（安全语义同 0cz _eval_symbolic_terms）。
    """
    env = {"sqrt": math.sqrt, "log": math.log, "__builtins__": {}}
    return float(eval(code, env, dict(namespace)))


# ── 曲线锚：pchip（Fritsch-Carlson 保单调三次插值，自含实现）───────────────

def _pchip_slopes(xs: list[float], ys: list[float]) -> list[float]:
    """Fritsch-Carlson 端点+内部斜率（scipy PchipInterpolator 同公式）。"""
    n = len(xs)
    if n < 2:
        raise ValueError("曲线锚至少需要 2 个点")
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    if any(hi <= 0.0 for hi in h):
        raise ValueError("曲线锚 x 必须严格递增")
    delta = [(ys[i + 1] - ys[i]) / h[i] for i in range(n - 1)]
    if n == 2:
        return [delta[0], delta[0]]

    def _edge(d0: float, d1: float, h0: float, h1: float) -> float:
        # scipy _edge_case：端点斜率符号/幅值钳制保单调
        m = ((2.0 * h0 + h1) * d0 - h0 * d1) / (h0 + h1)
        if math.copysign(1.0, m) != math.copysign(1.0, d0):
            return 0.0
        if (math.copysign(1.0, d0) != math.copysign(1.0, d1)
                and abs(m) > 3.0 * abs(d0)):
            return 3.0 * d0
        return m

    m = [0.0] * n
    m[0] = _edge(delta[0], delta[1], h[0], h[1])
    m[-1] = _edge(delta[-1], delta[-2], h[-1], h[-2])
    for i in range(1, n - 1):
        if delta[i - 1] * delta[i] <= 0.0:
            m[i] = 0.0
        else:
            # 加权调和平均（Fritsch-Carlson），同号 δ 下保单调
            w1 = 2.0 * h[i] + h[i - 1]
            w2 = h[i] + 2.0 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / delta[i - 1] + w2 / delta[i])
    return m


def eval_pchip(xs: Sequence[float], ys: Sequence[float], x: float,
               slopes: list[float] | None = None) -> float:
    """pchip 单点求值（Hermite 基）；x 必须落在 [xs[0], xs[-1]] 内。"""
    xs_l = [float(v) for v in xs]
    ys_l = [float(v) for v in ys]
    if slopes is None:
        slopes = _pchip_slopes(xs_l, ys_l)
    if not xs_l[0] <= float(x) <= xs_l[-1]:
        raise ValueError(
            f"曲线锚域外求值 x={x} 超出 [{xs_l[0]}, {xs_l[-1]}]"
            "（extrapolate: forbidden，不外推）")
    # 线性定位区间（锚点数 ≤ 数十，无需二分）
    i = 0
    for j in range(len(xs_l) - 1):
        if x <= xs_l[j + 1] or j == len(xs_l) - 2:
            i = j
            break
    hi_ = xs_l[i + 1] - xs_l[i]
    t = (float(x) - xs_l[i]) / hi_
    h00 = (1.0 + 2.0 * t) * (1.0 - t) ** 2
    h10 = t * (1.0 - t) ** 2
    h01 = t * t * (3.0 - 2.0 * t)
    h11 = t * t * (t - 1.0)
    return float(h00 * ys_l[i] + h10 * hi_ * slopes[i]
                 + h01 * ys_l[i + 1] + h11 * hi_ * slopes[i + 1])


# ── 锚记录与锚集 ───────────────────────────────────────────────────────────

@dataclass
class AnchorRecord:
    """单条锚（dict 背书，构造期做求值阻断性校验）。"""

    anchor_id: str
    kind: str
    status: str
    version: int
    template_family: list[str]
    engine_pair: dict[str, str] | None
    quantity: dict[str, Any]
    value: float | None
    expr: str | None
    variables: list[str] | None
    points: list[dict[str, float]] | None
    interp: dict[str, Any] | None
    axis: dict[str, str] | None
    uncertainty: dict[str, Any] | None
    domain: dict[str, list[float]] | None
    provenance: dict[str, Any]
    registered_at: str | None
    last_verified: dict[str, Any] | None
    fallback: str | None
    # consumers 字段语义二分（G-08 注记 2026-10-04，不改行为）：
    # - runtime_resolve：消费者经锚存储运行时取值（resolve_anchor/
    #   live_anchor_set/apply_anchor_correction 链——如 render_c3 与
    #   fake_adapter 的 c3.l_via_h、rf_line 的 cps.gamma_er、level2_design
    #   的 XC-A 注入）——锚值变更即刻传播到消费者；
    # - declarative_identity：消费者只消费与锚同源的闭式内核恒等（渲染
    #   f-string 缺省/内核常量，不 import 锚存储）——锚值变更不传播，
    #   声明仅作溯源指引。2026-10-04 G-04 起，ge8 TA/b 批的超报
    #   declarative 声明已照 J1-4/R2-2（c3.k_of_g）口径清为 consumers=[]
    #   并在 provenance.consumers_note 留痕；此后新增 consumers 声明默认
    #   须为 runtime_resolve，确需 declarative_identity 的须在 provenance
    #   注记显式声明该语义（两语义判定口径=消费者文件是否 import
    #   infra.anchors_store 或经 resolve_anchor 取值）。
    consumers: list[str]
    raw: dict[str, Any] = field(default_factory=dict, repr=False)
    _formula_code: Any = field(default=None, repr=False)
    _curve_xs: list[float] = field(default_factory=list, repr=False)
    _curve_ys: list[float] = field(default_factory=list, repr=False)
    _curve_slopes: list[float] = field(default_factory=list, repr=False)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> AnchorRecord:
        anchor_id = str(raw.get("anchor_id") or "")
        if not _ANCHOR_ID_RE.match(anchor_id):
            raise ValueError(
                f"anchor_id 不合规格 <族>.<量>.<引擎对>-v<N>: {anchor_id!r}")
        kind = str(raw.get("kind") or "")
        if kind not in ANCHOR_KINDS:
            raise ValueError(f"未知锚型 kind={kind!r}（{anchor_id}）")
        status = str(raw.get("status") or "")
        if status not in ANCHOR_STATUSES:
            raise ValueError(f"未知状态 status={status!r}（{anchor_id}）")
        version = int(anchor_id.rsplit("-v", 1)[1])
        rec = cls(
            anchor_id=anchor_id,
            kind=kind,
            status=status,
            version=version,
            template_family=[str(t) for t in (raw.get("template_family") or [])],
            engine_pair=raw.get("engine_pair"),
            quantity=raw.get("quantity") or {},
            value=raw.get("value"),
            expr=raw.get("expr"),
            variables=list(raw.get("variables") or []) or None,
            points=list(raw.get("points") or []) or None,
            interp=raw.get("interp"),
            axis=raw.get("axis"),
            uncertainty=raw.get("uncertainty"),
            domain=raw.get("domain"),
            provenance=raw.get("provenance") or {},
            registered_at=raw.get("registered_at"),
            last_verified=raw.get("last_verified"),
            fallback=raw.get("fallback"),
            consumers=[str(c) for c in (raw.get("consumers") or [])],
            raw=dict(raw),
        )
        rec._prepare_evaluator()
        return rec

    # 构造期求值准备（阻断性问题 fail-fast；schema/provenance 校验在 infra）

    def _prepare_evaluator(self) -> None:
        if self.kind == "constant":
            if self.value is None:
                raise ValueError(f"constant 锚缺 value: {self.anchor_id}")
            self.value = float(self.value)
        elif self.kind == "formula":
            if not self.expr or not self.variables:
                raise ValueError(
                    f"formula 锚缺 expr/variables: {self.anchor_id}")
            self._formula_code = compile_anchor_formula(
                str(self.expr), self.variables)
        elif self.kind == "curve":
            pts = self.points or []
            if not pts:
                if self.status != "awaiting_data":
                    raise ValueError(
                        f"curve 锚无 points 只允许 awaiting_data: "
                        f"{self.anchor_id}")
                return
            self._curve_xs = [float(p["x"]) for p in pts]
            self._curve_ys = [float(p["y"]) for p in pts]
            # 单调断言（hairpin 先例）：非严格单调（同号或零），符号混杂即拒
            deltas = [b - a for a, b in
                      zip(self._curve_ys, self._curve_ys[1:], strict=False)]
            if any(d > 0.0 for d in deltas) and any(d < 0.0 for d in deltas):
                raise ValueError(
                    f"曲线锚 points 非单调: {self.anchor_id}"
                    "（单调断言失败，疑似判读/转录错误）")
            self._curve_slopes = _pchip_slopes(self._curve_xs,
                                               self._curve_ys)
            if not self.axis or not self.axis.get("param"):
                raise ValueError(
                    f"curve 锚缺 axis.param: {self.anchor_id}")
            method = (self.interp or {}).get("method", "pchip")
            if method != "pchip":
                raise ValueError(
                    f"曲线锚仅支持 pchip 插值，收到 {method!r}"
                    f"（{self.anchor_id}）")

    # 求值

    @property
    def curve_axis_param(self) -> str:
        if not self.axis or not self.axis.get("param"):
            raise ValueError(f"curve 锚缺 axis.param: {self.anchor_id}")
        return str(self.axis["param"])

    def check_domain(self, params: Mapping[str, float]) -> bool:
        """参数盒守卫；domain=null（未定维）恒 True（曲线锚另受点域约束）。"""
        if self.kind == "curve" and self._curve_xs:
            # 曲线自变量必须落在点域内（extrapolate: forbidden 的结构化面；
            # 直接 evaluate 走 eval_pchip 的显式 ValueError，双保险）
            key = self.curve_axis_param
            if key not in params:
                return False
            v = float(params[key])
            if not (self._curve_xs[0] <= v <= self._curve_xs[-1]):
                return False
        if not self.domain:
            return True
        for key, box in self.domain.items():
            if key not in params:
                return False
            lo, hi = float(box[0]), float(box[1])
            v = float(params[key])
            if not (lo <= v <= hi) or not math.isfinite(v):
                return False
        return True

    def evaluate(self, params: Mapping[str, float]) -> float | None:
        """域内求值（调用方先过 check_domain；曲线域外抛 ValueError）。"""
        if self.kind == "constant":
            return self.value
        if self.kind == "formula":
            ns: dict[str, float] = {}
            for var in self.variables or []:
                if var not in params:
                    raise ValueError(
                        f"公式锚缺变量 {var}: {self.anchor_id}")
                ns[var] = float(params[var])
            return eval_anchor_formula(self._formula_code, ns)
        if self.kind == "curve":
            if not self.points:
                raise ValueError(
                    f"曲线锚数据未回填（awaiting_data）: {self.anchor_id}")
            key = self.curve_axis_param
            if key not in params:
                raise ValueError(f"曲线锚缺自变量 {key}: {self.anchor_id}")
            return eval_pchip(self._curve_xs, self._curve_ys,
                              float(params[key]), self._curve_slopes)
        return None  # pointer：值在模型档案，不就地求值

    def uncertainty_sigma_abs(self, expected: float) -> float | None:
        """不确定度绝对值（relative 按期望值折算；缺失/为 None → None）。"""
        unc = self.uncertainty
        if not unc or unc.get("value") is None:
            return None
        sigma = float(unc["value"])
        if str(unc.get("kind") or "") in _UNCERTAINTY_RELATIVE_KINDS:
            sigma = sigma * abs(expected)
        return sigma

    def to_dict(self) -> dict[str, Any]:
        """JSON 安全全量记录（raw 透传 + 解析字段）。"""
        out = dict(self.raw)
        out["version"] = self.version
        return out


class AnchorSet:
    """锚集合（纯内存；由 infra 装载层喂 raw dict 列表）。"""

    def __init__(self, raw_anchors: Any = None) -> None:
        self._records: dict[str, AnchorRecord] = {}
        self.load_errors: list[str] = []
        for raw in list(raw_anchors or []):
            try:
                rec = AnchorRecord.from_dict(raw)
            except (ValueError, TypeError, KeyError) as exc:
                # 单锚坏不拖垮整表（#105 best-effort）；错误留痕供 validate 报
                self.load_errors.append(f"{raw.get('anchor_id')!r}: {exc}")
                continue
            if rec.anchor_id in self._records:
                self.load_errors.append(
                    f"{rec.anchor_id!r}: 重复 anchor_id（后者丢弃）")
                continue
            self._records[rec.anchor_id] = rec

    # 容器语义

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, anchor_id: object) -> bool:
        return anchor_id in self._records

    def get(self, anchor_id: str) -> AnchorRecord | None:
        return self._records.get(anchor_id)

    @property
    def anchor_ids(self) -> list[str]:
        return sorted(self._records)

    @property
    def records(self) -> list[AnchorRecord]:
        return [self._records[k] for k in sorted(self._records)]

    # XC-A 注册表查询（规格 §B-2：现仅 anchor_id 精确 get，补 family+quantity）

    def find_anchors(self, template_family: str, quantity: str, *,
                     active_only: bool = True,
                     engine: str | None = None) -> list[AnchorRecord]:
        """按 模板族 × 量 查询锚记录（XC-A，anchor_id 精确 get 之外的投影面）。

        匹配语义（全部大小写不敏感、显式 .lower()，normcase 类教训）：
        - family：``template_family`` 列表命中，或 ``["*"]`` 通配（lit 域盒
          锚等族无关锚对任意 family 查询命中）；
        - quantity：``quantity.name`` 字段命中，或 anchor_id 中段
          （``<族>.<量>.<来源>-v<N>`` 的 <量>）命中；
        - engine（可选）：``engine_pair.calibrated`` 命中；engine_pair 为空
          的来源锚（lit 等）视为引擎无关，任何 engine 过滤都命中——用于
          同族同量的分引擎锚去歧义（如 patch.f_dip_l 的 openems/hfss 双席）；
        - active_only=True（缺省）只返回 status=active；False 返回全部匹配
          （含 experimental/stale/awaiting_data/retired，供拒绝分支如实
          报告被拒锚与状态）。

        返回按 anchor_id 排序（确定性）；零匹配返回空表（不抛）。
        """
        fam = str(template_family or "").strip().lower()
        q = str(quantity or "").strip().lower()
        if not fam or not q:
            return []
        eng = None if engine is None else str(engine).strip().lower()
        out: list[AnchorRecord] = []
        for rec in self.records:
            fams = [str(t).strip().lower() for t in rec.template_family]
            if fams != ["*"] and fam not in fams:
                continue
            q_name = str((rec.quantity or {}).get("name") or "").strip().lower()
            parts = rec.anchor_id.split(".")
            q_seg = parts[1].strip().lower() if len(parts) > 2 else ""
            if q not in (q_name, q_seg):
                continue
            if eng is not None:
                calibrated = str(
                    (rec.engine_pair or {}).get("calibrated") or ""
                ).strip().lower()
                if calibrated and calibrated != eng:
                    continue
            if active_only and rec.status != "active":
                continue
            out.append(rec)
        return out


    # 消费者 API

    def resolve_anchor(self, anchor_id: str,
                       params: Mapping[str, float] | None = None) -> dict[str, Any]:
        """规格书核心语义：{hit, value, source: anchor|fallback, version,
        domain_ok}；域外/未知/非可消费状态一律结构化 fallback（不抛）。"""
        rec = self._records.get(str(anchor_id))
        if rec is None:
            return {"hit": False, "value": None, "source": "fallback",
                    "version": None, "domain_ok": False, "stale": False,
                    "reason": "unknown_anchor", "anchor_id": str(anchor_id)}
        out: dict[str, Any] = {
            "hit": True, "anchor_id": rec.anchor_id, "kind": rec.kind,
            "version": rec.version, "status": rec.status,
            "stale": rec.status == "stale", "source": "anchor",
            "domain_ok": True, "value": None, "reason": None,
        }
        if rec.status in ("awaiting_data", "retired"):
            out.update(hit=False, source="fallback", domain_ok=False,
                       reason=rec.status)
            return out
        params = dict(params or {})
        if rec.kind == "formula" and rec.variables:
            missing = [v for v in rec.variables if v not in params]
            if missing:
                out.update(source="fallback", domain_ok=False,
                           reason=f"missing_params:{','.join(missing)}")
                return out
        if not rec.check_domain(params):
            out.update(source="fallback", domain_ok=False,
                       reason="out_of_domain")
            return out
        out["value"] = rec.evaluate(params)
        return out

    def note_anchor_residual(self, anchor_id: str,
                             point: Mapping[str, float],
                             observed: float) -> dict[str, Any]:
        """漂移检测：|残差| > max(3σ, 5%·|锚值|) → 内存面翻 stale + 告警。

        注册表运行时只读（YAML 零改写）；落盘回填走人工 commit/ingest
        （P2 战役 ingest 自动回填挂点）。
        """
        res = self.resolve_anchor(anchor_id, point)
        base: dict[str, Any] = {
            "ok": False, "anchor_id": str(anchor_id),
            "point": dict(point), "observed": float(observed),
            "expected": None, "residual": None, "threshold": None,
            "stale": False, "alarm": None,
        }
        if not res["hit"] or res["value"] is None or not res["domain_ok"]:
            base["reason"] = res.get("reason") or "not_resolvable"
            return base
        expected = float(res["value"])
        residual = float(observed) - expected
        sigma = self._records[str(anchor_id)].uncertainty_sigma_abs(expected)
        parts = []
        if sigma is not None:
            parts.append(_RESIDUAL_SIGMA_FACTOR * sigma)
        parts.append(_RESIDUAL_REL_FLOOR * abs(expected))
        threshold = max(parts)
        stale = abs(residual) > threshold
        base.update(ok=True, expected=expected, residual=residual,
                    threshold=threshold, stale=stale,
                    alarm=("residual_exceeds_max(3sigma,5%)——锚疑似 stale，"
                           "请登记复验" if stale else None))
        if stale:
            rec = self._records[str(anchor_id)]
            rec.status = "stale"
            rec.raw["status"] = "stale"
        return base


# ── 活注册表接插点（DP-3 第二批消费接线，df7 锚消费第二批）──────────────────
# core 是分层 leaf（零 IO，不 import infra）：由上层装载层 infra/anchors_store
# 在模块导入时把 load_anchors 注册为 provider（infra→core 合法方向）。消费者
# （core/calculators 等）经 live_anchor_set() 惰性取用；provider 未注册
# （进程未导入锚装载层）或调用失败 → 返回 None，消费者走字面/闭式回退
# （零行为变化兜底，#105 best-effort：锚系统任何故障不阻塞业务主路径）。

_LIVE_SET_PROVIDER: Callable[[], AnchorSet] | None = None


def set_live_anchor_set_provider(
        provider: Callable[[], AnchorSet] | None) -> None:
    """注册活注册表 provider（infra/anchors_store 导入时调用；测试可替换）。"""
    global _LIVE_SET_PROVIDER
    _LIVE_SET_PROVIDER = provider


def live_anchor_set() -> AnchorSet | None:
    """取活锚注册表（惰性；provider 未注册/任何异常 → None，消费者走回退）。

    返回对象由装载层缓存（mtime 键），本函数不持有状态——重复调用共享同一
    AnchorSet；调用方只读消费（note_anchor_residual 的内存面翻 stale 语义
    归装载层缓存对象所有）。"""
    provider = _LIVE_SET_PROVIDER
    if provider is None:
        return None
    try:
        anchor_set = provider()
    except Exception:  # best-effort：provider 任何故障都走消费者回退（#105）
        return None
    return anchor_set if isinstance(anchor_set, AnchorSet) else None


# ── XC-A 锚→设计自动修正闭环（规格 §B-2，模块面）──────────────────────────

def find_anchors(template_family: str, quantity: str, *,
                 active_only: bool = True,
                 engine: str | None = None,
                 anchor_set: AnchorSet | None = None) -> list[AnchorRecord]:
    """锚注册表查询（XC-A 模块面）：family+quantity 匹配，缺省只出 active。

    anchor_set 缺省走活注册表（live_anchor_set；provider 未注册/故障 →
    空表，消费者语义与 #105 best-effort 一致）。其余语义见
    ``AnchorSet.find_anchors``。
    """
    aset = anchor_set if anchor_set is not None else live_anchor_set()
    if aset is None:
        return []
    return aset.find_anchors(template_family, quantity,
                             active_only=active_only, engine=engine)


def apply_anchor_correction(
    family: str,
    quantity: str,
    params: Mapping[str, float] | None = None,
    *,
    design_value: float | None = None,
    engine: str | None = None,
    uncertainty_rel_max: float = UNCERTAINTY_REL_MAX_DEFAULT,
    anchor_set: AnchorSet | None = None,
) -> dict[str, Any]:
    """XC-A 偏差面修正：锚匹配 → 三拒绝门 → 修正量包络（JSON 安全，不抛）。

    分层声明（规格 §B-2 原文口径，见模块头注释）：warm_start=参数面优化
    起点；本函数=偏差面综合闭式输出修正；XC-A 产物可作 warm_start 候选
    输入不越层——本函数只产出修正包络，注入综合初值/收缩 bounds 的策略
    归上层挂点（service/level2_design.py 的修正注入点），零优化器 IO。

    语义：
    - 匹配：``find_anchors(family, quantity, active_only=False, engine)``
      → **恰一个** status=active 候选才继续；0 个/多个都如实拒绝（多候选
      保守歧义拒绝，修正必须单源可溯；分引擎双席用 engine= 去歧义）；
    - 修正量：双值锚（pointer ``quantity.values``）取**中位**；单值锚取
      锚值（formula/curve 锚按 params 域内求值）；偏差带 band=uncertainty
      绝对值（relative 按锚值折算，同 resolve 语义）；
    - Δ：percent 单位锚（偏差型）Δ=锚值本身（delta_kind="percent"）；
      其余单位锚 Δ=锚值−design_value（delta_kind="absolute"；design_value
      是调用方按 quantity 语义给的同量纲设计侧估计，缺 → 拒绝）。

    三拒绝门（规格原文，各自结构化 reason，永不抛）：
    1. uncertainty 相对超阈：band/|锚值| > uncertainty_rel_max（缺省
       ``UNCERTAINTY_REL_MAX_DEFAULT``=0.10）→
       ``reason="uncertainty_exceeds_threshold"``；
    2. status≠active（experimental/stale/awaiting_data/retired）→
       ``reason="status_not_active"``；
    3. domain_ok=False（参数盒/曲线点域外）→ ``reason="out_of_domain"``。

    另有前置分支（非数据拒绝）：``no_matching_anchor``（family×quantity
    零匹配）/``ambiguous_active_anchors``（多 active 候选）/
    ``missing_design_value``（绝对量纲锚缺设计侧估计）/
    ``registry_unavailable``（无活注册表且未显式传 anchor_set）。

    Returns:
        {applied, family, quantity, anchor_id, version, kind, status,
        source, value, unit, delta, delta_kind, band, band_rel, domain_ok,
        reason, injection(None, 注入策略归上层), candidates, notes,
        uncertainty_rel_max}；审计五元组提炼见
        ``anchor_correction_provenance``。
    """
    rel_max = float(uncertainty_rel_max)
    if not (rel_max > 0.0):
        raise ValueError(
            f"uncertainty_rel_max 须 >0，实际 {uncertainty_rel_max!r}")
    env: dict[str, Any] = {
        "applied": False, "family": str(family), "quantity": str(quantity),
        "anchor_id": None, "version": None, "kind": None, "status": None,
        "source": None, "value": None, "unit": None, "delta": None,
        "delta_kind": None, "band": None, "band_rel": None,
        "domain_ok": False, "reason": None, "injection": None,
        "candidates": [], "notes": [], "uncertainty_rel_max": rel_max,
    }
    aset = anchor_set if anchor_set is not None else live_anchor_set()
    if aset is None:
        env["reason"] = "registry_unavailable"
        return env
    param_map = {str(k): float(v) for k, v in dict(params or {}).items()
                 if isinstance(v, (int, float)) and not isinstance(v, bool)}
    matches = aset.find_anchors(family, quantity, active_only=False,
                                engine=engine)
    env["candidates"] = [
        {"anchor_id": r.anchor_id, "kind": r.kind, "status": r.status,
         "selected": False, "rejected_reason": None} for r in matches]
    if not matches:
        env["reason"] = "no_matching_anchor"
        return env
    active = [r for r in matches if r.status == "active"]
    if not active:
        # 拒绝门 2：status∈{experimental, stale, awaiting_data, retired}
        env["reason"] = "status_not_active"
        by_id = {c["anchor_id"]: c for c in env["candidates"]}
        for r in matches:
            by_id[r.anchor_id]["rejected_reason"] = f"status:{r.status}"
            if env["anchor_id"] is None:
                env.update(anchor_id=r.anchor_id, version=r.version,
                           kind=r.kind, status=r.status, source="anchor")
        return env
    if len(active) > 1:
        env["reason"] = "ambiguous_active_anchors"
        env["notes"].append(
            "多个 active 锚匹配同族同量：修正必须单源可溯，用 engine= 去歧义")
        return env
    rec = active[0]
    env.update(anchor_id=rec.anchor_id, version=rec.version, kind=rec.kind,
               status=rec.status, source="anchor", domain_ok=True)
    for c in env["candidates"]:
        c["selected"] = c["anchor_id"] == rec.anchor_id

    # 拒绝门 3：域外（参数盒 / 曲线点域）
    if not rec.check_domain(param_map):
        env.update(domain_ok=False, reason="out_of_domain")
        return env

    # 修正量：双值锚中位 / 单值锚值 / formula·curve 域内求值
    unit = str((rec.quantity or {}).get("unit") or "").strip()
    env["unit"] = unit or None
    try:
        if rec.kind == "pointer":
            raw_values = (rec.quantity or {}).get("values") or {}
            vals = sorted(float(v) for v in raw_values.values())
            if not vals:
                env["reason"] = "pointer_values_missing"
                return env
            value = float(statistics.median(vals))  # 双值锚=中位（2 值即均值）
        elif rec.kind in ("constant", "formula", "curve"):
            evaluated = rec.evaluate(param_map)
            if evaluated is None:
                env["reason"] = "value_unavailable"
                return env
            value = float(evaluated)
        else:  # pragma: no cover - ANCHOR_KINDS 已穷举
            env["reason"] = "value_unavailable"
            return env
    except Exception as exc:  # 坏锚记录不炸消费者（#105 同源：结构化如实降级）
        env["reason"] = f"eval_failed:{type(exc).__name__}"
        env["notes"].append(str(exc))
        return env
    env["value"] = value
    sigma = rec.uncertainty_sigma_abs(value)
    band_rel: float | None = None
    if sigma is not None:
        env["band"] = abs(float(sigma))
        band_rel = math.inf if value == 0.0 else env["band"] / abs(value)
        env["band_rel"] = band_rel

    # 拒绝门 1：uncertainty 相对超阈（缺省 10%）
    if band_rel is not None and band_rel > rel_max:
        env["reason"] = "uncertainty_exceeds_threshold"
        return env

    if unit.strip().lower() in _PERCENT_UNITS:
        env.update(delta=value, delta_kind="percent", applied=True)
        return env
    if design_value is None:
        env["reason"] = "missing_design_value"
        return env
    env.update(delta=value - float(design_value), delta_kind="absolute",
               applied=True)
    return env


def anchor_correction_provenance(correction: Mapping[str, Any]) -> dict[str, Any]:
    """审计留痕提炼（规格 §B-2）：correction 进 run meta 的
    ``{anchor_id, version, Δ, domain_ok, source}`` 五元组（另附 applied/
    reason 供拒绝分支审计——拒绝也要留痕，如实不凑）。

    落点：level2 设计链 ``record.provenance.anchor_correction``（随既有
    provenance 面走，不另开写路径）。
    """
    return {
        "anchor_id": correction.get("anchor_id"),
        "version": correction.get("version"),
        "delta": correction.get("delta"),
        "domain_ok": bool(correction.get("domain_ok")),
        "source": correction.get("source"),
        "applied": bool(correction.get("applied")),
        "reason": correction.get("reason"),
    }


# ── XA-10 analytic-anchor（内核侧轻条目：注册 helper + 覆盖统计面）──────────
# 划界（研究扩充 round18 XA-10；模板/内核划界见
# 方案池 十五轮）：XC-T=模板侧锚注册，
# XA-10=内核侧 analytic-anchor 轻条目。closedform 恒等锚不开新 ANCHOR_KINDS
# ——走既有 kind=constant + uncertainty kind=identity 形态（ge8 TA 三批先例
# 10 锚：schiffman/qwt_multisection/sicl/nway_wilkinson/diplexer/ridged_wg
# 六族，2026-10-02）。本节纯构造零 IO：helper 产出注册表 raw dict 供注册链
# 批次落盘（knowledge/anchors.yaml 运行时只读，写面=人工 commit，
# 规则 6 同源）；provenance.arbitration_runs/commit 由注册链批次回填，
# helper 不伪造仲裁证据（#122 如实口径）。

#: analytic 锚缺省 source 段（anchor_id 第三段 = engine_pair.calibrated）。
ANALYTIC_SOURCE_DEFAULT = "closedform"

#: identity 不确定度缺省注记（闭式恒等锚轻条目形态）。
_IDENTITY_UNCERTAINTY_NOTE = "闭式恒等锚（analytic light entry）"

#: analytic 锚 id 段词法预检（anchor_id 正则的段级收窄：snake 单段）。
_ANALYTIC_SEG_RE = re.compile(r"^[a-z0-9_]+$")


def register_analytic_anchor(
    family: str,
    quantity: str,
    value: float,
    semantics: str,
    *,
    unit: str | None = None,
    quantity_name: str | None = None,
    source: str = ANALYTIC_SOURCE_DEFAULT,
    version: int = 1,
    status: str = "experimental",
    uncertainty: Mapping[str, Any] | None = None,
    domain: Mapping[str, Sequence[float]] | None = None,
    provenance: Mapping[str, Any] | None = None,
    registered_at: str | None = None,
    consumers: Sequence[str] | None = None,
    fallback: str = "closed_form",
) -> dict[str, Any]:
    """analytic-anchor 轻条目注册 helper（XA-10；纯构造，零 IO）。

    产出 closedform-v1 形态的注册表 raw dict（ge8 TA 三批先例同形）：
    kind=constant + engine_pair.calibrated=<source> + uncertainty
    kind=identity（缺省）——内核双路径互证（闭式回代单测钉）后的恒等锚，
    真机首判窗语义进 semantics。注册链默认动作：内核/模板注册批次按
    ``raw = register_analytic_anchor(...)`` 产出条目 → 补 provenance
    （arbitration_runs/commit，勿伪造）→ 人工 commit 进
    knowledge/anchors.yaml 并同步 EXPECTED_ANCHORS 单源与定向测试
    （#231/#304 注册表消费者纪律）。

    Args:
        family: 模板族（snake 单段，如 ``sicl``）。
        quantity: 量名（snake 单段，作 anchor_id 中段与 quantity.name 词根）。
        value: 锚值（闭式恒等量；float 化）。
        semantics: 语义注记（恒等式出处/单测钉/真机首判窗——必填非空）。
        unit: 量纲（``"percent"`` 走 XC-A percent 修正路径；其余绝对量纲，
            消费方按 quantity 语义给 design_value）。
        quantity_name: quantity.name 覆盖（缺省 ``f"{family}_{quantity}"``，
            TA 批先例同构）。
        source: anchor_id 第三段（缺省 ``closedform``；engine_pair.calibrated
            同值）。
        version: 锚版本（重登记 v2+）。
        status: 缺省 ``experimental``（恒等锚真机首判前的如实状态；AGREE
            仲裁后由批次翻 active）。
        uncertainty: 覆盖缺省 identity 形态（如 sicl rounding_band
            ``{"value": 0.005, "kind": "rounding_band", "note": ...}``）。
        domain/provenance/registered_at/consumers/fallback: 同注册表
            schema；provenance 缺省空 dict（仲裁证据由注册链批次回填）。

    Returns:
        注册表 raw dict（尾部过 ``AnchorRecord.from_dict`` 构造期校验——
        坏段/坏形态 fail-fast，不产出不可装载条目）。

    Raises:
        ValueError: family/quantity/source 段不合 snake 词法、semantics 空、
            version <1、status 不在枚举、或 from_dict 校验失败。
    """
    fam = str(family).strip()
    qty = str(quantity).strip()
    src = str(source).strip()
    for label, seg in (("family", fam), ("quantity", qty), ("source", src)):
        if not _ANALYTIC_SEG_RE.match(seg):
            raise ValueError(
                f"analytic 锚 {label} 段须为 snake 单段 [a-z0-9_]+: {seg!r}")
    sem = str(semantics).strip()
    if not sem:
        raise ValueError("analytic 锚 semantics 必填（恒等式出处/首判窗注记）")
    ver = int(version)
    if ver < 1:
        raise ValueError(f"version 须 >=1: {version!r}")
    if status not in ANCHOR_STATUSES:
        raise ValueError(f"未知状态 status={status!r}（{fam}.{qty}.{src}）")
    unc = dict(uncertainty) if uncertainty is not None else {
        "value": 0.0, "kind": "identity", "note": _IDENTITY_UNCERTAINTY_NOTE,
    }
    raw: dict[str, Any] = {
        "anchor_id": f"{fam}.{qty}.{src}-v{ver}",
        "kind": "constant",
        "template_family": [fam],
        "engine_pair": {"calibrated": src, "referee": None},
        "quantity": {
            "name": str(quantity_name).strip()
            if quantity_name else f"{fam}_{qty}",
            "unit": unit,
            "semantics": sem,
        },
        "value": float(value),
        "uncertainty": unc,
        "domain": dict(domain) if domain is not None else None,
        "provenance": dict(provenance) if provenance is not None else {},
        "registered_at": registered_at,
        "last_verified": None,
        "fallback": fallback,
        "status": status,
        "consumers": [str(c) for c in (consumers or [])],
    }
    AnchorRecord.from_dict(raw)  # 构造期 fail-fast（schema/求值准备同源）
    return raw


def anchor_coverage(anchor_set: AnchorSet) -> dict[str, Any]:
    """锚覆盖统计面（XA-10）：锚册 → 按族统计（纯函数，确定性排序）。

    语义：
    - template_family 多族锚在每族各计一席——族 total 之和可大于
      ``total_anchors``（多族锚重复计席，如实口径非去重计数）；
    - ``["*"]`` 通配族单列 ``"*"`` 桶；空 template_family 归 ``"<none>"``
      桶（不静默蒸发）；
    - ``closedform`` 席 = engine_pair.calibrated == ``"closedform"``
      （analytic-anchor 的定义性特征，XA-10 增量观察面——恒等锚注册
      是否随内核/模板批次默认动作推进，以此对账）。

    Returns:
        ``{total_anchors, family_count, closedform_total, families:
        {族: {total, active, closedform, by_kind, by_status, anchor_ids}}}``，
        族键与 anchor_ids 均排序（确定性）。
    """
    families: dict[str, dict[str, Any]] = {}
    for rec in anchor_set.records:
        fams = [str(t).strip() for t in rec.template_family
                if str(t).strip()]
        if not fams:
            fams = ["<none>"]
        for fam in fams:
            b = families.setdefault(fam, {
                "total": 0, "active": 0, "closedform": 0,
                "by_kind": {}, "by_status": {}, "anchor_ids": [],
            })
            b["total"] += 1
            if rec.status == "active":
                b["active"] += 1
            if (str((rec.engine_pair or {}).get("calibrated") or "")
                    .strip().lower() == ANALYTIC_SOURCE_DEFAULT):
                b["closedform"] += 1
            b["by_kind"][rec.kind] = b["by_kind"].get(rec.kind, 0) + 1
            b["by_status"][rec.status] = b["by_status"].get(rec.status, 0) + 1
            b["anchor_ids"].append(rec.anchor_id)
    for b in families.values():
        b["anchor_ids"].sort()
    return {
        "total_anchors": len(anchor_set),
        "family_count": len(families),
        "closedform_total": sum(b["closedform"] for b in families.values()),
        "families": {k: families[k] for k in sorted(families)},
    }
