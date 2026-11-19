/** drill-down 路徑與 URL query 的轉換：節點 id 以「;」串接（id 內不會出現 ;） */
export const encodePath = (ids: string[]): string | undefined => (ids.length ? ids.join(";") : undefined);

export const decodePath = (v: unknown): string[] => {
  const s = Array.isArray(v) ? v[0] : v;
  return typeof s === "string" && s ? s.split(";").filter(Boolean) : [];
};

export const firstQuery = (v: unknown): string | undefined => {
  const s = Array.isArray(v) ? v[0] : v;
  return typeof s === "string" ? s : undefined;
};
