"""aurora_n wave_ui_a 席位回归钉：前端引导线 A 席三件修复。

对应 runs/aurora_n/ui_recon/TOUR_FINDINGS.md 三发现：

- P1-1 Run 列表↔详情双源不一致：list_runs（SQLite 索引）与 run_detail
  （物理目录）双源漂移——实测 200 条列出 27 条无目录、缺失的恰是霸占
  首屏的最新记录。修法（最小形态，list 面禁物理全扫红线不碰）：
  * ui_service.list_runs 对已列出 ≤limit 行逐行 stat 补 ``on_disk`` 在盘
    标注；run_detail 目录缺失按索引可查性分口径给可行动文案 + ``missing_dir``
    机器可读旗标。两字段走信封附加键（_Contract extra="ignore" 前向兼容，
    契约模型零改动——本席文件面红线）。
  * 前端消费：dashboard 最近活动/最近 runs 行、runs 历史行、sparams 下拉
    （归档缺失=非可点入口/徽章/后缀）；detail 重试钮对 missing_dir 禁用。

- P1-2 Agent 对话浮窗自动弹出遮挡内容 + chips 重复堆叠：浮窗挂
  document.body 跨页存活，pageAgent 每次进页 openChatFloat(false) 强制
  复显（×关闭态被踩）；chips 追加前不清容器（win 命中早退不重建 DOM），
  再进 agent 页每 chip 重复 ×2。修法：chatAutoOpenBlocked 关闭意愿闸
  （localStorage rfauto-chat-closed，显式打开钮清除）+ chips 容器先清空。

- P2 审批收件箱无忽略控件（#144 家族 UI 面：测试残留提案永久占位）：
  忽略=前端 localStorage 记账（rfauto-inbox-dismissed，服务端零新写路径
  零新表——红线），parseInboxDismissed/splitPendingByDismissed 纯函数 +
  折叠已忽略清单可查看/恢复。

变异验证（移除修复必红，开发期逐钉实测并记录于本文件尾注）：各源码钉
关键串即修复本体（删除即断言红）；node 行为钉消费导出纯函数（删除导出
即 import undefined 红）；后端行为钉消费 on_disk/missing_dir 字段（摘除
标注/旗标即 KeyError/断言红）。

不依赖 runs/ 真实湖（tmp 隔离）、不读网络、不启动服务器；node 面缺 node
诚实 skip；不 commit。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from rfauto.service.contracts import annotate_contract

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_NODE = shutil.which("node")

_RUN_ID_DIR = "20260101_000000_withdir"
_RUN_ID_GONE = "20260101_000000_gone"
_RUN_ID_UNKNOWN = "20991231_000000_nope"


def _src(name: str) -> str:
    return (_STATIC / "pages" / name).read_text(encoding="utf-8")


def _run_node_js(js: str) -> dict:
    r = subprocess.run(
        [_NODE, "--input-type=module", "-e", js],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60, cwd=str(_STATIC),
    )
    assert r.returncode == 0, f"node 执行失败:\n{r.stderr[-2500:]}"
    import json

    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.fixture()
def _iso(tmp_path, monkeypatch):
    """cwd+注册表 DB 双隔离（#144 家族口径：本机 env 与真实 runs/ 湖零触碰）。"""
    monkeypatch.delenv("RFAUTO_REGISTRY_DB", raising=False)
    monkeypatch.setenv("RFAUTO_REGISTRY_DB", str(tmp_path / "reg.sqlite"))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _seed_index(run_id: str, timestamp: str) -> None:
    from rfauto.infra.run_store import record_run

    assert record_run(record={
        "run_id": run_id, "model": "wilkinson_power_divider",
        "adapter": "fake", "status": "done", "timestamp": timestamp,
    })


# ────────────────────────── P1-1 后端行为钉 ──────────────────────────

class TestP11ListRunsOnDisk:
    def test_list_runs_annotates_on_disk(self, _iso):
        """索引行逐行带 on_disk：目录在盘 True / 目录消亡 False（≤limit 行
        逐行 stat，非全扫——list 面禁物理全扫红线不碰）。"""
        from rfauto.service.ui_service import list_runs

        run_dir = _iso / "runs" / _RUN_ID_DIR / "results"
        run_dir.mkdir(parents=True)
        _seed_index(_RUN_ID_DIR, "2026-01-01T00:00:00+00:00")
        _seed_index(_RUN_ID_GONE, "2026-01-02T00:00:00+00:00")  # 无目录残留行
        r = list_runs(limit=10)
        assert r["ok"]
        rows = {x["run_id"]: x for x in r["runs"]}
        assert rows[_RUN_ID_DIR]["on_disk"] is True
        assert rows[_RUN_ID_GONE]["on_disk"] is False

    def test_list_runs_annotates_via_endpoint_contract(self, _iso):
        """on_disk 过 ListRunsPayload 契约（_Contract extra="ignore" 前向
        兼容——标注字段为信封附加键，不违约、不拦响应）。"""
        from rfauto.service.ui_service import list_runs

        _seed_index(_RUN_ID_GONE, "2026-01-02T00:00:00+00:00")
        r = annotate_contract("list_runs", list_runs(limit=5))
        assert r["contract_check"]["ok"] is True, r["contract_check"]["errors"]
        assert r["runs"][0]["on_disk"] is False

    def test_infra_run_store_untouched(self, _iso):
        """infra.run_store.list_runs 零改动（标注只在 ui_service 消费面；
        CLI runs list / MCP runs 资源口径不受影响）。"""
        from rfauto.infra.run_store import list_runs as infra_list_runs

        _seed_index(_RUN_ID_GONE, "2026-01-02T00:00:00+00:00")
        rows = infra_list_runs(limit=5)
        assert len(rows) == 1
        assert "on_disk" not in rows[0], "infra 层不应被 UI 标注污染"


class TestP11RunDetailMissingDir:
    def test_indexed_missing_dir_actionable(self, _iso):
        """索引有、目录无 → 可行动文案（重试无效/索引残留）+ missing_dir
        机器可读旗标（前端据此禁用重试钮，不再骗点击）。"""
        from rfauto.service.ui_service import run_detail

        _seed_index(_RUN_ID_GONE, "2026-01-02T00:00:00+00:00")
        d = run_detail(_RUN_ID_GONE)
        assert d["ok"] is False
        assert d["missing_dir"] is True
        assert any("重试无效" in e for e in d["errors"])
        assert any("索引残留" in e for e in d["errors"])

    def test_unknown_run_still_honest_and_flagged(self, _iso):
        """索引也无 → 维持"run 不存在"原文案；missing_dir 旗标同在（目录
        不在盘=重试恒失败，两种形态都禁重试）。"""
        from rfauto.service.ui_service import run_detail

        d = run_detail(_RUN_ID_UNKNOWN)
        assert d["ok"] is False
        assert d["missing_dir"] is True
        assert any(f"run 不存在: {_RUN_ID_UNKNOWN}" in e for e in d["errors"])

    def test_missing_dir_via_endpoint_contract(self, _iso):
        """错误信封过 RunDetailPayload 契约（missing_dir 为信封附加键，
        _Contract extra="ignore" 前向兼容不违约）。"""
        from rfauto.service.ui_service import run_detail

        _seed_index(_RUN_ID_GONE, "2026-01-02T00:00:00+00:00")
        d = annotate_contract("run_detail", run_detail(_RUN_ID_GONE))
        assert d["contract_check"]["ok"] is True, d["contract_check"]["errors"]

    def test_success_path_has_no_missing_dir_flag(self, _iso):
        """目录在盘成功路径不带 missing_dir 真值面（契约缺省 False，
        前端 !!d.missing_dir 恒假走原重试钮）。"""
        from rfauto.service.ui_service import run_detail

        run_dir = _iso / "runs" / _RUN_ID_DIR
        (run_dir / "results").mkdir(parents=True)
        (run_dir / "results" / "metrics.json").write_text("{}", encoding="utf-8")
        d = run_detail(_RUN_ID_DIR)
        assert d["ok"] is True
        assert not d.get("missing_dir")


# ────────────────────────── P1-1 前端接线源码钉 ──────────────────────────

class TestP11FrontendWiring:
    def test_detail_retry_disabled_for_missing_dir(self):
        """missing_dir → 重试钮 disabled+tooltip；非缺失分支保留可点重试
        （test_w7c_ui_p2_sweep 同笔钉面 id="detail-retry"/showRun(id) 不动）。"""
        src = _src("view_detail.js")
        assert "const missingDir = !!d.missing_dir;" in src
        assert 'disabled title="${escAttr(t("detail.retry_futile"))}"' in src
        assert 'if (retry && !missingDir) retry.onclick = () => showRun(id);' in src

    def test_dashboard_archived_rows_not_clickable(self):
        """总览最近活动/最近 runs：on_disk===false 行=归档缺失徽章、无
        data-id/无 clickable 类（bindClickRows 选择器天然跳过）。"""
        src = _src("view_dashboard.js")
        # wActivity 分支：归档行无 data-id（[data-id] 选择器跳过）
        assert src.count("r.on_disk === false") >= 2, "活动+最近 runs 两处消费"
        assert 't("runs.archived_missing")' in src
        assert 't("runs.archived_missing_tip")' in src
        m = re.search(r"if \(r\.on_disk === false\) \{\s*\n\s*return `<div title=", src)
        assert m, "wActivity 归档行分支形态（title=说明、无 data-id）"
        m2 = re.search(r'if \(r\.on_disk === false\) \{\s*\n\s*return `<tr class="st-muted" title=', src)
        assert m2, "wRecentRuns 归档行分支形态（无 clickable 类）"

    def test_runs_history_archived_rows_not_clickable(self):
        """runs 历史行：归档行不挂 clickable 类/行动作三件套，状态列附
        归档缺失徽章+行悬停说明。"""
        src = _src("view_runs.js")
        assert "const missing = r.on_disk === false;" in src
        assert 'if (!missing) tr.className = "clickable";' in src
        assert "if (!missing) {" in src and "kitApplyClickRowAttrs" in src
        assert 'tr.title = t("runs.archived_missing_tip");' in src
        assert 'T.badge(t("runs.archived_missing"), "muted")' in src

    def test_sparams_dropdown_archived_suffix(self):
        """S 参数分析 run 下拉：归档缺失选项附词表后缀（联动受益面）。"""
        src = _src("view_sparams.js")
        assert "r.on_disk === false ? esc(t(\"sparams.archived_suffix\"))" in src

    def test_i18n_keys_zh_en_paired(self):
        """新键 zh/en 双语齐全 + 前缀归属页引用（runs.* 由 view_runs 引用，
        dashboard 跨页复用只增引用）。"""
        i18n = _src("i18n.js")
        for key in ("runs.archived_missing", "runs.archived_missing_tip",
                    "detail.retry_futile", "sparams.archived_suffix",
                    "agent.dismiss", "agent.dismissed_ok",
                    "agent.dismissed_summary_tpl", "agent.dismiss_restore",
                    "agent.inbox_all_dismissed", "agent.dismiss_tip"):
            assert f'"{key}"' in i18n, f"i18n 缺键 {key}"
        assert "runs.archived_missing" in _src("view_runs.js")
        assert "runs.archived_missing" in _src("view_dashboard.js")
        assert "detail.retry_futile" in _src("view_detail.js")
        assert "sparams.archived_suffix" in _src("view_sparams.js")

    def test_backend_annotation_present_not_full_scan(self):
        """服务端标注形态钉：逐行 stat 补 on_disk（no rglob/scandir 进
        list_runs——list 面禁物理全扫红线）。"""
        from rfauto.service.ui_service import runs_recipes

        fn_src = Path(runs_recipes.__file__).read_text(encoding="utf-8")
        m = re.search(r"def list_runs\(.*?\n(?=def |\Z)", fn_src, re.S)
        assert m
        body = m.group(0)
        assert 'row["on_disk"]' in body, "逐行在盘标注缺失"
        for banned in ("rglob", "scandir", "iterdir", "glob("):
            assert banned not in body, f"list_runs 面禁全扫原语 {banned}"


# ────────────────────────── P1-2 浮窗闸 + chips 去重 ──────────────────────────

class TestP12ChatFloatGate:
    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_chat_auto_open_blocked_behavior(self):
        """chatAutoOpenBlocked 真值表：关闭意愿('1')=blocked；无/其他值/
        存储故障/null store=放行（故障不拦对话可用性）。"""
        out = _run_node_js(
            "const m = await import('./pages/view_agent.js');\n"
            "const mk = (v) => ({ getItem: (k) => (k === 'rfauto-chat-closed' ? v : null) });\n"
            "const r = {};\n"
            "r.blockedWhenClosed = m.chatAutoOpenBlocked(mk('1'));\n"
            "r.openWhenAbsent = m.chatAutoOpenBlocked(mk(null));\n"
            "r.openWhenZero = m.chatAutoOpenBlocked(mk('0'));\n"
            "r.openOnStoreError = m.chatAutoOpenBlocked({ getItem: () => { throw new Error('boom'); } });\n"
            "r.openOnNullStore = m.chatAutoOpenBlocked(null);\n"
            "console.log(JSON.stringify(r));\n"
        )
        assert out == {
            "blockedWhenClosed": True, "openWhenAbsent": False,
            "openWhenZero": False, "openOnStoreError": False,
            "openOnNullStore": False,
        }

    def test_chat_float_gate_wiring(self):
        """接线钉：auto 形参闸在 openChatFloat 入口；×关闭写意愿键；显式
        打开钮清意愿；进页自动唤出走 auto=true。"""
        src = _src("view_agent.js")
        assert "function openChatFloat(focus = true, auto = false)" in src
        assert "if (auto && chatAutoOpenBlocked(localStorage)) return;" in src
        assert 'localStorage.setItem("rfauto-chat-closed", "1")' in src
        assert 'localStorage.removeItem("rfauto-chat-closed")' in src
        assert "openChatFloat(false, true)" in src

    def test_chips_container_cleared_before_append(self):
        """chips 去重：容器先清空再追加（浮窗跨页存活 win 命中早退不重建
        DOM——不清空则再进 agent 页每 chip 重复 ×2）。"""
        src = _src("view_agent.js")
        m = re.search(r"const q = document\.getElementById\(\"chat-suggest\"\);\s*\n"
                      r"\s*if \(q\) \{\s*\n\s*(q\.innerHTML = \"\";)", src)
        assert m, "chips 追加前缺容器清空"


# ────────────────────────── P2 收件箱忽略控件 ──────────────────────────

class TestP2InboxDismiss:
    @pytest.mark.skipif(_NODE is None, reason="本机无 node")
    def test_parse_and_split_behavior(self):
        """parseInboxDismissed（JSON 数组/Set/损坏/非数组容错）+
        splitPendingByDismissed（精确 token_hash 分流、缺键入 visible、
        非 Set/非数组入参容错）。"""
        out = _run_node_js(
            "const m = await import('./pages/view_agent.js');\n"
            "const r = {};\n"
            "r.parseNormal = [...m.parseInboxDismissed(JSON.stringify(['a','b']))].sort().join(',');\n"
            "r.parseNull = m.parseInboxDismissed(null).size;\n"
            "r.parseBroken = m.parseInboxDismissed('{oops').size;\n"
            "r.parseNonArray = m.parseInboxDismissed('{\"a\":1}').size;\n"
            "r.parseCoerceNum = [...m.parseInboxDismissed('[42]')].join(',');\n"
            "r.parseDropEmpty = [...m.parseInboxDismissed('[\"\", \"k\"]')].join(',');\n"
            "const pending = [{token_hash:'k1', recipe:'r1'},{token_hash:'k2', recipe:'r2'},{recipe:'r3'}];\n"
            "const s = m.splitPendingByDismissed(pending, new Set(['k1']));\n"
            "r.visIds = s.visible.map((p) => p.token_hash || '(none)').join(',');\n"
            "r.hidIds = s.hidden.map((p) => p.token_hash).join(',');\n"
            "r.noSetArgVisible = m.splitPendingByDismissed(pending).visible.length;\n"
            "r.nonArrayPending = m.splitPendingByDismissed('x', new Set()).visible.length;\n"
            "r.unmatchedGoesVisible = m.splitPendingByDismissed(pending, new Set(['zz'])).hidden.length;\n"
            "console.log(JSON.stringify(r));\n"
        )
        assert out == {
            "parseNormal": "a,b", "parseNull": 0, "parseBroken": 0,
            "parseNonArray": 0, "parseCoerceNum": "42", "parseDropEmpty": "k",
            "visIds": "k2,(none)", "hidIds": "k1",
            "noSetArgVisible": 3, "nonArrayPending": 0,
            "unmatchedGoesVisible": 0,
        }

    def test_inbox_dismiss_wiring(self):
        """接线钉：提案卡忽略钮（data-act='dismiss'）→ localStorage 记账 →
        重拉收件箱；loadInbox 分流渲染；已忽略折叠清单含恢复钮。"""
        src = _src("view_agent.js")
        assert "data-act='dismiss'" in src
        assert 'localStorage.getItem("rfauto-inbox-dismissed")' in src
        assert 'localStorage.setItem("rfauto-inbox-dismissed", JSON.stringify([...s]))' in src
        assert "splitPendingByDismissed(all, dismissed)" in src
        assert "renderDismissedBox(hidden)" in src
        assert "agent.dismiss_restore" in src
        assert "agent.inbox_all_dismissed" in src

    def test_localstorage_keys_registered_in_context_contract(self):
        """新 localStorage 键入 context.js 持久键登记（键契约表面诚实）。"""
        ctx = _src("context.js")
        assert "rfauto-chat-closed" in ctx
        assert "rfauto-inbox-dismissed" in ctx


# ────────────────────────── 变异验证记录（开发期实测，非 CI 钉）──────────────────────────
#
# 逐钉"移除修复必红"实测（读-改-还原方式逐条执行，结果全数红后还原）：
# 1. runs_recipes.list_runs 摘除 on_disk 标注行 → test_list_runs_annotates_on_disk
#    （KeyError on_disk）+ test_backend_annotation_present_not_full_scan 红。
# 2. run_detail missing-dir 分支还原旧单行 error_envelope →
#    test_indexed_missing_dir_actionable / test_unknown_run_still_honest_and_flagged 红。
# 3. view_detail.js 重试钮还原无条件可点 → test_detail_retry_disabled_for_missing_dir 红。
# 4. view_dashboard/view_runs 摘除归档分支 → test_dashboard_archived_rows_not_clickable /
#    test_runs_history_archived_rows_not_clickable 红。
# 5. view_agent.js 摘除 chatAutoOpenBlocked 闸（openChatFloat 恒复显）→
#    test_chat_float_gate_wiring 红；行为函数导出删除 → node 行为钉红。
# 6. view_agent.js 摘除 q.innerHTML = "" → test_chips_container_cleared_before_append 红。
# 7. view_agent.js 摘除忽略钮/分流 → test_inbox_dismiss_wiring 红；纯函数导出
#    删除 → node 行为钉红。
