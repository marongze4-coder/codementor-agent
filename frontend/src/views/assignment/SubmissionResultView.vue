<template>
  <div class="page">
    <el-page-header title="返回" content="作业评测结果" @back="router.push('/assignments')" />
    <el-card class="content" v-loading="loading">
      <el-result v-if="data?.status === 'evaluating'" icon="info" title="正在自动评测" sub-title="测试用例在隔离容器中运行，页面会自动刷新" />
      <el-result v-else-if="data?.status === 'failed'" icon="error" title="评测失败" :sub-title="data.error_msg" />
      <template v-else-if="data">
        <div class="top"><div><h2>{{ data.assignment_title }}</h2><p>{{ data.course_name }} · {{ data.original_filename }}</p></div><el-progress type="dashboard" :percentage="displayScore"><template #default><b>{{ displayScore }}</b><small>/100</small></template></el-progress></div>
        <el-descriptions border :column="3"><el-descriptions-item label="功能测试">{{ data.functional_score ?? 0 }}</el-descriptions-item><el-descriptions-item label="代码质量">{{ data.quality_score ?? 0 }}</el-descriptions-item><el-descriptions-item label="发布状态"><el-tag :type="data.status === 'published' ? 'success' : 'warning'">{{ data.status === 'published' ? '教师已发布' : '等待教师确认' }}</el-tag></el-descriptions-item></el-descriptions>
        <h3>测试用例</h3><el-table :data="data.test_results"><el-table-column prop="name" label="用例"/><el-table-column label="结果" width="100"><template #default="{row}"><el-tag :type="row.passed?'success':'danger'">{{ row.passed?'通过':'失败' }}</el-tag></template></el-table-column><el-table-column prop="duration_ms" label="耗时(ms)" width="110"/><el-table-column prop="stderr" label="错误信息" /></el-table>
        <h3>综合反馈</h3><el-alert :title="data.feedback || '评测完成'" :description="data.teacher_comment || '教师确认后发布最终成绩。'" type="info" :closable="false" />
      </template>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { assignmentApi, type Submission } from '@/api/assignment'
const route=useRoute(),router=useRouter(),data=ref<Submission>(),loading=ref(true);let timer:number|undefined
const displayScore=computed(()=>data.value?.final_score ?? data.value?.automatic_score ?? 0)
async function load(){data.value=(await assignmentApi.submission(route.params.submissionId as string)).data;loading.value=false;if(data.value.status==='evaluating')timer=window.setTimeout(load,1500)}
onMounted(load);onBeforeUnmount(()=>timer&&clearTimeout(timer))
</script>

<style scoped>
.page{max-width:1000px}.content{margin-top:18px}.top{display:flex;justify-content:space-between;align-items:center}.top h2{margin:0}.top p{color:#909399}.content h3{margin-top:24px}small{color:#909399}
</style>
