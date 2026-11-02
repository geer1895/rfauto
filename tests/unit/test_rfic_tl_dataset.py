"""PB-1 RFIC-TL 公开基准接入测试（core/rfic_tl_dataset）。

三段结构：
- 无数据也可跑（其他机器全绿）：节点名解析、按节点划分的无泄漏与
  校验逻辑（内存合成 dict，不触文件系统数据）；
- 数据在盘（runs/pb1_rfic_tl/upstream，skipif 缺失——他机诚实 skip）：
  实测 schema/样本计数码钉（钉上游快照 commit，上游更新数据即红=
  有意复检信号）、真实数据无泄漏钉、numpy 岭回归最小基线；
- 基线口径（2026-09-26 实测）：x→y 映射强非线性（线性岭回归节点内
  mean R²=0.164，二次特征 0.333，跨节点≈0——上游用 Cascade_512 深网
  有因）。本基线只作「管线跑通 + 数值合理」的机械性检查：固定种子
  子采样下节点内对照 mean R² > 0.10 宽松门（x/y 错位或数据损坏即塌
  到 ≤0），跨节点数值只打印登记、不设硬门（方案书 PB-1 接入口径：
  基准级对比留 GP/surrogate_loop 通道，非本测试职责）。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from rfauto.core.rfic_tl_dataset import (
    UNITS,
    UNSTATED,
    X_COLUMNS,
    Y_COLUMNS,
    Z_COLUMNS,
    discover_nodes,
    load_rfic_tl,
    parse_node_name,
    train_test_split_by_node,
)

REPO = Path(__file__).resolve().parents[2]
UPSTREAM = REPO / "runs" / "pb1_rfic_tl" / "upstream"
_HAS_DATA = (UPSTREAM / "data").is_dir()
_SKIP_REASON = (
    "RFIC-TL 上游快照不在盘（诚实 skip）："
    "git clone --depth 1 https://github.com/ChenhaoChu/RFIC-TL.git "
    "runs/pb1_rfic_tl/upstream"
)

# 2026-09-26 实测（上游 commit 41d8aac6）：样本计数码钉
EXPECTED_COUNTS = {
    "nodeA_GNRN_30GHz": 3159000,
    "nodeB_GNVT_30GHz": 328050,
    "nodeB_GNVT_39GHz": 328050,
    "nodeB_RNVT_30GHz": 328050,
    "nodeB_RNVT_39GHz": 328050,
}


# ---------------------------------------------------------------------------
# 无数据段：节点名解析与划分逻辑（内存合成）
# ---------------------------------------------------------------------------


def test_parse_node_name() -> None:
    meta = parse_node_name("nodeB_GNVT_39GHz")
    assert meta == {"process": "nodeB", "metal": "GNVT", "frequency_ghz": 39.0}
    meta_a = parse_node_name("nodeA_GNRN_30GHz")
    assert meta_a == {"process": "nodeA", "metal": "GNRN", "frequency_ghz": 30.0}


def test_parse_node_name_rejects_bad_format() -> None:
    for bad in ("nodeX", "nodeB_GNVT", "nodeB_GNVT_39", "NodeB_GNVT_39GHz"):
        with pytest.raises(ValueError, match="不符合"):
            parse_node_name(bad)


def _fake_data() -> dict:
    """三节点合成 dict（行数互异以便核对堆叠）。"""

    def node(n: int, fill: float) -> dict:
        return {
            "x": np.full((n, 4), fill, np.float32),
            "y": np.full((n, 6), fill * 2, np.float32),
            "z": np.full((n, 6), fill * 3, np.float32),
        }

    return {
        "nodes": {
            "nodeA_GNRN_30GHz": node(4, 1.0),
            "nodeB_GNVT_30GHz": node(3, 2.0),
            "nodeB_RNVT_39GHz": node(5, 3.0),
        }
    }


def test_split_by_node_no_leakage_in_memory() -> None:
    data = _fake_data()
    split = train_test_split_by_node(data, ["nodeB_RNVT_39GHz"])
    # 协议核心断言：train/test 节点集交为空
    assert not (set(split["train_nodes"]) & set(split["test_nodes"]))
    assert split["train_nodes"] == ["nodeA_GNRN_30GHz", "nodeB_GNVT_30GHz"]
    assert split["test_nodes"] == ["nodeB_RNVT_39GHz"]
    assert split["x_train"].shape == (7, 4)  # 4 + 3
    assert split["y_train"].shape == (7, 6)
    assert split["x_test"].shape == (5, 4)
    # test 块逐值等于被排除节点的数据（无篡改直通）
    assert np.array_equal(split["y_test"], data["nodes"]["nodeB_RNVT_39GHz"]["y"])
    # target="z" 通道
    split_z = train_test_split_by_node(data, ["nodeB_GNVT_30GHz"], target="z")
    assert split_z["y_train"].shape == (9, 6)
    assert np.array_equal(
        split_z["y_test"], data["nodes"]["nodeB_GNVT_30GHz"]["z"]
    )


def test_split_by_node_validates_inputs() -> None:
    data = _fake_data()
    with pytest.raises(ValueError, match="未知测试节点"):
        train_test_split_by_node(data, ["nodeC_XXYY_60GHz"])
    with pytest.raises(ValueError, match="不能为空"):
        train_test_split_by_node(data, [])
    with pytest.raises(ValueError, match="训练集为空"):
        train_test_split_by_node(data, list(data["nodes"]))
    with pytest.raises(ValueError, match="target"):
        train_test_split_by_node(data, ["nodeB_GNVT_30GHz"], target="x")
    with pytest.raises(ValueError, match="nodes"):
        train_test_split_by_node({"schema": {}}, ["nodeB_GNVT_30GHz"])


# ---------------------------------------------------------------------------
# 数据在盘段（skipif）：schema 码钉 + 无泄漏钉 + 最小基线
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_DATA, reason=_SKIP_REASON)
class TestRficTlRealData:
    def test_discover_all_nodes(self) -> None:
        assert discover_nodes(UPSTREAM) == list(EXPECTED_COUNTS)

    def test_load_schema_and_provenance(self) -> None:
        data = load_rfic_tl(UPSTREAM, nodes=["nodeB_GNVT_30GHz"])
        node = data["nodes"]["nodeB_GNVT_30GHz"]
        # 列序按上游 preprocess.py（生成代码口径，非 README）
        assert data["schema"]["x_columns"] == list(X_COLUMNS)
        assert data["schema"]["y_columns"] == list(Y_COLUMNS)
        assert data["schema"]["z_columns"] == list(Z_COLUMNS)
        assert node["x"].shape == (328050, 4)
        assert node["y"].shape == (328050, 6)
        assert node["z"].shape == (328050, 6)
        assert node["x"].dtype == np.float32
        assert node["process"] == "nodeB"
        assert node["metal"] == "GNVT"
        assert node["frequency_ghz"] == 30.0
        # provenance 强制面：出处/许可/诚实 caveat/单位
        prov = data["provenance"]
        assert prov["license"] == "Apache-2.0"
        assert prov["source_url"] == "https://github.com/ChenhaoChu/RFIC-TL"
        assert "fictitious" in prov["data_release_note"]
        assert "C1" in prov["column_order_caveat"]
        assert "频率是节点级标量" in prov["frequency_axis_note"]
        assert prov["units"]["y"]["SRF"] == "GHz"
        assert prov["units"]["y"]["k"] == "dimensionless"
        assert prov["units"]["x"]["C1"] == UNSTATED
        assert UNITS["z"]["wlow"] == UNSTATED
        # 实测量级码钉（±1e-3 容差，float32 舍入内）
        r = node["ranges"]
        assert r["x"]["C2"] == pytest.approx([10.0, 300.0], abs=1e-3)
        assert r["y"]["k"] == pytest.approx([0.3644, 0.7691], abs=1e-3)
        assert r["y"]["SRF"] == pytest.approx([52.5, 100.0], abs=1e-3)
        assert r["z"]["r0"][0] == pytest.approx(40.0, abs=1e-3)

    def test_full_inventory_counts(self) -> None:
        data = load_rfic_tl(UPSTREAM)
        assert data["summary"]["n_nodes"] == 5
        assert data["summary"]["n_samples_total"] == sum(EXPECTED_COUNTS.values())
        for name, expected_n in EXPECTED_COUNTS.items():
            assert data["nodes"][name]["n_samples"] == expected_n
        # loader 已拒绝非有限值（实测全零 NaN）；此处钉 x 有限性直通
        assert np.isfinite(data["nodes"]["nodeA_GNRN_30GHz"]["x"]).all()

    def test_split_by_node_no_leakage_real(self) -> None:
        data = load_rfic_tl(
            UPSTREAM, nodes=["nodeB_GNVT_30GHz", "nodeB_RNVT_30GHz"]
        )
        split = train_test_split_by_node(data, ["nodeB_RNVT_30GHz"])
        assert not (set(split["train_nodes"]) & set(split["test_nodes"]))
        n_train = data["nodes"]["nodeB_GNVT_30GHz"]["n_samples"]
        assert split["x_train"].shape[0] == n_train
        assert split["x_test"].shape[0] == EXPECTED_COUNTS["nodeB_RNVT_30GHz"]
        assert np.array_equal(split["x_test"], data["nodes"]["nodeB_RNVT_30GHz"]["x"])

    def test_minimal_ridge_baseline(self) -> None:
        """最小 numpy 岭回归基线：管线跑通 + 机械性宽松门（口径见模块 docstring）。

        固定种子 0、固定子采样 30k/10k——数值完全可复现；节点内对照
        mean R² 实测 0.1641（2026-09-26），门 0.10 只防 x/y 错位级故障，
        不是基准级性能门；跨节点数值打印登记不设门。
        """
        data = load_rfic_tl(UPSTREAM, nodes=["nodeB_GNVT_30GHz", "nodeB_GNVT_39GHz"])
        rng = np.random.default_rng(0)

        def ridge_fit_predict(
            x_tr: np.ndarray, y_tr: np.ndarray, x_te: np.ndarray, lam: float = 1e-3
        ) -> np.ndarray:
            mu, sd = x_tr.mean(0), x_tr.std(0)
            sd = np.where(sd == 0, 1.0, sd)
            ymu, ysd = y_tr.mean(0), y_tr.std(0)
            ysd = np.where(ysd == 0, 1.0, ysd)
            A = (x_tr - mu) / sd
            Y = (y_tr - ymu) / ysd
            n, d = A.shape
            W = np.linalg.solve(A.T @ A + lam * n * np.eye(d), A.T @ Y)
            return ((x_te - mu) / sd) @ W * ysd + ymu

        def r2_per_target(y_true: np.ndarray, y_pred: np.ndarray) -> np.ndarray:
            ss_res = ((y_true - y_pred) ** 2).sum(0)
            ss_tot = ((y_true - y_true.mean(0)) ** 2).sum(0)
            denom = np.where(ss_tot > 0, ss_tot, 1.0)
            return np.where(ss_tot > 0, 1.0 - ss_res / denom, np.nan)

        src = data["nodes"]["nodeB_GNVT_30GHz"]
        idx = rng.permutation(src["n_samples"])
        tr_idx, te_idx = idx[:30000], idx[30000:40000]
        pred_in = ridge_fit_predict(src["x"][tr_idx], src["y"][tr_idx], src["x"][te_idx])
        r2_in = r2_per_target(src["y"][te_idx], pred_in)
        mean_r2_in = float(np.nanmean(r2_in))
        print(f"in-node control R2 per target: {np.round(r2_in, 4)}")
        print(f"in-node control mean R2: {mean_r2_in:.4f}")
        # 机械性宽松门：显著优于常数预测器（x/y 错位即塌 ≤0）
        assert mean_r2_in > 0.10
        assert np.isfinite(pred_in).all()

        split = train_test_split_by_node(data, ["nodeB_GNVT_39GHz"])
        assert not (set(split["train_nodes"]) & set(split["test_nodes"]))
        i_te = rng.permutation(split["x_test"].shape[0])[:10000]
        i_tr = rng.permutation(split["x_train"].shape[0])[:30000]
        pred_x = ridge_fit_predict(
            split["x_train"][i_tr], split["y_train"][i_tr], split["x_test"][i_te]
        )
        r2_x = r2_per_target(split["y_test"][i_te], pred_x)
        print(f"cross-node (30->39GHz) R2 per target: {np.round(r2_x, 4)}")
        print(f"cross-node mean R2: {float(np.nanmean(r2_x)):.4f}")
        # 跨节点不设硬门：只要求可计算且预测非退化
        assert np.isfinite(r2_x).all()
        assert float(pred_x.std()) > 0.0
