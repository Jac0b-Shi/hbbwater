<template>
  <div class="alerts-page">
    <el-card shadow="hover">
      <template #header>
        <div class="page-header">
          <h2>告警管理</h2>
          <div class="header-actions">
            <el-tag v-if="!accountStore.canResolveAlerts" effect="plain" type="info">当前账号仅可查看</el-tag>
            <el-radio-group v-if="accountStore.canResolveAlerts" v-model="alertMode" size="small">
              <el-radio-button label="realtime">实时告警</el-radio-button>
              <el-radio-button label="forecast">预报告警</el-radio-button>
            </el-radio-group>
            <el-radio-group v-if="alertMode === 'realtime'" v-model="filterStatus" size="small">
              <el-radio-button label="all">全部</el-radio-button>
              <el-radio-button label="active">未处理</el-radio-button>
              <el-radio-button label="resolved">已处理</el-radio-button>
            </el-radio-group>
            <el-button type="primary" size="small" @click="refreshCurrent">
              <el-icon><Refresh /></el-icon>刷新
            </el-button>
          </div>
        </div>
      </template>

      <template v-if="alertMode === 'realtime'">
        <!-- Alert Stats -->
        <el-row :gutter="20" class="stats-row">
          <el-col :xs="12" :sm="6">
            <div class="stat-box">
              <div class="stat-number critical">{{ alertStore.criticalAlerts.length }}</div>
              <div class="stat-label">紧急告警</div>
            </div>
          </el-col>
          <el-col :xs="12" :sm="6">
            <div class="stat-box">
              <div class="stat-number high">{{ alertStore.highAlerts.length }}</div>
              <div class="stat-label">高优先级</div>
            </div>
          </el-col>
          <el-col :xs="12" :sm="6">
            <div class="stat-box">
              <div class="stat-number medium">{{ alertStore.activeAlerts.filter(a => a.severity === 'medium').length }}</div>
              <div class="stat-label">中优先级</div>
            </div>
          </el-col>
          <el-col :xs="12" :sm="6">
            <div class="stat-box">
              <div class="stat-number total">{{ alertStore.unresolvedCount }}</div>
              <div class="stat-label">未处理总数</div>
            </div>
          </el-col>
        </el-row>

        <!-- Alerts Table -->
        <el-table
          v-if="!isMobile"
          v-loading="alertStore.loading"
          :data="filteredAlerts"
          stripe
          style="width: 100%"
        >
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="alert-detail">
              <p><strong>详细信息:</strong></p>
              <pre>{{ JSON.stringify(row.details, null, 2) }}</pre>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column prop="created_at" label="时间" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="severity" label="级别" width="100">
          <template #default="{ row }">
            <el-tag :type="getSeverityType(row.severity)">
              {{ getSeverityText(row.severity) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="alert_type" label="类型" width="150">
          <template #default="{ row }">
            <el-tag effect="plain">{{ getAlertTypeText(row.alert_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="sensor_id" label="传感器" width="150" />
        <el-table-column prop="message" label="消息" show-overflow-tooltip />
        <el-table-column prop="is_resolved" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_resolved ? 'success' : 'danger'">
              {{ row.is_resolved ? '已处理' : '未处理' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="!row.is_resolved && accountStore.canResolveAlerts"
              type="primary" 
              size="small" 
              @click="resolveAlert(row)"
            >
              处理
            </el-button>
            <span v-else-if="!row.is_resolved" class="resolved-info">只读</span>
            <span v-else class="resolved-info">
              处理人: {{ row.resolved_by }}
            </span>
          </template>
        </el-table-column>
        </el-table>
        <div v-else v-loading="alertStore.loading" class="alert-card-list">
          <article v-for="alert in filteredAlerts" :key="alert.id" class="alert-card" :class="`severity-${alert.severity}`">
          <div class="alert-card-head">
            <div class="alert-card-tags">
              <el-tag :type="getSeverityType(alert.severity)">{{ getSeverityText(alert.severity) }}</el-tag>
              <el-tag effect="plain">{{ getAlertTypeText(alert.alert_type) }}</el-tag>
            </div>
            <el-tag size="small" :type="alert.is_resolved ? 'success' : 'danger'">
              {{ alert.is_resolved ? '已处理' : '未处理' }}
            </el-tag>
          </div>
          <div class="alert-card-message">{{ alert.message }}</div>
          <dl class="alert-card-meta">
            <div><dt>传感器</dt><dd>{{ alert.sensor_id }}</dd></div>
            <div><dt>时间</dt><dd>{{ formatTime(alert.created_at) }}</dd></div>
            <div v-if="alert.is_resolved"><dt>处理人</dt><dd>{{ alert.resolved_by || '-' }}</dd></div>
          </dl>
          <el-collapse v-if="alert.details" class="alert-details-collapse">
            <el-collapse-item title="查看详细信息" name="details">
              <pre>{{ JSON.stringify(alert.details, null, 2) }}</pre>
            </el-collapse-item>
          </el-collapse>
          <el-button
            v-if="!alert.is_resolved && accountStore.canResolveAlerts"
            type="primary"
            class="mobile-primary-action"
            @click="resolveAlert(alert)"
          >
            处理告警
          </el-button>
          </article>
          <el-empty v-if="filteredAlerts.length === 0" description="暂无告警" />
        </div>
      </template>

      <template v-else>
        <div class="forecast-toolbar">
          <div class="forecast-run-summary">
            <el-tag :type="forecastAlertStore.latestRun?.dry_run ? 'info' : 'success'">
              {{ forecastAlertStore.latestRun?.dry_run ? '演练结果' : '正式评估' }}
            </el-tag>
            <span>{{ forecastAlertStore.latestRun ? `评估 ${formatTime(forecastAlertStore.latestRun.created_at)}` : '暂无预报评估结果' }}</span>
          </div>
          <div class="forecast-actions">
            <el-button :loading="forecastAlertStore.evaluating" @click="runForecastDryRun">Dry-run 评估</el-button>
            <el-button type="primary" :loading="forecastAlertStore.loading" @click="refreshForecast">
              <el-icon><Refresh /></el-icon>刷新预报
            </el-button>
          </div>
        </div>

        <el-table
          v-if="!isMobile"
          v-loading="forecastAlertStore.loading || forecastAlertStore.evaluating"
          :data="forecastResults"
          stripe
          style="width: 100%"
        >
          <el-table-column type="expand">
            <template #default="{ row }">
              <div class="alert-detail">
                <p><strong>预测详情:</strong></p>
                <pre>{{ JSON.stringify(row, null, 2) }}</pre>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="risk_level" label="风险" width="100">
            <template #default="{ row }">
              <el-tag :type="getRiskType(row.risk_level)">{{ getRiskText(row.risk_level) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="sensor_id" label="传感器" width="150" />
          <el-table-column prop="station_id" label="雨量站" width="110" />
          <el-table-column label="未来窗口" width="100">
            <template #default="{ row }">{{ row.horizon_hours }}h</template>
          </el-table-column>
          <el-table-column label="峰值时间" width="180">
            <template #default="{ row }">{{ formatTime(row.peak_time) }}</template>
          </el-table-column>
          <el-table-column label="无泵上涨" width="120">
            <template #default="{ row }">{{ formatMm(row.predicted_free_rise_mm) }}</template>
          </el-table-column>
          <el-table-column label="泵后上涨" width="120">
            <template #default="{ row }">{{ formatMm(row.predicted_observed_rise_mm) }}</template>
          </el-table-column>
          <el-table-column label="预计测距" width="120">
            <template #default="{ row }">{{ formatCm(row.projected_distance_cm) }}</template>
          </el-table-column>
          <el-table-column label="通知" width="100">
            <template #default="{ row }">
              <el-tag :type="row.notification_sent ? 'success' : (row.should_notify ? 'warning' : 'info')">
                {{ row.notification_sent ? '已发送' : (row.should_notify ? '待通知' : '不通知') }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="置信度" width="100">
            <template #default="{ row }">{{ formatPercent(row.confidence) }}</template>
          </el-table-column>
        </el-table>

        <div v-else v-loading="forecastAlertStore.loading || forecastAlertStore.evaluating" class="alert-card-list">
          <article v-for="result in forecastResults" :key="result.id" class="alert-card" :class="`severity-${forecastSeverity(result.risk_level)}`">
            <div class="alert-card-head">
              <div class="alert-card-tags">
                <el-tag :type="getRiskType(result.risk_level)">{{ getRiskText(result.risk_level) }}</el-tag>
                <el-tag effect="plain">{{ result.station_id || '无雨量站' }}</el-tag>
              </div>
              <el-tag size="small" :type="result.notification_sent ? 'success' : 'info'">
                {{ result.notification_sent ? '已通知' : '未通知' }}
              </el-tag>
            </div>
            <div class="alert-card-message">{{ result.decision_reason || '暂无预测说明' }}</div>
            <dl class="alert-card-meta">
              <div><dt>传感器</dt><dd>{{ result.sensor_id }}</dd></div>
              <div><dt>峰值</dt><dd>{{ formatTime(result.peak_time) }}</dd></div>
              <div><dt>无泵上涨</dt><dd>{{ formatMm(result.predicted_free_rise_mm) }}</dd></div>
              <div><dt>预计测距</dt><dd>{{ formatCm(result.projected_distance_cm) }}</dd></div>
            </dl>
          </article>
          <el-empty v-if="forecastResults.length === 0" description="暂无预报评估结果" />
        </div>
      </template>
    </el-card>

    <!-- Resolve Dialog -->
    <el-dialog v-model="showResolveDialog" title="处理告警" :width="dialogWidth">
      <el-form :model="resolveForm" :label-position="isMobile ? 'top' : 'right'">
        <el-form-item label="处理人">
          <el-input v-model="resolveForm.resolved_by" placeholder="请输入处理人姓名" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showResolveDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmResolve">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useAccountStore } from '../stores/account'
import { useAlertStore } from '../stores/alerts'
import { useForecastAlertStore } from '../stores/forecastAlerts'
import { formatUtc8DateTime } from '../utils/time'
import { useResponsive } from '../composables/useResponsive'

const accountStore = useAccountStore()
const alertStore = useAlertStore()
const forecastAlertStore = useForecastAlertStore()
const { isMobile } = useResponsive()
const dialogWidth = computed(() => isMobile.value ? 'calc(100vw - 24px)' : '400px')

const alertMode = ref('realtime')
const filterStatus = ref('active')
const showResolveDialog = ref(false)
const currentAlert = ref(null)
const resolveForm = ref({ resolved_by: '' })
let refreshTimer = null

const filteredAlerts = computed(() => {
  if (filterStatus.value === 'active') {
    return alertStore.activeAlerts
  } else if (filterStatus.value === 'resolved') {
    return alertStore.alerts.filter(a => a.is_resolved)
  }
  return alertStore.alerts
})
const forecastResults = computed(() => forecastAlertStore.latestResults)

const getSeverityType = (severity) => {
  const map = { low: 'info', medium: 'warning', high: 'danger', critical: 'danger' }
  return map[severity] || 'info'
}

const getSeverityText = (severity) => {
  const map = { low: '低', medium: '中', high: '高', critical: '紧急' }
  return map[severity] || severity
}

const getAlertTypeText = (type) => {
  const map = {
    high_water: '高水位',
    forecast_high_water: '预报高水位',
    water_detected: '浸水检测',
    sensor_offline: '传感器离线',
    low_battery: '低电量'
  }
  return map[type] || type
}

const formatTime = (time) => formatUtc8DateTime(time)
const formatMm = (value) => value === null || value === undefined ? '-' : `${Number(value).toFixed(1)} mm`
const formatCm = (value) => value === null || value === undefined ? '-' : `${Number(value).toFixed(2)} cm`
const formatPercent = (value) => value === null || value === undefined ? '-' : `${Math.round(Number(value) * 100)}%`

const getRiskType = (risk) => {
  const map = { normal: 'success', watch: 'info', warning: 'warning', critical: 'danger' }
  return map[risk] || 'info'
}

const getRiskText = (risk) => {
  const map = { normal: '正常', watch: '关注', warning: '预警', critical: '危险' }
  return map[risk] || risk
}

const forecastSeverity = (risk) => {
  if (risk === 'critical') return 'critical'
  if (risk === 'warning') return 'high'
  return 'medium'
}

const refreshAlerts = () => {
  alertStore.fetchAlerts()
}

const refreshForecast = async () => {
  if (!accountStore.canResolveAlerts) return
  try {
    await forecastAlertStore.fetchLatest()
  } catch (error) {
    ElMessage.error('加载预报评估失败: ' + (error.response?.data?.detail || error.message))
  }
}

const refreshCurrent = () => {
  if (alertMode.value === 'forecast') {
    refreshForecast()
    return
  }
  refreshAlerts()
}

const runForecastDryRun = async () => {
  try {
    await forecastAlertStore.evaluate({ dry_run: true })
    ElMessage.success('Dry-run 评估完成')
  } catch (error) {
    ElMessage.error('评估失败: ' + (error.response?.data?.detail || error.message))
  }
}

const resolveAlert = (alert) => {
  currentAlert.value = alert
  resolveForm.value.resolved_by = accountStore.displayName
  showResolveDialog.value = true
}

const confirmResolve = async () => {
  if (!resolveForm.value.resolved_by) {
    ElMessage.warning('请输入处理人')
    return
  }
  
  try {
    await alertStore.resolveAlert(currentAlert.value.id, resolveForm.value.resolved_by)
    ElMessage.success('告警已处理')
    showResolveDialog.value = false
  } catch {
    ElMessage.error('处理失败')
  }
}

onMounted(() => {
  alertStore.fetchAlerts()
  refreshTimer = setInterval(() => {
    alertStore.fetchAlerts()
    if (alertMode.value === 'forecast' && accountStore.canResolveAlerts) {
      forecastAlertStore.fetchLatest().catch(() => {})
    }
  }, 10000)
})

watch(alertMode, (mode) => {
  if (mode === 'forecast') {
    refreshForecast()
  }
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
  }
})
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.page-header h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.stats-row {
  margin-bottom: 20px;
}

.forecast-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
  padding: 14px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #f8fafc;
}

.forecast-run-summary,
.forecast-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.stat-box {
  text-align: center;
  padding: 20px;
  background: #f5f7fa;
  border-radius: 8px;
}

.stat-number {
  font-size: 32px;
  font-weight: 600;
  margin-bottom: 8px;
}

.stat-number.critical { color: #f56c6c; }
.stat-number.high { color: #e6a23c; }
.stat-number.medium { color: #409eff; }
.stat-number.total { color: #67c23a; }

.stat-label {
  color: #909399;
  font-size: 14px;
}

.alert-detail {
  padding: 10px 20px;
  background: #f5f7fa;
  border-radius: 4px;
}

.alert-detail pre {
  margin: 0;
  font-size: 12px;
  white-space: pre-wrap;
}

.resolved-info {
  font-size: 12px;
  color: #909399;
}

.alert-card-list {
  min-height: 120px;
  display: grid;
  gap: 12px;
}

.alert-card {
  padding: 14px;
  border: 1px solid #ebeef5;
  border-left: 4px solid #909399;
  border-radius: 10px;
  background: #fff;
}

.alert-card.severity-critical,
.alert-card.severity-high {
  border-left-color: #f56c6c;
}

.alert-card.severity-medium {
  border-left-color: #e6a23c;
}

.alert-card-head,
.alert-card-tags {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.alert-card-head {
  justify-content: space-between;
}

.alert-card-tags {
  flex-wrap: wrap;
}

.alert-card-message {
  margin: 14px 0;
  color: #303133;
  font-size: 15px;
  line-height: 1.6;
}

.alert-card-meta {
  margin: 0;
  display: grid;
  gap: 8px;
}

.alert-card-meta div {
  display: grid;
  grid-template-columns: 64px minmax(0, 1fr);
  gap: 10px;
}

.alert-card-meta dt,
.alert-card-meta dd {
  margin: 0;
  font-size: 13px;
}

.alert-card-meta dt {
  color: #909399;
}

.alert-card-meta dd {
  color: #606266;
  overflow-wrap: anywhere;
}

.alert-details-collapse {
  margin-top: 10px;
}

.alert-details-collapse :deep(.el-collapse-item__content) {
  padding-bottom: 8px;
}

.alert-details-collapse pre {
  margin: 0;
  padding: 10px;
  border-radius: 6px;
  background: #f5f7fa;
  font-size: 12px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.mobile-primary-action {
  width: 100%;
  min-height: 44px;
  margin-top: 12px;
}

@media (max-width: 767px) {
  .page-header {
    align-items: stretch;
    flex-direction: column;
    gap: 12px;
  }

  .header-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .forecast-toolbar,
  .forecast-run-summary,
  .forecast-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .forecast-actions :deep(.el-button) {
    width: 100%;
    margin-left: 0;
  }

  .header-actions :deep(.el-radio-group) {
    display: flex;
  }

  .header-actions :deep(.el-radio-button) {
    flex: 1;
  }

  .header-actions :deep(.el-radio-button__inner) {
    width: 100%;
  }

  .stats-row {
    margin-bottom: 8px;
  }

  .stats-row :deep(.el-col) {
    margin-bottom: 12px;
  }

  .stat-box {
    padding: 14px 8px;
  }

  .stat-number {
    font-size: 26px;
  }

  :global(.el-dialog) {
    max-width: calc(100vw - 24px);
  }
}
</style>
