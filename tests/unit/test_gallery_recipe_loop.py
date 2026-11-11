"""T-Q18（aurora_q Q-W9-1R）模板画廊→配方闭环 UX 端到端钉。

验收核心=外部用户视角走查链（画廊→导出→落盘 recipes/→列表自动收录→
validate→run fake 全绿，每步都是外部用户在 UI/CLI 真实触达的面）：

- 走查链 ≥6 步断言（parametrize 双形态：cpw=template 直跑 / wilkinson=
  model 优化链，service/template_recipe_service 单源同款——UI POST
  /api/template-recipe/export 与 CLI templates export-recipe 薄壳同源）；
- recipes/ 预置件防腐钉：T-Q18 新增 4 份（cpw/wilkinson/patch/branchline
  _v1，经 export-recipe 产线生成）validate+fake run 全绿 + 参数逐键
  =TEMPLATE_NOMINAL（铁律 7）+ 频带派生钉（patch 单端口族=专利 4 Fix3
  宽带 0.70，多端口族 0.96）；
- UI 面钉（源码级静态扫描）：卡片导出入口（data-gal-export）/三步提示条
  单点（exportStepsBarHtml）/抽屉结果接线/词表键 zh-en 双语+占位符对齐+
  view_gallery 消费互证+词表值零 HTML；
- 刷新语义钉（件3）：list_recipes live 重扫（加文件即见，零缓存失效面）+
  导出落盘→列表自动含新配方 + view_recipe.js loadCatalog 进页即拉（源码
  钉）+ palette 60s TTL（源码钉）。

隔离纪律：走查链/预置件 run 全部 monkeypatch.chdir(tmp_path)（#144 家族：
run 目录与 recipes 守卫解析取 cwd——真实 runs/ 湖与 recipes/ 零写入，
run 目录落 pytest tmp）；零网络、零真机、runs/ 湖零写入。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from rfauto.service.api.run_core import run_once, validate_recipe
from rfauto.service.r3_services.fence import list_recipes
from rfauto.service.template_recipe_service import (
    build_template_recipe,
    export_template_recipe,
)

_REPO = Path(__file__).resolve().parents[2]
_REPO_RECIPES = _REPO / "recipes"
_PAGES = _REPO / "src" / "rfauto" / "ui" / "static" / "pages"

#: T-Q18 新增预置件（export-recipe 产线生成，防腐蚀钉对象）。
_NEW_PRESETS = {
    "cpw_v1.yaml": "cpw",
    "wilkinson_v1.yaml": "wilkinson",
    "patch_v1.yaml": "patch",
    "branchline_v1.yaml": "branchline",
}

#: T-Q18 新增词表键（zh/en 双语 + 占位符对齐 + 消费互证对象）。
_NEW_I18N_KEYS = (
    "gallery.card_export_aria_tpl",
    "gallery.export_steps_title",
    "gallery.export_step1_done",
    "gallery.export_step2_validate",
    "gallery.export_step3_run",
    "gallery.export_steps_refresh",
)

_GALLERY_JS = (_PAGES / "view_gallery.js").read_text(encoding="utf-8")
_I18N_JS = (_PAGES / "i18n.js").read_text(encoding="utf-8")
_RECIPE_JS = (_PAGES / "view_recipe.js").read_text(encoding="utf-8")
_PALETTE_JS = (_REPO / "src" / "rfauto" / "ui" / "static" / "palette.js"
               ).read_text(encoding="utf-8")
_NODE = shutil.which("node")


# ─── 1. 外部用户走查链（验收核心；每步≥1 断言，7 步全绿）─────────────────────


class TestGalleryToRecipeWalkthrough:
    """画廊→导出→落盘 recipes/→列表自动收录→validate→run fake→复扫一致。

    双形态 parametrize：cpw=template 形态（openEMS 模板直跑，fake 通道
    路由 run_template_recipe）；wilkinson=model 形态（既有优化模型链）。
    全程 chdir tmp_path——真实 runs/ 湖与 recipes/ 零写入（#144 隔离口径）。
    """

    @pytest.mark.parametrize(
        "case",
        [
            pytest.param(("cpw", "cpw_v1.yaml", "template"), id="template-cpw"),
            pytest.param(
                ("wilkinson", "wilkinson_v1.yaml", "model"), id="model-wilkinson"),
        ],
    )
    def test_gallery_export_list_validate_run_chain(
            self, case, tmp_path, monkeypatch):
        family, fname, form = case
        monkeypatch.chdir(tmp_path)

        # 步 1（画廊）：外部用户在画廊页看到目标模板卡（含名义参数面）。
        from rfauto.service.gallery_service import gallery_cards

        gal = gallery_cards()
        assert gal["ok"] is True
        names = [c["name"] for c in gal["cards"]]
        assert family in names, f"画廊卡清单缺目标模板 {family}"
        card = next(c for c in gal["cards"] if c["name"] == family)
        assert card["nominal_params"], "画廊卡缺名义参数面（导出数据源）"

        # 步 2（导出）：UI「导出配方」按钮 POST 同源 service——ok 信封 +
        # yaml 文本 + 形态正确 + 参数逐键=注册表归档名义值（铁律 7）。
        from rfauto.adapters.oe_templates.registry import TEMPLATE_NOMINAL

        r = export_template_recipe(family)
        assert r["ok"] is True, r.get("errors")
        assert r["form"] == form
        assert isinstance(r["yaml"], str) and r["yaml"].strip()
        assert r["recipe"]["params"] == dict(TEMPLATE_NOMINAL[family])

        # 步 3（落盘 recipes/）：用户复制粘贴/CLI --out 的等价面——recipe_guard
        # explicit 档原地写出（导出预览不落盘，T-Q14 口径；落盘是用户动作）。
        w = export_template_recipe(family, f"recipes/{fname}")
        assert w["ok"] is True, w.get("errors")
        assert Path(f"recipes/{fname}").exists()

        # 步 4（列表自动收录）：配方页目录/命令面板数据源 list_recipes()
        # 自动含新配方——零手动注册动作（件3 刷新语义的走查实证）。
        lst = list_recipes()
        paths = [e["path"] for e in lst["recipes"]]
        assert f"recipes/{fname}" in paths
        entry = next(e for e in lst["recipes"]
                     if e["path"] == f"recipes/{fname}")
        assert entry["kind"] == "original"

        # 步 5（validate）：导出产物过配方校验器。
        v = validate_recipe(f"recipes/{fname}")
        assert v["ok"] is True, (fname, v.get("errors"))

        # 步 6（run fake 全绿）：零 license 试跑（template 形态路由
        # run_template_recipe；model 形态走既有优化模型链）——run 目录/
        # 报告落盘（pytest tmp，非真实 runs/ 湖）。
        rr = run_once(f"recipes/{fname}", adapter_name="fake")
        assert rr["ok"] is True, (fname, rr.get("errors"))
        assert Path(rr["run_dir"]).exists()
        assert Path(rr["report"]).exists()
        if form == "template":
            # 模板直跑链信封多带 touchstone 面（写出秩=network 实际秩）。
            assert Path(rr["touchstone"]).exists()

        # 步 7（复扫一致）：二次 list_recipes() 仍收录且计数自洽——
        # live 扫描无缓存漂移（两次调用之间零写动作）。
        lst2 = list_recipes()
        assert (f"recipes/{fname}"
                in [e["path"] for e in lst2["recipes"]])
        assert lst2["groups"]["originals"] == lst["groups"]["originals"]


# ─── 2. recipes/ 预置件防腐钉（T-Q18 新增 4 份）──────────────────────────────


class TestRecipePresetsTQ18:
    """export-recipe 产线生成的预置件三重钉：validate+fake run 全绿 /
    参数逐键=TEMPLATE_NOMINAL（铁律 7）/ 频带=导出面确定性派生。"""

    @pytest.mark.parametrize("fname,family", sorted(_NEW_PRESETS.items()))
    def test_preset_validates_and_fake_runs(self, fname, family,
                                            tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        src = _REPO_RECIPES / fname
        assert src.exists(), f"T-Q18 预置配方缺失: {src}"
        target = tmp_path / fname
        target.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        v = validate_recipe(target)
        assert v["ok"] is True, (fname, v.get("errors"))
        r = run_once(target, adapter_name="fake")
        assert r["ok"] is True, (fname, r.get("errors"))

    @pytest.mark.parametrize("fname,family", sorted(_NEW_PRESETS.items()))
    def test_preset_params_equal_registry_nominal(self, fname, family):
        """铁律 7：预置件参数值逐键=TEMPLATE_NOMINAL（零手拍数字）。"""
        from rfauto.adapters.oe_templates.registry import TEMPLATE_NOMINAL

        data = yaml.safe_load(
            (_REPO_RECIPES / fname).read_text(encoding="utf-8"))
        assert data["params"] == dict(TEMPLATE_NOMINAL[family]), fname

    @pytest.mark.parametrize("fname,family", sorted(_NEW_PRESETS.items()))
    def test_preset_setup_matches_regenerated_export(self, fname, family):
        """setup 段（solver/频带/点数）=现导出面再生逐键一致——预置件随
        导出缺省演化（patch 单端口族已带专利 4 Fix3 宽带 0.70 面）。"""
        data = yaml.safe_load(
            (_REPO_RECIPES / fname).read_text(encoding="utf-8"))
        fresh = build_template_recipe(family)
        assert data["setup"] == fresh["setup"], fname

    def test_patch_preset_carries_single_port_wide_band_fix3(self):
        """专利 4 Fix3（commit dc1c8761）钉：单端口族导出频带=f0/0.70 对称
        宽带（≈2f0 全带宽，窄带下真谐振落带外观感根治）——patch 新预置件
        照新导出面生成（n_ports=1 → [1.68, 3.428571]）。"""
        from rfauto.adapters.oe_templates.registry import TEMPLATE_META

        data = yaml.safe_load(
            (_REPO_RECIPES / "patch_v1.yaml").read_text(encoding="utf-8"))
        f0 = float(TEMPLATE_META["patch"]["f0_ghz"])
        assert int(TEMPLATE_META["patch"]["n_ports"]) == 1
        assert data["setup"]["freq_range_ghz"] == [
            round(f0 * 0.70, 6), round(f0 / 0.70, 6)]

    def test_multi_port_presets_keep_narrow_band(self):
        """多端口族（cpw/wilkinson/branchline）导出频带维持窄带 0.96
        （Fix3 只放宽单端口族；同笔钉住两种口径不互相漂移）。"""
        from rfauto.adapters.oe_templates.registry import TEMPLATE_META

        for fname, family in (
                ("cpw_v1.yaml", "cpw"),
                ("wilkinson_v1.yaml", "wilkinson"),
                ("branchline_v1.yaml", "branchline")):
            data = yaml.safe_load(
                (_REPO_RECIPES / fname).read_text(encoding="utf-8"))
            assert int(TEMPLATE_META[family]["n_ports"]) != 1
            f0 = float(TEMPLATE_META[family]["f0_ghz"])
            assert data["setup"]["freq_range_ghz"] == [
                round(f0 * 0.96, 6), round(f0 / 0.96, 6)], fname

    def test_pifa_preset_still_registry_nominal(self):
        """T-Q14 既有 3 份预置件回归锚：pifa 参数仍=注册表名义值（本席
        零触碰；防腐钉顺带覆盖——monopole/mline 由
        test_template_recipe_path.TestRecipePresets 既有钉守护）。"""
        from rfauto.adapters.oe_templates.registry import TEMPLATE_NOMINAL

        data = yaml.safe_load(
            (_REPO_RECIPES / "pifa_v1.yaml").read_text(encoding="utf-8"))
        assert data["params"] == dict(TEMPLATE_NOMINAL["pifa"])


# ─── 3. UI 面钉（源码级静态扫描 + node 双语行为）─────────────────────────────


class TestGalleryCardExportSurface:
    """卡片级导出入口 + 三步提示条的 view_gallery.js 源码钉。"""

    def test_card_export_entry_present(self):
        """卡片级入口：data-gal-export 钮（aria-label 卡名消歧）+ 卡内导出槽。"""
        assert "data-gal-export='" in _GALLERY_JS, "卡片导出钮缺席"
        assert "gallery.card_export_aria_tpl" in _GALLERY_JS, (
            "卡片导出 aria 词表键未消费")
        assert "data-slot='card-export'" in _GALLERY_JS, "卡内导出槽缺席"
        # 既有详情钮/抽屉入口零回归（T-Q14 面原样在位）。
        assert "data-gal='" in _GALLERY_JS
        assert "gallery.detail_btn" in _GALLERY_JS

    def test_three_step_bar_single_point_and_wiring(self):
        """三步提示条单点（exportStepsBarHtml）+ 卡/抽屉双消费接线。"""
        fn = re.search(
            r"function exportStepsBarHtml\(\) \{.*?\n\}", _GALLERY_JS, re.S)
        assert fn, "三步提示条单点函数缺席"
        for k in _NEW_I18N_KEYS:
            if k != "gallery.card_export_aria_tpl":
                assert k in fn.group(0), f"提示条缺词表键 {k}"
        card_fn = re.search(
            r"async function exportRecipeIntoCard\(.*?\n  \}", _GALLERY_JS,
            re.S)
        assert card_fn, "卡片级导出渲染函数缺席"
        assert "exportStepsBarHtml()" in card_fn.group(0), (
            "卡片级结果缺三步提示条")
        drawer_fn = re.search(
            r"async function exportRecipeInto\(.*?\n  \}", _GALLERY_JS, re.S)
        assert drawer_fn, "抽屉级导出渲染函数缺席"
        assert "exportStepsBarHtml()" in drawer_fn.group(0), (
            "抽屉级结果缺三步提示条（卡/抽屉共用单点）")

    def test_card_export_handler_wired(self):
        """导出钮 click 接线：卡内槽定位（closest .panel）+ 槽脱离文档
        不写隐藏区（UI-R12 纪律）。"""
        wiring = re.search(
            r"for \(const btn of grid\.querySelectorAll\("
            r"\"\[data-gal-export\]\"\)\)\s*\n\s*btn\.onclick",
            _GALLERY_JS)
        assert wiring, "卡片导出钮 click 接线缺席"
        assert "closest(\".panel\")" in _GALLERY_JS, "卡内槽定位缺席"
        card_fn = re.search(
            r"async function exportRecipeIntoCard\(.*?\n  \}", _GALLERY_JS,
            re.S)
        assert "slot.isConnected" in card_fn.group(0), (
            "槽脱离文档守卫缺席（UI-R12 不写隐藏区）")

    def test_steps_bar_no_raw_api_interpolation(self):
        """XSS 源钉自证（局部棘轮）：三步条与卡片级渲染函数内零裸插值——
        插值全部 t()/esc() 出口（与 test_ui_xss_escape 全文件扫描同口径）。"""
        for fname in (r"function exportStepsBarHtml\(\) \{.*?\n\}",
                      r"async function exportRecipeIntoCard\(.*?\n  \}"):
            fn = re.search(fname, _GALLERY_JS, re.S)
            assert fn, f"函数缺席: {fname}"
            raw = re.findall(r"\$\{\s*(?!escAttr\(|esc\(|t\(|T\.|\})[^}]*\.",
                             fn.group(0))
            assert not raw, f"裸 API 插值面: {raw}"


class TestGalleryExportI18nKeys:
    """T-Q18 新增词表键：zh/en 双语 + 占位符对齐 + 值零 HTML + 消费互证。"""

    def test_new_keys_defined_and_consumed(self):
        """键集互证（本文件局部版）：6 新键 i18n.js 定义 + view_gallery.js
        消费（缺定义=悬空引用即红；缺消费=死键即红——与 test_ui_i18n
        TestKeySetCrossValidation 同口径）。"""
        for k in _NEW_I18N_KEYS:
            assert f'"{k}"' in _I18N_JS, f"词表缺键: {k}"
            assert k in _GALLERY_JS, f"view_gallery 未消费: {k}"

    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_new_keys_bilingual_and_placeholder_parity(self):
        """node 真执行：新键 zh/en 真值齐全 + {占位符} 集合两语一致 +
        值零 HTML（htmlRe 同 test_ui_i18n 口径）+ en 语料零 Han。"""
        keys = json.dumps(list(_NEW_I18N_KEYS))
        js = """
const m = await import('./pages/i18n.js');
const keys = __KEYS__;
const errs = [];
const htmlRe = /<\\/?[a-zA-Z]/;
const hanRe = /[\\u3400-\\u4dbf\\u4e00-\\u9fff]/;
const phRe = /\\{(\\w+)\\}/g;
for (const k of keys) {
  const e = m.LOCALES[k];
  if (!e) { errs.push('missing: ' + k); continue; }
  if (typeof e.zh !== 'string' || !e.zh) errs.push('zh missing: ' + k);
  if (typeof e.en !== 'string' || !e.en) errs.push('en missing: ' + k);
  if (htmlRe.test(e.zh) || htmlRe.test(e.en)) errs.push('html in value: ' + k);
  if (hanRe.test(e.en)) errs.push('han in en: ' + k);
  const ph = (s) => [...String(s).matchAll(phRe)].map((x) => x[1]).sort().join(',');
  if (e.zh && e.en && ph(e.zh) !== ph(e.en)) errs.push(
    'placeholder mismatch: ' + k + ' zh=' + ph(e.zh) + ' en=' + ph(e.en));
}
if (errs.length) throw new Error(errs.join('; '));
console.log('ok:tq18-i18n');
""".replace("__KEYS__", keys)
        out = subprocess.run([_NODE, "--input-type=module", "-e", js],
                             capture_output=True, text=True, timeout=60,
                             cwd=str(_PAGES.parent))
        assert out.returncode == 0, (
            f"node 行为核失败:\n{out.stdout[-800:]}\n{out.stderr[-800:]}")
        assert "ok:tq18-i18n" in out.stdout


# ─── 4. 配方列表刷新语义钉（件3）─────────────────────────────────────────────


class TestRecipeListRefreshSemantics:
    """"导出后列表自动含新配方"语义三钉：服务级 live 重扫 / 导出落盘即收录 /
    UI 加载点进页即拉（源码钉）。选型=自动收录（非显式刷新入口）——
    recipes/ 消费面实测三处全 live：view_recipe loadCatalog（每次进页）、
    palette（60s TTL）、list_recipes 服务（cwd 相对 Path("recipes") 实扫）。"""

    def test_live_rescan_no_cache(self, tmp_path, monkeypatch):
        """live 重扫：目录加文件后下一次 list_recipes() 即见（无缓存失效面
        ——两次调用之间零额外动作）。"""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "recipes").mkdir()
        assert list_recipes()["recipes"] == []
        minimal = {
            "recipe_version": 1,
            "model": "mline",
            "params": {},
            "setup": {"solver": "openEMS", "freq_range_ghz": [1.0, 4.0],
                      "points": 201},
        }
        (tmp_path / "recipes" / "a.yaml").write_text(
            yaml.safe_dump(minimal, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
        lst = list_recipes()
        assert [e["path"] for e in lst["recipes"]] == ["recipes/a.yaml"]

    def test_exported_recipe_auto_listed(self, tmp_path, monkeypatch):
        """导出落盘 → 列表自动含新配方（走查链步 4 的单点钉：export+
        list 两调用之间零注册/刷新动作）。"""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "recipes").mkdir()
        w = export_template_recipe("cpw", "recipes/cpw_v1.yaml")
        assert w["ok"] is True, w.get("errors")
        lst = list_recipes()
        assert "recipes/cpw_v1.yaml" in [e["path"] for e in lst["recipes"]]

    def test_view_recipe_catalog_rescans_on_page_entry(self):
        """UI 加载点（源码钉）：配方页每次进页 loadCatalog() 即拉
        /api/recipes（pageRecipe 体内直接调用）——导出落盘后切到配方页
        即见新配方；ctx.refresh 重拉同源。"""
        assert re.search(r"loadCatalog\(\);", _RECIPE_JS), (
            "loadCatalog 进页调用缺席（配方目录进页即扫语义）")
        m = re.search(r"async function loadCatalog\(\) \{.*?"
                      r'apiFetch\("/api/recipes"', _RECIPE_JS, re.S)
        assert m, "loadCatalog 数据源非 /api/recipes"

    def test_palette_recipe_source_with_ttl(self):
        """命令面板 recipes 数据源（源码钉）：/api/recipes + 60s TTL——
        导出落盘后面板 60 秒内自动收录（P8-3 TTL 缓存语义）。"""
        assert 'apiFetch("/api/recipes")' in _PALETTE_JS, (
            "palette recipes 数据源缺席")
        ttl = re.search(r"_DYN_TTL_MS\s*=\s*(\d+)", _PALETTE_JS)
        assert ttl and int(ttl.group(1)) == 60000, "palette TTL ≠ 60s"

    def test_recipe_page_ctx_refresh_wired(self):
        """配方页 PageContext refresh=配方目录重拉（源码钉）——显式刷新
        通道在位（refresh() → pageRecipe() 幂等重进）。"""
        m = re.search(r"export const recipeCtx = \{.*?\};", _RECIPE_JS, re.S)
        assert m, "recipeCtx 缺席"
        assert "refresh" in m.group(0), "recipeCtx.refresh 缺席"
