<template>
  <div class="page"><h2>🧰 课程与作业配置</h2><el-tabs v-model="tab" type="border-card">
    <el-tab-pane label="新建课程" name="course"><el-form label-position="top" class="form"><el-form-item label="课程名称"><el-input v-model="course.name" placeholder="Python 程序设计基础"/></el-form-item><el-form-item label="课程编号"><el-input v-model="course.code" placeholder="PY101"/></el-form-item><el-form-item label="课程简介"><el-input v-model="course.description" type="textarea"/></el-form-item><el-button type="primary" @click="createCourse">保存课程</el-button></el-form></el-tab-pane>
    <el-tab-pane label="新建作业" name="assignment"><el-form label-position="top" class="form"><el-form-item label="所属课程"><el-select v-model="assignment.course_id" style="width:100%"><el-option v-for="c in courses" :key="c.id" :label="`${c.code} · ${c.name}`" :value="c.id"/></el-select></el-form-item><el-form-item label="作业标题"><el-input v-model="assignment.title"/></el-form-item><el-form-item label="题目要求"><el-input v-model="assignment.description" type="textarea" :rows="5"/></el-form-item><el-form-item label="功能 / 质量权重"><el-slider v-model="functionalWeight" :min="10" :max="90" show-input/></el-form-item><el-button type="primary" @click="createAssignment">保存作业</el-button></el-form></el-tab-pane>
    <el-tab-pane label="添加测试用例" name="test"><el-form label-position="top" class="form"><el-form-item label="作业"><el-select v-model="test.assignment_id" style="width:100%"><el-option v-for="a in assignments" :key="a.id" :label="`${a.course_name} · ${a.title}`" :value="a.id"/></el-select></el-form-item><el-form-item label="用例名称"><el-input v-model="test.name"/></el-form-item><el-form-item label="标准输入"><el-input v-model="test.input_data" type="textarea" :rows="3"/></el-form-item><el-form-item label="预期输出"><el-input v-model="test.expected_output" type="textarea" :rows="3"/></el-form-item><el-row :gutter="20"><el-col :span="8"><el-form-item label="超时秒数"><el-input-number v-model="test.timeout_seconds" :min="1" :max="30"/></el-form-item></el-col><el-col :span="8"><el-form-item label="权重"><el-input-number v-model="test.weight" :min="1"/></el-form-item></el-col><el-col :span="8"><el-form-item label="对学生隐藏"><el-switch v-model="test.is_hidden"/></el-form-item></el-col></el-row><el-button type="primary" @click="createTest">添加测试用例</el-button></el-form></el-tab-pane>
  </el-tabs></div>
</template>
<script setup lang="ts">
import { computed,onMounted,reactive,ref } from 'vue';import { ElMessage } from 'element-plus';import { assignmentApi,type Assignment,type Course } from '@/api/assignment'
const tab=ref('course'),courses=ref<Course[]>([]),assignments=ref<Assignment[]>([]),functionalWeight=ref(60)
const course=reactive({name:'',code:'',description:'',primary_language:'python'})
const assignment=reactive({course_id:'',title:'',description:'',language:'python',entry_file:'main.py',max_score:100})
const test=reactive({assignment_id:'',name:'',input_data:'',expected_output:'',timeout_seconds:3,weight:1,is_hidden:true})
const rubric=computed(()=>({functional:functionalWeight.value,quality:100-functionalWeight.value}))
async function load(){const [c,a]=await Promise.all([assignmentApi.courses(),assignmentApi.list()]);courses.value=c.data;assignments.value=a.data}
async function createCourse(){if(!course.name||!course.code)return ElMessage.warning('请填写课程名称和编号');await assignmentApi.createCourse(course);ElMessage.success('课程已创建');course.name='';course.code='';course.description='';await load()}
async function createAssignment(){if(!assignment.course_id||!assignment.title||!assignment.description)return ElMessage.warning('请完整填写作业信息');await assignmentApi.createAssignment({...assignment,rubric:rubric.value});ElMessage.success('作业已创建');assignment.title='';assignment.description='';await load();tab.value='test'}
async function createTest(){if(!test.assignment_id||!test.name||!test.expected_output)return ElMessage.warning('请填写作业、名称和预期输出');await assignmentApi.createTestCase(test.assignment_id,test);ElMessage.success('测试用例已添加');test.name='';test.input_data='';test.expected_output=''}
onMounted(load)
</script>
<style scoped>.page{max-width:900px}.page h2{margin-top:0}.form{max-width:650px;padding:14px}</style>
