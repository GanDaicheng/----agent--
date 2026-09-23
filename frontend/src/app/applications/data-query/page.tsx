import type { Metadata } from "next";

import { PageHeader } from "@/components/ui/PageHeader";
import { DataQueryWorkspace } from "@/components/data-query/DataQueryWorkspace";
import { getModule, getSection, RETAIL_DATA_NOTE } from "@/features/platform/platform-config";

const SECTION_ID = "applications";
const MODULE_SLUG = "data-query";

export const metadata: Metadata = {
  title: "智能问数",
  description: "用自然语言查询零售样例数据，生成分析结论和图表建议。",
};

/**
 * 示例问题。
 *
 * 定义在服务端组件里、以 props 传给客户端工作台——数组是可序列化的，
 * 不会把整份配置或函数带进客户端包。
 *
 * 两条挑选原则：
 * 1. **写明年份与范围**。样例数据只覆盖 2025 全年，问「最近六个月」时
 *    用户心里的「最近」是今天往前数，而数据里根本没有 2026 年的行，
 *    结果会是一个看起来像 bug 的空结果。写死 2025 就不会有这种误会。
 * 2. 只放**当前安全策略真的能算出来**的问题。受控查询只允许单条 SELECT，
 *    函数限定在 COUNT / SUM / AVG / MIN / MAX，并且明确拒绝 CASE 与子查询
 *    （已实测：`HAVING` 放行，`CASE` 报「使用了不允许的 SQL 函数」，
 *    子查询报「禁止使用子查询」）。
 *    所以像「复购率」这种要算「下单次数大于 1 的客户数 ÷ 全部客户数」的比值，
 *    在这套限制下表达不出来——它要么需要条件计数（CASE），要么需要子查询。
 *    指标目录里登记了它，但问数答不了，不放进示例免得用户点了就撞墙。
 *
 * 点击示例只填入输入框，不自动提交：每次提问都会真实调用模型服务，
 * 不能因为一次误点就花掉一次调用。
 */
const EXAMPLES = [
  "2025 年各月销售额趋势怎么样？",
  "2025 年销售额最高的 10 个商品是哪些？",
  "不同区域的销售额和订单数有什么差异？",
  "各商品品类的销售额分别是多少？",
] as const;

/**
 * 智能问数页面。
 *
 * 路由文件刻意保持很薄：只负责页头、边界说明和示例清单这些静态内容，
 * 交互与取数全部交给 DataQueryWorkspace（客户端组件）。
 * 这样绝大部分内容仍然是服务端渲染的。
 */
export default function Page() {
  const section = getSection(SECTION_ID);
  const moduleConfig = getModule(SECTION_ID, MODULE_SLUG);

  return (
    <article>
      <PageHeader
        sectionName={section?.name ?? "智能应用"}
        title="智能问数"
        subtitle="用自然语言查询零售样例数据，生成分析结论和图表建议。"
        boundary={
          <>
            {/* 边界说明放在最顶上：用户提交的内容会被送到模型服务，
                这件事必须在动手输入之前就讲清楚 */}
            <p>
              当前为本地零售样例数据，<strong>覆盖 2025 全年</strong>。
              提问时请写明具体年份或月份，「最近几个月」在样例数据上会查不到东西。
              提交问题会调用模型服务，不适合输入敏感信息。
            </p>
            <p>{RETAIL_DATA_NOTE}</p>
            {moduleConfig?.notice ? <p>{moduleConfig.notice}</p> : null}
          </>
        }
      />

      <DataQueryWorkspace examples={EXAMPLES} />
    </article>
  );
}
