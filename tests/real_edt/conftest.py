"""real_edt 真机测试 conftest——AEDT 环境检查 + 轻量配方 fixture。

标记体系：pyproject.toml 定义 `real_edt` marker；运行用 `-m real_edt` 或
`-m "not real_edt"` 排除。缺 RFAUTO_AEDT_PATH 时自动 skip，不阻塞 CI。
"""

import os

import pytest

pytestmark = pytest.mark.real_edt


@pytest.fixture()
def aedt_env_ready() -> str:
    """返回可用的 AEDT 路径；显式 env 优先，否则自动探测（项目 B），无则 skip。"""
    p = os.environ.get("RFAUTO_AEDT_PATH", "")
    if p and os.path.exists(p):
        return p
    from rfauto.infra.version_probe import resolve_aedt_install

    install = resolve_aedt_install(None)
    if install is None:
        pytest.skip("RFAUTO_AEDT_PATH 未设置且自动探测未发现安装（真机验收需 AEDT）")
    return str(install["path"])


@pytest.fixture()
def lightweight_wilkinson_recipe(tmp_path):
    """轻量窄带配方（11 点 / delta 0.1，真机约 45s）——真机时间敏感，控短。"""
    import yaml
    recipe = {
        "model": "wilkinson_power_divider",
        "schema_version": 1,
        "notes": "真机验收轻量版：窄带 11 点",
        "params": {
            "f0_ghz": {"value": 2.4, "unit": "GHz"},
            "z0_ohm": {"value": 50, "unit": "ohm"},
            "substrate": "rogers4350b_h0.508",
            "division": "1:1",
            "arm_len_mm": {"value": 20.5},
            "series_w_mm": {"value": 0.33},
            "shunt_w_mm": {"value": 1.10},
        },
        "setup": {
            "solver": "DrivenModal",
            "freq_range_ghz": [2.3, 2.5],
            "points": 11,
            "convergence_delta": 0.1,
            "radiation_box": "open",
        },
        "objectives": [
            {"metric": "s11_db", "band": [2.3, 2.5], "op": "max_below", "value": -15},
            {"metric": "s21_db", "band": [2.3, 2.5], "op": "mean_within", "value": [-3.6, -3.1]},
        ],
        "export": {"touchstone": {"renorm_ohm": 50, "deembed": False}},
    }
    path = tmp_path / "recipe.yaml"
    path.write_text(yaml.safe_dump(recipe, allow_unicode=True), encoding="utf-8")
    return str(path)
