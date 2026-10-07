"""QW 快赢批定向测试（2026-09-26）：QW-1 混合模 / QW-2 知识检索 / QW-3 锚新鲜度。

QW-1：si_channel_service.mixed_mode_metrics（skrf se2gmm 薄封装）+ ``si mixed``
CLI——skrf 口径（官方 docstring 4-port 图实测钉死）：相邻单端口成对
(0,1)/(2,3)（0 起），变换后输出端口序 [d0, d1, c0, c1]；本测试用独立重述
的矩阵下标表与 skrf 直调对拍，防接口漂移。
QW-2：knowledge_service.search_knowledge + MCP ``search_knowledge``——
tmp 构造四类数据面正/负例 + 真仓 knowledge/ 只读冒烟。
QW-3：anchors_service.anchors_stale_report + ``anchors stale`` CLI——
阈值边界（29/30/31 天，严格大于）+ no_date 如实标注 + 真注册表冒烟。
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import numpy as np
import pytest
import yaml
from typer.testing import CliRunner

from rfauto.cli.main import app
from rfauto.service.anchors_service import anchors_stale_report
from rfauto.service.knowledge_service import search_knowledge
from rfauto.service.si_channel_service import mixed_mode_metrics

runner = CliRunner()

_REPO_ROOT = Path(__file__).resolve().parents[2]

_FREQ_HZ = np.linspace(1.0e9, 2.0e9, 5)


def _through_s() -> np.ndarray:
    """理想 4 端口直通：+线 1↔3、−线 2↔4（1 起），全带 |S|=1。"""
    s = np.zeros((5, 4, 4), dtype=complex)
    s[:, 2, 0] = 1
    s[:, 0, 2] = 1
    s[:, 3, 1] = 1
    s[:, 1, 3] = 1
    return s


def _swap_s() -> np.ndarray:
    """交叉 4 端口：+线 1↔4、−线 2↔3（1 起）——差模/共模全通、零模式转换。"""
    s = np.zeros((5, 4, 4), dtype=complex)
    s[:, 3, 0] = 1
    s[:, 0, 3] = 1
    s[:, 2, 1] = 1
    s[:, 1, 2] = 1
    return s


def _asymmetric_s() -> np.ndarray:
    """非对称失配 4 端口（确定性强弱元混合）——对拍用，暴露端口序错误。"""
    rng = np.random.default_rng(20260926)
    base = rng.uniform(0.05, 0.5, size=(5, 4, 4)) + 1j * rng.uniform(
        -0.5, 0.5, size=(5, 4, 4))
    # 压幅保被动（σmax < 1），仅作对拍载荷不做物理断言
    u, _, vh = np.linalg.svd(base)
    sigma = np.array([0.9, 0.5, 0.3, 0.1])
    return u * sigma[np.newaxis, :, np.newaxis] @ vh


# 与 service._MIXED_MODE_MATRIX_INDEX 独立重述（防接口漂移的对拍锚）：
# skrf se2gmm(p=2) 输出序 [d0, d1, c0, c1]；S_行,列 = 列口激励、行口响应。
_QW1_INDEX = {
    "sdd21": (1, 0), "sdd11": (0, 0), "sdd12": (0, 1),
    "scc21": (3, 2), "scc11": (2, 2),
    "scd21": (1, 2), "sdc21": (3, 0),
    "scd12": (0, 3), "sdc12": (2, 1),
}


def _direct_skrf_gmm_db(s: np.ndarray, pair1: tuple[int, int],
                        pair2: tuple[int, int]) -> dict[str, list[float]]:
    """独立直调 skrf se2gmm 复算九指标（对拍锚，不 import service 实现）。"""
    import skrf

    net = skrf.Network(
        frequency=skrf.Frequency.from_f(_FREQ_HZ, unit="hz"),
        s=np.asarray(s, dtype=complex), z0=50.0)
    g = net.copy()
    g.renumber([pair1[0] - 1, pair1[1] - 1, pair2[0] - 1, pair2[1] - 1],
               [0, 1, 2, 3])
    g.se2gmm(p=2)
    out: dict[str, list[float]] = {}
    for key, (row, col) in _QW1_INDEX.items():
        db = 20.0 * np.log10(
            np.maximum(np.abs(g.s[:, row, col]), 1e-15))
        out[f"{key}_db"] = [float(v) for v in db]
    return out


class TestMixedModeMetrics:
    """QW-1：混合模指标（skrf se2gmm 薄封装）。"""

    def test_ideal_through_sdd_scc(self):
        r = mixed_mode_metrics(freq_hz=_FREQ_HZ, s=_through_s())
        assert r["ok"] is True
        assert r["pairs"] == {"diff_port_1": [1, 2], "diff_port_2": [3, 4]}
        m = r["metrics"]
        # 逐位：理想直通 Sdd21 = 0 dB
        assert all(abs(v - 0.0) < 1e-12 for v in m["sdd21_db"])
        # 回损/共模/模式转换全为地板（|S|=0 → −300 dB 地板）
        for key in ("sdd11_db", "scc11_db", "scd21_db", "sdc21_db",
                    "scd12_db", "sdc12_db"):
            assert all(v <= -40.0 for v in m[key]), key

    def test_swap_zero_mode_conversion(self):
        r = mixed_mode_metrics(freq_hz=_FREQ_HZ, s=_swap_s())
        assert r["ok"] is True
        m = r["metrics"]
        assert all(abs(v - 0.0) < 1e-12 for v in m["sdd21_db"])
        assert all(abs(v - 0.0) < 1e-12 for v in m["scc21_db"])
        for key in ("sdd11_db", "scd21_db", "sdc21_db", "scd12_db",
                    "sdc12_db"):
            assert all(v <= -40.0 for v in m[key]), key

    @pytest.mark.parametrize("s_mat,pair1,pair2", [
        (_through_s(), (1, 2), (3, 4)),
        (_swap_s(), (1, 2), (3, 4)),
        (_asymmetric_s(), (1, 2), (3, 4)),
        (_asymmetric_s(), (1, 3), (2, 4)),
    ])
    def test_matches_direct_skrf_call(self, s_mat, pair1, pair2):
        """与 skrf 直调逐位对拍（同端口对、同下标表）——防接口漂移。"""
        r = mixed_mode_metrics(freq_hz=_FREQ_HZ, s=s_mat,
                               ports_pair=pair1)
        assert r["ok"] is True
        assert r["pairs"] == {"diff_port_1": list(pair1),
                              "diff_port_2": list(pair2)}
        expect = _direct_skrf_gmm_db(s_mat, pair1, pair2)
        for key, values in expect.items():
            np.testing.assert_allclose(np.asarray(r["metrics"][key]),
                                       np.asarray(values),
                                       rtol=0, atol=1e-12, err_msg=key)

    def test_touchstone_source_path(self, tmp_path):
        import skrf

        net = skrf.Network(
            frequency=skrf.Frequency.from_f(_FREQ_HZ, unit="hz"),
            s=_through_s(), z0=50.0)
        p = tmp_path / "link.s4p"
        net.write_touchstone(str(p))
        r = mixed_mode_metrics(str(p))
        assert r["ok"] is True
        assert r["source"]["kind"] == "touchstone"
        assert all(abs(v - 0.0) < 1e-9 for v in r["metrics"]["sdd21_db"])

    def test_non4port_rejected(self):
        s2 = np.zeros((5, 2, 2), dtype=complex)
        s2[:, 1, 0] = 1
        s2[:, 0, 1] = 1
        r = mixed_mode_metrics(freq_hz=_FREQ_HZ, s=s2)
        assert r["ok"] is False
        assert any("shape" in e or "4 端口" in e for e in r["errors"])

    @pytest.mark.parametrize("pair", [(2, 2), (0, 2), (1, 5), (1,), (1, 2, 3)])
    def test_ports_pair_validation(self, pair):
        r = mixed_mode_metrics(freq_hz=_FREQ_HZ, s=_through_s(),
                               ports_pair=pair)
        assert r["ok"] is False
        assert r["errors"]

    def test_no_input_rejected(self):
        r = mixed_mode_metrics()
        assert r["ok"] is False
        assert r["errors"]

    def test_s_without_freq_rejected(self):
        r = mixed_mode_metrics(s=_through_s())
        assert r["ok"] is False
        assert r["errors"]

    def test_summary_block_present(self):
        r = mixed_mode_metrics(freq_hz=_FREQ_HZ, s=_through_s())
        assert r["summary"]["sdd21_db"]["mean"] == pytest.approx(0.0,
                                                                 abs=1e-12)
        assert r["n_freqs"] == 5
        assert len(r["freq_hz"]) == 5


class TestSearchKnowledge:
    """QW-2：知识库统一检索（tmp 构造正/负例 + 真仓只读冒烟）。"""

    @pytest.fixture()
    def kb(self, tmp_path):
        rules = tmp_path / "rules.yaml"
        rules.write_text(yaml.dump({
            "rules": [
                {"id": "TQW1", "category": "diagnosis",
                 "description": "qw2 needle alpha 症状",
                 "applicable_models": ["all"]},
                {"id": "TQW2", "category": "diagnosis",
                 "description": "完全无关的条目",
                 "applicable_models": ["all"]},
                {"id": "TQW3", "category": "initial_value",
                 "description": "长文本截断钉：" + "填充" * 100 + " needle 尾",
                 "applicable_models": ["all"]},
            ]}, allow_unicode=True), encoding="utf-8")
        anchors = tmp_path / "anchors.yaml"
        anchors.write_text(yaml.dump({
            "schema": "anchors/v1",
            "anchors": [
                {"anchor_id": "qw.t_needle.openems-hfss-v1",
                 "kind": "constant", "status": "active", "value": 0.1e-9,
                 "quantity": {"name": "needle_qty", "unit": "H",
                              "semantics": "qw2 needle 语义"},
                 "template_family": ["tmpl_a"]},
            ]}, allow_unicode=True), encoding="utf-8")
        diag = tmp_path / "diagnostics"
        diag.mkdir()
        playbook = diag / "playbook.yaml"
        playbook.write_text(yaml.dump({
            "rules": [
                {"id": "qw_needle_fp", "root_cause_family": "needle_family",
                 "symptom_fingerprints": ["fp_a"]},
            ]}, allow_unicode=True), encoding="utf-8")
        fab = tmp_path / "fab_profiles"
        fab.mkdir()
        (fab / "qwfab.yaml").write_text(yaml.dump({
            "profile": {"name": "qw_fab",
                        "verification": "needle fab 核验文本",
                        "source_url": "https://example.com/qw"}}),
            encoding="utf-8", )
        return {"rules": rules, "anchors": anchors, "playbook": playbook,
                "fab": fab}

    def test_hits_all_scopes(self, kb):
        r = search_knowledge("needle", rules_path=kb["rules"],
                             anchors_path=kb["anchors"],
                             playbook_path=kb["playbook"],
                             fab_dir=kb["fab"])
        assert r["ok"] is True
        assert r["counts"]["total"] == 5  # rules 2 + anchors/playbook/fab 各 1
        assert r["counts"]["rules"] == 2
        assert {h["source"] for h in r["hits"]} == {
            "rules", "anchors", "playbook", "fab"}
        for h in r["hits"]:
            assert set(h) == {"source", "name", "snippet", "path"}

    def test_scope_filter(self, kb):
        r = search_knowledge("needle", scope="rules", rules_path=kb["rules"],
                             anchors_path=kb["anchors"],
                             playbook_path=kb["playbook"],
                             fab_dir=kb["fab"])
        assert r["ok"] is True
        assert {h["source"] for h in r["hits"]} == {"rules"}
        assert r["counts"]["total"] == r["counts"]["rules"]
        assert "anchors" not in r["counts"]

    def test_negative_zero_hits_ok(self, kb):
        r = search_knowledge("absent_term_xyz", rules_path=kb["rules"],
                             anchors_path=kb["anchors"],
                             playbook_path=kb["playbook"],
                             fab_dir=kb["fab"])
        assert r["ok"] is True
        assert r["hits"] == []
        assert r["counts"]["total"] == 0

    def test_case_insensitive(self, kb):
        r = search_knowledge("NEEDLE", scope="rules", rules_path=kb["rules"],
                             anchors_path=kb["anchors"],
                             playbook_path=kb["playbook"],
                             fab_dir=kb["fab"])
        assert r["ok"] is True
        assert r["counts"]["rules"] >= 1

    def test_snippet_truncated(self, kb):
        r = search_knowledge("needle", scope="rules", rules_path=kb["rules"],
                             anchors_path=kb["anchors"],
                             playbook_path=kb["playbook"],
                             fab_dir=kb["fab"])
        assert r["ok"] is True
        assert all(len(h["snippet"]) <= 160 for h in r["hits"])

    def test_limit_caps_per_scope(self, kb):
        r = search_knowledge("needle", scope="rules", limit=1,
                             rules_path=kb["rules"],
                             anchors_path=kb["anchors"],
                             playbook_path=kb["playbook"],
                             fab_dir=kb["fab"])
        assert r["ok"] is True
        assert r["counts"]["rules"] == 2
        assert len(r["hits"]) == 1

    def test_empty_query_rejected(self, kb):
        r = search_knowledge("   ", rules_path=kb["rules"])
        assert r["ok"] is False
        assert r["errors"]

    def test_invalid_scope_rejected(self, kb):
        r = search_knowledge("needle", scope="bogus", rules_path=kb["rules"])
        assert r["ok"] is False
        assert "scope" in r["errors"][0]

    def test_real_knowledge_smoke(self):
        """真仓 knowledge/ 只读冒烟（缺文件如实 skip，不造数据）。"""
        if not (_REPO_ROOT / "knowledge" / "rules.yaml").is_file():
            pytest.skip("仓内 knowledge/rules.yaml 不存在")
        r = search_knowledge("Wilkinson")
        assert r["ok"] is True
        assert r["counts"]["rules"] >= 1
        r2 = search_knowledge("rogers")
        assert r2["ok"] is True
        # 同词跨 scope 命中（rules+fab），scope 过滤后只剩单域
        assert r2["counts"]["total"] >= 1
        r3 = search_knowledge("rogers", scope="anchors")
        # scope 过滤语义：scope="anchors" 下 rules/fab/playbook 三域必须
        # 零命中（排除性）。anchors 域本身自 W4 FA3 锚起 domain_note 含
        # RO4350B/RO3003（合法命中），不再钉全零。
        assert r3["counts"]["total"] == r3["counts"].get("anchors", 0)
        assert r3["counts"].get("rules", 0) == 0
        assert r3["counts"].get("fab", 0) == 0

    def test_mcp_tool_delegates(self, monkeypatch):
        from rfauto import mcp_server

        sentinel = {"ok": True, "hits": [], "counts": {"total": 0}}
        seen: dict[str, object] = {}

        def fake_search(query, scope="all", **kwargs):
            seen["query"] = query
            seen["scope"] = scope
            return sentinel

        monkeypatch.setattr("rfauto.service.knowledge_service.search_knowledge",
                            fake_search)
        out = mcp_server.search_knowledge("wilkinson", "rules")
        assert out is sentinel
        assert seen == {"query": "wilkinson", "scope": "rules"}

    def test_mcp_tool_real_call(self):
        from rfauto import mcp_server

        if not (_REPO_ROOT / "knowledge" / "rules.yaml").is_file():
            pytest.skip("仓内 knowledge/rules.yaml 不存在")
        out = mcp_server.search_knowledge("Wilkinson")
        assert out["ok"] is True
        assert out["counts"]["total"] >= 1


def _write_stale_registry(path: Path, now: datetime.datetime) -> None:
    """阈值边界注册表：29/30/31 天 + last_verified:null + 缺字段共 5 锚。"""

    def iso(days: float) -> str:
        return (now - datetime.timedelta(days=days)).isoformat()

    rows = [
        {"anchor_id": "qw.a29.openems-hfss-v1", "kind": "constant",
         "status": "active", "value": 1.0,
         "quantity": {"name": "x", "unit": "H"},
         "last_verified": {"at": iso(29.0), "residual": 0.01}},
        {"anchor_id": "qw.b30.openems-hfss-v1", "kind": "constant",
         "status": "active", "value": 2.0,
         "quantity": {"name": "x", "unit": "H"},
         "last_verified": {"at": iso(30.0), "residual": 0.02}},
        {"anchor_id": "qw.c31.openems-hfss-v1", "kind": "constant",
         "status": "active", "value": 3.0,
         "quantity": {"name": "x", "unit": "H"},
         "last_verified": {"at": iso(31.0), "residual": 0.03}},
        {"anchor_id": "qw.d_null.openems-hfss-v1", "kind": "constant",
         "status": "experimental", "value": 4.0,
         "quantity": {"name": "x", "unit": "H"},
         "last_verified": None},
        {"anchor_id": "qw.e_missing.openems-hfss-v1", "kind": "constant",
         "status": "awaiting_data", "value": 5.0,
         "quantity": {"name": "x", "unit": "H"}},
    ]
    path.write_text(yaml.dump({"schema": "anchors/v1", "anchors": rows},
                              allow_unicode=True), encoding="utf-8")


class TestAnchorsStaleReport:
    """QW-3：锚新鲜度报告（阈值边界 + no_date + 真注册表冒烟）。"""

    NOW = datetime.datetime(2026, 9, 26, 12, 0, 0,
                            tzinfo=datetime.timezone.utc)

    @pytest.fixture()
    def registry(self, tmp_path):
        p = tmp_path / "anchors.yaml"
        _write_stale_registry(p, self.NOW)
        return p

    def test_threshold_boundary(self, registry):
        r = anchors_stale_report(30.0, path=str(registry), now=self.NOW)
        assert r["ok"] is True
        rows = {a["anchor_id"]: a for a in r["anchors"]}
        # 严格大于：29/30 天 fresh，31 天 stale
        assert rows["qw.a29.openems-hfss-v1"]["stale"] is False
        assert rows["qw.b30.openems-hfss-v1"]["stale"] is False
        assert rows["qw.c31.openems-hfss-v1"]["stale"] is True
        assert rows["qw.c31.openems-hfss-v1"]["age_days"] == 31.0
        assert r["stale_count"] == 1
        # 无日期如实标注，不虚构日期、不算 stale
        for key in ("qw.d_null.openems-hfss-v1", "qw.e_missing.openems-hfss-v1"):
            row = rows[key]
            assert row["stale"] is None
            assert row["age_days"] is None
            assert row["last_verified_at"] is None
            assert row["date_kind"] == "no_date"
        assert r["no_date_count"] == 2
        assert r["count"] == 5

    def test_threshold_move_changes_verdict(self, registry):
        r = anchors_stale_report(31.0, path=str(registry), now=self.NOW)
        assert r["stale_count"] == 0
        r2 = anchors_stale_report(28.0, path=str(registry), now=self.NOW)
        assert r2["stale_count"] == 3  # 29/30/31 天全部 > 28

    def test_negative_threshold_rejected(self, registry):
        r = anchors_stale_report(-1.0, path=str(registry))
        assert r["ok"] is False
        assert r["error"]

    def test_status_field_carried(self, registry):
        r = anchors_stale_report(30.0, path=str(registry), now=self.NOW)
        rows = {a["anchor_id"]: a for a in r["anchors"]}
        assert rows["qw.d_null.openems-hfss-v1"]["status"] == "experimental"
        assert rows["qw.e_missing.openems-hfss-v1"]["status"] == "awaiting_data"

    def test_real_registry_smoke(self):
        """真注册表只读冒烟（与 core 单源计数核对；缺文件 skip）。"""
        if not (_REPO_ROOT / "knowledge" / "anchors.yaml").is_file():
            pytest.skip("仓内 knowledge/anchors.yaml 不存在")
        from rfauto.core.anchors import EXPECTED_ANCHORS

        r = anchors_stale_report(30.0)
        assert r["ok"] is True
        assert r["count"] == len(EXPECTED_ANCHORS)
        assert r["stale_count"] + r["no_date_count"] <= r["count"]
        for row in r["anchors"]:
            assert row["date_kind"] in ("dated", "no_date")
            if row["date_kind"] == "no_date":
                assert row["stale"] is None

    def test_cli_json_and_reject(self, registry):
        result = runner.invoke(app, ["anchors", "stale", "--json",
                                     "--threshold", "30"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["ok"] is True

        result2 = runner.invoke(app, ["anchors", "stale", "--json",
                                      "--threshold", "-1"])
        assert result2.exit_code == 1
        assert "threshold" in result2.output or "error" in result2.output


class TestSiMixedCli:
    """QW-1 CLI：``si mixed`` 薄壳（真实 s4p 走通 + 非法 --ports 拒绝）。"""

    def test_si_mixed_end_to_end(self, tmp_path):
        import skrf

        net = skrf.Network(
            frequency=skrf.Frequency.from_f(_FREQ_HZ, unit="hz"),
            s=_through_s(), z0=50.0)
        p = tmp_path / "link.s4p"
        net.write_touchstone(str(p))
        result = runner.invoke(app, ["si", "mixed", str(p), "--ports", "1,2"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["ok"] is True
        assert data["pairs"] == {"diff_port_1": [1, 2], "diff_port_2": [3, 4]}
        assert all(abs(v) < 1e-9 for v in data["metrics"]["sdd21_db"])

    def test_si_mixed_bad_ports_exit_2(self, tmp_path):
        import skrf

        net = skrf.Network(
            frequency=skrf.Frequency.from_f(_FREQ_HZ, unit="hz"),
            s=_through_s(), z0=50.0)
        p = tmp_path / "link.s4p"
        net.write_touchstone(str(p))
        result = runner.invoke(app, ["si", "mixed", str(p),
                                     "--ports", "a,b"])
        assert result.exit_code == 2

    def test_si_mixed_non4p_exit_1(self, tmp_path):
        import skrf

        net2 = skrf.Network(
            frequency=skrf.Frequency.from_f(_FREQ_HZ, unit="hz"),
            s=np.zeros((5, 2, 2), dtype=complex), z0=50.0)
        p2 = tmp_path / "line.s2p"
        net2.write_touchstone(str(p2))
        result = runner.invoke(app, ["si", "mixed", str(p2)])
        assert result.exit_code == 1
