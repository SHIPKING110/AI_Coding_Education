<script setup lang="ts">
import { useToastStore } from '@/stores/toast'

const toast = useToastStore()
</script>

<template>
  <div class="toast-host" aria-live="polite">
    <transition-group name="toast">
      <div
        v-for="t in toast.toasts"
        :key="t.id"
        class="toast"
        :class="t.kind"
        @click="toast.dismiss(t.id)"
      >
        <span class="toast-dot" />
        <span class="toast-text">{{ t.text }}</span>
        <button class="toast-x" @click.stop="toast.dismiss(t.id)">×</button>
      </div>
    </transition-group>
  </div>
</template>

<style scoped>
.toast-host {
  position: fixed;
  top: 16px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: min(560px, calc(100vw - 32px));
  pointer-events: none;
}
.toast {
  pointer-events: auto;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 12px;
  font-size: 13.5px;
  line-height: 1.6;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.22);
  cursor: pointer;
  background: #fff;
  border: 1px solid var(--line);
}
.toast.error {
  border-color: #f3c1c1;
  background: #fff5f5;
  color: #991b1b;
}
.toast.success {
  border-color: #bfe8cf;
  background: #f0fdf4;
  color: #166534;
}
.toast.info {
  border-color: #c7d2fe;
  background: #eef2ff;
  color: #3730a3;
}
.toast-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-top: 6px;
  flex-shrink: 0;
  background: currentColor;
}
.toast-text {
  flex: 1;
  word-break: break-word;
}
.toast-x {
  border: none;
  background: none;
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  color: inherit;
  opacity: 0.6;
  padding: 2px 4px;
}
.toast-enter-active,
.toast-leave-active {
  transition: all 0.25s ease;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
