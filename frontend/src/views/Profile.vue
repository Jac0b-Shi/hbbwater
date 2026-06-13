<template>
  <div class="profile-page">
    <el-row :gutter="20" v-loading="accountStore.loading">
      <el-col :xs="24" :md="8">
        <el-card shadow="hover" class="profile-card">
          <div class="profile-header">
            <el-avatar :size="100" :src="accountStore.avatarUrl" :icon="UserFilled" />
            <h3>{{ accountStore.displayName }}</h3>
            <p class="profile-role">{{ accountStore.roleLabel }}</p>
          </div>
          <div class="profile-info">
            <p><el-icon><Message /></el-icon> {{ accountStore.profile?.email || '-' }}</p>
            <p><el-icon><Phone /></el-icon> {{ accountStore.profile?.phone || '未设置' }}</p>
            <p><el-icon><Timer /></el-icon> 注册时间：{{ createdAtText }}</p>
            <p><el-icon><Connection /></el-icon> 认证方式：{{ accountStore.authProviderLabel }}</p>
            <p><el-icon><Key /></el-icon> 权限：{{ permissionSummary }}</p>
          </div>
        </el-card>
      </el-col>
      
      <el-col :xs="24" :md="16">
        <el-card shadow="hover">
          <template #header>
            <span>编辑资料</span>
          </template>
          <el-alert
            v-if="accountStore.profile && !accountStore.profile.can_update_profile"
            title="当前认证方式下，个人资料由上游身份系统维护"
            type="info"
            show-icon
            :closable="false"
            class="mb-4"
          />
          <el-form :model="profileForm" :label-width="isMobile ? 'auto' : '100px'" :label-position="isMobile ? 'top' : 'right'" :disabled="accountStore.profile && !accountStore.profile.can_update_profile">
            <el-form-item label="登录名">
              <el-input v-model="profileForm.username" placeholder="请输入用户名" />
            </el-form-item>
            <el-form-item label="显示名称">
              <el-input v-model="profileForm.display_name" placeholder="请输入显示名称" />
            </el-form-item>
            <el-form-item label="邮箱">
              <el-input v-model="profileForm.email" placeholder="请输入邮箱，用于 Gravatar 头像" />
            </el-form-item>
            <el-form-item label="手机号">
              <el-input v-model="profileForm.phone" placeholder="请输入手机号" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="accountStore.saving" @click="saveProfile">保存修改</el-button>
            </el-form-item>
          </el-form>
        </el-card>
        
        <el-card shadow="hover" class="mt-4">
          <template #header>
            <span>{{ accountStore.profile?.password_initialized ? '修改密码' : '初始化密码' }}</span>
          </template>
          <el-alert
            v-if="!accountStore.profile?.can_change_password"
            title="当前认证方式不支持在本系统内修改密码"
            type="info"
            show-icon
            :closable="false"
            class="mb-4"
          />
          <el-alert
            v-else-if="accountStore.profile && !accountStore.profile.password_initialized"
            title="当前账户尚未设置本地密码，首次设置时无需填写当前密码"
            type="warning"
            show-icon
            :closable="false"
            class="mb-4"
          />
          <el-form :model="passwordForm" :label-width="isMobile ? 'auto' : '100px'" :label-position="isMobile ? 'top' : 'right'" :disabled="!accountStore.profile?.can_change_password">
            <el-form-item :label="accountStore.profile?.password_initialized ? '当前密码' : '当前密码(留空)'">
              <el-input v-model="passwordForm.current" type="password" show-password :placeholder="accountStore.profile?.password_initialized ? '请输入当前密码' : '首次设置时可留空'" />
            </el-form-item>
            <el-form-item label="新密码">
              <el-input v-model="passwordForm.new" type="password" show-password placeholder="请输入新密码" />
            </el-form-item>
            <el-form-item label="确认密码">
              <el-input v-model="passwordForm.confirm" type="password" show-password placeholder="请再次输入新密码" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="accountStore.saving" @click="changePassword">修改密码</el-button>
            </el-form-item>
          </el-form>
        </el-card>

        <el-card shadow="hover" class="mt-4">
          <template #header>
            <span>认证与权限</span>
          </template>
          <div class="provider-list">
            <div
              v-for="provider in accountStore.providers"
              :key="provider.id"
              class="provider-item"
              :class="{ active: provider.id === accountStore.profile?.auth_provider }"
            >
              <div>
                <strong>{{ provider.label }}</strong>
                <p>{{ provider.id === 'campus_sso' ? '用于后续接入学校统一身份认证' : '当前默认账户提供者' }}</p>
              </div>
              <el-tag :type="provider.enabled ? 'success' : 'info'">
                {{ provider.enabled ? '已启用' : '预留中' }}
              </el-tag>
            </div>
          </div>
          <el-divider />
          <div class="permission-chips">
            <el-tag v-for="permission in accountStore.permissions" :key="permission" effect="plain">
              {{ permission }}
            </el-tag>
            <el-tag v-if="!accountStore.permissions.length" effect="plain" type="info">
              只读访问
            </el-tag>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { UserFilled, Message, Phone, Timer, Connection, Key } from '@element-plus/icons-vue'
import { useAccountStore } from '../stores/account'
import { validatePassword } from '../utils/password'
import { useResponsive } from '../composables/useResponsive'
import { formatUtc8DateTime } from '../utils/time'

const accountStore = useAccountStore()
const { isMobile } = useResponsive()
const profileForm = ref({
  username: '',
  display_name: '',
  email: '',
  phone: '',
})

const passwordForm = ref({
  current: '',
  new: '',
  confirm: ''
})

const createdAtText = computed(() => {
  const value = accountStore.profile?.created_at
  return formatUtc8DateTime(value, 'YYYY-MM-DD HH:mm')
})

const permissionSummary = computed(() => {
  if (!accountStore.permissions.length) {
    return '只读访问'
  }
  return accountStore.permissions.join(' / ')
})

function syncProfileForm() {
  const profile = accountStore.profile
  if (!profile) return

  profileForm.value = {
    username: profile.username || '',
    display_name: profile.display_name || '',
    email: profile.email || '',
    phone: profile.phone || ''
  }
}

const saveProfile = async () => {
  try {
    await accountStore.updateProfile(profileForm.value)
    syncProfileForm()
    ElMessage.success('资料已保存')
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '资料保存失败')
  }
}

const changePassword = async () => {
  if (passwordForm.value.new !== passwordForm.value.confirm) {
    ElMessage.error('两次输入的密码不一致')
    return
  }

  const passwordError = validatePassword(passwordForm.value.new, {
    requiredMessage: '请输入新密码',
    minimumMessage: '新密码长度不能少于 8 位'
  })
  if (passwordError) {
    ElMessage.error(passwordError)
    return
  }

  try {
    await accountStore.changePassword({
      current_password: passwordForm.value.current.trim(),
      new_password: passwordForm.value.new
    })
    ElMessage.success('密码已修改')
    passwordForm.value = { current: '', new: '', confirm: '' }
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '密码修改失败')
  }
}

onMounted(async () => {
  if (!accountStore.profile) {
    try {
      await accountStore.fetchProfile()
    } catch (err) {
      ElMessage.error(err.response?.data?.detail || '账户信息加载失败')
    }
  }
  syncProfileForm()
})

watch(() => accountStore.profile, syncProfileForm)
</script>

<style scoped>
.profile-page {
  padding: 0;
}

.profile-card {
  text-align: center;
}

.profile-header {
  padding: 20px 0;
}

.profile-header h3 {
  margin: 16px 0 8px;
  font-size: 20px;
}

.profile-role {
  color: #909399;
  font-size: 14px;
  margin: 0;
}

.profile-info {
  text-align: left;
  padding: 20px;
  border-top: 1px solid #ebeef5;
}

.profile-info p {
  margin: 12px 0;
  color: #606266;
  display: flex;
  align-items: center;
  gap: 8px;
}

.provider-list {
  display: grid;
  gap: 12px;
}

.permission-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.provider-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  border: 1px solid #ebeef5;
  border-radius: 12px;
  background: #fafafa;
}

.provider-item.active {
  border-color: #409eff;
  background: #ecf5ff;
}

.provider-item p {
  margin: 6px 0 0;
  color: #909399;
  font-size: 13px;
}

.mb-4 {
  margin-bottom: 16px;
}

.mt-4 {
  margin-top: 20px;
}

@media (max-width: 767px) {
  .profile-page :deep(.el-col + .el-col) {
    margin-top: 12px;
  }

  .profile-info {
    padding: 16px 8px;
  }

  .profile-info p {
    align-items: flex-start;
    overflow-wrap: anywhere;
  }

  .provider-item {
    align-items: flex-start;
    flex-direction: column;
  }

  .profile-page :deep(.el-form-item__label) {
    margin-bottom: 4px;
  }

  .profile-page :deep(.el-form-item .el-button) {
    width: 100%;
    min-height: 42px;
    margin-left: 0;
  }
}
</style>
