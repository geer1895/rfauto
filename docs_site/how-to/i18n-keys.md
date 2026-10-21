<!-- PR-10 文档站同步副本：源=docs/how-to/i18n-keys.md（scripts/build_docs_pages.py 重建，勿直接改本文件——改动请改源文件后重跑生成器） -->

# 如何管理 UI i18n 词表键

**场景**：你要给 UI 新页面/新控件加中英文案，或把一个既有页面接入
i18n。词表是零依赖自研方案（无构建步、无第三方库），单源在
`src/rfauto/ui/static/pages/i18n.js`——本文讲词表结构、三个注入口、
与 esc 转义体系的共存纪律、新页面接线五步。全部命令实测（2026-10-19，
词表 1032 键（发布令批全量软编码后，node 实测；660 系 架构批 W4-S1 时点），`test_ui_i18n.py` + `test_ui_perf_loading.py` 合跑 17 passed）。

## 1. 词表结构（单源 LOCALES）

```javascript
// src/rfauto/ui/static/pages/i18n.js
export const LOCALES = {
  "tools.title": { zh: "微波工具箱", en: "Microwave Tools" },
  "gallery.count_tpl": {
    zh: "{n} 模板 · {p} 配闭式预览通道",
    en: "{n} templates · {p} with closed-form preview",
  },
  ...
};
```

- **键命名**：`<域>.<语义>`。现行 18 域：壳面 `nav.*`（键名=index.html nav 的
  `data-v` 值，单源对齐钉）、`nav.group.*`（侧栏分组）、`common.*`
  （skip 链接/壳 aria/kit 公共空态单源）、`palette.*`、`foot.*`；页面域
  `tools.*` / `gallery.*` / `queue.*` / `dashboard.*` / `runs.*` /
  `detail.*` / `sparams.*` / `agent.*` / `timeline.*` / `loopboard.*` /
  `guide.*` / `datasets.*` / `anchors.*` / `uq.*`。新页面用自己的前缀；
- **值**：`{ zh, en }` 两语言**必须齐**（缺语言=守卫测试红）；**值永不
  含 HTML**（纯文本，守卫测试逐值扫标签）；
- **占位符**：`{name}` 形态，`t(key, { name: value })` 插值——params
  值同为开发侧可信串（见第 4 节）。

当前规模：**1032 键 × 29 域**（2026-10-21 实测：node 枚举
`Object.keys(LOCALES)` 计数，i18n.js 头注同口径——静态壳 + 12 视图页
+ kit 公共件已迁）。

## 2. 三个注入口（静态壳通道）

`applyI18nRoot(root)` 幂等重扫 root 内全部标注元素（返回应用条数）：

| 属性 | 写入目标 | 用途 |
|---|---|---|
| `data-i18n="键"` | `textContent` | 可见文本 |
| `data-i18n-ph="键"` | `placeholder` 属性 | 输入框占位 |
| `data-i18n-aria="键"` | `aria-label` 属性 | 无障碍标签 |

```html
<a class="skip-link" href="#main-content" data-i18n="common.skip_to_content">跳到主内容</a>
<aside aria-label="侧边栏" data-i18n-aria="common.aside_aria">
```

静态壳（`index.html`，39 个标注）由 `pages.js` 启动时
`applyI18nRoot(document)` 一次装配；试点页在各自视图渲染完后对容器
`applyI18nRoot(v)` 补扫。

## 3. t() 渲染期烘焙（动态容器通道）

JS 拼出来的 HTML 容器**不走 data-i18n**（重扫会覆写动态状态），改在
渲染模板串里直接调 `t()`：

```javascript
import { t, applyI18nRoot } from "./i18n.js";

html += `<button id='tool-run' class='primary'>${t("tools.run")}</button>`;
html += `<div class='muted'>${esc(apiData.name)}</div>`;  // 数据走 esc，不进词表
applyI18nRoot(v);  // 壳静态标签补扫
```

**分工一句话**：静态壳挂 `data-i18n*`，动态容器用 `t()` 烘焙；两者都
只放**文案**，不放数据。

## 4. 与 esc 体系的共存纪律（违者返工）

R1 规格写死、守卫测试钉住（`test_view_sink_discipline` /
`test_no_inner_html_and_discipline_header`）：

- `t()` 产出 = **开发侧可信文本**（与既有字面量同信任级）；API 动态
  数据照旧走 `esc()`/`escAttr()`——**禁止 `t()` 包数据、禁止把数据拼
  进词表值**；
- 词表值永不含 HTML，所以三注入口（textContent/placeholder/aria-label）
  零 innerHTML 面；
- CSP 零内联脚本不变：切语言走 `setLocale()` 全壳重扫，不加内联 boot。

## 5. 新页面接线五步

1. **加键**：`i18n.js` 的 `LOCALES` 加 `<页面域>.<语义>`，zh/en 双语
   写齐（值纯文本，插值用 `{name}`）；
2. **静态壳挂标注**：页面 HTML 模板里静态标签挂
   `data-i18n` / `data-i18n-ph` / `data-i18n-aria`（与键一一对应）；
3. **动态容器烘焙**：视图 JS `import { t } from "./i18n.js"`，渲染模板
   串里 `${t("键")}`；数据仍走 `esc()`；
4. **渲染后补扫**：视图装配完调 `applyI18nRoot(v)`（照
   `view_tools.js:537` 先例——切到非 zh 语言档时壳字面被接管）；
5. **守卫自证**：

```bash
.venv/Scripts/python.exe -m pytest tests/unit/test_ui_i18n.py -q
```

五层钉自动核对：双语齐全+零 HTML、属性引用无悬空（引用 ⊆ 词表）、
壳面键无死键（词表 ⊆ 引用）、nav 键集==data-v 全集、纪律头注在档、
`node --check i18n.js` 语法（node 缺席环境 skip）。

## 6. 语言档判定与切换

- 判定序：`localStorage["rfauto-locale"]` 显式档 > `<html lang>` 跟随
  > zh 缺省（隐私模式/无 DOM 全 try/catch，#105 best-effort）；
- 切换出口单源：命令面板「语言 / Language」命令（`palette.js`
  `act-locale`，zh↔en 翻面）→ `setLocale()`——写档 + 同步 `html lang`
  + `applyI18nRoot(document)` 全壳重扫，一步完成；
- 缺键行为：`t()` 对未知键 console.warn 并**返回键名**（渲染不炸，
  #105）——真机看到界面露出 `tools.xxx` 形态的键名就是缺键漏注册。

## 7. 高频坑位

- **把 data-i18n 挂到内容随数据重建的元素上**：语言切换重扫会用词表值
  覆写动态内容——这类元素一律 t() 渲染期烘焙（第 3 节）；
- **词表值里塞 HTML/数据**：双语完整性与零 HTML 是逐值扫描的守卫门，
  塞了当场红；数据进词表还会绕过 esc 信任级分离；
- **只加 en 不加 zh（或反之）**：`test_locales_bilingual_complete_and_html_free`
  逐键扫双语言，缺一边即红；
- **键名与 data-v 不一致**：`nav.*` 键名必须等于导航按钮 `data-v` 值
  （`test_nav_keys_align_data_v_registry` 单源对齐钉）；
- **文档侧全量迁移口径**：静态壳 + 12 视图页 + kit 公共件已迁
  （505 键）；残余硬编码中文面走 `scripts/check_ui_i18n_coverage.py`
  棘轮（40 文件对账零回潮，在账 33 文件 / 5417 个 Han 字符，只减不增）
  后续分波清偿——新页面直接按本文五步接入即是增量正确形态。
