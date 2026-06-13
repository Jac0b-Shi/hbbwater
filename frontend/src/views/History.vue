<template>
  <div class="history-page">
    <el-card shadow="hover">
      <template #header>
        <div class="page-header">
          <h2>历史数据查询</h2>
        </div>
      </template>

      <!-- Filter Form -->
      <el-form :model="filterForm" :inline="!isMobile" :label-position="isMobile ? 'top' : 'right'" class="filter-form">
        <el-form-item label="传感器">
          <el-select v-model="filterForm.sensor_id" placeholder="选择传感器" clearable class="sensor-select">
            <el-option-group label="超声波传感器">
              <el-option 
                v-for="s in ultrasonicSensors" 
                :key="s.sensor_id" 
                :label="`${s.sensor_id} - ${s.location}`" 
                :value="s.sensor_id" 
              />
            </el-option-group>
            <el-option-group label="浸水传感器">
              <el-option 
                v-for="s in immersionSensors" 
                :key="s.sensor_id" 
                :label="`${s.sensor_id} - ${s.location}`" 
                :value="s.sensor_id" 
              />
            </el-option-group>
          </el-select>
        </el-form-item>
        <el-form-item label="时间范围">
          <el-date-picker
            v-if="!isMobile"
            v-model="filterForm.timeRange"
            type="datetimerange"
            range-separator="至"
            start-placeholder="开始时间"
            end-placeholder="结束时间"
            value-format="YYYY-MM-DD HH:mm:ss"
          />
          <div v-else class="mobile-time-range">
            <el-date-picker
              v-model="filterForm.timeRange[0]"
              type="datetime"
              placeholder="开始时间"
              value-format="YYYY-MM-DD HH:mm:ss"
            />
            <el-date-picker
              v-model="filterForm.timeRange[1]"
              type="datetime"
              placeholder="结束时间"
              value-format="YYYY-MM-DD HH:mm:ss"
            />
          </div>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="queryHistory">
            <el-icon><Search /></el-icon>查询
          </el-button>
          <el-button @click="resetFilter">重置</el-button>
          <el-button type="success" :loading="exporting" @click="exportData" :disabled="historyTotal === 0">
            <el-icon><Download /></el-icon>导出
          </el-button>
        </el-form-item>
      </el-form>

      <!-- Chart -->
      <div v-if="chartData.length" class="chart-section">
        <v-chart class="history-chart" :option="chartOption" autoresize @datazoom="handleDataZoom" />
      </div>

      <!-- Data Table -->
      <el-table
        v-if="!isMobile"
        v-loading="loading"
        :data="historyData"
        stripe
        style="width: 100%"
        max-height="500"
      >
        <el-table-column prop="recorded_at" label="时间" width="180">
          <template #default="{ row }">{{ formatTime(row.recorded_at) }}</template>
        </el-table-column>
        <el-table-column prop="sensor_id" label="传感器" width="150" />
        <el-table-column prop="location" label="位置" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="getStatusType(row.status)">{{ getStatusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="water_level" label="水位(cm)" width="120">
          <template #default="{ row }">{{ row.water_level?.toFixed(2) || '-' }}</template>
        </el-table-column>
        <el-table-column prop="water_detected" label="浸水" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.water_detected !== null" :type="row.water_detected ? 'danger' : 'success'">
              {{ row.water_detected ? '是' : '否' }}
            </el-tag>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="供电/电量" width="120">
          <template #default="{ row }">{{ row.external_powered ? '外接供电' : (row.battery_level?.toFixed(1) || '-') }}</template>
        </el-table-column>
      </el-table>
      <div v-else v-loading="loading" class="history-card-list">
        <article v-for="record in historyData" :key="record.id" class="history-record-card">
          <div class="history-record-head">
            <div>
              <strong>{{ formatTime(record.recorded_at) }}</strong>
              <div>{{ record.sensor_id }} · {{ record.location || '未设置位置' }}</div>
            </div>
            <el-tag :type="getStatusType(record.status)">{{ getStatusText(record.status) }}</el-tag>
          </div>
          <div class="history-record-fields">
            <div>
              <span>读数</span>
              <strong v-if="record.water_level !== null && record.water_level !== undefined">{{ record.water_level.toFixed(2) }} cm</strong>
              <strong v-else-if="record.water_detected !== null">{{ record.water_detected ? '浸水' : '正常' }}</strong>
              <strong v-else>-</strong>
            </div>
            <div>
              <span>供电</span>
              <strong>{{ record.external_powered ? '外接供电' : (record.battery_level !== null && record.battery_level !== undefined ? `${record.battery_level.toFixed(1)}%` : '-') }}</strong>
            </div>
          </div>
        </article>
      </div>

      <!-- Pagination -->
      <el-pagination
        v-if="historyTotal > 0"
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[20, 50, 100, 200]"
        :layout="isMobile ? 'total, prev, next' : 'total, sizes, prev, pager, next'"
        :pager-count="isMobile ? 5 : 7"
        :total="historyTotal"
        class="pagination"
        @current-change="handlePageChange"
        @size-change="handlePageSizeChange"
      />

      <el-empty v-if="!loading && !historyData.length" description="请选择条件查询数据" />
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import { useSensorStore } from '../stores/sensors'
import dayjs from 'dayjs'
import { formatUtc8AsBackendUtc, formatUtc8DateTime } from '../utils/time'
import { useResponsive } from '../composables/useResponsive'

use([CanvasRenderer, LineChart, ScatterChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent])

const sensorStore = useSensorStore()
const { isMobile } = useResponsive()

const filterForm = ref({
  sensor_id: '',
  timeRange: []
})

const historyData = ref([])
const chartData = ref([])
const historyTotal = ref(0)
const loading = ref(false)
const exporting = ref(false)
const currentPage = ref(1)
const pageSize = ref(100)
const chartZoomRange = ref(null)
const activeQueryKey = ref('')
let refreshTimer = null

const ultrasonicSensors = computed(() => sensorStore.ultrasonicSensors)
const immersionSensors = computed(() => sensorStore.immersionSensors)

const getCurrentQueryKey = () => {
  const timeRange = filterForm.value.timeRange || []
  return [filterForm.value.sensor_id, timeRange[0] || '', timeRange[1] || ''].join('|')
}

const chartOption = computed(() => {
  if (!chartData.value.length) return {}
  
  const sensor = sensorStore.sensors.find(s => s.sensor_id === filterForm.value.sensor_id)
  const isUltrasonic = sensor?.sensor_type === 'ultrasonic'
  
  const data = chartData.value
    .filter(d => isUltrasonic ? d.water_level !== null : d.water_detected !== null)
    .map(d => [formatUtc8DateTime(d.recorded_at), isUltrasonic ? d.water_level : (d.water_detected ? 1 : 0)])
    .reverse()

  return {
    title: { text: `${sensor?.sensor_id} - ${sensor?.location}`, left: 'center' },
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: isMobile.value ? '8%' : '15%', containLabel: true },
    xAxis: { type: 'time', boundaryGap: false },
    yAxis: { 
      type: 'value', 
      name: isUltrasonic ? '水位(cm)' : '浸水状态',
      min: isUltrasonic ? 0 : -0.1,
      max: isUltrasonic ? null : 1.1
    },
    dataZoom: isMobile.value
      ? [{ id: 'history-inside-zoom', type: 'inside', ...(chartZoomRange.value || {}) }]
      : [
          { id: 'history-inside-zoom', type: 'inside', ...(chartZoomRange.value || {}) },
          { id: 'history-slider-zoom', type: 'slider', ...(chartZoomRange.value || {}) }
        ],
    series: [{
      name: isUltrasonic ? '水位' : '浸水',
      type: isUltrasonic ? 'line' : 'scatter',
      smooth: true,
      symbol: isUltrasonic ? 'none' : 'circle',
      symbolSize: isUltrasonic ? 0 : 10,
      data: data
    }]
  }
})

const formatTime = (time) => formatUtc8DateTime(time)

const getStatusType = (status) => {
  const map = { normal: 'success', warning: 'warning', danger: 'danger', alarm: 'danger', offline: 'info' }
  return map[status] || 'info'
}

const getStatusText = (status) => {
  const map = { normal: '正常', warning: '预警', danger: '危险', alarm: '告警', offline: '离线' }
  return map[status] || status
}

const handleDataZoom = (params) => {
  const zoom = params?.batch?.[0] || params
  if (!Number.isFinite(zoom?.start) || !Number.isFinite(zoom?.end)) {
    return
  }

  chartZoomRange.value = {
    start: zoom.start,
    end: zoom.end
  }
}

const buildQueryParams = () => {
  const params = {}
  const [startTime, endTime] = filterForm.value.timeRange || []
  if (startTime) {
    params.start_time = formatUtc8AsBackendUtc(startTime)
  }
  if (endTime) {
    params.end_time = formatUtc8AsBackendUtc(endTime)
  }
  return params
}

const queryHistory = async ({ resetPage = true, refreshChart = true } = {}) => {
  if (!filterForm.value.sensor_id) {
    ElMessage.warning('请选择传感器')
    return
  }
  
  loading.value = true
  try {
    const queryKey = getCurrentQueryKey()
    const queryChanged = queryKey !== activeQueryKey.value
    if (resetPage || queryChanged) {
      currentPage.value = 1
    }

    const baseParams = buildQueryParams()
    const tableRequest = sensorStore.fetchReadings(filterForm.value.sensor_id, {
      ...baseParams,
      limit: pageSize.value,
      page: currentPage.value,
    })
    const chartRequest = refreshChart || queryChanged
      ? sensorStore.fetchReadings(filterForm.value.sensor_id, { ...baseParams, limit: 2000, page: 1 })
      : null
    const [response, chartResponse] = await Promise.all([tableRequest, chartRequest])

    historyData.value = response.items.map(item => ({
      ...item,
      location: sensorStore.sensors.find(s => s.sensor_id === item.sensor_id)?.location || ''
    }))
    historyTotal.value = response.total
    if (chartResponse) {
      chartData.value = chartResponse.items
    }
    activeQueryKey.value = queryKey
    if (queryChanged) {
      chartZoomRange.value = null
    }
  } catch (error) {
    ElMessage.error('查询失败')
  } finally {
    loading.value = false
  }
}

const resetFilter = () => {
  filterForm.value = { sensor_id: '', timeRange: [] }
  historyData.value = []
  chartData.value = []
  historyTotal.value = 0
  chartZoomRange.value = null
  activeQueryKey.value = ''
  currentPage.value = 1
}

const exportData = async () => {
  if (!filterForm.value.sensor_id || historyTotal.value === 0) {
    return
  }

  if (historyTotal.value > 10000) {
    ElMessage.warning('单次最多导出最近 10000 条记录，请缩小时间范围后重试')
    return
  }

  exporting.value = true
  try {
    const response = await sensorStore.fetchReadings(filterForm.value.sensor_id, {
      ...buildQueryParams(),
      limit: Math.max(historyTotal.value, 1),
      page: 1,
    })
    const sensor = sensorStore.sensors.find(s => s.sensor_id === filterForm.value.sensor_id)
    const csvContent = [
      ['时间', '传感器ID', '位置', '状态', '水位(cm)', '浸水', '供电/电量', '信号(dBm)'].join(','),
      ...response.items.map(row => [
        formatTime(row.recorded_at),
        row.sensor_id,
        sensor?.location || '',
        row.status,
        row.water_level ?? '',
        row.water_detected ?? '',
        row.external_powered ? '外接供电' : (row.battery_level ?? ''),
        row.signal_strength ?? ''
      ].join(','))
    ].join('\n')

    const blob = new Blob(['\ufeff' + csvContent], { type: 'text/csv;charset=utf-8;' })
    const downloadUrl = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = downloadUrl
    link.download = `sensor_data_${filterForm.value.sensor_id}_${dayjs().format('YYYYMMDD')}.csv`
    link.click()
    URL.revokeObjectURL(downloadUrl)
    ElMessage.success('导出成功')
  } catch {
    ElMessage.error('导出失败')
  } finally {
    exporting.value = false
  }
}

const handlePageChange = () => {
  queryHistory({ resetPage: false, refreshChart: false })
}

const handlePageSizeChange = () => {
  currentPage.value = 1
  queryHistory({ resetPage: false, refreshChart: false })
}

onMounted(() => {
  sensorStore.fetchSensors()
  refreshTimer = setInterval(() => {
    sensorStore.fetchSensors()
    if (filterForm.value.sensor_id) {
      queryHistory({ resetPage: false, refreshChart: true })
    }
  }, 10000)
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
  }
})
</script>

<style scoped>
.page-header h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.filter-form {
  background: #f5f7fa;
  padding: 20px;
  border-radius: 8px;
  margin-bottom: 20px;
}

.sensor-select {
  width: 220px;
}

.mobile-time-range {
  width: 100%;
  display: grid;
  gap: 8px;
}

.chart-section {
  height: 400px;
  margin-bottom: 20px;
}

.history-chart {
  width: 100%;
  height: 100%;
}

.pagination {
  margin-top: 20px;
  justify-content: flex-end;
}

.history-card-list {
  min-height: 120px;
  display: grid;
  gap: 12px;
}

.history-record-card {
  padding: 14px;
  border: 1px solid #ebeef5;
  border-radius: 10px;
  background: #fff;
}

.history-record-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.history-record-head strong {
  color: #303133;
  font-size: 14px;
}

.history-record-head div div {
  margin-top: 5px;
  color: #909399;
  font-size: 12px;
}

.history-record-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 14px;
}

.history-record-fields > div {
  display: grid;
  gap: 5px;
}

.history-record-fields span {
  color: #909399;
  font-size: 12px;
}

.history-record-fields strong {
  color: #606266;
  font-size: 14px;
}

@media (max-width: 767px) {
  .filter-form {
    padding: 14px;
    margin-bottom: 14px;
  }

  .filter-form :deep(.el-form-item) {
    width: 100%;
    margin-right: 0;
    margin-bottom: 14px;
  }

  .filter-form :deep(.el-form-item:last-child) {
    margin-bottom: 0;
  }

  .sensor-select,
  .filter-form :deep(.el-date-editor) {
    width: 100% !important;
  }

  .filter-form :deep(.el-form-item__content) {
    width: 100%;
  }

  .filter-form :deep(.el-form-item:last-child .el-form-item__content) {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
  }

  .filter-form :deep(.el-button) {
    min-height: 42px;
    margin-left: 0;
    padding-right: 8px;
    padding-left: 8px;
  }

  .chart-section {
    height: 280px;
  }

  .pagination {
    justify-content: space-between;
  }
}
</style>
