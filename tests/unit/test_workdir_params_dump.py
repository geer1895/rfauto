"""工作目录 params JSON 落盘 → import_workdir_runs 全链单测（#320-#322
实证 marchand/mline 0 行的战役侧补链）。

覆盖两层：
- 服务写出端 ``write_workdir_params_json``（与读取端 _params_from_json 同
  模块单一事实源）：np 标量收敛、非标量/非有限值显式拒绝、curve 同名 stem
  命名 + 显式引用嵌入；
- 各战役脚本抽出的 dump_point_params/dump_curve_params（importlib 加载，
  模块级零重活；smoke 脚本已包 main()）在 tmp_path 构造点目录后走
  import_workdir_runs 真导入：断言行数 1+、params_key=="params"、
  provenance.params_source 指向落盘 JSON——打通"脚本落盘→导入器识别"。
真机零依赖：不 import pyaedt/openEMS 绑定，不跑求解；健康门关闭（曲线为
合成文件，G11 语义不在本项范围）。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
for _p in (str(REPO / "scripts"), str(REPO / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from rfauto.service.dataset_service import (
    import_workdir_runs,
    query_dataset,
    write_workdir_params_json,
)

_CSV_HEADER = "freq_hz,re_S11,im_S11,re_S21,im_S21"


def _write_sparams_csv(path: Path, n: int = 5) -> None:
    rows = [",".join([f"{2.0e9 + i * 0.25e9:.1f}", "0.300000", "0.000000",
                      "0.500000", "0.000000"]) for i in range(n)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_CSV_HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def _load_script(name: str):
    """importlib 加载 scripts/<name>.py（dump 抽出函数所属；模块级可安全导入）。"""
    spec = importlib.util.spec_from_file_location(
        f"_params_dump_{name}", REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _import_and_rows(root: Path, models: str) -> tuple[dict[str, Any], list[dict]]:
    """runs_root=root 真导入（健康门关，合成曲线）并取回注册表行。"""
    out_dir = root / "datasets"
    res = import_workdir_runs(name="chain", runs_root=root,
                              out_dir=out_dir, models=[models],
                              health_gate=False)
    assert res["ok"], res.get("errors")
    q = query_dataset("chain", limit=50, out_dir=out_dir)
    assert q["ok"] and q["n_rows"] == res["n_rows"]
    return res, q["rows"]


# ── 服务写出端 ────────────────────────────────────────────────────────────────

class TestWriteWorkdirParamsJson:
    def test_writes_params_json_with_plain_scalars(self, tmp_path):
        p = write_workdir_params_json(tmp_path / "pt1", {
            "w_mm": np.float64(1.113), "line_len_mm": np.float64(40.0),
            "order": np.int64(3), "ok": np.bool_(True), "tag": "a"})
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["params"] == {"w_mm": 1.113, "line_len_mm": 40.0,
                                  "order": 3, "ok": True, "tag": "a"}
        assert all(type(v) in (int, float, bool, str)
                   for v in data["params"].values())

    def test_curve_same_stem_filename_and_reference(self, tmp_path):
        curve = tmp_path / "hfss_marchand_anchor_a.s4p"
        curve.write_text("!", encoding="utf-8")
        p = write_workdir_params_json(tmp_path, {"w_mm": 1.0}, curve=curve)
        assert p.name == "hfss_marchand_anchor_a.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["curve"] == "hfss_marchand_anchor_a.s4p"

    def test_curve_outside_dir_uses_relative_path_ref(self, tmp_path):
        """曲线在 point_dir 外 → 回退相对 JSON 所在目录的相对路径
        （不再退纯文件名），无歧义标记。"""
        other = tmp_path.parent / "elsewhere.s2p"
        p = write_workdir_params_json(tmp_path / "pt1", {"w_mm": 1.0}, curve=other)
        data = json.loads(p.read_text(encoding="utf-8"))
        # elsewhere.s2p 在 tmp 根（pt1 上两级）：relpath 从 point_dir 出发两级上溯
        assert data["curve"] == "../../elsewhere.s2p"
        assert "curve_ref_ambiguous" not in data

    def test_curve_cross_subdir_same_stem_refs_disambiguated(self, tmp_path):
        """主场景：曲线在 point_dir 外且多子目录同名 stem——相对路径
        引用可区分（旧回退 c.name 会把两个点写成同一个歧义引用 "pt1.s2p"）。"""
        ca = tmp_path / "batch_a" / "pt1.s2p"
        cb = tmp_path / "batch_b" / "pt1.s2p"
        for c in (ca, cb):
            c.parent.mkdir(parents=True, exist_ok=True)
            c.write_text("! synthetic\n", encoding="utf-8")
        pa = write_workdir_params_json(tmp_path / "points" / "run_a",
                                       {"w_mm": 1.0}, curve=ca)
        pb = write_workdir_params_json(tmp_path / "points" / "run_b",
                                       {"w_mm": 2.0}, curve=cb)
        da = json.loads(pa.read_text(encoding="utf-8"))
        db = json.loads(pb.read_text(encoding="utf-8"))
        assert da["curve"] == "../../batch_a/pt1.s2p"
        assert db["curve"] == "../../batch_b/pt1.s2p"
        assert da["curve"] != db["curve"]
        assert "curve_ref_ambiguous" not in da
        assert "curve_ref_ambiguous" not in db

    def test_explicit_filename_override(self, tmp_path):
        p = write_workdir_params_json(tmp_path / "pt1", {"w_mm": 1.0},
                                      curve=tmp_path / "x.s2p",
                                      filename="params.json")
        assert p.name == "params.json"

    def test_rejects_non_scalar_values(self, tmp_path):
        with pytest.raises(TypeError, match="非标量"):
            write_workdir_params_json(tmp_path, {"w_mm": [1.0, 2.0]})

    def test_rejects_nonfinite_float(self, tmp_path):
        with pytest.raises(ValueError, match="非有限"):
            write_workdir_params_json(tmp_path, {"w_mm": float("nan")})

    def test_rejects_empty_or_non_dict(self, tmp_path):
        with pytest.raises(TypeError):
            write_workdir_params_json(tmp_path, {})
        with pytest.raises(TypeError):
            write_workdir_params_json(tmp_path, [1, 2])  # type: ignore[arg-type]


# ── 全链：脚本 dump 抽出函数 → import_workdir_runs ──────────────────────────

class TestScriptDumpChain:
    """tmp_path 构造 runs/<工作目录>/… 形态 + 脚本 dump 函数落盘 → 真导入。"""

    def test_mline_pseudofloor_point_params(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "runs"
        work = root / "mline_pseudofloor" / "m1.2" / "w0.8500_L40.0"
        _write_sparams_csv(work / "sparams.csv")
        mod = _load_script("mline_pseudofloor_probe")
        pj = mod.dump_point_params(work, 0.85, 1.2)
        assert pj == work / "params.json"
        res, rows = _import_and_rows(root, "mline")
        assert res["n_points_skipped"] == 0 and res["n_rows"] == 1
        r = rows[0]
        assert r["run_id"] == "mline_pseudofloor" and r["model"] == "mline"
        assert json.loads(r["params_json"]) == {
            "w_mm": 0.85, "line_len_mm": 40.0, "mesh_mm": 1.2}
        prov = json.loads(r["provenance_json"])
        assert prov["params_key"] == "params"
        assert prov["params_source"] == "m1.2/w0.8500_L40.0/params.json"

    def test_mline_smoke_point_params(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "runs"
        work = root / "mline_smoke" / "pt1"
        _write_sparams_csv(work / "sparams.csv")
        mod = _load_script("smoke_mline_anchor")
        pj = mod.dump_point_params(work)
        assert pj == work / "params.json"
        res, rows = _import_and_rows(root, "mline")
        assert res["n_points_skipped"] == 0 and res["n_rows"] == 1
        r = rows[0]
        assert json.loads(r["params_json"]) == {
            "w_mm": 1.113, "line_len_mm": 40.0, "mesh_mm": 0.0}
        prov = json.loads(r["provenance_json"])
        assert prov["params_key"] == "params"
        assert prov["params_source"] == "pt1/params.json"

    def test_marchand_same_stem_params_multi_curve(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "runs"
        wd = root / "hfss_marchand_anchor"
        wd.mkdir(parents=True)
        curves = {}
        for tag, n in (("a", 4), ("b", 3)):
            c = wd / f"hfss_marchand_anchor_{tag}.s{n}p"
            c.write_text("! synthetic\n", encoding="utf-8")
            curves[tag] = c
        mod = _load_script("hfss_marchand_anchor")
        monkeypatch.setattr(mod, "OUT", wd)   # 重定向：测试绝不写真实 runs/
        ctx = mod.design_context()            # 离线确定性（core 名义点单源）
        for tag, c in curves.items():
            pj = mod.dump_curve_params(tag, c, ctx)
            assert pj == wd / f"hfss_marchand_anchor_{tag}.json"
        res, rows = _import_and_rows(root, "marchand")
        # 多曲线根目录：同名 stem 归属，两锚各一行（不同 anchor 参数不折叠）
        assert res["n_points_skipped"] == 0 and res["n_rows"] == 2
        by_prov = {json.loads(r["provenance_json"])["params_source"]: r
                   for r in rows}
        assert set(by_prov) == {"hfss_marchand_anchor_a.json",
                                "hfss_marchand_anchor_b.json"}
        for src, r in by_prov.items():
            prov = json.loads(r["provenance_json"])
            assert prov["params_key"] == "params"
            assert prov["n_ports"] == (4 if src.endswith("_a.json") else 3)
            params = json.loads(r["params_json"])
            assert params["anchor"] == ("a" if src.endswith("_a.json") else "b")
            assert params["w_mm"] == pytest.approx(ctx["w_mm"])
            assert params["l_sect_mm"] == pytest.approx(ctx["l_sect_mm"])

    def test_hairpin_smoke_point_params(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "runs"
        work = root / "hairpin_smoke" / "pt1"
        _write_sparams_csv(work / "sparams.csv")
        mod = _load_script("hairpin_smoke")
        params = {"order": 3, "w_mm": 1.1117, "arm_len_mm": 35.4676,
                  "arm_gap_mm": 3.0, "gap_mm": 0.7539, "tap_frac": 0.388478}
        pj = mod.dump_point_params(work, params, 0.4, 2.5, 0.05, 20.0)
        assert pj == work / "params.json"
        res, rows = _import_and_rows(root, "hairpin")
        assert res["n_points_skipped"] == 0 and res["n_rows"] == 1
        r = rows[0]
        assert r["model"] == "hairpin"
        got = json.loads(r["params_json"])
        assert got["gap_mm"] == 0.7539 and got["f0_ghz"] == 2.5
        assert got["mesh_mm"] == 0.4 and got["rl_db"] == 20.0
        prov = json.loads(r["provenance_json"])
        assert prov["params_key"] == "params"
        assert prov["params_source"] == "pt1/params.json"

    def test_slotline_arbitration_gamma_pair_dedup(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "runs"
        out = root / "slotline_arbitration" / "hfss"
        out.mkdir(parents=True)
        curves = []
        for name in ("hfss_slotline_wide.s2p", "hfss_slotline_wide_gamma.s2p"):
            c = out / name
            c.write_text("! synthetic\n", encoding="utf-8")
            curves.append(c)
        mod = _load_script("hfss_slotline_arbitration")
        monkeypatch.setattr(mod, "OUT", out)  # 重定向：测试绝不写真实 runs/
        variant = {"tag": "wide", "y_half_mm": 60.0, "z_bot_mm": 30.0,
                   "z_top_mm": 30.0}
        mod.dump_curve_params(variant, *curves)
        assert (out / "hfss_slotline_wide.json").is_file()
        assert (out / "hfss_slotline_wide_gamma.json").is_file()
        res, rows = _import_and_rows(root, "slotline")
        # 同一求解两份导出参数相同 → 指纹去重折叠为单点（n_dup=1）
        assert res["n_curves"] == 2 and res["n_dup"] == 1 and res["n_rows"] == 1
        r = rows[0]
        assert r["model"] == "slotline" and r["adapter"] == "hfss"
        got = json.loads(r["params_json"])
        assert got["w_slot_mm"] == 1.0 and got["port_y_half_mm"] == 60.0
        prov = json.loads(r["provenance_json"])
        assert prov["params_key"] == "params"
        assert prov["params_source"].endswith(".json")

    def test_slotline_transitions_gamma_pair_dedup(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "runs"
        out = root / "slotline_transitions" / "hfss"
        out.mkdir(parents=True)
        curves = []
        for name in ("hfss_trans.s2p", "hfss_trans_gamma.s2p"):
            c = out / name
            c.write_text("! synthetic\n", encoding="utf-8")
            curves.append(c)
        mod = _load_script("hfss_slotline_transitions")
        monkeypatch.setattr(mod, "OUT", out)  # 重定向：测试绝不写真实 runs/
        mod.dump_curve_params("trans", *curves)
        assert (out / "hfss_trans.json").is_file()
        res, rows = _import_and_rows(root, "slotline")
        assert res["n_dup"] == 1 and res["n_rows"] == 1
        got = json.loads(rows[0]["params_json"])
        assert got["kind"] == "trans" and got["w_msl_mm"] == 3.3439
        prov = json.loads(rows[0]["provenance_json"])
        assert prov["params_key"] == "params"
