"""aurora_m W1-8：tier 分层接线钉（marker 施加 / 诚实降级 / 名单生成器确定性）。

钉面（验收硬门槛对应）：
1. committed 名单形态与计数自洽（tier_b/tier_c 名单==头部 count）；
2. 干净环境降级：名单文件缺席 → (∅,∅)=不加标记=全量语义（不 skip 不报错，
   行为==终门口径）；
3. pyproject marker 注册（-m "not tier_c" 在 strict 场景与干净环境均可用）；
4. 生成器确定性（同输入逐字节一致）+ 冻结件现树重判语义（合成输入端到端）；
5. gate_daily 过滤矩阵（tier × 串并行的 -m 参数纯函数）+ #355 日志名守卫。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import tomllib

from tests import conftest as conftest_mod

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TIERS_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "test_tiers.yaml"


class _FakeItem:
    """鸭子类型收集项（conftest.apply_tier_markers 只需 nodeid+add_marker）。"""

    def __init__(self, nodeid: str):
        self.nodeid = nodeid
        self.marker_names: list[str] = []

    def add_marker(self, marker) -> None:
        self.marker_names.append(marker.name)


def _load_script(tag: str, name: str):
    spec = importlib.util.spec_from_file_location(
        tag, REPO_ROOT / "scripts" / name)
    mod = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[tag] = mod
    spec.loader.exec_module(mod)
    return mod


# ── 1. committed 名单形态 ────────────────────────────────────────────────────


def test_tiers_fixture_present_and_counts_consistent():
    import yaml

    data = yaml.safe_load(TIERS_FIXTURE.read_text(encoding="utf-8"))
    assert data["schema_version"] == "aurora_m_test_tiers_v1"
    tier_b = data["tier_b"]["nodeids"]
    tier_c = data["tier_c"]["nodeids"]
    assert data["tier_b"]["count"] == len(tier_b)
    assert data["tier_c"]["count"] == len(tier_c)
    # 名单互斥：同一条目不得同时挂 B 与 C
    assert not (set(tier_b) & set(tier_c))
    # 名单排序（确定性再生可比对）
    assert tier_b == sorted(tier_b)
    assert tier_c == sorted(tier_c)
    # 冻结件重判证据在档：pool_patrol 冠军裁定保 B（任务书口径）
    overrides = data["frozen_retier"]["ruling_overrides"]
    assert {o["nodeid"] for o in overrides} == {
        "tests/unit/test_pool_patrol.py::TestGoldCalibrationRealRepo"
        "::test_default_gold_rate_is_one",
        "tests/unit/test_pool_patrol.py::TestCliPoolPatrol"
        "::test_human_output_smoke",
    }
    # 边界复核清单在档（4.5-5.5s 带）
    band = data["params"]["boundary_review_band_s"]
    for row in data["boundary_review"]:
        assert band[0] <= row["duration_s"] <= band[1]


def test_load_tier_sets_from_committed_fixture():
    tier_b, tier_c = conftest_mod.load_tier_sets()
    assert tier_b and tier_c
    assert len(tier_b) > len(tier_c)  # B（1-5s）多于 C（>=5s）的画像事实


# ── 2. 干净环境诚实降级（文件缺席=全量语义）───────────────────────────────


def test_missing_tiers_file_degrades_to_full_semantics(tmp_path):
    absent = tmp_path / "test_tiers_absent.yaml"
    assert conftest_mod.load_tier_sets(absent) == (set(), set())
    items = [_FakeItem("tests/unit/test_x.py::test_a"),
             _FakeItem("tests/unit/test_x.py::test_b")]
    n_b, n_c = conftest_mod.apply_tier_markers(items, path=absent)
    assert (n_b, n_c) == (0, 0)
    assert all(not it.marker_names for it in items)  # 无标记=全量语义


def test_corrupt_tiers_file_degrades_without_error(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("tier_b: [unclosed", encoding="utf-8")
    assert conftest_mod.load_tier_sets(bad) == (set(), set())


# ── 3. marker 施加与注册 ────────────────────────────────────────────────────


def test_apply_tier_markers_marks_b_and_c_only(tmp_path):
    import yaml

    data = yaml.safe_load(TIERS_FIXTURE.read_text(encoding="utf-8"))
    b_node = data["tier_b"]["nodeids"][0]
    c_node = data["tier_c"]["nodeids"][0]
    a_node = "tests/unit/test_not_in_any_list.py::test_default_a"
    items = [_FakeItem(b_node), _FakeItem(c_node), _FakeItem(a_node)]
    n_b, n_c = conftest_mod.apply_tier_markers(items, path=TIERS_FIXTURE)
    assert (n_b, n_c) == (1, 1)
    assert items[0].marker_names == ["tier_b"]
    assert items[1].marker_names == ["tier_c"]
    assert items[2].marker_names == []  # A 层不加标记=缺省


def test_tier_markers_registered_in_pyproject():
    with open(REPO_ROOT / "pyproject.toml", "rb") as f:
        cfg = tomllib.load(f)
    markers = cfg["tool"]["pytest"]["ini_options"]["markers"]
    names = {m.split(":", 1)[0].strip() for m in markers}
    assert {"tier_a", "tier_b", "tier_c"} <= names
    # 既有 marker 未被拆（零扰）
    assert {"real_edt", "solo", "slow"} <= names


def test_summary_parse_matches_v2_semantics():
    """gate_daily._parse_summary 与 v2 门判据同款（failed-only/error-only 非零）。"""
    gate = _load_script("_tt_gate_daily", "gate_daily.py")
    assert gate._parse_summary("28583 passed, 115 deselected in 900.10s") == (
        28583, 0, 0)
    assert gate._parse_summary("3 failed, 100 passed in 5.00s") == (100, 3, 0)
    assert gate._parse_summary("2 errors in 0.30s") == (0, 2, 0)  # 全败形态
    assert gate._parse_summary("1 failed in 0.71s") == (0, 1, 0)
    assert gate._parse_summary("nothing here") == (0, 0, 0)


# ── 4. 生成器：确定性 + 冻结件重判（合成输入端到端）─────────────────────────


def _write_synthetic_inputs(tmp_path: Path) -> tuple[Path, Path]:
    """合成 manifest（快扫行形态）+ 合成重测 junitxml（三冻结条目 + 常规条目）。"""
    manifest = tmp_path / "manifest.yaml"
    entries = [
        # 冻结件三件：288.259→12.454（裁定保 B）/ 9.597→3.963（机械 B）/
        # 12.885→0.397（机械 A）
        ("tests/unit/test_pool_patrol.py::TestGold::test_champion",
         "tests/unit/test_pool_patrol.py", 288.259, "C"),
        ("tests/unit/test_league_service.py::TestRealRuns::test_report",
         "tests/unit/test_league_service.py", 9.597, "C"),
        ("tests/unit/test_criteria_index_build.py::test_scan",
         "tests/unit/test_criteria_index_build.py", 12.885, "C"),
        # 非冻结件：边界带 4.8（B，落 boundary_review）/ 常规 C / 常规 A
        ("tests/unit/test_boundary.py::test_mid",
         "tests/unit/test_boundary.py", 4.8, "B"),
        ("tests/unit/test_heavy.py::test_c30",
         "tests/unit/test_heavy.py", 30.0, "C"),
        ("tests/unit/test_fast.py::test_a",
         "tests/unit/test_fast.py", 0.001, "A"),
    ]
    lines = [
        "schema_version: aurora_m_durations_manifest_v2",
        "generated_at: '2026-10-27T00:00:00+08:00'",
        "summary:",
        "  total_tests: 6",
        "entries:",
    ]
    for nodeid, file, dur, tier in sorted(entries):
        lines.append(
            f"  {nodeid}: {{file: {file}, duration_s: {dur}, tier: {tier}, "
            "status: passed}")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")

    remeasure = tmp_path / "remeasure_frozen.xml"
    remeasure.write_text(
        '<?xml version="1.0" encoding="utf-8"?><testsuites name="pytest tests">'
        '<testsuite name="pytest" tests="3">'
        '<testcase classname="tests.unit.test_pool_patrol.TestGold" '
        'name="test_champion" time="12.454" />'
        '<testcase classname="tests.unit.test_league_service.TestRealRuns" '
        'name="test_report" time="3.963" />'
        '<testcase classname="tests.unit.test_criteria_index_build" '
        'name="test_scan" time="0.397" />'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    return manifest, remeasure


def test_generator_deterministic_and_frozen_rejudged(tmp_path):
    gtm = _load_script("_tt_generate_tier_marks", "generate_tier_marks.py")
    manifest, remeasure = _write_synthetic_inputs(tmp_path)
    out1 = tmp_path / "tiers1.yaml"
    out2 = tmp_path / "tiers2.yaml"
    rc1 = gtm.main(["--manifest", str(manifest), "--remeasure", str(remeasure),
                    "--out", str(out1)])
    rc2 = gtm.main(["--manifest", str(manifest), "--remeasure", str(remeasure),
                    "--out", str(out2)])
    assert rc1 == rc2 == 0
    # 同输入两次输出逐字节一致（durations manifest 同律）
    assert out1.read_bytes() == out2.read_bytes()

    import yaml

    data = yaml.safe_load(out1.read_text(encoding="utf-8"))
    tiers = {}
    for nid in data["tier_b"]["nodeids"]:
        tiers[nid] = "B"
    for nid in data["tier_c"]["nodeids"]:
        tiers[nid] = "C"
    # 冠军 12.454s：机械规则应落 C，任务书裁定保 B
    assert tiers["tests/unit/test_pool_patrol.py::TestGold::test_champion"] == "B"
    # league 3.963s：机械规则落 [1,5) B
    assert tiers["tests/unit/test_league_service.py::TestRealRuns::test_report"] == "B"
    # criteria 0.397s：重测后 <1s 落 A（不在名单）
    assert "tests/unit/test_criteria_index_build.py::test_scan" not in tiers
    # 非冻结件按 manifest 口径直读
    assert tiers["tests/unit/test_heavy.py::test_c30"] == "C"
    assert "tests/unit/test_fast.py::test_a" not in tiers
    # 边界带复核清单含 4.8s 条目、不含 30s/12.454s
    review_ids = {r["nodeid"] for r in data["boundary_review"]}
    assert "tests/unit/test_boundary.py::test_mid" in review_ids
    assert "tests/unit/test_heavy.py::test_c30" not in review_ids
    # 裁定证据逐条落账
    overrides = {o["nodeid"]: o for o in data["frozen_retier"]["ruling_overrides"]}
    assert overrides["tests/unit/test_pool_patrol.py::TestGold::test_champion"][
        "remeasured_s"] == 12.454


def test_generator_remeasure_coverage_gap_recorded(tmp_path):
    """重测 xml 未覆盖的冻结文件条目保 manifest 口径且缺口落账（不静默）。"""
    gtm = _load_script("_tt_generate_tier_marks_gap", "generate_tier_marks.py")
    manifest, remeasure = _write_synthetic_inputs(tmp_path)
    # 追加一条冻结文件内、但重测 xml 未覆盖的条目
    text = manifest.read_text(encoding="utf-8")
    text = text.replace("summary:\n  total_tests: 6",
                        "summary:\n  total_tests: 7")
    text += (
        "  tests/unit/test_pool_patrol.py::TestNew::test_added:"
        " {file: tests/unit/test_pool_patrol.py, duration_s: 20.0, tier: C,"
        " status: passed}\n"
    )
    manifest.write_text(text, encoding="utf-8")
    out = tmp_path / "tiers_gap.yaml"
    assert gtm.main(["--manifest", str(manifest), "--remeasure",
                     str(remeasure), "--out", str(out)]) == 0
    import yaml

    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["frozen_retier"]["coverage_gaps"], "缺口必须落账不静默"
    assert data["frozen_retier"]["coverage_gaps"][0].startswith(
        "tests/unit/test_pool_patrol.py::TestNew::test_added")
    # 缺口条目保 manifest 口径（C）
    assert ("tests/unit/test_pool_patrol.py::TestNew::test_added"
            in data["tier_c"]["nodeids"])


# ── 5. gate_daily 过滤矩阵与 #355 日志名守卫 ────────────────────────────────


def test_gate_daily_marker_filter_matrix():
    gate = _load_script("_tt_gate_daily_matrix", "gate_daily.py")
    # 缺省 ab 并行：tier 过滤 + solo deselect（xdist 假红防护）
    assert gate.build_marker_args("ab", serial=False) == [
        "-m", "not tier_c and not solo"]
    # ab 串行：只 tier 过滤（solo 串行下合法）
    assert gate.build_marker_args("ab", serial=True) == ["-m", "not tier_c"]
    # a 档：B 也排除（W2-3 合流门预留口径）
    assert gate.build_marker_args("a", serial=True) == [
        "-m", "not tier_c and not tier_b"]
    # all：无 tier 过滤（终门口径自证）；并行仍保 solo deselect
    assert gate.build_marker_args("all", serial=True) == []
    assert gate.build_marker_args("all", serial=False) == ["-m", "not solo"]


def test_gate_daily_log_name_guards_355_glob(tmp_path):
    gate = _load_script("_tt_gate_daily_log", "gate_daily.py")
    gate.RUNS = tmp_path
    gate.GATE_PARTS = tmp_path / "gate_parts"
    gate.GATE_LOGS = tmp_path / "gate_logs"
    # 缺省命名：gate_daily_<ts>.log 不含 full（#355 门口径 glob 零命中）
    p = gate.resolve_log_path(None, "20261028_120000")
    assert p == tmp_path / "gate_daily_20261028_120000.log"
    assert "full" not in p.name
    # --seg-log：落 gate_parts 子目录（Path.glob 非递归，顶层零命中）
    p2 = gate.resolve_log_path("w1_8_daily_serial", "20261028_120001")
    assert p2 == tmp_path / "gate_parts" / "w1_8_daily_serial.log"
    # 含 full 的名字拒绝发射
    with pytest.raises(SystemExit):
        gate.resolve_log_path("gate_full_daily", "20261028_120002")
    with pytest.raises(SystemExit):
        gate.resolve_log_path("innocent-FULL-name", "20261028_120003")


def test_tier_counts_applied_parse_and_deselected_semantics(tmp_path):
    """主代理收编补钉：段进程 JSONL 计数聚合 + 三档 deselect 语义 + 缺文件
    回退 None（conftest RFAUTO_TIER_COUNTS_OUT env 门观测，#105）。"""
    gate = _load_script("_tt_gate_counts", "gate_daily.py")
    cp = tmp_path / "counts.jsonl"
    assert gate._deselected_for("ab", cp) is None  # 缺文件=回退终端解析
    cp.write_text(
        '{"applied_b": 10, "applied_c": 3, "n_items": 100, "pid": 1}\n'
        '{"applied_b": 4, "applied_c": 2, "n_items": 90, "pid": 2}\n',
        encoding="utf-8")
    assert gate._tier_counts_applied(cp) == (14, 5)
    assert gate._deselected_for("ab", cp) == 5
    assert gate._deselected_for("a", cp) == 19
    assert gate._deselected_for("all", cp) == 0
    cp.write_text("not json\n", encoding="utf-8")
    assert gate._deselected_for("ab", cp) is None  # 坏行=回退不假数
