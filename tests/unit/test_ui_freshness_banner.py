"""aurora_l Wave-C C2：UI freshness 红条接线测试（R1 #14/15）。

K4 落的 ``runs_verify_service.verify_run`` 此前无 run 详情/双 run 对比
消费口（全 ui/ 唯一 stale=标定锚页）。本批接两处 UI 消费面并钉语义：

1. ``ui_service.run_detail``：响应增 ``freshness`` 观测块（status=
   fresh/stale/legacy/error 透传 + issues_n/stale_kinds 摘要；verify 面
   故障 → status="unknown" 不阻塞详情主路径 #105）。**不进
   _RUN_SCAN_CACHE**——签名面盖不住 manifest 顶替/损坏（缓存期内错配
   会出假 fresh），逐请求现算（manifest 损坏钉证：缓存命中面 files 不
   变、freshness 即时翻红）。
2. ``runs_diff``（service 单源 → ui/runs_diff.py re-export）：响应增
   ``freshness={a,b}`` 两侧状态行（stale 标红不硬拒——对比结论可读出
   "哪边是脏数据"）。
3. 前端源码钉：view_detail.js 条件渲染（stale 红 role="alert"/legacy
   灰/fresh 不出条 + API 数据 esc）、指标区顶部拼接序；i18n.js zh/en
   双语键（node 行为钉 + 正则钉）；view_reports.js 对照行；键域归属
   自证（detail.*/reports.* 键在归属页引用——test_ui_i18n 死键门同款
   口径的本批增量，防跨页借用回潮）。

合成 run 手法照 test_runs_verify_service.py / test_freshness_gates.py
（sidecar+manifest stamp）；全离线零网络（#139）、chdir 隔离零 runs/ 湖
写入（#144）。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.service.envelope import error_envelope
from rfauto.service.runs_verify_service import (
    write_manifest,
    write_touchstone_sidecar,
)
from rfauto.service.ui_service import run_detail
from rfauto.ui.runs_diff import runs_diff

# 旧工程顶替内容（与 stamp 时的字节不同 → stale_replaced）
_S1P = "# Hz S RI R 50\n1.0e9 0.1 0.0\n"
_REPLACED_S1P = "# Hz S RI R 50\n1.0e9 0.9 0.0\n"

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_DETAIL = (_STATIC / "pages" / "view_detail.js").read_text(encoding="utf-8")
_REPORTS = (_STATIC / "pages" / "view_reports.js").read_text(encoding="utf-8")
_I18N = (_STATIC / "pages" / "i18n.js").read_text(encoding="utf-8")
_NODE = shutil.which("node")

_FRESHNESS_I18N_KEYS = (
    "detail.freshness_stale_banner",
    "detail.freshness_issues_lead",
    "detail.freshness_legacy_banner",
    "reports.freshness_row_label",
    "reports.freshness_fresh_badge",
    "reports.freshness_stale_badge",
    "reports.freshness_legacy_badge",
    "reports.freshness_unknown_badge",
)


@pytest.fixture(autouse=True)
def _isolated(isolated):
    yield


def _make_run(runs: Path, name: str, *, stamp: bool = False) -> Path:
    """合成 run（HFSS 形态；stamp=收官指纹 sidecar+manifest，run_once 同序）。"""
    run = runs / name
    (run / "results").mkdir(parents=True)
    (run / "meta.json").write_text(json.dumps({
        "run_id": name, "adapter": "hfss", "model": "patch_antenna",
        "status": "done",
    }), encoding="utf-8")
    (run / "results" / "params.s1p").write_text(_S1P, encoding="utf-8")
    if stamp:
        write_touchstone_sidecar(run / "results" / "params.s1p", run_id=name)
        write_manifest(run)
    return run


def _boom_verify(monkeypatch) -> None:
    """verify 面故障注入（#105 钉：观测面故障不阻塞消费主路径）。"""

    def _boom(run_dir):
        raise RuntimeError("verify 通道故障")

    monkeypatch.setattr(
        "rfauto.service.runs_verify_service.verify_run", _boom)


# ─────────────────── 1. run_detail freshness 块（四态） ───────────────────


class TestRunDetailFreshnessBlock:
    RID = "20261023_000001_aaaa"

    def _runs(self, isolated: Path) -> Path:
        runs = isolated / "runs"
        runs.mkdir(exist_ok=True)
        return runs

    def test_fresh_status(self, isolated):
        _make_run(self._runs(isolated), self.RID, stamp=True)
        d = run_detail(self.RID)
        assert d["ok"]
        fr = d["freshness"]
        assert fr["status"] == "fresh"
        assert fr["ok"] is True
        assert fr["stale_kinds"] == "" and fr["issues_n"] == 0
        assert fr["run_id"] == self.RID

    def test_stale_status_with_kinds_summary(self, isolated):
        runs = self._runs(isolated)
        _make_run(runs, self.RID, stamp=True)
        (runs / self.RID / "results" / "params.s1p").write_text(
            _REPLACED_S1P, encoding="utf-8")  # 旧工程顶替（用户病灶原样）
        fr = run_detail(self.RID)["freshness"]
        assert fr["status"] == "stale"
        assert fr["ok"] is False
        assert "stale_replaced" in fr["stale_kinds"]
        assert fr["issues_n"] >= 1
        assert "复核" in fr["note"]

    def test_legacy_status(self, isolated):
        _make_run(self._runs(isolated), self.RID, stamp=False)  # 老 run 无 manifest
        fr = run_detail(self.RID)["freshness"]
        assert fr["status"] == "legacy"
        assert fr["ok"] is True
        assert fr["stale_kinds"] == ""

    def test_error_status_passthrough_non_blocking(self, isolated, monkeypatch):
        """verify_run 回 error 信封（目录竞态形态）→ status="error" 透传，
        详情主路径不阻塞（#105），错误串透出到 note。"""
        _make_run(self._runs(isolated), self.RID, stamp=True)

        def _error(run_dir):
            return error_envelope(
                ["run 目录不存在（模拟竞态）"], run_id=self.RID,
                status="error", issues=[])

        monkeypatch.setattr(
            "rfauto.service.runs_verify_service.verify_run", _error)
        d = run_detail(self.RID)
        assert d["ok"]  # 详情主路径不受观测面影响
        fr = d["freshness"]
        assert fr["status"] == "error"
        assert fr["ok"] is False
        assert "模拟竞态" in fr["note"]

    def test_verify_face_failure_unknown(self, isolated, monkeypatch):
        """verify 面异常 → status="unknown" 不阻塞详情（#105）。"""
        _make_run(self._runs(isolated), self.RID, stamp=True)
        _boom_verify(monkeypatch)
        d = run_detail(self.RID)
        assert d["ok"]
        fr = d["freshness"]
        assert fr["status"] == "unknown"
        assert fr["ok"] is None
        assert "不可用" in fr["note"]

    def test_freshness_not_cached_manifest_corrupt_flips_red(self, isolated):
        """freshness 不进 _RUN_SCAN_CACHE：manifest 被顶替为损坏内容（不在
        签名面内 → files 缓存命中不变）而 freshness 即时翻红
        （manifest_corrupt）。若误进缓存，此钉即红。"""
        runs = self._runs(isolated)
        _make_run(runs, self.RID, stamp=True)
        d1 = run_detail(self.RID)
        assert d1["freshness"]["status"] == "fresh"
        (runs / self.RID / "manifest.json").write_text(
            "{not json", encoding="utf-8")
        d2 = run_detail(self.RID)
        fr2 = d2["freshness"]
        assert fr2["status"] == "stale"
        assert "manifest_corrupt" in fr2["stale_kinds"]
        # 缓存命中面不变（签名不含 manifest.json）——翻红只来自逐请求现算
        assert [f["path"] for f in d2["files"]] == \
            [f["path"] for f in d1["files"]]

    def test_missing_run_error_envelope_has_no_freshness(self, isolated):
        """run 不存在错误路径形状不变（freshness 只在 ok 信封上）。"""
        d = run_detail("no_such_run")
        assert not d["ok"]
        assert "freshness" not in d


# ─────────────────── 2. runs_diff freshness 对照节 ───────────────────


class TestRunsDiffFreshnessSection:
    A, B = "20261023_000001_aaaa", "20261023_000002_bbbb"

    def _runs(self, isolated: Path) -> Path:
        runs = isolated / "runs"
        runs.mkdir(exist_ok=True)
        return runs

    def test_fresh_vs_stale_sides_marked_not_rejected(self, isolated):
        runs = self._runs(isolated)
        _make_run(runs, self.A, stamp=True)
        _make_run(runs, self.B, stamp=True)
        (runs / self.B / "results" / "params.s1p").write_text(
            _REPLACED_S1P, encoding="utf-8")
        d = runs_diff(self.A, self.B)
        assert d["ok"]  # stale 标红不硬拒（对比结论可读出哪边是脏数据）
        fr = d["freshness"]
        assert fr["a"]["status"] == "fresh"
        assert fr["b"]["status"] == "stale"
        assert "stale_replaced" in fr["b"]["stale_kinds"]
        assert fr["a"]["run_id"] == self.A and fr["b"]["run_id"] == self.B

    def test_legacy_sides(self, isolated):
        runs = self._runs(isolated)
        _make_run(runs, self.A, stamp=False)
        _make_run(runs, self.B, stamp=False)
        fr = runs_diff(self.A, self.B)["freshness"]
        assert fr["a"]["status"] == "legacy"
        assert fr["b"]["status"] == "legacy"

    def test_verify_face_failure_unknown_non_blocking(self, isolated,
                                                      monkeypatch):
        _make_run(self._runs(isolated), self.A, stamp=True)
        _make_run(self._runs(isolated), self.B, stamp=True)
        _boom_verify(monkeypatch)
        d = runs_diff(self.A, self.B)
        assert d["ok"]  # diff 主路径不受观测面故障影响（#105）
        fr = d["freshness"]
        assert fr["a"]["status"] == "unknown"
        assert fr["b"]["status"] == "unknown"
        assert "不可用" not in fr["a"]["note"] or "verify_run 异常" in fr["a"]["note"]


# ─────────────────── 3. 前端源码钉 ───────────────────


class TestFreshnessFrontendSourcePins:
    def test_detail_banner_conditional_render(self):
        """红条/灰条条件渲染钉：stale 红条 role=alert + 摘要；legacy 灰条；
        fresh（与 unknown）无分支不出条。"""
        assert 'fr.status === "stale"' in _DETAIL
        assert 'fr.status === "legacy"' in _DETAIL
        assert _DETAIL.count('fr.status ===') == 2, \
            "fresh/unknown 不得出条（只许 stale/legacy 两分支）"
        assert 'role="alert"' in _DETAIL
        assert 't("detail.freshness_stale_banner")' in _DETAIL
        assert 't("detail.freshness_legacy_banner")' in _DETAIL
        assert 't("detail.freshness_issues_lead")' in _DETAIL

    def test_detail_banner_data_escaped(self):
        """XSS 纪律：issue 摘要是 API 数据（issues_n/stale_kinds）必须 esc。"""
        assert "esc(fr.issues_n)" in _DETAIL
        assert "esc(fr.stale_kinds)" in _DETAIL

    def test_detail_banner_at_top_of_metrics_area(self):
        """指标区顶部：frBanner 拼在指标徽章前。"""
        anchor = _DETAIL.index('T.$("detail-head").innerHTML = frBanner +')
        badges = _DETAIL.index("metricBadgeHtml(k, v2, glossary[k], loc)")
        assert anchor < badges

    def test_reports_diff_freshness_row(self):
        """双 run 对比页 freshness 对照行：A/B 各自状态 + kinds esc。"""
        assert "d.freshness?.a?.status" in _REPORTS
        assert "d.freshness?.b?.status" in _REPORTS
        assert 't("reports.freshness_row_label")' in _REPORTS
        assert 't("reports.freshness_stale_badge")' in _REPORTS
        assert "esc(side.stale_kinds)" in _REPORTS

    def test_i18n_keys_bilingual_and_html_free(self):
        """zh/en 同笔：8 键齐、双语齐、值零 HTML（test_ui_i18n 同口径增量）。"""
        html_re = re.compile(r"</?[a-zA-Z]")
        for key in _FRESHNESS_I18N_KEYS:
            m = re.search(rf'"{key}":\s*\{{([^}}]*)\}}', _I18N, re.S)
            assert m, f"词表缺键: {key}"
            block = m.group(1)
            assert re.search(r"\bzh:\s*[\"'`]", block), f"zh 缺: {key}"
            assert re.search(r"\ben:\s*[\"'`]", block), f"en 缺: {key}"
            assert not html_re.search(block), f"值含 HTML: {key}"

    def test_freshness_keys_owned_by_rendering_view(self):
        """键域归属自证：detail.*/reports.* freshness 键全部在渲染页引用
        （test_ui_i18n 死键门同款口径的本批增量——防跨页借用回潮）。"""
        keys = set(re.findall(
            r'"((?:detail|reports)\.freshness_[a-z_]+)":', _I18N))
        assert keys == set(_FRESHNESS_I18N_KEYS), "词表键集与钉面清单漂移"
        detail_refs = set(re.findall(
            r'\bt\("(detail\.freshness_[a-z_]+)"', _DETAIL))
        reports_refs = set(re.findall(
            r'\bt\("(reports\.freshness_[a-z_]+)"', _REPORTS))
        assert keys == detail_refs | reports_refs, (
            f"死键/悬空: 词表-引用差={sorted(keys - (detail_refs | reports_refs))} "
            f"引用-词表差={sorted((detail_refs | reports_refs) - keys)}")

    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_node_check_edited_views(self):
        """三份前端改动文件语法门（node --check；与 test_ui_i18n 同款）。"""
        for rel in ("pages/view_detail.js", "pages/view_reports.js",
                    "pages/i18n.js"):
            r = subprocess.run(
                [_NODE, "--check", str(_STATIC / rel)],
                capture_output=True, text=True, timeout=60)
            assert r.returncode == 0, f"node --check {rel}:\n{r.stderr[-2000:]}"

    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_i18n_keys_node_behavior(self):
        """node 真执行词表：8 键在场且 zh/en 非空（行为钉，非正则）。"""
        keys = json.dumps(list(_FRESHNESS_I18N_KEYS))
        js = (
            "const m = await import('./pages/i18n.js');\n"
            f"const keys = {keys};\n"
            "const errs = [];\n"
            "for (const k of keys) {\n"
            "  const e = m.LOCALES[k];\n"
            "  if (!e) errs.push('missing: ' + k);\n"
            "  else if (typeof e.zh !== 'string' || !e.zh) errs.push('zh 缺: ' + k);\n"
            "  else if (typeof e.en !== 'string' || !e.en) errs.push('en 缺: ' + k);\n"
            "}\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:freshness:' + keys.length);\n")
        r = subprocess.run(
            [_NODE, "--input-type=module", "-e", js],
            capture_output=True, text=True, timeout=60, cwd=str(_STATIC))
        assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2000:]}"
        assert "ok:freshness:8" in r.stdout
