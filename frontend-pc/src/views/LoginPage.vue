<script setup>
/**
 * PC 管理员登录页（严格照 ui-design.md §4.2）。
 * 左：品牌叙事区（深绿渐变 + logo + 大标题 + 功能胶囊）
 * 右：表单卡片（深面板 + 聚焦边框变品牌绿）
 * 底部：安全提示。管理员无注册入口。
 */
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const formRef = ref(null)
const loading = ref(false)

const form = reactive({
  username: '',
  password: '',
  remember: true,
})

const rules = {
  username: [{ required: true, message: '请输入管理员账号', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

/** 功能胶囊标签 */
const features = [
  { icon: '📊', text: '实时监控' },
  { icon: '⚠️', text: '预警中心' },
  { icon: '💬', text: '工单答疑' },
]

/** 提交登录 */
async function handleLogin() {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch (e) {
    return
  }
  loading.value = true
  try {
    const data = await userStore.login(form.username.trim(), form.password)
    const user = data.user || {}
    if (user.role !== 'admin') {
      // 非管理员：清除登录态并拒绝
      userStore.logout()
      ElMessage.error('该账号非管理员，无权访问管理端')
      return
    }
    ElMessage.success('登录成功，欢迎回来')
    const redirect = route.query.redirect && String(route.query.redirect)
    await router.replace(redirect && redirect !== '/login' ? redirect : { name: 'dashboard' })
  } catch (e) {
    // 错误提示已在 axios 拦截器统一处理
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  // 由守卫带过来的「非管理员」场景：给出明确提示
  if (route.query.denied) {
    ElMessage.warning('当前账号非管理员，已退出登录')
  }
})
</script>

<template>
  <div class="login-page">
    <!-- 左侧品牌叙事区 -->
    <section class="login-brand">
      <div class="login-brand__glow login-brand__glow--1" />
      <div class="login-brand__glow login-brand__glow--2" />

      <div class="login-brand__top">
        <span class="login-brand__logo">🌱</span>
        <div class="login-brand__brand">
          <div class="login-brand__brand-cn">作物医生</div>
          <div class="login-brand__brand-en">CROPDOCTOR ADMIN</div>
        </div>
      </div>

      <div class="login-brand__body">
        <h1 class="login-brand__title">
          农作物病害
          <span class="login-brand__title-em">智能检测与问诊</span>
          管理平台
        </h1>
        <p class="login-brand__subtitle">
          基于 YOLO11s 病害识别 · ResNet50 严重度分级 · RAG 智能问诊 · 天气驱动风险预警，
          为管理员提供全链路数据监控与运营能力。
        </p>
        <div class="login-brand__features">
          <span v-for="f in features" :key="f.text" class="login-brand__pill">
            <span class="login-brand__pill-icon">{{ f.icon }}</span>{{ f.text }}
          </span>
        </div>
      </div>

      <div class="login-brand__foot">CropDoctor · 智慧农业病害防治平台</div>
    </section>

    <!-- 右侧表单区 -->
    <section class="login-form-wrap">
      <div class="login-card">
        <h2 class="login-card__title">管理员登录</h2>
        <p class="login-card__subtitle">请使用管理员账号进入控制台</p>

        <el-form
          ref="formRef"
          class="login-card__form"
          :model="form"
          :rules="rules"
          label-position="top"
          size="large"
          @keyup.enter="handleLogin"
        >
          <el-form-item label="账号" prop="username">
            <el-input v-model="form.username" placeholder="请输入管理员账号" autocomplete="username" />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="请输入密码"
              show-password
              autocomplete="current-password"
            />
          </el-form-item>

          <div class="login-card__row">
            <el-checkbox v-model="form.remember">记住我</el-checkbox>
            <span class="login-card__forgot">忘记密码？请联系系统管理员</span>
          </div>

          <el-button
            class="login-card__submit"
            type="primary"
            size="large"
            :loading="loading"
            @click="handleLogin"
          >
            登 录
          </el-button>
        </el-form>

      </div>

      <div class="login-foot">仅限授权管理员访问 · 操作将被记录</div>
    </section>
  </div>
</template>

<style scoped>
.login-page {
  display: flex;
  height: 100vh;
  width: 100vw;
  overflow: hidden;
  background-color: #0f1419;
}

/* ---------- 左侧品牌区 ---------- */
.login-brand {
  position: relative;
  flex: 1.15;
  min-width: 0;
  padding: 48px 56px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  overflow: hidden;
  background: linear-gradient(150deg, #123326 0%, #0f1419 100%);
}
.login-brand__glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(2px);
  pointer-events: none;
}
.login-brand__glow--1 {
  width: 520px;
  height: 520px;
  right: -160px;
  top: -180px;
  background: radial-gradient(circle, rgba(43, 164, 113, 0.28) 0%, rgba(43, 164, 113, 0) 68%);
}
.login-brand__glow--2 {
  width: 380px;
  height: 380px;
  left: -120px;
  bottom: -140px;
  background: radial-gradient(circle, rgba(43, 164, 113, 0.18) 0%, rgba(43, 164, 113, 0) 68%);
}
.login-brand__top {
  display: flex;
  align-items: center;
  gap: 12px;
  position: relative;
  z-index: 1;
}
.login-brand__logo {
  width: 44px;
  height: 44px;
  border-radius: 11px;
  background: linear-gradient(135deg, #2ba471 0%, #1e7a54 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  box-shadow: 0 6px 16px rgba(43, 164, 113, 0.32);
}
.login-brand__brand-cn {
  color: #e4e9ee;
  font-size: 17px;
  font-weight: 700;
  letter-spacing: 1px;
}
.login-brand__brand-en {
  color: #6b7b71;
  font-size: 11px;
  letter-spacing: 1.5px;
}
.login-brand__body {
  position: relative;
  z-index: 1;
  max-width: 520px;
}
.login-brand__title {
  margin: 0;
  font-size: 40px;
  line-height: 1.28;
  font-weight: 700;
  color: #e4e9ee;
  letter-spacing: 1px;
}
.login-brand__title-em {
  color: #2ba471;
}
.login-brand__subtitle {
  margin: 20px 0 0;
  font-size: 14px;
  line-height: 1.9;
  color: #7c8a96;
}
.login-brand__features {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 28px;
}
.login-brand__pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 9px 18px;
  border-radius: 22px;
  font-size: 13px;
  color: #c7d0d8;
  background: rgba(43, 164, 113, 0.1);
  border: 1px solid rgba(43, 164, 113, 0.28);
}
.login-brand__pill-icon {
  font-size: 14px;
}
.login-brand__foot {
  position: relative;
  z-index: 1;
  color: #4d5860;
  font-size: 12px;
  letter-spacing: 0.5px;
}

/* ---------- 右侧表单区 ---------- */
.login-form-wrap {
  flex: 1;
  min-width: 420px;
  background: #141c24;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  position: relative;
}
.login-card {
  width: 100%;
  max-width: 372px;
}
.login-card__title {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  color: #e4e9ee;
}
.login-card__subtitle {
  margin: 8px 0 28px;
  font-size: 13px;
  color: #7c8a96;
}
.login-card__form :deep(.el-form-item__label) {
  color: #aab6c0;
  font-size: 13px;
}
.login-card__form :deep(.el-input__wrapper) {
  background-color: #0f1419;
  box-shadow: 0 0 0 1px #26313c inset;
  border-radius: 6px;
}
.login-card__form :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px #2ba471 inset;
}
.login-card__form :deep(.el-input__inner) {
  color: #e4e9ee;
}
.login-card__form :deep(.el-checkbox__label) {
  color: #aab6c0;
  font-size: 13px;
}
.login-card__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
}
.login-card__forgot {
  font-size: 12px;
  color: #7c8a96;
}
.login-card__submit {
  width: 100%;
  height: 44px;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 4px;
  border: none;
  background: linear-gradient(135deg, #2ba471 0%, #1e7a54 100%);
  box-shadow: 0 6px 16px rgba(43, 164, 113, 0.32);
}
.login-foot {
  position: absolute;
  bottom: 22px;
  font-size: 12px;
  color: #4d5860;
  letter-spacing: 0.5px;
}
</style>
