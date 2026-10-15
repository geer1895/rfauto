"""报告垂直域摘要节（aging/PI/OTA/EMC/EDB）测试——B3 批 U1 链挂接。

判据（月计划 G 流"报告增强：aging/PI/OTA/EMC 四新节进 U1 报告链"）：
- 节构建器=既有确定性内核输出的摘要渲染（铁律 7：零计算零换算，
  值逐键透传+来源标注；缺键如实 None/empty，不冒充判读 #122）；
- build_report_model(domain_results=...) 挂 domains 节后 typ/HTML 双渲染
  同源可见；缺省（None）时模型无 domains 键、HTML 与既有逐字节一致；
- U1 规则 2：报告模型全域 bare_number_fields==0（domains 节不破例）；
- OTA/EMC 用真实内核出数（确定性离线）；aging/PI 用罐头输出（形状
  与 service 契约一致）。
- ``edb`` 节（EDB 道与报表联动最小件）：edb_status+list_datasets
  （edb_lane_*）+健康门统计三面摘要；缺面如实留空/零行降级"无数据"
  不炸；数字全部为确定性计数（清点面，非物理量）。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from rfauto.service.report_domains import (
    DOMAIN_ORDER,
    EDB_LANE_DATASET_PREFIX,
    aging_section,
    assemble_domain_sections,
    edb_section,
    emc_section,
    ota_section,
    pi_section,
    render_domains_html,
)
from rfauto.service.report_render import (
    bare_number_fields,
    build_report_model,
    external_resource_refs,
    render_html,
    render_typ,
)

# ── 罐头输出（形状=service 契约；数字为测试固定值非物理声明） ────────────────

def _aging_ok() -> dict:
    return {
        "ok": True,
        "template": "interdigital",
        "disclaimer": "fake 通道演示口径（非物理基准）",
        "sections": {
            "mission_profile": {"columns": ["seg", "t_s"],
                                "rows": [], "t_total_s": 8.76e5,
                                "t_equivalent_s": 4.38e5},
            "drift_trajectory": {"t_s": [0.0, 1.0], "er": [3.66, 3.60],
                                 "drift_frac": [0.0, 0.0164],
                                 "er0": 3.66, "er_eol": 3.60,
                                 "detune_pct": 0.8,
                                 "detune_pct_predicted": 0.79},
            "eol_verdict": {"ok": True, "verdict": "PASS",
                            "reason": "detune 0.8% ≤ spec 2%"},
            "provenance": {"source": "test-fixture"},
        },
    }


def _pi_gate_ok() -> dict:
    return {
        "ok": True, "gate": "pdn_ac_pi",
        "verdict": "UNKNOWN",
        "violations": [],
        "modes_in_band": [{"m": 1, "n": 0, "f_hz": 5.1e7}],
        "unknown_reason": "plane 未给——R1/R2 不判",
    }


def _edb_status_ok() -> dict:
    """edb_status 信封罐头（形状=service/edb_lane_service.edb_status 契约）。"""
    return {
        "ok": True, "root": "runs/edb_lane", "n_projects": 2,
        "items": [
            {"stem": "edb_branchline", "aedb": "a.aedb", "config_json": "c1",
             "solve_log": "l1", "extract_log": "e1", "touchstone": "t1.s4p",
             "spec_json": "s1", "solved": True},
            {"stem": "edb_ratrace", "aedb": None, "config_json": "c2",
             "solve_log": None, "extract_log": None, "touchstone": None,
             "spec_json": None, "solved": False},
        ],
        "templates": [
            {"template": "edb_branchline", "supported": True},
            {"template": "edb_coupled_line", "supported": True},
            {"template": "edb_power_divider", "supported": True},
            {"template": "edb_ratrace", "supported": True},
            {"template": "edb_lange", "supported": False, "reason": "…",
             "upgrade_doc": "docs/templates/edb_lange/meta.yaml"},
        ],
    }


def _list_datasets_envelope() -> dict:
    """list_datasets 信封罐头（形状=service/dataset_insights.list_datasets）。"""
    return {
        "ok": True, "out_dir": "datasets", "n_datasets": 3,
        "datasets": [
            {"name": "edb_lane_w1", "n_points": 5, "n_rows": 5, "n_dup": 0,
             "visibility": "private", "n_gt_rows": 5},
            {"name": "edb_lane_w2", "n_points": 3, "n_rows": 3, "n_dup": 0,
             "visibility": "private", "n_gt_rows": 3},
            {"name": "not_edb_lane", "n_points": 9, "n_rows": 9, "n_dup": 0,
             "visibility": "private", "n_gt_rows": 0},
        ],
    }


def _edb_input() -> dict:
    """edb 节输入罐头（三面全集；health 形状=collect 信封/manifest 键）。"""
    return {
        "edb_status": _edb_status_ok(),
        "datasets": _list_datasets_envelope(),
        "health": {"health_gate": True,
                   "health_verdicts": {"w1/pt1": "healthy",
                                       "w1/pt2": "unhealthy"},
                   "n_unhealthy_skipped": 1},
    }


# ── 四节构建器 ───────────────────────────────────────────────────────────────

class TestSectionBuilders:
    def test_aging_section_happy_path(self):
        sec = aging_section(_aging_ok())
        assert sec["status"] == "ok" and sec["verdict"] == "PASS"
        by_name = {m["metric"]: m for m in sec["metrics"]}
        assert by_name["t_equivalent_s"]["value"] == 4.38e5
        assert by_name["detune_pct"]["value"] == 0.8
        assert by_name["detune_pct"]["source"] == \
            "sections.drift_trajectory.detune_pct"
        # 铁律 7：值逐键透传不换算
        assert by_name["er_eol"]["value"] == 3.60

    def test_aging_section_not_ok_honest_empty(self):
        sec = aging_section({"ok": False, "errors": ["payload 缺键"]})
        assert sec["status"] == "empty" and sec["verdict"] is None
        assert sec["metrics"] == []
        joined = "\n".join(sec["notes"])
        assert "payload 缺键" in joined
        assert "如实留空" in joined

    def test_pi_section_gate_shape(self):
        sec = pi_section(_pi_gate_ok())
        assert sec["status"] == "ok" and sec["verdict"] == "UNKNOWN"
        by_name = {m["metric"]: m for m in sec["metrics"]}
        assert by_name["n_modes_in_band"]["value"] == 1
        assert by_name["n_violations"]["value"] == 0
        assert any("R1/R2 不判" in n for n in sec["notes"])

    def test_pi_section_analyze_shape_verdict_unknown(self):
        sec = pi_section({"ok": True, "margin_db": 6.0,
                          "worst_margin": 6.0})
        assert sec["verdict"] is None  # analyze 面无门 verdict——如实 UNKNOWN
        assert "analyze" in sec["kernel"]

    def test_pi_section_missing_margin_is_none(self):
        sec = pi_section({"ok": True, "gate": "pdn_ac_pi", "verdict": "PASS"})
        by_name = {m["metric"]: m for m in sec["metrics"]}
        assert by_name["margin_db"]["value"] is None

    def test_ota_section_from_real_kernel(self):
        th = np.linspace(0.0, 180.0, 19)
        ph = np.linspace(0.0, 360.0, 37)
        gain = np.broadcast_to(np.clip(10.0 * np.log10(np.maximum(
            np.sin(np.deg2rad(th[:, None])) ** 2, 1e-6)) + 30.0, -40.0, None),
            (th.size, ph.size))
        from rfauto.core.ota_metrics import ota_report_card

        sec = ota_section(ota_report_card(gain, th, ph))
        assert sec["status"] == "ok" and sec["verdict"] == "ok"
        names = {m["metric"] for m in sec["metrics"]}
        assert {"trp_dbm", "eirp_peak_dbm", "directivity_dbi",
                "beam_efficiency", "grid_coverage_fraction"} <= names
        # 值与内核一致（透传不换算）
        card = ota_report_card(gain, th, ph)
        by_name = {m["metric"]: m for m in sec["metrics"]}
        assert by_name["trp_dbm"]["value"] == card["trp"]["trp_dbm"]

    def test_emc_section_from_real_kernel(self):
        from rfauto.core.emc_radiated import (
            cispr32_classb_radiated_limits,
            radiated_margin,
        )

        f = np.linspace(3.0e7, 6.0e9, 40)
        e = np.full(f.size, 60.0)  # dBµV/m 高场强（限值 40/47）→ 必有违例
        sec = emc_section(radiated_margin(
            f, e, cispr32_classb_radiated_limits()))
        assert sec["status"] == "ok" and sec["verdict"] == "FAIL"
        by_name = {m["metric"]: m for m in sec["metrics"]}
        assert by_name["n_violations"]["value"] >= 1
        assert by_name["min_margin_db"]["value"] < 0

    def test_empty_input_honest(self):
        for builder in (aging_section, pi_section, ota_section, emc_section):
            sec = builder({})
            assert sec["status"] == "empty"
            assert "如实留空" in "".join(sec["notes"]) or \
                sec["metrics"] == [] or sec["verdict"] is None


# ── edb 节构建器（EDB 道与报表联动最小件） ───────────────────────────────────

class TestEdbSection:
    def test_happy_path_all_faces(self):
        sec = edb_section(_edb_input())
        assert sec["domain"] == "edb"
        assert sec["status"] == "ok"
        assert sec["verdict"] is None  # 清点摘要无判据门——不冒充判读
        by_name = {m["metric"]: m for m in sec["metrics"]}
        # 产物面（计数=确定性计数非物理量）
        assert by_name["n_projects"]["value"] == 2
        assert by_name["n_solved"]["value"] == 1
        assert by_name["n_touchstone"]["value"] == 1
        assert by_name["n_spec_json"]["value"] == 1
        assert by_name["n_config_json"]["value"] == 2
        assert by_name["n_projects"]["source"] == "edb_status.n_projects"
        assert by_name["n_solved"]["source"] == \
            "edb_status.items[*].solved（确定性计数）"
        # 五族清单（四支持+1 声明不支持）
        assert by_name["n_families_supported"]["value"] == 4
        joined = "\n".join(sec["notes"])
        assert "支持族：edb_branchline、edb_coupled_line、" \
               "edb_power_divider、edb_ratrace" in joined
        assert "不支持族：edb_lange" in joined
        assert "docs/templates/edb_lange/meta.yaml" in joined
        # 数据集面：非 edb_lane_* 前缀排除（9 行的 not_edb_lane 不计入）
        assert by_name["n_edb_lane_datasets"]["value"] == 2
        assert by_name["n_rows_total"]["value"] == 8
        assert "数据集 edb_lane_w1：5 行" in joined
        assert "数据集 edb_lane_w2：3 行" in joined
        # 健康门面
        assert by_name["health_gate"]["value"] is True
        assert by_name["n_health_checked"]["value"] == 2
        assert by_name["n_unhealthy"]["value"] == 1
        assert by_name["n_unhealthy_skipped"]["value"] == 1
        assert "unhealthy 点：w1/pt2" in joined
        # 每个指标都带非空 source（U1 规则 2 在节内先检）
        assert all(str(m["source"]).strip() for m in sec["metrics"])

    def test_missing_input_empty(self):
        sec = edb_section({})
        assert sec["status"] == "empty"
        assert sec["metrics"] == []
        assert "如实留空" in "\n".join(sec["notes"])
        sec_none = edb_section(None)  # type: ignore[arg-type]
        assert sec_none["status"] == "empty"

    def test_both_faces_missing_stays_empty(self):
        sec = edb_section({"edb_status": {"ok": False, "errors": ["炸了"]}})
        assert sec["status"] == "empty"
        joined = "\n".join(sec["notes"])
        assert "产物面如实留空" in joined
        assert "炸了" in joined  # 内核 errors 如实透传（aging 同口径）
        assert "数据集面如实留空" in joined

    def test_non_ok_status_with_datasets_degrades_partial_ok(self):
        # 产物面坏、数据集面在场 → 节 ok（在场面出数），坏面 notes 如实
        sec = edb_section({"edb_status": {"ok": False,
                                          "errors": ["产物根目录不可读: x"]},
                           "datasets": _list_datasets_envelope()})
        assert sec["status"] == "ok"
        by_name = {m["metric"]: m for m in sec["metrics"]}
        assert "n_projects" not in by_name
        assert by_name["n_rows_total"]["value"] == 8
        assert "产物根目录不可读: x" in "\n".join(sec["notes"])

    def test_datasets_zero_rows_degrades_no_data(self):
        # 数据集目录缺/零行 → "无数据"降级不炸（list_datasets 缺目录本就
        # ok 空表；本节再如实记零）
        sec = edb_section({"edb_status": _edb_status_ok(),
                           "datasets": {"ok": True, "out_dir": "d",
                                        "datasets": []}})
        assert sec["status"] == "ok"
        by_name = {m["metric"]: m for m in sec["metrics"]}
        assert by_name["n_edb_lane_datasets"]["value"] == 0
        assert by_name["n_rows_total"]["value"] == 0
        assert "如实无数据" in "\n".join(sec["notes"])

    def test_datasets_face_missing_honest(self):
        sec = edb_section({"edb_status": _edb_status_ok()})
        assert sec["status"] == "ok"
        by_name = {m["metric"]: m for m in sec["metrics"]}
        assert "n_rows_total" not in by_name
        assert "数据集面如实留空" in "\n".join(sec["notes"])

    def test_health_missing_honest(self):
        sec = edb_section({"edb_status": _edb_status_ok(),
                           "datasets": _list_datasets_envelope()})
        by_name = {m["metric"]: m for m in sec["metrics"]}
        for key in ("health_gate", "n_health_checked", "n_unhealthy",
                    "n_unhealthy_skipped"):
            assert key not in by_name
        assert "健康门统计如实留空" in "\n".join(sec["notes"])

    def test_health_partial_keys_only_present_rendered(self):
        sec = edb_section({"edb_status": _edb_status_ok(),
                           "datasets": _list_datasets_envelope(),
                           "health": {"health_gate": False}})
        by_name = {m["metric"]: m for m in sec["metrics"]}
        assert by_name["health_gate"]["value"] is False
        assert by_name["health_gate"]["source"] == "health.health_gate"
        assert "n_health_checked" not in by_name

    def test_health_only_face_not_silently_swallowed(self):
        """ge8e 审查席补：两面全缺而仅 health 在场 → 节保持 empty（契约），
        但必须落"health 在场未渲染"注记——此前 health 指标算完即弃且零
        注记=静默吞已透传输入（#122/#314 非静默吞同源）。"""
        sec = edb_section({"health": {"health_gate": True,
                                      "health_verdicts": {"w1/pt1": "healthy",
                                                          "w1/pt2": "unhealthy"}}})
        assert sec["status"] == "empty"  # 两面契约不翻
        assert sec["metrics"] == []  # 健康指标不冒充节出数
        joined = "\n".join(sec["notes"])
        assert "health 在场" in joined
        assert "两面全缺" in joined

    def test_malformed_n_rows_no_crash_and_noted(self):
        """ge8e 审查席补：n_rows 畸形行不炸（此前 int() 直抛 ValueError
        违"缺面如实留空不炸"模块纪律），未计入总数+如实留痕。"""
        env = _list_datasets_envelope()
        rows = list(env["datasets"])
        rows.append({"name": "edb_lane_bad", "n_rows": "not-a-number",
                     "visibility": "public"})
        sec = edb_section({"edb_status": _edb_status_ok(),
                           "datasets": {**env, "datasets": rows}})
        assert sec["status"] == "ok"  # 不炸，好行照常出数
        by_name = {m["metric"]: m for m in sec["metrics"]}
        assert by_name["n_rows_total"]["value"] == 8  # 畸形行未计入
        assert by_name["n_edb_lane_datasets"]["value"] == 3
        joined = "\n".join(sec["notes"])
        assert "edb_lane_bad" in joined
        assert "未计入" in joined

    def test_dataset_prefix_constant(self):
        assert EDB_LANE_DATASET_PREFIX == "edb_lane_"


# ── 组装与渲染 ───────────────────────────────────────────────────────────────

class TestAssembleAndRender:
    def test_assemble_full_set_ok(self):
        th = np.linspace(0.0, 180.0, 7)
        ph = np.linspace(0.0, 360.0, 13)
        from rfauto.core.ota_metrics import ota_report_card

        gain = np.broadcast_to(np.full((th.size, ph.size), 10.0),
                               (th.size, ph.size))
        asm = assemble_domain_sections({
            "aging": _aging_ok(), "pi": _pi_gate_ok(),
            "ota": ota_report_card(gain, th, ph),
            "emc": {"verdict": "PASS", "min_margin_db": 3.0,
                    "n_violations": 0},
            "edb": _edb_input(),
        })
        assert asm["ok"] is True
        assert [s["domain"] for s in asm["sections"]] == list(DOMAIN_ORDER)
        assert asm["n_missing"] == 0 and asm["unknown_keys"] == []

    def test_assemble_unknown_key_and_partial_honest(self):
        asm = assemble_domain_sections({"aging": _aging_ok(),
                                        "bogus": {"ok": True}})
        assert asm["ok"] is False  # 四域缺 → 不凑全
        assert asm["unknown_keys"] == ["bogus"]
        assert [s["domain"] for s in asm["sections"]] == ["aging"]
        assert asm["n_missing"] == 4

    def test_assemble_none_yields_no_sections(self):
        asm = assemble_domain_sections(None)
        assert asm["ok"] is False and asm["sections"] == []

    def test_render_html_escape(self):
        # 注入面走 aging 的 errors 通道（节构建的 notes 透传内核 errors）
        asm = assemble_domain_sections({
            "aging": {"ok": False,
                      "errors": ["<script>alert(1)</script>"]},
            "emc": {"verdict": "PASS", "min_margin_db": 1.0,
                    "n_violations": 0},
        })
        html = render_domains_html(asm)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
        assert 'class="judge-PASS"' in html

    def test_render_html_empty_returns_empty_string(self):
        assert render_domains_html({"sections": []}) == ""
        assert render_domains_html({}) == ""


# ── U1 链挂接（build_report_model + 双渲染） ────────────────────────────────

def _make_run(tmp_path: Path) -> Path:
    run = tmp_path / "run_domains"
    run.mkdir()
    (run / "meta.json").write_text(json.dumps({
        "template": "interdigital", "engine": "openems", "stage": "sample",
        "mesh_mm": 0.3, "n_ports": 2, "n_freq_points": 2,
        "freq_range_ghz": [2.0, 3.0], "reference_impedance": 50.0,
        "sub": {"er": 4.4, "h_mm": 1.6, "tan_d": 0.02},
    }, ensure_ascii=False), encoding="utf-8")
    rows = ["freq_hz,re_S11,im_S11,re_S21,im_S21"]
    for i in range(2):
        rows.append(f"{(2.0 + 0.5 * i) * 1e9:.1f},0.06,0.08,0.5,0.5")
    (run / "sparams.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return run


class TestReportChainHookup:
    @pytest.fixture()
    def run_dir(self, tmp_path):
        return _make_run(tmp_path)

    def test_default_model_has_no_domains_key(self, run_dir, tmp_path):
        model = build_report_model(run_dir)
        assert "domains" not in model
        # 缺省 HTML 与既有逐字节一致（无 domains 节增量）
        html = render_html(model)
        assert "sec-domains" not in html
        typ = render_typ(model)
        assert "垂直域摘要" not in typ

    def test_domains_section_renders_in_both_outputs(self, run_dir):
        results = {
            "aging": _aging_ok(),
            "pi": _pi_gate_ok(),
            "ota": {"trp": {"status": "ok", "trp_dbm": 28.25},
                    "eirp": {"status": "ok", "eirp_peak_dbm": 30.0},
                    "directivity": {"status": "ok", "d_db": 1.75},
                    "beam_efficiency": {"status": "ok", "efficiency": 0.42},
                    "grid_quality": {"coverage_fraction": 0.99}},
            "emc": {"verdict": "PASS", "min_margin_db": 5.0,
                    "min_margin_f_hz": 3.0e7, "first_violation_f_hz": None,
                    "n_violations": 0, "n_out_of_band": 0},
            "edb": _edb_input(),
        }
        model = build_report_model(run_dir, domain_results=results)
        assert model["domains"]["ok"] is True
        # U1 规则 2：全域裸数字零判定不破例（edb 节计数均带 source）
        assert bare_number_fields(model) == []
        html = render_html(model)
        assert 'id="sec-domains"' in html
        for title in ("老化漂移", "PI/PDN", "OTA", "EMC 辐射发射",
                      "EDB 快车道"):
            assert title in html, title
        assert "28.25" in html  # OTA 卡值透传
        assert "n_rows_total" in html  # edb 节指标名透传
        typ = render_typ(model)
        assert "垂直域摘要" in typ
        for title in ("老化漂移", "PI/PDN", "OTA", "EMC 辐射发射",
                      "EDB 快车道"):
            assert title in typ, title
        # HTML 零外网规则不破例
        assert external_resource_refs(html) == []

    def test_typ_template_has_conditional_domains_block(self):
        from rfauto.service.report_render import _TYP_TEMPLATE

        assert "{% if model.domains" in _TYP_TEMPLATE
        # 既有四段标题未被增补破坏（#146 吞标题防线）
        for heading in ("== 标识引用", "== 方法配置", "== 数据与判据",
                        "== 结论与异常"):
            assert heading in _TYP_TEMPLATE, heading
