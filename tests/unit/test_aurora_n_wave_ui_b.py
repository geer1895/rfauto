"""aurora_n wave_ui_b 席位回归钉：前端引导线 B 席四件（新手动线可点击化）。

对应 runs/aurora_n/ui_recon/TOUR_FINDINGS.md 组 B 条目：

- P2-1 总览「快速开始」四步卡可点击化：wQuickLinks 此前纯文本零 button/a
  （guide-flow 内 [data-v] 计数=0，新手第一屏无行动入口）。修法（首访导览
  三步卡同款单源形态）：每步卡 data-go 跳对应页 + kitClickRowAttrs 三件套
  （role=button/tabindex/aria）+ bindClickRows（click 与 Enter/Space 同一
  激活）；hover 手势=既有 div.clickable 光标态（零新 CSS——index.html 本席
  禁改）。指南页「5 分钟上手路线」四步卡同笔（g-steps-flow 容器）。

- P2-2 Run 详情页（26 页中唯一无「本页说明」）：
  * 补 help 壳（文案具体到按钮名/区域，对齐既有 25 页形态）；
  * metrics.json 全量载荷区块化：/api/runs/<id> 的 metrics 字段=落盘全文
    （params/metrics/cost/checks/diagnosis 嵌套包），此前整包直进
    metricBadgeHtml——诊断建议（R002「S11 谐振频率偏高」+hint「检查馈电位
    置是否过短」）埋在单行 JSON 里=对新手不存在，且词典查顶层键恒未命中
    （38 键 metric_glossary tooltip 从未挂上）。修法：splitMetricPayload
    形态判别 + diagCardsHtml 诊断卡（徽章 rule_id·severity+现象+指标门限
    +建议）+ checksBadgesHtml 物理校验徽章 + detailMetricsHtml 总装（内层
    指标键接 glossary tooltip——基建现成，命中即挂）。平铺旧档退化为原
    指标徽章行（行为面不回退）。

- P2-5 CLI 报错下一步指针：``rfauto run definitely_missing.yaml`` 此前只说
  原因不指路（hints 规则表无该指纹、human 失败分支未消费 hints）。修法：
  ① hint_rules 增「配方文件不存在」指纹（内置配方 recipes/ 指路 + getting
  -started 锚，severity=info）；② _core._print_next_steps_stderr——与既有
  _print_error_hints_text 同规则表单源，差异=输出走 stderr（stdout 红字/
  JSON 信封消费面零污染）+行首「下一步: 」；挂 run/dry-run human 失败分支。

变异验证（移除修复必红，开发期逐钉实测并记录于本文件尾注）：源码钉关键串
即修复本体（删除即断言红）；node 行为钉消费导出纯函数（删除导出即 import
undefined 红）；CLI 行为钉走真 CliRunner/直接函数调用（摘除挂接即红）。

不依赖 runs/ 真实湖、不读网络、不启动服务器；node 面缺 node 诚实 skip；
不 commit。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_NODE = shutil.which("node")


def _src(name: str) -> str:
    return (_STATIC / "pages" / name).read_text(encoding="utf-8")


def _run_node_js(js: str) -> dict:
    r = subprocess.run(
        [_NODE, "--input-type=module", "-e", js],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2500:]}"
    return json.loads(r.stdout.strip().splitlines()[-1])


# ────────────────────────── P2-1 快速开始/五分钟步骤卡 ──────────────────────────


def _wquicklinks_body() -> str:
    import re

    src = _src("view_dashboard.js")
    m = re.search(r"async function wQuickLinks\(el\) \{(.*?)\n  \}", src, re.S)
    assert m, "wQuickLinks 函数体缺失"
    return m.group(1)


class TestQuickLinksClickable:
    def test_dashboard_steps_have_data_go_and_kit_attrs(self):
        """四步卡=data-go 跳页（steps 数组四页 id：import/recipe/tune/runs，
        模板 data-go='${go}'）+ kitClickRowAttrs aria（ql_step_aria_tpl 整句
        键）+ clickable 类（hover 光标态既有单源）。"""
        body = _wquicklinks_body()
        assert "data-go='${go}'" in body, "步卡模板缺 data-go 绑定"
        for go in ("import", "recipe", "tune", "runs"):
            assert f'["{go}", t("nav.' in body, f"steps 数组缺页 id {go}"
        # 四步共用单条 map 模板（kitClickRowAttrs 单点——非四份展开）
        assert body.count("kitClickRowAttrs(") == 1
        assert 't("dashboard.ql_step_aria_tpl"' in body
        assert "class='guide-step clickable'" in body

    def test_dashboard_steps_bind_click_rows_showpage(self):
        """接线=bindClickRows 单源（click 与 Enter/Space 同一激活）→
        showPage(row.dataset.go)（router 跳页单入口，hash 同步随之）。"""
        body = _wquicklinks_body()
        assert 'bindClickRows(el, (row) => showPage(row.dataset.go), "[data-go]")' in body

    def test_guide_steps_clickable_same_form(self):
        """指南页五分钟上手：g-steps-flow 容器 + 四步卡 data-go + kit 三件套
        + bindClickRows（dashboard 同款形态；与 _bindToc 的 a[data-goto]
        委托互不重叠——选择器域不同）。"""
        src = _src("view_guide.js")
        assert "id='g-steps-flow'" in src
        for go in ("import", "recipe", "tune", "runs"):
            assert f"data-go='{go}'" in src, f"指南步骤 {go} 缺 data-go"
        assert src.count('t("guide.step_open_tpl"') == 4
        assert "class='guide-step clickable'" in src
        assert 'bindClickRows(flow, (row) => showPage(row.dataset.go), "[data-go]")' in src
        # kit 形态 import 在位（router 无环：router 不 import view_guide）
        assert 'import { bindClickRows, kitClickRowAttrs } from "./kit.js";' in src
        assert 'import { showPage } from "./router.js";' in src

    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_guide_module_imports_clean_with_router(self):
        """view_guide（+router 链）node 裸 import 零环零顶层爆炸。"""
        out = _run_node_js(
            "const g = await import('./pages/view_guide.js');\n"
            "const r = await import('./pages/router.js');\n"
            "console.log(JSON.stringify({"
            "guide: typeof g.pageGuide, showPage: typeof r.showPage}));\n"
        )
        assert out == {"guide": "function", "showPage": "function"}

    def test_i18n_step_aria_keys_paired(self):
        """新 aria 键 zh/en 双语齐全且被两页引用（键集互证同笔）。"""
        i18n = _src("i18n.js")
        for key in ("dashboard.ql_step_aria_tpl", "guide.step_open_tpl"):
            assert f'"{key}"' in i18n, f"i18n 缺键 {key}"
        assert "dashboard.ql_step_aria_tpl" in _src("view_dashboard.js")
        assert "guide.step_open_tpl" in _src("view_guide.js")


# ────────────────────────── P2-2 Run 详情页三件 ──────────────────────────


class TestDetailHelpShell:
    def test_help_shell_present_with_four_items(self):
        """详情页补 help 壳（26 页收尾）：help() 四条+文案键（具体到按钮名
        ——「一键查看诊断」/图例点击/产物清单与既有 25 页形态对齐）。"""
        src = _src("view_detail.js")
        assert "import { esc, escAttr, help }" in src
        for key in ("detail.help_1", "detail.help_2", "detail.help_3",
                    "detail.help_4"):
            assert f't("{key}")' in src
            assert f'"{key}"' in _src("i18n.js")

    def test_help_copy_names_concrete_buttons(self):
        """文案具体性钉：帮助正文提及本页真实控件名（防退化成空话）。"""
        i18n = _src("i18n.js")
        assert "一键查看诊断" in i18n  # help_2 提及失败 run 真实按钮
        assert "产物清单" in i18n      # help_4 提及底部真实面板


_PAYLOAD_JS = (
    "const payload = { run_id: 'r1', plugin_version: 'schema1', schema_version: 1,\n"
    "  params: { f0_ghz: 2.4, z0_ohm: 50 },\n"
    "  metrics: { s11_db_max_in_band: -8.083476465503841 },\n"
    "  cost: 1.234,\n"
    "  checks: { passivity_ok: true, reciprocity_ok: false, sanity_all_ok: true,\n"
    "    sanity_notes: ['note<b>'] },\n"
    "  diagnosis: { ok: true, diagnoses: [ { rule_id: 'R002',\n"
    "    description: 'S11 谐振频率偏高', hint: '检查馈电位置是否过短',\n"
    "    severity: 'warning', metric: 's11_db_max_in_band',\n"
    "    value: -8.083476465503841, threshold: -10 } ],\n"
    "    suggestions: ['检查馈电位置是否过短'], initial_values: {}, rules_applied: 2 } };\n"
)


class TestDetailMetricsBlocks:
    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_split_payload_nested_and_flat(self):
        """形态判别：嵌套形态拆内层四件；平铺旧档（无嵌套 metrics 键）原样
        当指标面且 params/checks/diagnosis 如实缺席（不猜）。"""
        out = _run_node_js(
            "const m = await import('./pages/view_detail.js');\n"
            + _PAYLOAD_JS +
            "const p = m.splitMetricPayload(payload);\n"
            "const flat = m.splitMetricPayload({ s11_db_max_in_band: -12, cost: 0.5 });\n"
            "const r = {};\n"
            "r.nestedMetrics = Object.keys(p.metrics).join(',');\n"
            "r.cost = p.cost;\n"
            "r.params = Object.keys(p.params).join(',');\n"
            "r.diag = !!p.diagnosis;\n"
            "r.flatMetrics = Object.keys(flat.metrics).join(',');\n"
            "r.flatAbsent = flat.params === null && flat.checks === null"
            " && flat.diagnosis === null && flat.cost === null;\n"
            "r.badInput = Object.keys(m.splitMetricPayload(null).metrics).length === 0;\n"
            "console.log(JSON.stringify(r));\n"
        )
        assert out == {
            "nestedMetrics": "s11_db_max_in_band", "cost": 1.234,
            "params": "f0_ghz,z0_ohm", "diag": True,
            "flatMetrics": "s11_db_max_in_band,cost", "flatAbsent": True,
            "badInput": True,
        }

    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_diagnosis_cards_readable_and_honest(self):
        """诊断卡=可读四件（规则徽章/现象/指标门限/建议）；空与缺席=空串
        如实不出卡（不硬凑）。"""
        out = _run_node_js(
            "const m = await import('./pages/view_detail.js');\n"
            + _PAYLOAD_JS +
            "const cards = m.diagCardsHtml(payload.diagnosis);\n"
            "const r = {};\n"
            "r.rule = cards.includes('R002');\n"
            "r.desc = cards.includes('S11 谐振频率偏高');\n"
            "r.gate = cards.includes('门限 -10');\n"
            "r.hint = cards.includes('检查馈电位置是否过短');\n"
            "r.warnCls = cards.includes('badge warn');\n"
            "r.emptyNull = m.diagCardsHtml(null) === '';\n"
            "r.emptyNone = m.diagCardsHtml({}) === '';\n"
            "r.emptyZero = m.diagCardsHtml({ diagnoses: [] }) === '';\n"
            "r.plainNoGate = m.diagCardsHtml({ diagnoses: [{ rule_id: 'R004',"
            " description: 'd', hint: 'h', severity: 'error', metric: 'passivity_ok',"
            " value: false }] }).includes('badge err')\n"
            "  && !m.diagCardsHtml({ diagnoses: [{ rule_id: 'R004', severity: 'error' }]"
            " }).includes('指标');\n"
            "console.log(JSON.stringify(r));\n"
        )
        assert out == {
            "rule": True, "desc": True, "gate": True, "hint": True,
            "warnCls": True, "emptyNull": True, "emptyNone": True,
            "emptyZero": True, "plainNoGate": True,
        }

    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_diagnosis_cards_xss_escaped(self):
        """诊断内容是 API 数据：标签/引号注入 esc 单点转义（XSS 反向扫描
        同口径——注入面零新增）。"""
        out = _run_node_js(
            "const m = await import('./pages/view_detail.js');\n"
            "const x = m.diagCardsHtml({ diagnoses: [{ rule_id: 'R<X>',"
            " description: '<img src=x onerror=alert(1)>',"
            " hint: '\" onmouseover=\"a', severity: 'error',"
            " metric: 'm', value: 1, threshold: 0 }] });\n"
            "const r = {};\n"
            "r.noImg = !x.includes('<img src=x');\n"
            "r.noQuote = !x.includes('\" onmouseover');\n"
            "r.escaped = x.includes('&lt;img') && x.includes('&quot;');\n"
            "console.log(JSON.stringify(r));\n"
        )
        assert out == {"noImg": True, "noQuote": True, "escaped": True}

    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_checks_badges_and_notes(self):
        """物理校验行：布尔→ok/err 徽章（已知键词表标签，未知键原样键名
        不猜）；sanity_notes 摘要尾行 esc。"""
        out = _run_node_js(
            "const m = await import('./pages/view_detail.js');\n"
            + _PAYLOAD_JS +
            "const cb = m.checksBadgesHtml(payload.checks);\n"
            "const r = {};\n"
            "r.okN = (cb.match(/badge ok/g) || []).length;\n"
            "r.errN = (cb.match(/badge err/g) || []).length;\n"
            "r.notesEscaped = cb.includes('note&lt;b&gt;');\n"
            "r.unknownKeyRaw = m.checksBadgesHtml({ weird_flag: true })"
            ".includes('weird_flag');\n"
            "r.empty = m.checksBadgesHtml(null) === '';\n"
            "console.log(JSON.stringify(r));\n"
        )
        assert out == {"okN": 2, "errN": 1, "notesEscaped": True,
                       "unknownKeyRaw": True, "empty": True}

    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_head_assembly_glossary_hits_inner_metric_keys(self):
        """总装钉（P2-2 指标键 tooltip 接线）：内层指标键（s11_db_max_in_band）
        查词典命中→徽章外包 m-tip data-tip（38 键基建挂上）；params 徽章零
        词典面；诊断卡与区块小标题在位；平铺旧档退化为纯徽章行。"""
        out = _run_node_js(
            "const m = await import('./pages/view_detail.js');\n"
            + _PAYLOAD_JS +
            "const glossary = { s11_db_max_in_band: { plain_zh: '带内 S11 最大值',"
            " gate: { op: 'max_below', good: -10 } } };\n"
            "const head = m.detailMetricsHtml(payload, glossary, 'zh');\n"
            "const r = {};\n"
            "r.tip = head.includes('m-tip') && head.includes('data-tip=');\n"
            "r.gateColor = head.includes('var(--err)');\n"
            "r.costBadge = head.includes('cost:');\n"
            "r.paramsSec = head.includes('设计参数') && head.includes('f0_ghz');\n"
            "r.checksSec = head.includes('物理校验');\n"
            "r.diagSec = head.includes('诊断建议') && head.includes('R002');\n"
            "const flatHead = m.detailMetricsHtml({ s11_db_max_in_band: -12 }, {}, 'zh');\n"
            "r.flatDegraded = flatHead.includes('s11_db_max_in_band')"
            " && !flatHead.includes('设计参数');\n"
            "console.log(JSON.stringify(r));\n"
        )
        assert out == {
            "tip": True, "gateColor": True, "costBadge": True,
            "paramsSec": True, "checksSec": True, "diagSec": True,
            "flatDegraded": True,
        }

    def test_head_assembly_wiring_and_no_regression(self):
        """接线钉：detail-head 总装走 detailMetricsHtml 单源；glossary 拉取
        链保留（metricGlossaryMap→detailMetricsHtml 实参）；既有 P1-1 重试
        钉面（missing_dir 分支）不在本席改动域内逐字保留。"""
        src = _src("view_detail.js")
        assert "detailMetricsHtml(m, glossary, loc)" in src
        assert "const glossary = await metricGlossaryMap();" in src
        assert "const missingDir = !!d.missing_dir;" in src  # wave_ui_a 钉不破
        # 旧整包直渲路径不得残留（JSON 单行平铺病灶根除）
        assert "Object.entries(m).map(([k, v2]) =>" not in src

    def test_i18n_block_keys_paired(self):
        """本席 detail.* 新键 zh/en 双语齐全（help 四条+区块标签+校验标签
        +诊断文案段）。"""
        i18n = _src("i18n.js")
        keys = ("detail.help_1", "detail.help_2", "detail.help_3",
                "detail.help_4", "detail.sec_metrics", "detail.sec_params",
                "detail.sec_checks", "detail.sec_diagnosis",
                "detail.check_passivity", "detail.check_reciprocity",
                "detail.check_sanity", "detail.diag_metric_tpl",
                "detail.diag_metric_plain_tpl", "detail.diag_advice_lead")
        for key in keys:
            assert f'"{key}"' in i18n, f"i18n 缺键 {key}"


# ────────────────────────── P2-5 CLI 报错下一步指针 ──────────────────────────

_MISSING_RECIPE_ERR = "配方文件不存在: definitely_missing.yaml"


class TestRecipeMissingHintRule:
    def test_fingerprint_hits_hint_rule(self):
        """新指纹入规则表：配方文件不存在 → 可行动提示（recipes/ 指路+
        getting-started 锚，severity=info——路径错非引擎故障不夸级）。"""
        from rfauto.service.error_hints_service import hint_for_message

        out = hint_for_message(_MISSING_RECIPE_ERR)
        assert out["ok"] is True
        assert out["n_hits"] >= 1
        hit = next(h for h in out["hits"] if h["pattern"] == "配方文件不存在")
        assert "recipes/" in hit["hint"]
        assert "getting-started" in hit["refs"]
        assert hit["severity"] == "info"

    def test_rule_table_listed(self):
        """规则表读面含新条目（rfauto hints list 可见——只读叶同源）。"""
        from rfauto.service.hint_rules import list_hint_rules

        rules = list_hint_rules()["rules"]
        assert any(r["pattern"] == "配方文件不存在" for r in rules)


class TestNextStepsStderr:
    def test_direct_call_emits_to_stderr(self, capsys):
        """直呼：命中→stderr「下一步: …」行（stdout 零污染）；refs 随行。"""
        from rfauto.cli.domains._core import _print_next_steps_stderr

        _print_next_steps_stderr([_MISSING_RECIPE_ERR])
        captured = capsys.readouterr()
        assert "下一步:" in captured.err
        assert "recipes/" in captured.err
        assert "getting-started" in captured.err
        assert captured.out == ""

    def test_unknown_error_zero_output(self, capsys):
        """未命中=零输出（不编造提示，映射层同约束）。"""
        from rfauto.cli.domains._core import _print_next_steps_stderr

        _print_next_steps_stderr(["totally unknown failure xyzzy"])
        captured = capsys.readouterr()
        assert captured.err == "" and captured.out == ""

    def test_empty_and_bad_input_never_raise(self, capsys):
        from rfauto.cli.domains._core import _print_next_steps_stderr

        _print_next_steps_stderr([])
        _print_next_steps_stderr(None)  # type: ignore[arg-type]
        assert capsys.readouterr().err == ""

    def test_hint_failure_swallowed(self, monkeypatch, capsys):
        """#105：hint 生成炸→静默返回，绝不遮蔽原错误路径。"""
        from rfauto.cli.domains import _core

        def _boom(_text):
            raise RuntimeError("hint 层炸(合成)")

        monkeypatch.setattr(
            "rfauto.service.error_hints_service.hint_for_message", _boom)
        _core._print_next_steps_stderr([_MISSING_RECIPE_ERR])
        assert capsys.readouterr().err == ""


runner = CliRunner()


class TestRunCommandNextStepPointer:
    def test_run_missing_recipe_stderr_pointer(self):
        """真命令集成钉（审计条目复现形态）：rfauto run 不存在配方 → 红字
        原因照旧（stdout）+ stderr「下一步」指针出现；退出码 1 不变。"""
        result = runner.invoke(
            __import__("rfauto.cli.main", fromlist=["app"]).app,
            ["run", "definitely_missing.yaml"])
        assert result.exit_code == 1
        assert "仿真失败" in result.output
        assert _MISSING_RECIPE_ERR in result.output
        assert "下一步:" in result.stderr
        assert "recipes/" in result.stderr

    def test_run_missing_recipe_json_envelope_carries_hints(self):
        """--json 同笔：信封 hints 键含新指纹命中（_attach_error_hints 既有
        主挂点自动受益——规则表单源）。"""
        from rfauto.cli.main import app

        result = runner.invoke(app, ["run", "definitely_missing.yaml", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["ok"] is False
        assert any(h["pattern"] == "配方文件不存在" for h in payload["hints"])

    def test_dry_run_missing_recipe_stderr_pointer(self):
        """--dry-run 失败分支同挂（同指纹同指路）。"""
        from rfauto.cli.main import app

        result = runner.invoke(
            app, ["run", "definitely_missing.yaml", "--dry-run"])
        assert result.exit_code == 1
        assert "下一步:" in result.stderr


# ────────────────────────── 变异验证记录（开发期实测，非 CI 钉）──────────────────────────
#
# 逐钉"移除修复必红"实测（读-改-还原方式逐条执行，结果全数红后还原）：
# 1. view_dashboard.js wQuickLinks 摘除 data-go/kitClickRowAttrs/bindClickRows
#    （还原纯文本步卡）→ test_dashboard_steps_have_data_go_and_kit_attrs +
#    test_dashboard_steps_bind_click_rows_showpage 红。
# 2. view_guide.js 步骤卡还原纯文本 + 摘除 bindClickRows 接线 →
#    test_guide_steps_clickable_same_form 红。
# 3. view_detail.js 摘除 help 壳四条 → test_help_shell_present_with_four_items 红。
# 4. view_detail.js 还原旧整包 Object.entries 直渲（摘 detailMetricsHtml 总装）
#    → test_head_assembly_wiring_and_no_regression 红；导出纯函数删除 →
#    4 个 node 行为钉 import undefined 红（本文件全部 skipif 门内用例）。
# 5. hint_rules.py 摘「配方文件不存在」条 → test_fingerprint_hits_hint_rule /
#    test_rule_table_listed / stderr 三钉红（零命中零输出）。
# 6. workflow.py run/dry-run 失败分支摘 _print_next_steps_stderr 挂接 →
#    test_run_missing_recipe_stderr_pointer / test_dry_run_missing_recipe_stderr_pointer 红。
