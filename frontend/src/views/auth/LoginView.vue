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
const showPassword = ref(false)
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
    <!-- ========== 舞台：场景 + 卡片整体居中 ========== -->
    <div class="stage">

    <!-- ========== 主题场景（纯装饰，aria-hidden） ========== -->


    <!-- 1) 积木工坊：Scratch 缺口积木堆 -->
    <div v-if="theme.loginTheme === 'default'" class="scene blocks-scene" aria-hidden="true">
      <p class="scene-kicker">SCRATCH BLOCKS · 拼出每一步成长</p>
      <div class="block-stack">
        <span class="blk blk-flag">当 <b>绿旗</b> 被点击</span>
        <span class="blk blk-move">移动 <b>10</b> 步</span>
        <span class="blk blk-loop">重复执行 <b>3</b> 次</span>
        <span class="blk blk-say">播报「<b>我上线啦</b>」</span>
      </div>
      <p class="scene-foot">// 每一次登录，都是一次奔跑的开始</p>
    </div>

    <!-- 2) 代码夜色：行号 gutter 贯穿全页 -->
    <div v-if="theme.loginTheme === 'dark'" class="scene gutter-scene" aria-hidden="true">
      <ol class="gutter">
        <li v-for="n in 16" :key="n">{{ n }}</li>
      </ol>
      <p class="gutter-hint">~ / 行舟 · 教师控制台</p>
    </div>

    <!-- 3) 像素乐园：编程乐园关卡 + 海龟画图彩虹轨迹 -->
    <div v-if="theme.loginTheme === 'light'" class="scene pixel-scene" aria-hidden="true">
      <svg class="pixel-art" viewBox="0 0 1280 280" preserveAspectRatio="xMidYMax slice" shape-rendering="crispEdges">
        <!-- 像素太阳（暖） -->
        <g fill="#ffd23f">
          <rect x="1096" y="40" width="64" height="8" />
          <rect x="1088" y="48" width="80" height="8" />
          <rect x="1080" y="56" width="96" height="8" />
          <rect x="1080" y="64" width="96" height="8" />
          <rect x="1080" y="72" width="96" height="8" />
          <rect x="1088" y="80" width="80" height="8" />
          <rect x="1096" y="88" width="64" height="8" />
        </g>
        <!-- 像素云 -->
        <g fill="#ffffff" opacity="0.95">
          <rect x="196" y="60" width="80" height="8" />
          <rect x="180" y="68" width="112" height="8" />
          <rect x="172" y="76" width="128" height="8" />
          <rect x="188" y="84" width="96" height="8" />
          <rect x="560" y="40" width="56" height="8" />
          <rect x="548" y="48" width="80" height="8" />
          <rect x="540" y="56" width="96" height="8" />
          <rect x="552" y="64" width="72" height="8" />
        </g>
        <!-- 圆润远山（薄荷绿，三级台阶） -->
        <g fill="#bfe8ad">
          <rect x="120" y="212" width="360" height="24" />
          <rect x="152" y="204" width="296" height="8" />
          <rect x="196" y="196" width="208" height="8" />
          <rect x="236" y="188" width="128" height="8" />
        </g>
        <g fill="#a9dd94">
          <rect x="760" y="212" width="400" height="24" />
          <rect x="796" y="204" width="328" height="8" />
          <rect x="848" y="196" width="224" height="8" />
          <rect x="892" y="188" width="136" height="8" />
        </g>
        <!-- 像素树（左） -->
        <g>
          <rect x="176" y="188" width="16" height="48" fill="#8b5a2b" />
          <rect x="160" y="156" width="48" height="8" fill="#4fae45" />
          <rect x="152" y="164" width="64" height="8" fill="#5fc457" />
          <rect x="144" y="172" width="80" height="8" fill="#5fc457" />
          <rect x="144" y="180" width="80" height="8" fill="#4fae45" />
          <rect x="152" y="188" width="64" height="8" fill="#4fae45" />
        </g>
        <!-- 像素树（右，较大） -->
        <g>
          <rect x="1120" y="176" width="16" height="60" fill="#8b5a2b" />
          <rect x="1096" y="136" width="64" height="8" fill="#4fae45" />
          <rect x="1088" y="144" width="80" height="8" fill="#5fc457" />
          <rect x="1080" y="152" width="96" height="8" fill="#5fc457" />
          <rect x="1080" y="160" width="96" height="8" fill="#5fc457" />
          <rect x="1080" y="168" width="96" height="8" fill="#4fae45" />
          <rect x="1088" y="176" width="80" height="8" fill="#4fae45" />
        </g>
        <!-- 海龟画图彩虹轨迹（签名元素）：一路拖到海龟尾部 -->
        <g>
          <rect x="96" y="216" width="32" height="8" fill="#ff8a7a" />
          <rect x="128" y="208" width="32" height="8" fill="#ffb84d" />
          <rect x="160" y="200" width="32" height="8" fill="#ffd84d" />
          <rect x="192" y="200" width="32" height="8" fill="#9be15d" />
          <rect x="224" y="208" width="32" height="8" fill="#4dd0c4" />
          <rect x="256" y="216" width="32" height="8" fill="#6ec1ff" />
          <rect x="288" y="216" width="32" height="8" fill="#c39bff" />
          <rect x="320" y="208" width="32" height="8" fill="#ff8a7a" />
          <rect x="352" y="200" width="32" height="8" fill="#ffb84d" />
          <rect x="384" y="192" width="32" height="8" fill="#ffd84d" />
          <rect x="416" y="192" width="32" height="8" fill="#9be15d" />
          <rect x="448" y="200" width="32" height="8" fill="#4dd0c4" />
          <rect x="480" y="208" width="32" height="8" fill="#6ec1ff" />
          <rect x="512" y="216" width="32" height="8" fill="#c39bff" />
          <rect x="544" y="216" width="32" height="8" fill="#ff8a7a" />
          <rect x="576" y="208" width="32" height="8" fill="#ffb84d" />
          <rect x="608" y="200" width="32" height="8" fill="#ffd84d" />
          <rect x="640" y="200" width="32" height="8" fill="#9be15d" />
          <rect x="672" y="208" width="32" height="8" fill="#4dd0c4" />
          <rect x="704" y="216" width="32" height="8" fill="#6ec1ff" />
          <rect x="736" y="216" width="32" height="8" fill="#c39bff" />
        </g>
        <!-- 像素海龟（面向右，正拖出轨迹） -->
        <g>
          <!-- 壳（深描边 + 亮填充 + 龟甲纹） -->
          <rect x="772" y="196" width="72" height="8" fill="#2f7d3f" />
          <rect x="764" y="204" width="88" height="24" fill="#2f7d3f" />
          <rect x="780" y="196" width="56" height="8" fill="#5fc457" />
          <rect x="772" y="204" width="72" height="16" fill="#6fd268" />
          <rect x="796" y="208" width="8" height="8" fill="#3f9b4d" />
          <rect x="820" y="208" width="8" height="8" fill="#3f9b4d" />
          <rect x="808" y="216" width="8" height="8" fill="#3f9b4d" />
          <!-- 头 + 眼 -->
          <rect x="852" y="200" width="24" height="20" fill="#6fd268" />
          <rect x="852" y="196" width="20" height="8" fill="#2f7d3f" />
          <rect x="868" y="204" width="6" height="6" fill="#17322a" />
          <!-- 四足 + 尾 -->
          <rect x="776" y="228" width="12" height="10" fill="#3f9b4d" />
          <rect x="824" y="228" width="12" height="10" fill="#3f9b4d" />
          <rect x="760" y="212" width="8" height="8" fill="#3f9b4d" />
        </g>
        <!-- 草地平台（双层绿 + 顶部亮边 + 底部土壤） -->
        <rect x="0" y="236" width="1280" height="44" fill="#6bcb5f" />
        <rect x="0" y="236" width="1280" height="8" fill="#8ee07f" />
        <rect x="0" y="268" width="1280" height="12" fill="#4fae45" />
        <!-- 草尖 + 小fafa -->
        <g fill="#5fc457">
          <rect x="56" y="230" width="8" height="8" /><rect x="332" y="230" width="8" height="8" />
          <rect x="512" y="230" width="8" height="8" /><rect x="704" y="230" width="8" height="8" />
          <rect x="1016" y="230" width="8" height="8" /><rect x="1224" y="230" width="8" height="8" />
        </g>
        <g>
          <rect x="384" y="252" width="8" height="8" fill="#ff8a9b" />
          <rect x="376" y="260" width="8" height="8" fill="#5fc457" />
          <rect x="376" y="244" width="8" height="8" fill="#ffd84d" />
          <rect x="936" y="256" width="8" height="8" fill="#6ec1ff" />
          <rect x="928" y="248" width="8" height="8" fill="#ffd84d" />
        </g>
      </svg>
    </div>

    <!-- 4) 品牌海报：海龟画图螺旋 + </> 轮廓字 -->
    <div v-if="theme.loginTheme === 'poster'" class="scene poster-scene" aria-hidden="true">
      <svg class="turtle-spiral" viewBox="0 0 400 400" fill="none">
        <g stroke="#8fd4ae" stroke-width="2.5" opacity="0.5">
          <rect x="40" y="40" width="320" height="320" rx="24" />
          <rect x="70" y="70" width="260" height="260" rx="20" opacity="0.8" />
          <rect x="100" y="100" width="200" height="200" rx="16" opacity="0.65" />
          <rect x="130" y="130" width="140" height="140" rx="12" opacity="0.5" />
          <rect x="160" y="160" width="80" height="80" rx="8" opacity="0.4" />
        </g>
        <circle cx="200" cy="200" r="14" fill="#8fd4ae" opacity="0.9" />
      </svg>
      <div class="poster-glyph">&lt;/&gt;</div>
      <div class="poster-copy">
        <div class="poster-kicker">{{ theme.loginSubtitle }}</div>
        <div class="poster-title">{{ theme.loginTitle }}</div>
        <div class="poster-sub">{{ theme.loginHero }}</div>
      </div>
    </div>

    <!-- ========== 登录卡片 ========== -->
    <section class="card">
      <div v-if="theme.loginTheme === 'dark'" class="win-bar" aria-hidden="true">
        <span class="win-dot dot-r" /><span class="win-dot dot-y" /><span class="win-dot dot-g" />
        <span class="win-name">login.ts — {{ theme.loginTitle }}</span>
      </div>
      <div class="card-body">
        <div class="logo">
          <div class="logo-mark">
            <BrandLogo :logo="theme.loginLogo" :accent="accent" />
          </div>
        </div>
        <h1>{{ theme.loginTitle }}</h1>
        <p class="sub" :class="{ 'mono-prompt': theme.loginTheme === 'dark' }">{{ theme.loginSubtitle }}</p>
        <p v-if="theme.loginHero && theme.loginTheme !== 'poster'" class="hero">{{ theme.loginHero }}</p>

        <form @submit.prevent="onSubmit">
          <label>
            <span>用户名</span>
            <input
              v-model="username"
              type="text"
              autocomplete="username"
              placeholder="请输入用户名"
              :style="{ '--field-accent': accent }"
            />
          </label>
          <label>
            <span>密码</span>
            <div class="pwd-field">
              <input
                v-model="password"
                :type="showPassword ? 'text' : 'password'"
                autocomplete="current-password"
                placeholder="请输入密码"
                :style="{ '--field-accent': accent }"
              />
              <button
                type="button"
                class="eye-btn"
                :title="showPassword ? '隐藏密码' : '显示密码'"
                :aria-label="showPassword ? '隐藏密码' : '显示密码'"
                @click="showPassword = !showPassword"
              >
                <svg v-if="!showPassword" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />
                  <circle cx="12" cy="12" r="3" />
                </svg>
                <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M9.9 4.2A10.9 10.9 0 0 1 12 4c6.5 0 10 7 10 7a17.6 17.6 0 0 1-3.4 4.3M6.6 6.6A17.6 17.6 0 0 0 2 11s3.5 7 10 7a10.9 10.9 0 0 0 4.1-.8M1 1l22 22" />
                </svg>
              </button>
            </div>
          </label>
          <p v-if="error" class="error">{{ error }}</p>
          <button type="submit" class="submit-btn" :disabled="loading" :style="{ background: accent }">
            <span v-if="loading" class="spinner" />{{ loading ? '登录中…' : '登录' }}
          </button>
        </form>
      </div>
    </section>
    </div>
  </main>
</template>

<style scoped>
/* ============ 主题令牌（每主题成套切换，保证协调） ============ */
.page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  position: relative;
  overflow: hidden;
  padding: 24px 48px;
  --login-bg: #14293f;
  --login-card: #ffffff;
  --login-ink: #14293f;
  --login-sub: #5b6d84;
  --login-accent: #d1560b;
  --login-accent-ink: #ffffff;
  --login-field-bg: #f3f6f5;
  --login-field-border: #dde5e3;
  --login-card-shadow: 0 24px 64px rgba(9, 26, 44, 0.22);
  background: var(--login-bg);
  transition: background 0.25s;
}
/* 舞台：场景 + 卡片整体在视口正中并排 */
.stage {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 72px;
  width: 100%;
  max-width: 1120px;
}

/* 1) 积木工坊：浅色工作台纸底 */
.page.login-default {
  --login-bg: #eef3f2;
  --login-ink: #14293f;
  --login-sub: #5b6d84;
  --login-accent: #d1560b;
  --login-field-bg: #f5f8f7;
  --login-field-border: #dde5e3;
  --login-card-shadow: 0 20px 48px rgba(20, 41, 63, 0.14);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.5) 0%, rgba(255, 255, 255, 0) 40%),
    var(--login-bg);
}

/* 2) 代码夜色：编辑器深底 */
.page.login-dark {
  --login-bg: #0e1520;
  --login-card: #101826;
  --login-ink: #d6e4f5;
  --login-sub: #7d8fa9;
  --login-accent: #e8b96b;
  --login-accent-ink: #1a1205;
  --login-field-bg: #0b1424;
  --login-field-border: #22314c;
  --login-card-shadow: 0 28px 70px rgba(0, 0, 0, 0.55);
}

/* 3) 像素乐园：像素天空 */
.page.login-light {
  --login-bg: #bfe3ff;
  --login-ink: #16324e;
  --login-sub: #4a6a88;
  --login-accent: #1d6fe0;
  --login-field-bg: #f3f9ff;
  --login-field-border: #cde2f5;
  --login-card-shadow: 0 20px 48px rgba(23, 50, 79, 0.16);
  background: linear-gradient(180deg, #a9dcff 0%, #cfeaff 46%, #eaf6ff 100%);
}

/* 4) 品牌海报：松林深底 */
.page.login-poster {
  --login-bg: #0a2b22;
  --login-ink: #17322a;
  --login-sub: #5b7a6d;
  --login-accent: #0b8a5f;
  --login-field-bg: #f2f7f4;
  --login-field-border: #d5e8dd;
  --login-card-shadow: 0 26px 64px rgba(3, 20, 12, 0.5);
  background:
    radial-gradient(900px 520px at 24% 30%, #14503a 0%, rgba(20, 80, 58, 0) 62%),
    radial-gradient(700px 420px at 82% 88%, #0e3a2c 0%, rgba(14, 58, 44, 0) 60%),
    var(--login-bg);
}

/* ============ 场景层 ============ */
/* 积木工坊 / 品牌海报：作为 flex 兄弟与卡片并排；其余为绝对定位背景装饰 */
.blocks-scene,
.poster-scene {
  position: relative;
  z-index: 1;
  flex-shrink: 0;
}
.gutter-scene,
.pixel-scene {
  position: absolute;
  pointer-events: none;
  z-index: 0;
}

/* —— 积木工坊 —— */
.blocks-scene {
  width: 380px;
}
.scene-kicker {
  font-family: var(--font-mono, ui-monospace, 'SF Mono', Consolas, monospace);
  font-size: 12px;
  letter-spacing: 0.18em;
  color: #8b9aa7;
  margin-bottom: 22px;
}
.block-stack {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
}
.blk {
  position: relative;
  display: inline-block;
  padding: 12px 22px 12px 16px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 700;
  color: #14293f;
  box-shadow:
    0 3px 0 rgba(20, 41, 63, 0.16),
    inset 0 1px 0 rgba(255, 255, 255, 0.45);
  opacity: 0;
  animation: blk-drop 0.5s cubic-bezier(0.22, 1, 0.36, 1) forwards;
}
.blk b {
  background: rgba(255, 255, 255, 0.55);
  border-radius: 5px;
  padding: 1px 7px;
  font-weight: 800;
}
/* Scratch 式缺口凸榫：继承块色的小半圆 */
.blk::after {
  content: '';
  position: absolute;
  left: 20px;
  bottom: -8px;
  width: 18px;
  height: 12px;
  background: inherit;
  border-radius: 0 0 10px 10px;
  box-shadow: 0 2px 0 rgba(20, 41, 63, 0.1);
}
.blk-flag { background: #ffab4d; margin-bottom: 14px; animation-delay: 0.05s; }
.blk-move { background: #7cc4ff; margin-bottom: 14px; margin-left: 26px; animation-delay: 0.15s; }
.blk-loop { background: #c39bff; margin-bottom: 14px; margin-left: 6px; animation-delay: 0.25s; }
.blk-say { background: #8fe3b0; margin-left: 32px; animation-delay: 0.35s; }
.scene-foot {
  margin-top: 26px;
  font-family: var(--font-mono, ui-monospace, 'SF Mono', Consolas, monospace);
  font-size: 12px;
  color: #9aa8b3;
}
@keyframes blk-drop {
  from { opacity: 0; transform: translateY(-14px); }
  to { opacity: 1; transform: translateY(0); }
}

/* —— 代码夜色 —— */
.gutter-scene {
  left: 0;
  top: 0;
  bottom: 0;
  width: 88px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: flex-end;
  padding-right: 18px;
  border-right: 1px solid rgba(34, 49, 76, 0.5);
}
.gutter {
  list-style: none;
  margin: 0;
  padding: 0;
  text-align: right;
  font-family: var(--font-mono, ui-monospace, 'SF Mono', Consolas, monospace);
  font-size: 11px;
  line-height: 1.9;
  color: #2c3d55;
}
.gutter li:nth-child(4n) {
  color: #40587a;
}
.gutter-hint {
  margin-top: 26px;
  font-family: var(--font-mono, ui-monospace, 'SF Mono', Consolas, monospace);
  font-size: 11px;
  color: #40587a;
  white-space: nowrap;
}

/* —— 像素乐园 —— */
.pixel-scene {
  left: 0;
  right: 0;
  bottom: 0;
  height: 280px;
}
.pixel-art {
  width: 100%;
  height: 100%;
  display: block;
  image-rendering: pixelated;
}

/* —— 品牌海报 —— */
.poster-scene {
  width: 400px;
  color: #f2fbf6;
}
.turtle-spiral {
  position: absolute;
  right: -40px;
  top: -80px;
  width: 360px;
  height: 360px;
  opacity: 0.55;
}
.poster-glyph {
  position: absolute;
  left: -10px;
  bottom: -115px;
  font-family: var(--font-mono, ui-monospace, 'SF Mono', Consolas, monospace);
  font-size: 130px;
  font-weight: 800;
  line-height: 1;
  color: transparent;
  -webkit-text-stroke: 1.5px rgba(143, 212, 174, 0.35);
  letter-spacing: -0.06em;
}
.poster-copy {
  position: relative;
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
  font-weight: 900;
  line-height: 1.25;
  letter-spacing: 0.01em;
}
.poster-sub {
  margin-top: 16px;
  font-size: 14px;
  color: #bfe3cf;
}

/* ============ 登录卡片 ============ */
.card {
  position: relative;
  z-index: 1;
  width: 400px;
  max-width: calc(100vw - 48px);
  background: var(--login-card);
  border-radius: 22px;
  box-shadow: var(--login-card-shadow);
  animation: card-rise 0.45s cubic-bezier(0.22, 1, 0.36, 1) both;
}
.card-body {
  padding: 34px 34px 30px;
}
@keyframes card-rise {
  from { opacity: 0; transform: translateY(16px); }
  to { opacity: 1; transform: translateY(0); }
}

/* 积木工坊：卡片像一块厚积木（底部硬边） */
.page.login-default .card {
  border: 1px solid #e2e9e7;
  border-bottom: 5px solid #d7e0dd;
  border-radius: 24px;
}
/* 代码夜色：卡片即编辑器窗口 */
.page.login-dark .card {
  border: 1px solid #1e2a3d;
  border-radius: 14px;
}
.win-bar {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 11px 16px;
  border-bottom: 1px solid #1e2a3d;
  background: #0c1420;
  border-radius: 14px 14px 0 0;
}
.win-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
}
.dot-r { background: #ff5f57; }
.dot-y { background: #febc2e; }
.dot-g { background: #28c840; }
.win-name {
  margin-left: 8px;
  font-family: var(--font-mono, ui-monospace, 'SF Mono', Consolas, monospace);
  font-size: 11px;
  color: #5f7694;
}
.page.login-dark .card-body {
  padding-top: 28px;
}
/* 像素乐园：干净小圆角 */
.page.login-light .card {
  border-radius: 18px;
  border: 1px solid rgba(255, 255, 255, 0.8);
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
  box-shadow: 0 10px 24px rgba(9, 26, 44, 0.22);
}
.page.login-default .logo-mark {
  border-radius: 18px;
  transform: rotate(-3deg);
}
h1 {
  font-size: 21px;
  text-align: center;
  color: var(--login-ink);
}
.page.login-default h1 {
  font-weight: 900;
  letter-spacing: 0.01em;
}
.sub {
  text-align: center;
  color: var(--login-sub);
  font-size: 12.5px;
  margin: 8px 0 22px;
}
.page.login-dark .sub.mono-prompt {
  font-family: var(--font-mono, ui-monospace, 'SF Mono', Consolas, monospace);
  font-size: 12px;
  color: #9ece6a;
}
.page.login-dark .sub.mono-prompt::before {
  content: '> ';
  color: #5f7694;
}
.sub:has(+ .hero) {
  margin-bottom: 8px;
}
.hero {
  text-align: center;
  color: var(--login-sub);
  opacity: 0.85;
  font-size: 12px;
  margin: 0 0 22px;
  line-height: 1.6;
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
.pwd-field {
  position: relative;
}
.pwd-field input {
  padding-right: 42px;
}
.eye-btn {
  position: absolute;
  top: 50%;
  right: 8px;
  transform: translateY(-50%);
  width: 28px;
  height: 28px;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 8px;
  background: none;
  color: var(--login-sub);
  cursor: pointer;
}
.eye-btn:hover {
  background: color-mix(in srgb, var(--login-sub) 14%, transparent);
  color: var(--login-ink);
}
.eye-btn svg {
  width: 17px;
  height: 17px;
}
.error {
  color: var(--danger, #dc2626);
  font-size: 13px;
  margin: 0 0 10px;
}
.submit-btn {
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
.page.login-default .submit-btn {
  border-radius: 10px;
  box-shadow: 0 3px 0 rgba(20, 41, 63, 0.22);
}
.submit-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  filter: brightness(1.06);
}
.submit-btn:focus-visible {
  outline: 2px solid var(--field-accent, var(--login-accent));
  outline-offset: 2px;
}
.submit-btn:disabled {
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
.page.login-dark .spinner {
  border-color: rgba(26, 18, 5, 0.25);
  border-top-color: #1a1205;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

/* ============ 响应式：场景在窄屏隐藏，卡片居中 ============ */
@media (max-width: 1160px) {
  .blocks-scene,
  .poster-scene {
    display: none;
  }
}
@media (max-width: 760px) {
  .page {
    padding: 20px;
  }
  .gutter-scene,
  .pixel-scene {
    opacity: 0.45;
  }
}

/* ============ 无障碍：尊重减少动效 ============ */
@media (prefers-reduced-motion: reduce) {
  .card,
  .blk {
    animation: none;
    opacity: 1;
  }
  .submit-btn:hover:not(:disabled) {
    transform: none;
  }
}
</style>
