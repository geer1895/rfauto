# 如何添加一个新 CALC 键（注册 + 五钉 + 再生全流程）

**场景**：你要给确定性内核加一个闭式计算器（公式 → 数字），从写函数
到合流预检全绿要动哪些文件、按什么顺序。装饰器形态的速查版在
docs/tutorials/extending-rfauto.md 第 2 节——本文是**全程实操**，
含每一步背后的守卫为什么存在。全部命令实测（2026-10-19 复核；
CALCULATOR_REGISTRY 计数随内核扩批滚动——本文示例以落笔时点
245/246 为锚，**现行值一律以 `python scripts/check_numbers.py`
实测行为准**，勿沿用本文数字）。

## 0. 前置：落位与形态

- 代码只能进 `src/rfauto/core/calc_families/<你的族>.py`（分层铁律：
  数值只在确定性内核，壳层写公式=架构违例）；
- 注册用装饰器（`core/calc_families/registry.py`）：

```python
from rfauto.core.calc_families.registry import register_calculator

@register_calculator(
    "my_formula",                        # 键名（CLI/MCP 消费）
    "一句话语义描述（含口径与文献出处）",
    params=(("freq_ghz", "float GHz - 频率"),
            ("w_mm", "float mm - 线宽")),
    required=("freq_ghz",),
    experimental=False,                  # True=默认不列/默认拒跑
    reciprocal=True,                     # 非互易器件显式 False
)
def my_formula(freq_ghz: float, w_mm: float = 1.0) -> dict:
    ...
```

- 返回纯 dict（数值键），入参校验在函数体显式抛 `ValueError`；
- 参考实现：`core/calc_families/cm_core.py`（切比雪夫族，
  `chebyshev_prototype` 是最小完整样例）。

### 0b. 脚手架入口（推荐）：new_calc_key 生成骨架与五钉模板

手写之前先用生成器（架构批 W8-S3 落件、W15-S3 增强）把骨架与逐钉
可粘贴模板一次产出——**只生成不改**：绝不自动编辑消费者文件，模板
落盘后由人对照锚点粘贴（消费者文件是并行合流热区）：

```bash
# ① 骨架打印到 stdout（--out 落盘则拒绝覆盖已存在文件）
.venv/Scripts/python.exe scripts/new_calc_key.py my_new_key \
    --module my_family --description "一行物理语义（含口径与出处）" \
    --group 传输线 --param "freq_ghz:float GHz - 频率" --required freq_ghz

# ② 五钉消费者补丁模板逐钉落盘（01→05：锚点+代码块+自证命令；
#    会话一次性产物按工作区纪律落 runs/）
.venv/Scripts/python.exe scripts/new_calc_key.py my_new_key \
    --module my_family --description "…" \
    --emit-templates runs/new_calc_key_templates_my_new_key
```

模板 05 会提醒两类特殊面：**模板类键**（键名随新模板族伴生）加跑
test_template_meta_consistency + test_template_geometry_audit；
test_model_docs / test_experimental_calculators 是注册表驱动的自动
覆盖面，零改动跑绿即可。退出码：0=生成成功，2=用法/校验错误
（键名非法、--out 已存在、--emit-templates 越界落 src/tests）。
骨架自带"零物理数字"纪律注记（铁律 7）：常数出处由实现者填入。

## 1. 五钉清单（漏一钉=定向绿、合流全量门红，#231 实证）

| 钉 | 文件 | 动作 |
|---|---|---|
| 1 | `tests/unit/test_calculators.py` | 键加进 `EXPECTED` 集合（实验键加 `EXPERIMENTAL_EXPECTED` 并在注册时 `experimental=True`） |
| 2 | `tests/unit/test_physics_invariants.py` | §1 per-key 输入表加一行：给你的键一组合法输入（不变量测试逐键跑：result 全有限值 + JSON 可序列化） |
| 3 | `tests/unit/test_model_docs.py` | 无需改文件——但你的 spec 必须完整（描述/参数自描述），文档覆盖测试按注册表逐键生成校验 |
| 4 | `tests/unit/test_experimental_calculators.py` | 无需改文件——计数已单源化 `len(EXPECTED)`（#247），只要钉 1 做对这里就绿 |
| 5 | 文档/计数再生面 | 见第 2 节（三处再生一条命令链） |

钉 3/4 是"检查面"不是"修改面"——真正要动手的是钉 1、钉 2、钉 5。

## 2. 文档与计数再生（钉 5 展开）

新键改变计数锚（示例：246→247），三处再生面必须同笔：

```bash
# ① docs_site/reference/calculators.md（键清单+计数，机读生成）
.venv/Scripts/python.exe scripts/build_docs_pages.py

# ② README AUTO-NUMBERS 数字条 + 两处内联计数（缺省 dry-run 看差异）
.venv/Scripts/python.exe scripts/sync_readme_numbers.py          # 预览
.venv/Scripts/python.exe scripts/sync_readme_numbers.py --write  # 落盘

# ③ 内核卡（仅当你的族有专属卡；--check 退出码 1=需重建）
.venv/Scripts/python.exe scripts/build_kernel_cards.py --check
```

若你的实现带出处声明（docstring 行首"出处："标记，铁律 5 惯例），
还要第四处：KD-1 注册表再生——`scripts/collect_formula_provenance.py`
（漂移门 `--check`；声明写法见 docs/how-to/formula-provenance.md），
漏跑的指纹是 test_formula_provenance 三连红。

自证：`scripts/check_numbers.py` 全链对账（输出 All numbers
consistent 才算齐）；若你的键带新族 kernel card，卡内计数由 builder
从三源机读，禁手写数字（#97）。

## 3. 冒烟与定向门

```bash
rfauto calc list                          # 键在列（实验键默认不列——预期行为）
rfauto calc run my_formula -p freq_ghz=2.4 -p w_mm=3.0 --json
```

然后按序跑定向门（新文件写完先 `ruff check`，#104）：

```bash
.venv/Scripts/python.exe -m pytest tests/unit/test_calculators.py \
    tests/unit/test_physics_invariants.py tests/unit/test_model_docs.py \
    tests/unit/test_experimental_calculators.py -q
```

## 4. 收官：合流预检

```bash
.venv/Scripts/python.exe scripts/merge_preflight.py
```

它把"漂移类失败"前移消化：check_numbers 全链、docs_site 再生差异、
注册序金快照、信封契约、help 卫生、CLI/MCP 计数互证全在清单里——
全绿再返回，别把漂移留给 52 分钟全量门。

## 5. 高频坑位（项目史实证）

- **实验键语义**：`experimental=True` 的键 `names()` 默认排除、默认
  拒跑（显式 `include_experimental=True` 才列）——"calc list 看不到
  我的新键"先查这个开关，不是注册失败；
- **键名与 CLI/MCP 文档数字联动**：注册序金快照与计数锚都是"改一处
  动全链"——漏跑再生是 W3 门实红谱系第一位；
- **数值断言对计算函数不对渲染文本**（#175）：给计算器写单测时直接
  断言返回 dict 的数值（解析恒等式/独立来源解析值双对照，#118），
  别匹配 --help 渲染文本；
- **互易性**：隔离器/环行器类注册时显式 `reciprocal=False` 进豁免
  清单，互易性守卫测试才知道不判。
