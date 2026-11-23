<script setup lang="ts">
import { RouterLink } from 'vue-router'

defineProps<{ active: 'assignments' | 'bank' }>()
</script>

<template>
  <div class="asg-tabs" role="tablist" aria-label="AI 习题模块">
    <RouterLink to="/assignments" class="asg-tab" :class="{ active: active === 'assignments' }" role="tab">
      作业
    </RouterLink>
    <RouterLink to="/question-bank" class="asg-tab" :class="{ active: active === 'bank' }" role="tab">
      题库
    </RouterLink>
  </div>
</template>

<style scoped>
.asg-tabs {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  margin-bottom: 14px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 12px;
  box-shadow: var(--shadow-xs);
}
.asg-tab {
  padding: 7px 20px;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 700;
  color: var(--ink-3);
  text-decoration: none;
  transition: background 0.15s, color 0.15s;
}
.asg-tab:hover {
  color: var(--ink);
  background: var(--bg-soft);
}
.asg-tab.active {
  color: #fff;
  background: var(--brand-strong);
}
.asg-tab:focus-visible {
  outline: 2px solid var(--brand);
  outline-offset: 2px;
}
</style>

