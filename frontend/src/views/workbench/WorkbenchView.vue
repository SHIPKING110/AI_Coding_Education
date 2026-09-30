<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import PageHead from '@/components/PageHead.vue'
import {
  computePayroll,
  getWorkbench,
  listPayroll,
  type WorkbenchItem,
} from '@/api/payroll'

const month = ref(new Date().toISOString().slice(0, 7))
const items = ref<WorkbenchItem[]>([])
const rules = ref<Record<string, string>>({})
const loading = ref(false)
const error = ref('')
const msg = ref('')

const roleFilter = ref('')
const keyword = ref('')

// 核算弹窗
const showCompute = ref(false)
const target = ref<WorkbenchItem | null>(null)
const form = ref({
  invite_count: 0,
  trial_count: 0,
  convert_count: 0,
  renew_count: 0,
  refer_count: 0,
  trial_lesson_count: 0,
  lesson_commission: '',
})
const computing = ref(false)
const result = ref<Record<string, string> | null>(null)
const entries = ref<Record<string, unknown>[]>([])

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

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [wb, pr] = await Promise.all([
      getWorkbench(month.value),
      listPayroll(month.value).catch(() => ({ items: [] })),
    ])
    items.value = wb.items
    rules.value = wb.rules
    entries.value = (pr as { items: Record<string, unknown>[] }).items || []
  } catch {
    error.value = '加载教务工作台失败'
  } finally {
    loading.value = false
  }
}

const filtered = computed(() =>
  items.value.filter((u) => {
    if (roleFilter.value && u.role !== roleFilter.value) return false
    if (keyword.value && !u.name.includes(keyword.value.trim())) return false
    return true
  }),
)

const totals = computed(() => {
  const t = { base: 0, total: 0, count: filtered.value.length, computed: 0 }
  for (const u of filtered.value) {
    t.base += Number(u.base_salary || 0)
    t.total += Number(u.total || 0)
    if (u.has_entry) t.computed += 1
  }
  return t
})

const entryOf = (uid: string) => entries.value.find((e) => e.user_id === uid) as Record<string, string> | undefined

function openCompute(u: WorkbenchItem) {
  target.value = u
  const e = entryOf(u.user_id)
  form.value = {
    invite_count: Number(e?.invite_count || 0),
    trial_count: Number(e?.trial_count || 0),
    convert_count: Number(e?.convert_count || 0),
    renew_count: Number(e?.renew_count || 0),
    refer_count: Number(e?.refer_count || 0),
    trial_lesson_count: 0,
    lesson_commission: String(e?.lesson_commission || ''),
  }
  result.value = null
  showCompute.value = true
}

async function submitCompute() {
  if (!target.value) return
  computing.value = true
  try {
    result.value = await computePayroll({
      user_id: target.value.user_id,
      month: month.value,
      invite_count: form.value.invite_count,
      trial_count: form.value.trial_count,
      convert_count: form.value.convert_count,
      renew_count: form.value.renew_count,
      refer_count: form.value.refer_count,
      trial_lesson_count: form.value.trial_lesson_count,
      lesson_commission: form.value.lesson_commission || '0',
    })
    flash(`已核算 ${target.value.name} ${month.value} 薪资 ¥${Number(result.value.total).toLocaleString('zh-CN')}`)
    await load()
  } catch (e: any) {
    alert(e?.response?.data?.detail || '核算失败')
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
  <div class="workbench">
    <PageHead
      title="教务工作台"
      eyebrow="WORKBENCH"
      sub="招生邀约 · 体验课 · 转化续费 · 口碑 — 教务与教师双薪资体系核算"
    />

    <div class="filter-bar">
      <input v-model="month" type="month" class="filter-input" @change="load" />
      <select v-model="roleFilter" class="filter-select" @change="() => {}">
        <option value="">教务 + 教师</option>
        <option value="staff">仅教务</option>
        <option value="teacher">仅教师</option>
      </select>
      <input v-model="keyword" type="text" class="filter-input" placeholder="按姓名筛选" />
      <button class="btn primary sm" @click="load">刷新</button>
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
    </div>

    <!-- 人员薪资表 -->
    <section class="card">
      <div class="card-title">{{ month }} 薪资总览</div>
      <div v-if="loading" class="loading-tip">加载中…</div>
      <div v-else-if="filtered.length === 0" class="empty-tip">暂无人员（先在教师管理/账号中添加教务与教师）</div>
      <table v-else class="mini-table payroll-table">
        <thead>
          <tr>
            <th>姓名</th><th>角色</th><th>职务</th><th>校区</th><th>级别</th>
            <th>基本工资</th><th>课时绩效</th><th>邀约/体验</th><th>转化</th><th>续费</th><th>口碑</th>
            <th>应发合计</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in filtered" :key="u.user_id" :class="{ done: u.has_entry }">
            <td><strong>{{ u.name }}</strong></td>
            <td><span class="pill" :class="u.role === 'staff' ? 'campus' : 'title-pill'">{{ roleLabel(u.role) }}</span></td>
            <td>{{ u.title || '—' }}</td>
            <td>{{ u.campus || '—' }}</td>
            <td>{{ u.level || '—' }}</td>
            <td>¥{{ money(u.base_salary) }}</td>
            <td>{{ entryOf(u.user_id) ? `¥${money(entryOf(u.user_id)?.lesson_commission)}` : '—' }}</td>
            <td>
              <template v-if="entryOf(u.user_id)">
                {{ entryOf(u.user_id)?.invite_count }}人/¥{{ money(entryOf(u.user_id)?.invite_bonus) }} ·
                {{ entryOf(u.user_id)?.trial_count }}人/¥{{ money(entryOf(u.user_id)?.trial_bonus) }}
              </template>
              <span v-else>—</span>
            </td>
            <td>{{ entryOf(u.user_id) ? `${entryOf(u.user_id)?.convert_count}单/¥${money(entryOf(u.user_id)?.convert_bonus)}` : '—' }}</td>
            <td>{{ entryOf(u.user_id) ? `${entryOf(u.user_id)?.renew_count}单/¥${money(entryOf(u.user_id)?.renew_bonus)}` : '—' }}</td>
            <td>{{ entryOf(u.user_id) ? `${entryOf(u.user_id)?.refer_count}人/¥${money(entryOf(u.user_id)?.refer_bonus)}` : '—' }}</td>
            <td class="hl">¥{{ money(u.total) }}</td>
            <td><button class="link-btn" @click="openCompute(u)">{{ u.has_entry ? '重新核算' : '核算' }}</button></td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 核算弹窗 -->
    <div v-if="showCompute && target" class="overlay" @click.self="showCompute = false">
      <div class="modal">
        <h2>薪资核算 · {{ target.name }} · {{ month }}</h2>
        <p class="muted-sm">基本工资 ¥{{ money(target.base_salary) }}（个人设置优先，其次职务工资）＋ 课时绩效 ＋ 以下提成按单价自动计算</p>
        <div class="form-grid">
          <label>电话意向人头数<input v-model.number="form.invite_count" type="number" min="0" /></label>
          <label>到场体验人数<input v-model.number="form.trial_count" type="number" min="0" /></label>
          <label>体验课课时提成人数（教师）<input v-model.number="form.trial_lesson_count" type="number" min="0" /></label>
          <label>体验转化报名单数<input v-model.number="form.convert_count" type="number" min="0" /></label>
          <label>续费单数<input v-model.number="form.renew_count" type="number" min="0" /></label>
          <label>转介绍人头数<input v-model.number="form.refer_count" type="number" min="0" /></label>
          <label>课时绩效金额（教师所耗课时提成）<input v-model="form.lesson_commission" type="number" min="0" step="0.01" /></label>
        </div>
        <div v-if="result" class="result-card">
          <div>基本工资 ¥{{ money(result.base_salary) }} ＋ 课时绩效 ¥{{ money(result.lesson_commission) }}</div>
          <div>邀约奖 ¥{{ money(result.invite_bonus) }} · 体验 ¥{{ money(result.trial_bonus) }} · 转化 ¥{{ money(result.convert_bonus) }} · 续费 ¥{{ money(result.renew_bonus) }} · 口碑 ¥{{ money(result.refer_bonus) }}</div>
          <strong>应发合计 ¥{{ money(result.total) }}</strong>
        </div>
        <div class="modal-actions">
          <button class="btn ghost" @click="showCompute = false">关闭</button>
          <button class="btn primary" :disabled="computing" @click="submitCompute">{{ computing ? '核算中…' : '确认核算' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.workbench { position: relative; }
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
.link-btn { border: none; background: none; color: var(--brand-strong); font-size: 12.5px; cursor: pointer; }
.loading-tip, .empty-tip { text-align: center; color: var(--ink-3); padding: 20px 0; font-size: 13px; }
.muted-sm { font-size: 12px; color: var(--ink-3); }
.overlay { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); display: flex; align-items: center; justify-content: center; z-index: 60; padding: 16px; }
.modal { background: var(--surface); border-radius: 16px; padding: 22px 24px; width: 560px; max-width: 100%; max-height: 90vh; overflow: auto; }
.modal h2 { font-size: 16px; margin-bottom: 8px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 14px 0; }
.form-grid label { display: flex; flex-direction: column; gap: 6px; font-size: 12.5px; color: var(--ink-2); }
.form-grid input { padding: 8px 10px; border: 1px solid var(--line); border-radius: 8px; font-size: 13px; }
.result-card { background: var(--brand-soft); border: 1px solid var(--brand); border-radius: 12px; padding: 12px 14px; font-size: 13px; display: flex; flex-direction: column; gap: 6px; margin-bottom: 6px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; }
.payroll-table { display: block; overflow-x: auto; }
</style>
