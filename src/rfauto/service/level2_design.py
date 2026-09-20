"""level2_design：Level 2 端到端——自然语言设计任务验收集执行器。

Level 2 验收口径="10 句自然语言设计任务"：一句中文需求描述、一份可
复现的设计工件输出，七个环节全部由确定性组件串联，成功率
≥7/10 判 PASS。本模块只立四个真缺口（#222 对账：七环节组件与两轴打分
范式均已在树，勿重立）：

 ① 验收集 tests/gold/level2_design_public.yaml（10 句 NL，≥4 器件族，
   字段照 agentbench_public.yaml 先例；family 语义=器件族，与 WP3.7 的
   操作族区分）
 ② 链路执行器 design_chain()：
    NL→typed DesignIntent（LLM 通道可注入，schema 校验失败/缺省回落
     确定性关键词族路由，对 TEMPLATE_META）
    → synthesize_*（core/synthesis.py）初值
    → fake 适配器离线求解（adapters/fake_adapter.py）
    → SpecEvaluator 指标（core/objectives.py）
    → provenance（infra/run_store.py）+ 报告叙事（service/report_narrative.py）
    → agentbench record 契约 {id, trajectory, artifacts, numeric}
    → （可选第 8 环，默认关）优化发起 run_optimize_kickoff()：在 evaluate
     达标任务上调 optimization/surrogate_loop.run_surrogate_loop（fake
     采样器、小预算、seed 固定）真实发起一次代理寻优；产物/状态写
     record.kickoff 与 provenance.optimize_kickoff，报告追加零数字段。
     语义"发起≠完成"：kickoff_status ∈ {completed, launched, failed,
     skipped}——环正常返回且有 best=completed；正常返回但预算耗尽无
     best=launched；调用异常如实记 failed（不抛）；开启但链路前段失败
     =skipped。enable_optimize=False 时链路逐字节与七环节版本相同
     （goldset 10/10 锚零漂移），不进 REQUIREMENT_LINKS 验收矩阵
     （验收门口径仍是七环节，）。
 ③ 成功率门 run_level2_acceptance()：复用 agent_bench 两轴打分
   （evaluate_agentbench/score_agent_task），再独立按执行轴逐任务计
   pass，n_pass ≥ 7/10 判 PASS；结果内嵌 requirement_coverage
   七环节×组件文件锚矩阵
 ④ 防污染：验收集 id 与 agentbench_public.yaml 交集非空即 FAIL

数值铁律：本模块不产生任何物理数字——NL 解析只读取
用户"要求"的频率/阻抗/衰减（需求值，进 spec 与综合内核入参），几何
初值只出自综合内核，S 参数只出自 fake 闭式模型，指标只出自 SpecEvaluator，
报告数字只出自白名单。LLM 通道只负责"分类+抽取需求"，其输出经 pydantic
schema 钉死，任何数值都不进 metrics。真实 LLM 由调用方经 llm_channel
注入，本模块零网络（#139：测试一律 monkeypatch 钉住通道）。

数值锚纪律（#207）：验收集 expected.numeric 是"确定性链路回归锚"
（fake 闭式模型实测钉值，非物理基准），物理口径以 source 引
docs/rf_template_references.md；fake 模型改动会让锚漂移——这是回归门
应有的敏感度，不是要凑绿。
"""

from __future__ import annotations

import json
import re
import warnings
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from rfauto.service.agent_bench import (
  default_public_path,
  evaluate_agentbench,
  load_bench_set,
)

LEVEL2_SCHEMA_VERSION = 1
LEVEL2_SET_FILENAME = "level2_design_public.yaml"
DEFAULT_MIN_SUCCESS = 7      # 成功率 ≥7/10
_PASS_EPS = 1e-9         # 执行轴逐任务 pass 判据（声明维度全满足）

# 本链路当前可端到端闭环的器件族（综合内核 + fake 闭式模型 + TEMPLATE_META
# 三面都在树；slotline/Marchand/C5 族禁入，openEMS 无 slotline 端口原语）。
DESIGN_FAMILIES: tuple[str, ...] = (
  "wilkinson", "branchline", "patch", "mline", "atten_pi")

# 确定性关键词族路由（大小写不敏感；先匹配先得，关键词集合两两无交集）。
_FAMILY_KEYWORDS: dict[str, tuple[str, ...]] = {
  "wilkinson": ("wilkinson", "威尔金森", "功分器", "功率分配"),
  "branchline": ("branchline", "branch-line", "分支线", "支线耦合", "电桥"),
  "patch": ("patch", "贴片"),
  "mline": ("mline", "微带线", "均匀微带", "传输线", "校准线"),
  "atten_pi": ("atten_pi", "衰减器", "π 型", "π型", "pi 型", "pi型"),
}

# 七环节 typed tool 名（轨迹词汇；expected.calls 对照）。
TOOL_PARSE = "design.parse"
TOOL_ROUTE = "design.route"
TOOL_SYNTHESIZE = "design.synthesize"
TOOL_SIMULATE = "design.simulate"
TOOL_EVALUATE = "design.evaluate"
TOOL_REPORT = "design.report"
DESIGN_TOOLS: tuple[str, ...] = (
  TOOL_PARSE, TOOL_ROUTE, TOOL_SYNTHESIZE, TOOL_SIMULATE, TOOL_EVALUATE,
  TOOL_REPORT)
# 可选第 8 环节 typed tool 名（enable_optimize=True 时追加于轨迹尾部；不进
# DESIGN_TOOLS——七环节轨迹词汇是 goldset expected.calls 的裁判口径，子序列
# 匹配天然容忍尾部追加，见 goldset_service.score_trajectory）。
TOOL_OPTIMIZE = "design.optimize"

# 优化发起（kickoff）预算：fake 采样器闭式秒级，小预算只为"真实发起一次"
# 并留下可复现产物；seed 固定使同任务重跑逐字节可复现（#158 配对实验语义）。
KICKOFF_SEED = 42
KICKOFF_N_INIT = 3
KICKOFF_MAX_REAL = 5
KICKOFF_TOP_K = 1
KICKOFF_VIRTUAL_TRIALS = 120
KICKOFF_REL_SPAN = 0.2       # 搜索域 = 综合初值 ×(1∓REL_SPAN)
KICKOFF_RL_TARGET_DB = -20.0    # 回损目标（谐振族谷深/平坦族包络 ≤ 此值）
KICKOFF_ATTEN_TOL_DB = 1.0     # atten_pi 衰减均值容差（MEAN_WITHIN 半宽）
KICKOFF_STATUSES: tuple[str, ...] = ("completed", "launched", "failed", "skipped")
# 需求量键（用户"要求"的量：设计频率/系统阻抗/衰减量）不是设计变量——综合
# 内核把它们原样带进 params（f0 走适配器 init，atten_db 是 fake 模型输入），
# 若放进搜索域，环会直接改需求量去"满足"目标（作弊）。kickoff 只优化几何/
# 元件参数。
KICKOFF_REQUIREMENT_KEYS: tuple[str, ...] = ("f0_ghz", "z0_ohm", "atten_db")

# 工件名（record.artifacts 词汇）。
ART_INTENT = "design_intent"
ART_SYNTHESIS = "synthesis_params"
ART_SPARAMS = "s_params"
ART_METRICS = "metrics"
ART_REPORT = "design_report"
ART_KICKOFF = "optimize_kickoff"  # 仅 enable_optimize=True 时入 artifacts

# 各族 record.numeric 键（全部出自 _evaluate_metrics，铁律 7）。
_RECORD_NUMERIC_KEYS: dict[str, tuple[str, ...]] = {
  "wilkinson": ("f_dip_ghz", "s11_db_min_in_band", "s21_db_at_dip"),
  "branchline": ("f_dip_ghz", "s11_db_min_in_band", "s21_db_at_dip"),
  "patch": ("f_res_ghz", "s11_db_min_in_band"),
  "mline": ("s11_db_max_in_band", "s21_db_mean_in_band"),
  "atten_pi": ("s21_db_mean_in_band", "s11_db_max_in_band"),
}
_RESONANT_FAMILIES = ("wilkinson", "branchline", "patch")
_N_PORTS: dict[str, int] = {
  "wilkinson": 3, "branchline": 4, "patch": 2, "mline": 2, "atten_pi": 2}

_REQ_F0 = re.compile(r"(\d+(?:\.\d+)?)\s*(?:GHz|ghz|Ghz|吉赫)")
_REQ_Z0 = re.compile(r"(\d+(?:\.\d+)?)\s*(?:欧姆|欧|Ω|ohm|Ohm|OHM)")
_REQ_ATTEN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:dB|db|DB)")

# 七环节 × 组件文件锚（表；covered 由记录实证填充）。
REQUIREMENT_LINKS: tuple[dict[str, Any], ...] = (
  {"link": "nl_parse", "requirement": "NL→spec 抽取（typed DesignIntent，LLM 可注入）",
   "anchors": ["src/rfauto/service/level2_design.py:DesignIntent",
         "src/rfauto/service/level2_design.py:extract_requirements"],
   "tool": TOOL_PARSE, "artifact": ART_INTENT},
  {"link": "family_route", "requirement": "NL→模板族路由（对 TEMPLATE_META）",
   "anchors": ["src/rfauto/service/level2_design.py:route_family",
         "src/rfauto/adapters/openems_templates.py:TEMPLATE_META"],
   "tool": TOOL_ROUTE, "artifact": None},
  {"link": "synthesis", "requirement": "综合初值（闭式内核）",
   "anchors": ["src/rfauto/core/synthesis.py:synthesize_wilkinson",
         "src/rfauto/core/synthesis.py:synthesize_branchline",
         "src/rfauto/core/synthesis.py:synthesize_patch",
         "src/rfauto/core/synthesis.py:synthesize_mline_model",
         "src/rfauto/core/synthesis.py:synthesize_atten_pi_model"],
   "tool": TOOL_SYNTHESIZE, "artifact": ART_SYNTHESIS},
  {"link": "simulate", "requirement": "离线求解（fake 闭式模型，零真机）",
   "anchors": ["src/rfauto/adapters/fake_adapter.py:FakeAdapter.solve"],
   "tool": TOOL_SIMULATE, "artifact": ART_SPARAMS},
  {"link": "evaluate", "requirement": "指标评估（SpecEvaluator DSL）",
   "anchors": ["src/rfauto/core/objectives.py:SpecEvaluator.compute_metrics"],
   "tool": TOOL_EVALUATE, "artifact": ART_METRICS},
  {"link": "provenance", "requirement": "provenance（best-effort，#105）",
   "anchors": ["src/rfauto/infra/run_store.py:collect_provenance"],
   "tool": TOOL_REPORT, "artifact": None},
  {"link": "report", "requirement": "报告叙事（白名单数字，铁律 7）",
   "anchors": ["src/rfauto/service/report_narrative.py:render_template_narrative",
         "src/rfauto/service/report_narrative.py:build_whitelist"],
   "tool": TOOL_REPORT, "artifact": ART_REPORT},
)

LlmChannel = Callable[[str], Any]


def default_level2_path() -> Path:
  """验收集缺省路径（tests/gold/level2_design_public.yaml，随库）。"""
  return default_public_path().parent / LEVEL2_SET_FILENAME


# ---------------------------------------------------------------------------
# ① NL → typed DesignIntent（spec 抽取 + 模板族路由）
# ---------------------------------------------------------------------------

class DesignIntent(BaseModel):
  """typed 设计意图（NL→spec 抽取产物）。

  requirements 只装用户"要求"的量（f0_ghz / z0_ohm / atten_db），是
  综合内核的入参、不是物理预测；family 必须是本链路可闭环的器件族。
  """
  family: str
  requirements: dict[str, float] = Field(default_factory=dict)
  source: str = "keyword"     # keyword | llm | keyword_fallback
  raw_prompt: str = ""

  @field_validator("family")
  @classmethod
  def _family_known(cls, value: str) -> str:
    fam = str(value or "").strip().lower()
    if fam not in DESIGN_FAMILIES:
      raise ValueError(
        f"family={value!r} 不在可闭环器件族 {list(DESIGN_FAMILIES)}")
    from rfauto.adapters.openems_templates import TEMPLATE_META

    if fam not in TEMPLATE_META:
      raise ValueError(f"family={fam!r} 不在 TEMPLATE_META")
    return fam

  @field_validator("requirements")
  @classmethod
  def _requirements_finite(cls, value: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, raw in (value or {}).items():
      if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"requirements[{key}] 必须是数值")
      if float(raw) <= 0:
        raise ValueError(f"requirements[{key}] 必须为正")
      out[str(key)] = float(raw)
    return out


def route_family(prompt: str) -> str:
  """确定性关键词族路由（NL→模板族）。无匹配 → ValueError。"""
  text = str(prompt or "").lower()
  for family, keywords in _FAMILY_KEYWORDS.items():
    if any(k.lower() in text for k in keywords):
      return family
  raise ValueError("无法从自然语言路由到已知器件族（关键词零命中）")


def extract_requirements(prompt: str) -> dict[str, float]:
  """从 NL 读取用户要求的量（只读取、不预测）：f0_ghz / z0_ohm / atten_db。

  atten_db 只在句中出现"衰减"时才从 dB 数字抽取（避免把回损/耦合度
  的 dB 数误当衰减量）。
  """
  text = str(prompt or "")
  out: dict[str, float] = {}
  m = _REQ_F0.search(text)
  if m:
    out["f0_ghz"] = float(m.group(1))
  m = _REQ_Z0.search(text)
  if m:
    out["z0_ohm"] = float(m.group(1))
  if "衰减" in text or "atten" in text.lower():
    m = _REQ_ATTEN.search(text)
    if m:
      out["atten_db"] = float(m.group(1))
  return out


def _coerce_llm_output(raw: Any) -> Mapping[str, Any]:
  if isinstance(raw, Mapping):
    return raw
  if isinstance(raw, (str, bytes)):
    data = json.loads(raw)
    if isinstance(data, Mapping):
      return data
  raise TypeError("LLM 通道输出必须是映射或 JSON 对象字符串")


def parse_design_intent(prompt: str,
            llm_channel: LlmChannel | None = None) -> DesignIntent:
  """NL→DesignIntent：LLM 通道（可注入）优先，schema 校验失败/异常回落关键词。

  LLM 通道契约：接收 prompt，返回 {"family": str, "requirements": {..}}
  （映射或 JSON 字符串）。任何异常/校验失败都不致命——记 source=
  keyword_fallback 走确定性路由，链路不因通道失灵而中断。
  """
  if llm_channel is not None:
    try:
      data = _coerce_llm_output(llm_channel(prompt))
      return DesignIntent(
        family=str(data.get("family") or ""),
        requirements=dict(data.get("requirements") or {}),
        source="llm", raw_prompt=str(prompt or ""))
    except Exception: # 通道失灵/输出不合法一律回落（观测性不阻塞主路径，#105）
      return DesignIntent(
        family=route_family(prompt),
        requirements=extract_requirements(prompt),
        source="keyword_fallback", raw_prompt=str(prompt or ""))
  return DesignIntent(
    family=route_family(prompt), requirements=extract_requirements(prompt),
    source="keyword", raw_prompt=str(prompt or ""))


# ---------------------------------------------------------------------------
# ②③ 模板族元数据 + 综合初值（闭式内核）
# ---------------------------------------------------------------------------

def _family_defaults(family: str) -> dict[str, float]:
  """族缺省需求（TEMPLATE_META f0 / 50Ω / TEMPLATE_NOMINAL atten）。"""
  from rfauto.adapters.openems_templates import TEMPLATE_META, TEMPLATE_NOMINAL

  meta = TEMPLATE_META[family]
  out = {"f0_ghz": float(meta.get("f0_ghz") or 2.4), "z0_ohm": 50.0}
  if family == "atten_pi":
    out["atten_db"] = float((TEMPLATE_NOMINAL.get("atten_pi") or {})
                .get("atten_db", 10.0))
  return out


def synthesize_initial(family: str,
            requirements: Mapping[str, float]) -> dict[str, Any]:
  """综合初值：需求 → core/synthesis 闭式内核 → 几何/元件参数。

  返回 {"model", "params", "goal", "notes"}；params 里的每个数字都出自
  综合内核（本函数只做分派与缺省填充）。
  """
  from rfauto.core import synthesis as syn

  req = {**_family_defaults(family), **dict(requirements or {})}
  f0 = float(req["f0_ghz"])
  z0 = float(req["z0_ohm"])
  if family == "wilkinson":
    res = syn.synthesize_wilkinson(f0_ghz=f0, z0_ohm=z0)
  elif family == "branchline":
    res = syn.synthesize_branchline(f0_ghz=f0, z0_ohm=z0)
  elif family == "patch":
    res = syn.synthesize_patch(f0_ghz=f0)
  elif family == "mline":
    res = syn.synthesize_mline_model(z0_ohm=z0, freq_ghz=f0)
  elif family == "atten_pi":
    res = syn.synthesize_atten_pi_model(
      attenuation_db=float(req["atten_db"]), z0_ohm=z0, freq_ghz=f0)
  else: # pragma: no cover - DesignIntent 已钉死族集合
    raise ValueError(f"未支持的器件族: {family}")
  return {
    "model": res.model,
    "params": {k: float(v) for k, v in res.params.items()},
    "goal": dict(res.goal),
    "notes": list(res.notes),
    "effective_requirements": req,
  }


# ---------------------------------------------------------------------------
# ④ 离线求解（fake 闭式模型）
# ---------------------------------------------------------------------------

def _variable_strings(params: Mapping[str, float]) -> dict[str, str]:
  """综合参数 → 适配器变量串（长度带 mm 单位；f0 走适配器 init，不作变量）。"""
  out: dict[str, str] = {}
  for key, value in params.items():
    if key == "f0_ghz":
      continue
    out[key] = f"{value}mm" if key.endswith("_mm") else str(value)
  return out


def _freq_span(family: str, f0: float) -> tuple[float, float, int]:
  if family in _RESONANT_FAMILIES:
    return (0.7 * f0, 1.3 * f0, 401)
  return (0.9 * f0, 1.1 * f0, 201)


def simulate_offline(family: str, params: Mapping[str, float], f0_ghz: float,
           *, seed: int = 42) -> Any:
  """fake 适配器离线求解 → skrf.Network（零真机、确定性、秒级）。"""
  from rfauto.adapters.fake_adapter import FakeAdapter

  adapter = FakeAdapter(model_type=family, freq_ghz=_freq_span(family, f0_ghz),
             n_ports=_N_PORTS[family], f0_ghz=float(f0_ghz), seed=seed)
  adapter.connect({})
  adapter.set_variables(_variable_strings(params))
  report = adapter.solve("level2_design_chain")
  if not report.success:
    raise RuntimeError(f"fake 求解失败: {report.message}")
  return adapter.get_sparams()


# ---------------------------------------------------------------------------
# ⑤ 指标评估（SpecEvaluator）
# ---------------------------------------------------------------------------

def evaluate_metrics(network: Any) -> dict[str, float]:
  """SpecEvaluator 指标 + 谷点指标（全部由 S 参数网络算出，铁律 7）。

  产物：s11_db_max_in_band / s11_db_min_in_band / s21_db_mean_in_band
  （SpecEvaluator.compute_metrics，带=网络全频宽）、f_dip_ghz（|S11|
  谷位，#195 谷深语义）、s21_db_at_dip（谷位处 |S21|，多端口取 S21）。
  """
  import numpy as np

  from rfauto.core.objectives import Objective, SpecEvaluator

  freq_ghz = np.asarray(network.frequency.f, dtype=float) * 1e-9
  band = [float(freq_ghz.min()), float(freq_ghz.max())]
  objectives = [Objective(metric="s11_db", band=band),
         Objective(metric="s21_db", band=band)]
  metrics = SpecEvaluator.compute_metrics(network, objectives)

  s11_db = 20.0 * np.log10(np.abs(network.s[:, 0, 0]) + 1e-30)
  idx = int(np.argmin(s11_db))
  metrics["f_dip_ghz"] = float(freq_ghz[idx])
  s21 = (network.s[idx, 1, 0] if network.s.shape[1] > 1
      else network.s[idx, 0, 0])
  metrics["s21_db_at_dip"] = float(20.0 * np.log10(abs(s21) + 1e-30))
  return {k: float(v) for k, v in metrics.items()}


def _record_numeric(family: str, metrics: Mapping[str, float]) -> dict[str, float]:
  """按族挑 record.numeric（patch 谷位以 f_res_ghz 命名，对齐 ab002 先例）。"""
  out: dict[str, float] = {}
  for key in _RECORD_NUMERIC_KEYS[family]:
    src = "f_dip_ghz" if key == "f_res_ghz" else key
    if src in metrics:
      out[key] = float(metrics[src])
  return out


# ---------------------------------------------------------------------------
# ⑥⑦ provenance + 报告叙事
# ---------------------------------------------------------------------------

_PROVENANCE_CACHE: dict[str, Any] = {}


def _provenance() -> dict[str, Any]:
  """collect_provenance 进程内缓存（pip freeze 哈希开销只付一次；best-effort）。"""
  if not _PROVENANCE_CACHE:
    try:
      from rfauto.infra.run_store import collect_provenance

      _PROVENANCE_CACHE.update(collect_provenance(
        solver_versions={"fake_adapter": "closed-form"}))
    except Exception as exc: # 观测性不得阻塞主路径（#105）
      _PROVENANCE_CACHE.update({"error": str(exc)})
  return dict(_PROVENANCE_CACHE)


def render_design_report(family: str, numeric: Mapping[str, float],
             params: Mapping[str, float]) -> str:
  """确定性报告叙事：数字只来自白名单（指标+综合参数），零 LLM。"""
  from rfauto.service.report_narrative import (
    build_whitelist,
    render_template_narrative,
  )

  data = {"model": family, "adapter": "fake",
      "metrics": dict(numeric), "params": dict(params)}
  whitelist = build_whitelist(data, source="level2_design_chain")
  return render_template_narrative(data, whitelist,
                   source="level2 设计链（fake 闭式模型 + 综合内核）")


# ---------------------------------------------------------------------------
# ⑧ 优化发起（kickoff，可选；默认关）
# ---------------------------------------------------------------------------

def kickoff_bounds(params: Mapping[str, float],
          rel_span: float = KICKOFF_REL_SPAN,
          *,
          exclude: Sequence[str] = KICKOFF_REQUIREMENT_KEYS,
          ) -> dict[str, tuple[float, float]]:
  """综合初值 → 代理环搜索域：每个设计变量取 ×(1∓rel_span) 邻域（确定性派生，
  铁律 7：域端点只是综合内核数字的确定性缩放，不引入新物理量）。

  exclude（缺省 KICKOFF_REQUIREMENT_KEYS）里的需求量键剔除——它们是用户要求
  的量而非设计变量（见常量注释）；非正参数无法构造有序区间，同样剔除。
  """
  span = float(rel_span)
  if not (0.0 < span < 1.0):
    raise ValueError(f"rel_span 必须在 (0, 1)：{rel_span!r}")
  skip = {str(k) for k in exclude}
  out: dict[str, tuple[float, float]] = {}
  for key, raw in (params or {}).items():
    if str(key) in skip or isinstance(raw, bool):
      continue
    value = float(raw)
    if value <= 0.0:
      continue
    out[str(key)] = (value * (1.0 - span), value * (1.0 + span))
  return out


def kickoff_objectives(family: str, f0_ghz: float,
            requirements: Mapping[str, float] | None = None) -> list[Any]:
  """按族定 kickoff 目标（单目标，小预算环最稳；数值只来自常量与需求）：

  - 谐振族（wilkinson/branchline/patch）：谷深 s11_db_min ≤ RL_TARGET
   （#195 谷深语义走显式统计量名，不踩带内 max 常数陷阱）；
  - mline：带内包络 s11_db ≤ RL_TARGET；
  - atten_pi：s21_db 均值落在 [-(atten+tol), -(atten-tol)]（atten 取用户
   要求值，缺省走族缺省）。
  """
  from rfauto.core.objectives import MetricOp, Objective

  band = list(_freq_span(family, float(f0_ghz))[:2])
  if family in _RESONANT_FAMILIES:
    return [Objective(metric="s11_db_min", band=band, op=MetricOp.MAX_BELOW,
             value=KICKOFF_RL_TARGET_DB)]
  if family == "atten_pi":
    req = {**_family_defaults(family), **dict(requirements or {})}
    atten = float(req["atten_db"])
    return [Objective(metric="s21_db", band=band, op=MetricOp.MEAN_WITHIN,
             value=[-(atten + KICKOFF_ATTEN_TOL_DB),
                 -(atten - KICKOFF_ATTEN_TOL_DB)])]
  return [Objective(metric="s11_db", band=band, op=MetricOp.MAX_BELOW,
           value=KICKOFF_RL_TARGET_DB)]


def kickoff_evaluate_fn(family: str, f0_ghz: float, objectives: Sequence[Any],
            fixed: Mapping[str, float] | None = None,
            ) -> Callable[[dict[str, float]], dict[str, float]]:
  """params → metrics（fake 采样器口径：simulate_offline + SpecEvaluator，
  与 surrogate_optimize_service._make_evaluate_fn 同构；抛异常=该点真跑失败，
  由环记 failure 不入样本）。

  fixed = 不进搜索域但 fake 模型仍要消费的综合参数（如 atten_pi 的
  atten_db 需求量），逐点与环给的搜索变量合并（搜索变量优先）。
  """
  from rfauto.core.objectives import SpecEvaluator

  specs = list(objectives)
  base = {str(k): float(v) for k, v in (fixed or {}).items()}

  def evaluate(params: dict[str, float]) -> dict[str, float]:
    full = {**base, **{str(k): float(v) for k, v in params.items()}}
    network = simulate_offline(family, full, float(f0_ghz))
    return SpecEvaluator.compute_metrics(network, specs)

  return evaluate


def _kickoff_tag(tag: str) -> str:
  safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(tag or "")).strip("._-")
  return safe or "kickoff"


def run_optimize_kickoff(family: str, synth: Mapping[str, Any], *,
             seed: int = KICKOFF_SEED,
             out_dir: str | Path | None = None,
             tag: str = "") -> dict[str, Any]:
  """优化发起：对综合初值真实发起一次代理寻优（run_surrogate_loop，fake
  采样器、小预算、seed 固定），返回 kickoff 契约（永不抛）。

  synth = synthesize_initial() 的返回（params / effective_requirements）。
  kickoff_status：completed（环正常返回且 best 非空）/ launched（正常返回
  但预算耗尽无 best——"发起≠完成"）/ failed（调用异常，error 如实记）。
  out_dir 给定时把环返回体落盘为 <out_dir>/surrogate_kickoff_<tag>.json 并
  记 artifact_path（design_chain 层默认不落盘，避免链路污染 runs/，#144）。
  """
  params = {k: float(v) for k, v in (synth.get("params") or {}).items()}
  eff = dict(synth.get("effective_requirements") or {})
  f0 = float(eff.get("f0_ghz") or _family_defaults(family)["f0_ghz"])
  out: dict[str, Any] = {
    "kickoff_status": "failed", "family": family, "seed": int(seed),
    "algorithm": "surrogate_loop", "adapter": "fake",
    "budget": {"n_init": KICKOFF_N_INIT, "max_real": KICKOFF_MAX_REAL,
          "top_k": KICKOFF_TOP_K, "virtual_trials": KICKOFF_VIRTUAL_TRIALS},
    "bounds": {}, "best": None, "n_real_used": 0, "stop_reason": None,
    "artifact_path": None,
  }
  try:
    from rfauto.optimization.surrogate_loop import run_surrogate_loop

    bounds = kickoff_bounds(params)
    if not bounds:
      raise ValueError("综合初值无可优化参数（搜索域为空）")
    fixed = {k: v for k, v in params.items() if k not in bounds}
    objectives = kickoff_objectives(family, f0, eff)
    out["bounds"] = {k: [float(lo), float(hi)] for k, (lo, hi) in bounds.items()}
    out["fixed_params"] = dict(fixed)
    out["objectives"] = [o.model_dump(mode="json") for o in objectives]
    # 小预算（≤KICKOFF_MAX_REAL 样本）下环内 GP 代理质量报告的核超参
    # 必贴边界并发 sklearn ConvergenceWarning——与 kickoff 语义无关，且会
    # 污染 CLI stderr；仅在本调用块内压制（不改 optimization 层、不吞异常）。
    try:
      from sklearn.exceptions import ConvergenceWarning as _ConvWarn
    except Exception: # pragma: no cover - sklearn 是环的既有依赖
      _ConvWarn = UserWarning # type: ignore[assignment,misc]
    with warnings.catch_warnings():
      warnings.simplefilter("ignore", _ConvWarn)
      result = run_surrogate_loop(
        bounds, objectives, kickoff_evaluate_fn(family, f0, objectives, fixed),
        n_init=KICKOFF_N_INIT, top_k=KICKOFF_TOP_K,
        virtual_trials=KICKOFF_VIRTUAL_TRIALS, max_real=KICKOFF_MAX_REAL,
        seed=int(seed))
    if not isinstance(result, Mapping):
      raise TypeError("run_surrogate_loop 返回体必须是映射")
    if not result.get("ok", True):
      raise RuntimeError("; ".join(str(e) for e in result.get("errors") or [])
                or "环返回 ok=False")
    best = result.get("best")
    out["best"] = dict(best) if isinstance(best, Mapping) else None
    out["n_real_used"] = int(result.get("n_real_used") or 0)
    out["stop_reason"] = result.get("stop_reason")
    out["n_failures"] = int(result.get("n_failures") or 0)
    out["real_cost_trace"] = [float(c) for c in result.get("real_cost_trace") or []]
    out["kickoff_status"] = "completed" if out["best"] else "launched"
    if out_dir is not None:
      target = Path(out_dir)
      target.mkdir(parents=True, exist_ok=True)
      path = target / f"surrogate_kickoff_{_kickoff_tag(tag or family)}.json"
      path.write_text(json.dumps({"kickoff": out, "loop_result": dict(result)},
                    ensure_ascii=False, indent=1, default=str),
              encoding="utf-8")
      out["artifact_path"] = str(path)
  except Exception as exc: # 预算耗尽/异常一律如实记录，不抛（发起≠完成）
    out["kickoff_status"] = "failed"
    out["error"] = f"{type(exc).__name__}: {exc}"
  return out


def render_kickoff_section(kickoff: Mapping[str, Any]) -> str:
  """报告追加段（零数字，铁律 7）：kickoff 的全部数字留在 record.kickoff /
  provenance.optimize_kickoff 结构化工件，叙述层只做定性指引，主报告白名单
  审计对追加段照样绿（无独立数字 token）。"""
  status = str(kickoff.get("kickoff_status") or "skipped")
  lines = ["", "## 优化发起（kickoff，可选第八环节）"]
  if status == "completed":
    lines.append("- 已在综合初值邻域真实发起一次代理寻优并得到最优可行点；"
           "最优参数与指标见结构化工件 kickoff.best。")
  elif status == "launched":
    lines.append("- 已真实发起一次代理寻优，预算耗尽时尚无最优点（发起不等于完成）；"
           "真跑轨迹见结构化工件 kickoff。")
  elif status == "failed":
    lines.append("- 优化发起过程出现异常，已如实记录于 kickoff.error，未影响设计链其余环节。")
  else:
    lines.append("- 本任务未发起优化（链路前段未达标或未启用）。")
  if kickoff.get("artifact_path"):
    lines.append("- 环返回体已落盘，路径见 provenance.optimize_kickoff.artifact_path。")
  lines.append("- 预算、seed、搜索域与真跑成本轨迹均见 provenance.optimize_kickoff。")
  return "\n".join(lines) + "\n"


def _kickoff_provenance(kickoff: Mapping[str, Any]) -> dict[str, Any]:
  keys = ("kickoff_status", "algorithm", "adapter", "seed", "budget", "bounds",
      "n_real_used", "n_failures", "stop_reason", "real_cost_trace",
      "artifact_path", "error")
  return {k: kickoff[k] for k in keys if k in kickoff}


# ---------------------------------------------------------------------------
# 链路执行器（七环节串联 + 可选第 8 环 → agentbench record 契约）
# ---------------------------------------------------------------------------

def design_chain(task: Mapping[str, Any],
         llm_channel: LlmChannel | None = None,
         *,
         enable_optimize: bool = False,
         optimize_out_dir: str | Path | None = None) -> dict[str, Any]:
  """一句 NL 设计任务 → agentbench record（{id, trajectory, artifacts, numeric}）。

  每步先落 typed tool call 再执行（轨迹可复现、模型无关）；任一步异常
  → record 带 error 与已完成的部分工件返回（评分时执行轴自然不满，
  不抛、不凑）。task 只用 id 与 prompt——器件族由链路自己从 NL 路由，
  任务集里的 family 是裁判元数据，不喂给链路。

  enable_optimize（默认 False，链路逐字节与七环节版本相同）：True 时在
  七环节全部达标后追加第 8 环 design.optimize——run_optimize_kickoff 真实
  发起一次代理寻优，结果进 record.kickoff / record.kickoff_status /
  provenance.optimize_kickoff，报告追加零数字段，artifacts 追加
  optimize_kickoff；环内异常已消化为 kickoff_status=failed，不会让链路
  带 error。链路前段失败时开启态记 kickoff_status=skipped。
  optimize_out_dir 给定时环返回体落盘并记 artifact_path（缺省不落盘）。
  """
  task_id = task.get("id")
  prompt = str(task.get("prompt") or "")
  trajectory: list[dict[str, Any]] = []
  artifacts: list[str] = []
  record: dict[str, Any] = {
    "id": task_id, "trajectory": trajectory, "artifacts": artifacts,
    "numeric": {}, "schema_version": LEVEL2_SCHEMA_VERSION,
  }
  try:
    trajectory.append({"tool": TOOL_PARSE, "args": {"prompt": prompt}})
    intent = parse_design_intent(prompt, llm_channel)
    record["intent"] = intent.model_dump()
    artifacts.append(ART_INTENT)

    trajectory.append({"tool": TOOL_ROUTE, "args": {"family": intent.family}})
    from rfauto.adapters.openems_templates import TEMPLATE_META

    meta = TEMPLATE_META[intent.family]
    record["family"] = intent.family
    record["template_params"] = list(meta.get("params") or [])

    synth = synthesize_initial(intent.family, intent.requirements)
    eff = synth["effective_requirements"]
    trajectory.append({"tool": TOOL_SYNTHESIZE, "args": {
      "family": intent.family, "f0_ghz": float(eff["f0_ghz"])}})
    record["synthesis_params"] = synth["params"]
    record["synthesis_notes"] = synth["notes"]
    artifacts.append(ART_SYNTHESIS)

    trajectory.append({"tool": TOOL_SIMULATE, "args": {
      "family": intent.family, "adapter": "fake"}})
    network = simulate_offline(intent.family, synth["params"],
                  float(eff["f0_ghz"]))
    record["n_ports"] = int(network.s.shape[1])
    record["n_freq"] = int(network.s.shape[0])
    artifacts.append(ART_SPARAMS)

    trajectory.append({"tool": TOOL_EVALUATE, "args": {"family": intent.family}})
    metrics = evaluate_metrics(network)
    record["metrics"] = metrics
    record["numeric"] = _record_numeric(intent.family, metrics)
    artifacts.append(ART_METRICS)

    trajectory.append({"tool": TOOL_REPORT, "args": {"family": intent.family}})
    record["provenance"] = _provenance()
    record["report"] = render_design_report(
      intent.family, record["numeric"], synth["params"])
    artifacts.append(ART_REPORT)

    if enable_optimize:
      # ⑧ 可选第 8 环：evaluate 已达标（前六环全部无异常）才发起；先落
      # typed tool call 再执行；run_optimize_kickoff 永不抛。
      trajectory.append({"tool": TOOL_OPTIMIZE, "args": {
        "family": intent.family, "adapter": "fake", "seed": KICKOFF_SEED}})
      kickoff = run_optimize_kickoff(
        intent.family, synth, seed=KICKOFF_SEED,
        out_dir=optimize_out_dir, tag=str(task_id or intent.family))
      record["kickoff"] = kickoff
      record["kickoff_status"] = kickoff["kickoff_status"]
      record["provenance"]["optimize_kickoff"] = _kickoff_provenance(kickoff)
      record["report"] = record["report"] + render_kickoff_section(kickoff)
      artifacts.append(ART_KICKOFF)
  except Exception as exc: # 记录部分结果，评分时如实扣分
    record["error"] = f"{type(exc).__name__}: {exc}"
    if enable_optimize and "kickoff_status" not in record:
      record["kickoff_status"] = "skipped"
      record["kickoff"] = {
        "kickoff_status": "skipped",
        "reason": "链路前段失败（未达 evaluate 达标条件），不发起优化"}
  return record


def reference_design_provider(task: Mapping[str, Any]) -> dict[str, Any]:
  """离线参考提供器：确定性设计链本体（零 LLM、零网络）——门的正控。"""
  return design_chain(task, None)


# ---------------------------------------------------------------------------
# 防污染 + 成功率门 + 需求覆盖矩阵
# ---------------------------------------------------------------------------

def check_set_contamination(level2_path: str | Path | None = None,
              agentbench_path: str | Path | None = None
              ) -> dict[str, Any]:
  """验收集 id 与 WP3.7 公开集交集非空即污染（复用 load_bench_sets 语义）。"""
  level2 = load_bench_set(level2_path or default_level2_path())
  bench = load_bench_set(agentbench_path or default_public_path())
  errors: list[str] = []
  if not level2.get("ok"):
    errors.extend(str(e) for e in level2.get("errors") or ["level2 集加载失败"])
  if not bench.get("ok"):
    errors.extend(str(e) for e in bench.get("errors") or ["agentbench 公开集加载失败"])
  overlap: list[str] = []
  if not errors:
    l2_ids = {t.get("id") for t in level2.get("tasks") or []}
    ab_ids = {t.get("id") for t in bench.get("tasks") or []}
    overlap = sorted(str(i) for i in (l2_ids & ab_ids))
    if overlap:
      errors.append(
        f"集污染：level2 验收集与 agentbench 公开集 id 交集非空 → {overlap[:5]}")
  return {"ok": not errors, "errors": errors, "overlap_ids": overlap,
      "level2": level2, "agentbench": bench}


def requirement_coverage(tasks: Sequence[Mapping[str, Any]],
             records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
  """七环节 × 组件文件锚矩阵：每环节以"全部记录都留有该环节证据"判 covered。

  证据 = 轨迹含该环节 typed tool + （若声明）工件名在 artifacts 中；
  family_route 额外要求路由结果 == 任务声明器件族（裁判元数据）。
  """
  by_id = {t.get("id"): t for t in tasks}
  rows: list[dict[str, Any]] = []
  for link in REQUIREMENT_LINKS:
    hits = 0
    for rec in records:
      tools = {str(c.get("tool")) for c in rec.get("trajectory") or []
           if isinstance(c, Mapping)}
      arts = {str(a) for a in rec.get("artifacts") or []}
      ok = link["tool"] in tools
      if link["artifact"] is not None:
        ok = ok and link["artifact"] in arts
      if link["link"] == "family_route":
        task = by_id.get(rec.get("id")) or {}
        ok = ok and str(rec.get("family") or "") == str(task.get("family") or "")
      if link["link"] == "provenance":
        ok = ok and bool(rec.get("provenance"))
      hits += int(ok)
    rows.append({
      "link": link["link"], "requirement": link["requirement"],
      "anchors": list(link["anchors"]), "n_hit": hits,
      "n_records": len(records),
      "covered": bool(records) and hits == len(records),
    })
  return {"n_links": len(rows), "n_covered": sum(r["covered"] for r in rows),
      "links": rows}


def run_level2_acceptance(
  records: Sequence[Mapping[str, Any]] | None = None,
  *,
  set_path: str | Path | None = None,
  llm_channel: LlmChannel | None = None,
  min_success: int = DEFAULT_MIN_SUCCESS,
  enable_optimize: bool = False,
  optimize_out_dir: str | Path | None = None,
) -> dict[str, Any]:
  """ Level 2 验收门：防污染 → 逐任务跑链（或用记录）→ 两轴打分
  → 执行轴逐任务 pass 计数 ≥ min_success 判 PASS → 需求覆盖矩阵。

  records 缺省=对验收集每任务跑 design_chain（llm_channel 可注入；None
  即确定性参考链）。防空转：集加载失败/污染/记录为空/含未知 id/未覆盖
  全部任务 → FAIL。

  enable_optimize / optimize_out_dir 只在缺省自跑链时透传给 design_chain
  （外部 records 已是既成记录，不重跑）；结果体 optimize.kickoff_counts
  如实汇总各任务 kickoff_status（默认关时全部 absent），per_task 逐行带
  kickoff_status。kickoff 不参与 pass 判定——发起≠完成，门口径仍是七环节。
  """
  path = Path(set_path) if set_path else default_level2_path()
  contamination = check_set_contamination(path)
  n_tasks = len((contamination.get("level2") or {}).get("tasks") or [])

  def _result(ok: bool, reasons: list[str], **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
      "ok": ok, "gate": "PASS" if ok else "FAIL",
      "schema_version": LEVEL2_SCHEMA_VERSION,
      "set_path": str(path), "n_tasks": n_tasks,
      "n_pass": 0, "success_rate": 0.0, "min_success": int(min_success),
      "contamination": {"overlap_ids": contamination.get("overlap_ids") or []},
      "two_axis": None, "per_task": [], "requirement_coverage": None,
      "optimize": {"enabled": bool(enable_optimize), "kickoff_counts": {}},
      "reasons": reasons, "errors": [] if ok else list(reasons),
    }
    out.update(extra)
    return out

  if not contamination.get("ok"):
    return _result(False, list(contamination.get("errors") or ["验收集不可用"]))
  tasks = list(contamination["level2"]["tasks"])
  if not tasks:
    return _result(False, ["验收集为空：拒绝空跑（防空转）"])

  if records is None:
    items: list[Mapping[str, Any]] = [
      design_chain(t, llm_channel, enable_optimize=enable_optimize,
             optimize_out_dir=optimize_out_dir)
      for t in tasks]
  else:
    if not isinstance(records, (list, tuple)):
      return _result(False, ["records 必须是序列"])
    items = list(records)
    if not items:
      return _result(False, ["记录为空：拒绝空跑（防空转）"])
    for item in items:
      if not isinstance(item, Mapping):
        return _result(False, ["记录项必须是映射 {id, trajectory, ...}"])

  known = {t.get("id") for t in tasks}
  seen = {r.get("id") for r in items if r.get("id") in known}
  unknown = sorted(str(r.get("id")) for r in items if r.get("id") not in known)
  if unknown:
    return _result(False, [f"记录含未知任务 id: {unknown[:5]}"])
  if seen != known:
    absent = sorted(str(i) for i in known - seen)
    return _result(False, [f"记录未覆盖全部验收任务：缺 {len(absent)} 个 {absent[:5]}"])

  report = evaluate_agentbench(items, public_path=path, private_path=None)
  if not report.get("ok"):
    return _result(False, ["两轴打分失败"] + [str(e) for e in report.get("errors") or []])
  scored = (report.get("sets") or {}).get("public") or {}
  by_id = {r.get("id"): r for r in scored.get("results") or []}
  rec_by_id = {r.get("id"): r for r in items}
  per_task: list[dict[str, Any]] = []
  n_pass = 0
  for task in tasks:
    tid = task.get("id")
    r = by_id.get(tid) or {}
    rec = rec_by_id.get(tid) or {}
    execution = float(r.get("execution", 0.0)) if "error" not in r else 0.0
    passed = ("error" not in r) and execution >= 1.0 - _PASS_EPS
    n_pass += int(passed)
    per_task.append({
      "id": tid, "family": task.get("family"),
      "routed_family": rec.get("family"),
      "pass": passed, "execution": execution,
      "abstraction": float(r.get("abstraction", 0.0)) if "error" not in r else 0.0,
      "artifact_missing": list(r.get("artifact_missing") or []),
      "numeric_failed": list(r.get("numeric_failed") or []),
      "error": r.get("error") or rec.get("error"),
      "kickoff_status": rec.get("kickoff_status"),
    })
  coverage = requirement_coverage(tasks, items)
  kickoff_counts: dict[str, int] = {}
  for row in per_task:
    key = str(row.get("kickoff_status") or "absent")
    kickoff_counts[key] = kickoff_counts.get(key, 0) + 1
  two_axis = {
    "abstraction": float(scored.get("abstraction", 0.0)),
    "execution": float(scored.get("execution", 0.0)),
    "tsa": float(scored.get("tsa", 0.0)),
    "fca": float(scored.get("fca", 0.0)),
    "n_scored": int(scored.get("n_scored", 0)),
  }
  success_rate = n_pass / len(tasks)
  reasons: list[str] = []
  if n_pass < int(min_success):
    reasons.append(f"成功率 {n_pass}/{len(tasks)} < 门限 {int(min_success)}/{len(tasks)}"
            "")
  ok = not reasons
  if ok:
    reasons.append(f"PASS：成功率 {n_pass}/{len(tasks)} ≥ {int(min_success)}/{len(tasks)}，"
            f"七环节覆盖 {coverage['n_covered']}/{coverage['n_links']}")
  return _result(ok, reasons, n_pass=n_pass, success_rate=success_rate,
          two_axis=two_axis, per_task=per_task,
          requirement_coverage=coverage,
          optimize={"enabled": bool(enable_optimize),
               "kickoff_counts": kickoff_counts},
          families=sorted({str(t.get("family")) for t in tasks}))
