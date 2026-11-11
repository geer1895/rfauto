"""AX-4（aurora_r R-03）服务器工具链 lock 离线钉。

判据对照（席位任务书预声明验收面）：
1. 采集器 probe_toolchain：固定工具键序（lock 形态稳定）、每行 version
   str、单工具探测失败降级 unknown 永不 raise（#105）、零敏感信息
   （序列化面无盘符路径——configs/*.local.yaml 无 gitignore 通配的如实
   对策）。
2. build_toolchain_lock：时间戳/生成器版本注入后确定性（纯函数判据）；
   键形归一（非 dict probe → 空采集、tools 行非 dict 降级、值 str 化）。
3. 比对器 compare_toolchain_lock 纯函数：正例 match / 漂移例 drift /
   缺字段 unknown 例 unverifiable / 非法输入不炸；输入零变异；
   drift 优先于 unverifiable（规则 0 拦截面不被 unknown 稀释）。
4. service 信封入口（JSON 进出规则 4）：toolchain_lock_write 写盘回读；
   toolchain_lock_check 三态（lock 缺失 skipped / 读取失败 error /
   比对成功 ok）+ caller 探测注入（远程 probe 流程调用形态）。
5. 脚本薄壳 scripts/toolchain_lock.py：写模式 + --check 退出码契约
   （match=0/drift=1/unverifiable=2/lock 缺失=3）。

chdir 隔离零污染（#144 家族）；探测通道 monkeypatch 钉住（#139），
零网络依赖零真机。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from rfauto.service import toolchain_service as tcs
from rfauto.service.toolchain_service import (
    _PROBED_PACKAGES,
    _TOOL_ORDER,
    DEFAULT_LOCK_PATH,
    TOOLCHAIN_LOCK_SCHEMA_VERSION,
    build_toolchain_lock,
    compare_toolchain_lock,
    probe_toolchain,
    toolchain_lock_check,
    toolchain_lock_write,
)

_SCRIPT = (Path(__file__).resolve().parents[2] / "scripts"
           / "toolchain_lock.py")

_SYNTHETIC_PROBE = {
    "tools": {
        "hfss": {"version": "2025.1", "version_probe": "auto-probe"},
        "ads": {"version": "2027", "version_probe": "hpeesof_dir"},
        "openems": {"version": "0.6.2", "version_probe": "importlib.metadata"},
        "python": {"version": "3.12.0", "version_probe": "sys.version_info"},
    },
    "packages": {"numpy": "2.0.0", "scipy": "1.14.0"},
}


# ---------------------------------------------------------------------------
# 1. probe_toolchain 采集器
# ---------------------------------------------------------------------------


class TestProbeToolchain:
    def test_fixed_tool_keys_in_order(self):
        out = probe_toolchain(include_packages=False)
        assert tuple(out["tools"]) == _TOOL_ORDER
        assert "packages" not in out

    def test_rows_are_strings_and_packages_present(self):
        out = probe_toolchain()
        for name in _TOOL_ORDER:
            row = out["tools"][name]
            assert isinstance(row["version"], str) and row["version"]
        assert set(out["packages"]) == set(_PROBED_PACKAGES)
        assert all(isinstance(v, str) and v
                   for v in out["packages"].values())

    def test_single_tool_failure_degrades_unknown(self, monkeypatch):
        """#105：单工具探测异常只降级该行，不炸整次采集（行级兜底）。"""
        def _boom():
            raise RuntimeError("probe down")

        monkeypatch.setattr(tcs, "_probe_hfss_row", _boom)
        out = probe_toolchain()
        assert out["tools"]["hfss"]["version"] == "unknown"
        assert "probe_error" in out["tools"]["hfss"]["version_probe"]
        assert out["tools"]["ads"]["version"]  # 其余行照常

    def test_no_sensitive_paths_in_serialized_lock(self, tmp_path,
                                                   monkeypatch):
        """零敏感信息守卫：lock 序列化面无盘符/反斜杠路径（gitignore 无
        *.local.yaml 通配的如实对策——模块 docstring 申报）。"""
        monkeypatch.chdir(tmp_path)
        env = toolchain_lock_write()
        assert env["ok"] is True, env.get("errors")
        text = Path(env["path"]).read_text(encoding="utf-8")
        assert ":\\" not in text and "/home/" not in text
        assert "E:" not in text and "C:" not in text


# ---------------------------------------------------------------------------
# 2. build_toolchain_lock 规范化
# ---------------------------------------------------------------------------


class TestBuildToolchainLock:
    def test_deterministic_with_injected_stamp(self):
        lock1 = build_toolchain_lock(_SYNTHETIC_PROBE,
                                     generated_at="2026-11-10T00:00:00+00:00",
                                     generator_version="9.9.9")
        lock2 = build_toolchain_lock(_SYNTHETIC_PROBE,
                                     generated_at="2026-11-10T00:00:00+00:00",
                                     generator_version="9.9.9")
        assert lock1 == lock2
        assert lock1["schema_version"] == TOOLCHAIN_LOCK_SCHEMA_VERSION
        assert lock1["generator"] == "rfauto/toolchain_lock"
        assert lock1["generator_version"] == "9.9.9"
        assert lock1["generated_at"] == "2026-11-10T00:00:00+00:00"
        assert lock1["tools"] == _SYNTHETIC_PROBE["tools"]

    def test_default_stamp_fields_present(self):
        lock = build_toolchain_lock({})
        assert lock["generated_at"]  # ISO 时间戳
        assert lock["generator_version"]  # rfauto __version__ 注入

    def test_garbage_probe_normalizes_to_empty(self):
        lock = build_toolchain_lock("junk")
        assert lock["tools"] == {}
        assert lock["packages"] == {}

    def test_row_shapes_normalized(self):
        lock = build_toolchain_lock({
            "tools": {"hfss": "2025.1",  # 非 dict 行降级
                      "ads": {"version": None},  # None 版本 → unknown
                      42: {"version": "x"}},  # 非 str 键 str() 化
            "packages": {"numpy": 2},  # 值 str 化
        })
        assert lock["tools"]["hfss"] == {"version": "2025.1"}
        assert lock["tools"]["ads"] == {"version": "unknown"}
        assert lock["tools"]["42"] == {"version": "x"}
        assert lock["packages"]["numpy"] == "2"

    def test_lock_has_no_tools_beyond_probe(self):
        lock = build_toolchain_lock(_SYNTHETIC_PROBE)
        assert set(lock) == {"schema_version", "generated_at", "generator",
                             "generator_version", "tools", "packages"}


# ---------------------------------------------------------------------------
# 3. compare_toolchain_lock 比对器（纯函数）
# ---------------------------------------------------------------------------


class TestCompareToolchainLock:
    def _lock(self):
        return build_toolchain_lock(_SYNTHETIC_PROBE,
                                    generated_at="2026-11-10T00:00:00+00:00",
                                    generator_version="9.9.9")

    def test_match_positive(self):
        out = compare_toolchain_lock(self._lock(), _SYNTHETIC_PROBE)
        assert out["verdict"] == "match"
        assert out["drift"] == [] and out["unverifiable"] == []
        assert out["match_count"] == len(out["items"])

    def test_drift_detected_item_by_item(self):
        """漂移=服务器版本≠本机（规则 0 拦截核心例）。"""
        probed = json.loads(json.dumps(_SYNTHETIC_PROBE))
        probed["tools"]["hfss"]["version"] = "2024.2"
        probed["packages"]["numpy"] = "1.26.0"
        out = compare_toolchain_lock(self._lock(), probed)
        assert out["verdict"] == "drift"
        drift_pairs = {(it["kind"], it["name"]) for it in out["drift"]}
        assert drift_pairs == {("tool", "hfss"), ("package", "numpy")}
        hfss = next(it for it in out["drift"] if it["name"] == "hfss")
        assert hfss["lock"] == "2025.1" and hfss["probe"] == "2024.2"

    def test_unknown_side_unverifiable_not_fabricated(self):
        probed = json.loads(json.dumps(_SYNTHETIC_PROBE))
        probed["tools"]["ads"]["version"] = "unknown"
        out = compare_toolchain_lock(self._lock(), probed)
        assert out["verdict"] == "unverifiable"
        assert [it["name"] for it in out["unverifiable"]] == ["ads"]

    def test_missing_and_extra_keys_unverifiable(self):
        """lock 缺项/probe 多项均如实 unverifiable（多报不放过 #316）。"""
        out = compare_toolchain_lock(self._lock(), {"tools": {}})
        assert out["verdict"] == "unverifiable"
        assert len(out["unverifiable"]) == len(out["items"])

        probed = json.loads(json.dumps(_SYNTHETIC_PROBE))
        probed["tools"]["comsol"] = {"version": "6.3"}
        out2 = compare_toolchain_lock(self._lock(), probed)
        comsol = next(it for it in out2["items"] if it["name"] == "comsol")
        assert comsol["status"] == "unverifiable"
        assert comsol["lock"] == "unknown" and comsol["probe"] == "6.3"

    def test_drift_wins_over_unverifiable(self):
        probed = json.loads(json.dumps(_SYNTHETIC_PROBE))
        probed["tools"]["ads"]["version"] = "unknown"
        probed["tools"]["hfss"]["version"] = "2024.2"
        out = compare_toolchain_lock(self._lock(), probed)
        assert out["verdict"] == "drift"

    def test_garbage_inputs_never_raise(self):
        for lock, probe in ((None, None), ("junk", 42), ({}, []),
                            (self._lock(), None)):
            out = compare_toolchain_lock(lock, probe)  # type: ignore[arg-type]
            assert out["verdict"] in ("match", "drift", "unverifiable")

    def test_pure_function_no_input_mutation(self):
        lock = self._lock()
        probe = json.loads(json.dumps(_SYNTHETIC_PROBE))
        lock_snap = json.dumps(lock, sort_keys=True)
        probe_snap = json.dumps(probe, sort_keys=True)
        compare_toolchain_lock(lock, probe)
        assert json.dumps(lock, sort_keys=True) == lock_snap
        assert json.dumps(probe, sort_keys=True) == probe_snap


# ---------------------------------------------------------------------------
# 4. service 信封入口
# ---------------------------------------------------------------------------


class TestServiceEnvelopeEntries:
    def test_write_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(tcs, "probe_toolchain",
                            lambda **kw: json.loads(
                                json.dumps(_SYNTHETIC_PROBE)))
        env = toolchain_lock_write()
        assert env["ok"] is True, env.get("errors")
        assert env["schema_version"] == TOOLCHAIN_LOCK_SCHEMA_VERSION
        loaded = yaml.safe_load(Path(env["path"]).read_text(encoding="utf-8"))
        assert loaded["tools"] == _SYNTHETIC_PROBE["tools"]
        assert loaded["packages"] == _SYNTHETIC_PROBE["packages"]
        assert loaded["generated_at"] == env["generated_at"]
        # 缺省落点=cwd 相对 configs/（#144 家族：测试 chdir 隔离）
        assert Path(env["path"]) == DEFAULT_LOCK_PATH
        assert (tmp_path / env["path"]).exists()

    def test_write_explicit_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tcs, "probe_toolchain",
                            lambda **kw: json.loads(
                                json.dumps(_SYNTHETIC_PROBE)))
        env = toolchain_lock_write(tmp_path / "sub" / "lock.yaml")
        assert env["ok"] is True
        assert (tmp_path / "sub" / "lock.yaml").exists()

    def test_check_lock_missing_skipped(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        env = toolchain_lock_check(_SYNTHETIC_PROBE)
        assert env["ok"] is True and env["skipped"] is True
        assert env["verdict"] == "SKIP"

    def test_check_drift_with_caller_probed(self, tmp_path, monkeypatch):
        """远程 probe 流程调用形态：服务器侧探测 dict 作 probed 注入。"""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(tcs, "probe_toolchain",
                            lambda **kw: json.loads(
                                json.dumps(_SYNTHETIC_PROBE)))
        assert toolchain_lock_write()["ok"] is True
        drifted = json.loads(json.dumps(_SYNTHETIC_PROBE))
        drifted["tools"]["openems"]["version"] = "0.7.0"
        env = toolchain_lock_check(drifted)
        assert env["ok"] is True
        assert env["verdict"] == "drift"
        assert env["probed_source"] == "caller"
        assert env["drift"][0]["name"] == "openems"

    def test_check_local_probe_match(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(tcs, "probe_toolchain",
                            lambda **kw: json.loads(
                                json.dumps(_SYNTHETIC_PROBE)))
        assert toolchain_lock_write()["ok"] is True
        env = toolchain_lock_check()  # probed=None → 本机自探
        assert env["ok"] is True
        assert env["verdict"] == "match"
        assert env["probed_source"] == "local_probe"

    def test_check_corrupt_lock_error_envelope(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        target = tmp_path / DEFAULT_LOCK_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{{{not yaml", encoding="utf-8")
        env = toolchain_lock_check(_SYNTHETIC_PROBE)
        assert env["ok"] is False
        assert env["errors"] and "lock 文件读取失败" in env["errors"][0]


# ---------------------------------------------------------------------------
# 5. 脚本薄壳退出码契约
# ---------------------------------------------------------------------------


class TestScriptExitCodes:
    def _run(self, *args: str, cwd: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_SCRIPT), *args],
            capture_output=True, text=True, encoding="utf-8", cwd=str(cwd),
            timeout=120)

    def test_write_then_check_match_exit_0(self, tmp_path):
        monkeypatch_free_cwd = tmp_path / "wt"
        monkeypatch_free_cwd.mkdir()
        r = self._run(cwd=monkeypatch_free_cwd)
        assert r.returncode == 0, r.stderr
        assert (monkeypatch_free_cwd / DEFAULT_LOCK_PATH).exists()
        # 干净检出（无机器配置/工具缺装）时写入探测面含 unknown → check 恒
        # unverifiable（exit 2=未知项如实上报，不冒充 match）；满配环境钉
        # 全 match 契约。分支判据取写入载荷本身（零额外探测依赖）。
        written = json.loads(r.stdout)
        clean_checkout = any(
            t.get("version") in (None, "unknown")
            for t in written.get("tools", {}).values())
        r2 = self._run("--check", cwd=monkeypatch_free_cwd)
        payload = json.loads(r2.stdout)
        if clean_checkout:
            assert r2.returncode == 2, r2.stderr
            assert payload["verdict"] == "unverifiable"
        else:
            assert r2.returncode == 0, r2.stderr
            assert payload["verdict"] == "match"
        assert payload["probed_source"] == "local_probe"

    def test_check_drift_exit_1(self, tmp_path):
        cwd = tmp_path / "wt"
        cwd.mkdir()
        assert self._run(cwd=cwd).returncode == 0
        lock_path = cwd / DEFAULT_LOCK_PATH
        lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
        lock["tools"]["python"]["version"] = "9.9.9-drift"
        lock_path.write_text(
            yaml.safe_dump(lock, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
        r = self._run("--check", cwd=cwd)
        assert r.returncode == 1, r.stdout
        payload = json.loads(r.stdout)
        assert payload["verdict"] == "drift"
        assert payload["drift"][0]["name"] == "python"

    def test_check_without_lock_exit_3(self, tmp_path):
        r = self._run("--check", cwd=tmp_path)
        assert r.returncode == 3, r.stdout
        payload = json.loads(r.stdout)
        assert payload["skipped"] is True and payload["verdict"] == "SKIP"
