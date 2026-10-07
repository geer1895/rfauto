"""XC-U 全链不确定度账本锚树（round19 P1"四处挂点纯编排"）。

判据（#122 预声明，#118 独立来源）：本面零新物理数字——
- GUM 段手算基准：u=[0.1,0.2]（c=1）→ u_c=√(0.01+0.04)=0.22360679…，
  U(k=2)=0.44721359…（手算值直接断言，非内核自证）；
- 仿真段手算基准：grid_discretization(a=0.1, b=0.01, base=1.0) →
  dev=0.11 常数谱 → u_std=0.11（两点分解闭式 #313）；
- 材料段：u95/k 显式折算恒等式；
- 产线段：**链通语义**=production 未给 u95 时消费测量段 U（链不断）；
- 聚合语义：#105 段缺→unknown 不阻塞；#121 单位不一→跨段最大分量
  指针不给（None+note）；CSV 渲染逐行对照。
"""

from __future__ import annotations

import csv
import io
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.service import uncertainty_ledger_service as ul


def _stages(out):
    return {row["stage"]: row for row in out["stages"]}


class TestGumStage:
    def test_hand_computed_gum(self):
        out = ul.uncertainty_ledger({
            "measurement": {"components": [
                {"name": "a", "u": 0.1}, {"name": "b", "u": 0.2}],
                "unit": "dB"}})
        row = _stages(out)["measurement"]
        assert row["status"] == "ok"
        assert row["result"]["u_std"] == pytest.approx(0.223606797749979, rel=1e-12)
        assert row["result"]["U"] == pytest.approx(0.447213595499958, rel=1e-12)
        assert [c["name"] for c in row["result"]["contributions"]] == \
            ["b", "a"]  # 最大分量优先排序

    def test_missing_components_unknown(self):
        out = ul.uncertainty_ledger({"measurement": {}})
        assert _stages(out)["measurement"]["status"] == "unknown"

    def test_bad_component_error(self):
        out = ul.uncertainty_ledger({
            "measurement": {"components": [{"name": "x"}]}})  # 缺 u
        assert _stages(out)["measurement"]["status"] == "error"


class TestSimulationStage:
    def test_grid_discretization_hand_value(self):
        out = ul.uncertainty_ledger({
            "simulation": {"items": [
                {"type": "budget.grid_discretization", "a": 0.1, "b": 0.01,
                 "base": 1.0}],
                "f_hz": [1e9], "unit": "dB"}})
        row = _stages(out)["simulation"]
        assert row["status"] == "ok"
        assert row["result"]["u_std"] == pytest.approx(0.11, rel=1e-12)
        assert row["result"]["contributions"][0]["share"] == pytest.approx(1.0)

    def test_quadratic_sum_two_items(self):
        # 手算勾股数 RSS 独立基准：0.3 与 0.4 → 0.5。
        # port_reference |Γ|=dev/(100+dev)=0.4 ⇔ dev=200/3（闭式反解）
        out = ul.uncertainty_ledger({
            "simulation": {"items": [
                {"type": "budget.grid_discretization", "a": 0.3, "b": 0.0,
                 "base": 1.0},
                {"type": "budget.port_reference", "z0_deviance": 200.0 / 3.0,
                 "z0_ref": 50.0}],
                "f_hz": [1e9]}})
        row = _stages(out)["simulation"]
        assert row["status"] == "ok"
        assert row["result"]["u_std"] == pytest.approx(0.5, rel=1e-12)

    def test_bypass_u_num(self):
        out = ul.uncertainty_ledger({
            "simulation": {"u_num": 0.25, "unit": "dB"}})
        row = _stages(out)["simulation"]
        assert row["status"] == "ok"
        assert row["result"]["bypass"] is True
        assert row["result"]["u_std"] == 0.25

    def test_absent_unknown(self):
        out = ul.uncertainty_ledger({})
        assert _stages(out)["simulation"]["status"] == "unknown"


class TestChain:
    def _full_payload(self):
        return {
            "material": {"name": "er_fit", "u95": 0.02, "k": 2.0,
                         "unit": "dimensionless"},
            "simulation": {"items": [
                {"type": "budget.grid_discretization", "a": 0.1, "b": 0.01,
                 "base": 1.0}], "f_hz": [1e9], "unit": "dB"},
            "measurement": {"components": [{"name": "cal", "u": 0.1}],
                            "unit": "dB"},
            "production": {"value": -14.5, "spec": -10.0, "side": "upper",
                           "pfa_target": 0.02, "k": 2.0, "unit": "dB"},
        }

    def test_production_chains_measurement_u(self):
        out = ul.uncertainty_ledger(self._full_payload())
        st = _stages(out)
        assert st["production"]["status"] == "ok"
        assert st["production"]["result"]["chained_u95"] is True
        assert st["production"]["result"]["u95"] == pytest.approx(
            _stages(out)["measurement"]["result"]["U"])

    def test_chain_dict_and_material(self):
        out = ul.uncertainty_ledger(self._full_payload())
        assert out["chain"]["u_material"] == pytest.approx(0.01)
        assert "u_measurement" in out["chain"]
        assert "U_production" in out["chain"]

    def test_mixed_units_no_cross_stage_max(self):
        out = ul.uncertainty_ledger(self._full_payload())
        assert out["cross_stage_max"] is None
        assert "单位不一" in out["unit_note"]

    def test_uniform_units_gives_cross_stage_max(self):
        payload = self._full_payload()
        payload["material"]["unit"] = "dB"  # 全链同单位（演示口径）
        out = ul.uncertainty_ledger(payload)
        assert out["cross_stage_max"] is not None
        best = out["cross_stage_max"]
        all_u = [c["u"] for c in out["contributions"] if c.get("u") is not None]
        assert best["u"] == pytest.approx(max(all_u))
        assert 0.0 < best["share"] <= 1.0

    def test_chain_broken_without_measurement(self):
        payload = self._full_payload()
        del payload["measurement"]
        out = ul.uncertainty_ledger(payload)
        st = _stages(out)
        assert st["measurement"]["status"] == "unknown"
        assert st["production"]["status"] == "unknown"
        assert "断在测量段" in st["production"]["detail"]
        assert out["ok"] is True  # 段缺不炸账本（#105）


class TestCsv:
    def test_render_and_write_roundtrip(self, tmp_path):
        out = ul.uncertainty_ledger({
            "measurement": {"components": [{"name": "cal", "u": 0.1}],
                            "unit": "dB"}})
        text = ul.render_uncertainty_chain_csv(out)
        rows = list(csv.reader(io.StringIO(text)))
        assert rows[0] == ["stage", "status", "u_std", "unit", "component",
                           "u_component", "share"]
        data_rows = rows[1:]
        assert any(r[4] == "cal" and float(r[5]) == pytest.approx(0.1)
                   for r in data_rows)
        p = ul.write_uncertainty_chain_csv(out, tmp_path / "u_chain.csv")
        assert p.read_text(encoding="utf-8") == text
