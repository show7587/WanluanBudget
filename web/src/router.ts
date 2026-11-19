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
    { path: "/:year(\\d+)/搜尋", name: "search", component: () => import("@/views/SearchView.vue"), meta: { title: "搜尋" } },
    { path: "/:year(\\d+)/參考表", name: "reference", component: () => import("@/views/ReferenceView.vue"), meta: { title: "參考表" } },
    { path: "/:year(\\d+)/備註", name: "memo", component: () => import("@/views/MemoView.vue"), meta: { title: "資料備註" } },
    {
      // 瀏覽器重新整理／上一頁時，網址中的中文會是百分比編碼，靜態中文路由比不到；
      // 這裡拿到的 pathMatch 已解碼，認得出是已知頁面就導回對應路由（保留 query），否則回首頁。
      path: "/:pathMatch(.*)*",
      redirect: (to) => {
        const raw = Array.isArray(to.params.pathMatch) ? to.params.pathMatch.join("/") : String(to.params.pathMatch ?? "");
        const p = "/" + raw.replace(/^\/+/, "");
        return /^\/\d+\/(總覽|歲出|歲入|比較|搜尋|參考表|備註)$/.test(p) ? { path: p, query: to.query, hash: to.hash } : "/";
      },
    },
  ],
  scrollBehavior: () => ({ top: 0 }),
});

router.afterEach((to) => {
  const t = to.meta.title as string | undefined;
  document.title = t ? `${t}｜萬巒鄉預算查詢` : "萬巒鄉預算查詢";
});
