"""WaveguidePort 族探针 COMPAT 簇4 修补块（模板生成脚本嵌入单源）。

上游 openEMS python 端口 2026-05 重写（9527f81 端口类重构 + efc90db
mode-probe 坐标对齐）后，RectWGPort 缺省 local_origin='corner' 把角点
偏移经 CSPropProbeBox 的 ModeOrigin 交给引擎侧平移；本机安装栈（openEMS
v0.37.0-rc1-11 + CSXCAD v0.7.0-rc1-12 + python 绑定 0.7.0，2026-10-02
重写版）实测该探针 origin 的 XML 序列化错位：(x,y,z) 落盘成 (0,x,y)
（GetModeOrigin 读回正确、Write2XML 落盘错位）。后果：探针权重=未平移
模式函数，与被激励 TE 模正交 → uf_tot≡0、S11≡−1、P_acc≈0（w7a
pyramid_horn_l12 实证；最小复现 内部证据档：
案例 A 缺省 |S11|≡1 全反射、案例 B 旧约定内联偏移 S11max=−48dB 健康、
案例 D=本修补口径与 B 逐位一致）。

修补口径（旧绑定 2023 era 等效）：构造后把端口探针的模式函数改为
内联减角点、ModeOrigin 归零（零向量序列化被跳过=绕开错位）；激励
CSPropExcitation.WeightOrigin 路径实测正常，不动。WG_mode/kc/excite
等端口语义与消费测试钉全部保持不变。

块文本约束：嵌入模板渲染 f-string，故正文不得含花括号（模式表达式
一律 %-格式化；%r 与绑定原 '{}' 浮点格式逐字节同源）。
"""

from __future__ import annotations

# 生成的 openEMS 脚本文本（顶层零缩进；np 由生成脚本头部导入）。
# 行内禁花括号（见模块 docstring 块文本约束）。
WG_PROBE_REFIT_BLOCK = '''\
def _wg_probe_refit(port):
    """COMPAT 簇4：RectWGPort 探针角点偏移改内联（oe_templates'
    wg_port_compat 模块 docstring 含根因与复现指针；安装栈探针
    ModeOrigin 序列化错位 (x,y,z)->(0,x,y)，本函数绕开该序列化面）。"""
    xyz = "xyz"
    ny = int(port.exc_ny)
    m_ord = float(port.M)
    n_ord = float(port.N)
    a_d = port.WG_size[0] / port.unit
    b_d = port.WG_size[1] / port.unit
    ny_p = (ny + 1) % 3
    ny_pp = (ny + 2) % 3
    corner = np.minimum(np.asarray(port.start, dtype=float),
                        np.asarray(port.stop, dtype=float))
    name_p = "(%s-(%r))" % (xyz[ny_p], float(corner[ny_p]))
    name_pp = "(%s-(%r))" % (xyz[ny_pp], float(corner[ny_pp]))
    e_func = [0, 0, 0]
    h_func = [0, 0, 0]
    if n_ord > 0:
        e_func[ny_p] = "%r*cos(%r*%s)*sin(%r*%s)" % (
            n_ord / b_d, m_ord * np.pi / a_d, name_p,
            n_ord * np.pi / b_d, name_pp)
        h_func[ny_pp] = "%r*cos(%r*%s)*sin(%r*%s)" % (
            n_ord / b_d, m_ord * np.pi / a_d, name_p,
            n_ord * np.pi / b_d, name_pp)
    if m_ord > 0:
        e_func[ny_pp] = "%r*sin(%r*%s)*cos(%r*%s)" % (
            -m_ord / a_d, m_ord * np.pi / a_d, name_p,
            n_ord * np.pi / b_d, name_pp)
        h_func[ny_p] = "%r*sin(%r*%s)*cos(%r*%s)" % (
            m_ord / a_d, m_ord * np.pi / a_d, name_p,
            n_ord * np.pi / b_d, name_pp)
    for _prop in port.port_props:
        if type(_prop).__name__ != "CSPropProbeBox":
            continue
        _pt = int(_prop.GetProbeType())
        if _pt == 10:
            _new = [str(_v) for _v in e_func]
        elif _pt == 11:
            _new = [str(_v) for _v in h_func]
        else:
            continue
        if not any(_prop.GetModeOrigin()):
            continue
        _prop.SetModeOrigin([0.0, 0.0, 0.0])
        _prop.SetModeFunction(_new)
'''
