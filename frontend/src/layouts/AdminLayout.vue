<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'

import { getUnreadCount, listNotifications, markNotificationRead, type NotificationOut } from '@/api/client'
import { myPermissions } from '@/api/permissions'
import { useAiTasksStore } from '@/stores/aiTasks'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import BrandLogo from '@/components/BrandLogo.vue'
import { fmtDateTimeFromIso } from '@/utils/date'

const auth = useAuthStore()
const theme = useThemeStore()

/** 教师本人的操作权限（仅教师加载；用于订单入口显隐） */
const teacherPerms = ref<Record<string, boolean>>({})
async function refreshTeacherPerms() {
  if (auth.user?.role !== 'teacher') return
  try {
    teacherPerms.value = await myPermissions()
  } catch {
    teacherPerms.value = {}
  }
}
const router = useRouter()
const route = useRoute()

const aiTasks = useAiTasksStore()
const isAdmin = computed(() => auth.isRole(['admin']))
const collapsed = ref(false)

// —— 全局 AI 任务完成通知（按任务来源分流跳转） ——
const aiToastVisible = ref(false)
const aiToastTitle = ref('')
const aiToastSub = ref('')
const aiToastTarget = ref<{ name: string; query?: Record<string, string> } | null>(null)
let aiToastTimer: number | null = null

/** 按任务类型决定跳转目标：习题任务 → AI 习题；评估/班级 PPT → 学员评估（班级 PPT 自动打开面板） */
function routeForTask(t: { taskKind?: string; kind?: string; result?: unknown; summary?: string }) {
  if (t.taskKind === 'evaluation') {
    const kind = String((t as { kind?: string }).kind ?? '')
    if (kind === 'class_parent_ppt' || kind === 'class_parent_ppt_refine') {
      const r = (t.result ?? {}) as Record<string, unknown>
      const q: Record<string, string> = { openClassPpt: '1' }
      if (typeof r.class_id === 'string' && r.class_id) q.ppt_class_id = r.class_id
      if (typeof r.period_start === 'string' && r.period_start) q.ppt_start = r.period_start.slice(0, 10)
      if (typeof r.period_end === 'string' && r.period_end) q.ppt_end = r.period_end.slice(0, 10)
      return { name: 'evaluations', query: q }
    }
    return { name: 'evaluations' }
  }
  return { name: 'assignments' }
}

/** 浮窗主跳转：哪类任务多去哪类页面（持平时优先习题，保持老行为） */
function goFloatMain() {
  if (aiTasks.evaluationRunningCount > aiTasks.assignmentRunningCount) {
    router.push({ name: 'evaluations', query: { openClassPpt: '1' } })
  } else {
    router.push({ name: 'assignments' })
  }
}

function goFloatAssignments() {
  router.push({ name: 'assignments' })
}

function goFloatEvaluations() {
  router.push({ name: 'evaluations', query: { openClassPpt: '1' } })
}

function goToastTarget() {
  const target = aiToastTarget.value
  aiToastVisible.value = false
  aiTasks.dismissDone()
  if (target) router.push(target)
  else router.push({ name: 'assignments' })
}

watch(
  () => aiTasks.latestDone,
  (t) => {
    if (!t) return
    if (aiToastTimer !== null) {
      window.clearTimeout(aiToastTimer)
    }
    const tt = t as unknown as { taskKind?: string; kind?: string; summary?: string }
    aiToastTarget.value = routeForTask(tt)
    const kind = String(tt.kind ?? '')
    if (tt.taskKind === 'evaluation') {
      if (kind === 'class_parent_ppt' || kind === 'class_parent_ppt_refine') {
        aiToastTitle.value = '班级家长会 PPT 已生成'
        aiToastSub.value = '点击查看本班 PPT 并下载：' + (tt.summary || '')
      } else if (kind === 'evaluation_refine') {
        aiToastTitle.value = '评估优化完成'
        aiToastSub.value = '点击回学员评估查看回填内容：' + (tt.summary || '')
      } else {
        aiToastTitle.value = '评估草稿已生成'
        aiToastSub.value = '点击回学员评估查看回填内容：' + (tt.summary || '')
      }
    } else {
      aiToastTitle.value = 'AI 生成完成'
      aiToastSub.value =
        kind === 'refine' ? '优化任务已完成：' + (tt.summary || '') : '可查看并加入作业：' + (tt.summary || '')
    }
    aiToastVisible.value = true
    aiToastTimer = window.setTimeout(() => {
      aiToastVisible.value = false
      aiTasks.dismissDone()
    }, 6000)
  },
)

function goAssignments() {
  router.push({ name: 'assignments' })
}

function goProfile() {
  router.push({ name: 'profile' })
}

async function onLogout() {
  await auth.logout()
  aiTasks.clear()
  router.push({ name: 'login' })
}

// 进入布局即恢复进行中的 AI 任务（刷新页面也不丢）
onMounted(() => {
  aiTasks.bootstrap()
  refreshNotifications()
  refreshTeacherPerms()
  notiTimer = window.setInterval(refreshNotifications, 30_000)
})

onBeforeUnmount(() => {
  if (notiTimer !== null) window.clearInterval(notiTimer)
})

// —— 教师端站内通知（学员提交作业提醒等）：顶栏铃铛 + 下拉面板 ——
const unreadCount = ref(0)
const notis = ref<NotificationOut[]>([])
const showNotiPop = ref(false)
const bellBtn = ref<HTMLElement | null>(null)
const popStyle = ref<Record<string, string>>({})
let notiTimer: number | null = null

const SUBMISSION_TYPE = 'submission_submitted'

/** 通知的提交状态：todo=有待批改内容可跳、done=已处理完（再次点击只进列表）、invalid=提交已不存在 */
function notiState(n: NotificationOut): 'todo' | 'done' | 'invalid' {
  if (n.type !== SUBMISSION_TYPE) return 'todo'
  const data = (n.data ?? {}) as Record<string, unknown>
  const reviewedAt = typeof data.reviewed_at === 'string' ? data.reviewed_at : ''
  const status = typeof data.submission_status === 'string' ? data.submission_status : ''
  if (status === 'missing' || reviewedAt && status === 'missing') return 'invalid'
  if (status === 'graded' || reviewedAt) return 'done'
  return 'todo'
}

function notiSuffix(n: NotificationOut): string {
  const s = notiState(n)
  if (n.type !== SUBMISSION_TYPE) return ''
  if (s === 'done') return '（已批改）'
  if (s === 'invalid') return '（已失效）'
  return ''
}

async function refreshNotifications() {
  // parent/student 走客户端布局，管理端铃铛仅教师/教务/管理员需要
  if (!auth.user || auth.user.role === 'parent' || auth.user.role === 'student') return
  try {
    unreadCount.value = await getUnreadCount()
    if (showNotiPop.value || unreadCount.value > 0) {
      const page = await listNotifications({ limit: 12 })
      notis.value = page.items
    }
  } catch {
    // 轮询失败静默，下个周期重试
  }
}

function toggleNotiPop() {
  showNotiPop.value = !showNotiPop.value
  if (showNotiPop.value) {
    void refreshNotifications()
    // 铃铛已并入侧栏底部：浮层改 fixed 定位，按按钮位置展开，避免被侧栏裁剪
    nextTick(() => {
      const el = bellBtn.value
      if (!el) return
      const r = el.getBoundingClientRect()
      popStyle.value = {
        left: `${Math.min(r.right + 10, window.innerWidth - 380)}px`,
        bottom: `${Math.max(12, window.innerHeight - r.top + 10)}px`,
      }
    })
  }
}

/** 通知点击：submission_submitted 精确跳转到该学生的提交并自动打开批改弹窗 */
async function onNotiClick(n: NotificationOut) {
  if (!n.read_at) {
    try {
      await markNotificationRead(n.id)
      unreadCount.value = Math.max(0, unreadCount.value - 1)
      n.read_at = new Date().toISOString()
    } catch {
      // 忽略已读失败
    }
  }
  showNotiPop.value = false
  const data = (n.data ?? {}) as Record<string, unknown>
  if (n.type !== SUBMISSION_TYPE) return
  if (typeof data.assignment_id !== 'string' || !data.assignment_id) return
  const query: Record<string, string> = {}
  // 精确提交（新通知才有；老通知无 submission_id 时退化为只进批改列表）
  if (typeof data.submission_id === 'string' && data.submission_id) {
    query.submission = data.submission_id
  }
  if (typeof data.student_id === 'string' && data.student_id) {
    query.student = data.student_id
  }
  // 已处理/已失效的通知：不再带精确参数，只进批改列表（避免第二次点击报「加载提交失败」）
  if (notiState(n) !== 'todo') {
    router.push({ path: `/assignments/${data.assignment_id}/submissions` })
    return
  }
  router.push({ path: `/assignments/${data.assignment_id}/submissions`, query })
}

/** 通知类型 → 商务风 SVG 图标路径（24x24 线性图标，1.8px 描边） */
const NOTI_ICON_PATHS: Record<string, string> = {
  submission_submitted: 'M22 12h-6l-2 3h-4l-2-3H2M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z',
  submission_graded: 'M22 11.08V12a10 10 0 1 1-5.93-9.14M22 4 12 14.01l-3-3',
  assignment_published: 'M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20',
  feedback_published: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z',
  evaluation_published: 'M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01z',
  schedule_reminder: 'M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0',
  order_confirmed: 'M20 12l-8-5-8 5 8 5 8-5zM4 12v6a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-6',
  default: 'M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0',
}

function notiIcon(n: NotificationOut): string {
  return NOTI_ICON_PATHS[n.type] ?? NOTI_ICON_PATHS.default
}

watch(
  () => route.fullPath,
  () => {
    showNotiPop.value = false
  },
)

const ADMIN_NAV = [
  { to: '/students', label: '学员管理', icon: 'M12 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM4 20c0-4 4-6 8-6s8 2 8 6', navKey: 'nav_students' },
  { to: '/invitations', label: '招生邀约', icon: 'M18 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 21v-2a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v2M19 8v6M22 11h-6', navKey: 'nav_invitations' },
  { to: '/classes', label: '班级管理', icon: 'M3 21h18M5 21V7l7-4 7 4v14M9 9h.01M9 12h.01M9 15h.01M15 9h.01M15 12h.01M15 15h.01', navKey: 'nav_classes' },
  { to: '/teachers', label: '教师管理', icon: 'M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75', navKey: 'nav_teachers' },
  { to: '/permissions', label: '权限管理', icon: 'M12 2l7 4v6c0 5-3.5 8.5-7 10-3.5-1.5-7-5-7-10V6l7-4zM9 12l2 2 4-4', adminOnly: true },
  { to: '/settings', label: '设置', icon: 'M12 21a9 9 0 1 0-9-9M12 21a9 9 0 0 0 9-9M12 3a9 9 0 0 1 9 9M12 3A9 9 0 0 0 3 12', perm: 'settings_manage', navKey: 'nav_settings' },
  { to: '/schedules', label: '排课与考勤', navKey: 'nav_schedules', icon: 'M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z' },
  { to: '/packages', label: '课时包管理', navKey: 'nav_packages', icon: 'M20 12l-8-5-8 5 8 5 8-5zM4 12v6a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-6' },
  { to: '/feedbacks', label: '课后反馈', navKey: 'nav_feedbacks', icon: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2zM8 9h8M8 13h5' },
  { to: '/reports', label: '报告·总结', navKey: 'nav_reports', icon: 'M8 2v4M16 2v4M3 10h18M6 6h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2zM8 14h8M8 18h5' },
  { to: '/evaluations', label: '学员评估', navKey: 'nav_evaluations', icon: 'M7 3h10a2 2 0 0 1 2 2v16H5V5a2 2 0 0 1 2-2zM8 8h8M8 12h8M8 16h5' },
  { to: '/agents', label: 'Agent 工作台', navKey: 'nav_agents', icon: 'M13 2 3 14h7l-1 8 10-12h-7l1-8z' },
  { to: '/assignments', label: 'AI 习题', navKey: 'nav_assignments', icon: 'M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11M15 3h6v6' },
  { to: '/finance', label: '财务管理', icon: 'M3 3v18h18M7 14l4-4 4 4 5-6', perm: 'finance_view', navKey: 'nav_finance' },
]

/** 教师端按权限键显隐：设置(settings_manage)/财务(finance_view)默认不可见；
 * 各模块导航(nav_*) 默认全开，可在权限管理-导航可见分组中按教师关闭；管理员/教务全开 */
const navItems = computed(() =>
  ADMIN_NAV.filter((item) => {
    const perm = (item as { perm?: string }).perm
    const navKey = (item as { navKey?: string }).navKey
    if (auth.user?.role === 'teacher') {
      if (perm && teacherPerms.value[perm] !== true) return false
      if (navKey && teacherPerms.value[navKey] !== true) return false
    }
    if ((item as { adminOnly?: boolean }).adminOnly && auth.user?.role !== 'admin') return false
    return true
  }),
)
</script>

<template>
  <div class="layout" :class="{ collapsed, 'teacher-theme': auth.user?.role === 'teacher' }">
    <aside class="sidebar" :class="{ collapsed }" :data-sidebar-theme="theme.sidebarTheme">
      <div class="brand">
        <div class="brand-mark">
          <BrandLogo :logo="theme.loginLogo" />
        </div>
        <div v-if="!collapsed" class="brand-text">
          <span class="brand-name">{{ theme.loginTitle || '智能编程教务' }}</span>
          <span class="brand-sub">{{ theme.sidebarSub }}</span>
        </div>
        <button class="collapse-btn inline" :title="collapsed ? '展开侧边栏' : '收起侧边栏'" @click="collapsed = !collapsed">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path v-if="!collapsed" d="M15 18l-6-6 6-6" />
            <path v-else d="M9 18l6-6-6-6" />
          </svg>
        </button>
      </div>

      <nav class="nav">
        <RouterLink
        <RouterLink
          v-for="item in navItems"
          :key="item.to"
          :to="item.to"
          class="nav-item"
          :class="{ active: item.to === '/reports' ? route.path.startsWith('/reports') || route.path.startsWith('/summaries') : route.path.startsWith(item.to) }"
          :title="collapsed ? item.label : undefined"
        >
          <svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path :d="item.icon" />
          </svg>
          <span v-if="!collapsed">{{ item.label }}</span>
          <span v-if="item.to === '/assignments' && aiTasks.assignmentRunningCount > 0" class="nav-badge">
            {{ aiTasks.assignmentRunningCount }}
          </span>
          <span v-if="item.to === '/evaluations' && aiTasks.evaluationRunningCount > 0" class="nav-badge">
            {{ aiTasks.evaluationRunningCount }}
          </span>
        </RouterLink>
      </nav>

      <div class="spacer" />
      <Teleport to="body">
        <div v-if="showNotiPop" class="noti-pop side-pop" :style="popStyle" @click.stop>
          <div class="noti-pop-head">
            <span>通知</span>
            <span v-if="unreadCount > 0" class="noti-pop-count">{{ unreadCount }} 条未读</span>
          </div>
          <div v-if="notis.length === 0" class="noti-empty">暂无通知</div>
          <button
            v-for="n in notis"
            :key="n.id"
            class="noti-item"
            :class="{ unread: !n.read_at, highlight: n.type === 'submission_submitted', done: notiState(n) === 'done', invalid: notiState(n) === 'invalid' }"
            @click="onNotiClick(n)"
          >
            <svg class="noti-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path :d="notiIcon(n)" /></svg>
            <span class="noti-body">
              <span class="noti-title">{{ n.title }}{{ notiSuffix(n) }}</span>
              <span class="noti-content">{{ n.content }}</span>
              <span class="noti-time">{{ fmtDateTimeFromIso(n.created_at) }}</span>
            </span>
            <span v-if="!n.read_at" class="noti-unread-dot" />
          </button>
        </div>
      </Teleport>
      <div class="user-box" :class="{ collapsed }" title="点击进入个人信息" @click="goProfile">
        <div class="avatar">{{ (auth.user?.name || '?').slice(0, 1) }}</div>
        <template v-if="!collapsed">
          <div class="user-meta">
            <div class="user-name">{{ auth.user?.name }}</div>
            <div class="user-role">
              {{ auth.user?.role }}<template v-if="isAdmin"> · 管理员</template>
            </div>
          </div>
          <button ref="bellBtn" class="icon-ghost" title="站内通知" @click.stop="toggleNotiPop">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0" />
            </svg>
            <span v-if="unreadCount > 0" class="icon-badge">{{ unreadCount > 99 ? '99+' : unreadCount }}</span>
          </button>
          <button class="logout" title="退出登录" @click.stop="onLogout">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
            </svg>
          </button>
        </template>
        <button v-else ref="bellBtn" class="icon-ghost" title="站内通知" @click.stop="toggleNotiPop">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0" />
          </svg>
          <span v-if="unreadCount > 0" class="icon-badge">{{ unreadCount > 99 ? '99+' : unreadCount }}</span>
        </button>
      </div>
    </aside>

    <main class="main" :style="theme.mainBgStyle">
      <RouterView />
    </main>

    <!-- 全局 AI 任务进行中浮窗（按类型分流：习题 / 评估·班级 PPT） -->
    <div v-if="aiTasks.runningCount > 0" class="ai-float-stack">
      <div v-if="aiTasks.assignmentRunningCount > 0" class="ai-float" @click="goFloatMain">
        <span class="ai-float-dot" />
        <div class="ai-float-text">
          <div class="ai-float-title">AI 出题中…（{{ aiTasks.assignmentRunningCount }} 个任务）</div>
          <div class="ai-float-sub">点击回 AI 习题查看<span v-if="aiTasks.evaluationRunningCount > 0"> · 或点下方评估任务</span></div>
        </div>
        <button class="ai-float-go" type="button" @click.stop="goFloatAssignments">去查看</button>
      </div>
      <div v-if="aiTasks.evaluationRunningCount > 0" class="ai-float eval" @click="goFloatMain">
        <span class="ai-float-dot eval-dot" />
        <div class="ai-float-text">
          <div class="ai-float-title">评估 / 班级 PPT 生成中…（{{ aiTasks.evaluationRunningCount }} 个任务）</div>
          <div class="ai-float-sub">点击回学员评估 · 班级面板查看进度与下载</div>
        </div>
        <button class="ai-float-go" type="button" @click.stop="goFloatEvaluations">去查看</button>
      </div>
    </div>

    <!-- 完成通知 toast（按任务来源分流跳转） -->
    <Transition name="toast">
      <div v-if="aiToastVisible" class="ai-toast" @click="goToastTarget">
        <div class="ai-toast-icon">✓</div>
        <div>
          <div class="ai-toast-title">{{ aiToastTitle }}</div>
          <div class="ai-toast-sub">{{ aiToastSub }}</div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

/* 侧边栏：固定高度自带滚动，不被右侧拉伸 */
.sidebar {
  width: 232px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  padding: 20px 14px 16px;
  height: 100vh;
  overflow-y: auto;
  overflow-x: hidden;
  /* 隐藏滚动条（保留滚动能力） */
  scrollbar-width: none;
  transition: width 0.24s ease;
  background:
    radial-gradient(1200px 600px at -20% -10%, rgba(99, 102, 241, 0.35), transparent 60%),
    radial-gradient(800px 400px at 110% 110%, rgba(6, 182, 212, 0.22), transparent 55%),
    #0f172a;
  color: #cbd5e1;
}

.sidebar::-webkit-scrollbar {
  width: 0;
}

.sidebar.collapsed {
  width: 72px;
  padding: 20px 8px 16px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 6px 20px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.15);
  margin-bottom: 14px;
  white-space: nowrap;
}

.brand-mark {
  width: 38px;
  height: 38px;
  flex-shrink: 0;
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 4px 14px rgba(3, 8, 20, 0.45);
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
  overflow: hidden;
  flex: 1;
  min-width: 0;
}

.brand-name {
  font-weight: 700;
  font-size: 15px;
  color: #fff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 150px;
}

.brand-sub {
  font-size: 11px;
  color: #64748b;
  letter-spacing: 0.04em;
}

/* 收起/展开：品牌行内右侧，与 Logo/标题同一水平 */
.collapse-btn.inline {
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  border: 1px solid transparent;
  background: rgba(148, 163, 184, 0.12);
  color: #94a3b8;
  cursor: pointer;
  transition: all 0.15s;
  margin: 0 0 0 auto;
  padding: 0;
}

.collapse-btn.inline:hover {
  color: #fff;
  border-color: rgba(148, 163, 184, 0.35);
  background: rgba(148, 163, 184, 0.22);
}

.collapse-btn.inline svg {
  width: 14px;
  height: 14px;
}

/* 收起态：品牌区上下排列，按钮居中位于 Logo 下方 */
.sidebar.collapsed .brand {
  flex-direction: column;
  gap: 10px;
  padding-bottom: 14px;
}
.sidebar.collapsed .collapse-btn.inline {
  margin: 0;
}
.sidebar[data-sidebar-theme='light'].collapsed .brand {
  border-bottom-color: var(--line);
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 500;
  color: #94a3b8;
  transition: all 0.18s ease;
  white-space: nowrap;
}

.sidebar.collapsed .nav-item {
  justify-content: center;
  padding: 10px 0;
  gap: 0;
}

.nav-item:hover {
  color: #e2e8f0;
  background: rgba(148, 163, 184, 0.1);
}

.nav-item.active {
  color: #fff;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.9), rgba(6, 182, 212, 0.75));
  box-shadow: 0 4px 16px rgba(99, 102, 241, 0.35);
}

.nav-icon {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

.spacer {
  flex: 1;
}

.user-box {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 8px 0;
  border-top: 1px solid rgba(148, 163, 184, 0.15);
  margin-top: 14px;
  cursor: pointer;
  transition: background 0.15s;
}

.user-box:hover {
  background: rgba(255, 255, 255, 0.06);
}

.user-box.collapsed {
  justify-content: center;
  padding: 14px 0 0;
}

.avatar {
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #f59e0b, #ef4444);
}

.user-meta {
  flex: 1;
  min-width: 0;
  line-height: 1.35;
}

.user-name {
  color: #f1f5f9;
  font-weight: 600;
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.user-role {
  color: #64748b;
  font-size: 11px;
}

.logout {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: #64748b;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
}

.logout:hover {
  color: #fca5a5;
  background: rgba(239, 68, 68, 0.15);
}

.logout svg {
  width: 16px;
  height: 16px;
}

/* AI 任务导航徽标 */
.nav-item {
  position: relative;
}
.nav-badge {
  position: absolute;
  top: 6px;
  right: 10px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 999px;
  background: linear-gradient(135deg, #f59e0b, #ef4444);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
}
.sidebar.collapsed .nav-badge {
  top: 4px;
  right: 4px;
}

/* 全局 AI 任务进行中浮窗（按类型分流堆叠） */
.ai-float-stack {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 60;
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-width: min(380px, calc(100vw - 40px));
}
.ai-float {
  position: relative;
  right: auto;
  bottom: auto;
  z-index: auto;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-radius: 12px;
  background: rgba(15, 23, 42, 0.92);
  color: #f1f5f9;
  box-shadow: 0 8px 28px rgba(15, 23, 42, 0.35);
  cursor: pointer;
  backdrop-filter: blur(6px);
  border: 1px solid rgba(148, 163, 184, 0.25);
  transition: all 0.2s;
}
.ai-float:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 32px rgba(99, 102, 241, 0.35);
}
.ai-float-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  animation: ai-pulse 1.2s infinite;
  flex-shrink: 0;
}
@keyframes ai-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
.ai-float-text {
  flex: 1;
  min-width: 0;
}
.ai-float-go {
  flex-shrink: 0;
  border: 1px solid rgba(148, 163, 184, 0.4);
  background: rgba(99, 102, 241, 0.25);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  padding: 6px 12px;
  border-radius: 999px;
  cursor: pointer;
  white-space: nowrap;
}
.ai-float-go:hover {
  background: rgba(99, 102, 241, 0.45);
}
.ai-float.eval .ai-float-go {
  background: rgba(6, 182, 212, 0.25);
}
.ai-float.eval .ai-float-go:hover {
  background: rgba(6, 182, 212, 0.45);
}
.eval-dot {
  background: linear-gradient(135deg, #06b6d4, #10b981);
}
.ai-float-title {
  font-size: 13px;
  font-weight: 600;
}
.ai-float-sub {
  font-size: 11.5px;
  color: #94a3b8;
  margin-top: 2px;
}

/* 完成通知 toast */
.ai-toast {
  position: fixed;
  right: 20px;
  top: 20px;
  z-index: 70;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-radius: 12px;
  background: var(--surface);
  color: var(--ink);
  box-shadow: var(--shadow-lg);
  border: 1px solid var(--line);
  cursor: pointer;
  max-width: 360px;
}
.ai-toast-icon {
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--success-soft);
  color: #047857;
  font-weight: 700;
  font-size: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.ai-toast-title {
  font-size: 13.5px;
  font-weight: 700;
}
.ai-toast-sub {
  font-size: 12px;
  color: var(--ink-3);
  margin-top: 2px;
}
.toast-enter-active, .toast-leave-active {
  transition: all 0.25s ease;
}
.toast-enter-from, .toast-leave-to {
  opacity: 0;
  transform: translateX(24px);
}

/* 右侧主窗口：独立滚动，不拉伸侧边栏 */
.main {
  flex: 1;
  min-width: 0;
  height: 100vh;
  overflow-y: auto;
  overflow-x: auto;
  padding: 28px 32px;
  position: relative;
}

/* —— 教师端主题：沉稳现代（纯色、无渐变） —— */
.teacher-theme .sidebar {
  background: #101d33;
  color: #c3cfe3;
}
.teacher-theme .brand {
  border-bottom-color: rgba(255, 255, 255, 0.12);
}
.teacher-theme .brand-mark {
  background: #ffffff;
  color: #101d33;
  box-shadow: none;
}
.teacher-theme .brand-name {
  color: #ffffff;
}
.teacher-theme .nav-item {
  border-radius: 10px;
  font-weight: 500;
}
.teacher-theme .nav-item:hover {
  background: rgba(255, 255, 255, 0.08);
}
.teacher-theme .nav-item.active {
  background: #ffffff;
  color: #101d33;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.25);
}
.teacher-theme .avatar {
  background: #2f6fed;
}
.teacher-theme .main {
  background: var(--bg);
}

/* —— 侧边栏风格（个性化设置，全端生效；写在教师主题之后以取得优先） —— */
/* 浅色：云白底 + 深字 */
.sidebar[data-sidebar-theme='light'] {
  background: #eef1f6;
  color: var(--ink-2);
}
.sidebar[data-sidebar-theme='light'] .brand {
  border-bottom-color: var(--line);
}
.sidebar[data-sidebar-theme='light'] .brand-name {
  color: var(--ink);
}
.sidebar[data-sidebar-theme='light'] .brand-sub {
  color: var(--ink-3);
}
.sidebar[data-sidebar-theme='light'] .nav-item {
  color: #5b6b82;
}
.sidebar[data-sidebar-theme='light'] .nav-item:hover {
  color: var(--ink);
  background: rgba(15, 23, 42, 0.06);
}
.sidebar[data-sidebar-theme='light'] .nav-item.active {
  background: #ffffff;
  color: var(--brand-strong);
  box-shadow: var(--shadow-sm);
}
.sidebar[data-sidebar-theme='light'] .user-box {
  border-top-color: var(--line);
}
.sidebar[data-sidebar-theme='light'] .user-box:hover {
  background: rgba(15, 23, 42, 0.04);
}
.sidebar[data-sidebar-theme='light'] .user-name {
  color: var(--ink);
}
.sidebar[data-sidebar-theme='light'] .user-role {
  color: var(--ink-3);
}
.sidebar[data-sidebar-theme='light'] .logout {
  color: var(--ink-3);
}
.sidebar[data-sidebar-theme='light'] .icon-ghost {
  color: var(--ink-3);
}
.sidebar[data-sidebar-theme='light'] .icon-ghost:hover {
  color: var(--brand-strong);
  background: rgba(15, 23, 42, 0.06);
}
/* 品牌色：跟随系统主题主色 */
.sidebar[data-sidebar-theme='brand'] {
  background: var(--brand);
  color: rgba(255, 255, 255, 0.75);
}
.sidebar[data-sidebar-theme='brand'] .brand {
  border-bottom-color: rgba(255, 255, 255, 0.22);
}
.sidebar[data-sidebar-theme='brand'] .brand-mark {
  background: #ffffff;
  color: var(--brand-strong);
  box-shadow: none;
}
.sidebar[data-sidebar-theme='brand'] .brand-name {
  color: #ffffff;
}
.sidebar[data-sidebar-theme='brand'] .brand-sub {
  color: rgba(255, 255, 255, 0.72);
}
.sidebar[data-sidebar-theme='brand'] .nav-item {
  color: rgba(255, 255, 255, 0.78);
}
.sidebar[data-sidebar-theme='brand'] .nav-item:hover {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.14);
}
.sidebar[data-sidebar-theme='brand'] .nav-item.active {
  background: #ffffff;
  color: var(--brand-strong);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.22);
}
.sidebar[data-sidebar-theme='brand'] .user-box {
  border-top-color: rgba(255, 255, 255, 0.22);
}
.sidebar[data-sidebar-theme='brand'] .user-box:hover {
  background: rgba(255, 255, 255, 0.1);
}
.sidebar[data-sidebar-theme='brand'] .user-name {
  color: #ffffff;
}
.sidebar[data-sidebar-theme='brand'] .user-role {
  color: rgba(255, 255, 255, 0.72);
}
.sidebar[data-sidebar-theme='brand'] .logout,
.sidebar[data-sidebar-theme='brand'] .icon-ghost {
  color: rgba(255, 255, 255, 0.78);
}
.sidebar[data-sidebar-theme='brand'] .logout:hover,
.sidebar[data-sidebar-theme='brand'] .icon-ghost:hover {
  color: #ffffff;
  background: rgba(255, 255, 255, 0.14);
}

/* ===== 用户行内的通知铃（替代独占一行/单独区块） ===== */
.icon-ghost {
  position: relative; width: 32px; height: 32px; flex-shrink: 0;
  display: inline-flex; align-items: center; justify-content: center;
  border: none; background: transparent; color: #94a3b8; border-radius: 8px; cursor: pointer; transition: all .15s;
}
.icon-ghost:hover { color: #e2e8f0; background: rgba(255, 255, 255, 0.08); }
.icon-ghost svg { width: 17px; height: 17px; }
.icon-badge {
  position: absolute; top: 2px; right: 0; min-width: 15px; height: 15px; padding: 0 3px;
  background: #ef4444; color: #fff; font-size: 9.5px; font-weight: 700; line-height: 15px; text-align: center;
  border-radius: 999px;
}
.user-box.collapsed { flex-direction: column; gap: 10px; }
.side-pop { position: fixed; z-index: 200; }
.topbar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 8px;
  min-height: 36px;
}
.noti-wrap {
  position: relative;
}
.noti-bell {
  position: relative;
  width: 38px;
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--line);
  background: var(--surface);
  border-radius: 10px;
  color: var(--ink-2);
  cursor: pointer;
  transition: all 0.15s;
}
.noti-bell:hover {
  border-color: var(--brand);
  color: var(--brand-strong);
}
.noti-bell svg {
  width: 18px;
  height: 18px;
}
.noti-dot {
  position: absolute;
  top: -6px;
  right: -6px;
  min-width: 17px;
  height: 17px;
  padding: 0 4px;
  border-radius: 999px;
  background: linear-gradient(135deg, #f59e0b, #ef4444);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  animation: noti-pulse 1.6s infinite;
}
@keyframes noti-pulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.12); }
}
.noti-pop {
  position: absolute;
  right: 0;
  top: 46px;
  width: 360px;
  max-height: 420px;
  overflow: auto;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  box-shadow: var(--shadow-lg);
  z-index: 80;
  padding: 6px;
}
.noti-pop-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px 6px;
  font-size: 13.5px;
  font-weight: 700;
  color: var(--ink);
  border-bottom: 1px solid var(--line);
  position: sticky;
  top: 0;
  background: var(--surface);
}
.noti-pop-count {
  font-size: 11.5px;
  font-weight: 600;
  color: #b45309;
}
.noti-empty {
  text-align: center;
  color: var(--ink-3);
  font-size: 13px;
  padding: 26px 0;
}
.noti-item {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  width: 100%;
  text-align: left;
  border: none;
  background: none;
  padding: 10px;
  border-radius: 10px;
  cursor: pointer;
  font-family: inherit;
}
.noti-item:hover {
  background: var(--brand-soft);
}
.noti-item.highlight {
  background: #fffbeb;
}
.noti-item.highlight:hover {
  background: var(--brand-soft);
}
.noti-item.done {
  opacity: 0.72;
}
.noti-item.done .noti-title {
  color: var(--ink-3);
}
.noti-item.invalid {
  opacity: 0.55;
}
.noti-icon {
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  margin-top: 1px;
  color: #6366f1;
}
.noti-item.done .noti-icon,
.noti-item.invalid .noti-icon {
  color: var(--ink-3);
}
.noti-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.noti-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--ink);
}
.noti-content {
  font-size: 12.5px;
  color: var(--ink-2);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.noti-time {
  font-size: 11px;
  color: var(--ink-3);
}
.noti-unread-dot {
  flex-shrink: 0;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ef4444;
  margin-top: 6px;
}
</style>
