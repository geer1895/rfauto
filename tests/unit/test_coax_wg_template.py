"""coax_waveguide_transition 波导-同轴过渡模板测试（ME-6 离线段，#212 制度化）。

零仿真（exec 截断于 FDTD.Run 之前，秒级）：渲染→exec 几何段→CSXCAD 实测
封闭厚壁腔/探针柱/集总桥连通性/双场端口截面/壁面站线入网 + WR 表联动
（core/rw_tables.wr_lookup 单源，fc10 恒等式 + λg/4 背腔闭式重算）+ 教程
名义参数回显 + 渲染守卫（探针体/触顶壁/不进腔/伸入校准段）+ 注册四件套
+ docs meta.yaml 一致性。

方案锚：月度增强方案 §三 A 流 ME-6——openEMS
官方 Coax-to-Waveguide 教程参数化直抄起手（wiki Matlab 教程结构 + 官方
Python "Horn Antenna with Coaxial Pin Feed" 教程 pin/集总桥参数）+ HFSS
仲裁（Ph3 窗，本批零发射）；端口口径决定：CoaxialPort 不用（仓内
sma_launcher pt2 真机判废 + 官方讨论 #437），采纳探针柱+LumpedPort。
"""

from __future__ import annotations

import csv
import math
import os
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters.openems_templates import (
    COAX_WG_NOMINAL,
    TEMPLATE_META,
    TEMPLATE_NOMINAL,
    _coax_wg_layout,
    coax_wg_design_params,
    geometry_spec,
    render_script,
    template_meta,
)
from rfauto.core.rw_tables import wr_lookup
from tests.unit import _geometry_audit_helpers as gh
from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES

NOM = dict(COAX_WG_NOMINAL)
T = "coax_waveguide_transition"
F0_GHZ = 10.0
BAND = (F0_GHZ - 0.25, F0_GHZ + 0.25)
_C0_MM_GHZ = 299.792458   # mm·GHz（闭式重算口径，mm 域免 1e-3 换算）


# ─── 1) 名义单源 + WR 联动（wr_lookup 单源，零手抄 #1c）──────────────────────

class TestNominalAndWrLinkage:
    def test_nominal_matches_wr_table_bitwise(self):
        """a/b 与 wr_lookup("WR-90") 逐位相等（WR 表单源，非近似）。"""
        rec = wr_lookup("WR-90")
        assert NOM["a_mm"] == rec.a_mm
        assert NOM["b_mm"] == rec.b_mm

    def test_fc10_identity_and_backshort_closed_form(self):
        """fc10=c0/2a 恒等式（与表 fc10_ghz 自洽）+ backshort=λg/4 闭式重算
        （独立于 _coax_wg_nominal 的实现路径，#118 族双源钉）。"""
        rec = wr_lookup("WR-90")
        fc10 = _C0_MM_GHZ / (2.0 * NOM["a_mm"])
        assert fc10 == pytest.approx(rec.fc10_ghz, rel=1e-12)
        lam0 = _C0_MM_GHZ / F0_GHZ
        lam_g = lam0 / math.sqrt(1.0 - (fc10 / F0_GHZ) ** 2)
        assert NOM["backshort_mm"] == pytest.approx(lam_g / 4.0, rel=1e-12)

    def test_tutorial_copied_params(self):
        """官方 Python 教程直抄参数：wg_t=2.0/pin_r=0.5/port_h=1.0、
        pin_len=0.55·b（docs.openems.de Horn Antenna with Coaxial Pin
        Feed 教程字面）。"""
        assert NOM["wg_t_mm"] == pytest.approx(2.0)
        assert NOM["pin_r_mm"] == pytest.approx(0.5)
        assert NOM["port_h_mm"] == pytest.approx(1.0)
        assert NOM["pin_len_mm"] == pytest.approx(0.55 * NOM["b_mm"])
        assert NOM["l_wg_mm"] == pytest.approx(30.0)

    @pytest.mark.parametrize("wr_name", ["WR-90", "WR-75", "WR-62", "WR-284"])
    def test_design_params_multi_wr(self, wr_name):
        """WR 表联动换档：a/b=表口径、backshort=λg/4@带中心闭式重算一致。"""
        rec = wr_lookup(wr_name)
        f0 = 0.5 * (rec.f_start_ghz + rec.f_end_ghz)
        d = coax_wg_design_params(wr_name, f0)
        assert d["a_mm"] == rec.a_mm and d["b_mm"] == rec.b_mm
        fc10 = _C0_MM_GHZ / (2.0 * rec.a_mm)
        lam_g = (_C0_MM_GHZ / f0) / math.sqrt(1.0 - (fc10 / f0) ** 2)
        assert d["backshort_mm"] == pytest.approx(lam_g / 4.0, rel=1e-12)
        assert d["pin_len_mm"] == pytest.approx(0.55 * rec.b_mm)


# ─── 2) 布局派生量 + 渲染守卫（设计约束先声明后钉）────────────────────────────

class TestLayoutAndGuards:
    def test_layout_derived_quantities(self):
        """域/盒数/端口坐标：域对称（x/y）、探针中心 z=backshort、port2 两
        面内移 16·BASE 出 PML_8（审查轨 B P0-1 修正；#154 域边口径仅
        MSLPort 成立，WaveguidePort 探针面在 PML 内=波分解被衰减）。"""
        lay = _coax_wg_layout(dict(NOM), BAND, 0.4)
        t = NOM["wg_t_mm"]
        assert lay["dom_x_mm"] == pytest.approx(NOM["a_mm"] / 2 + t + 6.0)
        assert lay["dom_y_mm"] == pytest.approx(NOM["b_mm"] / 2 + t + 6.0)
        assert lay["z_lo_mm"] == pytest.approx(-(t + 6.0))
        assert lay["z_hi_mm"] == pytest.approx(NOM["l_wg_mm"])
        assert lay["z_pin_mm"] == pytest.approx(NOM["backshort_mm"])
        assert len(lay["boxes"]) == 6   # 四壁+背短路板+探针柱
        p1, p2 = lay["port1"], lay["port2"]
        # port1：探针基集总桥（壁内侧面→针底，截面 2·pin_r，R=50）
        assert p1["start_mm"] == pytest.approx(
            [-NOM["pin_r_mm"], -NOM["b_mm"] / 2,
             NOM["backshort_mm"] - NOM["pin_r_mm"]])
        assert p1["stop_mm"] == pytest.approx(
            [NOM["pin_r_mm"], -NOM["b_mm"] / 2 + NOM["port_h_mm"],
             NOM["backshort_mm"] + NOM["pin_r_mm"]])
        assert p1["r_ohm"] == pytest.approx(50.0)
        # port2：腔端面 TE10（a 绑 x 宽边、b 绑 y 窄边，exc_dir=z 绑定序）
        assert p2["a_bind_mm"] == pytest.approx(NOM["a_mm"])
        assert p2["b_bind_mm"] == pytest.approx(NOM["b_mm"])
        assert p2["mode"] == "TE10"
        inset = 16.0 * lay["base_mm"]
        assert p2["stop_mm"][2] == pytest.approx(NOM["l_wg_mm"] - inset)
        assert (p2["stop_mm"][2] - p2["start_mm"][2]
                ) == pytest.approx(lay["meas_len_mm"])

    def test_guard_pin_body_empty(self):
        """探针体非正（pin_len≤port_h）显式拒绝（设计约束 docstring 声明）。"""
        with pytest.raises(ValueError, match="探针体非正"):
            _coax_wg_layout(dict(NOM, pin_len_mm=NOM["port_h_mm"]), BAND, 0.4)

    def test_guard_pin_touches_top_wall(self):
        """探针触顶壁短路（pin_len≥b）显式拒绝。"""
        with pytest.raises(ValueError, match="触顶壁"):
            _coax_wg_layout(dict(NOM, pin_len_mm=NOM["b_mm"]), BAND, 0.4)

    def test_guard_pin_wider_than_guide(self):
        """探针截面超波导宽边（2·pin_r≥a）显式拒绝。"""
        with pytest.raises(ValueError, match="超波导宽边"):
            _coax_wg_layout(dict(NOM, pin_r_mm=NOM["a_mm"] / 2), BAND, 0.4)

    def test_guard_backshort_nonpositive(self):
        """背腔距非正显式拒绝。"""
        with pytest.raises(ValueError, match="背腔距非正"):
            _coax_wg_layout(dict(NOM, backshort_mm=0.0), BAND, 0.4)

    def test_guard_probe_misses_cavity(self):
        """探针不进腔（offset 越界：z_pin−pin_r<0 穿背短路板）显式拒绝。"""
        with pytest.raises(ValueError, match="不进腔"):
            _coax_wg_layout(dict(NOM, backshort_mm=0.4), BAND, 0.4)

    def test_guard_probe_enters_port_section(self):
        """探针伸入端口校准段（z_pin+pin_r>l_wg−meas_len）显式拒绝。"""
        with pytest.raises(ValueError, match="端口校准段"):
            _coax_wg_layout(dict(NOM, l_wg_mm=10.0), BAND, 0.4)

    def test_render_rejects_far_field_and_bad_port(self):
        """封闭腔无辐射口径：far_field 显式拒绝；excite_port 越域拒绝。"""
        with pytest.raises(ValueError, match="far_field"):
            render_script(T, dict(NOM), BAND, mesh_resolution_mm=0.4,
                          far_field=True)
        with pytest.raises(ValueError, match="excite_port"):
            render_script(T, dict(NOM), BAND, mesh_resolution_mm=0.4,
                          excite_port=3)


# ─── 3) #212 离线几何审计（exec 几何段 + CSXCAD 实测）────────────────────────

class TestOfflineGeometryAudit:
    def test_two_field_ports_and_binding(self):
        """双场端口：port1=集总桥（R=50、exc 沿 y）、port2=RectWGPort TE10
        （exc 沿 z、kc=π/a_phys 绑定自算——exc_dir=z 绑定序 a→x/b→y）。"""
        scope, _prims = gh.load_geometry(T)
        ports = gh.port_objects(scope)
        assert sorted(ports) == [1, 2]
        p1, p2 = ports[1], ports[2]
        assert type(p1).__name__ == "LumpedPort"
        assert p1.R == 50.0                         # 集总桥 R 单位=Ω（非几何）
        assert int(p1.exc_ny) == 1                  # exc 沿 y（探针轴平行 E 场）
        assert type(p2).__name__ == "RectWGPort"
        assert p2.WG_mode == "TE10"
        assert p2.kc == pytest.approx(math.pi / (NOM["a_mm"] * 1e-3), rel=1e-9)
        assert int(p2.exc_ny) == 2                  # exc 沿 z（波导轴）

    def test_single_network_via_lumped_bridge(self):
        """连通性（探针-波导腔导通路径）：探针柱与腔壁 DC 隔离（隙=port_h
        不接触），唯一耦合路径=探针基集总桥——壁+桥+探针构成 1 个导体网络
        （is_conductor 含 LumpedElement）；桥盒同时 Face 贴腔壁内侧面与针底。"""
        _scope, prims = gh.load_geometry(T)
        conductors, labels = gh.conductor_labels(prims)
        assert len(set(labels)) == 1, (
            "壁+桥+探针须为单导体网络（桥缺失=探针浮空 2 分量）")
        pin = [p for p in conductors if p.prop == "wg_pin"]
        walls = [p for p in conductors if p.prop == "wg_wall"]
        bridge = [p for p in conductors if p.kind == "LumpedElement"]
        assert len(pin) == 1 and len(walls) == 5 and len(bridge) == 1
        # 探针与腔壁无 bbox 接触（集总口隙 port_h 隔离=耦合路径唯一性）
        assert not any(gh.connected(pin[0], w) for w in walls)
        # 桥盒下底面贴壁内侧面（y=−b/2）、上顶面贴针底（y=−b/2+port_h）
        b = bridge[0]
        assert b.lo[1] == pytest.approx(-NOM["b_mm"] / 2 * 1e-3, abs=1e-12)
        assert b.hi[1] == pytest.approx(
            (-NOM["b_mm"] / 2 + NOM["port_h_mm"]) * 1e-3, abs=1e-12)
        assert any(gh.connected(b, w) for w in walls)
        assert gh.connected(b, pin[0])

    def test_probe_inside_cavity(self):
        """探针柱整体在腔内（x/z 居中截面、y 自壁内侧面伸入未触顶壁）——
        探针伸入腔内=唯一场耦合区（FIELD 端口截面的物理有效性）。"""
        _scope, prims = gh.load_geometry(T)
        pin = next(p for p in prims if p.prop == "wg_pin")
        ya0 = (-NOM["b_mm"] / 2 + NOM["port_h_mm"]) * 1e-3
        ya1 = (-NOM["b_mm"] / 2 + NOM["pin_len_mm"]) * 1e-3
        assert pin.lo[1] == pytest.approx(ya0, abs=1e-12)
        assert pin.hi[1] == pytest.approx(ya1, abs=1e-12)
        assert pin.hi[1] < NOM["b_mm"] / 2 * 1e-3          # 未触顶壁
        assert pin.lo[2] > 0.0 and pin.hi[2] < NOM["l_wg_mm"] * 1e-3
        assert abs(pin.lo[0]) < NOM["a_mm"] / 2 * 1e-3

    def test_field_port_sections_contain_conductor(self):
        """FIELD_PORT 口径（审计③同款正面复钉）：两端口盒包围盒内含导体。"""
        scope, prims = gh.load_geometry(T)
        for number, port in gh.port_objects(scope).items():
            lo = np.minimum(np.asarray(port.start, dtype=float),
                            np.asarray(port.stop, dtype=float))
            hi = np.maximum(np.asarray(port.start, dtype=float),
                            np.asarray(port.stop, dtype=float))
            inside = [p for p in prims if gh.is_conductor(p)
                      and bool(np.all(p.hi >= lo - 1e-9))
                      and bool(np.all(p.lo <= hi + 1e-9))]
            assert inside, f"port{number} 截面无导体（模式端口无效）"

    def test_wall_planes_on_mesh_lines(self):
        """全部原语零厚面恰在网格线上（#174 激励体积/面进网格铁律）。"""
        scope, prims = gh.load_geometry(T)
        assert gh.off_mesh_planes(prims, scope) == []

    def test_mesh_min_gap_guard(self):
        """#152 最小线距（全轴 >1µm，无 CFL 塌缩线）。"""
        scope, _prims = gh.load_geometry(T)
        for axis in ("x", "y", "z"):
            ls = np.asarray(scope["mesh"].GetLines(axis), dtype=float)
            assert bool(np.all(np.diff(ls) > 1e-6)), f"{axis} 轴近重合线"

    def test_nominal_params_drive_conductor_geometry(self):
        """八几何参各自扰动改变导体签名（声明即生效；er/h_mm 走材料豁免）。"""
        changed = gh.geometry_changing_params(T, list(TEMPLATE_META[T]["params"]))
        assert changed == set(TEMPLATE_META[T]["params"])

    def test_excitation_wiring_and_station_lines(self):
        """激励以 meta f0 为中心；壁面/探针特征站线显式入网（#198）。"""
        scope, _prims = gh.load_geometry(T)
        ls = {ax: np.asarray(scope["mesh"].GetLines(ax), dtype=float)
              for ax in ("x", "y", "z")}
        assert float(np.min(np.abs(
            ls["x"] - NOM["a_mm"] / 2 * 1e-3))) <= 1e-6, "x=±a/2 未入网"
        assert float(np.min(np.abs(
            ls["y"] + NOM["b_mm"] / 2 * 1e-3))) <= 1e-6, "y=−b/2 未入网"
        assert float(np.min(np.abs(ls["z"] - 0.0))) <= 1e-6, "背短路面未入网"
        assert float(np.min(np.abs(
            ls["z"] - NOM["l_wg_mm"] * 1e-3))) <= 1e-6, "腔端面未入网"
        assert float(scope["F0"]) == pytest.approx(F0_GHZ * 1e9)


# ─── 4) 渲染脚本字面量（单激励口径 + 教程参数回显）───────────────────────────

class TestRenderScriptLiterals:
    def test_excite_port_1_wiring(self):
        """excite_port=1：LumpedPort excite=1 / RectWGPort excite=0，跨口
        校正=sqrt(50/ZL_wg)（wiki 教程 S21 阻抗口径），csv 5 列 schema。"""
        text = render_script(T, dict(NOM), BAND, mesh_resolution_mm=0.4)
        assert "EXCITE_PORT = 1" in text
        assert 'excite=1, priority=5' in text      # port1 桥激励
        assert 'excite=0' in text                  # port2 无源
        assert "np.sqrt(50.0 / _zl_wg)" in text
        assert '"re_" + refl_name' in text
        assert 'mode_name="TE10"' in text
        assert 'a=0.02286' in text and 'b=0.01016' in text   # WR-90 绑定字面
        assert '["MUR", "MUR", "MUR", "MUR", "PML_8", "PML_8"]' in text
        assert "ER = 1.0" in text                  # MATERIAL_VALUE_PARAMS 接线
        assert "fc_te10_hz" in text and "lambda_g_mm" in text

    def test_excite_port_2_wiring(self):
        """excite_port=2：波导口激励（excite=1），跨口校正=sqrt(ZL_wg/50)。"""
        text = render_script(T, dict(NOM), BAND, mesh_resolution_mm=0.4,
                             excite_port=2)
        assert "EXCITE_PORT = 2" in text
        assert "np.sqrt(_zl_wg / 50.0)" in text
        assert 'mode_name="TE10", excite=1' in text


# ─── 5) 注册四件套（#304）────────────────────────────────────────────────────

class TestRegistration:
    def test_registered_same_object_and_tail_position(self):
        from rfauto.adapters import openems_templates as ot

        assert ot.TEMPLATE_META[T] is ot.COAX_WG_META
        assert ot.TEMPLATE_NOMINAL[T] is ot.COAX_WG_NOMINAL
        assert frozenset(ot.TEMPLATE_META) == frozenset(ot.TEMPLATE_NOMINAL)
        # 键集断言（AU-1B4，尾序槽位钉 [-N:] 退役）：尾块相对次序子序列钉——
        # 本批注册时居尾；M-5 varactor_bpf（2026-09-27）尾部追加后退居其前，
        # J2FB ms_ring_patch（2026-09-30）注册于 ms 族段内不动本段；新批次
        # 尾部追加不改块内既有相对次序
        _TAIL_BLOCK = ["pyramid_horn", T, "varactor_bpf"]
        keys = list(ot.TEMPLATE_META)
        assert set(_TAIL_BLOCK) <= set(keys)
        _it = iter(keys)  # 相对次序：块内名字按注册序出现（子序列）
        for _name in _TAIL_BLOCK:
            assert _name in _it, f"注册相对次序漂移：{_name}"
        assert ot._TEMPLATE_PORT_AXES[T] == ("z",)
        assert ot._TEMPLATE_RADIATOR[T] is False
        assert T in ot.COAX_WG_TEMPLATES
        assert T in EXPECTED_TEMPLATES
        # 计数只与单源比对（#247 禁轨内自钉）
        assert len(ot.TEMPLATE_META) == len(EXPECTED_TEMPLATES)

    def test_template_meta_accessor(self):
        meta = template_meta(T)
        assert meta["template"] == T
        assert meta["n_ports"] == 2
        assert meta["f0_ghz"] == pytest.approx(F0_GHZ)
        assert meta["nominal_params"] == COAX_WG_NOMINAL

    def test_geometry_spec_ports_match_meta(self):
        spec = geometry_spec(T, dict(NOM))
        assert len(spec["ports"]) == int(TEMPLATE_META[T]["n_ports"]) == 2
        assert len(spec["boxes"]) == 6   # 预览口径：四壁+背短路板+探针柱

    def test_smoke_note_honest(self):
        """smoke_note 必须如实声明未冒烟与 v1 近似级别（不虚报真机状态）。"""
        note = str(TEMPLATE_META[T].get("smoke_note", ""))
        assert "未冒烟" in note
        assert "近似级别" in note or "近似" in note
        assert "Ph3" in note


# ─── 6) docs meta.yaml 一致性 ────────────────────────────────────────────────

class TestDocsMetaYaml:
    def _data(self) -> dict:
        path = REPO / "docs" / "templates" / T / "meta.yaml"
        assert path.exists(), path
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def test_identity_and_key_sets(self):
        data = self._data()
        assert data["template"] == T
        assert float(data["f0_ghz"]) == pytest.approx(
            float(TEMPLATE_META[T]["f0_ghz"]))
        assert int(data["n_ports"]) == int(TEMPLATE_META[T]["n_ports"])
        assert set(data["params"]) == set(TEMPLATE_META[T]["params"])
        assert set(data["nominal_params"]) == set(TEMPLATE_NOMINAL[T])

    def test_nominal_values_match_src(self):
        data = self._data()
        for key, value in TEMPLATE_NOMINAL[T].items():
            assert float(data["nominal_params"][key]) == pytest.approx(
                value, rel=1e-9), key

    def test_derivation_and_smoke_note_declared(self):
        data = self._data()
        assert "nominal_derivation" in data, "综合链出处须入 meta.yaml"
        assert "smoke_note" in data
        assert "未冒烟" in data["smoke_note"]

    def test_yaml_no_half_width_hash_truncation(self):
        """#324 回归钉：plain scalar 内半角空格+'#' 截断——实读比对防静默注释化。"""
        raw = (REPO / "docs" / "templates" / T / "meta.yaml").read_text(
            encoding="utf-8")
        data = self._data()
        # 关键长字段实读非空（若 '#' 截断，行尾内容会被静默吞掉）
        assert len(str(data["mesh_note"])) > 50
        assert len(str(data["param_semantics"])) > 50
        assert "（#" in raw or "#152" in data["mesh_note"]


# ─── 7) S21 透射通道朝向修复守卫（F1，2026-09-29 根因审计）───────────────────
#
# 根因（docs/audit/oe3_coax_fail_audit_20260929.md §3）：openEMS CalcPort 波
# 分解 uf_inc=沿 port.direction 正向行波、uf_ref=逆向行波。本模板 port2 按
# 自然升序定义（start z < stop z → direction=+1 向外），出腔透射落在
# uf_inc；uf_ref 实测是测量面外短路 stub+PML 回波（−51…−54dB）。旧公式取
# uf_ref 把回波当透射（S21=−54.28dB 假象，三门全红误诊）。
# "port2 uf_ref=到达行波"仅对反向定义端口成立（MSL/CPW/SSL 族 port2 stop
# 指向电路内侧、direction=−1，其 uf_ref 公式自洽，不在本守卫范围）。


def _extract_post_segment(text: str) -> str:
    """渲染脚本截取后处理段（f=linspace…sparams.csv 写盘，不含 summary）。

    站点标记唯一性先断言（防渲染文本漂移静默截错段）。"""
    start = "f = np.linspace(F0 - FC"
    end = "# TE10 截止"
    assert text.count(start) == 1 and text.count(end) == 1, "后处理段标记漂移"
    return text[text.index(start):text.index(end)]


class _SyntheticPort:
    """合成端口桩：uf_inc/uf_ref 频谱与 ZL 直给，CalcPort 空转（零仿真）。"""

    def __init__(self, uf_inc, uf_ref, zl):
        self.uf_inc = np.asarray(uf_inc, dtype=complex)
        self.uf_ref = np.asarray(uf_ref, dtype=complex)
        self.ZL = np.asarray(zl, dtype=complex)

    def CalcPort(self, _path, _f, ref_impedance=None):
        return None


def _forward_port2_stubs(n: int = 201):
    """port1 激励、无损双端口（|S11|²+|S21|²=1）在「port2 朝向向外」分解
    下的合成 u/i 频谱：uf_inc2=出腔透射（大）、uf_ref2=stub+PML 回波（小）。"""
    s11 = 0.3 * np.exp(1j * 0.7)                    # port1 反射（朝向正确）
    s21_phys = np.sqrt(0.91) * np.exp(1j * 1.1)     # 物理透射（功率闭合 0.09+0.91）
    zl = 500.0 * (1.0 + 0.02j)                      # TE10 解析波导阻抗（色散形态）
    pml_echo = 1e-3 * np.exp(1j * 2.3)              # −60dB 量级回波（审计同形态）
    p1 = _SyntheticPort(np.full(n, 1.0 + 0j), np.full(n, s11), 50.0)
    # 模板公式消费 _zl_wg=np.real(ZL)（色散阻抗取实部口径），反推同口径
    corr = np.sqrt(np.real(zl) / 50.0)   # uf_inc2=s21_phys·sqrt(Re(ZL)/50)
    p2 = _SyntheticPort(np.full(n, s21_phys * corr), np.full(n, pml_echo), zl)
    return p1, p2, s11, s21_phys, zl


class TestS21OrientationFix:
    """S21 通道朝向修复守卫：功率守恒主钉 + 朝向混淆负例（#122 不凑绿口径）。"""

    def test_rendered_formula_uses_uf_inc(self):
        """字面钉：渲染脚本 s_tran 取 uf_inc 且旧公式绝迹，审计指针随行。"""
        text = render_script(T, dict(NOM), BAND, mesh_resolution_mm=0.4)
        assert ("s_tran = np.sqrt(50.0 / _zl_wg) * _port2.uf_inc"
                " / _port1.uf_inc") in text
        assert "_port2.uf_ref / _port1.uf_inc" not in text, "旧公式残留"
        assert "docs/audit/oe3_coax_fail_audit_20260929.md" in text

    def test_power_conservation_synthetic(self, tmp_path):
        """守卫主钉（审计 §5 建议）：合成无损双端口喂渲染后处理段（render→
        exec 家法），f0 处 |S11|²+|S21|²∈[0.95,1.05]——透射通道一旦错配
        （回波 1e-3 量级当透射）功率和塌到 0.09，本门一票即抓。"""
        text = render_script(T, dict(NOM), BAND, mesh_resolution_mm=0.4)
        post = _extract_post_segment(text)
        compile(post, "coax_post", "exec")   # #201 语法门
        p1, p2, s11, s21_phys, _zl = _forward_port2_stubs()
        ns = {"np": np, "os": os, "csv": csv,
              "F0": 10e9, "FC": 0.25e9, "EXCITE_PORT": 1,
              "SIM_PATH": "unused", "SCRIPT_DIR": str(tmp_path),
              "_port1": p1, "_port2": p2}
        exec(compile(post, "<coax_post>", "exec"), ns)   # 受控渲染段 exec
        rows = np.genfromtxt(tmp_path / "sparams.csv", delimiter=",",
                             names=True)
        s11_csv = rows["re_S11"] + 1j * rows["im_S11"]
        s21_csv = rows["re_S21"] + 1j * rows["im_S21"]
        i0 = 100   # linspace(F0-FC, F0+FC, 201) 中点=F0
        assert abs(s11_csv[i0] - s11) < 1e-12
        assert abs(s21_csv[i0] - s21_phys) < 1e-9
        pw = abs(s11_csv[i0]) ** 2 + abs(s21_csv[i0]) ** 2
        assert 0.95 <= pw <= 1.05, f"功率守恒出窗：{pw:.4f}"

    def test_orientation_confusion_negative(self):
        """负例钉（朝向混淆即红的两面）：
        (a) 回归面——模板若退回 uf_ref（回波当透射），功率和 0.09 出守卫窗；
        (b) 等价面——port2 反向定义数据（uf_inc↔uf_ref 对换）经 uf_ref 公式
        复现同一物理 S21 且功率守恒：通道必须随朝向选（MSL/CPW/SSL 族反向
        端口取 uf_ref 与本模板取 uf_inc 是同一物理量，勿跨模板"统一"）。"""
        p1, p2, s11, s21_phys, zl = _forward_port2_stubs()
        i0 = 100
        k21 = np.sqrt(50.0 / np.real(zl))   # 模板口径：ZL 取实部
        # (a) 旧公式在正向数据上=回波通道 → 守卫必红
        s21_old = k21 * p2.uf_ref[i0] / p1.uf_inc[i0]
        pw_old = abs(s11) ** 2 + abs(s21_old) ** 2
        assert pw_old < 0.95, "旧公式竟能过守卫（守卫失牙）"
        # (b) 反向端口数据的 uf_ref=正向数据的 uf_inc（CalcPort 分解对换）
        s21_rev = k21 * p2.uf_inc[i0] / p1.uf_inc[i0]
        assert abs(s21_rev - s21_phys) < 1e-9
        assert 0.95 <= abs(s11) ** 2 + abs(s21_rev) ** 2 <= 1.05
