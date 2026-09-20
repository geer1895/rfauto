"""agent_propose / agent_apply 编排闭环测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from rfauto.service.api import agent_apply, agent_propose


def _recipe(tmp_path: Path) -> Path:
    recipe = {
        "model": "wilkinson_power_divider",
        "schema_version": 1,
        "params": {
            "arm_len_mm": {"value": 20.5, "unit": "mm"},
        },
        "setup": {"freq_range_ghz": [1.5, 3.5], "points": 11},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
        ],
        "optimization": {
            "params": {"arm_len_mm": {"low": 18.0, "high": 23.0}},
        },
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RFAUTO_CACHE", "off")
    yield


class TestAgentPropose:
    def test_propose_ok_returns_token(self, tmp_path):
        result = agent_propose(_recipe(tmp_path), {"arm_len_mm": 21.0})
        assert result["ok"]
        assert result["token"]
        assert result["effective_params"]["arm_len_mm"] == 21.0

    def test_propose_unknown_param_rejected_l1(self, tmp_path):
        result = agent_propose(_recipe(tmp_path), {"bogus_param": 1.0})
        assert not result["ok"]
        assert result["stage"] == "L1"
        assert any("bogus_param" in v for v in result["gate"]["details"]["violations"])

    def test_propose_out_of_bounds_rejected_l2(self, tmp_path):
        # arm_len_mm 优化范围 [18, 23]；30 有覆盖也要在 params/optimization 白名单并超界
        recipe = _recipe(tmp_path)
        import yaml as _yaml
        data = _yaml.safe_load(recipe.read_text(encoding="utf-8"))
        data["params"]["arm_len_mm"] = {"value": 20.5, "unit": "mm"}
        data["optimization"]["params"]["arm_len_mm"] = {"low": 18.0, "high": 23.0}
        data["params"]["series_w_mm"] = {"value": 0.33}
        data["optimization"]["params"]["series_w_mm"] = {"low": 0.25, "high": 0.45}
        recipe.write_text(_yaml.safe_dump(data), encoding="utf-8")

        result = agent_propose(recipe, {"series_w_mm": 5.0})
        assert not result["ok"]
        assert result["stage"] == "L2"


class TestAgentApply:
    def test_apply_with_wrong_token_rejected(self, tmp_path):
        result = agent_apply(_recipe(tmp_path), "deadbeef", {"arm_len_mm": 21.0})
        assert not result["ok"]
        assert result["stage"] == "L3"

    def test_apply_with_tampered_params_rejected(self, tmp_path):
        recipe = _recipe(tmp_path)
        proposed = agent_propose(recipe, {"arm_len_mm": 21.0})
        assert proposed["ok"]
        # propose 后篡改参数 → token 哈希不匹配
        result = agent_apply(recipe, proposed["token"], {"arm_len_mm": 22.5})
        assert not result["ok"]
        assert result["stage"] == "L3"

    def test_apply_full_loop_runs_fake_sim(self, tmp_path):
        recipe = _recipe(tmp_path)
        proposed = agent_propose(recipe, {"arm_len_mm": 21.0})
        result = agent_apply(recipe, proposed["token"], {"arm_len_mm": 21.0})
        assert result["ok"], result.get("errors")
        assert result["run_id"]
        assert result["agent_gate"] == "L1+L2+L3"
        # 提案配方落在独立目录，原配方未被覆盖
        proposal_dir = Path("runs") / "agent_proposals"
        assert list(proposal_dir.glob("proposal_*.yaml"))
        assert json.loads((Path("runs") / result["run_id"] / "results" / "metrics.json")
                          .read_text(encoding="utf-8"))["params"]["arm_len_mm"] == 21.0
