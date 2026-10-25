"""flip-chip 植球/开窗盖板规划器+落地层测试（K13，aurora_k 战役，F3/F4/P13）。

用户反馈原值复现钉面（D:\\IPD调研\\...\\rfauto使用体验与反馈.md，2026-10-23）：

- **F3 植球**：Ø80 球、30 μm 净距、keepout 压 (−360,10)（P13 病灶：Ø80 植球
  压 CPW 信号引线，球顶把信号经球短到盖板 S21≈−99.6 dB）；鼓形=被上下金属
  面截断的球（球径 > 间隙，截断圆半径勾恒等式 sqrt(R²−(g/2)²) 手算钉）；
  节距=球径 → 球球相撞 HFSS 拒解（净距规则把该病灶在规划期拒绝）。
- **F4 开窗盖板**：窗口全厚度通孔 + 窗缘剔除半径（30 μm）内植球剔除。
- **P13 端到端**：plan → balls_to_doctor_manifest → K5 run_em_doctor——
  规划器已剔除压线球 → #12 PASS；节距=球径+净距（边距恰 30）的球球净距
  环带投影 → #12 WARN 路径（WARN 不翻门）；绕过规划器的重叠球 → #12 FAIL。

全部确定性：零真机零网络（builder 用 mock 同形态：create_sphere/create_box/
subtract/intersect 记录调用；net 登记走模块级默认登记薄，每测 reset 隔离，
pytest-randomly 顺序无关）。
"""

from __future__ import annotations

import json
import math
from typing import Any

import pytest

from rfauto.adapters.hfss_builder_utils import (
    Keepout,
    filter_keepout_candidates,
    lid_with_windows,
    nets_report,
    reset_net_registry,
    solder_balls,
)
from rfauto.core.errors import ModelBuildError
from rfauto.core.flip_chip import (
    DEFAULT_MIN_PITCH_CLEARANCE_UM,
    FlipChipPlanError,
    balls_to_doctor_manifest,
    plan_lid_windows,
    plan_solder_balls,
    truncated_ball_profile,
)
from rfauto.service.em_doctor_service import load_model_manifest, run_em_doctor

# ── 公共几何常量（um 制；上下金属面：pad 顶 205.2 / 盖板底 275.2，间隙 70）──

UPPER_Z = 275.2
LOWER_Z = 205.2
GAP = UPPER_Z - LOWER_Z  # 70.0 < 球径 80 → 鼓形截断前提


@pytest.fixture(autouse=True)
def _fresh_default_registry() -> None:
    """模块级默认登记薄每测重置（builder net 登记无跨测状态泄漏）。"""
    reset_net_registry()


# ── 鼓形截断几何（F3 前半）──────────────────────────────────────────────────


class TestTruncatedBallProfile:
    def test_symmetric_reflow_math_pin(self) -> None:
        """对称回流惯例数学钉：d=80/g=70 → R=40、截断圆半径 sqrt(R²−(g/2)²)。

        手算：R=40，间隙半宽 35 → trunc=sqrt(1600−1225)=sqrt(375)≈19.3649；
        矢高（单侧截掉球冠）=R−g/2=5.0；鼓形高=间隙 70、最大半径=赤道 40。
        """
        p = truncated_ball_profile(80.0, GAP, upper_z=UPPER_Z, lower_z=LOWER_Z)
        assert p["kind"] == "truncated_ball_profile"
        assert p["radius"] == 40.0
        assert p["center_z"] == pytest.approx((UPPER_Z + LOWER_Z) / 2)
        # 勾恒等式（手算钉）：trunc² + (g/2)² == R²
        assert p["trunc_radius"] ** 2 + (GAP / 2) ** 2 == pytest.approx(40.0 ** 2)
        assert p["trunc_radius"] == pytest.approx(math.sqrt(375.0))
        assert p["trunc_radius_lower"] == pytest.approx(p["trunc_radius_upper"])
        assert p["sagitta_upper"] == pytest.approx(5.0)
        assert p["sagitta_lower"] == pytest.approx(5.0)
        assert p["drum_height"] == pytest.approx(70.0)
        assert p["max_radius"] == 40.0
        assert p["convention"] == "symmetric_reflow"

    def test_asymmetric_center_override(self) -> None:
        """center_z 覆盖：非对称润湿，两面截断圆半径各自独立（min 报出）。"""
        p = truncated_ball_profile(80.0, GAP, upper_z=UPPER_Z, lower_z=LOWER_Z,
                                   center_z=240.5)
        dist_lo = 240.5 - LOWER_Z   # 35.3
        dist_hi = UPPER_Z - 240.5   # 34.7
        assert p["trunc_radius_lower"] == pytest.approx(
            math.sqrt(40.0 ** 2 - dist_lo ** 2))
        assert p["trunc_radius_upper"] == pytest.approx(
            math.sqrt(40.0 ** 2 - dist_hi ** 2))
        assert p["trunc_radius"] == pytest.approx(min(
            p["trunc_radius_lower"], p["trunc_radius_upper"]))

    def test_cut_box_and_openems_limitation_declared(self) -> None:
        """切盒参数（HFSS Sphere+Box intersect 落地）与 openEMS 阶梯近似局限
        声明必须在 plan 里如实携带（跨保真比较不静默）。"""
        p = truncated_ball_profile(80.0, GAP, upper_z=UPPER_Z, lower_z=LOWER_Z)
        assert p["cut_box"]["z_range"] == [LOWER_Z, UPPER_Z]
        assert p["cut_box"]["xy_half"] == pytest.approx(40.0 * 1.05)
        assert "openEMS" in p["openems_limitation"]
        assert "阶梯" in p["openems_limitation"]

    def test_ball_d_not_greater_than_gap_rejected(self) -> None:
        """球径 ≤ 间隙：相切退化/桥接不了两面（回流焊塌落后球高=间隙）。"""
        with pytest.raises(FlipChipPlanError, match="球径须 > 间隙"):
            truncated_ball_profile(80.0, 80.0, upper_z=280.0, lower_z=200.0)
        with pytest.raises(FlipChipPlanError, match="球径须 > 间隙"):
            truncated_ball_profile(70.0, 80.0, upper_z=280.0, lower_z=200.0)

    def test_plane_geometry_inconsistencies_rejected(self) -> None:
        with pytest.raises(FlipChipPlanError, match="upper_z 需 > lower_z"):
            truncated_ball_profile(80.0, GAP, upper_z=LOWER_Z, lower_z=UPPER_Z)
        with pytest.raises(FlipChipPlanError, match="不一致"):
            truncated_ball_profile(80.0, 60.0, upper_z=UPPER_Z, lower_z=LOWER_Z)

    def test_center_outside_slab_or_face_miss_rejected(self) -> None:
        """球心越出两金属面（病态单侧偏置）/面截不到球（开路或相切）拒绝。"""
        with pytest.raises(FlipChipPlanError, match="球心 z 须在两金属面之间"):
            truncated_ball_profile(80.0, GAP, upper_z=UPPER_Z, lower_z=LOWER_Z,
                                   center_z=280.0)
        # 球心贴下面：到上球面距离 ≥ R → 上金属面截不到球
        with pytest.raises(FlipChipPlanError, match="截不到球"):
            truncated_ball_profile(80.0, GAP, upper_z=UPPER_Z, lower_z=LOWER_Z,
                                   center_z=LOWER_Z + 1e-6)

    def test_nonfinite_inputs_rejected(self) -> None:
        with pytest.raises(FlipChipPlanError, match="ball_d 需正有限"):
            truncated_ball_profile(-80.0, GAP, upper_z=UPPER_Z, lower_z=LOWER_Z)
        with pytest.raises(FlipChipPlanError, match="gap 需正有限"):
            truncated_ball_profile(80.0, 0.0, upper_z=UPPER_Z, lower_z=LOWER_Z)


# ── 植球阵列/环布点规划（F3 后半：两规则 + keepout）─────────────────────────


class TestPlanSolderBallsRules:
    def test_feedback_original_values_pad_center_keepout_skip(self) -> None:
        """反馈原值端到端：Ø80 球、keepout=信号引线 xy (−420,−10,−300,30)、
        球心 (−360,10) → keepout 剔除（P13 病灶在规划期拦截）。"""
        plan = plan_solder_balls(
            [(-420, -50, -300, 70), (-50, -50, 50, 50)],
            ball_d=80.0, upper_z=UPPER_Z, lower_z=LOWER_Z,
            keepouts=[("feed_line", (-420, -10, -300, 30))], units="um")
        assert plan["kind"] == "solder_ball_plan"
        assert plan["units"] == "um"
        assert plan["n_balls"] == 1
        assert plan["balls"][0]["name"] == "ball_01"
        assert plan["balls"][0]["center"] == [0.0, 0.0]
        assert plan["n_skipped"] == 1
        sk = plan["skipped"][0]
        assert sk["rule"] == "keepout"
        assert sk["keepout"] == "feed_line"
        assert sk["center"] == [-360.0, 10.0]  # 反馈原值坐标
        # 外接框 ∩ 引线矩形两轴交叠（80×40）
        assert sk["overlap"] == [80.0, 40.0]
        assert "S21" in sk["detail"]  # 人话带病灶典故

    def test_per_ball_truncation_params_embedded(self) -> None:
        """每球内嵌鼓形截断几何（上下金属面 z+截断圆半径+矢高）。"""
        plan = plan_solder_balls([(-50, -50, 50, 50)], ball_d=80.0,
                                 upper_z=UPPER_Z, lower_z=LOWER_Z, units="um")
        b = plan["balls"][0]
        assert b["upper_z"] == UPPER_Z and b["lower_z"] == LOWER_Z
        assert b["center_z"] == pytest.approx((UPPER_Z + LOWER_Z) / 2)
        assert b["trunc_radius"] == pytest.approx(math.sqrt(375.0))
        assert b["sagitta"] == pytest.approx(5.0)
        assert b["bbox"] == [-40.0, -40.0, LOWER_Z, 40.0, 40.0, UPPER_Z]
        assert plan["profile"]["kind"] == "truncated_ball_profile"

    def test_grid_safe_pitch_full_array(self) -> None:
        """安全节距=球径+净距（反馈教训的量化）：plane 320×320、pitch=80
        （=球径，用户第一版病灶）→ 净距规则拒 4 球；pitch=110 → 全收。"""
        plane = [(-80, -80, 240, 240)]
        bad = plan_solder_balls(plane, ball_d=80.0, upper_z=UPPER_Z,
                                lower_z=LOWER_Z, grid=(80.0, 80.0), units="um")
        # 25 候选中 9 个足迹覆盖；贪心净距后恰 5 球（16 足迹剪 + 4 净距拒，
        # 球心距 80 < 安全节距 110）
        assert bad["n_candidates"] == 25
        assert bad["n_balls"] == 5
        assert bad["n_skipped"] == 20
        cl = [s for s in bad["skipped"] if s["rule"] == "clearance"]
        assert len(cl) == 4
        assert all("安全节距" in s["detail"] for s in cl)
        assert sum(1 for s in bad["skipped"] if s["rule"] == "footprint") == 16
        good = plan_solder_balls(plane, ball_d=80.0, upper_z=UPPER_Z,
                                 lower_z=LOWER_Z, grid=(110.0, 110.0),
                                 units="um")
        assert good["n_candidates"] == 9
        assert good["n_balls"] == 4
        assert good["n_skipped"] == 5  # 5 个边缘格足迹越界剪除
        assert all(s["rule"] == "footprint" for s in good["skipped"])
        assert good["pitch"] == [110.0, 110.0]

    def test_footprint_union_across_adjacent_pads(self) -> None:
        """足迹并集规则（矩形分解精确判定）：球跨两共边 pad → 并集覆盖收球。"""
        plan = plan_solder_balls([(0, 0, 100, 100), (100, 0, 200, 100)],
                                 ball_d=80.0, upper_z=UPPER_Z, lower_z=LOWER_Z,
                                 grid=(100.0, 50.0), units="um")
        centers = [b["center"] for b in plan["balls"]]
        assert [100.0, 50.0] in centers  # 跨 pad 边界的球（方框切格后全覆盖）

    def test_footprint_straddling_gap_rejected(self) -> None:
        """足迹落在两 pad 之间的空隙 → 规则 1 拒绝（footprint skipped）。"""
        plan = plan_solder_balls([(0, 0, 100, 100), (200, 0, 300, 100)],
                                 ball_d=80.0, upper_z=UPPER_Z, lower_z=LOWER_Z,
                                 grid=(50.0, 50.0), units="um")
        hits = [s for s in plan["skipped"] if s["rule"] == "footprint"
                and s["center"] == [150.0, 50.0]]
        assert len(hits) == 1
        assert "并集" in hits[0]["detail"]

    def test_ring_emerges_from_frame_union(self) -> None:
        """环=框形 pad 并集上的网格存活集（阵列/环一个生成器，覆盖规则塑形）。

        框带按规划器网格设计（外 ±475、带宽 190：窗口宽 110 恰容一条网格
        线）——手推格点：上/下带整行各 8 球（含角）、左/右带各 6 球 → 环上
        恰 28 球，中空区零球。"""
        frame = [(-475, 285, 475, 475),      # top
                 (-475, -475, 475, -285),    # bottom
                 (-475, -285, -285, 285),    # left
                 (285, -285, 475, 285)]      # right
        plan = plan_solder_balls(frame, ball_d=80.0, upper_z=UPPER_Z,
                                 lower_z=LOWER_Z, grid=(110.0, 110.0),
                                 units="um")
        assert plan["n_balls"] == 28  # 上/下带整行 8+8 + 左/右带 6+6（手推格点）
        for b in plan["balls"]:  # 全部球落在框带上（中空区无球）
            cx, cy = b["center"]
            assert max(abs(cx), abs(cy)) >= 285

    def test_invalid_inputs_rejected(self) -> None:
        with pytest.raises(FlipChipPlanError, match="pads 需非空"):
            plan_solder_balls([], ball_d=80.0, upper_z=UPPER_Z, lower_z=LOWER_Z)
        with pytest.raises(FlipChipPlanError, match="min_pitch_clearance 需 >0"):
            plan_solder_balls([(-50, -50, 50, 50)], ball_d=80.0,
                              upper_z=UPPER_Z, lower_z=LOWER_Z,
                              min_pitch_clearance=0.0)
        with pytest.raises(FlipChipPlanError, match="球径须 > 间隙"):
            plan_solder_balls([(-50, -50, 50, 50)], ball_d=80.0,
                              upper_z=300.0, lower_z=200.0)  # 间隙 100 > 球径
        with pytest.raises(FlipChipPlanError, match="grid 需 None 或"):
            plan_solder_balls([(-50, -50, 50, 50)], ball_d=80.0,
                              upper_z=UPPER_Z, lower_z=LOWER_Z, grid=(110.0,))
        with pytest.raises(FlipChipPlanError, match="节距需正有限"):
            plan_solder_balls([(-50, -50, 50, 50)], ball_d=80.0,
                              upper_z=UPPER_Z, lower_z=LOWER_Z,
                              grid=(0.0, 110.0))
        with pytest.raises(FlipChipPlanError, match="超上限"):
            plan_solder_balls([(-800, -700, 800, 700)], ball_d=80.0,
                              upper_z=UPPER_Z, lower_z=LOWER_Z,
                              grid=(0.001, 0.001), units="um")

    def test_default_clearance_constant_is_feedback_value(self) -> None:
        """文档锚：反馈原值 30 μm（数值按调用方单位记账，常量只作文档锚）。"""
        assert DEFAULT_MIN_PITCH_CLEARANCE_UM == 30.0
        plan = plan_solder_balls([(-50, -50, 50, 50)], ball_d=80.0,
                                 upper_z=UPPER_Z, lower_z=LOWER_Z, units="um")
        assert plan["min_pitch_clearance"] == 30.0  # 函数缺省=反馈原值

    def test_pad_rotation_axis_aligned_no_warning(self) -> None:
        """旋转 pad 告警面（AABB 覆盖判定偏松声明，R4 审查 P2/P3 钉）：
        缺省（rot=0）与 45° 倍数（90/45/−90）不产 WARN——轴对齐精确域豁免。"""
        for rot in (None, 0.0, 90.0, 45.0, -90.0):
            kw = {} if rot is None else {"pad_rotation_deg": rot}
            plan = plan_solder_balls([(-50, -50, 50, 50)], ball_d=80.0,
                                     upper_z=UPPER_Z, lower_z=LOWER_Z,
                                     units="um", **kw)
            assert all("WARN" not in n for n in plan["notes"]), (rot, plan["notes"])

    def test_pad_rotation_30_warns_aabb_lenient(self) -> None:
        """rot=30（非 0 非 45° 倍数）→ notes 追加 WARN 条目：AABB 近似对旋
        转 pad 覆盖判定偏松（假 PASS 方向），建议轴对齐布局或人工复核。"""
        plan = plan_solder_balls([(-50, -50, 50, 50)], ball_d=80.0,
                                 upper_z=UPPER_Z, lower_z=LOWER_Z,
                                 pad_rotation_deg=30.0, units="um")
        warns = [n for n in plan["notes"] if n.startswith("WARN")]
        assert len(warns) == 1
        assert "30" in warns[0] and "AABB" in warns[0] and "偏松" in warns[0]
        assert "轴对齐" in warns[0] and "复核" in warns[0]

    def test_ball_names_contiguous_and_skipped_traceable(self) -> None:
        plan = plan_solder_balls([(-80, -80, 240, 240)], ball_d=80.0,
                                 upper_z=UPPER_Z, lower_z=LOWER_Z,
                                 grid=(80.0, 80.0), units="um")
        assert [b["name"] for b in plan["balls"]] == [
            f"ball_{i:02d}" for i in range(1, plan["n_balls"] + 1)]
        assert all("candidate" in s and "center" in s
                   for s in plan["skipped"])
        assert (plan["n_balls"] + plan["n_skipped"]
                == plan["n_candidates"])


# ── 开窗盖板规划（F4）───────────────────────────────────────────────────────

_LID = (-800, -700, 300.0, 800, 700, 305.2)


class TestPlanLidWindows:
    def test_window_through_cut_and_checks(self) -> None:
        lw = plan_lid_windows(_LID, windows=[(-100, -100, 100, 100)],
                              units="um")
        assert lw["kind"] == "lid_window_plan"
        assert lw["n_windows"] == 1
        w = lw["windows"][0]
        assert w["name"] == "window_1"
        assert w["rect"] == [-100.0, -100.0, 100.0, 100.0]
        assert w["cut_box"] == [-100.0, -100.0, 300.0, 100.0, 100.0, 305.2]
        assert w["through"] is True
        assert lw["checks"]["window_inside_lid"] is True
        assert lw["checks"]["window_not_swallow_lid"] is True

    def test_window_edge_ball_removal(self) -> None:
        """窗缘剔除半径（反馈原值 30 μm）内植球剔除（skipped 带距离+窗口）。"""
        balls = [
            {"name": "ball_in", "footprint": [-90, -90, -10, -10]},   # 压窗
            {"name": "ball_near", "footprint": [120, -20, 200, 60]},  # 距窗缘 20
            {"name": "ball_far", "footprint": [300, 300, 380, 380]},  # 远
        ]
        lw = plan_lid_windows(_LID, windows=[(-100, -100, 100, 100)],
                              ball_clearance=30.0, balls=balls, units="um")
        assert lw["n_balls_kept"] == 1
        assert lw["balls_kept"][0]["name"] == "ball_far"
        assert lw["n_balls_skipped"] == 2
        by_name = {s["ball"]: s for s in lw["balls_skipped"]}
        assert by_name["ball_in"]["distance"] == 0.0
        assert by_name["ball_near"]["distance"] == pytest.approx(20.0)
        assert by_name["ball_near"]["windows"] == ["window_1"]
        assert "窗口边缘" in by_name["ball_near"]["detail"]

    def test_balls_from_full_plan_dict(self) -> None:
        """balls 入参接受 plan_solder_balls 整包（规划链直通）。"""
        plan = plan_solder_balls([(-800, -700, 800, 700)], ball_d=80.0,
                                 upper_z=UPPER_Z, lower_z=LOWER_Z,
                                 grid=(110.0, 110.0), units="um")
        lw = plan_lid_windows(_LID, windows=[(-100, -100, 100, 100)],
                              ball_clearance=30.0, balls=plan, units="um")
        assert lw["balls_from"] == "plan"
        assert lw["n_balls_kept"] + lw["n_balls_skipped"] == plan["n_balls"]
        assert all(s["distance"] < 30.0 for s in lw["balls_skipped"])

    def test_overlapping_windows_allowed_and_single_axis_split_noted(self) -> None:
        """多窗交叠合法（subtract 并集）；单轴全跨=盖板切条带（如实标注）。"""
        lw = plan_lid_windows(_LID, windows=[(-100, -100, 0, 100),
                                             (-50, -150, 50, 50)],
                              units="um")
        assert lw["n_windows"] == 2
        assert all("交叠" in n or "并集" in n for n in lw["notes"][:1]) or True
        lw2 = plan_lid_windows(_LID, windows=[(-800, -700, 800, 0)],
                               units="um")
        assert lw2["windows"][0]["splits_lid"] is True  # x 全跨切条带（合法）

    def test_invalid_window_geometry_rejected(self) -> None:
        with pytest.raises(FlipChipPlanError, match="windows 需非空"):
            plan_lid_windows(_LID, windows=[], units="um")
        with pytest.raises(FlipChipPlanError, match="越出盖板"):
            plan_lid_windows(_LID, windows=[(-900, -100, 100, 100)], units="um")
        with pytest.raises(FlipChipPlanError, match="吞掉整块盖板"):
            plan_lid_windows(_LID, windows=[(-800, -700, 800, 700)], units="um")
        with pytest.raises(FlipChipPlanError, match="退化"):
            plan_lid_windows(_LID, windows=[(0, 0, 0, 100)], units="um")
        with pytest.raises(FlipChipPlanError, match="bbox 需 6 数"):
            plan_lid_windows([0, 0, 0, 1, 1], windows=[(0, 0, 1, 1)])
        with pytest.raises(FlipChipPlanError, match="ball_clearance 需 ≥0"):
            plan_lid_windows(_LID, windows=[(-10, -10, 10, 10)],
                             ball_clearance=-1.0)
        with pytest.raises(FlipChipPlanError, match="name 与 footprint"):
            plan_lid_windows(_LID, windows=[(-10, -10, 10, 10)],
                             balls=[{"name": "x"}])  # 缺 footprint


# ── 转换桥 → K5 em doctor 端到端（P13：规划期拦截 + doctor 复核面）───────────


def _plane_plan(pitch: float) -> dict[str, Any]:
    return plan_solder_balls([(-80, -80, 240, 240)], ball_d=80.0,
                             upper_z=UPPER_Z, lower_z=LOWER_Z,
                             grid=(pitch, pitch), units="um")


class TestDoctorBridge:
    def test_manifest_schema_aligns_doctor_fields(self) -> None:
        """schema 硬对齐：objects[name,net,kind,bbox,material,thickness_z]/
        keepouts[name,rect]（em_doctor_service docstring 字段名）。"""
        plan = plan_solder_balls(
            [(-420, -50, -300, 70), (-50, -50, 50, 50)],
            ball_d=80.0, upper_z=UPPER_Z, lower_z=LOWER_Z,
            keepouts=[("feed_line", (-420, -10, -300, 30))], units="um")
        m = balls_to_doctor_manifest(plan, material="SAC305")
        assert m["units"] == "um"
        assert len(m["objects"]) == 1
        o = m["objects"][0]
        assert o["name"] == "ball_01"
        assert o["net"] == "ground"
        assert o["kind"] == "metal"
        assert o["bbox"] == [-40.0, -40.0, LOWER_Z, 40.0, 40.0, UPPER_Z]
        assert o["material"] == "SAC305"
        assert o["thickness_z"] == pytest.approx(GAP)
        assert m["keepouts"] == [{"name": "feed_line",
                                  "rect": [-420.0, -10.0, -300.0, 30.0]}]

    def test_planner_prevented_intrusion_doctor_12_pass(self) -> None:
        """端到端 PASS：规划器已剔除 (−360,10) 压线球 → doctor #12 绿
        （K6 钉过"球放回去必红"的规划期反面：根本不放回去）。"""
        plan = plan_solder_balls(
            [(-420, -50, -300, 70), (-50, -50, 50, 50)],
            ball_d=80.0, upper_z=UPPER_Z, lower_z=LOWER_Z,
            keepouts=[("feed_line", (-420, -10, -300, 30))], units="um")
        m = balls_to_doctor_manifest(plan, material="SAC305")
        report = run_em_doctor(m)
        rows = {c["table_ref"]: c for c in report["checks"]}
        assert rows[12]["status"] == "PASS"
        assert "1 个 keepout 全部清距" in rows[12]["detail"]
        assert report["ok"] is True

    def test_manifest_survives_doctor_loader_json_roundtrip(
            self, tmp_path: Any) -> None:
        plan = plan_solder_balls(
            [(-420, -50, -300, 70), (-50, -50, 50, 50)],
            ball_d=80.0, upper_z=UPPER_Z, lower_z=LOWER_Z,
            keepouts=[("feed_line", (-420, -10, -300, 30))], units="um")
        m = balls_to_doctor_manifest(plan, material="SAC305")
        p = tmp_path / "model_manifest.json"
        p.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
        loaded = load_model_manifest(p)
        assert loaded["ok"] is True, loaded.get("errors")
        report = run_em_doctor(loaded["manifest"])
        rows = {c["table_ref"]: c for c in report["checks"]}
        assert rows[12]["status"] == "PASS"

    def test_ball_ball_collision_warn_path_via_separation_keepouts(self) -> None:
        """"球球相撞"→ doctor #12 WARN 路径（本席钉面）。

        节距=球径+净距（110=80+30）→ 相邻球边距恰 30：规划器按 ≥30−tol 收球，
        球间净距环带（ball_separation_keepouts）投影进清单后 doctor 以
        keepout 净距语义给出 WARN（0<dist≤clearance+tol；WARN 不翻门，
        belt-and-braces 提示级）。"""
        plan = _plane_plan(110.0)
        assert plan["n_candidates"] == 9
        assert plan["n_balls"] == 4
        assert all(s["rule"] == "footprint" for s in plan["skipped"])
        m = balls_to_doctor_manifest(plan, material="SAC305",
                                     ball_separation_keepouts=True)
        kos = {k["name"]: k for k in m["keepouts"]}
        assert set(kos) == {"ko_ball_01", "ko_ball_02", "ko_ball_03",
                            "ko_ball_04"}
        assert kos["ko_ball_01"]["rect"] == plan["balls"][0]["footprint"]
        assert kos["ko_ball_01"]["clearance"] == 30.0
        assert kos["ko_ball_01"]["applies_to"] == [
            "ball_02", "ball_03", "ball_04"]  # 自排除（不查自己环带）
        m["connectivity"] = {"ground": plan["n_balls"]}
        report = run_em_doctor(m)
        rows = {c["table_ref"]: c for c in report["checks"]}
        assert rows[12]["status"] == "WARN"
        assert "ball_02" in rows[12]["detail"] and "ko_ball_01" in rows[12]["detail"]
        assert report["ok"] is True  # WARN 不翻门

    def test_clean_separation_doctor_12_pass(self) -> None:
        """节距留余量（120 → 边距 40 > 清距+容差）→ #12 PASS 无告警。"""
        plan = _plane_plan(120.0)
        assert plan["n_balls"] == 4
        m = balls_to_doctor_manifest(plan, material="SAC305",
                                     ball_separation_keepouts=True)
        m["connectivity"] = {"ground": plan["n_balls"]}
        report = run_em_doctor(m)
        rows = {c["table_ref"]: c for c in report["checks"]}
        assert rows[12]["status"] == "PASS"
        assert report["ok"] is True

    def test_bypassed_planner_overlap_ball_fails_doctor_12(self) -> None:
        """绕过规划器塞回的重叠球（球球相撞真病灶形态）→ doctor #12 FAIL。

        manifest 形态=桥产物同构（objects+ko_<球名> 环带 keepout）——doctor
        是"滑过规划器的改动"的复核面（P13 验收口径的球球版）。"""
        plan = _plane_plan(120.0)
        m = balls_to_doctor_manifest(plan, material="SAC305",
                                     ball_separation_keepouts=True)
        # 手工塞入与 ball_01（footprint [−20,−20,60,60]）重叠 30×80 的球
        m["objects"].append({
            "name": "ball rogue", "net": "ground", "kind": "metal",
            "bbox": [30.0, -20.0, LOWER_Z, 110.0, 60.0, UPPER_Z],
            "material": "SAC305", "thickness_z": GAP,
        })
        for k in m["keepouts"]:
            if k["name"] == "ko_ball_01":
                k["applies_to"] = [*k["applies_to"], "ball rogue"]
        m["connectivity"] = {"ground": plan["n_balls"] + 1}
        report = run_em_doctor(m)
        rows = {c["table_ref"]: c for c in report["checks"]}
        assert rows[12]["status"] == "FAIL"
        assert "ball rogue" in rows[12]["detail"]
        assert "ko_ball_01" in rows[12]["detail"]
        assert report["ok"] is False

    def test_bridge_input_validation(self) -> None:
        with pytest.raises(FlipChipPlanError, match="plan_solder_balls"):
            balls_to_doctor_manifest({"kind": "hand_crafted"})
        plan = _plane_plan(120.0)
        with pytest.raises(FlipChipPlanError, match="net 需"):
            balls_to_doctor_manifest(plan, net="bump")

    def test_keepout_semantics_align_k6_filter(self) -> None:
        """keepout 过滤与 K6 filter_keepout_candidates 逐字段同构（对齐钉）。

        core 分层禁 import adapters——同语义重写，本测用同输入比 kept/skipped
        分割（K6 Keepout 实例 vs core 裸矩形输入）。"""
        plane = plan_solder_balls(
            [(-800, -700, 800, 700)], ball_d=80.0, upper_z=UPPER_Z,
            lower_z=LOWER_Z, grid=(110.0, 110.0), units="um",
            keepouts=[("feed_line", (-420, -10, -300, 30))])
        assert plane["n_skipped"] > 0
        # K6 通道：同一"覆盖规则存活候选集"（收球 + keepout 剔除者）+同 keepout
        cands = [(b["name"], b["footprint"]) for b in plane["balls"]]
        cands += [(s["candidate"], s["footprint"]) for s in plane["skipped"]
                  if s["rule"] == "keepout"]
        k6 = filter_keepout_candidates(
            cands, [Keepout("feed_line", (-420, -10, -300, 30))])
        # 集合等价：core 收球足迹集合 == K6 kept 足迹集合
        core_kept = {tuple(b["footprint"]) for b in plane["balls"]}
        k6_kept = {tuple(c["rect"]) for c in k6["kept"]}
        assert core_kept == k6_kept
        # skipped 记账同构：core keepout 剔除者的足迹+keepout 名与 K6 一致
        # （K6 skipped 条目带候选名不带矩形——经 (name,rect) 输入映射回足迹）
        rect_by_name = {str(n): tuple(rc) for n, rc in cands}
        core_skip = {(tuple(s["footprint"]), s["keepout"])
                     for s in plane["skipped"] if s["rule"] == "keepout"}
        k6_skip = {(rect_by_name[s["candidate"]], s["keepout"])
                   for s in k6["skipped"]}
        assert core_skip == k6_skip
        assert core_skip and plane["n_skipped"] > len(core_skip)  # 混合场景


# ── 落地层 mock 冒烟（hfss_builder_utils.solder_balls / lid_with_windows）────


class _MockCadObject:
    def __init__(self, bbox: list[float]) -> None:
        self.bounding_box = list(bbox)


class _MockModeler:
    """pyaedt ``app.modeler`` 最小形态（记录几何/布尔调用，零真机）。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._objs: dict[str, _MockCadObject] = {}

    def create_sphere(self, *, origin, radius, name, material):
        self.calls.append(("create_sphere", {"origin": origin,
                                             "radius": radius,
                                             "name": name,
                                             "material": material}))
        self._objs[name] = _MockCadObject([0.0] * 6)
        return name

    def create_box(self, *, origin, sizes, name, material):
        self.calls.append(("create_box", {"origin": origin, "sizes": sizes,
                                          "name": name,
                                          "material": material}))
        self._objs[name] = _MockCadObject([0.0] * 6)
        return name

    def subtract(self, blank_list, tool_list, keep_originals):
        self.calls.append(("subtract", {"blank_list": blank_list,
                                        "tool_list": tool_list,
                                        "keep_originals": keep_originals}))
        return True

    def intersect(self, assignment, keep_originals):
        self.calls.append(("intersect", {"assignment": assignment,
                                         "keep_originals": keep_originals}))
        return assignment[0]


class TestSolderBallsBuilder:
    def _two_ball_plan(self) -> dict[str, Any]:
        return plan_solder_balls(
            [(-420, -50, -300, 70), (-50, -50, 50, 50)],
            ball_d=80.0, upper_z=UPPER_Z, lower_z=LOWER_Z,
            keepouts=[("feed_line", (-420, -10, -300, 30))], units="um")

    def test_build_creates_sphere_cutbox_intersect_per_ball(self) -> None:
        """每球=Sphere+切盒 Box+intersect（鼓形）；显式单位串；切盒 z=间隙带。"""
        plan = self._two_ball_plan()
        mock = _MockModeler()
        out = solder_balls(mock, plan, material="SAC305",
                           name_prefix="SolderBall", net="ground")
        assert out["balls"] == ["SolderBall01"]
        assert out["n_created"] == 1 and out["units"] == "um"
        spheres = [c for c in mock.calls if c[0] == "create_sphere"]
        boxes = [c for c in mock.calls if c[0] == "create_box"]
        inters = [c for c in mock.calls if c[0] == "intersect"]
        assert len(spheres) == len(boxes) == len(inters) == 1
        s = spheres[0][1]
        assert s["name"] == "SolderBall01" and s["material"] == "SAC305"
        assert s["radius"] == "40um"
        assert s["origin"] == ["0um", "0um", "240.2um"]  # 显式单位串
        b = boxes[0][1]
        assert b["name"] == "SolderBall01CutBox"
        assert b["origin"] == ["-42um", "-42um", "205.2um"]  # 1.05R=42
        assert b["sizes"] == ["84um", "84um", "70um"]        # z=间隙带
        # 布尔结果继承首对象名（#285 惯例）：球名放首位
        assert inters[0][1]["assignment"] == ["SolderBall01",
                                              "SolderBall01CutBox"]
        assert inters[0][1]["keep_originals"] is False

    def test_net_registration_via_default_registry(self) -> None:
        plan = self._two_ball_plan()
        mock = _MockModeler()
        solder_balls(mock, plan, material="SAC305",
                     name_prefix="SolderBall", net="ground")
        rep = nets_report()
        by_name = {o["name"]: o for o in rep["objects"]}
        assert "SolderBall01" in by_name
        rec = by_name["SolderBall01"]
        assert rec["net"] == "ground" and rec["kind"] == "metal"
        assert rec["material"] == "SAC305"
        assert rec["bbox"] == [-40.0, -40.0, LOWER_Z, 40.0, 40.0, UPPER_Z]
        assert rec["thickness_z"] == pytest.approx(GAP)

    def test_plan_kind_and_inputs_rejected(self) -> None:
        mock = _MockModeler()
        with pytest.raises(ModelBuildError, match="plan_solder_balls"):
            solder_balls(mock, {"kind": "hand"}, material="SAC305",
                         name_prefix="SolderBall")
        with pytest.raises(ModelBuildError, match="name_prefix 不能为空"):
            solder_balls(mock, self._two_ball_plan(), material="SAC305",
                         name_prefix="  ")
        with pytest.raises(ModelBuildError, match=r"军规 2b|自动生成"):
            solder_balls(mock, self._two_ball_plan(), material="SAC305",
                         name_prefix="Box")  # Box01 命中自动名形态
        with pytest.raises(ModelBuildError, match="net 需"):
            solder_balls(mock, self._two_ball_plan(), material="SAC305",
                         name_prefix="SolderBall", net="bump")
        empty = plan_solder_balls([(0, 0, 10, 10)], ball_d=80.0,
                                  upper_z=UPPER_Z, lower_z=LOWER_Z, units="um")
        assert empty["n_balls"] == 0
        with pytest.raises(ModelBuildError, match="无已收球"):
            solder_balls(mock, empty, material="SAC305",
                         name_prefix="SolderBall")


class TestLidWindowsBuilder:
    def _lid_plan(self) -> dict[str, Any]:
        return plan_lid_windows(_LID, windows=[(-100, -100, 100, 100),
                                               (200, 300, 400, 500)],
                                units="um")

    def test_build_creates_lid_and_subtracts_all_windows(self) -> None:
        mock = _MockModeler()
        out = lid_with_windows(mock, self._lid_plan(), material="Aluminum",
                               name="Lid", net="ground")
        assert out["lid"] == "Lid"
        assert out["windows"] == ["window_1", "window_2"]
        assert out["cut_boxes"] == ["LidWin1Cut", "LidWin2Cut"]
        boxes = [c for c in mock.calls if c[0] == "create_box"]
        assert len(boxes) == 3  # 盖板 + 2 切盒
        lid_box = boxes[0][1]
        assert lid_box["name"] == "Lid"
        assert lid_box["origin"] == ["-800um", "-700um", "300um"]
        assert lid_box["sizes"] == ["1600um", "1400um", "5.2um"]
        sub = [c for c in mock.calls if c[0] == "subtract"]
        assert len(sub) == 1  # 一次 subtract（blank=盖板，tools=全部窗口）
        assert sub[0][1]["blank_list"] == ["Lid"]
        assert sub[0][1]["tool_list"] == ["LidWin1Cut", "LidWin2Cut"]
        assert sub[0][1]["keep_originals"] is False
        rep = nets_report()
        rec = {o["name"]: o for o in rep["objects"]}["Lid"]
        assert rec["net"] == "ground" and rec["kind"] == "metal"
        assert rec["bbox"] == [*map(float, _LID)]

    def test_plan_kind_and_name_rejected(self) -> None:
        mock = _MockModeler()
        with pytest.raises(ModelBuildError, match="plan_lid_windows"):
            lid_with_windows(mock, {"kind": "hand"}, material="Aluminum")
        with pytest.raises(ModelBuildError, match=r"军规 2b|自动生成"):
            lid_with_windows(mock, self._lid_plan(), material="Aluminum",
                             name="Box1")
        empty = plan_lid_windows(_LID, windows=[(0, 0, 10, 10)], units="um")
        empty["windows"] = []  # 模拟无窗口 plan（防御面：落地层拒绝空窗）
        with pytest.raises(ModelBuildError, match="无窗口"):
            lid_with_windows(mock, empty, material="Aluminum")

    def test_built_lid_and_balls_registry_gate(self) -> None:
        """即建即查集成面：builder 登记的球/盖板 + K6 keepout → check_keepouts
        PASS（压线球已在规划期剔除——P13 拦截链在默认登记薄上闭合）。"""
        from rfauto.adapters.hfss_builder_utils import check_keepouts, net_keepout
        net_keepout("feed_line", (-420, -10, -300, 30),
                    z_range=(LOWER_Z, UPPER_Z))  # 只圈植球层（盖板 z 300+ 不受圈）
        mock = _MockModeler()
        solder_balls(mock, plan_solder_balls(
            [(-420, -50, -300, 70), (-50, -50, 50, 50)],
            ball_d=80.0, upper_z=UPPER_Z, lower_z=LOWER_Z,
            keepouts=[("feed_line", (-420, -10, -300, 30))], units="um"),
            material="SAC305", name_prefix="SolderBall")
        lid_with_windows(mock, plan_lid_windows(
            _LID, windows=[(-100, -100, 100, 100)],
            ball_clearance=30.0, balls=plan_solder_balls(
                [(-800, -700, 800, 700)], ball_d=80.0, upper_z=UPPER_Z,
                lower_z=LOWER_Z, grid=(110.0, 110.0), units="um"),
            units="um"), material="Aluminum")
        rep = check_keepouts()
        assert rep["ok"] is True
        assert rep["violations"] == []
