"""layer_setup 模板——技术文件层定义 + 显示属性数据表（techfile 脚手架）。

用法（本地 Virtuoso CIW，对目标库有写权限）::

    load("layer_setup.il")

变量契约（铁律 7：层名/层号/颜色全部来自调用方变量，模板零手拍层表）：

- ``lib_name``（str，必填）——目标技术库；
- ``layers``（list[dict]，必填）——逐层：name/number（GDS 层号数值）/
  purpose（可选缺省 "drawing"）；
- ``display_rows``（list[dict]，可选缺省 []）——显示属性数据表逐行：
  layer/purpose/props（**raw** 预成形属性表如
  ``("lineStyle" "solid") ("color" "y0")``——属性形态调用方自理）；
- ``save``（bool，可选缺省 False）——true 时 techUpdateTechFile 落盘
  （先核对再落盘：techfile 变更不可逆，交互核对后显式置 true）；
- ``title``（str，可选）——文件头注释行。

函数名出处（#122 如实声明；发布版须对照本地 SKILL Language Reference
的 Tech File 函数节校准——本仓无 Virtuoso 安装，techAddLayer/
techUpdateTechFile 的签名与版本行为是**首要校准点**）：
``ddGetObj(lib)``（库对象）/ ``techGetTechFile(libId)``（技术文件句柄）/
``techAddLayer(tf layer purpose number)``（层定义脚手架）/
``techUpdateTechFile(tf)``（落盘——save=true 时才发射）。显示属性以
displayProps 纯 SKILL 数据表直出（assoc 形态零 API 面——按本地
display.drf 流程消费）。
"""

from __future__ import annotations

from rfauto.core.skill_templates import SkillTemplateSpec, register_skill_template

SOURCE = """\
; {{title|default("techfile layer setup skeleton (rfauto skill render)")}}
; 由 rfauto 模板+变量直出（零手拍层表）；函数名以本地 SKILL Language Reference 为准
let( (libId tf displayProps)
  libId = ddGetObj({{lib_name}})
  tf = techGetTechFile(libId)
{%for lyr in layers%}  techAddLayer(tf {{lyr.name}} {{lyr.purpose|default("drawing")}} {{lyr.number}})
{%endfor%}{%if display_rows%}  displayProps = '(
{%for r in display_rows%}    ({{r.layer}} {{r.purpose|default("drawing")}} {{r.props|raw}})
{%endfor%}  )
{%endif%}{%if save%}  techUpdateTechFile(tf)
{%endif%}\
)
"""

register_skill_template(SkillTemplateSpec(
    name="layer_setup",
    title="技术文件层定义 + 显示属性数据表",
    description=(
        "取目标库技术文件句柄后按 layers 清单 techAddLayer 逐层定义，"
        "display_rows 以纯 SKILL 数据表直出显示属性（零 API 面），"
        "save=true 时 techUpdateTechFile 落盘（缺省 False 交互核对）。"),
    category="techfile",
    source=SOURCE,
    default_vars={"display_rows": [], "save": False},
    functions=("ddGetObj", "techGetTechFile", "techAddLayer",
               "techUpdateTechFile"),
    example_vars={
        "lib_name": "myTechLib",
        "layers": [
            {"name": "Metal1", "number": 11},
            {"name": "Metal2", "number": 12, "purpose": "drawing"},
        ],
        "display_rows": [
            {"layer": "Metal1", "props": '("lineStyle" "solid") ("color" "y0")'},
        ],
        "save": True,
    },
))
