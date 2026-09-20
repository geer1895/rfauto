"""KiCad CLI（E7a 接线批次）+ 审计修复批次测试。

离线路径：不依赖真机 KiCad——缺失 KiCad Python 时 generate_pcb 返回失败结果，
DRC 对缺失 PCB 文件返回 violations，均走确定性分支。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rfauto.adapters.kicad_drc import run_drc_kicad
from rfauto.adapters.kicad_pcell import PCBDesign
from rfauto.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # 强制 KiCad Python 不存在，走确定性失败分支（CI 无 KiCad 也能测）
    import rfauto.adapters.kicad_pcell as kp

    monkeypatch.setattr(kp, "KICAD_PYTHON", str(tmp_path / "no_kicad" / "python.exe"))
    yield


class TestPCBDesignFromDict:
    def test_roundtrip(self):
        design = PCBDesign.from_dict({
            "board_size": [40, 25],
            "traces": [{"start": [5, 10], "end": [20, 10], "width": 0.33}],
            "vias": [{"position": [20, 10], "drill": 0.3, "pad": 0.6}],
            "pads": [{"position": [2, 10], "size": [1.0, 1.0], "shape": "circle"}],
        })
        assert design.board_size == [40, 25]
        assert len(design.traces) == 1 and design.traces[0].width == 0.33
        assert len(design.vias) == 1 and len(design.pads) == 1

        d = design.to_dict()
        again = PCBDesign.from_dict(d)
        assert again.to_dict() == d

    def test_missing_required_key_raises(self):
        with pytest.raises(KeyError):
            PCBDesign.from_dict({"traces": [{"start": [0, 0]}]})  # 缺 end/width


class TestKicadCli:
    def _design_json(self, tmp_path: Path) -> Path:
        p = tmp_path / "design.json"
        p.write_text(json.dumps({
            "board_size": [50, 30],
            "traces": [{"start": [10, 15], "end": [30, 15], "width": 0.33}],
        }), encoding="utf-8")
        return p

    def test_pcb_without_kicad_fails_cleanly(self, tmp_path):
        result = runner.invoke(app, [
            "kicad", "pcb", str(self._design_json(tmp_path)),
            "--output", str(tmp_path / "out.kicad_pcb"),
        ])
        assert result.exit_code == 1
        assert "KiCad Python 不存在" in result.output

    def test_pcb_bad_json_fails(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        result = runner.invoke(app, ["kicad", "pcb", str(bad), "-o", "x.kicad_pcb"])
        assert result.exit_code == 1

    def test_pcb_missing_required_field_fails(self, tmp_path):
        p = tmp_path / "partial.json"
        p.write_text(json.dumps({"traces": [{"start": [0, 0]}]}), encoding="utf-8")
        result = runner.invoke(app, ["kicad", "pcb", str(p), "-o", "x.kicad_pcb"])
        assert result.exit_code == 1

    def test_drc_missing_pcb_reports_violation(self, tmp_path):
        result = runner.invoke(app, [
            "kicad", "drc", str(tmp_path / "ghost.kicad_pcb"),
            "--report", str(tmp_path / "drc.md"),
        ])
        assert result.exit_code == 1
        assert "file_exists" in result.output
        assert (tmp_path / "drc.md").exists()

    def test_drc_module_level_missing_file(self, tmp_path):
        result = run_drc_kicad(tmp_path / "no_such.kicad_pcb")
        assert not result.passed
        assert result.n_errors == 1
