"""DP-17 W2 单测——失败指纹库 playbook + explain_run 确定性解释器。

判据（runs/df6_dp17/criteria.md §W2）：
- 5 个已知 FAIL run 回放命中正确根因族（真仓只读；runs/ 缺席环境如实
  skip）+ 健康负例零命中不硬凑；
- playbook schema：规则字段齐备、指纹词表对齐、未知指纹规则如实 skip；
- 匹配确定性（同输入两次逐字节同输出）；多证并击只出候选族列表；
- 合成树单测：各检测器（健康因子/零填充/et 尾段/日志正则/unite 工件/
  verdict 工件/status）独立可驱动，不依赖真仓。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import ClassVar

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rfauto.service.explain_run import (
    collect_run_features,
    explain_run,
    load_playbook,
)


def _REPO_ROOT_of() -> Path:
    return Path(__file__).resolve().parents[2]


_REPO = Path(__file__).resolve().parents[2]
_REPO_RUNS = _REPO / "runs"
_PLAYBOOK = _REPO / "knowledge" / "diagnostics" / "playbook.yaml"


# ---------------------------------------------------------------------------
# playbook schema
# ---------------------------------------------------------------------------

class TestPlaybookSchema:
    def test_real_playbook_loads_and_fields_complete(self):
        book = load_playbook()
        assert book["ok"] is True
        assert book["rules"], "真 playbook 非空"
        vocab = set(book["detector_vocab"])
        assert vocab, "检测器词表非空"
        for rule in book["rules"]:
            assert rule.get("id"), "规则缺 id"
            fps = rule.get("symptom_fingerprints")
            assert isinstance(fps, list) and fps, f"{rule['id']} 缺指纹"
            for fp in fps:
                assert fp in vocab, f"{rule['id']} 引用词表外指纹 {fp}"
            assert rule.get("root_cause_family")
            assert isinstance(rule.get("forensic_commands"), list)
            assert isinstance(rule.get("pit_refs"), list)
            assert isinstance(rule.get("applicable_templates"), list)

    def test_rules_within_machine_observable_subset(self):
        """v1 只收可机器观测子集（criteria 预声明 15-25 条区间）。"""
        book = load_playbook()
        assert 10 <= len(book["rules"]) <= 25

    def test_missing_playbook_honest(self, tmp_path):
        r = load_playbook(tmp_path / "nope.yaml")
        assert r["ok"] is False and "不存在" in r["reason"]

    def test_unknown_fingerprint_rule_skipped_honest(self, tmp_path):
        p = tmp_path / "pb.yaml"
        p.write_text(yaml.safe_dump({
            "schema": "rfauto-diag-playbook-v1",
            "detector_vocab": ["known_fp"],
            "rules": [
                {"id": "bad", "symptom_fingerprints": ["ghost_fp"],
                 "root_cause_family": "x", "applicable_templates": ["*"]},
                {"id": "empty", "symptom_fingerprints": [],
                 "root_cause_family": "y", "applicable_templates": ["*"]},
            ],
        }), encoding="utf-8")
        r = explain_run(tmp_path, playbook_path=p)
        assert r["ok"] is True and r["overall"] == "no_hit"
        assert {s["id"] for s in r["skipped_rules"]} == {"bad", "empty"}


# ---------------------------------------------------------------------------
# 合成树检测器（无真仓依赖）
# ---------------------------------------------------------------------------

class TestSyntheticDetectors:
    def _make_run(self, tmp_path, *, meta=None, sparams_5col=False,
                  et_tail_ratio=None, err_text=None, unite_json=None,
                  verdict=None):
        d = tmp_path / "runs" / "syn"
        d.mkdir(parents=True, exist_ok=True)
        if meta is not None:
            (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        if sparams_5col:
            (d / "sparams.csv").write_text(
                "freq_hz,re_S11,im_S11,re_S21,im_S21\n"
                + "".join(f"{1e9 + i},0.5,0.1,0.01,0.0\n"
                          for i in range(30)), encoding="utf-8")
        if et_tail_ratio is not None:
            peak, n = 1.0, 100
            lines = [f"{i * 1e-12:.6e}\t{peak:.6f}\n" for i in range(n)]
            for i in range(int(n * 0.9), n):
                lines[i] = f"{i * 1e-12:.6e}\t{peak * et_tail_ratio:.6f}\n"
            (d / "fdtd").mkdir(exist_ok=True)
            (d / "fdtd" / "et").write_text("".join(lines), encoding="utf-8")
        if err_text is not None:
            (d / "case.err").write_text(err_text, encoding="utf-8")
        if unite_json is not None:
            (d / "attempt1.json").write_text(json.dumps(unite_json),
                                             encoding="utf-8")
        if verdict is not None:
            (d / "verdict.json").write_text(json.dumps(verdict),
                                            encoding="utf-8")
        return d

    def test_meta_status_failed_fingerprint(self, tmp_path):
        d = self._make_run(tmp_path, meta={"run_id": "syn", "status":
                                           "failed"})
        r = collect_run_features(d)
        assert "meta_status_failed" in r["fingerprints"]
        r2 = explain_run(d)
        assert r2["candidates"] == ["run_execution_failed"]

    def test_zerofill_and_et_tail_and_rules(self, tmp_path):
        d = self._make_run(tmp_path, sparams_5col=True, et_tail_ratio=0.2)
        r = explain_run(d)
        assert "sparam_partial_matrix_zerofill" in r["fingerprints"]
        assert "fdtd_tail_not_decayed" in r["fingerprints"]
        # 只有零填充指纹在场（无 S 参数健康因子）→ 掩码语义族
        assert "single_excitation_mask_semantics" in r["candidates"]

    def test_decayed_tail_no_fingerprint(self, tmp_path):
        d = self._make_run(tmp_path, et_tail_ratio=0.0001)
        r = collect_run_features(d)
        assert "fdtd_tail_not_decayed" not in r["fingerprints"]

    def test_log_pattern_and_unite_and_verdict(self, tmp_path):
        d = self._make_run(
            tmp_path,
            err_text="Traceback\n关闭 AEDT 失败（忽略）: Design."
                     "release_desktop() got an unexpected keyword\n",
            unite_json={"unite_result": "False",
                        "helix_objects_after_unite": 15},
            verdict={"verdict": "FAIL: 某门未达"},
        )
        r = explain_run(d)
        fps = r["fingerprints"]
        assert "pyaedt_release_error" in fps
        assert "unite_incomplete" in fps
        assert "verdict_fail_recorded" in fps
        fams = set(r["candidates"])
        assert {"pyaedt_session_leak", "hfss_cad_unite_failure",
                "judgment_gate_fail"} <= fams

    def test_arbitration_gate_fail_fingerprint(self, tmp_path):
        d = self._make_run(tmp_path)
        (d / "arbitration_result.json").write_text(json.dumps(
            {"verdict": "FAIL", "gate": 0.1}), encoding="utf-8")
        r = explain_run(d)
        assert "arbitration_gate_fail" in r["fingerprints"]
        assert "hfss_port_convention_gap" in r["candidates"]
        assert "judgment_gate_fail" in r["candidates"]

    def test_healthy_run_zero_hit(self, tmp_path):
        d = self._make_run(tmp_path, meta={"run_id": "syn", "status": "done"})
        r = explain_run(d)
        assert r["overall"] == "no_hit"
        assert r["candidates"] == []
        assert r["matched_rules"] == []

    def test_template_scoping_blocks_nonwildcard_rule(self, tmp_path):
        p = tmp_path / "pb.yaml"
        p.write_text(yaml.safe_dump({
            "schema": "rfauto-diag-playbook-v1",
            "detector_vocab": ["meta_status_failed"],
            "rules": [{"id": "scoped", "symptom_fingerprints":
                       ["meta_status_failed"],
                       "root_cause_family": "fam",
                       "applicable_templates": ["only_this_template"]}],
        }), encoding="utf-8")
        d = self._make_run(tmp_path, meta={"run_id": "syn", "model": "mline",
                                           "status": "failed"})
        r = explain_run(d, playbook_path=p)
        assert r["overall"] == "no_hit"  # mline 不在 applicable_templates

    def test_determinism(self, tmp_path):
        d = self._make_run(tmp_path, sparams_5col=True, et_tail_ratio=0.2,
                           verdict={"verdict": "FAIL"})
        r1 = explain_run(d)
        r2 = explain_run(d)
        assert r1 == r2

    def test_missing_run_dir_honest(self, tmp_path):
        r = explain_run(tmp_path / "nope")
        assert r["ok"] is False and "不存在" in r["reason"]


# ---------------------------------------------------------------------------
# 真仓回放（判据主表：5 FAIL 命中 + 1 健康负例；runs/ 缺席环境 skip）
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _REPO_RUNS.is_dir(), reason="真仓 runs/ 缺席环境")
class TestRealRunsReplay:
    # 用例回放 runs/ 真机证据目录（不随 git 分发）——缺失环境整组诚实 skip。
    pytestmark = pytest.mark.skipif(
        not (_REPO_ROOT_of() / 'runs' / 'hairpin_calib').exists(),
        reason='runs/ evidence not distributed with git')

    CASES: ClassVar[list] = [
        ("R1_fdtd_truncation", "hairpin_calib/kgap_b3_n3_invalid_fc200",
         "fdtd_truncation_artifact"),
        ("R2_hfss_mapes_arb", "hfss_mapes_m_arb",
         "hfss_port_convention_gap"),
        ("R3_helix_unite_undecidable", "helix_arbitration",
         "hfss_cad_unite_failure"),
        ("R3b_helix_undecidable", "helix_arbitration",
         "hfss_sheet_compression_undecidable"),
        ("R4_icepak_session_leak", "icepak_electrothermal",
         "pyaedt_session_leak"),
        ("R5_mask_semantics", "hairpin_calib/kgap2_g0500",
         "single_excitation_mask_semantics"),
    ]

    @pytest.mark.parametrize("label,rel,expected_family", CASES,
                             ids=[c[0] for c in CASES])
    def test_fail_run_hits_expected_family(self, label, rel, expected_family):
        r = explain_run(_REPO_RUNS / rel)
        assert r["ok"] is True
        assert r["overall"] == "candidates"
        assert expected_family in r["candidates"], \
            f"{label}: {expected_family} 不在候选 {r['candidates']}"
        # 期望族携带取证命令与坑号链
        rule = next(x for x in r["matched_rules"]
                    if x["root_cause_family"] == expected_family)
        assert rule["forensic_commands"]
        assert isinstance(rule["pit_refs"], list)

    def test_r1_truncation_is_top_candidate(self):
        r = explain_run(_REPO_RUNS / "hairpin_calib/kgap_b3_n3_invalid_fc200")
        assert r["candidates"][0] == "fdtd_truncation_artifact"

    def test_healthy_fake_run_zero_hit(self):
        r = explain_run(_REPO_RUNS / "20260829_191826_da184d1d")
        assert r["ok"] is True
        assert r["overall"] == "no_hit"
        assert r["candidates"] == []
        assert r["fingerprints"] == {}
