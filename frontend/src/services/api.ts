import axios from 'axios'
import type { TripFormData, TripPlanResponse } from '@/types'

const apiClient = axios.create({
baseURL: 'http://localhost:8000',
timeout: 120000,
headers: {
  'Content-Type': 'application/json'
}
})

/** 生成旅行计划 */
export async function generateTripPlan(
formData: TripFormData
): Promise<TripPlanResponse> {
const response = await apiClient.post<TripPlanResponse>(
  '/api/trip/plan',
  formData
)
return response.data
}

/** 健康检查 */
export async function healthCheck(): Promise<any> {
const response = await apiClient.get('/health')
return response.data
}