"""DP-8 P3 §11 半实例（pin 面参考端口）去嵌基线：渲染能力 + 判读开关单测。

定向门=runs/gate_df7half.log（与 test_compose_layout_netlist 同跑）。
覆盖（#212 离线 exec 审计制度化 + #248 表头钉死 + #122 fail-closed）：
  1) 渲染字节确定（双渲染逐字节同；产物文件与渲染器现输出对账防漂移）；
  2) 契约对齐：R_PIN=round(Z_PV,4)==compose_meta taper pin z_ref（同源
     实证）、R_PIN 双激励脚本互证、截断面=v2 端口面守卫（末孔缘<pin 面）；
  3) 离线 exec 审计（秒级零仿真）：藩篱截断侧/板止于 pin 面/锥-板 SEAM
     连通/激励属性唯一/端口盒边落格（脚本内 #152/#283/#347 守卫随 exec
     全过）/cells-dt 实测；
  4) merge 全矩阵合并：v4.1（§12）电压波→功率波换算（合成互易网络跨基
     换算后互易恢复+解析功率波逐元素对齐）/9 列排列/互易残差（raw 同报）/
     频栅不一致与表头违约显式报错/幂等键 sha 对账/#318 超预算 PARTIAL 载荷；
  5) judge v4 开关：缺省 half、--baseline full 保留（§10 v3 路径）、
     half 基线端到端 PASS/FAIL/MISSING（假曲线，tmp 隔离不污染 runs 证据）。
"""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

_RUN_DIR = REPO / "runs" / "df7_dp8p3"

# 证据脚本（render_half.py / judge 脚本）随 runs/ 留档、不随 git 分发——
# 缺失环境整文件诚实 skip（证据恢复后照常全量判读）。
pytestmark = pytest.mark.skipif(
    not (_RUN_DIR / "render_half.py").exists(),
    reason="runs/df7_dp8p3 evidence scripts not distributed with git")


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def render_half():
    return _load_module("render_half_mod", _RUN_DIR / "render_half.py")


@pytest.fixture(scope="module")
def judge_c4():
    return _load_module("judge_c4_mod", _RUN_DIR / "judge_c4.py")


# ─── 1) 渲染字节确定 + 契约对齐 ─────────────────────────────────────────────

def test_render_byte_determinism_and_artifact_lock(render_half):
    """双渲染逐字节同；产物 simulation_exc1/exc2.py 与现渲染输出一致
    （渲染器-产物漂移哨兵）。"""
    t1 = render_half.render_half_taper(render_half.INSTANCE_PARAMS,
                                       render_half.BAND, render_half.MESH_MM,
                                       "msl")
    t2 = render_half.render_half_taper(render_half.INSTANCE_PARAMS,
                                       render_half.BAND, render_half.MESH_MM,
                                       "msl")
    assert t1 == t2
    for name, excite in (("simulation_exc1.py", "msl"),
                         ("simulation_exc2.py", "pin")):
        artifact = _RUN_DIR / "half_anchor" / name
        assert artifact.exists(), f"缺渲染产物 {name}（先跑 render_half.py）"
        assert artifact.read_bytes().decode("utf-8") == (
            render_half.render_half_taper(render_half.INSTANCE_PARAMS,
                                          render_half.BAND,
                                          render_half.MESH_MM, excite))


def test_pin_contract_single_source_alignment(render_half):
    """R_PIN=round(Z_PV,4) 与 compose_meta taper pin z_ref 同源同值
    （compose pin 契约对齐证据）；盒式/参考基与 compose 契约同式。"""
    der = render_half.half_derived(render_half.INSTANCE_PARAMS,
                                   render_half.BAND, render_half.MESH_MM)
    assert der["r_pin"] == 22.8393          # criteria §11.1 钉值
    meta = json.loads((_RUN_DIR / "compose_run" / "compose_meta.json")
                      .read_text(encoding="utf-8"))
    pin = meta["instances"][0]["pins"]["siw"]   # taper_in.siw
    assert pin["z_ref_ohm"] == der["r_pin"]
    assert pin["port_type"] == "lumped"
    assert pin["cross_section"]["w_mm"] == pytest.approx(
        float(der["lay"]["w"]) * 1e3, rel=1e-12)
    # 截断面=v2 端口面守卫：末孔缘严格在 pin 面之前
    assert der["last_via_edge"] < der["y_cut"]
    assert der["via_half"] == (-0.001,)     # k=0 孔剔除（§11.1）
    assert der["y_max"] == pytest.approx(16.0 * der["base_m"], rel=1e-15)
    # 文本契约：边界/表头/CV/SIM 命名
    text = render_half.render_half_taper(render_half.INSTANCE_PARAMS,
                                         render_half.BAND,
                                         render_half.MESH_MM, "msl")
    assert ('SetBoundaryCond(["MUR", "MUR", "PML_8", "PML_8", "PEC", "MUR"])'
            in text)
    assert "R_PIN = 22.8393" in text
    assert "ref_impedance=50" in text and "ref_impedance=R_PIN" in text


# ─── 2) 离线 exec 审计（#212；脚本内 #152/#283/#347/v2port 守卫随 exec 全过）──

def _exec_truncated(render_half, excite: str) -> dict:
    text = render_half.render_half_taper(render_half.INSTANCE_PARAMS,
                                         render_half.BAND,
                                         render_half.MESH_MM, excite)
    cut = text.index("FDTD.Run(")
    scope: dict = {"__name__": "__main__",
                   "__file__": str(_RUN_DIR / "half_anchor" / "_audit.py")}
    exec(compile(text[:cut], "half_audit_test", "exec"), scope)
    return scope


@pytest.mark.parametrize("excite", ["msl", "pin"])
def test_offline_exec_audit_geometry(render_half, excite):
    """藩篱/板/锥连通/端口盒截断/激励唯一（两激励脚本各自审计）。"""
    scope = _exec_truncated(render_half, excite)
    csx = scope["CSX"]
    props = {str(csx.GetProperty(i).GetName()): csx.GetProperty(i)
             for i in range(csx.GetQtyProperties())}
    n_excite = sum(1 for p in props.values()
                   if str(p.GetTypeString()) == "Excitation")
    assert n_excite == 1                      # 单激励契约（#155：excite=0 无激励属性）
    via = list(props["siw_via"].GetAllPrimitives())
    assert len(via) == 2                      # 截断侧单孔 ×2 列
    h_sub = float(scope["H_SUB"])
    for c in via:
        assert float(c.GetStart()[1]) == pytest.approx(-0.001, abs=1e-15)
        assert float(c.GetStart()[2]) == 0.0 and float(c.GetStop()[2]) == h_sub
    # 顶壁板止于 pin 面 + 锥-板 SEAM 搭接连通（#310 预防）
    msl_top = props["msl_top"]
    polys, boxes = [], []
    for prim in msl_top.GetAllPrimitives():
        bb = np.asarray(prim.GetBoundBox(), dtype=float)
        (boxes if hasattr(prim, "GetStart") else polys).append(bb)
    assert len(polys) == 1 and len(boxes) >= 2
    seam = float(scope["SEAM"])
    y_plate = float(scope["Y_PLATE"])
    assert min(abs(polys[0][0][1]), abs(polys[0][1][1])) == pytest.approx(
        y_plate - seam, rel=1e-9)             # 锥内端越入板区
    plate = [b for b in boxes
             if abs(b[1][0] - b[0][0] - 2 * float(scope["DOM_X"])) < 1e-12]
    assert plate and plate[0][1][1] == pytest.approx(
        float(scope["Y_CUT"]), abs=1e-15)     # 板缘=pin 面
    # pin 端口盒（文字面已 assert 落格；此处实测盒边在网格线上）
    ys = np.asarray(scope["mesh"].GetLines("y"), dtype=float)
    for v in (scope["Y_CUT"] - scope["PY"], scope["Y_CUT"],
              scope["Y_CUT"] + scope["PY"], scope["Y_MIN"], scope["Y_MAX"]):
        assert float(np.min(np.abs(ys - v))) <= 1e-9


def test_offline_exec_audit_grid_cells_dt(render_half):
    """cells/dt_CFL 实测钉（§11.4 审计数字；字节确定 ⇒ 网格确定）。"""
    scope = _exec_truncated(render_half, "msl")
    mesh = scope["mesh"]
    lines = {ax: np.asarray(mesh.GetLines(ax), dtype=float)
             for ax in ("x", "y", "z")}
    cells = int(lines["x"].size * lines["y"].size * lines["z"].size)
    assert cells == 974700                   # §11.4 实测钉
    gaps = {ax: float(np.diff(v).min()) for ax, v in lines.items()}
    assert all(g > 1e-6 for g in gaps.values())   # #152
    dt = 1.0 / (299792458.0 * np.sqrt(sum(1.0 / gaps[a] ** 2
                                          for a in ("x", "y", "z"))))
    assert dt == pytest.approx(1.0117e-13, rel=2e-3)   # §11.4
    assert lines["y"].min() == pytest.approx(float(scope["Y_MIN"]), abs=1e-9)
    assert lines["y"].max() == pytest.approx(float(scope["Y_MAX"]), abs=1e-9)


# ─── 3) merge 全矩阵合并 ────────────────────────────────────────────────────

def _write5(path: Path, freq, s11, s21) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["freq_hz", "re_S11", "im_S11", "re_S21", "im_S21"])
        for i, fi in enumerate(freq):
            w.writerow([fi, s11[i].real, s11[i].imag,
                        s21[i].real, s21[i].imag])


def test_merge_sparams_full_matrix(tmp_path, render_half):
    """v4.1（§12）：跨基列做电压波→功率波换算后合并（S21×√(Z_MSL/Z_PIN)、
    S12×√(Z_PIN/Z_MSL)，对角原样）；raw 残差同报留痕；因子互逆。"""
    freq = np.linspace(9e9, 11e9, 5)
    r_pin = 22.8393
    k21 = np.sqrt(50.0 / r_pin)
    k12 = np.sqrt(r_pin / 50.0)
    s11_1 = np.array([0.1 + 0.02j] * 5)
    s21_1 = np.array([0.7 - 0.1j] * 5)
    s11_2 = np.array([0.3 + 0.05j] * 5)       # = L22（pin 基）
    s21_2 = np.array([0.68 - 0.12j] * 5)      # = L12
    p1 = tmp_path / "e1.csv"
    p2 = tmp_path / "e2.csv"
    out = tmp_path / "sparams.csv"
    _write5(p1, freq, s11_1, s21_1)
    _write5(p2, freq, s11_2, s21_2)
    audit = render_half.merge_sparams(p1, p2, out, z_pin=r_pin)
    with out.open(encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == render_half.HEADER9     # 9 列契约
    assert float(rows[1][1]) == pytest.approx(0.1)     # S11←exc1（对角原样）
    assert float(rows[1][7]) == pytest.approx(0.3)     # S22←exc2（对角原样）
    assert complex(float(rows[1][3]), float(rows[1][4])) == pytest.approx(
        s21_1[0] * k21)                                # S21×√(Z_MSL/Z_PIN)
    assert complex(float(rows[1][5]), float(rows[1][6])) == pytest.approx(
        s21_2[0] * k12)                                # S12×√(Z_PIN/Z_MSL)
    assert audit["wave_basis_conversion"]["s21_factor"] == pytest.approx(k21)
    assert audit["wave_basis_conversion"]["s12_factor"] == pytest.approx(k12)
    assert audit["wave_basis_conversion"]["s21_factor"] * \
        audit["wave_basis_conversion"]["s12_factor"] == pytest.approx(1.0)
    # 残差：换算后为主字段，raw 同报留痕
    assert audit["reciprocity_residual_max"] == pytest.approx(
        abs(s21_1[0] * k21 - s21_2[0] * k12))
    assert audit["reciprocity_residual_max_raw"] == pytest.approx(
        abs(s21_1[0] - s21_2[0]))
    assert audit["s21_mag_min"] == pytest.approx(
        float(np.min(np.abs(s21_1 * k21))))
    # 频栅不一致/表头违约 → 显式报错（#287/#248）
    _write5(p2, np.linspace(9e9, 11e9, 6),
            np.full(6, 0.3 + 0.05j), np.full(6, 0.68 - 0.12j))
    with pytest.raises(ValueError, match="频栅"):
        render_half.merge_sparams(p1, p2, out, z_pin=r_pin)
    bad = tmp_path / "bad.csv"
    bad.write_text("f,s11\n", encoding="utf-8")
    with pytest.raises(ValueError, match="列契约"):
        render_half._read5(bad)


def test_merge_wave_basis_conversion_restores_reciprocity(
        tmp_path, render_half, judge_c4):
    """P1 核心单测：合成**互易网络**（对称 Z 矩阵）→ 伪波原始比值表 M=
    (Z−D)(Z+D)⁻¹（D=diag(50, R_PIN)，=两激励各自的 uf_ref/uf_inc 电压波
    比）→ merge_sparams 电压波→功率波换算后互易必须恢复（S21=S12），且
    逐元素等于解析功率波 S^P=D^{-1/2}(Z−D)(Z+D)^{-1}D^{1/2}（§12 推导）。"""
    freq = np.linspace(9e9, 11e9, 7)
    r_pin = 22.8393
    d = np.array([50.0, r_pin])
    # 对称 Z 矩阵（互易；轻微频变+复数对称互易，含耗损形态）
    z = np.empty((freq.size, 2, 2), dtype=complex)
    for i, fi in enumerate(freq):
        z[i] = [[30.0 + 2.0 * (fi / 1e10), 10.0 + 2.0j],
                [10.0 + 2.0j, 25.0 - 1.0 * (fi / 1e10)]]
    d_mat = np.diag(d)                        # 对角参考基矩阵（勿按列广播）
    m = np.einsum("fij,fjk->fik", z - d_mat,  # (Z−D)(Z+D)^{-1}（逐频批式）
                  np.linalg.inv(z + d_mat))
    # 前置（缺陷形态）：原始电压波比不满足互易（d1≠d2 ⇒ M_10≠M_01）
    assert not np.allclose(m[:, 1, 0], m[:, 0, 1])
    p1 = tmp_path / "e1.csv"
    p2 = tmp_path / "e2.csv"
    _write5(p1, freq, m[:, 0, 0], m[:, 1, 0])   # exc1：S11、S21(raw)
    _write5(p2, freq, m[:, 1, 1], m[:, 0, 1])   # exc2：S22、S12(raw)
    out = tmp_path / "sparams.csv"
    render_half.merge_sparams(p1, p2, out, z_msl=50.0, z_pin=r_pin)
    f_m, s = judge_c4.read_sparams_full(out)
    assert np.array_equal(f_m, freq)
    # 互易恢复：换算后 S21 与 S12 逐点相等（浮点级）
    assert np.allclose(s[:, 1, 0], s[:, 0, 1], rtol=1e-12, atol=1e-15)
    # 逐元素对齐解析功率波 S^P（对角 factor=1 原样、跨基 ×√(Z_src/Z_dest)）
    # S^P_ij = M_ij·√(d_j/d_i)（=D^{-1/2}·M·D^{1/2} 逐元素式）
    s_pow = m * (np.sqrt(d)[None, None, :] / np.sqrt(d)[None, :, None])
    assert np.allclose(s, s_pow, rtol=1e-12, atol=1e-15)
    # 对角反射不受换算影响
    assert np.allclose(s[:, 0, 0], m[:, 0, 0], rtol=1e-15)
    assert np.allclose(s[:, 1, 1], m[:, 1, 1], rtol=1e-15)


def test_merged_csv_current_sha_reconciliation(tmp_path, render_half):
    """P2 幂等键：sparams.csv 必须出自当前渲染字节（merge_audit.sha256 ==
    render_input.json 现值）；漂移/缺审计/坏 JSON 一律 False（重跑）。"""
    out = tmp_path / "sparams.csv"
    out.write_text("x\n", encoding="utf-8")
    info_path = tmp_path / "render_input.json"
    sha = {"simulation_exc1.py": "a" * 64, "simulation_exc2.py": "b" * 64}
    info_path.write_text(json.dumps({"sha256": sha}), encoding="utf-8")
    audit_path = tmp_path / "merge_audit.json"
    # 缺审计 → False
    assert render_half._merged_csv_current(out, info_path) is False
    # sha 一致 → True
    audit_path.write_text(json.dumps({"sha256": sha}), encoding="utf-8")
    assert render_half._merged_csv_current(out, info_path) is True
    # sha 漂移 → False
    audit_path.write_text(json.dumps(
        {"sha256": {**sha, "simulation_exc1.py": "c" * 64}}),
        encoding="utf-8")
    assert render_half._merged_csv_current(out, info_path) is False
    # 旧版审计无 sha256 键 → False（不静默复用过期产物）
    audit_path.write_text(json.dumps({"n_points": 401}), encoding="utf-8")
    assert render_half._merged_csv_current(out, info_path) is False
    # 坏 JSON → False
    audit_path.write_text("{not json", encoding="utf-8")
    assert render_half._merged_csv_current(out, info_path) is False
    # sparams.csv 缺失 → False
    out.unlink()
    audit_path.write_text(json.dumps({"sha256": sha}), encoding="utf-8")
    assert render_half._merged_csv_current(out, info_path) is False


def test_budget_partial_record_shape(tmp_path, render_half, monkeypatch):
    """P2 #318：超预算 PARTIAL 判读档载荷（port_ut 末行时间轴快照随档，
    best-effort 缺数据为 None 不抛）。"""
    monkeypatch.setattr(render_half, "ANCHOR_DIR", tmp_path)
    rec = render_half.budget_partial_record(1500.0)
    assert rec["verdict"] == "PARTIAL(超预算)"
    assert rec["budget_s"] == render_half.BUDGET_S
    assert rec["wall_s"] == pytest.approx(1500.0)
    assert rec["port_ut_t_end_s"] == {"exc1": None, "exc2": None}
    # 有 port_ut 产物时快照末行时间轴
    fd = tmp_path / "fdtd_exc1"
    fd.mkdir()
    (fd / "port_ut_1").write_text("0.0 0\n1.0e-9 0.5\n2.5e-9 0\n",
                                  encoding="utf-8")
    rec = render_half.budget_partial_record(1500.0)
    assert rec["port_ut_t_end_s"]["exc1"] == pytest.approx(2.5e-9)


# ─── 4) judge v4 开关（假曲线，tmp 全隔离）──────────────────────────────────

def test_judge_default_baseline_is_half(judge_c4):
    """缺省轨=half（§11.3）：argparse 缺省 + 调度缺省双钉。"""
    src_code = (_RUN_DIR / "judge_c4.py").read_text(encoding="utf-8")
    assert 'default="half"' in src_code
    assert 'choices=("half", "full")' in src_code
    assert judge_c4.cascade_baseline.__defaults__ == ("full",)
    with pytest.raises(ValueError, match="baseline"):
        judge_c4.cascade_baseline("bogus")


def test_cascade_half_mixed_basis_roundtrip(judge_c4, tmp_path, monkeypatch):
    """混合基全链路钉：50Ω 基真网络 →（inverse renorm）混合基 CSV 载荷 →
    判读侧 [50,R_PIN] 网络 renormalize(50) 必须精确还原，且级联=
    net50 × run × flip(net50)（镜像逻辑+双 renorm 基处理一次钉死）。

    注：物理半实例（MSL 端≠SIW 端）在任何基下均非对称，flip 无恒等
    简化——非对称假数据即真实形态。
    """
    freq = np.linspace(9e9, 11e9, 11)
    z_pin = 22.8393
    s50 = np.zeros((11, 2, 2), complex)
    s50[:, 0, 0] = 0.15 + 0.05j
    s50[:, 1, 1] = 0.12 + 0.04j               # 非对称（真实半实例形态）
    s50[:, 0, 1] = 0.8 - 0.03j
    s50[:, 1, 0] = 0.8 - 0.03j
    import skrf

    net50 = skrf.Network(frequency=skrf.Frequency.from_f(freq, unit="Hz"),
                         s=s50, z0=50.0)
    mixed = net50.copy()
    mixed.renormalize(np.array([50.0, z_pin]))   # 50Ω 基 → 混合基（CSV 载荷）
    with (tmp_path / "sparams.csv").open("w", newline="",
                                         encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(judge_c4.HEADER9)
        for i, fi in enumerate(freq):
            w.writerow([fi, mixed.s[i, 0, 0].real, mixed.s[i, 0, 0].imag,
                        mixed.s[i, 1, 0].real, mixed.s[i, 1, 0].imag,
                        mixed.s[i, 0, 1].real, mixed.s[i, 0, 1].imag,
                        mixed.s[i, 1, 1].real, mixed.s[i, 1, 1].imag])
    for tag in ("exc1", "exc2"):
        (tmp_path / f"simulation_{tag}.py").write_text(
            f"R_PIN = {z_pin}\n", encoding="utf-8")
    monkeypatch.setattr(judge_c4, "HALF_CSV", tmp_path / "sparams.csv")
    monkeypatch.setattr(judge_c4, "HALF_SCRIPTS",
                        (tmp_path / "simulation_exc1.py",
                         tmp_path / "simulation_exc2.py"))
    f_base, s21_half = judge_c4.cascade_baseline_half()
    assert np.array_equal(f_base, freq)
    # 期望：全 50Ω 基级联（run 与 judge 同路径：真 siw CSV→R_PORT 基→renorm）
    f_s, s11_r, s21_r = judge_c4.read_sparams(judge_c4.SIW_CSV)
    s11_r = np.interp(freq, f_s, s11_r.real) + 1j * np.interp(
        freq, f_s, s11_r.imag)
    s21_r = np.interp(freq, f_s, s21_r.real) + 1j * np.interp(
        freq, f_s, s21_r.imag)
    run = judge_c4._network(freq, s11_r, s21_r, z0=judge_c4.siw_z_base_ohm())
    run.renormalize(50.0)
    flip = net50.copy()
    flip.s = np.array(net50.s[:, ::-1, ::-1], dtype=complex)
    from skrf.network import connect

    expect = connect(connect(net50, 1, run, 0), 1, flip, 0)
    assert np.allclose(s21_half, np.asarray(expect.s[:, 1, 0]),
                       rtol=1e-9, atol=1e-12)


@pytest.fixture()
def judge_fakes(judge_c4, tmp_path, monkeypatch):
    """judge 全输入假曲线隔离：RUN_DIR/COMPOSE_DIR/锚 CSV 全指 tmp。"""
    freq = np.linspace(9e9, 11e9, 41)
    z_pin = 22.8393
    anchor = tmp_path / "anchor"
    anchor.mkdir()
    comp = tmp_path / "compose_run"
    comp.mkdir()
    (comp / "compose_meta.json").write_text(
        json.dumps({"band_ghz": [9.0, 11.0]}), encoding="utf-8")
    s = np.zeros((41, 2, 2), complex)
    s[:, 0, 0] = 0.15 + 0.05j
    s[:, 1, 1] = 0.12 + 0.04j                 # 非对称（真实半实例形态）
    s[:, 0, 1] = 0.8 - 0.03j
    s[:, 1, 0] = 0.8 - 0.03j
    with (anchor / "sparams.csv").open("w", newline="",
                                       encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(judge_c4.HEADER9)
        for i, fi in enumerate(freq):
            w.writerow([fi, s[i, 0, 0].real, s[i, 0, 0].imag,
                        s[i, 1, 0].real, s[i, 1, 0].imag,
                        s[i, 0, 1].real, s[i, 0, 1].imag,
                        s[i, 1, 1].real, s[i, 1, 1].imag])
    for tag in ("exc1", "exc2"):
        (anchor / f"simulation_{tag}.py").write_text(
            f"R_PIN = {z_pin}\n", encoding="utf-8")
    taper = tmp_path / "taper.csv"
    _write5(taper, np.linspace(6e9, 13e9, 41),
            np.full(41, 0.2 + 0.1j), np.full(41, 0.6 - 0.2j))
    siw = tmp_path / "siw.csv"
    _write5(siw, np.linspace(6e9, 13e9, 41),
            np.full(41, 0.3 - 0.1j), np.full(41, 0.5 + 0.1j))
    monkeypatch.setattr(judge_c4, "RUN_DIR", tmp_path)
    monkeypatch.setattr(judge_c4, "COMPOSE_DIR", comp)
    monkeypatch.setattr(judge_c4, "HALF_CSV", anchor / "sparams.csv")
    monkeypatch.setattr(judge_c4, "HALF_SCRIPTS",
                        (anchor / "simulation_exc1.py",
                         anchor / "simulation_exc2.py"))
    monkeypatch.setattr(judge_c4, "TAPER_CSV", taper)
    monkeypatch.setattr(judge_c4, "SIW_CSV", siw)
    return {"freq": freq, "anchor_csv": anchor / "sparams.csv",
            "comp": comp, "z_pin": z_pin, "s": s}


def test_judge_half_baseline_pass_fail_missing(judge_c4, judge_fakes):
    """端到端：组合假数据=half 基线 → PASS(delta≈0)；幅值×0.5 → FAIL；
    half 锚缺失 → MISSING exit 2（fail-closed，不产假数字 #122）。"""
    f_base, s21_base = judge_c4.cascade_baseline("half")
    # PASS：compose 假 CSV = 基线自身
    with (judge_fakes["comp"] / "sparams.csv").open(
            "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(judge_c4.HEADER)
        for i, fi in enumerate(f_base):
            w.writerow([fi, 0.1, 0.01, s21_base[i].real, s21_base[i].imag])
    result, code = judge_c4.judge(sanity=False, baseline="half")
    assert result["baseline"] == "half"
    assert result["verdict"] == "PASS" and code == 0
    assert result["delta_db_max"] == pytest.approx(0.0, abs=1e-9)
    assert result["half_pin_z_ohm"] == judge_fakes["z_pin"]
    assert result["half_reciprocity_residual_max"] is not None
    # FAIL：幅值 ×0.5（−6dB）
    with (judge_fakes["comp"] / "sparams.csv").open(
            "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(judge_c4.HEADER)
        for i, fi in enumerate(f_base):
            w.writerow([fi, 0.1, 0.01, 0.5 * s21_base[i].real,
                        0.5 * s21_base[i].imag])
    result, code = judge_c4.judge(sanity=False, baseline="half")
    assert result["verdict"] == "FAIL" and code == 1
    assert result["delta_db_max"] == pytest.approx(6.0, abs=0.1)
    # MISSING：half 锚缺失 fail-closed
    judge_fakes["anchor_csv"].unlink()
    result, code = judge_c4.judge(sanity=False, baseline="half")
    assert result["verdict"] == "MISSING" and code == 2
    assert "基线锚不可用" in result["message"]


def test_judge_full_baseline_path_preserved(judge_c4, judge_fakes):
    """--baseline full：§10 v3 路径可复现（taper×siw×taper 基线下
    基线自级联组合假数据 → PASS）。"""
    f_base, s21_base = judge_c4.cascade_baseline("full")
    with (judge_fakes["comp"] / "sparams.csv").open(
            "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(judge_c4.HEADER)
        for i, fi in enumerate(f_base):
            w.writerow([fi, 0.1, 0.01, s21_base[i].real, s21_base[i].imag])
    result, code = judge_c4.judge(sanity=False, baseline="full")
    assert result["baseline"] == "full"
    assert result["verdict"] == "PASS" and code == 0
    assert "half_pin_z_ohm" not in result     # full 轨无 half 附加字段
    with pytest.raises(ValueError, match="baseline"):
        judge_c4.cascade_baseline("bogus")
