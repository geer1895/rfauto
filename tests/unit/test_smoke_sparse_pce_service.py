"""sparse_pce_service 冒烟门（aurora72 A5-C 测试盲区批量补冒烟席）。

盲区总账（A5-C triple-grep 复核，R8 盘点面 4 交叉映射勘误）：R8 报
"单引用 38 个"系过时/口径漂移登记——38 个被点名实现类
（rotman_lens/butler_matrix/premortem/dataset_quality/tma_array/sparse_array_cs
等）经 qualified 引用全量复核全部已有专属直测文件；全仓 232 个 service
模块中真盲区=零 qualified 引用 3 个：**sparse_pce_service、
vibration_srs_service（R8 已点名）+ lc_filter_service（R8 漏计）**。
三者的 src/scripts 侧亦无任何 CLI/MCP/api 消费者（孤儿模块），间接
覆盖不存在。本席以 3 个冒烟文件清零（见同批
test_smoke_lc_filter_service.py / test_smoke_vibration_srs_service.py）。

冒烟口径：单入口最小 dry-call（2 维均匀分布 + 线性交叉目标，seed 钉死
确定性）、ok=False 信封不抛、report 键 JSON 可序列化（model 键按
docstring 契约为进程内对象、不在 JSON 面内）。

未触达函数：无——唯一公开函数 sparse_pce_sobol_report 直测。
"""

from __future__ import annotations

import inspect
import json

from rfauto.service import sparse_pce_service as sps

_PARAM_SPECS = {
    "a": {"low": -1.0, "high": 1.0},
    "b": {"low": -1.0, "high": 1.0},
}


def _objective(p: dict[str, float]) -> float:
    return 1.0 + 2.0 * p["a"] + 3.0 * p["b"] + 0.5 * p["a"] * p["b"]


def test_public_api_surface():
    assert callable(sps.sparse_pce_sobol_report)
    assert inspect.isfunction(sps.sparse_pce_sobol_report)
    assert sps.sparse_pce_sobol_report.__doc__ and sps.sparse_pce_sobol_report.__doc__.strip()
    assert sps.SPARSE_PCE_SERVICE_SCHEMA_VERSION == "1.0"


def test_sparse_pce_sobol_report_minimal_dry_call():
    out = sps.sparse_pce_sobol_report(
        _PARAM_SPECS,
        _objective,
        degree_start=1,
        degree_max=2,
        n_samples=32,
        seed=42,
    )
    assert out["ok"] is True
    # 信封元数据面
    assert out["method"] == "sparse_pce_blatman_sudret"
    assert out["schema_version"] == "1.0"
    assert out["kucherenko_status"]  # 诚实边界标记透传
    # Sobol 解析面非空（逐参数 S1/ST 键，值域 [0,1]）
    sensitivity = out["sensitivity"]
    assert set(sensitivity.keys()) == {"a", "b"}
    for entry in sensitivity.values():
        assert {"S1", "ST"} <= set(entry)
        assert 0.0 <= entry["S1"] <= 1.0
        assert 0.0 <= entry["ST"] <= 1.0
    # report 键=JSON 面（model 键是进程内对象，docstring 契约排除）
    json.dumps(out["report"])


def test_constant_objective_ok_false_no_raise():
    out = sps.sparse_pce_sobol_report(
        _PARAM_SPECS,
        lambda p: 3.14,  # 常数目标 → 内核 ValueError → 信封如实拒绝
        n_samples=32,
        seed=42,
    )
    assert out["ok"] is False
    assert "ValueError" in out["error"]
    json.dumps(out)  # 失败信封同样 JSON 可序列化
