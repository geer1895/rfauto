"""runs/ 面双根收敛单源钉（R3-9，runs/review_ge8e/f3_fix/REPORT.md）。

infra/runs_paths.py 单源 + 三消费面（agent_sandbox/agent_runtime/
agent_safety）语义唯一确定：cwd 根优先、仓内子目录 chdir 收敛回仓库
runs/、tmp/新工作区落 cwd 不污染仓库。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.infra.runs_paths import resolve_runs_dir, runs_root

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_runs_root_cwd_priority_when_exists(tmp_path, monkeypatch):
    """cwd/runs 存在 → cwd 根（仓根运行与 tmp 两态不变）。"""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "runs").mkdir()
    assert runs_root() == tmp_path / "runs"


def test_runs_root_tmp_chdir_stays_tmp_not_repo(tmp_path, monkeypatch):
    """回归钉（R3-9 验收口径）：tmp chdir 下沙箱草稿落 tmp 而非仓 runs/。"""
    monkeypatch.chdir(tmp_path)
    assert runs_root() == tmp_path / "runs"
    from rfauto.service.agent_sandbox import RecipeSandbox

    sb = RecipeSandbox()
    assert sb.root == tmp_path / "runs" / "recipe_sandbox"
    recipe = tmp_path / "r.yaml"
    recipe.write_text("a: 1\n", encoding="utf-8")
    out = sb.stage(recipe)
    assert Path(out["draft"]).is_relative_to(tmp_path)
    assert (tmp_path / "runs" / "recipe_sandbox").exists()
    assert not (REPO_ROOT / "runs" / "recipe_sandbox"
                / Path(out["draft"]).name).exists()


def test_runs_root_repo_subdir_converges_to_repo_runs(monkeypatch):
    """chdir 进仓库 runs/ 子目录（#295 族驱动脚本场景）→ 收敛回仓库
    runs/，沙箱/会话/审计不再嵌套分叉到 <子目录>/runs/。只断言解析、
    零写入（仓库 runs/ 既有文件禁改）。"""
    runs_dir = REPO_ROOT / "runs"
    if not runs_dir.is_dir():
        pytest.skip("仓库 runs/ 不在场")
    monkeypatch.chdir(runs_dir)
    assert runs_root() == runs_dir
    assert (resolve_runs_dir(Path("runs") / "chat_sessions")
            == runs_dir / "chat_sessions")
    from rfauto.service.agent_safety import _resolved_audit_dir
    from rfauto.service.agent_sandbox import RecipeSandbox

    assert RecipeSandbox().root == runs_dir / "recipe_sandbox"
    assert _resolved_audit_dir() == runs_dir / "agent_proposals"


def test_sessions_dir_convergence_no_nested_runs(tmp_path, monkeypatch):
    """agent_runtime.persist_session 在仓内子目录 cwd 不再写 <cwd>/runs/。"""
    runs_dir = REPO_ROOT / "runs"
    if not runs_dir.is_dir():
        pytest.skip("仓库 runs/ 不在场")
    from rfauto.service import agent_runtime

    nested = runs_dir / "_r3_9_probe_nested"
    nested.mkdir(exist_ok=True)
    try:
        monkeypatch.chdir(nested)
        path = agent_runtime.persist_session(
            agent_runtime.new_session_doc("r39probe", {}))
        assert path == runs_dir / "chat_sessions" / "r39probe.json"
    finally:
        monkeypatch.chdir(tmp_path)
        # 任务毕必须清理（本测自建的探针目录与会话档）
        import contextlib
        with contextlib.suppress(OSError):
            (runs_dir / "chat_sessions" / "r39probe.json").unlink()
        with contextlib.suppress(OSError):
            nested.rmdir()


def test_resolve_runs_dir_absolute_passthrough(tmp_path):
    """显式绝对注入（测试/调用方）原样透传，不受收敛影响。"""
    assert resolve_runs_dir(tmp_path / "x") == tmp_path / "x"


# ─── S3 批 F-6/F-7：模板沙箱 / 会话挖掘 / 写白名单 / 战役仪表盘收敛钉 ─────────


def test_template_sandbox_root_converges_in_repo_subdir(monkeypatch):
    """F-6/S3：TemplateDraftSandbox 缺省根 chdir 仓内 runs/ 子目录时收敛回
    仓库 runs/（原 cwd 相对 .resolve() 会分叉到 <子目录>/runs）。只断言
    解析零写入。"""
    runs_dir = REPO_ROOT / "runs"
    if not runs_dir.is_dir():
        pytest.skip("仓库 runs/ 不在场")
    from rfauto.service.agent_sandbox import TemplateDraftSandbox

    monkeypatch.chdir(runs_dir)
    assert TemplateDraftSandbox().root == runs_dir / "template_sandbox"


def test_write_whitelist_root_converges_in_repo_subdir(monkeypatch, tmp_path):
    """F-6/S3：写路径白名单 runs 根与 runs_root() 同源——chdir 仓内 runs/
    子目录时白名单=仓库 runs/（旧 <cwd>/runs 形态下嵌套路径不再放行）。"""
    runs_dir = REPO_ROOT / "runs"
    if not runs_dir.is_dir():
        pytest.skip("仓库 runs/ 不在场")
    from rfauto.service.agent_safety import allowed_write_roots, check_write_paths

    recipe = tmp_path / "r.yaml"
    recipe.write_text("a: 1\n", encoding="utf-8")
    monkeypatch.chdir(runs_dir)
    roots = allowed_write_roots(recipe)
    assert roots[0] == runs_dir
    # 仓库 runs/ 下目标放行（旧 <cwd>/runs 白名单形态下该路径越界——
    # chdir runs/ 时旧根=runs_dir/runs，放行的是嵌套路径而非仓库 runs 本体）
    ok_guard = check_write_paths([str(runs_dir / "agent_proposals" / "p.yaml")],
                                 recipe)
    assert ok_guard["ok"], ok_guard["violations"]


def test_few_shot_default_root_converges_in_repo_subdir(monkeypatch, tmp_path):
    """F-6/S3：few_shot 缺省会话根 chdir 仓内 runs/ 子目录时收敛回仓库
    runs/chat_sessions（探针档自建自清，仓库资产零残留）。"""
    import contextlib
    import json as _json

    runs_dir = REPO_ROOT / "runs"
    if not runs_dir.is_dir():
        pytest.skip("仓库 runs/ 不在场")
    from rfauto.service import few_shot_service

    sessions = runs_dir / "chat_sessions"
    sessions.mkdir(exist_ok=True)
    probe = sessions / "_s3_f6_probe_session.json"
    doc = {
        "schema": "rfauto-chat-session-v1",
        "session_id": "_s3_f6_probe_session",
        "history": [{"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "done"}],
        "tool_calls": [{"action": "run_once"}],
        "stats": {"turns": 1},
    }
    probe.write_text(_json.dumps(doc), encoding="utf-8")
    try:
        monkeypatch.chdir(runs_dir)
        cands = few_shot_service.mine_session_candidates()
        assert any(c.get("id") == "_s3_f6_probe_session" for c in cands)
    finally:
        monkeypatch.chdir(tmp_path)
        with contextlib.suppress(OSError):
            probe.unlink()


def test_campaign_dashboard_runs_root_converges_in_repo_subdir(
        monkeypatch, tmp_path):
    """F-7/S3：campaign_dashboard 的 runs 根走双根收敛——chdir 仓内 runs/
    子目录时能读到仓库 runs/ 下探针 run（旧 cwd 相对会去 <子目录>/runs/
    找）。探针 run 自建自清。"""
    import contextlib
    import json as _json
    import shutil

    runs_dir = REPO_ROOT / "runs"
    if not runs_dir.is_dir():
        pytest.skip("仓库 runs/ 不在场")
    from rfauto.service.campaign_dashboard_service import campaign_dashboard

    probe_run = runs_dir / "_s3_f7_probe_run"
    trials_dir = probe_run / "trials"
    trials_dir.mkdir(parents=True, exist_ok=True)
    (trials_dir / "trial_0000.json").write_text(_json.dumps({
        "trial_number": 0, "params": {"w_mm": 0.5, "er": 2.2},
        "metrics": {}, "cost": 1.25}), encoding="utf-8")
    (trials_dir / "trial_0001.json").write_text(_json.dumps({
        "trial_number": 1, "params": {"w_mm": 0.8, "er": 2.4},
        "metrics": {}, "cost": 0.75}), encoding="utf-8")
    try:
        monkeypatch.chdir(runs_dir)
        r = campaign_dashboard("_s3_f7_probe_run")
        assert r["ok"], r.get("errors")
        assert r["n_trials_used"] == 2
        assert r["best"]["cost"] == 0.75
    finally:
        monkeypatch.chdir(tmp_path)
        with contextlib.suppress(OSError):
            shutil.rmtree(probe_run)
