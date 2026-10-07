"""judge_k3_envelope 通道级门回退读单测（ge8e 审查批 F7 回归钉，R6-1）。

原缺陷：runs/ge8_k3mech/judge_k3.py 的 campaign_gates 只读 seat_dir/
verdict.json——本批该文件不存在，三座真实通道状态在 envelope.json
（verdict=PARTIAL、exec_rc=1、reason 明言 solve_success=False 降档）→
campaign_* 全 null、三座 status=OK，判据 §4"任一座位 PARTIAL→该座如实
记"缺账。

fixture 三态（数据形态对照 runs/review_ge8e/r6_runs/r6_scripts_k3.py 复算
批与三座真实 envelope.json 键面）：
1. verdict.json 存在 → 原口径消费（status/nrts/g5）；
2. verdict.json 缺失 + envelope.json PARTIAL/exec_rc=1 → 通道级 PARTIAL、
   solve_success=False、座位状态 CAMPAIGN_PARTIAL（如实不凑 OK）；
3. 两档全缺 → 相关字段 None（best-effort 如实，不阻断机械数值门）。
另钉 FAIL 态阻断。全离线零仿真；归档零改写（fixture 全在 tmp_path）。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_PATH = (Path(__file__).resolve().parents[2] / "scripts"
               / "judge_k3_envelope.py")
_spec = importlib.util.spec_from_file_location(
    "_judge_k3_envelope_under_test", SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
jke = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("_judge_k3_envelope_under_test", jke)
_spec.loader.exec_module(jke)

campaign_gates_with_envelope = jke.campaign_gates_with_envelope
seat_status_from_gates = jke.seat_status_from_gates
usable_for_mech = jke.usable_for_mech


def _write_envelope(seat_dir: Path, verdict: str, exec_rc: int) -> None:
    """envelope.json fixture——键面照 x1_gapmesh/envelope.json 实测形态。"""
    envelope = {
        "ok": True,
        "verdict": verdict,
        "skipped": False,
        "launched": True,
        "reason": ("引擎 rc=1 非零但产物已回拉（50 文件）——判读交本地判读面"
                   "（产物优先于退出码口径），seat 判读按 solve_success=False 降档"
                   if exec_rc != 0 else "全门过"),
        "errors": [],
        "machine": "sim_host",
        "batch": "oe_47001f7c",
        "out_dir_local": str(seat_dir),
        "exec_rc": exec_rc,
        "wait_mode": "sync",
    }
    seat_dir.mkdir(parents=True, exist_ok=True)
    (seat_dir / "envelope.json").write_text(
        json.dumps(envelope, ensure_ascii=False, indent=1), encoding="utf-8")


def _write_verdict_json(seat_dir: Path, status: str | None) -> None:
    v: dict = {"status": status,
               "nrts_converged": {"ok": True, "reason": "energy stop"},
               "g5_health": {"ok": True}}
    seat_dir.mkdir(parents=True, exist_ok=True)
    (seat_dir / "verdict.json").write_text(
        json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")


class TestCampaignGatesThreeStates:
    """三态 fixture：verdict.json / envelope PARTIAL / 全缺。"""

    def test_state1_verdict_json_present_original_semantics(self, tmp_path):
        seat = tmp_path / "x1_gapmesh"
        _write_verdict_json(seat, "done")
        _write_envelope(seat, "PARTIAL", exec_rc=1)  # 并存时 verdict.json 优先
        g = campaign_gates_with_envelope(seat)
        assert g["campaign_source"] == "verdict.json"
        assert g["campaign_verdict_status"] == "done"
        assert g["nrts_converged_ok"] is True
        assert g["g5_health_ok"] is True
        assert g["exec_rc"] is None  # envelope 面不消费

    def test_state2_envelope_partial_fallback(self, tmp_path):
        """R6-1 主钉：verdict.json 缺档 → envelope PARTIAL 如实入账。"""
        seat = tmp_path / "x2a_len204"
        _write_envelope(seat, "PARTIAL", exec_rc=1)
        g = campaign_gates_with_envelope(seat)
        assert g["campaign_source"] == "envelope.json"
        assert g["campaign_verdict_status"] == "PARTIAL"
        assert g["envelope_verdict"] == "PARTIAL"
        assert g["exec_rc"] == 1
        assert g["solve_success"] is False  # 降档语义（reason 留痕）
        assert "solve_success=False" in (g["envelope_reason"] or "")
        # nrts/g5 该文件不含 → 如实 None 不伪造
        assert g["nrts_converged_ok"] is None
        assert g["g5_health_ok"] is None

    def test_state2b_envelope_pass_ok(self, tmp_path):
        seat = tmp_path / "clean_seat"
        _write_envelope(seat, "PASS", exec_rc=0)
        g = campaign_gates_with_envelope(seat)
        assert g["campaign_verdict_status"] == "PASS"
        assert g["solve_success"] is True

    def test_state3_both_missing_all_none(self, tmp_path):
        g = campaign_gates_with_envelope(tmp_path / "empty_seat")
        assert g["campaign_verdict_status"] is None
        assert g["campaign_source"] is None
        assert g["solve_success"] is None
        assert g["nrts_converged_ok"] is None
        assert g["g5_health_ok"] is None


class TestSeatStatusDowngrade:
    """判据 §4 对账：任一座位 PARTIAL → 该座降档记，不凑 OK。"""

    def test_envelope_partial_downgrades_seat(self, tmp_path):
        seat = tmp_path / "x2b_len208"
        _write_envelope(seat, "PARTIAL", exec_rc=1)
        g = campaign_gates_with_envelope(seat)
        # 数据面完整（401 点/有限/无源照 r6_scripts_k3 复算形态）→ 机械门照算
        assert seat_status_from_gates(
            g, numeric_gates_ok=True, hygiene_ok=True) == "CAMPAIGN_PARTIAL"
        assert usable_for_mech(g) is True  # 产物优先于退出码：数据可消费
        # 数据缺失照旧 MISSING
        assert seat_status_from_gates(
            g, numeric_gates_ok=False, hygiene_ok=True) == "MISSING"

    def test_envelope_fail_blocks(self, tmp_path):
        seat = tmp_path / "failed_seat"
        _write_envelope(seat, "FAIL", exec_rc=2)
        g = campaign_gates_with_envelope(seat)
        assert g["campaign_verdict_status"] == "FAIL"
        assert seat_status_from_gates(
            g, numeric_gates_ok=True, hygiene_ok=True) == "CAMPAIGN_GATE_ISSUE"
        assert usable_for_mech(g) is False

    def test_missing_gates_do_not_block(self, tmp_path):
        """全缺档（字段 None）不阻断机械数值门——judge_k3 原口径延续。"""
        g = campaign_gates_with_envelope(tmp_path / "empty")
        assert seat_status_from_gates(
            g, numeric_gates_ok=True, hygiene_ok=True) == "OK"
        assert usable_for_mech(g) is True

    def test_hygiene_fail_with_partial_gate(self, tmp_path):
        seat = tmp_path / "x1_gapmesh"
        _write_envelope(seat, "PARTIAL", exec_rc=1)
        g = campaign_gates_with_envelope(seat)
        assert seat_status_from_gates(
            g, numeric_gates_ok=True, hygiene_ok=False) == "CAMPAIGN_GATE_ISSUE"


class TestArchiveUntouched:
    """归档零改写钉：模块不向 batch 目录写任何文件。"""

    def test_main_does_not_touch_batch_dir(self, tmp_path, monkeypatch,
                                           capsys):
        seat = tmp_path / "x1_gapmesh"
        _write_envelope(seat, "PARTIAL", exec_rc=1)
        before = {p.name: p.stat().st_mtime for p in tmp_path.rglob("*")}
        monkeypatch.setattr(sys, "argv", [
            "judge_k3_envelope.py", "--batch-dir", str(tmp_path)])
        rc = jke.main()
        assert rc == 0
        after = {p.name: p.stat().st_mtime for p in tmp_path.rglob("*")}
        assert before == after
        out = json.loads(capsys.readouterr().out)
        assert out["seats"]["x1_gapmesh"]["campaign"][
            "campaign_verdict_status"] == "PARTIAL"
