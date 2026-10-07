"""XA-6 出处断链巡检门锚树（scripts/audit_provenance.py）。

规格：研究扩充 round18 XA-6。巡检对象=KD-1
注册表（knowledge/formula_provenance.yaml）。

锚树：
1. 确定性——同输入二跑报告 dict 逐字节相等（payload 零时间戳字段）；
2. 阈值边界——unverified_ratio == max 绿、> max 红（严格大于语义）；
   ratio_max<=0 参数拒收；
3. fail 三面——占比超限红；孤儿条目（kernel_file 磁盘缺失）红；
   stale id（注册表有/docstring 扫描无，origin=docstring）红；
4. 报告不阻断两面——uncollected（扫描有/注册表无，归属 collector --check）
   与 verified 条目 evidence 双缺抽检清单只进报告面，门保持绿；
5. manual_entries 人工补录区不参与 stale 判定（按定义不在 docstring 扫描面）；
6. CLI——绿 0 / 红 1 / 巡检不可执行（注册表缺失）2；--json 机读面可解析；
7. 真仓冒烟——真树巡检结构自洽 + 二跑逐字节一致 + 零孤儿 + 门绿。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "audit_provenance.py"
_SPEC = importlib.util.spec_from_file_location("audit_provenance_gate", _SCRIPT)
audit_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(audit_mod)

from rfauto.core.formula_provenance import (
    load_formula_provenance,
    render_formula_provenance_yaml,
    scan_formula_provenance,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]

# 三标记内核：verified+refs / unverified / verified 双缺 evidence（§ 锚但无
# 年份引文无 DOI）——词面经 _extract_access_status 真实管线判级，不造字段。
_KERNEL_THREE = '''"""演示内核。

出处（已核：Pozar, Microwave Engineering 4th ed., 2012 §1.1）：
    delta = sqrt(2 / (omega mu sigma))

出处（未核：某手册 §2.3，原文未读）：
    q = f0 / bw

出处（已核：Kerns 平面波谱口径 §2.3）：
    Gamma = (Z - Z0) / (Z + Z0)
"""
'''

# 两标记内核：verified + unverified 各一（占比恰 0.5，边界钉）。
_KERNEL_TWO = '''"""边界内核。

出处（已核：Collin, Foundations for Microwave Engineering, 2001 §3.2）：
    gamma = sqrt(j omega mu (sigma + j omega eps))

出处（未核：某 lecture notes，未获原文）：
    z_in = z0 (zl + j tan) / (z0 + j zl tan)
"""
'''


def _build_repo(tmp_path: Path, kernel_text: str,
                filename: str = "demo_kernel.py") -> Path:
    """tmp 仓：src/rfauto/core 单内核 + knowledge/formula_provenance.yaml
    （真收集管线产条目再渲染落盘——不手造 schema 字段）。"""
    core = tmp_path / "src" / "rfauto" / "core"
    core.mkdir(parents=True)
    (core / filename).write_text(kernel_text, encoding="utf-8")
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    entries = scan_formula_provenance(core, kernel_file_base=tmp_path)
    reg = knowledge / "formula_provenance.yaml"
    reg.write_text(render_formula_provenance_yaml(entries), encoding="utf-8")
    return reg


def _audit(tmp_path: Path, reg: Path, **kw):
    return audit_mod.audit_provenance(tmp_path, registry_path=reg, **kw)


# ── 1+2. 确定性与总量面（绿例）─────────────────────────────────────────────

def test_audit_structure_and_determinism(tmp_path: Path):
    reg = _build_repo(tmp_path, _KERNEL_THREE)
    r1 = _audit(tmp_path, reg, unverified_ratio_max=0.5)
    r2 = _audit(tmp_path, reg, unverified_ratio_max=0.5)
    assert r1 == r2  # 确定性：同输入二跑逐键相等
    t = r1["totals"]
    assert t["entries"] == 3 and t["manual_entries"] == 0
    assert t["docstring_entries"] == 3
    assert t["by_access"] == {"verified": 2, "unverified": 1, "null": 0}
    assert t["fresh_scan_entries"] == 3
    assert r1["unverified_ratio"] == pytest.approx(1 / 3)
    assert r1["unverified_ratio_judged"] == pytest.approx(1 / 3)  # 1/(2+1)
    assert r1["unverified_ratio_max"] == 0.5
    assert r1["orphans"] == [] and r1["stale_ids"] == []
    assert r1["uncollected_ids"] == []
    assert r1["gate"]["ok"] is True and r1["gate"]["fail_items"] == []
    # 全 id 列表排序（确定性面）
    for key in ("unverified_ids", "stale_ids", "uncollected_ids"):
        assert r1[key] == sorted(r1[key])


def test_audit_threshold_boundary_exact_and_exceeded(tmp_path: Path):
    reg = _build_repo(tmp_path, _KERNEL_TWO)  # 1 verified + 1 unverified
    # 恰等阈值（0.5 == 0.5）→ 绿（严格大于才红）
    r_eq = _audit(tmp_path, reg, unverified_ratio_max=0.5)
    assert r_eq["unverified_ratio"] == 0.5
    assert r_eq["gate"]["ok"] is True
    # 过线（0.4999 < 0.5）→ 红且 fail 项带占比与计数
    r_over = _audit(tmp_path, reg, unverified_ratio_max=0.4999)
    assert r_over["gate"]["ok"] is False
    assert any("unverified_ratio" in s and "1/2" in s
               for s in r_over["gate"]["fail_items"])
    # 缺省阈值 0.30 同样过线
    r_default = _audit(tmp_path, reg)
    assert r_default["gate"]["ok"] is False


def test_audit_rejects_nonpositive_threshold(tmp_path: Path):
    reg = _build_repo(tmp_path, _KERNEL_TWO)
    with pytest.raises(ValueError, match="unverified_ratio_max"):
        _audit(tmp_path, reg, unverified_ratio_max=0.0)


# ── 3. fail 三面：占比 / 孤儿 / stale ──────────────────────────────────────

def test_audit_orphan_kernel_file_fails_gate(tmp_path: Path):
    reg = _build_repo(tmp_path, _KERNEL_TWO)
    data = load_formula_provenance(reg)
    data["entries"][0]["kernel_file"] = "src/rfauto/core/ghost.py"
    reg.write_text(render_formula_provenance_yaml(data["entries"]),
                   encoding="utf-8")
    r = _audit(tmp_path, reg, unverified_ratio_max=0.5)
    assert r["gate"]["ok"] is False
    assert len(r["orphans"]) == 1
    assert r["orphans"][0]["kernel_file"] == "src/rfauto/core/ghost.py"
    assert any("orphan" in s for s in r["gate"]["fail_items"])


def test_audit_stale_ids_fail_and_uncollected_report_only(tmp_path: Path):
    reg = _build_repo(tmp_path, _KERNEL_TWO)
    entries = load_formula_provenance(reg)["entries"]
    # docstring 断链：注册表有 / 扫描无 → stale，门红
    r_stale = _audit(tmp_path, reg, unverified_ratio_max=0.5,
                     fresh_entries=[entries[0]])
    assert r_stale["stale_ids"] == [entries[1]["formula_id"]]
    assert r_stale["gate"]["ok"] is False
    assert any("stale" in s for s in r_stale["gate"]["fail_items"])
    # 反向：扫描有 / 注册表无 → uncollected 只进报告面，门不阻断
    extra = dict(entries[0])
    extra["formula_id"] = "ghost_kernel:<module>:01"
    r_uncol = _audit(tmp_path, reg, unverified_ratio_max=0.5,
                     fresh_entries=[*entries, extra])
    assert r_uncol["uncollected_ids"] == ["ghost_kernel:<module>:01"]
    assert r_uncol["stale_ids"] == []
    assert r_uncol["gate"]["ok"] is True
    assert r_uncol["gate"]["warn_counts"]["uncollected"] == 1


def test_audit_manual_entries_excluded_from_stale(tmp_path: Path):
    reg = _build_repo(tmp_path, _KERNEL_TWO)
    entries = load_formula_provenance(reg)["entries"]
    manual = [{"formula_id": "manual:thing:01",
               "claim_line": "人工补录（XA-6 测试）",
               "verified_by": "tester"}]
    reg.write_text(render_formula_provenance_yaml(entries, manual),
                   encoding="utf-8")
    r = _audit(tmp_path, reg, unverified_ratio_max=0.5)
    assert "manual:thing:01" not in r["stale_ids"]
    assert r["totals"]["manual_entries"] == 1
    assert r["gate"]["ok"] is True


# ── 4. 报告面：verified evidence 抽检 ──────────────────────────────────────

def test_audit_verified_without_evidence_listed_not_blocking(tmp_path: Path):
    reg = _build_repo(tmp_path, _KERNEL_THREE)
    r = _audit(tmp_path, reg, unverified_ratio_max=0.5)
    ids = [row["formula_id"] for row in r["verified_without_evidence"]]
    assert len(ids) == 1
    assert ids[0].startswith("demo_kernel:<module>:")  # Kerns §2.3 无年份无 DOI 席
    assert r["gate"]["warn_counts"]["verified_without_evidence"] == 1
    assert r["gate"]["ok"] is True  # 报告面不阻断


# ── 6. CLI 退出码与机读面 ──────────────────────────────────────────────────

def test_cli_exit_codes_and_json(tmp_path: Path, capsys: pytest.CaptureFixture):
    reg_ok = _build_repo(tmp_path, _KERNEL_THREE)
    # 人读绿例 → exit 0
    assert audit_mod.main(["--repo-root", str(tmp_path), "--registry",
                           str(reg_ok), "--unverified-ratio-max", "0.5"]) == 0
    capsys.readouterr()

    # --json 机读面可解析且 gate.ok 与退出码一致
    rc = audit_mod.main(["--repo-root", str(tmp_path), "--registry",
                         str(reg_ok), "--unverified-ratio-max", "0.5",
                         "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0 and payload["gate"]["ok"] is True
    assert payload["totals"]["entries"] == 3

    # 红例（孤儿）→ exit 1
    broken = tmp_path / "broken"
    broken.mkdir()
    reg_bad = _build_repo(broken, _KERNEL_TWO)
    d = load_formula_provenance(reg_bad)
    d["entries"][0]["kernel_file"] = "src/rfauto/core/ghost.py"
    reg_bad.write_text(render_formula_provenance_yaml(d["entries"]),
                       encoding="utf-8")
    rc_bad = audit_mod.main(["--repo-root", str(broken), "--registry",
                             str(reg_bad), "--unverified-ratio-max", "0.5"])
    assert rc_bad == 1
    capsys.readouterr()

    # 巡检不可执行（注册表缺失）→ exit 2
    rc_err = audit_mod.main(["--repo-root", str(tmp_path),
                             "--registry", str(tmp_path / "nope.yaml")])
    assert rc_err == 2


def test_cli_human_report_renders_gate_lines(tmp_path: Path,
                                             capsys: pytest.CaptureFixture):
    reg = _build_repo(tmp_path, _KERNEL_TWO)
    assert audit_mod.main(["--repo-root", str(tmp_path), "--registry",
                           str(reg), "--unverified-ratio-max", "0.4999"]) == 1
    out = capsys.readouterr().out
    assert "[xa6] FAIL:" in out
    assert "unverified_ratio" in out
    assert "collect_formula_provenance.py" in out  # 处置指引随报告


# ── 7. 真仓冒烟（只读；树面 drift 由 collector --check 看管）────────────────

@pytest.fixture(scope="module")
def live_report() -> dict:
    return audit_mod.audit_provenance(_REPO_ROOT)


@pytest.fixture(scope="module")
def _live_report_twice() -> tuple[dict, dict]:
    r1 = audit_mod.audit_provenance(_REPO_ROOT)
    r2 = audit_mod.audit_provenance(_REPO_ROOT)
    return r1, r2


def test_live_audit_self_consistent(live_report: dict):
    reg = load_formula_provenance()
    t = live_report["totals"]
    assert t["entries"] == len(reg["entries"])
    assert t["manual_entries"] == len(reg["manual_entries"])
    # 占比自洽：分子分母来自同一加载面
    n_unver = sum(1 for e in reg["entries"]
                  if e.get("access_status") == "unverified")
    assert live_report["unverified_ratio"] == pytest.approx(
        n_unver / len(reg["entries"]))
    assert sorted(live_report["unverified_ids"]) == live_report["unverified_ids"]


def test_live_audit_deterministic(_live_report_twice: tuple[dict, dict]):
    r1, r2 = _live_report_twice
    assert r1 == r2


def test_live_audit_no_orphans_gate_green(live_report: dict):
    # 零孤儿（文件存在性——test_formula_provenance 同款钉，双检防御）；
    # 门绿=当前树占比/断链在限内（树面 docstring drift 若使门红，
    # collector --check 同步红——两门联动的真信号，测试如实跟进修数据）。
    assert live_report["orphans"] == []
    assert live_report["gate"]["ok"] is True
    assert live_report["stale_ids"] == []
