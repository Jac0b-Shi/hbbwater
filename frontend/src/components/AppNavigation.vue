<template>
  <div class="app-navigation" :class="{ 'is-collapsed': collapsed }">
    <div class="logo">
      <el-icon size="32"><Drizzling /></el-icon>
      <span v-if="!collapsed" class="logo-text">水浸监测系统</span>
    </div>

    <el-menu
      :default-active="activeMenu"
      class="navigation-menu"
      :collapse="collapsed"
      :collapse-transition="false"
      router
      @select="$emit('navigate')"
    >
      <el-menu-item index="/">
        <el-icon><Odometer /></el-icon>
        <template #title>监控仪表盘</template>
      </el-menu-item>

      <el-menu-item index="/water-map">
        <el-icon><LocationFilled /></el-icon>
        <template #title>水位地图</template>
      </el-menu-item>

      <el-sub-menu index="/sensors">
        <template #title>
          <el-icon><Cpu /></el-icon>
          <span>传感器管理</span>
        </template>
        <el-menu-item index="/sensors">全部传感器</el-menu-item>
        <el-menu-item index="/sensors/ultrasonic">超声波传感器</el-menu-item>
        <el-menu-item index="/sensors/immersion">浸水传感器</el-menu-item>
      </el-sub-menu>

      <el-menu-item index="/alerts">
        <el-icon><Bell /></el-icon>
        <template #title>
          <span>告警管理</span>
          <el-badge v-if="alertStore.unresolvedCount > 0" :value="alertStore.unresolvedCount" class="alert-badge" />
        </template>
      </el-menu-item>

      <el-menu-item index="/history">
        <el-icon><TrendCharts /></el-icon>
        <template #title>历史数据</template>
      </el-menu-item>

      <el-menu-item v-if="accountStore.canManageUsers" index="/users">
        <el-icon><UserFilled /></el-icon>
        <template #title>用户管理</template>
      </el-menu-item>

      <el-menu-item v-if="accountStore.canAccessSettings" index="/settings">
        <el-icon><Setting /></el-icon>
        <template #title>系统设置</template>
      </el-menu-item>
    </el-menu>

    <div v-if="!collapsed" class="navigation-footer">
      <el-tag size="small" type="info">{{ accountStore.roleLabel }}</el-tag>
      <el-text type="info" size="small">{{ APP_VERSION }}</el-text>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAccountStore } from '../stores/account'
import { useAlertStore } from '../stores/alerts'
import { APP_VERSION } from '../constants/appMeta'

defineProps({
  collapsed: {
    type: Boolean,
    default: false
  }
})

defineEmits(['navigate'])

const route = useRoute()
const accountStore = useAccountStore()
const alertStore = useAlertStore()
const activeMenu = computed(() => route.path)
</script>

<style scoped>
.app-navigation {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
  color: #fff;
}

.logo {
  height: 64px;
  flex: 0 0 64px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.logo-text {
  font-size: 18px;
  font-weight: 600;
  color: #fff;
  white-space: nowrap;
}

.navigation-menu {
  flex: 1;
  border-right: none;
  background: transparent;
  overflow-y: auto;
  overflow-x: hidden;
}

.navigation-menu:not(.el-menu--collapse) {
  width: 100%;
}

.navigation-menu :deep(.el-menu-item),
.navigation-menu :deep(.el-sub-menu__title) {
  color: #a6aab3;
}

.navigation-menu :deep(.el-menu-item:hover),
.navigation-menu :deep(.el-sub-menu__title:hover) {
  background: rgba(255, 255, 255, 0.05);
  color: #fff;
}

.navigation-menu :deep(.el-menu-item.is-active) {
  background: linear-gradient(90deg, rgba(64, 158, 255, 0.2) 0%, transparent 100%);
  color: #409eff;
  border-right: 3px solid #409eff;
}

.navigation-menu :deep(.el-menu) {
  background: rgba(0, 0, 0, 0.12);
}

.navigation-footer {
  padding: 16px;
  text-align: center;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  display: grid;
  gap: 10px;
}

.alert-badge :deep(.el-badge__content) {
  top: 10px;
  right: -22px;
}
</style>
