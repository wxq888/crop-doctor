import { defineStore } from 'pinia'

import * as feedbackApi from '@/api/feedback'
import * as warningApi from '@/api/warning'

/**
 * 角标状态：「我的」Tab 与功能列表上的未读角标。
 * - feedbackUnread：管理员回复且本人未读的工单消息数（GET /feedback/unread-count）
 * - warningUnread：未读预警数（GET /warning/alerts/unread-count）
 */
export const useBadgeStore = defineStore('badge', {
  state: () => ({
    /** 反馈新回复数 */
    feedbackUnread: 0,
    /** 预警未读数 */
    warningUnread: 0,
  }),

  getters: {
    /** 两类未读总数（TabBar「我的」红点用） */
    total: (state) => state.feedbackUnread + state.warningUnread,
    /** 是否有任何未读 */
    hasUnread: (state) => state.total > 0,
  },

  actions: {
    /** 并行刷新两类未读数；单边失败不影响另一边（错误已由拦截器统一提示） */
    async refresh() {
      try {
        const res = await feedbackApi.getFeedbackUnreadCount()
        this.feedbackUnread = (res && res.count) || 0
      } catch (e) {
        /* 保持原值，不崩 */
      }
      try {
        const res = await warningApi.getAlertUnreadCount()
        this.warningUnread = (res && res.count) || 0
      } catch (e) {
        /* 保持原值，不崩 */
      }
    },

    /** 登出时清零 */
    reset() {
      this.feedbackUnread = 0
      this.warningUnread = 0
    },
  },
})
