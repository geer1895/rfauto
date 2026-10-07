"""calc_families：core/calculators.py 巨石拆分包（AU-1 批 2，2026-09-30）。

导入本包即完成全部计算器注册（子模块按原文件定义顺序导入，
CALCULATOR_REGISTRY._specs 插入序与原单文件逐位一致）。
公开入口 = rfauto.core.calculators（facade，逐名 re-export）。
"""
# isort: skip_file
# 导入顺序=注册顺序（@register_calculator 装饰器 import 期生效，
# 字母重排会致 _specs 插入序漂移——放文件头才生效，批 1 实证）

from . import registry  # noqa: F401  # 注册副作用
from . import rf_line  # noqa: F401  # 注册副作用
from . import rf_match  # noqa: F401  # 注册副作用
from . import cm_core  # noqa: F401  # 注册副作用
from . import cm_extract  # noqa: F401  # 注册副作用
from . import thermal  # noqa: F401  # 注册副作用
from . import cavity  # noqa: F401  # 注册副作用
from . import symbolic  # noqa: F401  # 注册副作用
from . import slotline_siw  # noqa: F401  # 注册副作用
from . import budget  # noqa: F401  # 注册副作用
from . import cm_diag  # noqa: F401  # 注册副作用
from . import taper  # noqa: F401  # 注册副作用
from . import kqe  # noqa: F401  # 注册副作用
from . import rfid  # noqa: F401  # 注册副作用
from . import shield  # noqa: F401  # 注册副作用
from . import mask_spec  # noqa: F401  # 注册副作用（ge6 pool1 mask 闭环，追加尾位）
from . import cma  # noqa: F401  # 注册副作用（ge6 Wave1 CMA 离线档）
from . import chipless_rfid  # noqa: F401  # 注册副作用（ge6 pool3 chipless 编码，追加尾位）
from . import t_match  # noqa: F401  # 注册副作用（ge6 pool3 T-match，追加尾位）
from . import exposure_limits  # noqa: F401  # 注册副作用（ge6 pool3 暴露限值，追加尾位）
from . import link  # noqa: F401  # 注册副作用（LT-1 G/T 组合键，round18，追加尾位）
from . import propagation  # noqa: F401  # 注册副作用（AP-5 传播基础闭式包，§A-7，追加尾位）
from . import satellite  # noqa: F401  # 注册副作用（AP-9 卫星链路预算器，§A-10，追加尾位）
from . import fading  # noqa: F401  # 注册副作用（AP-7 多径衰落统计包，§A-9，追加尾位）
from . import allan  # noqa: F401  # 注册副作用（MS-5 Allan 方差/时钟稳定度，round15 :212，追加尾位）
from . import corona  # noqa: F401  # 注册副作用（MP-2 电晕/局放判据，round15 :82，追加尾位）
from . import noise_correlation  # noqa: F401  # 注册副作用（MT-1 噪声相关矩阵级联，round17，追加尾位）
from . import rx_impairments  # noqa: F401  # 注册副作用（MT-4 接收机损伤三件套，round17，追加尾位）
from . import mimo  # noqa: F401  # 注册副作用（NX-1 MIMO 虚拟阵+NX-10 MIMO 容量，round14 :88/:108，追加尾位）
from . import ms_gstc  # noqa: F401  # 注册副作用（MM-3 GSTC 面抗综合三键，§C-2，追加尾位）
from . import multipactor  # noqa: F401  # 注册副作用（MP-3 multipactor 击穿阈值，round15 :84，追加尾位）
from . import microwave_heating  # noqa: F401  # 注册副作用（LT-5..7 微波加热整包，round18 :137-144，追加尾位）
from . import electromigration  # noqa: F401  # 注册副作用（MP-4 电迁移-场联动，round15 :86，追加尾位）
from . import pll_loop_filter  # noqa: F401  # 注册副作用（MT-5 PLL 三阶环路滤波器综合，round17 :34，追加尾位）
from . import ris_cascade  # noqa: F401  # 注册副作用（NX-4 RIS 级联闭式表征，round14 :96-97，追加尾位）
from . import crlh  # noqa: F401  # 注册副作用（MM-4 CRLH 单元计算器，round17 :146，追加尾位）
from . import homogenization  # noqa: F401  # 注册副作用（MM-7 均匀化通用内核四键，round17 :154，追加尾位）
from . import reliability  # noqa: F401  # 注册副作用（XD-11 FORM 可靠度 form_beta_linear，ge XD-11 2026-10-04，追加尾位）
from . import array_synth  # noqa: F401  # 注册副作用（RB-ALG-1 差波束三法+RB-ALG-2 MIP 量化阵列，Phase3 W3-E，追加尾位）
