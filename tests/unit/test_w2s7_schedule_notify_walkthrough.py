"""W2-S7 收尾走查钉：调度/选机/digest/依赖四面的可发现性与 env 接线.

走查结论的补钉面（语义测试 W2-S5/S6/W3-S3 已覆盖，不重复）：
- **help 可发现性**：digest --notify 的 help 必须点名两个 webhook env 键；
  queue-daemon 的 help 必须点名对冲两 env 键（配置全走 env，help 是唯一
  发现入口）；remote resources 的 help 必须提 recommend 块；help 不回潮
  内部账本词（#277 坑号/同口径）；help 引用的 how-to 文档必须真实存在；
- **env→tick 生产接线**：W3-S3 的对冲触发链测试全部显式传参，这里补
  "只设 env 不传参"的缺省分支钉（走 _resolve_hedge_cfg env 分支）；
- **CLI recommend 附着**：remote resources --json 信封带 recommend 块
  （本地模式=无登记机器，eligible=False 如实排除态）。

全 fake 零网络零真机；env 全集清理照 S6 autouse 形态（同名前缀整清）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.main import get_command
from typer.testing import CliRunner

from rfauto.cli.main import app as root_app
from rfauto.service.campaign_notify_service import (
    NOTIFY_FEISHU_WEBHOOK_ENV,
    NOTIFY_TIMEOUT_S_ENV,
    NOTIFY_WEBHOOK_URL_ENV,
)
from rfauto.service.campaign_queue_daemon import (
    HEDGE_CODE_STALL,
    HEDGE_RELAUNCH_ENV,
    HEDGE_STALL_S_ENV,
    ITEM_LAUNCHED,
    item_id_of,
    queue_tick,
)

runner = CliRunner()

_WALKTHROUGH_ENV_KEYS = (
    HEDGE_STALL_S_ENV,
    HEDGE_RELAUNCH_ENV,
    NOTIFY_WEBHOOK_URL_ENV,
    NOTIFY_FEISHU_WEBHOOK_ENV,
    NOTIFY_TIMEOUT_S_ENV,
)


@pytest.fixture(autouse=True)
def _clean_walkthrough_env(monkeypatch):
    """确定性前提：本面 env 全集清理（对冲两键+通知三键）。"""
    for k in _WALKTHROUGH_ENV_KEYS:
        monkeypatch.delenv(k, raising=False)


# ─── help 可发现性（click 树读 help 原文，避开 rich 渲染截断）───────────────

_HOWTO = "docs/how-to/campaign-queue-and-notify.md"


def _click_cmd(*path: str):
    """根 app → click 树逐级取命令（#354：typer 内嵌 click，鸭子树遍历稳）。"""
    node = get_command(root_app)
    for part in path:
        node = node.commands[part]
    return node


def _param_help(cmd, opts: tuple[str, ...]) -> str:
    for p in getattr(cmd, "params", None) or []:
        if set(opts) & set(getattr(p, "opts", ())):
            return str(getattr(p, "help", "") or "")
    return ""


class TestHelpDiscoverability:
    def test_digest_notify_help_names_both_webhook_env_keys(self):
        cmd = _click_cmd("campaign", "digest")
        help_text = _param_help(cmd, ("--notify", "--no-notify"))
        assert "RFAUTO_NOTIFY_WEBHOOK_URL" in help_text
        assert "RFAUTO_NOTIFY_FEISHU_WEBHOOK" in help_text
        # W5-S20 文案审查迁移：原钉"零网络"随 help 改写（两括号合并+
        # 去内部口径词）换为用户视角语义钉——两键均未设即关。
        assert "未设即关" in help_text

    def test_queue_daemon_help_names_hedge_env_keys(self):
        help_text = str(_click_cmd("campaign", "queue-daemon").help or "")
        assert "RFAUTO_QUEUE_HEDGE_STALL_S" in help_text
        assert "RFAUTO_QUEUE_HEDGE_RELAUNCH" in help_text

    def test_remote_resources_help_mentions_recommend(self):
        help_text = str(_click_cmd("remote", "resources").help or "")
        assert "recommend" in help_text

    def test_walked_helps_carry_no_internal_ledger_words(self):
        """本席清理过的 help 不回潮内部账本词（坑号/同口径）。"""
        texts = [
            _param_help(_click_cmd("campaign", "digest"),
                        ("--notify", "--no-notify")),
            _param_help(_click_cmd("campaign", "queue-daemon"),
                        ("--license-gate", "--no-license-gate")),
            _click_cmd("campaign", "digest").help or "",
            _click_cmd("campaign", "queue-daemon").help or "",
            _click_cmd("remote", "resources").help or "",
        ]
        for t in texts:
            assert "#277" not in t
            assert "同口径" not in t

    def test_help_referenced_howto_doc_exists(self):
        """help 里的 how-to 指针不得是死链（文档改 path 时此钉先红）。"""
        repo = Path(__file__).resolve().parents[2]
        for cmd_path in (("campaign", "queue-daemon"),
                         ("remote", "resources")):
            help_text = str(_click_cmd(*cmd_path).help or "")
            if _HOWTO in help_text:
                assert (repo / _HOWTO).exists(), cmd_path


# ─── env→tick 生产接线（只设 env 不传参的缺省分支）───────────────────────────

_PLAN_A = r"E:\x\runs\camp_a\campaign.plan.json"


def _entry(plan_path: str, *, verdict: str = "") -> dict:
    return {"item_id": item_id_of(plan_path), "plan_path": plan_path,
            "model": "wilkinson", "verdict": verdict,
            "n_stages": 2, "license_gated": False}


def _cal() -> dict:
    return {"loaded": False, "state": "open", "launchable": True,
            "windows_hit": [], "reason": "fake calendar open"}


class _Launcher:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, plan_path: str) -> dict:
        self.calls.append(plan_path)
        return dict(ok=True, pid=100 + len(self.calls), cmdline=["fake"],
                    log_path=plan_path + ".log")


def _probe(ts: float | None):
    return lambda plan_path: ts


def _drive_to_inflight(launcher: _Launcher):
    """T1 发射 → 返回 state（项在途）。"""
    _, state = queue_tick(
        None, now_fn=lambda: 100.0, calendar_fn=_cal,
        preflight_fn=lambda m: {"ok": True, "verdict": "PASS"},
        queue_fn=lambda root: [_entry(_PLAN_A)], launcher_fn=launcher,
        failure_context_fn=None)
    return state


class TestHedgeEnvWiring:
    """queue_tick 不带 hedge 参数、只设 env：配置经 _resolve_hedge_cfg 生效。"""

    def _second_tick(self, state, launcher, ts: float):
        return queue_tick(
            state, now_fn=lambda: 1000.0, calendar_fn=_cal,
            preflight_fn=lambda m: {"ok": True, "verdict": "PASS"},
            queue_fn=lambda root: [_entry(_PLAN_A, verdict="RUNNING")],
            launcher_fn=launcher, failure_context_fn=None,
            progress_fn=_probe(ts))

    def test_env_threshold_only_fires_alert_default_no_relaunch(
            self, monkeypatch):
        monkeypatch.setenv(HEDGE_STALL_S_ENV, "100")
        launcher = _Launcher()
        state = _drive_to_inflight(launcher)
        actions, state = self._second_tick(state, launcher, ts=100.0)
        # 停滞 900 ≥ env 阈值 100 → 告警+落账；重发开关未设 → 只告警
        assert any(a.get("action") == "hedge_alert" for a in actions)
        assert launcher.calls == [_PLAN_A]
        rec = state["items"][item_id_of(_PLAN_A)]
        assert rec["status"] == ITEM_LAUNCHED
        assert rec["hedge"]["code"] == HEDGE_CODE_STALL

    def test_env_threshold_and_relaunch_fire_one_relaunch(self, monkeypatch):
        monkeypatch.setenv(HEDGE_STALL_S_ENV, "1")
        monkeypatch.setenv(HEDGE_RELAUNCH_ENV, "1")
        launcher = _Launcher()
        state = _drive_to_inflight(launcher)
        actions, _state = self._second_tick(state, launcher, ts=0.0)
        assert any(a.get("action") == "hedge_relaunch" for a in actions)
        assert launcher.calls == [_PLAN_A, _PLAN_A]  # 首发+对冲重发一次

    def test_env_unset_stays_off_zero_probe_calls(self, monkeypatch):
        monkeypatch.delenv(HEDGE_STALL_S_ENV, raising=False)
        monkeypatch.delenv(HEDGE_RELAUNCH_ENV, raising=False)
        launcher = _Launcher()
        state = _drive_to_inflight(launcher)
        probe_calls = {"n": 0}

        def probe(plan_path: str) -> float | None:
            probe_calls["n"] += 1
            return 0.0

        actions, state = queue_tick(
            state, now_fn=lambda: 1000.0, calendar_fn=_cal,
            preflight_fn=lambda m: {"ok": True, "verdict": "PASS"},
            queue_fn=lambda root: [_entry(_PLAN_A, verdict="RUNNING")],
            launcher_fn=launcher, failure_context_fn=None, progress_fn=probe)
        # 缺省关硬验收：探针零调用、动作零 hedge_*、账面零对冲字段
        assert probe_calls["n"] == 0
        assert not [a for a in actions
                    if str(a.get("action", "")).startswith("hedge")]
        rec = state["items"][item_id_of(_PLAN_A)]
        assert "hedge" not in rec and "hedge_attempts" not in rec


# ─── CLI recommend 附着（remote resources --json）───────────────────────────

class TestCliRecommendSurface:
    def test_resources_json_carries_recommend_block(self, monkeypatch):
        from rfauto.service import remote_scheduler_service as rss

        # 真实离线路径（零登记+进程 census 桩，同既有 offline-real 形态）
        monkeypatch.setattr(rss, "load_remote_machines", lambda: {})
        monkeypatch.setattr(rss, "_ps_capture",
                            lambda cmd, timeout_s=30.0: (True, ""))
        monkeypatch.setattr(rss, "list_ansysedt_processes", lambda: [])
        r = runner.invoke(root_app, ["remote", "resources", "--json"])
        assert r.exit_code == 0, r.output[:400]
        payload = json.loads(r.output[r.output.index("{"):])
        # 本地模式（无登记机器）→ 排除态如实：eligible=False、不打分
        rec = payload["recommend"]
        assert rec["machine"] is None
        assert rec["eligible"] is False
        assert rec["score"] is None
        assert rec["excluded_by"]  # 排除原因清单非空
        assert rec["max_parallel"] == 1


if __name__ == "__main__":
    raise SystemExit(__import__("pytest").main([__file__, "-q"]))
