"""G16 EDA 数据格式互操作矩阵测试（Touchstone 1.0/2.0 × MDIF × CITI）。

全部用例确定性、无网络、无真机，写入 tmp_path 隔离目录，不污染 runs/。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import skrf
from skrf.io import Citi, Mdif
from skrf.networkSet import NetworkSet

from rfauto.adapters.interchange import (
    INTERCHANGE_FORMATS,
    db_to_linear_magnitude,
    export_citi,
    export_interchange,
    export_mdif,
    export_mdif_table,
    export_touchstone,
    max_complex_delta,
    read_citi,
    read_interchange,
    read_mdif,
    read_mdif_table,
    read_touchstone,
    validate_frequency_range,
)
from rfauto.core.contracts import TouchstoneContract
from rfauto.core.errors import ContractViolationError

ABS_TOL = 1e-12
PORT_COUNTS = (1, 2, 3, 4)
_EXTENSIONS = {"touchstone1": "s{}p", "touchstone2": "s{}p", "mdif": "mdf", "citi": "cti"}
REAL_ADS_MDF = Path(
    "scripts/spike_b_ads/sample_wrk27/Datalink_Basics_wrk/data/python/IMPORT_TO_ADS.mdf"
)


def synth(
    n_ports: int,
    z0: float = 50.0,
    seed: int = 0,
    n_points: int = 11,
    name: str = "dut",
) -> skrf.Network:
    """确定性合成 N 端口网络：固定 NumPy 种子，逐元素可复现。"""
    freq = skrf.Frequency(1.0, 5.0, n_points, unit="GHz")
    rng = np.random.default_rng(seed)
    raw = rng.normal(size=(n_points, n_ports, n_ports)) + 1j * rng.normal(
        size=(n_points, n_ports, n_ports)
    )
    return skrf.Network(frequency=freq, s=raw * 0.1, z0=z0, name=name)


def out_path(tmp_path: Path, fmt: str, n_ports: int) -> Path:
    return tmp_path / f"{fmt}_n{n_ports}.{_EXTENSIONS[fmt].format(n_ports)}"


class TestTouchstoneRoundtrip:
    def test_touchstone1_two_port_roundtrip(self, tmp_path):
        net = synth(2, seed=1)
        path = export_interchange(net, out_path(tmp_path, "touchstone1", 2), "touchstone1")
        back = read_interchange(path, "touchstone1")[0]
        assert back.number_of_ports == 2
        assert max_complex_delta(net.s, back.s) <= ABS_TOL
        assert np.allclose(back.f, net.f)
        assert float(np.asarray(back.z0)[0, 0].real) == pytest.approx(50.0)

    def test_touchstone2_two_port_roundtrip(self, tmp_path):
        net = synth(2, seed=1)
        path = export_interchange(net, out_path(tmp_path, "touchstone2", 2), "touchstone2")
        back = read_interchange(path, "touchstone2")[0]
        assert back.number_of_ports == 2
        assert max_complex_delta(net.s, back.s) <= ABS_TOL
        assert np.allclose(back.f, net.f)
        assert float(np.asarray(back.z0)[0, 0].real) == pytest.approx(50.0)

    @pytest.mark.parametrize("n_ports", PORT_COUNTS)
    def test_touchstone_versions_roundtrip_all_port_counts(self, tmp_path, n_ports):
        for fmt in ("touchstone1", "touchstone2"):
            net = synth(n_ports, seed=n_ports)
            path = export_interchange(net, out_path(tmp_path, fmt, n_ports), fmt)
            back = read_interchange(path, fmt)[0]
            assert back.number_of_ports == n_ports
            assert max_complex_delta(net.s, back.s) <= ABS_TOL

    def test_port_order_and_frequency_axis_preserved(self, tmp_path):
        net = synth(3, seed=3)
        net.s[:, 0, 1] = 0.9  # 非对称 S12：端口顺序若错位必被 |ΔS| 抓住
        path = export_interchange(net, out_path(tmp_path, "touchstone2", 3), "touchstone2")
        back = read_touchstone(path)
        assert np.allclose(back.f, net.f)
        assert back.frequency.unit == net.frequency.unit
        assert max_complex_delta(net.s, back.s) <= ABS_TOL


class TestMdifRoundtrip:
    @pytest.mark.parametrize("n_ports", PORT_COUNTS)
    def test_mdif_roundtrip_all_port_counts(self, tmp_path, n_ports):
        net = synth(n_ports, z0=50.0, seed=n_ports)
        path = export_mdif(net, out_path(tmp_path, "mdif", n_ports), comments=["g16"])
        back = read_mdif(path)[0]
        assert back.number_of_ports == n_ports
        assert max_complex_delta(net.s, back.s) <= ABS_TOL
        assert np.allclose(back.f, net.f)
        assert float(np.asarray(back.z0)[0, 0].real) == pytest.approx(50.0)

    def test_mdif_write_skips_name_comment_metadata(self, tmp_path):
        net = synth(2, seed=2)
        path = export_mdif(net, out_path(tmp_path, "mdif", 2), comments=["g16-comment"])
        parsed = Mdif(str(path))
        assert parsed.networks[0].name == net.name
        assert any("g16-comment" in line for line in parsed.comments)

    def test_three_port_repairs_skrf_writer_defect(self, tmp_path):
        """skrf 2.1.0 Mdif.write 折行 %F 头缺 % 前缀；export_mdif 负责修复。"""
        net = synth(3, seed=3)
        raw = tmp_path / "raw_skrf_3port.mdf"
        Mdif.write(NetworkSet([net]), str(raw))
        with pytest.raises(ValueError):
            Mdif(str(raw))
        fixed = export_mdif(net, tmp_path / "fixed_3port.mdf")
        back = read_mdif(fixed)[0]
        assert max_complex_delta(net.s, back.s) <= ABS_TOL


class TestCitiRoundtrip:
    @pytest.mark.parametrize("n_ports", PORT_COUNTS)
    def test_citi_roundtrip_all_port_counts(self, tmp_path, n_ports):
        net = synth(n_ports, seed=n_ports)
        path = export_citi(net, out_path(tmp_path, "citi", n_ports))
        back = read_citi(path)[0]
        assert back.number_of_ports == n_ports
        assert max_complex_delta(net.s, back.s) <= ABS_TOL
        assert np.allclose(back.f, net.f)
        assert float(np.asarray(back.z0)[0, 0].real) == pytest.approx(50.0)


class TestReferenceImpedance:
    @pytest.mark.parametrize("fmt", INTERCHANGE_FORMATS)
    def test_uniform_non_50_ohm_roundtrip(self, tmp_path, fmt):
        net = synth(2, z0=75.0, seed=2)
        path = export_interchange(net, out_path(tmp_path, fmt, 2), fmt)
        back = read_interchange(path, fmt)[0]
        assert max_complex_delta(net.s, back.s) <= ABS_TOL
        assert float(np.asarray(back.z0)[0, 0].real) == pytest.approx(75.0)

    def test_touchstone2_per_port_z0_roundtrip(self, tmp_path):
        net = synth(2, seed=2)
        net.z0 = np.array([[50.0, 75.0]] * len(net.f))
        path = export_touchstone(net, tmp_path / "pp.s2p", version="2.0", write_z0=True)
        back = read_touchstone(path)
        assert np.asarray(back.z0)[0, 0].real == pytest.approx(50.0)
        assert np.asarray(back.z0)[0, 1].real == pytest.approx(75.0)
        assert max_complex_delta(net.s, back.s) <= ABS_TOL

    def test_citi_per_port_z0_roundtrip(self, tmp_path):
        net = synth(2, seed=2)
        net.z0 = np.array([[50.0, 75.0]] * len(net.f))
        path = export_citi(net, tmp_path / "pp.cti")
        back = read_citi(path)[0]
        assert np.asarray(back.z0)[0, 0].real == pytest.approx(50.0)
        assert np.asarray(back.z0)[0, 1].real == pytest.approx(75.0)
        assert max_complex_delta(net.s, back.s) <= ABS_TOL

    def test_mdif_rejects_per_port_z0(self, tmp_path):
        """MDIF 只有单一 R 参考阻抗；不等端口阻抗时 skrf 显式报错而非静默。"""
        net = synth(2, seed=2)
        net.z0 = np.array([[50.0, 75.0]] * len(net.f))
        with pytest.raises(ValueError, match="unequal port impedances"):
            export_mdif(net, tmp_path / "pp.mdf")


class TestCommentMetadata:
    @pytest.mark.parametrize("fmt", INTERCHANGE_FORMATS)
    def test_comment_preserved(self, tmp_path, fmt):
        net = synth(2, seed=2)
        net.comments = "g16-comment"
        path = export_interchange(
            net, out_path(tmp_path, fmt, 2), fmt, comments=["g16-comment"]
        )
        if fmt.startswith("touchstone"):
            assert "g16-comment" in read_touchstone(path).comments
        elif fmt == "mdif":
            assert any("g16-comment" in line for line in Mdif(str(path)).comments)
        else:
            assert any("g16-comment" in line for line in Citi(str(path)).comments)

    def test_citi_comment_keyword_is_dropped_by_skrf(self, tmp_path):
        """skrf Citi 只识别 #/! 注释行；CITI 规范的 COMMENT 关键字被丢弃。"""
        net = synth(1, seed=1)
        path = export_citi(net, tmp_path / "c.cti", comments=["kept"])
        text = path.read_text(encoding="utf-8").replace(
            "! kept", "COMMENT dropped-by-skrf"
        )
        path.write_text(text, encoding="utf-8")
        comments = Citi(str(path)).comments
        assert not any("dropped-by-skrf" in line for line in comments)


class TestFrequencyValidation:
    def test_validate_frequency_range_accepts_covering_band(self):
        net = synth(2, seed=1)  # 1..5 GHz
        assert validate_frequency_range(net, 1.0, 5.0) is True
        assert validate_frequency_range(net, 1.5, 4.5) is True

    def test_validate_frequency_range_rejects_outside_band(self):
        net = synth(2, seed=1)
        assert validate_frequency_range(net, 0.5, 4.5) is False
        assert validate_frequency_range(net, 1.5, 6.0) is False


class TestExplicitErrors:
    @pytest.mark.parametrize("fmt", INTERCHANGE_FORMATS)
    def test_missing_file_raises_filenotfound(self, tmp_path, fmt):
        with pytest.raises(FileNotFoundError):
            read_interchange(out_path(tmp_path, fmt, 2), fmt)

    def test_unknown_format_raises_valueerror(self, tmp_path):
        net = synth(2, seed=1)
        with pytest.raises(ValueError, match="不支持的互操作格式"):
            export_interchange(net, tmp_path / "x.bin", "sparquet")
        with pytest.raises(ValueError, match="不支持的互操作格式"):
            read_interchange(tmp_path / "x.bin", "sparquet")

    def test_garbage_touchstone_raises_valueerror(self, tmp_path):
        bad = tmp_path / "bad.s2p"
        bad.write_text("this is not a touchstone file\n", encoding="utf-8")
        with pytest.raises(ValueError):
            read_touchstone(bad)

    def test_garbage_citi_raises(self, tmp_path):
        bad = tmp_path / "bad.cti"
        bad.write_text("NOT A CITI FILE\n", encoding="utf-8")
        with pytest.raises(ValueError):
            read_citi(bad)

    def test_export_touchstone_rejects_unknown_version(self, tmp_path):
        with pytest.raises(ValueError, match="Touchstone 版本"):
            export_touchstone(synth(2, seed=1), tmp_path / "x.s2p", version="9.9")

    def test_export_citi_rejects_network_set(self, tmp_path):
        with pytest.raises(TypeError, match=r"单个 skrf\.Network"):
            export_citi(NetworkSet([synth(2, seed=1)]), tmp_path / "x.cti")


class TestRealAdsMdf:
    @pytest.mark.skipif(not REAL_ADS_MDF.exists(), reason="仓库内无真实 ADS .mdf")
    def test_real_ads_mdf_is_not_skrf_readable_gmdif(self):
        """仓库内唯一真实 .mdf（ADS 导入用）是逗号分隔的 dB 数据，非 GMDIF。"""
        text = REAL_ADS_MDF.read_text(encoding="utf-8", errors="replace")
        assert "%Freq(1) dBS21(1)" in text
        assert "," in text
        assert "#" not in text  # 无 Touchstone/MDIF 选项行
        with pytest.raises((ValueError, NotImplementedError)):
            read_mdif(REAL_ADS_MDF)

    @pytest.mark.skipif(not REAL_ADS_MDF.exists(), reason="仓库内无真实 ADS .mdf")
    def test_real_ads_mdf_parses_as_tabular_variant(self):
        """真文件按 tabular 变体可解：块名/列头/行数/首末行数值全部对上文件原文。"""
        tables = read_mdif_table(REAL_ADS_MDF)
        assert len(tables) == 1
        table = tables[0]
        assert table.name == "BLK0"
        assert table.columns == ("Freq(1)", "dBS21(1)")
        assert table.data.shape == (30, 2)
        assert table.data[0, 0] == pytest.approx(1.0e7)
        assert table.data[0, 1] == pytest.approx(14.283)
        assert table.data[-1, 0] == pytest.approx(3.0e9)
        assert table.data[-1, 1] == pytest.approx(-1.126)
        assert np.all(np.diff(table.column("Freq(1)")) > 0)  # 频率轴单调递增

    @pytest.mark.skipif(not REAL_ADS_MDF.exists(), reason="仓库内无真实 ADS .mdf")
    def test_real_ads_mdf_data_roundtrip_bitexact(self, tmp_path):
        """真文件解析出的数据写出→读回逐位无损（max|Δ| == 0 ≤ 1e-12 口径）。"""
        table = read_mdif_table(REAL_ADS_MDF)[0]
        path = export_mdif_table(tmp_path / "roundtrip.mdf", table.name, table.columns, table.data)
        back = read_mdif_table(path)[0]
        assert back.name == table.name
        assert back.columns == table.columns
        assert back.data.shape == table.data.shape
        assert float(np.max(np.abs(back.data - table.data))) == 0.0

    def test_db_to_linear_magnitude_closed_form(self):
        """dB→线性换算对闭式值：20dB→10、0dB→1、-20dB→0.1（独立期望，非自证）。"""
        linear = db_to_linear_magnitude(np.array([20.0, 0.0, -20.0]))
        np.testing.assert_allclose(linear, [10.0, 1.0, 0.1], rtol=0, atol=1e-15)

    @pytest.mark.skipif(not REAL_ADS_MDF.exists(), reason="仓库内无真实 ADS .mdf")
    def test_real_ads_mdf_db_column_to_linear(self):
        """真文件 dBS21 列可消费为线性幅度（确定性换算，无相位合成）。"""
        table = read_mdif_table(REAL_ADS_MDF)[0]
        linear = db_to_linear_magnitude(table.column("dBS21(1)"))
        assert linear.shape == (30,)
        assert linear[0] == pytest.approx(10 ** (14.283 / 20), rel=1e-12)


class TestCitiDataFormats:
    """CITI 数据格式档（skrf Citi 读取器支持的全部三种：RI/MAGANGLE/DBANGLE）。"""

    @pytest.mark.parametrize("data_format", ["RI", "MA", "DB"])
    @pytest.mark.parametrize("n_ports", PORT_COUNTS)
    def test_citi_data_format_all_port_counts(self, tmp_path, data_format, n_ports):
        net = synth(n_ports, seed=n_ports)
        path = export_citi(
            net, tmp_path / f"fmt_{data_format}_n{n_ports}.cti", data_format=data_format
        )
        back = read_citi(path)[0]
        assert back.number_of_ports == n_ports
        assert max_complex_delta(net.s, back.s) <= ABS_TOL
        assert np.allclose(back.f, net.f)

    @pytest.mark.parametrize("data_format", ["MA", "DB"])
    def test_citi_data_format_non_50_ohm(self, tmp_path, data_format):
        net = synth(2, z0=75.0, seed=3)
        path = export_citi(
            net, tmp_path / f"z75_{data_format}.cti", data_format=data_format
        )
        back = read_citi(path)[0]
        assert max_complex_delta(net.s, back.s) <= ABS_TOL
        assert float(np.asarray(back.z0)[0, 0].real) == pytest.approx(75.0)

    def test_citi_data_format_case_insensitive_and_file_token(self, tmp_path):
        net = synth(2, seed=2)
        path = export_citi(net, tmp_path / "lower.cti", data_format="ma")
        text = path.read_text(encoding="utf-8")
        assert "DATA S[1,1] MAGANGLE" in text  # 文件档 token 是 CITI 规范名
        assert max_complex_delta(net.s, read_citi(path)[0].s) <= ABS_TOL

    def test_citi_unknown_data_format_raises(self, tmp_path):
        with pytest.raises(ValueError, match="数据格式档"):
            export_citi(synth(2, seed=1), tmp_path / "x.cti", data_format="LIN")


class TestTabularMdifRoundtrip:
    def test_roundtrip_two_columns_bitexact(self, tmp_path):
        rng = np.random.default_rng(7)
        data = np.column_stack([np.linspace(1e6, 3e9, 101), rng.normal(size=101) * 10.0])
        path = export_mdif_table(
            tmp_path / "t.mdf",
            "BLK0",
            ["Freq(1)", "dBS21(1)"],
            data,
            comments=["tabular variant"],
        )
        text = path.read_text(encoding="utf-8")
        assert text.startswith("! tabular variant\n")
        assert "BEGIN BLK0" in text
        assert "%Freq(1) dBS21(1)" in text
        back = read_mdif_table(path)
        assert len(back) == 1
        table = back[0]
        assert table.name == "BLK0"
        assert table.columns == ("Freq(1)", "dBS21(1)")
        assert table.data.shape == (101, 2)
        assert float(np.max(np.abs(table.data - data))) == 0.0  # .17g 逐位无损

    def test_roundtrip_single_cell_and_empty_table(self, tmp_path):
        path = export_mdif_table(tmp_path / "one.mdf", "A", ["x"], np.array([[1.25]]))
        table = read_mdif_table(path)[0]
        assert table.data.shape == (1, 1)
        assert table.data[0, 0] == 1.25

        empty = export_mdif_table(tmp_path / "empty.mdf", "B", ["a", "b"], np.empty((0, 2)))
        table0 = read_mdif_table(empty)[0]
        assert table0.data.shape == (0, 2)

    def test_roundtrip_1d_single_column(self, tmp_path):
        path = export_mdif_table(tmp_path / "vec.mdf", "V", ["mag"], np.array([1.0, 2.5, -3.0]))
        table = read_mdif_table(path)[0]
        assert table.columns == ("mag",)
        assert table.data.shape == (3, 1)
        assert table.data[:, 0].tolist() == [1.0, 2.5, -3.0]

    def test_reader_accepts_multiple_blocks_and_mixed_separators(self, tmp_path):
        path = tmp_path / "multi.mdf"
        path.write_text(
            "BEGIN A\n%a b\n1, 2\n3 4\nEND\n"
            "! comment between blocks\n"
            "BEGIN B\n%c\n5\nEND\n",
            encoding="utf-8",
        )
        tables = read_mdif_table(path)
        assert [t.name for t in tables] == ["A", "B"]
        assert tables[0].data.tolist() == [[1.0, 2.0], [3.0, 4.0]]
        assert tables[1].data.tolist() == [[5.0]]

    def test_reader_is_single_pass_line_stream_on_moderate_size(self, tmp_path):
        """2 万行中规模数据秒级往返（逐行单遍读取，无整文件字符串切分）。"""
        n = 20000
        data = np.column_stack([np.linspace(1e6, 3e9, n), np.arange(n, dtype=float)])
        path = export_mdif_table(tmp_path / "big.mdf", "BIG", ["Freq(1)", "Idx"], data)
        table = read_mdif_table(path)[0]
        assert table.data.shape == (n, 2)
        assert float(np.max(np.abs(table.data - data))) <= ABS_TOL


class TestTabularMdifErrors:
    def test_truncated_begin_without_end(self, tmp_path):
        path = tmp_path / "trunc.mdf"
        path.write_text("BEGIN A\n%a\n1\n", encoding="utf-8")
        with pytest.raises(ValueError, match="END"):
            read_mdif_table(path)

    def test_data_row_before_header(self, tmp_path):
        path = tmp_path / "nohdr.mdf"
        path.write_text("BEGIN A\n1,2\nEND\n", encoding="utf-8")
        with pytest.raises(ValueError, match="列头"):
            read_mdif_table(path)

    def test_missing_header_block_rejected(self, tmp_path):
        path = tmp_path / "nohdr2.mdf"
        path.write_text("BEGIN A\nEND\n", encoding="utf-8")
        with pytest.raises(ValueError, match="列头"):
            read_mdif_table(path)

    def test_wrong_column_count(self, tmp_path):
        path = tmp_path / "width.mdf"
        path.write_text("BEGIN A\n%a b\n1,2,3\nEND\n", encoding="utf-8")
        with pytest.raises(ValueError, match="列数不匹配"):
            read_mdif_table(path)

    def test_non_numeric_row(self, tmp_path):
        path = tmp_path / "nan.mdf"
        path.write_text("BEGIN A\n%a\nfoo\nEND\n", encoding="utf-8")
        with pytest.raises(ValueError, match="非数值"):
            read_mdif_table(path)

    def test_option_line_rejected(self, tmp_path):
        """# 选项行是 Touchstone/GMDIF 语法，tabular 变体显式报错而非误读。"""
        path = tmp_path / "option.mdf"
        path.write_text("BEGIN A\n# HZ S RI R 50\n%a\n1\nEND\n", encoding="utf-8")
        with pytest.raises(ValueError, match="# 选项行"):
            read_mdif_table(path)

    def test_nested_begin(self, tmp_path):
        path = tmp_path / "nested.mdf"
        path.write_text("BEGIN A\n%a\nBEGIN B\n%b\n1\nEND\nEND\n", encoding="utf-8")
        with pytest.raises(ValueError, match="嵌套"):
            read_mdif_table(path)

    def test_orphan_end(self, tmp_path):
        path = tmp_path / "orphan.mdf"
        path.write_text("END\n", encoding="utf-8")
        with pytest.raises(ValueError, match="孤立 END"):
            read_mdif_table(path)

    def test_empty_file_has_no_blocks(self, tmp_path):
        path = tmp_path / "empty.mdf"
        path.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="数据块"):
            read_mdif_table(path)

    def test_gmdif_style_content_rejected(self, tmp_path):
        """GMDIF 的 VAR 声明行不是 tabular 变体语法——误投喂时显式报错。"""
        path = tmp_path / "gmdif.mdf"
        path.write_text("VAR freq MAG 2\nBEGIN ACDATA\n%F\n1\nEND\n", encoding="utf-8")
        with pytest.raises(ValueError, match="无法识别"):
            read_mdif_table(path)

    def test_missing_file_raises_filenotfound(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_mdif_table(tmp_path / "absent.mdf")

    def test_export_rejects_column_mismatch(self, tmp_path):
        with pytest.raises(ValueError, match="列数不匹配"):
            export_mdif_table(tmp_path / "x.mdf", "A", ["a", "b"], np.ones((2, 3)))

    def test_export_rejects_bad_name_and_columns(self, tmp_path):
        with pytest.raises(ValueError, match="块名"):
            export_mdif_table(tmp_path / "x.mdf", "A B", ["a"], np.ones((1, 1)))
        with pytest.raises(ValueError, match="列名"):
            export_mdif_table(tmp_path / "x.mdf", "A", ["a b"], np.ones((1, 1)))
        with pytest.raises(ValueError, match="至少需要一列"):
            export_mdif_table(tmp_path / "x.mdf", "A", [], np.ones((1, 1)))

    def test_column_accessor_unknown_name(self, tmp_path):
        path = export_mdif_table(tmp_path / "c.mdf", "A", ["a"], np.ones((1, 1)))
        table = read_mdif_table(path)[0]
        with pytest.raises(ValueError, match="不含列"):
            table.column("b")


class TestHelpersAndContract:
    def test_max_complex_delta_detects_difference(self):
        a = synth(2, seed=1)
        b = synth(2, seed=1)
        assert max_complex_delta(a.s, b.s) == 0.0
        b.s[0, 0, 0] += 1e-9
        assert max_complex_delta(a.s, b.s) == pytest.approx(1e-9, rel=1e-6)

    def test_max_complex_delta_shape_mismatch(self):
        with pytest.raises(ValueError, match="形状不一致"):
            max_complex_delta(synth(2, seed=1).s, synth(3, seed=1).s)

    def test_touchstone_contract_still_enforced(self, tmp_path):
        contract = TouchstoneContract(port_order=["P1", "P2"], renormalization_ohm=75.0)
        with pytest.raises(ContractViolationError, match="参考阻抗"):
            export_touchstone(synth(2, z0=50.0, seed=1), tmp_path / "bad.s2p", contract)
        ok = export_touchstone(synth(2, z0=75.0, seed=1), tmp_path / "ok.s2p", contract)
        assert read_touchstone(ok, contract).number_of_ports == 2
