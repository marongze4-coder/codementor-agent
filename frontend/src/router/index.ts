import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      component: () => import('@/components/layout/AppLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        {
          path: '',
          redirect: '/dashboard',
        },
        {
          path: 'dashboard',
          name: 'dashboard',
          component: () => import('@/views/DashboardView.vue'),
        },
        // AI 助手（统一入口）
        {
          path: 'chat',
          name: 'chat',
          component: () => import('@/views/UnifiedChatView.vue'),
        },
        // QA 问答
        {
          path: 'qa',
          name: 'qa',
          component: () => import('@/views/qa/QAChatView.vue'),
        },
        {
          path: 'assignments',
          name: 'assignments',
          component: () => import('@/views/assignment/AssignmentListView.vue'),
        },
        {
          path: 'assignments/submissions/:submissionId',
          name: 'submission-result',
          component: () => import('@/views/assignment/SubmissionResultView.vue'),
        },
        {
          path: 'code-review',
          name: 'code-review',
          component: () => import('@/views/code-review/CodeReviewView.vue'),
        },
        {
          path: 'code-review/:reviewId',
          name: 'code-review-result',
          component: () => import('@/views/code-review/CodeReviewResultView.vue'),
        },
        {
          path: 'defense',
          name: 'defense',
          component: () => import('@/views/defense/DefenseSetupView.vue'),
        },
        {
          path: 'defense/:sessionId',
          name: 'defense-chat',
          component: () => import('@/views/defense/DefenseChatView.vue'),
        },
        // 教师端（需要 teacher/admin 角色）
        {
          path: 'teacher/course-manage',
          name: 'teacher-course-manage',
          component: () => import('@/views/teacher/CourseManageView.vue'),
          meta: { requiresTeacher: true },
        },
        {
          path: 'teacher/assignment-review',
          name: 'teacher-assignment-review',
          component: () => import('@/views/teacher/AssignmentReviewView.vue'),
          meta: { requiresTeacher: true },
        },
        {
          path: 'teacher/knowledge-pending',
          name: 'teacher-knowledge-pending',
          component: () => import('@/views/teacher/KnowledgePendingView.vue'),
          meta: { requiresTeacher: true },
        },
      ],
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/dashboard',
    },
  ],
})

router.beforeEach((to, _from, next) => {
  const auth = useAuthStore()

  if (to.meta.public) {
    if (auth.isLoggedIn && to.name === 'login') return next('/dashboard')
    return next()
  }

  if (!auth.isLoggedIn) return next('/login')

  if (to.meta.requiresTeacher && !auth.isTeacher) return next('/dashboard')

  next()
})

export default router
