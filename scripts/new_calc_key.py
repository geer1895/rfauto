#!/usr/bin/env python
"""new_calc_key：新增 CALC 键脚手架生成器（R1 T6 配套 DX，aurora_g W8-S3）。

背景：新增一个 CALC 键需同步 6+ 消费者（内核立规注记 坑账 #231/#304 两次实证
"只跑本项定向绿、合流全量必红"），清单此前只活在坑账文本。本生成器把
清单工具化：输入键名/组名/模块名 → 输出①内核模块骨架（可直接落盘）
+②"五步"消费者钉清单（含可粘贴代码片段与自证命令）。

DX 增强（aurora_g W15-S3）：``--emit-templates DIR`` 把五钉消费者文件
的**可粘贴补丁模板**逐钉落成文件（锚点+代码块+自证命令），比清单文本
更进一步——执行者不再手抄代码块，逐文件对照锚点粘贴即可::

    python scripts/new_calc_key.py my_new_key ... \
        --emit-templates runs/new_calc_key_templates_my_new_key

设计红线：
- **只生成不改**：本工具绝不自动编辑 src/tests 任何文件（消费者文件是
  并行合流热区；五钉由人按模板执行）——``--out`` 只写新骨架文件且拒绝
  覆盖已存在文件；``--emit-templates`` 只写模板文件且拒绝落进 src/tests
  消费者树（会话一次性产物按工作区纪律落 runs/）；
- **零物理数字**（铁律 7）：骨架只含签名/参数描述/结构，不产出任何
  物理数值——数值一律由实现者用闭式/文献口径填入并给出处注记；
- 骨架风格对齐 calc_families 现行惯例（kqe.py 族：``from __future__
  import annotations`` + ``@register_calculator`` 装饰器 + 确定性纯函数）。

退出码：0=生成成功；2=用法/校验错误（键名/参数名非法、--out 已存在、
--emit-templates 越界）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CALC_FAMILIES_DIR = REPO_ROOT / "src" / "rfauto" / "core" / "calc_families"

_IDENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")
"""键/模块/参数名统一 snake_case 标识符口径（注册表键全是小写下划线）。"""

_SNAKE_WORDS_RE = re.compile(r"^[a-z0-9_]+$")

_FIVE_STEPS_HEADER = """\
════════════════════════════════════════════════════════════════════
新增 CALC 键「五步」清单（#231/#304 消费者税工具化；按序执行后跑自证门）
════════════════════════════════════════════════════════════════════
"""

_FIVE_STEPS_FOOTER = """\
────────────────────────────────────────────────────────────────────
自证门（返回合流前必跑；对应 merge_preflight 面19/面20）::

    .venv/Scripts/python.exe -m pytest tests/unit/test_calculators.py \\
tests/unit/test_physics_invariants.py tests/unit/test_experimental_\\
calculators.py tests/unit/test_model_docs.py -q

提示：test_model_docs 与 test_experimental_calculators 为注册表驱动/
单源计数——骨架正确时零改动自动过；模板类键另跑
test_template_meta_consistency + test_template_geometry_audit。
五钉消费者文件的可粘贴补丁模板可用 --emit-templates <dir> 逐钉落盘
（锚点+代码块+自证命令；建议 runs/new_calc_key_templates_<key>/）。
"""


def _check_ident(name: str, what: str) -> str:
    if not _IDENT_RE.match(name):
        raise SystemExit(
            f"错误：{what} {name!r} 须为 snake_case 标识符"
            "（小写字母开头，仅小写字母/数字/下划线）")
    return name


def _parse_params(specs: list[str]) -> list[tuple[str, str]]:
    """--param 名:描述 列表 → (名, 描述) 元组表（保持命令行给出序）。"""
    out: list[tuple[str, str]] = []
    for spec in specs:
        name, _sep, desc = spec.partition(":")
        _check_ident(name.strip(), "参数名")
        if not desc.strip():
            raise SystemExit(f"错误：参数 {name!r} 缺描述（格式 名:描述）")
        out.append((name.strip(), desc.strip()))
    return out


def build_module_skeleton(
    key: str,
    *,
    module: str,
    description: str,
    params: list[tuple[str, str]],
    required: list[str],
    group: str,
    experimental: bool,
) -> str:
    """内核模块骨架文本（风格对齐 calc_families 现行惯例）。"""
    unknown = sorted(set(required) - {p for p, _ in params})
    if unknown:
        raise SystemExit(
            f"错误：--required 引用了未声明的参数: {', '.join(unknown)}")
    param_lines = "\n".join(
        f'        ("{name}", "{desc}"),' for name, desc in params)
    required_arg = ""
    if required:
        required_arg = ("\n    required=("
                        + ", ".join(f'"{r}"' for r in required) + ",),")
    exp_arg = "\n    experimental=True," if experimental else ""
    group_arg = ""
    if group:
        group_arg = f'\n    group="{group}",'
    if params:
        func_args = ("(\n"
                     + "\n".join(f"    {name}: float," for name, _ in params)
                     + "\n) -> dict[str, Any]:")
    else:
        func_args = "(**_kwargs: float) -> dict[str, Any]:"
    return f'''\"""{module}：{description}（骨架由 scripts/new_calc_key.py 生成）。

数值出处纪律（铁律 7 + #118）：函数体只允许确定性闭式/文献公式——
每个常数必须带出处注记（文献/标准条款/仓内锚 run 路径），禁止
"调出来的"无出处魔法数；越域输入显式 ValueError 拒绝，禁止外推。
"""

from __future__ import annotations

from typing import Any

from .registry import register_calculator


@register_calculator(
    name="{key}",
    description="{description}",
    params=(
{param_lines}
    ),{required_arg}{exp_arg}{group_arg}
)
def {key}{func_args}
    """{description}（确定性纯函数：同输入同输出，可复现性红线）。

    TODO(实现者)：填入闭式实现与常数出处；本骨架不产出物理数字。
    """
    raise NotImplementedError("骨架未实现：按模块 docstring 出处纪律填入")
'''


def build_checklist(
    key: str,
    *,
    module: str,
    group: str,
    experimental: bool,
    params: list[tuple[str, str]],
    required: list[str],
) -> str:
    """五步清单文本（含可粘贴片段与自证命令）。"""
    expected_table = ("EXPERIMENTAL_EXPECTED" if experimental else "EXPECTED")
    input_row = ", ".join(f'"{p}": 0.0  # TODO 确定性合法输入'
                          for p, _ in params) or 'pass  # 无参数键'
    required_note = ""
    if required:
        required_note = ("；required=(" + ", ".join(
            f'"{r}"' for r in required) + ") 的缺参路径另补显式报错用例")
    steps = _FIVE_STEPS_HEADER + f"""\
键：{key}   模块：src/rfauto/core/calc_families/{module}.py
分组：{group or "（未指定→落 DEFAULT_CALC_GROUP=其他）"}   \
experimental：{str(experimental).lower()}

第 1 步 · 内核骨架落位
    --out 未指定时把上面骨架文本手工落到
    src/rfauto/core/calc_families/{module}.py（已存在则并入该模块，
    勿覆盖既有键）；实现闭式并逐常数给出处注记。

第 2 步 · 注册副作用挂入聚合面（注册序=导入序，#T7 口径）
    src/rfauto/core/calc_families/__init__.py **追加尾位**：

        from . import {module}  # noqa: F401  # 注册副作用（追加尾位）

    禁止字母重排既有行——插入序漂移会打红注册序/金快照类消费者。

第 3 步 · 键集EXPECTED 表补键
    tests/unit/test_calculators.py → {expected_table} 集合加：

        "{key}",   # TODO 一行出处/语义注记

第 4 步 · 物理不变量输入表补行
    tests/unit/test_physics_invariants.py → _calculator_inputs() 返回
    dict 加（值必须确定性合法、物理 sane）：

        "{key}": {{
            {input_row}
        }},
{required_note}

第 5 步 · 分组单源表补行（显式 group= 注册的可跳过）
    src/rfauto/core/calc_families/registry.py → CALC_GROUP_TABLE 加：

        "{key}": "{group or '其他'}",

自动覆盖面（零改动，跑绿即可，勿手工加表）：
    - test_model_docs：注册表驱动逐键出文档，注册即覆盖；
    - test_experimental_calculators：实验键计数单源取 EXPECTED 表；
    - test_physics_invariants §1 参数化列表直接取注册表，缺第 4 步
      输入行会以明确报错指路。
"""
    return steps + _FIVE_STEPS_FOOTER


def build_consumer_templates(
    key: str,
    *,
    module: str,
    group: str,
    experimental: bool,
    params: list[tuple[str, str]],
    required: list[str],
) -> dict[str, str]:
    """五钉消费者文件的可粘贴补丁模板（W15-S3 DX 增强）。

    每钉一份模板文件：目标文件+锚点+插入代码块+自证命令。代码块与
    build_checklist 同源同语义——本函数只做"逐钉落盘"的载体，不产生
    新口径。返回 {文件名: 内容}（有序，01→05 即执行序）。
    """
    expected_table = ("EXPERIMENTAL_EXPECTED" if experimental else "EXPECTED")
    input_row = ",\n".join(
        f'            "{p}": 0.0,  # TODO 确定性合法输入（物理 sane）'
        for p, _ in params) or "            pass  # 无参数键：传空 dict 即可"
    required_note = ""
    if required:
        required_note = (
            "\n另：required=(" + ", ".join(f'"{r}"' for r in required)
            + ") 的缺参路径需在该键的定向用例补一条显式报错断言"
              "（ValueError 文案含缺参名）。")
    group_row = group or "其他"

    tpl01 = f"""\
01 · 注册副作用聚合行（第 2 步载体）
目标文件: src/rfauto/core/calc_families/__init__.py
锚点: 文件末尾（既有 from . import ... 注册副作用行块的最后一行之后）
操作: 追加一行（保持文件内既有行序，禁止插入中间或重排——插入序漂移
会打红注册序/金快照类消费者）：

    from . import {module}  # noqa: F401  # 注册副作用（追加尾位）

自证: .venv/Scripts/python.exe -m pytest tests/unit/test_calculators.py -q
"""

    tpl02 = f"""\
02 · 键集 EXPECTED 表（#231 钉①）
目标文件: tests/unit/test_calculators.py
锚点: {expected_table} = {{ 集合字面量的收尾 }} 之前（末个键行之后）
操作: 追加一行键字符串（带一行出处/语义注记，与既有键行风格一致）：

    "{key}",   # TODO 一行出处/语义注记（文献/标准条款/锚 run 路径）

注：本键为 {'实验键（names()/describe() 缺省排除）' if experimental else '常规键'}，
落 {expected_table} 表。
自证: .venv/Scripts/python.exe -m pytest tests/unit/test_calculators.py -q
"""

    tpl03 = f"""\
03 · 物理不变量输入表（#231 钉②）
目标文件: tests/unit/test_physics_invariants.py
锚点: _calculator_inputs() 返回 dict 字面量的收尾 }} 之前（末个键条目之后）
操作: 追加条目（0.0 为占位——必须改成确定性合法且物理 sane 的输入值；
越域值会让不变量断言以物理失败的方式打红，不是脚手架问题）：

    "{key}": {{
{input_row}
    }},
{required_note}
自证: .venv/Scripts/python.exe -m pytest tests/unit/test_physics_invariants.py -q
（缺本行时该测试以"注册键未在 G15 输入表声明"明确报错指路）
"""

    tpl04 = f"""\
04 · 分组单源表（#231 钉⑤；显式 group= 注册的可跳过本钉）
目标文件: src/rfauto/core/calc_families/registry.py
锚点: CALC_GROUP_TABLE: dict[str, str] = {{ 字面量内对应分组注释块下
操作: 追加键行（缺省组落 DEFAULT_CALC_GROUP=其他）：

    "{key}": "{group_row}",

自证: .venv/Scripts/python.exe -m pytest tests/unit/test_calculators.py -q
"""

    tpl05 = """\
05 · 模板类钉与自动覆盖面（#231 钉③④ + 模板一致性族）

A. 模板类键才需要（键名随新模板族伴生，如 <tmpl>_synthesis）；
   纯内核键跳过本钉：
   - tests/unit/test_template_meta_consistency.py：TEMPLATE_META 条目
     补键时同步 docs/templates/<t>/meta.yaml nominal_params（三处条目
     集一致钉：TEMPLATE_META/TEMPLATE_NOMINAL/meta.yaml）；
   - tests/unit/test_template_geometry_audit.py：EXPECTED_TEMPLATES
     frozenset 补条目 + len(EXPECTED_TEMPLATES)==N 字面计数 +1。

B. 自动覆盖面（零改动，跑绿即可，勿手工加表）：
   - test_model_docs：注册表驱动逐键出文档，注册即覆盖；
   - test_experimental_calculators：实验键计数单源取 EXPECTED 表。

自证: .venv/Scripts/python.exe -m pytest tests/unit/test_model_docs.py \\
tests/unit/test_experimental_calculators.py -q
模板类键加跑: tests/unit/test_template_meta_consistency.py \\
tests/unit/test_template_geometry_audit.py -q
"""
    return {
        "01_calc_families_init_import.py.template": tpl01,
        "02_test_calculators_EXPECTED.py.template": tpl02,
        "03_test_physics_invariants_inputs.py.template": tpl03,
        "04_registry_CALC_GROUP_TABLE.py.template": tpl04,
        "05_template_consumers_and_auto.md.template": tpl05,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="新增 CALC 键脚手架生成器：输出内核骨架+五步消费者"
                    "钉清单（只生成不改消费者文件）")
    parser.add_argument("key", help="新 CALC 键名（snake_case）")
    parser.add_argument("--module", required=True,
                        help="落位模块名（calc_families/<module>.py）")
    parser.add_argument("--description", required=True,
                        help="一行物理语义说明（入注册表 description）")
    parser.add_argument("--group", default="",
                        help="工具箱分组名（入 CALC_GROUP_TABLE；缺省落其他）")
    parser.add_argument("--param", action="append", default=[],
                        metavar="NAME:DESC",
                        help="参数声明（名:描述），可重复")
    parser.add_argument("--required", nargs="*", default=[],
                        help="必填参数名子集")
    parser.add_argument("--experimental", action="store_true",
                        help="实验键口径（names()/describe() 默认排除，"
                             "EXPECTED 进 EXPERIMENTAL_EXPECTED）")
    parser.add_argument("--out", default="",
                        help="骨架落盘路径（缺省只打印 stdout；已存在"
                             "文件拒绝覆盖）")
    parser.add_argument("--emit-templates", default="", metavar="DIR",
                        help="五钉消费者补丁模板落盘目录（01→05 每钉一"
                             "份：锚点+代码块+自证；拒绝覆盖既有模板文"
                             "件、拒绝落 src/tests 消费者树；建议 "
                             "runs/new_calc_key_templates_<key>/）")
    args = parser.parse_args(argv)

    key = _check_ident(args.key, "键名")
    module = _check_ident(args.module, "模块名")
    params = _parse_params(args.param)
    required = [_check_ident(r, "必填参数名") for r in args.required]

    skeleton = build_module_skeleton(
        key, module=module, description=args.description, params=params,
        required=required, group=args.group,
        experimental=args.experimental)
    print(skeleton)
    print(build_checklist(
        key, module=module, group=args.group,
        experimental=args.experimental, params=params, required=required))

    if args.out:
        out = Path(args.out)
        if out.exists():
            raise SystemExit(
                f"错误：--out 目标已存在（拒绝覆盖）: {out}")
        if out.resolve().parent != CALC_FAMILIES_DIR.resolve():
            raise SystemExit(
                f"错误：--out 只允许落 {CALC_FAMILIES_DIR}（骨架非注册"
                "文件，落别处不会被 import 副作用注册）")
        out.write_text(skeleton, encoding="utf-8", newline="\n")
        print(f"[new_calc_key] 骨架已写入: {out}")

    if args.emit_templates:
        templates_dir = Path(args.emit_templates)
        resolved = templates_dir.resolve()
        # 只生成不改红线：模板不得落进消费者树（src/、tests/）
        for forbidden in (REPO_ROOT / "src", REPO_ROOT / "tests"):
            forbidden_resolved = forbidden.resolve()
            if (resolved == forbidden_resolved
                    or resolved.is_relative_to(forbidden_resolved)):
                raise SystemExit(
                    f"错误：--emit-templates 目录不得落在消费者树内: "
                    f"{forbidden}（模板只生成不改，五钉由人按模板执行；"
                    "会话一次性产物按工作区纪律落 runs/）")
        templates_dir.mkdir(parents=True, exist_ok=True)
        templates = build_consumer_templates(
            key, module=module, group=args.group,
            experimental=args.experimental, params=params, required=required)
        targets = [templates_dir / fname for fname in templates]
        clashes = [t for t in targets if t.exists()]
        if clashes:
            raise SystemExit(
                "错误：模板文件已存在（拒绝覆盖）: "
                + "; ".join(str(t) for t in clashes))
        for target, content in zip(targets, templates.values(), strict=True):
            target.write_text(content, encoding="utf-8", newline="\n")
        print(f"[new_calc_key] 五钉消费者模板已写入: {templates_dir}"
              f"（{len(templates)} 份，01→05=执行序）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
