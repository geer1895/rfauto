"""oe_templates：openems_templates 巨石拆分包（AU-1，2026-09-30）。

导入本包即完成全部族注册（render_core 顶层按注册顺序汇集族模块，
TEMPLATE_META/TEMPLATE_NOMINAL 等插入顺序与原单文件逐名一致）。
公开入口 = rfauto.adapters.openems_templates（facade，逐名 re-export）。
"""
# isort: skip_file
# 导入顺序=注册顺序（closedform→hairpin 共享链使族注册不得按字母重排；
# render_core 位置=级联触发点——isort 字母重排会致注册序漂移，2026-09-30 实证后钉此文件）

from . import registry  # noqa: F401  # 注册副作用
from . import closedform  # noqa: F401  # 注册副作用
from . import smatrix  # noqa: F401  # 注册副作用
from . import grid  # noqa: F401  # 注册副作用
from . import render_core  # noqa: F401  # 注册副作用
from . import render_tl  # noqa: F401  # 注册副作用
from . import render_ratrace_cyl  # noqa: F401  # 注册副作用
from . import render_hairpin  # noqa: F401  # 注册副作用
from . import render_coupled_bpf  # noqa: F401  # 注册副作用
from . import render_msl_sma  # noqa: F401  # 注册副作用
from . import render_antenna2  # noqa: F401  # 注册副作用
from . import render_c3  # noqa: F401  # 注册副作用
from . import render_array_eep  # noqa: F401  # 注册副作用
from . import render_c4  # noqa: F401  # 注册副作用
from . import render_siw  # noqa: F401  # 注册副作用
from . import render_slotline  # noqa: F401  # 注册副作用
from . import render_metasurface  # noqa: F401  # 注册副作用
from . import render_coil_nfc  # noqa: F401  # 注册副作用
from . import render_mmwave  # noqa: F401  # 注册副作用
from . import render_ring  # noqa: F401  # 注册副作用
from . import render_horn  # noqa: F401  # 注册副作用
from . import render_coax_wg  # noqa: F401  # 注册副作用
from . import render_varactor  # noqa: F401  # 注册副作用
