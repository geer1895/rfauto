"""EMI 诊断知识库（EM-9，round17）——症状→根因→对策的确定性规则引擎。

规格：研究扩充 round17 §四 EM-9——"CM/DM 分离器
判据+近场三板斧+ESD 受扰路径分析入 playbook.yaml"。本批文件面禁写
knowledge/**，知识库按 premortem 先例以模块结构化常量承载；条目 schema 与
knowledge/diagnostics/playbook.yaml 的规则面同构（symptom_fingerprints 多
指纹 AND 同击、root_cause_family、forensic_commands、pit_refs——DP-17 W2
口径），后续如需 playbook 化可由本库确定性导出，不双写双维护。

四个知识域（EM-9 三域 + 谱签名域）：
- spectrum_signature：发射谱/限值余量谱签名判读（时钟谐波族/DC-DC 开关宽带/
  偶奇谐波对称性模式）；
- cm_dm_split：CM/DM 分离器判据（emc_radiated.cm_dm_split 的 dominant 判定
  + 电流钳 µA 量级判据）；
- near_field：近场三板斧（H 探头=电流源 / E 探头=电压源 / 电流钳=缆 CM/DM
  分离——探头选型与读数判读）；
- esd_path：ESD 受扰路径分析（接触直注/缝隙场耦合/缆注入/软失效）。

设计约束（与 premortem 同源， 硬规则 7）：
- 诊断=确定性规则引擎：observations 特征集按静态知识库 AND 匹配，无 LLM、
  无网络、无随机数；多证并击只出候选根因列表（按特异度=触发特征数降序），
  不下黑箱结论（DP-17 playbook 同纪律）；
- 纯函数内核：同输入两次输出逐位一致（JSON sort_keys 往返逐字节同）；
- 出处等级如实（SOURCE_LEVELS）：standard（标准+等级口径）/textbook（书级
  引用，章节未逐字核对不虚构条款号）/application_note/repo_pit（仓内坑号）。
  EMI 现场经验类知识不以"标准"名义拔高等级；数值判据常量全部模块内显式
  命名（可单测钉），不藏魔法数；
- 观测面只读消费邻接面：``margin_observations`` 消费
  ``emi_filter.margin_report`` 的返回 dict；CM/DM 主导观测来自
  ``emc_radiated.cm_dm_split`` 的 dominant 字段（调用方组装传入）——本模块
  零 import 邻接模块（core 内零耦合）。

与 playbook/explain 面（DP-17）的关系：explain_run 是"run 产物指纹→根因族"
（检测器词表在 service/explain_run 侧，看仿真 run 工件）；本模块是"EMI 现场
观测→根因候选"（看测量/仪器观测面），两者正交互不覆盖。

谱签名观测面的测量口径（instrument convention，CISPR 16-1-1 接收机 RBW 档
惯例：30 MHz–1 GHz 准峰值 120 kHz 为常用档）：峰的窄带/宽带分类按 −6dB 宽
（``PEAK_WIDTH_DB``）对 RBW 之比（``NARROWBAND_WIDTH_FACTOR``），RBW 缺省
以频率栅格 df 代理（分辨率受限，如实记录在峰表 bandwidth_class 口径里）。

用法::

    from rfauto.core.emi_diagnostics import emi_diagnose, spectrum_observations

    obs = spectrum_observations(f_hz, amp_db, rbw_hz=120e3)
    hits = emi_diagnose(obs)      # [{cause, evidence_check, remedy_ref, ...}]
    未知观测特征 → ValueError（负例契约，不静默降级）；零命中 → []（如实）。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

#: 知识库 schema 版本（playbook 同构，rfauto-diag-playbook-v1 的 core 侧孪生）。
EMI_DIAGNOSTICS_SCHEMA = "rfauto-emi-diagnostics-v1"

# ---------------------------------------------------------------------------
# 常量：诊断域 / 出处等级 / 判据常量
# ---------------------------------------------------------------------------

#: 四个诊断知识域（EM-9 三域 + 谱签名域）。
DIAGNOSTIC_CATEGORIES: tuple[str, ...] = (
    "spectrum_signature",
    "cm_dm_split",
    "near_field",
    "esd_path",
)

#: 域中文标签（报告渲染面）。
CATEGORY_LABELS: dict[str, str] = {
    "spectrum_signature": "谱签名判读",
    "cm_dm_split": "CM/DM 分离判据",
    "near_field": "近场三板斧",
    "esd_path": "ESD 受扰路径",
}

#: 域→条目 id 前缀（premortem KIND_PREFIX 同构；完整性锚断言）。
CATEGORY_PREFIXES: dict[str, str] = {
    "spectrum_signature": "SIG",
    "cm_dm_split": "CMD",
    "near_field": "NF",
    "esd_path": "ESD",
}

_CATEGORY_ORDER: dict[str, int] = {c: i for i, c in enumerate(DIAGNOSTIC_CATEGORIES)}

#: 出处等级（如实分级；source 字符串必须与等级自洽，完整性锚断言）。
SOURCE_LEVELS: tuple[str, ...] = (
    "standard",          # 标准条文/等级口径（带标准号）
    "textbook",          # 教科书/专著书级引用（未逐字核对章节不虚构条款号）
    "application_note",  # 厂商/应用笔记级（经验口径）
    "repo_pit",          # 仓内坑号提炼（#NNN 可溯）
)

# ── 谱签名观测面判据常量（全部显式命名，单测钉值）────────────────────────────

#: 峰宽测量口径：峰下方多少 dB 处量宽度（噪声/信号判别惯例 6 dB）。
PEAK_WIDTH_DB = 6.0

#: 窄带判别：−6dB 宽 ≤ 此系数 × RBW 记窄带，否则宽带（缺省 RBW=频率栅格 df）。
NARROWBAND_WIDTH_FACTOR = 2.5

#: 缺省峰显著性门（dB）：峰相对两侧谷底的显著度下限。
DEFAULT_PEAK_PROMINENCE_DB = 6.0

#: 谐波族频率匹配容差：max(0.5×df, 此分数 × k×f0)。
HARMONIC_TOL_FRAC = 0.005

#: 缺省谐波阶数扫描上限（k=2..max；超出按未扫如实，不外推）。
DEFAULT_HARMONIC_ORDER_MAX = 12

#: 谐波族成立最少谐波数（不含基频；单配对不成族）。
HARMONIC_MIN_MATCHES = 2

#: 宽带底噪抬升判据一：热点占比门（|amp−max|≤HOT_MARGIN_DB 的栅格占比下限）。
BROADBAND_HOT_FRACTION = 0.2

#: 宽带底噪抬升判据二：热点带宽（与峰顶差 ≤ 此 dB 记热点）。
HOT_MARGIN_DB = 6.0

# ── 余量观测面判据常量 ────────────────────────────────────────────────────

#: 贴线余量门（dB）：0 ≤ min_margin < 此值记"余量紧张"。
TIGHT_MARGIN_DB = 6.0

#: 违限点数 ≥ 此值记"违限广泛"（多点散布→系统性宽带问题方向）。
WIDESPREAD_VIOLATIONS = 5

#: 违限点数 ≤ 此值且 ≥1 记"孤立违限"（单点→单源方向）。
ISOLATED_VIOLATIONS_MAX = 2

# ---------------------------------------------------------------------------
# 特征目录：观测特征词表（emi_diagnose 只认词表内特征，未知键 ValueError）
# ---------------------------------------------------------------------------

#: 特征来源域。
FEATURE_ORIGINS: tuple[str, ...] = (
    "auto_spectrum", "auto_margin", "instrument", "checklist",
)

#: 特征目录：特征名→说明（emi_diagnose 的合法词表；封闭断言锚）。
FEATURE_CATALOG: dict[str, str] = {
    # ── auto_spectrum（spectrum_observations 产出）──
    "peaks_present": "谱内存在显著峰（prominence ≥ 门限）",
    "spectrum_peak_count": "显著峰个数（int，0=无峰）",
    "narrowband_peaks_present": "存在未削边的窄带峰（−6dB 宽 ≤ 2.5×RBW）",
    "broadband_peaks_present": "存在未削边的宽带峰（−6dB 宽 > 2.5×RBW）",
    "broadband_floor_rise": "宽带底噪抬升（热点占比 ≥ 0.2 且谱内有可分峰结构）",
    "harmonic_series_present": "存在谐波族（≥2 个整数倍频峰落容差内）",
    "harmonic_max_order": "检出的最高谐波阶（int，0=无谐波族）",
    "even_harmonics_only": "谐波族全部为偶数阶",
    "odd_harmonics_only": "谐波族全部为奇数阶",
    "harmonic_parity_mixed": "谐波族奇偶混合",
    # ── auto_margin（margin_observations 产出，消费 emi_filter.margin_report）──
    "limit_violations_present": "限值余量报告存在违限点（margin<0）",
    "violation_count": "违限点个数（int）",
    "violations_widespread": "违限广泛（点数 ≥ 5，多点散布）",
    "violations_isolated": "孤立违限（1–2 个点）",
    "min_margin_negative": "最小余量为负（确已违限）",
    "min_margin_tight": "最小余量贴线（0 ≤ margin < 6 dB）",
    "out_of_band_points_present": "存在带外点（限值线未覆盖，不参与判读）",
    # ── instrument（电流钳/场探头类仪器观测，人工按仪器读数置真）──
    "cm_current_microamp_class": "缆共模电流达 µA 量级（电流钳实测；µA 级即足以致 Class B 超标）",
    "cm_dm_split_cm_dominant": "CM/DM 分离对照判 CM 主导（emc_radiated.cm_dm_split dominant='cm'）",
    "cm_dm_split_dm_dominant": "CM/DM 分离对照判 DM 主导（emc_radiated.cm_dm_split dominant='dm'）",
    "cm_choke_applied_reduced": "加共模扼流圈/磁环后发射显著下降（CM 路径确认证据）",
    # ── checklist（近场三板斧/ESD 现场排查核对项，人工按排查记录置真）──
    "nf_h_probe_peak": "H 探头（磁环环路探头）扫到显著热点",
    "nf_h_probe_quiet": "H 探头全程安静（无明显磁热点）",
    "nf_e_probe_peak": "E 探头（短单极探头）扫到显著热点",
    "nf_e_probe_quiet": "E 探头全程安静（无明显电热点）",
    "nf_peak_follows_cable": "热点沿缆线分布/探头贴近缆时读数抬升（缆为辐射体迹象）",
    "esd_contact_fail": "ESD 接触放电下受扰/失败",
    "esd_air_fail_only": "仅空气放电失败、接触放电通过（缝隙场耦合指向）",
    "esd_fail_disappears_cable_removed": "摘除缆后 ESD 失效消失（缆注入路径指向）",
    "esd_soft_reset_only": "ESD 下仅软失效（复位/挂起/误触发），无硬损伤",
}

#: 特征名→来源域（与 FEATURE_CATALOG 同键集，import 期封闭断言）。
FEATURE_ORIGIN: dict[str, str] = {}
for _f in (
    ("peaks_present", "auto_spectrum"), ("spectrum_peak_count", "auto_spectrum"),
    ("narrowband_peaks_present", "auto_spectrum"), ("broadband_peaks_present", "auto_spectrum"),
    ("broadband_floor_rise", "auto_spectrum"), ("harmonic_series_present", "auto_spectrum"),
    ("harmonic_max_order", "auto_spectrum"), ("even_harmonics_only", "auto_spectrum"),
    ("odd_harmonics_only", "auto_spectrum"), ("harmonic_parity_mixed", "auto_spectrum"),
    ("limit_violations_present", "auto_margin"), ("violation_count", "auto_margin"),
    ("violations_widespread", "auto_margin"), ("violations_isolated", "auto_margin"),
    ("min_margin_negative", "auto_margin"), ("min_margin_tight", "auto_margin"),
    ("out_of_band_points_present", "auto_margin"),
    ("cm_current_microamp_class", "instrument"), ("cm_dm_split_cm_dominant", "instrument"),
    ("cm_dm_split_dm_dominant", "instrument"), ("cm_choke_applied_reduced", "instrument"),
    ("nf_h_probe_peak", "checklist"), ("nf_h_probe_quiet", "checklist"),
    ("nf_e_probe_peak", "checklist"), ("nf_e_probe_quiet", "checklist"),
    ("nf_peak_follows_cable", "checklist"),
    ("esd_contact_fail", "checklist"), ("esd_air_fail_only", "checklist"),
    ("esd_fail_disappears_cable_removed", "checklist"), ("esd_soft_reset_only", "checklist"),
):
    FEATURE_ORIGIN[_f[0]] = _f[1]
del _f

if set(FEATURE_ORIGIN) != set(FEATURE_CATALOG):  # pragma: no cover - import 期守卫
    raise ValueError("FEATURE_ORIGIN 与 FEATURE_CATALOG 键集不一致（目录/来源两表必须同步）")

# ---------------------------------------------------------------------------
# 知识条目：症状→根因→对策（playbook 规则面同构 schema）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiagnosticEntry:
    """单条 EMI 诊断知识（症状指纹 → 候选根因 → 取证 → 对策）。

    - entry_id：全局唯一（<域前缀>-<序号>，如 SIG-01）
    - category：所属诊断域（DIAGNOSTIC_CATEGORIES 键）
    - symptom：症状（一句话讲清"看到什么"）
    - trigger_features：触发特征集（AND 语义，全部为真才命中——playbook
      symptom_fingerprints 同构；控归纳过度泛化）
    - cause：候选根因（多证并击只出候选，不下黑箱结论）
    - evidence_check：取证步骤（确定性核实手段，逐条可执行——playbook
      forensic_commands 同构）
    - remedy：对策要点
    - remedy_ref：对策稳定引用（仓内可建模面名 core.<module>.<func> /
      doc:<文献或标准条>）
    - source：出处（与 source_level 等级自洽，出处等级如实）
    - source_level：出处等级（SOURCE_LEVELS 键）
    - lesson_refs：仓内坑号背书（#NNN；无则空元组，不凑）
    """

    entry_id: str
    category: str
    symptom: str
    trigger_features: tuple[str, ...]
    cause: str
    evidence_check: tuple[str, ...]
    remedy: str
    remedy_ref: str
    source: str
    source_level: str
    lesson_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 可直接渲染的字典（消费面键契约稳定）。"""
        return {
            "entry_id": self.entry_id,
            "category": self.category,
            "symptom": self.symptom,
            "trigger_features": list(self.trigger_features),
            "cause": self.cause,
            "evidence_check": list(self.evidence_check),
            "remedy": self.remedy,
            "remedy_ref": self.remedy_ref,
            "source": self.source,
            "source_level": self.source_level,
            "lesson_refs": list(self.lesson_refs),
        }


def _entry(entry_id: str, category: str, symptom: str, triggers: Sequence[str],
           cause: str, evidence: Sequence[str], remedy: str, remedy_ref: str,
           source: str, source_level: str,
           lessons: Sequence[str] = ()) -> DiagnosticEntry:
    """库表紧凑构造（域/等级/特征词表即时校验——坏条目注册即炸）。"""
    if category not in DIAGNOSTIC_CATEGORIES:
        raise ValueError(f"{entry_id}: 未知诊断域 {category!r}")
    if source_level not in SOURCE_LEVELS:
        raise ValueError(f"{entry_id}: 未知出处等级 {source_level!r}")
    unknown = [t for t in triggers if t not in FEATURE_CATALOG]
    if unknown:
        raise ValueError(f"{entry_id}: 触发特征不在词表 {unknown!r}")
    if not triggers:
        raise ValueError(f"{entry_id}: 触发特征集为空（AND 语义至少一特征）")
    return DiagnosticEntry(
        entry_id=entry_id, category=category, symptom=symptom,
        trigger_features=tuple(triggers), cause=cause,
        evidence_check=tuple(evidence), remedy=remedy, remedy_ref=remedy_ref,
        source=source, source_level=source_level, lesson_refs=tuple(lessons),
    )


_SRC_OTT = "Ott, Electromagnetic Compatibility Engineering, Wiley 2009（书级引用；章节未逐字核对不虚构条款号）"
_SRC_PAUL = "Paul, Introduction to Electromagnetic Compatibility, 2nd ed., Wiley 2006（书级引用）"
_SRC_IEC_ESD = "IEC 61000-4-2（ESD 抗扰试验等级口径：接触 2/4/6/8 kV、空气 2/4/8/15 kV）"

#: 诊断知识库（全量条目；entry_id 唯一，域内按序登记）。
DIAGNOSTIC_LIBRARY: tuple[DiagnosticEntry, ...] = tuple(sorted((
    # ── spectrum_signature 谱签名判读 ──────────────────────────────────────
    _entry(
        "SIG-01", "spectrum_signature",
        "窄带峰成谐波族（等间隔整数倍频，峰形随 RBW 不变）",
        ("narrowband_peaks_present", "harmonic_series_present"),
        "数字时钟/晶振及其谐波辐射（时钟基频=峰间隔，谐波包络随脉宽）",
        ("峰间隔对照板内晶振/时钟树频率清单（基频=最小峰间隔）",
         "改变 RBW 复测：窄带信号读数不随 RBW 变化（CISPR 判别惯例）",
         "峰位判读用 −6dB 带心不用 argmax（纹波/平台下 argmax 跳变）"),
        "时钟线串联阻尼电阻/扩谱时钟(SSC)/时钟回流地平面完整/必要时局部屏蔽",
        "doc:Ott 2009 数字电路辐射主题",
        _SRC_OTT,
        "textbook",
        ("#298",),
    ),
    _entry(
        "SIG-02", "spectrum_signature",
        "宽带底噪抬升（热点占比大、无明显离散峰族、沿线毯式抬升）",
        ("broadband_floor_rise",),
        "DC-DC/开关电源宽带噪声（开关沿高 di/dt+二极管反向恢复，开关频率谐波带宽带裙边）",
        ("关断/使能 DC-DC 做 A/B 谱对比（关断后底噪塌落即坐实）",
         "检查开关频率及其倍频处是否仍有峰结构（残留峰=开关谐波）",
         "核对输入滤波器拓扑与磁珠/电解电容实效（老化/直流偏置失配）"),
        "输入端 π 型滤波+开关节点环路缩小+snubber 抑制开关沿（滤波插损可先建模仿算）",
        "core.emi_filter.lc_filter_il",
        _SRC_OTT,
        "textbook",
    ),
    _entry(
        "SIG-03", "spectrum_signature",
        "存在宽带峰（−6dB 宽显著大于 RBW 的连续谱包）",
        ("broadband_peaks_present",),
        "宽带发射源（电机/继电器触点/开关沿包络/数字总线同时翻转的宽带串扰）",
        ("峰包中心频率随 RBW/扫描时间漂移检查（宽带读数随接收机设置变化）",
         "宽带峰的中心/包络报告带平台宽一并给出（平台内 argmax 频移非物理）",
         "时域定位：示波器+近场探头联查源器件开关时刻"),
        "源端抑制（触点RC吸收/缓动电路）+屏蔽+接口滤波，按源器件逐一排除",
        "doc:Ott 2009 宽带噪声主题",
        _SRC_OTT,
        "textbook",
        ("#281",),
    ),
    _entry(
        "SIG-04", "spectrum_signature",
        "谐波族仅含偶数阶（2/4/6…次突出）",
        ("even_harmonics_only",),
        "波形对称性破坏（占空比偏离 50%/差分对直流失衡/半波对称不成立→偶次谐波出现）",
        ("核对驱动波形占空比（50% 方波理论上无偶次；偏离即出偶次）",
         "差分对两臂直流工作点/幅度对称性核查",
         "与同频 50% 占空比理想方波谱对比（理想谱仅奇次）"),
        "恢复对称性（占空比校正/差分均衡/对称布线），偶次谐波随之收敛",
        "doc:周期信号傅里叶分析（半波对称⇔仅奇次）",
        _SRC_PAUL,
        "textbook",
    ),
    _entry(
        "SIG-05", "spectrum_signature",
        "谐波族仅含奇数阶（3/5/7…次突出）",
        ("odd_harmonics_only",),
        "对称方波族特征（50% 占空比时钟/开关波形的典型谐波结构）",
        ("与 SIG-01 联判（奇次族=时钟族特例，先定位基频源再谈抑制）",
         "核对波形占空比确为 50%（排除偶次被漏检：低 RBW 漏峰）"),
        "同 SIG-01 治理路径（时钟源端抑制为主）",
        "doc:周期信号傅里叶分析（半波对称⇔仅奇次）",
        _SRC_PAUL,
        "textbook",
    ),
    _entry(
        "SIG-06", "spectrum_signature",
        "孤立窄带单峰（无谐波族相伴）",
        ("narrowband_peaks_present",),
        "本振/参考源泄漏或单一射频源直射（振荡器辐馈、接口线缆再辐射）",
        ("频点对照板内振荡器/PLL/本振清单（含分频/倍频组合）",
         "近场探头沿布局定位辐射段（板上 vs 缆上分辨——缆上转 CMD 面）"),
        "源端屏蔽/去耦+泄漏路径隔断（腔体/滤波），按频点溯源单点治理",
        "doc:Ott 2009 窄带辐射主题",
        _SRC_OTT,
        "textbook",
    ),
    _entry(
        "SIG-07", "spectrum_signature",
        "违限点广泛散布且宽带底噪抬升（限值线全线压线）",
        ("violations_widespread", "broadband_floor_rise"),
        "系统性宽带问题（电源/地分配系统为共同阻抗耦合通道，而非单点单源）",
        ("电源完整性核查（PDN 阻抗/去耦网络实效）",
         "单点治理试验：逐个断电分板，违限面整体塌落=系统性问题坐实"),
        "先做电源/地系统治理（去耦+平面完整+共模抑制），再谈单点屏蔽",
        "core.emi_filter.lc_filter_il",
        _SRC_OTT,
        "textbook",
    ),
    # ── cm_dm_split CM/DM 分离器判据 ───────────────────────────────────────
    _entry(
        "CMD-01", "cm_dm_split",
        "CM/DM 分离对照判 CM 主导（闭式对照 delta_db>0）",
        ("cm_dm_split_cm_dominant",),
        "缆线共模电流辐射（回流路径缺失/地电位差驱动缆为单极子天线）",
        ("电流钳套全缆量总共模电流（CM 电流 µA 量级即可致 Class B 超标量级）",
         "摘缆复测辐射发射（塌落=缆辐射坐实；不塌=回查板上源）",
         "闭式复算对照限值：core.emc_radiated.cm_radiated_field"),
        "共模扼流圈/磁环+改善回流搭接+屏蔽层 360° 端接（扼流圈插损可先建模仿算）",
        "core.emi_filter.cm_choke_il",
        _SRC_OTT,
        "textbook",
    ),
    _entry(
        "CMD-02", "cm_dm_split",
        "电流钳实测缆共模电流达 µA 量级",
        ("cm_current_microamp_class",),
        "共模电流即辐射主因（缆等效单极子：µA 级 CM 电流 @百 MHz、米级缆即达 Class B 量级）",
        ("闭式复算场强对照限值（core.emc_radiated.cm_radiated_field）",
         "沿缆滑动电流钳定位 CM 电流注入点（靠近接口入口处最大）"),
        "在注入点就近施加共模抑制（磁环/CM 扼流圈/接口滤波），复测钳流验证收敛",
        "core.emc_radiated.cm_radiated_field",
        _SRC_OTT,
        "textbook",
    ),
    _entry(
        "CMD-03", "cm_dm_split",
        "CM/DM 分离对照判 DM 主导（闭式对照 delta_db<0）",
        ("cm_dm_split_dm_dominant",),
        "差模环路辐射（信号-回流环路面积过大，等效小环天线）",
        ("闭式复算对照限值（core.emc_radiated.dm_loop_radiated_field）",
         "近场 H 探头沿环路走线定位最大环段（转 NF 面）",
         "高频去耦电容就近核查（回流被追绕=环路面积放大）"),
        "缩小关键信号回路面积（就近去耦/回流地平面完整/差分对称）",
        "core.emc_radiated.dm_loop_radiated_field",
        _SRC_OTT,
        "textbook",
    ),
    _entry(
        "CMD-04", "cm_dm_split",
        "加共模扼流圈/磁环后发射显著下降",
        ("cm_choke_applied_reduced",),
        "CM 路径确认（对策有效=路径假设的因果证据，非巧合）",
        ("复测 margin_report 核对余量恢复量（量化改善 dB 数入记录）",
         "磁环材料阻抗-频率曲线与问题频段匹配核查（感性区才有效）"),
        "定型共模扼流圈/磁环入设计+接口滤波固化（扼流圈插损可建模仿算定型值）",
        "core.emi_filter.cm_choke_il",
        _SRC_OTT,
        "textbook",
    ),
    # ── near_field 近场三板斧 ──────────────────────────────────────────────
    _entry(
        "NF-01", "near_field",
        "近场扫描 H 探头热、E 探头冷（磁场主导热点）",
        ("nf_h_probe_peak", "nf_e_probe_quiet"),
        "电流驱动型源（开关环路/地弹/回流缺口——低阻电流环辐射，近场磁场强）",
        ("H 探头沿走线逐段扫（热点段=环路最大 di/dt 段）",
         "热点频段与开关/时钟频率对表（对上=环路归属坐实）"),
        "缩小该环路面积/就近去耦/串联阻尼（源端抑制优先于屏蔽）",
        "doc:Ott 2009 近场探测主题",
        _SRC_OTT,
        "textbook",
    ),
    _entry(
        "NF-02", "near_field",
        "近场扫描 E 探头热、H 探头冷（电场主导热点）",
        ("nf_e_probe_peak", "nf_h_probe_quiet"),
        "电压驱动型源（高阻电压节点：时钟走线开路端/散热器/屏蔽体浮置谐振）",
        ("E 探头热点对照高阻节点清单（时钟线端/未端接导体）",
         "浮置导体按压接地试验（压上后热点消失=浮置谐振坐实）"),
        "护卫地线/串联阻尼/浮置导体多点接地或屏蔽罩",
        "doc:Ott 2009 近场探测主题",
        _SRC_OTT,
        "textbook",
    ),
    _entry(
        "NF-03", "near_field",
        "热点沿缆分布/探头贴近缆读数抬升（三板斧第三斧指向缆）",
        ("nf_peak_follows_cable",),
        "缆为辐射体（板上热点只是激励源，辐射主体在缆——治理面在接口而非板上）",
        ("电流钳分 CM/DM（套全缆=CM，双线同套=DM，转 CMD 面定对策）",
         "摘缆复测发射（塌落量=缆贡献占比）"),
        "接口端滤波+共模抑制+屏蔽搭接（板上源头仍按 NF-01/NF-02 源端抑制）",
        "doc:Ott 2009 缆线辐射主题",
        _SRC_OTT,
        "textbook",
    ),
    _entry(
        "NF-04", "near_field",
        "近场扫描 E/H 探头同频段均热（复合场热点）",
        ("nf_e_probe_peak", "nf_h_probe_peak"),
        "复合源或腔体谐振（屏蔽体内驻留模式把两类场同点放大）",
        ("热点频点与屏蔽腔体谐振估算对表（f≈c/(2d)，d=腔体最大边）",
         "腔内加吸波/分隔后复扫（热点塌落=腔谐振坐实）"),
        "腔体分隔/吸波处理+热点区源端复核（腔谐振治理后再读板面源）",
        "doc:屏蔽腔体谐振主题（Ott 2009）",
        _SRC_OTT,
        "textbook",
    ),
    # ── esd_path ESD 受扰路径分析 ──────────────────────────────────────────
    _entry(
        "ESD-01", "esd_path",
        "接触放电下受扰/失败",
        ("esd_contact_fail",),
        "ESD 电流经放电点直注入电路（接触放电 8 kV 级电流峰值数十安、上升沿 ~1 ns 量级）",
        ("逐连接器/缝隙放电定位入口（哪个点放哪个坏）",
         "断开缆/接口复测（路径隔离验证）",
         "放电等级口径对表（IEC 61000-4-2 接触 2/4/6/8 kV）"),
        "接口 TVS+串联阻抗（串阻/共模扼流）+放电点就近低感接地（地过孔/回流地平面完整）",
        "doc:IEC 61000-4-2 试验配置与等级",
        _SRC_IEC_ESD,
        "standard",
    ),
    _entry(
        "ESD-02", "esd_path",
        "仅空气放电失败、接触放电通过",
        ("esd_air_fail_only",),
        "缝隙/孔洞场耦合或电弧到内线（空气放电空间场路径为主，接触直注路径未涉）",
        ("缝隙长度核查（缝隙天线谐振：L≈λ/2 对应频段最敏感）",
         "临时导电胶带封缝复测（封缝后通过=缝隙路径坐实）",
         "放电等级口径对表（IEC 61000-4-2 空气 2/4/8/15 kV）"),
        "缝隙导电衬垫/缩短缝隙/内部敏感线远离缝隙（受扰路径与缝隙解耦）",
        "doc:IEC 61000-4-2 等级口径+缝隙屏蔽主题（Ott 2009）",
        _SRC_IEC_ESD,
        "standard",
    ),
    _entry(
        "ESD-03", "esd_path",
        "摘除缆后 ESD 失效消失",
        ("esd_fail_disappears_cable_removed",),
        "ESD 经缆耦合注入（缆为受扰路径主体：放电场耦合/地抬升经缆传入门内电路）",
        ("逐缆摘除定位（哪根缆摘掉就好）",
         "该缆接口滤波与屏蔽搭接现状核查（360° 端接是否名存实亡）"),
        "该缆接口加共模磁环/滤波阵列+屏蔽层 360° 搭接机壳",
        "doc:Ott 2009 ESD 主题",
        _SRC_OTT,
        "textbook",
    ),
    _entry(
        "ESD-04", "esd_path",
        "ESD 下仅软失效（复位/挂起/误触发，无硬损伤）",
        ("esd_soft_reset_only",),
        "敏感监测/复位路径受扰（复位脚/看门狗/电源监测器被 ESD 瞬态误触发）",
        ("示波器监测复位/中断/使能脚（放电瞬间抓毛刺=误触发点坐实）",
         "复现后功能自恢复核查（软失效 vs 损伤分流——软失效按抗扰治理）"),
        "复位脚 RC 滤波+逻辑门限裕量核查+看门狗策略+敏感脚局部去耦",
        "doc:Ott 2009 ESD 主题",
        _SRC_OTT,
        "textbook",
    ),
), key=lambda e: (_CATEGORY_ORDER[e.category], e.entry_id)))

if len({e.entry_id for e in DIAGNOSTIC_LIBRARY}) != len(DIAGNOSTIC_LIBRARY):  # pragma: no cover
    raise ValueError("DIAGNOSTIC_LIBRARY 条目 id 重复（注册即炸）")

# ---------------------------------------------------------------------------
# 查询面：确定性规则引擎
# ---------------------------------------------------------------------------


def emi_diagnose(observations: Mapping[str, object],
                 *, categories: Sequence[str] | None = None) -> list[dict[str, object]]:
    """观测特征集 → 候选根因条目列表（确定性规则引擎， 硬规则 7）。

    匹配语义：条目 trigger_features 全部在 observations 中为真即命中（AND，
    playbook 同击语义）；多证并击只出候选列表，不下黑箱结论。

    排序（确定性）：触发特征数多者优先（特异度降序），同数按域序（
    DIAGNOSTIC_CATEGORIES 顺序），再按 entry_id 字典序。

    Args:
        observations: 观测特征 dict——键必须 ∈ FEATURE_CATALOG（未知键
            ValueError，负例契约不静默降级，防错别字静默零命中）；值按
            真值判定（bool/int，0/False=未观测）。缺失特征=假，无需显式置假。
        categories: 限定诊断域（None=全域）；未知域 ValueError。

    Returns:
        list[dict]: 命中条目 to_dict() 列表（cause/evidence_check/remedy_ref
        及溯源字段），按上述确定性排序。零命中返回 []（如实）。
    """
    if not isinstance(observations, Mapping):
        raise TypeError(f"observations 须为 Mapping，实际 {type(observations).__name__}")
    unknown = sorted(k for k in observations if k not in FEATURE_CATALOG)
    if unknown:
        raise ValueError(
            f"未知观测特征 {unknown!r}（合法词表见 FEATURE_CATALOG，"
            f"共 {len(FEATURE_CATALOG)} 项）")
    if categories is None:
        cats = DIAGNOSTIC_CATEGORIES
    else:
        unknown_cat = [c for c in categories if c not in DIAGNOSTIC_CATEGORIES]
        if unknown_cat:
            raise ValueError(
                f"未知诊断域 {unknown_cat!r}（合法域: {', '.join(DIAGNOSTIC_CATEGORIES)}）")
        wanted = set(categories)
        cats = tuple(c for c in DIAGNOSTIC_CATEGORIES if c in wanted)
    truthy = {k for k, v in observations.items() if bool(v)}
    hits = [
        e for e in DIAGNOSTIC_LIBRARY
        if e.category in cats and all(t in truthy for t in e.trigger_features)
    ]
    hits.sort(key=lambda e: (-len(e.trigger_features), _CATEGORY_ORDER[e.category], e.entry_id))
    return [e.to_dict() for e in hits]


# ---------------------------------------------------------------------------
# 观测面 A：谱签名特征提取（发射谱/余量谱 → 词表特征；确定性纯函数）
# ---------------------------------------------------------------------------


def _freq_array(f: object, name: str) -> np.ndarray:
    """频率轴校验（正有限一维；与 emi_filter 同纪律、本地实现零耦合）。"""
    arr = np.atleast_1d(np.asarray(f, dtype=float))
    if arr.ndim != 1:
        raise ValueError(f"{name} 必须一维，实际 shape {arr.shape}")
    if arr.size == 0:
        raise ValueError(f"{name} 不能为空")
    if not np.all(np.isfinite(arr)) or np.any(arr <= 0):
        raise ValueError(f"{name} 必须全为正有限数")
    return arr


def _amp_array(amp: object) -> np.ndarray:
    """幅度轴（dB）校验（有限一维）。"""
    arr = np.atleast_1d(np.asarray(amp, dtype=float))
    if arr.ndim != 1:
        raise ValueError(f"amp_db 必须一维，实际 shape {arr.shape}")
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"amp_db 必须全为有限数，实际 {amp!r}")
    return arr


def _side_base(amp: np.ndarray, i: int, step: int) -> float:
    """峰一侧的谷底基准：沿 step 方向走到首个高于峰值的样本（或阵列端），返回路径最小值。

    两侧谷底取大者得 prominence（scipy 口径的简化确定性实现：全局峰两侧
    走到阵列端时以该侧半边最小值为基准）。
    """
    level = float(amp[i])
    run_min = level
    j = i + step
    while 0 <= j < amp.size:
        v = float(amp[j])
        if v > level:
            break
        if v < run_min:
            run_min = v
        j += step
    return run_min


def spectrum_peaks(f: object, amp_db: object, *,
                   rbw_hz: float | None = None,
                   peak_prominence_db: float = DEFAULT_PEAK_PROMINENCE_DB,
                   ) -> list[dict[str, object]]:
    """谱峰表：显著峰逐峰给出位置/电平/−6dB 宽/窄宽带分类/削边标记（确定性）。

    分类口径：width_6db ≤ NARROWBAND_WIDTH_FACTOR×RBW 记 "narrow"，否则
    "broad"；−6dB 走查触及阵列端（峰在带缘，宽度被观测窗截断）记
    "undetermined"（clipped=True，不参与窄/宽带计数——如实不猜）。RBW 缺省
    以频率栅格中位差 df 代理（分辨率受限口径，模块 docstring 声明）。
    """
    f_arr = _freq_array(f, "f")
    amp = _amp_array(amp_db)
    if f_arr.shape != amp.shape:
        raise ValueError(f"f 与 amp_db 长度必须一致，实际 {f_arr.shape} vs {amp.shape}")
    if amp.size < 3:
        raise ValueError(f"谱点数不足以判读峰形（需 ≥3），实际 {amp.size}")
    if not math.isfinite(peak_prominence_db) or peak_prominence_db <= 0:
        raise ValueError(f"peak_prominence_db 必须为正有限数，实际 {peak_prominence_db!r}")
    if rbw_hz is not None:
        rbw = float(rbw_hz)
        if not math.isfinite(rbw) or rbw <= 0:
            raise ValueError(f"rbw_hz 必须为正有限数，实际 {rbw_hz!r}")
    else:
        rbw = float(np.median(np.diff(f_arr)))
    out: list[dict[str, object]] = []
    for i in range(1, amp.size - 1):
        # 峰候选：左邻严格低 + 右邻不高于（平台峰取平台左缘，确定性约定）
        if not (amp[i] > amp[i - 1] and amp[i] >= amp[i + 1]):
            continue
        level = float(amp[i])
        prominence = level - max(_side_base(amp, i, -1), _side_base(amp, i, +1))
        if prominence < peak_prominence_db:
            continue
        thr = level - PEAK_WIDTH_DB
        j = i
        while j > 0 and amp[j - 1] >= thr:
            j -= 1
        clipped_left = j == 0 and amp[0] >= thr
        k = i
        while k < amp.size - 1 and amp[k + 1] >= thr:
            k += 1
        clipped_right = k == amp.size - 1 and amp[-1] >= thr
        width_hz = float(k - j) * rbw  # 栅格分辨率口径（df 代理时为下界近似）
        if clipped_left or clipped_right:
            bw_class = "undetermined"
        elif width_hz <= NARROWBAND_WIDTH_FACTOR * rbw:
            bw_class = "narrow"
        else:
            bw_class = "broad"
        out.append({
            "f_hz": float(f_arr[i]),
            "level_db": level,
            "prominence_db": float(prominence),
            "width_6db_hz": width_hz,
            "bandwidth_class": bw_class,
            "clipped": bool(clipped_left or clipped_right),
        })
    return out


def spectrum_observations(f: object, amp_db: object, *,
                          rbw_hz: float | None = None,
                          peak_prominence_db: float = DEFAULT_PEAK_PROMINENCE_DB,
                          harmonic_order_max: int = DEFAULT_HARMONIC_ORDER_MAX,
                          ) -> dict[str, object]:
    """发射谱 → 词表观测特征（emi_diagnose 可直接消费的 auto_spectrum 子集）。

    特征判据（全部确定性、常量显式命名）：
    - 峰检出与窄/宽带分类见 spectrum_peaks（削边峰不参与窄/宽带计数）；
    - 谐波族：以最高电平峰为基频候选（同电平取最低频），k=2..harmonic_order_max
      逐阶在容差 max(0.5×df, HARMONIC_TOL_FRAC×k×f0) 内配峰；≥
      HARMONIC_MIN_MATCHES 阶配中记族成立；奇偶模式按配中阶集合判定；
    - 宽带底噪抬升：热点（|amp−max|≤HOT_MARGIN_DB）占比 ≥
      BROADBAND_HOT_FRACTION 且谱内存在可分峰结构（纯平底无结构不判，如实）。
    """
    f_arr = _freq_array(f, "f")
    amp = _amp_array(amp_db)
    if f_arr.shape != amp.shape:
        raise ValueError(f"f 与 amp_db 长度必须一致，实际 {f_arr.shape} vs {amp.shape}")
    if not isinstance(harmonic_order_max, int) or isinstance(harmonic_order_max, bool) \
            or harmonic_order_max < 2:
        raise ValueError(f"harmonic_order_max 必须为 ≥2 的整数，实际 {harmonic_order_max!r}")
    peaks = spectrum_peaks(f_arr, amp, rbw_hz=rbw_hz, peak_prominence_db=peak_prominence_db)
    df = float(np.median(np.diff(f_arr)))
    n_classified = [p for p in peaks if not p["clipped"]]
    narrow = any(p["bandwidth_class"] == "narrow" for p in n_classified)
    broad = any(p["bandwidth_class"] == "broad" for p in n_classified)

    # 谐波族：基频候选=最高电平峰（同电平取最低频——(-level, f) 全序，确定性）
    orders: list[int] = []
    if peaks:
        pk = max(peaks, key=lambda p: (p["level_db"], -p["f_hz"]))
        f0 = float(pk["f_hz"])
        others = [p for p in peaks if p is not pk]
        for p in others:
            for k in range(2, harmonic_order_max + 1):
                tol = max(0.5 * df, HARMONIC_TOL_FRAC * k * f0)
                if abs(float(p["f_hz"]) - k * f0) <= tol:
                    orders.append(k)
                    break
        orders.sort()
    series = len(orders) >= HARMONIC_MIN_MATCHES
    even = [k for k in orders if k % 2 == 0]
    odd = [k for k in orders if k % 2 == 1]

    max_amp = float(np.max(amp))
    hot_fraction = float(np.count_nonzero(amp >= max_amp - HOT_MARGIN_DB)) / float(amp.size)
    floor_rise = bool(peaks) and hot_fraction >= BROADBAND_HOT_FRACTION

    return {
        "peaks_present": bool(peaks),
        "spectrum_peak_count": len(peaks),
        "narrowband_peaks_present": narrow,
        "broadband_peaks_present": broad,
        "broadband_floor_rise": floor_rise,
        "harmonic_series_present": series,
        "harmonic_max_order": max(orders) if orders else 0,
        "even_harmonics_only": series and bool(even) and not odd,
        "odd_harmonics_only": series and bool(odd) and not even,
        "harmonic_parity_mixed": series and bool(even) and bool(odd),
    }


# ---------------------------------------------------------------------------
# 观测面 B：限值余量报告特征提取（只读消费 emi_filter.margin_report 返回 dict）
# ---------------------------------------------------------------------------

#: margin_observations 必需键（emi_filter.margin_report 返回 dict schema 的子集）。
_MARGIN_REPORT_REQUIRED_KEYS: tuple[str, ...] = (
    "n_violations", "min_margin_db", "n_out_of_band", "verdict",
)


def margin_observations(report: Mapping[str, object]) -> dict[str, object]:
    """margin_report 返回 dict → 词表观测特征（auto_margin 子集，只读消费）。

    判读纪律：min_margin_db 的"缺失"用 is not None 显式判（None=带内全无
    覆盖的合法形态），不用真值判定顶替（#364④：0.0 是合法的贴线值）。
    带外点不参与违限判读（margin_report 语义），但如实报告存在性。
    """
    missing = [k for k in _MARGIN_REPORT_REQUIRED_KEYS if k not in report]
    if missing:
        raise ValueError(
            f"report 缺键 {missing!r}（须为 emi_filter.margin_report 的返回 dict 或同 schema）")
    n_viol = int(report["n_violations"])  # type: ignore[arg-type]
    n_out = int(report["n_out_of_band"])  # type: ignore[arg-type]
    raw_min = report["min_margin_db"]
    min_margin = None if raw_min is None else float(raw_min)  # type: ignore[arg-type]
    return {
        "limit_violations_present": n_viol >= 1,
        "violation_count": n_viol,
        "violations_widespread": n_viol >= WIDESPREAD_VIOLATIONS,
        "violations_isolated": 1 <= n_viol <= ISOLATED_VIOLATIONS_MAX,
        "min_margin_negative": min_margin is not None and min_margin < 0.0,
        "min_margin_tight": min_margin is not None and 0.0 <= min_margin < TIGHT_MARGIN_DB,
        "out_of_band_points_present": n_out >= 1,
    }
