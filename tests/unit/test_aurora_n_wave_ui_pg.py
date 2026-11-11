"""aurora_n wave_ui_pg 席位回归钉：playground 对比模式 + model_card 出卡全键。

两件交付（任务书 aurora_n 前端引导线席）：

1. **playground 对比模式（纯前端，服务端零语义变化）**：探索器加第二 run
   选择器（#pg-ex-run2，缺省空=单键模式既有路径逐位保留）——同滑条/同扫参
   轴对 B run 的校准最佳代理再拉一次既有 /api/playground/explore，双预测曲
   线叠加（A=蓝 seriesBlue 既有、B=橙 seriesOrange），曲线名带各代理键
   （A/B 两键图例可读=差异区可读）。诚实跳过面：B==A 同 run 不对比；B 拉
   取失败/轴不在 B bounds（服务 ok=false）/缺同指标=状态行如实记因不硬造
   第二曲线（#122 前端同构）；B 请求不拦主曲线（#105 家法）。
2. **model_card 出卡全键验证**：本役新代理九任务名逐键 build_model_card
   （registry 卡=代码工件卡，按既有出卡器零改动）+ 合成小样本拟合冒烟
   （键活着旁证）。param_vf=模块名（surrogate/param_vf.py，T-N15）注册键
   =vf_parametric——build_model_card("param_vf") 如实 ok=False 列 available
   （不硬造别名卡，model_card_service 零改动=缺口如实登记）。

红线：零服务端语义变化（只消费既有 3 端点；单键模式逐位保留=源码钉）；
i18n zh/en 同笔（compare_b/compare_b_none/compare_b_no_metric_tpl/help_5
四键）；三禁（不 commit/不写 DEVLOG·TODO/不改 docs）。

变异验证（移除增强必红，开发期逐钉实测记录于 runs/aurora_n/wave_ui_pg/
MUTATION_LOG.md）：源码钉关键串即增强本体（删除即断言红）；node 行为钉
消费导出纯函数 compareExploreSeries（删除导出/import undefined 即红）；
真服钉消费信封形状（tmp 隔离 #144 家族口径，零触真实 runs/ 湖）。

不读网络、不启动长驻服务器（TestClient 内存态）；node 面缺 node 诚实
skip；不 commit。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_NODE = shutil.which("node")

_PG_KEYS = (
    "playground.compare_b", "playground.compare_b_none",
    "playground.compare_b_no_metric_tpl", "playground.help_5",
)
_CARD_KEYS = ("conformal", "ensemble", "mt_gp", "rff_gp", "siren",
              "deep_ensemble", "pole_residue", "vf_parametric")


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


def _seed_cal_run(root: Path, run_id: str, kind: str, *, n: int = 12) -> None:
    """tmp runs/ 种一个有校准产物的 run（samples.json+campaign.json，
    schema=surrogate_playground._load_artifacts 消费面）。两键同 bounds
    （wilkinson 族参数面）——对比模式"同一滑条"的现实形态。"""
    base = root / "runs" / run_id / "calibration"
    base.mkdir(parents=True)
    bounds = {"arm_len_mm": [15.0, 30.0], "series_w_mm": [0.4, 2.0]}
    samples = []
    for i in range(n):
        t = i / (n - 1)
        params = {"arm_len_mm": 15.0 + 15.0 * t,
                  "series_w_mm": 0.4 + 1.6 * (1.0 - t)}
        val = 1.0 + 0.08 * params["arm_len_mm"] - 0.5 * params["series_w_mm"]
        samples.append({"params": params, "metrics": {"cost": float(val)}})
    (base / "samples.json").write_text(
        json.dumps({"samples": samples, "bounds": bounds}), encoding="utf-8")
    (base / "campaign.json").write_text(json.dumps({
        "best_surrogate": kind, "augment_rho": 0.9,
        "augment_verdict": "PASS", "n_samples": n,
    }), encoding="utf-8")


# ══════════════════ 对比模式结构源码钉（新增面形态） ══════════════════


class TestComparisonStructure:
    def test_second_selector_shell_and_options_fill(self):
        """壳面：探索器工具栏第二 run 选择器（data-i18n 静态注入口）+
        help_5 引导句；选项填充：空选项=单键模式（i18n 键）+ run 清单同源
        （选项名带各 run 校准最佳代理键）。"""
        src = _src("view_playground.js")
        assert "id='pg-ex-run2'" in src, "缺第二 run 选择器"
        assert "data-i18n='playground.compare_b'" in src
        assert "<li>${t(\"playground.help_5\")}</li>" in src
        # 选项填充：空选项（单键缺省）+ runs 同源映射
        assert 'T.$("pg-ex-run2").innerHTML =' in src
        assert "playground.compare_b_none" in src
        # 空选项 value='' 是单键模式判定锚
        assert "<option value=''>" in src

    def test_compare_branch_guard_and_fetch(self):
        """对比分支：B==A 同 run 不对比 + B 探索请求=既有 explore 端点
        同参形态（同滑条 currentParams/同轴/同点数；用户动作 POST 无
        signal、长跑豁免 timeoutMs:0 与 A 同口径）。"""
        src = _src("view_playground.js")
        assert "const runB = T.$(\"pg-ex-run2\").value;" in src
        assert "if (runB && runB !== sel.value) {" in src
        # B 请求体与 A 请求同构（同滑条/同轴/同点数）
        assert src.count('apiFetch("/api/playground/explore", {') == 2, \
            "探索请求应恰两处（A/B 同端点——零新端点）"
        assert src.count("params: currentParams(),") == 2
        assert 'sweep: { axis: T.$("pg-ex-axis").value, n: +T.$("pg-ex-n").value },' in src
        assert "timeoutMs: 0" in src

    def test_compare_series_assembly_and_status(self):
        """系列组装走导出纯函数 compareExploreSeries；叠加=B 入列+A 名改带
        键；B 失败/缺指标走诚实记因（errorText/缺指标模板键）；状态行追加
        B 段（单键模式 cmpNote='' 追加空串=逐位保留）；B 色分=seriesOrange。"""
        src = _src("view_playground.js")
        assert "compareExploreSeries(r, rb, key, axisName, bodyIsLight())" in src
        assert "series[0].name = cmp.nameA;" in src
        assert "series.push(cmp.seriesB);" in src
        assert "cmpNote = errorText(rb);" in src
        assert 't("playground.compare_b_no_metric_tpl", { k: key })' in src
        assert "+ (cmpNote ? ` · B: ${cmpNote}` : \"\");" in src
        assert "THEME_COLORS.seriesOrange" in src
        # onchange 接线（B 选择器换选即重画）
        assert '["pg-ex-axis", "pg-ex-n", "pg-ex-metric", "pg-ex-run2"]' in src

    def test_exported_pure_function_shape(self):
        """导出纯函数契约：不触 DOM/网络的组装器——null（信封不 ok/畸形/
        长度失配）/ skip（缺同指标）/ {nameA, seriesB} 三态；x 四位舍入与
        A 探索曲线同口径。"""
        src = _src("view_playground.js")
        assert "export function compareExploreSeries(" in src
        assert "rb.ok !== true" in src
        assert "Object.prototype.hasOwnProperty.call(rb.curves, metricKey)" in src
        assert "vals.length !== mean.length" in src
        assert "+(+v).toFixed(4)" in src

    def test_single_mode_byte_anchors(self):
        """红线钉：单键模式既有路径逐位保留——A 曲线名/A 探索请求体/方差带/
        画布 prop/预测表全在位（任何"顺手重构"触碰即红）。"""
        src = _src("view_playground.js")
        assert 'const series = [{ name: `${key} mean`, x: xs, y: cur.mean,' in src
        assert 'color: themePick(bodyIsLight(), THEME_COLORS.seriesBlue) }];' in src
        assert 'name: `${key} ±1σ`, type: "band", x: xs,' in src
        assert "run_id: sel.value," in src
        assert 'xlabel: axisName, ylabel: key, xvalue: true, crosshair: true, height: "300px",' in src
        assert 'exportName: "explore-sweep", exportCsv: false,' in src
        assert "t(\"playground.th_nearest_tpl\", { d: r.nearest_sample.normalized_distance })" in src
        # 对比增强不新增任何 API 端点（runs/predict/explore 三面恒在；
        # explore 字面两处=A/B 同端点复用）
        assert src.count("/api/playground/") == 4

    def test_i18n_compare_keys_complete_bilingual(self):
        """词表完整性：本席四键 zh/en 双语在档 + t() 插值面可用
        （{k} 模板）；view_playground 只消费在档键（悬空/死键双向由
        test_ui_i18n 棘轮常驻，此处钉本席键域）。"""
        out = _run_node_js(
            "const m = await import('./pages/i18n.js');\n"
            "const keys = " + json.dumps(list(_PG_KEYS)) + ";\n"
            "const r = { missing: [], empty: [], tpl: '' };\n"
            "for (const k of keys) {\n"
            "  const e = m.LOCALES[k];\n"
            "  if (!e) { r.missing.push(k); continue; }\n"
            "  if (!String(e.zh || '').trim() || !String(e.en || '').trim())\n"
            "    r.empty.push(k);\n"
            "}\n"
            "r.tpl = m.t('playground.compare_b_no_metric_tpl', { k: 'cost' });\n"
            "console.log(JSON.stringify(r));\n")
        assert out["missing"] == [], f"词表缺键: {out['missing']}"
        assert out["empty"] == [], f"双语缺档: {out['empty']}"
        assert "cost" in out["tpl"]

    def test_i18n_values_html_free(self):
        """词表值零 HTML 标签/零字符实体（textContent 注入口不解码实体，
        wizard 席真服走查实证口径）；键域内零尖括号零实体。"""
        i18n = _src("i18n.js")
        block = i18n[i18n.index('"playground.compare_b"'):
                     i18n.index("queue.help_1_lead")]
        for bad in ("&lt;", "&gt;", "<b>", "<span"):
            assert bad not in block, f"textContent 注入口值禁含 {bad}"


# ══════════════════ 对比模式行为钉（node 导出纯函数） ══════════════════


class TestComparisonBehavior:
    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_module_imports_clean_with_exports(self):
        """view_playground（+router 链）node 裸 import 零环零顶层爆炸；
        对比模式导出面在位（compareExploreSeries 纯函数 + 既有两面）。"""
        out = _run_node_js(
            "const m = await import('./pages/view_playground.js');\n"
            "console.log(JSON.stringify({\n"
            "  cmp: typeof m.compareExploreSeries,\n"
            "  page: typeof m.pagePlayground,\n"
            "  ctx: typeof m.playgroundCtx.refresh,\n"
            "}));\n")
        assert out == {"cmp": "function", "page": "function",
                       "ctx": "function"}

    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_compare_series_truth_table(self):
        """compareExploreSeries 真值表：happy（A/B 名带各键+橙双色档）/
        缺同指标=skip / 信封不 ok=null / A 畸形=null / 轴长失配=null；
        x 四位舍入；B 色分亮暗两档（seriesOrange #b26a00/#ffb74d）。"""
        out = _run_node_js(
            "const m = await import('./pages/view_playground.js');\n"
            "const A = { ok: true, kind: 'nn', curves: { cost: { mean: [1, 2] } },\n"
            "  sweep: { axes_values: { a_mm: [15, 30] } } };\n"
            "const B = { ok: true, kind: 'poly_ridge',\n"
            "  curves: { cost: { mean: [1.5, 2.5] } },\n"
            "  sweep: { axes_values: { a_mm: [15, 22.5, 30] } },\n"
            "  curves_ok: 1 };\n"
            "const B2 = { ok: true, kind: 'poly_ridge',\n"
            "  curves: { cost: { mean: [1.5, 2.5, 2.9] } },\n"
            "  sweep: { axes_values: { a_mm: [15.0123456, 22.5, 30] } } };\n"
            "const r = {};\n"
            "r.happy = m.compareExploreSeries(A, B2, 'cost', 'a_mm', false);\n"
            "r.happyLight = m.compareExploreSeries(A, B2, 'cost', 'a_mm', true)\n"
            "  .seriesB.color;\n"
            "r.skip = m.compareExploreSeries(A, { ok: true, kind: 'x',\n"
            "  curves: { other: { mean: [1] } },\n"
            "  sweep: { axes_values: { a_mm: [1] } } }, 'cost', 'a_mm', false);\n"
            "r.notOk = m.compareExploreSeries(A, { ok: false, error: 'e' },\n"
            "  'cost', 'a_mm', false);\n"
            "r.badA = m.compareExploreSeries(null, B, 'cost', 'a_mm', false);\n"
            "r.lenMismatch = m.compareExploreSeries(A, B, 'cost', 'a_mm', false);\n"
            "console.log(JSON.stringify(r));\n")
        h = out["happy"]
        assert h["nameA"] == "cost mean·nn"
        assert h["seriesB"]["name"] == "cost mean·poly_ridge"
        assert h["seriesB"]["x"] == [15.0123, 22.5, 30]  # 四位舍入
        assert h["seriesB"]["y"] == [1.5, 2.5, 2.9]
        assert h["seriesB"]["color"] == "#ffb74d"  # 暗档橙
        assert out["happyLight"] == "#b26a00"  # 亮档橙
        assert out["skip"] == {"skip": True}
        assert out["notOk"] is None and out["badA"] is None
        # 轴 3 点 vs mean 2 点 → 长度失配 null（B 表用 2 点构造）
        assert out["lenMismatch"] is None


# ══════════════════ model_card 出卡全键钉（既有出卡器） ══════════════════


class TestModelCardNineKeys:
    @pytest.mark.parametrize("kind", list(_CARD_KEYS))
    def test_registry_card_buildable(self, kind: str):
        """八注册键逐键出卡：ok/kind/source/params_schema（config 形参
        面在档）/created=None（代码工件卡语义）/drift 如实 no_data。"""
        from rfauto.service.model_card_service import build_model_card

        card = build_model_card(kind, "registry")
        assert card["ok"] is True, f"{kind} 出卡失败: {card.get('error')}"
        assert card["kind"] == "surrogate"
        assert card["source"] == "registry"
        schema = card["params_schema"]
        assert isinstance(schema, list) and schema, f"{kind} params_schema 空"
        assert any(row["name"] == "config" for row in schema)
        assert card["created"] is None
        assert card["drift_status"]["verdict"] == "no_data"
        assert card["drift_status"]["available"] is False

    def test_param_vf_module_name_honest_mapping(self):
        """param_vf=模块名（T-N15 surrogate/param_vf.py）非注册键——
        build_model_card('param_vf') 如实 ok=False 并列 available 全集
        （含 vf_parametric）；不硬造别名卡=服务端零改动缺口登记。"""
        from rfauto.optimization.surrogate import surrogate_registry
        from rfauto.service.model_card_service import build_model_card

        out = build_model_card("param_vf", "registry")
        assert out["ok"] is False
        assert "param_vf" not in out["available"]["surrogate"]
        assert "vf_parametric" in out["available"]["surrogate"]
        ok = build_model_card("vf_parametric", "registry")
        assert ok["ok"] is True and ok["kind"] == "surrogate"
        # 模块↔注册键同类同源（同一 ParamVFSurrogate 工厂）
        factory = surrogate_registry.snapshot()["vf_parametric"]
        assert factory.__name__ == "ParamVFSurrogate"
        import rfauto.optimization.surrogate.param_vf as pv_mod

        assert factory.__module__ == pv_mod.__name__

    def test_registry_ids_cover_all_card_keys(self):
        from rfauto.service.model_card_service import registry_model_ids

        ids = registry_model_ids()
        missing = [k for k in _CARD_KEYS if k not in ids["surrogate"]]
        assert missing == [], f"注册表缺本役键: {missing}"

    @pytest.mark.parametrize("kind", list(_CARD_KEYS))
    def test_synthetic_small_sample_fit_smoke(self, kind: str):
        """合成小样本拟合冒烟（键活着旁证）：registry.create 最小 config +
        确定性合成样本 fit + 界中点 predict——8 键全绿（siren 快档 25 epoch）。
        失败即红（卡键对应可实例化模型是出卡面的地基）。"""
        from rfauto.optimization.surrogate import surrogate_registry

        bounds = {"a": (0.0, 1.0), "b": (0.0, 1.0)}
        t = np.linspace(0.0, 1.0, 12)
        if kind == "siren":
            cfg = {"coord_keys": ["x", "y"], "field_key": "field",
                   "epochs": 25, "width": 8, "n_hidden": 1,
                   "bounds": {"x": (0.0, 1.0), "y": (0.0, 1.0)}}
        elif kind == "conformal":
            cfg = {"base_kind": "poly_ridge", "base_config": {"bounds": bounds},
                   "bounds": dict(bounds)}
        elif kind == "ensemble":
            cfg = {"bounds": dict(bounds),
                   "members": ["poly_ridge", "huber_ridge"]}
        elif kind == "deep_ensemble":
            cfg = {"bounds": dict(bounds), "base_kind": "poly_ridge",
                   "n_members": 2, "curve_key": "cost",
                   "base_config": {"bounds": dict(bounds)}}
        elif kind in ("pole_residue", "vf_parametric"):
            cfg = {"bounds": dict(bounds), "freq_grid_ghz": (1.0, 3.0),
                   "n_freq": 33}
            if kind == "pole_residue":
                cfg["head"] = "ridge"
        else:
            cfg = {"bounds": dict(bounds)}
        # 确定性合成样本（曲线键=单谐振反射 S11，f0 随参数平移）
        if kind in ("pole_residue", "vf_parametric"):
            f = np.linspace(1.0, 3.0, 33) * 1e9
            samples = []
            for i in range(8):
                frac = i / 7.0
                params = {"a": frac, "b": 1.0 - frac}
                f0 = 1.4e9 + 1.0e9 * frac
                s = 0.05 + 0.9 / (1.0 + 1j * 25.0 * (f / f0 - f0 / f))
                samples.append({"params": params,
                                "metrics": {"s11_curve": [complex(v) for v in s]}})
        elif kind == "siren":
            samples = [{"params": {"x": float(v), "y": float(1.0 - v)},
                        "metrics": {"field": float(1.0 + 2.0 * v)}}
                       for v in t]
        else:
            samples = [{"params": {"a": float(v), "b": float(1.0 - v)},
                        "metrics": {"cost": float(1.0 + 2.0 * v)}}
                       for v in t]
        model = surrogate_registry.create(kind, config=cfg)
        model.fit(samples)
        assert model.fitted, f"{kind} 拟合后 fitted=False"
        bnds = cfg.get("bounds") or {}
        mid = {k: (float(v[0]) + float(v[1])) / 2.0 for k, v in bnds.items()}
        pred = model.predict(mid)
        assert isinstance(pred, dict) and pred, f"{kind} predict 空返回"
        # 数值面全有限（vf_parametric predict 附带 param_extrapolation
        # 判据字符串值——键面混合返回，数值面单独核）
        numeric = [v for v in pred.values()
                   if isinstance(v, (int, float)) and not isinstance(v, bool)]
        assert numeric, f"{kind} predict 无数值面: {sorted(pred)}"
        assert all(np.isfinite(float(v)) for v in numeric), \
            f"{kind} predict 数值面含非有限值: {pred}"


# ══════════════════ 真服钉（TestClient 内存态，tmp 隔离） ══════════════════


class TestPlaygroundRealServer:
    def test_two_run_explore_envelopes_feed_comparison(self, client, _iso):
        """真服信封 → 对比纯函数（E2E 组合语义）：seed 同 bounds 两校准
        run（A=poly_ridge/B=huber_ridge）→ 既有 explore 端点两信封注入
        compareExploreSeries 真执行=双键系列（A/B 名带各键、B 橙）；
        零新端点（runs/predict/explore 三面既有）。"""
        _seed_cal_run(_iso, "20261031_000000_aaaa", "poly_ridge")
        _seed_cal_run(_iso, "20261031_000100_bbbb", "huber_ridge")
        env_runs = client.get("/api/playground/runs").json()
        assert env_runs["ok"] is True and len(env_runs["runs"]) == 2
        body = {"params": {}, "sweep": {"axis": "arm_len_mm", "n": 7}}
        ea = client.post("/api/playground/explore",
                         json={**body, "run_id": "20261031_000000_aaaa"}).json()
        eb = client.post("/api/playground/explore",
                         json={**body, "run_id": "20261031_000100_bbbb"}).json()
        assert ea["ok"] is True and ea["kind"] == "poly_ridge"
        assert eb["ok"] is True and eb["kind"] == "huber_ridge"
        metric = next(iter(ea["curves"]))
        assert metric in eb["curves"], "同 bounds 两 run 应共享指标键"
        assert _NODE is not None
        out = _run_node_js(
            "const m = await import('./pages/view_playground.js');\n"
            "const A = " + json.dumps(ea, ensure_ascii=True) + ";\n"
            "const B = " + json.dumps(eb, ensure_ascii=True) + ";\n"
            "const cmp = m.compareExploreSeries(A, B, " + \
            json.dumps(metric) + ", 'arm_len_mm', false);\n"
            "console.log(JSON.stringify({ nameA: cmp.nameA,\n"
            "  nameB: cmp.seriesB.name, color: cmp.seriesB.color,\n"
            "  nB: cmp.seriesB.x.length }));\n")
        assert out["nameA"] == f"{metric} mean·poly_ridge"
        assert out["nameB"] == f"{metric} mean·huber_ridge"
        assert out["color"] == "#ffb74d"
        assert out["nB"] == 7

    def test_static_page_serves_comparison_face(self, client):
        """页面载荷链：static 挂载面浏览器实际执行的代码在档——
        view_playground 含第二选择器与对比函数；i18n 键随模块链可达。"""
        pg = client.get("/static/pages/view_playground.js")
        assert pg.status_code == 200
        assert "id='pg-ex-run2'" in pg.text
        assert "compareExploreSeries" in pg.text
        i18n = client.get("/static/pages/i18n.js")
        assert i18n.status_code == 200
        for key in _PG_KEYS:
            assert f'"{key}"' in i18n.text

    def test_missing_metric_honest_skip_note_key(self, client, _iso):
        """B 缺同指标=诚实跳过（skip 态）：不同指标键的两 run——A cost /
        B 另名指标 → compareExploreSeries skip=true（前端状态行走
        compare_b_no_metric_tpl 记因，不硬造第二曲线）。"""
        _seed_cal_run(_iso, "20261031_000000_aaaa", "poly_ridge")
        base = _iso / "runs" / "20261031_000200_cccc" / "calibration"
        base.mkdir(parents=True)
        (base / "samples.json").write_text(json.dumps({
            "samples": [{"params": {"arm_len_mm": 15.0 + 3.0 * i,
                                    "series_w_mm": 2.0 - 0.3 * i},
                         "metrics": {"other_metric": 1.0 + 0.1 * i}}
                        for i in range(6)],
            "bounds": {"arm_len_mm": [15.0, 30.0],
                       "series_w_mm": [0.4, 2.0]},
        }), encoding="utf-8")
        (base / "campaign.json").write_text(json.dumps({
            "best_surrogate": "poly_ridge", "augment_rho": 0.9,
            "augment_verdict": "PASS", "n_samples": 1,
        }), encoding="utf-8")
        body = {"params": {}, "sweep": {"axis": "arm_len_mm", "n": 5}}
        ea = client.post("/api/playground/explore",
                         json={**body, "run_id": "20261031_000000_aaaa"}).json()
        ec = client.post("/api/playground/explore",
                         json={**body, "run_id": "20261031_000200_cccc"}).json()
        assert ea["ok"] is True and ec["ok"] is True
        assert "cost" in ea["curves"] and "cost" not in ec["curves"]
        assert _NODE is not None
        out = _run_node_js(
            "const m = await import('./pages/view_playground.js');\n"
            "const i18n = await import('./pages/i18n.js');\n"
            "const A = " + json.dumps(ea, ensure_ascii=True) + ";\n"
            "const C = " + json.dumps(ec, ensure_ascii=True) + ";\n"
            "const cmp = m.compareExploreSeries(A, C, 'cost', 'arm_len_mm', false);\n"
            "console.log(JSON.stringify({ skip: cmp && cmp.skip === true,\n"
            "  note: i18n.t('playground.compare_b_no_metric_tpl', { k: 'cost' }) }));\n")
        assert out["skip"] is True
        assert "cost" in out["note"]
