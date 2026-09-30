<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

import PaginationBar from '@/components/PaginationBar.vue'
import { listClientFeedbacks, type ClientFeedbackOut } from '@/api/client'
import { useClientStore } from '@/stores/client'

const store = useClientStore()
const route = useRoute()
const student = computed(() => store.activeStudent)

const items = ref<ClientFeedbackOut[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 8
const loading = ref(false)
const error = ref('')

const expandedId = ref<string | null>(null)

function fmt(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function load() {
  if (!store.me) await store.loadMe(true)
  if (!student.value) return
  loading.value = true
  error.value = ''
  try {
    const data = await listClientFeedbacks(student.value.id, {
      limit: pageSize,
      offset: (page.value - 1) * pageSize,
    })
    items.value = data.items
    total.value = data.total
  } catch {
    error.value = '加载反馈失败'
  } finally {
    loading.value = false
  }
}

function onPageChange(p: number) {
  page.value = p
  load()
}

function toggle(id: string) {
  expandedId.value = expandedId.value === id ? null : id
}

function applyStudentFromRoute() {
  const sid = route.query.student_id
  if (typeof sid === 'string' && sid && sid !== store.activeStudentId) {
    store.setActiveStudent(sid)
  }
}

onMounted(() => {
  applyStudentFromRoute()
  load()
})

watch(
  () => store.activeStudentId,
  () => {
    page.value = 1
    load()
  },
)

watch(
  () => route.query.student_id,
  () => {
    applyStudentFromRoute()
    load()
  },
)
</script>

<template>
  <div>
    <header class="page-head">
      <div>
        <h1>课后反馈</h1>
        <p class="page-sub" v-if="student">{{ student.name }} · 共 {{ total }} 条反馈</p>
      </div>
    </header>

    <p v-if="error" class="error-banner">{{ error }}</p>

    <div v-if="loading" class="loading-tip">加载中…</div>

    <div v-else-if="items.length === 0" class="empty-tip">
      暂无已发布的课后反馈，老师发送后即可在这里查看
    </div>

    <div v-else class="fb-list">
      <div v-for="fb in items" :key="fb.id" class="fb-item" :class="{ expanded: expandedId === fb.id }">
        <div class="fb-head" @click="toggle(fb.id)">
          <div class="fb-title">
            <span class="fb-badge">已发送</span>
            <strong>{{ fb.title || fb.topic || '课后反馈' }}</strong>
          </div>
          <div class="fb-meta">
            <span>{{ fmt(fb.schedule_time || fb.published_at) }}</span>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="chevron" :class="{ open: expandedId === fb.id }"><path d="m6 9 6 6 6-6" /></svg>
          </div>
        </div>

        <div v-if="expandedId === fb.id" class="fb-body">
          <div v-if="fb.topic" class="fb-row">
            <span class="label">课题</span>
            <span>{{ fb.topic }}</span>
          </div>
          <div v-if="fb.content" class="fb-row">
            <span class="label">课程内容</span>
            <span>{{ fb.content }}</span>
          </div>
          <div v-if="fb.performance" class="fb-row">
            <span class="label">课堂表现</span>
            <span>{{ fb.performance }}</span>
          </div>
          <div v-if="fb.evaluation" class="fb-row">
            <span class="label">课堂评价</span>
            <span>{{ fb.evaluation }}</span>
          </div>
          <div v-if="fb.homework" class="fb-row">
            <span class="label">今日作业</span>
            <span>{{ fb.homework }}</span>
          </div>
          <div v-if="fb.media_urls && fb.media_urls.length" class="media-row">
            <span class="label">课堂照片</span>
            <div class="media-grid">
              <img
                v-for="(url, i) in fb.media_urls"
                :key="i"
                :src="url"
                alt="课堂照片"
                class="media-thumb"
                loading="lazy"
              />
            </div>
          </div>
        </div>
      </div>
    </div>

    <PaginationBar :total="total" :page="page" :page-size="pageSize" @update:page="onPageChange" />
  </div>
</template>

<style scoped>
.page-head {
  margin-bottom: 16px;
}
h1 {
  font-size: 22px;
}
.page-sub {
  color: var(--ink-3);
  font-size: 13px;
  margin-top: 4px;
}

.error-banner {
  background: var(--danger-soft);
  color: var(--danger);
  padding: 10px 14px;
  border-radius: 10px;
  margin-bottom: 14px;
  font-size: 13px;
}

.loading-tip {
  text-align: center;
  color: var(--ink-3);
  font-size: 13px;
  padding: 20px 0;
}

.empty-tip {
  text-align: center;
  color: var(--ink-3);
  padding: 40px 0;
  font-size: 14px;
  background: var(--surface);
  border: 1px dashed var(--line);
  border-radius: 16px;
}

.fb-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.fb-item {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  overflow: hidden;
  transition: border-color 0.15s;
}

.fb-item.expanded {
  border-color: #c7d2fe;
  box-shadow: var(--shadow-sm);
}

.fb-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 14px 16px;
  cursor: pointer;
}

.fb-title {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.fb-title strong {
  font-size: 14.5px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.fb-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--success-soft);
  color: var(--success);
  flex-shrink: 0;
}

.fb-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--ink-3);
  flex-shrink: 0;
}

.chevron {
  width: 16px;
  height: 16px;
  transition: transform 0.2s;
}

.chevron.open {
  transform: rotate(180deg);
}

.fb-body {
  padding: 4px 16px 16px;
  border-top: 1px solid #f1f5f9;
  padding-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.fb-row {
  display: flex;
  gap: 10px;
  font-size: 13.5px;
  line-height: 1.65;
}

.fb-row .label {
  flex-shrink: 0;
  min-width: 68px;
  font-weight: 600;
  color: var(--ink-3);
  font-size: 12.5px;
  padding-top: 2px;
}

.media-row {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.media-row .label {
  font-weight: 600;
  color: var(--ink-3);
  font-size: 12.5px;
}

.media-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 8px;
}

.media-thumb {
  width: 100%;
  aspect-ratio: 4 / 3;
  object-fit: cover;
  border-radius: 10px;
  border: 1px solid var(--line);
}
</style>
