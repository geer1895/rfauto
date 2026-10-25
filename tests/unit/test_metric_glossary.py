"""指标词典测试（aurora_i W2-S2，R3 设计 M2）：YAML 覆盖率钉 + service
三函数正负例 + 判定内核（与前端 kit.js metricGateVerdict 同构交叉钉）。

数据单一事实源：knowledge/metric_glossary.yaml——数据湖 20 个 dataset
parquet 的 metrics_json 实测 38 个不同指标键（R3 §3.1 口径；W2-S2 席
2026-10-19 复测 38 键不变，键清单硬编码于 _DATA_LAKE_KEYS 作覆盖率钉）。
2026-10-23 aurora_k K2 增补 q_factor 判读语义条目（反馈 P14；词典超集
口径，现 39 条），键数钉与语义钉同笔更新。
铁律 7 面一致：本文件只钉词典文本与判定逻辑，不产生物理数字。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GLOSSARY_PATH = _REPO_ROOT / "knowledge" / "metric_glossary.yaml"
_TERMINOLOGY_PATH = _REPO_ROOT / "knowledge" / "terminology.yaml"

_ALLOWED_KEYS = {
    "metric_id", "plain_zh", "plain_en", "unit", "good_when",
    "gate", "gate_semantics", "pitfall_refs", "related_terms",
    "computed_by", "notes",
}
_REQUIRED_KEYS = {"metric_id", "plain_zh", "plain_en", "unit"}
_ALLOWED_GATE_OPS = {"max_below", "min_above", "abs_le", "bool_true"}

# ── 覆盖率钉锚：数据湖 metrics_json 实测 38 键（2026-10-19 W2-S2 复测，
#    与 runs/aurora_i/R3_credibility_design.md §3.1 清单一致）。数据湖是
#    演进面（新键出现=词典纯增量跟进），本清单只钉"38 键全有条目"下界，
#    词典允许超集。 ──
_DATA_LAKE_KEYS = [
    "s11_db_max_in_band",
    "s21_db_mean_in_band",
    "iso_s23_db_min_in_band",
    "s11_db_min_in_band",
    "eps_eff_mean_in_band",
    "eps_eff_beta_mean_in_band",
    "zl1_re_ohm_med_in_band",
    "zl2_re_ohm_med_in_band",
    "s31_db_mean_in_band",
    "all_pass",
    "f0_offset_pct",
    "f0_on_grid",
    "f_res_ghz_s11min",
    "grid_step_ghz",
    "n_freqs",
    "n_gates_pass",
    "n_gates_total",
    "n_ports",
    "ok",
    "s11_db@f0",
    "s21_db@f0",
    "s22_db@f0",
    "s23_db@f0",
    "s31_db@f0",
    "s33_db@f0",
    "sigma_max@f0",
    "sigma_max_fullband",
    "s41_db@f0",
    "s44_db@f0",
    "directivity_db_proxy",
    "s24_db@f0",
    "s34_db@f0",
    "s32_db@f0",
    "reciprocity_max_abs",
    "s21_phase_deg@f0",
    "s21_s41_phase_diff_deg",
    "s41_phase_deg@f0",
    "s21_s31_balance_db",
]

_PITFALL_RE = re.compile(r"^#\d+$")


@pytest.fixture()
def data() -> dict:
    with open(_GLOSSARY_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture()
def entries(data) -> list[dict]:
    return data["entries"]


@pytest.fixture()
def terminology_terms() -> set[str]:
    with open(_TERMINOLOGY_PATH, encoding="utf-8") as f:
        terms = yaml.safe_load(f)["terms"]
    return {str(t["term"]).strip().lower() for t in terms}


class TestMetricGlossaryYaml:
    """knowledge/metric_glossary.yaml schema 与覆盖率钉。"""

    def test_file_exists(self):
        assert _GLOSSARY_PATH.exists()

    def test_no_mojibake(self):
        """U+FFFD 替换字符零容忍（#259 家族：长中文段落写入抽查）。"""
        text = _GLOSSARY_PATH.read_text(encoding="utf-8")
        assert "\ufffd" not in text

    def test_schema_version(self, data):
        assert data["schema"] == "metric-glossary/v1"

    def test_coverage_pin_38_data_lake_keys(self, entries):
        """覆盖率钉：数据湖实测 38 键全有条目（漏键=诚实缺省前先拦在这里）。"""
        keys = {str(e.get("metric_id", "")) for e in entries}
        missing = [k for k in _DATA_LAKE_KEYS if k not in keys]
        assert not missing, f"词典缺数据湖指标键: {missing}"

    def test_metric_key_unique(self, entries):
        keys = [str(e["metric_id"]).strip() for e in entries]
        assert len(keys) == len(set(keys)), "metric_key 重复"

    def test_required_fields_nonempty(self, entries):
        for e in entries:
            assert set(e) >= _REQUIRED_KEYS, \
                f"缺必填键: {e.get('metric_key')!r}"
            for k in _REQUIRED_KEYS:
                assert isinstance(e[k], str) and e[k].strip(), \
                    f"{e['metric_key']!r} 字段 {k} 为空"

    def test_explain_or_gate_semantics_present(self, entries):
        """每词条至少有 good_when（白话判据）或 gate_semantics（门语义）
        之一——"说明待补"的诚实缺省允许 absent，但不允许两样全无。"""
        for e in entries:
            has = any(
                isinstance(e.get(k), str) and e.get(k, "").strip()
                for k in ("good_when", "gate_semantics"))
            assert has, f"{e['metric_key']!r} 缺 good_when/gate_semantics"

    def test_optional_fields_allowlist(self, entries):
        for e in entries:
            extra = set(e) - _ALLOWED_KEYS
            assert not extra, \
                f"未知键 {extra!r}（schema 见文件头注）"

    def test_gate_shape_and_ops(self, entries):
        """机读 gate：op 在合法集，数值 op 必带有限数值 good（着色内核
        的输入契约；bool_true 可省 good）。"""
        for e in entries:
            gate = e.get("gate")
            if gate is None:
                continue
            assert isinstance(gate, dict), f"{e['metric_key']!r} gate 形态"
            assert gate.get("op") in _ALLOWED_GATE_OPS, \
                f"{e['metric_key']!r} 未知 gate.op: {gate.get('op')!r}"
            if gate["op"] != "bool_true":
                good = gate.get("good")
                assert isinstance(good, (int, float)) and good == good, \
                    f"{e['metric_key']!r} 数值 op 缺有限 good"

    def test_pitfall_refs_format(self, entries):
        """坑号引用一律 #NNN 形态（仓内账本出处标记，D1 裁决保留口径）。"""
        for e in entries:
            for ref in e.get("pitfall_refs") or []:
                assert _PITFALL_RE.match(str(ref)), \
                    f"{e['metric_key']!r} 坑号形态异常: {ref!r}"

    def test_related_terms_resolve_to_terminology(self, entries,
                                                   terminology_terms):
        """related_terms 指向 knowledge/terminology.yaml 既有术语（一处
        知识处处复用的契约；悬空引用=死链）。"""
        for e in entries:
            for term in e.get("related_terms") or []:
                assert str(term).strip().lower() in terminology_terms, \
                    f"{e['metric_key']!r} 悬空 related_term: {term!r}"

    def test_bilingual_parity(self, entries):
        """中英白话定义都在场且都非 ASCII 单语（plain_en 缺失=前端 en 档
        回退 zh——允许，但显式登记面必须双语，见 schema 必填键）。"""
        for e in entries:
            assert e["plain_zh"].strip() and e["plain_en"].strip()

    def test_q_factor_semantic_pin(self, entries):
        """q_factor 判读语义条目（aurora_k K2 2026-10-23，反馈 P14 吸收）：
        "Q 高≠损耗低"语义钉——串联口径 Q=|X|/R、电容变小 Q 也升、判损耗
        并看 R（串联电阻）与 S21；无机读门（Q 单值着色会误导判读）。"""
        e = next(x for x in entries if x.get("metric_id") == "q_factor")
        assert "|X|/R" in e["plain_zh"]
        assert "电容变小" in e["plain_zh"]
        assert "串联电阻" in e["plain_zh"] and "S21" in e["plain_zh"]
        assert "series resistance" in e["plain_en"] and "S21" in e["plain_en"]
        assert "gate" not in e, "q_factor 不设机读门（Q 高≠损耗低）"
        assert not e.get("pitfall_refs"), "无仓内坑号可引，如实不造"


class TestMetricGlossaryService:
    """service 三函数正负例（ok 信封口径，同 terminology_service 模式）。"""

    @pytest.fixture()
    def svc(self):
        from rfauto.service import metric_glossary_service as m
        return m

    def test_load_returns_schema_and_entries(self, svc):
        doc = svc.load_metric_glossary()
        assert doc.get("schema") == "metric-glossary/v1"
        # 39 = 数据湖 38 键 + q_factor 判读语义增补（aurora_k K2 2026-10-23）
        assert len(doc["entries"]) == 39

    def test_list_envelope(self, svc):
        r = svc.list_metric_glossary()
        assert r["ok"] is True
        assert r["count"] == len(r["entries"]) == 39
        assert len(r["keys"]) == 39
        assert set(r["gate_ops"]) == _ALLOWED_GATE_OPS
        assert r["schema"] == "metric-glossary/v1"
        json.dumps(r)  # 信封 JSON 可序列化

    def test_get_metric_case_insensitive(self, svc):
        for probe in ("s11_db_max_in_band", "S11_DB_MAX_IN_BAND",
                      "  s11_db_max_in_band  "):
            r = svc.get_metric(probe)
            assert r["ok"] is True
            assert r["metric"]["metric_id"] == "s11_db_max_in_band"
            assert r["metric"]["plain_zh"].strip()

    def test_get_metric_unknown_negative(self, svc):
        r = svc.get_metric("no_such_metric_key")
        assert r["ok"] is False
        assert isinstance(r["errors"], list) and r["errors"]

    def test_envelope_schema_version(self, svc):
        assert svc.METRIC_GLOSSARY_SERVICE_SCHEMA_VERSION == "1.0"
        for env in (svc.list_metric_glossary(),
                    svc.get_metric("ok"),
                    svc.get_metric("nope"),
                    svc.judge_metric("ok", True)):
            assert env["schema_version"] == "1.0"
        json.dumps([svc.list_metric_glossary(), svc.judge_metric("ok", 1)])

    def test_missing_yaml_degrades_empty(self, svc, monkeypatch):
        monkeypatch.setattr(svc, "_GLOSSARY_PATH",
                            Path("no/such/file.yaml"))
        assert svc.load_metric_glossary() == {}
        assert svc.list_metric_glossary()["count"] == 0
        assert svc.get_metric("ok")["ok"] is False


class TestJudgeMetric:
    """判定内核三态（着色契约：good→绿 / bad→红 / neutral→中性）。"""

    @pytest.fixture()
    def judge(self):
        from rfauto.service import metric_glossary_service as m
        return m.judge_metric

    def test_good_bad_neutral_tri_state(self, judge):
        assert judge("s11_db_max_in_band", -15.2)["verdict"] == "good"
        assert judge("s11_db_max_in_band", -5.0)["verdict"] == "bad"
        # 无 gate 词条（family 敏感键）一律中性
        assert judge("s21_db@f0", -3.0)["verdict"] == "neutral"
        assert judge("s21_db@f0", -3.0)["reason"] == "no_gate"

    def test_boundary_inclusive(self, judge):
        """边界值判达标（v <= good 口径，含等号——预声明门惯例）。"""
        assert judge("s11_db_max_in_band", -10.0)["verdict"] == "good"
        assert judge("sigma_max_fullband", 1.01)["verdict"] == "good"
        assert judge("sigma_max_fullband", 1.010001)["verdict"] == "bad"
        assert judge("s21_s31_balance_db", 0.5)["verdict"] == "good"
        assert judge("s21_s31_balance_db", 0.71)["verdict"] == "bad"
        assert judge("f0_offset_pct", -0.75)["verdict"] == "good"
        assert judge("f0_offset_pct", -12.75)["verdict"] == "bad"

    def test_bool_true_op(self, judge):
        for truthy in (True, 1):
            assert judge("ok", truthy)["verdict"] == "good"
        for falsy in (False, 0, "false"):
            assert judge("ok", falsy)["verdict"] == "bad"
        # 非布尔语义值如实中性（不猜）
        assert judge("ok", "maybe")["verdict"] == "neutral"

    def test_non_numeric_value_neutral(self, judge):
        for bad in ("n/a", None, float("nan"), float("inf"), [1, 2]):
            r = judge("s11_db_max_in_band", bad)
            assert r["verdict"] == "neutral", f"value={bad!r}"
            assert r["reason"] == "non_numeric_value"

    def test_bool_is_not_treated_as_number(self, judge):
        """bool 是 int 子类——bool_true 之外的 op 不许把 True 当 1 判。"""
        r = judge("s11_db_max_in_band", True)
        assert r["verdict"] == "neutral"

    def test_unknown_metric_key_neutral(self, judge):
        r = judge("no_such_key", -20.0)
        assert r["verdict"] == "neutral"
        assert r["reason"] == "unknown_metric_key"

    def test_min_above_op(self, judge):
        assert judge("iso_s23_db_min_in_band", 20.0)["verdict"] == "good"
        assert judge("iso_s23_db_min_in_band", 5.0)["verdict"] == "bad"

    def test_verdict_labels_never_say_pass_fail(self, judge):
        """neutral 三态词汇纪律：verdict ∈ {good,bad,neutral}——不借
        PASS/FAIL 字面（#122：无判据可判≠通过也≠失败）。"""
        for probe_key, probe_val in (("s11_db_max_in_band", -1.0),
                                     ("s21_db@f0", -3.0),
                                     ("no_such_key", 0)):
            assert judge(probe_key, probe_val)["verdict"] in {
                "good", "bad", "neutral"}


class TestMetricGlossaryMCPResource:
    """MCP resource 注册面冒烟（W3.5-K3 2026-10-19；照
    test_terminology.TestTerminologyMCPResource 形态）。"""

    @pytest.fixture()
    def mcp_server(self):
        from rfauto.mcp_server import mcp

        return mcp

    def test_metric_glossary_resource_registered(self, mcp_server):
        import anyio
        resources = anyio.run(mcp_server.list_resources)
        uris = {str(r.uri) for r in resources}
        assert "rfauto://knowledge/metric-glossary" in uris

    def test_read_metric_glossary_resource(self, mcp_server):
        import anyio
        content = anyio.run(
            lambda: mcp_server.read_resource(
                "rfauto://knowledge/metric-glossary")
        )
        # fastmcp 3.x 形态分流（同 test_mcp_server._resource_text）：
        # dict 资源序列化 JSON 在 contents[0].content，旧形态在 [0].text。
        if hasattr(content, "contents") and content.contents:
            block = content.contents[0]
            text = getattr(block, "content", None) or getattr(block, "text", "")
        elif isinstance(content, list) and content:
            text = content[0].text
        else:
            text = str(content)
        data = json.loads(text)
        entries = data.get("entries")
        assert isinstance(entries, list) and entries
        assert "metric_id" in entries[0]
