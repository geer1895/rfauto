"""W1-F 席 E-09：scripts/check_encoding.py 纯函数单测（H1-11 零测试收口）。

判定逻辑抽成纯函数 check_bytes/is_skipped 后的回归钉：violation 文案与
main 历史输出逐字节同形（门消费者按串匹配不受影响）；BOM/非 UTF-8/干净
三路 + 跳过集纯函数两路。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import check_encoding


class TestCheckBytes:
    def test_clean_utf8_returns_none(self):
        assert check_encoding.check_bytes("a.py", "中文 ok\n".encode()) is None

    def test_bom_detected_with_exact_legacy_message(self):
        raw = b"\xef\xbb\xbf" + b"x=1\n"
        assert check_encoding.check_bytes("a.py", raw) == "a.py: UTF-8 BOM detected"

    def test_invalid_utf8_reports_decoder_message(self):
        raw = b"\xa0\xa1"  # 非 UTF-8 双字节（GBK 误存硬信号）
        msg = check_encoding.check_bytes("b.md", raw)
        assert msg is not None and msg.startswith("b.md: not valid UTF-8 (")
        assert "'utf-8' codec" in msg

    def test_empty_bytes_clean(self):
        assert check_encoding.check_bytes("empty.txt", b"") is None


class TestIsSkipped:
    def test_binary_suffix_skipped(self):
        assert check_encoding.is_skipped("assets/logo.PNG") is True  # 后缀小写比较
        assert check_encoding.is_skipped("a/b/c.s2p") is True

    def test_vendor_dir_skipped(self):
        assert check_encoding.is_skipped("pyaedt-main/x/core.py") is True
        assert check_encoding.is_skipped("src/.venv/lib/m.py") is True

    def test_normal_source_not_skipped(self):
        assert check_encoding.is_skipped("src/rfauto/core/x.py") is False


def test_main_clean_tree_smoke(tmp_path, monkeypatch, capsys):
    """main 全链路冒烟：干净小树 → exit 0 + clean 行（输出格式钉）。"""
    (tmp_path / "ok.py").write_text("print('hi')\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(check_encoding, "tracked_files", lambda: ["ok.py"])
    rc = check_encoding.main()
    out = capsys.readouterr().out
    assert rc == 0 and out == "Encoding check: clean (1 files).\n"


def test_main_reports_violation_and_exit_1(tmp_path, monkeypatch, capsys):
    (tmp_path / "bad.py").write_bytes(b"\xef\xbb\xbfprint(1)\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(check_encoding, "tracked_files", lambda: ["bad.py"])
    rc = check_encoding.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "ENCODING CHECK: 1 violations" in out
    assert "bad.py: UTF-8 BOM detected" in out
