<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import BrandLogo from '@/components/BrandLogo.vue'

const auth = useAuthStore()
const theme = useThemeStore()
const router = useRouter()
const route = useRoute()

const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

/** 登录页强调色：自定义优先，否则跟随主题默认 */
const accent = computed(() => theme.loginAccent || 'var(--login-accent)')

async function onSubmit() {
  error.value = ''
  if (!username.value || !password.value) {
    error.value = '请输入用户名和密码'
    return
  }
  loading.value = true
  try {
    await auth.login({ username: username.value, password: password.value })
    const redirect = (route.query.redirect as string) || '/'
    router.push(redirect)
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '登录失败，请检查用户名和密码'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="page" :class="`login-${theme.loginTheme}`">
    <div class="bg-pattern" aria-hidden="true" />
    <div v-if="theme.loginTheme === 'poster'" class="poster-side">
      <div class="poster-kicker">{{ theme.loginSubtitle }}</div>
      <div class="poster-title">{{ theme.loginTitle }}</div>
      <div class="poster-sub">{{ theme.loginHero }}</div>
    </div>

    <section class="card">
      <div class="logo">
        <div class="logo-mark">
          <BrandLogo :logo="theme.loginLogo" :accent="accent" />
        </div>
      </div>
      <h1>{{ theme.loginTitle }}</h1>
      <p class="sub">{{ theme.loginSubtitle }}</p>

      <form @submit.prevent="onSubmit">
        <label>
          <span>用户名</span>
          <input v-model="username" type="text" autocomplete="username" placeholder="请输入用户名" :style="{ '--field-accent': accent }" />
        </label>
        <label>
          <span>密码</span>
          <input v-model="password" type="password" autocomplete="current-password" placeholder="请输入密码" :style="{ '--field-accent': accent }" />
        </label>
        <p v-if="error" class="error">{{ error }}</p>
        <button type="submit" :disabled="loading" :style="{ background: accent }">
          <span v-if="loading" class="spinner" />{{ loading ? '登录中…' : '登录' }}
        </button>
      </form>
    </section>
  </main>
</template>

<style scoped>
.page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: auto;
  gap: 64px;
  padding: 24px 48px;
  /* 主题变量：背景 / 卡片 / 文字 / 强调（成套切换，保证协调） */
  --login-bg: #101d33;
  --login-pattern: rgba(255, 255, 255, 0.05);
  --login-card: #ffffff;
  --login-ink: #0f172a;
  --login-sub: #62748e;
  --login-accent: #2f6fed;
  --login-accent-ink: #ffffff;
  --login-field-bg: #f4f6fa;
  --login-field-border: #e2e8f0;
  --login-card-shadow: 0 24px 64px rgba(3, 8, 20, 0.45);
  background: var(--login-bg);
  transition: background 0.25s;
}
.page.login-light {
  --login-bg: #e9edf3;
  --login-pattern: rgba(15, 23, 42, 0.05);
  --login-card: #ffffff;
  --login-ink: #0f172a;
  --login-sub: #62748e;
  --login-accent: #2f6fed;
  --login-field-bg: #f4f6fa;
  --login-field-border: #e2e8f0;
  --login-card-shadow: 0 16px 44px rgba(15, 23, 42, 0.12);
}
.page.login-dark {
  --login-bg: #070d1d;
  --login-pattern: rgba(255, 255, 255, 0.04);
  --login-card: #101a30;
  --login-ink: #e8eef7;
  --login-sub: #8ea0bb;
  --login-accent: #5b8cff;
  --login-field-bg: #0b1428;
  --login-field-border: #22314f;
  --login-card-shadow: 0 24px 64px rgba(0, 0, 0, 0.6);
}
.page.login-poster {
  --login-bg: #123524;
  --login-pattern: rgba(255, 255, 255, 0.06);
  --login-card: #ffffff;
  --login-ink: #0f172a;
  --login-sub: #62748e;
  --login-accent: #0e9f6e;
  --login-field-bg: #f2f7f4;
  --login-field-border: #dcebe3;
  --login-card-shadow: 0 24px 64px rgba(3, 20, 12, 0.5);
}

/* 背景细纹（纯色 + 纹理，不用大面积渐变） */
.bg-pattern {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background-image: radial-gradient(var(--login-pattern) 1px, transparent 1px);
  background-size: 22px 22px;
}

.poster-side {
  display: none;
}
.page.login-poster .poster-side {
  display: block;
  max-width: 420px;
  color: #f2fbf6;
  z-index: 1;
}
.poster-kicker {
  font-size: 13px;
  letter-spacing: 0.2em;
  color: #8fd4ae;
  margin-bottom: 16px;
  font-weight: 600;
}
.poster-title {
  font-size: 42px;
  font-weight: 800;
  line-height: 1.3;
  letter-spacing: 0.02em;
}
.poster-sub {
  margin-top: 16px;
  font-size: 14px;
  color: #bfe3cf;
}

.card {
  position: relative;
  z-index: 1;
  width: 400px;
  max-width: calc(100vw - 48px);
  background: var(--login-card);
  border-radius: 20px;
  padding: 36px 34px 30px;
  box-shadow: var(--login-card-shadow);
}
.logo {
  display: flex;
  justify-content: center;
  margin-bottom: 18px;
}
.logo-mark {
  width: 56px;
  height: 56px;
  border-radius: 17px;
  overflow: hidden;
  box-shadow: 0 10px 24px rgba(3, 8, 20, 0.28);
}
h1 {
  font-size: 21px;
  text-align: center;
  color: var(--login-ink);
}
.sub {
  text-align: center;
  color: var(--login-sub);
  font-size: 12.5px;
  margin: 8px 0 22px;
}
label {
  display: block;
  margin-bottom: 14px;
  font-size: 13px;
  color: var(--login-sub);
  font-weight: 600;
}
label span {
  display: block;
  margin-bottom: 6px;
}
input {
  display: block;
  width: 100%;
  padding: 11px 13px;
  border: 1px solid var(--login-field-border);
  background: var(--login-field-bg);
  color: var(--login-ink);
  border-radius: 10px;
  font-size: 14px;
  transition: all 0.15s;
  box-sizing: border-box;
}
input:focus {
  outline: none;
  border-color: var(--field-accent, var(--login-accent));
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--field-accent, var(--login-accent)) 18%, transparent);
  background: var(--login-card);
}
.error {
  color: var(--danger);
  font-size: 13px;
  margin: 0 0 10px;
}
button {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 12px;
  border: none;
  border-radius: 10px;
  color: var(--login-accent-ink);
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 0.3em;
  text-indent: 0.3em;
  cursor: pointer;
  transition: all 0.15s;
}
button:hover:not(:disabled) {
  transform: translateY(-1px);
  filter: brightness(1.06);
}
button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.spinner {
  width: 15px;
  height: 15px;
  border: 2px solid rgba(255, 255, 255, 0.4);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@media (max-width: 1100px) {
  .page {
    gap: 28px;
    padding: 24px;
  }
  .page.login-poster {
    flex-wrap: wrap;
  }
  .page.login-poster .poster-side {
    max-width: 400px;
  }
}
@media (max-width: 900px) {
  .page.login-poster .poster-side {
    display: none;
  }
}
</style>
