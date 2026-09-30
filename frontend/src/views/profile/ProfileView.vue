<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { changeMyPasswordApi, updateMeApi } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import { useClientStore } from '@/stores/client'

const auth = useAuthStore()
const client = useClientStore()

const me = computed(() => auth.user)

const ROLE_LABELS: Record<string, string> = {
  admin: '管理员',
  staff: '教务',
  teacher: '教师',
  parent: '家长',
  student: '学员',
}
const roleLabel = computed(() => (me.value ? ROLE_LABELS[me.value.role] || me.value.role : ''))

const canEditCampus = computed(
  () => !!me.value && ['admin', 'staff', 'teacher'].includes(me.value.role),
)

const saving = ref(false)
const saveMsg = ref('')
const saveErr = ref('')
const info = ref({ name: '', phone: '', campus: '' })

// 修改密码
const pwForm = ref({ old: '', next: '', confirm: '' })
const pwSaving = ref(false)
const pwMsg = ref('')
const pwErr = ref('')

function syncInfo() {
  info.value = {
    name: me.value?.name ?? '',
    phone: me.value?.phone ?? '',
    campus: me.value?.campus ?? '',
  }
}

onMounted(syncInfo)

async function saveInfo() {
  saveMsg.value = ''
  saveErr.value = ''
  if (!info.value.name.trim()) {
    saveErr.value = '姓名不能为空'
    return
  }
  saving.value = true
  try {
    const updated = await updateMeApi({
      name: info.value.name.trim(),
      phone: info.value.phone.trim() || null,
      campus: canEditCampus.value ? info.value.campus.trim() || null : undefined,
    })
    saveMsg.value = '保存成功 ✓'
    // 同步全局用户信息（顶栏姓名/角色展示即时刷新）
    auth.user = updated
    if (['parent', 'student'].includes(updated.role)) {
      client.loadMe(true).catch(() => {})
    }
  } catch (e: any) {
    saveErr.value = e?.response?.data?.detail || '保存失败，请重试'
  } finally {
    saving.value = false
  }
}

async function changePassword() {
  pwMsg.value = ''
  pwErr.value = ''
  const { old: oldPw, next, confirm } = pwForm.value
  if (!oldPw) {
    pwErr.value = '请输入原密码'
    return
  }
  if (next.length < 6) {
    pwErr.value = '新密码至少 6 位'
    return
  }
  if (next !== confirm) {
    pwErr.value = '两次输入的新密码不一致'
    return
  }
  if (next === oldPw) {
    pwErr.value = '新密码不能与原密码相同'
    return
  }
  pwSaving.value = true
  try {
    await changeMyPasswordApi(oldPw, next)
    pwMsg.value = '密码修改成功 ✓ 下次登录请使用新密码'
    pwForm.value = { old: '', next: '', confirm: '' }
  } catch (e: any) {
    pwErr.value = e?.response?.data?.detail || '修改失败，请重试'
  } finally {
    pwSaving.value = false
  }
}
</script>

<template>
  <div class="profile-page">
    <div class="profile-card">
      <h1>个人信息</h1>
      <p class="profile-sub">完善资料与定期修改密码，保障账号安全</p>

      <div class="id-block">
        <div class="big-avatar">{{ (me?.name || '?').slice(0, 1) }}</div>
        <div class="id-meta">
          <div class="id-name">{{ me?.name }}</div>
          <div class="id-tags">
            <span class="role-pill">{{ roleLabel }}</span>
            <span class="uname-pill">{{ me?.username }}</span>
            <span v-if="me?.campus" class="campus-pill">{{ me.campus }}</span>
          </div>
        </div>
      </div>

      <div class="form-grid">
        <label>
          姓名
          <input v-model="info.name" type="text" maxlength="64" />
        </label>
        <label>
          手机号
          <input v-model="info.phone" type="text" maxlength="20" placeholder="选填，用于接收通知" />
        </label>
        <label v-if="canEditCampus">
          校区
          <input v-model="info.campus" type="text" placeholder="如：一校 / 二校 / 三校" />
        </label>
      </div>
      <p v-if="saveErr" class="msg err">{{ saveErr }}</p>
      <p v-if="saveMsg" class="msg ok">{{ saveMsg }}</p>
      <div class="actions">
        <button class="btn primary" :disabled="saving" @click="saveInfo">
          {{ saving ? '保存中…' : '保存资料' }}
        </button>
      </div>
    </div>

    <div class="profile-card">
      <h2>修改密码</h2>
      <p class="profile-sub">修改后请牢记新密码；忘记密码可联系机构管理员重置</p>
      <div class="form-grid">
        <label>
          原密码
          <input v-model="pwForm.old" type="password" autocomplete="current-password" placeholder="输入当前密码" />
        </label>
        <label>
          新密码
          <input v-model="pwForm.next" type="password" autocomplete="new-password" placeholder="至少 6 位" />
        </label>
        <label>
          确认新密码
          <input v-model="pwForm.confirm" type="password" autocomplete="new-password" placeholder="再次输入新密码" />
        </label>
      </div>
      <p v-if="pwErr" class="msg err">{{ pwErr }}</p>
      <p v-if="pwMsg" class="msg ok">{{ pwMsg }}</p>
      <div class="actions">
        <button class="btn primary" :disabled="pwSaving" @click="changePassword">
          {{ pwSaving ? '提交中…' : '修改密码' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.profile-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
  max-width: 760px;
  margin: 0 auto;
}

.profile-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 24px 26px;
  box-shadow: var(--shadow-sm);
}

.profile-card h1 {
  font-size: 20px;
}

.profile-card h2 {
  font-size: 17px;
}

.profile-sub {
  color: var(--ink-3);
  font-size: 12.5px;
  margin-top: 4px;
}

.id-block {
  display: flex;
  align-items: center;
  gap: 14px;
  margin: 18px 0 20px;
  padding: 14px 16px;
  border-radius: 14px;
  background: linear-gradient(135deg, #eef2ff, #f0fdfa);
}

.big-avatar {
  width: 54px;
  height: 54px;
  border-radius: 50%;
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  font-size: 22px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.id-meta {
  min-width: 0;
}

.id-name {
  font-size: 16px;
  font-weight: 700;
  color: var(--ink);
}

.id-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.role-pill,
.uname-pill,
.campus-pill {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 10px;
  border-radius: 999px;
}

.role-pill {
  background: var(--brand-soft);
  color: var(--brand-strong);
}

.uname-pill {
  background: rgba(15, 23, 42, 0.06);
  color: var(--ink-2);
  font-family: ui-monospace, Consolas, monospace;
}

.campus-pill {
  background: var(--accent-soft);
  color: #0e7490;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 14px 16px;
}

.form-grid label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: var(--ink-2);
}

.form-grid input {
  display: block;
  width: 100%;
  box-sizing: border-box;
  margin-top: 6px;
  padding: 9px 11px;
  border: 1px solid var(--line);
  border-radius: 10px;
  font-size: 14px;
  background: var(--surface);
  color: var(--ink);
  transition: all 0.15s;
}

.form-grid input:focus {
  outline: none;
  border-color: var(--brand);
  box-shadow: 0 0 0 3px var(--brand-soft);
}

.msg {
  font-size: 12.5px;
  margin-top: 10px;
}

.msg.err {
  color: var(--danger);
}

.msg.ok {
  color: var(--success);
}

.actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 9px 18px;
  border-radius: 10px;
  border: none;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}

.btn.primary {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  box-shadow: 0 6px 16px rgba(99, 102, 241, 0.3);
}

.btn.primary:hover {
  transform: translateY(-1px);
}

.btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  transform: none;
}
</style>
