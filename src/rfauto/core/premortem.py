"""Pre-mortem 失败预演内核（XN-1，第十九轮 P1，KD-4 的对偶）。

战役/设计开工前自动生成"最可能失败模式 + 症状指纹 + 早期检测探针"——
把坑账从"事后追账"变"前置防线"（#157/#177 家族
教训前置化）。与 service/rationale_memory.py 的 recall_for（"这个坑踩过
没有"检索）互为对偶：那里按任务文本检索历史经验，这里按任务类别把整张
失败模式表确定性铺开。

设计约束（与 rationale_memory / solve_health 同源）：
- 失败模式生成 = **确定性规则引擎**：按 task_kind 查静态模式库，无 LLM、
  无网络、无随机数。
- 纯函数内核：同输入两次输出逐位一致（JSON sort_keys 往返逐字节同）。
- 每条失败模式：模式名 / 可能性档（high|medium|low）/ 症状指纹（早期信号）
  / 检测探针 id / 缓解引用（坑号/TODO 项）+ 出处。
- 检测探针 = 可执行检查的纯函数规格（declarative spec + run_probe 执行）：
  开工前对 context（开工声明面）做"在案？"静态检查——如"真机求解类 →
  发射前后台分离+存活探针在案？"。探针不碰文件系统/进程/网络（纯读
  context），可静态检查、可单测钉死。

模式库种子 = 仓内真实坑账提炼，
五类起步：真机求解 / 参数扫描战役 / 校准 / 综合注册 / 模板注册，
每类 5-10 条。扩库 = 往 ``FAILURE_MODE_LIBRARY`` 追加条目 + 需要的新探针
spec（注册表消费者：tests/unit/test_premortem.py 完整性锚）。

用法::

    from rfauto.core.premortem import premortem, detection_probes, run_probe

    report = premortem("real_solve", {"background_launch": True})
    report["failure_modes"]   # top-10（可能性档降序，同档按 mode_id）
    report["checklist"]       # 开工前核对表（按探针去重）
    report["probe_report"]    # 探针执行结果（context 为 Mapping 时）
    unknown → ValueError（负例契约）
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# 常量：任务类别 / 可能性档 / top-k 口径
# ---------------------------------------------------------------------------

#: 五类起步任务（round19 XN-1：战役/设计开工前；战役=param_sweep 主类）。
TASK_KINDS: tuple[str, ...] = (
    "real_solve",
    "param_sweep",
    "calibration",
    "synthesis_registration",
    "template_registration",
)

#: 任务类别中文标签（报告/核对表渲染面）。
TASK_KIND_LABELS: dict[str, str] = {
    "real_solve": "真机求解",
    "param_sweep": "参数扫描战役",
    "calibration": "校准",
    "synthesis_registration": "综合注册",
    "template_registration": "模板注册",
}

#: task_kind 别名（中英文惯称；归一到规范 id，确定性 alias 表）。
TASK_KIND_ALIASES: dict[str, str] = {
    "real_solve": "real_solve",
    "solve": "real_solve",
    "真机求解": "real_solve",
    "真机": "real_solve",
    "真跑": "real_solve",
    "param_sweep": "param_sweep",
    "sweep": "param_sweep",
    "campaign": "param_sweep",
    "参数扫描": "param_sweep",
    "参数扫描战役": "param_sweep",
    "战役": "param_sweep",
    "calibration": "calibration",
    "calibrate": "calibration",
    "校准": "calibration",
    "synthesis_registration": "synthesis_registration",
    "synthesis": "synthesis_registration",
    "综合注册": "synthesis_registration",
    "综合": "synthesis_registration",
    "template_registration": "template_registration",
    "template": "template_registration",
    "模板注册": "template_registration",
    "模板": "template_registration",
}

#: 可能性档与排序权（high 最先；round19 口径"最可能 N 种失败"按此排）。
LIKELIHOOD_BANDS: tuple[str, ...] = ("high", "medium", "low")
_LIKELIHOOD_RANK: dict[str, int] = {b: i for i, b in enumerate(LIKELIHOOD_BANDS)}

#: 缺省产出条数（round19 原文口径："最可能 10 种失败"）。
DEFAULT_TOP_K = 10

PREMORTEM_SCHEMA = "rfauto-premortem-v1"

# ---------------------------------------------------------------------------
# 检测探针：declarative spec + 纯函数执行器
# ---------------------------------------------------------------------------
# 探针 = 开工前对"开工声明面"（context 扁平键）的在案检查，三种检查类：
# - declares：keys 中任一键 truthy 即在案（#364④ 教训：truthy 判定天然
#   把 0/""/None 排除——声明值就用非零字符串/布尔，不拿 0 当"已声明"）
# - forbids：keys 中任一键 truthy 即不通过（禁用形态在案=红）
# - in：keys[0] 的值 ∈ value（值域检查）
# 探针不产生数字、不做 I/O——"在案？"是布尔判断不是测量（规则 7）。


@dataclass(frozen=True)
class ProbeSpec:
    """检测探针规格（可执行纯函数的 declarative 载体）。

    - probe_id：全局唯一（registry 键，失败模式以 id 引用）
    - question：探针问句（核对表渲染面，如"发射前互斥自检在案？"）
    - check_kind：declares | forbids | in
    - keys：declares/forbids 为全部参与键；in 为单键（keys[0]）
    - value：in 检查的合法值域（tuple，成员判定，非序敏感）
    - lesson_refs：探针背书的坑号（渲染时随行）
    """

    probe_id: str
    question: str
    check_kind: str
    keys: tuple[str, ...]
    value: tuple[Any, ...] = ()
    lesson_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "probe_id": self.probe_id,
            "question": self.question,
            "check_kind": self.check_kind,
            "keys": list(self.keys),
            "value": [v for v in self.value],
            "lesson_refs": list(self.lesson_refs),
        }


def _spec(probe_id: str, question: str, *, keys: tuple[str, ...],
          check_kind: str = "declares", value: tuple[Any, ...] = (),
          lessons: tuple[str, ...] = ()) -> ProbeSpec:
    """探针 spec 紧凑构造（库表可读性；lessons=坑号背书）。"""
    return ProbeSpec(probe_id=probe_id, question=question,
                     check_kind=check_kind, keys=tuple(keys),
                     value=tuple(value), lesson_refs=tuple(lessons))


#: 全量探针注册表（跨五类并集；probe_id 唯一，同类内按 mode 顺序登记）。
PROBE_REGISTRY: dict[str, ProbeSpec] = {}
for _p in (
    # ── real_solve 真机求解 ──
    _spec("launch_isolated", "发射形态=后台分离进程+日志文件轮询（非前台裸跑）在案？",
          keys=("background_launch", "harness_launch", "wait_launcher"),
          lessons=("#157", "#323", "#177")),
    _spec("watcher_survival_probe", "长跑存活探针（周期按命令行匹配列 PID 落日志）在案？",
          keys=("watcher_probe", "survival_probe"),
          lessons=("#323", "#157")),
    _spec("orphan_desktop_swept", "开工前孤儿 ansysedt（父进程已死）清点在案？",
          keys=("orphan_desktop_swept", "orphan_sweep"),
          lessons=("#265", "#308")),
    _spec("absolute_outdir", "求解 outdir 全部绝对路径（相对 -outdir 构造期挂起）在案？",
          keys=("absolute_outdir",),
          lessons=("#243",)),
    _spec("hpeesof_env", "ADS/hpeesofsim 环境面（HPEESOF_DIR/PATH 前置+仓根执行）在案？",
          keys=("hpeesof_env", "ads_env", "hpeesof_dir"),
          lessons=("#272", "#295")),
    _spec("solo_slot", "计时敏感真机标 solo 单飞+发射前互斥自检（并发 2.3-8× 拖慢）在案？",
          keys=("solo_slot", "solo", "mutex_check"),
          lessons=("#246", "#261")),
    _spec("nrts_window_check", "时窗预算按终网格实测 dt 折算、FC 窗覆盖脉冲全程在案？",
          keys=("nrts_window_check", "nrts_budget"),
          lessons=("#262", "#343", "#312")),
    _spec("mesh_min_spacing_guard", "起跑前全轴最小线距守卫+缝内内部线 ≥1 在案？",
          keys=("mesh_min_spacing_guard", "mesh_guard"),
          lessons=("#152", "#349", "#311")),
    _spec("convergence_ladder", "HFSS 收敛验收（passes 未触顶+关键标量 ≥3 级 ΔS 阶梯饱和）在案？",
          keys=("convergence_ladder", "delta_s_ladder"),
          lessons=("#335",)),
    _spec("same_params_audit", "对照/审计路径与求解路径同参同网格（最终网格效力断言）在案？",
          keys=("same_params_audit",),
          lessons=("#368", "#335")),
    # ── param_sweep 参数扫描战役 ──
    _spec("cost_nondegenerate_smoke", "放量前小样本 cost 分布非退化常数冒烟在案？",
          keys=("cost_nondegenerate_smoke", "cost_smoke"),
          lessons=("#195", "#197")),
    _spec("valley_depth_scan", "新族接入前谷深扫描定门口径（线性域 |Γ| 或 εeff）在案？",
          keys=("valley_depth_scan",),
          lessons=("#370", "#371")),
    _spec("study_seed_unique", "新轨迹换 study/seed（同种子 study 复用=缓存秒回）在案？",
          keys=("study_seed_unique",),
          lessons=("#158",)),
    _spec("first_point_ingest", "放量前先跑 1 点 ingest 核对成行在案？",
          keys=("first_point_ingest",),
          lessons=("#251",)),
    _spec("plan_full_params", "plan 化探针/部分运行带与放量一致的全参数在案？",
          keys=("plan_full_params",),
          lessons=("#df4③",)),
    _spec("total_count_semantics", "总数语义实测返回语义（n_rows=limit 截断≠全量计数）在案？",
          keys=("total_count_semantics",),
          lessons=("#369",)),
    _spec("explicit_none_check", "判据布尔化 is not None 显式判缺（0.0 合法值不被顶替）在案？",
          keys=("explicit_none_check",),
          lessons=("#364④", "#117")),
    _spec("extend_budget_accounting", "帽停自动展延按重跑全程计预算（wall 突回退=展延信号）在案？",
          keys=("extend_budget_accounting",),
          lessons=("#df7⑦",)),
    _spec("chdir_isolation", "优化循环 chdir 隔离（不污染真实 runs）在案？",
          keys=("chdir_isolation",),
          lessons=("#144",)),
    _spec("waiting_trial_recheck", "enqueue 注入后回查 user_attrs WAITING trial 号（不依赖返回值）在案？",
          keys=("waiting_trial_recheck",),
          lessons=("#123",)),
    # ── calibration 校准 ──
    _spec("model_audit_first", "修正前先审计建模正确性（几何/单位/端口/网格）在案？",
          keys=("model_audit_first",),
          lessons=("#1b", "#191")),
    _spec("param_key_priority", "导入参数段键路径优先级 params>calib_params>design_params 钉死在案？",
          keys=("param_key_priority",),
          lessons=("#320",)),
    _spec("measured_mask", "补齐矩阵随行已测掩码、判据只对两向独立已测对下结论在案？",
          keys=("measured_mask",),
          lessons=("#314", "#316")),
    _spec("peak_metric_defined", "峰位/频偏报告与门口径固定（−3dB 带心或 |Y| 极小，非 argmax）在案？",
          keys=("peak_metric_defined",),
          lessons=("#298",)),
    _spec("explicit_curve_ref", "多曲线目录按显式引用/同名 stem 归属（不按文件序猜）在案？",
          keys=("explicit_curve_ref",),
          lessons=("#321",)),
    _spec("fingerprint_study_name", "导入行指纹 study_name 非空（防跨战役折叠同设计点）在案？",
          keys=("fingerprint_study_name",),
          lessons=("#322",)),
    _spec("synthetic_recovery", "拟合斜率→物理量换算带合成注入→回收钉在案？",
          keys=("synthetic_recovery",),
          lessons=("#340", "#118")),
    _spec("line_z0_inversion", "S 矩阵按列反演线基→去嵌→renormalize 50Ω（禁整矩阵直接归一）在案？",
          keys=("line_z0_inversion",),
          lessons=("#250", "#280")),
    _spec("per_er_fitting", "定标常数逐 εr 拟合（单 εr 定标外推会 +3~6%）在案？",
          keys=("per_er_fitting",),
          lessons=("#302", "#333")),
    # ── synthesis_registration 综合注册 ──
    _spec("registry_consumer_pins", "注册表消费者五钉清单（EXPECTED/不变量/计数/meta/文档）在案？",
          keys=("registry_consumer_pins",),
          lessons=("#231",)),
    _spec("referee_known_basis", "裁判先过已知基准（解析/闭式对拍+仓内可复跑实现）在案？",
          keys=("referee_known_basis",),
          lessons=("#300",)),
    _spec("independent_referee", "数值裁判=独立来源解析值+小步长收敛（非自家推导互证）在案？",
          keys=("independent_referee",),
          lessons=("#118", "#273")),
    _spec("continuity_scale", "闭式连续性测试激励尺度远低于灵敏度尺度（如 L≤1e-18H）在案？",
          keys=("continuity_scale",),
          lessons=("#299",)),
    _spec("saturation_branch", "双精度饱和死区分支（k′=sech 直取+inf 分支回 q=0）在案？",
          keys=("saturation_branch",),
          lessons=("#334",)),
    _spec("warm_bound_target", "warm-start 历史集上界剔除阈值=判据同款 target（verdict 带 channel）在案？",
          keys=("warm_bound_target",),
          lessons=("#273",)),
    _spec("explicit_variables", "对拍用例显式 set_variables 全部几何量（隐式 f0 直取只到 1e-4）在案？",
          keys=("explicit_variables",),
          lessons=("#306",)),
    # ── template_registration 模板注册 ──
    _spec("template_consumer_pins", "模板注册消费者钉（meta 一致性/几何审计/字面计数三处）在案？",
          keys=("template_consumer_pins",),
          lessons=("#304",)),
    _spec("nominal_hj_synthesis", "名义几何值（线宽/臂长/缝）全部 HJ 精算（禁沿用毫米数）在案？",
          keys=("nominal_hj_synthesis",),
          lessons=("#252", "#1c")),
    _spec("physics_roles_check", "同名几何参数跨适配器语义逐参数对（走 physics_roles）在案？",
          keys=("physics_roles_check",),
          lessons=("#154",)),
    _spec("offline_geometry_audit", "渲染→exec 几何段→CSXCAD 实测带宽/连通性（零仿真审计）在案？",
          keys=("offline_geometry_audit",),
          lessons=("#212", "#198")),
    _spec("mesh_guard_callpoints", "引入渲染守卫前 grep 全部调用点+审计档按模板查表在案？",
          keys=("mesh_guard_callpoints",),
          lessons=("#297", "#266")),
    _spec("grid_line_alignment", "端口/探针盒在终网格线集上三线齐备+阈值严格 > 口径在案？",
          keys=("grid_line_alignment",),
          lessons=("#283",)),
    _spec("default_path_diff", "渲染器加旋钮先验证缺省路径 unified diff 为空在案？",
          keys=("default_path_diff",),
          lessons=("#329",)),
    _spec("yaml_scalar_check", "YAML plain scalar 内 '#' 前半角空格截断（坑号全角包裹）在案？",
          keys=("yaml_scalar_check",),
          lessons=("#324",)),
    _spec("perfecte_assignment", "零厚度薄片导电=assign_perfecte_to_sheets（pec 盒不导电）在案？",
          keys=("perfecte_assignment",),
          lessons=("#356", "#310")),
    _spec("pyx_source_check", "CSXCAD Python 绑定 API 口径逐条对照 .pyx 源码在案？",
          keys=("pyx_source_check",),
          lessons=("#149", "#150", "#155")),
):
    if _p.probe_id in PROBE_REGISTRY:
        raise ValueError(f"探针 id 重复注册: {_p.probe_id}")
    PROBE_REGISTRY[_p.probe_id] = _p
del _p


def _normalize_task_kind(task_kind: Any) -> str:
    """task_kind（规范 id/别名/中文）→ 规范 id；未知 → ValueError（负例契约）。"""
    key = str(task_kind).strip().lower() if task_kind is not None else ""
    canonical = TASK_KIND_ALIASES.get(key)
    if canonical is None:
        # 中文别名不走 lower 命中，再原样试一次（lower 对中文恒等，等价兜底）
        canonical = TASK_KIND_ALIASES.get(str(task_kind).strip())
    if canonical is None:
        raise ValueError(
            f"未知 task_kind: {task_kind!r}（合法类别: {', '.join(TASK_KINDS)}"
            f"；中文别名: 真机求解/参数扫描/校准/综合注册/模板注册）")
    return canonical


def detection_probes(task_kind: Any) -> tuple[ProbeSpec, ...]:
    """task_kind → 该类失败模式引用的全部检测探针规格（probe_id 序，确定性）。

    未知 task_kind → ValueError。返回冻结元组——同输入两次逐位一致。
    """
    kind = _normalize_task_kind(task_kind)
    ids = sorted({fm.detection_probe for fm in FAILURE_MODE_LIBRARY[kind]})
    missing = [pid for pid in ids if pid not in PROBE_REGISTRY]
    if missing:  # 库完整性自检（不应发生；锚测试双钉）
        raise ValueError(f"失败模式引用了未注册探针: {missing}")
    return tuple(PROBE_REGISTRY[pid] for pid in ids)


def run_probe(probe: str | ProbeSpec, context: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """执行单个检测探针（纯函数：只读 context，不碰 I/O，无随机）。

    返回 {"ok", "probe_id", "question", "check_kind", "detail"}；
    未知 probe_id → ValueError。context 缺省 {}（全未声明 → declares 不通过）。
    """
    if isinstance(probe, str):
        spec = PROBE_REGISTRY.get(probe)
        if spec is None:
            raise ValueError(f"未知检测探针: {probe!r}")
    elif isinstance(probe, ProbeSpec):
        spec = probe
    else:
        raise ValueError(f"未知检测探针: {probe!r}")
    ctx: Mapping[str, Any] = context or {}
    if spec.check_kind == "declares":
        hit = sorted(k for k in spec.keys if ctx.get(k))
        ok = bool(hit)
        detail = (f"已声明: {', '.join(hit)}" if ok
                  else f"未声明（期待任一）: {', '.join(spec.keys)}")
    elif spec.check_kind == "forbids":
        hit = sorted(k for k in spec.keys if ctx.get(k))
        ok = not hit
        detail = (f"禁用形态在案: {', '.join(hit)}" if hit
                  else f"未出现禁用形态: {', '.join(spec.keys)}")
    elif spec.check_kind == "in":
        val = ctx.get(spec.keys[0])
        ok = val in spec.value
        detail = (f"{spec.keys[0]}={val!r} 在合法值域" if ok
                  else f"{spec.keys[0]}={val!r} 不在值域 {list(spec.value)}")
    else:
        raise ValueError(f"探针 {spec.probe_id} 未知检查类: {spec.check_kind}")
    return {"ok": ok, "probe_id": spec.probe_id, "question": spec.question,
            "check_kind": spec.check_kind, "detail": detail}


# ---------------------------------------------------------------------------
# 失败模式库（静态结构化知识；LLM 不产失败模式——硬规则 7）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FailureMode:
    """单条失败模式（坑账提炼的结构化知识条目）。

    - mode_id：全局唯一（<类前缀>-<序号>，如 RS-01）
    - task_kind：所属任务类别（规范 id）
    - mode：失败模式名（一句话讲清"怎么死"）
    - likelihood_band：可能性档 high|medium|low（仓内复发频次的经验定档）
    - early_signals：症状指纹（早期信号，判读时逐条对照）
    - detection_probe：检测探针 id（PROBE_REGISTRY 键）
    - mitigation_ref：缓解引用（坑号/TODO 项/ 规则号，可溯）
    - source：出处
    """

    mode_id: str
    task_kind: str
    mode: str
    likelihood_band: str
    early_signals: tuple[str, ...]
    detection_probe: str
    mitigation_ref: str
    source: str
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode_id": self.mode_id,
            "task_kind": self.task_kind,
            "mode": self.mode,
            "likelihood_band": self.likelihood_band,
            "early_signals": list(self.early_signals),
            "detection_probe": self.detection_probe,
            "probe_question": (PROBE_REGISTRY[self.detection_probe].question
                               if self.detection_probe in PROBE_REGISTRY else ""),
            "mitigation_ref": self.mitigation_ref,
            "source": self.source,
            "schema_version": self.schema_version,
        }


def _fm(mode_id: str, task_kind: str, mode: str, band: str,
        signals: Sequence[str], probe: str, ref: str, source: str) -> FailureMode:
    """库表紧凑构造（band 合法性与探针存在性即时校验——坏条目注册即炸）。"""
    if band not in _LIKELIHOOD_RANK:
        raise ValueError(f"{mode_id}: 未知可能性档 {band!r}")
    if probe not in PROBE_REGISTRY:
        raise ValueError(f"{mode_id}: 引用未注册探针 {probe!r}")
    return FailureMode(mode_id=mode_id, task_kind=task_kind, mode=mode,
                       likelihood_band=band, early_signals=tuple(signals),
                       detection_probe=probe, mitigation_ref=ref, source=source)


_SRC = "项目规则 踩坑速查"
_SRC_D = "项目规则 df4 批坑账"
_SRC_D7 = "项目规则 df7 批坑账"
_SRC_R4 = "项目规则 round4 审查批坑账"

#: 失败模式库（五类起步；条目全部提炼自仓内真实坑账，坑号可溯）。
FAILURE_MODE_LIBRARY: dict[str, tuple[FailureMode, ...]] = {
    "real_solve": (
        _fm("RS-01", "real_solve",
            "整树无声消失：求解进程树无 traceback 退出（#157 家族，来源不可证）",
            "high",
            ("进程表按命令行匹配的 PID 集合缩小而日志无异常栈",
             "et/ht 产物 mtime 停更且无新进程接管"),
            "watcher_survival_probe", "#157/#323/#177",
            _SRC + "（#157/#323）+ "),
        _fm("RS-02", "real_solve",
            "NrTS/FC 时窗截断：脉冲未跑完即触顶，|S11|>1 非物理假象",
            "high",
            ("max|S11|>1 且能量曲线触 NrTS 上限",
             "port_ut 末段时间轴远短于激励时长"),
            "nrts_window_check", "#262/#343/#312",
            _SRC + "（#262/#343/#312）"),
        _fm("RS-03", "real_solve",
            "网格最小间距塌缩：nm 级近重合线使 dt 塌缩数量级（症状是 CalcPort "
            "IndexError 而非网格报错）",
            "high",
            ("CSXCAD 网格 dt 比同档已知模板低多个量级",
             "起跑审计报缝内内部线数为 0"),
            "mesh_min_spacing_guard", "#152/#349/#311",
            _SRC + "（#152/#349/#311）"),
        _fm("RS-04", "real_solve",
            "孤儿 ansysedt：脚本退出未 release_desktop，占 HFSS 轨/许可数小时",
            "medium",
            ("父 python 已死而 ansysedt -grpcsrv 仍在",
             "HFSS 轨被占但队列无在跑任务"),
            "orphan_desktop_swept", "#265/#308",
            _SRC + "（#265/#308）"),
        _fm("RS-05", "real_solve",
            "发射形态裸奔：前台内联跑长求解，会话断/杀树连坐即全灭",
            "medium",
            ("发射命令行含内联 python -c 长求解",
             "无日志文件、进度只存 stdout"),
            "launch_isolated", "#157/#177/#df7①",            _SRC + "（#157/#177）+ " + _SRC_D7 + "①"),
        _fm("RS-06", "real_solve",
            "相对 outdir 挂起：Hfss() 相对 -outdir 构造期 Rename 挂 ~6min 后 "
            "GrpcApiError（3/3 复现）",
            "medium",
            ("构造期卡死分钟级无日志推进",
             "报错栈在 Project.Rename 附近"),
            "absolute_outdir", "#243",
            _SRC + "（#243）"),
        _fm("RS-07", "real_solve",
            "ADS 环境缺失：hpeesofsim 裸调静默无输出（exit 0、无产物、无报错）",
            "medium",
            ("仿真命令 exit 0 但无产物落盘",
             "stdout/stderr 双空"),
            "hpeesof_env", "#272/#295",
            _SRC + "（#272/#295）"),
        _fm("RS-08", "real_solve",
            "同机并发争用：多求解并发互相拖慢 2.3-8×，预算全线超支",
            "medium",
            ("wall 时间数倍于独占机基线",
             "CPU 时长正常而墙钟暴涨"),
            "solo_slot", "#246/#df7⑤",
            _SRC + "（#246）+ " + _SRC_D7 + "⑤"),
        _fm("RS-09", "real_solve",
            "未收敛先判向：ΔS 达标但 passes 触顶，关键标量随 ΔS 阶梯漂移 0.8dB",
            "medium",
            ("setup 报 final_delta_s 达标但 passes==max_passes",
             "ΔS 收紧一档后关键指标移动超门"),
            "convergence_ladder", "#335",
            _SRC + "（#335）"),
        _fm("RS-10", "real_solve",
            "审计/求解参数漂移：对照实验拿错配方审计（自动档 vs 实跑档），"
            "效力断言在错网格上做",
            "medium",
            ("对照\"无差异\"与引擎 debugCSX 逐位对比矛盾",
             "审计网格档与 EMSolverConfig 缺省不一致"),
            "same_params_audit", "#368/#335",
            _SRC + "（#368）"),
    ),
    "param_sweep": (
        _fm("PS-01", "param_sweep",
            "cost 退化常数：判据统计量与响应形态失配（带内 max 恒定），"
            "优化无梯度白跑整役",
            "high",
            ("已完成点 cost 方差≈0（常数平台）",
             "best 与 worst 同值"),
            "cost_nondegenerate_smoke", "#195/#197",
            _SRC + "（#195/#197）"),
        _fm("PS-02", "param_sweep",
            "深谷族 dB 门误定：dB 域 GP/验收门对深谐振谷病态，加密反而恶化",
            "high",
            ("S11 谷深 −50dB 以下且加密后 dB 误差反向爆炸",
             "线性域 |Γ| 误差正常而 dB 门 FAIL"),
            "valley_depth_scan", "#370/#371",
            _SRC + "（#370/#371）"),
        _fm("PS-03", "param_sweep",
            "study 复用假秒回：同种子同 study 重跑走缓存秒回，新轨迹没真跑",
            "high",
            ("战役\"完成\"耗时秒级且 trials 数不增",
             "配对实验两臂轨迹逐位相同"),
            "study_seed_unique", "#158",
            _SRC + "（#158）"),
        _fm("PS-04", "param_sweep",
            "收集器零点：单次 run/新产物形态不被收集分支认识，战役跑完 n_gt 纹丝不动",
            "high",
            ("战役结束但数据集行数 0 增长",
             "ingest 报 skipped 占比 100%"),
            "first_point_ingest", "#251",
            _SRC + "（#251）"),
        _fm("PS-05", "param_sweep",
            "plan 冻结缺省点数：探针/部分运行缺全参数，放量撞不可变校验",
            "medium",
            ("探针跑通后放量报 plan 冻结参数冲突",
             "n_points 与预申报不一致"),
            "plan_full_params", "#df4③",
            _SRC_D + "③"),
        _fm("PS-06", "param_sweep",
            "总数语义误读：n_rows=limit 截断行数被当全量计数，judge 全红假 FAIL",
            "medium",
            ("judge 报行数远小于战役点数",
             "limit 参数与计数消费同点"),
            "total_count_semantics", "#369",
            _SRC + "（#369）"),
        _fm("PS-07", "param_sweep",
            "falsy 顶替合法 0.0：float(cost or 1e9) 把达标零值判成缺失",
            "medium",
            ("cost 恰为 0 的达标点被判 FAIL/缺失",
             "缺失率与达标率同步异常"),
            "explicit_none_check", "#364④/#117",
            _SRC_R4 + "④+（#117）"),
        _fm("PS-08", "param_sweep",
            "帽停展延双倍墙钟：自动展延=引擎从头重跑，预算外推按单程漏算",
            "medium",
            ("wall 时间突然回退重涨",
             "et 文件时间轴从头开始"),
            "extend_budget_accounting", "#df7⑦",
            _SRC_D7 + "⑦"),
        _fm("PS-09", "param_sweep",
            "优化循环污染真实 runs/：测试/循环 chdir 未隔离，写脏生产数据目录",
            "low",
            ("runs/ 出现测试命名 meta",
             "生产目录 mtime 与无关注入吻合"),
            "chdir_isolation", "#144",
            _SRC + "（#144）"),
        _fm("PS-10", "param_sweep",
            "enqueue 注入丢失：enqueue_trial 返回 None 被依赖，warm 点没真进队",
            "low",
            ("WAITING 队列无注入点",
             "warm 首 trial 与历史最优点不重合"),
            "waiting_trial_recheck", "#123",
            _SRC + "（#123）"),
    ),
    "calibration": (
        _fm("CA-01", "calibration",
            "对错误模型校准：建模错误（几何/单位/端口）被调参固化",
            "high",
            ("校准残差系统性偏移且多保真互不一致",
             "网格收敛后指标整体平移不收敛"),
            "model_audit_first", "#1b/#191",
            "项目规则 硬限制 1b+（#191）"),
        _fm("CA-02", "calibration",
            "参数段张冠李戴：design_params（校准前设计值）与 calib_params（实跑几何）"
            "语义相反，提取静默错配",
            "high",
            ("导入行几何与该目录实跑记录矛盾",
             "键名带设计值指纹（如 g0500）与 value 不符"),
            "param_key_priority", "#320",
            _SRC + "（#320）"),
        _fm("CA-03", "calibration",
            "补齐矩阵当测量值：对称/互易补齐元素混入判据，互易因子拿 |S21| 当不对称",
            "high",
            ("max_asym 恰等于传输幅值（−3dB 指纹）",
             "健康门拦掉整批真机 run"),
            "measured_mask", "#314/#316",
            _SRC + "（#314/#316）"),
        _fm("CA-04", "calibration",
            "argmax 峰位歧义：等值平台内 argmax 随微小畸变跳变，频偏报告非物理",
            "medium",
            ("峰位报告在两轮间跳变数个 %",
             "指标在带缘/带心双峰等值"),
            "peak_metric_defined", "#298/#281",
            _SRC + "（#298/#281）"),
        _fm("CA-05", "calibration",
            "多曲线误归属：共用根级 JSON 的多曲线目录按文件序取上下文，参数配错曲线",
            "medium",
            ("校准趋势散乱无单调性",
             "同参数不同曲线判读互斥"),
            "explicit_curve_ref", "#321",
            _SRC + "（#321）"),
        _fm("CA-06", "calibration",
            "指纹跨战役折叠：导入行 study_name 置空，同设计点跨战役被折叠丢失",
            "low",
            ("导入后行数少于源目录曲线数",
             "dup 组跨战役目录出现"),
            "fingerprint_study_name", "#322",
            _SRC + "（#322）"),
        _fm("CA-07", "calibration",
            "斜率换算错：拟合斜率→物理量少除/多除因子（τ 低估 6.3×），无回收钉漏检",
            "medium",
            ("提取量与解析期望差整数倍",
             "合成已知量注入回收不回原值"),
            "synthetic_recovery", "#340/#118",
            _SRC + "（#340/#118）"),
        _fm("CA-08", "calibration",
            "归一化错路：整矩阵 renormalize 到 50Ω（合成误差=|Γ_step|），非线基反演链",
            "medium",
            ("装配矩阵非无源（σmax>1）",
             "馈线引擎 ZL 偏 50Ω 时伪反射常数"),
            "line_z0_inversion", "#250/#280",
            _SRC + "（#250/#280）"),
        _fm("CA-09", "calibration",
            "单 εr 定标外推：闭式重定标在单 εr 平面拟合，高 εr 外推 +3~82%",
            "low",
            ("族内其他 εr 对拍偏差陡增",
             "定标残差随 εr 单调发散"),
            "per_er_fitting", "#302/#333",
            _SRC + "（#302/#333）"),
    ),
    "synthesis_registration": (
        _fm("SR-01", "synthesis_registration",
            "注册表消费者漏钉：新键只过本项定向门，合流全量门红（EXPECTED/不变量/"
            "计数表不同步）",
            "high",
            ("定向绿而 test_calculators/test_physics_invariants/计数控红",
             "注册表键数与 EXPECTED 长度不一致"),
            "registry_consumer_pins", "#231/#304",
            _SRC + "（#231/#304）"),
        _fm("SR-02", "synthesis_registration",
            "裁判未过基准：未对拍任何解析/闭式基准的裁判先裁定闭式，方向写反",
            "high",
            ("两份未入库 FD 互相矛盾",
             "refs 结论与第三方门相反"),
            "referee_known_basis", "#300",
            _SRC + "（#300）"),
        _fm("SR-03", "synthesis_registration",
            "自家推导当裁判：推导/解析期望与实现同源自证，错公式互证通过",
            "high",
            ("实现与自家推导逐位一致但第三方门红",
             "回收测试的参考实现 import 被测实现"),
            "independent_referee", "#118/#273",
            _SRC + "（#118/#273）"),
        _fm("SR-04", "synthesis_registration",
            "连续性尺度失配：闭式退化连续性测试的激励尺度在灵敏度区内，1e-15H 已偏 5e-6",
            "medium",
            ("连续性用例在门限附近红",
             "取更小尺度后同门转绿"),
            "continuity_scale", "#299",
            _SRC + "（#299）"),
        _fm("SR-05", "synthesis_registration",
            "双精度饱和死区：tanh(x≳19) 饱和为 1.0 使比值死区（q 恒 0），inf 分支回错值",
            "medium",
            ("端点参数下 q 恒 0 或端点检查炸",
             "大 x 输入输出不再随 x 变化"),
            "saturation_branch", "#334",
            _SRC + "（#334）"),
        _fm("SR-06", "synthesis_registration",
            "warm 上界阈值错：历史集剔除阈值≠判据 target，warm 首 trial 仍平推假红利",
            "medium",
            ("warm 达标率异常高于冷臂",
             "verdict 无 channel 字段"),
            "warm_bound_target", "#273",
            _SRC + "（#273）"),
        _fm("SR-07", "synthesis_registration",
            "隐式变量对拍：FakeAdapter 无显式变量时 f0 直取不走几何反演，逐位对拍失真",
            "low",
            ("名义 vs 解析只到 ~1e-4",
             "set_variables 补全后骤降至 1e-9"),
            "explicit_variables", "#306",
            _SRC + "（#306）"),
    ),
    "template_registration": (
        _fm("TR-01", "template_registration",
            "注册消费者漏钉：模板键集与 meta.yaml/counters 不同步，交付门绿而"
            " meta 一致性/几何审计/字面计数红",
            "high",
            ("test_template_meta_consistency/EXPECTED_TEMPLATES/==N 计数红",
             "TEMPLATE_NOMINAL 键集与 docs meta 不一致"),
            "template_consumer_pins", "#304",
            _SRC + "（#304）"),
        _fm("TR-02", "template_registration",
            "名义几何非精算：臂长/线宽沿用其他模型毫米数，名义谐振偏差 −10.8%",
            "high",
            ("名义值与 HJ 综合值差 >1%",
             "引擎-闭式一致而设计值整体偏移"),
            "nominal_hj_synthesis", "#252/#1c",
            _SRC + "（#252）+ 硬限制 1c"),
        _fm("TR-03", "template_registration",
            "跨适配器参数语义漂移：同名几何参数各通道各画各的，单通道对而跨保真"
            "是两个器件家族",
            "high",
            ("单通道审计全绿、跨保真 S 参数族不重合",
             "physics_roles 无该参数条目"),
            "physics_roles_check", "#154",
            _SRC + "（#154）"),
        _fm("TR-04", "template_registration",
            "画法错误漏检：字符串存在性/compile() 抓不住几何画法错，三端口全死",
            "high",
            ("CSXCAD 实测带宽远窄于设计或端口零传输",
             "激励体积为零/盒边未进网格"),
            "offline_geometry_audit", "#212/#198/#174",
            _SRC + "（#212/#198/#174）"),
        _fm("TR-05", "template_registration",
            "薄片不导电：零厚度盒 material=pec 在 HFSS 不导电，|S11|≈−0.2dB 全反射",
            "high",
            ("HFSS 端口解出空框模式",
             "电流路径在薄片处断开"),
            "perfecte_assignment", "#356/#310",
            _SRC + "（#356/#310）"),
        _fm("TR-06", "template_registration",
            "网格守卫级联：渲染级硬守卫打红全部按固定审计档渲染的离线消费者",
            "medium",
            ("守卫上线后既有单测 MESH_MM 全越界红",
             "审计 helper 与消费档网格不一致"),
            "mesh_guard_callpoints", "#297/#266",
            _SRC + "（#297/#266）"),
        _fm("TR-07", "template_registration",
            "端口/探针落格失败：探针盒中线不在终网格线集上，u/i 探针吸附盒角/边界",
            "medium",
            ("跨轮装配偏差中位 ~2%",
             "port_ut 头 start-coordinates 偏离设计面"),
            "grid_line_alignment", "#283",
            _SRC + "（#283）"),
        _fm("TR-08", "template_registration",
            "旋钮缺省路径漂移：渲染器加旋钮未验证缺省路径不变，无旋钮消费者静默改变",
            "medium",
            ("缺省参数渲染 unified diff 非空",
             "既有字节钉/哈希钉转红"),
            "default_path_diff", "#329",
            _SRC + "（#329）"),
        _fm("TR-09", "template_registration",
            "YAML 坑号截断：plain scalar 内 '#' 前半角空格把行内引注截成注释",
            "low",
            ("meta reasons 字段半截",
             "读回 YAML 与写入意图不符"),
            "yaml_scalar_check", "#324",
            _SRC + "（#324）"),
        _fm("TR-10", "template_registration",
            "CSXCAD 绑定口径错：按 MATLAB 版 API 写 Python 绑定（AddMetal priority/"
            "SetError 位置），注册即 TypeError 或端口静默缺激励",
            "medium",
            ("渲染抛 TypeError 或 MSLPort 无激励属性",
             "GetAllPrimitives 数量与预期不符"),
            "pyx_source_check", "#149/#150/#155",
            _SRC + "（#149/#150/#155）"),
    ),
}

#: 每类最低条数（完整性锚的封闭断言值；扩库不得低于此线）。
MIN_MODES_PER_KIND = 5

#: 每类最高条数上界参考（round19 口径"最可能 10 种"——超 10 条时 premortem
#: 按 likelihood 档+mode_id 截 top-k）。
MAX_MODES_PER_KIND = 10

# 类前缀 ↔ task_kind（mode_id 命名锚用，确定性映射）
KIND_PREFIX: dict[str, str] = {
    "real_solve": "RS",
    "param_sweep": "PS",
    "calibration": "CA",
    "synthesis_registration": "SR",
    "template_registration": "TR",
}
_PREFIX_KIND: dict[str, str] = {v: k for k, v in KIND_PREFIX.items()}


def _mode_sort_key(fm: FailureMode) -> tuple[int, str]:
    """确定性排序键：可能性档升序（high 先）→ mode_id 字典序。"""
    return (_LIKELIHOOD_RANK.get(fm.likelihood_band, len(LIKELIHOOD_BANDS)),
            fm.mode_id)


def premortem(task_kind: Any, context: Any = None, *,
              top_k: int = DEFAULT_TOP_K) -> dict[str, Any]:
    """开工前失败预演（XN-1 主入口，确定性规则引擎）。

    task_kind：五类之一（规范 id 或中文别名；未知 → ValueError）。
    context：开工声明面（Mapping，扁平键；None 视为 {}——只铺模式表不跑探针）。
    top_k：产出条数帽（round19 口径缺省 10；可能性档 high>medium>low，
           同档按 mode_id；并列确定性）。

    返回 JSON 友好契约::

        {ok, schema, task_kind, task_kind_label, n_modes_total, top_k,
         failure_modes: [{mode_id, task_kind, mode, likelihood_band,
                          early_signals[], detection_probe, probe_question,
                          mitigation_ref, source, schema_version}],
         checklist: [{item, probe_id, question, lesson_refs[], source_refs[]}],
         probe_report: [{ok, probe_id, question, check_kind, detail}]}
    probe_report 仅在 context 为 Mapping 时附带（探针可执行面）。
    """
    kind = _normalize_task_kind(task_kind)
    pool = list(FAILURE_MODE_LIBRARY[kind])
    ordered = sorted(pool, key=_mode_sort_key)
    k = max(int(top_k), 0)
    selected = ordered[:k]
    ctx: Mapping[str, Any] = context if isinstance(context, Mapping) else {}

    # 核对表：按选中模式的探针去重（顺序=首次出现序，确定性），来源坑号归并
    checklist: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    for fm in selected:
        spec = PROBE_REGISTRY[fm.detection_probe]
        item = seen.get(fm.detection_probe)
        if item is None:
            item = {
                "item": spec.question,
                "probe_id": spec.probe_id,
                "question": spec.question,
                "lesson_refs": list(spec.lesson_refs),
                "source_refs": [],
            }
            seen[fm.detection_probe] = item
            checklist.append(item)
        if fm.mitigation_ref and fm.mitigation_ref not in item["source_refs"]:
            item["source_refs"].append(fm.mitigation_ref)

    result: dict[str, Any] = {
        "ok": True,
        "schema": PREMORTEM_SCHEMA,
        "task_kind": kind,
        "task_kind_label": TASK_KIND_LABELS[kind],
        "n_modes_total": len(pool),
        "top_k": k,
        "failure_modes": [fm.to_dict() for fm in selected],
        "checklist": checklist,
    }
    if isinstance(context, Mapping):
        result["probe_report"] = [
            run_probe(spec, ctx) for spec in detection_probes(kind)
        ]
        result["n_probes_open"] = sum(1 for r in result["probe_report"]
                                      if not r["ok"])
    return result


def render_premortem_markdown(result: Mapping[str, Any], *,
                              heading: str | None = None) -> str:
    """premortem 结果 → 确定性 markdown 章节（无 LLM；非 ok 结果返回空串）。

    结构：标题（任务类别 + 总数）→ 失败模式表（模式/档/症状指纹/缓解引用）
    → 开工核对表（探针问句 + 坑号）→ 探针未闭合清单（context 附带时）。
    """
    if not result.get("ok"):
        return ""
    kind = str(result.get("task_kind", ""))
    label = str(result.get("task_kind_label", kind))
    lines = [heading or (f"## Pre-mortem 失败预演（{label}）"), ""]
    modes = list(result.get("failure_modes") or [])
    lines.append(f"失败模式 {len(modes)}/{result.get('n_modes_total', len(modes))}"
                 f"（可能性档降序）：")
    lines.append("")
    for fm in modes:
        lines.append(f"- **{fm.get('mode_id')} [{fm.get('likelihood_band')}]** "
                     f"{fm.get('mode')}")
        for sig in fm.get("early_signals") or []:
            lines.append(f"  - 症状指纹：{sig}")
        lines.append(f"  - 检测探针：{fm.get('probe_question')}"
                     f"（{fm.get('detection_probe')}）")
        lines.append(f"  - 缓解引用：{fm.get('mitigation_ref')}"
                     f"｜出处：{fm.get('source')}")
    checklist = list(result.get("checklist") or [])
    if checklist:
        lines += ["", "### 开工前核对表", ""]
        for i, item in enumerate(checklist, 1):
            refs = "、".join(item.get("source_refs") or [])
            lines.append(f"- [ ] {i}. {item.get('question')}"
                         + (f"（{refs}）" if refs else ""))
    probe_report = list(result.get("probe_report") or [])
    open_probes = [p for p in probe_report if not p.get("ok")]
    if probe_report:
        lines += ["", f"### 检测探针 {len(probe_report) - len(open_probes)}"
                      f"/{len(probe_report)} 闭合", ""]
        for p in probe_report:
            mark = "x" if p.get("ok") else " "
            lines.append(f"- [{mark}] {p.get('question')}——{p.get('detail')}")
    lines.append("")
    return "\n".join(lines)
