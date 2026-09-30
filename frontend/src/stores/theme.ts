import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  getSystemSettings,
  updateSystemSettings,
  type SystemSettings,
} from '@/api/system'

export const LOGIN_THEMES = [
  { key: 'default', label: '深空藏青' },
  { key: 'light', label: '云白明亮' },
  { key: 'dark', label: '暗夜' },
  { key: 'poster', label: '品牌海报' },
] as const

export const UI_THEMES = [
  { key: 'default', label: '藏青默认', swatch: '#4f46e5' },
  { key: 'fresh', label: '清新薄荷', swatch: '#0e9f6e' },
  { key: 'calm', label: '沉稳墨蓝', swatch: '#2563eb' },
  { key: 'warm', label: '暖阳赭石', swatch: '#c2570b' },
] as const

/** 桌面背景预设：纯色（图片走上传） */
export const DESKTOP_BGS = [
  { key: 'default', label: '默认' },
  { key: '#eef3f1', label: '雾绿' },
  { key: '#edf1f8', label: '雾蓝' },
  { key: '#f7f1e8', label: '米白' },
  { key: '#eceef4', label: '浅灰' },
] as const

export const LOGIN_LOGOS = ['⚡', '📚', '🚀', '🌟', '💡', '🎓'] as const

export const SIDEBAR_THEMES = [
  { key: 'navy', label: '深海军蓝', desc: '默认深色' },
  { key: 'light', label: '云白浅色', desc: '浅底深字' },
  { key: 'brand', label: '主题品牌色', desc: '跟随系统主题' },
] as const

export const useThemeStore = defineStore('theme', () => {
  const loginTheme = ref('default')
  const desktopBg = ref('default')
  const uiTheme = ref('default')
  const loginTitle = ref('智能少儿编程教育')
  const loginSubtitle = ref('教务管理系统 · 教师效率提升 家长服务闭环')
  const loginLogo = ref('')
  const loginAccent = ref('')
  const loginHero = ref('排课 · 考勤 · 课时 · 反馈，一站式教务')
  const sidebarSub = ref('Child Code Studio')
  const sidebarTheme = ref('navy')
  const loaded = ref(false)

  function apply(s: Partial<SystemSettings>) {
    if (s.login_theme) {
      loginTheme.value = s.login_theme
    }
    if (s.desktop_bg !== undefined) {
      desktopBg.value = s.desktop_bg || 'default'
    }
    if (s.ui_theme) {
      uiTheme.value = s.ui_theme
      document.documentElement.dataset.uiTheme = s.ui_theme
    }
    if (s.login_title !== undefined && s.login_title) loginTitle.value = s.login_title
    if (s.login_subtitle !== undefined && s.login_subtitle) loginSubtitle.value = s.login_subtitle
    if (s.login_logo !== undefined) loginLogo.value = s.login_logo || ''
    if (s.login_accent !== undefined) loginAccent.value = s.login_accent || ''
    if (s.login_hero !== undefined && s.login_hero) loginHero.value = s.login_hero
    if (s.sidebar_sub !== undefined && s.sidebar_sub) sidebarSub.value = s.sidebar_sub
    if (s.sidebar_theme !== undefined && s.sidebar_theme) sidebarTheme.value = s.sidebar_theme
  }

  async function load() {
    try {
      apply(await getSystemSettings())
    } catch {
      // 后端不可用时保持默认主题
    } finally {
      loaded.value = true
    }
  }

  async function save(payload: Partial<SystemSettings>) {
    apply(await updateSystemSettings(payload))
  }

  /** 登录 Logo 是否图片（http/或 /uploads 路径） */
  const loginLogoIsImage = computed(
    () => /^https?:\/\//.test(loginLogo.value) || loginLogo.value.startsWith('/'),
  )

  /** 桌面背景 style：支持纯色 / 图片 URL（/uploads 由 vite/网关代理到后端） */
  const isBgImage = computed(() => /^https?:\/\//.test(desktopBg.value) || desktopBg.value.startsWith('/'))
  const mainBgStyle = computed((): Record<string, string> => {
    if (desktopBg.value === 'default' || !desktopBg.value) return {}
    if (isBgImage.value) {
      return {
        backgroundImage: `url(${desktopBg.value})`,
        backgroundSize: 'cover',
        backgroundPosition: 'center',
        backgroundAttachment: 'fixed',
      }
    }
    return { background: desktopBg.value }
  })

  /** 客户端头部 style：强调色存在时用强调色渐变，否则走默认深色渐变 */
  const clientHeaderStyle = computed((): Record<string, string> => {
    if (!loginAccent.value) return {}
    return { background: `linear-gradient(135deg, ${loginAccent.value}, var(--brand-strong))` }
  })

  return {
    loginTheme,
    desktopBg,
    uiTheme,
    loginTitle,
    loginSubtitle,
    loginLogo,
    loginAccent,
    loginHero,
    sidebarSub,
    sidebarTheme,
    loaded,
    loginLogoIsImage,
    mainBgStyle,
    clientHeaderStyle,
    load,
    save,
  }
})
