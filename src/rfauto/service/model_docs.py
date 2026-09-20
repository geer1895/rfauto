"""模板文档自动化（P6+）—— pydantic schema 到 参数文档。

仿 gdsfactory：每个模板自动生成参数文档页。

扩展：除模型插件（pydantic schema）外，generate_all_model_docs 还覆盖
全部注册计算器（CALCULATOR_REGISTRY.names()）与全部 openEMS 模板
（TEMPLATE_META）。三类文档一次性生成，确定性（两次生成逐字节一致），
输出目录由调用方给定（单测走 tmp_path，不污染工作区）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# 文档键命名空间（generate_all_model_docs 返回 dict 的键 / 落盘文件名前缀）：
# 模型插件保持原名（向后兼容 CLI models docs），计算器/模板加前缀避免歧义。
CALCULATOR_DOC_PREFIX = "calc-"
TEMPLATE_DOC_PREFIX = "template-"

# 模板元数据必备字段：缺一即显式报错（不静默产出残缺文档）
TEMPLATE_REQUIRED_KEYS = ("f0_ghz", "n_ports", "params", "param_semantics")


def _write_doc(content: str, doc_key: str, output_dir: str | Path | None) -> None:
    """写文档到 output_dir/<doc_key>.md；output_dir 为空只返回内容不落盘。"""
    if not output_dir:
        return
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{doc_key}.md").write_text(content, encoding="utf-8")


def generate_model_docs(model_name: str, output_dir: str | Path | None = None) -> str:
    """为指定模型生成参数文档。"""
    from rfauto.models.registry import get as get_plugin_cls

    plugin_cls = get_plugin_cls(model_name)
    schema = plugin_cls.params_model.model_json_schema()

    lines = []
    lines.append(f"# {model_name} 参数文档")
    lines.append("")
    lines.append(f"**Schema 版本**: {plugin_cls.schema_version}")
    lines.append("")
    lines.append("## 参数列表")
    lines.append("")
    lines.append("| 参数名 | 类型 | 默认值 | 范围 | 说明 |")
    lines.append("|--------|------|--------|------|------|")

    properties = schema.get("properties", {})
    for param_name, param_info in properties.items():
        param_type = param_info.get("type", "any")
        default = param_info.get("default", "-")
        description = param_info.get("description", "")
        ge = param_info.get("minimum")
        le = param_info.get("maximum")
        range_str = ""
        # 边界判断用 is not None：ge=0 是常见约束但为假值，真值判断会丢弃下界 0
        # （C5 修复：原先 `if ge and le` 导致 minimum=0 的范围列整个为空）
        if ge is not None and le is not None:
            range_str = f"[{ge}, {le}]"
        elif ge is not None:
            range_str = f">= {ge}"
        elif le is not None:
            range_str = f"<= {le}"
        lines.append(f"| {param_name} | {param_type} | {default} | {range_str} | {description} |")

    lines.append("")
    lines.append("## JSON Schema")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(schema, indent=2, ensure_ascii=False))
    lines.append("```")
    lines.append("")

    doc_content = "\n".join(lines)
    _write_doc(doc_content, model_name, output_dir)
    return doc_content


# ─── 计算器文档（CALCULATOR_REGISTRY 全键覆盖）─────────────────────────

def generate_calculator_docs(
    calculator_name: str, output_dir: str | Path | None = None
) -> str:
    """为指定已注册计算器生成参数文档；未注册名抛 KeyError（显式，不静默）。

    实验态键（experimental=True）照常生成文档，但元数据里带实验标签——
    文档可见可审计，运行仍需 calculators.allow_experimental 开关。
    """
    from rfauto.core.calculators import CALCULATOR_REGISTRY

    spec = CALCULATOR_REGISTRY.get(calculator_name)

    lines = [
        f"# 计算器 {spec.name} 参数文档",
        "",
        spec.description,
        "",
        "## 参数",
        "",
        "| 参数名 | 必填 | 类型/单位/说明 |",
        "|--------|------|----------------|",
    ]
    for param_name, param_desc in spec.params:
        required = "是" if param_name in spec.required else ""
        lines.append(f"| {param_name} | {required} | {param_desc} |")
    lines += [
        "",
        "## 元数据",
        "",
        f"- 名称: {spec.name}",
        f"- 参数数: {len(spec.params)}",
        f"- 必填参数: {', '.join(spec.required) if spec.required else '-'}",
        f"- 实验性: {'是（experimental，默认关闭，运行需 calculators.allow_experimental 开关）' if spec.experimental else '否'}",
        "",
    ]
    doc_content = "\n".join(lines)
    _write_doc(doc_content, f"{CALCULATOR_DOC_PREFIX}{spec.name}", output_dir)
    return doc_content


# ─── 模板文档（TEMPLATE_META 全键覆盖）─────────────────────────────────

# param_semantics 自由文本按 "name=含义（到下一个分隔符）" 抽取；只搬运声明，
# 不产生任何新数值。前缀用负向后顾避免 w_mm 误匹配 series_w_mm。
_SEMANTICS_ENTRY = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z0-9_]+)\s*=\s*([^，,；;]+)")


def _param_semantics_map(text: str) -> dict[str, str]:
    """把 param_semantics 自由文本解析为 {参数名: 语义}（抽取失败即缺省空串）。"""
    return {
        match.group(1): match.group(2).strip()
        for match in _SEMANTICS_ENTRY.finditer(text)
    }


def generate_template_docs(
    template_name: str, output_dir: str | Path | None = None
) -> str:
    """为指定 openEMS 模板生成参数文档。

    未注册模板抛 KeyError；元数据缺必备字段抛 ValueError（显式报错，
    不产出残缺文档）。
    """
    from rfauto.adapters.openems_templates import TEMPLATE_META

    if template_name not in TEMPLATE_META:
        raise KeyError(
            f"未注册的模板: {template_name}（可用: {sorted(TEMPLATE_META)}）")
    meta: dict[str, Any] = TEMPLATE_META[template_name]
    missing = [key for key in TEMPLATE_REQUIRED_KEYS if key not in meta]
    if missing:
        raise ValueError(f"模板 {template_name} 元数据缺关键字段: {missing}")

    semantics = _param_semantics_map(str(meta.get("param_semantics", "")))
    params = list(meta.get("params") or [])
    lines = [
        f"# 模板 {template_name} 参数文档",
        "",
        f"**中心频率**: {meta['f0_ghz']} GHz",
        "",
        f"**端口数**: {meta['n_ports']}",
        "",
        "## 参数语义",
        "",
        "| 参数名 | 语义 |",
        "|--------|------|",
    ]
    for param_name in params:
        lines.append(f"| {param_name} | {semantics.get(param_name, '')} |")
    if not params:
        lines.append("| - | - |")
    lines += [
        "",
        "## 提取与拓扑",
        "",
        f"- 提取点: {meta.get('extraction', '')}",
        f"- 拓扑: {meta.get('topology', '')}",
        f"- 网格说明: {meta.get('mesh_note', '')}",
        "",
        "## 元数据（全量）",
        "",
        "```json",
        json.dumps(meta, indent=2, ensure_ascii=False, default=str),
        "```",
        "",
    ]
    doc_content = "\n".join(lines)
    _write_doc(doc_content, f"{TEMPLATE_DOC_PREFIX}{template_name}", output_dir)
    return doc_content


def generate_all_model_docs(output_dir: str | Path = "docs/models") -> dict[str, str]:
    """为全部已注册模型 + 全部注册计算器 + 全部 openEMS 模板生成文档。

    计算器覆盖含实验态键（experimental=True，文档内带实验标签）。

    返回 dict[文档键, Markdown 内容]：
    - 模型插件：键 = 模型名（历史语义，CLI models docs 依赖）；
    - 计算器：键 = calc-<name>；
    - 模板：键 = template-<name>。
    计算器/模板严格生成（任一缺失/坏输入即抛错）；模型插件保持历史容错语义
    （失败以 "Error: ..." 落值，不中断其余文档）。
    """
    from rfauto.adapters.openems_templates import TEMPLATE_META
    from rfauto.core.calculators import CALCULATOR_REGISTRY
    from rfauto.models.registry import list_models

    results: dict[str, str] = {}
    for model_name in list_models():
        try:
            results[model_name] = generate_model_docs(model_name, output_dir)
        except Exception as e:
            results[model_name] = f"Error: {e}"

    for calculator_name in CALCULATOR_REGISTRY.names(include_experimental=True):
        key = f"{CALCULATOR_DOC_PREFIX}{calculator_name}"
        results[key] = generate_calculator_docs(calculator_name, output_dir)

    for template_name in sorted(TEMPLATE_META):
        key = f"{TEMPLATE_DOC_PREFIX}{template_name}"
        results[key] = generate_template_docs(template_name, output_dir)

    missing = [
        f"{CALCULATOR_DOC_PREFIX}{name}"
        for name in CALCULATOR_REGISTRY.names(include_experimental=True)
        if f"{CALCULATOR_DOC_PREFIX}{name}" not in results
    ] + [
        f"{TEMPLATE_DOC_PREFIX}{name}"
        for name in TEMPLATE_META
        if f"{TEMPLATE_DOC_PREFIX}{name}" not in results
    ]
    if missing:
        raise RuntimeError(f"文档覆盖不完整，缺: {missing}")
    return results
