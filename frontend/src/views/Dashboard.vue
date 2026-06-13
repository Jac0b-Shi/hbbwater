<template>
  <div class="dashboard">
    <!-- Stats Cards -->
    <el-row :gutter="20" class="stats-row">
      <el-col :xs="12" :sm="12" :md="6">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-icon total">
            <el-icon><Cpu /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ dashboardStore.stats.total_sensors }}</div>
            <div class="stat-label">传感器总数</div>
          </div>
        </el-card>
      </el-col>
      
      <el-col :xs="12" :sm="12" :md="6">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-icon online">
            <el-icon><CircleCheck /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ dashboardStore.stats.online_sensors }}</div>
            <div class="stat-label">在线传感器</div>
            <div class="stat-rate">{{ dashboardStore.onlineRate }}%</div>
          </div>
        </el-card>
      </el-col>
      
      <el-col :xs="12" :sm="12" :md="6">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-icon alert">
            <el-icon><Warning /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ dashboardStore.stats.active_alerts }}</div>
            <div class="stat-label">活动告警</div>
          </div>
        </el-card>
      </el-col>
      
      <el-col :xs="12" :sm="12" :md="6">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-icon data">
            <el-icon><DataLine /></el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value">{{ dashboardStore.stats.today_readings }}</div>
            <div class="stat-label">今日数据</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" class="rainfall-row">
      <el-col :span="24">
        <el-card class="rainfall-card" shadow="hover" v-loading="weatherStore.loading">
          <template #header>
            <div class="card-header">
              <div class="rainfall-title">
                <el-icon><Cloudy /></el-icon>
                <span>小时雨量</span>
              </div>
              <div class="rainfall-updated">
                {{ weatherStore.rainfallSummary ? `更新 ${formatTime(weatherStore.rainfallSummary.updated_at)}` : '等待数据' }}
              </div>
            </div>
          </template>

          <div v-if="rainfallStations.length" class="rainfall-grid">
            <div
              v-for="station in rainfallStations"
              :key="station.station_id"
              class="rainfall-station"
              :class="getRainfallStationClasses(station)"
            >
              <div class="rainfall-station-head">
                <div>
                  <div class="rainfall-station-name">{{ station.station_name }}</div>
                  <div class="rainfall-station-id">{{ station.station_id }}</div>
                </div>
                <el-tag size="small" :type="getRainfallRoleTagType(station)">
                  {{ getRainfallRoleText(station) }}
                </el-tag>
              </div>
              <div class="rainfall-metrics">
                <div class="rainfall-metric actual">
                  <span class="metric-label">当前实况</span>
                  <span class="metric-value">{{ formatRainfall(station.current_actual_mm) }}</span>
                  <span class="metric-time">{{ station.current_actual_time ? formatTime(station.current_actual_time) : '暂无时次' }}</span>
                </div>
                <div class="rainfall-metric">
                  <span class="metric-label">未来1h</span>
                  <span class="metric-value">{{ formatRainfall(station.forecast_totals?.next_1h) }}</span>
                </div>
                <div class="rainfall-metric">
                  <span class="metric-label">未来3h</span>
                  <span class="metric-value">{{ formatRainfall(station.forecast_totals?.next_3h) }}</span>
                </div>
                <div class="rainfall-metric">
                  <span class="metric-label">未来24h</span>
                  <span class="metric-value">{{ formatRainfall(station.forecast_totals?.next_24h) }}</span>
                </div>
              </div>
              <div class="rainfall-station-foot">
                <span>{{ getRainfallStatusText(station) }}</span>
                <span v-if="station.latest_forecast_issued_at">
                  预报批次 {{ formatTime(station.latest_forecast_issued_at) }}
                </span>
              </div>
            </div>
          </div>
          <el-empty v-else description="暂无雨量数据" />
        </el-card>
      </el-col>
    </el-row>

    <!-- Main Content -->
    <el-row :gutter="20" class="main-row">
      <!-- Sensor Status Table -->
      <el-col :xs="24" :lg="16">
        <el-card class="status-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <span>传感器状态</span>
              <el-button type="primary" size="small" @click="refreshStatus">
                <el-icon><Refresh /></el-icon>刷新
              </el-button>
            </div>
          </template>
          <el-table v-if="!isMobile" :data="dashboardStore.sensorStatus" stripe style="width: 100%">
            <el-table-column prop="sensor_id" label="传感器ID" width="150" />
            <el-table-column prop="location" label="位置" />
            <el-table-column prop="sensor_type" label="类型" width="120">
              <template #default="{ row }">
                <el-tag :type="row.sensor_type === 'ultrasonic' ? 'primary' : 'warning'">
                  {{ row.sensor_type === 'ultrasonic' ? '超声波' : '浸水' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="getStatusType(row.status)">
                  {{ getStatusText(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="is_online" label="在线" width="80">
              <template #default="{ row }">
                <el-icon :size="20" :color="row.is_online ? '#67c23a' : '#f56c6c'">
                  <CircleCheck v-if="row.is_online" />
                  <CircleClose v-else />
                </el-icon>
              </template>
            </el-table-column>
            <el-table-column prop="water_level" label="水位(cm)" width="120">
              <template #default="{ row }">
                {{ row.water_level !== null ? row.water_level.toFixed(1) : '-' }}
              </template>
            </el-table-column>
            <el-table-column label="供电/电量" width="120">
              <template #default="{ row }">
                <span v-if="row.external_powered">外接供电</span>
                <el-progress 
                  v-else-if="row.battery_level !== null"
                  :percentage="Math.round(row.battery_level)"
                  :color="getBatteryColor"
                  :show-text="false"
                  style="width: 50px"
                />
                <span v-else>-</span>
              </template>
            </el-table-column>
          </el-table>
          <div v-else class="mobile-record-list">
            <article
              v-for="sensor in dashboardStore.sensorStatus"
              :key="sensor.sensor_id"
              class="sensor-status-card"
            >
              <div class="mobile-record-head">
                <div>
                  <strong>{{ sensor.sensor_id }}</strong>
                  <div class="mobile-record-subtitle">{{ sensor.location || '未设置位置' }}</div>
                </div>
                <el-tag :type="getStatusType(sensor.status)">{{ getStatusText(sensor.status) }}</el-tag>
              </div>
              <div class="sensor-status-grid">
                <div>
                  <span>类型</span>
                  <strong>{{ sensor.sensor_type === 'ultrasonic' ? '超声波' : '浸水' }}</strong>
                </div>
                <div>
                  <span>连接</span>
                  <strong :class="sensor.is_online ? 'is-online' : 'is-offline'">
                    {{ sensor.is_online ? '在线' : '离线' }}
                  </strong>
                </div>
                <div>
                  <span>当前读数</span>
                  <strong>{{ sensor.water_level !== null ? `${sensor.water_level.toFixed(1)} cm` : (sensor.water_detected ? '浸水' : '-') }}</strong>
                </div>
                <div>
                  <span>供电</span>
                  <strong>{{ sensor.external_powered ? '外接供电' : (sensor.battery_level !== null ? `${Math.round(sensor.battery_level)}%` : '-') }}</strong>
                </div>
              </div>
            </article>
            <el-empty v-if="dashboardStore.sensorStatus.length === 0" description="暂无传感器状态" />
          </div>
        </el-card>
      </el-col>

      <!-- Recent Alerts -->
      <el-col :xs="24" :lg="8">
        <el-card class="alerts-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <span>最新告警</span>
              <el-button type="primary" link @click="$router.push('/alerts')">
                查看全部
              </el-button>
            </div>
          </template>
          <div class="alert-list">
            <div 
              v-for="alert in dashboardStore.recentAlerts" 
              :key="alert.id"
              class="alert-item"
              :class="alert.severity"
            >
              <div class="alert-header">
                <el-tag size="small" :type="getSeverityType(alert.severity)">
                  {{ getSeverityText(alert.severity) }}
                </el-tag>
                <span class="alert-time">{{ formatTime(alert.created_at) }}</span>
              </div>
              <div class="alert-content">{{ alert.message }}</div>
              <div class="alert-location">
                <el-icon><Location /></el-icon>
                {{ alert.location }}
              </div>
            </div>
            <el-empty v-if="dashboardStore.recentAlerts.length === 0" description="暂无告警" />
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- Recent Readings -->
    <el-row :gutter="20" class="bottom-row">
      <el-col :span="24">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header">
              <span>最近数据</span>
              <el-radio-group v-model="dataFilter" size="small">
                <el-radio-button label="all">全部</el-radio-button>
                <el-radio-button label="ultrasonic">超声波</el-radio-button>
                <el-radio-button label="immersion">浸水</el-radio-button>
              </el-radio-group>
            </div>
          </template>
          <el-timeline>
            <el-timeline-item
              v-for="reading in filteredReadings.slice(0, 10)"
              :key="reading.id"
              :type="getReadingType(reading.status)"
              :timestamp="formatTime(reading.recorded_at)"
            >
              <div class="reading-item">
                <span class="reading-sensor">{{ reading.sensor_id }}</span>
                <span class="reading-location">{{ reading.location }}</span>
                <span v-if="reading.water_level !== null" class="reading-value">
                  水位: {{ reading.water_level.toFixed(1) }}cm
                </span>
                <span v-if="reading.water_detected !== null" class="reading-value">
                  状态: {{ reading.water_detected ? '浸水' : '正常' }}
                </span>
                <el-tag size="small" :type="getStatusType(reading.status)">
                  {{ getStatusText(reading.status) }}
                </el-tag>
              </div>
            </el-timeline-item>
          </el-timeline>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useDashboardStore } from '../stores/dashboard'
import { useWeatherStore } from '../stores/weather'
import { formatUtc8DateTime, SHORT_DATE_TIME_FORMAT } from '../utils/time'
import { useResponsive } from '../composables/useResponsive'

const dashboardStore = useDashboardStore()
const weatherStore = useWeatherStore()
const { isMobile } = useResponsive()
const dataFilter = ref('all')
let refreshInterval = null
let weatherRefreshInterval = null

const filteredReadings = computed(() => {
  if (dataFilter.value === 'all') {
    return dashboardStore.recentReadings
  }
  return dashboardStore.recentReadings.filter(r => r.sensor_type === dataFilter.value)
})

const rainfallStations = computed(() => weatherStore.rainfallSummary?.stations || [])

const getStatusType = (status) => {
  const map = {
    normal: 'success',
    warning: 'warning',
    danger: 'danger',
    alarm: 'danger',
    offline: 'info'
  }
  return map[status] || 'info'
}

const getStatusText = (status) => {
  const map = {
    normal: '正常',
    warning: '预警',
    danger: '危险',
    alarm: '告警',
    offline: '离线'
  }
  return map[status] || status
}

const getSeverityType = (severity) => {
  const map = {
    low: 'info',
    medium: 'warning',
    high: 'danger',
    critical: 'danger'
  }
  return map[severity] || 'info'
}

const getSeverityText = (severity) => {
  const map = {
    low: '低',
    medium: '中',
    high: '高',
    critical: '紧急'
  }
  return map[severity] || severity
}

const getReadingType = (status) => {
  if (status === 'danger' || status === 'alarm') return 'danger'
  if (status === 'warning') return 'warning'
  return 'primary'
}

const getBatteryColor = (percentage) => {
  if (percentage < 20) return '#f56c6c'
  if (percentage < 40) return '#e6a23c'
  return '#67c23a'
}

const formatTime = (time) => {
  return formatUtc8DateTime(time, SHORT_DATE_TIME_FORMAT)
}

const formatRainfall = (value) => {
  if (value === null || value === undefined) return '-- mm'
  return `${Number(value).toFixed(1)} mm`
}

const getRainfallRoleText = (station) => {
  if (station.station_id === weatherStore.rainfallSummary?.selected_station_id) {
    return station.role === 'primary' ? '主站参考' : '备份参考'
  }
  return station.role === 'primary' ? '主站' : '备份'
}

const getRainfallRoleTagType = (station) => {
  if (station.station_id === weatherStore.rainfallSummary?.selected_station_id) return 'success'
  return station.role === 'primary' ? 'primary' : 'info'
}

const getRainfallStatusText = (station) => {
  if (station.last_error) return station.last_error
  if (station.is_stale) return '数据已过期'
  if (station.last_success_at) return `采集 ${formatTime(station.last_success_at)}`
  return '等待首次采集'
}

const getRainfallStationClasses = (station) => ({
  'is-selected': station.station_id === weatherStore.rainfallSummary?.selected_station_id,
  'is-stale': station.is_stale || Boolean(station.last_error),
})

const refreshStatus = async () => {
  await dashboardStore.refreshAll()
  await weatherStore.fetchRainfallSummary()
}

onMounted(async () => {
  await Promise.allSettled([
    dashboardStore.refreshAll(),
    weatherStore.fetchRainfallSummary(),
  ])
  // Auto refresh every 5 seconds for near real-time updates
  refreshInterval = setInterval(() => {
    dashboardStore.refreshAll().catch(() => {})
  }, 5000)
  weatherRefreshInterval = setInterval(() => {
    weatherStore.fetchRainfallSummary().catch(() => {})
  }, 60000)
})

onUnmounted(() => {
  if (refreshInterval) {
    clearInterval(refreshInterval)
  }
  if (weatherRefreshInterval) {
    clearInterval(weatherRefreshInterval)
  }
})
</script>

<style scoped>
.dashboard {
  padding-bottom: 20px;
}

.stats-row {
  margin-bottom: 20px;
}

.rainfall-row {
  margin-bottom: 20px;
}

.rainfall-card {
  border: none;
}

.rainfall-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: #303133;
}

.rainfall-updated {
  color: #909399;
  font-size: 12px;
}

.rainfall-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.rainfall-station {
  padding: 16px;
  border: 1px solid #dbeafe;
  border-radius: 8px;
  background: linear-gradient(180deg, #f8fbff 0%, #ffffff 100%);
}

.rainfall-station.is-selected {
  border-color: #67c23a;
  box-shadow: inset 0 0 0 1px rgba(103, 194, 58, 0.24);
}

.rainfall-station.is-stale {
  border-color: #f3d19e;
  background: #fffaf2;
}

.rainfall-station-head,
.rainfall-station-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.rainfall-station-name {
  color: #172033;
  font-size: 15px;
  font-weight: 700;
}

.rainfall-station-id,
.rainfall-station-foot {
  color: #909399;
  font-size: 12px;
}

.rainfall-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin: 14px 0;
}

.rainfall-metric {
  min-height: 74px;
  padding: 10px;
  border-radius: 8px;
  background: #f4f7fb;
}

.rainfall-metric.actual {
  background: #ecf5ff;
}

.metric-label,
.metric-time {
  display: block;
  color: #909399;
  font-size: 12px;
}

.metric-value {
  display: block;
  margin-top: 6px;
  color: #1f4f8a;
  font-size: 18px;
  font-weight: 700;
  line-height: 1.1;
}

.metric-time {
  margin-top: 6px;
}

.stat-card {
  padding: 10px;
}

.stat-card :deep(.el-card__body) {
  width: 100%;
  display: flex;
  align-items: center;
}

.stat-icon {
  width: 60px;
  height: 60px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 32px;
  margin-right: 16px;
}

.stat-icon.total {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.stat-icon.online {
  background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
  color: white;
}

.stat-icon.alert {
  background: linear-gradient(135deg, #fc4a1a 0%, #f7b733 100%);
  color: white;
}

.stat-icon.data {
  background: linear-gradient(135deg, #2193b0 0%, #6dd5ed 100%);
  color: white;
}

.stat-info {
  flex: 1;
}

.stat-value {
  font-size: 28px;
  font-weight: 600;
  color: #303133;
  line-height: 1;
}

.stat-label {
  font-size: 14px;
  color: #909399;
  margin-top: 8px;
}

.stat-rate {
  font-size: 12px;
  color: #67c23a;
  margin-top: 4px;
}

.main-row {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.status-card {
  min-height: 500px;
}

.alert-list {
  max-height: 500px;
  overflow-y: auto;
}

.alert-item {
  padding: 12px;
  border-radius: 8px;
  margin-bottom: 12px;
  background: #f5f7fa;
  border-left: 4px solid #909399;
}

.alert-item.critical {
  border-left-color: #f56c6c;
  background: #fef0f0;
}

.alert-item.high {
  border-left-color: #e6a23c;
  background: #fdf6ec;
}

.alert-item.medium {
  border-left-color: #e6a23c;
}

.alert-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.alert-time {
  font-size: 12px;
  color: #909399;
}

.alert-content {
  font-size: 14px;
  color: #303133;
  margin-bottom: 8px;
}

.alert-location {
  font-size: 12px;
  color: #909399;
  display: flex;
  align-items: center;
  gap: 4px;
}

.reading-item {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.reading-sensor {
  font-weight: 500;
  color: #303133;
}

.reading-location {
  color: #909399;
  font-size: 13px;
}

.reading-value {
  color: #409eff;
  font-weight: 500;
}

@media (max-width: 900px) {
  .rainfall-grid {
    grid-template-columns: 1fr;
  }

  .rainfall-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.mobile-record-list {
  display: grid;
  gap: 12px;
}

.sensor-status-card {
  padding: 14px;
  border: 1px solid #ebeef5;
  border-radius: 10px;
  background: #fff;
}

.mobile-record-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.mobile-record-subtitle {
  margin-top: 5px;
  color: #909399;
  font-size: 12px;
}

.sensor-status-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 14px;
}

.sensor-status-grid > div {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.sensor-status-grid span {
  color: #909399;
  font-size: 12px;
}

.sensor-status-grid strong {
  overflow: hidden;
  color: #303133;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sensor-status-grid .is-online {
  color: #67c23a;
}

.sensor-status-grid .is-offline {
  color: #f56c6c;
}

@media (max-width: 767px) {
  .dashboard {
    padding-bottom: 4px;
  }

  .stats-row,
  .rainfall-row,
  .main-row {
    margin-bottom: 12px;
  }

  .stats-row :deep(.el-col) {
    margin-bottom: 12px;
  }

  .stat-card {
    min-height: 96px;
    padding: 2px;
  }

  .stat-card :deep(.el-card__body) {
    padding: 12px;
  }

  .stat-icon {
    width: 42px;
    height: 42px;
    margin-right: 10px;
    border-radius: 10px;
    font-size: 23px;
  }

  .stat-value {
    font-size: 23px;
  }

  .stat-label {
    margin-top: 5px;
    font-size: 12px;
  }

  .rainfall-station {
    padding: 12px;
  }

  .rainfall-card :deep(.el-empty) {
    padding: 12px 0;
  }

  .rainfall-card :deep(.el-empty__image) {
    width: 76px;
  }

  .rainfall-station-head,
  .rainfall-station-foot,
  .card-header {
    align-items: flex-start;
  }

  .rainfall-station-foot {
    flex-direction: column;
    gap: 4px;
  }

  .status-card {
    min-height: auto;
  }

  .alert-list {
    max-height: none;
  }

  .reading-item {
    gap: 8px;
  }

  .bottom-row .card-header {
    flex-direction: column;
    gap: 10px;
  }

  .bottom-row :deep(.el-radio-group) {
    width: 100%;
    display: flex;
  }

  .bottom-row :deep(.el-radio-button) {
    flex: 1;
  }

  .bottom-row :deep(.el-radio-button__inner) {
    width: 100%;
  }
}
</style>
