import client from './client'

export interface DefenseSession {
  id: string; stage: string; turn_count: number; status: string; overall_score?: number
  assignment_title?: string; original_filename?: string; messages?: DefenseMessageItem[]; report?: DefenseReport
  created_at: string
}
export interface DefenseMessageItem { role: 'student' | 'assistant'; content: string; evaluation?: Record<string, unknown> }
export interface DefenseReport {
  overall_score?: number; score_status?: string; strengths?: string[]; weaknesses?: string[]; recommendations?: string[]
  architecture_score?: number; coding_score?: number; debugging_score?: number; communication_score?: number
}

export const defenseApi = {
  list: () => client.get<DefenseSession[]>('/defense/sessions'),
  create: (data: { submission_id?: string; code_review_id?: string; course_id?: string }) =>
    client.post<{ session_id: string; message: string }>('/defense/sessions', data),
  get: (id: string) => client.get<DefenseSession>(`/defense/sessions/${id}`),
  chat: (id: string, message: string) => client.post<{ stage: string; turn_count: number; status: string; message: string; report?: DefenseReport; fallback_used: boolean }>(`/defense/sessions/${id}/chat`, { message }),
  report: (id: string) => client.get<{ report: DefenseReport; overall_score?: number }>(`/defense/sessions/${id}/report`),
}
