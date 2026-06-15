<template>
<div class="home-container">
  <div class="page-header">
    <h1 class="page-title">✈️ 智能旅行助手</h1>
    <p class="page-subtitle">基于 LangGraph 多智能体的个性化旅行规划</p>
  </div>

  <a-card class="form-card" :bordered="false">
    <a-form :model="formData" layout="vertical" @finish="handleSubmit">

      <!-- 目的地和日期 -->
      <a-row :gutter="24">
        <a-col :span="8">
          <a-form-item name="city" label="目的地城市" :rules="[{ required: true }]">
            <a-input v-model:value="formData.city" placeholder="例如：北京" size="large" />
          </a-form-item>
        </a-col>
        <a-col :span="6">
          <a-form-item name="start_date" label="开始日期" :rules="[{ required: true }]">
            <a-date-picker v-model:value="formData.start_date" style="width: 100%" size="large" />
          </a-form-item>
        </a-col>
        <a-col :span="6">
          <a-form-item name="end_date" label="结束日期" :rules="[{ required: true }]">
            <a-date-picker v-model:value="formData.end_date" style="width: 100%" size="large" />
          </a-form-item>
        </a-col>
        <a-col :span="4">
          <div class="travel-days-field">
            <label class="travel-days-label">旅行天数</label>
            <div class="days-display">
              <span class="days-value">{{ formData.travel_days }}</span>
              <span class="days-unit">天</span>
            </div>
          </div>
        </a-col>
      </a-row>

      <!-- 偏好设置 -->
      <a-row :gutter="24">
        <a-col :span="8">
          <a-form-item name="transportation" label="交通方式">
            <a-select v-model:value="formData.transportation" size="large">
              <a-select-option value="公共交通">🚇 公共交通</a-select-option>
              <a-select-option value="自驾">🚗 自驾</a-select-option>
              <a-select-option value="步行">🚶 步行</a-select-option>
              <a-select-option value="混合">🔀 混合</a-select-option>
            </a-select>
          </a-form-item>
        </a-col>
        <a-col :span="8">
          <a-form-item name="accommodation" label="住宿偏好">
            <a-select v-model:value="formData.accommodation" size="large">
              <a-select-option value="经济型酒店">💰 经济型酒店</a-select-option>
              <a-select-option value="舒适型酒店">🏨 舒适型酒店</a-select-option>
              <a-select-option value="豪华酒店">⭐  豪华酒店</a-select-option>
              <a-select-option value="民宿">🏡 民宿</a-select-option>
            </a-select>
          </a-form-item>
        </a-col>
        <a-col :span="8">
          <a-form-item name="preferences" label="旅行偏好">
            <a-checkbox-group v-model:value="formData.preferences">
              <a-checkbox value="历史文化">🏛️ 历史文化</a-checkbox>
              <a-checkbox value="自然风光">🏞️ 自然风光</a-checkbox>
              <a-checkbox value="美食">🍜 美食</a-checkbox>
              <a-checkbox value="购物">🛍️ 购物</a-checkbox>
              <a-checkbox value="艺术">🎨 艺术</a-checkbox>
              <a-checkbox value="休闲">☕  休闲</a-checkbox>
            </a-checkbox-group>
          </a-form-item>
        </a-col>
      </a-row>

      <!-- 额外要求 -->
      <a-form-item name="free_text_input" label="额外要求">
        <a-textarea
          v-model:value="formData.free_text_input"
          placeholder="例如：想去看升旗、对海鲜过敏..."
          :rows="3"
          size="large"
        />
      </a-form-item>

      <!-- 提交按钮 -->
      <a-form-item>
        <a-button type="primary" html-type="submit" :loading="loading" size="large" block>
          <template v-if="!loading">🚀 开始规划我的旅行</template>
          <template v-else>正在生成中，请耐心等待...</template>
        </a-button>
      </a-form-item>

      <!-- 进度条（规划中显示） -->
      <div v-if="loading" class="progress-section">
        <a-steps :current="progressStep" size="small" direction="vertical">
          <a-step v-for="step in progressSteps" :key="step.key"
            :title="step.title"
            :description="currentStepKey === step.key ? progressMessage : ''"
            :status="step.status"
          />
        </a-steps>
      </div>
    </a-form>
  </a-card>
</div>
</template>

<script setup lang="ts">
import { ref, reactive, watch, computed, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { generateTripPlan, getProgress } from '@/services/api'
import type { TripFormData } from '@/types'
import type { Dayjs } from 'dayjs'

const router = useRouter()
const loading = ref(false)
const progressMessage = ref('')
const currentStepKey = ref('')
let progressTimer: ReturnType<typeof setInterval> | null = null

// 进度步骤映射
const STEP_MAP: Record<string, number> = {
  idle: -1,
  searching: 0,
  planning: 1,
  reviewing: 2,
  revising: 1,  // 回退到 planning
  enriching: 3,
  done: 4,
}

const progressSteps = computed(() => {
  const key = currentStepKey.value
  return [
    { key: 'searching', title: '搜索景点、天气、酒店', status: getStatus('searching') },
    { key: 'planning', title: '生成旅行计划', status: getStatus('planning') },
    { key: 'reviewing', title: '审查计划质量', status: getStatus('reviewing') },
    { key: 'enriching', title: '景点配图', status: getStatus('enriching') },
    { key: 'done', title: '完成', status: getStatus('done') },
  ]
})

function getStatus(stepKey: string): 'wait' | 'process' | 'finish' {
  const currentIdx = STEP_MAP[currentStepKey.value] ?? -1
  const stepIdx = STEP_MAP[stepKey] ?? -1
  if (stepIdx < currentIdx) return 'finish'
  if (stepIdx === currentIdx) return 'process'
  return 'wait'
}

const progressStep = computed(() => {
  const idx = STEP_MAP[currentStepKey.value]
  return idx >= 0 ? idx : 0
})

function startPolling(traceId: string) {
  progressTimer = setInterval(async () => {
    try {
      const p = await getProgress(traceId)
      currentStepKey.value = p.step
      progressMessage.value = p.message
      if (p.step === 'done') {
        stopPolling()
      }
    } catch {
      // 轮询失败忽略，下次再试
    }
  }, 800)
}

function stopPolling() {
  if (progressTimer) {
    clearInterval(progressTimer)
    progressTimer = null
  }
}

onBeforeUnmount(() => stopPolling())

const formData = reactive<TripFormData & { start_date: Dayjs | null; end_date: Dayjs | null }>({
  city: '',
  start_date: null,
  end_date: null,
  travel_days: 1,
  transportation: '公共交通',
  accommodation: '经济型酒店',
  preferences: [],
  free_text_input: ''
})

// 监听日期变化，自动计算旅行天数
watch([() => formData.start_date, () => formData.end_date], ([start, end]) => {
  if (start && end) {
    const days = end.diff(start, 'day') + 1
    if (days > 0 && days <= 30) {
      formData.travel_days = days
    } else if (days > 30) {
      message.warning('旅行天数不能超过30天')
      formData.end_date = null
    } else {
      message.warning('结束日期不能早于开始日期')
      formData.end_date = null
    }
  }
})

const handleSubmit = async () => {
  if (!formData.start_date || !formData.end_date) {
    message.error('请选择日期')
    return
  }

  loading.value = true

  try {
    const requestData: TripFormData = {
      city: formData.city,
      start_date: formData.start_date.format('YYYY-MM-DD'),
      end_date: formData.end_date.format('YYYY-MM-DD'),
      travel_days: formData.travel_days,
      transportation: formData.transportation,
      accommodation: formData.accommodation,
      preferences: formData.preferences,
      free_text_input: formData.free_text_input
    }

    // 生成 trace_id，发请求同时开始轮询进度
    const traceId = Math.random().toString(36).slice(2, 10)
    startPolling(traceId)

    console.log('[Home] Sending request, trace_id:', traceId)
    const response = await generateTripPlan(requestData, traceId)
    stopPolling()
    console.log('[Home] API response:', response)

    if (response.success && response.data) {
      const jsonStr = JSON.stringify(response.data)
      console.log('[Home] Storing to sessionStorage, size:', jsonStr.length, 'chars')
      try {
        sessionStorage.setItem('tripPlan', jsonStr)
        console.log('[Home] sessionStorage set OK')
        currentStepKey.value = 'done'
        progressMessage.value = '规划完成！正在跳转...'
        message.success('旅行计划生成成功！')
        setTimeout(() => {
          stopPolling()
          router.push('/result')
        }, 800)
      } catch (storageError: any) {
        console.error('[Home] sessionStorage error:', storageError)
        message.error('数据存储失败: ' + storageError.message)
      }
    } else {
      console.error('[Home] Response invalid:', response)
      message.error(response.message || '生成失败')
    }
  } catch (error: any) {
    console.error('[Home] Request error:', error)
    if (error.response) {
      console.error('[Home] Response status:', error.response.status)
      console.error('[Home] Response data:', error.response.data)
    }
    message.error(error.message || '生成失败，请稍后重试')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.home-container {
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 60px 20px;
}

.page-header {
  text-align: center;
  margin-bottom: 40px;
}

.page-title {
  font-size: 48px;
  font-weight: 800;
  color: #ffffff;
  margin-bottom: 12px;
  text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.3);
}

.page-subtitle {
  font-size: 18px;
  color: rgba(255, 255, 255, 0.9);
}

.form-card {
  max-width: 1000px;
  margin: 0 auto;
  border-radius: 16px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
}

.travel-days-field {
  display: flex;
  flex-direction: column;
}

.travel-days-label {
  font-size: 14px;
  color: rgba(0, 0, 0, 0.88);
  margin-bottom: 8px;
  font-weight: 400;
}

.days-display {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 40px;
  padding: 8px 16px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 12px;
  color: white;
}

.days-value {
  font-size: 24px;
  font-weight: 700;
  margin-right: 4px;
}

.days-unit {
  font-size: 14px;
}

.progress-section {
  margin-top: 24px;
  padding: 20px 24px;
  background: #fafafa;
  border-radius: 12px;
  border: 1px solid #f0f0f0;
}
</style>
