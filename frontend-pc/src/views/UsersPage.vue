<script setup>
/**
 * 用户管理（ui-design.md §4.3 / impl-pc-admin-v1 §8）。
 * 列表 + 详情抽屉（检测/反馈/预警三 tab）+ 禁用启用 + 重置密码（返回新密码一次性弹窗）。
 */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import PageHeader from '@/components/common/PageHeader.vue'
import UserDetailDrawer from '@/components/users/UserDetailDrawer.vue'
import { getUsers, updateUserStatus, resetUserPassword } from '@/api/admin'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()

const loading = ref(false)
const list = ref([])
const total = ref(0)

const query = reactive({
  page: 1,
  page_size: 20,
  keyword: '',
  role: '',
  status: '',
})

const ROLE_OPTIONS = [
  { label: '全部角色', value: '' },
  { label: '管理员', value: 'admin' },
  { label: '普通用户', value: 'user' },
]
const STATUS_OPTIONS = [
  { label: '全部状态', value: '' },
  { label: '启用', value: 1 },
  { label: '禁用', value: 0 },
]

// 详情抽屉
const drawerVisible = ref(false)
const activeUserId = ref(null)

/** 加载列表 */
async function loadList() {
  loading.value = true
  try {
    const params = { ...query }
    if (params.status === '') delete params.status
    if (params.role === '') delete params.role
    const data = await getUsers(params)
    list.value = (data && data.items) || []
    total.value = (data && data.total) || 0
  } catch (e) {
    list.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function handleFilter() {
  query.page = 1
  loadList()
}

function resetFilter() {
  query.keyword = ''
  query.role = ''
  query.status = ''
  query.page = 1
  loadList()
}

/** 打开详情 */
function openDetail(row) {
  activeUserId.value = row.id
  drawerVisible.value = true
}

/** 切换启用 / 禁用 */
async function toggleStatus(row) {
  const next = row.status === 1 ? 0 : 1
  const action = next === 1 ? '启用' : '禁用'
  try {
    await ElMessageBox.confirm(`确认${action}用户「${row.username}」？`, `${action}用户`, {
      confirmButtonText: `确认${action}`,
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch (e) {
    return
  }
  try {
    await updateUserStatus(row.id, next)
    ElMessage.success(`已${action}用户`)
    loadList()
  } catch (e) {
    // 8002（禁用自己 / 最后一个管理员）已由拦截器提示
  }
}

/** 重置密码 */
async function handleReset(row) {
  try {
    await ElMessageBox.confirm(`确认重置用户「${row.username}」的密码？`, '重置密码', {
      confirmButtonText: '确认重置',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch (e) {
    return
  }
  try {
    const data = await resetUserPassword(row.id)
    const pwd = (data && (data.new_password || data.password)) || '（未返回）'
    const uname = (data && data.username) || row.username
    await ElMessageBox.alert(
      `<div style="line-height:1.9">账号：<b>${uname}</b><br/>新密码：<b style="color:#2BA471;font-size:16px">${pwd}</b><br/><span style="color:#7C8A96;font-size:12px">请立即转交用户，此密码仅展示一次</span></div>`,
      '重置成功',
      { dangerouslyUseHTMLString: true, confirmButtonText: '我已记录' },
    )
    loadList()
  } catch (e) {
    // 错误已提示
  }
}

/** 是否本人（禁用自己按钮提示） */
function isSelf(row) {
  return userStore.user && userStore.user.id === row.id
}

onMounted(loadList)
</script>

<template>
  <div class="users-page">
    <PageHeader title="用户管理" subtitle="用户列表 · 详情（检测/反馈/预警）· 禁用启用 · 重置密码">
      <template #actions>
        <el-button size="small" @click="loadList">刷新</el-button>
      </template>
    </PageHeader>

    <div class="cd-panel users-panel">
      <div class="users-panel__filters">
        <el-input v-model="query.keyword" size="small" placeholder="搜索用户名/昵称" clearable style="width: 180px" @keyup.enter="handleFilter" />
        <el-select v-model="query.role" size="small" placeholder="全部角色" clearable style="width: 120px" @change="handleFilter">
          <el-option v-for="o in ROLE_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
        </el-select>
        <el-select v-model="query.status" size="small" placeholder="全部状态" clearable style="width: 120px" @change="handleFilter">
          <el-option v-for="o in STATUS_OPTIONS" :key="o.value" :label="o.label" :value="o.value" />
        </el-select>
        <el-button size="small" type="primary" plain @click="handleFilter">查询</el-button>
        <el-button size="small" text @click="resetFilter">重置</el-button>
        <span class="users-panel__total">共 {{ total }} 位用户</span>
      </div>

      <el-table v-loading="loading" :data="list" size="default" empty-text="暂无用户">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column label="用户" min-width="180">
          <template #default="{ row }">
            <div class="user-cell">
              <span class="user-cell__avatar">{{ (row.nickname || row.username || 'U').slice(0, 1) }}</span>
              <div>
                <div class="user-cell__name">{{ row.nickname || row.username }}</div>
                <div class="user-cell__sub">{{ row.username }}</div>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="角色" width="110">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="row.role === 'admin' ? 'warning' : 'info'">
              {{ row.role === 'admin' ? '管理员' : '普通用户' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" effect="plain" :type="row.status === 1 ? 'success' : 'danger'">
              {{ row.status === 1 ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="detection_count" label="检测数" width="90" />
        <el-table-column prop="feedback_count" label="反馈数" width="90" />
        <el-table-column label="注册时间" width="170">
          <template #default="{ row }">{{ (row.created_at || '').replace('T', ' ').slice(0, 19) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="250" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="openDetail(row)">详情</el-button>
            <el-button
              size="small"
              text
              :type="row.status === 1 ? 'danger' : 'success'"
              :disabled="isSelf(row)"
              :title="isSelf(row) ? '不能禁用自己' : ''"
              @click="toggleStatus(row)"
            >
              {{ row.status === 1 ? '禁用' : '启用' }}
            </el-button>
            <el-button size="small" text type="warning" @click="handleReset(row)">重置密码</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="users-panel__pager">
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

    <UserDetailDrawer v-model="drawerVisible" :user-id="activeUserId" />
  </div>
</template>

<style scoped>
.users-panel {
  padding: 14px 16px;
}
.users-panel__filters {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.users-panel__total {
  margin-left: auto;
  font-size: 12px;
  color: var(--pc-text-muted);
}
.users-panel__pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
.user-cell {
  display: flex;
  align-items: center;
  gap: 10px;
}
.user-cell__avatar {
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: var(--pc-primary-soft);
  color: var(--pc-primary);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 13px;
  flex-shrink: 0;
}
.user-cell__name {
  font-size: 13px;
  color: var(--pc-text);
  font-weight: 500;
}
.user-cell__sub {
  font-size: 11px;
  color: var(--pc-text-muted);
}
</style>
