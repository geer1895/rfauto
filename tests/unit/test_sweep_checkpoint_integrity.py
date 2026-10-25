"""aurora_l Wave-B B3 席定向门——sweep checkpoint 行级完整性（T7）。

病灶：checkpoint.jsonl 是 resume 的信任源——旧实现逐行裸 JSON、读侧损坏行
静默跳过，截断/篡改/旧文件顶替都会把残缺或陈旧结果静默带进新 summary
（旧 checkpoint 顶替=旧结果进新 summary 的病灶）。

处方：写侧行信封 ``{"seq","sha256","payload"}``；读侧逐行验证——哈希不
匹配/损坏行起丢弃并如实 note；旧格式（无信封）整文件拒收（宁契约错误不
silently-wrong，老 sweep 重跑即可）。

零网络（#139）；chdir 隔离（#144：不污染真实 runs/）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

src_dir = Path(__file__).parent.parent.parent / "src"
if src_dir.exists() and str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

_RECIPE = {
    "model": "wilkinson_power_divider",
    "params": {
        "arm_len_mm": {"value": 20.5},
        "series_w_mm": {"value": 0.33},
        "shunt_w_mm": {"value": 1.10},
    },
    "setup": {"freq_range_ghz": [1.5, 3.5], "points": 21},
    "objectives": [
        {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
    ],
    "optimization": {
        "params": {
            "arm_len_mm": {"low": 18.0, "high": 23.0},
            "series_w_mm": {"low": 0.25, "high": 0.45},
        },
    },
}


def _make_run(tmp_path, monkeypatch) -> dict:
    """跑一次小 grid sweep，返回结果信封（chdir 隔离在 tmp_path）。"""
    from rfauto.optimization.sweep_backend import run_sweep

    monkeypatch.chdir(tmp_path)
    recipe = tmp_path / "recipe.yaml"
    recipe.write_text(yaml.safe_dump(_RECIPE, allow_unicode=True),
                      encoding="utf-8")
    result = run_sweep(str(recipe), adapter_name="fake", method="grid",
                       coarse_samples=4, max_combos=16,
                       adapter_kwargs={"n_ports": 3})
    assert result["ok"], result.get("errors")
    return result


def _read_lines(cp: Path) -> list[str]:
    return [ln for ln in cp.read_text(encoding="utf-8").splitlines()
            if ln.strip()]


def _write_lines(cp: Path, lines: list[str]) -> None:
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _envelope_line(seq: int, result: dict) -> str:
    """按生产同款规范化造一行信封（测试夹具走同源函数）。"""
    from rfauto.optimization.sweep_backend import (
        _checkpoint_payload_text,
        _payload_sha256,
    )

    payload_text = _checkpoint_payload_text(result)
    return json.dumps({"seq": seq, "sha256": _payload_sha256(payload_text),
                       "payload": json.loads(payload_text)},
                      ensure_ascii=False)


def _sample_result(i: int) -> dict:
    return {"combo_index": i,
            "params": {"arm_len_mm": 18.0 + i, "series_w_mm": 0.25 + i / 100},
            "cost": -10.0 - i,
            "metrics": {"s11_db": -10.0 - i}}


class TestCheckpointWriteEnvelope:
    def test_run_sweep_writes_hash_envelope(self, tmp_path, monkeypatch):
        from rfauto.optimization.sweep_backend import (
            _payload_sha256,
            load_sweep_checkpoint,
        )

        result = _make_run(tmp_path, monkeypatch)
        cp = tmp_path / "runs" / result["run_id"] / "sweep_results" \
            / "checkpoint.jsonl"
        lines = _read_lines(cp)
        assert len(lines) == result["total_combos"] > 0
        for i, ln in enumerate(lines):
            row = json.loads(ln)
            assert row["seq"] == i
            assert len(row["sha256"]) == 64
            assert {"params", "cost", "metrics"} <= set(row["payload"])
            # 哈希与 payload 规范化文本互证（写读两侧同一规范化）
            actual = _payload_sha256(
                json.dumps(row["payload"], ensure_ascii=False,
                           sort_keys=True))
            assert actual == row["sha256"]
        loaded = load_sweep_checkpoint(cp.parent)
        assert loaded["rejected"] is False
        assert loaded["notes"] == []
        assert len(loaded["rows"]) == result["total_combos"]

    def test_resume_roundtrip_self_contained(self, tmp_path, monkeypatch):
        from rfauto.optimization.sweep_backend import run_sweep

        first = _make_run(tmp_path, monkeypatch)
        recipe = tmp_path / "recipe.yaml"
        second = run_sweep(str(recipe), adapter_name="fake", method="grid",
                           coarse_samples=4, max_combos=16,
                           adapter_kwargs={"n_ports": 3},
                           resume_run_id=first["run_id"])
        assert second["ok"], second.get("errors")
        assert second["resumed_combos"] == first["total_combos"]
        assert second["total_combos"] == first["total_combos"]
        # 二轮全命中：resume_notes 干净、三口一致
        assert second["resume_notes"] == []
        summary = json.loads(
            (tmp_path / "runs" / second["run_id"] / "sweep_results"
             / "summary.json").read_text(encoding="utf-8"))
        assert summary["resume_notes"] == []
        # 新 run checkpoint 自包含全部历史且逐行过校验
        from rfauto.optimization.sweep_backend import load_sweep_checkpoint
        cp = (tmp_path / "runs" / second["run_id"] / "sweep_results"
              / "checkpoint.jsonl")
        loaded = load_sweep_checkpoint(cp.parent)
        assert len(loaded["rows"]) == first["total_combos"]
        assert loaded["notes"] == []


class TestCheckpointReadVerification:
    def _make_checkpoint(self, tmp_path) -> tuple[Path, list[dict]]:
        results_dir = tmp_path / "sweep_results"
        cp = results_dir / "checkpoint.jsonl"
        results = [_sample_result(i) for i in range(3)]
        _write_lines(cp, [_envelope_line(i, r) for i, r in
                          enumerate(results)])
        return cp, results

    def test_tampered_payload_drops_from_row(self, tmp_path):
        from rfauto.optimization.sweep_backend import load_sweep_checkpoint

        cp, results = self._make_checkpoint(tmp_path)
        lines = _read_lines(cp)
        # 中间行篡改 payload 数值但保留原哈希（内容-指纹失配）
        row = json.loads(lines[1])
        row["payload"]["cost"] = -999.0
        lines[1] = json.dumps(row, ensure_ascii=False)
        _write_lines(cp, lines)
        loaded = load_sweep_checkpoint(cp.parent)
        assert loaded["rejected"] is False
        # 前 1 行验证通过保留，自第 1 行起丢弃（含余 2 行）
        assert [r["combo_index"] for r in loaded["rows"]] == \
            [results[0]["combo_index"]]
        assert len(loaded["notes"]) == 1
        assert "第 1 行" in loaded["notes"][0]
        assert "sha256" in loaded["notes"][0]
        assert "2 行不采信" in loaded["notes"][0]

    def test_truncated_tail_drops_partial_line(self, tmp_path):
        from rfauto.optimization.sweep_backend import load_sweep_checkpoint

        cp, results = self._make_checkpoint(tmp_path)
        lines = _read_lines(cp)
        # 末行截断（中途死写盘形态：半行 JSON）
        truncated = lines[-1][:len(lines[-1]) // 2]
        _write_lines(cp, [*lines[:-1], truncated])
        loaded = load_sweep_checkpoint(cp.parent)
        assert loaded["rejected"] is False
        assert [r["combo_index"] for r in loaded["rows"]] == \
            [r["combo_index"] for r in results[:-1]]
        assert len(loaded["notes"]) == 1
        assert "第 2 行" in loaded["notes"][0]

    def test_seq_gap_rejected_from_row(self, tmp_path):
        from rfauto.optimization.sweep_backend import load_sweep_checkpoint

        cp, results = self._make_checkpoint(tmp_path)
        lines = _read_lines(cp)
        # 第 2 行 seq 被改写（行删除/重排拼合形态）→ 断号拒收
        row = json.loads(lines[2])
        row["seq"] = 7
        lines[2] = json.dumps(row, ensure_ascii=False)
        _write_lines(cp, lines)
        loaded = load_sweep_checkpoint(cp.parent)
        assert [r["combo_index"] for r in loaded["rows"]] == \
            [r["combo_index"] for r in results[:2]]
        assert "seq 断号" in loaded["notes"][0]

    def test_legacy_format_rejects_whole_file(self, tmp_path):
        from rfauto.optimization.sweep_backend import load_sweep_checkpoint

        cp = tmp_path / "sweep_results" / "checkpoint.jsonl"
        # aurora_l 前旧格式：裸结果 dict（无信封哈希）
        _write_lines(cp, [json.dumps(_sample_result(i), ensure_ascii=False)
                          for i in range(3)])
        loaded = load_sweep_checkpoint(cp.parent)
        assert loaded["rejected"] is True
        assert loaded["rows"] == []
        assert "旧格式" in loaded["notes"][0]
        # 混合格式（首行信封+中间裸行）同样自中间行起拒收
        lines = [_envelope_line(0, _sample_result(0)),
                 json.dumps(_sample_result(1), ensure_ascii=False)]
        _write_lines(cp, lines)
        mixed = load_sweep_checkpoint(cp.parent)
        assert mixed["rejected"] is False
        assert len(mixed["rows"]) == 1
        assert "行结构非法" in mixed["notes"][0]

    def test_missing_and_empty_file_zero_behavior(self, tmp_path):
        from rfauto.optimization.sweep_backend import load_sweep_checkpoint

        loaded = load_sweep_checkpoint(tmp_path / "no_such_dir")
        assert loaded == {"rows": [], "notes": [], "rejected": False}
        cp = tmp_path / "sweep_results" / "checkpoint.jsonl"
        cp.parent.mkdir(parents=True)
        cp.write_text("\n\n", encoding="utf-8")
        assert load_sweep_checkpoint(cp.parent)["rows"] == []


class TestResumeIntegrityGates:
    def test_resume_from_legacy_checkpoint_refuses(self, tmp_path,
                                                   monkeypatch):
        from rfauto.optimization.sweep_backend import run_sweep

        first = _make_run(tmp_path, monkeypatch)
        cp = tmp_path / "runs" / first["run_id"] / "sweep_results" \
            / "checkpoint.jsonl"
        # 旧 run 的 checkpoint 回写为旧格式（顶替形态）
        _write_lines(cp, [json.dumps(_sample_result(i), ensure_ascii=False)
                          for i in range(2)])
        recipe = tmp_path / "recipe.yaml"
        second = run_sweep(str(recipe), adapter_name="fake", method="grid",
                           coarse_samples=4, max_combos=16,
                           adapter_kwargs={"n_ports": 3},
                           resume_run_id=first["run_id"])
        assert second["ok"] is False
        assert any("拒收" in e and "旧格式" in e for e in second["errors"])

    def test_resume_from_tampered_carries_verified_prefix_with_notes(
            self, tmp_path, monkeypatch):
        from rfauto.optimization.sweep_backend import run_sweep

        first = _make_run(tmp_path, monkeypatch)
        cp = tmp_path / "runs" / first["run_id"] / "sweep_results" \
            / "checkpoint.jsonl"
        lines = _read_lines(cp)
        row = json.loads(lines[-1])
        row["payload"]["cost"] = 12345.0
        lines[-1] = json.dumps(row, ensure_ascii=False)
        _write_lines(cp, lines)
        recipe = tmp_path / "recipe.yaml"
        second = run_sweep(str(recipe), adapter_name="fake", method="grid",
                           coarse_samples=4, max_combos=16,
                           adapter_kwargs={"n_ports": 3},
                           resume_run_id=first["run_id"])
        assert second["ok"], second.get("errors")
        # 只采信验证过的前缀（末行篡改被丢弃）
        assert second["resumed_combos"] == first["total_combos"] - 1
        assert second["resume_notes"] \
            and "sha256" in second["resume_notes"][0]
        # note 落 summary.json（旧结果静默进新 summary 的病灶封堵留痕）
        summary = json.loads(
            (tmp_path / "runs" / second["run_id"] / "sweep_results"
             / "summary.json").read_text(encoding="utf-8"))
        assert summary["resume_notes"] == second["resume_notes"]

    def test_missing_resume_source_fails_unchanged(self, tmp_path,
                                                   monkeypatch):
        from rfauto.optimization.sweep_backend import run_sweep

        monkeypatch.chdir(tmp_path)
        recipe = tmp_path / "recipe.yaml"
        recipe.write_text(yaml.safe_dump(_RECIPE, allow_unicode=True),
                          encoding="utf-8")
        result = run_sweep(str(recipe), adapter_name="fake",
                           resume_run_id="no_such_run")
        assert result["ok"] is False
        assert any("checkpoint" in e for e in result["errors"])


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
