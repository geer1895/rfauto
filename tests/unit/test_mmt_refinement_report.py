"""DP-1④ service 面接线：mmt_service.iris_refinement_report 合成链单测。

零真机零 runs/ 产物（纯 numpy 秒级）：WR-90 居中感性膜片小例（与
test_rwg_mmt_refinement 同族口径）经 JSON 段表 → service 信封 → core
对照/触发判定逐键透传。覆盖：
- 缺省腿（无 refined 无槽位）：ok=True，comparison.refined/refinement=None；
- blocked 槽位合法透传：refinement 元数据原样、refined=None（不产数值）；
- 冒充拒绝：blocked 槽位 + refined 段表 / 无槽位裸 refined 段表 →
  ok=False 信封（core ValueError 消息透传，#122）；
- active 槽位双腿：refined 腿产出 s2x2 数值；
- g1 触发判定：方向/单调/长度不符/非法元素/掩码；
- 段表契约：缺 sections / 非 dict payload → bad_request 信封（不抛异常）；
- 严格契约（df7fix2 P2）：refinement_slot 非 dict / status 非法裸
  ValueError → bad_request 信封；g1.judged 严格 bool（禁 bool() 强转）。

MCP/CLI 本项不接（登记面）；分层纪律：service 信封失败路径不抛异常
（与 solve_mmt 同款口径）。
"""
from __future__ import annotations

import pytest

from rfauto.service.mmt_service import iris_refinement_report

_A_MM, _B_MM = 22.86, 10.16          # WR-90（mm 口径输入）
_FREQS = [10.0, 10.5]                # 带内两点（近截止风险外，秒级）


def _sections_json(aperture_mm: float = 16.0) -> list[dict]:
    """WR-90 + 零厚感性膜片 d=aperture 的 JSON 段表（uniform|iris 三段）。"""
    wg = {"a_mm": _A_MM, "b_mm": _B_MM}
    return [
        {"type": "uniform", **wg, "length_mm": 10.0},
        {"type": "iris", **wg, "aperture_mm": aperture_mm, "thickness_mm": 0.0},
        {"type": "uniform", **wg, "length_mm": 10.0},
    ]


def _slot_json(status: str) -> dict:
    return {"formula_id": "xu_wu_2005_w_eff", "status": status,
            "candidate_formula": "a_eff = a - 1.08*d^2/s + 0.1*d^2/a",
            "source": "IEEE TMTT 53(1) 2005（合成测试桩，非核对声明）",
            "verification_note": "单测 fixture；语义由 core 构件校验"}


class TestDefaultLeg:
    def test_default_leg_only_reports_s2x2(self) -> None:
        out = iris_refinement_report({"sections": _sections_json(),
                                      "freqs_ghz": _FREQS})
        assert out["ok"] is True
        comp = out["comparison"]
        assert comp["schema"] == "rfauto-mmt-refinement/v1"
        assert comp["n_points"] == len(_FREQS)
        assert comp["freqs_ghz"] == pytest.approx(_FREQS)
        assert comp["refined"] is None
        assert comp["refinement"] is None
        # 缺省腿出数值：S11/S21 行均为 [re, im] 对（determined 频点）
        for row in comp["default"]["s2x2"]:
            for cell in row:
                assert cell is not None and len(cell) == 2
        assert comp["default"]["converged"] is True

    def test_undetermined_none_passthrough_is_json_safe(self) -> None:
        """信封整体 JSON 可序列化（复数=[re,im]、undetermined=None 口径）。"""
        import json
        out = iris_refinement_report({"sections": _sections_json(),
                                      "freqs_ghz": _FREQS})
        assert json.loads(json.dumps(out))["ok"] is True


class TestBlockedSlotSemantics:
    def test_blocked_slot_passthrough_without_refined(self) -> None:
        """blocked 槽位（无 refined 段表）合法：元数据透传、refined=None。"""
        out = iris_refinement_report({"sections": _sections_json(),
                                      "freqs_ghz": _FREQS,
                                      "refinement_slot": _slot_json("blocked")})
        assert out["ok"] is True
        comp = out["comparison"]
        assert comp["refined"] is None
        assert comp["refinement"]["status"] == "blocked"
        assert comp["refinement"]["formula_id"] == "xu_wu_2005_w_eff"
        assert comp["refinement"]["verification_note"]

    def test_refined_with_blocked_slot_rejected(self) -> None:
        """blocked 槽位携带 refined 段表 → ok=False（core 拒绝消息透传）。"""
        out = iris_refinement_report({"sections": _sections_json(),
                                      "freqs_ghz": _FREQS,
                                      "refined_sections": _sections_json(15.0),
                                      "refinement_slot": _slot_json("blocked")})
        assert out["ok"] is False
        assert out["status"] == "refinement_violation"
        assert out["comparison"] is None
        assert any("blocked" in e for e in out["errors"])

    def test_refined_without_slot_rejected(self) -> None:
        """无槽位裸 refined 段表 → ok=False（精化数值必须携带元数据）。"""
        out = iris_refinement_report({"sections": _sections_json(),
                                      "freqs_ghz": _FREQS,
                                      "refined_sections": _sections_json(15.0)})
        assert out["ok"] is False
        assert out["status"] == "refinement_violation"
        assert any("槽位" in e for e in out["errors"])

    def test_active_slot_dual_leg_produces_numbers(self) -> None:
        """active 槽位 + refined 段表：双腿 s2x2 都出数值（框架全通）。"""
        out = iris_refinement_report({"sections": _sections_json(),
                                      "freqs_ghz": _FREQS,
                                      "refined_sections": _sections_json(15.0),
                                      "refinement_slot": _slot_json("active")})
        assert out["ok"] is True
        comp = out["comparison"]
        assert comp["refinement"]["status"] == "active"
        for leg in ("default", "refined"):
            for row in comp[leg]["s2x2"]:
                for cell in row:
                    assert cell is not None and len(cell) == 2


class TestG1Leg:
    def test_g1_monotonic_negative_direction(self) -> None:
        freqs4 = [10.0, 10.25, 10.5, 10.75]
        dev = [-1.0, -1.2, -0.9, -1.1]
        out = iris_refinement_report({"sections": _sections_json(),
                                      "freqs_ghz": freqs4,
                                      "g1": {"signed_dev_db": dev}})
        assert out["ok"] is True
        assert out["g1"]["direction"] == -1
        assert out["g1"]["monotonic_direction"] is True
        assert out["g1"]["signed_median_db"] == pytest.approx(
            sorted(dev)[1] / 2 + sorted(dev)[2] / 2)
        assert out["g1"]["n_judged"] == 4

    def test_g1_judged_mask_excludes_points(self) -> None:
        freqs4 = [10.0, 10.25, 10.5, 10.75]
        dev = [2.0, 2.0, -5.0, -5.0]
        out = iris_refinement_report({
            "sections": _sections_json(), "freqs_ghz": freqs4,
            "g1": {"signed_dev_db": dev, "judged": [True, True, False, False]}})
        assert out["g1"]["n_judged"] == 2
        assert out["g1"]["direction"] == 1

    def test_g1_length_mismatch_envelope(self) -> None:
        out = iris_refinement_report({"sections": _sections_json(),
                                      "freqs_ghz": _FREQS,
                                      "g1": {"signed_dev_db": [0.1, 0.2, 0.3]}})
        assert out["ok"] is False
        assert out["status"] == "bad_request"
        assert any("不一致" in e for e in out["errors"])

    def test_g1_non_numeric_envelope(self) -> None:
        out = iris_refinement_report({"sections": _sections_json(),
                                      "freqs_ghz": _FREQS,
                                      "g1": {"signed_dev_db": ["x", "y"]}})
        assert out["ok"] is False
        assert out["status"] == "bad_request"
        assert any("非数值" in e for e in out["errors"])

    def test_g1_judged_wrong_length_envelope(self) -> None:
        out = iris_refinement_report({
            "sections": _sections_json(), "freqs_ghz": _FREQS,
            "g1": {"signed_dev_db": [0.1, 0.2], "judged": [True]}})
        assert out["ok"] is False
        assert out["status"] == "bad_request"


class TestRequestContract:
    def test_missing_sections_envelope(self) -> None:
        out = iris_refinement_report({"freqs_ghz": _FREQS})
        assert out["ok"] is False
        assert out["status"] == "bad_request"

    def test_non_dict_payload_envelope(self) -> None:
        out = iris_refinement_report([1, 2, 3])  # type: ignore[arg-type]
        assert out["ok"] is False
        assert out["status"] == "bad_request"

    def test_bad_section_type_envelope(self) -> None:
        out = iris_refinement_report({"sections": [{"type": "magic"}],
                                      "freqs_ghz": _FREQS})
        assert out["ok"] is False
        assert out["status"] == "bad_request"
        assert any("未知段类型" in e for e in out["errors"])

    def test_bad_freq_grid_envelope(self) -> None:
        out = iris_refinement_report({"sections": _sections_json(),
                                      "freqs_ghz": [12.0, 10.0]})
        assert out["ok"] is False
        assert out["status"] == "bad_request"
        assert any("严格递增" in e for e in out["errors"])


class TestSlotAndJudgedStrictContract:
    """P2（df7fix2 第二轮审查）：信封契约击穿修复回归钉。

    ① refinement_slot 非 dict → bad_request 信封（此前 slot_raw.get 对
       非 dict 裸抛 AttributeError 击穿"信封不抛"契约）；
    ② RefinementSlot 构造裸 ValueError（status 非 blocked/active）→
       bad_request 信封（此前穿透为未处理异常）；
    ③ g1.judged 严格 bool 校验（禁 bool() 强转 #175）：bool("yes")/bool(0.0)
       类静默翻转一律 bad_request。
    """

    def test_refinement_slot_str_envelope(self) -> None:
        out = iris_refinement_report({"sections": _sections_json(),
                                      "freqs_ghz": _FREQS,
                                      "refinement_slot": "blocked"})
        assert out["ok"] is False
        assert out["status"] == "bad_request"
        assert any("refinement_slot" in e for e in out["errors"])

    def test_refinement_slot_list_envelope(self) -> None:
        out = iris_refinement_report({"sections": _sections_json(),
                                      "freqs_ghz": _FREQS,
                                      "refinement_slot": ["blocked"]})
        assert out["ok"] is False
        assert out["status"] == "bad_request"
        assert any("refinement_slot" in e for e in out["errors"])

    def test_refinement_slot_bad_status_valueerror_envelope(self) -> None:
        out = iris_refinement_report({"sections": _sections_json(),
                                      "freqs_ghz": _FREQS,
                                      "refinement_slot": _slot_json("pending")})
        assert out["ok"] is False
        assert out["status"] == "bad_request"
        assert any("status" in e for e in out["errors"])

    def test_g1_judged_string_coercion_rejected(self) -> None:
        """bool("yes")==True 的静默翻转（#175 v2 宽松同族）必须拒绝。"""
        out = iris_refinement_report({
            "sections": _sections_json(), "freqs_ghz": _FREQS,
            "g1": {"signed_dev_db": [0.1, -0.2],
                   "judged": [True, "yes"]}})
        assert out["ok"] is False
        assert out["status"] == "bad_request"
        assert any("严格 bool" in e for e in out["errors"])

    def test_g1_judged_numeric_and_none_coercion_rejected(self) -> None:
        for bad in (1, 0.0, None):
            out = iris_refinement_report({
                "sections": _sections_json(), "freqs_ghz": _FREQS,
                "g1": {"signed_dev_db": [0.1, -0.2],
                       "judged": [True, bad]}})
            assert out["ok"] is False, f"非 bool 元素 {bad!r} 未拒绝"
            assert out["status"] == "bad_request"

    def test_g1_judged_true_bools_still_pass(self) -> None:
        """严格校验不误伤真 bool 掩码（回归护栏）。"""
        out = iris_refinement_report({
            "sections": _sections_json(), "freqs_ghz": _FREQS,
            "g1": {"signed_dev_db": [2.0, 2.0],
                   "judged": [True, False]}})
        assert out["ok"] is True
        assert out["g1"]["n_judged"] == 1
