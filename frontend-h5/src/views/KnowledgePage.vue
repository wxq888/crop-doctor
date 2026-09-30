<template>
  <div class="cd-page cd-kb">
    <header class="cd-kb__head">
      <div class="cd-kb__title">知识库</div>
      <van-search
        v-model="keyword"
        class="cd-kb__search"
        placeholder="搜索病害防治知识，如：晚疫病"
        shape="round"
        @search="onSearch"
      />
      <!-- 搜索结果模式提示条 -->
      <div v-if="searchMode" class="cd-kb__search-bar">
        <span>
          搜索「{{ searchedKw }}」共 {{ searchHits.length }} 条结果（{{ searchModeType === 'semantic' ? '语义检索' : '关键字检索' }}）
        </span>
        <span class="cd-kb__search-cancel" @click="exitSearch">返回门户</span>
      </div>
    </header>

    <div class="cd-page__body">
      <!-- ===== 搜索结果模式 ===== -->
      <template v-if="searchMode">
        <div v-if="searching" class="cd-kb__loading"><van-loading>搜索中…</van-loading></div>
        <EmptyState
          v-else-if="!searchHits.length"
          icon="🔍"
          title="没有找到相关资料"
          hint="换个关键词试试，或浏览下方作物分类"
        />
        <div
          v-for="(hit, i) in searchHits"
          :key="`hit-${i}`"
          class="cd-kb__doc"
          @click="openHit(hit)"
        >
          <div class="cd-kb__doc-title">
            {{ hit.title }}
            <van-tag v-if="hit.section" plain type="primary" class="cd-kb__doc-sec">{{ hit.section }}</van-tag>
          </div>
          <div class="cd-kb__doc-snippet">{{ hit.snippet || '暂无摘要' }}</div>
        </div>
      </template>

      <!-- ===== 门户模式 ===== -->
      <template v-else>
        <!-- 作物分类 chips -->
        <div class="cd-kb__chips">
          <span
            class="cd-kb__chip"
            :class="{ 'cd-kb__chip--active': selectedCrop === '' }"
            @click="selectCrop('')"
          >
            全部
          </span>
          <span
            v-for="c in crops"
            :key="c.crop_cn"
            class="cd-kb__chip"
            :class="{ 'cd-kb__chip--active': selectedCrop === c.crop_cn }"
            @click="selectCrop(c.crop_cn)"
          >
            {{ c.crop_cn }}（{{ c.disease_count }}）
          </span>
        </div>

        <van-list
          v-model:loading="loading"
          :finished="finished"
          finished-text="没有更多了"
          loading-text="加载中…"
          @load="onLoad"
        >
          <div
            v-for="doc in docs"
            :key="doc.id"
            class="cd-kb__doc"
            @click="router.push(`/knowledge/docs/${doc.id}`)"
          >
            <div class="cd-kb__doc-title">{{ doc.title }}</div>
            <div class="cd-kb__doc-snippet">{{ doc.snippet || '点击查看全文' }}</div>
            <div class="cd-kb__doc-meta">
              <van-tag v-if="doc.crop" plain type="primary">{{ doc.crop }}</van-tag>
              <van-tag v-if="doc.disease" plain type="primary">{{ doc.disease }}</van-tag>
              <span class="cd-kb__doc-time">{{ formatDateTime(doc.updated_at) }}</span>
            </div>
          </div>
        </van-list>

        <van-loading v-if="loading && !docs.length" class="cd-kb__loading">加载中…</van-loading>

        <EmptyState
          v-if="finished && !docs.length && !loading"
          icon="📚"
          title="该分类暂无文档"
          hint="知识库资料持续补充中，可尝试搜索"
        />
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'

import EmptyState from '@/components/common/EmptyState.vue'
import * as knowledgeApi from '@/api/knowledge'
import { formatDateTime } from '@/utils/format'

/**
 * 知识库 Tab：搜索框 → 作物分类 chips → 文档列表 → 详情（Markdown）。
 * 搜索走 GET /knowledge/search（语义优先，未就绪回退关键字）。
 */
const router = useRouter()

const keyword = ref('')
const searchedKw = ref('')
const searchMode = ref(false)
const searchModeType = ref('keyword')
const searchHits = ref([])
const searching = ref(false)

const crops = ref([])
const selectedCrop = ref('')

const docs = ref([])
const page = ref(1)
const PAGE_SIZE = 10
const loading = ref(false)
const finished = ref(false)

// ===== 门户模式 =====

async function loadCrops() {
  try {
    const res = await knowledgeApi.getKnowledgeCrops()
    crops.value = (res && res.items) || []
  } catch (e) {
    crops.value = []
  }
}

function selectCrop(cropCn) {
  if (selectedCrop.value === cropCn) return
  selectedCrop.value = cropCn
  docs.value = []
  page.value = 1
  finished.value = false
  if (!loading.value) {
    loading.value = true
    onLoad()
  }
}

async function onLoad() {
  try {
    const params = { page: page.value, page_size: PAGE_SIZE }
    if (selectedCrop.value) params.crop = selectedCrop.value
    const res = await knowledgeApi.listKnowledgeDocs(params)
    const list = (res && res.items) || []
    docs.value.push(...list)
    loading.value = false
    if (!list.length || docs.value.length >= ((res && res.total) || 0)) {
      finished.value = true
    } else {
      page.value += 1
    }
  } catch (e) {
    loading.value = false
    finished.value = true
  }
}

// ===== 搜索模式 =====

async function onSearch() {
  const q = keyword.value.trim()
  if (!q) {
    showToast('请输入搜索关键词')
    return
  }
  searchedKw.value = q
  searchMode.value = true
  searching.value = true
  try {
    const res = await knowledgeApi.searchKnowledge(q, 10)
    searchHits.value = (res && res.items) || []
    searchModeType.value = (res && res.mode) || 'keyword'
  } catch (e) {
    searchHits.value = []
  } finally {
    searching.value = false
  }
}

function exitSearch() {
  searchMode.value = false
  searchHits.value = []
  keyword.value = ''
}

/** 打开搜索命中项：doc_id 可能为空（片段无对应文档），如实提示 */
function openHit(hit) {
  if (hit && hit.doc_id != null) {
    router.push(`/knowledge/docs/${hit.doc_id}`)
  } else {
    showToast('该片段暂无对应文档')
  }
}

loadCrops()
</script>

<style scoped>
.cd-kb {
  display: flex;
  flex-direction: column;
  /* 内容型页面随 body 滚动：min-height + TabBar 底部留白（防遮挡） */
  min-height: 100%;
  padding-bottom: calc(50px + env(safe-area-inset-bottom));
  background: var(--color-bg);
}

.cd-kb__head {
  flex: 0 0 auto;
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
  padding-top: env(safe-area-inset-top);
}

.cd-kb__title {
  font: var(--font-h2);
  color: var(--color-text);
  padding: 14px 16px 0;
}

.cd-kb__search {
  background: transparent;
}

.cd-kb__search :deep(.van-search__content) {
  background: var(--color-bg);
  border-radius: var(--radius-button);
}

.cd-kb__search-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px 10px;
  font: var(--font-mini);
  color: var(--color-text-muted);
}

.cd-kb__search-cancel {
  color: var(--color-primary);
  font-weight: 600;
  padding: 2px 6px;
}

/* 作物分类 chips：横向滚动 */
.cd-kb__chips {
  display: flex;
  gap: 8px;
  padding: 12px;
  overflow-x: auto;
  white-space: nowrap;
  -webkit-overflow-scrolling: touch;
}

.cd-kb__chip {
  flex: 0 0 auto;
  padding: 6px 14px;
  border-radius: var(--radius-button);
  background: var(--color-surface);
  font: var(--font-caption);
  color: var(--color-text);
  box-shadow: var(--shadow-card);
}

.cd-kb__chip--active {
  background: var(--color-primary);
  color: #fff;
  font-weight: 600;
}

/* 文档卡片 */
.cd-kb__doc {
  margin: 0 12px 10px;
  padding: var(--space-12);
  background: var(--color-surface);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
}

.cd-kb__doc-title {
  font: var(--font-h2);
  color: var(--color-text);
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.cd-kb__doc-sec {
  font-weight: 400;
}

.cd-kb__doc-snippet {
  margin-top: 6px;
  font: var(--font-caption);
  color: var(--color-text-muted);
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.cd-kb__doc-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}

.cd-kb__doc-time {
  margin-left: auto;
  font: var(--font-mini);
  color: var(--color-text-muted);
}

.cd-kb__loading {
  display: flex;
  justify-content: center;
  padding: 32px 0;
  color: var(--color-text-muted);
}
</style>
