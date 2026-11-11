"""设计回放与总结报告（rfauto-design-report/v1，aurora_o T-O5，2026-11-01）。

用户需求（PLAN_DRAFT §〇 第 5 条原文）："设计回放和总结：设计完之后出具
一个简单的设计报告"——**回放**（轨迹）+ **总结**（最终设计与门判读）+
**简单**（单文件可读 md）。规格=single source
``runs/aurora_o/report_spec/REPORT_SPEC.md``（384 行，六节/公式/门表全钉），
本模块按其实现；公式不在此复述第二遍（注释只标规格节号）。

组合式 schema（规格 §1.2）：顶层六新节（goals/trajectory/final_design/
diagrams/tradeoff/repro）+ ``base_report`` 节（=
:func:`rfauto.service.report_render.build_report_model` 产物原样嵌入，
``rfauto-report/v1`` 零变化——扩键走金快照成本为零）。provenance 纪律
延伸：整棵模型断言 :func:`report_render.bare_number_fields` 判零；source
词法三类（规格 §1.2）：``文件名:JSON 路径``（湖直读）/ ``derived:<公式
id>@REPORT_SPEC §n``（确定性派生，公式在规格钉死）/ ``service:<函数名>``
（复用面产出）。

红线对齐：

1. **零 LLM 零网络**（规格 §1.3.3）：渲染全确定性模板，同输入逐字节同
   输出（唯一豁免=base_report.identification.generated_at 时间戳行）；
2. **缺产物如实降级**（#105/#122）：每节 ``status: ok|missing|skipped``，
   missing 必附 note，不虚构占位数字；门表缺键=UNKNOWN 不凑 PASS；
3. **只读消费**（规格 §1.3.4）：对 run 目录零改写；唯一写面=design_report.md
   自身与 diagrams/ 附件（均声明产物落点，manifest 不含它们→untracked
   信息级，不判 stale——runs_verify_service 三态语义已核实）；
4. **数值只在确定性内核**（铁律 7）：门表判定零公式复制——逐目标单元素
   拆分调 :func:`rfauto.core.objectives.SpecEvaluator.evaluate_objectives`
   （cost 语义单源）；轨迹派生量（bsf/auc_norm/conv_ratio/improvements）
   按 REPORT_SPEC §2·轨迹公式实现；**缺键≠PASS**（#364-④ falsy-0 家法：
   evaluate_objectives 对缺键目标静默贡献 0，必须逐目标判键在位）。

§④ 链路级数据识别键清单（规格 §五.3 授权 T-O5 首版钉死）：v1 识别
(a) 顶层 ``chain.json``/``link_chain.json`` 根为非空数组；(b) 任一顶层
``*.json`` dict 的 ``chain`` 键值为非空数组——数组元素须含
``name``/``gain_db``/``nf_db`` 三键（diagram_service 级 schema）。
普遍优化族 run（wilkinson/branchline 等）湖内无此形态→如实 missing+
手工出图命令指引，不猜 chain、不造数字。

§④ ADS 前仿反标注图接入（aurora_o o_ads 件3，T-O4 已落地）：run 目录
顶层 ``*_circuit.drawio``（ads-circuit run 反标注产物，annot_sim 指标层）
只读扫描——与链路级识别独立（无 chain 数据也照扫）；命中即入 attachments
+ ``ads_sim`` 节，正文以相对链接引用（annot_sim 每卡带 source/sim_ref/
unit，provenance 图版）；未命中如实注记生成入口，不猜不造。

T-O9 附件面（2026-11-01）：§④ ok 态附件节点带 ``rel_path``（相对 run
目录）且 generate_design_report 按报告落点注入 ``rel_link``——报告正文
以 ``[rel_link](rel_link)`` 相对链接引用附件（round-trip：从报告所在
目录解析即达附件；不引外网 viewer，零外网红线）。

⑤b Pareto 前沿节（aurora_p C1，2026-11-01，REPORT_SPEC §五.2 v2 扩展位
落地）：顶层第七节 ``pareto``（组合式增量，单目标 run 各节零变化）。
多目标判据与双源消费（与 ui_service.pareto_view 同口径）：源 A=
``results/pareto_front.json``（nsga2 run 前沿产物，optimizer E9 落盘）
直读；源 B=trials 现算（配方 objectives ≥2，目标向量=逐目标违约量，
SpecEvaluator 单目标拆分，约束取 trial 审计 ``constraint_values``）。
支配/超体积/膝点/弱单调全部 :mod:`rfauto.optimization.pareto_tools`
单源（零公式复制，铁律 7）；散点 PNG 附件落 ``diagrams/``（声明产物
落点，确定性逐字节）；单目标 run → 节如实 ``single-objective run: N/A``
（不空不炸）；目标键缺失 → UNKNOWN（缺键≠数字，#364-④ 家法）。

⑤c 版本对账节（aurora_p C2，2026-11-01，REPORT_SPEC §五.2 "refine 链
design_diff 版本对账节" v2 扩展位落地）：**可选** diff 对象——
:func:`build_design_report_model` 的 ``diff_run_dir`` /
:func:`generate_design_report` 的 ``diff_run_id``（CLI 叶可选第二位置参数
BASE_RUN_ID）。a=对比基线 run、b=本 run，"从 base 到本 run 改了什么"。
两侧最终设计声明=§③ 同款选择语义（trial 文件 cost 最小确定性重导
:func:`_pick_best_trial` 单源 / 单评族 results/metrics.json）；参数面与
指标面差异各一次调 :func:`rfauto.service.design_diff_service.
design_version_diff`（数字全部单源逐位，本模块只注入 source 键满足
provenance 门，铁律 7）。降级三态钉死（#122）：未传 diff 对象→节**不
出现**（模型无 ``diff`` 键，单 run 模型/md 逐字节零变化）；对比 run
目录不存在→``status=missing``；任一侧声明不可得→``status=missing``
如实注记哪侧。设计稿=runs/aurora_p/c2/DIFF_DESIGN.md。

外发安全面（aurora_o o_ads 件3）：md 正文零 run 绝对路径——头部 run
目录行与 §⑥ ``reports render`` 命令均以 ``runs/<run_id>`` 相对形态渲染
（绝对路径只保留在模型面 run_ref.run_dir，md 渲染段省略；⑤c 对账节的
base/本 run 引用同样只用 run 目录名）。"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "DESIGN_REPORT_SCHEMA",
    "build_design_report_model",
    "evaluate_objective_gates",
    "generate_design_report",
    "render_design_report_md",
    "replay_trajectory",
]

#: 报告 schema 标识（规格 §1.2；组合式新 schema，不动 rfauto-report/v1）
DESIGN_REPORT_SCHEMA = "rfauto-design-report/v1"

#: 派生公式 source 词法（规格 §1.2 三类之二；公式 id 与规格节号绑定）
_DERIV_TRAJ = "derived@REPORT_SPEC §2·轨迹"
_DERIV_GATES = "derived:objective_gates@REPORT_SPEC §2·门表"
_DERIV_FINAL = "derived:final_design@REPORT_SPEC §2·门表"
_DERIV_TRADEOFF = "derived@REPORT_SPEC §2·敏感性"

#: §④ 手工出图命令模板（规格 §2·电路图 missing 行为；真实存在的 T-O1 叶）
_DIAGRAM_MANUAL_CMD = (
    "rfauto diagram link --chain @chain.json --out runs/<run_id>/diagrams/"
    "link_summary.drawio --json"
)

#: Pearson r 低样本警示阈值（规格 §2·敏感性：n<12 强制警示）
_PEARSON_MIN_N_WARN = 12

#: §⑥ 复现命令清单（规格 §2·复现：全部真实存在叶，只组装不改语义）
_REPRO_COMMANDS = (
    ("rfauto replay {run_id}",
     "复现本 run（快照重跑 + plugin/schema/git 版本核对 + freshness 门）",
     "service/api/reporting.py::replay_run"),
    ("rfauto repro export {run_id}",
     "导出复现包（snapshot/meta/sparams/provenance.json/reproduce.py）",
     "service/api/reporting.py::repro_export"),
    ("rfauto runs verify {run_id}",
     "收官指纹复核（fresh/stale/legacy）",
     "runs_verify_service.verify_run"),
    ("rfauto design-report {run_id} --json",
     "本报告再生成（自引）",
     "T-O5 新叶（本模块 generate_design_report）"),
    ("rfauto reports render runs/{run_id}",
     "既有报告面（单评族 run 可用；优化族无 results/metrics.json 不适用）",
     "report_render.render_run_report"),
)

#: §⑥ 环境指纹键（meta.json 逐键 source；缺失键不造——样例手稿形态）
_ENV_KEYS = (
    "git_sha", "package_version", "plugin_version", "schema_version",
    "aedt_version", "ads_version", "seed", "python_version", "os",
    "pip_freeze_sha", "optuna_seed",
)


# ── 小工具（全部确定性） ────────────────────────────────────────────────────


def _fmt_cell(value: Any) -> str:
    """md 表格单元格显示格式：fmt_value 单源（.6g）+ 管道符转义
    （verdict_summary_service._fmt_val 家法）。"""
    from rfauto.service.report_render import fmt_value

    return fmt_value(value).replace("|", "\\|").replace("\n", " ")


def _load_json(path: Path) -> tuple[Any, str]:
    """读单 JSON；返回 (数据, 错误串)。缺失/损坏→(None, 原因)（#105 不崩）。"""
    if not path.is_file():
        return None, f"{path.name} 不在场"
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except (OSError, ValueError) as exc:
        return None, f"{path.name} 不可读: {exc}"


def _num(value: Any) -> float | None:
    """数值收敛（bool 不算数值）；非有限→None。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _sorted_trial_files(run_dir: Path) -> tuple[list[Path], list[str]]:
    """trials/trial_*.json 数值序（trial_number 语义序；字典序会把 trial_10
    排到 trial_2 前——al_service.py:154 先例）。不可解析文件名沉底按名排。
    返回 (文件表, 坏名注记)。"""
    trials_dir = run_dir / "trials"
    if not trials_dir.is_dir():
        return [], []
    notes: list[str] = []
    pairs: list[tuple[int, str, Path]] = []
    for path in trials_dir.glob("trial_*.json"):
        stem = path.stem.split("_")[-1]
        try:
            pairs.append((int(stem), "", path))
        except ValueError:
            notes.append(f"trial 文件名序号不可解析（沉底按名序）: {path.name}")
            pairs.append((1 << 30, path.name, path))
    pairs.sort(key=lambda item: (item[0], item[1]))
    return [p for _, _, p in pairs], notes


def _trial_sort_key_number(record: dict[str, Any], fallback: int) -> int:
    """trial 记录的序号（trial_number 键优先；缺键用文件名序 fallback）。"""
    number = record.get("trial_number")
    if isinstance(number, int) and not isinstance(number, bool):
        return number
    return fallback


def _pearson_r(xs: list[float], ys: list[float]) -> float | None:
    """标准样本 Pearson r（规格 §2·敏感性钉死公式；n<2 或零方差→undefined）。

    与 numpy corrcoef 同值（#118：裁判=独立数值对照，tests 与本实现同源
    对拍真实湖样本与合成已知量）。
    """
    n = len(xs)
    if n < 2 or len(ys) != n:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0.0 or syy <= 0.0:
        return None
    return sxy / math.sqrt(sxx * syy)


# ── ① replay_trajectory：§② 轨迹节（规格公式钉死） ────────────────────────


def replay_trajectory(run_dir: str | Path) -> dict[str, Any]:
    """trials/trial_N.json → §② 轨迹节（数值排序/bsf/改进事件/auc_norm/
    conv_ratio/n_trial_files；重复评估复用 convergence_service 同口径）。

    Returns:
        ok 信封（本函数不失败；缺/空 → ok=True 且 status="missing"——
        降级不是错误，规格 §四签名草案）。数值载体节点全部带 source
        （bare_number_fields 判零）。

    公式（REPORT_SPEC §2·轨迹，钉死）::

        bsf_i = min(c₁..c_i)
        auc_norm = (Σᵢ bsf_i) / (N · bsf_1)   ∈(0,1]；1.0=零改进
        conv_ratio = (bsf_1 − bsf_N) / bsf_1
        improvements = [(i, bsf_i, bsf_i−bsf_{i-1}) | bsf_i < bsf_{i-1}]

    约束：N≤1 或 bsf_1==0 → 对应量 status="undefined"（不除零不凑数）。
    """
    run_path = Path(run_dir)  # PathLike 入参第一行收敛（#140）
    files, name_notes = _sorted_trial_files(run_path)
    notes = list(name_notes)
    traj_source = "derived:n_trial_files@REPORT_SPEC §2·轨迹"
    undefined_auc = {"status": "undefined", "value": None,
                     "source": f"{_DERIV_TRAJ} auc_norm"}
    undefined_conv = {"status": "undefined", "value": None,
                      "source": f"{_DERIV_TRAJ} conv_ratio"}
    empty_dup = {"n_evals": 0, "n_duplicate_evals": 0,
                 "source": "service:convergence_service.duplicate_evals"}
    if not files:
        return ok_envelope(
            status="missing",
            note="trials/ 目录缺失或无 trial_*.json（单次 run 族无优化轨迹）",
            n_trial_files=0,
            trials=[],
            best_sofar=[],
            improvements=[],
            auc_norm=dict(undefined_auc),
            conv_ratio=dict(undefined_conv),
            duplicates=dict(empty_dup),
            source=traj_source,
        )

    trials: list[dict[str, Any]] = []
    for idx, path in enumerate(files):
        data, err = _load_json(path)
        rel = f"trials/{path.name}"
        if data is None or not isinstance(data, dict):
            notes.append(f"trial 文件不可读（如实跳过该文件，不计入轨迹）: {err}")
            continue
        params = data.get("params")
        cost = _num(data.get("cost"))
        if not isinstance(params, dict) or cost is None:
            notes.append(
                f"trial 文件缺 params/cost 或值非有限（如实跳过）: {rel}")
            continue
        number = _trial_sort_key_number(data, idx)
        params_node = dict(params)
        params_node["source"] = f"{rel}:params"
        trials.append({
            "trial": number,
            "params": params_node,
            "cost": cost,
            "source": rel,
        })

    if not trials:
        return ok_envelope(
            status="missing",
            note="trials/ 有文件但全部不可读（params/cost 缺失或非有限）",
            n_trial_files=len(files),
            trials=[],
            best_sofar=[],
            improvements=[],
            auc_norm=dict(undefined_auc),
            conv_ratio=dict(undefined_conv),
            duplicates=dict(empty_dup),
            source=traj_source,
        )

    # bsf / auc_norm / conv_ratio / improvements（规格公式逐字实现）
    bsf_series: list[float] = []
    best = math.inf
    for row in trials:
        best = min(best, row["cost"])
        bsf_series.append(best)
    improvements = [
        {"trial": trials[i]["trial"], "best_sofar": bsf_series[i],
         "delta": bsf_series[i] - bsf_series[i - 1],
         "source": f"{_DERIV_TRAJ} improvements"}
        for i in range(1, len(trials)) if bsf_series[i] < bsf_series[i - 1]
    ]
    n = len(trials)
    bsf_first = bsf_series[0]
    if n > 1 and bsf_first != 0.0:
        auc_norm = {"status": "ok",
                    "value": sum(bsf_series) / (n * bsf_first),
                    "source": f"{_DERIV_TRAJ} auc_norm"}
    else:
        auc_norm = dict(undefined_auc)
    if n > 1 and bsf_first != 0.0:
        conv_ratio = {"status": "ok",
                      "value": (bsf_first - bsf_series[-1]) / bsf_first,
                      "source": f"{_DERIV_TRAJ} conv_ratio"}
    else:
        conv_ratio = dict(undefined_conv)

    # 重复评估：convergence_service 同口径复用（接受裸 trial 记录序列）
    dup_raw: dict[str, Any] = {}
    try:
        from rfauto.service.convergence_service import duplicate_evals

        dup_raw = duplicate_evals([
            {"params": {k: v for k, v in row["params"].items()
                        if k != "source"},
             "value": row["cost"], "number": row["trial"]}
            for row in trials])
    except Exception as exc:  # 观测面兜底（#105）：记账统计失败不炸报告
        notes.append(f"重复评估诊断不可用（非阻断）: {exc}")
    duplicates = {
        "n_evals": int(dup_raw.get("n_evals") or 0),
        "n_duplicate_evals": int(dup_raw.get("n_duplicate_evals") or 0),
        "source": "service:convergence_service.duplicate_evals",
    }

    return ok_envelope(
        status="ok",
        note="；".join(notes),
        n_trial_files=n,
        trials=trials,
        best_sofar=bsf_series,
        improvements=improvements,
        auc_norm=auc_norm,
        conv_ratio=conv_ratio,
        duplicates=duplicates,
        source=traj_source,
    )


# ── ② evaluate_objective_gates：§③ 门表（缺键≠PASS） ──────────────────────


def evaluate_objective_gates(
    metrics: dict[str, Any] | None,
    objectives: list[dict[str, Any]],
    *,
    metrics_source: str = "metrics",
    objectives_source: str = "recipe.snapshot.yaml:objectives",
) -> dict[str, Any]:
    """配方目标门表：逐目标单元素拆分调 core/objectives（cost 语义单源，
    零公式复制）；缺键→UNKNOWN（**缺键≠PASS**，#364-④ 家法测试钉）。

    Args:
        metrics: 最终设计的指标 dict（键=compute_metrics 产物惯例）。
        objectives: 配方 objective dict 列表（recipe.snapshot.yaml 原文形态）。
        metrics_source: 观测值出处词头（如 ``trials/trial_6.json:metrics``）。
        objectives_source: 目标规格出处词头。

    Returns:
        ``{ok, rows, overall, n_pass, n_fail, n_unknown, notes, source}``——
        行 ``{objective, metric, op, threshold, observed, violation,
        judgment, source}``；汇总判定（规格 §2·门表）：全 PASS→PASS；有
        FAIL→FAIL；无 FAIL 有 UNKNOWN→UNKNOWN（不凑绿 #122）。
    """
    from rfauto.core.objectives import Objective, SpecEvaluator

    rows: list[dict[str, Any]] = []
    notes: list[str] = []
    metrics = metrics if isinstance(metrics, dict) else {}
    for idx, obj_spec in enumerate(objectives or []):
        obj_source = f"{objectives_source}[{idx}]"
        if not isinstance(obj_spec, dict):
            notes.append(f"目标 #{idx} 非 dict（如实 UNKNOWN）")
            rows.append({
                "objective": idx, "metric": "", "op": "", "threshold": None,
                "observed": None, "violation": None, "judgment": "UNKNOWN",
                "source": obj_source,
            })
            continue
        metric = str(obj_spec.get("metric", ""))
        raw_op = obj_spec.get("op", "")
        op = str(getattr(raw_op, "value", raw_op))
        try:
            obj = Objective(
                metric=metric,
                band=list(obj_spec.get("band") or []),
                op=op,
                value=obj_spec.get("value"),
                weight=obj_spec.get("weight", 1.0),
                length_mm=obj_spec.get("length_mm"),
            )
        except Exception as exc:  # pydantic 校验负例：如实 UNKNOWN 不炸
            notes.append(f"目标 #{idx}（{metric}）规格不可解析: {exc}")
            rows.append({
                "objective": idx, "metric": metric, "op": op,
                "threshold": obj_spec.get("value"), "observed": None,
                "violation": None, "judgment": "UNKNOWN",
                "source": obj_source,
            })
            continue
        # 候选键在位判定（#195 口径同源）：全未命中→UNKNOWN——绝不能把
        # evaluate_objectives 对缺键的静默 0 当达标（falsy-0 陷阱）
        candidates = SpecEvaluator.metric_key_candidates(obj.metric, obj.op)
        observed: Any = None
        observed_key = ""
        for key in candidates:
            if key in metrics:
                observed = metrics[key]
                observed_key = key
                break
        if observed is None:
            rows.append({
                "objective": idx, "metric": metric,
                "op": str(obj.op.value), "threshold": obj.value,
                "observed": None, "violation": None, "judgment": "UNKNOWN",
                "source": f"{obj_source}（候选键全未命中: {', '.join(candidates)}）",
            })
            continue
        violation = SpecEvaluator.evaluate_objectives(metrics, [obj])
        rows.append({
            "objective": idx, "metric": metric,
            "op": str(obj.op.value), "threshold": obj.value,
            "observed": observed, "violation": violation,
            "judgment": "PASS" if violation == 0.0 else "FAIL",
            "source": f"{metrics_source}.{observed_key} vs {obj_source}",
        })
    judgments = [str(r["judgment"]) for r in rows]
    if rows and all(j == "PASS" for j in judgments):
        overall = "PASS"
    elif "FAIL" in judgments:
        overall = "FAIL"
    else:
        overall = "UNKNOWN"
    return ok_envelope(
        rows=rows,
        overall=overall,
        n_pass=sum(1 for j in judgments if j == "PASS"),
        n_fail=sum(1 for j in judgments if j == "FAIL"),
        n_unknown=sum(1 for j in judgments if j == "UNKNOWN"),
        notes=notes,
        source=_DERIV_GATES,
    )


def _pick_best_trial(raw_trials: list[dict[str, Any]]) -> dict[str, Any]:
    """最终设计选择（规格 §2·门表钉死）：有 constraint_values → 全部违约
    ≤0 中 cost 最小（全不可行→all_infeasible）；无约束→全部 cost 最小
    （并列取 trial_number 小者）。入参=build 侧装载的 ``{trial, raw}``
    序（已按 trial 数值序）。返回选择节点（含 all_infeasible 旗标）。

    可行性判定单源= :func:`_constraint_violations_of`（list/dict 双格式
    归一，与 §⑤b pareto 节共用，禁两份解析逻辑）。写侧形态出处
    （optimization/optimizer.py）：``_record_constraints``（:358-383）把
    逐约束违约量 list[float] 写入 trial 审计 ``constraint_values``
    （set_user_attr :378；湖审计落盘 :594-595，仅约束 run 写）——元素=
    第 i 条约束（配方 constraints 表序）的违约量，>0=违约、0=可行边界
    （docstring :363-374）；``feasible`` 旗标 ``all(v <= 0.0)``（:379）
    同口径。C1L1 前本函数只认 dict 形，list 形被判无约束→真实约束 run
    最终设计可能选中违约点（夹具盲区型缺口，aurora_p C1L1 清偿）。
    分量非数值/NaN→``_num`` None→按违约处理（与写侧 ``nan <= 0`` 恒
    False、feasible=False 同口径）；缺失/空向量视为可行（与 dict 路径
    既有口径及 optimizer ``_trial_is_feasible`` ``vals is None → True``
    旧 study 兼容一致；dict 路径逐位零变化）。"""
    constrained = any(
        isinstance(tr["raw"].get("constraint_values"), (dict, list, tuple))
        for tr in raw_trials)
    if constrained:
        feasible = [
            tr for tr in raw_trials
            if all(v is not None and v <= 0.0
                   for v in _constraint_violations_of(tr["raw"]))
        ]
    else:
        feasible = list(raw_trials)
    if not feasible:
        return {"status": "all_infeasible", "trial": None, "cost": None,
                "constrained": constrained, "source": _DERIV_FINAL}
    def _sort_key(tr: dict) -> tuple:
        c = _num(tr["raw"].get("cost"))
        # #364-④ 家法：合法 0.0 不得被 `or math.inf` 顶替（W6-1 审查 P1 实证：
        # cost=0.0 可行 trial 被顶成 inf 选错）——None（缺失/非有限）才回退。
        return (math.inf if c is None else c, tr["trial"])

    best = min(feasible, key=_sort_key)
    return {"status": "ok", "trial": best["trial"],
            "cost": _num(best["raw"].get("cost")),
            "constrained": constrained, "source": _DERIV_FINAL}


# ── §④ 电路图：chain 识别键清单（模块 docstring 同账） ─────────────────────

_CHAIN_FILES = ("chain.json", "link_chain.json")
_CHAIN_REQUIRED_KEYS = ("name", "gain_db", "nf_db")


def _detect_link_chain(run_dir: Path) -> tuple[list[dict[str, Any]], str]:
    """湖内链路级级表识别（规格 §2·电路图；识别键清单见模块 docstring）。

    Returns:
        (chain 表, 出处串)；未识别→([], "")。识别到但 schema 不合→
        ([], 错误注记)——不猜不补，交由 missing 降级注记。
    """
    candidates: list[tuple[str, Any]] = []
    for fname in _CHAIN_FILES:
        data, _ = _load_json(run_dir / fname)
        if data is not None:
            candidates.append((fname, data))
    for path in sorted(run_dir.glob("*.json")):
        if path.name in _CHAIN_FILES:
            continue
        data, _ = _load_json(path)
        if isinstance(data, dict) and "chain" in data:
            candidates.append((f"{path.name}:chain", data.get("chain")))
    chain_notes: list[str] = []
    for source, data in candidates:
        if not isinstance(data, list) or not data:
            chain_notes.append(f"{source} 形态非非空数组")
            continue
        ok_shape = all(
            isinstance(item, dict)
            and all(key in item for key in _CHAIN_REQUIRED_KEYS)
            for item in data)
        if not ok_shape:
            chain_notes.append(
                f"{source} 级 schema 不合三键 "
                f"{'/'.join(_CHAIN_REQUIRED_KEYS)}")
            continue
        return [dict(item) for item in data], source
    return [], "；".join(chain_notes)


def _rel_link(attach_path: str, base_dir: Path) -> str:
    """报告内附件相对链接（T-O9，posix 分隔；round-trip 契约=从链接所在
    目录解析即达附件：缺省落点 run 目录下 report↔diagrams/ 子目录相对，
    外置 output 时含 ``..`` 段）。跨盘等 relpath 不可得情形退化为空串
    （渲染端回退 run 相对路径，#105 不阻断）。"""
    try:
        return Path(os.path.relpath(attach_path, base_dir)).as_posix()
    except ValueError:
        return ""


def _build_diagrams_section(run_dir: Path, *, with_diagrams: bool,
                            anomalies: list[str]) -> dict[str, Any]:
    """§④ 电路图总结（链路框图 T-O1 generate_link_diagram + ADS 前仿反标注
    图 T-O4 接入；引用不复制——正文只出信封回显三标量，逐级 G/NF 不进正文）。

    T-O9 附件面：附件节点增 ``rel_path``（相对 run 目录的 posix 路径，
    模型面稳定形态；报告正文相对链接 ``rel_link`` 由 generate_design_report
    按报告落点计算后注入）。

    ADS 前仿反标注图（aurora_o o_ads 件3，T-O4 已落）：run 目录顶层
    ``*_circuit.drawio``（ads-circuit run 产物，annot_sim 指标层）只读
    扫描，与链路级识别独立（无 chain 数据也照扫）；命中即追加进
    attachments 并落 ``ads_sim`` 节，正文以相对链接引用。"""
    section: dict[str, Any] = {
        "source": "service:diagram_service.generate_link_diagram",
        "status": "missing",
        "note": "",
        "attachments": [],
        "summary": {"n_stages": 0, "gain_total_db": None, "nf_total_db": None,
                    "source": "service:diagram_service.generate_link_diagram"},
    }
    if not with_diagrams:
        section["status"] = "skipped"
        section["note"] = "调用方禁用图产物（with_diagrams=False）"
        section["ads_sim"] = {
            "status": "skipped", "n_circuits": 0, "names": [],
            "note": "调用方禁用图产物（with_diagrams=False）——只读扫描一并禁用",
            "source": "design_replay_report §④ ads_sim 扫描",
        }
        return section

    # ADS 前仿反标注图只读扫描（与链路级识别独立；sorted=确定性）
    circuit_files = sorted(run_dir.glob("*_circuit.drawio"))
    section["ads_sim"] = {
        "status": "ok" if circuit_files else "missing",
        "n_circuits": len(circuit_files),
        "names": [p.name for p in circuit_files],
        "note": ("ads-circuit run 反标注产物（annot_sim 指标层，每卡带 "
                 "source/sim_ref/unit）" if circuit_files else
                 "本 run 无 ads-circuit run 产物（<族>_circuit.drawio）——"
                 "生成入口 rfauto ads-circuit diagram → draw.io Edit Data "
                 "改值 → rfauto ads-circuit run --out-dir runs/<run_id>"),
        "source": "ads-circuit run 产物湖直读（design_replay_report §④ 扫描）",
    }
    for cf in circuit_files:
        section["attachments"].append({
            "name": cf.name,
            "path": str(cf),
            "rel_path": _rel_link(str(cf), run_dir),
            "generator": "ads_circuit_run（ads-circuit run 反标注 annot_sim）",
            "exists": cf.is_file(),
            "source": "ads-circuit run 产物（湖直读）",
        })

    chain, chain_source = _detect_link_chain(run_dir)
    if not chain:
        note = (
            "run 湖内无链路级级表数据（识别键清单=design_replay_report 模块 "
            "docstring：chain.json/link_chain.json 或 *.json 的 chain 键，"
            "级三键 name/gain_db/nf_db）——不猜 chain、不造数字。"
            "手工出图入口：" + _DIAGRAM_MANUAL_CMD)
        if chain_source:
            note = f"识别到 chain 候选但降级（{chain_source}）。" + note
            anomalies.append(f"§④ 链路数据识别降级：{chain_source}")
        section["note"] = note
        return section
    out_dir = run_dir / "diagrams"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "link_summary.drawio"
    try:
        from rfauto.service.diagram_service import generate_link_diagram

        result = generate_link_diagram(chain, out_path,
                                       title=f"link summary {run_dir.name}")
    except Exception as exc:  # 生成器故障如实降级（#105）
        section["note"] = f"链路图生成不可用（非阻断）: {exc}"
        return section
    if not result.get("ok"):
        section["note"] = ("识别到链路级数据但生成器拒绝（"
                           + "; ".join(str(e) for e in result.get("errors") or [])
                           + "）——如实降级不造数字")
        anomalies.append("§④ 链路图生成器拒绝（schema/数值校验未过）")
        return section
    section["status"] = "ok"
    section["attachments"].append({
        "name": out_path.name,
        "path": str(out_path),
        "rel_path": _rel_link(str(out_path), run_dir),
        "generator": "diagram_service.generate_link_diagram",
        "exists": out_path.is_file(),
        "source": "service:generate_link_diagram",
    })
    section["summary"] = {
        "n_stages": result.get("n_stages"),
        "gain_total_db": result.get("gain_total_db"),
        "nf_total_db": result.get("nf_total_db"),
        "source": "service:diagram_service.generate_link_diagram（信封回显）",
    }
    return section


# ── §①/§③/§⑤/§⑥ 节构建 ───────────────────────────────────────────────────


def _unit_of(key: str, spec: dict[str, Any] | None = None) -> str:
    """展示单位：参数 spec 显式 unit 优先，回退键名后缀推断
    （report_render._unit_from_key 单源复用）。"""
    if isinstance(spec, dict) and isinstance(spec.get("unit"), str):
        return spec["unit"]
    from rfauto.service.report_render import _unit_from_key

    return _unit_from_key(key)


def _build_goals_section(
    meta: dict[str, Any] | None,
    recipe: dict[str, Any] | None,
    recipe_missing_reason: str,
) -> tuple[dict[str, Any], list[str]]:
    """§① 设计目标与配方摘要（三张表：基本信息/名义参数与优化范围/目标规格
    + setup；recipe 缺失→missing 降级，§③ 门表随之 UNKNOWN）。"""
    anomalies: list[str] = []
    basic: list[dict[str, Any]] = []
    if isinstance(meta, dict):
        for key in ("model", "adapter", "study_name", "status", "timestamp",
                    "git_sha"):
            if key in meta:
                basic.append({"name": key, "value": meta[key],
                              "source": f"meta.json:{key}"})
    if not isinstance(recipe, dict):
        return {
            "source": "recipe.snapshot.yaml",
            "status": "missing",
            "note": f"配方快照缺失（{recipe_missing_reason}）——"
                    "优化边界/目标规格不可判，§③ 门表全 UNKNOWN",
            "basic": basic,
            "params": [],
            "objectives": [],
            "setup": [],
        }, ["配方快照缺失：§① 降级（目标规格不可判）"]
    params_rows: list[dict[str, Any]] = []
    recipe_params = recipe.get("params")
    opt_params: dict[str, Any] = {}
    optimization = recipe.get("optimization")
    if isinstance(optimization, dict) and isinstance(
            optimization.get("params"), dict):
        opt_params = optimization["params"]
    if isinstance(recipe_params, dict):
        for key in sorted(recipe_params):
            spec = recipe_params[key]
            nominal = spec.get("value") if isinstance(spec, dict) else spec
            bounds = opt_params.get(key)
            low: Any = None
            high: Any = None
            bound_src = ""
            if isinstance(bounds, dict):
                low = bounds.get("low")
                high = bounds.get("high")
                bound_src = f" / optimization.params.{key}"
            unit = _unit_of(key, spec if isinstance(spec, dict) else None)
            params_rows.append({
                "param": key, "nominal": nominal, "unit": unit,
                "low": low, "high": high,
                "source": f"recipe.snapshot.yaml:params.{key}{bound_src}",
            })
    objectives_rows: list[dict[str, Any]] = []
    objectives = recipe.get("objectives")
    if isinstance(objectives, list):
        for idx, obj in enumerate(objectives):
            if not isinstance(obj, dict):
                continue
            value = obj.get("value")
            op = str(getattr(obj.get("op", ""), "value", obj.get("op", "")))
            if isinstance(value, list) and len(value) == 2:
                spec_disp = f"落在 [{_fmt_cell(value[0])}, {_fmt_cell(value[1])}]"
            elif op == "max_below":
                spec_disp = f"≤ {_fmt_cell(value)}"
            elif op == "min_above":
                spec_disp = f"≥ {_fmt_cell(value)}"
            else:
                spec_disp = _fmt_cell(value)
            band = obj.get("band") or []
            band_disp = (f"{_fmt_cell(band[0])}–{_fmt_cell(band[1])}"
                         if len(band) == 2 else "全带")
            objectives_rows.append({
                "objective": idx + 1,
                "metric": str(obj.get("metric", "")),
                "op": op,
                "spec": spec_disp,
                "band": band_disp,
                "source": f"recipe.snapshot.yaml:objectives[{idx}]",
            })
    setup_rows: list[dict[str, Any]] = []
    setup = recipe.get("setup")
    if isinstance(setup, dict):
        freq = setup.get("freq_range_ghz")
        if isinstance(freq, list) and len(freq) == 2:
            setup_rows.append({
                "name": "freq_range_ghz",
                "value": f"{_fmt_cell(freq[0])}–{_fmt_cell(freq[1])} GHz",
                "source": "recipe.snapshot.yaml:setup.freq_range_ghz",
            })
        if "points" in setup:
            setup_rows.append({
                "name": "points", "value": setup["points"],
                "source": "recipe.snapshot.yaml:setup.points",
            })
    return {
        "source": "recipe.snapshot.yaml",
        "status": "ok",
        "note": "",
        "basic": basic,
        "params": params_rows,
        "objectives": objectives_rows,
        "setup": setup_rows,
    }, anomalies


def _gates_stub(note: str) -> dict[str, Any]:
    """门表空档形态（全 UNKNOWN；缺产物不凑 PASS）。"""
    return {"rows": [], "overall": "UNKNOWN", "n_pass": 0, "n_fail": 0,
            "n_unknown": 0, "notes": [note], "source": _DERIV_GATES}


def _build_final_design_section(
    run_dir: Path,
    meta: dict[str, Any] | None,
    raw_trials: list[dict[str, Any]],
    trajectory_trials: list[dict[str, Any]],
    recipe: dict[str, Any] | None,
    anomalies: list[str],
) -> dict[str, Any]:
    """§③ 最终设计与 verdict 门表（最终设计=湖内确定性重导：trial 文件按
    cost 最小；meta 只存 best_metrics 不存 best_params——与 meta.metrics
    交叉核对，规格 §〇.1 两事实）。"""
    section: dict[str, Any] = {
        "source": _DERIV_FINAL,
        "status": "missing",
        "note": "",
        "best": {"trial": None, "cost": None, "constrained": False,
                 "source": _DERIV_FINAL},
        "rows": [],
        "cross_check": {"status": "missing", "note": "无最终指标可核对",
                        "source": "meta.json:metrics"},
        "gates": _gates_stub("无最终指标可判"),
        "consistency": {"status": "na", "note": "", "source": _DERIV_FINAL},
        "verdict_md": {"status": "missing",
                       "note": "不在场（本 run 无战役判定档案）",
                       "markdown": "",
                       "source": "service:verdict_summary_md"},
    }
    objectives: list[dict[str, Any]] = []
    if isinstance(recipe, dict) and isinstance(recipe.get("objectives"), list):
        objectives = [o for o in recipe["objectives"] if isinstance(o, dict)]

    metrics: dict[str, Any] | None = None
    metrics_source = ""

    if raw_trials:
        selection = _pick_best_trial(raw_trials)
        section["best"] = selection
        if selection["status"] == "all_infeasible":
            section["note"] = ("全部 trial 违约 >0（不可行）：最终设计表如实"
                               "留空（语义与 optimizer E10 best_feasible 对齐）")
            anomalies.append("§③ 全部 trial 不可行：最终设计留空")
            return section
        best_trial = selection["trial"]
        best_raw = next(tr["raw"] for tr in raw_trials
                        if tr["trial"] == best_trial)
        best_record = next(t for t in trajectory_trials
                           if t["trial"] == best_trial)
        rel = best_record["source"]
        metrics = dict(best_raw.get("metrics") or {})
        metrics_source = f"{rel}:metrics"
        for key in sorted(best_raw.get("params") or {}):
            section["rows"].append({
                "item": key, "value": best_raw["params"][key],
                "unit": _unit_of(key), "source": f"{rel}:params.{key}",
            })
        section["rows"].append({
            "item": "cost", "value": best_record["cost"], "unit": "",
            "source": f"{rel}:cost",
        })
        if isinstance(best_raw.get("metrics"), dict):
            for key in sorted(best_raw["metrics"]):
                section["rows"].append({
                    "item": key, "value": best_raw["metrics"][key],
                    "unit": _unit_of(key),
                    "source": f"{rel}:metrics.{key}",
                })
    else:
        # 单评族兜底（A 族）：results/metrics.json 的 params/metrics/cost
        results, err = _load_json(run_dir / "results" / "metrics.json")
        if isinstance(results, dict):
            metrics = dict(results.get("metrics") or {})
            metrics_source = "results/metrics.json:metrics"
            section["note"] = ("无 trials（单次 run 族）："
                               "最终设计=results/metrics.json")
            for key in sorted(results.get("params") or {}):
                section["rows"].append({
                    "item": key, "value": results["params"][key],
                    "unit": _unit_of(key),
                    "source": f"results/metrics.json:params.{key}",
                })
            if results.get("cost") is not None:
                section["rows"].append({
                    "item": "cost", "value": results.get("cost"), "unit": "",
                    "source": "results/metrics.json:cost",
                })
            for key in sorted(metrics):
                section["rows"].append({
                    "item": key, "value": metrics[key],
                    "unit": _unit_of(key),
                    "source": f"results/metrics.json:metrics.{key}",
                })
        else:
            section["note"] = ("无 trials 且无 results/metrics.json"
                               f"（{err}）：最终设计不可得"
                               "（校准族产物面见 §⑤）")
            return section

    section["status"] = "ok"

    # 交叉核对（规格 §③：meta.json:metrics 与最优 trial metrics 逐键比对）
    meta_metrics = meta.get("metrics") if isinstance(meta, dict) else None
    if isinstance(meta_metrics, dict) and metrics:
        mismatches = [
            key for key in sorted(set(meta_metrics) | set(metrics))
            if meta_metrics.get(key) != metrics.get(key)
        ]
        if mismatches:
            section["cross_check"] = {
                "status": "mismatch",
                "note": "键不一致: " + ", ".join(mismatches),
                "source": f"{metrics_source} vs meta.json:metrics",
            }
            anomalies.append("§③ 交叉核对不一致（meta.metrics vs 最优 trial "
                             f"metrics）：{', '.join(mismatches)}")
        else:
            section["cross_check"] = {
                "status": "ok", "note": "逐位一致",
                "source": f"{metrics_source} vs meta.json:metrics",
            }
    else:
        section["cross_check"] = {
            "status": "missing",
            "note": "meta.json:metrics 或最终指标缺一侧，核对不适用",
            "source": "meta.json:metrics",
        }

    # 门表（缺键≠PASS）+ violation 和 vs cost 一致性自证
    if objectives:
        section["gates"] = evaluate_objective_gates(
            metrics, objectives, metrics_source=metrics_source)
        for note in section["gates"].get("notes") or []:
            anomalies.append(f"§③ 门表注记：{note}")
        violations = [r["violation"] for r in section["gates"]["rows"]
                      if r.get("violation") is not None]
        cost_value = section["best"].get("cost")
        if cost_value is None:
            cost_value = next(
                (r["value"] for r in section["rows"] if r["item"] == "cost"),
                None)
        if violations and _num(cost_value) is not None:
            viol_sum = math.fsum(float(v) for v in violations)
            cost_f = float(cost_value)
            if abs(viol_sum - cost_f) <= 1e-9 * max(1.0, abs(cost_f)):
                section["consistency"] = {
                    "status": "ok",
                    "note": "violation 之和 == cost（cost=violation 加权和语义）",
                    "value": viol_sum,
                    "source": f"{_DERIV_GATES} vs cost",
                }
            else:
                section["consistency"] = {
                    "status": "mismatch",
                    "note": (f"violation 之和 {viol_sum:.6g} != cost "
                             f"{cost_f:.6g}（如实注记，不翻案）"),
                    "value": viol_sum,
                    "source": f"{_DERIV_GATES} vs cost",
                }
                anomalies.append("§③ violation 之和与 cost 不一致（如实注记）")
    else:
        section["gates"] = _gates_stub("无 objectives 可判（配方快照缺失）")

    # design_verdict（规格汇总判定口径，不凑绿）
    section["design_verdict"] = section["gates"]["overall"]

    # 既有 verdict.json（C 族/战役 run）：verdict_summary_md 原样嵌入 §③
    verdict_path = run_dir / "verdict.json"
    if verdict_path.is_file():
        try:
            from rfauto.service.verdict_summary_service import verdict_summary_md

            section["verdict_md"] = {
                "status": "ok", "note": "",
                "markdown": verdict_summary_md(verdict_path),
                "source": "service:verdict_summary_md",
            }
        except Exception as exc:  # 摘要面故障如实降级（#105）
            section["verdict_md"] = {
                "status": "missing", "note": f"verdict 摘要不可用: {exc}",
                "markdown": "", "source": "service:verdict_summary_md",
            }
    return section


def _build_tradeoff_section(run_dir: Path, trajectory: dict[str, Any],
                            recipe: dict[str, Any] | None,
                            anomalies: list[str]) -> dict[str, Any]:
    """§⑤ 敏感性/trade-off 摘要（v1 两形态，其余如实 missing 不识别不解读）：
    优化族探索性统计（param_span + Pearson r，低样本强制警示）/ 校准族代理
    可信度摘要（calibration/gate.json + surrogate.json 只读嵌入）。"""
    calib_dir = run_dir / "calibration"
    gate_data, gate_err = _load_json(calib_dir / "gate.json")
    surro_data, _ = _load_json(calib_dir / "surrogate.json")
    if isinstance(gate_data, dict):
        rows: list[dict[str, Any]] = []
        for key in ("verdict", "rho_threshold", "validation_max_delta",
                    "n_samples", "n_failures"):
            if key in gate_data:
                rows.append({"item": key, "value": gate_data[key],
                             "source": f"calibration/gate.json:{key}"})
        loocv = gate_data.get("loocv")
        if isinstance(loocv, dict) and "rho" in loocv:
            rows.append({"item": "loocv_rho", "value": loocv.get("rho"),
                         "source": "calibration/gate.json:loocv.rho"})
        fsv = gate_data.get("fsv_gate")
        if isinstance(fsv, dict):
            for key in ("threshold", "grade", "pass", "degraded"):
                if key in fsv:
                    rows.append({"item": f"fsv_{key}", "value": fsv.get(key),
                                 "source":
                                     f"calibration/gate.json:fsv_gate.{key}"})
        if isinstance(surro_data, dict):
            if isinstance(surro_data.get("kind"), str):
                rows.append({"item": "surrogate_kind",
                             "value": surro_data["kind"],
                             "source": "calibration/surrogate.json:kind"})
            config = surro_data.get("config")
            if isinstance(config, dict) and isinstance(
                    config.get("metric_keys"), list):
                rows.append({
                    "item": "surrogate_metric_keys",
                    "value": ", ".join(str(k) for k in config["metric_keys"]),
                    "source":
                        "calibration/surrogate.json:config.metric_keys",
                })
        return {
            "source": "calibration/gate.json",
            "status": "ok",
            "kind": "calibration",
            "note": "代理可信度摘要（只读嵌入不重算——校准 report.md 为先例）",
            "param_stats": [],
            "low_sample_warning": "",
            "calibration": rows,
        }

    trials = trajectory.get("trials") or []
    if not trials:
        return {
            "source": _DERIV_TRADEOFF,
            "status": "missing",
            "kind": "none",
            "note": ("无 trials 且无 calibration/（"
                     + (gate_err or "gate.json 缺失")
                     + "）：敏感性/trade-off 两形态均不适用"),
            "param_stats": [],
            "low_sample_warning": "",
            "calibration": [],
        }

    # 优化参数集合：recipe optimization.params 优先，回退 trial 参数并集
    opt_keys: list[str] = []
    if isinstance(recipe, dict):
        optimization = recipe.get("optimization")
        if isinstance(optimization, dict) and isinstance(
                optimization.get("params"), dict):
            opt_keys = sorted(optimization["params"])
    if not opt_keys:
        seen: dict[str, None] = {}
        for t in trials:
            for key in (t.get("params") or {}):
                if key != "source":
                    seen.setdefault(key, None)
        opt_keys = sorted(seen)

    costs = [t["cost"] for t in trials]
    stats_rows: list[dict[str, Any]] = []
    n_samples = len(trials)
    for key in opt_keys:
        values = [_num((t.get("params") or {}).get(key)) for t in trials]
        pairs = [(v, c) for v, c in zip(values, costs, strict=True)
                 if v is not None]
        xs = [p[0] for p in pairs]
        r_value = _pearson_r(xs, [p[1] for p in pairs])
        stats_rows.append({
            "param": key,
            "min": min(xs) if xs else None,
            "max": max(xs) if xs else None,
            "unit": _unit_of(key),
            "pearson_r": r_value,
            "n": len(pairs),
            "source": f"{_DERIV_TRADEOFF} param_span / param_cost_pearson",
        })
    warning = ""
    if n_samples < _PEARSON_MIN_N_WARN:
        warning = (f"n={n_samples}<12：低样本探索性统计，非物理敏感性结论"
                   "（不写主控因素类断言，#118 家法）")
    return {
        "source": _DERIV_TRADEOFF,
        "status": "ok",
        "kind": "exploratory",
        "note": "探索性统计（只陈列不解释；因果断言不写）",
        "param_stats": stats_rows,
        "low_sample_warning": warning,
        "calibration": [],
    }


def _build_repro_section(run_dir: Path,
                         meta: dict[str, Any] | None) -> dict[str, Any]:
    """§⑥ 复现命令附录（全部真实存在叶；环境指纹逐键 source=meta.json）。"""
    run_id = (meta or {}).get("run_id")
    run_id = str(run_id) if run_id else run_dir.name
    # §⑥ 命令面零绝对路径（aurora_o o_ads 件3 外发安全）：模板全部走
    # runs/{run_id} 相对形态，run_dir 只用于 run_id 缺省回退（目录名）。
    commands = [
        {"command": cmd.format(run_id=run_id),
         "purpose": purpose, "source": origin}
        for cmd, purpose, origin in _REPRO_COMMANDS
    ]
    env_rows: list[dict[str, Any]] = []
    if isinstance(meta, dict):
        for key in _ENV_KEYS:
            if key in meta:
                value = meta[key]
                if value == "":
                    value = "（空串）"  # 样例手稿形态：空串与缺失可辨
                elif isinstance(value, dict):
                    value = json.dumps(value, sort_keys=True,
                                       ensure_ascii=False)
                env_rows.append({"key": key, "value": value,
                                 "source": f"meta.json:{key}"})
        numeric_env = meta.get("numeric_env")
        if isinstance(numeric_env, dict):
            for key in ("numpy_version", "blas"):
                if key in numeric_env and numeric_env[key] is not None:
                    env_rows.append({
                        "key": f"numeric_env.{key}",
                        "value": numeric_env[key],
                        "source": f"meta.json:numeric_env.{key}",
                    })
        if not env_rows:
            env_rows.append({"key": "(meta.json 无指纹键)", "value": "无",
                             "source": "meta.json"})
    return {
        "source": "meta.json",
        "commands": commands,
        "env_fingerprint": env_rows,
        "snapshot_pointer": (
            f"配方快照=runs/{run_id}/recipe.snapshot.yaml"
            "（复现以此为准，非 recipes/ 原件）"),
    }


# ── ⑤b Pareto 前沿（多目标 run 扩展节；REPORT_SPEC §五.2 v2 扩展位落地） ───

#: nsga2 run 前沿机器可读产物（optimizer.run_multiobjective_optimization
#: E9 落盘；ui_service.pareto_view 同款直读先例）
_PARETO_FRONT_JSON = "results/pareto_front.json"

#: Pareto 节派生量 source 词法（单源=pareto_tools，零公式复制，铁律 7）
_DERIV_PARETO = "derived@pareto_tools"
_DERIV_PARETO_HV = (
    "derived:exact_hypervolume@pareto_tools"
    "（ref=default_reference_point：各维最差值+max(1.0, 0.1·|最差值|)，"
    "最小化口径）")


def _ascii_label(text: str) -> str:
    """matplotlib 图标签 ASCII 化（CJK 缺字形只出豆腐块——AGENTS 家法；
    非 ASCII 字符逐字替换 '?'）。"""
    return text.encode("ascii", "replace").decode("ascii")


def _constraint_violations_of(raw: dict[str, Any]) -> list[float | None]:
    """trial 审计约束违约向量（湖读侧双格式兼容：optimizer 落盘=逐约束
    违约量 list[float]（``_record_constraints``）；dict 形态=逐约束指标→
    违约量；其余形态=无约束）。分量非数值→None（由调用方判可用性）。"""
    cv = raw.get("constraint_values")
    if isinstance(cv, dict):
        return [_num(v) for v in cv.values()]
    if isinstance(cv, (list, tuple)):
        return [_num(v) for v in cv]
    return []


def _build_pareto_section(
    run_dir: Path,
    recipe: dict[str, Any] | None,
    raw_trials: list[dict[str, Any]],
    *,
    with_diagrams: bool,
) -> dict[str, Any]:
    """§⑤b Pareto 前沿节（多目标 run；判据与降级形态见模块 docstring）。

    Returns:
        节节点（status: ok | na_single_objective | na_no_objective_spec |
        unknown | missing；数值载体全部带 source——bare_number_fields 判零）。
    """
    section: dict[str, Any] = {
        "source": "service:design_replay_report._build_pareto_section",
        "status": "missing",
        "kind": None,
        "note": "",
        "objective_names": [],
    }
    degrade_notes: list[str] = []

    # ── 源 A：results/pareto_front.json 直读（nsga2 run） ──
    front_path = run_dir / _PARETO_FRONT_JSON
    front_doc, front_err = _load_json(front_path)
    if isinstance(front_doc, dict) and _pareto_doc_usable(front_doc):
        return _pareto_section_from_doc(
            run_dir, front_doc, with_diagrams=with_diagrams)
    if front_path.is_file():
        degrade_notes.append(
            f"{_PARETO_FRONT_JSON} 在场但不可直读（"
            + (front_err or "形态不合：objective_names≥2 且 pareto_points "
                            "逐点 objectives 数值齐全方可直读")
            + "）——回退 trials 现算")

    # ── 源 B 前置：配方 objectives 解析（≥2 才有 Pareto 语义） ──
    objectives_spec = (recipe.get("objectives")
                       if isinstance(recipe, dict) else None)
    if not isinstance(objectives_spec, list) or not objectives_spec:
        section["status"] = "na_no_objective_spec"
        section["note"] = (
            "无 objectives 规格（配方快照缺失或为空）：单/多目标不可判，"
            "Pareto 前沿不适用（不猜不造，#122）。"
            + " ".join(degrade_notes)).strip()
        return section
    if len(objectives_spec) == 1:
        section["status"] = "na_single_objective"
        section["objective_names"] = [
            str(o.get("metric", ""))
            for o in objectives_spec if isinstance(o, dict)]
        section["note"] = (
            "single-objective run: Pareto 前沿不适用（N/A）——"
            "单目标轨迹与 trade-off 见 §②/§⑤。").strip()
        return section

    from rfauto.core.objectives import Objective

    objectives: list[Objective] = []
    parse_notes: list[str] = []
    for idx, spec in enumerate(objectives_spec):
        if not isinstance(spec, dict):
            parse_notes.append(f"objectives[{idx}] 非 dict（规格不可解析）")
            continue
        try:
            objectives.append(Objective(
                metric=str(spec.get("metric", "")),
                band=list(spec.get("band") or []),
                op=str(getattr(spec.get("op", ""), "value",
                               spec.get("op", ""))),
                value=spec.get("value"),
                weight=spec.get("weight", 1.0),
                length_mm=spec.get("length_mm"),
            ))
        except Exception as exc:  # pydantic 校验负例：如实 unknown 不炸
            parse_notes.append(f"objectives[{idx}] 规格不可解析: {exc}")
    if parse_notes or len(objectives) < 2:
        section["status"] = "unknown"
        section["note"] = ("；".join(parse_notes)
                           or "可用 objectives 少于 2 个（解析后）"
                           "——Pareto 前沿语义不可判（不凑节）")
        section["note"] += " " + " ".join(degrade_notes)
        section["note"] = section["note"].strip()
        return section

    return _pareto_section_from_trials(
        run_dir, objectives, raw_trials,
        with_diagrams=with_diagrams, degrade_notes=degrade_notes)


def _pareto_doc_usable(doc: dict[str, Any]) -> bool:
    """pareto_front.json 可直读判据：objective_names ≥2 且 pareto_points
    非空、逐点 objectives 含全部目标名的有限数值（不合法→回退 trials）。"""
    names = doc.get("objective_names")
    points = doc.get("pareto_points")
    if (not isinstance(names, list) or len(names) < 2
            or not all(isinstance(n, str) for n in names)
            or not isinstance(points, list) or not points):
        return False
    for point in points:
        if not isinstance(point, dict):
            return False
        objs = point.get("objectives")
        if not isinstance(objs, dict):
            return False
        for name in names:
            if name not in objs or _num(objs.get(name)) is None:
                return False
    return True


def _pareto_metrics_from_front(
    front_pts: list[tuple[float, ...]],
) -> tuple[float, list[float], dict[str, Any]]:
    """前沿点集 → (HV, ref, knee 节点)——pareto_tools 单源：
    exact_hypervolume + default_reference_point + knee（2D 弯曲角法 /
    k>2 HV 贡献法，平局取最小索引=确定性）。"""
    from rfauto.optimization.pareto_tools import (
        default_reference_point,
        exact_hypervolume,
        knee_point_bending_angle,
        knee_point_hv_contribution,
    )

    ref = default_reference_point(front_pts)
    hv = exact_hypervolume(front_pts, ref)
    if len(ref) == 2:
        knee_idx, knee_val = knee_point_bending_angle(front_pts)
        knee = {
            "point": int(knee_idx), "value": float(knee_val),
            "method": "knee_point_bending_angle（2D 弯曲角法）",
            "source": "derived:knee_point_bending_angle@pareto_tools",
        }
    else:
        knee_idx, knee_val = knee_point_hv_contribution(front_pts, ref)
        knee = {
            "point": int(knee_idx), "value": float(knee_val),
            "method": "knee_point_hv_contribution（HV 贡献法，k>2 无唯一弯曲角）",
            "source": "derived:knee_point_hv_contribution@pareto_tools",
        }
    return hv, [float(v) for v in ref], knee


def _pareto_section_from_doc(
    run_dir: Path,
    doc: dict[str, Any],
    *,
    with_diagrams: bool,
) -> dict[str, Any]:
    """源 A 构建节：pareto_front.json 直读（点序=文件原序，文件即前沿）。"""
    names = [str(n) for n in doc.get("objective_names") or []]
    points = doc.get("pareto_points") or []
    notes: list[str] = []
    n_doc = doc.get("n_pareto")
    if isinstance(n_doc, int) and not isinstance(n_doc, bool) \
            and n_doc != len(points):
        notes.append(
            f"n_pareto={n_doc} 与 pareto_points 数 {len(points)} 不符"
            "（以文件 pareto_points 为准，如实注记）")

    front: list[dict[str, Any]] = []
    front_pts: list[tuple[float, ...]] = []
    for i, point in enumerate(points):
        objs_raw = point.get("objectives") or {}
        objs = {name: float(_num(objs_raw.get(name))) for name in names}
        params = point.get("params")
        node: dict[str, Any] = {
            "point": i,
            "trial": None,
            "params": dict(params) if isinstance(params, dict) else {},
            "objectives": dict(objs),
            "cost": _num(point.get("cost")),
            "feasible": (point.get("feasible")
                         if isinstance(point.get("feasible"), bool) else None),
            "source": f"{_PARETO_FRONT_JSON}:pareto_points[{i}]",
        }
        node["params"]["source"] = f"{_PARETO_FRONT_JSON}:pareto_points[{i}].params"
        node["objectives"]["source"] = \
            f"{_PARETO_FRONT_JSON}:pareto_points[{i}].objectives"
        cv = _constraint_violations_of(point)
        if cv and all(v is not None for v in cv):
            node["constraint_values"] = [float(v) for v in cv]
        else:
            node["constraint_values"] = None
        front.append(node)
        front_pts.append(tuple(objs[name] for name in names))

    hv, ref, knee = _pareto_metrics_from_front(front_pts)
    section: dict[str, Any] = {
        "source": f"{_PARETO_FRONT_JSON}（湖直读，nsga2 前沿产物）+ {_DERIV_PARETO}",
        "status": "ok",
        "kind": "front_file",
        "note": "；".join(notes),
        "objective_names": names,
        "counts": {
            "n_pareto": len(front),
            "n_points_total": len(front),
            "n_trials_evaluable": None,
            "source": f"{_PARETO_FRONT_JSON}:pareto_points",
        },
        "front": front,
        "hypervolume": {
            "value": hv, "reference_point": ref,
            "source": _DERIV_PARETO_HV,
        },
        "knee": knee,
        "hv_convergence": _hv_convergence_summary(doc),
        "scatter": _pareto_scatter_node(
            run_dir, names, front_pts, [],
            with_diagrams=with_diagrams,
            dominated_note="前沿产物只含前沿点，无被支配点可比对（如实注记）"),
    }
    return section


def _hv_convergence_summary(doc: dict[str, Any]) -> dict[str, Any] | None:
    """nsga2 前沿产物的 HV 收敛轨迹摘要（逐代 HV 序列回显三标量+弱单调
    自证 is_weakly_monotone；缺产物/形态不合→None 如实）。"""
    from rfauto.optimization.pareto_tools import is_weakly_monotone

    trace = doc.get("hv_convergence")
    if not isinstance(trace, list) or not trace:
        return None
    values = [_num(v) for v in trace]
    if not values or any(v is None for v in values):
        return None
    vals = [float(v) for v in values]
    return {
        "n_generations": len(vals),
        "first": vals[0],
        "last": vals[-1],
        "weakly_monotone": bool(is_weakly_monotone(vals)),
        "source": (f"{_PARETO_FRONT_JSON}:hv_convergence"
                   "（弱单调判定=pareto_tools.is_weakly_monotone）"),
    }


def _pareto_section_from_trials(
    run_dir: Path,
    objectives: list[Any],
    raw_trials: list[dict[str, Any]],
    *,
    with_diagrams: bool,
    degrade_notes: list[str],
) -> dict[str, Any]:
    """源 B 构建节：trials 现算（目标向量=逐目标违约量，SpecEvaluator
    单目标拆分——与 run_multiobjective_optimization/pareto_view 同口径；
    支配=pareto_tools.constrained_pareto_front）。"""
    from rfauto.core.objectives import SpecEvaluator
    from rfauto.optimization.pareto_tools import constrained_pareto_front

    names = [obj.metric for obj in objectives]
    notes = list(degrade_notes)
    section: dict[str, Any] = {
        "source": ("trials/*.json:metrics + recipe.snapshot.yaml:objectives"
                   "（SpecEvaluator 单目标拆分）+ " + _DERIV_PARETO),
        "status": "missing",
        "kind": "trials_recomputed",
        "note": "",
        "objective_names": names,
    }

    # 可评估样本：metrics 非空 dict（pareto_view 同款过滤；全空→missing）
    evaluable = [
        tr for tr in raw_trials
        if isinstance(tr["raw"].get("metrics"), dict)
        and tr["raw"].get("metrics")
    ]
    skipped = len(raw_trials) - len(evaluable)
    if skipped:
        notes.append(f"{skipped} 个 trial 无 metrics（不可评估，如实跳过）")
    if not evaluable:
        section["status"] = "missing"
        section["note"] = (
            "trials 均无可评估 metrics——Pareto 前沿不可算"
            "（如实缺省，不凑绿，#122）。" + "；".join(notes)).strip()
        return section
    if len(evaluable) < 2:
        notes.append(
            f"可评估 trial 数 {len(evaluable)}<2：单点前沿合法但样本不足，"
            "前沿形态不代表收敛终态（如实注记）")

    # 逐 trial 逐目标：候选键在位判定（#364-④ 家法——SpecEvaluator 对缺键
    # 静默贡献 0，绝不能把 phantom-perfect 的 0 当违约量进前沿）
    obj_mat: list[list[float]] = []
    kept: list[dict[str, Any]] = []
    unknown_notes: list[str] = []
    for tr in evaluable:
        metrics = tr["raw"]["metrics"]
        row: list[float] = []
        ok_row = True
        for obj in objectives:
            observed: Any = None
            for key in SpecEvaluator.metric_key_candidates(
                    obj.metric, str(getattr(obj.op, "value", obj.op))):
                if key in metrics:
                    observed = metrics[key]
                    break
            if observed is None or _num(observed) is None:
                unknown_notes.append(
                    f"trial {tr['trial']} 目标 {obj.metric} 键缺失或非数值"
                    f"（候选键全未命中/值非有限）——违约量不可算")
                ok_row = False
                break
            violation = _num(SpecEvaluator.evaluate_objectives(metrics, [obj]))
            if violation is None:
                unknown_notes.append(
                    f"trial {tr['trial']} 目标 {obj.metric} 违约量非有限"
                    "（NaN/inf 守卫）")
                ok_row = False
                break
            row.append(float(violation))
        if ok_row:
            obj_mat.append(row)
            kept.append(tr)
    if unknown_notes:
        section["status"] = "unknown"
        section["note"] = (
            "；".join(unknown_notes) + "——受影响 trial 不进前沿，"
            "目标键缺失≠违约量 0（#364-④）；" + "；".join(notes)).strip()
        section["counts"] = {
            "n_pareto": None,
            "n_points_total": len(obj_mat),
            "n_trials_evaluable": len(kept),
            "source": "trials/*.json（候选键在位审计）",
        }
        return section

    # 约束违约向量（list/dict 双格式；任一 trial 缺约束键或含非数值分量→
    # 整体回退无约束支配+注记；全无约束键=正常无约束 run，静默）
    viol_rows = [_constraint_violations_of(tr["raw"]) for tr in kept]
    has_any_constraint = any(len(r) > 0 for r in viol_rows)
    use_viol = has_any_constraint and all(
        len(r) > 0 and all(v is not None for v in r) for r in viol_rows)
    if has_any_constraint and not use_viol:
        notes.append("约束违约向量不可用（部分 trial 缺约束键或含非数值分量）"
                     "——回退无约束支配（如实注记）")
    viol_mat: list[list[float]] = (
        [[float(v) for v in r] for r in viol_rows] if use_viol else [])

    front_idx = constrained_pareto_front(obj_mat, viol_mat if use_viol else None)
    front_set = set(front_idx)
    nodes: list[dict[str, Any]] = []
    front_pts: list[tuple[float, ...]] = []
    dominated_pts: list[tuple[float, ...]] = []
    for i, tr in enumerate(kept):
        rel = f"trials/trial_{tr['trial']}.json"
        objs = {name: obj_mat[i][col] for col, name in enumerate(names)}
        pt = tuple(objs[name] for name in names)
        node: dict[str, Any] = {
            "point": i,
            "trial": tr["trial"],
            "params": dict(tr["raw"].get("params") or {}),
            "objectives": dict(objs),
            "cost": _num(tr["raw"].get("cost")),
            "constraint_values": (viol_mat[i] if use_viol else None),
            "feasible": (all(v <= 0.0 for v in viol_mat[i])
                         if use_viol else None),
            "source": f"{rel}:metrics（SpecEvaluator.evaluate_objectives"
                      " 单目标拆分）",
        }
        node["params"]["source"] = f"{rel}:params"
        node["objectives"]["source"] = f"{rel}:metrics → derived:objective_violation"
        nodes.append(node)
        if i in front_set:
            front_pts.append(pt)
        else:
            dominated_pts.append(pt)
    # 前沿节点=constrained_pareto_front 输出原序（=nondominated 输入原序，
    # 即 trial 数值序）；point 字段重编为前沿位序（与 knee.point 同基）
    front = [nodes[i] for i in front_idx]
    for pos, node in enumerate(front):
        node["point"] = pos

    hv, ref, knee = _pareto_metrics_from_front(front_pts)
    section["status"] = "ok"
    section["note"] = "；".join(notes).strip()
    section["counts"] = {
        "n_pareto": len(front_pts),
        "n_points_total": len(kept),
        "n_trials_evaluable": len(kept),
        "source": "trials/*.json（可评估样本）→ constrained_pareto_front",
    }
    section["front"] = front
    section["hypervolume"] = {
        "value": hv, "reference_point": ref, "source": _DERIV_PARETO_HV}
    section["knee"] = knee
    section["hv_convergence"] = None
    section["scatter"] = _pareto_scatter_node(
        run_dir, names, front_pts, dominated_pts,
        with_diagrams=with_diagrams)
    return section


def _pareto_scatter_node(
    run_dir: Path,
    obj_names: list[str],
    front_pts: list[tuple[float, ...]],
    dominated_pts: list[tuple[float, ...]],
    *,
    with_diagrams: bool,
    dominated_note: str = "",
) -> dict[str, Any]:
    """§⑤b 散点 PNG 附件节点（落 ``diagrams/pareto_scatter.png``——T-O9
    声明产物落点；with_diagrams=False → skipped 不落盘；生成失败 best-effort
    #105 如实注记，正文数字不受影响）。"""
    node: dict[str, Any] = {
        "status": "skipped",
        "path": None,
        "rel_path": None,
        "note": "",
        "source": "service:design_replay_report._render_pareto_scatter",
    }
    if not with_diagrams:
        node["note"] = "调用方禁用图产物（with_diagrams=False）"
        return node
    if len(obj_names) < 2:
        node["status"] = "missing"
        node["note"] = "目标维数<2，散点图不适用"
        return node
    out_path = run_dir / "diagrams" / "pareto_scatter.png"
    ok, err = _render_pareto_scatter(
        [(p[0], p[1]) for p in front_pts],
        [(p[0], p[1]) for p in dominated_pts],
        obj_names, out_path)
    if not ok:
        node["status"] = "missing"
        node["note"] = f"散点图生成失败（非阻断）: {err}"
        return node
    note_parts = ["前沿点=实心圆+虚线阶梯，被支配点=灰 x；k>2 只绘前两维"]
    if dominated_note:
        note_parts.append(dominated_note)
    if not dominated_pts:
        note_parts.append("本图无被支配点")
    node["status"] = "ok"
    node["path"] = str(out_path)
    node["rel_path"] = _rel_link(str(out_path), run_dir)
    node["note"] = "；".join(note_parts)
    return node


def _render_pareto_scatter(
    front_pts: list[tuple[float, float]],
    dominated_pts: list[tuple[float, float]],
    obj_names: list[str],
    out_path: Path,
) -> tuple[bool, str]:
    """Pareto 散点 PNG（确定性：OO API（Figure+FigureCanvasAgg，infra/
    report.py 线程安全同款）+显式 metadata+固定 dpi，零时间戳零随机——
    同输入两跑逐字节；标签 ASCII 化，前沿点与被支配点视觉区分）。

    R11 Top4 论文图风格单源消费（Q-W8-4）：rcParams 经
    core/plot_style.paper_figure_context 作用域施加（字号/字体栈/
    unicode_minus 等 STYLE 常量单源），退出逐键还原零全局残留；显式
    figsize/dpi 实参优先于 STYLE 缺省——同输入两跑逐字节确定性不变。
    """
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure

        from rfauto.core.plot_style import paper_figure_context

        with paper_figure_context():
            fig = Figure(figsize=(6.0, 4.5), dpi=100)
            FigureCanvasAgg(fig)
            ax = fig.add_subplot(111)
            if dominated_pts:
                ax.scatter([p[0] for p in dominated_pts],
                           [p[1] for p in dominated_pts],
                           marker="x", c="#7f7f7f", s=36.0, label="dominated")
            if front_pts:
                ordered = sorted(front_pts, key=lambda p: (p[0], p[1]))
                ax.plot([p[0] for p in ordered], [p[1] for p in ordered],
                        linestyle="--", color="#d62728", linewidth=1.0,
                        alpha=0.7)
                ax.scatter([p[0] for p in front_pts], [p[1] for p in front_pts],
                           marker="o", c="#d62728", s=42.0, label="front")
            x_label = _ascii_label(obj_names[0]) if obj_names else "objective 1"
            y_label = (_ascii_label(obj_names[1]) if len(obj_names) > 1
                       else "objective 2")
            ax.set_xlabel(x_label + " (violation)")
            ax.set_ylabel(y_label + " (violation)")
            ax.set_title(f"Pareto front: {len(front_pts)} points")
            ax.grid(True, alpha=0.3)
            if dominated_pts or front_pts:
                ax.legend(loc="best")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(str(out_path), format="png", dpi=150,
                        metadata={"Software":
                                  "rfauto design-report pareto scatter"})
        return True, ""
    except Exception as exc:  # 生成面故障如实降级（#105）
        return False, str(exc)


# ── ⑤c 版本对账（可选 diff 对象扩展节；REPORT_SPEC §五.2 v2 扩展位落地） ──

#: ⑤c 差异计算单源词头（design_diff_service；数字全部来自其信封，铁律 7）
_DIFF_SOURCE = "service:design_diff_service.design_version_diff"


def _load_raw_trials(run_path: Path) -> list[dict[str, Any]]:
    """trials/trial_*.json → ``[{trial, raw}]``（trial 数值序；坏文件如实
    跳过）——build 侧同款装载形态，供 ⑤c 对比 run 侧复用。"""
    files, _ = _sorted_trial_files(run_path)
    raw_trials: list[dict[str, Any]] = []
    for idx, path in enumerate(files):
        data, _err = _load_json(path)
        if isinstance(data, dict):
            raw_trials.append({
                "trial": _trial_sort_key_number(data, idx),
                "raw": data,
            })
    return raw_trials


def _final_declaration(
    run_path: Path,
    raw_trials: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """run → 最终设计声明 ``{params, metrics, cost, trial, source}``。

    选择语义与 §③ 同款单源：优化族=trial 文件 cost 最小确定性重导
    （:func:`_pick_best_trial`；全部不可行→None）；单评族=
    results/metrics.json；C 校准族/全缺→None（不猜不造，#122）。
    ``raw_trials`` 缺省时自装载（对比 run 侧）；build 侧传已装载表。
    """
    trials = raw_trials if raw_trials is not None \
        else _load_raw_trials(run_path)
    if trials:
        selection = _pick_best_trial(trials)
        if selection.get("status") != "ok":
            return None
        best = next(tr for tr in trials if tr["trial"] == selection["trial"])
        rel = f"trials/trial_{selection['trial']}.json"
        return {
            "params": dict(best["raw"].get("params") or {}),
            "metrics": dict(best["raw"].get("metrics") or {}),
            "cost": _num(best["raw"].get("cost")),
            "trial": selection["trial"],
            "source": f"{rel}:params/metrics（§③ 同款 cost 最小确定性重导）",
        }
    results, _err = _load_json(run_path / "results" / "metrics.json")
    if isinstance(results, dict):
        return {
            "params": dict(results.get("params") or {}),
            "metrics": dict(results.get("metrics") or {}),
            "cost": _num(results.get("cost")),
            "trial": None,
            "source": "results/metrics.json:params/metrics（单评族）",
        }
    return None


def _diff_envelope(
    a_decl: dict[str, Any],
    b_decl: dict[str, Any],
    labels: tuple[str, str],
    facet: str,
) -> dict[str, Any]:
    """单面（params / metrics）两版声明差异信封：design_version_diff 单源
    逐位 + provenance 注入——``changes[i]``/``summary`` 节补 ``source``
    键（数值零改写；信封顶层 source 由 design_diff_service 自带）。"""
    from rfauto.service.design_diff_service import design_version_diff

    env = design_version_diff(a_decl, b_decl, labels=labels)
    facet_source = f"{_DIFF_SOURCE}（{facet} 面；a=base→b=本 run）"
    out = dict(env)
    out["changes"] = [dict(c, source=facet_source)
                      for c in env.get("changes") or []]
    out["summary"] = dict(env.get("summary") or {}, source=facet_source)
    return out


def _build_diff_section(
    run_path: Path,
    raw_trials: list[dict[str, Any]],
    diff_run_path: Path,
    *,
    base_label: str,
    current_label: str,
) -> dict[str, Any]:
    """§⑤c 版本对账节（降级三态与数据流见模块 docstring）。

    Returns:
        节节点（status: ok | missing；ok 态带 ``params_diff``/``metrics_diff``
        两信封——数值全部 design_version_diff 单源逐位；引用只用 run
        目录名，模型/正文零绝对路径）。
    """
    section: dict[str, Any] = {
        "source": _DIFF_SOURCE,
        "status": "missing",
        "note": "",
        "base_ref": {"run_id": base_label,
                     "source": "调用方 diff 对象入参（run 目录名）"},
        "current_ref": {"run_id": current_label,
                        "source": "本报告 run（run_ref.run_id）"},
        "params_diff": None,
        "metrics_diff": None,
    }
    if not diff_run_path.is_dir():
        section["note"] = (
            f"对比 run 目录不存在: {diff_run_path.name}"
            "（base 对象不可得，如实降级不凑节，#122）")
        return section
    base_decl = _final_declaration(diff_run_path)
    if base_decl is None:
        section["note"] = (
            f"对比 run（{base_label}）最终设计声明不可得（无 trials 且无 "
            "results/metrics.json，或全部 trial 不可行）——如实降级不凑节")
        return section
    current_decl = _final_declaration(run_path, raw_trials)
    if current_decl is None:
        section["note"] = (
            "本 run 最终设计声明不可得（§③ 同判：无 trials 且无 "
            "results/metrics.json，或全部 trial 不可行）——参数/指标差异"
            "不可比，如实降级不凑节")
        return section
    labels = (base_label, current_label)
    section["status"] = "ok"
    section["base_ref"]["decl_source"] = base_decl["source"]
    section["current_ref"]["decl_source"] = current_decl["source"]
    section["params_diff"] = _diff_envelope(
        base_decl["params"], current_decl["params"], labels, "params")
    section["metrics_diff"] = _diff_envelope(
        base_decl["metrics"], current_decl["metrics"], labels, "metrics")
    return section


# ── 模型组装（规格 §1.2 组合式） ───────────────────────────────────────────


def build_design_report_model(
    run_dir: str | Path,
    *,
    criteria_dir: str | Path | None = None,
    git_commit: str | None = None,
    with_diagrams: bool = True,
    diff_run_dir: str | Path | None = None,
) -> dict:
    """run 目录 → ``rfauto-design-report/v1`` 全模型（六新节 + base_report）。

    调用方断言 :func:`report_render.bare_number_fields`(model)==[]；
    run 目录不存在 → FileNotFoundError（与 base 同口径）。
    ``with_diagrams=False`` 时 §④ 记 skipped（不写 diagrams/）。
    ``diff_run_dir``（aurora_p C2，可选）：给定时追加 ``diff`` 键（⑤c
    版本对账节，a=该 run→b=本 run）；缺省 None 时模型零变化（无该键）。
    """
    run_path = Path(run_dir)
    if not run_path.is_dir():
        raise FileNotFoundError(f"run 目录不存在：{run_path}")
    from rfauto.service.report_render import build_report_model

    base = build_report_model(run_path, criteria_dir=criteria_dir,
                              git_commit=git_commit)

    meta, _meta_err = _load_json(run_path / "meta.json")
    if meta is not None and not isinstance(meta, dict):
        meta = None

    import yaml

    recipe: dict[str, Any] | None = None
    recipe_err = ""
    recipe_path = run_path / "recipe.snapshot.yaml"
    if recipe_path.is_file():
        try:
            loaded = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
            recipe = loaded if isinstance(loaded, dict) else None
            if recipe is None:
                recipe_err = "recipe.snapshot.yaml 根节点非映射"
        except (OSError, yaml.YAMLError) as exc:
            recipe_err = f"recipe.snapshot.yaml 不可读: {exc}"
    else:
        recipe_err = "recipe.snapshot.yaml 不在场"

    anomalies: list[str] = []
    goals, goal_anomalies = _build_goals_section(meta, recipe, recipe_err)
    anomalies.extend(goal_anomalies)

    trajectory = replay_trajectory(run_path)
    trajectory_out = {k: v for k, v in trajectory.items() if k != "ok"}
    if trajectory.get("status") == "ok":
        trajectory_out["source"] = "trials/（湖直读）+ " + _DERIV_TRAJ

    # 内部传递原始 trial dict（constraint_values 判定面；不进模型——
    # 模型消费面只走 trajectory_out 与 final_design 节）
    raw_trials: list[dict[str, Any]] = []
    if trajectory.get("status") == "ok":
        files, _ = _sorted_trial_files(run_path)
        for idx, path in enumerate(files):
            data, _err = _load_json(path)
            if isinstance(data, dict):
                raw_trials.append({
                    "trial": _trial_sort_key_number(data, idx),
                    "raw": data,
                })

    final_design = _build_final_design_section(
        run_path, meta, raw_trials, trajectory.get("trials") or [],
        recipe, anomalies)

    # 单评族 §② 降级：结果指标表（results/metrics.json:metrics）
    if trajectory_out.get("status") == "missing":
        results, _ = _load_json(run_path / "results" / "metrics.json")
        if isinstance(results, dict) and isinstance(
                results.get("metrics"), dict):
            trajectory_out["fallback_rows"] = [
                {"metric": key, "value": results["metrics"][key],
                 "source": f"results/metrics.json:metrics.{key}"}
                for key in sorted(results["metrics"])
            ]

    diagrams = _build_diagrams_section(
        run_path, with_diagrams=with_diagrams, anomalies=anomalies)
    tradeoff = _build_tradeoff_section(
        run_path, trajectory_out, recipe, anomalies)
    # §⑤b Pareto 前沿（aurora_p C1：多目标 run 扩展节；单目标 run 如实 N/A）
    pareto = _build_pareto_section(
        run_path, recipe, raw_trials, with_diagrams=with_diagrams)
    repro = _build_repro_section(run_path, meta)

    run_id = base["identification"]["run_id"]
    model: dict[str, Any] = {
        "schema": DESIGN_REPORT_SCHEMA,
        "run_ref": {
            "run_id": run_id,
            "run_dir": str(run_path),
            "source": ("meta.json:run_id"
                       if isinstance(meta, dict) and meta.get("run_id")
                       else f"run 目录名（{run_path.name}）"),
        },
        "goals": goals,
        "trajectory": trajectory_out,
        "final_design": final_design,
        "diagrams": diagrams,
        "tradeoff": tradeoff,
        "pareto": pareto,
        "repro": repro,
        "anomalies": anomalies,
        "base_report": base,
    }

    # 失败解释：仅 failed run 附候选族块（规格 §0.2/§③；其余 run 不出现该块）
    if isinstance(meta, dict) and meta.get("status") == "failed":
        model["final_design"]["failure_explain"] = _build_failure_explain(
            run_path)

    # §⑤c 版本对账（aurora_p C2）：仅调用方给定 diff 对象时追加 ``diff`` 键
    # ——未传时模型零变化（单 run 既有消费面/金钉逐字节同形）；对比 run
    # 缺失/声明不可得在节内如实 missing（#122 不凑节、不升级为错误）。
    if diff_run_dir is not None:
        diff_path = Path(diff_run_dir)
        model["diff"] = _build_diff_section(
            run_path, raw_trials, diff_path,
            base_label=diff_path.name, current_label=str(run_id))
    return model


def _build_failure_explain(run_path: Path) -> dict[str, Any]:
    """explain_run 候选族提取（只取字符串字段——explain 原始信封含数值节点，
    原样嵌入会破 provenance；候选族/坑号链/取证命令均为字符串面）。"""
    try:
        from rfauto.service.explain_run import explain_run

        explain = explain_run(run_path)
    except Exception as exc:  # 解释面故障如实降级（#105）
        return {"source": "service:explain_run", "overall": "no_hit",
                "candidates": [], "note": f"解释面不可用: {exc}"}
    if not explain.get("ok"):
        return {"source": "service:explain_run", "overall": "no_hit",
                "candidates": [],
                "note": str(explain.get("reason") or "解释面不可用")}
    return {
        "source": "service:explain_run",
        "overall": str(explain.get("overall") or "no_hit"),
        "candidates": [
            {"id": str(r.get("id")),
             "family": str(r.get("root_cause_family")),
             "pit_refs": [str(p) for p in r.get("pit_refs") or []],
             "forensic_commands": [
                 str(c) for c in r.get("forensic_commands") or []]}
            for r in explain.get("matched_rules") or []
        ],
    }


# ── md 渲染（确定性模板；同输入逐字节同输出） ───────────────────────────────


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    """GitHub markdown 管道表（确定性拼装）。"""
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join([" --- "] * len(headers)) + "|"]
    for row in rows:
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out)


def _design_verdict_of(model: dict) -> str:
    return str(model["final_design"].get("design_verdict") or "UNKNOWN")


def _gate_spec_disp(row: dict[str, Any]) -> str:
    """门表规格列显示（op 语义符号化；mean_within 区间形态）。"""
    if row.get("op") == "max_below":
        return f"≤ {_fmt_cell(row.get('threshold'))}"
    if row.get("op") == "min_above":
        return f"≥ {_fmt_cell(row.get('threshold'))}"
    return _fmt_cell(row.get("threshold"))


def _attachment_lines(dg: dict[str, Any]) -> list[str]:
    """§④ 附件相对链接行（T-O9 round-trip：从报告所在目录解析即达附件；
    rel_link 缺席时回退模型面 rel_path——缺省落点下二者同值）。"""
    out: list[str] = []
    for att in dg.get("attachments") or []:
        link = str(att.get("rel_link") or att.get("rel_path") or "")
        disp = f"[{link}]({link})" if link else f"`{att.get('path')}`"
        out.append(f"- 附件：{disp}"
                   f"（exists={_fmt_cell(att.get('exists'))}，"
                   f"generator={att.get('generator')}）")
    return out


def _ads_sim_line(dg: dict[str, Any]) -> str:
    """§④ ADS 前仿反标注图行（aurora_o o_ads 件3，T-O4 已落——占位文案
    改实际接入形态）：annot_sim 图命中→张数+引用；未命中→生成入口指引。"""
    ads_sim = dg.get("ads_sim") or {}
    if ads_sim.get("status") == "ok":
        return (
            f"ADS 前仿反标注图：**{ads_sim.get('n_circuits')} 张**"
            f"（{'、'.join(f'`{n}`' for n in ads_sim.get('names') or [])}，"
            "annot_sim 指标层，每卡带 source/sim_ref/unit）——见上附件相对"
            "链接，draw.io 重开即见最新指标"
            f"（{ads_sim.get('source')}）。")
    if ads_sim.get("status") == "skipped":
        return ("ADS 前仿反标注图：skipped（with_diagrams=False，"
                "只读扫描一并禁用）。")
    return (
        "ADS 前仿反标注图：本 run 无 ads-circuit run 产物"
        "（`<族>_circuit.drawio`）——入口 `rfauto ads-circuit diagram` → "
        "draw.io Edit Data 改值 → `rfauto ads-circuit run --out-dir "
        "runs/<run_id>`（指标反标注上图，J5 迭代再改值再 run）。")


def _feasible_disp(value: Any) -> str:
    """前沿表可行列显示（bool→是/否；None=无约束/不可判→—）。"""
    if value is True:
        return "是"
    if value is False:
        return "否"
    return "—"


def _pareto_md_lines(pareto: dict[str, Any]) -> list[str]:
    """§⑤b Pareto 前沿节 md 行（确定性拼装；status 五态逐一如实渲染——
    单目标 run 显式 ``single-objective run: N/A`` 不空不炸）。"""
    out: list[str] = ["## ⑤b Pareto 前沿（多目标 run 扩展节）", ""]
    status = str(pareto.get("status") or "missing")
    if status == "na_single_objective":
        out.append("**状态：na（single-objective run）**——"
                   "single-objective run: Pareto 前沿不适用（N/A）；"
                   f"配方 objectives={len(pareto.get('objective_names') or [])}，"
                   "单目标轨迹与 trade-off 见 §②/§⑤。")
        out.append("")
        return out
    if status != "ok":
        out.append(f"**状态：{status}（如实降级）**——{pareto.get('note')}")
        out.append("")
        return out

    names = [str(n) for n in pareto.get("objective_names") or []]
    counts = pareto.get("counts") or {}
    kind_disp = ("results/pareto_front.json 直读（nsga2 前沿产物，点序=文件原序）"
                 if pareto.get("kind") == "front_file"
                 else "trials 现算（目标向量=逐目标违约量，SpecEvaluator 单目标"
                      "拆分；点序=pareto_tools.nondominated_indices 输入原序"
                      "=trial 数值序）")
    out.append(f"**状态：ok**——源：{kind_disp}；可评估样本 "
               f"{_fmt_cell(counts.get('n_points_total'))}，前沿 "
               f"**{_fmt_cell(counts.get('n_pareto'))} 点**"
               f"（{counts.get('source')}）。")
    if pareto.get("note"):
        out.append(f"注记：{pareto['note']}")
    out.append("")
    out.append("**前沿表**（逐点目标值原样；最小化口径，越小越好；"
               "source 见模型面 front[i].source）")
    out.append("")
    headers = ["点序", "trial"] + [n.replace("|", "\\|") for n in names] \
        + ["cost", "可行"]
    rows: list[list[str]] = []
    for node in pareto.get("front") or []:
        objs = node.get("objectives") or {}
        rows.append(
            [str(node.get("point")),
             _fmt_cell(node.get("trial")) if node.get("trial") is not None
             else "—"]
            + [_fmt_cell(objs.get(n)) for n in names]
            + [_fmt_cell(node.get("cost")), _feasible_disp(node.get("feasible"))])
    out.append(_md_table(headers, rows))
    out.append("")
    hv = pareto.get("hypervolume") or {}
    knee = pareto.get("knee") or {}
    ref = hv.get("reference_point") or []
    knee_point = knee.get("point")
    knee_trial = ""
    if knee_point is not None:
        front = pareto.get("front") or []
        if 0 <= int(knee_point) < len(front) \
                and front[int(knee_point)].get("trial") is not None:
            knee_trial = f"（trial {front[int(knee_point)]['trial']}）"
    out.append("**超体积与膝点**（pareto_tools 单源：exact_hypervolume + "
               "default_reference_point + knee_point_*；零公式复制）")
    out.append("")

    def _esc(text: Any) -> str:  # 说明列含字面 |·|（绝对值）——管道表转义
        return str(text).replace("|", "\\|")

    out.append(_md_table(
        ["量", "值", "读法 / 来源"],
        [["hypervolume", _fmt_cell(hv.get("value")),
          _esc(f"前沿在参考点盒内的精确超体积（越大=前沿越丰满）；{hv.get('source')}")],
         ["reference_point",
          "(" + ", ".join(_fmt_cell(v) for v in ref) + ")",
          _esc("default_reference_point：各维最差值 + max(1.0, 0.1·|最差值|)")],
         ["knee 点序", f"{_fmt_cell(knee_point)}{knee_trial}",
          _esc(f"{knee.get('method')}；{knee.get('source')}")],
         ["knee 值", _fmt_cell(knee.get("value")),
          "弯曲角法=距前沿两极值点连线的垂直距离；HV 贡献法=移除该点的 HV 跌落"]]))
    out.append("")
    conv = pareto.get("hv_convergence")
    if isinstance(conv, dict):
        out.append(f"**HV 收敛轨迹摘要**（{conv.get('source')}）")
        out.append("")
        out.append(_md_table(
            ["代数", "首代 HV", "末代 HV", "弱单调不减"],
            [[_fmt_cell(conv.get("n_generations")), _fmt_cell(conv.get("first")),
              _fmt_cell(conv.get("last")),
              "是" if conv.get("weakly_monotone") else "否（如实注记）"]]))
        out.append("")
    scatter = pareto.get("scatter") or {}
    if scatter.get("status") == "ok":
        link = str(scatter.get("rel_link") or scatter.get("rel_path") or "")
        disp = f"[{link}]({link})" if link else f"`{scatter.get('path')}`"
        out.append(f"- 附件：{disp}（散点 PNG，generator=design_replay_report."
                   f"_render_pareto_scatter；{scatter.get('note')}）")
    elif scatter.get("status") == "skipped":
        out.append(f"- 附件：skipped（{scatter.get('note')}）")
    else:
        out.append(f"- 附件：missing（{scatter.get('note')}）——正文数字不受影响")
    out.append("")
    out.append("**判读边界**：前沿/HV/膝点为集合运算记账量（pareto_tools），"
               "不外推『设计已最优』结论；目标向量=违约量而非物理指标原值。")
    out.append("")
    return out


def _diff_change_rows(changes: list[dict[str, Any]]) -> list[list[str]]:
    """⑤c 差异表行：path/kind/base 值/本 run 值/相对变化——值全部来自
    design_version_diff 信封原样（fmt_value 单源显示）；单侧缺席（added/
    removed 无 a 或无 b 键）显 ``—``，rel_change 为 None（非数值变更或
    base 值为 0 不除零）显 ``—``。"""
    rows: list[list[str]] = []
    for c in changes:
        rel = c.get("rel_change")
        rows.append([
            str(c.get("path", "")).replace("|", "\\|"),
            str(c.get("kind", "")),
            _fmt_cell(c["a"]) if "a" in c else "—",
            _fmt_cell(c["b"]) if "b" in c else "—",
            f"{rel * 100:+.3g}%" if rel is not None else "—",
        ])
    return rows


def _diff_facet_lines(title: str, node: dict[str, Any] | None) -> list[str]:
    """⑤c 单面（参数/指标）差异表 md 行（确定性拼装）。"""
    node = node if isinstance(node, dict) else {}
    changes = node.get("changes") or []
    summary = node.get("summary") or {}
    summary_disp = "，".join(
        f"{k}={v}" for k, v in sorted(summary.items()) if k != "source")
    out: list[str] = [
        f"**{title}**（design_version_diff 单源逐位；verdict="
        f"**{node.get('verdict') or 'unknown'}**，共 {len(changes)} 处变更"
        + (f"：{summary_disp}" if summary_disp else "") + "）",
        "",
    ]
    if not changes:
        out.append("（逐键一致：零变更，identical）")
        out.append("")
        return out
    out.append(_md_table(
        ["路径", "类型", "base 值", "本 run 值", "相对变化"],
        _diff_change_rows(changes)))
    out.append("")
    return out


def _diff_md_lines(diff: dict[str, Any]) -> list[str]:
    """§⑤c 版本对账节 md 行（aurora_p C2；确定性拼装；数字全部来自
    design_version_diff 信封——引用不复制，铁律 7）。status 非 ok 一律
    "如实降级"一行（不空不炸）；引用只用 run 目录名（正文零绝对路径）。"""
    out: list[str] = ["## ⑤c 版本对账（与对比 run 的设计差异）", ""]
    status = str(diff.get("status") or "missing")
    if status != "ok":
        out.append(f"**状态：{status}（如实降级）**——{diff.get('note')}")
        out.append("")
        return out
    base_ref = diff.get("base_ref") or {}
    current_ref = diff.get("current_ref") or {}
    out.append(
        f"- 对比方向：base=`{base_ref.get('run_id')}` → 本 run="
        f"`{current_ref.get('run_id')}`（变更读法=从 base 到本 run；"
        "a→b 同向）。")
    out.append(
        f"- 最终设计声明出处：base={base_ref.get('decl_source')}；"
        f"本 run={current_ref.get('decl_source')}。")
    out.append("")
    out.extend(_diff_facet_lines("参数差异表", diff.get("params_diff")))
    out.extend(_diff_facet_lines("指标差异表", diff.get("metrics_diff")))
    out.append("**判读边界**：差异表=两版最终设计声明的机械对账"
               "（design_diff_service；值列 —=单侧缺席或值为空，相对变化 —="
               "非数值变更或 base 值为 0），不判定优劣与因果。")
    out.append("")
    return out


def render_design_report_md(model: dict) -> str:
    """报告模型 → md（人读主形态；确定性，同输入逐字节同输出——唯一豁免=
    base_report.identification.generated_at 时间戳行，规格 §3.1）。

    样式对拍基准=runs/aurora_o/report_spec/sample_design_report_*.md
    （B 优化族真实 run 手稿）。
    """
    lines: list[str] = []
    run_ref = model["run_ref"]
    base = model["base_report"]
    ident = base["identification"]
    freshness = model.get("_freshness") or {}
    fresh_status = str(freshness.get("status") or "unknown")
    fresh_note = str(freshness.get("note") or "")
    goals = model["goals"]
    traj = model["trajectory"]
    fd = model["final_design"]
    gates = fd["gates"]
    dup = traj.get("duplicates") or {}

    lines.append(f"# rfauto 设计回放报告：{run_ref['run_id']}")
    lines.append("")
    # 外发安全（#364 面）：md 正文零 run 绝对路径——相对形态 runs/<run_id>，
    # 绝对路径只保留在模型面 run_ref.run_dir（aurora_o o_ads 件3）
    lines.append(
        f"- run 目录：`runs/{run_ref['run_id']}`（{run_ref['source']}；"
        "外发省略绝对路径，完整路径见模型面 run_ref.run_dir）")
    lines.append(
        f"- 生成时间：{ident['generated_at']}"
        "（**逐字节复现豁免行**：除本行外，数字与结构同输入可逐字节复现"
        "——REPORT_SPEC §3.1）")
    lines.append(f"- freshness：{fresh_status}"
                 + (f"（{fresh_note}）" if fresh_note else ""))
    lines.append(
        f"- 汇总判定：**design_verdict={_design_verdict_of(model)}**；"
        f"轨迹重复评估 {dup.get('n_duplicate_evals', 0)}；复现入口见 §⑥。")
    lines.append("")

    # ── ① 设计目标与配方摘要 ──
    lines.append("## ① 设计目标与配方摘要")
    lines.append("")
    lines.append("**基本信息**")
    lines.append("")
    if goals["basic"]:
        lines.append(_md_table(
            ["字段", "值", "来源"],
            [[r["name"], _fmt_cell(r["value"]), r["source"]]
             for r in goals["basic"]]))
    else:
        lines.append("（meta.json 不可读：基本信息缺）")
    lines.append("")
    if goals["status"] == "ok":
        lines.append("**名义参数与优化范围**（名义=recipe.snapshot.yaml:params；"
                     "范围=recipe.snapshot.yaml:optimization.params）")
        lines.append("")
        if goals["params"]:
            lines.append(_md_table(
                ["参数", "名义值", "单位", "下界", "上界", "来源"],
                [[r["param"], _fmt_cell(r["nominal"]),
                  r["unit"] or "—",
                  _fmt_cell(r["low"]) if r["low"] is not None else "—（不优化）",
                  _fmt_cell(r["high"]) if r["high"] is not None else "—",
                  r["source"]]
                 for r in goals["params"]]))
        lines.append("")
        if goals["objectives"]:
            lines.append("**设计目标**（recipe.snapshot.yaml:objectives）")
            lines.append("")
            lines.append(_md_table(
                ["#", "指标", "判据", "规格", "频带 (GHz)", "来源"],
                [[str(r["objective"]), r["metric"], r["op"], r["spec"],
                  r["band"], r["source"]]
                 for r in goals["objectives"]]))
        if goals["setup"]:
            lines.append("")
            lines.append("评测设置：" + "；".join(
                f"{r['value']}（{r['source']}）" for r in goals["setup"])
                + "。")
    else:
        lines.append(f"**配方摘要：{goals['status']}**——{goals['note']}")
    lines.append("")

    # ── ② 优化轨迹回放 ──
    lines.append("## ② 优化轨迹回放")
    lines.append("")
    if traj.get("status") == "ok":
        lines.append(
            f"本 run 含 **{traj['n_trial_files']} 份 trial 文件**"
            f"（{traj.get('source')}，按 trial_number 数值排序）。"
            "**诚实注记**：trial 文件=成功 trial 全集；被剪枝/失败的 trial "
            "不落文件（optimizer 剪枝路径在写文件前退出），本报告不虚报"
            f"总 trial 数。重复参数向量：**{dup.get('n_duplicate_evals', 0)}**"
            f"（{dup.get('source')}）。")
        if traj.get("note"):
            lines.append(f"注记：{traj['note']}")
        lines.append("")
        param_keys: list[str] = []
        seen: set[str] = set()
        for t in traj["trials"]:
            for key in (t.get("params") or {}):
                if key != "source" and key not in seen:
                    seen.add(key)
                    param_keys.append(key)
        headers = ["trial"] + [
            f"{k} ({_unit_of(k) or '—'})" for k in param_keys
        ] + ["cost", "best-so-far"]
        rows = []
        bsf_series = traj.get("best_sofar") or []
        for i, t in enumerate(traj["trials"]):
            cells = [str(t["trial"])]
            cells += [_fmt_cell(t["params"].get(k)) for k in param_keys]
            bsf = bsf_series[i] if i < len(bsf_series) else None
            # 改进事件标记：严格小于前一轮 bsf（持平不标——规格 improvements
            # 公式同口径；==min 的写法会把持平轮误标）
            is_new_bsf = (bsf is not None and i > 0
                          and bsf < bsf_series[i - 1])
            cells.append(_fmt_cell(t["cost"]))
            cells.append(f"**{_fmt_cell(bsf)}** ↓" if is_new_bsf
                         else _fmt_cell(bsf))
            rows.append(cells)
        lines.append("**轨迹表**（params/cost=trials/trial_N.json；"
                     "bsf=derived:best_sofar@REPORT_SPEC §2·轨迹）")
        lines.append("")
        lines.append(_md_table(headers, rows))
        lines.append("")
        improvements = traj.get("improvements") or []
        if bsf_series:
            lines.append("**关键决策点（改进事件）**（derived:improvements"
                         "@REPORT_SPEC §2·轨迹）")
            lines.append("")
            imp_rows = [[str(traj["trials"][0]["trial"]),
                         _fmt_cell(bsf_series[0]), "基线"]]
            for imp in improvements:
                imp_rows.append([str(imp["trial"]),
                                 _fmt_cell(imp["best_sofar"]),
                                 _fmt_cell(imp["delta"])])
            lines.append(_md_table(
                ["trial", "best-so-far", "相对上轮 bsf 改进"], imp_rows))
            last = traj["trials"][-1]["trial"]
            last_imp = improvements[-1]["trial"] if improvements \
                else traj["trials"][0]["trial"]
            lines.append("")
            lines.append(f"trial {last_imp} 之后 {last - last_imp} 个 trial"
                         f"（{last_imp + 1}–{last}）无再改进"
                         "（bsf 持平，derived）。")
            lines.append("")
        auc = traj.get("auc_norm") or {}
        conv = traj.get("conv_ratio") or {}
        lines.append("**收敛汇总量**（derived@REPORT_SPEC §2·轨迹，"
                     "公式同源可复算）")
        lines.append("")
        auc_disp = (_fmt_cell(auc.get("value")) if auc.get("status") == "ok"
                    else "undefined")
        conv_disp = (_fmt_cell(conv.get("value"))
                     if conv.get("status") == "ok" else "undefined")
        lines.append(_md_table(
            ["量", "值", "读法"],
            [["auc_norm", auc_disp,
              "∈(0,1]，1=零改进；越小=收敛越快"
              if auc.get("status") == "ok"
              else "undefined（N≤1 或 bsf_1==0，不除零不凑数）"],
             ["conv_ratio", conv_disp,
              "全程相对改进" if conv.get("status") == "ok"
              else "undefined（bsf_1==0 或 N≤1）"]]))
        lines.append("")
        lines.append("**判读边界**：以上为记账统计，不外推『已收敛/未收敛』"
                     "结论（判定以 §③ 门表为准）。")
    else:
        lines.append(f"**优化轨迹：{traj.get('status')}**——{traj.get('note')}。")
        fallback = traj.get("fallback_rows") or []
        if fallback:
            lines.append("")
            lines.append("**结果指标表**（单次 run 族降级形态；"
                         "source=results/metrics.json:metrics）")
            lines.append("")
            lines.append(_md_table(
                ["指标", "值", "来源"],
                [[r["metric"], _fmt_cell(r["value"]), r["source"]]
                 for r in fallback]))
    lines.append("")

    # ── ③ 最终设计与 verdict 门表 ──
    lines.append("## ③ 最终设计与 verdict 门表")
    lines.append("")
    select_disp = ("可行 trial 中 cost 最小者" if fd["best"].get("constrained")
                   else "trial 文件中 cost 最小者")
    head = (f"**最终设计**（定义={select_disp}，REPORT_SPEC §2·门表）")
    best_trial = fd["best"].get("trial")
    if best_trial is not None:
        head += f"= **trial {best_trial}**（derived:final_design）。"
    lines.append(head)
    if fd.get("note") and fd.get("status") == "ok":
        lines.append(f"（{fd['note']}）")
    lines.append("")
    if fd["status"] == "ok" and fd["rows"]:
        lines.append(_md_table(
            ["项", "值", "单位", "来源"],
            [[r["item"], _fmt_cell(r["value"]), r["unit"] or "—", r["source"]]
             for r in fd["rows"]]))
        lines.append("")
    else:
        lines.append(f"（最终设计：{fd['status']}——{fd['note']}）")
        lines.append("")
    cc = fd.get("cross_check") or {}
    if cc.get("status") == "ok":
        lines.append(f"交叉核对：与 meta.json:metrics **逐位一致**"
                     f"（cross_check=ok，来源 {cc.get('source')}）。")
    else:
        lines.append(f"交叉核对：{cc.get('status')}——{cc.get('note')}"
                     f"（来源 {cc.get('source')}）。")
    gate_rows = gates.get("rows") or []
    lines.append("")
    if gate_rows:
        lines.append("**配方目标门表**（判定=单目标拆分调 core/objectives 语义；"
                     "derived:objective_gates@REPORT_SPEC §2·门表）")
        lines.append("")
        lines.append(_md_table(
            ["#", "目标", "规格", "观测", "违约量 (violation)", "判定", "来源"],
            # # 列 1 基显示（与 §① 目标表同形态）；source 内 objectives[i]
            # 保持 0 基原文（文件真值）
            [[str(r["objective"] + 1), r["metric"], _gate_spec_disp(r),
              _fmt_cell(r["observed"]), _fmt_cell(r["violation"]),
              f"**{r['judgment']}**", r["source"]]
             for r in gate_rows]))
        lines.append("")
    lines.append(f"汇总：**design_verdict = {gates.get('overall')}**"
                 f"（PASS {gates.get('n_pass', 0)} / FAIL "
                 f"{gates.get('n_fail', 0)} / UNKNOWN "
                 f"{gates.get('n_unknown', 0)}；有 FAIL 行即 FAIL，无 FAIL 有 "
                 "UNKNOWN 即 UNKNOWN，不凑绿）。")
    cons = fd.get("consistency") or {}
    if cons.get("status") in ("ok", "mismatch"):
        lines.append(f"一致性自证：{cons.get('note')}"
                     f"（{cons.get('source')}）。")
    lines.append("")
    other_faces: list[str] = []
    crit = base.get("criteria") or {}
    other_faces.append(
        f"判据对照表（criteria/v2）：{crit.get('status', 'none-provided')}"
        "（不虚构对照表；见 base_report.criteria）。")
    vm = fd.get("verdict_md") or {}
    if vm.get("status") == "ok":
        lines.append("**verdict.json 判读摘要**（service:verdict_summary_md "
                     "原样嵌入）：")
        lines.append("")
        for vline in str(vm.get("markdown") or "").splitlines():
            lines.append(vline)
        lines.append("")
    other_faces.append(
        "verdict.json：已嵌入（见上）。" if vm.get("status") == "ok"
        else f"verdict.json：{vm.get('note')} → 不嵌入门表。")
    fe = fd.get("failure_explain")
    if fe is not None:
        if fe.get("candidates"):
            fam = "；".join(
                f"{c.get('family')}（{c.get('id')}，坑号链 "
                f"{'/'.join(c.get('pit_refs') or []) or '无'}）"
                for c in fe["candidates"])
            other_faces.append(f"失败解释（explain_run）候选根因族：{fam}。")
        else:
            other_faces.append(
                "失败解释（explain_run）：无命中候选族（no_hit，不硬凑）。")
    else:
        meta_status = next(
            (r["value"] for r in goals["basic"] if r["name"] == "status"),
            None)
        other_faces.append(
            "失败解释（explain_run）：不适用（meta.json:status="
            f"{_fmt_cell(meta_status)}，非 failed run）。")
    lines.append("**其他判读面**（如实陈列）：")
    lines.append("")
    for face in other_faces:
        lines.append(f"- {face}")
    lines.append("")

    # ── ④ 电路图总结 ──
    dg = model["diagrams"]
    lines.append("## ④ 电路图总结（.drawio 附件）")
    lines.append("")
    if dg.get("status") == "ok":
        summary = dg.get("summary") or {}
        lines.append(f"**状态：ok**——链路框图附件已生成（{dg.get('source')}）。")
        # 相对链接（T-O9 round-trip；链路图+ADS 反标注图统一附件行）
        lines.extend(_attachment_lines(dg))
        lines.append(f"- 级数 n_stages={_fmt_cell(summary.get('n_stages'))}；"
                     f"级联 ΣG={_fmt_cell(summary.get('gain_total_db'))} dB；"
                     f"ΣNF={_fmt_cell(summary.get('nf_total_db'))} dB"
                     "（信封回显三标量；逐级 G/NF 见图内——引用不复制）。")
        lines.append("")
        lines.append(_ads_sim_line(dg))
    elif dg.get("status") == "skipped":
        lines.append(f"**状态：skipped**——{dg.get('note')}。")
    else:
        lines.append(f"**状态：missing（如实降级）**——{dg.get('note')}")
        lines.append("")
        # ADS 反标注图附件（若湖面有 ads-circuit run 产物）——链路级缺席
        # 不掩蔽图附件（o_ads 件3：引用不复制）
        att_lines = _attachment_lines(dg)
        lines.extend(att_lines)
        if att_lines:
            lines.append("")
        lines.append(_ads_sim_line(dg))
    lines.append("")

    # ── ⑤ 敏感性 / trade-off 摘要 ──
    to = model["tradeoff"]
    lines.append("## ⑤ 敏感性 / trade-off 摘要")
    lines.append("")
    if to.get("kind") == "calibration":
        lines.append(f"**校准族代理可信度摘要**（{to.get('note')}；"
                     f"source={to.get('source')}）")
        lines.append("")
        if to.get("calibration"):
            lines.append(_md_table(
                ["项", "值", "来源"],
                [[r["item"], _fmt_cell(r["value"]), r["source"]]
                 for r in to["calibration"]]))
    elif to.get("status") == "ok":
        warn_part = (f"；**{to.get('low_sample_warning')}**"
                     if to.get("low_sample_warning") else "")
        lines.append(f"**探索性统计**（{to.get('source')}" + warn_part + "）")
        lines.append("")
        if to.get("param_stats"):
            lines.append(_md_table(
                ["参数", "trial 内跨度 min–max", "Pearson r（参数 vs cost）",
                 "n", "来源"],
                [[r["param"],
                  f"{_fmt_cell(r['min'])} – {_fmt_cell(r['max'])}"
                  f" {r['unit']}".strip(),
                  _fmt_cell(r["pearson_r"]), str(r["n"]), r["source"]]
                 for r in to["param_stats"]]))
        lines.append("")
        lines.append("读法边界：r 只陈列不解释（n 与混杂未控，"
                     "不写『主控因素』类断言）。")
    else:
        lines.append(f"**状态：{to.get('status')}**——{to.get('note')}")
    lines.append("")

    # ── ⑤b Pareto 前沿（多目标 run 扩展节；REPORT_SPEC §五.2 v2 扩展位） ──
    # 既有 §①-⑥ 编号零变化（⑥ 复现附录不重编号）；老模型无 pareto 键时
    # 不渲染（向后兼容，不炸）
    pareto = model.get("pareto")
    if isinstance(pareto, dict):
        lines.extend(_pareto_md_lines(pareto))

    # ── ⑤c 版本对账（aurora_p C2：可选 diff 对象扩展节） ──
    # 模型无 diff 键（未传对比 run）时不渲染——单 run md 逐字节零变化；
    # ①-⑥ 编号零变化（⑥ 不重编号）
    diff_section = model.get("diff")
    if isinstance(diff_section, dict):
        lines.extend(_diff_md_lines(diff_section))

    # ── ⑥ 复现命令附录 ──
    repro = model["repro"]
    lines.append("## ⑥ 复现命令附录")
    lines.append("")
    lines.append("```bash")
    for i, cmd in enumerate(repro.get("commands") or [], 1):
        lines.append(f"# {i}) {cmd.get('purpose')}（{cmd.get('source')}）")
        lines.append(str(cmd.get("command")))
    lines.append("```")
    lines.append("")
    lines.append(f"**配方快照指针**：{repro.get('snapshot_pointer')}。")
    lines.append("")
    lines.append("**环境指纹**（来源 meta.json；老 run 无对应键者如实标"
                 "『无』）")
    lines.append("")
    if repro.get("env_fingerprint"):
        lines.append(_md_table(
            ["键", "值", "来源"],
            [[r["key"], _fmt_cell(r["value"]), r["source"]]
             for r in repro["env_fingerprint"]]))
    lines.append("")

    # ── 尾部：异常与注记汇总 + provenance 注 ──
    lines.append("---")
    lines.append("")
    lines.append("### 异常与注记汇总（anomalies）")
    lines.append("")
    anomalies = model.get("anomalies") or []
    if anomalies:
        for i, a in enumerate(anomalies, 1):
            lines.append(f"{i}. {a}")
    else:
        lines.append("（无异常注记）")
    lines.append("")
    lines.append("> 本报告为 rfauto-design-report/v1 模型之 md 渲染"
                 "（REPORT_SPEC 形态基准）。provenance 门：全文数字均带来源"
                 "标注，`bare_number_fields(model)==[]`。")
    lines.append("")
    return "\n".join(lines)


# ── 服务入口（CLI/MCP 薄壳背后；规格 §四签名草案） ─────────────────────────


def generate_design_report(
    run_id: str,
    *,
    output: str | Path | None = None,
    with_diagrams: bool = True,
    diff_run_id: str | None = None,
) -> dict[str, Any]:
    """服务入口：freshness gate → 模型 → md 渲染 → 落盘（缺省
    ``runs/<run_id>/design_report.md``）→（数据在时）diagrams/ 附件
    （T-O9：附件节点按报告落点注入 ``rel_link`` 相对链接，round-trip
    契约=从报告所在目录解析即达附件）。

    ``diff_run_id``（aurora_p C2，可选）：给定时报告追加 ⑤c 版本对账节
    （a=该对比 run→b=本 run）；解析与主 run 同款 resolve_run_dir 双根
    归一，对比 run 缺失/声明不可得**不报错**——节内如实 missing（#122）。

    Returns:
        ok 信封 ``{ok, run_id, schema, report, diagrams, design_verdict,
        n_gates_pass, n_gates_fail, freshness:{status, note}}``（键集零增
        减——diff 信息只在模型/md，不在信封）；stale →
        error_envelope(stage="freshness_gate")；run 不存在 →
        error_envelope（显式负例，不静默）。
    """
    from rfauto.service.runs_verify_service import resolve_run_dir, verify_run

    explicit = Path(run_id)
    resolved = resolve_run_dir(str(run_id))
    if not explicit.is_dir() and not resolved.is_dir():
        return error_envelope(
            f"run 目录不存在: {run_id}（传 run_id 或 run 目录路径）",
            run_id=str(run_id), stage="resolve_run_dir")
    run_path = resolved if resolved.is_dir() else explicit

    diff_path: Path | None = None
    if diff_run_id:
        diff_explicit = Path(diff_run_id)
        diff_resolved = resolve_run_dir(str(diff_run_id))
        diff_path = diff_resolved if diff_resolved.is_dir() else diff_explicit

    # freshness gate（K4 同款；stale 拒出——交付错配不能静默通过）
    fresh_status = "unknown"
    fresh_note = ""
    try:
        freshness = verify_run(run_path)
        fresh_status = str(freshness.get("status") or "unknown")
        if fresh_status == "stale":
            return error_envelope(
                list(freshness.get("errors") or ["run 产物新鲜度校验未通过"]),
                stage="freshness_gate",
                run_id=str(freshness.get("run_id") or run_id),
                status="stale",
                issues=freshness.get("issues") or [])
        fresh_note = str(freshness.get("note") or "")
    except Exception as exc:  # 校验面故障记账不阻断（#105）
        fresh_note = f"新鲜度校验不可用（非阻断）: {exc}"

    try:
        model = build_design_report_model(run_path,
                                          with_diagrams=with_diagrams,
                                          diff_run_dir=diff_path)
    except FileNotFoundError as exc:
        return error_envelope(str(exc), run_id=str(run_id))
    model["_freshness"] = {"status": fresh_status, "note": fresh_note}

    out_path = Path(output) if output is not None \
        else run_path / "design_report.md"
    # 报告内相对链接（T-O9 round-trip）：按报告实际落点计算，附件节点
    # 注入 ``rel_link``（渲染端 `[rel](rel)` 形态；同输入确定性）。
    for att in (model.get("diagrams") or {}).get("attachments") or []:
        att_path = att.get("path")
        if isinstance(att_path, str) and att_path:
            att["rel_link"] = _rel_link(att_path, out_path.parent)
    # §⑤b 散点 PNG 附件同款 rel_link（T-O9 round-trip 契约）
    scatter = (model.get("pareto") or {}).get("scatter")
    if isinstance(scatter, dict) and isinstance(scatter.get("path"), str) \
            and scatter["path"]:
        scatter["rel_link"] = _rel_link(scatter["path"], out_path.parent)

    md_text = render_design_report_md(model)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md_text, encoding="utf-8")
    except OSError as exc:
        return error_envelope(f"设计报告写盘失败：{exc}", run_id=str(run_id))

    gates = model["final_design"]["gates"]
    dg = model["diagrams"]
    return ok_envelope(
        run_id=model["run_ref"]["run_id"],
        schema=DESIGN_REPORT_SCHEMA,
        report=str(out_path),
        diagrams={
            "status": dg.get("status"),
            "attachments": dg.get("attachments") or [],
        },
        design_verdict=gates.get("overall"),
        n_gates_pass=gates.get("n_pass", 0),
        n_gates_fail=gates.get("n_fail", 0),
        freshness={"status": fresh_status, "note": fresh_note},
    )
