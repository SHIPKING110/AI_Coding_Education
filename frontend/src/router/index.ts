import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { tokenClient } from '@/api/http'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/auth/LoginView.vue'),
    },
    {
      path: '/share/:token',
      name: 'share',
      component: () => import('@/views/agents/SharedConversationView.vue'),
    },
    {
      path: '/',
      component: () => import('@/layouts/AdminLayout.vue'),
      meta: { requiresAuth: true },
      redirect: '/students',
      children: [
        {
          path: 'students',
          name: 'students',
          component: () => import('@/views/students/StudentsView.vue'),
        },
        {
          path: 'collection',
          name: 'collection',
          component: () => import('@/views/collection/CollectionView.vue'),
        },
        {
          path: 'classes',
          name: 'classes',
          component: () => import('@/views/classes/ClassesView.vue'),
        },
        {
          path: 'teachers',
          name: 'teachers',
          component: () => import('@/views/teachers/TeachersView.vue'),
        },
        {
          path: 'permissions',
          name: 'permissions',
          component: () => import('@/views/permissions/PermissionsView.vue'),
          meta: { adminOnly: true },
        },
        {
          path: 'settings',
          name: 'settings',
          component: () => import('@/views/settings/SettingsView.vue'),
          meta: { perm: 'settings_manage' },
        },
        {
          path: 'personalize',
          name: 'personalize',
          component: () => import('@/views/settings/PersonalizeView.vue'),
          meta: { adminOnly: true },
        },
        {
          path: 'schedules',
          name: 'schedules',
          component: () => import('@/views/schedules/SchedulesView.vue'),
        },
        {
          path: 'schedules/:id',
          name: 'schedule-detail',
          component: () => import('@/views/schedules/ScheduleDetailView.vue'),
        },
        {
          path: 'packages',
          name: 'packages',
          component: () => import('@/views/packages/PackagesView.vue'),
        },
        {
          path: 'feedbacks',
          name: 'feedbacks',
          component: () => import('@/views/feedbacks/FeedbackView.vue'),
        },
        {
          path: 'reports',
          name: 'reports',
          component: () => import('@/views/reports/ReportsView.vue'),
        },
        {
          path: 'summaries',
          name: 'summaries',
          component: () => import('@/views/reports/SummaryView.vue'),
        },
        {
          path: 'assignments',
          name: 'assignments',
          component: () => import('@/views/assignments/AssignmentsView.vue'),
        },
        {
          path: 'grading',
          name: 'grading-center',
          component: () => import('@/views/assignments/GradingCenterView.vue'),
        },
        {
          path: 'assignments/:id/submissions',
          name: 'submission-grading',
          component: () => import('@/views/assignments/SubmissionGradingView.vue'),
        },
        {
          path: 'evaluations',
          name: 'evaluations',
          component: () => import('@/views/evaluations/EvaluationsView.vue'),
        },
        {
          path: 'agents',
          name: 'agents',
          component: () => import('@/views/agents/AgentsView.vue'),
        },
        {
          path: 'students/:id/evaluations',
          name: 'student-evaluations',
          component: () => import('@/views/evaluations/EvaluationsView.vue'),
        },
        {
          path: 'orders',
          redirect: '/finance',
        },
        {
          path: 'finance',
          name: 'finance',
          component: () => import('@/views/finance/FinanceView.vue'),
          meta: { perm: 'finance_view' },
        },
        {
          path: 'invitations',
          name: 'invitations',
          component: () => import('@/views/invitations/InvitationsView.vue'),
        },
        {
          path: 'workbench',
          redirect: '/finance',
        },
        {
          path: 'profile',
          name: 'profile',
          component: () => import('@/views/profile/ProfileView.vue'),
        },
      ],
    },
    {
      path: '/client',
      component: () => import('@/layouts/ClientLayout.vue'),
      meta: { requiresAuth: true, clientRole: true },
      redirect: '/client/home',
      children: [
        {
          path: 'profile',
          name: 'client-profile',
          component: () => import('@/views/profile/ProfileView.vue'),
        },
        {
          path: 'home',
          name: 'client-home',
          component: () => import('@/views/client/ClientHomeView.vue'),
        },
        {
          path: 'feedbacks',
          name: 'client-feedbacks',
          component: () => import('@/views/client/ClientFeedbackView.vue'),
        },
        {
          path: 'evaluations',
          name: 'client-evaluations',
          component: () => import('@/views/client/ClientEvaluationsView.vue'),
        },
        {
          path: 'assignments',
          name: 'client-assignments',
          component: () => import('@/views/client/ClientAssignmentsView.vue'),
        },
        {
          path: 'assignments/:id',
          name: 'client-assignment-detail',
          component: () => import('@/views/client/ClientAssignmentDetailView.vue'),
        },
        {
          path: 'packages',
          name: 'client-packages',
          component: () => import('@/views/client/ClientPackagesView.vue'),
        },
        {
          path: 'orders',
          name: 'client-orders',
          component: () => import('@/views/client/ClientOrdersView.vue'),
        },
        {
          path: 'notifications',
          name: 'client-notifications',
          component: () => import('@/views/client/ClientNotificationsView.vue'),
        },
      ],
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/',
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!to.meta.requiresAuth) {
    if (to.name === 'login' && tokenClient.getAccess() && auth.user) {
      // 已登录用户去对应首页
      if (auth.user.role === 'parent' || auth.user.role === 'student') {
        return { name: 'client-home' }
      }
      return { name: 'students' }
    }
    return true
  }
  if (!tokenClient.getAccess()) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (!auth.user) {
    try {
      await auth.fetchMe()
    } catch {
      tokenClient.clear()
      return { name: 'login' }
    }
  }
  const user = auth.user
  if (!user) {
    tokenClient.clear()
    return { name: 'login' }
  }
  // 客户端路由限制：仅 parent/student 可访问；课时包与订单仅家长可见
  if (to.meta.clientRole && !['parent', 'student'].includes(user.role)) {
    return { name: 'students' }
  }
  if (
    user.role === 'student' &&
    (to.name === 'client-packages' || to.name === 'client-orders')
  ) {
    return { name: 'client-home' }
  }
  // 管理端路由限制：parent/student 不可访问
  if (!to.meta.clientRole && to.name !== 'login' && ['parent', 'student'].includes(user.role)) {
    return { name: 'client-home' }
  }
  // 权限管理仅管理员可访问
  if (to.meta.adminOnly && user.role !== 'admin') {
    return { name: 'students' }
  }
  // 权限键路由：教师需对应权限（管理员/教务默认放行，后端同样兜底）
  if (typeof to.meta.perm === 'string' && user.role === 'teacher') {
    const perms = await auth.fetchPerms()
    if (perms[to.meta.perm] !== true) {
      return { name: 'students' }
    }
  }
  return true
})

export default router