"""service/gerber_overview_service.py（T-Q6 最小 RS-274X 读入口）测试。

夹具=手写最小 Gerber（tests/unit/fixtures/gerber_overview/minimal_x2.gbr）；
弧线 I/J 偏移排除、无 FS 不定标等边界用内联最小件。全离线确定性双跑。
"""

from __future__ import annotations

import json
from pathlib import Path

from rfauto.service.gerber_overview_service import gerber_overview

_FIXTURE = Path(__file__).parent / "fixtures" / "gerber_overview" / "minimal_x2.gbr"

_ARC_GBR = (
    "%FSLAX36Y36*%\n"
    "%MOMM*%\n"
    "%ADD10C,0.5*%\n"
    "G01*\n"
    "X1000000Y1000000D02*\n"
    "G03X2000000Y1000000I500000J0D01*\n"
    "M02*\n"
)

_NO_FS_GBR = (
    "%MOMM*%\n"
    "%ADD10C,0.5*%\n"
    "X100D01*\n"
    "X200Y300D02*\n"
    "M02*\n"
)

_INCH_GBR = (
    "%FSLAX24Y24*%\n"
    "%MOIN*%\n"
    "%ADD10C,0.05*%\n"
    "X10000Y20000D03*\n"
    "M02*\n"
)


def _j(env: dict) -> str:
    return json.dumps(env, ensure_ascii=False)


class TestGerberOverview:
    def test_format_detection_fs_mo(self):
        out = gerber_overview(_FIXTURE)
        assert out["ok"] is True
        assert out["kind"] == "gerber"
        assert out["schema_version"] == "1.0"
        assert out["format"] == {
            "unit": "MM",
            "fs": {"zero_omission": "L", "notation": "A",
                   "x": [3, 6], "y": [3, 6]},
            "fs_present": True,
        }

    def test_aperture_list_and_macros(self):
        """D 码清单=模板+参数原文（零数值解释）；宏只计数不解析宏体。"""
        out = gerber_overview(_FIXTURE)
        assert out["apertures"] == [
            {"dcode": 10, "template": "C", "params": "0.500"},
            {"dcode": 11, "template": "R", "params": "1.000X2.000"},
            {"dcode": 12, "template": "FIXDOT", "params": "0.250"},
        ]
        assert out["n_apertures"] == 3
        assert out["n_aperture_macros"] == 1

    def test_op_counts(self):
        out = gerber_overview(_FIXTURE)
        assert out["ops"] == {"d01": 1, "d02": 1, "d03": 2}
        assert out["n_aperture_selects"] == 1  # D10*

    def test_bbox_declared_aggregation_scaled(self):
        """声明聚合：显式 X/Y 词 min/max；FS 6 位小数定标为文件单位。"""
        out = gerber_overview(_FIXTURE)
        assert out["bbox"] == {
            "raw_min": [-1000000, -500000],
            "raw_max": [3000000, 2000000],
            "min": [-1.0, -0.5],
            "max": [3.0, 2.0],
            "unit": "MM",
            "fs_decimals": [6, 6],
            "n_declared_points": 8,
        }

    def test_bbox_excludes_arc_ij_offsets(self, tmp_path: Path):
        """I/J=圆弧圆心偏移量非坐标——不入 bbox（只聚合显式 X/Y 词）。"""
        p = tmp_path / "arc.gbr"
        p.write_text(_ARC_GBR, encoding="utf-8", newline="\n")
        out = gerber_overview(p)
        assert out["ok"] is True
        assert out["bbox"]["raw_min"] == [1000000, 1000000]
        assert out["bbox"]["raw_max"] == [2000000, 1000000]
        assert out["bbox"]["n_declared_points"] == 4
        assert out["ops"] == {"d01": 1, "d02": 1, "d03": 0}

    def test_other_extended_counted_verbatim(self):
        """未识别扩展字段（X2 属性 TF/极性 LP）原样计数不猜语义。"""
        out = gerber_overview(_FIXTURE)
        assert out["other_extended"] == {
            "LPD": 1,
            "TF.GenerationSoftware": 1,
        }

    def test_double_run_byte_identical(self):
        a = _j(gerber_overview(_FIXTURE))
        b = _j(gerber_overview(_FIXTURE))
        assert a == b

    def test_no_fs_bbox_unscaled(self, tmp_path: Path):
        """FS 缺失→坐标词零歧义定标（前导/尾随零），min/max=None 只给整数。"""
        p = tmp_path / "nofs.gbr"
        p.write_text(_NO_FS_GBR, encoding="utf-8", newline="\n")
        out = gerber_overview(p)
        assert out["ok"] is True
        assert out["format"]["fs_present"] is False
        assert out["format"]["fs"] is None
        assert out["bbox"]["raw_min"] == [100, 300]
        assert out["bbox"]["raw_max"] == [200, 300]
        assert out["bbox"]["min"] == [None, None]  # FS 缺失→逐轴 None 不定标
        assert out["bbox"]["max"] == [None, None]
        assert out["bbox"]["fs_decimals"] is None

    def test_inch_unit(self, tmp_path: Path):
        p = tmp_path / "inch.gbr"
        p.write_text(_INCH_GBR, encoding="utf-8", newline="\n")
        out = gerber_overview(p)
        assert out["format"]["unit"] == "IN"
        assert out["bbox"]["min"] == [1.0, 2.0]  # 4 位小数定标：10000/10^4
        assert out["bbox"]["max"] == [1.0, 2.0]

    def test_not_gerber_rejected(self, tmp_path: Path):
        p = tmp_path / "plain.txt"
        p.write_text("hello world, this is not a gerber at all\n",
                     encoding="utf-8")
        out = gerber_overview(p)
        assert out["ok"] is False
        assert "不像 RS-274X Gerber" in out["errors"][0]

    def test_empty_file_rejected(self, tmp_path: Path):
        p = tmp_path / "empty.gbr"
        p.write_text("", encoding="utf-8")
        assert gerber_overview(p)["ok"] is False

    def test_missing_file_rejected(self, tmp_path: Path):
        out = gerber_overview(tmp_path / "nope.gbr")
        assert out["ok"] is False
        assert "不可读" in out["errors"][0]
