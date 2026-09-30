<template>
  <div class="cd-page cd-detail">
    <PageNav title="检测结果">
      <template #right>
        <van-icon name="delete-o" @click="onDelete" />
      </template>
    </PageNav>

    <div class="cd-page__body">
      <van-loading v-if="loading" class="cd-detail__loading">加载中…</van-loading>

      <EmptyState
        v-else-if="!record"
        icon="🧪"
        title="记录不存在或已删除"
        action-text="返回首页"
        @action="router.replace('/home')"
      />

      <template v-else>
        <!-- ① 标注图（红框病灶） -->
        <div class="cd-card cd-detail__img-card">
          <img class="cd-detail__img" :src="mainImageUrl" alt="检测结果标注图" />
          <div v-if="record.annotated_url" class="cd-detail__img-tip">
            {{ isHealthy ? '叶片健康，框线为 AI 识别的叶片区域' : '红框为 AI 识别的病灶区域' }}
          </div>
        </div>

        <!-- ② 结论卡 -->
        <div class="cd-card cd-detail__conclusion">
          <div class="cd-detail__crop">{{ cropText }}</div>
          <div class="cd-detail__disease-row">
            <h1 class="cd-detail__disease">{{ diseaseText }}</h1>
            <SeverityTag
              v-if="isHealthy"
              :level="0"
              label="健康"
              :color="HEALTHY_COLOR"
            />
            <SeverityTag v-else :level="record.severity_level" :label="record.severity_label" />
          </div>
          <div class="cd-detail__metrics">
            <span>置信度 {{ confText }}</span>
            <template v-if="!isHealthy">
              <span>病斑 {{ record.spot_count }} 处</span>
              <span>面积占比 {{ areaText }}</span>
            </template>
            <span v-else class="cd-detail__metrics--healthy">叶片健康，未检出病斑</span>
          </div>
        </div>

        <!-- ③ Grad-CAM 热力图卡（异步轮询：pending 占位 / done 出图 / failed 失败） -->
        <div class="cd-card">
          <div class="cd-card__title">
            病灶热力图
            <span class="cd-card__title-sub">Grad-CAM · 模型关注区域</span>
          </div>
          <div v-if="gradcamState === 'pending'" class="cd-detail__gc-pending">
            <van-loading size="22" color="var(--color-primary)" />
            <span>热力图生成中，约需几秒…</span>
          </div>
          <img v-else-if="gradcamState === 'done'" class="cd-detail__gc-img" :src="gradcamUrl" alt="Grad-CAM 热力图" />
          <div v-else-if="gradcamState === 'skipped'" class="cd-detail__gc-empty">该记录未生成热力图</div>
          <div v-else class="cd-detail__gc-failed">
            <van-icon name="warning-o" />
            热力图生成失败，请稍后在 PC 端重试
          </div>
        </div>

        <!-- ④ 天气施药提示行（degraded → 暂无天气数据） -->
        <div class="cd-card cd-detail__weather">
          <span class="cd-detail__weather-icon">🌤</span>
          <div class="cd-detail__weather-body">
            <div class="cd-detail__weather-label">施药建议</div>
            <p v-if="sprayOk" class="cd-detail__weather-text">
              {{ spray.advice }}
              <template v-if="spray.next_rain_date">（{{ spray.next_rain_date }} 有降雨，请合理安排施药时间）</template>
            </p>
            <p v-else class="cd-detail__weather-text cd-detail__weather-text--muted">暂无天气数据</p>
          </div>
        </div>

        <!-- ⑤ 操作区 -->
        <div class="cd-detail__actions">
          <van-button round block type="primary" class="cd-btn-main" @click="goChat">去问诊</van-button>
          <van-button round block plain type="primary" class="cd-btn-sub" @click="showFeedback = true">
            结果对吗？反馈
          </van-button>
        </div>
      </template>
    </div>

    <!-- 反馈弹层：正确 / 错误 / 存疑 三选 + 可选正确病害名 -->
    <van-popup v-model:show="showFeedback" position="bottom" round class="cd-detail__fb-popup">
      <div class="cd-fb">
        <div class="cd-fb__title">这次检测结果准确吗？</div>
        <van-radio-group v-model="verdict" class="cd-fb__radios">
          <van-radio name="correct" class="cd-fb__radio">✅ 检测结果正确</van-radio>
          <van-radio name="wrong" class="cd-fb__radio">❌ 检测结果错误</van-radio>
          <van-radio name="unsure" class="cd-fb__radio">🤔 不确定 / 存疑</van-radio>
        </van-radio-group>
        <van-field
          v-if="verdict === 'wrong'"
          v-model="correctDisease"
          class="cd-fb__field"
          label="正确病害"
          placeholder="选填，如：番茄早疫病"
        />
        <van-field
          v-model="fbContent"
          class="cd-fb__field"
          type="textarea"
          rows="2"
          autosize
          maxlength="200"
          placeholder="补充说明（选填）"
        />
        <van-button
          block
          round
          type="primary"
          class="cd-btn-main cd-fb__submit"
          :loading="fbSubmitting"
          @click="submitFeedback"
        >
          提交反馈
        </van-button>
      </div>
    </van-popup>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showConfirmDialog, showToast } from 'vant'

import EmptyState from '@/components/common/EmptyState.vue'
import PageNav from '@/components/common/PageNav.vue'
import SeverityTag from '@/components/common/SeverityTag.vue'
import * as detectionApi from '@/api/detection'
import { resolveStaticUrl } from '@/api/chat'
import { HEALTHY_COLOR } from '@/stores/chat'
import * as weatherApi from '@/api/weather'
import * as feedbackApi from '@/api/feedback'
import { useBadgeStore } from '@/stores/badge'
import { getLonLat } from '@/utils/geo'

/**
 * 检测详情页（ui-design.md §3.2 ②）：
 * 标注图 → 结论卡 → Grad-CAM（异步轮询）→ 天气施药提示 → 去问诊 / 反馈。
 */
const route = useRoute()
const router = useRouter()
const badgeStore = useBadgeStore()

const record = ref(null)
const loading = ref(false)

// Grad-CAM 状态机：idle / pending / done / failed / skipped
const gradcamState = ref('idle')
const gradcamUrl = ref('')
let pollTimer = null
let pollTries = 0
const POLL_INTERVAL = 3000
const POLL_MAX = 40

// 天气施药建议
const spray = ref(null)

// 反馈表单
const showFeedback = ref(false)
const verdict = ref('correct')
const correctDisease = ref('')
const fbContent = ref('')
const fbSubmitting = ref(false)

const VERDICT_TEXT = { correct: '正确', wrong: '错误', unsure: '存疑' }

// ===== 展示计算 =====
const mainImageUrl = computed(() =>
  resolveStaticUrl(record.value && (record.value.annotated_url || record.value.image_url)),
)
const cropText = computed(() => {
  const r = record.value || {}
  return r.crop_cn || r.crop || '未知作物'
})
const diseaseText = computed(() => {
  const r = record.value || {}
  return r.disease_cn || r.top_disease || '未知病害'
})
/** 健康类记录：分级展示映射为「健康」（绿色），病斑统计换成友好文案 */
const isHealthy = computed(() => record.value?.is_healthy === true)
const confText = computed(() =>
  record.value && record.value.top_conf != null ? `${Math.round(record.value.top_conf * 100)}%` : '—',
)
const areaText = computed(() =>
  record.value && record.value.area_ratio != null ? `${(record.value.area_ratio * 100).toFixed(1)}%` : '—',
)
const sprayOk = computed(() => {
  const s = spray.value
  return !!s && !s.degraded && !!s.advice
})

// ===== 数据加载 =====

async function loadRecord(id) {
  const numId = Number(id)
  if (!numId || Number.isNaN(numId)) {
    record.value = null
    return
  }
  loading.value = true
  try {
    record.value = await detectionApi.getDetectionRecord(numId)
    initGradcam()
    loadSprayAdvice()
  } catch (e) {
    record.value = null
  } finally {
    loading.value = false
  }
}

/** 热力图初始化：done 直接出图；pending 启动轮询；failed/skipped 直接落定 */
function initGradcam() {
  const r = record.value
  if (!r) return
  if (r.gradcam_status === 'done' && r.gradcam_url) {
    gradcamState.value = 'done'
    gradcamUrl.value = resolveStaticUrl(r.gradcam_url)
    return
  }
  if (r.gradcam_status === 'pending') {
    gradcamState.value = 'pending'
    pollTries = 0
    schedulePoll()
    return
  }
  gradcamState.value = r.gradcam_status === 'skipped' ? 'skipped' : 'failed'
}

function schedulePoll() {
  clearPoll()
  pollTimer = setTimeout(pollGradcam, POLL_INTERVAL)
}

async function pollGradcam() {
  const r = record.value
  if (!r || gradcamState.value !== 'pending') return
  pollTries += 1
  if (pollTries > POLL_MAX) {
    gradcamState.value = 'failed'
    return
  }
  try {
    const res = await detectionApi.getDetectionGradcam(r.id)
    const status = (res && res.status) || 'pending'
    if (status === 'done' && res.url) {
      gradcamState.value = 'done'
      gradcamUrl.value = resolveStaticUrl(res.url)
      return
    }
    if (status === 'failed') {
      gradcamState.value = 'failed'
      return
    }
    if (status === 'skipped') {
      gradcamState.value = 'skipped'
      return
    }
    schedulePoll()
  } catch (e) {
    // 单次轮询失败不终止，继续重试直至上限
    schedulePoll()
  }
}

function clearPoll() {
  if (pollTimer) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

onBeforeUnmount(clearPoll)

/** 天气施药建议（降级 → 暂无天气数据）
 *  优先按浏览器定位（经度,纬度）查询；定位不可用则不传 location，后端用默认位置。 */
async function loadSprayAdvice() {
  try {
    const location = await getLonLat()
    spray.value = await weatherApi.getSprayAdvice(location || '')
  } catch (e) {
    spray.value = null
  }
}

// 路由复用（同页面不同 id）时重新加载
watch(() => route.params.id, (id) => loadRecord(id), { immediate: true })

// ===== 动作 =====

/** 去问诊：携带检测上下文（ChatPage 已支持 detection_id） */
function goChat() {
  router.push({ path: '/chat', query: { detection_id: record.value.id } })
}

/** 删除该记录（带二次确认） */
async function onDelete() {
  if (!record.value) return
  try {
    await showConfirmDialog({
      title: '删除记录',
      message: '删除后该条检测记录及其热力图将不可恢复，确定删除？',
    })
  } catch (e) {
    return
  }
  try {
    await detectionApi.deleteDetectionRecord(record.value.id)
    showToast('已删除')
    router.replace('/records')
  } catch (e) {
    /* 拦截器已提示 */
  }
}

/** 提交结果反馈：POST /feedback（type=result_verdict） */
async function submitFeedback() {
  if (fbSubmitting.value) return
  fbSubmitting.value = true
  try {
    const r = record.value
    await feedbackApi.createFeedback({
      type: 'result_verdict',
      title: `检测结果反馈：${diseaseText.value}`,
      content:
        fbContent.value.trim() ||
        `AI 判定为「${diseaseText.value}」（严重度：${r.severity_label || '未知'}，置信度：${confText.value}），用户标记为${VERDICT_TEXT[verdict.value] || '存疑'}。`,
      record_id: r.id,
      verdict: verdict.value,
      correct_disease: verdict.value === 'wrong' && correctDisease.value.trim() ? correctDisease.value.trim() : null,
    })
    showFeedback.value = false
    fbContent.value = ''
    correctDisease.value = ''
    showToast('反馈已提交，感谢你的反馈')
  } catch (e) {
    /* 拦截器已提示 */
  } finally {
    fbSubmitting.value = false
  }
}
</script>

<style scoped>
.cd-detail {
  display: flex;
  flex-direction: column;
  /* 内容型页面随 body 滚动：min-height + 底部留白（防固定元素遮挡） */
  min-height: 100%;
  padding-bottom: calc(50px + env(safe-area-inset-bottom));
  background: var(--color-bg);
}

.cd-detail__loading {
  display: flex;
  justify-content: center;
  padding: 48px 0;
  color: var(--color-text-muted);
}

.cd-card {
  background: var(--color-surface);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  padding: var(--space-12);
  margin: 0 var(--space-12) var(--space-16);
}

.cd-card__title {
  font: var(--font-h2);
  color: var(--color-text);
  margin-bottom: 10px;
}

.cd-card__title-sub {
  margin-left: 8px;
  font: var(--font-mini);
  color: var(--color-text-muted);
  font-weight: 400;
}

/* ① 标注图 */
.cd-detail__img-card {
  margin-top: var(--space-12);
  padding: 0;
  overflow: hidden;
}

.cd-detail__img {
  display: block;
  width: 100%;
  max-height: 300px;
  object-fit: contain;
  background: var(--color-bg);
}

.cd-detail__img-tip {
  padding: 8px 12px;
  font: var(--font-mini);
  color: var(--color-text-muted);
}

/* ② 结论卡 */
.cd-detail__crop {
  font: var(--font-caption);
  color: var(--color-text-muted);
}

.cd-detail__disease-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 4px;
  flex-wrap: wrap;
}

.cd-detail__disease {
  margin: 0;
  font: var(--font-h1);
  color: var(--color-text);
}

.cd-detail__metrics {
  display: flex;
  gap: 16px;
  margin-top: 10px;
  font: var(--font-caption);
  color: var(--color-text-muted);
}

.cd-detail__metrics--healthy {
  color: var(--color-primary, #2ba471);
  font-weight: 600;
}

/* ③ Grad-CAM */
.cd-detail__gc-pending {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  height: 160px;
  border-radius: 10px;
  background: var(--color-bg);
  font: var(--font-caption);
  color: var(--color-text-muted);
}

.cd-detail__gc-img {
  display: block;
  width: 100%;
  max-height: 280px;
  object-fit: contain;
  border-radius: 10px;
  background: var(--color-bg);
}

.cd-detail__gc-empty,
.cd-detail__gc-failed {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 120px;
  border-radius: 10px;
  background: var(--color-bg);
  font: var(--font-caption);
}

.cd-detail__gc-empty {
  color: var(--color-text-muted);
}

.cd-detail__gc-failed {
  color: var(--severity-3);
}

/* ④ 天气提示行 */
.cd-detail__weather {
  display: flex;
  gap: 10px;
}

.cd-detail__weather-icon {
  flex: 0 0 auto;
  font-size: 24px;
}

.cd-detail__weather-label {
  font: var(--font-caption);
  font-weight: 600;
  color: var(--color-text);
}

.cd-detail__weather-text {
  margin: 4px 0 0;
  font: var(--font-caption);
  color: var(--color-text-muted);
  line-height: 1.6;
}

.cd-detail__weather-text--muted {
  color: var(--color-text-muted);
}

/* ⑤ 操作区 */
.cd-detail__actions {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 4px 12px 24px;
}

.cd-btn-main {
  height: 48px;
  border-radius: var(--radius-button);
  font-size: 16px;
  font-weight: 600;
  background: var(--gradient-brand-135);
  border: none;
}

.cd-btn-sub {
  height: 44px;
  border-radius: var(--radius-button);
  font-size: 15px;
}

/* 反馈弹层 */
.cd-fb {
  padding: 20px 20px calc(20px + env(safe-area-inset-bottom));
}

.cd-fb__title {
  font: var(--font-h2);
  color: var(--color-text);
  text-align: center;
  margin-bottom: 14px;
}

.cd-fb__radios {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 14px;
}

.cd-fb__radio {
  font: var(--font-body);
  color: var(--color-text);
}

.cd-fb__field {
  background: var(--color-bg);
  border-radius: var(--radius-input);
  margin-bottom: 12px;
}

.cd-fb__submit {
  margin-top: 4px;
}
</style>
