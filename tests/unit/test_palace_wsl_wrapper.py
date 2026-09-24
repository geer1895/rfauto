"""palace_wsl_wrapper.py 生成器单测（E-MED-6）。

三态面（生成/幂等/--check）全离线：monkeypatch BIN_DIR 到 tmp_path、
_wsl_helper_path 钉常量（POSIX 上 tmp 路径无盘符段，路径推导另有专门
护栏测试）——CI（Linux）与本机（Windows）同一套语义断言。

真实资产 `--check` 门（tools/palace-install/bin/palace.cmd 在位才执行、
缺席 skip——机器状态单门；--check 是纯字节对比零 WSL 调用，无 #139 风
险面）：这是 wrapper 质量门的实际执行点，本地全量 pytest 门即覆盖；
GitHub runner 无 tools/ 资产 → skip（graceful，ci.yml 条件步同口径）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(scripts_dir))

import palace_wsl_wrapper as psw

# 生成的 wrapper 资产（tools/ 不入 git；在位与否决定真实资产门是否执行）
_REAL_BIN_DIR = scripts_dir.parent / "tools" / "palace-install" / "bin"
_HELPER_PIN = "/mnt/e/rfauto/tools/palace-install/bin/palace_wsl.sh"


@pytest.fixture()
def sandbox_bin(tmp_path, monkeypatch):
    """隔离的生成沙箱：BIN_DIR→tmp_path、helper 路径钉常量（内容跨平台稳定）。"""
    bindir = tmp_path / "bin"
    monkeypatch.setattr(psw, "BIN_DIR", bindir)
    monkeypatch.setattr(psw, "_wsl_helper_path", lambda: _HELPER_PIN)
    return bindir


class TestDriveLetterGuard:
    """盘符提取护栏（extract_drive_letter，E-MED-6）。

    历史实现对首段 '/'（POSIX 绝对路径）或相对路径静默提取出空串得
    /mnt// 坏路径——改为 ValueError 显式报错。纯函数，跨平台同断言。
    """

    def test_windows_drive_forms(self):
        # Path.parts 首段实测形态（bridge_criteria §2）：'E:\\' 带反斜杠尾
        assert psw.extract_drive_letter(("E:\\", "rfauto", "tools")) == "e"
        assert psw.extract_drive_letter(("C:", "x")) == "c"
        assert psw.extract_drive_letter(("d:/", "y")) == "d"

    @pytest.mark.parametrize("parts", [
        ("/", "home", "x"),               # POSIX 绝对路径首段
        (("relative", "path")),           # 相对路径
        ("\\\\server\\share", "x"),        # UNC 首段
        ("", "x"),                        # 空段
        (),                               # 空 parts
    ])
    def test_non_drive_first_segment_rejected(self, parts):
        with pytest.raises(ValueError, match="Windows 盘符"):
            psw.extract_drive_letter(tuple(parts))

    def test_real_bin_dir_helper_path_mounted_form(self):
        """真实安装布局（Windows 盘符根）推导 /mnt/<盘>/... 形态；非盘符布局
        （异常嵌入/打包环境）显式报错而非静默坏路径。"""
        try:
            helper = psw._wsl_helper_path()
        except ValueError:
            return  # 非 Windows 盘符布局（CI Linux 仓检出）：护栏已生效
        assert helper.startswith("/mnt/")
        assert helper.endswith("/palace_wsl.sh")
        assert "tools/palace-install/bin" in helper


class TestGenerateAndCheck:
    """生成器三态面（生成/幂等/--check 三态），in-process main() 全覆盖。"""

    def test_generate_writes_two_ascii_lf_files(self, sandbox_bin, capsys):
        rc = psw.main([])
        assert rc == 0
        cmd, sh = sandbox_bin / "palace.cmd", sandbox_bin / "palace_wsl.sh"
        assert cmd.is_file() and sh.is_file()
        for p in (cmd, sh):
            raw = p.read_bytes()
            assert b"\x00" not in raw
            raw.decode("ascii")  # ASCII-only（坑账 #89/#271：工具脚本零非 ASCII）
        assert b"\r\n" not in sh.read_bytes()  # bash 对 CRLF 零容忍
        assert b"\r\n" not in cmd.read_bytes()  # 生成器统一 LF
        assert _HELPER_PIN.encode() in cmd.read_bytes()
        assert psw.WSL_DISTRO.encode() in cmd.read_bytes()
        assert b"do not hand-edit" in cmd.read_bytes()
        out = capsys.readouterr().out
        assert "WROTE" in out

    def test_generate_is_idempotent(self, sandbox_bin):
        psw.main([])
        snapshot = {p: p.read_bytes() for p in sandbox_bin.iterdir()}
        psw.main([])  # 二次生成：内容钉死不漂移
        for p, raw in snapshot.items():
            assert p.read_bytes() == raw

    def test_check_ok_after_generate(self, sandbox_bin, capsys):
        psw.main([])
        capsys.readouterr()
        assert psw.main(["--check"]) == 0
        out = capsys.readouterr().out
        assert "OK:" in out

    def test_check_detects_drift(self, sandbox_bin, capsys):
        psw.main([])
        target = sandbox_bin / "palace_wsl.sh"
        target.write_bytes(target.read_bytes() + b"# drifted\n")
        capsys.readouterr()
        assert psw.main(["--check"]) == 1
        assert "DRIFT" in capsys.readouterr().out

    def test_check_detects_missing(self, sandbox_bin, capsys):
        psw.main([])
        (sandbox_bin / "palace.cmd").unlink()
        capsys.readouterr()
        assert psw.main(["--check"]) == 1
        assert "MISSING" in capsys.readouterr().out


class TestRealAssetsGate:
    """真实资产 `--check` 质量门（本地全量 pytest 即执行；资产缺席 skip）。

    tools/palace-install/bin/ 是 wrapper 的仓内安装面（不入 git）：在位时
    必须与生成器钉死内容逐字节一致（官方 wrapper CRLF 修复等资产漂移在
    此拦下）；缺席（CI/GitHub runner/干净检出）→ skip，不红。
    """

    @pytest.mark.skipif(
        not (_REAL_BIN_DIR / "palace.cmd").is_file(),
        reason=f"palace wrapper assets not installed ({_REAL_BIN_DIR}); "
               "generate via scripts/palace_wsl_wrapper.py",
    )
    def test_installed_wrapper_matches_pinned_content(self):
        rc = subprocess.run(
            [sys.executable, str(scripts_dir / "palace_wsl_wrapper.py"), "--check"],
            capture_output=True, text=True, timeout=120, check=False,
        )
        assert rc.returncode == 0, f"--check 门红:\n{rc.stdout}\n{rc.stderr}"
        assert "OK:" in rc.stdout
        assert "DRIFT" not in rc.stdout and "MISSING" not in rc.stdout
