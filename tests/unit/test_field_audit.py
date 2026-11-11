"""service/field_audit_service.py（Y2 场图多模态审计封装接口）测试。

全离线零网络（#139：多模态通道一律注入 fake client 钉住）；
PNG/JPEG 夹具用 zlib+struct 手工构造（确定性字节，无渲染器依赖）。
T-Q6 泛化面（jpeg/svg 预检+audit_artifact 路由）自本文件 TestJpegPrecheck 起。
"""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

from rfauto.service.field_audit_service import (
    audit_artifact,
    build_field_audit_request,
    dispatch_field_audit,
    jpeg_precheck,
    png_precheck,
    svg_precheck,
)


def _make_png(path: Path, w: int = 8, h: int = 8, color: bytes = b"\x40\x80\xc0") -> None:
    """手工构造合法 PNG（8-bit RGB，规范布局：签名+IHDR+IDAT+IEND）。"""

    def chunk(typ: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + color * w for _ in range(h))
    blob = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    path.write_bytes(blob)


class TestPngPrecheck:
    def test_valid_png_dims_and_fingerprint(self, tmp_path: Path):
        p = tmp_path / "ez.png"
        _make_png(p, w=16, h=9)
        out = png_precheck(p)
        assert out["ok"] is True
        assert out["width_px"] == 16
        assert out["height_px"] == 9
        assert out["degenerate"] is False
        assert len(out["sha256"]) == 64
        # 同字节同指纹（确定性）
        assert png_precheck(p)["sha256"] == out["sha256"]

    def test_degenerate_tiny_png(self, tmp_path: Path):
        p = tmp_path / "tiny.png"
        _make_png(p, w=1, h=1)
        out = png_precheck(p)
        assert out["ok"] is True
        assert out["degenerate"] is True

    def test_non_png_rejected(self, tmp_path: Path):
        p = tmp_path / "fake.png"
        p.write_bytes(b"not a png at all........")
        out = png_precheck(p)
        assert out["ok"] is False
        assert "签名不符" in out["errors"][0]

    def test_missing_file_error(self, tmp_path: Path):
        out = png_precheck(tmp_path / "nope.png")
        assert out["ok"] is False


class TestBuildRequest:
    def test_prompt_deterministic_three_questions(self, tmp_path: Path):
        p1 = tmp_path / "a.png"
        p2 = tmp_path / "b.png"
        _make_png(p1)
        _make_png(p2)
        r1 = build_field_audit_request([p1, p2], template="patch")
        r2 = build_field_audit_request([p1, p2], template="patch")
        assert r1["ok"] is True
        assert r1["prompt"] == r2["prompt"]  # 同输入逐字节同请求
        # 三问清单（被困/热点/馈电激励）
        assert "被困" in r1["prompt"]
        assert "热点" in r1["prompt"]
        assert "馈电激励" in r1["prompt"]
        assert len(r1["images"]) == 2
        assert r1["context"]["template"] == "patch"

    def test_custom_question_and_port_note(self, tmp_path: Path):
        p = tmp_path / "a.png"
        _make_png(p)
        out = build_field_audit_request(
            [p], port_note="馈点 x=0", question="第 4 问：边缘场？")
        assert "馈点 x=0" in out["prompt"]
        assert "第 4 问" in out["prompt"]
        assert out["context"]["questions"][-1] == "第 4 问：边缘场？"

    def test_empty_paths_rejected(self):
        assert build_field_audit_request([])["ok"] is False

    def test_mixed_readable_and_broken(self, tmp_path: Path):
        good = tmp_path / "good.png"
        bad = tmp_path / "bad.png"
        _make_png(good)
        bad.write_bytes(b"junk-junk-junk-junk-junk")
        out = build_field_audit_request([good, bad])
        assert out["ok"] is True
        assert len(out["images"]) == 1
        assert len(out["precheck_errors"]) == 1

    def test_all_broken_rejected(self, tmp_path: Path):
        bad = tmp_path / "bad.png"
        bad.write_bytes(b"junk-junk-junk-junk-junk")
        out = build_field_audit_request([bad])
        assert out["ok"] is False
        assert out["precheck_errors"]


class TestDispatch:
    def _request(self, tmp_path: Path) -> dict:
        p = tmp_path / "a.png"
        _make_png(p)
        return build_field_audit_request([p], run_id="run_x")

    def test_no_client_is_skipped_not_failed(self, tmp_path: Path):
        """缺省无 client=skipped（ok=True），#105 best-effort 口径。"""
        out = dispatch_field_audit(self._request(tmp_path), client=None)
        assert out["ok"] is True
        assert out["skipped"] is True
        assert "client 未配置" in out["reason"]

    def test_injected_fake_client_payload_and_result(self, tmp_path: Path):
        """#139：通道=注入 fake client；payload 含 prompt/路径/上下文。"""
        calls: list[dict] = []

        def fake_client(payload: dict) -> dict:
            calls.append(payload)
            return {"findings": ["无被困证据"], "ok": True}

        req = self._request(tmp_path)
        out = dispatch_field_audit(req, client=fake_client)
        assert out["ok"] is True
        assert out["result"] == {"findings": ["无被困证据"], "ok": True}
        assert len(calls) == 1
        assert calls[0]["images"] == [str(tmp_path / "a.png")]
        assert "被困" in calls[0]["prompt"]
        assert out["request_echo"]["context"]["run_id"] == "run_x"

    def test_client_exception_preserves_request(self, tmp_path: Path):
        def boom(payload: dict) -> dict:
            raise RuntimeError("通道挂了")

        req = self._request(tmp_path)
        out = dispatch_field_audit(req, client=boom)
        assert out["ok"] is False
        assert "通道挂了" in out["errors"][0]
        # 原请求保留（可重放）
        assert "prompt" in out["request_json"]

    def test_bad_request_passthrough(self, tmp_path: Path):
        bad = {"ok": False, "errors": ["x"]}
        assert dispatch_field_audit(bad, client=None) is bad


# ---------------------------------------------------------------------------
# T-Q6 泛化面：JPEG/SVG 预检 + audit_artifact 按扩展名路由
# ---------------------------------------------------------------------------

_SVG_SAMPLE = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<svg width="210mm" height="297mm" viewBox="0 0 210 297" '
    'xmlns="http://www.w3.org/2000/svg">\n'
    '  <g id="outline">\n'
    '    <rect x="0" y="0" width="210" height="297"/>\n'
    '    <path d="M 10 10 L 20 20"/>\n'
    "  </g>\n"
    '  <text x="10" y="20">RF filter</text>\n'
    "</svg>\n"
)


def _make_jpeg(path: Path, w: int = 16, h: int = 12,
               sof_marker: int = 0xC0) -> None:
    """手工构造最小 JPEG（SOI+APP0+SOF+EOI；标记结构合法、无熵数据）。"""
    app0 = (b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00"
            + b"\x01\x02" + b"\x00" + b"\x00\x01" + b"\x00\x01" + b"\x00\x00")
    sof = (b"\xff" + struct.pack(">B", sof_marker)
           + struct.pack(">HBHHB", 11, 8, h, w, 1) + b"\x01\x22\x00")
    path.write_bytes(b"\xff\xd8" + app0 + sof + b"\xff\xd9")


def _j(env: dict) -> str:
    return json.dumps(env, ensure_ascii=False)


class TestJpegPrecheck:
    def test_valid_jpeg_sof0_dims_and_fingerprint(self, tmp_path: Path):
        p = tmp_path / "ez.jpg"
        _make_jpeg(p, w=16, h=12)
        out = jpeg_precheck(p)
        assert out["ok"] is True
        assert out["width_px"] == 16
        assert out["height_px"] == 12
        assert out["degenerate"] is False
        assert len(out["sha256"]) == 64
        assert jpeg_precheck(p)["sha256"] == out["sha256"]

    def test_progressive_sof2_also_parsed(self, tmp_path: Path):
        p = tmp_path / "prog.jpg"
        _make_jpeg(p, w=8, h=9, sof_marker=0xC2)
        out = jpeg_precheck(p)
        assert out["ok"] is True
        assert (out["width_px"], out["height_px"]) == (8, 9)

    def test_degenerate_tiny_jpeg(self, tmp_path: Path):
        p = tmp_path / "tiny.jpg"
        _make_jpeg(p, w=1, h=1)
        assert jpeg_precheck(p)["degenerate"] is True

    def test_non_jpeg_rejected(self, tmp_path: Path):
        p = tmp_path / "fake.jpg"
        p.write_bytes(b"not a jpeg at all........")
        out = jpeg_precheck(p)
        assert out["ok"] is False
        assert "签名不符" in out["errors"][0]

    def test_missing_sof_rejected(self, tmp_path: Path):
        """SOI+APP0+EOI 无帧头 → 显式报错（不猜尺寸）。"""
        p = tmp_path / "nosof.jpg"
        app0 = (b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00"
                + b"\x01\x02" + b"\x00" + b"\x00\x01" + b"\x00\x01"
                + b"\x00\x00")
        p.write_bytes(b"\xff\xd8" + app0 + b"\xff\xd9")
        out = jpeg_precheck(p)
        assert out["ok"] is False
        assert "SOF" in out["errors"][0]

    def test_missing_file_error(self, tmp_path: Path):
        assert jpeg_precheck(tmp_path / "nope.jpg")["ok"] is False


class TestSvgPrecheck:
    def test_valid_svg_attrs_and_counts(self, tmp_path: Path):
        p = tmp_path / "ez.svg"
        p.write_text(_SVG_SAMPLE, encoding="utf-8")
        out = svg_precheck(p)
        assert out["ok"] is True
        # 属性原文（单位不换算、数值不派生——直读口径）
        assert out["width_attr"] == "210mm"
        assert out["height_attr"] == "297mm"
        assert out["view_box"] == "0 0 210 297"
        assert out["element_counts"]["rect"] == 1
        assert out["element_counts"]["path"] == 1
        assert out["element_counts"]["g"] == 1
        assert out["element_counts"]["text"] == 1
        assert out["element_counts"]["circle"] == 0
        # 几何/引用类：rect+path（text/g 不计入 draw 面）
        assert out["n_draw_elements"] == 2

    def test_missing_root_rejected(self, tmp_path: Path):
        p = tmp_path / "bad.svg"
        p.write_text("<html><body>not svg</body></html>", encoding="utf-8")
        out = svg_precheck(p)
        assert out["ok"] is False
        assert "缺 <svg> 根元素" in out["errors"][0]

    def test_single_quoted_attrs(self, tmp_path: Path):
        p = tmp_path / "sq.svg"
        p.write_text("<svg width='10mm' height='20mm'></svg>",
                     encoding="utf-8")
        out = svg_precheck(p)
        assert out["ok"] is True
        assert out["width_attr"] == "10mm"
        assert out["height_attr"] == "20mm"
        assert out["view_box"] is None


class TestAuditArtifact:
    def test_png_route_reuses_image_face(self, tmp_path: Path):
        """.png → 既有图像审计面（三问 prompt 复用，零复制零漂移）。"""
        p = tmp_path / "ez.png"
        _make_png(p)
        out = audit_artifact(p)
        assert out["ok"] is True
        assert out["kind"] == "image_png"
        assert out["path"] == str(p)
        assert "被困" in out["prompt"]  # 既有三问
        assert len(out["images"]) == 1
        assert out["images"][0]["width_px"] == 8
        assert out["context"]["kind"] == "image_png"

    def test_jpeg_route_via_jpeg_precheck(self, tmp_path: Path):
        """.jpg → jpeg_precheck（非 png_precheck）+ 同一图像审计面。"""
        p = tmp_path / "ez.jpg"
        _make_jpeg(p, w=16, h=12)
        out = audit_artifact(p)
        assert out["ok"] is True
        assert out["kind"] == "image_jpeg"
        assert out["images"][0]["width_px"] == 16
        assert "被困" in out["prompt"]

    def test_svg_route_prompt_carries_summary(self, tmp_path: Path):
        """.svg → 文本可直读：prompt 携带确定性结构摘要+结构性二问。"""
        p = tmp_path / "ez.svg"
        p.write_text(_SVG_SAMPLE, encoding="utf-8")
        out = audit_artifact(p, question="第 3 问：层次结构？")
        assert out["ok"] is True
        assert out["kind"] == "svg"
        assert "210mm" in out["prompt"]  # 画布声明原文
        assert "rect=1" in out["prompt"]  # 元素计数摘要
        assert out["context"]["questions"][-1] == "第 3 问：层次结构？"
        assert len(out["context"]["questions"]) == 3  # 二问+自定义

    def test_unknown_kind_explicit_skip(self, tmp_path: Path):
        """其他扩展名 → 显式 unknown（skipped 非失败；能力不适用口径）。"""
        p = tmp_path / "doc.txt"
        p.write_text("plain text", encoding="utf-8")
        out = audit_artifact(p)
        assert out["ok"] is True
        assert out["skipped"] is True
        assert out["kind"] == "unknown"
        assert "无审计路由" in out["reason"]

    def test_broken_png_error_envelope(self, tmp_path: Path):
        p = tmp_path / "bad.png"
        p.write_bytes(b"junk-junk-junk-junk-junk")
        out = audit_artifact(p)
        assert out["ok"] is False
        assert out["kind"] == "image_png"
        assert "签名不符" in out["errors"][0]

    def test_double_run_byte_identical(self, tmp_path: Path):
        png = tmp_path / "a.png"
        _make_png(png)
        svg = tmp_path / "b.svg"
        svg.write_text(_SVG_SAMPLE, encoding="utf-8")
        assert _j(audit_artifact(png)) == _j(audit_artifact(png))
        assert _j(audit_artifact(svg)) == _j(audit_artifact(svg))

    def test_svg_request_dispatchable(self, tmp_path: Path):
        """泛化请求与 dispatch_field_audit 形状兼容（注入 fake client）。"""
        p = tmp_path / "ez.svg"
        p.write_text(_SVG_SAMPLE, encoding="utf-8")
        calls: list[dict] = []

        def fake_client(payload: dict) -> dict:
            calls.append(payload)
            return {"findings": ["结构一致"], "ok": True}

        req = audit_artifact(p)
        out = dispatch_field_audit(req, client=fake_client)
        assert out["ok"] is True
        assert out["result"]["findings"] == ["结构一致"]
        assert calls[0]["images"] == [str(p)]
        assert "SVG" in calls[0]["prompt"]
        assert calls[0]["context"]["kind"] == "svg"
