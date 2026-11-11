"""aedt_run_simulation 模板——ADE XL 仿真启动 + 结果汇总导出（OCEAN XL）。

用法（本地 Virtuoso CIW / ocean 命令行）::

    ocean> load("aedt_run_simulation.il")

变量契约（铁律 7：setup 文件名/汇总输出路径全部来自调用方变量）：

- ``setup_file``（str，必填）——ADE XL 图形界保存的 setup 文件
  （*.ocnxl）路径，经 ``load`` 加载恢复会话配置；
- ``summary_csv``（str，必填）——结果汇总 CSV 输出路径；
- ``exit_after``（bool，可选缺省 False）——true 时 run 后调 ocnxlExit()
  结束 XL 会话（批处理收尾用；交互会话保持缺省 False）；
- ``title``（str，可选）——文件头注释行。

函数名出处（#122 如实声明；发布版须对照本地 ADE XL OCEAN XL 参考校准）：
``load``（SKILL 核心字）/ ``ocnxlRun()``（启动 XL 批跑——setup 已含
corner/分析/输出配置）/ ``ocnxlOutputSummaryCSV(path)``（结果汇总 CSV
导出）/ ``ocnxlExit()``（会话收尾）。ADE L（asi* 系列）交互式分析不在
本模板面——XL 批跑口径。
"""

from __future__ import annotations

from rfauto.core.skill_templates import SkillTemplateSpec, register_skill_template

SOURCE = """\
; {{title|default("ADE XL run + summary CSV export (rfauto skill render)")}}
; 由 rfauto 模板+变量直出；函数名以本地 ADE XL OCEAN XL Reference 为准
load({{setup_file}})
ocnxlRun()
ocnxlOutputSummaryCSV({{summary_csv}})
{%if exit_after%}ocnxlExit()
{%endif%}\
"""

register_skill_template(SkillTemplateSpec(
    name="aedt_run_simulation",
    title="ADE XL 仿真启动 + 结果汇总 CSV 导出",
    description=(
        "加载 ADE XL setup 文件恢复会话配置后 ocnxlRun 批跑，"
        "ocnxlOutputSummaryCSV 导出结果汇总 CSV；exit_after=true 时 "
        "ocnxlExit 收尾会话（批处理口径）。"),
    category="simulation",
    source=SOURCE,
    default_vars={"exit_after": False},
    functions=("load", "ocnxlRun", "ocnxlOutputSummaryCSV", "ocnxlExit"),
    example_vars={
        "setup_file": "./mySim_setup.ocnxl",
        "summary_csv": "./results_summary.csv",
        "exit_after": True,
    },
))
