<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import PaginationBar from '@/components/PaginationBar.vue'
import {
  autoComputePayroll,
  computePayroll,
  getWorkbench,
  listPayroll,
  listPosts,
  type WorkbenchItem,
} from '@/api/payroll'
import { getPayrollEvidence, getPayrollStats, type PayrollEvidenceItem } from '@/api/trials'
import { listCampuses } from '@/api/business'
const month = ref(new Date().toISOString().slice(0, 7))
const items = ref<WorkbenchItem[]>([])
const rules = ref<Record<string, string>>({})
const loading = ref(false)
const error = ref('')
const msg = ref('')

const titleFilter = ref('')
const titles = ref<string[]>([])
const campusFilter = ref('')
const campuses = ref<string[]>([])
const keyword = ref('')
const computeStatus = ref<'all' | 'done' | 'todo'>('all')
const page = ref(1)
const pageSize = 8

// 核算弹窗
const showCompute = ref(false)
const target = ref<WorkbenchItem | null>(null)
const computing = ref(false)
const result = ref<Record<string, string> | null>(null)
const entries = ref<Record<string, any>[]>([])

const RULE_LABELS: Record<string, string> = {
  invite: '电话意向人头奖',
  trial: '到场体验课提成',
  convert: '体验转化报名提成',
  renew: '续费提成',
  refer: '口碑转介绍奖',
  trial_lesson: '体验课课时提成',
}

function flash(t: string) {
  msg.value = t
  setTimeout(() => (msg.value = ''), 3000)
}

async function load(auto = true) {
  loading.value = true
  error.value = ''
  try {
    // 先自动核算（数据更新即重算，跳过手工锁定），再拉取总览，保证列表总额是最新的
    if (auto) {
      try {
        const r = await autoComputePayroll(month.value)
        if (r.computed > 0) {
          flash(`已自动核算 ${r.computed} 人${r.skipped ? `，跳过手工锁定 ${r.skipped} 人` : ''}`)
        }
      } catch {
        /* 自动核算失败不阻塞展示 */
      }
    }
    const [wb, pr, ps, cs] = await Promise.all([
      getWorkbench(month.value),
      listPayroll(month.value).catch(() => ({ items: [] })),
      listPosts().catch(() => []),
      listCampuses().catch(() => ({ items: [] })),
    ])
    items.value = wb.items
    rules.value = wb.rules
    entries.value = (pr as { items: Record<string, unknown>[] }).items || []
    titles.value = (ps as { name: string }[]).map((p) => p.name).filter(Boolean)
    campuses.value = ((cs as { name: string }[]) || []).map((c) => c.name).filter(Boolean)
  } catch {
    error.value = '加载教务工作台失败'
  } finally {
    loading.value = false
  }
}

const filtered = computed(() =>
  items.value.filter((u) => {
    if (titleFilter.value && (u.title || '') !== titleFilter.value) return false
    if (campusFilter.value && (u.campus || '') !== campusFilter.value) return false
    if (keyword.value && !u.name.includes(keyword.value.trim())) return false
    if (computeStatus.value === 'done' && !u.has_entry) return false
    if (computeStatus.value === 'todo' && u.has_entry) return false
    return true
  }),
)

const paged = computed(() =>
  filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize),
)

function resetPage() {
  page.value = 1
}

const totals = computed(() => {
  const t = { base: 0, total: 0, count: filtered.value.length, computed: 0, od: 0 }
  for (const u of filtered.value) {
    t.base += Number(u.base_salary || 0)
    t.total += Number(u.total || 0)
    t.od += Number(u.overdraft_commission || 0)
    if (u.has_entry) t.computed += 1
  }
  return t
})

const maxTotal = computed(() =>
  filtered.value.reduce((m, u) => Math.max(m, Number(u.total || 0)), 0),
)

const entryOf = (uid: string) => entries.value.find((e) => e.user_id === uid) as Record<string, any> | undefined

// 明细弹窗：结构化分解（金额 + 占比），供可视化展示
const detailRows = computed(() => {
  const e = target.value ? entryOf(target.value.user_id) : undefined
  if (!e) return []
  return DETAIL_ROWS.map((row) => {
    const count = row.countKey ? Number(e[row.countKey] || 0) : 0
    const amount = row.bonusKey ? Number(e[row.bonusKey] || 0) : 0
    const unitPrice = row.ruleKey ? Number(rules.value[row.ruleKey] || 0) : 0
    return { ...row, count, amount, unitPrice, hasBonus: !!row.bonusKey, active: amount !== 0 || count !== 0 }
  }).filter((r) => r.active)
})

const detailGross = computed(() => {
  const e = target.value ? entryOf(target.value.user_id) : undefined
  if (!e) return 0
  return Number(target.value?.base_salary || 0) + detailRows.value.reduce((s, r) => s + r.amount, 0)
})

const detailMax = computed(() => detailRows.value.reduce((m, r) => Math.max(m, r.amount), 0))

// 明细溯源
const evidenceKind = ref('')
const evidenceItems = ref<PayrollEvidenceItem[]>([])
const evidenceLoading = ref(false)

const DETAIL_ROWS = [
  { key: 'invite', kind: 'invite', label: '电话意向人头', countKey: 'invite_count', bonusKey: 'invite_bonus', ruleKey: 'invite', unit: '人' },
  { key: 'trial', kind: 'arrived', label: '到场体验', countKey: 'trial_count', bonusKey: 'trial_bonus', ruleKey: 'trial', unit: '人' },
  { key: 'trial_lesson', kind: 'trial', label: '体验课课时（教师）', countKey: 'trial_lesson_count', bonusKey: null, ruleKey: 'trial_lesson', unit: '节' },
  { key: 'convert', kind: 'convert', label: '体验转化报名', countKey: 'convert_count', bonusKey: 'convert_bonus', ruleKey: 'convert', unit: '单' },
  { key: 'renew', kind: 'renew', label: '续费', countKey: 'renew_count', bonusKey: 'renew_bonus', ruleKey: 'renew', unit: '单' },
  { key: 'refer', kind: 'refer', label: '口碑转介绍', countKey: 'refer_count', bonusKey: 'refer_bonus', ruleKey: 'refer', unit: '人' },
  { key: 'commission', kind: 'commission', label: '课时绩效（账本汇总）', countKey: null, bonusKey: 'lesson_commission', ruleKey: null, unit: '' },
]

async function openCompute(u: WorkbenchItem) {
  target.value = u
  result.value = null
  evidenceKind.value = ''
  evidenceItems.value = []
  showCompute.value = true
}

async function toggleEvidence(kind: string) {
  if (evidenceKind.value === kind) {
    evidenceKind.value = ''
    return
  }
  if (!target.value) return
  evidenceKind.value = kind
  evidenceLoading.value = true
  try {
    const r = await getPayrollEvidence({ kind, month: month.value, user_id: target.value.user_id })
    evidenceItems.value = r.items
  } catch {
    evidenceItems.value = []
  } finally {
    evidenceLoading.value = false
  }
}

function evidenceLine(it: PayrollEvidenceItem, kind: string): string {
  const parts = [`「${it.student_name || '?'}」`]
  if (kind === 'invite' || kind === 'arrived') {
    if (it.parent) parts.push(it.parent)
    if (it.subject) parts.push(it.subject)
    if (it.teacher) parts.push(`体验教师:${it.teacher}`)
  }
  if (kind === 'trial' && it.class) parts.push(it.class)
  if ((kind === 'convert' || kind === 'refer') && it.source) parts.push(it.source)
  if (kind === 'refer' && it.referrer) parts.push(`介绍人:${it.referrer}`)
  if (kind === 'renew') {
    if (it.lessons) parts.push(`${it.lessons}节`)
    if (it.amount) parts.push(`¥${it.amount}`)
  }
  if (kind === 'commission') {
    if (it.subject) parts.push(it.subject)
    if (it.lessons) parts.push(`${it.lessons}节`)
    if (it.amount) parts.push(`金额¥${it.amount}`)
    if (it.commission) parts.push(`绩效¥${it.commission}`)
    if (it.overdraft) parts.push('欠费')
  }
  if (it.time) parts.push(it.time)
  return parts.join(' · ')
}

async function lockEntry() {
  if (!target.value) return
  const e = entryOf(target.value.user_id)
  if (!e) return
  computing.value = true
  try {
    result.value = await computePayroll({
      user_id: target.value.user_id,
      month: month.value,
      invite_count: Number(e.invite_count || 0),
      trial_count: Number(e.trial_count || 0),
      convert_count: Number(e.convert_count || 0),
      renew_count: Number(e.renew_count || 0),
      refer_count: Number(e.refer_count || 0),
      trial_lesson_count: Number((e as any).trial_lesson_count || 0),
      lesson_commission: String(e.lesson_commission || '0'),
    })
    flash(`已锁定 ${target.value.name} ${month.value} 薪资（后续自动核算不再覆盖）`)
    await load(false)
  } catch (err: any) {
    alert(err?.response?.data?.detail || '锁定失败')
  } finally {
    computing.value = false
  }
}

async function recomputeEntry() {
  if (!target.value) return
  computing.value = true
  try {
    const s = await getPayrollStats({ month: month.value, user_id: target.value.user_id })
    result.value = await computePayroll({
      user_id: target.value!.user_id,
      month: month.value,
      invite_count: s.invite_count,
      trial_count: s.trial_count,
      convert_count: s.convert_count,
      renew_count: s.renew_count,
      refer_count: s.refer_count,
      trial_lesson_count: s.trial_lesson_count,
      lesson_commission: s.lesson_commission,
    })
    flash(`已按最新业务数据重算 ${target.value.name} ${month.value} 薪资（仍为自动核算，可锁定）`)
    // 重算后恢复自动态：再调一次自动核算把 auto 标回 true
    await autoComputePayroll(month.value)
    await load(false)
  } catch (err: any) {
    alert(err?.response?.data?.detail || '重算失败')
  } finally {
    computing.value = false
  }
}

function money(s: unknown): string {
  return Number(s || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function roleLabel(r: string): string {
  return r === 'staff' ? '教务' : r === 'teacher' ? '教师' : r
}

onMounted(load)
</script>

<template>
  <div class="salary-panel">

    <div class="filter-bar">
      <input v-model="month" type="month" class="filter-input" @change="() => { resetPage(); load() }" />
      <select v-model="titleFilter" class="filter-select" @change="resetPage()">
        <option value="">全部职务</option>
        <option v-for="t in titles" :key="t" :value="t">{{ t }}</option>
      </select>
      <select v-model="campusFilter" class="filter-select" @change="resetPage()">
        <option value="">全部校区</option>
        <option v-for="c in campuses" :key="c" :value="c">{{ c }}</option>
      </select>
      <select v-model="computeStatus" class="filter-select" @change="resetPage()">
        <option value="all">全部核算状态</option>
        <option value="done">已核算</option>
        <option value="todo">未核算</option>
      </select>
      <input v-model="keyword" type="text" class="filter-input" placeholder="按姓名筛选" @input="resetPage()" />
      <button class="btn primary sm" @click="() => load()">刷新重算</button>
    </div>


    <p v-if="error" class="error-banner">{{ error }}</p>
    <p v-if="msg" class="success-banner">{{ msg }}</p>

    <!-- 薪资体系说明 -->
    <div class="formula-grid">
      <section class="card formula-card dean">
        <div class="formula-title">教务薪资构成</div>
        <div class="formula-body">基本工资 ＋ 招生绩效（意向人头奖 ＋ 到场体验提成）＋ 体验转化提成 ＋ 续费提成 ＋ 口碑奖</div>
      </section>
      <section class="card formula-card teacher">
        <div class="formula-title">教师薪资构成</div>
        <div class="formula-body">基本工资 ＋ 课时绩效（所耗课时 × 级别比例）＋ 体验课提成 ＋ 体验转化提成 ＋ 续费提成 ＋ 口碑奖</div>
      </section>
    </div>

    <!-- 提成单价 -->
    <section class="card">
      <div class="card-title">本月提成单价 <span class="hint">设置 → 业务功能设置 → 提成规则中调整</span></div>
      <div class="rule-chips">
        <span v-for="(v, k) in rules" :key="k" class="rule-chip">
          {{ RULE_LABELS[k] || k }} <strong>¥{{ v }}</strong>
        </span>
      </div>
    </section>

    <!-- 汇总 -->
    <div class="kpi-grid">
      <div class="kpi ico">
        <span class="kpi-ico blue"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z" /></svg></span>
        <div class="kpi-body"><span>覆盖人数</span><strong>{{ totals.count }} 人</strong></div>
      </div>
      <div class="kpi ico">
        <span class="kpi-ico amber"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M3 7a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><path d="M3 9h18" /></svg></span>
        <div class="kpi-body"><span>基本工资合计</span><strong>¥{{ money(totals.base) }}</strong></div>
      </div>
      <div class="kpi ico highlight">
        <span class="kpi-ico green"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 17l6-6 4 4 8-8" /><path d="M15 7h6v6" /></svg></span>
        <div class="kpi-body"><span>应发薪资合计</span><strong>¥{{ money(totals.total) }}</strong></div>
      </div>
      <div class="kpi ico">
        <span class="kpi-ico green"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9" /><path d="M8.5 12.5l2.5 2.5 4.5-5.5" /></svg></span>
        <div class="kpi-body"><span>已核算</span><strong>{{ totals.computed }} 人</strong></div>
      </div>
      <div class="kpi ico" :class="{ danger: totals.od > 0 }">
        <span class="kpi-ico red"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4M12 17h.01" /><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /></svg></span>
        <div class="kpi-body"><span>欠费课时绩效（学员未缴）</span><strong>¥{{ money(totals.od) }}</strong></div>
      </div>
    </div>

    <!-- 人员薪资榜 -->
    <section class="card staff-card">
      <div class="card-title">{{ month }} 薪资总览 <span class="hint">按应发排序 · 欠费绩效为学员未缴费部分的风险提示</span></div>
      <div v-if="loading" class="loading-tip">加载中…</div>
      <div v-else-if="filtered.length === 0" class="empty-tip">暂无人员（先在教师管理/账号中添加教务与教师）</div>
      <div v-else class="staff-list">
        <div v-for="(u, idx) in paged" :key="u.user_id" class="staff-row" :class="{ done: u.has_entry }">
          <span class="staff-no" :class="{ r1: (page - 1) * pageSize + idx === 0, r2: (page - 1) * pageSize + idx === 1, r3: (page - 1) * pageSize + idx === 2 }">{{ (page - 1) * pageSize + idx + 1 }}</span>
          <span class="staff-avatar">{{ (u.name || '?').slice(0, 1) }}</span>
          <div class="staff-main">
            <div class="staff-head">
              <strong>{{ u.name }}</strong>
              <span class="pill" :class="u.role === 'staff' ? 'campus' : 'title-pill'">{{ roleLabel(u.role) }}</span>
              <span v-if="u.level" class="lvl">{{ u.level }}</span>
              <span v-if="u.campus" class="muted-sm">{{ u.campus }}</span>
              <span v-if="u.title" class="muted-sm">{{ u.title }}</span>
              <span v-if="Number(u.overdraft_commission || 0) > 0" class="od-chip" :title="`其中欠费课时绩效 ¥${money(u.overdraft_commission)}，学员尚未缴费`">
                欠费绩效 ¥{{ money(u.overdraft_commission) }}
              </span>
            </div>
            <div class="staff-break">
              <span>基本 ¥{{ money(u.base_salary) }}</span>
              <span>课时绩效 {{ entryOf(u.user_id) ? `¥${money(entryOf(u.user_id)?.lesson_commission)}` : '—' }}</span>
              <span>邀约/体验 {{ entryOf(u.user_id) ? `¥${money(Number(entryOf(u.user_id)?.invite_bonus || 0) + Number(entryOf(u.user_id)?.trial_bonus || 0))}` : '—' }}</span>
              <span>转化 {{ entryOf(u.user_id) ? `¥${money(entryOf(u.user_id)?.convert_bonus)}` : '—' }}</span>
              <span>续费 {{ entryOf(u.user_id) ? `¥${money(entryOf(u.user_id)?.renew_bonus)}` : '—' }}</span>
              <span>口碑 {{ entryOf(u.user_id) ? `¥${money(entryOf(u.user_id)?.refer_bonus)}` : '—' }}</span>
            </div>
            <div class="bar-track"><div class="bar-fill" :style="{ width: `${maxTotal > 0 ? (Number(u.total) / maxTotal) * 100 : 0}%` }" /></div>
          </div>
          <div class="staff-side">
            <strong class="staff-total">¥{{ money(u.total) }}</strong>
            <span v-if="entryOf(u.user_id)?.auto === false" class="lock-mini">已锁定</span>
            <button class="link-btn" @click="openCompute(u)">查看明细</button>
          </div>
        </div>
      </div>
      <PaginationBar :total="filtered.length" :page="page" :page-size="pageSize" @update:page="(p) => (page = p)" />
    </section>

    <!-- 薪资明细弹窗（可视化分解 + 锁定/重算） -->
    <div v-if="showCompute && target" class="overlay" @click.self="showCompute = false">
      <div class="modal wide">
        <div class="detail-head">
          <div class="detail-head-main">
            <span class="staff-avatar lg">{{ (target.name || '?').slice(0, 1) }}</span>
            <div>
              <div class="detail-name">{{ target.name }}
                <span class="pill" :class="target.role === 'staff' ? 'campus' : 'title-pill'">{{ roleLabel(target.role) }}</span>
                <span v-if="target.level" class="lvl">{{ target.level }}</span>
              </div>
              <div class="muted-sm">{{ month }} · {{ target.campus || '—' }}{{ target.title ? ` · ${target.title}` : '' }}</div>
            </div>
          </div>
          <span v-if="entryOf(target.user_id)" class="lock-tag" :class="{ auto: entryOf(target.user_id)?.auto !== false }">
            {{ entryOf(target.user_id)?.auto !== false ? '自动核算' : '已锁定' }}
          </span>
        </div>

        <div v-if="!entryOf(target.user_id)" class="empty-tip">本月暂无核算记录（数据变化时会自动核算）</div>

        <template v-else>
          <!-- 应发总额 -->
          <div class="gross-card">
            <div class="gross-item base">
              <span>基本工资</span>
              <strong>¥{{ money(target.base_salary) }}</strong>
            </div>
            <span class="gross-plus">＋</span>
            <div class="gross-item perf">
              <span>绩效提成</span>
              <strong>¥{{ money(detailRows.reduce((s, r) => s + r.amount, 0)) }}</strong>
            </div>
            <span class="gross-plus">＝</span>
            <div class="gross-item total">
              <span>应发合计</span>
              <strong>¥{{ money(detailGross) }}</strong>
            </div>
          </div>

          <!-- 绩效构成可视化 -->
          <div class="breakdown">
            <div v-if="detailRows.length === 0" class="muted-sm" style="padding:8px 0">本月无绩效提成（仅基本工资）</div>
            <div v-for="row in detailRows" :key="row.key" class="bk-row">
              <div class="bk-line">
                <div class="bk-label">
                  <strong>{{ row.label }}</strong>
                  <span class="bk-calc">
                    <template v-if="row.countKey">{{ row.count }}{{ row.unit }}</template>
                    <template v-if="row.countKey && row.hasBonus"> × ¥{{ money(row.unitPrice) }}</template>
                    <template v-if="!row.hasBonus"> · 已计入课时绩效</template>
                  </span>
                </div>
                <div class="bk-right">
                  <span v-if="row.hasBonus" class="bk-amt">¥{{ money(row.amount) }}</span>
                  <button class="link-btn" @click="toggleEvidence(row.kind)">
                    {{ evidenceKind === row.kind ? '收起溯源' : '查看溯源' }}
                  </button>
                </div>
              </div>
              <div v-if="row.hasBonus" class="bk-bar"><div class="bk-fill" :style="{ width: `${detailMax > 0 ? (row.amount / detailMax) * 100 : 0}%` }" /></div>
              <div v-if="evidenceKind === row.kind" class="evidence">
                <div v-if="evidenceLoading" class="muted-sm">加载明细…</div>
                <div v-else-if="evidenceItems.length === 0" class="muted-sm">暂无明细</div>
                <div v-else v-for="it in evidenceItems" :key="it.id" class="evidence-line">
                  {{ evidenceLine(it, row.kind) }}
                </div>
              </div>
            </div>
          </div>

          <div v-if="Number(target.overdraft_commission || 0) > 0" class="od-note">
            含欠费课时绩效 ¥{{ money(target.overdraft_commission) }}（学员未缴费部分，存在回收风险）
          </div>
        </template>

        <div v-if="result" class="result-card">
          <strong>已更新，应发合计 ¥{{ money(result.total) }}</strong>
        </div>
        <div class="modal-actions">
          <button class="btn ghost" @click="showCompute = false">关闭</button>
          <button
            v-if="entryOf(target.user_id)?.auto !== false"
            class="btn primary"
            :disabled="computing"
            @click="lockEntry"
          >{{ computing ? '锁定中…' : '确认锁定' }}</button>
          <button v-else class="btn primary" :disabled="computing" @click="recomputeEntry">
            {{ computing ? '重算中…' : '重新自动核算' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.salary-panel { position: relative; }
.workbench::before {
  content: '';
  position: fixed;
  inset: 0;
  pointer-events: none;
  background:
    radial-gradient(600px 220px at 12% -40px, rgba(99, 102, 241, 0.12), transparent 70%),
    radial-gradient(700px 260px at 88% -60px, rgba(6, 182, 212, 0.12), transparent 70%);
  z-index: -1;
}
.filter-bar { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }
.filter-select, .filter-input { padding: 8px 12px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); font-size: 13px; color: var(--ink-2); }
.btn { padding: 8px 18px; border-radius: 10px; font-size: 13px; cursor: pointer; border: 1px solid var(--line); }
.btn.primary { background: linear-gradient(135deg, #6366f1, #06b6d4); color: #fff; border-color: transparent; font-weight: 600; }
.btn.ghost { background: var(--surface); color: var(--ink-2); }
.btn.sm { padding: 7px 14px; font-size: 12.5px; }
.error-banner { background: var(--danger-soft); color: var(--danger); padding: 10px 14px; border-radius: 10px; margin-bottom: 14px; font-size: 13px; }
.success-banner { background: #e2f5ea; color: #0e9f6e; padding: 10px 14px; border-radius: 10px; margin-bottom: 14px; font-size: 13px; }
.formula-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }
@media (max-width: 900px) { .formula-grid { grid-template-columns: 1fr; } }
.formula-card { position: relative; overflow: hidden; border: 1px solid var(--line); border-radius: 16px; padding: 16px 18px; margin-bottom: 0; }
.formula-card::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 5px; }
.formula-card.dean::before { background: linear-gradient(180deg, #6366f1, #8b5cf6); }
.formula-card.teacher::before { background: linear-gradient(180deg, #06b6d4, #10b981); }
.formula-card.dean { background: linear-gradient(135deg, #eef2ff, var(--surface) 65%); }
.formula-card.teacher { background: linear-gradient(135deg, #ecfeff, var(--surface) 65%); }
.formula-title { font-size: 14px; font-weight: 800; margin-bottom: 6px; }
.formula-body { font-size: 13px; color: var(--ink-2); line-height: 1.7; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 18px 20px; margin-bottom: 16px; }
.card-title { font-size: 15px; font-weight: 700; margin-bottom: 12px; }
.card-title .hint { font-size: 12px; font-weight: 400; color: var(--ink-3); margin-left: 8px; }
.rule-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.rule-chip { background: var(--surface-alt); border: 1px solid var(--line); border-radius: 999px; padding: 6px 14px; font-size: 12.5px; color: var(--ink-2); }
.rule-chip strong { color: var(--brand-strong); margin-left: 4px; }
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 16px; }
.kpi { background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 14px 16px; display: flex; gap: 6px; }
.kpi strong { font-size: 20px; font-weight: 800; }
.kpi span { font-size: 12px; color: var(--ink-3); }
.kpi.highlight { border-color: var(--brand); background: var(--brand-soft); }
.kpi.highlight strong { color: var(--brand-strong); }
.kpi.ico { flex-direction: row; align-items: center; gap: 12px; }
.kpi-ico { width: 42px; height: 42px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; border-radius: 13px; }
.kpi-ico svg { width: 21px; height: 21px; }
.kpi-ico.blue { background: #e8effe; color: #2f6fed; }
.kpi-ico.green { background: #e2f5ea; color: #0e9f6e; }
.kpi-ico.amber { background: #fdf0dd; color: #c2570b; }
.kpi-ico.red { background: #fde4e4; color: #d64545; }
.kpi.danger { border-color: #f3c1c1; background: linear-gradient(135deg, #fff5f5, var(--surface) 70%); }
.kpi.danger strong { color: #b91c1c; }
.kpi-body { display: flex; flex-direction: column; gap: 4px; }
.mini-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.mini-table th { text-align: left; font-size: 12px; color: var(--ink-3); font-weight: 600; padding: 8px 8px; border-bottom: 1px solid var(--line); white-space: nowrap; }
.mini-table td { padding: 9px 8px; border-bottom: 1px solid #f1f5f9; white-space: nowrap; }
.mini-table tr:last-child td { border-bottom: none; }
.mini-table .hl { font-weight: 800; color: var(--brand-strong); }
tr.done td:first-child { border-left: 3px solid #10b981; }
.pill { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px; }
.pill.campus { background: var(--brand-soft); color: var(--brand-strong); }
.pill.title-pill { background: #fef3c7; color: #92400e; }
.lock-mini { font-size: 10px; font-weight: 700; padding: 1px 7px; border-radius: 999px; background: var(--surface-alt); color: var(--ink-3); }
.modal.wide { width: 680px; }
.lock-tag { font-size: 11px; font-weight: 700; padding: 2px 10px; border-radius: 999px; background: var(--surface-alt); color: var(--ink-3); margin-left: 8px; vertical-align: middle; }
.lock-tag.auto { background: #e2f5ea; color: #0e9f6e; }

/* 明细弹窗（重设计） */
.detail-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-bottom: 14px; border-bottom: 1px solid var(--line); }
.detail-head-main { display: flex; align-items: center; gap: 12px; }
.detail-name { display: flex; align-items: center; gap: 8px; font-size: 17px; font-weight: 800; }
.detail-name .lvl { font-size: 11px; font-weight: 700; padding: 1px 8px; border-radius: 999px; background: #eef2ff; color: #4338ca; }
.staff-avatar.lg { width: 48px; height: 48px; font-size: 19px; }
.gross-card { display: flex; align-items: stretch; gap: 10px; margin: 16px 0; padding: 14px 16px; border-radius: 14px; background: linear-gradient(135deg, var(--brand-soft), var(--surface) 70%); border: 1px solid var(--brand); }
.gross-item { flex: 1; display: flex; flex-direction: column; gap: 5px; }
.gross-item span { font-size: 12px; color: var(--ink-3); }
.gross-item strong { font-size: 19px; font-weight: 800; font-variant-numeric: tabular-nums; }
.gross-item.total { text-align: right; }
.gross-item.total strong { font-size: 24px; color: var(--brand-strong); }
.gross-plus { display: flex; align-items: center; color: var(--brand); font-size: 18px; font-weight: 700; }
.breakdown { display: flex; flex-direction: column; gap: 12px; margin-top: 4px; }
.bk-row { display: flex; flex-direction: column; gap: 6px; }
.bk-line { display: flex; align-items: center; justify-content: space-between; gap: 10px; font-size: 13.5px; }
.bk-label { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
.bk-calc { font-size: 12px; color: var(--ink-3); font-variant-numeric: tabular-nums; }
.bk-right { display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
.bk-amt { font-weight: 800; color: var(--ink); font-variant-numeric: tabular-nums; }
.bk-bar { height: 6px; border-radius: 999px; background: var(--surface-alt); overflow: hidden; }
.bk-fill { height: 100%; border-radius: 999px; background: linear-gradient(90deg, #6366f1, #06b6d4); transition: width 0.4s ease; }
.od-note { margin-top: 14px; padding: 10px 12px; border-radius: 10px; background: #fde4e4; color: #b91c1c; font-size: 12.5px; }
.detail-list { display: flex; flex-direction: column; margin-top: 10px; }
.detail-row { padding: 10px 2px; border-bottom: 1px solid var(--line); }
.detail-row:last-of-type { border-bottom: none; }
.detail-main { display: flex; align-items: center; gap: 10px; font-size: 13.5px; flex-wrap: wrap; }
.detail-nums { color: var(--ink-2); font-variant-numeric: tabular-nums; }
.detail-total { text-align: right; font-size: 14px; padding: 10px 2px 0; }
.detail-total strong { font-size: 18px; color: var(--brand-strong); }
.evidence { margin-top: 8px; background: var(--surface-alt); border-radius: 10px; padding: 8px 12px; display: flex; flex-direction: column; gap: 5px; max-height: 220px; overflow: auto; }
.evidence-line { font-size: 12.5px; color: var(--ink-2); padding: 3px 0; border-bottom: 1px dashed var(--line); }
.evidence-line:last-child { border-bottom: none; }
.link-btn { border: none; background: none; color: var(--brand-strong); font-size: 12.5px; cursor: pointer; }
.loading-tip, .empty-tip { text-align: center; color: var(--ink-3); padding: 20px 0; font-size: 13px; }
.muted-sm { font-size: 12px; color: var(--ink-3); }
.tabs { display: flex; gap: 8px; margin-bottom: 16px; }
.tab { display: inline-flex; align-items: center; gap: 7px; padding: 8px 20px; border-radius: 999px; border: 1px solid var(--line); background: var(--surface); color: var(--ink-3); font-size: 13.5px; cursor: pointer; transition: all 0.2s ease; }
.tab svg { width: 15px; height: 15px; }
.tab:hover { border-color: #c7d2fe; color: #4f46e5; }
.tab.active { background: linear-gradient(135deg, #6366f1, #06b6d4); color: #fff; border-color: transparent; font-weight: 600; box-shadow: 0 4px 12px rgba(99, 102, 241, 0.35); }
.overlay { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); display: flex; align-items: center; justify-content: center; z-index: 60; padding: 16px; }
.modal { background: var(--surface); border-radius: 16px; padding: 22px 24px; width: 560px; max-width: 100%; max-height: 90vh; overflow: auto; }
.modal h2 { font-size: 16px; margin-bottom: 8px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 14px 0; }
.form-grid label { display: flex; flex-direction: column; gap: 6px; font-size: 12.5px; color: var(--ink-2); }
.form-grid input { padding: 8px 10px; border: 1px solid var(--line); border-radius: 8px; font-size: 13px; }
.result-card { background: var(--brand-soft); border: 1px solid var(--brand); border-radius: 12px; padding: 12px 14px; font-size: 13px; display: flex; flex-direction: column; gap: 6px; margin-bottom: 6px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; }
.payroll-table { display: block; overflow-x: auto; }

/* 高级感薪资榜 */
.staff-card { padding: 20px 22px; }
.staff-list { display: flex; flex-direction: column; }
.staff-row { display: flex; align-items: center; gap: 12px; padding: 14px 6px; border-bottom: 1px solid var(--line); }
.staff-row:last-child { border-bottom: none; }
.staff-row.done { background: linear-gradient(90deg, rgba(16, 185, 129, 0.05), transparent 40%); border-radius: 12px; }
.staff-no { width: 26px; height: 26px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; border-radius: 9px; font-size: 12px; font-weight: 800; background: var(--surface-alt); color: var(--ink-3); }
.staff-no.r1 { background: linear-gradient(135deg, #f59e0b, #f97316); color: #fff; }
.staff-no.r2 { background: linear-gradient(135deg, #6366f1, #8b5cf6); color: #fff; }
.staff-no.r3 { background: linear-gradient(135deg, #06b6d4, #10b981); color: #fff; }
.staff-avatar { width: 42px; height: 42px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; border-radius: 50%; background: linear-gradient(135deg, #eef2ff, #e0f2fe); color: #4338ca; font-weight: 800; font-size: 16px; }
.staff-main { flex: 1; min-width: 0; }
.staff-head { display: flex; align-items: center; gap: 8px; font-size: 14px; flex-wrap: wrap; }
.staff-head .lvl { font-size: 11px; font-weight: 700; padding: 1px 8px; border-radius: 999px; background: #eef2ff; color: #4338ca; }
.od-chip { font-size: 11px; font-weight: 700; padding: 2px 9px; border-radius: 999px; background: #fde4e4; color: #b91c1c; }
.staff-break { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 12px; color: var(--ink-3); margin-top: 4px; }
.bar-track { height: 6px; border-radius: 999px; background: var(--surface-alt); margin-top: 8px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 999px; background: linear-gradient(90deg, #6366f1, #06b6d4); transition: width 0.4s ease; }
.staff-side { text-align: right; flex-shrink: 0; display: flex; flex-direction: column; gap: 4px; align-items: flex-end; }
.staff-total { font-size: 18px; font-weight: 800; color: var(--brand-strong); }
</style>
