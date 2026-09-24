"""c3 重设计出处纪律单测（criteria.md §四）。

覆盖：
① render_input_sha256 确定性（同名义同哈希、改 res_len 变哈希）；
② crosscheck_run_literal：字节一致 ok / 篡改几何字面量不 ok / 缺档案不 ok
   （#122 不臆造）/ 存在但畸形不 ok 不裸抛（E-M2）；
③ registration_freshness 时戳边界（mtime ≥ commit；缺失 → None）；
④ synthesis 主流程产物带 render_input_sha256（tmp_path --out 端到端，零仿真）。
真机层全 mock/零依赖：不碰 openEMS/HFSS、零网络、零 git（nominal_commit_ts
经 monkeypatch 注入）。
"""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
SCRIPTS = REPO / "scripts"
for _p in (SRC, SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


syn = _load_script("c3_redesign_synthesis")
from rfauto.adapters.openems_templates import (
    TEMPLATE_NOMINAL,
    interdigital_design_from_order,
    render_script,
)

T = "interdigital"
NOMINAL = dict(TEMPLATE_NOMINAL[T])


def test_render_input_sha256_deterministic_and_sensitive():
    h1 = syn.render_input_sha256(T, NOMINAL)
    h2 = syn.render_input_sha256(T, dict(NOMINAL))
    assert h1 == h2 and len(h1) == 64
    tampered = dict(NOMINAL, res_len_mm=1.0)
    assert syn.render_input_sha256(T, tampered) != h1


def test_crosscheck_run_literal_byte_equal(tmp_path):
    mesh = syn.auto_mesh_mm(T, NOMINAL)
    text = render_script(T, dict(NOMINAL), (syn.F_LO, syn.F_HI),
                         mesh_resolution_mm=mesh)
    sim = tmp_path / "simulation.py"
    sim.write_text(text, encoding="utf-8")
    out = syn.crosscheck_run_literal(T, NOMINAL, sim)
    assert out == {"ok": True, "checked": True,
                   "n_lines": out["n_lines"], "reasons": []}
    assert out["n_lines"] > 20            # 几何段非空


def test_crosscheck_run_literal_detects_tamper(tmp_path):
    mesh = syn.auto_mesh_mm(T, NOMINAL)
    text = render_script(T, dict(NOMINAL), (syn.F_LO, syn.F_HI),
                         mesh_resolution_mm=mesh)
    tampered = text.replace("priority=10)  # bar1",
                            "priority=10)  # bar1  # 旧几何残迹")
    assert tampered != text               # 几何段内确有可区分字面量
    # 更直接：改棒长（几何段坐标变化）
    old = json.loads(json.dumps(NOMINAL))
    old["res_len_mm"] = 17.5252
    text_old = render_script(T, old, (syn.F_LO, syn.F_HI),
                             mesh_resolution_mm=mesh)
    sim = tmp_path / "simulation.py"
    sim.write_text(text_old, encoding="utf-8")
    out = syn.crosscheck_run_literal(T, NOMINAL, sim)
    assert out["ok"] is False and out["checked"] is True
    assert out["n_diff_lines"] > 0 and out["reasons"]


def test_crosscheck_run_literal_missing_archive(tmp_path):
    out = syn.crosscheck_run_literal(T, NOMINAL, tmp_path / "nope.py")
    assert out["ok"] is False and out["checked"] is False
    assert "不存在" in out["reasons"][0]


def test_crosscheck_run_literal_malformed_archive(tmp_path):
    """存在但畸形（缺几何段标记）的归档：显式 ok=False 带路径与畸形描述，
    不裸抛 StopIteration（E-M2，#105 观测面故障不炸整跑）。"""
    sim = tmp_path / "simulation.py"
    sim.write_text("print('garbage: 无 CSX.AddMetal 无 SetPriority')\n",
                   encoding="utf-8")
    out = syn.crosscheck_run_literal(T, NOMINAL, sim)
    assert out["ok"] is False and out["checked"] is False
    r = out["reasons"][0]
    assert "畸形" in r and "几何段标记缺失" in r
    assert str(sim) in r, "畸形描述必须含归档路径（调用方据此决策）"


def test_geometry_section_marker_missing_returns_none():
    """_geometry_section 对畸形文本返回 None 而非抛 StopIteration（E-M2）。"""
    assert syn._geometry_section("no markers here\n", T) is None
    assert syn._geometry_section("", T) is None


def test_registration_freshness_boundaries():
    now = time.time()
    assert syn.registration_freshness(now, now - 60.0) is True
    assert syn.registration_freshness(now - 60.0, now) is False
    assert syn.registration_freshness(now, None) is None       # 缺 commit 时戳
    assert syn.registration_freshness(None, now) is None       # 缺文件时戳
    assert syn.registration_freshness(None, None) is None


def test_synthesis_products_carry_render_hash(tmp_path, monkeypatch):
    """端到端（零仿真）：--out tmp 产 redesign_nominals.json，每模板带
    render_input_sha256 与出处三面（R2）。"""
    monkeypatch.setattr(syn, "nominal_commit_ts", lambda: 1700000000.0)
    rc = syn.main(["--out", str(tmp_path)])
    assert rc == 0
    doc = json.loads((tmp_path / "redesign_nominals.json").read_text(
        encoding="utf-8"))
    for t in ("interdigital", "combline", "sir_bpf"):
        block = doc["templates"][t]
        h = block["render_input_sha256"]
        assert isinstance(h, str) and len(h) == 64
        assert h == syn.render_input_sha256(t, block["new_nominal"])
        xchk = block["refix_run_geometry_crosscheck"]
        assert set(xchk) >= {"params", "literal_crosscheck",
                             "registration_freshness", "note"}
        assert xchk["literal_crosscheck"]["checked"] in (True, False)
    # 名义注册重生成守卫：设计链 auto 再生 == 注册 TEMPLATE_NOMINAL（4 位舍入）
    design = interdigital_design_from_order(3, 2.5, 0.05, 20.0, l_via_h=None)
    assert round(design["res_len_mm"], 4) == TEMPLATE_NOMINAL["interdigital"][
        "res_len_mm"]
