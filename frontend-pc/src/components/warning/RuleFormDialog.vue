<script setup>
/**
 * 病害-气象规则表单对话框（ui-design.md §4.3 预警中心）。
 * 字段：病害 / 作物 / 温度区间 / 湿度区间 / 降雨条件 / 风险等级 / 防治建议 / 启用开关。
 * 校验通过后 emit('submit', payload)，由父组件调用 API。
 */
import { reactive, ref, watch } from 'vue'

const props = defineProps({
  /** 显隐（v-model） */
  modelValue: { type: Boolean, default: false },
  /** 编辑目标；null 表示新建 */
  rule: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue', 'submit'])

const formRef = ref(null)

const form = reactive({
  disease: '',
  crop: '',
  temp_min: null,
  temp_max: null,
  humidity_min: null,
  humidity_max: null,
  rain_condition: 'any',
  risk_level: 'mid',
  advice: '',
  enabled: true,
})

const rules = {
  disease: [{ required: true, message: '请输入病害标识（如 tomato_late_blight）', trigger: 'blur' }],
  risk_level: [{ required: true, message: '请选择风险等级', trigger: 'change' }],
}

/** 对话框打开时：编辑回填 / 新建重置 */
watch(
  () => props.modelValue,
  (visible) => {
    if (!visible) return
    if (props.rule) {
      Object.assign(form, {
        disease: props.rule.disease || '',
        crop: props.rule.crop || '',
        temp_min: props.rule.temp_min ?? null,
        temp_max: props.rule.temp_max ?? null,
        humidity_min: props.rule.humidity_min ?? null,
        humidity_max: props.rule.humidity_max ?? null,
        rain_condition: props.rule.rain_condition || 'any',
        risk_level: props.rule.risk_level || 'mid',
        advice: props.rule.advice || '',
        enabled: props.rule.enabled === undefined ? true : !!props.rule.enabled,
      })
    } else {
      Object.assign(form, {
        disease: '',
        crop: '',
        temp_min: null,
        temp_max: null,
        humidity_min: null,
        humidity_max: null,
        rain_condition: 'any',
        risk_level: 'mid',
        advice: '',
        enabled: true,
      })
    }
  },
)

/** 提交：校验后抛给父组件 */
async function submit() {
  if (formRef.value) {
    try {
      await formRef.value.validate()
    } catch (e) {
      return
    }
  }
  emit('submit', { ...form })
}

function close() {
  emit('update:modelValue', false)
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="rule ? '编辑预警规则' : '新建预警规则'"
    width="620px"
    @update:model-value="close"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="92px" size="default">
      <el-form-item label="病害标识" prop="disease">
        <el-input v-model="form.disease" placeholder="如 tomato_late_blight（后端类名）" />
      </el-form-item>
      <el-form-item label="作物">
        <el-input v-model="form.crop" placeholder="选填，如 tomato" />
      </el-form-item>

      <el-form-item label="温度区间">
        <div class="rule-range">
          <el-input-number v-model="form.temp_min" :controls="false" placeholder="最低 ℃" />
          <span class="rule-range__sep">~</span>
          <el-input-number v-model="form.temp_max" :controls="false" placeholder="最高 ℃" />
          <span class="rule-range__unit">℃（留空表示不约束）</span>
        </div>
      </el-form-item>

      <el-form-item label="湿度区间">
        <div class="rule-range">
          <el-input-number v-model="form.humidity_min" :controls="false" placeholder="最低 %" />
          <span class="rule-range__sep">~</span>
          <el-input-number v-model="form.humidity_max" :controls="false" placeholder="最高 %" />
          <span class="rule-range__unit">%（留空表示不约束）</span>
        </div>
      </el-form-item>

      <el-form-item label="降雨条件">
        <el-radio-group v-model="form.rain_condition">
          <el-radio value="any">不限</el-radio>
          <el-radio value="rain">需降雨</el-radio>
          <el-radio value="no_rain">需无雨</el-radio>
        </el-radio-group>
      </el-form-item>

      <el-form-item label="风险等级" prop="risk_level">
        <el-radio-group v-model="form.risk_level">
          <el-radio value="high">高风险</el-radio>
          <el-radio value="mid">中风险</el-radio>
          <el-radio value="low">低风险</el-radio>
        </el-radio-group>
      </el-form-item>

      <el-form-item label="防治建议">
        <el-input v-model="form.advice" type="textarea" :rows="3" placeholder="命中该规则时推送给农户的防治建议" />
      </el-form-item>

      <el-form-item label="启用">
        <el-switch v-model="form.enabled" />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.rule-range {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}
.rule-range__sep {
  color: var(--pc-text-muted);
}
.rule-range__unit {
  font-size: 12px;
  color: var(--pc-text-muted);
}
.rule-range :deep(.el-input-number) {
  width: 120px;
}
</style>
