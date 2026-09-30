<template>
  <div class="cd-empty">
    <div class="cd-empty__illus">{{ icon }}</div>
    <div class="cd-empty__title">{{ title }}</div>
    <div v-if="hint" class="cd-empty__hint">{{ hint }}</div>
    <van-button
      v-if="actionText"
      round
      type="primary"
      class="cd-empty__btn"
      size="normal"
      @click="$emit('action')"
    >
      {{ actionText }}
    </van-button>
  </div>
</template>

<script setup>
/**
 * 空状态引导（ui-design.md §6）：插画位 + 文案 + 可选操作按钮。
 */
defineProps({
  /** 插画位 emoji */
  icon: { type: String, default: '🌾' },
  /** 主文案 */
  title: { type: String, default: '暂无内容' },
  /** 辅助文案 */
  hint: { type: String, default: '' },
  /** 操作按钮文字，空串则不显示 */
  actionText: { type: String, default: '' },
})

defineEmits(['action'])
</script>

<style scoped>
.cd-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 56px 24px 40px;
  text-align: center;
}

.cd-empty__illus {
  width: 88px;
  height: 88px;
  border-radius: 50%;
  background: var(--color-primary-soft);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 44px;
  margin-bottom: 16px;
}

.cd-empty__title {
  font: var(--font-h2);
  color: var(--color-text);
}

.cd-empty__hint {
  margin-top: 8px;
  font: var(--font-caption);
  color: var(--color-text-muted);
  line-height: 1.6;
}

.cd-empty__btn {
  margin-top: 20px;
  min-width: 160px;
  height: 44px;
  border-radius: var(--radius-button);
  font-size: 15px;
}
</style>
