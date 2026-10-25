"""aurora72 A6-D（W8-B P2 尾项 + R6 F-3 版本口径）回归钉。

本席文件面=index.html + server.py + 本测试（pages.js/app.js/palette.js/
theme.js/plotcard.js 他席在制或冻结，禁改）。三块：

1. **P2-4 表单控件 id/name——静态壳守卫**：index.html 内全部
   <input>/<select>/<textarea> 必须带 id 或 name（DevTools a11y
   "A form field element should have an id or name" 的静态壳清零钉）。
   **运行期控件（原登记不修项，2026-10-14 UI-R11 清偿）**：W8-B 审计的
   19 个运行期控件全部出自 pages 模板（imp-include/imp-low/imp-high 行、
   params 参数行、setup 表单、opt-b 行、场切片滑条、uq-sigma；playground
   滑条此前已带 pg-s-*）——已按 pg-s-* 惯例补 id（动态段经 key()（非单词
   字符折 "_"）消毒，id 为纯增量挂钩、data-*/class 消费位不动），棘轮钉=
   TestStaticShellFormFieldIds.test_dynamic_template_form_controls_have_ids
   （label for 的 a11y 半边=aria-label 已由 test_ui_a11y_rows 覆盖）。
   静态壳现况唯一控件 #palette-in 已带 id。

2. **R6 F-3 版本口径（UI 说真话）**：index.html 旧字面 "HFSS 2023.1
   verified" 与硬编码端口 127.0.0.1:8642 清零，脚注中性化（"以实装版本
   为准"+首处括注实测环境 2025 R1/v251，内核立规注记 规则 0 勘误口径）；
   server.py api_hfss_import 缺省版本钉 2023.1→2025.1（与
   edb_adapter._DEFAULT_AEDT_VERSION / remote_machines.yaml 同源）。
   **登记不修项（跨席）**：pages.js 五处旧口径（~940 dashboard solvers
   widget、~1003 guide FAQ、~1018 import help、~1027 imp-version 下拉
   两 option、~1927 solvers help）与 service/adapter 缺省钉
   （hfss_import.py:245 "2023.1"、v3_services.py:666 "2026.1"）不在本席
   文件面；/api/solvers 现无版本字段（type/class/available/n_visualizations），
   "前端消费 API 版本" 需 service 加字段 + pages.js 消费，随解冻批立项。

3. **W8-B P2-3 ocean 主按钮视觉重量**：ocean 主按钮渐变族一档加深提饱和
   （accent/accent2 teal·sky 300→400、primary→teal-500、act2 cyan
   200→400）。本钉对 index.html **活值**重跑 w14_palette_check 口径全矩阵
   （该脚本内嵌 hex 副本是离线镜像，以本活值钉为准）并钉：
   a) 精确 hex（防无声回退）；
   b) 功能面：深字 #04121c/--act-fg 对两族按钮四停靠全 ≥4.5；accent 文字
      三底 ≥4.5；accent2 图形 ≥3.0（与 test_ui_a11y_theme 矩阵同口径，
      双源复述）；
   c) 重量面（新增棘轮）：四停靠对 panel 亮度比 ∈ [5,12]——旧 act2
      #a5f3fc 高达 14.1（washed-out 洗白感即此），上限 12 防 pastel 化
      回潮，下限 5 防过度加深破坏深字可读；
   d) 隔离面：midnight/light 两主题按钮停靠 hex 逐字不动 +
      html[data-theme="light"] 与 body.light 镜像块逐字一致（既有注释
      契约，防本批 ocean 编辑串味）。

不依赖 runs/（gitignored）；免 node/免网络/不启动服务器。
"""

from __future__ import annotations

import re
from pathlib import Path

_STATIC = Path(__file__).resolve().parents[2] / "src" / "rfauto" / "ui" / "static"
_INDEX = (_STATIC / "index.html").read_text(encoding="utf-8")
_SERVER = (_STATIC.parent / "server.py").read_text(encoding="utf-8")
# aurora_d UI-R1 拆分：api_hfss_import 机械迁 routes/importer.py（函数体
# 逐字节未动）——缺省版本钉/旧字面守卫扫描面随单源走。
_IMPORTER = ((_STATIC.parent / "routes" / "importer.py")
             .read_text(encoding="utf-8"))


def _vars(block_re: str) -> dict[str, str]:
    m = re.search(block_re, _INDEX, re.S)
    assert m, f"CSS 块缺失: {block_re}"
    return dict(re.findall(r"(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;", m.group(1)))


def _strip_comments(html: str) -> str:
    return re.sub(r"<!--.*?-->", "", html, flags=re.S)


# ────────────────── 1. P2-4 静态壳表单控件 id/name 守卫 ──────────────────


class TestStaticShellFormFieldIds:
    def test_every_static_form_control_has_id_or_name(self):
        # W8-B ② 控制台 a11y issue "A form field element should have an
        # id or name" 的静态壳清零钉（19 个运行期控件原登记不修=见模块
        # docstring，UI-R11 已清偿；静态壳不得新增无 id/name 控件）。
        html = _strip_comments(_INDEX)
        bare = []
        for m in re.finditer(r"<(?:input|select|textarea)\b[^>]*>", html):
            tag = m.group(0)
            if "id=" not in tag and "name=" not in tag:
                bare.append(tag)
        assert not bare, f"静态壳表单控件缺 id/name: {bare}"

    def test_palette_input_keeps_id(self):
        # 静态壳唯一控件（命令面板输入框）id 在位（palette.js 消费面）
        assert 'id="palette-in"' in _INDEX

    def test_dynamic_template_form_controls_have_ids(self):
        # UI-R11（A6 P2-7 可测试性半边；W8B P2-4 登记清偿）：pages/ 模板面
        # 全部 <input>/<select>/<textarea> 必须带 id（pg-s-* 惯例，动态段经
        # key()（\W→_）消毒为选择器稳健形态；id 纯增量、data-*/class 消费位
        # 不动）。先逐字面钉 10 个新 id 模板位，再全量棘轮防回潮。
        id_templates = (
            ("view_recipe.js", 'id="rp-param-${key(p.name)}"'),   # 配方参数值
            ("view_recipe.js", 'id="rp-setup-${k}"'),             # setup 表单（6 字段）
            ("view_recipe.js", 'id="rp-opt-${key(n)}-low"'),      # 优化下界
            ("view_recipe.js", 'id="rp-opt-${key(n)}-high"'),     # 优化上界
            ("view_gallery.js", "id='gal-s-${key(k)}'"),          # 画廊滑条
            ("view_import.js", 'id="imp-include-${key(n)}"'),     # 导入勾选
            ("view_import.js", 'id="imp-low-${key(n)}"'),         # 导入下界
            ("view_import.js", 'id="imp-high-${key(n)}"'),        # 导入上界
            ("view_data.js", "id='uq-sig-${key(n)}'"),            # UQ 容差 σ
            ("view_fieldviz.js", "id='fv-s-${escAttr(s.axis)}'"),  # 场切片滑条
        )
        for name, needle in id_templates:
            src = (_STATIC / "pages" / name).read_text(encoding="utf-8")
            assert needle in src, f"{name} 缺表单 id 模板位: {needle}"
        # 棘轮：pages/ 模板面 id-less 表单控件零残留（开标签行必须带 id=；
        # 行级判据成立前提=全站模板开标签单行，既有面已核实）
        bare = []
        for p in sorted((_STATIC / "pages").glob("*.js")):
            for i, line in enumerate(
                    p.read_text(encoding="utf-8").splitlines(), 1):
                if (re.search(r"<(?:input|select|textarea)\b", line)
                        and "id=" not in line):
                    bare.append(f"{p.name}:{i}")
        assert not bare, f"pages/ 表单控件模板缺 id（pg-s-* 惯例）: {bare}"


# ────────────────── 2. R6 F-3 版本口径（UI 说真话） ──────────────────


class TestVersionNarrative:
    def test_index_html_no_stale_version_pins(self):
        # 只钉带小数位的版本字面（裸 2023/2026 会误击注释里的日期）
        for stale in ("2023.1", "2026.1"):
            assert stale not in _INDEX, f"index.html 残留旧版本字面 {stale!r}"

    def test_index_html_no_hardcoded_port(self):
        # F-3：服务端口可配（W8-B 验收即跑 8643），静态页不得写死端口号
        assert "8642" not in _INDEX

    def test_footnote_neutral_wording_with_measured_env_note(self):
        # 中性表述 + 首处括注实测环境（六处版本叙事之首=index.html 脚注）
        assert "以实装版本为准" in _INDEX
        assert "2025 R1" in _INDEX and "v251" in _INDEX

    def test_server_import_default_pin_is_real_machine_version(self):
        # server.py（拆分后=routes/importer.py）api_hfss_import 缺省钉=真机
        # 2025.1（空串亦归缺省）
        m = re.search(r'version=str\(body\.get\("version"\) or "([^"]+)"\)', _IMPORTER)
        assert m, "api_hfss_import 缺省版本钉形态漂移"
        assert m.group(1) == "2025.1", f"缺省版本钉应 2025.1（真机 v251），实得 {m.group(1)}"

    def test_server_no_stale_version_literals(self):
        for stale in ("2023.1", "2026.1"):
            assert stale not in _SERVER, f"server.py 残留旧版本字面 {stale!r}"
            assert stale not in _IMPORTER, (
                f"routes/importer.py 残留旧版本字面 {stale!r}")


# ────────────────── 3. W8-B P2-3 ocean 主按钮视觉重量 ──────────────────

# WCAG 自含实现（与 test_ui_a11y_theme / 内部证据档
# 同口径，#118：多源互证而非单源自证）
def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _lum(hx: str) -> float:
    r, g, b = (int(hx[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _ratio(a: str, b: str) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


_OCEAN_BLOCK = r'html\[data-theme="ocean"\]\s*\{(.*?)\}'
_BTN_FG = "#04121c"  # 深主题主按钮深字（w14 checker 口径，midnight 共用）


class TestOceanPrimaryButtonWeight:
    def test_deepened_stop_hexes_pinned(self):
        v = _vars(_OCEAN_BLOCK)
        # 一档加深提饱和（teal/sky 300 档→400 档、primary→teal-500、
        # act2 cyan 200 档→400 档）——精确 hex 钉防无声回退 pastel
        assert v["--accent"] == "#2dd4bf"
        assert v["--accent2"] == "#38bdf8"
        assert v["--primary"] == "#14b8a6"
        assert v["--act2"] == "#22d3ee"
        assert v["--act-fg"] == "#04121c"

    def test_full_contrast_matrix_on_live_values(self):
        # w14_palette_check 口径在 index.html 活值上重跑（0 FAIL 约束）
        v = _vars(_OCEAN_BLOCK)
        fails: list[str] = []
        for fgv in ("--fg", "--muted", "--muted2", "--accent",
                    "--ok", "--warn", "--err"):
            for bgv in ("--bg", "--panel", "--panel2"):
                r = _ratio(v[fgv], v[bgv])
                if r < 4.5:
                    fails.append(f"{fgv} on {bgv}={r:.2f}")
        for fgv in ("--ok", "--warn", "--err"):
            f = [int(v[fgv][i:i + 2], 16) for i in (1, 3, 5)]
            b = [int(v["--panel"][i:i + 2], 16) for i in (1, 3, 5)]
            blended = "#" + "".join(
                f"{round(x * 0.14 + y * 0.86):02x}" for x, y in zip(f, b, strict=True))
            r = _ratio(v[fgv], blended)
            if r < 4.5:
                fails.append(f"badge {fgv}={r:.2f}")
        if _ratio(v["--accent"], v["--panel"]) < 3.0:
            fails.append("accent graphic")
        if _ratio(v["--accent2"], v["--plot-bg"]) < 3.0:
            fails.append("accent2 graphic")
        assert not fails, f"ocean 活值对比度矩阵破门: {fails}"

    def test_button_stops_functional_contrast(self):
        # 两族主按钮四停靠 × 深字 ≥4.5（.act=primary→act2、.primary=accent→accent2）
        v = _vars(_OCEAN_BLOCK)
        for stop in ("--primary", "--act2", "--accent", "--accent2"):
            for fg_name, fg in (("#04121c", _BTN_FG), ("--act-fg", v["--act-fg"])):
                r = _ratio(fg, v[stop])
                assert r >= 4.5, f"按钮深字 {fg_name} on {stop}={r:.2f} < 4.5"

    def test_button_stops_visual_weight_band(self):
        # 重量棘轮：四停靠对 panel 亮度比 ∈ [5,12]。旧 act2 #a5f3fc=14.1
        # （W8-B P2-3 "视觉重量偏弱"的量化本体=洗白 pastel）；上限 12 防
        # pastel 化回潮，下限 5 防过度加深破坏深字可读。
        v = _vars(_OCEAN_BLOCK)
        for stop in ("--primary", "--act2", "--accent", "--accent2"):
            r = _ratio(v[stop], v["--panel"])
            assert 5.0 <= r <= 12.0, f"{stop} 对 panel 亮度比 {r:.2f} 出重量带 [5,12]"

    def test_other_themes_button_stops_untouched(self):
        # 隔离面：本批只动 ocean——midnight/light 按钮停靠 hex 逐字不动
        midnight = _vars(r":root\s*\{(.*?)\}")
        assert midnight["--accent"] == "#93a0fa"
        assert midnight["--accent2"] == "#22d3ee"
        assert midnight["--primary"] == "#6366f1"
        assert midnight["--act2"] == "#22d3ee"
        assert midnight["--act-fg"] == "#050914"
        light = _vars(r"body\.light\s*\{(.*?)\}")
        assert light["--accent"] == "#4f46e5"
        assert light["--accent2"] == "#0e7490"
        assert light["--primary"] == "#4f46e5"
        assert light["--act2"] == "#0e7490"
        assert light["--act-fg"] == "#ffffff"

    def test_light_mirror_blocks_stay_identical(self):
        # 既有契约（对比度账本解析器口径）：html[data-theme="light"] 块与
        # body.light 块逐字一致——防 ocean 编辑串味到浅色镜像
        a = re.search(r'html\[data-theme="light"\]\s*\{(.*?)\}', _INDEX, re.S)
        b = re.search(r"body\.light\s*\{(.*?)\}", _INDEX, re.S)
        assert a and b, "浅色双块缺失"
        assert a.group(1) == b.group(1), "浅色镜像双块不再逐字一致"
