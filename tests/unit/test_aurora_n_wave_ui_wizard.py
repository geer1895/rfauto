"""aurora_n wave_ui_wizard 席位回归钉：校准面向导化改造（三步向导引导层）。

对应 aurora_n UI 审计 P2 面（校准页对新用户引导薄弱）：view_calibration
新增 #cal-wizard 引导层块——三步 stepper 卡（选模板/配目标 → 选数据源 →
跑与判读），每步=前置条件守卫行 + 输入引导 + 产物预告。形态家法：

- 组 B 快速开始四步卡 data-go 形态（guide-flow/guide-step clickable +
  kitClickRowAttrs 三件套 + bindClickRows click 与 Enter/Space 同一激活 →
  showPage 跳页单源——dashboard wQuickLinks/view_guide g-steps-flow 同款）；
- guide 锚形态（a[data-goto] 委托 + 文档绝对坐标直设 scrollTop，不写
  location.hash——hash 是两级路由信道；view_guide _bindToc 同款）；
- journeyB recipeFileExists 家法（/api/fs/list 只读探测 + #105 best-effort
  ——探测失败/超时/切页取消=unknown 如实显示，守卫永不拦主路径）。

红线：向导是引导层**新增块**——校准页既有表单/按钮/表格/深链/排序/
演化图零改动（test_existing_page_red_lines 逐字节钉住既有行为锚）；
服务端零新端点零语义变化（守卫只消费既有 /api/recipes 与 /api/fs/list
只读面）。

变异验证（移除修复必红，开发期逐钉实测记录于 runs/aurora_n/
wave_ui_wizard/MUTATION_LOG.md）：源码钉关键串即修复本体（删除即断言
红）；node 行为钉消费导出纯函数/探测函数（删除导出/import undefined 即
红）；真服钉消费信封形状（tmp 隔离 #144 家族口径，零触真实 runs/ 湖）。

不读网络、不启动长驻服务器（TestClient 内存态）；node 面缺 node 诚实
skip；不 commit。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_NODE = shutil.which("node")

_WIZ_KEYS = (
    "calibration.wiz_title", "calibration.wiz_lead",
    "calibration.wiz_jump_table", "calibration.wiz_step_aria_tpl",
    "calibration.wiz_s1_t", "calibration.wiz_s1_d", "calibration.wiz_s1_out",
    "calibration.wiz_g1_ok_tpl", "calibration.wiz_g1_empty",
    "calibration.wiz_s2_t", "calibration.wiz_s2_d", "calibration.wiz_s2_out",
    "calibration.wiz_g2_ok_tpl", "calibration.wiz_g2_empty",
    "calibration.wiz_s3_t", "calibration.wiz_s3_d", "calibration.wiz_s3_out",
    "calibration.wiz_g3_ok_tpl", "calibration.wiz_g3_empty",
    "calibration.wiz_g_unknown",
)


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


@pytest.fixture()
def _iso(tmp_path, monkeypatch):
    """cwd+注册表 DB+缓存三隔离（#144 家族口径：本机 env 与真实 runs/
    湖零触碰）；RFAUTO_UI_TOKEN 摘除防鉴权面干扰只读动线。"""
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


_RECIPE_YAML = """model: wilkinson_power_divider
schema_version: 1
params:
  arm_len_mm: {value: 20.5, unit: mm, bounds: [15.0, 30.0]}
objectives:
  - {metric: s11_db, band: [2.3, 2.5], op: max_below, value: -15}
"""


# ══════════════════ 向导结构源码钉（新增块形态） ══════════════════


class TestWizardStructure:
    def test_wizard_block_stepper_three_steps(self):
        """三步卡结构：#cal-wizard 面板 + #cal-wiz-flow 容器 + 三卡
        data-go（recipe/solvers/guide——组 B guide-step clickable 家法）+
        每卡守卫行 role='status'（cal-wiz-g1/g2/g3）+ 产物预告键 +
        aria 走整句模板键（kitClickRowAttrs 单点共用）。"""
        src = _src("view_calibration.js")
        assert "id='cal-wizard'" in src
        assert "id='cal-wiz-flow'" in src
        for go in ("recipe", "solvers", "guide"):
            assert f"data-go='{go}'" in src, f"向导缺步卡跳转 {go}"
        assert src.count("class='guide-step clickable'") == 3
        for gid in ("cal-wiz-g1", "cal-wiz-g2", "cal-wiz-g3"):
            assert f"id='{gid}' role='status'" in src, f"守卫行 {gid} 缺 status 语义"
        # aria=整句模板键（{n}/{name} 插值），kitClickRowAttrs 三卡共用单点
        assert src.count("kitClickRowAttrs({ label: t(\"calibration.wiz_step_aria_tpl\"") == 3
        # 每卡三件式：引导描述 + 守卫行 + 产物预告（data-i18n 静态注入口）
        for k in ("wiz_s1_d", "wiz_s2_d", "wiz_s3_d",
                  "wiz_s1_out", "wiz_s2_out", "wiz_s3_out",
                  "wiz_title", "wiz_lead", "wiz_jump_table"):
            assert f"data-i18n='calibration.{k}'" in src, f"缺 data-i18n 注入口 {k}"

    def test_wizard_anchor_jump_uses_guide_toc_form(self):
        """锚跳转=guide 锚形态：a[data-goto='cal-table']（href 兜底形态）+
        委托监听 dataset 去重（wizBound）+ 文档绝对坐标直设 scrollTop
        （scrollIntoView smooth 不可靠先例）+ 不写 location.hash（只认
        赋值形态——头注/docstring 提及不误伤）。"""
        src = _src("view_calibration.js")
        assert "href='#cal-table' data-goto='cal-table'" in src
        assert "if (wiz && !wiz.dataset.wizBound) {" in src
        assert 'wiz.dataset.wizBound = "1";' in src
        assert 'const a = tgt && tgt.closest ? tgt.closest("a[data-goto]") : null;' in src
        assert 'window.scrollTo({ top, left: 0, behavior: "instant" });' in src
        assert not re.search(r"location\.hash\s*=", src), \
            "锚跳转不得写 location.hash（两级路由信道污染）"

    def test_wizard_bindings_wiring(self):
        """接线：mountCalWizard 在 pageCalibration 数据到位后调用（list=
        步 3 守卫零新请求）+ bindClickRows→showPage(row.dataset.go) 单源 +
        守卫填充切页取消短路（aborted 不写隐藏区）+ #105 探测故障兜底。"""
        src = _src("view_calibration.js")
        assert "mountCalWizard(v, list);" in src
        assert 'bindClickRows(flow, (row) => showPage(row.dataset.go), "[data-go]")' in src
        assert "if (cat.aborted || dir.aborted) return;" in src
        assert ".catch(() => { /* #105：守卫探测故障静默" in src
        assert "fillCalWizardGuards(runsList);" in src

    def test_existing_page_red_lines(self):
        """红线钉：向导是新增块——既有行为锚逐字节在位（表格/排序/深链/
        空态/详情/演化图零改动；本钉消费关键串，任何"顺手重构"触碰即红）。"""
        src = _src("view_calibration.js")
        # 既有数据面（清单+演化双拉、切页取消短路）
        assert 'apiFetch("/api/calibration", { signal: viewSignal("calibration") })' in src
        assert 'apiFetch("/api/cross_fidelity", { signal: viewSignal("calibration") })' in src
        assert "if (runs.aborted || evo.aborted) return;" in src
        # 既有表：可排序 + 点行详情 + 空态三件式 + verdict 徽章单源
        assert 'bindClickRows(tbody, (tr) => loadCalibration(tr.dataset.rid), "tr[data-rid]")' in src
        assert "const scal = makeSortable(T.$(\"cal-table\"));" in src
        assert '<tr><td colspan="7">${kitEmptyState(t("calibration.empty"))}</td></tr>' in src
        assert "const b = kitVerdictBadge(r.verdict);" in src
        # 既有深链与详情 hash 回写
        assert "consumeCalibrationPendingId()" in src
        assert '_syncRouteHash("calibration", runId);' in src
        # 既有演化图 ρ 门
        assert "markline: [{ yAxis: 0.8 }]" in src

    def test_i18n_wiz_keys_complete_bilingual(self):
        """词表完整性：全部 wiz_* 键 zh/en 双语在档（node 行为钉逐键取值
        非空 + t() 插值面可用）；view_calibration 只消费在档键（悬空/
        死键双向由 test_ui_i18n 棘轮常驻，此处钉本席键域）。"""
        out = _run_node_js(
            "const m = await import('./pages/i18n.js');\n"
            "const keys = " + json.dumps(list(_WIZ_KEYS)) + ";\n"
            "const r = { missing: [], empty: [], tpl: '' };\n"
            "for (const k of keys) {\n"
            "  const e = m.LOCALES[k];\n"
            "  if (!e) { r.missing.push(k); continue; }\n"
            "  if (!String(e.zh || '').trim() || !String(e.en || '').trim())\n"
            "    r.empty.push(k);\n"
            "}\n"
            "r.tpl = m.t('calibration.wiz_step_aria_tpl', { n: 2, name: 'X' });\n"
            "console.log(JSON.stringify(r));\n")
        assert out["missing"] == [], f"词表缺键: {out['missing']}"
        assert out["empty"] == [], f"双语缺档: {out['empty']}"
        assert "2" in out["tpl"] and "X" in out["tpl"]

    def test_wiz_values_html_free_and_guard_texts_present(self):
        """词表值零 HTML 标签/零字符实体（i18n 骨架钉同口径本地复验；
        本席静态文案走 data-i18n→textContent 注入口——textContent 不解码
        实体，值含 &lt; 会按字面显示，真服走查实证，故键域内一律零尖括号
        零实体）；三步守卫文案键域齐（ok_tpl 带 {n} 插值位）。"""
        i18n = _src("i18n.js")
        block = i18n[i18n.index("calibration.wiz_title"):
                     i18n.index("calibration.wiz_g_unknown") + 200]
        assert "&lt;" not in block and "&gt;" not in block, \
            "textContent 注入口不解码实体——值禁用 &lt;/&gt;（走查实证）"
        for key in _WIZ_KEYS:
            assert f'"{key}"' in i18n
        assert "{n}" in i18n[i18n.index('"calibration.wiz_g1_ok_tpl"'):
                             i18n.index('"calibration.wiz_g1_empty"')]


# ══════════════════ 向导行为钉（node 导出纯函数/探测） ══════════════════


class TestWizardBehavior:
    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_module_imports_clean_with_exports(self):
        """view_calibration（+router 链）node 裸 import 零环零顶层爆炸；
        向导导出面在位（countYamlEntries/双探测/wizGuardText）。"""
        out = _run_node_js(
            "const m = await import('./pages/view_calibration.js');\n"
            "console.log(JSON.stringify({\n"
            "  count: typeof m.countYamlEntries,\n"
            "  cat: typeof m.probeRecipesCatalog,\n"
            "  dir: typeof m.probeRecipesDir,\n"
            "  guard: typeof m.wizGuardText,\n"
            "  page: typeof m.pageCalibration,\n"
            "}));\n")
        assert out == {"count": "function", "cat": "function",
                       "dir": "function", "guard": "function",
                       "page": "function"}

    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_count_yaml_entries_truth_table(self):
        """计数纯函数真值表：yaml/yml 双后缀、大小写不敏感、目录恒不计
        （目录名带 .yaml 后缀同样不计——kind 判据优先于名字判据）、
        null/恶输入返 0 不炸。"""
        out = _run_node_js(
            "const m = await import('./pages/view_calibration.js');\n"
            "const es = [{ name: 'a.yaml', kind: 'file' },\n"
            "  { name: 'B.YML', kind: 'file' },\n"
            "  { name: 'recipes', kind: 'dir' },\n"
            "  { name: 'trap.yaml', kind: 'dir' },\n"
            "  { name: 'notes.txt', kind: 'file' }, null];\n"
            "console.log(JSON.stringify({\n"
            "  mixed: m.countYamlEntries(es),\n"
            "  none: m.countYamlEntries([{ name: 'x.txt', kind: 'file' }]),\n"
            "  bad: m.countYamlEntries(null),\n"
            "  notArray: m.countYamlEntries('recipes'),\n"
            "}));\n")
        assert out == {"mixed": 2, "none": 0, "bad": 0, "notArray": 0}

    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_probe_catalog_branch_matrix_explicit(self):
        """目录探测逐分支显式（独立桩进程）：two/zero/bad/throw 四态。"""
        out = _run_node_js(
            "const m = await import('./pages/view_calibration.js');\n"
            "async function run(mode) {\n"
            "  const saved = globalThis.fetch;\n"
            "  globalThis.fetch = async () => {\n"
            "    if (mode === 'throw') throw new Error('net');\n"
            "    const env = mode === 'two'\n"
            "      ? { ok: true, recipes: [1, 2] }\n"
            "      : mode === 'zero' ? { ok: true, recipes: [] }\n"
            "      : { ok: false, errors: ['x'] };\n"
            "    return { json: async () => env };\n"
            "  };\n"
            "  try { return await m.probeRecipesCatalog(); }\n"
            "  finally { globalThis.fetch = saved; }\n"
            "}\n"
            "const r = {};\n"
            "r.two = await run('two');\n"
            "r.zero = await run('zero');\n"
            "r.bad = await run('bad');\n"
            "r.throw = await run('throw');\n"
            "console.log(JSON.stringify(r));\n")
        assert out["two"] == {"state": "ok", "n": 2}
        assert out["zero"] == {"state": "empty", "n": 0}
        assert out["bad"] == {"state": "unknown", "n": 0}
        assert out["throw"] == {"state": "unknown", "n": 0}

    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_probe_dir_three_branches_journeyb_form(self):
        """fs/list 探测（journeyB recipeFileExists 家法）：在盘 .yaml 计数
        →ok / 目录在但无配方=empty / 围栏拒绝（目录不存在，ok:false）=
        unknown 如实——不冒充 empty 也不拦主路径。"""
        out = _run_node_js(
            "const m = await import('./pages/view_calibration.js');\n"
            "async function run(env, throwIt) {\n"
            "  const saved = globalThis.fetch;\n"
            "  globalThis.fetch = async () => {\n"
            "    if (throwIt) throw new Error('net');\n"
            "    return { json: async () => env };\n"
            "  };\n"
            "  try { return await m.probeRecipesDir(); }\n"
            "  finally { globalThis.fetch = saved; }\n"
            "}\n"
            "const seeded = { ok: true, path: 'recipes', parent: '.',\n"
            "  entries: [{ name: 'a.yaml', kind: 'file' },\n"
            "            { name: 'b.YML', kind: 'file' },\n"
            "            { name: 'sub', kind: 'dir' }] };\n"
            "const r = {};\n"
            "r.seeded = await run(seeded);\n"
            "r.emptyDir = await run({ ok: true, entries: [] });\n"
            "r.fenced = await run({ ok: false, error: '目录不存在: recipes' });\n"
            "r.throw = await run(null, true);\n"
            "console.log(JSON.stringify(r));\n")
        assert out["seeded"] == {"state": "ok", "n": 2}
        assert out["emptyDir"] == {"state": "empty", "n": 0}
        assert out["fenced"] == {"state": "unknown", "n": 0}
        assert out["throw"] == {"state": "unknown", "n": 0}

    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_wiz_guard_text_matrix(self):
        """守卫文本矩阵：三步 × ok（{n} 插值）/empty/unknown；未知 kind 与
        畸形 probe=unknown 中性文案。"""
        out = _run_node_js(
            "const m = await import('./pages/view_calibration.js');\n"
            "const r = {};\n"
            "r.g1ok = m.wizGuardText('catalog', { state: 'ok', n: 3 });\n"
            "r.g1empty = m.wizGuardText('catalog', { state: 'empty', n: 0 });\n"
            "r.g2ok = m.wizGuardText('disk', { state: 'ok', n: 5 });\n"
            "r.g2empty = m.wizGuardText('disk', { state: 'empty', n: 0 });\n"
            "r.g3ok = m.wizGuardText('runs', { state: 'ok', n: 7 });\n"
            "r.g3empty = m.wizGuardText('runs', { state: 'empty', n: 0 });\n"
            "r.unknown = m.wizGuardText('runs', { state: 'unknown', n: 0 });\n"
            "r.badKind = m.wizGuardText('nope', { state: 'ok', n: 1 });\n"
            "r.badProbe = m.wizGuardText('runs', null);\n"
            "console.log(JSON.stringify(r));\n")
        assert "3" in out["g1ok"] and out["g1ok"] != out["g2ok"]
        assert out["g1empty"] != out["g1ok"]
        assert "5" in out["g2ok"] and "7" in out["g3ok"]
        unknown = out["unknown"]
        assert unknown == out["badKind"] == out["badProbe"]
        assert "不影响使用" in unknown


# ══════════════════ 真服钉（TestClient 内存态，tmp 隔离） ══════════════════


class TestWizardRealServer:
    def test_real_server_envelopes_feed_probes(self, client, _iso):
        """真服信封 → 前端探测函数（E2E 组合语义）：seed 配方后 /api/recipes
        与 /api/fs/list 只读信封注入桩 fetch，probe 两函数真执行=ok/1；
        countYamlEntries 消费真 entries=1。"""
        rdir = _iso / "recipes"
        rdir.mkdir()
        (rdir / "wilkinson_pd_v1.yaml").write_text(_RECIPE_YAML, encoding="utf-8")
        env_cat = client.get("/api/recipes").json()
        assert env_cat["ok"] is True
        assert [r["path"] for r in env_cat["recipes"]] == \
            ["recipes/wilkinson_pd_v1.yaml"]
        env_dir = client.get("/api/fs/list", params={"path": "recipes"}).json()
        assert env_dir["ok"] is True
        assert env_dir["entries"][0]["name"] == "wilkinson_pd_v1.yaml"
        assert _NODE is not None
        out = _run_node_js(
            "const m = await import('./pages/view_calibration.js');\n"
            "const CAT = " + json.dumps(env_cat, ensure_ascii=True) + ";\n"
            "const DIR = " + json.dumps(env_dir, ensure_ascii=True) + ";\n"
            "globalThis.fetch = async (url) => ({ json: async () =>\n"
            "  String(url).includes('/api/recipes') ? CAT : DIR });\n"
            "const r = {};\n"
            "r.cat = await m.probeRecipesCatalog();\n"
            "r.dir = await m.probeRecipesDir();\n"
            "r.count = m.countYamlEntries(DIR.entries);\n"
            "r.g1 = m.wizGuardText('catalog', r.cat);\n"
            "r.g2 = m.wizGuardText('disk', r.dir);\n"
            "console.log(JSON.stringify(r));\n")
        assert out["cat"] == {"state": "ok", "n": 1}
        assert out["dir"] == {"state": "ok", "n": 1}
        assert out["count"] == 1
        assert "1" in out["g1"] and "1" in out["g2"]

    def test_real_server_empty_workspace_honest_states(self, client, _iso):
        """空工作台语义（诚实三态）：无 recipes 目录——/api/recipes
        ok+空列表（catalog 探测=empty 如实）；fs/list 围栏拒绝 ok:false
        （disk 探测=unknown 如实，不冒充 empty）；node 端到端复演两态。"""
        env_cat = client.get("/api/recipes").json()
        assert env_cat["ok"] is True and env_cat["recipes"] == []
        env_dir = client.get("/api/fs/list", params={"path": "recipes"}).json()
        assert env_dir["ok"] is False
        assert _NODE is not None
        out = _run_node_js(
            "const m = await import('./pages/view_calibration.js');\n"
            "const CAT = " + json.dumps(env_cat, ensure_ascii=True) + ";\n"
            "const DIR = " + json.dumps(env_dir, ensure_ascii=True) + ";\n"
            "globalThis.fetch = async (url) => ({ json: async () =>\n"
            "  String(url).includes('/api/recipes') ? CAT : DIR });\n"
            "const r = {};\n"
            "r.cat = await m.probeRecipesCatalog();\n"
            "r.dir = await m.probeRecipesDir();\n"
            "r.g1 = m.wizGuardText('catalog', r.cat);\n"
            "r.g2 = m.wizGuardText('disk', r.dir);\n"
            "console.log(JSON.stringify(r));\n")
        assert out["cat"] == {"state": "empty", "n": 0}
        assert out["dir"] == {"state": "unknown", "n": 0}
        assert "未检测到配方" in out["g1"] or "No recipes detected" in out["g1"]
        assert "不影响使用" in out["g2"] or "never blocks" in out["g2"]

    def test_real_server_seeded_empty_dir_gives_empty_state(self, client, _iso):
        """recipes/ 目录在但空：两探测同出 empty（守卫行指向第 1 步），
        零 unknown 混入——围栏拒绝（目录缺）与空目录两形态语义分立。"""
        (_iso / "recipes").mkdir()
        env_cat = client.get("/api/recipes").json()
        env_dir = client.get("/api/fs/list", params={"path": "recipes"}).json()
        assert env_cat["ok"] is True and env_cat["recipes"] == []
        assert env_dir["ok"] is True and env_dir["entries"] == []
        assert _NODE is not None
        out = _run_node_js(
            "const m = await import('./pages/view_calibration.js');\n"
            "const CAT = " + json.dumps(env_cat, ensure_ascii=True) + ";\n"
            "const DIR = " + json.dumps(env_dir, ensure_ascii=True) + ";\n"
            "globalThis.fetch = async (url) => ({ json: async () =>\n"
            "  String(url).includes('/api/recipes') ? CAT : DIR });\n"
            "const cat = await m.probeRecipesCatalog();\n"
            "const dir = await m.probeRecipesDir();\n"
            "console.log(JSON.stringify({ cat, dir }));\n")
        assert out["cat"]["state"] == "empty" and out["dir"]["state"] == "empty"

    def test_page_module_chain_serves_wizard(self, client):
        """页面载荷链：pages.js 懒加载链 + view_calibration 模块体含向导
        块（真服 static 挂载面——浏览器实际执行的代码在档）。"""
        pages_js = client.get("/static/pages.js")
        assert pages_js.status_code == 200
        assert '_lazyView("calibration", "view_calibration.js"' in pages_js.text
        vc = client.get("/static/pages/view_calibration.js")
        assert vc.status_code == 200
        body = vc.text
        assert "id='cal-wizard'" in body
        assert "data-go='recipe'" in body and "data-go='solvers'" in body \
            and "data-go='guide'" in body
        assert 'showPage(row.dataset.go)' in body
        # i18n 键面随模块链可达（词表是静态 import，随 index 载荷入浏览器）
        i18n = client.get("/static/pages/i18n.js")
        assert i18n.status_code == 200
        for key in ("calibration.wiz_title", "calibration.wiz_g_unknown"):
            assert f'"{key}"' in i18n.text
