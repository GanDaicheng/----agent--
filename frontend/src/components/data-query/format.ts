/**
 * 结果值的展示格式化。
 *
 * 纯函数模块：不碰 React、不碰网络，因此表格和图表可以共用同一套口径，
 * 不会出现「表格显示 ¥1,234.56、图里显示 1234.56」这种不一致。
 *
 * 值本身来自后端，属于不可信数据——这里只做字符串转换，从不生成 HTML。
 */

import type { ValueFormat } from "@/lib/api/agent-data-query";

const numberFormatter = new Intl.NumberFormat("zh-CN", {
  maximumFractionDigits: 2,
});

const currencyFormatter = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  maximumFractionDigits: 2,
});

/** 坐标轴刻度用的紧凑格式，避免长数字把轴挤爆。 */
const compactFormatter = new Intl.NumberFormat("zh-CN", {
  notation: "compact",
  maximumFractionDigits: 1,
});

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * 把值解析成有限数值，解析不了返回 null。
 *
 * 图表用它判断「能不能画」：null 就意味着必须安全降级，
 * 绝不能把 NaN 当成 0 画进图里。
 */
export function toFiniteNumber(value: unknown): number | null {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

/**
 * 按建议的格式渲染一个值。
 *
 * 认不出来的一律按普通字符串安全展示，绝不猜格式：
 * 猜错的后果是数字看起来合理但含义完全不同，比不格式化更糟。
 */
export function formatValue(value: unknown, format: ValueFormat | null): string {
  if (value === null || value === undefined) {
    return "—";
  }

  if (typeof value === "boolean") {
    return value ? "是" : "否";
  }

  const numeric = typeof value === "number" ? value : null;
  if (numeric !== null && Number.isFinite(numeric)) {
    if (format === "currency") return currencyFormatter.format(numeric);
    // percent 在后端按 0~1 的小数存放，展示时由前端决定乘 100
    if (format === "percent") return `${numberFormatter.format(numeric * 100)}%`;
    return numberFormatter.format(numeric);
  }

  if (typeof value === "string") {
    return value;
  }

  if (isRecord(value) || Array.isArray(value)) {
    try {
      return JSON.stringify(value);
    } catch {
      return "（无法展示的值）";
    }
  }

  return String(value);
}

/** 轴标签：数值走紧凑格式，其他类型按普通文本。 */
export function formatAxisValue(value: number): string {
  return compactFormatter.format(value);
}

/** 横轴类目标签：空值给一个占位符，避免出现空白格子。 */
export function formatCategoryLabel(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "（空）";
  }
  return String(value);
}
