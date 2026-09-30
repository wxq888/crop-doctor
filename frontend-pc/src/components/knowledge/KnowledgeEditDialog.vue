<script setup>
/**
 * 知识库文档编辑 / 新建对话框（ui-design.md §4.3 知识库管理）。
 * 支持：手填 JSON 字段，或上传 .md 文件（解析首行 H1 作标题）。
 * 提交时：有文件 → FormData；否则 → JSON 对象。由父组件调用 API。
 */
import { ref, reactive, watch } from 'vue'
import { ElMessage } from 'element-plus'

const props = defineProps({
  /** 显隐（v-model） */
  modelValue: { type: Boolean, default: false },
  /** 编辑目标；null 表示新建 */
  doc: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue', 'submit'])

const formRef = ref(null)
const fileRef = ref(null) // el-upload 组件实例
const mdFile = ref(null)

const form = reactive({
  title: '',
  crop: '',
  disease: '',
  content_md: '',
})

const rules = {
  title: [{ required: true, message: '请输入文档标题', trigger: 'blur' }],
  content_md: [{ required: true, message: '请输入正文（Markdown）', trigger: 'blur' }],
}

watch(
  () => props.modelValue,
  (visible) => {
    if (!visible) return
    mdFile.value = null
    if (fileRef.value) fileRef.value.clearFiles()
    if (props.doc) {
      Object.assign(form, {
        title: props.doc.title || '',
        crop: props.doc.crop || '',
        disease: props.doc.disease || '',
        content_md: props.doc.content_md || '',
      })
    } else {
      Object.assign(form, { title: '', crop: '', disease: '', content_md: '' })
    }
  },
)

/** 选择 .md 文件（不自动上传，仅暂存并预览） */
function onFileChange(file) {
  mdFile.value = file.raw || file
  // 尝试读取正文，提升编辑体验（失败不阻断）
  const reader = new FileReader()
  reader.onload = () => {
    const text = String(reader.result || '')
    form.content_md = text
    const firstLine = text.split('\n').find((l) => l.trim().startsWith('# '))
    if (firstLine && !form.title) {
      form.title = firstLine.replace(/^#\s*/, '').trim()
    }
  }
  reader.onerror = () => {
    ElMessage.warning('文件读取失败，请手动填写正文')
  }
  reader.readAsText(mdFile.value)
}

/** 提交 */
async function submit() {
  if (formRef.value) {
    try {
      await formRef.value.validate()
    } catch (e) {
      return
    }
  }
  if (mdFile.value) {
    const fd = new FormData()
    fd.append('file', mdFile.value)
    if (form.crop) fd.append('crop', form.crop)
    if (form.disease) fd.append('disease', form.disease)
    emit('submit', fd)
  } else {
    emit('submit', {
      title: form.title,
      crop: form.crop,
      disease: form.disease,
      content_md: form.content_md,
    })
  }
}

function close() {
  emit('update:modelValue', false)
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="doc ? '编辑知识文档' : '新建知识文档'"
    width="720px"
    @update:model-value="close"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="80px">
      <el-form-item v-if="!doc" label="上传文件">
        <el-upload
          ref="fileRef"
          :auto-upload="false"
          :limit="1"
          accept=".md,.markdown,.txt"
          :on-change="onFileChange"
        >
          <el-button plain>选择 .md 文件</el-button>
          <template #tip>
            <div class="kb-tip">上传后自动解析首行 H1 作为标题；也可直接在下方手填。</div>
          </template>
        </el-upload>
      </el-form-item>

      <el-form-item label="标题" prop="title">
        <el-input v-model="form.title" placeholder="文档标题" />
      </el-form-item>
      <div class="kb-row">
        <el-form-item label="作物">
          <el-input v-model="form.crop" placeholder="如 tomato（选填）" />
        </el-form-item>
        <el-form-item label="病害">
          <el-input v-model="form.disease" placeholder="如 late_blight（选填）" />
        </el-form-item>
      </div>
      <el-form-item label="正文" prop="content_md">
        <el-input
          v-model="form.content_md"
          type="textarea"
          :rows="12"
          placeholder="Markdown 正文（支持 # 标题 / 列表 / 表格）"
        />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" @click="submit">保存并进入向量化队列</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.kb-tip {
  font-size: 12px;
  color: var(--pc-text-muted);
  margin-top: 4px;
}
.kb-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
</style>
