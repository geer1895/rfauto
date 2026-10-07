"""W1-E D-05 定向门——mdSanitize 硬错化：净化器缺失/净化失败拒绝 innerHTML。

判据（runs/w1_phase1/criteria.md §W1-E）：
- 禁用 DOMPurify 的反证测试渲染零注入：DOMPurify 整体缺失 / sanitize 非函
  数 / 净化结果非字符串三形态下，renderMarkdown 一律 textContent 兜底，
  XSS 载荷（img onerror / script）永不进入 innerHTML；
- 手段注记：pages.js 是零依赖 ES module（无顶层 DOM 访问，node 直
  import 实测可跑），内核行为用 node 真单测驱动（tests/unit/js/
  w1e_d05_mdsanitize.test.mjs，本文件 subprocess 调用并断言逐条 PASS）；
  模板拼接语境的两个调用点不可脱离整页 DOM，由下方静态断言钉纪律；
- UI 冒烟关联：净化的成功路径（DOMPurify 健康）行为不变（node 用例 4）。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PAGES_JS = _REPO_ROOT / "src" / "rfauto" / "ui" / "static" / "pages.js"
_INDEX_HTML = _REPO_ROOT / "src" / "rfauto" / "ui" / "static" / "index.html"
_NODE_TEST = _REPO_ROOT / "tests" / "unit" / "js" / "w1e_d05_mdsanitize.test.mjs"


class TestNodeKernelReverseProof:
    """node 反证测试：禁用 DOMPurify 三形态 + 健康路径（零注入断言在 js）。"""

    def test_node_subprocess_all_pass(self):
        node = _find_node()
        proc = subprocess.run(
            [str(node), str(_NODE_TEST)], capture_output=True, text=True,
            timeout=60, cwd=str(_REPO_ROOT))
        assert proc.returncode == 0, (
            f"node 反证测试失败:\n{proc.stdout}\n{proc.stderr}")
        assert "ALL_OK" in proc.stdout
        # 逐条 PASS 在场（防 node 静默零用例通过）
        assert proc.stdout.count("PASS ") >= 11
        assert "FAIL " not in proc.stdout


def _find_node() -> str:
    """node 可执行探测（shutil.which；缺失如实 skip 不假绿）。"""
    import shutil

    node = shutil.which("node")
    if node is None:
        pytest.skip("node 不在 PATH——D-05 js 内核单测无法驱动（如实 skip）")
    return node


class TestCallSiteDiscipline:
    """模板拼接语境（不可整页 DOM 单测）的 python 侧静态断言。"""

    def test_weak_script_strip_fallback_removed(self):
        """旧弱降级（裸 <script> 剥离）必须已删除——它挡不住 img onerror。"""
        src = _PAGES_JS.read_text(encoding="utf-8")
        assert "<script[\\s\\S]*?<\\/script>" not in src

    def test_no_direct_innerHTML_assignment_of_mdSanitize(self):
        """任何调用点不得把 mdSanitize 结果直塞 innerHTML（null 注入面）。"""
        src = _PAGES_JS.read_text(encoding="utf-8")
        assert ".innerHTML = mdSanitize" not in src

    def test_template_sites_guarded_by_mdReady(self):
        """两处模板拼接语境必须 mdReady() 先行分流（不可用时走 esc 分支）。"""
        src = _PAGES_JS.read_text(encoding="utf-8")
        n = len(re.findall(r"mdReady\(\)\s*\?\s*mdSanitize\(", src,
                           re.S))
        assert n == 2, (
            f"模板拼接调用点的 mdReady 分流数变化（{n}）——核对新增调用点"
            "是否同样先探净化链可用性再拼 innerHTML")

    def test_renderMarkdown_is_single_entry_for_direct_render(self):
        """直渲染语境单点走 renderMarkdown（textContent 兜底封装）。"""
        src = _PAGES_JS.read_text(encoding="utf-8")
        assert "renderMarkdown(el," in src
        assert "export function renderMarkdown" in src

    def test_purify_load_order_preserved(self):
        """净化链加载前提：purify.min.js 以经典 script 在场，pages.js 经
        app.js ES import（module 天然延后，经典脚本先执行）进入——
        renderMarkdown 调用时 window.DOMPurify 必已可用。"""
        html = _INDEX_HTML.read_text(encoding="utf-8")
        assert 'src="/static/vendor/purify.min.js"' in html
        app_js = (_REPO_ROOT / "src" / "rfauto" / "ui" / "static"
                  / "app.js").read_text(encoding="utf-8")
        assert 'from "./pages.js"' in app_js
