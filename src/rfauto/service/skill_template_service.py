"""SKILL 模板服务面（T-Q27 席 Q-X32，aurora_q CAD 大扩展）。

模板生成四函数 JSON 信封进出（规则 4：CLI ``rfauto skill render/lint/list``
与未来 MCP 工具同源同名 service 函数；零 Virtuoso 依赖零真机调用——生成
是纯 Python 字符串操作，执行侧在用户本地 Virtuoso）：

- :func:`list_skill_templates`` → 5 模板目录（注册表只读视图，sorted）；
- :func:`render_skill_template`` → 模板+变量 → SKILL 代码（含 lint 守卫、
  sha256、可选落盘）；
- :func:`lint_skill_code`` → SKILL 语法守卫（括号/引号/let 绑定/函数名
  白名单/赋值目标/残留标签）；
- :func:`save_skill_file`` → 磁盘写出（防覆盖守卫+sha256）。

信封契约（service/envelope 构造器单源，#105：错误文案带指引不抛裸异常；
新代码禁止裸 dict 信封）：

- ``list_skill_templates`` ok：``{templates, count}``；
- ``render_skill_template`` ok：``{template, title, category, vars_echo,
  skill_code, sha256, lint, file_path?, bytes?}``——lint 有 error 级
  issue 时 ok=False 但 skill_code/lint 仍附带（fail-loud 不吞产物）；
- ``lint_skill_code``：``{ok, issues, n_errors, n_warnings}``（ok=调用
  成立恒 True；代码健康度读 n_errors——warning 级 unknown_function
  不入 error，见引擎 docstring 分级口径）；
- ``save_skill_file`` ok：``{path, sha256, bytes}``。

确定性：同 (模板, 变量) 两跑 skill_code 逐字节同（内核纯函数单源；
sha256 为渲染字节摘要）；落盘走 ``write_bytes``（零平台换行翻译），
信封 sha256 == 盘上文件字节 sha256。

变量合并口径：``spec.default_vars``（模板可选旋钮单源）先合，
调用方变量后合覆盖；未知键（模板不消费）记 lint 外的 ``unknown_vars``
warning 字段不翻 ok（调用方拼写自检面）；必填缺失由内核 fail-loud
转 error 信封（文案带 required 清单指引）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from rfauto.core.skill_template_engine import (
    SkillTemplateError,
    render_template,
    skill_lint_issues,
)
from rfauto.core.skill_templates import (
    SkillTemplateSpec,
    get_skill_template,
    list_skill_template_specs,
)
from rfauto.service.envelope import error_envelope, ok_envelope

__all__ = [
    "lint_skill_code",
    "list_skill_templates",
    "render_skill_template",
    "save_skill_file",
]


def _spec_row(spec: SkillTemplateSpec) -> dict[str, Any]:
    """注册表只读视图行（list 信封元素单源）。"""
    return {
        "name": spec.name,
        "title": spec.title,
        "description": spec.description,
        "category": spec.category,
        "required_vars": list(spec.required_vars),
        "optional_vars": list(spec.optional_vars),
        "default_vars": dict(spec.default_vars),
        "functions": list(spec.functions),
    }


def list_skill_templates() -> dict[str, Any]:
    """模板目录（sorted；注册表只读视图零副作用）。"""
    rows = [_spec_row(s) for s in list_skill_template_specs()]
    return ok_envelope(templates=rows, count=len(rows))


def lint_skill_code(code: str) -> dict[str, Any]:
    """SKILL 语法守卫信封：{ok, issues, n_errors, n_warnings}。

    ``ok`` =调用成立（lint 本身零异常恒 True）；**代码健康度**读
    n_errors/n_warnings——ok=False 语义保留给调用失败（#122 测量与
    报告语义分层；CI 退出码由 CLI 按 n_errors 裁定）。
    """
    issues = skill_lint_issues(code)
    n_errors = sum(1 for i in issues if i["severity"] == "error")
    n_warnings = sum(1 for i in issues if i["severity"] == "warning")
    return ok_envelope(issues=issues, n_errors=n_errors,
                       n_warnings=n_warnings)


def save_skill_file(code: str, path: str | Path, *,
                    overwrite: bool = False) -> dict[str, Any]:
    """SKILL 文件落盘（父目录自动创建；已存在且未 --force 即报错）。

    写出走 ``write_bytes``+UTF-8+``\\n`` 换行（零平台翻译——确定性），
    信封 sha256 == 盘上字节 sha256。
    """
    target = Path(path)
    if target.exists() and not overwrite:
        return error_envelope(
            [f"目标已存在（防覆盖；--force 覆写）: {target}"])
    parent = target.parent
    try:
        if str(parent):
            parent.mkdir(parents=True, exist_ok=True)
        data = code.encode("utf-8")
        target.write_bytes(data)
    except OSError as exc:
        return error_envelope([f"落盘失败: {target}（{exc}）"])
    return ok_envelope(path=str(target), sha256=hashlib.sha256(data).hexdigest(),
                       bytes=len(data))


def render_skill_template(template_name: str,
                          variables: dict[str, Any] | None = None,
                          *,
                          out_path: str | Path | None = None,
                          overwrite: bool = False) -> dict[str, Any]:
    """模板+变量 → SKILL 代码信封（渲染→lint→可选落盘；同入参两跑
    skill_code 逐字节同）。

    失败信封形态：未知模板/渲染异常/必填变量缺失 → ok=False（errors
    带指引）；lint 有 error 级 issue → ok=False 且 skill_code/lint 附带
    （产物可见不吞）。``out_path`` 给定时追加落盘（防覆盖守卫同
    :func:`save_skill_file`）。
    """
    caller_vars = dict(variables or {})
    try:
        spec = get_skill_template(template_name)
    except SkillTemplateError as exc:
        return error_envelope([str(exc)])
    merged: dict[str, Any] = {**spec.default_vars, **caller_vars}
    unknown = sorted(k for k in caller_vars
                     if k not in spec.required_vars
                     and k not in spec.optional_vars)
    try:
        code = render_template(spec.source, merged)
    except SkillTemplateError as exc:
        return error_envelope([
            f"模板渲染失败: {exc}",
            f"必填变量: {list(spec.required_vars)}；可选变量: "
            f"{list(spec.optional_vars)}（optional 可经模板缺省/服务 "
            f"default_vars 兜底）",
        ])
    lint = lint_skill_code(code)
    data = code.encode("utf-8")
    result = ok_envelope(
        template=spec.name,
        title=spec.title,
        category=spec.category,
        vars_echo=merged,
        skill_code=code,
        sha256=hashlib.sha256(data).hexdigest(),
        lint={k: lint[k] for k in ("issues", "n_errors", "n_warnings")},
        unknown_vars=unknown,
    )
    if unknown:
        result["warnings"] = [
            f"调用方变量模板不消费: {unknown}（拼写自检；模板变量面见 "
            "required_vars/optional_vars）"]
    if lint["n_errors"] > 0:
        result["ok"] = False
        result["errors"] = [
            f"渲染产物未过语法守卫（{lint['n_errors']} error）——"
            "issues 见 lint 字段（fail-loud 不吞产物）"]
    if out_path is not None:
        saved = save_skill_file(code, out_path, overwrite=overwrite)
        if not saved.get("ok"):
            saved.update({"skill_code": code, "sha256": result["sha256"]})
            return saved
        result["file_path"] = saved["path"]
        result["bytes"] = saved["bytes"]
    return result
