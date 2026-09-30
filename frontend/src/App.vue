<template>
  <RouterView />
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterView } from 'vue-router'

import { useThemeStore } from './stores/theme'

const theme = useThemeStore()
onMounted(() => {
  theme.load()
})
</script>

<style>
:root {
  /* 品牌色板 — 2026 精炼版：更柔和通透的 indigo × 天青 */
  --brand: #615fff;
  --brand-strong: #4f46e5;
  --brand-soft: #eef2ff;
  --brand-glow: rgba(97, 95, 255, 0.14);
  --brand-gradient: linear-gradient(135deg, #615fff 0%, #7c86ff 46%, #00b8db 100%);
  --brand-gradient-soft: linear-gradient(135deg, #eef2ff 0%, #ecfeff 100%);
  --accent: #00b8db;
  --accent-strong: #007595;
  --accent-soft: #ecfeff;
  --success: #0e9f6e;
  --success-soft: #e0fbe9;
  --warning: #f59e0b;
  --warning-soft: #fef3c7;
  --danger: #ef4444;
  --danger-soft: #fee2e2;

  /* 中性色 — 更通透的灰阶 */
  --ink: #0f172a;
  --ink-2: #314158;
  --ink-3: #62748e;
  --ink-light: #90a1b9;
  --line: #e2e8f0;
  --line-soft: #f1f5f9;
  --bg: #f8fafc;
  --bg-soft: #f1f5f9;
  --surface: #ffffff;
  --surface-alt: #f8faff;

  /* 阴影 — 更柔和的层次 */
  --shadow-xs: 0 1px 2px rgba(15, 23, 42, 0.04);
  --shadow-sm: 0 2px 8px rgba(15, 23, 42, 0.06);
  --shadow-md: 0 8px 24px rgba(15, 23, 42, 0.08);
  --shadow-lg: 0 16px 40px rgba(15, 23, 42, 0.12);
  --shadow-brand: 0 8px 22px rgba(97, 95, 255, 0.22);

  /* 圆角与字体 */
  --radius-xl: 20px;
  --radius-lg: 16px;
  --radius: 12px;
  --radius-sm: 8px;
  --radius-pill: 999px;
  --ability-radius: 999px;
  --font:
    'Inter', -apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

/* —— 系统主题风格（个性化设置，全局生效；均为纯色系，无渐变） —— */
:root[data-ui-theme='fresh'] {
  --brand: #0e9f6e;
  --brand-strong: #047857;
  --brand-soft: #e0fbe9;
  --brand-glow: rgba(14, 159, 110, 0.14);
  --accent: #0e9f6e;
  --accent-strong: #047857;
  --accent-soft: #e0fbe9;
  --surface-alt: #f2fbf6;
  --bg: #f4faf7;
  --shadow-brand: 0 8px 22px rgba(14, 159, 110, 0.2);
}
:root[data-ui-theme='calm'] {
  --brand: #2563eb;
  --brand-strong: #1d4ed8;
  --brand-soft: #e4edfe;
  --brand-glow: rgba(37, 99, 235, 0.14);
  --accent: #0284c7;
  --accent-strong: #0369a1;
  --accent-soft: #e0f2fe;
  --surface-alt: #f4f8ff;
  --bg: #f4f7fc;
  --shadow-brand: 0 8px 22px rgba(37, 99, 235, 0.2);
}
:root[data-ui-theme='warm'] {
  --brand: #c2570b;
  --brand-strong: #9a4a0a;
  --brand-soft: #fdf0e0;
  --brand-glow: rgba(194, 87, 11, 0.14);
  --accent: #c2570b;
  --accent-strong: #9a4a0a;
  --accent-soft: #fdf0e0;
  --surface-alt: #fdf8f1;
  --bg: #faf7f2;
  --shadow-brand: 0 8px 22px rgba(194, 87, 11, 0.2);
}

* {
  margin: 0;
  box-sizing: border-box;
}

/* —— 教师端去渐变：主按钮统一纯色 —— */
.teacher-theme .btn.primary,
.teacher-theme .cf-btn.primary,
.teacher-theme .c-btn.brand {
  background: var(--brand-strong);
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.22);
}
.teacher-theme .btn.primary:hover,
.teacher-theme .cf-btn.primary:hover,
.teacher-theme .c-btn.brand:hover {
  filter: brightness(1.08);
}

/* —— 全局按钮体系（纯色高级感）：未自定样式的视图直接受益 —— */
.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 9px 18px;
  border-radius: 10px;
  border: 1px solid transparent;
  font-size: 13.5px;
  font-weight: 600;
  line-height: 1.4;
  cursor: pointer;
  white-space: nowrap;
  transition: transform 0.15s, box-shadow 0.15s, background 0.15s, border-color 0.15s, color 0.15s;
}
.btn svg {
  width: 15px;
  height: 15px;
}
.btn.primary {
  background: var(--brand);
  color: #fff;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.22);
}
.btn.primary:hover:not(:disabled) {
  transform: translateY(-1px);
  filter: brightness(1.07);
  box-shadow: 0 6px 16px rgba(15, 23, 42, 0.25);
}
.btn.primary:active:not(:disabled) {
  transform: translateY(0);
  filter: brightness(0.97);
}
.btn.primary:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.btn.ghost {
  background: var(--surface);
  color: var(--ink-2);
  border-color: var(--line);
}
.btn.ghost:hover:not(:disabled) {
  border-color: var(--brand);
  color: var(--brand-strong);
}
.btn.warn {
  background: var(--warning-soft);
  color: #b45309;
  border-color: #fde3b8;
}
.btn.warn:hover:not(:disabled) {
  border-color: #f59e0b;
}
.btn.sm {
  padding: 6px 12px;
  font-size: 12.5px;
  border-radius: 8px;
}

body {
  font-family: var(--font);
  background: var(--bg);
  color: var(--ink);
  -webkit-font-smoothing: antialiased;
  font-size: 14px;
}

a {
  text-decoration: none;
  color: inherit;
}

/* —— 文案编辑框高度自适应（autogrow-edit）：v-autogrow 指令驱动 —— */
textarea.autogrow-ta {
  overflow-y: hidden;
  min-height: 64px;
  max-height: 340px;
  line-height: 1.65;
}

h1,
h2,
h3 {
  font-weight: 700;
  letter-spacing: -0.01em;
}

/* —— 全局页头：左侧实色 accent 条 + 紧凑副标题（各模块左上角标题统一美化，纯色无渐变） —— */
.page-head > div > h1 {
  font-size: 21px;
  font-weight: 800;
  letter-spacing: 0;
  padding-left: 12px;
  border-left: 4px solid var(--brand);
  line-height: 1.3;
}
.page-head .page-sub {
  margin-top: 6px;
  padding-left: 16px;
}
</style>