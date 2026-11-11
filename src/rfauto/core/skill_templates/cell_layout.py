"""cell_layout 模板——打开 cellview + 创建 layout 基本图形（矩形/路径/标签）。

用法（本地 Virtuoso CIW）::

    load("cell_layout.il")

变量契约（铁律 7：几何/层/文本全部来自调用方变量，模板零手拍电路数值）：

- ``lib_name``/``cell_name``（str，必填）——目标库/cell（带引号直出）；
- ``view_name``（str，可选缺省 "layout"）；
- ``view_type``（str，可选缺省 "maskLayout"）；
- ``shapes``（list[dict]，必填）——逐图形记录：
  - ``type: "rect"``：layer/purpose(默认 drawing)/x1,y1,x2,y2（数值）；
  - ``type: "path"``：layer/purpose/width（数值）/points（**raw** 预成形
    SKILL 点表如 ``list(0:0 10:0 10:5)``——点表形态由调用方拼装，模板
    不代造几何）；
  - ``type: "label"``：layer/purpose(默认 text)/x,y/text/justify(默认
    centerCenter)/font(默认 R0)/height(默认 0.25 数值——结构旋钮非电路值)；
- ``title``（str，可选）——文件头注释行。

函数名出处（#122 如实声明；发布版须对照本地 SKILL Language Reference
校准——本仓无 Virtuoso 安装，参数形态为 Cadence 文档常用惯例）：
``dbOpenCellViewByType(lib cell view mode type)``（mode "a"=append，
type "maskLayout"）/ ``dbCreateRect(cvId layerPurpose bBox)`` /
``dbCreatePath(cvId layerPurpose width points)`` /
``dbCreateLabel(cvId layerPurpose point label justify font height type)`` /
``dbSave`` / ``dbClose``。
"""

from __future__ import annotations

from rfauto.core.skill_templates import SkillTemplateSpec, register_skill_template

SOURCE = """\
; {{title|default("cell layout skeleton (rfauto skill render)")}}
; 由 rfauto 模板+变量直出（零手拍电路数值）；函数名以本地 SKILL Language Reference 为准
let( (cv)
  cv = dbOpenCellViewByType({{lib_name}} {{cell_name}} {{view_name|default("layout")}} "a" {{view_type|default("maskLayout")}})
{%for s in shapes%}  {%if s.type == "rect"%}dbCreateRect(cv list({{s.layer}} {{s.purpose|default("drawing")}}) list({{s.x1}}:{{s.y1}} {{s.x2}}:{{s.y2}}))
{%elif s.type == "path"%}dbCreatePath(cv list({{s.layer}} {{s.purpose|default("drawing")}}) {{s.width}} {{s.points|raw}})
{%elif s.type == "label"%}dbCreateLabel(cv list({{s.layer}} {{s.purpose|default("text")}}) list({{s.x}}:{{s.y}}) {{s.text}} {{s.justify|default("centerCenter")}} {{s.font|default("R0")}} {{s.height|default(0.25)}} "labelObject")
{%endif%}{%endfor%}  dbSave(cv)
  dbClose(cv)
)
"""

register_skill_template(SkillTemplateSpec(
    name="cell_layout",
    title="cellview 打开 + layout 基本图形（矩形/路径/标签）",
    description=(
        "打开目标库/cell 的 layout cellview 并按 shapes 清单逐条创建 "
        "dbCreateRect/dbCreatePath/dbCreateLabel 图形，收尾 dbSave+dbClose。"
        "shapes 逐记录 type 分派：rect(bBox 四数值)/path(width+raw 点表)/"
        "label(文本+对齐+字体+高度)。"),
    category="layout",
    source=SOURCE,
    default_vars={},
    functions=(
        "dbOpenCellViewByType", "dbCreateRect", "dbCreatePath",
        "dbCreateLabel", "dbSave", "dbClose",
    ),
    example_vars={
        "lib_name": "myLib",
        "cell_name": "myCell",
        "shapes": [
            {"type": "rect", "layer": "Metal1", "x1": 0, "y1": 0,
             "x2": 10.0, "y2": 20.0},
            {"type": "path", "layer": "Metal1", "width": 0.5,
             "points": "list(0:0 10:0 10:5)"},
            {"type": "label", "layer": "Metal1", "x": 5.0, "y": 22.0,
             "text": "GND"},
        ],
    },
))
