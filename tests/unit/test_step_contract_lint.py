"""XD-6 step 契约 lint（scripts/step_contract_lint.py，aurora_m W4-2 席圈定件）。

钉面（池件裁定 runs/aurora_m/w4_2/xd_pool_verdict.md）：
① 禁③外部路径静态扫：盘符/UNC/POSIX 根/~ 形态命中 + URL/数值误报守卫；
② 禁①输入哈希前后对拍：清单稳定 + --baseline 四态差分
   （mutated/removed/added；#317 配方污染、#276 网表死绝对路径同族）；
③ 禁④缺 seed 随机性报警：随机源无钉 → 报警级（不进退出码）；
④ 退出码三态（0 clean/1 违例/2 程序性错误，XD-9 audit-stale 同款）；
⑤ 零时间戳确定性：同输入重跑 report 逐字节一致（XD-16 教训，
   --baseline 对拍可靠性前提）。
载体纪律钉：脚本只读、零 src 接线（W6-S29 放弃理由"污染守卫敏感面"
不成立化——不触 agent_sandbox promote 门）。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_SCRIPT = REPO / "scripts" / "step_contract_lint.py"

_SPEC = importlib.util.spec_from_file_location("step_contract_lint_test_target",
                                               _SCRIPT)
scl = importlib.util.module_from_spec(_SPEC)
sys.modules["step_contract_lint_test_target"] = scl
_SPEC.loader.exec_module(scl)


# ── 禁③：外部路径静态扫 ─────────────────────────────────────────────────

def test_drive_letter_detected():
    text = "notes: '校准基准取自 E:\\rfauto-workspace\\runs\\x.csv'"
    kinds = [f["kind"] for f in scl.scan_external_paths(text)]
    assert "drive_letter" in kinds


def test_unc_and_posix_and_home_detected():
    unc = "file=\\\\sim_server\\share\\netlist.ssp"
    posix = "ref: /home/user/calib.json"
    home = "out: ~/results/x.csv"
    assert "unc" in [f["kind"] for f in scl.scan_external_paths(unc)]
    assert "posix_root" in [f["kind"] for f in scl.scan_external_paths(posix)]
    assert "home_expand" in [f["kind"] for f in scl.scan_external_paths(home)]


def test_url_and_ratio_not_flagged():
    """URL 误报守卫 + 数值冒号不命中（https:// 与 12:30 形态）。"""
    text = ("docs: https://github.com/geer1895/rfauto and http://x.org/home\n"
            "time: 12:30, ratio 50:1\n")
    assert scl.scan_external_paths(text) == []


def test_external_path_finding_has_location():
    text = "a: 1\nb: E:\\tmp\\x.csv\n"
    fs = scl.scan_external_paths(text)
    assert len(fs) == 1 and fs[0]["line"] == 2 and fs[0]["col"] == 4


# ── 禁①：输入哈希前后对拍 ───────────────────────────────────────────────

def _mk(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_manifest_stable_and_lint_pass(tmp_path):
    p = _mk(tmp_path, "clean.yaml", "model: patch\ndefault_rng(42)\n")
    r1 = scl.lint_paths([p])
    r2 = scl.lint_paths([p])
    assert r1["verdict"] == "PASS" and r1["findings"] == []
    assert r1["digests"][str(p)]["sha256"] == scl.sha256_file(p)
    assert r1 == r2  # 同输入重跑逐字节同构（零时间戳）


def test_baseline_detects_mutation(tmp_path):
    p = _mk(tmp_path, "r.yaml", "seed: 42\n")
    base = scl.lint_paths([p])
    p.write_text("seed: 43\n", encoding="utf-8")
    cur = scl.lint_paths([p], baseline=base)
    rules = [f["rule"] for f in cur["findings"]]
    assert "input_mutated" in rules and cur["verdict"] == "FAIL"


def test_baseline_detects_added_and_removed(tmp_path):
    a = _mk(tmp_path, "a.yaml", "a: 1\n")
    b = _mk(tmp_path, "b.yaml", "b: 2\n")
    base = scl.lint_paths([a, b])
    c = _mk(tmp_path, "c.yaml", "c: 3\n")
    cur = scl.lint_paths([a, c], baseline=base)
    rules = sorted(f["rule"] for f in cur["findings"])
    assert rules == ["input_added", "input_removed"]


def test_lint_fail_on_external_path_in_file(tmp_path):
    p = _mk(tmp_path, "recipe.yaml", "notes: 'C:\\Users\\<local-user>\\x.csv'\n")
    r = scl.lint_paths([p])
    assert r["verdict"] == "FAIL"
    assert r["findings"][0]["rule"] == "external_path"


# ── 禁④：缺 seed 随机性报警（报警级，不进退出码）────────────────────────

def test_randomness_without_seed_warns(tmp_path):
    p = _mk(tmp_path, "gen.py", "import numpy as np\nx = np.random.uniform(0, 1)\n")
    r = scl.lint_paths([p])
    assert r["findings"] == [] and r["verdict"] == "PASS"
    assert len(r["warnings"]) == 1
    assert r["warnings"][0]["rule"] == "randomness_no_seed"


def test_randomness_with_seed_pin_no_warning(tmp_path):
    p = _mk(tmp_path, "gen2.py",
            "seed = 1234\nrng = np.random.default_rng(seed)\n")
    r = scl.lint_paths([p])
    assert r["warnings"] == []


# ── main/退出码三态 ──────────────────────────────────────────────────────

def test_main_exit_codes(tmp_path, capsys):
    clean = _mk(tmp_path, "ok.yaml", "model: patch\n")
    assert scl.main([str(clean)]) == 0
    bad = _mk(tmp_path, "bad.yaml", "x: E:\\y.csv\n")
    assert scl.main([str(bad)]) == 1
    assert scl.main([str(tmp_path / "ghost.yaml")]) == 2
    err = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert err["ok"] is False and "不存在" in err["error"]


def test_main_json_and_baseline_roundtrip(tmp_path, capsys):
    p = _mk(tmp_path, "r.yaml", "a: 1\n")
    assert scl.main([str(p), "--json"]) == 0
    out = capsys.readouterr().out
    doc = json.loads(out)
    assert doc["schema"] == scl.SCHEMA and doc["verdict"] == "PASS"
    base = tmp_path / "base.json"
    base.write_text(out, encoding="utf-8")
    # 同态复跑对拍=PASS（对拍可靠性）
    assert scl.main([str(p), "--json", "--baseline", str(base)]) == 0
    # 基线 schema 不符=程序性错误 exit 2
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "other"}), encoding="utf-8")
    assert scl.main([str(p), "--baseline", str(bad)]) == 2


def test_main_non_json_summary(tmp_path, capsys):
    bad = _mk(tmp_path, "b.yaml", "p: /home/u/x.json\n")
    assert scl.main([str(bad)]) == 1
    out = capsys.readouterr().out
    assert "VIOLATION" in out and "external_path" in out
    assert "step_contract_lint: FAIL" in out
