import http from './http'

export type InvitationStatus = 'invited' | 'scheduled' | 'arrived' | 'signed' | 'lost'

export interface InvitationOut {
  id: string
  staff_id: string | null
  staff_name: string | null
  staff_campus: string | null
  parent_name: string
  parent_phone: string | null
  student_name: string
  subject_id: string | null
  subject_name: string
  status: InvitationStatus
  chat_images: string[]
  remark: string | null
  trial_student_id: string | null
  trial_schedule_id: string | null
  trial_class_id: string | null
  trial_teacher_id: string | null
  trial_teacher_name: string | null
  trial_class_name?: string | null
  created_at: string | null
}

export const INVITATION_STATUS_LABEL: Record<InvitationStatus, string> = {
  invited: '已邀约',
  scheduled: '已排体验课',
  arrived: '已到场',
  signed: '已报名',
  lost: '未报名结束',
}

export async function uploadChatImage(file: File): Promise<{ url: string; filename: string }> {
  const fd = new FormData()
  fd.append('file', file)
  const { data } = await http.post('/trials/upload', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function listInvitations(params: {
  staff_id?: string
  status?: string
  keyword?: string
  subject_id?: string
  trial_teacher_id?: string
  campus?: string
  date_from?: string
  date_to?: string
  limit?: number
  offset?: number
}): Promise<{ items: InvitationOut[]; total: number }> {
  const { data } = await http.get('/trials/invitations', { params })
  return data
}

export async function createInvitation(payload: {
  parent_name: string
  parent_phone?: string | null
  student_name: string
  subject_id?: string | null
  subject_name?: string | null
  chat_images?: string[]
  remark?: string | null
}): Promise<InvitationOut> {
  const { data } = await http.post('/trials/invitations', payload)
  return data
}

export async function updateInvitation(
  id: string,
  payload: {
    status?: string
    parent_name?: string
    parent_phone?: string | null
    student_name?: string
    chat_images?: string[]
    remark?: string | null
    subject_id?: string | null
    subject_name?: string | null
    trial_student_id?: string | null
    trial_schedule_id?: string | null
    trial_class_id?: string | null
    trial_teacher_id?: string | null
  },
): Promise<InvitationOut> {
  const { data } = await http.patch(`/trials/invitations/${id}`, payload)
  return data
}

export async function deleteInvitation(id: string): Promise<{ deleted: boolean; cleaned_student: boolean }> {
  const { data } = await http.delete(`/trials/invitations/${id}`)
  return data
}

export async function createTrialStudent(invitationId: string): Promise<Record<string, unknown>> {
  const { data } = await http.post(`/trials/invitations/${invitationId}/trial-student`)
  return data
}

export async function updateTrialStatus(
  studentId: string,
  payload: { trial_status: string; source?: string | null; referrer?: string | null },
): Promise<Record<string, unknown>> {
  const { data } = await http.patch(`/trials/students/${studentId}/trial-status`, payload)
  return data
}

export interface PayrollStatsOut {
  month: string
  user_id: string
  invite_count: number
  invite_ids: string[]
  trial_count: number
  arrived_ids: string[]
  trial_lesson_count: number
  trial_attendance_ids: string[]
  convert_count: number
  convert_ids: string[]
  renew_count: number
  renew_ids: string[]
  refer_count: number
  refer_ids: string[]
  lesson_commission: string
}

export async function getPayrollStats(params: {
  month?: string
  user_id?: string
}): Promise<PayrollStatsOut> {
  const { data } = await http.get('/trials/payroll-stats', { params })
  return data
}

export interface PayrollEvidenceItem {
  id: string
  student_name?: string
  parent?: string
  subject?: string
  status?: string
  teacher?: string | null
  class?: string
  source?: string
  referrer?: string
  lessons?: string
  amount?: string
  commission?: string
  overdraft?: boolean
  time?: string
}

export async function getPayrollEvidence(params: {
  kind: string
  month?: string
  user_id?: string
}): Promise<{ kind: string; month: string; count: number; items: PayrollEvidenceItem[] }> {
  const { data } = await http.get('/trials/payroll-evidence', { params })
  return data
}
