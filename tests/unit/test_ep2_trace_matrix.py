"""EP-2 四向追溯矩阵单测（specs §C-7）。

五组锚：
- B 档表格解析：extract_gate_lines 附加 table 结构化键，匹配集与 threshold
  语义不变（368 行登记稳定的实现保证）；
- 三档迁移：A（regex threshold）/B（表格行）/C（legacy_only）分档 + 幂等
  （同树同参二跑逐字节一致，二跑 diff=0）；
- curated v2 零改写：既有人工 v2 按 referee_run 识别跳过骨架，回读逐位；
- 四向键：gate_id/param_key(CALCULATOR)/test_id(pytest nodeid 模块路径，
  只读 collect 缓存)/anchor_id(锚注册表) 四域可解析；
- 审计：check_numbers trace——coverage/by_dim/dangling(编辑距离 top-3)/
  status；断链注入负例必 FAIL；覆盖率棘轮只升不降（首批 gate≥80%/param
  ≥60%）。

真树锚（index/tests 缓存缺在时诚实 skip——本测试钉工作区资产，不伪造）。
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from criteria_index_build import (
    FIRST_BATCH_FLOORS,
    build_index,
    criteria_id_of,
    curated_v2_run_keys,
    extract_gate_lines,
    migrate_v2,
    parse_table_row,
)

INDEX_PATH = _REPO_ROOT / "knowledge" / "criteria" / "index.yaml"
V2_DIR = _REPO_ROOT / "knowledge" / "criteria" / "v2"
SKELETON_DIR = V2_DIR / "skeleton"
TRACE_PATH = _REPO_ROOT / "knowledge" / "trace_matrix.yaml"
TESTS_CACHE = _REPO_ROOT / "runs" / "ep2" / "test_universe.txt"
CURATED_IDS = {"df6_dp10_scan_j1c_coverage", "df5_c3fix_sentinel_four_gates",
               "hfss_interdigital_check_m1"}

_SCRIPT = _REPO_ROOT / "scripts" / "check_numbers.py"
_SPEC = importlib.util.spec_from_file_location("_ep2_check_numbers", _SCRIPT)
check_numbers = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_numbers)


# ── ① B 档表格解析（附加结构化，匹配集不变）─────────────────────────────────


def test_b_tier_table_row_structured():
    gates = extract_gate_lines(
        "| dev（外推 vs 截断偏差） | ≤ 0.5dB | 0.627 | 0.552 |")
    assert len(gates) == 1
    g = gates[0]
    assert g["threshold"] == 0.5
    assert g["table"]["name"] == "dev（外推 vs 截断偏差）"
    assert g["table"]["op"] == "≤"
    assert g["table"]["unit"] == "dB"
    assert g["table"]["observed"] == [0.627, 0.552]


def test_b_tier_escaped_pipe_row_threshold_unchanged():
    # 真树 c4_z_substrate 门行（含 \| 转义竖线）：threshold 与 index 登记逐位一致
    gates = extract_gate_lines(
        "| cline_coupler | −5.4693 | −2.1877 | −2.9030 | \\|b₈\\| ≤ 1.4515% | 2.0321% |")
    assert len(gates) == 1
    assert gates[0]["threshold"] == 1.4515
    assert gates[0]["table"]["op"] == "≤"
    assert gates[0]["table"]["unit"] == "%"
    assert gates[0]["table"]["observed"] == []  # 实测列在门限列之前=不算 observed


def test_b_tier_separator_and_header_rows_not_matched():
    # 匹配集不变：分隔行/表头行/无比较符表格行一律不抽（368 登记稳定）
    assert parse_table_row("|---|---|---|") is None
    assert extract_gate_lines("|---|---|---|") == []
    assert extract_gate_lines("| 指标 | 门限 | 实测 |") == []
    assert extract_gate_lines("| a | b | c |") == []  # 无比较符无单位
    assert extract_gate_lines("普通散文行没有判据") == []


def test_pm_threshold_table_unit():
    gates = extract_gate_lines("| 偏差 | ± 0.02mm 以内 | 0.01 |")
    assert len(gates) == 1
    assert gates[0]["threshold"] == 0.02
    assert gates[0]["table"]["op"] is None  # ± 门无比较符
    assert gates[0]["table"]["unit"] == "mm"


# ── ② 三档迁移（tmp 树：分档 + 幂等 + 零改写）───────────────────────────────


def _make_tmp_tree(runs: Path) -> None:
    (runs / "cpw_gate").mkdir(parents=True)
    (runs / "cpw_gate" / "criteria.md").write_text(
        "# CPW 门\n- 谷深 ≤-10dB 才算起振\n- 预算帽 ≤12000s\n", encoding="utf-8")
    (runs / "cpw_gate2").mkdir(parents=True)
    (runs / "cpw_gate2" / "criteria.md").write_text(
        "# CPW 门二批\n- 谷深 ≤-10dB 才算起振\n- 预算帽 ≤12000s\n", encoding="utf-8")
    (runs / "cps_tbl").mkdir(parents=True)
    (runs / "cps_tbl" / "criteria.md").write_text(
        "# CPS 表格门\n| 指标 | 门限 | 实测 |\n|---|---|---|\n"
        "| dev | ≤ 0.5dB | 0.41 |\n| span | ≥ 20dB | 12.4 |\n", encoding="utf-8")
    (runs / "prose_only").mkdir(parents=True)
    (runs / "prose_only" / "criteria.md").write_text(
        "纯散文判读，无结构化门。\n", encoding="utf-8")


def _migrate_tmp(tmp_path: Path) -> tuple[dict, Path, Path]:
    runs = tmp_path / "runs"
    _make_tmp_tree(runs)
    v2_dir = tmp_path / "v2"
    v2_dir.mkdir()
    (v2_dir / "curated_probe.yaml").write_text(
        "schema: criteria/v2\ncriteria_id: curated_probe\n"
        "provenance: {referee_run: runs/cpw_gate/sentinel.json}\n",
        encoding="utf-8")
    index_doc = build_index(runs)
    skel = tmp_path / "skeleton"
    trace = tmp_path / "trace_matrix.yaml"
    summary = migrate_v2(
        index_doc=index_doc, index_sha256="in-memory", runs_root=runs,
        skeleton_dir=skel, trace_out=trace, curated_v2_dir=v2_dir,
        calc_names=("cpw_analysis", "cpw_synthesis", "cps_analysis",
                    "cps_synthesis"),
        anchor_pairs=[("cpw.k_of_g.cpw-v1", ["cpw"])],
        test_modules=("tests/unit/test_cpw_template.py",
                      "tests/unit/test_cps_template.py"),
        head_commit="testhead")
    return summary, skel, trace


def test_migrate_v2_tmp_tiers_curated_and_links(tmp_path):
    summary, skel, trace = _migrate_tmp(tmp_path)
    assert summary["ok"] is True
    # 三档：A=cpw_gate2（叙事 threshold）/B=cps_tbl（表格行）/
    # C=prose_only（legacy_only）；cpw_gate 被 curated 识别跳过骨架
    tf = summary["tier_files"]
    assert tf["A"] == 1 and tf["B"] == 1 and tf["curated"] == 1
    assert summary["n_legacy"] == 1
    assert summary["n_skeletons"] == 2
    assert "cpw_gate/criteria.md" in summary["skipped_curated"]
    assert not (skel / "cpw_gate.yaml").exists()       # curated 跳过
    assert not (skel / "prose_only.yaml").exists()     # C 档无骨架

    a_doc = yaml.safe_load((skel / "cpw_gate2.yaml").read_text(encoding="utf-8"))
    assert a_doc["schema"] == "criteria/v2"
    assert a_doc["status"] == "skeleton_v2"
    assert a_doc["runner_binding"] == "unmigrated"
    assert a_doc["migration"]["tier"] == "A"
    for key in ("u_num", "u_input", "u_D"):
        assert a_doc["u_val"][key]["source"] == "none_declared"  # 不虚构
    assert a_doc["verdict_map"] == {}
    assert a_doc["decision_rule"]["gates"][0]["gate_id"] == "cpw_gate2#1"
    assert a_doc["decision_rule"]["gates"][0]["threshold"] == 10.0

    b_doc = yaml.safe_load((skel / "cps_tbl.yaml").read_text(encoding="utf-8"))
    assert b_doc["migration"]["tier"] == "B"
    assert all(g["tier"] == "B" for g in b_doc["decision_rule"]["gates"])
    assert b_doc["decision_rule"]["gates"][0]["table"]["name"] == "dev"

    mtx = yaml.safe_load(trace.read_text(encoding="utf-8"))
    assert mtx["schema"] == "trace-matrix/v1"
    by_gate: dict[str, list[dict]] = {}
    for lk in mtx["links"]:
        assert set(lk) == {"gate_id", "param_key", "test_id", "anchor_id",
                           "strength"}
        assert lk["strength"] == "mechanical"
        assert "#" in lk["gate_id"]
        by_gate.setdefault(lk["gate_id"], []).append(lk)
    # cpw_gate2 门链到 cpw 综合/分析 + 模块测试；cps_tbl 门链到 cps 分析
    assert any(lk["param_key"] == "cpw_synthesis"
               for lk in by_gate["cpw_gate2#1"])
    assert any(lk["test_id"] == "tests/unit/test_cpw_template.py"
               for lk in by_gate["cpw_gate2#1"])
    assert any(lk["anchor_id"] == "cpw.k_of_g.cpw-v1"
               for lk in by_gate["cpw_gate2#1"])
    assert any(lk["param_key"] == "cps_analysis" for lk in by_gate["cps_tbl#1"])
    assert mtx["ratchet"]["gate_min_pct"] == FIRST_BATCH_FLOORS["gate_min_pct"]
    assert mtx["ratchet"]["param_min_pct"] == FIRST_BATCH_FLOORS["param_min_pct"]


def test_migrate_v2_tmp_idempotent_and_zero_rewrite(tmp_path):
    _summary1, skel, trace = _migrate_tmp(tmp_path)
    runs = tmp_path / "runs"
    md_bytes = {p: p.read_bytes() for p in sorted(runs.rglob("criteria.md"))}
    snapshot = {p: p.read_bytes() for p in sorted(skel.glob("*.yaml"))}
    snapshot[trace.name] = trace.read_bytes()

    # 二跑（同树同参）：diff=0
    index_doc = build_index(runs)
    summary2 = migrate_v2(
        index_doc=index_doc, index_sha256="in-memory", runs_root=runs,
        skeleton_dir=skel, trace_out=trace,
        curated_v2_dir=tmp_path / "v2",
        calc_names=("cpw_analysis", "cpw_synthesis", "cps_analysis",
                    "cps_synthesis"),
        anchor_pairs=[("cpw.k_of_g.cpw-v1", ["cpw"])],
        test_modules=("tests/unit/test_cpw_template.py",
                      "tests/unit/test_cps_template.py"),
        head_commit="testhead")
    assert summary2["ok"] is True
    for key, b in snapshot.items():
        cur = (trace if key == trace.name else skel / key).read_bytes()
        assert cur == b, f"二跑漂移: {key}"
    # md 零改写（迁移=附加不替代，#325/#326）
    for p, b in md_bytes.items():
        assert p.read_bytes() == b


# ── ③ 真树锚：真树重生成逐字节一致 + curated/index 零改写 ───────────────────

_need_real = pytest.mark.skipif(
    not (INDEX_PATH.is_file() and TRACE_PATH.is_file()
         and SKELETON_DIR.is_dir() and TESTS_CACHE.is_file()),
    reason="真树 EP-2 产物不在（干净检出）——不伪造")


@_need_real
def test_real_tree_regenerates_byte_identical(tmp_path):
    """幂等锚（真树）：同参重生成 → 矩阵与全部骨架逐字节一致（diff=0），
    且 index.yaml 与既有 curated v2 三个文件零改写。

    head_commit 取 shipped 骨架的 provenance.commit（生成时点 HEAD）——
    commit 戳=生成输入的一部分（诚实出处语义），并发轨推进 HEAD 后重生成
    合法地只变 commit 行，不构成幂等违例。"""
    index_bytes = INDEX_PATH.read_bytes()
    curated_files = sorted(V2_DIR.glob("*.yaml"))
    curated_bytes = {p.name: p.read_bytes() for p in curated_files}
    shipped_commit = next(iter(yaml.safe_load(
        p.read_text(encoding="utf-8"))["provenance"]["commit"]
        for p in sorted(SKELETON_DIR.glob("*.yaml"))))

    index_doc = yaml.safe_load(INDEX_PATH.read_text(encoding="utf-8"))
    import hashlib

    sha = hashlib.sha256(index_bytes).hexdigest()
    summary = migrate_v2(
        index_doc=index_doc, index_sha256=sha, runs_root=_REPO_ROOT / "runs",
        skeleton_dir=tmp_path / "skeleton", trace_out=tmp_path / "trace.yaml",
        curated_v2_dir=V2_DIR, head_commit=shipped_commit,
        test_modules=tuple(check_numbers.read_tests_cache(TESTS_CACHE)))
    assert summary["ok"] is True
    # 幂等口径（同 idempotency 锚一致）：ratchet 块=运行态棘轮（首次审计
    # --update-ratchet 上抬过，新路径重生成按设计回首批 floor）；其余逐字节
    # 一致。验证方式=把重生成文档的 ratchet 换成 shipped 值后整文档 dump 逐
    # 字节比对（换行归一 CRLF——write_text 平台差异，非内容）。
    from criteria_index_build import _dump_yaml

    shipped_text = TRACE_PATH.read_text(encoding="utf-8")
    shipped_doc = yaml.safe_load(shipped_text)
    regen_doc = yaml.safe_load((tmp_path / "trace.yaml").read_text(encoding="utf-8"))
    assert regen_doc["ratchet"]["gate_min_pct"] == FIRST_BATCH_FLOORS["gate_min_pct"]
    regen_doc["ratchet"] = shipped_doc["ratchet"]
    assert _dump_yaml(regen_doc).replace("\r\n", "\n") == \
        shipped_text.replace("\r\n", "\n")
    n_cmp = 0
    for p in sorted(SKELETON_DIR.glob("*.yaml")):
        assert p.name in {q.name for q in (tmp_path / "skeleton").glob("*.yaml")}
        assert (tmp_path / "skeleton" / p.name).read_bytes() == p.read_bytes(), \
            f"骨架二跑漂移: {p.name}"
        n_cmp += 1
    assert n_cmp == summary["n_skeletons"]
    assert INDEX_PATH.read_bytes() == index_bytes
    for p in curated_files:
        assert p.read_bytes() == curated_bytes[p.name]


@_need_real
def test_real_skeletons_and_curated_skip():
    """骨架=迁移档−curated 跳过；三件人工 curated v2 不在骨架目录。"""
    import re

    index_doc = yaml.safe_load(INDEX_PATH.read_text(encoding="utf-8"))
    n_migrate = sum(1 for e in index_doc["entries"]
                    if e["status"] == "migrate_to_v2")
    n_legacy = sum(1 for e in index_doc["entries"]
                   if e["status"] == "legacy_only")
    n_curated = sum(
        1 for e in index_doc["entries"] if e["status"] == "migrate_to_v2"
        if any(e["path"].split("/")[0] in k
               for k in curated_v2_run_keys(V2_DIR)))
    skeletons = sorted(SKELETON_DIR.glob("*.yaml"))
    assert len(skeletons) == n_migrate - n_curated
    ids = {yaml.safe_load(p.read_text(encoding="utf-8"))["criteria_id"]
           for p in skeletons}
    assert ids.isdisjoint(CURATED_IDS)
    for p in skeletons:
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        assert doc["status"] == "skeleton_v2"
        assert re.fullmatch(r"\S+#\d+", doc["decision_rule"]["gates"][0]["gate_id"])
        for key in ("u_num", "u_input", "u_D"):
            assert doc["u_val"][key]["source"] == "none_declared"
    assert n_legacy == 3  # C 档维持 legacy_only（不迁移）


@_need_real
def test_real_curated_v2_readback_bitwise():
    """既有 3 件 v2 回读零改写逐位：关键门值 float.hex 同位核对。"""
    docs = {}
    for p in sorted(V2_DIR.glob("*.yaml")):
        docs[yaml.safe_load(p.read_text(encoding="utf-8"))["criteria_id"]] = \
            yaml.safe_load(p.read_text(encoding="utf-8"))
    assert set(docs) == CURATED_IDS
    dp10 = docs["df6_dp10_scan_j1c_coverage"]
    assert float(dp10["decision_rule"]["threshold"]).hex() == (300.0).hex()
    assert dp10["decision_rule"]["comparison"] == ">="
    assert float(dp10["claim"]["f_ghz"]).hex() == (10.0).hex()
    assert dp10["u_val"]["u_num"]["source"] == "none_declared"
    sent = docs["df5_c3fix_sentinel_four_gates"]
    gates = sent["decision_rule"]["gates"]
    assert float(gates["dev_db"]["threshold"]).hex() == (0.5).hex()
    assert float(gates["holdout_rel"]["threshold"]).hex() == (0.05).hex()
    assert float(gates["span_db"]["threshold"]).hex() == (20.0).hex()
    assert float(gates["s21_inf_f0_db"]["threshold"]).hex() == (-3.0).hex()
    assert float(sent["decision_rule"]["budget_conditional"]["ratio_limit"]
                 ).hex() == (1.5).hex()
    m1 = docs["hfss_interdigital_check_m1"]
    assert float(m1["decision_rule"]["gate_db"]).hex() == (0.5).hex()
    assert float(m1["decision_rule"]["references"]["sentinel"]) == -14.4657
    # curated 三件不被迁移器改写为骨架（status 仍 active_v2）
    for cid, doc in docs.items():
        assert doc["status"] == "active_v2", cid


# ── ④ 四向键真树解析 + 审计（含断链注入负例）────────────────────────────────


@_need_real
def test_real_matrix_four_way_keys_resolve():
    from rfauto.core.calculators import CALCULATOR_REGISTRY

    calc = set(CALCULATOR_REGISTRY.names(include_experimental=True))
    anchors_doc = yaml.safe_load(
        (_REPO_ROOT / "knowledge" / "anchors.yaml").read_text(encoding="utf-8"))
    anchor_ids = {a["anchor_id"] for a in anchors_doc["anchors"]}
    mtx = yaml.safe_load(TRACE_PATH.read_text(encoding="utf-8"))
    assert mtx["schema"] == "trace-matrix/v1"
    assert mtx["ratchet"]["gate_min_pct"] >= FIRST_BATCH_FLOORS["gate_min_pct"]
    assert mtx["ratchet"]["param_min_pct"] >= FIRST_BATCH_FLOORS["param_min_pct"]
    n_links = 0
    for lk in mtx["links"]:
        assert set(lk) == {"gate_id", "param_key", "test_id", "anchor_id",
                           "strength"}
        assert lk["strength"] == "mechanical"  # 机械迁移不冒充 declared
        assert lk["gate_id"].count("#") == 1
        if lk["param_key"] is not None:
            assert lk["param_key"] in calc, lk
        if lk["anchor_id"] is not None:
            assert lk["anchor_id"] in anchor_ids, lk
        if lk["test_id"] is not None:
            assert (_REPO_ROOT / lk["test_id"]).is_file(), lk
        n_links += 1
    assert n_links > 0
    assert mtx["source"]["n_gate_rows"] == 368  # 登记面（50 文件/368 门行）稳定
    assert mtx["source"]["n_files"] == 50


@_need_real
def test_real_audit_status_pass_zero_dangling():
    from rfauto.core.calculators import CALCULATOR_REGISTRY

    calc = list(CALCULATOR_REGISTRY.names(include_experimental=True))
    anchors_doc = yaml.safe_load(
        (_REPO_ROOT / "knowledge" / "anchors.yaml").read_text(encoding="utf-8"))
    anchor_ids = [a["anchor_id"] for a in anchors_doc["anchors"]]
    index_doc = yaml.safe_load(INDEX_PATH.read_text(encoding="utf-8"))
    mtx = yaml.safe_load(TRACE_PATH.read_text(encoding="utf-8"))
    audit = check_numbers.trace_audit(
        mtx, index_doc, calc, anchor_ids,
        check_numbers.read_tests_cache(TESTS_CACHE))
    assert audit["status"] == "PASS"
    assert audit["dangling"] == []
    assert audit["coverage_pct"] >= FIRST_BATCH_FLOORS["gate_min_pct"]
    assert audit["by_dim"]["param"]["pct"] >= FIRST_BATCH_FLOORS["param_min_pct"]
    assert audit["universe"]["n_gates"] == 368


def _synthetic_world():
    index_doc = {"entries": [
        {"path": "cpw_gate/criteria.md", "status": "migrate_to_v2",
         "n_gates": 3, "gates": []},
        {"path": "prose/criteria.md", "status": "legacy_only",
         "n_gates": 0, "gates": []},
    ]}
    matrix = {"schema": "trace-matrix/v1",
              "ratchet": {"gate_min_pct": 80.0, "param_min_pct": 60.0},
              "links": [
                  {"gate_id": "cpw_gate#1", "param_key": "cpw_synthesis",
                   "test_id": "tests/unit/test_cpw_template.py",
                   "anchor_id": "cpw.k.cpw-v1", "strength": "mechanical"},
                  {"gate_id": "cpw_gate#2", "param_key": None,
                   "test_id": "tests/unit/test_cpw_template.py",
                   "anchor_id": None, "strength": "mechanical"},
                  {"gate_id": "cpw_gate#3", "param_key": "cpw_synthesis",
                   "test_id": "tests/unit/test_cpw_template.py",
                   "anchor_id": "cpw.k.cpw-v1", "strength": "mechanical"},
              ]}
    return index_doc, matrix


def test_trace_audit_coverage_math_and_pass():
    index_doc, matrix = _synthetic_world()
    audit = check_numbers.trace_audit(
        matrix, index_doc, ["cpw_synthesis"],
        ["cpw.k.cpw-v1"], ["tests/unit/test_cpw_template.py"])
    assert audit["status"] == "PASS"
    assert audit["coverage_pct"] == 100.0  # 3/3 门有 link
    assert audit["by_dim"]["gate"]["n"] == 3
    assert audit["by_dim"]["param"]["n"] == 2  # #2 param=None 不计 param 覆盖
    assert audit["by_dim"]["param"]["pct"] == round(200.0 / 3, 2)  # 66.67≥60
    assert audit["by_dim"]["anchor"]["n"] == 2
    assert audit["by_dim"]["test"]["pct"] == 100.0
    assert audit["dangling"] == []


def test_trace_audit_dangling_injection_negative():
    """断链注入负例：任一键指向域外 → status FAIL + 编辑距离 top-3 建议。"""
    index_doc, matrix = _synthetic_world()
    bad = [
        {"gate_id": "cpw_gate#1", "param_key": "cpw_syntheis",  # typo
         "test_id": "tests/unit/test_cpw_template.py",
         "anchor_id": "cpw.k.cpw-v1", "strength": "mechanical"},
    ]
    matrix["links"] = bad
    audit = check_numbers.trace_audit(
        matrix, index_doc, ["cpw_synthesis"], ["cpw.k.cpw-v1"],
        ["tests/unit/test_cpw_template.py"])
    assert audit["status"] == "FAIL"
    fields = {d["field"] for d in audit["dangling"]}
    assert "param_key" in fields
    sug = next(d["suggestions"] for d in audit["dangling"]
               if d["field"] == "param_key")
    assert sug[:1] == ["cpw_synthesis"]  # 编辑距离 top-3 首位即正主

    # 死 test（改名/删除）与死锚、死门各注入一发，全数抓获
    matrix["links"] = [
        {"gate_id": "cpw_gate#1", "param_key": "cpw_synthesis",
         "test_id": "tests/unit/test_gone.py", "anchor_id": None,
         "strength": "mechanical"}]
    audit = check_numbers.trace_audit(
        matrix, index_doc, ["cpw_synthesis"], ["cpw.k.cpw-v1"],
        ["tests/unit/test_cpw_template.py"])
    assert {d["field"] for d in audit["dangling"]} == {"test_id"}
    assert audit["status"] == "FAIL"

    matrix["links"] = [
        {"gate_id": "cpw_gates#9", "param_key": None, "test_id": None,
         "anchor_id": "no.such.anchor-v9", "strength": "mechanical"}]
    audit = check_numbers.trace_audit(
        matrix, index_doc, ["cpw_synthesis"], ["cpw.k.cpw-v1"], [])
    fields = {d["field"] for d in audit["dangling"]}
    assert fields == {"gate_id", "anchor_id"}
    # 死门名与真门名编辑距离近 → top-3 建议必含同族真门（远名建议可空，如实）
    gate_sug = next(d["suggestions"] for d in audit["dangling"]
                    if d["field"] == "gate_id")
    assert gate_sug and gate_sug[0].startswith("cpw_gate#")
    anchor_sug = next(d["suggestions"] for d in audit["dangling"]
                      if d["field"] == "anchor_id")
    assert isinstance(anchor_sug, list)
    assert audit["status"] == "FAIL"


def test_ratchet_only_rises():
    index_doc, matrix = _synthetic_world()
    audit = check_numbers.trace_audit(
        matrix, index_doc, ["cpw_synthesis"], ["cpw.k.cpw-v1"],
        ["tests/unit/test_cpw_template.py"])
    new_matrix, notes = check_numbers.update_ratchet(matrix, audit)
    assert new_matrix["ratchet"]["gate_min_pct"] == 100.0  # 只升
    assert any("100.0" in n for n in notes)
    # 覆盖回退时棘轮不降（守住首批 floor 语义）
    audit_low = dict(audit)
    audit_low["coverage_pct"] = 10.0
    audit_low["by_dim"] = dict(audit["by_dim"])
    audit_low["by_dim"]["param"] = {"n": 0, "pct": 0.0}
    m3, _notes3 = check_numbers.update_ratchet(new_matrix, audit_low)
    assert m3["ratchet"]["gate_min_pct"] == 100.0  # 不降
    assert m3["ratchet"]["param_min_pct"] == 66.67  # 保持首轮上抬值，不降


# ── ⑤ check_numbers trace CLI（缺失面 fail-closed + 子命令接线）─────────────


def test_trace_cmd_missing_matrix_returns_2(tmp_path, capsys):
    ns = argparse.Namespace(matrix=tmp_path / "nope.yaml",
                            index=INDEX_PATH if INDEX_PATH.is_file()
                            else tmp_path / "nope2.yaml",
                            anchors=_REPO_ROOT / "knowledge" / "anchors.yaml",
                            tests_cache=tmp_path / "nope3.txt",
                            json=False, update_ratchet=False)
    rc = check_numbers.cmd_trace(ns)
    assert rc == 2
    assert "trace matrix 缺失" in capsys.readouterr().out


@pytest.mark.skipif(not (INDEX_PATH.is_file() and TRACE_PATH.is_file()
                         and TESTS_CACHE.is_file()),
                    reason="真树 EP-2 产物不在（干净检出）")
def test_trace_cmd_end_to_end(tmp_path, capsys):
    """trace 子命令端到端：rc=0 + 摘要行；--update-ratchet 落盘不降棘轮。"""
    ns = argparse.Namespace(matrix=TRACE_PATH, index=INDEX_PATH,
                            anchors=_REPO_ROOT / "knowledge" / "anchors.yaml",
                            tests_cache=TESTS_CACHE, json=True,
                            update_ratchet=True)
    rc = check_numbers.cmd_trace(ns)
    out = capsys.readouterr().out
    assert rc == 0
    import json

    payload = json.loads(out[out.index("{"):])
    assert payload["status"] == "PASS"
    # 棘轮落盘后逐位不降（只升不降回归钉）
    mtx = yaml.safe_load(TRACE_PATH.read_text(encoding="utf-8"))
    assert mtx["ratchet"]["gate_min_pct"] >= FIRST_BATCH_FLOORS["gate_min_pct"]
    assert mtx["ratchet"]["param_min_pct"] >= FIRST_BATCH_FLOORS["param_min_pct"]


def test_criteria_id_of_and_gate_universe():
    assert criteria_id_of("a/b/criteria.md") == "a_b"
    assert criteria_id_of("cps_xrefine/x1_repro/criteria.md") == \
        "cps_xrefine_x1_repro"
    assert criteria_id_of("criteria.md") == "criteria"
    index_doc = {"entries": [
        {"path": "a/criteria.md", "status": "migrate_to_v2", "n_gates": 2},
        {"path": "b/criteria.md", "status": "legacy_only", "n_gates": 0},
    ]}
    universe = check_numbers.trace_gate_universe(index_doc)
    assert set(universe) == {"a#1", "a#2"}  # legacy_only 不进门全集
