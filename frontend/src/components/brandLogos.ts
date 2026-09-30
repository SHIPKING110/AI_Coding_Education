/** 品牌 Logo 预设线条图标（登录页 / 侧边栏 / 个性化共用）。 */

export const LOGO_ICONS = [
  { key: 'icon:cap', label: '学位帽' },
  { key: 'icon:book', label: '书本' },
  { key: 'icon:spark', label: '星芒' },
  { key: 'icon:compass', label: '指南针' },
  { key: 'icon:pen', label: '笔' },
] as const

export const ICON_PATHS: Record<string, string> = {
  cap: 'M12 3.5 2.5 8 12 12.5 21.5 8 12 3.5z M6.5 10.2v4.1c0 1.6 2.5 2.9 5.5 2.9s5.5-1.3 5.5-2.9v-4.1 M21.5 8v5',
  book: 'M12 6.5C10 5 7 4.5 4 5.5v13c3-1 6-.5 8 1 2-1.5 5-2 8-1v-13c-3-1-6-.5-8 1z M12 6.5v13',
  spark:
    'M12 3.5l1.8 5.3 5.3 1.8-5.3 1.8L12 17.7l-1.8-5.3-5.3-1.8 5.3-1.8L12 3.5z M19 15.5l.9 2.6 2.6.9-2.6.9-.9 2.6-.9-2.6-2.6-.9 2.6-.9.9-2.6z',
  compass: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z M15.5 8.5l-2.2 4.8-4.8 2.2 2.2-4.8 4.8-2.2z',
  pen: 'M12 19.5l7-7-4-4-7 7-1.2 5.2 5.2-1.2z M14.5 7L17 9.5 M9 21h12',
}
