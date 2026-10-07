"""HfssAdapter.dual_conductor_mode_impedances 薄封装接线钉（ge8e W1 A2）。

背景：ge8e 审查批 F7 建 core/coupled_mode_z 单源（#307 换算链：共模
Zc=Z0e/2、差模 Zd=2·Z0o，模序按 εeff 较高识别偶模）时 hfss_adapter 并发
在制无法接线（审查 R4-4：换算链只活在 runs 任务书 文档与战役脚本）；
本批适配器 expose 薄封装收口——零 gRPC/零 session 触碰（未连接亦可调），
供仲裁脚本与未来消费者走单源。

数值证据=runs/hairpin_hfss_anchor/hairpin_anchor.json 归档读数（与
test_coupled_mode_z.py 同源逐位字面量，零改写只读）。
"""

from __future__ import annotations

import pytest

from rfauto.adapters.hfss_adapter import HfssAdapter
from rfauto.core.coupled_mode_z import DualConductorModeImpedances

# runs/hairpin_hfss_anchor/hairpin_anchor.json verdict.points["0.5"]
# .line_default_zpi per_port 每模 Modal Zo 读数（逐位字面量）
ZO = {"m1": (29.29097559664919, 29.002746036964748),
      "m2": (96.74300002087644, 95.33145958876825)}
EPS = {"m1": (3.0469352415471382, 3.0394922211781012),
       "m2": (2.590339340109888, 2.592684148037429)}


def test_expose_replays_archived_readings_bitwise() -> None:
    adapter = HfssAdapter()  # 未连接（纯换算零 session 触碰）
    out = adapter.dual_conductor_mode_impedances(ZO, EPS)
    assert isinstance(out, DualConductorModeImpedances)
    assert out.z0e_ohm == 58.29372163361394   # 2·mean(Zc)，归档逐位
    assert out.z0o_ohm == 48.01861490241117   # Zd/2，归档逐位
    assert out.even_mode_key == "m1"          # εeff 较高者=偶模（#307）
    assert out.odd_mode_key == "m2"
    assert out.k_z == pytest.approx(0.09665018252816722, rel=1e-15)


def test_expose_is_core_single_source_passthrough() -> None:
    """与 core 直调逐字段相等（薄封装零数值面添加）。"""
    from rfauto.core.coupled_mode_z import (
        dual_conductor_mode_impedances as core_fn,
    )

    adapter = HfssAdapter()
    via_adapter = adapter.dual_conductor_mode_impedances(ZO, EPS)
    via_core = core_fn(ZO, EPS)
    assert via_adapter == via_core  # frozen dataclass 逐字段相等


def test_expose_error_semantics_forwarded() -> None:
    """core 拒绝语义透传（模数不足显式 ValueError，不静默降级）。"""
    adapter = HfssAdapter()
    with pytest.raises(ValueError, match="至少 2 个模"):
        adapter.dual_conductor_mode_impedances({"m1": 29.0}, {"m1": 3.0})
    with pytest.raises(ValueError, match="并列"):
        adapter.dual_conductor_mode_impedances(
            {"m1": 29.0, "m2": 96.0}, {"m1": 3.0, "m2": 3.0})


def test_expose_docstring_carries_provenance() -> None:
    """docstring 注明 #307 出处与 F7 受阻背景（登记语义钉）。"""
    doc = HfssAdapter.dual_conductor_mode_impedances.__doc__ or ""
    assert "#307" in doc
    assert "F7" in doc
