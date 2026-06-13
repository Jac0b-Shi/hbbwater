<template>
  <div class="users-page">
    <el-card shadow="hover">
      <template #header>
        <div class="page-header">
          <div>
            <h2>用户管理</h2>
            <p>超级管理员可维护账号状态、重置初始密码并调整角色权限。</p>
          </div>
          <el-button type="primary" @click="openCreateDialog">
            <el-icon><Plus /></el-icon>新增用户
          </el-button>
        </div>
      </template>

      <el-table v-if="!isMobile" v-loading="accountStore.loading" :data="accountStore.users" stripe>
        <el-table-column prop="display_name" label="显示名称" min-width="180" />
        <el-table-column prop="username" label="登录名" min-width="140" />
        <el-table-column prop="email" label="邮箱" min-width="220" />
        <el-table-column prop="role_label" label="角色" width="140">
          <template #default="{ row }">
            <el-tag :type="roleTagType(row.role)">{{ row.role_label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="is_active" label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '停用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="权限摘要" min-width="260">
          <template #default="{ row }">
            <el-space wrap>
              <el-tag v-for="permission in row.permissions" :key="permission" effect="plain" size="small">
                {{ permission }}
              </el-tag>
              <span v-if="!row.permissions.length" class="permission-empty">仅查看</span>
            </el-space>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link @click="openEditDialog(row)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-else v-loading="accountStore.loading" class="user-card-list">
        <article v-for="user in accountStore.users" :key="user.id" class="user-card">
          <div class="user-card-head">
            <div>
              <strong>{{ user.display_name }}</strong>
              <div>@{{ user.username }}</div>
            </div>
            <el-tag :type="user.is_active ? 'success' : 'info'">{{ user.is_active ? '启用' : '停用' }}</el-tag>
          </div>
          <dl class="user-card-fields">
            <div><dt>邮箱</dt><dd>{{ user.email }}</dd></div>
            <div><dt>角色</dt><dd><el-tag size="small" :type="roleTagType(user.role)">{{ user.role_label }}</el-tag></dd></div>
          </dl>
          <div class="permission-list">
            <el-tag v-for="permission in user.permissions" :key="permission" effect="plain" size="small">
              {{ permission }}
            </el-tag>
            <span v-if="!user.permissions.length" class="permission-empty">仅查看</span>
          </div>
          <el-button type="primary" plain class="user-edit-button" @click="openEditDialog(user)">编辑用户</el-button>
        </article>
        <el-empty v-if="accountStore.users.length === 0" description="暂无用户" />
      </div>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="editingUser ? '编辑用户' : '新增用户'" :width="dialogWidth">
      <el-form ref="formRef" :model="form" :rules="rules" :label-width="isMobile ? 'auto' : '110px'" :label-position="isMobile ? 'top' : 'right'">
        <el-form-item label="登录名" prop="username">
          <el-input v-model="form.username" :disabled="Boolean(editingUser)" placeholder="用于登录系统" />
        </el-form-item>
        <el-form-item label="显示名称" prop="display_name">
          <el-input v-model="form.display_name" placeholder="界面显示名称" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="form.email" placeholder="name@example.com" />
        </el-form-item>
        <el-form-item label="手机号">
          <el-input v-model="form.phone" placeholder="可选" />
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-select v-model="form.role" style="width: 100%">
            <el-option
              v-for="roleItem in accountStore.roles"
              :key="roleItem.id"
              :label="`${roleItem.label} - ${roleItem.description}`"
              :value="roleItem.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="form.is_active" :disabled="isEditingCurrentUser" />
        </el-form-item>
        <el-form-item :label="editingUser ? '重置密码' : '初始密码'" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            :placeholder="editingUser ? '留空表示不修改' : '至少 8 位'"
          />
        </el-form-item>
        <el-alert
          v-if="isEditingCurrentUser"
          title="当前登录账号不能在此页面停用或修改自己的角色。"
          type="warning"
          :closable="false"
        />
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="accountStore.saving" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'

import { useAccountStore } from '../stores/account'
import { validatePassword } from '../utils/password'
import { useResponsive } from '../composables/useResponsive'

const accountStore = useAccountStore()
const { isMobile } = useResponsive()
const dialogVisible = ref(false)
const editingUser = ref(null)
const formRef = ref(null)

const buildDefaultForm = () => ({
  username: '',
  display_name: '',
  email: '',
  phone: '',
  role: 'user',
  password: '',
  is_active: true
})

const form = ref(buildDefaultForm())

const isEditingCurrentUser = computed(() => editingUser.value?.id === accountStore.profile?.id)
const dialogWidth = computed(() => isMobile.value ? 'calc(100vw - 24px)' : '560px')

const rules = {
  username: [{ required: true, message: '请输入登录名', trigger: 'blur' }],
  display_name: [{ required: true, message: '请输入显示名称', trigger: 'blur' }],
  email: [{ required: true, message: '请输入邮箱', trigger: 'blur' }],
  role: [{ required: true, message: '请选择角色', trigger: 'change' }],
  password: [{
    validator: (_, value, callback) => {
      const error = validatePassword(value, {
        required: !editingUser.value,
        requiredMessage: '请输入初始密码',
        minimumMessage: editingUser.value ? '新密码长度不能少于 8 位' : '初始密码长度不能少于 8 位'
      })
      callback(error ? new Error(error) : undefined)
    },
    trigger: 'blur'
  }]
}

const roleTagType = (role) => {
  if (role === 'super_admin') return 'danger'
  if (role === 'admin') return 'warning'
  return 'info'
}

const resetForm = () => {
  editingUser.value = null
  form.value = buildDefaultForm()
}

const openCreateDialog = () => {
  resetForm()
  dialogVisible.value = true
}

const openEditDialog = (user) => {
  editingUser.value = user
  form.value = {
    username: user.username,
    display_name: user.display_name,
    email: user.email,
    phone: user.phone || '',
    role: user.role,
    password: '',
    is_active: user.is_active
  }
  dialogVisible.value = true
}

const submitForm = async () => {
  await formRef.value.validate()

  try {
    if (editingUser.value) {
      const payload = {
        display_name: form.value.display_name.trim(),
        email: form.value.email.trim(),
        phone: form.value.phone.trim(),
        role: form.value.role,
        is_active: form.value.is_active
      }
      if (!isEditingCurrentUser.value) {
        payload.role = form.value.role
        payload.is_active = form.value.is_active
      }
      if (form.value.password) {
        payload.password = form.value.password
      }
      await accountStore.updateUser(editingUser.value.id, payload)
      ElMessage.success('用户已更新')
    } else {
      await accountStore.createUser({
        username: form.value.username.trim(),
        display_name: form.value.display_name.trim(),
        email: form.value.email.trim(),
        phone: form.value.phone.trim(),
        role: form.value.role,
        password: form.value.password,
        is_active: form.value.is_active
      })
      ElMessage.success('用户已创建')
    }
    dialogVisible.value = false
    resetForm()
    await accountStore.fetchUsers()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || accountStore.error || '保存失败')
  }
}

onMounted(async () => {
  try {
    if (!accountStore.roles.length) {
      await accountStore.fetchProfile(true)
    }
    await accountStore.fetchUsers()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || accountStore.error || '用户列表加载失败')
  }
})
</script>

<style scoped>
.users-page {
  padding: 0;
}

.page-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
}

.page-header h2 {
  margin: 0 0 8px;
  font-size: 18px;
  font-weight: 600;
}

.page-header p {
  margin: 0;
  color: #909399;
}

.permission-empty {
  color: #909399;
  font-size: 13px;
}

.user-card-list {
  min-height: 120px;
  display: grid;
  gap: 12px;
}

.user-card {
  padding: 14px;
  border: 1px solid #ebeef5;
  border-radius: 10px;
  background: #fff;
}

.user-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.user-card-head strong {
  color: #303133;
  font-size: 15px;
}

.user-card-head div div {
  margin-top: 5px;
  color: #909399;
  font-size: 12px;
}

.user-card-fields {
  margin: 14px 0 0;
  display: grid;
  gap: 8px;
}

.user-card-fields > div {
  display: grid;
  grid-template-columns: 56px minmax(0, 1fr);
  align-items: center;
  gap: 10px;
}

.user-card-fields dt,
.user-card-fields dd {
  margin: 0;
  font-size: 13px;
}

.user-card-fields dt {
  color: #909399;
}

.user-card-fields dd {
  color: #606266;
  overflow-wrap: anywhere;
}

.permission-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 12px;
}

.user-edit-button {
  width: 100%;
  min-height: 42px;
  margin-top: 14px;
}

@media (max-width: 768px) {
  .page-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .page-header :deep(.el-button) {
    width: 100%;
    min-height: 42px;
  }

  :deep(.el-dialog__body) {
    max-height: calc(100dvh - 160px);
    padding: 14px 16px;
    overflow-y: auto;
  }

  :deep(.el-dialog__footer .el-button) {
    min-width: 96px;
    min-height: 42px;
  }
}
</style>
