"""T-O4 real_edt：ADS 前仿链真机一例（wilkinson_snp 闭式参考链）。

spec §6 钉 9（真机一例）：build_wilkinson_touchstone 造闭式参考 .s3p →
ads-circuit run（真 hpeesofsim）→ 对拍 gate_ok=True（门 1e-3）→ 反标注图
annot_sim 层可读（draw.io 人工目检=交付报告附产物路径）。skip-not-fail
（缺 RFAUTO_HPEESOF_DIR/ADS 安装即 skip，不阻塞缺省门）；solo 单飞
（#246：真机并发拖慢 2.7-8×，计时敏感真机项一律 solo）。

环境红线（任务书转抄）：仓根执行或显式 RFAUTO_HPEESOF_DIR（#295 相对
cwd 读 settings）；求解只走 ads_netlist 正规 env 入口（#272 裸调 exe
静默无输出）。真机预算 ≤5min 级冒烟（41 点 S 参数批处理秒级~分钟级）。
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from rfauto.core.circuit_diagram import ANNOT_LAYER_ID
from rfauto.linkage import ads_template_family as atf
from rfauto.service.circuit_sim_service import (
    circuit_sim_run,
    generate_circuit_diagram,
)

pytestmark = [pytest.mark.real_edt, pytest.mark.solo]

_ADS = Path(os.environ.get("RFAUTO_HPEESOF_DIR", r"C:/Program Files/Keysight/ADS2027"))


@pytest.mark.skipif(not (_ADS / "bin" / "hpeesofsim.exe").exists(),
                    reason="ADS 2027 未安装（RFAUTO_HPEESOF_DIR 未设且缺省路径不存在）")
def test_ads_circuit_run_real_wilkinson(tmp_path):
    """真机一例：闭式参考 .s3p → 出图 → run → gate_ok → 反标注图在档。"""
    snp = atf.build_wilkinson_touchstone(tmp_path / "wilk.s3p", n_points=41)
    gen = generate_circuit_diagram("wilkinson_snp", snp, tmp_path / "ckt.drawio")
    assert gen["ok"], gen.get("errors")

    result = circuit_sim_run(tmp_path / "ckt.drawio", snp_path=snp,
                             out_dir=tmp_path / "run")
    assert result["ok"], result.get("errors")
    assert result["ads"]["status"] == "ok"
    assert result["ads"]["runner"] == "hpeesofsim"
    # 对拍=SnP 直通（数据穿透），max|ΔS| 应在 Touchstone 写出精度量级
    assert result["compare"]["gate_ok"] is True
    assert result["compare"]["max_abs_delta_s"] <= 1e-3

    # 反标注图：annot_sim 层在档可读（draw.io 人工目检项的结构化替身）
    annotated = Path(result["annotated_diagram_path"])
    assert annotated.exists()
    root = ET.parse(annotated).getroot()
    layer_cells = [el for el in root.iter("mxCell") if el.get("id") == ANNOT_LAYER_ID]
    assert len(layer_cells) == 1, "annot_sim 层恰一张（幂等）"
    metric_cards = [el for el in root.iter("UserObject")
                    if (el.get("id") or "").startswith("sim_")]
    assert metric_cards, "指标卡上图"
    for card in metric_cards:
        assert card.get("source") and card.get("sim_ref") is not None
    # 指标量级合理（wilkinson 带内均值；闭式对照 #118）
    metrics = result["metrics"]
    assert -4.0 < metrics["system_gain_db"] < -3.0
    assert metrics["amplitude_balance_db"] == pytest.approx(0.0, abs=1e-2)
