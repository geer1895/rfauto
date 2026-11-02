"""aurora_n 开放池席：UI E2E 冒烟套件（六条关键用户动线 + run_all 汇总）。

本役 UI 面大改（waveUI-A/B/C 三组 + 缓存治理 cache_gov + 上级修复
ef2cb34e）全靠一次性走查验证——本套件把动线钉成**持久回归冒烟**。

测试形态（不引 Playwright 重依赖，禁真浏览器；禁真跑优化/求解——
fake 通道/快速失败路径）：

- **真服 API 动线**：starlette TestClient 直驱 create_ui_app（页面 HTML
  载荷含关键模块引用 + /api/* 信封序列），照 test_aurora_n_wave_ui_a
  真服形态（tmp cwd+注册表双隔离，#144 家族口径零触真实 runs/ 湖）。
- **node 行为级分派**：关键 js 模块的分派函数真执行（stub DOM 形态，
  照 test_ui_modules_behavior 先例，每用例独立 node 进程）；动线信封
  用真服响应注入 node fetch 桩——「真服载荷 → 前端分派函数」组合而非
  各自孤立（E2E 语义所在）。

六动线（每线一测）：
①导入：index 载荷含 import 模块链 → /api/fs/list parent+data-k（回归
  ef2cb34e：上级行 data-k="dir"，bindClickRows 按 k 分派导航非选中）
  → 导入路由快速失败 200（不启动 AEDT）；
②优化：tune 页载荷 → 计划段 dry-run 信封 params_semantics（journeyB
  F-P1-2）→ runs 列表 on_disk（组 A P1-1）；
③导览：dashboard 快速开始四卡 data-go（组 B P2-1）→ guide 锚
  （TOC data-goto + g-steps-flow）——bindClickRows→showPage 分派真执行；
④详情：run_detail missing_dir 两态+重试钮禁用（组 A）+ 诊断卡/词典
  tooltip（组 B P2-2，真服 metrics.json 载荷 → view_detail 分派函数）；
⑤错误：validate 拼写错 RC=1 did-you-mean（journeyA F-P1-1）→ CLI hint
  指纹（sweep 二批三指纹命中，CLI 面单测形态）；
⑥缓存：pages+根级演进 JS no-cache / vendor max-age（cache_gov，f0156ec2）。

汇总：test_smoke_run_all_six_flows 单会话顺序走完六线（粗粒度断言，
run_all 冒烟口径）。

不依赖 runs/ 真实湖（tmp 隔离）、不读网络、不启动服务器；node 面缺
node 诚实 skip（_NODE 先例）；每用例 ≤5s；不 commit。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_NODE = shutil.which("node")

_RUN_ID_DIR = "20260101_000000_withdir"
_RUN_ID_GONE = "20260101_000000_gone"
_RUN_ID_UNKNOWN = "20991231_000000_nope"


# ────────────────────────── 工具（真服 + node 桩两形态共用） ──────────────────────────


def _run_node_js(js: str) -> dict:
    """node --input-type=module 真执行（程序走 stdin——真服信封动辄
    十几 KB，-e 命令行形态撞 Windows 32K 限 WinError 206；cwd=_STATIC，
    pages/ 相对 import 与 -e 同基）；stdout 末行 JSON 约定照
    test_ui_modules_behavior 同款。"""
    r = subprocess.run(
        [_NODE, "--input-type=module"],
        input=js, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=60, cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2500:]}"
    return json.loads(r.stdout.strip().splitlines()[-1])


def _recipe_dict() -> dict:
    """最小 fake 配方（test_integ_b_ui_tune_fullstack 同款形态）。"""
    return {
        "model": "wilkinson_power_divider",
        "schema_version": 1,
        "params": {
            "arm_len_mm": {"value": 20.5, "unit": "mm",
                           "bounds": [15.0, 30.0]},
        },
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
             "value": -15},
        ],
    }


def _seed_index(run_id: str, timestamp: str) -> None:
    from rfauto.infra.run_store import record_run

    assert record_run(record={
        "run_id": run_id, "model": "wilkinson_power_divider",
        "adapter": "fake", "status": "done", "timestamp": timestamp,
    })


_METRICS_JSON = {
    "params": {"arm_len_mm": 20.5},
    "metrics": {"s11_db_max_in_band": -8.08},
    "cost": 1.234,
    "checks": {"passivity_ok": True, "reciprocity_ok": False},
    "diagnosis": {"ok": True, "diagnoses": [
        {"rule_id": "R002", "description": "S11 谐振频率偏高",
         "hint": "检查馈电位置是否过短", "severity": "warning",
         "metric": "s11_db_max_in_band", "value": -8.08, "threshold": -10}],
    },
}


@pytest.fixture()
def _iso(tmp_path, monkeypatch):
    """cwd+注册表 DB+缓存三隔离（#144 家族口径：本机 env 与真实 runs/
    湖零触碰）；RFAUTO_UI_TOKEN 摘除防鉴权面干扰写端点动线。"""
    monkeypatch.delenv("RFAUTO_UI_TOKEN", raising=False)
    monkeypatch.delenv("RFAUTO_REGISTRY_DB", raising=False)
    monkeypatch.setenv("RFAUTO_REGISTRY_DB", str(tmp_path / "reg.sqlite"))
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    monkeypatch.setenv("RFAUTO_UI_CACHE", "0")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture()
def client(_iso):
    from starlette.testclient import TestClient

    from rfauto.ui.server import create_ui_app

    with TestClient(create_ui_app(include_runs_mount=False)) as c:
        yield c


def _glossary_map(client) -> dict:
    """真服 /api/metric-glossary → 前端 metricGlossaryMap 同构映射
    （{metric_id: entry}——view_detail detailMetricsHtml 实参形态）。"""
    d = client.get("/api/metric-glossary").json()
    assert d["ok"] is True
    return {e["metric_id"]: e for e in d["entries"] if e.get("metric_id")}


# ────────────────────────── 动线①：导入（fs_list parent+data-k 回归 ef2cb34e） ──────────────────────────


class TestFlowImport:
    def test_index_module_chain_fslist_parent_datak_import_route(
            self, _iso, client):
        """导入动线全链：index/pages.js/view_import 模块引用链 → 真服
        fs_list 信封（parent 在档）→ fileBrowser 分派真执行（上级行
        data-k="dir" 导航、文件行 onPick 关弹层——ef2cb34e 回归的行为级
        形态）→ /api/hfss/import 快速失败 200（零 AEDT 启动）。"""
        # ① 页面载荷：SPA 壳 + import 域模块链（filebrowser 经 view_import
        # 引用——弹层本体不在 index 静态串，链路引用是 E2E 可钉面）
        index = client.get("/")
        assert index.status_code == 200
        assert "/static/app.js" in index.text
        app_js = client.get("/static/app.js")
        assert app_js.status_code == 200
        assert 'from "./pages.js"' in app_js.text, "加载器链 app.js→pages.js"
        pages_js = client.get("/static/pages.js")
        assert pages_js.status_code == 200
        assert '_lazyView("import", "view_import.js"' in pages_js.text
        view_import = client.get("/static/pages/view_import.js")
        assert view_import.status_code == 200
        assert "fileBrowser(" in view_import.text
        assert '".aedt"' in view_import.text

        # ② 真服 /api/fs/list 信封（parent 字段=上级导航数据面）；
        #    叶目录（仅 .yaml 文件）信封供「全滤空态说明」分支
        (_iso / "demo.aedt").write_text("stub", encoding="utf-8")
        (_iso / "recipes").mkdir()
        leaf = _iso / "leafdir"
        leaf.mkdir()
        (leaf / "x.yaml").write_text("model: x\n", encoding="utf-8")
        envelope = client.get("/api/fs/list", params={"path": ""}).json()
        assert envelope["ok"] is True
        assert envelope["parent"]
        names = {e["name"]: e["kind"] for e in envelope["entries"]}
        assert names.get("demo.aedt") == "file"
        assert names.get("recipes") == "dir"
        envelope_leaf = client.get(
            "/api/fs/list", params={"path": str(leaf)}).json()
        assert [e["name"] for e in envelope_leaf["entries"]] == ["x.yaml"]

        # ③ node 行为级：fileBrowser 分派真执行消费真服信封（stub DOM）
        out = _run_node_js(
            "const ENVELOPE = " + json.dumps(envelope, ensure_ascii=True) + ";\n"
            "const ENVELOPE_LEAF = "
            + json.dumps(envelope_leaf, ensure_ascii=True) + ";\n"
            "const fb = await import('./pages/filebrowser.js');\n"
            "let fetchCalls = [];\n"
            "globalThis.fetch = async (url) => { fetchCalls.push(String(url));\n"
            "  return { json: async () => (String(url).includes('leafdir')\n"
            "    ? ENVELOPE_LEAF : ENVELOPE) }; };\n"
            "const removed = [];\n"
            "function mkEl() {\n"
            "  const el = { id: '', style: {}, attrs: {}, children: {},\n"
            "    _html: '', textContent: '',\n"
            "    setAttribute(n, v) { this.attrs[n] = v; },\n"
            "    remove() { removed.push(this.id); },\n"
            "    addEventListener() {}, focus() {},\n"
            "    insertAdjacentHTML(pos, html) { this.innerHTML += html; },\n"
            "    querySelector(sel) { if (!this.children[sel])\n"
            "      this.children[sel] = mkEl(); return this.children[sel]; },\n"
            "    querySelectorAll(sel) {\n"
            "      if (!this._rows) this._rows = [];\n"
            "      if (this._rowsDirty || !this._rows.length) {\n"
            "        this._rows.length = 0;\n"
            "        const re = /data-p=\"([^\"]*)\" data-k=\"([^\"]*)\"/g;\n"
            "        let m;\n"
            "        while ((m = re.exec(this.innerHTML)) !== null)\n"
            "          this._rows.push({ dataset: { p: m[1], k: m[2] } });\n"
            "        this._rowsDirty = false;\n"
            "      }\n"
            "      return sel === '.fs-row' ? this._rows : [];\n"
            "    } };\n"
            "  Object.defineProperty(el, 'innerHTML', {\n"
            "    get() { return this._html; },\n"
            "    set(v) { this._html = String(v); this._rowsDirty = true; } });\n"
            "  return el;\n"
            "}\n"
            "const modals = [];\n"
            "globalThis.document = {\n"
            "  getElementById: (id) => modals.find((m) => m.id === id) || null,\n"
            "  createElement: () => { const e = mkEl(); modals.push(e); return e; },\n"
            "  body: { appendChild() {} }, activeElement: null,\n"
            "  contains: () => false };\n"
            "const tick = () => new Promise((r) => setTimeout(r, 5));\n"
            "const waitReady = async (list) => {\n"
            "  for (let i = 0; i < 60 && !list.innerHTML.includes('fs-row'); i++)\n"
            "    await tick(); };\n"
            "let picked = null;\n"
            "fb.fileBrowser('', (p) => { picked = p; }, null);\n"
            "const list1 = modals[0].querySelector('#fs-list');\n"
            "await waitReady(list1);\n"
            "const rows1 = list1.querySelectorAll('.fs-row');\n"
            "const r = {};\n"
            "r.parentK = rows1[0].dataset.k;  // ef2cb34e：上级行必须 data-k=dir\n"
            "r.parentLabel = list1.innerHTML.includes('aria-label=\"返回上级目录\"');\n"
            "const fileRow = rows1.find((x) => x.dataset.k === 'file');\n"
            "fileRow.onclick(); await tick();\n"
            "r.picked = picked;\n"
            "r.pickedMatchesEntry = ENVELOPE.entries.some(\n"
            "  (e) => e.kind === 'file' && e.path === picked);\n"
            "r.closedAfterPick = removed.includes('fs-browser');\n"
            "// .s2p 过滤：叶目录（仅 .yaml）→ 文件行全滤+空态说明、上级/目录恒可见\n"
            "fb.fileBrowser('leafdir', () => {}, ['.s2p']);\n"
            "const modal2 = modals[modals.length - 1];\n"
            "const list2 = modal2.querySelector('#fs-list');\n"
            "await waitReady(list2);\n"
            "const rows2 = list2.querySelectorAll('.fs-row');\n"
            "r.filteredDirsKept = rows2.some((x) => x.dataset.k === 'dir');\n"
            "r.filteredNoFile = !rows2.some((x) => x.dataset.k === 'file');\n"
            "r.filterEmptyNote = list2.innerHTML.includes('本目录没有匹配文件');\n"
            "// 上级行点击=导航（二次 fs/list 拉取）非选中（ef2cb34e 分派契约）\n"
            "const nBefore = fetchCalls.length;\n"
            "rows2[0].onclick(); await tick(); await tick();\n"
            "r.parentNavigates = fetchCalls.length > nBefore;\n"
            "r.pickNotFiredOnParent = picked === r.picked;\n"
            "console.log(JSON.stringify(r));\n"
        )
        assert out["parentK"] == "dir", "ef2cb34e 回归：上级行缺 data-k=dir"
        assert out["parentLabel"] is True
        assert out["pickedMatchesEntry"] is True
        assert out["closedAfterPick"] is True
        assert out["filteredDirsKept"] is True and out["filteredNoFile"] is True
        assert out["filterEmptyNote"] is True
        assert out["parentNavigates"] is True
        assert out["pickNotFiredOnParent"] is True

        # ④ 导入路由 200：不存在工程快速失败信封（零 AEDT 启动）；空路径 400
        r1 = client.post("/api/hfss/import",
                         json={"project": str(_iso / "nope.aedt")})
        assert r1.status_code == 200
        assert r1.json()["ok"] is False
        assert "工程文件不存在" in r1.json()["error"]
        r2 = client.post("/api/hfss/import", json={"project": "  "})
        assert r2.status_code == 400


# ────────────────────────── 动线②：优化（dry-run params_semantics + runs on_disk） ──────────────────────────


class TestFlowTune:
    def test_tune_payload_dryrun_envelope_runs_on_disk(self, _iso, client):
        """优化动线：tune 页载荷（前置校验接线在档）→ 计划段 dry-run 信封
        params_semantics/optimization_ranges（journeyB）→ 真服 /api/runs
        on_disk 双值（组 A）+ node 行为级 recipeFileExists 分派消费真服
        fs_list 信封。"""
        # ① tune 页载荷：启动 POST + 存在性前置校验（wave_ui_c P3-3）
        view_tune = client.get("/static/pages/view_tune.js")
        assert view_tune.status_code == 200
        assert "/api/tune/start" in view_tune.text
        assert "const _exists = await recipeFileExists(_p);" in view_tune.text

        # ② 真服 fs_list 信封 → node recipeFileExists 分派（启动前置校验）
        recipes_dir = _iso / "recipes"
        recipes_dir.mkdir(exist_ok=True)
        recipe_path = recipes_dir / "demo.yaml"
        recipe_path.write_text(
            yaml.safe_dump(_recipe_dict()), encoding="utf-8")
        envelope = client.get(
            "/api/fs/list", params={"path": str(recipes_dir)}).json()
        assert envelope["ok"] is True
        out = _run_node_js(
            "const ENVELOPE = " + json.dumps(envelope, ensure_ascii=True) + ";\n"
            "const m = await import('./pages/view_tune.js');\n"
            "globalThis.fetch = async () => ({ json: async () => ENVELOPE });\n"
            "const r = {};\n"
            "r.found = await m.recipeFileExists('recipes/demo.yaml');\n"
            "r.missing = await m.recipeFileExists('recipes/nope.yaml');\n"
            "r.split = m.splitRecipePath('recipes/demo.yaml');\n"
            "console.log(JSON.stringify(r));\n"
        )
        assert out == {"found": True, "missing": False,
                       "split": {"dir": "recipes", "name": "demo.yaml"}}

        # ③ 计划段 dry-run 信封（fake 通道零真跑零求解）：journeyB 三键
        from rfauto.service.api import dry_run

        d = dry_run(str(recipe_path))
        assert d["ok"] is True
        assert d["mode"] == "dry-run"
        assert "params_semantics" in d, "journeyB F-P1-2 计划段参数语义键缺席"
        assert "tune" in d["params_semantics"]
        ranges = d["optimization_ranges"]
        assert isinstance(ranges, dict) and ranges.get("arm_len_mm") == {
            "low": 15.0, "high": 30.0}

        # ④ 真服 runs 列表 on_disk 双值（组 A P1-1：索引行逐行在盘标注）
        _seed_index(_RUN_ID_DIR, "2026-01-01T00:00:00+00:00")
        (_iso / "runs" / _RUN_ID_DIR).mkdir(parents=True)
        _seed_index(_RUN_ID_GONE, "2026-01-02T00:00:00+00:00")
        r = client.get("/api/runs", params={"limit": 10})
        assert r.status_code == 200
        rows = {x["run_id"]: x for x in r.json()["runs"]}
        assert rows[_RUN_ID_DIR]["on_disk"] is True
        assert rows[_RUN_ID_GONE]["on_disk"] is False


# ────────────────────────── 动线③：导览（dashboard 四卡 data-go → guide 锚） ──────────────────────────


class TestFlowDashboardGuide:
    def test_dashboard_quickstart_cards_dispatch_and_guide_anchor(
            self, _iso, client):
        """导览动线：dashboard 快速开始四卡 data-go（组 B）+ 指南页
        g-steps-flow 同款四卡与 TOC 锚 → node 分派真执行
        （bindClickRows→showPage：四卡逐卡激活对应页 + guide 锚跳转）。"""
        dash = client.get("/static/pages/view_dashboard.js")
        assert dash.status_code == 200
        assert "data-go='${go}'" in dash.text
        for go in ("import", "recipe", "tune", "runs"):
            assert f'["{go}", t("nav.' in dash.text, f"步卡缺页 id {go}"
        guide = client.get("/static/pages/view_guide.js")
        assert guide.status_code == 200
        assert "id='g-steps-flow'" in guide.text
        for go in ("import", "recipe", "tune", "runs"):
            assert f"data-go='{go}'" in guide.text
        # guide 锚：TOC data-goto 页内锚在档（五分钟上手/工作流节）
        for anchor in ("g-steps", "g-what", "g-wf"):
            assert f"data-goto='{anchor}'" in guide.text, f"guide 锚缺 {anchor}"

        out = _run_node_js(
            "globalThis.location = { hash: '' };\n"
            "globalThis.history = { replaceState: (a, b, u) => {\n"
            "  globalThis.location.hash = u; } };\n"
            "const ctx = await import('./pages/context.js');\n"
            "const kit = await import('./pages/kit.js');\n"
            "const router = await import('./pages/router.js');\n"
            "ctx.T.activate = () => {};\n"
            "for (const p of ['import', 'recipe', 'tune', 'runs', 'guide'])\n"
            "  router.VIEWS[p] = () => {};\n"
            "const rows = ['import', 'recipe', 'tune', 'runs'].map(\n"
            "  (go) => ({ dataset: { go } }));\n"
            "const root = { querySelectorAll: (sel) =>\n"
            "  sel === '[data-go]' ? rows : [] };\n"
            "kit.bindClickRows(root, (row) => router.showPage(row.dataset.go),\n"
            "  '[data-go]');\n"
            "const seq = [];\n"
            "for (const r of rows) { r.onclick(); seq.push(ctx.getActiveView()); }\n"
            "router.showPage('guide');\n"
            "console.log(JSON.stringify({ seq, guide: ctx.getActiveView(),\n"
            "  hash: globalThis.location.hash }));\n"
        )
        assert out["seq"] == ["import", "recipe", "tune", "runs"], \
            "四卡逐卡激活对应页（bindClickRows→showPage 分派）"
        assert out["guide"] == "guide" and out["hash"] == "#/guide"


# ────────────────────────── 动线④：详情（missing_dir 两态+重试钮+诊断卡+词典） ──────────────────────────


class TestFlowRunDetail:
    def test_detail_missing_states_retry_diag_glossary(self, _iso, client):
        """详情动线：run_detail missing_dir 两态（索引残留可行动文案/纯
        不存在）+ 重试钮禁用钉（组 A）→ 真服 run_detail 成功信封
        metrics.json 全量载荷 → node view_detail 分派真执行（形态判别+
        诊断卡+词典 tooltip——组 B，词典走真服 /api/metric-glossary）。"""
        # ① 两态（组 A P1-1）
        _seed_index(_RUN_ID_GONE, "2026-01-02T00:00:00+00:00")
        d1 = client.get(f"/api/runs/{_RUN_ID_GONE}").json()
        assert d1["ok"] is False and d1["missing_dir"] is True
        assert any("重试无效" in e for e in d1["errors"])
        assert any("索引残留" in e for e in d1["errors"])
        d2 = client.get(f"/api/runs/{_RUN_ID_UNKNOWN}").json()
        assert d2["ok"] is False and d2["missing_dir"] is True
        assert any(f"run 不存在: {_RUN_ID_UNKNOWN}" in e for e in d2["errors"])

        # ② 重试钮禁用 + missing_dir 消费面（served 载荷钉）
        view_detail = client.get("/static/pages/view_detail.js")
        assert view_detail.status_code == 200
        assert "const missingDir = !!d.missing_dir;" in view_detail.text
        assert 'disabled title="${escAttr(t("detail.retry_futile"))}"' \
            in view_detail.text

        # ③ 成功路径真服信封：metrics=metrics.json 全量（嵌套形态）
        run_dir = _iso / "runs" / _RUN_ID_DIR
        (run_dir / "results").mkdir(parents=True)
        (run_dir / "results" / "metrics.json").write_text(
            json.dumps(_METRICS_JSON), encoding="utf-8")
        d3 = client.get(f"/api/runs/{_RUN_ID_DIR}").json()
        assert d3["ok"] is True and not d3.get("missing_dir")
        assert d3["metrics"]["diagnosis"]["diagnoses"][0]["rule_id"] == "R002"

        # ④ node 行为级：真服载荷 → view_detail 分派函数 + 真服词典
        glossary = _glossary_map(client)
        assert "s11_db_max_in_band" in glossary
        out = _run_node_js(
            "const METRICS = " + json.dumps(_METRICS_JSON, ensure_ascii=True) + ";\n"
            "const GLOSSARY = " + json.dumps(glossary, ensure_ascii=True) + ";\n"
            "const m = await import('./pages/view_detail.js');\n"
            "const p = m.splitMetricPayload(METRICS);\n"
            "const cards = m.diagCardsHtml(p.diagnosis);\n"
            "const head = m.detailMetricsHtml(METRICS, GLOSSARY, 'zh');\n"
            "console.log(JSON.stringify({\n"
            "  metricKeys: Object.keys(p.metrics).join(','),\n"
            "  hasParams: !!p.params, hasChecks: !!p.checks, hasDiag: !!p.diagnosis,\n"
            "  rule: cards.includes('R002'),\n"
            "  gate: cards.includes('门限 -10'),\n"
            "  hint: cards.includes('检查馈电位置是否过短'),\n"
            "  warnCls: cards.includes('badge warn'),\n"
            "  tip: head.includes('m-tip') && head.includes('data-tip='),\n"
            "  paramsSec: head.includes('设计参数'),\n"
            "  checksSec: head.includes('物理校验'),\n"
            "  diagSec: head.includes('诊断建议'),\n"
            "}));\n"
        )
        assert out["metricKeys"] == "s11_db_max_in_band"
        assert out["hasParams"] and out["hasChecks"] and out["hasDiag"]
        assert out["rule"] and out["gate"] and out["hint"] and out["warnCls"], \
            "组 B 诊断卡四件（规则徽章/门限/建议/级别）"
        assert out["tip"], "词典 tooltip（38+ 键基建）挂上内层指标键"
        assert out["paramsSec"] and out["checksSec"] and out["diagSec"]


# ────────────────────────── 动线⑤：错误（validate did-you-mean + hint 指纹） ──────────────────────────


runner = CliRunner()


class TestFlowErrorHints:
    def test_validate_typo_rc1_did_you_mean_then_hint_fingerprints(self, _iso):
        """错误动线：validate 拼写错 RC=1 + did-you-mean（journeyA）→
        CLI hint 指纹（sweep 二批三指纹：配方文件不存在/配方不存在/
        run 不存在——三面消息各自命中且 severity=info 指路 recipes/）。"""
        recipe = _recipe_dict()
        recipe["paramz"] = {}  # 拼写错（合法面照旧在档——纯多键形态）
        bad = _iso / "typo.yaml"
        bad.write_text(yaml.safe_dump(recipe), encoding="utf-8")

        from rfauto.cli.main import app

        result = runner.invoke(app, ["validate", str(bad)])
        assert result.exit_code == 1, "拼写错必须 RC=1"
        assert "你是不是想写 'params'？" in result.output, \
            "journeyA did-you-mean 后缀缺失"
        assert "未知顶层键: paramz" in result.output

        # CLI hint 指纹（sweep 二批——CLI 面单测形态）：错误文本 → 可行动提示
        from rfauto.service.error_hints_service import hint_for_message

        h1 = hint_for_message("配方文件不存在: definitely_missing.yaml")
        assert h1["ok"] and h1["n_hits"] >= 1
        hit1 = next(h for h in h1["hits"] if h["pattern"] == "配方文件不存在")
        assert "recipes/" in hit1["hint"] and "validate" in hit1["hint"]
        assert "getting-started" in hit1["refs"]
        assert hit1["severity"] == "info"
        h2 = hint_for_message("配方不存在: x.yaml")  # tune/campaign 面（二批）
        hit2 = next(h for h in h2["hits"] if h["pattern"] == "配方不存在")
        assert "recipes/" in hit2["hint"] and "validate" in hit2["hint"]
        h3 = hint_for_message(f"run 不存在: {_RUN_ID_UNKNOWN}")  # runs 面（二批）
        hit3 = next(h for h in h3["hits"] if h["pattern"] == "run( 目录)? ?不存在")
        assert "runs watch" in hit3["hint"]


# ────────────────────────── 动线⑥：缓存（cache_gov 分域头） ──────────────────────────


class TestFlowCacheGov:
    def test_cache_control_domains(self, _iso, client):
        """缓存动线（cache_gov，f0156ec2）：pages/ 与根级演进 JS no-cache
        （协商缓存保留——waveUI-A 遗留痛点：修复部署后旧页 max-age 窗内
        看不到新 JS）；vendor 长缓存不变；HTML/API 缺省 no-cache 显式化。"""
        r_pages = client.get("/static/pages/i18n.js")
        assert r_pages.status_code == 200
        assert r_pages.headers["cache-control"] == "no-cache", \
            "pages/ 演进 JS 必须 no-cache（cache_gov）"
        r_app = client.get("/static/app.js")
        assert r_app.status_code == 200
        assert r_app.headers["cache-control"] == "no-cache", \
            "根级演进 JS（app.js）随 cache_gov 迁 no-cache"
        r_vendor = client.get("/static/vendor/echarts.min.js")
        assert r_vendor.status_code == 200
        assert r_vendor.headers["cache-control"] == "public, max-age=86400", \
            "vendor 不变资产长缓存不变"
        assert client.get("/").headers["cache-control"] == "no-cache"
        r_api = client.get("/api/runs", params={"limit": 1})
        assert r_api.status_code == 200
        assert r_api.headers["cache-control"] == "no-cache", "API 动态面禁缓存"


# ────────────────────────── 汇总：smoke run_all（单会话六线顺序走查） ──────────────────────────


class TestSmokeRunAll:
    def test_smoke_run_all_six_flows(self, _iso, client):
        """汇总冒烟：单会话顺序走完六条动线（粗粒度断言——每线一布尔，
        全 True 才过；与上方分线用例同源信封/分派面，防"单线绿但组合
        断链"的集成级回退）。"""
        checks: dict[str, bool] = {}

        # 线①导入：载荷链 + fs_list + 导入快速失败
        index = client.get("/")
        checks["flow1_index_module_chain"] = (
            index.status_code == 200
            and "/static/app.js" in index.text
            and 'from "./pages.js"' in client.get("/static/app.js").text
            and '_lazyView("import", "view_import.js"'
            in client.get("/static/pages.js").text)
        (_iso / "demo.aedt").write_text("stub", encoding="utf-8")
        env = client.get("/api/fs/list", params={"path": ""}).json()
        checks["flow1_fslist_parent"] = (
            env["ok"] is True and bool(env["parent"])
            and any(e["name"] == "demo.aedt" for e in env["entries"]))
        imp = client.post("/api/hfss/import",
                          json={"project": str(_iso / "nope.aedt")})
        checks["flow1_import_route_200"] = (
            imp.status_code == 200 and imp.json()["ok"] is False)

        # 线②优化：tune 载荷 + dry-run params_semantics + runs on_disk
        vt = client.get("/static/pages/view_tune.js")
        recipes_dir = _iso / "recipes"
        recipes_dir.mkdir(exist_ok=True)
        recipe_path = recipes_dir / "demo.yaml"
        recipe_path.write_text(yaml.safe_dump(_recipe_dict()),
                               encoding="utf-8")
        from rfauto.service.api import dry_run

        d = dry_run(str(recipe_path))
        checks["flow2_tune_dryrun_semantics"] = (
            vt.status_code == 200 and "/api/tune/start" in vt.text
            and d["ok"] and d["mode"] == "dry-run"
            and bool(d.get("params_semantics")))
        _seed_index(_RUN_ID_DIR, "2026-01-01T00:00:00+00:00")
        (_iso / "runs" / _RUN_ID_DIR).mkdir(parents=True)
        _seed_index(_RUN_ID_GONE, "2026-01-02T00:00:00+00:00")
        runs_env = client.get("/api/runs", params={"limit": 10}).json()
        rows = {x["run_id"]: x.get("on_disk") for x in runs_env["runs"]}
        checks["flow2_runs_on_disk"] = (rows.get(_RUN_ID_DIR) is True
                                        and rows.get(_RUN_ID_GONE) is False)

        # 线③导览：四卡 data-go（dashboard+guide）+ guide 锚
        dash = client.get("/static/pages/view_dashboard.js").text
        guide = client.get("/static/pages/view_guide.js").text
        checks["flow3_quickstart_cards_guide_anchor"] = (
            "data-go='${go}'" in dash and "id='g-steps-flow'" in guide
            and all(f"data-go='{go}'" in guide
                    for go in ("import", "recipe", "tune", "runs"))
            and "data-goto='g-steps'" in guide)

        # 线④详情：missing_dir 两态 + 重试钮钉 + 成功路径诊断载荷
        d1 = client.get(f"/api/runs/{_RUN_ID_GONE}").json()
        d2 = client.get(f"/api/runs/{_RUN_ID_UNKNOWN}").json()
        run_dir = _iso / "runs" / _RUN_ID_DIR
        (run_dir / "results").mkdir(parents=True, exist_ok=True)
        (run_dir / "results" / "metrics.json").write_text(
            json.dumps(_METRICS_JSON), encoding="utf-8")
        d3 = client.get(f"/api/runs/{_RUN_ID_DIR}").json()
        vd = client.get("/static/pages/view_detail.js").text
        checks["flow4_detail_missing_retry_diag"] = (
            d1["missing_dir"] is True and any("重试无效" in e for e in d1["errors"])
            and d2["missing_dir"] is True
            and d3["ok"] is True
            and "missingDir" in vd and "detail.retry_futile" in vd
            and d3["metrics"]["diagnosis"]["diagnoses"][0]["rule_id"] == "R002")

        # 线⑤错误：hint 指纹（validate RC=1 did-you-mean 由分线用例真跑——
        # run_all 口径钉指纹单源面）
        from rfauto.service.error_hints_service import hint_for_message

        h = hint_for_message("配方文件不存在: x.yaml")
        checks["flow5_hint_fingerprint"] = (
            h["ok"] and h["n_hits"] >= 1
            and any("getting-started" in x["refs"] for x in h["hits"]))

        # 线⑥缓存：三域头
        checks["flow6_cache_domains"] = (
            client.get("/static/pages/i18n.js").headers["cache-control"]
            == "no-cache"
            and client.get("/static/app.js").headers["cache-control"]
            == "no-cache"
            and client.get("/static/vendor/echarts.min.js")
            .headers["cache-control"] == "public, max-age=86400")

        bad = {k: v for k, v in checks.items() if not v}
        assert not bad, f"smoke run_all 六线断链: {bad}"
        assert {k.split("_")[0] for k in checks} == {f"flow{i}" for i in range(1, 7)}, \
            "六线键集必须齐整（动线清单防缩水）"
