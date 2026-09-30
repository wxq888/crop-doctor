<script setup>
/**
 * 用户详情抽屉（ui-design.md §4.3：用户详情抽屉 → 检测记录/反馈历史/预警记录三 tab）。
 */
import { ref, watch } from 'vue'

import { getUserDetail } from '@/api/admin'
import SeverityTag from '@/components/common/SeverityTag.vue'
import RiskTag from '@/components/common/RiskTag.vue'

const props = defineProps({
  /** 抽屉显隐（v-model） */
  modelValue: { type: Boolean, default: false },
  /** 目标用户 id */
  userId: { type: [Number, String], default: null },
})

const emit = defineEmits(['update:modelValue'])

const loading = ref(false)
const detail = ref(null)
const activeTab = ref('detections')

/** 列表容错读取 */
function pickList(obj, keys) {
  if (!obj) return []
  for (const k of keys) {
    if (Array.isArray(obj[k])) return obj[k]
  }
  return []
}

const detections = ref([])
const feedbacks = ref([])
const alerts = ref([])

/** 拉取用户详情 */
async function load() {
  if (!props.userId) return
  loading.value = true
  try {
    const data = await getUserDetail(props.userId)
    detail.value = data || null
    detections.value = pickList(data, ['detections', 'recent_detections', 'detection_records'])
    feedbacks.value = pickList(data, ['feedbacks', 'recent_feedbacks', 'feedback_records'])
    alerts.value = pickList(data, ['alerts', 'recent_alerts', 'alert_records'])
  } catch (e) {
    detail.value = null
    detections.value = []
    feedbacks.value = []
    alerts.value = []
  } finally {
    loading.value = false
  }
}

/** 打开抽屉时加载 */
watch(
  () => [props.modelValue, props.userId],
  ([visible]) => {
    if (visible && props.userId) {
      activeTab.value = 'detections'
      load()
    }
  },
  { immediate: true },
)

function close() {
  emit('update:modelValue', false)
}
</script>

<template>
  <el-drawer
    :model-value="modelValue"
    size="640px"
    :title="detail ? `用户详情 · ${detail.username}` : '用户详情'"
    @update:model-value="close"
  >
    <div v-loading="loading" class="user-detail">
      <template v-if="detail">
        <!-- 概要 -->
        <div class="user-detail__summary cd-panel">
          <div class="user-detail__avatar">{{ (detail.nickname || detail.username || 'U').slice(0, 1) }}</div>
          <div class="user-detail__info">
            <div class="user-detail__name">
              {{ detail.nickname || detail.username }}
              <el-tag size="small" effect="plain" :type="detail.role === 'admin' ? 'warning' : 'info'">
                {{ detail.role === 'admin' ? '管理员' : '普通用户' }}
              </el-tag>
              <el-tag size="small" effect="plain" :type="detail.status === 1 ? 'success' : 'danger'">
                {{ detail.status === 1 ? '启用' : '禁用' }}
              </el-tag>
            </div>
            <div class="user-detail__meta">
              <span>ID：{{ detail.id }}</span>
              <span>账号：{{ detail.username }}</span>
              <span>注册：{{ (detail.created_at || '').replace('T', ' ').slice(0, 16) }}</span>
            </div>
            <div class="user-detail__counts">
              <span>检测 {{ detail.detection_count ?? detections.length }} 次</span>
              <span>反馈 {{ detail.feedback_count ?? feedbacks.length }} 条</span>
            </div>
          </div>
        </div>

        <!-- 三 tab -->
        <el-tabs v-model="activeTab" class="user-detail__tabs">
          <el-tab-pane label="检测记录" name="detections">
            <el-table :data="detections" size="small" height="320" empty-text="暂无检测记录">
              <el-table-column prop="id" label="ID" width="70" />
              <el-table-column label="病害" min-width="130">
                <template #default="{ row }">{{ row.disease_cn || row.disease || '—' }}</template>
              </el-table-column>
              <el-table-column label="分级" width="90">
                <template #default="{ row }"><SeverityTag :level="row.severity_level ?? 0" :label="row.severity_label" /></template>
              </el-table-column>
              <el-table-column label="时间" min-width="140">
                <template #default="{ row }">{{ (row.created_at || '').replace('T', ' ').slice(0, 16) }}</template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="反馈历史" name="feedbacks">
            <el-table :data="feedbacks" size="small" height="320" empty-text="暂无反馈">
              <el-table-column prop="id" label="ID" width="70" />
              <el-table-column label="类型" width="100">
                <template #default="{ row }">{{ row.type === 'result_verdict' ? '结果核对' : '问题咨询' }}</template>
              </el-table-column>
              <el-table-column prop="title" label="标题" min-width="150" show-overflow-tooltip />
              <el-table-column label="状态" width="90">
                <template #default="{ row }">{{ { pending: '待回复', replied: '已回复', closed: '已关闭' }[row.status] || row.status }}</template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="预警记录" name="alerts">
            <el-table :data="alerts" size="small" height="320" empty-text="暂无预警">
              <el-table-column prop="id" label="ID" width="70" />
              <el-table-column label="病害" min-width="130">
                <template #default="{ row }">{{ row.disease_cn || row.disease || '—' }}</template>
              </el-table-column>
              <el-table-column label="风险" width="100">
                <template #default="{ row }"><RiskTag :risk="row.risk_level || 'low'" /></template>
              </el-table-column>
              <el-table-column label="预报日" width="110">
                <template #default="{ row }">{{ row.forecast_date || '—' }}</template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
        </el-tabs>
      </template>
      <el-empty v-else-if="!loading" description="未能加载用户详情" />
    </div>
  </el-drawer>
</template>

<style scoped>
.user-detail {
  min-height: 200px;
}
.user-detail__summary {
  display: flex;
  gap: 14px;
  padding: 14px 16px;
  margin-bottom: 12px;
}
.user-detail__avatar {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background: var(--pc-primary-soft);
  color: var(--pc-primary);
  font-size: 22px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.user-detail__info {
  flex: 1;
  min-width: 0;
}
.user-detail__name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: var(--pc-text);
}
.user-detail__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-top: 6px;
  font-size: 12px;
  color: var(--pc-text-muted);
}
.user-detail__counts {
  display: flex;
  gap: 16px;
  margin-top: 8px;
  font-size: 12px;
  color: var(--pc-primary);
  font-weight: 600;
}
</style>
