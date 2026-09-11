<template>
  <div class="page">
    <el-card>
      <template #header><b>🔍 代码质量审查</b></template>
      <el-alert title="支持 Python、Java、JavaScript、TypeScript、C/C++ 和 Go；单文件不超过 512 KB。" type="info" :closable="false" />
      <el-upload class="upload" drag :auto-upload="false" :limit="1" :on-change="onFile" :on-remove="() => selected = undefined">
        <div class="upload-icon">⌨️</div>
        <div>将源代码拖到这里，或点击选择文件</div>
      </el-upload>
      <el-button type="primary" :loading="submitting" :disabled="!selected" @click="submit">开始六维审查</el-button>
    </el-card>

    <el-card class="history">
      <template #header><b>审查记录</b></template>
      <el-table :data="reviews" v-loading="loading" empty-text="暂无审查记录">
        <el-table-column prop="original_filename" label="文件" min-width="180" />
        <el-table-column prop="language" label="语言" width="110" />
        <el-table-column label="得分" width="90"><template #default="{ row }">{{ row.overall_score ?? '—' }}</template></el-table-column>
        <el-table-column label="状态" width="110"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="150"><template #default="{ row }">
          <el-button link type="primary" @click="router.push(`/code-review/${row.id}`)">查看</el-button>
          <el-button link type="danger" @click="remove(row.id)">删除</el-button>
        </template></el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type UploadFile } from 'element-plus'
import { codeReviewApi, type CodeReview } from '@/api/codeReview'

const router = useRouter()
const selected = ref<File>()
const reviews = ref<CodeReview[]>([])
const loading = ref(false)
const submitting = ref(false)
const onFile = (file: UploadFile) => { selected.value = file.raw }
const statusText = (v: string) => ({ processing: '审查中', done: '已完成', failed: '失败' }[v] ?? v)
const statusType = (v: string) => v === 'done' ? 'success' : v === 'failed' ? 'danger' : 'warning'

async function load() {
  loading.value = true
  try { reviews.value = (await codeReviewApi.list()).data } finally { loading.value = false }
}
async function submit() {
  if (!selected.value) return
  submitting.value = true
  try {
    const { data } = await codeReviewApi.submit(selected.value)
    ElMessage.success('代码已提交，正在分析')
    router.push(`/code-review/${data.review_id}`)
  } finally { submitting.value = false }
}
async function remove(id: string) { await codeReviewApi.remove(id); ElMessage.success('记录已删除'); await load() }
onMounted(load)
</script>

<style scoped>
.page{max-width:960px}.upload{margin:18px 0}.upload-icon{font-size:38px}.history{margin-top:18px}
</style>
