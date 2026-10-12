import http from './http'

// ---------- 类型 ----------

export interface PageOut<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface ClassBrief {
  id: string
  name: string
  subject: string
  teacher_name: string | null
}

export interface StudentOut {
  id: string
  name: string
  phone: string | null
  gender?: string
  campus: string | null
  parent_user_id: string | null
  student_user_id: string | null
  lesson_balance: number
  follow_up_status: string
  follow_up_at: string | null
  follow_up_note: string | null
  stop_note: string | null
  status: string
  low_balance: boolean
  arrears_lessons: number
  arrears_amount: string | null
  trial_status: string
  source: string
  referrer: string | null
  classes: ClassBrief[]
  created_at: string
}

export interface StudentCreate {
  name: string
  phone?: string | null
  gender?: string | null
  campus?: string | null
  parent_user_id?: string | null
  student_user_id?: string | null
  lesson_balance: number
  package_id?: string | null
  source?: string | null
  referrer?: string | null
  class_ids: string[]
}

export interface ClassOut {
  id: string
  name: string
  subject: string
  teacher_id: string | null
  teacher_name: string | null
  start_date: string | null
  status: string
  student_count: number
  created_at: string
}

export interface ClassStudentOut {
  id: string
  name: string
  campus: string | null
  phone: string | null
  lesson_balance: number
  status: string
  follow_up_status: string
  classes: ClassBrief[]
}

export interface ClassDetailOut extends ClassOut {
  students: ClassStudentOut[]
}

export interface ClassCreate {
  name: string
  subject: string
  teacher_id?: string | null
  start_date?: string | null
}

export interface LessonPackageOut {
  id: string
  name: string
  price: string
  total_lessons: number
  subject_id: string | null
  subject_name: string | null
  tag: string
  sale_start: string | null
  sale_end: string | null
  published_at: string | null
  paid_students: number
  cover_image: string | null
  status: string
  created_at: string
}

export interface LessonPackageCreate {
  name: string
  price: string
  total_lessons: number
  cover_image?: string | null
  subject_id?: string | null
  tag?: string
  sale_start?: string | null
  sale_end?: string | null
}

export interface LessonPackageUpdate {
  name?: string
  price?: string
  total_lessons?: number
  cover_image?: string | null
  status?: string
  subject_id?: string | null
  subject_id_set?: boolean
  tag?: string
  sale_start?: string | null
  sale_end?: string | null
}

export interface LessonRecordOut {
  id: string
  student_id: string
  record_type: string
  delta: number
  balance_after: number
  unit_price: number | null
  amount: number | null
  student_name?: string
  campus?: string | null
  ref_id: string | null
  remark: string | null
  operator_name: string | null
  created_at: string
}

export interface AllRecordsQuery {
  keyword?: string
  campus?: string
  record_type?: string
  date_from?: string
  date_to?: string
  limit?: number
  offset?: number
}

export interface AllRecordsOut {
  items: LessonRecordOut[]
  total: number
  summary: { amount_in: string; amount_out: string; amount_net: string }
}

// ---------- 学员 ----------

export async function listStudents(params: {
  keyword?: string
  class_id?: string
  class_unassigned?: boolean
  campus?: string
  campus_unassigned?: boolean
  teacher_id?: string
  teacher_unassigned?: boolean
  account?: '' | 'unbound_student' | 'unbound_parent'
  status?: string
  lesson_balance_min?: number
  lesson_balance_max?: number
  low_balance_only?: boolean
  follow_up?: string
  limit?: number
  offset?: number
} = {}): Promise<PageOut<StudentOut>> {
  const { data } = await http.get<PageOut<StudentOut>>('/students', { params })
  return data
}

export async function getStudent(id: string): Promise<StudentOut> {
  const { data } = await http.get<StudentOut>(`/students/${id}`)
  return data
}

export async function createStudent(payload: StudentCreate): Promise<StudentOut> {
  const { data } = await http.post<StudentOut>('/students', payload)
  return data
}

export async function updateStudent(id: string, payload: Partial<StudentCreate>): Promise<StudentOut> {
  const { data } = await http.patch<StudentOut>(`/students/${id}`, payload)
  return data
}

/** 调整学员班级：教师只能调整到本人所带班级；管理员/教务可任意。 */
export async function updateStudentClasses(id: string, classIds: string[]): Promise<StudentOut> {
  const { data } = await http.patch<StudentOut>(`/students/${id}/classes`, { class_ids: classIds })
  return data
}

export async function deleteStudent(id: string): Promise<void> {
  await http.delete(`/students/${id}`)
}

export async function refundStudentPreview(id: string): Promise<{
  items: Array<{
    order_id: string
    package_name: string
    purchased_lessons: number
    remaining_lessons: number
    unit_price: string
    refund_amount: string
  }>
  total_amount: string
  total_lessons: number
}> {
  const { data } = await http.get(`/students/${id}/refund-preview`)
  return data
}

export async function refundStudent(id: string, note: string): Promise<{
  student: StudentOut
  orders: string[]
  records: string[]
  detail: Array<{
    order_id: string
    package_name: string
    purchased_lessons: number
    remaining_lessons: number
    unit_price: string
    refund_amount: string
  }>
  total_amount: string
  total_lessons: number
}> {
  const { data } = await http.post(`/students/${id}/refund`, { note })
  return data
}

/** 学员停课 / 恢复在读（停课需备注）。 */
export async function updateStudentStatus(
  id: string,
  payload: { status: 'active' | 'stopped'; stop_note?: string | null },
): Promise<StudentOut> {
  const { data } = await http.patch<StudentOut>(`/students/${id}/status`, payload)
  return data
}

/** 催缴续费入账：选择课时包（package_id）或自定义（custom_lessons/custom_amount）。 */
export async function renewStudent(
  id: string,
  payload: {
    package_id?: string
    custom_lessons?: number
    custom_amount?: number
    note?: string | null
  },
): Promise<StudentOut> {
  const { data } = await http.post<StudentOut>(`/students/${id}/renew`, payload)
  return data
}

// ---------- 班级 ----------

export async function listClasses(
  params: {
    keyword?: string
    teacher_id?: string
    teacher_unassigned?: boolean
    campus?: string
    campus_unassigned?: boolean
    start_date_from?: string
    start_date_to?: string
    subject?: string
    limit?: number
    offset?: number
  } = {},
): Promise<PageOut<ClassOut>> {
  const { data } = await http.get<PageOut<ClassOut>>('/classes', { params })
  return data
}

export async function getClass(id: string): Promise<ClassDetailOut> {
  const { data } = await http.get<ClassDetailOut>(`/classes/${id}`)
  return data
}

export async function createClass(payload: ClassCreate): Promise<ClassOut> {
  const { data } = await http.post<ClassOut>('/classes', payload)
  return data
}

export async function updateClass(id: string, payload: Partial<ClassCreate>): Promise<ClassOut> {
  const { data } = await http.patch<ClassOut>(`/classes/${id}`, payload)
  return data
}

export async function deleteClass(id: string): Promise<void> {
  await http.delete(`/classes/${id}`)
}

// ---------- 课时包 ----------

export async function listPackages(
  includeInactive = false,
  params: {
    limit?: number
    offset?: number
    subject_id?: string
    tag?: string
    price_min?: string
    price_max?: string
  } = {},
): Promise<PageOut<LessonPackageOut>> {
  const { data } = await http.get<PageOut<LessonPackageOut>>('/lesson-packages', {
    params: { include_inactive: includeInactive, ...params },
  })
  return data
}

export async function createPackage(payload: LessonPackageCreate): Promise<LessonPackageOut> {
  const { data } = await http.post<LessonPackageOut>('/lesson-packages', payload)
  return data
}

export async function updatePackage(
  id: string,
  payload: LessonPackageUpdate,
): Promise<LessonPackageOut> {
  const { data } = await http.patch<LessonPackageOut>(`/lesson-packages/${id}`, payload)
  return data
}

export async function deletePackage(id: string): Promise<void> {
  await http.delete(`/lesson-packages/${id}`)
}

// ---------- 课时流水 ----------

export async function listLessonRecords(studentId: string): Promise<LessonRecordOut[]> {
  const { data } = await http.get<LessonRecordOut[]>(`/students/${studentId}/lesson-records`)
  return data
}

export async function adjustLessonBalance(
  studentId: string,
  delta: number,
  remark?: string | null,
  unit_price?: number,
): Promise<LessonRecordOut> {
  const { data } = await http.post<LessonRecordOut>(`/students/${studentId}/lesson-records`, {
    delta,
    remark,
    unit_price,
  })
  return data
}

export async function listAllLessonRecords(params: AllRecordsQuery = {}): Promise<AllRecordsOut> {
  const { data } = await http.get<AllRecordsOut>('/finance/records', { params })
  return data
}

export async function getLastPrice(
  studentId: string,
): Promise<{ price: string | null; package_name: string | null; order_id: string | null }> {
  const { data } = await http.get(`/students/${studentId}/last-price`)
  return data
}

// ---------- 催缴跟进 ----------

export async function updateStudentFollowUp(
  studentId: string,
  payload: { follow_up_status: string; note?: string | null },
): Promise<StudentOut> {
  const { data } = await http.patch<StudentOut>(`/students/${studentId}/follow-up`, payload)
  return data
}
