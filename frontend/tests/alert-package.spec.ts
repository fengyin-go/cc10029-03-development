import { expect, test } from '@playwright/test'

/**
 * 告警关联处置数据包验收：
 * - 告警中心结果页按看板展示，列表随处置结论变化；
 * - 同一监控对象重复触发归入同一处置主事件，不重复建包；
 * - 未关联到事件的规则不能进入处置包；
 * - 连续两次相同提交只保留一份；
 * - 运行监控同步监控事件清单，时间范围、错误次数与主事件一致，可按监控对象查看。
 */

const BATCH = `BATCH-E2E-${Date.now()}`
const TARGET = 'E2E验收对象'

function hit(rule: string, type: string, time: string, seq: number, errors: number, note = '') {
  return {
    命中编号: `${rule}-H${seq}`,
    规则编号: rule,
    监控对象: TARGET,
    事件类型: type,
    触发时间: time,
    序列: seq,
    错误次数: errors,
    明细说明: note,
  }
}

function packagePayload(batch: string, hits: ReturnType<typeof hit>[], endTime: string, errors: number) {
  return {
    采集批次: batch,
    监控对象: TARGET,
    规则命中明细: hits,
    监控事件快照: {
      事件时间范围: { 开始: '2026-11-17 08:00:00', 结束: endTime },
      错误次数: errors,
      监控对象: TARGET,
      采集批次: batch,
    },
  }
}

test('告警中心：看板展示、重复触发归并、重复提交去重', async ({ page, request }) => {
  // 第一次提交：同一规则两次触发，应只形成一个处置主事件
  const first = packagePayload(
    BATCH,
    [
      hit('ALER-0001', '触发', '2026-11-17 08:00:00', 1, 3, '首次触发'),
      hit('ALER-0001', '触发', '2026-11-17 08:30:00', 2, 2, '重复触发'),
    ],
    '2026-11-17 08:30:00',
    5,
  )
  const r1 = await request.post('/api/alert/packages', { data: first })
  expect(r1.ok()).toBeTruthy()
  const body1 = await r1.json()
  expect(body1.ok).toBeTruthy()
  expect(body1.entry.处置主事件).toHaveLength(1)
  expect(body1.entry.处置主事件[0].命中次数).toBe(2)
  const packageId = body1.entry.id

  // 未关联到事件的规则不能进入处置包
  const bad = packagePayload(
    `${BATCH}-BAD`,
    [hit('ALER-9999', '触发', '2026-11-17 08:00:00', 1, 1)],
    '2026-11-17 08:00:00',
    1,
  )
  const rBad = await request.post('/api/alert/packages', { data: bad })
  const badBody = await rBad.json()
  expect(badBody.ok).toBeFalsy()
  expect(badBody.entry.code).toBe('RULE_NOT_ASSOCIATED')

  // 后续触发写入明细，不重复建包
  const follow = packagePayload(
    BATCH,
    [hit('ALER-0001', '触发', '2026-11-17 09:00:00', 3, 4, '第三次触发')],
    '2026-11-17 09:00:00',
    9,
  )
  const r2 = await request.post('/api/alert/packages', { data: follow })
  const body2 = await r2.json()
  expect(body2.entry.id).toBe(packageId)
  expect(body2.entry.处置主事件).toHaveLength(1)
  expect(body2.entry.处置主事件[0].命中次数).toBe(3)
  expect(body2.entry.版本).toBe(2)

  // 连续两次完全相同的提交，第二次冲突，只保留一份
  const dup = packagePayload(
    `${BATCH}-DUP`,
    [hit('ALER-0001', '触发', '2026-11-17 08:00:00', 1, 2)],
    '2026-11-17 08:00:00',
    2,
  )
  const d1 = await request.post('/api/alert/packages', { data: dup })
  expect(d1.ok()).toBeTruthy()
  const d2 = await request.post('/api/alert/packages', { data: dup })
  expect(d2.status()).toBe(409)
  const d2Body = await d2.json()
  expect(d2Body.detail.code).toBe('PACKAGE_VERSION_CONFLICT')

  // 页面：切换到关联处置包，看板与列表呈现
  await page.goto('/alert')
  await page.getByTestId('tab-packages').click()
  await page.getByTestId('pkg-kanban').waitFor()
  await expect(page.locator('.kanban-col')).toHaveCount(3)
  await page.getByTestId('pkg-filter-batch').fill(BATCH)
  await page.getByTestId('pkg-query').click()
  const rows = page.locator(`[data-testid="pkg-row-${packageId}"]`)
  await expect(rows).toHaveCount(1)

  // 详情：核对重复触发被归入同一主事件
  await page.getByTestId(`pkg-detail-${packageId}`).click()
  await page.getByTestId('pkg-detail-modal').waitFor()
  const mainEvent = page.getByTestId('main-event-AME-0001')
  await expect(mainEvent).toBeVisible()
  await expect(mainEvent.locator('tbody tr')).toHaveCount(3)
})

test('运行监控：同步监控事件清单且按监控对象过滤', async ({ page, request }) => {
  const batch = `BATCH-E2E-MON-${Date.now()}`
  const payload = packagePayload(
    batch,
    [
      hit('ALER-0002', '触发', '2026-11-17 10:00:00', 1, 4),
      hit('ALER-0002', '恢复', '2026-11-17 10:45:00', 2, 0, '最终恢复'),
    ],
    '2026-11-17 10:45:00',
    4,
  )
  const resp = await request.post('/api/alert/packages', { data: payload })
  expect(resp.ok()).toBeTruthy()

  const eventsResp = await request.get('/api/monitor/alert-events')
  const eventsBody = await eventsResp.json()
  const event = eventsBody.items.find((e: any) => e.采集批次 === batch)
  expect(event).toBeTruthy()
  expect(event.错误次数).toBe(4)
  expect(event.时间范围).toEqual({ 开始: '2026-11-17 10:00:00', 结束: '2026-11-17 10:45:00' })
  expect(event.处置状态).toBe('已恢复')

  await page.goto('/monitor')
  const panel = page.getByTestId('alert-event-panel')
  await panel.waitFor()
  await expect(panel.locator('tbody tr').first()).toBeVisible()
  await page.getByTestId('alert-event-filter').fill(TARGET)
  await panel.getByRole('button', { name: '查询' }).click()
  await expect(panel.locator('tbody tr')).toHaveCount(
    eventsBody.items.filter((e: any) => e.监控对象 === TARGET).length,
  )
})
