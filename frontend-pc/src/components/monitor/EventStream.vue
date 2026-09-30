<script setup>
/**
 * 实时事件流容器（大屏，ui-design.md §4.3 ⑤）。
 * - 「● LIVE」标记由 store.connected 驱动
 * - 新事件顶部插入并短暂高亮（避免自动滚动打断阅读，§7.6）
 * - 空态给出引导文案
 */
import { computed, nextTick, ref, watch } from 'vue'

import EventItem from './EventItem.vue'
import { useMonitorStore } from '@/stores/monitor'

const monitorStore = useMonitorStore()

const listEl = ref(null)
/** 最新事件 id（用于高亮） */
const highlightId = ref('')

const events = computed(() => monitorStore.events)
const connected = computed(() => monitorStore.connected)

/** 新事件到达 → 记录高亮 id（顶部插入，无需滚动） */
watch(
  () => events.value.length && events.value[0] && events.value[0].id,
  (id) => {
    if (!id) return
    highlightId.value = id
    nextTick(() => {
      // 保证滚动条回到顶部（新事件在顶部）
      if (listEl.value) listEl.value.scrollTop = 0
    })
    setTimeout(() => {
      if (highlightId.value === id) highlightId.value = ''
    }, 1600)
  },
)
</script>

<template>
  <div class="event-stream">
    <div class="event-stream__head">
      <span class="event-stream__title">实时事件流</span>
      <span class="event-stream__live" :class="{ 'is-on': connected }">
        {{ connected ? '● LIVE' : '○ 未连接' }}
      </span>
    </div>

    <div ref="listEl" class="event-stream__list">
      <div v-if="!events.length" class="event-stream__empty">
        <span class="event-stream__empty-icon">📡</span>
        <span>暂无实时事件</span>
        <span class="event-stream__empty-hint">检测 / 工单 / 预警动作将在此滚动显示</span>
      </div>
      <div
        v-for="evt in events"
        :key="evt.id"
        class="event-stream__row"
        :class="{ 'is-new': evt.id === highlightId }"
      >
        <EventItem :event="evt" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.event-stream {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.event-stream__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--pc-border);
}
.event-stream__title {
  font-weight: 600;
  color: var(--pc-text);
  font-size: 13px;
}
.event-stream__live {
  font-size: 11px;
  font-weight: 700;
  color: var(--pc-text-muted);
}
.event-stream__live.is-on {
  color: var(--pc-primary);
}
.event-stream__list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 4px;
}
.event-stream__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 36px 8px;
  color: var(--pc-text-muted);
  font-size: 12px;
  text-align: center;
}
.event-stream__empty-icon {
  font-size: 26px;
  opacity: 0.7;
}
.event-stream__empty-hint {
  font-size: 11px;
  opacity: 0.75;
}
.event-stream__row {
  transition: background-color 0.6s ease;
  border-radius: var(--pc-radius-sm);
}
.event-stream__row.is-new {
  background-color: rgba(43, 164, 113, 0.12);
}
</style>
