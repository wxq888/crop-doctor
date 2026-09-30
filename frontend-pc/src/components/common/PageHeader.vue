<script setup>
/**
 * 页标题 + 副标题 + 右侧操作区插槽（各页统一头部）。
 */
defineProps({
  /** 主标题 */
  title: { type: String, default: '' },
  /** 副标题 / 说明 */
  subtitle: { type: String, default: '' },
})
</script>

<template>
  <div class="page-header">
    <div class="page-header__left">
      <h2 class="page-header__title">{{ title }}</h2>
      <p v-if="subtitle" class="page-header__subtitle">{{ subtitle }}</p>
    </div>
    <div class="page-header__actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}
.page-header__title {
  margin: 0;
  font: var(--pc-font-h1);
  color: var(--pc-text);
}
.page-header__subtitle {
  margin: 6px 0 0;
  font: var(--pc-font-sm);
  color: var(--pc-text-muted);
}
.page-header__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
</style>
