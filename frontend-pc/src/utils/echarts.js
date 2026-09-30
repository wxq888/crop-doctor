/* ==========================================================================
   ECharts 按需注册 + 主题色板（暗 / 亮）
   仅注册用到的图表与组件，控制包体（见 impl-pc-admin-v1 §7.2）。
   ========================================================================== */
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  CanvasRenderer,
])

/** 品牌 / 语义色（与 tokens.css 一致） */
export const CHART_COLORS = {
  primary: '#2BA471',
  primaryDark: '#1E7A54',
  warning: '#F5A623',
  danger: '#E5534B',
  neutral: '#6B7B71',
}

/**
 * 返回与当前主题匹配的图表配色（文本 / 轴线 / 分割线 / 提示框）。
 * @param {'dark'|'light'} mode
 */
export function getChartTheme(mode) {
  if (mode === 'light') {
    return {
      text: '#1F2B24',
      muted: '#6B7B71',
      axisLine: '#E3E8EB',
      splitLine: '#EEF2F4',
      tooltipBg: '#FFFFFF',
      tooltipBorder: '#E3E8EB',
      tooltipText: '#1F2B24',
      palette: [CHART_COLORS.primary, CHART_COLORS.warning, CHART_COLORS.danger, '#4C9BF5', '#9B7BF0'],
    }
  }
  return {
    text: '#E4E9EE',
    muted: '#7C8A96',
    axisLine: '#26313C',
    splitLine: '#1F2933',
    tooltipBg: '#1A222B',
    tooltipBorder: '#33414F',
    tooltipText: '#E4E9EE',
    palette: [CHART_COLORS.primary, CHART_COLORS.warning, CHART_COLORS.danger, '#4C9BF5', '#9B7BF0'],
  }
}

export default echarts
