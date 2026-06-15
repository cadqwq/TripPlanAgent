import axios from 'axios'
import type { TripFormData, TripPlanResponse, ProgressResponse } from '@/types'

const apiClient = axios.create({
  baseURL: 'http://localhost:8000',
  timeout: 300000,
  headers: {
    'Content-Type': 'application/json'
  }
})

/** 生成旅行计划 */
export async function generateTripPlan(
  formData: TripFormData,
  traceId: string
): Promise<TripPlanResponse> {
  const response = await apiClient.post<TripPlanResponse>(
    '/api/trip/plan',
    formData,
    { params: { trace_id: traceId } }
  )
  return response.data
}

/** 查询规划进度 */
export async function getProgress(traceId: string): Promise<ProgressResponse> {
  const response = await apiClient.get<ProgressResponse>(
    '/api/trip/progress',
    { params: { trace_id: traceId }, timeout: 5000 }
  )
  return response.data
}

/** 健康检查 */
export async function healthCheck(): Promise<any> {
  const response = await apiClient.get('/health')
  return response.data
}
