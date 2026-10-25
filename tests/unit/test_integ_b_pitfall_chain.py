"""INTEG-B 席跨模块集成测试：坑账链全链一致（aurora_d INTEG-B，2026-10-14）.

链条（合成源料从生产者打到消费端，全程零网络零 LLM，#139）：

    scripts/pitfall_index.py build_index（合成 内核立规注记.md+散档+消费指针）
      → canonical JSON 落盘（dumps_canonical 确定性）
        → service/pitfall_index_service.load_pitfall_index（同 schema 契约
          零改动加载+validate 校验）
          → CLI rfauto pitfalls search/get（--index 指向合成产物；CliRunner）

钉面：全链条目身份一致（解析产物 == loader 条目 == CLI get entry 逐键相等）、
检索召回一致（关键词/坑号/域过滤三入口命中同一条目）、确定性（两次构建
逐字节同、canonical 往返逐字节同）；错误路径（节标题缺失 ValueError、
坏 JSON/错 schema_version/重复 id 的 loader 拒载、CLI 未命中退出码 1、
usage 错误退出码 2）；边界（无坑号条目 A<行> 行锚 id、连号组展开进
--number 召回、解析失败如实计数不静默丢、散档 id 与全局坑号隔离）。

既有单测的分工：test_kb_b_pitfall_index 钉真 内核立规注记.md 产物与解析启发式、
test_pitfall_index_service 钉 loader/检索纯函数——本文件补「同一份数据从
解析器流到 CLI 消费端身份不变形」的跨模块合成链。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

import pytest
import yaml
from typer.testing import CliRunner

# cli.main 必须先于任何域模块导入：domain 模块 import 期自注册 add_typer，
# 域先于 main 会让 pitfalls 位次漂移打红 test_cli_registration_order 金快照
# （test_kb_b 同款前车之鉴）；域内纯函数 search_entries 在唯一消费用例内
# 惰性导入，避开 isort 排序与运行序的冲突（I001 会把域排回 main 之前）。
from rfauto.cli.main import app  # 先于域模块导入（注册位次锁序）
from rfauto.service.pitfall_index_service import (
    load_pitfall_index,
    pitfall_by_id,
    pitfall_search,
    validate_pitfall_index,
)

# ── scripts/pitfall_index.py 按文件路径装载（test_kb_b 同款模式）──────────
_SCRIPT = REPO / "scripts" / "pitfall_index.py"
_SPEC = importlib.util.spec_from_file_location("integ_b_pitfall_builder",
                                               _SCRIPT)
pitfall_index = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(pitfall_index)

runner = CliRunner()

_AGENTS_HEAD = "# 合成 AGENTS\n\n## 环境硬规则\n\n0. 前置节不进坑账。\n\n"

# 三条合成坑：#900（含折行续行）、#810-#812 连号组、无坑号（A<行> 行锚）；
# 末尾一个空条目占号（解析失败如实计数面）。## 收尾节闭合踩坑速查节。
_AGENTS_PITFALLS = """## 踩坑速查

> 速查注记行（blockquote，结构性跳过）。

- **taskkill 整树连坐坑**：杀进程树前必须核对命令行，
  `taskkill /T` 会把 shim 嵌套的合法进程整树连坐 #900
  —— 杀前先 wmic 看命令行。
- **UTF8 编码坑**：PowerShell 读写文本必须显式 `-Encoding UTF8` #810-#812
  否则中文静默变乱码。
- **无号合成条目**：这一条没有坑号，靠 A 行号锚合成 id。
- **域标签坑**：openEMS CSXCAD 绑定 GetLines 按插入序返回 #920
  遍历前必须 np.sort。
- 。

## 下一节

正文。
"""

_SCATTERED_MD = """# 会话坑账（合成散档 T1）

> 档头注记。

## 分节一

1. 散档首条：会话内 taskkill 误杀记录 #900 正文引用全局坑号
   折行并入同条。
2. 散档次条：PowerShell 编码回踩 #802。

- 散档无序形态条：无坑号正文。
"""

_CONSUMPTION_YAML = """schema: pitfall-consumption/v1
rows:
  - id: "#900"
    surface: index_search
    pointer: "tests/unit/test_integ_b_pitfall_chain.py"
    keywords: ["taskkill"]
    note: "合成消费指针行（按坑号交集并入）"
  - id: "A999"
    surface: index_search
    pointer: "nowhere"
    keywords: []
    note: "不存在的行锚——如实计 unmatched"
"""


@pytest.fixture()
def synthetic_tree(tmp_path: Path) -> dict:
    """合成源料树：内核立规注记.md + runs 散档 + 消费指针 YAML（互不越界）。"""
    agents = tmp_path / "项目规约.md"
    agents.write_text(_AGENTS_HEAD + _AGENTS_PITFALLS, encoding="utf-8")
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "SESSION_PITFALLS_T1.md").write_text(
        _SCATTERED_MD, encoding="utf-8")
    consumption = tmp_path / "consumption.yaml"
    consumption.write_text(_CONSUMPTION_YAML, encoding="utf-8")
    return {"agents": agents, "consumption": consumption, "root": tmp_path}


@pytest.fixture()
def built(synthetic_tree: dict, monkeypatch) -> dict:
    """合成树 → build_index 产物（散档登记表指向合成档）。

    INTEG-B 发现（真问题，留待修复）：build_index 的 consumption_path 形参
    声明可注入任意路径，但 source.consumption_yaml 报告字段写死
    ``consumption_path.relative_to(REPO_ROOT)``——消费文件在仓外（tmp 合成
    树）即 ValueError 崩溃（既有 test_kb_b 只传 runs_root，未踩此面）。
    本链以 monkeypatch REPO_ROOT=合成树绕过（测试缝），修复后可去除。
    """
    monkeypatch.setattr(pitfall_index, "REPO_ROOT", synthetic_tree["root"])
    monkeypatch.setattr(pitfall_index, "RUNS_PITFALL_DOCS",
                        ("runs/SESSION_PITFALLS_T1.md",))
    return pitfall_index.build_index(
        agents_path=synthetic_tree["agents"],
        consumption_path=synthetic_tree["consumption"],
        runs_root=synthetic_tree["root"])


@pytest.fixture()
def artifact_path(built: dict, tmp_path: Path) -> Path:
    """built → canonical JSON 落盘（生产者→磁盘产物这一跳）。"""
    out = tmp_path / "pitfalls_index_synth.json"
    out.write_text(pitfall_index.dumps_canonical(built) + "\n",
                   encoding="utf-8")
    return out


def _ids(index: dict) -> list[str]:
    return [e["id"] for e in index["entries"]]


def _entry(built: dict, entry_id: str) -> dict:
    for e in built["entries"]:
        if e["id"] == entry_id:
            return e
    raise AssertionError(f"built 缺条目 {entry_id}: {_ids(built)}")


# ────────────────────────── 正向：全链身份一致 ──────────────────────────


class TestChainConsistency:
    def test_built_passes_service_validator(self, built):
        errors, _warnings = validate_pitfall_index(built)
        assert errors == []
        assert built["schema_version"] == (
            "rfauto-pitfalls-index-v1")

    def test_loader_sees_same_entries_as_builder(
            self, built, artifact_path):
        loaded = load_pitfall_index(artifact_path)
        assert loaded["ok"] is True, loaded.get("errors")
        assert loaded["n_entries"] == built["n_entries"] == 7  # 4+3
        assert _ids(loaded) == _ids(built)
        for a, b in zip(loaded["entries"], built["entries"], strict=True):
            assert a == b  # 逐键相等（同一份数据零变形）

    def test_canonical_roundtrip_byte_identical(self, built, artifact_path):
        # 构建器 canonical 两次序列化逐字节稳定；磁盘原文 == canonical+尾换行；
        # loader 回读的条目与构建器条目逐键一致（信封包装层差异不计——
        # 服务消费面只取 entries，同事实已在 loader_sees_same 钉）。
        assert pitfall_index.dumps_canonical(built) == (
            pitfall_index.dumps_canonical(built))
        assert artifact_path.read_text(encoding="utf-8") == (
            pitfall_index.dumps_canonical(built) + "\n")
        loaded = load_pitfall_index(artifact_path)
        assert loaded["entries"] == built["entries"]

    def test_build_deterministic(self, synthetic_tree, monkeypatch):
        monkeypatch.setattr(pitfall_index, "REPO_ROOT", synthetic_tree["root"])
        monkeypatch.setattr(pitfall_index, "RUNS_PITFALL_DOCS",
                            ("runs/SESSION_PITFALLS_T1.md",))
        a = pitfall_index.build_index(
            agents_path=synthetic_tree["agents"],
            consumption_path=synthetic_tree["consumption"],
            runs_root=synthetic_tree["root"])
        b = pitfall_index.build_index(
            agents_path=synthetic_tree["agents"],
            consumption_path=synthetic_tree["consumption"],
            runs_root=synthetic_tree["root"])
        assert pitfall_index.dumps_canonical(a) == (
            pitfall_index.dumps_canonical(b))

    def test_cli_get_returns_builder_identical_entry(
            self, built, artifact_path):
        idx_arg = ["--index", str(artifact_path)]
        r = runner.invoke(app, ["pitfalls", "get", "#900", *idx_arg, "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.stdout)
        assert payload["ok"] is True
        assert payload["entry"] == _entry(built, "#900")
        assert payload["entry"]["category"] == "shell"
        assert payload["entry"]["consumption"][0]["pointer"] == (
            "tests/unit/test_integ_b_pitfall_chain.py")

    def test_cli_search_keyword_hits_full_text(
            self, built, artifact_path):
        r = runner.invoke(app, ["pitfalls", "search", "GetLines",
                                "--index", str(artifact_path), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.stdout)
        assert payload["ok"] is True and payload["n_hits"] >= 1
        assert payload["entries"][0]["id"] == "#920"
        # service 检索纯函数与 CLI 同池同源（同一条目被召回；service 面吃
        # 的是 load_pitfall_index 信封——消费链必经 loader，不收生 builder 产物）
        loaded = load_pitfall_index(artifact_path)
        svc = pitfall_search(loaded, ["GetLines"])
        assert svc["ok"] is True
        assert svc["entries"][0] == payload["entries"][0]

    def test_cli_search_number_recalls_range_expansion(
            self, built, artifact_path):
        # #810-#812 连号组展开 → --number 811 命中中间号（id=首坑号组原文）
        assert _entry(built, "#810-#812")["numbers"] == [810, 811, 812]
        r = runner.invoke(app, ["pitfalls", "search", "--number", "811",
                                "--index", str(artifact_path), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.stdout)
        assert payload["ok"] is True
        assert [e["id"] for e in payload["entries"]] == ["#810-#812"]
        # #900 散档正文引用全局坑号 → 散档条目同池召回（隔离不丢召回）
        r2 = runner.invoke(app, ["pitfalls", "search", "--number", "900",
                                 "--index", str(artifact_path), "--json"])
        ids = {e["id"] for e in json.loads(r2.stdout)["entries"]}
        assert {"#900", "#T1-1"} <= ids

    def test_cli_search_domain_filter(self, artifact_path):
        # 域过滤与关键词组合（CLI 门：零关键词且零 --number 属 usage 错）
        r = runner.invoke(app, ["pitfalls", "search", "GetLines",
                                "--domain", "openems",
                                "--index", str(artifact_path), "--json"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.stdout)
        assert payload["n_hits"] >= 1
        assert all(e["category"] == "openems" for e in payload["entries"])
        # 纯 --domain 零关键词：命令级 usage 错（exit 2，信封形态）
        r2 = runner.invoke(app, ["pitfalls", "search", "--domain", "openems",
                                 "--index", str(artifact_path), "--json"])
        assert r2.exit_code == 2
        assert json.loads(r2.stdout)["ok"] is False

    def test_scattered_entry_identity_and_isolation(
            self, built, artifact_path):
        # 散档条目 id=文件局部空间（#T1-<序>），devlog_ref 如实 None；
        # 无坑号散档条目照常入账（无序形态）。
        sc = _entry(built, "#T1-1")
        assert sc["devlog_ref"] is None
        assert sc["source"]["file"] == "runs/SESSION_PITFALLS_T1.md"
        assert "taskkill" in sc["text"]
        sc3 = _entry(built, "#T1-3")
        assert sc3["numbers"] == []
        loaded = load_pitfall_index(artifact_path)
        assert pitfall_by_id(loaded, "#T1-2")["entry"]["numbers"] == [802]

    def test_accounting_honest(self, built):
        # 空条目（- 。）解析失败如实计数（不静默丢）；blockquote/收尾节不计条目
        assert built["n_parse_failures"] == 1
        assert built["parse_failures"][0]["reason"] == "提不出标题"
        assert built["n_entries"] == 7
        assert built["scattered_docs"]["n_missing"] == 0
        assert built["skipped_lines"]["blockquote"] == 1
        # 消费指针：#900 并入（内核立规注记+散档两处）；A999 无匹配如实计
        cons = built["consumption"]
        assert cons["n_rows"] == 2 and cons["n_matched_rows"] == 1
        assert cons["unmatched_ids"] == ["A999"]


# ────────────────────────── 错误路径 ──────────────────────────


class TestErrorPaths:
    def test_missing_section_raises_valueerror(self, tmp_path):
        bad = tmp_path / "项目规约.md"
        bad.write_text("# 无坑账节\n\n正文。\n", encoding="utf-8")
        with pytest.raises(ValueError, match="踩坑速查"):
            pitfall_index.build_index(
                agents_path=bad,
                consumption_path=tmp_path / "no.yaml",
                runs_root=tmp_path)

    def test_loader_rejects_corrupted_artifacts(self, built, tmp_path):
        # 坏 JSON / 错 schema / 重复 id：三形态全部 ok=False+errors 显式报
        bad_json = tmp_path / "bad.json"
        bad_json.write_text("{not json", encoding="utf-8")
        r = load_pitfall_index(bad_json)
        assert r["ok"] is False and "JSON 解析失败" in r["errors"][0]

        wrong_schema = json.loads(json.dumps(built))
        wrong_schema["schema_version"] = "v0"
        p2 = tmp_path / "wrong.json"
        p2.write_text(json.dumps(wrong_schema, ensure_ascii=False),
                      encoding="utf-8")
        r2 = load_pitfall_index(p2)
        assert r2["ok"] is False
        assert any("schema_version" in e for e in r2["errors"])

        dup = json.loads(json.dumps(built))
        dup["entries"].append(dict(dup["entries"][0]))
        p3 = tmp_path / "dup.json"
        p3.write_text(json.dumps(dup, ensure_ascii=False), encoding="utf-8")
        r3 = load_pitfall_index(p3)
        assert r3["ok"] is False
        assert any("重复" in e for e in r3["errors"])

    def test_cli_get_miss_exit_1(self, artifact_path):
        r = runner.invoke(app, ["pitfalls", "get", "#999999",
                                "--index", str(artifact_path), "--json"])
        assert r.exit_code == 1
        payload = json.loads(r.stdout)
        assert payload["ok"] is False
        assert any("#999999" in e for e in payload["errors"])

    def test_cli_search_corrupted_index_exit_1(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        r = runner.invoke(app, ["pitfalls", "search", "taskkill",
                                "--index", str(bad), "--json"])
        assert r.exit_code == 1
        payload = json.loads(r.stdout)
        assert payload["ok"] is False

    def test_cli_usage_errors_exit_2(self, artifact_path):
        # 零关键词且零 --number（usage 类，exit 2 与 service 失败 exit 1 分）
        r = runner.invoke(app, ["pitfalls", "search",
                                "--index", str(artifact_path), "--json"])
        assert r.exit_code == 2
        assert json.loads(r.stdout)["ok"] is False
        r2 = runner.invoke(app, ["pitfalls", "search", "--number", "9-0",
                                 "--index", str(artifact_path), "--json"])
        assert r2.exit_code == 2

    def test_cli_missing_index_file_exit_1(self, tmp_path):
        r = runner.invoke(app, ["pitfalls", "get", "#1",
                                "--index", str(tmp_path / "ghost.json"),
                                "--json"])
        assert r.exit_code == 1
        assert json.loads(r.stdout)["ok"] is False


# ────────────────────────── 边界 ──────────────────────────


class TestBoundaries:
    def test_anchor_id_for_numberless_entry(self, built):
        # 无坑号条目 → A<行> 行锚合成 id（前缀 A）；id 唯一性由 validator 钉
        anchor = [e for e in built["entries"] if e["id"].startswith("A")]
        assert len(anchor) == 1
        assert anchor[0]["title"] == "无号合成条目"
        assert anchor[0]["source"]["line_start"] >= 1

    def test_wrapped_continuation_joined(self, built):
        # 折行续行并入同条（行段跨多行；并入这一链路面）
        e = _entry(built, "#900")
        assert "`taskkill /T`" in e["text"]
        assert e["source"]["line_end"] > e["source"]["line_start"]

    def test_scattered_missing_doc_accounted_not_fatal(
            self, synthetic_tree, monkeypatch):
        # 登记表指向缺失散档：如实计 missing，构建不中断（产物自包含）
        monkeypatch.setattr(pitfall_index, "REPO_ROOT", synthetic_tree["root"])
        monkeypatch.setattr(pitfall_index, "RUNS_PITFALL_DOCS",
                            ("runs/SESSION_PITFALLS_GHOST.md",))
        idx = pitfall_index.build_index(
            agents_path=synthetic_tree["agents"],
            consumption_path=synthetic_tree["consumption"],
            runs_root=synthetic_tree["root"])
        assert idx["scattered_docs"]["n_missing"] == 1
        assert idx["scattered_docs"]["n_entries"] == 0
        assert idx["n_entries"] == 4  # 仅 内核立规注记 面
        errors, _ = validate_pitfall_index(idx)
        assert errors == []

    def test_service_filter_and_cli_share_scoring(
            self, built, artifact_path):
        # search_entries 纯函数与 CLI 结果面同源（同一份 entries 同一计分）
        from rfauto.cli.domains.pitfalls import search_entries

        hits, n = search_entries(built["entries"], ["utf8"])
        assert n >= 1 and hits[0]["id"] == "#810-#812"
        r = runner.invoke(app, ["pitfalls", "search", "utf8",
                                "--index", str(artifact_path), "--json"])
        payload = json.loads(r.stdout)
        assert [e["id"] for e in payload["entries"]] == [
            e["id"] for e in hits[:len(payload["entries"])]]

    def test_consumption_yaml_missing_rows_is_best_effort(
            self, synthetic_tree, monkeypatch):
        # 消费指针文件缺失：空表不中断构建（增强面 #105 口径）
        monkeypatch.setattr(pitfall_index, "RUNS_PITFALL_DOCS", ())
        idx = pitfall_index.build_index(
            agents_path=synthetic_tree["agents"],
            consumption_path=synthetic_tree["root"] / "ghost.yaml",
            runs_root=synthetic_tree["root"])
        assert idx["consumption"] == {"n_rows": 0, "n_matched_rows": 0,
                                      "unmatched_ids": []}
        assert idx["n_entries"] == 4
        loaded_via_yaml_module = yaml.safe_load(_CONSUMPTION_YAML)
        assert loaded_via_yaml_module["rows"]  # 源料本身可解析（自证）
