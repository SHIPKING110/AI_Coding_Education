<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { getSharedConversation, type SharedConversation } from '@/api/agent'
import { renderMarkdown } from '@/utils/markdown'

const route = useRoute()
const loading = ref(true)
const error = ref('')
const data = ref<SharedConversation | null>(null)

onMounted(async () => {
  try {
    data.value = await getSharedConversation(String(route.params.token))
  } catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '分享链接无效或已失效'
  } finally {
    loading.value = false
  }
})

function fmt(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <div class="share-page">
    <header class="share-hero">
      <span class="share-mark">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z" /></svg>
      </span>
      <div class="share-hero-text">
        <h1>{{ data?.title || '对话分享' }}</h1>
        <p v-if="data">只读分享 · {{ data.items.length }} 条消息<template v-if="fmt(data.created_at)"> · {{ fmt(data.created_at) }}</template></p>
        <p v-else>智能编程教务 · Agent 工作台</p>
      </div>
    </header>

    <main class="share-body">
      <p v-if="loading" class="share-empty">加载中…</p>
      <p v-else-if="error" class="share-empty err">{{ error }}</p>
      <template v-else>
        <div v-for="(m, i) in data?.items" :key="i" class="share-msg" :class="m.role">
          <div class="share-avatar" :class="m.role">
            <svg v-if="m.role === 'assistant'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z" /></svg>
            <span v-else>我</span>
          </div>
          <div class="share-bubble" :class="m.role">
            <div v-if="m.role === 'assistant'" v-html="renderMarkdown(m.content)" />
            <p v-else>{{ m.content }}</p>
          </div>
        </div>
        <p v-if="!data?.items.length" class="share-empty">该对话暂无内容</p>
      </template>
    </main>

    <footer class="share-foot">由 智能编程教务 · Agent 工作台 生成</footer>
  </div>
</template>

<style scoped>
.share-page { min-height: 100vh; background: var(--bg, #f4f6fb); display: flex; flex-direction: column; align-items: center; padding: 0 16px 40px; }
.share-hero {
  width: 100%; max-width: 860px; display: flex; align-items: center; gap: 14px;
  margin: 28px 0 16px; padding: 18px 22px; border-radius: 16px;
  background: linear-gradient(135deg, var(--brand, #6366f1), var(--accent, #06b6d4)); color: #fff;
  box-shadow: 0 10px 30px rgba(99, 102, 241, 0.28);
}
.share-mark { width: 42px; height: 42px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; border-radius: 12px; background: rgba(255, 255, 255, 0.2); }
.share-mark svg { width: 22px; height: 22px; }
.share-hero-text h1 { margin: 0; font-size: 18px; font-weight: 700; }
.share-hero-text p { margin: 4px 0 0; font-size: 12.5px; opacity: 0.9; }
.share-body {
  width: 100%; max-width: 860px; flex: 1; background: var(--surface, #fff); border: 1px solid var(--line, #e5e7ef);
  border-radius: 16px; padding: 22px; display: flex; flex-direction: column; gap: 18px;
}
.share-msg { display: flex; gap: 12px; }
.share-msg.user { flex-direction: row-reverse; }
.share-avatar {
  width: 34px; height: 34px; flex-shrink: 0; display: flex; align-items: center; justify-content: center;
  border-radius: 10px; font-size: 12px; font-weight: 700; color: #fff; background: var(--brand, #6366f1);
}
.share-avatar.user { background: linear-gradient(135deg, #f59e0b, #ef4444); }
.share-avatar svg { width: 17px; height: 17px; }
.share-bubble { max-width: 76%; padding: 12px 16px; border-radius: 14px; font-size: 14px; line-height: 1.7; color: var(--ink, #1f2937); background: var(--bg-soft, #f6f7fb); }
.share-bubble.user { background: linear-gradient(135deg, var(--brand, #6366f1), var(--accent, #06b6d4)); color: #fff; }
.share-bubble p { margin: 0; white-space: pre-wrap; }
.share-bubble :deep(p) { margin: 4px 0; }
.share-bubble :deep(pre) { background: #0f172a; color: #e2e8f0; padding: 10px 12px; border-radius: 8px; overflow-x: auto; font-size: 12.5px; }
.share-bubble :deep(code) { background: rgba(99, 102, 241, 0.12); padding: 1px 5px; border-radius: 4px; font-size: 12.5px; }
.share-bubble :deep(.md-table) { border-collapse: collapse; margin: 8px 0; }
.share-bubble :deep(.md-table th), .share-bubble :deep(.md-table td) { border: 1px solid var(--line, #e5e7ef); padding: 6px 10px; }
.share-empty { text-align: center; color: var(--ink-3, #94a3b8); font-size: 13px; padding: 30px 0; }
.share-empty.err { color: var(--danger, #ef4444); }
.share-foot { margin-top: 18px; font-size: 12px; color: var(--ink-3, #94a3b8); }
</style>
