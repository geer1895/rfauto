"""aurora_m W1-7 席：时长棘轮门测试（单测时长预算只紧不松，PLAN W1-7）。

覆盖面
------
- TestRealTree：真树正例门（self_audit 模式全绿）+ 棘轮核心运行时上界钉。
- TestScanner：manifest 快扫（简单键/显式键双形态、完整性 fail-loud）。
- TestEnvStates：三态环境钉（双缺 skip / 预算缺红 / manifest 缺红与 skip 分界）。
- TestSelfAudit：sha 锚定自审（正例绿 + 手改预算只紧不松破坏红 + 覆盖缺登记红）。
- TestEnforce：执法模式负例（注入 30s 条目被拦点名 / 既有条目超预算 / 亚阈
  累积触发文件层 / schema 漂移红）——CI 内证明执法逻辑活的负例单测，
  不依赖真塞（真塞 30s 端到端见 runs/aurora_m/w1_7/ 证据档）。
- TestGenerator：生成器幂等（同 manifest 两跑逐字节一致）、只紧不松拦截、
  --accept-slower 审计落盘、--remeasure-junit 回填与封顶、新增测试豁免。

设计口径（预算覆盖面/噪声系数/三态语义/刷新工作流）见
scripts/check_duration_ratchet.py 与 scripts/generate_duration_budget.py
docstring——本文件只钉行为。棘轮测试自身为读文件比对级（模块实测 <2s，
红钱 2），核心单次 check 另设 5s 上界钉防 gross 回归（2s 为设计目标非
断言值——门内时钟抖动下硬钉 2s 会制造环境类假红）。

脚本经 importlib spec 装载（scripts 非包，test_check_numbers 同款口径）。
"""

from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
_MANIFEST = _REPO / "runs/aurora_m/durations_manifest.yaml"
_BUDGET = _REPO / "tests/fixtures/duration_budgets.yaml"


def _load_script(name: str, key: str):
    spec = importlib.util.spec_from_file_location(key, _REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ratchet = _load_script("check_duration_ratchet", "duration_ratchet_w1_7")
budget_gen = _load_script("generate_duration_budget", "duration_budget_gen_w1_7")

# 合成 manifest 基线（覆盖 A/B/C 三层 + 显式键形态条目 + 双文件）
BASE = [
    ("tests/unit/test_a.py::test_fast1", "tests/unit/test_a.py", 0.3, "A"),
    ("tests/unit/test_a.py::test_fast2", "tests/unit/test_a.py", 0.4, "A"),
    ("tests/unit/test_a.py::test_mid", "tests/unit/test_a.py", 1.2, "B"),
    ("tests/unit/test_b.py::test_slow", "tests/unit/test_b.py", 5.0, "C"),
    ("tests/unit/test_b.py::test_second", "tests/unit/test_b.py", 2.0, "B"),
    ("tests/unit/test_b.py::test_weird[a: b]", "tests/unit/test_b.py", 0.5, "A"),
]


def _write_manifest(path: Path, entries, gen_at="2026-10-27T00:00:00+08:00") -> Path:
    """按 build_durations_manifest 的产物形态写合成 manifest。

    nodeid 含 ": "（PyYAML plain 键非法序列）的条目按生成器实际输出写显式
    键形态（``? key`` / ``: {flow}``）——快扫器两形态都必须吃。
    """
    lines = [
        "schema_version: aurora_m_durations_manifest_v2",
        f"generated_at: '{gen_at}'",
        "generator: synthetic-for-test",
        "source_run:",
        "  name: synthetic",
        "  wall_min: 1.0",
        "  contention_note: synthetic",
        "summary:",
        f"  total_tests: {len(entries)}",
        "entries:",
    ]
    for nid, f, dur, tier in entries:
        flow = f"{{file: {f}, duration_s: {dur}, tier: {tier}, status: passed, flags: []}}"
        if ": " in nid:
            lines.append(f"  ? {nid}")
            lines.append(f"  : {flow}")
        else:
            lines.append(f"  {nid}: {flow}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _gen_budget(tmp_path: Path, entries=None, out="b.yaml", manifest="m.yaml", extra=()):
    m = _write_manifest(tmp_path / manifest, BASE if entries is None else entries)
    b = tmp_path / out
    rc = budget_gen.main(["--manifest", str(m), "--out", str(b), *extra])
    assert rc == 0
    return m, b


# ---------------------------------------------------------------------------
# 真树正例门 + 运行时上界
# ---------------------------------------------------------------------------


class TestRealTree:
    def test_positive_gate(self):
        """真树正例：manifest 与预算源 sha 一致 → self_audit 全绿。"""
        res = ratchet.check(_MANIFEST, _BUDGET)
        if res["status"] == "skip":
            pytest.skip("; ".join(res["notes"]))
        assert res["status"] == "ok", ratchet.render_result(res)
        assert res["mode"] == "self_audit"

    def test_core_runtime_bound(self):
        """棘轮核心单次 check 上界钉（5s 防 gross 回归；设计目标 <2s 见 docstring）。"""
        res = ratchet.check(_MANIFEST, _BUDGET)
        if res["status"] == "skip":
            pytest.skip("; ".join(res["notes"]))
        t0 = time.perf_counter()
        ratchet.check(_MANIFEST, _BUDGET)
        elapsed = time.perf_counter() - t0
        assert elapsed < 5.0, f"棘轮核心耗时 {elapsed:.2f}s（>5s=回归到重解析级）"


# ---------------------------------------------------------------------------
# manifest 快扫
# ---------------------------------------------------------------------------


class TestScanner:
    def test_simple_and_explicit_key_forms(self, tmp_path):
        m = _write_manifest(tmp_path / "m.yaml", BASE)
        doc = ratchet.scan_manifest(m)
        assert doc["total_tests"] == len(BASE)
        assert len(doc["entries"]) == len(BASE)
        nid = "tests/unit/test_b.py::test_weird[a: b]"
        assert doc["entries"][nid] == ("tests/unit/test_b.py", 0.5, "A")
        assert doc["entries"]["tests/unit/test_b.py::test_slow"] == (
            "tests/unit/test_b.py",
            5.0,
            "C",
        )
        assert doc["schema_version"] == ratchet.EXPECTED_MANIFEST_SCHEMA

    def test_count_mismatch_fails_loud(self, tmp_path):
        m = _write_manifest(tmp_path / "m.yaml", BASE)
        text = m.read_text(encoding="utf-8").replace(
            f"total_tests: {len(BASE)}", f"total_tests: {len(BASE) - 1}"
        )
        m.write_text(text, encoding="utf-8")
        with pytest.raises(ratchet.RatchetError, match="完整性违例"):
            ratchet.scan_manifest(m)

    def test_unparsable_entry_line_fails_loud(self, tmp_path):
        m = _write_manifest(tmp_path / "m.yaml", BASE)
        text = m.read_text(encoding="utf-8") + "  ??? 垃圾行\n"
        m.write_text(text, encoding="utf-8")
        with pytest.raises(ratchet.RatchetError, match="不可解析行"):
            ratchet.scan_manifest(m)


# ---------------------------------------------------------------------------
# 三态环境钉（红钱 3）
# ---------------------------------------------------------------------------


class TestEnvStates:
    def test_both_missing_no_evidence_root_skip(self, tmp_path):
        res = ratchet.check(tmp_path / "nope" / "m.yaml", tmp_path / "nope" / "b.yaml")
        assert res["status"] == "skip"
        assert res["violations"] == []

    def test_budget_missing_manifest_present_red(self, tmp_path):
        m = _write_manifest(tmp_path / "ev" / "m.yaml", BASE)
        res = ratchet.check(m, tmp_path / "ev" / "budget.yaml")
        assert res["status"] == "violation"
        assert res["violations"][0]["kind"] == "budget_missing"

    def test_budget_missing_evidence_root_present_red(self, tmp_path):
        (tmp_path / "ev").mkdir()
        res = ratchet.check(tmp_path / "ev" / "m.yaml", tmp_path / "ev" / "b.yaml")
        assert res["status"] == "violation"
        assert res["violations"][0]["kind"] == "budget_missing"

    def test_manifest_missing_evidence_root_present_red(self, tmp_path):
        (tmp_path / "ev").mkdir()
        (tmp_path / "b.yaml").write_text("schema_version: placeholder\n", encoding="utf-8")
        res = ratchet.check(tmp_path / "ev" / "m.yaml", tmp_path / "b.yaml")
        assert res["status"] == "violation"
        assert res["violations"][0]["kind"] == "manifest_missing"

    def test_manifest_missing_no_evidence_root_skip(self, tmp_path):
        (tmp_path / "b.yaml").write_text("schema_version: placeholder\n", encoding="utf-8")
        res = ratchet.check(tmp_path / "nope" / "m.yaml", tmp_path / "b.yaml")
        assert res["status"] == "skip"


# ---------------------------------------------------------------------------
# self_audit 模式（sha 锚定）
# ---------------------------------------------------------------------------


class TestSelfAudit:
    def test_baseline_green(self, tmp_path):
        m, b = _gen_budget(tmp_path)
        res = ratchet.check(m, b)
        assert res["status"] == "ok", ratchet.render_result(res)
        assert res["mode"] == "self_audit"

    def test_tampered_budget_value_red(self, tmp_path):
        """预算值被手改高于源实测 → 只紧不松破坏红（自审的防手改职责）。"""
        m, b = _gen_budget(tmp_path)
        doc = yaml.safe_load(b.read_text(encoding="utf-8"))
        doc["entries"]["tests/unit/test_a.py::test_mid"]["budget_s"] = 9.9
        b.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=True), encoding="utf-8")
        res = ratchet.check(m, b)
        kinds = [v["kind"] for v in res["violations"]]
        assert "tighten_violation" in kinds
        assert res["status"] == "violation"

    def test_dropped_budget_entry_red(self, tmp_path):
        """源 manifest ≥1s 条目未登记预算 → 覆盖完整性红。"""
        m, b = _gen_budget(tmp_path)
        doc = yaml.safe_load(b.read_text(encoding="utf-8"))
        del doc["entries"]["tests/unit/test_a.py::test_mid"]
        b.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=True), encoding="utf-8")
        res = ratchet.check(m, b)
        kinds = [v["kind"] for v in res["violations"]]
        assert "unbudgeted" in kinds

    def test_tampered_sub_threshold_fingerprint_red(self, tmp_path):
        """手改亚阈指纹（掩护漂移）→ 自审完整性红。"""
        m, b = _gen_budget(tmp_path)
        doc = yaml.safe_load(b.read_text(encoding="utf-8"))
        doc["file_budgets"]["tests/unit/test_a.py"]["sub_threshold_sha256"] = "0" * 64
        b.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=True), encoding="utf-8")
        res = ratchet.check(m, b)
        assert any(
            v["kind"] == "integrity" and "亚阈指纹" in v["detail"] for v in res["violations"]
        )


# ---------------------------------------------------------------------------
# enforce 模式负例（CI 内证明执法逻辑活——30s 注入不依赖真塞）
# ---------------------------------------------------------------------------


class TestEnforce:
    def test_injected_30s_test_caught_and_named(self, tmp_path):
        """负例单测（验收硬门槛的 CI 形态）：注入 30s 条目 → 棘轮红且点名。"""
        _m, b = _gen_budget(tmp_path)
        m2 = _write_manifest(
            tmp_path / "m2.yaml",
            [*BASE, ("tests/unit/test_evil.py::test_sleeps_30", "tests/unit/test_evil.py", 30.0, "C")],
        )
        res = ratchet.check(m2, b)
        assert res["status"] == "violation"
        assert res["mode"] == "enforce"
        kinds = {v["kind"] for v in res["violations"]}
        assert "unregistered" in kinds
        assert "file_unregistered" in kinds
        assert any("test_sleeps_30" in v["target"] for v in res["violations"])
        rendered = ratchet.render_result(res)
        assert "test_sleeps_30" in rendered and "30.000" in rendered

    def test_existing_entry_slowdown_exceeded(self, tmp_path):
        """既有预算条目超预算 ×1.5 → exceeded 红并列出实测/预算/超幅。"""
        _m, b = _gen_budget(tmp_path)
        entries = [
            (nid, f, 5.0 if nid.endswith("::test_mid") else d, t) for nid, f, d, t in BASE
        ]
        m2 = _write_manifest(tmp_path / "m2.yaml", entries)
        res = ratchet.check(m2, b)
        exceeded = [v for v in res["violations"] if v["kind"] == "exceeded"]
        assert [v["target"] for v in exceeded] == ["tests/unit/test_a.py::test_mid"]
        v = exceeded[0]
        assert v["actual_s"] == 5.0 and v["budget_s"] == 1.2  # 5.0 > 1.2×1.5=1.8
        # 文件层同样红：test_a 0.3+0.4+5.0=5.7 > 1.9×1.5=2.85 且超出 3.8>1.0
        assert any(v["kind"] == "file_exceeded" for v in res["violations"])

    def test_sub_threshold_accumulation_trips_file_layer(self, tmp_path):
        """亚阈条目各自微涨不触逐条线、累积触发文件层（双层执法的合成证据）。"""
        _m, b = _gen_budget(tmp_path)
        entries = [
            (nid, f, 0.9 if d in (0.3, 0.4) else d, t) for nid, f, d, t in BASE
        ]
        m2 = _write_manifest(tmp_path / "m2.yaml", entries)
        res = ratchet.check(m2, b)
        # test_a: 0.9+0.9+1.2=3.0 > 1.9×1.5=2.85 且超出 1.1>1.0；逐条均不越线
        assert [v["kind"] for v in res["violations"]] == ["file_exceeded"]
        assert res["violations"][0]["target"] == "tests/unit/test_a.py"

    def test_schema_drift_red(self, tmp_path):
        _m, b = _gen_budget(tmp_path)
        m2 = _write_manifest(tmp_path / "m2.yaml", BASE)
        text = m2.read_text(encoding="utf-8").replace(
            "aurora_m_durations_manifest_v2", "aurora_m_durations_manifest_v9"
        )
        m2.write_text(text, encoding="utf-8")
        res = ratchet.check(m2, b)
        assert res["status"] == "violation"
        assert res["violations"][0]["kind"] == "integrity"
        assert "schema" in res["violations"][0]["detail"]

    def test_remeasured_entry_uses_wider_factor(self, tmp_path):
        """重测条目执法系数 ×2.0（无争用上浮基线，防争用轮误报）。"""
        junit = tmp_path / "r.xml"
        junit.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n<testsuites><testsuite name="pytest" tests="1">'
            '<testcase classname="tests.unit.test_b" name="test_slow" time="3.3"/>'
            "</testsuite></testsuites>",
            encoding="utf-8",
        )
        _m, b = _gen_budget(tmp_path, extra=("--remeasure-junit", str(junit)))
        doc = yaml.safe_load(b.read_text(encoding="utf-8"))
        e = doc["entries"]["tests/unit/test_b.py::test_slow"]
        assert e["budget_s"] == 3.3 and e["remeasured"] is True and e["source_s"] == 5.0
        # 文件层静音：test_second 同步降至 1.0（m2 合计 8.0 < 预算合计 5.8×1.5=8.7）
        m2 = _write_manifest(
            tmp_path / "m2.yaml",
            [(nid, f, 6.5 if nid.endswith("::test_slow") else (1.0 if nid.endswith(
                "::test_second") else d), t) for nid, f, d, t in BASE],
        )
        res = ratchet.check(m2, b)
        assert res["status"] == "ok", ratchet.render_result(res)  # 6.5 ≤ 3.3×2.0=6.6
        m3 = _write_manifest(
            tmp_path / "m3.yaml",
            [(nid, f, 6.8 if nid.endswith("::test_slow") else (1.0 if nid.endswith(
                "::test_second") else d), t) for nid, f, d, t in BASE],
        )
        res = ratchet.check(m3, b)
        assert any(v["kind"] == "exceeded" for v in res["violations"])  # 6.8 > 6.6


# ---------------------------------------------------------------------------
# 生成器行为
# ---------------------------------------------------------------------------


class TestGenerator:
    def test_idempotent_two_runs_byte_identical(self, tmp_path):
        m = _write_manifest(tmp_path / "m.yaml", BASE)
        b = tmp_path / "b.yaml"
        assert budget_gen.main(["--manifest", str(m), "--out", str(b)]) == 0
        first = b.read_bytes()
        assert budget_gen.main(["--manifest", str(m), "--out", str(b)]) == 0
        assert b.read_bytes() == first

    def test_only_tighten_blocks_without_accept_slower(self, tmp_path, capsys):
        _m, b = _gen_budget(tmp_path)
        before = b.read_bytes()
        entries = [
            (nid, f, 2.5 if nid.endswith("::test_mid") else d, t) for nid, f, d, t in BASE
        ]
        m2 = _write_manifest(tmp_path / "m2.yaml", entries)
        rc = budget_gen.main(["--manifest", str(m2), "--out", str(b)])
        assert rc == 2
        assert b.read_bytes() == before  # 拒绝写盘
        err = capsys.readouterr().err
        assert "只紧不松拦截" in err and "test_mid" in err

    def test_accept_slower_records_reason_and_history(self, tmp_path):
        _m, b = _gen_budget(tmp_path)
        entries = [
            (nid, f, 2.5 if nid.endswith("::test_mid") else d, t) for nid, f, d, t in BASE
        ]
        m2 = _write_manifest(tmp_path / "m2.yaml", entries)
        rc = budget_gen.main(
            ["--manifest", str(m2), "--out", str(b),
             "--accept-slower", "轮间争用上调，已复核非语料回涨"]
        )
        assert rc == 0
        doc = yaml.safe_load(b.read_text(encoding="utf-8"))
        acc = doc["only_tighten"]["slower_acceptances"]
        assert len(acc) == 1
        assert acc[0]["reason"] == "轮间争用上调，已复核非语料回涨"
        # 预算条目回涨同时推高文件合计 → 文件层记录一并放行（逐条+文件双记录）
        acc_map = {e["target"]: e for e in acc[0]["entries"]}
        mid = acc_map["tests/unit/test_a.py::test_mid"]
        assert mid["old_s"] == 1.2 and mid["new_s"] == 2.5 and mid["kind"] == "test"
        assert acc_map["tests/unit/test_a.py"]["kind"] == "file"
        # 再一轮干净 manifest：预算被只紧不松拉回（2.5→1.2 自动接受）
        m3 = _write_manifest(tmp_path / "m3.yaml", BASE)
        assert budget_gen.main(["--manifest", str(m3), "--out", str(b)]) == 0
        doc = yaml.safe_load(b.read_text(encoding="utf-8"))
        assert doc["entries"]["tests/unit/test_a.py::test_mid"]["budget_s"] == 1.2
        # 审计历史保留
        assert len(doc["only_tighten"]["slower_acceptances"]) == 1

    def test_remeasure_caps_at_source(self, tmp_path):
        """重测值高于 manifest 源值时按源值封顶（上限只降不升）。"""
        m = _write_manifest(tmp_path / "m.yaml", BASE)
        junit = tmp_path / "r.xml"
        junit.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n<testsuites><testsuite name="pytest" tests="1">'
            '<testcase classname="tests.unit.test_b" name="test_slow" time="9.9"/>'
            "</testsuite></testsuites>",
            encoding="utf-8",
        )
        b = tmp_path / "b.yaml"
        assert budget_gen.main(
            ["--manifest", str(m), "--out", str(b), "--remeasure-junit", str(junit)]
        ) == 0
        doc = yaml.safe_load(b.read_text(encoding="utf-8"))
        e = doc["entries"]["tests/unit/test_b.py::test_slow"]
        assert e["budget_s"] == 5.0 and e["remeasured"] is True

    def test_new_test_addition_needs_no_accept_slower(self, tmp_path):
        """文件层新增豁免：新增测试登记不触发只紧不松拦截。"""
        _m, b = _gen_budget(tmp_path)
        m2 = _write_manifest(
            tmp_path / "m2.yaml",
            [*BASE, ("tests/unit/test_a.py::test_new", "tests/unit/test_a.py", 0.4, "A")],
        )
        assert budget_gen.main(["--manifest", str(m2), "--out", str(b)]) == 0
        doc = yaml.safe_load(b.read_text(encoding="utf-8"))
        # 新文件合计含新增条目（登记语义）
        assert doc["file_budgets"]["tests/unit/test_a.py"]["budget_total_s"] == 2.3

    def test_sub_threshold_drift_blocked_at_generation(self, tmp_path, capsys):
        """亚阈总体不变、既有亚阈条目漂移（0.3/0.4→0.9/0.9）→ 生成期文件层拦截。"""
        _m, b = _gen_budget(tmp_path)
        entries = [
            (nid, f, 0.9 if d in (0.3, 0.4) else d, t) for nid, f, d, t in BASE
        ]
        m2 = _write_manifest(tmp_path / "m2.yaml", entries)
        rc = budget_gen.main(["--manifest", str(m2), "--out", str(b)])
        assert rc == 2
        err = capsys.readouterr().err
        assert "[file]" in err and "tests/unit/test_a.py" in err

    def test_file_layer_blocked_by_budgeted_drift_within_jitter_each(self, tmp_path, capsys):
        """逐条各自在容差内微涨、文件基准合计越 0.05s 容差 → 文件层拦截。"""
        _m, b = _gen_budget(tmp_path)
        entries = [
            (nid, f, d + 0.04 if f.endswith("test_b.py") and d >= 1.0 else d, t)
            for nid, f, d, t in BASE
        ]
        m2 = _write_manifest(tmp_path / "m2.yaml", entries)
        rc = budget_gen.main(["--manifest", str(m2), "--out", str(b)])
        assert rc == 2
        err = capsys.readouterr().err
        assert "[file]" in err and "tests/unit/test_b.py" in err

    def test_main_input_error_rc3(self, tmp_path):
        rc = budget_gen.main(
            ["--manifest", str(tmp_path / "missing.yaml"), "--out", str(tmp_path / "b.yaml")]
        )
        assert rc == 3


# ---------------------------------------------------------------------------
# CLI 信封
# ---------------------------------------------------------------------------


class TestCli:
    def test_main_json_envelope_violation(self, tmp_path, capsys):
        m = _write_manifest(tmp_path / "ev" / "m.yaml", BASE)
        rc = ratchet.main(
            ["--manifest", str(m), "--budget", str(tmp_path / "ev" / "b.yaml"), "--json"]
        )
        assert rc == 1
        doc = json.loads(capsys.readouterr().out)
        assert doc["ok"] is False
        assert doc["violations"][0]["kind"] == "budget_missing"

    def test_main_rc0_on_skip(self, tmp_path, capsys):
        rc = ratchet.main(
            ["--manifest", str(tmp_path / "nope" / "m.yaml"),
             "--budget", str(tmp_path / "nope" / "b.yaml")]
        )
        assert rc == 0
        assert "skip" in capsys.readouterr().out
