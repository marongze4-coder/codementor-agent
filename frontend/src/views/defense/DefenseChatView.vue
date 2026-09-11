<template>
  <div class="page"><el-page-header title="返回" content="课程项目答辩" @back="router.push('/defense')" />
    <el-steps class="steps" :active="activeStage" align-center><el-step title="项目概述"/><el-step title="设计思路"/><el-step title="调试分析"/><el-step title="优化改进"/><el-step title="总结"/></el-steps>
    <el-card class="chat" v-loading="loading">
      <template v-if="session?.status==='finished'"><el-result icon="success" title="答辩已结束" :sub-title="session.overall_score == null ? '记录已保存，等待教师或大模型评价' : `综合得分 ${session.overall_score}`"/><div v-if="session.report" class="report"><h3>答辩报告</h3><p v-for="x in session.report.strengths" :key="x">优势：{{x}}</p><p v-for="x in session.report.weaknesses" :key="x">不足：{{x}}</p><p v-for="x in session.report.recommendations" :key="x">建议：{{x}}</p></div></template>
      <template v-else><div class="messages" ref="box"><div v-for="(m,i) in messages" :key="i" class="message" :class="m.role"><div class="bubble">{{m.content}}</div></div></div><div class="composer"><el-input v-model="input" type="textarea" :rows="3" placeholder="说明你的思路；输入“结束答辩”可提前结束" @keyup.ctrl.enter="send"/><div class="actions"><span>第 {{session?.turn_count ?? 0}} / 10 轮</span><div><el-button @click="input='结束答辩';send()" :disabled="sending">结束答辩</el-button><el-button type="primary" @click="send" :loading="sending" :disabled="!input.trim()">发送回答</el-button></div></div></div></template>
    </el-card>
  </div>
</template>
<script setup lang="ts">
import { computed,nextTick,onMounted,ref } from 'vue';import { useRoute,useRouter } from 'vue-router';import { ElMessage } from 'element-plus';import { defenseApi,type DefenseMessageItem,type DefenseSession } from '@/api/defense'
const route=useRoute(),router=useRouter(),session=ref<DefenseSession>(),messages=ref<DefenseMessageItem[]>([]),input=ref(''),sending=ref(false),loading=ref(true),box=ref<HTMLElement>()
const stages=['overview','design','debugging','improvement','closing'];const activeStage=computed(()=>Math.max(0,stages.indexOf(session.value?.stage||'overview')))
async function load(){session.value=(await defenseApi.get(route.params.sessionId as string)).data;messages.value=session.value.messages||[];loading.value=false;await scroll()}
async function scroll(){await nextTick();if(box.value)box.value.scrollTop=box.value.scrollHeight}
async function send(){const value=input.value.trim();if(!value||sending.value)return;messages.value.push({role:'student',content:value});input.value='';sending.value=true;await scroll();try{const {data}=await defenseApi.chat(route.params.sessionId as string,value);messages.value.push({role:'assistant',content:data.message});if(session.value){session.value.stage=data.stage;session.value.turn_count=data.turn_count;session.value.status=data.status;if(data.report)session.value.report=data.report}await scroll();if(data.fallback_used)ElMessage.info('当前未配置大模型密钥，本轮使用本地答辩流程')}finally{sending.value=false}}
onMounted(load)
</script>
<style scoped>.page{max-width:930px}.steps{margin:24px 0}.chat{min-height:560px}.messages{height:390px;overflow:auto;padding:8px}.message{display:flex;margin:12px 0}.message.student{justify-content:flex-end}.bubble{max-width:75%;padding:11px 14px;border-radius:12px;background:#f2f3f5;white-space:pre-wrap;line-height:1.6}.student .bubble{background:#1677ff;color:white}.composer{border-top:1px solid #eee;padding-top:15px}.actions{display:flex;justify-content:space-between;align-items:center;margin-top:10px;color:#909399}.report{max-width:650px;margin:auto}.report p{padding:8px;background:#f7f8fa}</style>
