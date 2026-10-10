<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import ConfirmDialog from '@/components/ConfirmDialog.vue'
import {
  getSchedule,
  listAttendance,
  submitAttendance,
  cancelSchedule,
  type AttendanceOut,
  type ScheduleOut,
} from '@/api/schedule'
import { fmtDateTimeFromIso, parseServerTime, today } from '@/utils/date'

const route = useRoute()
const router = useRouter()
const scheduleId = route.params.id as string

const schedule = ref<ScheduleOut | null>(null)
const rows = ref<AttendanceOut[]>([])
const loading = ref(false)
const submitting = ref(false)
const notice = ref<{ type: 'ok' | 'err' | 'info'; text: string } | null>(null)
const markLocked = computed(() => schedule.value?.status !== 'scheduled')

// 未到上课时间：禁止签到（防误操作），但允许提前请假
const notStarted = computed(() => {
  if (!schedule.value || schedule.value.status !== 'scheduled') return false
  return parseServerTime(schedule.value.start_time).getTime() > today().getTime()
})
const attendDisabled = computed(() => markLocked.value || notStarted.value)
const leaveDisabled = computed(() => markLocked.value)

const pending = ref<Set<string>>(new Set())
const loadError = ref('')

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    schedule.value = await getSchedule(scheduleId)
    rows.value = await listAttendance(scheduleId)
  } catch (e: any) {
    loadError.value = e?.response?.data?.detail || e?.message || '加载排课详情失败'
  } finally {
    loading.value = false
  }
}

const attendedCount = computed(() => rows.value.filter((r) => r.status === 'attended').length)
const leaveCount = computed(() => rows.value.filter((r) => r.status === 'leave').length)
const unmarkedCount = computed(() => rows.value.filter((r) => r.status === 'unmarked').length)

async function cancelThis() {
  if (!schedule.value) return
  showCancel.value = true
}
const showCancel = ref(false)
async function confirmCancel() {
  if (!schedule.value) return
  showCancel.value = false
  try {
    await cancelSchedule(schedule.value.id)
    router.push({ name: 'schedules' })
  } catch (e: any) {
    notice.value = { type: 'err', text: e?.response?.data?.detail || '取消排课失败' }
  }
}

function timeOf(iso: string): string {
  return fmtDateTimeFromIso(iso)
}

async function mark(status: 'attended' | 'leave', studentId: string) {
  if (status === 'attended' && attendDisabled.value) {
    notice.value = { type: 'info', text: '未到上课时间，暂不能签到；请假可提前标记' }
    return
  }
  if (status === 'leave' && leaveDisabled.value) {
    notice.value = { type: 'info', text: '该排课已结束或取消，不可再标记' }
    return
  }
  pending.value.add(studentId)
  submitting.value = true
  notice.value = null
  try {
    const result = await submitAttendance(scheduleId, [{ student_id: studentId, status }])
    if (result.errors.length) {
      notice.value = { type: 'err', text: result.errors[0].reason }
    } else {
      const rec = result.lesson_records[0]
      const rowName = rows.value.find((r) => r.student_id === studentId)?.student_name
      notice.value = rec
        ? {
            type: 'ok',
            text:
              rec.is_trial
                ? `${rowName} 已到（体验课免费，不扣课时）`
                : `${rowName} 已到，扣 2 课时（余额 ${rec.balance_after}）` +
                  (rec.balance_after < 0
                    ? `，已欠费 ${-rec.balance_after} 节（按最近购包价记账，挂应收）`
                    : ''),
          }
        : { type: 'ok', text: '已标记请假（不扣课时）' }
    }
    await load()
  } catch (e: any) {
    notice.value = { type: 'err', text: e?.response?.data?.detail || '操作失败' }
  } finally {
    pending.value.delete(studentId)
    submitting.value = false
  }
}

function back() {
  router.push({ name: 'schedules' })
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    scheduled: '待上课',
    completed: '已完成',
    cancelled: '已取消',
  }
  return map[status] || status
}

onMounted(load)
</script>

<template>
  <div>
    <button class="btn ghost back" @click="back">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M12 19l-7-7 7-7" /></svg>
      返回课表
    </button>

    <div v-if="!loading && loadError" class="notice err">{{ loadError }}</div>

    <template v-if="schedule">      <header class="head">
        <div class="head-main">
          <div class="title-row">
            <h1>{{ schedule.class_name || '体验课（无班级）' }}<span v-if="schedule.is_trial" class="trial-chip">体验课</span></h1>
            <span class="status-pill" :class="schedule.status">{{ statusLabel(schedule.status) }}</span>
          </div>
          <p class="meta">
            {{ timeOf(schedule.start_time) }} ～ {{ timeOf(schedule.end_time) }}
            <span class="dot">·</span>
            {{ schedule.subject }}
            <span class="dot">·</span>
            {{ schedule.teacher_name || '未分配教师' }}
          </p>
          <div class="head-ops">
            <button v-if="schedule.status === 'scheduled'" class="btn danger-ghost" @click="cancelThis">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
              取消排课
            </button>
          </div>
        </div>
        <div class="stats">
          <div class="stat">
            <span class="stat-num">{{ rows.length }}</span>
            <span class="stat-label">学员</span>
          </div>
          <div class="stat">
            <span class="stat-num ok">{{ attendedCount }}</span>
            <span class="stat-label">已到</span>
          </div>
          <div class="stat">
            <span class="stat-num warn">{{ leaveCount }}</span>
            <span class="stat-label">请假</span>
          </div>
          <div class="stat" v-if="unmarkedCount">
            <span class="stat-num muted-num">{{ unmarkedCount }}</span>
            <span class="stat-label">待标记</span>
          </div>
        </div>
      </header>

      <div v-if="notice" class="notice" :class="notice.type">
        {{ notice.text }}
      </div>

      <div v-if="markLocked" class="locked-tip">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8v4l3 3M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z" /></svg>
        {{ schedule.status === 'completed' ? '该节课已完成考勤，不可再标记' : '该排课已取消' }}
      </div>

      <div v-else-if="notStarted" class="locked-tip not-started">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" /></svg>
        未到上课时间（{{ timeOf(schedule.start_time) }} 开始），签到需到点后操作；请假可提前标记
      </div>

      <section class="panel">
        <div class="panel-head">
          <h2>学员考勤与划课时</h2>
          <p class="hint">「已到」需到上课时间后标记，自动扣 2 课时；「请假」可提前标记，不扣课时；同一学员每节课只能标记一次</p>
        </div>

        <div v-if="loading" class="empty">加载中…</div>
        <div v-else-if="rows.length === 0" class="empty">该班级暂无学员</div>

        <div v-else class="student-grid">
          <div v-for="r in rows" :key="r.id" class="student-card" :class="r.status">
            <div class="avatar" :class="r.status">{{ (r.student_name || '?').slice(0, 1) }}</div>
            <div class="info">
              <div class="name">{{ r.student_name }}<span v-if="r.trial_status === 'trial'" class="trial-chip">体验</span></div>
              <div class="balance" :class="{ low: r.low_balance, neg: (r.lesson_balance ?? 0) < 0 }">
                课时 {{ r.lesson_balance }}
                <span v-if="r.low_balance" class="low-tag">待续费</span>
                <span v-if="(r.lesson_balance ?? 0) < 0" class="arrears-tag">欠费{{-(r.lesson_balance ?? 0)}}节</span>
              </div>
            </div>

            <div class="ops">
              <template v-if="r.status === 'unmarked'">
                <button
                  class="mark-btn attended"
                  :disabled="attendDisabled || submitting || pending.has(r.student_id)"
                  :title="notStarted ? '未到上课时间，到点后可签到' : '标记已到并扣课时'"
                  @click="mark('attended', r.student_id)"
                >
                  {{ r.trial_status === 'trial' ? '已到 · 免费' : '已到 · 扣2' }}
                </button>
                <button
                  class="mark-btn leave"
                  :disabled="leaveDisabled || submitting || pending.has(r.student_id)"
                  title="请假可提前标记，不扣课时"
                  @click="mark('leave', r.student_id)"
                >
                  请假
                </button>
              </template>
              <template v-else>
                <span class="mark-state" :class="r.status">
                  {{ r.status === 'attended' ? '✓ 已到' : '· 请假' }}
                </span>
              </template>
            </div>
          </div>
        </div>
      </section>
    </template>

    <!-- 取消排课确认 -->
    <ConfirmDialog
      :visible="showCancel"
      title="取消排课"
      :message="`确认取消「${schedule?.class_name} · ${schedule ? timeOf(schedule.start_time) : ''}」这节课？取消后不可恢复，该节学员考勤将无法再标记。`"
      confirm-text="确认取消"
      danger
      @confirm="confirmCancel"
      @cancel="showCancel = false"
    />
  </div>
</template>

<style scoped>
.back {
  margin-bottom: 16px;
}
.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-2);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.btn svg {
  width: 15px;
  height: 15px;
}
.btn:hover {
  border-color: var(--brand);
  color: var(--brand);
}

.head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  background: linear-gradient(135deg, #eef2ff, #f5f3ff, #ecfeff);
  border: 1px solid #e0e7ff;
  border-radius: 16px;
  padding: 22px 26px;
  margin-bottom: 18px;
}
.title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
h1 {
  font-size: 22px;
}
.status-pill {
  font-size: 12px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 999px;
}
.status-pill.scheduled {
  background: var(--brand-soft);
  color: var(--brand-strong);
}
.status-pill.completed {
  background: var(--success-soft);
  color: var(--success);
}
.status-pill.cancelled {
  background: #f1f5f9;
  color: var(--ink-3);
}
.meta {
  color: var(--ink-3);
  font-size: 13px;
  margin-top: 6px;
}
.dot {
  margin: 0 6px;
  opacity: 0.5;
}

.stats {
  display: flex;
  gap: 22px;
}
.stat {
  display: flex;
  flex-direction: column;
  align-items: center;
}
.stat-num {
  font-size: 24px;
  font-weight: 800;
  color: var(--ink);
}
.stat-num.ok {
  color: var(--success);
}
.stat-num.warn {
  color: var(--warning);
}
.stat-num.muted-num {
  color: var(--ink-3);
}
.stat-label {
  font-size: 11px;
  color: var(--ink-3);
  margin-top: 2px;
}

.head-ops {
  margin-top: 12px;
}
.btn.danger-ghost {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 13px;
  border-radius: 9px;
  border: 1px solid #fecaca;
  background: var(--surface);
  color: var(--danger);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.btn.danger-ghost:hover {
  background: var(--danger-soft);
}
.btn.danger-ghost svg {
  width: 14px;
  height: 14px;
}

.notice {
  padding: 11px 14px;
  border-radius: 10px;
  font-size: 13px;
  margin-bottom: 14px;
}
.notice.ok {
  background: var(--success-soft);
  color: var(--success);
}
.notice.err {
  background: var(--danger-soft);
  color: var(--danger);
}
.notice.info {
  background: var(--warning-soft);
  color: #92400e;
}

.locked-tip {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #f1f5f9;
  color: var(--ink-3);
  padding: 11px 14px;
  border-radius: 10px;
  font-size: 13px;
  margin-bottom: 14px;
}
.locked-tip.not-started {
  background: var(--warning-soft);
  color: #92400e;
}
.locked-tip svg {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
}
.locked-tip.not-started svg {
  color: var(--warning);
}

.panel {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 20px 24px;
}
.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 16px;
}
.panel-head h2 {
  font-size: 16px;
}
.hint {
  color: var(--ink-3);
  font-size: 12px;
}
.empty {
  text-align: center;
  color: var(--ink-3);
  padding: 40px 0;
}

.student-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 12px;
}
.student-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 14px;
  transition: all 0.15s;
}
.student-card.attended {
  border-color: #a7f3d0;
  background: #ecfdf5;
}
.student-card.leave {
  border-color: var(--line);
  background: #f8fafc;
  opacity: 0.85;
}
.avatar {
  width: 42px;
  height: 42px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #6366f1, #06b6d4);
}
.avatar.attended {
  background: linear-gradient(135deg, #10b981, #059669);
}
.avatar.leave {
  background: linear-gradient(135deg, #94a3b8, #64748b);
}
.info {
  flex: 1;
  min-width: 0;
}
.name {
  font-weight: 600;
  font-size: 14.5px;
  color: var(--ink);
  display: flex;
  align-items: center;
  gap: 6px;
}
.trial-chip {
  font-size: 10px;
  font-weight: 700;
  padding: 1px 7px;
  border-radius: 999px;
  background: linear-gradient(135deg, #fef3c7, #fde68a);
  color: #92400e;
}
.balance {
  font-size: 12.5px;
  color: var(--ink-3);
  margin-top: 3px;
}
.balance.low {
  color: var(--danger);
  font-weight: 700;
}
.low-tag {
  margin-left: 6px;
  background: var(--danger-soft);
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 11px;
}
.balance.neg {
  color: var(--danger);
  font-weight: 800;
}
.arrears-tag {
  margin-left: 6px;
  background: #fde4e4;
  color: #b91c1c;
  padding: 1px 7px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
}
.ops {
  display: flex;
  gap: 8px;
}
.mark-btn {
  padding: 7px 13px;
  border: none;
  border-radius: 9px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.mark-btn.attended {
  background: linear-gradient(135deg, #10b981, #059669);
  color: #fff;
}
.mark-btn.attended:hover:not(:disabled) {
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.4);
}
.mark-btn.leave {
  background: #f1f5f9;
  color: var(--ink-2);
}
.mark-btn.leave:hover:not(:disabled) {
  background: #e2e8f0;
}
.mark-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.mark-state {
  font-weight: 700;
  font-size: 13px;
  padding: 6px 12px;
  border-radius: 9px;
}
.mark-state.attended {
  color: var(--success);
  background: var(--success-soft);
}
.mark-state.leave {
  color: var(--ink-3);
  background: #f1f5f9;
}
</style>