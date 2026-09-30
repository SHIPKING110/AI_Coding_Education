import { defineStore } from 'pinia'

import { getClientMe, getUnreadCount, type ClientMeOut, type ClientStudentOut } from '@/api/client'

/** 客户端（家长/学员端）共享状态：当前账号/名下学员/选中的孩子/未读通知数。 */
export const useClientStore = defineStore('client', {
  state: () => ({
    me: null as ClientMeOut | null,
    loading: false,
    activeStudentId: null as string | null,
    unread: 0,
    // 私有字段：在途的 loadMe 请求（并发去重，不参与响应式）
    _mePromise: null as Promise<void> | null,
  }),
  getters: {
    students: (state) => state.me?.students ?? [],
    activeStudent: (state): ClientStudentOut | null =>
      state.me?.students.find((s) => s.id === state.activeStudentId) ??
      state.me?.students[0] ??
      null,
  },
  actions: {
    async loadMe(force = false) {
      // 并发去重：多个页面/布局同时请求时共用同一个在途请求，避免各自提前 return
      // 导致 me 尚未就绪就结束加载（成长页评估一直转圈的直接原因之一）
      if (this._mePromise) return this._mePromise
      if (!force && this.me) return
      this.loading = true
      this._mePromise = (async () => {
        try {
          this.me = await getClientMe()
          this.unread = this.me.unread_notifications
          const saved = localStorage.getItem('client_active_student')
          if (saved && this.students.some((s) => s.id === saved)) {
            this.activeStudentId = saved
          } else {
            this.activeStudentId = this.students[0]?.id ?? null
          }
        } finally {
          this.loading = false
          this._mePromise = null
        }
      })()
      return this._mePromise
    },
    /** 只刷新未读徽标（标记已读后调用，不影响其他数据） */
    async refreshUnread() {
      try {
        this.unread = await getUnreadCount()
      } catch {
        // 静默
      }
    },
    /** 刷新名下学员的课时等信息（切换学员/订单到账后调用） */
    async refreshStudents() {
      try {
        const me = await getClientMe()
        this.me = me
        this.unread = me.unread_notifications
        // 当前选中的学员可能已不在列表（被解绑），回退到第一个
        if (this.activeStudentId && !me.students.some((s) => s.id === this.activeStudentId)) {
          this.activeStudentId = me.students[0]?.id ?? null
        }
      } catch {
        // 静默
      }
    },
    setActiveStudent(id: string | null) {
      this.activeStudentId = id
      if (id) localStorage.setItem('client_active_student', id)
      else localStorage.removeItem('client_active_student')
    },
    clear() {
      this.me = null
      this.activeStudentId = null
      this.unread = 0
    },
  },
})
