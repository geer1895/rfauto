"""F3L1 清偿钉（aurora_p，2026-11-02）：--json 信封 + 人读零变化 A/B 对。

F3 席四域审计（runs/aurora_p/f3/AUDIT.md §2/§3）登记的三处不一致本席清偿：

- I-1：``_watch_poll`` 超时分支 --json 下输出 error_envelope 信封（JSONL
  流内禁夹非 JSON 行，VI-5 W6-B 家法）；人读分支红字逐字节原样。
- I-2：``_load_json_file``/``_kv_floats`` 参数错收编 ``_emit_usage_error``
  单源（#ge1㉙：usage 错在 --json 下必须信封+exit 2）；人读信道红字/exit 2
  逐字节原样（Z 面钉=修前 bytecmp 基线同一字面，runs/aurora_p/f3l1/）。
- I-3：runs SSE 桥流内 error 帧 data 收编 error_envelope（裸
  ``{errors:[…]}`` → ok=False 信封）；前端 sse.js error 监听只判
  ``typeof e.data === "string"`` 不解析内容——消费零改动，本文件钉
  信封形态 + data 恒为 JSON 字符串（前端兼容面）。

离线确定性：全部错误路径在 service 调用前触发（解析面/轮询面），零
license 零网络零 runs/ 写面（tmp chdir 隔离，#144）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from rfauto.cli.main import app as root_app

RECIPE = {
    "model": "wilkinson_power_divider",
    "schema_version": 1,
    "params": {"arm_len_mm": {"value": 20.5, "unit": "mm"}},
    "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
    "objectives": [
        {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
    ],
    "optimization": {"params": {"arm_len_mm": {"low": 18.0, "high": 23.0}}},
}


@pytest.fixture(autouse=True)
def _isolated_cwd(isolated):
    """chdir 隔离（#144：watch 轮询回落 runs/<id>/meta.json 不污染真实湖）。

    体委托 tests/conftest.py::isolated 单源（conftest_fixture_hygiene
    棘轮：禁本地重写隔离体——aurora_p 终门 seg1 红清偿）。"""
    yield


def _invoke(argv: list[str]):
    return CliRunner().invoke(root_app, argv)


def _assert_pure_json_stream(text: str) -> list:
    """stdout 必须是纯 JSON 文档序列（VI-5 W6-B：流内禁夹非 JSON 行）。"""
    dec = json.JSONDecoder()
    docs: list = []
    idx = 0
    n = len(text)
    while True:
        while idx < n and text[idx] in " \t\r\n":
            idx += 1
        if idx >= n:
            break
        doc, idx = dec.raw_decode(text, idx)  # 非即 JSON ValueError → 钉红
        docs.append(doc)
    assert docs, "空输出（连一个 JSON 文档都没有）"
    return docs


def _assert_usage_envelope(result, frag: str) -> dict:
    """usage 错负例：exit 2 + stdout 纯 JSON 信封（ok=False+errors 含 frag）。"""
    assert result.exit_code == 2, \
        f"exit={result.exit_code}\n{result.output[:400]}"
    docs = _assert_pure_json_stream(result.output)
    last = docs[-1]
    assert last.get("ok") is False, f"ok 非 False：{list(last)[:8]}"
    assert last.get("errors") and any(frag in str(e) for e in last["errors"]), \
        f"errors 缺 {frag!r}：{last.get('errors')}"
    return last


# ══ I-1：_watch_poll 超时分支 ═════════════════════════════════════════════

WATCH = ["jobs", "watch", "f3l1_no_such_job", "--timeout", "0.3",
         "--interval", "0.1"]


class TestI1WatchTimeout:
    def test_json_channel_timeout_is_pure_envelope_stream(self):
        """--json 超时：stdout 全程纯 JSON（tick 行+终帧信封），无红字泄漏。"""
        r = _invoke([*WATCH, "--json"])
        assert r.exit_code == 1
        docs = _assert_pure_json_stream(r.output)
        last = docs[-1]
        assert last.get("ok") is False
        assert any("watch 超时" in str(e) and "state=unknown" in str(e)
                   for e in last.get("errors") or [])
        assert "✗" not in r.output, "JSONL 流内夹了红字裸文本"

    def test_human_channel_timeout_red_line_byte_identical(self):
        """人读超时：红字行逐字节=修前字面（bytecmp_before.txt Z05 同文）。"""
        r = _invoke([*WATCH])
        assert r.exit_code == 1
        kept = [ln for ln in r.output.splitlines()
                if not (ln.lstrip().startswith("[")
                        and "f3l1_no_such_job" in ln and "state=" in ln)]
        assert kept == ["✗ watch 超时（0.3s，末态 state=unknown）"], kept
        assert '"ok"' not in r.output, "人读信道不得混入 JSON 信封"


# ══ I-2：_load_json_file / _kv_floats ═════════════════════════════════════

class TestI2LoadJsonFile:
    def test_missing_payload_json_channel_envelope(self, tmp_path):
        """lint --json 缺 payload：信封+exit 2（修前=红字裸文本泄漏）。"""
        missing = tmp_path / "no_such_payload.json"
        _assert_usage_envelope(_invoke(["lint", str(missing), "--json"]),
                               "payload不存在")

    def test_missing_payload_human_channel_byte_identical(self):
        """lint（无旗标）缺 payload：红字逐字节=修前字面（Z01 同文，短路径免折行）。"""
        r = _invoke(["lint", "nope.json"])
        assert r.exit_code == 2
        assert r.output == "✗ payload不存在: nope.json\n", repr(r.output)

    def test_nondict_payload_human_channel_byte_identical(self, tmp_path):
        """lint（无旗标）非对象 JSON：红字逐字节=修前字面（Z02 同文）。"""
        arr = tmp_path / "array.json"
        arr.write_text("[1, 2]", encoding="utf-8")
        r = _invoke(["lint", str(arr)])
        assert r.exit_code == 2
        assert r.output == "✗ payload必须是 JSON 对象\n", repr(r.output)

    def test_bad_json_content_json_channel_envelope(self, tmp_path):
        """lint --json 坏 JSON 内容：不可读信封+exit 2。"""
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        _assert_usage_envelope(_invoke(["lint", str(bad), "--json"]), "不可读")

    def test_compat_default_json_leaf_envelope(self, tmp_path):
        """humidity uptake（缺省即 JSON 兼容位叶）缺 payload：缺省信道信封。"""
        missing = tmp_path / "no_such_payload.json"
        r = _invoke(["humidity", "uptake", str(missing)])
        assert r.exit_code == 2
        docs = _assert_pure_json_stream(r.output)
        assert docs[-1].get("ok") is False
        assert any("payload不存在" in str(e) for e in docs[-1]["errors"])

    def test_compat_default_json_leaf_nojson_human_unchanged(self):
        """humidity uptake --no-json：人读红字逐字节=修前字面（Z04 同文，短路径）。"""
        r = _invoke(["humidity", "uptake", "nope.json", "--no-json"])
        assert r.exit_code == 2
        assert r.output == "✗ payload不存在: nope.json\n", repr(r.output)


class TestI2KvFloats:
    @pytest.fixture()
    def recipe(self, tmp_path):
        p = tmp_path / "recipe.yaml"
        p.write_text(yaml.safe_dump(RECIPE), encoding="utf-8")
        return p

    def test_bad_format_json_channel_envelope(self, recipe):
        """campaign plan --json --tolerances bad：信封+exit 2。"""
        _assert_usage_envelope(
            _invoke(["campaign", "plan", str(recipe),
                     "--tolerances", "bad", "--json"]),
            "格式应为 参数名=值")

    def test_bad_format_human_channel_byte_identical(self, recipe):
        """campaign plan（无旗标）坏公差：红字逐字节=修前字面（Z03 同文）。"""
        r = _invoke(["campaign", "plan", str(recipe), "--tolerances", "bad"])
        assert r.exit_code == 2
        assert r.output == "✗ --tolerances 格式应为 参数名=值：bad\n", repr(r.output)

    def test_non_numeric_value_json_channel_envelope(self, recipe):
        """campaign plan --json --tolerances x=abc：值不是数字信封+exit 2。"""
        _assert_usage_envelope(
            _invoke(["campaign", "plan", str(recipe),
                     "--tolerances", "x=abc", "--json"]),
            "值不是数字")

    def test_compat_default_json_leaf_kv_envelope(self, tmp_path):
        """uq yield-at（恒 JSON 兼容位叶）坏 --tol：缺省信道信封。"""
        samples = tmp_path / "samples.json"
        pts = [{"params": {"arm_len_mm": 18.0 + 0.5 * i},
                "metrics": {"s11_db_max_in_band": -20.0}} for i in range(12)]
        samples.write_text(json.dumps({
            "bounds": {"arm_len_mm": [18.0, 23.0]},
            "objectives": [{"metric": "s11_db", "band": [2.3, 2.5],
                            "op": "max_below", "value": -15}],
            "samples": pts}), encoding="utf-8")
        r = _invoke(["uq", "yield-at", str(samples), "--tol", "bad"])
        assert r.exit_code == 2
        docs = _assert_pure_json_stream(r.output)
        assert docs[-1].get("ok") is False
        assert any("格式应为 参数名=值" in str(e) for e in docs[-1]["errors"])


# ══ I-3：runs SSE 桥 error 帧 ════════════════════════════════════════════

def _sse_named_frames(text: str) -> list[tuple[str, str]]:
    """SSE 文本 → 命名帧 (event, data) 列表（块=空行分隔）。"""
    frames: list[tuple[str, str]] = []
    for block in text.split("\n\n"):
        ev = None
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                ev = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())
        if ev is not None:
            frames.append((ev, "\n".join(data_lines)))
    return frames


class TestI3BridgeErrorFrame:
    def test_error_frame_data_is_error_envelope(self, tmp_path, monkeypatch):
        """流内 error 帧 data=error_envelope 信封（ok=False+errors list）。"""
        monkeypatch.setattr(
            "rfauto.service.ui_service.read_run_events",
            lambda run_id, offset: {"ok": False, "errors": ["读面炸了"]})
        from starlette.testclient import TestClient

        from rfauto.ui.server import create_ui_app

        client = TestClient(create_ui_app(include_runs_mount=False))
        r = client.get("/api/runs/f3l1_err/events/stream")
        assert r.status_code == 200
        frames = [f for f in _sse_named_frames(r.text) if f[0] == "error"]
        assert len(frames) == 1, frames
        ev, data = frames[0]
        assert ev == "error"
        payload = json.loads(data)  # data 恒 JSON 字符串（前端 typeof 判定面）
        assert payload.get("ok") is False
        assert payload.get("errors") == ["读面炸了"]

    def test_error_frame_no_longer_bare_errors_dict(self, tmp_path, monkeypatch):
        """负例钉：data 不再是裸 {errors:[…]}（无 ok 键=裸 dict=违约）。"""
        monkeypatch.setattr(
            "rfauto.service.ui_service.read_run_events",
            lambda run_id, offset: {"ok": False, "errors": ["再炸一次"]})
        from starlette.testclient import TestClient

        from rfauto.ui.server import create_ui_app

        client = TestClient(create_ui_app(include_runs_mount=False))
        r = client.get("/api/runs/f3l1_err2/events/stream")
        frames = [f for f in _sse_named_frames(r.text) if f[0] == "error"]
        assert frames, "流内应有 error 帧"
        payload = json.loads(frames[0][1])
        assert "ok" in payload, "error 帧 data 缺 ok 键（裸 dict 形态回潮）"
