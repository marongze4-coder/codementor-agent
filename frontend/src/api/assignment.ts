import client from './client'

export interface Course { id: string; name: string; code: string; description?: string; primary_language: string }
export interface Assignment {
  id: string; course_id: string; course_name: string; title: string; description: string
  language: string; entry_file: string; rubric: Record<string, number>; max_score: number; due_date?: string
}
export interface Submission {
  id: string; assignment_id: string; student_id: string; original_filename: string; status: string
  automatic_score?: number; teacher_score?: number; final_score?: number; weak_points?: string[]
  assignment_title: string; course_name: string; functional_score?: number; quality_score?: number
  dimension_scores?: Record<string, number>; issues?: Array<Record<string, unknown>>; feedback?: string
  needs_review?: boolean; teacher_comment?: string; error_msg?: string
  test_results: Array<{ name?: string; is_hidden?: boolean; passed: boolean; duration_ms?: number; stdout?: string; stderr?: string; error_type?: string }>
}

export const assignmentApi = {
  courses: () => client.get<Course[]>('/assignments/courses'),
  createCourse: (data: { name: string; code: string; description: string; primary_language: string }) => client.post<{ course_id: string }>('/assignments/courses', data),
  list: (courseId?: string) => client.get<Assignment[]>('/assignments', { params: courseId ? { course_id: courseId } : {} }),
  createAssignment: (data: { course_id: string; title: string; description: string; language: string; entry_file: string; rubric: Record<string, number>; max_score: number }) => client.post<{ assignment_id: string }>('/assignments', data),
  createTestCase: (assignmentId: string, data: { name: string; input_data: string; expected_output: string; timeout_seconds: number; weight: number; is_hidden: boolean }) => client.post<{ test_case_id: string }>(`/assignments/${assignmentId}/test-cases`, data),
  submit(assignmentId: string, file: File) {
    const form = new FormData()
    form.append('file', file)
    return client.post<{ submission_id: string; status: string }>(`/assignments/${assignmentId}/submit`, form)
  },
  submissions: () => client.get<Array<{ id: string; assignment_title: string; course_name: string; status: string; automatic_score?: number; final_score?: number; submitted_at: string }>>('/assignments/submissions'),
  submission: (id: string) => client.get<Submission>(`/assignments/submissions/${id}`),
  pending: () => client.get<Array<{ id: string; assignment_title: string; student_name: string; automatic_score?: number; submitted_at: string }>>('/assignments/pending-reviews'),
  confirm: (id: string, score: number, comment: string) => client.post(`/assignments/submissions/${id}/confirm`, { score, comment }),
}
