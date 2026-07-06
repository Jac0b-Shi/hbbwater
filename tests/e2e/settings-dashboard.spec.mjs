import { test, expect } from '@playwright/test'

test.describe('settings and dashboard regressions', () => {
  test('dashboard renders readable recent alerts', async ({ page }) => {
    await page.route('**/api/dashboard/stats', async route => {
      await route.fulfill({
        json: {
          total_sensors: 1,
          online_sensors: 0,
          offline_sensors: 1,
          active_alerts: 1,
          today_readings: 0,
          ultrasonic_sensors: 1,
          immersion_sensors: 0
        }
      })
    })
    await page.route('**/api/dashboard/recent-readings*', async route => {
      await route.fulfill({ json: [] })
    })
    await page.route('**/api/dashboard/sensor-status', async route => {
      await route.fulfill({ json: [] })
    })
    await page.route('**/api/dashboard/alerts/recent*', async route => {
      await route.fulfill({
        json: [
          {
            id: 1,
            sensor_id: '1',
            location: '1号楼地下室',
            alert_type: 'sensor_offline',
            severity: 'high',
            message: '传感器 1 已离线超过 60 分钟',
            created_at: '2026-04-07T00:00:00'
          }
        ]
      })
    })

    await page.goto('/dashboard')

    await expect(page.getByText('最新告警')).toBeVisible()
    await expect(page.getByText('传感器 1 已离线超过 60 分钟')).toBeVisible()
  })

  test('settings keeps saved smtp secret server-side and can test with only target email', async ({ page }) => {
    let notificationSaveCalls = 0
    let testEmailPayload = null

    await page.route('**/api/config/system', async route => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          json: {
            data_retention_days: 14,
            offline_timeout_minutes: 60,
            alert_cooldown_minutes: 30,
            archive_enabled: true,
            summary_enabled: true
          }
        })
        return
      }
      await route.fulfill({ json: { message: '系统配置已保存' } })
    })

    await page.route('**/api/config/notification', async route => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          json: {
            email_enabled: true,
            smtp_host: 'smtp.example.com',
            smtp_port: 465,
            smtp_user: 'sender@example.com',
            smtp_password_set: true,
            smtp_ssl: true,
            webhook_enabled: false,
            webhook_url: ''
          }
        })
        return
      }

      notificationSaveCalls += 1
      await route.fulfill({ json: { message: '通知配置已保存' } })
    })

    await page.route('**/api/config/database/stats', async route => {
      await route.fulfill({
        json: {
          readings_count: 0,
          archive_count: 0,
          hourly_count: 0,
          daily_count: 0
        }
      })
    })

    await page.route('**/api/forecast-alerts/config', async route => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          json: {
            global_config: {
              enabled: false,
              cooldown_minutes: 120,
              default_horizon_hours: 6,
              model_params: {}
            },
            profiles: [{
              id: null,
              sensor_id: 'ultrasonic_002',
              sensor_location: 'D楼',
              sensor_type: 'ultrasonic',
              is_enabled: false,
              station_id: null,
              horizon_hours: 6,
              warning_rise_mm: null,
              critical_rise_mm: null,
              model_params: null,
              pump_params: null,
              actuator_binding_id: null,
              created_at: null,
              updated_at: null
            }],
            stations: []
          }
        })
        return
      }
      await route.fulfill({ json: { message: '预报配置已保存' } })
    })

    await page.route('**/api/forecast-alerts/latest', async route => {
      await route.fulfill({ json: null })
    })

    await page.route('**/api/forecast-alerts/evaluate', async route => {
      await route.fulfill({
        json: {
          id: 1,
          trigger_type: 'manual',
          dry_run: true,
          status: 'completed',
          message: '已评估 1 个传感器',
          forecast_issued_at: null,
          started_at: '2026-06-23T00:00:00',
          completed_at: '2026-06-23T00:00:01',
          created_by: 'admin',
          source: {},
          created_at: '2026-06-23T00:00:00',
          results: []
        }
      })
    })

    await page.route('**/api/config/notification/test-email', async route => {
      testEmailPayload = route.request().postDataJSON()
      await route.fulfill({
        json: {
          message: '测试邮件已发送到 target@example.com'
        }
      })
    })

    await page.goto('/settings')

    const passwordInput = page.locator('input[name="smtp-password-config"]')
    await expect(passwordInput).toHaveValue('')
    await expect(page.getByText('授权码已保存在服务器端；留空则保持不变')).toBeVisible()

    await page.getByPlaceholder('接收测试邮件的邮箱地址').fill('target@example.com')
    await page.getByRole('button', { name: '测试邮件' }).click()

    await expect.poll(() => testEmailPayload).not.toBeNull()
    expect(testEmailPayload).toEqual({ to: 'target@example.com' })
    expect(notificationSaveCalls).toBe(0)
  })
})
