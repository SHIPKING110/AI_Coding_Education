import http from './http'

export interface TeacherPermissionRow {
  teacher_id: string
  teacher_name: string
  username: string
  campus: string | null
  title: string | null
  permissions: Record<string, boolean>
}

export interface PermissionKey {
  key: string
  label: string
}

export async function listPermissionKeys(): Promise<PermissionKey[]> {
  const { data } = await http.get<{ keys: PermissionKey[] }>('/permissions/keys')
  return data.keys
}

export async function listTeacherPermissions(keyword = ''): Promise<TeacherPermissionRow[]> {
  const { data } = await http.get<{ items: TeacherPermissionRow[] }>('/permissions/teachers', {
    params: keyword ? { keyword } : {},
  })
  return data.items
}

export async function updateTeacherPermissions(
  teacherId: string,
  payload: Partial<Record<string, boolean>>,
): Promise<TeacherPermissionRow> {
  const { data } = await http.put<TeacherPermissionRow>(
    `/permissions/teachers/${teacherId}`,
    payload,
  )
  return data
}

export interface JobTitle {
  id: string
  name: string
  permissions: Record<string, boolean>
  base_salary?: string
}

export async function myPermissions(): Promise<Record<string, boolean>> {
  const { data } = await http.get<{ permissions: Record<string, boolean> }>('/permissions/mine')
  return data.permissions
}

export async function listJobTitles(): Promise<JobTitle[]> {
  const { data } = await http.get<{ items: JobTitle[] }>('/permissions/job-titles')
  return data.items
}

export async function createJobTitle(payload: { name: string; permissions: Record<string, boolean>; base_salary?: string }): Promise<JobTitle> {
  const { data } = await http.post<JobTitle>('/permissions/job-titles', payload)
  return data
}

export async function updateJobTitle(
  id: string,
  payload: { name?: string; permissions?: Record<string, boolean>; base_salary?: string },
): Promise<JobTitle> {
  const { data } = await http.put<JobTitle>(`/permissions/job-titles/${id}`, payload)
  return data
}

export async function deleteJobTitle(id: string): Promise<void> {
  await http.delete(`/permissions/job-titles/${id}`)
}

export async function applyTitleToTeacher(teacherId: string, titleName: string): Promise<TeacherPermissionRow> {
  const { data } = await http.post<TeacherPermissionRow>(
    `/permissions/teachers/${teacherId}/apply-title`,
    { title: titleName },
  )
  return data
}

export async function syncTitleToTeachers(id: string): Promise<{ title: string; synced: number }> {
  const { data } = await http.post<{ title: string; synced: number }>(
    `/permissions/job-titles/${id}/sync`,
  )
  return data
}
