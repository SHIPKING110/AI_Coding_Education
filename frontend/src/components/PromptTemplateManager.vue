<script setup lang="ts">
/**
 * 提示词模板管理弹窗（按场景复用）。
 * scene: feedback 课后反馈 / report 报告总结 / evaluation 学员评估。
 */
import { computed, nextTick, ref, watch } from 'vue'

import {
  createPromptTemplate,
  deletePromptTemplate,
  listPromptTemplates,
  publishPromptTemplate,
  unpublishPromptTemplate,
  updatePromptTemplate,
  type PromptTemplateOut,
} from '@/api/prompt'
import { useAuthStore } from '@/stores/auth'

const props = defineProps<{ visible: boolean; scene: 'feedback' | 'report' | 'evaluation'; title: string }>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'changed'): void }>()

const SCENE_HINT: Record<string, string> = {
  feedback: '模板用于 AI 生成课堂评价，可用占位符：{student_name} {class_name} {subject} {topic} {content} {performance} {homework} {evaluation}。',
  report: '日报 / 周报 / 季度总结 / 年度总结共用此模板库，下方可用“类型筛选”快速定位对应预设；所选模板内容会作为写作风格要求叠加到 AI 生成中。',
  evaluation: '模板用于 AI 生成学员评估，所选模板内容会作为写作风格要求叠加到生成中。',
}

const auth = useAuthStore()
const isAdmin = computed(() => auth.user?.role === 'admin')
const loading = ref(false)
const error = ref('')
const items = ref<PromptTemplateOut[]>([])
const editingId = ref('')
const formName = ref('')
const formContent = ref('')
const formError = ref('')
const formNotice = ref('')
const saving = ref(false)
const kindFilter = ref('全部')
const expanded = ref(new Set<string>())
const formRef = ref<HTMLElement | null>(null)

function toggleExpand(id: string) {
  const s = new Set(expanded.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  expanded.value = s
}

/** report 场景按名称前缀二次分组：日报 / 周报 / 季度总结 / 年度总结 / 通用 */
function kindOf(t: PromptTemplateOut): string {
  if (props.scene !== 'report') return '全部'
  const n = t.name || ''
  if (n.includes('日报')) return '日报'
  if (n.includes('周报')) return '周报'
  if (n.includes('季度')) return '季度总结'
  if (n.includes('年度')) return '年度总结'
  return '通用'
}
const kindOptions = computed(() => {
  if (props.scene !== 'report') return ['全部']
  const set = new Set(items.value.map(kindOf))
  return ['全部', '日报', '周报', '季度总结', '年度总结', '通用'].filter((k) => k === '全部' || set.has(k))
})
const filtered = computed(() =>
  kindFilter.value === '全部' ? items.value : items.value.filter((t) => kindOf(t) === kindFilter.value),
)
const groups = computed(() => ({
  system: filtered.value.filter((t) => t.scope === 'system'),
  published: filtered.value.filter((t) => t.scope === 'published'),
  personal: filtered.value.filter((t) => t.scope === 'personal'),
}))
const editing = computed(() => items.value.find((t) => t.id === editingId.value) ?? null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    items.value = await listPromptTemplates(props.scene)
  } catch {
    error.value = '提示词模板加载失败'
  } finally {
    loading.value = false
  }
}

watch(() => props.visible, (v) => {
  if (v) {
    editingId.value = ''
    formError.value = ''
    formNotice.value = ''
    kindFilter.value = '全部'
    expanded.value = new Set()
    void load()
  }
})

function scrollToForm() {
  nextTick(() => formRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
}

function startCreate() {
  editingId.value = ''
  formName.value = ''
  formContent.value = ''
  formError.value = ''
  formNotice.value = ''
  scrollToForm()
}

function startEdit(t: PromptTemplateOut) {
  editingId.value = t.id
  formName.value = t.name
  formContent.value = t.content
  formError.value = ''
  // 非管理员点系统/已发布模板的编辑：提前说明保存时会存为“我的”副本，避免 403 困惑
  formNotice.value =
    !isAdmin.value && t.scope !== 'personal'
      ? '该模板为系统 / 全校模板，仅管理员可直接修改；你保存时会自动存为「我的」个人副本，不影响原模板。'
      : ''
  scrollToForm()
}

function cancelEdit() {
  editingId.value = ''
  formName.value = ''
  formContent.value = ''
  formError.value = ''
  formNotice.value = ''
}

async function save() {
  formError.value = ''
  formNotice.value = ''
  const name = formName.value.trim()
  const content = formContent.value.trim()
  if (!name) {
    formError.value = '请填写模板名称'
    return
  }
  if (!content) {
    formError.value = '请填写模板内容'
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      try {
        await updatePromptTemplate(editing.value.id, { name, content })
        formNotice.value = '已保存修改'
      } catch (e: any) {
        const status = e?.response?.status
        const detail = e?.response?.data?.detail || ''
        // 非管理员编辑系统/全校模板被 403：自动降级为新建个人副本，保证“默认模板也能改”
        if (status === 403 && editing.value.scope !== 'personal') {
          const copy = await createPromptTemplate({
            name: name === editing.value.name ? `${name}（我的副本）` : name,
            content,
            scene: props.scene,
          })
          editingId.value = copy.id
          formName.value = copy.name
          formNotice.value = '原模板仅管理员可改，已为你另存为「我的」个人副本并可直接选用'
        } else {
          formError.value = detail || '保存失败'
          return
        }
      }
    } else {
      const created = await createPromptTemplate({ name, content, scene: props.scene })
      editingId.value = created.id
      formNotice.value = '已创建，可继续编辑或点“新建模板”再建一个'
    }
    await load()
    emit('changed')
  } catch (e: any) {
    formError.value = e?.response?.data?.detail || '保存失败'
  } finally {
    saving.value = false
  }
}

async function remove(t: PromptTemplateOut) {
  if (t.scope === 'system') return
  if (!window.confirm(`确认删除模板「${t.name}」？`)) return
  try {
    await deletePromptTemplate(t.id)
    if (editingId.value === t.id) cancelEdit()
    await load()
    emit('changed')
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '删除失败'
  }
}

async function togglePublish(t: PromptTemplateOut) {
  try {
    if (t.scope === 'published') await unpublishPromptTemplate(t.id)
    else await publishPromptTemplate(t.id)
    await load()
    emit('changed')
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '操作失败'
  }
}

function scopeTag(t: PromptTemplateOut) {
  return t.scope === 'system' ? '系统' : t.scope === 'published' ? '全校' : '我的'
}
</script>

<template>
  <div v-if="visible" class="tpl-mask" @click.self="emit('close')">
    <div class="tpl-modal">
      <div class="tpl-head">
        <div>
          <h2>{{ title }}</h2>
          <p class="tpl-sub">{{ items.length }} 个模板 · 系统模板可直接用，改不动会自动存副本</p>
        </div>
        <div class="tpl-head-ops">
          <button class="tpl-new" type="button" @click="startCreate" title="新建一个模板">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
            新建模板
          </button>
          <button class="tpl-x" type="button" @click="emit('close')">✕</button>
        </div>
      </div>
      <p class="tpl-hint">
        {{ SCENE_HINT[scene] }}系统模板开箱即用（仅管理员可直接改，其他人点“编辑”后保存会自动存为“我的”副本）；
        「我的」模板仅自己可见。
        <template v-if="isAdmin">管理员可将模板「发布」给全校教师使用。</template>
        <template v-else>发布需管理员操作。</template>
      </p>
      <div v-if="scene === 'report' && kindOptions.length > 2" class="tpl-kinds">
        <button
          v-for="k in kindOptions"
          :key="k"
          type="button"
          class="tpl-kind"
          :class="{ on: kindFilter === k }"
          @click="kindFilter = k"
        >{{ k }}</button>
      </div>
      <p v-if="error" class="tpl-error">{{ error }}</p>
      <div v-if="loading" class="tpl-loading">加载中…</div>
      <template v-else>
        <template v-for="(group, key) in groups" :key="key">
          <div v-if="group.length" class="tpl-group">
            <div class="tpl-group-title">
              {{ key === 'system' ? '系统模板' : key === 'published' ? '已发布（全校）' : '我的模板' }}
              <span class="tpl-group-count">{{ group.length }}</span>
            </div>
            <div v-for="t in group" :key="t.id" class="tpl-item" :class="{ active: editingId === t.id }">
              <div class="tpl-item-head">
                <strong>{{ t.name }}</strong>
                <span class="tpl-tag" :class="t.scope">{{ scopeTag(t) }}</span>
                <span v-if="editingId === t.id" class="tpl-editing-flag">编辑中</span>
                <button class="tpl-expand" type="button" @click="toggleExpand(t.id)">
                  {{ expanded.has(t.id) ? '收起 ▲' : '展开全文 ▼' }}
                </button>
              </div>
              <p class="tpl-item-content" :class="{ clamp: !expanded.has(t.id) }">{{ t.content }}</p>
              <div class="tpl-item-ops">
                <button class="mini-btn" type="button" @click="startEdit(t)">{{ editingId === t.id ? '正在编辑…' : '编辑' }}</button>
                <button v-if="t.scope !== 'system'" class="mini-btn danger" type="button" @click="remove(t)">删除</button>
                <button v-if="isAdmin && (t.scope === 'personal' || t.scope === 'published')" class="mini-btn" type="button" @click="togglePublish(t)">
                  {{ t.scope === 'published' ? '取消发布' : '发布给全校' }}
                </button>
              </div>
            </div>
          </div>
        </template>
        <div v-if="!filtered.length" class="tpl-empty">该分类暂无模板，点击右上「新建模板」创建</div>
      </template>
      <div ref="formRef" class="tpl-form" :class="{ editing: !!editing }">
        <div class="tpl-form-head">
          <h3>
            <span class="tpl-form-dot" :class="{ editing: !!editing }" />
            {{ editing ? `编辑模板 · ${editing.name}` : '新建模板' }}
          </h3>
          <button v-if="editing" class="tpl-switch-new" type="button" @click="startCreate" title="不改这个了，新建一个">
            ＋ 切换为新建
          </button>
        </div>
        <label class="tpl-field">
          <span>模板名称</span>
          <input v-model="formName" type="text" placeholder="如：鼓励成长型" />
        </label>
        <label class="tpl-field">
          <span>模板正文</span>
          <textarea v-model="formContent" rows="6" placeholder="模板正文（反馈场景可用 {student_name} 等占位符）" />
        </label>
        <p v-if="formNotice" class="tpl-notice">{{ formNotice }}</p>
        <p v-if="formError" class="tpl-error">{{ formError }}</p>
        <div class="tpl-form-ops">
          <button v-if="editing" class="mini-btn" type="button" @click="cancelEdit">取消编辑</button>
          <button class="mini-btn ghost" type="button" @click="startCreate">{{ editing ? '清空并新建' : '清空' }}</button>
          <button class="mini-btn primary" type="button" :disabled="saving" @click="save">{{ saving ? '保存中…' : editing ? '保存修改' : '创建模板' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tpl-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
  padding: 16px;
}
.tpl-modal {
  background: var(--surface);
  border-radius: 16px;
  max-width: 720px;
  width: 100%;
  max-height: 88vh;
  overflow: auto;
  padding: 22px 24px;
  box-shadow: var(--shadow-lg);
  scroll-behavior: smooth;
}
.tpl-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.tpl-head h2 {
  margin: 0;
  font-size: 17px;
}
.tpl-sub {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--ink-3);
}
.tpl-head-ops {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.tpl-new {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
  border-radius: 999px;
  padding: 8px 16px;
  font-size: 13px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  box-shadow: 0 3px 12px rgba(99, 102, 241, 0.35);
  cursor: pointer;
  white-space: nowrap;
}
.tpl-new:hover {
  filter: brightness(1.06);
}
.tpl-new svg {
  width: 14px;
  height: 14px;
}
.tpl-x {
  border: none;
  background: var(--bg-soft);
  border-radius: 8px;
  width: 30px;
  height: 30px;
  cursor: pointer;
  color: var(--ink-2);
}
.tpl-hint {
  font-size: 12.5px;
  color: var(--ink-3);
  margin: 8px 0 12px;
  line-height: 1.6;
}
.tpl-kinds {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.tpl-kind {
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-3);
  font-size: 12px;
  font-weight: 600;
  padding: 5px 13px;
  border-radius: 999px;
  cursor: pointer;
}
.tpl-kind.on {
  background: #eef2ff;
  border-color: #c7d2fe;
  color: #4338ca;
}
.tpl-error {
  color: var(--danger);
  font-size: 13px;
}
.tpl-notice {
  color: #047857;
  background: var(--success-soft);
  border-radius: 8px;
  padding: 7px 11px;
  font-size: 12.5px;
}
.tpl-loading {
  color: var(--ink-3);
  padding: 12px 0;
}
.tpl-group {
  margin-bottom: 14px;
}
.tpl-group-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--ink-2);
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.tpl-group-count {
  font-size: 11px;
  font-weight: 700;
  background: var(--bg-soft);
  border: 1px solid var(--line);
  color: var(--ink-3);
  border-radius: 999px;
  padding: 0 8px;
}
.tpl-item {
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 12px 14px;
  margin-bottom: 10px;
  background: var(--bg-soft);
}
.tpl-item.active {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
  background: #fafaff;
}
.tpl-item-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.tpl-item-head strong {
  font-size: 14px;
}
.tpl-editing-flag {
  font-size: 11px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  border-radius: 999px;
  padding: 2px 9px;
}
.tpl-expand {
  margin-left: auto;
  border: none;
  background: none;
  color: var(--brand-strong);
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
}
.tpl-tag {
  font-size: 11px;
  background: var(--brand-soft);
  color: var(--brand-strong);
  border-radius: 999px;
  padding: 1px 8px;
}
.tpl-tag.system {
  background: #e0e7ff;
  color: #3730a3;
}
.tpl-tag.published {
  background: #d1fae5;
  color: #065f46;
}
.tpl-tag.personal {
  background: var(--brand-soft);
  color: var(--brand-strong);
}
.tpl-item-content {
  font-size: 12.5px;
  color: var(--ink-2);
  white-space: pre-wrap;
  margin: 8px 0;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 8px 10px;
}
.tpl-item-content.clamp {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  max-height: none;
}
.tpl-item-ops {
  display: flex;
  gap: 6px;
}
.tpl-empty {
  color: var(--ink-3);
  font-size: 13px;
  padding: 8px 0;
}
.tpl-form {
  border-top: 1px solid var(--line);
  margin-top: 12px;
  padding-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  scroll-margin-top: 12px;
}
.tpl-form.editing {
  background: #fafaff;
  border: 1px solid #c7d2fe;
  border-radius: 12px;
  padding: 14px;
}
.tpl-form-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.tpl-form-head h3 {
  margin: 0;
  font-size: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.tpl-form-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #22c55e;
}
.tpl-form-dot.editing {
  background: #6366f1;
}
.tpl-switch-new {
  border: 1px dashed #c7d2fe;
  background: #eef2ff;
  color: #4338ca;
  font-size: 12px;
  font-weight: 700;
  border-radius: 999px;
  padding: 5px 12px;
  cursor: pointer;
  white-space: nowrap;
}
.tpl-switch-new:hover {
  background: #e0e7ff;
}
.tpl-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12.5px;
  color: var(--ink-2);
  font-weight: 600;
}
.tpl-field input,
.tpl-field textarea {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 8px 10px;
  font-size: 13px;
  font-family: inherit;
}
.tpl-form-ops {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.mini-btn {
  border: 1px solid var(--line);
  background: var(--bg-soft);
  color: var(--ink-2);
  font-size: 12.5px;
  padding: 5px 12px;
  border-radius: 8px;
  cursor: pointer;
}
.mini-btn.ghost {
  background: var(--surface);
}
.mini-btn.primary {
  background: var(--brand);
  border-color: var(--brand);
  color: #fff;
}
.mini-btn.danger {
  color: var(--danger);
  border-color: #fecaca;
}
</style>
