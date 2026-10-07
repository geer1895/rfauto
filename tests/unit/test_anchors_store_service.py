"""DP-3 锚注册表装载/服务/CLI 接线测试（判据 a2 + b + d，预声明
runs/df6_dp3anchors/criteria.md）。

- a2：f_dip·L 双锚值与 scripts/wp39_followup_run.py 硬编码字面值逐位相等
  （regex 只读提取，scripts 非包不入 import 面）；
- b：provenance 单测——真实注册表 validate 全过（runs 路径存在/commit 可
  解析/时戳可解析/consumers 文件存在/referee_script 存在）；
- d：装载集合 == EXPECTED_ANCHORS 单源；
- store best-effort：缺文件/坏 YAML → 空集 + warning（#105）；
- service JSON 面四入口 + CLI/MCP 挂载最小接线。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY_PATH = _REPO_ROOT / "knowledge" / "anchors.yaml"


def _live_anchor_set():
    from rfauto.infra.anchors_store import load_anchors

    return load_anchors()


# ── 判据 d + b：单源计数与 provenance 全过 ─────────────────────────────────

def test_d_registry_matches_expected_single_source() -> None:
    from rfauto.core.anchors import EXPECTED_ANCHOR_COUNT, EXPECTED_ANCHORS

    anchor_set = _live_anchor_set()
    assert len(anchor_set.load_errors) == 0
    assert set(anchor_set.anchor_ids) == set(EXPECTED_ANCHORS)
    assert len(anchor_set) == EXPECTED_ANCHOR_COUNT


def test_b_validate_registry_full_pass() -> None:
    from rfauto.infra.anchors_store import validate_anchor_set

    report = validate_anchor_set(_live_anchor_set(),
                                 registry_path=_REGISTRY_PATH)
    assert report["ok"], f"provenance/schema issues: {report['issues']}"
    assert report["expected_match"] and report["count"] == 60  # ge8e X5 批 36→49


def test_b_each_active_anchor_provenance_fields_resolvable() -> None:
    from datetime import datetime

    anchor_set = _live_anchor_set()
    for rec in anchor_set.records:
        if rec.status == "awaiting_data":
            continue
        assert rec.provenance.get("arbitration_runs"), rec.anchor_id
        assert re.fullmatch(r"[0-9a-f]{7,40}",
                            str(rec.provenance["commit"]).lower())
        datetime.fromisoformat(str(rec.registered_at))
        assert rec.uncertainty and rec.uncertainty.get("value") is not None


# ── 判据 a2：f_dip·L 双值与 scripts 硬编码字面值逐位相等 ───────────────────

def test_a2_f_dip_l_bit_exact_against_script_literals() -> None:
    src = (_REPO_ROOT / "scripts" / "wp39_followup_run.py").read_text(
        encoding="utf-8")
    hfss_lit = float(re.search(r"^HFSS_PATCH_CONSTANT_REF\s*=\s*([0-9.]+)",
                               src, re.M).group(1))
    oe_lit = float(re.search(r"^OPENEMS_PATCH_CONSTANT_DOC\s*=\s*([0-9.]+)",
                             src, re.M).group(1))
    assert hfss_lit == 99.8 and oe_lit == 76.8  # 脚本现值先自钉
    anchor_set = _live_anchor_set()
    got_oe = anchor_set.resolve_anchor("patch.f_dip_l.openems-v1")
    got_hfss = anchor_set.resolve_anchor("patch.f_dip_l.hfss-v1")
    assert got_oe["value"] == oe_lit
    assert got_hfss["value"] == hfss_lit


def test_a2_patch_oe_last_verified_backfilled() -> None:
    """A1 回填钉（ge8e W1 席）：patch.f_dip_l.openems-v1 last_verified 非空。

    归档复测证据=runs/wp39_mvp_followup/patch_calib.json（openEMS 真机
    1.5-2.5GHz 401 点单点扫频，f_dip=1.94455GHz×L=40mm → 常数 77.78）：
    77.78 相对锚值 76.8 偏 1.28% 带内——沿 ge8b patch 名义 MISMATCH 同款
    保守裁决，锚值 76.8 维持（断锚历史零改写），仅回填 last_verified
    （at=复测落档时点，residual=相对偏差 0.0128）；复测注记随 provenance。
    """
    from datetime import datetime

    anchor_set = _live_anchor_set()
    rec = anchor_set.get("patch.f_dip_l.openems-v1")
    assert rec is not None and rec.last_verified is not None
    lv_at = datetime.fromisoformat(str(rec.last_verified["at"]))
    assert lv_at == datetime.fromisoformat("2026-09-13T15:34:23+08:00")
    assert rec.last_verified["residual"] == pytest.approx(0.0128)
    assert rec.value == 76.8  # 锚值维持（保守裁决，不随复测改锚）
    assert "复测回填" in str(rec.provenance.get("devlog"))  # 注记随锚落档
    # 兄弟席 hfss-v1（99.8）：W1 批时点为 null（零触碰钉）；2026-10-04
    # G1 G-14 批按 一百二十三 ④+runs/wp39_mvp_followup/patch_calib.
    # json hfss 块（probe.s1p 离线复核 99.79，相对锚值残差 1.0e-4）回填
    # ——时点收窄改钉回填值（#353① 口径：历史时点钉随新批次重标定收窄）
    hfss_rec = anchor_set.get("patch.f_dip_l.hfss-v1")
    assert hfss_rec is not None and hfss_rec.last_verified is not None
    assert hfss_rec.last_verified["at"] == "2026-09-13T15:34:23+08:00"
    assert hfss_rec.last_verified["residual"] == pytest.approx(0.0001)
    assert hfss_rec.value == 99.8  # 锚值维持（复核带内，不随复测改锚）
    assert "last_verified 回填" in str(hfss_rec.provenance.get("devlog"))


# ── store best-effort（#105）与缓存 ────────────────────────────────────────

def test_store_missing_file_best_effort_empty_warning(
        caplog: pytest.LogCaptureFixture) -> None:
    from rfauto.infra.anchors_store import load_anchors

    with caplog.at_level(logging.WARNING, logger="rfauto.infra.anchors_store"):
        anchor_set = load_anchors(_REPO_ROOT / "knowledge" / "no_such.yaml")
    assert len(anchor_set) == 0
    assert any("best-effort" in r.message for r in caplog.records)


def test_store_corrupt_yaml_best_effort_empty(
        caplog: pytest.LogCaptureFixture) -> None:
    from rfauto.infra.anchors_store import load_anchors

    bad = _REPO_ROOT / "runs" / "df6_dp3anchors" / "_bad_anchors.yaml"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("anchors: [ {anchor_id: broken\n  :::\n", encoding="utf-8")
    try:
        with caplog.at_level(logging.WARNING,
                             logger="rfauto.infra.anchors_store"):
            anchor_set = load_anchors(bad, force_reload=True)
        assert len(anchor_set) == 0
        assert caplog.records
    finally:
        bad.unlink(missing_ok=True)


def test_store_bad_anchor_does_not_sink_whole_table() -> None:
    from rfauto.core.anchors import AnchorSet
    from rfauto.infra.anchors_store import load_anchors

    data = yaml.safe_load(_REGISTRY_PATH.read_text(encoding="utf-8"))
    data["anchors"].append({"anchor_id": "bad.id-v1", "kind": "constant",
                            "status": "active"})
    merged = AnchorSet(data["anchors"])
    assert len(merged.load_errors) == 1
    assert len(merged) == 60  # ge8e X5 批 36→49
    assert load_anchors(_REGISTRY_PATH) is not None


def test_store_mtime_cache_roundtrip() -> None:
    from rfauto.infra.anchors_store import load_anchors

    first = load_anchors(_REGISTRY_PATH)
    second = load_anchors(_REGISTRY_PATH)
    assert first is second  # 同 (path, mtime, size) 命中缓存


# ── service JSON 面 ────────────────────────────────────────────────────────

def test_service_list_inspect_validate_resolve_json_roundtrip() -> None:
    from rfauto.service import anchors_service as svc

    listed = svc.list_anchors()
    assert listed["ok"] and listed["count"] == 60  # ge8e X5 批 36→49
    assert json.dumps(listed, ensure_ascii=False)  # JSON 可序列化

    inspected = svc.inspect_anchor("c3.l_via_h.openems-hfss-v1")
    assert inspected["ok"] and inspected["anchor"]["value"] == 0.125e-9

    miss = svc.inspect_anchor("no.such-v1")
    assert miss["ok"] is False and "未知锚" in miss["error"]

    report = svc.validate_registry()
    assert report["ok"] and report["expected_match"]

    resolved = svc.resolve_anchor_request("cps.gamma_er.fdref-v1",
                                          {"er": 3.66})
    assert resolved["ok"] and resolved["result"]["value"] == pytest.approx(
        1.3949000923648935)

    residual = svc.note_anchor_residual_request("cps.gamma_er.fdref-v1",
                                                {"er": 3.66}, 1.40)
    assert residual["ok"] and residual["result"]["stale"] is False


def test_service_registry_yaml_shape_honest() -> None:
    """schema: anchors/v1 头与全注册表 status 如实登记。

    HFSS 窗 B→A 批（wf:anchor-register，2026-09-29）：+6 窗锚——constant 2
    席 active（wilkinson.f_match/gysel.s32_iso）+ pointer 4 席 experimental
    （stepped/coupled_line/marchand/branchline 双值指针）；补批
    （wf:anchor-register-p1x4，2026-09-29）+1 constant active
    （patch_array_1x4.f_res）；指针补批（wf:anchor-pointer-register，
    2026-09-29）+1 pointer experimental（patch_array.f_res 族级双值，
    席 8 2x2 重跑 DISAGREE）；P-KJ-EVEN P3 批（wf:goal-t5，2026-09-30）
    +1 constant active（coupled_microstrip.kj_even_domain.lit-v1，KJ even
    闭式适用域盒锚：域盒 u/g/er=[0.1,10]²×[1,18]+域内基准 0.66%+两条域缘
    MARGINAL 注记）；Goal 批 T14（wf:goal-t14，2026-09-30）+2 constant active
    （mmt.inductive_post_b.hfss-v1 / mmt.resonant_window_fres.hfss-v1，ME-5
    MMT 销钉/谐振窗 HFSS 仲裁偏差常量）；ge6 Wave1 锚注册批
    （wf:ge6-anchor，2026-10-01）+2 pointer experimental（ring.design_dk
    双引擎 DISAGREE 双值 {oe 3.5333, hfss 3.3425}+mmwave.design_dk.ro3003-
    oe-v1 OE 单引擎封档 {oe 3.1434}，constant 待 78GHz HFSS 仲裁腿）；
    ge6 A22 批（wf:ge6-a22，2026-10-01）+1 pointer experimental
    （ms_cross.wg_resonance 双值 {oe 11.675, hfss 11.4951}，ge6 席 2
    HFSS 仲裁分支 A 收敛判读——wg 模拟器谷位两引擎 AGREE，偏离 Floquet
    属前提差禁产 constant）。
    全表 active=13、experimental=36（ge8e X5 批 +13 全 experimental）。
    """
    data = yaml.safe_load(_REGISTRY_PATH.read_text(encoding="utf-8"))
    assert data["schema"] == "anchors/v1"
    statuses = {a["anchor_id"]: a["status"] for a in data["anchors"]}
    assert statuses["c3.k_of_g.openems-hfss-v1"] == "active"
    assert sum(s == "active" for s in statuses.values()) == 17  # ge8 K-4 v2 constant active  # W7-A G-13 首判回填 +4（ratrace.ring_z/r_ring、siw.fc_te10、monopole.mon_len PASS→active，evolve_anchors 原地翻转）
    assert sum(s == "experimental" for s in statuses.values()) == 43  # W7-A G-13 回填 -4（X5 四席 PASS→active） # W6-F cpw +1（核验裁决 A=CPWG/50Ω，experimental） # W4-E 锚二批+UX-B1 档① +10（全 experimental：cps×2/suspended_stripline×2/cheb_g×5/xcheb_bpf4/msl_cpw.s11）  # ge8e X5 批 +13（…；W7-A 首判回填后 13 席=active4+experimental9，见 anchors.yaml 各席 devlog 首判注记）  # ge8 TA 批三 +4  # ge8 TA 批二 +4  # ge8 TA 批 +2 内核恒等锚 experimental  # ge8b WA 席1 +3  # ge8b WB 席B9 +2
    for aid in ("wilkinson.f_match.openems-hfss-v1",
                "gysel.s32_iso.openems-hfss-v1",
                "patch_array_1x4.f_res.openems-hfss-v1",
                "coupled_microstrip.kj_even_domain.lit-v1",
                "mmt.inductive_post_b.hfss-v1",
                "mmt.resonant_window_fres.hfss-v1"):
        assert statuses[aid] == "active"
    for aid in ("stepped_impedance.f_pass.openems-hfss-v1",
                "coupled_line.s31_coupling.openems-hfss-v1",
                "marchand.f_null.openems-hfss-v1",
                "branchline.f_match.openems-hfss-v1",
                "patch_array.f_res.openems-hfss-v1",
                "ring.design_dk.openems-hfss-v1",
                "mmwave.design_dk.ro3003-oe-v1",
                "ms_cross.wg_resonance.openems-hfss-v1"):
        assert statuses[aid] == "experimental"
        row = next(a for a in data["anchors"] if a["anchor_id"] == aid)
        assert row["kind"] == "pointer" and row["value"] is None
        # 消费面断言：wilkinson（constant active）锚接 +3 消费者（XC-A 回填
        # 时点 374cc5b）；branchline pointer 席原同批挂 +3，2026-10-04 G-07
        # 对齐 pointer 契约（模块头注"不就地求值"+pointer 4 席块注
        # "consumers=[] 消费面不接"）清回 []；其余指针锚维持零接线
        if aid == "wilkinson.f_match.openems-hfss-v1":
            assert "src/rfauto/core/anchors.py" in (row["consumers"] or [])
        else:
            assert row["consumers"] == []  # 消费面不接（指针锚登记语义）
    fam = next(a for a in data["anchors"]
               if a["anchor_id"] == "patch_array.f_res.openems-hfss-v1")
    assert fam["quantity"]["values"] == {"openems": 4.976, "hfss": 5.6898}
    assert fam["quantity"]["metric"] == "f_min_ghz"
    kj = next(a for a in data["anchors"]
              if a["anchor_id"] == "coupled_microstrip.kj_even_domain.lit-v1")
    assert kj["kind"] == "constant" and kj["value"] == 0.66
    assert kj["consumers"] == []  # 运行时 warning 接线留主代理裁定（P1 §8.6）
    assert kj["domain"] == {"u": [0.1, 10], "g": [0.1, 10], "er": [1, 18]}
    assert "MARGINAL" in kj["provenance"]["domain_note"]  # 域缘注记随锚落档
    kofg = next(a for a in data["anchors"]
                if a["anchor_id"] == "c3.k_of_g.openems-hfss-v1")
    assert len(kofg["points"]) == 6
    assert kofg["uncertainty"] is not None
    assert kofg["provenance"]["arbitration_runs"] == ["runs/df6_a1_r4"]


# ── CLI 挂载最小接线（#305：--help 真构建；list/validate JSON 出）──────────

def test_cli_anchors_help_builds() -> None:
    from typer.testing import CliRunner

    from rfauto.cli.main import app

    runner = CliRunner()
    for args in (["anchors", "--help"], ["anchors", "list", "--help"],
                 ["anchors", "inspect", "--help"],
                 ["anchors", "validate", "--help"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, (args, result.output)


def test_cli_anchors_list_json() -> None:
    from typer.testing import CliRunner

    from rfauto.cli.main import app

    result = CliRunner().invoke(app, ["anchors", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["count"] == 60  # ge8e X5 批 36→49


def test_cli_anchors_inspect_json() -> None:
    from typer.testing import CliRunner

    from rfauto.cli.main import app

    result = CliRunner().invoke(
        app, ["anchors", "inspect", "patch.f_dip_l.openems-v1", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["anchor"]["value"] == 76.8


def test_cli_anchors_validate_pass() -> None:
    from typer.testing import CliRunner

    from rfauto.cli.main import app

    result = CliRunner().invoke(app, ["anchors", "validate"])
    assert result.exit_code == 0, result.output


# ── QW-16 漂移预警（ge-code2 批：service + CLI drift）──────────────────────

def test_service_anchor_drift_status_empty_series_honest() -> None:
    """无序列数据 → ok=True + empty_series 如实（QW-16 积累期口径）。"""
    from rfauto.service.anchors_service import anchor_drift_status

    status = anchor_drift_status("cps.gamma_er.fdref-v1")
    assert status["ok"] is True
    assert status["history_source"] in ("none", "registry.last_verified",
                                        "snapshot_store")
    assert status["empty_series"] == (
        status["report"]["verdict"] == "no_data")


def test_service_anchor_drift_status_explicit_series() -> None:
    """显式序列：上升序列 → MK 线+劈半指纹差分双线 → drifted。"""
    from rfauto.service.anchors_service import anchor_drift_status

    status = anchor_drift_status(
        "cps.gamma_er.fdref-v1",
        [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5])
    assert status["ok"] is True
    assert status["history_source"] == "caller"
    assert status["report"]["verdict"] == "drifted"
    assert status["report"]["trend"]["trend"] == "increasing"


def test_service_anchor_drift_status_unknown_anchor() -> None:
    from rfauto.service.anchors_service import anchor_drift_status

    status = anchor_drift_status("no.such.anchor-v1")
    assert status["ok"] is False
    assert "未知锚" in status["error"]


def test_snapshot_record_load_status_roundtrip(tmp_path: Path) -> None:
    """快照机制：record→load→status 回退链（snapshot_store 数据源）。"""
    from rfauto.service.anchors_service import (
        anchor_drift_status,
        load_anchor_drift_snapshots,
        record_anchor_drift_snapshot,
    )

    store = tmp_path / "snapshots.json"
    assert record_anchor_drift_snapshot(
        "cps.gamma_er.fdref-v1", [0.0, 0.1, 0.0, 0.1], at="t0",
        store_path=store)["ok"] is True
    assert record_anchor_drift_snapshot(
        "cps.gamma_er.fdref-v1", [5.0, 5.1, 5.0, 5.1], at="t1",
        store_path=store)["ok"] is True
    loaded = load_anchor_drift_snapshots("cps.gamma_er.fdref-v1",
                                         store_path=store)
    assert loaded["count"] == 2
    status = anchor_drift_status("cps.gamma_er.fdref-v1",
                                 store_path=store)
    assert status["history_source"] == "snapshot_store"
    # 两快照仅指纹差分线可用 → 单线上限 warning（阶梯跳变被尺度归一捕获）
    assert status["report"]["verdict"] == "warning"
    # 其他锚过滤：快照库无该锚记录 → 回退注册表/空（不串数据）
    other = anchor_drift_status("patch.f_dip_l.openems-v1",
                                store_path=store)
    assert other["history_source"] != "snapshot_store"


def test_cli_anchors_drift_json_and_history_file(tmp_path: Path) -> None:
    """CLI drift：JSON 输出 + --history-file 序列形态端到端。"""
    from typer.testing import CliRunner

    from rfauto.cli.main import app

    history = tmp_path / "history.json"
    history.write_text(json.dumps([0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]),
                       encoding="utf-8")
    result = CliRunner().invoke(
        app, ["anchors", "drift", "cps.gamma_er.fdref-v1",
              "--history-file", str(history), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["history_source"] == "caller"
    assert payload["report"]["verdict"] == "drifted"

    empty = CliRunner().invoke(
        app, ["anchors", "drift", "cps.gamma_er.fdref-v1", "--json"])
    assert empty.exit_code == 0, empty.output
    payload_empty = json.loads(empty.output)
    assert payload_empty["ok"] is True
    assert payload_empty["empty_series"] is True


def test_cli_anchors_drift_bad_history_file(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from rfauto.cli.main import app

    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    result = CliRunner().invoke(
        app, ["anchors", "drift", "cps.gamma_er.fdref-v1",
              "--history-file", str(bad)])
    assert result.exit_code == 1
    assert "history_file" in result.output


# ── MCP 挂载最小接线（工具注册 + 可调用，不开传输；#270 list_tools 口径）────

def test_mcp_tools_registered_and_callable() -> None:
    import asyncio

    from rfauto.mcp_server import mcp

    tools = {t.name: t for t in asyncio.run(mcp.list_tools())}
    assert {"anchors_list", "anchors_inspect"} <= set(tools)
    listed = tools["anchors_list"].fn()
    assert listed["ok"] and listed["count"] == 60  # ge8e X5 批 36→49
    inspected = tools["anchors_inspect"].fn("c3.l_via_h.openems-hfss-v1")
    assert inspected["ok"] and inspected["anchor"]["version"] == 1
