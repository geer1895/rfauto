"""W2-S4 人性化二批回归钉（aurora_i 采纳 R1 #5+#6）：远程机器面板三件。

覆盖面（全离线，#139：进程探测/SSH 通道一律 monkeypatch 桩钉死，绝不真连
真枚举；node 行为钉缺 node skip）：

1. service 层（remote_scheduler_service 增量）：
   - ``recommend_machine`` 纯函数：size_aware 排除集六路（不可达/SSH 非
     ok/n_tasks unknown/#122 不猜/占用中 n>=max_parallel 钉 1/磁盘不足）
     + 打分项（磁盘/100 − OE×2 − HFSS×2）+ 排除态 score=None；
   - ``resources_view``：recommend 附着 + remote.probed_at 探测时间戳；
   - ``queue_inflight_view``：守护状态档 launched 瘦形（占用徽章行）+
     缺文件/损坏降级（daemon load 语义原样继承）；
   - ``resources_panel_view``：聚合信封 + 未知机器 error 信封。
2. JS 纯函数（node 真执行）：resFreshInfo（新鲜/超龄/钳 0/锚回落）+
   queueBucketOf/queueTabCounts（verdict 分桶）+ miniBarHtml（越界不接）。
3. 源码钉（免 node）：✗ 豁免点恒 1、queueCtx leave 收束 ticker、
   setInterval 联合计数不被本席改动、W2-S3 合流面（阻塞列）原样在位、
   i18n 新键双语在档、UI 端点接线（campaign_app handler + server 路由）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

src_dir = Path(__file__).resolve().parents[2] / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

import rfauto.service.remote_scheduler_service as rss
from rfauto.service.remote_scheduler_service import (
    RECOMMEND_MAX_PARALLEL,
    RECOMMEND_MIN_FREE_DISK_GB,
    queue_inflight_view,
    recommend_machine,
    remote_resources,
    resources_panel_view,
    resources_view,
)

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_QUEUE = _STATIC / "pages" / "view_queue.js"
_NODE = shutil.which("node")


def _run_node_js(js: str) -> str:
    r = subprocess.run(
        [_NODE, "--input-type=module", "-e", js],
        capture_output=True, text=True, timeout=60, cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2500:]}"
    return r.stdout


# ─── recommend_machine 纯函数（size_aware 排除集 + 打分） ─────────────────────

def _ok_view(**kw) -> dict:
    """健康空闲机器实况基线（reachable+ssh ok+n_tasks=0+磁盘充裕）。"""
    import time

    base = {
        "machine": "sim_server", "reachable": True,
        "ssh": {"auth": "ok"},
        "openems": {"state": "ok", "busy": False, "n_procs": 0},
        "hfss": {"state": "ok", "busy": False, "n_procs": 0},
        "disk": {"state": "ok", "free_gb": 213.5, "drive": "E:"},
        "n_tasks": 0,
        "probed_at": time.time(),
    }
    base.update(kw)
    return base


def test_recommend_eligible_idle_scores():
    rec = recommend_machine(_ok_view())
    assert rec["machine"] == "sim_server"
    assert rec["eligible"] is True
    assert rec["excluded_by"] == []
    # 打分 = 213.5/100 − 0×2 − 0×2 = 2.135 → round(...,2)（银行家舍入=2.13）
    assert rec["score"] == pytest.approx(2.13, abs=0.005)
    assert rec["max_parallel"] == 1  # #261 钉 1 如实展示
    assert any("磁盘" in r for r in rec["reasons"])


def test_recommend_busy_excluded_max_parallel_pinned():
    rec = recommend_machine(_ok_view(n_tasks=1))
    assert rec["eligible"] is False
    assert rec["score"] is None  # 排除态不打分不冒充可比（#122 同族）
    assert any("钉 1" in r and "#261" in r for r in rec["excluded_by"])
    assert rec["max_parallel"] == RECOMMEND_MAX_PARALLEL == 1


def test_recommend_unreachable_and_ssh_excluded():
    rec = recommend_machine(_ok_view(reachable=False))
    assert rec["eligible"] is False
    assert any("不可达" in r for r in rec["excluded_by"])
    rec2 = recommend_machine(_ok_view(ssh={"auth": "missing_credentials"}))
    assert rec2["eligible"] is False
    assert any("SSH" in r for r in rec2["excluded_by"])


def test_recommend_n_tasks_unknown_excluded_honest():
    """census 半边不凑数（#122）→ n_tasks unknown 不得推荐"空闲"。"""
    rec = recommend_machine(_ok_view(n_tasks=None))
    assert rec["eligible"] is False
    assert any("#122" in r for r in rec["excluded_by"])
    assert rec["n_tasks"] is None


def test_recommend_disk_low_excluded_unknown_not_excluded():
    rec = recommend_machine(_ok_view(
        disk={"state": "ok", "free_gb": 10.0, "drive": "E:"}))
    assert rec["eligible"] is False
    assert any("磁盘余量不足" in r for r in rec["excluded_by"])
    # 磁盘 unknown 不排除（size_aware 同语义"未知≠不足"），reasons 如实登记
    rec2 = recommend_machine(_ok_view(
        disk={"state": "unknown", "free_gb": None, "drive": "E:",
              "reason": "x"}))
    assert rec2["eligible"] is True
    assert any("unknown" in r for r in rec2["reasons"])


def test_recommend_no_machine_and_proc_penalty():
    rec = recommend_machine({"machine": None, "reachable": None})
    assert rec["eligible"] is False
    assert any("无登记机器" in r for r in rec["excluded_by"])
    # 在跑进程罚项：n_procs=3 → −6.0（OE/HFSS 同权，size_aware aedt×2 同构）
    rec2 = recommend_machine(_ok_view(
        openems={"state": "ok", "busy": True, "n_procs": 3},
        disk={"state": "unknown", "free_gb": None, "drive": None}))
    assert rec2["score"] == pytest.approx(-6.0, abs=0.01)
    assert any("openEMS" in r and "-6.0" in r for r in rec2["reasons"])


def test_recommend_min_disk_constant_matches_size_aware():
    assert RECOMMEND_MIN_FREE_DISK_GB == 20.0  # size_aware MIN_FREE_DISK_GB


# ─── resources_view / remote_resources 增量字段 ───────────────────────────────

def test_resources_view_attaches_recommend_and_probed_at(monkeypatch):
    monkeypatch.setattr(rss, "local_openems_view",
                        lambda: {"state": "ok", "busy": False, "n_procs": 0,
                                 "reason": None})
    monkeypatch.setattr(rss, "local_hfss_view",
                        lambda: {"state": "ok", "busy": False, "n_procs": 0,
                                 "n_grpcsrv": 0, "reason": None})
    monkeypatch.setattr(rss, "remote_resources", lambda m=None: _ok_view())
    monkeypatch.setattr(rss, "calendar_launch_view", lambda: {
        "ok": True, "loaded": False, "state": "open", "launchable": True})
    view = resources_view()
    assert view["ok"] is True
    assert isinstance(view["remote"].get("probed_at"), float)
    assert view["recommend"]["machine"] == "sim_server"
    assert view["recommend"]["eligible"] is True


def test_remote_resources_probed_at_on_degraded_paths(monkeypatch):
    """无登记机器降级路径同样带 probed_at（新鲜度锚全覆盖）。"""
    monkeypatch.setattr(rss, "load_remote_machines", lambda: {})
    view = remote_resources(None)
    assert view["state"] == "no_machine"
    assert isinstance(view["probed_at"], float)


# ─── queue_inflight_view（守护状态档只读瘦形） ────────────────────────────────

def _write_state(tmp_path: Path, items: dict) -> Path:
    p = tmp_path / "queue_state.json"
    p.write_text(json.dumps({
        "schema": "rfauto-campaign-queue-daemon-v1",
        "root": "runs", "machine": None, "items": items,
        "last_tick_at": 1700000000.0, "last_actions": [],
        "updated_at": 1700000000.0,
    }, ensure_ascii=False), encoding="utf-8")
    return p


def test_inflight_view_counts_launched_only(tmp_path):
    p = _write_state(tmp_path, {
        "a": {"item_id": "a", "plan_path": "runs/ca", "model": "patch",
              "status": "launched", "launched_at": 111.0,
              "pid": 1, "log_path": None, "verdict_seen": "",
              "reason": "", "updated_at": 222.0},
        "b": {"item_id": "b", "plan_path": "runs/cb", "model": "cpw",
              "status": "done", "launched_at": 100.0, "pid": None,
              "log_path": None, "verdict_seen": "COMPLETE",
              "reason": "", "updated_at": 150.0},
    })
    view = queue_inflight_view(p)
    assert view["ok"] is True
    assert view["in_flight"] == 1
    assert view["max_parallel"] == 1
    assert view["exists"] is True
    assert len(view["campaigns"]) == 1
    row = view["campaigns"][0]
    assert row["model"] == "patch"
    assert row["plan_path"] == "runs/ca"
    assert row["launched_at"] == 111.0


def test_inflight_view_missing_and_corrupt_degrade(tmp_path):
    miss = queue_inflight_view(tmp_path / "nope.json")
    assert miss["ok"] is True and miss["in_flight"] == 0
    assert miss["exists"] is False and miss["campaigns"] == []
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    # 损坏档 = daemon load_queue_state 空白档语义原样继承（#105 不炸）
    view = queue_inflight_view(bad)
    assert view["ok"] is True and view["in_flight"] == 0


# ─── resources_panel_view（UI 端点聚合面） ────────────────────────────────────

def test_panel_view_merges_resources_and_occupancy(monkeypatch, tmp_path):
    monkeypatch.setattr(rss, "local_openems_view",
                        lambda: {"state": "ok", "busy": False, "n_procs": 0,
                                 "reason": None})
    monkeypatch.setattr(rss, "local_hfss_view",
                        lambda: {"state": "ok", "busy": False, "n_procs": 0,
                                 "reason": None})
    monkeypatch.setattr(rss, "remote_resources", lambda m=None: _ok_view())
    monkeypatch.setattr(rss, "calendar_launch_view", lambda: {
        "ok": True, "loaded": False, "state": "open", "launchable": True})
    state = _write_state(tmp_path, {})
    panel = resources_panel_view(state_path=state)
    assert panel["ok"] is True
    assert panel["resources"]["recommend"]["eligible"] is True
    assert panel["occupancy"]["in_flight"] == 0


def test_panel_view_unknown_machine_error_envelope(monkeypatch):
    from rfauto.infra.remote_machines import RemoteConfigError

    def _raise(machine=None):
        raise RemoteConfigError("远程机器 'nope' 未登记")

    monkeypatch.setattr(rss, "remote_resources", _raise)
    panel = resources_panel_view(machine="nope")
    assert panel["ok"] is False
    assert panel["errors"] and "未登记" in panel["errors"][0]


# ─── JS 纯函数行为钉（node 真执行） ───────────────────────────────────────────

@pytest.mark.skipif(_NODE is None, reason="本机无 node")
class TestJsPureFunctions:
    def test_res_fresh_info(self):
        out = _run_node_js(
            "const m = await import('./pages/view_queue.js');\n"
            "const errs = [];\n"
            "const now = 1000_000_000_000;\n"
            # 探测 30s 前 → 新鲜
            "let f = m.resFreshInfo((now - 30_000) / 1000, now, now);\n"
            "if (f.age_s !== 30 || f.stale) errs.push('fresh=' + JSON.stringify(f));\n"
            # 探测 300s 前 → 超龄（阈 120）
            "f = m.resFreshInfo((now - 300_000) / 1000, now, now);\n"
            "if (!f.stale) errs.push('stale miss');\n"
            # 服务端钟快于本端（probed_at 在 fetched 之后）→ 锚回落 fetched
            "f = m.resFreshInfo((now + 60_000) / 1000, now, now - 45_000);\n"
            "if (f.age_s !== 45) errs.push('skew=' + f.age_s);\n"
            # probed_at 缺失 → fetched 锚；双缺 → age null 不判超龄
            "f = m.resFreshInfo(null, now, now - 10_000);\n"
            "if (f.age_s !== 10) errs.push('fallback=' + f.age_s);\n"
            "f = m.resFreshInfo(null, now, null);\n"
            "if (f.age_s !== null || f.stale) errs.push('none=' + JSON.stringify(f));\n"
            # 负龄期钳 0
            "f = m.resFreshInfo((now + 30_000) / 1000, now, now);\n"
            "if (f.age_s !== 0) errs.push('clamp=' + f.age_s);\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:fresh');\n")
        assert "ok:fresh" in out

    def test_bucket_and_tab_counts(self):
        out = _run_node_js(
            "const m = await import('./pages/view_queue.js');\n"
            "const errs = [];\n"
            "const cases = { RUNNING: 'running', COMPLETE: 'done',"
            " FAILED: 'failed', ABORTED: 'failed', PARTIAL: 'failed',"
            " '': 'other', WEIRD: 'other', null_: 'other' };\n"
            "for (const [v, want] of Object.entries(cases)) {\n"
            "  const got = m.queueBucketOf(v === 'null_' ? null : v);\n"
            "  if (got !== want) errs.push(v + '->' + got);\n"
            "}\n"
            "const c = m.queueTabCounts([{verdict:'RUNNING'},"
            "{verdict:'COMPLETE'},{verdict:'ABORTED'},{verdict:''}]);\n"
            "if (c.all !== 4 || c.running !== 1 || c.done !== 1 ||"
            " c.failed !== 1 || c.other !== 1) errs.push(JSON.stringify(c));\n"
            "const e = m.queueTabCounts([]);\n"
            "if (e.all !== 0) errs.push('empty');\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:bucket');\n")
        assert "ok:bucket" in out

    def test_mini_bar_boundaries(self):
        out = _run_node_js(
            "const m = await import('./pages/view_queue.js');\n"
            "const errs = [];\n"
            "if (m.miniBarHtml(50, 'var(--ok)', 4, 90) === '') errs.push('50');\n"
            "for (const bad of [null, undefined, NaN, -1, 101, 'x'])\n"
            "  if (m.miniBarHtml(bad, 'var(--ok)', 4, 90) !== '') errs.push('bad:' + bad);\n"
            "const h = m.miniBarHtml(100, 'var(--warn)', 6, 160);\n"
            "if (!h.includes('width:100%') || !h.includes('var(--warn)'))"
            " errs.push('full:' + h);\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:bar');\n")
        assert "ok:bar" in out

    def test_node_check_view_queue(self):
        r = subprocess.run([_NODE, "--check", str(_QUEUE)],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"node --check view_queue.js:\n{r.stderr[-2000:]}"

    def test_i18n_w2s4_keys_bilingual(self):
        keys = [
            "queue.res_title", "queue.res_fresh_tpl", "queue.res_fresh_stale",
            "queue.res_fresh_aria", "queue.res_fresh_unknown",
            "queue.res_reach_ok", "queue.res_reach_bad",
            "queue.res_reach_unknown", "queue.res_occupancy_tpl",
            "queue.res_no_machine", "queue.res_recommend_lead",
            "queue.res_recommend_score_tpl", "queue.res_not_recommended",
            "queue.res_maintenance", "queue.res_backup_risk",
            "queue.res_tasks_tpl", "queue.res_disk_tpl",
            "queue.res_local_label", "queue.tab_all", "queue.tab_running",
            "queue.tab_done", "queue.tab_failed", "queue.filter_empty",
        ]
        out = _run_node_js(
            "const m = await import('./pages/i18n.js');\n"
            "const want = " + json.dumps(keys) + ";\n"
            "const errs = [];\n"
            "for (const k of want) {\n"
            "  const e = m.LOCALES[k];\n"
            "  if (!e || typeof e.zh !== 'string' || !e.zh) errs.push('zh:' + k);\n"
            "  if (!e || typeof e.en !== 'string' || !e.en) errs.push('en:' + k);\n"
            "}\n"
            "if (errs.length) throw new Error(errs.join('; '));\n"
            "console.log('ok:keys:' + want.length);\n")
        assert "ok:keys:23" in out


# ─── 源码钉（免 node；跨席计数钉与合流面） ────────────────────────────────────

class TestSourcePins:
    def test_queue_x_exempt_site_count_unchanged(self):
        """✗ 豁免点恒 1（跨席计数钉；资源面板错误态走 kitErrorPanel）。"""
        q = _QUEUE.read_text(encoding="utf-8")
        assert q.count("color:var(--err)'>✗") == 1

    def test_queue_ctx_leave_stops_fresh_ticker(self):
        q = _QUEUE.read_text(encoding="utf-8")
        assert "leave: () => {" in q
        assert "clearTimeout(_freshTimer)" in q
        # 新鲜度 ticker 只允许 setTimeout 自续链（test_ui_lifecycle 的
        # setInterval 联合计数 ==2 钉不被本席触碰）
        union = "\n".join(
            p.read_text(encoding="utf-8")
            for p in sorted((_STATIC / "pages").glob("*.js")))
        assert union.count("setInterval(") == 2

    def test_w2s3_merge_surface_intact(self):
        """W2-S3 阻塞列与本席面板同文件共存（合流双向钉）。

        W3-S3（aurora_i 采纳 #1）阻塞列演进为"阻塞账→对冲告警→占位"
        三段回退链（同列零布局变化），钉面随金标演进正当迁移——钉的
        意图=阻塞列渲染面在位且 queue_block 仍是第一优先。
        """
        q = _QUEUE.read_text(encoding="utf-8")
        assert "function queueBlockHtml(b)" in q
        assert 't("queue.th_block_reason")' in q
        assert ("${queueBlockHtml(c.queue_block) || hedgeHtml(c.queue_hedge)"
                " || \"<span class='muted'>—</span>\"}") in q
        # 本席面：机器卡容器 + 资源请求点（字面量含 "?"，契约门归一按 ?
        # 截断得精确路径——campaign_queue 先例）+ 推荐行 + 维护遮罩在位
        assert "id='q-resources'" in q
        assert '"/api/remote/resources?"' in q
        assert "queue.res_recommend_lead" in q
        assert "queue.res_maintenance" in q

    def test_ui_endpoint_wiring(self):
        """handler 协程 + server 路由注册（薄壳直渲染，规则 4）。"""
        import inspect

        from rfauto.ui import campaign_app, server

        assert inspect.iscoroutinefunction(campaign_app.api_remote_resources)
        assert server.api_remote_resources is campaign_app.api_remote_resources
        server_src = (Path(__file__).resolve().parents[2] / "src" / "rfauto"
                      / "ui" / "server.py").read_text(encoding="utf-8")
        assert 'Route("/api/remote/resources", api_remote_resources)' in \
            server_src


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
