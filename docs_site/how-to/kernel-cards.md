<!-- PR-10 文档站同步副本：源=docs/how-to/kernel-cards.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# 如何理解与再生存内核文档卡（74 张三源聚合体系）

**场景**：你写/改了一个确定性内核（`core/` 下的公式模块或注册计算器），
要给它出一张人读文档卡；或者卡面数字/公式与代码面对不上要查漂移；
或者想"这个内核的口径是什么、被谁消费、精度有没有建档"——先查卡再
读源。**卡不是手写的文档**：它是 `scripts/build_kernel_cards.py` 从
三源机读聚合的生成物，手改必被冲掉。新 CALC 键的注册流程见
docs/how-to/add-new-calc-key.md，公式出处声明见
docs/how-to/formula-provenance.md——本文管"卡"这一层。

## 1. 三源与卡面结构

生成器（2026-10-19 实测 74 张）从三源聚合出
`docs_site/kernel_cards/<kernel_id>.md`（文档站"内核文档卡"节，
mkdocs nav 逐张注册）：

| 源 | 文件 | 喂给卡面哪节 |
|---|---|---|
| 精度档案（XC-P） | `knowledge/precision_profiles.yaml` | 「精度域」（已建档/未收录两支路，不编造分档数字） |
| 出处注册（KD-1） | `knowledge/formula_provenance.yaml` | 按 kernel_file 过滤的「出处」引注（零命中就显示"0 条"） |
| 模块 docstring/AST | `src/rfauto/core/...` | 物理语义、公式原文、使用边界、公开符号 |
| 辅源 | `knowledge/anchors.yaml` + tests/service/adapters 引用扫描 | 「锚与测试入口」「关联」（消费拓扑） |

固定节序：物理语义 → 公式与口径 → 精度域 → 使用边界 → 代码入口 →
锚与测试入口 → 关联。卡头表格记内核 ID/主模块/注册表状态/KD-1 条数
/数据来源——全部构建时实测。

## 2. 再生与保鲜门

```bash
# 原地重建全部卡（写 docs_site/kernel_cards/）
.venv/Scripts/python.exe scripts/build_kernel_cards.py

# 漂移检查（重渲染 vs 已提交逐字节比对；退出码 1=需重建，不写文件）
.venv/Scripts/python.exe scripts/build_kernel_cards.py --check

# 保鲜门（重渲染 == 已提交字节；合流门/全量门成员）
.venv/Scripts/python.exe -m pytest tests/unit/test_kernel_cards.py -q
```

确定性契约：不写时间戳/环境相关内容，键序/遍历序全部显式排序——
同一棵树重跑逐字节一致，所以"改了源忘重建"必被 `--check` 与保鲜门
抓住。

## 3. 改动走哪条路（按你想改什么）

| 你想改 | 动哪里 | 之后 |
|---|---|---|
| 公式/物理语义/口径 | 内核模块 docstring | 重跑生成器（docstring 是唯一写作点） |
| 精度分档 | 精度档案（先看 formula-provenance 与精度档案分工） | 重跑生成器 |
| 出处 | docstring 出处行（KD-1 再生，见 formula-provenance.md） | 先跑 KD-1 收集器，再跑卡生成器 |
| 公式 LaTeX 转写/使用边界注记 | 生成器内该卡的手写段 | **每条必须携带 docstring 逐字引文（quote）** |
| 消费拓扑/测试计数 | 不用动——引用扫描机读 | 重跑生成器即更新 |

两条同源纪律（#97 零手写数字）：卡内一切计数（KD-1 条目数、公开符号
数、test 函数数、锚命中数）构建时实测，**禁止手写**；手写段仅公式
LaTeX 与使用边界注记两处，且引文是机器核对载体——构建时断言 quote
在模块源文件中存在，LaTeX/注记只是它的人读转写。

## 4. 与其他面的分工

- `docs/how-to/add-new-calc-key.md`：键注册 + 五钉消费者同步——
  "让键存在且门全绿"；
- `docs/how-to/formula-provenance.md`：出处声明写作与 KD-1 再生——
  "让出处可查"，卡面出处注册节按 kernel_file 过滤渲染，零命中的卡
  就显示"0 条"（诚实路径）；
- `docs_site` 参考页再生（`scripts/build_docs_pages.py`）：管站点
  目录/参考页同步，不管卡内容。

## 5. 高频坑位

- **手改卡文件**：下次重建即冲掉 + 保鲜门红（双输）——永远改源
  （docstring/YAML/生成器手写段）后重跑生成器；
- **手写段引文不逐字**：quote 与模块源文件差一个字/标点，构建断言
  即红——引文从 docstring 复制粘贴，不要凭记忆转写；
- **零命中想"补数字"**：某内核还没有精度档案/出处条目时，卡面就
  显示"0 条"/未收录——去补的是源（建档/写出处行），不是卡面数字
  （#122 的原则：宁可显示 0，不编一个数）；
- **先出处后出卡**：写新卡前先把 docstring 出处声明写好并跑 KD-1
  收集器——卡面按 kernel_file 过滤，出处行缺失时卡面"出处注册 0 条"
  而不是报错，容易漏看。
