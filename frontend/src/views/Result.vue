<template>
<div class="result-container">
  <div class="page-header">
    <a-button size="large" @click="goBack">← 返回首页</a-button>
  </div>

  <div v-if="tripPlan" class="content-wrapper">
    <!-- 行程概览 -->
    <a-card :title="tripPlan.city + ' 旅行计划'" :bordered="false">
      <p><strong>📅 日期：</strong>{{ tripPlan.start_date }} 至 {{ tripPlan.end_date }}</p>
      <p><strong>💡 建议：</strong>{{ tripPlan.overall_suggestions }}</p>
    </a-card>

    <!-- 预算 -->
    <a-card v-if="tripPlan.budget" title="💰 预算明细" :bordered="false" style="margin-top: 20px">
      <a-row :gutter="16">
        <a-col :span="6">
          <a-statistic title="景点门票" :value="tripPlan.budget.total_attractions" prefix="¥" />
        </a-col>
        <a-col :span="6">
          <a-statistic title="酒店住宿" :value="tripPlan.budget.total_hotels" prefix="¥" />
        </a-col>
        <a-col :span="6">
          <a-statistic title="餐饮费用" :value="tripPlan.budget.total_meals" prefix="¥" />
        </a-col>
        <a-col :span="6">
          <a-statistic title="交通费用" :value="tripPlan.budget.total_transportation" prefix="¥" />
        </a-col>
      </a-row>
      <a-divider />
      <div style="text-align: center; font-size: 24px; font-weight: bold; color: #667eea;">
        预估总费用：¥{{ tripPlan.budget.total }}
      </div>
    </a-card>

    <!-- 每日行程 -->
    <a-card title="📅 每日行程" :bordered="false" style="margin-top: 20px">
      <a-collapse v-model:activeKey="activeDays">
        <a-collapse-panel
          v-for="(day, index) in tripPlan.days"
          :key="index"
        >
          <template #header>
            <div>
              <strong>第{{ day.day_index + 1 }}天</strong>
              <span style="color: #999; margin-left: 12px;">{{ day.date }}</span>
            </div>
          </template>

          <p><strong>📝 行程：</strong>{{ day.description }}</p>
          <p><strong>🚗 交通：</strong>{{ day.transportation }}</p>

          <!-- 景点 -->
          <a-divider orientation="left">🎯 景点安排</a-divider>
          <a-row :gutter="16">
            <a-col :span="12" v-for="(attr, i) in day.attractions" :key="i">
              <a-card :title="attr.name" size="small" style="margin-bottom: 16px">
                <p><strong>地址：</strong>{{ attr.address }}</p>
                <p><strong>游览时长：</strong>{{ attr.visit_duration }}分钟</p>
                <p><strong>描述：</strong>{{ attr.description }}</p>
                <p v-if="attr.ticket_price"><strong>门票：</strong>¥{{ attr.ticket_price }}</p>
              </a-card>
            </a-col>
          </a-row>

          <!-- 酒店 -->
          <a-divider v-if="day.hotel" orientation="left">🏨 住宿推荐</a-divider>
          <a-card v-if="day.hotel" size="small">
            <p><strong>{{ day.hotel.name }}</strong></p>
            <p>{{ day.hotel.address }} | {{ day.hotel.type }} | ⭐{{ day.hotel.rating }}</p>
            <p>{{ day.hotel.price_range }} | {{ day.hotel.distance }}</p>
          </a-card>

          <!-- 餐饮 -->
          <a-divider orientation="left">🍽️ 餐饮安排</a-divider>
          <div v-for="meal in day.meals" :key="meal.type" style="margin-bottom: 8px;">
            <a-tag color="blue">{{ meal.type === 'breakfast' ? '早餐' : meal.type === 'lunch' ? '午餐' : '晚餐' }}</a-tag>
            <strong>{{ meal.name }}</strong>
            <span v-if="meal.description"> — {{ meal.description }}</span>
            <span v-if="meal.estimated_cost" style="color: #999;"> 约¥{{ meal.estimated_cost }}</span>
          </div>
        </a-collapse-panel>
      </a-collapse>
    </a-card>

    <!-- 天气 -->
    <a-card v-if="tripPlan.weather_info && tripPlan.weather_info.length > 0" title="🌤️ 天气预报" :bordered="false" style="margin-top: 20px">
      <a-row :gutter="16">
        <a-col :span="8" v-for="w in tripPlan.weather_info" :key="w.date">
          <a-card size="small" class="weather-card">
            <div style="text-align: center; font-weight: bold; margin-bottom: 8px;">{{ w.date }}</div>
            <p>☀️ 白天：{{ w.day_weather }} {{ w.day_temp }}°C</p>
            <p>🌙 夜间：{{ w.night_weather }} {{ w.night_temp }}°C</p>
            <p>💨 {{ w.wind_direction }} {{ w.wind_power }}</p>
          </a-card>
        </a-col>
      </a-row>
    </a-card>
  </div>

  <a-empty v-else description="没有找到旅行计划" />
</div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import type { TripPlan } from '@/types'

const router = useRouter()
const tripPlan = ref<TripPlan | null>(null)
const activeDays = ref<number[]>([0])

onMounted(() => {
  console.log('[Result] Component mounted')
  const data = sessionStorage.getItem('tripPlan')
  console.log('[Result] sessionStorage data exists:', !!data)
  console.log('[Result] sessionStorage data length:', data ? data.length : 0)

  if (data) {
    try {
      tripPlan.value = JSON.parse(data)
      console.log('[Result] Parsed tripPlan:', tripPlan.value)
      console.log('[Result] tripPlan.city:', tripPlan.value?.city)
      console.log('[Result] tripPlan.days count:', tripPlan.value?.days?.length)
    } catch (parseError) {
      console.error('[Result] JSON parse error:', parseError)
      console.error('[Result] Raw data (first 200 chars):', data.substring(0, 200))
    }
  } else {
    console.warn('[Result] No tripPlan found in sessionStorage!')
  }
})

const goBack = () => {
  router.push('/')
}
</script>

<style scoped>
.result-container {
  min-height: 100vh;
  background: #f5f7fa;
  padding: 40px 20px;
}

.page-header {
  max-width: 1200px;
  margin: 0 auto 24px;
}

.content-wrapper {
  max-width: 1200px;
  margin: 0 auto;
}

.weather-card {
  background: linear-gradient(135deg, #e0f7fa 0%, #b2ebf2 100%);
  border: none;
}
</style>
