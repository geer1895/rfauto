"""阶段 2.4：recipes → agent skill 格式测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


@pytest.fixture
def recipe_path(tmp_path):
    recipe = {
        "model": "wilkinson_power_divider",
        "params": {"arm_len_mm": {"value": 20.5}},
        "setup": {"freq_range_ghz": [2.3, 2.5], "points": 41},
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below",
             "value": -15},
        ],
        "optimization": {"params": {
            "arm_len_mm": {"low": 18.0, "high": 23.0},
            "series_w_mm": {"low": 0.25, "high": 0.45},
        }},
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(recipe), encoding="utf-8")
    return str(path)


class TestRecipeToSkill:
    def test_generates_frontmatter_and_sections(self, recipe_path):
        from rfauto.service.skill_service import recipe_to_skill

        r = recipe_to_skill(recipe_path)
        assert r["ok"]
        assert r["skill_name"] == "rfauto-wilkinson-power-divider"
        content = r["content"]
        assert content.startswith("---\n")
        assert "name: rfauto-wilkinson-power-divider" in content
        assert "arm_len_mm" in content and "series_w_mm" in content
        assert "rfauto autotune" in content
        assert "不产生物理数字" in content

    def test_write_skill_idempotent(self, recipe_path, tmp_path):
        from rfauto.service.skill_service import write_skill

        out_dir = tmp_path / "skills"
        r1 = write_skill(recipe_path, output_dir=out_dir)
        assert r1["written"]
        first = Path(r1["output_path"]).read_text(encoding="utf-8")
        r2 = write_skill(recipe_path, output_dir=out_dir)
        second = Path(r2["output_path"]).read_text(encoding="utf-8")
        assert first == second

    def test_missing_recipe_rejected(self, tmp_path):
        from rfauto.service.skill_service import recipe_to_skill

        assert not recipe_to_skill(tmp_path / "nope.yaml")["ok"]
