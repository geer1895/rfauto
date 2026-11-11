"""R-09 capture 面单测——会话捕获→配方草稿编译（aurora_r C3）。

钉住：
1. 端到端：录制（run_once/set_param/eval）→编译→草稿只落 runs/recipe_sandbox/
   沙箱 + 模板名/参数轨迹/最终参数集提取正确；
2. 守卫负例：沙箱根指向受保护 recipes/（含 #318 normcase 大小写变体）、
   草稿名 ``..`` 越界、绝对路径越界、非法后缀；
3. 录制负例：未知 kind fail-closed（会话零增行）、set_param 缺 value
   （#364：value=0 合法、键缺席才拒）、非法/不存在会话 id、重名会话；
4. 编译负例：空会话/损坏 JSONL（行号点名）/手工构造未知 kind（防御纵深）
   /无 model/template 可言/会话 id 穿越形态；
5. 诚实草稿：未推断段 ``# capture-draft: <段> 未能从会话推断`` 如实出现；
   payload 携带 setup 时该段被吸收不标注；
6. 零变化缺省：不调用就不落盘。

全部用例 isolated_cache_off（chdir tmp，#144：runs 面产物不污染真实 runs/）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

from rfauto.service import capture_service as cs


@pytest.fixture(autouse=True)
def _isolated(isolated_cache_off):
    """chdir tmp 隔离（#144）：会话与草稿产物落 tmp runs/，不污染真实 runs/。"""
    yield


def _tmp_runs() -> Path:
    return Path.cwd() / "runs"


def _start_with_action(name: str) -> str:
    """起一个已含一条可编译动作（带 model+params）的会话，返回会话 id。"""
    started = cs.start_capture(name)
    assert started["ok"], started
    sid = started["session_id"]
    r = cs.record_action(
        sid, "run_once",
        {"recipe_path": "recipes/branchline_v1.yaml",
         "model": "branchline_coupler",
         "params": {"arm_len_mm": 20.5, "series_w_mm": 1.87}})
    assert r["ok"], r
    return sid


# ─── 1. 端到端 ────────────────────────────────────────────────────────────────


class TestEndToEnd:
    def test_capture_compile_end_to_end(self):
        started = cs.start_capture("e2e_demo")
        assert started["ok"] is True, started
        sid = started["session_id"]
        session_path = Path(started["path"])
        assert session_path.exists()
        assert session_path.parent == _tmp_runs() / "capture_sessions"

        r1 = cs.record_action(sid, "run_once", {
            "recipe_path": "recipes/branchline_v1.yaml",
            "model": "branchline_coupler",
            "params": {"arm_len_mm": 20.5, "series_w_mm": 1.87}})
        assert r1["ok"] is True and r1["seq"] == 0
        r2 = cs.record_action(sid, "set_param", {"key": "arm_len_mm", "value": 21.25})
        assert r2["ok"] is True and r2["seq"] == 1
        r3 = cs.record_action(sid, "eval", {
            "model": "branchline_coupler",
            "params": {"arm_len_mm": 21.25, "series_w_mm": 1.87, "shunt_w_mm": 1.11}})
        assert r3["ok"] is True

        stopped = cs.stop_capture(sid)
        assert stopped["ok"] is True
        assert stopped["already_stopped"] is False
        assert stopped["actions"] == 3
        assert stopped["kinds"] == {"run_once": 1, "set_param": 1, "eval": 1}

        out = cs.compile_capture(sid)
        assert out["ok"] is True, out
        draft = Path(out["draft"])
        assert draft.exists()
        # 草稿只落沙箱（runs/recipe_sandbox），生产 recipes/ 零写入
        assert os.path.normcase(str(draft.parent)) == os.path.normcase(
            str(_tmp_runs() / "recipe_sandbox"))
        assert not (_tmp_runs() / "recipes").exists()
        assert draft.name == f"capture_{sid}.yaml"

        data = yaml.safe_load(draft.read_text(encoding="utf-8"))
        assert data["model"] == "branchline_coupler"
        assert data["recipe_version"] == 1
        assert data["params"]["arm_len_mm"] == 21.25  # set_param 覆盖生效
        assert data["params"]["series_w_mm"] == 1.87
        assert data["params"]["shunt_w_mm"] == 1.11  # eval 快照并入
        assert "三层 Gate" in data["notes"]

        # 诚实草稿：未推断段如实标注（#324：注释只占独立行）
        text = draft.read_text(encoding="utf-8")
        for sec in ("setup", "objectives", "optimization"):
            assert f"# capture-draft: {sec} 未能从会话推断" in text
        assert out["uninferred"] == ["setup", "objectives", "optimization"]
        # 参数轨迹与初始/最终参数集
        assert out["param_trajectory"] == {
            "arm_len_mm": [{"seq": 1, "value": 21.25}]}
        assert out["params_initial"] == {"arm_len_mm": 20.5, "series_w_mm": 1.87}
        assert out["params"] == data["params"]

    def test_compile_by_explicit_jsonl_path(self):
        sid = _start_with_action("by_path")
        session_path = cs._sessions_dir() / f"{sid}.jsonl"
        out = cs.compile_capture(session_path, draft_name="by_path_draft.yaml")
        assert out["ok"] is True, out
        assert Path(out["draft"]).name == "by_path_draft.yaml"
        assert out["session_id"] == sid

    def test_set_param_falsy_value_zero_is_legal(self):
        # #364：value=0 是合法值，判缺用 in 不用真值
        sid = _start_with_action("falsy_zero")
        r = cs.record_action(sid, "set_param", {"key": "gap_mm", "value": 0})
        assert r["ok"] is True, r
        out = cs.compile_capture(sid)
        assert out["ok"] is True, out
        assert out["params"]["gap_mm"] == 0

    def test_payload_setup_section_absorbed_not_annotated(self):
        started = cs.start_capture("setup_absorbed")
        sid = started["session_id"]
        r = cs.record_action(sid, "run_once", {
            "model": "branchline_coupler",
            "params": {"arm_len_mm": 20.5},
            "setup": {"solver": "openEMS", "freq_range_ghz": [2.3, 2.5],
                      "points": 201}})
        assert r["ok"] is True, r
        out = cs.compile_capture(sid)
        assert out["ok"] is True, out
        text = Path(out["draft"]).read_text(encoding="utf-8")
        assert "# capture-draft: setup 未能从会话推断" not in text
        assert out["uninferred"] == ["objectives", "optimization"]
        data = yaml.safe_load(text)
        assert data["setup"]["solver"] == "openEMS"


# ─── 2. 守卫负例（#318 normcase 口径）────────────────────────────────────────


class TestGuardNegatives:
    def test_sandbox_root_under_recipes_rejected(self):
        # cwd 相对受保护根 <cwd>/recipes（recipe_guard 根①，存在与否都受保护）
        sid = _start_with_action("guard_recipes_sub")
        recipes_root = Path.cwd() / "recipes"
        recipes_root.mkdir()
        out = cs.compile_capture(sid, sandbox_root=str(recipes_root / "sub"))
        assert out["ok"] is False
        assert any("recipes" in e for e in out["errors"])
        assert not list(recipes_root.rglob("capture_*"))  # 生产区零落盘

    def test_sandbox_root_case_variant_rejected(self):
        # #318：保护根判定必须大小写不敏感（normcase+casefold，POSIX 亦然）
        sid = _start_with_action("guard_recipes_case")
        out = cs.compile_capture(sid, sandbox_root=str(Path.cwd() / "RECIPES"))
        assert out["ok"] is False
        assert any("recipes" in e for e in out["errors"])

    def test_sandbox_root_repo_recipes_rejected(self):
        # 仓库真实生产区（recipe_guard 根②：由 __file__ 推导，chdir 后仍受保护）
        repo_recipes = Path(__file__).resolve().parents[2] / "recipes"
        sid = _start_with_action("guard_recipes_repo")
        out = cs.compile_capture(sid, sandbox_root=str(repo_recipes))
        assert out["ok"] is False
        assert any("recipes" in e for e in out["errors"])
        assert not list(repo_recipes.glob("capture_*"))  # 生产区零落盘

    def test_draft_name_escape_rejected(self):
        sid = _start_with_action("guard_escape")
        out = cs.compile_capture(sid, draft_name="../outside.yaml")
        assert out["ok"] is False
        assert any("越出沙箱" in e for e in out["errors"])

    def test_draft_name_absolute_outside_rejected(self, tmp_path):
        sid = _start_with_action("guard_abs")
        out = cs.compile_capture(sid, draft_name=str(tmp_path / "elsewhere.yaml"))
        assert out["ok"] is False
        assert any("越出沙箱" in e for e in out["errors"])

    def test_draft_suffix_whitelist_rejected(self):
        sid = _start_with_action("guard_suffix")
        out = cs.compile_capture(sid, draft_name="evil.py")
        assert out["ok"] is False
        assert any("后缀" in e for e in out["errors"])

    def test_session_id_traversal_rejected(self):
        out = cs.compile_capture("../../escape_targets")
        assert out["ok"] is False
        assert any("非法会话" in e for e in out["errors"])


# ─── 3. 录制负例（fail-closed）───────────────────────────────────────────────


class TestRecorderNegatives:
    def test_unknown_kind_rejected_and_session_unchanged(self):
        started = cs.start_capture("neg_kind")
        sid = started["session_id"]
        out = cs.record_action(sid, "solve", {"x": 1})
        assert out["ok"] is False
        assert any("kind" in e for e in out["errors"])
        lines = [ln for ln in Path(started["path"]).read_text(
            encoding="utf-8").splitlines() if ln.strip()]
        assert len(lines) == 1  # 只有 session_start，未知 kind 零落盘

    def test_set_param_missing_value_rejected(self):
        sid = _start_with_action("neg_no_value")
        out = cs.record_action(sid, "set_param", {"key": "arm_len_mm"})
        assert out["ok"] is False
        assert any("value" in e for e in out["errors"])

    def test_set_param_missing_key_rejected(self):
        sid = _start_with_action("neg_no_key")
        out = cs.record_action(sid, "set_param", {"value": 1.0})
        assert out["ok"] is False
        assert any("key" in e for e in out["errors"])

    def test_record_into_unknown_session_rejected(self):
        out = cs.record_action("no_such_session", "run_once", {})
        assert out["ok"] is False
        assert any("不存在" in e for e in out["errors"])

    def test_start_capture_duplicate_name_rejected(self):
        first = cs.start_capture("dup_session")
        assert first["ok"] is True
        second = cs.start_capture("dup_session")
        assert second["ok"] is False
        assert any("已存在" in e for e in second["errors"])

    def test_start_capture_bad_name_rejected(self):
        for bad in ("../evil", "a/b", "", ".hidden"):
            out = cs.start_capture(bad)
            assert out["ok"] is False, bad
            assert any("非法会话名" in e for e in out["errors"]), bad

    def test_stop_capture_idempotent(self):
        sid = _start_with_action("stop_twice")
        first = cs.stop_capture(sid)
        assert first["ok"] is True and first["already_stopped"] is False
        second = cs.stop_capture(sid)
        assert second["ok"] is True and second["already_stopped"] is True
        assert second["actions"] == 1


# ─── 4. 编译负例 ─────────────────────────────────────────────────────────────


class TestCompilerNegatives:
    def test_empty_session_rejected(self):
        started = cs.start_capture("neg_empty")
        sid = started["session_id"]
        stopped = cs.stop_capture(sid)
        assert stopped["ok"] is True
        out = cs.compile_capture(sid)
        assert out["ok"] is False
        assert any("无动作" in e for e in out["errors"])

    def test_corrupt_jsonl_rejected_with_line_number(self):
        started = cs.start_capture("neg_corrupt")
        sid = started["session_id"]
        assert cs.record_action(
            sid, "run_once",
            {"model": "branchline_coupler", "params": {"a": 1}})["ok"]
        path = Path(started["path"])
        path.write_text(
            path.read_text(encoding="utf-8") + "{not-json\n", encoding="utf-8")
        out = cs.compile_capture(sid)
        assert out["ok"] is False
        assert any("损坏" in e for e in out["errors"])
        assert any("第" in e and "行" in e for e in out["errors"])  # 行号点名

    def test_hand_crafted_unknown_kind_rejected(self):
        # 防御纵深：录制端已 fail-closed，编译端对文件面再验（手工构造）
        started = cs.start_capture("neg_handkind")
        sid = started["session_id"]
        rec = {"schema": cs.CAPTURE_SCHEMA, "record": "action", "seq": 0,
               "ts": "2026-11-10T00:00:00+0800", "kind": "solve", "payload": {}}
        path = Path(started["path"])
        path.write_text(
            path.read_text(encoding="utf-8") + json.dumps(rec) + "\n",
            encoding="utf-8")
        out = cs.compile_capture(sid)
        assert out["ok"] is False
        assert any("不支持" in e for e in out["errors"])

    def test_no_model_or_template_rejected(self):
        started = cs.start_capture("neg_nomodel")
        sid = started["session_id"]
        assert cs.record_action(sid, "set_param", {"key": "a", "value": 1})["ok"]
        out = cs.compile_capture(sid)
        assert out["ok"] is False
        assert any("模型/模板" in e for e in out["errors"])

    def test_model_and_template_ambiguous_rejected(self):
        started = cs.start_capture("neg_ambiguous")
        sid = started["session_id"]
        assert cs.record_action(sid, "eval", {
            "model": "branchline_coupler", "template": "branchline",
            "params": {"a": 1}})["ok"]
        out = cs.compile_capture(sid)
        assert out["ok"] is False
        assert any("互斥" in e for e in out["errors"])


# ─── 5. 零变化缺省 ───────────────────────────────────────────────────────────


class TestDefaultNoSideEffects:
    def test_no_writes_without_calls(self):
        # 不调用就不落盘：模块 import 无副作用，会话/沙箱目录均未被创建
        assert not (_tmp_runs() / "capture_sessions").exists()
        assert not (_tmp_runs() / "recipe_sandbox").exists()
        assert not (_tmp_runs() / "recipes").exists()
