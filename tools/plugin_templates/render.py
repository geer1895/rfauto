"""cookiecutter 占位符渲染器（最小替代；docs/plugins.md 快速开始引用）。

cookiecutter 不在本 venv（#222 实测）——本模块用最小 ``{{ cookiecutter.x }}``
占位符替换达成同效渲染（同名文件/目录占位一并替换；cookiecutter.json
交叉引用有界迭代收敛）。与 tests/unit/test_plugin_templates.py 内嵌渲染器
同语义；真实 cookiecutter 行为以官方工具为准。

用法（仓根执行）::

    python -m tools.plugin_templates.render template_family
    python -m tools.plugin_templates.render metric_benchmark --out ./out \
        --set bench_name=my_bench
    python -m tools.plugin_templates.render --list
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_TOOLS_ROOT = Path(__file__).resolve().parent
_MAX_RESOLVE_ROUNDS = 4


def _render_text(text: str, ctx: dict[str, str]) -> str:
    # 占位符形态两枚：带空格 "{{ cookiecutter.key }}" 与紧凑
    # "{{cookiecutter.key}}"——字符串拼接构造（不走 f-string 花括号转义，
    # 写入面曾把空格挪进插值内静默变形，#102 家族）
    for key, value in ctx.items():
        text = text.replace("{{ cookiecutter." + key + " }}", str(value))
        text = text.replace("{{cookiecutter." + key + "}}", str(value))
    return text


def build_context(template_dir: Path,
                  overrides: dict[str, str] | None = None) -> dict[str, str]:
    """cookiecutter.json → 上下文（交叉引用迭代收敛；未收敛断言）。"""
    ctx: dict[str, str] = {}
    raw = json.loads((template_dir / "cookiecutter.json").read_text(
        encoding="utf-8"))
    ctx.update({k: str(v) for k, v in raw.items()})
    if overrides:
        ctx.update(overrides)
    for _ in range(_MAX_RESOLVE_ROUNDS):
        changed = False
        for key, value in list(ctx.items()):
            if "{{" in value:
                new = _render_text(value, ctx)
                if new != value:
                    ctx[key] = new
                    changed = True
        if not changed:
            break
    assert not any("{{" in v for v in ctx.values()), "上下文未收敛"
    return ctx


def render_template(template_dir: str | Path, out_dir: str | Path,
                    overrides: dict[str, str] | None = None) -> Path:
    """渲染模板目录 → out_dir/<project_slug>/（返回包根）。"""
    tdir = Path(template_dir)
    out = Path(out_dir)
    ctx = build_context(tdir, overrides)
    dest_root = out / _render_text("{{cookiecutter.project_slug}}", ctx)
    for path in sorted(tdir.rglob("*")):
        rel = path.relative_to(tdir)
        if rel.parts[0] == "cookiecutter.json":
            continue
        rel_rendered = _render_text(str(rel).replace("\\", "/"), ctx)
        dest = out / rel_rendered
        if path.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(
                _render_text(path.read_text(encoding="utf-8"), ctx),
                encoding="utf-8")
    return dest_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tools.plugin_templates.render",
        description="cookiecutter 最小占位符渲染器（离线替代，#222）")
    parser.add_argument("template", nargs="?", default=None,
                        help="模板目录名（tools/plugin_templates/ 下）")
    parser.add_argument("--out", default=".",
                        help="输出根目录（缺省当前目录）")
    parser.add_argument("--set", action="append", default=[],
                        metavar="KEY=VALUE", help="上下文覆盖（可多次）")
    parser.add_argument("--list", action="store_true",
                        help="列出可用模板后退出")
    args = parser.parse_args(argv)

    available = sorted(p.name for p in _TOOLS_ROOT.iterdir()
                       if p.is_dir() and (p / "cookiecutter.json").is_file())
    if args.list:
        print("\n".join(available))
        return 0
    if not args.template:
        parser.error("缺少 template 参数（--list 查看可用）")
    if args.template not in available:
        print(f"未知模板 {args.template!r}；可用：{'，'.join(available)}",
              file=sys.stderr)
        return 2
    overrides = {}
    for item in args.set:
        key, sep, value = item.partition("=")
        if not sep or not key:
            parser.error(f"--set 须为 KEY=VALUE 形式，得到 {item!r}")
        overrides[key] = value
    pkg_root = render_template(_TOOLS_ROOT / args.template, args.out,
                               overrides or None)
    print(f"rendered: {pkg_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
