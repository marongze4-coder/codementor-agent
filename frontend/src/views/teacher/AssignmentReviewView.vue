<template>
  <div class="page"><h2>✅ 作业成绩确认</h2><el-card><el-table :data="items" v-loading="loading" empty-text="暂无待确认作业"><el-table-column prop="assignment_title" label="作业"/><el-table-column prop="student_name" label="学生" width="130"/><el-table-column prop="automatic_score" label="自动评分" width="110"/><el-table-column prop="submitted_at" label="提交时间" width="190"/><el-table-column label="操作" width="170"><template #default="{row}"><el-button link @click="router.push(`/assignments/submissions/${row.id}`)">详情</el-button><el-button link type="primary" @click="open(row)">确认成绩</el-button></template></el-table-column></el-table></el-card>
    <el-dialog v-model="visible" title="确认并发布成绩" width="430"><el-form label-position="top"><el-form-item label="最终成绩"><el-input-number v-model="score" :min="0" :max="100"/></el-form-item><el-form-item label="教师评语"><el-input v-model="comment" type="textarea" :rows="4"/></el-form-item></el-form><template #footer><el-button @click="visible=false">取消</el-button><el-button type="primary" @click="confirm">发布</el-button></template></el-dialog>
  </div>
</template>
<script setup lang="ts">
import { onMounted, ref } from 'vue';import { useRouter } from 'vue-router';import { ElMessage } from 'element-plus';import { assignmentApi } from '@/api/assignment'
const router=useRouter(),items=ref<any[]>([]),loading=ref(false),visible=ref(false),currentId=ref(''),score=ref(0),comment=ref('')
async function load(){loading.value=true;try{items.value=(await assignmentApi.pending()).data}finally{loading.value=false}}
function open(row:any){currentId.value=row.id;score.value=row.automatic_score??0;comment.value='';visible.value=true}
async function confirm(){await assignmentApi.confirm(currentId.value,score.value,comment.value);ElMessage.success('成绩已发布');visible.value=false;await load()}
onMounted(load)
</script>
<style scoped>.page{max-width:1050px}.page h2{margin-top:0}</style>
