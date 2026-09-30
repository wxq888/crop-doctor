<template>
  <div class="cd-page cd-about">
    <PageNav title="关于" />

    <div class="cd-page__body">
      <div class="cd-about__card">
        <div class="cd-about__logo">🌱</div>
        <div class="cd-about__name">作物医生 CropDoctor</div>
        <div class="cd-about__version">v1.0.0</div>
        <div class="cd-about__slogan">拍照识病害 · AI 帮你看田</div>

        <div class="cd-about__divider"></div>

        <div class="cd-about__item">
          <span class="cd-about__item-icon">📷</span>
          <div>
            <div class="cd-about__item-title">病害检测</div>
            <div class="cd-about__item-desc">拍照上传叶片，AI 秒级识别病害并给出严重程度分级</div>
          </div>
        </div>
        <div class="cd-about__item">
          <span class="cd-about__item-icon">💬</span>
          <div>
            <div class="cd-about__item-title">智能问诊</div>
            <div class="cd-about__item-desc">基于权威知识库资料回答病害识别与防治问题，答案可溯源</div>
          </div>
        </div>
        <div class="cd-about__item">
          <span class="cd-about__item-icon">⚠️</span>
          <div>
            <div class="cd-about__item-title">风险预警</div>
            <div class="cd-about__item-desc">结合气象预报评估病害爆发风险，提前推送防治建议</div>
          </div>
        </div>
      </div>

      <p class="cd-about__footer">本应用检测结果仅供参考，重大病害请咨询当地农技部门</p>
    </div>
  </div>
</template>

<script setup>
import PageNav from '@/components/common/PageNav.vue'
</script>

<style scoped>
.cd-about {
  display: flex;
  flex-direction: column;
  /* 内容型页面随 body 滚动：min-height + 底部留白（防固定元素遮挡） */
  min-height: 100%;
  padding-bottom: calc(50px + env(safe-area-inset-bottom));
  background: var(--color-bg);
}

.cd-about__card {
  margin: 12px;
  padding: 28px 20px;
  background: var(--color-surface);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  text-align: center;
}

.cd-about__logo {
  width: 72px;
  height: 72px;
  margin: 0 auto 12px;
  border-radius: 20px;
  background: var(--color-primary-soft);
  font-size: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.cd-about__name {
  font: var(--font-h1);
  color: var(--color-text);
}

.cd-about__version {
  margin-top: 4px;
  font: var(--font-mini);
  color: var(--color-text-muted);
}

.cd-about__slogan {
  margin-top: 8px;
  font: var(--font-caption);
  color: var(--color-primary);
  font-weight: 600;
  letter-spacing: 1px;
}

.cd-about__divider {
  height: 1px;
  background: var(--color-border);
  margin: 18px 0;
}

/* 功能介绍 */
.cd-about__item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 14px;
  text-align: left;
}

.cd-about__item:last-child {
  margin-bottom: 0;
}

.cd-about__item-icon {
  flex: 0 0 auto;
  font-size: 22px;
}

.cd-about__item-title {
  font: var(--font-body);
  font-weight: 600;
  color: var(--color-text);
}

.cd-about__item-desc {
  margin-top: 2px;
  font: var(--font-caption);
  color: var(--color-text-muted);
  line-height: 1.6;
}

.cd-about__footer {
  margin: 4px 24px;
  text-align: center;
  font: var(--font-mini);
  color: var(--color-text-muted);
  line-height: 1.7;
}
</style>
