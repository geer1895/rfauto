"""aurora_e W3-S4：campaign digest 战役终态摘要聚合器测试（全合成零真机零网络）。

判据（任务书：digest 聚合器 + zh 文案 + runs/ 产物 + CLI 单节触发）：
①service 合成战役态→摘要文案：COMPLETE/PARTIAL/ABORTED 三终态各一——
  计数行、逐战役行（✓/⚠/✗ + 阶段进度）、失败原因摘录（apply_event 的
  "failed: detail" note 尾段）齐备；
②verdict 语义复用：非终态（RUNNING/无 verdict）缺省不计入，
  include_running=True 计入且不冒充终态；
③since_h 时间窗：老计划（mtime 回拨）被窗滤掉；非法 since_h 如实
  ok=False；
④产物：JSON+文本双产物落盘（原子写），JSON 读回含 schema/counts/
  artifacts；write=False 零落盘；空扫描如实 ok=True"无终态战役"；
⑤CLI 接线：rfauto campaign digest 人读面 + --json 信封面（W2-C 棘轮
  口径：新叶必带 --json）；失败面（非法 since_h）--json 同构信封。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from typer.testing import CliRunner

# 规范注册序锁定（本文件字母序 < test_cli.py < test_cli_registration_order.py
# ——若先导 bands_uq 域模块，其 calc_vna 联带导入会把 sparams-compare 等
# 根 app 命令抢注册到队首，CLI 注册序金快照测试在本文件同跑时必红；模块面
# 先导 cli.main 即按 main.py 规范序完成全部域注册，测试函数内的域模块惰性
# 导入皆缓存命中，零序漂移）。
from rfauto.cli.main import app as _cli_root_app  # noqa: F401
from rfauto.service.campaign_digest_service import (
    DIGEST_DIR_DEFAULT,
    campaign_digest,
    failure_reason,
    render_digest_text,
)
from rfauto.service.campaign_manager import apply_event, plan_campaign, save_plan

runner = CliRunner()

_STAGES = ("calibrate", "prefilter", "tune", "tolerance", "report",
           "final_verify")


def _recipe(tmp_path: Path, name: str) -> Path:
    p = tmp_path / f"recipe_{name}.yaml"
    p.write_text(
        "model: wilkinson\n"
        "objectives:\n"
        "  - metric: s11_db\n"
        "    target: -15\n"
        "limits:\n"
        "  max_trials: 5\n",
        encoding="utf-8")
    return p


def _plan_dir(tmp_path: Path, name: str, *, model: str = "wilkinson") -> Path:
    """立一个真实 plan 落盘（走 plan_campaign + save_plan 生产路径）。"""
    recipe = _recipe(tmp_path, name)
    plan = plan_campaign(recipe)
    assert plan.get("ok"), plan.get("errors")
    plan["model"] = model  # 测试可读性：战役名与 model 解耦
    d = tmp_path / name
    save_plan(plan, d)
    return d


def _drive_terminal(d: Path, verdict: str, *, fail_detail: str = "") -> None:
    """用 apply_event 生产状态机推进到目标终态并回写落盘。"""
    from rfauto.service.campaign_manager import load_plan

    plan = load_plan(d)["plan"]
    if verdict == "COMPLETE":
        for s in _STAGES:
            apply_event(plan, s, "stage_done")
    elif verdict == "ABORTED":
        apply_event(plan, "tune", "stage_failed", detail=fail_detail)
    else:  # PARTIAL：dead>0 且零 failed（aborted 直改——apply_event 词表
        # 只经 failed 传播 aborted，本形态来自手工状态面/旧 plan，合法读入）
        for s in plan["stages"]:
            if s["stage"] == "tolerance":
                s["status"] = "aborted"
        apply_event(plan, "report", "stage_done")
    save_plan(plan, d)


# ── ① 合成战役态 → 摘要文案 ────────────────────────────────────────────

class TestDigestText:
    def test_three_terminal_states_summary(self, tmp_path):
        for name, verdict, detail in (
                ("wilkinson", "COMPLETE", ""),
                ("patch", "COMPLETE", ""),
                ("vivaldi", "ABORTED", "NrTS 触顶")):
            d = _plan_dir(tmp_path, name, model=name)
            _drive_terminal(d, verdict, fail_detail=detail)
        out = campaign_digest(str(tmp_path), write=False)
        assert out["ok"] is True
        assert out["n_campaigns"] == 3
        assert out["counts"] == {"COMPLETE": 2, "PARTIAL": 0, "ABORTED": 1}
        text = out["summary_text"]
        assert "共 3 战役终态" in text
        assert "2 完成" in text and "1 已中止" in text
        assert "- wilkinson ✓ 完成（6/6 阶段）" in text
        assert "- vivaldi ✗ 已中止" in text
        # 失败原因摘录：apply_event note 尾段进文案（任务书示例口径）
        assert "NrTS 触顶" in text
        # 导语单行（信封 headline）带逐战役内联
        assert "vivaldi ✗ 已中止（" in out["headline"]
        # 逐战役明细带 plan 路径（权威细节锚点）
        paths = {it["name"]: it["path"] for it in out["campaigns"]}
        assert (tmp_path / "vivaldi" / "campaign.plan.json") == Path(paths["vivaldi"])

    def test_partial_campaign_no_false_reason(self, tmp_path):
        """手工 aborted（无 failed: 标记）不把阶段规划描述冒充失败原因。"""
        d = _plan_dir(tmp_path, "c3", model="branchline")
        _drive_terminal(d, "PARTIAL")
        out = campaign_digest(str(tmp_path), write=False)
        assert out["counts"]["PARTIAL"] == 1
        assert "⚠ 部分完成" in out["summary_text"]
        assert "原因" not in out["summary_text"]
        assert out["campaigns"][0]["reason"] == ""


class TestFailureReason:
    def test_failed_note_tail_extracted(self):
        plan = {"stages": [
            {"stage": "tune", "status": "failed",
             "note": "中保真精算 | failed: NrTS 触顶"},
        ]}
        assert failure_reason(plan) == "NrTS 触顶"

    def test_complete_plan_empty_reason(self):
        assert failure_reason({"stages": [
            {"stage": "tune", "status": "done"}]}) == ""

    def test_long_reason_truncated(self):
        plan = {"stages": [{"stage": "tune", "status": "failed",
                            "note": "failed: " + "x" * 200}]}
        r = failure_reason(plan)
        assert len(r) == 61 and r.endswith("…")


# ── ② verdict 语义复用（非终态过滤） ───────────────────────────────────

class TestVerdictFilter:
    def test_running_excluded_by_default(self, tmp_path):
        _plan_dir(tmp_path, "fresh")  # 未推进：无 verdict
        d2 = _plan_dir(tmp_path, "done_camp")
        _drive_terminal(d2, "COMPLETE")
        out = campaign_digest(str(tmp_path), write=False)
        assert out["n_campaigns"] == 1
        assert out["campaigns"][0]["name"] == "done_camp"

    def test_include_running_marks_not_terminal(self, tmp_path):
        _plan_dir(tmp_path, "fresh")
        out = campaign_digest(str(tmp_path), write=False, include_running=True)
        assert out["n_campaigns"] == 1
        it = out["campaigns"][0]
        assert it["verdict_zh"] == "进行中"
        # 非终态不计入三终态计数（不冒充终态）
        assert out["counts"] == {"COMPLETE": 0, "PARTIAL": 0, "ABORTED": 0}
        assert "1 个非终态计入" in out["summary_text"]


# ── ③ since_h 时间窗 ──────────────────────────────────────────────────

class TestSinceWindow:
    def test_old_plan_filtered(self, tmp_path):
        d_old = _plan_dir(tmp_path, "old_camp")
        _drive_terminal(d_old, "COMPLETE")
        d_new = _plan_dir(tmp_path, "new_camp")
        _drive_terminal(d_new, "COMPLETE")
        old = time.time() - 48 * 3600
        os.utime(d_old / "campaign.plan.json", (old, old))
        out = campaign_digest(str(tmp_path), write=False, since_h=24.0)
        assert out["n_campaigns"] == 1
        assert out["campaigns"][0]["name"] == "new_camp"
        assert out["since_h"] == 24.0

    def test_invalid_since_h_error_envelope(self, tmp_path):
        out = campaign_digest(str(tmp_path), write=False, since_h=0)
        assert out["ok"] is False and out["errors"]
        out2 = campaign_digest(str(tmp_path), write=False, since_h="abc")
        assert out2["ok"] is False and out2["errors"]


# ── ④ 产物落盘 ────────────────────────────────────────────────────────

class TestArtifacts:
    def test_json_and_txt_written(self, tmp_path):
        d = _plan_dir(tmp_path, "c1")
        _drive_terminal(d, "COMPLETE")
        out_root = tmp_path / "digest_out"
        out = campaign_digest(str(tmp_path), out_dir=out_root, write=False)
        # write=False：无 artifacts 键（预览面零副作用）
        assert "artifacts" not in out
        out = campaign_digest(str(tmp_path), out_dir=out_root)
        art = out["artifacts"]
        assert Path(art["json"]).exists() and Path(art["txt"]).exists()
        payload = json.loads(Path(art["json"]).read_text(encoding="utf-8"))
        assert payload["schema"] == "rfauto-campaign-digest-v1"
        assert payload["n_campaigns"] == 1
        txt = Path(art["txt"]).read_text(encoding="utf-8")
        assert txt.strip() == out["summary_text"]

    def test_default_out_dir_uses_runs_root(self, tmp_path, monkeypatch):
        """缺省产物根走 runs_paths 双根收敛（DIGEST_DIR_DEFAULT）。"""
        from rfauto.infra import runs_paths

        monkeypatch.chdir(tmp_path)
        (tmp_path / "runs").mkdir()
        out = campaign_digest(str(tmp_path / "scans"), write=True)
        assert Path(out["artifacts"]["json"]).parent == (
            tmp_path / "runs" / "campaign_digest")
        # 单源常量与缺省落点一致
        assert DIGEST_DIR_DEFAULT == "runs/campaign_digest"
        assert runs_paths.resolve_runs_dir(
            DIGEST_DIR_DEFAULT) == tmp_path / "runs" / "campaign_digest"

    def test_empty_scan_is_ok_not_error(self, tmp_path):
        (tmp_path / "nobody").mkdir()
        out = campaign_digest(str(tmp_path / "nobody"), write=False)
        assert out["ok"] is True
        assert out["n_campaigns"] == 0
        assert "无终态战役" in out["summary_text"]
        assert "无终态战役" in render_digest_text(
            [], root="x", generated_at="t")


# ── ⑤ CLI 接线 ────────────────────────────────────────────────────────

class TestCliDigest:
    def _app(self):
        # 域模块惰性导入（lazy-import-conventions；模块面已先导 cli.main
        # 锁规范注册序，此处缓存命中零漂移）。
        from rfauto.cli.domains.bands_uq import campaign_app

        return campaign_app

    def _camp(self, tmp_path: Path) -> Path:
        d = _plan_dir(tmp_path, "cli_camp", model="wilkinson")
        _drive_terminal(d, "COMPLETE")
        return d

    def test_human_output_and_artifacts(self, tmp_path):
        self._camp(tmp_path)
        out_dir = tmp_path / "art"
        r = runner.invoke(self._app(), [
            "digest", "--root", str(tmp_path), "--out-dir", str(out_dir)])
        assert r.exit_code == 0, r.output
        assert "共 1 战役终态" in r.output
        assert "wilkinson ✓ 完成" in r.output
        assert "digest_" in r.output  # 产物路径在打印面
        assert list(out_dir.glob("digest_*.json"))
        assert list(out_dir.glob("digest_*.txt"))

    def test_json_envelope(self, tmp_path):
        self._camp(tmp_path)
        r = runner.invoke(self._app(), [
            "digest", "--root", str(tmp_path), "--no-write", "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["ok"] is True
        assert payload["n_campaigns"] == 1
        assert payload["counts"]["COMPLETE"] == 1
        assert "artifacts" not in payload

    def test_json_failure_same_shape(self, tmp_path):
        r = runner.invoke(self._app(), [
            "digest", "--root", str(tmp_path), "--since-h", "-1", "--json"])
        assert r.exit_code != 0
        payload = json.loads(r.output)
        assert payload["ok"] is False
        assert isinstance(payload["errors"], list)

    def test_since_h_option_wiring(self, tmp_path):
        d = self._camp(tmp_path)
        old = time.time() - 48 * 3600
        os.utime(d / "campaign.plan.json", (old, old))
        r = runner.invoke(self._app(), [
            "digest", "--root", str(tmp_path), "--since-h", "24",
            "--no-write", "--json"])
        assert r.exit_code == 0, r.output
        assert json.loads(r.output)["n_campaigns"] == 0

    def test_root_app_reexport_identity(self):
        """bands_uq 薄壳 re-export 与 domain 模块同一对象（UX-B6 契约延伸）。"""
        from rfauto.cli.domains import bands_uq
        from rfauto.cli.domains import campaign as camp_mod

        assert bands_uq.campaign_digest_cmd is camp_mod.campaign_digest_cmd
        assert self._app() is camp_mod.campaign_app


if __name__ == "__main__":
    raise SystemExit(__import__("pytest").main([__file__, "-q"]))
