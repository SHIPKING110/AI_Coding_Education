import http from './http'

export interface SystemSettings {
  login_theme: string
  desktop_bg: string
  ui_theme: string
  login_title: string
  login_subtitle: string
  login_logo: string
  login_accent: string
  login_hero: string
  sidebar_sub: string
  sidebar_theme: string
  nav_order: string[]
}

export async function getSystemSettings(): Promise<SystemSettings> {
  const { data } = await http.get<SystemSettings>('/system-settings')
  return data
}

export async function updateSystemSettings(
  payload: Partial<SystemSettings>,
): Promise<SystemSettings> {
  const { data } = await http.put<SystemSettings>('/system-settings', payload)
  return data
}

export async function uploadSettingImage(file: File): Promise<string> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post<{ url: string }>('/system-settings/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data.url
}

/** 兼容旧名 */
export const uploadDesktopBg = uploadSettingImage
