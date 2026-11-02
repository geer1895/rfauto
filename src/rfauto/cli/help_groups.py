"""CLI --help 按域分组面板（aurora_n wave_ui_c D1，审计 P2-4）。

问题：``rfauto --help`` 顶层命令 119 个全平铺在单一 Commands 面板，research
面与核心路径混排，新用户无法分辨"该看哪些"（TOUR_FINDINGS P2-4）。

修法（最小侵入形态）：typer 原生 rich 分组面板（rich_help_panel）——
**不新增/不改名/不重排任何命令**，只在注册完成后对 typer 内部 CommandInfo/
GroupInfo 补挂面板名注记（apply_help_panels，cli/main.py 注册链末尾调用）。
渲染面变化、注册面零变化：注册序金快照（test_cli_registration_order）、
叶命令计数（test_cli count_cli=280 口径）、zero-shadow 三钉全部不受影响；
D-06 字符纪律同守（面板名零裸 ``[`` 零 ``%``，rich markup 安全）。

面板序=各面板首个注册命令的出现序（registration order 派生，不独立可控
——核心工作流含 doctor=首命令，恒为第一面板）。未入表的新命令回落缺省
Commands 面板（不炸不隐藏），覆盖完整性由 test_aurora_n_wave_ui_c 的
集合相等断言守（新命令=显式评审动作，与本仓注册序金快照同口径）。

面板裁定口径（8 域，2026-10-29 wave_ui_c 席定）：
- 核心工作流=新手五步（doctor/syn/calc/run/runs health）+ 优化主链
  （tune/sweep/refine/autotune/tolerance/…）+ run 资产管理（runs/report/
  replay/jobs/cache/link/…）+ UI/模型/配方；
- 综合与设计=闭式综合/级联/拓扑/模板/版图/KiCad·EDB·HFSS 导入/互操作；
- 分析与研究=诊断/灵敏度/代理/UQ/VNA/远场/链路/P0·study 实验面；
- 数据与知识=数据集/湖/DB/锚/坑账/hints/rationale/RAG/教学卡；
- 报告与复现=报告族/PDF/复现包/叙述位/zenodo；
- 环境与可靠性=湿度/编织/低温/故障树/datasheet/老化/PDN/电热/寄生/量产统计；
- 自动化与协作=agent/审批/对话/审计/DAG/Goal/战役/重放/沙箱；
- 运维与开发=回归门/预检/剖析/远程/REST/夜间回归/求解器管理/脚手架。
"""

from __future__ import annotations

# 命令名（click 名，连字符形态）→ rich 面板名（119 顶层命令全覆盖；
# 面板名不含裸 [ 与 %——rich markup 渲染面，D-06 同纪律）。
HELP_PANEL_OF: dict[str, str] = {
    # ── 核心工作流（19）──
    "doctor": "核心工作流",
    "models": "核心工作流",
    "syn": "核心工作流",
    "calc": "核心工作流",
    "run": "核心工作流",
    "tune": "核心工作流",
    "sweep": "核心工作流",
    "refine": "核心工作流",
    "autotune": "核心工作流",
    "tolerance": "核心工作流",
    "validate": "核心工作流",
    "recipe": "核心工作流",
    "jobs": "核心工作流",
    "cache": "核心工作流",
    "link": "核心工作流",
    "replay": "核心工作流",
    "report": "报告与复现",
    "runs": "核心工作流",
    "ui": "核心工作流",
    "warm-start": "核心工作流",
    # ── 综合与设计（25）──
    "ads-circuit": "综合与设计",
    "array": "综合与设计",
    "budget": "综合与设计",
    "cascade": "综合与设计",
    "compose": "综合与设计",
    "compose-templates": "综合与设计",
    "constraints": "综合与设计",
    "design": "综合与设计",
    "diagram": "综合与设计",
    "edb": "综合与设计",
    "em": "综合与设计",
    "fab": "综合与设计",
    "firmware": "综合与设计",
    "hfss-import": "综合与设计",
    "interop": "综合与设计",
    "kicad": "综合与设计",
    "layout": "综合与设计",
    "lint": "综合与设计",
    "nfc": "综合与设计",
    "pcell": "综合与设计",
    "slotline": "综合与设计",
    "solid-import": "综合与设计",
    "templates": "综合与设计",
    "template-spec": "综合与设计",
    "topology": "综合与设计",
    "transitions": "综合与设计",
    # ── 分析与研究（29）──
    "afs": "分析与研究",
    "bands": "分析与研究",
    "cal-wizard": "分析与研究",  # aurora_p G1 2026-11-02（TRL 校准件设计向导）
    "certify": "分析与研究",
    "chain": "分析与研究",
    "competition": "分析与研究",
    "correlate": "分析与研究",
    "diagnose": "分析与研究",
    "even-odd": "分析与研究",
    "explain-run": "分析与研究",
    "farfield": "分析与研究",
    "logs": "分析与研究",
    "mmt": "分析与研究",
    "mo": "分析与研究",
    "nfmeas": "分析与研究",
    "oracle": "分析与研究",
    "p0": "分析与研究",
    "sar": "分析与研究",
    "self-heal": "分析与研究",
    "sensitivity": "分析与研究",
    "si": "分析与研究",
    "sparams-compare": "分析与研究",
    "study": "分析与研究",
    "surrogate": "分析与研究",
    "tolerance-allocate": "分析与研究",
    "uq": "分析与研究",
    "vna": "分析与研究",
    "vna-replay": "分析与研究",
    "verdict-summary": "分析与研究",
    # ── 数据与知识（12）──
    "al": "数据与知识",
    "anchors": "数据与知识",
    "datasets": "数据与知识",
    "db": "数据与知识",
    "few-shot": "数据与知识",
    "hints": "数据与知识",
    "lake": "数据与知识",
    "materials": "数据与知识",
    "pitfalls": "数据与知识",
    "rag": "数据与知识",
    "rationale": "数据与知识",
    "teaching": "数据与知识",
    # ── 报告与复现（11；report 在上方核心块内，面板归此域）──
    "datasheet": "报告与复现",
    "design-report": "报告与复现",
    "export-report-pdf": "报告与复现",
    "report-narrative": "报告与复现",
    "reports": "报告与复现",
    "repro": "报告与复现",
    "repro-manifest": "报告与复现",
    "repro-verify": "报告与复现",
    "tuning-report": "报告与复现",
    "zenodo": "报告与复现",
    # ── 环境与可靠性（9）──
    "aging": "环境与可靠性",
    "cryo": "环境与可靠性",
    "electrothermal": "环境与可靠性",
    "fault-tree": "环境与可靠性",
    "humidity": "环境与可靠性",
    "parasitic": "环境与可靠性",
    "pdn": "环境与可靠性",
    "stats": "环境与可靠性",
    "weave": "环境与可靠性",
    # ── 自动化与协作（10）──
    "agent": "自动化与协作",
    "audit": "自动化与协作",
    "campaign": "自动化与协作",
    "chat": "自动化与协作",
    "dag": "自动化与协作",
    "goal": "自动化与协作",
    "inbox": "自动化与协作",
    "recast": "自动化与协作",
    "sandbox": "自动化与协作",
    "watchdog": "自动化与协作",  # aurora_p F2 2026-11-02（seat 三证判活，常驻循环默认关）
    # ── 运维与开发（11）──
    "bench": "运维与开发",
    "dev": "运维与开发",
    "pool-patrol": "运维与开发",
    "port-gate": "运维与开发",
    "preflight": "运维与开发",
    "profile": "运维与开发",
    "remote": "运维与开发",
    "rest": "运维与开发",
    "simci": "运维与开发",
    "simci-pin-baseline": "运维与开发",
    "solvers": "运维与开发",
}


def top_level_panel_names() -> dict[str, str]:
    """映射的只读视图（测试消费；防调用方误改表）。"""
    return dict(HELP_PANEL_OF)


def apply_help_panels(app) -> int:
    """注册后按 HELP_PANEL_OF 补挂 rich_help_panel（只挂注记，零注册变化）。

    @app.command() 未显式命名的 CommandInfo.name 为 None（click 名在
    get_command 阶段才由函数名派生）——此处按 typer 同款规则
    （小写+下划线转连字符）先行派生再查表。幂等：已挂面板的 info 不覆盖
    （显式声明优先）。返回：本次补挂数（观测面）。
    """
    from typer.main import get_command_name

    n = 0
    for info in getattr(app, "registered_commands", None) or []:
        name = info.name or get_command_name(info.callback.__name__)
        panel = HELP_PANEL_OF.get(name)
        if panel and not info.rich_help_panel:
            info.rich_help_panel = panel
            n += 1
    for info in getattr(app, "registered_groups", None) or []:
        panel = HELP_PANEL_OF.get(info.name or "")
        if panel and not info.rich_help_panel:
            info.rich_help_panel = panel
            n += 1
    return n
