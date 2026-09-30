<script setup>
/**
 * 检测记录管理（ui-design.md §4.3 / impl-pc-admin-v1 §8）。
 * 全局记录表格（缩略/用户/病害/分级/置信度/时间/反馈状态）+ 详情抽屉（含热力图）+ 异常趋势线 + 导出 CSV。
 */
import { onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'

import PageHeader from '@/components/common/PageHeader.vue'
import SeverityTag from '@/components/common/SeverityTag.vue'
import TrendBarChart from '@/components/charts/TrendBarChart.vue'
import DetectionDetailDrawer from '@/components/detections/DetectionDetailDrawer.vue'

import { getDetections, getStatsTrend } from '@/api/admin'
import { assetUrl } from '@/utils/url'

const route = useRoute()

const loading = ref(false)
const list = ref([])
const total = ref(0)

const query = reactive({
  page: 1,
  page_size: 20,
  user_id: '',
  disease: '',
  severity_level: '',
  crop: '',
  start: '',
  end: '',
  has_feedback: '',
})

const SEVERITY_OPTIONS = [
  { label: '全部分级', value: '' },
  { label: '无病害', value: 0 },
  { label: '轻微', value: 1 },
  { label: '中等', value: 2 },
  { label: '严重', value: 3 },
]
const FEEDBACK_OPTIONS = [
  { label: '全部', value: '' },
  { label: '有反馈', value: true },
  { label: '无反馈', value: false },
]

/** 异常趋势线数据 */
const trend = ref({ days: [], detections: [] })
const trendLoading = ref(false)

/** 详情抽屉 */
const drawerVisible = ref(false)
const activeId = ref(null)

/** 缩略图加载失败的行 id（图片 404 / 未生成时回退占位） */
const imgError = ref(new Set())

/** 加载列表 */
async function loadList() {
  loading.value = true
  try {
    const params = { ...query }
    Object.keys(params).forEach((k) => {
      if (params[k] === '' || params[k] === null) delete params[k]
    })
    const data = await getDetections(params)
    list.value = (data && data.items) || []
    total.value = (data && data.total) || 0
  } catch (e) {
    list.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

/** 加载异常趋势线 */
async function loadTrend() {
  trendLoading.value = true
  try {
    const data = await getStatsTrend(7)
    if (data) trend.value = { days: data.days || [], detections: data.detections || [] }
  } catch (e) {
    // 静默
  } finally {
    trendLoading.value = false
  }
}

function handleFilter() {
  query.page = 1
  loadList()
}

function resetFilter() {
  query.user_id = ''
  query.disease = ''
  query.severity_level = ''
  query.crop = ''
  query.start = ''
  query.end = ''
  query.has_feedback = ''
  query.page = 1
  loadList()
}

/** 打开详情 */
function openDetail(row) {
  activeId.value = row.id
  drawerVisible.value = true
}

/** 置信度展示 */
function confText(v) {
  if (v === undefined || v === null) return '—'
  return `${(Number(v) * 100).toFixed(1)}%`
}

/** 反馈状态展示 */
const FEEDBACK_STATUS_TEXT = {
  pending: '待回复',
  replied: '已回复',
  closed: '已关闭',
}

/** 导出 CSV（按当前筛选拉取前 100 条） */
async function exportCsv() {
  try {
    const params = { ...query, page: 1, page_size: 100 }
    Object.keys(params).forEach((k) => {
      if (params[k] === '' || params[k] === null) delete params[k]
    })
    const data = await getDetections(params)
    const items = (data && data.items) || []
    if (!items.length) {
      ElMessage.warning('当前筛选无数据可导出')
      return
    }
    const header = ['ID', '用户', '作物', '病害', '分级', '置信度', '反馈状态', '检测时间']
    const rows = items.map((it) => [
      it.id,
      it.username || it.user_id || '',
      it.crop_cn || it.crop || '',
      it.disease_cn || it.disease || '',
      it.severity_label || it.severity_level || '',
      it.top_conf !== undefined && it.top_conf !== null ? (Number(it.top_conf) * 100).toFixed(1) + '%' : '',
      FEEDBACK_STATUS_TEXT[it.feedback_status] || it.feedback_status || '',
      (it.created_at || '').replace('T', ' ').slice(0, 19),
    ])
    const csv = [header, ...rows]
      .map((r) => r.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(','))
      .join('\r\n')
    // 加 BOM 保证 Excel 正确识别中文
    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `检测记录_${new Date().toISOString().slice(0, 10)}.csv`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    ElMessage.success(`已导出 ${items.length} 条记录`)
  } catch (e) {
    // 错误已提示
  }
}

onMounted(() => {
  // 大屏按作物下钻带入 crop 筛选
  if (route.query.crop) {
    query.crop = String(route.query.crop)
  }
  loadList()
  loadTrend()
})
</script>

<template>
  <div class="detections-page">
    <PageHeader title="检测记录管理" subtitle="全局检测记录（含所有用户）· 筛选 / 导出 · 详情含热力图">
      <template #actions>
        <el-button size="small" @click="loadList">刷新</el-button>
        <el-button size="small" type="primary" plain @click="exportCsv">导出 CSV</el-button>
      </template>
    </PageHeader>

    <!-- 异常趋势线 -->
    <div class="cd-panel det-trend">
      <div class="det-trend__title">检测异常趋势（近 7 日检测量）</div>
      <TrendBarChart :days="trend.days" :values="trend.detections" :loading="trendLoading" height="180px" />
    </div>

    <div class="cd-panel det-panel">
      <div class="det-panel__filters">
        <el-input v-model="query.disease" size="small" placeholder="病害标识" clearable style="width: 140px" @keyup.enter="handleFilter" />
        <el-input v-model="query.crop" size="small" placeholder="作物" clearable style="width: 110px" @keyup.enter="handleFilter" />
        <el-input v-model="query.user_id" size="small" placeholder="用户 ID" clearable style="width: 100px" @keyup.enter="handleFilter" />
        <el-select v-model="query.severity_level" size="small" placeholder="全部分级" clearable style="width: 110px" @change="handleFilter">
          <el-option v-for="o in SEVERITY_OPTIONS" :key="String(o.value)" :label="o.label" :value="o.value" />
        </el-select>
        <el-select v-model="query.has_feedback" size="small" placeholder="反馈状态" clearable style="width: 110px" @change="handleFilter">
          <el-option v-for="o in FEEDBACK_OPTIONS" :key="String(o.value)" :label="o.label" :value="o.value" />
        </el-select>
        <el-date-picker
          v-model="query.start"
          size="small"
          type="date"
          placeholder="开始日期"
          value-format="YYYY-MM-DD"
          style="width: 140px"
          @change="handleFilter"
        />
        <el-date-picker
          v-model="query.end"
          size="small"
          type="date"
          placeholder="结束日期"
          value-format="YYYY-MM-DD"
          style="width: 140px"
          @change="handleFilter"
        />
        <el-button size="small" type="primary" plain @click="handleFilter">查询</el-button>
        <el-button size="small" text @click="resetFilter">重置</el-button>
        <span class="det-panel__total">共 {{ total }} 条</span>
      </div>

      <el-table v-loading="loading" :data="list" size="small" empty-text="暂无检测记录" @row-click="openDetail">
        <el-table-column label="缩略图" width="80">
          <template #default="{ row }">
            <img
              v-if="assetUrl(row.thumb_url) && !imgError.has(row.id)"
              :src="assetUrl(row.thumb_url)"
              class="det-thumb"
              alt="缩略图"
              @error="imgError.add(row.id)"
            />
            <div v-else class="det-thumb det-thumb--empty">无图</div>
          </template>
        </el-table-column>
        <el-table-column prop="id" label="ID" width="64" />
        <el-table-column label="用户" width="120">
          <template #default="{ row }">{{ row.username || (row.user_id !== undefined ? '#' + row.user_id : '—') }}</template>
        </el-table-column>
        <el-table-column label="作物" width="100">
          <template #default="{ row }">{{ row.crop_cn || row.crop || '—' }}</template>
        </el-table-column>
        <el-table-column label="病害" min-width="150">
          <template #default="{ row }">{{ row.disease_cn || row.disease || '—' }}</template>
        </el-table-column>
        <el-table-column label="分级" width="90">
          <template #default="{ row }"><SeverityTag :level="row.severity_level ?? 0" :label="row.severity_label" /></template>
        </el-table-column>
        <el-table-column label="置信度" width="90">
          <template #default="{ row }">{{ confText(row.top_conf) }}</template>
        </el-table-column>
        <el-table-column label="反馈状态" width="100">
          <template #default="{ row }">
            <span v-if="row.feedback_status">{{ FEEDBACK_STATUS_TEXT[row.feedback_status] || row.feedback_status }}</span>
            <span v-else class="cd-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="检测时间" width="160">
          <template #default="{ row }">{{ (row.created_at || '').replace('T', ' ').slice(0, 19) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click.stop="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="det-panel__pager">
        <el-pagination
          v-model:current-page="query.page"
          v-model:page-size="query.page_size"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          size="small"
          background
          @current-change="loadList"
          @size-change="handleFilter"
        />
      </div>
    </div>

    <DetectionDetailDrawer v-model="drawerVisible" :detection-id="activeId" />
  </div>
</template>

<style scoped>
.det-trend {
  padding: 14px 16px;
  margin-bottom: 16px;
}
.det-trend__title {
  font-weight: 600;
  color: var(--pc-text);
  font-size: 13px;
  margin-bottom: 8px;
}
.det-panel {
  padding: 14px 16px;
}
.det-panel__filters {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.det-panel__total {
  margin-left: auto;
  font-size: 12px;
  color: var(--pc-text-muted);
}
.det-panel__pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
.det-thumb {
  width: 48px;
  height: 48px;
  object-fit: cover;
  border-radius: 4px;
  display: block;
}
.det-thumb--empty {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  color: var(--pc-text-muted);
  background: var(--pc-bg);
}
</style>
