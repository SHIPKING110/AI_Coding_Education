<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  total: number
  page: number
  pageSize: number
}>()

const emit = defineEmits<{
  (e: 'update:page', page: number): void
}>()

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))

const pageNumbers = computed(() => {
  const current = Math.min(props.page, totalPages.value)
  const pages: (number | '...')[] = []
  const start = Math.max(1, current - 2)
  const end = Math.min(totalPages.value, current + 2)
  if (start > 1) {
    pages.push(1)
    if (start > 2) pages.push('...')
  }
  for (let i = start; i <= end; i++) pages.push(i)
  if (end < totalPages.value) {
    if (end < totalPages.value - 1) pages.push('...')
    pages.push(totalPages.value)
  }
  return pages
})

function go(page: number) {
  if (page < 1 || page > totalPages.value || page === props.page) return
  emit('update:page', page)
}
</script>

<template>
  <div v-if="total > 0" class="pager">
    <span class="pager-total">共 {{ total }} 条</span>
    <div class="pager-nav">
      <button class="pg-btn" :disabled="page <= 1" @click="go(page - 1)">上一页</button>
      <template v-for="(p, i) in pageNumbers" :key="i">
        <span v-if="p === '...'" class="pg-ellipsis">…</span>
        <button
          v-else
          class="pg-btn"
          :class="{ active: p === page }"
          @click="go(p)"
        >
          {{ p }}
        </button>
      </template>
      <button class="pg-btn" :disabled="page >= totalPages" @click="go(page + 1)">下一页</button>
    </div>
    <span class="pager-info">第 {{ page }} / {{ totalPages }} 页</span>
  </div>
</template>

<style scoped>
.pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
  flex-wrap: wrap;
}
.pager-total {
  color: var(--ink-3);
  font-size: 13px;
}
.pager-nav {
  display: flex;
  align-items: center;
  gap: 6px;
}
.pg-btn {
  min-width: 32px;
  padding: 6px 11px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-2);
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.pg-btn:hover:not(:disabled):not(.active) {
  border-color: var(--brand);
  color: var(--brand);
}
.pg-btn.active {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  border-color: transparent;
  color: #fff;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}
.pg-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.pg-ellipsis {
  color: var(--ink-3);
  padding: 0 2px;
}
.pager-info {
  color: var(--ink-3);
  font-size: 13px;
}
</style>
