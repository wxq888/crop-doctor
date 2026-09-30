<template>
  <!-- 快捷问题胶囊：点击直接发送 -->
  <div class="cd-quick">
    <div v-for="(q, i) in questions" :key="i" class="cd-quick__chip" @click="$emit('select', q)">
      {{ q }}
    </div>
  </div>
</template>

<script setup>
defineProps({
  /** 问题文案数组 */
  questions: {
    type: Array,
    default: () => [],
  },
})

defineEmits(['select'])
</script>

<style scoped>
.cd-quick {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  padding: 4px 4px 0;
}

.cd-quick__chip {
  padding: 8px 14px;
  border-radius: var(--radius-button);
  background: var(--color-surface);
  color: var(--color-primary);
  font: var(--font-caption);
  border: 1px solid var(--color-primary-soft);
  box-shadow: var(--shadow-card);
  transition: transform 0.15s ease;
}

.cd-quick__chip:active {
  transform: scale(0.96);
  background: var(--color-primary-soft);
}
</style>
