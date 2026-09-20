"""mline（均匀微带线锚模板）模型插件包。

纯 openEMS 锚模板（校准件+引擎仲裁探针+数据工厂）——HFSS 无对应
桌面插件，models.registry 此前的内置插件天然无此项。本包补齐注册
（openems 优化通道接线，自进程内补丁产物化）：

- 几何单一事实源 = openems_templates.render_script("mline", ...)——本插件
  build() 不画几何（openems 优化适配器在 solve 时按当前变量整脚本重渲染）；
- fake 链走 FakeAdapter 的 mline 解析近似（fake_model_type="mline"，变量驱动：
  w_mm → skrf HJ 闭式 εeff → 相速/损耗，w 变则响应变）。
"""
