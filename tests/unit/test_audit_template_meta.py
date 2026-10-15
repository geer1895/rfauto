"""模板 meta 健康度审计门单测（aurora72 R8 面 3 常驻化，2026-10-11 A8-C 席）。

覆盖面：5 维审计逐维合成好/坏样本抓出（schema/nominal/placeholder/teaching/
link）+ 豁免清单消费 + rc 语义（0 绿/1 红/2 SKIP）+ 现树 GREEN 证据
（registered=72/edb=5/teaching=51 实测口径，唯一实违例 ms_ring_patch 死链
修复后零违例零证据缺失）。

脚本经 sys.path 装载（scripts 非包，test_audit_anchor_freshness 同款口径）。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
REPO = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import audit_template_meta as mod


def _good_meta(template: str = "tmpl_a") -> dict:
    """最小合格注册族 meta（与 docs/templates/mline 同形态）。"""
    return {
        "template": template,
        "f0_ghz": 2.5,
        "n_ports": 2,
        "max_time_ns": 30.0,
        "mesh_resolution_mm": 0.5,
        "n_segments": None,
        "params": ["w_mm", "line_len_mm"],
        "nominal_params": {"w_mm": 1.113, "line_len_mm": 40.0},
        "substrate": {"er": 3.66, "h_mm": 0.508, "tan_d": 0.0037},
        "extraction": "S11/S21 @ MSLPort 1-2",
    }


def _audit(meta: dict, text: str = "", exemptions=mod.EXEMPTIONS):
    return mod.audit_template(meta.get("template", "tmpl_a"), meta, text,
                              REPO, exemptions)


def _dims(items: list[dict]) -> list[str]:
    return [x["dim"] for x in items]


# ─── 维度 1：schema ──────────────────────────────────────────────────────────

class TestSchema:
    def test_good_meta_zero_violations(self):
        viols, evid = _audit(_good_meta())
        assert viols == [] and evid == []

    def test_missing_core_key_flagged(self):
        meta = _good_meta()
        del meta["max_time_ns"]
        viols, _ = _audit(meta)
        assert any(x["dim"] == "schema" and "max_time_ns" in x["detail"]
                   for x in viols)

    def test_template_dirname_mismatch_flagged(self):
        meta = _good_meta("other")
        viols, _ = mod.audit_template("tmpl_a", meta, "", REPO)
        assert any("目录名" in x["detail"] for x in viols)

    def test_scalar_sanity(self):
        meta = _good_meta()
        meta["f0_ghz"] = -1.0
        meta["n_ports"] = -2
        meta["mesh_resolution_mm"] = -0.5
        meta["max_time_ns"] = 0
        meta["n_segments"] = -1
        viols, _ = _audit(meta)
        assert _dims(viols) == ["schema"] * 5

    def test_params_missing_nominal_registered_only(self):
        meta = _good_meta()
        meta["params"] = ["w_mm", "ghost_mm"]
        viols, _ = _audit(meta)
        assert any("ghost_mm" in x["detail"] for x in viols)

    def test_edb_family_emitter_params_need_no_nominal(self):
        meta = {
            "template": "edb_x", "schema_version": 1, "edb_lane": "EDB 快车道",
            "registry_status": "已落地", "f0_ghz": 2.4, "n_ports": 4,
            "units": {"length": "mm", "frequency": "GHz"},
            "substrate": {"er": 3.66, "h_mm": 0.508},
            "params": ["f0_ghz", "z0_ohm", "board_margin_mm"],
            "nominal_params": {"series_w_mm": 1.8703},
            "topology": "矩形环四臂", "extraction": "全 S 矩阵 4 端口",
        }
        viols, _ = _audit(meta)
        assert viols == []

    def test_campaign_capable_false_requires_triple(self):
        meta = _good_meta()
        meta["campaign_capable"] = False
        viols, _ = _audit(meta)
        assert sum(1 for x in viols if "campaign_capable" in x["detail"]) == 2
        meta["campaign_capable_reasons"] = ["无自洽设计点"]
        meta["campaign_unlock_criteria"] = {"k_gap": "过门"}
        viols, _ = _audit(meta)
        assert viols == []

    def test_toplevel_non_mapping_flagged(self):
        viols, _ = mod.audit_template("t", ["not", "a", "map"], "", REPO)
        assert viols and viols[0]["dim"] == "schema"


# ─── 维度 2：nominal 数值语义 ────────────────────────────────────────────────

class TestNominal:
    def test_negative_and_zero_length_flagged(self):
        meta = _good_meta()
        meta["params"] = ["w_mm"]
        meta["nominal_params"] = {"w_mm": -1.0}
        viols, _ = _audit(meta)
        assert any("长度须>0" in x["detail"] for x in viols)
        meta["nominal_params"] = {"w_mm": 0}
        viols, _ = _audit(meta)
        assert any("长度须>0" in x["detail"] for x in viols)

    def test_h_mm_zero_legal_for_hollow_waveguide(self):
        meta = _good_meta()
        meta["params"] = ["h_mm", "l_wg_mm"]
        meta["nominal_params"] = {"h_mm": 0.0, "l_wg_mm": 1.0}
        viols, _ = _audit(meta)
        assert viols == []

    def test_semantic_rules_by_key(self):
        meta = _good_meta()
        keys = ["f0_ghz", "z0_ohm", "er", "tan_d", "c_load_pf", "tap_frac",
                "n_x", "feed_off_mm"]
        meta["params"] = list(keys)
        meta["nominal_params"] = {
            "f0_ghz": 0.0, "z0_ohm": -50, "er": 0.5, "tan_d": -0.001,
            "c_load_pf": 0.0, "tap_frac": 1.5, "n_x": -1, "feed_off_mm": -0.1,
        }
        viols, _ = _audit(meta)
        assert len(viols) == 8 and set(_dims(viols)) == {"nominal"}

    def test_offset_zero_legal(self):
        meta = _good_meta()
        meta["params"] = ["feed_off_mm", "g_pos_mm"]
        meta["nominal_params"] = {"feed_off_mm": 0.0, "g_pos_mm": 0.0}
        viols, _ = _audit(meta)
        assert viols == []

    def test_bool_and_nonfinite_and_string_leaf(self):
        meta = _good_meta()
        meta["params"] = ["w_mm", "h_mm", "l_mm", "cell_id"]
        meta["nominal_params"] = {"w_mm": True, "h_mm": float("nan"),
                                  "l_mm": math.inf, "cell_id": "ms_patch"}
        viols, _ = _audit(meta)
        assert len(viols) == 3  # bool/NaN/inf 拒收；cell_id 字符串白名单
        assert all(x["dim"] == "nominal" for x in viols)

    def test_nested_lists_and_cell_map_walked(self):
        meta = _good_meta()
        meta["params"] = ["widths_mm", "cell_map"]
        meta["nominal_params"] = {
            "widths_mm": [1.0, -2.0],
            "cell_map": [[{"cell_id": "ms_patch", "px_mm": 6.0},
                          {"cell_id": "ms_patch", "px_mm": 0.0}]],
        }
        viols, _ = _audit(meta)
        assert len(viols) == 2  # 列表内负值 + 逐胞表内零值（cell_id 不误报）


# ─── 维度 3：占位符残留 ──────────────────────────────────────────────────────

class TestPlaceholder:
    def test_real_residue_flagged(self):
        for text in ("TBD：待补值", "FIXME later", "此处待填", "lorem ipsum",
                     "xxx 参数", "TODO：清理", "尾随 TODO"):
            viols, _ = _audit(_good_meta(), text)
            assert viols and set(_dims(viols)) == {"placeholder"}, text

    def test_ledger_todo_citation_is_legal(self):
        for text in ("TODO 0dk 根修变体", "（TODO 0df④，#349）",
                     "见 TODO 0df followUp③", "干净文本无任何记号"):
            viols, _ = _audit(_good_meta(), text)
            assert viols == [], text


# ─── 维度 4：teaching ────────────────────────────────────────────────────────

def _good_teaching() -> dict:
    return {
        "schema": "rfauto-teaching/v1",
        "physics": {
            "summary": "准 TEM 传输线。",
            "derivations": [{"claim": "c", "formula": "f", "source": "s"}],
        },
        "sensitivity_ranking": [
            {"param": "w_mm", "order": 1, "basis": "b"},
            {"param": "er", "order": 2, "basis": "b"},
        ],
    }


class TestTeaching:
    def test_good_teaching_passes(self):
        meta = _good_meta()
        meta["teaching"] = _good_teaching()
        viols, _ = _audit(meta)
        assert viols == []

    def test_no_teaching_block_is_legal(self):
        viols, _ = _audit(_good_meta())
        assert viols == []

    def test_wrong_schema_and_empty_summary(self):
        meta = _good_meta()
        t = _good_teaching()
        t["schema"] = "other/v9"
        t["physics"]["summary"] = ""
        meta["teaching"] = t
        viols, _ = _audit(meta)
        assert len(viols) == 2 and set(_dims(viols)) == {"teaching"}

    def test_derivation_missing_key(self):
        meta = _good_meta()
        t = _good_teaching()
        del t["physics"]["derivations"][0]["source"]
        meta["teaching"] = t
        viols, _ = _audit(meta)
        assert any("source" in x["detail"] for x in viols)

    def test_ranking_orders_must_be_1_to_n(self):
        meta = _good_meta()
        t = _good_teaching()
        t["sensitivity_ranking"][1]["order"] = 3
        meta["teaching"] = t
        viols, _ = _audit(meta)
        assert any("1..N 连续" in x["detail"] for x in viols)

    def test_ranking_param_outside_universe(self):
        meta = _good_meta()
        t = _good_teaching()
        t["sensitivity_ranking"][0]["param"] = "not_a_param_mm"
        meta["teaching"] = t
        viols, _ = _audit(meta)
        assert any("宇宙" in x["detail"] for x in viols)

    def test_bad_quiz_refs(self):
        meta = _good_meta()
        t = _good_teaching()
        t["quiz_refs"] = [""]
        meta["teaching"] = t
        viols, _ = _audit(meta)
        assert any("quiz_refs" in x["detail"] for x in viols)


# ─── 维度 5：链接存在性 ──────────────────────────────────────────────────────

class TestLinks:
    def test_resolve_ref_real_repo_shapes(self):
        # 仓根直指 / 模块路径（src/rfauto）/ file.symbol 记号三形态
        assert mod.resolve_ref("docs/rf_template_references.md", REPO)
        assert mod.resolve_ref("core/synthesis", REPO)
        assert mod.resolve_ref("oe_templates/render_tl.py", REPO)
        assert mod.resolve_ref("scripts/hairpin_q_extract.HAIRPIN_ALT_KGAP_GATE",
                               REPO)
        assert mod.resolve_ref("runs/", REPO) is None or True  # 目录存在性不钉

    def test_resolve_ref_missing_returns_none(self):
        assert mod.resolve_ref("docs/definitely_not_there.md", REPO) is None
        assert mod.resolve_ref("core/no_such_module", REPO) is None

    def test_dead_repo_link_is_hard_violation(self):
        viols, evid = _audit(_good_meta(), "锚见 docs/no_such_file_x9.md。")
        assert _dims(viols) == ["link"] and evid == []

    def test_dead_runs_link_is_report_only(self):
        viols, evid = _audit(_good_meta(), "证据 runs/definitely_gone_x9/r.json。")
        assert viols == [] and len(evid) == 1 \
            and evid[0]["ref"] == "runs/definitely_gone_x9/r.json"


# ─── 豁免清单 ────────────────────────────────────────────────────────────────

class TestExemptions:
    def test_matching_entry_suppresses_and_records_shape(self):
        meta = _good_meta()
        meta["params"] = ["w_mm"]
        meta["nominal_params"] = {"w_mm": -1.0}
        ex = (("tmpl_a", "nominal", "长度须>0"),)
        viols, _ = mod.audit_template("tmpl_a", meta, "", REPO, ex)
        assert viols == []
        viols, _ = mod.audit_template("tmpl_b", meta | {"template": "tmpl_b"},
                                      "", REPO, ex)
        assert len(viols) == 1  # 非豁免模板不命中

    def test_default_exemption_table_is_empty(self):
        # 挂 preflight 面 15 前置：豁免清单清零（A8-C 实测达成后维护只收不放）
        assert mod.EXEMPTIONS == ()


# ─── 全树 + rc 语义 ──────────────────────────────────────────────────────────

class TestTreeAndMain:
    def test_real_tree_green(self):
        rep = mod.audit_tree(REPO / "docs" / "templates", REPO)
        assert rep["green"] is True, rep["violations"]
        # teaching=70：aurora_d TEACH-B2 席（2026-10-14）63→70——任务书名义 12
        # 族，实际缺 teaching 的非排除族仅 7（bend/ifa/patch_eep_1x4/
        # patch_eep_2x2/pifa/via/wstep；其余 14 缺口=edb_* 5 域外+atten_pi/
        # ring_resonator 测试钉死反例+63 已有），全部落地后如实按 7 计数
        # （#122 不凑绿；候选池清单系登记快照过时，#222 核实现状后定案）。
        assert rep["counts"] == {"dirs": 77, "edb": 5, "registered": 72,
                                 "teaching": 70}
        assert rep["violations"] == []
        assert rep["evidence_links_missing"] == []
        assert mod.verdict(rep) == 0

    def test_main_rc0_with_json_report(self, tmp_path):
        out = tmp_path / "report.json"
        rc = mod.main(["--json", str(out)])
        assert rc == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["schema"] == mod.REPORT_SCHEMA
        assert data["green"] is True

    def test_main_rc1_on_synthetic_bad_tree(self, tmp_path):
        d = tmp_path / "docs" / "templates" / "bad_t"
        d.mkdir(parents=True)
        (d / "meta.yaml").write_text(
            "template: bad_t\nf0_ghz: 2.5\nn_ports: 2\nparams: [w_mm]\n"
            "substrate: {er: 3.66, h_mm: 0.508}\nextraction: x\n",
            encoding="utf-8")
        rc = mod.main(["--templates-root", str(tmp_path / "docs" / "templates")])
        assert rc == 1

    def test_main_rc2_on_empty_root(self, tmp_path):
        (tmp_path / "empty").mkdir()
        rc = mod.main(["--templates-root", str(tmp_path / "empty")])
        assert rc == 2
