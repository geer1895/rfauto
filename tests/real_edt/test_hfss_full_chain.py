"""real_edt 真机全链验收——build→solve→export→metrics（HANDOFF #3，轻量窄带版）。

P2 目标：确认真机全链跑通 + S 参数物理合理 + SolveReport 收敛真值（D6 get_profile）。
时间敏感：轻量 setup ~45s，单次。断言不硬卡 passes 数量（轻量 setup 自适应 pass 少，
且 AEDT profile 可能不生成完整 adaptive_pass），只校验 success + cost 有限 + 物理合理性。
"""

import pytest

pytestmark = pytest.mark.real_edt


def test_hfss_full_chain_solve(lightweight_wilkinson_recipe, aedt_env_ready, tmp_path, monkeypatch):
    """HFSS 真机全链：run_once 走 hfss 路径，build→solve→export→metrics。"""
    monkeypatch.chdir(tmp_path)
    from rfauto.service.api import run_once

    result = run_once(lightweight_wilkinson_recipe, adapter_name="hfss")
    assert result["ok"], f"run_once 失败: {result.get('errors')}"
    assert result["from_cache"] is False  # 真机首跑不应命中缓存

    # D6: SolveReport 收敛真值（首次真实求解路径）
    sr = result["solve_report"]
    assert sr["success"] is True, f"solve 未成功: {sr}"
    assert "passes" in sr and "delta_s_final" in sr
    print(f"[真机收敛] passes={sr['passes']}, delta_s_final={sr['delta_s_final']}")

    # 全链产物
    assert "run_dir" in result
    assert result["cost"] != float("inf"), "cost 不应为 inf"
    assert result["cost"] > 0  # 理想功分器 cost>0（S 参数偏离目标）

    # S 参数物理合理性（防止 P1 教训：'成功'了两天发现全反射）
    m = result["metrics"]
    s11 = m.get("s11_db_max_in_band")
    s21 = m.get("s21_db_mean_in_band")
    assert s11 is not None and s21 is not None, f"缺少核心指标: {m}"
    assert s11 < -3, f"s11={s11} 异常（接近 0dB 可能全反射，P1 教训）"
    assert -10 < s21 < 0, f"s21={s21} 异常（应接近 -3dB ~ -5dB）"
    print(f"[真机S参数] s11_max={s11:.2f}dB, s21_mean={s21:.2f}dB, cost={result['cost']:.3f}")

    # 收敛报告文件存在
    import json
    from pathlib import Path
    meta = Path(result["run_dir"]) / "meta.json"
    assert meta.exists()
    data = json.loads(meta.read_text(encoding="utf-8"))
    assert data.get("status") == "done"
