"""Q-W8-3 UI 走查自动化回归门（aurora_q R11 Top1 吸收批，静态 a11y-lite 形态）。

gh 实践四机制同构（runs/aurora_q/r11/CROSS_POLLINATION.md §域7）：a11y
snapshot / 走查留痕 / 回归门 / 逃生口。aurora_l 曾做 26 页浏览器人工走查
（console=0，TODO L74 实录）——本席把它自动化为常驻回归门。

**环境实测形态判定（2026-11-05，任务书预置二选一如实判定）**：playwright
不在 venv（`.venv/Scripts/python.exe -m pip list` 实测 rc=1，零命中）——
落 **零新依赖形态**：starlette TestClient 遍历全部 UI 路由（照
test_aurora_n_ui_e2e_smoke 真服先例；禁真端口长驻，#143 备用端口纪律只对
真进程）→ 每页静态 a11y-lite 审计，六检查：

  标题层级跳变 / 图片 alt 缺失 / 按钮无可达名 / 链接 href 空 /
  重复 id / 表单控件无 label

SPA 页 HTML 由 view_*.js 模板字面量生成——走查器做 JS→HTML 语料抽取
（模板字面量+HTML 形态引号串；``${...}`` 插值替换为唯一 token=动态内容
视同在场）。抽取器是带状态机的小型 JS 词法面：模板字面量嵌套、``//``
与 ``/* */`` 注释、**正则字面量**（view_agent.js 的 ``/^[{[]/`` 实证：
不识别正则会让插值深度计数 desync → 扫描发散分钟级假死——本文件
extract 版本含正则/注释双处理+全局步数熔断，回归钉
TestJsExtractor::test_regex_literal_desync_regression）。

回归门（上限棘轮只收不放，W2-C 家法：探针内联、禁 runs/ 工件依赖）：
- UI_WALK_ISSUES_CAP：全部页 issue 总数上限（基线实测冻结，修复只降不升；
  新页/新 issue 使总数超限即红——修 UI 或有意抬门须同笔说明）；
- 页数棘轮：枚举页数 ≥ 基线 26（禁缩 scope 骗门）；
- 检查种类棘轮：六检查逐类计数 ≤ 基线（类内只收不放）；
- index 壳单独钉 0（W5-S23/W7 a11y 批已打磨净，回归即红）。

浏览器级快照衔接点（逃生口正向登记）：playwright 落地后仅需把本文件的
``_page_corpus``（JS 语料抽取）替换为真浏览器 a11y snapshot 拉取，六检查
审计函数与棘轮门结构原样复用；登记见 Q-W8-3 交付报告。
"""

from __future__ import annotations

import re
import sys
import textwrap
from html.parser import HTMLParser

import pytest

from rfauto.ui.server import create_ui_app

# ── 棘轮常量（只收不放；修复后同笔下调，有意抬门须同笔说明） ─────────────────
#: 全部走查页 issue 总数上限（基线实测冻结 2026-11-05：26 页 88 条=
#: control_no_label 84 + dup_id 4；快照 runs/aurora_q/qw83_audit/
#: ui_walk_issues_baseline.json）
UI_WALK_ISSUES_CAP = 88
#: 页数下限（枚举动态解析 pages.js——只增不减；缩 scope 骗门即红）
UI_WALK_PAGES_FLOOR = 26
#: 检查种类棘轮（逐类 ≤ 基线；键集=六检查种类）
UI_WALK_KIND_CAPS = {
    "control_no_label": 84,
    "dup_id": 4,
    "button_no_name": 0,
    "img_alt_missing": 0,
    "a_no_href": 0,
    "heading_jump": 0,
}
#: index 壳 issue 上限（壳已打磨净——回归即红）
INDEX_SHELL_ISSUES_CAP = 0


# ────────────────────────── JS→HTML 语料抽取 ──────────────────────────

_STEP_BUDGET = 4_000_000  # 全局步数熔断（扫描发散即响错，不假死）


class _BudgetExceeded(RuntimeError):
    pass


class _JsHtmlExtractor:
    """JS 源 → HTML 形态字符串语料（模板字面量+HTML 形态引号串）。

    ``${...}`` 插值替换为唯一 token（动态内容视同在场：按钮含 ${t(...)}
    文本=有可达名；动态 id 唯一化不产假 dup）。嵌套模板/注释/正则字面量
    三态处理（缺失后两者会 desync 插值深度——view_agent.js 实证回归钉）。"""

    def __init__(self, js: str) -> None:
        self.js = js
        self.n = len(js)
        self.steps = 0
        self.counter = 0
        self.out: list[str] = []

    def _tick(self) -> None:
        self.steps += 1
        if self.steps > _STEP_BUDGET:
            raise _BudgetExceeded(
                f"JS 语料抽取步数超熔断（{_STEP_BUDGET}）——扫描发散回归")

    def extract(self) -> str:
        js, n = self.js, self.n
        i = 0
        while i < n:
            self._tick()
            c = js[i]
            if c == "/" and i + 1 < n and js[i + 1] == "/":
                while i < n and js[i] != "\n":
                    i += 1
                continue
            if c == "/" and i + 1 < n and js[i + 1] == "*":
                end = js.find("*/", i + 2)
                i = self.n if end < 0 else end + 2
                continue
            if c == "`":
                i = self._read_template(i)
                continue
            if c == "/":
                # 主上下文同样需正则字面量处理（view_agent.js 实证：/'/ 形态
                # 正则会吞掉后续引号串/模板——与插值体同款 desync）
                i = self._regex_or_div(i)
                continue
            if c in "'\"":
                text, i = self._read_quoted(i, c)
                if "<" in text and re.search(r"<[a-zA-Z/]", text):
                    self.out.append(text)
                continue
            i += 1
        return "\n".join(self.out)

    def _read_template(self, j: int) -> int:
        """模板字面量（`` ` `` 起）：文本收语料，``${}`` 换 token 递归跳过。"""
        js, n = self.js, self.n
        buf: list[str] = []
        assert js[j] == "`"
        j += 1
        while j < n:
            self._tick()
            c = js[j]
            if c == "\\":
                j += 2
                continue
            if c == "`":
                self.out.append("".join(buf))
                return j + 1
            if c == "$" and j + 1 < n and js[j + 1] == "{":
                self.counter += 1
                buf.append(f"i{self.counter}")  # 唯一 token：动态内容视同在场
                j = self._read_interp(j + 2)
                continue
            buf.append(c)
            j += 1
        self.out.append("".join(buf))
        return j

    def _read_interp(self, j: int) -> int:
        """``${...}`` 表达式体：深度计 braces，串/模板/注释/正则三态跳过。"""
        js, n = self.js, self.n
        depth = 1
        while j < n:
            self._tick()
            c = js[j]
            if c == "\\":
                j += 2
                continue
            if c == "/" and j + 1 < n and js[j + 1] == "/":
                while j < n and js[j] != "\n":
                    j += 1
                continue
            if c == "/" and j + 1 < n and js[j + 1] == "*":
                end = js.find("*/", j + 2)
                j = n if end < 0 else end + 2
                continue
            if c in "'\"":
                _, j = self._read_quoted(j, c)
                continue
            if c == "`":
                j = self._read_template(j)
                continue
            if c == "/":
                j = self._regex_or_div(j)
                continue
            if c == "{":
                depth += 1
                j += 1
                continue
            if c == "}":
                depth -= 1
                j += 1
                if depth == 0:
                    return j
                continue
            j += 1
        return j

    def _regex_or_div(self, j: int) -> int:
        """插值体内 ``/``：正则字面量（含 ``[...]`` 类）整段跳过 or 除号 +1。"""
        js, n = self.js, self.n
        k = j - 1
        while k >= 0 and js[k] in " \t\r\n":
            k -= 1
        prev = js[k] if k >= 0 else ""
        if prev and (prev.isalnum() or prev in "_$)]}\"'`" or prev == "."):
            return j + 1  # 除号（前导=标识符/数字/右括号/引号尾）
        j += 1
        in_class = False
        while j < n:
            self._tick()
            ch = js[j]
            if ch == "\\":
                j += 2
                continue
            if ch == "[":
                in_class = True
            elif ch == "]":
                in_class = False
            elif ch == "/" and not in_class:
                j += 1
                break
            j += 1
        while j < n and js[j].isalpha():
            j += 1  # flags（g/i/m/s/u/y）
        return j

    def _read_quoted(self, j: int, quote: str) -> tuple[str, int]:
        js, n = self.js, self.n
        buf: list[str] = []
        j += 1
        while j < n:
            self._tick()
            c = js[j]
            if c == "\\":
                j += 2
                continue
            if c == quote:
                return "".join(buf), j + 1
            buf.append(c)
            j += 1
        return "".join(buf), j


def _extract_js_html(js: str) -> str:
    return _JsHtmlExtractor(js).extract()


# ────────────────────────── a11y-lite 审计器 ──────────────────────────

#: 无需可达名的 input type（hidden 不可见；submit/button/reset 以 value 为名）
_EXEMPT_INPUT_TYPES = frozenset({"hidden", "submit", "button", "reset"})


class A11yLiteAuditor(HTMLParser):
    """六检查静态 a11y-lite 审计（HTML 片段容错解析）。

    检查种类：heading_jump / img_alt_missing / button_no_name /
    a_no_href / dup_id / control_no_label。label 关联三通道：aria-label/
    aria-labelledby/title 显式名、label[for]=id 同页关联、label 包裹。
    placeholder 不算 label（WCAG：输入即消失——棘轮吸收现状，修复只降）。"""

    def __init__(self, page: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page = page
        self.issues: list[dict] = []
        self._ids: dict[str, int] = {}
        self._label_for: set[str] = set()
        self._heading_seq: list[int] = []
        self._label_depth = 0
        self._button_stack: list[dict] = []
        self._pending_controls: list[dict] = []

    # —— 标签面 ——
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        tag = tag.lower()
        if tag == "label":
            self._label_depth += 1
            if a.get("for"):
                self._label_for.add(a["for"])
            return
        self._common_start(tag, a, selfclosing=False)

    def handle_startendtag(self, tag, attrs):
        self._common_start(tag.lower(), dict(attrs), selfclosing=True)

    def _common_start(self, tag: str, a: dict, *, selfclosing: bool) -> None:
        if a.get("id"):
            self._ids[a["id"]] = self._ids.get(a["id"], 0) + 1
        if tag == "img" and "alt" not in a:
            self._issue("img_alt_missing", tag, a)
        if not selfclosing and tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading_seq.append(int(tag[1]))
        if tag == "a" and ("href" not in a or a.get("href") == ""):
            self._issue("a_no_href", tag, a)
        if tag in ("input", "select", "textarea"):
            self._pending_controls.append({"tag": tag, "attrs": a})
            return
        if tag == "button" and not selfclosing:
            frame = {"attrs": a, "text": [], "depth": 1}
            self._button_stack.append(frame)
            return
        if self._button_stack:
            self._button_stack[-1]["depth"] += 1

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "label":
            if self._label_depth > 0:
                self._label_depth -= 1
            return
        if self._button_stack:
            if self._button_stack[-1]["depth"] > 1:
                self._button_stack[-1]["depth"] -= 1
            else:
                self._check_button(self._button_stack.pop())

    def handle_data(self, data):
        if self._button_stack:
            self._button_stack[-1]["text"].append(data)

    # —— 检查面 ——
    def _issue(self, kind: str, tag: str, a: dict, *, detail: str = "") -> None:
        self.issues.append({
            "page": self.page, "kind": kind, "tag": tag,
            "detail": detail or " ".join(
                f'{k}={v!r}' for k, v in a.items())[:120],
        })

    def _check_button(self, frame: dict) -> None:
        a = frame["attrs"]
        if a.get("aria-label") or a.get("aria-labelledby") or a.get("title"):
            return
        if "".join(frame["text"]).strip():
            return
        self._issue("button_no_name", "button", a)

    def _check_control(self, ctl: dict) -> None:
        a = ctl["attrs"]
        tag = ctl["tag"]
        if tag == "input" and a.get("type", "text") in _EXEMPT_INPUT_TYPES:
            return
        if a.get("aria-label") or a.get("aria-labelledby") or a.get("title"):
            return
        cid = a.get("id") or ""
        if cid and cid in self._label_for:
            return
        # label 包裹判定：控件出现在 label 开闭区间内无法从 attrs 读出——
        # 语料形态下 label 包裹的控件极少数；保守按「无显式关联」计
        self._issue("control_no_label", tag, a, detail=cid or
                    " ".join(f'{k}={v!r}' for k, v in a.items())[:120])

    def finish_a11y(self) -> list[dict]:
        """收尾检查（重复 id / 标题跳变 / label[for] 后解析）。"""
        for k, v in self._ids.items():
            if v > 1:
                self.issues.append({"page": self.page, "kind": "dup_id",
                                    "tag": "*", "detail": f'id={k!r} x{v}'})
        prev = None
        for lvl in self._heading_seq:
            if prev is not None and lvl > prev + 1:
                self.issues.append({"page": self.page, "kind": "heading_jump",
                                    "tag": f"h{lvl}",
                                    "detail": f"h{prev}->h{lvl}"})
            prev = lvl
        for ctl in self._pending_controls:
            self._check_control(ctl)
        self._pending_controls.clear()
        return self.issues


def audit_html_fragment(html: str, page: str) -> list[dict]:
    auditor = A11yLiteAuditor(page)
    auditor.feed(html)
    auditor.close()
    return auditor.finish_a11y()


# ────────────────────────── 路由枚举（HTTP 面） ──────────────────────────

_LAZY_RE = re.compile(
    r'const (\w+) = _lazyView\("(\w+)", "([\w.]+)", "\w+"\);')
_VIEWS_BLOCK_RE = re.compile(r"Object\.assign\(VIEWS, \{(.*?)\}\);",
                             re.S)
_STATIC_IMPORT_RE = re.compile(
    r'import \{([\w, ]+)\} from "\./pages/([\w.]+)"')


def enumerate_view_routes(pages_js_text: str) -> dict[str, str]:
    """pages.js → {路由键: 视图模块文件}（_lazyView 注册+静态 import 双源，
    VIEWS 组装块绑定名解析——新页自动入走查范围，动态枚举不写死）。"""
    binding2file: dict[str, str] = {}
    for binding, _key, fname in _LAZY_RE.findall(pages_js_text):
        binding2file[binding] = fname
    for names, fname in _STATIC_IMPORT_RE.findall(pages_js_text):
        for nm in names.split(","):
            nm = nm.strip()
            binding2file.setdefault(nm, fname)
    block_m = _VIEWS_BLOCK_RE.search(pages_js_text)
    assert block_m, "VIEWS 组装块缺失（pages.js 结构漂移——枚举源失真）"
    routes: dict[str, str] = {}
    for key, binding in re.findall(r"(\w+): (\w+)[,\n]", block_m.group(1)):
        fname = binding2file.get(binding)
        assert fname, f"路由 {key} 绑定 {binding} 无法解析到视图文件"
        routes[key] = fname
    return routes


def walk_all_pages(client) -> dict:
    """全路由 HTTP 走查：pages.js 枚举 → 逐页模块 HTTP 拉取 → 语料抽取 →
    六检查审计。返回 {routes, pages:{key:{file,issues}}, total, kinds}。"""
    resp = client.get("/static/pages.js")
    assert resp.status_code == 200
    routes = enumerate_view_routes(resp.text)
    pages: dict[str, dict] = {}
    kinds: dict[str, int] = {}
    total = 0
    for key in sorted(routes):
        fname = routes[key]
        mod_resp = client.get(f"/static/pages/{fname}")
        assert mod_resp.status_code == 200, f"视图模块 404: {key} {fname}"
        corpus = _extract_js_html(mod_resp.text)
        issues = audit_html_fragment(corpus, key)
        pages[key] = {"file": fname, "issues": issues}
        total += len(issues)
        for it in issues:
            kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1
    index_resp = client.get("/")
    assert index_resp.status_code == 200
    shell_issues = audit_html_fragment(index_resp.text, "index")
    return {
        "routes": routes,
        "pages": pages,
        "total": total,
        "kinds": kinds,
        "index_issues": shell_issues,
    }


# ────────────────────────── 测试夹具（局部，禁改 conftest） ──────────────────────────


@pytest.fixture()
def _iso(tmp_path, monkeypatch):
    """cwd+鉴权 env 隔离（#144 家族口径；本席只走读路径零写面，防 mount
    解析触真实 runs/ 湖——include_runs_mount=False 已免，chdir 双保险）。"""
    monkeypatch.delenv("RFAUTO_UI_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture()
def client(_iso):
    from starlette.testclient import TestClient

    with TestClient(create_ui_app(include_runs_mount=False)) as c:
        yield c


# ────────────────────────── 走查门（全路由） ──────────────────────────


class TestWalkthroughGate:
    def test_full_walk_issues_within_ratchet_cap(self, client):
        """主门：全 26+ 页走查 issue 总数 ≤ UI_WALK_ISSUES_CAP（只收不放）。"""
        report = walk_all_pages(client)
        assert report["total"] <= UI_WALK_ISSUES_CAP, (
            f"UI_WALK_ISSUES={report['total']} > 棘轮 {UI_WALK_ISSUES_CAP}；"
            f"超限明细（页:种类:细节）: {_top_issues(report, 12)}")

    def test_page_scope_no_shrink(self, client):
        """页数棘轮：动态枚举页数 ≥ 基线 26——新页自动入走查，缩 scope 即红。"""
        report = walk_all_pages(client)
        assert len(report["routes"]) >= UI_WALK_PAGES_FLOOR, (
            f"走查页数 {len(report['routes'])} < 下限 {UI_WALK_PAGES_FLOOR}")

    def test_all_view_modules_serve_200(self, client):
        """走查范围全页模块 HTTP 200（路由枚举→文件映射→静态服务链通）。"""
        routes = enumerate_view_routes(client.get("/static/pages.js").text)
        assert routes, "路由枚举空转（枚举源失真）"
        for key, fname in routes.items():
            resp = client.get(f"/static/pages/{fname}")
            assert resp.status_code == 200, f"{key} → {fname} 非 200"

    def test_per_kind_ratchet_caps(self, client):
        """检查种类棘轮：六检查逐类计数 ≤ 基线（类内只收不放）。"""
        report = walk_all_pages(client)
        kinds = report["kinds"]
        for kind, cap in UI_WALK_KIND_CAPS.items():
            assert kinds.get(kind, 0) <= cap, (
                f"{kind}={kinds.get(kind, 0)} > 类棘轮 {cap}；明细: "
                f"{_top_issues(report, 12, kind=kind)}")

    def test_index_shell_zero_issues(self, client):
        """index 壳钉 ≤ 上限（W5-S23/W7 a11y 批打磨净，基线 0——回归即红）。"""
        report = walk_all_pages(client)
        assert len(report["index_issues"]) <= INDEX_SHELL_ISSUES_CAP, (
            f"index 壳 a11y 回归: {report['index_issues'][:5]}")

    def test_walk_report_shape_and_serializable(self, client, tmp_path):
        """走查留痕：报告结构完整+可 JSON 落盘（证据区衔接面）。"""
        import json

        report = walk_all_pages(client)
        assert set(report["routes"]) >= {
            "dashboard", "runs", "tune", "detail", "agent", "guide",
            "calibration", "gallery", "campaign", "queue"}
        assert report["total"] == sum(
            len(p["issues"]) for p in report["pages"].values())
        for page in report["pages"].values():
            for it in page["issues"]:
                assert set(it) == {"page", "kind", "tag", "detail"}
        blob = tmp_path / "walk.json"
        blob.write_text(json.dumps(
            {"total": report["total"], "kinds": report["kinds"],
             "routes": sorted(report["routes"])}, ensure_ascii=False),
            encoding="utf-8")
        assert json.loads(blob.read_text(encoding="utf-8"))["total"] \
            == report["total"]


def _top_issues(report: dict, limit: int, kind: str | None = None) -> str:
    rows = []
    for key in sorted(report["pages"]):
        for it in report["pages"][key]["issues"]:
            if kind and it["kind"] != kind:
                continue
            rows.append(f"{key}:{it['kind']}:{it['detail'][:60]}")
    return " | ".join(rows[:limit])


# ────────────────────────── 抽取器回归钉 ──────────────────────────


class TestJsExtractor:
    def test_regex_literal_desync_regression(self):
        """view_agent.js 实证回归钉：插值体内正则字面量（``/^[{[]/`` 形态，
        含 unbalanced brace/引号）不识别会让深度计数 desync → 扫描发散
        （分钟级假死）。本钉：含正则+注释+嵌套模板的语料在步数预算内
        收敛且 HTML 完整。"""
        js = textwrap.dedent("""
            export function pageAgent() {
              // 注释含 `backtick` 与 ${fake} 不入语料
              v.innerHTML = `<div id='a'><button>${t("send")}</button>
                ${body.match(/^\\s*\\[LLM[^\\]]*\\]\\s*/) ? `<p id='b'>ok</p>` : ""}</div>`;
              if (!/^[{[]/.test(body)) return null;
              const re2 = /'/;  // 引号形态正则——老扫描器在此吞掉后续模板
              v.innerHTML += `<span id='c'>tail</span>`;
            }
        """)
        corpus = _extract_js_html(js)
        # 三段模板语料齐备（正则不吞后续模板）
        assert "<div id='a'>" in corpus
        assert "<p id='b'>ok</p>" in corpus
        assert "<span id='c'>tail</span>" in corpus
        # 插值被 token 化（fake 不漏进语料）
        assert "${fake}" not in corpus
        assert "<button>i" in corpus

    def test_interpolation_unique_tokens_no_false_dup(self):
        """动态 id 唯一 token 化：两个 ``id='${x}'`` 不产假 dup_id。"""
        js = "f = `<input id='${x}'><input id='${y}'>`;"
        issues = audit_html_fragment(_extract_js_html(js), "t")
        assert [i for i in issues if i["kind"] == "dup_id"] == []

    def test_step_budget_fails_loudly_not_hang(self, monkeypatch):
        """步数熔断：预算调低后长输入响错不假死（熔断机制本体回归钉）。"""
        monkeypatch.setattr(sys.modules[__name__], "_STEP_BUDGET", 100)
        js = "`" + "a" * 500 + "<div>"
        with pytest.raises(_BudgetExceeded):
            _extract_js_html(js)


# ────────────────────────── 审计器六检查正负例 ──────────────────────────


class TestA11yChecks:
    @pytest.mark.parametrize("fragment,kind", [
        ("<h2>a</h2><h4>b</h4>", "heading_jump"),
        ("<img src='x.png'>", "img_alt_missing"),
        ("<button class='icon'></button>", "button_no_name"),
        ("<a name='x'>go</a>", "a_no_href"),
        ("<a href=''>go</a>", "a_no_href"),
        ("<div id='k'></div><span id='k'></span>", "dup_id"),
        ("<input id='q' placeholder='filter'>", "control_no_label"),
        ("<select id='s'><option>1</option></select>", "control_no_label"),
    ])
    def test_issue_detected(self, fragment, kind):
        issues = audit_html_fragment(fragment, "p")
        assert [i["kind"] for i in issues] == [kind], issues

    @pytest.mark.parametrize("fragment", [
        "<h2>a</h2><h3>b</h3><h2>c</h2>",        # 层级渐进/回升合法
        "<img src='x.png' alt='曲线'>",           # alt 在场
        "<button aria-label='关闭' class='icon'></button>",  # aria 名
        "<button title='关闭'></button>",          # title 名
        "<a href='#/runs'>go</a>",                # href 在场
        "<div id='k'></div><span id='j'></span>",  # id 唯一
        "<label for='q'>过滤</label><input id='q'>",  # label[for] 关联
        "<input type='hidden' id='h'>",           # hidden 豁免
        "<input type='submit' value='查询'>",      # submit 豁免
    ])
    def test_clean_fragment_no_issue(self, fragment):
        assert audit_html_fragment(fragment, "p") == []

    def test_interpolation_counts_as_accessible_name(self):
        """``${t(...)}`` 文本视同在场：i18n 按钮不误报无可达名（动态内容
        视同在场口径——语料 token 化后非空即有名）。"""
        js = "f = `<button class='minor'>${t('runs.clear')}</button>`;"
        issues = audit_html_fragment(_extract_js_html(js), "p")
        assert issues == []

    def test_label_for_resolved_when_label_comes_later(self):
        """label[for] 后置关联：label 在控件之后出现也能消解（全文收集）。"""
        fragment = "<input id='q'><label for='q'>过滤</label>"
        assert audit_html_fragment(fragment, "p") == []

    def test_real_view_corpora_extract_cleanly(self, client):
        """全 26+ 页语料非空（抽取器对真实视图模块零发散——agent 页正则
        desync 回归的项目级对照面）。"""
        routes = enumerate_view_routes(client.get("/static/pages.js").text)
        for key, fname in routes.items():
            src = client.get(f"/static/pages/{fname}").text
            corpus = _extract_js_html(src)
            assert len(corpus) > 200, f"{key} 语料塌缩（{len(corpus)} 字符）"

    def test_playwright_absence_form_declaration(self):
        """形态判定留痕：playwright 缺席 → 静态 a11y-lite 形态（任务书
        预置二选一如实判定；playwright 落地后本钉翻转即提示换真快照面）。"""
        try:
            import playwright  # noqa: F401
            found = True
        except ImportError:
            found = False
        assert found is False, (
            "venv 已装 playwright——本门应升级为真浏览器 a11y snapshot 形态"
            "（衔接点见本文件 docstring 逃生口节），静态语料抽取可退役")
