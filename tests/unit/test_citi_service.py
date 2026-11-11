"""Q-X35（aurora_q）：CITIfile 服务包装 + CLI 叶 + 计数链测试。

全离线零网络零真机：信封三态（ok/error/skipped，AU-2 构造器同形）、
段读取过滤与 raw 显式声明、skrf 桥接探针条件预声明（齐套方阵/频率表
/无多值扫描，不满足走 skipped 如实给 reason）、CLI 三叶 --json 双路径
（CliRunner 直连 citi_app——不触共享 app，零金快照漂移）、计数链
（新叶 grep 字面钉 + cli.main 零导入钉）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.cli.domains.citi import citi_app
from rfauto.service import citi_service

FIXTURE = Path(__file__).parent / "fixtures" / "citi" / "sample_citi.cti"

runner = CliRunner()


# ── citi_info 信封钉 ──────────────────────────


def test_citi_info_fixture_envelope():
    result = citi_service.citi_info(FIXTURE)
    assert result["ok"] is True
    assert result["n_packages"] == 1
    pkg = result["packages"][0]
    assert pkg["version"] == "A.01.01"
    assert pkg["header"]["OUTPERHA"] == "?"
    assert pkg["metadata"]["n_packages"] == 1
    names = result["summary"][0]["segment_names"]
    assert names == ["S[1,1]", "PortZ[1]"]


def test_citi_info_max_values_truncation_declared():
    result = citi_service.citi_info(FIXTURE, max_values=2)
    seg = result["packages"][0]["segments"][0]
    assert len(seg["dependent_vars"][0]["values"]) == 2
    assert seg["dependent_vars"][0]["values_truncated"] is True
    full = citi_service.citi_info(FIXTURE)["packages"][0]["segments"][0]
    assert len(full["dependent_vars"][0]["values"]) == 5


def test_citi_info_missing_file_error_envelope():
    result = citi_service.citi_info("Z:/no/such/file.cti")
    assert result["ok"] is False
    assert isinstance(result["errors"], list)
    assert "不存在" in result["errors"][0]


def test_citi_info_non_citi_file_error_envelope(tmp_path):
    bad = tmp_path / "bad.cti"
    bad.write_text("hello world\nnot a citi file\n", encoding="utf-8")
    result = citi_service.citi_info(bad)
    assert result["ok"] is False
    assert "非 CITI" in result["errors"][0]


# ── citi_read_segments 钉 ──────────────────────────


def test_read_segments_name_filter_and_missing_honest():
    result = citi_service.citi_read_segments(FIXTURE, names=["S[1,1]"])
    assert result["ok"] is True
    assert result["n_segments"] == 1
    assert result["segments"][0]["var_name"] == "S[1,1]"
    assert result["missing_names"] == []
    result2 = citi_service.citi_read_segments(FIXTURE, names=["Nope[9,9]"])
    assert result2["n_segments"] == 0
    assert result2["missing_names"] == ["Nope[9,9]"]


def test_read_segments_include_raw_flag():
    text = (
        "CITIFILE A.01.00\nNAME RAWCD\nVAR FREQ MAG 1\n"
        "VAR_LIST_BEGIN\n1e9\nVAR_LIST_END\n"
        "INDEPENDENT freq HZ 1\n"
        "DEPENDENT c CMPLX\n"
        "SEG C 1\nBEGIN\n3FB9999999\nEND\n"
    )
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "raw_c.cti"
        p.write_text(text, encoding="utf-8")
        no_raw = citi_service.citi_read_segments(p)
        assert "raw_records" not in no_raw["segments"][0]
        with_raw = citi_service.citi_read_segments(p, include_raw=True)
        assert with_raw["segments"][0]["raw_records"] == ["3FB9999999"]
        assert with_raw["segments"][0]["decode_status"] == "unsupported_width"


# ── skrf 桥接探针钉（条件预声明 + skipped 诚实） ──────────────────────────


def test_network_probe_fixture_bridge_ok():
    result = citi_service.citi_network_probe(FIXTURE)
    assert result["ok"] is True
    assert "skipped" not in result
    bridged = result["bridged_packages"][0]
    assert bridged["n_ports"] == 1
    assert bridged["n_freq"] == 5
    assert bridged["f_min_hz"] == 1e9
    assert bridged["f_max_hz"] == 2e9
    assert bridged["z0_source"] == "PortZ/Zo segment"
    assert bridged["network_summary"]["s_shape"] == [5, 1, 1]


def test_network_probe_skipped_no_s_matrix(tmp_path):
    text = (
        "CITIFILE A.01.00\nNAME NO_S\nVAR FREQ MAG 1\n"
        "VAR_LIST_BEGIN\n1e9\nVAR_LIST_END\n"
        "INDEPENDENT freq HZ 1\n"
        "DATA VOLTAGE[1] RI\nBEGIN\n0.1, 0.2\nEND\n"
    )
    p = tmp_path / "no_s.cti"
    p.write_text(text, encoding="utf-8")
    result = citi_service.citi_network_probe(p)
    assert result["ok"] is True
    assert result["skipped"] is True
    assert "无可解码 S[i,j]" in result["reason"]
    assert result["bridged_packages"] == []


def test_network_probe_skipped_incomplete_matrix(tmp_path):
    text = (
        "CITIFILE A.01.00\nNAME HALF_MATRIX\nVAR FREQ MAG 1\n"
        "VAR_LIST_BEGIN\n1e9\nVAR_LIST_END\n"
        "INDEPENDENT freq HZ 1\n"
        "DATA S[1,1] RI\nBEGIN\n0.1, 0.0\nEND\n"
        "DATA S[2,1] RI\nBEGIN\n0.2, 0.0\nEND\n"
    )
    p = tmp_path / "half.cti"
    p.write_text(text, encoding="utf-8")
    result = citi_service.citi_network_probe(p)
    assert result["ok"] is True
    assert result["skipped"] is True
    assert "方阵不齐套" in result["reason"]


def test_network_probe_skipped_freq_missing(tmp_path):
    text = (
        "CITIFILE A.01.00\nNAME NO_FREQ\n"
        "DATA S[1,1] RI\nBEGIN\n0.1, 0.0\nEND\n"
    )
    p = tmp_path / "no_freq.cti"
    p.write_text(text, encoding="utf-8")
    result = citi_service.citi_network_probe(p)
    assert result["skipped"] is True
    assert "频率" in result["reason"]


# ── CLI 三叶 --json 双路径钉 ──────────────────────────


def test_cli_info_json_envelope():
    res = runner.invoke(citi_app, ["info", str(FIXTURE), "--json"])
    assert res.exit_code == 0, res.output
    envelope = json.loads(res.output)
    assert envelope["ok"] is True
    assert envelope["packages"][0]["name"] == "RAW_DATA"


def test_cli_info_json_failure_envelope():
    res = runner.invoke(citi_app, ["info", "Z:/no/such.cti", "--json"])
    assert res.exit_code == 1
    envelope = json.loads(res.output)
    assert envelope["ok"] is False
    assert isinstance(envelope["errors"], list)


def test_cli_segments_json_values():
    res = runner.invoke(citi_app, ["segments", str(FIXTURE),
                                   "--name", "S[1,1]", "--json"])
    assert res.exit_code == 0, res.output
    envelope = json.loads(res.output)
    assert envelope["n_segments"] == 1
    dep = envelope["segments"][0]["dependent_vars"][0]
    assert dep["values"][2] == [0.3, 0.15]


def test_cli_network_json_skipped_and_ok():
    res = runner.invoke(citi_app, ["network", str(FIXTURE), "--json"])
    assert res.exit_code == 0, res.output
    envelope = json.loads(res.output)
    assert envelope["ok"] is True
    assert envelope["bridged_packages"][0]["n_ports"] == 1


def test_cli_help_no_bare_percent():
    # help 卫生（#305 家族）：--help 构建成功 + 零裸 %
    for leaf in (["info", "--help"], ["segments", "--help"],
                 ["network", "--help"]):
        res = runner.invoke(citi_app, leaf)
        assert res.exit_code == 0, res.output
        assert "%" not in res.output


# ── 计数链（CLI 新叶 grep 字面钉；零共享树漂移钉） ──────────────────────────


def test_citi_leaves_literal_pin():
    # 计数链钉：citi 域恰 3 叶、每叶带 --json（新叶无 --json 即红）
    source = Path(citi_service.__file__).parent.parent.joinpath(
        "cli", "domains", "citi.py").read_text(encoding="utf-8")
    for literal in ('@citi_app.command("info")',
                    '@citi_app.command("segments")',
                    '@citi_app.command("network")'):
        assert source.count(literal) == 1, literal
    assert source.count("json_output: bool = typer.Option") == 3
    assert '--json", "-j"' in source
