"""VB-6 SKILL 包 MCP resources/prompts 钉（aurora_r Wave2 席 R-13，
2026-11-10；提案源 runs/aurora_q/qx40_vbridge/PROPOSALS.md VB-6）。

预声明验收口径（PROPOSALS VB-6 ①-⑤）：
① 资源列表 = skills/ 目录实测清单（确定性排序）——目录走查独立实测
   vs list_resources() 注册面逐位一致；skill:// 注册序=包名字典序。
② 穿越/越界/绝对路径/背斜杠/符号链接逃逸/超 2MB 一律拒——守卫单源
   resolve_skill_file/read_skill_text 直钉 + MCP 读面拒钉。
③ prompts 文本正则扫描：零"数字+物理单位"字面量（铁律 7）——扫描器
   自带正负对照钉（扫描器自身先过已知基准才有资格裁判，#118 族）。
④ MCP 工具数不变：list_tools()==200==@mcp.tool 正则面（check_numbers
   count_mcp 同口径独立复算）；资源双口径一致：list_resources() 条目数
   ==@mcp.resource 正则面（R5-02 check_mcp_resources_vs_source 同款
   独立复算——两面同笔同移）。
⑤ stdio stdout 纯度钉仍绿：``python -m rfauto.mcp_server`` stdin EOF →
   stdout 零字节（家法同 test_mcp_server #278 钉）。

计数口径定案（VB-6 细化"先实测"项，2026-11-10 实测）：
- check_numbers.count_mcp() 只数 ``@mcp.tool`` 装饰器行（正则
  ``^@mcp\\.tool``），resources/prompts/模板零计入 → 工具数 200 不变，
  零计数面动作（本文件 ④ 双口径钉自证）。
- ``add_template`` 程序化注册的 references 模板不进 list_resources()
  也不进 ``@mcp.resource`` 正则面 → 计数双口径零扰动。
- 资源计数面 10→17（+7 静态 SKILL.md 资源）为预声明合流面：三个锚
  （test_mcp_server::TestMCPResources::test_resources_registered 精确
  集合断言 / test_check_numbers::test_mcp_resources_dual_source_consistent
  的 ``== 10`` 绝对锚 / test_cli_registration_order::test_mcp_tool_and_
  resource_order 的金快照 resources 清单）如实转红待合并者同笔递增
  （VB-6 细化"计数链同笔调整"+金快照 --write-gold 惯例）；两面
  一致性（17==17）不破。
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import subprocess
import sys
import typing
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SKILLS = _REPO / "skills"
_SCRIPT_CHECK_NUMBERS = _REPO / "scripts" / "check_numbers.py"


@pytest.fixture()
def mcp_server():
    from rfauto.mcp_server import mcp
    return mcp


def _import_check_numbers():
    """scripts/check_numbers.py 独立装载（家法同 test_check_numbers）。"""
    spec = importlib.util.spec_from_file_location(
        "check_numbers_r13", _SCRIPT_CHECK_NUMBERS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _expected_skill_packages() -> list[str]:
    """skills/ 目录独立实测（不走被测模块代码——清单=目录的独立性）。"""
    return sorted(
        p.name for p in _SKILLS.iterdir()
        if p.is_dir() and (p / "SKILL.md").is_file())


def _count_decorator_lines(pattern: str) -> int:
    """``^@mcp.<kind>`` 正则面计数（口径同 check_numbers.mcp_source_files：
    facade + mcp_tools 全集）。"""
    base = _REPO / "src" / "rfauto"
    files = [base / "mcp_server.py",
             *sorted((base / "mcp_tools").rglob("*.py"))]
    return sum(
        len(re.findall(pattern, f.read_text(encoding="utf-8"), re.MULTILINE))
        for f in files)


def _resource_text(resource_result) -> str:
    """read_resource 返回值提取文本（fastmcp 3.x 形态分流，家法同
    test_mcp_server._resource_text）。"""
    if hasattr(resource_result, "contents") and resource_result.contents:
        block = resource_result.contents[0]
        return getattr(block, "content", None) or getattr(block, "text", "")
    if isinstance(resource_result, list) and resource_result:
        return resource_result[0].text
    return str(resource_result)


# ══ ① 资源列表 = skills/ 目录实测清单（确定性排序） ════════════════════════


class TestSkillResourceListing:
    def test_skill_resources_match_directory_listing(self, mcp_server):
        from rfauto.mcp_tools._resources import SKILL_URI_SCHEME

        resources = asyncio.run(mcp_server.list_resources())
        raw_skill_uris = [str(r.uri) for r in resources
                          if str(r.uri).startswith(SKILL_URI_SCHEME)]
        expected = [f"{SKILL_URI_SCHEME}{p}/SKILL.md"
                    for p in _expected_skill_packages()]
        # 注册面=目录实测（逐位一致；新增包不注册即红=棘轮）
        assert raw_skill_uris == expected, (
            f"skill:// 资源注册清单≠skills/ 目录实测清单: "
            f"{raw_skill_uris} != {expected}")
        # 确定性排序：注册序（list_resources 原始序）本身=包名字典序
        assert raw_skill_uris == sorted(raw_skill_uris)

    def test_skill_reference_template_registered_once(self, mcp_server):
        from rfauto.mcp_tools._resources import SKILL_URI_SCHEME

        tpls = asyncio.run(mcp_server.list_resource_templates())
        skill_tpls = [t for t in tpls
                      if str(t.uri_template).startswith(SKILL_URI_SCHEME)]
        assert len(skill_tpls) == 1
        assert str(skill_tpls[0].uri_template) == \
            f"{SKILL_URI_SCHEME}{{name}}/references/{{path*}}"
        # 模板不进资源清单面（计数双口径零扰动的注册面证据）
        uris = {str(r.uri) for r in asyncio.run(mcp_server.list_resources())}
        assert not any("references" in u for u in uris)

    def test_existing_rfauto_resources_unchanged(self, mcp_server):
        """本席纯增量自证：既有十件 rfauto:// 资源逐件仍在（合并者锚
        递增=集合只增七件 skill://，零改零删）。"""
        uris = {str(r.uri) for r in asyncio.run(mcp_server.list_resources())}
        assert {
            "rfauto://runs/index",
            "rfauto://knowledge/materials",
            "rfauto://knowledge/compat_matrix",
            "rfauto://knowledge/terminology",
            "rfauto://knowledge/metric-glossary",
            "rfauto://toolsets/definition",
            "rfauto://edb/status",
            "rfauto://edb/datasets",
            "rfauto://calculators/index",
            "rfauto://datasets/index",
        } <= uris

    def test_read_skill_md_static(self, mcp_server):
        from rfauto.mcp_tools._resources import SKILL_URI_SCHEME

        for pkg in _expected_skill_packages():
            content = asyncio.run(
                mcp_server.read_resource(
                    f"{SKILL_URI_SCHEME}{pkg}/SKILL.md"))
            text = _resource_text(content)
            assert text.strip(), f"{pkg} SKILL.md 不应为空"

    def test_read_reference_subpath_via_template(self, mcp_server):
        from rfauto.mcp_tools._resources import SKILL_URI_SCHEME

        content = asyncio.run(mcp_server.read_resource(
            f"{SKILL_URI_SCHEME}veriloga-authoring/references/workflow.md"))
        text = _resource_text(content)
        assert text.strip(), "references/ 子路径模板读回不应为空"


# ══ ② 穿越/越界/绝对路径/符号链接逃逸/超大 一律拒 ══════════════════════════


def _try_dir_link(link: Path, target: Path) -> bool:
    """目录符号链接（Windows 回退目录联接 junction——无需特权）。"""
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if sys.platform == "win32":
        try:
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
            return True
        except OSError:
            return False
    return False


class TestSkillResourceGuards:
    """守卫单源直钉（resolve_skill_file/read_skill_text）+ MCP 读面拒钉。"""

    @pytest.mark.parametrize("name,rel", [
        ("rfauto-cpw", "../rfauto-pifa/SKILL.md"),        # .. 穿越
        ("rfauto-cpw", "references/../../AGENTS.md"),     # references 内穿越
        ("rfauto-cpw", "..\\..\\secret.md"),              # 背斜杠分隔符
        ("rfauto-cpw", "/etc/passwd"),                    # 绝对路径
        ("rfauto-cpw", "C:Windows\\x.md"),                # 盘符形态
        ("rfauto-cpw", "references/./x.md"),              # 点段
        ("rfauto-cpw", "references//x.md"),               # 空段
        ("no-such-pkg", "SKILL.md"),                      # 越界=未知包
        ("rfauto-cpw", "references/nope.md"),             # 缺失文件
        ("", "SKILL.md"),                                 # 空包名
        ("rfauto-cpw", "SKILL.md "),                      # 尾随空白
    ])
    def test_guard_rejects(self, name, rel):
        from rfauto.mcp_tools._resources import resolve_skill_file

        with pytest.raises(Exception) as ei:
            resolve_skill_file(name, rel)
        assert type(ei.value).__name__ == "SkillResourceError", ei.value

    def test_guard_positive_control(self):
        """正对照：合法包内路径解析成功且落在包目录内（守卫只拒非法）。"""
        from rfauto.mcp_tools._resources import resolve_skill_file

        got = resolve_skill_file("veriloga-authoring",
                                 "references/workflow.md")
        assert got.is_file() and got.name == "workflow.md"

    def test_symlink_escape_rejected(self, tmp_path):
        """符号链接/目录联接越界拒（resolve 后仍在包目录内判定）；
        链接创建不可用的环境如实 skip（环境类）。"""
        from rfauto.mcp_tools._resources import resolve_skill_file

        root = tmp_path / "skills"
        pkg = root / "pkg-a"
        pkg.mkdir(parents=True)
        (pkg / "SKILL.md").write_text("# pkg-a\n", encoding="utf-8")
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.md").write_text("secret", encoding="utf-8")
        # references 槽位让给越界链接（链接路径必须事先不存在——
        # symlink/junction 都不能落在已有目录上）
        if not _try_dir_link(pkg / "references", outside):
            pytest.skip("符号链接/目录联接创建不可用（环境类如实 skip）")
        with pytest.raises(Exception, match="越出"):
            resolve_skill_file("pkg-a", "references/secret.md", root=root)

    def test_oversize_file_rejected(self, tmp_path):
        """超 2MB 拒（上限=SKILL_MAX_BYTES=2 MiB；恰等于上限放行）。"""
        from rfauto.mcp_tools._resources import (
            SKILL_MAX_BYTES,
            read_skill_text,
        )

        assert SKILL_MAX_BYTES == 2 * 1024 * 1024
        big = tmp_path / "big.md"
        big.write_bytes(b"x" * (SKILL_MAX_BYTES + 1))
        with pytest.raises(Exception, match="超大"):
            read_skill_text(big)
        edge = tmp_path / "edge.md"
        edge.write_bytes(b"x" * SKILL_MAX_BYTES)
        assert len(read_skill_text(edge)) == SKILL_MAX_BYTES

    def test_mcp_surface_rejects_bad_uris(self, mcp_server):
        """MCP 读面拒钉：未知包/编码穿越/缺失→ResourceError；字面点段
        URI→fastmcp URL 归一化后不落模板（NotFoundError）——两种形态
        都是拒（一律拒口径），来源不同如实分钉。"""
        from fastmcp.exceptions import NotFoundError, ResourceError

        from rfauto.mcp_tools._resources import SKILL_URI_SCHEME

        with pytest.raises(ResourceError):
            asyncio.run(mcp_server.read_resource(
                f"{SKILL_URI_SCHEME}no-such-pkg/references/x.md"))
        with pytest.raises(ResourceError):  # 百分号编码穿越（unquote 后撞守卫）
            asyncio.run(mcp_server.read_resource(
                f"{SKILL_URI_SCHEME}veriloga-authoring/references/"
                "%2e%2e%2fAGENTS.md"))
        with pytest.raises(ResourceError):
            asyncio.run(mcp_server.read_resource(
                f"{SKILL_URI_SCHEME}veriloga-authoring/references/nope.md"))
        with pytest.raises((NotFoundError, ResourceError)):
            asyncio.run(mcp_server.read_resource(
                f"{SKILL_URI_SCHEME}veriloga-authoring/references/"
                "../../../AGENTS.md"))


# ══ ③ prompts 零"数字+物理单位"扫描钉（铁律 7） ════════════════════════════

# 数字+物理单位字面量扫描（词边界收口；IGNORECASE 覆盖大小写混写）。
_UNIT_SCAN_RE = re.compile(
    r"\d[\d.,]*\s*(?:mm|cm|km|um|µm|mil|inch|GHz|MHz|kHz|Hz|dB|dBm|dBc|"
    r"Ω|ohm|ohms|ns|us|µs|ms|°C|degC|pF|nF|uF|µF|nH|uH|pH|W|V|A|K|s|H|F)\b",
    re.IGNORECASE)


class TestSkillPrompts:
    _NAMES: typing.ClassVar[set[str]] = {
        "skill_parser_cluster_flow", "em_bench_task_flow",
        "recipe_draft_capture_flow"}

    def _prompt_texts(self, mcp_server) -> dict[str, str]:
        prompts = asyncio.run(mcp_server.list_prompts())
        texts: dict[str, str] = {}
        for p in prompts:
            comp = asyncio.run(mcp_server.get_prompt(p.name))
            rendered = asyncio.run(comp.render(arguments={}))
            texts[p.name] = rendered.messages[0].content.text
        return texts

    def test_three_workflow_prompts_registered(self, mcp_server):
        prompts = asyncio.run(mcp_server.list_prompts())
        assert {p.name for p in prompts} == self._NAMES

    def test_prompt_texts_nonempty_and_tool_refs_valid(self, mcp_server):
        """提示词只引用真实注册工具名（陈旧引用即红——与注册面同步
        的棘轮钉）。"""
        tools = asyncio.run(mcp_server.list_tools())
        tool_names = {t.name for t in tools}
        texts = self._prompt_texts(mcp_server)
        assert set(texts) == self._NAMES
        for name, text in texts.items():
            assert text.strip(), f"{name} 文本不应为空"
            refs = set(re.findall(r"`([a-zA-Z0-9_/]+)`", text))
            stale = refs - tool_names
            assert not stale, f"{name} 引用了未注册工具: {sorted(stale)}"

    def test_prompt_texts_zero_digit_with_unit(self, mcp_server):
        """铁律 7 钉：三条提示词文本零"数字+物理单位"字面量。"""
        texts = self._prompt_texts(mcp_server)
        for name, text in texts.items():
            hits = _UNIT_SCAN_RE.findall(text)
            assert not hits, f"{name} 疑似物理数值字面量: {hits}"

    def test_unit_scanner_positive_and_negative_controls(self):
        """扫描器自身先过已知基准（#118 族：裁判先验）。正对照=物理
        数值字面量必抓；负对照=含数字的工具名（ipc356 家族）不误伤。"""
        for good in ("50 Ohm", "2.4 GHz", "10 dB", "-40 °C", "12 mm",
                     "3.3 V", "100 nH", "5 s"):
            assert _UNIT_SCAN_RE.search(good), f"扫描器漏报: {good!r}"
        for bad in ("ipc356_fab_pair_check", "R13 席", "Q-X85 四批",
                    "aurora_r Wave2"):
            assert not _UNIT_SCAN_RE.search(bad), f"扫描器误报: {bad!r}"


# ══ ④ 工具数 200 不变 + 计数双口径一致（check_numbers 独立复算） ═══════════


class TestCountFaces:
    def test_tool_count_unchanged_200(self, mcp_server):
        tools = asyncio.run(mcp_server.list_tools())
        assert len(tools) == 208
        assert len(tools) == _count_decorator_lines(r"^@mcp\.tool"), (
            "list_tools() 注册面与 @mcp.tool 正则面漂移（count_mcp 口径）")

    def test_resources_dual_source_consistent(self, mcp_server):
        """R5-02 双口径独立复算：list_resources() 条目数 == @mcp.resource
        正则面（本席 +7 资源两面同笔同移；绝对锚 10→17 递增属合并者
        锚面——见模块 docstring 计数口径定案）。"""
        n_registry = len(asyncio.run(mcp_server.list_resources()))
        n_regex = _count_decorator_lines(r"^@mcp\.resource")
        assert n_registry == n_regex

    def test_check_numbers_count_mcp_still_200(self):
        """check_numbers.count_mcp() 实测=200（工具计数面零动作定案证据；
        count_mcp 不数 resources/prompts——只数 @mcp.tool 装饰器行）。"""
        cn = _import_check_numbers()
        assert cn.count_mcp() == 208
        # 资源双口径门（check_mcp_resources_vs_source）保持一致
        assert cn.check_mcp_resources_vs_source() is None

    def test_prompts_not_counted_by_tool_face(self, mcp_server):
        """prompts/@mcp.prompt 不进任何计数面（无 prompt 计数门；
        工具/资源正则对 prompt 装饰器行零命中）。"""
        assert _count_decorator_lines(r"^@mcp\.prompt") == 3
        assert _count_decorator_lines(r"^@mcp\.tool") == 208  # 不含 prompt（M-6 终合流 202→208：R-26 parser_ext +6）


# ══ ⑤ stdio stdout 纯度钉仍绿（#278 家法） ═════════════════════════════════


class TestStdioPurity:
    def test_module_main_with_devnull_stdin_emits_zero_stdout(self):
        """``python -m rfauto.mcp_server`` stdin EOF → stdout 零字节
        （资源/模板/提示词注册不污染 JSON-RPC 信道；banner/日志走 stderr
        不在口径）。"""
        proc = subprocess.Popen(
            [sys.executable, "-m", "rfauto.mcp_server"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            stdout, _ = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate(timeout=10)
            pytest.fail("rfauto.mcp_server 未在 30s 内随 stdin EOF 退出")
        assert proc.returncode == 0, f"rc={proc.returncode}"
        assert stdout == b"", (
            f"stdout 必须零字节（JSON-RPC 信道纯度），实得 "
            f"{len(stdout)} 字节: {stdout[:200]!r}")


# ══ 附：金快照锚面现状取证（只读——锚面禁改，转红现状如实留证） ═══════════


def test_gold_registration_order_snapshot_shape():
    """金快照 resources 清单=10（本席前基线）——本席 +7 后该锚由合并者
    --write-gold 重钉；本钉只锁快照文件形态（keys/工具序字段存在），
    不锁 resources 条目数（数量演进归 test_check_numbers 绝对锚）。"""
    gold = json.loads(
        (_REPO / "tests" / "gold" / "mcp_registration_order.json")
        .read_text(encoding="utf-8"))
    assert set(gold) == {"tool_names_order", "resources"}
    assert len(gold["tool_names_order"]) == 208  # M-6 终合流重钉
