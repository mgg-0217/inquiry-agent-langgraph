import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/inbox' },
    {
      path: '/inbox',
      name: 'inbox',
      component: () => import('../views/InboxView.vue'),
    },
    {
      path: '/approvals',
      name: 'approvals',
      component: () => import('../views/ApprovalsView.vue'),
    },
    {
      path: '/customers',
      name: 'customers',
      component: () => import('../views/CustomersView.vue'),
    },
    {
      path: '/customers/:id',
      name: 'customer-memory',
      component: () => import('../views/CustomerMemoryView.vue'),
    },
    {
      path: '/threads/:id/trace',
      name: 'trace',
      component: () => import('../views/TraceView.vue'),
    },
  ],
})

export default router
