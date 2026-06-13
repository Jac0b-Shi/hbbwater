<template>
  <div class="sensor-detail" v-if="sensor">
    <el-page-header @back="$router.push('/sensors')" :title="sensor.sensor_id" />
    
    <el-row :gutter="20" class="detail-row">
      <!-- Sensor Info Card -->
      <el-col :xs="24" :md="8">
        <el-card shadow="hover">
          <template #header>
            <span>传感器信息</span>
          </template>
          <el-descriptions :column="1" border>
            <el-descriptions-item label="传感器ID">{{ sensor.sensor_id }}</el-descriptions-item>
            <el-descriptions-item label="类型">
              <el-tag :type="sensor.sensor_type === 'ultrasonic' ? 'primary' : 'warning'">
                {{ sensor.sensor_type === 'ultrasonic' ? '超声波' : '浸水' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="位置">{{ sensor.location }}</el-descriptions-item>
            <el-descriptions-item label="描述">{{ sensor.description || '-' }}</el-descriptions-item>
            <el-descriptions-item label="上报方式">{{ formatReportMethod(sensor) }}</el-descriptions-item>
            <el-descriptions-item v-if="sensor.webhook_group_name" label="所属组">{{ sensor.webhook_group_name }}</el-descriptions-item>
            <el-descriptions-item v-if="sensor.device_imei" label="设备IMEI">{{ sensor.device_imei }}</el-descriptions-item>
            <el-descriptions-item v-if="sensor.webhook_group_name && sensor.webhook_group_token" label="组Webhook">
              {{ `${window.location.origin}/api/sensors/group-webhook/${sensor.webhook_group_token}` }}
            </el-descriptions-item>
            <el-descriptions-item label="状态">
              <el-switch v-model="sensor.is_active" :disabled="!accountStore.canManageSensors" @change="updateActive" />
            </el-descriptions-item>
            <template v-if="sensor.sensor_type === 'ultrasonic'">
              <el-descriptions-item label="返回单位">{{ formatMeasurementUnit(sensor.measurement_unit) }}</el-descriptions-item>
              <el-descriptions-item label="阈值判定">{{ formatThresholdCondition(sensor.threshold_condition) }}</el-descriptions-item>
              <el-descriptions-item label="预警水位">{{ sensor.warning_level }} cm</el-descriptions-item>
              <el-descriptions-item label="危险水位">{{ sensor.danger_level }} cm</el-descriptions-item>
            </template>
            <el-descriptions-item label="正常间隔">{{ formatInterval(sensor.normal_interval) }}</el-descriptions-item>
            <el-descriptions-item label="预警间隔">{{ formatInterval(sensor.alert_interval) }}</el-descriptions-item>
          </el-descriptions>
        </el-card>

        <!-- Latest Reading Card -->
        <el-card shadow="hover" class="mt-4" v-if="latestReading">
          <template #header>
            <span>最新读数</span>
          </template>
          <div class="latest-reading">
            <div class="reading-time">{{ formatTime(latestReading.recorded_at) }}</div>
            <div class="reading-main" v-if="sensor.sensor_type === 'ultrasonic'">
              <div class="reading-value">{{ latestReading.water_level?.toFixed(1) }}<span class="unit">cm</span></div>
              <div class="reading-label">当前水位（已换算为 cm）</div>
            </div>
            <div class="reading-main" v-else>
              <div class="reading-value" :class="latestReading.water_detected ? 'danger' : 'success'">
                {{ latestReading.water_detected ? '浸水' : '正常' }}
              </div>
              <div class="reading-label">检测状态</div>
            </div>
            <div class="reading-extra">
              <div v-if="latestReading.external_powered">
                <el-icon><Lightning /></el-icon> 供电: 外接有线电源
              </div>
              <div v-else-if="latestReading.battery_level !== null && latestReading.battery_level !== undefined">
                <el-icon><Battery /></el-icon> 电量: {{ latestReading.battery_level.toFixed(1) }}%
              </div>
              <div v-if="latestReading.signal_strength !== null && latestReading.signal_strength !== undefined">
                <el-icon><Signal /></el-icon> 信号: {{ latestReading.signal_strength }} dBm
              </div>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- Chart Card -->
      <el-col :xs="24" :md="16">
        <el-card shadow="hover">
          <template #header>
            <div class="chart-header">
              <span>历史数据趋势</span>
              <el-radio-group v-model="timeRange" size="small">
                <el-radio-button label="24h">24小时</el-radio-button>
                <el-radio-button label="7d">7天</el-radio-button>
                <el-radio-button label="30d">30天</el-radio-button>
              </el-radio-group>
            </div>
          </template>
          <div class="chart-container">
            <v-chart class="chart" :option="chartOption" autoresize />
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Recent Readings Table -->
    <el-row class="mt-4">
      <el-col :span="24">
        <el-card shadow="hover">
          <template #header>
            <span>最近读数记录</span>
          </template>
          <el-table v-if="!isMobile" :data="readings" stripe>
            <el-table-column prop="recorded_at" label="时间" width="180">
              <template #default="{ row }">{{ formatTime(row.recorded_at) }}</template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="getStatusType(row.status)">{{ getStatusText(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column v-if="sensor.sensor_type === 'ultrasonic'" prop="water_level" label="水位(cm)" />
            <el-table-column v-else prop="water_detected" label="浸水">
              <template #default="{ row }">{{ row.water_detected ? '是' : '否' }}</template>
            </el-table-column>
            <el-table-column label="供电/电量" width="140">
              <template #default="{ row }">
                {{ row.external_powered ? '外接供电' : (row.battery_level?.toFixed(1) || '-') }}
              </template>
            </el-table-column>
            <el-table-column prop="signal_strength" label="信号(dBm)" width="120" />
          </el-table>
          <div v-else class="reading-card-list">
            <article v-for="reading in readings" :key="reading.id" class="reading-card">
              <div class="reading-card-head">
                <strong>{{ formatTime(reading.recorded_at) }}</strong>
                <el-tag :type="getStatusType(reading.status)">{{ getStatusText(reading.status) }}</el-tag>
              </div>
              <div class="reading-card-grid">
                <div>
                  <span>读数</span>
                  <strong v-if="sensor.sensor_type === 'ultrasonic'">{{ reading.water_level?.toFixed(1) ?? '-' }} cm</strong>
                  <strong v-else>{{ reading.water_detected ? '浸水' : '正常' }}</strong>
                </div>
                <div>
                  <span>供电</span>
                  <strong>{{ reading.external_powered ? '外接供电' : (reading.battery_level !== null && reading.battery_level !== undefined ? `${reading.battery_level.toFixed(1)}%` : '-') }}</strong>
                </div>
                <div>
                  <span>信号</span>
                  <strong>{{ reading.signal_strength !== null && reading.signal_strength !== undefined ? `${reading.signal_strength} dBm` : '-' }}</strong>
                </div>
              </div>
            </article>
            <el-empty v-if="readings.length === 0" description="暂无读数记录" />
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { useAccountStore } from '../stores/account'
import { useSensorStore } from '../stores/sensors'
import { formatUtc8DateTime } from '../utils/time'
import { useResponsive } from '../composables/useResponsive'

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent])

const route = useRoute()
const accountStore = useAccountStore()
const sensorStore = useSensorStore()
const { isMobile } = useResponsive()
const sensorId = computed(() => route.params.id)
let refreshTimer = null

const sensor = ref(null)
const readings = ref([])
const timeRange = ref('24h')
const timeSeries = ref({ data: [] })

const latestReading = computed(() => readings.value[0])

const chartOption = computed(() => {
  const isUltrasonic = sensor.value?.sensor_type === 'ultrasonic'
  const data = timeSeries.value.data || []
  
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: isMobile.value ? '10%' : '15%', containLabel: true },
    xAxis: {
      type: 'time',
      boundaryGap: false
    },
    yAxis: {
      type: 'value',
      name: isUltrasonic ? '水位(cm)' : '状态',
      min: isUltrasonic ? 0 : -0.1,
      max: isUltrasonic ? null : 1.1
    },
    dataZoom: isMobile.value ? [{ type: 'inside' }] : [{ type: 'inside' }, { type: 'slider' }],
    series: [{
      name: isUltrasonic ? '水位' : '浸水状态',
      type: 'line',
      smooth: true,
      symbol: 'none',
      areaStyle: {
        color: {
          type: 'linear',
          x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(64,158,255,0.3)' },
            { offset: 1, color: 'rgba(64,158,255,0.05)' }
          ]
        }
      },
      lineStyle: { color: '#409eff', width: 2 },
      data: data.map(d => [formatUtc8DateTime(d.timestamp), d.value])
    }]
  }
})

const formatInterval = (seconds) => {
  if (seconds >= 3600) return `${Math.floor(seconds / 3600)}小时`
  if (seconds >= 60) return `${Math.floor(seconds / 60)}分钟`
  return `${seconds}秒`
}

const formatTime = (time) => formatUtc8DateTime(time)

const getStatusType = (status) => {
  const map = { normal: 'success', warning: 'warning', danger: 'danger', alarm: 'danger', offline: 'info' }
  return map[status] || 'info'
}

const getStatusText = (status) => {
  const map = { normal: '正常', warning: '预警', danger: '危险', alarm: '告警', offline: '离线' }
  return map[status] || status
}

const formatReportMethod = (sensorData) => {
  if (sensorData?.webhook_group_name || sensorData?.webhook_group_token) {
    return '组 Webhook'
  }

  const method = sensorData?.report_method
  const map = {
    http_api: 'HTTP API',
    webhook: '独立 Webhook',
    udp_binary: 'UDP 二进制组 Webhook',
    mqtt: 'MQTT',
    coap: 'CoAP'
  }
  return map[method] || method || '-'
}

const formatThresholdCondition = (value) => (
  value === 'less_or_equal' ? '小于等于阈值触发' : '大于等于阈值触发'
)

const formatMeasurementUnit = (value) => (
  value === 'mm' ? '毫米 (mm)，页面自动换算为 cm' : '厘米 (cm)'
)

const updateActive = async (val) => {
  try {
    await sensorStore.updateSensor(sensorId.value, { is_active: val })
    ElMessage.success('状态已更新')
  } catch {
    sensor.value.is_active = !val
    ElMessage.error('更新失败')
  }
}

const fetchData = async () => {
  try {
    sensor.value = await sensorStore.fetchSensor(sensorId.value)
    const readingsRes = await sensorStore.fetchReadings(sensorId.value, { limit: 100 })
    readings.value = readingsRes.items || []
    
    const hours = timeRange.value === '24h' ? 24 : timeRange.value === '7d' ? 168 : 720
    const field = sensor.value.sensor_type === 'ultrasonic' ? 'water_level' : 'water_detected'
    timeSeries.value = await sensorStore.fetchTimeSeries(sensorId.value, field, hours)
  } catch (error) {
    ElMessage.error('获取数据失败')
  }
}

watch(timeRange, fetchData)
watch(sensorId, fetchData)

onMounted(async () => {
  await fetchData()
  refreshTimer = setInterval(() => {
    fetchData()
  }, 5000)
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
  }
})
</script>

<style scoped>
.sensor-detail {
  padding: 0;
}

.detail-row {
  margin-top: 20px;
}

.mt-4 {
  margin-top: 20px;
}

.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.chart-container {
  height: 350px;
}

.chart {
  width: 100%;
  height: 100%;
}

.latest-reading {
  text-align: center;
  padding: 20px 0;
}

.reading-time {
  color: #909399;
  font-size: 14px;
  margin-bottom: 16px;
}

.reading-main {
  margin-bottom: 20px;
}

.reading-value {
  font-size: 48px;
  font-weight: 600;
  color: #303133;
}

.reading-value .unit {
  font-size: 20px;
  color: #909399;
  margin-left: 8px;
}

.reading-value.success { color: #67c23a; }
.reading-value.danger { color: #f56c6c; }

.reading-label {
  color: #909399;
  margin-top: 8px;
}

.reading-extra {
  display: flex;
  justify-content: center;
  gap: 24px;
  color: #606266;
  font-size: 14px;
}

.reading-extra .el-icon {
  margin-right: 4px;
  vertical-align: middle;
}

.reading-card-list {
  display: grid;
  gap: 12px;
}

.reading-card {
  padding: 14px;
  border: 1px solid #ebeef5;
  border-radius: 10px;
  background: #fff;
}

.reading-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.reading-card-head strong {
  color: #303133;
  font-size: 14px;
}

.reading-card-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}

.reading-card-grid > div {
  min-width: 0;
  display: grid;
  gap: 5px;
}

.reading-card-grid span {
  color: #909399;
  font-size: 12px;
}

.reading-card-grid strong {
  overflow: hidden;
  color: #606266;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 767px) {
  .sensor-detail :deep(.el-page-header__left) {
    min-height: 44px;
  }

  .detail-row {
    margin-top: 12px;
  }

  .detail-row :deep(.el-col + .el-col) {
    margin-top: 12px;
  }

  .chart-header {
    align-items: stretch;
    flex-direction: column;
    gap: 12px;
  }

  .chart-header :deep(.el-radio-group) {
    width: 100%;
    display: flex;
  }

  .chart-header :deep(.el-radio-button) {
    flex: 1;
  }

  .chart-header :deep(.el-radio-button__inner) {
    width: 100%;
  }

  .chart-container {
    height: 280px;
  }

  .latest-reading {
    padding: 8px 0;
  }

  .reading-value {
    font-size: 38px;
  }

  .reading-extra {
    align-items: center;
    flex-direction: column;
    gap: 10px;
  }

  .mt-4 {
    margin-top: 12px;
  }

  :deep(.el-descriptions__label) {
    width: 104px;
  }
}
</style>
