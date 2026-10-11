<!--
 占位符插入条（提示词模板编辑共用）。
 - 下拉框列出本场景可用占位符（key + 中文解释），选中即在光标处插入并保留焦点；
 - “正文已用”常驻解析正文里的 {xxx}，输入再多也不会看不到；未知占位符标红提醒。
-->
<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'

import type { PlaceholderDef } from '@/components/placeholders'

const props = defineProps<{
  placeholders: PlaceholderDef[]
  content: string
  textareaRef?: HTMLTextAreaElement | null
}>()
const emit = defineEmits<{ (e: 'insert', value: string): void }>()

const pick = ref('')

const used = computed(() => {
  const known = new Map(props.placeholders.map((p) => [p.key, p.desc]))
  const found = [...(props.content || '').matchAll(/\{\s*(\w+)\s*\}/g)].map((m) => m[1])
  return [...new Set(found)].map((k) => ({ key: k, desc: known.get(k) ?? '', known: known.has(k) }))
})

function insert() {
  const token = pick.value
  if (!token) return
  const ta = props.textareaRef
  const cur = props.content || ''
  if (!ta) {
    emit('insert', cur ? `${cur} {${token}}` : `{${token}}`)
  } else {
    const start = ta.selectionStart ?? cur.length
    const end = ta.selectionEnd ?? cur.length
    emit('insert', `${cur.slice(0, start)}{${token}}${cur.slice(end)}`)
    const pos = start + token.length + 2
    nextTick(() => {
      ta.focus()
      ta.setSelectionRange(pos, pos)
    })
  }
  pick.value = ''
}
</script>

<template>
  <div class="ph-bar">
    <select v-model="pick" class="ph-select" @change="insert">
      <option value="">＋ 插入占位符…</option>
      <option v-for="p in placeholders" :key="p.key" :value="p.key">
        {{ '{' + p.key + '}' }} · {{ p.desc }}
      </option>
    </select>
    <span class="ph-used">
      正文已用：
      <template v-if="!used.length">暂无</template>
      <template v-else>
        <span v-for="u in used" :key="u.key" class="ph-tag" :class="{ unknown: !u.known }" :title="u.known ? u.desc : '未知占位符，生成时不会被替换，请检查拼写'">
          {{ '{' + u.key + '}' }}{{ u.known ? '' : '（未知）' }}
        </span>
      </template>
    </span>
  </div>
</template>

<style scoped>
.ph-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  background: var(--bg-soft);
  border: 1px dashed var(--line);
  border-radius: 10px;
  padding: 7px 10px;
}
.ph-select {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 12.5px;
  font-weight: 600;
  background: var(--surface);
  color: var(--brand-strong);
  cursor: pointer;
  max-width: 100%;
}
.ph-used {
  font-size: 12px;
  color: var(--ink-3);
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.ph-tag {
  background: var(--brand-soft);
  color: var(--brand-strong);
  border-radius: 999px;
  padding: 1px 9px;
  font-weight: 600;
  white-space: nowrap;
}
.ph-tag.unknown {
  background: #fee2e2;
  color: #b91c1c;
}
</style>
