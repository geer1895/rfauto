"""waveform_export 模板——OCEAN 波形数据 CSV 导出（ocnPrint 后处理）。

用法（本地 Virtuoso ocean 命令行，已打开结果数据库/PSF 目录）::

    ocean> load("waveform_export.il")

变量契约（铁律 7：信号名/表达式/输出路径全部来自调用方变量，模板
零手拍信号清单）：

- ``out_csv``（str，必填）——CSV 输出路径；
- ``signals``（list[dict]，必填）——逐信号二选一：
  - ``name``：信号名（模板包成 ``v("name")`` 节点电压形态）；
  - ``expr``：预成形 SKILL 表达式（**raw** 直出，如 ``v("/out")``,
    ``IDC("/V0")``——表达式形态调用方自理，模板不代造）；
- ``number_notation``（str，可选缺省 "engineering"）——数值记法
  （版本相关词表 none/engineering/scientific 发布版须核）；
- ``precision``/``width``（数值，可选缺省 10/80——ocnPrint 结构旋钮）；
- ``title``（str，可选）——文件头注释行。

函数名出处（#122 如实声明；发布版须对照本地 OCEAN Reference 校准）：
``ocnPrint(?output path ?numberNotation s ?precision n ?width n ...)``——
选项关键词形态 + 信号表达式位置参数收尾；CSV 列分隔形态依版本
（部分 release 的 ocnPrint 支持分隔选项，本模板缺省走空格列分隔的
通用形态——CSV 化由消费端 Python 侧行处理或按本地 Reference 加
分隔选项）。
"""

from __future__ import annotations

from rfauto.core.skill_templates import SkillTemplateSpec, register_skill_template

SOURCE = """\
; {{title|default("waveform CSV export (rfauto skill render)")}}
; 由 rfauto 模板+变量直出（零手拍信号清单）；函数名以本地 OCEAN Reference 为准
ocnPrint(?output {{out_csv}} ?numberNotation {{number_notation|default("engineering")}} ?precision {{precision|default(10)}} ?width {{width|default(80)}}{%for sig in signals%}{%if sig.expr%} {{sig.expr|raw}}{%else%} v({{sig.name}}){%endif%}{%endfor%})
"""

register_skill_template(SkillTemplateSpec(
    name="waveform_export",
    title="波形数据 CSV 导出（ocnPrint）",
    description=(
        "对已打开的结果数据库 ocnPrint 导出信号波形：signals 逐条 "
        "name（v(\"名\") 电压节点形态）或 expr（预成形表达式 raw 直出），"
        "数值记法/精度/宽度走结构旋钮缺省。"),
    category="postproc",
    source=SOURCE,
    default_vars={"number_notation": "engineering", "precision": 10,
                  "width": 80},
    functions=("ocnPrint",),
    example_vars={
        "out_csv": "./wave_out.csv",
        "signals": [{"name": "out"}, {"expr": 'IDC("/V0")'}],
    },
))
