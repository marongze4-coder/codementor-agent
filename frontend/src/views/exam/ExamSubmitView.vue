<template>
  <div class="exam-submit">
    <el-card>
      <template #header>
        <span>📝 综合作业</span>
      </template>

      <el-form :model="form" label-width="100px" style="max-width: 560px">
        <el-form-item label="选择作业">
          <el-select v-model="form.examId" placeholder="请选择教师发布的综合作业" style="width: 100%">
            <el-option
              v-for="exam in exams"
              :key="exam.id"
              :label="`${exam.title}（${exam.full_score}分）`"
              :value="exam.id"
            />
          </el-select>
        </el-form-item>
        <el-alert
          v-if="selectedExam"
          :title="`${selectedExam.question_count} 题：客观题 ${selectedExam.objective_count}、简答题 ${selectedExam.subjective_count}、代码题 ${selectedExam.code_count}`"
          :description="selectedExam.description"
          type="info"
          :closable="false"
          style="margin-bottom: 18px"
        />
        <el-form-item label="答题文件">
          <el-upload
            ref="uploadRef"
            :auto-upload="false"
            :limit="1"
            accept=".docx"
            :on-change="handleFileChange"
            :on-remove="() => (form.file = null)"
          >
            <el-button :icon="Upload">选择文件</el-button>
            <template #tip>
              <div class="upload-tip">仅支持 .docx，按题号作答；代码题请放在 ``` 代码块中，最大 20MB</div>
            </template>
          </el-upload>
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            :loading="loading"
            :disabled="!form.examId || !form.file"
            @click="handleSubmit"
          >
            提交批改
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 历史提交记录 -->
    <el-card style="margin-top: 16px">
      <template #header>
        <span>历史提交</span>
      </template>
      <el-empty v-if="!recentSubmissions.length" description="暂无提交记录" />
      <el-table v-else :data="recentSubmissions" size="small">
        <el-table-column prop="exam_title" label="综合作业" />
        <el-table-column prop="submitted_at" label="提交时间" width="180" />
        <el-table-column label="状态" width="140">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button
              text
              type="primary"
              size="small"
              @click="router.push(`/mixed-assignments/${row.submission_id}`)"
            >
              查看结果
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type UploadFile } from 'element-plus'
import { Upload } from '@element-plus/icons-vue'
import { examApi, type AvailableExam, type MySubmissionItem } from '@/api/exam'

const router = useRouter()
const loading = ref(false)
const form = reactive({ examId: '', file: null as File | null })
const exams = ref<AvailableExam[]>([])
const recentSubmissions = ref<MySubmissionItem[]>([])
const selectedExam = computed(() => exams.value.find(item => item.id === form.examId))

async function fetchSubmissions() {
  try {
    const { data } = await examApi.listMySubmissions()
    recentSubmissions.value = data.items
  } catch {
    // 忽略
  }
}

async function fetchExams() {
  exams.value = (await examApi.available()).data
  if (!form.examId && exams.value.length === 1) form.examId = exams.value[0].id
}

function handleFileChange(file: UploadFile) {
  form.file = file.raw ?? null
}

function statusType(status: string) {
  if (status === 'published') return 'success'
  if (status === 'pending_review') return 'warning'
  if (status === 'submitted') return 'danger'
  return 'info'
}

function statusLabel(status: string) {
  if (status === 'published') return '已发布'
  if (status === 'pending_review') return '等待教师确认'
  if (status === 'ai_processing') return '三轨批改中'
  if (status === 'submitted') return '处理失败，请重新提交'
  return status
}

async function handleSubmit() {
  if (!form.examId || !form.file) return
  loading.value = true
  try {
    await examApi.submit(form.examId, form.file)
    ElMessage.success('提交成功，客观题、简答题和代码题正在并行批改...')
    form.file = null
    await fetchSubmissions()
  } catch {
    // 错误已由 client 拦截器处理
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await Promise.all([fetchExams(), fetchSubmissions()])
})
</script>

<style scoped>
.exam-submit { max-width: 800px; }
.upload-tip { font-size: 12px; color: #8c8c8c; margin-top: 4px; }
</style>
