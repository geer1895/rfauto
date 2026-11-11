"""SPICE 导出随参数插值服务单测（aurora_p D4；service/spice_param_export_service）。

链路：θ → param_vf 预测 S(θ,ω) → core.macromodel VF → SPICE 子电路 →
回放自检 → 网表交付。验收映射（任务书冻结判据 A-E）：

    A θ₀ 端到端：四门全过+已交付；交付网表回放 vs 预测 S 的 RMS ≤
      DEFAULT_RMS_THRESHOLD_DB（栅上+栅间中点），逐频误差向量逐点 ≤
      10^(阈值/20)；内核回放 vs 模型 ≤ DEFAULT_REPLAY_CONSISTENCY_TOL——
      容差全部读 core.macromodel 单源常量（零新口径）。独立裁判（#118）：
      交付网表回放 vs **闭式真值**（串联 RL 两端口 ABCD 推导）相对 RMSE ≤
      D2 冻结门 RL_GATE=5e-2（param_vf 插值误差即唯一误差源）。
    B 确定性：同 θ 两跑网表逐字节 + 信封逐键一致（路径键除外）。
    C θ 敏感性：显式定阶 (1 实, 0 复) 结构上锁拓扑（1×1 重定位特征值必为
      实）——两 θ 网表字节不同、拓扑签名相同、元件名/节点逐行相同、值不同；
      数值合理：状态网络电阻 Rp=-1/p 对闭式 L/(R+2Z0) 相对偏差 ≤
      ELEM_GATE=5e-2（探针实测 1.2e-3/9.2e-3），且随 θ 变化方向一致。
    D 诚实边界：verification 字段（third_party_spice_equivalence=False）+
      声明串=内核回放单源 + 网表 ASCII 头注 + 服务 docstring 三处在场。
    E 负例如实 FAIL（#122）：无源违例 / 回放超差 / 空 Data / 键集不匹配 /
      放宽阈值 / 带外频栅 / 交付文件语义篡改（G2 有效性）——零写面（不交付、
      新建父目录回滚、既存文件不动）。既有 macromodel/param_vf 钉零改动全绿
      为独立证据（本席不改 core/surrogate）。

裁判纪律（#118）：合成真值一律独立闭式公式，不经被测服务构造；口径钉
（服务 RMS vs 内核 compare_s_matrices）证明误差口径单源未漂移。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np
import pytest

from rfauto.core.macromodel import (
    DEFAULT_REPLAY_CONSISTENCY_TOL,
    DEFAULT_RMS_THRESHOLD_DB,
    compare_s_matrices,
    replay_spice_subcircuit_s,
)
from rfauto.optimization.surrogate.param_vf import ParamVFSurrogate
from rfauto.service import spice_param_export_service as svc
from rfauto.service.spice_param_export_service import spice_param_export


@pytest.fixture(autouse=True)
def _isolated(isolated):
    """cwd 隔离单源（tests/conftest.py::isolated）——零湖写。"""
    yield

# ─── 常量与冻结门 ──────────────────────────────

Z0 = 50.0
#: 独立裁判门：回放 vs 闭式真值相对 RMSE（D2 test_param_vf_nport.RL_GATE 同值
#: 同依据——param_vf 插值误差是唯一误差源，VF/回放误差 ~1e-6 量级可忽略）。
RL_GATE = 5e-2
#: C 数值合理门：Rp 对闭式 L/(R+2Z0) 相对偏差（探针 runs/aurora_p/d4/
#: probe_d4_topology.log 实测 θ0 1.2e-3 / θ1 9.2e-3；同 RL_GATE 值）。
ELEM_GATE = 5e-2

F_LO_HZ, F_HI_HZ, N_FREQ = 0.1e9, 6.0e9, 81
RL_SAMPLES = [(32.0, 9.0), (45.0, 14.5), (58.0, 8.5), (66.0, 13.0),
              (38.0, 15.5), (52.0, 10.5), (30.0, 12.5), (62.0, 15.0)]
RL_BOUNDS = {"r_ohm": (28.0, 70.0), "l_nh": (8.0, 16.0)}
THETA0 = {"r_ohm": 44.0, "l_nh": 12.0}
THETA1 = {"r_ohm": 55.0, "l_nh": 11.5}
RLC_SAMPLES = [(4.0, 0.8), (6.0, 0.8), (4.0, 1.4), (6.0, 1.4),
               (5.0, 1.1), (4.5, 1.0), (5.5, 1.25), (5.0, 0.9)]
RLC_BOUNDS = {"l_nh": (3.8, 6.2), "c_pf": (0.75, 1.45)}
RLC_THETA = {"l_nh": 5.0, "c_pf": 1.0}
ORDER_PIN = {"n_poles_real": 1, "n_poles_cmplx": 0}


# ─── 独立闭式真值（不经被测服务） ─────────────────────────────────────────────


def _freq() -> np.ndarray:
    return np.linspace(F_LO_HZ, F_HI_HZ, N_FREQ)


def _series_z_2port(z: np.ndarray) -> np.ndarray:
    """串联 Z 两端口（ABCD=[1,Z;0,1]）：S11=S22=Z/(2Z0+Z)，S21=S12=2Z0/(2Z0+Z)。"""
    m = np.zeros((len(z), 2, 2), dtype=complex)
    m[:, 0, 0] = m[:, 1, 1] = z / (2.0 * Z0 + z)
    m[:, 0, 1] = m[:, 1, 0] = 2.0 * Z0 / (2.0 * Z0 + z)
    return m


def _rl_truth(r_ohm: float, l_nh: float, freq: np.ndarray | None = None) -> np.ndarray:
    f = _freq() if freq is None else freq
    return _series_z_2port(r_ohm + 2.0j * np.pi * f * l_nh * 1e-9)


def _rlc_truth(l_nh: float, c_pf: float, r_ohm: float = 2.0) -> np.ndarray:
    s = 2.0j * np.pi * _freq()
    return _series_z_2port(r_ohm + s * l_nh * 1e-9 + 1.0 / (s * c_pf * 1e-12))


def _rlc_1port_truth(f: np.ndarray, l_nh: float, c_pf: float,
                     r_ohm: float = 5.0) -> np.ndarray:
    s = 2.0j * np.pi * f
    z = r_ohm + s * l_nh * 1e-9 + 1.0 / (s * c_pf * 1e-12)
    return (z - Z0) / (z + Z0)


def _rl_samples(sign: float = 1.0) -> list[dict]:
    return [{"params": {"r_ohm": sign * r, "l_nh": ln},
             "metrics": {"s_matrix": _rl_truth(sign * r, ln)}}
            for r, ln in RL_SAMPLES]


def _rl_config(**overrides) -> dict:
    cfg = {"bounds": dict(RL_BOUNDS), "freq_grid_ghz": (0.1, 6.0),
           "n_freq": N_FREQ, "n_real_poles": 2, "n_cmplx_pairs": 3,
           "n_ports": 2}
    cfg.update(overrides)
    return cfg


def _rlc_samples() -> list[dict]:
    return [{"params": {"l_nh": ln, "c_pf": c},
             "metrics": {"s_matrix": _rlc_truth(ln, c)}}
            for ln, c in RLC_SAMPLES]


def _rlc_config() -> dict:
    return {"bounds": dict(RLC_BOUNDS), "freq_grid_ghz": (0.1, 6.0),
            "n_freq": N_FREQ, "n_real_poles": 2, "n_cmplx_pairs": 3,
            "n_ports": 2}


def _payload(out: Path, **overrides) -> dict:
    p = {"config": _rl_config(), "samples": _rl_samples(),
         "params": dict(THETA0), "out_path": str(out)}
    p.update(overrides)
    return p


def _rel_rmse(a: np.ndarray, b: np.ndarray) -> float:
    """D2 同式：Frobenius 相对误差 ‖a−b‖/‖b‖。"""
    return float(np.linalg.norm(np.asarray(a) - np.asarray(b))
                 / np.linalg.norm(b))


def _element_rows(text: str) -> list[tuple[str, tuple[str, ...], str]]:
    """网表元件行 → (名, 节点/控制令牌, 值令牌)；注释/指令跳过。"""
    rows = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("*", ".")):
            continue
        toks = line.split()
        rows.append((toks[0], tuple(toks[1:-1]), toks[-1]))
    return rows


def _assert_not_delivered(env: dict, out: Path) -> None:
    assert env["ok"] is False
    assert env["verdict"] == "FAIL"
    assert env["delivered"] is False
    assert env["netlist_path"] is None
    assert isinstance(env["errors"], list) and env["errors"]
    assert not out.exists()
    assert not list(out.parent.glob(f".{out.name}.*.staging")) \
        if out.parent.exists() else True


# ─── A：θ₀ 端到端 ─────────────────────────────────────────────────────────────


class TestAEndToEnd:
    def test_theta0_pass_all_gates_within_single_source_tolerance(self, tmp_path):
        out = tmp_path / "net" / "rl_theta0.sp"
        env = spice_param_export(_payload(out))
        assert env["ok"] is True, env.get("errors")
        assert env["verdict"] == "PASS" and env["delivered"] is True
        assert env["gates"] == {
            "G1_kernel_ok": True, "G2_delivered_replay_consistent": True,
            "G3_replay_vs_prediction": True,
            "G4_replay_vs_prediction_offgrid": True}
        assert Path(env["netlist_path"]) == out and out.is_file()
        assert env["netlist_sha256"] == hashlib.sha256(
            out.read_bytes()).hexdigest()
        rep = env["replay"]
        # 容差全部读内核单源常量（零新口径）
        assert rep["consistency_tol_abs"] == DEFAULT_REPLAY_CONSISTENCY_TOL
        assert rep["rms_threshold_db"] == DEFAULT_RMS_THRESHOLD_DB
        assert rep["kernel_replay_vs_model_max_abs"] <= DEFAULT_REPLAY_CONSISTENCY_TOL
        # 头注只加注释行：交付文件回放与内核回放逐位相同
        assert rep["delivered_vs_kernel_replay_max_abs"] == 0.0
        for sec in ("vs_prediction", "vs_prediction_offgrid"):
            assert rep[sec]["rms_db"] <= DEFAULT_RMS_THRESHOLD_DB, sec
        # 逐频误差：每个频点条目最大 |ΔS| 均在单源容差（线性）内
        lin_tol = 10.0 ** (DEFAULT_RMS_THRESHOLD_DB / 20.0)
        per_freq = rep["vs_prediction"]["per_freq_max_abs"]
        assert len(per_freq) == N_FREQ
        assert max(per_freq) <= lin_tol
        assert len(rep["vs_prediction_offgrid"]["per_freq_max_abs"]) == N_FREQ - 1
        assert max(rep["vs_prediction_offgrid"]["per_freq_max_abs"]) <= lin_tol
        assert env["param_model"]["param_extrapolation"][
            "param_extrapolation"] == "ok"
        assert env["freq_grid"]["source"] == "model_training_grid"
        # 交付后目录只剩网表本体（staging 已原子替换，无残留）
        assert list(out.parent.iterdir()) == [out]
        json.dumps(env)  # JSON 原生（规则 4）

    def test_tightened_threshold_is_honored(self, tmp_path):
        """阈值只许收紧：更严阈值被 VF 阶梯与 G3/G4 一致采用。"""
        out = tmp_path / "rl_tight.sp"
        env = spice_param_export(_payload(out, rms_threshold_db=-60.0))
        assert env["ok"] is True, env.get("errors")
        assert env["vector_fit"]["threshold_db"] == -60.0
        assert env["replay"]["rms_threshold_db"] == -60.0
        assert env["replay"]["vs_prediction"]["rms_db"] <= -60.0

    def test_independent_judge_replay_vs_closed_form_truth(self, tmp_path):
        """#118：交付网表经内核回放 vs 闭式真值（独立来源），≤ D2 冻结门。"""
        out = tmp_path / "rl.sp"
        env = spice_param_export(_payload(out))
        assert env["ok"] is True, env.get("errors")
        f = _freq()
        rp = replay_spice_subcircuit_s(out, f, z0=Z0, n_ports=2)
        rel = _rel_rmse(rp["s"], _rl_truth(**THETA0))
        assert rel <= RL_GATE, f"rel_rmse={rel:.3e}"

    def test_error_metric_matches_kernel_compare_single_source(self, tmp_path):
        """口径钉：服务 RMS/max 与内核 compare_s_matrices 误差口径逐位一致。"""
        out = tmp_path / "rl.sp"
        env = spice_param_export(_payload(out))
        assert env["ok"] is True, env.get("errors")
        model = ParamVFSurrogate(_rl_config())
        model.fit(_rl_samples())
        s_pred = model.predict_matrix(dict(THETA0))
        f = _freq()
        rp = replay_spice_subcircuit_s(out, f, z0=Z0, n_ports=2)
        ref = compare_s_matrices(f, s_pred, rp["s"])["error"]
        got = env["replay"]["vs_prediction"]
        assert got["rms_abs"] == ref["rms_abs"]
        assert got["rms_db"] == ref["rms_db"]
        assert got["max_abs"] == ref["max_abs"]

    def test_single_port_s11_path_pass(self, tmp_path):
        f1 = np.linspace(0.5e9, 6.0e9, N_FREQ)
        samples = [{"params": {"l_nh": ln, "c_pf": c},
                    "metrics": {"s11_curve": _rlc_1port_truth(f1, ln, c)}}
                   for ln, c in [(1.6, 0.4), (2.4, 0.4), (1.6, 0.6), (2.4, 0.6),
                                 (2.0, 0.5), (1.8, 0.45), (2.2, 0.55), (2.0, 0.42)]]
        cfg = {"bounds": {"l_nh": (1.5, 2.5), "c_pf": (0.38, 0.62)},
               "freq_grid_ghz": (0.5, 6.0), "n_freq": N_FREQ}
        out = tmp_path / "p1.sp"
        env = spice_param_export({"config": cfg, "samples": samples,
                                  "params": {"l_nh": 2.0, "c_pf": 0.5},
                                  "out_path": str(out)})
        assert env["ok"] is True, env.get("errors")
        assert env["n_ports"] == 1
        subckt = [ln for ln in out.read_text().splitlines()
                  if ln.startswith(".SUBCKT")]
        assert subckt == [".SUBCKT param_s_equivalent p1"]

    def test_explicit_in_band_freq_grid(self, tmp_path):
        f_ghz = list(np.linspace(0.5, 5.5, 41))
        out = tmp_path / "rl_grid.sp"
        env = spice_param_export(_payload(out, freq_ghz=f_ghz))
        assert env["ok"] is True, env.get("errors")
        assert env["freq_grid"]["source"] == "explicit"
        assert env["freq_grid"]["n_points"] == 41
        assert len(env["replay"]["vs_prediction"]["per_freq_max_abs"]) == 41


# ─── B：确定性 ────────────────────────────────────────────────────────────────


class TestBDeterminism:
    def test_same_theta_two_runs_byte_identical(self, tmp_path):
        a, b = tmp_path / "a.sp", tmp_path / "b.sp"
        env_a = spice_param_export(_payload(a))
        env_b = spice_param_export(_payload(b))
        assert env_a["ok"] is True and env_b["ok"] is True
        assert a.read_bytes() == b.read_bytes()
        assert env_a["netlist_sha256"] == env_b["netlist_sha256"]
        strip = {"netlist_path"}
        ja = json.dumps({k: v for k, v in env_a.items() if k not in strip},
                        sort_keys=True)
        jb = json.dumps({k: v for k, v in env_b.items() if k not in strip},
                        sort_keys=True)
        assert ja == jb

    def test_netlist_is_lf_ascii_with_header_first(self, tmp_path):
        out = tmp_path / "rl.sp"
        env = spice_param_export(_payload(out))
        assert env["ok"] is True
        raw = out.read_bytes()
        assert b"\r\n" not in raw  # 行尾统一 LF（跨平台逐字节）
        text = raw.decode("ascii")  # 纯 ASCII（SPICE 工具互通）
        assert text.startswith("* rfauto spice_param_export:")
        assert "* params: l_nh=12.0 r_ohm=44.0\n" in text


# ─── C：θ 敏感性（显式定阶锁拓扑） ───────────────────────────────────────────


class TestCThetaSensitivity:
    def test_two_theta_values_change_topology_pinned(self, tmp_path):
        o0, o1 = tmp_path / "t0.sp", tmp_path / "t1.sp"
        e0 = spice_param_export(_payload(o0, order=dict(ORDER_PIN)))
        e1 = spice_param_export(_payload(o1, params=dict(THETA1),
                                         order=dict(ORDER_PIN)))
        assert e0["ok"] is True, e0.get("errors")
        assert e1["ok"] is True, e1.get("errors")
        assert o0.read_bytes() != o1.read_bytes()
        assert e0["topology"]["signature"] == e1["topology"]["signature"]
        assert e0["topology"]["element_counts"] == e1["topology"]["element_counts"]
        assert e0["vector_fit"]["poles"] == e1["vector_fit"]["poles"] == {
            "n_poles_stored": 1, "n_real_poles": 1, "n_complex_pairs": 0,
            "effective_order": 1}
        r0 = _element_rows(o0.read_text())
        r1 = _element_rows(o1.read_text())
        assert [(n, nd) for n, nd, _ in r0] == [(n, nd) for n, nd, _ in r1]
        changed = [n for (n, _, v0), (_, _, v1) in zip(r0, r1, strict=True)
                   if v0 != v1]
        assert changed, "两 θ 元件值应不同"

    def test_state_resistor_matches_closed_form_pole(self, tmp_path):
        """数值合理：Rp=-1/p，闭式 p=-(R+2Z0)/L ⇒ Rp=L/(R+2Z0)。"""
        rps = {}
        for tag, th in (("t0", THETA0), ("t1", THETA1)):
            out = tmp_path / f"{tag}.sp"
            env = spice_param_export(_payload(out, params=dict(th),
                                              order=dict(ORDER_PIN)))
            assert env["ok"] is True, env.get("errors")
            vals = {n: float(v) for n, _, v in _element_rows(out.read_text())
                    if re.fullmatch(r"Rp1_a[12]", n)}
            assert set(vals) == {"Rp1_a1", "Rp1_a2"}
            truth = th["l_nh"] * 1e-9 / (th["r_ohm"] + 2.0 * Z0)
            for name, val in vals.items():
                assert abs(val - truth) / truth <= ELEM_GATE, (tag, name, val)
            rps[tag] = vals["Rp1_a1"]
        # 方向一致：闭式 Rp(θ1)=7.42e-11 < Rp(θ0)=8.33e-11
        assert rps["t1"] < rps["t0"]

    def test_topology_signature_recomputes_from_file(self, tmp_path):
        out = tmp_path / "rl.sp"
        env = spice_param_export(_payload(out))
        assert env["ok"] is True
        rows = []
        for raw in out.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("*"):
                continue
            toks = line.split()
            rows.append(" ".join(toks if line.startswith(".") else toks[:-1]))
        sig = hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()[:16]
        assert env["topology"]["signature"] == sig


# ─── D：诚实边界 ─────────────────────────────────────────────────────────────


class TestDHonesty:
    def test_envelope_header_and_docstring_disclaim_third_party(self, tmp_path):
        out = tmp_path / "rl.sp"
        env = spice_param_export(_payload(out))
        assert env["ok"] is True
        ver = env["verification"]
        assert ver["kind"] == "replay_selfcheck"
        assert ver["third_party_spice_equivalence"] is False
        assert env["replay"]["verifier"] == "replay_selfcheck"
        # 声明串单源：与内核回放返回的 disclaimer 逐字相同
        kernel = replay_spice_subcircuit_s(out, _freq(), z0=Z0)
        assert ver["disclaimer"] == kernel["disclaimer"]
        assert "ngspice" in ver["disclaimer"]
        assert "NOT a third-party SPICE" in out.read_text()
        doc = spice_param_export.__doc__ or ""
        assert "回放自检" in doc and "不是第三方 SPICE 等价验证" in doc
        assert "不是第三方 SPICE 等价验证" in (svc.__doc__ or "")


# ─── E：负例如实 FAIL + 零写面 ───────────────────────────────────────────────


class TestENegatives:
    def test_nonpassive_model_fails_honestly(self, tmp_path):
        out = tmp_path / "act.sp"
        cfg = _rl_config(bounds={"r_ohm": (-70.0, -28.0), "l_nh": (8.0, 16.0)})
        env = spice_param_export({
            "config": cfg, "samples": _rl_samples(sign=-1.0),
            "params": {"r_ohm": -44.0, "l_nh": 12.0}, "out_path": str(out)})
        _assert_not_delivered(env, out)
        assert env["stage"] == "gates"
        assert env["gates"]["G1_kernel_ok"] is False
        assert env["param_model"]["prediction_passivity"]["passive"] is False
        assert env["vector_fit"]["passivity"]["passive_in_band_before"] is False
        assert any("无源" in e for e in env["errors"])

    def test_replay_over_tolerance_fails_with_faithful_netlist(self, tmp_path):
        """低阶阶梯：网表忠实于 VF 模型（G2 过）但回放 vs 预测超容差。"""
        out = tmp_path / "low.sp"
        env = spice_param_export({
            "config": _rlc_config(), "samples": _rlc_samples(),
            "params": dict(RLC_THETA), "out_path": str(out),
            "order_ladder": [[1, 0]]})
        _assert_not_delivered(env, out)
        assert env["stage"] == "gates"
        g = env["gates"]
        assert g["G2_delivered_replay_consistent"] is True
        assert g["G3_replay_vs_prediction"] is False
        assert g["G4_replay_vs_prediction_offgrid"] is False
        assert env["replay"]["vs_prediction"]["rms_db"] > DEFAULT_RMS_THRESHOLD_DB
        assert any(e.startswith("G3") for e in env["errors"])

    def test_g2_detects_tampered_delivery_file(self, tmp_path, monkeypatch):
        """交付文件与已验文件语义不一致（头注入篡改元件值）→ G2 拦截。"""
        real_inject = svc._inject_header

        def _tamper(path: Path, header: str) -> None:
            real_inject(path, header)
            text = path.read_text(encoding="utf-8")
            text = re.sub(r"^(R1 s1 0) (\S+)$", r"\1 75.0", text, count=1,
                          flags=re.M)
            path.write_text(text, encoding="utf-8", newline="\n")

        monkeypatch.setattr(svc, "_inject_header", _tamper)
        out = tmp_path / "tamper.sp"
        env = spice_param_export(_payload(out))
        _assert_not_delivered(env, out)
        assert env["gates"]["G2_delivered_replay_consistent"] is False
        assert env["replay"]["delivered_vs_kernel_replay_max_abs"] > \
            DEFAULT_REPLAY_CONSISTENCY_TOL
        assert any(e.startswith("G2") for e in env["errors"])

    def test_fail_is_zero_write_rolls_back_new_dirs(self, tmp_path):
        out = tmp_path / "new1" / "new2" / "low.sp"
        env = spice_param_export({
            "config": _rlc_config(), "samples": _rlc_samples(),
            "params": dict(RLC_THETA), "out_path": str(out),
            "order_ladder": [[1, 0]]})
        assert env["ok"] is False and env["delivered"] is False
        assert not (tmp_path / "new1").exists()

    def test_fail_leaves_existing_target_untouched(self, tmp_path):
        out = tmp_path / "keep.sp"
        out.write_bytes(b"* sentinel\n")
        env = spice_param_export({
            "config": _rlc_config(), "samples": _rlc_samples(),
            "params": dict(RLC_THETA), "out_path": str(out),
            "order_ladder": [[1, 0]]})
        assert env["ok"] is False and env["delivered"] is False
        assert out.read_bytes() == b"* sentinel\n"
        assert sorted(p.name for p in tmp_path.iterdir()) == ["keep.sp"]

    @pytest.mark.parametrize("samples", [[], "few"])
    def test_empty_or_insufficient_data_fail(self, tmp_path, samples):
        out = tmp_path / "x.sp"
        data = [] if samples == [] else _rl_samples()[:2]
        env = spice_param_export(_payload(out, samples=data))
        _assert_not_delivered(env, out)
        assert env["stage"] == "param_fit"

    def test_params_key_mismatch_fail(self, tmp_path):
        out = tmp_path / "x.sp"
        env = spice_param_export(_payload(out, params={"r_ohm": 44.0}))
        _assert_not_delivered(env, out)
        assert env["stage"] == "predict"

    def test_explicit_order_insufficient_poles_fail(self, tmp_path):
        out = tmp_path / "x.sp"
        env = spice_param_export({
            "config": _rlc_config(), "samples": _rlc_samples(),
            "params": dict(RLC_THETA), "out_path": str(out),
            "order": dict(ORDER_PIN)})
        _assert_not_delivered(env, out)
        assert env["stage"] == "vector_fit"
        assert "极点不足" in env["errors"][0]

    @pytest.mark.parametrize("override, needle", [
        ({"rms_threshold_db": -30.0}, "放宽"),
        ({"freq_ghz": list(np.linspace(0.05, 5.0, 41))}, "越出模型训练带"),
        ({"freq_ghz": list(np.linspace(0.5, 5.0, 10))}, "MIN_FREQ_POINTS"),
        ({"subckt_name": "1bad name"}, "subckt_name"),
        ({"order": dict(ORDER_PIN), "order_ladder": [[1, 2]]}, "二选一"),
        ({"z0_ohm": [50.0, -1.0]}, "z0_ohm"),
        ({"config": None}, "config"),
        ({"params": {}}, "params"),
        ({"out_path": ""}, "out_path"),
    ])
    def test_invalid_input_rejected(self, tmp_path, override, needle):
        out = tmp_path / "x.sp"
        env = spice_param_export(_payload(out, **override))
        _assert_not_delivered(env, out)
        assert env["stage"] == "input"
        assert any(needle in e for e in env["errors"]), env["errors"]


# ─── JSON 输入面等价（[re, im] 对 / samples_path） ───────────────────────────


class TestJsonInputForms:
    def test_pairs_and_samples_path_are_byte_equivalent(self, tmp_path):
        ref_out = tmp_path / "ref.sp"
        assert spice_param_export(_payload(ref_out))["ok"] is True
        pairs = [{"params": s["params"],
                  "metrics": {"s_matrix": np.stack(
                      [s["metrics"]["s_matrix"].real,
                       s["metrics"]["s_matrix"].imag], axis=-1).tolist()}}
                 for s in _rl_samples()]
        p_out = tmp_path / "pairs.sp"
        assert spice_param_export(_payload(p_out, samples=pairs))["ok"] is True
        jpath = tmp_path / "samples.json"
        jpath.write_text(json.dumps(pairs), encoding="utf-8")
        j_out = tmp_path / "json.sp"
        payload = _payload(j_out)
        payload.pop("samples")
        payload["samples_path"] = str(jpath)
        assert spice_param_export(payload)["ok"] is True
        assert ref_out.read_bytes() == p_out.read_bytes() == j_out.read_bytes()


# ─── 极点计数单源化（Q-R3R 遗留清偿席 Q-W8-2 登记） ───────────────────────────


class TestPoleCountsSingleSource:
    """_pole_counts 单源消费 core/macromodel poles_summary（#122 同键双实现
    清偿）：计数式只在 core 一处（skrf 共轭对只存一个，n_complex_pairs=
    n_poles_stored−n_real，#286 同源），service 面降为键名映射+effective_order
    派生。既有端到端金字面（TestCThetaSensitivity 两 θ 拓扑钉的
    vector_fit.poles 四键值）零变化由该测继续承担。"""

    def test_pole_counts_maps_kernel_summary_exactly(self):
        # 内核 summary 形态（fit_macromodel→_poles_residues 契约键 n_poles）
        summary = {"n_poles": 5, "n_real_poles": 1, "n_complex_pairs": 2,
                   "max_abs_pole_rad_s": -1.0}
        assert svc._pole_counts(summary) == {
            "n_poles_stored": 5, "n_real_poles": 1, "n_complex_pairs": 2,
            "effective_order": 5}
        # effective_order 派生口径（#286：get_model_order=N_real+2·N_complex）
        assert svc._pole_counts({"n_poles": 1, "n_real_poles": 1,
                                 "n_complex_pairs": 0}) == {
            "n_poles_stored": 1, "n_real_poles": 1, "n_complex_pairs": 0,
            "effective_order": 1}

    def test_pole_counts_matches_independent_recount(self):
        # #118 独立裁判：测试内独立重算（不经被测函数）对映射值互证
        poles = [[-1.0, 0.0], [-2.0, 3.0], [-4.0, -5.0]]
        n_real = sum(1 for _, im in poles if im == 0.0)
        expect = {"n_poles_stored": len(poles), "n_real_poles": n_real,
                  "n_complex_pairs": len(poles) - n_real,
                  "effective_order": n_real + 2 * (len(poles) - n_real)}
        summary = {"n_poles": len(poles), "n_real_poles": n_real,
                   "n_complex_pairs": len(poles) - n_real}
        assert svc._pole_counts(summary) == expect

    def test_pole_counts_rejects_malformed_summary(self):
        with pytest.raises(ValueError, match="poles_summary"):
            svc._pole_counts({"n_poles": 3})  # 缺 n_real_poles/n_complex_pairs
        with pytest.raises(ValueError, match="poles_summary"):
            svc._pole_counts({"n_poles": "x", "n_real_poles": 0,
                              "n_complex_pairs": 0})

    def test_service_source_consumes_kernel_summary_not_recount(self):
        # 防漂移棘轮（test_width_single_source 同风格）：service 源面不得再
        # 出现独立计数式——单源纪律的源级钉（docstring 引用口径除外）
        import inspect
        svc_src = inspect.getsource(svc)
        assert '"poles_summary"' in svc_src  # 单源消费内核 summary
        assert 'fit.get("poles_rad_s") or []' not in svc_src  # 旧独立重算入口已拆
        counts_src = inspect.getsource(svc._pole_counts)
        counts_code = counts_src.split('"""')[-1]  # 去文档串，只看代码体
        assert "n_stored - n_real" not in counts_code  # 计数式不再本面实现
        assert "poles_rad_s" not in counts_code  # 代码体不再消费极点列表
        assert "poles_rad_s: list" not in counts_src  # 签名不再收极点列表
