"""R4 人性化席（结果数据说明文案批 2026-10-19）回归钉：算出来的东西
要有说明——用户痛点"算出来的是什么？怎么计算的？"的三面呈现层钉。

1. 画廊参数"电路作用"行（view_gallery）：paramRoleKey 两级查找（模板×
   参数覆写 ROLE_TPL_OVERRIDE → 裸键 ROLE_OVERRIDE → 名称形态学通类）
   对注册表 TEMPLATE_META 全量模板×参数对（72×324）解析出词表键；
   gallery.role_* 全部 zh/en 双语、零 HTML、且全部被视图字面引用
   （零死键）。node 真执行：覆写表/分类器从 view_gallery.js 正则提取
   （CRLF 兼容），词表自 i18n.js import——防"分类器改了没跑"漂移。
2. tune 结果卡「结果怎么读」折叠区（view_tune）：tune.res_howto_*
   （label/cost/best/pruned）四键视图接线在位（词表 zh/en 双语+零 HTML
   由 test_ui_i18n 全词表统一管，此处钉引用存在性+键在档）。
3. 校准页判定/ρ 白话（view_calibration）：清单表脚注+详情面板两处引用
   calibration.verdict_note/calibration.rho_note。

不依赖 runs/、不读网络、不启动服务器（TEMPLATE_META 为仓内注册表）。"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_NODE = shutil.which("node")

_I18N = (_STATIC / "pages" / "i18n.js").read_text(encoding="utf-8")
_GALLERY = (_STATIC / "pages" / "view_gallery.js").read_text(encoding="utf-8")
_TUNE = (_STATIC / "pages" / "view_tune.js").read_text(encoding="utf-8")
_CALIB = (_STATIC / "pages" / "view_calibration.js").read_text(encoding="utf-8")

_HOWTO_KEYS = [
    "tune.res_howto_label",
    "tune.res_howto_cost",
    "tune.res_howto_best",
    "tune.res_howto_pruned",
]
_CALIB_KEYS = ["calibration.verdict_note", "calibration.rho_note"]


def _run_node_js(js: str) -> str:
    r = subprocess.run(
        [_NODE, "--input-type=module", "-e", js],
        capture_output=True, text=True, timeout=60, cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2500:]}"
    return r.stdout


# ────────────── 1. 画廊参数"电路作用"行（node 真执行全量解析） ──────────────

@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestGalleryParamRole:
    def test_param_role_keys_resolve_all_template_params(self):
        """全量解析钉：注册表每个模板×参数对都必须经两级查找+形态学通类
        解析出一个词表键（键在档且 zh/en 双语）——分类器/覆写表回退即红
        （诚实省略仅允许出现在"注册表之外"的未知键，注册表内零遗漏）。"""
        from rfauto.adapters.openems_templates import TEMPLATE_META

        tpl_params = {name: list(meta.get("params") or [])
                      for name, meta in TEMPLATE_META.items()}
        n_pairs = sum(len(v) for v in tpl_params.values())
        assert n_pairs >= 300, f"注册表参数对数异常: {n_pairs}"
        payload = json.dumps(tpl_params, ensure_ascii=False)
        out = _run_node_js(
            "import { readFileSync } from 'node:fs';\n"
            "const m = await import('./pages/i18n.js');\n"
            "const src = readFileSync('./pages/view_gallery.js', 'utf-8');\n"
            "const grab = (re) => { const x = src.match(re);\n"
            "  if (!x) throw new Error('提取失败: ' + re); return x[0]; };\n"
            "const tplTbl = grab(/const ROLE_TPL_OVERRIDE = \\{[\\s\\S]*?\\r?\\n\\};/);\n"
            "const bareTbl = grab(/const ROLE_OVERRIDE = \\{[\\s\\S]*?\\r?\\n\\};/);\n"
            "const fn = grab(/function paramRoleKey\\(c, k\\) \\{[\\s\\S]*?\\r?\\n\\}/);\n"
            "const evalObj = (t) => eval('(' + t.slice(t.indexOf('{'),\n"
            "  t.lastIndexOf('}') + 1) + ')');\n"
            "const ROLE_TPL_OVERRIDE = evalObj(tplTbl);\n"
            "const ROLE_OVERRIDE = evalObj(bareTbl);\n"
            "const paramRoleKey = eval('(' + fn + ')');\n"
            f"const tplParams = {payload};\n"
            "const bad = [];\n"
            "let hit = 0;\n"
            "for (const [tpl, params] of Object.entries(tplParams))\n"
            "  for (const p of params) {\n"
            "    const key = paramRoleKey({ name: tpl }, p);\n"
            "    if (!key) { bad.push(tpl + '.' + p + ' -> null'); continue; }\n"
            "    const e = m.LOCALES[key];\n"
            "    if (!e) { bad.push(tpl + '.' + p + ' -> ' + key + ' 缺键'); continue; }\n"
            "    if (typeof e.zh !== 'string' || !e.zh\n"
            "      || typeof e.en !== 'string' || !e.en)\n"
            "      bad.push(tpl + '.' + p + ' -> ' + key + ' zh/en 缺半边');\n"
            "    else hit++;\n"
            "  }\n"
            "const dead = Object.keys(m.LOCALES)\n"
            "  .filter((k) => k.startsWith('gallery.role_') && !src.includes('\"' + k + '\"'));\n"
            "if (bad.length) throw new Error('未解析/缺键 '\n"
            "  + bad.length + ': ' + bad.slice(0, 20).join('; '));\n"
            "if (dead.length) throw new Error('gallery.role_* 死键: ' + dead.join(','));\n"
            "if (hit !== " + str(n_pairs) + ") throw new Error('命中数漂移 ' + hit);\n"
            "console.log('ok:role:' + hit);\n")
        assert f"ok:role:{n_pairs}" in out

    def test_role_tables_literal_key_discipline(self):
        """两级覆写表的值必须全为 gallery.role_* 字面（禁动态拼键——
        动态拼键逃逸 _PAGE_KEY_LIT 键集互证，死键无从抓起）。"""
        for tbl in ("ROLE_TPL_OVERRIDE", "ROLE_OVERRIDE"):
            m = re.search(r"const " + tbl + r" = \{[\s\S]*?\r?\n\};", _GALLERY)
            assert m, f"{tbl} 字面表缺席"
            vals = re.findall(r'["\w]+:\s*"([^"]+)"', m.group(0))
            assert vals, f"{tbl} 空表"
            off = [v for v in vals if not v.startswith("gallery.role_")]
            assert not off, f"{tbl} 值越出 gallery.role_* 键域: {off[:5]}"

    def test_role_line_rendering_in_drawer(self):
        """渲染面钉：抽屉参数行消费 paramRoleKey，命中时含义单元格内加
        ↳ 细释行（词表值 esc 后进模板）；未命中=诚实省略。"""
        assert "paramRoleKey(c, k)" in _GALLERY, "参数行未消费 paramRoleKey"
        assert "gallery.sem_missing" in _GALLERY  # 含义列兜底仍在位（未动）
        m = re.search(r"const roleKey = paramRoleKey\(c, k\);[\s\S]*?\"", _GALLERY)
        assert m, "角色行渲染块缺席"
        assert "\\u21b3" in _GALLERY, "↳ 箭头走 \\u 转义形态（Han 棘轮基线=0 纪律）"


# ────────────── 2. tune 结果卡「结果怎么读」折叠区 ──────────────

class TestTuneHowtoSection:
    def test_howto_refs_wired(self):
        for k in _HOWTO_KEYS:
            assert f't("{k}")' in _TUNE, f"view_tune 未引用 {k}"
            assert f'"{k}":' in _I18N, f"i18n 缺 {k}"

    def test_howto_in_result_card_before_raw_json(self):
        """折叠区挂在结果卡尾部、原始 JSON 折叠之前（怎么读→原文顺序）。"""
        m = re.search(
            r't\("tune\.res_howto_label"\)[\s\S]*?t\("tune\.res_details_label"\)', _TUNE)
        assert m, "howto 折叠区未挂在原始 JSON 折叠之前"

    def test_howto_values_plain_text_bilingual(self):
        for k in _HOWTO_KEYS:
            m = re.search(r'"' + re.escape(k) + r'":\s*\{\s*zh: "((?:[^"\\]|\\.)*)"\s*,\s*en: "((?:[^"\\]|\\.)*)"', _I18N)
            assert m, f"{k} 词表值缺席或缺半边"
            for side, val in (("zh", m.group(1)), ("en", m.group(2))):
                assert val.strip(), f"{k} {side} 空值"
                assert not re.search(r"</?[a-zA-Z]", val), f"{k} {side} 值含 HTML"


# ────────────── 3. 校准页 verdict/ρ 白话 ──────────────

class TestCalibrationVerdictNotes:
    def test_notes_wired_list_and_detail(self):
        """清单表脚注与详情面板两处都引用（判定旁白话=两处判定呈现点）。"""
        for k in _CALIB_KEYS:
            assert f't("{k}")' in _CALIB, f"view_calibration 未引用 {k}"
            assert f'"{k}":' in _I18N, f"i18n 缺 {k}"
        # 详情面板（loadCalibration）内也有一份（badge 旁）
        detail = re.search(r"async function loadCalibration\([\s\S]*?\n\}", _CALIB)
        assert detail, "loadCalibration 缺席"
        for k in _CALIB_KEYS:
            assert f't("{k}")' in detail.group(0), f"详情面板未引用 {k}"

    def test_note_values_plain_text_bilingual(self):
        for k in _CALIB_KEYS:
            m = re.search(r'"' + re.escape(k) + r'":\s*\{\s*zh: "((?:[^"\\]|\\.)*)"\s*,\s*en: "((?:[^"\\]|\\.)*)"', _I18N)
            assert m, f"{k} 词表值缺席或缺半边"
            for side, val in (("zh", m.group(1)), ("en", m.group(2))):
                assert val.strip(), f"{k} {side} 空值"
                assert not re.search(r"</?[a-zA-Z]", val), f"{k} {side} 值含 HTML"
