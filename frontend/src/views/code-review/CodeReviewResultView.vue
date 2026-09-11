<template>
  <div class="page">
    <el-page-header title="返回" content="代码审查报告" @back="router.push('/code-review')" />
    <el-card class="report" v-loading="loading">
      <el-result v-if="review?.status === 'processing'" icon="info" title="正在审查代码" sub-title="页面会自动刷新" />
      <el-result v-else-if="review?.status === 'failed'" icon="error" title="审查失败" :sub-title="review.error_msg" />
      <template v-else-if="review">
        <div class="hero"><div><h2>{{ review.original_filename }}</h2><el-tag>{{ review.language }}</el-tag></div><el-progress type="dashboard" :percentage="review.overall_score ?? 0"><template #default><b>{{ review.overall_score }}</b><small> / 100</small></template></el-progress></div>
        <el-row :gutter="12">
          <el-col v-for="item in review.dimension_scores" :key="item.dimension" :span="8"><el-card shadow="never" class="dimension"><b>{{ item.dimension }}</b><span>{{ item.score }}</span><el-progress :percentage="item.score" :show-text="false" /></el-card></el-col>
        </el-row>
        <h3>问题与修改建议</h3>
        <el-empty v-if="!review.issues?.length" description="未发现明显问题" />
        <el-collapse v-else>
          <el-collapse-item v-for="(item, index) in review.issues" :key="index" :name="index">
            <template #title><el-tag :type="severityType(item.severity)" size="small">{{ item.severity }}</el-tag><span class="issue-title">{{ item.title }}<small v-if="item.line">（第 {{ item.line }} 行）</small></span></template>
            <p v-if="item.evidence"><b>依据：</b>{{ item.evidence }}</p><p><b>建议：</b>{{ item.suggestion }}</p>
          </el-collapse-item>
        </el-collapse>
        <el-alert class="summary" :title="`等级 ${review.summary?.grade ?? '—'}`" :description="review.summary?.next_steps?.join('；')" type="success" :closable="false" />
      </template>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { codeReviewApi, type CodeReview } from '@/api/codeReview'
const route = useRoute(), router = useRouter()
const review = ref<CodeReview>(), loading = ref(true)
let timer: number | undefined
const severityType = (v: string) => v === 'critical' || v === 'high' ? 'danger' : v === 'medium' ? 'warning' : 'info'
async function load() {
  review.value = (await codeReviewApi.get(route.params.reviewId as string)).data
  loading.value = false
  if (review.value.status === 'processing') timer = window.setTimeout(load, 1500)
}
onMounted(load); onBeforeUnmount(() => timer && clearTimeout(timer))
</script>

<style scoped>
.page{max-width:1050px}.report{margin-top:18px}.hero{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px}.hero h2{margin:0 0 8px}.dimension{margin-bottom:12px}.dimension span{float:right;font-size:20px;color:#1677ff}.issue-title{margin-left:10px}.summary{margin-top:20px}small{color:#909399}
</style>
