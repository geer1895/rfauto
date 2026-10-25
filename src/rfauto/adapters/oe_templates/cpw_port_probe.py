"""CPWPort exc_dir 语义两代并存的自适应探针（渲染脚本注入文本单源）。

openEMS 绑定 2026-10-02 CPWPort exc_dir 语义重定义：旧=面法向/高度方向
（'z'），新=缝间电场方向=CPW 宽度方向（'x'），高度法向改由 prop×exc 叉积
自算。两代对 start/stop 的等值检查轴互换（新代查法向 z，旧代查 exc 轴），
同一渲染字面量跨代部署必有一侧构造即炸（aurora_c cpw 席服务器实测：服务器
绑定停在旧代 v0.37.0-rc1-11-gd3d2a49，按新代口径 exc_dir="x" 渲染即抛
"CPWPort: start/stop in height direction must be equal"——start/stop 的 z
两端本就相等（同贴金属面 H_SUB），炸点实为 exc 轴语义换位）。

处置=渲染脚本内对绑定源码语义自检（inspect.getsource），按**部署侧实际
语义**自适应选 exc_dir——跨代部署/服务器后续升级绑定均自愈。探针必须在
脚本执行期运行（渲染期自检的是渲染机而非部署机，语义可能不同）。

单源纪律（#116）：全部 CPWPort 发射点（cpw/msl_cpw/fgcpw 三模板，与
render_core footer ``extra_ports_import`` 名单一致）一律经
:func:`exc_dir_probe_lines` 注入同一探针文本，禁止内联复制（原 render_tl
内联版即 CFIX 2026-10-13 初版，已收编为本单源）。适用前提=CPWPort 端口
start/stop 贴金属面（高度方向两端相等）——三发射点均满足。

本模块不注册模板、零包内依赖（三个 render_* 消费者 import 无环），无
``__all__``（公开面私有，public_api 金快照零影响）。
"""

from __future__ import annotations

#: 新代绑定指纹：CPWPort.__init__ 内 "exc_dir=缝间横向" 口径的唯一行
#: （openEMS ports.py）。旧代（≤d3d2a49）同位置是 exc_vec/argmax 高度口径
#: （exc_dir=面法向），无此行。
NEW_GEN_FINGERPRINT = "self.width_ny = CheckNyDir(exc_dir)"


def exc_dir_probe_lines() -> str:
    """渲染脚本可 exec 的自适应探针源码文本（执行后置 ``_CPW_EXC_DIR``）。

    新绑定源码含指纹行 → ``_CPW_EXC_DIR="x"``（exc_dir=缝间横向）；
    旧绑定 → ``"z"``（exc_dir=面法向）。getsource 不可得（冻结环境）缺省
    按新代 "x"（与本仓 2026-10-02 口径一致——CFIX 初版 except 分支置空
    _cpw_src 实际落 'z'，与其头注声明相反，本单源已按声明方向修正；旧代
    部署为常规安装、getsource 可用，不受该缺省影响）。返回文本以换行
    结尾，直接内插进模板体 f-string（调用方惯用 ``_cpw_probe_src`` 局部
    变量承载）。
    """
    return (
        "# CPWPort exc_dir 语义两代并存的自适应探针（单源\n"
        "# oe_templates.cpw_port_probe，口径与测试钉\n"
        "# tests/unit/test_cpw_port_probe.py）：新绑定含指纹行\n"
        f'# "{NEW_GEN_FINGERPRINT}"（exc_dir=缝间横向）；\n'
        "# 旧绑定（≤d3d2a49 代）同位置是 exc_vec/argmax 高度口径\n"
        "#（exc_dir=面法向）；getsource 不可得（冻结环境）缺省按新代 'x'\n"
        "#（与本仓 2026-10-02 口径一致）。\n"
        "import inspect as _insp\n"
        "try:\n"
        "    _cpw_src = _insp.getsource(CPWPort.__init__)\n"
        "except (OSError, TypeError):\n"
        "    # 冻结环境 getsource 不可得：以指纹行占位=缺省按新代 'x'\n"
        "    #（旧代部署为常规安装、getsource 可用，不受此缺省影响）\n"
        f'    _cpw_src = "{NEW_GEN_FINGERPRINT}"\n'
        f'if "{NEW_GEN_FINGERPRINT}" in _cpw_src:\n'
        '    _CPW_EXC_DIR = "x"   # 新绑定：exc_dir=缝间横向（宽度方向）\n'
        "else:\n"
        '    _CPW_EXC_DIR = "z"   # 旧绑定：exc_dir=面法向（高度方向）\n'
    )
