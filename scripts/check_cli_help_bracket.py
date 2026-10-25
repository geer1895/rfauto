"""CLI 参数级 help 字符卫生静态扫描（D-06 参数级清偿，2026-10-11 aurora36 W5-C）。

背景（#305 家族 / D-06）：typer 的 --help 经 rich 渲染且 markup 开启——help
文本含裸 ``[`` 时 ASCII 词元 ``[xxx]`` 被当 rich 标记静默吞掉（实测
``A [exp] B`` 渲染成 ``A  B``）、闭合标记 ``[/xxx]`` 直接 MarkupError 炸
--help。命令级（cmd.help/short_help）同源门=tests/unit/
test_cli_help_text_hygiene.py（2026-10-05 W1-D 清偿 10 处后收紧全禁）；
参数级（--param 描述）21 处残留 2026-10-11 W5-C 清偿后由本脚本+同目录
测试 TestParamHelpTextHygiene 双机制常驻（树面判定=构建后 click 树逐
param.help，是判定地面真相；本脚本=源码级 AST 归因工具，红时直接给出
file:line，也兜住未挂载/开发中 CLI 面）。

口径：AST 扫 src/rfauto/cli/ 树全部 Call 的 help= 字符串字面（typer.Option/
typer.Argument/Annotated 内嵌调用均覆盖；相邻字面串隐式拼接在 AST 层已是
单个 Constant，天然覆盖；f-string 取其字面片段）。含 ``[`` 记违例；
``%`` 面不在本门作用域（click 参数 help 无 %-展开，命令级 % 门与 #305
argparse 家族归 test_cli_help_text_hygiene.py）。

退出码：0=零残留；1=有残留（逐条 file:line 打印，改写口径=全角【】/
圆括号/描述化，语义不变）。
"""
from __future__ import annotations

import ast
import sys
import warnings
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCAN_ROOT = REPO / "src" / "rfauto" / "cli"


def _help_literals(source: str, rel: str) -> list[tuple[int, str]]:
    """提取一段源码中全部 help= 字符串字面（Constant 与 f-string 字面片段）。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        tree = ast.parse(source, filename=rel)
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg != "help":
                continue
            value = kw.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                out.append((getattr(value, "lineno", kw.lineno), value.value))
            elif isinstance(value, ast.JoinedStr):
                literal = "".join(
                    str(part.value) for part in value.values
                    if isinstance(part, ast.Constant))
                if literal:
                    out.append((getattr(value, "lineno", kw.lineno), literal))
    return out


def scan_repo(root: Path | None = None) -> list[tuple[str, int, str]]:
    """扫描 CLI 树，返回 (rel_path, lineno, text) 违例清单。"""
    violations: list[tuple[str, int, str]] = []
    for path in sorted((root or SCAN_ROOT).rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(REPO).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:  # 观测性 best-effort（#105）
            print(f"WARN 读取跳过: {rel}: {exc}")
            continue
        for lineno, text in _help_literals(source, rel):
            if "[" in text:
                violations.append((rel, lineno, text))
    return violations


def main() -> int:
    violations = scan_repo()
    for rel, lineno, text in violations:
        print(f"CLI_HELP_BRACKET {rel}:{lineno} {text!r}")
    print(f"CLI_HELP_BRACKET_SUMMARY violations={len(violations)}")
    if violations:
        print("CLI_HELP_BRACKET_VIOLATIONS（改写口径：全角【】/圆括号/描述化，"
              "语义不变；rich markup 面 [ 必吞词元或炸 --help）")
        return 1
    print("CLI_HELP_BRACKET_CLEAN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
