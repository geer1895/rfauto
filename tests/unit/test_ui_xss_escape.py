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
# aurora_d UI-R2（2026-10-14）：pages.js 拆分为薄入口 + pages/ 域模块（零构建
# ESM）——源码钉读"入口+全部域模块"并集，行为断言逐字不变（拆分前=单文件）。
def _pages_union_text() -> str:
    parts = [_STATIC / "pages.js"]
    parts += sorted((_STATIC / "pages").glob("*.js"))
    return "\n".join(p.read_text(encoding="utf-8") for p in parts)

_PAGES = _pages_union_text()

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
        src = _PAGES
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
        src = _PAGES
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
        src = _PAGES
        assert "window.DOMPurify" in src
        assert "mdSanitize(window.marked.parse(" in src

    def test_no_raw_api_interpolation_outside_exemption(self):
        r"""修后余量复查的机器可执行版（双向钉）：全文件扫裸 API 根变量插值
        `${var.field}`（var=API 响应对象命名惯例），命中必须逐一登记在豁免
        清单；豁免条目也必须仍能在源码命中（防清单腐烂）。豁免逐条理由见
        内部证据档 §余量：数字/布尔格式化、textContent/canvas/
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

        src = _PAGES
        raw = re.compile(
            r"\$\{\s*(?!escAttr\(|esc\()"
            r"(?!(?:JSON|Math|Object|S|T)\.)"
            r"[A-Za-z_$][\w$]*\.[\w.]+")
        hits = {m.group(0) for m in raw.finditer(src)}
        # 豁免清单（AU-4 修后余量，逐条已人工归因——详见审计文档 §余量）：
        exempt = set()
        # 1) 数字/布尔格式化（toFixed/length/count/坐标/统计量，无法携带标签）
        exempt |= {
            "${c.i", "${c.j",
            #    S2 发布令批：${c.n}/${c.n_feasible}/${c.mean_total_violation.toFixed}
            #    随 optstack 热图悬停行迁 t() params 退场（数值走 params 插值）
            #    ——豁免条目同笔删除（清偿闭环）。
            "${c.phi_deg", "${c.hpbw_deg",
            "${c.front_to_back_db", "${p.phi_deg", "${p.theta_deg", "${p.value",
            "${d.points.length", "${d.seed_sample_count", "${d.mesh_resolution_mm",
            #    发布令 i18n 批新增豁免（S1/S2/S4 迁移面，逐条归因）：
            #    ${r.has_sar}/${r.has_farfield_h5}=布尔条件字面量选择（" ·SAR"/
            #    t() 键），${rows.length}=textContent 赋值（非 HTML 模板），
            #    ${seg.level_db}=图表 series 名（非 DOM），${o.file}=series
            #    label 前缀（chart 数据面，非 DOM）——五处均非 HTML 注入位。
            "${r.has_sar", "${r.has_farfield_h5", "${rows.length",
            #    人性化二批 W3.5-K1 dashboard credibility 新面（同族豁免）：
            #    ${s.fams.length}/${s.nArb}=计数/枚举长度插值，非 HTML 注入位
            "${s.fams.length", "${s.nArb",
            "${seg.level_db", "${o.file",
            #    W2-S1 批 4：${d.expected_count}/${d.no_date_count} 随锚 KPI/
            #    无日期徽章迁 t() params 退场（${d.stale_count} 余 1 处=stale
            #    徽章，纯计数未迁）——同笔删除（清偿闭环）。
            "${d.count", "${d.stale_count",
            #    S2 发布令批：${d.cells.length}/${d.n_feasible_total}/
            #    ${d.n_pareto} 随 optstack 热图信息行/来源行迁 t() params 退场
            #    ——同笔删除；${d.n_trials_used/total} 余量=campaign 进度行（S3）。
            "${d.n_trials_used",
            "${d.n_trials_total",
            "${list.length", "${orig.length",
            #    aurora_f W8-S32 i18n 批 3：${d.n_without_cost 随 timeline 状态
            #    行迁词表 t() {n} 占位退场（计数=开发侧数值走 params 插值，
            #    不经模板裸插值面）——豁免条目同笔删除（本钉设计的清偿闭环）。
            #    aurora_g W2-S1 批 4：${d.expected_count}/${d.no_date_count}/
            #    ${si.age_days}/${stats.length} 随 anchors KPI/新鲜度徽章与
            #    uq 卡片计数迁 t() params 插值退场（同笔删除，清偿闭环同源）。
            "${work.length", "${trials.length",
            #    人性化二批 W2-S1：${ep.referee}=锚卡三元判定字面量
            #    （ep.referee ? A : B，枚举协议值非 API 数据注入；实际
            #    引擎名经 esc(anchorEngineName(...)) 单点转义消费）
            "${ep.referee",
            #    W6-S2 S 状态收编：run 总数计数插值原走 S.allRuns（S 根名
            #    在扫描排除集）——键降级模块级改名 _allRuns 后进扫描面，
            #    同笔迁入本清单（textContent 语境数字计数，语义不变）。
            "${_allRuns.length",
            "${r.n_draws",
            "${r.rho",
            "${iso.levels_db.join", "${iso.n_vertices", "${iso.n_faces",
            "${vol.shape.join", "${vol.frequency_ghz", "${vol.n_timesteps",
            "${t.freq_ghz", "${t.re", "${t.im", "${t.mag",
            "${t.z_re_ohm", "${t.z_im_ohm",
        }
        # 2) textContent / canvas / echarts 配置 / URL 语境（非 HTML sink）
        #    A7-A ui-kit 清理（2026-10-11）：${stats.map 随 uq 指标分布表迁
        #    kitTable(rowsHtml) 退场（map 移出模板插值面）。
        #    aurora_h W4-S1：${stats.* 五项随 agent 统计条迁 t() params 退场
        #    （t() 产出后仍走 textContent 单点，sink 语境不变）。
        exempt |= {
            "${val.model", "${val.template_hint", "${r.engine",
            "${r.has_variance", "${r.variance_note", "${r.honest_note",
            "${d.template", "${d.x_param", "${d.y_param",
            #    S2 发布令批：${d.source} 随 optstack 来源行迁 lead/计数
            #    params 拼接退场——同笔删除（${d.x_param/y_param} 余量=悬停
            #    行与 campaign 热图 aria 既有插值）。
            #    S2 发布令批：${d.constraint_names.join} 随 optstack 约束后缀
            #    迁 lead 词表段拼接退场——同笔删除。
            "${c.name", "${t.name", "${t.file", "${x.name", "${p.seriesName",
        }
        # 3) badge 系包裹（badge 内部 esc——参数里的 API 值已被转义）
        #    W2-S1 批 4：${si.age_days}/${d.no_date_count} 随锚新鲜度徽章迁
        #    t() params 退场（同笔删除）；余量=runs 湖 clamped 表+stale 徽章。
        #    S2 发布令批：${r.clamped.join} 随 playground 越界徽章迁 lead
        #    词表段拼接退场——同笔删除；${d.stale_count} 余量不变。
        exempt |= {"${d.stale_count"}
        # 4) 分派三元（分支全是静态字面量或已 esc/badge 包裹的 API 值）
        #    A7-A ui-kit 清理：${s.available 随求解器可用徽章迁 kitBoolBadge 退场。
        #    aurora_f W2-S5（R1 #8 三态批1）：${d.ok 随 sparams Smith 无产物
        #    分支拆 kitEmptyState/kitErrorPanel 退场——豁免条目同笔删除
        #   （本钉设计的清偿闭环，P8-11 钉面注记）。
        exempt |= {
            "${item.recipe",
            "${cs.milestone", "${m.detail", "${m.eta_gate.ok", "${it.parsed",
            "${p.filters", "${p.required", "${c.experimental", "${s.result",
            "${x.gt_unlocked", "${x.has_hf", "${x.visibility",
            "${a.engine_pair",
        }
        # 5) id 查找对（模板 id 与 T.$ 查找同用原始值，转义反而失配）
        exempt |= {"${s.axis"}
        # 6) 代码控制常量与 builder 中间量（sink 处已 esc）
        #    aurora_f W6-S21（2026-10-18）：${w.title 随 dashboard widget 标题
        #    迁注册表 tk 字段 t() 渲染期烘焙退场（t() 产出=开发侧可信文本，
        #    i18n.js 纪律头注在档；t( 前缀形态不在裸插值扫描口径内）——
        #    豁免条目同笔删除（本钉设计的清偿闭环）。
        exempt |= {"${p.bounds.join", "${val.optimization.params"}
        # 7) ge5 P2-2 反向扫描新增存量命中（26 处，2026-10-01 逐处源码归因）：
        #    7a) 数字格式化（toFixed/toPrecision/length/一元+强转）
        exempt |= {
            "${dv.toFixed", "${loocv.rho",
            #    S2 发布令批：${h.length}/${infeas.length} 随 optstack 超体积
            #    收敛行迁 t() params/前沿分系退场——同笔删除。
            # W8-S32 i18n 批 3：${pts.length 随 timeline 状态行迁词表 t() {n}
            # 占位退场（同笔删除，d.n_without_cost 条目注记同源）。
            "${names.length", "${q.value", "${s2.toFixed",
            "${xmax.toPrecision", "${xmin.toPrecision", "${ymax.toPrecision",
            "${ymin.toPrecision",
        }
        #    7b) textContent / canvas / echarts 配置 / T.msg 语境（非 HTML sink；
        #        T.msg 实现为 el.textContent，app.js L12-17）。
        #        W3-S12（P-5）：${slice.axis/${slice.position_mm 为场切片
        #        aria-label 插值——经 plotCard 壳 setAttribute("aria-label")
        #        赋值语境（属性赋值不解析 HTML，同 canvas/echarts 文本口径）。
        exempt |= {
            "${e.rho", "${e.run_id", "${e.verdict",
            #    S2 发布令批：${names.slice} 随 optstack hv 维数提示迁 lead/tail
            #    拼接退场（API 串照旧模板外拼）——同笔删除。
            "${slice.u_axis", "${slice.v_axis",
            "${slice.axis", "${slice.position_mm",
        }
        #    7c) esc/fmtCell 全包裹（数据表 cols.map：th=esc(c)、td=fmtCell）
        exempt |= {"${cols.map"}
        #    7d) 分派三元（两分支均为静态字面量/badge 内部转义）
        #    A7-A ui-kit 清理：${g.verdict 随校准详情 verdict 徽章迁
        #    kitVerdictBadge 退场（kit 前缀形态不在裸插值口径内）。
        exempt |= {"${listing.viz3d_available"}
        #    7e) id 查找对（/\W/g 清洗后的 chart 容器 id）
        exempt |= {"${f.replace"}
        # 7f) ge8b Wave B 服务受控字段面（席B2/B3 新页：画廊/仪表盘/profile/
        #     队列）——模板卡元数据/统计计数/成本数值/时长/平台枚举，全部来自
        #     后端受控 JSON（非自由用户输入）；自由文本出口经 esc 单源（钉上）。
        #     A7-A ui-kit 清理：${dl.map 随队列决策日志表迁 kitTable(rows=dl)
        #     退场（map 移出模板插值面）。
        exempt |= {
            "${body.join", "${c.f0_ghz", "${c.n_stages", "${c.preview",
            "${c.remote", "${c.scheduling", "${c.topology",
            "${cmax.toPrecision", "${cmin.toPrecision", "${d.best.cost",
            "${d.best.trial_number", "${d.cost_mean",
            "${d.params_source",
            "${d.table_rows", "${d.table_truncated", "${dl.length",
            "${m.initial", "${m.max", "${m.min", "${m.step",
            "${r.duration_s", "${r.fmt", "${r.output_path", "${r.rate_hz",
            "${s.license_gated", "${stages.map",
        }
        # aurora_f W1-S2（2026-10-18）：${d.n_campaigns}/${d.n_templates}/
        # ${d.n_previews} 三条随 i18n 试点迁 t(key, params) 渲染期烘焙
        # （view_queue info 行 / view_gallery 计数行）退场——豁免条目同笔
        # 删除（本钉设计的清偿闭环）。
        # aurora72 合流批（2026-10-12）：tools 页 A2-B/A3-A 落地的 15 处，逐条归因——
        # ①textContent/计数/维度数字（无法携带标签）：cals/groups/vis/nums/val.length、
        #   mat.rows/cols、g.items.length、groups.map（map 回调只产出组名字符串进 textContent 拼接）；
        # ②echarts 文本语境（tooltip formatter/系列名按文本渲染，载荷=服务端计算器结果的
        #   结构键名与数值矩阵，非用户输入面）：m.key/m.raw/mat.key/sub.title；
        # ③esc 已包裹的分派三元：r.y/r.error（真值分支均走 esc()）。
        #    aurora_g W2-S1 批 4：${groups.length}/${groups.map}/${mat.rows}/
        #    ${mat.cols}/${mat.key}/${val.length} 随帮助组清单/热图标签/结果
        #    单元格迁 t() params 退场（同笔删除）；${cals.length} 余 1 处=
        #    tool-count 计数行（纯数字，未迁）。
        exempt |= {
            "${cals.length", "${g.items.length",
            "${m.key", "${m.raw",
            "${nums.length", "${r.error",
            "${r.y", "${sub.title", "${vis.length",
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
