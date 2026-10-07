"""MP-B4 Icepak 判据清偿（#244 五坑离线固化）：守卫自检 + 源扫描 + 语义钉。

五坑 → 处置（全账见 runs/mpb4/clearance.md；既有钉=tests/unit/
test_icepak_adapter.py 内对应测试）：
1. **Region 自动生成**（首个实体自动生成 Region，create_region 报
   "already exists"）→ 既有钉 ``test_auto_region_reconfigured_instead_
   of_created``（改填充不新建）+ 全序列钉 fallback 形态（Absolute
   Offset+单位串）——已固化，本文件不重复；
2. **面监控两坑**（面 id 监控随 Region 重生成被删/对象级面监控对 3D
   Region 被拒）→ **守卫** ``audit_no_face_monitor_usage``（本文件扫
   adapter+脚本零命中+坏源自检）+ 既有钉（全序列断言不出面监控、判据
   走边界名 field summary、壁面 side="Adjacent"）；
3. **Include Gravity 在 setup 级且默认 False + gravity_dir=2**（pyaedt
   1.4.0 实装 0..5=−X..+Z，2=−Z；任务书草案"5=−Z"被代码实裁定）→
   既有钉（全序列断言 props["Include Gravity"] is True 与
   edit_design_settings==(2, 25.0)、bool/越界拒绝参数化）+ 本文件钉
   **stack 模式不碰该键**（防"顺手全局化"改纯传导语义）与常量钉；
4. **多设计状态快照**（previous 必须切换前取，否则新设计继承旧
   setup_name → analyze 静默 no-op）→ 既有钉 ``test_use_design_does_
   not_inherit_state`` + 本文件钉 set_active_design 往返恢复
   （切回旧设计 setup_name/monitor 复原、不重复 create_setup）；
5. **表达式字面量必须带单位**（#218 复踩：裸数字 5/8 被按米求值致空气
   盒 5m×8m）→ **守卫** ``audit_geometry_unit_literals``（本文件：坏源
   抓到+通道四源全扫通过）。

真机 Icepak 窗（AEDT 真跑判据复核/守恒门 32.5% 归因）本批不做，
如实登记 clearance.md（离线面=守卫+钉，不产真机结论）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rfauto.adapters.icepak_adapter import (
    DEFAULT_GRAVITY_DIR,
    FORBIDDEN_MONITOR_APIS,
    GEOMETRY_UNIT_PARAM_RULES,
    audit_geometry_unit_literals,
    audit_no_face_monitor_usage,
)
from tests.unit.test_icepak_adapter import (
    _CONVECTION_REPORTS,
    _FakeIcepak,
    _install_fake_pyaedt,
    _make_adapter,
)

_REPO = Path(__file__).resolve().parents[2]

#: Icepak 通道源面（守卫扫描范围：adapter + 三个真机编排脚本；
#: multiphysics_probe.py 只做 license/安装面探测、零几何构建调用，
#: 不在扫描面——登记 clearance.md 坑5"不适用"）
_ICEntriesPAK_SOURCES = [
    _REPO / "src" / "rfauto" / "adapters" / "icepak_adapter.py",
    _REPO / "scripts" / "icepak_convection_case.py",
    _REPO / "scripts" / "icepak_electrothermal_case.py",
    _REPO / "scripts" / "icepak_hfss_loss_e2e.py",
]


# ─── 坑5 守卫：几何调用单位字面量审计（#218）────────────────────────────────


class TestUnitLiteralGuardPit5:
    def test_channel_sources_are_clean(self):
        """通道四源全扫零违规（守卫通过态=当前代码面固化为基线）。"""
        for path in _ICEntriesPAK_SOURCES:
            violations = audit_geometry_unit_literals(
                path.read_text(encoding="utf-8"), filename=str(path))
            assert violations == [], f"{path}: {violations}"

    def test_guard_flags_bare_numbers_all_forms(self):
        bad = '''
def build(m, val):
    m.create_box(origin=[0, 0, "0mm"], sizes=[5, 8, 1.5], name="Air")  # 位置+裸数
    m.create_box(origin=["0mm", -2, "0mm"], sizes=["1mm", "1mm", "1mm"])  # 一元负号
    m.create_cylinder(orientation="Z", origin=["0mm", "0mm", 0.0],
                      radius=8, height="2mm", name="c")  # 关键字形态
    m.create_region([7, 7, 7, 7, 7, 7])  # 列表内裸数
    m.assign_point_monitor([1.0, "2mm", "0mm"])  # 监控点位置
'''
        violations = audit_geometry_unit_literals(bad, filename="bad.py")
        text = "\n".join(violations)
        # 行号与形参名进报告（可定位修复）
        for lineno in (3, 4, 5, 6, 7, 8):
            assert any(v.startswith(f"bad.py:{lineno}:") for v in violations), text
        for param in ("origin", "sizes", "radius", "padding", "position"):
            assert f"{param}=" in text, text
        assert "SI 米" in text  # #218 坑语义随报告在场

    def test_guard_passes_clean_forms(self):
        good = '''
def build(m, count, val):
    m.create_box(origin=["0mm", "0mm", "0mm"],
                 sizes=["20.0mm", "20.0mm", "0.508mm"], name="s", material="m")
    m.create_box(origin=[f"{val}mm", "-2.0mm", "0mm"],
                 sizes=[mm_of(3), "sub_l*$scale", "0mm"])
    m.create_cylinder(orientation="Z", origin=["0mm", "0mm", "0mm"],
                      radius=val, height=2 * count, name="c")
    m.create_rectangle(origin=["-a/2", y, "0mm"], sizes=["4*h", "5*w"])
    m.create_region([f"{val}mm"] * 6, pad_type="Absolute Offset")
    m.assign_point_monitor([center_x, "0mm", "0.254mm"])
    m.create_box(origin=["0mm", "0mm", "0mm"], sizes=["1mm", 1 + 1, "1mm"])
'''
        assert audit_geometry_unit_literals(good, filename="good.py") == []

    def test_guard_reraises_syntax_error(self):
        with pytest.raises(SyntaxError):
            audit_geometry_unit_literals("def broken(:", filename="x.py")

    def test_audited_api_set_is_explicit(self):
        """审计 API 集显式钉（扩面=显式评审动作，防静默漂移）。"""
        assert set(GEOMETRY_UNIT_PARAM_RULES) == {
            "create_box", "create_cylinder", "create_circle",
            "create_rectangle", "create_region", "assign_point_monitor"}


# ─── 坑2 守卫：面监控禁用（判据数据源=边界名 field summary）─────────────────


class TestFaceMonitorGuardPit2:
    def test_channel_sources_have_no_face_monitor_calls(self):
        for path in _ICEntriesPAK_SOURCES:
            violations = audit_no_face_monitor_usage(
                path.read_text(encoding="utf-8"), filename=str(path))
            assert violations == [], f"{path}: {violations}"

    def test_guard_flags_face_monitor_usage(self):
        bad = '''
def watch(ipk, faces):
    ipk.monitor.assign_face_monitor(faces[0], monitor_name="T")
    ipk.assign_surface_monitor("Region", monitor_type="Temperature")
'''
        violations = audit_no_face_monitor_usage(bad, filename="bad.py")
        assert len(violations) == 2
        assert all("evaluate_boundary_quantity" in v for v in violations)

    def test_forbidden_api_list_is_explicit(self):
        assert FORBIDDEN_MONITOR_APIS == (
            "assign_face_monitor", "assign_surface_monitor")


# ─── 坑3 语义钉：重力开关 setup 级缺省关态 + 方向常量 ───────────────────────


class TestGravitySemanticsPit3:
    def test_default_gravity_dir_is_minus_z(self):
        """pyaedt 1.4.0 icepak.py 实装 0..5=−X..+Z（>2 判正方向）→ 2=−Z。

        任务书草案"5=−Z"与实装相反，按代码实裁定（WP4.4a verdict）——
        本钉防回退到错误方向口径。
        """
        assert DEFAULT_GRAVITY_DIR == 2

    def test_stack_solve_does_not_touch_include_gravity(self, tmp_path,
                                                         monkeypatch):
        """stack（TemperatureOnly）模式 solve 不得置 Include Gravity。

        重力开关在 setup 级且 AEDT 默认 False；对流模式显式开（既有钉
        test_build_and_solve_full_sequence 断言 True）。本钉反方向：
        纯传导模式的 setup props 不出现该键——"顺手全局化"会改纯传导
        语义（浮升力本不该在场），一旦引入此钉即红。
        """
        calls: list = []
        _install_fake_pyaedt(monkeypatch, calls, {"Mean": 25.4, "Unit": "cel"})
        adapter = _make_adapter(tmp_path)  # 默认 problem_type=TemperatureOnly
        assert adapter.connect() is True
        assert adapter.build_geometry({"power_w": 0.5}) is True
        result = adapter.solve()
        setup_obj = adapter._ipk.last_setup  # close 前抓
        adapter.close()

        assert result.success is True
        assert "Include Gravity" not in setup_obj.props
        assert not any(c[1] == "edit_design_settings" for c in calls)


# ─── 坑4 语义钉：多设计状态快照的切换前取 + 往返恢复 ────────────────────────


class TestDesignStateSnapshotPit4:
    @staticmethod
    def _fake_set_active_design(self, name):
        self.calls.append(("call", "set_active_design", (name,), {}))
        self.design_name = name
        return name

    def test_set_active_design_roundtrip_restores_state(self, tmp_path,
                                                         monkeypatch):
        """往返恢复：切回旧设计后 setup_name/建模状态复原且不重建 setup。

        坑语义（2025.1 真机实证）：状态存档挂错设计名会让新设计继承旧
        setup_name → solve 跳过 create_setup → analyze 对不存在 setup
        静默 no-op（"solved in 0.0s"）→ 监控读空。往返恢复钉补齐
        set_active_design 路径（既有钉只盖 use_design 单向）。
        """
        monkeypatch.setattr(_FakeIcepak, "set_active_design",
                            self._fake_set_active_design, raising=False)
        calls: list = []
        _install_fake_pyaedt(monkeypatch, calls, {"Mean": 60.0, "Unit": "cel"})
        adapter = _make_adapter(tmp_path)
        assert adapter.connect() is True
        # 设计 A（默认 rfauto_et）：建模+求解（建 setup）
        assert adapter.build_geometry({"power_w": 0.5}) is True
        assert adapter.solve().success is True
        assert adapter._setup_name == "rfauto_et_setup"
        # 切设计 B：全新状态（不继承 A 的 setup_name）
        assert adapter.use_design("rfauto_second") is True
        assert adapter._setup_name is None
        assert adapter._built is False
        # 设计 B 建模+求解（第二次 create_setup）
        assert adapter.build_geometry({"power_w": 0.25}) is True
        assert adapter.solve().success is True
        # 切回 A：状态复原（setup_name/监控/模式），且不第三次 create_setup
        assert adapter.set_active_design("rfauto_et") is True
        assert adapter._ipk.design_name == "rfauto_et"
        assert adapter._setup_name == "rfauto_et_setup"
        assert adapter._built is True
        assert adapter._mode == "stack"
        assert adapter._monitor_name == "rfauto_T_blk"
        assert adapter._spec["power_w"] == 0.5
        # 复原的 setup 直接复用：solve 不再 create_setup（总数保持 2）
        result = adapter.solve()
        assert result.success is True
        assert sum(1 for c in calls if c[1] == "create_setup") == 2
        analyze_targets = [c[2][0] for c in calls if c[1] == "analyze"]
        assert analyze_targets == ["rfauto_et_setup", "rfauto_et_setup",
                                   "rfauto_et_setup"]

    def test_convection_reports_boundary_names(self, tmp_path,
                                               monkeypatch):
        """坑2 动态对账（补充既有钉）：判据数据源=边界名字符串而非面 id。"""
        calls: list = []
        _install_fake_pyaedt(monkeypatch, calls, dict(_CONVECTION_REPORTS))
        adapter = _make_adapter(tmp_path, problem_type="TemperatureAndFlow")
        adapter.connect()
        assert adapter.build_convection_case({"power_w": 0.5}) is True
        assert isinstance(adapter._wall_boundary, str)
        assert isinstance(adapter._opening_boundary, str)
        result = adapter.solve()
        adapter.close()
        heat = result.field_data["heat_flow"]
        # 出热判据按边界名（面 id 监控会被 Region 重生成删除——坑2a）
        assert heat["wall_boundary"] == "Wall"
        assert heat["opening_boundary"] == "Opening1"
