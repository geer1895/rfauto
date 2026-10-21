"""架构批 UI-R6 席位回归钉：pages/ 核心基础设施模块行为级 node 测试深化。

**模块覆盖清单（2026-10-14，UI-R2 拆分后 33 模块中的核心基础设施 + 2 视图）**

=========================  ==================================================  ==========================
模块                        本文件行为钉                                         先例钉（不重复面）
=========================  ==================================================  ==========================
pages/dom.js                esc/escAttr 全字符类+_amp_链+String 形参收敛；       test_ui_xss_escape
                            fmtNum 边界（负/大数/Infinity/串形参/负零/d=0）；    （五字符逐位+62 sink 面）；
                            errorText 失败信封文案回退链（UI-R11：errors→      test_ui_tables_sort
                            error→reason→兜底，cli _error_text 同款语义）；     （fmtNum 缺失+舍入）
                            markdown 净化单点（D-05）：mdSanitize/mdReady/
                            renderMarkdown 双路（stub DOMPurify 恶意串净化 /
                            缺失→textContent 拒 innerHTML）；help 壳模板
pages/sortable.js           纯函数三件补分支：稳定序（数值并列保自然序升/降）、   test_ui_tables_sort
                            降序（数值+字符串 collation）、多类型列回退           （三击循环/aria/refresh/
                            （数字列混入文本→字典序）、缺格行、null/undefined/    幂等挂载）
                            空串键语义（""→0 与 "-"→-∞ 的实测契约，见钉注）
pages/polling.js            进页即拉/定时器托管/_pollVisible 四守卫（元素缺失/    test_ui_lifecycle
                            display:none/标签页隐藏/换页）/隐藏暂停恢复立即拉/    （仅源码钉——行为面
                            终态停不复活/非终态停复活/非当前页不复活/重注册       本文件首补）
                            清旧定时器（桩 timer+visibility，免 jsdom）
pages/router.js             opener 注册表执行路：routeOpen true 路全链            test_ui_routing
                            （S.currentRunId+hash 编码回写+activate+VIEWS 渲染）、  （parseRoute 纯解析+
                            hash 同值幂等、arg 强转、campaign 待选消费即清、      注册表结构钉）
                            未知页 false 零副作用、tools opener、VIEWS 缺页
                            回落 dashboard、openCampaign("")→""（非 null）
pages/sse.js                连接级状态机转移表全分支（stub EventSource 真跑）：   test_ui_sse
                            订阅幂等门（存活/终态/空流/放弃态同会话拦+新闭包/     （纯函数转移表+
                            新 runId 放行）、onopen→live 让位轮询、原生错误       端点帧契约）
                            连续计数→gaveUp 收束、end 控制帧 terminal→done/
                            exists=false→empty（恢复可见清标记重探）、服务端
                            error 帧（MessageEvent）→close+末次刷新不弃订、
                            隐藏全收束/恢复复活（view 匹配+非 done/非 gaveUp）、
                            离页收束留档、无 EventSource 环境全链静默
pages/dashboard_util.js     阶梯精确边界（60s/1h/1d/30d 整点跳档）、新鲜度档      test_ui_dashboard_widgets
                            精确边界（1h→warn/24h→stale）、环弧钳值（warn 缘      （阶梯粗粒度+三档+
                            0.06 最小可见弧/none 0.08）、statusBucket 补值        XSS 零回声）
view_tools.js               表单校验原语 toolIsNumList 全分支（minLen/NaN/        test_ui_tools_page
                            ±∞/非数组/minLen 覆盖）+ A3-A 探测器全家：            （calcGroup/groupCalcList/
                            toolDetectCurves（平铺/轴名不当系列/等长过滤/         toolFilterMatch/
                            曲线族/嵌套递归前缀/识别不了如实[]/图表数帽）、       toolsDeepLinkKey）
                            toolDetectMatrix（数值方阵/复数方阵取模+raw/
                            两列点对不硬猜/复数非方阵不硬猜/ragged/超大帽）、
                            toolPickSweepMetric（扫参名排除/非标量排除）、
                            toolDescHasFormula（=与冒号双特征）、
                            toolResultCellText（诚实截断/矩阵标签/嵌套数组）

桩形态照 test_ui_a11y_rows 先例（桩 root/document 即 node 真执行，免 jsdom）；
polling/sse 桩 setInterval/clearInterval + visibilitychange 捕获；router 桩
location/history/T.activate/VIEWS；sse 桩 window.EventSource 类。每 pytest
用例一次独立 node 进程（ granular 失败定位，test_ui_charts_layer 同款）。

发现的契约注记（实测行为与模块注释的差异，如实钉住当前行为不改码）：
- sortCellKey("", true) 返回 0（+"")=0 有限）而非注释所称 -Infinity——
  "-" 占位（fmtNum 缺失语义）恒 -∞ 排最前不受影响；真空串格在数值列当 0，
  现网表格数值列无真空串（缺失走 "-"），休眠边缘，登记不改（纯测试席）。

不依赖 runs/、不读网络、不启动服务器；缺 node 诚实 skip；不 commit。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_NODE = shutil.which("node")


def _run_node_js(js: str) -> str:
    r = subprocess.run(
        [_NODE, "--input-type=module", "-e", js],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2500:]}"
    return r.stdout


def _payload(out: str) -> dict:
    """取 stdout 末行 JSON（胶水脚本单行 console.log(JSON.stringify(...)) 约定）。"""
    return json_loads(out.strip().splitlines()[-1])


def json_loads(s: str) -> dict:
    import json

    return json.loads(s)


def _node_check(name: str) -> None:
    r = subprocess.run([_NODE, "--check", str(_STATIC / "pages" / name)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"node --check {name}:\n{r.stderr[-2000:]}"


# ────────────────────────── 1. dom.js：转义/数值/净化单点 ──────────────────────────

@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestDomBehavior:
    def test_esc_escattr_full_charset_and_amp_chain(self):
        """五字符类逐位 + _amp_ 链不二次解码 + String() 形参收敛（escAttr 同口）。"""
        out = _run_node_js(
            "const d = await import('./pages/dom.js');\n"
            "const r = {};\n"
            "r.five = d.esc('&') + '|' + d.esc('<') + '|' + d.esc('>') + '|' +\n"
            "  d.esc('\"') + '|' + d.esc(\"'\");\n"
            "r.ampChain = d.esc('&amp;') + '|' + d.esc('&lt;'); // 实体原文不被解码\n"
            "r.mixed = d.esc('<img src=x onerror=alert(1)>');\n"
            "r.normal = d.esc('run_20260101_abc'); // 正常数据逐字节不变\n"
            "r.coerce = [d.esc(123), d.esc(null), d.esc(undefined), d.esc(1.5)];\n"
            "r.attrSame = ['&', '<', '>', '\"', \"'\", '混合<\"x>'].every(\n"
            "  (s) => d.escAttr(s) === d.esc(s));\n"
            "console.log(JSON.stringify(r));\n"
        )
        p = _payload(out)
        assert p["five"] == "&amp;|&lt;|&gt;|&quot;|&#39;"
        assert p["ampChain"] == "&amp;amp;|&amp;lt;"
        assert p["mixed"] == "&lt;img src=x onerror=alert(1)&gt;"
        assert p["normal"] == "run_20260101_abc"
        assert p["coerce"] == ["123", "null", "undefined", "1.5"]
        assert p["attrSame"] is True

    def test_fmtnum_boundaries(self):
        """负数/大数/Infinity/串形参/负零/d=0/缺省 4dp。"""
        out = _run_node_js(
            "const d = await import('./pages/dom.js');\n"
            "console.log(JSON.stringify({\n"
            "  neg: d.fmtNum(-3.14159),\n"
            "  big: d.fmtNum(1e21),\n"
            "  inf: d.fmtNum(Infinity),\n"
            "  ninf: d.fmtNum(-Infinity),\n"
            "  str: d.fmtNum('2.5'),\n"
            "  badstr: d.fmtNum('abc'),\n"
            "  negzero: d.fmtNum(-0, 2),\n"
            "  d0: d.fmtNum(5, 0),\n"
            "  tiny: d.fmtNum(-1e-7, 6),\n"
            "  zero: d.fmtNum(0),\n"
            "}));\n"
        )
        assert _payload(out) == {
            "neg": "-3.1416", "big": "1e+21", "inf": "Infinity",
            "ninf": "-Infinity", "str": "2.5000", "badstr": "-",
            "negzero": "0.00", "d0": "5", "tiny": "-0.000000", "zero": "0.0000",
        }

    def test_error_text_envelope_fallback_chain(self):
        """UI-R11（A6 P2-3）：失败信封文案单源 errorText——与
        cli/domains/anchors.py _error_text 同款语义（errors join "; " →
        error → reason → 兜底；前四分支与 test_cli_envelope_ratchet 钉值
        同源对齐），errors 空列表/缺 errors（单数 error 遗留形）与
        api() 网络兜底形状都可达，不再渲染 "undefined"。"""
        out = _run_node_js(
            "const d = await import('./pages/dom.js');\n"
            "console.log(JSON.stringify([\n"
            "  d.errorText({ ok: false, errors: ['a 错', 'b 错'] }),\n"
            "  d.errorText({ ok: false, error: '旧形' }),\n"
            "  d.errorText({ ok: false, reason: '跳过形' }),\n"
            "  d.errorText({ ok: false }),\n"
            "  d.errorText({ ok: false, errors: [], error: '空列表落回 error' }),\n"
            "  d.errorText(null),\n"
            "  d.errorText(undefined, '自定义兜底'),\n"
            "]));\n"
        )
        assert _payload(out) == [
            "a 错; b 错", "旧形", "跳过形", "未知错误",
            "空列表落回 error", "未知错误", "自定义兜底",
        ]

    def test_markdown_sanitize_single_point(self):
        """D-05：净化单点三分支——缺失拒 innerHTML（textContent 兜底+false）、
        在位恶意串净化、非串净化结果拒收。"""
        out = _run_node_js(
            "const d = await import('./pages/dom.js');\n"
            "const r = {};\n"
            "globalThis.window = {}; // 无 DOMPurify\n"
            "r.readyAbsent = d.mdReady();\n"
            "r.sanitizeAbsent = d.mdSanitize('<img onerror=x>');\n"
            "const el = { innerHTML: 'keep', textContent: '' };\n"
            "r.fallbackRet = d.renderMarkdown(el, '<b>hi</b>');\n"
            "r.fallbackText = el.textContent;\n"
            "r.innerHTMLUntouched = el.innerHTML; // 拒绝 innerHTML（D-05 硬错化）\n"
            "globalThis.window.DOMPurify = { sanitize: (h) =>\n"
            "  '<p>' + String(h).replace(/<[^>]*>/g, '') + '</p>' };\n"
            "r.readyOk = d.mdReady();\n"
            "const clean = d.mdSanitize(\n"
            "  '<script>alert(1)</script><b onclick=x>hi</b>');\n"
            "r.noScript = !clean.includes('<script');\n"
            "r.strippedTags = !clean.includes('<b');\n"
            "r.keptText = clean.includes('alert(1)hi');\n"
            "const el2 = { innerHTML: '', textContent: '' };\n"
            "r.cleanRet = d.renderMarkdown(el2, '<p>ok</p>');\n"
            "r.cleanHtml = el2.innerHTML;\n"
            "globalThis.window.DOMPurify = { sanitize: () => 42 };\n"
            "r.nonString = d.mdSanitize('x');\n"
            "globalThis.window.DOMPurify = { sanitize: 'nope' };\n"
            "r.notFn = d.mdReady();\n"
            "console.log(JSON.stringify(r));\n"
        )
        assert _payload(out) == {
            "readyAbsent": False, "sanitizeAbsent": None,
            "fallbackRet": False, "fallbackText": "<b>hi</b>",
            "innerHTMLUntouched": "keep", "readyOk": True,
            "noScript": True, "strippedTags": True, "keptText": True,
            "cleanRet": True, "cleanHtml": "<p>ok</p>",
            "nonString": None, "notFn": False,
        }

    def test_help_shell_template(self):
        out = _run_node_js(
            "const d = await import('./pages/dom.js');\n"
            "const h = d.help('<li>x</li>');\n"
            "console.log(JSON.stringify({ open: "
            "h.startsWith('<details class=\"help\"><summary>❓ 本页说明（点开查看）</summary>'),"
            " close: h.endsWith('</details>'), pass: h.includes('<li>x</li>') }));\n"
        )
        assert _payload(out) == {"open": True, "close": True, "pass": True}

    def test_node_check_dom(self):
        _node_check("dom.js")


# ────────────────────────── 2. sortable.js：纯函数补分支 ──────────────────────────

_SORTABLE_MK = """
function mkTable(head, rows) {
  const ths = head.map(() => ({ dataset: {}, style: {}, _aria: undefined, _click: null,
    setAttribute(n, v) { if (n === "aria-sort") this._aria = v; },
    removeAttribute(n) { if (n === "aria-sort") this._aria = undefined; },
    addEventListener(_t, f) { this._click = f; } }));
  const bodyRows = rows.map((cells) => ({
    cells: cells.map((t) => ({ textContent: t })), parentNode: null, _id: null }));
  const body = { rows: bodyRows,
    appendChild(tr) { const i = this.rows.indexOf(tr);
      if (i >= 0) this.rows.splice(i, 1); this.rows.push(tr); tr.parentNode = body; } };
  for (const r of bodyRows) r.parentNode = body;
  const table = { tHead: { rows: [{ cells: ths }] }, tBodies: [body], dataset: {} };
  return { table, ths, body };
}
"""


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestSortableBehavior:
    def test_stable_order_with_numeric_ties(self):
        """数值并列键：升序/降序均保持自然序（sort 稳定性契约——行点击监听
        随节点走，并列不抖动）。"""
        out = _run_node_js(
            "const p = await import('./pages/sortable.js');\n" + _SORTABLE_MK +
            "let s = mkTable(['v'], [['5'], ['1'], ['5'], ['1']]);\n"
            "s.body.rows.forEach((r, i) => { r._id = i; });\n"
            "p.makeSortable(s.table);\n"
            "s.ths[0]._click();\n"
            "const asc = s.body.rows.map((r) => r._id).join(',');\n"
            "s.ths[0]._click();\n"
            "const desc = s.body.rows.map((r) => r._id).join(',');\n"
            "console.log(JSON.stringify({ asc, desc }));\n"
        )
        assert _payload(out) == {"asc": "1,3,0,2", "desc": "0,2,1,3"}

    def test_desc_direction_numeric_and_string(self):
        """降序双形态：数值列反序 + 字符串列 collation 反序。"""
        out = _run_node_js(
            "const p = await import('./pages/sortable.js');\n" + _SORTABLE_MK +
            "let s = mkTable(['v'], [['-0.5'], ['-20.1'], ['-3.5']]);\n"
            "p.makeSortable(s.table); s.ths[0]._click(); s.ths[0]._click();\n"
            "const numDesc = s.body.rows.map((r) => r.cells[0].textContent).join(',');\n"
            "s = mkTable(['n'], [['b'], ['a'], ['c']]);\n"
            "p.makeSortable(s.table); s.ths[0]._click(); s.ths[0]._click();\n"
            "const strDesc = s.body.rows.map((r) => r.cells[0].textContent).join(',');\n"
            "console.log(JSON.stringify({ numDesc, strDesc }));\n"
        )
        assert _payload(out) == {"numDesc": "-0.5,-3.5,-20.1", "strDesc": "c,b,a"}

    def test_multi_type_column_falls_back_to_string(self):
        """多类型列（数值里混入文本）→ 整列回退字典序（numeric collation：
        '1'<'5'<'abc'），不臆测数值序。"""
        out = _run_node_js(
            "const p = await import('./pages/sortable.js');\n" + _SORTABLE_MK +
            "const mixedNum = p.columnIsNumeric(['1', 'abc', '5']);\n"
            "const s = mkTable(['v'], [['5'], ['abc'], ['1']]);\n"
            "p.makeSortable(s.table); s.ths[0]._click();\n"
            "const order = s.body.rows.map((r) => r.cells[0].textContent).join(',');\n"
            "console.log(JSON.stringify({ mixedNum, order }));\n"
        )
        assert _payload(out) == {"mixedNum": False, "order": "1,5,abc"}

    def test_missing_cell_and_nullish_keys(self):
        """缺格行（cells 短一行）与 null/undefined 格：字符串列缺格键=""
        排最前；数值列 null/undefined 格经 String(??'') 收敛。"""
        out = _run_node_js(
            "const p = await import('./pages/sortable.js');\n" + _SORTABLE_MK +
            "const s = mkTable(['a', 'b'], [['2', 'y'], ['1'], ['3', 'x']]);\n"
            "p.makeSortable(s.table); s.ths[1]._click();\n"
            "const missingFirst = s.body.rows.map((r) =>\n"
            "  r.cells[1] ? r.cells[1].textContent : '(none)').join(',');\n"
            "const numWithNullish = p.columnIsNumeric([null, undefined, '3']);\n"
            "const keyNullStr = p.sortCellKey(null, false);\n"
            "const dashIsNegInf = p.sortCellKey('-', true) === -Infinity;\n"
            "const emptyStrKey = p.sortCellKey('', true); // 实测契约：+''=0（非 -∞）\n"
            "console.log(JSON.stringify({ missingFirst, numWithNullish, keyNullStr,"
            " dashIsNegInf, emptyStrKey }));\n"
        )
        p = _payload(out)
        assert p == {
            "missingFirst": "(none),x,y", "numWithNullish": True,
            "keyNullStr": "", "dashIsNegInf": True, "emptyStrKey": 0,
        }, "sortCellKey 空串键语义漂移——见本文件 docstring 契约注记"

    def test_mount_sortable_tables_guards(self):
        """mountSortableTables：null/无 querySelectorAll root 零抛。"""
        out = _run_node_js(
            "const p = await import('./pages/sortable.js');\n"
            "p.mountSortableTables(null);\n"
            "p.mountSortableTables({});\n"
            "p.mountSortableTables({ querySelectorAll: () => [] });\n"
            "console.log(JSON.stringify('guards-ok'));\n"
        )
        assert _payload(out) == "guards-ok"

    def test_node_check_sortable(self):
        _node_check("sortable.js")


# ────────────────────────── 3. polling.js：轮询生命周期（桩 timer+visibility） ──────────────────────────

_POLL_SETUP = """
const ctx = await import('./pages/context.js');
const pol = await import('./pages/polling.js');
const views = {};
ctx.T.$ = (id) => views[id] || null;
globalThis.document = { visibilityState: 'visible', handlers: {},
  addEventListener(t, f) { this.handlers[t] = f; } };
let seq = 0; const timers = new Map();
globalThis.setInterval = (fn, ms) => { const id = ++seq; timers.set(id, { fn, ms }); return id; };
globalThis.clearInterval = (id) => { timers.delete(id); };
pol._bindVisibilityPolling();
const vis = document.handlers['visibilitychange'];
"""


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestPollingBehavior:
    def test_register_pulls_immediately_and_owns_timer(self):
        """进页即拉一次 + 定时器托管（重注册同名清旧定时器，不叠定时器）。"""
        out = _run_node_js(_POLL_SETUP +
            "const calls = [];\n"
            "pol._pollRegister('tune', 'tune', () => calls.push('a'), 3000);\n"
            "const afterFirst = { calls: calls.length, timers: timers.size };\n"
            "pol._pollRegister('tune', 'tune', () => calls.push('b'), 3000);\n"
            "console.log(JSON.stringify({ afterFirst, afterSecond:\n"
            "  { calls: calls.length, timers: timers.size } }));\n"
        )
        p = _payload(out)
        assert p["afterFirst"] == {"calls": 1, "timers": 1}, "进页必须立即拉一次"
        assert p["afterSecond"] == {"calls": 2, "timers": 1}, "重注册清旧定时器"

    def test_poll_visible_four_guards(self):
        """_pollVisible 四守卫：元素在+可见+标签页可见才 true。"""
        out = _run_node_js(_POLL_SETUP +
            "views['view-tune'] = { style: { display: '' } };\n"
            "const ok = pol._pollVisible('tune');\n"
            "views['view-tune'].style.display = 'none';\n"
            "const hiddenEl = pol._pollVisible('tune');\n"
            "views['view-tune'].style.display = '';\n"
            "document.visibilityState = 'hidden';\n"
            "const hiddenTab = pol._pollVisible('tune');\n"
            "document.visibilityState = 'visible';\n"
            "const missingEl = pol._pollVisible('nope');\n"
            "console.log(JSON.stringify({ ok, hiddenEl, hiddenTab, missingEl }));\n"
        )
        assert _payload(out) == {"ok": True, "hiddenEl": False,
                                 "hiddenTab": False, "missingEl": False}

    def test_visibility_pause_and_resume_with_immediate_pull(self):
        """隐藏暂停（定时器清、fn 保留）→ 恢复可见立即拉一次并重启定时器。"""
        out = _run_node_js(_POLL_SETUP +
            "ctx.setActiveView('tune');\n"
            "views['view-tune'] = { style: { display: '' } };\n"
            "const calls = [];\n"
            "pol._pollRegister('tune', 'tune', () => calls.push('t'), 3000);\n"
            "document.visibilityState = 'hidden'; vis();\n"
            "const paused = timers.size;\n"
            "document.visibilityState = 'visible'; vis();\n"
            "console.log(JSON.stringify({ paused, resumed: timers.size,\n"
            "  calls: calls.length }));\n"  # 1 进页拉 + 1 恢复拉
        )
        assert _payload(out) == {"paused": 0, "resumed": 1, "calls": 2}

    def test_terminal_stop_never_revives(self):
        """终态停（_pollStop(name, true) 清 fn）：恢复可见不得复活。"""
        out = _run_node_js(_POLL_SETUP +
            "ctx.setActiveView('tune');\n"
            "views['view-tune'] = { style: { display: '' } };\n"
            "const calls = [];\n"
            "pol._pollRegister('tune', 'tune', () => calls.push('t'), 3000);\n"
            "pol._pollStop('tune', true);\n"
            "document.visibilityState = 'hidden'; vis();\n"
            "document.visibilityState = 'visible'; vis();\n"
            "console.log(JSON.stringify({ timers: timers.size, calls: calls.length }));\n"
        )
        assert _payload(out) == {"timers": 0, "calls": 1}

    def test_nonterminal_stop_revives_on_resume_same_view_only(self):
        """非终态停保留 fn：同视图恢复复活；非当前页视图不复活。"""
        out = _run_node_js(_POLL_SETUP +
            "views['view-loopboard'] = { style: { display: '' } };\n"
            "views['view-runs'] = { style: { display: '' } };\n"
            "const calls = [];\n"
            "ctx.setActiveView('loopboard');\n"
            "pol._pollRegister('loop', 'loopboard', () => calls.push('l'), 4000);\n"
            "pol._pollStop('loop'); // 非终态：fn 保留\n"
            "document.visibilityState = 'hidden'; vis();\n"
            "document.visibilityState = 'visible'; vis();\n"
            "const revived = timers.size === 1 && calls.length === 2;\n"
            "// 非当前页：runs 页轮询在 loopboard 前台不复活\n"
            "pol._pollRegister('w', 'runs', () => calls.push('w'), 1000);\n"
            "pol._pollStop('w');\n"
            "document.visibilityState = 'hidden'; vis();\n"
            "document.visibilityState = 'visible'; vis();\n"
            "console.log(JSON.stringify({ revived, wrongViewNotRevived:\n"
            "  timers.size === 1, calls }));\n"
        )
        assert _payload(out) == {"revived": True, "wrongViewNotRevived": True,
                                 "calls": ["l", "l", "w", "l"]}
        # calls 溯源：l=进页拉、l=第一轮恢复复活、w=register 即拉（与恢复无关）、
        # l=第二轮恢复再复活（loop 非终态仍在册）——w 从未被恢复复活（视图不符）

    def test_node_check_polling(self):
        _node_check("polling.js")


# ────────────────────────── 4. router.js：opener 注册表执行路 ──────────────────────────

_ROUTER_SETUP = """
const ctx = await import('./pages/context.js');
const r = await import('./pages/router.js');
globalThis.location = { hash: '' };
const replaced = [];
globalThis.history = { replaceState: (a, b, u) => replaced.push(u) };
const activated = [];
ctx.T.activate = (v) => activated.push(v);
const rendered = [];
r.VIEWS.detail = (id) => rendered.push(['detail', id]);
r.VIEWS.campaign = (id) => rendered.push(['campaign', id]);
r.VIEWS.tools = (id) => rendered.push(['tools', id]);
r.VIEWS.dashboard = (id) => rendered.push(['dashboard', id]);
"""


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestRouterOpenerBehavior:
    def test_route_open_true_path_full_chain(self):
        """routeOpen('detail') true 路全链：S.currentRunId 单源写 + hash 编码
        回写（/ → %2F）+ activate + VIEWS 渲染 + activeView 落位。"""
        out = _run_node_js(_ROUTER_SETUP +
            "const ok = r.routeOpen('detail', 'run/1');\n"
            "console.log(JSON.stringify({ ok, cur: ctx.S.currentRunId,\n"
            "  hash: replaced[replaced.length - 1], act: ctx.getActiveView(),\n"
            "  activated, rendered }));\n"
        )
        assert _payload(out) == {
            "ok": True, "cur": "run/1", "hash": "#/detail/run%2F1",
            "act": "detail", "activated": ["detail"], "rendered": [["detail", "run/1"]],
        }

    def test_route_hash_write_idempotent_on_same_value(self):
        """同值 hash 不重写（replaceState 幂等——不与 hashchange 分发互激）。"""
        out = _run_node_js(_ROUTER_SETUP +
            "r.routeOpen('detail', 'run/1');\n"
            "globalThis.location.hash = '#/detail/run%2F1';\n"
            "const n = replaced.length;\n"
            "r.routeOpen('detail', 'run/1');\n"
            "console.log(JSON.stringify({ idempotent: replaced.length === n }));\n"
        )
        assert _payload(out) == {"idempotent": True}

    def test_arg_coerced_to_string(self):
        """非串 arg 强转 String（数字 run_id 深链同款）。"""
        out = _run_node_js(_ROUTER_SETUP +
            "r.routeOpen('detail', 123);\n"
            "console.log(JSON.stringify({ cur: ctx.S.currentRunId,\n"
            "  last: replaced[replaced.length - 1] }));\n"
        )
        assert _payload(out) == {"cur": "123", "last": "#/detail/123"}

    def test_campaign_pending_consume_clears(self):
        """campaign 待选 run_id：openCampaign 记待选 + 消费即清（二次消费 null）；
        空串待选消费回 ''（非 null——String(runId||'') 契约）。"""
        out = _run_node_js(_ROUTER_SETUP +
            "r.routeOpen('campaign', 'c1');\n"
            "const c1 = r.consumeCampaignPendingId();\n"
            "const c2 = r.consumeCampaignPendingId();\n"
            "r.openCampaign('');\n"
            "const empty = r.consumeCampaignPendingId();\n"
            "console.log(JSON.stringify({ c1, c2, empty,\n"
            "  act: ctx.getActiveView(), rendered: rendered[rendered.length - 1] }));\n"
        )
        assert _payload(out) == {"c1": "c1", "c2": None, "empty": "",
                                 "act": "campaign", "rendered": ["campaign", None]}

    def test_unknown_page_false_with_zero_side_effects(self):
        """未知页/未收参页：routeOpen false + 零激活零渲染（调用方回落裸页）。"""
        out = _run_node_js(_ROUTER_SETUP +
            "const actN = activated.length, renN = rendered.length;\n"
            "const a = r.routeOpen('runs', 'x');\n"
            "const b = r.routeOpen('__nope__', '');\n"
            "console.log(JSON.stringify({ a, b, noAct: activated.length === actN,\n"
            "  noRender: rendered.length === renN }));\n"
        )
        assert _payload(out) == {"a": False, "b": False, "noAct": True, "noRender": True}

    def test_tools_opener_and_missing_view_falls_back_dashboard(self):
        """tools opener 走 showPage('tools')；VIEWS 缺页回落 dashboard 渲染
        （showPage 的 VIEWS[v] || VIEWS.dashboard 契约）。"""
        out = _run_node_js(_ROUTER_SETUP +
            "ctx.setActiveView('dashboard');\n"
            "r.routeOpen('tools', 'albersheim_detection_snr');\n"
            "const act = ctx.getActiveView();\n"
            "delete r.VIEWS.tools;\n"
            "r.routeOpen('tools', 'k2');\n"
            "console.log(JSON.stringify({ act, activatedLast:\n"
            "  activated[activated.length - 1], fallback: rendered[rendered.length - 1] }));\n"
        )
        assert _payload(out) == {"act": "tools", "activatedLast": "tools",
                                 "fallback": ["dashboard", None]}

    def test_node_check_router(self):
        _node_check("router.js")


# ────────────────────────── 5. sse.js：连接级状态机（stub EventSource） ──────────────────────────

_SSE_SETUP = """
class FakeES {
  constructor(url) { this.url = url; this.readyState = 0; this.closed = false;
    this.handlers = {}; FakeES.created.push(this); }
  static created = [];
  addEventListener(t, f) { (this.handlers[t] = this.handlers[t] || []).push(f); }
  close() { this.closed = true; this.readyState = 2; }
  fire(t, ev) { (this.handlers[t] || []).forEach((f) => f(ev)); }
  open() { this.readyState = 1; if (this.onopen) this.onopen(); }
}
FakeES.created = [];
globalThis.window = { EventSource: FakeES };
window.EventSource.CLOSED = 2;
globalThis.document = { visibilityState: 'visible', handlers: {},
  addEventListener(t, f) { this.handlers[t] = f; } };
const ctx = await import('./pages/context.js');
const sse = await import('./pages/sse.js');
sse._bindVisibilitySSE();
const vis = document.handlers['visibilitychange'];
ctx.setActiveView('campaign');
"""


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestSseStateMachineBehavior:
    """UI-R9 后形态连接级转移表：gaveUp/重连/控制帧全分支（stub ES 真跑）。"""

    def test_full_state_machine(self):
        out = _run_node_js(_SSE_SETUP +
            "const rC = () => {}; const rC2 = () => {}; const rT = () => {}; const rX = () => {};\n"
            "const tCalls = []; const rfT = () => tCalls.push('t');\n"
            "const xCalls = []; const rfX = () => xCalls.push('x');\n"
            "// ① 订阅：URL 单源编码（/ → %2F）\n"
            "sse._sseSubscribe('campaign', 'run/1', rC, 'campaign');\n"
            "const es0 = FakeES.created[0];\n"
            "const url = es0.url;\n"
            "// ② 幂等门：同 runId+同闭包不重连\n"
            "sse._sseSubscribe('campaign', 'run/1', rC, 'campaign');\n"
            "const sameBlocked = FakeES.created.length === 1;\n"
            "// ③ onopen → live（轮询让位）+ errors 归零\n"
            "es0.open();\n"
            "const live = sse._SSE.campaign.live && sse.ssePollSuppressed(sse._SSE.campaign);\n"
            "// ④ 原生错误连续计数：2 次不弃订、live 翻 false（轮询接管）\n"
            "es0.fire('error', {}); es0.fire('error', {});\n"
            "const err2 = { n: sse._SSE.campaign.errors, gaveUp: sse._SSE.campaign.gaveUp,\n"
            "  alive: !es0.closed, liveOff: sse._SSE.campaign.live === false };\n"
            "// ⑤ 第 3 次连续 → gaveUp + close（重连永动机根治面）\n"
            "es0.fire('error', {});\n"
            "const gaveUp = sse._SSE.campaign.gaveUp && es0.closed &&\n"
            "  sse._SSE.campaign.es === null;\n"
            "// ⑥ gaveUp 同会话订阅拦；新闭包=显式重连放行且标记全重置\n"
            "sse._sseSubscribe('campaign', 'run/1', rC, 'campaign');\n"
            "const gaveUpBlocked = FakeES.created.length === 1;\n"
            "sse._sseSubscribe('campaign', 'run/1', rC2, 'campaign');\n"
            "const reconnect = FakeES.created.length === 2 &&\n"
            "  sse._SSE.campaign.gaveUp === false && sse._SSE.campaign.errors === 0;\n"
            "// ⑦ end 控制帧 terminal=true → done + close + 末次刷新 + 不复活\n"
            "sse._sseSubscribe('tune', 'r2', rfT, 'tune');\n"
            "const esT = FakeES.created[FakeES.created.length - 1];\n"
            "esT.fire('end', { data: '{\"terminal\": true, \"run_id\": \"r2\"}' });\n"
            "const doneMark = sse._SSE.tune.done === true && esT.closed &&\n"
            "  tCalls.length === 1;\n"
            "sse._sseSubscribe('tune', 'r2', rfT, 'tune');\n"
            "const doneBlocked = FakeES.created.length === 3;\n"
            "// ⑧ end exists=false → empty（会话内不热重试）+ 恢复可见清标记重探\n"
            "sse._sseSubscribe('x', 'r3', rfX, 'campaign');\n"
            "const esX = FakeES.created[FakeES.created.length - 1];\n"
            "esX.fire('end', { data: '{\"exists\": false}' });\n"
            "const emptyMark = sse._SSE.x.empty === true && xCalls.length === 1;\n"
            "const nBefore = FakeES.created.length;\n"
            "vis(); // 恢复可见（当前已 visible）：empty 清标记重探一次\n"
            "const emptyRetried = FakeES.created.length === nBefore + 1 &&\n"
            "  sse._SSE.x.empty === false;\n"
            "// ⑨ 服务端 error 帧（MessageEvent 有 data）→ close+末次刷新，非 gaveUp\n"
            "const esX2 = FakeES.created[FakeES.created.length - 1];\n"
            "esX2.fire('error', { data: '{\"detail\": \"read fail\"}' });\n"
            "const serverErr = esX2.closed && xCalls.length === 2 &&\n"
            "  !sse._SSE.x.gaveUp;\n"
            "// ⑩ 隐藏全收束；恢复按 view 匹配复活（done 不复活）\n"
            "document.visibilityState = 'hidden'; vis();\n"
            "const allClosed = !sse._SSE.campaign.es && !sse._SSE.x.es && !sse._SSE.tune.es;\n"
            "document.visibilityState = 'visible'; vis();\n"
            "const resumed = !!sse._SSE.campaign.es && !!sse._SSE.x.es &&\n"
            "  !sse._SSE.tune.es && sse._SSE.tune.done;\n"
            "// ⑪ gaveUp 恢复可见不复活（放弃后轮询常驻）\n"
            "const esC2 = sse._SSE.campaign.es;\n"
            "esC2.open(); esC2.readyState = 2; esC2.fire('error', {});\n"
            "const campGaveUp = sse._SSE.campaign.gaveUp && esC2.closed;\n"
            "document.visibilityState = 'hidden'; vis();\n"
            "document.visibilityState = 'visible'; vis();\n"
            "const gaveUpNotRevived = !sse._SSE.campaign.es;\n"
            "// ⑫ 离页收束他页订阅；同页订阅存活（runId/refresh 留档）\n"
            "const rR = () => {};\n"
            "sse._sseLeavePage('runs');\n"
            "const leftOthers = !sse._SSE.campaign.es && !sse._SSE.x.es;\n"
            "sse._sseSubscribe('lp', 'r4', rR, 'runs');\n"
            "const esLp = FakeES.created[FakeES.created.length - 1];\n"
            "sse._sseLeavePage('runs');\n"
            "const sameViewKept = !esLp.closed && sse._SSE.lp.es === esLp;\n"
            "console.log(JSON.stringify({ url, sameBlocked, live, err2, gaveUp,"
            " gaveUpBlocked, reconnect, doneMark, doneBlocked, emptyMark,"
            " emptyRetried, serverErr, allClosed, resumed, campGaveUp,"
            " gaveUpNotRevived, leftOthers, sameViewKept }));\n"
        )
        p = _payload(out)
        assert p["url"] == "/api/runs/run%2F1/events/stream"
        assert p["sameBlocked"] is True, "同 runId+同闭包必须幂等不重连"
        assert p["live"] is True, "onopen 翻 live 让位轮询"
        assert p["err2"] == {"n": 2, "gaveUp": False, "alive": True, "liveOff": True}
        assert p["gaveUp"] is True, "连续 3 次原生错误 → gaveUp + close"
        assert p["gaveUpBlocked"] is True, "gaveUp 同会话订阅拦（重连永动机根治）"
        assert p["reconnect"] is True, "新闭包=显式重连放行 + 标记全重置"
        assert p["doneMark"] is True, "end terminal → done + close + 末次刷新"
        assert p["doneBlocked"] is True, "done 会话内不复活"
        assert p["emptyMark"] is True, "end exists=false → empty 口径"
        assert p["emptyRetried"] is True, "empty 恢复可见清标记重探一次"
        assert p["serverErr"] is True, "服务端 error 帧 → close+刷新，非放弃"
        assert p["allClosed"] is True, "隐藏全收束"
        assert p["resumed"] is True, "恢复按 view 匹配复活；done 不复活"
        assert p["campGaveUp"] is True
        assert p["gaveUpNotRevived"] is True, "gaveUp 恢复可见不复活"
        assert p["leftOthers"] is True and p["sameViewKept"] is True

    def test_no_eventsource_environment_silent_noop(self):
        """EventSource 缺席（node 裸环境/老浏览器）：订阅全链静默跳过、
        状态表零残留（渐进增强零硬依赖）。"""
        out = _run_node_js(
            "globalThis.window = {}; // 无 EventSource\n"
            "globalThis.document = { visibilityState: 'visible', handlers: {},\n"
            "  addEventListener(t, f) { this.handlers[t] = f; } };\n"
            "const sse = await import('./pages/sse.js');\n"
            "sse._sseSubscribe('tune', 'r1', () => {}, 'tune');\n"
            "sse._sseLeavePage('x');\n"
            "sse._bindVisibilitySSE(); // document 在位：装配成功但流面静默\n"
            "console.log(JSON.stringify({ empty: Object.keys(sse._SSE).length === 0 }));\n"
        )
        assert _payload(out) == {"empty": True}

    def test_node_check_sse(self):
        _node_check("sse.js")


# ────────────────────────── 6. dashboard_util.js：阶梯/档位精确边界 ──────────────────────────

_DASH_NOW = 'const NOW = Date.parse("2026-10-11T12:00:00Z");\nconst iso = (ms) => new Date(ms).toISOString();\n'


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestDashboardUtilBoundaries:
    def test_reltime_exact_ladder_boundaries(self):
        """整点跳档契约：60s→1 分钟前、1h→1 小时前、1d→1 天前、30d 整点→
        绝对短日期（时区敏感，只钉格式）。"""
        out = _run_node_js(
            "const m = await import('./pages/dashboard_util.js');\n" + _DASH_NOW +
            "const r = {};\n"
            "r.s59 = m.relTime(iso(NOW - 59999), NOW);\n"
            "r.m60 = m.relTime(iso(NOW - 60000), NOW);\n"
            "r.m59 = m.relTime(iso(NOW - 59 * 60000), NOW);\n"
            "r.h1 = m.relTime(iso(NOW - 3600000), NOW);\n"
            "r.h23 = m.relTime(iso(NOW - 23 * 3600e3), NOW);\n"
            "r.d1 = m.relTime(iso(NOW - 86400000), NOW);\n"
            "r.d29 = m.relTime(iso(NOW - 29 * 86400e3 - 1), NOW);\n"
            "r.d30 = /^\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}$/.test(\n"
            "  m.relTime(iso(NOW - 30 * 86400e3), NOW));\n"
            "console.log(JSON.stringify(r));\n"
        )
        assert _payload(out) == {
            "s59": "刚刚", "m60": "1 分钟前", "m59": "59 分钟前", "h1": "1 小时前",
            "h23": "23 小时前", "d1": "1 天前", "d29": "29 天前", "d30": True,
        }

    def test_freshness_tier_exact_edges_and_ring_clamp(self):
        """档位精确边界（1h 整→warn、24h 整→stale）+ 环弧钳值（warn 缘
        0.06 最小可见弧；none 0.08）。"""
        out = _run_node_js(
            "const m = await import('./pages/dashboard_util.js');\n" + _DASH_NOW +
            "const t1h = m.freshnessTier(iso(NOW - 3600e3), NOW).tier;\n"
            "const t24h = m.freshnessTier(iso(NOW - 24 * 3600e3), NOW).tier;\n"
            "const dash = (svg) => svg.match(/stroke-dasharray=\"([^\"]+)\"/)[1];\n"
            "const warnEdge = dash(m.freshnessRingSvg(iso(NOW - 23.9 * 3600e3), NOW));\n"
            "const noneArc = dash(m.freshnessRingSvg(null, NOW));\n"
            "const freshArc = dash(m.freshnessRingSvg(iso(NOW - 60000), NOW));\n"
            "console.log(JSON.stringify({ t1h, t24h, warnEdge, noneArc, freshArc }));\n"
        )
        p = _payload(out)
        assert p["t1h"] == "warn" and p["t24h"] == "stale"
        assert p["warnEdge"] == "3.39 53.16", "warn 缘钳 0.06 最小可见弧"
        assert p["noneArc"] == "4.52 52.02", "none 档固定 0.08 弧"
        fresh = [float(x) for x in p["freshArc"].split()]
        # 1 分钟前 → frac≈1（24h 窗口几乎全鲜）：弧长 ≈ 周长 56.55
        assert fresh[0] > 56.0, f"新鲜档弧长应近满周: {p['freshArc']}"

    def test_status_bucket_supplementary_values(self):
        out = _run_node_js(
            "const m = await import('./pages/dashboard_util.js');\n"
            "console.log(JSON.stringify([m.statusBucket(null),\n"
            "  m.statusBucket('Solve_Failed'), m.statusBucket('imported'),\n"
            "  m.statusBucket('DONE')]));\n"
        )
        assert _payload(out) == ["other", "fail", "other", "pass"]

    def test_node_check_dashboard_util(self):
        _node_check("dashboard_util.js")


# ────────────────────────── 7. view_tools.js：表单校验原语 + 探测器全家 ──────────────────────────

@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestViewToolsDetectors:
    def test_tool_is_num_list_all_branches(self):
        """表单校验原语：全有限数值+长度 ≥minLen；NaN/±∞/字符串项/非数组
        全 false；minLen 覆盖。"""
        out = _run_node_js(
            "const t = await import('./pages/view_tools.js');\n"
            "console.log(JSON.stringify({\n"
            "  basic: t.toolIsNumList([1, 2]), single: t.toolIsNumList([1]),\n"
            "  empty: t.toolIsNumList([]), strItems: t.toolIsNumList(['a', 'b']),\n"
            "  nan: t.toolIsNumList([1, NaN]), inf: t.toolIsNumList([1, Infinity]),\n"
            "  ninf: t.toolIsNumList([-Infinity, 1]), nonArr: t.toolIsNumList('12'),\n"
            "  nullIn: t.toolIsNumList([1, null]), minLen1: t.toolIsNumList([7], 1),\n"
            "}));\n"
        )
        assert _payload(out) == {
            "basic": True, "single": False, "empty": False, "strItems": False,
            "nan": False, "inf": False, "ninf": False, "nonArr": False,
            "nullIn": False, "minLen1": True,
        }

    def test_tool_detect_curves_all_shapes(self):
        """曲线探测：平铺（轴名不当系列）/等长过滤/曲线族（dict_list 展开）/"""
        """嵌套递归（父键前缀）/识别不了如实 []/图表数帽 4。"""
        out = _run_node_js(
            "const t = await import('./pages/view_tools.js');\n"
            "const r = {};\n"
            "const flat = t.toolDetectCurves({ freq: [1, 2, 3], s11: [-1, -2, -3],\n"
            "  omega_norm: [0.1, 0.2, 0.3], note: 'txt' });\n"
            "r.flat = flat.map((c) => ({ title: c.title, xKey: c.xKey,\n"
            "  series: c.series.map((s) => s.name) }));\n"
            "r.lenMismatch = t.toolDetectCurves({ freq: [1, 2, 3], short: [1, 2] }).length;\n"
            "const fam = t.toolDetectCurves({ freq: [1, 2], modes: [\n"
            "  { mode: 'TE01', f_norm: [1, 2] }, { mode: 'TE11', f_norm: [3, 4] }] });\n"
            "r.family = fam.map((c) => ({ title: c.title,\n"
            "  series: c.series.map((s) => s.name) }));\n"
            "r.nested = t.toolDetectCurves({ outer: { x: [1, 2], y: [5, 6] } })\n"
            "  .map((c) => c.title);\n"
            "r.none = [t.toolDetectCurves({ a: 's' }).length,\n"
            "  t.toolDetectCurves([1, 2]).length, t.toolDetectCurves(null).length];\n"
            "const many = {};\n"
            "for (let i = 0; i < 6; i++) many['k' + i] = { x: [1, 2], y: [3, 4] };\n"
            "r.cap = t.toolDetectCurves(many).length;\n"
            "console.log(JSON.stringify(r));\n"
        )
        assert _payload(out) == {
            "flat": [{"title": "曲线（x=freq）", "xKey": "freq", "series": ["s11"]}],
            "lenMismatch": 0,
            "family": [{"title": "曲线族（x=freq）",
                        "series": ["TE01·f_norm", "TE11·f_norm"]}],
            "nested": ["outer：曲线（x=x）"],
            "none": [0, 0, 0],
            "cap": 4,
        }, "曲线探测形态漂移——轴名排除/族展开/嵌套前缀/帽值契约"

    def test_tool_detect_matrix_all_branches(self):
        """矩阵探测：数值方阵 / 两列点对不硬猜 / 复数方阵取模+raw 留痕 /
        复数非方阵不硬猜 / ragged / 超大帽（rows*cols>4096）。"""
        out = _run_node_js(
            "const t = await import('./pages/view_tools.js');\n"
            "const m1 = t.toolDetectMatrix({ K: [[1, 2, 3], [4, 5, 6], [7, 8, 9]] });\n"
            "const big = {};\n"
            "big.huge = Array.from({ length: 65 }, () => Array(65).fill(1)); // 4225 > 4096\n"
            "console.log(JSON.stringify({\n"
            "  plain: m1 && { key: m1.key, rows: m1.rows, cols: m1.cols,\n"
            "    complex: m1.complex, copied: m1.values[0][0] === 1 },\n"
            "  twoCol: t.toolDetectMatrix({ pts: [[1, 2], [3, 4]] }),\n"
            "  complex: (() => { const m = t.toolDetectMatrix(\n"
            "    { C: [[[1, -1], [0, 2]], [[0, 1], [2, 0]]] });\n"
            "    return m && { complex: m.complex, sq: m.rows === m.cols,\n"
            "      mods: m.values.flat(), hasRaw: Array.isArray(m.raw) }; })(),\n"
            "  cxRect: t.toolDetectMatrix({ x: [[[1, 0], [2, 0], [3, 0]],\n"
            "    [[4, 0], [5, 0], [6, 0]]] }),\n"
            "  ragged: t.toolDetectMatrix({ bad: [[1, 2, 3], [4, 5]] }),\n"
            "  huge: t.toolDetectMatrix(big),\n"
            "  scalar: t.toolDetectMatrix('nope'),\n"
            "}));\n"
        )
        p = _payload(out)
        assert p["plain"] == {"key": "K", "rows": 3, "cols": 3,
                              "complex": False, "copied": True}
        assert p["twoCol"] is None, "两列数值更像点对列表，不硬猜"
        assert p["complex"] == {"complex": True, "sq": True,
                                "mods": [1.4142135623730951, 2, 1, 2],
                                "hasRaw": True}
        assert p["cxRect"] is None, "复数非方阵不硬猜"
        assert p["ragged"] is None
        assert p["huge"] is None, "超大帽防病态渲染"
        assert p["scalar"] is None

    def test_tool_pick_sweep_metric_and_desc_and_cell(self):
        """扫参指标提取（扫参名排除+非标量排除）+ 公式特征（=与冒号双特征）
        + 单元格诚实折叠。"""
        out = _run_node_js(
            "const t = await import('./pages/view_tools.js');\n"
            "const pick = t.toolPickSweepMetric(\n"
            "  { w: 2, gain: 3.5, label: 'x', ok: true, arr: [1], bad: NaN }, 'w');\n"
            "console.log(JSON.stringify({\n"
            "  pick,\n"
            "  none: t.toolPickSweepMetric({ w: 2 }, 'w'),\n"
            "  empty: t.toolPickSweepMetric(null, 'w'),\n"
            "  f1: t.toolDescHasFormula('VSWR：用途：公式=(|Γ|+1)/(|Γ|-1)（出处）'),\n"
            "  f2: t.toolDescHasFormula('no formula'),\n"
            "  f3: t.toolDescHasFormula('a=b only'),\n"
            "  f4: t.toolDescHasFormula(null),\n"
            "  c1: t.toolResultCellText(null),\n"
            "  c2: t.toolResultCellText(3.5),\n"
            "  c3: t.toolResultCellText([1, 2]),\n"
            "  c4: t.toolResultCellText([[1, 2, 3], [4, 5, 6]]),\n"
            "  c5: t.toolResultCellText([[1, 2], [3]]),\n"
            "  c6: t.toolResultCellText({ a: 1 }),\n"
            "  c7: t.toolResultCellText([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]),\n"
            "}));\n"
        )
        assert _payload(out) == {
            "pick": {"key": "gain", "value": 3.5},
            "none": None, "empty": None,
            "f1": True, "f2": False, "f3": False, "f4": False,
            "c1": "null", "c2": "3.5", "c3": "1, 2", "c4": "[2×3 矩阵]",
            "c5": "[嵌套数组 2 行]", "c6": '{"a":1}',
            "c7": "1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12 …（共 15 项）",
        }

    def test_node_check_view_tools(self):
        _node_check("view_tools.js")


# ────────────────────────── 8. context.js：S 收编结构钉（W6-S2） ──────────────────────────

# R2 审计 §面2 / Top10 #1：S 收敛 {currentRunId} 单键（16 个单模块私有键
# 降级各视图模块级 let，行为等价搬家）；currentRunId 写面唯一=router.js
# （openRun 主入口 + noteCurrentRunId 旁路同步面）。

_S_KEYS_DOWNGRADED = {
    "view_agent": ["chatLog"],
    "view_dashboard": ["dashData", "widgetSet", "widgetSpan", "kpiPrev"],
    "view_sparams": ["spOverlay", "spRunId", "spMode"],
    "view_optstack": ["osRunId"],
    "view_fieldviz": ["fvDump", "ffRunId", "fvRunId"],
    "view_data": ["dsAll"],
    "view_runs": ["allRuns"],
    "view_gallery": ["galCards"],
    "view_campaign": ["cpRunId"],
}


def _src(name: str) -> str:
    return (_STATIC / "pages" / name).read_text(encoding="utf-8")


def _strip_js_comments(src: str) -> str:
    """字符级 JS 注释剥离（// 与 /* */，字符串字面量感知——头注里的
    "原 S.xxx" 契约注记不算代码引用）。"""
    out = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            while i < n and src[i] != "\n":
                i += 1
        elif c == "/" and nxt == "*":
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                i += 1
            i += 2
            out.append(" ")
        elif c in ("'", '"', "`"):
            q = c
            out.append(c)
            i += 1
            while i < n:
                if src[i] == "\\":
                    out.append(src[i:i + 2])
                    i += 2
                    continue
                out.append(src[i])
                if src[i] == q:
                    i += 1
                    break
                i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestSConsolidation:
    def test_s_collapsed_to_single_key(self):
        """S 收敛单键：context.js 声明 {currentRunId}，无历史键残留。"""
        out = _run_node_js(
            "const ctx = await import('./pages/context.js');\n"
            "console.log(JSON.stringify({ keys: Object.keys(ctx.S),\n"
            "  cur: ctx.S.currentRunId }));\n"
        )
        p = _payload(out)
        assert p == {"keys": ["currentRunId"], "cur": None}

    def test_write_face_unique_to_router(self):
        """写面唯一=router.js：全 pages/ 树 S.currentRunId 赋值语句只允许
        出现在 router.js（openRun + noteCurrentRunId 两处）；其他模块直写
        即红（含 view_detail 第二写点回潮；头注契约注记不算——注释剥离）。"""
        offenders = []
        for f in (_STATIC / "pages").glob("*.js"):
            if f.name == "router.js":
                continue
            body = _strip_js_comments(f.read_text(encoding="utf-8"))
            for i, line in enumerate(body.splitlines(), 1):
                if re.search(r"S\.currentRunId\s*=", line):
                    offenders.append(f"{f.name}:{i}")
        assert not offenders, f"S.currentRunId 写面越界（唯一=router.js）: {offenders}"

    def test_downgraded_keys_absent_from_s_and_module_let_present(self):
        """16 键降级双验：①原 S.<key> 代码引用在 pages/ 树清零（注释剥离
        后判定——头注"原 S.xxx"注记合法）；②各属主模块级 let 在位（行为
        等价搬家的落地面）。"""
        for mod, keys in _S_KEYS_DOWNGRADED.items():
            body = _strip_js_comments(_src(f"{mod}.js"))
            for k in keys:
                assert f"S.{k}" not in body, f"{mod}.js S.{k} 未降级（代码面）"
                assert re.search(rf"^let _{k}\b", body, re.M), \
                    f"{mod}.js 模块级 let _{k} 缺席"

    def test_s_import_dropped_where_no_shared_consumption(self):
        """降级后无共享键消费的属主模块 S 绑定移除；仍读 S.currentRunId 的
        模块（view_sparams/view_reports/view_detail/router）保 S 合法。"""
        for mod in ("view_agent", "view_dashboard", "view_data", "view_runs",
                    "view_gallery", "view_campaign", "view_optstack",
                    "view_fieldviz"):
            src = _src(f"{mod}.js")
            assert "import { S," not in src and "import { S }" not in src, \
                f"{mod}.js S 绑定应随降级移除（无共享键消费面）"
        for mod in ("view_sparams.js", "view_reports.js", "view_detail.js",
                    "router.js"):
            assert "S" in _src(mod), f"{mod} 共享键读者 S 绑定应保留"

    def test_detail_uses_router_note_path(self):
        """view_detail 显式 id 重渲经 noteCurrentRunId（router 转发面）——
        openRun 主链与页内直写两路径等价（R2 雷区表钉面）。"""
        detail = _src("view_detail.js")
        assert "noteCurrentRunId(id);" in detail
        assert "S.currentRunId = id;" not in detail
        router = _src("router.js")
        assert "export function noteCurrentRunId(runId)" in router
        assert "S.currentRunId = runId;" in router  # 写面在本模块

    def test_downgraded_modules_still_node_importable(self):
        """降级后各属主模块 node 裸 import 可测保持（R2 雷区表：模块级 let
        不得引入顶层 DOM 执行）。"""
        mods = ["context", "router", "view_detail", "view_agent",
                "view_dashboard", "view_data", "view_runs", "view_gallery",
                "view_campaign", "view_optstack", "view_sparams",
                "view_fieldviz"]
        out = _run_node_js(
            "const r = [];\n"
            + "".join(
                f"try {{ await import('./pages/{m}.js'); r.push('{m}:ok'); }}\n"
                f"catch (e) {{ r.push('{m}:FAIL ' + String(e).slice(0, 80)); }}\n"
                for m in mods)
            + "console.log(JSON.stringify(r));\n"
        )
        results = json_loads(out.strip().splitlines()[-1])
        bad = [x for x in results if "FAIL" in x]
        assert not bad, f"node 裸 import 破坏: {bad}"
        assert len(results) == len(mods)

    def test_context_contract_table_present(self):
        """键契约表（v8 P8-8 欠账补账）在 context.js 头注：S 唯一键属主 +
        16 降级键归属 + localStorage 键登记。"""
        ctx = _src("context.js")
        assert "键契约表" in ctx
        for token in ("currentRunId", "_chatLog", "_dashData", "_spOverlay",
                      "_osRunId", "_ffRunId", "_dsAll", "_allRuns",
                      "_galCards", "_cpRunId", "localStorage"):
            assert token in ctx, f"契约表缺 {token}"

    def test_node_check_context_router_detail(self):
        for name in ("context.js", "router.js", "view_detail.js",
                     "view_agent.js", "view_dashboard.js", "view_sparams.js",
                     "view_fieldviz.js"):
            _node_check(name)
