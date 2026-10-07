"""service/field_audit_service.py（Y2 场图多模态审计封装接口）测试。

全离线零网络（#139：多模态通道一律注入 fake client 钉住）；
PNG 夹具用 zlib+struct 手工构造（确定性字节，无渲染器依赖）。
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

from rfauto.service.field_audit_service import (
    build_field_audit_request,
    dispatch_field_audit,
    png_precheck,
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
