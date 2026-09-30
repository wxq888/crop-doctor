<template>
  <!-- 引用来源灰条：AI 气泡下方展示引用信息 -->
  <!-- 兜底：过滤掉既无标题也无摘要的脏条目；无有效条目时整条不渲染，避免空白项 -->
  <div v-if="visibleCitations.length" class="cd-citation-bar">
    <!-- 流式中：只渲染一行紧凑摘要，不渲染卡片/摘要正文，避免把回答正文顶出视口 -->
    <div v-if="streaming" class="cd-citation-bar__summary">
      <van-icon name="records-o" class="cd-citation-bar__summary-icon" />
      <span>正在引用 {{ visibleCitations.length }} 篇资料…</span>
    </div>

    <!-- 流式结束：默认折叠为一行摘要头，点击整行展开/收起卡片列表 -->
    <template v-else>
      <button class="cd-citation-bar__head" type="button" @click="panelOpen = !panelOpen">
        <van-icon name="records-o" />
        <span class="cd-citation-bar__head-text">引用来源 · {{ visibleCitations.length }} 篇</span>
        <van-icon
          class="cd-citation-bar__toggle"
          :class="{ 'cd-citation-bar__toggle--open': panelOpen }"
          name="arrow-down"
        />
      </button>

      <div v-show="panelOpen" class="cd-citation-bar__list">
        <div
          v-for="(item, index) in visibleCitations"
          :key="item.doc_id || index"
          class="cd-citation"
          @click="toggle(index)"
        >
          <div class="cd-citation__head">
            <span class="cd-citation__idx">[{{ index + 1 }}]</span>
            <span class="cd-citation__name">{{ item.title }}</span>
            <van-icon
              class="cd-citation__arrow"
              :name="expanded === index ? 'arrow-up' : 'arrow-down'"
            />
          </div>
          <div v-if="item.snippet" class="cd-citation__snippet">{{ item.snippet }}</div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  /** 引用数组 [{doc_id,title,snippet}] */
  citations: {
    type: Array,
    default: () => [],
  },
  /** 该条消息是否还在流式输出（true 时引用区只显示一行紧凑摘要） */
  streaming: {
    type: Boolean,
    default: false,
  },
})

/**
 * 归一化 + 去脏：
 * - 非数组 → 空数组（防御后端异常下发的类型）
 * - title 缺失时回退为「未知来源」，避免渲染成空白项
 * - 既无标题也无摘要的条目直接丢弃（防止空白项/报错）
 */
const visibleCitations = computed(() => {
  const list = Array.isArray(props.citations) ? props.citations : []
  return list
    .filter((it) => it && (it.title || it.snippet))
    .map((it) => ({
      doc_id: it.doc_id != null ? it.doc_id : '',
      title: it.title || '未知来源',
      snippet: it.snippet || '',
    }))
})

/** 卡片列表是否展开（流式结束后默认折叠，由用户点击整行控制） */
const panelOpen = ref(false)

/** 当前展开 snippet 的引用下标（-1 表示全部收起） */
const expanded = ref(-1)

// 流式期间强制收起卡片列表，防止 meta 帧先到时把上一轮的展开态带进来
watch(
  () => props.streaming,
  (val) => {
    if (val) panelOpen.value = false
  },
)

function toggle(index) {
  expanded.value = expanded.value === index ? -1 : index
}
</script>

<style scoped>
.cd-citation-bar {
  width: 100%;
  margin-top: 6px;
  padding: 8px 10px;
  border-radius: var(--radius-card);
  background: #eef1ef;
  border-left: 3px solid var(--color-text-muted);
}

/* 流式中的紧凑摘要行 */
.cd-citation-bar__summary {
  display: flex;
  align-items: center;
  gap: 4px;
  font: var(--font-mini);
  color: var(--color-text-muted);
  white-space: nowrap;
}

.cd-citation-bar__summary-icon {
  flex: 0 0 auto;
  font-size: 12px;
}

/* 折叠头：整行可点击（button 便于无障碍 + 点击热区） */
.cd-citation-bar__head {
  display: flex;
  align-items: center;
  gap: 4px;
  width: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  font: var(--font-mini);
  color: var(--color-text-muted);
  text-align: left;
  cursor: pointer;
}

.cd-citation-bar__head-text {
  flex: 1;
  min-width: 0;
}

/* 折叠箭头旋转过渡 */
.cd-citation-bar__toggle {
  flex: 0 0 auto;
  font-size: 12px;
  transition: transform 0.2s ease;
}

.cd-citation-bar__toggle--open {
  transform: rotate(180deg);
}

/* 卡片列表容器 */
.cd-citation-bar__list {
  margin-top: 4px;
}

.cd-citation {
  padding: 3px 0;
  cursor: pointer;
}

.cd-citation__head {
  display: flex;
  align-items: center;
  gap: 4px;
}

.cd-citation__idx {
  color: var(--color-primary);
  font: var(--font-mini);
  font-weight: 600;
}

.cd-citation__name {
  flex: 1;
  min-width: 0;
  font: var(--font-mini);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cd-citation__arrow {
  font-size: 12px;
  color: var(--color-text-muted);
}

.cd-citation__snippet {
  margin: 4px 0 2px 20px;
  padding: 6px 8px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.75);
  font: var(--font-mini);
  color: var(--color-text-muted);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
