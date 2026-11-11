"""layered_stack 判读对照服务单测（aurora_q 席位 Q-X26）。

消费契约：判据门限唯一事实源 = runs/aurora_q/qx10_smoke/qx10_verdict.py
（#122 冻结）——本文件**零门限数字重声明**（唯一钉死的数字=真实模块
closed_form 锚 1.6007603731686557 的冻结容差与 A 档冻结窗，来源
qx10_verdict selftest 与 criteria_qx11.md），服务接线/白名单/对照/三因
子分解全部用**合成 verdict 模块**（tmp_path 落盘，接口同形）验证；真实
模块两测试（skipif：干净检出诚实 skip）钉①加载+冻结锚+A 档配置注入、
②真实 selftest 零回归（只读消费，零改动）。

负例面（任务书预声明）：产物缺 → INCOMPLETE 透传；verdict 缺失/未判
档在对照表原样透传不升格；白名单外注入键（门限常量）→ fail-loud。
零网络零真机零 SSH（硬约束 5）：全部断言离线纯函数。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from rfauto.service import layered_stack_verdict_service as lsv

REPO = Path(__file__).resolve().parents[2]
REAL_VERDICT = (REPO / "runs" / "aurora_q" / "qx10_smoke"
                / "qx10_verdict.py")

# ── 合成 verdict 模块（接口同形 stub；INCOMPLETE 透传语义照录真实契约）────
SYNTHETIC_MODULE = '''"""synthetic qx10-verdict-compatible stub（tests only）。"""
MESH_RESOLUTION_MM = 0.04
NRTS = 51000
EXCITE_PORT = 1
G1_PASS, G1_PARTIAL = 0.02, 0.05
CANNED_STATS = {"eps_eff_med": 1.6, "over_unity_cnt": 0, "audit_ok": True}


def closed_form_anchor():
    return {"eps_eff": 1.6, "z0_ohm": 50.0, "w_mm": 0.5}


def gate_g0_anchor(meta_closed_form):
    return {"gate": "G0", "status": "PASS"}


def gate_g1_beta(eps):
    return {"gate": "G1", "status": "PASS"}


def gate_g2_s11_valley(f_valley_ghz, depth_db):
    return {"gate": "G2", "status": "PASS"}


def gate_g3_health(passivity_max, over_unity_cnt, audit_ok, plane_dist_ok):
    return {"gate": "G3", "status": "PASS"}


def structural_sentinel(measured):
    return {"gate": "S0", "status": "PASS"}


def collect_stats(rundir):
    return dict(CANNED_STATS)


def judge_qx10(measured, meta_closed_form=None):
    if measured is None:
        return {"verdict": "INCOMPLETE",
                "missing": ["sparams.csv/port_beta.csv"]}
    return {"verdict": "AGREE", "measured_seen": measured,
            "meta_seen": meta_closed_form,
            "mesh_seen": MESH_RESOLUTION_MM, "nrts_seen": NRTS,
            "excite_seen": EXCITE_PORT}


def nominal_plane_dist_m(base_m):
    return 0.0
'''

BROKEN_MODULE = SYNTHETIC_MODULE.replace(
    'def structural_sentinel(measured):\n'
    '    return {"gate": "S0", "status": "PASS"}\n\n\n', ''
).replace(
    'def gate_g0_anchor(meta_closed_form):\n'
    '    return {"gate": "G0", "status": "PASS"}\n\n\n', ''
).replace(
    'def nominal_plane_dist_m(base_m):\n    return 0.0\n', ''
)

A_DT_FS = 9.297037451221739          # budget_a_auto.json exec 实测
A_BASE_MM = 0.01655342703385268      # 同上（A_auto 档实测 base）
C_DT_FS = 12.253783221768696         # budget_ladder.json C 行 exec 实测
A_NRTS_FROZEN = 135000               # criteria_qx11.md §3 冻结取整档


def _write_module(tmp_path: Path, text: str, name: str = "vmod.py") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _touch_products(rundir: Path) -> None:
    rundir.mkdir(parents=True, exist_ok=True)
    (rundir / "sparams.csv").write_text("freq_hz\n", encoding="utf-8")
    (rundir / "port_beta.csv").write_text("freq_hz\n", encoding="utf-8")


def _s0_trigger_verdict() -> dict:
    """真实 C 档 post-fix verdict 同形（S0 TRIGGER → INCOMPLETE 透传）。"""
    return {
        "verdict": "INCOMPLETE",
        "g0_status": "PASS",
        "s0_structure": {"gate": "S0", "status": "TRIGGER",
                         "failed": ["beta_linearity_r2", "port_agreement"],
                         "checks": {}},
        "port_structure_suspect": True,
        "note": "结构哨兵触发（S0 port-structure）……",
    }


def _legacy_truncation_verdict() -> dict:
    """Q-X11 旧版 verdict 同形（无 S0；计数只在 note 文本）。"""
    return {
        "verdict": "INCOMPLETE",
        "truncation_suspect": True,
        "g0_status": "PASS",
        "note": "|S|>1 命中 #262 家族截断嫌疑——加倍 NrTS 复跑后再判读"
                "（判据冻结不改）；over_unity_cnt=201",
    }


def _full_gates_verdict() -> dict:
    return {
        "verdict": "AGREE",
        "g0_status": "PASS",
        "s0_structure": {"status": "PASS", "failed": []},
        "gates": {
            "G1": {"status": "PASS", "observed_eps_eff": 1.6101,
                   "closed_eps_eff": 1.6008, "rel": 0.006},
            "G2": {"status": "PASS"},
            "G3": {"status": "PASS", "s_over_unity_cnt": 3},
        },
        "info": {},
    }


# ── 判据模块加载 ─────────────────────────────────────────────────────────────
class TestLoadVerdictModule:
    def test_missing_file_fail_loud(self):
        with pytest.raises(FileNotFoundError, match="fail-loud"):
            lsv.load_verdict_module(
                Path(sys.modules[__name__].__file__).parent / "nope.py")

    def test_missing_required_attrs_fail_loud(self, tmp_path):
        path = _write_module(tmp_path, BROKEN_MODULE, "broken.py")
        with pytest.raises(ValueError, match="structural_sentinel"):
            lsv.load_verdict_module(path)

    def test_config_injection_and_coercion(self, tmp_path):
        path = _write_module(tmp_path, SYNTHETIC_MODULE)
        m = lsv.load_verdict_module(path, config={
            "mesh_resolution_mm": "0.01655342703385268", "nrts": "135000",
            "excite_port": 1})
        # 字符串十进制 → float 强转后与字面量逐位同值（同双精度表示）
        assert m.MESH_RESOLUTION_MM == A_BASE_MM
        assert m.NRTS == 135000 and isinstance(m.NRTS, int)
        assert m.EXCITE_PORT == 1

    def test_non_whitelist_key_rejected(self, tmp_path):
        path = _write_module(tmp_path, SYNTHETIC_MODULE)
        with pytest.raises(ValueError, match="白名单"):
            lsv.load_verdict_module(path, config={"G1_PASS": 0.9})

    def test_fresh_instances_isolated_and_no_sys_modules(self, tmp_path):
        path = _write_module(tmp_path, SYNTHETIC_MODULE)
        m1 = lsv.load_verdict_module(path, config={"nrts": 1000})
        m2 = lsv.load_verdict_module(path, config={"nrts": 2000})
        assert m1.NRTS == 1000 and m2.NRTS == 2000
        assert m2.MESH_RESOLUTION_MM == 0.04  # m1 注入不污染 m2
        assert m1 is not m2
        assert not [k for k in sys.modules
                    if k.startswith("_qx10_verdict_fresh_")]


# ── 判读入口（产物缺 → INCOMPLETE 透传）─────────────────────────────────────
class TestJudgeEntries:
    def test_missing_products_incomplete_passthrough(self, tmp_path):
        empty = tmp_path / "empty_run"
        empty.mkdir()
        out = lsv.judge_products(empty, config={"nrts": 51000},
                                 verdict_module_path=_write_module(
                                     tmp_path, SYNTHETIC_MODULE))
        assert out["products_ok"] is False
        assert out["stats"] is None
        assert out["verdict"]["verdict"] == "INCOMPLETE"
        assert out["verdict"]["missing"] == ["sparams.csv/port_beta.csv"]
        assert out["run_config"]["nrts"] == 51000

    def test_delegation_measured_and_meta_and_config(self, tmp_path):
        rd = tmp_path / "run"
        _touch_products(rd)
        out = lsv.judge_products(
            rd, meta_closed_form={"epsilon_eff": 1.6, "z0_ohm": 50.0},
            config={"mesh_resolution_mm": A_BASE_MM, "nrts": 135000},
            verdict_module_path=_write_module(tmp_path, SYNTHETIC_MODULE))
        v = out["verdict"]
        assert v["verdict"] == "AGREE"
        assert v["measured_seen"] == {"eps_eff_med": 1.6,
                                      "over_unity_cnt": 0, "audit_ok": True}
        assert v["meta_seen"] == {"epsilon_eff": 1.6, "z0_ohm": 50.0}
        assert v["mesh_seen"] == pytest.approx(A_BASE_MM, rel=1e-15)
        assert v["nrts_seen"] == 135000
        assert out["run_config"] == {
            "mesh_resolution_mm": pytest.approx(A_BASE_MM, rel=1e-15),
            "nrts": 135000, "excite_port": 1}

    def test_meta_auto_from_layered_stack_meta(self, tmp_path):
        rd = tmp_path / "run"
        _touch_products(rd)
        (rd / "layered_stack_meta.json").write_text(
            '{"closed_form": {"epsilon_eff": 1.65, "z0_ohm": 49.9,'
            ' "source": "core.calculators"}}', encoding="utf-8")
        out = lsv.judge_products(
            rd, config={"nrts": 100},
            verdict_module_path=_write_module(tmp_path, SYNTHETIC_MODULE))
        assert out["verdict"]["meta_seen"] == {"epsilon_eff": 1.65,
                                               "z0_ohm": 49.9}

    def test_judge_mirror_fail_loud_no_guess(self, tmp_path):
        vpath = _write_module(tmp_path, SYNTHETIC_MODULE)
        mirror = tmp_path / "mirror"
        mirror.mkdir()
        with pytest.raises(ValueError, match="nrts 必显式传入"):
            lsv.judge_mirror(mirror, audit_json={"base_m": 1e-5},
                             verdict_module_path=vpath)
        with pytest.raises(ValueError, match="audit_json 必显式传入"):
            lsv.judge_mirror(mirror, nrts=135000,
                             verdict_module_path=vpath)
        with pytest.raises(ValueError, match="base_m"):
            lsv.judge_mirror(mirror, audit_json={"cells": 1}, nrts=135000,
                             verdict_module_path=vpath)

    def test_judge_mirror_audit_base_injection(self, tmp_path):
        vpath = _write_module(tmp_path, SYNTHETIC_MODULE)
        mirror = tmp_path / "mirror"
        _touch_products(mirror)
        audit = tmp_path / "audit_nominal.json"
        audit.write_text('{"base_m": 1.655342703385268e-05,'
                         ' "cells": 26987400}', encoding="utf-8")
        out = lsv.judge_mirror(mirror, audit_json=audit, nrts=135000,
                               verdict_module_path=vpath)
        assert out["run_config"]["mesh_resolution_mm"] == pytest.approx(
            A_BASE_MM, rel=1e-12)
        assert out["run_config"]["excite_port"] == 1
        assert out["verdict"]["verdict"] == "AGREE"
        out2 = lsv.judge_mirror(mirror, audit_json={"base_m": 1.655e-5},
                                nrts=100, excite_port=2,
                                verdict_module_path=vpath)
        assert out2["run_config"]["excite_port"] == 2


# ── 修复后重发射 NrTS 推导（criteria_qx11.md §3 冻结规则同式）───────────────
class TestDeriveRelaunchNrts:
    def test_a_tier_dt_invariants_and_frozen_pick(self):
        r = lsv.derive_relaunch_nrts(dt_fs=A_DT_FS, pick=135000)
        c_win = r["c_doubled_window_ps"]
        assert c_win == pytest.approx(1249.885888620407, rel=1e-12)
        # 下界性质：min 档覆盖加倍窗、min−1 档不覆盖（ceil 正确性）
        assert r["nrts_min"] * A_DT_FS / 1000.0 >= c_win
        assert (r["nrts_min"] - 1) * A_DT_FS / 1000.0 < c_win
        # 冻结先例 pick=135000 合法且窗=实测 1255.1ps ≥ 加倍窗
        assert r["nrts_pick"] == 135000
        assert r["window_ps"] == pytest.approx(1255.100055914935,
                                               rel=1e-12)
        assert r["window_ratio_vs_c_doubled"] > 1.0

    def test_rejects_shrink_and_bad_inputs(self):
        r0 = lsv.derive_relaunch_nrts(dt_fs=A_DT_FS)
        with pytest.raises(ValueError, match="只许加窗不许减窗"):
            lsv.derive_relaunch_nrts(dt_fs=A_DT_FS,
                                     pick=r0["nrts_min"] - 1)
        with pytest.raises(ValueError, match="正有限"):
            lsv.derive_relaunch_nrts(dt_fs=0.0)
        with pytest.raises(ValueError, match="正有限"):
            lsv.derive_relaunch_nrts(dt_fs=float("nan"))
        with pytest.raises(ValueError, match="正整数"):
            lsv.derive_relaunch_nrts(dt_fs=A_DT_FS, c_nrts=0)


# ── 档位记录规约（None 透传；取值链带来源标注）──────────────────────────────
class TestBuildTierRecord:
    def test_none_verdict_passthrough_not_judged(self):
        row = lsv.build_tier_record("x", verdict=None)
        assert row["not_judged"] is True
        assert row["verdict"] is None
        assert row["s0_status"] is None
        assert row["over_unity_cnt"] is None
        assert row["over_unity_cnt_source"] == "missing"
        assert row["g1_status"] is None and row["g3_status"] is None

    def test_empty_verdict_dict_all_none(self):
        row = lsv.build_tier_record("x", verdict={})
        assert row["not_judged"] is False
        assert row["verdict"] is None
        assert row["port_structure_suspect"] is False
        assert row["truncation_suspect"] is False

    def test_s0_and_gates_extraction(self):
        row = lsv.build_tier_record("c_postfix",
                                    verdict=_s0_trigger_verdict())
        assert row["verdict"] == "INCOMPLETE"
        assert row["s0_status"] == "TRIGGER"
        assert row["s0_failed"] == ["beta_linearity_r2", "port_agreement"]
        assert row["port_structure_suspect"] is True
        assert row["g0_status"] == "PASS"
        full = lsv.build_tier_record("ok", verdict=_full_gates_verdict())
        assert (full["g1_status"], full["g2_status"],
                full["g3_status"]) == ("PASS", "PASS", "PASS")
        assert full["s0_status"] == "PASS"

    def test_over_unity_fallback_chain_with_source(self):
        stats = {"over_unity_cnt": 66}
        r1 = lsv.build_tier_record("a", verdict={}, stats=stats)
        assert (r1["over_unity_cnt"], r1["over_unity_cnt_source"]) == \
            (66, "stats")
        r2 = lsv.build_tier_record("b",
                                   verdict={"over_unity_cnt_also": 7})
        assert (r2["over_unity_cnt"], r2["over_unity_cnt_source"]) == \
            (7, "verdict.over_unity_cnt_also")
        r3 = lsv.build_tier_record("c", verdict=_full_gates_verdict())
        assert (r3["over_unity_cnt"], r3["over_unity_cnt_source"]) == \
            (3, "gates.G3")
        r4 = lsv.build_tier_record("d", verdict=_legacy_truncation_verdict())
        assert (r4["over_unity_cnt"], r4["over_unity_cnt_source"]) == \
            (201, "note_regex")

    def test_eps_and_window_derivation(self):
        r = lsv.build_tier_record("a", verdict=_full_gates_verdict(),
                                  stats=None, nrts=135000,
                                  mesh={"dt_fs": A_DT_FS, "base_mm": A_BASE_MM,
                                        "cells": 26987400})
        assert r["eps_eff_med"] == 1.6101
        assert r["eps_eff_med_source"] == "gates.G1"
        assert r["window_ps"] == pytest.approx(1255.100055914935, rel=1e-12)
        assert r["mesh_base_mm"] == A_BASE_MM
        no_dt = lsv.build_tier_record("b", verdict={}, nrts=100)
        assert no_dt["window_ps"] is None


# ── 三因子正交分解（RC1/RC2/RC3；预声明规则）────────────────────────────────
def _rec(name, *, s0=None, ou=None, suspect=False, base=None, geo=None,
         nrts=None, dt=None, verdict="INCOMPLETE"):
    return lsv.build_tier_record(
        name,
        verdict={"verdict": verdict, "s0_structure": s0,
                 "port_structure_suspect": suspect}
        if s0 is not None or suspect else {"verdict": verdict},
        stats={} if ou is None else {"over_unity_cnt": ou},
        nrts=nrts,
        mesh=None if base is None else {"base_mm": base, "cells": None,
                                        "dt_fs": dt},
        geometry=geo)


class TestDecomposeFactors:
    def test_per_tier_factor_statuses(self):
        recs = {
            "rc1_hit": lsv.build_tier_record(
                "rc1_hit", verdict=_s0_trigger_verdict(),
                stats={"over_unity_cnt": 201}),
            "pure_trunc": lsv.build_tier_record(
                "pure_trunc",
                verdict={"verdict": "INCOMPLETE",
                         "s0_structure": {"status": "PASS", "failed": []}},
                stats={"over_unity_cnt": 66}),
            "legacy": lsv.build_tier_record(
                "legacy", verdict=_legacy_truncation_verdict()),
            "healthy": lsv.build_tier_record(
                "healthy",
                verdict={"verdict": "AGREE",
                         "s0_structure": {"status": "PASS", "failed": []}},
                stats={"over_unity_cnt": 0}),
        }
        f = lsv.decompose_factors(recs)["factors"]
        assert f["rc1_hit"]["RC1_geometry_port_structure"] == "implicated"
        assert f["rc1_hit"]["RC3_truncation"] == "co_present_not_attributed"
        assert f["pure_trunc"]["RC1_geometry_port_structure"] == "excluded"
        assert f["pure_trunc"]["RC3_truncation"] == "implicated"
        assert f["legacy"]["RC1_geometry_port_structure"] == "unevaluated"
        assert f["legacy"]["RC3_truncation"] == "implicated"
        assert f["healthy"]["RC1_geometry_port_structure"] == "excluded"
        assert f["healthy"]["RC3_truncation"] == "excluded"
        for name in recs:
            assert f[name]["RC2_mesh_resolution"] == "indeterminate_per_tier"

    def test_pair_rc1_cured_mesh_dominant(self):
        recs = {
            "coarse": _rec("coarse", s0=_s0_trigger_verdict()["s0_structure"],
                           suspect=True, base=0.04, geo="pre-fix"),
            "fine": _rec("fine", s0={"status": "PASS", "failed": []},
                         base=0.0165534, geo="pre-fix"),
        }
        out = lsv.decompose_factors(recs)
        pair = out["pairs"][0]
        assert pair["rc1"]["pair_verdict"] == "cured_by_joint_refinement"
        assert pair["coarse"] == "coarse" and pair["fine"] == "fine"
        assert pair["base_ratio"] == pytest.approx(0.04 / 0.0165534, rel=1e-9)
        assert out["conclusions"]["RC2_mesh"] == "mesh_dominant_suspect"

    def test_pair_persists_and_rc3_attribution_block(self):
        recs = {
            "coarse": _rec("coarse", ou=66, base=0.04, geo="pre-fix",
                           nrts=51000, dt=C_DT_FS),
            "fine": lsv.build_tier_record(
                "fine", verdict=_s0_trigger_verdict(),
                stats={"over_unity_cnt": 201}, nrts=135000,
                mesh={"base_mm": 0.0165534, "cells": None, "dt_fs": A_DT_FS},
                geometry="pre-fix"),
        }
        out = lsv.decompose_factors(recs)
        pair = out["pairs"][0]
        assert pair["rc3"]["pair_verdict"] == "not_cured_by_joint_refinement"
        assert pair["rc3"]["fine_attribution_blocked_by_rc1"] is True
        assert pair["window_ratio"] == pytest.approx(
            135000 * A_DT_FS / (51000 * C_DT_FS), rel=1e-9)
        assert out["conclusions"][
            "RC3_truncation"] == "window_mesh_joint_refinement_not_cured"
        assert "orthogonality_caveat" in out["conclusions"]

    def test_different_geometry_no_pair(self):
        recs = {
            "pre": _rec("pre", s0=_s0_trigger_verdict()["s0_structure"],
                        suspect=True, base=0.04, geo="pre-fix"),
            "post": _rec("post", s0={"status": "PASS", "failed": []},
                         base=0.04, geo="post-fix"),
        }
        out = lsv.decompose_factors(recs)
        assert out["pairs"] == []
        assert out["conclusions"]["RC2_mesh"] == "not_observable"
        assert out["conclusions"]["geometry_labels_present"] == [
            "post-fix", "pre-fix"]


# ── 对照表（INCOMPLETE/未判透传不升格）───────────────────────────────────────
class TestCompareTiers:
    def test_incomplete_and_unjudged_passthrough(self):
        recs = {
            "judged": lsv.build_tier_record(
                "judged",
                verdict={"verdict": "INCOMPLETE",
                         "s0_structure": {"status": "PASS", "failed": []}},
                stats={"over_unity_cnt": 0}),
            "unjudged": lsv.build_tier_record("unjudged", verdict=None),
        }
        out = lsv.compare_tiers(recs)
        assert out["tiers"]["unjudged"]["verdict"] is None
        assert out["tiers"]["unjudged"]["not_judged"] is True
        assert out["summary"]["verdicts"]["judged"] == "INCOMPLETE"
        assert out["summary"]["n_incomplete"] == 1
        assert out["summary"]["n_judged"] == 1
        assert out["summary"]["n_tiers"] == 2

    def test_eps_eff_rel_and_closed_fill(self):
        recs = {
            "a": lsv.build_tier_record(
                "a", verdict={}, stats={"eps_eff_med": 1.8316975055804328}),
        }
        closed = 1.6007603731686557
        out = lsv.compare_tiers(recs, closed_eps_eff=closed)
        row = out["tiers"]["a"]
        assert row["eps_eff_closed"] == closed
        expect = abs(1.8316975055804328 - closed) / closed
        assert row["eps_eff_rel"] == pytest.approx(expect, rel=1e-12)
        bare = lsv.compare_tiers({"b": lsv.build_tier_record("b",
                                                             verdict={})})
        assert bare["tiers"]["b"]["eps_eff_rel"] is None


# ── 真实冻结判据模块（只读消费；干净检出诚实 skip）──────────────────────────
@pytest.mark.skipif(not REAL_VERDICT.is_file(),
                    reason="runs/ 判据单源不在树（干净检出）——诚实 skip")
class TestRealQx10VerdictModule:
    def test_load_frozen_anchor_and_a_config_injection(self):
        m = lsv.load_verdict_module(
            REAL_VERDICT,
            config={"mesh_resolution_mm": A_BASE_MM, "nrts": A_NRTS_FROZEN})
        assert m.NRTS == A_NRTS_FROZEN
        assert m.MESH_RESOLUTION_MM == A_BASE_MM
        anchor = m.closed_form_anchor()
        assert anchor["eps_eff"] == pytest.approx(1.6007603731686557,
                                                  rel=1e-12)
        assert anchor["z0_ohm"] == pytest.approx(50.0, abs=1e-9)
        # judge(None) → INCOMPLETE 透传（真实模块同契约）
        assert m.judge_qx10(None)["verdict"] == "INCOMPLETE"
        # S0 哨兵健康观测面 PASS（Q-X14 Fix3 接口在位）
        good = {"beta_r2_min": 0.999, "beta_r2_ports": [0.999, 0.998],
                "zl_re_med_ports": [49.0, 51.0],
                "beta_port_disagreement_med": 0.01}
        assert m.structural_sentinel(good)["status"] == "PASS"

    def test_real_selftest_zero_regression(self):
        m = lsv.load_verdict_module(REAL_VERDICT)
        assert m._selftest() == 0
