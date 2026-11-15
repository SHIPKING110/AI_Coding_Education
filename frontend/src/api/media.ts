import http from './http'

/**
 * 换取站内素材的签名访问 URL。
 * /uploads/ 下文件必须携带短期签名（防匿名盗链），API 响应里的 URL 已自动带签名；
 * 仅当前端自行拼接路径（如 PPT 文件名 → 下载链接）时才需要调用本方法。
 */
export async function signedMediaUrl(path: string): Promise<string> {
  if (!path) return path
  if (/^https?:\/\//i.test(path)) return path
  const { data } = await http.post<{ url: string }>('/media/sign', { path })
  return data.url
}

/** 新窗口打开站内素材（先换取签名，再 window.open） */
export async function openMedia(path: string): Promise<void> {
  const url = await signedMediaUrl(path)
  if (url) window.open(url, '_blank', 'noopener')
}
