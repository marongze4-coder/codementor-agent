import client from './client'

export interface CodeIssue {
  severity: 'critical' | 'high' | 'medium' | 'low'
  dimension: string
  title: string
  line?: number
  evidence?: string
  suggestion: string
}

export interface DimensionScore {
  dimension: string
  score: number
  summary: string
  issues: CodeIssue[]
}

export interface CodeReview {
  id: string
  student_id?: string
  original_filename: string
  language?: string
  overall_score?: number
  status: 'processing' | 'done' | 'failed'
  code_structure?: Record<string, unknown>
  dimension_scores?: DimensionScore[]
  issues?: CodeIssue[]
  summary?: { overall_score?: number; grade?: string; strengths?: string[]; priorities?: string[]; next_steps?: string[] }
  error_msg?: string
  created_at: string
}

export const codeReviewApi = {
  submit(file: File) {
    const form = new FormData()
    form.append('file', file)
    return client.post<{ review_id: string; status: string; file_name: string }>('/code-review/submit', form)
  },
  get: (id: string) => client.get<CodeReview>(`/code-review/reviews/${id}`),
  list: () => client.get<CodeReview[]>('/code-review/reviews'),
  remove: (id: string) => client.delete(`/code-review/reviews/${id}`),
}
