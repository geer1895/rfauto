"""T-Q26b geometry_lint 建模期几何门单测（aurora_q 席位 Q-X2）。

输入=晶圆键合实测反馈 §4 质检门表 + §2.2/§2.3（D:/晶圆键合/
rfauto_反馈与实测经验.md）。覆盖：
- 六检查各正负例（含 §2.2 vacuum 包裹合法/部分相交报两情形；
  §2.3 端口三静默失败形态 A/B/C 各一钉）；
- 信封契约（ok/lint_pass/issues/counts/summary、schema 校验失败走
  error_envelope、多模豁免、零厚度 sheet 豁免）；
- hfss_adapter.build_and_setup 挂钩（缺省关零行为变化/ERROR 拦截/
  WARN 放行/报告形态非法 fail-loud）。

零 pyaedt、零网络、零真机、零 license——纯声明式几何与表达式词法。
"""

from __future__ import annotations

import pytest

from rfauto.service.geometry_lint_service import (
    LintBox,
    LintGeometry,
    LintPort,
    LintPortSheet,
    LintVariable,
    lint_geometry,
)

# ── 复用夹具：真空域盒（反馈 §2.1 口径 0.9×0.5×4.0mm 空气腔量级）──────

VAC = dict(name="Vacuum", material="vacuum", solve_inside=True,
           coords=(-2.0, -0.45, -0.25, 2.0, 0.45, 0.25))


def _vac(**over) -> LintBox:
    kw = dict(VAC)
    kw.update(over)
    return LintBox(**kw)


def _wave_port(name: str = "P1", pos: float = -2.0, **sheet_over) -> LintPort:
    """x=pos 面上的满截面波端口（u=y 跨度、v=z 跨度）。"""
    return LintPort(
        name=name, kind="wave",
        sheet=LintPortSheet(axis="x", pos=pos,
                            u=(-0.45, 0.45), v=(-0.25, 0.25), **sheet_over))


def _issues(envelope: dict, check: str | None = None) -> list[dict]:
    items = envelope["issues"]
    if check is None:
        return items
    return [i for i in items if i["check"] == check]


# ── 信封契约 ───────────────────────────────────────────────────────────


class TestEnvelope:
    def test_clean_geometry_ok_pass_true_zero_issues(self):
        env = lint_geometry(LintGeometry(boxes=[_vac()],
                                         ports=[_wave_port()]))
        assert env["ok"] is True
        assert env["lint_pass"] is True
        assert env["issues"] == []
        assert env["counts"] == {"error": 0, "warn": 0}
        assert env["model_units"] == "mm"
        assert env["summary"] == {"boxes": 1, "ports": 1, "variables": 0}

    def test_dict_input_accepted_and_unknown_field_rejected(self):
        raw = {"boxes": [{"name": "B", "coords": [0, 0, 0, 1, 1, 1]}]}
        env = lint_geometry(raw)
        assert env["ok"] is True and env["summary"]["boxes"] == 1
        bad = {"boxes": [{"name": "B", "coords": [0, 0, 0, 1, 1, 1],
                          "no_such_field": 1}]}
        env_bad = lint_geometry(bad)
        assert env_bad["ok"] is False
        assert env_bad["errors"], "schema 失败必须带 errors"
        assert env_bad["issues"] == [] and env_bad["lint_pass"] is False

    def test_duplicate_names_rejected(self):
        # 构造期 pydantic 直接红（schema 层）；经 dict 走 lint_geometry
        # 则收敛为 error 信封（service JSON 进出路径）
        with pytest.raises(Exception, match="重名"):
            LintGeometry(boxes=[_vac(), _vac()])
        env = lint_geometry({"boxes": [
            {"name": "Vacuum", "coords": [0, 0, 0, 1, 1, 1]},
            {"name": "Vacuum", "coords": [2, 2, 2, 3, 3, 3]},
        ]})
        assert env["ok"] is False and "重名" in env["errors"][0]

    def test_multi_violation_counts_and_pass_false(self):
        # ①埋入端口 + ④部分相交 + ⑥裸数 三处 ERROR 同时聚合
        # （Si2 只在 x∈[1.2,2.5] 与真空盒部分相交、不覆盖端口面 x=0，
        #   避免检查③截面切分 WARN 混入计数）
        geo = LintGeometry(
            boxes=[
                _vac(),
                LintBox(name="Si2", material="silicon", solve_inside=True,
                        coords=(1.2, -0.45, -0.25, 2.5, 0.45, 0.25)),
            ],
            ports=[_wave_port(pos=0.0)],
            variables=[LintVariable(name="w_s", expression="w_base+0.04")],
        )
        env = lint_geometry(geo)
        assert env["ok"] is True and env["lint_pass"] is False
        assert env["counts"]["error"] == 3 and env["counts"]["warn"] == 0
        checks = {i["check"] for i in env["issues"]}
        assert checks == {"port_on_outer_boundary", "partial_intersection",
                          "variable_units"}


# ── 检查① 端口在外边界（反馈 §2.3 断言 1）────────────────────────────


class TestPortOnOuterBoundary:
    def test_wave_port_on_bbox_face_ok(self):
        env = lint_geometry(LintGeometry(boxes=[_vac()],
                                         ports=[_wave_port()]))
        assert _issues(env, "port_on_outer_boundary") == []

    def test_wave_port_buried_inside_error(self):
        # 反馈 §2.3 断言 1 反例：端口面在模型内部（x=0 非包围盒面）
        env = lint_geometry(LintGeometry(boxes=[_vac()],
                                         ports=[_wave_port(pos=0.0)]))
        hits = _issues(env, "port_on_outer_boundary")
        assert len(hits) == 1 and hits[0]["level"] == "ERROR"
        assert hits[0]["objects"] == ["P1"]

    def test_lumped_port_exempt_from_boundary_check(self):
        # lumped 口天然在模型内部，检查①豁免（②仍把门）
        lumped = LintPort(name="LP", kind="lumped",
                          sheet=LintPortSheet(axis="x", pos=0.0,
                                              u=(-0.1, 0.1), v=(-0.1, 0.1)))
        env = lint_geometry(LintGeometry(boxes=[_vac()], ports=[lumped]))
        assert _issues(env, "port_on_outer_boundary") == []

    def test_no_boxes_skips_boundary_check(self):
        # 无实体（纯端口描述）时检查①无包围盒可比对，跳过不误报
        env = lint_geometry(LintGeometry(ports=[_wave_port()]))
        assert _issues(env, "port_on_outer_boundary") == []


# ── 检查② 端口邻接 solve-inside 体（反馈 §2.3 形态 A）────────────────


class TestPortAdjacentSolveInside:
    def test_adjacent_solve_inside_ok(self):
        env = lint_geometry(LintGeometry(boxes=[_vac()],
                                         ports=[_wave_port()]))
        assert _issues(env, "port_adjacent_solve_inside") == []

    def test_no_solve_inside_neighbor_error_form_a(self):
        # 反馈 §2.3 形态 A 复现钉：真空是背景（未显式建 solve_inside 体）
        env = lint_geometry(LintGeometry(
            boxes=[_vac(solve_inside=False)], ports=[_wave_port()]))
        hits = _issues(env, "port_adjacent_solve_inside")
        assert len(hits) == 1 and hits[0]["level"] == "ERROR"
        assert "solved inside material" in hits[0]["message"]

    def test_adjacency_within_tol_vs_beyond(self):
        # 1e-6 邻域口径：体面距端口面 5e-7=邻接；1e-4=不邻接（②连同
        # ①一起红——bbox 已随体移动，两检查共 firing 属预期）
        near = _vac(name="Near", coords=(-1.9999995, -0.45, -0.25,
                                         2.0, 0.45, 0.25))
        env_near = lint_geometry(LintGeometry(boxes=[near],
                                              ports=[_wave_port()]))
        assert _issues(env_near, "port_adjacent_solve_inside") == []
        far = _vac(name="Far", coords=(-1.9999, -0.45, -0.25,
                                       2.0, 0.45, 0.25))
        env_far = lint_geometry(LintGeometry(boxes=[far],
                                             ports=[_wave_port()]))
        hits = _issues(env_far, "port_adjacent_solve_inside")
        assert len(hits) == 1 and hits[0]["level"] == "ERROR"

    def test_tangential_edge_graze_not_adjacent(self):
        # 体与端口面只在棱上擦边（切向零面积交）不算邻接
        grazed = _vac(name="G", coords=(-2.0, 0.45, -0.25,
                                        2.0, 0.9, 0.25))
        env = lint_geometry(LintGeometry(boxes=[grazed], ports=[_wave_port()]))
        assert len(_issues(env, "port_adjacent_solve_inside")) == 1


# ── 检查③ 端口截面连通性（反馈 §2.3 断言 3 / 形态 B、C）──────────────


class TestPortCrossSectionConnectivity:
    def test_single_air_region_ok(self):
        env = lint_geometry(LintGeometry(boxes=[_vac()],
                                         ports=[_wave_port()]))
        assert _issues(env, "port_cross_section_connectivity") == []

    def test_split_air_warn_form_b(self):
        # 反馈 §2.3 形态 B 复现钉：金属壁把截面空气切成两个不连通区
        # （端口面取 x=+2.0 域面，壁横跨该面）
        wall = LintBox(name="Wall", material="gold",
                       coords=(1.5, -0.01, -0.25, 2.0, 0.01, 0.25))
        env = lint_geometry(LintGeometry(boxes=[_vac(), wall],
                                         ports=[_wave_port(pos=2.0)]))
        hits = _issues(env, "port_cross_section_connectivity")
        assert len(hits) == 1 and hits[0]["level"] == "WARN"
        assert hits[0]["objects"][0] == "P1" and "Wall" in hits[0]["objects"]
        # WARN 不拦截门（lint_pass 只看 ERROR）
        assert env["lint_pass"] is True and env["counts"]["warn"] == 1

    def test_thin_film_wall_subcell_warn_form_c(self):
        # 反馈 §2.3 形态 C 复现钉：3µm 薄膜（亚胞：0.9mm/64≈14µm 胞距）
        # 切分截面——保守栅格化必须仍能切开空气（端口面 x=+2.0）
        film = LintBox(name="Film", material="gold",
                       coords=(1.5, -0.0015, -0.25, 2.0, 0.0015, 0.25))
        env = lint_geometry(LintGeometry(boxes=[_vac(), film],
                                         ports=[_wave_port(pos=2.0)]))
        hits = _issues(env, "port_cross_section_connectivity")
        assert len(hits) == 1 and hits[0]["level"] == "WARN"

    def test_multimode_exempt(self):
        wall = LintBox(name="Wall", material="gold",
                       coords=(1.5, -0.01, -0.25, 2.0, 0.01, 0.25))
        port = _wave_port(pos=2.0)
        port_multimode = LintPort(name=port.name, kind=port.kind,
                                  sheet=port.sheet, multimode=True)
        env = lint_geometry(LintGeometry(boxes=[_vac(), wall],
                                         ports=[port_multimode]))
        assert _issues(env, "port_cross_section_connectivity") == []

    def test_air_material_body_does_not_split(self):
        # air/vacuum 材质体不阻挡空气连通性（截面上叠半个真空盒仍 1 连通域）
        air_half = LintBox(name="AirHalf", material="air",
                           coords=(1.5, 0.0, -0.25, 2.0, 0.45, 0.25))
        env = lint_geometry(LintGeometry(boxes=[_vac(), air_half],
                                         ports=[_wave_port()]))
        assert _issues(env, "port_cross_section_connectivity") == []


# ── 检查④ 实体部分相交（反馈 §2.2 两情形）────────────────────────────


class TestPartialIntersections:
    def test_vacuum_wrapping_solid_legal(self):
        # 反馈 §2.2 情形 1：真空盒完全包住 Si 盒 → 不报（合法包含）
        vac = _vac(name="Vacuum", coords=(-0.45, -0.25, -2.0,
                                          0.45, 0.30, 2.0))
        si = LintBox(name="Si", material="silicon", solve_inside=True,
                     coords=(-0.4, -0.25, -1.8, 0.4, 0.25, 1.8))
        env = lint_geometry(LintGeometry(boxes=[vac, si]))
        assert _issues(env, "partial_intersection") == []
        assert env["lint_pass"] is True

    def test_partial_intersection_error(self):
        # 反馈 §2.2 情形 2：膜穿出真空盒 → ERROR 双对象列出
        vac = _vac(name="Vacuum")
        membrane = LintBox(name="W2_Membrane", material="silicon",
                           solve_inside=True,
                           coords=(-2.5, -0.02, -2.0, 0.6, 0.03, 2.0))
        env = lint_geometry(LintGeometry(boxes=[vac, membrane]))
        hits = _issues(env, "partial_intersection")
        assert len(hits) == 1 and hits[0]["level"] == "ERROR"
        assert hits[0]["objects"] == ["Vacuum", "W2_Membrane"]
        assert "Parts" in hits[0]["message"] and "intersect" in hits[0]["message"]
        assert env["lint_pass"] is False

    def test_touching_layers_and_identical_boxes_ok(self):
        # 面贴层叠（z 向共享面，重叠=0）与全同盒（互为包含）都不算部分相交
        # （全同盒放在 x∈[5,6] 远离层叠，避免与层叠构成真部分相交）
        bottom = LintBox(name="Sub", material="silicon",
                         coords=(-1.0, -1.0, -0.25, 1.0, 1.0, 0.0))
        top = LintBox(name="Memb", material="silicon",
                      coords=(-1.0, -1.0, 0.0, 1.0, 1.0, 0.05))
        dup1 = LintBox(name="Dup1", material="vacuum",
                       coords=(5.0, 5.0, 5.0, 6.0, 6.0, 6.0))
        dup2 = LintBox(name="Dup2", material="vacuum",
                       coords=(5.0, 5.0, 5.0, 6.0, 6.0, 6.0))
        env = lint_geometry(LintGeometry(boxes=[bottom, top, dup1, dup2]))
        assert _issues(env, "partial_intersection") == []

    def test_zero_thickness_sheet_never_partial_intersects(self):
        # 零厚度薄片与体相交不成实体（HFSS sheet 语义），不进相交列表
        sheet = LintBox(name="Strip", material="pec",
                        coords=(-1.9, -0.26, 0.02, 1.9, 0.26, 0.02))
        env = lint_geometry(LintGeometry(boxes=[_vac(), sheet]))
        assert _issues(env, "partial_intersection") == []


# ── 检查⑤ 薄金属纵横比 ─────────────────────────────────────────────────


class TestMetalAspectRatio:
    def test_thin_metal_solid_warn(self):
        film = LintBox(name="film", material="gold",
                       coords=(0.0, 0.0, 0.0, 40.0, 40.0, 0.0001))
        env = lint_geometry(LintGeometry(boxes=[film]))
        hits = _issues(env, "metal_aspect_ratio")
        assert len(hits) == 1 and hits[0]["level"] == "WARN"
        assert "sheet" in hits[0]["message"]

    def test_zero_thickness_metal_sheet_exempt(self):
        # 零厚度=已是 sheet（"建议改 sheet"的目标形态本身），不告警
        sheet = LintBox(name="sheet", material="pec",
                        coords=(0.0, 0.0, 0.0, 40.0, 40.0, 0.0))
        env = lint_geometry(LintGeometry(boxes=[sheet]))
        assert _issues(env, "metal_aspect_ratio") == []

    def test_material_heuristic_and_explicit_override(self):
        # 介质薄膜不告警；"alumina" 不误判金属；is_metal=True 显式覆盖生效
        alumina = LintBox(name="al", material="alumina",
                          coords=(0.0, 0.0, 0.0, 40.0, 40.0, 0.0001))
        env = lint_geometry(LintGeometry(boxes=[alumina]))
        assert _issues(env, "metal_aspect_ratio") == []
        forced = LintBox(name="al2", material="alumina", is_metal=True,
                         coords=(0.0, 0.0, 0.0, 40.0, 40.0, 0.0001))
        env2 = lint_geometry(LintGeometry(boxes=[forced]))
        assert len(_issues(env2, "metal_aspect_ratio")) == 1


# ── 检查⑥ 变量单位裸数（反馈 §4 末条真坑）────────────────────────────


class TestVariableUnits:
    def test_bare_additive_number_error(self):
        # 真坑原样：w_s+0.04 → HFSS 把 0.04 当 0.04 m
        geo = LintGeometry(variables=[
            LintVariable(name="w_s", expression="w_base+0.04")])
        env = lint_geometry(geo)
        hits = _issues(env, "variable_units")
        assert len(hits) == 1 and hits[0]["level"] == "ERROR"
        assert hits[0]["objects"] == ["w_s"]
        assert "0.04 m" in hits[0]["message"]
        assert env["lint_pass"] is False

    def test_unit_suffix_multiplier_function_args_ok(self):
        geo = LintGeometry(variables=[
            LintVariable(name="a", expression="w_base+0.04mm"),
            LintVariable(name="b", expression="2*w_base"),
            LintVariable(name="c", expression="w_base*0.5"),
            LintVariable(name="d", expression="sqrt(2)*w_base"),
            LintVariable(name="e", expression="-2*w_base"),
        ])
        env = lint_geometry(geo)
        assert _issues(env, "variable_units") == []

    def test_whole_expression_bare_and_dimensionless_exempt(self):
        geo = LintGeometry(variables=[
            LintVariable(name="w", expression="0.5"),
            LintVariable(name="n", expression="2+3",
                         dimension="dimensionless"),
        ])
        env = lint_geometry(geo)
        hits = _issues(env, "variable_units")
        assert len(hits) == 1 and hits[0]["objects"] == ["w"]

    def test_subtractive_and_unary_signs(self):
        geo = LintGeometry(variables=[
            LintVariable(name="a", expression="w_base-0.04"),   # 减法裸数
            LintVariable(name="b", expression="w_s + -0.04"),   # 右操作数负裸数
            LintVariable(name="c", expression="-0.04*w_base"),  # 一元负号乘子
        ])
        env = lint_geometry(geo)
        hits = _issues(env, "variable_units")
        assert {h["objects"][0] for h in hits} == {"a", "b"}


# ── hfss_adapter.build_and_setup 挂钩（缺省关）─────────────────────────


def _adapter_with_recording():
    """零 pyaedt 构造 HfssAdapter（session.hfss 置哑元），记录执行序。"""
    from rfauto.adapters.hfss_adapter import HfssAdapter

    ad = HfssAdapter()
    ad.session.hfss = object()  # build_and_setup 只判非 None
    log: list[str] = []

    def builder(_adapter) -> None:
        log.append("build")

    def fake_setup(cfg: dict) -> str:
        log.append(f"setup:{cfg.get('name')}")
        return str(cfg.get("name"))

    return ad, log, builder, fake_setup


class TestBuildHook:
    def test_default_off_zero_behavior(self):
        # 缺省（不传 geometry_lint_report）：builder 照跑、无门干预
        ad, log, builder, fake_setup = _adapter_with_recording()
        ad.configure_setup = fake_setup  # type: ignore[method-assign]
        ad.build_and_setup(builder, {"name": "S1"})
        assert log == ["build", "setup:S1"]

    def test_error_report_blocks_before_setup(self):
        from rfauto.core.errors import ModelBuildError

        ad, log, builder, fake_setup = _adapter_with_recording()
        ad.configure_setup = fake_setup  # type: ignore[method-assign]
        report = lint_geometry(LintGeometry(
            boxes=[_vac(solve_inside=False)], ports=[_wave_port()]))
        assert report["counts"]["error"] == 1
        with pytest.raises(ModelBuildError) as ei:
            ad.build_and_setup(builder, {"name": "S1"},
                               geometry_lint_report=report)
        assert log == ["build"], "门在 build 出口、configure_setup 之前"
        assert "port_adjacent_solve_inside" in str(ei.value)

    def test_warn_report_proceeds(self, caplog):
        ad, log, builder, fake_setup = _adapter_with_recording()
        ad.configure_setup = fake_setup  # type: ignore[method-assign]
        wall = LintBox(name="Wall", material="gold",
                       coords=(1.5, -0.01, -0.25, 2.0, 0.01, 0.25))
        report = lint_geometry(LintGeometry(boxes=[_vac(), wall],
                                            ports=[_wave_port(pos=2.0)]))
        assert report["counts"] == {"error": 0, "warn": 1}
        import logging

        with caplog.at_level(logging.WARNING):
            ad.build_and_setup(builder, {"name": "S1"},
                               geometry_lint_report=report)
        assert log == ["build", "setup:S1"]
        assert any("geometry_lint WARN" in r.message for r in caplog.records)

    def test_malformed_report_fails_loud(self):
        from rfauto.core.errors import ModelBuildError

        ad, log, builder, _ = _adapter_with_recording()
        with pytest.raises(ModelBuildError):
            ad.build_and_setup(builder, None, geometry_lint_report=["bad"])
        with pytest.raises(ModelBuildError):
            ad.build_and_setup(builder, None, geometry_lint_report={"no": "ok"})
        bad_ok = {"ok": False, "errors": ["schema 炸了"]}
        with pytest.raises(ModelBuildError) as ei:
            ad.build_and_setup(builder, None, geometry_lint_report=bad_ok)
        assert "schema" in str(ei.value)
        assert log == ["build", "build", "build"]
