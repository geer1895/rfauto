"""DA-2 检索式元学习内核单测（研究扩充 round4 DA-2 判据）。

判据映射（任务书预声明）：
- 检索恒等式：同元特征查询 → 同 top-k 逐位（test_retrieval_identity_*）；
- 标准化口径恒等式：μ/σ 库内总体统计显式回显 + 对角马氏解析回收
  （test_standardization_*、test_standardized_metric_analytic_*，双路径
  #118：测试内独立公式离线复算，不调内核函数拼期望）；
- warm_start 形态往返：检索输出 warm_start_samples 喂既有
  optimization.warm_start.warm_start_points 门 → ok 且按 cost 升序/界外
  裁剪（test_warm_start_channel_*）；
- 空库/库 < k → 降级空先验字段不抛（test_empty_library_*、
  test_library_smaller_than_k）；
- 注入通道 smoke：合成历史库→检索→门→无异常（test_warm_start_channel_smoke）。

零随机零 IO（铁律 7/#144）：全部合成内存数据，不触真实 runs/。
"""

from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rfauto.core import meta_retrieval as mr
from rfauto.optimization.warm_start import warm_start_points
from rfauto.service import meta_retrieval_service as mrs

# ─── 合成库构造助手（确定性，无随机） ────────────────────────────────────────


def _entry(eid, family, dim, f0, bw, params, cost):
    return {
        "entry_id": eid,
        "params": params,
        "cost": cost,
        "meta": {"model": family, "dim": dim, "f0_ghz": f0, "bw_frac": bw},
    }


def _query(family="patch", dim=3, f0=10.0, bw=0.1):
    return {"model": family, "dim": dim, "f0_ghz": f0, "bw_frac": bw}


def _two_entry_library():
    """解析回收钉库：数值维只 log10_f0 变（0 ↔ 1），其余恒定。

    entry1: f0=1.0（log10=0）；entry2: f0=10.0（log10=1）；bw 同 0.1
    （log10=-1.0 逐位）；dim 同 3；族同 "patch"（one-hot 同位）。
    """
    return [
        _entry("e_low", "patch", 3, 1.0, 0.1, {"a_mm": 1.0}, 0.5),
        _entry("e_high", "patch", 3, 10.0, 0.1, {"a_mm": 2.0}, 0.2),
    ]


# ─── 1. 特征 schema（显式定义面） ────────────────────────────────────────────


def test_feature_schema_names_and_order():
    names = mr.meta_feature_names()
    assert names[:3] == ["dim", "log10_f0", "log10_bw"]
    onehot = names[3:]
    assert onehot == [f"family_{f}" for f in mr.TEMPLATE_FAMILY_VOCAB]
    assert len(names) == 3 + len(mr.TEMPLATE_FAMILY_VOCAB)
    # 词表快照含代表性族（显式冻结，漂移走全零桶不报错）
    for fam in ("patch", "wilkinson", "coupled_line", "hairpin_alt"):
        assert fam in mr.TEMPLATE_FAMILY_VOCAB


def test_build_meta_vector_values_bitwise():
    vec = mr.build_meta_vector(_query(family="wilkinson", dim=4, f0=2.5, bw=0.05))
    assert vec[0] == 4.0
    assert vec[1] == math.log10(2.5)
    assert vec[2] == math.log10(0.05)
    onehot = vec[3:]
    idx = mr.TEMPLATE_FAMILY_VOCAB.index("wilkinson")
    assert onehot[idx] == 1.0
    assert sum(onehot) == 1.0  # one-hot 严格单位化


def test_build_meta_vector_unknown_family_zero_bucket():
    vec = mr.build_meta_vector(_query(family="no_such_family"))
    assert sum(vec[3:]) == 0.0  # 未知族 → 全零桶，不报错不臆造列


def test_meta_vector_input_guards():
    for bad in (
        {"model": "patch", "dim": 3, "f0_ghz": 0.0, "bw_frac": 0.1},   # f0<=0
        {"model": "patch", "dim": 3, "f0_ghz": -1.0, "bw_frac": 0.1},
        {"model": "patch", "dim": 3, "f0_ghz": 2.0, "bw_frac": 0.0},   # bw<=0
        {"model": "patch", "dim": 3, "f0_ghz": 2.0, "bw_frac": 1.5},   # bw>1
        {"model": "patch", "dim": 3, "f0_ghz": float("nan"), "bw_frac": 0.1},
        {"model": "patch", "dim": 0, "f0_ghz": 2.0, "bw_frac": 0.1},   # dim<1
        {"model": "patch", "dim": True, "f0_ghz": 2.0, "bw_frac": 0.1},  # bool 拒收
        {"model": "patch", "dim": 3, "f0_ghz": True, "bw_frac": 0.1},
        {"model": "patch", "dim": "3", "f0_ghz": 2.0, "bw_frac": 0.1},  # 非整数
        "not a dict",
    ):
        with pytest.raises(ValueError):
            mr.build_meta_vector(bad)


# ─── 2. 检索恒等式（同元特征 → 同 top-k 逐位） ───────────────────────────────


def test_retrieval_identity_bitwise_and_pure():
    lib = _two_entry_library()
    lib_snapshot = copy.deepcopy(lib)
    q = _query()
    r1 = mr.retrieve_warm_start_prior(q, lib, k=2)
    r2 = mr.retrieve_warm_start_prior(dict(q), copy.deepcopy(lib), k=2)
    assert r1 == r2  # 逐位（dict 相等即全键全值浮点逐位）
    assert lib == lib_snapshot  # 纯函数：不修改入参库


def test_retrieval_orders_by_query_distance():
    lib = _two_entry_library()
    near_high = mr.retrieve_warm_start_prior(_query(f0=10.0), lib, k=2)
    assert [n["entry_id"] for n in near_high["neighbors"]] == ["e_high", "e_low"]
    near_low = mr.retrieve_warm_start_prior(_query(f0=1.0), lib, k=2)
    assert [n["entry_id"] for n in near_low["neighbors"]] == ["e_low", "e_high"]


def test_tie_breaks_by_library_index():
    # 三条目元特征全同 → 距离全同（=0）→ 严格按库序，k 截断取前两
    lib = [
        _entry("t0", "cpw", 2, 5.0, 0.2, {"w": 1.0}, 0.9),
        _entry("t1", "cpw", 2, 5.0, 0.2, {"w": 2.0}, 0.1),
        _entry("t2", "cpw", 2, 5.0, 0.2, {"w": 3.0}, 0.5),
    ]
    res = mr.retrieve_warm_start_prior(_query(family="cpw", dim=2, f0=5.0, bw=0.2), lib, k=2)
    assert [n["entry_id"] for n in res["neighbors"]] == ["t0", "t1"]
    assert all(n["distance"] == 0.0 and n["similarity"] == 1.0 for n in res["neighbors"])


# ─── 3. 距离口径：解析回收钉 + 标准化恒等式（#118 双路径） ────────────────────


def test_euclidean_metric_analytic_recycle():
    lib = _two_entry_library()
    res = mr.retrieve_warm_start_prior(_query(f0=10.0), lib, k=2, metric="euclidean")
    by_id = {n["entry_id"]: n for n in res["neighbors"]}
    # 查询 log10_f0=1.0；e_low 特征差 |0−1|=1 其余 0 → d=1.0；e_high d=0
    assert by_id["e_low"]["distance"] == 1.0
    assert by_id["e_high"]["distance"] == 0.0
    assert by_id["e_low"]["similarity"] == 0.5  # 1/(1+1) 逐位
    assert by_id["e_high"]["similarity"] == 1.0


def test_standardized_metric_analytic_recycle():
    lib = _two_entry_library()
    res = mr.retrieve_warm_start_prior(_query(f0=10.0), lib, k=2)
    by_id = {n["entry_id"]: n for n in res["neighbors"]}
    # 独立离线复算（#118 双路径，不调内核函数拼期望）：
    # log10_f0 列库内 [0.0, 1.0] → μ=0.5、σ=0.5（n=2 总体口径）
    # 查询 1.0：z=(1.0−0.5)/0.5=1.0；e_low z=(0.0−0.5)/0.5=−1.0 → 差²=4？否：
    # 对角马氏距离是"查询 vs 条目"的标准化坐标欧氏——两者 z 分别为 1 与 −1，
    # 坐标差 |1−(−1)|=2 → d_e_low=sqrt(4)=2.0；e_high z=1 → d=0。
    assert by_id["e_low"]["distance"] == 2.0
    assert by_id["e_high"]["distance"] == 0.0


def test_standardization_params_explicit_echo():
    lib = _two_entry_library()
    res = mr.retrieve_warm_start_prior(_query(), lib, k=1)
    std = res["standardization"]
    assert std is not None
    names = res["feature_names"]
    assert len(std["mean"]) == len(std["std"]) == len(names)
    i_f0 = names.index("log10_f0")
    assert std["mean"][i_f0] == 0.5  # (0+1)/2 逐位
    assert std["std"][i_f0] == 0.5  # sqrt((0.25+0.25)/2) 逐位
    i_bw = names.index("log10_bw")
    assert std["std"][i_bw] == 0.0  # 恒定列零方差守卫 → 显式 0.0
    # euclidean 口径不产标准化参数（该口径无标准化面）
    res_eu = mr.retrieve_warm_start_prior(_query(), lib, k=1, metric="euclidean")
    assert res_eu["standardization"] is None


def test_zero_variance_dim_query_off_mean_raw_fallback():
    # 库内 f0 恒 2.0（零方差），查询 f0=3.0 异值 → 该维未标准化差²（σ:=1）
    lib = [
        _entry("a", "mline", 1, 2.0, 0.05, {"w": 1.0}, 0.3),
        _entry("b", "mline", 1, 2.0, 0.20, {"w": 2.0}, 0.7),
    ]
    res = mr.retrieve_warm_start_prior(_query(family="mline", dim=1, f0=3.0, bw=0.1), lib, k=2)
    by_id = {n["entry_id"]: n for n in res["neighbors"]}
    # 独立复算：bw 列 σ=|log10(0.20)−log10(0.05)|/2，μ=两者均值；
    # f0 维零方差异值 → (log10(3)−log10(2))²；one-hot/dim 维全同贡献 0。
    a, b = math.log10(0.05), math.log10(0.20)
    mu = (a + b) / 2
    sigma = math.sqrt(((a - mu) ** 2 + (b - mu) ** 2) / 2)
    d_f0 = (math.log10(3.0) - math.log10(2.0)) ** 2
    d_a = math.sqrt(d_f0 + ((math.log10(0.1) - a) / sigma) ** 2)
    d_b = math.sqrt(d_f0 + ((math.log10(0.1) - b) / sigma) ** 2)
    assert by_id["a"]["distance"] == pytest.approx(d_a, rel=1e-12)
    assert by_id["b"]["distance"] == pytest.approx(d_b, rel=1e-12)


def test_onehot_distance_euclidean():
    # 数值维全同（查询与库逐值相等）→ 距离纯由 one-hot 差决定：
    # 同族 d=0，异族 d=sqrt(2)
    lib = [
        _entry("same", "patch", 3, 2.4, 0.05, {"x": 1.0}, 0.4),
        _entry("diff", "mline", 3, 2.4, 0.05, {"x": 2.0}, 0.6),
    ]
    res = mr.retrieve_warm_start_prior(_query(f0=2.4, bw=0.05), lib, k=2, metric="euclidean")
    by_id = {n["entry_id"]: n for n in res["neighbors"]}
    assert by_id["same"]["distance"] == 0.0
    assert by_id["diff"]["distance"] == math.sqrt(2.0)
    assert [n["entry_id"] for n in res["neighbors"]] == ["same", "diff"]


def test_similarity_score_identity():
    lib = [
        _entry(f"s{i}", fam, dim, f0, bw, {"p": float(i)}, 0.1 * i)
        for i, (fam, dim, f0, bw) in enumerate(
            [("patch", 3, 1.0, 0.02), ("wilkinson", 3, 2.5, 0.05),
             ("cpw", 2, 10.0, 0.5), ("mline", 1, 0.5, 0.9)]
        )
    ]
    res = mr.retrieve_warm_start_prior(_query(), lib, k=4)
    for n in res["neighbors"]:
        assert n["similarity"] == 1.0 / (1.0 + n["distance"])  # 逐位恒等式
        assert 0.0 < n["similarity"] <= 1.0


# ─── 4. 规模降级与条目清洗（不抛判据） ───────────────────────────────────────


def test_empty_library_degrades_no_raise():
    res = mr.retrieve_warm_start_prior(_query(), [], k=5)
    assert res["ok"] is True
    assert res["warm_start_samples"] == []
    assert res["neighbors"] == []
    assert res["k_effective"] == 0
    assert res["k_requested"] == 5
    assert res["n_library"] == 0
    assert res["standardization"] is None
    assert res["n_skipped_invalid"] == 0


def test_library_smaller_than_k():
    lib = _two_entry_library()
    res = mr.retrieve_warm_start_prior(_query(), lib, k=5)
    assert res["ok"] is True
    assert res["k_effective"] == 2  # 全返回，不抛不凑数
    assert len(res["neighbors"]) == len(res["warm_start_samples"]) == 2


def test_invalid_entries_skipped_with_stable_reasons():
    lib = [
        _entry("good", "patch", 3, 2.4, 0.1, {"a": 1.0}, 0.3),
        "not a dict",                                                     # 条目非对象
        {"params": {"a": 1.0}, "cost": 0.1, "meta": _query()},            # entry_id 缺失
        _entry("bad_params", "patch", 3, 2.4, 0.1, "not dict", 0.1),      # params 非对象
        {"entry_id": "no_cost", "params": {"a": 1.0}, "meta": _query()},  # cost 缺失
        _entry("nan_cost", "patch", 3, 2.4, 0.1, {"a": 1.0}, float("nan")),
        _entry("bad_meta", "patch", 3, 0.0, 0.1, {"a": 1.0}, 0.2),        # f0<=0
    ]
    res = mr.retrieve_warm_start_prior(_query(), lib, k=5)
    assert res["ok"] is True
    assert res["n_library"] == 7
    assert res["n_valid"] == 1
    assert res["n_skipped_invalid"] == 6
    assert [n["entry_id"] for n in res["neighbors"]] == ["good"]
    assert res["skip_reasons"] == {
        "条目非对象": 1, "entry_id 缺失": 1, "params 非对象": 1,
        "cost 缺失或非数值": 1, "cost 含 NaN/Inf": 1, "meta 非法": 1,
    }
    assert len(res["skip_examples"]) == 3  # 明细最多 3 条溯源样例
    # NaN cost 走 params 非对象之外独立类别（喂料合法性纵深防御不静默）


def test_dim_fallback_to_params_len():
    lib = [
        {"entry_id": "no_dim", "params": {"a": 1.0, "b": 2.0, "c": 3.0},
         "cost": 0.2, "meta": {"model": "patch", "f0_ghz": 2.4, "bw_frac": 0.05}},
    ]
    res = mr.retrieve_warm_start_prior(_query(dim=3, f0=2.4, bw=0.05), lib, k=1)
    assert res["ok"] is True
    assert res["neighbors"][0]["dim_source"] == "params_len"
    assert res["neighbors"][0]["distance"] == 0.0  # 回退 dim=3 与查询一致
    # 显式 dim 走 meta
    lib2 = [_entry("with_dim", "patch", 5, 2.4, 0.05, {"a": 1.0}, 0.1)]
    res2 = mr.retrieve_warm_start_prior(_query(dim=5, f0=2.4, bw=0.05), lib2, k=1)
    assert res2["neighbors"][0]["dim_source"] == "meta"


def test_query_and_k_metric_guards():
    lib = _two_entry_library()
    with pytest.raises(ValueError):
        mr.retrieve_warm_start_prior(_query(), lib, k=0)
    with pytest.raises(ValueError):
        mr.retrieve_warm_start_prior(_query(), lib, k=-1)
    with pytest.raises(ValueError):
        mr.retrieve_warm_start_prior(_query(), lib, k=True)  # bool 拒收
    with pytest.raises(ValueError):
        mr.retrieve_warm_start_prior(_query(), lib, metric="cosine")
    with pytest.raises(ValueError):
        mr.retrieve_warm_start_prior({"model": "patch"}, lib)  # 查询缺 f0/bw


# ─── 5. warm_start 通道形态往返 + 注入 smoke（既有通道只读调用） ──────────────


def test_warm_start_sample_form_alignment():
    lib = _two_entry_library()
    res = mr.retrieve_warm_start_prior(_query(), lib, k=2)
    for s in res["warm_start_samples"]:
        assert set(s.keys()) == {"params", "cost", "entry_id"}
        assert isinstance(s["params"], dict)
        assert isinstance(s["cost"], float)
    # 邻居序 = 样本序（通道按 cost 升序重排是门职责，检索保持相似度序）
    assert [s["entry_id"] for s in res["warm_start_samples"]] == [
        n["entry_id"] for n in res["neighbors"]
    ]


def test_warm_start_channel_roundtrip_gate():
    """检索样本直接喂既有门：ok、cost 升序、界外裁剪（形态往返判据）。"""
    lib = [
        _entry("w0", "patch", 3, 2.4, 0.05, {"len_mm": 30.0, "w_mm": 2.0}, 0.9),
        _entry("w1", "patch", 3, 2.4, 0.05, {"len_mm": 36.0, "w_mm": 1.5}, 0.1),
        _entry("w2", "patch", 3, 2.4, 0.05, {"len_mm": 99.0, "w_mm": 1.8}, 0.5),  # 越界
    ]
    res = mr.retrieve_warm_start_prior(_query(f0=2.4), lib, k=3)
    bounds = {"len_mm": {"low": 20.0, "high": 40.0}, "w_mm": {"low": 0.5, "high": 3.0}}
    gate = warm_start_points(res["warm_start_samples"], bounds=bounds, top_n=2)
    assert gate["ok"] is True
    assert gate["n_candidates"] == 3
    costs = [p["cost"] for p in gate["points"]]
    assert costs == sorted(costs)  # 门按 cost 升序
    assert costs[0] == 0.1
    assert set(gate["points"][0]["params"].keys()) == {"len_mm", "w_mm"}  # 形态保持
    # w2 的 len_mm=99 被门裁剪到界内（若入选）；top_n=2 只取 cost 最小两个
    assert all(20.0 <= p["params"]["len_mm"] <= 40.0 for p in gate["points"])


def test_warm_start_channel_smoke_via_service():
    """注入通道 smoke：合成库→service 检索→service 门→无异常全链。"""
    lib = [
        _entry(f"sm{i}", "branchline", 3, 2.4, 0.03 + 0.01 * i,
               {"arm_len_mm": 18.0 + i, "series_w_mm": 1.8, "shunt_w_mm": 1.1},
               0.8 - 0.1 * i)
        for i in range(6)
    ]
    got = mrs.retrieve_meta_warm_start(_query(family="branchline", f0=2.4, bw=0.05), lib, k=4)
    assert got["ok"] is True
    assert got["k_effective"] == 4
    gate = mrs.gate_meta_warm_start(
        got["warm_start_samples"],
        {"arm_len_mm": {"low": 10.0, "high": 30.0},
         "series_w_mm": {"low": 0.5, "high": 3.0},
         "shunt_w_mm": {"low": 0.5, "high": 3.0}},
        top_n=3,
    )
    assert gate["ok"] is True
    assert 1 <= len(gate["points"]) <= 3


# ─── 6. service 薄壳信封 ─────────────────────────────────────────────────────


def test_service_envelope_passthrough_and_error():
    lib = _two_entry_library()
    got = mrs.retrieve_meta_warm_start(_query(), lib, k=2, metric="euclidean")
    kernel = mr.retrieve_warm_start_prior(_query(), lib, k=2, metric="euclidean")
    assert got == kernel  # 合法路径原样透传内核结果
    bad = mrs.retrieve_meta_warm_start({"model": "patch"}, lib, k=2)  # 查询缺 f0/bw
    assert bad["ok"] is False
    assert isinstance(bad["errors"], list) and bad["errors"]
    bad_metric = mrs.retrieve_meta_warm_start(_query(), lib, metric="cosine")
    assert bad_metric["ok"] is False
    bad_k = mrs.retrieve_meta_warm_start(_query(), lib, k=0)
    assert bad_k["ok"] is False


def test_service_gate_passthrough_insufficient():
    # 门拒绝语义如实透传（异族参数空间 → insufficient_similarity，不凑数）
    samples = [{"params": {"other_key": 1.0}, "cost": 0.1, "entry_id": "x"}]
    bounds = {"len_mm": {"low": 0.0, "high": 10.0}}
    gate = mrs.gate_meta_warm_start(samples, bounds)
    assert gate["ok"] is False
    assert gate["reason"] == "insufficient_similarity"


def test_result_json_serializable():
    lib = _two_entry_library()
    res = mr.retrieve_warm_start_prior(_query(), lib, k=2)
    text = json.dumps(res, ensure_ascii=False)
    assert "warm_start_samples" in text
    back = json.loads(text)
    assert back == res
