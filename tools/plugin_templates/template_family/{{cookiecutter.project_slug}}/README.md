# {{ cookiecutter.project_slug }}

rfauto 模板族插件（RFModelPlugin 契约，`rfauto.models.registry` 注册面）。

## 快速开始

```bash
pip install cookiecutter          # 渲染（一次性）
cookiecutter /path/to/rfauto/tools/plugin_templates/template_family
cd {{ cookiecutter.project_slug }}
pip install -e . --no-deps        # 安装进 rfauto 所在 venv
```

安装后 `[project.entry-points."rfauto.models"]` 组被
`rfauto.models.registry` 双检锁发现，`models.registry.get("{{ cookiecutter.template_name }}")`
即可取用。

## ⚠️ #362：entry-point 变更必须重装

`importlib.metadata` 读的是**安装时 dist-info 快照**——改过
`pyproject.toml` entry-point 段后必须 `pip install -e . --no-deps` 重装，
否则新插件对发现层不存在（症状：单跑绿、全量红、缺谁取决于元数据龄）。
reload 注册表的测试必须 `registry.__dict__` 快照 + finally 还原。

## #154：param_semantics 跨通道语义声明

同一配方参数跨通道（openEMS 模板渲染/HFSS 插件/fake 近似）的物理角色
必须显式声明且互洽（wilkinson series/shunt 相反语义实证）。模板族的
参数名→渲染脚本键口径要与消费通道逐参数对齐后再接校准/优化。

## #304：注册新模板族的消费者清单（缺一必红）

- `tests/unit/test_template_meta_consistency.py`：TEMPLATE_NOMINAL 键集
  必须与 `docs/templates/<t>/meta.yaml` nominal_params 一致（内置模板
  面消费者；第三方包建议同样交付 meta.yaml 保持可审计）；
- `tests/unit/test_template_geometry_audit.py`（EXPECTED_TEMPLATES）与
  三处字面计数（antenna2×2/coupled_bpf/slotline_family_registration，
  #247 已改 `len(TEMPLATE_META)` 单源的不受影响）；
- `tests/unit/test_models_registry.py` 面：`models.registry.list_models()`
  计数断言若为字面量需同步；
- fake 通道：`fake_model_type` 键若不在 FakeAdapter 解析近似表内，须
  fake 侧扩展或显式接受 wilkinson 缺省近似（仅冒烟非物理）。

## 验证

```python
from rfauto.models.registry import get, list_models

assert "{{ cookiecutter.template_name }}" in list_models()
plugin_cls = get("{{ cookiecutter.template_name }}")
params = plugin_cls.params_model(w_mm=3.0, line_len_mm=40.0, er=4.4)
```
