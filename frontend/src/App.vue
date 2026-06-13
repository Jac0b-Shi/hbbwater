<template>
  <router-view v-if="isAuthLayout" />

  <div v-else class="app-wrapper">
    <el-container class="main-container">
      <el-aside v-if="!isMobile" :width="isCollapse ? '64px' : '220px'" class="sidebar">
        <app-navigation :collapsed="isCollapse" />
      </el-aside>

      <el-drawer
        v-if="isMobile"
        v-model="mobileMenuVisible"
        direction="ltr"
        size="min(86vw, 320px)"
        :with-header="false"
        class="mobile-navigation-drawer"
      >
        <app-navigation @navigate="mobileMenuVisible = false" />
      </el-drawer>

      <el-container>
        <el-header class="main-header">
          <div class="header-left">
            <el-button
              v-if="isMobile"
              text
              class="collapse-btn"
              aria-label="打开导航菜单"
              data-testid="mobile-menu-button"
              @click="mobileMenuVisible = true"
            >
              <el-icon><Menu /></el-icon>
            </el-button>
            <el-button v-else text class="collapse-btn" :aria-label="isCollapse ? '展开侧边栏' : '折叠侧边栏'" @click="toggleCollapse">
              <el-icon><Fold v-if="!isCollapse" /><Expand v-else /></el-icon>
            </el-button>
            <breadcrumb v-if="!isMobile" />
            <span v-else class="mobile-page-title">{{ route.meta.title }}</span>
          </div>
          <div class="header-right">
            <el-tag v-if="!isMobile && !accountStore.canManageSensors" effect="plain" round>只读模式</el-tag>
            <el-tooltip content="刷新数据" placement="bottom">
              <el-icon class="header-icon" @click="refreshData"><Refresh /></el-icon>
            </el-tooltip>
            <el-tooltip v-if="!isMobile" content="全屏" placement="bottom">
              <el-icon class="header-icon" @click="toggleFullscreen"><FullScreen /></el-icon>
            </el-tooltip>
            <el-dropdown trigger="click">
              <span class="user-info">
                <el-avatar :size="32" :src="accountStore.avatarUrl" :icon="UserFilled" />
                <span v-if="!isMobile" class="username">{{ accountStore.displayName }}</span>
                <el-icon v-if="!isMobile"><ArrowDown /></el-icon>
              </span>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item @click="$router.push('/profile')">个人设置</el-dropdown-item>
                  <el-dropdown-item v-if="accountStore.canManageUsers" @click="$router.push('/users')">用户管理</el-dropdown-item>
                  <el-dropdown-item v-if="accountStore.canAccessSettings" @click="$router.push('/settings')">系统设置</el-dropdown-item>
                  <el-dropdown-item divided @click="handleLogout">退出登录</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </el-header>

        <el-main class="main-content">
          <router-view v-slot="{ Component }">
            <transition name="fade-transform" mode="out-in">
              <component :is="Component" />
            </transition>
          </router-view>
        </el-main>
      </el-container>
    </el-container>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAccountStore } from './stores/account'
import Breadcrumb from './components/Breadcrumb.vue'
import AppNavigation from './components/AppNavigation.vue'
import { useResponsive } from './composables/useResponsive'

const route = useRoute()
const router = useRouter()
const accountStore = useAccountStore()
const { isMobile } = useResponsive()

const isCollapse = ref(false)
const mobileMenuVisible = ref(false)

const isAuthLayout = computed(() => route.meta.layout === 'auth')

watch(() => route.fullPath, () => {
  mobileMenuVisible.value = false
})

const toggleCollapse = () => {
  isCollapse.value = !isCollapse.value
}

const refreshData = () => {
  window.location.reload()
}

const toggleFullscreen = () => {
  if (!document.fullscreenElement) {
    document.documentElement.requestFullscreen()
  } else {
    document.exitFullscreen()
  }
}

const handleLogout = async () => {
  await accountStore.logout()
  router.push('/login')
}
</script>

<style scoped>
.app-wrapper {
  height: 100vh;
  height: 100dvh;
  width: 100vw;
  overflow: hidden;
}

.main-container {
  height: 100%;
}

.sidebar {
  transition: width 0.2s ease;
  overflow: hidden;
}

.main-header {
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  box-shadow: 0 1px 4px rgba(0,0,0,0.08);
  z-index: 100;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.collapse-btn {
  padding: 0;
  font-size: 20px;
  cursor: pointer;
  color: #606266;
}

.collapse-btn:hover {
  color: #409eff;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 20px;
}

.mobile-page-title {
  max-width: 45vw;
  overflow: hidden;
  color: #303133;
  font-size: 16px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-icon {
  font-size: 20px;
  cursor: pointer;
  color: #606266;
}

.header-icon:hover {
  color: #409eff;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.username {
  font-size: 14px;
  color: #606266;
}

.main-content {
  background: #f0f2f5;
  padding: 20px;
  overflow-y: auto;
}

.fade-transform-enter-active,
.fade-transform-leave-active {
  transition: all 0.3s;
}

.fade-transform-enter-from {
  opacity: 0;
  transform: translateX(-20px);
}

.fade-transform-leave-to {
  opacity: 0;
  transform: translateX(20px);
}

:global(.mobile-navigation-drawer .el-drawer__body) {
  padding: 0;
}

@media (max-width: 767px) {
  .main-header {
    padding: 0 12px;
  }

  .header-left {
    min-width: 0;
    gap: 12px;
  }

  .header-right {
    gap: 14px;
  }

  .header-icon,
  .collapse-btn {
    min-width: 28px;
    min-height: 44px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }

  .main-content {
    padding: 12px;
    padding-right: max(12px, env(safe-area-inset-right));
    padding-bottom: max(12px, env(safe-area-inset-bottom));
    padding-left: max(12px, env(safe-area-inset-left));
  }

  .fade-transform-enter-from,
  .fade-transform-leave-to {
    transform: translateY(8px);
  }
}
</style>
