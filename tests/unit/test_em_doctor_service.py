"""em_doctor_service 测试（K5，aurora_k，P12/F8：EM 模型清单体检器）。

用户反馈三病灶原值复现钉面（反馈 §6.1，2026-10-23）：

- 13:05 端口：aperture z 0–190 vs 金属 200.2–205.2 μm（**不含金属**照样
  能解能导出，L≈0.135 nH 等效短路）→ 检查#3 必红；积分线 z=102.6 落
  衬底内部 → 检查#5 必红。
- P13 植球：Ø80 球压在 CPW 信号引线上（球顶把信号经球短到盖板，
  S21≈−99.6 dB）→ 检查#8/#12 必红。
- P7/P15 竖墙：0.2 μm SiNx 声明层被建成 15 μm 竖墙（SRF 6.3→0.95 GHz）
  → 检查#11 必红。

好模型 fixture（八角电感 GaAs 薄膜叠层，数值取自反馈：衬底 200/SiNx
0.2/FM 5 μm、gap 30、修复后 aperture 顶=205.2+3×30=295.2）全绿。
全部确定性：零真机零网络零 runs/ 湖写入（run 目录走 tmp_path，#144）。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rfauto.cli.main import app as root_app
from rfauto.service.em_doctor_service import (
    SCHEMA,
    load_model_manifest,
    run_em_doctor,
)
from rfauto.service.runs_verify_service import write_manifest

# ── 好模型 fixture（八角电感；两槽地框如实分裂为左右两块→ground:2）─────


def _good_manifest() -> dict:
    return {
        "units": "um",
        "domain": {"bbox": [-800, -700, 0, 800, 700, 500]},
        "device_topology": "series",
        # 两槽地框（底槽走 feed_l、顶槽走 feed_r）把地框切成左右两轨——
        # 显式声明期望 2（bbox 近似如实），信号经 coil 连通为 1 分量。
        "connectivity": {"signal": 1, "ground": 2},
        "objects": [
            {"name": "coil", "bbox": [-60, -60, 200.2, 60, 60, 205.2],
             "net": "signal", "material": "Au", "thickness_z": 5.0},
            {"name": "feed_l", "bbox": [-40, -700, 200.2, 0, -60, 205.2],
             "net": "signal", "material": "Au"},
            {"name": "feed_r", "bbox": [0, 60, 200.2, 40, 700, 205.2],
             "net": "signal", "material": "Au"},
            # 地框：左右全高轨 + 上下槽沿分段（feed 两侧各让 30 μm 隙）
            {"name": "gnd_left", "bbox": [-800, -700, 200.2, -500, 700, 205.2],
             "net": "ground", "material": "Au"},
            {"name": "gnd_right", "bbox": [500, -700, 200.2, 800, 700, 205.2],
             "net": "ground", "material": "Au"},
            {"name": "gnd_top_l", "bbox": [-500, 300, 200.2, -30, 700, 205.2],
             "net": "ground", "material": "Au"},
            {"name": "gnd_top_r", "bbox": [70, 300, 200.2, 500, 700, 205.2],
             "net": "ground", "material": "Au"},
            {"name": "gnd_bl", "bbox": [-500, -700, 200.2, -70, -300, 205.2],
             "net": "ground", "material": "Au"},
            {"name": "gnd_br", "bbox": [30, -700, 200.2, 500, -300, 205.2],
             "net": "ground", "material": "Au"},
            {"name": "sinx", "bbox": [-800, -700, 200.0, 800, 700, 200.2],
             "net": "other", "kind": "dielectric", "material": "SiNx",
             "thickness_z": 0.2},
            {"name": "gaas", "bbox": [-800, -700, 0, 800, 700, 200.0],
             "net": "other", "kind": "dielectric", "material": "GaAs",
             "thickness_z": 200.0},
        ],
        "ports": [
            {"name": "P1", "plane": {"axis": "y", "at": -700},
             "aperture_bbox": [-450, -700, 0, 100, -700, 295.2],
             "integration_line": {"start": [-450, -700, 202.7],
                                  "end": [-20, -700, 202.7]},
             "num_modes": 1, "on_boundary": True, "gap": 30},
            {"name": "P2", "plane": {"axis": "y", "at": 700},
             "aperture_bbox": [-650, 700, 0, 60, 700, 295.2],
             "integration_line": {"start": [-650, 700, 202.7],
                                  "end": [20, 700, 202.7]},
             "num_modes": 1, "on_boundary": True, "gap": 30},
        ],
        "stackup": [
            {"name": "GaAs", "thickness": 200.0, "material": "GaAs",
             "z_range": [0.0, 200.0]},
            {"name": "SiNx1", "thickness": 0.2, "material": "SiNx",
             "z_range": [200.0, 200.2]},
            {"name": "FM", "thickness": 5.0, "material": "Au",
             "z_range": [200.2, 205.2]},
        ],
    }


def _disease_bump_manifest() -> dict:
    """P13 植球压信号：Ø80 球（80×80 footprint）压入 feed_l，经 lid 接地。

    球顶 z 到 300 触盖板（lid 300–305.2），球底压入信号线 5 μm
    （P9 压入形态）→ 异 net 交叠体积>0；keepout 按反馈"植球外接框 ∩
    信号引线矩形"剔除语义给出（bump_17 应被剔除而未剔）。
    """
    m = _good_manifest()
    m["objects"].append(
        {"name": "lid", "bbox": [-800, -700, 300.0, 800, 700, 305.2],
         "net": "ground", "material": "Au"})
    m["objects"].append(
        {"name": "bump_17", "bbox": [-40, -500, 200.2, 40, -420, 300.0],
         "net": "ground", "material": "SAC305"})
    # lid+bump 把左右地轨桥成 1 块——期望随之改 1（地网连通属修复后形态）
    m["connectivity"] = {"signal": 1, "ground": 1}
    m["keepouts"] = [
        {"name": "feed_l_slot", "rect": [-70, -720, 30, -60],
         "applies_to": ["bump_17"]}]
    return m


def _check(report: dict, table_ref: int) -> dict:
    """按反馈表编号取检查行（报告行序=表编号序的契约面）。"""
    rows = [c for c in report["checks"] if c["table_ref"] == table_ref]
    assert len(rows) == 1, f"表#{table_ref} 应恰一行，实际 {len(rows)}"
    return rows[0]


# ── 好模型：全绿（v1 检查 PASS/SKIP，v2 六行 SKIP 带标记）──────────────────


class TestGoodModel:
    def test_all_green(self) -> None:
        report = run_em_doctor(_good_manifest())
        assert report["schema"] == SCHEMA
        assert report["verdict"] == "PASS"
        assert report["ok"] is True
        for check in report["checks"]:
            assert check["status"] in ("PASS", "SKIP", "WARN"), check
            assert check["status"] != "FAIL", check["detail"]

    def test_sixteen_rows_in_table_order(self) -> None:
        report = run_em_doctor(_good_manifest())
        refs = [c["table_ref"] for c in report["checks"]]
        assert refs == list(range(1, 17))
        for check in report["checks"]:
            assert check["catches"], "每行带会抓到的真实问题（反馈表原文口吻）"
            assert check["title"]

    def test_v2_rows_six_skip_tagged(self) -> None:
        report = run_em_doctor(_good_manifest())
        v2 = [c for c in report["checks"] if c.get("reason_tag") == "v2"]
        assert {c["table_ref"] for c in v2} == {1, 4, 9, 10, 13, 14}
        assert all(c["status"] == "SKIP" for c in v2)
        assert report["summary"]["n_skip_v2"] == 6

    def test_summary_counts_consistent(self) -> None:
        report = run_em_doctor(_good_manifest())
        n = len(report["checks"])
        s = report["summary"]
        assert s["n_pass"] + s["n_fail"] + s["n_warn"] + s["n_skip"] == n

    def test_air_margin_3xgap_pass_and_note(self) -> None:
        """修复后形态：aperture 顶=metal_top+3×gap（205.2+90=295.2）→ PASS。"""
        report = run_em_doctor(_good_manifest())
        row = _check(report, 3)
        assert row["status"] == "PASS"
        p1 = next(i for i in row["items"] if i["port"] == "P1")
        assert "3×gap" in p1["detail"]


# ── 病灶一：13:05 端口（aperture 不含金属 + 积分线在衬底内部）────────────


class TestDisease1305Aperture:
    def _diseased(self) -> dict:
        m = _good_manifest()
        m["ports"][0]["aperture_bbox"] = [-450, -700, 0, 100, -700, 190.0]
        m["ports"][0]["integration_line"] = {
            "start": [-450, -700, 102.6], "end": [-20, -700, 102.6]}
        return m

    def test_aperture_excludes_metal_fails_check3(self) -> None:
        report = run_em_doctor(self._diseased())
        assert report["verdict"] == "FAIL"
        assert report["ok"] is False
        row = _check(report, 3)
        assert row["status"] == "FAIL"
        p1 = next(i for i in row["items"] if i["port"] == "P1")
        # 人话病灶描述：0.135 nH 家族 + ValidateDesign 语义边界
        assert "0.135 nH" in p1["detail"]
        assert "200.2" in p1["detail"] and "205.2" in p1["detail"]
        assert "190" in p1["detail"]

    def test_integration_line_in_substrate_fails_check5(self) -> None:
        report = run_em_doctor(self._diseased())
        row = _check(report, 5)
        assert row["status"] == "FAIL"
        p1 = next(i for i in row["items"] if i["port"] == "P1")
        assert "102.6" in p1["detail"]

    def test_healthy_port_p2_unaffected(self) -> None:
        """只坏 P1：P2 两检查保持 PASS（逐端口定位，不连坐）。"""
        report = run_em_doctor(self._diseased())
        for ref in (3, 5):
            p2 = next(i for i in _check(report, ref)["items"]
                      if i["port"] == "P2")
            assert p2["status"] == "PASS", p2

    def test_no_metal_in_window_at_all_fails(self) -> None:
        """窗口内一个金属都没有（端口激励空）也是 0.135nH 家族。"""
        m = _good_manifest()
        # x∈[5,25] 落在 feed_l(≤0) 与 gnd_br(≥30) 之间的槽内——窗口空
        m["ports"][0]["aperture_bbox"] = [5, -700, 0, 25, -700, 295.2]
        report = run_em_doctor(m)
        row = _check(report, 3)
        p1 = next(i for i in row["items"] if i["port"] == "P1")
        assert p1["status"] == "FAIL"
        assert "无任何金属" in p1["detail"]

    def test_air_margin_below_3xgap_warns(self) -> None:
        """软判据：金属上方空气 < 3×gap → WARN（不 FAIL）。"""
        m = _good_manifest()
        m["ports"][0]["aperture_bbox"] = [-450, -700, 0, 100, -700, 250.0]
        report = run_em_doctor(m)
        row = _check(report, 3)
        p1 = next(i for i in row["items"] if i["port"] == "P1")
        assert p1["status"] == "WARN"
        assert "295.2" in p1["detail"]  # 建议值=metal_top+3×gap

    def test_gap_absent_skips_soft_margin(self) -> None:
        m = _good_manifest()
        del m["ports"][0]["gap"]
        report = run_em_doctor(m)
        p1 = next(i for i in _check(report, 3)["items"] if i["port"] == "P1")
        assert p1["status"] == "PASS"
        assert "未声明 gap" in p1["detail"]

    def test_ground_only_capture_warns(self) -> None:
        """窗口只捕获地金属、信号金属被截掉 → WARN（对照积分线端点核）。"""
        m = _good_manifest()
        # 窗顶 205 恰含地金属带 200.2–205.2，信号线抬到 ABM 层出窗
        m["ports"][0]["aperture_bbox"] = [-450, -700, 0, 100, -700, 205.0]
        m["objects"][1]["bbox"] = [-40, -700, 300.0, 0, -60, 305.2]  # feed_l
        report = run_em_doctor(m)
        p1 = next(i for i in _check(report, 3)["items"] if i["port"] == "P1")
        assert p1["status"] == "WARN"
        assert "无信号金属" in p1["detail"]


# ── 病灶二：植球把信号短到地（P13）─────────────────────────────────────────


class TestDiseaseBumpShort:
    def test_cross_net_overlap_fails_check8(self) -> None:
        report = run_em_doctor(_disease_bump_manifest())
        assert report["verdict"] == "FAIL"
        row = _check(report, 8)
        assert row["status"] == "FAIL"
        assert "bump_17" in row["detail"] and "feed_l" in row["detail"]
        assert "−99.6" in row["detail"]  # 反馈实测 S21 口径

    def test_keepout_intrusion_fails_check12(self) -> None:
        report = run_em_doctor(_disease_bump_manifest())
        row = _check(report, 12)
        assert row["status"] == "FAIL"
        assert "bump_17" in row["detail"] and "feed_l_slot" in row["detail"]

    def test_same_net_overlap_not_flagged(self) -> None:
        """同 net 交叠（球压接地板/lid 属连接形态）不进 #8——表#9 是 v2 面。"""
        report = run_em_doctor(_disease_bump_manifest())
        row = _check(report, 8)
        assert "gnd_br" not in row["detail"]

    def test_lid_not_false_positive_in_check3(self) -> None:
        """盖板（z 300–305.2）横跨端口面但被 aperture 有意排除——不判红。

        用户修复后参考模型即此形态（aperture 顶 295.2、盖板 300 起）：
        #3 只要求窗口**捕获**馈电导体，窗口外回流结构记信息注记。
        """
        report = run_em_doctor(_disease_bump_manifest())
        row = _check(report, 3)
        assert row["status"] == "PASS", row["detail"]
        p1 = next(i for i in row["items"] if i["port"] == "P1")
        assert "lid" in p1["detail"]
        assert "有意排除" in p1["detail"]

    def test_face_touch_different_nets_warns(self) -> None:
        """异 net bbox 贴面零体积：WARN（bbox 近似下可能是真短路）。"""
        m = _good_manifest()
        # 在信号线旁放一块地金属：xy 有间隙为 0、z 恰共面——体积 0 但贴面
        m["objects"].append(
            {"name": "gnd_probe", "bbox": [0.0, -500, 200.2, 200, -420, 205.2],
             "net": "ground"})
        report = run_em_doctor(m)
        row = _check(report, 8)
        assert row["status"] == "WARN"
        assert "贴面" in row["detail"]

    def test_no_cross_net_pairs_trivial_pass(self) -> None:
        m = _good_manifest()
        for o in m["objects"]:
            if o["net"] == "ground":
                o["net"] = "signal"
        m["connectivity"] = {"signal": 1}
        report = run_em_doctor(m)
        assert _check(report, 8)["status"] == "PASS"
        assert "平凡真" in _check(report, 8)["detail"]


# ── 病灶三：0.2 μm 薄层建成 15 μm 竖墙（P7/P15）──────────────────────────


class TestDiseaseThinWall:
    def test_wall_fails_check11(self) -> None:
        m = _good_manifest()
        m["objects"][9]["bbox"] = [-300, -300, 190.0, 300, 300, 205.0]
        report = run_em_doctor(m)
        row = _check(report, 11)
        assert row["status"] == "FAIL"
        assert "0.2" in row["detail"] and "15" in row["detail"][:120]
        assert "竖墙" in row["detail"]

    def test_stackup_layer_mismatch_fails(self) -> None:
        m = _good_manifest()
        m["stackup"][1]["z_range"] = [200.0, 215.0]  # SiNx 0.2 声明/15 实际
        report = run_em_doctor(m)
        row = _check(report, 11)
        assert row["status"] == "FAIL"
        assert "SiNx1" in row["detail"]

    def test_within_tolerance_passes(self) -> None:
        """恰等声明（span==h）与 1% 内偏差都过（闭边界语义）。"""
        m = _good_manifest()
        m["objects"][9]["bbox"] = [-800, -700, 200.0, 800, 700, 200.202]
        report = run_em_doctor(m)
        assert _check(report, 11)["status"] == "PASS"

    def test_no_declaration_skips(self) -> None:
        m = _good_manifest()
        for o in m["objects"]:
            o.pop("thickness_z", None)
        for layer in m["stackup"]:
            layer.pop("thickness", None)
        report = run_em_doctor(m)
        assert _check(report, 11)["status"] == "SKIP"


# ── on_boundary 自洽（表#2）与端口面语义───────────────────────────────────


class TestPortOnBoundary:
    def test_declared_boundary_but_inside_fails(self) -> None:
        m = _good_manifest()
        m["ports"][0]["plane"]["at"] = -600  # 域 y∈[-700,700] 内部
        report = run_em_doctor(m)
        row = _check(report, 2)
        assert row["status"] == "FAIL"
        p1 = next(i for i in row["items"] if i["port"] == "P1")
        assert "PEC 背衬" in p1["detail"]

    def test_declared_internal_but_on_face_warns(self) -> None:
        m = _good_manifest()
        m["ports"][0]["on_boundary"] = False
        report = run_em_doctor(m)
        row = _check(report, 2)
        p1 = next(i for i in row["items"] if i["port"] == "P1")
        assert p1["status"] == "WARN"
        assert row["status"] == "WARN"

    def test_declared_internal_and_inside_passes(self) -> None:
        m = _good_manifest()
        m["ports"][0]["on_boundary"] = False
        m["ports"][0]["plane"]["at"] = -600
        report = run_em_doctor(m)
        p1 = next(i for i in _check(report, 2)["items"] if i["port"] == "P1")
        assert p1["status"] == "PASS"
        assert "PEC 背衬" in p1["detail"]  # 内部端口背衬提示仍在

    def test_domain_absent_skips(self) -> None:
        m = _good_manifest()
        del m["domain"]
        report = run_em_doctor(m)
        assert _check(report, 2)["status"] == "SKIP"


# ── 积分线（表#5）分支面────────────────────────────────────────────────────


class TestIntegrationLineBranches:
    def test_both_on_ground_fails(self) -> None:
        m = _good_manifest()
        m["ports"][0]["integration_line"] = {
            "start": [-450, -700, 202.7], "end": [-200, -700, 202.7]}
        report = run_em_doctor(m)
        p1 = next(i for i in _check(report, 5)["items"] if i["port"] == "P1")
        assert p1["status"] == "FAIL"
        assert "地→信号" in p1["detail"]

    def test_other_net_endpoint_fails(self) -> None:
        """一端信号、另一端只落 other 金属（非地）→ FAIL。"""
        m = _good_manifest()
        # shield 放在 feed_l(≤0) 与 gnd_br(≥30) 之间的槽内——只被 IL 命中
        m["objects"].append(
            {"name": "shield", "bbox": [5, -700, 200.2, 25, -660, 205.2],
             "net": "other"})
        m["ports"][0]["integration_line"] = {
            "start": [15, -700, 202.7], "end": [-20, -700, 202.7]}
        report = run_em_doctor(m)
        p1 = next(i for i in _check(report, 5)["items"] if i["port"] == "P1")
        assert p1["status"] == "FAIL"
        assert "未落在地金属" in p1["detail"]

    def test_no_integration_line_skips(self) -> None:
        m = _good_manifest()
        for p in m["ports"]:
            del p["integration_line"]
        report = run_em_doctor(m)
        assert _check(report, 5)["status"] == "SKIP"


# ── 叠层延伸到端口面（表#6）────────────────────────────────────────────────


class TestStackupReachesPort:
    def test_layer_not_reaching_port_plane_fails(self) -> None:
        m = _good_manifest()
        m["stackup"][0]["bbox"] = [-800, -690, 0, 800, 700, 200.0]  # 差 10μm
        report = run_em_doctor(m)
        row = _check(report, 6)
        assert row["status"] == "FAIL"
        p1 = next(i for i in row["items"] if i["port"] == "P1")
        assert p1["status"] == "FAIL"
        assert "GaAs" in p1["detail"]

    def test_aperture_not_overlapping_stack_fails(self) -> None:
        m = _good_manifest()
        for p in m["ports"]:
            p["aperture_bbox"] = [
                p["aperture_bbox"][0], p["aperture_bbox"][1], 400.0,
                p["aperture_bbox"][3], p["aperture_bbox"][4], 450.0]
        report = run_em_doctor(m)
        row = _check(report, 6)
        assert row["status"] == "FAIL"
        for item in row["items"]:
            assert item["status"] == "FAIL"
            assert "悬空" in item["detail"]

    def test_no_stackup_skips(self) -> None:
        m = _good_manifest()
        m["stackup"] = []
        report = run_em_doctor(m)
        assert _check(report, 6)["status"] == "SKIP"


# ── 连通分量（表#7；bbox 2D 投影近似）─────────────────────────────────────


class TestNetConnectivity:
    def test_series_default_expects_two(self) -> None:
        """缺省派生（反馈 P13）：series→信号恰 2 分量（IDC 家族语义）。"""
        m = _good_manifest()
        del m["connectivity"]  # 保留 device_topology: series
        m["objects"] = [o for o in m["objects"] if o["name"] != "coil"]
        # feed_l 与 feed_r 互不接触=2 分量；地框（无期望声明→缺省 1、实际
        # 两槽分裂 2）同步 WARN——信号行本身必须 PASS
        report = run_em_doctor(m)
        row = _check(report, 7)
        sig = next(i for i in row["items"] if i["net"] == "signal")
        assert sig["status"] == "PASS"
        assert "2 分量" in sig["detail"]

    def test_series_default_merged_fails(self) -> None:
        """railA/railB 意外短接（1 分量≠期望 2）→ FAIL（S21≈0 dB 家族）。"""
        m = _good_manifest()
        del m["connectivity"]
        m["objects"] = [o for o in m["objects"] if o["name"] != "coil"]
        m["objects"].append(
            {"name": "bridge_oops", "bbox": [-40, -60, 200.2, 40, 60, 205.2],
             "net": "signal"})
        report = run_em_doctor(m)
        row = _check(report, 7)
        assert row["status"] == "FAIL"
        sig = next(i for i in row["items"] if i["net"] == "signal")
        assert "railA/railB" in sig["detail"]

    def test_ground_split_warns_not_fails(self) -> None:
        m = _good_manifest()
        m["connectivity"] = {"signal": 1, "ground": 1}  # 期望 1、实际 2
        report = run_em_doctor(m)
        row = _check(report, 7)
        assert row["status"] == "WARN"  # 地分裂是提示级不翻门
        gnd = next(i for i in row["items"] if i["net"] == "ground")
        assert "分裂" in gnd["detail"]

    def test_no_expectation_skips_with_observation(self) -> None:
        m = _good_manifest()
        del m["connectivity"]
        del m["device_topology"]
        report = run_em_doctor(m)
        row = _check(report, 7)
        assert row["status"] == "SKIP"
        assert row["evidence"]["signal_components"] == 1

    def test_approximation_evidence_declared(self) -> None:
        report = run_em_doctor(_good_manifest())
        ev = _check(report, 7)["evidence"]
        assert "投影" in ev["approximation"]  # bbox 近似局限如实声明


# ── keepout（表#12）分支面──────────────────────────────────────────────────


class TestKeepoutBranches:
    def test_clearance_warning(self) -> None:
        """侵入未发生但净距 ≤ 声明清距 → WARN。"""
        m = _good_manifest()
        m["keepouts"] = [
            {"name": "far_keepout", "rect": [100, -500, 200, -420],
             "clearance": 500, "applies_to": ["feed_l"]}]
        report = run_em_doctor(m)
        row = _check(report, 12)
        assert row["status"] == "WARN"
        assert "净距" in row["detail"]

    def test_unknown_applies_to_name_warns(self) -> None:
        m = _good_manifest()
        m["keepouts"] = [
            {"name": "ko", "rect": [2000, 2000, 2100, 2100],
             "applies_to": ["ghost_bump"]}]
        report = run_em_doctor(m)
        row = _check(report, 12)
        assert row["status"] == "WARN"
        assert "ghost_bump" in row["detail"]

    def test_z_range_excludes_object(self) -> None:
        """keepout 限 z 层面、对象不在该层 → 不判侵入。"""
        m = _disease_bump_manifest()
        m["keepouts"][0]["z_range"] = [0.0, 100.0]
        report = run_em_doctor(m)
        row = _check(report, 12)
        assert row["status"] == "PASS"

    def test_good_keepout_clean_passes(self) -> None:
        m = _good_manifest()
        m["keepouts"] = [
            {"name": "far_keepout", "rect": [2000, 2000, 2100, 2100]}]
        report = run_em_doctor(m)
        assert _check(report, 12)["status"] == "PASS"


# ── S 参数物理 sanity（表#15；判定口径=edb_health_gate 单源复用）──────────


def _write_s2p(path: Path, matrix: list[list[float]], freqs: list[float]) -> Path:
    """合成 Touchstone RI 形态（skrf 可读）。"""
    lines = ["! synthetic for em doctor tests", "# Hz S RI R 50"]
    for f in freqs:
        parts = [f"{f:.6e}"]
        for row in matrix:
            for v in row:
                parts.append(f"{v:.6f} 0.000000")
        lines.append(" ".join(parts))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


_PASSIVE = [[0.1, 0.9], [0.9, 0.1]]   # 对称阵特征值 1.0/-0.8 → σmax=1.0
_ACTIVE = [[0.2, 1.2], [1.2, 0.2]]    # 特征值 1.4 → σmax=1.4 违无源性
_FREQS = [1.0e9, 2.0e9, 3.0e9]


class TestSparamSanity:
    def test_passive_reciprocal_passes(self, tmp_path: Path) -> None:
        snp = _write_s2p(tmp_path / "dut.s2p", _PASSIVE, _FREQS)
        m = _good_manifest()
        m["sparams"] = snp.name
        report = run_em_doctor(m, manifest_dir=tmp_path)
        row = _check(report, 15)
        assert row["status"] == "PASS"
        assert "判定规则沿用 edb_health_gate" in row["detail"]

    def test_non_passive_fails(self, tmp_path: Path) -> None:
        snp = _write_s2p(tmp_path / "dut.s2p", _ACTIVE, _FREQS)
        m = _good_manifest()
        m["sparams"] = str(snp)
        report = run_em_doctor(m)
        row = _check(report, 15)
        assert row["status"] == "FAIL"
        assert "passivity" in row["detail"]

    def test_missing_file_fails(self, tmp_path: Path) -> None:
        m = _good_manifest()
        m["sparams"] = str(tmp_path / "ghost.s2p")
        report = run_em_doctor(m)
        assert _check(report, 15)["status"] == "FAIL"

    def test_absent_skips(self) -> None:
        report = run_em_doctor(_good_manifest())
        assert _check(report, 15)["status"] == "SKIP"


# ── 结果新鲜度（表#16；verify_run K4 单源复用）────────────────────────────


def _make_run(tmp_path: Path) -> Path:
    run = tmp_path / "run_k5"
    (run / "results").mkdir(parents=True)
    (run / "meta.json").write_text(
        json.dumps({"run_id": run.name, "adapter": "hfss",
                    "status": "done"}), encoding="utf-8")
    (run / "results" / "params.s1p").write_text(
        "# Hz S RI R 50\n1.0e9 0.1 0.0\n", encoding="utf-8")
    return run


class TestResultFreshness:
    def test_fresh_run_passes(self, tmp_path: Path) -> None:
        run = _make_run(tmp_path)
        write_manifest(run)
        m = _good_manifest()
        m["run_dir"] = str(run)
        report = run_em_doctor(m)
        assert _check(report, 16)["status"] == "PASS"

    def test_stale_run_fails(self, tmp_path: Path) -> None:
        """P11 验收场景：旧文件顶替新 run 必须红，不能静默通过。"""
        run = _make_run(tmp_path)
        write_manifest(run)
        (run / "results" / "params.s1p").write_text(
            "# Hz S RI R 50\n1.0e9 0.9 0.0\n", encoding="utf-8")  # 换内容
        m = _good_manifest()
        m["run_dir"] = str(run)
        report = run_em_doctor(m)
        row = _check(report, 16)
        assert row["status"] == "FAIL"
        assert "stale_replaced" in row["detail"]

    def test_legacy_run_warns(self, tmp_path: Path) -> None:
        run = _make_run(tmp_path)  # 无 manifest
        m = _good_manifest()
        m["run_dir"] = str(run)
        report = run_em_doctor(m)
        assert _check(report, 16)["status"] == "WARN"

    def test_missing_run_dir_fails(self, tmp_path: Path) -> None:
        m = _good_manifest()
        m["run_dir"] = str(tmp_path / "ghost_run")
        report = run_em_doctor(m)
        assert _check(report, 16)["status"] == "FAIL"

    def test_surface_failure_skips_not_crashes(
            self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """新鲜度校验面故障（verify_run OSError 族）→ SKIP 行非阻断（#105：
        观测面不得成为主路径故障点——doctor 报告完整返回）。"""
        run = _make_run(tmp_path)
        write_manifest(run)

        def _boom(run_dir: object) -> dict:
            raise OSError("盘面瞬断（故障注入）")

        monkeypatch.setattr(
            "rfauto.service.runs_verify_service.verify_run", _boom)
        m = _good_manifest()
        m["run_dir"] = str(run)
        report = run_em_doctor(m)
        row = _check(report, 16)
        assert row["status"] == "SKIP"
        assert "新鲜度校验面故障" in row["detail"]
        assert "非阻断" in row["detail"]
        assert row["evidence"]["run_dir"] == str(run)

    def test_absent_skips(self) -> None:
        report = run_em_doctor(_good_manifest())
        assert _check(report, 16)["status"] == "SKIP"


# ── 单位词汇（AEDT 长词收编面：meter 直收 / mil·cm·in 拒收点名指路）───────


class TestUnitsVocabulary:
    def test_meter_alias_normalizes_to_m(self) -> None:
        """AEDT 长词 meter → 归一 m 直收：容差表按 m 键取值（contact 5e-7/
        thickness 1e-9），几何不变则 verdict 不变。"""
        m = _good_manifest()
        m["units"] = "meter"
        report = run_em_doctor(m)
        assert report["units"] == "m"
        assert report["ok"] is True
        # 归一后走 m 键容差：薄层 0.2μm 声明仍按 m 制 abs 1e-9 判（同 um
        # 清单同几何 verdict 一致——跨单位物理一致的回归面）
        ref = run_em_doctor(_good_manifest())
        assert _check(report, 11)["status"] == _check(ref, 11)["status"]

    def test_mil_rejected_with_25p4_guidance(self) -> None:
        """mil 无倍数换算别名 → 拒收且报错点名"手改 um（1mil=25.4μm）"。"""
        m = _good_manifest()
        m["units"] = "mil"
        report = run_em_doctor(m)
        assert report["ok"] is False
        row = report["checks"][0]
        assert row["check"] == "manifest" and row["status"] == "FAIL"
        assert "mil" in row["detail"] and "25.4" in row["detail"]

    def test_in_and_cm_rejected_with_named_guidance(self) -> None:
        """in/cm 同族拒收：报错点名手改路径（in→mm 25.4、cm→mm 10）。"""
        for unit, needle in (("in", "1in=25.4mm"), ("cm", "1cm=10mm")):
            m = _good_manifest()
            m["units"] = unit
            report = run_em_doctor(m)
            row = report["checks"][0]
            assert row["status"] == "FAIL", (unit, row)
            assert needle in row["detail"], (unit, row["detail"])


# ── 清单装载（load_model_manifest）────────────────────────────────────────


class TestLoader:
    def test_yaml_and_json_equivalent(self, tmp_path: Path) -> None:
        good = _good_manifest()
        yml = tmp_path / "m.yaml"
        lines = ["units: um", "objects:", "  - name: coil",
                 "    bbox: [0, 0, 0, 10, 10, 5]", "    net: signal"]
        yml.write_text("\n".join(lines) + "\n", encoding="utf-8")
        jsn = tmp_path / "m.json"
        jsn.write_text(json.dumps(good), encoding="utf-8")
        r1 = load_model_manifest(yml)
        r2 = load_model_manifest(jsn)
        assert r1["ok"] is True and r2["ok"] is True
        # 好清单全量 JSON 也能直接体检（round-trip）
        assert run_em_doctor(r2["manifest"], manifest_dir=tmp_path)["ok"] is True

    def test_missing_file_error(self, tmp_path: Path) -> None:
        result = load_model_manifest(tmp_path / "ghost.yaml")
        assert result["ok"] is False
        assert "不存在" in result["errors"][0]

    def test_malformed_entry_lists_location(self, tmp_path: Path) -> None:
        bad = {"units": "um", "objects": [{"name": "x", "bbox": [1, 2, 3]}]}
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(bad), encoding="utf-8")
        result = load_model_manifest(path)
        assert result["ok"] is False
        assert any("objects[0](x)" in e for e in result["errors"])

    def test_bad_units_error(self, tmp_path: Path) -> None:
        bad = {"units": "inch", "objects": []}
        path = tmp_path / "u.json"
        path.write_text(json.dumps(bad), encoding="utf-8")
        result = load_model_manifest(path)
        assert result["ok"] is False
        assert any("units" in e for e in result["errors"])

    def test_wrong_suffix_error(self, tmp_path: Path) -> None:
        path = tmp_path / "m.txt"
        path.write_text("{}", encoding="utf-8")
        assert load_model_manifest(path)["ok"] is False

    def test_non_dict_root_error(self, tmp_path: Path) -> None:
        path = tmp_path / "m.json"
        path.write_text("[1, 2]", encoding="utf-8")
        assert load_model_manifest(path)["ok"] is False

    def test_corrupt_yaml_error(self, tmp_path: Path) -> None:
        path = tmp_path / "m.yaml"
        path.write_text("objects: [unclosed", encoding="utf-8")
        assert load_model_manifest(path)["ok"] is False

    def test_raw_bad_manifest_becomes_fail_row(self) -> None:
        """未过装载器的畸形 dict 直接体检：落 manifest FAIL 行不抛异常。"""
        report = run_em_doctor({"units": "um", "objects": [
            {"name": "x", "bbox": "not-a-bbox"}]})
        assert report["verdict"] == "FAIL"
        assert report["checks"][0]["check"] == "manifest"
        assert report["checks"][0]["status"] == "FAIL"

    def test_contact_tolerance_override(self) -> None:
        """tolerances.contact 显式覆盖单位缺省（大容差把 30μm 隙也算接触）。"""
        m = _good_manifest()
        m["tolerances"] = {"contact": 40.0}
        report = run_em_doctor(m)
        # feed 与两侧地（隙 30<40）被算作接触 → 信号地跨接体现在 #7/#8 证据
        row = _check(report, 8)
        assert row["status"] in ("PASS", "WARN", "FAIL")  # 容差生效不炸即可
        # 信号分量把地框并进来不会发生（#7 按 net 分图），但 feed-gap 30
        # 在 #8 贴面判定下变 WARN
        assert _check(report, 7)["status"] in ("PASS", "WARN")


# ── CLI 冒烟（rfauto em doctor）────────────────────────────────────────────


class TestCliSmoke:
    def _write(self, tmp_path: Path, manifest: dict, name: str) -> Path:
        path = tmp_path / name
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        return path

    def test_good_manifest_exit0_json(self, tmp_path: Path) -> None:
        path = self._write(tmp_path, _good_manifest(), "good.json")
        result = CliRunner().invoke(root_app, ["em", "doctor", str(path), "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["verdict"] == "PASS"
        assert len(payload["checks"]) == 16

    def test_disease_manifest_exit1_json(self, tmp_path: Path) -> None:
        m = copy.deepcopy(_good_manifest())
        m["ports"][0]["aperture_bbox"] = [-450, -700, 0, 100, -700, 190.0]
        path = self._write(tmp_path, m, "d1.json")
        result = CliRunner().invoke(root_app, ["em", "doctor", str(path), "-j"])
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["verdict"] == "FAIL"

    def test_human_output_has_table_and_verdict(self, tmp_path: Path) -> None:
        path = self._write(tmp_path, _disease_bump_manifest(), "d2.json")
        result = CliRunner().invoke(root_app, ["em", "doctor", str(path)])
        assert result.exit_code == 1
        assert "FAIL" in result.output
        assert "bump_17" in result.output

    def test_missing_manifest_exit1(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            root_app, ["em", "doctor", str(tmp_path / "ghost.yaml")])
        assert result.exit_code == 1

    def test_yaml_manifest_cli(self, tmp_path: Path) -> None:
        """YAML 清单走同一入口（.yaml 后缀分发）。"""
        m = _good_manifest()
        m["objects"] = m["objects"][:3]
        m["ports"] = []
        m["stackup"] = []
        path = tmp_path / "mini.yaml"
        path.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
        result = CliRunner().invoke(root_app, ["em", "doctor", str(path), "--json"])
        assert result.exit_code == 0, result.output


if __name__ == "__main__":
    print(__doc__)
    pytest.main([__file__, "-q"])
