<template>
  <div class="cd-page cd-kbdoc">
    <PageNav :title="doc ? doc.title : '知识文档'" />

    <div class="cd-page__body">
      <van-loading v-if="loading" class="cd-kbdoc__loading">加载中…</van-loading>

      <EmptyState
        v-else-if="!doc"
        icon="📄"
        title="文档不存在或已下架"
        action-text="返回知识库"
        @action="router.replace('/knowledge')"
      />

      <template v-else>
        <!-- 元信息 -->
        <div class="cd-kbdoc__meta">
          <van-tag v-if="doc.crop" plain type="primary">{{ doc.crop }}</van-tag>
          <van-tag v-if="doc.disease" plain type="primary">{{ doc.disease }}</van-tag>
          <span class="cd-kbdoc__time">更新于 {{ formatDateTime(doc.updated_at) }}</span>
        </div>

        <!-- Markdown 正文（已转义渲染） -->
        <div class="cd-kbdoc__body cd-md" v-html="contentHtml"></div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import EmptyState from '@/components/common/EmptyState.vue'
import PageNav from '@/components/common/PageNav.vue'
import * as knowledgeApi from '@/api/knowledge'
import { renderMarkdown } from '@/utils/markdown'
import { formatDateTime } from '@/utils/format'

/**
 * 知识文档详情页：Markdown 正文渲染（页面内自带 md 基础排版样式）。
 */
const route = useRoute()
const router = useRouter()

const doc = ref(null)
const loading = ref(false)

const contentHtml = computed(() => renderMarkdown(doc.value && doc.value.content_md))

async function load(id) {
  const numId = Number(id)
  if (!numId || Number.isNaN(numId)) {
    doc.value = null
    return
  }
  loading.value = true
  try {
    doc.value = await knowledgeApi.getKnowledgeDoc(numId)
  } catch (e) {
    doc.value = null
  } finally {
    loading.value = false
  }
}

watch(() => route.params.id, load, { immediate: true })
</script>

<style scoped>
.cd-kbdoc {
  display: flex;
  flex-direction: column;
  /* 内容型页面随 body 滚动：min-height + 底部留白（防固定元素遮挡） */
  min-height: 100%;
  padding-bottom: calc(50px + env(safe-area-inset-bottom));
  background: var(--color-bg);
}

.cd-kbdoc__loading {
  display: flex;
  justify-content: center;
  padding: 48px 0;
  color: var(--color-text-muted);
}

.cd-kbdoc__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px 0;
}

.cd-kbdoc__time {
  margin-left: auto;
  font: var(--font-mini);
  color: var(--color-text-muted);
}

/* 正文卡片 */
.cd-kbdoc__body {
  margin: 12px;
  padding: 16px;
  background: var(--color-surface);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
}
</style>

<style>
/* 知识库 Markdown 正文排版（全局样式：v-html 内容无 scoped） */
.cd-md h1,
.cd-md h2,
.cd-md h3,
.cd-md h4,
.cd-md h5,
.cd-md h6 {
  color: var(--color-text);
  margin: 16px 0 8px;
  font-weight: 600;
}

.cd-md h1 {
  font-size: 20px;
}

.cd-md h2 {
  font-size: 17px;
}

.cd-md h3,
.cd-md h4,
.cd-md h5,
.cd-md h6 {
  font-size: 15px;
}

.cd-md p {
  margin: 8px 0;
  font: var(--font-body);
  color: var(--color-text);
  line-height: 1.8;
}

.cd-md ul,
.cd-md ol {
  margin: 8px 0;
  padding-left: 22px;
}

.cd-md li {
  font: var(--font-body);
  color: var(--color-text);
  line-height: 1.8;
}

.cd-md blockquote {
  margin: 8px 0;
  padding: 6px 12px;
  border-left: 3px solid var(--color-primary);
  background: var(--color-primary-soft);
  border-radius: 0 8px 8px 0;
  color: var(--color-text-muted);
  font: var(--font-caption);
}

.cd-md code {
  background: var(--color-bg);
  border-radius: 4px;
  padding: 1px 5px;
  font-size: 13px;
  color: var(--color-primary-dark);
}

.cd-md pre {
  background: var(--color-bg);
  border-radius: 8px;
  padding: 12px;
  overflow-x: auto;
}

.cd-md pre code {
  background: transparent;
  padding: 0;
}

.cd-md hr {
  border: none;
  border-top: 1px solid var(--color-border);
  margin: 14px 0;
}

.cd-md a {
  color: var(--color-primary);
}
</style>
