import { defineStore } from 'pinia'

import { loginApi, meApi, type LoginIn, type UserOut } from '@/api/auth'
import { myPermissions } from '@/api/permissions'
import { tokenClient } from '@/api/http'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as UserOut | null,
    loading: false,
    perms: null as Record<string, boolean> | null,
  }),
  getters: {
    isAuthenticated: (state) => !!tokenClient.getAccess() && !!state.user,
    isRole: (state) => (roles: UserOut['role'][]) => !!state.user && roles.includes(state.user.role),
  },
  actions: {
    async login(payload: LoginIn) {
      this.loading = true
      try {
        const tokens = await loginApi(payload)
        tokenClient.setTokens(tokens.access_token, tokens.refresh_token)
        await this.fetchMe()
      } finally {
        this.loading = false
      }
    },
    async fetchMe() {
      if (!tokenClient.getAccess()) return
      this.user = await meApi()
      this.perms = null
    },
    /** 教师操作权限（管理员/教务视为全开，由后端 effective 兜底） */
    async fetchPerms(): Promise<Record<string, boolean>> {
      if (this.perms) return this.perms
      if (this.user?.role === 'teacher') {
        try {
          this.perms = await myPermissions()
        } catch {
          this.perms = {}
        }
      } else {
        this.perms = {}
      }
      return this.perms
    },
    async logout() {
      tokenClient.clear()
      this.user = null
      this.perms = null
    },
  },
})