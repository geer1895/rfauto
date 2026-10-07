"""数值环境指纹钉（round3 附带三件之二；infra/numeric_env.py）。

契约：JSON 安全、best-effort 永不 raise（#105）、numpy<2 降级面如实。
"""

from __future__ import annotations

import builtins
import json
import sys
import types

from rfauto.infra.numeric_env import THREAD_ENV_KEYS, numeric_env_fingerprint


class TestNumericEnvFingerprint:
    def test_available_and_machine_readable(self):
        fp = numeric_env_fingerprint()
        assert fp["available"] is True
        assert fp["reason"] is None
        assert isinstance(fp["numpy_version"], str) and fp["numpy_version"]
        # venv numpy>=2.4 实测机读 CONFIG 在装——BLAS backend 名非空
        assert isinstance(fp["blas"], str) and fp["blas"]
        assert isinstance(fp["numpy_config"], dict)
        assert fp["cpu_count"] is None or fp["cpu_count"] > 0
        json.dumps(fp)  # JSON 安全契约

    def test_threads_keys_covered_and_injectable(self):
        env = {k: "1" for k in THREAD_ENV_KEYS}
        env["EXTRA"] = "ignore-me"
        fp = numeric_env_fingerprint(env=env)
        assert fp["threads"] == {k: "1" for k in THREAD_ENV_KEYS}
        assert "EXTRA" not in fp["threads"]

    def test_default_env_reads_process(self, monkeypatch):
        monkeypatch.setenv("OPENBLAS_NUM_THREADS", "7")
        fp = numeric_env_fingerprint()
        assert fp["threads"]["OPENBLAS_NUM_THREADS"] == "7"

    def test_numpy_missing_degrades_best_effort(self, monkeypatch):
        # numpy import 失败 → available=False + reason，绝不 raise（#105）
        real_import = __import__

        def fake_import(name, *args, **kwargs):
            if name == "numpy":
                raise ImportError("no numpy in this fantasy env")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        fp = numeric_env_fingerprint()
        assert fp["available"] is False
        assert fp["reason"] is not None and "ImportError" in fp["reason"]
        json.dumps(fp)

    def test_numpy1_no_config_still_available(self, monkeypatch):
        # numpy<2：无机读 CONFIG → available 仍 True、numpy_config=None（版本面如实）
        fake_mod = types.ModuleType("numpy.__config__")  # 故意无 CONFIG 属性
        monkeypatch.setitem(sys.modules, "numpy.__config__", fake_mod)
        fp = numeric_env_fingerprint()
        assert fp["available"] is True
        assert fp["numpy_config"] is None
        assert fp["numpy_version"]
