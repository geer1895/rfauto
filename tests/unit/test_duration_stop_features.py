"""时长预测 NrTS/stop_reason 停机机制特征 单元测试。

钉死四条语义（全部合成样本，零 runs/ 依赖、零网络、零仿真）：

1. 特征提取——``DurationSample.feature`` 解析 v2 派生名（``DURATION_FEATURES_V2``）：
   ``nrts_limit`` 未申报 -> 中性 1.0；交互项 ``nrts_capped_steps`` 只在
   nrts_cap 档激活（时长 ~ nrts_limit·dt 而非能量机制）；``stop_*`` 互斥
   one-hot（命中档 e / 其余 1.0）；旧样本（缺新字段）全中性零移位；
2. 预测走通——3 合成样本 log-linear 拟合 v2 特征子集 + 预测逐位复原声明律，
   同 cap 下 nrts_cap 档 ~exp(2) 倍能量档（机制可分）；
3. 同构装载——duration_sample.json 同构 schema（``hit_nr_ts_cap`` 三值 ->
   stop_reason 枚举）映射正确、旧样本缺字段向后兼容、坏条目 best-effort
   skip（#105）；
4. 序列化兼容——to_json/from_json 携带新字段重拟合逐位一致；旧 payload 缺
   新键按缺省装载、预测不变（version 保持 1，additive 双向兼容）。

模型重训不在本任务（干净集 n=4 样本少）：特征就绪，样本 >=6 后重训评估 LOO。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from rfauto.pipeline.duration_calibration import load_duration_sample_json
from rfauto.pipeline.quota_guard import (
    DURATION_FEATURES,
    DURATION_FEATURES_V2,
    STOP_ONEHOT_LEVEL,
    DurationPredictor,
    DurationSample,
    OffsetPowerDurationPredictor,
    RobustDurationPredictor,
    TieredDurationPredictor,
)

# --------------------------------------------------------------------------- #
# 1) 特征提取：one-hot / 交互项 / 旧样本中性缺省
# --------------------------------------------------------------------------- #

def test_v2_feature_extraction_hit_miss_and_legacy() -> None:
    capped = DurationSample(
        mesh_mm=0.3, solve_s=1781.6, nrts_limit=100000, stop_reason="nrts_cap",
        source="synthetic/capped",
    )
    energy = DurationSample(
        mesh_mm=0.3, solve_s=1781.6, nrts_limit=100000, stop_reason="energy",
    )
    timeout = DurationSample(mesh_mm=0.3, solve_s=1.0, stop_reason="timeout")
    legacy = DurationSample(mesh_mm=0.4, solve_s=900.0)  # 旧样本：缺新字段

    # 交互项只在 nrts_cap 档激活，量值 = 声明步数上限
    assert capped.feature("nrts_capped_steps") == 100000.0
    assert energy.feature("nrts_capped_steps") == 1.0
    assert timeout.feature("nrts_capped_steps") == 1.0
    assert legacy.feature("nrts_capped_steps") == 1.0
    # nrts_limit 特征：声明值直传；未申报（0）-> 中性 1.0
    assert capped.feature("nrts_limit") == 100000.0
    assert legacy.feature("nrts_limit") == 1.0
    # one-hot：命中档 e（log e = 1），其余与未申报档全 1.0（零移位）
    for name, sample, expected in (
        ("stop_energy", energy, STOP_ONEHOT_LEVEL),
        ("stop_nrts_cap", capped, STOP_ONEHOT_LEVEL),
        ("stop_timeout", timeout, STOP_ONEHOT_LEVEL),
    ):
        assert sample.feature(name) == pytest.approx(expected)
        others = [n for n in ("stop_energy", "stop_nrts_cap", "stop_timeout")
                  if n != name]
        assert all(sample.feature(n) == 1.0 for n in others)
    assert all(legacy.feature(n) == 1.0
               for n in ("stop_energy", "stop_nrts_cap", "stop_timeout"))
    # stop_reason 大小写/空白宽容归一（归档脏数据不炸、不错档）
    messy = DurationSample(mesh_mm=0.3, solve_s=1.0, stop_reason=" NRTS_CAP ")
    assert messy.feature("stop_nrts_cap") == pytest.approx(STOP_ONEHOT_LEVEL)
    # 未识别枚举值按未申报处理（one-hot 全中性），不抛错（#105）
    weird = DurationSample(mesh_mm=0.3, solve_s=1.0, stop_reason="crashed")
    assert all(weird.feature(n) == 1.0 for n in DURATION_FEATURES_V2)


def test_capped_sample_without_declared_limit_raises() -> None:
    """触顶样本缺声明上限 = 内部矛盾，特征化必须响（不静默猜值）。"""
    bad = DurationSample(mesh_mm=0.3, solve_s=1.0, stop_reason="nrts_cap")
    with pytest.raises(ValueError, match="nrts_limit"):
        bad.feature("nrts_capped_steps")
    # 其余 v2 名不触发该守卫
    assert bad.feature("stop_nrts_cap") == pytest.approx(STOP_ONEHOT_LEVEL)


def test_v1_feature_resolution_unchanged() -> None:
    legacy = DurationSample(mesh_mm=0.4, solve_s=900.0)
    assert legacy.feature("mesh_mm") == 0.4
    with pytest.raises(KeyError, match="unknown duration feature"):
        legacy.feature("not_a_feature")
    with pytest.raises(ValueError, match="positive and finite"):
        DurationSample(mesh_mm=0.0, solve_s=1.0).feature("mesh_mm")


# --------------------------------------------------------------------------- #
# 2) v1 模型对新字段不敏感（零翻转钉）+ 3 样本 v2 拟合/预测走通
# --------------------------------------------------------------------------- #

def _v1_law_samples(n: int = 5) -> list[DurationSample]:
    """精确 offset+power 律 t = 20 + 5·mesh^-3.5 的合成标定样本。"""
    meshes = [0.6, 0.5, 0.4, 0.3, 0.25][:n]
    return [
        DurationSample(
            mesh_mm=m, solve_s=20.0 + 5.0 * m ** (-3.5),
            domain_volume_mm3=1000.0, n_excitations=1,
        )
        for m in meshes
    ]


def test_v1_model_predictions_ignore_new_fields() -> None:
    base = dict(mesh_mm=0.45, domain_volume_mm3=1000.0, n_excitations=1)
    legacy = DurationSample(**base)
    stamped = DurationSample(**base, nrts_limit=100000, stop_reason="nrts_cap")
    robust = RobustDurationPredictor.fit(_v1_law_samples())
    assert robust.predict(legacy).predicted_s == pytest.approx(
        robust.predict(stamped).predicted_s, rel=1e-12
    )
    offset_power = OffsetPowerDurationPredictor.fit(_v1_law_samples())
    assert offset_power.predict_s(legacy) == pytest.approx(
        offset_power.predict_s(stamped), rel=1e-12
    )
    loglinear = DurationPredictor.fit(_v1_law_samples(), DURATION_FEATURES)
    assert loglinear.predict_s(legacy) == pytest.approx(
        loglinear.predict_s(stamped), rel=1e-12
    )


def test_loglinear_fit_predict_walkthrough_with_stop_features() -> None:
    """3 合成样本、v2 特征子集 (nrts_limit, stop_nrts_cap) 的端到端走通。

    声明律 log t = 4 + 0.5·log(nrts_limit) + 2·log(stop_nrts_cap)：3 样本
    恰可定 3 参数，拟合应逐位复原；同 cap 查询下 nrts_cap 档 = exp(2) 倍
    能量档（停机机制可分——ratrace 混池问题的特征面解药）。
    """

    def law(nrts_feat: float, stop_feat: float) -> float:
        return math.exp(4.0) * nrts_feat**0.5 * stop_feat**2.0

    samples = [
        DurationSample(mesh_mm=0.3, solve_s=law(1.0, 1.0)),  # 旧样本：全中性
        DurationSample(  # 能量停机：步数 < 上限，nrts_limit 只是声明上限
            mesh_mm=0.3, solve_s=law(200000.0, 1.0),
            nrts_limit=200000, stop_reason="energy",
        ),
        DurationSample(  # 触顶停机：步数 = 上限，类移位 exp(2)
            mesh_mm=0.3, solve_s=law(100000.0, STOP_ONEHOT_LEVEL),
            nrts_limit=100000, stop_reason="nrts_cap",
        ),
    ]
    features = ("nrts_limit", "stop_nrts_cap")
    predictor = DurationPredictor.fit(samples, features)
    # 系数逐位复原声明律（c0=4, c1=0.5, c2=2）
    assert predictor.coefficients == pytest.approx([4.0, 0.5, 2.0], rel=1e-9)
    # 预测走通：同 cap 不同停机机制 -> exp(2) 倍分离
    query_capped = predictor.predict_s(
        mesh_mm=0.3, nrts_limit=250000, stop_reason="nrts_cap")
    query_energy = predictor.predict_s(
        mesh_mm=0.3, nrts_limit=250000, stop_reason="energy")
    expected_common = math.exp(4.0) * 250000.0**0.5
    assert query_capped == pytest.approx(expected_common * math.exp(2.0), rel=1e-9)
    assert query_energy == pytest.approx(expected_common, rel=1e-9)
    assert query_capped / query_energy == pytest.approx(math.exp(2.0), rel=1e-9)
    # 旧样本形态查询（未申报）落在中性基线
    assert predictor.predict_s(mesh_mm=0.3) == pytest.approx(
        math.exp(4.0), rel=1e-9)


# --------------------------------------------------------------------------- #
# 3) duration_sample.json 同构装载（映射 / 向后兼容 / best-effort skip）
# --------------------------------------------------------------------------- #

def _write_archive(path: Path, samples: list[dict], **header: object) -> Path:
    payload = {"schema": "rfauto.quota_guard.ratrace_duration_samples.v1",
               **header, "samples": samples}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_duration_sample_json_maps_stop_fields(tmp_path: Path) -> None:
    """R10 形态映射：hit False->energy / True->nrts_cap / null->未申报。"""
    archive = _write_archive(
        tmp_path / "runs" / "quota_guard" / "duration_sample.json",
        [
            {  # R10 同构：0.3mm 单激励、能量干净停机未触顶
                "id": "R10", "template": "ratrace", "grid_tier": "0p3mm",
                "base_mm": 0.3, "n_excitations": 1, "wall_s": 1781.6,
                "nr_ts_cap_declared": 100000, "hit_nr_ts_cap": False,
                "domain_volume_mm3": 79315.2, "adapter": "openems",
                "source": "ratrace_03mm_sample/result.json:solve_s",
            },
            {  # 触顶停机（R2 机制）
                "id": "RX", "base_mm": 0.2, "wall_s": 13936.7,
                "nr_ts_cap_declared": 100000, "hit_nr_ts_cap": True,
            },
            {  # 旧样本形态：无 stdout 尾巴归档（hit=null）+ 显式 stop_reason 优先
                "id": "R1", "base_mm": 0.2, "wall_s": 7681.6,
                "nr_ts_cap_declared": 100000, "hit_nr_ts_cap": None,
            },
        ],
    )
    loaded = load_duration_sample_json(archive)
    assert loaded["skipped"] == []
    assert [s.stop_reason for s in loaded["samples"]] == [
        "energy", "nrts_cap", ""]
    r10, capped, legacy = loaded["samples"]
    assert (r10.mesh_mm, r10.solve_s, r10.nrts_limit) == (0.3, 1781.6, 100000)
    assert r10.template == "ratrace" and r10.grid_tier == "0p3mm"
    assert r10.n_excitations == 1 and r10.domain_volume_mm3 == pytest.approx(79315.2)
    assert r10.solver == "openems"
    assert capped.feature("nrts_capped_steps") == 100000.0
    assert legacy.feature("stop_energy") == 1.0  # 未知机制 -> one-hot 中性
    assert legacy.nrts_limit == 100000  # 声明上限仍在（机制未知不抹掉上限）
    assert loaded["provenance"] == [str(archive)]


def test_load_duration_sample_json_backward_compat_and_skips(tmp_path: Path) -> None:
    """旧样本缺新字段向后兼容 + 坏条目 best-effort skip（#105）。"""
    archive = _write_archive(
        tmp_path / "duration_sample.json",
        [
            {  # 极简旧条目：缺全部机制面字段 -> 缺省装载不炸
                "id": "OLD", "base_mm": 0.4, "wall_s": 800.0,
            },
            {"id": "BAD1", "base_mm": 0.4, "wall_s": None},  # 缺 wall_s
            {"id": "BAD2", "base_mm": None, "wall_s": 100.0},  # 缺 base_mm
            {  # 触顶却无声明上限：机制已知但无法特征化，如实 skip 不猜
                "id": "BAD3", "base_mm": 0.4, "wall_s": 100.0,
                "hit_nr_ts_cap": True,
            },
            {"id": "BAD4", "base_mm": 0.4, "wall_s": "not-a-number"},
            "not-a-dict",
        ],
    )
    loaded = load_duration_sample_json(archive)
    assert len(loaded["samples"]) == 1
    old = loaded["samples"][0]
    assert (old.nrts_limit, old.stop_reason) == (0, "")  # 缺省 = 未申报
    assert old.n_excitations == 1 and old.solver == "openems"
    assert old.feature("nrts_limit") == 1.0  # v2 特征全中性
    assert old.feature("nrts_capped_steps") == 1.0
    assert all(old.feature(n) == 1.0 for n in DURATION_FEATURES_V2
               if n.startswith("stop_"))
    assert len(loaded["skipped"]) == 5
    assert all(("BAD" in s) or ("non-dict" in s) for s in loaded["skipped"])


def test_load_duration_sample_json_file_level_guards(tmp_path: Path) -> None:
    """缺文件 / schema 不符整文件 skip；schema 缺省宽容装载。"""
    missing = load_duration_sample_json(tmp_path / "nope.json")
    assert missing == {"samples": [], "provenance": [],
                       "skipped": [str(tmp_path / "nope.json")]}
    alien = tmp_path / "alien.json"
    alien.write_text(json.dumps({"schema": "other.schema.v1", "samples": [
        {"id": "X", "base_mm": 0.4, "wall_s": 1.0}]}), encoding="utf-8")
    loaded = load_duration_sample_json(alien)
    assert loaded["samples"] == []
    assert loaded["skipped"] == ["alien.json: schema mismatch 'other.schema.v1'"]
    schemaless = _write_archive(
        tmp_path / "schemaless.json",
        [{"id": "S0", "base_mm": 0.4, "wall_s": 2.0, "hit_nr_ts_cap": True,
          "nr_ts_cap_declared": 50000}],
    )
    ok = load_duration_sample_json(schemaless)
    assert ok["skipped"] == []
    assert ok["samples"][0].stop_reason == "nrts_cap"
    assert ok["samples"][0].nrts_limit == 50000


# --------------------------------------------------------------------------- #
# 4) 序列化兼容：round-trip 逐位一致 + 旧 payload 缺新键
# --------------------------------------------------------------------------- #

def test_tiered_json_roundtrip_and_old_payload_compat() -> None:
    samples = [
        DurationSample(
            mesh_mm=m, solve_s=20.0 + 5.0 * m ** (-3.5),
            domain_volume_mm3=1000.0, n_excitations=1, solver="openems",
            template="ratrace", grid_tier="0p4mm",
            nrts_limit=100000,
            stop_reason="nrts_cap" if m == 0.25 else "energy",
        )
        for m in (0.6, 0.5, 0.4, 0.3, 0.25)
    ]
    query = DurationSample(mesh_mm=0.4, domain_volume_mm3=1000.0,
                           n_excitations=1, solver="openems",
                           template="ratrace", grid_tier="0p4mm")
    before = TieredDurationPredictor.fit(samples).predict(query).to_dict()

    roundtrip = TieredDurationPredictor.from_json(
        TieredDurationPredictor.fit(samples).to_json())
    assert roundtrip.predict(query).to_dict() == before

    # 旧 payload：样本行缺 nrts_limit/stop_reason 键（additive 向后兼容）
    old_payload = {
        "version": 1,
        "samples": [
            {"mesh_mm": m, "solve_s": 20.0 + 5.0 * m ** (-3.5),
             "domain_volume_mm3": 1000.0, "n_excitations": 1,
             "solver": "openems", "template": "ratrace", "grid_tier": "0p4mm",
             "source": ""}
            for m in (0.6, 0.5, 0.4, 0.3, 0.25)
        ],
    }
    from_old = TieredDurationPredictor.from_json(old_payload)
    assert from_old.predict(query).to_dict() == before
    # 显式 null 同样落缺省（不炸）
    null_payload = {
        "version": 1,
        "samples": [dict(row, nrts_limit=None, stop_reason=None)
                    for row in old_payload["samples"]],
    }
    assert TieredDurationPredictor.from_json(null_payload).predict(
        query).to_dict() == before
