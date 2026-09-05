import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/chat' },
  { path: '/chat', name: 'chat', component: () => import('../views/ChatView.vue'), meta: { titleKey: 'page.chat.title', tagKeys: ['page.chat.tags.0', 'page.chat.tags.1', 'page.chat.tags.2'] } },
  { path: '/dashboard', name: 'dashboard', component: () => import('../views/DashboardView.vue'), meta: { titleKey: 'page.dashboard.title', tagKeys: ['page.dashboard.tags.0', 'page.dashboard.tags.1', 'page.dashboard.tags.2'] } },
  { path: '/agents', name: 'agents', component: () => import('../views/AgentsView.vue'), meta: { titleKey: 'page.agents.title', tagKeys: ['page.agents.tags.0', 'page.agents.tags.1'] } },
  { path: '/task', name: 'task', component: () => import('../views/TaskView.vue'), meta: { titleKey: 'page.task.title', tagKeys: ['page.task.tags.0', 'page.task.tags.1', 'page.task.tags.2'] } },
  { path: '/knowledge', name: 'knowledge', component: () => import('../views/KnowledgeView.vue'), meta: { titleKey: 'page.knowledge.title', tagKeys: ['page.knowledge.tags.0', 'page.knowledge.tags.1'] } },
  { path: '/analysis', name: 'analysis', component: () => import('../views/AnalysisView.vue'), meta: { titleKey: 'page.analysis.title', tagKeys: ['page.analysis.tags.0', 'page.analysis.tags.1'] } },
  { path: '/integration', name: 'integration', component: () => import('../views/IntegrationView.vue'), meta: { titleKey: 'page.integration.title', tagKeys: ['page.integration.tags.0', 'page.integration.tags.1', 'page.integration.tags.2'] } },
  { path: '/settings', name: 'settings', component: () => import('../views/SettingsView.vue'), meta: { titleKey: 'page.settings.title', tagKeys: ['page.settings.tags.0', 'page.settings.tags.1', 'page.settings.tags.2'] } },
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
