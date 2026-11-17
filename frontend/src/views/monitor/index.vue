<template>
  <section class="page" data-module="monitor">
    <header class="page-head">
      <div><h2>运行监控</h2><p class="page-desc">展示各采集任务的实时运行指标、成功率和资源占用，并同步告警中心关联处置包生成监控事件清单。</p></div>
    </header>
    <div class="analysis-summary">
      <article v-for="m in summaryMetrics" :key="m.label" class="analysis-card" data-testid="kpi-card">
        <span style="font-size:12px;color:var(--muted)">{{ m.label }}</span>
        <strong style="font-size:22px;display:block">{{ m.value }}</strong>
        <span :class="m.trend > 0 ? 'trend-up' : 'trend-down'" style="font-size:12px">{{ m.trend > 0 ? '↑' : '↓' }}{{ Math.abs(m.trend) }}%</span>
      </article>
    </div>
    <form class="analysis-form" @submit.prevent="runAnalysis">
      <label v-for="field in paramFields" :key="field"><span>{{ field }}</span>
        <select v-if="field.includes('方法')||field.includes('策略')||field.includes('粒度')" v-model="params[field]"><option v-for="o in options[field]" :key="o" :value="o">{{ o }}</option></select>
        <input v-else v-model="params[field]" :placeholder="`请输入${field}`" />
      </label>
      <button class="btn primary" type="submit" data-testid="run-analysis">运行分析</button>
    </form>
    <div v-if="chartData.length" class="analysis-chart">
      <div v-for="(bar, i) in chartData" :key="i" class="analysis-bar" :style="{ height: barHeight(bar.value) + 'px' }"><span>{{ bar.label }}</span></div>
    </div>
    <table class="data-table" v-if="results.length">
      <thead><tr><th v-for="c in resultColumns" :key="c">{{ c }}</th></tr></thead>
      <tbody><tr v-for="row in results" :key="row.id"><td v-for="c in resultColumns" :key="c">{{ row[c] ?? '—' }}</td></tr></tbody>
    </table>
    <p v-if="!results.length && !loading" style="text-align:center;color:var(--muted)">请配置参数后运行分析</p>

    <div class="event-panel" data-testid="alert-event-panel">
      <header class="event-head">
        <h3>监控事件清单（告警关联处置包同步）</h3>
        <form class="event-filter" @submit.prevent="fetchAlertEvents">
          <input v-model="eventTarget" data-testid="alert-event-filter" placeholder="按监控对象检索" />
          <button class="btn" type="submit">查询</button>
          <button class="btn ghost" type="button" @click="eventTarget = ''; fetchAlertEvents()">重置</button>
        </form>
      </header>
      <table class="data-table" v-if="alertEvents.length">
        <thead>
          <tr><th v-for="c in eventColumns" :key="c">{{ c }}</th></tr>
        </thead>
        <tbody>
          <tr v-for="event in alertEvents" :key="event.事件编号" :data-testid="`alert-event-${event.事件编号}`" :data-state="event.处置状态">
            <td v-for="c in eventColumns" :key="c">{{ formatCell(event, c) }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty-state">暂无同步过来的监控事件，请先在告警中心提交关联处置包</p>
      <footer class="page-foot">
        <span>共 {{ alertEvents.length }} 条监控事件，时间范围与错误次数同处置主事件一致</span>
        <span v-if="eventError" class="error-text">{{ eventError }}</span>
      </footer>
    </div>
  </section>
</template>
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { request } from '@/api/client'
const ENDPOINT = '/api/monitor'
const summaryMetrics = ref<{label:string;value:number;trend:number}[]>([])
const results = ref<any[]>([]); const chartData = ref<{label:string;value:number}[]>([])
const loading = ref(false)
const params = ref<Record<string,string>>({})
const paramFields = ["大盘编号", "关联任务", "采集速率", "成功率", "平均延迟", "内存占用", "错误次数", "观测时段"].filter((f: string) => !['编号','名称','版本'].includes(f)).slice(0, 4)
const options: Record<string,string[]> = { '统计粒度': ['按日','按周','按月'], '分组字段': ['全量','按类型','按区域'], '比较方法': ['环比','同比','绝对值'], '时间范围': ['最近7天','最近30天','最近90天'] }
const resultColumns = computed(() => ["大盘编号", "关联任务", "采集速率", "成功率", "平均延迟", "内存占用", "错误次数", "观测时段"].slice(0, 5))

type AlertEvent = {
  事件编号: string
  采集批次: string
  监控对象: string
  规则编号: string
  告警条件: string
  时间范围: { 开始: string; 结束: string }
  错误次数: number
  命中次数: number
  处置状态: string
  处置包编号: string
  版本: number
}
const eventColumns = ['事件编号', '采集批次', '监控对象', '规则编号', '时间范围', '错误次数', '命中次数', '处置状态', '处置包编号']
const alertEvents = ref<AlertEvent[]>([])
const eventTarget = ref('')
const eventError = ref('')

function barHeight(v: number) { const max = Math.max(...chartData.value.map(d => d.value), 1); return Math.max(10, (v / max) * 140) }
function formatCell(event: AlertEvent, column: string): string | number {
  if (column === '时间范围') {
    return `${event.时间范围.开始} ~ ${event.时间范围.结束}`
  }
  return event[column as keyof AlertEvent] as string | number
}
async function fetchSummary() { try { const res = await request(`${ENDPOINT}/summary`); summaryMetrics.value = (await res.json()).metrics || [] } catch(e) {} }
async function runAnalysis() {
  loading.value = true
  try { const res = await request(`${ENDPOINT}/run`, { method: 'POST', body: JSON.stringify({ values: params.value }) }); const data = await res.json(); results.value = data.items || []; chartData.value = (data.items || []).map((r: any) => ({ label: Object.values(r)[0] as string, value: Object.values(r).filter(v => typeof v === 'number')[0] as number || 0 })).slice(0, 6) } catch(e) { results.value = [] }
  loading.value = false
}
async function fetchAlertEvents() {
  eventError.value = ''
  const query = eventTarget.value ? `?${new URLSearchParams({ 监控对象: eventTarget.value }).toString()}` : ''
  try {
    const res = await request(`${ENDPOINT}/alert-events${query}`)
    if (!res.ok) throw new Error('监控事件清单读取失败')
    const data = await res.json()
    alertEvents.value = data.items ?? []
  } catch (error) {
    eventError.value = error instanceof Error ? error.message : '监控事件清单读取失败'
  }
}
onMounted(() => { void fetchSummary(); void fetchAlertEvents() })
</script>
<style scoped>
.event-panel {
  margin-top: 20px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px;
}
.event-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}
.event-head h3 {
  margin: 0;
  font-size: 15px;
}
.event-filter {
  display: flex;
  gap: 8px;
}
.event-filter input {
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 13px;
}
</style>
