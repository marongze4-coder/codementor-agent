import client from './client'

export interface ExamSubmitResponse {
  submission_id: string
  status: string
  message: string
}

export interface AvailableExam {
  id: string
  title: string
  description?: string
  due_date?: string
  question_count: number
  full_score: number
  objective_count: number
  subjective_count: number
  code_count: number
}

export interface PendingReviewItem {
  submission_id: string
  student_name: string
  exam_title: string
  submitted_at: string
  pre_review: {
    total_score: number
    full_score: number
    needs_review_count: number
  }
  weak_points: Array<{ tag: string; wrong_count: number; total_count?: number; question_nos?: number[]; suggestion?: string }>
}

export interface ReviewDetail {
  submission_id: string
  status: string
  student_id: string
  pre_review_summary: {
    total_score: number
    full_score: number
    by_question: Array<{
      question_id: string
      question_no: number
      question_type: string
      full_score: number
      score: number
      content?: string
      student_answer: string
      correct_answer?: string
      ai_feedback: string
      needs_review: boolean
      point_results?: Array<{
        point_score: number
        point_desc: string
        earned: boolean
        missing?: string
      }>
      test_cases_passed?: number
      test_cases_total?: number
      sandbox_skipped?: boolean
      quality_feedback?: string[]
      functional_score?: number
      quality_score?: number
      automatic_percent?: number
      sandbox_ready?: boolean
      sandbox_reason?: string
      test_results?: Array<{
        name: string
        passed: boolean
        duration_ms?: number
        stdout?: string
        stderr?: string
        error_type?: string
        is_hidden?: boolean
      }>
      dimension_scores?: Array<{ dimension: string; score: number; summary?: string }>
      issues?: Array<{ dimension: string; severity: string; title: string; line?: number; evidence?: string; suggestion?: string }>
      teacher_comment?: string
      final_score?: number
    }>
  }
  weak_points: Array<{ tag: string; wrong_count: number; total_count?: number; question_nos?: number[]; suggestion?: string }>
  weak_points_summary: string
}

export interface ConfirmRequest {
  action: 'approve' | 'modify'
  modifications: Array<{
    question_id: string
    new_score?: number
    comment?: string
  }>
}

export interface ConfirmResponse {
  submission_id: string
  status: string
  final_score: number
  full_score: number
  score_rate: number
  weak_points: Array<{ tag: string; wrong_count: number; total_count?: number; question_nos?: number[]; suggestion?: string }>
  weak_points_summary: string
}

export interface MySubmissionItem {
  submission_id: string
  exam_id: string
  exam_title: string
  status: string
  submitted_at: string
}

export const examApi = {
  available: () =>
    client.get<AvailableExam[]>('/mixed-assignments/available'),

  listMySubmissions: () =>
    client.get<{ items: MySubmissionItem[] }>('/mixed-assignments/my-submissions'),

  submit: (examId: string, file: File) => {
    const form = new FormData()
    form.append('exam_id', examId)
    form.append('file', file)
    return client.post<ExamSubmitResponse>('/mixed-assignments/submit', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  getPendingReviews: () =>
    client.get<{ items: PendingReviewItem[]; total: number }>('/mixed-assignments/pending-reviews'),

  getSubmissionReview: (submissionId: string) =>
    client.get<ReviewDetail>(`/mixed-assignments/my-submissions/${submissionId}`),

  getSubmissionReviewTeacher: (submissionId: string) =>
    client.get<ReviewDetail>(`/mixed-assignments/submissions/${submissionId}/review`),

  confirmReview: (submissionId: string, data: ConfirmRequest) =>
    client.post<ConfirmResponse>(`/mixed-assignments/submissions/${submissionId}/confirm`, data),
}
