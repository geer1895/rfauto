"""方向 2 模板库测试：geometry_spec / render_script 新模板覆盖。

验收口径：>=6 模板且 models list 可见；每模板 geometry_spec 返回有效结构。
"""

from __future__ import annotations

import pytest

from rfauto.adapters.openems_templates import geometry_spec, render_script

ALL_TEMPLATES = ["wilkinson", "patch", "branchline", "dipole", "stepped_impedance", "coupled_line"]


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield


class TestGeometrySpec:
    @pytest.mark.parametrize("template", ALL_TEMPLATES)
    def test_returns_valid_structure(self, template):
        params = _default_params(template)
        spec = geometry_spec(template, params)
        assert spec["template"] == template
        assert "boxes" in spec
        assert "ports" in spec
        assert "substrate" in spec
        assert len(spec["boxes"]) >= 3  # substrate + ground + at least 1 trace
        assert len(spec["ports"]) >= 1

    def test_wilkinson_box_count(self):
        spec = geometry_spec("wilkinson", {"series_w_mm": 1.113, "shunt_w_mm": 0.604, "arm_len_mm": 18.1})
        # substrate + ground + feed_in + T + 2 arms + 2 feed_out = 8
        assert len(spec["boxes"]) == 8

    def test_wilkinson_param_semantics_aligned_with_recipe(self):
        """语义统一回归（2026-09-04）：series_w_mm=λ/4 臂（窄）、
        shunt_w_mm=50Ω 馈线（宽），与 recipe/HFSS/fake 三方口径一致。
        旧语义反渲染会把同一配方画成 120Ω 馈线的病态结构。"""
        s = render_script(
            "wilkinson",
            {"series_w_mm": 0.33, "shunt_w_mm": 1.10, "arm_len_mm": 20.5},
            (1.5, 3.5),
        )
        assert "W_IN = 1.1 * 1e-3" in s
        assert "W_ARM = 0.33 * 1e-3" in s

    def test_wilkinson_s23_dual_excitation_block(self):
        """3 端口模板生成 S23 双激励后处理（e3_ 副本端口 + 第二 FDTD run）。
        注：该块在共享头部，2 端口模板也含此文本但惰性（_port3 未定义 →
        NameError 被 except 吞掉 → 5 列 CSV）。"""
        s = render_script(
            "wilkinson",
            {"series_w_mm": 0.33, "shunt_w_mm": 1.10, "arm_len_mm": 20.5},
            (1.5, 3.5),
        )
        assert "PortNamePrefix=\"e3_\"" in s
        assert "re_S23" in s

    def test_wilkinson_topology_correct(self):
        # 多模态审计回归（A0）：旧版是共线断口直通线（无分叉/无电阻/单输出）。
        # 正确拓扑必须有：T 型分叉、x 向并列双臂、3 端口、100Ω 隔离电阻。
        spec = geometry_spec("wilkinson", {"series_w_mm": 1.113, "shunt_w_mm": 0.604, "arm_len_mm": 18.1})
        names = [b["name"] for b in spec["boxes"]]
        assert "t_junction" in names
        assert "arm_left" in names and "arm_right" in names
        assert len(spec["ports"]) == 3
        res = spec["elements"][0]
        assert res["kind"] == "lumped_r" and res["r_ohm"] == 100.0

    def test_patch_official_lumped_feed(self):
        # 回归（第四轮馈电修正，2026-09-05）：对照官方 Simple Patch
        # Antenna——patch_len（谐振 λ/2）沿 x 轴；馈电 = LumpedPort 底探针
        # （0.2×2mm 盒、z 跨基板、x=-feed_offset）。历史：①更早"零宽探针
        # 不耦合（|S11|≡1）"是激励体积坍缩（盒未进网格，铁律 #3），非引擎
        # 缺陷；②微带边缘馈冒烟病态（端口面悬空离 PML λ0/4 + 馈点 x=0 是
        # patch_len 谐振模场节点）——谷位 3.08GHz、s11@2.4=+0.4dB 非物理。
        spec = geometry_spec("patch", {"patch_len_mm": 34.9, "patch_w_mm": 50.0,
                                       "feed_offset_mm": 7.8})
        patch = next(b for b in spec["boxes"] if b["name"] == "patch")
        dx = patch["stop_mm"][0] - patch["start_mm"][0]
        dy = patch["stop_mm"][1] - patch["start_mm"][1]
        assert dx == pytest.approx(34.9)  # 谐振轴
        assert dy == pytest.approx(50.0)
        probe = next(b for b in spec["boxes"] if b["name"] == "feed_probe")
        assert probe["start_mm"][0] == pytest.approx(-7.9)
        assert probe["stop_mm"][0] == pytest.approx(-7.7)
        assert probe["stop_mm"][1] - probe["start_mm"][1] == pytest.approx(2.0)
        assert probe["start_mm"][2] == pytest.approx(0.0)
        assert probe["stop_mm"][2] > 0  # z 跨基板
        el = spec["elements"][0]
        assert el["kind"] == "lumped_port" and el["r_ohm"] == 50.0
        assert spec["ports"][0]["pos_mm"][0] == pytest.approx(-7.8)
        s = render_script("patch", {"patch_len_mm": 40.0, "patch_w_mm": 50.0,
                                    "feed_offset_mm": 7.8}, (1.5, 3.5))
        assert "patch.AddBox" in s
        assert "LumpedPort(CSX, port_nr=1, R=50.0" in s
        assert "FEED_X = -7.8 * 1e-3" in s  # 官方口径 x=-feed_offset
        # 无边界端口 → 侧界全 MUR（官方辐射口径，z 底 PEC 当地面）
        assert 'SetBoundaryCond(["MUR", "MUR", "MUR", "MUR", "PEC", "MUR"])' in s
        assert "_near_x = [" in s and "_near_y = [" in s

    def test_patch_feed_box_edges_in_mesh_points(self):
        # 铁律 #3（激励盒必须与网格线对齐）：馈盒四条边必须出现在近场网格
        # 点里，否则激励体积坍缩为零 → |S11|≡1（零宽探针失败根因）
        from rfauto.adapters.openems_templates import _near_points

        nx, ny = _near_points("patch", {"patch_len_mm": 40.0,
                                        "patch_w_mm": 50.0,
                                        "feed_offset_mm": 7.8})
        for target in (-0.0079, -0.0077):  # x 向盒边（FEED_X±0.1mm）
            assert any(abs(v - target) < 1e-9 for v in nx), (target, nx)
        for target in (-0.001, 0.001):     # y 向盒边（±1mm 宽）
            assert any(abs(v - target) < 1e-12 for v in ny), (target, ny)

    def test_branchline_box_count(self):
        spec = geometry_spec("branchline", {"arm_len_mm": 20.5, "series_w_mm": 1.87, "shunt_w_mm": 1.11})
        # substrate + ground + 4 arms + 4 feeds = 10（2026-09-05 角馈重构：
        # 四角 50Ω 馈线，port4=隔离端 PML 端接）
        assert len(spec["boxes"]) == 10

    def test_dipole_box_count(self):
        spec = geometry_spec("dipole", {"dipole_len_mm": 58.0, "dipole_w_mm": 2.0, "gap_mm": 2.0})
        # substrate + ground + 2 arms + feed = 5
        assert len(spec["boxes"]) == 5

    def test_stepped_box_count(self):
        spec = geometry_spec("stepped_impedance", {"z1_width_mm": 0.3, "z2_width_mm": 3.0, "seg_len_mm": 5.0, "n_segments": 5})
        # substrate + ground + 2 feeds + 5 segments = 9
        assert len(spec["boxes"]) == 9

    def test_branchline_has_3_ports(self):
        spec = geometry_spec("branchline", {"arm_len_mm": 20.5, "series_w_mm": 1.87, "shunt_w_mm": 1.11})
        # 3 个 MSLPort + 隔离端 PML 端接标注 = 4（2026-09-05 角馈重构）
        assert len(spec["ports"]) == 4

    def test_dipole_has_1_port(self):
        spec = geometry_spec("dipole", {"dipole_len_mm": 58.0})
        assert len(spec["ports"]) == 1

    def test_stepped_has_2_ports(self):
        spec = geometry_spec("stepped_impedance", {"z1_width_mm": 0.3, "z2_width_mm": 3.0, "seg_len_mm": 5.0, "n_segments": 5})
        assert len(spec["ports"]) == 2

    def test_coupled_line_box_count(self):
        spec = geometry_spec("coupled_line", {"coupled_len_mm": 20.0, "line_w_mm": 1.0, "gap_mm": 0.5})
        # substrate + ground + 2 lines + 3 feeds = 7
        assert len(spec["boxes"]) == 7

    def test_coupled_line_has_3_ports(self):
        spec = geometry_spec("coupled_line", {"coupled_len_mm": 20.0, "line_w_mm": 1.0, "gap_mm": 0.5})
        assert len(spec["ports"]) == 3

    def test_coupled_line_spec_matches_script_topology(self):
        # 防回归：geometry_spec 与 render_script 必须描述同一拓扑（曾出现 coupled_line 缺 geometry_spec 分支、UI 3D 回落画成 patch）
        spec = geometry_spec("coupled_line", {"coupled_len_mm": 20.0, "line_w_mm": 1.0, "gap_mm": 0.5})
        assert spec["template"] == "coupled_line"
        names = [b["name"] for b in spec["boxes"]]
        assert "line_left" in names and "line_right" in names


class TestRenderScript:
    @pytest.mark.parametrize("template", ALL_TEMPLATES)
    def test_script_contains_essential_parts(self, template):
        params = _default_params(template)
        script = render_script(template, params, freq_range_ghz=(1.5, 3.5))
        assert "CSXCAD" in script
        assert "openEMS" in script
        assert "MSLPort" in script
        assert "CalcPort" in script
        assert "sparams.csv" in script
        assert "_port1" in script

    def test_branchline_script_has_port3(self):
        params = _default_params("branchline")
        script = render_script("branchline", params, freq_range_ghz=(2.0, 3.0))
        assert "_port3" in script

    def test_dipole_script_single_port(self):
        # WP1.3 官方口径重写：LumpedPort 中央直馈（单端口，无 _port2）
        params = _default_params("dipole")
        script = render_script("dipole", params, freq_range_ghz=(1.0, 2.0))
        assert "AddLumpedPort(1, 50.0" in script
        # 模板 body 无 _port2（footer 通用回退块除外，try/except 兜底）

    def test_stepped_script_has_loop(self):
        params = _default_params("stepped_impedance")
        script = render_script("stepped_impedance", params, freq_range_ghz=(1.0, 5.0))
        assert "for i in range(N_SEGS)" in script


def _default_params(template: str) -> dict:
    defaults = {
        "wilkinson": {"f0_ghz": 2.5, "series_w_mm": 1.113, "shunt_w_mm": 0.604, "arm_len_mm": 18.1},
        "patch": {"f0_ghz": 2.4, "patch_len_mm": 34.9, "patch_w_mm": 50.0, "feed_offset_mm": 10.0},
        "branchline": {"f0_ghz": 2.4, "arm_len_mm": 20.5, "series_w_mm": 1.87, "shunt_w_mm": 1.11},
        "dipole": {"f0_ghz": 2.4, "dipole_len_mm": 58.0, "dipole_w_mm": 2.0, "gap_mm": 2.0},
        "stepped_impedance": {"f0_ghz": 2.4, "z1_width_mm": 0.3, "z2_width_mm": 3.0, "seg_len_mm": 5.0, "n_segments": 5},
        "coupled_line": {"f0_ghz": 2.4, "coupled_len_mm": 20.0, "line_w_mm": 1.0, "gap_mm": 0.5},
    }
    return defaults.get(template, {})


class TestTemplateMeta:
    """方向 2 参数化公约：每模板 meta（仿真时长/网格/S 参数提取点/端口）。"""

    def test_meta_for_all_templates(self):
        from rfauto.adapters.openems_templates import PORTLESS_TEMPLATES, TEMPLATE_META, template_meta
        for t in TEMPLATE_META:
            meta = template_meta(t)
            assert meta["f0_ghz"] > 0
            # n_ports≥1 惯例；唯一例外=无端口软平面照明散射体（DP-10 阵）
            if meta["n_ports"] == 0:
                assert t in PORTLESS_TEMPLATES,                     f"{t}: n_ports=0 仅允许 PORTLESS_TEMPLATES"
            else:
                assert meta["n_ports"] >= 1
            assert "extraction" in meta  # S 参数提取点
            assert meta["max_time_ns"] > 0  # 仿真时长
            assert meta["mesh_resolution_mm"] >= 0  # 网格 base 覆盖（0=自动 λ_sub/50）
            assert meta["params"], "标称参数列表不能为空"

    def test_nominal_params_cover_geometry_inputs(self):
        # 标称设计点必须覆盖 geometry_spec 所需输入（防公约漂移）
        from rfauto.adapters.openems_templates import (
            TEMPLATE_META,
            TEMPLATE_NOMINAL,
            geometry_spec,
        )
        for t in TEMPLATE_META:
            spec = geometry_spec(t, TEMPLATE_NOMINAL[t])
            assert spec["template"] == t

    def test_meta_yaml_files_in_docs(self):
        # docs/templates/<t>/meta.yaml 静态文件与 TEMPLATE_META 同步
        import pathlib

        import yaml as _yaml

        from rfauto.adapters.openems_templates import TEMPLATE_META
        repo_root = pathlib.Path(__file__).resolve().parents[2]
        for t in TEMPLATE_META:
            p = repo_root / "docs" / "templates" / t / "meta.yaml"
            assert p.exists(), p
            data = _yaml.safe_load(p.read_text(encoding="utf-8"))
            assert data["template"] == t
            assert data["n_ports"] == TEMPLATE_META[t]["n_ports"]
