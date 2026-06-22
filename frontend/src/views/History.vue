<template>
  <div class="history-page">
    <el-card shadow="hover">
      <template #header>
        <div class="page-header">
          <h2>历史数据查询</h2>
        </div>
      </template>

      <el-form :model="filterForm" :inline="!isMobile" :label-position="isMobile ? 'top' : 'right'" class="filter-form">
        <el-form-item label="数据类型">
          <el-radio-group v-model="filterForm.data_scope" class="scope-switch" @change="handleDataScopeChange">
            <el-radio-button label="sensor">传感器</el-radio-button>
            <el-radio-button label="rainfall">小时雨量</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <template v-if="isSensorMode">
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
        </template>

        <template v-else>
          <el-form-item label="雨量站">
            <el-select v-model="filterForm.station_id" placeholder="全部雨量站" clearable class="station-select">
              <el-option
                v-for="station in rainfallStations"
                :key="station.station_id"
                :label="`${station.station_name} - ${station.station_id}`"
                :value="station.station_id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="雨量类型">
            <el-select v-model="filterForm.rainfall_type" class="rainfall-type-select">
              <el-option label="实况雨量" value="actual" />
              <el-option label="预报雨量" value="forecast" />
              <el-option label="实况 + 预报" value="all" />
            </el-select>
          </el-form-item>
        </template>

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

      <div v-if="chartData.length" class="chart-section">
        <v-chart class="history-chart" :option="chartOption" autoresize @datazoom="handleDataZoom" />
      </div>

      <template v-if="isSensorMode">
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
      </template>

      <template v-else>
        <el-table
          v-if="!isMobile"
          v-loading="loading"
          :data="historyData"
          stripe
          style="width: 100%"
          max-height="500"
        >
          <el-table-column prop="hour_time" label="雨量时次" width="180">
            <template #default="{ row }">{{ formatTime(row.hour_time) }}</template>
          </el-table-column>
          <el-table-column label="雨量站" min-width="180">
            <template #default="{ row }">
              <div class="station-cell">
                <strong>{{ row.station_name || row.station_id }}</strong>
                <span>{{ row.station_id }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="data_type" label="类型" width="100">
            <template #default="{ row }">
              <el-tag :type="getRainfallTypeTag(row.data_type)">{{ getRainfallTypeText(row.data_type) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="rainfall_mm" label="小时雨量(mm)" width="130">
            <template #default="{ row }">{{ formatRainfallValue(row.rainfall_mm) }}</template>
          </el-table-column>
          <el-table-column label="采集/预报批次" width="180">
            <template #default="{ row }">{{ formatTime(row.forecast_issued_at || row.batch_time) }}</template>
          </el-table-column>
          <el-table-column label="来源更新时间" width="180">
            <template #default="{ row }">{{ formatTime(row.source_updated_at) }}</template>
          </el-table-column>
          <el-table-column label="修正" width="110">
            <template #default="{ row }">
              <el-tag v-if="row.revision_count" type="warning">{{ row.revision_count }} 次</el-tag>
              <span v-else>-</span>
            </template>
          </el-table-column>
        </el-table>

        <div v-else v-loading="loading" class="history-card-list">
          <article v-for="record in historyData" :key="getRainfallRowKey(record)" class="history-record-card rainfall-record-card">
            <div class="history-record-head">
              <div>
                <strong>{{ formatTime(record.hour_time) }}</strong>
                <div>{{ record.station_name || record.station_id }} · {{ record.station_id }}</div>
              </div>
              <el-tag :type="getRainfallTypeTag(record.data_type)">{{ getRainfallTypeText(record.data_type) }}</el-tag>
            </div>
            <div class="history-record-fields rainfall-record-fields">
              <div>
                <span>小时雨量</span>
                <strong>{{ formatRainfallValue(record.rainfall_mm) }} mm</strong>
              </div>
              <div>
                <span>来源更新</span>
                <strong>{{ formatShortTime(record.source_updated_at) }}</strong>
              </div>
              <div>
                <span>批次</span>
                <strong>{{ formatShortTime(record.forecast_issued_at || record.batch_time) }}</strong>
              </div>
              <div>
                <span>修正</span>
                <strong>{{ record.revision_count ? `${record.revision_count} 次` : '-' }}</strong>
              </div>
            </div>
          </article>
        </div>

        <section v-if="showRevisionSection" class="revision-section">
          <div class="revision-header">
            <div>
              <h3>雨量修正记录</h3>
              <p>按被修正的雨量时次筛选，便于后续预测模型回溯数据版本变化。</p>
            </div>
            <el-tag v-if="rainfallRevisionTotal" type="warning">{{ rainfallRevisionTotal }} 条</el-tag>
          </div>

          <el-table
            v-if="!isMobile && rainfallRevisions.length"
            :data="rainfallRevisions"
            stripe
            style="width: 100%"
            max-height="260"
          >
            <el-table-column prop="hour_time" label="被修正时次" width="180">
              <template #default="{ row }">{{ formatTime(row.hour_time) }}</template>
            </el-table-column>
            <el-table-column label="雨量站" min-width="180">
              <template #default="{ row }">{{ row.station_name || row.station_id }} · {{ row.station_id }}</template>
            </el-table-column>
            <el-table-column label="旧值(mm)" width="110">
              <template #default="{ row }">{{ formatRainfallValue(row.old_rainfall_mm) }}</template>
            </el-table-column>
            <el-table-column label="新值(mm)" width="110">
              <template #default="{ row }">{{ formatRainfallValue(row.new_rainfall_mm) }}</template>
            </el-table-column>
            <el-table-column label="检测时间" width="180">
              <template #default="{ row }">{{ formatTime(row.detected_at) }}</template>
            </el-table-column>
          </el-table>

          <div v-else-if="isMobile && rainfallRevisions.length" class="revision-card-list">
            <article v-for="revision in rainfallRevisions" :key="getRevisionRowKey(revision)" class="revision-card">
              <div class="history-record-head">
                <div>
                  <strong>{{ formatTime(revision.hour_time) }}</strong>
                  <div>{{ revision.station_name || revision.station_id }} · {{ revision.station_id }}</div>
                </div>
                <el-tag type="warning">{{ formatRainfallValue(revision.old_rainfall_mm) }} -> {{ formatRainfallValue(revision.new_rainfall_mm) }}</el-tag>
              </div>
              <div class="revision-detected">检测 {{ formatTime(revision.detected_at) }}</div>
            </article>
          </div>

          <el-empty v-else description="当前范围内未检测到气象局修正记录" />
        </section>
      </template>

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

      <el-empty v-if="!loading && !historyData.length" :description="emptyDescription" />
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart, ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import dayjs from 'dayjs'
import { useSensorStore } from '../stores/sensors'
import { useWeatherStore } from '../stores/weather'
import { DATE_TIME_FORMAT, SHORT_DATE_TIME_FORMAT, formatUtc8AsBackendUtc, formatUtc8DateTime } from '../utils/time'
import { useResponsive } from '../composables/useResponsive'

use([CanvasRenderer, BarChart, LineChart, ScatterChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent])

const DATA_SCOPE_SENSOR = 'sensor'
const DATA_SCOPE_RAINFALL = 'rainfall'
const RAINFALL_TYPE_ALL = 'all'
const REVISION_EXPORT_LIMIT = 5000

const sensorStore = useSensorStore()
const weatherStore = useWeatherStore()
const { isMobile } = useResponsive()

const filterForm = ref({
  data_scope: DATA_SCOPE_SENSOR,
  sensor_id: '',
  station_id: '',
  rainfall_type: 'actual',
  timeRange: []
})

const historyData = ref([])
const chartData = ref([])
const rainfallRevisions = ref([])
const historyTotal = ref(0)
const rainfallRevisionTotal = ref(0)
const loading = ref(false)
const exporting = ref(false)
const hasQueried = ref(false)
const currentPage = ref(1)
const pageSize = ref(100)
const chartZoomRange = ref(null)
const activeQueryKey = ref('')
let refreshTimer = null

const isSensorMode = computed(() => filterForm.value.data_scope === DATA_SCOPE_SENSOR)
const isRainfallMode = computed(() => filterForm.value.data_scope === DATA_SCOPE_RAINFALL)
const ultrasonicSensors = computed(() => sensorStore.ultrasonicSensors)
const immersionSensors = computed(() => sensorStore.immersionSensors)
const rainfallStations = computed(() => weatherStore.stations)
const showRevisionSection = computed(() => (
  isRainfallMode.value && filterForm.value.rainfall_type !== 'forecast' && hasQueried.value
))

const emptyDescription = computed(() => {
  if (hasQueried.value) return '没有匹配的历史数据'
  return isSensorMode.value ? '请选择传感器查询数据' : '请选择条件查询小时雨量'
})

const getCurrentQueryKey = () => {
  const timeRange = filterForm.value.timeRange || []
  return [
    filterForm.value.data_scope,
    filterForm.value.sensor_id || '',
    filterForm.value.station_id || '',
    filterForm.value.rainfall_type || '',
    timeRange[0] || '',
    timeRange[1] || '',
  ].join('|')
}

const chartOption = computed(() => {
  if (!chartData.value.length) return {}
  return isSensorMode.value ? buildSensorChartOption() : buildRainfallChartOption()
})

const buildSensorChartOption = () => {
  const sensor = sensorStore.sensors.find(s => s.sensor_id === filterForm.value.sensor_id)
  const isUltrasonic = sensor?.sensor_type === 'ultrasonic'
  const data = chartData.value
    .filter(d => isUltrasonic ? d.water_level !== null : d.water_detected !== null)
    .map(d => [formatUtc8DateTime(d.recorded_at), isUltrasonic ? d.water_level : (d.water_detected ? 1 : 0)])
    .reverse()

  return {
    title: { text: `${sensor?.sensor_id || ''} - ${sensor?.location || ''}`, left: 'center' },
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: isMobile.value ? '8%' : '15%', containLabel: true },
    xAxis: { type: 'time', boundaryGap: false },
    yAxis: {
      type: 'value',
      name: isUltrasonic ? '水位(cm)' : '浸水状态',
      min: isUltrasonic ? 0 : -0.1,
      max: isUltrasonic ? null : 1.1
    },
    dataZoom: getDataZoom(),
    series: [{
      name: isUltrasonic ? '水位' : '浸水',
      type: isUltrasonic ? 'line' : 'scatter',
      smooth: true,
      symbol: isUltrasonic ? 'none' : 'circle',
      symbolSize: isUltrasonic ? 0 : 10,
      data
    }]
  }
}

const buildRainfallChartOption = () => {
  const groups = new Map()
  chartData.value
    .slice()
    .sort((left, right) => new Date(left.hour_time) - new Date(right.hour_time))
    .forEach((row) => {
      const stationName = row.station_name || row.station_id
      const typeText = getRainfallTypeText(row.data_type)
      const key = `${stationName} ${typeText}`
      if (!groups.has(key)) {
        groups.set(key, {
          name: key,
          dataType: row.data_type,
          data: [],
        })
      }
      groups.get(key).data.push([formatUtc8DateTime(row.hour_time), row.rainfall_mm])
    })

  const selectedStation = rainfallStations.value.find(station => station.station_id === filterForm.value.station_id)
  const title = selectedStation ? `${selectedStation.station_name} 小时雨量` : '小时雨量历史'

  return {
    title: { text: title, left: 'center' },
    tooltip: { trigger: 'axis' },
    legend: { top: 28 },
    grid: { left: '3%', right: '4%', bottom: isMobile.value ? '8%' : '15%', top: 72, containLabel: true },
    xAxis: { type: 'time', boundaryGap: true },
    yAxis: { type: 'value', name: '雨量(mm)', min: 0 },
    dataZoom: getDataZoom(),
    series: Array.from(groups.values()).map(group => ({
      name: group.name,
      type: group.dataType === 'actual' ? 'bar' : 'line',
      smooth: group.dataType === 'forecast',
      symbol: group.dataType === 'actual' ? 'none' : 'circle',
      symbolSize: group.dataType === 'actual' ? 0 : 6,
      lineStyle: group.dataType === 'forecast' ? { type: 'dashed' } : undefined,
      barMaxWidth: 28,
      data: group.data,
    })),
  }
}

const getDataZoom = () => (
  isMobile.value
    ? [{ id: 'history-inside-zoom', type: 'inside', ...(chartZoomRange.value || {}) }]
    : [
        { id: 'history-inside-zoom', type: 'inside', ...(chartZoomRange.value || {}) },
        { id: 'history-slider-zoom', type: 'slider', ...(chartZoomRange.value || {}) }
      ]
)

const formatTime = (time) => formatUtc8DateTime(time, DATE_TIME_FORMAT)
const formatShortTime = (time) => formatUtc8DateTime(time, SHORT_DATE_TIME_FORMAT)

const formatRainfallValue = (value) => {
  if (value === null || value === undefined || value === '') return '-'
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(1) : '-'
}

const getStatusType = (status) => {
  const map = { normal: 'success', warning: 'warning', danger: 'danger', alarm: 'danger', offline: 'info' }
  return map[status] || 'info'
}

const getStatusText = (status) => {
  const map = { normal: '正常', warning: '预警', danger: '危险', alarm: '告警', offline: '离线' }
  return map[status] || status
}

const getRainfallTypeText = (type) => {
  const map = { actual: '实况', forecast: '预报' }
  return map[type] || type
}

const getRainfallTypeTag = (type) => {
  const map = { actual: 'success', forecast: 'warning' }
  return map[type] || 'info'
}

const getRainfallRowKey = (row) => [
  row.station_id,
  row.data_type,
  row.hour_time,
  row.batch_time,
].join('|')

const getRevisionRowKey = (row) => [
  row.station_id,
  row.hour_time,
  row.detected_at,
  row.old_rainfall_mm,
  row.new_rainfall_mm,
].join('|')

const getRevisionLookupKey = (stationId, hourTime) => `${stationId}|${formatTime(hourTime)}`

const buildRevisionLookup = (revisions) => {
  const lookup = new Map()
  const items = revisions || []
  items.forEach((revision) => {
    const key = getRevisionLookupKey(revision.station_id, revision.hour_time)
    if (!lookup.has(key)) {
      lookup.set(key, [])
    }
    lookup.get(key).push(revision)
  })
  return lookup
}

const formatRevisionValueList = (revisions, field) => (
  revisions.map(revision => formatRainfallValue(revision[field])).join('; ')
)

const formatRevisionTimeList = (revisions, field) => (
  revisions.map(revision => formatTime(revision[field])).join('; ')
)

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

const buildRainfallParams = () => {
  const params = buildQueryParams()
  if (filterForm.value.station_id) {
    params.station_id = filterForm.value.station_id
  }
  if (filterForm.value.rainfall_type && filterForm.value.rainfall_type !== RAINFALL_TYPE_ALL) {
    params.data_type = filterForm.value.rainfall_type
  }
  return params
}

const clearResults = () => {
  historyData.value = []
  chartData.value = []
  rainfallRevisions.value = []
  historyTotal.value = 0
  rainfallRevisionTotal.value = 0
  chartZoomRange.value = null
  activeQueryKey.value = ''
  currentPage.value = 1
  hasQueried.value = false
}

const handleDataScopeChange = () => {
  clearResults()
  if (isRainfallMode.value) {
    weatherStore.fetchStations().catch(() => {})
  }
}

const queryHistory = async ({ resetPage = true, refreshChart = true } = {}) => {
  if (isSensorMode.value && !filterForm.value.sensor_id) {
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

    if (isSensorMode.value) {
      await querySensorHistory({ queryKey, queryChanged, refreshChart })
    } else {
      await queryRainfallHistory({ queryKey, queryChanged, refreshChart })
    }

    hasQueried.value = true
    activeQueryKey.value = queryKey
    if (queryChanged) {
      chartZoomRange.value = null
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '查询失败')
  } finally {
    loading.value = false
  }
}

const querySensorHistory = async ({ queryChanged, refreshChart }) => {
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
  rainfallRevisions.value = []
  rainfallRevisionTotal.value = 0
}

const queryRainfallHistory = async ({ queryChanged, refreshChart }) => {
  const baseParams = buildRainfallParams()
  const tableRequest = weatherStore.fetchHistory({
    ...baseParams,
    limit: pageSize.value,
    page: currentPage.value,
  })
  const chartRequest = refreshChart || queryChanged
    ? weatherStore.fetchHistory({ ...baseParams, limit: 2000, page: 1 })
    : null
  const shouldFetchRevisions = filterForm.value.rainfall_type !== 'forecast'
  const revisionsRequest = shouldFetchRevisions
    ? weatherStore.fetchRevisions({
        ...buildQueryParams(),
        station_id: filterForm.value.station_id || undefined,
        time_field: 'hour_time',
        limit: 200,
        page: 1,
      })
    : Promise.resolve({ items: [], total: 0 })

  const [response, chartResponse, revisionResponse] = await Promise.all([
    tableRequest,
    chartRequest,
    revisionsRequest,
  ])

  historyData.value = response.items
  historyTotal.value = response.total
  if (chartResponse) {
    chartData.value = chartResponse.items
  }
  rainfallRevisions.value = revisionResponse.items || []
  rainfallRevisionTotal.value = revisionResponse.total || 0
}

const resetFilter = () => {
  const currentScope = filterForm.value.data_scope
  filterForm.value = {
    data_scope: currentScope,
    sensor_id: '',
    station_id: '',
    rainfall_type: 'actual',
    timeRange: [],
  }
  clearResults()
}

const csvCell = (value) => {
  if (value === null || value === undefined) return ''
  const text = String(value).replace(/"/g, '""')
  return /[",\n\r]/.test(text) ? `"${text}"` : text
}

const downloadCsv = (filename, rows) => {
  const csvContent = rows.map(row => row.map(csvCell).join(',')).join('\n')
  const blob = new Blob(['\ufeff' + csvContent], { type: 'text/csv;charset=utf-8;' })
  const downloadUrl = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = downloadUrl
  link.download = filename
  link.click()
  URL.revokeObjectURL(downloadUrl)
}

const exportData = async () => {
  if (historyTotal.value === 0) return

  if (historyTotal.value > 10000) {
    ElMessage.warning('单次最多导出最近 10000 条记录，请缩小时间范围后重试')
    return
  }

  exporting.value = true
  try {
    if (isSensorMode.value) {
      await exportSensorData()
    } else {
      await exportRainfallData()
    }
    ElMessage.success('导出成功')
  } catch {
    ElMessage.error('导出失败')
  } finally {
    exporting.value = false
  }
}

const exportSensorData = async () => {
  const response = await sensorStore.fetchReadings(filterForm.value.sensor_id, {
    ...buildQueryParams(),
    limit: Math.max(historyTotal.value, 1),
    page: 1,
  })
  const sensor = sensorStore.sensors.find(s => s.sensor_id === filterForm.value.sensor_id)
  const rows = [
    ['时间', '传感器ID', '位置', '状态', '水位(cm)', '浸水', '供电/电量', '信号(dBm)'],
    ...response.items.map(row => [
      formatTime(row.recorded_at),
      row.sensor_id,
      sensor?.location || '',
      row.status,
      row.water_level ?? '',
      row.water_detected ?? '',
      row.external_powered ? '外接供电' : (row.battery_level ?? ''),
      row.signal_strength ?? ''
    ])
  ]
  downloadCsv(`sensor_data_${filterForm.value.sensor_id}_${dayjs().format('YYYYMMDD')}.csv`, rows)
}

const exportRainfallData = async () => {
  const [historyResponse, revisionResponse] = await Promise.all([
    weatherStore.fetchHistory({
      ...buildRainfallParams(),
      limit: Math.max(historyTotal.value, 1),
      page: 1,
    }),
    filterForm.value.rainfall_type !== 'forecast'
      ? weatherStore.fetchRevisions({
          ...buildQueryParams(),
          station_id: filterForm.value.station_id || undefined,
          time_field: 'hour_time',
          limit: REVISION_EXPORT_LIMIT,
          page: 1,
        })
      : Promise.resolve({ items: [] }),
  ])
  const revisionLookup = buildRevisionLookup(revisionResponse.items)
  const rows = [
    ['雨量时次', '雨量站ID', '雨量站', '类型', '小时雨量(mm)', '采集/预报批次', '来源更新时间', '原始时次', '修正次数', '修正前(mm)', '修正后(mm)', '修正检测时间'],
    ...historyResponse.items.map((row) => {
      const revisions = row.data_type === 'actual'
        ? (revisionLookup.get(getRevisionLookupKey(row.station_id, row.hour_time)) || [])
        : []
      const revisionCount = row.data_type === 'actual'
        ? (row.revision_count || revisions.length || '')
        : ''
      return [
        formatTime(row.hour_time),
        row.station_id,
        row.station_name || '',
        getRainfallTypeText(row.data_type),
        formatRainfallValue(row.rainfall_mm),
        formatTime(row.forecast_issued_at || row.batch_time),
        formatTime(row.source_updated_at),
        row.raw_time_label || '',
        revisionCount,
        formatRevisionValueList(revisions, 'old_rainfall_mm'),
        formatRevisionValueList(revisions, 'new_rainfall_mm'),
        formatRevisionTimeList(revisions, 'detected_at'),
      ]
    })
  ]
  const stationPart = filterForm.value.station_id || 'all'
  downloadCsv(`rainfall_history_${stationPart}_${dayjs().format('YYYYMMDD')}.csv`, rows)
}

const handlePageChange = () => {
  queryHistory({ resetPage: false, refreshChart: false })
}

const handlePageSizeChange = () => {
  currentPage.value = 1
  queryHistory({ resetPage: false, refreshChart: false })
}

onMounted(() => {
  Promise.allSettled([
    sensorStore.fetchSensors(),
    weatherStore.fetchStations(),
  ])

  refreshTimer = setInterval(() => {
    sensorStore.fetchSensors().catch(() => {})
    if (isRainfallMode.value) {
      weatherStore.fetchStations().catch(() => {})
    }
    if (hasQueried.value) {
      queryHistory({ resetPage: false, refreshChart: true })
    }
  }, 60000)
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

.scope-switch {
  white-space: nowrap;
}

.sensor-select,
.station-select {
  width: 240px;
}

.rainfall-type-select {
  width: 150px;
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

.station-cell {
  display: grid;
  gap: 3px;
}

.station-cell strong {
  color: #303133;
  font-size: 14px;
  font-weight: 600;
}

.station-cell span {
  color: #909399;
  font-size: 12px;
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
  border-radius: 8px;
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

.rainfall-record-fields {
  grid-template-columns: repeat(2, minmax(0, 1fr));
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

.revision-section {
  margin-top: 24px;
  padding-top: 18px;
  border-top: 1px solid #ebeef5;
}

.revision-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.revision-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.revision-header p {
  margin: 6px 0 0;
  color: #909399;
  font-size: 13px;
}

.revision-card-list {
  display: grid;
  gap: 12px;
}

.revision-card {
  padding: 14px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #fff;
}

.revision-detected {
  margin-top: 10px;
  color: #909399;
  font-size: 12px;
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
  .station-select,
  .rainfall-type-select,
  .filter-form :deep(.el-date-editor) {
    width: 100% !important;
  }

  .scope-switch,
  .filter-form :deep(.el-form-item__content) {
    width: 100%;
  }

  .scope-switch :deep(.el-radio-button) {
    width: 50%;
  }

  .scope-switch :deep(.el-radio-button__inner) {
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

  .revision-header {
    display: grid;
  }
}
</style>
