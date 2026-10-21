"""fake_adapter.calibration —— fake 联合校准锚（configs/fake_calibration.yaml）。

自 adapters/fake_adapter.py 单文件巨石按职责域拆分（架构批 W4-S2，T2 范式/
AU-1 工艺，W3-S1 lake_compact_service 先例）：本域持有 _CAL_CACHE/
_DEFAULT_CALIBRATION/load_fake_calibration（#105 best-effort 读链）。代码体
自原节「fake 联合校准」逐字节搬迁，零逻辑改动。唯一物理路径调整：配置根
定位 parents[3]→parents[4]（单文件→包内子模块目录深度 +1，同一仓根 configs/）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# ─── fake 联合校准（fake ↔ openEMS，AGENTS 硬限 1b：先验模型再校准）──────────

_CAL_CACHE: dict[str, Any] | None = None

# 默认物理锚（无配置文件时使用；来源见各字段注释）
# v0（2026-09-03）：wilkinson 撤绝对 eps_eff 锚（旧锚 3.28 是 branchline 真机
# 值，误用于 wilkinson 会把 f0 压低 10%，P0 FAIL 复盘时发现），谐振频率改由
# synthesis.forward_z0 按线宽物理计算 εeff。
# v1（2026-09-23 用户拍板，上批遗留拍板项①）：wilkinson 落**位置锚（乘法缩放
# 语义）**——eps_eff_scale=K=3.54/2.725 对 HJ 物理推导值做频率尺度修正
# （3.54=openEMS 名义谷位 2.2GHz λ/4 反推，2.725=HJ 参考点 series 臂 εeff
# @2.4GHz，实测 2.724642；缩放语义与实验推导口径同源，拒绝绝对覆盖）。
# R008 结论不变：锚只保 fake 通道谷位保真（UI/冒烟），不承诺预筛排序改善。
# D4 出处注记（2026-09-22 df5 杂项批，grep git 历史裁定；只补注记不改值）：
# - branchline 3.28 = 真机 HFSS 校准值（2026-08-31，configs/fake_calibration.yaml
#   同值同源，代码缺省=配置锚的离线回退镜像）；
# - patch 2.33 = 代码级回退锚，薄基板准静态近似 (εr+1)/2（rogers4350b εr=3.66
#   → (3.66+1)/2=2.33；2026-08-31 18d8c55 引入时行内注 "εeff≈2.33 for
#   rogers4350b"）——生产锚是 configs/fake_calibration.yaml patch eps_eff=3.27
#   （2026-09-02 a93fdc6 A1 联合校准，由 f_res=2.375GHz 反演）。**两值异源
#   不同语义**（名义推导回退 vs 反演校准），不统一（D4 裁定），配置缺失/损坏
#   时本缺省兜底（#105 best-effort）。
_DEFAULT_CALIBRATION: dict[str, dict[str, float]] = {
    "branchline": {"eps_eff": 3.28},       # 真机 HFSS 校准值 2026-08-31（配置同源）
    "patch": {"eps_eff": 2.33},            # (εr+1)/2 回退锚；生产锚=配置 3.27（反演）
    "wilkinson": {"eps_eff_scale": 3.54 / 2.725},
}


def load_fake_calibration(path: str | Path | None = None) -> dict[str, dict[str, float]]:
    """读取 configs/fake_calibration.yaml（best-effort；缺失/损坏返回默认锚）。

    配置来源与含义：eps_eff 为该模型 fake 谐振公式的有效介电常数锚
    （绝对覆盖语义）；eps_eff_scale 为乘法缩放位置锚（对 HJ 物理推导
    εeff 乘频率尺度修正因子，wilkinson 2026-09-23 起用，见
    runs/fake_anchor_354/criteria.md 语义裁定）；
    s11_floor_db/s11_edge_scale 已废除（2026-09-23 df4a，零读取点）。
    数值以 knowledge/reference/openems_nominal/ 的收敛
    openEMS 曲线为准（多模态审计确认模型正确后的联合校准）。
    """
    global _CAL_CACHE
    if _CAL_CACHE is not None:
        return _CAL_CACHE
    merged = {k: dict(v) for k, v in _DEFAULT_CALIBRATION.items()}
    try:
        import yaml
        p = Path(path) if path else Path(__file__).resolve().parents[4] / "configs" / "fake_calibration.yaml"  # W4-S2 拆包：单文件→包内子模块目录深度 +1，同指仓根 configs/
        if p.exists():
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            for model, kv in (data.get("models") or {}).items():
                if isinstance(kv, dict):
                    merged.setdefault(model, {}).update(
                        {k: float(v) for k, v in kv.items() if isinstance(v, (int, float))})
    except Exception:
        # 兜 yaml 模块缺失/配置文件缺失/内容损坏/键非数值等一切读配置侧异常——
        # 校准只是锚点修正（#105 best-effort），任一异常都退回内置默认锚，不阻塞求解
        pass
    _CAL_CACHE = merged
    return merged
