"""VB-3 严格结果访问器层测试（aurora_r 席位 R-12，2026-11-10）。

正负例矩阵（任务书契约）：
- resolve_unique_result_file：恰一匹配 / 0 个 / 2 个 / ``..`` / 绝对路径 /
  符号链接越界（Windows 无符号链接权限时如实 skip）；
- require_finite_vector/array：NaN/Inf/空/复数（实数口径）/二维/非数值；
- require_strictly_increasing：倒退 / 重复频点（差恰 0）/ ULP 级近重复
  （math.nextafter 精确构造 1/8 倍 ulp=违例、9/12 倍 ulp=放行）；
- require_exact_port/key：不存在即报错，字符串/浮点/布尔一律不猜别名；
- validate_network_strict：clean 网络过、NaN S 矩阵/非单调频轴/ULP 近重复
  各自抛对应类型化错误；
- interchange strict 选通：strict=False 对坏文件照常读取（缺省逐位零变化
  证据）、strict=True 抛类型化错误（消息含文件名+规则名）；
- runs/ 证据区真机 sNp ≥2 件 strict 通过（找不到如实 skip=UNVERIFIED）。

全部离线（真机面只读 runs/ 既有证据，不新跑仿真）；错误断言统一验
"消息含文件名 + 规则名"（VB-3 契约）。
"""

from __future__ import annotations

import itertools
import math
from pathlib import Path

import numpy as np
import os
import pytest
import skrf

from rfauto.adapters.interchange import export_touchstone, read_touchstone
from rfauto.core.strict_access import (
    ULP_NEAR_DUPLICATE_TOLERANCE,
    StrictExactKeyError,
    StrictFiniteVectorError,
    StrictMonotonicFreqError,
    StrictPathRejectedError,
    StrictSymlinkEscapeError,
    StrictUlpNearDuplicateError,
    StrictUniqueFileError,
    require_exact_key,
    require_exact_port,
    require_finite_array,
    require_finite_vector,
    require_strictly_increasing,
    resolve_unique_result_file,
    validate_network_strict,
)

_REPO = Path(__file__).resolve().parents[2]


def _advance_ulp(value: float, steps: int) -> float:
    """沿 +inf 精确推进 steps 个 ulp（math.nextafter 逐步，无舍入歧义）。"""
    out = float(value)
    for _ in range(int(steps)):
        out = math.nextafter(out, math.inf)
    return out


def _clean_network(n_freq: int = 21, n_ports: int = 3) -> skrf.Network:
    freq = skrf.Frequency(1.5, 3.5, n_freq, unit="GHz")
    s = np.zeros((n_freq, n_ports, n_ports), dtype=complex)
    s[:, 0, 0] = 0.1
    return skrf.Network(frequency=freq, s=s, z0=50.0)


def _write_s1p(path: Path, rows: list[str]) -> Path:
    """手写 1 端口 MA 格式 Touchstone（行文本完全可控，供坏文件构造）。"""
    lines = ["# GHz S MA R 50", *rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ── resolve_unique_result_file ──────────────────────────────────────────────


class TestResolveUniqueResultFile:
    def test_unique_match_ok(self, tmp_path):
        (tmp_path / "results").mkdir()
        target = tmp_path / "results" / "params.s2p"
        target.write_text("# GHz S MA R 50\n1 1 0\n", encoding="utf-8")
        got = resolve_unique_result_file(tmp_path, "results/*.s2p")
        assert got == target

    def test_zero_matches(self, tmp_path):
        with pytest.raises(StrictUniqueFileError) as ei:
            resolve_unique_result_file(tmp_path, "*.s2p")
        assert "unique_file_match" in str(ei.value)
        assert str(tmp_path) in str(ei.value)

    def test_two_matches_lists_candidates(self, tmp_path):
        for name in ("a.s2p", "b.s2p"):
            (tmp_path / name).write_text("# GHz S MA R 50\n1 1 0\n", encoding="utf-8")
        with pytest.raises(StrictUniqueFileError) as ei:
            resolve_unique_result_file(tmp_path, "*.s2p")
        msg = str(ei.value)
        assert "unique_file_match" in msg and "a.s2p" in msg and "b.s2p" in msg

    @pytest.mark.parametrize("pattern", ["../outside.s2p", "a/../b.s2p"])
    def test_reject_dotdot(self, tmp_path, pattern):
        with pytest.raises(StrictPathRejectedError) as ei:
            resolve_unique_result_file(tmp_path, pattern)
        assert "path_containment" in str(ei.value)

    @pytest.mark.skipif(os.name != "nt",
                        reason="C:/ 盘符与反斜杠形态参数=Windows 路径语义"
                               "（POSIX 下非绝对路径，报错形态不同）——诚实 skip")
    @pytest.mark.parametrize("pattern", ["/abs/x.s2p", "C:/x.s2p", "\\x.s2p"])
    def test_reject_absolute(self, tmp_path, pattern):
        with pytest.raises(StrictPathRejectedError):
            resolve_unique_result_file(tmp_path, pattern)

    def test_missing_root(self, tmp_path):
        with pytest.raises(StrictUniqueFileError):
            resolve_unique_result_file(tmp_path / "nope", "*.s2p")

    def test_directory_match_not_counted(self, tmp_path):
        (tmp_path / "sub.s2p").mkdir()  # 目录撞模式：不计入文件匹配
        with pytest.raises(StrictUniqueFileError):
            resolve_unique_result_file(tmp_path, "*.s2p")

    def test_symlink_escape(self, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "leaked.s2p").write_text("# GHz S MA R 50\n1 1 0\n", encoding="utf-8")
        root = tmp_path / "root"
        root.mkdir()
        link = root / "evil.s2p"
        made = False
        try:
            link.symlink_to(outside / "leaked.s2p")
            made = True
            pattern = "*.s2p"
        except OSError:
            # Windows 无符号链接权限：降级目录联接（mklink /J 无需管理员），
            # 联接指向根外目录、glob 穿透——逃逸检测同面可验。
            import subprocess

            junction = root / "link"
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                capture_output=True, text=True)
            if result.returncode != 0:
                pytest.skip("符号链接与目录联接权限均不可用（如实 skip）")
            made = True
            pattern = "link/*.s2p"
        finally:
            if not made and link.exists():
                pass  # 未建成无需清理
        with pytest.raises(StrictSymlinkEscapeError) as ei:
            resolve_unique_result_file(root, pattern)
        assert "symlink_escape" in str(ei.value)


# ── require_finite_vector / require_finite_array ────────────────────────────


class TestRequireFiniteVector:
    def test_ok_passthrough(self):
        out = require_finite_vector([1.0, 2.0, 3.0], source="x.s2p", name="f")
        assert out.dtype == np.float64
        np.testing.assert_array_equal(out, [1.0, 2.0, 3.0])

    def test_empty_rejected(self):
        with pytest.raises(StrictFiniteVectorError) as ei:
            require_finite_vector([], source="x.s2p", name="f")
        assert "finite_nonempty_vector" in str(ei.value)

    def test_nan_reports_index_and_count(self):
        with pytest.raises(StrictFiniteVectorError) as ei:
            require_finite_vector([1.0, float("nan"), 3.0], source="x.s2p", name="f")
        assert ei.value.details["n_nan"] == 1
        assert ei.value.details["first_bad_index"] == [1]

    @pytest.mark.parametrize("bad", [float("inf"), float("-inf")])
    def test_inf_rejected(self, bad):
        with pytest.raises(StrictFiniteVectorError):
            require_finite_vector([1.0, bad], source="x.s2p", name="f")

    def test_complex_rejected_for_real_vector(self):
        with pytest.raises(StrictFiniteVectorError) as ei:
            require_finite_vector(np.array([1 + 0j, 2 + 0j]), source="x.s2p", name="f")
        assert "实数" in str(ei.value)

    def test_two_dim_rejected(self):
        with pytest.raises(StrictFiniteVectorError):
            require_finite_vector([[1.0], [2.0]], source="x.s2p", name="f")

    def test_non_numeric_rejected(self):
        with pytest.raises(StrictFiniteVectorError):
            require_finite_vector(["a", "b"], source="x.s2p", name="f")


class TestRequireFiniteArray:
    def test_clean_complex_allowed(self):
        out = require_finite_array(np.array([1 + 2j, 3 + 4j]), source="x.s2p", name="s")
        assert np.iscomplexobj(out)

    def test_complex_nan_rejected(self):
        with pytest.raises(StrictFiniteVectorError) as ei:
            require_finite_array(np.array([1 + 2j, complex(float("nan"), 0)]),
                                 source="x.s2p", name="s")
        assert ei.value.details["n_nan"] == 1


# ── require_strictly_increasing ─────────────────────────────────────────────


class TestRequireStrictlyIncreasing:
    def test_ok_clean_gap(self):
        freq = np.array([2.0e9, 2.25e9, 2.5e9])
        np.testing.assert_array_equal(require_strictly_increasing(freq, source="x"), freq)

    def test_single_point_trivially_ok(self):
        np.testing.assert_array_equal(
            require_strictly_increasing([2.4e9], source="x"), [2.4e9])

    def test_decreasing_rejected(self):
        with pytest.raises(StrictMonotonicFreqError) as ei:
            require_strictly_increasing([2.5e9, 2.0e9], source="x.s2p")
        assert "strictly_increasing_freq" in str(ei.value)
        assert "倒退" in str(ei.value)

    def test_exact_duplicate_rejected(self):
        with pytest.raises(StrictMonotonicFreqError) as ei:
            require_strictly_increasing([1.0e9, 1.0e9], source="x.s2p")
        assert "重复频点" in str(ei.value)

    def test_one_ulp_gap_flagged(self):
        f0 = 2.0e9
        arr = [f0, _advance_ulp(f0, 1)]
        with pytest.raises(StrictUlpNearDuplicateError) as ei:
            require_strictly_increasing(arr, source="x.s2p")
        assert "ulp_near_duplicate_freq" in str(ei.value)
        assert ei.value.details["index"] == 0

    def test_gap_at_tolerance_is_flagged(self):
        f0 = 2.0e9
        arr = [f0, _advance_ulp(f0, ULP_NEAR_DUPLICATE_TOLERANCE)]
        with pytest.raises(StrictUlpNearDuplicateError):
            require_strictly_increasing(arr, source="x.s2p")

    def test_gap_just_over_tolerance_passes(self):
        f0 = 2.0e9  # 2^30 < f0 < 2^31：推进 ≤12 ulp 不跨二进制阶，ulp 恒定
        arr = [f0, _advance_ulp(f0, ULP_NEAR_DUPLICATE_TOLERANCE + 1)]
        np.testing.assert_array_equal(require_strictly_increasing(arr, source="x"), arr)

    def test_nan_checked_first(self):
        with pytest.raises(StrictFiniteVectorError):
            require_strictly_increasing([float("nan")], source="x.s2p")


# ── require_exact_port / require_exact_key（不猜别名） ───────────────────────


class TestExactPortAndKey:
    @pytest.mark.parametrize("port", [0, 1, np.int64(1)])
    def test_port_ok(self, port):
        assert require_exact_port(port, 2, source="x.s2p") == int(port)

    def test_port_out_of_range(self):
        with pytest.raises(StrictExactKeyError) as ei:
            require_exact_port(2, 2, source="x.s2p")
        assert "exact_key" in str(ei.value) and "[0, 2)" in str(ei.value)

    def test_port_negative_rejected(self):
        with pytest.raises(StrictExactKeyError):
            require_exact_port(-1, 2, source="x.s2p")

    @pytest.mark.parametrize("bad", ["1", 1.0, True, None])
    def test_port_no_alias_coercion(self, bad):
        """字符串 "1"/浮点 1.0/布尔 True 一律拒绝——端口名不做类型强转。"""
        with pytest.raises(StrictExactKeyError) as ei:
            require_exact_port(bad, 2, source="x.s2p")
        assert "不猜别名" in str(ei.value) or "强转" in str(ei.value)

    def test_key_ok(self):
        assert require_exact_key("S21", ["S11", "S21"], source="x.s2p") == "S21"

    def test_missing_key_lists_available(self):
        with pytest.raises(StrictExactKeyError) as ei:
            require_exact_key("S32", ["S11", "S21"], source="x.s2p", kind="端口名")
        msg = str(ei.value)
        assert "exact_key" in msg and "S11" in msg and "不回退别名" in msg

    def test_key_case_sensitive_no_fallback(self):
        """大小写不回退：请求 s21 而可用 S21 → 报错而非猜别名。"""
        with pytest.raises(StrictExactKeyError):
            require_exact_key("s21", ["S21"], source="x.s2p")

    def test_non_str_key_rejected(self):
        with pytest.raises(StrictExactKeyError):
            require_exact_key(21, ["21"], source="x.s2p")


# ── validate_network_strict（组合缝） ────────────────────────────────────────


class TestValidateNetworkStrict:
    def test_clean_network_passes(self):
        validate_network_strict(_clean_network(), source="clean.s3p")

    def test_nan_in_s_reported_with_source(self):
        net = _clean_network()
        net.s[3, 1, 0] = complex(float("nan"), 0.0)
        with pytest.raises(StrictFiniteVectorError) as ei:
            validate_network_strict(net, source="bad_nan.s3p")
        assert "bad_nan.s3p" in str(ei.value)
        assert ei.value.details["first_bad_index"] == [3, 1, 0]

    def test_non_monotonic_freq(self):
        freq = skrf.Frequency(2.0, 3.0, 5, unit="Hz")
        freq.f[:] = np.array([3e9, 2e9, 2.25e9, 2.5e9, 2.75e9])
        net = skrf.Network(frequency=freq, s=np.zeros((5, 1, 1)), z0=50.0)
        with pytest.raises(StrictMonotonicFreqError):
            validate_network_strict(net, source="bad_mono.s1p")

    def test_ulp_near_duplicate_freq(self):
        f0 = 2.0e9
        freq = skrf.Frequency(2.0, 3.0, 2, unit="Hz")
        freq.f[:] = np.array([f0, _advance_ulp(f0, 2)])
        net = skrf.Network(frequency=freq, s=np.zeros((2, 1, 1)), z0=50.0)
        with pytest.raises(StrictUlpNearDuplicateError):
            validate_network_strict(net, source="ulp.s1p")


# ── interchange strict 选通（缺省 False 逐位零变化证据） ─────────────────────


class TestInterchangeStrictGate:
    def test_strict_false_reads_bad_file_unchanged(self, tmp_path):
        """缺省路径零变化：非单调频文件 strict=False（含不传参）照常读取。"""
        p = _write_s1p(tmp_path / "bad_freq.s1p", ["2.0 0.5 0", "1.0 0.6 0"])
        net_default = read_touchstone(p)
        net_explicit = read_touchstone(p, strict=False)
        np.testing.assert_array_equal(net_default.f, [2e9, 1e9])
        np.testing.assert_array_equal(net_explicit.f, net_default.f)

    def test_strict_true_raises_typed_with_file_and_rule(self, tmp_path):
        p = _write_s1p(tmp_path / "bad_freq.s1p", ["2.0 0.5 0", "1.0 0.6 0"])
        with pytest.raises(StrictMonotonicFreqError) as ei:
            read_touchstone(p, strict=True)
        msg = str(ei.value)
        assert "bad_freq.s1p" in msg and "strictly_increasing_freq" in msg

    def test_strict_true_duplicate_freq(self, tmp_path):
        p = _write_s1p(tmp_path / "dup_freq.s1p", ["1.0 0.5 0", "1.0 0.6 0"])
        with pytest.raises(StrictMonotonicFreqError, match="重复频点"):
            read_touchstone(p, strict=True)

    def test_strict_true_ulp_shaped_file_loud_fail(self, tmp_path):
        """#287 形态文件（17 位有效数字下相邻 GHz 文本差 ~1 ulp）：strict 下
        必落频轴两规则之一响亮失败（文本→GHz→Hz 两次浮点缩放使 0/1 ulp 均
        可能，但绝不静默放行——这是本测试钉的行为）。"""
        next_text = format(math.nextafter(2.4, math.inf), ".17g")
        p = _write_s1p(tmp_path / "ulp.s1p", ["2.4 0.5 0", f"{next_text} 0.6 0"])
        with pytest.raises((StrictUlpNearDuplicateError, StrictMonotonicFreqError)):
            read_touchstone(p, strict=True)

    def test_strict_roundtrip_clean_file_passes(self, tmp_path):
        out = export_touchstone(_clean_network(), tmp_path / "clean.s3p")
        back_default = read_touchstone(out)
        back_strict = read_touchstone(out, strict=True)
        assert back_default.nports == 3
        np.testing.assert_array_equal(back_strict.f, back_default.f)
        np.testing.assert_allclose(back_strict.s, back_default.s)


# ── runs/ 证据区真机 sNp（找到即用，找不到如实 UNVERIFIED skip） ─────────────


class TestRealRunsTouchstone:
    def test_two_real_snp_pass_strict(self):
        runs_dir = _REPO / "runs"
        candidates = itertools.islice(
            runs_dir.glob("**/*.s?p"), 64) if runs_dir.is_dir() else iter(())
        passed: list[Path] = []
        last_error: str | None = None
        for candidate in candidates:
            if len(passed) >= 2:
                break
            try:
                read_touchstone(candidate, strict=True)
            except Exception as exc:  # 坏证据如实记录，不静默跳过
                last_error = f"{candidate}: {type(exc).__name__}: {exc}"
                continue
            passed.append(candidate)
        if len(passed) < 2:
            pytest.skip(
                "UNVERIFIED：runs/ 证据区可用真机 sNp 不足 2 件"
                f"（found={len(passed)}，last_error={last_error!r}）")
        assert all(p.suffix.startswith(".s") for p in passed)
