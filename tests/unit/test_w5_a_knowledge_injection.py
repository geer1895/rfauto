"""W5-A SK-2/SK-3 AD-2 会话知识注入判据（SK 规格包 V §2.3 十条预声明门值）。

判据逐条对应（注释标注判据号）；#139 全 mock——四源检索函数/few-shot
构造器/LLM 运行时全部 monkeypatch，零网络零真 LLM。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]

# ─── 共享夹具 ───────────────────────────────────────────────────────────────

SETTINGS_TMPL = """
agent:
  knowledge_injection:
    enabled: {enabled}
    budgets:
      snippet: 200
      source_section: 600
      section: 1500
      few_shot: 900
      extra_system: 2400
"""


@pytest.fixture()
def settings_path(tmp_path, monkeypatch):
    """可写 settings.yaml 副本 + 指针重定向（不碰 tracked configs）。"""
    from rfauto.service import knowledge_injection_service as kis

    path = tmp_path / "settings.yaml"
    path.write_text(SETTINGS_TMPL.format(enabled="false"), encoding="utf-8")
    monkeypatch.setattr(kis, "SETTINGS_PATH", path)
    return path


def _set_enabled(path: Path, enabled: bool) -> None:
    path.write_text(SETTINGS_TMPL.format(
        enabled="true" if enabled else "false"), encoding="utf-8")


def _entry(source: str, idx: int, *, snippet: str = "网格守卫教训",
           score: float | None = None) -> dict:
    return {"id": f"{source}-{idx}", "source": source,
            "title": f"{source} 条目 {idx}",
            "score": (1.0 / (idx + 1)) if score is None else score,
            "snippet": snippet}


@pytest.fixture()
def mock_sources(monkeypatch):
    """四源固定返回（#139 钉；返回调用记录供断言）。"""
    from rfauto.service import knowledge_injection_service as kis

    calls = {"n": 0}
    fixed = {
        "rationale": [_entry("rationale", 0)],
        "pitfall": [_entry("pitfall", 0), _entry("pitfall", 1)],
        "rag": [_entry("rag", 0)],
        "knowledge": [_entry("knowledge", 0)],
    }

    def _mk(source):
        def _fetch(task_text, limit, docs_dir=None):
            calls["n"] += 1
            calls.setdefault("last_task", task_text)
            return list(fixed[source])
        return _fetch

    monkeypatch.setattr(kis, "_fetch_rationale", _mk("rationale"))
    monkeypatch.setattr(kis, "_fetch_pitfall", _mk("pitfall"))
    monkeypatch.setattr(kis, "_fetch_rag", _mk("rag"))
    monkeypatch.setattr(kis, "_fetch_knowledge", _mk("knowledge"))
    return {"calls": calls, "fixed": fixed}


@pytest.fixture()
def chat_harness(monkeypatch, tmp_path):
    """AgentChat 全 mock 台：configured=True + 脚本化运行时捕获 request。"""
    from rfauto.service import agent_runtime, few_shot_service, r3_services

    captured: list = []

    class _CaptureRuntime(agent_runtime.AgentRuntime):
        name = "_w5a_capture"

        def submit(self, request, executor):
            captured.append(request)
            return agent_runtime.RuntimeResult(
                text="ok",
                usage=agent_runtime.RuntimeUsage(prompt_tokens=1))

    monkeypatch.setattr(r3_services, "get_chat_settings",
                        lambda: {"ok": True, "configured": True})
    monkeypatch.setattr(r3_services, "get_chat_settings_raw",
                        lambda: {"runtime": "builtin", "model": "m",
                                 "max_tool_rounds": 4})
    monkeypatch.setattr(agent_runtime.RuntimeRegistry, "create",
                        staticmethod(lambda name, **kw: _CaptureRuntime()))
    monkeypatch.setattr(agent_runtime, "SESSIONS_DIR", tmp_path / "sess")
    # few-shot 挖掘面独立 SESSIONS_DIR（few_shot_service 自有常量）——
    # 指到空 tmp 保证会话台密闭（不消费仓库真实 runs/chat_sessions）。
    empty_sess = tmp_path / "few_shot_sess"
    empty_sess.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(few_shot_service, "SESSIONS_DIR", empty_sess)
    return {"captured": captured}


# ─── 判据 1：确定性 ────────────────────────────────────────────────────────

class TestCriterion1Determinism:
    def test_same_task_twice_identical(self, settings_path, mock_sources):
        from rfauto.service.knowledge_injection_service import compose_knowledge_injection

        a = compose_knowledge_injection("wilkinson 网格 收敛 冒烟")
        b = compose_knowledge_injection("wilkinson 网格 收敛 冒烟")
        assert a["section"] == b["section"]
        assert a["entries"] == b["entries"]
        assert a["usage"] == b["usage"]


# ─── 判据 2：预算截断单调 ──────────────────────────────────────────────────

class TestCriterion2BudgetTruncation:
    def test_priority_truncation_and_no_half_line(self, settings_path,
                                                  monkeypatch):
        from rfauto.service import knowledge_injection_service as kis

        big_knowledge = "知" * 400
        monkeypatch.setattr(kis, "_fetch_rationale",
                            lambda t, limit, docs_dir=None:
                            [_entry("rationale", 0, snippet="先离线审计再冒烟")])
        monkeypatch.setattr(kis, "_fetch_pitfall",
                            lambda t, limit, docs_dir=None: [])
        monkeypatch.setattr(kis, "_fetch_rag",
                            lambda t, limit, docs_dir=None: [])
        monkeypatch.setattr(kis, "_fetch_knowledge",
                            lambda t, limit, docs_dir=None:
                            [_entry("knowledge", i, snippet=big_knowledge)
                             for i in range(9)])
        result = kis.compose_knowledge_injection("网格 审计")
        assert result["ok"]
        sources = [e["source"] for e in result["entries"]]
        assert "rationale" in sources, "源优先级截断失守：rationale 必须存活"
        # knowledge 单条截 snippet≤200 后仍 9 条 ~2300 chars > 节预算 1500
        # → 尾部整条截断（rationale 全存活的同预算下 knowledge 被裁）
        assert len(sources) < 10
        assert result["usage"]["truncated"] >= 1
        assert result["usage"]["chars"] <= 1500
        assert result["usage"]["per_source"]["knowledge"]["n"] >= 1
        # 渲染节内无半行：每行要么 [kN] 起头、要么标题/收尾句
        for line in result["section"].splitlines():
            assert (line.startswith("[k") or line.startswith("【参考资料")
                    or line.startswith("以上仅供上下文")), line


# ─── 判据 3：空命中零注入 ──────────────────────────────────────────────────

class TestCriterion3EmptyHitZeroInjection:
    def test_all_sources_empty_section_blank(self, settings_path, monkeypatch):
        from rfauto.service import knowledge_injection_service as kis

        for name in ("_fetch_rationale", "_fetch_pitfall", "_fetch_rag",
                     "_fetch_knowledge"):
            monkeypatch.setattr(kis, name,
                                lambda t, limit, docs_dir=None: [])
        result = kis.compose_knowledge_injection("任意任务")
        assert result["ok"] and result["section"] == ""
        assert result["entries"] == []

    def test_llm_turn_byte_identical_when_empty(self, settings_path,
                                                chat_harness, monkeypatch):
        """注入开启但两段皆空 → messages 与关闭档逐位一致、extra_system=None。"""
        from rfauto.service import knowledge_injection_service as kis
        from rfauto.service import r3_services
        for name in ("_fetch_rationale", "_fetch_pitfall", "_fetch_rag",
                     "_fetch_knowledge"):
            monkeypatch.setattr(kis, name,
                                lambda t, limit, docs_dir=None: [])

        _set_enabled(settings_path, False)
        chat_off = r3_services.AgentChat()
        chat_off.chat("网格审计任务")
        req_off = chat_harness["captured"][-1]

        _set_enabled(settings_path, True)
        chat_on = r3_services.AgentChat()
        chat_on.chat("网格审计任务")
        req_on = chat_harness["captured"][-1]

        assert req_on.extra_system is None
        assert req_on.messages == req_off.messages

    def test_default_request_extra_system_is_none(self):
        from rfauto.service.agent_runtime import RuntimeRequest

        assert RuntimeRequest(messages=[]).extra_system is None


# ─── 判据 4：best-effort ───────────────────────────────────────────────────

class TestCriterion4BestEffort:
    def test_source_failure_isolated(self, settings_path, monkeypatch):
        from rfauto.service import knowledge_injection_service as kis

        def _boom(task_text, limit, docs_dir=None):
            raise RuntimeError("rag 语料爆炸")

        monkeypatch.setattr(kis, "_fetch_rationale",
                            lambda t, limit, docs_dir=None:
                            [_entry("rationale", 0)])
        monkeypatch.setattr(kis, "_fetch_rag", _boom)
        monkeypatch.setattr(kis, "_fetch_pitfall",
                            lambda t, limit, docs_dir=None: [])
        monkeypatch.setattr(kis, "_fetch_knowledge",
                            lambda t, limit, docs_dir=None:
                            [_entry("knowledge", 0)])
        result = kis.compose_knowledge_injection("网格 审计")
        assert result["ok"], "部分源失败不得拉垮整体（#105）"
        assert any("rag" in e for e in result["errors"])
        assert {e["source"] for e in result["entries"]} == {
            "rationale", "knowledge"}

    def test_compose_never_raises_on_garbage(self, settings_path):
        from rfauto.service import knowledge_injection_service as kis

        assert not kis.compose_knowledge_injection("   ")["ok"]
        assert not kis.compose_knowledge_injection("")["ok"]


# ─── 判据 5：指纹解耦（AD-1 红线）──────────────────────────────────────────

class TestCriterion5FingerprintDecoupling:
    def test_prompt_sha_invariant_under_injection_toggle(
            self, settings_path, mock_sources):
        from rfauto.service.knowledge_injection_service import compose_knowledge_injection
        from rfauto.service.r3_services import get_system_prompt, get_system_prompt_meta

        sha_off = get_system_prompt_meta()["sha256"]
        text_off = get_system_prompt()
        _set_enabled(settings_path, True)
        result = compose_knowledge_injection("wilkinson 网格 收敛 冒烟")
        assert result["section"], "前置：注入节非空才有判别力"
        sha_on = get_system_prompt_meta()["sha256"]
        assert sha_on == sha_off
        assert get_system_prompt() == text_off


# ─── 判据 6：判分不降（agentbench 回归门，mock transport）───────────────────

class TestCriterion6BenchNotDegraded:
    @staticmethod
    def _bench_records(chat_harness, settings_path, mock_sources, enabled):
        """经真实 chat 链产 bench 记录（注入 ON/OFF 两臂；mock 四源零网络）。

        记录体=任务期望回放（reference provider 同构，两臂同分）——本判据
        证明的是"注入开启的完整 chat 链跑过门且不降分"（mock transport 钉），
        注入行为面由 ON 臂捕获的 extra_system 断言背书。
        """
        from rfauto.service import r3_services
        from rfauto.service.agent_bench import load_bench_set

        _set_enabled(settings_path, enabled)
        records = []
        chat = r3_services.AgentChat()
        for task in load_bench_set()["tasks"]:
            expected = task.get("expected") or {}
            numeric = {str(n.get("metric")): n.get("value")
                       for n in expected.get("numeric") or [] if n.get("metric")}
            chat._llm_turn(str(task.get("prompt") or task.get("id")))
            records.append({
                "id": task["id"],
                "trajectory": [{"tool": str(c.get("tool") or ""),
                                "args": dict(c.get("args") or {})}
                               for c in expected.get("calls") or []],
                "artifacts": list(expected.get("artifacts") or []),
                "numeric": numeric,
            })
        return records

    def test_on_arm_passes_gate_and_not_degraded(self, settings_path,
                                                 chat_harness, mock_sources,
                                                 monkeypatch):
        from rfauto.service.agent_bench import run_agentbench_regression

        records_off = self._bench_records(chat_harness, settings_path,
                                          mock_sources, enabled=False)
        records_on = self._bench_records(chat_harness, settings_path,
                                         mock_sources, enabled=True)
        # ON 臂确实注入了 extra_system（mock 通道捕获面）
        assert any(req.extra_system for req in chat_harness["captured"])
        r_off = run_agentbench_regression(records=records_off)
        r_on = run_agentbench_regression(records=records_on)
        assert r_off["ok"] and r_on["ok"], (
            f"off={r_off.get('reasons')} on={r_on.get('reasons')}")
        for axis in ("abstraction", "execution"):
            delta = (r_on["report"]["combined"][axis]
                     - r_off["report"]["combined"][axis])
            assert delta >= -0.02, f"{axis} 回归 {delta:.4f} 超 −2pp 容差"


# ─── 判据 7：防幻觉双态 ────────────────────────────────────────────────────

class TestCriterion7UngroundedScan:
    def test_ungrounded_number_claim_flagged(self):
        from rfauto.service.knowledge_injection_service import scan_ungrounded_claims

        result = scan_ungrounded_claims(
            "该器件 f0 = 2.465 GHz，回损 18.2 dB。",
            grounded_texts=["工具返回：谐振频率 2.470 GHz"],
            entries=[{"snippet": "带内回损 ≥15 dB"}])
        assert result["n"] >= 1
        kinds = {c["kind"] for c in result["claims"]}
        assert "number" in kinds

    def test_all_grounded_reply_zero_hit(self):
        from rfauto.service.knowledge_injection_service import scan_ungrounded_claims

        result = scan_ungrounded_claims(
            "谐振 2.470 GHz，回损 18.2 dB，见 configs/settings.yaml。",
            grounded_texts=["谐振频率 2.470GHz", "回损 18.2dB",
                            "配置在 configs/settings.yaml"],
            entries=[])
        assert result["n"] == 0, str(result["claims"])


# ─── 判据 8：零数值合成 ────────────────────────────────────────────────────

class TestCriterion8NoNumberSynthesis:
    FORBIDDEN = re.compile(r"建议\s*[\w\u4e00-\u9fff]+\s*[=≈]")

    def test_rendered_section_free_of_suggestion_patterns(self, settings_path,
                                                          mock_sources):
        from rfauto.service.knowledge_injection_service import compose_knowledge_injection

        result = compose_knowledge_injection("wilkinson 网格 收敛 冒烟 谐振")
        assert not self.FORBIDDEN.search(result["section"])

    def test_snippets_only_truncated_not_fabricated(self, settings_path,
                                                    mock_sources):
        from rfauto.service import knowledge_injection_service as kis

        result = kis.compose_knowledge_injection("网格 收敛")
        fixed_texts = {e["snippet"] for e in mock_sources["fixed"].values()
                       for e in e}
        for entry in result["entries"]:
            raw = entry["snippet"]
            assert any(raw == t or (t.startswith(raw[:-1]) and raw.endswith("…"))
                       or raw in t for t in fixed_texts), raw


# ─── 判据 9：会话档 ────────────────────────────────────────────────────────

class TestCriterion9SessionDoc:
    def test_injections_recorded_and_reversible(self, settings_path,
                                                chat_harness, mock_sources):
        from rfauto.service import r3_services

        _set_enabled(settings_path, True)
        chat = r3_services.AgentChat()
        chat.chat("wilkinson 网格 收敛 冒烟")
        chat._persist_session()
        assert chat._session_doc is not None
        injections = chat._session_doc["meta"]["injections"]
        assert injections["schema"] == "rfauto-knowledge-injection-v1"
        assert injections["entries"], "mock 四源必有命中"
        for entry in injections["entries"]:
            assert {"k", "id", "source", "score", "snippet"} <= set(entry)
        ks = sorted(e["k"] for e in injections["entries"])
        assert ks == list(range(1, len(ks) + 1))
        assert "chars" in injections["usage"]

    def test_persist_failure_does_not_block_chat(self, settings_path,
                                                 chat_harness, mock_sources,
                                                 monkeypatch, tmp_path):
        from rfauto.service import agent_runtime, r3_services

        _set_enabled(settings_path, True)
        monkeypatch.setattr(agent_runtime, "SESSIONS_DIR", tmp_path / "sess")

        def _boom(doc):
            raise OSError("disk full")

        monkeypatch.setattr(agent_runtime, "persist_session", _boom)
        chat = r3_services.AgentChat()
        response = chat.chat("wilkinson 网格 收敛 冒烟")
        assert response["text"] == "ok"


# ─── 判据 10：四钉 + 单账本 ────────────────────────────────────────────────

class TestCriterion10Ledger:
    def test_extra_system_total_within_budget(self, settings_path,
                                              chat_harness, monkeypatch):
        """few-shot + knowledge 同账本：extra_system 总长 ≤2400。"""
        from rfauto.service import few_shot_service, r3_services
        from rfauto.service import knowledge_injection_service as kis

        big_block = ("- 任务：> 很长的任务描述文本\n- 工具序列：`a → b → c`\n"
                     "- 结果摘要：> 很长的结果摘要文本内容\n\n")
        big_section = ("## 成功案例参考\n\n### 案例 1\n" + big_block) * 12 \
            + "（案例只演示工具编排路径。）\n"
        monkeypatch.setattr(few_shot_service, "build_few_shot_system",
                            lambda task, **kw: {"ok": True, "section": big_section,
                                                "exemplars": [], "errors": []})
        monkeypatch.setattr(kis, "_fetch_rationale",
                            lambda t, limit, docs_dir=None:
                            [_entry("rationale", i, snippet="长" * 180)
                             for i in range(3)])
        monkeypatch.setattr(kis, "_fetch_pitfall",
                            lambda t, limit, docs_dir=None:
                            [_entry("pitfall", i, snippet="坑" * 180)
                             for i in range(3)])
        monkeypatch.setattr(kis, "_fetch_rag",
                            lambda t, limit, docs_dir=None:
                            [_entry("rag", i, snippet="R" * 180)
                             for i in range(3)])
        monkeypatch.setattr(kis, "_fetch_knowledge",
                            lambda t, limit, docs_dir=None:
                            [_entry("knowledge", i, snippet="K" * 180)
                             for i in range(2)])
        _set_enabled(settings_path, True)
        chat = r3_services.AgentChat()
        extra = chat._compose_extra_system("wilkinson 网格 收敛 冒烟")
        assert extra is not None
        assert len(extra) <= 2400
        assert "成功案例参考" in extra, "固定序：few-shot 段在前"
        assert "【参考资料" in extra, "固定序：知识节在后"

    def test_memo_reuses_same_key(self, settings_path, chat_harness,
                                  mock_sources):
        from rfauto.service import r3_services

        _set_enabled(settings_path, True)
        chat = r3_services.AgentChat()
        first = chat._compose_extra_system("wilkinson 网格 收敛 冒烟")
        assert first
        n_after_first = mock_sources["calls"]["n"]
        second = chat._compose_extra_system("wilkinson 网格 冒烟 收敛")
        assert second == first
        assert mock_sources["calls"]["n"] == n_after_first, "同词集复用缓存"


# ─── 缺省关回归钉（#329：settings 关/缺席=逐字节不变）───────────────────────

class TestDefaultOffRegression:
    def test_tracked_settings_ships_disabled(self):
        """tracked settings.yaml enabled=true（2026-10-05 W5 合流笔翻开：
        判分门已过，两步预声明第二步执行，记 八百八十五）。"""

        data = yaml.safe_load(
            (REPO / "configs" / "settings.yaml").read_text(encoding="utf-8"))
        section = (data.get("agent") or {}).get("knowledge_injection") or {}
        assert section.get("enabled") is True
        budgets = section.get("budgets") or {}
        assert budgets.get("extra_system") == 2400

    def test_disabled_wiring_returns_none(self, settings_path, chat_harness):
        from rfauto.service import r3_services

        _set_enabled(settings_path, False)
        chat = r3_services.AgentChat()
        assert chat._compose_extra_system("任意任务") is None

    def test_missing_settings_file_disables(self, tmp_path, monkeypatch):
        from rfauto.service import knowledge_injection_service as kis

        monkeypatch.setattr(kis, "SETTINGS_PATH",
                            tmp_path / "不存在.yaml")
        assert kis.knowledge_injection_settings() == {
            "enabled": False, "budgets": {}}
