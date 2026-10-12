import http from './http'

export type UserRole = 'admin' | 'staff' | 'teacher' | 'parent' | 'student'

export interface PageOut<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface UserOut {
  id: string
  role: UserRole
  username: string
  name: string
  phone: string | null
  campus: string | null
  title: string | null
  gender?: string | null
  teacher_level_id: string | null
  teacher_level_name: string | null
  base_salary: string | null
  status: string
  created_at: string
}

export interface LoginIn {
  username: string
  password: string
}

export interface RegisterIn {
  role: UserRole
  username: string
  password: string
  name: string
  phone?: string | null
  gender?: string | null
  campus?: string | null
  title?: string | null
}

export interface TeacherCreateIn {
  username: string
  password: string
  name: string
  phone?: string | null
  gender?: string | null
  campus?: string | null
  title?: string | null
  teacher_level_id?: string | null
  base_salary?: string | null
}

export async function createTeacherApi(payload: TeacherCreateIn): Promise<UserOut> {
  const { data } = await http.post<UserOut>('/auth/teachers', payload)
  return data
}

export interface TeacherUpdateIn {
  name?: string
  phone?: string | null
  gender?: string | null
  campus?: string | null
  title?: string | null
  teacher_level_id?: string | null
  base_salary?: string | null
  password?: string
  status?: string
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
}

export async function loginApi(payload: LoginIn): Promise<TokenPair> {
  const { data } = await http.post<TokenPair>('/auth/login', payload)
  return data
}

export async function registerApi(payload: RegisterIn): Promise<UserOut> {
  const { data } = await http.post<UserOut>('/auth/register', payload)
  return data
}

export async function meApi(): Promise<UserOut> {
  const { data } = await http.get<UserOut>('/auth/me')
  return data
}

/** 个人信息完善（本人）：姓名/电话/校区。 */
export async function updateMeApi(
  payload: { name?: string; phone?: string | null; campus?: string | null },
): Promise<UserOut> {
  const { data } = await http.patch<UserOut>('/auth/me', payload)
  return data
}

/** 修改本人密码（校验原密码）。 */
export async function changeMyPasswordApi(
  oldPassword: string,
  newPassword: string,
): Promise<UserOut> {
  const { data } = await http.post<UserOut>('/auth/me/password', {
    old_password: oldPassword,
    new_password: newPassword,
  })
  return data
}

/** 管理员重置他人账号密码。 */
export async function resetUserPasswordApi(userId: string, newPassword: string): Promise<UserOut> {
  const { data } = await http.patch<UserOut>(`/auth/users/${userId}/password`, {
    new_password: newPassword,
  })
  return data
}

export async function listTeachersApi(params: {
  keyword?: string
  campus?: string
  include_inactive?: boolean
  limit?: number
  offset?: number
} = {}): Promise<PageOut<UserOut>> {
  const { data } = await http.get<PageOut<UserOut>>('/auth/teachers', { params })
  return data
}

export async function getTeacherApi(id: string): Promise<UserOut> {
  const { data } = await http.get<UserOut>(`/auth/teachers/${id}`)
  return data
}

export async function updateTeacherApi(id: string, payload: TeacherUpdateIn): Promise<UserOut> {
  const { data } = await http.patch<UserOut>(`/auth/teachers/${id}`, payload)
  return data
}

export async function deleteTeacherApi(id: string): Promise<void> {
  await http.delete(`/auth/teachers/${id}`)
}

export async function listCampusesApi(): Promise<string[]> {
  const { data } = await http.get<string[]>('/auth/campuses')
  return data
}
