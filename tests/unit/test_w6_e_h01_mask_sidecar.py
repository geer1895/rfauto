"""W6-E H-01 openEMS csv 掩码自描述定向门（Phase 6 批，2026-10-06）。

判据（ra_criteria SPECS §六 6.3 预声明，B 案=sidecar JSON）：
- 写出端：render_script 四分支（default/4 口轮转/nway/3 口）在 sparams.csv
  旁并排落 sparams.mask.json（schema_version/n_ports/excite_port/
  measured_mask/filler_columns/reciprocity_filled/symmetry_filled）；
- B 案核心承诺：csv 写出段字节零漂移（渲染 diff 仅追加 sidecar 段，
  证据 runs/w6_phase6/w6e/{pre,post}_render_h01/ 实测 removed=0）；本文件
  另以冻结 csv writer 块逐字节钉住 default 尾段；
- 读入端：health_service._load_sparams_csv sidecar 权威 → 缺档回退启发式
  （旧归档永续可读：5 列/9 列双激励/fdtd 子目录三形态零破坏）；
- G11 双态钉：填充副本样本（S21=S11 逐位副本+sidecar 如实标未测）→ 互易
  因子 UNKNOWN；sidecar 显式双向已测 → 因子可判；
- #316 方向钉：sidecar 损坏（截断 JSON）→ errors 留痕+S 因子 UNKNOWN，
  不回退 Touchstone 全矩阵假阳性；形状不符 → 掩码回 None=全矩阵已测
  （多报方向先例）。

零仿真零真机：写出端=渲染文本+stub exec 尾段（#212 几何段级审计同款手法
延伸到产物落盘段），读入端=tmp 目录合成产物（#144 chdir 隔离不适用——
全程 tmp_path，不触真实 runs）。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from rfauto.adapters.openems_templates import render_script
from rfauto.service import health_service as hs
from tests.unit import _geometry_audit_helpers as gh

NL = chr(10)


def _render(template: str, excite_port: int = 1) -> str:
    return render_script(template, dict(gh.TEMPLATE_NOMINAL[template]),
                         gh.band_for(template), excite_port=excite_port)


# ── 写出端：渲染文本面 ────────────────────────────────────────────────────────


class TestRenderSidecarText:
    def test_four_branches_emit_sidecar_block(self):
        """四分支渲染产物均含 sidecar 写出段（replace 到 sparams.mask.json）。"""
        for template, ep in (("wilkinson", 1), ("ratrace", 2),
                             ("nway_wilkinson", 1), ("diplexer", 3)):
            text = _render(template, ep)
            assert "sparams.mask.json" in text, template
            assert '"measured_mask"' in text, template
            assert '"schema_version": "1"' in text, template

    def test_rotation_mask_literal_matches_excite_port(self):
        """轮转掩码字面量=excite_port 列全测（行=响应口；其余未测）。"""
        text = _render("ratrace", 2)
        assert ('"excite_port": 2' in text
                and '"n_ports": 4' in text)
        assert ('[[False, True, False, False], [False, True, False, False],'
                in text)
        text3 = _render("diplexer", 3)
        assert ('"excite_port": 3' in text3 and '"n_ports": 3' in text3)
        assert "[[False, False, True], [False, False, True], " \
               "[False, False, True]]" in text3
        text5 = _render("nway_wilkinson", 1)
        assert ('"excite_port": 1' in text5 and '"n_ports": 5' in text5)
        assert text5.count("[True, False, False, False, False]") == 5

    def test_default_tail_tracks_s21_filler(self):
        """default 尾段：_S21_FILLER 标记在 try/except 两臂就位（R6-4
        逐位副本案例→filler_columns 如实标记）。"""
        text = _render("wilkinson", 1)
        assert "_S21_FILLER = False" in text
        assert ("    S21 = _port1.uf_ref / _port1.uf_inc"
                f"  # single-port fallback{NL}    _S21_FILLER = True") in text
        assert "_S21_MEASURED = not _S21_FILLER" in text
        assert "'S21': 'S11_copy'" in text

    def test_csv_writer_section_byte_identical_to_frozen_block(self):
        """B 案核心承诺（in-repo 钉）：default 尾段 csv writer 块与改动前
        冻结块逐字节一致（sidecar 段纯追加，不触碰写出段）。"""
        text = _render("wilkinson", 1)
        frozen = NL.join([
            "if not _LOOP_DONE:",
            '    with open(CSV_PATH, "w", newline="") as fh:',
            "        w = csv.writer(fh)",
            "        if S31 is not None and S23 is not None:",
            '            w.writerow(["freq_hz", "re_S11", "im_S11", "re_S21", "im_S21",',
            '                        "re_S31", "im_S31", "re_S23", "im_S23"])',
            "            for i, fi in enumerate(f):",
            "                w.writerow([fi, S11[i].real, S11[i].imag, S21[i].real,",
            "                            S21[i].imag, S31[i].real, S31[i].imag,",
            "                            S23[i].real, S23[i].imag])",
            "        else:",
            '            w.writerow(["freq_hz", "re_S11", "im_S11", "re_S21", "im_S21"])',
            "            for i, fi in enumerate(f):",
            "                w.writerow([fi, S11[i].real, S11[i].imag, S21[i].real, S21[i].imag])",
        ]) + NL
        assert frozen in text
        # sidecar 段在 csv writer 块之后（同一缩进层级，still inside if）
        assert text.index(frozen) < text.index("sparams.mask.json")


class TestRenderTailExecRoundtrip:
    """stub exec 尾段→csv+sidecar 落盘→读入端 roundtrip（零仿真）。"""

    def _exec_tail(self, tmp: Path, *, s21_filler: bool):
        text = _render("wilkinson", 1)
        start = text.index("_S21_FILLER = False")
        tail = text[start:]
        f = np.linspace(2.0e9, 3.0e9, 401)
        s11 = 0.05 * np.ones(401, dtype=complex)
        s21 = (0.7 + 0.01j) * np.ones(401, dtype=complex)
        class _P1:
            CalcPort = staticmethod(lambda *a, **k: None)
            uf_ref = np.ones(401, dtype=complex)
            uf_inc = np.ones(401, dtype=complex)

        scope: dict = {
            "__name__": "__main__",
            "SIM_PATH": str(tmp / "fdtd"),
            "_port1": _P1(),
            "CSV_PATH": str(tmp / "sparams.csv"),
            "csv": __import__("csv"),
            "f": f,
            "S11": s11,
            "S21": s21 if not s21_filler else s11.copy(),  # 逐位副本
            "S31": None,
            "S23": None,
            "_port2": type("_P2", (), {"CalcPort": lambda self, *a, **k: (
                (_ for _ in ()).throw(RuntimeError("probe gone"))
                if s21_filler else None)})(),
        }
        exec(compile(tail, "h01_tail", "exec"), scope)
        return tmp / "sparams.csv", tmp / "sparams.mask.json"

    def test_tail_exec_writes_csv_and_sidecar(self, tmp_path):
        csv_path, sc_path = self._exec_tail(tmp_path, s21_filler=True)
        assert csv_path.is_file() and sc_path.is_file()
        doc = json.loads(sc_path.read_text(encoding="utf-8"))
        # spec 6.2 键集（#314 全语义 + 版本戳 + 激励口）
        assert doc["schema_version"] == "1"
        assert doc["n_ports"] == 2 and doc["excite_port"] == 1
        assert doc["measured_mask"] == [[True, False], [False, False]]
        assert doc["filler_columns"] == {"S21": "S11_copy"}
        assert doc["reciprocity_filled"] == []
        assert doc["symmetry_filled"] == [[1, 1]]

    def test_roundtrip_sidecar_mask_authoritative(self, tmp_path):
        """读入端：sidecar 在档 → 掩码权威（fallback 样本 [[T,F],[F,F]]，
        与启发式 [[T,F],[T,F]] 不同——权威性可区分）。"""
        _csv_path, _sc = self._exec_tail(tmp_path, s21_filler=True)
        errors: list[str] = []
        out = hs._load_sparams_csv(tmp_path, errors)
        assert out is not None and not errors, errors
        _freq, _s, mask = out
        assert mask.tolist() == [[True, False], [False, False]]

    def test_tail_exec_normal_path_marks_measured(self, tmp_path):
        """port2 正常路径：S21 真测量 → measured [[T,F],[T,F]] +
        reciprocity_filled [[0,1]]（S12:=S21），零 filler。"""
        text = _render("wilkinson", 1)
        tail = text[text.index("_S21_FILLER = False"):]
        class _P1:
            CalcPort = staticmethod(lambda *a, **k: None)
            uf_ref = np.ones(401, dtype=complex)
            uf_inc = np.ones(401, dtype=complex)

        scope: dict = {
            "__name__": "__main__",
            "SIM_PATH": str(tmp_path / "fdtd"),
            "_port1": _P1(),
            "CSV_PATH": str(tmp_path / "sparams.csv"),
            "csv": __import__("csv"),
            "f": np.linspace(2.0e9, 3.0e9, 401),
            "S11": 0.05 * np.ones(401, dtype=complex),
            "S21": (0.7 + 0.01j) * np.ones(401, dtype=complex),
            "S31": None,
            "S23": None,
            "_port2": type("P2", (), {"CalcPort": staticmethod(lambda *a, **k: None), "uf_ref": np.ones(401, dtype=complex)})(),
        }
        exec(compile(tail, "h01_tail_ok", "exec"), scope)
        doc = json.loads((tmp_path / "sparams.mask.json").read_text(encoding="utf-8"))
        assert doc["measured_mask"] == [[True, False], [True, False]]
        assert doc["filler_columns"] == {}
        assert doc["reciprocity_filled"] == [[0, 1]]


# ── 读入端：向后兼容（旧档案三形态零破坏） ──────────────────────────────────


class TestBackwardCompatNoSidecar:
    @staticmethod
    def _write_csv(path: Path, rows: list[str]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(NL.join(rows) + NL, encoding="utf-8")
        return path

    def test_three_legacy_forms_mask_identical_to_heuristic(self, tmp_path):
        """spec 6.3 旧档案回归：5 列 / 9 列双激励 / fdtd 子目录三形态，
        无 sidecar 掩码与现启发式逐位一致。"""
        five_col = self._write_csv(tmp_path / "run_a" / "sparams.csv", [
            "freq_hz,re_S11,im_S11,re_S21,im_S21",
            "1e9,0.05,0.0,0.7,0.01",
            "2e9,0.06,0.0,0.71,0.01",
        ])
        nine_col = self._write_csv(tmp_path / "run_b" / "sparams.csv", [
            "freq_hz,re_S11,im_S11,re_S21,im_S21,re_S31,im_S31,re_S23,im_S23",
            "1e9,0.05,0.0,0.7,0.01,0.7,0.02,0.01,0.0",
            "2e9,0.06,0.0,0.71,0.01,0.71,0.02,0.01,0.0",
        ])
        fdtd_col = self._write_csv(tmp_path / "run_c" / "fdtd" / "sparams.csv", [
            "freq_hz,re_S11,im_S11,re_S21,im_S21",
            "1e9,0.05,0.0,0.7,0.01",
        ])
        errors: list[str] = []
        for run_dir in (tmp_path / "run_a", tmp_path / "run_b", tmp_path / "run_c"):
            out = hs._load_sparams_csv(run_dir, errors)
            assert out is not None
            _freq, _s, mask = out
            heuristic = hs._parse_sparams_csv_masked(
                run_dir / "sparams.csv" if (run_dir / "sparams.csv").is_file()
                else run_dir / "fdtd" / "sparams.csv")
            assert mask.tolist() == np.asarray(heuristic[2]).tolist()
        assert not errors, errors
        assert five_col.is_file() and nine_col.is_file() and fdtd_col.is_file()

    def test_sidecar_shape_mismatch_falls_back_full_measured(self, tmp_path):
        """sidecar 形状与 csv 矩阵不符（4 口掩码 vs 5 列 csv 的 2×2 矩阵）
        → errors 留痕 + 掩码 None=全矩阵已测（#316 形状不符多报方向）。"""
        self._write_csv(tmp_path / "sparams.csv", [
            "freq_hz,re_S11,im_S11,re_S21,im_S21",
            "1e9,0.05,0.0,0.7,0.01",
        ])
        (tmp_path / "sparams.mask.json").write_text(json.dumps({
            "schema_version": "1", "n_ports": 4, "excite_port": 2,
            "measured_mask": [[False, True, False, False]] * 4,
            "filler_columns": {}, "reciprocity_filled": [],
            "symmetry_filled": [],
        }), encoding="utf-8")
        errors: list[str] = []
        out = hs._load_sparams_csv(tmp_path, errors)
        assert out is not None
        _freq, _s, mask = out
        assert mask is None
        assert any("形状与 csv 矩阵不符" in e for e in errors), errors


# ── G11 双态钉 + #316 方向钉（health_check_run 集成面） ─────────────────────


def _write_sidecar(run_dir: Path, doc: dict) -> None:
    (run_dir / "sparams.mask.json").write_text(
        json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def _copy_sample_run(run_dir: Path, *, s21_equals_s11: bool = True) -> None:
    """合成 5 列单激励 run 目录（S21 列=S11 逐位副本=单端口 fallback 形态）。"""
    run_dir.mkdir(parents=True, exist_ok=True)
    s11 = 0.05 + 0.0j
    s21 = s11 if s21_equals_s11 else 0.7 + 0.01j
    rows = ["freq_hz,re_S11,im_S11,re_S21,im_S21"]
    for k in range(20):
        rows.append(f"{1e9 + k * 1e7:g},{s11.real:g},0.0,{s21.real:g},{s21.imag:g}")
    (run_dir / "sparams.csv").write_text(NL.join(rows) + NL, encoding="utf-8")


def _reciprocity_factor(report: dict) -> dict:
    for fac in report["factors"]:
        if fac.get("factor") == "reciprocity" or fac.get("name") == "reciprocity":
            return fac
    raise AssertionError(f"reciprocity factor 缺失: {[f.get('factor', f.get('name')) for f in report['factors']]}")


class TestG11DoubleState:
    def test_filler_copy_sidecar_yields_unknown(self, tmp_path):
        """G11 双态①：5 列副本样本 + sidecar 如实标未测 → 掩码双向 False
        → 互易因子 UNKNOWN（不凑 PASS 也不假 FAIL）。"""
        run_dir = tmp_path / "r_copy"
        _copy_sample_run(run_dir)
        _write_sidecar(run_dir, {
            "schema_version": "1", "n_ports": 2, "excite_port": 1,
            "measured_mask": [[True, False], [False, False]],
            "filler_columns": {"S21": "S11_copy"},
            "reciprocity_filled": [], "symmetry_filled": [[1, 1]],
        })
        report = hs.health_check_run("r_copy", runs_dir=tmp_path)
        fac = _reciprocity_factor(report)
        assert fac["status"] == "UNKNOWN", fac

    def test_sidecar_both_measured_yields_decidable(self, tmp_path):
        """G11 双态②：sidecar 显式声明 (0,1)/(1,0) 双向独立已测 → 因子可判
        （合成互易样本 → PASS，非 UNKNOWN）。"""
        run_dir = tmp_path / "r_pair"
        _copy_sample_run(run_dir, s21_equals_s11=False)
        _write_sidecar(run_dir, {
            "schema_version": "1", "n_ports": 2, "excite_port": 1,
            "measured_mask": [[True, True], [True, False]],
            "filler_columns": {}, "reciprocity_filled": [],
            "symmetry_filled": [[1, 1]],
        })
        report = hs.health_check_run("r_pair", runs_dir=tmp_path)
        fac = _reciprocity_factor(report)
        assert fac["status"] == "PASS", fac


class TestCorruptSidecar316:
    def test_truncated_sidecar_no_touchstone_fallback(self, tmp_path):
        """#316 方向钉：sidecar 截断 JSON → errors 留痕+S 因子 UNKNOWN，
        不回退 Touchstone 全矩阵假阳性（results/params.s2p 在档也不读）。"""
        run_dir = tmp_path / "r_corrupt"
        _copy_sample_run(run_dir)
        (run_dir / "sparams.mask.json").write_text(
            '{"schema_version": "1", "measured_mask": [[Tru', encoding="utf-8")
        # 全矩阵 Touchstone（S12≠S21，若被回退读入即互易 FAIL 假阳性通道）
        # 最小 cost 产物：让体检越过"全空产物"早退，S 因子以 UNKNOWN 行呈现
        trials = run_dir / "trials"
        trials.mkdir()
        (trials / "trial_0001.json").write_text(
            json.dumps({"trial_number": 1, "cost": 1.5}), encoding="utf-8")
        res = run_dir / "results"
        res.mkdir()
        rows = ["# GHZ S RI R 50"]
        for k in range(5):
            rows.append(f"{1 + k * 0.1:g} 0.05 0.0 0.30 0.0 0.70 0.0 0.05 0.0")
        (res / "params.s2p").write_text(NL.join(rows) + NL, encoding="utf-8")

        report = hs.health_check_run("r_corrupt", runs_dir=tmp_path)
        assert any("sidecar 损坏" in e for e in report["errors"]), report["errors"]
        fac = _reciprocity_factor(report)
        assert fac["status"] == "UNKNOWN", fac
        assert "S 参数缺失" in str(fac.get("detail", "")), fac

    def test_sidecar_missing_key_also_corrupt(self, tmp_path):
        """在档但缺 measured_mask 键 → 同走损坏通道（多报不放过）。"""
        run_dir = tmp_path / "r_badkey"
        _copy_sample_run(run_dir)
        (run_dir / "sparams.mask.json").write_text(
            json.dumps({"schema_version": "1", "n_ports": 2}), encoding="utf-8")
        errors: list[str] = []
        with pytest.raises(hs._SparamsCsvCorrupt, match="sidecar 损坏"):
            hs._load_sparams_csv(run_dir, errors)
        assert any("形状非法" in e for e in errors), errors
