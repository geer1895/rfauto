"""AD-1 系统提示词版本化 + prompt 回归门单测（plan_deepdive_specs §D-4）。

覆盖面：
1. 外置单源：configs/prompts/system_prompt.md（frontmatter {schema,version,
   changelog} + 正文）；get_system_prompt 读文件、与内置 _SYSTEM_PROMPT 逐字节
   相等（迁移证明）；缺文件/坏 frontmatter → 回退内置 + WARN 一次（进程级去重）。
2. 指纹面：protocol_surface 并列 prompt_sha256（旧档缺字段读回 None 不炸）；
   agent_bench 门记录增 prompt{version, sha256}。
3. 回归门 run_prompt_regression：四指标差分、n_tools 一致、pass→fail 翻转
   （人工裁决放行）、轨迹缓存与旧档兼容读回。
4. LLM 通道（#139）：一律假通道（预录回复序列 / runtime_ab 注入缝双轨
   scripted_prompt_track），门自身零网络——socket 钉死证明。
"""

from __future__ import annotations

import hashlib
import json
import logging
import socket
import sys
from pathlib import Path

import yaml
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

runner = CliRunner()

_FULL_MARK = "立即调用 propose_params"  # 完整提示指纹串（外置正文含此句）


# ---------------------------------------------------------------------------
# 工厂：小任务集 + 预录回复假通道（#139：绝不真打外网）
# ---------------------------------------------------------------------------

def _task(tid, calls, *, artifacts=None, numerics=None, family="template_render",
          level=1):
    expected = {"calls": calls}
    if artifacts is not None:
        expected["artifacts"] = artifacts
    if numerics is not None:
        expected["numeric"] = numerics
    return {"id": tid, "family": family, "level": level, "prompt": f"任务 {tid}",
            "expected": expected}


def _write_set(tmp_path, name, tasks):
    p = tmp_path / name
    p.write_text(yaml.safe_dump({"version": 1, "set_kind": "public",
                                 "tasks": tasks}, allow_unicode=True),
                 encoding="utf-8")
    return p


def _two_task_set(tmp_path):
    return _write_set(tmp_path, "mini_public.yaml", [
        _task("t1", [{"tool": "run", "args": {"adapter": "fake"}}],
              artifacts=["s_params", "run_summary"]),
        _task("t2", [{"tool": "syn", "args": {"kind": "patch"}},
                     {"tool": "run", "args": {"adapter": "fake"}}],
              artifacts=["s_params", "mesh_report"]),
    ])


def _fake_channel_provider(task, system_prompt):
    """预录回复假通道：完整提示→回放期望（满分）；降级提示→空轨迹（全掉分）。"""
    from rfauto.service.agent_bench import reference_agentbench_provider

    if _FULL_MARK in system_prompt:
        return reference_agentbench_provider(task)
    return {"trajectory": [], "artifacts": [], "numeric": {}}


# ---------------------------------------------------------------------------
# 1. 外置单源与回退
# ---------------------------------------------------------------------------

class TestExternalizedPrompt:
    def test_file_exists_with_frontmatter(self):
        from rfauto.service.r3_services import SYSTEM_PROMPT_PATH

        raw = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        assert raw.startswith("---\n")
        assert "schema: rfauto.system_prompt/1" in raw
        assert "version:" in raw and "changelog:" in raw

    def test_get_system_prompt_byte_identical_to_builtin(self):
        # 迁移逐字节证明：外置正文 == 内置 _SYSTEM_PROMPT（sha256 同）
        from rfauto.service import r3_services

        prompt = r3_services.get_system_prompt()
        assert prompt == r3_services._SYSTEM_PROMPT
        assert (hashlib.sha256(prompt.encode("utf-8")).hexdigest()
                == "6ed5bcbd0464840a6d0134c79741ea1507ba79d096b636df3fde2fc19fb21996")

    def test_meta_source_file_with_version(self):
        from rfauto.service.r3_services import get_system_prompt_meta

        meta = get_system_prompt_meta()
        assert meta["ok"] is True and meta["source"] == "file"
        assert meta["version"] == "1.0.0"
        assert meta["schema"] == "rfauto.system_prompt/1"
        assert meta["changelog"].strip()
        assert meta["errors"] == []

    def test_missing_file_falls_back_with_single_warn(
            self, tmp_path, monkeypatch, caplog):
        from rfauto.service import r3_services

        monkeypatch.setattr(r3_services, "SYSTEM_PROMPT_PATH",
                            tmp_path / "nope.md")
        monkeypatch.setattr(r3_services, "_prompt_warn_emitted", False)
        with caplog.at_level(logging.WARNING,
                             logger="rfauto.service.r3_services"):
            first = r3_services.get_system_prompt()
            second = r3_services.get_system_prompt()
        assert first == r3_services._SYSTEM_PROMPT
        assert second == r3_services._SYSTEM_PROMPT
        warns = [r for r in caplog.records
                 if r.levelno == logging.WARNING]
        assert len(warns) == 1, "WARN 必须只发一次（进程级去重）"
        meta = r3_services.get_system_prompt_meta()
        assert meta["source"] == "builtin" and meta["ok"] is False
        assert meta["errors"] and "读取失败" in meta["errors"][0]

    def test_malformed_frontmatter_falls_back(self, tmp_path, monkeypatch):
        from rfauto.service import r3_services

        bad = tmp_path / "system_prompt.md"
        bad.write_text("---\nschema: wrong/9\nversion: \"9.9\"\n---\n正文\n",
                       encoding="utf-8")
        monkeypatch.setattr(r3_services, "SYSTEM_PROMPT_PATH", bad)
        monkeypatch.setattr(r3_services, "_prompt_warn_emitted", False)
        assert r3_services.get_system_prompt() == r3_services._SYSTEM_PROMPT
        meta = r3_services.get_system_prompt_meta()
        assert meta["source"] == "builtin"
        assert any("schema 不识别" in e for e in meta["errors"])

    def test_chat_assembly_uses_get_system_prompt(self):
        # AgentChat 组装点改走公开访问口（源码静态断言，防回退到私有名）
        from pathlib import Path as _P

        from rfauto.service import r3_services

        src = _P(r3_services.__file__).read_text(encoding="utf-8")
        i = src.index('messages = [{"role": "system",')
        j = src.index("menu_lines}]", i)
        seg = src[i:j]
        assert "get_system_prompt()" in seg
        assert "_SYSTEM_PROMPT" not in seg


# ---------------------------------------------------------------------------
# 2. 指纹面
# ---------------------------------------------------------------------------

class TestFingerprintSurface:
    def test_protocol_surface_prompt_sha256(self):
        from rfauto.service.goldset_service import protocol_surface

        assert protocol_surface(["b", "a"])["prompt_sha256"] is None
        out = protocol_surface(["a"], prompt_sha256="deadbeef")
        assert out["prompt_sha256"] == "deadbeef"
        assert out["sha256"] == protocol_surface(["a"])["sha256"]  # 工具面指纹不受影响

    def test_protocol_surface_old_archive_compat(self):
        # 旧档 JSON 无 prompt_sha256 字段：读回 None 不炸（.get 容错）
        old = json.loads(json.dumps({"n_tools": 1, "tools": ["a"],
                                     "sha256": "x"}))
        assert old.get("prompt_sha256") is None

    def test_prompt_fingerprint_shape(self):
        from rfauto.service.agent_bench import prompt_fingerprint

        fp = prompt_fingerprint("abc", version="1.0.0")
        assert fp["version"] == "1.0.0"
        assert fp["sha256"] == hashlib.sha256(b"abc").hexdigest()

    def test_agentbench_gate_records_prompt_block(self):
        from rfauto.service.agent_bench import (
            reference_agentbench_provider,
            run_agentbench_regression,
        )

        r = run_agentbench_regression(
            trajectory_provider=reference_agentbench_provider,
            prompt={"version": "t1", "sha256": "aa11"})
        assert r["ok"] is True
        assert r["prompt"] == {"version": "t1", "sha256": "aa11"}
        assert r["expected_protocol"]["prompt_sha256"] == "aa11"

    def test_agentbench_gate_prompt_defaults_to_active(self):
        from rfauto.service.agent_bench import (
            reference_agentbench_provider,
            run_agentbench_regression,
        )
        from rfauto.service.r3_services import get_system_prompt_meta

        r = run_agentbench_regression(
            trajectory_provider=reference_agentbench_provider)
        assert r["prompt"]["sha256"] == get_system_prompt_meta()["sha256"]


# ---------------------------------------------------------------------------
# 3. 回归门 run_prompt_regression
# ---------------------------------------------------------------------------

class TestPromptRegressionGate:
    def test_identical_fingerprints_rejected(self):
        from rfauto.service.agent_bench import run_prompt_regression

        r = run_prompt_regression("same text", "same text", persist=False)
        assert r["gate"] == "FAIL"
        assert any("指纹相同" in x for x in r["reasons"])

    def test_reference_replay_green_with_cache(self, tmp_path):
        # 门自洽正控：参考回放不消费 prompt 内容 → 两臂恒同 → 差分零、无翻转
        from rfauto.service.agent_bench import (
            load_prompt_regression_record,
            run_prompt_regression,
        )

        full = "你是 rfauto 助手。" + _FULL_MARK
        degraded = "你是 rfauto 助手。"
        r = run_prompt_regression(full, degraded, version_a="1.0.0",
                                  version_b="0.9.0",
                                  cache_dir=tmp_path / "cache")
        assert r["ok"] is True and r["gate"] == "PASS", r["reasons"]
        assert r["mode"] == "reference_replay"
        assert all(m["delta"] == 0.0 for m in r["metrics"].values())
        assert r["n_tools_consistent"] is True and r["flips"] == []
        assert r["prompt_a"]["version"] == "1.0.0"
        assert r["prompt_a"]["sha256"] != r["prompt_b"]["sha256"]
        assert Path(r["cache_path"]).exists()

        back = load_prompt_regression_record(r["cache_path"])
        assert back["ok"] is True
        assert back["prompt_a_sha256"] == r["prompt_a"]["sha256"]
        assert back["metrics"]["abstraction"]["delta"] == 0.0

    def test_load_old_archive_without_prompt_blocks(self, tmp_path):
        # 旧档兼容：AD-1 之前形态（无 prompt 块/metrics）读回 None 不炸
        from rfauto.service.agent_bench import load_prompt_regression_record

        old = tmp_path / "old.json"
        old.write_text(json.dumps({"ok": True, "gate": "PASS"}),
                       encoding="utf-8")
        back = load_prompt_regression_record(old)
        assert back["ok"] is True
        assert back["prompt_a_sha256"] is None
        assert back["metrics"] is None and back["flips"] == []

    def test_fake_channel_detects_regression_and_flips(self, tmp_path):
        from rfauto.service.agent_bench import run_prompt_regression

        full = "完整提示。" + _FULL_MARK
        degraded = "降级提示。"
        r = run_prompt_regression(
            full, degraded,
            trajectory_provider=_fake_channel_provider,
            public_path=_two_task_set(tmp_path), persist=False)
        assert r["gate"] == "FAIL"
        assert any("任务抽象轴回归" in x for x in r["reasons"])
        assert any("执行轴回归" in x for x in r["reasons"])
        assert {f["id"] for f in r["flips"]} == {"t1", "t2"}
        flip = r["flips"][0]
        assert flip["execution_a"] == 1.0 and flip["execution_b"] == 0.0

    def test_partial_regression_within_gate_passes(self, tmp_path):
        # 单任务半档回归：t1 execution 0.5、t2 恒 1.0 → 宏 delta
        # execution = (0.5+1)/2 − 1 = −0.25（−25pp），max_regression_pp=30
        # 时门内；翻转 t1 已裁决 → 全绿（判据数学闭合验证）
        from rfauto.service.agent_bench import (
            reference_agentbench_provider,
            run_prompt_regression,
        )

        def half_degraded(task, system_prompt):
            rec = dict(reference_agentbench_provider(task))
            if _FULL_MARK not in system_prompt and task["id"] == "t1":
                rec["artifacts"] = ["s_params"]  # 2 个工件缺 1 → artifact 0.5
            return rec

        r = run_prompt_regression(
            "A" + _FULL_MARK, "B",
            trajectory_provider=half_degraded,
            public_path=_two_task_set(tmp_path), persist=False,
            max_regression_pp=30.0, adjudicated_flips=["t1"])
        assert r["ok"] is True, r["reasons"]
        assert r["flips"] == [] and len(r["flips_adjudicated"]) == 1
        assert r["metrics"]["abstraction"]["delta"] == 0.0
        assert r["metrics"]["execution"]["delta"] == -0.25

    def test_flip_adjudication_waives_flip_criterion_only(self, tmp_path):
        # 已裁决放行：翻转判据清空，但宏差分判据独立照判（不因裁决而虚绿）
        from rfauto.service.agent_bench import run_prompt_regression

        r = run_prompt_regression(
            "A" + _FULL_MARK, "B",
            trajectory_provider=_fake_channel_provider,
            public_path=_two_task_set(tmp_path), persist=False,
            adjudicated_flips=["t1", "t2"])
        assert r["flips"] == [] and len(r["flips_adjudicated"]) == 2
        assert not any("翻转" in x for x in r["reasons"])
        assert r["gate"] == "FAIL"  # 抽象/执行轴 −100pp 独立红，不凑绿
        assert any("任务抽象轴回归" in x for x in r["reasons"])

    def test_n_tools_mismatch_rejected(self, tmp_path):
        from rfauto.service.agent_bench import (
            load_bench_set,
            reference_agentbench_provider,
            run_prompt_regression,
        )
        from rfauto.service.goldset_service import goldset_expected_tools

        set_path = _two_task_set(tmp_path)
        expected = goldset_expected_tools(load_bench_set(set_path))

        r_missing = run_prompt_regression(
            "A", "B", trajectory_provider=reference_agentbench_provider,
            public_path=set_path, persist=False,
            runtime_tools_a=expected[:-1], runtime_tools_b=expected)
        assert r_missing["gate"] == "FAIL"
        assert any("协议面回归" in x for x in r_missing["reasons"])

        r_extra = run_prompt_regression(
            "A", "B", trajectory_provider=reference_agentbench_provider,
            public_path=set_path, persist=False,
            runtime_tools_a=expected, runtime_tools_b=[*expected, "ghost_tool"])
        assert r_extra["gate"] == "FAIL"
        assert r_extra["n_tools_consistent"] is False
        assert any("n_tools 不一致" in x for x in r_extra["reasons"])

    def test_provider_exception_is_red(self, tmp_path):
        from rfauto.service.agent_bench import run_prompt_regression

        def boom(task, system_prompt):
            raise RuntimeError("通道故障")

        r = run_prompt_regression("A", "B", trajectory_provider=boom,
                                  public_path=_two_task_set(tmp_path),
                                  persist=False)
        assert r["gate"] == "FAIL"
        assert any("轨迹提供器异常" in x for x in r["reasons"])
        assert any("通道故障" in x for x in r["reasons"])

    def test_records_mode_with_coverage_check(self, tmp_path):
        from rfauto.service.agent_bench import (
            reference_agentbench_provider,
            run_prompt_regression,
        )

        set_path = _two_task_set(tmp_path)
        tasks = yaml.safe_load(set_path.read_text(encoding="utf-8"))["tasks"]
        recs_a = [reference_agentbench_provider(t) | {"id": t["id"]}
                  for t in tasks]
        recs_b = [recs_a[0],
                  {"id": "t2", "trajectory": [], "artifacts": [],
                   "numeric": {}}]

        r = run_prompt_regression("A", "B", records_a=recs_a, records_b=recs_b,
                                  public_path=set_path, persist=False)
        assert r["gate"] == "FAIL" and r["mode"] == "records"
        assert {f["id"] for f in r["flips"]} == {"t2"}

        r_gap = run_prompt_regression("A", "B", records_a=recs_a[:1],
                                      records_b=recs_a[:1],
                                      public_path=set_path, persist=False)
        assert r_gap["gate"] == "FAIL"
        assert any("未覆盖全部基准任务" in x for x in r_gap["reasons"])


# ---------------------------------------------------------------------------
# 4. runtime_ab 双轨通道（scripted_prompt_track，#139 零网络）
# ---------------------------------------------------------------------------

class TestScriptedPromptTrack:
    def test_dual_track_same_trajectory_and_structure(self):
        from rfauto.service.runtime_ab import (
            ScriptedTurn,
            scripted_prompt_track,
        )

        turns = [ScriptedTurn(tool_calls=[("run", {"recipe": "r.yaml",
                                                   "adapter": "fake"})]),
                 ScriptedTurn(text="完成")]
        out = scripted_prompt_track("系统提示A" + _FULL_MARK, list(turns),
                                    user_prompt="渲染模板")
        assert out["dual_track_consistent"] is True
        assert out["trajectory"] == [
            {"tool": "run", "args": {"recipe": "r.yaml", "adapter": "fake"}}]
        assert out["finish_reasons"] == {"builtin": "stop",
                                         "pydantic_ai": "stop"}
        # system 文本进两轨 messages → 出站载荷可见（prompt 变体在结构量上可分辨）；
        # 序列化器不同源（ToolSpec str 化 vs schema dict），字节数不比相等，只比可见
        assert out["builtin_wire_chars"] > 0
        assert out["pydantic_ai_wire_chars"] > 0

    def test_prompt_variant_changes_wire_chars(self):
        from rfauto.service.runtime_ab import (
            ScriptedTurn,
            scripted_prompt_track,
        )

        turns = [ScriptedTurn(text="结论。")]
        short = scripted_prompt_track("短提示", list(turns))
        long = scripted_prompt_track("长提示" + "很长的系统规范" * 30, list(turns))
        assert long["builtin_wire_chars"] > short["builtin_wire_chars"]

    def test_track_feeds_regression_gate(self, tmp_path):
        # 双轨注入缝作为门的假通道（预录回复按 system prompt 键控）→ 端到端
        from rfauto.service.agent_bench import (
            reference_agentbench_provider,
            run_prompt_regression,
        )
        from rfauto.service.runtime_ab import (
            ScriptedTurn,
            scripted_prompt_track,
        )

        turns_full = [ScriptedTurn(tool_calls=[("run", {"adapter": "fake"})]),
                      ScriptedTurn(text="完成")]
        turns_bad = [ScriptedTurn(text="我直接猜一个参数。")]

        def provider(task, system_prompt):
            turns = turns_full if _FULL_MARK in system_prompt else turns_bad
            out = scripted_prompt_track(system_prompt, list(turns),
                                        user_prompt=task["prompt"])
            assert out["dual_track_consistent"] is True
            rec = {"trajectory": out["trajectory"]}
            if _FULL_MARK in system_prompt:
                full = reference_agentbench_provider(task)
                rec.update({"artifacts": full["artifacts"],
                            "numeric": full["numeric"]})
            else:
                rec.update({"artifacts": [], "numeric": {}})
            return rec

        r = run_prompt_regression(
            "提示" + _FULL_MARK, "提示（降级）",
            trajectory_provider=provider,
            public_path=_two_task_set(tmp_path), persist=False)
        assert r["gate"] == "FAIL"
        assert any("任务抽象轴回归" in x for x in r["reasons"])
        assert len(r["flips"]) == 2


# ---------------------------------------------------------------------------
# 5. CLI 薄壳 + 零网络钉（#139）
# ---------------------------------------------------------------------------

class TestCliPromptRegression:
    def _write_prompts(self, tmp_path):
        pa = tmp_path / "a.txt"
        pb = tmp_path / "b.txt"
        pa.write_text("提示A" + _FULL_MARK, encoding="utf-8")
        pb.write_text("提示B（降级）", encoding="utf-8")
        return pa, pb

    def test_reference_replay_pass_exit0_no_persist(self, tmp_path):
        from rfauto.cli.bench_app import bench_app

        pa, pb = self._write_prompts(tmp_path)
        result = runner.invoke(bench_app, [
            "prompt-regression", "--prompt-a", str(pa), "--prompt-b", str(pb),
            "--version-a", "1.0.0", "--version-b", "0.9.0", "--no-persist"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["ok"] is True and payload["mode"] == "reference_replay"

    def test_identical_prompts_fail_exit1(self, tmp_path):
        from rfauto.cli.bench_app import bench_app

        pa, _ = self._write_prompts(tmp_path)
        result = runner.invoke(bench_app, [
            "prompt-regression", "--prompt-a", str(pa), "--prompt-b", str(pa),
            "--no-persist"])
        assert result.exit_code == 1
        assert "指纹相同" in result.output

    def test_missing_prompt_file_exit2(self, tmp_path):
        from rfauto.cli.bench_app import bench_app

        pa, _ = self._write_prompts(tmp_path)
        result = runner.invoke(bench_app, [
            "prompt-regression", "--prompt-a", str(pa),
            "--prompt-b", str(tmp_path / "ghost.txt"), "--no-persist"])
        assert result.exit_code == 2

    def test_records_mode_flip_fail_exit1(self, tmp_path):
        from rfauto.cli.bench_app import bench_app

        pa, pb = self._write_prompts(tmp_path)
        set_path = _two_task_set(tmp_path)
        from rfauto.service.agent_bench import reference_agentbench_provider
        tasks = yaml.safe_load(set_path.read_text(encoding="utf-8"))["tasks"]
        recs_a = [reference_agentbench_provider(t) | {"id": t["id"]}
                  for t in tasks]
        recs_b = [recs_a[0],
                  {"id": "t2", "trajectory": [], "artifacts": [],
                   "numeric": {}}]
        ra = tmp_path / "a.json"
        rb = tmp_path / "b.json"
        ra.write_text(json.dumps(recs_a, ensure_ascii=False), encoding="utf-8")
        rb.write_text(json.dumps(recs_b, ensure_ascii=False), encoding="utf-8")
        result = runner.invoke(bench_app, [
            "prompt-regression", "--prompt-a", str(pa), "--prompt-b", str(pb),
            "--public-set", str(set_path), "--records-a", str(ra),
            "--records-b", str(rb), "--no-persist"])
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert {f["id"] for f in payload["flips"]} == {"t2"}

    def test_gate_is_offline(self, tmp_path, monkeypatch):
        # #139 钉：门全链路零网络——socket 连接即炸，门照常跑完
        from rfauto.cli.bench_app import bench_app

        def _boom(*_a, **_k):
            raise AssertionError("回归门不得发起网络连接（#139）")

        monkeypatch.setattr(socket.socket, "connect", _boom)
        monkeypatch.setattr(socket, "create_connection", _boom)
        pa, pb = self._write_prompts(tmp_path)
        result = runner.invoke(bench_app, [
            "prompt-regression", "--prompt-a", str(pa), "--prompt-b", str(pb),
            "--no-persist"])
        assert result.exit_code == 0, result.output
