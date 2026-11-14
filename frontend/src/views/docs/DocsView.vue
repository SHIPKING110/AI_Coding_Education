<template>
  <div class="docs-page">
    <aside class="docs-side">
      <div class="docs-brand">
        <span class="docs-kicker">Developer Docs</span>
        <h1>开发文档</h1>
        <p>按模块组织的企业级落地说明</p>
      </div>

      <input v-model="query" class="docs-search" placeholder="搜索文档…" />

      <nav class="docs-nav">
        <div v-for="g in groups" :key="g.name" class="docs-group">
          <div class="docs-group-title">{{ g.name }}</div>
          <RouterLink
            v-for="d in g.items"
            :key="d.slug"
            :to="`/docs/${d.slug}`"
            class="docs-link"
            :class="{ active: d.slug === slug }"
          >
            <span class="docs-link-title">{{ d.title }}</span>
            <span class="docs-link-desc">{{ d.desc }}</span>
          </RouterLink>
        </div>
        <p v-if="!groups.length" class="docs-empty">没有匹配的文档</p>
      </nav>
    </aside>

    <main class="docs-main">
      <div class="docs-toolbar">
        <RouterLink v-if="slug === 'rag-eval-spec'" to="/rag/eval" class="docs-back">← 返回评测中心</RouterLink>
        <span class="docs-crumb">
          开发文档 <i>/</i> {{ doc?.group || '未知' }} <i>/</i> {{ doc?.title || slug }}
        </span>
        <span class="docs-badge">v1.0</span>
      </div>

      <div v-if="doc" class="docs-grid">
        <article ref="articleRef" class="docs-article" v-html="rendered.html" />

        <aside class="docs-toc">
          <div class="docs-toc-title">本页目录</div>
          <a
            v-for="t in rendered.toc"
            :key="t.id"
            :href="`#${t.id}`"
            class="docs-toc-link"
            :class="{ sub: t.level === 3 }"
            @click.prevent="scrollToSec(t.id)"
          >
            {{ t.text }}
          </a>
          <div v-if="!rendered.toc.length" class="docs-toc-empty">—</div>
        </aside>
      </div>

      <div v-else class="docs-missing">
        <h2>未找到文档「{{ slug }}」</h2>
        <p>该文档可能尚未创建或链接已失效。</p>
        <RouterLink to="/docs/index" class="btn">返回文档首页</RouterLink>
      </div>

      <div v-if="doc" class="docs-pager">
        <RouterLink v-if="prev" :to="`/docs/${prev.slug}`" class="pager-card">
          <span>上一篇</span><b>{{ prev.title }}</b>
        </RouterLink>
        <span v-else />
        <RouterLink v-if="next" :to="`/docs/${next.slug}`" class="pager-card next">
          <span>下一篇</span><b>{{ next.title }}</b>
        </RouterLink>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import { renderMarkdown } from '@/utils/markdown'
import { observeMermaid, renderMermaidNodes } from '@/utils/mermaid'

interface DocMeta {
  slug: string
  title: string
  desc: string
  group: string
  keywords?: string
}

const REGISTRY: DocMeta[] = [
  { slug: 'index', title: '文档首页', desc: '文档定位、地图与阅读顺序', group: '开始' },
  { slug: 'architecture', title: '系统架构', desc: '技术栈、分层、目录与部署拓扑', group: '基础' },
  {
    slug: 'ai-agent',
    title: 'AI 与 Agent 架构',
    desc: 'LangChain、编排、工具、记忆、RAG',
    group: 'AI 架构',
    keywords: 'LangChain LangGraph function calling agent 智能体 记忆 mcp 沙箱 rag',
  },
  { slug: 'permissions', title: '权限体系', desc: '角色、权限键、职务预设与鉴权链路', group: '基础' },
  { slug: 'modules', title: '业务模块', desc: '学员、排课、反馈、报告、评估、习题', group: '业务' },
  { slug: 'rag-admin', title: '后台管理（RAG）', desc: '知识资产、路由、追踪、任务与设置', group: '后台管理' },
  {
    slug: 'rag-eval-spec',
    title: '评测数据规格',
    desc: '导入格式、字段、校验与合规要求',
    group: '后台管理',
    keywords: '评测 导入 jsonl json csv 合规 脱敏 指标',
  },
  {
    slug: 'rag-eval-metrics',
    title: '评测指标解读',
    desc: '各指标口径、参考线、闸门与判读手册',
    group: '后台管理',
    keywords: '指标 hit mrr ndcg recall 忠实度 完整性 kappa 闸门 阈值 判读 bad case',
  },
  { slug: 'usage-cost', title: '用量与成本', desc: '计价、归属、预算告警与月度对账', group: '后台管理' },
  { slug: 'api', title: '接口约定', desc: '鉴权、分页、错误码与请求示例', group: '研发' },
  { slug: 'ops', title: '部署与运维', desc: '容器、迁移、备份、排障与安全', group: '研发' },
]

const modules = import.meta.glob('../../docs/*.md', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

const route = useRoute()
const articleRef = ref<HTMLElement>()
const query = ref('')

const slug = computed(() => {
  const raw = String(route.params.slug || 'index')
  // 兼容旧链接：/docs/rag-eval-import-format
  return raw === 'rag-eval-import-format' ? 'rag-eval-spec' : raw
})

const doc = computed(() => REGISTRY.find((d) => d.slug === slug.value) || null)

const docIndex = computed(() => REGISTRY.findIndex((d) => d.slug === slug.value))

const prev = computed(() => (docIndex.value > 0 ? REGISTRY[docIndex.value - 1] : null))
const next = computed(() =>
  docIndex.value >= 0 && docIndex.value < REGISTRY.length - 1 ? REGISTRY[docIndex.value + 1] : null,
)

function rawFor(target: string): string {
  const entry = Object.entries(modules).find(([key]) => key.endsWith(`/${target}.md`))
  return entry ? entry[1] : ''
}

/** 渲染 Markdown，并为 h2/h3 注入锚点，生成右侧目录 */
const rendered = computed<{ html: string; toc: { id: string; text: string; level: number }[] }>(() => {
  const raw = rawFor(slug.value)
  if (!raw) return { html: '', toc: [] }
  const base = renderMarkdown(raw)
  const toc: { id: string; text: string; level: number }[] = []
  let seq = 0
  const html = base.replace(/<h([23])>([\s\S]*?)<\/h\1>/g, (_m, lvl: string, inner: string) => {
    const id = `sec-${++seq}`
    const text = inner.replace(/<[^>]+>/g, '').trim()
    toc.push({ id, text, level: Number(lvl) })
    return `<h${lvl} id="${id}">${inner}</h${lvl}>`
  })
  return { html, toc }
})

const groups = computed(() => {
  const q = query.value.trim().toLowerCase()
  const filtered = REGISTRY.filter((d) => {
    if (!q) return true
    return `${d.title} ${d.desc} ${d.slug} ${d.keywords || ''}`.toLowerCase().includes(q)
  })
  const order: string[] = []
  const map = new Map<string, DocMeta[]>()
  for (const d of filtered) {
    if (!map.has(d.group)) {
      map.set(d.group, [])
      order.push(d.group)
    }
    map.get(d.group)!.push(d)
  }
  return order.map((name) => ({ name, items: map.get(name)! }))
})

function scrollToSec(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function toTop() {
  const scroller = articleRef.value?.closest('.main') as HTMLElement | null
  scroller?.scrollTo({ top: 0 })
  window.scrollTo({ top: 0 })
}

watch(slug, () => {
  nextTick(toTop)
})

// 文档中的 mermaid 流程图：MutationObserver 自动渲染（本地打包懒加载，失败保留源码+重试）
function renderDocMermaid() {
  void nextTick().then(() => {
    observeMermaid(articleRef.value)
    void renderMermaidNodes(articleRef.value)
  })
}
onMounted(renderDocMermaid)
watch(() => rendered.value.html, renderDocMermaid)
</script>

<style scoped>
.docs-page {
  display: grid;
  grid-template-columns: 264px minmax(0, 1fr);
  gap: 28px;
  max-width: 1320px;
  margin: 0 auto;
}

/* ---------------- 左侧导航 ---------------- */
.docs-side {
  position: sticky;
  top: 0;
  align-self: start;
  max-height: calc(100vh - 56px);
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding-right: 6px;
}
.docs-brand { padding: 4px 6px 0; }
.docs-kicker {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--brand);
}
.docs-brand h1 {
  margin: 6px 0 4px;
  font-size: 24px;
  color: var(--ink);
}
.docs-brand p { margin: 0; font-size: 12px; color: var(--ink-3); }
.docs-search {
  width: 100%;
  padding: 9px 12px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--surface);
  font-size: 13px;
  color: var(--ink);
  outline: none;
}
.docs-search:focus { border-color: var(--brand); box-shadow: 0 0 0 3px var(--brand-glow); }
.docs-nav { overflow-y: auto; padding: 2px 2px 12px; }
.docs-group { margin-bottom: 14px; }
.docs-group-title {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: var(--ink-light);
  text-transform: uppercase;
  padding: 6px 8px 4px;
}
.docs-link {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 10px;
  border-radius: 10px;
  text-decoration: none;
  border: 1px solid transparent;
  transition: background 0.15s, border-color 0.15s;
}
.docs-link:hover { background: var(--bg-soft); }
.docs-link.active {
  background: var(--brand-soft);
  border-color: color-mix(in srgb, var(--brand) 22%, transparent);
}
.docs-link-title {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink-2);
}
.docs-link.active .docs-link-title { color: var(--brand-strong); }
.docs-link-desc { font-size: 11.5px; color: var(--ink-light); line-height: 1.35; }
.docs-empty { font-size: 12px; color: var(--ink-3); padding: 8px; }

/* ---------------- 主区域 ---------------- */
.docs-main { min-width: 0; }
.docs-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 4px 16px;
  border-bottom: 1px solid var(--line);
  margin-bottom: 20px;
}
.docs-back {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--brand-strong);
  text-decoration: none;
  padding: 5px 10px;
  border-radius: 999px;
  background: var(--brand-soft);
  white-space: nowrap;
}
.docs-crumb { font-size: 12.5px; color: var(--ink-3); }
.docs-crumb i { font-style: normal; color: var(--ink-light); margin: 0 4px; }
.docs-badge {
  margin-left: auto;
  font-size: 11px;
  font-weight: 700;
  color: var(--accent-strong);
  background: var(--accent-soft);
  border-radius: 999px;
  padding: 3px 10px;
}

.docs-grid { display: grid; grid-template-columns: minmax(0, 1fr) 210px; gap: 28px; }

.docs-article {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 26px 32px 34px;
  box-shadow: var(--shadow-sm);
  min-width: 0;
}

/* ---------------- 右侧目录 ---------------- */
.docs-toc {
  position: sticky;
  top: 8px;
  align-self: start;
  max-height: calc(100vh - 80px);
  overflow-y: auto;
  font-size: 12.5px;
  padding: 4px 0 0 10px;
  border-left: 1px solid var(--line);
}
.docs-toc-title {
  font-weight: 700;
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink-light);
  margin-bottom: 8px;
}
.docs-toc-link {
  display: block;
  padding: 4px 6px;
  border-radius: 7px;
  color: var(--ink-3);
  text-decoration: none;
  line-height: 1.4;
  margin-bottom: 2px;
}
.docs-toc-link:hover { color: var(--brand-strong); background: var(--brand-soft); }
.docs-toc-link.sub { padding-left: 16px; font-size: 12px; }
.docs-toc-empty { color: var(--ink-light); }

/* ---------------- 上下篇 ---------------- */
.docs-pager {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-top: 20px;
}
.pager-card {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 180px;
  padding: 12px 16px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface);
  text-decoration: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.pager-card:hover { border-color: var(--brand); box-shadow: var(--shadow-sm); }
.pager-card span { font-size: 11px; color: var(--ink-light); }
.pager-card b { font-size: 13.5px; color: var(--ink-2); }
.pager-card.next { text-align: right; align-items: flex-end; }

.docs-missing {
  background: var(--surface);
  border: 1px dashed var(--line);
  border-radius: 16px;
  padding: 48px;
  text-align: center;
}
.docs-missing h2 { margin: 0 0 8px; color: var(--ink); }
.docs-missing p { color: var(--ink-3); margin: 0 0 16px; }
.btn {
  display: inline-block;
  padding: 9px 18px;
  border-radius: 10px;
  background: var(--brand);
  color: #fff;
  text-decoration: none;
  font-weight: 600;
  font-size: 13px;
}

/* ---------------- Markdown 渲染样式 ---------------- */
.docs-article :deep(h1),
.docs-article :deep(h2),
.docs-article :deep(h3),
.docs-article :deep(h4) {
  color: var(--ink);
  scroll-margin-top: 20px;
  line-height: 1.3;
}
.docs-article :deep(h1) {
  font-size: 26px;
  margin: 2px 0 14px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--line);
}
.docs-article :deep(h2) {
  font-size: 19px;
  margin: 30px 0 12px;
  padding-left: 10px;
  border-left: 4px solid var(--brand);
}
.docs-article :deep(h3) { font-size: 15.5px; margin: 20px 0 8px; color: var(--ink-2); }
.docs-article :deep(h4) { font-size: 14px; margin: 16px 0 6px; }
.docs-article :deep(p) { font-size: 13.5px; line-height: 1.75; color: var(--ink-2); margin: 10px 0; }
.docs-article :deep(a) { color: var(--brand-strong); text-decoration: none; border-bottom: 1px solid color-mix(in srgb, var(--brand) 30%, transparent); }
.docs-article :deep(ul),
.docs-article :deep(ol) { margin: 10px 0; padding-left: 22px; }
.docs-article :deep(li) { font-size: 13.5px; line-height: 1.75; color: var(--ink-2); margin: 4px 0; }
.docs-article :deep(strong) { color: var(--ink); font-weight: 700; }
.docs-article :deep(blockquote) {
  margin: 14px 0;
  padding: 10px 16px;
  border-left: 4px solid var(--accent);
  background: var(--accent-soft);
  border-radius: 0 8px 8px 0;
  color: var(--ink-2);
  font-size: 13px;
  line-height: 1.7;
}
.docs-article :deep(code) {
  background: var(--bg-soft);
  border: 1px solid var(--line);
  border-radius: 5px;
  padding: 1px 6px;
  font-size: 12.5px;
  color: var(--brand-strong);
  font-family: 'JetBrains Mono', 'Cascadia Code', Consolas, monospace;
}
.docs-article :deep(pre) {
  margin: 14px 0;
  padding: 14px 16px;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 10px;
  overflow-x: auto;
  font-size: 12.5px;
  line-height: 1.6;
}
.docs-article :deep(pre code) {
  background: none;
  border: none;
  padding: 0;
  color: inherit;
  font-size: inherit;
}
.docs-article :deep(.md-mermaid) { margin: 14px 0; }
.docs-article :deep(.md-mermaid-head) { font-size: 12px; font-weight: 700; color: var(--brand-strong); margin-bottom: 5px; display: flex; align-items: center; gap: 8px; }
.docs-article :deep(.mermaid-render:empty) { display: none; }
.docs-article :deep(.mermaid-render) { background: #fff; border: 1px solid var(--line); border-radius: 10px; padding: 14px; overflow-x: auto; }
.docs-article :deep(.mermaid-render svg) { max-width: 100%; height: auto; }
.docs-article :deep(.md-mermaid.rendered pre.mermaid-src) { display: none; }
.docs-article :deep(.md-mermaid pre.mermaid-src) { border: 1px dashed var(--brand); background: #f8fafc; color: var(--ink-2); }
.docs-article :deep(.md-mermaid-error) { display: flex; align-items: center; gap: 10px; font-size: 12.5px; color: #a03028; }
.docs-article :deep(.md-mermaid-retry) { padding: 3px 10px; border: 1px solid currentColor; border-radius: 6px; background: transparent; color: inherit; font-size: 11.5px; cursor: pointer; }
.docs-article :deep(.md-code-wrap) {
  margin: 14px 0;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid #1e293b;
}
.docs-article :deep(.md-code-head) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 12px;
  background: #1e293b;
  color: #94a3b8;
  font-size: 11.5px;
}
.docs-article :deep(.md-code-head .md-copy),
.docs-article :deep(.md-code-head .md-dl) {
  background: #334155;
  color: #e2e8f0;
  border: none;
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 11px;
  cursor: pointer;
}
.docs-article :deep(.md-code-wrap .md-code) { margin: 0; border-radius: 0; }
.docs-article :deep(.md-terminal),
.docs-article :deep(.md-tree) {
  background: #0b1220;
  color: #d1fae5;
  border-radius: 10px;
  padding: 14px 16px;
  overflow-x: auto;
  font-size: 12.5px;
  line-height: 1.6;
}
.docs-article :deep(.md-table) {
  width: 100%;
  border-collapse: collapse;
  margin: 14px 0;
  font-size: 12.8px;
  display: block;
  overflow-x: auto;
}
.docs-article :deep(.md-table th) {
  text-align: left;
  background: var(--bg-soft);
  color: var(--ink);
  font-weight: 700;
  padding: 8px 12px;
  border: 1px solid var(--line);
  white-space: nowrap;
}
.docs-article :deep(.md-table td) {
  padding: 7px 12px;
  border: 1px solid var(--line);
  color: var(--ink-2);
  vertical-align: top;
}
.docs-article :deep(.md-table tbody tr:nth-child(even)) { background: var(--surface-alt); }
.docs-article :deep(hr) { border: none; border-top: 1px solid var(--line); margin: 22px 0; }
.docs-article :deep(.md-alert) {
  margin: 14px 0;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.7;
  border-left: 4px solid var(--brand);
  background: var(--brand-soft);
  color: var(--ink-2);
}
.docs-article :deep(.md-alert.warn) { border-color: var(--warning); background: var(--warning-soft); }
.docs-article :deep(.md-alert.error) { border-color: var(--danger); background: var(--danger-soft); }
.docs-article :deep(.md-alert.success) { border-color: var(--success); background: var(--success-soft); }
.docs-article :deep(.md-fold) {
  margin: 14px 0;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 14px;
  background: var(--surface-alt);
}
.docs-article :deep(.md-fold summary) { cursor: pointer; font-size: 13px; color: var(--ink-2); font-weight: 600; }
.docs-article :deep(.md-kv) {
  margin: 12px 0;
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
}
.docs-article :deep(.md-kv-row) { display: flex; gap: 12px; padding: 7px 12px; font-size: 12.8px; border-top: 1px solid var(--line); }
.docs-article :deep(.md-kv-row:first-child) { border-top: none; }
.docs-article :deep(.md-kv-row b) { min-width: 120px; color: var(--ink); }
.docs-article :deep(.md-timeline) { margin: 12px 0; }
.docs-article :deep(.md-tl-item) { display: flex; gap: 10px; font-size: 13px; padding: 4px 0; color: var(--ink-2); }
.docs-article :deep(.md-tl-dot) { width: 8px; height: 8px; border-radius: 50%; background: var(--brand); margin-top: 7px; flex: none; }
.docs-article :deep(.md-badge) {
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  color: #fff;
  background: var(--brand);
  border-radius: 999px;
  padding: 1px 8px;
}
.docs-article :deep(.md-tag) {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  color: var(--accent-strong);
  background: var(--accent-soft);
  border-radius: 999px;
  padding: 1px 8px;
}
.docs-article :deep(.md-tasks) { list-style: none; padding-left: 6px; }

@media (max-width: 1080px) {
  .docs-grid { grid-template-columns: minmax(0, 1fr); }
  .docs-toc { display: none; }
}
@media (max-width: 860px) {
  .docs-page { grid-template-columns: 1fr; }
  .docs-side { position: static; max-height: none; }
  .docs-article { padding: 20px; }
}
</style>
