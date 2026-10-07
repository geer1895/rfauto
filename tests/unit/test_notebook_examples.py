"""PR-14 notebook 示例库测试（席D3）。

examples/notebooks/ 首批 ≥3 个可运行示例（消费已合流闭式面）：

- **结构面**：nbformat 4 JSON 形态、cell 字段完整、代码单元零 magic
  零 shell 逃逸（保持 nbclient/普通 exec 双可跑）；
- **执行面（确定性门）**：代码单元按序 exec（共享命名空间，等价
  notebook 顺序执行）零异常——纯 Python 无 magic 使其无需内核即可
  确定性复跑；
- **执行面（内核面，skipif）**：nbclient 真内核执行——依赖 nbclient/
  jupyter_client/ipykernel，缺装诚实 skip（真跑非本席门同口径）；
- **导入守卫**：代码单元 import 的 rfauto 模块必须真实存在（防
  示例引用漂移）。
"""

from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
NB_DIR = REPO_ROOT / "examples" / "notebooks"


def _notebook_paths() -> list[Path]:
    if not NB_DIR.is_dir():
        return []
    return sorted(NB_DIR.glob("*.ipynb"))


def _cell_source(cell: dict) -> str:
    src = cell.get("source", "")
    if isinstance(src, list):
        return "".join(str(s) for s in src)
    return str(src)


def _load_raw(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestNotebookStructure:
    def test_at_least_three_examples(self):
        paths = _notebook_paths()
        assert len(paths) >= 3, f"首批 ≥3 示例，实测 {len(paths)}: {paths}"

    def test_nbformat4_structure(self):
        for path in _notebook_paths():
            raw = _load_raw(path)
            assert raw.get("nbformat") == 4, path.name
            assert isinstance(raw.get("cells"), list) and raw["cells"], \
                path.name
            for i, cell in enumerate(raw["cells"]):
                assert cell.get("cell_type") in ("markdown", "code"), \
                    f"{path.name} cell{i}"
                assert _cell_source(cell).strip(), \
                    f"{path.name} cell{i} 空源"
            # nbformat>=4.5 须有 cell id（nbformat 生成面自带；形态钉）
            if raw.get("nbformat_minor", 0) >= 5:
                for i, cell in enumerate(raw["cells"]):
                    assert "id" in cell, f"{path.name} cell{i} 缺 id"

    def test_code_cells_no_magic_no_shell(self):
        for path in _notebook_paths():
            raw = _load_raw(path)
            for i, cell in enumerate(raw["cells"]):
                if cell["cell_type"] != "code":
                    continue
                for ln, line in enumerate(
                        _cell_source(cell).splitlines(), start=1):
                    stripped = line.lstrip()
                    assert not stripped.startswith(("%", "!")), \
                        f"{path.name} cell{i} 行{ln} 含 magic/shell: {line!r}"

    def test_code_cells_import_existing_modules(self):
        for path in _notebook_paths():
            raw = _load_raw(path)
            for i, cell in enumerate(raw["cells"]):
                if cell["cell_type"] != "code":
                    continue
                tree = ast.parse(_cell_source(cell))
                for node in ast.walk(tree):
                    names: list[str] = []
                    if isinstance(node, ast.Import):
                        names = [a.name for a in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        names = [node.module]
                    for name in names:
                        if not name.startswith("rfauto"):
                            continue
                        assert importlib.util.find_spec(name) is not None, \
                            f"{path.name} cell{i} import 不存在: {name}"

    def test_code_cells_compile(self):
        for path in _notebook_paths():
            raw = _load_raw(path)
            for i, cell in enumerate(raw["cells"]):
                if cell["cell_type"] != "code":
                    continue
                # 不抛即过：compile 失败即 SyntaxError=测试失败
                compile(_cell_source(cell), f"{path.name}#cell{i}", "exec")


class TestNotebookExecution:
    @pytest.fixture(autouse=True)
    def _repo_cwd(self, monkeypatch):
        monkeypatch.chdir(REPO_ROOT)

    def test_sequential_exec_all_cells(self):
        # 确定性执行门：逐单元按序 exec（共享命名空间，等价顺序执行）
        for path in _notebook_paths():
            raw = _load_raw(path)
            ns: dict = {"__name__": "__main__"}
            for i, cell in enumerate(raw["cells"]):
                if cell["cell_type"] != "code":
                    continue
                # 仓内可信示例的确定性顺序执行（S 系 bandit 码未启用，
                # 无需 noqa——裸 exec 在此即被测能力本身）
                exec(compile(_cell_source(cell), f"{path.name}#cell{i}",
                             "exec"), ns)

    @pytest.mark.skipif(
        importlib.util.find_spec("nbclient") is None
        or importlib.util.find_spec("jupyter_client") is None,
        reason="内核执行面 opt-in：需 nbclient+jupyter_client+ipykernel"
               "（缺装诚实 skip，真跑非本席门）",
    )
    def test_kernel_execution_nbclient(self):
        nbclient = pytest.importorskip("nbclient")
        nbf = pytest.importorskip("nbformat")
        for path in _notebook_paths():
            nb = nbf.read(str(path), as_version=4)
            nbclient.NotebookClient(
                nb, timeout=120, kernel_name="python3",
                resources={"metadata": {"path": str(REPO_ROOT)}},
            ).execute()
            assert not any(
                c.get("outputs") and any(
                    o.get("output_type") == "error" for o in c["outputs"])
                for c in nb.cells if c.cell_type == "code"), path.name
