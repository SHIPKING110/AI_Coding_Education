import axios, { type AxiosError } from 'axios'

interface TokenClient {
  getAccess(): string | null
  getRefresh(): string | null
  setTokens(access: string, refresh: string): void
  clear(): void
  tokenType: string
}

export const tokenClient: TokenClient = {
  tokenType: 'bearer',
  getAccess: () => localStorage.getItem('access_token'),
  getRefresh: () => localStorage.getItem('refresh_token'),
  setTokens: (access, refresh) => {
    localStorage.setItem('access_token', access)
    localStorage.setItem('refresh_token', refresh)
  },
  clear: () => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
  },
}

const http = axios.create({
  baseURL: '/api',
  timeout: 15000,
})

http.interceptors.request.use((config) => {
  const token = tokenClient.getAccess()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

let refreshing: Promise<string | null> | null = null

async function refreshTokens(): Promise<string | null> {
  const refresh = tokenClient.getRefresh()
  if (!refresh) return null
  const { data } = await axios.post('/api/auth/refresh', null, {
    params: { refresh_token: refresh },
  })
  tokenClient.setTokens(data.access_token, data.refresh_token)
  return data.access_token
}

http.interceptors.response.use(
  (res) => res,
  async (error: AxiosError) => {
    const original = error.config as (typeof error.config & { _retry?: boolean }) | undefined
    if (error.response?.status === 401 && original && !original._retry) {
      original._retry = true
      refreshing = refreshing ?? refreshTokens()
      const token = await refreshing
      refreshing = null
      if (token) {
        original.headers.Authorization = `Bearer ${token}`
        return http(original)
      }
      tokenClient.clear()
    }
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail
    if (typeof detail === 'string' && detail) {
      return Promise.reject(new Error(detail))
    }
    return Promise.reject(error)
  },
)

export default http