<script setup lang="ts">
/**
 * 提示词模板管理弹窗（按场景复用）。
 * scene: feedback 课后反馈 / report 报告总结 / evaluation 学员评估。
 * 系统模板：所有人可见，可编辑、不可删除；个人模板仅自己可见、可删改；
 * 管理员可发布/取消发布个人模板给全校。
 */
import { computed, ref, watch } from 'vue'

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
  report: '模板用于 AI 生成报告总结，所选模板内容会作为写作风格要求叠加到生成中。',
  evaluation: '模板用于 AI 生成学员评估，所选模板内容会作为写作风格要求叠加到生成中。',
}

const auth = useAuthStore()
const isAdmin = computed(() => auth.user?.role === 'admin')
const loading = ref(false)
const error = ref('')
const items = ref<PromptTemplateOut[]>([])
const editing = ref<PromptTemplateOut | null>(null)
const formName = ref('')
const formContent = ref('')
const formError = ref('')
const saving = ref(false)

const groups = computed(() => ({
  system: items.value.filter((t) => t.scope === 'system'),
  published: items.value.filter((t) => t.scope === 'published'),
  personal: items.value.filter((t) => t.scope === 'personal'),
}))

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
    editing.value = null
    formError.value = ''
    void load()
  }
})

function startCreate() {
  editing.value = null
  formName.value = ''
  formContent.value = ''
  formError.value = ''
}

function startEdit(t: PromptTemplateOut) {
  editing.value = t
  formName.value = t.name
  formContent.value = t.content
  formError.value = ''
}

async function save() {
  formError.value = ''
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
      await updatePromptTemplate(editing.value.id, { name, content })
    } else {
      await createPromptTemplate({ name, content, scene: props.scene })
    }
    editing.value = null
    formName.value = ''
    formContent.value = ''
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
        <h2>{{ title }}</h2>
        <button class="tpl-x" @click="emit('close')">✕</button>
      </div>
      <p class="tpl-hint">
        {{ SCENE_HINT[scene] }}系统模板开箱即用（可编辑、不可删除）；「我的」模板仅自己可见。
        <template v-if="isAdmin">管理员可将模板「发布」给全校教师使用。</template>
        <template v-else>发布需管理员操作。</template>
      </p>
      <p v-if="error" class="tpl-error">{{ error }}</p>
      <div v-if="loading" class="tpl-loading">加载中…</div>
      <template v-else>
        <template v-for="(group, key) in groups" :key="key">
          <div v-if="group.length" class="tpl-group">
            <div class="tpl-group-title">
              {{ key === 'system' ? '系统模板' : key === 'published' ? '已发布（全校）' : '我的模板' }}
            </div>
            <div v-for="t in group" :key="t.id" class="tpl-item">
              <div class="tpl-item-head">
                <strong>{{ t.name }}</strong>
                <span class="tpl-tag">{{ scopeTag(t) }}</span>
              </div>
              <p class="tpl-item-content">{{ t.content }}</p>
              <div class="tpl-item-ops">
                <button class="mini-btn" @click="startEdit(t)">编辑</button>
                <button v-if="t.scope !== 'system'" class="mini-btn danger" @click="remove(t)">删除</button>
                <button v-if="isAdmin && (t.scope === 'personal' || t.scope === 'published')" class="mini-btn" @click="togglePublish(t)">
                  {{ t.scope === 'published' ? '取消发布' : '发布给全校' }}
                </button>
              </div>
            </div>
          </div>
        </template>
        <div v-if="!items.length" class="tpl-empty">暂无模板，点击下方「新建模板」创建</div>
      </template>
      <div class="tpl-form">
        <h3>{{ editing ? '编辑模板' : '新建模板' }}</h3>
        <input v-model="formName" type="text" placeholder="模板名称，如：鼓励成长型" />
        <textarea v-model="formContent" rows="5" placeholder="模板正文（反馈场景可用 {student_name} 等占位符）" />
        <p v-if="formError" class="tpl-error">{{ formError }}</p>
        <div class="tpl-form-ops">
          <button v-if="!editing" class="mini-btn" @click="startCreate">清空</button>
          <button class="mini-btn primary" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存模板' }}</button>
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
  max-width: 640px;
  width: 100%;
  max-height: 88vh;
  overflow: auto;
  padding: 20px;
}
.tpl-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.tpl-head h2 {
  margin: 0;
  font-size: 17px;
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
}
.tpl-error {
  color: var(--danger);
  font-size: 13px;
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
}
.tpl-item {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 12px;
  margin-bottom: 8px;
}
.tpl-item-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.tpl-tag {
  font-size: 11px;
  background: var(--brand-soft);
  color: var(--brand-strong);
  border-radius: 999px;
  padding: 1px 8px;
}
.tpl-item-content {
  font-size: 12.5px;
  color: var(--ink-3);
  white-space: pre-wrap;
  margin: 6px 0;
  max-height: 120px;
  overflow: auto;
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
  padding-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.tpl-form h3 {
  margin: 0;
  font-size: 14px;
}
.tpl-form input,
.tpl-form textarea {
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
