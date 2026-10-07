<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import PageHead from '@/components/PageHead.vue'
import { myPermissions } from '@/api/permissions'
import { useAuthStore } from '@/stores/auth'
import PersonalizeView from '@/views/settings/PersonalizeView.vue'
import LLMConfigTab from '@/views/settings/LLMConfigTab.vue'
import {
  createCampus,
  createSubject,
  getFinanceSetting,
  listCampuses,
  listSubjects,
  reorderCampuses,
  updateCampus,
  updateFinanceSetting,
  updateSubject,
  type CampusOut,
  type SubjectOut,
} from '@/api/business'
import {
  createPost,
  createTeacherLevel,
  deleteTeacherLevel,
  listCommissionRules,
  listPosts,
  listTeacherLevels,
  updateCommissionRules,
  updatePost,
  updateTeacherLevel,
  type CommissionRuleOut,
  type PostOut,
  type TeacherLevelOut,
} from '@/api/payroll'

const activeTab = ref<'personalize' | 'business' | 'llm'>('personalize')

// 设置 tab 可见与操作：教师按 settings_tab_* 键（settings_manage 为总开关）
const myPerms = ref<Record<string, boolean>>({})
const canSet = (key: string): boolean => {
  if (auth.user?.role !== 'teacher') return true
  return myPerms.value[key] === true || myPerms.value.settings_manage === true
}
const visibleTabs = computed(() => ({
  personalize: canSet('settings_tab_personalize'),
  llm: canSet('settings_tab_model'),
  business: canSet('settings_tab_business'),
}))

// ---- 校区 ----
const campuses = ref<CampusOut[]>([])
const newCampus = ref('')
const editingCampus = ref<CampusOut | null>(null)
const editCampusName = ref('')

// ---- 科目 ----
const subjects = ref<SubjectOut[]>([])
const newSubject = ref({ name: '', per_session: '2', commission_rate: '' })
const editingSubject = ref<SubjectOut | null>(null)
const editSubject = ref({ name: '', per_session: '2', commission_rate: '', useGlobal: true })

// ---- 财务 ----
const commissionDefault = ref('0.30')
const overdraftMax = ref('10')
const financeNote = ref('')
const formulas = ref({ revenue: '', commission: '', net: '' })

// ---- 教师级别 ----
const levels = ref<TeacherLevelOut[]>([])
const newLevel = ref({ name: '', ratioPct: '10' })
const editingLevel = ref<TeacherLevelOut | null>(null)
const editLevel = ref({ name: '', ratioPct: '10' })

// ---- 职务工资 ----
const posts = ref<PostOut[]>([])
const newPost = ref({ name: '', baseSalary: '' })
const editingPost = ref<PostOut | null>(null)
const editPost = ref({ name: '', baseSalary: '' })

// ---- 提成规则 ----
const rules = ref<CommissionRuleOut[]>([])

const msg = ref('')
const error = ref('')

function flash(text: string) {
  msg.value = text
  setTimeout(() => (msg.value = ''), 3000)
}

const auth = useAuthStore()

async function loadAll() {
  error.value = ''
  try {
    const [c, s, f, lv, ps, rl] = await Promise.all([
      listCampuses(true),
      listSubjects(true),
      getFinanceSetting(),
      listTeacherLevels(true),
      listPosts(),
      listCommissionRules(),
    ])
    campuses.value = c
    subjects.value = s
    commissionDefault.value = f.commission_default
    overdraftMax.value = f.overdraft_max ?? '10'
    financeNote.value = f.note || ''
    if (f.formula) formulas.value = f.formula
    levels.value = lv
    posts.value = ps
    rules.value = rl
  } catch {
    error.value = '加载业务设置失败'
  }
}

async function addCampus() {
  const name = newCampus.value.trim()
  if (!name) return
  try {
    await createCampus(name)
    newCampus.value = ''
    campuses.value = await listCampuses(true)
    flash('校区已新增')
  } catch (e: any) {
    alert(e?.response?.data?.detail || '新增失败')
  }
}

function startEditCampus(c: CampusOut) {
  editingCampus.value = c
  editCampusName.value = c.name
}

async function saveCampus() {
  if (!editingCampus.value) return
  try {
    await updateCampus(editingCampus.value.id, { name: editCampusName.value.trim() })
    editingCampus.value = null
    campuses.value = await listCampuses(true)
    flash('校区已更新')
  } catch (e: any) {
    alert(e?.response?.data?.detail || '保存失败')
  }
}

async function toggleCampus(c: CampusOut) {
  try {
    await updateCampus(c.id, { active: !c.active })
    campuses.value = await listCampuses(true)
  } catch (e: any) {
    alert(e?.response?.data?.detail || '操作失败')
  }
}

async function moveCampus(i: number, delta: number) {
  const j = i + delta
  if (j < 0 || j >= campuses.value.length) return
  const ids = campuses.value.map((c) => c.id)
  ;[ids[i], ids[j]] = [ids[j], ids[i]]
  try {
    campuses.value = await reorderCampuses(ids)
    flash('校区顺序已更新')
  } catch (e: any) {
    alert(e?.response?.data?.detail || '排序失败')
  }
}

async function addSubject() {
  const name = newSubject.value.name.trim()
  if (!name) return
  try {
    await createSubject({
      name,
      per_session: newSubject.value.per_session || '2',
      commission_rate: newSubject.value.commission_rate || null,
    })
    newSubject.value = { name: '', per_session: '2', commission_rate: '' }
    subjects.value = await listSubjects(true)
    flash('科目已新增')
  } catch (e: any) {
    alert(e?.response?.data?.detail || '新增失败')
  }
}

function startEditSubject(s: SubjectOut) {
  editingSubject.value = s
  editSubject.value = {
    name: s.name,
    per_session: s.per_session,
    commission_rate: s.commission_rate || '',
    useGlobal: s.commission_rate === null,
  }
}

async function saveSubject() {
  if (!editingSubject.value) return
  try {
    await updateSubject(editingSubject.value.id, {
      name: editSubject.value.name.trim(),
      per_session: editSubject.value.per_session,
      commission_rate: editSubject.value.useGlobal ? null : editSubject.value.commission_rate || null,
      commission_rate_set: true,
    })
    editingSubject.value = null
    subjects.value = await listSubjects(true)
    flash('科目已更新')
  } catch (e: any) {
    alert(e?.response?.data?.detail || '保存失败')
  }
}

async function toggleSubject(s: SubjectOut) {
  try {
    await updateSubject(s.id, { active: !s.active })
    subjects.value = await listSubjects(true)
  } catch (e: any) {
    alert(e?.response?.data?.detail || '操作失败')
  }
}

async function saveFinance() {
  try {
    const out = await updateFinanceSetting({
      commission_default: commissionDefault.value,
      overdraft_max: overdraftMax.value,
      note: financeNote.value || null,
    })
    commissionDefault.value = out.commission_default
    overdraftMax.value = out.overdraft_max ?? '10'
    financeNote.value = out.note || ''
    flash('财务设置已保存（新消耗按此比例记账，历史账本不变）')
  } catch (e: any) {
    alert(e?.response?.data?.detail || '保存失败')
  }
}

function pctToRatio(pct: string): string {
  return (Number(pct || 0) / 100).toFixed(4)
}

async function addLevel() {
  const name = newLevel.value.name.trim()
  if (!name) return
  try {
    await createTeacherLevel({ name, ratio: pctToRatio(newLevel.value.ratioPct) })
    newLevel.value = { name: '', ratioPct: '10' }
    levels.value = await listTeacherLevels(true)
    flash('教师级别已新增')
  } catch (e: any) {
    alert(e?.response?.data?.detail || '新增失败')
  }
}

function startEditLevel(l: TeacherLevelOut) {
  editingLevel.value = l
  editLevel.value = { name: l.name, ratioPct: l.ratio_pct }
}

async function saveLevel() {
  if (!editingLevel.value) return
  try {
    await updateTeacherLevel(editingLevel.value.id, {
      name: editLevel.value.name.trim(),
      ratio: pctToRatio(editLevel.value.ratioPct),
    })
    editingLevel.value = null
    levels.value = await listTeacherLevels(true)
    flash('教师级别已更新（新增账本按新比例，历史账本不变）')
  } catch (e: any) {
    alert(e?.response?.data?.detail || '保存失败')
  }
}

async function removeLevel(l: TeacherLevelOut) {
  if (!confirm(`确认删除级别「${l.name}」？被教师使用时不可删除。`)) return
  try {
    await deleteTeacherLevel(l.id)
    levels.value = await listTeacherLevels(true)
    flash('级别已删除')
  } catch (e: any) {
    alert(e?.response?.data?.detail || '删除失败')
  }
}

async function addPost() {
  const name = newPost.value.name.trim()
  if (!name) return
  try {
    const out = await createPost({ name, base_salary: newPost.value.baseSalary || '0' })
    newPost.value = { name: '', baseSalary: '' }
    posts.value = await listPosts()
    flash(out.hint || '职务已新增（权限默认全关，请到权限管理授权）')
  } catch (e: any) {
    alert(e?.response?.data?.detail || '新增失败')
  }
}

function startEditPost(p: PostOut) {
  editingPost.value = p
  editPost.value = { name: p.name, baseSalary: p.base_salary }
}

async function savePost() {
  if (!editingPost.value) return
  try {
    await updatePost(editingPost.value.id, {
      name: editPost.value.name.trim(),
      base_salary: editPost.value.baseSalary || '0',
    })
    editingPost.value = null
    posts.value = await listPosts()
    flash('职务工资已更新（与权限管理职务预设同源）')
  } catch (e: any) {
    alert(e?.response?.data?.detail || '保存失败')
  }
}

async function saveRules() {
  try {
    rules.value = await updateCommissionRules(
      rules.value.map((r) => ({ key: r.key, label: r.label, amount: r.amount, unit: r.unit })),
    )
    flash('提成规则已保存（薪资核算按新单价）')
  } catch (e: any) {
    alert(e?.response?.data?.detail || '保存失败')
  }
}

onMounted(async () => {
  if (auth.user?.role === 'teacher') {
    try {
      myPerms.value = await myPermissions()
    } catch {
      myPerms.value = {}
    }
    const first = (['personalize', 'llm', 'business'] as const).find((t) => visibleTabs.value[t])
    if (first) activeTab.value = first
  }
  await loadAll()
})
</script>

<template>
  <div>
    <PageHead
      title="设置"
      eyebrow="SETTINGS"
      sub="个性化外观 · 校区与科目等业务基础资料 · 财务参数"
    >
      <template #actions>
      <div class="tabs">
        <button v-if="visibleTabs.personalize" class="tab" :class="{ active: activeTab === 'personalize' }" @click="activeTab = 'personalize'">
          个性化设置
        </button>
        <button v-if="visibleTabs.llm" class="tab" :class="{ active: activeTab === 'llm' }" @click="activeTab = 'llm'">
          模型配置
        </button>
        <button v-if="visibleTabs.business" class="tab" :class="{ active: activeTab === 'business' }" @click="activeTab = 'business'">
          业务功能设置
        </button>
      </div>
      </template>
    </PageHead>

    <p v-if="error" class="error-banner">{{ error }}</p>
    <p v-if="msg" class="success-banner">{{ msg }}</p>

    <PersonalizeView v-if="activeTab === 'personalize' && visibleTabs.personalize" embedded />

    <LLMConfigTab v-else-if="activeTab === 'llm' && visibleTabs.llm" />

    <div v-else-if="visibleTabs.business" class="biz">
      <!-- 校区 -->
      <section class="card">
        <h2>校区名称</h2>
        <p class="muted">学员/教师/班级的校区下拉数据源，可增删改（停用即隐藏）；↑↓ 调整顺序，各处校区筛选项即时跟随。</p>
        <div class="add-row">
          <input v-model="newCampus" type="text" placeholder="如：三校" @keyup.enter="addCampus" />
          <button class="btn primary sm" @click="addCampus">新增校区</button>
        </div>
        <div class="tag-list">
          <div v-for="(c, i) in campuses" :key="c.id" class="tag-item" :class="{ off: !c.active }">
            <template v-if="editingCampus?.id === c.id">
              <input v-model="editCampusName" type="text" class="inline-input" @keyup.enter="saveCampus" />
              <button class="link-btn" @click="saveCampus">保存</button>
              <button class="link-btn muted" @click="editingCampus = null">取消</button>
            </template>
            <template v-else>
              <span class="order-btns">
                <button class="link-btn" :disabled="i === 0" title="上移" @click="moveCampus(i, -1)">↑</button>
                <button class="link-btn" :disabled="i === campuses.length - 1" title="下移" @click="moveCampus(i, 1)">↓</button>
              </span>
              <span class="tag-name">{{ c.name }}</span>
              <button class="link-btn" @click="startEditCampus(c)">改名</button>
              <button class="link-btn" @click="toggleCampus(c)">{{ c.active ? '停用' : '启用' }}</button>
            </template>
          </div>
        </div>
      </section>

      <!-- 科目 -->
      <section class="card">
        <h2>常规课科目</h2>
        <p class="muted">课时包/班级/排课的科目来源；每次课消耗课时数决定考勤扣减与创收，抽成比例决定教师绩效（留空用全局默认）。</p>
        <div class="add-row grid4">
          <input v-model="newSubject.name" type="text" placeholder="科目名称，如：Python" @keyup.enter="addSubject" />
          <input v-model="newSubject.per_session" type="number" min="0.5" step="0.5" title="每次课消耗课时数" />
          <input v-model="newSubject.commission_rate" type="number" min="0" max="1" step="0.01" placeholder="抽成0~1（空=全局）" />
          <button class="btn primary sm" @click="addSubject">新增科目</button>
        </div>
        <table class="mini-table">
          <thead><tr><th>科目</th><th>每次课消耗</th><th>教师抽成</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="s in subjects" :key="s.id" :class="{ off: !s.active }">
              <template v-if="editingSubject?.id === s.id">
                <td><input v-model="editSubject.name" type="text" class="inline-input" /></td>
                <td><input v-model="editSubject.per_session" type="number" min="0.5" step="0.5" class="inline-input num" /></td>
                <td>
                  <label class="check"><input v-model="editSubject.useGlobal" type="checkbox" />全局默认</label>
                  <input
                    v-model="editSubject.commission_rate"
                    type="number"
                    min="0"
                    max="1"
                    step="0.01"
                    class="inline-input num"
                    :disabled="editSubject.useGlobal"
                  />
                </td>
                <td>{{ s.active ? '启用' : '停用' }}</td>
                <td>
                  <button class="link-btn" @click="saveSubject">保存</button>
                  <button class="link-btn muted" @click="editingSubject = null">取消</button>
                </td>
              </template>
              <template v-else>
                <td><strong>{{ s.name }}</strong></td>
                <td>{{ s.per_session }} 课时/次</td>
                <td>{{ s.commission_rate === null ? '全局默认' : `${(Number(s.commission_rate) * 100).toFixed(0)}%` }}</td>
                <td>{{ s.active ? '启用' : '停用' }}</td>
                <td>
                  <button class="link-btn" @click="startEditSubject(s)">编辑</button>
                  <button class="link-btn" @click="toggleSubject(s)">{{ s.active ? '停用' : '启用' }}</button>
                </td>
              </template>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- 财务 -->
      <section class="card">
        <h2>财务设置</h2>
        <p class="muted">科目未单独设置抽成时使用全局默认。公式固定：</p>
        <ul class="formula">
          <li>{{ formulas.revenue || '创收 = Σ 消耗课时 × 消耗瞬间FIFO单价' }}</li>
          <li>{{ formulas.commission || '教师绩效 = 消耗金额 × 科目抽成' }}</li>
          <li>{{ formulas.net || '公司实收 = 创收 − 教师绩效 − 退款' }}</li>
        </ul>
        <div class="add-row">
          <label class="field-inline">全局默认抽成
            <input v-model="commissionDefault" type="number" min="0" max="1" step="0.01" class="inline-input num" />
          </label>
          <label class="field-inline">允许透支（课时）
            <input v-model="overdraftMax" type="number" min="0" max="100" step="0.5" class="inline-input num" title="学员余额最低可到负多少，欠费仍可上课" />
          </label>
          <input v-model="financeNote" type="text" placeholder="备注（可选）" class="grow" />
          <button class="btn primary sm" @click="saveFinance">保存财务设置</button>
        </div>
      </section>

      <!-- 教师级别 -->
      <section class="card">
        <h2>教师级别</h2>
        <p class="muted">上课教师的绩效档位：每消耗 1 课时，按单价 × 绩效比例计教师绩效，剩余为公司课时盈收。抽成优先级：教师级别 ＞ 科目 ＞ 全局默认。</p>
        <div class="add-row grid4">
          <input v-model="newLevel.name" type="text" placeholder="级别名称，如：P1" @keyup.enter="addLevel" />
          <input v-model="newLevel.ratioPct" type="number" min="0" max="100" step="0.5" placeholder="绩效比例%" />
          <button class="btn primary sm" @click="addLevel">新增级别</button>
        </div>
        <table class="mini-table">
          <thead><tr><th>级别</th><th>绩效比例</th><th>含义</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="l in levels" :key="l.id">
              <template v-if="editingLevel?.id === l.id">
                <td><input v-model="editLevel.name" type="text" class="inline-input" /></td>
                <td><input v-model="editLevel.ratioPct" type="number" min="0" max="100" step="0.5" class="inline-input num" /> %</td>
                <td class="muted-sm">每课时绩效 {{ editLevel.ratioPct }}%，盈收 {{ (100 - Number(editLevel.ratioPct || 0)).toFixed(1) }}%</td>
                <td>
                  <button class="link-btn" @click="saveLevel">保存</button>
                  <button class="link-btn muted" @click="editingLevel = null">取消</button>
                </td>
              </template>
              <template v-else>
                <td><strong>{{ l.name }}</strong></td>
                <td>{{ l.ratio_pct }}%</td>
                <td class="muted-sm">每课时绩效 {{ l.ratio_pct }}%，盈收 {{ (100 - Number(l.ratio_pct)).toFixed(1) }}%</td>
                <td>
                  <button class="link-btn" @click="startEditLevel(l)">改名/调比</button>
                  <button class="link-btn danger" @click="removeLevel(l)">删除</button>
                </td>
              </template>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- 职务工资 -->
      <section class="card">
        <h2>职务与基本工资</h2>
        <p class="muted">与权限管理「职务预设」同源：此处可新建职务并设基本工资（新职务权限默认全关，需回权限管理授权）；薪资核算时人员基本工资优先取个人设置，其次取职务工资。</p>
        <div class="add-row grid4">
          <input v-model="newPost.name" type="text" placeholder="职务名称，如：教务专员" @keyup.enter="addPost" />
          <input v-model="newPost.baseSalary" type="number" min="0" step="100" placeholder="基本工资（元/月）" />
          <button class="btn primary sm" @click="addPost">新增职务</button>
        </div>
        <table class="mini-table">
          <thead><tr><th>职务</th><th>基本工资（元/月）</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="p in posts" :key="p.id">
              <template v-if="editingPost?.id === p.id">
                <td><input v-model="editPost.name" type="text" class="inline-input" /></td>
                <td><input v-model="editPost.baseSalary" type="number" min="0" step="100" class="inline-input num" /></td>
                <td>
                  <button class="link-btn" @click="savePost">保存</button>
                  <button class="link-btn muted" @click="editingPost = null">取消</button>
                </td>
              </template>
              <template v-else>
                <td><strong>{{ p.name }}</strong></td>
                <td>¥{{ Number(p.base_salary).toLocaleString('zh-CN') }}</td>
                <td><button class="link-btn" @click="startEditPost(p)">编辑</button></td>
              </template>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- 提成规则 -->
      <section class="card">
        <h2>提成规则</h2>
        <p class="muted">教务工作台薪资核算的单价口径：招生人头奖、体验课提成、转化/续费提成、口碑奖。</p>
        <table class="mini-table">
          <thead><tr><th>项目</th><th>单价（元）</th><th>单位</th></tr></thead>
          <tbody>
            <tr v-for="r in rules" :key="r.key">
              <td><strong>{{ r.label }}</strong><span class="muted-sm">（{{ r.key }}）</span></td>
              <td><input v-model="r.amount" type="number" min="0" step="1" class="inline-input num" /></td>
              <td>{{ r.unit }}</td>
            </tr>
          </tbody>
        </table>
        <div class="add-row"><button class="btn primary sm" @click="saveRules">保存提成规则</button></div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.tabs {
  display: flex;
  gap: 8px;
}
.tab {
  padding: 8px 20px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-3);
  font-size: 13.5px;
  cursor: pointer;
}
.tab.active {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  border-color: transparent;
  font-weight: 600;
}

.error-banner {
  background: var(--danger-soft);
  color: var(--danger);
  padding: 10px 14px;
  border-radius: 10px;
  margin-bottom: 14px;
  font-size: 13px;
}
.success-banner {
  background: var(--success-soft);
  color: var(--success);
  padding: 10px 14px;
  border-radius: 10px;
  margin-bottom: 14px;
  font-size: 13px;
}

.biz {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 20px 22px;
}
.card h2 {
  font-size: 16px;
  margin-bottom: 4px;
}
.muted {
  font-size: 12.5px;
  color: var(--ink-3);
  margin-bottom: 14px;
}
.add-row {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.add-row input[type='text'],
.add-row input[type='number'] {
  padding: 8px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  font-size: 13px;
  background: var(--surface);
  color: var(--ink);
}
.add-row input[type='text'] {
  width: 220px;
}
.grid4 input {
  width: 150px;
}
.grow {
  flex: 1;
  min-width: 160px;
}
.btn {
  padding: 8px 16px;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  border: none;
}
.btn.primary {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
}
.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.tag-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  border: 1px solid var(--line);
  border-radius: 999px;
  font-size: 13px;
  background: var(--surface-alt);
}
.tag-item.off {
  opacity: 0.55;
}
.order-btns {
  display: inline-flex;
  gap: 2px;
}
.order-btns .link-btn:disabled {
  opacity: 0.3;
  cursor: default;
}
.tag-name {
  font-weight: 600;
}
.link-btn {
  border: none;
  background: none;
  color: var(--brand-strong);
  font-size: 12.5px;
  cursor: pointer;
  padding: 0;
}
.link-btn.muted {
  color: var(--ink-3);
}
.link-btn.danger {
  color: var(--danger);
}
.inline-input {
  padding: 6px 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  font-size: 13px;
  width: 140px;
  background: var(--surface);
  color: var(--ink);
}
.inline-input.num {
  width: 90px;
}
.mini-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.mini-table th {
  text-align: left;
  font-size: 12px;
  color: var(--ink-3);
  font-weight: 600;
  padding: 8px 10px;
  border-bottom: 1px solid var(--line);
}
.mini-table td {
  padding: 9px 10px;
  border-bottom: 1px solid #f1f5f9;
}
.mini-table tr:last-child td {
  border-bottom: none;
}
.mini-table tr.off td {
  opacity: 0.55;
}
.check {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12.5px;
  color: var(--ink-3);
  margin-right: 8px;
}
.formula {
  margin: 0 0 14px 18px;
  font-size: 13px;
  color: var(--ink-2);
  line-height: 1.8;
}
.field-inline {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--ink-2);
}
</style>
