<script setup lang="ts">
/**
 * 页面页头 v2：左侧品牌色竖条 + 英文眉题 + 大标题 + 描述，置于圆角卡片内；
 * 右侧操作区。9 个主要模块共用。
 * 用法：<PageHead title="学员管理" sub="..." eyebrow="STUDENTS"><template #actions>…</template></PageHead>
 */
defineProps<{
  title: string
  sub?: string
  eyebrow?: string
}>()
</script>

<template>
  <header class="page-head v2">
    <div class="head-main">
      <div v-if="eyebrow" class="eyebrow-line">{{ eyebrow }}</div>
      <h1>{{ title }}</h1>
      <p v-if="sub || $slots.sub" class="page-sub">
        <slot name="sub">{{ sub }}</slot>
      </p>
    </div>
    <div v-if="$slots.actions" class="head-actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped>
.page-head.v2 {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 18px;
  padding: 14px 20px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  box-shadow: var(--shadow-sm);
}
.head-main {
  flex: 1;
  min-width: 0;
}
.eyebrow-line {
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.26em;
  color: var(--brand-strong);
  margin-bottom: 3px;
}
h1 {
  font-size: 21px;
  font-weight: 800;
  letter-spacing: 0.02em;
  line-height: 1.25;
}
.page-sub {
  color: var(--ink-3);
  font-size: 12.5px;
  margin-top: 3px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.head-actions {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-shrink: 0;
}
</style>
