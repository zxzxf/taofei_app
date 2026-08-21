import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/chat' },
  { path: '/chat', name: 'chat', component: () => import('../views/ChatView.vue'), meta: { title: '会话中心', tags: ['多轮对话', '任务触发', '历史记录'] } },
  { path: '/dashboard', name: 'dashboard', component: () => import('../views/DashboardView.vue'), meta: { title: '工作台', tags: ['数据概览', '趋势分析', '快速开始'] } },
  { path: '/agents', name: 'agents', component: () => import('../views/AgentsView.vue'), meta: { title: '智能体', tags: ['Agent 市场', '自定义编排'] } },
  { path: '/task', name: 'task', component: () => import('../views/TaskView.vue'), meta: { title: '任务编排', tags: ['新建任务', '运行结果', '可视化编排'] } },
  { path: '/knowledge', name: 'knowledge', component: () => import('../views/KnowledgeView.vue'), meta: { title: '知识库', tags: ['文档上传', 'RAG 问答'] } },
  { path: '/analysis', name: 'analysis', component: () => import('../views/AnalysisView.vue'), meta: { title: '数据分析', tags: ['运行统计', '成本分析'] } },
  { path: '/integration', name: 'integration', component: () => import('../views/IntegrationView.vue'), meta: { title: '集成管理', tags: ['天气查询', '技能管理', '集成列表'] } },
  { path: '/settings', name: 'settings', component: () => import('../views/SettingsView.vue'), meta: { title: '系统设置', tags: ['模型配置', '外观', '备份'] } },
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
