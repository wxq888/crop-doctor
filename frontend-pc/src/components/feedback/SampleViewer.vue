<script setup>
/**
 * 检测结果样本查看（ui-design.md §4.3 ⑥：检测反馈类工单可查看附图与样本）。
 * 展示标注图 + 缩略图 + 分级 + 病害名，供管理员核对样本。
 */
import { computed, ref, watch } from 'vue'

import SeverityTag from '@/components/common/SeverityTag.vue'
import { assetUrl } from '@/utils/url'

const props = defineProps({
  /** 关联检测记录（含 annotated_url / thumb_url / 病害 / 分级） */
  record: { type: Object, default: null },
})

const annotated = computed(() => assetUrl(props.record && (props.record.annotated_url || props.record.image_url)))
const thumb = computed(() => assetUrl(props.record && props.record.thumb_url))

/** 图片加载失败标记（回退占位，避免出现破图标） */
const annotatedFailed = ref(false)
const thumbFailed = ref(false)

/** 切换样本记录时重置失败标记 */
watch(
  () => props.record,
  () => {
    annotatedFailed.value = false
    thumbFailed.value = false
  },
)
</script>

<template>
  <div v-if="record" class="sample-viewer">
    <div class="sample-viewer__head">
      <span class="sample-viewer__title">样本核对</span>
      <SeverityTag :level="record.severity_level ?? 0" :label="record.severity_label" />
    </div>
    <div class="sample-viewer__body">
      <div class="sample-viewer__img-wrap">
        <img
          v-if="annotated && !annotatedFailed"
          class="sample-viewer__img"
          :src="annotated"
          alt="标注图"
          @error="annotatedFailed = true"
        />
        <div v-else class="sample-viewer__placeholder">标注图暂不可用</div>
        <span class="sample-viewer__tag">标注图</span>
      </div>
      <div class="sample-viewer__img-wrap">
        <img
          v-if="thumb && !thumbFailed"
          class="sample-viewer__img"
          :src="thumb"
          alt="缩略图"
          @error="thumbFailed = true"
        />
        <div v-else class="sample-viewer__placeholder">缩略图暂不可用</div>
        <span class="sample-viewer__tag">原图</span>
      </div>
    </div>
    <div class="sample-viewer__meta">
      <span>作物：{{ record.crop_cn || record.crop || '—' }}</span>
      <span>病害：{{ record.disease_cn || record.disease || '—' }}</span>
      <span v-if="record.top_conf !== undefined && record.top_conf !== null">
        置信度：{{ (Number(record.top_conf) * 100).toFixed(1) }}%
      </span>
    </div>
  </div>
</template>

<style scoped>
.sample-viewer {
  border: 1px solid var(--pc-border);
  border-radius: var(--pc-radius);
  padding: 10px 12px;
  background: var(--pc-bg);
}
.sample-viewer__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.sample-viewer__title {
  font-size: 12px;
  font-weight: 600;
  color: var(--pc-text);
}
.sample-viewer__body {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.sample-viewer__img-wrap {
  position: relative;
  border-radius: var(--pc-radius);
  overflow: hidden;
  background: var(--pc-panel);
  height: 120px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.sample-viewer__img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.sample-viewer__placeholder {
  font-size: 11px;
  color: var(--pc-text-muted);
}
.sample-viewer__tag {
  position: absolute;
  left: 6px;
  bottom: 6px;
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
}
.sample-viewer__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-top: 8px;
  font-size: 11px;
  color: var(--pc-text-muted);
}
</style>
