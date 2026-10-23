"""aurora_j W2-S6：campaign digest webhook 推送通道测试（全合成零真网络）。

判据（任务书）：
①未配置（两通道 env 均未设）→ skipped，零网络零行为（缺省关证明）；
②通用+飞书两形态 payload 钉（注入 fake opener，禁真网络）；
③白名单构造零敏感钉：含敏感字段假输入（盘符路径/IP/凭据/本地 txt 正文）
  → payload 一概不含，只出聚合白名单字段；
④超时/非 2xx/任意异常 → 降级 ok=False 信封，绝不抛出（#105）；
⑤digest 集成：notify 失败/抛异常 digest 主产物照旧 ok，结果记 notify
  字段+notes 一行；--no-notify 显式关优先于 env；write=False 零推送；
⑥CLI --notify 三态缺省关冒烟（CliRunner，网络面 monkeypatch）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

# 规范注册序锁定（同 test_campaign_digest.py 口径：本文件字母序 <
# test_cli.py < test_cli_registration_order.py——模块面先导 cli.main 按
# 规范序完成全部域注册，CLI 冒烟内的域模块惰性导入缓存命中零序漂移）。
from rfauto.cli.main import app as _cli_root_app  # noqa: F401
from rfauto.service.campaign_digest_service import campaign_digest
from rfauto.service.campaign_notify_service import (
    NOTIFY_FEISHU_WEBHOOK_ENV,
    NOTIFY_TIMEOUT_S_DEFAULT,
    NOTIFY_TIMEOUT_S_ENV,
    NOTIFY_WEBHOOK_URL_ENV,
    build_digest_payload,
    notify_config,
    notify_digest,
)

runner = CliRunner()

_NOTIFY_ENV_KEYS = (NOTIFY_WEBHOOK_URL_ENV, NOTIFY_FEISHU_WEBHOOK_ENV,
                    NOTIFY_TIMEOUT_S_ENV)


@pytest.fixture(autouse=True)
def _clean_notify_env(monkeypatch):
    """确定性前提：清空本面同名 env 全集（三键整集清，不只清用例自己 set 的）。"""
    for k in _NOTIFY_ENV_KEYS:
        monkeypatch.delenv(k, raising=False)


class _FakeOpener:
    """假网络面（opener 注入缝）：记录调用并回预设状态码/异常——零真网络。"""

    def __init__(self, status: int = 200, exc: Exception | None = None):
        self.calls: list[dict] = []
        self.status = status
        self.exc = exc

    def __call__(self, url: str, payload: dict, timeout_s: float) -> int:
        self.calls.append(
            {"url": url, "payload": payload, "timeout_s": timeout_s})
        if self.exc is not None:
            raise self.exc
        return self.status


def _digest() -> dict:
    """合成 digest 信封（含敏感字段假输入：盘符路径/凭据——payload 必不含）。"""
    return {
        "ok": True,
        "root": "E:\\rf_local_work\\runs",
        "generated_at": "2026-10-23 10:00:00",
        "n_campaigns": 3,
        "counts": {"COMPLETE": 2, "PARTIAL": 0, "ABORTED": 1},
        "campaigns": [
            {"name": "camp_a", "model": "wilkinson", "verdict": "COMPLETE",
             "verdict_zh": "完成", "mark": "✓", "n_done": 6, "n_stages": 6,
             "path": "E:\\rf_local_work\\runs\\camp_a\\campaign.plan.json",
             "reason": ""},
            {"name": "camp_b", "model": "vivaldi", "verdict": "COMPLETE",
             "verdict_zh": "完成", "mark": "✓", "n_done": 5, "n_stages": 6,
             "path": "E:\\rf_local_work\\runs\\camp_b\\campaign.plan.json",
             "reason": ""},
            {"name": "camp_c", "model": "patch", "verdict": "ABORTED",
             "verdict_zh": "已中止", "mark": "✗", "n_done": 2, "n_stages": 6,
             "path": "E:\\rf_local_work\\runs\\camp_c\\campaign.plan.json",
             "reason": "failed: password=hunter2 token=abc123 at E:\\tmp"},
        ],
        "summary_text": "本地文本含 E:\\rf_local_work 绝对路径与失败原因",
        "headline": "本地文本含 C:\\Users\\pc\\secret",
    }


# ── ① 配置单源：缺省关 ────────────────────────────────────────────────

class TestNotifyConfig:
    def test_default_off_all_none(self):
        cfg = notify_config()
        assert cfg["webhook_url"] is None
        assert cfg["feishu_webhook"] is None
        assert cfg["timeout_s"] == NOTIFY_TIMEOUT_S_DEFAULT == 10.0

    def test_env_single_channel_and_timeout(self, monkeypatch):
        monkeypatch.setenv(NOTIFY_FEISHU_WEBHOOK_ENV, "https://feishu.example/x")
        monkeypatch.setenv(NOTIFY_TIMEOUT_S_ENV, "2.5")
        cfg = notify_config()
        assert cfg["feishu_webhook"] == "https://feishu.example/x"
        assert cfg["webhook_url"] is None
        assert cfg["timeout_s"] == 2.5

    @pytest.mark.parametrize("raw", ["abc", "0", "-2", ""])
    def test_env_timeout_invalid_falls_back(self, monkeypatch, raw):
        monkeypatch.setenv(NOTIFY_TIMEOUT_S_ENV, raw)
        assert notify_config()["timeout_s"] == NOTIFY_TIMEOUT_S_DEFAULT

    def test_empty_env_is_unset(self, monkeypatch):
        monkeypatch.setenv(NOTIFY_WEBHOOK_URL_ENV, "   ")
        assert notify_config()["webhook_url"] is None

    def test_explicit_config_overrides_env(self, monkeypatch):
        monkeypatch.setenv(NOTIFY_WEBHOOK_URL_ENV, "http://env.example/hook")
        monkeypatch.setenv(NOTIFY_TIMEOUT_S_ENV, "9")
        cfg = notify_config({"webhook_url": " http://explicit.example/h ",
                             "timeout_s": "3"})
        assert cfg["webhook_url"] == "http://explicit.example/h"
        assert cfg["timeout_s"] == 3.0

    def test_config_partial_keeps_env_other_channel(self, monkeypatch):
        monkeypatch.setenv(NOTIFY_FEISHU_WEBHOOK_ENV, "https://feishu.example/x")
        cfg = notify_config({"webhook_url": "http://explicit.example/h"})
        assert cfg["webhook_url"] == "http://explicit.example/h"
        assert cfg["feishu_webhook"] == "https://feishu.example/x"

    @pytest.mark.parametrize("bad", [False, True, 123, 1.5])
    def test_config_non_str_channel_raises(self, bad):
        """非 None 非 str 的显式通道配置=ValueError（宁契约错误不
        silently-wrong——str(False)=='False' 当 URL 是假配置真推送）。"""
        with pytest.raises(ValueError, match="webhook_url"):
            notify_config({"webhook_url": bad})
        with pytest.raises(ValueError, match="feishu_webhook"):
            notify_config({"feishu_webhook": bad})


# ── ② payload 白名单构造（零敏感单点） ────────────────────────────────

class TestBuildDigestPayload:
    def test_one_liner_and_inline_lines(self):
        p = build_digest_payload(_digest())
        assert p.startswith("[rfauto 战役摘要]（2026-10-23 10:00:00）")
        assert "共 3 战役终态——2 完成、0 部分完成、1 已中止" in p
        assert "- wilkinson ✓ 完成（6/6 阶段）" in p
        assert "- patch ✗ 已中止（2/6 阶段）" in p

    def test_non_terminal_counted_not_terminal(self):
        d = _digest()
        d["n_campaigns"] = 1
        d["counts"] = {"COMPLETE": 0, "PARTIAL": 0, "ABORTED": 0}
        d["campaigns"] = [{"name": "fresh", "model": "dashcam",
                           "verdict": "RUNNING", "n_done": 2, "n_stages": 6}]
        p = build_digest_payload(d)
        assert "共 1 战役终态" in p
        assert "（另 1 个非终态计入）" in p
        assert "- dashcam … 进行中（2/6 阶段）" in p

    def test_unknown_verdict_closed_vocab_only(self):
        d = _digest()
        d["campaigns"] = [{"name": "x", "model": "m", "verdict": "WEIRD",
                           "n_done": None, "n_stages": None}]
        p = build_digest_payload(d)
        assert "WEIRD" not in p  # 自由 verdict 串不回显（词表封闭）
        assert "? 未知（?/? 阶段）" in p

    def test_sensitive_fields_never_leak(self):
        p = build_digest_payload(_digest())
        for bad in ("E:", "rf_local_work", "C:\\Users", "hunter2",
                    "token=abc123", "campaign.plan.json", "本地文本",
                    "secret"):
            assert bad not in p, f"payload 泄漏敏感面: {bad!r}"
        # 白名单允许面（战役名/模型/状态词/计数/时间戳）确在 payload
        assert "wilkinson" in p and "vivaldi" in p and "patch" in p

    def test_incomplete_digest_length_only(self):
        p = build_digest_payload({}, text="x" * 137)
        assert "digest 字段不完整" in p
        assert "137" in p and "未透传" in p
        assert "xxx" not in p

    def test_inline_cap_20(self):
        d = _digest()
        d["n_campaigns"] = 25
        d["counts"] = {"COMPLETE": 25, "PARTIAL": 0, "ABORTED": 0}
        d["campaigns"] = [{"name": f"c{i}", "model": f"m{i}",
                           "verdict": "COMPLETE", "n_done": 6,
                           "n_stages": 6} for i in range(25)]
        p = build_digest_payload(d)
        assert p.count("\n- ") == 20
        assert "另 5 战役未逐列" in p


# ── ③ 通道推送（fake opener，零真网络） ───────────────────────────────

class TestNotifyDigest:
    def test_not_configured_skip_zero_network(self):
        opener = _FakeOpener(exc=AssertionError("缺省关必须零网络"))
        out = notify_digest(_digest(), "本地正文", opener=opener)
        assert out["ok"] is True
        assert out["skipped"] is True
        assert "not_configured" in out["reason"]
        assert opener.calls == []

    def test_generic_channel_payload_and_envelope(self, monkeypatch):
        url = "http://hook.example/notify"
        monkeypatch.setenv(NOTIFY_WEBHOOK_URL_ENV, url)
        opener = _FakeOpener()
        out = notify_digest(_digest(), "本地正文 E:\\secret", opener=opener)
        assert out["ok"] is True
        assert out["channels"] == ["webhook"]
        assert out["results"]["webhook"] == {"ok": True, "status": 200}
        assert len(opener.calls) == 1
        call = opener.calls[0]
        assert call["url"] == url
        assert call["timeout_s"] == 10.0
        text = call["payload"]["text"]
        assert call["payload"] == {"text": text}  # 通用形态 {"text": 摘要}
        assert "共 3 战役终态" in text
        assert "E:\\secret" not in text  # 本地 txt 正文不透传

    def test_feishu_channel_payload(self, monkeypatch):
        monkeypatch.setenv(NOTIFY_FEISHU_WEBHOOK_ENV, "https://feishu.example/x")
        opener = _FakeOpener()
        out = notify_digest(_digest(), "本地正文", opener=opener)
        assert out["channels"] == ["feishu"]
        assert opener.calls[0]["payload"] == {
            "msg_type": "text",
            "content": {"text": opener.calls[0]["payload"]["content"]["text"]},
        }
        assert "共 3 战役终态" in opener.calls[0]["payload"]["content"]["text"]

    def test_both_channels_in_order(self, monkeypatch):
        monkeypatch.setenv(NOTIFY_WEBHOOK_URL_ENV, "http://hook.example/n")
        monkeypatch.setenv(NOTIFY_FEISHU_WEBHOOK_ENV, "https://feishu.example/x")
        opener = _FakeOpener()
        out = notify_digest(_digest(), "t", opener=opener)
        assert out["channels"] == ["webhook", "feishu"]
        assert len(opener.calls) == 2

    def test_non_2xx_degrades_no_raise(self, monkeypatch):
        monkeypatch.setenv(NOTIFY_WEBHOOK_URL_ENV, "http://hook.example/n")
        out = notify_digest(_digest(), "t", opener=_FakeOpener(status=500))
        assert out["ok"] is False
        assert out["results"]["webhook"] == {"ok": False, "error": "HTTP 500"}

    @pytest.mark.parametrize("exc", [TimeoutError("timed out"),
                                     RuntimeError("conn reset")])
    def test_exception_degrades_never_raises(self, monkeypatch, exc):
        monkeypatch.setenv(NOTIFY_WEBHOOK_URL_ENV, "http://hook.example/n")
        out = notify_digest(_digest(), "t", opener=_FakeOpener(exc=exc))
        assert out["ok"] is False
        assert "timed out" in out["results"]["webhook"]["error"] \
            or "conn reset" in out["results"]["webhook"]["error"]

    def test_timeout_env_reaches_post(self, monkeypatch):
        monkeypatch.setenv(NOTIFY_WEBHOOK_URL_ENV, "http://hook.example/n")
        monkeypatch.setenv(NOTIFY_TIMEOUT_S_ENV, "2.5")
        opener = _FakeOpener()
        notify_digest(_digest(), "t", opener=opener)
        assert opener.calls[0]["timeout_s"] == 2.5

    def test_config_only_channel_without_env(self):
        opener = _FakeOpener()
        out = notify_digest(_digest(), "t", opener=opener,
                            config={"webhook_url": "http://cfg.example/h"})
        assert out["ok"] is True and out["channels"] == ["webhook"]
        assert opener.calls[0]["url"] == "http://cfg.example/h"

    def test_one_channel_down_overall_not_ok(self, monkeypatch):
        monkeypatch.setenv(NOTIFY_WEBHOOK_URL_ENV, "http://hook.example/n")
        monkeypatch.setenv(NOTIFY_FEISHU_WEBHOOK_ENV, "https://feishu.example/x")

        class _Half(_FakeOpener):
            def __call__(self, url, payload, timeout_s):
                self.calls.append({"url": url})
                return 500 if url.startswith("http://hook") else 200

        out = notify_digest(_digest(), "t", opener=_Half())
        assert out["ok"] is False
        assert out["results"]["webhook"]["ok"] is False
        assert out["results"]["feishu"]["ok"] is True


# ── ④ digest 集成（notify 失败主产物照旧） ────────────────────────────

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
    from rfauto.service.campaign_manager import plan_campaign, save_plan

    plan = plan_campaign(_recipe(tmp_path, name))
    assert plan.get("ok"), plan.get("errors")
    plan["model"] = model  # 测试可读性：战役名与 model 解耦
    d = tmp_path / name
    save_plan(plan, d)
    return d


def _drive_complete(d: Path) -> None:
    from rfauto.service.campaign_manager import apply_event, load_plan, save_plan

    plan = load_plan(d)["plan"]
    for s in _STAGES:
        apply_event(plan, s, "stage_done")
    save_plan(plan, d)


class TestDigestIntegration:
    def test_notify_failure_digest_still_ok(self, tmp_path, monkeypatch):
        d = _plan_dir(tmp_path, "c1")
        _drive_complete(d)
        monkeypatch.setattr("rfauto.service.campaign_notify_service.notify_digest",
                            lambda *a, **k: {
                                "ok": False,
                                "results": {"webhook":
                                            {"ok": False, "error": "boom"}}})
        out = campaign_digest(str(tmp_path), out_dir=tmp_path / "art")
        assert out["ok"] is True  # 主产物不受通知失败影响（#105）
        assert Path(out["artifacts"]["json"]).exists()
        assert Path(out["artifacts"]["txt"]).exists()
        assert out["notify"]["ok"] is False
        assert out["notes"] == ["notify 推送未成功: boom"]
        # 通知结果只记返回信封——盘上 JSON 产物结构零变化（notify 在
        # 产物落盘后才发生，W2-S6 接线口径）
        on_disk = json.loads(
            Path(out["artifacts"]["json"]).read_text(encoding="utf-8"))
        assert "notify" not in on_disk
        assert on_disk["schema"] == "rfauto-campaign-digest-v1"

    def test_notify_raise_caught(self, tmp_path, monkeypatch):
        _plan_dir(tmp_path, "c1")
        _drive_complete(tmp_path / "c1")

        def _boom(*a, **k):
            raise RuntimeError("notify exploded")

        monkeypatch.setattr(
            "rfauto.service.campaign_notify_service.notify_digest", _boom)
        out = campaign_digest(str(tmp_path), out_dir=tmp_path / "art")
        assert out["ok"] is True
        assert out["notify"]["ok"] is False
        assert "notify exploded" in str(out["notify"]["errors"])
        assert "notify 推送未成功" in out["notes"][0]

    def test_explicit_false_skips_service_and_env(self, tmp_path, monkeypatch):
        _plan_dir(tmp_path, "c1")
        _drive_complete(tmp_path / "c1")
        monkeypatch.setenv(NOTIFY_WEBHOOK_URL_ENV, "http://hook.example/n")

        def _must_not_call(*a, **k):
            raise AssertionError("显式 False 不得触达 notify_digest")

        monkeypatch.setattr(
            "rfauto.service.campaign_notify_service.notify_digest",
            _must_not_call)
        out = campaign_digest(str(tmp_path), out_dir=tmp_path / "art",
                              notify=False)
        assert out["ok"] is True
        assert out["notify"]["skipped"] is True
        assert "disabled" in out["notify"]["reason"]

    def test_default_unconfigured_skipped_no_notes(self, tmp_path):
        _plan_dir(tmp_path, "c1")
        _drive_complete(tmp_path / "c1")
        out = campaign_digest(str(tmp_path), out_dir=tmp_path / "art")
        assert out["ok"] is True
        assert out["notify"]["skipped"] is True
        assert "not_configured" in out["notify"]["reason"]
        assert "notes" not in out  # skipped 非 failed：不入 notes

    def test_notify_success_no_notes(self, tmp_path, monkeypatch):
        _plan_dir(tmp_path, "c1")
        _drive_complete(tmp_path / "c1")
        monkeypatch.setattr(
            "rfauto.service.campaign_notify_service.notify_digest",
            lambda *a, **k: {"ok": True, "channels": ["webhook"],
                             "results": {"webhook":
                                         {"ok": True, "status": 200}}})
        out = campaign_digest(str(tmp_path), out_dir=tmp_path / "art")
        assert out["notify"]["ok"] is True
        assert "notes" not in out

    def test_write_false_never_notifies(self, tmp_path, monkeypatch):
        _plan_dir(tmp_path, "c1")
        _drive_complete(tmp_path / "c1")
        monkeypatch.setenv(NOTIFY_WEBHOOK_URL_ENV, "http://hook.example/n")
        monkeypatch.setattr(
            "rfauto.service.campaign_notify_service.notify_digest",
            lambda *a, **k: {"ok": True})
        out = campaign_digest(str(tmp_path), write=False)
        assert out["ok"] is True
        assert "notify" not in out  # 预览面（零落盘）零推送副作用


# ── ⑤ CLI 三态接线 ────────────────────────────────────────────────────

class TestCliNotify:
    def _app(self):
        from rfauto.cli.domains.campaign import campaign_app

        return campaign_app

    def _camp(self, tmp_path: Path) -> Path:
        d = _plan_dir(tmp_path, "cli_camp", model="wilkinson")
        _drive_complete(d)
        return d

    def test_default_off_zero_network_smoke(self, tmp_path, monkeypatch):
        self._camp(tmp_path)
        monkeypatch.setattr(
            "rfauto.service.campaign_notify_service._http_post_json",
            lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("缺省关必须零网络")))
        r = runner.invoke(self._app(), [
            "digest", "--root", str(tmp_path),
            "--out-dir", str(tmp_path / "art"), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["notify"]["skipped"] is True
        assert "not_configured" in payload["notify"]["reason"]

    def test_no_notify_flag_service_never_called(self, tmp_path, monkeypatch):
        self._camp(tmp_path)
        monkeypatch.setenv(NOTIFY_WEBHOOK_URL_ENV, "http://hook.example/n")

        def _must_not_call(*a, **k):
            raise AssertionError("--no-notify 不得触达 notify_digest")

        monkeypatch.setattr(
            "rfauto.service.campaign_notify_service.notify_digest",
            _must_not_call)
        r = runner.invoke(self._app(), [
            "digest", "--root", str(tmp_path),
            "--out-dir", str(tmp_path / "art"), "--no-notify", "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["notify"]["skipped"] is True
        assert "disabled" in payload["notify"]["reason"]

    def test_default_reads_env_and_posts(self, tmp_path, monkeypatch):
        self._camp(tmp_path)
        monkeypatch.setenv(NOTIFY_WEBHOOK_URL_ENV, "http://hook.example/n")
        seen: list[dict] = []

        def _fake_post(url, payload, timeout_s):
            seen.append({"url": url, "payload": payload})
            return 200

        monkeypatch.setattr(
            "rfauto.service.campaign_notify_service._http_post_json",
            _fake_post)
        r = runner.invoke(self._app(), [
            "digest", "--root", str(tmp_path),
            "--out-dir", str(tmp_path / "art"), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.output)
        assert payload["notify"]["results"]["webhook"]["status"] == 200
        assert seen and seen[0]["url"] == "http://hook.example/n"
        assert seen[0]["payload"]["text"].startswith("[rfauto 战役摘要]")

    def test_notify_flag_explicit_true_posts(self, tmp_path, monkeypatch):
        self._camp(tmp_path)
        monkeypatch.setenv(NOTIFY_WEBHOOK_URL_ENV, "http://hook.example/n")
        monkeypatch.setattr(
            "rfauto.service.campaign_notify_service._http_post_json",
            lambda url, payload, timeout_s: 200)
        r = runner.invoke(self._app(), [
            "digest", "--root", str(tmp_path),
            "--out-dir", str(tmp_path / "art"), "--notify", "--json"])
        assert r.exit_code == 0, r.output
        assert json.loads(r.output)["notify"]["ok"] is True

    def test_notify_failure_digest_still_ok_via_cli(self, tmp_path,
                                                    monkeypatch):
        self._camp(tmp_path)
        monkeypatch.setenv(NOTIFY_WEBHOOK_URL_ENV, "http://hook.example/n")
        monkeypatch.setattr(
            "rfauto.service.campaign_notify_service._http_post_json",
            lambda url, payload, timeout_s: 503)
        r = runner.invoke(self._app(), [
            "digest", "--root", str(tmp_path),
            "--out-dir", str(tmp_path / "art"), "--json"])
        assert r.exit_code == 0, r.output  # 通知失败不失败命令（#105）
        payload = json.loads(r.output)
        assert payload["ok"] is True
        assert payload["notify"]["results"]["webhook"] == {
            "ok": False, "error": "HTTP 503"}
        assert "notify 推送未成功" in payload["notes"][0]


if __name__ == "__main__":
    raise SystemExit(__import__("pytest").main([__file__, "-q"]))
