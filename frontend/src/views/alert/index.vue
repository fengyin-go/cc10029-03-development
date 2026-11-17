<template>
  <section class="page" data-module="alert">
    <header class="page-head">
      <div>
        <h2>告警中心管理</h2>
        <p class="page-desc">配置采集异常的告警触发条件、通知渠道和值班策略，并按采集批次归并生成告警关联处置数据包。</p>
      </div>
      <div class="page-actions">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          class="btn"
          :class="{ primary: activeTab === tab.key }"
          :data-testid="`tab-${tab.key}`"
          type="button"
          @click="switchTab(tab.key)"
        >
          {{ tab.label }}
        </button>
      </div>
    </header>

    <!-- ================================================== 告警规则（既有契约） -->
    <div v-if="activeTab === 'rules'">
      <div class="stat-row">
        <article v-for="item in stats" :key="item.label" class="stat-card">
          <span class="stat-label">{{ item.label }}</span>
          <strong class="stat-value">{{ item.value }}</strong>
        </article>
      </div>

      <form class="filter-bar" @submit.prevent="reload">
        <label v-for="field in filterFields" :key="field" class="filter-item">
          <span>{{ field }}</span>
          <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
        </label>
        <button class="btn" data-testid="query" type="submit">查询</button>
        <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
      </form>

      <div class="page-actions" style="margin-bottom: 10px">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">登记告警规则</button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">导出告警中心清单</button>
      </div>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in columns" :key="column">{{ column }}</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
            <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
            <td class="row-actions">
              <button
                v-for="action in actions"
                :key="action"
                class="link"
                type="button"
                :data-testid="`action-${row.id}-${action}`"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td :colspan="columns.length + 1" class="empty-state">暂无告警中心数据，可先登记告警规则</td>
          </tr>
        </tbody>
      </table>

      <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
        <form class="modal" @submit.prevent="submitCreate">
          <h3>登记告警规则</h3>
          <label v-for="field in columns" :key="field" class="create-field">
            <span>{{ field }}</span>
            <input v-model="createValues[field]" :data-testid="`create-${field}`" required />
          </label>
          <div class="page-actions">
            <button class="btn" type="button" @click="showCreate = false">取消</button>
            <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
              {{ creating ? '提交中…' : '确认登记' }}
            </button>
          </div>
        </form>
      </div>

      <footer class="page-foot">
        <span>共 {{ total }} 条告警中心记录</span>
        <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      </footer>
    </div>

    <!-- ================================================== 关联处置包 -->
    <div v-else>
      <div class="stat-row" data-testid="pkg-dashboard">
        <article v-for="card in dashboard.cards" :key="card.label" class="stat-card">
          <span class="stat-label">{{ card.label }}</span>
          <strong class="stat-value">{{ card.value }}</strong>
        </article>
      </div>

      <div class="kanban" data-testid="pkg-kanban">
        <article v-for="group in dashboard.groups" :key="group.状态" class="kanban-col" :data-state="group.状态">
          <header class="kanban-head">
            <strong>{{ group.状态 }}</strong>
            <span class="kanban-count">{{ group.items.length }}</span>
          </header>
          <div v-for="pkg in group.items" :key="pkg.id" class="kanban-card" :data-testid="`kanban-${pkg.id}`">
            <p class="kanban-title">{{ pkg.处置包编号 }} · v{{ pkg.版本 }}</p>
            <p class="kanban-meta">{{ pkg.监控对象 }}</p>
            <p class="kanban-meta">{{ pkg.采集批次 }} · 主事件 {{ pkg.主事件数 }} · 命中 {{ pkg.规则命中总数 }}</p>
            <button class="link" type="button" @click="openDetail(pkg.id)">查看关联处置包</button>
          </div>
          <p v-if="!group.items.length" class="empty-state">暂无处置包</p>
        </article>
      </div>

      <form class="filter-bar" @submit.prevent="reloadPackages">
        <label class="filter-item">
          <span>监控对象</span>
          <input v-model="pkgFilters.监控对象" data-testid="pkg-filter-target" placeholder="按监控对象检索" />
        </label>
        <label class="filter-item">
          <span>采集批次</span>
          <input v-model="pkgFilters.采集批次" data-testid="pkg-filter-batch" placeholder="按采集批次检索" />
        </label>
        <label class="filter-item">
          <span>最终处置状态</span>
          <select v-model="pkgFilters.最终处置状态" data-testid="pkg-filter-state">
            <option value="">全部</option>
            <option v-for="state in packageStates" :key="state" :value="state">{{ state }}</option>
          </select>
        </label>
        <button class="btn" data-testid="pkg-query" type="submit">查询</button>
        <button class="btn ghost" data-testid="pkg-reset" type="button" @click="resetPackageFilters">重置条件</button>
        <button class="btn primary" data-testid="open-pkg-create" type="button" @click="openPackageForm">提交处置包</button>
      </form>

      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in packageColumns" :key="column">{{ column }}</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="pkg in packages" :key="pkg.id" :data-testid="`pkg-row-${pkg.id}`" :data-state="pkg.最终处置状态">
            <td v-for="column in packageColumns" :key="column">{{ packageCell(pkg, column) ?? '—' }}</td>
            <td class="row-actions">
              <button class="link" type="button" :data-testid="`pkg-detail-${pkg.id}`" @click="openDetail(pkg.id)">
                规则命中明细
              </button>
            </td>
          </tr>
          <tr v-if="!packages.length">
            <td :colspan="packageColumns.length + 1" class="empty-state">暂无告警关联处置数据包</td>
          </tr>
        </tbody>
      </table>

      <footer class="page-foot">
        <span>共 {{ packageTotal }} 份关联处置数据包（重复触发已归入同一处置主事件）</span>
        <span v-if="packageMessage" class="error-text">{{ packageMessage }}</span>
      </footer>
    </div>

    <!-- ================================================== 处置包详情 -->
    <div v-if="detailPackage" class="modal-backdrop" data-testid="pkg-detail-modal">
      <div class="modal modal-wide">
        <h3>关联处置包 {{ detailPackage.处置包编号 }} <small>v{{ detailPackage.版本 }} · {{ detailPackage.最终处置状态 }}</small></h3>
        <p class="page-desc">
          采集批次：{{ detailPackage.采集批次 }} ｜ 监控对象：{{ detailPackage.监控对象 }} ｜
          更新时间：{{ detailPackage.更新时间 }}
        </p>
        <div v-for="main in detailPackage.处置主事件" :key="main.主事件编号" class="event-block" :data-testid="`main-event-${main.主事件编号}`">
          <header class="event-head">
            <strong>{{ main.主事件编号 }} · {{ main.规则编号 }}</strong>
            <span class="state-tag" :data-state="main.处置状态">{{ main.处置状态 }}</span>
          </header>
          <p class="kanban-meta">
            告警条件：{{ main.告警条件 }} ｜ 时间范围：{{ main.时间范围.开始 }} ~ {{ main.时间范围.结束 }} ｜
            错误次数：{{ main.错误次数 }} ｜ 命中次数：{{ main.命中次数 }}
          </p>
          <table class="data-table inner-table">
            <thead>
              <tr><th v-for="col in hitColumns" :key="col">{{ col }}</th></tr>
            </thead>
            <tbody>
              <tr v-for="hit in main.事件明细" :key="hit.命中编号" :data-testid="`hit-${hit.命中编号}`">
                <td v-for="col in hitColumns" :key="col">{{ hitCell(hit, col) ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <h4>监控事件快照（与处置包一起写入）</h4>
        <pre class="snapshot-box">{{ JSON.stringify(detailPackage.监控事件快照, null, 2) }}</pre>
        <div class="page-actions">
          <button class="btn primary" type="button" @click="detailPackage = null">关闭</button>
        </div>
      </div>
    </div>

    <!-- ================================================== 提交处置包 -->
    <div v-if="showPackageForm" class="modal-backdrop" data-testid="pkg-create-modal">
      <form class="modal modal-wide" @submit.prevent="submitPackage">
        <h3>提交告警关联处置数据包</h3>
        <div class="form-grid">
          <label class="create-field">
            <span>采集批次</span>
            <input v-model="packageForm.采集批次" data-testid="pkg-form-batch" required />
          </label>
          <label class="create-field">
            <span>监控对象</span>
            <input v-model="packageForm.监控对象" data-testid="pkg-form-target" required />
          </label>
          <label class="create-field">
            <span>快照开始时间</span>
            <input v-model="packageForm.开始时间" data-testid="pkg-form-start" placeholder="2026-11-17 08:00:00" required />
          </label>
          <label class="create-field">
            <span>快照结束时间</span>
            <input v-model="packageForm.结束时间" data-testid="pkg-form-end" placeholder="2026-11-17 09:00:00" required />
          </label>
          <label class="create-field">
            <span>快照错误次数</span>
            <input v-model.number="packageForm.错误次数" data-testid="pkg-form-errors" type="number" min="0" required />
          </label>
        </div>

        <div class="form-head">
          <h4>规则命中明细（未关联到事件的规则不能进入处置包）</h4>
          <button class="btn" type="button" data-testid="pkg-add-hit" @click="addHitRow">新增命中</button>
        </div>
        <table class="data-table inner-table">
          <thead>
            <tr>
              <th>规则编号</th><th>事件类型</th><th>触发时间</th><th>序列</th><th>错误次数</th><th>明细说明</th><th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(hit, index) in packageForm.命中明细" :key="index">
              <td>
                <input v-model="hit.规则编号" list="alert-rule-options" :data-testid="`pkg-hit-rule-${index}`" required />
                <datalist id="alert-rule-options">
                  <option v-for="rule in ruleOptions" :key="String(rule.id)" :value="String(rule.规则编号)">{{ rule.监控对象 }}</option>
                </datalist>
              </td>
              <td>
                <select v-model="hit.事件类型" :data-testid="`pkg-hit-type-${index}`">
                  <option v-for="t in eventTypes" :key="t" :value="t">{{ t }}</option>
                </select>
              </td>
              <td><input v-model="hit.触发时间" :data-testid="`pkg-hit-time-${index}`" placeholder="2026-11-17 08:00:00" required /></td>
              <td><input v-model.number="hit.序列" :data-testid="`pkg-hit-seq-${index}`" type="number" min="1" required /></td>
              <td><input v-model.number="hit.错误次数" :data-testid="`pkg-hit-errors-${index}`" type="number" min="0" required /></td>
              <td><input v-model="hit.明细说明" :data-testid="`pkg-hit-note-${index}`" /></td>
              <td><button class="link" type="button" @click="removeHitRow(index)">删除</button></td>
            </tr>
          </tbody>
        </table>

        <p v-if="packageMessage" class="error-text">{{ packageMessage }}</p>
        <div class="page-actions">
          <button class="btn" type="button" @click="showPackageForm = false">取消</button>
          <button class="btn primary" data-testid="pkg-submit" type="submit" :disabled="packageSubmitting">
            {{ packageSubmitting ? '提交中…' : '确认提交' }}
          </button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type HitDetail = {
  命中编号: string
  事件类型: string
  触发时间: string
  序列: number
  错误次数: number
  明细说明: string
}
type MainEvent = {
  主事件编号: string
  监控对象: string
  规则编号: string
  告警条件: string
  命中次数: number
  事件明细: HitDetail[]
  时间范围: { 开始: string; 结束: string }
  错误次数: number
  处置状态: string
}
type AlertPackage = {
  id: number
  处置包编号: string
  采集批次: string
  监控对象: string
  版本: number
  处置主事件: MainEvent[]
  监控事件快照: Record<string, unknown>
  规则命中总数: number
  主事件数: number
  已关闭数: number
  已恢复数: number
  最终处置状态: string
  创建时间: string
  更新时间: string
}
type DashboardGroup = { 状态: string; items: AlertPackage[] }
type HitForm = {
  规则编号: string
  事件类型: string
  触发时间: string
  序列: number
  错误次数: number
  明细说明: string
}

const ENDPOINT = '/api/alert'
const columns = ['规则编号', '监控对象', '告警条件', '通知渠道', '通知模板', '重复间隔', '生效时段', '值班人员']
const actions = ['提交校验', '启用配置', '停用配置']
const statuses = ['草稿', '待校验', '已启用', '已停用']
const metricNames = ['告警规则总数', '待校验告警规则', '已启用告警规则']
const packageStates = ['处置中', '已关闭', '已恢复']
const eventTypes = ['触发', '关闭', '恢复']
const packageColumns = ['处置包编号', '采集批次', '监控对象', '版本', '主事件数', '规则命中总数', '最终处置状态', '更新时间']
const hitColumns = ['命中编号', '事件类型', '触发时间', '序列', '错误次数', '明细说明']

const tabs = [
  { key: 'rules', label: '告警规则' },
  { key: 'packages', label: '关联处置包' },
] as const
type TabKey = (typeof tabs)[number]['key']
const activeTab = ref<TabKey>('rules')

// ------------------------------------------------------------- 告警规则
const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})
const stats = computed(() => [
  { label: metricNames[0], value: total.value },
  { label: metricNames[1], value: rows.value.filter((row) => row.status === statuses[1]).length },
  { label: metricNames[2], value: rows.value.filter((row) => row.status === statuses[statuses.length - 1]).length },
])

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value).toString()
  try {
    const response = await request(`${ENDPOINT}/export?${query}`)
    if (!response.ok) throw new Error('导出失败，请稍后重试')
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = 'alert.csv'
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(columns.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST', body: JSON.stringify(createValues.value),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '登记失败')
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('告警中心动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '告警中心操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('告警规则列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '告警中心列表读取失败'
  }
}

// ------------------------------------------------------------- 关联处置包
const packages = ref<AlertPackage[]>([])
const packageTotal = ref(0)
const packageMessage = ref('')
const pkgFilters = ref<Record<string, string>>({ 监控对象: '', 采集批次: '', 最终处置状态: '' })
const dashboard = ref<{ cards: { label: string; value: number }[]; groups: DashboardGroup[] }>({
  cards: [], groups: [],
})
const detailPackage = ref<AlertPackage | null>(null)
const showPackageForm = ref(false)
const packageSubmitting = ref(false)
const ruleOptions = ref<Row[]>([])
const packageForm = ref<{
  采集批次: string
  监控对象: string
  开始时间: string
  结束时间: string
  错误次数: number
  命中明细: HitForm[]
}>({
  采集批次: '', 监控对象: '', 开始时间: '', 结束时间: '', 错误次数: 0, 命中明细: [],
})

function emptyHit(): HitForm {
  return { 规则编号: '', 事件类型: '触发', 触发时间: '', 序列: 1, 错误次数: 1, 明细说明: '' }
}

function packageCell(pkg: AlertPackage, column: string): string | number {
  return pkg[column as keyof AlertPackage] as string | number
}

function hitCell(hit: HitDetail, column: string): string | number {
  return hit[column as keyof HitDetail] as string | number
}

function addHitRow() {
  packageForm.value.命中明细.push(emptyHit())
}

function removeHitRow(index: number) {
  packageForm.value.命中明细.splice(index, 1)
}

async function reloadDashboard() {
  try {
    const response = await request(`${ENDPOINT}/packages/dashboard`)
    if (!response.ok) throw new Error('看板读取失败')
    dashboard.value = await response.json()
  } catch (error) {
    packageMessage.value = error instanceof Error ? error.message : '看板读取失败'
  }
}

async function reloadPackages() {
  packageMessage.value = ''
  const params = new URLSearchParams()
  Object.entries(pkgFilters.value).forEach(([key, value]) => {
    if (value) params.append(key, value)
  })
  try {
    const response = await request(`${ENDPOINT}/packages?${params.toString()}`)
    if (!response.ok) throw new Error('关联处置包列表读取失败')
    const payload = await response.json()
    packages.value = payload.items ?? []
    packageTotal.value = payload.total ?? packages.value.length
  } catch (error) {
    packageMessage.value = error instanceof Error ? error.message : '关联处置包列表读取失败'
  }
}

function resetPackageFilters() {
  pkgFilters.value = { 监控对象: '', 采集批次: '', 最终处置状态: '' }
  void reloadPackages()
}

async function openDetail(packageId: number) {
  packageMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/packages/${packageId}`)
    if (!response.ok) throw new Error('处置包明细读取失败')
    detailPackage.value = await response.json()
  } catch (error) {
    packageMessage.value = error instanceof Error ? error.message : '处置包明细读取失败'
  }
}

async function openPackageForm() {
  packageMessage.value = ''
  packageForm.value = {
    采集批次: '', 监控对象: '', 开始时间: '', 结束时间: '', 错误次数: 0, 命中明细: [emptyHit()],
  }
  if (!ruleOptions.value.length) {
    try {
      const response = await request(`${ENDPOINT}?size=200`)
      const payload = await response.json()
      ruleOptions.value = payload.items ?? []
    } catch {
      ruleOptions.value = []
    }
  }
  showPackageForm.value = true
}

async function submitPackage() {
  packageSubmitting.value = true
  packageMessage.value = ''
  const form = packageForm.value
  const payload = {
    采集批次: form.采集批次,
    监控对象: form.监控对象,
    规则命中明细: form.命中明细.map((hit, index) => ({
      命中编号: `${hit.规则编号}-H${index + 1}`,
      规则编号: hit.规则编号,
      监控对象: form.监控对象,
      事件类型: hit.事件类型,
      触发时间: hit.触发时间,
      序列: hit.序列,
      错误次数: hit.错误次数,
      明细说明: hit.明细说明,
    })),
    监控事件快照: {
      事件时间范围: { 开始: form.开始时间, 结束: form.结束时间 },
      错误次数: form.错误次数,
      监控对象: form.监控对象,
      采集批次: form.采集批次,
    },
  }
  try {
    const response = await request(`${ENDPOINT}/packages`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    const body = await response.json().catch(() => ({}))
    if (response.status === 409) {
      throw new Error(body?.detail?.message ?? '相同处置包已存在，仅保留首个成功版本')
    }
    if (!response.ok || body.ok === false) {
      throw new Error(body?.message ?? '处置包提交失败')
    }
    showPackageForm.value = false
    await Promise.all([reloadPackages(), reloadDashboard()])
  } catch (error) {
    packageMessage.value = error instanceof Error ? error.message : '处置包提交失败'
  } finally {
    packageSubmitting.value = false
  }
}

function switchTab(tab: TabKey) {
  activeTab.value = tab
  if (tab === 'packages') {
    void reloadPackages()
    void reloadDashboard()
  } else {
    void reload()
  }
}

onMounted(reload)
</script>

<style scoped>
.kanban {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}
.kanban-col {
  background: #f8fafc;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px;
  min-height: 120px;
}
.kanban-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.kanban-count {
  background: #e2e8f0;
  border-radius: 10px;
  padding: 1px 8px;
  font-size: 12px;
}
.kanban-card {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 8px;
}
.kanban-title {
  margin: 0 0 4px;
  font-size: 13px;
}
.kanban-meta {
  margin: 2px 0;
  font-size: 12px;
  color: var(--muted);
}
.modal-wide {
  width: min(920px, 96vw);
}
.event-block {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 12px;
  background: #fafbfc;
}
.event-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.state-tag {
  border-radius: 10px;
  padding: 2px 10px;
  font-size: 12px;
  background: #e2e8f0;
}
.state-tag[data-state='已恢复'] {
  background: #dcfce7;
  color: #166534;
}
.state-tag[data-state='已关闭'] {
  background: #fee2e2;
  color: #991b1b;
}
.inner-table {
  margin-top: 6px;
}
.inner-table input,
.inner-table select {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 4px 6px;
  font-size: 12px;
}
.snapshot-box {
  background: #1e293b;
  color: #e2e8f0;
  border-radius: 6px;
  padding: 10px;
  font-size: 12px;
  max-height: 220px;
  overflow: auto;
}
.form-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}
.form-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 12px 0 6px;
}
h3 small {
  color: var(--muted);
  font-size: 12px;
  font-weight: normal;
}
</style>
