<script setup>
/**
 * 预警中心（ui-design.md §4.3 / impl-pc-admin-v1 §8）。
 * 病害-气象规则配置表 + 当前风险总览 + 预警记录 + 天气面板 + 手动刷新。
 * 天气不可用时顶部灰条提示「降级运行」，页面不报错（§4.2 降级不抛错）。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import PageHeader from '@/components/common/PageHeader.vue'
import RiskTag from '@/components/common/RiskTag.vue'
import SeverityPieChart from '@/components/charts/SeverityPieChart.vue'
import WeatherPanel from '@/components/charts/WeatherPanel.vue'
import RuleFormDialog from '@/components/warning/RuleFormDialog.vue'

import {
  getOverview,
  refreshWarning,
  getRules,
  createRule,
  updateRule,
  deleteRule,
  getRecords,
} from '@/api/warning'

/* ---------------- 风险总览 ---------------- */
const overview = ref({
  degraded: false,
  location: '',
  now: null,
  forecast: [],
  current_risks: [],
  stats: { high: 0, mid: 0, low: 0 },
  last_refresh_at: '',
})
const overviewLoading = ref(false)
const refreshing = ref(false)

/** 风险等级分布（喂给环图） */
const riskDist = computed(() => {
  const s = overview.value.stats || {}
  return [
    { risk: 'high', label: '高风险', count: s.high || 0 },
    { risk: 'mid', label: '中风险', count: s.mid || 0 },
    { risk: 'low', label: '低风险', count: s.low || 0 },
  ]
})

const RISK_TEXT = { high: '高', mid: '中', low: '低' }

async function loadOverview() {
  overviewLoading.value = true
  try {
    const data = await getOverview()
    if (data) {
      // 防御：forecast 上游可能是对象信封（如 {list:[...]}) 或非数组，统一归一为数组再下发
      const fc = data.forecast
      const list = Array.isArray(fc)
        ? fc
        : fc && typeof fc === 'object' && Array.isArray(fc.list)
          ? fc.list
          : fc && typeof fc === 'object' && Array.isArray(fc.items)
            ? fc.items
            : []
      overview.value = { ...overview.value, ...data, forecast: list }
    }
  } catch (e) {
    // 静默
  } finally {
    overviewLoading.value = false
  }
}

/** 手动触发风险评估 */
async function handleRefresh() {
  refreshing.value = true
  try {
    const data = await refreshWarning()
    if (data && data.degraded) {
      ElMessage.warning('天气服务未配置，风险引擎降级运行，本次未生成预警')
    } else {
      ElMessage.success(`评估完成：命中 ${data.matched ?? 0} 条，新增预警 ${data.created ?? 0} 条`)
    }
    await loadOverview()
    await loadRecords()
  } catch (e) {
    // 错误已提示
  } finally {
    refreshing.value = false
  }
}

/* ---------------- 规则管理 ---------------- */
const ruleLoading = ref(false)
const rules = ref([])
const ruleTotal = ref(0)
const ruleQuery = reactive({ page: 1, page_size: 10, disease: '', enabled: '' })
const ruleDialogVisible = ref(false)
const editingRule = ref(null)

async function loadRules() {
  ruleLoading.value = true
  try {
    const params = { ...ruleQuery }
    if (params.enabled === '') delete params.enabled
    if (!params.disease) delete params.disease
    const data = await getRules(params)
    rules.value = (data && data.items) || []
    ruleTotal.value = (data && data.total) || 0
  } catch (e) {
    rules.value = []
    ruleTotal.value = 0
  } finally {
    ruleLoading.value = false
  }
}

function openCreateRule() {
  editingRule.value = null
  ruleDialogVisible.value = true
}

function openEditRule(row) {
  editingRule.value = { ...row }
  ruleDialogVisible.value = true
}

/** 规则表单提交（新建 / 编辑） */
async function submitRule(payload) {
  try {
    if (editingRule.value) {
      await updateRule(editingRule.value.id, payload)
      ElMessage.success('规则已更新')
    } else {
      await createRule(payload)
      ElMessage.success('规则已创建')
    }
    ruleDialogVisible.value = false
    await loadRules()
    await loadOverview()
  } catch (e) {
    // 7040 等已提示
  }
}

/** 删除规则 */
async function removeRule(row) {
  try {
    await ElMessageBox.confirm(`确认删除规则「${row.disease}」？`, '删除规则', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch (e) {
    return
  }
  try {
    await deleteRule(row.id)
    ElMessage.success('规则已删除')
    loadRules()
  } catch (e) {
    // 错误已提示
  }
}

/** 启停规则（直接更新 enabled） */
async function toggleRule(row) {
  try {
    await updateRule(row.id, { enabled: row.enabled })
    ElMessage.success(row.enabled ? '规则已启用' : '规则已停用')
    loadOverview()
  } catch (e) {
    // 失败回滚
    row.enabled = !row.enabled
  }
}

/* ---------------- 预警记录 ---------------- */
const recordLoading = ref(false)
const records = ref([])
const recordTotal = ref(0)
const recordQuery = reactive({ page: 1, page_size: 10, risk_level: '', source: '', location: '' })

const RISK_OPTIONS = [
  { label: '全部风险', value: '' },
  { label: '高风险', value: 'high' },
  { label: '中风险', value: 'mid' },
  { label: '低风险', value: 'low' },
]
const SOURCE_OPTIONS = [
  { label: '全部来源', value: '' },
  { label: '天气驱动', value: 'weather' },
  { label: '手动', value: 'manual' },
]

async function loadRecords() {
  recordLoading.value = true
  try {
    const params = { ...recordQuery }
    Object.keys(params).forEach((k) => {
      if (params[k] === '') delete params[k]
    })
    const data = await getRecords(params)
    records.value = (data && data.items) || []
    recordTotal.value = (data && data.total) || 0
  } catch (e) {
    records.value = []
    recordTotal.value = 0
  } finally {
    recordLoading.value = false
  }
}

function handleRecordFilter() {
  recordQuery.page = 1
  loadRecords()
}

/** 温度 / 湿度区间展示 */
function rangeText(min, max, unit) {
  if ((min === null || min === undefined) && (max === null || max === undefined)) return '不约束'
  const a = min === null || min === undefined ? '*' : min
  const b = max === null || max === undefined ? '*' : max
  return `${a} ~ ${b}${unit}`
}

const RAIN_TEXT = { any: '不限', rain: '需降雨', no_rain: '需无雨' }

onMounted(() => {
  loadOverview()
  loadRules()
  loadRecords()
})
</script>

<template>
  <div class="warning-page">
    <PageHeader title="预警中心" subtitle="病害-气象规则配置 · 当前风险总览 · 预警记录与推送情况">
      <template #actions>
        <el-button size="small" type="primary" :loading="refreshing" @click="handleRefresh">
          立即评估
        </el-button>
      </template>
    </PageHeader>

    <!-- 降级灰条 -->
    <el-alert
      v-if="overview.degraded"
      class="warn-degraded"
      type="warning"
      :closable="false"
      show-icon
      title="天气服务未配置，风险引擎降级运行"
      description="规则配置与预警记录照常可用；配置 WEATHER_API_KEY 后风险将自动生成。"
    />

    <!-- 风险总览 -->
    <div class="warn-overview">
      <div class="cd-panel warn-overview__stats">
        <div class="warn-panel__title">当前风险总览</div>
        <div class="warn-overview__cards">
          <div class="warn-stat warn-stat--high">
            <span class="warn-stat__num">{{ overview.stats?.high || 0 }}</span>
            <span class="warn-stat__label">高风险</span>
          </div>
          <div class="warn-stat warn-stat--mid">
            <span class="warn-stat__num">{{ overview.stats?.mid || 0 }}</span>
            <span class="warn-stat__label">中风险</span>
          </div>
          <div class="warn-stat warn-stat--low">
            <span class="warn-stat__num">{{ overview.stats?.low || 0 }}</span>
            <span class="warn-stat__label">低风险</span>
          </div>
        </div>
        <div class="warn-overview__risks">
          <div class="warn-overview__risks-title">当前风险项（{{ (overview.current_risks || []).length }}）</div>
          <div v-if="(overview.current_risks || []).length" class="warn-overview__risk-list">
            <div v-for="(r, i) in overview.current_risks" :key="i" class="warn-risk-item">
              <RiskTag :risk="r.risk_level || 'low'" />
              <span class="warn-risk-item__name">{{ r.disease_cn || r.disease }}</span>
              <span class="warn-risk-item__date">{{ r.forecast_date || '' }}</span>
            </div>
          </div>
          <el-empty v-else :image-size="52" description="暂无当前风险（或天气降级）" />
        </div>
        <div class="warn-overview__foot">
          最近评估：{{ (overview.last_refresh_at || '').replace('T', ' ').slice(0, 19) || '—' }}
        </div>
      </div>

      <div class="cd-panel warn-overview__chart">
        <div class="warn-panel__title">风险等级分布</div>
        <SeverityPieChart :dist="riskDist" height="220px" />
      </div>

      <div class="cd-panel warn-overview__weather">
        <WeatherPanel :now="overview.now" :forecast="overview.forecast" :degraded="overview.degraded" :loading="overviewLoading" />
      </div>
    </div>

    <!-- 规则配置 -->
    <div class="cd-panel warn-panel">
      <div class="warn-panel__head">
        <span class="warn-panel__title">病害-气象规则配置</span>
        <div class="warn-panel__head-actions">
          <el-input v-model="ruleQuery.disease" size="small" placeholder="按病害筛选" clearable style="width: 160px" @keyup.enter="loadRules" />
          <el-button size="small" @click="loadRules">查询</el-button>
          <el-button size="small" type="primary" @click="openCreateRule">新建规则</el-button>
        </div>
      </div>
      <el-table v-loading="ruleLoading" :data="rules" size="small" empty-text="暂无启用规则">
        <el-table-column prop="disease" label="病害标识" min-width="170" />
        <el-table-column label="作物" width="100">
          <template #default="{ row }">{{ row.crop || '—' }}</template>
        </el-table-column>
        <el-table-column label="温度区间" width="130">
          <template #default="{ row }">{{ rangeText(row.temp_min, row.temp_max, '℃') }}</template>
        </el-table-column>
        <el-table-column label="湿度区间" width="130">
          <template #default="{ row }">{{ rangeText(row.humidity_min, row.humidity_max, '%') }}</template>
        </el-table-column>
        <el-table-column label="降雨" width="90">
          <template #default="{ row }">{{ RAIN_TEXT[row.rain_condition] || row.rain_condition }}</template>
        </el-table-column>
        <el-table-column label="风险" width="90">
          <template #default="{ row }"><RiskTag :risk="row.risk_level || 'low'" /></template>
        </el-table-column>
        <el-table-column label="防治建议" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.advice || '—' }}</template>
        </el-table-column>
        <el-table-column label="启用" width="70">
          <template #default="{ row }"><el-switch v-model="row.enabled" size="small" @change="toggleRule(row)" /></template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="openEditRule(row)">编辑</el-button>
            <el-button size="small" text type="danger" @click="removeRule(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 预警记录 -->
    <div class="cd-panel warn-panel">
      <div class="warn-panel__head">
        <span class="warn-panel__title">预警记录</span>
        <div class="warn-panel__head-actions">
          <el-select v-model="recordQuery.risk_level" size="small" placeholder="全部风险" clearable style="width: 110px" @change="handleRecordFilter">
            <el-option v-for="o in RISK_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
          <el-select v-model="recordQuery.source" size="small" placeholder="全部来源" clearable style="width: 110px" @change="handleRecordFilter">
            <el-option v-for="o in SOURCE_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
          <el-input v-model="recordQuery.location" size="small" placeholder="地区" clearable style="width: 130px" @keyup.enter="handleRecordFilter" />
          <el-button size="small" @click="handleRecordFilter">查询</el-button>
        </div>
      </div>
      <el-table v-loading="recordLoading" :data="records" size="small" empty-text="暂无预警记录">
        <el-table-column prop="id" label="ID" width="64" />
        <el-table-column label="来源" width="90">
          <template #default="{ row }">{{ row.source === 'weather' ? '天气驱动' : row.source || '—' }}</template>
        </el-table-column>
        <el-table-column label="病害" min-width="150">
          <template #default="{ row }">{{ row.disease_cn || row.disease || '—' }}</template>
        </el-table-column>
        <el-table-column label="风险" width="90">
          <template #default="{ row }"><RiskTag :risk="row.risk_level || 'low'" /></template>
        </el-table-column>
        <el-table-column label="地区" width="110">
          <template #default="{ row }">{{ row.location || '全局' }}</template>
        </el-table-column>
        <el-table-column label="预报日" width="110">
          <template #default="{ row }">{{ row.forecast_date || '—' }}</template>
        </el-table-column>
        <el-table-column prop="content" label="内容" min-width="240" show-overflow-tooltip />
        <el-table-column label="创建时间" width="160">
          <template #default="{ row }">{{ (row.created_at || '').replace('T', ' ').slice(0, 19) }}</template>
        </el-table-column>
      </el-table>
      <div class="warn-panel__pager">
        <el-pagination
          v-model:current-page="recordQuery.page"
          v-model:page-size="recordQuery.page_size"
          :total="recordTotal"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          size="small"
          background
          @current-change="loadRecords"
          @size-change="handleRecordFilter"
        />
      </div>
    </div>

    <RuleFormDialog v-model="ruleDialogVisible" :rule="editingRule" @submit="submitRule" />
  </div>
</template>

<style scoped>
.warn-degraded {
  margin-bottom: 14px;
}
.warn-overview {
  display: grid;
  grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}
.warn-overview__stats,
.warn-overview__chart,
.warn-overview__weather {
  padding: 14px 16px;
}
.warn-overview__cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin: 12px 0;
}
.warn-stat {
  border-radius: var(--pc-radius);
  padding: 10px;
  text-align: center;
  border: 1px solid var(--pc-border);
}
.warn-stat__num {
  display: block;
  font-size: 22px;
  font-weight: 700;
}
.warn-stat__label {
  font-size: 12px;
  color: var(--pc-text-muted);
}
.warn-stat--high .warn-stat__num {
  color: var(--pc-sev-3);
}
.warn-stat--mid .warn-stat__num {
  color: var(--pc-sev-2);
}
.warn-stat--low .warn-stat__num {
  color: var(--pc-sev-1);
}
.warn-overview__risks {
  margin-top: 10px;
}
.warn-overview__risks-title {
  font-size: 12px;
  color: var(--pc-text-muted);
  margin-bottom: 8px;
}
.warn-overview__risk-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 130px;
  overflow-y: auto;
}
.warn-risk-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.warn-risk-item__name {
  color: var(--pc-text);
}
.warn-risk-item__date {
  color: var(--pc-text-muted);
  margin-left: auto;
}
.warn-overview__foot {
  margin-top: 10px;
  font-size: 11px;
  color: var(--pc-text-muted);
}
.warn-panel {
  padding: 14px 16px;
  margin-bottom: 16px;
}
.warn-panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.warn-panel__head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.warn-panel__title {
  font-weight: 600;
  color: var(--pc-text);
  font-size: 13px;
}
.warn-panel__pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

@media (max-width: 1500px) {
  .warn-overview {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  }
  .warn-overview__weather {
    grid-column: span 2;
  }
}
</style>
