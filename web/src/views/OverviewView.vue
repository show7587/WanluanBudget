<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import ChartPanel from "@/components/ChartPanel.vue";
import DataTable from "@/components/DataTable.vue";
import KpiCard from "@/components/KpiCard.vue";
import { useBudget } from "@/composables/useBudget";
import { fmtCompact, fmtInt, fmtSignedPct, fmtSignedYuan, fmtYuan } from "@/data/format";
import { computeDiff, normalizeExpenditure, normalizeRevenue, type FlatRow } from "@/data/normalize";
import type { TreeNode } from "@/data/types";
import StructureChart from "@/views/overview/StructureChart.vue";
import YearCompareBarChart from "@/views/overview/YearCompareBarChart.vue";

const route = useRoute();
const router = useRouter();

const year = computed(() => Number(route.params.year) || 0);
const { loading, error, index, data, compare } = useBudget(year);

const sortedSummaries = computed(() =>
  [...(index.value?.year_summaries ?? [])].sort((a, b) => a.year - b.year),
);

interface YearSummaryRow {
  year: number;
  revenue: number;
  expenditure: number;
  balance: number;
  revPct: number | null;
  expPct: number | null;
}

const yearSummaryRows = computed<YearSummaryRow[]>(() =>
  sortedSummaries.value.map((s, idx) => {
    const prev = idx > 0 ? sortedSummaries.value[idx - 1] : null;
    const revDiff = computeDiff(s.revenue_total_元, prev ? prev.revenue_total_元 : null);
    const expDiff = computeDiff(s.expenditure_total_元, prev ? prev.expenditure_total_元 : null);
    return {
      year: s.year,
      revenue: s.revenue_total_元,
      expenditure: s.expenditure_total_元,
      balance: s.revenue_total_元 - s.expenditure_total_元,
      revPct: revDiff.pct,
      expPct: expDiff.pct,
    };
  }),
);

const currentSummaryRow = computed(() =>
  yearSummaryRows.value.find((r) => r.year === year.value) ?? null,
);

const prevYear = computed<number | null>(() => {
  const idx = sortedSummaries.value.findIndex((s) => s.year === year.value);
  return idx > 0 ? sortedSummaries.value[idx - 1].year : null;
});

function trendText(pct: number | null | undefined, prevY: number | null): string {
  if (pct == null || prevY == null) return "";
  const sym = pct > 0 ? "▲" : pct < 0 ? "▼" : "＝";
  return `｜較 ${prevY} 年度 ${sym} ${fmtSignedPct(pct)}`;
}

function balanceTag(balance: number): { symbol: string; label: string; tone: "good" | "bad" | "neutral" } {
  if (balance > 0) return { symbol: "▲", label: "賸餘", tone: "good" };
  if (balance < 0) return { symbol: "▼", label: "短絀", tone: "bad" };
  return { symbol: "＝", label: "收支平衡", tone: "neutral" };
}

const kpiCards = computed(() => {
  const ov = data.value?.overview;
  if (!ov) return [];
  const bal = balanceTag(ov.balance_元);
  const cur = currentSummaryRow.value;
  return [
    {
      key: "revenue",
      label: "歲入總額",
      value: fmtYuan(ov.revenue_total_元),
      sub: `約 ${fmtCompact(ov.revenue_total_元)}${trendText(cur?.revPct, prevYear.value)}`,
      tone: "neutral" as const,
    },
    {
      key: "expenditure",
      label: "歲出總額",
      value: fmtYuan(ov.expenditure_total_元),
      sub: `約 ${fmtCompact(ov.expenditure_total_元)}${trendText(cur?.expPct, prevYear.value)}`,
      tone: "neutral" as const,
    },
    {
      key: "balance",
      label: "歲入歲出餘絀",
      value: fmtSignedYuan(ov.balance_元),
      sub:
        ov.balance_元 < 0
          ? `${bal.symbol} ${bal.label}（約 ${fmtCompact(Math.abs(ov.balance_元))}，歲出大於歲入）`
          : ov.balance_元 > 0
            ? `${bal.symbol} ${bal.label}（約 ${fmtCompact(ov.balance_元)}，歲入大於歲出）`
            : `${bal.symbol} ${bal.label}`,
      tone: bal.tone,
    },
    {
      key: "prior_surplus",
      label: "動用以前年度賸餘",
      value: fmtYuan(ov.prior_surplus_used_元),
      sub:
        ov.prior_surplus_used_元 > 0
          ? `約 ${fmtCompact(ov.prior_surplus_used_元)}｜彌補當年度收支短絀`
          : "本年度未動用以前年度賸餘",
      tone: "neutral" as const,
    },
  ];
});

const yearCompareExportRows = computed<FlatRow[]>(() =>
  sortedSummaries.value.flatMap((s, idx) => {
    const prev = idx > 0 ? sortedSummaries.value[idx - 1] : null;
    const rev = computeDiff(s.revenue_total_元, prev ? prev.revenue_total_元 : null);
    const exp = computeDiff(s.expenditure_total_元, prev ? prev.expenditure_total_元 : null);
    return [
      {
        level: "年度總額",
        path: [`${s.year} 年度`, "歲入"],
        name: `${s.year} 年度歲入`,
        amount: s.revenue_total_元,
        prev: rev.prev,
        diff: rev.diff,
        pct: rev.pct,
        status: rev.status,
      },
      {
        level: "年度總額",
        path: [`${s.year} 年度`, "歲出"],
        name: `${s.year} 年度歲出`,
        amount: s.expenditure_total_元,
        prev: exp.prev,
        diff: exp.diff,
        pct: exp.pct,
        status: exp.status,
      },
    ];
  }),
);

const revenueNodes = computed<TreeNode[]>(() =>
  data.value ? [...normalizeRevenue(data.value, compare.value)].sort((a, b) => b.amount - a.amount) : [],
);

const expenditureNodes = computed<TreeNode[]>(() =>
  data.value
    ? [...normalizeExpenditure(data.value, compare.value, "政事別")].sort((a, b) => b.amount - a.amount)
    : [],
);

function toFlatRows(nodes: TreeNode[]): FlatRow[] {
  return nodes.map((n) => ({
    level: n.level,
    path: [n.name],
    name: n.name,
    amount: n.amount,
    prev: n.prev,
    diff: n.diff,
    pct: n.pct,
    status: n.status,
  }));
}

const revenueExportRows = computed(() => toFlatRows(revenueNodes.value));
const expenditureExportRows = computed(() => toFlatRows(expenditureNodes.value));

function goToRevenueNode(node: TreeNode): void {
  void router.push({ path: `/${year.value}/歲入`, query: { path: node.id } });
}

function goToExpenditureNode(node: TreeNode): void {
  void router.push({ path: `/${year.value}/歲出`, query: { path: node.id } });
}

const entryLinks = computed(() => {
  const ov = data.value?.overview;
  const y = year.value;
  return [
    {
      to: `/${y}/歲出`,
      title: "歲出結構查詢",
      badge: `${expenditureNodes.value.length} 大政事別`,
      desc: ov
        ? `依政事別、機關別、用途別三視角下鑽查看工作計畫與用途明細（歲出總計 ${fmtCompact(ov.expenditure_total_元)}）。`
        : "依政事別、機關別、用途別三視角瀏覽歲出明細。",
    },
    {
      to: `/${y}/歲入`,
      title: "歲入來源查詢",
      badge: `${revenueNodes.value.length} 大收入款別`,
      desc: ov
        ? `依款、項、子目、細目逐層查看各項收入來源與增減變化（歲入總計 ${fmtCompact(ov.revenue_total_元)}）。`
        : "依款、項、子目、細目逐層瀏覽歲入來源。",
    },
    {
      to: `/${y}/比較`,
      title: "跨年度預算比較",
      badge: compare.value ? `${compare.value.to_year} vs ${compare.value.from_year}` : "最早年度",
      desc: compare.value
        ? `檢視 ${compare.value.to_year} 與 ${compare.value.from_year} 年度各項歲入與歲出增減排行、變化幅度與篩選。`
        : `${y} 年度為目前收錄最早年度，可前往檢視說明或切換其他年度比較。`,
    },
  ];
});
</script>

<template>
  <div class="page" :aria-busy="loading">
    <header class="page-head">
      <h1 class="page-title">{{ year }} 年度預算總覽</h1>
      <p class="muted subtitle">
        萬巒鄉總預算收支規模、歷年對照與款層級結構；金額單位一律為「元」。
      </p>
    </header>

    <div v-if="loading" class="card muted" role="status" aria-live="polite">
      正在載入 {{ year }} 年度預算資料…
    </div>

    <div v-else-if="error" class="error-box" role="alert">
      無法載入 {{ year }} 年度預算資料：{{ error }}
    </div>

    <template v-else-if="data">
      <!-- KPI 卡片 -->
      <section aria-label="核心收支指標" class="grid kpi">
        <KpiCard
          v-for="card in kpiCards"
          :key="card.key"
          :label="card.label"
          :value="card.value"
          :sub="card.sub"
          :tone="card.tone"
        />
      </section>

      <!-- 經常門／資本門摘要 -->
      <section class="card account-strip" aria-label="經常門與資本門收支摘要">
        <div class="account-item">
          <div class="account-title">經常門</div>
          <div class="account-detail muted">
            <span>歲入 <strong class="num">{{ fmtYuan(data.overview.current_account.revenue_元) }}</strong></span>
            <span>歲出 <strong class="num">{{ fmtYuan(data.overview.current_account.expenditure_元) }}</strong></span>
            <span>
              {{ data.overview.current_account.surplus_元 >= 0 ? "經常收支賸餘" : "經常收支短絀" }}
              <strong class="num"><span aria-hidden="true">{{ data.overview.current_account.surplus_元 >= 0 ? "▲" : "▼" }}</span> {{ fmtYuan(Math.abs(data.overview.current_account.surplus_元)) }}</strong>
            </span>
          </div>
        </div>
        <div class="account-item">
          <div class="account-title">資本門</div>
          <div class="account-detail muted">
            <span>歲入 <strong class="num">{{ fmtYuan(data.overview.capital_account.revenue_元) }}</strong></span>
            <span>歲出 <strong class="num">{{ fmtYuan(data.overview.capital_account.expenditure_元) }}</strong></span>
            <span>
              {{ data.overview.capital_account.shortfall_元 >= 0 ? "資本收支短絀" : "資本收支賸餘" }}
              <strong class="num"><span aria-hidden="true">{{ data.overview.capital_account.shortfall_元 >= 0 ? "▼" : "▲" }}</span> {{ fmtYuan(Math.abs(data.overview.capital_account.shortfall_元)) }}</strong>
            </span>
          </div>
        </div>
      </section>

      <!-- 3 個年度歲入 vs 歲出對照長條圖 -->
      <ChartPanel
        v-if="sortedSummaries.length"
        title="歷年歲入與歲出對照"
        :subtitle="`比較 ${sortedSummaries.map((s) => `${s.year} 年度`).join('、')} 總預算歲入與歲出規模（目前檢視：${year} 年度）`"
        :export-rows="yearCompareExportRows"
        :export-name="`budget-overview-years-${year}`"
      >
        <template #chart>
          <YearCompareBarChart :summaries="sortedSummaries" :current-year="year" />
        </template>
        <template #table>
          <div class="table-wrap">
            <table class="data">
              <caption>歷年總預算歲入與歲出對照表（金額單位：元）</caption>
              <thead>
                <tr>
                  <th scope="col">年度</th>
                  <th scope="col" class="num">歲入（元）</th>
                  <th scope="col" class="num">歲出（元）</th>
                  <th scope="col" class="num">歲入歲出餘絀（元）</th>
                  <th scope="col">收支狀態</th>
                  <th scope="col" class="num">歲入較上年度</th>
                  <th scope="col" class="num">歲出較上年度</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="r in yearSummaryRows" :key="r.year" :class="{ 'is-current': r.year === year }">
                  <th scope="row">
                    {{ r.year }} 年度
                    <span v-if="r.year === year" class="current-tag">目前</span>
                  </th>
                  <td class="num">{{ fmtInt(r.revenue) }}</td>
                  <td class="num">{{ fmtInt(r.expenditure) }}</td>
                  <td class="num">{{ fmtSignedYuan(r.balance) }}</td>
                  <td>
                    <span aria-hidden="true">{{ balanceTag(r.balance).symbol }}</span>
                    {{ balanceTag(r.balance).label }}
                  </td>
                  <td class="num">
                    <template v-if="r.revPct != null">
                      <span aria-hidden="true">{{ r.revPct > 0 ? "▲" : r.revPct < 0 ? "▼" : "＝" }}</span>
                      {{ fmtSignedPct(r.revPct) }}
                    </template>
                    <template v-else>—</template>
                  </td>
                  <td class="num">
                    <template v-if="r.expPct != null">
                      <span aria-hidden="true">{{ r.expPct > 0 ? "▲" : r.expPct < 0 ? "▼" : "＝" }}</span>
                      {{ fmtSignedPct(r.expPct) }}
                    </template>
                    <template v-else>—</template>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
      </ChartPanel>

      <!-- 歲入／歲出結構圖（各一，款層級） -->
      <div class="structure-grid">
        <ChartPanel
          title="歲入結構（款層級）"
          :subtitle="`${year} 年度共 ${revenueNodes.length} 款，點擊項目可前往歲入頁下鑽`"
          :export-rows="revenueExportRows"
          :export-name="`budget-overview-revenue-${year}`"
        >
          <template #chart>
            <StructureChart
              :nodes="revenueNodes"
              :total="data.overview.revenue_total_元"
              center-title="歲入總額"
              :chart-title="`${year} 年度歲入結構（款層級）`"
              @select="goToRevenueNode"
            />
          </template>
          <template #table>
            <DataTable
              :nodes="revenueNodes"
              :parent-total="data.overview.revenue_total_元"
              :show-diff="true"
              :caption="`${year} 年度歲入結構（款層級）`"
              @drill="goToRevenueNode"
            />
          </template>
        </ChartPanel>

        <ChartPanel
          title="歲出結構（政事別）"
          :subtitle="`${year} 年度共 ${expenditureNodes.length} 大政事別，點擊項目可前往歲出頁下鑽`"
          :export-rows="expenditureExportRows"
          :export-name="`budget-overview-expenditure-${year}`"
        >
          <template #chart>
            <StructureChart
              :nodes="expenditureNodes"
              :total="data.overview.expenditure_total_元"
              center-title="歲出總額"
              :chart-title="`${year} 年度歲出結構（政事別）`"
              @select="goToExpenditureNode"
            />
          </template>
          <template #table>
            <DataTable
              :nodes="expenditureNodes"
              :parent-total="data.overview.expenditure_total_元"
              :show-diff="true"
              :caption="`${year} 年度歲出結構（政事別）`"
              @drill="goToExpenditureNode"
            />
          </template>
        </ChartPanel>
      </div>

      <!-- 入口卡片 -->
      <section aria-labelledby="entry-heading" class="entries-section">
        <h2 id="entry-heading" class="section-title">深入探索 {{ year }} 年度預算</h2>
        <div class="entry-grid">
          <router-link
            v-for="entry in entryLinks"
            :key="entry.to"
            :to="entry.to"
            class="card entry-card"
          >
            <div class="entry-head">
              <h3 class="entry-title">{{ entry.title }}</h3>
              <span class="entry-badge">{{ entry.badge }}</span>
            </div>
            <p class="entry-desc muted">{{ entry.desc }}</p>
            <span class="entry-cta">前往查詢 <span aria-hidden="true">→</span></span>
          </router-link>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.page-head {
  display: grid;
  gap: 4px;
}
.subtitle {
  margin: 0;
  font-size: var(--fs-sm);
}

.account-strip {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(min(280px, 100%), 1fr));
}
.account-item {
  display: grid;
  gap: 4px;
  min-width: 0;
}
.account-title {
  font-weight: 700;
  font-size: var(--fs-sm);
}
.account-detail {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 14px;
  font-size: var(--fs-sm);
}
.account-detail strong {
  color: var(--text);
  font-weight: 600;
}

.structure-grid {
  display: grid;
  gap: var(--gap);
  grid-template-columns: minmax(0, 1fr);
}
@media (min-width: 900px) {
  .structure-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
.structure-grid > * {
  min-width: 0;
}

.is-current {
  background: var(--surface-2);
}
.current-tag {
  display: inline-block;
  margin-left: 6px;
  padding: 1px 6px;
  border-radius: 999px;
  font-size: var(--fs-xs);
  font-weight: 600;
  background: var(--accent);
  color: var(--accent-contrast);
  vertical-align: middle;
}

.entries-section {
  display: grid;
  gap: 12px;
}
.section-title {
  font-size: var(--fs-lg);
}
.entry-grid {
  display: grid;
  gap: var(--gap);
  grid-template-columns: repeat(auto-fit, minmax(min(240px, 100%), 1fr));
}
.entry-card {
  display: grid;
  gap: 8px;
  text-decoration: none;
  color: var(--text);
  transition: border-color 0.15s ease, transform 0.15s ease;
  min-width: 0;
}
.entry-card:hover {
  border-color: var(--accent);
  transform: translateY(-1px);
}
.entry-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.entry-title {
  font-size: var(--fs-md);
  color: var(--text);
}
.entry-badge {
  font-size: var(--fs-xs);
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text-muted);
  white-space: nowrap;
}
.entry-desc {
  margin: 0;
  font-size: var(--fs-sm);
}
.entry-cta {
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--accent);
}
</style>
