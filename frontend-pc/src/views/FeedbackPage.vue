<script setup>
/**
 * ⑥ 反馈工单中心（ui-design.md §4.3 / impl-pc-admin-v1 §8）。
 * 左：工单列表（待回复置顶）· 右：对话式回复界面（用户左灰 / 管理员右绿）。
 * 进入详情自动置已读；回复后状态变 replied；已关闭工单回复被拒（toast 6002）。
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import PageHeader from '@/components/common/PageHeader.vue'
import FeedbackChat from '@/components/feedback/FeedbackChat.vue'
import {
  getAdminFeedbacks,
  getAdminFeedbackDetail,
  adminReplyFeedback,
  adminCloseFeedback,
} from '@/api/feedback'

const loading = ref(false)
const list = ref([])
const total = ref(0)

const query = reactive({
  page: 1,
  page_size: 20,
  status: '',
  type: '',
  keyword: '',
  unread_only: false,
})

const detail = ref(null)
const detailLoading = ref(false)
const sending = ref(false)
const chatRef = ref(null)

const STATUS_OPTIONS = [
  { label: '全部状态', value: '' },
  { label: '待回复', value: 'pending' },
  { label: '已回复', value: 'replied' },
  { label: '已关闭', value: 'closed' },
]
const TYPE_OPTIONS = [
  { label: '全部类型', value: '' },
  { label: '问题咨询', value: 'question' },
  { label: '结果核对', value: 'result_verdict' },
]

/** 状态 → 文案 / tag 类型 */
const STATUS_MAP = {
  pending: { text: '待回复', type: 'warning' },
  replied: { text: '已回复', type: 'success' },
  closed: { text: '已关闭', type: 'info' },
}

/** 列表数据：待回复置顶排序 */
const sortedList = computed(() => {
  const order = { pending: 0, replied: 1, closed: 2 }
  return [...list.value].sort((a, b) => (order[a.status] ?? 9) - (order[b.status] ?? 9))
})

/** 加载列表 */
async function loadList() {
  loading.value = true
  try {
    const data = await getAdminFeedbacks({ ...query })
    list.value = (data && data.items) || []
    total.value = (data && data.total) || 0
  } catch (e) {
    list.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

/** 选择工单 → 拉详情（自动置已读） */
async function selectRow(row) {
  detailLoading.value = true
  try {
    detail.value = (await getAdminFeedbackDetail(row.id)) || null
  } catch (e) {
    detail.value = null
  } finally {
    detailLoading.value = false
  }
}

/** 回复 */
async function handleReply(content) {
  if (!detail.value) return
  sending.value = true
  try {
    await adminReplyFeedback(detail.value.id, content)
    ElMessage.success('回复已发送')
    if (chatRef.value) chatRef.value.clearInput()
    await selectRow({ id: detail.value.id })
    await loadList()
  } catch (e) {
    // 6002（已关闭）等错误已由拦截器 toast
  } finally {
    sending.value = false
  }
}

/** 关闭工单（终态） */
async function handleClose() {
  if (!detail.value) return
  try {
    await ElMessageBox.confirm('关闭后该工单不可再回复，确认关闭？', '关闭工单', {
      confirmButtonText: '确认关闭',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch (e) {
    return
  }
  try {
    await adminCloseFeedback(detail.value.id)
    ElMessage.success('工单已关闭')
    await selectRow({ id: detail.value.id })
    await loadList()
  } catch (e) {
    // 6003 非法流转等已由拦截器提示
  }
}

/** 筛选变更 */
function handleFilter() {
  query.page = 1
  loadList()
}

/** 重置筛选 */
function resetFilter() {
  query.status = ''
  query.type = ''
  query.keyword = ''
  query.unread_only = false
  query.page = 1
  loadList()
}

onMounted(loadList)
</script>

<template>
  <div class="feedback-page">
    <PageHeader title="反馈工单中心" subtitle="待回复工单置顶 · 进入详情自动置已读 · 回复即时同步给用户">
      <template #actions>
        <el-button size="small" @click="loadList">刷新列表</el-button>
      </template>
    </PageHeader>

    <div class="fb-layout">
      <!-- 左：列表 -->
      <div class="cd-panel fb-list">
        <div class="fb-list__filters">
          <el-input v-model="query.keyword" size="small" placeholder="搜索标题/用户" clearable style="width: 150px" @keyup.enter="handleFilter" />
          <el-select v-model="query.status" size="small" placeholder="全部状态" clearable style="width: 104px" @change="handleFilter">
            <el-option v-for="o in STATUS_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
          <el-select v-model="query.type" size="small" placeholder="全部类型" clearable style="width: 104px" @change="handleFilter">
            <el-option v-for="o in TYPE_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
          <el-button size="small" type="primary" plain @click="handleFilter">查询</el-button>
          <el-button size="small" text @click="resetFilter">重置</el-button>
        </div>
        <div class="fb-list__unread">
          <el-checkbox v-model="query.unread_only" size="small" @change="handleFilter">仅看未读</el-checkbox>
          <span class="fb-list__count">共 {{ total }} 条</span>
        </div>

        <el-table
          v-loading="loading"
          :data="sortedList"
          size="small"
          height="calc(100% - 84px)"
          highlight-current-row
          empty-text="暂无工单"
          @row-click="selectRow"
        >
          <el-table-column prop="id" label="#" width="52" />
          <el-table-column label="用户" width="96">
            <template #default="{ row }">{{ row.username || (row.user && row.user.username) || '—' }}</template>
          </el-table-column>
          <el-table-column label="标题" min-width="130" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="fb-list__title">{{ row.title || '（无标题）' }}</span>
              <el-badge v-if="row.unread_count > 0" :value="row.unread_count" class="fb-list__badge" />
            </template>
          </el-table-column>
          <el-table-column label="类型" width="80">
            <template #default="{ row }">{{ row.type === 'result_verdict' ? '结果核对' : '咨询' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" :type="(STATUS_MAP[row.status] || {}).type || 'info'">
                {{ (STATUS_MAP[row.status] || {}).text || row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="更新" width="108">
            <template #default="{ row }">{{ (row.last_reply_at || row.updated_at || row.created_at || '').replace('T', ' ').slice(5, 16) }}</template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 右：对话 -->
      <div class="cd-panel fb-conv">
        <FeedbackChat
          ref="chatRef"
          :detail="detail"
          :loading="detailLoading"
          :sending="sending"
          @reply="handleReply"
          @close="handleClose"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.fb-layout {
  display: grid;
  grid-template-columns: minmax(520px, 1fr) minmax(420px, 1.05fr);
  gap: 16px;
  height: calc(100vh - 150px);
}
.fb-list {
  display: flex;
  flex-direction: column;
  padding: 12px;
  min-height: 0;
}
.fb-list__filters {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.fb-list__unread {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 2px;
}
.fb-list__count {
  font-size: 12px;
  color: var(--pc-text-muted);
}
.fb-list__title {
  font-weight: 500;
}
.fb-list__badge {
  margin-left: 8px;
}
.fb-conv {
  padding: 14px 16px;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

@media (max-width: 1500px) {
  .fb-layout {
    grid-template-columns: minmax(460px, 1fr) minmax(380px, 1fr);
  }
}
</style>
