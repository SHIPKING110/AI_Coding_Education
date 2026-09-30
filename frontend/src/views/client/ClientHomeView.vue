<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import {
  listClientFeedbacks,
  listClientSchedules,
  type ClientFeedbackOut,
  type ClientScheduleBrief,
} from '@/api/client'
import { listClientEvaluations, type ClientEvaluationOut } from '@/api/evaluation'
import { useClientStore } from '@/stores/client'

const store = useClientStore()

const student = computed(() => store.activeStudent)
const schedules = ref<ClientScheduleBrief[]>([])
const recentFeedbacks = ref<ClientFeedbackOut[]>([])
const latestEvaluation = ref<ClientEvaluationOut | null>(null)
const loading = ref(false)

function fmtDate(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}月${d.getDate()}日 ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function fmtDay(iso: string): string {
  const d = new Date(iso)
  const today = new Date()
  const diff = Math.floor((new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() - new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime()) / 86400000)
  if (diff === 0) return '今天'
  if (diff === 1) return '明天'
  if (diff === 2) return '后天'
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

async function load() {
  if (!store.me) await store.loadMe(true)
  if (!student.value) return
  loading.value = true
  try {
    const [scheds, fbs, evals] = await Promise.all([
      listClientSchedules(student.value.id, { limit: 10 }),
      listClientFeedbacks(student.value.id, { limit: 3 }),
      listClientEvaluations(student.value.id, { limit: 1 }).catch(() => null),
    ])
    schedules.value = scheds
    recentFeedbacks.value = fbs.items
    latestEvaluation.value = evals?.items[0] ?? null
  } catch {
    // 静默
  } finally {
    loading.value = false
  }
}

function evalSummary(ev: ClientEvaluationOut | null): string {
  if (!ev) return ''
  const s = (ev.content ?? {}) as Record<string, unknown>
  return typeof s.summary === 'string' ? s.summary : ''
}

onMounted(load)

// 切换学员后自动刷新本页数据（课时卡/课表/反馈）
watch(() => store.activeStudentId, load)
</script>

<template>
  <div>
    <!-- 学员课时卡 -->
    <div v-if="student" class="balance-card" :class="{ low: student.low_balance }">
      <div class="balance-info">
        <p class="balance-label">{{ store.me?.role === 'student' ? '我的剩余课时' : `${student.name} 的剩余课时` }}</p>
        <div class="balance-value">
          <strong>{{ student.lesson_balance }}</strong>
          <span>节</span>
        </div>
        <p v-if="student.low_balance" class="low-tip">课时 ≤ 10，请尽快续费，避免影响上课</p>
        <p v-else class="healthy-tip">课时充足，继续加油</p>
        <p v-if="student.has_student_account === false" class="account-tip">⚠️ 该学员暂未绑定学员账号：课堂作业将无法触达，请联系老师补建账号后再做课堂练习</p>
        <div v-if="student.next_schedule" class="next-class">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z" /></svg>
          <span>
            {{ fmtDay(student.next_schedule.start_time) }}
            {{ fmtDate(student.next_schedule.start_time).slice(-5) }}
            有课 · {{ student.next_schedule.class_name }}
          </span>
        </div>
      </div>
      <RouterLink v-if="store.me?.role !== 'student'" to="/client/packages" class="renew-btn">
        {{ student.low_balance ? '立即续费' : '去续费' }}
      </RouterLink>
    </div>

    <div v-else-if="!store.loading && store.me && store.students.length === 0" class="empty-tip">
      <p>还没有关联学员。请联系机构老师将学员绑定到您的账号。</p>
    </div>

    <!-- 快捷入口 -->
    <div class="quick-grid">
      <RouterLink to="/client/assignments" class="quick-card">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11h6M9 15h4M7 3h10a2 2 0 0 1 2 2v16H5V5a2 2 0 0 1 2-2z" /></svg>
        <span>在线作业</span>
      </RouterLink>
      <RouterLink to="/client/feedbacks" class="quick-card">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2zM8 9h8M8 12h5" /></svg>
        <span>课后反馈</span>
      </RouterLink>
      <RouterLink to="/client/evaluations" class="quick-card">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2 15 8.6 22 9.3 17 14 18.2 21 12 17.6 5.8 21 7 14 2 9.3 9 8.6z" /></svg>
        <span>学习评估</span>
      </RouterLink>
      <RouterLink v-if="store.me?.role !== 'student'" to="/client/packages" class="quick-card">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 12l-8-5-8 5 8 5 8-5zM4 12v6a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-6" /></svg>
        <span>课时续费</span>
      </RouterLink>
      <RouterLink v-if="store.me?.role !== 'student'" to="/client/orders" class="quick-card">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2M9 5a2 2 0 0 0 2 2h2a2 2 0 0 0 2-2M9 5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2" /></svg>
        <span>我的订单</span>
      </RouterLink>
    </div>

    <!-- 最新学习评估 -->
    <section v-if="latestEvaluation" class="panel eval-panel">
      <div class="panel-head">
        <h2>最新学习评估</h2>
        <RouterLink to="/client/evaluations" class="more-link">全部</RouterLink>
      </div>
      <div class="eval-strip" @click="$router.push('/client/evaluations')">
        <div class="eval-strip-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2 15 8.6 22 9.3 17 14 18.2 21 12 17.6 5.8 21 7 14 2 9.3 9 8.6z" /></svg>
        </div>
        <div class="eval-strip-main">
          <strong>{{ latestEvaluation.title || '学习评估' }}</strong>
          <p>{{ evalSummary(latestEvaluation) || '查看完整评估内容' }}</p>
        </div>
        <svg class="eval-strip-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6" /></svg>
      </div>
    </section>

    <!-- 近期上课安排 -->
    <section v-if="schedules.length > 0" class="panel">
      <div class="panel-head">
        <h2>近期上课安排</h2>
        <span class="panel-sub">{{ schedules.length }} 节</span>
      </div>
      <div class="schedule-list">
        <div v-for="s in schedules.slice(0, 6)" :key="s.id" class="schedule-row">
          <div class="date-chip">
            <span class="day">{{ fmtDay(s.start_time) }}</span>
            <span class="time">{{ fmtDate(s.start_time).slice(-5) }}-{{ fmtDate(s.end_time).slice(-5) }}</span>
          </div>
          <div class="sched-main">
            <strong>{{ s.class_name || '编程课' }}</strong>
            <span class="sched-sub">{{ s.subject }} · {{ s.teacher_name }}</span>
          </div>
          <span class="sched-status" :class="s.status">{{ s.status === 'completed' ? '已完成' : s.status === 'cancelled' ? '已取消' : '待上课' }}</span>
        </div>
      </div>
    </section>

    <!-- 最近反馈 -->
    <section v-if="recentFeedbacks.length > 0" class="panel">
      <div class="panel-head">
        <h2>最近课后反馈</h2>
        <RouterLink to="/client/feedbacks" class="more-link">全部</RouterLink>
      </div>
      <div class="fb-list">
        <RouterLink v-for="fb in recentFeedbacks" :key="fb.id" to="/client/feedbacks" class="fb-card">
          <div class="fb-head">
            <strong>{{ fb.title || fb.topic || '课后反馈' }}</strong>
            <span class="fb-date">{{ fmtDate(fb.schedule_time) }}</span>
          </div>
          <p class="fb-desc">{{ fb.performance || fb.content || fb.evaluation || '查看反馈详情' }}</p>
        </RouterLink>
      </div>
    </section>

    <p v-if="loading" class="loading-tip">加载中…</p>
  </div>
</template>

<style scoped>
.balance-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 22px 24px;
  border-radius: 18px;
  background: linear-gradient(135deg, #1e1b4b, #0e7490);
  color: #f1f5f9;
  box-shadow: 0 10px 30px rgba(14, 116, 144, 0.25);
  margin-bottom: 18px;
}

.balance-card.low {
  background: linear-gradient(135deg, #7f1d1d, #c2410c);
  box-shadow: 0 10px 30px rgba(194, 65, 12, 0.28);
}

.balance-label {
  font-size: 13px;
  color: rgba(241, 245, 249, 0.75);
}

.balance-value {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin: 6px 0;
}

.balance-value strong {
  font-size: 44px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.balance-value span {
  font-size: 15px;
  color: rgba(241, 245, 249, 0.8);
}

.low-tip {
  color: #fecaca;
  font-size: 12.5px;
}

.healthy-tip {
  color: rgba(241, 245, 249, 0.7);
  font-size: 12.5px;
}

.account-tip {
  margin-top: 6px;
  color: #fde68a;
  font-size: 12px;
  line-height: 1.5;
}

.next-class {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 12px;
  padding: 6px 12px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.14);
  font-size: 12.5px;
}

.next-class svg {
  width: 14px;
  height: 14px;
}

.renew-btn {
  flex-shrink: 0;
  padding: 10px 20px;
  border-radius: 999px;
  background: #fff;
  color: #0e7490;
  font-size: 14px;
  font-weight: 700;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.18);
  transition: transform 0.15s;
}

.renew-btn:hover {
  transform: translateY(-2px);
}

.balance-card.low .renew-btn {
  color: #b91c1c;
}

.empty-tip {
  background: var(--surface);
  border: 1px dashed var(--line);
  border-radius: 16px;
  padding: 40px 20px;
  text-align: center;
  color: var(--ink-3);
  font-size: 14px;
}

.quick-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 18px;
}

.quick-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 18px 10px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  color: var(--ink-2);
  font-size: 13px;
  font-weight: 600;
  transition: all 0.15s;
}

.quick-card svg {
  width: 22px;
  height: 22px;
  color: var(--brand);
}

.quick-card:hover {
  border-color: #c7d2fe;
  box-shadow: var(--shadow-sm);
  transform: translateY(-2px);
  color: var(--brand-strong);
}

.panel {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 18px 20px;
  margin-bottom: 18px;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}

.panel-head h2 {
  font-size: 16px;
}

.panel-sub {
  font-size: 12px;
  color: var(--ink-3);
}

.more-link {
  font-size: 13px;
  color: var(--brand);
  font-weight: 600;
}

.schedule-list {
  display: flex;
  flex-direction: column;
}

.schedule-row {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 0;
  border-bottom: 1px solid #f1f5f9;
}

.schedule-row:last-child {
  border-bottom: none;
}

.date-chip {
  min-width: 72px;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 6px 10px;
  border-radius: 10px;
  background: var(--brand-soft);
  color: var(--brand-strong);
  font-size: 12px;
  font-weight: 600;
}

.time {
  font-size: 11px;
  color: var(--ink-3);
  margin-top: 2px;
}

.sched-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.sched-main strong {
  font-size: 14px;
}

.sched-sub {
  font-size: 12px;
  color: var(--ink-3);
}

.sched-status {
  font-size: 11.5px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
}

.sched-status.scheduled {
  background: var(--success-soft);
  color: var(--success);
}

.sched-status.completed {
  background: #f1f5f9;
  color: var(--ink-3);
}

.sched-status.cancelled {
  background: var(--danger-soft);
  color: var(--danger);
}

.fb-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.fb-card {
  display: block;
  padding: 12px 14px;
  border-radius: 12px;
  background: var(--bg);
  border: 1px solid #eef2f7;
  transition: all 0.15s;
}

.fb-card:hover {
  border-color: #c7d2fe;
}

.fb-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.fb-head strong {
  font-size: 13.5px;
  color: var(--ink);
}

.fb-date {
  font-size: 12px;
  color: var(--ink-3);
}

.fb-desc {
  font-size: 12.5px;
  color: var(--ink-2);
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
}

/* 最新学习评估横条 */
.eval-panel {
  border-color: #c7d2fe;
  background: linear-gradient(180deg, #eef2ff 0%, var(--surface) 55%);
}

.eval-strip {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 12px;
  background: var(--surface);
  border: 1px solid var(--line);
  cursor: pointer;
  transition: all 0.15s;
}

.eval-strip:hover {
  border-color: #c7d2fe;
  box-shadow: var(--shadow-sm);
  transform: translateY(-1px);
}

.eval-strip-icon {
  width: 38px;
  height: 38px;
  flex-shrink: 0;
  border-radius: 11px;
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
}

.eval-strip-icon svg {
  width: 18px;
  height: 18px;
}

.eval-strip-main {
  flex: 1;
  min-width: 0;
}

.eval-strip-main strong {
  font-size: 13.5px;
  color: var(--ink);
}

.eval-strip-main p {
  font-size: 12px;
  color: var(--ink-3);
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
}

.eval-strip-arrow {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  color: var(--ink-3);
}

.loading-tip {
  text-align: center;
  color: var(--ink-3);
  font-size: 13px;
  padding: 20px 0;
}

@media (max-width: 640px) {
  .quick-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .balance-card {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
