<template>
  <div class="cd-login">
    <!-- Hero 区：品牌绿渐变 + 装饰光斑 + logo + 品牌名 + slogan -->
    <div class="cd-hero">
      <span class="cd-hero__blob cd-hero__blob--1"></span>
      <span class="cd-hero__blob cd-hero__blob--2"></span>
      <span class="cd-hero__leaf cd-hero__leaf--1">🍃</span>
      <span class="cd-hero__leaf cd-hero__leaf--2">🌿</span>

      <div class="cd-hero__logo">🌱</div>
      <div class="cd-hero__name">作物医生</div>
      <div class="cd-hero__slogan">拍照识病害 · AI 帮你看田</div>
    </div>

    <!-- 上浮白卡 -->
    <div class="cd-card">
      <!-- Tab 切换：登录 / 注册 -->
      <div class="cd-tabs">
        <div
          class="cd-tabs__item"
          :class="{ 'cd-tabs__item--active': mode === 'login' }"
          @click="switchMode('login')"
        >
          登录
        </div>
        <div
          class="cd-tabs__item"
          :class="{ 'cd-tabs__item--active': mode === 'register' }"
          @click="switchMode('register')"
        >
          注册
        </div>
      </div>

      <!-- 表单 -->
      <div class="cd-form">
        <van-field
          v-model="form.username"
          class="cd-field"
          :border="false"
          clearable
          autocomplete="username"
          placeholder="请输入用户名"
        >
          <template #left-icon><van-icon name="user-o" /></template>
        </van-field>

        <van-field
          v-model="form.password"
          class="cd-field"
          :border="false"
          :type="showPwd ? 'text' : 'password'"
          autocomplete="current-password"
          placeholder="请输入密码"
          @keyup.enter="submit"
        >
          <template #left-icon><van-icon name="lock" /></template>
          <template #right-icon>
            <van-icon
              :name="showPwd ? 'eye-o' : 'closed-eye'"
              class="cd-field__eye"
              @click="showPwd = !showPwd"
            />
          </template>
        </van-field>

        <!-- 注册：确认密码 -->
        <van-field
          v-if="mode === 'register'"
          v-model="form.confirm"
          class="cd-field"
          :border="false"
          :type="showPwd ? 'text' : 'password'"
          placeholder="请再次输入密码"
          @keyup.enter="submit"
        >
          <template #left-icon><van-icon name="lock" /></template>
        </van-field>

        <!-- 登录：忘记密码 -->
        <div v-if="mode === 'login'" class="cd-form__aux">
          <span class="cd-form__link" @click="onForgot">忘记密码？</span>
        </div>

        <van-button
          class="cd-btn"
          block
          :loading="loading"
          loading-text="请稍候…"
          @click="submit"
        >
          {{ mode === 'login' ? '登 录' : '注 册' }}
        </van-button>
      </div>

      <!-- 底部协议 -->
      <p class="cd-protocol">
        登录即代表同意
        <span>《用户协议》</span>
        与
        <span>《隐私政策》</span>
      </p>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast } from 'vant'

import { useUserStore } from '@/stores/user'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

/** 当前 Tab：login | register */
const mode = ref('login')
/** 密码是否明文显示 */
const showPwd = ref(false)
/** 提交中（防重复提交） */
const loading = ref(false)

const form = reactive({
  username: '',
  password: '',
  confirm: '',
})

function switchMode(next) {
  if (mode.value === next) return
  mode.value = next
  form.password = ''
  form.confirm = ''
}

/** 校验表单，返回错误文案或空串 */
function validate() {
  if (!form.username.trim()) return '请输入用户名'
  if (form.username.trim().length < 3) return '用户名至少 3 个字符'
  if (!form.password) return '请输入密码'
  if (form.password.length < 6) return '密码至少 6 位'
  if (mode.value === 'register' && form.password !== form.confirm) return '两次输入的密码不一致'
  return ''
}

async function submit() {
  if (loading.value) return
  const err = validate()
  if (err) {
    showToast(err)
    return
  }

  loading.value = true
  try {
    if (mode.value === 'login') {
      await userStore.login(form.username.trim(), form.password)
      showToast('登录成功')
      const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/chat'
      router.replace(redirect)
    } else {
      await userStore.register({
        username: form.username.trim(),
        password: form.password,
        nickname: form.username.trim(),
      })
      showToast('注册成功，请登录')
      mode.value = 'login'
      form.password = ''
      form.confirm = ''
    }
  } catch (e) {
    // 具体错误文案已由 axios 拦截器统一 toast（如「用户名已存在」/「用户名或密码错误」）
  } finally {
    loading.value = false
  }
}

function onForgot() {
  showToast('请联系管理员重置密码')
}
</script>

<style scoped>
.cd-login {
  position: relative;
  height: 100%;
  overflow-y: auto;
  background: var(--color-bg);
  display: flex;
  flex-direction: column;
}

/* ---------- Hero 区 ---------- */
.cd-hero {
  position: relative;
  flex: 0 0 auto;
  height: 240px;
  padding: 48px 24px 42px;
  overflow: hidden;
  background: var(--gradient-brand);
  color: #fff;
}

.cd-hero__blob {
  position: absolute;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.12);
}

.cd-hero__blob--1 {
  width: 160px;
  height: 160px;
  top: -50px;
  right: -40px;
}

.cd-hero__blob--2 {
  width: 90px;
  height: 90px;
  bottom: 10px;
  left: -30px;
  background: rgba(255, 255, 255, 0.08);
}

.cd-hero__leaf {
  position: absolute;
  opacity: 0.55;
  font-size: 30px;
}

.cd-hero__leaf--1 {
  top: 26px;
  right: 74px;
  transform: rotate(-18deg);
}

.cd-hero__leaf--2 {
  bottom: 28px;
  right: 28px;
  font-size: 38px;
  transform: rotate(12deg);
}

.cd-hero__logo {
  width: 58px;
  height: 58px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 32px;
  margin-bottom: 14px;
}

.cd-hero__name {
  font: 600 26px/1.3 -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif;
  letter-spacing: 2px;
}

.cd-hero__slogan {
  margin-top: 8px;
  font: var(--font-caption);
  opacity: 0.9;
  letter-spacing: 1px;
}

/* ---------- 上浮白卡 ---------- */
.cd-card {
  position: relative;
  flex: 1 1 auto;
  margin-top: -26px;
  padding: 22px 22px 28px;
  background: var(--color-surface);
  border-radius: var(--radius-card-top) var(--radius-card-top) 0 0;
  box-shadow: 0 -2px 16px rgba(31, 43, 36, 0.06);
}

/* Tab 切换 */
.cd-tabs {
  display: flex;
  gap: 28px;
  padding: 0 4px;
  margin-bottom: 20px;
}

.cd-tabs__item {
  position: relative;
  padding: 6px 2px 10px;
  font: var(--font-h2);
  color: var(--color-text-muted);
}

.cd-tabs__item--active {
  color: var(--color-text);
  font-weight: 600;
}

.cd-tabs__item--active::after {
  content: '';
  position: absolute;
  left: 50%;
  bottom: 0;
  transform: translateX(-50%);
  width: 26px;
  height: 3px;
  border-radius: 3px;
  background: var(--color-primary);
}

/* 表单 */
.cd-form {
  display: flex;
  flex-direction: column;
}

.cd-field {
  background: var(--color-bg);
  border-radius: var(--radius-input);
  padding: 10px 12px;
  margin-bottom: 14px;
}

.cd-field :deep(.van-field__left-icon) {
  color: var(--color-text-muted);
  font-size: 18px;
  margin-right: 8px;
}

.cd-field :deep(.van-field__control) {
  font: var(--font-body);
  color: var(--color-text);
}

.cd-field__eye {
  color: var(--color-text-muted);
  font-size: 18px;
}

.cd-form__aux {
  display: flex;
  justify-content: flex-end;
  margin: -4px 2px 18px;
}

.cd-form__link {
  font: var(--font-caption);
  color: var(--color-primary);
}

/* 主按钮：品牌绿渐变胶囊 14px + 柔和投影 */
.cd-btn {
  height: 48px;
  border: none !important;
  border-radius: 14px !important;
  background: var(--gradient-brand-135) !important;
  color: #fff !important;
  font: 600 16px/1 -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif !important;
  letter-spacing: 2px;
  box-shadow: var(--shadow-primary);
}

/* 底部协议 */
.cd-protocol {
  margin: 20px 0 0;
  text-align: center;
  font: var(--font-mini);
  color: var(--color-text-muted);
  line-height: 1.7;
}

.cd-protocol span {
  color: var(--color-primary);
}
</style>
