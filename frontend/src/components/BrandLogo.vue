<script setup lang="ts">
/**
 * 品牌 Logo：图片 / 预设线条图标 / 兼容旧 emoji / 空则默认学位帽。
 * 登录页、侧边栏、个性化预览共用，保证三处一致。
 */
import { computed, ref } from 'vue'

import { ICON_PATHS } from './brandLogos'

const props = withDefaults(
  defineProps<{
    logo?: string
    /** 外层底座背景；空则用品牌色 */
    accent?: string
    /** 图标颜色；默认白色 */
    ink?: string
  }>(),
  { logo: '', accent: '', ink: '#fff' },
)

const kind = computed<'image' | 'icon' | 'emoji' | 'default'>(() => {
  const v = (props.logo || '').trim()
  if (!v || imgBroken.value) return 'default'
  if (/^https?:\/\//.test(v) || v.startsWith('/')) return 'image'
  if (v.startsWith('icon:')) return 'icon'
  return 'emoji'
})

/** 图片 404/失效时回退默认图标，永不空白 */
const imgBroken = ref(false)

const iconKey = computed(() => {
  const v = (props.logo || '').trim()
  if (v.startsWith('icon:')) {
    const k = v.slice(5)
    if (ICON_PATHS[k]) return k
  }
  return 'cap'
})
</script>

<template>
  <span class="brandlogo-tile" :style="{ background: accent || undefined, color: ink }">
    <img v-if="kind === 'image'" :src="logo" alt="logo" @error="imgBroken = true" />
    <svg
      v-else-if="kind === 'icon' || kind === 'default'"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.8"
      stroke-linecap="round"
      stroke-linejoin="round"
    >
      <path :d="ICON_PATHS[iconKey]" />
    </svg>
    <span v-else class="brandlogo-emoji">{{ logo }}</span>
  </span>
</template>

<style scoped>
.brandlogo-tile {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  background: var(--brandlogo-accent, var(--brand));
  color: #fff;
  border-radius: inherit;
  overflow: hidden;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.28),
    inset 0 -2px 4px rgba(0, 0, 0, 0.12);
}
.brandlogo-tile svg {
  width: 62%;
  height: 62%;
}
.brandlogo-tile img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.brandlogo-emoji {
  font-size: 1.4em;
  line-height: 1;
}
</style>
