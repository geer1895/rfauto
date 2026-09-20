"""§10.3 C1 天线族 II：单极子/PIFA/IFA/环形/螺旋/缝隙 六模板单测。

方案行：贴片已锚，向变形
扩展。2026-09-14 起六模板正式注册（原"附加模板"边界升格）：
- 注册态钉：ANTENNA2_META/ANTENNA2_NOMINAL 同对象入 TEMPLATE_META/
  TEMPLATE_NOMINAL（18→25，含 coupled_bpf）；注册四件套 docs/templates/<t>/
  meta.yaml、EXPECTED_TEMPLATES、fake 派发 _antenna2_sparams、template_specs
  _register_antenna2（test_antenna2_registered_in_registry /
  test_antenna2_registration_surface_complete / TestAntenna2FakeDispatch）。
- 闭式设计函数（确定性内核）：λ/4 像理论（monopole）、L 路径式 λ/4
  （PIFA，2026-09-16 定版：居中短路板 L=λ0/(4√εeff(W))，真机两轮实证）、
  短路板态 λ/4（IFA）、C≈λ0 自由空间大环（loop，2026-09-16 改造 a=λ0/4）、
  λ0/4 总线长螺旋（helix）、λ0/2 Booker 对偶缝（slot）——标称值 = 设计函数
  4 位舍入（互检）；fake 谐振 = 设计函数精确逆（antenna2_resonance_ghz，
  往返闭合单测）。
- #212 制度化：render → exec 几何段（FDTD.Run 之前）→ CSXCAD 实测，
  秒级零仿真（字符串门抓不住画法错误）。判据：原语非零体积/进网格
  （含零厚面）、端口盒邻接导体、连通性（环断口/缝隔离/螺旋单路径）、
  z 网格覆盖立体器件、slot 地面留槽 + 底 MUR、loop 自由空间（无板无地、
  底 MUR、域 z 向下延 λ0/4、nf2ff 六面全包）。
- 真机冒烟判读（runs/antenna2_smoke，2026-09-14/16）见 openems_templates
  ANTENNA2_META 段注与 docs/templates/<t>/meta.yaml smoke_note：monopole/
  ifa/slot PASS，pifa 旧通式标称 FAIL → L 路径式定版（override 17.08 PASS）、
  loop 贴地 FAIL → 自由空间 v2、helix FAIL（口径，扩带/HFSS 仲裁），不凑绿。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
REPO = Path(__file__).resolve().parents[2]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rfauto.adapters import openems_templates as ot
from tests.unit import _geometry_audit_helpers as gh

MESH_MM = 0.4
BAND = (2.15, 2.65)
EXPECTED_PORT_COUNT = {"monopole": 1, "pifa": 1, "ifa": 1,
                       "loop": 1, "helix": 1, "slot": 2}


def _load(template: str, params: dict | None = None,
          mesh_mm: float = MESH_MM):
    """渲染 antenna2 模板 → exec 几何段 → (脚本作用域, 原语列表)。"""
    resolved = dict(params if params is not None
                    else ot.ANTENNA2_NOMINAL[template])
    text = ot.render_script(template, resolved, BAND,
                            mesh_resolution_mm=mesh_mm)
    head = text[: text.index("FDTD.Run(")]
    scope: dict = {"__name__": "__main__",
                   "__file__": str(REPO / "_antenna2_audit_sim.py")}
    exec(compile(head, "antenna2_audit", "exec"), scope)
    return scope, gh.extract_primitives(scope["CSX"])


# ─── 正式注册（2026-09-14：原"附加不注册"边界升格）─────────────────────────

def test_antenna2_registered_in_registry():
    """六模板已正式注册：同对象入两表；渲染四链路键保持。"""
    for t in ot.ANTENNA2_TEMPLATES:
        assert ot.TEMPLATE_META[t] is ot.ANTENNA2_META[t], t
        assert ot.TEMPLATE_NOMINAL[t] is ot.ANTENNA2_NOMINAL[t], t
        assert t in ot._TEMPLATE_PORT_AXES, t
        assert ot._TEMPLATE_RADIATOR[t] is True, t
        meta = ot.template_meta(t)
        assert meta["template"] == t
        assert meta["f0_ghz"] == 2.4
        assert meta["n_ports"] == EXPECTED_PORT_COUNT[t]
        assert meta["nominal_params"] == ot.ANTENNA2_NOMINAL[t]
        # 声明参数集 = 名义参数集（无幽灵/无漏声明）
        assert set(meta["params"]) == set(ot.ANTENNA2_NOMINAL[t]), t
        assert ot.antenna2_meta(t)["nominal_params"] == ot.ANTENNA2_NOMINAL[t]
    with pytest.raises(KeyError):
        ot.antenna2_meta("patch")
    # 注册表条目集闭合：18 + coupled_bpf + 6 = 25 → +§C3 三模板 28 → +C9 传输线
    # 族 II 两模板（cps/suspended_stripline，2026-09-15）= 30 → +§C2 阵列族三模板
    # （patch_array_1x4/2x2/series，2026-09-15）= 33 → +§C4 耦合器族 II 三模板
    # （cline_coupler/branchline_2sect/lange，2026-09-16）= 36 → +WP2.5 过渡族
    # 两模板（msl_cpw/sma_launcher，2026-09-16）= 38 → +槽线族四模板（slotline/
    # slotline_lumped/msl_slot_transition/marchand_balun，2026-09-18）= 42 →
    # +hairpin_alt 交替取向发夹线（2026-09-18）= 43
    # （单源计数=审计文件 EXPECTED_TEMPLATES，#247 禁轨内自钉）
    from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES as _ET

    assert frozenset(ot.TEMPLATE_META) == frozenset(ot.TEMPLATE_NOMINAL)
    assert len(ot.TEMPLATE_META) == len(_ET)
    # slot 走 y 边界 PML（MSL 端口），其余集总馈全 MUR（patch 口径）
    assert ot._TEMPLATE_PORT_AXES["slot"] == ("y",)
    for t in ("monopole", "pifa", "ifa", "loop", "helix"):
        assert ot._TEMPLATE_PORT_AXES[t] == (), t


def test_antenna2_registration_surface_complete():
    """注册四件套同步：docs meta.yaml ×6 / EXPECTED_TEMPLATES / template_specs
    / geometry_spec 预览端口数；fake 派发见 TestAntenna2FakeDispatch。"""
    import yaml

    from rfauto.models.template_spec import TEMPLATE_SPECS
    from rfauto.models.template_specs import bootstrap_template_specs
    from tests.unit.test_template_geometry_audit import EXPECTED_TEMPLATES

    bootstrap_template_specs()
    # 单源计数（#247：禁轨内自钉，只与审计文件单源比对，不钉字面；
    # 2026-09-18 slotline 族四模板注册 38→42、hairpin_alt 注册 42→43 实证）
    assert len(ot.TEMPLATE_META) == len(EXPECTED_TEMPLATES)
    for t in ot.ANTENNA2_TEMPLATES:
        data = yaml.safe_load(
            (REPO / "docs" / "templates" / t / "meta.yaml")
            .read_text(encoding="utf-8"))
        assert data["template"] == t
        assert float(data["f0_ghz"]) == pytest.approx(2.4, rel=1e-12)
        assert int(data["n_ports"]) == EXPECTED_PORT_COUNT[t]
        assert list(data["params"]) == list(ot.ANTENNA2_META[t]["params"]), t
        assert data["nominal_params"] == ot.ANTENNA2_NOMINAL[t], t
        assert "smoke_note" in data, f"{t}: 真机冒烟判读须入 meta.yaml"
        assert t in EXPECTED_TEMPLATES
        spec = TEMPLATE_SPECS.get(t)
        assert spec.meta["n_ports"] == EXPECTED_PORT_COUNT[t]
        assert callable(TEMPLATE_SPECS.component(t, "render_script"))
        assert callable(TEMPLATE_SPECS.component(t, "fake_model"))
        assert spec.hfss_plugin is None
        # 综合入口：谐振尺寸 = 闭式设计函数（再生 == NOMINAL 4 位常数）
        draft = TEMPLATE_SPECS.draft_recipe(t, f0_ghz=2.4)
        got = {k: v["value"] for k, v in draft["params"].items()}
        assert got == ot.ANTENNA2_NOMINAL[t], t
        # UI 预览端口数与 meta 一致（slot 2、其余 1）
        spec_geo = ot.geometry_spec(t, dict(ot.ANTENNA2_NOMINAL[t]))
        assert len(spec_geo["ports"]) == EXPECTED_PORT_COUNT[t], t
        names = [b["name"] for b in spec_geo["boxes"]]
        # monopole/helix 无介质板（像理论）；loop 自由空间无板无地（2026-09-16）
        assert ("substrate" in names) == (t not in ("monopole", "helix", "loop")), t
        assert ("ground" in names) == (t not in ("slot", "loop")), t
    roles = dict(TEMPLATE_SPECS.get("loop").physics_roles)
    assert roles["loop_side_mm"] == "resonator_length_mm"
    assert roles["loop_gap_mm"] == "gap_width_mm"


class TestAntenna2FakeDispatch:
    """fake 派发：设计函数精确逆 + 一阶谐振电路（设计口径裁判，不为真机凑绿）。"""

    F = np.linspace(1.9, 2.9, 401)

    def test_resonance_is_exact_inverse_of_design_functions(self):
        from rfauto.adapters.fake_adapter import antenna2_resonance_ghz

        for t in ot.ANTENNA2_TEMPLATES:
            # 标称几何（设计函数 4 位舍入）→ 逆式回到 2.4GHz（舍入级误差）
            assert antenna2_resonance_ghz(t, ot.ANTENNA2_NOMINAL[t]) == \
                pytest.approx(2.4, rel=2e-5), t
        # 非标称点往返：f0=3.1 设计 → 逆式回 3.1（各模板独立式）
        f0 = 3.1
        cases = {
            "monopole": {"mon_len_mm": ot.monopole_len_mm(f0)},
            "pifa": {"pifa_l_mm": ot.pifa_l_mm(f0, 8.0, 2.0),
                     "pifa_w_mm": 8.0, "pifa_ws_mm": 2.0},
            "ifa": {"ifa_arm_mm": ot.ifa_arm_len_mm(f0, 1.0), "ifa_w_mm": 1.0},
            "loop": {"loop_side_mm": ot.loop_side_mm(f0, 1.0), "loop_w_mm": 1.0},
            "helix": {"helix_d_mm": 2.0, "helix_turns": 2,
                      "helix_pitch_mm": ot.helix_pitch_mm(f0, 2.0, 2)},
            "slot": {"slot_l_mm": ot.slot_len_mm(f0)},
        }
        for t, params in cases.items():
            assert antenna2_resonance_ghz(t, params, eps_eval_ghz=f0) == \
                pytest.approx(f0, rel=1e-9), t

    def test_single_port_family_dip_at_resonance_and_scale_law(self):
        from rfauto.adapters.fake_adapter import _antenna2_sparams

        for t in ("monopole", "pifa", "ifa", "loop", "helix"):
            s = _antenna2_sparams(self.F, t, ot.ANTENNA2_NOMINAL[t])
            assert s.shape == (len(self.F), 1, 1)
            s11 = 20 * np.log10(np.abs(s[:, 0, 0]))
            assert float(self.F[np.argmin(s11)]) == pytest.approx(2.4, abs=0.003)
            assert float(s11.min()) < -10.0
            assert float(np.max(np.abs(s[:, 0, 0]))) <= 1.0 + 1e-12
        # 尺度律：谐振尺寸 ×1.1 ⇒ 谷位 ÷1.1（数据工厂语义：尺寸是唯一自由度）
        p = dict(ot.ANTENNA2_NOMINAL["monopole"])
        p["mon_len_mm"] *= 1.1
        s = _antenna2_sparams(self.F, "monopole", p)
        f_dip = float(self.F[np.argmin(np.abs(s[:, 0, 0]))])
        assert f_dip == pytest.approx(2.4 / 1.1, abs=0.003)

    def test_slot_two_port_radiation_notch(self):
        from rfauto.adapters.fake_adapter import _antenna2_sparams

        s = _antenna2_sparams(self.F, "slot", ot.ANTENNA2_NOMINAL["slot"])
        assert s.shape == (len(self.F), 2, 2)
        s21 = 20 * np.log10(np.abs(s[:, 1, 0]))
        assert float(self.F[np.argmin(s21)]) == pytest.approx(2.4, abs=0.003)
        assert float(s21.min()) < -12.0          # 辐射凹（真机锚签名量级）
        # 冒烟判据同款：凹 ≤ 带底电平 −6dB（Q=10 一阶宽凹，带底 −4.0dB 与真机
        # −4.07dB 同量级，非拟合）
        assert float(s21.min()) <= float(s21[0]) - 6.0
        # 互易 + 辐射功率 = 1 − |S11|² − |S21|² ≥ 0（有耗=辐射，非增益）
        assert float(np.max(np.abs(s[:, 0, 1] - s[:, 1, 0]))) < 1e-12
        rad = 1.0 - np.abs(s[:, 0, 0]) ** 2 - np.abs(s[:, 1, 0]) ** 2
        assert float(rad.min()) >= -1e-12 and float(rad.max()) > 0.2

    def test_fake_adapter_dispatch_all_six(self):
        from rfauto.adapters.fake_adapter import FakeAdapter

        for t in ot.ANTENNA2_TEMPLATES:
            ad = FakeAdapter(model_type=t, f0_ghz=2.4, freq_ghz=(1.9, 2.9, 101))
            ad.connect({})
            ad.set_variables({k: str(v) for k, v in ot.ANTENNA2_NOMINAL[t].items()})
            ad.build_and_setup(lambda a: None, None)
            assert ad.solve("Setup1").success, t
            net = ad.get_sparams()
            assert net.s.shape[1:] == ((2, 2) if t == "slot" else (1, 1)), t
        # 变量驱动：helix_turns 走整数解析、螺距缩短 ⇒ 总线长缩短 ⇒ 谷位上移
        # （k_helix 定版 2026-09-17：f=k·c/(4·wire)，wire=28mm → 3.644GHz，扫频扩到 4.5）
        ad = FakeAdapter(model_type="helix", f0_ghz=2.4, freq_ghz=(1.9, 4.5, 521))
        ad.connect({})
        ad.set_variables({"helix_turns": "2", "helix_pitch_mm": "2.0"})
        ad.build_and_setup(lambda a: None, None)
        ad.solve("Setup1")
        net = ad.get_sparams()
        f_dip = float(net.f[np.argmin(np.abs(net.s[:, 0, 0]))] / 1e9)
        assert f_dip == pytest.approx(
            ot.K_HELIX * 299.792458 / (4 * (4 * 3 * 2 + 2 * 2.0)), abs=0.006)

    def test_fake_validation(self):
        from rfauto.adapters.fake_adapter import antenna2_resonance_ghz

        with pytest.raises(ValueError):
            antenna2_resonance_ghz("monopole", {"mon_len_mm": 0.0})
        with pytest.raises(ValueError):
            antenna2_resonance_ghz("helix", {"helix_d_mm": 3.0, "helix_turns": 0,
                                             "helix_pitch_mm": 3.0})
        with pytest.raises(ValueError):
            antenna2_resonance_ghz("nope", {})


# ─── 闭式设计函数（确定性内核；标称值 = 设计函数 4 位舍入）──────────────────

def test_nominal_matches_design_functions():
    f0 = 2.4
    assert round(ot.monopole_len_mm(f0), 4) == 31.2284
    # pifa L 路径式定版（2026-09-16）：λ0/(4√εeff(8mm)=3.3435)=17.0785（旧通式
    # 11.0785 真机 FAIL）；loop 自由空间 a=λ0/4=31.2284（旧贴地 λg/4=18.5515）
    assert round(ot.pifa_l_mm(f0, 8.0, 2.0), 4) == 17.0785
    assert round(ot.ifa_arm_len_mm(f0, 1.0), 4) == 18.5515
    assert round(ot.loop_side_mm(f0, 1.0), 4) == 31.2284
    # helix k_helix 定版（2026-09-17 HFSS 同几何仲裁 AGREE 1.44%）：p=(1.3615·λ0/4−24)/2
    # =9.2587（旧 λ0/4 口径 3.6142 真机 f_x 3.31GHz≠2.4）
    assert round(ot.helix_pitch_mm(f0, 3.0, 2), 4) == 9.2587
    assert ot.K_HELIX == 1.3615
    assert round(ot.slot_len_mm(f0, 3.66), 4) == 40.9168
    for t in ot.ANTENNA2_TEMPLATES:
        assert ot.ANTENNA2_NOMINAL[t], t


def test_design_function_identities_and_guards():
    # PIFA L 路径式恒等回代：L = λ0/(4√εeff(W))（HJ 独立正向；W/Ws 不进谐振式）
    l_mm = ot.pifa_l_mm(2.4, 8.0, 2.0)
    quarter = ot._ANT2_C_MM_GHZ / (
        4.0 * 2.4 * np.sqrt(ot._ant2_eps_eff(8.0, 2.4, 3.66, 0.508)))
    assert l_mm == pytest.approx(quarter, abs=1e-9)
    assert ot.pifa_l_mm(2.4, 8.0, 4.0) == pytest.approx(l_mm, abs=1e-12)   # Ws 无关
    # loop 自由空间恒等：a = λ0/4（与 monopole 同数），对 w/εr/h 不敏感（εeff→1）
    assert ot.loop_side_mm(2.4, 1.0) == pytest.approx(ot.monopole_len_mm(2.4), abs=1e-12)
    assert ot.loop_side_mm(2.4, 3.0, er=10.2, h_mm=1.0) == \
        pytest.approx(ot.loop_side_mm(2.4, 1.0), abs=1e-12)
    # εeff 合理域（1, εr）
    for w in (1.0, 8.0):
        eps = ot._ant2_eps_eff(w, 2.4, 3.66, 0.508)
        assert 1.0 < eps < 3.66
    # 单调性：频率↑ 尺寸↓；εr↑ 缝长↓（介质加载缩尺）
    assert ot.ifa_arm_len_mm(3.0, 1.0) < ot.ifa_arm_len_mm(2.4, 1.0)
    assert ot.slot_len_mm(2.4, 3.66) < ot.slot_len_mm(2.4, 2.2)
    # 守卫：非法输入显式报错（不静默）
    with pytest.raises(ValueError):
        ot.monopole_len_mm(0.0)
    with pytest.raises(ValueError):
        ot.pifa_l_mm(2.4, 8.0, 0.0)      # Ws 须正（守卫仍在，虽不进谐振式）
    with pytest.raises(ValueError):
        ot.loop_side_mm(2.4, 0.0)
    with pytest.raises(ValueError):
        ot.helix_pitch_mm(2.4, 5.5, 2)   # 4·5.5·2=44mm > k_helix·λ0/4=42.52 → p<0
    with pytest.raises(ValueError):
        ot.slot_len_mm(2.4, 0.5)         # εr < 1
    with pytest.raises(ValueError):
        ot._ant2_layout("nope", {})


def test_helix_layout_wire_length_is_quarter_wave():
    """staircase 螺旋总线长 = 4·d·N + N·p = λ0/4（单导线连续路径）。"""
    nom = ot.ANTENNA2_NOMINAL["helix"]
    lay = ot._ant2_layout("helix", nom)
    total = 0.0
    d0, p0 = nom["helix_d_mm"], nom["helix_pitch_mm"]
    for (_prop, nm, x0, y0, z0, x1, y1, z1) in lay["boxes"]:
        ext = (abs(x1 - x0), abs(y1 - y0), abs(z1 - z0))
        assert min(ext) <= nom["helix_w_mm"] + 1e-9, \
            f"螺旋段 {nm} 过厚（非薄板/细条）: ext={ext}"
        # 中心线行程：直段=d；短竖板=p/4；D 板=y 行程 d + z 爬升 p/4
        if nm.endswith(("_a", "_b", "_c")):
            total += d0
        elif nm.endswith(("_ab", "_bc", "_cd", "riser_base")):
            total += p0 / 4.0
        elif nm.endswith("_d"):
            total += d0 + p0 / 4.0
        else:
            raise AssertionError(f"未知螺旋段 {nm}")
    d, n, p = nom["helix_d_mm"], nom["helix_turns"], nom["helix_pitch_mm"]
    assert total == pytest.approx(4 * d * n + n * p, rel=1e-9)
    # 总线长 = k_helix·λ0/4（2026-09-17 HFSS 仲裁定版；旧口径 λ0/4=monopole_len）
    assert 4 * d * n + n * p == pytest.approx(
        ot.K_HELIX * ot.monopole_len_mm(2.4), rel=1e-3)


# ─── #212 制度化：CSXCAD 实测离线审计（六模板参数化）─────────────────────────

@pytest.mark.parametrize("template", sorted(ot.ANTENNA2_TEMPLATES))
def test_primitives_nonzero_and_in_mesh(template):
    scope, prims = _load(template)
    metal = [p for p in prims if p.kind == "Metal"]
    diel = [p for p in prims if p.kind == "Material"]
    assert metal, f"{template}: 无金属原语"
    for p in metal:
        assert int(np.sum(p.extent[:2] > 1e-12)) >= 1, \
            f"{template}: 零退化金属盒 {p.prop} ext={p.extent}"
    if template in ("monopole", "helix"):
        assert not diel, f"{template}: 立体器件无介质板（像理论口径）"
    elif template == "loop":
        assert not diel, f"{template}: 自由空间环无介质板（dipole 口径，2026-09-16）"
    else:
        assert diel, f"{template}: 缺介质原语"
    # 零厚面必须落网格线（#198/#174 家族：不进网格=原语丢失/激励坍缩）
    assert gh.off_mesh_planes(prims, scope) == [], \
        f"{template}: 零厚面未入网 {gh.off_mesh_planes(prims, scope)}"


@pytest.mark.parametrize("template", sorted(ot.ANTENNA2_TEMPLATES))
def test_ports_touch_conductor_and_excitation_nonzero(template):
    scope, prims = _load(template)
    ports = gh.port_objects(scope)
    assert len(ports) == EXPECTED_PORT_COUNT[template], \
        f"{template}: 端口对象数 {len(ports)}"
    conductors = [p for p in prims if gh.is_conductor(p)]
    for nr, port in ports.items():
        start = np.asarray(port.start, dtype=float)
        stop = np.asarray(port.stop, dtype=float)
        ext = np.abs(stop - start)
        assert np.max(ext) > 1e-9, f"{template} port{nr}: 退化端口"
        # 端口盒（含零厚面）邻接至少一个导体原语（激励有金属性回路）
        box = SimpleNamespace(prop=f"port{nr}", kind="Metal",
                              lo=np.minimum(start, stop),
                              hi=np.maximum(start, stop))
        assert any(gh.connected(box, c) for c in conductors), \
            f"{template} port{nr}: 端口盒不邻接任何导体（悬空馈电）"


def test_monopole_helix_z_mesh_covers_element():
    """立体器件：布局 z 面全部入网 + 域顶 ≥ 元件顶 + AIR_TOP（元不出域）。"""
    for t in ("monopole", "helix"):
        scope, _ = _load(t)
        lay = ot._ant2_layout(t, ot.ANTENNA2_NOMINAL[t])
        z_lines = gh.mesh_lines(scope, "z")
        for z_mm in lay["z_lines_mm"]:
            gap = float(np.min(np.abs(z_lines - z_mm * 1e-3)))
            assert gap <= 1e-6, f"{t}: 布局 z={z_mm}mm 未入网"
        air_top = 3e8 / (2.65e9) / 4.0
        assert float(np.max(z_lines)) >= lay["element_top_mm"] * 1e-3 + air_top


def test_loop_gap_not_short_and_ring_connected():
    """环形：底边断口存在（两端面不接触）且五段环带同一连通分量。"""
    _scope, prims = _load("loop")
    names = {p.prop for p in prims if p.kind == "Metal"}
    assert names == {"loop_top", "loop_left", "loop_right",
                     "loop_bot_l", "loop_bot_r"}, names
    conductors = [p for p in prims if gh.is_conductor(p)]
    labels = gh.component_labels(conductors)
    by_name = {p.prop: p for p in conductors}
    # 断口：bot_l 右端面 x=−g/2、bot_r 左端面 x=+g/2，包围盒不相交
    bl, br = by_name["loop_bot_l"], by_name["loop_bot_r"]
    g = ot.ANTENNA2_NOMINAL["loop"]["loop_gap_mm"] * 1e-3
    assert bl.hi[0] == pytest.approx(-g / 2, abs=1e-9)
    assert br.lo[0] == pytest.approx(+g / 2, abs=1e-9)
    assert not gh.connected(bl, br), "环形断口塌缩=DC 短路"
    # 绕行连续：五段全在同一金属分量（断口只断底边、绕行走左右竖边）
    assert len(set(labels)) == 1, f"环带分裂：{len(set(labels))} 分量"


def test_loop_free_space_render_no_ground_no_substrate():
    """loop 自由空间改造（2026-09-16）：环面 z=0、六面 MUR（底非 PEC）、无介质
    原语、域 z 向下延 ≥ AIR_TOP、far_field 走六面全包 nf2ff 盒（dipole 同款）。

    动因：旧 z=h 贴 PEC 地口径真机 R=0.56Ω（镜像反向电流抵消辐射）。
    """
    params = dict(ot.ANTENNA2_NOMINAL["loop"])
    text = ot.render_script("loop", params, BAND, mesh_resolution_mm=MESH_MM)
    assert 'FDTD.SetBoundaryCond(["MUR", "MUR", "MUR", "MUR", "MUR", "MUR"])' in text
    assert 'CSX.AddMaterial("substrate"' not in text
    scope, prims = _load("loop")
    assert not [p for p in prims if p.kind == "Material"]
    for p in prims:
        if p.kind == "Metal":
            assert abs(p.lo[2]) <= 1e-12 and abs(p.hi[2]) <= 1e-12, \
                f"loop 环面须在 z=0（自由空间口径）: {p.prop} z=[{p.lo[2]},{p.hi[2]}]"
    port = gh.port_objects(scope)[1]
    assert abs(float(np.asarray(port.start)[2])) <= 1e-12
    z_lines = gh.mesh_lines(scope, "z")
    air_top = 3e8 / (2.65e9) / 4.0
    assert float(np.min(z_lines)) <= -air_top + 1e-9, "域未向下延 λ0/4"
    assert float(np.max(z_lines)) >= air_top - 1e-9
    lay = ot._ant2_layout("loop", params)
    assert lay["substrate"] is False and lay["ground"] is False
    assert lay["air_below"] is True
    # 设计式即标称：a = λ0/4（自由空间，εeff→1）
    assert params["loop_side_mm"] == round(ot.loop_side_mm(2.4), 4)
    # far_field：六面全包分支（盒 z 自 −AIR_TOP 起，非接地 z=0 起）
    ff = ot.render_script("loop", params, BAND, mesh_resolution_mm=MESH_MM,
                          far_field=True)
    assert "-AIR_TOP + _FF_MARGIN" in ff and "六面全包" in ff
    head = ff[: ff.index("FDTD.Run(")]
    ff_scope: dict = {"__name__": "__main__", "__file__": "_ff_loop_sim.py"}
    exec(compile(head, "ff_loop_audit", "exec"), ff_scope)


def test_pifa_ifa_feed_pin_and_short_touch_ground_line():
    """PIFA/IFA：短路板触地（z=0）、馈针=LumpedPort 本身（顶触贴片/臂 z=h）。

    口径钉（2026-09-14）：不再另画与端口同体积的金属针盒——真机 v1（有针盒）
    /v2（无针盒）S11 逐点一致，针盒对结果无影响，去掉只为消除"金属盖端口
    体元"的口径歧义（patch 官方口径=端口即探针）。判据：任何金属原语与端口
    盒的三维交集体积必须为零（仅允许面接触）。
    """
    for t in ("pifa", "ifa"):
        scope, prims = _load(t)
        by_name = {p.prop: p for p in prims if p.kind == "Metal"}
        radiator_name = f"{t}_patch" if t == "pifa" else f"{t}_arm"
        assert set(by_name) == {radiator_name, f"{t}_short"}, set(by_name)
        radiator = by_name[radiator_name]
        short = by_name[f"{t}_short"]
        assert short.lo[2] <= 1e-9, f"{t}: 短路板未触地"
        assert gh.connected(radiator, short), \
            f"{t}: 贴片/臂与短路板不连通"
        port = gh.port_objects(scope)[1]
        start = np.asarray(port.start, dtype=float)
        stop = np.asarray(port.stop, dtype=float)
        pbox = SimpleNamespace(prop="port1", kind="Metal",
                               lo=np.minimum(start, stop),
                               hi=np.maximum(start, stop))
        assert pbox.lo[2] <= 1e-12 and abs(pbox.hi[2] - radiator.lo[2]) <= 1e-12, \
            f"{t}: 端口须自地面 z=0 立到辐射体面 z=h"
        assert gh.connected(pbox, radiator), f"{t}: 端口顶未触辐射体"
        for name, metal in by_name.items():
            overlap = np.minimum(pbox.hi, metal.hi) - np.maximum(pbox.lo, metal.lo)
            volume = float(np.prod(np.maximum(overlap, 0.0)))
            assert volume <= 1e-30, \
                f"{t}: 金属 {name} 与端口体积重叠 {volume}（激励被 PEC 吞）"


def test_slot_ground_gap_and_dc_isolation():
    """缝隙：地面留槽（槽中心无金属）、馈线与地面 DC 隔离（槽隔离判据）。"""
    _scope, prims = _load("slot")
    props = {p.prop for p in prims if p.kind == "Metal"}
    assert props == {"slot_gnd", "slot_feed"}, props
    nom = ot.ANTENNA2_NOMINAL["slot"]
    lx, wy = nom["slot_l_mm"] / 2 * 1e-3, nom["slot_w_mm"] / 2 * 1e-3
    # 槽中心无金属（原语包围盒均不覆盖 (0,0,0)）
    for p in prims:
        if not gh.is_conductor(p):
            continue
        inside = bool(np.all(p.lo - 1e-12 <= np.array([0.0, 0.0, 0.0]))
                      and np.all(p.hi + 1e-12 >= np.array([0.0, 0.0, 0.0])))
        assert not inside, f"slot: 金属覆盖槽中心 {p.prop}"
    conductors = [p for p in prims if gh.is_conductor(p)]
    labels = gh.component_labels(conductors)
    comp = {}
    for p, lb in zip(conductors, labels, strict=True):
        comp.setdefault(p.prop, set()).add(lb)
    assert len(comp["slot_gnd"]) == 1, "四块地面拼合应同一分量"
    assert comp["slot_gnd"].isdisjoint(comp["slot_feed"]), \
        "馈线与地面经槽 DC 短路（槽被金属桥接）"
    # 缝长两侧端面落在 ±L/2（闭式缝长进几何；gnd_xm = 右端面 <0 的那块地）
    xm = next(p for p in conductors
              if p.prop == "slot_gnd" and p.hi[0] < 0.0)
    assert xm.hi[0] == pytest.approx(-lx, abs=1e-9)
    assert abs(xm.hi[1] - xm.lo[1]) == pytest.approx(wy * 2, abs=1e-9)


def test_helix_single_path_staircase_connectivity():
    """螺旋：全部段一连通分量（单导线连续 staircase，无双并联回路）。"""
    _scope, prims = _load("helix")
    conductors = [p for p in prims if gh.is_conductor(p)]
    labels = gh.component_labels(conductors)
    assert len(set(labels)) == 1, \
        f"螺旋分裂为 {len(set(labels))} 个金属分量（staircase 断链）"


def test_perturbed_params_change_geometry():
    """参数驱动几何：任一名义参数扰动必须改变导体签名（防幽灵参数）。"""
    for t in ot.ANTENNA2_TEMPLATES:
        nom = dict(ot.ANTENNA2_NOMINAL[t])
        base = gh.conductor_signature(_load(t, nom)[1])
        drift = []
        for key, val in nom.items():
            if key == "helix_turns":
                pert = dict(nom)
                pert[key] = int(val) + 1
            elif isinstance(val, int) and not isinstance(val, bool):
                pert = dict(nom)
                pert[key] = val * 2
            else:
                pert = dict(nom)
                pert[key] = float(val) * 1.15
            try:
                sig = gh.conductor_signature(_load(t, pert)[1])
            except ValueError:
                # 守卫拒超界值（如 loop gap ≥ side）——换温和扰动重试
                pert = dict(nom)
                pert[key] = float(val) * 1.02 if key != "helix_turns" \
                    else int(val) + 1
                sig = gh.conductor_signature(_load(t, pert)[1])
            if sig != base:
                drift.append(key)
        assert set(drift) == set(nom), \
            f"{t}: 未驱动几何的参数 {set(nom) - set(drift)}（幽灵参数）"


def test_render_far_field_ground_plane_branch():
    """far_field=True：接地辐射族走 patch 型 NF 盒（z 底=0），渲染可执行。"""
    for t in ("pifa", "monopole", "slot"):
        params = dict(ot.ANTENNA2_NOMINAL[t])
        text = ot.render_script(t, params, BAND, mesh_resolution_mm=MESH_MM,
                                far_field=True)
        assert "CreateNF2FFBox" in text
        head = text[: text.index("FDTD.Run(")]
        scope: dict = {"__name__": "__main__", "__file__": "_ff_sim.py"}
        exec(compile(head, "ff_audit", "exec"), scope)
