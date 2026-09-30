<script setup>
/**
 * 单条实时事件（ui-design.md §4.3 ⑤：彩色圆点分类）。
 * 绿=检测 / 红=预警 / 琥珀=工单。
 */
import { computed } from 'vue'

const props = defineProps({
  /** 事件对象 {type,kind,ts,data} */
  event: { type: Object, required: true },
})

/** kind → 圆点颜色 */
const DOT_COLOR = {
  detection: '#2BA471',
  warning: '#E5534B',
  feedback: '#F5A623',
}

/** kind → 类型标签 */
const KIND_LABEL = {
  detection: '检测',
  warning: '预警',
  feedback: '工单',
}

const kind = computed(() => props.event.kind || 'detection')
const dotColor = computed(() => DOT_COLOR[kind.value] || '#6B7B71')
const kindLabel = computed(() => KIND_LABEL[kind.value] || '事件')

/** 时间戳格式化：ISO-8601(UTC) → 本地 HH:MM:SS */
const timeText = computed(() => {
  const ts = props.event.ts
  if (!ts) return ''
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return String(ts)
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
})

/** 事件摘要文案（按事件类型拼装，不复制后端映射表） */
const summary = computed(() => {
  const d = props.event.data || {}
  switch (props.event.type) {
    case 'detection.created': {
      const who = d.nickname || d.username || `用户#${d.user_id ?? '-'}`
      const disease = d.disease_cn || d.top_disease || '未知病害'
      const crop = d.crop_cn || d.crop || ''
      const conf = d.top_conf !== undefined ? ` 置信度 ${(Number(d.top_conf) * 100).toFixed(1)}%` : ''
      return `${who} 检测出 ${crop ? crop + '·' : ''}${disease}（${d.severity_label || '—'}）${conf}`
    }
    case 'warning.created': {
      const disease = d.disease_cn || d.disease || '未知病害'
      const riskMap = { high: '高风险', mid: '中风险', low: '低风险' }
      const risk = riskMap[d.risk_level] || d.risk_level || ''
      return `${d.location || '全局'} 生成${risk}预警：${disease}（${d.forecast_date || ''}）`
    }
    case 'feedback.created': {
      const who = d.username || `用户#${d.user_id ?? '-'}`
      return `${who} 提交工单「${d.title || '—'}」`
    }
    case 'feedback.replied': {
      return `${d.admin_name || '管理员'} 回复了工单「${d.title || '—'}」`
    }
    default:
      return props.event.type
  }
})
</script>

<template>
  <div class="event-item">
    <span class="event-item__dot" :style="{ backgroundColor: dotColor }" />
    <div class="event-item__body">
      <div class="event-item__row">
        <span class="event-item__kind" :style="{ color: dotColor }">{{ kindLabel }}</span>
        <span class="event-item__time cd-mono">{{ timeText }}</span>
      </div>
      <div class="event-item__text">{{ summary }}</div>
    </div>
  </div>
</template>

<style scoped>
.event-item {
  display: flex;
  gap: 10px;
  padding: 8px 4px;
  border-bottom: 1px dashed var(--pc-border);
}
.event-item:last-child {
  border-bottom: none;
}
.event-item__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-top: 5px;
  flex-shrink: 0;
}
.event-item__body {
  flex: 1;
  min-width: 0;
}
.event-item__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.event-item__kind {
  font-size: 11px;
  font-weight: 700;
}
.event-item__time {
  font-size: 11px;
  color: var(--pc-text-muted);
}
.event-item__text {
  margin-top: 2px;
  font-size: 12px;
  color: var(--pc-text);
  line-height: 1.5;
  word-break: break-all;
}
</style>
