<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { RouterLink, RouterView, useRouter } from 'vue-router'

import BrandLogo from '@/components/BrandLogo.vue'
import { useAuthStore } from '@/stores/auth'
import { useClientStore } from '@/stores/client'
import { useThemeStore } from '@/stores/theme'

const auth = useAuthStore()
const router = useRouter()
const store = useClientStore()
const theme = useThemeStore()

const meName = computed(() => auth.user?.name ?? '')
const meRole = computed(() => auth.user?.role ?? '')
const isStudent = computed(() => meRole.value === 'student')

const students = computed(() => store.students)
const activeStudentId = computed(() => store.activeStudentId)
const unreadCount = computed(() => store.unread)

const clientNavItems = computed(() => {
  const all = [
    { to: '/client/home', label: '首页', icon: 'M3 10.5 12 3l9 7.5M5 9.5V21h14V9.5', roles: ['parent', 'student'] },
    { to: '/client/assignments', label: '作业', icon: 'M9 11h6M9 15h4M7 3h10a2 2 0 0 1 2 2v16H5V5a2 2 0 0 1 2-2z', roles: ['parent', 'student'] },
    { to: '/client/feedbacks', label: '反馈', icon: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2zM8 9h8M8 12h5', roles: ['parent', 'student'] },
    { to: '/client/evaluations', label: '成长', icon: 'M12 2 15 8.6 22 9.3 17 14 18.2 21 12 17.6 5.8 21 7 14 2 9.3 9 8.6z', roles: ['parent', 'student'] },
    { to: '/client/packages', label: '续费', icon: 'M20 12l-8-5-8 5 8 5 8-5zM4 12v6a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-6', roles: ['parent'] },
    { to: '/client/orders', label: '订单', icon: 'M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2M9 5a2 2 0 0 0 2 2h2a2 2 0 0 0 2-2M9 5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2m-6 9 2 2 4-4', roles: ['parent'] },
  ]
  return all.filter((i) => i.roles.includes(meRole.value))
})

async function loadMe() {
  await store.loadMe(true)
}

function switchStudent(id: string) {
  store.setActiveStudent(id)
}

async function onLogout() {
  await auth.logout()
  store.clear()
  router.push({ name: 'login' })
}

function goProfile() {
  router.push({ name: 'client-profile' })
}

onMounted(loadMe)
</script>

<template>
  <div class="client-shell">
    <header class="client-header" :style="theme.clientHeaderStyle">
      <div class="header-inner">
        <div class="brand">
          <div class="brand-mark">
            <BrandLogo :logo="theme.loginLogo" />
          </div>
          <div class="brand-text">
            <strong>{{ theme.loginTitle || '少儿编程学习中心' }}</strong>
            <span>{{ meRole === 'student' ? '学员端' : '家长端' }}</span>
          </div>
        </div>

        <div class="header-actions">
          <RouterLink to="/client/notifications" class="notif-link">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0" />
            </svg>
            <span v-if="unreadCount > 0" class="badge">{{ unreadCount > 99 ? '99+' : unreadCount }}</span>
          </RouterLink>
          <button class="user-chip" :title="`${auth.user?.name}（${auth.user?.username}）· 点击进入个人信息`" @click="goProfile">
            {{ meName }}
          </button>
          <button class="logout-btn" @click="onLogout">退出</button>
        </div>
      </div>

      <!-- 学员切换（家长多孩 / 学员本人） -->
      <div v-if="students.length > 1" class="student-switch">
        <button
          v-for="s in students"
          :key="s.id"
          class="student-tab"
          :class="{ active: s.id === activeStudentId }"
          @click="switchStudent(s.id)"
        >
          {{ s.name }}
        </button>
      </div>
    </header>

    <div class="client-body">
      <RouterView />
    </div>

    <nav class="client-nav">
      <RouterLink v-for="item in clientNavItems" :key="item.to" :to="item.to" class="nav-item">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path :d="item.icon" />
        </svg>
        <span>{{ item.label }}</span>
      </RouterLink>
    </nav>
  </div>
</template>

<style scoped>
.client-shell {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg);
}

.client-header {
  position: sticky;
  top: 0;
  z-index: 30;
  background: linear-gradient(135deg, #1e1b4b, #0e7490);
  color: #f1f5f9;
  box-shadow: 0 4px 20px rgba(15, 23, 42, 0.18);
}

.header-inner {
  max-width: 1080px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  gap: 12px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-mark {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  display: flex;
  align-items: center;
  justify-content: center;
}

.brand-mark svg {
  width: 20px;
  height: 20px;
}

.brand-text {
  display: flex;
  flex-direction: column;
  line-height: 1.25;
}

.brand-text strong {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.brand-text span {
  font-size: 11px;
  color: rgba(241, 245, 249, 0.7);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.notif-link {
  position: relative;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.12);
  transition: background 0.2s;
}

.notif-link:hover {
  background: rgba(255, 255, 255, 0.22);
}

.notif-link svg {
  width: 18px;
  height: 18px;
}

.badge {
  position: absolute;
  top: -4px;
  right: -4px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 8px;
  background: #ef4444;
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

.user-chip {
  padding: 5px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.14);
  font-size: 12.5px;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.2s;
}

.user-chip:hover {
  background: rgba(255, 255, 255, 0.26);
  border-color: rgba(255, 255, 255, 0.4);
}

.logout-btn {
  padding: 5px 12px;
  border: 1px solid rgba(255, 255, 255, 0.35);
  border-radius: 999px;
  background: transparent;
  color: #f1f5f9;
  font-size: 12.5px;
  cursor: pointer;
  transition: all 0.2s;
}

.logout-btn:hover {
  background: rgba(255, 255, 255, 0.16);
}

.student-switch {
  max-width: 1080px;
  margin: 0 auto;
  padding: 0 20px 10px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.student-tab {
  padding: 6px 16px;
  border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.3);
  background: transparent;
  color: rgba(241, 245, 249, 0.85);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.student-tab.active {
  background: #fff;
  color: #0e7490;
  font-weight: 600;
  border-color: #fff;
}

.client-body {
  flex: 1;
  max-width: 1080px;
  width: 100%;
  margin: 0 auto;
  padding: 20px 20px 84px;
}

/* 底部导航 */
.client-nav {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 30;
  display: flex;
  background: rgba(255, 255, 255, 0.96);
  backdrop-filter: blur(8px);
  border-top: 1px solid var(--line);
  box-shadow: 0 -4px 16px rgba(15, 23, 42, 0.06);
}

.nav-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  padding: 8px 0 9px;
  color: var(--ink-3);
  font-size: 11px;
  transition: color 0.2s;
}

.nav-item svg {
  width: 20px;
  height: 20px;
}

.nav-item.router-link-active {
  color: var(--brand-strong);
  font-weight: 600;
}
</style>
