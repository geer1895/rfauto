"""CfC 隐态导出 + animation cfc_state 接线端到端钉测（Q-R3R 遗留清偿席）。

清偿 Q-W4-1 登记："CfC 无现成产物形态，出图需先在 lnn_cfc 消费面补隐态
导出"——三段链逐段钉：

- 内存面：``lnn_cfc.hidden_state_doc``（固定权重前向=确定性；真训练禁，
  本文件零 BENCH 级训练）与 ``LnnCfcSurrogate.hidden_states``（1 轮微拟=
  确定性 fixture 构造，非真训练；与 predict_curve 逐位一致性钉）；
- 落盘面：``service/lnn_cfc_export_service.export_cfc_hidden_states``
  （output_path=None 拒写=#144 同族；同 doc 两写逐字节同）；
- 动画面：spec kind=``cfc_state``（spec.py 只增）+ loaders 契约 +
  renderers/cfc_state.py 渲染器——**端到端 1 例**：CfcNet 固定权重
  rollout → 导出 JSON → render_animation(self_check=True) 全链。

数据纪律：本文件全部数据=合成 rollout（固定 seed 权重前向，闭式阶跃
响应采样），零 run 湖读取零示意数据混入渲染链（快照源=确定性前向本身）；
只落 tmp_path，禁写 runs/ 湖。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from rfauto.optimization.surrogate.lnn_cfc import (
    CfcNet,
    LnnCfcSurrogate,
    hidden_state_doc,
    second_order_step_response,
)
from rfauto.service.animation import render_animation
from rfauto.service.animation.loaders import AnimationDataError, load_cfc_state
from rfauto.service.animation.spec import (
    AnimationSpecError,
    parse_animation_spec,
)
from rfauto.service.lnn_cfc_export_service import export_cfc_hidden_states

SEED = 20261106
_NET = dict(n_in=2, hidden=4, backbone=6, seed=SEED)
_THETA = [0.5, 0.5]
N_STEPS = 24


def _net() -> CfcNet:
    return CfcNet(**_NET)


# ─── 内存面：hidden_state_doc ─────────────────────────────────────────────────


def test_hidden_state_doc_shape_keys_and_determinism():
    a = hidden_state_doc(_net(), _THETA, N_STEPS, 1.0,
                         time_grid=[0.0, 8.0], params={"wn": 2.0, "zeta": 0.5})
    b = hidden_state_doc(_net(), _THETA, N_STEPS, 1.0,
                         time_grid=[0.0, 8.0], params={"wn": 2.0, "zeta": 0.5})
    assert a == b  # 同 seed 固定权重前向：同 doc 逐位复现（确定性红线）
    assert a["hidden_dim"] == _NET["hidden"] and a["n_steps"] == N_STEPS
    assert len(a["hidden"]) == N_STEPS
    assert all(len(row) == _NET["hidden"] for row in a["hidden"])
    assert all(-1.0 <= v <= 1.0 for row in a["hidden"] for v in row)  # tanh 有界
    assert a["dt"] == 1.0
    assert a["params"] == {"wn": 2.0, "zeta": 0.5}
    assert len(a["time"]) == N_STEPS and a["time"][0] == 0.0 \
        and a["time"][-1] == 8.0


def test_hidden_state_doc_without_time_grid_has_no_time_key():
    doc = hidden_state_doc(_net(), _THETA, 6, 1.0)
    assert "time" not in doc
    assert doc["n_steps"] == 6
    # dt 向量形态：JSON 原生列表透传
    doc2 = hidden_state_doc(_net(), _THETA, 4, [1.0, 2.0, 3.0])
    assert doc2["dt"] == [1.0, 2.0, 3.0]


def test_hidden_state_doc_negatives_explicit():
    with pytest.raises(ValueError, match="n_steps"):
        hidden_state_doc(_net(), _THETA, 1, 1.0)
    with pytest.raises(ValueError, match="theta_u"):
        hidden_state_doc(_net(), [[0.1, 0.2], [0.3, 0.4]], 6, 1.0)  # 两点批
    with pytest.raises(ValueError, match="非有限"):
        hidden_state_doc(_net(), [float("nan"), 0.5], 6, 1.0)
    with pytest.raises(ValueError, match="time_grid"):
        hidden_state_doc(_net(), _THETA, 6, 1.0, time_grid=[8.0, 0.0])
    with pytest.raises(ValueError, match="time_grid"):
        hidden_state_doc(_net(), _THETA, 6, 1.0, time_grid=[0.0])
    with pytest.raises(ValueError, match="provenance"):
        hidden_state_doc(_net(), _THETA, 6, 1.0, provenance=["x"])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="params"):
        hidden_state_doc(_net(), _THETA, 6, 1.0, params={"wn": float("inf")})


# ─── 拟合模型出口：hidden_states 与 predict_curve 逐位一致 ────────────────────


def _fitted_surrogate() -> LnnCfcSurrogate:
    """1 轮微拟=确定性 fixture 构造（非真训练——BENCH 600/1500 轮归 BENCH 面）。"""
    t = np.linspace(0.0, 4.0, 8)
    model = LnnCfcSurrogate(config={
        "bounds": {"wn": (1.0, 3.0), "zeta": (0.3, 1.2)},
        "time_grid": [0.0, 4.0], "curve_samples": 8,
        "hidden": 4, "backbone": 6, "epochs": 1, "lr": 5e-3, "seed": SEED,
    })
    samples = [
        {"params": {"wn": 1.0, "zeta": 0.4},
         "metrics": {"response_curve":
                     second_order_step_response(t, 1.0, 0.4).tolist()}},
        {"params": {"wn": 1.5, "zeta": 0.7},
         "metrics": {"response_curve":
                     second_order_step_response(t, 1.5, 0.7).tolist()}},
    ]
    model.fit(samples)
    return model


def test_surrogate_hidden_states_matches_predict_curve_bitwise():
    model = _fitted_surrogate()
    params = {"wn": 1.2, "zeta": 0.5}
    doc = model.hidden_states(params)
    curve = model.predict_curve(params)
    assert doc["response"] == curve["response"]  # 同计算路径逐位一致（钉）
    assert doc["time"] == curve["time"]
    assert len(doc["hidden"]) == doc["n_steps"] == 8  # 训练网格点数
    assert doc["hidden_dim"] == 4


def test_surrogate_hidden_states_negatives_and_extrapolation():
    model = _fitted_surrogate()
    with pytest.raises(RuntimeError):
        LnnCfcSurrogate(config={
            "bounds": {"a": (0.0, 1.0)}, "time_grid": [0.0, 1.0],
        }).hidden_states({"a": 0.5})  # 未拟合
    with pytest.raises(ValueError, match="t_end"):
        model.hidden_states({"wn": 1.0, "zeta": 0.5}, t_end=-1.0)
    with pytest.raises(ValueError, match="n_points"):
        model.hidden_states({"wn": 1.0, "zeta": 0.5}, n_points=1)
    # 同 Δt 时域外推契约（与 predict_curve 同）：更长窗=更多步
    doc = model.hidden_states({"wn": 1.0, "zeta": 0.5}, t_end=6.0)
    assert doc["n_steps"] == 8 and doc["time"][-1] == 6.0


# ─── 落盘面：export_cfc_hidden_states ────────────────────────────────────────


def _doc() -> dict:
    return hidden_state_doc(_net(), _THETA, N_STEPS, 1.0,
                            time_grid=[0.0, 8.0],
                            provenance={"source": "fixed-weight forward"})


def test_export_refuses_default_none_path(tmp_path):
    # #144 同族：缺省 None 拒写——不选缺省落盘点（无任何文件产生）
    doc = _doc()
    before = sorted(x.name for x in tmp_path.iterdir())
    with pytest.raises(ValueError, match="拒写"):
        export_cfc_hidden_states(doc, None)
    assert sorted(x.name for x in tmp_path.iterdir()) == before


def test_export_writes_deterministic_json_roundtrip(tmp_path):
    doc = _doc()
    p1 = tmp_path / "nested" / "cfc_state.json"
    assert export_cfc_hidden_states(doc, p1) is doc  # 原样返回（写面零改写）
    back = json.loads(p1.read_text(encoding="utf-8"))
    assert back == doc
    # 同 doc 两写逐字节同（sort_keys+固定缩进+LF 确定性）
    p2 = tmp_path / "cfc_state_again.json"
    export_cfc_hidden_states(doc, p2)
    assert p1.read_bytes() == p2.read_bytes()
    assert b"NaN" not in p1.read_bytes() and b"Infinity" not in p1.read_bytes()


def test_export_rejects_ragged_nonfinite_and_dim_mismatch(tmp_path):
    p = tmp_path / "x.json"
    doc = _doc()
    ragged = dict(doc, hidden=[[1.0, 2.0], [3.0]])
    with pytest.raises(ValueError, match="矩形"):
        export_cfc_hidden_states(ragged, p)
    with pytest.raises(ValueError, match="非有限"):
        export_cfc_hidden_states(dict(doc, hidden=[[float("nan"), 0.0]]), p)
    with pytest.raises(ValueError, match="等长"):
        export_cfc_hidden_states(dict(doc, time=[0.0, 1.0]), p)
    with pytest.raises(ValueError, match="hidden_dim"):
        export_cfc_hidden_states(dict(doc, hidden_dim=7), p)
    with pytest.raises(ValueError, match="dict"):
        export_cfc_hidden_states([1, 2], p)  # type: ignore[arg-type]
    assert not p.exists()  # 校验失败零写面


# ─── 动画面：cfc_state kind 契约 + 渲染器 ────────────────────────────────────


def test_spec_accepts_cfc_state_kind(tmp_path):
    p = tmp_path / "c.json"
    export_cfc_hidden_states(_doc(), p)
    spec = parse_animation_spec({"chart_type": "cfc_state",
                                 "source": {"kind": "cfc_state",
                                            "path": str(p)}})
    assert spec.source is not None and spec.source.kind == "cfc_state"


def test_load_cfc_state_contract(tmp_path):
    p = tmp_path / "c.json"
    export_cfc_hidden_states(_doc(), p)
    doc = load_cfc_state(p)
    assert doc.n_steps == N_STEPS and doc.hidden_dim == _NET["hidden"]
    assert doc.time is not None and len(doc.time) == N_STEPS
    assert doc.provenance == {"source": "fixed-weight forward"}
    # 负例（显式 AnimationDataError，不画空图）
    with pytest.raises(AnimationDataError, match="hidden"):
        (tmp_path / "missing.json").write_text("{}", encoding="utf-8")
        load_cfc_state(tmp_path / "missing.json")
    with pytest.raises(AnimationDataError, match="矩形"):
        bad = tmp_path / "ragged.json"
        bad.write_text(json.dumps({"hidden": [[1.0, 2.0], [3.0]]}),
                       encoding="utf-8")
        load_cfc_state(bad)
    with pytest.raises(AnimationDataError, match="hidden_dim"):
        dimbad = tmp_path / "dim.json"
        dimbad.write_text(json.dumps({"hidden": [[1.0, 2.0]],
                                      "hidden_dim": 5}), encoding="utf-8")
        load_cfc_state(dimbad)


def _end_to_end_files(tmp_path: Path) -> Path:
    """端到端 1 例的数据件：固定权重 rollout → 导出 JSON（tmp_path 内）。"""
    out = tmp_path / "cfc_hidden.json"
    export_cfc_hidden_states(_doc(), out)
    return out


def test_cfc_state_end_to_end_fixed_weight_rollout(tmp_path):
    """端到端 1 例：CfcNet 固定权重前向 → 隐态 JSON → cfc_state 动画全链。"""
    out = _end_to_end_files(tmp_path)
    spec = {"chart_type": "cfc_state",
            "title": "CfC hidden state rollout (fixed-weight forward)",
            "source": {"kind": "cfc_state", "path": str(out)},
            "animation": {"fps": 8}}
    r1 = render_animation(spec, self_check=True)
    r2 = render_animation(spec, self_check=True)
    assert r1.sha256 == r2.sha256  # 同 spec 两跑逐字节同（确定性红线）
    assert r1.frame_count == N_STEPS  # 帧=逐 time step 揭示
    assert abs(r1.duration_s - N_STEPS / 8.0) < 1e-9
    report = r1.self_check
    assert report.ok and report.n_errors == 0
    assert report.n_warnings == 0  # 自检全净（含旋转 ylabel 排版修复红利）
    body = r1.svg_str
    assert body.count("<polyline") == _NET["hidden"]  # 逐隐维一条线
    assert 'frame_count=24' in body
    assert '<desc>' in body  # 帧数契约建档
    # 数据直通：SVG 内无坐标改写面之外的信息面问题由自检兜底（此处零 issue）


def test_cfc_state_renderer_validations(tmp_path):
    out = _end_to_end_files(tmp_path)
    with pytest.raises(AnimationSpecError, match="恰 1 个 source"):
        render_animation({"chart_type": "cfc_state", "sources": [
            {"kind": "cfc_state", "path": str(out)},
            {"kind": "cfc_state", "path": str(out)}]})
    with pytest.raises(AnimationSpecError, match="kind 须为 cfc_state"):
        render_animation({"chart_type": "cfc_state",
                          "source": {"kind": "trials", "path": str(out)}})
    with pytest.raises(AnimationSpecError, match=r"style\.labels"):
        render_animation({"chart_type": "cfc_state",
                          "source": {"kind": "cfc_state", "path": str(out)},
                          "style": {"labels": ["only_one"]}})
    # time 非单调不减 → 显式拒绝（渲染器不隐式重排）
    p = tmp_path / "unsorted.json"
    export_cfc_hidden_states(dict(_doc(), time=list(range(N_STEPS))[::-1]), p)
    with pytest.raises(AnimationDataError, match="单调"):
        render_animation({"chart_type": "cfc_state",
                          "source": {"kind": "cfc_state", "path": str(p)}})


def test_cfc_state_step_axis_when_time_absent(tmp_path):
    doc = hidden_state_doc(_net(), _THETA, 6, 1.0)  # 无 time_grid
    p = tmp_path / "steps.json"
    export_cfc_hidden_states(doc, p)
    r = render_animation({"chart_type": "cfc_state",
                          "source": {"kind": "cfc_state", "path": str(p)}})
    assert r.frame_count == 6
    assert '"x_axis": "step"' in json.dumps(list(r.data_sources), default=str)
