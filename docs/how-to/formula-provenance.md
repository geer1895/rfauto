# 如何声明公式出处与再生 KD-1 注册表

**场景**：你在 `core/` 写了一个新内核函数（或改了某模块的出处注记），
定向门报"注册表与 docstring 扫描漂移"；或者你要给新内核模块写出处
声明，想一次写对、不被收集器拒收。为什么要有这套制度（出处↔精度的
分工、三载体防漂移）见 docs/explanation/formula-provenance-system.md
——本文只管"怎么做"。全部命令实测（2026-10-19，entries=278 口径；
条目数随内核扩批滚动，现行值以实测为准）。

## 0. 30 秒认知：三载体与再生方向

| 载体 | 文件 | 角色 |
|---|---|---|
| 人读面 | 各内核模块 docstring 的出处行 | 出处声明的**唯一写作点**（禁反向手改注册表） |
| 机读单源 | `knowledge/formula_provenance.yaml` | 收集器生成（`manual_entries` 段除外），消费面查这里 |
| 机制面 | `src/rfauto/core/formula_provenance.py` | schema/AST 扫描/查询；`scripts/collect_formula_provenance.py` 是再生薄壳 |

再生方向永远是 **docstring → 注册表**：改出处只改 docstring，然后跑
收集器。手改 YAML 的 entries 段会被下一次再生冲掉，一致性门也会红。

## 1. 写声明：两种形态

### 形态 A：source（行首标记，主力形态）

在函数/类/模块 docstring 里写一行**行首标记**，收集器从标记行起取
声明块（连续注记行，空行后接 bullet 或更深缩进才续块；上限 30 行）：

```python
def microstrip_attenuation(...):
    """微带衰减率（dB/m）。

    出处：Hammerstad-Jensen 导体衰减（经 qucsator msline.cpp 可执行
    逐字+Qucs 手册 式(11.79)-(11.83) 双源）；介质衰减式同节。
    已核——两网源逐字一致，β 闭环对照另见 内部证据目录*。
    """
```

- 认识的标记词（`core/formula_provenance.MARKER_LINE_RE` 单源）：
  `出处：`/`来源：`/`法源：`/`文献：`/`机制出处：`/`口径来源：`/
  `原始文献：`/`参考文献：`/`权威口径：`/`Spec 出处：`/`References：`，
  以及裸 `参考（`——**裸"参考："必须有文献证据**（refs 抽取面/§锚/
  docs/ 链接之一），纯 prose 用法（"参考（不做门判）"）不收；
- 声明块内可被抽取的证据面：DOI（`DOI:10.xxxx/...`）、arXiv id、
  标准号（ITU-R P.xxx/CISPR/IEEE Std/IEC/ECSS/3GPP TS/ASME V&V）、
  URL、带年份的引文行（ISO 日期不算年份）、式号/章节锚（`式(n)`、
  `§x.y`、`Eq. n`、`Table n`）；
- **可达性词面**（自声明，unverified 从严优先）：写"已核/逐位核对/
  双源/实测可达"→ verified；写"未核/付费墙/不可达"→ unverified；
  判不了就别写词——如实 null，不编；
- 模块 docstring 也收（symbol 记 `<module>`，`出处见` 指针的常规落点）。

### 形态 B：pointer（指针，"出处见"）

函数级一句话指向模块头注，不重复抄块：

```python
def mbvd_impedance(...):
    """…（函数 docstring 其余部分）

    出处见模块 docstring（Larson III et al. 2000 IEEE Ultrasonics Symp.）。
    """
```

仅收"出处见"字样所在行，块=该行本身。

### 两条边界

- `精度档案：knowledge/precision_profiles.yaml#…` 镜像行属于 **XC-P
  精度档案**载体，收集器按前缀剥离不进本表（两表分工见 explanation）；
- 注释（`#`）与无标记的内联引文**不在收集面**——宁缺毋滥是登记口径
  （如实不凑数）。

## 2. 再生与漂移门

```bash
# 再生（写 knowledge/formula_provenance.yaml；manual_entries 逐字保留）
.venv/Scripts/python.exe scripts/collect_formula_provenance.py
#   → [kd1] 写入 knowledge\formula_provenance.yaml（entries=278，files=225，manual=0）

# 漂移门（只验不写；CI/定向门用）
.venv/Scripts/python.exe scripts/collect_formula_provenance.py --check
#   绿：[kd1] OK: 注册表与 docstring 扫描逐字节一致（entries=278，manual=0）
#   红：[kd1] FAIL: … 漂移（diff 行数=N）——exit 1 并给再生指引与前 20 行 diff
```

幂等契约：同一棵树二跑逐字节 diff=0（无时间戳类字段）——再生后立即
再跑 `--check` 应当绿；不绿说明有并发在写树（先 `git status` 盘点）。

一致性门（改动后与合流前都要跑）：

```bash
.venv/Scripts/python.exe -m pytest tests/unit/test_formula_provenance.py -q
```

## 3. 健康巡检：audit_provenance（XA-6）

```bash
.venv/Scripts/python.exe scripts/audit_provenance.py          # 人读报告
.venv/Scripts/python.exe scripts/audit_provenance.py --json   # 机读面
.venv/Scripts/python.exe scripts/audit_provenance.py --unverified-ratio-max 0.3
```

五面判据（实测 2026-10-19：ratio=41/278≈0.147 绿，judged 41/(28+41)
≈0.59 只报告不作门，verified 无机读证据 13 条报告面）：

| 面 | 判据 | 语义 |
|---|---|---|
| 1 unverified 占比 | unverified/docstring 条目 > 阈值（缺省 0.30，严格大于才红） | fail |
| 2 孤儿条目 | kernel_file 磁盘缺失（文件删除/移动未再生） | fail |
| 3 陈旧条目 | formula_id 在重扫描中消失（标记被删未再生） | fail |
| 4 verified 证据抽检 | verified 且 refs/DOI 双缺，如实列出 | 报告 |
| 5 未收集新条目 | 扫描有而注册表无（归属第 2 节 --check） | 报告 |

退出码：0=绿；1=fail 面超限；2=巡检不可执行（注册表缺失/schema 坏）。

## 4. 人工补录（manual_entries）

出处不在 docstring 里（如经多跳文献传导链、外部仲裁报告）时，往
`knowledge/formula_provenance.yaml` 的 `manual_entries` 段手补——这是
注册表唯一允许手写的段。必需键 `formula_id`（全表唯一，建议
`manual/<主题>:<符号>:01` 自定前缀避免与扫描 id 撞）、`claim_line`、
`verified_by`；可选 `note`、`refs`、`source_doi` 等全 schema 键。
再生时收集器逐字保留补录段；查询面/摘要面把 manual 条目一并纳入。

## 5. 查询面（消费方怎么用）

```python
from rfauto.core.formula_provenance import formula_provenance, provenance_summary

formula_provenance(file="microstrip_extra.py")        # 按文件查（仓相对路径）
formula_provenance(symbol="microstrip_attenuation")   # 按符号查
provenance_summary()                                   # 覆盖摘要（by_kind/by_access/…）
```

内核卡（`scripts/build_kernel_cards.py`，74 张）按 kernel_file 过滤渲染
"KD-1 出处注册"节，零命中的卡如实渲染"0 条"——写卡前先把出处声明写进
docstring，卡面数字由 builder 机读，禁手抄。

## 6. 高频坑位

- **改了 docstring 忘了再生**：一致性门红（`test_registry_matches_fresh_scan`
  等 3 连红是典型指纹）——跑第 2 节再生即可，不要手补 YAML；
- **标记行不在行首**（前面有正文）或用了词表外的头（如"依据："）：
  收集不到，条目静默缺失——拿查询面查自己的符号确认在档；
- **可达性词面误伤**：块里出现"未经"（如"未经仿真"）即判 unverified
  （从严优先）——只想声明"已核"时别在同一块里带否定词面；
- **XC-P 镜像行抄进出处块**：会被剥离（防两表串味），但它不是出处
  证据——两表各写各的行；
- **manual 条目 formula_id 撞扫描 id**：加载器整表唯一钉红，自定前缀
  规避。
