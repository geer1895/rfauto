/* 指标词典前端数据面（aurora_i W2-S2，R3 设计 M2）：
   /api/metric-glossary 会话级单拉缓存（词条是小清单——38 键，一次取全量
   后本地判定着色，不打逐键请求）；挂载器把 data-mkey 挂点元素（如 runs
   表列头）接上悬浮说明。全部 best-effort（#105）：词典加载失败=空映射
   （调用方降级原样渲染，说明层不得成为页面主路径故障点）。 */

import { apiFetch } from "./api.js";
import { getLocale } from "./i18n.js";
import { metricTipText } from "./kit.js";

/* 会话级缓存（null=未拉）；失败也缓存空映射（本会话不再重试——词库是
   静态知识文件，失败多为服务端旧版，重试无益；刷新页面重试）。 */
let _promise = null;

export function metricGlossaryMap() {
  if (!_promise) {
    _promise = apiFetch("/api/metric-glossary")
      .then((d) => {
        const map = {};
        if (d && d.ok && Array.isArray(d.entries)) {
          for (const e of d.entries) {
            if (e && typeof e === "object" && e.metric_id)
              map[e.metric_id] = e;
          }
        }
        return map;
      })
      .catch(() => ({}));
  }
  return _promise;
}

/* 把 root（元素/选择器，缺省 document）内全部 [data-mkey] 挂点接上悬浮
   说明（列头 th 等静态挂点用；动态行内徽章走 kit.metricBadgeHtml 直渲）。
   词条缺席的挂点零触碰（不挂 class 不占位）。 */
export async function mountMetricTips(root) {
  const scope = typeof root === "string"
    ? (typeof document !== "undefined" ? document.querySelector(root) : null)
    : (root || (typeof document !== "undefined" ? document : null));
  if (!scope || typeof scope.querySelectorAll !== "function") return;
  const map = await metricGlossaryMap();
  const els = scope.querySelectorAll("[data-mkey]");
  for (const el of els) {
    if (el.classList.contains("m-tip")) continue; // 幂等重挂零副作用
    const entry = map[el.getAttribute("data-mkey")];
    const tip = metricTipText(entry, getLocale());
    if (!tip) continue;
    el.classList.add("m-tip");
    el.setAttribute("tabindex", "0");
    el.setAttribute("data-tip", tip);
  }
}
