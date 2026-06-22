import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import axios from 'axios'

const numericFields = [
  'longitude',
  'latitude',
  'current_actual_mm',
  'stale_after_seconds'
]

const rainfallNumericFields = [
  'rainfall_mm',
  'revision_count'
]

const rainfallRevisionNumericFields = [
  'old_rainfall_mm',
  'new_rainfall_mm'
]

function toNumber(value) {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function normalizeStation(station) {
  if (!station) return station
  const normalized = { ...station }
  numericFields.forEach((field) => {
    if (field in normalized) {
      normalized[field] = toNumber(normalized[field])
    }
  })
  if (normalized.forecast_totals) {
    normalized.forecast_totals = Object.entries(normalized.forecast_totals).reduce((map, [key, value]) => {
      map[key] = toNumber(value)
      return map
    }, {})
  }
  return normalized
}

function normalizeSummary(summary) {
  if (!summary) return summary
  return {
    ...summary,
    stale_after_seconds: toNumber(summary.stale_after_seconds),
    stations: (summary.stations || []).map(normalizeStation),
  }
}

function normalizeRainfallRecord(record) {
  if (!record) return record
  return rainfallNumericFields.reduce((normalized, field) => {
    if (field in normalized) {
      normalized[field] = toNumber(normalized[field])
    }
    return normalized
  }, { ...record })
}

function normalizeRainfallRevision(revision) {
  if (!revision) return revision
  return rainfallRevisionNumericFields.reduce((normalized, field) => {
    if (field in normalized) {
      normalized[field] = toNumber(normalized[field])
    }
    return normalized
  }, { ...revision })
}

export const useWeatherStore = defineStore('weather', () => {
  const rainfallSummary = ref(null)
  const stations = ref([])
  const loading = ref(false)
  const error = ref(null)
  const lastFetch = ref(null)

  const selectedStation = computed(() => {
    if (!rainfallSummary.value?.selected_station_id) return null
    return rainfallSummary.value.stations.find(
      (station) => station.station_id === rainfallSummary.value.selected_station_id
    ) || null
  })

  const primaryStation = computed(() => (
    rainfallSummary.value?.stations.find((station) => station.role === 'primary') || null
  ))

  const backupStation = computed(() => (
    rainfallSummary.value?.stations.find((station) => station.role === 'backup') || null
  ))

  async function fetchRainfallSummary() {
    loading.value = true
    error.value = null
    try {
      const response = await axios.get('/api/weather/rainfall/summary')
      rainfallSummary.value = normalizeSummary(response.data)
      lastFetch.value = new Date()
      return rainfallSummary.value
    } catch (err) {
      error.value = err.message
      console.error('Failed to fetch rainfall summary:', err)
      throw err
    } finally {
      loading.value = false
    }
  }

  async function fetchStations() {
    const response = await axios.get('/api/weather/rainfall/stations')
    stations.value = response.data.map(normalizeStation)
    return stations.value
  }

  async function fetchHistory(params = {}) {
    const response = await axios.get('/api/weather/rainfall/history', { params })
    return {
      ...response.data,
      items: (response.data.items || []).map(normalizeRainfallRecord),
    }
  }

  async function fetchRevisions(params = {}) {
    const response = await axios.get('/api/weather/rainfall/revisions', { params })
    return {
      ...response.data,
      items: (response.data.items || []).map(normalizeRainfallRevision),
    }
  }

  return {
    rainfallSummary,
    stations,
    loading,
    error,
    lastFetch,
    selectedStation,
    primaryStation,
    backupStation,
    fetchRainfallSummary,
    fetchStations,
    fetchHistory,
    fetchRevisions,
  }
})
