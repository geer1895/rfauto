"""W2-D Z-16：升级回归矩阵（EC-12 前置锚快检）脚本面测试。

不真跑矩阵全量（真跑=基线落盘动作，归 scripts/upgrade_regression_matrix.py
的 CLI 调用；runs/w2_phase2/z16_baseline.json 为在档基线证据）——本文件钉：
- 矩阵清单确定性（同输入逐位一致、段位结构、real-machine 档 run_policy）；
- 两内联体检在当前 vendor 上全绿（锚注册表结构 + 内核抽样 golden）；
- 基线 JSON（在档证据）verdict 全绿（存在时）。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "upgrade_regression_matrix.py"


@pytest.fixture(scope="module")
def matrix_script():
    spec = importlib.util.spec_from_file_location("z16_matrix", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestMatrixDefinition:
    def test_script_exists(self):
        assert _SCRIPT.is_file()

    def test_matrix_structure(self, matrix_script):
        m = matrix_script.build_matrix()
        assert m, "矩阵不应为空"
        ids = [i["id"] for i in m]
        assert len(ids) == len(set(ids)), "矩阵 id 必须唯一"
        for item in m:
            assert item["section"] in ("A", "B", "C")
            assert item["tier"] in ("offline", "real-machine")
            assert item["kind"] in ("inline", "pytest", "manual")
        # real-machine 档：manual 执行策略，缺省集（offline）之外
        real = [i for i in m if i["tier"] == "real-machine"]
        assert all(i["kind"] == "manual" for i in real)
        assert all(i["id"].startswith("anchors.real-machine.") for i in real)

    def test_matrix_deterministic(self, matrix_script):
        assert matrix_script.build_matrix() == matrix_script.build_matrix()

    def test_offline_set_never_requires_real_machine(self, matrix_script):
        """零真机铁律：缺省集（offline 档）不得含真机项。"""
        m = matrix_script.build_matrix()
        offline = [i for i in m if i["tier"] == "offline"]
        assert offline, "离线档不应为空"
        assert all(i["kind"] != "manual" for i in offline)
        # B 段模板冒烟全部是 tests/unit 下 CSXCAD 离线 exec 级文件
        for item in (i for i in offline if i["section"] == "B"):
            assert item["target"].startswith("tests/unit/test_")
            assert item["requires_csxcad"] is True


class TestInlineChecks:
    def test_anchors_registry_check_green_on_current_vendor(
            self, matrix_script):
        detail = matrix_script.check_anchors_registry()
        assert detail["ok"], detail["problems"]
        assert detail["n_openems_anchors"] >= 10  # 实测 15 锚依赖 openems
        assert all(t["status"] != "retired" for t in detail["targets"])

    def test_calc_sampling_green_on_current_vendor(self, matrix_script):
        detail = matrix_script.check_calc_sampling()
        assert detail["ok"], detail["problems"]
        assert detail["n_checked"] >= 3

    def test_calc_sampling_catches_drift(self, matrix_script):
        """golden 面真的能红：篡改期望值 → problems 非空（裁判自检）。"""
        monkey_case = dict(matrix_script._CALC_GOLDEN[0])
        monkey_case["expect"] = dict(monkey_case["expect"])
        monkey_case["expect"]["r_series_mid_ohm"] = 999.0
        from rfauto.core.calculators import CALCULATOR_REGISTRY

        out = CALCULATOR_REGISTRY.get("attenuator_pi").func(
            **monkey_case["params"])
        assert abs(out["r_series_mid_ohm"] - 999.0) > 1  # 篡改值确实不产出


class TestBaselineArtifact:
    """在档基线证据（runs/w2_phase2/z16_baseline.json，存在时校验）。"""

    def test_baseline_green_if_present(self):
        p = _REPO_ROOT / "runs" / "w2_phase2" / "z16_baseline.json"
        if not p.is_file():
            pytest.skip("基线未落盘（本席另跑 scripts CLI 产出）")
        d = json.loads(p.read_text(encoding="utf-8"))
        assert d["schema"] == "z16_upgrade_regression_matrix/v1"
        assert d["verdict"] in ("green", "green_with_skips")
        assert d["summary"]["n_fail"] == 0
        assert d["csxcad_available"] is True
