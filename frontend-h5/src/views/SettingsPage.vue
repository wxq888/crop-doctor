<template>
  <div class="cd-page cd-settings">
    <PageNav title="设置" />

    <div class="cd-page__body">
      <!-- 修改资料 -->
      <van-cell-group class="cd-settings__group" :border="false">
        <div class="cd-settings__caption">账号资料</div>
        <van-field
          v-model="nickname"
          class="cd-settings__field"
          label="昵称"
          label-width="70px"
          placeholder="请输入昵称"
          maxlength="50"
          clearable
        />
        <van-field
          v-model="username"
          class="cd-settings__field"
          label="用户名"
          label-width="70px"
          disabled
          placeholder="—"
        />
        <div class="cd-settings__actions">
          <van-button round block type="primary" class="cd-settings__btn" :loading="savingProfile" @click="saveProfile">
            保存资料
          </van-button>
        </div>
      </van-cell-group>

      <!-- 修改密码 -->
      <van-cell-group class="cd-settings__group" :border="false">
        <div class="cd-settings__caption">修改密码</div>
        <van-field
          v-model="oldPwd"
          class="cd-settings__field"
          label="原密码"
          label-width="70px"
          type="password"
          placeholder="请输入原密码"
        />
        <van-field
          v-model="newPwd"
          class="cd-settings__field"
          label="新密码"
          label-width="70px"
          type="password"
          placeholder="至少 6 位"
        />
        <van-field
          v-model="confirmPwd"
          class="cd-settings__field"
          label="确认密码"
          label-width="70px"
          type="password"
          placeholder="请再次输入新密码"
        />
        <div class="cd-settings__actions">
          <van-button round block plain type="primary" class="cd-settings__btn" :loading="savingPwd" @click="savePassword">
            修改密码
          </van-button>
        </div>
      </van-cell-group>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { showToast } from 'vant'

import PageNav from '@/components/common/PageNav.vue'
import * as authApi from '@/api/auth'
import { useUserStore } from '@/stores/user'

/**
 * 设置页：修改资料（PUT /auth/profile）+ 修改密码（PUT /auth/password）。
 */
const userStore = useUserStore()

const nickname = ref((userStore.user && userStore.user.nickname) || '')
const username = ref((userStore.user && userStore.user.username) || '')

const savingProfile = ref(false)
const oldPwd = ref('')
const newPwd = ref('')
const confirmPwd = ref('')
const savingPwd = ref(false)

async function saveProfile() {
  const name = nickname.value.trim()
  if (!name) {
    showToast('昵称不能为空')
    return
  }
  savingProfile.value = true
  try {
    await authApi.updateProfile({ nickname: name })
    await userStore.loadProfile()
    showToast('资料已更新')
  } catch (e) {
    /* 拦截器已提示 */
  } finally {
    savingProfile.value = false
  }
}

async function savePassword() {
  if (!oldPwd.value) {
    showToast('请输入原密码')
    return
  }
  if (newPwd.value.length < 6) {
    showToast('新密码至少 6 位')
    return
  }
  if (newPwd.value !== confirmPwd.value) {
    showToast('两次输入的新密码不一致')
    return
  }
  savingPwd.value = true
  try {
    await authApi.changePassword({
      old_password: oldPwd.value,
      new_password: newPwd.value,
    })
    showToast('密码已修改，下次登录请使用新密码')
    oldPwd.value = ''
    newPwd.value = ''
    confirmPwd.value = ''
  } catch (e) {
    /* 拦截器已提示（含 1005 原密码错误） */
  } finally {
    savingPwd.value = false
  }
}
</script>

<style scoped>
.cd-settings {
  display: flex;
  flex-direction: column;
  /* 内容型页面随 body 滚动：min-height + 底部留白（防固定元素遮挡） */
  min-height: 100%;
  padding-bottom: calc(50px + env(safe-area-inset-bottom));
  background: var(--color-bg);
}

.cd-settings__group {
  margin: 12px;
  padding: 4px 0 12px;
  border-radius: var(--radius-card);
  background: var(--color-surface);
  box-shadow: var(--shadow-card);
}

.cd-settings__caption {
  font: var(--font-h2);
  color: var(--color-text);
  padding: 12px 16px 4px;
}

.cd-settings__field {
  background: transparent;
}

.cd-settings__field :deep(.van-field__control) {
  font: var(--font-body);
  color: var(--color-text);
}

.cd-settings__actions {
  padding: 12px 16px 0;
}

.cd-settings__btn {
  height: 44px;
  border-radius: var(--radius-button);
  font-size: 15px;
}
</style>
