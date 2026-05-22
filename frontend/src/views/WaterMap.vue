<template>
  <div class="water-map-page">
    <el-row :gutter="16" class="summary-row">
      <el-col :xs="12" :md="6">
        <el-card class="summary-card card-total" shadow="hover">
          <div class="summary-icon">
            <el-icon><LocationFilled /></el-icon>
          </div>
          <div class="summary-content">
            <div class="summary-label">监测点总数</div>
            <div class="summary-value">{{ activeSensors.length }}</div>
            <div class="summary-meta">已纳入地图监控的启用点位</div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :md="6">
        <el-card class="summary-card card-normal" shadow="hover">
          <div class="summary-icon">
            <el-icon><CircleCheck /></el-icon>
          </div>
          <div class="summary-content">
            <div class="summary-label">正常</div>
            <div class="summary-value">{{ normalCount }}</div>
            <div class="summary-meta">{{ onlineCount }} 个点位在线</div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :md="6">
        <el-card class="summary-card card-alert" shadow="hover">
          <div class="summary-icon">
            <el-icon><Warning /></el-icon>
          </div>
          <div class="summary-content">
            <div class="summary-label">预警/告警</div>
            <div class="summary-value">{{ abnormalCount }}</div>
            <div class="summary-meta">
              离线 {{ offlineCount }} 个
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :xs="12" :md="6">
        <el-card class="summary-card card-water" shadow="hover">
          <div class="summary-icon">
            <el-icon><DataLine /></el-icon>
          </div>
          <div class="summary-content">
            <div class="summary-label">平均相对水位</div>
            <div class="summary-value">
              <template v-if="averageRelativeWaterLevel !== null">
                {{ formatMetricValue(averageRelativeWaterLevel) }}<span class="summary-unit">cm</span>
              </template>
              <template v-else>--</template>
            </div>
            <div class="summary-meta">基于 {{ averageSampleCount }} 个已设基准在线超声波点位</div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-card class="map-card" shadow="hover" v-loading="pageLoading">
      <template #header>
        <div class="map-card-header">
          <div>
            <div class="map-title">水位监测地图</div>
            <div class="map-subtitle">
              点击点位标签可查看实时读数、设置超声波基准值，并通过拖拽后锁定固化地图布局
            </div>
          </div>
          <div class="map-toolbar">
            <div class="zoom-controls">
              <el-button size="small" :disabled="mapZoom <= MIN_MAP_ZOOM" @click="changeZoom(-0.1)">缩小</el-button>
              <el-slider
                v-model="mapZoom"
                :min="MIN_MAP_ZOOM"
                :max="MAX_MAP_ZOOM"
                :step="0.05"
                :show-tooltip="false"
                class="zoom-slider"
              />
              <span class="zoom-value">{{ zoomPercent }}%</span>
              <el-button size="small" @click="resetZoom">适配</el-button>
            </div>
            <el-select v-model="statusFilter" size="small" style="width: 160px">
              <el-option
                v-for="option in statusFilterOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
            <el-button :loading="statusLoading" size="small" @click="refreshAll">
              <el-icon><Refresh /></el-icon>刷新数据
            </el-button>
          </div>
        </div>
      </template>

      <div v-if="selectedRainfallStation" class="rainfall-strip" :class="{ 'is-backup': selectedRainfallStation.role === 'backup' }">
        <div class="rainfall-strip-main">
          <div class="rainfall-strip-icon">
            <el-icon><Cloudy /></el-icon>
          </div>
          <div>
            <div class="rainfall-strip-title">
              {{ selectedRainfallStation.station_name }}
              <span>{{ selectedRainfallStation.role === 'backup' ? '备份参考' : '主站参考' }}</span>
            </div>
            <div class="rainfall-strip-meta">
              当前实况 {{ formatRainfall(selectedRainfallStation.current_actual_mm) }}
              · 未来3h {{ formatRainfall(selectedRainfallStation.forecast_totals?.next_3h) }}
              · 未来24h {{ formatRainfall(selectedRainfallStation.forecast_totals?.next_24h) }}
            </div>
          </div>
        </div>
        <div class="rainfall-strip-status">
          {{ getRainfallMapStatus(selectedRainfallStation) }}
        </div>
      </div>

      <div v-if="unplacedCount || unlockedCount" class="map-notices">
        <el-alert
          v-if="unplacedCount"
          type="warning"
          :closable="false"
          show-icon
          :title="`有 ${unplacedCount} 个点位仍在使用临时坐标，请拖到对应位置后锁定。`"
        />
        <el-alert
          v-if="unlockedCount"
          type="info"
          :closable="false"
          show-icon
          :title="`有 ${unlockedCount} 个点位已保存坐标但尚未锁定，仍可继续拖动微调。`"
        />
      </div>

      <el-empty v-if="!mergedMarkers.length" description="当前没有可展示的传感器" />

      <div v-else class="map-stage-shell">
        <div class="map-viewport">
          <div class="map-canvas" :style="mapCanvasStyle">
            <div ref="mapStageRef" class="map-stage" @click="closePanel">
              <img class="map-image" src="/campus-water-map.webp" alt="校园水位地图" />

              <div
                v-for="marker in filteredMarkers"
                :key="marker.sensor_id"
                class="sensor-marker"
                :class="getMarkerClasses(marker)"
                :style="getMarkerStyle(marker)"
              >
                <button
                  class="sensor-dot"
                  type="button"
                  @click.stop="toggleMarkerPanel(marker)"
                >
                  <span class="sensor-dot-core" />
                </button>

                <button
                  v-if="accountStore.canManageSensors && !isMarkerLocked(marker)"
                  class="drag-handle"
                  type="button"
                  @pointerdown.prevent.stop="startDrag($event, marker)"
                  :title="`拖动 ${marker.sensor_id}`"
                >
                  <span class="drag-text">拖</span>
                </button>

                <button
                  class="sensor-label"
                  type="button"
                  @click.stop="toggleMarkerPanel(marker)"
                >
                  <span class="sensor-id">{{ marker.sensor_id }}</span>
                  <span class="sensor-reading">{{ getMarkerReadingText(marker) }}</span>
                  <span v-if="marker.sensor_type === 'ultrasonic' && marker.metric.mode === 'distance'" class="sensor-hint">
                    待设基准
                  </span>
                  <span v-else-if="!marker.hasStoredPosition" class="sensor-hint">
                    临时位置
                  </span>
                </button>

                <div
                  v-if="selectedSensorId === marker.sensor_id"
                  class="sensor-panel"
                  :class="getPanelClasses(marker)"
                  @click.stop
                >
                  <div class="sensor-panel-header">
                    <div>
                      <div class="panel-title-row">
                        <span class="panel-title">{{ marker.sensor_id }}</span>
                        <el-tag size="small" :type="getStatusTagType(marker.status)">
                          {{ getStatusText(marker.status) }}
                        </el-tag>
                      </div>
                      <div class="panel-subtitle">{{ marker.location }}</div>
                    </div>
                    <button class="panel-close" type="button" @click="closePanel">
                      x
                    </button>
                  </div>

                  <div class="sensor-panel-grid">
                    <div class="metric-item">
                      <span class="metric-label">传感器类型</span>
                      <span class="metric-value">{{ getSensorTypeLabel(marker.sensor_type) }}</span>
                    </div>
                    <div class="metric-item">
                      <span class="metric-label">最近上报</span>
                      <span class="metric-value">{{ formatLastReading(marker.last_reading) }}</span>
                    </div>
                    <div v-if="marker.sensor_type === 'ultrasonic'" class="metric-item">
                      <span class="metric-label">当前测距</span>
                      <span class="metric-value">{{ formatMetricValue(marker.water_level) }} cm</span>
                    </div>
                    <div v-if="marker.sensor_type === 'ultrasonic'" class="metric-item">
                      <span class="metric-label">相对水位</span>
                      <span class="metric-value">
                        {{ marker.relativeWaterLevel !== null ? `${formatMetricValue(marker.relativeWaterLevel)} cm` : '待设基准' }}
                      </span>
                    </div>
                    <div v-if="marker.sensor_type === 'immersion'" class="metric-item">
                      <span class="metric-label">浸水状态</span>
                      <span class="metric-value">{{ marker.water_detected ? '检测到浸水' : '未检测到浸水' }}</span>
                    </div>
                    <div class="metric-item">
                      <span class="metric-label">位置状态</span>
                      <span class="metric-value">
                        {{ marker.hasStoredPosition ? '已保存' : '临时坐标' }} / {{ isMarkerLocked(marker) ? '已锁定' : '未锁定' }}
                      </span>
                    </div>
                  </div>

                  <template v-if="accountStore.canManageSensors">
                    <div v-if="marker.sensor_type === 'ultrasonic'" class="config-section">
                      <div class="config-title">基准值设置</div>
                      <div class="config-help">
                        相对水位 = 基准测距 - 当前测距。用于把不同安装高度的测距值换算成可比较的平均水位。
                      </div>
                      <div class="config-row">
                        <el-input-number
                          v-model="panelForm.water_level_baseline"
                          :min="0"
                          :step="0.5"
                          :precision="1"
                          controls-position="right"
                          style="width: 170px"
                        />
                        <el-button text @click="panelForm.water_level_baseline = null">清除基准</el-button>
                      </div>
                    </div>

                    <div class="config-section">
                      <div class="config-title">点位布局</div>
                      <div class="config-row config-row-between">
                        <div class="lock-hint">
                          {{ isMarkerLocked(marker) ? '已锁定，拖动手柄会隐藏。' : '未锁定，可继续拖动点位微调。' }}
                        </div>
                        <el-switch v-model="panelForm.map_locked" />
                      </div>
                      <div class="config-help">
                        当前坐标：X {{ marker.x.toFixed(2) }}%，Y {{ marker.y.toFixed(2) }}%
                      </div>
                    </div>

                    <div class="panel-actions">
                      <el-button
                        v-if="marker.hasStoredPosition"
                        text
                        type="danger"
                        @click="resetSelectedPosition"
                        :loading="savingSensorId === marker.sensor_id"
                      >
                        重置点位
                      </el-button>
                      <el-button
                        v-if="!panelForm.map_locked"
                        @click="lockCurrentMarker"
                        :loading="savingSensorId === marker.sensor_id"
                      >
                        锁定当前位置
                      </el-button>
                      <el-button
                        type="primary"
                        @click="saveSelectedConfig"
                        :loading="savingSensorId === marker.sensor_id"
                      >
                        保存配置
                      </el-button>
                    </div>
                  </template>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="map-footer">
        <div class="legend">
          <span class="legend-item"><i class="legend-dot dot-normal" />正常</span>
          <span class="legend-item"><i class="legend-dot dot-warning" />预警</span>
          <span class="legend-item"><i class="legend-dot dot-danger" />危险/告警</span>
          <span class="legend-item"><i class="legend-dot dot-offline" />离线/停用</span>
        </div>
        <div class="footer-note">
          地图点位以百分比坐标保存，页面缩放或不同屏幕比例下不会发生相对偏移。
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAccountStore } from '../stores/account'
import { useSensorStore } from '../stores/sensors'
import { useWeatherStore } from '../stores/weather'
import { SHORT_DATE_TIME_FORMAT, formatUtc8DateTime } from '../utils/time'
import {
  clampPercent,
  formatMetricValue,
  getRelativeWaterLevel,
  getUltrasonicMetric,
  hasStoredMapPosition,
} from '../utils/waterLevel'

const accountStore = useAccountStore()
const sensorStore = useSensorStore()
const weatherStore = useWeatherStore()
const MAP_ZOOM_STORAGE_KEY = 'hbbwater_water_map_zoom'
const MIN_MAP_ZOOM = 0.55
const MAX_MAP_ZOOM = 1.35

const statusRows = ref([])
const statusFilter = ref('all')
const selectedSensorId = ref('')
const statusLoading = ref(false)
const pageLoading = ref(false)
const savingSensorId = ref('')
const pendingPositions = ref({})
const dragState = ref(null)
const mapStageRef = ref(null)
const mapZoom = ref(1)
const panelForm = reactive({
  water_level_baseline: null,
  map_locked: false,
})

let refreshTimer = null
let rainfallRefreshTimer = null

const statusFilterOptions = [
  { value: 'all', label: '全部状态' },
  { value: 'abnormal', label: '仅异常' },
  { value: 'normal', label: '仅正常' },
  { value: 'offline', label: '离线/停用' },
  { value: 'needs-baseline', label: '未设基准' },
]

function normalizeZoom(value) {
  const next = Number(value)
  if (!Number.isFinite(next)) {
    return 1
  }

  return Math.min(MAX_MAP_ZOOM, Math.max(MIN_MAP_ZOOM, Number(next.toFixed(2))))
}

if (typeof window !== 'undefined') {
  mapZoom.value = normalizeZoom(localStorage.getItem(MAP_ZOOM_STORAGE_KEY) || 1)
}

function getFallbackPosition(index) {
  const columns = 3
  const column = index % columns
  const row = Math.floor(index / columns)
  return {
    x: 14 + (column * 20),
    y: 18 + (row * 14),
  }
}

const statusBySensorId = computed(() => (
  statusRows.value.reduce((map, row) => {
    map[row.sensor_id] = row
    return map
  }, {})
))

const fallbackPositions = computed(() => {
  const positions = {}
  sensorStore.sensors
    .filter((sensor) => !hasStoredMapPosition(sensor))
    .slice()
    .sort((left, right) => String(left.sensor_id).localeCompare(String(right.sensor_id), 'zh-CN'))
    .forEach((sensor, index) => {
      positions[sensor.sensor_id] = getFallbackPosition(index)
    })
  return positions
})

const mergedMarkers = computed(() => sensorStore.sensors.map((sensor) => {
  const statusRow = statusBySensorId.value[sensor.sensor_id]
  const fallback = fallbackPositions.value[sensor.sensor_id] || { x: 50, y: 50 }
  const pending = pendingPositions.value[sensor.sensor_id]
  const x = pending?.x ?? (hasStoredMapPosition(sensor) ? Number(sensor.map_x) : fallback.x)
  const y = pending?.y ?? (hasStoredMapPosition(sensor) ? Number(sensor.map_y) : fallback.y)
  const status = sensor.is_active ? (statusRow?.status || 'offline') : 'inactive'
  const metric = sensor.sensor_type === 'ultrasonic'
    ? getUltrasonicMetric(sensor, statusRow?.water_level)
    : null
  const relativeWaterLevel = sensor.sensor_type === 'ultrasonic'
    ? getRelativeWaterLevel(sensor, statusRow?.water_level)
    : null

  return {
    ...sensor,
    x,
    y,
    status,
    is_online: Boolean(statusRow?.is_online),
    last_reading: statusRow?.last_reading || null,
    water_level: statusRow?.water_level ?? null,
    water_detected: statusRow?.water_detected ?? null,
    metric,
    relativeWaterLevel,
    hasStoredPosition: hasStoredMapPosition(sensor),
    needsBaseline: sensor.sensor_type === 'ultrasonic' && sensor.water_level_baseline === null,
  }
}))

const filteredMarkers = computed(() => mergedMarkers.value.filter((marker) => {
  if (statusFilter.value === 'abnormal') {
    return ['warning', 'danger', 'alarm'].includes(marker.status)
  }
  if (statusFilter.value === 'normal') {
    return marker.status === 'normal'
  }
  if (statusFilter.value === 'offline') {
    return ['offline', 'inactive'].includes(marker.status)
  }
  if (statusFilter.value === 'needs-baseline') {
    return marker.needsBaseline
  }
  return true
}))

const selectedMarker = computed(() => (
  mergedMarkers.value.find((marker) => marker.sensor_id === selectedSensorId.value) || null
))

const activeSensors = computed(() => mergedMarkers.value.filter((marker) => marker.is_active))
const onlineCount = computed(() => activeSensors.value.filter((marker) => marker.is_online).length)
const normalCount = computed(() => activeSensors.value.filter((marker) => marker.status === 'normal').length)
const abnormalCount = computed(() => activeSensors.value.filter((marker) => ['warning', 'danger', 'alarm'].includes(marker.status)).length)
const offlineCount = computed(() => activeSensors.value.filter((marker) => marker.status === 'offline').length)
const unplacedCount = computed(() => mergedMarkers.value.filter((marker) => !marker.hasStoredPosition).length)
const unlockedCount = computed(() => mergedMarkers.value.filter((marker) => marker.hasStoredPosition && !marker.map_locked).length)

const relativeWaterSamples = computed(() => activeSensors.value
  .filter((marker) => marker.is_online && marker.relativeWaterLevel !== null)
  .map((marker) => marker.relativeWaterLevel))

const averageSampleCount = computed(() => relativeWaterSamples.value.length)
const zoomPercent = computed(() => Math.round(mapZoom.value * 100))
const markerScale = computed(() => Number(Math.max(0.82, Math.min(1.08, mapZoom.value)).toFixed(2)))
const mapCanvasStyle = computed(() => ({
  width: `${Math.round(mapZoom.value * 100)}%`,
  '--marker-scale': markerScale.value,
}))
const averageRelativeWaterLevel = computed(() => {
  if (!relativeWaterSamples.value.length) {
    return null
  }
  const total = relativeWaterSamples.value.reduce((sum, value) => sum + value, 0)
  return total / relativeWaterSamples.value.length
})

const selectedRainfallStation = computed(() => weatherStore.selectedStation)

watch(mapZoom, (value) => {
  const normalized = normalizeZoom(value)
  if (normalized !== value) {
    mapZoom.value = normalized
    return
  }

  if (typeof window !== 'undefined') {
    localStorage.setItem(MAP_ZOOM_STORAGE_KEY, String(normalized))
  }
})

function syncPanelForm(marker) {
  panelForm.water_level_baseline = marker?.sensor_type === 'ultrasonic' && marker?.water_level_baseline !== null
    ? Number(marker.water_level_baseline)
    : null
  panelForm.map_locked = Boolean(marker?.map_locked)
}

function toggleMarkerPanel(marker) {
  if (selectedSensorId.value === marker.sensor_id) {
    closePanel()
    return
  }

  selectedSensorId.value = marker.sensor_id
  syncPanelForm(marker)
}

function closePanel() {
  selectedSensorId.value = ''
}

function getSensorTypeLabel(sensorType) {
  return sensorType === 'ultrasonic' ? '超声波' : '浸水'
}

function getStatusText(status) {
  const map = {
    normal: '正常',
    warning: '预警',
    danger: '危险',
    alarm: '告警',
    offline: '离线',
    inactive: '停用',
  }
  return map[status] || status
}

function getStatusTagType(status) {
  const map = {
    normal: 'success',
    warning: 'warning',
    danger: 'danger',
    alarm: 'danger',
    offline: 'info',
    inactive: 'info',
  }
  return map[status] || 'info'
}

function getMarkerReadingText(marker) {
  if (marker.sensor_type === 'immersion') {
    if (marker.status === 'offline' || marker.status === 'inactive') {
      return '暂无上报'
    }
    return marker.water_detected ? '浸水' : '正常'
  }

  if (marker.metric?.value === null) {
    return '暂无数据'
  }

  const value = formatMetricValue(marker.metric.value)
  return `${marker.metric.mode === 'relative' ? '水位' : '测距'} ${value} cm`
}

function formatLastReading(value) {
  return formatUtc8DateTime(value, SHORT_DATE_TIME_FORMAT, '暂无上报')
}

function formatRainfall(value) {
  if (value === null || value === undefined) return '-- mm'
  return `${Number(value).toFixed(1)} mm`
}

function getRainfallMapStatus(station) {
  if (station.last_error) return station.last_error
  if (station.is_stale) return '雨量数据已过期'
  if (station.current_actual_time) return `实况时次 ${formatLastReading(station.current_actual_time)}`
  return '等待雨量采集'
}

function getMarkerClasses(marker) {
  return [
    `status-${marker.status}`,
    {
      'is-selected': selectedSensorId.value === marker.sensor_id,
      'is-dragging': dragState.value?.sensorId === marker.sensor_id,
      'align-right': marker.x > 72,
      'align-bottom': marker.y > 70,
    },
  ]
}

function getPanelClasses(marker) {
  return {
    'panel-right': marker.x > 72,
    'panel-up': marker.y > 70,
  }
}

function getMarkerStyle(marker) {
  return {
    left: `${marker.x}%`,
    top: `${marker.y}%`,
    zIndex: selectedSensorId.value === marker.sensor_id ? 50 : 10,
  }
}

function isMarkerLocked(marker) {
  if (selectedSensorId.value === marker.sensor_id) {
    return Boolean(panelForm.map_locked)
  }

  return Boolean(marker.map_locked)
}

function setMapZoom(value) {
  mapZoom.value = normalizeZoom(value)
}

function changeZoom(delta) {
  setMapZoom(mapZoom.value + delta)
}

function resetZoom() {
  setMapZoom(1)
}

async function refreshStatuses({ quiet = false } = {}) {
  statusLoading.value = true
  try {
    statusRows.value = await sensorStore.fetchAllSensorStatus()
  } catch (error) {
    if (!quiet) {
      ElMessage.error(error.response?.data?.detail || '刷新地图状态失败')
    }
  } finally {
    statusLoading.value = false
  }
}

async function refreshAll() {
  pageLoading.value = true
  try {
    await sensorStore.fetchSensors()
    weatherStore.fetchRainfallSummary().catch(() => {})
    await refreshStatuses()
    if (selectedMarker.value) {
      syncPanelForm(selectedMarker.value)
    } else if (selectedSensorId.value) {
      closePanel()
    }
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '加载水位地图失败')
  } finally {
    pageLoading.value = false
  }
}

function updatePendingPosition(sensorId, position) {
  pendingPositions.value = {
    ...pendingPositions.value,
    [sensorId]: position,
  }
}

function clearPendingPosition(sensorId) {
  if (!(sensorId in pendingPositions.value)) {
    return
  }

  const next = { ...pendingPositions.value }
  delete next[sensorId]
  pendingPositions.value = next
}

function startDrag(event, marker) {
  if (!accountStore.canManageSensors || isMarkerLocked(marker) || !mapStageRef.value) {
    return
  }

  selectedSensorId.value = marker.sensor_id
  syncPanelForm(marker)
  dragState.value = {
    sensorId: marker.sensor_id,
    startClientX: event.clientX,
    startClientY: event.clientY,
    startX: marker.x,
    startY: marker.y,
  }
  updatePendingPosition(marker.sensor_id, { x: marker.x, y: marker.y })
}

function handlePointerMove(event) {
  if (!dragState.value || !mapStageRef.value) {
    return
  }

  const rect = mapStageRef.value.getBoundingClientRect()
  if (!rect.width || !rect.height) {
    return
  }

  const deltaX = ((event.clientX - dragState.value.startClientX) / rect.width) * 100
  const deltaY = ((event.clientY - dragState.value.startClientY) / rect.height) * 100
  updatePendingPosition(dragState.value.sensorId, {
    x: clampPercent(dragState.value.startX + deltaX),
    y: clampPercent(dragState.value.startY + deltaY),
  })
}

async function handlePointerUp() {
  if (!dragState.value) {
    return
  }

  const { sensorId } = dragState.value
  const nextPosition = pendingPositions.value[sensorId]
  dragState.value = null

  if (!nextPosition) {
    return
  }

  try {
    await sensorStore.updateSensor(sensorId, {
      map_x: Number(nextPosition.x.toFixed(3)),
      map_y: Number(nextPosition.y.toFixed(3)),
    })
    clearPendingPosition(sensorId)
  } catch (error) {
    clearPendingPosition(sensorId)
    ElMessage.error(error.response?.data?.detail || `保存 ${sensorId} 点位位置失败`)
  }
}

async function saveSelectedConfig() {
  if (!accountStore.canManageSensors || !selectedMarker.value) {
    return
  }

  const marker = selectedMarker.value
  const payload = {
    map_x: Number(marker.x.toFixed(3)),
    map_y: Number(marker.y.toFixed(3)),
    map_locked: Boolean(panelForm.map_locked),
  }

  if (marker.sensor_type === 'ultrasonic') {
    payload.water_level_baseline = panelForm.water_level_baseline === null || panelForm.water_level_baseline === undefined
      ? null
      : Number(panelForm.water_level_baseline)
  }

  savingSensorId.value = marker.sensor_id
  try {
    await sensorStore.updateSensor(marker.sensor_id, payload)
    clearPendingPosition(marker.sensor_id)
    syncPanelForm(selectedMarker.value)
    ElMessage.success('点位配置已保存')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '保存点位配置失败')
  } finally {
    savingSensorId.value = ''
  }
}

async function lockCurrentMarker() {
  panelForm.map_locked = true
  await saveSelectedConfig()
}

async function resetSelectedPosition() {
  if (!accountStore.canManageSensors || !selectedMarker.value) {
    return
  }

  const marker = selectedMarker.value

  try {
    await ElMessageBox.confirm(
      `确定重置 ${marker.sensor_id} 的地图点位吗？重置后会回到临时坐标，需要重新拖动并保存。`,
      '重置点位',
      { type: 'warning' },
    )
  } catch (error) {
    if (error === 'cancel' || error === 'close') {
      return
    }
    throw error
  }

  savingSensorId.value = marker.sensor_id
  try {
    await sensorStore.updateSensor(marker.sensor_id, {
      map_x: null,
      map_y: null,
      map_locked: false,
    })
    clearPendingPosition(marker.sensor_id)
    panelForm.map_locked = false
    syncPanelForm(selectedMarker.value)
    ElMessage.success('点位已重置，请重新拖动布置')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '重置点位失败')
  } finally {
    savingSensorId.value = ''
  }
}

onMounted(async () => {
  window.addEventListener('pointermove', handlePointerMove)
  window.addEventListener('pointerup', handlePointerUp)
  window.addEventListener('pointercancel', handlePointerUp)

  await refreshAll()
  refreshTimer = setInterval(() => {
    refreshStatuses({ quiet: true })
  }, 15000)
  rainfallRefreshTimer = setInterval(() => {
    weatherStore.fetchRainfallSummary().catch(() => {})
  }, 60000)
})

onUnmounted(() => {
  window.removeEventListener('pointermove', handlePointerMove)
  window.removeEventListener('pointerup', handlePointerUp)
  window.removeEventListener('pointercancel', handlePointerUp)

  if (refreshTimer) {
    clearInterval(refreshTimer)
  }
  if (rainfallRefreshTimer) {
    clearInterval(rainfallRefreshTimer)
  }
})
</script>

<style scoped>
.water-map-page {
  display: grid;
  gap: 18px;
}

.summary-row {
  margin-bottom: 0;
}

.summary-card {
  min-height: 130px;
  border: none;
  overflow: hidden;
}

.summary-card :deep(.el-card__body) {
  display: flex;
  gap: 14px;
  align-items: center;
  padding: 20px;
}

.summary-icon {
  width: 54px;
  height: 54px;
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28px;
  color: #fff;
  box-shadow: 0 14px 26px rgba(17, 24, 39, 0.16);
}

.card-total .summary-icon {
  background: linear-gradient(135deg, #2f80ed 0%, #56ccf2 100%);
}

.card-normal .summary-icon {
  background: linear-gradient(135deg, #1f9d72 0%, #45c98f 100%);
}

.card-alert .summary-icon {
  background: linear-gradient(135deg, #f97316 0%, #fb7185 100%);
}

.card-water .summary-icon {
  background: linear-gradient(135deg, #0f766e 0%, #2dd4bf 100%);
}

.summary-content {
  flex: 1;
}

.summary-label {
  color: #64748b;
  font-size: 13px;
}

.summary-value {
  margin-top: 8px;
  color: #0f172a;
  font-size: 30px;
  font-weight: 700;
  line-height: 1;
}

.summary-unit {
  margin-left: 4px;
  font-size: 14px;
  font-weight: 500;
  color: #64748b;
}

.summary-meta {
  margin-top: 10px;
  color: #64748b;
  font-size: 12px;
}

.map-card {
  border: none;
}

.map-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.map-title {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
}

.map-subtitle {
  margin-top: 6px;
  color: #64748b;
  font-size: 13px;
  line-height: 1.5;
}

.map-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.rainfall-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
  padding: 12px 14px;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  background: #f0f7ff;
}

.rainfall-strip.is-backup {
  border-color: #d8dce6;
  background: #f6f8fb;
}

.rainfall-strip-main {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.rainfall-strip-icon {
  width: 38px;
  height: 38px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  color: #fff;
  background: #2563eb;
}

.rainfall-strip-title {
  color: #0f172a;
  font-size: 14px;
  font-weight: 700;
}

.rainfall-strip-title span {
  margin-left: 8px;
  color: #64748b;
  font-size: 12px;
  font-weight: 500;
}

.rainfall-strip-meta,
.rainfall-strip-status {
  margin-top: 4px;
  color: #475569;
  font-size: 12px;
  line-height: 1.5;
}

.rainfall-strip-status {
  margin-top: 0;
  text-align: right;
  flex: 0 0 auto;
}

.zoom-controls {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.84);
  border: 1px solid #dbe5f0;
  backdrop-filter: blur(10px);
}

.zoom-slider {
  width: 130px;
}

.zoom-value {
  min-width: 48px;
  color: #334155;
  font-size: 12px;
  font-weight: 700;
}

.map-notices {
  display: grid;
  gap: 10px;
  margin-bottom: 16px;
}

.map-stage-shell {
  border-radius: 22px;
  overflow: visible;
  border: 1px solid #dbe5f0;
  background:
    radial-gradient(circle at top left, rgba(56, 189, 248, 0.12), transparent 28%),
    linear-gradient(180deg, #e2ecf8 0%, #eff5fb 100%);
  padding: 16px;
}

.map-viewport {
  overflow: auto;
  padding: 4px 2px 22px;
}

.map-canvas {
  width: 100%;
  min-width: 55%;
  margin: 0 auto;
  --marker-scale: 1;
}

.map-stage {
  position: relative;
  width: 100%;
}

.map-image {
  display: block;
  width: 100%;
  height: auto;
  border-radius: 18px;
  user-select: none;
  pointer-events: none;
  box-shadow: 0 18px 38px rgba(15, 23, 42, 0.16);
}

.sensor-marker {
  position: absolute;
  transform: translate(-50%, -50%);
}

.sensor-dot,
.drag-handle,
.sensor-label,
.panel-close {
  border: none;
  cursor: pointer;
}

.sensor-dot {
  position: relative;
  width: calc(22px * var(--marker-scale));
  height: calc(22px * var(--marker-scale));
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.88);
  box-shadow:
    0 0 0 calc(6px * var(--marker-scale)) rgba(59, 130, 246, 0.18),
    0 8px 24px rgba(15, 23, 42, 0.24);
}

.sensor-dot::before,
.sensor-dot::after {
  content: '';
  position: absolute;
  inset: 50%;
  border-radius: 999px;
  transform: translate(-50%, -50%);
  border: 2px solid currentColor;
  opacity: 0.26;
}

.sensor-dot::before {
  width: calc(28px * var(--marker-scale));
  height: calc(28px * var(--marker-scale));
}

.sensor-dot::after {
  width: calc(38px * var(--marker-scale));
  height: calc(38px * var(--marker-scale));
}

.sensor-dot-core {
  display: block;
  width: calc(12px * var(--marker-scale));
  height: calc(12px * var(--marker-scale));
  margin: calc(5px * var(--marker-scale));
  border-radius: 999px;
  background: currentColor;
}

.drag-handle {
  position: absolute;
  left: calc(-36px * var(--marker-scale));
  top: calc(-4px * var(--marker-scale));
  width: calc(26px * var(--marker-scale));
  height: calc(26px * var(--marker-scale));
  border-radius: calc(10px * var(--marker-scale));
  background: rgba(15, 23, 42, 0.78);
  color: #fff;
  touch-action: none;
}

.drag-text {
  font-size: calc(9px * var(--marker-scale));
  font-weight: 700;
  letter-spacing: 0.03em;
}

.sensor-label {
  position: absolute;
  left: calc(18px * var(--marker-scale));
  top: 50%;
  transform: translateY(-50%);
  min-width: calc(112px * var(--marker-scale));
  max-width: calc(164px * var(--marker-scale));
  padding: calc(9px * var(--marker-scale)) calc(12px * var(--marker-scale));
  border-radius: calc(14px * var(--marker-scale));
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 16px 28px rgba(15, 23, 42, 0.18);
  color: #0f172a;
  text-align: left;
}

.align-right .sensor-label {
  left: auto;
  right: calc(18px * var(--marker-scale));
}

.sensor-id {
  display: block;
  font-size: calc(12px * var(--marker-scale));
  font-weight: 700;
  letter-spacing: 0.02em;
}

.sensor-reading {
  display: block;
  margin-top: calc(4px * var(--marker-scale));
  color: #2563eb;
  font-size: calc(13px * var(--marker-scale));
  font-weight: 600;
}

.sensor-hint {
  display: inline-flex;
  margin-top: calc(6px * var(--marker-scale));
  padding: calc(2px * var(--marker-scale)) calc(8px * var(--marker-scale));
  border-radius: 999px;
  background: #eff6ff;
  color: #475569;
  font-size: calc(11px * var(--marker-scale));
}

.sensor-panel {
  position: absolute;
  left: calc(18px * var(--marker-scale));
  top: calc(28px * var(--marker-scale));
  width: 310px;
  padding: 16px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 28px 48px rgba(15, 23, 42, 0.22);
}

.panel-right {
  left: auto;
  right: calc(18px * var(--marker-scale));
}

.panel-up {
  top: auto;
  bottom: calc(28px * var(--marker-scale));
}

.sensor-panel-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
}

.panel-title-row {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.panel-title {
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
}

.panel-subtitle {
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
}

.panel-close {
  width: 28px;
  height: 28px;
  border-radius: 999px;
  background: #f8fafc;
  color: #64748b;
}

.sensor-panel-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}

.metric-item {
  padding: 10px 12px;
  border-radius: 14px;
  background: #f8fafc;
}

.metric-label {
  display: block;
  color: #64748b;
  font-size: 11px;
}

.metric-value {
  display: block;
  margin-top: 4px;
  color: #0f172a;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.4;
}

.config-section {
  margin-top: 14px;
  padding: 12px;
  border-radius: 14px;
  background: #f8fafc;
}

.config-title {
  color: #0f172a;
  font-size: 13px;
  font-weight: 700;
}

.config-help {
  margin-top: 6px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}

.config-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
}

.config-row-between {
  justify-content: space-between;
}

.lock-hint {
  color: #334155;
  font-size: 12px;
  line-height: 1.4;
}

.panel-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 14px;
}

.map-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-top: 16px;
  flex-wrap: wrap;
}

.legend {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #475569;
  font-size: 12px;
}

.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  display: inline-block;
}

.footer-note {
  color: #64748b;
  font-size: 12px;
}

.dot-normal,
.status-normal,
.status-normal .sensor-dot {
  color: #16a34a;
}

.dot-warning,
.status-warning,
.status-warning .sensor-dot {
  color: #f59e0b;
}

.dot-danger,
.status-danger,
.status-alarm,
.status-danger .sensor-dot,
.status-alarm .sensor-dot {
  color: #ef4444;
}

.dot-offline,
.status-offline,
.status-inactive,
.status-offline .sensor-dot,
.status-inactive .sensor-dot {
  color: #64748b;
}

.status-inactive .sensor-label,
.status-offline .sensor-label {
  background: rgba(248, 250, 252, 0.96);
}

.is-selected .sensor-label,
.is-selected .sensor-dot {
  box-shadow:
    0 0 0 7px rgba(59, 130, 246, 0.18),
    0 18px 30px rgba(15, 23, 42, 0.22);
}

.is-dragging .sensor-label {
  cursor: grabbing;
}

@media (max-width: 1024px) {
  .map-card-header {
    flex-direction: column;
    align-items: stretch;
  }

  .map-toolbar {
    justify-content: space-between;
  }

  .sensor-panel {
    width: 280px;
  }
}

@media (max-width: 768px) {
  .summary-card {
    min-height: 116px;
  }

  .summary-card :deep(.el-card__body) {
    padding: 16px;
  }

  .summary-value {
    font-size: 24px;
  }

  .map-stage-shell {
    padding: 10px;
  }

  .map-viewport {
    padding-bottom: 16px;
  }

  .zoom-controls {
    width: 100%;
    justify-content: space-between;
  }

  .rainfall-strip {
    align-items: flex-start;
    flex-direction: column;
  }

  .rainfall-strip-status {
    text-align: left;
  }

  .zoom-slider {
    flex: 1;
    min-width: 88px;
  }

  .sensor-label {
    min-width: 96px;
    max-width: 132px;
    padding: 8px 10px;
  }

  .sensor-reading {
    font-size: 12px;
  }

  .sensor-panel {
    left: 0;
    right: auto;
    top: 34px;
    width: min(84vw, 280px);
  }

  .panel-right {
    right: 0;
    left: auto;
  }

  .sensor-panel-grid {
    grid-template-columns: 1fr;
  }
}
</style>
