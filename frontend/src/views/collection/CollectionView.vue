<script setup lang="ts">
import { onMounted, ref } from 'vue'

import PaginationBar from '@/components/PaginationBar.vue'
import {
  listPackages,
  listStudents,
  renewStudent,
  updateStudentFollowUp,
  type LessonPackageOut,
  type StudentOut,
} from '@/api/enrollment'

const students = ref<StudentOut[]>([])
const packages = ref<LessonPackageOut[]>([])
const loading = ref(false)
const error = ref('')
const followUpTab = ref<'all' | 'pending' | 'renewed' | 'stopped'>('all')
const summary = ref({ total: 0, urgent: 0, renewed: 0 })

// 分页
const page = ref(1)
const pageSize = 10
const total = ref(0)

// 已续费弹窗：选课包 / 自定义
const showRenew = ref(false)
const renewStudent_ = ref<StudentOut | null>(null)
const renewMode = ref<'package' | 'custom'>('package')
const renewPackageId = ref('')
const renewCustomLessons = ref<number | null>(null)
const renewCustomAmount = ref<number | null>(null)
const renewNote = ref('')
const renewError = ref('')
const renewSubmitting = ref(false)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const pageData = await listStudents({
      low_balance_only: true,
      follow_up: followUpTab.value === 'all' ? undefined : followUpTab.value,
      limit: pageSize,
      offset: (page.value - 1) * pageSize,
    })
    const list = pageData.items
    // 待跟进优先，其次按课时余额升序
    students.value = list.sort((a, b) => {
      const pa = a.follow_up_status === 'pending' ? 0 : 1
      const pb = b.follow_up_status === 'pending' ? 0 : 1
      if (pa !== pb) return pa - pb
      return a.lesson_balance - b.lesson_balance
    })
    total.value = pageData.total
    summary.value = {
      total: pageData.total,
      urgent: list.filter((s) => s.lesson_balance <= 5 && s.follow_up_status === 'pending').length,
      renewed: list.filter((s) => s.follow_up_status === 'renewed').length,
    }
  } catch {
    error.value = '加载催缴名单失败'
  } finally {
    loading.value = false
  }
}

function switchTab(tab: 'all' | 'pending' | 'renewed' | 'stopped') {
  followUpTab.value = tab
  page.value = 1
  load()
}

function onPageChange(p: number) {
  page.value = p
  load()
}

async function loadPackages() {
  const pkgPage = await listPackages(false, { limit: 500 })
  packages.value = pkgPage.items
}

function openRenew(s: StudentOut) {
  renewStudent_.value = s
  renewMode.value = 'package'
  renewPackageId.value = packages.value[0]?.id || ''
  renewCustomLessons.value = null
  renewCustomAmount.value = null
  renewNote.value = ''
  renewError.value = ''
  showRenew.value = true
}

async function submitRenew() {
  if (!renewStudent_.value) return
  renewError.value = ''
  renewSubmitting.value = true
  try {
    const payload: Record<string, unknown> = { note: renewNote.value.trim() || null }
    if (renewMode.value === 'package') {
      if (!renewPackageId.value) {
        renewError.value = '请选择课时包'
        return
      }
      payload.package_id = renewPackageId.value
    } else {
      if (!renewCustomLessons.value || renewCustomLessons.value <= 0) {
        renewError.value = '请填写自定义补充课时'
        return
      }
      payload.custom_lessons = renewCustomLessons.value
      if (renewCustomAmount.value && renewCustomAmount.value > 0) {
        payload.custom_amount = renewCustomAmount.value
      }
    }
    await renewStudent(renewStudent_.value.id, payload)
    showRenew.value = false
    await load()
  } catch (e: any) {
    renewError.value = e?.response?.data?.detail || '续费入账失败'
  } finally {
    renewSubmitting.value = false
  }
}

async function recordStopped(s: StudentOut) {
  if (!window.confirm(`确认「${s.name}」已停课？将停止后续催缴提醒，学员同步标记为停课。`)) return
  await updateStudentFollowUp(s.id, { follow_up_status: 'stopped', note: '教务跟进确认已停课' })
  await load()
}

/** 已停课学员恢复为待跟进（同步恢复在读）。 */
async function restorePending(s: StudentOut) {
  if (!window.confirm(`确认将「${s.name}」恢复为待跟进？将同步恢复在读并重新进入催缴跟进。`)) return
  await updateStudentFollowUp(s.id, { follow_up_status: 'pending', note: '恢复为待跟进' })
  await load()
}

function followUpLabel(status: string): string {
  const map: Record<string, string> = {
    pending: '待跟进',
    renewed: '已续费',
    stopped: '已停课',
  }
  return map[status] || '待跟进'
}

function followUpTime(s: StudentOut): string {
  if (!s.follow_up_at) return ''
  const d = new Date(s.follow_up_at)
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

function pkgInfo(pkg: LessonPackageOut): string {
  return `${pkg.name}（${pkg.total_lessons} 课时 / ¥${Number(pkg.price).toFixed(0)}）`
}

onMounted(async () => {
  try {
    await loadPackages()
  } catch {
    packages.value = []
  }
  await load()
})
</script>

<template>
  <div>
    <header class="page-head">
      <div>
        <h1>催缴名单</h1>
        <p class="page-sub">课时 ≤ 10 自动进入 · 跟进状态直接显示（待跟进 / 已续费 / 已停课）</p>
      </div>
      <div class="summary">
        <div class="stat-card">
          <span class="stat-num">{{ summary.total }}</span>
          <span class="stat-label">名单人数</span>
        </div>
        <div class="stat-card urgent">
          <span class="stat-num">{{ summary.urgent }}</span>
          <span class="stat-label">本页紧急（≤5）</span>
        </div>
        <div class="stat-card ok">
          <span class="stat-num">{{ summary.renewed }}</span>
          <span class="stat-label">本页已续费</span>
        </div>
      </div>
    </header>

    <div class="rule-tip">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z" /></svg>
      业务规则：课时 ≤ 10 节自动进入名单（待跟进）；教务跟进后标记为「已续费」，仍保留在名单中直接显示跟进状态
    </div>

    <div class="tabs">
      <button
        v-for="t in (['all', 'pending', 'renewed', 'stopped'] as const)"
        :key="t"
        class="tab"
        :class="{ active: followUpTab === t }"
        @click="switchTab(t)"
      >
        {{ t === 'all' ? '全部' : t === 'pending' ? '待跟进' : t === 'renewed' ? '已续费' : '已停课' }}
      </button>
    </div>

    <p v-if="error" class="error-banner">{{ error }}</p>

    <div class="card-table">
      <table>
        <thead>
          <tr>
            <th>学员</th>
            <th>电话</th>
            <th>班级</th>
            <th>课时余额</th>
            <th>紧急程度</th>
            <th>跟进状态</th>
            <th class="ops">跟进</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in students" :key="s.id">
            <td>
              <div class="cell-user">
                <div class="cell-avatar" :class="{ urgent: s.lesson_balance <= 5, stopped: s.follow_up_status === 'stopped' }">{{ s.name.slice(0, 1) }}</div>
                <div>
                  <div class="cell-name">{{ s.name }}</div>
                  <div class="cell-sub" v-if="s.follow_up_at">跟进于 {{ followUpTime(s) }}</div>
                </div>
              </div>
            </td>
            <td>{{ s.phone || '—' }}</td>
            <td>{{ s.classes.map((c) => c.name).join('、') || '—' }}</td>
            <td>
              <span :class="['balance', { urgent: s.lesson_balance <= 5 }]">{{ s.lesson_balance }}</span>
            </td>
            <td>
              <span v-if="s.follow_up_status === 'pending'" class="badge" :class="{ urgent: s.lesson_balance <= 5 }">
                {{ s.lesson_balance <= 5 ? '紧急' : '待续费' }}
              </span>
              <span v-else class="badge done">—</span>
            </td>
            <td>
              <span class="follow-pill" :class="s.follow_up_status">
                {{ followUpLabel(s.follow_up_status) }}
              </span>
              <div v-if="s.follow_up_status === 'stopped' && s.stop_note" class="stop-note" :title="s.stop_note">
                {{ s.stop_note }}
              </div>
            </td>
            <td class="ops">
              <template v-if="s.follow_up_status === 'pending'">
                <button class="recharge-btn" @click="openRenew(s)">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
                  已续费
                </button>
                <button class="stop-btn" @click="recordStopped(s)">已停课</button>
              </template>
              <template v-else-if="s.follow_up_status === 'stopped'">
                <button class="restore-btn" @click="restorePending(s)">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7M3 4v5h5" /></svg>
                  恢复为待跟进
                </button>
              </template>
              <span v-else class="done-text">已完成</span>
            </td>
          </tr>
          <tr v-if="!loading && students.length === 0">
            <td colspan="7" class="empty">
              <span class="empty-emoji">🎉</span>
              暂无该状态下的催缴学员
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <PaginationBar :total="total" :page="page" :page-size="pageSize" @update:page="onPageChange" />

    <!-- 已续费弹窗：选课包 / 自定义 -->
    <div v-if="showRenew" class="overlay" @click.self="showRenew = false">
      <div class="modal">
        <h2>续费入账 · {{ renewStudent_?.name }}</h2>
        <p class="muted">当前余额：{{ renewStudent_?.lesson_balance }} 课时 · 选择课时包或自定义补充课时与金额</p>

        <div class="mode-tabs">
          <button :class="['mode-tab', { active: renewMode === 'package' }]" @click="renewMode = 'package'">选择课时包</button>
          <button :class="['mode-tab', { active: renewMode === 'custom' }]" @click="renewMode = 'custom'">自定义课时</button>
        </div>

        <template v-if="renewMode === 'package'">
          <label>
            课时包
            <select v-model="renewPackageId">
              <option value="" disabled>请选择课时包</option>
              <option v-for="p in packages" :key="p.id" :value="p.id">{{ pkgInfo(p) }}</option>
            </select>
            <small>按课时包课时入账（如 80 课时包 → +80 课时）</small>
          </label>
        </template>

        <template v-else>
          <div class="row">
            <label>
              补充课时 *
              <input v-model.number="renewCustomLessons" type="number" min="1" placeholder="如：30" />
            </label>
            <label>
              金额（元）
              <input v-model.number="renewCustomAmount" type="number" min="0" step="0.01" placeholder="机动定价，选填" />
            </label>
          </div>
        </template>

        <label>
          备注（选填）
          <input v-model="renewNote" type="text" placeholder="如：老学员优惠续费" />
        </label>

        <p v-if="renewError" class="error">{{ renewError }}</p>
        <div class="modal-actions">
          <button class="btn ghost" @click="showRenew = false">取消</button>
          <button class="btn primary" :disabled="renewSubmitting" @click="submitRenew">
            {{ renewSubmitting ? '入账中…' : '确认续费入账' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
}
h1 {
  font-size: 22px;
}
.page-sub {
  color: var(--ink-3);
  font-size: 13px;
  margin-top: 4px;
}
.summary {
  display: flex;
  gap: 10px;
}
.stat-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 10px 18px;
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 88px;
}
.stat-card.urgent {
  border-color: #fecaca;
  background: linear-gradient(160deg, #fff, #fff7f7);
}
.stat-card.ok {
  border-color: #a7f3d0;
  background: linear-gradient(160deg, #fff, #f0fdf9);
}
.stat-num {
  font-size: 24px;
  font-weight: 800;
  color: var(--ink);
}
.stat-card.urgent .stat-num {
  color: var(--danger);
}
.stat-card.ok .stat-num {
  color: var(--success);
}
.stat-label {
  font-size: 11.5px;
  color: var(--ink-3);
  margin-top: 1px;
}

.rule-tip {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--warning-soft);
  color: #92400e;
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 13px;
  margin-bottom: 14px;
}
.rule-tip svg {
  width: 15px;
  height: 15px;
  color: var(--warning);
  flex-shrink: 0;
}

.tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
}
.tab {
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-3);
  font-size: 13px;
  font-weight: 600;
  padding: 7px 16px;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.15s;
}
.tab:hover {
  border-color: var(--brand);
  color: var(--brand);
}
.tab.active {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  border-color: transparent;
  color: #fff;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.error-banner {
  background: var(--danger-soft);
  color: var(--danger);
  padding: 10px 14px;
  border-radius: 10px;
  margin-bottom: 16px;
  font-size: 13px;
}

.card-table {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  overflow: hidden;
  box-shadow: var(--shadow-sm);
}
.card-table table {
  width: 100%;
  border-collapse: collapse;
}
.card-table th,
.card-table td {
  padding: 13px 18px;
  text-align: left;
  font-size: 14px;
  border-bottom: 1px solid var(--line);
}
.card-table th {
  background: #f9fafb;
  color: var(--ink-3);
  font-weight: 600;
  font-size: 12.5px;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.card-table tr:last-child td {
  border-bottom: none;
}

.cell-user {
  display: flex;
  align-items: center;
  gap: 11px;
}
.cell-avatar {
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 11px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #f59e0b, #f97316);
}
.cell-avatar.urgent {
  background: linear-gradient(135deg, #f97316, #ef4444);
}
.cell-avatar.stopped {
  background: linear-gradient(135deg, #94a3b8, #64748b);
}
.cell-name {
  font-weight: 600;
  color: var(--ink);
}
.cell-sub {
  color: var(--ink-3);
  font-size: 11.5px;
  margin-top: 1px;
}

.balance {
  font-weight: 800;
  font-size: 17px;
  color: var(--warning);
}
.balance.urgent {
  color: var(--danger);
}
.badge {
  background: var(--warning-soft);
  color: #92400e;
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
}
.badge.urgent {
  background: var(--danger-soft);
  color: var(--danger);
}
.badge.done {
  background: #f1f5f9;
  color: var(--ink-3);
}

.follow-pill {
  font-size: 12px;
  font-weight: 700;
  padding: 3px 12px;
  border-radius: 999px;
  white-space: nowrap;
}
.follow-pill.pending {
  background: var(--warning-soft);
  color: #b45309;
}
.follow-pill.renewed {
  background: var(--success-soft);
  color: var(--success);
}
.follow-pill.stopped {
  background: #f1f5f9;
  color: var(--ink-3);
}
.stop-note {
  margin-top: 4px;
  font-size: 11px;
  color: var(--ink-3);
  max-width: 180px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ops {
  white-space: nowrap;
}
.recharge-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: none;
  background: linear-gradient(135deg, #10b981, #059669);
  color: #fff;
  font-size: 12.5px;
  font-weight: 600;
  padding: 6px 13px;
  border-radius: 9px;
  cursor: pointer;
  transition: all 0.15s;
}
.recharge-btn:hover {
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.35);
  transform: translateY(-1px);
}
.recharge-btn svg {
  width: 13px;
  height: 13px;
}
.stop-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-3);
  font-size: 12.5px;
  font-weight: 600;
  padding: 6px 13px;
  border-radius: 9px;
  cursor: pointer;
  margin-left: 6px;
  transition: all 0.15s;
}
.stop-btn:hover {
  border-color: var(--ink-3);
  color: var(--ink);
}
.restore-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 1px solid var(--brand);
  background: var(--brand-soft);
  color: var(--brand-strong);
  font-size: 12.5px;
  font-weight: 600;
  padding: 6px 13px;
  border-radius: 9px;
  cursor: pointer;
  transition: all 0.15s;
}
.restore-btn:hover {
  background: var(--brand);
  color: #fff;
}
.restore-btn svg {
  width: 13px;
  height: 13px;
}
.done-text {
  color: var(--ink-3);
  font-size: 12.5px;
}
.empty {
  text-align: center;
  color: var(--ink-3);
  padding: 40px 0;
}
.empty-emoji {
  display: block;
  font-size: 28px;
  margin-bottom: 6px;
}

.overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.5);
  backdrop-filter: blur(3px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 50;
}
.modal {
  width: 460px;
  background: var(--surface);
  border-radius: 16px;
  padding: 26px;
  box-shadow: var(--shadow-lg);
  max-height: 86vh;
  overflow: auto;
}
.modal h2 {
  font-size: 18px;
  margin-bottom: 14px;
}
.modal label {
  display: block;
  margin-bottom: 14px;
  font-size: 13px;
  color: var(--ink-2);
  font-weight: 500;
}
.modal input,
.modal select {
  display: block;
  width: 100%;
  margin-top: 6px;
  padding: 9px 11px;
  border: 1px solid var(--line);
  border-radius: 10px;
  box-sizing: border-box;
  font-size: 14px;
  transition: all 0.15s;
  background: var(--surface);
}
.modal input:focus,
.modal select:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}
.modal small {
  color: var(--ink-3);
}
.muted {
  color: var(--ink-3);
  font-size: 13px;
  margin-bottom: 12px;
}
.error {
  color: var(--danger);
  font-size: 13px;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
}

.mode-tabs {
  display: flex;
  gap: 8px;
  background: #f1f5f9;
  border-radius: 10px;
  padding: 4px;
  margin-bottom: 16px;
}
.mode-tab {
  flex: 1;
  border: none;
  background: transparent;
  padding: 8px 0;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-3);
  cursor: pointer;
  transition: all 0.15s;
}
.mode-tab.active {
  background: var(--surface);
  color: var(--brand-strong);
  box-shadow: var(--shadow-sm);
}
.row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
</style>
