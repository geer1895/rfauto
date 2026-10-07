"""numeric_env 消费钩子钉（round3 附带件之二收尾：内核+钉已备，本件接线）。

消费面（E 类台账 plan_gap_e_tail_20260929 §三.2 残余池销账）：
- ``infra/run_store.collect_provenance`` 增 ``numeric_env`` 键（best-effort
  #105：探测失败如实 available=False，不阻塞业务主路径）；
- ``write_meta`` 覆盖语义不变（meta_dict 同名键优先，docstring 契约）；
- ``infra/dag_cache.env_fingerprint`` 键成分**不受影响**（缓存键面回归钉：
  numeric_env 不得进缓存键，否则线程环境变量一变缓存全失效）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rfauto.infra.dag_cache import env_fingerprint
from rfauto.infra.numeric_env import numeric_env_fingerprint
from rfauto.infra.run_store import collect_provenance, write_meta


class TestNumericEnvHook:
    def test_collect_provenance_has_numeric_env(self):
        p = collect_provenance()
        assert "numeric_env" in p
        fp = p["numeric_env"]
        assert isinstance(fp, dict)
        # venv 内 numpy 在装 → available True（内核钉语义）
        assert fp["available"] is True
        assert fp["numpy_version"]
        assert set(fp["threads"]) == {"OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS",
                                      "MKL_NUM_THREADS"}

    def test_threads_reflect_process_env(self, monkeypatch):
        monkeypatch.setenv("OPENBLAS_NUM_THREADS", "3")
        fp = numeric_env_fingerprint()
        assert fp["threads"]["OPENBLAS_NUM_THREADS"] == "3"
        # 经 collect_provenance 透传一致（同一进程 env 面）
        assert collect_provenance()["numeric_env"]["threads"][
            "OPENBLAS_NUM_THREADS"
        ] == "3"

    def test_write_meta_numeric_env_json_safe(self, tmp_path: Path):
        run_dir = tmp_path / "run_hook"
        write_meta(run_dir, run_id="hook_001")
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["numeric_env"]["available"] is True
        assert isinstance(meta["numeric_env"]["cpu_count"], int)

    def test_meta_dict_overrides_numeric_env(self, tmp_path: Path):
        run_dir = tmp_path / "run_override"
        override = {"numeric_env": {"available": False, "reason": "custom"}}
        write_meta(run_dir, override, run_id="hook_002")
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        assert meta["numeric_env"] == {"available": False, "reason": "custom"}

    def test_env_fingerprint_keys_unaffected(self):
        # 缓存键面回归钉：numeric_env 不进 env_fingerprint 键成分，
        # 否则线程环境变量一变 dag/结果缓存全失效
        fp = env_fingerprint()
        assert set(fp) == {"git_sha", "pip_freeze_sha", "uv_lock_sha256"}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
