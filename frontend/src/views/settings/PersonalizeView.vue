<script setup lang="ts">
/**
 * 个性化设置（管理员）：登录页主题、桌面背景、系统主题风格，全局生效。
 * 权限默认给管理员（后端 PUT 仅 admin）。
 */
import { computed, onMounted, ref } from 'vue'

import PageHead from '@/components/PageHead.vue'
import { getSystemSettings, updateSystemSettings, uploadSettingImage } from '@/api/system'
import { DESKTOP_BGS, LOGIN_THEMES, SIDEBAR_THEMES, UI_THEMES, useThemeStore } from '@/stores/theme'
import BrandLogo from '@/components/BrandLogo.vue'
import { LOGO_ICONS } from '@/components/brandLogos'

const ACCENT_PRESETS = ['#2f6fed', '#0e9f6e', '#2563eb', '#c2570b', '#7c3aed', '#be123c']

defineProps<{ embedded?: boolean }>()

const theme = useThemeStore()
const loginTheme = ref('default')
const loginTitle = ref('')
const loginSubtitle = ref('')
const loginLogo = ref('')
const loginAccent = ref('')
const loginHero = ref('')
const sidebarSub = ref('')
const sidebarTheme = ref('navy')
// 侧边栏模块排序：与 AdminLayout ADMIN_NAV 一一对应（to 唯一键；权限管理仅管理员可见，照常排）
const NAV_MODULES = [
  { to: '/students', label: '学员管理' },
  { to: '/invitations', label: '招生邀约' },
  { to: '/classes', label: '班级管理' },
  { to: '/teachers', label: '教师管理' },
  { to: '/permissions', label: '权限管理' },
  { to: '/settings', label: '设置' },
  { to: '/schedules', label: '排课与考勤' },
  { to: '/packages', label: '课时包管理' },
  { to: '/feedbacks', label: '课后反馈' },
  { to: '/reports', label: '报告·总结' },
  { to: '/evaluations', label: '学员评估' },
  { to: '/agents', label: 'Agent 工作台' },
  { to: '/assignments', label: 'AI 习题' },
  { to: '/finance', label: '财务管理' },
]
const navOrder = ref<string[]>([])
function orderedModules() {
  const order = navOrder.value.filter((t) => NAV_MODULES.some((m) => m.to === t))
  const rest = NAV_MODULES.map((m) => m.to).filter((t) => !order.includes(t))
  return [...order, ...rest].map((t) => NAV_MODULES.find((m) => m.to === t)!)
}
function moveNav(i: number, dir: -1 | 1) {
  const list = orderedModules().map((m) => m.to)
  const j = i + dir
  if (j < 0 || j >= list.length) return
  ;[list[i], list[j]] = [list[j], list[i]]
  navOrder.value = list
}
const desktopBg = ref('default')
const customBg = ref('')
const uiTheme = ref('default')
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const doneMsg = ref('')
const uploading = ref(false)
const uploadError = ref('')
const bgFileInput = ref<HTMLInputElement | null>(null)
const logoFileInput = ref<HTMLInputElement | null>(null)
const isBgImageUrl = computed(() => /^(\/|https?:\/\/)/.test(customBg.value.trim()))

async function onBgFile(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  uploading.value = true
  uploadError.value = ''
  try {
    customBg.value = await uploadSettingImage(file)
    desktopBg.value = '__custom__'
  } catch (err: any) {
    uploadError.value = err?.response?.data?.detail || '上传失败'
  } finally {
    uploading.value = false
    if (bgFileInput.value) bgFileInput.value.value = ''
  }
}

async function onLogoFile(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  uploading.value = true
  uploadError.value = ''
  try {
    loginLogo.value = await uploadSettingImage(file)
  } catch (err: any) {
    uploadError.value = err?.response?.data?.detail || '上传失败'
  } finally {
    uploading.value = false
    if (logoFileInput.value) logoFileInput.value.value = ''
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const s = await getSystemSettings()
    loginTheme.value = s.login_theme
    loginTitle.value = s.login_title || ''
    loginSubtitle.value = s.login_subtitle || ''
    loginLogo.value = s.login_logo || ''
    loginAccent.value = s.login_accent || ''
    loginHero.value = s.login_hero || ''
    sidebarSub.value = s.sidebar_sub || ''
    sidebarTheme.value = s.sidebar_theme || 'navy'
    navOrder.value = Array.isArray(s.nav_order) ? s.nav_order : []
    uiTheme.value = s.ui_theme
    if (DESKTOP_BGS.some((b) => b.key === s.desktop_bg)) {
      desktopBg.value = s.desktop_bg
      customBg.value = ''
    } else if (s.desktop_bg && s.desktop_bg !== 'default') {
      desktopBg.value = '__custom__'
      customBg.value = s.desktop_bg
    }
  } catch {
    error.value = '加载个性化设置失败'
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  error.value = ''
  doneMsg.value = ''
  try {
    const bg = desktopBg.value === '__custom__' ? customBg.value.trim() : desktopBg.value
    await theme.save({
      login_theme: loginTheme.value,
      login_title: loginTitle.value.trim(),
      login_subtitle: loginSubtitle.value.trim(),
      login_logo: loginLogo.value.trim(),
      login_accent: loginAccent.value.trim(),
      login_hero: loginHero.value.trim(),
      sidebar_sub: sidebarSub.value.trim(),
      sidebar_theme: sidebarTheme.value,
      nav_order: orderedModules().map((m) => m.to),
      desktop_bg: bg || 'default',
      ui_theme: uiTheme.value,
    })
    // 同步本地选中态
    if (DESKTOP_BGS.some((b) => b.key === bg)) {
      desktopBg.value = bg
      customBg.value = ''
    } else if (bg && bg !== 'default') {
      desktopBg.value = '__custom__'
      customBg.value = bg
    }
    doneMsg.value = '已保存，全局生效（含登录页与各端桌面背景）。'
  } catch (e: any) {
    error.value = e?.response?.data?.detail || '保存失败'
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <PageHead v-if="!embedded" title="个性化设置" eyebrow="PERSONALIZE" sub="管理员配置登录品牌、桌面背景与系统主题风格，保存后全局生效。">
      <template #actions>
      <button class="btn primary" :disabled="saving" @click="save">
        {{ saving ? '保存中…' : '保存设置' }}
      </button>
      </template>
    </PageHead>

    <p v-if="error" class="perm-error">{{ error }}</p>
    <p v-if="doneMsg" class="done-msg">{{ doneMsg }}</p>
    <p v-if="loading" class="muted">加载中…</p>

    <template v-else>
      <section class="card">
        <h2>登录页面主题</h2>
        <div class="swatches">
          <button
            v-for="t in LOGIN_THEMES"
            :key="t.key"
            class="swatch"
            :class="{ active: loginTheme === t.key }"
            @click="loginTheme = t.key"
          >
            <span class="swatch-preview" :class="`login-prev-${t.key}`">登</span>
            <span>{{ t.label }}</span>
          </button>
        </div>
      </section>

      <section class="card">
        <h2>登录品牌（标题 / Logo / 强调色）</h2>
        <p class="muted">登录框标题、副标题、Logo 与按钮颜色，保存后登录页即时换装。</p>
        <div class="brand-grid">
          <label class="field">
            <span>主标题</span>
            <input v-model="loginTitle" type="text" placeholder="如：智能少儿编程教育" />
          </label>
          <label class="field">
            <span>副标题</span>
            <input v-model="loginSubtitle" type="text" placeholder="如：教务管理系统 · 教师效率提升 家长服务闭环" />
          </label>
        </div>
        <label class="field">
          <span>海报副文案（品牌海报主题左侧底部）</span>
          <input v-model="loginHero" type="text" placeholder="如：排课 · 考勤 · 课时 · 反馈，一站式教务" />
        </label>
        <div class="field">
          <span class="field-label">Logo</span>
          <div class="logo-row">
            <button
              v-for="item in LOGO_ICONS"
              :key="item.key"
              class="logo-opt"
              :class="{ active: loginLogo === item.key || (!loginLogo && item.key === 'icon:cap') }"
              :title="item.label"
              @click="loginLogo = item.key"
            >
              <BrandLogo :logo="item.key" accent="var(--surface-alt)" ink="var(--brand-strong)" />
            </button>
            <label class="upload-btn sm">
              <input ref="logoFileInput" type="file" accept="image/*" hidden @change="onLogoFile" />
              {{ uploading ? '上传中…' : '上传图片' }}
            </label>
            <button v-if="loginLogo" class="link-btn" @click="loginLogo = ''">恢复默认</button>
          </div>
          <div class="logo-preview">
            <BrandLogo :logo="loginLogo" />
          </div>
        </div>
        <div class="field">
          <span class="field-label">强调色（登录按钮 / 输入聚焦 / Logo 底）</span>
          <div class="logo-row">
            <button
              v-for="c in ACCENT_PRESETS"
              :key="c"
              class="accent-opt"
              :class="{ active: loginAccent === c }"
              :style="{ background: c }"
              :title="c"
              @click="loginAccent = c"
            />
            <input v-model="loginAccent" class="color-text" type="text" placeholder="#2f6fed（留空跟随主题）" />
            <button v-if="loginAccent" class="link-btn" @click="loginAccent = ''">跟随主题</button>
          </div>
        </div>
      </section>

      <section class="card">
        <h2>侧边栏风格</h2>
        <p class="muted">教师 / 管理端左侧导航栏的配色与副标题，保存后即时生效。</p>
        <div class="swatches">
          <button
            v-for="t in SIDEBAR_THEMES"
            :key="t.key"
            class="swatch wide"
            :class="{ active: sidebarTheme === t.key }"
            @click="sidebarTheme = t.key"
          >
            <span class="swatch-preview" :class="`sidebar-prev-${t.key}`">
              <i /><i /><i />
            </span>
            <span>{{ t.label }}</span>
            <small>{{ t.desc }}</small>
          </button>
        </div>
        <label class="field" style="margin-top: 12px">
          <span>侧边栏副标题（标题下方小字）</span>
          <input v-model="sidebarSub" type="text" placeholder="如：Child Code Studio" />
        </label>
        <div class="field" style="margin-top: 12px">
          <span>模块上下排序（上↑ / 下↓ 调整，保存后所有人侧边栏即时生效）</span>
          <ul class="nav-order-list">
            <li v-for="(m, i) in orderedModules()" :key="m.to" class="nav-order-row">
              <span class="nav-order-num">{{ i + 1 }}</span>
              <span class="nav-order-label">{{ m.label }}</span>
              <span class="nav-order-btns">
                <button class="mini-btn" :disabled="i === 0" @click="moveNav(i, -1)">上移</button>
                <button class="mini-btn" :disabled="i === orderedModules().length - 1" @click="moveNav(i, 1)">下移</button>
              </span>
            </li>
          </ul>
        </div>
      </section>

      <section class="card">
        <h2>桌面背景</h2>
        <p class="muted">作用于管理端右侧主区域背景，保存后即时生效。</p>
        <div class="swatches">
          <button
            v-for="b in DESKTOP_BGS"
            :key="b.key"
            class="swatch"
            :class="{ active: desktopBg === b.key }"
            @click="desktopBg = b.key"
          >
            <span class="swatch-preview" :style="b.key === 'default' ? {} : { background: b.key }" />
            <span>{{ b.label }}</span>
          </button>
          <button class="swatch" :class="{ active: desktopBg === '__custom__' }" @click="desktopBg = '__custom__'">
            <span class="swatch-preview custom">?</span>
            <span>自定义颜色/图片</span>
          </button>
        </div>
        <div v-if="desktopBg === '__custom__'" class="custom-bg-row">
          <input
            v-model="customBg"
            class="custom-input"
            type="text"
            placeholder="纯色如 #e8f4f0，或图片地址如 https://…/bg.jpg"
          />
          <label class="upload-btn">
            <input ref="bgFileInput" type="file" accept="image/*" hidden @change="onBgFile" />
            {{ uploading ? '上传中…' : '上传图片' }}
          </label>
        </div>
        <p v-if="uploadError" class="perm-error" style="margin-top: 8px">{{ uploadError }}</p>
        <div v-if="desktopBg === '__custom__' && isBgImageUrl" class="bg-preview">
          <img :src="customBg" alt="桌面背景预览" />
        </div>
      </section>

      <section class="card">
        <h2>系统主题风格</h2>
        <p class="muted">切换全站主色（纯色系），即时预览。</p>
        <div class="swatches">
          <button
            v-for="t in UI_THEMES"
            :key="t.key"
            class="swatch"
            :class="{ active: uiTheme === t.key }"
            @click="uiTheme = t.key"
          >
            <span class="swatch-preview" :style="{ background: t.swatch }" />
            <span>{{ t.label }}</span>
          </button>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
  gap: 12px;
}
h1 {
  font-size: 22px;
}
.page-sub {
  color: var(--ink-3);
  font-size: 13px;
  margin-top: 4px;
}
.perm-error {
  color: var(--danger);
  background: var(--danger-soft);
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 13px;
  margin-bottom: 12px;
}
.done-msg {
  color: #047857;
  background: #e0fbe9;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 13px;
  margin-bottom: 12px;
}
.muted {
  color: var(--ink-3);
  font-size: 13px;
  margin-bottom: 8px;
}
.card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 18px;
  margin-bottom: 14px;
}
.card h2 {
  font-size: 15.5px;
  margin-bottom: 12px;
}
.swatches {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.swatch {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border: 2px solid var(--line);
  border-radius: 12px;
  background: var(--surface);
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-2);
  cursor: pointer;
  min-width: 110px;
}
.swatch.active {
  border-color: var(--brand);
  color: var(--brand-strong);
}
.swatch.wide {
  min-width: 150px;
}
.swatch small {
  font-size: 11px;
  font-weight: 400;
  color: var(--ink-3);
}
.sidebar-prev-navy,
.sidebar-prev-light,
.sidebar-prev-brand {
  flex-direction: row;
  align-items: center;
  justify-content: center;
  gap: 3px;
  width: 52px;
}
.sidebar-prev-navy i,
.sidebar-prev-light i,
.sidebar-prev-brand i {
  width: 5px;
  height: 18px;
  border-radius: 3px;
  background: currentColor;
  opacity: 0.55;
}
.sidebar-prev-navy i:first-child,
.sidebar-prev-light i:first-child,
.sidebar-prev-brand i:first-child {
  opacity: 1;
}
.sidebar-prev-navy {
  background: #101d33;
  color: #8ea0bb;
}
.sidebar-prev-light {
  background: #f4f6fa;
  color: #94a3b8;
}
.sidebar-prev-brand {
  background: var(--brand);
  color: rgba(255, 255, 255, 0.85);
}
.swatch-preview {
  width: 44px;
  height: 30px;
  border-radius: 8px;
  border: 1px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: #fff;
  font-weight: 700;
}
.login-prev-default,
.login-prev-dark {
  background: #0f172a;
}
.login-prev-light {
  background: #eef2f7;
  color: var(--ink-2);
}
.login-prev-poster {
  background: #123524;
}
.swatch-preview.custom {
  background: var(--surface-alt);
  color: var(--ink-3);
}
.custom-input {
  margin-top: 12px;
  width: 100%;
  max-width: 480px;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 9px 12px;
  font-size: 13.5px;
  background: var(--surface);
  color: var(--ink);
}
.custom-bg-row {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-top: 4px;
}
.custom-bg-row .custom-input {
  margin-top: 12px;
  flex: 1;
}
.upload-btn {
  margin-top: 12px;
  flex-shrink: 0;
  padding: 9px 18px;
  border-radius: 10px;
  border: 1px solid var(--brand);
  background: var(--brand-soft);
  color: var(--brand-strong);
  font-size: 13.5px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}
.upload-btn:hover {
  background: var(--brand);
  color: #fff;
}
.bg-preview {
  margin-top: 12px;
  max-width: 480px;
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
}
.bg-preview img {
  display: block;
  width: 100%;
  max-height: 220px;
  object-fit: cover;
}
.brand-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 14px;
}
.field > span,
.field-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-2);
}
.field input[type='text'] {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 9px 12px;
  font-size: 13.5px;
  background: var(--surface);
  color: var(--ink);
}
.logo-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.logo-opt {
  width: 42px;
  height: 42px;
  font-size: 20px;
  border-radius: 12px;
  border: 2px solid var(--line);
  background: var(--surface);
  cursor: pointer;
}
.logo-opt.active {
  border-color: var(--brand);
  background: var(--brand-soft);
}
.accent-opt {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  border: 2px solid transparent;
  cursor: pointer;
}
.accent-opt.active {
  border-color: var(--ink);
}
.color-text {
  width: 200px;
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 8px 10px;
  font-size: 13px;
  background: var(--surface);
  color: var(--ink);
}
.upload-btn.sm {
  margin-top: 0;
  padding: 8px 14px;
  font-size: 13px;
}
.link-btn {
  background: none;
  border: none;
  color: var(--brand-strong);
  font-size: 12.5px;
  cursor: pointer;
}
.logo-preview {
  margin-top: 10px;
  width: 64px;
  height: 64px;
  border-radius: 16px;
  border: 1px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: var(--surface-alt);
}
.logo-preview img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.logo-preview-emoji {
  font-size: 30px;
}
.nav-order-list {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.nav-order-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
}
.nav-order-num {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--brand-soft);
  color: var(--brand-strong);
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.nav-order-label {
  flex: 1;
  font-size: 14px;
  color: var(--ink-2);
}
.nav-order-btns {
  display: flex;
  gap: 6px;
}
.mini-btn {
  border: 1px solid var(--line);
  background: var(--bg-soft);
  color: var(--ink-2);
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 8px;
  cursor: pointer;
}
.mini-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.mini-btn:not(:disabled):hover {
  border-color: var(--brand);
  color: var(--brand-strong);
}
</style>
