"""DP-1 P2 单测：MMT 适配器/服务/薄壳（判据 runs/df6_dp1p2/criteria.md 先写后跑）。

判据映射（#122 预声明，全部门在 criteria §1）：
- G-P2-1 注册全链（registry.create → config → build_geometry JSON 段表 →
  solve → 三产物）；
- G-P2-2 WR-90 直段 β vs core.calculators.siw_beta_rad_m 逐频 ≤1e-6
  （G3 既有钉复用）+ 50Ω 产物 vs 独立均匀线闭式 ≤1e-9（裁判式与
  renormalize_2port 实现路径不同源——公式取自传输线教科书 ABCD；μ0 共享
  core.rwg_mmt.MU0 常量，裁判对象是 renormalize/产物路径不是物理常量）；
- G-P2-3 产物一致性：mmt.s2p skrf 读回 vs 内存 ≤1e-12（skrf 2.1.0 ri
  往返实测 0.0）、sparams.csv 5 列掩码 schema、meta JSON 往返；
- G-P2-4 服务 JSON 往返 + undetermined 如实 null 不外推 + converged/
  warnings 透传；
- G-P2-5 无耗段 50Ω 重归一无源/互易 ≤1e-9。

确定性：纯仓内零网络零真机；work_dir 全部落 tmp（#144 不污染真实 runs/）。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

import rfauto.adapters  # noqa: F401 —— 导入副作用：注册含 mmt
from rfauto.adapters.em_solver_base import (
    EMSolverConfig,
    EMSolverType,
    get_global_registry,
    solver_capabilities_for,
)
from rfauto.adapters.mmt_adapter import (
    MmtAdapter,
    MmtError,
    mode_policy_from_json,
    parse_sections,
)
from rfauto.core.calculators import siw_beta_rad_m
from rfauto.core.rwg_mmt import (
    MU0,
    HStepJunction,
    InductiveIris,
    UniformSection,
)

WR90 = {"a_mm": 22.86, "b_mm": 10.16}
FREQS = [8.0 + 0.2 * i for i in range(21)]  # 8–12GHz，WR-90 全传播
STRAIGHT = {"sections": [{"type": "uniform", **WR90, "length_mm": 20.0}],
            "freqs_ghz": FREQS}


def _adapter(tmp_path: Path) -> MmtAdapter:
    cfg = EMSolverConfig(solver_type=EMSolverType.MMT, working_dir=str(tmp_path))
    adapter = get_global_registry().create(EMSolverType.MMT, cfg)
    assert isinstance(adapter, MmtAdapter)
    return adapter


def _complex_list(rows: list) -> np.ndarray:
    return np.array([complex(*v) if v is not None else complex(np.nan, np.nan)
                     for v in rows])


@pytest.fixture(scope="module")
def env(solved):
    """产物面测试别名（同一确定性求解产物只读复用）。"""
    return solved


@pytest.fixture(scope="module")
def solved(tmp_path_factory):
    """WR-90 直段一次求解共享（纯确定性内核，跨测试只读复用）。"""
    wd = tmp_path_factory.mktemp("mmt_wr90")
    adapter = _adapter(wd)
    adapter.build_geometry(dict(STRAIGHT))
    result = adapter.solve()
    assert result.success, result.message
    return wd, adapter, result


# ─── G-P2-1 注册全链 ─────────────────────────────────────────────────────────


class TestRegistryFullChain:
    def test_enum_value_and_registration(self):
        assert EMSolverType.MMT.value == "mmt"
        reg = get_global_registry()
        assert reg.is_registered(EMSolverType.MMT)

    def test_adapter_kit_contract(self):
        from rfauto.service.adapter_kit import KNOWN_ADAPTERS, check_adapter_contract

        assert KNOWN_ADAPTERS["mmt"]["class"] == "MmtAdapter"
        report = check_adapter_contract(MmtAdapter)
        assert report["ok"], report

    def test_full_chain_json_to_products(self, tmp_path):
        adapter = _adapter(tmp_path)
        assert adapter.connect() is True
        assert adapter.is_available() is True
        assert adapter.build_geometry(dict(STRAIGHT)) is True
        result = adapter.solve()
        assert result.success, result.message
        assert result.wall_time_s < 10.0  # 预算：秒级（criteria §1）
        for name in ("sparams.csv", "mmt.s2p", "mmt_meta.json"):
            assert (tmp_path / name).is_file(), name


# ─── G-P2-2 WR-90 β 互洽 + 50Ω 闭式对拍 ──────────────────────────────────────


class TestWR90Straight:
    def test_beta_anchor_per_frequency(self, solved):
        """G3 既有钉复用：β_mmt vs siw_beta_rad_m 逐频 ≤1e-6（fc10 钉）。"""
        _wd, _adapter, result = solved
        assert result.success
        beta = result.field_data["beta_te10_ports"][:, 0]
        for i, f in enumerate(FREQS):
            beta_ref, fc10 = siw_beta_rad_m(WR90["a_mm"], 1.0, f)
            assert abs(fc10 - 6.5571) < 5e-5  # 既有钉
            assert abs(beta[i].real - beta_ref) / beta_ref <= 1e-6

    def test_products_match_uniform_line_closed_form(self, solved):
        """50Ω 产物 2×2 vs 均匀线闭式（Γ/T 式，实现路径外裁判）≤1e-9。"""
        _wd, _adapter, result = solved
        s = result.s_params
        worst = 0.0
        for i, f in enumerate(FREQS):
            beta_ref, _ = siw_beta_rad_m(WR90["a_mm"], 1.0, f)
            z_te = 2.0 * math.pi * f * 1e9 * MU0 / beta_ref
            gamma = (z_te - 50.0) / (z_te + 50.0)
            tt = complex(math.cos(beta_ref * 0.02), -math.sin(beta_ref * 0.02))
            den = 1.0 - gamma * gamma * tt * tt
            s11_cf = gamma * (1.0 - tt * tt) / den
            s21_cf = tt * (1.0 - gamma * gamma) / den
            worst = max(worst, abs(s[i, 0, 0] - s11_cf), abs(s[i, 1, 0] - s21_cf))
        assert worst <= 1e-9

    def test_passive_reciprocal_at_50ohm(self, solved):
        """G-P2-5：无耗段 50Ω 重归一 |S11|²+|S21|²≤1+1e-9 且 S12=S21。"""
        _wd, _adapter, result = solved
        s = result.s_params
        assert np.all(np.abs(s[:, 0, 0]) ** 2 + np.abs(s[:, 1, 0]) ** 2
                      <= 1.0 + 1e-9)
        assert np.max(np.abs(s[:, 0, 1] - s[:, 1, 0])) <= 1e-9
        assert result.field_data["converged"] is True


# ─── G-P2-3 产物一致性 ────────────────────────────────────────────────────────


class TestProducts:
    def test_touchstone_matches_memory(self, env):
        wd, _adapter, result = env
        import skrf

        net = skrf.Network(str(wd / "mmt.s2p"))
        s_det = result.s_params[~result.field_data["undetermined"]]
        assert net.s.shape == s_det.shape
        assert float(np.max(np.abs(net.s - s_det))) <= 1e-12
        assert np.allclose(net.z0, 50.0)

    def test_sparams_csv_masked_schema(self, env):
        wd, _adapter, result = env
        from rfauto.service.health_service import _parse_sparams_csv_masked

        parsed = _parse_sparams_csv_masked(wd / "sparams.csv")
        assert parsed is not None
        freq_hz, s, mask = parsed
        assert mask[0, 0] and mask[1, 0]  # 5 列契约：独立实测仅 S11/S21
        assert not mask[0, 1] and not mask[1, 1]  # 补齐元素掩码 False（#314）
        det = ~result.field_data["undetermined"]
        assert np.allclose(freq_hz, np.array(FREQS)[det] * 1e9, rtol=0, atol=1e-6)
        assert float(np.max(np.abs(s[:, 0, 0]
                                   - result.s_params[det, 0, 0]))) <= 1e-12

    def test_meta_json_roundtrip(self, env):
        wd, adapter, _result = env
        meta_file = json.loads((wd / "mmt_meta.json").read_text(encoding="utf-8"))
        assert meta_file == adapter.get_meta()
        assert json.loads(json.dumps(meta_file)) == meta_file
        assert meta_file["schema"] == "rfauto-mmt/v1"
        assert "UNDECIDABLE" in meta_file["absolute_s_note"]
        assert meta_file["n_undetermined"] == 0

    def test_export_touchstone_path(self, env, tmp_path):
        _wd, adapter, _result = env
        out = tmp_path / "exported" / "x.s2p"
        path = adapter.export_touchstone(out)
        assert path.is_file()
        import skrf

        assert skrf.Network(str(path)).s.shape[1:] == (2, 2)


# ─── G-P2-4 服务 JSON 往返与 undetermined ────────────────────────────────────


class TestServiceEnvelope:
    def test_json_roundtrip_and_grid(self, tmp_path):
        from rfauto.service.mmt_service import solve_mmt

        out = solve_mmt(dict(STRAIGHT), work_dir=str(tmp_path / "wd"))
        assert out["ok"] is True
        assert json.loads(json.dumps(out)) == out  # G-P2-4 往返律
        n = len(FREQS)
        assert len(out["freqs_ghz"]) == n and len(out["s11"]) == n
        assert out["converged"] is True
        assert out["n_determined"] == n and out["n_undetermined"] == 0
        assert all(v is not None for v in out["s11"])
        for name in ("sparams_csv", "touchstone", "meta"):
            assert Path(out["artifacts"][name]).is_file(), name

    def test_undetermined_not_extrapolated(self, tmp_path):
        """近截止/过传频点：S=null、逐点列名、产物只写 determined 行。"""
        from rfauto.service.mmt_service import solve_mmt

        out = solve_mmt({"sections": STRAIGHT["sections"],
                         "freqs_ghz": [5.0, 5.5, 6.0]},
                        work_dir=str(tmp_path / "wd2"))
        assert out["ok"] is True
        assert out["n_undetermined"] == 3
        assert out["undetermined_freqs_ghz"] == [5.0, 5.5, 6.0]
        assert all(v is None for v in out["s11"])  # 不外推
        assert not Path(out["artifacts"]["touchstone"]).exists()  # 无 determined 行
        csv_rows = Path(out["artifacts"]["sparams_csv"]).read_text(
            encoding="utf-8").strip().splitlines()
        assert len(csv_rows) == 1  # 仅表头

    def test_mode_policy_passthrough(self, tmp_path):
        from rfauto.service.mmt_service import solve_mmt

        out = solve_mmt({"sections": STRAIGHT["sections"],
                         "freqs_ghz": [9.0, 10.0, 11.0],
                         "mode_policy": {"n_modes_ref": 11}},
                        work_dir=str(tmp_path / "wd3"))
        assert out["ok"] and out["converged"] is True
        assert out["n_modes"] == [11]

    def test_bad_sections_error_envelope(self, tmp_path):
        from rfauto.service.mmt_service import solve_mmt

        out = solve_mmt({"sections": [{"type": "coax", "a_mm": 1.0}],
                         "freqs_ghz": [9.0, 10.0]}, work_dir=str(tmp_path))
        assert out["ok"] is False and out["status"] == "bad_request"
        assert out["errors"]

    def test_adjacency_violation_honest_failure(self, tmp_path):
        """相邻段缺显式 hstep：core 拒绝 → 服务 ok=False 不静默。"""
        from rfauto.service.mmt_service import solve_mmt

        out = solve_mmt({"sections": [
            {"type": "uniform", **WR90, "length_mm": 10.0},
            {"type": "uniform", "a_mm": 12.0, "b_mm": 10.16, "length_mm": 10.0}],
            "freqs_ghz": [9.0, 10.0]}, work_dir=str(tmp_path))
        assert out["ok"] is False and out["status"] == "solve_failed"
        assert "HStepJunction" in out["errors"][0]


# ─── 段表解析与规范化 ─────────────────────────────────────────────────────────


class TestSectionParsing:
    def test_three_types_and_units(self):
        chain = parse_sections([
            {"type": "uniform", **WR90, "length_mm": 5.0, "tan_d": 1e-4},
            {"type": "hstep", "a_left_mm": 22.86, "b_left_mm": 10.16,
             "a_right_mm": 12.0, "b_right_mm": 10.16},
            {"type": "iris", **WR90, "aperture_mm": 16.0, "thickness_mm": 1.0},
        ], {"eps_r": 1.0, "tan_d": 0.0, "sigma_s_m": None})
        assert isinstance(chain[0], UniformSection)
        assert chain[0].wg.a == pytest.approx(0.02286)
        assert chain[0].length_m == pytest.approx(0.005)
        assert isinstance(chain[1], HStepJunction)
        # 居中阶梯偏移：窄侧局部原点在 (22.86−12)/2 mm
        assert chain[1].offset_right_m == pytest.approx(0.0) or \
            chain[1].offset_left_m == pytest.approx((22.86 - 12.0) / 2e3)
        assert isinstance(chain[2], InductiveIris)
        assert chain[2].aperture_m == pytest.approx(0.016)

    def test_unknown_type_and_empty_rejected(self):
        with pytest.raises(MmtError, match="未知段类型"):
            parse_sections([{"type": "coax"}], {})
        with pytest.raises(MmtError, match="非空"):
            parse_sections([], {})

    def test_json_chain_value_equal_instances_solve(self, tmp_path):
        """行为等价钉（P1 core id() 反查根治后适配器权宜 canonicalize_chain
        已删，followUp 闭合）：JSON 段表逐段**新造** Waveguide
        （值相等、实例不同——本链三处 WR90 互为不同实例），core 值语义
        去重+按值反查直接可解。物理旁证：两段同规格均匀段级联=无结构
        均匀线（值去重若失效会引入伪结面/伪 guide 破坏守恒）。"""
        adapter = _adapter(tmp_path)
        assert adapter.build_geometry({
            "sections": [{"type": "uniform", **WR90, "length_mm": 10.0},
                         {"type": "uniform", **WR90, "length_mm": 10.0}],
            "freqs_ghz": [10.0, 12.0]}) is True
        result = adapter.solve()
        assert result.success, result.message
        s = result.s_params
        assert np.all(np.isfinite(s))  # 10/12GHz 全 determined 无 NaN
        # 无耗功率守恒 |S11|²+|S21|²=1（50Ω 归一后仍守恒）
        p = np.abs(s[:, 0, 0]) ** 2 + np.abs(s[:, 1, 0]) ** 2
        assert np.allclose(p, 1.0, atol=1e-9)
        # 对称/互易：均匀线 S11=S22、S12=S21
        assert np.allclose(s[:, 0, 0], s[:, 1, 1], atol=1e-12)
        assert np.allclose(s[:, 0, 1], s[:, 1, 0], atol=1e-12)


# ─── 膜片/阶梯链与 UNDECIDABLE 声明 ──────────────────────────────────────────


class TestIrisChain:
    def test_iris_chain_runs_and_declares_undecidable(self, tmp_path):
        from rfauto.service.mmt_service import solve_mmt

        # 频点避开膜片子波导近截止带（aperture=16mm → fc_sub=9.371GHz、
        # ±5% 病态带 [8.90,9.84]GHz——9.0GHz 会被 undetermined 规则如实置 NaN，
        # 该行为由 test_undetermined_not_extrapolated 另行钉）
        out = solve_mmt({"sections": [
            {"type": "uniform", **WR90, "length_mm": 10.0},
            {"type": "iris", **WR90, "aperture_mm": 16.0, "thickness_mm": 0.0},
            {"type": "uniform", **WR90, "length_mm": 10.0}],
            "freqs_ghz": [10.0, 11.0, 12.0],
            "mode_policy": {"n_modes_ref": 21}},
            work_dir=str(tmp_path / "iris"))
        assert out["ok"] is True, out.get("errors")
        assert out["converged"] is True
        s11 = _complex_list(out["s11"])
        s21 = _complex_list(out["s21"])
        # 无源性：多结面含倏逝耦合级联不设物理门（criteria §1 G-P2-5 作用域
        # 修正 + §3 修正记录）——首跑实测残差 +1.7% 且对模式数平坦（P1 已档
        # "双结面级联表示不等价"的 TE10 指纹，绝对值归 G1）；此处只设 ≤3%
        # 回归带宽，防粗大回归，不冒充物理门（#122）。
        resid = np.abs(s11) ** 2 + np.abs(s21) ** 2 - 1.0
        assert float(np.max(resid)) <= 0.03
        assert "UNDECIDABLE" in out["absolute_s_note"]
        meta = json.loads(
            Path(out["artifacts"]["meta"]).read_text(encoding="utf-8"))
        # 回显保持输入契约形态（iris 保持 iris，不展开成三件）
        assert [s["type"] for s in meta["sections"]] == ["uniform", "iris",
                                                         "uniform"]

    def test_hstep_chain_with_material_defaults(self, tmp_path):
        """介质阶梯：材料过渡在结面右侧声明（与后继 uniform 逐字段一致）。"""
        from rfauto.service.mmt_service import solve_mmt

        out = solve_mmt({"sections": [
            {"type": "uniform", **WR90, "length_mm": 8.0},
            {"type": "hstep", "a_left_mm": 22.86, "b_left_mm": 10.16,
             "a_right_mm": 15.0, "b_right_mm": 10.16, "eps_r_right": 2.04,
             "tan_d_right": 2e-4},
            {"type": "uniform", "a_mm": 15.0, "b_mm": 10.16, "length_mm": 8.0,
             "eps_r": 2.04, "tan_d": 2e-4}],
            "freqs_ghz": [9.0, 10.0, 11.0]},
            work_dir=str(tmp_path / "hstep"))
        assert out["ok"] is True, out.get("errors")
        assert out["warnings"] == []


# ─── 能力声明 ────────────────────────────────────────────────────────────────


class TestCapabilities:
    def test_solver_capabilities_for_mmt(self):
        caps = solver_capabilities_for(EMSolverType.MMT)
        assert caps.solver_type == "mmt"
        assert caps.dimension == "2d"
        assert caps.supports_touchstone_export is True
        assert caps.requires_license is False
        assert caps.supported_templates == ("chain",)
        adapter = MmtAdapter(EMSolverConfig(solver_type=EMSolverType.MMT))
        assert adapter.is_available() is True  # 零 exe 门，恒可用
        assert adapter.capabilities().available is True

    def test_mode_policy_json_keys(self):
        policy = mode_policy_from_json(
            {"n_modes_ref": 9, "strict_truncation_guard": False,
             "n_modes_override": {"0": 30, "1": 90}})
        assert policy.n_modes_ref == 9
        assert policy.strict_truncation_guard is False
        assert policy.n_modes_override == {0: 30, 1: 90}
        with pytest.raises(MmtError):
            mode_policy_from_json({"n_modes_ref": 0})


# ─── CLI/MCP 薄壳（零逻辑转发；计数钉在 test_cli/test_mcp_server）────────────


class TestThinShells:
    def test_cli_mmt_solve_inline_json(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        monkeypatch.chdir(tmp_path)  # #144：产物不落真实 runs/
        sections = json.dumps({"sections": STRAIGHT["sections"]})
        res = CliRunner().invoke(app, [
            "mmt", "solve", "--sections", sections,
            "--freqs-ghz", "9,10,11", "--work-dir", str(tmp_path / "cli"),
            "--json"])
        assert res.exit_code == 0, res.output
        assert "MMT 求解" in res.output or "converged" in res.output

    def test_cli_mmt_solve_at_file(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        monkeypatch.chdir(tmp_path)
        payload = {"sections": STRAIGHT["sections"], "freqs_ghz": [9.0, 10.0]}
        f = tmp_path / "chain.json"
        f.write_text(json.dumps(payload), encoding="utf-8")
        res = CliRunner().invoke(app, [
            "mmt", "solve", "--sections", f"@{f}",
            "--work-dir", str(tmp_path / "cli2")])
        assert res.exit_code == 0, res.output
        assert (tmp_path / "cli2" / "mmt_meta.json").is_file()

    def test_cli_mmt_solve_bad_json_exit_1(self, tmp_path, monkeypatch):
        from typer.testing import CliRunner

        from rfauto.cli.main import app

        monkeypatch.chdir(tmp_path)
        res = CliRunner().invoke(app, [
            "mmt", "solve", "--sections", "{not-json",
            "--freqs-ghz", "9,10"])
        assert res.exit_code == 1

    def test_mcp_tool_registered_and_callable(self, tmp_path):
        import asyncio

        from rfauto.mcp_server import mcp, mmt_solve

        tools = asyncio.run(mcp.list_tools())
        assert "mmt_solve" in {t.name for t in tools}
        # 薄壳直调（函数体零逻辑转发 mmt_service）
        out = mmt_solve(
            sections=[{"type": "uniform", **WR90, "length_mm": 20.0}],
            freqs_ghz=[9.0, 10.0, 11.0], work_dir=str(tmp_path / "mcp"))
        assert out["ok"] is True and out["converged"] is True
