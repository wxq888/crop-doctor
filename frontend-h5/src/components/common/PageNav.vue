<template>
  <div class="cd-page-nav">
    <van-icon name="arrow-left" class="cd-page-nav__back" @click="goBack" />
    <div class="cd-page-nav__title">{{ title }}</div>
    <div class="cd-page-nav__right">
      <slot name="right"></slot>
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'

/**
 * 二级页顶部导航：左返回 + 标题 + 右操作区（slot）。
 */
defineProps({
  title: { type: String, default: '' },
})

const router = useRouter()

/** 返回上一页；无历史（如直接打开链接）时兜底回首页 */
function goBack() {
  if (window.history.length > 1) {
    router.back()
  } else {
    router.replace('/home')
  }
}
</script>

<style scoped>
.cd-page-nav {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  height: 50px;
  padding: 0 12px;
  padding-top: env(safe-area-inset-top);
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
}

.cd-page-nav__back {
  flex: 0 0 auto;
  font-size: 20px;
  color: var(--color-text);
  padding: 6px 10px 6px 2px;
}

.cd-page-nav__title {
  flex: 1;
  min-width: 0;
  font: var(--font-h2);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cd-page-nav__right {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 16px;
  font-size: 19px;
  color: var(--color-text);
}
</style>
