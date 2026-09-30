<script setup>
/**
 * 模型管理（ui-design.md §4.3 / impl-pc-admin-v1 §8）。
 * 权重版本列表 + 当前生效标记 + 切换（CPU 热加载数秒，加 loading）。
 * 注意：切换仅进程内生效，重启回退默认权重（§9 限制 4）。
 */
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

import PageHeader from '@/components/common/PageHeader.vue'
import ModelVersionList from '@/components/model/ModelVersionList.vue'
import { getModels, activateModel } from '@/api/admin'

const loading = ref(false)
const models = ref([])
const active = ref('')
const loaded = ref(false)
const activating = ref('')

/** 权重数量 */
const count = computed(() => models.value.length)

/** 加载模型列表 */
async function loadModels() {
  loading.value = true
  try {
    const data = await getModels()
    models.value = (data && data.items) || []
    active.value = (data && data.active) || ''
    loaded.value = !!(data && data.loaded)
  } catch (e) {
    models.value = []
  } finally {
    loading.value = false
  }
}

/** 切换生效模型 */
async function handleActivate(filename) {
  try {
    await ElMessageBox.confirm(
      `将热切换到「${filename}」，CPU 加载预计数秒，期间检测请求可能短暂排队。确认切换？`,
      '切换模型',
      { confirmButtonText: '确认切换', cancelButtonText: '取消', type: 'warning' },
    )
  } catch (e) {
    return
  }
  activating.value = filename
  try {
    const data = await activateModel(filename)
    if (data) {
      active.value = data.filename || filename
    }
    loaded.value = true
    ElMessage.success('模型已切换')
    await loadModels()
  } catch (e) {
    // 8003 等已提示
  } finally {
    activating.value = ''
  }
}

onMounted(loadModels)
</script>

<template>
  <div class="model-page">
    <PageHeader title="模型管理" subtitle="权重版本列表 · 当前生效标记 · 热切换（仅进程内生效，重启回退默认权重）">
      <template #actions>
        <el-button size="small" @click="loadModels">刷新</el-button>
      </template>
    </PageHeader>

    <div class="cd-panel model-panel">
      <div class="model-panel__head">
        <span class="model-panel__title">权重版本（{{ count }}）</span>
        <div class="model-panel__meta">
          <span>当前生效：<b class="cd-mono">{{ active || '—' }}</b></span>
          <el-tag size="small" :type="loaded ? 'success' : 'info'" effect="plain">
            {{ loaded ? '已加载到内存' : '未加载' }}
          </el-tag>
        </div>
      </div>

      <ModelVersionList
        :models="models"
        :active="active"
        :loaded="loaded"
        :loading="loading"
        :activating="activating"
        @activate="handleActivate"
      />

      <div class="model-panel__note">
        说明：模型切换为进程内热加载，不写入配置文件；后端重启后将回退到默认权重（见设计文档 §9 限制）。
      </div>
    </div>
  </div>
</template>

<style scoped>
.model-panel {
  padding: 16px;
}
.model-panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.model-panel__title {
  font-weight: 600;
  color: var(--pc-text);
  font-size: 13px;
}
.model-panel__meta {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
  color: var(--pc-text-muted);
}
.model-panel__note {
  margin-top: 14px;
  padding: 10px 12px;
  border-radius: var(--pc-radius);
  background: var(--pc-bg);
  font-size: 12px;
  color: var(--pc-text-muted);
  line-height: 1.7;
}
</style>
