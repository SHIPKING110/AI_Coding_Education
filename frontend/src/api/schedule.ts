import http from './http'

export interface ScheduleOut {
  id: string
  class_id: string | null
  class_name: string | null
  subject: string | null
  teacher_id: string
  teacher_name: string | null
  start_time: string
  end_time: string
  status: string
  is_trial: boolean
  created_at: string
}

export interface ConflictOut {
  id: string
  class_name: string | null
  teacher_name: string | null
  start_time: string
  end_time: string
  status: string
}

export interface ScheduleCreateIn {
  class_id: string | null
  teacher_id: string
  start_time: string
  end_time: string
  force?: boolean
  is_trial?: boolean
}

export interface ScheduleCreateResult {
  schedule: ScheduleOut | null
  conflicts: ConflictOut[]
  created: boolean
}

export interface AttendanceOut {
  id: string
  schedule_id: string
  student_id: string
  student_name: string | null
  lesson_balance: number | null
  low_balance: boolean
  status: string
  is_trial: boolean
  trial_status: string
  created_at: string
}

export interface AttendanceSubmitResult {
  updated: AttendanceOut[]
  lesson_records: { student_id: string; delta: number; balance_after: number; is_trial?: boolean }[]
  errors: { student_id: string; reason: string }[]
}

export async function listSchedules(params: {
  start?: string
  end?: string
  class_id?: string
  teacher_id?: string
  campus?: string
  status?: string
} = {}): Promise<ScheduleOut[]> {
  const { data } = await http.get<ScheduleOut[]>('/schedules', { params })
  return data
}

export async function getSchedule(id: string): Promise<ScheduleOut> {
  const { data } = await http.get<ScheduleOut>(`/schedules/${id}`)
  return data
}

export async function createSchedule(payload: ScheduleCreateIn): Promise<ScheduleCreateResult> {
  const { data } = await http.post<ScheduleCreateResult>('/schedules', payload)
  return data
}

// ---------- 循环排课 ----------

export interface RecurringSlotIn {
  weekday: number // 1=周一 ... 7=周日
  start_time: string // HH:MM
  duration_min: number
}

export interface RecurringCreateIn {
  class_id: string
  teacher_id: string
  start_date: string
  slots: RecurringSlotIn[]
  total_lessons: number
  force?: boolean
}

export interface RecurringCreateResult {
  created: boolean
  created_count: number
  conflicts: ConflictOut[]
  schedules: ScheduleOut[]
}

export async function createRecurringSchedules(
  payload: RecurringCreateIn,
): Promise<RecurringCreateResult> {
  const { data } = await http.post<RecurringCreateResult>('/schedules/recurring', payload)
  return data
}

export async function cancelSchedule(id: string): Promise<void> {
  await http.delete(`/schedules/${id}`)
}

export async function listAttendance(scheduleId: string): Promise<AttendanceOut[]> {
  const { data } = await http.get<AttendanceOut[]>(`/schedules/${scheduleId}/attendance`)
  return data
}

export async function submitAttendance(
  scheduleId: string,
  items: { student_id: string; status: 'attended' | 'leave' }[],
): Promise<AttendanceSubmitResult> {
  const { data } = await http.post<AttendanceSubmitResult>(
    `/schedules/${scheduleId}/attendance`,
    { items },
  )
  return data
}