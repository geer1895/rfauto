"""X2 席回归钉（PR-6 座位状态表 + PR-8 CLI profile 入口，2026-10-04）。

覆盖三面：
- PR-6 页面装配钉：战役仪表盘视图/导航/注册序（test_campaign_queue_ui
  的 TestQueuePage 同款静态装配钉）；
- AU-4 esc 抽查钉：trial 虚拟列表 trial_number 必须 esc（#320 导入面
  外来数据可达 XSP 面）；座位状态表数字经 esc/badge 单点转义；
- PR-8 CLI 面：profile status/run 注册 + CliRunner 冒烟（service 层
  monkeypatch stub，与 test_profile_service 同款——py-spy 本机缺装也全绿）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from rfauto.cli.profile_app import profile_app
from rfauto.service import profile_service as ps

_PAGES_JS = (
    Path(__file__).resolve().parents[2]
    / "src" / "rfauto" / "ui" / "static" / "pages.js"
).read_text(encoding="utf-8")


# ── PR-6 战役仪表盘页装配钉 ──────────────────────────────────────────────


class TestCampaignPageAssembly:
    def test_index_serves_campaign_view(self):
        html = client_index_html()
        assert 'id="view-campaign"' in html and 'data-v="campaign"' in html

    def test_pages_js_registers_campaign(self):
        assert "campaign: pageCampaign" in _PAGES_JS
        assert "async function pageCampaign()" in _PAGES_JS

    def test_seat_status_table_markup_present(self):
        # X2 v1：座位状态表（PASS/SKIP/FAIL 分色）= 真 <table> 标记
        # （语义化表格：无 JS 交互/读屏/复制场景仍逐格可读）
        assert 'cp-seats' in _PAGES_JS
        assert '<th>座位状态</th>' in _PAGES_JS
        assert 'T.badge("PASS", "ok")' in _PAGES_JS
        assert 'T.badge("SKIP", skipped ? "warn" : "muted")' in _PAGES_JS
        assert 'T.badge("FAIL", "err")' in _PAGES_JS

    def test_seat_numbers_go_through_esc(self):
        # AU-4：座位表计数是 API 数据插值——必须经 esc（badge 自身单点转义）
        assert 'esc(d.n_trials_used)' in _PAGES_JS
        assert 'esc(skipped)' in _PAGES_JS
        assert 'esc((d.errors || []).join("; "))' in _PAGES_JS

    def test_trial_number_in_virtual_list_escaped(self):
        # XSS 抽查钉：trial_number 出自 runs/ trials 审计（#320 导入面
        # 外来数据可达），此前裸插值是逃逸面——必须 esc
        assert 'esc(rows[i].trial_number)' in _PAGES_JS
        # 进度条走 textContent（无 innerHTML 插值面）
        assert '座位进度' in _PAGES_JS

    def test_profile_page_registered(self):
        # PR-8 UI 页（ge8b 席B2 已落）：装配钉防静默丢失
        assert 'id="view-profile"' in client_index_html()
        assert "profile: pageProfile" in _PAGES_JS
        assert "async function pageProfile()" in _PAGES_JS


def client_index_html() -> str:
    from starlette.testclient import TestClient

    from rfauto.ui.server import create_ui_app

    return TestClient(create_ui_app()).get("/").text


# ── PR-8 CLI profile 入口 ────────────────────────────────────────────────


@pytest.fixture()
def fake_pyspy(monkeypatch, tmp_path):
    """py-spy 在位 + subprocess 捕获（不真跑；stub 落盘模拟 py-spy 写文件）。"""
    monkeypatch.setattr(ps.shutil, "which", lambda name: r"E:\tools\py-spy.exe")
    calls = {}

    def fake_run(argv, **kwargs):
        calls["argv"] = argv
        out = argv[argv.index("-o") + 1]
        ps.Path(out).write_bytes(b"flamegraph-stub")
        from types import SimpleNamespace

        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(ps.subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)
    return calls


class TestProfileCli:
    def test_registered_in_main_app(self):
        # 注册面实测（#97）：main app 里 profile 子应用 status/run 两叶
        from typer.main import get_command

        from rfauto.cli.main import app

        root = get_command(app)
        assert "profile" in root.commands
        sub = root.commands["profile"]
        assert set(sub.commands) == {"status", "run"}

    def test_status_available_exit0(self, fake_pyspy):
        r = CliRunner().invoke(profile_app, ["status"])
        assert r.exit_code == 0
        assert '"available": true' in r.output

    def test_status_missing_is_honest_exit0(self, monkeypatch):
        # 探测是信息面不是门：缺装也是 exit 0 + 安装提示（不假红）
        monkeypatch.setattr(ps.shutil, "which", lambda name: None)
        r = CliRunner().invoke(profile_app, ["status"])
        assert r.exit_code == 0
        assert '"available": false' in r.output and "pip install py-spy" in r.output

    def test_run_cmd_whitespace_split(self, fake_pyspy):
        r = CliRunner().invoke(profile_app, [
            "run", "--cmd", "python scripts/x.py --flag", "--duration", "5"])
        assert r.exit_code == 0, r.output
        argv = fake_pyspy["argv"]
        assert "--" in argv and argv[argv.index("--") + 1:] == [
            "python", "scripts/x.py", "--flag"]
        assert '"ok": true' in r.output and "pyspy_python-scripts-x.py---flag.svg" in r.output

    def test_run_pid_target(self, fake_pyspy):
        r = CliRunner().invoke(profile_app, [
            "run", "--pid", "4242", "--duration", "5", "--rate", "200"])
        assert r.exit_code == 0, r.output
        argv = fake_pyspy["argv"]
        assert argv[argv.index("--pid") + 1] == "4242"

    def test_run_invalid_target_exit1(self, fake_pyspy):
        # pid/cmd 都缺=显错（服务层信封）→ 门色退出码 1
        r = CliRunner().invoke(profile_app, ["run", "--duration", "5"])
        assert r.exit_code == 1
        assert '"ok": false' in r.output and "二选一" in r.output
