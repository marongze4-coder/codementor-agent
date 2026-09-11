<template>
  <div class="page">
    <div class="heading"><div><h2>💻 编程实训</h2><p>选择课程作业，提交 Python 源文件进行自动评测。</p></div><el-select v-model="courseId" clearable placeholder="全部课程" @change="loadAssignments"><el-option v-for="c in courses" :key="c.id" :label="`${c.code} · ${c.name}`" :value="c.id" /></el-select></div>
    <el-row :gutter="16" v-loading="loading">
      <el-col v-for="item in assignments" :key="item.id" :span="12">
        <el-card class="assignment" shadow="hover"><div class="course">{{ item.course_name }} · {{ item.language }}</div><h3>{{ item.title }}</h3><p>{{ item.description }}</p><div class="footer"><span>满分 {{ item.max_score }}</span><el-upload :auto-upload="false" :show-file-list="false" :on-change="onAssignmentFile(item.id)"><el-button type="primary" :loading="submitting === item.id">提交 main.py</el-button></el-upload></div></el-card>
      </el-col>
    </el-row>
    <el-empty v-if="!loading && !assignments.length" description="暂无可提交作业" />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type UploadFile } from 'element-plus'
import { assignmentApi, type Assignment, type Course } from '@/api/assignment'
const router = useRouter()
const courses = ref<Course[]>([]), assignments = ref<Assignment[]>([]), courseId = ref('')
const loading = ref(false), submitting = ref('')
async function loadAssignments(){ loading.value=true; try{ assignments.value=(await assignmentApi.list(courseId.value || undefined)).data }finally{loading.value=false} }
async function submit(id:string,file:UploadFile){
  if(!file.raw)return
  if(!file.name.toLowerCase().endsWith('.py')){ElMessage.warning('当前作业只接受 .py 文件');return}
  submitting.value=id
  try{const {data}=await assignmentApi.submit(id,file.raw);ElMessage.success('提交成功，正在隔离运行测试');router.push(`/assignments/submissions/${data.submission_id}`)}finally{submitting.value=''}
}
const onAssignmentFile = (id: string) => (file: UploadFile) => submit(id, file)
onMounted(async()=>{courses.value=(await assignmentApi.courses()).data;await loadAssignments()})
</script>

<style scoped>
.page{max-width:1050px}.heading{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:18px}.heading h2{margin:0 0 5px}.heading p{margin:0;color:#909399}.assignment{margin-bottom:16px}.assignment h3{margin:8px 0}.assignment p{color:#606266;min-height:48px;white-space:pre-line}.course{font-size:13px;color:#1677ff}.footer{display:flex;justify-content:space-between;align-items:center;color:#909399}
</style>
