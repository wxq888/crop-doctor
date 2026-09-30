<script setup>
/**
 * 检测记录详情抽屉（ui-design.md §4.3 检测记录管理：详情侧滑，含热力图）。
 * 热力图异步生成，未完成时显示占位。
 */
import { computed, ref, watch } from 'vue'

import { getDetectionDetail } from '@/api/admin'
import SeverityTag from '@/components/common/SeverityTag.vue'
import { assetUrl } from '@/utils/url'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  detectionId: { type: [Number, String], default: null },
})

const emit = defineEmits(['update:modelValue'])

const loading = ref(false)
const detail = ref(null)

/** 热力图 URL（后端可能返回 heatmap_url / gradcam_url / 未就绪标记） */
const heatmapUrl = computed(() => {
  const d = detail.value
  if (!d) return ''
  return assetUrl(d.heatmap_url || d.gradcam_url || d.heat_map_url)
})
const annotatedUrl = computed(() => assetUrl(detail.value && (detail.value.annotated_url || detail.value.image_url)))
const thumbUrl = computed(() => assetUrl(detail.value && detail.value.thumb_url))

/** 图片加载失败标记（回退占位，避免出现破图标） */
const annotatedFailed = ref(false)
const heatmapFailed = ref(false)

/** 检测框列表 */
const boxes = computed(() => {
  const d = detail.value
  if (!d) return []
  return d.boxes || d.detections || d.objects || []
})

async function load() {
  if (!props.detectionId && props.detectionId !== 0) return
  loading.value = true
  try {
    detail.value = (await getDetectionDetail(props.detectionId)) || null
  } catch (e) {
    detail.value = null
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.modelValue, props.detectionId],
  ([visible]) => {
    if (visible && (props.detectionId || props.detectionId === 0)) {
      annotatedFailed.value = false
      heatmapFailed.value = false
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
    size="720px"
    :title="detail ? `检测详情 #${detail.id}` : '检测详情'"
    @update:model-value="close"
  >
    <div v-loading="loading" class="det-detail">
      <template v-if="detail">
        <!-- 结论 -->
        <div class="det-detail__conclusion cd-panel">
          <div class="det-detail__conclusion-main">
            <span class="det-detail__disease">{{ detail.disease_cn || detail.disease || '未知病害' }}</span>
            <SeverityTag :level="detail.severity_level ?? 0" :label="detail.severity_label" />
          </div>
          <div class="det-detail__meta">
            <span>作物：{{ detail.crop_cn || detail.crop || '—' }}</span>
            <span>用户：{{ detail.username || (detail.user_id !== undefined ? '#' + detail.user_id : '—') }}</span>
            <span v-if="detail.top_conf !== undefined && detail.top_conf !== null">
              置信度：{{ (Number(detail.top_conf) * 100).toFixed(1) }}%
            </span>
            <span>时间：{{ (detail.created_at || '').replace('T', ' ').slice(0, 19) }}</span>
          </div>
        </div>

        <!-- 图片：标注图 + 热力图 -->
        <div class="det-detail__images">
          <div class="det-detail__img-card cd-panel">
            <div class="det-detail__img-title">标注图</div>
            <img
              v-if="annotatedUrl && !annotatedFailed"
              :src="annotatedUrl"
              alt="标注图"
              class="det-detail__img"
              @error="annotatedFailed = true"
            />
            <div v-else class="det-detail__placeholder">标注图暂不可用</div>
          </div>
          <div class="det-detail__img-card cd-panel">
            <div class="det-detail__img-title">Grad-CAM 热力图</div>
            <img
              v-if="heatmapUrl && !heatmapFailed"
              :src="heatmapUrl"
              alt="热力图"
              class="det-detail__img"
              @error="heatmapFailed = true"
            />
            <div v-else class="det-detail__placeholder">热力图生成中 / 暂不可用</div>
          </div>
        </div>

        <!-- 检测框 -->
        <div class="cd-panel det-detail__boxes">
          <div class="det-detail__boxes-title">检测框（{{ boxes.length }}）</div>
          <el-table :data="boxes" size="small" empty-text="无检测框明细">
            <el-table-column label="病害" min-width="140">
              <template #default="{ row }">{{ row.disease_cn || row.label_cn || row.class_name || row.label || '—' }}</template>
            </el-table-column>
            <el-table-column label="置信度" width="110">
              <template #default="{ row }">
                <span v-if="row.conf !== undefined && row.conf !== null">{{ (Number(row.conf) * 100).toFixed(1) }}%</span>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column label="位置" min-width="180">
              <template #default="{ row }">
                <span class="cd-mono">{{ row.bbox ? row.bbox.join(', ') : (row.x !== undefined ? `${row.x},${row.y},${row.w},${row.h}` : '—') }}</span>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </template>
      <el-empty v-else-if="!loading" description="未能加载检测详情" />
    </div>
  </el-drawer>
</template>

<style scoped>
.det-detail {
  min-height: 200px;
}
.det-detail__conclusion {
  padding: 14px 16px;
  margin-bottom: 14px;
}
.det-detail__conclusion-main {
  display: flex;
  align-items: center;
  gap: 10px;
}
.det-detail__disease {
  font-size: 18px;
  font-weight: 700;
  color: var(--pc-text);
}
.det-detail__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-top: 10px;
  font-size: 12px;
  color: var(--pc-text-muted);
}
.det-detail__images {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 14px;
}
.det-detail__img-card {
  padding: 10px 12px;
}
.det-detail__img-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--pc-text);
  margin-bottom: 8px;
}
.det-detail__img {
  width: 100%;
  height: 220px;
  object-fit: contain;
  border-radius: var(--pc-radius);
  background: var(--pc-bg);
}
.det-detail__placeholder {
  height: 220px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--pc-radius);
  background: var(--pc-bg);
  color: var(--pc-text-muted);
  font-size: 12px;
}
.det-detail__boxes {
  padding: 12px 14px;
}
.det-detail__boxes-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--pc-text);
  margin-bottom: 8px;
}
</style>
