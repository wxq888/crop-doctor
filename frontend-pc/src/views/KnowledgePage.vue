<script setup>
/**
 * 知识库管理（ui-design.md §4.3 / impl-pc-admin-v1 §8）。
 * 文档列表 + 上传/编辑 + 向量化状态标记 + 重新向量化（触发后台任务并轮询状态）。
 */
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import PageHeader from '@/components/common/PageHeader.vue'
import KnowledgeEditDialog from '@/components/knowledge/KnowledgeEditDialog.vue'

import {
  getAdminDocs,
  getCrops,
  createDoc,
  updateDoc,
  deleteDoc,
  reindex,
  getReindexStatus,
} from '@/api/knowledge'

const loading = ref(false)
const list = ref([])
const total = ref(0)

const query = reactive({
  page: 1,
  page_size: 10,
  q: '',
  crop: '',
  disease: '',
  vector_status: '',
})

const crops = ref([])

const VECTOR_OPTIONS = [
  { label: '全部状态', value: '' },
  { label: '待向量化', value: 'pending' },
  { label: '已完成', value: 'done' },
  { label: '失败', value: 'failed' },
]
/** 向量状态 → 文案 / tag */
const VECTOR_MAP = {
  pending: { text: '待向量化', type: 'warning' },
  done: { text: '已完成', type: 'success' },
  failed: { text: '失败', type: 'danger' },
}

/** 重新向量化状态 */
const reindexStatus = ref({ running: false, last_built_at: '', count: 0, error: '' })
const reindexing = ref(false)
let pollTimer = null

/** 加载文档列表 */
async function loadList() {
  loading.value = true
  try {
    const params = { ...query }
    Object.keys(params).forEach((k) => {
      if (params[k] === '' || params[k] === null) delete params[k]
    })
    const data = await getAdminDocs(params)
    list.value = (data && data.items) || []
    total.value = (data && data.total) || 0
  } catch (e) {
    list.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

/** 加载作物分类 */
async function loadCrops() {
  try {
    const data = await getCrops()
    const items = (data && data.items) || []
    crops.value = items.map((c) => ({ label: c.crop_cn || c.crop_en, value: c.crop_en || c.crop_cn }))
  } catch (e) {
    crops.value = []
  }
}

/** 加载向量化状态 */
async function loadReindexStatus() {
  try {
    const data = await getReindexStatus()
    if (data) reindexStatus.value = { ...reindexStatus.value, ...data }
  } catch (e) {
    // 静默
  }
}

/** 轮询状态直到完成 */
function startPolling() {
  stopPolling()
  pollTimer = setInterval(async () => {
    await loadReindexStatus()
    if (!reindexStatus.value.running) {
      stopPolling()
      reindexing.value = false
      if (reindexStatus.value.error) {
        ElMessage.error(`向量化失败：${reindexStatus.value.error}`)
      } else {
        ElMessage.success(`向量化完成，索引条目 ${reindexStatus.value.count ?? 0} 条`)
      }
      loadList()
    }
  }, 2000)
}
function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

/** 触发重新向量化 */
async function handleReindex() {
  try {
    await ElMessageBox.confirm('将重建 FAISS 索引并热更新检索服务，确认执行？', '重新向量化', {
      confirmButtonText: '开始',
      cancelButtonText: '取消',
      type: 'info',
    })
  } catch (e) {
    return
  }
  reindexing.value = true
  try {
    await reindex()
    ElMessage.info('已提交重建任务，正在后台执行…')
    startPolling()
    await loadReindexStatus()
  } catch (e) {
    reindexing.value = false
  }
}

/// 编辑 / 新建
const dialogVisible = ref(false)
const editingDoc = ref(null)

function openCreate() {
  editingDoc.value = null
  dialogVisible.value = true
}
function openEdit(row) {
  editingDoc.value = { ...row }
  dialogVisible.value = true
}

/** 提交（新建 / 编辑），payload 可能是对象或 FormData */
async function submitDoc(payload) {
  try {
    if (editingDoc.value) {
      await updateDoc(editingDoc.value.id, payload)
      ElMessage.success('文档已更新，已进入向量化队列')
    } else {
      await createDoc(payload)
      ElMessage.success('文档已创建，已进入向量化队列')
    }
    dialogVisible.value = false
    loadList()
  } catch (e) {
    // 7002 冲突等已提示
  }
}

/** 删除文档 */
async function removeDoc(row) {
  try {
    await ElMessageBox.confirm(`确认删除文档「${row.title}」？将同时移除 md 源文件。`, '删除文档', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch (e) {
    return
  }
  try {
    await deleteDoc(row.id)
    ElMessage.success('文档已删除')
    loadList()
  } catch (e) {
    // 错误已提示
  }
}

function handleFilter() {
  query.page = 1
  loadList()
}
function resetFilter() {
  query.q = ''
  query.crop = ''
  query.disease = ''
  query.vector_status = ''
  query.page = 1
  loadList()
}

onMounted(() => {
  loadList()
  loadCrops()
  loadReindexStatus()
})
onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="knowledge-page">
    <PageHeader title="知识库管理" subtitle="md 为事实源 · 上传/编辑后进入向量化队列 · 支持一键重建索引">
      <template #actions>
        <el-button size="small" :loading="reindexing" @click="handleReindex">
          {{ reindexing ? '重建中…' : '重新向量化' }}
        </el-button>
        <el-button size="small" type="primary" @click="openCreate">新建文档</el-button>
      </template>
    </PageHeader>

    <!-- 索引状态条 -->
    <div class="cd-panel kb-status">
      <div class="kb-status__item">
        <span class="kb-status__label">索引状态</span>
        <el-tag size="small" :type="reindexStatus.running ? 'warning' : reindexStatus.error ? 'danger' : 'success'" effect="plain">
          {{ reindexStatus.running ? '重建中…' : reindexStatus.error ? '上次失败' : '就绪' }}
        </el-tag>
      </div>
      <div class="kb-status__item">
        <span class="kb-status__label">索引条目</span>
        <span class="kb-status__value">{{ reindexStatus.count ?? '—' }}</span>
      </div>
      <div class="kb-status__item">
        <span class="kb-status__label">最近构建</span>
        <span class="kb-status__value">{{ (reindexStatus.last_built_at || '').replace('T', ' ').slice(0, 19) || '—' }}</span>
      </div>
      <div v-if="reindexStatus.error" class="kb-status__error">错误：{{ reindexStatus.error }}</div>
    </div>

    <div class="cd-panel kb-panel">
      <div class="kb-panel__filters">
        <el-input v-model="query.q" size="small" placeholder="搜索标题/正文" clearable style="width: 180px" @keyup.enter="handleFilter" />
        <el-select v-model="query.crop" size="small" placeholder="作物" clearable style="width: 130px" @change="handleFilter">
          <el-option v-for="c in crops" :key="c.value" :label="c.label" :value="c.value" />
        </el-select>
        <el-input v-model="query.disease" size="small" placeholder="病害" clearable style="width: 130px" @keyup.enter="handleFilter" />
        <el-select v-model="query.vector_status" size="small" placeholder="全部状态" clearable style="width: 130px" @change="handleFilter">
          <el-option v-for="o in VECTOR_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
        </el-select>
        <el-button size="small" type="primary" plain @click="handleFilter">查询</el-button>
        <el-button size="small" text @click="resetFilter">重置</el-button>
        <span class="kb-panel__total">共 {{ total }} 篇</span>
      </div>

      <el-table v-loading="loading" :data="list" size="default" empty-text="暂无知识文档">
        <el-table-column prop="id" label="ID" width="64" />
        <el-table-column prop="title" label="标题" min-width="220" show-overflow-tooltip />
        <el-table-column label="作物" width="120">
          <template #default="{ row }">{{ row.crop_cn || row.crop || '—' }}</template>
        </el-table-column>
        <el-table-column label="病害" width="150">
          <template #default="{ row }">{{ row.disease_cn || row.disease || '—' }}</template>
        </el-table-column>
        <el-table-column label="向量状态" width="120">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="(VECTOR_MAP[row.vector_status] || {}).type || 'info'">
              {{ (VECTOR_MAP[row.vector_status] || {}).text || row.vector_status || '未知' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="170">
          <template #default="{ row }">{{ (row.updated_at || row.created_at || '').replace('T', ' ').slice(0, 19) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" text type="danger" @click="removeDoc(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="kb-panel__pager">
        <el-pagination
          v-model:current-page="query.page"
          v-model:page-size="query.page_size"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          size="small"
          background
          @current-change="loadList"
          @size-change="handleFilter"
        />
      </div>
    </div>

    <KnowledgeEditDialog v-model="dialogVisible" :doc="editingDoc" @submit="submitDoc" />
  </div>
</template>

<style scoped>
.kb-status {
  display: flex;
  align-items: center;
  gap: 32px;
  padding: 12px 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.kb-status__item {
  display: flex;
  align-items: center;
  gap: 8px;
}
.kb-status__label {
  font-size: 12px;
  color: var(--pc-text-muted);
}
.kb-status__value {
  font-size: 13px;
  color: var(--pc-text);
  font-weight: 600;
}
.kb-status__error {
  width: 100%;
  font-size: 12px;
  color: var(--pc-sev-3);
}
.kb-panel {
  padding: 14px 16px;
}
.kb-panel__filters {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.kb-panel__total {
  margin-left: auto;
  font-size: 12px;
  color: var(--pc-text-muted);
}
.kb-panel__pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
</style>
