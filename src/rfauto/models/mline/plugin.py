"""mline（均匀微带线锚模板）插件——openEMS 优化通道的最小模型插件。

产物化自优化战役 harness 的进程内注册。定位（与 Wilkinson/Branchline/Patch 插件同一
注册表模式，rfauto.models.registry）：

- **仅参数 schema + 构建钩子**：build() 有意不画几何。mline 的几何单一
  事实源是 openems_templates.render_script("mline", ...)，openems 优化
  适配器（adapters/openems_optimizer_adapter.py）在 solve 时按当前变量
  整脚本重渲染——桌面会话通道（fake/HFSS）与脚本渲染通道不重复建模。
- fake 链：fake_model_type="mline" 命中 FakeAdapter 的 mline 解析近似
  （变量驱动：w_mm → skrf HJ 闭式 εeff → 相速/损耗）。
- openems 链：openems_template="mline" 供 optimizer._create_adapter 的
  openems 分支按插件声明解析渲染模板（缺省回退子串映射）。
"""

from __future__ import annotations

import logging
from typing import ClassVar

from pydantic import BaseModel

from rfauto.core.interfaces import RFModelPlugin, SimulatorAdapter
from rfauto.models.mline.schema import MlineParams
from rfauto.models.registry import register

logger = logging.getLogger(__name__)


class MlinePlugin(RFModelPlugin):
    """均匀微带线（锚模板）插件。

    n_ports=2（MSLPort 1-2：S11/S21，S21 相位斜率→εeff，β 金标准 #162）；
    优化回路消费面（参数 schema/变量写入）与既有插件同构。
    """

    name: ClassVar[str] = "mline"
    params_model: ClassVar[type[BaseModel]] = MlineParams
    schema_version: ClassVar[int] = 1
    n_ports: ClassVar[int] = 2                          # 输入 + 输出（均匀线）
    fake_model_type: ClassVar[str] = "mline"
    # 配方参数名 = 设计变量名（恒等映射；render_script("mline") 的 params
    # 键口径与此一致：w_mm / line_len_mm）
    hfss_var_map: ClassVar[dict[str, str]] = {}
    # openems 优化通道的渲染模板声明（optimizer._create_adapter openems
    # 分支按此解析；未声明 openems_template 的模型回退子串映射）
    openems_template: ClassVar[str] = "mline"

    def build(self, ad: SimulatorAdapter, params: BaseModel) -> None:
        """构建钩子（有意 no-op）。

        几何在 openems 适配器 solve 时按当前参数整脚本重渲染（无桌面会话
        可建；fake 链由 FakeAdapter 按 model_type 走解析近似）。这里只做
        参数归一（与既有插件一致的 params 类型收敛）。
        """
        if not isinstance(params, MlineParams):
            raw = params.model_dump() if hasattr(params, "model_dump") else params.__dict__
            params = MlineParams(**raw)
        logger.debug("mline build 钩子（几何由 openems 适配器渲染）: %s", params)

    def evaluate_extras(self, metrics: dict[str, float]) -> dict[str, float]:
        """mline 无额外专属指标（S11/S21/εeff 均为 DSL 通用指标）。"""
        return metrics


# 自动注册
register(MlinePlugin)
