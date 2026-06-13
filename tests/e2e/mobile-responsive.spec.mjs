import { test, expect } from '@playwright/test'

const profile = {
  id: 'admin-1',
  username: 'admin',
  display_name: '管理员',
  email: 'admin@example.com',
  avatar_url: '',
  role: 'super_admin',
  role_label: '超级管理员',
  permissions: ['users:write', 'sensors:write', 'alerts:resolve', 'settings:write'],
}

async function mockAuthenticatedSession(page) {
  await page.addInitScript(() => {
    localStorage.setItem('hbbwater_access_token', 'mobile-test-token')
  })

  await page.route('**/api/account/me', route => route.fulfill({ json: profile }))
  await page.route('**/api/account/providers', route => route.fulfill({ json: { providers: [] } }))
  await page.route('**/api/account/roles', route => route.fulfill({ json: { roles: [] } }))
}

async function expectNoPageOverflow(page) {
  await expect.poll(() => page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))).toEqual({ scrollWidth: 390, clientWidth: 390 })
}

test.describe('mobile responsive layout', () => {
  test.use({ viewport: { width: 390, height: 844 } })

  test.beforeEach(async ({ page }) => {
    await mockAuthenticatedSession(page)
  })

  test('dashboard uses a drawer shell and mobile status cards', async ({ page }) => {
    await page.route('**/api/dashboard/stats', route => route.fulfill({
      json: {
        total_sensors: 1,
        online_sensors: 1,
        offline_sensors: 0,
        active_alerts: 0,
        today_readings: 12,
        ultrasonic_sensors: 1,
        immersion_sensors: 0,
      },
    }))
    await page.route('**/api/dashboard/recent-readings*', route => route.fulfill({ json: [] }))
    await page.route('**/api/dashboard/alerts/recent*', route => route.fulfill({ json: [] }))
    await page.route('**/api/dashboard/sensor-status', route => route.fulfill({
      json: [{
        sensor_id: 'ultrasonic_001',
        location: '一号楼地下室',
        sensor_type: 'ultrasonic',
        status: 'normal',
        is_online: true,
        water_level: 12.5,
        external_powered: false,
        battery_level: 86,
      }],
    }))
    await page.route('**/api/weather/rainfall/summary', route => route.fulfill({
      json: { selected_station_id: null, stations: [] },
    }))

    await page.goto('/')

    await expect(page.getByTestId('mobile-menu-button')).toBeVisible()
    await expect(page.locator('.sensor-status-card')).toContainText('ultrasonic_001')
    await expect(page.locator('.sensor-status-card')).toContainText('12.5 cm')
    await expect(page.locator('aside.sidebar')).toHaveCount(0)

    await page.getByTestId('mobile-menu-button').click()
    await expect(page.getByText('水位地图', { exact: true })).toBeVisible()
    await expect(page.getByRole('menuitem', { name: '系统设置' })).toBeVisible()
    await expectNoPageOverflow(page)
  })

  test('sensor management keeps mobile create and edit operations available', async ({ page }) => {
    await page.route('**/api/sensors/groups', route => route.fulfill({ json: [] }))
    await page.route('**/api/sensors/', route => route.fulfill({
      json: [{
        sensor_id: 'immersion_001',
        sensor_type: 'immersion',
        location: '二号楼配电间',
        description: '配电间地面积水监测',
        report_method: 'http_api',
        is_active: true,
        webhook_group_id: null,
        webhook_group_name: null,
      }],
    }))

    await page.goto('/sensors')

    await expect(page.locator('.standalone-sensor-list .sensor-card')).toContainText('immersion_001')
    await expect(page.locator('.standalone-sensor-list .sensor-card')).toContainText('配电间地面积水监测')
    await page.getByTestId('add-sensor-button').click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await expect(page.getByPlaceholder('如: immersion_001')).toBeVisible()
    await expectNoPageOverflow(page)
  })

  test('history uses server pagination and mobile record cards', async ({ page }) => {
    const readingRequests = []
    await page.route('**/api/sensors/', route => route.fulfill({
      json: [{
        sensor_id: 'ultrasonic_001',
        sensor_type: 'ultrasonic',
        location: '一号楼地下室',
        is_active: true,
      }],
    }))
    await page.route('**/api/sensors/ultrasonic_001/readings*', route => {
      const url = new URL(route.request().url())
      readingRequests.push({
        limit: Number(url.searchParams.get('limit')),
        page: Number(url.searchParams.get('page')),
      })
      return route.fulfill({
        json: {
          items: [{
            id: Number(url.searchParams.get('page') || 1),
            sensor_id: 'ultrasonic_001',
            sensor_type: 'ultrasonic',
            recorded_at: '2026-06-12T08:00:00',
            status: 'normal',
            water_level: 18.25,
            water_detected: null,
            external_powered: true,
            battery_level: null,
            signal_strength: -65,
          }],
          total: 240,
          page: Number(url.searchParams.get('page') || 1),
          page_size: Number(url.searchParams.get('limit')),
        },
      })
    })

    await page.goto('/history')
    await page.locator('.sensor-select').click()
    await page.getByText('ultrasonic_001 - 一号楼地下室', { exact: true }).click()
    await page.getByRole('button', { name: '查询' }).click()

    await expect(page.locator('.history-record-card')).toContainText('18.25 cm')
    await expect(page.locator('.el-pagination__total')).toContainText('240')
    expect(readingRequests).toEqual(expect.arrayContaining([
      { limit: 100, page: 1 },
      { limit: 2000, page: 1 },
    ]))

    await page.locator('.el-pagination .btn-next').click()
    await expect.poll(() => readingRequests.some(request => request.limit === 100 && request.page === 2)).toBe(true)
    await expectNoPageOverflow(page)
  })
})

test('desktop dashboard keeps the sidebar and data table', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 })
  await mockAuthenticatedSession(page)
  await page.route('**/api/dashboard/stats', route => route.fulfill({
    json: {
      total_sensors: 1,
      online_sensors: 1,
      offline_sensors: 0,
      active_alerts: 0,
      today_readings: 12,
      ultrasonic_sensors: 1,
      immersion_sensors: 0,
    },
  }))
  await page.route('**/api/dashboard/recent-readings*', route => route.fulfill({ json: [] }))
  await page.route('**/api/dashboard/alerts/recent*', route => route.fulfill({ json: [] }))
  await page.route('**/api/dashboard/sensor-status', route => route.fulfill({
    json: [{
      sensor_id: 'ultrasonic_001',
      location: '一号楼地下室',
      sensor_type: 'ultrasonic',
      status: 'normal',
      is_online: true,
      water_level: 12.5,
      external_powered: false,
      battery_level: 86,
    }],
  }))
  await page.route('**/api/weather/rainfall/summary', route => route.fulfill({
    json: { selected_station_id: null, stations: [] },
  }))

  await page.goto('/')

  await expect(page.locator('aside.sidebar')).toBeVisible()
  await expect(page.getByTestId('mobile-menu-button')).toHaveCount(0)
  await expect(page.locator('.status-card .el-table')).toBeVisible()
  await expect(page.locator('.sensor-status-card')).toHaveCount(0)
})

test('mobile login page remains vertically scrollable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/login')

  const loginButton = page.getByRole('button', { name: '登录系统' })
  await loginButton.scrollIntoViewIfNeeded()
  await expect(loginButton).toBeInViewport()
  expect(await page.evaluate(() => document.documentElement.scrollHeight > document.documentElement.clientHeight)).toBe(true)
})
