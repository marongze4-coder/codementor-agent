<template>
  <div class="page">
    <el-card><template #header><b>🎙️ 开始项目答辩</b></template><el-alert title="答辩题目会结合你的真实作业、测试结果和代码质量问题生成。" type="info" :closable="false" />
      <el-form label-position="top" class="form"><el-form-item label="关联作业提交"><el-select v-model="submissionId" clearable placeholder="选择一次作业提交" @change="reviewId=''" style="width:100%"><el-option v-for="s in submissions" :key="s.id" :label="`${s.assignment_title} · ${s.final_score ?? s.automatic_score ?? '待评分'}分`" :value="s.id" /></el-select></el-form-item><el-form-item label="或关联代码审查"><el-select v-model="reviewId" clearable placeholder="选择一次已完成的代码审查" @change="submissionId=''" style="width:100%"><el-option v-for="r in reviews.filter(x=>x.status==='done')" :key="r.id" :label="`${r.original_filename} · ${r.overall_score ?? '—'}分`" :value="r.id" /></el-select></el-form-item><el-button type="primary" :disabled="!submissionId&&!reviewId" :loading="creating" @click="create">进入答辩</el-button></el-form>
    </el-card>
    <el-card class="history"><template #header><b>历史答辩</b></template><el-table :data="sessions"><el-table-column label="答辩依据"><template #default="{row}">{{ row.assignment_title || row.original_filename || '课程项目' }}</template></el-table-column><el-table-column prop="turn_count" label="轮次" width="80"/><el-table-column label="状态" width="110"><template #default="{row}"><el-tag :type="row.status==='finished'?'success':'warning'">{{ row.status==='finished'?'已结束':'进行中' }}</el-tag></template></el-table-column><el-table-column prop="overall_score" label="得分" width="90"/><el-table-column label="操作" width="100"><template #default="{row}"><el-button link type="primary" @click="router.push(`/defense/${row.id}`)">{{row.status==='finished'?'查看':'继续'}}</el-button></template></el-table-column></el-table></el-card>
  </div>
</template>
<script setup lang="ts">
import { onMounted, ref } from 'vue';import { useRouter } from 'vue-router';import { assignmentApi } from '@/api/assignment';import { codeReviewApi,type CodeReview } from '@/api/codeReview';import { defenseApi,type DefenseSession } from '@/api/defense'
const router=useRouter(),submissionId=ref(''),reviewId=ref(''),creating=ref(false),submissions=ref<any[]>([]),reviews=ref<CodeReview[]>([]),sessions=ref<DefenseSession[]>([])
async function create(){creating.value=true;try{const {data}=await defenseApi.create({submission_id:submissionId.value||undefined,code_review_id:reviewId.value||undefined});router.push(`/defense/${data.session_id}`)}finally{creating.value=false}}
onMounted(async()=>{const [s,r,d]=await Promise.all([assignmentApi.submissions(),codeReviewApi.list(),defenseApi.list()]);submissions.value=s.data;reviews.value=r.data;sessions.value=d.data})
</script>
<style scoped>.page{max-width:900px}.form{margin-top:18px}.history{margin-top:18px}</style>
