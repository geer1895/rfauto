"""SKILL 电路设计模板注册表（T-Q27 席 Q-X32，aurora_q CAD 大扩展）。

5 个即用电路设计模板（Virtuoso-Bridge-lite 核心模式借鉴化用——Python 侧
模板化生成 SKILL 代码字符串，输出 .il 供用户在本地 Virtuoso 加载执行，
零 Cadence 依赖零真机调用）：cell_layout / schematic_instance /
aedt_run_simulation / waveform_export / layer_setup。

注册表模式（#3 家法）：模块级 ``register_skill_template`` 装饰器注册 +
``SKILL_TEMPLATES`` dict 单源；新增模板=新模块+装饰器+本包 ``__init__``
导入一行（消费者测试清单见 tests/unit/test_skill_template_engine.py
test_registry_consumers 一节）。

出处声明（#1c 对照官方例 + #122 如实口径）：模板生成的函数名面是 Cadence
SKILL/OCEAN/ADE XL 文档中的常用惯例形态（dbOpenCellViewByType/dbCreateRect/
dbCreatePath/dbCreateLabel/dbCreateInst/schCreateWire/techGetTechFile/
ocnxlRun/ocnxlOutputSummaryCSV/ocnPrint 等）——本仓无 Virtuoso 安装，
各模板 docstring 逐函数声明参数形态依据与发布版校准点；生成文件头注释
同样带"以本地 SKILL Language Reference 为准"提示。模板值零物理数字
（铁律 7：默认参数只收结构旋钮如精度/宽度/视图名，几何与电路值全部
来自调用方变量）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rfauto.core.skill_template_engine import (
    SkillTemplateError,
    list_template_var_info,
)

__all__ = [
    "SKILL_TEMPLATES",
    "SKILL_TEMPLATE_CATEGORIES",
    "SkillTemplateSpec",
    "get_skill_template",
    "list_skill_template_names",
    "list_skill_template_specs",
    "register_skill_template",
]

#: 注册表（name → spec；注册序无关，读取面一律 sorted——确定性）
SKILL_TEMPLATES: dict[str, SkillTemplateSpec] = {}

#: 模板分类词表（单源；list 输出面按此分组）
SKILL_TEMPLATE_CATEGORIES = ("layout", "schematic", "simulation", "postproc",
                             "techfile")


@dataclass(frozen=True)
class SkillTemplateSpec:
    """模板规格（frozen——注册后零漂移）。"""

    name: str
    title: str
    description: str
    category: str
    source: str
    #: 引擎变量盘点（注册时冻结——required/optional 两列）
    required_vars: tuple[str, ...] = field(default=())
    optional_vars: tuple[str, ...] = field(default=())
    #: 服务层缺省变量（合并进调用方变量之前；可选旋钮的单源声明处）
    default_vars: dict[str, Any] = field(default_factory=dict)
    #: 生成面函数名（lint 白名单自查 + list 面展示）
    functions: tuple[str, ...] = field(default=())
    example_vars: dict[str, Any] = field(default_factory=dict)


def register_skill_template(spec: SkillTemplateSpec) -> SkillTemplateSpec:
    """注册模板（重名即 raise——fail-loud 防静默遮蔽）。"""
    if spec.name in SKILL_TEMPLATES:
        raise SkillTemplateError(f"SKILL 模板重名注册: {spec.name}")
    if spec.category not in SKILL_TEMPLATE_CATEGORIES:
        raise SkillTemplateError(
            f"模板 {spec.name} 分类 {spec.category!r} 不在词表 "
            f"{SKILL_TEMPLATE_CATEGORIES}")
    info = list_template_var_info(spec.source)
    object.__setattr__(spec, "required_vars",
                       tuple(info["required"]))
    object.__setattr__(spec, "optional_vars",
                       tuple(info["optional"]))
    SKILL_TEMPLATES[spec.name] = spec
    return spec


def get_skill_template(name: str) -> SkillTemplateSpec:
    """按名取模板（未知名 raise——错误文案附可用清单）。"""
    spec = SKILL_TEMPLATES.get(name)
    if spec is None:
        raise SkillTemplateError(
            f"未知 SKILL 模板 {name!r}（可用：{list_skill_template_names()}）")
    return spec


def list_skill_template_names() -> list[str]:
    """注册表键清单（sorted——确定性）。"""
    return sorted(SKILL_TEMPLATES)


def list_skill_template_specs() -> list[SkillTemplateSpec]:
    """规格清单（按 name sorted——确定性）。"""
    return [SKILL_TEMPLATES[n] for n in list_skill_template_names()]


# ── 模板模块导入（导入即注册；新增模板在此追加一行） ──────────────

from rfauto.core.skill_templates import aedt_run_simulation as _aedt  # noqa: E402,F401
from rfauto.core.skill_templates import cell_layout as _cell_layout  # noqa: E402,F401
from rfauto.core.skill_templates import layer_setup as _layer_setup  # noqa: E402,F401
from rfauto.core.skill_templates import schematic_instance as _schematic  # noqa: E402,F401
from rfauto.core.skill_templates import waveform_export as _waveform  # noqa: E402,F401
