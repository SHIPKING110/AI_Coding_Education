import http from './http'

// ---------- 类型 ----------

export interface PageOut<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface ClientClassBrief {
  id: string
  name: string
  subject: string
  teacher_name: string | null
}

export interface ClientScheduleBrief {
  id: string
  class_name: string | null
  subject: string | null
  teacher_name: string | null
  start_time: string
  end_time: string
  status: string
}

export interface ClientStudentOut {
  id: string
  name: string
  phone: string | null
  lesson_balance: number
  low_balance: boolean
  status: string
  classes: ClientClassBrief[]
  next_schedule: ClientScheduleBrief | null
  has_student_account?: boolean
}

export interface ClientMeOut {
  id: string
  role: string
  name: string
  username: string
  campus: string | null
  students: ClientStudentOut[]
  unread_notifications: number
}

export interface ClientFeedbackOut {
  id: string
  schedule_id: string
  student_id: string
  title: string | null
  topic: string | null
  content: string | null
  performance: string | null
  evaluation: string | null
  homework: string | null
  media_urls: string[]
  status: string
  published_at: string | null
  schedule_time: string | null
  created_at: string
}

export interface ClientLessonRecordOut {
  id: string
  student_id: string
  record_type: string
  delta: number
  balance_after: number
  ref_id: string | null
  remark: string | null
  created_at: string
}

export interface ClientPackageOut {
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
  created_at: string
}

export interface OrderOut {
  id: string
  student_id: string
  student_name: string | null
  student_campus: string | null
  package_id: string | null
  package_name: string | null
  amount: string
  status: string // pending/paid/confirmed/cancelled/refunded
  paid_at: string | null
  confirmed_at: string | null
  expires_at: string | null
  refund_amount: string | null
  refund_note: string | null
  refunded_at: string | null
  created_at: string
}

export interface ClientQuestionOut {
  order_no: number
  type: string // single_choice/multiple_choice/judgement/code_fill/programming
  stem: string
  options: string[] | null
  difficulty: number
  language: string | null
  // 提交/批改后返回（作答中为 null，防作弊）
  reference_answer: unknown | null
  reference_analysis: string | null
}

export interface ClientSubmissionOut {
  id: string
  assignment_id: string
  student_id: string
  answers: Record<string, unknown> | null
  judge_results: Record<string, unknown> | null
  score: number | null
  total: number | null
  passed: boolean | null
  passing_score: number | null
  status: string // not_submitted/submitted/graded
  submitted_at: string | null
  created_at: string
  updated_at: string
}

export interface ClientAssignmentListItem {
  id: string
  title: string
  mode: 'classwork' | 'homework'
  description: string | null
  deadline: string | null
  teacher_name: string | null
  class_names: string[]
  question_count: number
  passing_score: number | null
  my_status: string
  my_score: number | null
  my_total: number | null
  my_passed: boolean | null
  submitted_at: string | null
  answered_count: number
  published_at: string | null
}

export interface ClientAssignmentDetail {
  id: string
  title: string
  mode: 'classwork' | 'homework'
  description: string | null
  deadline: string | null
  published_at: string | null
  teacher_name: string | null
  class_names: string[]
  questions: ClientQuestionOut[]
  submission: ClientSubmissionOut | null
}

export interface ClientSubmitOut {
  submission: ClientSubmissionOut
  empty_questions: number[]
  judged_count: number
  pending_manual: number
  message: string
}

export interface NotificationOut {
  id: string
  user_id: string
  type: string
  title: string
  content: string
  data: Record<string, unknown> | null
  read_at: string | null
  created_at: string
}

// ---------- API ----------

/** 客户端首页：账号 + 名下学员（含课时/班级/下一节课/未读通知） */
export async function getClientMe(): Promise<ClientMeOut> {
  const { data } = await http.get<ClientMeOut>('/client/me')
  return data
}

/** 学员详情（课时余额/班级/下一节课） */
export async function getClientStudent(studentId: string): Promise<ClientStudentOut> {
  const { data } = await http.get<ClientStudentOut>(`/client/students/${studentId}`)
  return data
}

/** 已发布课后反馈（分页） */
export async function listClientFeedbacks(
  studentId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<PageOut<ClientFeedbackOut>> {
  const { data } = await http.get<PageOut<ClientFeedbackOut>>(
    `/client/students/${studentId}/feedbacks`,
    { params },
  )
  return data
}

/** 课时流水 */
export async function listClientLessonRecords(
  studentId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<ClientLessonRecordOut[]> {
  const { data } = await http.get<ClientLessonRecordOut[]>(
    `/client/students/${studentId}/lesson-records`,
    { params },
  )
  return data
}

/** 学员课表 */
export async function listClientSchedules(
  studentId: string,
  params: { start?: string; end?: string; limit?: number } = {},
): Promise<ClientScheduleBrief[]> {
  const { data } = await http.get<ClientScheduleBrief[]>(
    `/client/students/${studentId}/schedules`,
    { params },
  )
  return data
}

/** 在售课时包（仅家长；支持科目/标签/售价筛选） */
export async function listClientPackages(params: {
  subject_id?: string
  tag?: string
  price_min?: string
  price_max?: string
} = {}): Promise<ClientPackageOut[]> {
  const { data } = await http.get<ClientPackageOut[]>('/client/packages', { params })
  return data
}

/** 订阅下单 */
export async function createClientOrder(payload: {
  student_id: string
  package_id: string
}): Promise<OrderOut> {
  const { data } = await http.post<OrderOut>('/client/orders', payload)
  return data
}

/** 我的订单列表 */
export async function listClientOrders(params: {
  student_id?: string
  status?: string
  limit?: number
  offset?: number
} = {}): Promise<PageOut<OrderOut>> {
  const { data } = await http.get<PageOut<OrderOut>>('/client/orders', { params })
  return data
}

/** 模拟支付：pending -> paid */
export async function payClientOrder(orderId: string): Promise<OrderOut> {
  const { data } = await http.post<OrderOut>(`/client/orders/${orderId}/pay`)
  return data
}

/** 取消订单 */
export async function cancelClientOrder(orderId: string): Promise<OrderOut> {
  const { data } = await http.post<OrderOut>(`/client/orders/${orderId}/cancel`)
  return data
}

/** 自助退款前置检查：是否可退 + 提示文案 */
export async function checkClientRefund(orderId: string): Promise<{
  ok: boolean
  code: string
  message: string
}> {
  const { data } = await http.get(`/client/orders/${orderId}/refund-check`)
  return data
}

/** 家长自助退款：reason_key=wrong_package/busy/other，other 需填 reason_text */
export async function refundClientOrder(
  orderId: string,
  payload: { reason_key: string; reason_text?: string },
): Promise<OrderOut> {
  const { data } = await http.post<OrderOut>(`/client/orders/${orderId}/refund`, payload)
  return data
}

/** 我的作业列表 */
export async function listClientAssignments(
  studentId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<PageOut<ClientAssignmentListItem>> {
  const { data } = await http.get<PageOut<ClientAssignmentListItem>>('/client/assignments', {
    params: { student_id: studentId, ...params },
  })
  return data
}

/** 作业详情（题目不含答案）+ 我的作答进度 */
export async function getClientAssignment(
  assignmentId: string,
  studentId: string,
): Promise<ClientAssignmentDetail> {
  const { data } = await http.get<ClientAssignmentDetail>(`/client/assignments/${assignmentId}`, {
    params: { student_id: studentId },
  })
  return data
}

/** 保存答案进度（自动/手动保存） */
export async function saveClientAnswers(
  assignmentId: string,
  studentId: string,
  answers: Record<string, unknown>,
): Promise<ClientSubmissionOut> {
  const { data } = await http.post<ClientSubmissionOut>(
    `/client/assignments/${assignmentId}/answers`,
    { answers },
    { params: { student_id: studentId } },
  )
  return data
}

/** 提交作业（空题校验 + 客观题自动判题） */
export async function submitClientAssignment(
  assignmentId: string,
  studentId: string,
  answers: Record<string, unknown>,
): Promise<ClientSubmitOut> {
  const { data } = await http.post<ClientSubmitOut>(
    `/client/assignments/${assignmentId}/submit`,
    { answers },
    { params: { student_id: studentId } },
  )
  return data
}

// ---------- 通知 ----------

/** 通知列表（分页，可只看未读） */
export async function listNotifications(params: {
  unread_only?: boolean
  limit?: number
  offset?: number
} = {}): Promise<PageOut<NotificationOut>> {
  const { data } = await http.get<PageOut<NotificationOut>>('/notifications', { params })
  return data
}

/** 未读通知数 */
export async function getUnreadCount(): Promise<number> {
  const { data } = await http.get<{ count: number }>('/notifications/unread-count')
  return data.count
}

/** 标记单条已读 */
export async function markNotificationRead(id: string): Promise<NotificationOut> {
  const { data } = await http.post<NotificationOut>(`/notifications/${id}/read`)
  return data
}

/** 全部已读 */
export async function markAllNotificationsRead(): Promise<{ marked_count: number }> {
  const { data } = await http.post<{ marked_count: number }>('/notifications/read-all')
  return data
}

// ---------- 教师批改 ----------

export interface SubmissionListItem {
  id: string
  student_id: string
  student_name: string | null
  campus: string | null
  class_names: string[]
  status: string
  score: number | null
  total: number | null
  submitted_at: string | null
  auto_score: number
  pending_manual: number
  passing_score: number | null
  passed: boolean | null
}

export interface SubmissionQuestionOut {
  id: string
  order_no: number
  type: string
  stem: string
  options: string[] | null
  answer: unknown
  analysis: string | null
  difficulty: number
  test_cases: unknown[] | null
  language: string | null
}

export interface SubmissionDetail {
  id: string
  assignment_id: string
  student_id: string
  student_name: string | null
  answers: Record<string, unknown> | null
  judge_results: Record<string, unknown> | null
  score: number | null
  total: number | null
  passed: boolean | null
  passing_score: number | null
  status: string
  submitted_at: string | null
  questions: SubmissionQuestionOut[]
}

export interface SubmissionStats {
  total_students: number
  submitted: number
  graded: number
  pending_review: number
  not_submitted: number
  avg_score: number | null
  passing_score: number | null
  below_pass: number
}

/** 提交统计（教师批改进度） */
export async function getSubmissionStats(assignmentId: string): Promise<SubmissionStats> {
  const { data } = await http.get<SubmissionStats>(`/assignments/${assignmentId}/submission-stats`)
  return data
}

/** 提交列表 */
export async function listSubmissions(
  assignmentId: string,
  params: { limit?: number; offset?: number } = {},
): Promise<SubmissionListItem[]> {
  const { data } = await http.get<SubmissionListItem[]>(`/assignments/${assignmentId}/submissions`, {
    params,
  })
  return data
}

/** 提交详情 */
export async function getSubmission(
  assignmentId: string,
  submissionId: string,
): Promise<SubmissionDetail> {
  const { data } = await http.get<SubmissionDetail>(
    `/assignments/${assignmentId}/submissions/${submissionId}`,
  )
  return data
}

/** 教师批改打分 */
export async function gradeSubmission(
  assignmentId: string,
  submissionId: string,
  payload: { scores: Record<string, number>; comment?: string | null },
): Promise<{ score: number; total: number; status: string; message: string }> {
  const { data } = await http.post<{ score: number; total: number; status: string; message: string }>(
    `/assignments/${assignmentId}/submissions/${submissionId}/grade`,
    payload,
  )
  return data
}

// ---------- 管理员订单 ----------

/** 订单管理列表（admin/staff，支持姓名/校区/课包/时间区间/状态筛选） */
export async function listAdminOrders(params: {
  student_id?: string
  status?: string
  keyword?: string
  campus?: string
  package_id?: string
  date_from?: string
  date_to?: string
  limit?: number
  offset?: number
} = {}): Promise<PageOut<OrderOut>> {
  const { data } = await http.get<PageOut<OrderOut>>('/orders', { params })
  return data
}

/** 管理员确认到账（课时入账 + 流水 + 通知家长） */
export async function confirmOrder(orderId: string): Promise<OrderOut> {
  const { data } = await http.post<OrderOut>(`/orders/${orderId}/confirm`)
  return data
}

/** 管理员取消订单 */
export async function cancelAdminOrder(orderId: string): Promise<OrderOut> {
  const { data } = await http.post<OrderOut>(`/orders/${orderId}/cancel`)
  return data
}

// ---------- 用户（学员绑定账号） ----------

/** 用户列表（学员编辑弹窗绑定家长/学员账号） */
export async function listUsersApi(params: {
  role?: string
  keyword?: string
  include_inactive?: boolean
  limit?: number
  offset?: number
} = {}): Promise<PageOut<{ id: string; name: string; username: string; role: string; phone: string | null }>> {
  const { data } = await http.get('/auth/users', { params })
  return data
}
