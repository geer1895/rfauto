"""schematic_instance 模板——放置器件实例 + 连线（schematic 基本操作）。

用法（本地 Virtuoso CIW）::

    load("schematic_instance.il")

变量契约（铁律 7：库/cell/实例名/坐标全部来自调用方变量）：

- ``lib_name``/``cell_name``（str，必填）——目标原理图库/cell；
- ``view_name``（str，可选缺省 "schematic"）；
- ``instances``（list[dict]，必填）——逐实例：lib/cell/name（实例名）/
  x,y（放置坐标数值）/view（可选缺省 "schematic"，master 读取视图）/
  rot（可选，如 "R90"/"MY"——经 inst~>orient 属性写入，缺省不写）；
- ``wires``（list[dict]，可选缺省 []）——逐连线 x1,y1,x2,y2（坐标数值）；
- ``seg_width``/``draw_radius``/``wire_type``（数值，可选缺省
  0.0625/0.0625/0——schCreateWire 结构旋钮缺省形态，非电路数值）；
- ``title``（str，可选）——文件头注释行。

函数名出处（#122 如实声明；发布版须对照本地 SKILL Language Reference
与 schematic 命令参考校准）：
``dbOpenCellViewByType``（master 用 "r" 只读打开）/ ``dbCreateInst
(cvId masterId point instName)``（旋转不在创建调用里，走 inst~>orient
属性赋值）/ ``schCreateWire(cvId "draw" "full" pointPairs segWidth
drawRadius wireType)``（点对为 list(list(x1:y1 x2:y2)) 形态——
segWidth/drawRadius/wireType 的版本相关缺省值发布版须核）/
``dbSave`` / ``dbClose``。
"""

from __future__ import annotations

from rfauto.core.skill_templates import SkillTemplateSpec, register_skill_template

SOURCE = """\
; {{title|default("schematic instances + wires (rfauto skill render)")}}
; 由 rfauto 模板+变量直出（零手拍电路数值）；函数名以本地 SKILL Language Reference 为准
let( (cv master inst)
  cv = dbOpenCellViewByType({{lib_name}} {{cell_name}} {{view_name|default("schematic")}} "a" "schematic")
{%for d in instances%}  master = dbOpenCellViewByType({{d.lib}} {{d.cell}} {{d.view|default("schematic")}} "r" "schematic")
  inst = dbCreateInst(cv master list({{d.x}}:{{d.y}}) {{d.name}})
{%if d.rot%}  inst~>orient = {{d.rot}}
{%endif%}{%endfor%}{%for w in wires|default([])%}  schCreateWire(cv "draw" "full" list(list({{w.x1}}:{{w.y1}} {{w.x2}}:{{w.y2}})) {{seg_width|default(0.0625)}} {{draw_radius|default(0.0625)}} {{wire_type|default(0)}})
{%endfor%}  dbSave(cv)
  dbClose(cv)
)
"""

register_skill_template(SkillTemplateSpec(
    name="schematic_instance",
    title="器件实例放置 + 连线（schematic 基本操作）",
    description=(
        "打开目标原理图 cellview，逐实例以只读方式开 master 后 "
        "dbCreateInst 放置（可选 inst~>orient 旋转），再按 wires 清单 "
        "schCreateWire 连线，收尾 dbSave+dbClose。"),
    category="schematic",
    source=SOURCE,
    default_vars={"wires": [], "seg_width": 0.0625, "draw_radius": 0.0625,
                  "wire_type": 0},
    functions=(
        "dbOpenCellViewByType", "dbCreateInst", "schCreateWire",
        "dbSave", "dbClose",
    ),
    example_vars={
        "lib_name": "myLib",
        "cell_name": "topCell",
        "instances": [
            {"lib": "analogLib", "cell": "res", "name": "R0",
             "x": 0.0, "y": 1.0, "rot": "R0"},
            {"lib": "analogLib", "cell": "cap", "name": "C0",
             "x": 2.0, "y": 1.0},
        ],
        "wires": [{"x1": 0.375, "y1": 1.0, "x2": 1.625, "y2": 1.0}],
    },
))
