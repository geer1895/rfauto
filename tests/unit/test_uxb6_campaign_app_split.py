"""UX-B6 campaign_app 独立冒烟门（2026-10-08，交接书尾程项 11 首件）.

campaign 的 app 面（typer 子应用，自 cli/domains/bands_uq.py 迁
cli/domains/campaign.py）与 UI 面（PR-6/PR-9 三 handler，自 ui/server.py
迁 ui/campaign_app.py）独立成模块后钉住三件事：

1. 新模块 import 面：命令五件齐、handler 协程签名；
2. 薄壳 re-export 契约：bands_uq/server 既有消费方拿到的与
   新模块同一对象（is 同一性，main.py 导入路径零破坏）；
3. 注册序零漂移：``app.add_typer`` 留在 bands_uq 原位——campaign 组
   在 click 树 top_level 序中紧随 bands、先于 template-spec
   （tests/gold/cli_registration_order.json 全量序由该门另测，
   此处钉相邻关系防回潮）。
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest
import typer

src_dir = Path(__file__).resolve().parents[2] / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

# UX-B7 +1（2026-10-08：queue-daemon 队列常驻执行体叶，campaign 域内追加
# ——本常量为 campaign 组命令集钉面，随新叶同笔扩展）。
_CLI_COMMANDS = ["event", "list", "plan", "queue-daemon", "run", "status"]


def test_cli_campaign_app_module_structure() -> None:
    from rfauto.cli.domains import campaign as camp_mod

    assert isinstance(camp_mod.campaign_app, typer.Typer)
    got = sorted(c.name for c in camp_mod.campaign_app.registered_commands)
    assert got == _CLI_COMMANDS
    # 注册面同一性：root app 名下 "campaign" 组就是新模块定义的对象
    from rfauto.cli.main import app as root_app

    grp = next(g for g in root_app.registered_groups if g.name == "campaign")
    inst = getattr(grp, "typer_instance", None) or grp
    assert inst is camp_mod.campaign_app


def test_cli_thin_shell_reexport_identity() -> None:
    from rfauto.cli.domains import bands_uq
    from rfauto.cli.domains import campaign as camp_mod

    assert bands_uq.campaign_app is camp_mod.campaign_app
    for name in ("campaign_plan_cmd", "campaign_status_cmd",
                 "campaign_event_cmd", "campaign_list_cmd",
                 "campaign_run_cmd"):
        assert getattr(bands_uq, name) is getattr(camp_mod, name)


def test_campaign_group_neighbors_unchanged() -> None:
    """注册位零漂移：campaign 组紧随 bands、先于 template-spec。"""
    from rfauto.cli.main import app as root_app

    order = [g.name for g in root_app.registered_groups]
    i = order.index("campaign")
    assert order[i - 1] == "bands"
    assert order[i + 1] == "template-spec"
    grp = root_app.registered_groups[i]
    inst = getattr(grp, "typer_instance", None) or grp
    got = sorted(c.name for c in inst.registered_commands)
    assert got == _CLI_COMMANDS


def test_ui_campaign_app_module_structure() -> None:
    from rfauto.ui import campaign_app as ui_camp

    assert inspect.iscoroutinefunction(ui_camp.api_campaign_dashboard)
    assert inspect.iscoroutinefunction(ui_camp.api_campaign_queue)
    assert ui_camp._REMOTE_MTLS_NOTE  # PR-9 mTLS 如实登记注记在位


def test_ui_thin_shell_reexport_identity() -> None:
    from rfauto.ui import campaign_app as ui_camp
    from rfauto.ui import server

    assert server.api_campaign_dashboard is ui_camp.api_campaign_dashboard
    assert server.api_campaign_queue is ui_camp.api_campaign_queue


def test_campaign_remote_block_pure_call() -> None:
    """纯函数冒烟：_campaign_remote_block 形状契约（未登记机器降级面）。"""
    from rfauto.ui.campaign_app import _REMOTE_MTLS_NOTE, _campaign_remote_block

    plan = {"stages": [
        {"stage": "calibrate", "adapter": "openems", "license_gated": False},
        {"stage": "final_verify", "adapter": "hfss", "license_gated": True},
    ]}
    block = _campaign_remote_block(plan, "__uxb6_no_such_machine__")
    assert block["machine"] == "__uxb6_no_such_machine__"
    assert block["stage_candidates"] == ["final_verify"]
    assert block["mtls"] == _REMOTE_MTLS_NOTE


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
