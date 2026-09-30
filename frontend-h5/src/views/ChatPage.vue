<template>
  <div class="cd-chat">
    <!-- 顶部栏 -->
    <div class="cd-nav">
      <div class="cd-nav__title">智能问诊</div>
      <div class="cd-nav__actions">
        <van-icon name="plus" @click="onNewSession" />
        <van-icon name="bars" @click="showSessions = true" />
      </div>
    </div>

    <!-- 检测上下文卡片（从检测详情进入时展示） -->
    <DetectionContextCard
      v-if="chatStore.detectionContext"
      :context="chatStore.detectionContext"
      @close="chatStore.clearDetectionContext()"
    />

    <!-- 缺资料提示：该作物在知识库中无任何文档（琥珀色，语义=资料缺失，区别于降级横幅） -->
    <div v-if="chatStore.kbScopeMiss" class="cd-scope-miss">
      <van-icon name="warning-o" />
      <span>知识库暂无【{{ scopeCropLabel }}】的病害资料，已为你保留本次检测结论</span>
    </div>

    <!-- 降级提示（知识库离线 / 未配大模型） -->
    <div v-if="chatStore.degraded" class="cd-degraded">
      <van-icon name="info-o" />
      <span>当前为知识库离线模式 · 知识库资料尚在补充，回答基于已有资料，仍可继续对话</span>
    </div>

    <!-- 消息列表 -->
    <MessageList
      :messages="chatStore.messages"
      :quick-questions="chatStore.quickQuestions"
      :streaming="chatStore.streaming"
      @quick="onSend"
    />

    <!-- 底部输入栏 -->
    <ChatInputBar :streaming="chatStore.streaming" @send="onSend" @stop="chatStore.stop()" />

    <!-- 会话列表抽屉 -->
    <van-popup v-model:show="showSessions" position="right" :style="{ width: '78%', height: '100%' }">
      <div class="cd-session-panel">
        <div class="cd-session-panel__head">
          <span>会话历史</span>
          <van-icon name="cross" @click="showSessions = false" />
        </div>

        <div v-if="!chatStore.sessions.length" class="cd-session-panel__empty">暂无会话记录</div>

        <div
          v-for="s in chatStore.sessions"
          :key="s.id"
          class="cd-session-item"
          :class="{ 'cd-session-item--active': s.id === chatStore.currentSessionId }"
        >
          <div class="cd-session-item__main" @click="onOpenSession(s.id)">
            <div class="cd-session-item__title">{{ s.title || '未命名会话' }}</div>
            <div class="cd-session-item__time">{{ formatTime(s.updated_at || s.created_at) }}</div>
          </div>
          <van-icon class="cd-session-item__del" name="delete-o" @click="onDeleteSession(s.id)" />
        </div>
      </div>
    </van-popup>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { showConfirmDialog, showToast } from 'vant'

import ChatInputBar from '@/components/chat/ChatInputBar.vue'
import DetectionContextCard from '@/components/chat/DetectionContextCard.vue'
import MessageList from '@/components/chat/MessageList.vue'
import { useChatStore } from '@/stores/chat'

const route = useRoute()
const chatStore = useChatStore()

const showSessions = ref(false)

/** 缺资料提示条中的作物名：无检测上下文时回退为「该作物」 */
const scopeCropLabel = computed(() => chatStore.scopeCropName || '该作物')

onMounted(async () => {
  const rawId = route.query.detection_id
  const detectionId = rawId != null && rawId !== '' ? Number(rawId) : null

  await chatStore.loadSessions()

  if (detectionId && !Number.isNaN(detectionId)) {
    // 从检测详情进入：新建会话 + 注入检测上下文 + 首条概述
    await chatStore.initForDetection(detectionId)
  } else if (chatStore.sessions.length) {
    // 普通进入：打开最近一次会话
    await chatStore.openSession(chatStore.sessions[0].id)
  }
})

/** 发送问题 */
function onSend(question) {
  chatStore.send(question)
}

/** 新建会话（清空当前上下文，进入空态） */
async function onNewSession() {
  chatStore.stop()
  chatStore.currentSessionId = null
  chatStore.messages = []
  chatStore.detectionContext = null
  chatStore.degraded = false
  chatStore.kbScopeMiss = false
  chatStore.pendingDetectionId = null
  showSessions.value = false
}

/** 切换会话 */
async function onOpenSession(id) {
  showSessions.value = false
  if (id === chatStore.currentSessionId) return
  await chatStore.openSession(id)
}

/** 删除会话（二次确认） */
async function onDeleteSession(id) {
  try {
    await showConfirmDialog({ title: '删除会话', message: '删除后该会话及其消息不可恢复，确定删除？' })
  } catch (e) {
    return // 用户取消
  }
  const ok = await chatStore.deleteSession(id)
  if (ok) showToast('已删除')
}

/** 时间格式化：今天显示 HH:mm，否则显示 MM-DD */
function formatTime(raw) {
  if (!raw) return ''
  const d = new Date(raw)
  if (Number.isNaN(d.getTime())) return ''
  const now = new Date()
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  if (sameDay) return `${hh}:${mm}`
  const mo = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${mo}-${dd}`
}
</script>

<style scoped>
.cd-chat {
  display: flex;
  flex-direction: column;
  /* 固定布局页：消息区自滚、body 不滚。
     不用 height:100%（父级 min-height 时百分比不解析会塌），改为视口高度
     减去 TabBar（50px + 安全区，/chat 是一级 Tab 页带底部导航） */
  height: calc(100vh - 50px - env(safe-area-inset-bottom));
  height: calc(100dvh - 50px - env(safe-area-inset-bottom));
  background: var(--color-bg);
}

/* 顶部栏 */
.cd-nav {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  height: 50px;
  padding: 0 14px;
  padding-top: env(safe-area-inset-top);
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
}

.cd-nav__title {
  flex: 1;
  font: var(--font-h2);
  color: var(--color-text);
}

.cd-nav__actions {
  display: flex;
  gap: 18px;
  font-size: 20px;
  color: var(--color-primary);
}

/* 缺资料提示条（琥珀色 #F5A623 系，语义=资料缺失，区别于降级横幅） */
.cd-scope-miss {
  flex: 0 0 auto;
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin: 8px 12px 0;
  padding: 8px 10px;
  border-radius: 10px;
  background: #fff6e6;
  border-left: 3px solid var(--severity-2);
  color: #8a5a00;
  font: var(--font-mini);
  line-height: 1.5;
}

.cd-scope-miss :deep(.van-icon) {
  color: var(--severity-2);
  margin-top: 1px;
  flex: 0 0 auto;
}

/* 降级提示 */
.cd-degraded {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 8px 12px 0;
  padding: 8px 10px;
  border-radius: 10px;
  background: #fff4e0;
  color: #a86a00;
  font: var(--font-mini);
  line-height: 1.5;
}

/* 会话抽屉 */
.cd-session-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--color-surface);
}

.cd-session-panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  font: var(--font-h2);
  color: var(--color-text);
  border-bottom: 1px solid var(--color-border);
}

.cd-session-panel__empty {
  padding: 40px 0;
  text-align: center;
  color: var(--color-text-muted);
  font: var(--font-caption);
}

.cd-session-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border);
}

.cd-session-item--active {
  background: var(--color-primary-soft);
}

.cd-session-item__main {
  flex: 1;
  min-width: 0;
}

.cd-session-item__title {
  font: var(--font-body);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cd-session-item__time {
  margin-top: 2px;
  font: var(--font-mini);
  color: var(--color-text-muted);
}

.cd-session-item__del {
  flex: 0 0 auto;
  font-size: 18px;
  color: var(--color-text-muted);
  padding: 6px;
}
</style>
