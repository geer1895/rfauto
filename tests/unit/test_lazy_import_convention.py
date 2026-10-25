"""R1-T10 lazy import 约定棘轮（aurora_g W11-S2，2026-10-19；W14-S1 扩 service）。

约定文：docs/explanation/lazy-import-conventions.md（形态判定与合法
lazy 原因白名单在那里）。本文件只钉三道门：

1. 示范文件严格钉零：cli/domains 三个示范文件（scattered/bands_uq/
   workflow，W11-S2 已 100% 标注 66 站（W12 实测口径））函数体内不得出现未标注的
   rfauto import——新增 lazy 一律补 `# lazy: <原因>` 或移模块顶。
2. service 层示范文件严格钉零（W14-S1）：service 层 lazy 前三名
   （api/run_core 31 站/calibration_service 29 站/rest_api 26 站，
   合计 86 处物理行已 100% 标注）同款钉零。
   （W15-S1 审查勘误：分项原写 30 站系笔误，AST 实测 29 站；合计 86
   无误。docs/explanation/lazy-import-conventions.md 两处镜像同笔待
   主代理顺笔回改。W3-S2 T2 包化（2026-10-19）：rest_api 巨石拆
   rest_api/ 包，26 站随域分布于 8 个子模块（datasets 10/slotline 5/
   system·runs·calculators·db·rag 各 2/openapi 1），示范锚逐文件
   枚举，口径与合计数不变。）
3. cli 层未标注总数棘轮：只收不放。2026-10-19 实测 271（其中含
   W11-S3 T8 并行在制新收口的未标注站；余量预留至 300——同战役
   并行轨落新 cli 收口时请顺手补标注，或同步上调本常量并在行注
   说明；下战役开工按实测收紧）。

口径：函数体（含方法/嵌套函数）内、目标模块以 ``rfauto`` 起头（或相
对导入）的 import 语句；``if TYPE_CHECKING`` 块内与 ``try/except
ImportError``（可选依赖保护，军规 8 面）内不计；标注判定扫描语句
全跨行（多行 import 的标注可落在任一行）。
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src" / "rfauto"
CLI_DIR = _SRC / "cli"
DEMO_FILES = ("scattered.py", "bands_uq.py", "workflow.py")
SERVICE_DIR = _SRC / "service"
#: W14-S1 service 层示范文件（lazy 前三名， SERVICE_DIR 相对 POSIX 路径）。
#: rest_api 八子模块=W3-S2 T2 包化后 26 站的逐文件锚（2026-10-19）。
SERVICE_DEMO_FILES = (
    "api/run_core.py",
    "calibration_service.py",
    "rest_api/system.py",
    "rest_api/runs.py",
    "rest_api/calculators.py",
    "rest_api/datasets.py",
    "rest_api/db.py",
    "rest_api/rag.py",
    "rest_api/slotline.py",
    "rest_api/openapi.py",
)
TAG = "# lazy:"
#: 2026-10-19 实测 271（见模块 docstring 的余量说明）。
CLI_UNTAGGED_BUDGET = 300


def _is_type_checking_test(test: ast.expr) -> bool:
    if isinstance(test, ast.Name) and test.id == "TYPE_CHECKING":
        return True
    return (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")


def _handles_import_error(handlers: list[ast.ExceptHandler]) -> bool:
    for h in handlers:
        names = []
        if isinstance(h.type, ast.Name):
            names = [h.type.id]
        elif isinstance(h.type, ast.Attribute):
            names = [h.type.attr]
        elif isinstance(h.type, ast.Tuple):
            names = [e.id for e in h.type.elts if isinstance(e, ast.Name)]
        if any(n in ("ImportError", "ModuleNotFoundError") for n in names):
            return True
    return False


def _untagged_function_body_imports(path: Path) -> list[str]:
    """返回人读 offenders 列表（"文件:行号: 语句首行摘录"）。"""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    tree = ast.parse(text)
    offenders: list[str] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        exempt: set[int] = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.If) and _is_type_checking_test(node.test):
                for n in ast.walk(node):
                    if isinstance(n, (ast.Import, ast.ImportFrom)):
                        exempt.add(id(n))
            if isinstance(node, ast.Try) and _handles_import_error(node.handlers):
                for n in ast.walk(node):
                    if isinstance(n, (ast.Import, ast.ImportFrom)):
                        exempt.add(id(n))
        for node in ast.walk(fn):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if id(node) in exempt:
                continue
            if isinstance(node, ast.ImportFrom):
                mod, level = node.module or "", node.level
            else:
                mod = node.names[0].name if node.names else ""
                level = 0
            if level == 0 and not mod.startswith("rfauto"):
                continue
            span = lines[node.lineno - 1:node.end_lineno]
            if any(TAG in line for line in span):
                continue
            offenders.append(
                f"{path.name}:{node.lineno}: {lines[node.lineno - 1].strip()[:70]}")
    return offenders


def _scan_cli_layer() -> dict[Path, list[str]]:
    return {py: _untagged_function_body_imports(py)
            for py in sorted(CLI_DIR.rglob("*.py"))}


def test_demo_files_fully_tagged():
    """示范文件（约定文落地席）函数体内 rfauto import 必须 100% 带标注。"""
    scan = _scan_cli_layer()
    for name in DEMO_FILES:
        path = CLI_DIR / "domains" / name
        assert path.exists(), f"示范文件缺失: {path}"
        offenders = scan[path]
        assert not offenders, (
            f"{name} 存在未标注的函数内 lazy import（约定见 "
            f"docs/explanation/lazy-import-conventions.md：补 `# lazy: <原因>` "
            f"标注，或移回模块顶）:\n  " + "\n  ".join(offenders))


def test_service_demo_files_fully_tagged():
    """service 层示范文件（W14-S1）函数体内 rfauto import 必须 100% 带标注。

    合法原因按约定文 service 分册：同层 T1 解环面=cycle-break（消除项=
    T1 台账），其余执行面取用=run-path（T2 迁移顺带，迁移需查 patch 缝）。
    """
    for rel in SERVICE_DEMO_FILES:
        path = SERVICE_DIR / rel
        assert path.exists(), f"service 示范文件缺失: {path}"
        offenders = _untagged_function_body_imports(path)
        assert not offenders, (
            f"service/{rel} 存在未标注的函数内 lazy import（约定见 "
            f"docs/explanation/lazy-import-conventions.md：补 `# lazy: "
            f"<cycle-break|run-path>` 标注，或移回模块顶）:\n  "
            + "\n  ".join(offenders))


def test_cli_layer_untagged_budget_ratchet():
    """cli 层未标注总数只收不放（预算语义见模块 docstring）。"""
    scan = _scan_cli_layer()
    total = sum(len(v) for v in scan.values())
    assert total <= CLI_UNTAGGED_BUDGET, (
        f"cli 层未标注函数内 lazy import 总数 {total} 超预算 "
        f"{CLI_UNTAGGED_BUDGET}（棘轮只收不放）。新增 lazy 请补 "
        f"`# lazy: <原因>` 标注（约定见 docs/explanation/"
        f"lazy-import-conventions.md）；确需放宽预算时上调 "
        f"CLI_UNTAGGED_BUDGET 并在行注说明理由。重灾区：\n  "
        + "\n  ".join(
            f"{p.name}: {len(v)} 处"
            for p, v in sorted(scan.items(), key=lambda kv: -len(kv[1]))[:8]
            if v))
