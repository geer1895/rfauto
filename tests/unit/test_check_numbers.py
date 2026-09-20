"""scripts/check_numbers.py 数字门的钉子测试（#97）。

只钉轻量口径：CLI 实注册 walk=111（typer.main.get_command 实测裁决
锚：main 侧 108 + bench_app 3）、文档头部模式必须实际匹配（>0，防"门空转"
回归）、exe 缺失断言走优雅报错路径。

不真跑 pytest collect（慢）——tests 计数保持脚本内"门日志优先/collect 回退"
行为，不在单测里触发。
"""

import importlib.util
import re
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_numbers.py"
_SPEC = importlib.util.spec_from_file_location("check_numbers_gate", _SCRIPT)
check_numbers = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_numbers)


def test_cli_registered_leaf_count_matches_anchor():
    # 对拍锚：typer 实注册叶子=111（main 侧 108 + bench_app 3）。
    # 旧"正则数装饰器"口径只扫 main.py 得 108（漏检子应用）。
    assert check_numbers.count_cli() == 111


def test_cli_bench_subapp_breakdown():
    counts = check_numbers.cli_leaf_counts()
    assert counts["bench"] == 3
    assert sum(counts.values()) == check_numbers.count_cli()


@pytest.mark.parametrize(
    ("doc", "pattern", "label"),
    [
        (doc, pat, label)
        for doc, pats in check_numbers.DOC_PATTERNS.items()
        for pat, label in pats
    ],
)
def test_doc_header_patterns_actually_match(doc: str, pattern: str, label: str):
    # 回归钉：每个核对模式必须能在对应文档头部实际匹配到（>0），
    # 否则门静默空转——文档改版时必须同步改模式，让门红而不是放行。
    text = check_numbers.read_head(doc)
    assert text, f"{doc} 头部不可读"
    assert re.search(pattern, text), (
        f"{doc}: 模式 0 匹配——数字门空转回归 (label={label}, pattern={pattern!r})"
    )


def test_mcp_entry_missing_reports_gracefully(tmp_path: Path):
    # exe 缺失时返回明确缺失信息而非抛异常（不算崩溃）。
    msg = check_numbers.mcp_entry_missing_message(tmp_path / "nope" / "rfauto-mcp.exe")
    assert msg is not None
    assert "missing" in msg
    assert "rfauto-mcp.exe" in msg


def test_mcp_entry_present_in_dev_venv():
    # 开发 venv（editable 重装后）应当存在；缺失时脚本门会红，这里只断言
    # "存在→None / 缺失→字符串"的判定不抛异常，不把安装态钉死进单测。
    result = check_numbers.mcp_entry_missing_message()
    assert result is None or "missing" in result
