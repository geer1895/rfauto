"""em_bench_analog_service —— em_bench 模拟侧任务族扩容（aurora_r R-08，AX-8+B5）。

来源（思想级重写零搬运）：runs/aurora_q/qx40_vbridge/AUTHOR_SURVEY.md §2
**AX-8**（vaBench 四任务族扩 em_bench）与 **B5**（逆设计任务族，四文计划
同槽）两行；raw_author_survey_A.md §4（awesome-ams-skills：vaBench 任务族
四分法 spec-to-va/tb-generation/end-to-end/bugfix+"快引擎查→金标晋升"两级
验证路由）+ raw_author_survey_B.md §2（behavioral-veriloga-eval：must_include/
must_not_include 防偷步+hidden/visible 分层）。

**判据分层（两级验证路由，预声明不伪造）**：

- **L1 解析/静态级（本模块已实现）**：快引擎=core/veriloga_parser.py
  （Q-X80 内核，只读消费零改动）结构化解析+静态标记检查（must_include/
  must_not_include/tb 三要素组）——零真机零网络零随机，全离线确定性；
- **L2 金标晋升级（挂账，本席不伪造）**：AX-8 四族的第二级=PSSFSS 实仿真
  金标（adapters/pssfss_adapter.py 严格快通道，分钟级 MoM——判据面挂账
  ``L2_DEFERRAL`` 常量，本模块源码零 pssfss import，tests 源码钉）；
  B5 逆设计的第二级=候选响应由 fake/openEMS 确定性通道真跑产出后再生
  任务（本席判据只消费任务输入自带的已产出响应——as-recorded 口径）。
  **两级都不在本席冒充**：L2 结果缺席如实 absent，不编造通过。

**判据枚举零新增（词表闭集防漂移，Q-X43 钉纪律）**：五族判据全部复用
em_bench_service 既有枚举 ``gate_pass``（布尔极性：解析接受/骨架锚/表面
一致性门）与 ``success_rate``（下界极性：规格要素命中率/tb 三要素组命中
率/缺陷清除率/逆设计命中率）——``len(CRITERIA_NAMES)==10`` 钉不动；
命中语义与容差全部预声明在各 runner docstring 与任务 input_spec（#122：
阈值预声明，缺即 fail-closed 不猜）。

**注册形态（进程级注册表保护）**：五 family runner **不在 import 时注册**
（test_em_bench.py 的 ``registered_families()==BENCH_FAMILIES`` 闭集钉以
进程级注册表为锚——pytest 全量收集先于执行，import 期注册会打红闭集钉）；
显式安装走 :func:`install_va_bench_runners`（幂等+冲突拒收），生产接线=
主代合流面挂账处方（同笔更新 BENCH_FAMILIES 词表+test_em_bench.py 迁移
钉——Q-X43/Q-X55 词表同步迁移纪律先例）；单测经 monkeypatch.setitem 注入
（R-01 探针族同款，注册表自动还原）。

**任务面**：:func:`default_va_bench_tasks` 返回 7 任务（AX-8 四族各 1+
B5 演示 3——合成响应面逐位可复现），**不入** ``default_bench_tasks()``
（15 锚钉不动，合流面决策）；每任务带 grader_notes（AX-1①）+反例变体
（AX-1④ 各 ≥1）+预声明阈值；每族任务过 R-01 准入门
（:func:`em_bench_service.admit_bench_task`，oracle 探针供给=
:func:`va_bench_admission_catalog`——oracle=本模块 runner 对缺省输入的
实测测度，非手工编造）。

**CLI/MCP 挂账（本席无叶——处方进 docstring）**：R-01 处方的
``em-bench admit``/``em-bench score`` 两叶消费本模块任务目录即可覆盖
五族（CLI 薄壳调 :func:`default_va_bench_tasks`+
:func:`va_bench_admission_catalog`+:func:`em_bench_service.admit_bench_tasks`
三步，信封走 ok_envelope/error_envelope 构造器——合流面执行）。

本模块不设 ``__all__``（无 ``__all__`` 的非门面文件不进
tests/gold/public_api.json——veriloga_service/veriloga_parser 同款先例，
新模块零金快照漂移；公开面申报=五 family runner+三公开函数，见本
docstring 与 R-08 席位报告）。

零 LLM：本模块源代码无任何 LLM 通道 import（R-01 AST 静态钉同款纪律）。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from rfauto.core.veriloga_parser import parse_veriloga
from rfauto.service.em_bench_service import (
    BenchCriterion,
    BenchGraderNotes,
    BenchNegativeVariant,
    BenchRunContext,
    BenchTask,
    EnvelopeBound,
)

# ---------------------------------------------------------------------------
# family 词表（本模块五族；不入 em_bench_service.BENCH_FAMILIES 闭集——
# 合流面显式安装时同笔迁移，见模块 docstring 注册形态节）
# ---------------------------------------------------------------------------

#: AX-8 vaBench 四任务族 family 键（spec-to-va/tb-generation/end-to-end/bugfix）。
VA_FAMILY_SPEC_TO_VA = "va_spec_to_va"
VA_FAMILY_TB_GENERATION = "va_tb_generation"
VA_FAMILY_END_TO_END = "va_end_to_end"
VA_FAMILY_BUGFIX = "va_bugfix"
#: B5 逆设计任务族 family 键。
B5_FAMILY_INVERSE_DESIGN = "inverse_design"

#: 五族 family 键闭集（注册面/installer 消费序=本元组序）。
ANALOG_BENCH_FAMILIES: tuple[str, ...] = (
    VA_FAMILY_SPEC_TO_VA,
    VA_FAMILY_TB_GENERATION,
    VA_FAMILY_END_TO_END,
    VA_FAMILY_BUGFIX,
    B5_FAMILY_INVERSE_DESIGN,
)

#: L2 金标挂账登记面（AX-8 两级验证路由第二级/B5 第二级——如实 absent，
#: 不伪造 L2 结果；消费方读本常量做挂账审计）。
L2_DEFERRAL: dict[str, str] = {
    VA_FAMILY_SPEC_TO_VA: "L2 金标晋升=PSSFSS 实仿真复核候选 .va 驱动 PSSFSS "
                          "等效电路的响应一致性（挂账——本席零 PSSFSS 调用）",
    VA_FAMILY_TB_GENERATION: "L2 金标晋升=DUT+testbench 真仿真执行（挂账——"
                             "本席零真机调用）",
    VA_FAMILY_END_TO_END: "L2 金标晋升=PSSFSS/真机全链复验（挂账——本席零调用）",
    VA_FAMILY_BUGFIX: "L2 金标晋升=修复后 .va 真仿真行为复验（挂账——本席零调用）",
    B5_FAMILY_INVERSE_DESIGN: "L2=候选响应由 fake/openEMS 确定性通道真跑产出后"
                              "再生任务（本席判据消费已产出响应——真跑挂账）",
}

#: 预声明阈值（#122）：命中率类判据缺省下界。va 四族=全部要素命中（1.0）；
#: B5 演示任务各自预声明（见 default_va_bench_tasks 任务定义锚注释）。
_VA_HIT_RATE_MIN = 1.0
_B5_HIT_RATE_MIN_MIXED = 0.5
_B5_HIT_RATE_MIN_STRICT = 1.0

# ---------------------------------------------------------------------------
# B5 合成响应面（声明式合成——非物理真值，演示判据用；逐位可复现）
# ---------------------------------------------------------------------------

#: 合成响应面常数（纯数学面声明值，非物理拟合——L2 真机通道挂账对齐面）：
#: f0 = K0/(l·sqrt(εr))（半波谐振标度形态）+谷深 = −K1·(g_ref/g)（隙耦合
#: 单调形态）。
_SURFACE_F0_K_GHZ_MM = 150.0
_SURFACE_G_REF_MM = 0.2
_SURFACE_DIP_K_DB = 24.0


def _finite_number(v: Any) -> float | None:
    """数值收敛（拒 bool/非数值/非有限——#364 判据布尔化纪律；与
    em_bench_service._finite_number 同语义的本模块本地件，不跨模块私引）。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def surface_response(params: Mapping[str, Any]) -> dict[str, float]:
    """B5 合成响应面（确定性纯函数；同输入逐位同输出）。

    params = ``{"l_mm", "eps_r", "g_mm"}``（全正有限，零/负在实数面无定义
    ——fail-closed 拒绝不猜）。返回 ``{"f0_ghz", "dip_db"}``：
    f0_ghz = 150.0/(l_mm·sqrt(eps_r))；dip_db = −24.0·(0.2/g_mm)。
    声明式合成响应面（非物理真值——演示判据的单源确定性 producer；
    任务缺省候选的 response 即本函数产出冻结，hidden 一致性门逐位复核）。
    """
    l_mm = _finite_number(params.get("l_mm"))
    eps_r = _finite_number(params.get("eps_r"))
    g_mm = _finite_number(params.get("g_mm"))
    if l_mm is None or eps_r is None or g_mm is None:
        raise ValueError(
            f"合成响应面参数必须全为有限数值，得到 l_mm={params.get('l_mm')!r}, "
            f"eps_r={params.get('eps_r')!r}, g_mm={params.get('g_mm')!r}")
    if l_mm <= 0.0 or eps_r <= 0.0 or g_mm <= 0.0:
        raise ValueError(
            f"合成响应面参数必须全为正（实数面定义域），得到 l_mm={l_mm!r}, "
            f"eps_r={eps_r!r}, g_mm={g_mm!r}")
    return {
        "f0_ghz": _SURFACE_F0_K_GHZ_MM / (l_mm * math.sqrt(eps_r)),
        "dip_db": -_SURFACE_DIP_K_DB * (_SURFACE_G_REF_MM / g_mm),
    }


def _surface_candidate(target_id: str, params: dict[str, float]) -> dict[str, Any]:
    """B5 缺省候选构造单源：params → response=surface(params)（逐位一致
    by construction——hidden 一致性门的逐位复核即对同函数同输入）。"""
    return {"target_id": target_id, "params": dict(params),
            "response": surface_response(params)}


# ---------------------------------------------------------------------------
# AX-8 ①：spec-to-va runner
# ---------------------------------------------------------------------------

#: 规格要素 kind 闭集（must_include 口径；未知 kind fail-closed 拒收）。
SPEC_ELEMENT_KINDS: tuple[str, ...] = (
    "port", "param", "contribution_lhs",
    "text_must_include", "text_must_not_include",
)


def _derive_spec_elements(spec: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    """结构化规格声明 → must_include 要素清单（确定性派生，预声明映射：
    每端口→port 要素/每参数→param 要素/behavior.contribution_lhs（str 或
    list）→contribution 要素/text_must_include·text_must_not_include→文本
    要素）。要素集为空=任务定义错误（ValueError——空要素集不可判读，
    fail-closed 不猜）。"""
    module_name = spec.get("module_name")
    if not isinstance(module_name, str) or not module_name.strip():
        raise ValueError("spec.module_name 必填（非空 str——判据面模块锚）")
    elements: list[dict[str, Any]] = []
    for p in spec.get("ports") or []:
        if not isinstance(p, Mapping) or not str(p.get("name") or "").strip():
            raise ValueError(f"spec.ports 条目形态非法（须含 name）: {p!r}")
        el: dict[str, Any] = {"element_id": f"port:{p['name']}",
                              "kind": "port", "name": str(p["name"])}
        if p.get("dir") is not None:
            el["dir"] = str(p["dir"])
        elements.append(el)
    for prm in spec.get("params") or []:
        if not isinstance(prm, Mapping) or not str(prm.get("name") or "").strip():
            raise ValueError(f"spec.params 条目形态非法（须含 name）: {prm!r}")
        el = {"element_id": f"param:{prm['name']}",
              "kind": "param", "name": str(prm["name"])}
        if prm.get("type") is not None:
            el["type"] = str(prm["type"])
        if prm.get("default") is not None:
            el["default"] = prm["default"]
        elements.append(el)
    beh = spec.get("behavior") or {}
    if not isinstance(beh, Mapping):
        raise ValueError(f"spec.behavior 形态非法（须映射）: {beh!r}")
    lhs = beh.get("contribution_lhs")
    lhs_items = [lhs] if isinstance(lhs, str) else list(lhs or [])
    for item in lhs_items:
        if not str(item).strip():
            raise ValueError(f"behavior.contribution_lhs 条目空白: {item!r}")
        elements.append({"element_id": f"contrib:{item}",
                         "kind": "contribution_lhs", "lhs": str(item)})
    for tok in beh.get("text_must_include") or []:
        if not str(tok):
            raise ValueError("behavior.text_must_include 条目空白")
        elements.append({"element_id": f"text+:{tok}",
                         "kind": "text_must_include", "token": str(tok)})
    for tok in beh.get("text_must_not_include") or []:
        if not str(tok):
            raise ValueError("behavior.text_must_not_include 条目空白")
        elements.append({"element_id": f"text-:{tok}",
                         "kind": "text_must_not_include", "token": str(tok)})
    if not elements:
        raise ValueError("规格要素集为空（ports/params/behavior 至少声明一项"
                         "——空要素集不可判读，fail-closed）")
    return str(module_name), elements


def _spec_element_hit(el: Mapping[str, Any], doc: Mapping[str, Any] | None,
                      module_name: str, text: str) -> tuple[bool, str]:
    """单要素命中判定（预声明语义）：结构性 kind 走解析文档（解析失败=
    结构性要素全 miss——fail-closed）；text kind 走原文子串（verbatim
    大小写敏感——Verilog-A 正文大小写敏感语言面）。返回 (hit, reason)。"""
    kind = str(el.get("kind"))
    if kind == "text_must_include":
        tok = str(el.get("token"))
        return (tok in text), ("token 在场" if tok in text else "token 缺席")
    if kind == "text_must_not_include":
        tok = str(el.get("token"))
        return (tok not in text), ("禁用 token 已消除" if tok not in text
                                   else "禁用 token 在场（偷步/硬凑）")
    if doc is None:
        return False, "解析失败（结构性要素 fail-closed 全 miss）"
    modules = doc.get("modules") or {}
    body = modules.get(module_name)
    if body is None:
        return False, f"模块 {module_name!r} 不在解析文档"
    if kind == "port":
        name = str(el.get("name"))
        want_dir = el.get("dir")
        for p in body.get("ports") or []:
            if str(p.get("name")) != name:
                continue
            if want_dir is None or str(p.get("dir")) == str(want_dir):
                return True, "端口在场（方向匹配）"
            return False, (f"端口在场但方向不符（解析 {p.get('dir')!r} vs "
                           f"声明 {want_dir!r}）")
        return False, "端口缺席"
    if kind == "param":
        name = str(el.get("name"))
        row = next((q for q in body.get("params") or []
                    if str(q.get("name")) == name), None)
        if row is None:
            return False, "参数缺席"
        want_type = el.get("type")
        if want_type is not None and str(row.get("type")) != str(want_type):
            return False, (f"参数类型不符（解析 {row.get('type')!r} vs "
                           f"声明 {want_type!r}）")
        if "default" in el:
            want = _finite_number(el.get("default"))
            got = _finite_number(row.get("default"))
            if want is None:
                return False, "声明缺省值非有限数值（任务定义面）"
            if got is None:
                return False, ("参数缺省值非纯数值字面量（解析器不可回收"
                               "——fail-closed 判 miss，不猜表达式值）")
            if got != want:
                return False, f"参数缺省值不符（解析 {got!r} vs 声明 {want!r}）"
        return True, "参数在场（类型/缺省匹配）"
    if kind == "contribution_lhs":
        lhs = str(el.get("lhs"))
        lhs_list = [str(c.get("lhs")) for c in body["analog"]["contributions"]]
        if lhs in lhs_list:
            return True, "贡献语句 LHS 在场"
        return False, f"贡献 LHS 缺席（在场={lhs_list}）"
    raise ValueError(f"未知规格要素 kind {kind!r}（闭集={list(SPEC_ELEMENT_KINDS)}）")


def _run_va_spec_to_va(task: BenchTask, ctx: BenchRunContext) -> dict[str, Any]:
    """spec-to-va runner（AX-8 ①）：结构化 .va 规格声明（JSON：模块名/
    端口/参数/行为要素）× 候选 .va 文本 → 解析接受门（gate_pass）+规格
    要素逐项命中（success_rate，must_include 口径）。

    input_spec = ``{"spec": {module_name, ports: [{name, dir?}],
    params: [{name, type?, default?}], behavior: {contribution_lhs?,
    text_must_include?, text_must_not_include?}}, "candidate_va": str}``。

    判据分层：**L1 已实现**（本 runner——veriloga_parser 只读消费+静态
    要素命中）；**L2 挂账**（PSSFSS 实仿真金标——见 :data:`L2_DEFERRAL`，
    本席不伪造 L2 结果）。命中语义（预声明）：结构性要素（port/param/
    contribution_lhs）走解析文档精确匹配（解析失败=结构性要素全 miss
    fail-closed；参数缺省值须纯数值字面量可回收否则 miss）；文本要素
    （text_must_include/text_must_not_include）走原文 verbatim 子串
    （大小写敏感——防偷步 must_not_include 口径，vaBench 思想级重写）。
    解析接受门 passed=全文可解析 ∧ 规格模块名在场（detail 双旗分解）。
    要素 kind 未知 → ValueError（执行失败如实 fail——fail-closed 不猜）。
    """
    del ctx  # 纯文本判据（零 IO 零 cwd 依赖）
    spec = task.input_spec or {}
    inner = spec.get("spec")
    if not isinstance(inner, Mapping):
        raise ValueError(f"input_spec.spec 形态非法（须映射）: {type(inner).__name__}")
    candidate = spec.get("candidate_va")
    if not isinstance(candidate, str) or not candidate.strip():
        raise ValueError("input_spec.candidate_va 必填（非空 str——被评判产出）")
    module_name, elements = _derive_spec_elements(inner)
    parse_ok = True
    parse_error: str | None = None
    doc: dict[str, Any] | None = None
    try:
        doc = parse_veriloga(candidate)
    except Exception as exc:  # VerilogAParseError/词法家法族——解析拒绝=门 fail
        parse_ok = False
        parse_error = f"{type(exc).__name__}: {exc}"
    module_present = bool(doc) and module_name in (doc.get("module_order") or [])
    rows = []
    n_hit = 0
    for el in elements:
        hit, reason = _spec_element_hit(el, doc, module_name, candidate)
        rows.append({"element_id": str(el.get("element_id")),
                     "kind": str(el.get("kind")), "hit": bool(hit),
                     "reason": reason})
        n_hit += 1 if hit else 0
    return {
        "measures": {
            "gate_pass": {"passed": bool(parse_ok and module_present),
                          "gate": "va_parse_accept", "metric": None},
            "success_rate": {"n_ok": n_hit, "n_total": len(elements)},
        },
        "detail": {
            "module_name": module_name, "parse_ok": parse_ok,
            "module_present": bool(module_present),
            "parse_error": parse_error,
            "elements": rows,
            "hit_semantics": ("结构性要素=解析文档精确匹配（解析失败全 miss）/"
                              "文本要素=verbatim 子串（must_include/must_not_"
                              "include 防偷步）——L1 静态级；L2=PSSFSS 金标挂账"),
        },
    }


# ---------------------------------------------------------------------------
# AX-8 ②：tb-generation runner
# ---------------------------------------------------------------------------

def _tb_groups_from_spec(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    """tb 三要素组声明读取（激励/监测/仿真控制——组内 any-of 语义，预声明）：
    每组 ``{element_id, tokens: [必现标记任一], not_tokens?: [禁现标记]}``；
    tokens 空=任务定义错误（ValueError——any-of 空集不可判读）。"""
    groups_raw = spec.get("tb_elements")
    if not isinstance(groups_raw, list) or not groups_raw:
        raise ValueError("input_spec.tb_elements 必填（≥1 组——三要素骨架声明面）")
    groups: list[dict[str, Any]] = []
    for g in groups_raw:
        if not isinstance(g, Mapping):
            raise ValueError(f"tb_elements 条目形态非法: {g!r}")
        tokens = [str(t) for t in (g.get("tokens") or []) if str(t)]
        if not tokens:
            raise ValueError(f"tb_elements[{g.get('element_id')!r}].tokens 空"
                             "（any-of 组空集不可判读，fail-closed）")
        groups.append({
            "element_id": str(g.get("element_id") or f"group{len(groups)}"),
            "tokens": tokens,
            "not_tokens": [str(t) for t in (g.get("not_tokens") or []) if str(t)],
        })
    return groups


def _run_va_tb_generation(task: BenchTask, ctx: BenchRunContext) -> dict[str, Any]:
    """tb-generation runner（AX-8 ②）：给定 DUT .va 判 testbench 骨架完备性
    ——激励/监测/仿真控制三要素静态检查（组内 any-of 标记+组级禁现标记）。

    input_spec = ``{"dut_module": str, "dut_va": str, "candidate_tb": str,
    "tb_elements": [{element_id, tokens, not_tokens?}]}``。

    判据分层：**L1 已实现**（静态标记检查——tb 骨架完备性的快引擎语义，
    标记集由任务声明面预声明：激励源/监测指令/分析控制语句任一组缺位即
    miss）；**L2 挂账**（DUT+tb 真仿真执行——见 :data:`L2_DEFERRAL`）。
    门语义（预声明）：passed = DUT .va 可解析 ∧ 候选 tb 引用 DUT 模块名
    （连接性冒烟——大小写不敏感子串，SPICE 传承口径）。组命中语义：
    tokens 任一在场（大小写不敏感）∧ not_tokens 全部不在场。tb 组声明
    缺失/空 tokens → ValueError（fail-closed）。
    """
    del ctx
    spec = task.input_spec or {}
    dut_module = str(spec.get("dut_module") or "")
    dut_va = spec.get("dut_va")
    candidate_tb = spec.get("candidate_tb")
    if not dut_module.strip():
        raise ValueError("input_spec.dut_module 必填（连接性锚）")
    if not isinstance(dut_va, str) or not dut_va.strip():
        raise ValueError("input_spec.dut_va 必填（DUT 源文本）")
    if not isinstance(candidate_tb, str) or not candidate_tb.strip():
        raise ValueError("input_spec.candidate_tb 必填（被评判产出）")
    groups = _tb_groups_from_spec(spec)
    parse_ok = True
    parse_error: str | None = None
    try:
        parse_veriloga(dut_va)
    except Exception as exc:
        parse_ok = False
        parse_error = f"{type(exc).__name__}: {exc}"
    referenced = dut_module.lower() in candidate_tb.lower()
    rows = []
    n_hit = 0
    blob = candidate_tb.lower()
    for g in groups:
        hit = (any(t.lower() in blob for t in g["tokens"])
               and not any(nt.lower() in blob for nt in g["not_tokens"]))
        rows.append({"element_id": g["element_id"], "hit": bool(hit),
                     "tokens": g["tokens"], "not_tokens": g["not_tokens"]})
        n_hit += 1 if hit else 0
    return {
        "measures": {
            "gate_pass": {"passed": bool(parse_ok and referenced),
                          "gate": "tb_dut_anchor", "metric": None},
            "success_rate": {"n_ok": n_hit, "n_total": len(groups)},
        },
        "detail": {
            "dut_module": dut_module, "dut_parse_ok": parse_ok,
            "dut_module_referenced": bool(referenced),
            "dut_parse_error": parse_error,
            "tb_groups": rows,
            "hit_semantics": ("组内 any-of 标记（大小写不敏感）∧ not_tokens "
                              "全不在场——L1 静态骨架完备性；L2=真仿真挂账"),
        },
    }


# ---------------------------------------------------------------------------
# AX-8 ③：end-to-end runner（spec→va→tb 全链，组合①②判据）
# ---------------------------------------------------------------------------

def _run_va_end_to_end(task: BenchTask, ctx: BenchRunContext) -> dict[str, Any]:
    """end-to-end runner（AX-8 ③）：spec→va→tb 全链——组合①②两族判据
    （同判据名合并测度，预声明组合口径）。

    input_spec = ① 的 ``spec``+``candidate_va`` 与 ② 的 ``candidate_tb``+
    ``tb_elements`` 四键（候选 .va 即全链 DUT 源）。组合语义（预声明）：
    gate_pass passed = 候选 .va 可解析 ∧ 规格模块名在场 ∧ tb 引用模块名
    （三旗分解进 detail）；success_rate 分母 = 规格要素数+tb 组数、分子 =
    两面命中数（组合前两族判据的单一名分母口径——同判据名不重复计权）。
    判据分层：L1 已实现（同①②）；L2 挂账（PSSFSS/真机全链复验——
    :data:`L2_DEFERRAL`）。
    """
    del ctx
    spec = task.input_spec or {}
    inner = spec.get("spec")
    candidate = spec.get("candidate_va")
    candidate_tb = spec.get("candidate_tb")
    if not isinstance(inner, Mapping):
        raise ValueError(f"input_spec.spec 形态非法（须映射）: {type(inner).__name__}")
    if not isinstance(candidate, str) or not candidate.strip():
        raise ValueError("input_spec.candidate_va 必填（全链 DUT 源）")
    if not isinstance(candidate_tb, str) or not candidate_tb.strip():
        raise ValueError("input_spec.candidate_tb 必填（全链 tb 骨架）")
    module_name, elements = _derive_spec_elements(inner)
    groups = _tb_groups_from_spec(spec)
    parse_ok = True
    parse_error: str | None = None
    doc: dict[str, Any] | None = None
    try:
        doc = parse_veriloga(candidate)
    except Exception as exc:
        parse_ok = False
        parse_error = f"{type(exc).__name__}: {exc}"
    module_present = bool(doc) and module_name in (doc.get("module_order") or [])
    referenced = module_name.lower() in candidate_tb.lower()
    rows = []
    n_hit = 0
    for el in elements:
        hit, reason = _spec_element_hit(el, doc, module_name, candidate)
        rows.append({"element_id": str(el.get("element_id")),
                     "kind": str(el.get("kind")), "hit": bool(hit),
                     "reason": reason})
        n_hit += 1 if hit else 0
    group_rows = []
    blob = candidate_tb.lower()
    for g in groups:
        hit = (any(t.lower() in blob for t in g["tokens"])
               and not any(nt.lower() in blob for nt in g["not_tokens"]))
        group_rows.append({"element_id": g["element_id"], "hit": bool(hit)})
        n_hit += 1 if hit else 0
    return {
        "measures": {
            "gate_pass": {"passed": bool(parse_ok and module_present and referenced),
                          "gate": "e2e_chain_anchor", "metric": None},
            "success_rate": {"n_ok": n_hit, "n_total": len(elements) + len(groups)},
        },
        "detail": {
            "module_name": module_name, "parse_ok": parse_ok,
            "module_present": bool(module_present),
            "tb_module_referenced": bool(referenced),
            "parse_error": parse_error,
            "elements": rows, "tb_groups": group_rows,
            "hit_semantics": ("组合①②：规格要素（解析精确匹配/verbatim 文本）+"
                              "tb 组（any-of）单一名分母——L1 全链静态级；"
                              "L2=PSSFSS/真机全链挂账"),
        },
    }


# ---------------------------------------------------------------------------
# AX-8 ④：bugfix runner
# ---------------------------------------------------------------------------

def _run_va_bugfix(task: BenchTask, ctx: BenchRunContext) -> dict[str, Any]:
    """bugfix runner（AX-8 ④）：给定带已知缺陷的 .va（缺陷样例原创合成）
    判修复后候选通过解析（gate_pass）+缺陷点消除（success_rate）。

    input_spec = ``{"broken_va": str, "candidate_va": str,
    "defects": [{defect_id, marker, note?}], "must_keep": [str],
    "module_name"?: str}``。

    判据分层：**L1 已实现**（解析接受+缺陷标记消除/功能保全标记在场——
    静态口径）；**L2 挂账**（修复后真仿真行为复验——:data:`L2_DEFERRAL`）。
    缺陷消除语义（预声明）：defect.marker 子串在候选文本**缺席**=该缺陷
    消除（verbatim 大小写敏感——标记设计须指向缺陷原文形态）；must_keep
    标记在场=功能保全（防"删模块过门"投机解）。成功判据分母 =
    n_defects+n_keeps（分子=已消除+已保全）。broken/candidate 缺文本、
    defects 为空、must_keep 为空 → ValueError（fail-closed：无可判读
    缺陷面/无保全面=任务定义错误）。gate passed = 候选可解析 ∧（声明
    module_name 时）模块在场。
    """
    del ctx
    spec = task.input_spec or {}
    broken = spec.get("broken_va")
    candidate = spec.get("candidate_va")
    if not isinstance(broken, str) or not broken.strip():
        raise ValueError("input_spec.broken_va 必填（已知缺陷源文本）")
    if not isinstance(candidate, str) or not candidate.strip():
        raise ValueError("input_spec.candidate_va 必填（被评判修复产出）")
    defects_raw = spec.get("defects")
    keeps_raw = spec.get("must_keep") or []
    if not isinstance(defects_raw, list) or not defects_raw:
        raise ValueError("input_spec.defects 必填（≥1 条已知缺陷声明）")
    if not keeps_raw:
        raise ValueError("input_spec.must_keep 必填（≥1 条功能保全标记——"
                         "防删模块投机解，fail-closed）")
    defects = []
    for d in defects_raw:
        if not isinstance(d, Mapping) or not str(d.get("marker") or "").strip():
            raise ValueError(f"defects 条目形态非法（须含 marker）: {d!r}")
        defects.append({"defect_id": str(d.get("defect_id")
                                         or f"defect{len(defects)}"),
                        "marker": str(d["marker"]),
                        "note": str(d.get("note") or "")})
    keeps = [str(k) for k in keeps_raw if str(k)]
    module_name = spec.get("module_name")
    parse_ok = True
    parse_error: str | None = None
    doc: dict[str, Any] | None = None
    try:
        doc = parse_veriloga(candidate)
    except Exception as exc:
        parse_ok = False
        parse_error = f"{type(exc).__name__}: {exc}"
    module_present = None
    if isinstance(module_name, str) and module_name.strip():
        module_present = bool(doc) and module_name in (doc.get("module_order") or [])
    gate_passed = parse_ok and (module_present is not False)
    defect_rows = []
    keep_rows = []
    n_ok = 0
    for d in defects:
        eliminated = str(d["marker"]) not in candidate
        defect_rows.append({"defect_id": d["defect_id"],
                            "marker": d["marker"],
                            "eliminated": bool(eliminated),
                            "note": d["note"]})
        n_ok += 1 if eliminated else 0
    for k in keeps:
        present = k in candidate
        keep_rows.append({"marker": k, "present": bool(present)})
        n_ok += 1 if present else 0
    return {
        "measures": {
            "gate_pass": {"passed": bool(gate_passed),
                          "gate": "va_fix_parse_accept", "metric": None},
            "success_rate": {"n_ok": n_ok, "n_total": len(defects) + len(keeps)},
        },
        "detail": {
            "parse_ok": parse_ok, "parse_error": parse_error,
            "module_present": module_present,
            "defects": defect_rows, "must_keep": keep_rows,
            "hit_semantics": ("缺陷标记缺席=消除/must_keep 在场=保全（verbatim "
                              "子串，防删模块投机解）——L1 静态级；L2=修复后"
                              "真仿真行为复验挂账"),
        },
    }


# ---------------------------------------------------------------------------
# B5：inverse_design runner（命中判据=频偏≤tol1+幅度偏差≤tol2 显式口径）
# ---------------------------------------------------------------------------

def _inverse_targets(spec: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """目标规格读取（预声明 schema）：``{target_id: {f0_ghz>0, dip_db,
    tol_freq_rel≥0, tol_dip_db≥0}}``——任一键缺失/非法 → ValueError
    （任务定义错误 fail-closed 不猜）。"""
    targets_raw = spec.get("targets")
    if not isinstance(targets_raw, Mapping) or not targets_raw:
        raise ValueError("input_spec.targets 必填（≥1 目标规格——"
                         "逆设计判据的声明面）")
    targets: dict[str, dict[str, Any]] = {}
    for tid, t in targets_raw.items():
        if not isinstance(t, Mapping):
            raise ValueError(f"targets[{tid!r}] 形态非法: {t!r}")
        f0_t = _finite_number(t.get("f0_ghz"))
        dip_t = _finite_number(t.get("dip_db"))
        tol_f = _finite_number(t.get("tol_freq_rel"))
        tol_d = _finite_number(t.get("tol_dip_db"))
        if f0_t is None or f0_t <= 0.0:
            raise ValueError(f"targets[{tid!r}].f0_ghz 必须为正有限数值"
                             "（相对频偏分母——0/负不可判读）")
        if dip_t is None:
            raise ValueError(f"targets[{tid!r}].dip_db 缺失/非法（幅度轴）")
        if tol_f is None or tol_f < 0.0:
            raise ValueError(f"targets[{tid!r}].tol_freq_rel 必须为 ≥0 有限数值"
                             "（#122：命中容差预声明，缺即 fail-closed）")
        if tol_d is None or tol_d < 0.0:
            raise ValueError(f"targets[{tid!r}].tol_dip_db 必须为 ≥0 有限数值"
                             "（#122：命中容差预声明，缺即 fail-closed）")
        targets[str(tid)] = {"f0_ghz": f0_t, "dip_db": dip_t,
                             "tol_freq_rel": tol_f, "tol_dip_db": tol_d}
    return targets


def _run_inverse_design(task: BenchTask, ctx: BenchRunContext) -> dict[str, Any]:
    """inverse_design runner（B5）：目标响应规格（f0/谷深+预声明容差）×
    候选参数点（响应自带）→ 命中度（success_rate）+合成面一致性门
    （hidden gate_pass，surface_check 声明时）。

    input_spec = ``{"targets": {tid: {f0_ghz, dip_db, tol_freq_rel,
    tol_dip_db}}, "candidates": {cid: {target_id, params, response}},
    "surface_check"?: bool}``。**候选响应来源=任务输入自带**（响应由确定性
    通道产出后 as-recorded 携入——B5 口径：本席判据消费已产出响应；fake/
    openEMS 通道真跑= L2 挂账 :data:`L2_DEFERRAL`）。

    命中判据（预声明显式口径）：freq_dev = |f0_c−f0_t|/f0_t（目标 f0>0
    保证分母合法）≤ tol_freq_rel **且** dip_dev = |dip_c−dip_t|（dB 绝对
    偏差）≤ tol_dip_db → 该候选 hit；success_rate = hit 数/候选数（下界
    极性阈值任务面预声明）。候选 response 形态非法/测度缺失/非有限 →
    该候选计 miss（detail note=invalid_response——**不崩溃**：候选垃圾
    是被评判对象质量，判据如实判 miss；任务定义错误（targets 缺失/容差
    非法/未知 target_id）才 ValueError fail-closed）。

    surface_check=true 时附带 hidden 一致性门（gate_pass，门名
    b5_surface_consistency）：逐候选以 ：func:`surface_response` 重算并与
    声明 response **逐位**比对（合成响应面 demo 任务的单源防伪造面——
    声明值须为同函数同输入产出；位级漂移/编造值=门 fail）。hidden 判据
    的任务层声明在 BenchTask.hidden_criteria（visible 层只出 success_rate
    ——报告面 hidden 只出汇总不出细节，AX-1③ 分层语义）。
    """
    del ctx
    spec = task.input_spec or {}
    targets = _inverse_targets(spec)
    candidates_raw = spec.get("candidates")
    if not isinstance(candidates_raw, Mapping) or not candidates_raw:
        raise ValueError("input_spec.candidates 必填（≥1 候选参数点——"
                         "空候选集不可判读，fail-closed）")
    rows = []
    n_ok = 0
    for cid, cand in candidates_raw.items():
        cid_s = str(cid)
        if not isinstance(cand, Mapping):
            raise ValueError(f"candidates[{cid_s!r}] 形态非法（须映射）: {cand!r}")
        tid = str(cand.get("target_id") or "")
        tgt = targets.get(tid)
        if tgt is None:
            raise ValueError(f"candidates[{cid_s!r}].target_id={tid!r} 未知"
                             "（目标锚必须命中 targets 声明面——fail-closed）")
        resp = cand.get("response")
        f0_c = _finite_number(resp.get("f0_ghz")) if isinstance(resp, Mapping) else None
        dip_c = _finite_number(resp.get("dip_db")) if isinstance(resp, Mapping) else None
        note = ""
        freq_dev: float | None = None
        dip_dev: float | None = None
        if f0_c is None or dip_c is None:
            note = "invalid_response（response.f0_ghz/dip_db 缺失/非法——判 miss 不崩溃）"
            hit = False
        else:
            freq_dev = abs(f0_c - tgt["f0_ghz"]) / tgt["f0_ghz"]
            dip_dev = abs(dip_c - tgt["dip_db"])
            hit = freq_dev <= tgt["tol_freq_rel"] and dip_dev <= tgt["tol_dip_db"]
        rows.append({"candidate_id": cid_s, "target_id": tid,
                     "freq_dev_rel": freq_dev, "dip_dev_db": dip_dev,
                     "tol_freq_rel": tgt["tol_freq_rel"],
                     "tol_dip_db": tgt["tol_dip_db"],
                     "hit": bool(hit), "note": note})
        n_ok += 1 if hit else 0
    measures: dict[str, Any] = {
        "success_rate": {"n_ok": n_ok, "n_total": len(candidates_raw)},
    }
    detail: dict[str, Any] = {
        "candidates": rows,
        "hit_semantics": ("freq_dev_rel≤tol_freq_rel ∧ dip_dev_db≤tol_dip_db"
                          "（预声明显式口径）——响应=任务输入自带 as-recorded；"
                          "L2=fake/openEMS 真跑产响应挂账"),
    }
    if bool(spec.get("surface_check")):
        cons_rows = []
        all_consistent = True
        for cid, cand in candidates_raw.items():
            ok = False
            note = ""
            if isinstance(cand, Mapping):
                params = cand.get("params")
                resp = cand.get("response")
                if isinstance(params, Mapping) and isinstance(resp, Mapping):
                    try:
                        expected = surface_response(params)
                        f0_d = _finite_number(resp.get("f0_ghz"))
                        dip_d = _finite_number(resp.get("dip_db"))
                        ok = (f0_d is not None and dip_d is not None
                              and f0_d == expected["f0_ghz"]
                              and dip_d == expected["dip_db"])
                        if not ok:
                            note = ("声明 response 与合成响应面逐位不一致"
                                    "（编造值/位级漂移/非数值）")
                    except (KeyError, TypeError, ValueError) as exc:
                        note = f"参数不可评估: {exc}"
                else:
                    note = "params/response 形态非法（须映射）"
            else:
                note = "候选形态非法"
            all_consistent = all_consistent and ok
            cons_rows.append({"candidate_id": str(cid), "consistent": bool(ok),
                              "note": note})
        measures["gate_pass"] = {"passed": bool(all_consistent),
                                 "gate": "b5_surface_consistency",
                                 "metric": None}
        detail["surface_check"] = {
            "rows": cons_rows,
            "semantics": ("逐候选 surface_response(params) 重算与声明 response "
                          "逐位相等（合成面单源防伪造——demo 任务口径）"),
        }
    return {"measures": measures, "detail": detail}


# ---------------------------------------------------------------------------
# 注册面（显式安装——import 期不注册，见模块 docstring 注册形态节）
# ---------------------------------------------------------------------------

#: 五族 runner 映射（installer/测试注入单源；键序=ANALOG_BENCH_FAMILIES 序）。
VA_BENCH_RUNNERS: dict[str, Any] = {
    VA_FAMILY_SPEC_TO_VA: _run_va_spec_to_va,
    VA_FAMILY_TB_GENERATION: _run_va_tb_generation,
    VA_FAMILY_END_TO_END: _run_va_end_to_end,
    VA_FAMILY_BUGFIX: _run_va_bugfix,
    B5_FAMILY_INVERSE_DESIGN: _run_inverse_design,
}


def install_va_bench_runners() -> tuple[str, ...]:
    """显式安装五族 runner 到 em_bench_service 运行注册表（**挂账处方**：
    主代合流面执行——同笔更新 BENCH_FAMILIES 词表+test_em_bench.py 迁移钉，
    Q-X43/Q-X55 词表同步迁移纪律先例；import 期不注册以保护进程级闭集钉）。

    幂等（已注册且同函数对象 → 跳过）；同名异函数冲突拒收（ValueError——
    注册表闭集禁止静默覆盖）。返回本次新安装的 family 键元组（注册序）。
    """
    from rfauto.service import em_bench_service as em

    installed: list[str] = []
    for fam in ANALOG_BENCH_FAMILIES:
        fn = VA_BENCH_RUNNERS[fam]
        existing = em._RUNNER_REGISTRY.get(fam)
        if existing is None:
            em.register_runner(fam)(fn)
            installed.append(fam)
        elif existing is fn:
            continue
        else:
            raise ValueError(
                f"family {fam!r} 已被其他 runner 占用（{existing!r}）——"
                "注册表闭集禁止静默覆盖")
    return tuple(installed)


def va_bench_admission_catalog() -> dict[str, dict[str, Any]]:
    """准入门探针供给面（R-01 admit_bench_task/admit_bench_tasks 的 oracle
    必需品）：``{task_id: {"oracle_measures": measures}}``——oracle=本模块
    runner 对缺省任务输入的**实测测度**（确定性重算，非手工编造；noop 探针
    走 NOOP_PROBE_MEASURES 单源，本目录不覆盖）。

    消费处方（合流面/CLI 叶）：``em.default_va_tasks = default_va_bench_tasks()
    ``→ ``cat = va_bench_admission_catalog()`` → ``em.admit_bench_tasks(
    tasks, oracle_measures_by_task={tid: cat[tid]["oracle_measures"] ...})``。
    """
    catalog: dict[str, dict[str, Any]] = {}
    for t in default_va_bench_tasks():
        fn = VA_BENCH_RUNNERS[t.family]
        run = fn(t, BenchRunContext())
        measures = run.get("measures")
        if not isinstance(measures, Mapping):
            raise RuntimeError(f"task={t.task_id} oracle 测度形态非法（须映射）")
        catalog[t.task_id] = {"oracle_measures": dict(measures)}
    return catalog


# ---------------------------------------------------------------------------
# 缺省任务集（7 任务：AX-8 四族各 1 + B5 演示 3；阈值全部预声明——本函数
# 即预声明锚，改动阈值=改门口径须同笔更新测试断言；不入 default_bench_tasks
# 的 15 锚钉，合流面决策）
# ---------------------------------------------------------------------------

#: AX-8 演示 .va 样例（本席原创合成——非任何外部仓文本，思想级重写纪律）：
#: 纯电阻行为模型双端模块（L1 解析面演示用）。
_VA_GOOD_SAMPLE = """
// rfauto em_bench AX-8 L1 synthetic sample (seat R-08 original)
`include "disciplines.vams"

module rfauto_bench_resonator (p, n);
  inout p, n;
  electrical p, n;

  parameter real r0_ohm = 50.0 from [1.0:inf);
  parameter real f0_ghz = 2.4 from (0.0:inf);

  analog begin
    V(p, n) <+ r0_ohm * I(p, n);
  end
endmodule
"""

#: AX-8 ① 反例候选：解析通过但规格要素双 miss（f0_ghz 参数缺席+禁用算子
#: idt( 在场——偷步/硬凑投机解必败面）。
_VA_SPEC_NEG_CANDIDATE = """
module rfauto_bench_resonator (p, n);
  inout p, n;
  electrical p, n;

  parameter real r0_ohm = 50.0 from [1.0:inf);

  analog begin
    V(p, n) <+ r0_ohm * I(p, n) + idt(V(p, n));
  end
endmodule
"""

#: AX-8 演示 testbench 骨架（本席原创合成——L1 静态三要素标记面）。
_TB_GOOD_SAMPLE = """
* rfauto em_bench AX-8 testbench skeleton (seat R-08 original)
.tran 0 10n 1p
Vsrc in 0 SIN(0 1 2.4g)
Xdut in out rfauto_bench_resonator
Rterm out 0 50
.probe v(in) v(out)
.end
"""

#: AX-8 ② 反例候选 tb：激励在场但监测/仿真控制两要素缺位+未引用 DUT 模块名。
_TB_NEG_SAMPLE = """
Vsrc in 0 SIN(0 1 2.4g)
Rterm out 0 50
"""

#: AX-8 ④ bugfix 缺陷源（本席原创合成缺陷——两处已知语义缺陷，解析可过）：
#: ①电流取样反向 I(n,p)（无源电阻变有源负阻）；②未声明标识符 gain_k
#: （幽灵因子）。修复口径=反向取样改正+删除幽灵因子。
_VA_BROKEN_SAMPLE = """
// rfauto em_bench AX-8 bugfix defective sample (seat R-08 original)
`include "disciplines.vams"

module rfauto_bench_resonator (p, n);
  inout p, n;
  electrical p, n;

  parameter real r0_ohm = 50.0 from [1.0:inf);

  analog begin
    V(p, n) <+ r0_ohm * I(n, p) * gain_k;
  end
endmodule
"""

#: AX-8 ④ 修复候选（缺陷双消除+功能保全）。
_VA_FIXED_SAMPLE = """
// rfauto em_bench AX-8 bugfix fixed sample (seat R-08 original)
`include "disciplines.vams"

module rfauto_bench_resonator (p, n);
  inout p, n;
  electrical p, n;

  parameter real r0_ohm = 50.0 from [1.0:inf);

  analog begin
    V(p, n) <+ r0_ohm * I(p, n);
  end
endmodule
"""

#: AX-8 演示规格声明（结构化 JSON——模块名/端口/参数/行为要素）。
_VA_SPEC_DECL = {
    "module_name": "rfauto_bench_resonator",
    "ports": [{"name": "p", "dir": "inout"}, {"name": "n", "dir": "inout"}],
    "params": [{"name": "r0_ohm", "type": "real", "default": 50.0},
               {"name": "f0_ghz", "type": "real", "default": 2.4}],
    "behavior": {
        "contribution_lhs": "V(p, n)",
        "text_must_include": ["analog"],
        "text_must_not_include": ["idt(", "ddt("],
    },
}

#: AX-8 演示 tb 三要素组声明（标记集预声明——L1 静态骨架口径）。
_TB_ELEMENTS_DECL = [
    {"element_id": "excitation", "tokens": ["sin(", "pulse(", "pwl(", "dc "]},
    {"element_id": "monitor", "tokens": [".probe", ".print", ".measure", ".save"]},
    {"element_id": "sim_control", "tokens": [".tran", ".ac", ".dc", ".sp"]},
]


def default_va_bench_tasks() -> list[BenchTask]:
    """模拟侧任务族 7 任务（AX-8 四族各 1+B5 演示 3；判据阈值全部预声明）。

    每任务：grader_notes（AX-1① rubric 附注）+反例变体（AX-1④ ≥1——
    判据必须对其判 fail，check_negative_variants 自检）+data_source 溯源
    （L1 判据内核+L2 挂账声明）。B5 演示任务的候选 response 全部由
    :func:`surface_response` 同函数产出冻结（逐位可复现 by construction
    ——hidden 一致性门同函数复核）。
    """
    tasks: list[BenchTask] = []
    tasks.append(BenchTask(
        task_id="va-spec-to-va",
        family=VA_FAMILY_SPEC_TO_VA,
        title="spec-to-va：结构化规格→候选 .va 解析接受+规格要素逐项命中（AX-8①）",
        input_spec={"spec": _VA_SPEC_DECL, "candidate_va": _VA_GOOD_SAMPLE},
        criteria=[
            BenchCriterion(name="gate_pass", threshold=None),
            BenchCriterion(name="success_rate", threshold=_VA_HIT_RATE_MIN),
        ],
        grader_notes=BenchGraderNotes(
            correct_core=[
                "候选 .va 被 veriloga_parser 接受且规格模块名在场（解析接受门）",
                "规格要素逐项命中：端口名+方向/参数名+类型+缺省值（纯数值字面量"
                "可回收）/贡献 LHS 精确匹配（V(p, n) 渲染口径）/must_include 文本"
                "在场/must_not_include 禁用算子缺席（防偷步）",
            ],
            common_errors=[
                "解析失败（词法/注释未闭合）——结构性要素 fail-closed 全 miss",
                "参数缺省值写成表达式（解析器不可回收数值→miss，fail-closed 不猜）",
                "用禁用算子（idt(/ddt()硬凑行为——must_not_include 判 miss",
                "端口方向不符（inout 声明成 input/output）",
            ],
            partial_credit="spec_score=命中要素数/要素总数（success_rate 同一"
                           "分子分母；unknown 要素不计）",
        ),
        negative_variants=[
            BenchNegativeVariant(
                variant_id="spec-neg-banned-op-and-missing-param",
                input_spec={"spec": _VA_SPEC_DECL,
                            "candidate_va": _VA_SPEC_NEG_CANDIDATE},
                note="反例：f0_ghz 参数缺席+禁用算子 idt( 在场（解析通过但要素"
                     "双 miss——success_rate=6/8<1.0 判 fail；AX-1④ 反例面）",
            ),
        ],
        data_source="core/veriloga_parser.parse_veriloga（Q-X80 只读消费）结构化"
                    "解析+静态要素命中=L1 快引擎；L2 金标晋升=PSSFSS 实仿真复核"
                    "（挂账见 em_bench_analog_service.L2_DEFERRAL——本席零 PSSFSS"
                    " 调用不伪造）；样例=本席原创合成（思想级重写零搬运）",
    ))

    tasks.append(BenchTask(
        task_id="va-tb-generation",
        family=VA_FAMILY_TB_GENERATION,
        title="tb-generation：DUT→testbench 骨架完备性三要素静态检查（AX-8②）",
        input_spec={
            "dut_module": "rfauto_bench_resonator",
            "dut_va": _VA_GOOD_SAMPLE,
            "candidate_tb": _TB_GOOD_SAMPLE,
            "tb_elements": _TB_ELEMENTS_DECL,
        },
        criteria=[
            BenchCriterion(name="gate_pass", threshold=None),
            BenchCriterion(name="success_rate", threshold=_VA_HIT_RATE_MIN),
        ],
        grader_notes=BenchGraderNotes(
            correct_core=[
                "DUT .va 可解析且候选 tb 引用 DUT 模块名（连接性冒烟门）",
                "三要素组齐备：激励源标记（SIN(/PULSE(/PWL(/DC ）任一在场+监测"
                "指令（.probe/.print/.measure/.save）任一在场+仿真控制（.tran/"
                ".ac/.dc/.sp）任一在场——组内 any-of 语义（骨架完备性）",
            ],
            common_errors=[
                "tb 未引用 DUT 模块名（连接性断裂——DUT 悬空）",
                "监测/仿真控制要素缺位（只有激励=不可观测也不可执行的骨架）",
                "组内标记全缺（空骨架）",
            ],
            partial_credit="spec_score=命中组数/组数（success_rate 同一分子分母）",
        ),
        negative_variants=[
            BenchNegativeVariant(
                variant_id="tb-neg-monitor-and-control-missing",
                input_spec={
                    "dut_module": "rfauto_bench_resonator",
                    "dut_va": _VA_GOOD_SAMPLE,
                    "candidate_tb": _TB_NEG_SAMPLE,
                    "tb_elements": _TB_ELEMENTS_DECL,
                },
                note="反例：监测/仿真控制两要素缺位+未引用 DUT 模块名（门与命中率"
                     "双 fail——不可观测不可执行骨架必败面）",
            ),
        ],
        data_source="veriloga_parser 只读消费（DUT 可解析性）+静态标记组检查（"
                    "标记集任务面预声明）=L1 快引擎；L2=DUT+tb 真仿真执行挂账"
                    "（L2_DEFERRAL）；tb 样例=本席原创合成",
    ))

    tasks.append(BenchTask(
        task_id="va-end-to-end",
        family=VA_FAMILY_END_TO_END,
        title="end-to-end：spec→va→tb 全链（组合①②判据单一名分母；AX-8③）",
        input_spec={
            "spec": _VA_SPEC_DECL,
            "candidate_va": _VA_GOOD_SAMPLE,
            "candidate_tb": _TB_GOOD_SAMPLE,
            "tb_elements": _TB_ELEMENTS_DECL,
        },
        criteria=[
            BenchCriterion(name="gate_pass", threshold=None),
            BenchCriterion(name="success_rate", threshold=_VA_HIT_RATE_MIN),
        ],
        grader_notes=BenchGraderNotes(
            correct_core=[
                "全链门：候选 .va 可解析∧规格模块名在场∧tb 引用模块名（三旗）",
                "组合命中率=（规格要素命中+tb 组命中）/（要素数+组数）——"
                "组合①②判据的单一名分母口径",
            ],
            common_errors=[
                "候选 .va 词法损坏（全链断头——结构性要素 fail-closed 全 miss）",
                "tb 断链（模块名未引用）——门三旗缺一即 fail",
                "只过 va 不过 tb（或反之）——组合分母暴露半成品",
            ],
            partial_credit="spec_score=（要素+组）命中数/总数（success_rate "
                           "同一分子分母）",
        ),
        negative_variants=[
            BenchNegativeVariant(
                variant_id="e2e-neg-lexical-broken-va",
                input_spec={
                    "spec": _VA_SPEC_DECL,
                    "candidate_va": _VA_GOOD_SAMPLE.replace(
                        "analog begin", "analog begin /* 未闭合注释"),
                    "candidate_tb": _TB_GOOD_SAMPLE,
                    "tb_elements": _TB_ELEMENTS_DECL,
                },
                note="反例：候选 .va 块注释未闭合（解析拒绝——门 fail+结构性要素"
                     "全 miss 必败面）",
            ),
        ],
        data_source="组合①② runner（同判据名合并测度）=L1 全链静态级；"
                    "L2=PSSFSS/真机全链复验挂账（L2_DEFERRAL）；样例=本席原创合成",
    ))

    tasks.append(BenchTask(
        task_id="va-bugfix",
        family=VA_FAMILY_BUGFIX,
        title="bugfix：已知缺陷 .va 修复判读（解析接受+缺陷点消除+功能保全；AX-8④）",
        input_spec={
            "broken_va": _VA_BROKEN_SAMPLE,
            "candidate_va": _VA_FIXED_SAMPLE,
            "module_name": "rfauto_bench_resonator",
            "defects": [
                {"defect_id": "current-sense-reversed", "marker": "I(n, p)",
                 "note": "电流取样反向（I(n,p)=−I(p,n)）——无源电阻变有源负阻"},
                {"defect_id": "undeclared-gain-factor", "marker": "gain_k",
                 "note": "未声明标识符 gain_k 引用（幽灵因子——行为模型编译面"
                         "真实缺陷形态）"},
            ],
            "must_keep": ["V(p, n) <+ ", "r0_ohm"],
        },
        criteria=[
            BenchCriterion(name="gate_pass", threshold=None),
            BenchCriterion(name="success_rate", threshold=_VA_HIT_RATE_MIN),
        ],
        grader_notes=BenchGraderNotes(
            correct_core=[
                "修复后候选可解析且模块名在场（解析接受门）",
                "两缺陷标记全部消除（I(n, p) 反向取样/gain_k 幽灵因子）",
                "功能保全标记在场（V(p, n) <+ 贡献语句/r0_ohm 参数——防删模块"
                "投机解）",
            ],
            common_errors=[
                "只修一处（成功率 3/4<1.0 判 fail——不凑绿）",
                "删掉贡献语句或参数过门（must_keep 判 miss）",
                "换模块名绕过判读（module_name 门 fail）",
            ],
            partial_credit="spec_score=（已消除缺陷+已保全标记）/（缺陷数+保全"
                           "数）（success_rate 同一分子分母）",
        ),
        negative_variants=[
            BenchNegativeVariant(
                variant_id="bugfix-neg-noop-fix",
                input_spec={
                    "broken_va": _VA_BROKEN_SAMPLE,
                    "candidate_va": _VA_BROKEN_SAMPLE,
                    "module_name": "rfauto_bench_resonator",
                    "defects": [
                        {"defect_id": "current-sense-reversed", "marker": "I(n, p)",
                         "note": "电流取样反向（I(n,p)=−I(p,n)）——无源电阻变有源"
                                 "负阻"},
                        {"defect_id": "undeclared-gain-factor", "marker": "gain_k",
                         "note": "未声明标识符 gain_k 引用（幽灵因子）"},
                    ],
                    "must_keep": ["V(p, n) <+ ", "r0_ohm"],
                },
                note="反例：候选=缺陷源原样（no-op 修复——缺陷零消除，"
                     "success_rate=2/4=0.5<1.0 判 fail；AX-1④ 反例面）",
            ),
        ],
        data_source="veriloga_parser 只读消费（修复后解析接受）+缺陷标记静态判读="
                    "L1 快引擎；L2=修复后真仿真行为复验挂账（L2_DEFERRAL）；"
                    "缺陷样例=本席原创合成（两处语义缺陷，解析可过——非词法损坏）",
    ))

    # ── B5 演示三任务（合成响应面，逐位可复现）──────────────────────────
    tasks.append(BenchTask(
        task_id="inverse-design-surface-halfwave",
        family=B5_FAMILY_INVERSE_DESIGN,
        title="逆设计演示①：半波谐振合成面单目标命中度（2 命中/1 频偏 miss；"
              "命中率下界 0.5）",
        input_spec={
            "targets": {"t_main": {"f0_ghz": 2.4, "dip_db": -20.0,
                                   "tol_freq_rel": 0.02, "tol_dip_db": 2.5}},
            "candidates": {
                "c_hit_l30": _surface_candidate(
                    "t_main", {"l_mm": 30.0, "eps_r": 4.34, "g_mm": 0.24}),
                "c_hit_l31": _surface_candidate(
                    "t_main", {"l_mm": 31.0, "eps_r": 4.06, "g_mm": 0.25}),
                "c_freq_miss": _surface_candidate(
                    "t_main", {"l_mm": 28.0, "eps_r": 4.4, "g_mm": 0.24}),
            },
            "surface_check": True,
        },
        criteria=[BenchCriterion(name="success_rate",
                                 threshold=_B5_HIT_RATE_MIN_MIXED)],
        hidden_criteria=[BenchCriterion(name="gate_pass", threshold=None)],
        envelope={
            "l_mm": EnvelopeBound(min=10.0, max=60.0),
            "eps_r": EnvelopeBound(min=2.0, max=12.0),
            "g_mm": EnvelopeBound(min=0.05, max=1.0),
        },
        grader_notes=BenchGraderNotes(
            correct_core=[
                "命中判据（预声明显式口径）：freq_dev=|f0_c−f0_t|/f0_t≤tol_freq_rel"
                "（2%）∧ dip_dev=|dip_c−dip_t|≤tol_dip_db（2.5dB）",
                "命中率 2/3≥0.5 下界（混合候选面——频偏 miss 候选如实计分母）",
            ],
            common_errors=[
                "响应值编造（hidden 一致性门逐位复核 fail——合成面单源防伪造）",
                "response 形态非法/测度缺失（判 miss 不崩溃——候选垃圾是被评判"
                "对象质量）",
                "只比频偏漏幅度轴（双轴显式口径缺一即 miss）",
            ],
            partial_credit="spec_score=命中候选数/候选数（success_rate 同一分子"
                           "分母；invalid 候选计 miss）",
        ),
        negative_variants=[
            BenchNegativeVariant(
                variant_id="b5-neg-all-freq-miss",
                input_spec={
                    "targets": {"t_main": {"f0_ghz": 2.4, "dip_db": -20.0,
                                           "tol_freq_rel": 0.02,
                                           "tol_dip_db": 2.5}},
                    "candidates": {
                        "c_off_a": _surface_candidate(
                            "t_main", {"l_mm": 28.0, "eps_r": 4.4, "g_mm": 0.24}),
                        "c_off_b": _surface_candidate(
                            "t_main", {"l_mm": 33.0, "eps_r": 4.4, "g_mm": 0.24}),
                    },
                    "surface_check": True,
                },
                note="反例：双候选全频偏越界（f0≈2.554/2.169 相对偏差 >2%——"
                     "命中率 0/2<0.5 判 fail；AX-1④ 反例面）",
            ),
        ],
        data_source="surface_response（本模块声明式合成响应面——纯数学面，逐位"
                    "可复现；非物理真值）+目标/容差任务面预声明（#122）=L1 判据"
                    "消费已产出响应；L2=fake/openEMS 通道真跑产响应再生任务（"
                    "L2_DEFERRAL）；envelope=B3 包络声明（l_mm/eps_r/g_mm——"
                    "评估点首现胜口径，批量逐点包络挂账）",
    ))

    tasks.append(BenchTask(
        task_id="inverse-design-surface-strict",
        family=B5_FAMILY_INVERSE_DESIGN,
        title="逆设计演示②：严容差双候选全命中（阈值 1.0；hidden 一致性门"
              "防伪造反例）",
        input_spec={
            "targets": {"t_3g": {"f0_ghz": 3.0, "dip_db": -18.0,
                                 "tol_freq_rel": 0.01, "tol_dip_db": 1.0}},
            "candidates": {
                "s_exact": _surface_candidate(
                    "t_3g", {"l_mm": 25.0, "eps_r": 4.0, "g_mm": 4.8 / 18.0}),
                "s_near": _surface_candidate(
                    "t_3g", {"l_mm": 25.5, "eps_r": 3.9, "g_mm": 0.28}),
            },
            "surface_check": True,
        },
        criteria=[BenchCriterion(name="success_rate",
                                 threshold=_B5_HIT_RATE_MIN_STRICT)],
        hidden_criteria=[BenchCriterion(name="gate_pass", threshold=None)],
        grader_notes=BenchGraderNotes(
            correct_core=[
                "严容差（频偏 1%/幅度 1dB）下双候选全命中（success_rate=1.0）",
                "hidden 一致性门：声明 response 与 surface_response(params) "
                "逐位相等（合成面单源——编造值/位级漂移即门 fail）",
            ],
            common_errors=[
                "伪造 response 数值凑命中（visible 命中但 hidden 门 fail——"
                "verdict 仍 fail，AX-1③ 分层语义）",
                "容差内边界理解错（≤ 恰等含——恰等判 pass）",
            ],
            partial_credit="spec_score=命中候选数/候选数",
        ),
        negative_variants=[
            BenchNegativeVariant(
                variant_id="b5-neg-fabricated-response",
                input_spec={
                    "targets": {"t_3g": {"f0_ghz": 3.0, "dip_db": -18.0,
                                         "tol_freq_rel": 0.01,
                                         "tol_dip_db": 1.0}},
                    "candidates": {
                        "s_fabricated": {
                            "target_id": "t_3g",
                            "params": {"l_mm": 25.5, "eps_r": 3.9, "g_mm": 0.28},
                            "response": {"f0_ghz": 3.0, "dip_db": -18.0},
                        },
                    },
                    "surface_check": True,
                },
                note="反例：response 编造为恰好达标值（l=25.5/eps_r=3.9 的真实"
                     "合成面 f0≈2.979——visible 命中率 1/1 通过但 hidden 一致性"
                     "门逐位复核 fail→任务 verdict fail；不伪造不凑绿）",
            ),
        ],
        data_source="surface_response（声明式合成面单源）+hidden gate_pass="
                    "AX-1③ hidden/visible 分层消费（防伪造门在隐藏层——报告面"
                    "只出汇总）；L2=fake/openEMS 真跑产响应挂账（L2_DEFERRAL）",
    ))

    tasks.append(BenchTask(
        task_id="inverse-design-surface-multi-target",
        family=B5_FAMILY_INVERSE_DESIGN,
        title="逆设计演示③：双目标（2GHz/4GHz）三候选各按 target_id 命中"
              "（阈值 1.0）",
        input_spec={
            "targets": {
                "t_2g": {"f0_ghz": 2.0, "dip_db": -16.0,
                         "tol_freq_rel": 0.02, "tol_dip_db": 2.0},
                "t_4g": {"f0_ghz": 4.0, "dip_db": -16.0,
                         "tol_freq_rel": 0.02, "tol_dip_db": 2.0},
            },
            "candidates": {
                "a_2g_l36": _surface_candidate(
                    "t_2g", {"l_mm": 36.0, "eps_r": 4.34, "g_mm": 0.3}),
                "b_4g_l18": _surface_candidate(
                    "t_4g", {"l_mm": 18.0, "eps_r": 4.34, "g_mm": 0.3}),
                "c_4g_l175": _surface_candidate(
                    "t_4g", {"l_mm": 17.5, "eps_r": 4.6, "g_mm": 0.27}),
            },
            "surface_check": True,
        },
        criteria=[BenchCriterion(name="success_rate",
                                 threshold=_B5_HIT_RATE_MIN_STRICT)],
        hidden_criteria=[BenchCriterion(name="gate_pass", threshold=None)],
        grader_notes=BenchGraderNotes(
            correct_core=[
                "多目标批：候选按 target_id 锚定目标规格逐一判命中"
                "（同预声明双轴口径）；三候选全命中（success_rate=1.0）",
                "未知 target_id=任务定义错误（fail-closed ValueError——不猜）",
            ],
            common_errors=[
                "候选锚错目标（错锚即频偏 miss——判 fail 不崩溃）",
                "目标规格容差缺失（fail-closed——#122 缺阈值不猜）",
            ],
            partial_credit="spec_score=命中候选数/候选数",
        ),
        negative_variants=[
            BenchNegativeVariant(
                variant_id="b5-neg-wrong-target-anchor",
                input_spec={
                    "targets": {
                        "t_2g": {"f0_ghz": 2.0, "dip_db": -16.0,
                                 "tol_freq_rel": 0.02, "tol_dip_db": 2.0},
                        "t_4g": {"f0_ghz": 4.0, "dip_db": -16.0,
                                 "tol_freq_rel": 0.02, "tol_dip_db": 2.0},
                    },
                    "candidates": {
                        "a_2g_l36": _surface_candidate(
                            "t_2g", {"l_mm": 36.0, "eps_r": 4.34, "g_mm": 0.3}),
                        "b_4g_l18": _surface_candidate(
                            "t_4g", {"l_mm": 18.0, "eps_r": 4.34, "g_mm": 0.3}),
                        "c_misanchored": _surface_candidate(
                            "t_2g", {"l_mm": 17.5, "eps_r": 4.6, "g_mm": 0.27}),
                    },
                    "surface_check": True,
                },
                note="反例：第三候选错锚 t_2g（真实 f0≈3.996 对 2.0 目标相对"
                     "偏差 ~99.8%——命中率 2/3<1.0 判 fail；AX-1④ 反例面）",
            ),
        ],
        data_source="surface_response（声明式合成面）+多目标 target_id 锚定判据="
                    "L1 消费已产出响应；L2=fake/openEMS 真跑产响应挂账"
                    "（L2_DEFERRAL）",
    ))
    return tasks
