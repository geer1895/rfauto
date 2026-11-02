"""DP-16 C4 端口尺寸收敛前置门单测（合成 fake driver，零真机零网络）。

判据对齐 runs/df6_dp16/criteria.md（预声明）：
- 正例：微带 3 档合成收敛序列 → PASS；
- 负例：合成欠尺寸槽线端口（#254 口径）不收敛序列 → FAIL 不凑 PASS（#122）；
- Zvi 自校恒等式在合成 Zpi/Zpv 上逐位；构造不一致 Zvi → 自校 FAIL；
- 多模/驱动失败/族不可识别 → UNKNOWN。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.service.port_gate_service import (
    FAMILY_LADDERS,
    PortSolvePoint,
    SynthPortDriver,
    family_from_roles,
    ladder_rungs,
    port_gate_from_json,
    run_port_gate,
)

ROLES_MSL = {"w_mm": "line_width_mm"}
ROLES_SLOT = {"w_slot_mm": "gap_width_mm"}


def _run(driver, *, roles=ROLES_MSL, w=3.0, h=1.5, **kw):
    return run_port_gate(
        driver, line_width_mm=w, substrate_h_mm=h, probe_freq_ghz=2.5,
        template="mline", physics_roles=roles, **kw)


# ── 族阶梯查表 ────────────────────────────────────────────────────────────


def test_family_dispatch_by_physics_roles():
    """#154 角色口径：槽缝类换 #254 族、线宽类走微带、未知不猜。"""
    assert family_from_roles(ROLES_SLOT) == "slotline_balanced"
    assert family_from_roles(ROLES_MSL) == "microstrip"
    assert family_from_roles({"shunt_w_mm": "shunt_line_width_mm"}) == "microstrip"
    assert family_from_roles({"foo": "bar"}) == "unknown"
    assert family_from_roles(None) == "unknown"


def test_ladder_geometry_matches_family_rules():
    """微带 3/5/8×w、4×h；槽线族 w+2×margin、h+60（#254 ±60/∓30 口径）。"""
    rungs, ladder = ladder_rungs("microstrip", 3.0, 1.5)
    assert ladder is FAMILY_LADDERS["microstrip"]
    assert [(r.port_width_mm, r.port_height_mm) for r in rungs] == [
        (9.0, 6.0), (15.0, 6.0), (24.0, 6.0)]
    rungs, ladder = ladder_rungs("slotline_balanced", 1.0, 1.524)
    assert [(r.port_width_mm, r.port_height_mm) for r in rungs] == [
        (41.0, 61.524), (81.0, 61.524), (121.0, 61.524)]
    assert ladder.official_note  # 官方 8w/10h 勘误口径随结果返回


def test_ladder_degrades_to_top_two_rungs():
    """超预算降级（max_rungs=2）取阶梯最高两档；1 档不可比较 → 空。"""
    rungs, _ = ladder_rungs("microstrip", 3.0, 1.5, max_rungs=2)
    assert [r.index for r in rungs] == [1, 2]
    rungs, _ = ladder_rungs("microstrip", 3.0, 1.5, max_rungs=1)
    assert rungs == []


# ── 正例/负例/UNKNOWN 判据 ────────────────────────────────────────────────


def test_microstrip_converged_sequence_passes():
    """微带已知例 3 档合成收敛序列 → 全 PASS。"""
    driver = SynthPortDriver(
        z0_sequence=[49.0, 49.8, 50.0],
        s21_db_sequence=[-0.010, -0.008, -0.008])
    rep = _run(driver)
    assert rep["ok"] and rep["verdict"] == "PASS"
    assert rep["checks"]["s21_step_db"] == pytest.approx(0.0)
    assert rep["checks"]["z0_step_rel"] == pytest.approx(0.2 / 50.0)
    assert rep["checks"]["z0_ohm_last"] == pytest.approx(50.0)
    assert rep["budget"]["solves_total"] == 3  # 档数×点频单解
    # 每档 set_variables 换端口面尺寸（阶梯换档钩子）
    assert [v["port_width"] for v in driver.vars_log] == [
        "9.000000mm", "15.000000mm", "24.000000mm"]
    assert all(v["port_height"] == "6.000000mm" for v in driver.vars_log)


def test_undersized_slotline_port_gate_fails():
    """负例（#254 口径）：欠尺寸槽线端口截面 → 阻抗/S21 不收敛 → FAIL。

    #122：门有数值证据必须 FAIL，不凑 PASS。
    """
    driver = SynthPortDriver(
        z0_sequence=[180.0, 210.0, 235.0],
        s21_db_sequence=[-3.2, -2.1, -1.4])
    rep = _run(driver, roles=ROLES_SLOT, w=1.0, h=1.524)
    assert rep["verdict"] == "FAIL"
    assert rep["family"] == "slotline_balanced"
    assert any("|ΔS21|" in r for r in rep["reasons"])
    assert any("|ΔZ0/Z0|" in r for r in rep["reasons"])
    assert rep["checks"]["s21_step_db"] == pytest.approx(0.7)
    assert rep["checks"]["z0_step_rel"] == pytest.approx(25.0 / 235.0)


def test_driver_failure_is_unknown_not_fail():
    """驱动失败/缺数据 → UNKNOWN（无数值证据不冒充 FAIL，#122）。"""
    driver = SynthPortDriver(z0_sequence=[50.0, None],
                             s21_db_sequence=[-1.0, None])
    rep = _run(driver, max_rungs=2)
    assert rep["verdict"] == "UNKNOWN"
    assert any("求解失败/缺数据" in r for r in rep["reasons"])


def test_multimode_port_is_unknown():
    """多模端口 v1 只支持单模准 TEM 族 → 如实 UNKNOWN。"""
    driver = SynthPortDriver(z0_sequence=[50, 50, 50],
                             s21_db_sequence=[-1, -1, -1], n_modes=2)
    rep = _run(driver)
    assert rep["verdict"] == "UNKNOWN"
    assert any("多模" in r for r in rep["reasons"])


def test_unknown_family_is_unknown():
    """physics_roles 无法识别 → UNKNOWN 不猜阶梯（#154）。"""
    driver = SynthPortDriver(z0_sequence=[50] * 3, s21_db_sequence=[-1] * 3)
    rep = _run(driver, roles={"foo": "bar"})
    assert rep["verdict"] == "UNKNOWN"
    assert any("无法识别" in r for r in rep["reasons"])


# ── Zvi 自校恒等式（#356⑤）────────────────────────────────────────────────


def test_zvi_identity_bitwise_exact_on_synthetic_zpi_zpv():
    """Zvi=√(Zpi·Zpv) 精确构造 → 自校逐位 rel_err=0。"""
    driver = SynthPortDriver(z0_sequence=[49.3, 50.0],
                             s21_db_sequence=[-1, -1])
    rep = _run(driver, max_rungs=2)
    assert rep["verdict"] == "PASS"
    for rung in rep["rungs"]:
        chk = rung["zvi_self_check"]
        assert chk["status"] == "PASS"
        assert chk["rel_err"] == 0.0  # 逐位：同式构造零相消


def test_zvi_identity_violation_fails():
    """构造不一致 Zvi → 自校 FAIL（模数据病态/#307 族证据）。"""
    driver = SynthPortDriver(z0_sequence=[50.0, 50.0],
                             s21_db_sequence=[-1, -1],
                             zvi_override={1: 49.0})
    rep = _run(driver, max_rungs=2)
    assert rep["verdict"] == "FAIL"
    chk = rep["rungs"][-1]["zvi_self_check"]
    assert chk["status"] == "FAIL"
    assert chk["rel_err"] == pytest.approx(1.0 / 49.0)


def test_zvi_self_check_handles_missing_and_zero():
    """缺读数 → UNKNOWN；Zvi=0 非物理 → FAIL。"""
    from rfauto.service.port_gate_service import _zvi_self_check

    miss = PortSolvePoint(ok=True, freq_ghz=2.5)
    assert _zvi_self_check(miss)["status"] == "UNKNOWN"
    zero = PortSolvePoint(ok=True, freq_ghz=2.5, zpi_ohm=50, zpv_ohm=50,
                          zvi_ohm=0.0)
    assert _zvi_self_check(zero)["status"] == "FAIL"


# ── de-embed meta 与预算 ──────────────────────────────────────────────────


def test_deembed_meta_records_declared_l_ext():
    """调用方声明的 l_ext_mm 记 meta（消费侧 core/deembed）；未声明=null。"""
    driver = SynthPortDriver(z0_sequence=[50] * 3, s21_db_sequence=[-1] * 3)
    rep = _run(driver, l_ext_mm=1.016)
    assert rep["deembed"]["l_ext_mm"] == pytest.approx(1.016)
    assert "deembed_reference_plane" in rep["deembed"]["method"]
    rep2 = _run(SynthPortDriver(z0_sequence=[50] * 3,
                                s21_db_sequence=[-1] * 3))
    assert rep2["deembed"]["l_ext_mm"] is None


def test_full_sweep_budget_counted_once():
    """终档全扫可选一次：预算=档数+1（study 复用 #158 注记）。"""
    driver = SynthPortDriver(z0_sequence=[50] * 3, s21_db_sequence=[-1] * 3)
    rep = _run(driver, full_sweep_final=True)
    assert rep["budget"]["solves_total"] == 4
    assert rep["budget"]["full_sweep_final"] is True


# ── JSON 进出面 ───────────────────────────────────────────────────────────


def test_port_gate_from_json_synthetic_roundtrip():
    """JSON 进出：合成回放 PASS 且全文 JSON 安全（复杂阻抗 → re/im）。"""
    payload = {
        "driver": "synthetic",
        "line_width_mm": 3.0, "substrate_h_mm": 1.5,
        "probe_freq_ghz": 2.5, "physics_roles": ROLES_MSL,
        "template": "mline",
        "z0_ohm_sequence": [49.0, 49.8, 50.0],
        "s21_db_sequence": [-0.010, -0.008, -0.008],
        "l_ext_mm": 1.016,
    }
    rep = port_gate_from_json(payload)
    assert rep["verdict"] == "PASS"
    text = json.dumps(rep)  # 不抛=JSON 安全（#117 面外消费契约）
    assert '"verdict": "PASS"' in text


def test_port_gate_from_json_refuses_hfss_launch():
    """hfss 驱动 JSON 面不发射：如实 UNKNOWN（真机走脚本对象注入面）。"""
    rep = port_gate_from_json({"driver": "hfss"})
    assert rep["verdict"] == "UNKNOWN"
    assert any("JSON 面不发射" in r for r in rep["reasons"])
    rep2 = port_gate_from_json({"driver": "bogus"})
    assert rep2["ok"] is False and rep2["verdict"] == "UNKNOWN"


def test_hfss_driver_shell_keeps_interface():
    """真机薄壳接口：set_variables 委托 adapter；未连接会话 solve_point
    显式报错（真机 solve_point 实现已回填，2026-09-24 HFSS 轨）。"""
    from rfauto.service.port_gate_service import HfssPortDriver

    class _StubAdapter:
        def __init__(self):
            self.seen = None

        def set_variables(self, vars):
            self.seen = dict(vars)

    stub = _StubAdapter()
    driver = HfssPortDriver(stub, setup_name="Setup1")
    assert driver.driver_label() == "hfss"
    driver.set_variables({"port_width": "24mm"})
    assert stub.seen == {"port_width": "24mm"}
    with pytest.raises(RuntimeError, match="会话未连接"):
        driver.solve_point(2.5)


def test_hfss_driver_solve_point_offline_replay():
    """solve_point 取数链离线回放（df6 v2 口径）：CharImp 三定义换档子解
    → Port Zo 逐定义读取 → PortSolvePoint 对上（伪造边界/post，不启动
    HFSS，只验证换档与解析面）。"""
    import math

    from rfauto.service.port_gate_service import HfssPortDriver

    zo_table = {"Zpi": complex(50.0, 1.0), "Zpv": complex(49.8, 0.5),
                "Zvi": complex(50.2, -0.2)}
    s21 = 0.99 * complex(math.cos(math.radians(-30.0)),
                         math.sin(math.radians(-30.0)))
    state = {"char_imp": "Zpi", "analyzes": 0}

    class _FakeBoundary:
        def __init__(self, name):
            self.name = name
            self.props = {"Modes": {"Mode1": {"CharImp": "Zpi"}}}

        def update(self):
            # 真 HFSS 语义：边界 CharImp 生效 → Port Zo 按新定义读出
            state["char_imp"] = self.props["Modes"]["Mode1"]["CharImp"]
            return True

    class _FakeSol:
        def get_expression_data(self, q, formula="real"):
            cat = q.split("(", 1)[0]
            if cat == "S":
                val = s21.real if formula == "real" else s21.imag
            elif cat == "Gamma":
                val = 1.2 if formula == "real" else 80.0
            else:
                z = zo_table[state["char_imp"]]
                val = z.real if formula == "real" else z.imag
            return [2.5e9], [val]

    class _FakePost:
        def available_quantities_categories(self, **kw):
            assert kw["report_category"] == "Modal Solution Data"
            return ["Gamma", "VSWR", "Port Zo", "S Parameter",
                    "Z Parameter"]

        def available_report_quantities(self, **kw):
            cat = kw["quantities_category"]
            if cat == "S Parameter":
                return ["S(P1,P1)", "S(P2,P1)"]
            if cat == "Port Zo":
                return ["Zo(P1)", "Zo(P2)"]
            if cat == "Gamma":
                return ["Gamma(P1)"]
            return []

        def get_solution_data(self, expressions, setup_sweep_name,
                              report_category):
            assert setup_sweep_name == "Setup1 : LastAdaptive"
            assert report_category == "Modal Solution Data"
            return _FakeSol()

    class _FakeSetup:
        def __init__(self):
            self.props = {"Frequency": "2.5GHz"}

        def update(self):
            self.props["updated"] = True

    class _FakeHfss:
        post = _FakePost()
        boundaries = None  # ClassVar 形态由 __init__ 装配

        def __init__(self):
            self.boundaries = [_FakeBoundary("P1"), _FakeBoundary("P2")]

        def get_setup(self, name):
            assert name == "Setup1"
            return _FakeSetup()

        def analyze(self, setup=None):
            state["analyzes"] += 1
            return True

    fake_hfss = _FakeHfss()

    class _FakeSession:
        hfss = fake_hfss

    calls: list[dict] = []

    class _FakeAdapter:
        session = _FakeSession()

        def set_variables(self, vars):
            calls.append(dict(vars))

    driver = HfssPortDriver(_FakeAdapter(), setup_name="Setup1",
                            port_name="P1", other_port_name="P2")
    driver.set_variables({"port_width": "3.34mm"})
    assert calls == [{"port_width": "3.34mm"}]
    pt = driver.solve_point(2.5)
    assert pt.ok, pt.error
    assert pt.zpi_ohm == zo_table["Zpi"]
    assert pt.zpv_ohm == zo_table["Zpv"]
    assert pt.zvi_ohm == zo_table["Zvi"]
    assert abs(pt.s21_db - (20 * math.log10(0.99))) < 1e-12
    assert abs(pt.s21_deg - (-30.0)) < 1e-9
    assert pt.n_modes == 1
    assert state["analyzes"] == 3  # 三定义子解
    assert all(b.props["Modes"]["Mode1"]["CharImp"] == "Zvi"
               for b in fake_hfss.boundaries)  # 末轮=最后定义
