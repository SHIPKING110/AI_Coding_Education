<template>
  <div v-if="store.list.length" class="qb-ai-dock">
    <article v-for="task in store.list" :key="task.id" class="qb-ai-card" :class="task.status">
      <header>
        <strong>
          {{ task.kind === 'tag' ? 'AI 知识点打标' : 'AI 校准' }} ·
          {{ task.meta?.set_name || '题库' }}
        </strong>
        <button v-if="task.status !== 'running'" aria-label="关闭任务卡片" @click="store.dismiss(task.id)">
          ×
        </button>
      </header>
      <div class="qb-ai-progress">
        <div class="bar"><i :style="{ width: percent(task) + '%' }" /></div>
        <span>{{ task.progress }}/{{ task.total }}</span>
      </div>
      <p class="qb-ai-msg">{{ statusText(task) }}</p>
    </article>
  </div>
</template>

<script setup lang="ts">
import type { QbAiTask } from '@/api/questionBank'
import { useQbAiTasksStore } from '@/stores/qbAiTasks'

const store = useQbAiTasksStore()

function percent(task: QbAiTask): number {
  if (!task.total) return task.status === 'done' ? 100 : 0
  return Math.min(100, Math.round((task.progress / task.total) * 100))
}

function statusText(task: QbAiTask): string {
  if (task.status === 'error') return task.error || '任务失败'
  if (task.status === 'done') return '已完成，题库页已刷新'
  return task.message || '处理中…'
}
</script>

<style scoped>
.qb-ai-dock {
  position: fixed;
  right: 18px;
  bottom: 18px;
  z-index: 90;
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 300px;
}
.qb-ai-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 12px 14px;
  box-shadow: 0 12px 30px rgba(15, 23, 42, 0.16);
}
.qb-ai-card.done {
  border-color: #99f6e4;
}
.qb-ai-card.error {
  border-color: #fecaca;
}
header {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
}
header strong {
  font-size: 12.5px;
  color: #0f172a;
}
header button {
  border: none;
  background: none;
  cursor: pointer;
  font-size: 15px;
  color: #94a3b8;
}
.qb-ai-progress {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 8px 0 4px;
}
.bar {
  flex: 1;
  height: 6px;
  background: #f1f5f9;
  border-radius: 999px;
  overflow: hidden;
}
.bar i {
  display: block;
  height: 100%;
  background: #0d9488;
  transition: width 0.4s;
}
.qb-ai-progress span {
  font-size: 11px;
  color: #64748b;
}
.error .bar i {
  background: #ef4444;
}
.qb-ai-msg {
  margin: 0;
  font-size: 11.5px;
  color: #64748b;
  word-break: break-all;
}
</style>