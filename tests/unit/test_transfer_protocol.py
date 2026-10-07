"""AI-3（round14 §三）：预训练-微调迁移协议单元测试。

判据预声明（合成 4 维线性族——源/目标同权重、目标域偏移+2×噪声；
2026-10-03 本机冻结 seed=11/20261003）：

1. L2-SP 闭式两极限：μ→大 = 源模型直用（w_ft≈w_src）；μ→min（0 拒绝，
   从头训走 pretrain_ridge）；λ→大 = 向锚收缩；
2. 少样本判据：最低数据档（frac=0.125）微调 MSE < 从头 MSE
   （共享结构合成族上 L2-SP 必赢——结构共享 + 偏置平移恰是锚能
   补的量）；全量档差距收窄（形态合理）；
3. 确定性：同参同 seed 对比表逐字段一致；切分索引可复现；
4. rfic_tl 真数据通道：数据缺席（本仓外部 gitignored 快照他机缺席为
   合法常态）→ FileNotFoundError；在盘时 schema 对接冒烟（skipif）。

铁律 7 对照：全部数字=闭式线代+注入数据，seed 只控制切分索引。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from rfauto.core.transfer_protocol import (
    DEFAULT_FRACS,
    l2sp_finetune,
    pretrain_ridge,
    synthetic_transfer_case,
    transfer_better_at_low_shot,
    transfer_comparison,
)

REPO = Path(__file__).resolve().parents[2]
UPSTREAM = REPO / "runs" / "pb1_rfic_tl" / "upstream"


class TestClosedForms:
    def test_pretrain_recovers_linear_weights(self):
        x_src, y_src, _x_t, _y_t = synthetic_transfer_case()
        w = pretrain_ridge(x_src, y_src, lam=1e-6)
        assert w[:4] == pytest.approx([2.0, -1.0, 0.5, 0.25], abs=0.05)
        assert w[4] == pytest.approx(1.0, abs=0.05)  # 偏置

    def test_l2sp_large_mu_returns_source_model(self):
        x_src, y_src, x_t, y_t = synthetic_transfer_case()
        w_src = pretrain_ridge(x_src, y_src, lam=1.0)
        w_ft = l2sp_finetune(x_t[:5], y_t[:5], w_src, lam=1.0, mu=1e10)
        assert w_ft == pytest.approx(w_src, rel=1e-6)

    def test_l2sp_large_lambda_shrinks_toward_anchor(self):
        x_src, y_src, x_t, y_t = synthetic_transfer_case()
        w_src = pretrain_ridge(x_src, y_src, lam=1.0)
        w_ft = l2sp_finetune(x_t[:5], y_t[:5], w_src, lam=1e-6, mu=1.0)
        assert np.linalg.norm(w_ft - w_src) < np.linalg.norm(w_src) * 0.5

    def test_mu_zero_rejected(self):
        with pytest.raises(ValueError, match="从头训"):
            l2sp_finetune(np.eye(3), np.zeros(3), np.zeros(4), mu=0.0)

    def test_width_mismatch_rejected(self):
        with pytest.raises(ValueError, match="维数"):
            l2sp_finetune(np.eye(3), np.zeros(3), np.zeros(5))


class TestComparisonProtocol:
    @pytest.fixture(scope="class")
    def table(self):
        _x_src, y_src, x_tgt, y_tgt = synthetic_transfer_case()
        w_src = pretrain_ridge(_x_src, y_src, lam=1.0)
        return transfer_comparison(
            x_tgt, y_tgt, w_src, fracs=DEFAULT_FRACS,
            n_repeat=8, seed=20261003)

    def test_low_shot_finetune_wins(self, table):
        assert transfer_better_at_low_shot(table) is True
        first = table["table"][0]
        assert first["frac"] == pytest.approx(0.125)
        assert first["mse_finetune_mean"] < first["mse_scratch_mean"]

    def test_gap_narrows_at_full_data(self, table):
        rows = table["table"]
        gap_low = rows[0]["mse_scratch_mean"] - rows[0]["mse_finetune_mean"]
        gap_full = rows[-1]["mse_scratch_mean"] - rows[-1]["mse_finetune_mean"]
        assert gap_full <= gap_low + 1e-9

    def test_deterministic(self):
        _x_src, y_src, x_tgt, y_tgt = synthetic_transfer_case(seed=11)
        w_src = pretrain_ridge(_x_src, y_src)
        a = transfer_comparison(x_tgt, y_tgt, w_src, n_repeat=4, seed=1)
        b = transfer_comparison(x_tgt, y_tgt, w_src, n_repeat=4, seed=1)
        assert a["table"] == b["table"]

    def test_validation(self):
        with pytest.raises(ValueError, match="test_frac"):
            transfer_comparison(np.eye(10), np.arange(10.0),
                                np.zeros(5), test_frac=0.9)
        with pytest.raises(ValueError, match="frac"):
            transfer_comparison(np.eye(10), np.arange(10.0),
                                np.zeros(5), fracs=[1.5])


class TestRficTlChannel:
    def test_data_absent_raises_honest(self):
        # 外部数据快照 gitignored：缺席为合法常态（诚实 FileNotFoundError）
        absent = Path("/nonexistent/rfic_tl_root_that_never_exists")
        from rfauto.core.transfer_protocol import rfic_tl_transfer_table
        with pytest.raises((FileNotFoundError, ValueError)):
            rfic_tl_transfer_table(str(absent), ["nodeA_GNVT_39GHz"],
                                   "nodeB_GNVT_39GHz")

    @pytest.mark.skipif(not UPSTREAM.is_dir(),
                        reason="RFIC-TL 快照不在盘（gitignored 外部数据，"
                               "git clone 重放见 core/rfic_tl_dataset docstring）")
    def test_schema_smoke_when_present(self):
        from rfauto.core.rfic_tl_dataset import discover_nodes
        from rfauto.core.transfer_protocol import rfic_tl_transfer_table

        nodes = discover_nodes(UPSTREAM)
        assert len(nodes) >= 2
        table = rfic_tl_transfer_table(
            str(UPSTREAM), source_nodes=nodes[:1], target_node=nodes[1])
        assert table["source_nodes"] == nodes[:1]
        assert table["target_node"] == nodes[1]
        assert table["table"][0]["n_fewshot"] >= 2
