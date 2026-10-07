"""AU-4 XSS 清扫批行为钉（ui/static pages.js esc/escAttr 转义单源）。

两层钉：
1. **行为钉（node 真执行）**：node 可用时动态 import pages.js（ESM 语法
   检测，node >=22 默认开启），对 esc()/escAttr() 做 <>&"' 五字符逐位转义
   断言 + 代表性恶意插值串回归（`<img src=x onerror=alert(1)>` 进 → 转义
   文本出，无活性标签）。缺 node 时 skip（源码钉层仍生效）。
2. **源码钉（免 node）**：helper 单源存在且覆盖五字符；代表性 ①类插值面
   （fileBrowser 路径/文件名、提案 token、锚点表、数据集表、报告全文回退、
   chart/smith 错误消息）逐处走 esc/escAttr；app.js badge 单点内部转义；
   marked 主向量（mdSanitize+DOMPurify）未被本批破坏。

静态资源零构建直出：node --check 语法门由本文件 test_static_js_syntax 用
同一 node 探测承担（无 node 时跳过，语法由 CI/开发机 node 承担）。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_PAGES = _STATIC / "pages.js"
_APP = _STATIC / "app.js"

_NODE = shutil.which("node")

# 五字符逐位期望（& 必须最先替换，否则实体被二次转义——实现按单趟正则无此坑）
_PER_CHAR = [
    ("&", "&amp;"),
    ("<", "&lt;"),
    (">", "&gt;"),
    ('"', "&quot;"),
    ("'", "&#39;"),
]


def _run_node_js(js: str) -> str:
    """node 子进程跑一段 JS（stdout 返回；非零退出抛 AssertionError）。"""
    r = subprocess.run(
        [_NODE, "--input-type=module", "-e", js],
        capture_output=True, text=True, timeout=60,
        cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2000:]}"
    return r.stdout


class TestEscBehavioralNode:
    """esc/escAttr 行为钉：node 真执行 pages.js（动态 import）。"""

    @pytest.mark.skipif(_NODE is None, reason="本机无 node，行为钉退源码钉层")
    def test_esc_module_imports_and_exports(self):
        import json

        out = _run_node_js(
            "const m = await import('./pages.js');\n"
            "console.log(JSON.stringify([typeof m.esc, typeof m.escAttr]));"
        )
        assert json.loads(out.strip()) == ["function", "function"]

    @pytest.mark.skipif(_NODE is None, reason="本机无 node，行为钉退源码钉层")
    def test_esc_five_chars_bitwise(self):
        # 五字符逐位：单字符进 → 对应实体出（逐位断言，不打包）
        js = (
            "const { esc } = await import('./pages.js');\n"
            "const chars = ['&', '<', '>', '\"', \"'\"];\n"
            "const want = ['&amp;', '&lt;', '&gt;', '&quot;', '&#39;'];\n"
            "console.log(JSON.stringify(chars.map((c) => esc(c))));\n"
        )
        out = _run_node_js(js)
        assert __import__("json").loads(out.strip()) == [
            w for _, w in _PER_CHAR
        ]
        # 组合串逐位不变序
        js2 = (
            "const { esc } = await import('./pages.js');\n"
            'console.log(esc(String.raw`<a href="x">&\'</a>`));'
        )
        out2 = _run_node_js(js2)
        assert out2.strip() == "&lt;a href=&quot;x&quot;&gt;&amp;&#39;&lt;/a&gt;"

    @pytest.mark.skipif(_NODE is None, reason="本机无 node，行为钉退源码钉层")
    def test_escattr_matches_esc(self):
        out = _run_node_js(
            "const m = await import('./pages.js');\n"
            "const s = String.raw`<img src=x onerror=alert(1)> &\"'`;\n"
            "console.log(JSON.stringify([m.esc(s) === m.escAttr(s), m.escAttr(s)]));"
        )
        import json

        same, escaped = json.loads(out.strip())
        assert same is True  # 属性语境与文本语境同一五字符集
        assert "<" not in escaped and ">" not in escaped
        assert '"' not in escaped and "'" not in escaped
        assert "&amp;" in escaped

    @pytest.mark.skipif(_NODE is None, reason="本机无 node，行为钉退源码钉层")
    def test_malicious_interpolation_payload_is_inert_text(self):
        """代表性插值面回归：恶意串进 esc → 渲染出的是转义文本（无活性标签）。"""
        payloads = [
            "<img src=x onerror=alert(1)>",
            "<script>alert(1)</script>",
            '"><svg onload=alert(1)>',
            "'; DROP TABLE runs; -- & <b>bold</b>",
        ]
        js = (
            "const { esc } = await import('./pages.js');\n"
            'const ps = [\'<img src=x onerror=alert(1)>\', \'<script>alert(1)</script>\', '
            '"\\"><svg onload=alert(1)>", "\'; DROP TABLE runs; -- & <b>bold</b>"];\n'
            "console.log(JSON.stringify(ps.map((p) => esc(p))));"
        )
        import json

        for payload, escaped in zip(
            payloads, json.loads(_run_node_js(js).strip()), strict=True
        ):
            assert "<" not in escaped and ">" not in escaped
            assert '"' not in escaped and "'" not in escaped
            # 反转义回原串（实体↔字符一一对应）——渲染层 DOM 解码后视觉文本不变
            round_trip = (
                escaped.replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", '"').replace("&#39;", "'")
                .replace("&amp;", "&")
            )
            assert round_trip == payload

    @pytest.mark.skipif(_NODE is None, reason="本机无 node，行为钉退源码钉层")
    def test_esc_normal_data_is_byte_identical(self):
        """渲染不变铁律：不含五字符的正常数据逐字节不变。"""
        js = (
            "const { esc } = await import('./pages.js');\n"
            "const vals = ['wilkinson_power_divider', 'runs/20260101_000000_sp', "
            "'S11 (dB)', 42, 3.14159, true, null, undefined];\n"
            "console.log(JSON.stringify(vals.map((v) => esc(v))));"
        )
        import json

        assert json.loads(_run_node_js(js).strip()) == [
            "wilkinson_power_divider", "runs/20260101_000000_sp",
            "S11 (dB)", "42", "3.14159", "true", "null", "undefined",
        ]


class TestEscSourcePins:
    """源码钉（免 node）：单源 helper 存在 + ①类插值面逐处走转义。"""

    def test_helper_single_source_defined_and_exported(self):
        src = _PAGES.read_text(encoding="utf-8")
        # 单源：定义在 pages.js（五字符全转），app.js 经 import 复用
        assert "export function esc(" in src
        assert "export function escAttr(" in src
        for ent in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;"):
            assert ent in src, ent
        app = _APP.read_text(encoding="utf-8")
        assert 'import { initPages, showPage, esc } from "./pages.js"' in app

    def test_badge_escapes_internally_single_point(self):
        """badge 是 API 数据的 HTML 出口（run status/anchor 状态等），单点转义。"""
        app = _APP.read_text(encoding="utf-8")
        assert '${esc(text)}</span>`' in app

    def test_representative_interpolation_surfaces_escaped(self):
        src = _PAGES.read_text(encoding="utf-8")
        pins = {
            # 文件浏览器：路径属性 + 文件名文本（文件系统数据）
            'data-p="${escAttr(d.parent)}"': "fs 上级目录路径",
            'data-p="${escAttr(e.path)}"': "fs 条目路径",
            "${icon} ${esc(e.name)}": "fs 条目名",
            # run 历史/详情：API 字符串
            "<td>${esc(r.run_id || \"\")}</td>": "runs 行 run_id",
            "${esc(d.run_dir)}/${esc(f.path)}": "产物文件路径",
            # 收件箱提案：token 哈希 + 参数名/值
            "${escAttr(p.token_hash || \"\")}": "提案 token",
            # 报告中心：marked 缺装回退分支全文转义
            "`<pre>${esc(c.content)}</pre>`": "报告 md 回退",
            "`<pre>${esc(d.report_md)}</pre>`": "校准报告回退",
            # 错误消息面（e.message 可含任意文本）
            "smith error: ${esc(e.message)}": "smith 错误",
            "slice error: ${esc(e.message)}": "切片错误",
        }
        for needle, why in pins.items():
            assert needle in src, f"插值面未走转义：{why}（{needle}）"
        app = _APP.read_text(encoding="utf-8")
        assert "chart error: ${esc(e.message)}" in app, "图表错误面未走转义"

    def test_marked_main_vector_untouched(self):
        """marked+DOMPurify 主向量（218c5c9）未被本批破坏。"""
        src = _PAGES.read_text(encoding="utf-8")
        assert "window.DOMPurify" in src
        assert "mdSanitize(window.marked.parse(" in src

    def test_no_raw_api_interpolation_outside_exemption(self):
        r"""修后余量复查的机器可执行版（双向钉）：全文件扫裸 API 根变量插值
        `${var.field}`（var=API 响应对象命名惯例），命中必须逐一登记在豁免
        清单；豁免条目也必须仍能在源码命中（防清单腐烂）。豁免逐条理由见
        runs/au4_xss/xss_audit.md §余量：数字/布尔格式化、textContent/canvas/
        echarts 语境、badge 内部转义、esc 已包裹的分派三元、id 查找对。

        ge5 审查 P2-2 修复：扫描口径从"22 个白名单根名"改为**反向**——
        除安全函数/静态根（esc/escAttr 调用、JSON/Math/Object 全局、S/T
        静态表）外扫全部 `${var.field}` 形态，未来新增未列名根变量
        （如 `${resp.field}`）不再静默漏报；`\s*` 容许 `${` 后跨行。
        新增 26 处存量命中逐处人工归因（2026-10-01 源码复核：cols.map
        表头 esc/fmtCell 全包裹、run.cost 走 T.msg textContent、
        g.verdict/listing.viz3d_available 静态分支三元、其余数字格式化/
        textContent/echarts 配置/canvas）。"""
        import re

        src = _PAGES.read_text(encoding="utf-8")
        raw = re.compile(
            r"\$\{\s*(?!escAttr\(|esc\()"
            r"(?!(?:JSON|Math|Object|S|T)\.)"
            r"[A-Za-z_$][\w$]*\.[\w.]+")
        hits = {m.group(0) for m in raw.finditer(src)}
        # 豁免清单（AU-4 修后余量，逐条已人工归因——详见审计文档 §余量）：
        exempt = set()
        # 1) 数字/布尔格式化（toFixed/length/count/坐标/统计量，无法携带标签）
        exempt |= {
            "${c.i", "${c.j", "${c.n", "${c.n_feasible",
            "${c.mean_total_violation.toFixed", "${c.phi_deg", "${c.hpbw_deg",
            "${c.front_to_back_db", "${p.phi_deg", "${p.theta_deg", "${p.value",
            "${d.points.length", "${d.seed_sample_count", "${d.mesh_resolution_mm",
            "${d.count", "${d.expected_count", "${d.stale_count",
            "${d.no_date_count", "${d.cells.length", "${d.n_trials_used",
            "${d.n_trials_total", "${d.n_feasible_total", "${d.n_pareto",
            "${d.n_without_cost", "${list.length", "${orig.length",
            "${work.length", "${trials.length", "${stats.length",
            "${r.n_draws", "${r.nearest_sample.normalized_distance",
            "${r.rho", "${si.age_days",
            "${iso.levels_db.join", "${iso.n_vertices", "${iso.n_faces",
            "${vol.shape.join", "${vol.frequency_ghz", "${vol.n_timesteps",
            "${t.freq_ghz", "${t.re", "${t.im", "${t.mag",
            "${t.z_re_ohm", "${t.z_im_ohm",
        }
        # 2) textContent / canvas / echarts 配置 / URL 语境（非 HTML sink）
        exempt |= {
            "${val.model", "${val.template_hint", "${r.engine",
            "${r.has_variance", "${r.variance_note", "${r.honest_note",
            "${d.source", "${d.template", "${d.x_param", "${d.y_param",
            "${d.constraint_names.join", "${stats.turns", "${stats.llm_calls",
            "${stats.tool_calls", "${stats.prompt_tokens",
            "${stats.completion_tokens", "${stats.map",
            "${c.name", "${t.name", "${t.file", "${x.name", "${p.seriesName",
        }
        # 3) badge 系包裹（badge 内部 esc——参数里的 API 值已被转义）
        exempt |= {"${r.clamped.join", "${si.age_days", "${d.stale_count",
                   "${d.no_date_count"}
        # 4) 分派三元（分支全是静态字面量或已 esc/badge 包裹的 API 值）
        exempt |= {
            "${d.ok", "${d.warning", "${s.available", "${item.recipe",
            "${cs.milestone", "${m.detail", "${m.eta_gate.ok", "${it.parsed",
            "${p.filters", "${p.required", "${c.experimental", "${s.result",
            "${x.gt_unlocked", "${x.has_hf", "${x.visibility",
            "${r.has_sar", "${r.has_farfield_h5", "${r.recipe_path",
            "${a.engine_pair",
        }
        # 5) id 查找对（模板 id 与 T.$ 查找同用原始值，转义反而失配）
        exempt |= {"${s.axis"}
        # 6) 代码控制常量（WIDGETS 注册表标题）与 builder 中间量（sink 处已 esc）
        exempt |= {"${w.title", "${p.bounds.join", "${val.optimization.params"}
        # 7) ge5 P2-2 反向扫描新增存量命中（26 处，2026-10-01 逐处源码归因）：
        #    7a) 数字格式化（toFixed/toPrecision/length/一元+强转）
        exempt |= {
            "${dv.toFixed", "${h.length", "${infeas.length", "${loocv.rho",
            "${names.length", "${pts.length", "${q.value", "${s2.toFixed",
            "${xmax.toPrecision", "${xmin.toPrecision", "${ymax.toPrecision",
            "${ymin.toPrecision",
        }
        #    7b) textContent / canvas / echarts 配置 / T.msg 语境（非 HTML sink；
        #        T.msg 实现为 el.textContent，app.js L12-17）
        exempt |= {
            "${e.rho", "${e.run_id", "${e.verdict", "${names.slice",
            "${o.file", "${rows.length", "${run.cost", "${seg.level_db",
            "${slice.u_axis", "${slice.v_axis",
        }
        #    7c) esc/fmtCell 全包裹（数据表 cols.map：th=esc(c)、td=fmtCell）
        exempt |= {"${cols.map"}
        #    7d) 分派三元（两分支均为静态字面量/badge 内部转义）
        exempt |= {"${g.verdict", "${listing.viz3d_available"}
        #    7e) id 查找对（\W/g 清洗后的 chart 容器 id）
        exempt |= {"${f.replace"}
        # 7f) ge8b Wave B 服务受控字段面（席B2/B3 新页：画廊/仪表盘/profile/
        #     队列）——模板卡元数据/统计计数/成本数值/时长/平台枚举，全部来自
        #     后端受控 JSON（非自由用户输入）；自由文本出口经 esc 单源（钉上）。
        exempt |= {
            "${body.join", "${c.f0_ghz", "${c.n_stages", "${c.preview",
            "${c.remote", "${c.scheduling", "${c.topology",
            "${cmax.toPrecision", "${cmin.toPrecision", "${d.best.cost",
            "${d.best.trial_number", "${d.cost_mean", "${d.n_campaigns",
            "${d.n_previews", "${d.n_templates", "${d.params_source",
            "${d.table_rows", "${d.table_truncated", "${dl.length",
            "${dl.map", "${m.initial", "${m.max", "${m.min", "${m.step",
            "${r.duration_s", "${r.fmt", "${r.output_path", "${r.rate_hz",
            "${s.license_gated", "${stages.map",
        }
        unregistered = hits - exempt
        stale = exempt - hits
        assert not unregistered, f"发现未登记的裸 API 插值: {sorted(unregistered)}"
        assert not stale, f"豁免清单已腐烂（源码不再命中）: {sorted(stale)}"


class TestStaticJsSyntaxGate:
    """零构建直出：node --check 语法门（有 node 时硬门，无 node 跳过）。"""

    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    @pytest.mark.parametrize(
        "name", ["pages.js", "app.js", "palette.js", "plotcard.js"])
    def test_node_check_passes(self, name):
        r = subprocess.run(
            [_NODE, "--check", str(_STATIC / name)],
            capture_output=True, text=True, timeout=60,
        )
        assert r.returncode == 0, f"node --check {name} 失败:\n{r.stderr[-2000:]}"
