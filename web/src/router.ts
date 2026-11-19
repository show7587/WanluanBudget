import { createRouter, createWebHashHistory } from "vue-router";
import { dataSource } from "@/data/source";

/** 路由沿用舊站網址：#/<年>/<總覽|歲出|歲入|比較>?…；每頁狀態同步在 query（path、view…） */
export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: "/",
      component: { render: () => null },
      beforeEnter: async () => {
        const idx = await dataSource().index();
        return { path: `/${idx.default_year}/總覽`, replace: true };
      },
    },
    { path: "/:year(\\d+)/總覽", name: "overview", component: () => import("@/views/OverviewView.vue"), meta: { title: "總覽" } },
    { path: "/:year(\\d+)/歲出", name: "expenditure", component: () => import("@/views/ExpenditureView.vue"), meta: { title: "歲出" } },
    { path: "/:year(\\d+)/歲入", name: "revenue", component: () => import("@/views/RevenueView.vue"), meta: { title: "歲入" } },
    { path: "/:year(\\d+)/比較", name: "compare", component: () => import("@/views/CompareView.vue"), meta: { title: "比較" } },
    { path: "/:pathMatch(.*)*", redirect: "/" },
  ],
  scrollBehavior: () => ({ top: 0 }),
});

router.afterEach((to) => {
  const t = to.meta.title as string | undefined;
  document.title = t ? `${t}｜萬巒鄉預算查詢` : "萬巒鄉預算查詢";
});
