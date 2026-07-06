import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import axios from 'axios'

function toNumber(value) {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function normalizeProfile(profile) {
  if (!profile) return profile
  return {
    ...profile,
    horizon_hours: toNumber(profile.horizon_hours) || 6,
    warning_rise_mm: toNumber(profile.warning_rise_mm),
    critical_rise_mm: toNumber(profile.critical_rise_mm),
  }
}

function normalizeResult(result) {
  if (!result) return result
  return {
    ...result,
    predicted_free_rise_mm: toNumber(result.predicted_free_rise_mm),
    predicted_observed_rise_mm: toNumber(result.predicted_observed_rise_mm),
    projected_distance_cm: toNumber(result.projected_distance_cm),
    latest_distance_cm: toNumber(result.latest_distance_cm),
    confidence: toNumber(result.confidence),
  }
}

function normalizeRun(run) {
  if (!run) return run
  return {
    ...run,
    results: (run.results || []).map(normalizeResult),
  }
}

export const useForecastAlertStore = defineStore('forecastAlerts', () => {
  const config = ref(null)
  const latestRun = ref(null)
  const runs = ref([])
  const totalRuns = ref(0)
  const loading = ref(false)
  const saving = ref(false)
  const evaluating = ref(false)
  const error = ref(null)

  const profiles = computed(() => config.value?.profiles || [])
  const globalConfig = computed(() => config.value?.global_config || {
    enabled: false,
    cooldown_minutes: 120,
    default_horizon_hours: 6,
    model_params: {},
  })
  const latestResults = computed(() => latestRun.value?.results || [])

  async function fetchConfig() {
    loading.value = true
    error.value = null
    try {
      const { data } = await axios.get('/api/forecast-alerts/config')
      config.value = {
        ...data,
        profiles: (data.profiles || []).map(normalizeProfile),
      }
      return config.value
    } catch (err) {
      error.value = err.response?.data?.detail || err.message
      throw err
    } finally {
      loading.value = false
    }
  }

  async function saveConfig(payload) {
    saving.value = true
    error.value = null
    try {
      const { data } = await axios.post('/api/forecast-alerts/config', payload)
      config.value = {
        ...data,
        profiles: (data.profiles || []).map(normalizeProfile),
      }
      return config.value
    } catch (err) {
      error.value = err.response?.data?.detail || err.message
      throw err
    } finally {
      saving.value = false
    }
  }

  async function evaluate(payload = { dry_run: true }) {
    evaluating.value = true
    error.value = null
    try {
      const { data } = await axios.post('/api/forecast-alerts/evaluate', payload)
      latestRun.value = normalizeRun(data)
      return latestRun.value
    } catch (err) {
      error.value = err.response?.data?.detail || err.message
      throw err
    } finally {
      evaluating.value = false
    }
  }

  async function fetchLatest() {
    loading.value = true
    error.value = null
    try {
      const { data } = await axios.get('/api/forecast-alerts/latest')
      latestRun.value = normalizeRun(data)
      return latestRun.value
    } catch (err) {
      error.value = err.response?.data?.detail || err.message
      throw err
    } finally {
      loading.value = false
    }
  }

  async function fetchRuns(params = {}) {
    loading.value = true
    error.value = null
    try {
      const { data } = await axios.get('/api/forecast-alerts/runs', { params })
      runs.value = (data.items || []).map(normalizeRun)
      totalRuns.value = data.total || 0
      return data
    } catch (err) {
      error.value = err.response?.data?.detail || err.message
      throw err
    } finally {
      loading.value = false
    }
  }

  return {
    config,
    latestRun,
    runs,
    totalRuns,
    loading,
    saving,
    evaluating,
    error,
    profiles,
    globalConfig,
    latestResults,
    fetchConfig,
    saveConfig,
    evaluate,
    fetchLatest,
    fetchRuns,
  }
})
