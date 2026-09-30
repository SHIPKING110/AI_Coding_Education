<script setup lang="ts">
/**
 * 通用确认弹窗（替代 window.confirm，统一视觉风格）
 * 用法：
 *   <ConfirmDialog
 *     :visible="showDel"
 *     title="删除作业"
 *     message="确认删除该作业？删除后不可恢复。"
 *     confirm-text="删除"
 *     danger
 *     @confirm="doDelete"
 *     @cancel="showDel = false"
 *   />
 */
defineProps<{
  visible: boolean
  title: string
  message: string
  confirmText?: string
  cancelText?: string
  danger?: boolean
}>()

const emit = defineEmits<{
  (e: 'confirm'): void
  (e: 'cancel'): void
}>()
</script>

<template>
  <Teleport to="body">
    <Transition name="confirm-fade">
      <div v-if="visible" class="confirm-overlay" @click.self="emit('cancel')">
        <div class="confirm-modal" role="dialog" aria-modal="true">
          <div class="confirm-icon" :class="{ danger }">
            <svg v-if="danger" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
            </svg>
            <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M18 3a2 2 0 0 1 2 2v16l-4-2-4 2-4-2-4 2V5a2 2 0 0 1 2-2zM9 10h6" />
            </svg>
          </div>
          <div class="confirm-body">
            <h3>{{ title }}</h3>
            <p>{{ message }}</p>
            <div class="confirm-actions">
              <button class="c-btn" @click="emit('cancel')">{{ cancelText || '取消' }}</button>
              <button class="c-btn" :class="danger ? 'danger' : 'brand'" @click="emit('confirm')">
                {{ confirmText || '确认' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.confirm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.55);
  backdrop-filter: blur(3px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.confirm-modal {
  width: 360px;
  max-width: calc(100vw - 40px);
  background: var(--surface);
  border-radius: 16px;
  padding: 24px;
  box-shadow: var(--shadow-lg);
  display: flex;
  align-items: flex-start;
  gap: 14px;
}
.confirm-icon {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--danger-soft);
  color: var(--danger);
}
.confirm-icon svg {
  width: 20px;
  height: 20px;
}
.confirm-icon.danger {
  background: var(--danger-soft);
  color: var(--danger);
}
.confirm-body {
  flex: 1;
  min-width: 0;
}
.confirm-body h3 {
  font-size: 15.5px;
  font-weight: 700;
  color: var(--ink);
  margin-bottom: 6px;
}
.confirm-body p {
  font-size: 13px;
  color: var(--ink-3);
  line-height: 1.6;
  word-break: break-word;
  margin-bottom: 18px;
}
.confirm-actions {
  display: flex;
  justify-content: center;
  gap: 12px;
}
.c-btn {
  min-width: 84px;
  padding: 9px 18px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink-2);
  font-size: 13.5px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s;
}
.c-btn:hover {
  border-color: var(--brand);
  color: var(--brand-strong);
}
.c-btn.brand {
  background: linear-gradient(135deg, #6366f1, #06b6d4);
  color: #fff;
  border-color: transparent;
}
.c-btn.brand:hover {
  filter: brightness(1.05);
}
.c-btn.danger {
  background: var(--danger);
  color: #fff;
  border-color: transparent;
}
.c-btn.danger:hover {
  filter: brightness(1.08);
}
.confirm-fade-enter-active,
.confirm-fade-leave-active {
  transition: opacity 0.2s ease;
}
.confirm-fade-enter-active .confirm-modal,
.confirm-fade-leave-active .confirm-modal {
  transition: transform 0.2s ease;
}
.confirm-fade-enter-from,
.confirm-fade-leave-to {
  opacity: 0;
}
.confirm-fade-enter-from .confirm-modal,
.confirm-fade-leave-to .confirm-modal {
  transform: scale(0.96);
}
</style>