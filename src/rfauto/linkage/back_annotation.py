"""反标回路（P6）—— ADS 元件值 → HFSS 变量写回。

按 ADR-0003 预留的参数路由，把 ADS 侧元件值纳入 TuningEngine 分段参数空间。
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


class BackAnnotator:
    """反标器：ADS 元件值 → HFSS 变量。

    将 ADS 仿真得到的元件值（如匹配网络的电容/电感值）
    反推为 HFSS 的微带线尺寸变量。
    """

    # 默认映射规则：ADS 元件值 → HFSS 变量
    DEFAULT_MAPPING: ClassVar[dict[str, Any]] = {
        # 电容值 → 微带线宽度（简化映射，实际需要物理模型）
        "capacitor_pf": {
            "hfss_variable": "shunt_w",
            "transform": "inverse_linear",  # C ∝ 1/W
            "reference": {"cap": 1.0, "width": 1.10},
        },
        # 电感值 → 微带线长度
        "inductor_nh": {
            "hfss_variable": "arm_len",
            "transform": "linear",  # L ∝ len
            "reference": {"ind": 1.0, "length": 20.5},
        },
    }

    def __init__(self, mapping: dict[str, Any] | None = None) -> None:
        """
        Args:
            mapping: 自定义映射规则，覆盖 DEFAULT_MAPPING
        """
        self.mapping = mapping or self.DEFAULT_MAPPING.copy()

    def ads_to_hfss_params(
        self,
        ads_metrics: dict[str, Any],
        mapping_rules: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """反标：ADS 元件值 → HFSS 变量。

        Args:
            ads_metrics: ADS 仿真结果（包含元件值）
            mapping_rules: 自定义映射规则（可选）

        Returns:
            dict: HFSS 变量名 → 值
        """
        if mapping_rules:
            # 合并自定义规则
            for rule in mapping_rules:
                key = rule.get("ads_component", "")
                if key:
                    self.mapping[key] = rule

        result: dict[str, Any] = {}

        # 遍历 ADS 指标，查找可映射的元件值
        for ads_key, ads_value in ads_metrics.items():
            if ads_key in self.mapping:
                rule = self.mapping[ads_key]
                hfss_var = rule.get("hfss_variable", "")
                transform = rule.get("transform", "linear")
                ref = rule.get("reference", {})

                if hfss_var and ref:
                    hfss_value = self._transform_value(
                        ads_value, transform, ref
                    )
                    result[hfss_var] = hfss_value
                    logger.info(
                        "反标: %s=%s → %s=%s",
                        ads_key, ads_value, hfss_var, hfss_value,
                    )

        return result

    def _transform_value(
        self,
        ads_value: float,
        transform: str,
        reference: dict[str, Any],
    ) -> float:
        """变换 ADS 值到 HFSS 值。"""
        # reference 约定为二元 {ads_ref: v, hfss_ref: v}，按插入序解包
        ref_iter = iter(reference.values())
        ref_ads = next(ref_iter)
        ref_hfss = next(ref_iter)

        if transform == "linear":
            # 线性映射：hfss_value = ads_value * (ref_hfss / ref_ads)
            return ads_value * (ref_hfss / ref_ads)

        elif transform == "inverse_linear":
            # 反线性映射：hfss_value = ref_ads * ref_hfss / ads_value
            return ref_ads * ref_hfss / ads_value

        else:
            logger.warning("未知变换类型: %s", transform)
            return ads_value


# 模块级实例
_annotator: BackAnnotator | None = None


def get_back_annotator() -> BackAnnotator:
    """获取反标器单例。"""
    global _annotator
    if _annotator is None:
        _annotator = BackAnnotator()
    return _annotator


def back_annotate(
    ads_metrics: dict[str, Any],
    mapping_rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """便捷函数：ADS → HFSS 反标。"""
    annotator = get_back_annotator()
    return annotator.ads_to_hfss_params(ads_metrics, mapping_rules)
