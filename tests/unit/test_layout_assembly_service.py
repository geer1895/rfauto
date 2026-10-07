"""LC-5 装配 BOM 面单测（service/layout_assembly_service.py）。

铁律 2（KiCad 子进程域）：单测零真机 KiCad——子进程路径 monkeypatch
stub（kicad_drc 测试同款隔离面），纯函数面（脚本生成/解析/CSV/聚合）
直接测。
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from rfauto.service import layout_assembly_service as asm
from rfauto.service.layout_assembly_service import (
    ASSEMBLY_JSON_END,
    ASSEMBLY_JSON_START,
    aggregate_bom,
    assembly_payload,
    build_kicad_script,
    parse_assembly_stdout,
    write_bom_csv,
    write_pos_csv,
)

ROWS = [
    {"designator": "R1", "value": "10k", "footprint": "R_0402",
     "x_mm": 1.0, "y_mm": 2.0, "rot_deg": 90.0, "side": "front", "fields": {}},
    {"designator": "R2", "value": "10k", "footprint": "R_0402",
     "x_mm": 3.0, "y_mm": 2.0, "rot_deg": 270.0, "side": "back", "fields": {}},
    {"designator": "C1", "value": "100n", "footprint": "C_0402",
     "x_mm": 5.0, "y_mm": 2.0, "rot_deg": 0.0, "side": "front",
     "fields": {"Voltage": "50V"}},
]


class TestPureFunctions:
    def test_script_is_readonly_pcbnew_with_markers(self):
        script = build_kicad_script(r"E:\boards\demo.kicad_pcb")
        assert "import pcbnew" in script
        assert "LoadBoard" in script
        assert "SaveBoard" not in script, "只读口径：脚本不得写板（#210/#214 坑族零接触）"
        assert ASSEMBLY_JSON_START in script and ASSEMBLY_JSON_END in script
        assert r"E:\boards\demo.kicad_pcb" in script

    def test_parse_stdout_with_noise(self):
        noise = "pcbnew info banner\n"
        payload_text = json.dumps({"footprints": ROWS, "board_bbox_mm": [0, 0, 6, 3],
                                   "errors": [], "kicad_version": "10.0"})
        stdout = (noise + f"{ASSEMBLY_JSON_START}\n" + payload_text
                  + f"\n{ASSEMBLY_JSON_END}\ntrailing noise\n")
        data = parse_assembly_stdout(stdout)
        assert data["footprints"] == ROWS
        assert data["kicad_version"] == "10.0"

    def test_parse_missing_marker_is_valueerror(self):
        with pytest.raises(ValueError, match="marker"):
            parse_assembly_stdout("no markers here")
        with pytest.raises(ValueError, match="闭合"):
            parse_assembly_stdout(f"{ASSEMBLY_JSON_START}\n{{}}")

    def test_parse_bad_shape_is_valueerror(self):
        bad = (f"{ASSEMBLY_JSON_START}\n{json.dumps({'nope': 1})}\n{ASSEMBLY_JSON_END}")
        with pytest.raises(ValueError, match="footprints"):
            parse_assembly_stdout(bad)

    def test_write_pos_csv(self, tmp_path):
        out = write_pos_csv(ROWS, tmp_path / "b.pos")
        text = out.read_text(encoding="utf-8").splitlines()
        assert text[0] == "Designator,Val,Package,Mid X,Mid Y,Rotation,Layer"
        assert text[1] == "R1,10k,R_0402,1.0000,2.0000,90.00,front"
        assert "R2,10k,R_0402,3.0000,2.0000,270.00,back" in text

    def test_write_bom_csv(self, tmp_path):
        import csv as _csv

        out = write_bom_csv(aggregate_bom(ROWS), tmp_path / "b-bom.csv")
        rows = list(_csv.reader(out.read_text(encoding="utf-8").splitlines()))
        assert rows[0] == ["Refs", "Qty", "Value", "Footprint"]
        assert ["R1,R2", "2", "10k", "R_0402"] in rows  # 多位号 Refs 含逗号→CSV 引号包裹
        assert ["C1", "1", "100n", "C_0402"] in rows

    def test_aggregate_bom_groups_and_sorts(self):
        agg = aggregate_bom(ROWS)
        assert agg == [
            {"refs": ["C1"], "qty": 1, "value": "100n", "footprint": "C_0402"},
            {"refs": ["R1", "R2"], "qty": 2, "value": "10k", "footprint": "R_0402"},
        ]

    def test_aggregate_bom_empty(self):
        assert aggregate_bom([]) == []


class TestSubprocessPath:
    def test_missing_pcb_is_error_envelope(self, tmp_path):
        r = assembly_payload(tmp_path / "nope.kicad_pcb", tmp_path)
        assert r["ok"] is False and "不存在" in r["errors"][0]

    # 钉面=Windows KiCad 安装位（E:\KiCad\bin）+ PATH 前置断言：POSIX 上
    # 盘符串是单段路径名（Path.parent="."），KiCad 安装布局亦不同（真机档
    # 覆盖）——诚实跳过（skip-not-fail，Linux CI 首跑实证）。
    @pytest.mark.skipif(
        os.name != "nt",
        reason="KiCad Windows 安装位/PATH 前置口径为 Windows 面；"
               "POSIX 安装布局不同（真机档覆盖）")
    def test_happy_path_uses_kicad_python_and_writes_artifacts(self, tmp_path, monkeypatch):
        pcb = tmp_path / "demo.kicad_pcb"
        pcb.write_text("(kicad_pcb)", encoding="utf-8")
        out = tmp_path / "asm"
        payload = {"footprints": ROWS, "board_bbox_mm": [0.0, 0.0, 6.0, 3.0],
                   "errors": ["C1 fields: mock"], "kicad_version": "10.0"}
        calls = {}

        def fake_run(argv, **kwargs):
            calls["argv"] = argv
            calls["kwargs"] = kwargs
            script_path = argv[1]
            # 脚本文件形态（非 -c 内联）：#142 家族可审计口径
            assert argv[0] == r"E:\KiCad\bin\python.exe"
            assert script_path.endswith("_rfauto_assembly_export.py")
            stdout = (f"{ASSEMBLY_JSON_START}\n{json.dumps(payload)}\n{ASSEMBLY_JSON_END}")
            return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

        monkeypatch.setattr(asm.subprocess, "run", fake_run)
        monkeypatch.setenv("RFAUTO_KICAD_PYTHON", r"E:\KiCad\bin\python.exe")
        r = assembly_payload(pcb, out)
        assert r["ok"], r
        assert r["n_placed"] == 3
        assert r["kicad_version"] == "10.0"
        assert r["board_bbox_mm"] == [0.0, 0.0, 6.0, 3.0]
        assert r["errors"] == ["C1 fields: mock"]
        assert (out / "demo.pos").is_file()
        assert (out / "demo-bom.csv").is_file()
        assert (out / "_rfauto_assembly_export.py").is_file(), "脚本落盘留证据链"
        assert [g["refs"] for g in r["bom"]] == [["C1"], ["R1", "R2"]]
        # env 前置 KiCad bin 且继承完整环境（不裸替换）
        assert calls["kwargs"]["env"]["PATH"].startswith(r"E:\KiCad\bin")

    def test_nonzero_rc_is_error_with_stderr_tail(self, tmp_path, monkeypatch):
        pcb = tmp_path / "demo.kicad_pcb"
        pcb.write_text("(kicad_pcb)", encoding="utf-8")

        def fake_run(argv, **kwargs):
            return SimpleNamespace(returncode=1, stdout="", stderr="ModuleNotFoundError: pcbnew")

        monkeypatch.setattr(asm.subprocess, "run", fake_run)
        monkeypatch.setenv("RFAUTO_KICAD_PYTHON", r"E:\KiCad\bin\python.exe")
        r = assembly_payload(pcb, tmp_path / "out")
        assert r["ok"] is False
        assert "rc=1" in r["errors"][0] and "pcbnew" in r["errors"][0]

    def test_timeout_is_error_envelope(self, tmp_path, monkeypatch):
        import subprocess as sp

        pcb = tmp_path / "demo.kicad_pcb"
        pcb.write_text("(kicad_pcb)", encoding="utf-8")

        def fake_run(argv, **kwargs):
            raise sp.TimeoutExpired(cmd=argv, timeout=1)

        monkeypatch.setattr(asm.subprocess, "run", fake_run)
        monkeypatch.setenv("RFAUTO_KICAD_PYTHON", r"E:\KiCad\bin\python.exe")
        r = assembly_payload(pcb, tmp_path / "out")
        assert r["ok"] is False and "超时" in r["errors"][0]

    def test_bad_stdout_is_error_envelope(self, tmp_path, monkeypatch):
        pcb = tmp_path / "demo.kicad_pcb"
        pcb.write_text("(kicad_pcb)", encoding="utf-8")

        def fake_run(argv, **kwargs):
            return SimpleNamespace(returncode=0, stdout="garbage", stderr="")

        monkeypatch.setattr(asm.subprocess, "run", fake_run)
        monkeypatch.setenv("RFAUTO_KICAD_PYTHON", r"E:\KiCad\bin\python.exe")
        r = assembly_payload(pcb, tmp_path / "out")
        assert r["ok"] is False and "marker" in r["errors"][0]
