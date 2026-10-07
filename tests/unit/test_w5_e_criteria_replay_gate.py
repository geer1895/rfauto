"""T15-B11 判据注册即重放门（常驻门；SPECS3 §3.2）。

门语义（预声明）：knowledge/criteria/v2 顶层每个 ``*.yaml`` 必须有
``tests/gold/criteria_replay/<stem>.json`` 快照——快照自带合成 artifact
样本（不依赖 runs/ 在档，runs 清理后仍可重放；#325 归档零改写精神的
自足化），门用 core/recast.py replay_one 对快照 artifact 重放，
replay_verdict / replay_vv_status / direction 与快照 expect **逐位一致**。

- 过=全量 yaml 有快照且重放一致；
- 不过=任一 v2 yaml 无快照（新增件未带快照）或重放翻转（判据被静默
  改形）或孤儿快照（yaml 已删快照残留——多报方向 #316）→ 红；
- skeleton/ 目录豁免（顶层 glob 不下钻，目录名显式，防在写半成品误伤）；
- nearest_reference_gate 登记 not_machine_replayable（recast 预声明，
  bespoke 重放钉在 test_vv_recast.py）——快照钉注册面本身
  （重放侧恒 None + direction=not_judged）。

存量 3 件快照回补=首版补齐而非豁免清单（spec §3.2 存量回补条款）。
本文件为 W5-E 席自建测试（批纪律命名；spec 原名
test_criteria_replay_gate.py 并档记录见 runs/w5_phase5/w5e/REPORT.md）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rfauto.core.recast import replay_one

REPO = Path(__file__).resolve().parents[2]
V2_DIR = REPO / "knowledge" / "criteria" / "v2"
SNAP_DIR = REPO / "tests" / "gold" / "criteria_replay"

SNAPSHOT_SCHEMA = "rfauto-criteria-replay-snapshot/1"
SNAPSHOT_REQUIRED = ("schema", "criteria_stem", "evidence_path", "artifact",
                     "expect")
EXPECT_REQUIRED = ("replay_verdict", "replay_vv_status", "direction")


def scan_criteria_replay_gate(criteria_dir: Path,
                              snapshot_dir: Path) -> list[dict]:
    """判据目录 × 快照目录 → 违例表（空表=门绿；确定性序）。

    违例 kind 词表：missing_snapshot / orphan_snapshot / criteria_load_error
    / snapshot_schema / replay_mismatch。
    """
    violations: list[dict] = []
    yaml_paths = sorted(Path(criteria_dir).glob("*.yaml"))
    yaml_stems = {p.stem for p in yaml_paths}
    snap_paths = sorted(Path(snapshot_dir).glob("*.json"))
    snap_stems = {p.stem for p in snap_paths}

    for stem in sorted(yaml_stems - snap_stems):
        violations.append({
            "kind": "missing_snapshot", "stem": stem,
            "detail": "v2 判据注册无重放快照（新增件必须随件带快照）",
        })
    for stem in sorted(snap_stems - yaml_stems):
        violations.append({
            "kind": "orphan_snapshot", "stem": stem,
            "detail": "快照无对应判据 yaml（判据已删快照残留/命名错位）",
        })

    for path in yaml_paths:
        stem = path.stem
        if stem not in snap_stems:
            continue
        try:
            criteria = yaml.safe_load(
                path.read_text(encoding="utf-8"))
        except Exception as exc:
            violations.append({
                "kind": "criteria_load_error", "stem": stem,
                "detail": f"yaml 解析失败: {exc}",
            })
            continue
        snap_path = Path(snapshot_dir) / f"{stem}.json"
        try:
            snap = json.loads(snap_path.read_text(encoding="utf-8"))
        except Exception as exc:
            violations.append({
                "kind": "snapshot_schema", "stem": stem,
                "detail": f"快照 JSON 解析失败: {exc}",
            })
            continue
        missing = [k for k in SNAPSHOT_REQUIRED if k not in snap]
        if missing or snap.get("schema") != SNAPSHOT_SCHEMA:
            violations.append({
                "kind": "snapshot_schema", "stem": stem,
                "detail": (f"快照 schema/必备键不合规（schema="
                           f"{snap.get('schema')!r} 缺 {missing}）"),
            })
            continue
        expect = snap["expect"]
        missing = [k for k in EXPECT_REQUIRED if k not in expect]
        if missing:
            violations.append({
                "kind": "snapshot_schema", "stem": stem,
                "detail": f"快照 expect 缺键 {missing}",
            })
            continue
        if snap.get("criteria_stem") != stem:
            violations.append({
                "kind": "snapshot_schema", "stem": stem,
                "detail": (f"快照 criteria_stem={snap.get('criteria_stem')!r}"
                           f" 与文件名 {stem!r} 不一致"),
            })
            continue
        rep = replay_one(snap["artifact"], criteria,
                         evidence_path=snap.get("evidence_path"),
                         archived_verdict_path="verdict")
        for field in EXPECT_REQUIRED:
            if rep.get(field) != expect[field]:
                violations.append({
                    "kind": "replay_mismatch", "stem": stem,
                    "detail": (f"重放 {field}={rep.get(field)!r} 与快照期望 "
                               f"{expect[field]!r} 不一致（判据被静默改形/"
                               f"翻案必须显式浮出，#122）"),
                })
    return violations


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestRealTreeGate:
    def test_all_v2_yaml_have_snapshot_and_replay_matches(self):
        """门绿路径：存量 3 件全有快照且重放逐位一致。"""
        violations = scan_criteria_replay_gate(V2_DIR, SNAP_DIR)
        assert violations == [], f"判据重放门红：{violations}"
        stems = {p.stem for p in V2_DIR.glob("*.yaml")}
        assert len(stems) >= 3, "v2 判据目录意外缩水（<3 件）"
        assert stems == {p.stem for p in SNAP_DIR.glob("*.json")}, (
            "yaml 与快照 stem 集合不一致")

    def test_snapshots_are_self_contained_synthetic(self):
        """快照自带合成 artifact 样本：不引用 runs/ 绝对路径（自足化）。"""
        for path in sorted(SNAP_DIR.glob("*.json")):
            snap = json.loads(_read(path))
            text = json.dumps(snap["artifact"], ensure_ascii=False)
            assert "E:" not in text, f"{path.name} artifact 内嵌盘符路径"
            assert "runs/" not in text, (
                f"{path.name} artifact 依赖 runs/ 在档（违自足化口径）")


class TestGateDoubleState:
    def _tmp_criteria(self, tmp_path: Path, text: str, name: str) -> Path:
        d = tmp_path / "v2"
        d.mkdir()
        (d / name).write_text(text, encoding="utf-8")
        return d

    def test_new_yaml_without_snapshot_red(self, tmp_path):
        """判据①：新增无快照 yaml → 门红（构造钉）。"""
        text = _read(V2_DIR / "df6_dp10_scan.yaml").replace(
            "criteria_id: df6_dp10_scan_j1c_coverage",
            "criteria_id: syn_new_gate_no_snapshot")
        d = self._tmp_criteria(tmp_path, text, "syn_new_gate.yaml")
        violations = scan_criteria_replay_gate(d, tmp_path / "snapshots")
        kinds = [v["kind"] for v in violations]
        assert "missing_snapshot" in kinds
        stem = next(v["stem"] for v in violations
                    if v["kind"] == "missing_snapshot")
        assert stem == "syn_new_gate"

    def test_tampered_threshold_flips_red(self, tmp_path):
        """判据③：篡改 yaml threshold（模拟判据漂移）→ 重放翻转 → 门红。"""
        text = _read(V2_DIR / "df6_dp10_scan.yaml").replace(
            "threshold: 300.0", "threshold: 400.0")
        d = self._tmp_criteria(tmp_path, text, "df6_dp10_scan.yaml")
        violations = scan_criteria_replay_gate(d, SNAP_DIR)
        mismatch = [v for v in violations if v["kind"] == "replay_mismatch"]
        assert mismatch, f"篡改门值未被重放门抓（判据改形必被门抓失效）: {violations}"
        assert any("replay_verdict" in v["detail"] for v in mismatch)

    def test_skeleton_dir_exempt(self, tmp_path):
        """判据④：skeleton/ 目录豁免（在写半成品不误伤）。"""
        d = tmp_path / "v2"
        (d / "skeleton").mkdir(parents=True)
        (d / "skeleton" / "wip_draft.yaml").write_text(
            "schema: criteria/v2\nstatus: draft\n", encoding="utf-8")
        violations = scan_criteria_replay_gate(d, tmp_path / "snapshots")
        assert violations == []

    def test_orphan_snapshot_red(self, tmp_path):
        """孤儿快照（yaml 已删快照残留）→ 门红（多报方向 #316）。"""
        d = tmp_path / "v2"
        d.mkdir()
        snaps = tmp_path / "snapshots"
        snaps.mkdir()
        (snaps / "ghost_criteria.json").write_text(
            _read(SNAP_DIR / "df6_dp10_scan.json"), encoding="utf-8")
        violations = scan_criteria_replay_gate(d, snaps)
        kinds = [v["kind"] for v in violations]
        assert kinds == ["orphan_snapshot"]
        assert violations[0]["stem"] == "ghost_criteria"

    def test_snapshot_missing_expect_red(self, tmp_path):
        """快照缺 expect 键 → snapshot_schema 违例（不静默放过）。"""
        text = _read(V2_DIR / "df6_dp10_scan.yaml")
        d = self._tmp_criteria(tmp_path, text, "df6_dp10_scan.yaml")
        snaps = tmp_path / "snapshots"
        snaps.mkdir()
        snap = json.loads(_read(SNAP_DIR / "df6_dp10_scan.json"))
        del snap["expect"]["direction"]
        (snaps / "df6_dp10_scan.json").write_text(
            json.dumps(snap, ensure_ascii=False), encoding="utf-8")
        violations = scan_criteria_replay_gate(d, snaps)
        kinds = [v["kind"] for v in violations]
        assert "snapshot_schema" in kinds
        assert any("direction" in v["detail"] for v in violations
                   if v["kind"] == "snapshot_schema")

    def test_scan_deterministic(self, tmp_path):
        """门扫描两次输出逐字节一致（确定性）。"""
        one = scan_criteria_replay_gate(V2_DIR, SNAP_DIR)
        two = scan_criteria_replay_gate(V2_DIR, SNAP_DIR)
        assert json.dumps(one, ensure_ascii=False) == json.dumps(
            two, ensure_ascii=False)
