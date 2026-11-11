"""em_bench_service —— 电磁 Agent 基准骨架（aurora_q Q-W8-5，R10 空白地图 P1 位）。

R10 空白地图（runs/aurora_q/r10/PAPERS.md §7）：电磁自动化 Agent 基准
（引擎接地+质量门指标+防泄漏）截至 2026-11 仍零占位——CFD 有 CFDLLMBench、
PCB 有 PCBWorld-Bench，EM/RF 器件级无。本模块=该基准的**骨架/最小可评测**
层：把 rfauto 既有确定性资产（闭式综合内核/质量门/健康门/失败分类表/
round-trip 证书/FTS5 检索）组织成三件：

1. **task 集**：:class:`BenchTask` 声明式 schema（task_id/family/输入
   spec/判据列表（阈值预声明）/数据源）+ :func:`default_bench_tasks`
   首批 8 任务（syn-mline/syn-cpw/wilkinson-campaign/
   kicad-sch-roundtrip/vendor-search + aurora_q Q-X15 扩容：
   layered-stack-synthesis/afs-fsv-quality + aurora_q Q-X22 扩容：
   suspended-stripline-anchor——第 9 任务 ssl_anchor family，Q-X20 FD
   静流第三方裁判接入：fd_convergence/three_way_consistency 两新判据，
   跨引擎三方判据 FD+闭式+HFSS implied；aurora_q Q-X43 扩容 9→12：
   suspended-stripline-param-race（ssl_race family——4 参数 ±10%/±20% 单轴
   扰动确定性枚举表，fd_convergence+closedform_match 双判据批量最坏聚合）/
   ssl-g5-attribution（ssl_g5 family——Q-RM-4 G5 归因数据 as-recorded 基准
   任务化：over_unity 零容差门+passivity 超单位门，306 点超域如实 FAIL）/
   suspended-stripline-synthesis-matrix（ssl_matrix family——(b,h,εr) 笛卡尔
   2³ 采样×综合面反解 w×FD 裁判双通道，three_way 一致性批量）+ aurora_q
   Q-X55 扩容 12→15：branchline-campaign（campaign 第二器件族，prompt 型
   缺省变体枚举表 ：data:`DEFAULT_PROMPT_VARIANTS` 随
   ：func:`default_prompt_variants` 消费）/layered-stack-verdict
   （layered_verdict family——Q-X26 双档对照判读服务消费，RC 三因子分解，
   as-recorded 三档冻结快照）/suspended-stripline-rereverify（ssl_rereverify
   family——Q-X27 三态对照判读单源消费，as-recorded 基准））；
2. **评测器**：:func:`run_bench_task` —— 判据函数注册表（每判据=确定性
   函数，数值只出内核，铁律 7）× 任务 runner 注册表（每 family 走既有
   service 真函数确定性执行，零 stub 数值）→ TaskResult{verdict, scores,
   evidence_path}；
3. **得分卡**：:func:`score_bench` —— 逐任务 verdict + ChatCFD 对表
   三口径（success_rate / interface_failure_rate / token_cost；token_cost
   无计费账本如实 None——缺就是不缺数，不冒充实测）。

T-Q24 判据吸收对照（CAD-Agent 开发交接文档 §12.5 学术共识「不用 LLM 打分，
用确定性可执行判据」）：

===========================  ==========================  ==============================
T-Q24 学术判据                本模块判据枚举               落地通道
===========================  ==========================  ==============================
网表连通等价/round-trip 证书   ``certificate_pass``        kicad_sch_service.round_trip_
（Jaccard/二值）                                           certificate（Q-CAD-2 通用件
                                                           跨域复用）
有效电路率/编译通过率          ``success_rate``            vendor 检索命中面（下界极性）
DRC 违例计数                   ``drc_count``               Omni/PCBWorld 引擎检查口径
                                                           （注册表在位，首批任务预留）
ERC 分级                       ``erc_clean``               kicad-cli 子进程；缺席如实
                                                           unknown
SPICE/功能验证                 ``closedform_match``        core.synthesis 闭式回代自洽
质量门判读                     ``gate_pass``               campaign/synthesis 质量杆
成本效率（Token ROI）          ``token_cost``              预留（无计费账本如实 unknown）
===========================  ==========================  ==============================

零 LLM 打分：本模块源代码无任何 LLM 通道 import（tests AST 静态钉）。
任务准入与判据增强包（aurora_r R-01）同文件后续节；提案器跑分批面
（scripted/LLM 双通道提案）为内部档扩展位，不在公开树。
任务保持 fail-closed 不猜（缺判据=如实 unknown，不凑分）。

**并列 vs 扩展 agent_bench.py 的判定记录**：service/agent_bench.py 是
「轨迹记录打分」内核（records 由调用方注入；两轴=TSA/FCA+工件/数值；
公开/私有 YAML 双集+回归门+prompt 回归门——生命周期=比较，不执行任务）。
本模块是「任务执行+判据评测」层（runner 真跑既有 service 函数产出
measures → 判据注册表逐条评定 → 得分卡汇总——生命周期=执行→判据→汇总）。
两者契约（trajectory record vs TaskResult）、判据词汇（metric 名 vs 判据
枚举）、任务面（YAML goldset vs 声明式 BenchTask）均不同；扩展会把两个
生命周期混进 1059 行成熟模块且零收益承担回归风险。故**并列新模块**：
agent_bench.py 本席零改动；后续跑分批可对接两面（design_chain record →
agentbench 两轴；本模块 TaskResult → 得分卡）。

verdict 语义（预声明，#122）：判据层每条 ∈ {pass, fail, unknown}；任务层
verdict = 任一判据 fail → **fail**；全部 pass → **pass**；其余（含判据
测度缺失/通道缺席如 ERC 无 kicad-cli）→ **unknown**——显式不凑分。任务
定义错误（未知 family/必填阈值缺失/schema 非法）与 runner 异常 →
verdict=**fail**（stage=validate/execute 区分，记 errors——基准跑分中
 ill-defined 任务计失败，不静默丢出得分卡）。

runs/ 湖零写入：全 runner 统一在 work_root 的 cwd 隔离下执行（#144 家族
纪律——service 层 cwd 相对写面一律落 work_root，绝不污染真实 runs/ 湖）；
一次性产物落 work_root（缺省=tempfile），证据落显式 evidence_dir（缺省
None 拒写——vendor_doc #144 同款）。零网络：全部 runner 离线形态（fake
适配器/本地子进程/本地 SQLite），LLM 通道零触碰（#139）。

**判据增强包（aurora_r R-01，AX-1+B3；五仓思想汇流，全部思想级重写零搬运）**：
在既有 BenchTask/判据注册表/评测器/得分卡四件上纯增量六件——

1. **grader_notes/rubric 字段**（razavi-bench golden 内嵌 rubric 思想）：
   :class:`BenchGraderNotes`（correct_core 正确核列表+common_errors 常见
   错答列表+partial_credit 部分分规则描述）作为 ``BenchTask.grader_notes``
   可选字段——纯数据声明+报告面透出（TaskResult/score_bench 逐任务行），
   零 LLM 打分（判读仍是确定性判据注册表）；
2. **spec_score 部分分列**（code-a-chip spec score 思想）：
   :func:`spec_score_from_scores`——失败设计按通过检查数占比给 0~1 分
   （unknown 判据不进分子分母；全 unknown/空 → None 如实缺席）。
   TaskResult/score_bench 新增 ``spec_score`` 列与均值口径；**verdict 语义
   零变**（pass/fail/unknown 三态聚合一字不动，spec_score 只是附加报告列，
   #122 不凑绿红线不破）；
3. **hidden/visible 双层判据**（behavioral-veriloga-eval test_hidden/
   test_visible 思想）：``BenchTask.hidden_criteria`` 可选隐藏层（与
   ``criteria`` 公开层同名互斥——schema 校验拦截跨层重复）。判定时两层
   都算（verdict 聚合含隐藏层）；报告默认只出 visible 明细（``scores``）
   +hidden 汇总（``hidden_summary``={n_total,n_pass,n_fail,n_unknown}，
   不出隐藏层逐条细节——防"对着裁判调参"）；
4. **negative_variants 反例集**（vaBench negative_variants 思想）：
   ``BenchTask.negative_variants`` 可选反例输入（variant_id+input_spec），
   :func:`check_negative_variants` 行为自检——反例须被判据判 **fail**
   （pipeline ok=True 且 stage=execute 且 verdict=fail 才算"判据判 fail"，
   执行崩溃的 fail 不算——不凑绿）；有反例判不出 fail → 检查态
   **unknown** 如实登记；缺省任务 vendor-search 已带一条真反例
   （期望词不在语料的空命中查询——投机解/空检索必败实证）；
5. **no-op 必败门+任务准入门**（terminal-bench-science oracle×5/no-op
   必败门思想）：:func:`admit_bench_task` 三探针——①no-op 探针（把
   "什么都不做"的输出喂给判据必须得 fail；"无输出"按判据单源
   :data:`NOOP_PROBE_MEASURES` 确定性定义：布尔/计数判据=空产出即 fail，
   数值判据缺测=unknown 既有语义不改——故纯数值判据任务的 no-op 探针
   如实 unknown → 准入 quarantined 不凑）②oracle 稳定探针（同一已知好
   输出重复判 5 次结果一致且判 pass）③反例自检（同 4）。准入结果三态：
   **admitted**（三探针全过）/ **quarantined**（结构合法但探针未证明——
   如实标记不静默）/ **rejected**（结构拒绝：schema/runner/阈值缺失）；
   :func:`admit_bench_tasks` 批量分区（admitted/quarantined/rejected
   三清单——任务集装载面的"注册被拒或标记 quarantined"记账）；
6. **B3 OOD 探针+训练包络守卫**（四文计划 B3 思想）：
   ``BenchTask.envelope`` 可选包络声明（参数域 bounds，:class:
   `EnvelopeBound` min/max）；:func:`bench_envelope_point` 从 input_spec
   确定性提取评估点（有限数值叶，深度优先首现胜）；:func:
   `evaluate_bench_envelope` 纯函数判定——评估点越界 → TaskResult 附加
   ``ood_flag=true``（**不改 verdict 本体**）；包络未声明 → ``envelope.
   status="absent"`` 如实输出（不伪造）；包络已声明但评估点缺键 →
   ood_flag=false+unverified_keys 如实（未验证不判 OOD）。

**CLI 挂账处方（本席无 CLI 叶——两步接线，主代合流面执行）**：
① ``cli/domains/`` 新建 em_bench 域（参照既有 typer 域形态）两叶：
``em-bench admit <task_id>``（薄壳调 :func:`admit_bench_task`，oracle
测度由任务声明面 JSON 供给，--json 旗标必带——W2 棘轮门口径）与
``em-bench score``（薄壳调 :func:`score_bench` 消费证据目录结果 JSON）；
② ``cli/main.py`` 注册域+tests 锚（test_cli_registration_order/
test_check_numbers/help 卫生）同笔更新——新 CLI 叶三件套纪律。
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from rfauto.service.envelope import normalize_errors

__all__ = [
    "BENCH_FAMILIES",
    "BENCH_SCHEMA_VERSION",
    "CRITERIA_NAMES",
    "NOOP_PROBE_MEASURES",
    "THRESHOLD_REQUIRED",
    "BenchCriterion",
    "BenchGraderNotes",
    "BenchNegativeVariant",
    "BenchRunContext",
    "BenchTask",
    "EnvelopeBound",
    "admit_bench_task",
    "admit_bench_tasks",
    "bench_envelope_point",
    "check_negative_variants",
    "criterion_fn",
    "default_bench_tasks",
    "evaluate_bench_envelope",
    "register_criterion",
    "register_runner",
    "registered_criteria",
    "registered_families",
    "run_bench_task",
    "score_bench",
    "spec_score_from_scores",
]

BENCH_SCHEMA_VERSION = 1

#: 判据枚举（T-Q24 学术判据吸收后的闭集；新判据尾部追加——summary/得分卡
#: 按注册序稳定输出）。
CRITERIA_NAMES: tuple[str, ...] = (
    "closedform_match",   # 闭式对照（回代自洽相对偏差；上界极性）
    "gate_pass",          # 质量门判读（布尔极性）
    "certificate_pass",   # round-trip 二值证书（布尔极性；Q-CAD-2 通用件）
    "erc_clean",          # ERC 违例计数 ≤ 阈值（上界极性；缺席 unknown）
    "drc_count",          # DRC 违例计数 ≤ 阈值（上界极性；预留）
    "success_rate",       # 成功率 ≥ 阈值（下界极性）
    "token_cost",         # Token 成本 ≤ 阈值（上界极性；无账本 unknown）
    "fsv_grade",          # FSV GDM 等级 ≤ 阈值（上界极性；Q-X15 afs-fsv-quality）
    "fd_convergence",     # FD Richardson 残差 ≤ 阈值（上界极性；Q-X22 ssl_anchor）
    "three_way_consistency",  # 三方一致性双界（FD vs 闭式/FD vs HFSS implied；Q-X22）
)

#: 必须预声明阈值的判据（#122 阈值预声明纪律：缺阈值=任务定义错误，
#: run_bench_task 入口 fail-closed 拦截；布尔判据 gate_pass/certificate_pass
#: 免阈值）。
THRESHOLD_REQUIRED: frozenset[str] = frozenset({
    "closedform_match", "success_rate", "erc_clean", "drc_count", "token_cost",
    "fsv_grade", "fd_convergence", "three_way_consistency",
})

#: 任务 family 闭集（=runner 注册面预期键；新 family 经 register_runner 尾部追加）。
BENCH_FAMILIES: tuple[str, ...] = (
    "synthesis", "campaign", "kicad_sch", "vendor_search", "afs_sweep",
    "ssl_anchor",
    # Q-X43 扩容（aurora_q anchor 覆盖面）：ssl_race=param_race 变体批量 /
    # ssl_g5=G5 归因数据基准 / ssl_matrix=综合变体矩阵（尾部追加闭集纪律）。
    "ssl_race", "ssl_g5", "ssl_matrix",
    # Q-X55 扩容（aurora_q EM bench 第二席）：layered_verdict=layered_stack
    # 双档对照判读（Q-X26 服务消费）/ ssl_rereverify=悬置带线双修复重验
    # 三态对照（Q-X27 判读单源消费）——尾部追加闭集纪律。
    "layered_verdict", "ssl_rereverify",
)

#: 任务 verdict 词表。
VERDICTS: tuple[str, ...] = ("pass", "fail", "unknown")


# ---------------------------------------------------------------------------
# BenchTask 声明式 schema（Pydantic 严格契约；extra=forbid 抓拼写漂移）
# ---------------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BenchCriterion(_Strict):
    """单条判据声明（枚举名 + 预声明阈值；阈值语义随判据极性，见各判据函数 docstring）。"""

    name: str = Field(min_length=1)
    #: 预声明阈值（#122）：closedform_match/erc_clean/drc_count/token_cost/
    #: fd_convergence/three_way_consistency=上界（value ≤ threshold 判 pass；
    #: three_way 的 threshold=外包络上限，内界 1.5%/2% 由 runner 从预声明
    #: 常量注入 measure）；success_rate=下界（value ≥ threshold）；
    #: gate_pass/certificate_pass 布尔判据可缺省（None）。
    threshold: float | None = None

    @field_validator("name")
    @classmethod
    def _name_in_enum(cls, v: str) -> str:
        if v not in CRITERIA_NAMES:
            raise ValueError(
                f"判据名 {v!r} 不在枚举闭集 {list(CRITERIA_NAMES)}（新判据走 register_criterion 尾部追加）")
        return v


class EnvelopeBound(_Strict):
    """单参数训练包络界（B3：参数域 bounds；至少声明一界，min ≤ max）。

    数值必须是有限 float（inf/nan/bool 拒收——#364 判据布尔化纪律同族）；
    min/max 单边 None=该侧不设界（开放半域合法）。
    """

    min: float | None = None
    max: float | None = None

    @field_validator("min", "max", mode="before")
    @classmethod
    def _finite_bound(cls, v: Any) -> Any:
        """mode="before"：pydantic 会把 bool 静默强转 float（True→1.0）——
        bool 拒收必须在强转前看原始输入（#364 判据布尔化纪律）。"""
        if v is None:
            return None
        if isinstance(v, bool):
            raise ValueError(f"包络界必须为数值（bool 拒收——#364），得到 {v!r}")
        f = float(v)
        if not math.isfinite(f):
            raise ValueError(f"包络界必须为有限数值（inf/nan 拒收），得到 {v!r}")
        return f


class BenchGraderNotes(_Strict):
    """grader_notes/rubric 结构（AX-1①：razavi-bench golden 内嵌 rubric 思想，
    思想级重写零搬运）——判据条目的**纯数据附注**，报告面透出，零 LLM 打分。

    - ``correct_core``：正确核列表（什么算对——判读锚的题面层陈述）；
    - ``common_errors``：常见错答列表（为何错——失败分类表的人类可读面）；
    - ``partial_credit``：部分分规则描述（纯文本——与 spec_score 列的
      确定性口径互为说明，本字段不参与任何判定）。
    """

    correct_core: list[str] = Field(default_factory=list)
    common_errors: list[str] = Field(default_factory=list)
    partial_credit: str = ""


class BenchNegativeVariant(_Strict):
    """反例输入变体（AX-1④：vaBench negative_variants 思想，思想级重写）。

    - ``variant_id``：反例锚（检查报告/审计键，任务内唯一由调用方保证）；
    - ``input_spec``：反例输入载荷（与任务 input_spec 同构——替换后走
      全管线，判据必须对其判 fail；执行崩溃的 fail 不算"判据判 fail"）；
    - ``note``：反例说明（它代表哪类投机解/错误答）。
    """

    variant_id: str = Field(min_length=1)
    input_spec: dict[str, Any] = Field(default_factory=dict)
    note: str = ""


class BenchTask(_Strict):
    """基准任务声明式 schema（骨架三件之一：task 集）。

    - ``task_id``：任务锚（得分卡/证据文件名键，须唯一）；
    - ``family``：runner 分派键（BENCH_FAMILIES 闭集语义，运行时按注册表
      查找——未知 family 在 run_bench_task 入口 fail-closed）；
    - ``input_spec``：family 专属声明式输入（综合参数/需求原文/SchSpec/
      检索语料与查询集——全数据，零数值预言）；
    - ``criteria``：判据列表（枚举名+预声明阈值；≥1 条）——**visible 公开层**；
    - ``hidden_criteria``：隐藏判据层（AX-1③可选；与 criteria 同名互斥，
      判定时两层都算，报告只出汇总不出细节）；
    - ``negative_variants``：反例输入集（AX-1④可选；判据必须判 fail，
      :func:`check_negative_variants` 行为自检）；
    - ``grader_notes``：rubric 结构附注（AX-1①可选；纯数据+报告面透出）；
    - ``envelope``：训练包络声明（B3 可选；参数域 bounds，评估点越界
      ood_flag=true 不改 verdict）；
    - ``data_source``：数据源口径说明（provenance——判据真值出自哪个
      确定性内核/回归锚，供得分卡审计）。
    """

    task_id: str = Field(min_length=1)
    family: str = Field(min_length=1)
    title: str = ""
    input_spec: dict[str, Any] = Field(default_factory=dict)
    criteria: list[BenchCriterion] = Field(min_length=1)
    hidden_criteria: list[BenchCriterion] = Field(default_factory=list)
    negative_variants: list[BenchNegativeVariant] = Field(default_factory=list)
    grader_notes: BenchGraderNotes | None = None
    envelope: dict[str, EnvelopeBound] | None = None
    data_source: str = ""

    @model_validator(mode="after")
    def _layer_and_envelope_checks(self) -> BenchTask:
        """跨层互斥+包络域检（fail-closed 在 schema 面——AX-1③/B3 结构纪律）。

        - visible/hidden 判据名跨层重复=分层语义破坏（同名判据两层判定
          会双计且报告面归属不明）→ 拒收；
        - envelope 每键至少一界（min/max 全缺=空界不可判读）且 min ≤ max
          （声明即契约——反向界=定义错误）。
        """
        visible_names = [c.name for c in self.criteria]
        hidden_names = [c.name for c in self.hidden_criteria]
        overlap = sorted(set(visible_names) & set(hidden_names))
        if overlap:
            raise ValueError(
                f"判据名跨层重复 {overlap}（visible/hidden 分层必须互斥——"
                "同名判据两层判定双计且报告归属不明）")
        if self.envelope is not None:
            for key, bound in self.envelope.items():
                if not str(key).strip():
                    raise ValueError(f"envelope 键不得为空白，得到 {key!r}")
                if bound.min is None and bound.max is None:
                    raise ValueError(
                        f"envelope[{key!r}] min/max 全缺（至少声明一界——空界"
                        "不可判读，如实拒绝不猜）")
                if (bound.min is not None and bound.max is not None
                        and bound.min > bound.max):
                    raise ValueError(
                        f"envelope[{key!r}] min={bound.min!r} > max={bound.max!r}"
                        "（反向界=定义错误）")
        return self


@dataclass
class BenchRunContext:
    """单任务运行上下文（路径全部绝对化后注入；零缺省写面）。"""

    #: 证据落盘目录（None=拒写——只返回结果不落证据文件）。
    evidence_dir: Path | None = None
    #: cwd 隔离根（runner 全程在此目录下执行；一次性产物/湖/索引全落此树）。
    work_root: Path | None = None


# ---------------------------------------------------------------------------
# 判据函数注册表（每判据=确定性函数；数值只比较不产生——铁律 7）
# ---------------------------------------------------------------------------

CriterionFn = Callable[[Mapping[str, Any], float | None], dict[str, Any]]

_CRITERION_REGISTRY: dict[str, CriterionFn] = {}
_RUNNER_REGISTRY: dict[str, Callable[[BenchTask, BenchRunContext], dict[str, Any]]] = {}


def register_criterion(name: str) -> Callable[[CriterionFn], CriterionFn]:
    """判据函数注册装饰器（闭集防重复覆盖；name 须在 CRITERIA_NAMES）。"""

    def deco(fn: CriterionFn) -> CriterionFn:
        if name not in CRITERIA_NAMES:
            raise ValueError(f"判据名 {name!r} 不在枚举闭集 {list(CRITERIA_NAMES)}（先扩枚举再注册）")
        if name in _CRITERION_REGISTRY:
            raise ValueError(f"判据 {name!r} 已注册（注册表闭集禁止重复覆盖）")
        _CRITERION_REGISTRY[name] = fn
        return fn

    return deco


def criterion_fn(name: str) -> CriterionFn | None:
    """判据名 → 判据函数（未注册返回 None，不抛）。"""
    return _CRITERION_REGISTRY.get(name)


def registered_criteria() -> tuple[str, ...]:
    """已注册判据名（注册序）。"""
    return tuple(_CRITERION_REGISTRY)


def register_runner(
    family: str,
) -> Callable[[Callable[[BenchTask, BenchRunContext], dict[str, Any]]],
              Callable[[BenchTask, BenchRunContext], dict[str, Any]]]:
    """任务 runner 注册装饰器（family 键防重复覆盖）。"""

    def deco(fn: Callable[[BenchTask, BenchRunContext], dict[str, Any]]):
        if family in _RUNNER_REGISTRY:
            raise ValueError(f"family {family!r} 已注册 runner（注册表闭集禁止重复覆盖）")
        _RUNNER_REGISTRY[family] = fn
        return fn

    return deco


def registered_families() -> tuple[str, ...]:
    """已注册 runner family（注册序）。"""
    return tuple(_RUNNER_REGISTRY)


def _outcome(
    value: float | None,
    verdict: str,
    threshold: float | None,
    note: str | None = None,
) -> dict[str, Any]:
    """判据评定单条结果（JSON 安全固定四键；verdict ∈ VERDICTS）。"""
    if verdict not in VERDICTS:
        raise ValueError(f"verdict={verdict!r} 不在词表 {list(VERDICTS)}")
    return {"value": value, "verdict": verdict, "threshold": threshold, "note": note}


def _finite_number(v: Any) -> float | None:
    """数值收敛（拒 bool/非数值/非有限；#364 判据布尔化纪律）。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


@register_criterion("closedform_match")
def _criterion_closedform_match(measure: Mapping[str, Any],
                                threshold: float | None) -> dict[str, Any]:
    """闭式对照判据（上界极性：deviation ≤ threshold 判 pass）。

    measure = ``{"deviation": float}``——相对偏差 |实测−闭式真值|/|闭式真值|，
    由 runner 从确定性内核输出计算（本函数只比较、不产生数字，铁律 7）。
    阈值语义：相对偏差上限，任务声明时预声明（缺阈值=定义错误，入口拦截）。
    测度缺失/非法 → unknown（不凑分）；deviation 恰等于阈值判 pass（≤）。
    """
    dev = _finite_number(measure.get("deviation"))
    if dev is None or threshold is None:
        return _outcome(None, "unknown", threshold,
                        note=None if dev is not None else "deviation 测度缺失/非法")
    return _outcome(dev, "pass" if dev <= float(threshold) else "fail", threshold)


@register_criterion("gate_pass")
def _criterion_gate_pass(measure: Mapping[str, Any],
                         threshold: float | None) -> dict[str, Any]:
    """质量门判读判据（布尔极性；阈值不消费，None 合法）。

    measure = ``{"passed": bool, "gate": str, "metric": float|None}``——
    passed 由 runner 按预声明门条件从内核输出判读（如闭环 check 阶段
    verdicts 全过/campaign 质量杆）；value 记 metric（None 时以 1.0/0.0
    记布尔），verdict 只认 passed。测度缺失/非法 → unknown。
    """
    passed = measure.get("passed")
    if not isinstance(passed, bool):
        return _outcome(None, "unknown", threshold, note="passed 测度缺失/非法")
    metric = _finite_number(measure.get("metric"))
    value = metric if metric is not None else (1.0 if passed else 0.0)
    return _outcome(value, "pass" if passed else "fail", threshold)


@register_criterion("certificate_pass")
def _criterion_certificate_pass(measure: Mapping[str, Any],
                                threshold: float | None) -> dict[str, Any]:
    """round-trip 二值证书判据（布尔极性；T-Q24 网表等价/round-trip 口径）。

    measure = ``{"passed": bool, "n_diff": int|None}``——passed 出自通用件
    :func:`rfauto.service.roundtrip_certificate.is_pass`（确定性 fold，
    同输入证书逐字节同）；value = 1.0/0.0（n_diff 记 note 供审计）。
    测度缺失/非法 → unknown。
    """
    passed = measure.get("passed")
    if not isinstance(passed, bool):
        return _outcome(None, "unknown", threshold, note="passed 测度缺失/非法")
    n_diff = measure.get("n_diff")
    note = (f"n_diff={n_diff}" if isinstance(n_diff, int) and not isinstance(n_diff, bool)
            else None)
    return _outcome(1.0 if passed else 0.0, "pass" if passed else "fail", threshold,
                    note=note)


def _count_bound_criterion(measure: Mapping[str, Any], threshold: float | None,
                           *, count_key: str, label: str) -> dict[str, Any]:
    """计数/成本上界判据共用体（erc_clean/drc_count/token_cost）。

    available=False（通道缺席/无账本）→ unknown（如实不凑分）；count/cost
    收非负有限数（计数 int、成本 float——token_cost 复用本体）；恰等阈值判
    pass（≤ 上界极性）。
    """
    if not measure.get("available"):
        reason = str(measure.get("reason") or f"{label}通道不可用")
        return _outcome(None, "unknown", threshold, note=reason)
    count = _finite_number(measure.get(count_key))
    if count is None or count < 0:
        return _outcome(None, "unknown", threshold, note=f"{count_key} 测度缺失/非法")
    if threshold is None:
        return _outcome(None, "unknown", threshold, note="阈值未声明")
    return _outcome(count, "pass" if count <= float(threshold) else "fail",
                    threshold)


@register_criterion("erc_clean")
def _criterion_erc_clean(measure: Mapping[str, Any],
                         threshold: float | None) -> dict[str, Any]:
    """ERC 违例判据（上界极性：error_count ≤ threshold；T-Q24 ERC 分级口径）。

    measure = ``{"available": bool, "error_count": int|None, "reason": str?}``。
    kicad-cli 缺席（skipped 信封）或通道故障 → available=False → **unknown**
    （如实不凑分——工具缺席不是设计缺陷也不是通过）；count 恰等于阈值判
    pass（≤；零违例口径 threshold=0）。
    """
    return _count_bound_criterion(measure, threshold, count_key="error_count", label="ERC")


@register_criterion("drc_count")
def _criterion_drc_count(measure: Mapping[str, Any],
                         threshold: float | None) -> dict[str, Any]:
    """DRC 违例计数判据（上界极性：count ≤ threshold；T-Q24 DRC 口径）。

    measure = ``{"available": bool, "count": int|None, "reason": str?}``。
    首批 6 任务不消费（PCB/布局面 runner 后续席位接入）；注册表在位=
    判据池完整，负例测度缺失 → unknown。
    """
    return _count_bound_criterion(measure, threshold, count_key="count", label="DRC")


@register_criterion("success_rate")
def _criterion_success_rate(measure: Mapping[str, Any],
                            threshold: float | None) -> dict[str, Any]:
    """成功率判据（下界极性：rate ≥ threshold；T-Q24 有效电路率/编译通过率口径）。

    measure = ``{"n_ok": int, "n_total": int}``；分母 0 → unknown（如实缺席，
    不虚构 0 也不虚构 1）；rate 恰等于阈值判 pass（≥）。
    """
    n_ok = measure.get("n_ok")
    n_total = measure.get("n_total")
    ints = [v for v in (n_ok, n_total)]
    if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in ints):
        return _outcome(None, "unknown", threshold, note="n_ok/n_total 测度缺失/非法")
    n_ok_i, n_total_i = int(n_ok), int(n_total)
    if n_total_i <= 0:
        return _outcome(None, "unknown", threshold, note="分母 n_total=0——如实 unknown")
    if threshold is None:
        return _outcome(None, "unknown", threshold, note="阈值未声明")
    rate = n_ok_i / n_total_i
    return _outcome(rate, "pass" if rate >= float(threshold) else "fail", threshold)


@register_criterion("token_cost")
def _criterion_token_cost(measure: Mapping[str, Any],
                          threshold: float | None) -> dict[str, Any]:
    """Token 成本判据（上界极性：cost ≤ threshold；T-Q24 Token ROI 成本上限口径）。

    measure = ``{"available": bool, "cost": float|None, "reason": str?}``。
    无计费账本 → available=False → **unknown**（骨架期恒此态——成本轴缺
    数据不编数，铁律 7 同族：统计口径的缺失就是缺失，不冒充实测；
    LLM 提案器跑分批接线计费账本后由 runner 产出 available=True 测度）。
    """
    return _count_bound_criterion(measure, threshold, count_key="cost", label="Token 成本")


@register_criterion("fsv_grade")
def _criterion_fsv_grade(measure: Mapping[str, Any],
                         threshold: float | None) -> dict[str, Any]:
    """FSV GDM 等级判据（上界极性：grade_level ≤ threshold 判 pass；Q-X15）。

    measure = ``{"grade_level": int, "grade": str}``——FSV GDM 等级下标与
    名字（IEEE 1597.1 口径，core/fsv 确定性内核产出；等级下标越小越好：
    Ex=0/ VG=1/…族内递增）。阈值语义：等级下标上限，任务声明时预声明
    （afs-fsv-quality 预声明 2=VG 档，锚=tests/unit/test_afs_service.py
    numpy 2.5.4 口径 gdm_grade_level ≤ 2——原 ≤1 为 numpy 2.4.x 口径，
    aurora_q 终门实证定谳）。测度缺失/非法（含 bool，#364）→ unknown
    不凑分；恰等阈值判 pass（≤）；grade 名进 note 供审计。
    """
    level = measure.get("grade_level")
    if isinstance(level, bool) or not isinstance(level, int):
        return _outcome(None, "unknown", threshold, note="grade_level 测度缺失/非法")
    if threshold is None:
        return _outcome(None, "unknown", threshold, note="阈值未声明")
    grade = measure.get("grade")
    note = str(grade) if isinstance(grade, str) and grade else None
    return _outcome(float(level), "pass" if level <= float(threshold) else "fail",
                    threshold, note=note)


@register_criterion("fd_convergence")
def _criterion_fd_convergence(measure: Mapping[str, Any],
                              threshold: float | None) -> dict[str, Any]:
    """FD 收敛残差判据（上界极性：residual_max ≤ threshold 判 pass；Q-X22）。

    measure = ``{"residual_max": float, "status": str}``——residual_max=
    FD 收敛阶梯四项 Richardson 残差（εeff/C_air × finest-vs-外推/相邻外推
    互差）的最大值，由 runner 从 core/suspended_stripline_fd_judge 内核
    LadderResult 直读（本函数只比较、不产生数字，铁律 7）；status 随行记
    note 供审计（不进主判——8 门全量判读走 gate_pass 判据）。阈值语义：
    Richardson 残差上限，任务声明时预声明（ssl_anchor 任务=内核
    LADDER_RESIDUAL_MAX=1e-3 单源直引，缺阈值=定义错误入口拦截）。
    测度缺失/非法（含 bool，#364）→ unknown 不凑分；恰等阈值判 pass（≤）。
    """
    residual = _finite_number(measure.get("residual_max"))
    if residual is None:
        return _outcome(None, "unknown", threshold,
                        note="residual_max 测度缺失/非法")
    if threshold is None:
        return _outcome(None, "unknown", threshold, note="阈值未声明")
    status = measure.get("status")
    note = str(status) if isinstance(status, str) and status else None
    return _outcome(residual, "pass" if residual <= float(threshold) else "fail",
                    threshold, note=note)


@register_criterion("three_way_consistency")
def _criterion_three_way_consistency(measure: Mapping[str, Any],
                                     threshold: float | None) -> dict[str, Any]:
    """三方一致性判据（双界上界极性；Q-X22 跨引擎三方 FD+闭式+HFSS implied）。

    measure = ``{"fd_vs_closed": float, "fd_vs_hfss": float,
    "bound_closed": float, "bound_hfss": float}``——两条**带符号**相对偏差
    （FD 为基准：closed/FD−1、hfss/FD−1，Q-X20 judge_result.bias_rel 同
    口径）与两条预声明界（runner 从模块常量注入——界是预声明锚，非阈值
    逃逸通道）。阈值语义：外包络上限 max(|fd_vs_closed|,|fd_vs_hfss|) ≤
    threshold（任务声明时预声明；缺阈值=定义错误入口拦截）。
    pass 当且仅当 |fd_vs_closed| ≤ bound_closed 且 |fd_vs_hfss| ≤ bound_hfss
    且外包络成立；value=最坏偏差（带宽读数）；带符号对进 note 供审计
    （"fd_vs_closed 带宽"口径）。测度缺失/非法（含 bool，#364）→ unknown
    不凑分。
    """
    dev_closed = _finite_number(measure.get("fd_vs_closed"))
    dev_hfss = _finite_number(measure.get("fd_vs_hfss"))
    bound_closed = _finite_number(measure.get("bound_closed"))
    bound_hfss = _finite_number(measure.get("bound_hfss"))
    keys = ("fd_vs_closed", "fd_vs_hfss", "bound_closed", "bound_hfss")
    missing = [k for k, v in zip(keys, (dev_closed, dev_hfss, bound_closed,
                                        bound_hfss), strict=True) if v is None]
    if missing:
        return _outcome(None, "unknown", threshold,
                        note=f"测度缺失/非法: {missing}")
    if threshold is None:
        return _outcome(None, "unknown", threshold, note="阈值未声明")
    a_closed, a_hfss = abs(dev_closed), abs(dev_hfss)
    worst = max(a_closed, a_hfss)
    passed = (a_closed <= bound_closed and a_hfss <= bound_hfss
              and worst <= float(threshold))
    note = (f"fd_vs_closed={dev_closed:+.6f} (bound {bound_closed}); "
            f"fd_vs_hfss={dev_hfss:+.6f} (bound {bound_hfss})")
    return _outcome(worst, "pass" if passed else "fail", threshold, note=note)


# ---------------------------------------------------------------------------
# 任务 runner 注册表（每 family=既有 service 真函数确定性执行；零 stub 数值）
# ---------------------------------------------------------------------------


@register_runner("synthesis")
def _run_synthesis(task: BenchTask, ctx: BenchRunContext) -> dict[str, Any]:
    """综合任务 runner（syn-mline/syn-cpw/layered-stack-synthesis）：
    core.synthesis 闭式内核综合 → 独立正向回代 → closedform_match 测度。

    input_spec = ``{"kind": "mline"|"cpw"|"layered_stack", "params": {...}}``
    （params 透传综合内核关键字参数）。closedform_match 测度=回代相对偏差
    |z0_actual−z0_target|/|z0_target|：mline 经 forward_z0（skrf HJ 正向），
    cpw 经 core.calculators._cpwg_ri（共形映射闭式）——与综合内核同源的
    回代自洽口径（仓库惯例：ΔZ0 判据，SynthesisResult.delta_z0 同语义；
    四舍五入到 4 位小数的线宽回代含真实舍入偏差——回归门应有的敏感度）。
    kind="layered_stack"（Q-X15，模板 76 族新成员接入 bench）：消费
    adapters/layered_stack_spec.design_params（Z0 目标→strip 宽二分反解
    +独立裁判 |ΔZ0|≤1e-9Ω=#118 家法，铁律 7 确定性内核数值零手拍）——
    bench 层 closedform_match 为锚漂移回归门（#207 口径，非物理基准：
    design_params 内建独立裁判已保证残差，锚漂移=回归门敏感度）。
    未知 kind → ValueError（fail-closed）。
    """
    del ctx  # 综合内核零文件产物；ctx 仅保持 runner 签名统一
    spec = task.input_spec or {}
    kind = str(spec.get("kind") or "")
    params = dict(spec.get("params") or {})
    from rfauto.core.calculators import _cpwg_ri
    from rfauto.core.synthesis import (
        Stackup,
        forward_z0,
        synthesize_cpw_model,
        synthesize_mline_model,
    )

    if kind == "mline":
        res = synthesize_mline_model(**params)
        stackup_name = (str(params["stackup_name"]) if "stackup_name" in params
                        else "rogers4350b_h0.508")
        stackup = Stackup.from_materials_yaml(stackup_name)
        w_mm = float(res.params["w_mm"])
        freq = float(res.goal["freq_ghz"])
        target = float(res.goal["z0_ohm"])
        z0_actual = float(forward_z0(w_mm, freq, stackup)[0])
    elif kind == "cpw":
        res = synthesize_cpw_model(**params)
        gap_mm = float(res.params["gap_mm"])
        h_mm = float(params["h_mm"]) if "h_mm" in params else 0.508
        er = float(params["er"]) if "er" in params else 3.66
        w_mm = float(res.params["w_mm"])
        target = float(res.goal["z0_ohm"])
        z0_actual = float(_cpwg_ri(w_mm, gap_mm, h_mm, er)[1])
    elif kind == "layered_stack":
        z0_decl = params.get("z0_ohm")
        z0_num = _finite_number(z0_decl)
        if z0_num is None or z0_num <= 0:
            raise ValueError(
                f"layered_stack 任务 params.z0_ohm 必填且为正有限数值，得到 {z0_decl!r}")
        from rfauto.adapters.layered_stack_spec import design_params

        dp = design_params(z0_target_ohm=float(z0_num))
        target = float(dp["z0_target_ohm"])
        z0_actual = float(dp["z0_achieved_ohm"])
        deviation = abs(z0_actual - target) / abs(target)
        return {
            "measures": {"closedform_match": {"deviation": deviation}},
            "detail": {"kind": kind, "model": "layered_stack",
                       "params": dict(dp["params"]),
                       "z0_target": target,
                       "z0_actual": z0_actual,
                       "deviation": deviation,
                       "notes": [str(dp["source"])],
                       "z0_residual_ohm": float(dp["z0_residual_ohm"]),
                       "eps_eff": float(dp["eps_eff"]),
                       "anchor_hfss": dict(dp["anchor_hfss"])},
        }
    else:
        raise ValueError(f"synthesis kind={kind!r} 不在 {{'mline','cpw'}}（任务定义错误）")
    deviation = abs(z0_actual - target) / abs(target)
    return {
        "measures": {"closedform_match": {"deviation": deviation}},
        "detail": {"kind": kind, "model": res.model, "params": dict(res.params),
                   "z0_target": target, "z0_actual": round(z0_actual, 4),
                   "deviation": round(deviation, 8), "notes": list(res.notes)},
    }


@register_runner("campaign")
def _run_campaign(task: BenchTask, ctx: BenchRunContext) -> dict[str, Any]:
    """优化战役 runner（wilkinson-campaign）：level2_design.design_chain
    七环节 + 第 8 环代理寻优发起（run_surrogate_loop，fake 采样器/固定
    seed，离线确定性）→ closedform_match + gate_pass 测度。

    input_spec = ``{"prompt": "<NL 需求>"}``（族路由走 level2 关键词路由）。
    closedform_match 测度=|s21_db_at_dip − (−3.0103dB)|/3.0103——理想 3dB
    等分闭式（10·log10(0.5)，docs/rf_template_references Wilkinson 验收
    口径），非回代自洽、非同义反复（#118 纪律）。gate_pass 测度=战役门：
    kickoff_status == "completed"（寻优真实完成出最优点）且
    s11_db_min_in_band ≤ gate_pass 阈值（任务预声明质量杆；阈值缺失 →
    ValueError fail-closed）。fake 闭式模型回归锚口径（#207：锚漂移=
    回归门应有的敏感度，非物理基准）。
    """
    del ctx
    spec = task.input_spec or {}
    prompt = str(spec.get("prompt") or "")
    if not prompt.strip():
        raise ValueError("campaign 任务 input_spec.prompt 必填（NL 需求原文）")
    s11_limit = _criterion_threshold(task, "gate_pass")
    if s11_limit is None:
        raise ValueError("campaign gate_pass 阈值未预声明（s11_db_min_in_band 质量杆上限）")
    from rfauto.service.level2_design import design_chain

    record = design_chain({"id": task.task_id, "prompt": prompt}, None,
                          enable_optimize=True)
    if record.get("error"):
        raise RuntimeError(f"design_chain 执行失败: {record['error']}")
    numeric = dict(record.get("numeric") or {})
    metrics = dict(record.get("metrics") or {})
    s21_dip = _finite_number(numeric.get("s21_db_at_dip"))
    if s21_dip is None:
        raise RuntimeError(f"campaign 判据输入缺失: s21_db_at_dip（numeric={numeric}）")
    ideal_split_db = 10.0 * math.log10(0.5)  # −3.0103dB 理想等分（闭式）
    deviation = abs(s21_dip - ideal_split_db) / abs(ideal_split_db)
    s11_min = _finite_number(metrics.get("s11_db_min_in_band"))
    kickoff_status = str(record.get("kickoff_status") or "")
    if s11_min is None:
        raise RuntimeError(f"campaign 判据输入缺失: s11_db_min_in_band（metrics={metrics}）")
    gate_passed = (kickoff_status == "completed") and (s11_min <= float(s11_limit))
    return {
        "measures": {
            "closedform_match": {"deviation": deviation},
            "gate_pass": {"passed": gate_passed,
                          # Q-X55：门名随路由族（wilkinson-campaign 输出
                          # "wilkinson_campaign_gate" 逐字节不变——既有钉兼容；
                          # branchline-campaign → "branchline_campaign_gate"）。
                          "gate": f"{record.get('family')}_campaign_gate",
                          "metric": s11_min},
        },
        "detail": {"family": record.get("family"), "kickoff_status": kickoff_status,
                   "n_real_used": record.get("kickoff", {}).get("n_real_used"),
                   "prompt": prompt,
                   "synthesis_params": dict(record.get("synthesis_params") or {}),
                   "numeric": {k: round(float(v), 6) for k, v in numeric.items()},
                   "ideal_split_db": round(ideal_split_db, 6),
                   "s11_limit": float(s11_limit)},
    }


@register_runner("kicad_sch")
def _run_kicad_sch(task: BenchTask, ctx: BenchRunContext) -> dict[str, Any]:
    """KiCad 原理图 round-trip runner（kicad-sch-roundtrip）：
    kicad_sch_service.generate_schematic → round_trip_certificate（Q-CAD-2
    通用件跨域复用）→ certificate_pass 测度；可选 kicad-cli ERC →
    erc_clean 测度（T-Q24 ERC 分级口径）。

    input_spec = ``{"spec": {schema, components, nets}, "run_erc": bool}``。
    证书 PASS 是「生成正确」的确定性判据（Weave 思想二值证书）；ERC 通道
    缺席（kicad-cli 未装 → skipped 信封）→ erc_clean 测度 available=False
    → 判据 unknown（显式不凑分——默认任务 therefore 在无 KiCad 环境下
    verdict=unknown，属设计行为而非回归）。
    """
    spec_in = task.input_spec or {}
    spec = dict(spec_in.get("spec") or {})
    if not spec:
        raise ValueError("kicad_sch 任务 input_spec.spec 必填（SchSpec 载荷）")
    from rfauto.service import kicad_sch_service

    spec.setdefault("schema", kicad_sch_service.SCH_SPEC_SCHEMA)
    work = ctx.work_root or Path(tempfile.mkdtemp(prefix="rfauto_embench_kicad_"))
    out_path = work / f"{task.task_id}.kicad_sch"
    env = kicad_sch_service.generate_schematic(spec, out_path)
    if not env.get("ok"):
        raise RuntimeError(f"generate_schematic 失败: {env.get('errors')}")
    cert = dict(env.get("certificate") or {})
    n_diff = len(cert.get("diff") or [])
    measures: dict[str, Any] = {
        "certificate_pass": {"passed": bool(cert.get("pass")), "n_diff": n_diff}}
    detail: dict[str, Any] = {
        "out_path": str(out_path), "bytes": env.get("bytes"),
        "n_components": env.get("n_components"), "n_nets": env.get("n_nets"),
        "certificate_pass": bool(cert.get("pass")), "n_diff": n_diff,
        "unnamed_pins": cert.get("unnamed_pins")}
    if bool(spec_in.get("run_erc", True)):
        erc_env = kicad_sch_service.run_erc(out_path)
        detail["erc_exit_code"] = erc_env.get("exit_code")
        if erc_env.get("skipped"):
            measures["erc_clean"] = {"available": False,
                                     "reason": str(erc_env.get("reason") or "ERC 通道跳过")}
        elif not erc_env.get("ok"):
            measures["erc_clean"] = {
                "available": False,
                "reason": "; ".join(str(e) for e in (erc_env.get("errors") or ["ERC 通道故障"]))}
        else:
            measures["erc_clean"] = {"available": True,
                                     "error_count": erc_env.get("error_count")}
    return {"measures": measures, "detail": detail}


@register_runner("vendor_search")
def _run_vendor_search(task: BenchTask, ctx: BenchRunContext) -> dict[str, Any]:
    """厂商文档检索 runner（vendor-search）：vendor_doc_service 索引构建
    （内联语料物化 → SQLite FTS5）→ 逐查询带引用检索 → success_rate 测度。

    input_spec = ``{"corpus": {文件名: HTML 文本}, "queries": [{query,
    expect: [必现词...]}], "limit": int}``。命中语义（预声明）：top-k 结果
    的 title/path/snippet 拼串（小写化）包含**全部** expect 词 → 该查询
    hit。success_rate 测度 = n_ok/n_total（下界极性判据消费）。红线继承：
    厂商内容零入库（库内只存 ≤chunk_chars 摘要块）；索引库落 work_root
    （调用方显式树，非缺省位置——#144 同款）。
    """
    spec = task.input_spec or {}
    corpus = dict(spec.get("corpus") or {})
    queries = list(spec.get("queries") or [])
    if not corpus or not queries:
        raise ValueError("vendor_search 任务 input_spec.corpus 与 queries 必填")
    from rfauto.service import vendor_doc_service as vds

    work = ctx.work_root or Path(tempfile.mkdtemp(prefix="rfauto_embench_vendor_"))
    corpus_dir = work / f"vendor_corpus_{task.task_id}"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    for fname, text in corpus.items():
        safe = Path(str(fname)).name  # 防路径逃逸（语料键只当文件名消费）
        (corpus_dir / safe).write_text(str(text), encoding="utf-8")
    db_path = work / f"vendor_index_{task.task_id}.db"
    source = str(spec.get("source_name") or "bench_docs")
    idx = vds.build_vendor_index({source: corpus_dir}, db_path=db_path)
    if not idx.get("ok"):
        raise RuntimeError(f"vendor 索引构建失败: {idx.get('errors')}")
    limit = int(spec.get("limit") or 5)
    n_ok = 0
    per_query: list[dict[str, Any]] = []
    for q in queries:
        query = str(q.get("query") or "")
        expects = [str(t).lower() for t in (q.get("expect") or []) if str(t).strip()]
        res = vds.search_vendor_docs(query, db_path=db_path, limit=limit)
        blob_parts: list[str] = []
        if res.get("ok"):
            for hit in res.get("hits") or []:
                if isinstance(hit, Mapping):
                    blob_parts.append(" ".join(
                        str(hit.get(k) or "") for k in ("title", "path", "snippet")))
        blob = "\n".join(blob_parts).lower()
        hit_terms = [t for t in expects if t in blob]
        ok = bool(expects) and len(hit_terms) == len(expects)
        n_ok += 1 if ok else 0
        per_query.append({"query": query, "expect": expects, "hit": ok,
                          "hit_terms": hit_terms, "mode": res.get("mode"),
                          "n_hits": len(res.get("hits") or [])})
    return {
        "measures": {"success_rate": {"n_ok": n_ok, "n_total": len(queries)}},
        "detail": {"queries": per_query, "db_path": str(db_path),
                   "indexed_files": idx.get("indexed_files"),
                   "total_chunks": idx.get("total_chunks")},
    }


@register_runner("afs_sweep")
def _run_afs_sweep(task: BenchTask, ctx: BenchRunContext) -> dict[str, Any]:
    """AFS 自适应频扫 runner（afs-fsv-quality，Q-X15）：afs_service 真函数链
    synthetic_multiresonance_response（确定性合成多谐振解析响应）×
    afs_sweep（回调注入 SV-5 六步伪误差自适应频扫，Loewner 双阶核）→
    fsv_grade + success_rate 测度。

    input_spec = ``{"spec": "<谐振规格>", "band_ghz": [fmin, fmax],
    "tol": float}``（缺省=任务预声明锚 _AFS_SPEC_DEFAULT/_AFS_BAND_GHZ_DEFAULT
    ——与 tests/unit/test_afs_service.py 同款锚：2.4/3.1GHz 双陷波+2% 纹波、
    1-4GHz 频带；零真机零随机，铁律 7：FSV 等级/缩减比全出 core/afs+core/fsv
    确定性内核）。fsv_grade 测度=vs_full.fsv 直读（gdm_grade_level/grade）；
    success_rate 测度=缩减子判据成立性（n_ok/n_total=1/1 或 0/1：
    reduction_ratio ≥ afs_service.REDUCTION_RATIO_MIN(0.5，§10.20 补强⑩)，
    比值本体进 detail 供审计——判据只消费预声明子判据的成立性，不虚构
    分子分母语义）。ok=False 信封/判据输入缺失 → RuntimeError（执行失败
    如实 fail）；AFS 未收敛是合法结果（status/converged 如实进 detail，
    判据仍按 vs_full 评定——afs_service 信封契约同款）。
    """
    del ctx
    spec = task.input_spec or {}
    spec_text = str(spec.get("spec") or _AFS_SPEC_DEFAULT)
    band_ghz = spec.get("band_ghz") or list(_AFS_BAND_GHZ_DEFAULT)
    band_ghz = [float(band_ghz[0]), float(band_ghz[1])]
    band_hz = [band_ghz[0] * 1e9, band_ghz[1] * 1e9]
    tol = spec.get("tol")
    import numpy as np

    from rfauto.service.afs_service import (
        REDUCTION_RATIO_MIN,
        afs_sweep,
        synthetic_multiresonance_response,
    )

    response, syn_spec = synthetic_multiresonance_response(spec_text, *band_hz)

    def _evaluate(f_hz: float) -> dict[str, Any]:
        return {"s": complex(response(np.asarray([float(f_hz)]))[0])}

    env = afs_sweep(_evaluate, band_hz, tol, 12, full_response=response)
    if not env.get("ok"):
        raise RuntimeError(f"afs_sweep 执行失败: {env.get('error')}")
    summary = dict(env.get("result") or {})
    vs = summary.get("vs_full")
    if not isinstance(vs, Mapping) or not isinstance(vs.get("fsv"), Mapping):
        raise RuntimeError(f"afs 判据输入缺失: vs_full（full_response 未生效）, result={summary}")
    fsv = dict(vs["fsv"])
    grade_level = fsv.get("gdm_grade_level")
    if isinstance(grade_level, bool) or not isinstance(grade_level, int):
        raise RuntimeError(f"afs 判据输入缺失: gdm_grade_level（fsv={fsv}）")
    grade = str(fsv.get("gdm_grade") or "")
    reduction = _finite_number(vs.get("reduction_ratio"))
    if reduction is None:
        raise RuntimeError(f"afs 判据输入缺失: reduction_ratio（vs_full={dict(vs)}）")
    reduction_ok = reduction >= REDUCTION_RATIO_MIN
    return {
        "measures": {
            "fsv_grade": {"grade_level": grade_level, "grade": grade},
            "success_rate": {"n_ok": 1 if reduction_ok else 0, "n_total": 1},
        },
        "detail": {"spec": syn_spec, "band_ghz": band_ghz,
                   "algorithm": summary.get("algorithm"),
                   "status": summary.get("status"),
                   "converged": summary.get("converged"),
                   "n_solves": summary.get("n_solves"),
                   "n_full": vs.get("n_full"),
                   "reduction_ratio": reduction,
                   "reduction_ratio_min": REDUCTION_RATIO_MIN,
                   "gdm_grade": grade, "gdm_grade_level": grade_level,
                   "acceptance": summary.get("acceptance")},
    }


@register_runner("ssl_anchor")
def _run_ssl_anchor(task: BenchTask, ctx: BenchRunContext) -> dict[str, Any]:
    """悬置带线锚点 runner（suspended-stripline-anchor，Q-X22 / aurora_q）：
    消费 core/suspended_stripline_fd_judge（Q-X20 FD 静流第三方裁判，**只读
    零改动**）全量——FD 收敛阶梯（judge_ladder：六级网格+三点 Richardson
    外推+8 预声明门）+ 裁判资格锚（#300 先过已知基准：cohn_air_anchor/
    exact_limit_anchors/referee_cross_check）+ 闭式腿（_suspended_stripline_ri，
    被裁判对象现场重算）→ 四判据测度组。

    input_spec = ``{"geometry": {"w_mm", "b_mm", "h_mm", "eps_r"},
    "hfss_implied": {"eps_eff", "z0_ohm"}}``——geometry=锚点几何（缺省任务
    预声明 G3 精确点 w=0.52/b=0.50/h=0.05/εr=11.9）；hfss_implied=**外部
    实测锚数据声明**（调用方供给的数据源，非 runner 生成——铁律 7 同族：
    数据的出处是声明不是推算；缺省任务=Q-X20 冻结常量 1.59/50.2Ω）。全键
    正有限（eps_r ≥1）fail-closed。

    判据组（阈值预声明锚见 default_bench_tasks 与模块常量 _SSL_*）：
    - ``fd_convergence``：四项 Richardson 残差最大值 ≤0.001（单源=内核
      LADDER_RESIDUAL_MAX，任务阈值直引）；
    - ``gate_pass``：FD status==CONVERGED（8 门全过）∧ 资格锚全过
      （Cohn 外推 rel ≤0.5%/构造恒等逐位/独立网格族交叉对拍 ≤2e-3——
      INCOMPLETE 或任一锚失格即 fail，不凑）；
    - ``closedform_match``：|闭式−FD|/FD ≤0.015（Q-X20 实测 +1.14%）；
    - ``three_way_consistency``：|FD vs 闭式| ≤1.5% 且 |FD vs HFSS implied|
      ≤2%（带符号偏差对进 note/detail——"fd_vs_closed_signed 带宽"口径）。

    铁律 7：εeff/Z0/残差/资格锚数字全出 FD 内核与闭式内核确定性产出，
    runner 只组装与比较；零仿真零真机零网络（FD=静流数值裁判）。
    """
    del ctx  # FD 内核零文件产物；ctx 仅保持 runner 签名统一
    spec = task.input_spec or {}
    geo = dict(spec.get("geometry") or {})
    vals: dict[str, float] = {}
    for key in ("w_mm", "b_mm", "h_mm", "eps_r"):
        num = _finite_number(geo.get(key))
        if num is None or num <= 0:
            raise ValueError(
                f"ssl_anchor 任务 input_spec.geometry.{key} 必填且为正有限数值，"
                f"得到 {geo.get(key)!r}")
        vals[key] = num
    if vals["eps_r"] < 1.0:
        raise ValueError(
            f"ssl_anchor 任务 input_spec.geometry.eps_r={vals['eps_r']!r} 必须 ≥1.0"
            "（闭式定义域 εr≥1）")
    hf = dict(spec.get("hfss_implied") or {})
    hfss_eps = _finite_number(hf.get("eps_eff"))
    hfss_z0 = _finite_number(hf.get("z0_ohm"))
    if hfss_eps is None or hfss_eps <= 0 or hfss_z0 is None or hfss_z0 <= 0:
        raise ValueError(
            "ssl_anchor 任务 input_spec.hfss_implied.eps_eff/z0_ohm 必填且为正"
            f"有限数值（外部实测锚声明——数据源非预言），得到 {hf!r}")

    from rfauto.core.calculators import _suspended_stripline_ri
    from rfauto.core.suspended_stripline_fd_judge import (
        LADDER_RESIDUAL_MAX,
        cohn_air_anchor,
        exact_limit_anchors,
        judge_ladder,
        referee_cross_check,
    )

    eps_cf, z0_cf = _suspended_stripline_ri(
        vals["w_mm"], vals["b_mm"], vals["h_mm"], vals["eps_r"])
    lad = judge_ladder(w_mm=vals["w_mm"], b_mm=vals["b_mm"],
                       h_mm=vals["h_mm"], eps_r=vals["eps_r"])
    cohn = cohn_air_anchor(w_mm=vals["w_mm"], b_mm=vals["b_mm"])
    lim = exact_limit_anchors(w_mm=vals["w_mm"], b_mm=vals["b_mm"],
                              h_mm=vals["h_mm"], eps_r=vals["eps_r"])
    cross = None
    if lad.status == "CONVERGED":
        cross = referee_cross_check(w_mm=vals["w_mm"], b_mm=vals["b_mm"],
                                    h_mm=vals["h_mm"], eps_r=vals["eps_r"],
                                    eps_self=lad.eps_eff)
    residual_max = max(lad.residual_eps_fine, lad.residual_eps_agree,
                       lad.residual_cair_fine, lad.residual_cair_agree)
    cohn_ok = (bool(cohn.get("converged"))
               and abs(float(cohn["rel"])) <= _SSL_COHN_REL_MAX)
    exact_ok = (abs(float(lim["full_fill_err"])) <= _SSL_EXACT_IDENTITY_TOL
                and abs(float(lim["air_identity_err"])) <= _SSL_EXACT_IDENTITY_TOL
                and bool(lim["thin_lt_thicker"]))
    cross_ok = (cross is not None
                and cross.get("rel_vs_self") is not None
                and abs(float(cross["rel_vs_self"])) <= _SSL_CROSS_CHECK_REL_MAX)
    gate_passed = (lad.status == "CONVERGED") and cohn_ok and exact_ok and cross_ok
    fd_vs_closed = eps_cf / lad.eps_eff - 1.0        # 带符号（FD 为基准，Q-X20 口径）
    fd_vs_hfss = hfss_eps / lad.eps_eff - 1.0
    return {
        "measures": {
            "fd_convergence": {"residual_max": residual_max,
                               "status": lad.status},
            "gate_pass": {"passed": gate_passed,
                          "gate": "ssl_fd_ladder_with_qualification_anchors",
                          "metric": None},
            "closedform_match": {"deviation": abs(fd_vs_closed)},
            "three_way_consistency": {
                "fd_vs_closed": fd_vs_closed, "fd_vs_hfss": fd_vs_hfss,
                "bound_closed": _SSL_CLOSED_DEV_MAX,
                "bound_hfss": _SSL_HFSS_DEV_MAX},
        },
        "detail": {
            "geometry": dict(vals),
            "point": {"u": vals["w_mm"] / vals["b_mm"],
                      "s": vals["h_mm"] / vals["b_mm"]},
            "hfss_implied": {"eps_eff": hfss_eps, "z0_ohm": hfss_z0},
            "fd_converged": {"eps_eff": lad.eps_eff, "z0_ohm": lad.z0_ohm,
                             "status": lad.status,
                             "p_eps": lad.p_eps, "p_cair": lad.p_cair},
            "fd_ladder": lad.as_dict(),
            "anchors": {"cohn_air_z0": cohn, "exact_limits": lim,
                        "referee_cross_check": cross},
            "closed_form": {"eps_eff": eps_cf, "z0_ohm": z0_cf,
                            "source": "core.calc_families.rf_line."
                                      "_suspended_stripline_ri（被裁判对象，"
                                      "现场重算）"},
            "fd_vs_closed_signed": fd_vs_closed,
            "fd_vs_hfss_signed": fd_vs_hfss,
            "residual_max": residual_max,
            "bounds": {"closed": _SSL_CLOSED_DEV_MAX,
                       "hfss": _SSL_HFSS_DEV_MAX,
                       "residual_gate_source":
                           "core.suspended_stripline_fd_judge."
                           "LADDER_RESIDUAL_MAX",
                       "fd_threshold": LADDER_RESIDUAL_MAX},
            "anchor_tolerance": {"cohn_rel_max": _SSL_COHN_REL_MAX,
                                 "cross_check_rel_max": _SSL_CROSS_CHECK_REL_MAX,
                                 "exact_identity_tol": _SSL_EXACT_IDENTITY_TOL},
            "gate_flags": {"cohn_ok": cohn_ok, "exact_ok": exact_ok,
                           "cross_ok": cross_ok,
                           "fd_converged": lad.status == "CONVERGED"},
        },
    }


@register_runner("ssl_race")
def _run_ssl_race(task: BenchTask, ctx: BenchRunContext) -> dict[str, Any]:
    """anchor param_race 变体批量 runner（suspended-stripline-param-race，
    Q-X43 / aurora_q）：G3 锚点为中心的 4 参数（w/b/h/εr）单轴扰动确定性
    枚举表（:data:`_SSL_RACE_AXES` × :data:`_SSL_RACE_FACTORS`——轴插入序×
    因子序，4×4=16 变体，同表两次调用逐字段同构）→ 逐变体 FD 裁判全链
    （judge_ladder 六级阶梯）+ 闭式腿现场重算 → fd_convergence +
    closedform_match 双判据**批量最坏聚合**（上界极性 max——任一变体判据
    不达标即任务级不达标，与 verdict 聚合语义同构）。

    input_spec = ``{"geometry_center": {"w_mm", "b_mm", "h_mm", "eps_r"}}``
    （扰动中心几何；缺省任务=Q-X20 冻结 G3 精确点）。变体几何=中心单轴
    ×(1+factor)；枚举后逐变体先过正有限/εr≥1/h≤b 域检（任一越界
    ValueError fail-closed——不半程炸在 FD 内部）。

    铁律 7：εeff/Z0/残差全出 FD 内核与闭式内核确定性产出，runner 只枚举/
    组装/聚合；零仿真零真机零网络。批量锚数字带（Q-X43 本席探针实测，
    runs/aurora_q/qx43_stats/probe_numbers.json）：residual_max ∈
    [3.3e-4, 5.5e-4]、|dev| ∈ [0.75%, 1.38%]——预声明阈值
    LADDER_RESIDUAL_MAX/_SSL_CLOSED_DEV_MAX 全带内。
    """
    del ctx  # FD 内核零文件产物；ctx 仅保持 runner 签名统一
    spec = task.input_spec or {}
    center = _ssl_geometry_validated(dict(spec.get("geometry_center") or {}),
                                     context="geometry_center")
    fd_threshold = _criterion_threshold(task, "fd_convergence")
    closed_bound = _criterion_threshold(task, "closedform_match")
    from rfauto.core.calculators import _suspended_stripline_ri
    from rfauto.core.suspended_stripline_fd_judge import judge_ladder

    variants = _ssl_race_variant_table(center)
    rows: list[dict[str, Any]] = []
    residual_worst = 0.0
    dev_worst = 0.0
    all_converged = True
    for v in variants:
        geo = v["geometry"]
        lad = judge_ladder(w_mm=geo["w_mm"], b_mm=geo["b_mm"],
                           h_mm=geo["h_mm"], eps_r=geo["eps_r"])
        eps_cf, z0_cf = _suspended_stripline_ri(
            geo["w_mm"], geo["b_mm"], geo["h_mm"], geo["eps_r"])
        residual_max = max(lad.residual_eps_fine, lad.residual_eps_agree,
                           lad.residual_cair_fine, lad.residual_cair_agree)
        dev = abs(eps_cf / lad.eps_eff - 1.0)
        all_converged = all_converged and lad.status == "CONVERGED"
        residual_worst = max(residual_worst, residual_max)
        dev_worst = max(dev_worst, dev)
        rows.append({
            "variant_id": v["variant_id"], "axis": v["axis"],
            "factor": v["factor"], "geometry": dict(geo),
            "fd": {"eps_eff": lad.eps_eff, "z0_ohm": lad.z0_ohm,
                   "status": lad.status, "residual_max": residual_max},
            "closed_form": {"eps_eff": eps_cf, "z0_ohm": z0_cf},
            "deviation": dev,
            "verdicts": {"fd_convergence":
                         "pass" if residual_max <= float(fd_threshold)
                         else "fail",
                         "closedform_match":
                         "pass" if dev <= float(closed_bound) else "fail"},
        })
    return {
        "measures": {
            "fd_convergence": {"residual_max": residual_worst,
                               "status": "CONVERGED" if all_converged
                               else "INCOMPLETE"},
            "closedform_match": {"deviation": dev_worst},
        },
        "detail": {
            "geometry_center": dict(center),
            "variant_table": {"axes": list(_SSL_RACE_AXES),
                              "factors": list(_SSL_RACE_FACTORS),
                              "enumeration": "轴插入序×因子序（确定性枚举表，"
                                             "模块常量单源）"},
            "n_variants": len(rows),
            "aggregation": "worst_case_max_upper_bound（逐变体判据→批量最坏值）",
            "variants": rows,
        },
    }


@register_runner("ssl_g5")
def _run_ssl_g5(task: BenchTask, ctx: BenchRunContext) -> dict[str, Any]:
    """G5 归因数据基准 runner（ssl-g5-attribution，Q-X43 / aurora_q）：
    Q-RM-4 G5 带缘噪声 over_unity=306 的 bench 任务化——**外部实测/复算
    锚数据声明**（input_spec.g5_stats，调用方供给的数据源非 runner 生成，
    铁律 7 同族：数据出处是声明不是推算）→ 双门判读。

    判据（阈值预声明锚 :data:`_G5_OVER_UNITY_MAX`/:data:`_G5_PASSIVITY_MAX`）：
    - ``gate_pass``：over_unity_count 零容差门（Q-X27 冻结口径
      over_unity==0；passed=计数 ≤0，metric=计数，门名
      g5_over_unity_zero_tolerance）；
    - ``closedform_match``：passivity_max 超单位门（Q-X25 门设计面——
      零容差与 ~±0.15% 提取偏置底不兼容，能量面由本门覆盖；deviation=
      passivity_max−1.0 **带符号超单位余量**，欠单位=合法损耗态非违例，
      上界极性只看超出；阈值=超单位上限 _G5_PASSIVITY_EXCESS_MAX=0.05，
      对应 passivity_max ≤1.05——Q-X19 修复后实测 1.0142 门内余量 25%）。

    缺省任务（default_bench_tasks）声明 **Q-RM-4 as-recorded 如实基准**：
    over_unity=306（shield 98+open 208，Q-X25 逐点谱复算逐位一致）、
    passivity_max=1.0142 → gate fail + passivity 门内 → 任务 verdict=**fail**
    （如实登记冻结门 FAIL 态——本任务判读的是归因数据面，不凑绿；
    Q-X25 归因：固定 50Ω 参考下端口波分解提取系统偏置，非带缘盲区）。

    g5_stats 键闭集：必填 ``over_unity_count``（非负 int，bool 拒）/``passivity_max``
    （正有限）；可选 ``variant_split``（{str: 非负 int}）/``attribution``（非空
    str）/``peak_band_ghz``（正有限）/``source``（非空 str）；未知键拒收
    （extra=forbid 同族纪律）。零网络零真机零 FD（纯声明数据判读面）。
    """
    del ctx  # 纯判读面零文件产物
    spec = task.input_spec or {}
    stats = dict(spec.get("g5_stats") or {})
    unknown = sorted(k for k in stats if k not in _G5_STATS_KEYS)
    if unknown:
        raise ValueError(f"ssl_g5 任务 input_spec.g5_stats 未知键 {unknown}"
                         f"（键闭集 {sorted(_G5_STATS_KEYS)}）")
    ou = stats.get("over_unity_count")
    if isinstance(ou, bool) or not isinstance(ou, int) or ou < 0:
        raise ValueError(
            f"ssl_g5 任务 g5_stats.over_unity_count 必填且为非负整数，得到 {ou!r}")
    pmax = _finite_number(stats.get("passivity_max"))
    if pmax is None or pmax <= 0:
        raise ValueError(
            f"ssl_g5 任务 g5_stats.passivity_max 必填且为正有限数值，"
            f"得到 {stats.get('passivity_max')!r}")
    split = stats.get("variant_split")
    split_clean: dict[str, int] | None = None
    if split is not None:
        if not isinstance(split, Mapping) or not split:
            raise ValueError(f"g5_stats.variant_split 须为非空映射，得到 {split!r}")
        split_clean = {}
        for k, v in split.items():
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise ValueError(
                    f"g5_stats.variant_split[{k!r}] 须为非负整数，得到 {v!r}")
            split_clean[str(k)] = v
    attribution = stats.get("attribution")
    if attribution is not None and (not isinstance(attribution, str)
                                    or not attribution.strip()):
        raise ValueError(f"g5_stats.attribution 须为非空字符串，得到 {attribution!r}")
    peak = stats.get("peak_band_ghz")
    peak_num = None
    if peak is not None:
        peak_num = _finite_number(peak)
        if peak_num is None or peak_num <= 0:
            raise ValueError(f"g5_stats.peak_band_ghz 须为正有限数值，得到 {peak!r}")
    source = stats.get("source")
    if source is not None and (not isinstance(source, str) or not source.strip()):
        raise ValueError(f"g5_stats.source 须为非空字符串，得到 {source!r}")

    gate_passed = ou <= _G5_OVER_UNITY_MAX
    deviation = pmax - 1.0
    passivity_in_gate = deviation <= _G5_PASSIVITY_EXCESS_MAX
    return {
        "measures": {
            "gate_pass": {"passed": gate_passed,
                          "gate": "g5_over_unity_zero_tolerance",
                          "metric": float(ou)},
            "closedform_match": {"deviation": deviation},
        },
        "detail": {
            "over_unity_count": ou,
            "passivity_max": pmax,
            "gates": {"over_unity_max": _G5_OVER_UNITY_MAX,
                      "overunity_in_gate": gate_passed,
                      "passivity_max_gate": _G5_PASSIVITY_MAX,
                      "passivity_excess_max": _G5_PASSIVITY_EXCESS_MAX,
                      "passivity_in_gate": passivity_in_gate,
                      "deviation_semantics": "passivity_max−1.0 带符号超单位"
                                             "余量（欠单位=合法损耗态）"},
            "variant_split": split_clean,
            "split_sum_matches_over_unity": (None if split_clean is None
                                             else sum(split_clean.values()) == ou),
            "attribution": (str(attribution) if isinstance(attribution, str)
                            else None),
            "peak_band_ghz": peak_num,
            "source": (str(source) if isinstance(source, str) else None),
        },
    }


@register_runner("ssl_matrix")
def _run_ssl_matrix(task: BenchTask, ctx: BenchRunContext) -> dict[str, Any]:
    """综合变体矩阵 runner（suspended-stripline-synthesis-matrix，Q-X43 /
    aurora_q）：(b, h, εr) 三轴笛卡尔 2³=8 组采样（:data:`_SSL_MATRIX_AXES`
    预声明轴值枚举表，绕 G3 中心 ±10%）→ **综合面闭式反解 w**（core 内核
    suspended_stripline_synthesis：目标 Z0→brentq 回代自洽）→ FD 裁判全链
    双通道对照 → 逐点 fd_convergence + closedform_match +
    three_way_consistency 三判据 → 批量最坏聚合（上界极性 max，同 ssl_race
    语义）。8 组 (w,b,h,εr) 四维完备点=w 由综合面反解、(b,h,εr) 由枚举表
    给定。

    input_spec = ``{"z0_target_ohm": float}``（综合目标阻抗声明值；缺省任务
    50Ω）。three_way 第二腿（fd_vs_hfss 键位）=**综合目标 Z0 腿**：
    z0_target/FD Z0−1（带符号，FD 为基准）——矩阵变体无外部实测锚，第三腿
    如实取声明设计目标值（非 HFSS 实测，键位语义在 data_source 与本
    docstring 双声明；界沿用 _SSL_HFSS_DEV_MAX=外部参考分辨率带宽同款）。
    批量 three_way measure=逐腿跨点独立取最坏（带符号值进逐点 rows——
    外包络判读保守化，点间配对在 detail.variants 可审计）。

    铁律 7：w 出综合内核 brentq、εeff/Z0/残差出 FD 内核与闭式内核，runner
    只枚举/组装/聚合；零仿真零真机零网络。批量锚数字带（Q-X43 本席探针
    实测，runs/aurora_q/qx43_stats/probe_numbers.json）：residual_max ∈
    [3.5e-4, 4.1e-4]、|dev_closed| ∈ [1.07%, 1.29%]、|dev_target| ∈
    [0.43%, 0.53%]——预声明阈值全带内。
    """
    del ctx  # FD 内核零文件产物
    spec = task.input_spec or {}
    z0_target = _finite_number(spec.get("z0_target_ohm"))
    if z0_target is None or z0_target <= 0:
        raise ValueError(
            f"ssl_matrix 任务 input_spec.z0_target_ohm 必填且为正有限数值，"
            f"得到 {spec.get('z0_target_ohm')!r}")

    from rfauto.core.calculators import (
        _suspended_stripline_ri,
        suspended_stripline_synthesis,
    )
    from rfauto.core.suspended_stripline_fd_judge import judge_ladder

    fd_threshold = _criterion_threshold(task, "fd_convergence")
    closed_bound = _criterion_threshold(task, "closedform_match")
    rows: list[dict[str, Any]] = []
    residual_worst = 0.0
    dev_closed_worst = 0.0
    dev_target_worst = 0.0
    signed_closed_worst = 0.0
    signed_target_worst = 0.0
    all_converged = True
    for b_mm, h_mm, eps_r in _ssl_matrix_combos():
        syn = suspended_stripline_synthesis(z0_ohm=z0_target, b_mm=b_mm,
                                            h_mm=h_mm, epsilon_r=eps_r)
        w_mm = _finite_number(syn.get("w_mm"))
        if w_mm is None or w_mm <= 0:
            raise RuntimeError(
                f"综合面反解返回非法 w_mm={syn.get('w_mm')!r}（b={b_mm} "
                f"h={h_mm} εr={eps_r}）")
        lad = judge_ladder(w_mm=w_mm, b_mm=b_mm, h_mm=h_mm, eps_r=eps_r)
        eps_cf, z0_cf = _suspended_stripline_ri(w_mm, b_mm, h_mm, eps_r)
        residual_max = max(lad.residual_eps_fine, lad.residual_eps_agree,
                           lad.residual_cair_fine, lad.residual_cair_agree)
        signed_closed = eps_cf / lad.eps_eff - 1.0
        signed_target = z0_target / lad.z0_ohm - 1.0
        all_converged = all_converged and lad.status == "CONVERGED"
        residual_worst = max(residual_worst, residual_max)
        if abs(signed_closed) > abs(signed_closed_worst):
            signed_closed_worst = signed_closed
        if abs(signed_target) > abs(signed_target_worst):
            signed_target_worst = signed_target
        dev_closed_worst = max(dev_closed_worst, abs(signed_closed))
        dev_target_worst = max(dev_target_worst, abs(signed_target))
        rows.append({
            "combo_id": (f"b{b_mm}_h{h_mm}_e{eps_r}").replace(".", "p"),
            "geometry": {"w_mm": w_mm, "b_mm": b_mm, "h_mm": h_mm,
                         "eps_r": eps_r},
            "synthesis": {"w_mm": syn.get("w_mm"),
                          "z0_actual_ohm": syn.get("z0_actual_ohm"),
                          "eps_eff": syn.get("eps_eff")},
            "fd": {"eps_eff": lad.eps_eff, "z0_ohm": lad.z0_ohm,
                   "status": lad.status, "residual_max": residual_max},
            "closed_form": {"eps_eff": eps_cf, "z0_ohm": z0_cf},
            "signed_dev_closed": signed_closed,
            "signed_dev_target": signed_target,
            "verdicts": {"fd_convergence":
                         "pass" if residual_max <= float(fd_threshold)
                         else "fail",
                         "closedform_match":
                         "pass" if abs(signed_closed) <= float(closed_bound)
                         else "fail",
                         "three_way_consistency":
                         "pass" if (abs(signed_closed) <= _SSL_CLOSED_DEV_MAX
                                    and abs(signed_target)
                                    <= _SSL_HFSS_DEV_MAX) else "fail"},
        })
    return {
        "measures": {
            "fd_convergence": {"residual_max": residual_worst,
                               "status": "CONVERGED" if all_converged
                               else "INCOMPLETE"},
            "closedform_match": {"deviation": dev_closed_worst},
            "three_way_consistency": {
                "fd_vs_closed": signed_closed_worst,
                "fd_vs_hfss": signed_target_worst,
                "bound_closed": _SSL_CLOSED_DEV_MAX,
                "bound_hfss": _SSL_HFSS_DEV_MAX},
        },
        "detail": {
            "z0_target_ohm": z0_target,
            "sample_table": {"axes": [a for a, _, _ in _SSL_MATRIX_AXES],
                             "values": {a: [lo, hi] for a, lo, hi
                                        in _SSL_MATRIX_AXES},
                             "enumeration": "轴声明序×轴值序笛卡尔 2³=8 组"
                                            "（确定性枚举表，模块常量单源）",
                             "center_basis": "G3 中心 ±10%（Q-X20 冻结锚）"},
            "leg_semantics": {
                "fd_vs_closed": "闭式分析 εeff / FD εeff − 1（带符号，FD 为基准）",
                "fd_vs_hfss": "综合目标 Z0（声明值）/ FD Z0 − 1——矩阵变体无"
                              "外部实测锚，第三腿=声明设计目标（非 HFSS 实测）"},
            "n_combos": len(rows),
            "aggregation": "worst_case_max_upper_bound（逐点判据→批量最坏值；"
                           "three_way 逐腿跨点独立取最坏）",
            "combos": rows,
        },
    }


@register_runner("layered_verdict")
def _run_layered_verdict(task: BenchTask, ctx: BenchRunContext) -> dict[str, Any]:
    """layered_stack 双档对照判读 runner（layered-stack-verdict，Q-X55 /
    aurora_q）：消费 layered_stack_verdict_service（Q-X26 判读预备，**只读
    零改动**）的对照表（compare_tiers）+ RC 三因子分解（decompose_factors
    ——compare_tiers 内嵌 rc_matrix 同一产出）。

    input_spec = ``{"tiers": {name: 档位记录}, "closed_eps_eff": float}``——
    tiers=**声明式档位记录**（build_tier_record 产出形态的行：观测面+门态
    面，调用方供给的数据源非 runner 生成——铁律 7 同族：数据出处是声明不是
    推算；缺省任务=Q-X26 comparison_table.json 三档 as-recorded 冻结快照
    ：data:`_QX26_TIERS_SNAPSHOT`，出处随行）；closed_eps_eff=闭式锚
    （Q-X10 判据单源 closed_form_anchor 实测冻结值，对照表行内补缺/重算
    eps_eff_rel 消费）。判读行必需键 13 项（name/verdict/not_judged/
    geometry/mesh_base_mm/mesh_cells/window_ps/port_structure_suspect/
    s0_status/over_unity_cnt/eps_eff_med/eps_eff_closed/eps_eff_rel）缺席
    → ValueError fail-closed（对照/分解消费面不猜）。

    判据组（阈值预声明锚见 default_bench_tasks 与模块常量 _QX26_*）：
    - ``closedform_match``：跨档最坏 |eps_eff_med−eps_eff_closed|/closed
      ≤0.02（判据单源=runs/aurora_q/qx10_smoke/qx10_verdict.py G1_PASS
      冻结带承袭；对照表行内 eps_eff_rel 由服务重算消费，runner 只取最
      坏，铁律 7 零重实现）；
    - ``gate_pass``：RC 结构面门（预声明规则）——全部已判档 RC1 ==
      excluded ∧ RC3 == excluded（端口结构哨兵清白且零超一点）才过；
      implicated/co_present_not_attributed/unevaluated 任一在场即 fail
      （结构未清白=门未过，不凑）；INCOMPLETE/未判档由服务原样透传不升格
      （#122，服务 incomplete_passthrough_note 同款语义）。

    铁律 7：门限与状态词全出 Q-X26 服务与其判据单源（qx10_verdict 冻结
    模块）产出，runner 只组装/比较；零仿真零真机零网络。
    """
    del ctx  # 纯判读面零文件产物
    spec = task.input_spec or {}
    tiers_decl = spec.get("tiers")
    if not isinstance(tiers_decl, Mapping) or not tiers_decl:
        raise ValueError(
            f"layered_verdict 任务 input_spec.tiers 必填且为非空映射"
            f"（name→档位记录），得到 {tiers_decl!r}")
    closed = _finite_number(spec.get("closed_eps_eff"))
    if closed is None or closed <= 0:
        raise ValueError(
            f"layered_verdict 任务 input_spec.closed_eps_eff 必填且为正有限"
            f"数值（Q-X10 判据单源闭式锚声明值），得到 "
            f"{spec.get('closed_eps_eff')!r}")
    records: dict[str, dict[str, Any]] = {}
    for name, row in tiers_decl.items():
        if not isinstance(row, Mapping):
            raise ValueError(
                f"layered_verdict 任务档位 {name!r} 记录须为映射，得到 {row!r}")
        missing = [k for k in _QX26_ROW_REQUIRED_KEYS if k not in row]
        if missing:
            raise ValueError(
                f"layered_verdict 任务档位 {name!r} 缺必需键 {missing}"
                f"（对照/分解消费面 {list(_QX26_ROW_REQUIRED_KEYS)}）")
        records[str(name)] = dict(row)

    from rfauto.service import layered_stack_verdict_service as lsv

    table = lsv.compare_tiers(records, closed_eps_eff=closed)
    rc = table["rc_matrix"]
    rels = [abs(float(r["eps_eff_rel"])) for r in table["tiers"].values()
            if _finite_number(r.get("eps_eff_rel")) is not None]
    dev_worst = max(rels) if rels else None
    rc1_states = [str(f["RC1_geometry_port_structure"])
                  for f in rc["factors"].values()]
    rc3_states = [str(f["RC3_truncation"]) for f in rc["factors"].values()]
    gate_passed = (all(s == "excluded" for s in rc1_states)
                   and all(s == "excluded" for s in rc3_states))
    return {
        "measures": {
            "closedform_match": {"deviation": dev_worst},
            "gate_pass": {"passed": gate_passed,
                          "gate": "layered_stack_rc_factor_gate",
                          "metric": None},
        },
        "detail": {
            "tiers": table["tiers"],
            "summary": table["summary"],
            "rc_matrix": rc,
            "gate_rule": ("全部已判档 RC1==excluded 且 RC3==excluded"
                          "（端口结构哨兵清白+零超一点；unevaluated 不算"
                          "清白——预声明，不凑）"),
            "rc1_states": rc1_states,
            "rc3_states": rc3_states,
            "closed_eps_eff": closed,
            "data_provenance": {
                name: str(row.get("source")) if row.get("source") else None
                for name, row in records.items()},
        },
    }


# ── Q-X27 判读单源动态加载（ssl_rereverify runner 消费面）───────────────────

#: Q-X27 判读纯函数单源（**仓内只读件**，判读面与三态 as-recorded 快照
#: 常量同文件——runs/ 湖 gitignored，测试以常量随行登记出处不运行时读湖，
#: 本路径=常规检出必有面；发布包无 tests/ 时 fail-loud 缺失=诚实失败）。
_SSL_REREVERIFY_MODULE_RELATIVE = (Path("tests") / "unit"
                                   / "test_ssl_rereverify.py")
#: 加载后模块必须具备的判读面（缺任一=fail-loud；防半成品判读模块当真）。
_SSL_REREVERIFY_REQUIRED_ATTRS: tuple[str, ...] = (
    "g3_basis_switch", "g5_attribution_test", "three_state_gate_table",
    "predeclared_expectations", "expectation_check", "status_movement",
    "V_RM1", "V_RM4", "V_REVERIFY", "OU_RM4_VARIANTS",
    "OU_REVERIFY_VARIANTS",
)
#: ssl_rereverify 三态 verdict 快照 schema 的门键闭集（G1–G5）。
_SSL_REREVERIFY_GATE_IDS: tuple[str, ...] = ("G1", "G2", "G3", "G4", "G5")


def _load_ssl_rereverify_module(
    path: str | Path | None = None,
) -> Any:
    """Q-X27 判读单源加载（layered_stack_verdict_service 动态加载同款形态：
    importlib 文件加载独立实例、不注册 sys.modules；fail-loud 不静默降级）。

    - path 缺省=仓内 tests/unit/test_ssl_rereverify.py（repo 根由本文件
      位置推导）；文件缺 → FileNotFoundError。
    - 被加载模块自身 ``from tests.unit.test_suspended_anchor_verdict
      import``（冻结门单源）需 repo 根在 sys.path——加载前临时插入、exec
      后还原（其传递导入会正常进 sys.modules 包缓存，与 pytest 导入同一
      模块对象，零双份定义）。
    - 模块缺 :data:`_SSL_REREVERIFY_REQUIRED_ATTRS` 任一判读面 →
      ValueError（列出缺项）。
    """
    import importlib.util
    import sys
    import uuid

    resolved = (Path(path) if path is not None
                else Path(__file__).resolve().parents[3]
                / _SSL_REREVERIFY_MODULE_RELATIVE)
    if not resolved.is_file():
        raise FileNotFoundError(
            f"Q-X27 判读单源缺失（fail-loud 不静默降级）: {resolved}")
    repo_root = str(Path(__file__).resolve().parents[3])
    added = repo_root not in sys.path
    if added:
        sys.path.insert(0, repo_root)
    try:
        spec = importlib.util.spec_from_file_location(
            f"_qx27_judge_fresh_{uuid.uuid4().hex}", resolved)
        if spec is None or spec.loader is None:  # pragma: no cover - defensive
            raise ImportError(f"判读单源加载器构造失败: {resolved}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if added and repo_root in sys.path:
            sys.path.remove(repo_root)
    missing = [a for a in _SSL_REREVERIFY_REQUIRED_ATTRS
               if not hasattr(module, a)]
    if missing:
        raise ValueError(
            f"Q-X27 判读单源缺必需判读面 {missing}: {resolved}")
    return module


def _ssl_rereverify_state_validated(state: Any, label: str) -> dict[str, Any]:
    """三态 verdict 快照域检（fail-closed 不猜）：verdict 非空 str、G1–G5
    门映射齐且带非空 status、G5 带非负 int 超一点计数+正有限 passivity、
    G3 带正有限 observed_eps_eff（g3_basis_switch 消费面）。"""
    if not isinstance(state, Mapping):
        raise ValueError(
            f"ssl_rereverify 任务 states.{label} 须为映射，得到 {state!r}")
    verdict = state.get("verdict")
    if not isinstance(verdict, str) or not verdict.strip():
        raise ValueError(
            f"ssl_rereverify 任务 states.{label}.verdict 必填且为非空 str，"
            f"得到 {verdict!r}")
    gates = state.get("gates")
    if not isinstance(gates, Mapping):
        raise ValueError(
            f"ssl_rereverify 任务 states.{label}.gates 须为映射，得到 {gates!r}")
    for gid in _SSL_REREVERIFY_GATE_IDS:
        gate = gates.get(gid)
        status = gate.get("status") if isinstance(gate, Mapping) else None
        if not isinstance(status, str) or not status.strip():
            raise ValueError(
                f"ssl_rereverify 任务 states.{label}.{gid} 缺非空 status"
                f"（三态对照表消费面），得到 {gate!r}")
    g5 = gates["G5"]
    ou = g5.get("s_over_unity_cnt")
    if isinstance(ou, bool) or not isinstance(ou, int) or ou < 0:
        raise ValueError(
            f"ssl_rereverify 任务 states.{label}.G5.s_over_unity_cnt 必填"
            f"且为非负整数，得到 {ou!r}")
    pmax = _finite_number(g5.get("passivity_max"))
    if pmax is None or pmax <= 0:
        raise ValueError(
            f"ssl_rereverify 任务 states.{label}.G5.passivity_max 必填且为"
            f"正有限数值，得到 {g5.get('passivity_max')!r}")
    eps_obs = _finite_number(gates["G3"].get("observed_eps_eff"))
    if eps_obs is None or eps_obs <= 0:
        raise ValueError(
            f"ssl_rereverify 任务 states.{label}.G3.observed_eps_eff 必填且"
            f"为正有限数值（g3_basis_switch 消费面），得到 "
            f"{gates['G3'].get('observed_eps_eff')!r}")
    return dict(state)


@register_runner("ssl_rereverify")
def _run_ssl_rereverify(task: BenchTask, ctx: BenchRunContext) -> dict[str, Any]:
    """悬置带线双修复重验 runner（suspended-stripline-rereverify，Q-X55 /
    aurora_q）：消费 Q-X27 三态对照判读单源（tests/unit/test_ssl_rereverify
    .py——判读纯函数与三态 as-recorded 快照常量同文件，**动态加载只读
    零改动**）全链：三态五门对照表（three_state_gate_table）+ G5 归因检验
    （g5_attribution_test）+ G3 双基准并列判读（g3_basis_switch）+ 预声明
    期望吻合核对（predeclared_expectations×expectation_check）。

    input_spec = ``{"states": {"before"/"near_fix"/"reverify": verdict
    快照, "ou_before"/"ou_after": 分变体超一点计数}}``（可选——缺省=
    判读单源 as-recorded 冻结快照常量 Q-RM-1→Q-RM-4→重验 2026-11-07
    终态，数据源=判读单源同文件常量随行登记出处）。快照 schema 域检
    fail-closed（:func:`_ssl_rereverify_state_validated`）；分变体计数
    与三态 G5 计数和须一致（sum(ou_before)==near_fix.G5 计数、
    sum(ou_after)==reverify.G5 计数——Q-X27 三源一致守卫同款纪律，防
    混态数据进判读）。

    判据组（阈值预声明锚 :data:`_QX55_REREVERIFY_G3_REL_MAX`）：
    - ``gate_pass``：预声明期望吻合核对零 miss 才过（expectation_check
      n_misses==0；gate 名 qx27_expectation_check，metric=miss 数）；
    - ``closedform_match``：重验态 G3 双基准最坏相对偏差
      max(|rel_vs_closed|, |rel_vs_fd|) ≤0.05（G3_PARTIAL 冻结带承袭=
      非 FAIL 上界，源=tests/unit/test_suspended_anchor_verdict G3_PASS
      /G3_PARTIAL 2%/5% 不放宽；Q-X20 FD 真值=分析面旁证口径，冻结门锚
      仍=闭式）。

    缺省任务（default_bench_tasks）=**as-recorded 如实基准**：重验态
    over_unity 306→180（drop=41.2% 落中带 MIXED_PARTIAL_DROP，非预声明
    大幅线）+总 verdict DISAGREE（非预声明 PARTIAL）→ 期望核对 6 hit/
    2 miss → gate fail；G3 双基准最坏 2.88% ≤5% 门内 → closedform pass；
    任务 verdict=**fail**（预声明期望未全中如实登记不凑绿——G5 计数分支
    与总判两 miss 即 Q-X27 REPORT 同款 as-recorded 结论）。

    铁律 7：判读门限/状态词/期望表全出判读单源冻结模块，runner 只加载/
    组装/比较；零仿真零真机零网络（判读面纯函数）。
    """
    del ctx  # 纯判读面零文件产物
    spec = task.input_spec or {}
    module = _load_ssl_rereverify_module(spec.get("judge_module_path"))
    states_decl = spec.get("states")
    if states_decl is None:
        before = dict(module.V_RM1)
        near_fix = dict(module.V_RM4)
        reverify = dict(module.V_REVERIFY)
        ou_before = dict(module.OU_RM4_VARIANTS)
        ou_after = dict(module.OU_REVERIFY_VARIANTS)
        states_source = ("判读单源 as-recorded 冻结快照常量"
                         "（tests/unit/test_ssl_rereverify.py V_RM1/V_RM4/"
                         "V_REVERIFY+OU_*，出处随模块 docstring）")
    else:
        if not isinstance(states_decl, Mapping):
            raise ValueError(
                f"ssl_rereverify 任务 input_spec.states 须为映射，得到 "
                f"{states_decl!r}")
        for key in ("before", "near_fix", "reverify"):
            if key not in states_decl:
                raise ValueError(
                    f"ssl_rereverify 任务 input_spec.states 缺必填键 "
                    f"{key!r}（三态对照表消费面）")
        before = _ssl_rereverify_state_validated(states_decl["before"],
                                                 "before")
        near_fix = _ssl_rereverify_state_validated(states_decl["near_fix"],
                                                   "near_fix")
        reverify = _ssl_rereverify_state_validated(states_decl["reverify"],
                                                   "reverify")
        ou_before = dict(states_decl.get("ou_before") or {})
        ou_after = dict(states_decl.get("ou_after") or {})
        states_source = "input_spec.states 声明数据（调用方供给）"
    for key, state_label, ou_map, state in (
            ("ou_before", "near_fix", ou_before, near_fix),
            ("ou_after", "reverify", ou_after, reverify)):
        for var, cnt in ou_map.items():
            if isinstance(cnt, bool) or not isinstance(cnt, int) or cnt < 0:
                raise ValueError(
                    f"ssl_rereverify 任务 states.{key}[{var!r}] 须为非负"
                    f"整数，得到 {cnt!r}")
        expected_sum = int(state["gates"]["G5"]["s_over_unity_cnt"])
        if ou_map and sum(ou_map.values()) != expected_sum:
            raise ValueError(
                f"ssl_rereverify 任务 states.{key} 分变体和 "
                f"{sum(ou_map.values())} != states.{state_label} G5 计数 "
                f"{expected_sum}（三源一致守卫——混态数据不进判读）")

    expected = module.predeclared_expectations()
    table = module.three_state_gate_table(before, near_fix, reverify,
                                          expected)
    g5 = module.g5_attribution_test(
        over_unity_before=int(near_fix["gates"]["G5"]["s_over_unity_cnt"]),
        over_unity_after=int(reverify["gates"]["G5"]["s_over_unity_cnt"]),
        passivity_before=float(near_fix["gates"]["G5"]["passivity_max"]),
        passivity_after=float(reverify["gates"]["G5"]["passivity_max"]),
        per_variant_before=(dict(ou_before) if ou_before else None),
        per_variant_after=(dict(ou_after) if ou_after else None))
    g3_rows = {
        label: module.g3_basis_switch(
            float(state["gates"]["G3"]["observed_eps_eff"]))
        for label, state in (("before", before), ("near_fix", near_fix),
                             ("reverify", reverify))
    }
    chk = module.expectation_check(reverify, str(g5["classification"]),
                                   str(g3_rows["reverify"]["status_vs_fd"]))
    gate_passed = int(chk["n_misses"]) == 0
    rel_closed = abs(float(g3_rows["reverify"]["rel_vs_closed"]))
    rel_fd = abs(float(g3_rows["reverify"]["rel_vs_fd"]))
    dev_worst = max(rel_closed, rel_fd)
    return {
        "measures": {
            "gate_pass": {"passed": gate_passed,
                          "gate": "qx27_expectation_check",
                          "metric": float(chk["n_misses"])},
            "closedform_match": {"deviation": dev_worst},
        },
        "detail": {
            "states_source": states_source,
            "predeclared_expectations": dict(expected),
            "three_state_table": table,
            "g5_attribution": g5,
            "g3_basis_switch": g3_rows,
            "expectation_check": chk,
            "g3_rel_worst": dev_worst,
            "g3_rel_bound_source": (
                "tests/unit/test_suspended_anchor_verdict G3_PARTIAL=0.05"
                "（G3_PASS=0.02/G3_PARTIAL=0.05 冻结带承袭=非 FAIL 上界）"),
        },
    }


def _criterion_threshold(task: BenchTask, name: str) -> float | None:
    """任务声明里某判据的预声明阈值（未声明返回 None）。"""
    for c in task.criteria:
        if c.name == name:
            return c.threshold
    return None


# ---------------------------------------------------------------------------
# 评测器：run_bench_task（TaskResult 进出）
# ---------------------------------------------------------------------------


def _empty_result(task_id: str, family: str, errors: Sequence[str], *,
                  stage: str, title: str = "", data_source: str = "",
                  envelope: dict[str, Any] | None = None) -> dict[str, Any]:
    """任务定义错误/执行失败的 TaskResult 形态（verdict=fail，scores 空——
    基准跑分中 ill-defined/崩溃任务计失败且留痕，不静默丢出得分卡）。

    R-01 判据增强包固定键：spec_score=None（无判定面无部分分——不编数）/
    hidden_summary=None（未达隐藏层判定面）/ grader_notes=None（失败结果
    不携带 rubric 附注——判定未发生）/ ood_flag=False + envelope 块（缺省
    absent；调用方传入已解析任务的声明块时透传——声明在场不谎报 absent）。
    """
    return {
        "schema_version": BENCH_SCHEMA_VERSION,
        "task_id": task_id, "family": family, "title": title,
        "data_source": data_source,
        "stage": stage, "ok": False, "verdict": "fail",
        "scores": {}, "detail": {}, "errors": normalize_errors(list(errors)),
        "evidence_path": None,
        "spec_score": None, "hidden_summary": None, "grader_notes": None,
        "ood_flag": False,
        "envelope": envelope if envelope is not None else _envelope_absent_block(),
    }


def _envelope_absent_block(note: str | None = None) -> dict[str, Any]:
    """envelope=absent 固定形态（B3：包络未声明如实输出，不伪造）。

    五键固定（status/ood_flag/violations/checked_keys/unverified_keys）+
    可选 note——消费方面形状稳定，缺就是不缺（absent=未声明，不是 OOD）。"""
    return {
        "status": "absent", "ood_flag": False, "violations": [],
        "checked_keys": [], "unverified_keys": [],
        "note": note or "envelope 未声明（absent——如实不伪造）",
    }


def _envelope_declared_unverified_block(bt: BenchTask, stage: str) -> dict[str, Any]:
    """已解析任务在**未达评估点**路径（validate/execute 失败）的 envelope 块。

    声明在场不得谎报 absent（不伪造纪律）：status=declared、ood_flag=False
    （OOD 只在真越界时为 true）、全部包络键如实进 unverified_keys——
    "声明了但没验证"与"没声明"是两个事实，报告面分开说。"""
    if bt.envelope is None:
        return _envelope_absent_block()
    return {
        "status": "declared", "ood_flag": False, "violations": [],
        "checked_keys": [], "unverified_keys": sorted(bt.envelope),
        "note": f"任务未达评估点（stage={stage}）——包络已声明但 OOD 未验证",
    }


def _evaluate_criteria(
    task: BenchTask,
    measures: Mapping[str, Any],
    criteria: Sequence[BenchCriterion] | None = None,
) -> dict[str, dict[str, Any]]:
    """逐条判据评定（判据注册表分发；缺测/非法/判据函数异常 → unknown）。

    ``criteria``：待评定判据子序列（None=任务公开层 criteria）。AX-1③
    hidden/visible 分层消费面——隐藏层以 ``criteria=task.hidden_criteria``
    独立评定，结果不进公开 scores（报告只出汇总）。"""
    scores: dict[str, dict[str, Any]] = {}
    for c in (task.criteria if criteria is None else criteria):
        measure = measures.get(c.name)
        if measure is None:
            scores[c.name] = _outcome(
                None, "unknown", c.threshold,
                note="判据测度缺失（runner 未产出）——显式 unknown 不凑分")
            continue
        if not isinstance(measure, Mapping):
            scores[c.name] = _outcome(None, "unknown", c.threshold,
                                      note="判据测度形态非法（须映射）")
            continue
        fn = criterion_fn(c.name)
        if fn is None:  # schema 已拦；防御性兜底（注册表被运行时改动）
            scores[c.name] = _outcome(None, "unknown", c.threshold, note="判据函数未注册")
            continue
        try:
            scores[c.name] = fn(measure, c.threshold)
        except Exception as exc:  # 判据函数内部缺陷不冒充 pass/fail（#105 观测不阻塞）
            scores[c.name] = _outcome(None, "unknown", c.threshold,
                                      note=f"判据函数异常: {type(exc).__name__}: {exc}")
    return scores


def _aggregate_verdict(scores: Mapping[str, Mapping[str, Any]]) -> str:
    """任务 verdict 聚合（预声明语义，见模块 docstring）：任一 fail → fail；
    全部 pass → pass；其余（含空 scores/含 unknown）→ unknown。"""
    verdicts = [str(v.get("verdict")) for v in scores.values()]
    if "fail" in verdicts:
        return "fail"
    if verdicts and all(v == "pass" for v in verdicts):
        return "pass"
    return "unknown"


def run_bench_task(
    task: BenchTask | Mapping[str, Any],
    *,
    evidence_dir: str | Path | None = None,
    work_root: str | Path | None = None,
) -> dict[str, Any]:
    """执行单个基准任务并评判据（评测器主入口；TaskResult dict 进出）。

    流程：schema 校验 → family runner 查找（未知 fail-closed）→ 必填阈值
    预声明检查（#122；visible+hidden 双层同规）→ cwd 隔离（chdir
    work_root，finally 还原——#144 家族纪律：service 层 cwd 相对写面全落
    work_root，零真实 runs/ 湖污染）→ runner 执行（既有 service 真函数）→
    判据注册表逐条评定（visible+hidden 两层都算，AX-1③）→ verdict 聚合
    → spec_score/envelope/grader_notes 报告列组装（AX-1①②+B3）→ 证据
    落盘（evidence_dir 显式给定时写 ``<task_id>.result.json``，缺省 None
    拒写）。

    Args:
        task: BenchTask 实例或同构 dict（schema 串无——Pydantic 直校验）。
        evidence_dir: 证据目录（None=不落证据文件，evidence_path=None）。
        work_root: cwd 隔离根（None=tempfile 会话一次性目录，规则 9）。

    Returns:
        TaskResult dict：``{schema_version, task_id, family, title,
        data_source, stage, ok, verdict, scores, detail, errors,
        evidence_path, spec_score, hidden_summary, grader_notes,
        ood_flag, envelope}``。verdict 语义见模块 docstring（定义错误/runner
        异常=fail 且 stage=validate/execute 区分；判据缺测=unknown 不凑分）。
        R-01 判据增强包键：``spec_score``=部分分列（AX-1②，verdict 零变）；
        ``hidden_summary``=隐藏层汇总（AX-1③，None=无隐藏层；scores 只含
        visible 明细——hidden 细节不出报告面）；``grader_notes``=rubric
        附注透出（AX-1①）；``ood_flag``/``envelope``=训练包络守卫（B3——
        ood_flag=true 不改 verdict；envelope.status ∈ declared/absent/
        unknown 如实三态）。
    """
    raw_id = str(task.get("task_id") or "?") if isinstance(task, Mapping) else "?"
    raw_family = str(task.get("family") or "?") if isinstance(task, Mapping) else "?"
    try:
        bt = task if isinstance(task, BenchTask) else BenchTask.model_validate(dict(task))
    except Exception as exc:
        return _empty_result(raw_id, raw_family,
                             [f"BenchTask schema 校验失败: {type(exc).__name__}: {exc}"],
                             stage="validate",
                             envelope={"status": "unknown", "ood_flag": False,
                                       "violations": [], "checked_keys": [],
                                       "unverified_keys": [],
                                       "note": "任务形态不可读（schema 校验失败）"
                                               "——envelope 声明不可知，如实 unknown"})

    runner = _RUNNER_REGISTRY.get(bt.family)
    if runner is None:
        return _empty_result(
            bt.task_id, bt.family,
            [f"family={bt.family!r} 无注册 runner（已注册={list(_RUNNER_REGISTRY)}）"],
            stage="validate", title=bt.title, data_source=bt.data_source,
            envelope=_envelope_declared_unverified_block(bt, "validate"))
    all_criteria = [*bt.criteria, *bt.hidden_criteria]
    missing_thresholds = [c.name for c in all_criteria
                          if c.name in THRESHOLD_REQUIRED and c.threshold is None]
    if missing_thresholds:
        return _empty_result(
            bt.task_id, bt.family,
            [f"判据 {missing_thresholds} 缺预声明阈值"
             f"（#122：阈值预声明，缺即 fail-closed 不猜；hidden 层同规）"],
            stage="validate", title=bt.title, data_source=bt.data_source,
            envelope=_envelope_declared_unverified_block(bt, "validate"))

    if work_root is not None:
        root = Path(work_root).resolve()
    else:
        root = Path(tempfile.mkdtemp(prefix="rfauto_embench_")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    ev = Path(evidence_dir).resolve() if evidence_dir is not None else None
    ctx = BenchRunContext(evidence_dir=ev, work_root=root)

    prev_cwd = os.getcwd()
    try:
        os.chdir(root)
        run = runner(bt, ctx)
    except Exception as exc:
        result = _empty_result(bt.task_id, bt.family,
                               [f"{type(exc).__name__}: {exc}"],
                               stage="execute", title=bt.title,
                               data_source=bt.data_source,
                               envelope=_envelope_declared_unverified_block(bt, "execute"))
    else:
        if not isinstance(run, Mapping) or not isinstance(run.get("measures"), Mapping):
            result = _empty_result(
                bt.task_id, bt.family,
                [f"runner 返回形态非法（须 {{measures, detail}} 映射）: {type(run).__name__}"],
                stage="execute", title=bt.title, data_source=bt.data_source,
                envelope=_envelope_declared_unverified_block(bt, "execute"))
        else:
            # AX-1③ hidden/visible 双层判定：两层都算（verdict 聚合含隐藏
            # 层）；报告面 scores=visible 明细，hidden 只出汇总（不出细节）。
            scores = _evaluate_criteria(bt, run["measures"])
            hidden_scores = (_evaluate_criteria(bt, run["measures"],
                                                criteria=bt.hidden_criteria)
                             if bt.hidden_criteria else {})
            merged: dict[str, dict[str, Any]] = {**scores, **hidden_scores}
            verdict = _aggregate_verdict(merged)
            hidden_summary: dict[str, int] | None = None
            if bt.hidden_criteria:
                hv = [str(v.get("verdict")) for v in hidden_scores.values()]
                hidden_summary = {"n_total": len(bt.hidden_criteria),
                                  "n_pass": hv.count("pass"),
                                  "n_fail": hv.count("fail"),
                                  "n_unknown": hv.count("unknown")}
            # AX-1② spec_score 部分分列：visible+hidden 全体判定检查占比；
            # verdict 语义零变（上面聚合一字未动，spec_score 只是附加列）。
            spec = spec_score_from_scores(merged)
            env_block = _envelope_block_for_task(bt)
            result = {
                "schema_version": BENCH_SCHEMA_VERSION,
                "task_id": bt.task_id, "family": bt.family, "title": bt.title,
                "data_source": bt.data_source,
                "stage": "execute", "ok": True,
                "verdict": verdict,
                "scores": scores,
                "detail": dict(run.get("detail") or {}),
                "errors": [], "evidence_path": None,
                "spec_score": spec,
                "hidden_summary": hidden_summary,
                "grader_notes": (bt.grader_notes.model_dump()
                                 if bt.grader_notes is not None else None),
                "ood_flag": env_block["ood_flag"],
                "envelope": env_block,
            }
    finally:
        os.chdir(prev_cwd)

    if ev is not None:
        ev.mkdir(parents=True, exist_ok=True)
        path = ev / f"{bt.task_id}.result.json"
        result["evidence_path"] = str(path)
        path.write_text(
            json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8")
    return result


# ---------------------------------------------------------------------------
# 得分卡：score_bench（三口径汇总；ChatCFD 对表口径）
# ---------------------------------------------------------------------------


def score_bench(results: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    """基准得分卡汇总（TaskResult 序列 → 逐任务 verdict + 三口径）。

    三口径（ChatCFD 执行成功率 82%/物理保真 59%/$0.2 每例的对表位）：

    - ``success_rate``：n_pass / n_tasks（任务级执行成功率；fail 与
      unknown 都计分母——失败可见才是护栏经济学的实证形态）；
    - ``interface_failure_rate``：接口层失败分类口径（分类面=内部档，
      不在公开树）——公开面恒如实 None（铁律 7 同族）；
    - ``token_cost``：恒 None——无计费账本，缺就是不缺数，不编（铁律 7
      同族；后续席位接计费账本后由 token_cost 判据产出）。

    非 Mapping/缺 verdict 键的条目计 n_invalid（多报不放过，#316 方向）。
    """

    tasks: list[dict[str, Any]] = []
    n_pass = n_fail = n_unknown = n_invalid = 0
    for item in results or []:
        if not isinstance(item, Mapping) or "verdict" not in item:
            n_invalid += 1
            continue
        verdict = str(item.get("verdict"))
        scores = item.get("scores") or {}
        # R-01 报告列（AX-1①②③+B3）：spec_score/hidden_summary/grader_
        # notes/ood_flag 逐任务透传——缺键如实 None/False（老结果形态兼容，
        # 缺就是不缺，不编数）。
        ood_raw = item.get("ood_flag")
        tasks.append({
            "task_id": item.get("task_id"), "family": item.get("family"),
            "verdict": verdict, "ok": bool(item.get("ok")),
            "verdict_by_criterion": {
                str(k): str(v.get("verdict"))
                for k, v in scores.items() if isinstance(v, Mapping)},
            "evidence_path": item.get("evidence_path"),
            "spec_score": item.get("spec_score"),
            "hidden_summary": item.get("hidden_summary"),
            "grader_notes": item.get("grader_notes"),
            "ood_flag": bool(ood_raw) if ood_raw is not None else False,
        })
        if verdict == "pass":
            n_pass += 1
        elif verdict == "fail":
            n_fail += 1
        else:
            n_unknown += 1
    n_tasks = n_pass + n_fail + n_unknown
    # AX-1② spec_score 聚合口径：均值只对已得分任务（spec_score 非 None）
    # ——全 unknown/无判定面的任务不进均值分子分母（缺席是缺席，不编 0）。
    spec_vals = [float(t["spec_score"]) for t in tasks
                 if isinstance(t.get("spec_score"), (int, float))
                 and not isinstance(t.get("spec_score"), bool)]
    spec_score_block: dict[str, Any] = {
        "mean": (sum(spec_vals) / len(spec_vals)) if spec_vals else None,
        "n_scored": len(spec_vals),
        "basis": "spec score 部分分（失败设计按通过检查数占比 0~1；unknown "
                 "判据不进分子分母；verdict 语义零变——仅报告列，#122 不凑绿）",
    }
    return {
        "schema_version": BENCH_SCHEMA_VERSION,
        "n_tasks": n_tasks, "n_pass": n_pass, "n_fail": n_fail,
        "n_unknown": n_unknown, "n_invalid": n_invalid,
        "spec_score": spec_score_block,
        "three_metrics": {
            "success_rate": {
                "value": (n_pass / n_tasks) if n_tasks else None,
                "basis": "n_pass/n_tasks（ChatCFD 执行成功率口径，任务级；fail/unknown 计分母）"},
            "interface_failure_rate": {
                "value": None,
                "basis": "口径依赖失败分类面（内部档，不在公开树）——公开面如实 None"
                         "（铁律 7 同族：缺就是不缺，不编数）"},
            "token_cost": {
                "value": None,
                "basis": "无计费账本——成本轴缺数据如实 None 不编数（铁律 7 同族）"},
        },
        "failure_counts": {"pass": n_pass, "fail": n_fail,
                           "unknown": n_unknown},
        "tasks": tasks,
    }


# ---------------------------------------------------------------------------
# 首批 8 任务定义（骨架 task 集；阈值全部预声明）
# ---------------------------------------------------------------------------

#: −3.0103dB 理想等分相对偏差上限（campaign closedform_match；fake 闭式
#: 模型实测 ~8%，锚带宽预声明 10%——#207 回归锚口径）。
_CAMPAIGN_SPLIT_DEV_MAX = 0.10
#: campaign 质量杆（gate_pass；s11_db_min_in_band 上限，fake 模型实测
#: −18.4dB，预声明 −15dB——Wilkinson 验收回损口径）。
_CAMPAIGN_S11_MIN_DB = -15.0
#: 综合回代自洽相对偏差上限（syn-mline/syn-cpw/layered-stack-synthesis；
#: 4 位小数线宽舍入后实测 ~1e-4 量级，预声明 1%——E6a ΔZ0≤0.5Ω 同族口径
#: 的相对化；layered_stack 侧 design_params 内建独立裁判 1e-9Ω 实测 ~1e-11，
#: 本阈值=锚漂移回归门带宽）。
_SYN_DEV_MAX = 0.01
#: afs-fsv-quality 预声明锚（改动阈值=改门口径，须同笔更新本 docstring 与
#: tests/unit/test_em_bench.py 断言）：
#: - FSV GDM 等级上限（fsv_grade 阈值）=2——IEEE 1597.1 VG 档下标 ≤2
#:   （源锚 tests/unit/test_afs_service.py：numpy 2.5.4 环境下 GDM grade
#:   1→2，aurora_q 终门三连红后定谳 ≤2；原 ≤1 为 numpy 2.4.x 口径）。
_AFS_FSV_GRADE_MAX = 2
#: - afs-fsv-quality 缩减子判据（success_rate 阈值=1.0）：子判据
#:   reduction_ratio ≥ afs_service.REDUCTION_RATIO_MIN(0.5，§10.20 补强⑩)
#:   必须成立（n_ok/n_total=1/1；比值本体进 runner detail 供审计）。
_AFS_REDUCTION_RATE_MIN = 1.0
#: - afs-fsv-quality 合成多谐振规格缺省（=test_afs_service._SPEC 同款锚：
#:   2.4/3.1GHz 双陷波+2% 带内纹波）。
_AFS_SPEC_DEFAULT = "2.4:40;3.1:60;ripple=0.02"
#: - afs-fsv-quality 频带缺省（GHz；=test_afs_service._BAND 同款锚）。
_AFS_BAND_GHZ_DEFAULT = (1.0, 4.0)

# ── suspended-stripline-anchor 预声明锚（Q-X22；改动阈值=改门口径，须同笔
#    更新本 docstring 与 tests/unit/test_em_bench.py 断言；fd_convergence
#    阈值不经本块——default_bench_tasks 直引内核 LADDER_RESIDUAL_MAX 单源）：

#: 三方一致性闭式界（three_way_consistency 内界）：|闭式−FD|/FD ≤1.5%
#: （Q-X20 judge_result 实测 +1.14%；1.5% 带=闭式锚漂移回归门带宽，#207 口径
#: ——FD 收敛真值 εeff=1.58537 为基准，w2f 角点族闭式系统性偏 +0.4~+1.3%）。
_SSL_CLOSED_DEV_MAX = 0.015
#: 三方一致性 HFSS implied 界（three_way_consistency 外界=任务阈值）：
#: |HFSS implied−FD|/FD ≤2%（Q-X20 实测 +0.29%；HFSS=对齐基准，2% 带=
#: 外部实测锚读数分辨率带宽）。
_SSL_HFSS_DEV_MAX = 0.02
#: 资格锚容差（#300 裁判先过已知基准；冻结线沿内核/已验证裁判先例）：
#: Cohn 空气带状线外推 rel ≤0.5%（kernel cohn_air_anchor docstring 冻结合格线）。
_SSL_COHN_REL_MAX = 5e-3
#: 独立网格族交叉对拍 rel ≤2e-3（test_suspended_stripline_fd_judge 同款冻结线）。
_SSL_CROSS_CHECK_REL_MAX = 2e-3
#: 构造恒等（h→b 全填充 εeff=εr / εr=1 恒等 εeff=1）逐位容差（浮点保险带）。
_SSL_EXACT_IDENTITY_TOL = 1e-12

# ── ssl_race / ssl_g5 / ssl_matrix 预声明锚（Q-X43 / aurora_q；改动阈值=
#    改门口径，须同笔更新本 docstring 与 tests/unit/test_em_bench.py 断言）：

#: param_race 变体轴键闭集（4 参数单轴扰动——插入序=枚举序）。
_SSL_RACE_AXES: tuple[str, ...] = ("w_mm", "b_mm", "h_mm", "eps_r")
#: param_race 变体扰动因子闭集（±10%/±20%；单轴扰动——每变体恰好动一轴）。
_SSL_RACE_FACTORS: tuple[float, ...] = (-0.2, -0.1, 0.1, 0.2)
#: G5 over_unity_count 冻结门（Q-X27 冻结零容差口径 over_unity==0；#122：
#: 阈值预声明，缺/改=改门口径。as-recorded 基准 306 点超域如实 FAIL——
#: 门设计面矛盾（零容差 vs 提取偏置底）Q-X25 §3 已登记，本任务不修门）。
_G5_OVER_UNITY_MAX = 0
#: G5 passivity_max 门（Q-X25 门设计面：能量面由本门覆盖——Q-X19 修复后
#: 实测 1.0142 ≤1.05 门内余量 25%）。
_G5_PASSIVITY_MAX = 1.05
#: G5 passivity 超单位上限（closedform_match 阈值；deviation=
#: passivity_max−1.0 带符号超单位余量，欠单位=合法损耗态非违例）。
_G5_PASSIVITY_EXCESS_MAX = 0.05
#: ssl_g5 g5_stats 键闭集（必填 2+可选 4；未知键 fail-closed）。
_G5_STATS_KEYS: frozenset[str] = frozenset({
    "over_unity_count", "passivity_max",
    "variant_split", "attribution", "peak_band_ghz", "source",
})
#: 综合矩阵采样轴值枚举表（(b, h, εr) 三轴各 2 值，笛卡尔 2³=8 组；轴值=
#: G3 中心（b=0.50/h=0.05/εr=11.9，Q-X20 冻结锚）±10% 显式字面量——
#: 预声明枚举表非现场推算；w 由综合面按目标 Z0 反解（四维完备点）。
#: 轴声明序=枚举序。
_SSL_MATRIX_AXES: tuple[tuple[str, float, float], ...] = (
    ("b_mm", 0.45, 0.55),
    ("h_mm", 0.045, 0.055),
    ("eps_r", 10.71, 13.09),
)

# ── layered-stack-verdict / suspended-stripline-rereverify 预声明锚
#    （Q-X55 / aurora_q；改动阈值=改门口径，须同笔更新本 docstring 与
#    tests/unit/test_em_bench.py·test_em_bench_qx55.py 断言）：

#: layered_stack 判读行必需键闭集（对照/分解消费面；缺席 fail-closed）。
_QX26_ROW_REQUIRED_KEYS: tuple[str, ...] = (
    "name", "verdict", "not_judged", "geometry", "mesh_base_mm",
    "mesh_cells", "window_ps", "port_structure_suspect", "s0_status",
    "over_unity_cnt", "eps_eff_med", "eps_eff_closed", "eps_eff_rel",
)
#: layered_stack 双档对照缺省任务数据：Q-X26 comparison_table.json 三档
#: as-recorded **冻结快照**（runs/aurora_q/qx26_verdict/
#: comparison_table.json tiers 判读消费面投影——判读行全键原值，null 观察
#: 项（g1/g2/g3_status 等判读面不消费的 13 键）省略；出处=行内 source 键
#: 随行。runs/ 湖 gitignored——快照常量随行登记出处，不运行时读湖，同
#: Q-X27 判读单源快照常量纪律）。闭式锚 eps_eff_closed=1.6007603731686557
#: （Q-X10 判据单源 closed_form_anchor 实测冻结值，qx26 对照表同值）。
_QX26_CLOSED_EPS_EFF = 1.6007603731686557
_QX26_TIERS_SNAPSHOT: dict[str, dict[str, Any]] = {
    "C_qx10_prefix": {
        "name": "C_qx10_prefix", "verdict": "INCOMPLETE", "not_judged": False,
        "g0_status": None, "s0_status": None, "s0_failed": [],
        "port_structure_suspect": False, "truncation_suspect": True,
        "over_unity_cnt": 66, "eps_eff_med": 0.6289880702628833,
        "eps_eff_closed": 1.6007603731686557,
        "eps_eff_rel": 0.6070691898639264, "mesh_base_mm": 0.04,
        "mesh_cells": 4599980, "dt_fs": 12.253783221768696,
        "nrts": 51000, "window_ps": 624.9429443102035,
        "geometry": "pre-fix",
        "source": "qx11_server/comparison_a_vs_c.json C_qx10（Q-X11 收割"
                  "存档；原判=Q-X10 pre-S0 判读函数；修复前几何）",
    },
    "C_qx10_postfix": {
        "name": "C_qx10_postfix", "verdict": "INCOMPLETE", "not_judged": False,
        "g0_status": "PASS", "s0_status": "TRIGGER",
        "s0_failed": ["beta_linearity_r2", "port_agreement"],
        "port_structure_suspect": True, "truncation_suspect": False,
        "over_unity_cnt": 0, "eps_eff_med": 1.8316975055804328,
        "eps_eff_closed": 1.6007603731686557,
        "eps_eff_rel": 0.14426714721494768, "mesh_base_mm": 0.04,
        "mesh_cells": 4599980, "dt_fs": 12.253783221768696,
        "nrts": 51000, "window_ps": 624.9429443102035,
        "geometry": "post-fix",
        "source": "qx10_smoke/verdict.json+nominal/stats.json（Q-RM-3 修复"
                  "后 C 档本地重跑；判读=Q-X14 S0 版冻结函数）",
    },
    "A_qx11_prefix": {
        "name": "A_qx11_prefix", "verdict": "INCOMPLETE", "not_judged": False,
        "g0_status": "PASS", "s0_status": "TRIGGER",
        "s0_failed": ["port_agreement", "zl_plausible"],
        "port_structure_suspect": True, "truncation_suspect": False,
        "over_unity_cnt": 201, "eps_eff_med": 9.01445320007663,
        "eps_eff_closed": 1.6007603731686557,
        "eps_eff_rel": 4.63135704204921,
        "mesh_base_mm": 0.01655342703385268, "mesh_cells": 26987400,
        "dt_fs": 9.297037451221739, "nrts": 135000,
        "window_ps": 1255.1000559149347, "geometry": "pre-fix",
        "source": "qx11_server/a_auto/ 镜像（2026-11-07 收割回拉 launch_rc=0；"
                  "本席以现行 S0 版冻结函数重判——见 rejudge_a_prefix_s0.json）",
    },
}
#: ssl_rereverify G3 双基准最坏相对偏差阈值（closedform_match）：0.05=
#: G3_PARTIAL 冻结带承袭（tests/unit/test_suspended_anchor_verdict
#: G3_PASS=0.02/G3_PARTIAL=0.05 不放宽——非 FAIL 上界语义：重验态 G3
#: 判 PARTIAL 属冻结门内态非违例）。
_QX55_REREVERIFY_G3_REL_MAX = 0.05


def _ssl_geometry_validated(geo: Mapping[str, Any], *,
                            context: str) -> dict[str, float]:
    """悬置带线几何四键域检（正有限 + εr≥1 + h≤b；fail-closed 不猜）。

    ssl_race/ssl_matrix 族共用（Q-X43）；existing _run_ssl_anchor 的内联
    校验保持原样（只增纪律不重构已收官面）。返回收敛后的 float dict。
    """
    vals: dict[str, float] = {}
    for key in ("w_mm", "b_mm", "h_mm", "eps_r"):
        num = _finite_number(geo.get(key))
        if num is None or num <= 0:
            raise ValueError(
                f"ssl 任务 input_spec.{context}.{key} 必填且为正有限数值，"
                f"得到 {geo.get(key)!r}")
        vals[key] = num
    if vals["eps_r"] < 1.0:
        raise ValueError(
            f"ssl 任务 input_spec.{context}.eps_r={vals['eps_r']!r} 必须 ≥1.0"
            "（闭式定义域 εr≥1）")
    if vals["h_mm"] > vals["b_mm"]:
        raise ValueError(
            f"ssl 任务 input_spec.{context}.h_mm={vals['h_mm']!r} 不得大于 "
            f"b_mm={vals['b_mm']!r}（基板不得越出接地板腔）")
    return vals


def _ssl_race_variant_table(center: Mapping[str, float]) -> list[dict[str, Any]]:
    """param_race 确定性枚举表（纯函数）：中心几何 × 轴闭集 × 因子闭集 →
    16 变体（轴插入序×因子升序；每变体恰好单轴扰动）。枚举后逐变体域检
    （扰动不得越 h≤b/εr≥1/正有限域——越界 ValueError 带变体 id，fail-closed
    在 FD 执行前）。"""
    out: list[dict[str, Any]] = []
    for axis in _SSL_RACE_AXES:
        for factor in _SSL_RACE_FACTORS:
            geo = {k: float(center[k]) for k in
                   ("w_mm", "b_mm", "h_mm", "eps_r")}
            geo[axis] = float(center[axis]) * (1.0 + factor)
            pct = round(factor * 100)
            vid = f"{axis}{pct:+d}pct"
            bad = [k for k in ("w_mm", "b_mm", "h_mm", "eps_r")
                   if not (geo[k] > 0.0 and math.isfinite(geo[k]))]
            if bad or geo["eps_r"] < 1.0 or geo["h_mm"] > geo["b_mm"]:
                raise ValueError(
                    f"param_race 变体 {vid} 扰动越闭式/FD 定义域"
                    f"（非法键={bad or ('eps_r' if geo['eps_r'] < 1.0 else 'h>b')}，"
                    f"geometry={geo}）——调整 geometry_center 或因子闭集")
            out.append({"variant_id": vid, "axis": axis, "factor": factor,
                        "geometry": geo})
    return out


def _ssl_matrix_combos() -> list[tuple[float, float, float]]:
    """综合矩阵 8 组 (b, h, εr) 笛卡尔采样（纯函数；轴声明序×轴值序——
    确定性枚举表，:data:`_SSL_MATRIX_AXES` 单源）。"""
    axes = [(lo, hi) for _, lo, hi in _SSL_MATRIX_AXES]
    return [(b, h, e) for b in axes[0] for h in axes[1] for e in axes[2]]


def default_bench_tasks() -> list[BenchTask]:
    """首批 15 任务（R10 空白地图 P1 位骨架 task 集；Q-X15 扩容 6→8；
    Q-X22 扩容 8→9：suspended-stripline-anchor——Q-X20 FD 静流第三方裁判
    接入 bench，跨引擎三方判据；Q-X43 扩容 9→12：anchor 覆盖面三件——
    suspended-stripline-param-race（param_race 变体批量）/ssl-g5-attribution
    （G5 归因数据 as-recorded 基准）/suspended-stripline-synthesis-matrix
    （综合变体矩阵）；Q-X55 扩容 12→15：branchline-campaign（campaign 第
    二器件族，prompt 型缺省变体枚举表随 ：data:`DEFAULT_PROMPT_VARIANTS`
    落面）/layered-stack-verdict（Q-X26 双档对照判读服务消费，as-recorded
    三档冻结快照）/suspended-stripline-rereverify（Q-X27 三态对照判读单源
    消费，as-recorded 基准）；全离线确定性执行）。

    判据阈值全部预声明（本函数即预声明锚；改动阈值=改门口径，须同笔
    更新本 docstring 与 tests/unit/test_em_bench.py 对应断言）。
    """
    from rfauto.core.suspended_stripline_fd_judge import LADDER_RESIDUAL_MAX
    from rfauto.service.kicad_sch_service import SCH_SPEC_SCHEMA

    return [
        BenchTask(
            task_id="syn-mline",
            family="synthesis",
            title="微带线闭式综合（E6a 锚模板）",
            input_spec={"kind": "mline",
                        "params": {"z0_ohm": 50.0, "freq_ghz": 2.5}},
            criteria=[BenchCriterion(name="closedform_match", threshold=_SYN_DEV_MAX)],
            envelope={
                "z0_ohm": EnvelopeBound(min=40.0, max=120.0),
                "freq_ghz": EnvelopeBound(min=0.5, max=10.0),
            },
            data_source="core/synthesis.synthesize_mline_model（skrf HJ 闭式内核）"
                        "回代自洽——#1c 线宽禁手抄，数值只出综合内核；"
                        "envelope=E6a 锚模板训练包络声明（B3：z0∈[40,120]Ω/"
                        "freq∈[0.5,10]GHz——HJ 综合内核经验适用域声明值，"
                        "越界 ood_flag=true 不改 verdict）",
        ),
        BenchTask(
            task_id="syn-cpw",
            family="synthesis",
            title="共面波导（CPWG 口径）闭式综合",
            input_spec={"kind": "cpw",
                        "params": {"z0_ohm": 50.0, "gap_mm": 0.2, "freq_ghz": 2.5,
                                   "er": 3.66, "h_mm": 0.508}},
            criteria=[BenchCriterion(name="closedform_match", threshold=_SYN_DEV_MAX)],
            data_source="core/synthesis.synthesize_cpw_model（共形映射闭式 _cpwg_ri，"
                        "#193 CPWG 参照系口径）回代自洽",
        ),
        BenchTask(
            task_id="wilkinson-campaign",
            family="campaign",
            title="Wilkinson 功分器设计链+代理寻优战役（第 8 环发起）",
            input_spec={"prompt": "设计一个 2.4GHz 50 欧姆威尔金森功分器"},
            criteria=[
                BenchCriterion(name="closedform_match", threshold=_CAMPAIGN_SPLIT_DEV_MAX),
                BenchCriterion(name="gate_pass", threshold=_CAMPAIGN_S11_MIN_DB),
            ],
            data_source="level2_design.design_chain（fake 闭式模型回归锚，#207 口径："
                        "非物理基准，锚漂移=回归门敏感度）+ run_surrogate_loop "
                        "（fake 采样器/seed=42/小预算，离线确定性）",
        ),
        BenchTask(
            task_id="kicad-sch-roundtrip",
            family="kicad_sch",
            title="KiCad 原理图生成 round-trip 二值证书（+ERC）",
            input_spec={
                "spec": {
                    "schema": SCH_SPEC_SCHEMA,
                    "components": [
                        {"ref": "R1", "value": "10k", "lib_id": "Device:R"},
                        {"ref": "R2", "value": "20k", "lib_id": "Device:R"},
                    ],
                    "nets": [
                        {"name": "VIN", "pins": [{"ref": "R1", "pin": "1"}]},
                        {"name": "MID", "pins": [{"ref": "R1", "pin": "2"},
                                                 {"ref": "R2", "pin": "1"}]},
                        {"name": "GND", "pins": [{"ref": "R2", "pin": "2"}]},
                    ],
                },
                "run_erc": True,
            },
            criteria=[BenchCriterion(name="certificate_pass", threshold=None),
                      BenchCriterion(name="erc_clean", threshold=0)],
            data_source="kicad_sch_service.generate_schematic+round_trip_certificate"
                        "（Q-CAD-2 通用件跨域复用，Weave 二值证书）；ERC=kicad-cli"
                        " 子进程（缺席如实 unknown 不凑分）",
        ),
        BenchTask(
            task_id="vendor-search",
            family="vendor_search",
            title="厂商文档 FTS5 检索命中（内联语料 fixture）",
            input_spec={
                "corpus": {
                    "hfss_basics.html":
                        "<html><body><h1>HFSS 基础</h1>"
                        "<p>波导端口设置与阻抗匹配基础，wave port 与 lumped port 的区别。</p>"
                        "</body></html>",
                    "ads_sim.html":
                        "<html><body><h1>ADS 仿真入门</h1>"
                        "<p>VSWR 与 smith 圆图读数方法，S 参数仿真基础。</p>"
                        "</body></html>",
                },
                "queries": [
                    {"query": "波导", "expect": ["波导"]},    # <3 字 CJK → LIKE 回退通道
                    {"query": "vswr", "expect": ["vswr"]},    # trigram MATCH 通道
                    {"query": "smith", "expect": ["smith"]},
                ],
                "limit": 5,
            },
            criteria=[BenchCriterion(name="success_rate", threshold=1.0)],
            grader_notes=BenchGraderNotes(
                correct_core=[
                    "命中=该查询 expect 全部词出现在 top-k 结果的 "
                    "title/path/snippet 拼串（小写化）——预声明命中语义",
                    "trigram MATCH 与 <3 字 CJK LIKE 回退两通道均视为合法命中面",
                ],
                common_errors=[
                    "部分词命中（expect 词只中一部分）≠命中——hit_terms 缺词即该查询 fail",
                    "大小写漂移（expect 词大小写敏感词面未小写化比对）",
                ],
                partial_credit="spec_score=命中查询数/总查询数（success_rate "
                               "判据同一分子分母；unknown 查询不计）",
            ),
            negative_variants=[
                BenchNegativeVariant(
                    variant_id="noop-queries-absent-terms",
                    input_spec={
                        "corpus": {
                            "hfss_basics.html":
                                "<html><body><h1>HFSS 基础</h1>"
                                "<p>波导端口设置与阻抗匹配基础，wave port 与 lumped port 的区别。</p>"
                                "</body></html>",
                            "ads_sim.html":
                                "<html><body><h1>ADS 仿真入门</h1>"
                                "<p>VSWR 与 smith 圆图读数方法，S 参数仿真基础。</p>"
                                "</body></html>",
                        },
                        "queries": [
                            {"query": "不存在词xyzq", "expect": ["不存在词xyzq"]},
                        ],
                        "limit": 5,
                    },
                    note="反例：期望词不在语料（投机解/空检索/幻觉命中必须判 fail"
                         "——success_rate=0/1<1.0；AX-1④ 反例集缺省任务实证面）",
                ),
            ],
            data_source="vendor_doc_service.build_vendor_index+search_vendor_docs"
                        "（FTS5 trigram；厂商内容零入库红线——语料=任务内联 fixture）；"
                        "negative_variants=语料外期望词反例（AX-1④——空命中投机解"
                        "必败自检面，check_negative_variants 消费）",
        ),
        BenchTask(
            task_id="layered-stack-synthesis",
            family="synthesis",
            title="layered_stack 模板族名义设计点反解（Z0 目标→strip 宽；76 族新成员接入 bench）",
            input_spec={"kind": "layered_stack", "params": {"z0_ohm": 50.0}},
            criteria=[BenchCriterion(name="closedform_match", threshold=_SYN_DEV_MAX)],
            data_source="adapters/layered_stack_spec.design_params（Z0 目标→strip 宽二分"
                        "反解+独立裁判 |ΔZ0|≤DESIGN_Z0_JUDGE_OHM=1e-9Ω，#118 家法——"
                        "铁律 7 确定性内核数值零手拍）；锚=晶圆键合反馈 §2.1 实测"
                        "（w=0.52→Z0≈50.2，HFSS |S11|max=-23.5dB 背书 50Ω 点）；"
                        "bench 层 closedform_match=锚漂移回归门（#207 口径）",
        ),
        BenchTask(
            task_id="afs-fsv-quality",
            family="afs_sweep",
            title="AFS 自适应频扫质量（合成多谐振 SV-5 六步；FSV 等级+缩减双判据）",
            input_spec={"spec": _AFS_SPEC_DEFAULT,
                        "band_ghz": list(_AFS_BAND_GHZ_DEFAULT), "tol": 0.02},
            criteria=[
                BenchCriterion(name="fsv_grade", threshold=_AFS_FSV_GRADE_MAX),
                BenchCriterion(name="success_rate", threshold=_AFS_REDUCTION_RATE_MIN),
            ],
            data_source="afs_service.synthetic_multiresonance_response×afs_sweep"
                        "（确定性解析回调零真机零随机；SV-5 伪误差自适应频扫）；"
                        "fsv_grade 阈值=2 锚=test_afs_service numpy 2.5.4 口径"
                        "（VG 档，aurora_q 终门实证）；success_rate=缩减子判据"
                        "（reduction_ratio≥REDUCTION_RATIO_MIN=0.5，§10.20 补强⑩）",
        ),
        BenchTask(
            task_id="suspended-stripline-anchor",
            family="ssl_anchor",
            title="悬置带线 G3 锚点三方判据（FD 收敛真值+闭式+HFSS implied；资格锚全量）",
            input_spec={
                "geometry": {"w_mm": 0.52, "b_mm": 0.50, "h_mm": 0.05,
                             "eps_r": 11.9},
                "hfss_implied": {"eps_eff": 1.59, "z0_ohm": 50.2},
            },
            criteria=[
                BenchCriterion(name="fd_convergence",
                               threshold=LADDER_RESIDUAL_MAX),
                BenchCriterion(name="gate_pass", threshold=None),
                BenchCriterion(name="closedform_match",
                               threshold=_SSL_CLOSED_DEV_MAX),
                BenchCriterion(name="three_way_consistency",
                               threshold=_SSL_HFSS_DEV_MAX),
            ],
            data_source="core/suspended_stripline_fd_judge（Q-X20 FD 静流第三方"
                        "裁判，只读零改动：六级阶梯+三点 Richardson 外推+8 预声明"
                        "门，FD 收敛真值 εeff=1.58537/Z0=50.482 实测锚）+资格锚"
                        "全量（Cohn 空气带状线/构造恒等/独立网格族交叉对拍——#300"
                        "裁判先过已知基准）+闭式腿 _suspended_stripline_ri（被裁判"
                        "对象现场重算，Q-X20 实测偏 +1.14%）+HFSS implied 外部"
                        "实测锚 1.59/50.2Ω（qx9 spec.md §1 引述，"
                        "suspended_stripline_judge_service 冻结常量同源）；"
                        "fd_convergence 阈值=内核 LADDER_RESIDUAL_MAX=1e-3 单源"
                        "直引；闭式界 1.5%/HFSS 界 2%=预声明锚（Q-X22）",
        ),
        BenchTask(
            task_id="suspended-stripline-param-race",
            family="ssl_race",
            title="悬置带线 anchor param_race 变体批量（4 参数 ±10%/±20% 单轴"
                  "扰动 16 变体；fd_convergence+closedform_match 双判据最坏聚合）",
            input_spec={
                "geometry_center": {"w_mm": 0.52, "b_mm": 0.50, "h_mm": 0.05,
                                    "eps_r": 11.9},
            },
            criteria=[
                BenchCriterion(name="fd_convergence",
                               threshold=LADDER_RESIDUAL_MAX),
                BenchCriterion(name="closedform_match",
                               threshold=_SSL_CLOSED_DEV_MAX),
            ],
            data_source="确定性枚举表 _SSL_RACE_AXES×_SSL_RACE_FACTORS（4×4=16 "
                        "单轴扰动变体，轴插入序×因子序）×逐变体 judge_ladder "
                        "全链（Q-X20 FD 内核只读消费）+闭式腿现场重算；批量判据"
                        "=逐变体最坏聚合（上界极性 max——任一变体不达标即任务"
                        "不达标）；fd_convergence 阈值=内核 LADDER_RESIDUAL_MAX"
                        " 单源直引、闭式界 1.5%=预声明锚 _SSL_CLOSED_DEV_MAX；"
                        "Q-X43 探针实测批量数字带 residual_max∈[3.3e-4,5.5e-4]/"
                        "|dev|∈[0.75%,1.38%]（runs/aurora_q/qx43_stats/"
                        "probe_numbers.json）",
        ),
        BenchTask(
            task_id="ssl-g5-attribution",
            family="ssl_g5",
            title="悬置带线 G5 归因数据基准（Q-RM-4 over_unity=306 as-recorded "
                  "如实基准；over_unity 零容差门+passivity 超单位门）",
            input_spec={
                "g5_stats": {
                    "over_unity_count": 306,
                    "passivity_max": 1.0142,
                    "variant_split": {"shield": 98, "open": 208},
                    "peak_band_ghz": 10.0,
                    "attribution": "fixed_50ohm_ref_port_wave_extraction_bias",
                    "source": "runs/aurora_q/qx25_verify/VERIFY_REPORT.md §2 "
                              "逐点谱复算（306=shield 98+open 208 逐位一致，"
                              "全部 S21 列、S11 零超一）+qx27_rereverify/"
                              "REPORT.md G5 行",
                },
            },
            criteria=[
                BenchCriterion(name="gate_pass", threshold=None),
                BenchCriterion(name="closedform_match",
                               threshold=_G5_PASSIVITY_EXCESS_MAX),
            ],
            data_source="Q-RM-4 G5 带缘噪声 as-recorded 基准任务化（Q-X43）："
                        "over_unity_count=306 外部实测/复算锚声明（Q-X25 谱分析"
                        "归因=固定 50Ω 参考下端口波分解提取系统偏置非带缘盲区；"
                        "战役账'线端 nm 入网盲区'归因不被谱证据支持）；判据双门"
                        "阈值预声明：over_unity 零容差=Q-X27 冻结口径 "
                        "_G5_OVER_UNITY_MAX=0（306 点超域如实 FAIL 不凑绿——"
                        "门设计面矛盾 Q-X25 §3 登记不修门）+passivity_max≤1.05"
                        "（_G5_PASSIVITY_MAX，Q-X19 修复后实测 1.0142 门内余量 "
                        "25%，deviation=超单位带符号余量阈值 0.05）",
        ),
        BenchTask(
            task_id="suspended-stripline-synthesis-matrix",
            family="ssl_matrix",
            title="悬置带线综合变体矩阵（(b,h,εr) 笛卡尔 2³=8 组×综合面反解 w"
                  "×FD 裁判双通道；three_way 一致性批量）",
            input_spec={"z0_target_ohm": 50.0},
            criteria=[
                BenchCriterion(name="fd_convergence",
                               threshold=LADDER_RESIDUAL_MAX),
                BenchCriterion(name="closedform_match",
                               threshold=_SSL_CLOSED_DEV_MAX),
                BenchCriterion(name="three_way_consistency",
                               threshold=_SSL_HFSS_DEV_MAX),
            ],
            data_source="采样枚举表 _SSL_MATRIX_AXES（(b,h,εr) 三轴 G3 中心 "
                        "±10% 显式字面量 2³=8 组）→综合面闭式反解 w（core 内核 "
                        "suspended_stripline_synthesis brentq 回代自洽，目标 "
                        "Z0=50Ω 声明值）→逐点 judge_ladder 全链+闭式腿现场重算"
                        "双通道对照；three_way 第二腿（fd_vs_hfss 键位）=综合"
                        "目标 Z0 腿（z0_target/FD Z0−1——矩阵变体无外部实测锚，"
                        "如实取声明设计目标值非 HFSS 实测，leg_semantics 双声明"
                        "）；fd/闭式阈值同 anchor 单源；批量最坏聚合（three_way "
                        "逐腿跨点独立取最坏）；Q-X43 探针实测批量数字带 "
                        "residual_max∈[3.5e-4,4.1e-4]/|dev_closed|∈[1.07%,"
                        "1.29%]/|dev_target|∈[0.43%,0.53%]"
                        "（runs/aurora_q/qx43_stats/probe_numbers.json）",
        ),
        # ── Q-X55 扩容三件（12→15）───────────────────────────────────────
        BenchTask(
            task_id="branchline-campaign",
            family="campaign",
            title="分支线电桥设计链+代理寻优战役（campaign 第二器件族；"
                  "prompt 型缺省变体随 DEFAULT_PROMPT_VARIANTS）",
            input_spec={"prompt": "设计一个 2.4GHz 50 欧姆分支线电桥，等分输出"},
            criteria=[
                BenchCriterion(name="closedform_match", threshold=_CAMPAIGN_SPLIT_DEV_MAX),
                BenchCriterion(name="gate_pass", threshold=_CAMPAIGN_S11_MIN_DB),
            ],
            data_source="level2_design.design_chain（branchline 关键词族路由+"
                        "run_surrogate_loop fake 采样器离线确定性）——判据="
                        "理想 3dB 等分闭式/−15dB 回损质量杆（与 wilkinson-campaign"
                        " 同款预声明带，10·log10(0.5)/S11 杆）；**fake branchline "
                        "闭式模型粗档 as-recorded 基准**：本席探针实测 "
                        "s21_db_at_dip=−5.280dB（dev≈0.754 超带）+"
                        "s11_db_min_in_band=−8.103dB（超杆）→ 双判据如实 FAIL "
                        "不凑绿（模型质量差距登记面，非达标声明；模型侧修复="
                        "后续席位事项）；prompt 变体=DEFAULT_PROMPT_VARIANTS"
                        "[本任务]（3 条同族措辞排列，族路由确定性）",
        ),
        BenchTask(
            task_id="layered-stack-verdict",
            family="layered_verdict",
            title="layered_stack 双档对照判读（Q-X26 对照判读服务消费；RC 三因子"
                  "分解+as-recorded 三档冻结快照）",
            input_spec={
                "tiers": _QX26_TIERS_SNAPSHOT,
                "closed_eps_eff": _QX26_CLOSED_EPS_EFF,
            },
            criteria=[
                BenchCriterion(name="closedform_match", threshold=0.02),
                BenchCriterion(name="gate_pass", threshold=None),
            ],
            data_source="layered_stack_verdict_service.compare_tiers+"
                        "decompose_factors（Q-X26 判读预备服务只读消费；判据"
                        "门限单源=runs/aurora_q/qx10_smoke/qx10_verdict.py "
                        "G1_PASS=0.02 承袭——本阈值=预声明锚）；input_spec."
                        "tiers=Q-X26 comparison_table.json 三档 as-recorded "
                        "冻结快照（C_qx10_prefix/C_qx10_postfix/A_qx11_prefix，"
                        "runs/ 湖 gitignored——快照常量 _QX26_TIERS_SNAPSHOT "
                        "随行登记出处不运行时读湖）；闭式锚 1.6007603731686557"
                        "=Q-X10 判据单源 closed_form_anchor 实测冻结值；"
                        "**as-recorded 基准如实 FAIL**（三档 INCOMPLETE、"
                        "eps_eff_rel 最坏 4.63、RC1 两档 implicated——判读预备"
                        "态登记面，A/C 档重发后再判）；gate_pass=RC 结构面门"
                        "（全部已判档 RC1==excluded ∧ RC3==excluded，"
                        "unevaluated 不算清白）",
        ),
        BenchTask(
            task_id="suspended-stripline-rereverify",
            family="ssl_rereverify",
            title="悬置带线双修复重验三态对照（Q-X19/Q-X21 修复后 Q-X27 判读"
                  "单源消费；as-recorded 基准）",
            input_spec={},
            criteria=[
                BenchCriterion(name="gate_pass", threshold=None),
                BenchCriterion(name="closedform_match",
                               threshold=_QX55_REREVERIFY_G3_REL_MAX),
            ],
            data_source="tests/unit/test_ssl_rereverify.py（Q-X27 判读纯函数"
                        "单源+三态 as-recorded 快照常量同文件，动态加载只读"
                        "零改动）全链消费：three_state_gate_table（Q-RM-1→"
                        "Q-RM-4→重验 2026-11-07 终态三态五门对照）+"
                        "g5_attribution_test（over_unity 306→180 drop=41.2% "
                        "落中带 MIXED_PARTIAL_DROP）+g3_basis_switch（G3 双"
                        "基准：闭式 1.60342 冻结锚+Q-X20 FD 真值 1.58537 旁证）"
                        "+expectation_check（预声明期望 6 hit/2 miss——G5 计数"
                        "分支与总判两 miss）；**as-recorded 基准如实 FAIL 不凑"
                        "绿**；closedform_match 阈值 0.05=G3_PARTIAL 冻结带"
                        "承袭（test_suspended_anchor_verdict 2%/5% 不放宽，"
                        "非 FAIL 上界语义）；发布包无 tests/ 时判读单源缺失"
                        "=fail-loud（诚实失败不静默）",
        ),
    ]


# ---------------------------------------------------------------------------
# 判据增强包（aurora_r R-01，AX-1+B3）：spec_score / no-op 探针单源 /
# B3 包络判定 / negative_variants 自检 / 任务准入门
# ---------------------------------------------------------------------------


def spec_score_from_scores(scores: Mapping[str, Any]) -> float | None:
    """spec score 部分分（AX-1②：code-a-chip 思想，思想级重写）——判据
    评定结果映射 → 通过检查数占比 0~1（纯报告列，verdict 语义零变）。

    口径（预声明）：分子=verdict=="pass" 的判据数；分母=verdict ∈
    {pass, fail} 的判据数（**unknown 不进分子也不进分母**——缺测不是
    通过也不是失败，#122 同族：缺席是缺席）；分母 0（全 unknown/空
    scores）→ None 如实缺席，不编 0 也不编 1。输入只读判定结果的
    verdict 键（其余键不消费）；非映射条目按 unknown 处理（多报不放过，
    #316 方向）。
    """
    judged: list[str] = []
    for v in scores.values():
        verdict = str(v.get("verdict")) if isinstance(v, Mapping) else "unknown"
        if verdict in ("pass", "fail"):
            judged.append(verdict)
    if not judged:
        return None
    return judged.count("pass") / len(judged)


#: no-op 探针"什么都不做的输出"单源（AX-1⑤：terminal-bench-science no-op
#: 必败门思想）。每判据的**空产出形态**确定性定义（judges 自检输入，非
#: 物理测度——不构成数值预言）：布尔/计数判据的空产出=未达成（fail 语义）；
#: 数值判据的空产出=缺测（unknown 既有语义不改——纯数值判据任务的 no-op
#: 探针如实 unknown，准入 quarantined 不凑）。新判据注册时同笔在此登记
#: no-op 形态（缺登记 → 探针回退 {} → unknown → 准入不凑，如实）。
NOOP_PROBE_MEASURES: dict[str, dict[str, Any]] = {
    "closedform_match": {},        # 无偏差测度 → unknown（缺测不编数）
    "gate_pass": {"passed": False, "gate": "noop_probe", "metric": None},
    "certificate_pass": {"passed": False, "n_diff": None},
    "erc_clean": {"available": False, "reason": "no-op 探针（通道未产出）"},
    "drc_count": {"available": False, "reason": "no-op 探针（通道未产出）"},
    "success_rate": {"n_ok": 0, "n_total": 1},   # 空产出=0 命中 → fail（阈值>0 时）
    "token_cost": {"available": False, "reason": "no-op 探针（无计费账本）"},
    "fsv_grade": {},               # 无等级测度 → unknown
    "fd_convergence": {},          # 无残差测度 → unknown
    "three_way_consistency": {},   # 无偏差测度 → unknown
}

#: oracle 稳定探针缺省重复次数（terminal-bench-science oracle×5 口径）。
ADMISSION_ORACLE_RUNS = 5

#: 准入状态词表（admitted=三探针全过 / quarantined=结构合法但探针未证明
#: / rejected=结构拒绝：schema/runner/阈值缺失）。
ADMISSION_STATUSES: tuple[str, ...] = ("admitted", "quarantined", "rejected")


def bench_envelope_point(input_spec: Mapping[str, Any] | None) -> dict[str, float]:
    """评估点提取（B3，确定性纯函数）：input_spec 内全部有限数值叶 →
    {键: 值} 平面映射。

    规则（预声明）：深度优先遍历 Mapping 值；bool/非数值/非有限叶跳过
    （#364）；键冲突**首现胜**（插入序=遍历序，确定性）；列表不下钻
    （包络消费标量参数域——逐元素包络未立项不猜）。缺省 None/空 →
    空点（包络判定全键 unverified，如实）。"""
    point: dict[str, float] = {}

    def _walk(node: Mapping[str, Any]) -> None:
        for k, v in node.items():
            key = str(k)
            num = _finite_number(v)
            if num is not None:
                if key not in point:
                    point[key] = num
            elif isinstance(v, Mapping):
                _walk(v)

    if isinstance(input_spec, Mapping):
        _walk(dict(input_spec))
    return point


def evaluate_bench_envelope(
    bounds: Mapping[str, Any],
    point: Mapping[str, Any],
) -> dict[str, Any]:
    """包络判定（B3，纯函数）：参数域 bounds × 评估点 → OOD 判定块。

    bounds = {参数键: EnvelopeBound 或同构 Mapping(min/max)}；point =
    :func:`bench_envelope_point` 产出的评估点。判定规则（预声明）：
    - 点内键值取有限数（bool/非有限→该键 unverified——不猜）；
    - 越界 = val < min（声明下界时）或 val > max（声明上界时）；
    - ood_flag = 违例数 > 0（**判定块只陈述事实，不改 verdict 本体**）；
    - 包络声明了但点内缺键/非数值 → unverified_keys 如实列出（未验证
      不判 OOD——不伪造）。

    Returns:
        ``{status: "declared", ood_flag: bool, violations: [{key, value,
        bound_min, bound_max}], checked_keys, unverified_keys}``。
    """
    violations: list[dict[str, Any]] = []
    checked: list[str] = []
    unverified: list[str] = []
    for key in bounds:  # 插入序=声明序（确定性）
        raw = point.get(key)
        val = _finite_number(raw)
        if val is None:
            unverified.append(str(key))
            continue
        b = bounds[key]
        if isinstance(b, Mapping):
            mn_raw, mx_raw = b.get("min"), b.get("max")
        else:
            mn_raw, mx_raw = getattr(b, "min", None), getattr(b, "max", None)
        mn = _finite_number(mn_raw)
        mx = _finite_number(mx_raw)
        checked.append(str(key))
        out = (mn is not None and val < mn) or (mx is not None and val > mx)
        if out:
            violations.append({"key": str(key), "value": val,
                               "bound_min": mn, "bound_max": mx})
    return {
        "status": "declared", "ood_flag": bool(violations),
        "violations": violations, "checked_keys": checked,
        "unverified_keys": unverified,
    }


def _envelope_block_for_task(bt: BenchTask) -> dict[str, Any]:
    """任务级 envelope 报告块（成功路径消费）：未声明 → absent 块；已声明
    → bench_envelope_point 提取评估点 + evaluate_bench_envelope 判定，
    评估点出处随块声明（provenance）。"""
    if bt.envelope is None:
        return _envelope_absent_block()
    block = evaluate_bench_envelope(bt.envelope, bench_envelope_point(bt.input_spec))
    if block["unverified_keys"] and not block["violations"]:
        block["note"] = ("包络键在评估点缺席/非数值（未验证——如实不判 OOD，"
                         "不伪造 ood_flag）")
    return block


def check_negative_variants(
    task: BenchTask | Mapping[str, Any],
    *,
    work_root: str | Path | None = None,
) -> dict[str, Any]:
    """反例集行为自检（AX-1④）：任务反例逐个走全管线，判据必须判 fail。

    "判据判 fail"口径（预声明，不凑绿）：pipeline ok=True 且
    stage="execute" 且 verdict=="fail"——三者缺一不算（执行崩溃的 fail
    是"没跑成"不是"判据判错答案"；validate 态 fail 是任务定义错误）。
    检查态三值：**pass**（全部反例 judged_fail）/ **unknown**（存在未
    judged_fail 的反例——判据退化或执行崩溃，如实登记不凑）/
    **absent**（任务未声明反例——缺席不是通过也不是失败）。

    Returns:
        ``{status, ok, n_variants, results: [{variant_id, verdict, stage,
        pipeline_ok, judged_fail, note, errors}], note}``。
    """
    try:
        bt = (task if isinstance(task, BenchTask)
              else BenchTask.model_validate(dict(task)))
    except Exception as exc:
        return {"status": "unknown", "ok": False, "n_variants": 0, "results": [],
                "note": f"任务 schema 校验失败，反例自检未运行: "
                        f"{type(exc).__name__}: {exc}"}
    variants = list(bt.negative_variants)
    if not variants:
        return {"status": "absent", "ok": True, "n_variants": 0, "results": [],
                "note": "任务未声明反例变体（absent——缺席如实，不伪造通过）"}
    results: list[dict[str, Any]] = []
    for v in variants:
        sub_root = (Path(work_root) / f"negative_{v.variant_id}"
                    if work_root is not None else None)
        r = run_bench_task(bt.model_copy(update={"input_spec": dict(v.input_spec)}),
                           work_root=sub_root)
        judged_fail = (bool(r.get("ok")) and str(r.get("verdict")) == "fail"
                       and str(r.get("stage")) == "execute")
        results.append({
            "variant_id": v.variant_id,
            "verdict": r.get("verdict"), "stage": r.get("stage"),
            "pipeline_ok": bool(r.get("ok")), "judged_fail": judged_fail,
            "note": v.note,
            "errors": [str(e) for e in (r.get("errors") or [])][:3],
        })
    all_fail = all(r["judged_fail"] for r in results)
    return {
        "status": "pass" if all_fail else "unknown",
        "ok": all_fail,
        "n_variants": len(results),
        "results": results,
        "note": ("全部反例判 fail（判据面反例门干净）" if all_fail else
                 "存在未判 fail 的反例（判据退化或执行崩溃——如实 unknown，"
                 "不凑绿；judged_fail 口径=ok∧execute∧verdict=fail）"),
    }


def _admit_probe_verdicts(
    bt: BenchTask,
    measures: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], str]:
    """准入探针共用判定：measures → 双层判据评定 + 聚合 verdict
    （visible+hidden 都算——准入探针是作者面自检，非报告面，隐藏层
    逐条结果在探针 detail 可见不属泄漏面）。"""
    scores = _evaluate_criteria(bt, measures)
    if bt.hidden_criteria:
        scores = {**scores, **_evaluate_criteria(bt, measures,
                                                 criteria=bt.hidden_criteria)}
    return scores, _aggregate_verdict(scores)


def admit_bench_task(
    task: BenchTask | Mapping[str, Any],
    *,
    oracle_measures: Mapping[str, Any],
    noop_measures: Mapping[str, Any] | None = None,
    oracle_runs: int = ADMISSION_ORACLE_RUNS,
    work_root: str | Path | None = None,
) -> dict[str, Any]:
    """任务准入门（AX-1⑤：terminal-bench-science 任务质量门思想，思想级
    重写）——三探针自检，返回结构化准入报告（不注册不落库，执行权在调用方）。

    探针（全部确定性，零 LLM）：

    1. **no-op 必败门**：把"什么都不做的输出"喂给判据必须得 fail。无输出
       形态按判据单源 :data:`NOOP_PROBE_MEASURES`（调用方可用
       ``noop_measures`` 显式覆盖——键=判据名；覆盖降不了门：喂出 pass
       照样不过）。布尔/计数判据空产出=fail；数值判据缺测=unknown（既有
       语义不改）→ 该任务准入 **quarantined**（如实：no-op 必败未证明，
       不是通过也不是拒绝）。
    2. **oracle 稳定探针**：调用方供给的已知好输出（measures 形态）重复判
       ``oracle_runs``（缺省 5，tbs oracle×5 口径）次——verdict 与逐判据
       结果（JSON 归一化）必须逐次一致（确定性判据的稳定性门），且首次
       verdict=="pass"（oracle 解必须过——"已知好输出"判不过=判据极性
       反转或输出给错，如实 quarantined）。
    3. **反例自检**：:func:`check_negative_variants`（同 AX-1④）——有反例
       判不出 fail → quarantined；无反例 → absent（不挡准入，如实记录）。

    准入三态：**admitted**（三探针全过）/ **quarantined**（结构合法但
    探针未证明——如实标记，调用方决定注册/隔离）/ **rejected**（结构
    拒绝：schema 校验失败/family 无 runner/预声明阈值缺失——任务定义层
    破损，probes 不运行）。

    Args:
        task: BenchTask 实例或同构 dict。
        oracle_measures: 已知好输出（判据 measures 形态——键=判据名）。
        noop_measures: no-op 输出显式覆盖（None=NOOP_PROBE_MEASURES 单源）。
        oracle_runs: oracle 重复判定次数（≥1）。
        work_root: 反例自检 cwd 隔离根（None=逐变体 tempfile）。

    Returns:
        准入报告 dict：``{task_id, family, status, admitted, probes,
        errors}``；probes={noop, oracle_stability, negative_variants}，
        各带 ok 标志与 note（如实登记项）。
    """
    raw_id = str(task.get("task_id") or "?") if isinstance(task, Mapping) else "?"
    raw_family = str(task.get("family") or "?") if isinstance(task, Mapping) else "?"
    try:
        bt = (task if isinstance(task, BenchTask)
              else BenchTask.model_validate(dict(task)))
    except Exception as exc:
        return {"task_id": raw_id, "family": raw_family, "status": "rejected",
                "admitted": False, "probes": {},
                "errors": [f"BenchTask schema 校验失败: "
                           f"{type(exc).__name__}: {exc}"]}
    if bt.family not in _RUNNER_REGISTRY:
        return {"task_id": bt.task_id, "family": bt.family, "status": "rejected",
                "admitted": False, "probes": {},
                "errors": [f"family={bt.family!r} 无注册 runner"
                           f"（已注册={list(_RUNNER_REGISTRY)}）"]}
    all_criteria = [*bt.criteria, *bt.hidden_criteria]
    missing = [c.name for c in all_criteria
               if c.name in THRESHOLD_REQUIRED and c.threshold is None]
    if missing:
        return {"task_id": bt.task_id, "family": bt.family, "status": "rejected",
                "admitted": False, "probes": {},
                "errors": [f"判据 {missing} 缺预声明阈值（#122；hidden 层同规）"]}
    if isinstance(oracle_runs, bool) or not isinstance(oracle_runs, int) \
            or oracle_runs < 1:
        raise ValueError(f"oracle_runs 必须 ≥1 整数，得到 {oracle_runs!r}")

    errors: list[str] = []
    # ── 探针① no-op 必败门 ────────────────────────────────────────────
    noop_src = dict(noop_measures) if noop_measures is not None else None
    noop_map = {
        c.name: (noop_src[c.name] if noop_src is not None and c.name in noop_src
                 else dict(NOOP_PROBE_MEASURES.get(c.name, {})))
        for c in all_criteria}
    noop_scores, noop_verdict = _admit_probe_verdicts(bt, noop_map)
    noop_ok = noop_verdict == "fail"
    if not noop_ok:
        errors.append(
            f"no-op 探针未判 fail（verdict={noop_verdict}；"
            + ("无输出按 NOOP_PROBE_MEASURES 缺测语义=unknown——数值判据任务"
               "的 no-op 必败未证明，如实 quarantined"
               if noop_verdict == "unknown" else
               "空产出被判据判 pass=空过判据（判据退化，最严重档）") + "）")
    # ── 探针② oracle 稳定 ─────────────────────────────────────────────
    oracle_verdicts: list[str] = []
    oracle_snapshots: list[str] = []
    for _ in range(oracle_runs):
        o_scores, o_verdict = _admit_probe_verdicts(bt, oracle_measures)
        oracle_verdicts.append(o_verdict)
        oracle_snapshots.append(
            json.dumps(o_scores, sort_keys=True, ensure_ascii=False))
    oracle_stable = (len(set(oracle_verdicts)) == 1
                     and len(set(oracle_snapshots)) == 1)
    oracle_verdict = oracle_verdicts[0]
    oracle_ok = oracle_stable and oracle_verdict == "pass"
    if not oracle_ok:
        if not oracle_stable:
            errors.append(
                f"oracle 稳定探针未过（{oracle_runs} 次判定不一致："
                f"{oracle_verdicts}）——确定性判据不得随跑漂移")
        else:
            errors.append(
                f"oracle 输出未判 pass（verdict={oracle_verdict}）——已知好"
                "输出判不过=判据极性反转或 oracle 输出给错（oracle 解必须过）")
    # ── 探针③ 反例自检 ────────────────────────────────────────────────
    neg = check_negative_variants(bt, work_root=work_root)
    neg_ok = bool(neg.get("ok")) and str(neg.get("status")) in ("pass", "absent")
    if not neg_ok:
        errors.append(f"反例自检未过（status={neg.get('status')}）——"
                      "有反例判不出 fail（判据退化）或反例执行崩溃")

    status = "admitted" if (noop_ok and oracle_ok and neg_ok) else "quarantined"
    return {
        "task_id": bt.task_id, "family": bt.family, "status": status,
        "admitted": status == "admitted",
        "probes": {
            "noop": {"ok": noop_ok, "verdict": noop_verdict,
                     "source": ("caller_declared" if noop_src is not None
                                else "NOOP_PROBE_MEASURES"),
                     "per_criterion": {k: str(v.get("verdict"))
                                       for k, v in noop_scores.items()}},
            "oracle_stability": {"ok": oracle_ok, "n_runs": oracle_runs,
                                 "stable": oracle_stable,
                                 "verdict": oracle_verdict,
                                 "verdicts": oracle_verdicts},
            "negative_variants": {"ok": neg_ok, "status": neg.get("status"),
                                  "n_variants": neg.get("n_variants"),
                                  "results": neg.get("results", [])},
        },
        "errors": errors,
    }


def admit_bench_tasks(
    tasks: Sequence[BenchTask | Mapping[str, Any]],
    *,
    oracle_measures_by_task: Mapping[str, Mapping[str, Any]] | None = None,
    noop_measures_by_task: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None,
    oracle_runs: int = ADMISSION_ORACLE_RUNS,
    work_root: str | Path | None = None,
) -> dict[str, Any]:
    """任务集准入批量面（AX-1⑤）：逐任务 :func:`admit_bench_task` →
    admitted/quarantined/rejected 三清单分区（"注册被拒或标记 quarantined"
    的装载面记账——本函数只分区不注册，执行权在调用方）。

    ``oracle_measures_by_task``：{task_id: 已知好输出 measures}——**准入
    必需品**：条目缺席的任务如实 quarantined（oracle 探针未运行——缺席
    不是通过）；``noop_measures_by_task``：{task_id: {判据名: no-op
    measures}} 显式覆盖（None=注册表单源）。其余参数透传。
    """
    oracle_map = dict(oracle_measures_by_task or {})
    noop_map = dict(noop_measures_by_task or {})
    reports: list[dict[str, Any]] = []
    for t in tasks:
        if isinstance(t, BenchTask):
            tid, fam = t.task_id, t.family
        elif isinstance(t, Mapping):
            tid, fam = str(t.get("task_id") or "?"), str(t.get("family") or "?")
        else:
            tid, fam = "?", "?"
        oracle = oracle_map.get(tid)
        if oracle is None:
            reports.append({
                "task_id": tid, "family": fam,
                "status": "quarantined", "admitted": False, "probes": {},
                "errors": ["oracle_measures_by_task 缺本任务条目——oracle 探针"
                           "未运行（准入必需品缺席如实 quarantined，不猜）"]})
            continue
        noop = noop_map.get(tid)
        reports.append(admit_bench_task(
            t, oracle_measures=oracle, noop_measures=noop,
            oracle_runs=oracle_runs, work_root=work_root))
    admitted = [r["task_id"] for r in reports if r["status"] == "admitted"]
    quarantined = [r["task_id"] for r in reports if r["status"] == "quarantined"]
    rejected = [r["task_id"] for r in reports if r["status"] == "rejected"]
    return {
        "n_tasks": len(reports),
        "n_admitted": len(admitted), "n_quarantined": len(quarantined),
        "n_rejected": len(rejected),
        "admitted": admitted, "quarantined": quarantined, "rejected": rejected,
        "reports": reports,
    }
