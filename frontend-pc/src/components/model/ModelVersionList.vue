<script setup>
/**
 * 模型权重版本列表（ui-design.md §4.3 模型管理）。
 * 展示文件名 / 大小 / 修改时间 / 当前生效标记，支持切换（热加载，CPU 数秒）。
 */
defineProps({
  /** [{filename,size_mb,modified_at,is_active}] */
  models: { type: Array, default: () => [] },
  /** 当前生效文件名 */
  active: { type: String, default: '' },
  /** 模型是否已加载 */
  loaded: { type: Boolean, default: false },
  /** 列表加载中 */
  loading: { type: Boolean, default: false },
  /** 切换中（含目标文件名，避免误点） */
  activating: { type: String, default: '' },
})

const emit = defineEmits(['activate'])

/** 文件大小格式化 */
function sizeText(mb) {
  const n = Number(mb)
  if (!Number.isFinite(n)) return '—'
  return n >= 1024 ? `${(n / 1024).toFixed(2)} GB` : `${n.toFixed(1)} MB`
}

/** 时间格式化 */
function timeText(v) {
  return v ? String(v).replace('T', ' ').slice(0, 19) : '—'
}

/** 是否当前生效版本 */
function isActive(row, activeName) {
  if (row.is_active !== undefined) return !!row.is_active
  return row.filename && row.filename === activeName
}
</script>

<template>
  <el-table v-loading="loading" :data="models" size="default" empty-text="暂无模型权重文件">
    <el-table-column label="权重文件" min-width="240">
      <template #default="{ row }">
        <span class="cd-mono model-name">{{ row.filename }}</span>
      </template>
    </el-table-column>
    <el-table-column label="大小" width="120">
      <template #default="{ row }">{{ sizeText(row.size_mb) }}</template>
    </el-table-column>
    <el-table-column label="修改时间" width="180">
      <template #default="{ row }">{{ timeText(row.modified_at) }}</template>
    </el-table-column>
    <el-table-column label="状态" width="150">
      <template #default="{ row }">
        <el-tag v-if="isActive(row, active)" type="success" effect="plain" size="small">当前生效</el-tag>
        <el-tag v-else type="info" effect="plain" size="small">待用</el-tag>
        <el-tag v-if="isActive(row, active) && loaded" type="success" size="small" class="model-loaded">已加载</el-tag>
      </template>
    </el-table-column>
    <el-table-column label="操作" width="130" fixed="right">
      <template #default="{ row }">
        <el-button
          size="small"
          type="primary"
          plain
          :disabled="isActive(row, active)"
          :loading="activating === row.filename"
          @click="emit('activate', row.filename)"
        >
          {{ isActive(row, active) ? '使用中' : '切换' }}
        </el-button>
      </template>
    </el-table-column>
  </el-table>
</template>

<style scoped>
.model-name {
  color: var(--pc-text);
  font-size: 13px;
}
.model-loaded {
  margin-left: 6px;
}
</style>
