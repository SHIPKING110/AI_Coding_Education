<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'

interface Option {
  id: string
  label: string
}

const props = defineProps<{
  modelValue: string
  options: Option[]
  placeholder?: string
  /** 同一 group 的多个下拉一次只展开一个（互斥展开） */
  group?: string
}>()

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

// 模块级共享：记录每个 group 当前展开的实例标识（同组互斥）
const groupOpened = reactive<Record<string, string>>({})
let seq = 0
const uid = `ssel-${++seq}`

const open = ref(false)
const query = ref('')

watch(
  () => (props.group ? groupOpened[props.group] : ''),
  (k) => {
    // 同组其他实例展开时，关闭自己
    if (props.group && k && k !== uid) open.value = false
  },
)

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return props.options
  return props.options.filter((o) => o.label.toLowerCase().includes(q))
})

const current = computed(() => props.options.find((o) => o.id === props.modelValue))

function toggle() {
  if (open.value) {
    open.value = false
    if (props.group && groupOpened[props.group] === uid) groupOpened[props.group] = ''
    return
  }
  if (props.group) groupOpened[props.group] = uid
  open.value = true
  query.value = ''
}

function select(id: string) {
  emit('update:modelValue', id)
  open.value = false
}

function clear() {
  emit('update:modelValue', '')
  open.value = false
}

// 外部清空/变化时关闭下拉
watch(
  () => props.modelValue,
  () => {
    open.value = false
  },
)
</script>

<template>
  <div class="ssel">
    <button type="button" class="ssel-trigger" :class="{ active: modelValue }" @click="toggle">
      <span class="ssel-label">{{ current ? current.label : placeholder || '请选择' }}</span>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6" /></svg>
    </button>

    <div v-if="open" class="ssel-drop" @click.stop>
      <div class="ssel-search">
        <input v-model="query" placeholder="搜索…" @keyup.enter="filtered[0] && select(filtered[0].id)" />
      </div>
      <div class="ssel-list">
        <button
          v-for="o in filtered"
          :key="o.id"
          type="button"
          class="ssel-opt"
          :class="{ picked: o.id === modelValue }"
          @click="select(o.id)"
        >
          <span>{{ o.label }}</span>
          <svg v-if="o.id === modelValue" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
        </button>
        <div v-if="filtered.length === 0" class="ssel-empty">无匹配项</div>
      </div>
      <div class="ssel-foot">
        <button v-if="modelValue" type="button" class="ssel-clear" @click="clear">清除选择</button>
        <span v-else />
      </div>
    </div>
  </div>
</template>

<style scoped>
.ssel {
  position: relative;
}
.ssel-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 11px;
  min-width: 150px;
  max-width: 220px;
  border: 1px solid var(--line);
  border-radius: 9px;
  background: var(--surface);
  cursor: pointer;
  font-size: 13.5px;
  color: var(--ink-2);
  transition: border-color 0.15s;
  justify-content: space-between;
  box-sizing: border-box;
}
.ssel-trigger:hover {
  border-color: var(--brand);
}
.ssel-trigger.active .ssel-label {
  color: var(--ink);
  font-weight: 600;
}
.ssel-trigger svg {
  width: 14px;
  height: 14px;
  color: var(--ink-3);
  flex-shrink: 0;
}
.ssel-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ssel-drop {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  z-index: 40;
  width: 240px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 11px;
  box-shadow: var(--shadow-lg);
  overflow: hidden;
}
.ssel-search {
  padding: 8px;
  border-bottom: 1px solid var(--line);
}
.ssel-search input {
  width: 100%;
  box-sizing: border-box;
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  font-size: 13px;
}
.ssel-search input:focus {
  outline: none;
  border-color: var(--brand);
}
.ssel-list {
  max-height: 220px;
  overflow: auto;
  padding: 4px;
}
.ssel-opt {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  border: none;
  background: transparent;
  border-radius: 7px;
  font-size: 13.5px;
  color: var(--ink-2);
  cursor: pointer;
  text-align: left;
}
.ssel-opt:hover {
  background: var(--brand-soft);
}
.ssel-opt.picked {
  color: var(--brand-strong);
  font-weight: 600;
}
.ssel-opt svg {
  width: 14px;
  height: 14px;
}
.ssel-empty {
  padding: 18px 0;
  text-align: center;
  color: var(--ink-3);
  font-size: 13px;
}
.ssel-foot {
  display: flex;
  justify-content: flex-end;
  padding: 6px 9px;
  border-top: 1px solid var(--line);
}
.ssel-clear {
  border: none;
  background: none;
  color: var(--danger);
  font-size: 12px;
  cursor: pointer;
}
</style>