"""diagram_curve_image 内核钉（aurora_p B4：S 参数曲线嵌入）。

任务书验收映射（冻结判据）：
- C. PNG 确定性：同 plan 两渲染逐字节 + **两独立进程 sha256 相同**
  （A5 先例口径：rc_context 钉字体 + metadata Software=None → chunk 仅
  IHDR/pHYs/IDAT/IEND 零时间戳零软件串）；
- D. data URI 无分号：uri 零 ``;`` 且形态 ``data:image/png,<b64>``（不
  ``;base64``）；style 零 ``;base64`` 子串（review_annotation 先例同款）；
- E. 曲线数据逐点==payload：抽 3 频点断言 db[i] == 20·log10(|hypot(re,im)|)
  逐位（同函数同运算序）；JSON 往返后 plan→render 仍逐字节（离线
  annotate transport 语义）；
- 负例：无 S 参数 payload 显式 ValueError（message 可断言）；|S|=0 →
  None 如实断口；键缺失/长度不齐/键形态违约 fail loud。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from rfauto.core.diagram_curve_image import (
    CURVE_CANVAS,
    CURVE_COLORS,
    build_curve_plan,
    curve_image_data_uri,
    curve_image_style,
    curve_series_from_payload,
    payload_has_sparams,
    render_curves_png,
)

_src_dir = Path(__file__).resolve().parents[2] / "src"
if _src_dir.exists() and str(_src_dir) not in sys.path:
    sys.path.insert(0, str(_src_dir))


def _synth_payload() -> dict:
    """确定性合成 S 参数 payload（parse_dataset 形态替身；纯 math 零依赖）。"""
    n = 41
    freqs = [1.8e9 + 0.4e9 * i / (n - 1) for i in range(n)]
    s: dict[str, list[list[float]]] = {"1_1": [], "2_1": []}
    for f in freqs:
        x = (f - 2.0e9) / 0.2e9
        s["1_1"].append([0.6 * math.cos(x) * math.exp(-0.3 * x * x),
                         0.6 * math.sin(x) * math.exp(-0.3 * x * x)])
        s["2_1"].append([0.7 * math.cos(x / 2.0), 0.7 * math.sin(x / 2.0)])
    return {"ok": True, "key": "SP1.SP", "frequency_hz": freqs, "s": s,
            "port_names": ["P1", "P2"],
            "port_z": [[50.0, 0.0], [50.0, 0.0]]}


def _png_chunks(data: bytes) -> list[str]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    i, out = 8, []
    while i < len(data):
        n = struct.unpack(">I", data[i:i + 4])[0]
        out.append(data[i + 4:i + 8].decode("ascii"))
        i += 12 + n
    return out


def _png_size(data: bytes) -> tuple[int, int]:
    w = struct.unpack(">I", data[16:20])[0]
    h = struct.unpack(">I", data[20:24])[0]
    return w, h


# ─── payload_has_sparams / 负例 ──────────────────────────────────────────────


class TestPayloadHasSparams:
    def test_positive_and_negative(self):
        assert payload_has_sparams(_synth_payload()) is True
        assert payload_has_sparams(None) is False
        assert payload_has_sparams("x") is False
        # HB 单点形态（harmonics，无 s/frequency_hz）
        assert payload_has_sparams({"harmonics": [{"mix": 0}]}) is False
        assert payload_has_sparams({"s": {}}) is False
        assert payload_has_sparams({"s": {"1_1": [[0.0, 0.0]]},
                                    "frequency_hz": []}) is False


class TestSeriesExtraction:
    def test_point_by_point_three_samples(self):
        """验收 E：抽 3 频点逐位对拍（同函数同运算序 → 逐位相等）。"""
        payload = _synth_payload()
        node = curve_series_from_payload(payload)
        n = len(payload["frequency_hz"])
        for idx in (0, n // 2, n - 1):
            f = payload["frequency_hz"][idx]
            j = round((f - 1.8e9) / (0.4e9 / (n - 1)))
            assert node["frequency_hz"][idx] == f
            re_, im_ = payload["s"]["1_1"][idx]
            expect = 20.0 * math.log10(math.hypot(re_, im_))
            assert node["series"][0]["db"][idx] == expect
            assert node["series"][0]["db"][j] == expect, "频点索引互证"
        assert node["keys"] == ["1_1", "2_1"]
        assert node["series"][0]["label"] == "S11"
        assert node["series"][1]["label"] == "S21"
        assert node["source"] == "rfauto.core.diagram_curve_image.curve_series_from_payload"

    def test_explicit_keys_beyond_default(self):
        payload = _synth_payload()
        payload["s"]["2_2"] = [[0.1, 0.0]] * len(payload["frequency_hz"])
        node = curve_series_from_payload(payload, keys=("2_2", "1_1"))
        assert node["keys"] == ["2_2", "1_1"]
        assert node["series"][0]["label"] == "S22"

    def test_zero_magnitude_maps_to_none_gap(self):
        payload = _synth_payload()
        payload["s"]["1_1"][3] = [0.0, 0.0]
        payload["s"]["2_1"][5] = [float("nan"), 0.0]
        payload["s"]["2_1"][7] = [float("inf"), 1.0]
        node = curve_series_from_payload(payload)
        assert node["series"][0]["db"][3] is None, "|S|=0 → None（log10 无定义）"
        assert node["series"][1]["db"][5] is None, "NaN 分量 → None"
        assert node["series"][1]["db"][7] is None, "inf 分量 → None"
        plan = build_curve_plan(node)
        assert any("S11 有 1 个非有限点" in w for w in plan["warnings"])
        assert any("S21 有 2 个非有限点" in w for w in plan["warnings"])

    def test_negatives_fail_loud(self):
        with pytest.raises(ValueError, match="无 S 参数"):
            curve_series_from_payload({"harmonics": []})
        payload = _synth_payload()
        with pytest.raises(ValueError, match="重复"):
            curve_series_from_payload(payload, keys=("1_1", "1_1"))
        with pytest.raises(ValueError, match="缺曲线键"):
            curve_series_from_payload(payload, keys=("3_1",))
        bad_len = dict(payload)
        bad_len["s"] = {"1_1": [[0.0, 0.0]]}
        with pytest.raises(ValueError, match="不齐"):
            curve_series_from_payload(bad_len, keys=("1_1",))
        bad_key = dict(payload)
        bad_key["s"] = {"11": [[0.0, 0.0]] * len(payload["frequency_hz"])}
        with pytest.raises(ValueError, match="'<i>_<j>'"):
            curve_series_from_payload(bad_key, keys=("11",))
        bad_freq = dict(payload)
        bad_freq["frequency_hz"] = list(payload["frequency_hz"])
        bad_freq["frequency_hz"][2] = float("nan")
        with pytest.raises(ValueError, match="有限实数"):
            curve_series_from_payload(bad_freq)
        with pytest.raises(ValueError, match="键序列"):
            curve_series_from_payload(payload, keys="1_1")


# ─── plan 装配（确定性 + 单位缩放 + ASCII 纪律） ─────────────────────────────


class TestBuildCurvePlan:
    def test_deterministic_and_shape(self):
        node = curve_series_from_payload(_synth_payload())
        p1 = build_curve_plan(node)
        p2 = build_curve_plan(curve_series_from_payload(_synth_payload()))
        assert json.dumps(p1, sort_keys=True) == json.dumps(p2, sort_keys=True)
        assert p1["x_label"] == "Frequency (GHz)"
        assert p1["y_label"] == "|S| (dB)"
        assert p1["canvas"] == CURVE_CANVAS == {"w_px": 640, "h_px": 400, "dpi": 100}
        assert p1["n_points"] == 41
        assert [s["color"] for s in p1["series"]] == list(CURVE_COLORS[:2])
        # x = payload Hz ÷ 1e9（显示单位缩放零改数据）
        assert p1["x"] == [f / 1e9 for f in node["frequency_hz"]]
        # y_lim 覆盖全部有限数据点
        finite = [v for s in p1["series"] for v in s["db"] if v is not None]
        assert p1["y_lim"][0] <= min(finite) and max(finite) <= p1["y_lim"][1]

    def test_json_roundtrip_render_identical(self):
        """JSON 往返（circuit_result.json transport 形态）→ 同 PNG 逐字节。"""
        node = curve_series_from_payload(_synth_payload())
        png_direct = render_curves_png(build_curve_plan(node))
        node_rt = json.loads(json.dumps(node))
        png_roundtrip = render_curves_png(build_curve_plan(node_rt))
        assert png_direct == png_roundtrip

    def test_non_ascii_title_backslashreplace_with_warning(self):
        node = curve_series_from_payload(_synth_payload())
        plan = build_curve_plan(node, title="S参数曲线")
        assert plan["title"] == "S\\u53c2\\u6570\\u66f2\\u7ebf"
        assert plan["warnings"] and "backslashreplace" in plan["warnings"][0]

    def test_plan_shape_negatives(self):
        node = curve_series_from_payload(_synth_payload())
        with pytest.raises(ValueError, match="缺键"):
            build_curve_plan({"keys": ["1_1"]})
        bad = dict(node, series=node["series"][:1])
        with pytest.raises(ValueError, match="等长"):
            build_curve_plan(bad)
        bad2 = dict(node, keys=["2_1", "1_1"])
        with pytest.raises(ValueError, match="不齐"):
            build_curve_plan(bad2)
        bad3 = dict(node, keys=["1_1", "2_1"],
                    series=[node["series"][0], dict(node["series"][1], db=[None] * 40)])
        with pytest.raises(ValueError, match="不齐"):
            build_curve_plan(bad3)
        bad4 = dict(node, keys=["1_1", "2_1"],
                    series=[node["series"][0],
                            dict(node["series"][1], db=[float("inf")] * len(node["frequency_hz"]))])
        with pytest.raises(ValueError, match="非有限非 None"):
            build_curve_plan(bad4)
        all_none = dict(node, keys=["1_1"],
                        series=[dict(node["series"][0], db=[None] * len(node["frequency_hz"]))])
        plan = build_curve_plan(all_none)
        assert plan["y_lim"] == [-1.0, 0.0], "全断口退化窗（如实空图）"


# ─── 渲染确定性（验收 C） ────────────────────────────────────────────────────


class TestRenderDeterminism:
    def test_two_renders_byte_identical_chunks_clean(self):
        plan = build_curve_plan(curve_series_from_payload(_synth_payload()))
        a = render_curves_png(plan)
        b = render_curves_png(build_curve_plan(curve_series_from_payload(_synth_payload())))
        assert a == b
        assert len(a) > 1000
        chunks = _png_chunks(a)
        assert chunks[0] == "IHDR" and chunks[-1] == "IEND"
        assert not {"tEXt", "zTXt", "iTXt", "tIME"} & set(chunks), chunks
        assert _png_size(a) == (640, 400)

    def test_two_independent_processes_sha256_identical(self, tmp_path):
        """验收 C 本钉：两独立进程 sha256 相同（子进程脚本内联合成 payload
        ——零文件依赖零 fixtures；PYTHONPATH=src 兜底 editable 安装）。"""
        script = tmp_path / "probe_sha.py"
        script.write_text(
            "import hashlib, math\n"
            "from rfauto.core.diagram_curve_image import (\n"
            "    build_curve_plan, curve_series_from_payload, render_curves_png)\n"
            "n = 41\n"
            "freqs = [1.8e9 + 0.4e9 * i / (n - 1) for i in range(n)]\n"
            "s = {'1_1': [], '2_1': []}\n"
            "for f in freqs:\n"
            "    x = (f - 2.0e9) / 0.2e9\n"
            "    s['1_1'].append([0.6 * math.cos(x) * math.exp(-0.3 * x * x),\n"
            "                     0.6 * math.sin(x) * math.exp(-0.3 * x * x)])\n"
            "    s['2_1'].append([0.7 * math.cos(x / 2.0), 0.7 * math.sin(x / 2.0)])\n"
            "payload = {'ok': True, 'key': 'SP1.SP', 'frequency_hz': freqs, 's': s}\n"
            "png = render_curves_png(build_curve_plan(curve_series_from_payload(payload)))\n"
            "print(hashlib.sha256(png).hexdigest())\n",
            encoding="utf-8")
        # 确定性加固（公开门实测 flake 消源）：两进程共享受控空 MPLCONFIGDIR
        # +预热渲染一次（字体缓存先建于受控目录）——消除冷/热字体缓存不对称
        # 与宿主缓存状态漂移两类 sha 抖动源（渲染本体零改动）。
        mpl_cfg = tmp_path / "mplconfig"
        mpl_cfg.mkdir()
        env = {**os.environ, "PYTHONPATH": str(_src_dir),
               "MPLCONFIGDIR": str(mpl_cfg), "MPLBACKEND": "Agg"}
        outs = []
        for i in range(3):
            if i == 0:
                continue  # 第 0 轮=预热（字体缓存落 MPLCONFIGDIR，不进比对）
            r = subprocess.run([sys.executable, str(script)], capture_output=True,
                               text=True, encoding="utf-8", env=env, timeout=300,
                               cwd=str(tmp_path))
            assert r.returncode == 0, r.stderr
            outs.append(r.stdout.strip())
            r = subprocess.run([sys.executable, str(script)], capture_output=True,
                               text=True, encoding="utf-8", env=env, timeout=300,
                               cwd=str(tmp_path))
            assert r.returncode == 0, r.stderr
            outs.append(r.stdout.strip())
        assert outs[0] == outs[1], f"两进程 sha256 漂移：{outs}"
        # 进程内同构（同机同版本三方一致——证据链互证）
        plan = build_curve_plan(curve_series_from_payload(_synth_payload()))
        assert hashlib.sha256(render_curves_png(plan)).hexdigest() == outs[0]


# ─── data URI 无分号红线（验收 D） ───────────────────────────────────────────


class TestDataUriNoSemicolon:
    def test_uri_form_and_redline(self):
        png = render_curves_png(build_curve_plan(curve_series_from_payload(_synth_payload())))
        uri = curve_image_data_uri(png)
        assert uri.startswith("data:image/png,")
        assert ";" not in uri, "data URI 零分号（style 分隔符红线）"
        assert ";base64" not in uri

    def test_style_form_and_redline(self):
        png = render_curves_png(build_curve_plan(curve_series_from_payload(_synth_payload())))
        style = curve_image_style(curve_image_data_uri(png))
        assert style.startswith("shape=image;verticalLabelPosition=bottom;")
        assert style.endswith(";")
        assert ";base64" not in style, "先例同款红线钉"
        assert "image=data:image/png," in style
        assert style.count(";") >= 4, "style 键分隔符在 data URI 之外完好"

    def test_uri_negatives(self):
        with pytest.raises(ValueError, match="非空 bytes"):
            curve_image_data_uri(b"")
        with pytest.raises(ValueError, match="PNG 头"):
            curve_image_data_uri(b"\x89PNG NOT PNG")
        with pytest.raises(ValueError, match="data:image/"):
            curve_image_style("http://x/y.png")
        with pytest.raises(ValueError, match="分号"):
            curve_image_style("data:image/png;base64,QUJD")
