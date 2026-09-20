"""阶段 2.2 增量：Δrobust 改写表测试（LLM 注入，零网络——#139）。"""

from __future__ import annotations

import json

import pytest
import yaml


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield


def _mini_goldset(tmp_path):
    tasks = [
        {"id": "t1", "level": "L1", "prompt": "跑一次 wilkinson 配方的 fake 仿真",
         "expected": {"calls": [{"tool": "create_run",
                                 "args": {"adapter": "fake"}}]}},
        {"id": "t2", "level": "L2", "prompt": "列出最近 runs 再对比最新两个的指标",
         "expected": {"calls": [{"tool": "get_run_artifacts", "args": {}},
                                {"tool": "compare_runs", "args": {}}]}},
    ]
    path = tmp_path / "gold.yaml"
    path.write_text(yaml.safe_dump({"tasks": tasks}, allow_unicode=True),
                    encoding="utf-8")
    return str(path)


def _fake_llm(messages):
    """注入版 LLM：机械改写（原文+后缀），结构同真实响应。"""
    user = messages[-1]["content"]
    return json.dumps({"paraphrases": [user.replace("，", "。") + " 谢谢。",
                                       "帮我：" + user]})


class TestBuildRewriteTable:
    def test_build_with_injected_llm(self, tmp_path):
        from rfauto.service.robust_rewrite import build_rewrite_table

        gold = _mini_goldset(tmp_path)
        r = build_rewrite_table(gold, n_per_task=2,
                                out_path=tmp_path / "rt.json",
                                completion_fn=_fake_llm)
        assert r["ok"], r.get("failures")
        assert r["n_tasks_with_paraphrases"] == 2
        for item in r["table"].values():
            assert item["paraphrases"]
            for p in item["paraphrases"]:
                assert p.strip().lower() != item["original"].strip().lower()
        assert (tmp_path / "rt.json").exists()

    def test_dedup_and_cap(self, tmp_path):
        """重复改写去重、条数封顶 n_per_task。"""
        from rfauto.service.robust_rewrite import build_rewrite_table

        def dup_llm(messages):  # 全部返回相同文本 → 只留 1 条
            return json.dumps({"paraphrases": ["同款改写", "同款改写",
                                               "同款改写"]})

        gold = _mini_goldset(tmp_path)
        r = build_rewrite_table(gold, n_per_task=2,
                                out_path=tmp_path / "rt.json",
                                completion_fn=dup_llm)
        assert r["ok"]
        assert len(r["table"]["t1"]["paraphrases"]) == 1

    def test_unconfigured_channel_fails_clean(self, tmp_path, monkeypatch):
        """默认通道未配置 → 显式失败不炸不打网络（#139）。"""
        from rfauto.service import robust_rewrite as rr

        def _boom(_messages):
            raise RuntimeError("LLM 通道未配置")

        monkeypatch.setattr(rr, "_default_completion", _boom)
        gold = _mini_goldset(tmp_path)
        r = rr.build_rewrite_table(gold, out_path=tmp_path / "rt.json")
        assert not r["ok"]
        assert any("通道未配置" in f for f in r["failures"])


class TestEvaluateRobustness:
    def _table(self, tmp_path):
        from rfauto.service.robust_rewrite import build_rewrite_table

        gold = _mini_goldset(tmp_path)
        r = build_rewrite_table(gold, n_per_task=1,
                                out_path=tmp_path / "rt.json",
                                completion_fn=_fake_llm)
        assert r["ok"]
        return gold, tmp_path / "rt.json"

    def test_delta_math_and_gate(self, tmp_path):
        from rfauto.service.robust_rewrite import evaluate_robustness

        gold, rt = self._table(tmp_path)
        good = [{"id": "t1", "trajectory": [
                    {"tool": "create_run", "args": {"adapter": "fake"}}]},
                {"id": "t2", "trajectory": [
                    {"tool": "get_run_artifacts", "args": {}},
                    {"tool": "compare_runs", "args": {}}]}]
        r = evaluate_robustness(good, rt, gold)
        assert r["ok"], r.get("errors")
        assert r["macro"]["delta_tsa"] == 0.0
        assert r["robust_gate"] == "PASS"

        bad = [{"id": "t1", "trajectory": [
                    {"tool": "doctor", "args": {}},  # 答非所问
                    {"tool": "create_run", "args": {"adapter": "hfss"}}]},
               {"id": "t2", "trajectory": [
                    {"tool": "list_models", "args": {}}]}]
        r2 = evaluate_robustness(bad, rt, gold)
        assert r2["macro"]["delta_tsa"] < 0
        assert r2["robust_gate"] == "FAIL"
        assert r2["rows"][0]["delta"]["tsa"] == 0   # t1 子序列仍命中
        assert r2["rows"][1]["delta"]["tsa"] == -1  # t2 完全脱靶

    def test_missing_table_rejected(self, tmp_path):
        from rfauto.service.robust_rewrite import evaluate_robustness

        gold = _mini_goldset(tmp_path)
        assert not evaluate_robustness([], tmp_path / "nope.json", gold)["ok"]
