<template>
  <div class="sensors-page">
    <el-card shadow="hover">
      <template #header>
        <div class="page-header">
          <h2>传感器管理</h2>
          <div class="header-actions">
            <el-input
              v-model="searchQuery"
              placeholder="搜索组、传感器、IMEI..."
              clearable
              data-testid="sensor-search"
              style="width: 240px"
            />
            <el-tag v-if="!accountStore.canManageSensors" effect="plain" type="info">当前账号仅可查看</el-tag>
            <el-button v-if="accountStore.canManageSensors" type="primary" @click="openGroupDialog()">
              <el-icon><Plus /></el-icon>添加组
            </el-button>
            <el-button v-if="accountStore.canManageSensors" type="primary" plain data-testid="add-sensor-button" @click="openSensorDialog()">
              <el-icon><Plus /></el-icon>添加传感器
            </el-button>
          </div>
        </div>
      </template>

      <div class="section-title">组 Webhook</div>
      <div v-if="filteredGroups.length" class="group-list">
        <el-card v-for="group in filteredGroups" :key="group.id" class="group-card" shadow="never">
          <template #header>
            <div class="group-header">
              <div class="group-main">
                <el-button link @click="toggleGroup(group.id)">
                  <el-icon><ArrowRight v-if="!expandedGroups.has(group.id)" /><ArrowDown v-else /></el-icon>
                </el-button>
                <div>
                  <div class="group-name">{{ group.name }}</div>
                  <div class="group-meta">
                    <span>{{ group.description || '未填写描述' }}</span>
                    <span>成员 {{ group.sensors.length }}</span>
                    <span>{{ group.is_active ? '启用中' : '已停用' }}</span>
                  </div>
                </div>
              </div>
              <div class="group-actions">
                <el-button type="primary" link @click="copyGroupUrl(group)">复制组Webhook</el-button>
                <el-button v-if="accountStore.canManageSensors" type="primary" link @click="openSensorDialog(group)">添加组内传感器</el-button>
                <el-button v-if="accountStore.canManageSensors" type="primary" link @click="openGroupDialog(group)">编辑组</el-button>
                <el-button v-if="accountStore.canManageSensors" type="danger" link @click="deleteGroup(group)">删除组</el-button>
              </div>
            </div>
          </template>

          <div class="group-webhook-row">
            <span class="group-webhook-label">组Webhook地址</span>
            <el-input :model-value="groupWebhookUrl(group)" readonly />
          </div>

          <div v-show="expandedGroups.has(group.id)" class="group-sensors">
            <el-empty v-if="!group.sensors.length" description="组内还没有传感器" />
            <el-table v-else-if="!isMobile" :data="group.sensors" stripe>
              <el-table-column prop="sensor_id" label="传感器ID" width="150" />
              <el-table-column prop="sensor_type" label="类型" width="120">
                <template #default="{ row }">
                  <el-tag :type="row.sensor_type === 'ultrasonic' ? 'primary' : 'warning'">
                    {{ row.sensor_type === 'ultrasonic' ? '超声波' : '浸水' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="location" label="安装位置" />
              <el-table-column prop="device_imei" label="设备IMEI" width="160" />
              <el-table-column prop="is_active" label="状态" width="90">
                <template #default="{ row }">
                  <el-switch v-model="row.is_active" :disabled="!accountStore.canManageSensors" @change="(val) => toggleActive(row, val)" />
                </template>
              </el-table-column>
              <el-table-column label="操作" width="180" fixed="right">
                <template #default="{ row }">
                  <el-button type="primary" link @click="viewDetail(row)">详情</el-button>
                  <el-button v-if="accountStore.canManageSensors" type="primary" link @click="openSensorDialog(group, row)">编辑</el-button>
                  <el-button v-if="accountStore.canManageSensors" type="danger" link @click="deleteSensor(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
            <div v-else class="sensor-card-list">
              <article v-for="sensor in group.sensors" :key="sensor.sensor_id" class="sensor-card">
                <div class="sensor-card-head">
                  <div>
                    <strong>{{ sensor.sensor_id }}</strong>
                    <div>{{ sensor.location || '未设置位置' }}</div>
                  </div>
                  <el-tag :type="sensor.sensor_type === 'ultrasonic' ? 'primary' : 'warning'">
                    {{ sensor.sensor_type === 'ultrasonic' ? '超声波' : '浸水' }}
                  </el-tag>
                </div>
                <div class="sensor-card-fields">
                  <div><span>设备 IMEI</span><strong>{{ sensor.device_imei || '-' }}</strong></div>
                  <div>
                    <span>启用状态</span>
                    <el-switch v-model="sensor.is_active" :disabled="!accountStore.canManageSensors" @change="(val) => toggleActive(sensor, val)" />
                  </div>
                </div>
                <div class="sensor-card-actions">
                  <el-button type="primary" plain @click="viewDetail(sensor)">详情</el-button>
                  <el-button v-if="accountStore.canManageSensors" @click="openSensorDialog(group, sensor)">编辑</el-button>
                  <el-button v-if="accountStore.canManageSensors" type="danger" plain @click="deleteSensor(sensor)">删除</el-button>
                </div>
              </article>
            </div>
          </div>
        </el-card>
      </div>
      <el-empty v-else description="还没有组，可先创建组Webhook" />

      <div class="section-title standalone-title">未分组传感器</div>
      <el-table v-if="!isMobile" v-loading="sensorStore.loading" :data="filteredStandaloneSensors" stripe>
        <el-table-column prop="sensor_id" label="传感器ID" width="150" sortable />
        <el-table-column prop="sensor_type" label="类型" width="120" sortable>
          <template #default="{ row }">
            <el-tag :type="row.sensor_type === 'ultrasonic' ? 'primary' : 'warning'">
              {{ row.sensor_type === 'ultrasonic' ? '超声波' : '浸水' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="location" label="安装位置" />
        <el-table-column prop="report_method" label="上报方式" width="120">
          <template #default="{ row }">{{ formatReportMethod(row.report_method) }}</template>
        </el-table-column>
        <el-table-column prop="description" label="描述" show-overflow-tooltip />
        <el-table-column prop="is_active" label="状态" width="90">
          <template #default="{ row }">
            <el-switch v-model="row.is_active" :disabled="!accountStore.canManageSensors" @change="(val) => toggleActive(row, val)" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link @click="viewDetail(row)">详情</el-button>
            <el-button v-if="accountStore.canManageSensors" type="primary" link @click="openSensorDialog(null, row)">编辑</el-button>
            <el-button v-if="accountStore.canManageSensors" type="danger" link @click="deleteSensor(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-else v-loading="sensorStore.loading" class="sensor-card-list standalone-sensor-list">
        <article v-for="sensor in filteredStandaloneSensors" :key="sensor.sensor_id" class="sensor-card">
          <div class="sensor-card-head">
            <div>
              <strong>{{ sensor.sensor_id }}</strong>
              <div>{{ sensor.location || '未设置位置' }}</div>
            </div>
            <el-tag :type="sensor.sensor_type === 'ultrasonic' ? 'primary' : 'warning'">
              {{ sensor.sensor_type === 'ultrasonic' ? '超声波' : '浸水' }}
            </el-tag>
          </div>
          <p v-if="sensor.description" class="sensor-card-description">{{ sensor.description }}</p>
          <div class="sensor-card-fields">
            <div><span>上报方式</span><strong>{{ formatReportMethod(sensor.report_method) }}</strong></div>
            <div>
              <span>启用状态</span>
              <el-switch v-model="sensor.is_active" :disabled="!accountStore.canManageSensors" @change="(val) => toggleActive(sensor, val)" />
            </div>
          </div>
          <div class="sensor-card-actions">
            <el-button type="primary" plain @click="viewDetail(sensor)">详情</el-button>
            <el-button v-if="accountStore.canManageSensors" @click="openSensorDialog(null, sensor)">编辑</el-button>
            <el-button v-if="accountStore.canManageSensors" type="danger" plain @click="deleteSensor(sensor)">删除</el-button>
          </div>
        </article>
        <el-empty v-if="filteredStandaloneSensors.length === 0" description="暂无未分组传感器" />
      </div>
    </el-card>

    <el-dialog v-model="showGroupDialog" :title="editingGroup ? '编辑组' : '添加组'" :width="groupDialogWidth">
      <el-form ref="groupFormRef" :model="groupForm" :rules="groupRules" :label-width="isMobile ? 'auto' : '100px'" :label-position="isMobile ? 'top' : 'right'">
        <el-form-item label="组名称" prop="name">
          <el-input v-model="groupForm.name" placeholder="如: 地下车库一层" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="groupForm.description" type="textarea" rows="3" />
        </el-form-item>
        <el-form-item label="组标识">
          <el-input v-model="groupForm.webhook_token" placeholder="留空自动生成" />
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="groupForm.is_active" />
        </el-form-item>
        <el-form-item v-if="groupPreviewUrl" label="组Webhook">
          <div class="webhook-box">
            <el-input :model-value="groupPreviewUrl" readonly />
            <el-button type="primary" @click="copyText(groupPreviewUrl, '组 Webhook 地址已复制')">
              <el-icon><CopyDocument /></el-icon>复制
            </el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showGroupDialog = false">取消</el-button>
        <el-button type="primary" @click="saveGroup">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="showSensorDialog" :title="editingSensor ? '编辑传感器' : (selectedGroup ? '添加组内传感器' : '添加传感器')" :width="sensorDialogWidth">
      <el-form ref="sensorFormRef" :model="sensorForm" :rules="sensorRules" :label-width="isMobile ? 'auto' : '120px'" :label-position="isMobile ? 'top' : 'right'">
        <el-form-item label="所属组" v-if="selectedGroup">
          <el-tag type="warning">{{ selectedGroup.name }}</el-tag>
        </el-form-item>
        <el-form-item label="传感器ID" prop="sensor_id">
          <el-input v-model="sensorForm.sensor_id" placeholder="如: immersion_001" :disabled="Boolean(editingSensor)" />
        </el-form-item>
        <el-form-item label="传感器类型" prop="sensor_type">
          <el-radio-group v-model="sensorForm.sensor_type">
            <el-radio-button label="ultrasonic">超声波</el-radio-button>
            <el-radio-button label="immersion">浸水</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="上报方式" prop="report_method" v-if="!selectedGroup">
          <el-radio-group v-model="sensorForm.report_method">
            <el-radio-button label="http_api">HTTP API</el-radio-button>
            <el-radio-button label="webhook">Webhook</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="sensorForm.report_method === 'webhook' && !selectedGroup" label="Webhook地址">
          <div class="webhook-box">
            <el-input :model-value="sensorWebhookUrl" readonly />
            <el-button type="primary" @click="copyText(sensorWebhookUrl, 'Webhook 地址已复制')">
              <el-icon><CopyDocument /></el-icon>复制
            </el-button>
          </div>
        </el-form-item>
        <el-form-item label="设备IMEI" prop="device_imei" :required="Boolean(selectedGroup)" v-if="selectedGroup">
          <el-input v-model="sensorForm.device_imei" placeholder="如: 863237085571598" />
        </el-form-item>
        <el-form-item label="安装位置" prop="location">
          <el-input v-model="sensorForm.location" placeholder="如: 图书馆地下室" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="sensorForm.description" type="textarea" rows="3" />
        </el-form-item>
        <template v-if="sensorForm.sensor_type === 'ultrasonic'">
          <el-form-item label="返回单位">
            <el-select v-model="sensorForm.measurement_unit" style="width: 180px">
              <el-option
                v-for="option in measurementUnitOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
            <span class="form-hint">传感器原始上报单位；系统会统一换算为 cm 后入库、展示和告警</span>
          </el-form-item>
          <el-form-item label="阈值判定">
            <el-select v-model="sensorForm.threshold_condition">
              <el-option
                v-for="option in thresholdConditionOptions"
                :key="option.value"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
            <span class="form-hint">{{ thresholdConditionHint }}</span>
          </el-form-item>
          <el-form-item label="预警水位(cm)">
            <el-input-number v-model="sensorForm.warning_level" :min="0" :max="500" />
          </el-form-item>
          <el-form-item label="危险水位(cm)">
            <el-input-number v-model="sensorForm.danger_level" :min="0" :max="500" />
          </el-form-item>
        </template>
        <el-form-item label="正常上报间隔">
          <el-input-number v-model="sensorForm.normal_interval" :min="60" :step="60" />
        </el-form-item>
        <el-form-item label="预警上报间隔">
          <el-input-number v-model="sensorForm.alert_interval" :min="60" :step="60" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="sensorForm.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showSensorDialog = false">取消</el-button>
        <el-button type="primary" @click="saveSensor">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, ArrowRight, CopyDocument, Plus } from '@element-plus/icons-vue'
import { useAccountStore } from '../stores/account'
import { useSensorStore } from '../stores/sensors'
import { useResponsive } from '../composables/useResponsive'

const route = useRoute()
const router = useRouter()
const accountStore = useAccountStore()
const sensorStore = useSensorStore()
const { isMobile } = useResponsive()

const searchQuery = ref('')
const showGroupDialog = ref(false)
const showSensorDialog = ref(false)
const editingGroup = ref(null)
const editingSensor = ref(null)
const selectedGroup = ref(null)
const expandedGroups = ref(new Set())
const groupFormRef = ref(null)
const sensorFormRef = ref(null)
let refreshTimer = null

const groupForm = ref({
  name: '',
  description: '',
  webhook_token: '',
  is_active: true,
})

const sensorForm = ref({
  sensor_id: '',
  sensor_type: 'ultrasonic',
  location: '',
  description: '',
  warning_level: 30,
  danger_level: 50,
  threshold_condition: 'greater_or_equal',
  measurement_unit: 'cm',
  normal_interval: 1800,
  alert_interval: 300,
  is_active: true,
  report_method: 'http_api',
  webhook_token: '',
  webhook_group_id: null,
  device_imei: '',
})

const groupRules = {
  name: [{ required: true, message: '请输入组名称', trigger: 'blur' }],
}

const sensorRules = {
  sensor_id: [{ required: true, message: '请输入传感器ID', trigger: 'blur' }],
  sensor_type: [{ required: true, message: '请选择传感器类型', trigger: 'change' }],
  location: [{ required: true, message: '请输入安装位置', trigger: 'blur' }],
  device_imei: [{
    validator: (_, value, callback) => {
      if (selectedGroup.value && !String(value || '').trim()) {
        callback(new Error('组内传感器需要绑定设备IMEI'))
        return
      }
      callback()
    },
    trigger: 'blur',
  }],
}

const filter = computed(() => route.meta.filter)
const groupDialogWidth = computed(() => isMobile.value ? 'calc(100vw - 24px)' : '560px')
const sensorDialogWidth = computed(() => isMobile.value ? 'calc(100vw - 24px)' : '620px')
const thresholdConditionOptions = [
  { value: 'greater_or_equal', label: '大于等于阈值触发' },
  { value: 'less_or_equal', label: '小于等于阈值触发' },
]
const measurementUnitOptions = [
  { value: 'cm', label: '厘米 (cm)' },
  { value: 'mm', label: '毫米 (mm)' },
]
const thresholdConditionHint = computed(() => (
  sensorForm.value.threshold_condition === 'less_or_equal'
    ? '适合“传感器到水面的测距值”，值越小越危险；此时危险阈值应小于等于预警阈值'
    : '适合常规水位值，值越大越危险；此时危险阈值应大于等于预警阈值'
))

const filteredGroups = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  return sensorStore.groups.filter((group) => {
    const matchesFilter = !filter.value || group.sensors.some((sensor) => sensor.sensor_type === filter.value)
    if (!matchesFilter) {
      return false
    }
    if (!query) {
      return true
    }
    return [
      group.name,
      group.description,
      group.webhook_token,
      ...group.sensors.flatMap((sensor) => [sensor.sensor_id, sensor.location, sensor.device_imei]),
    ].some((value) => String(value || '').toLowerCase().includes(query))
  })
})

const filteredStandaloneSensors = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  return sensorStore.sensors.filter((sensor) => {
    const belongsToResolvedGroup = Boolean(sensor.webhook_group_id && sensor.webhook_group_name)
    if (belongsToResolvedGroup) {
      return false
    }
    if (filter.value && sensor.sensor_type !== filter.value) {
      return false
    }
    if (!query) {
      return true
    }
    return [sensor.sensor_id, sensor.location, sensor.description].some((value) =>
      String(value || '').toLowerCase().includes(query)
    )
  })
})

const groupPreviewUrl = computed(() => {
  if (!groupForm.value.webhook_token) {
    return ''
  }
  return `${window.location.origin}/api/sensors/group-webhook/${groupForm.value.webhook_token}`
})

const sensorWebhookUrl = computed(() => {
  if (!sensorForm.value.webhook_token) {
    return ''
  }
  return `${window.location.origin}/api/sensors/webhook/${sensorForm.value.webhook_token}`
})

const groupWebhookUrl = (group) => `${window.location.origin}/api/sensors/group-webhook/${group.webhook_token}`

const formatReportMethod = (method) => {
  const map = {
    http_api: 'HTTP API',
    webhook: 'Webhook',
    mqtt: 'MQTT',
    coap: 'CoAP',
    udp_binary: '组 Webhook',
  }
  return map[method] || method || '-'
}

const generateToken = () => {
  const chars = '0123456789abcdef'
  let token = ''
  for (let index = 0; index < 16; index += 1) {
    token += chars.charAt(Math.floor(Math.random() * chars.length))
  }
  return token
}

const resetGroupForm = () => {
  editingGroup.value = null
  groupForm.value = {
    name: '',
    description: '',
    webhook_token: '',
    is_active: true,
  }
}

const resetSensorForm = () => {
  editingSensor.value = null
  selectedGroup.value = null
  sensorForm.value = {
    sensor_id: '',
    sensor_type: 'ultrasonic',
    location: '',
    description: '',
    warning_level: 30,
    danger_level: 50,
    threshold_condition: 'greater_or_equal',
    measurement_unit: 'cm',
    normal_interval: 1800,
    alert_interval: 300,
    is_active: true,
    report_method: 'http_api',
    webhook_token: '',
    webhook_group_id: null,
    device_imei: '',
  }
}

const refreshAll = async () => {
  await Promise.all([sensorStore.fetchSensors(), sensorStore.fetchGroups()])
}

const copyText = async (value, successText) => {
  if (!value) {
    return
  }
  try {
    await navigator.clipboard.writeText(value)
    ElMessage.success(successText)
  } catch {
    ElMessage.error('复制失败')
  }
}

const copyGroupUrl = (group) => copyText(groupWebhookUrl(group), '组 Webhook 地址已复制')

const toggleGroup = (groupId) => {
  const next = new Set(expandedGroups.value)
  if (next.has(groupId)) {
    next.delete(groupId)
  } else {
    next.add(groupId)
  }
  expandedGroups.value = next
}

const openGroupDialog = (group = null) => {
  if (group) {
    editingGroup.value = group
    groupForm.value = {
      name: group.name,
      description: group.description || '',
      webhook_token: group.webhook_token,
      is_active: group.is_active,
    }
  } else {
    resetGroupForm()
    groupForm.value.webhook_token = generateToken()
  }
  showGroupDialog.value = true
}

const openSensorDialog = (group = null, sensor = null) => {
  selectedGroup.value = group
  if (sensor) {
    editingSensor.value = sensor
    sensorForm.value = {
      sensor_id: sensor.sensor_id,
      sensor_type: sensor.sensor_type,
      location: sensor.location,
      description: sensor.description || '',
      warning_level: sensor.warning_level,
      danger_level: sensor.danger_level,
      threshold_condition: sensor.threshold_condition || 'greater_or_equal',
      measurement_unit: sensor.measurement_unit || 'cm',
      normal_interval: sensor.normal_interval,
      alert_interval: sensor.alert_interval,
      is_active: sensor.is_active,
      report_method: sensor.report_method || 'http_api',
      webhook_token: sensor.webhook_token || generateToken(),
      webhook_group_id: sensor.webhook_group_id || group?.id || null,
      device_imei: sensor.device_imei || '',
    }
  } else {
    resetSensorForm()
    selectedGroup.value = group
    sensorForm.value.webhook_group_id = group?.id || null
    sensorForm.value.report_method = group ? 'webhook' : 'http_api'
    if (!group) {
      sensorForm.value.webhook_token = generateToken()
    }
  }
  showSensorDialog.value = true
}

const saveGroup = async () => {
  await groupFormRef.value.validate()
  const payload = { ...groupForm.value, webhook_token: groupForm.value.webhook_token || generateToken() }
  try {
    if (editingGroup.value) {
      await sensorStore.updateGroup(editingGroup.value.id, payload)
      ElMessage.success('组已更新')
    } else {
      await sensorStore.createGroup(payload)
      ElMessage.success('组已创建')
    }
    showGroupDialog.value = false
    resetGroupForm()
    await refreshAll()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '保存组失败')
  }
}

const saveSensor = async () => {
  await sensorFormRef.value.validate()
  const payload = { ...sensorForm.value }
  if (
    payload.sensor_type === 'ultrasonic' &&
    payload.warning_level !== null &&
    payload.warning_level !== undefined &&
    payload.danger_level !== null &&
    payload.danger_level !== undefined
  ) {
    const invalid =
      payload.threshold_condition === 'less_or_equal'
        ? Number(payload.danger_level) > Number(payload.warning_level)
        : Number(payload.danger_level) < Number(payload.warning_level)
    if (invalid) {
      ElMessage.error(
        payload.threshold_condition === 'less_or_equal'
          ? '当前为“小于等于阈值触发”，危险阈值必须小于或等于预警阈值'
          : '当前为“大于等于阈值触发”，危险阈值必须大于或等于预警阈值'
      )
      return
    }
  }
  if (selectedGroup.value) {
    payload.webhook_group_id = selectedGroup.value.id
    payload.webhook_token = null
    payload.report_method = 'webhook'
  } else if (payload.report_method === 'webhook') {
    payload.webhook_token = payload.webhook_token || generateToken()
    payload.webhook_group_id = null
    payload.device_imei = null
  } else {
    payload.webhook_token = null
    payload.webhook_group_id = null
    payload.device_imei = null
  }

  try {
    if (editingSensor.value) {
      await sensorStore.updateSensor(payload.sensor_id, payload)
      ElMessage.success('传感器已更新')
    } else {
      await sensorStore.createSensor(payload)
      ElMessage.success('传感器已创建')
    }
    showSensorDialog.value = false
    resetSensorForm()
    await refreshAll()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '保存传感器失败')
  }
}

const deleteGroup = async (group) => {
  try {
    await ElMessageBox.confirm(`确定删除组 ${group.name} 吗？组内传感器会变成未分组状态。`, '确认删除', { type: 'warning' })
    await sensorStore.deleteGroup(group.id)
    ElMessage.success('组已删除')
    await refreshAll()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除组失败')
    }
  }
}

const deleteSensor = async (sensor) => {
  try {
    await ElMessageBox.confirm(`确定删除传感器 ${sensor.sensor_id} 吗？`, '确认删除', { type: 'warning' })
    await sensorStore.deleteSensor(sensor.sensor_id)
    ElMessage.success('删除成功')
    await refreshAll()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

const toggleActive = async (sensor, value) => {
  try {
    await sensorStore.updateSensor(sensor.sensor_id, { is_active: value })
    ElMessage.success('状态已更新')
    await refreshAll()
  } catch {
    sensor.is_active = !value
    ElMessage.error('更新失败')
  }
}

const viewDetail = (sensor) => {
  router.push(`/sensors/${sensor.sensor_id}`)
}

onMounted(async () => {
  await refreshAll()
  refreshTimer = setInterval(() => {
    refreshAll()
  }, 15000)
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
  }
})
</script>

<style scoped>
.sensors-page {
  padding: 0;
}

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
  align-items: center;
}

.section-title {
  margin: 4px 0 16px;
  font-size: 14px;
  font-weight: 600;
  color: #606266;
}

.standalone-title {
  margin-top: 28px;
}

.group-list {
  display: grid;
  gap: 16px;
}

.group-card {
  border: 1px solid #ebeef5;
}

.group-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}

.group-main {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}

.group-name {
  font-weight: 600;
  color: #303133;
}

.group-meta {
  margin-top: 6px;
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  color: #909399;
  font-size: 12px;
}

.group-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.group-webhook-row {
  margin-bottom: 16px;
}

.group-webhook-label {
  display: block;
  margin-bottom: 8px;
  font-size: 12px;
  color: #909399;
}

.webhook-box {
  display: flex;
  gap: 8px;
}

.webhook-box .el-input {
  flex: 1;
}

.form-hint {
  display: block;
  width: 100%;
  margin-top: 6px;
  color: #909399;
  font-size: 12px;
  line-height: 1.4;
}

.group-sensors {
  margin-top: 12px;
}

.sensor-card-list {
  display: grid;
  gap: 12px;
}

.sensor-card {
  padding: 14px;
  border: 1px solid #ebeef5;
  border-radius: 10px;
  background: #fff;
}

.sensor-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.sensor-card-head strong {
  color: #303133;
  font-size: 15px;
}

.sensor-card-head div div,
.sensor-card-description {
  margin-top: 5px;
  color: #909399;
  font-size: 12px;
}

.sensor-card-description {
  line-height: 1.5;
}

.sensor-card-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 14px;
}

.sensor-card-fields > div {
  min-width: 0;
  display: grid;
  align-content: start;
  gap: 5px;
}

.sensor-card-fields span {
  color: #909399;
  font-size: 12px;
}

.sensor-card-fields strong {
  overflow: hidden;
  color: #606266;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sensor-card-actions {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-top: 14px;
}

.sensor-card-actions :deep(.el-button) {
  min-height: 42px;
  margin-left: 0;
}

@media (max-width: 767px) {
  .page-header,
  .header-actions,
  .group-header,
  .group-actions,
  .webhook-box {
    align-items: stretch;
    flex-direction: column;
  }

  .page-header {
    gap: 14px;
  }

  .header-actions :deep(.el-input),
  .header-actions :deep(.el-button),
  .group-actions :deep(.el-button) {
    width: 100% !important;
    min-height: 42px;
    margin-left: 0;
  }

  .group-header {
    gap: 12px;
  }

  .group-main {
    min-width: 0;
  }

  .group-actions {
    width: 100%;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .group-webhook-row :deep(.el-input__wrapper) {
    min-height: 42px;
  }

  .webhook-box :deep(.el-button) {
    min-height: 42px;
    margin-left: 0;
  }

  .standalone-title {
    margin-top: 20px;
  }

  .sensor-card-actions {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  :deep(.el-dialog__body) {
    max-height: calc(100dvh - 160px);
    padding: 14px 16px;
    overflow-y: auto;
  }

  :deep(.el-dialog__footer) {
    padding: 12px 16px 16px;
  }

  :deep(.el-dialog__footer .el-button) {
    min-width: 96px;
    min-height: 42px;
  }

  :deep(.el-form-item__label) {
    margin-bottom: 4px;
  }

  :deep(.el-radio-group) {
    width: 100%;
    display: flex;
  }

  :deep(.el-radio-button) {
    flex: 1;
  }

  :deep(.el-radio-button__inner) {
    width: 100%;
    padding-right: 8px;
    padding-left: 8px;
  }

  :deep(.el-input-number),
  :deep(.el-select) {
    width: 100% !important;
  }
}
</style>
