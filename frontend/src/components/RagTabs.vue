<script setup lang="ts">
import { useRoute } from 'vue-router'

const route = useRoute()

const tabs = [
  { to: '/rag/overview', group: 'knowledge', label: '总览' },
  { to: '/rag/assets', group: 'knowledge', label: '知识资产' },
  { to: '/rag/routes', group: 'knowledge', label: '路由测试' },
  { to: '/rag/eval', group: 'knowledge', label: '评测' },
  { to: '/rag/settings', group: 'knowledge', label: '设置' },
  { to: '/rag/traces', group: 'observability', label: '检索追踪' },
  { to: '/rag/runs', group: 'observability', label: '任务监控' },
  { to: '/rag/sessions', group: 'observability', label: '会话观测' },
  { to: '/rag/parent-sessions', group: 'observability', label: '家长会话' },
]

function isActive(to: string) {
  return route.path === to || route.path.startsWith(to + '/')
}
</script>

<template>
  <nav class="rag-tabs">
    <RouterLink
      v-for="(t, i) in tabs"
      :key="t.to"
      :to="t.to"
      class="rag-tab"
      :class="{ active: isActive(t.to), 'group-start': i === 5 }"
    >
      {{ t.label }}
    </RouterLink>
  </nav>
</template>

<style scoped>
.rag-tabs {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin: 0 0 16px;
  padding: 6px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--surface);
}
.rag-tab {
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-2);
  text-decoration: none;
  transition: all 0.15s;
}
.rag-tab:hover {
  background: var(--brand-soft);
  color: var(--brand-strong);
}
.rag-tab.group-start {
  margin-left: 8px;
  border-left: 1px solid var(--line);
  border-radius: 0 8px 8px 0;
  padding-left: 14px;
}
.rag-tab.active {
  background: var(--brand);
  color: #fff;
}
</style>