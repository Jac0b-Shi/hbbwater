<template>
  <div class="settings-page">
    <el-row :gutter="20">
      <el-col :xs="24" :md="12">
        <el-card shadow="hover">
          <template #header>
            <span>系统配置</span>
          </template>
          <el-form :model="systemConfig" :label-width="isMobile ? 'auto' : '150px'" :label-position="isMobile ? 'top' : 'right'">
            <el-form-item label="热数据保留天数">
              <el-input-number v-model="systemConfig.data_retention_days" :min="7" :max="30" />
              <span class="form-hint">天</span>
            </el-form-item>
            <el-form-item label="离线判定时间">
              <el-input-number v-model="systemConfig.offline_timeout_minutes" :min="10" :max="180" />
              <span class="form-hint">分钟</span>
            </el-form-item>
            <el-form-item label="告警冷却时间">
              <el-input-number v-model="systemConfig.alert_cooldown_minutes" :min="5" :max="120" />
              <span class="form-hint">分钟</span>
            </el-form-item>
            <el-form-item label="自动归档">
              <el-switch v-model="systemConfig.archive_enabled" />
            </el-form-item>
            <el-form-item label="数据统计">
              <el-switch v-model="systemConfig.summary_enabled" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="saveSystemConfig">保存配置</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>

      <el-col :xs="24" :md="12">
        <el-card shadow="hover">
          <template #header>
            <span>通知设置</span>
          </template>
          <el-form :model="notifyConfig" :label-width="isMobile ? 'auto' : '150px'" :label-position="isMobile ? 'top' : 'right'">
            <el-form-item label="邮件通知">
              <el-switch v-model="notifyConfig.email_enabled" />
              <span class="form-hint" style="margin-left: 10px; color: #67c23a;">优先使用 SMTP，失败时回退 WordPress 网关</span>
            </el-form-item>
            <el-form-item label="SMTP服务器">
              <el-input v-model="notifyConfig.smtp_host" placeholder="smtp.example.com" />
            </el-form-item>
            <el-form-item label="SMTP端口">
              <el-input-number v-model="notifyConfig.smtp_port" :min="1" :max="65535" />
            </el-form-item>
            <el-form-item label="发件人邮箱">
              <el-input
                v-model="notifyConfig.smtp_user"
                placeholder="alert@example.com"
                autocomplete="off"
                name="smtp-user-config"
                data-lpignore="true"
                data-1p-ignore="true"
                spellcheck="false"
              />
            </el-form-item>
            <el-form-item label="SMTP密码/授权码">
              <el-input
                :key="smtpPasswordFieldKey"
                v-model="smtpPasswordDraft"
                type="password"
                show-password
                :placeholder="notifyConfig.smtp_password_set ? '已保存授权码；如需更新，请输入新的授权码' : '邮箱授权码或密码'"
                autocomplete="off"
                name="smtp-password-config"
                data-lpignore="true"
                data-1p-ignore="true"
                spellcheck="false"
                clearable
              />
              <span class="form-hint">{{ smtpPasswordHint }}</span>
              <el-button link type="danger" @click="clearSmtpPassword">清空已保存密码</el-button>
            </el-form-item>
            <el-form-item label="使用SSL/TLS">
              <el-switch v-model="notifyConfig.smtp_ssl" @change="handleSmtpSslChange" />
              <span class="form-hint">{{ notifyConfig.smtp_ssl ? 'SSL加密（推荐）' : '明文传输' }}</span>
            </el-form-item>
            <el-form-item label="测试邮箱">
              <el-input v-model="testEmailAddress" placeholder="接收测试邮件的邮箱地址" />
            </el-form-item>
            <el-form-item>
              <el-button
                type="primary"
                @click="testEmail"
                :disabled="!notifyConfigReady || !notifyConfig.email_enabled || !testEmailAddress.trim()"
                :loading="testingEmail"
              >
                测试邮件
              </el-button>
              <el-button @click="saveNotifyConfig" :disabled="!notifyConfigReady" :loading="savingNotifyConfig">
                保存配置
              </el-button>
            </el-form-item>
            <el-divider />
            <el-form-item label="Webhook通知">
              <el-switch v-model="notifyConfig.webhook_enabled" />
            </el-form-item>
            <el-form-item label="Webhook URL">
              <el-input v-model="notifyConfig.webhook_url" placeholder="https://example.com/webhook" />
            </el-form-item>
            <el-form-item>
              <el-alert
                title="Webhook 将收到统一 JSON 负载，包含 event、sensor、alert、reading、sent_at 等字段。"
                type="info"
                :closable="false"
                show-icon
              />
            </el-form-item>
            <el-form-item>
              <el-button
                type="primary"
                @click="testWebhook"
                :disabled="!notifyConfigReady || !notifyConfig.webhook_enabled || !notifyConfig.webhook_url.trim()"
                :loading="testingWebhook"
              >
                测试 Webhook
              </el-button>
              <el-button @click="saveNotifyConfig" :disabled="!notifyConfigReady" :loading="savingNotifyConfig">
                保存配置
              </el-button>
              <span class="form-hint">测试前会自动保存当前填写内容</span>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" class="mt-4">
      <el-col :span="24">
        <el-card shadow="hover">
          <template #header>
            <div class="card-header-inline">
              <span>业务数据库</span>
              <el-tag :type="runtimeTagType">{{ businessDbState.runtime.display_name || '未配置' }}</el-tag>
            </div>
          </template>

          <el-alert
            title="管理员、通知配置和数据库 profile 固定保存在本地控制库 SQLite；传感器、读数、告警和统计数据写入当前激活的业务数据库。"
            type="info"
            show-icon
            :closable="false"
            class="mb-4"
          />
          <el-alert
            v-if="businessDbState.runtime.last_error"
            title="当前业务数据库尚未就绪，但控制库 SQLite 已可正常使用"
            :description="businessDbState.runtime.last_error"
            type="warning"
            show-icon
            :closable="false"
            class="mb-4"
          />

          <div class="profile-toolbar">
            <el-select
              v-model="selectedBusinessProfileId"
              placeholder="选择已有业务数据库配置"
              class="profile-select"
              :disabled="!businessDbState.profiles.length"
            >
              <el-option
                v-for="profile in businessDbState.profiles"
                :key="profile.id"
                :label="profile.display_name + (profile.is_active ? '（当前）' : '')"
                :value="profile.id"
              />
            </el-select>
            <el-button @click="startNewBusinessProfile">新建配置</el-button>
          </div>

          <el-descriptions :column="4" border class="mb-4">
            <el-descriptions-item label="当前业务库">{{ businessDbState.runtime.display_name || '未配置' }}</el-descriptions-item>
            <el-descriptions-item label="方言">{{ businessDbState.runtime.dialect || '-' }}</el-descriptions-item>
            <el-descriptions-item label="数据库名">{{ businessDbState.runtime.database || '-' }}</el-descriptions-item>
            <el-descriptions-item label="连接方式">{{ runtimeConnectionText }}</el-descriptions-item>
          </el-descriptions>

          <el-form :model="businessProfileForm" :label-width="isMobile ? 'auto' : '150px'" :label-position="isMobile ? 'top' : 'right'">
            <el-form-item label="配置名称">
              <el-input v-model="businessProfileForm.display_name" placeholder="例如：本地 MySQL / 单位达梦集群" />
            </el-form-item>
            <el-form-item label="数据库类型">
              <el-select v-model="businessProfileForm.dialect">
                <el-option label="MySQL" value="mysql" />
                <el-option label="达梦 DM8" value="dm" />
                <el-option label="SQLite" value="sqlite" />
              </el-select>
              <span class="form-hint">控制库仍固定使用 SQLite，这里配置的是业务库</span>
            </el-form-item>
            <el-form-item label="驱动">
              <el-input v-model="businessProfileForm.driver" placeholder="如 aiomysql / dmAsync / aiosqlite" />
            </el-form-item>
            <el-form-item v-if="businessProfileForm.dialect !== 'sqlite'" label="主机地址">
              <el-input v-model="businessProfileForm.host" :placeholder="businessProfileForm.dialect === 'mysql' ? 'mysql 或 127.0.0.1' : '达梦单实例地址，可留空改用服务名'" />
            </el-form-item>
            <el-form-item v-if="businessProfileForm.dialect !== 'sqlite'" label="端口">
              <el-input v-model="businessProfileForm.port" :placeholder="businessProfileForm.dialect === 'mysql' ? '3306' : '5236'" />
            </el-form-item>
            <el-form-item v-if="businessProfileForm.dialect === 'dm'" label="服务名">
              <el-input v-model="businessProfileForm.service_name" placeholder="例如 DM_CLUSTER；填写后优先走 dm_svc.conf 服务名连接" />
              <span class="form-hint">单位集群模式建议填写服务名，并同时配置 DM_SVC_PATH</span>
            </el-form-item>
            <el-form-item label="数据库名">
              <el-input v-model="businessProfileForm.database_name" placeholder="业务库名" />
            </el-form-item>
            <el-form-item v-if="businessProfileForm.dialect !== 'sqlite'" label="用户名">
              <el-input v-model="businessProfileForm.username" placeholder="数据库用户名" />
            </el-form-item>
            <el-form-item v-if="businessProfileForm.dialect !== 'sqlite'" label="密码">
              <el-input
                :key="businessPasswordFieldKey"
                v-model="businessPasswordDraft"
                type="password"
                show-password
                :placeholder="businessProfileForm.password_set ? '已保存密码；如需更新，请输入新的密码' : '数据库密码'"
                autocomplete="off"
                clearable
              />
              <span class="form-hint">{{ businessPasswordHint }}</span>
              <el-button
                v-if="businessProfileForm.id && businessProfileForm.password_set"
                link
                type="danger"
                @click="clearBusinessProfilePassword"
              >
                清空已保存密码
              </el-button>
            </el-form-item>
            <el-form-item v-if="businessProfileForm.dialect === 'dm'" label="DM_HOME">
              <el-input v-model="businessProfileForm.dm_home" placeholder="例如 /opt/dmdbms 或 D:\\Program Files\\dmdbms" />
            </el-form-item>
            <el-form-item v-if="businessProfileForm.dialect === 'dm'" label="DM_SVC_PATH">
              <el-input v-model="businessProfileForm.dm_svc_path" placeholder="例如 /etc 或 C:\\Windows\\System32" />
            </el-form-item>
            <el-form-item label="自动建表">
              <el-switch v-model="businessProfileForm.auto_create_schema" />
              <span class="form-hint">达梦建议关闭并先执行 `database/dm/init.sql`</span>
            </el-form-item>
            <el-form-item v-if="businessProfileForm.last_tested_at" label="最近测试">
              <span>{{ formatDateTime(businessProfileForm.last_tested_at) }}</span>
            </el-form-item>
            <el-form-item v-if="businessProfileForm.last_error" label="最近错误">
              <el-text type="danger">{{ businessProfileForm.last_error }}</el-text>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="savingBusinessProfile" @click="saveBusinessProfile">保存配置</el-button>
              <el-button :loading="testingBusinessProfile" @click="testBusinessProfile">测试连接</el-button>
              <el-button
                type="success"
                :loading="activatingBusinessProfile"
                :disabled="!businessProfileForm.id"
                @click="activateBusinessProfile"
              >
                应用切换
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" class="mt-4">
      <el-col :span="24">
        <el-card shadow="hover">
          <template #header>
            <span>业务数据库统计</span>
          </template>
          <el-alert
            v-if="businessStatsUnavailable"
            title="业务数据库统计暂不可用"
            type="warning"
            show-icon
            :closable="false"
            class="mb-4"
          />
          <el-descriptions :column="4" border>
            <el-descriptions-item label="热数据表">{{ dbStats.readings_count?.toLocaleString() }} 条</el-descriptions-item>
            <el-descriptions-item label="归档数据">{{ dbStats.archive_count?.toLocaleString() }} 条</el-descriptions-item>
            <el-descriptions-item label="小时汇总">{{ dbStats.hourly_count?.toLocaleString() }} 条</el-descriptions-item>
            <el-descriptions-item label="日汇总">{{ dbStats.daily_count?.toLocaleString() }} 条</el-descriptions-item>
          </el-descriptions>
          <div class="db-actions">
            <el-tooltip content="按控制库中的保留策略归档并清理过期热数据" placement="top">
              <el-button type="primary" :loading="maintenanceLoading" @click="runMaintenance">
                <el-icon><Tools /></el-icon>执行维护任务
              </el-button>
            </el-tooltip>
            <el-tooltip :content="optimizeTooltip" placement="top">
              <el-button type="warning" :loading="optimizeLoading" :disabled="!optimizeSupported" @click="optimizeTables">
                <el-icon><Rank /></el-icon>优化数据表
              </el-button>
            </el-tooltip>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" class="mt-4">
      <el-col :span="24">
        <el-card shadow="hover">
          <template #header>
            <span>系统信息</span>
          </template>
          <el-descriptions :column="3" border>
            <el-descriptions-item label="系统版本">{{ APP_VERSION }}</el-descriptions-item>
            <el-descriptions-item label="API版本">v1</el-descriptions-item>
            <el-descriptions-item label="控制库">SQLite</el-descriptions-item>
            <el-descriptions-item label="当前业务库">{{ businessDbState.runtime.display_name || '-' }}</el-descriptions-item>
            <el-descriptions-item label="业务库方言">{{ businessDbState.runtime.dialect || '-' }}</el-descriptions-item>
            <el-descriptions-item label="业务库目标">{{ runtimeDatabaseTarget }}</el-descriptions-item>
            <el-descriptions-item label="后端">FastAPI</el-descriptions-item>
            <el-descriptions-item label="前端">Vue 3 + Element Plus</el-descriptions-item>
            <el-descriptions-item label="Web服务器">Caddy</el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import axios from 'axios'
import { APP_VERSION } from '../constants/appMeta'
import { formatUtc8DateTime } from '../utils/time'
import { useResponsive } from '../composables/useResponsive'

const { isMobile } = useResponsive()

const systemConfig = ref({
  data_retention_days: 14,
  offline_timeout_minutes: 60,
  alert_cooldown_minutes: 30,
  archive_enabled: true,
  summary_enabled: true
})

const notifyConfig = ref({
  email_enabled: false,
  smtp_host: '',
  smtp_port: 587,
  smtp_user: '',
  smtp_password_set: false,
  smtp_ssl: true,
  webhook_enabled: false,
  webhook_url: ''
})

const notifyConfigReady = ref(false)
const savingNotifyConfig = ref(false)
const testingEmail = ref(false)
const testingWebhook = ref(false)
const smtpPasswordDraft = ref('')
const smtpPasswordFieldKey = ref(0)
const testEmailAddress = ref('')

const businessDbState = ref({
  active_profile_id: null,
  runtime: {
    display_name: '',
    dialect: '',
    database: '',
    host: '',
    service_name: '',
    configured: false,
    last_error: ''
  },
  profiles: []
})

const selectedBusinessProfileId = ref(null)
const savingBusinessProfile = ref(false)
const testingBusinessProfile = ref(false)
const activatingBusinessProfile = ref(false)
const businessPasswordDraft = ref('')
const businessPasswordFieldKey = ref(0)

const dbStats = ref({
  readings_count: 0,
  archive_count: 0,
  hourly_count: 0,
  daily_count: 0
})
const businessStatsUnavailable = ref(false)

const maintenanceLoading = ref(false)
const optimizeLoading = ref(false)

const defaultBusinessProfileForm = () => ({
  id: null,
  profile_key: '',
  display_name: '',
  dialect: 'mysql',
  driver: 'aiomysql',
  host: 'mysql',
  port: '3306',
  service_name: '',
  database_name: 'flood_monitoring',
  username: 'flood_user',
  password_set: false,
  dm_home: '',
  dm_svc_path: '',
  auto_create_schema: false,
  is_active: false,
  last_tested_at: '',
  last_error: ''
})

const businessProfileForm = ref(defaultBusinessProfileForm())

const smtpPasswordHint = computed(() => {
  if (smtpPasswordDraft.value.trim()) {
    return '将使用新的授权码覆盖当前已保存值'
  }
  return notifyConfig.value.smtp_password_set ? '授权码已保存在服务器端；留空则保持不变' : '尚未保存授权码'
})

const businessPasswordHint = computed(() => {
  if (businessPasswordDraft.value.trim()) {
    return '将使用新的数据库密码覆盖当前已保存值'
  }
  return businessProfileForm.value.password_set ? '密码已保存在服务器端；留空则保持不变' : '尚未保存数据库密码'
})

const optimizeSupported = computed(() => businessDbState.value.runtime.dialect === 'mysql')
const optimizeTooltip = computed(() => (
  optimizeSupported.value
    ? '执行 MySQL OPTIMIZE TABLE，可能需要较长时间'
    : `当前业务库为 ${businessDbState.value.runtime.dialect || '未知'}，暂未实现在线优化`
))
const runtimeTagType = computed(() => {
  if (businessDbState.value.runtime.last_error) return 'danger'
  if (businessDbState.value.runtime.dialect === 'dm') return 'success'
  if (businessDbState.value.runtime.dialect === 'mysql') return 'warning'
  return 'info'
})
const runtimeConnectionText = computed(() => (
  businessDbState.value.runtime.service_name
    ? `服务名 ${businessDbState.value.runtime.service_name}`
    : (businessDbState.value.runtime.host || '-')
))
const runtimeDatabaseTarget = computed(() => {
  if (businessDbState.value.runtime.service_name) {
    return `${businessDbState.value.runtime.service_name} / ${businessDbState.value.runtime.database || '-'}`
  }
  if (businessDbState.value.runtime.host) {
    return `${businessDbState.value.runtime.host} / ${businessDbState.value.runtime.database || '-'}`
  }
  return businessDbState.value.runtime.database || '-'
})

const getErrorMessage = (error) => {
  if (error.response?.data?.detail) return error.response.data.detail
  if (error.response?.data?.message) return error.response.data.message
  if (typeof error.response?.data === 'string') return error.response.data
  if (error.response?.data) return JSON.stringify(error.response.data)
  return error.message || '未知错误'
}

const resetSmtpPasswordDraft = () => {
  smtpPasswordDraft.value = ''
  smtpPasswordFieldKey.value += 1
}

const resetBusinessPasswordDraft = () => {
  businessPasswordDraft.value = ''
  businessPasswordFieldKey.value += 1
}

const formatDateTime = (value) => formatUtc8DateTime(value)

const buildNotifyConfigPayload = () => {
  const payload = {
    email_enabled: notifyConfig.value.email_enabled,
    smtp_host: notifyConfig.value.smtp_host.trim(),
    smtp_port: notifyConfig.value.smtp_port,
    smtp_user: notifyConfig.value.smtp_user.trim(),
    smtp_ssl: notifyConfig.value.smtp_ssl,
    webhook_enabled: notifyConfig.value.webhook_enabled,
    webhook_url: notifyConfig.value.webhook_url.trim()
  }

  const password = smtpPasswordDraft.value.trim()
  if (password) {
    payload.smtp_password = password
  }

  return payload
}

const applySavedNotifyConfig = (payload) => {
  notifyConfig.value = {
    ...notifyConfig.value,
    ...payload,
    smtp_password_set: Boolean(payload.smtp_password || notifyConfig.value.smtp_password_set)
  }
}

const submitNotifyConfig = async () => {
  const payload = buildNotifyConfigPayload()
  await axios.post('/api/config/notification', payload)
  applySavedNotifyConfig(payload)
  resetSmtpPasswordDraft()
}

const applyBusinessProfileForm = (profile) => {
  if (!profile) {
    businessProfileForm.value = defaultBusinessProfileForm()
    resetBusinessPasswordDraft()
    return
  }

  businessProfileForm.value = {
    ...defaultBusinessProfileForm(),
    ...profile
  }
  selectedBusinessProfileId.value = profile.id
  resetBusinessPasswordDraft()
}

const syncBusinessDatabaseState = (payload) => {
  businessDbState.value = {
    active_profile_id: payload.active_profile_id,
    runtime: payload.runtime || businessDbState.value.runtime,
    profiles: payload.profiles || []
  }

  const profiles = businessDbState.value.profiles
  const preferredProfile =
    profiles.find(profile => profile.id === selectedBusinessProfileId.value) ||
    profiles.find(profile => profile.id === payload.active_profile_id) ||
    profiles[0]

  if (preferredProfile) {
    applyBusinessProfileForm(preferredProfile)
  } else {
    applyBusinessProfileForm(null)
  }
}

const buildBusinessProfilePayload = (extra = {}) => {
  const payload = {
    id: businessProfileForm.value.id,
    profile_key: businessProfileForm.value.profile_key || null,
    display_name: businessProfileForm.value.display_name,
    dialect: businessProfileForm.value.dialect,
    driver: businessProfileForm.value.driver || null,
    host: businessProfileForm.value.host,
    port: businessProfileForm.value.port,
    service_name: businessProfileForm.value.service_name,
    database_name: businessProfileForm.value.database_name,
    username: businessProfileForm.value.username,
    dm_home: businessProfileForm.value.dm_home,
    dm_svc_path: businessProfileForm.value.dm_svc_path,
    auto_create_schema: businessProfileForm.value.auto_create_schema,
    ...extra
  }

  const password = businessPasswordDraft.value.trim()
  if (password) {
    payload.password = password
  }

  return payload
}

const loadSettings = async () => {
  const [systemRes, notifyRes, businessRes, statsRes] = await Promise.allSettled([
    axios.get('/api/config/system'),
    axios.get('/api/config/notification'),
    axios.get('/api/config/business-database'),
    axios.get('/api/config/database/stats')
  ])

  if (systemRes.status !== 'fulfilled') throw systemRes.reason
  if (notifyRes.status !== 'fulfilled') throw notifyRes.reason
  if (businessRes.status !== 'fulfilled') throw businessRes.reason

  systemConfig.value = { ...systemConfig.value, ...systemRes.value.data }
  notifyConfig.value = { ...notifyConfig.value, ...notifyRes.value.data }
  syncBusinessDatabaseState(businessRes.value.data)

  if (statsRes.status === 'fulfilled') {
    dbStats.value = { ...dbStats.value, ...statsRes.value.data }
    businessStatsUnavailable.value = false
  } else {
    dbStats.value = {
      readings_count: 0,
      archive_count: 0,
      hourly_count: 0,
      daily_count: 0
    }
    businessStatsUnavailable.value = true
  }

  resetSmtpPasswordDraft()
  notifyConfigReady.value = true
}

const saveSystemConfig = async () => {
  try {
    await axios.post('/api/config/system', systemConfig.value)
    ElMessage.success('系统配置已保存')
  } catch (error) {
    ElMessage.error('保存失败: ' + getErrorMessage(error))
  }
}

const saveNotifyConfig = async () => {
  savingNotifyConfig.value = true
  try {
    await submitNotifyConfig()
    ElMessage.success('通知配置已保存')
  } catch (error) {
    ElMessage.error('保存失败: ' + getErrorMessage(error))
  } finally {
    savingNotifyConfig.value = false
  }
}

const clearSmtpPassword = async () => {
  try {
    await axios.post('/api/config/notification', { clear_smtp_password: true })
    resetSmtpPasswordDraft()
    notifyConfig.value.smtp_password_set = false
    ElMessage.success('已清空保存的 SMTP 密码')
  } catch (error) {
    ElMessage.error('清空失败: ' + getErrorMessage(error))
  }
}

const handleSmtpSslChange = (value) => {
  notifyConfig.value.smtp_port = value ? 465 : 587
}

const testEmail = async () => {
  const to = testEmailAddress.value.trim()
  if (!to) {
    ElMessage.warning('请先填写测试邮箱')
    return
  }
  testingEmail.value = true
  try {
    await submitNotifyConfig()
    const response = await axios.post('/api/config/notification/test-email', { to })
    ElMessage.success(response.data.message || '测试邮件已发送')
  } catch (error) {
    ElMessage.error('发送失败: ' + getErrorMessage(error))
  } finally {
    testingEmail.value = false
  }
}

const testWebhook = async () => {
  testingWebhook.value = true
  try {
    await submitNotifyConfig()
    await axios.post('/api/config/notification/test-webhook')
    ElMessage.success('测试 Webhook 已发送')
  } catch (error) {
    ElMessage.error('发送失败: ' + getErrorMessage(error))
  } finally {
    testingWebhook.value = false
  }
}

const startNewBusinessProfile = () => {
  selectedBusinessProfileId.value = null
  applyBusinessProfileForm(null)
}

const saveBusinessProfile = async () => {
  savingBusinessProfile.value = true
  try {
    const response = await axios.post('/api/config/business-database/profiles', buildBusinessProfilePayload())
    ElMessage.success(response.data.message || '业务数据库配置已保存')
    await loadSettings()
    const profile = response.data.profile
    if (profile?.id) {
      selectedBusinessProfileId.value = profile.id
      applyBusinessProfileForm(profile)
    }
  } catch (error) {
    ElMessage.error('保存失败: ' + getErrorMessage(error))
  } finally {
    savingBusinessProfile.value = false
  }
}

const clearBusinessProfilePassword = async () => {
  if (!businessProfileForm.value.id) {
    return
  }
  savingBusinessProfile.value = true
  try {
    const response = await axios.post(
      '/api/config/business-database/profiles',
      buildBusinessProfilePayload({ clear_password: true })
    )
    ElMessage.success(response.data.message || '已清空业务数据库密码')
    await loadSettings()
    const profile = response.data.profile
    if (profile?.id) {
      selectedBusinessProfileId.value = profile.id
      applyBusinessProfileForm(profile)
    }
  } catch (error) {
    ElMessage.error('清空失败: ' + getErrorMessage(error))
  } finally {
    savingBusinessProfile.value = false
  }
}

const testBusinessProfile = async () => {
  testingBusinessProfile.value = true
  try {
    const response = await axios.post('/api/config/business-database/profiles/test', buildBusinessProfilePayload())
    ElMessage.success(response.data.message || '数据库连接测试成功')
    await loadSettings()
  } catch (error) {
    ElMessage.error('测试失败: ' + getErrorMessage(error))
  } finally {
    testingBusinessProfile.value = false
  }
}

const activateBusinessProfile = async () => {
  if (!businessProfileForm.value.id) {
    ElMessage.warning('请先保存配置，再应用切换')
    return
  }
  activatingBusinessProfile.value = true
  try {
    const response = await axios.post(`/api/config/business-database/profiles/${businessProfileForm.value.id}/activate`)
    ElMessage.success(response.data.message || '业务数据库已切换')
    await loadSettings()
  } catch (error) {
    ElMessage.error('切换失败: ' + getErrorMessage(error))
  } finally {
    activatingBusinessProfile.value = false
  }
}

const runMaintenance = async () => {
  maintenanceLoading.value = true
  try {
    const response = await axios.post('/api/config/database/maintenance')
    dbStats.value = response.data.stats || dbStats.value
    ElMessage.success(response.data.message || '维护任务执行完成')
  } catch (error) {
    ElMessage.error('维护任务执行失败: ' + getErrorMessage(error))
  } finally {
    maintenanceLoading.value = false
  }
}

const optimizeTables = async () => {
  optimizeLoading.value = true
  try {
    const response = await axios.post('/api/config/database/optimize')
    dbStats.value = response.data.stats || dbStats.value
    ElMessage.success(response.data.message || '数据表优化完成')
  } catch (error) {
    ElMessage.error('优化失败: ' + getErrorMessage(error))
  } finally {
    optimizeLoading.value = false
  }
}

watch(() => businessProfileForm.value.dialect, (dialect) => {
  if (dialect === 'mysql') {
    if (!businessProfileForm.value.driver || businessProfileForm.value.driver === 'dmAsync' || businessProfileForm.value.driver === 'aiosqlite') {
      businessProfileForm.value.driver = 'aiomysql'
    }
    if (!businessProfileForm.value.port) {
      businessProfileForm.value.port = '3306'
    }
    if (!businessProfileForm.value.host) {
      businessProfileForm.value.host = 'mysql'
    }
  } else if (dialect === 'dm') {
    if (!businessProfileForm.value.driver || businessProfileForm.value.driver === 'aiomysql' || businessProfileForm.value.driver === 'aiosqlite') {
      businessProfileForm.value.driver = 'dmAsync'
    }
    if (!businessProfileForm.value.port) {
      businessProfileForm.value.port = '5236'
    }
  } else if (dialect === 'sqlite') {
    businessProfileForm.value.driver = 'aiosqlite'
    businessProfileForm.value.host = ''
    businessProfileForm.value.port = ''
    businessProfileForm.value.service_name = ''
    businessProfileForm.value.username = ''
    businessProfileForm.value.dm_home = ''
    businessProfileForm.value.dm_svc_path = ''
  }
})

watch(selectedBusinessProfileId, (profileId) => {
  if (!profileId) return
  const profile = businessDbState.value.profiles.find(item => item.id === profileId)
  if (profile) {
    applyBusinessProfileForm(profile)
  }
})

onMounted(async () => {
  try {
    await loadSettings()
  } catch (error) {
    ElMessage.error('加载配置失败: ' + getErrorMessage(error))
  }
})
</script>

<style scoped>
.settings-page {
  padding: 0;
}

.mt-4 {
  margin-top: 20px;
}

.mb-4 {
  margin-bottom: 16px;
}

.form-hint {
  margin-left: 8px;
  color: #909399;
}

.card-header-inline {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.profile-toolbar {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.profile-select {
  width: 320px;
  max-width: 100%;
}

.db-actions {
  margin-top: 20px;
  display: flex;
  gap: 12px;
}

@media (max-width: 768px) {
  .profile-toolbar {
    flex-direction: column;
  }

  .profile-select {
    width: 100%;
  }

  .db-actions {
    flex-direction: column;
  }

  .settings-page :deep(.el-col + .el-col) {
    margin-top: 12px;
  }

  .settings-page :deep(.el-form-item__label) {
    margin-bottom: 4px;
  }

  .settings-page :deep(.el-input-number),
  .settings-page :deep(.el-select) {
    width: 100%;
  }

  .settings-page :deep(.el-form-item .el-button),
  .profile-toolbar :deep(.el-button),
  .db-actions :deep(.el-button) {
    min-height: 42px;
    margin-left: 0;
  }

  .profile-toolbar :deep(.el-button),
  .db-actions :deep(.el-button) {
    width: 100%;
  }
}
</style>
