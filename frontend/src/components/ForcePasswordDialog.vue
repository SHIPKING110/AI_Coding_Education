<script setup lang="ts">
import { computed, ref } from 'vue'

import { changeMyPasswordApi } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'

const auth = useAuthStore()
const toast = useToastStore()

const visible = computed(() => !!auth.user?.must_change_password)

const oldPw = ref('')
const newPw = ref('')
const confirmPw = ref('')
const saving = ref(false)
const error = ref('')

async function submit() {
  error.value = ''
  if (!oldPw.value) {
    error.value = '请输入当前密码（管理员告知的临时密码）'
    return
  }
  if (newPw.value.length < 8) {
    error.value = '新密码至少 8 位，且需同时包含字母和数字'
    return
  }
  if (newPw.value !== confirmPw.value) {
    error.value = '两次输入的新密码不一致'
    return
  }
  if (newPw.value === oldPw.value) {
    error.value = '新密码不能与临时密码相同'
    return
  }
  saving.value = true
  try {
    await changeMyPasswordApi(oldPw.value, newPw.value)
    await auth.fetchMe()
    toast.success('密码已更新，请牢记新密码')
  } catch (e) {
    error.value =
      (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
      (e instanceof Error ? e.message : '') ||
      '修改失败，请稍后重试'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="fp-mask">
      <div class="fp-card" role="dialog" aria-modal="true" aria-label="强制修改密码">
        <div class="fp-head">
          <h2>首次登录需修改密码</h2>
          <p>当前账号使用的是管理员创建的临时密码，为保障账号安全，请先设置新密码。</p>
        </div>
        <form class="fp-body" @submit.prevent="submit">
          <label>
            <span>当前密码（临时密码）</span>
            <input v-model="oldPw" type="password" autocomplete="current-password" />
          </label>
          <label>
            <span>新密码（至少 8 位，字母+数字）</span>
            <input v-model="newPw" type="password" autocomplete="new-password" />
          </label>
          <label>
            <span>确认新密码</span>
            <input v-model="confirmPw" type="password" autocomplete="new-password" />
          </label>
          <p v-if="error" class="fp-error">{{ error }}</p>
          <button class="btn primary fp-submit" type="submit" :disabled="saving">
            {{ saving ? '保存中…' : '设置新密码并继续' }}
          </button>
        </form>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.fp-mask {
  position: fixed;
  inset: 0;
  z-index: 10000;
  background: rgba(15, 23, 42, 0.55);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.fp-card {
  width: min(420px, 100%);
  background: var(--surface);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
}
.fp-head {
  padding: 22px 24px 8px;
}
.fp-head h2 {
  font-size: 18px;
  color: var(--ink);
}
.fp-head p {
  margin-top: 8px;
  font-size: 13px;
  color: var(--ink-3);
  line-height: 1.6;
}
.fp-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px 24px 24px;
}
.fp-body label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  color: var(--ink-2);
}
.fp-body input {
  padding: 9px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  font-size: 14px;
  outline: none;
}
.fp-body input:focus {
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-glow);
}
.fp-error {
  margin: 0;
  font-size: 12.5px;
  color: var(--danger);
}
.fp-submit {
  width: 100%;
  margin-top: 4px;
}
</style>
