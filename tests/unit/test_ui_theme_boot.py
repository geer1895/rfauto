"""W2-A（架构批）主题防闪（FOUC）boot 内联脚本回归钉。

P0-2（R1_ui_audit §13/P0-2）：index.html head 内联脚本在样式表生效前同步读档
→ html[data-theme]，消灭"存了 light/ocean/system(亮) 的用户每次刷新先闪暗色
再跳变"。本钉读源文本（免 node/免网络/不启动服务器），钉五件事：
1. boot 内联脚本存在于 <head>（body 解析前执行=先于首帧）；
2. localStorage 键与 theme.js THEME_KEY 单源一致（防双源漂移；A5-B/R-4
   起键面单源在 theme.js，pages.js re-export）；
3. 定型规则与 pages.js 同口径：旧 "dark" 别名→midnight、未知/缺省=system
   跟随 matchMedia(prefers-color-scheme: light)、写 html[data-theme] 与
   light 信号（documentElement 早镜像 + DOMContentLoaded 补写 body.light）；
4. html 标签缺省 data-theme="midnight" 保持（JS 被禁/localStorage 不可用的
   兜底面不漂移）；
5. CSP 哈希钉同步（D-04：server.py CSP_VALUE 含 boot 脚本 sha256）——内联
   脚本不入钉即被浏览器拒载，此钉防"源码钉绿而线上脚本被 CSP 拦"的假修。
"""

from __future__ import annotations

import base64
import hashlib
import re
import sys
from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_HTML = (_STATIC / "index.html").read_text(encoding="utf-8")
# 架构批 A5-B（R6 R-4）：THEME_KEY 键面单源迁 theme.js（pages.js re-export）
_THEME = (_STATIC / "theme.js").read_text(encoding="utf-8")

_m = re.search(r"<head>(.*?)</head>", _HTML, re.S)
assert _m, "index.html head 缺失（结构漂移）"
_HEAD = _m.group(1)

# 与 test_w1e_ui_csp.py 同一提取口径（浏览器哈希=标签间逐字节文本）
_INLINE_SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S)


def _boot_script() -> str:
    """head 内联脚本中含 localStorage 读档的主题 boot（现况唯一）。"""
    boots = [s for s in _INLINE_SCRIPT_RE.findall(_HEAD)
             if "localStorage" in s and "dataset.theme" in s]
    assert len(boots) == 1, (
        f"head 内主题 boot 脚本数={len(boots)}（应为 1）——FOUC 修复面漂移")
    return boots[0]


def test_boot_inline_script_in_head_before_style():
    m = re.search(r"<style>", _HEAD)
    assert m, "head 内 <style> 缺失"
    boot = _boot_script()
    # boot 必须出现在样式表之前（"样式表生效前读档"的字面口径）
    assert _HEAD.index(boot) < m.start(), "boot 脚本必须在 <style> 之前"


def test_theme_key_single_source_with_theme_js():
    m = re.search(r'THEME_KEY\s*=\s*"([^"]+)"', _THEME)
    assert m, "theme.js THEME_KEY 缺失"
    key = m.group(1)
    boot = _boot_script()
    assert f'localStorage.getItem("{key}")' in boot, (
        f"boot 读档键与 theme.js THEME_KEY({key!r}) 不一致")
    # 单源：boot 内不得出现第二个 localStorage 键面
    keys = set(re.findall(r'localStorage\.(?:getItem|setItem)\("([^"]+)"', boot))
    assert keys == {key}, f"boot 出现 THEME_KEY 之外的键: {keys - {key}}"


def test_boot_mode_resolution_matches_pages():
    boot = _boot_script()
    # 旧存量别名（pages.js _LEGACY_ALIAS: dark→midnight）
    assert '"dark"' in boot and "midnight" in boot
    # 缺省=system 跟随（pages.js getThemeMode/initPages 兜底口径）
    assert "matchMedia" in boot
    assert "(prefers-color-scheme: light)" in boot
    # 双写口径：html[data-theme]（设计系统变量面）+ light 信号（body.light，
    # 早镜像到 documentElement、DOMContentLoaded 补写 body）
    assert "dataset.theme" in boot
    assert 'classList.toggle("light"' in boot
    assert "DOMContentLoaded" in boot
    assert "document.body.classList" in boot
    # 失败安全（try/catch）：localStorage 不可用保持 html 缺省 midnight
    assert "try" in boot and "catch" in boot


def test_html_default_theme_unchanged():
    # JS 被禁/localStorage 不可用时的兜底面：html 标签缺省仍 midnight
    m = re.search(r'<html[^>]*data-theme="midnight"', _HTML)
    assert m, 'html 标签缺省 data-theme="midnight" 丢失'


def test_boot_script_csp_hash_pinned():
    """D-04 机制下内联脚本必须哈希钉进 CSP，否则浏览器拒载=修复无效（假修）。"""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
    from rfauto.ui.server import CSP_VALUE
    boot = _boot_script()
    digest = base64.b64encode(
        hashlib.sha256(boot.encode("utf-8")).digest()).decode()
    assert f"'sha256-{digest}'" in CSP_VALUE, (
        "boot 脚本内容与 server.py:CSP_VALUE 哈希钉失配——内容改动必须同步"
        " _THEME_BOOT_SHA256（否则线上被 CSP 拒载，FOUC 修复静默失效）")
