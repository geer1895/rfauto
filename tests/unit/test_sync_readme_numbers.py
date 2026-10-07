"""PR-13a README 数字自动同步的保鲜钉（round16 规格 PR-13a；#97/XA-8 纪律）。

钉六件事（全 live 对 live，零硬编码数字——#247 口径；覆盖面键集除外，
它是 round16 规格的显式裁决不是计数）：
1. 同步态：sync(README 实文, check_numbers 实测) == README 实文——六数字
   （MCP/resources/CLI/CALC/模板/锚）任一漂移即红，修复动作写在断言消息里
   （XA-8 kernel_cards 同款"重渲染 == 已提交字节"）；
2. 幂等：二跑 diff=0（sync∘sync == sync，构造性保证的回归钉）；
3. 修复力：内联数字改错+数字条整块污染的副本经 sync 逐位还原；
4. fail-closed：载体行/插入点缺失必须 ValueError，禁止静默放弃（#316 方向）；
5. 门兼容：同步产物仍被 check_numbers.DOC_PATTERNS["README.md"] 全部咬合
   （0 匹配=门空转，R3-E-02② 回归钉在本消费者侧复钉）；
6. CLI 端到端：--write 落盘 tmp 副本后 dry-run rc=0 且字节不变（真 README
   零写入——测试隔离，#144 族）。
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO = Path(__file__).resolve().parents[2]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - 防御
        raise RuntimeError(f"无法装载 {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


gen: Any = _load_module(
    "_pr13a_sync_readme_numbers", _REPO / "scripts" / "sync_readme_numbers.py")

# round16 规格 PR-13a 覆盖面键集（显式裁决面，非计数断言；
# tests 徽章按规格排除——绑定全量门日志，不自动写。
# R5-02（review_ge8e）：resources 第六位入覆盖面——旧版渲染串硬编码
# "+3 resources"，README 漂移 3→4 时同步器/门双双结构性失明）
COVERAGE_KEYS = frozenset(
    {"mcp", "resources", "cli", "calc", "calc_all", "templates", "anchors"})

_REMEDY = (
    "修复：仓根重跑 `python scripts/sync_readme_numbers.py --write`，"
    "README 产物随本轮改动同笔提交（#97 文档与代码同 commit）"
)


@pytest.fixture(scope="module")
def counts() -> dict[str, int]:
    return gen.collect_counts(gen.load_check_numbers())


@pytest.fixture(scope="module")
def readme_text() -> str:
    return (_REPO / "README.md").read_text(encoding="utf-8")


def _drift(text: str, counts: dict[str, int]) -> str:
    """构造漂移副本：内联 MCP tools+resources 数字改错 + 数字条整块手改污染。"""
    d = re.sub(gen.CARRIER_MCP,
               f"（{counts['mcp'] + 1} 个工具 + {counts['resources'] + 1} 个 resources）",
               text)
    d = re.sub(r"CALCULATOR_REGISTRY \d+，含实验键 \d+",
               "CALCULATOR_REGISTRY 1，含实验键 2", d)
    block_pat = re.compile(
        re.escape(gen.AUTO_START) + r".*?" + re.escape(gen.AUTO_END), re.S)
    return block_pat.sub(
        gen.AUTO_START + "\n手改污染行（生成器须整块接管修复）\n" + gen.AUTO_END, d)


# ─── 1. 同步态（保鲜钉主钉） ────────────────────────────────────────────────

def test_readme_numbers_in_sync(counts: dict[str, int],
                                readme_text: str) -> None:
    synced = gen.sync_text(readme_text, counts)
    assert synced == readme_text, (
        "README 数字落后于 check_numbers 实测（PR-13a 保鲜钉）；" + _REMEDY)


def test_coverage_keys_complete(counts: dict[str, int]) -> None:
    assert set(counts) == set(COVERAGE_KEYS), (
        "覆盖面键集漂移——round16 规格 PR-13a 五数字（MCP/CLI/CALC/模板/锚）；"
        "扩面须同步更新本集合与本测试文件 docstring")


def test_counts_sane(counts: dict[str, int]) -> None:
    for key in sorted(COVERAGE_KEYS):
        assert counts[key] > 0, (
            f"counts[{key!r}]=0——计数函数静默退化（门空转同族），先查 "
            f"check_numbers 再谈同步")
    assert counts["calc_all"] >= counts["calc"], (
        "实验键数 < 主键数——check_numbers 口径自相矛盾")


# ─── 2. 幂等：二跑 diff=0 ───────────────────────────────────────────────────

def test_sync_idempotent(counts: dict[str, int], readme_text: str) -> None:
    once = gen.sync_text(readme_text, counts)
    twice = gen.sync_text(once, counts)
    assert twice == once, "二跑 diff!=0——sync_text 非幂等，禁止落盘"


# ─── 3. 修复力：漂移副本逐位还原 ────────────────────────────────────────────

def test_sync_repairs_drifted_copy(counts: dict[str, int],
                                   readme_text: str) -> None:
    repaired = gen.sync_text(_drift(readme_text, counts), counts)
    assert repaired == gen.sync_text(readme_text, counts), (
        "漂移副本 sync 后与干净副本不一致——数字条/载体重写有漏改面")


def test_strip_block_is_generator_owned(counts: dict[str, int],
                                        readme_text: str) -> None:
    block_pat = re.compile(
        re.escape(gen.AUTO_START) + r"(.*?)" + re.escape(gen.AUTO_END), re.S)
    m = block_pat.search(readme_text)
    assert m, f"README 缺数字条标记块（{gen.AUTO_START}）；" + _REMEDY
    assert gen.render_block(counts) == gen.AUTO_START + m.group(1) + gen.AUTO_END, (
        "数字条标记块内容与生成器渲染不一致——手改了 AUTO 段或计数已前进；" + _REMEDY)


# ─── 4. fail-closed：载体/插入点缺失必须红 ──────────────────────────────────

def test_missing_carriers_fail_closed(counts: dict[str, int],
                                      readme_text: str) -> None:
    broken = re.sub(gen.CARRIER_MCP, "（工具若干）", readme_text)
    with pytest.raises(ValueError, match="MCP 载体行"):
        gen.sync_text(broken, counts)
    broken2 = re.sub(r"CALCULATOR_REGISTRY \d+，含实验键 \d+", "计算器若干",
                     readme_text)
    with pytest.raises(ValueError, match="CALC 载体行"):
        gen.sync_text(broken2, counts)


def test_missing_insert_anchor_fail_closed(counts: dict[str, int],
                                           readme_text: str) -> None:
    block_pat = re.compile(
        re.escape(gen.AUTO_START) + r".*?" + re.escape(gen.AUTO_END), re.S)
    stripped = block_pat.sub("", readme_text)
    stripped = stripped.replace(gen.STRIP_HEADING_ANCHOR, "## 已改名", 1)
    with pytest.raises(ValueError, match="插入点"):
        gen.sync_text(stripped, counts)


# ─── 5. 门兼容：同步产物仍被 check_numbers 模式全咬合 ───────────────────────

def test_synced_text_keeps_check_numbers_patterns(counts: dict[str, int],
                                                  readme_text: str) -> None:
    synced = gen.sync_text(readme_text, counts)
    patterns = gen.load_check_numbers().DOC_PATTERNS["README.md"]
    for pat, label in patterns:
        assert re.search(pat, synced), (
            f"sync 后 check_numbers 模式 0 匹配（label={label}）——同步器破坏"
            "了门载体行，门将空转（R3-E-02② 同族）")


# ─── 6. CLI 端到端：--write 落盘 tmp 副本，真 README 零写入 ─────────────────

def test_cli_write_then_dry_run_idempotent(tmp_path: Path,
                                           counts: dict[str, int],
                                           readme_text: str) -> None:
    dst = tmp_path / "README.md"
    dst.write_text(_drift(readme_text, counts), encoding="utf-8")
    assert gen.main(["--readme", str(dst), "--write"]) == 0
    written = dst.read_text(encoding="utf-8")
    assert written == gen.sync_text(readme_text, counts), (
        "--write 产物 != sync_text 渲染——CLI 面与纯函数面不同源")
    assert gen.main(["--readme", str(dst)]) == 0
    assert dst.read_text(encoding="utf-8") == written, (
        "已同步文件二跑发生变化——CLI 路径非幂等")


def test_cli_dry_run_reports_drift(tmp_path: Path, counts: dict[str, int],
                                   readme_text: str,
                                   capsys: pytest.CaptureFixture[str]) -> None:
    dst = tmp_path / "README.md"
    dst.write_text(_drift(readme_text, counts), encoding="utf-8")
    assert gen.main(["--readme", str(dst)]) == 1
    out = capsys.readouterr().out
    # unified diff 删除行=单破折号前缀（双破折号是 fromfile 头，不算）
    assert any(re.search(r"^-(?!-)", ln) for ln in out.splitlines()), (
        "dry-run 漂移未打 diff——报告面失效")
    assert "--write" in out, "dry-run 报告缺修复动作提示"
