import type {
  ChartSuggestion,
  QueryResult,
  ValueFormat,
} from "@/lib/api/agent-data-query";

import {
  formatAxisValue,
  formatCategoryLabel,
  formatValue,
  toFiniteNumber,
} from "./format";
import styles from "./data-query.module.css";

// SVG 画布尺寸。用 viewBox + width:100% 让它跟着容器缩放，
// 不需要 JS 测宽，也就不会在服务端渲染时碰到 window。
const WIDTH = 720;
const HEIGHT = 300;
const PAD = { top: 16, right: 24, bottom: 40, left: 80 };
const Y_TICK_COUNT = 4;
/** 横轴最多显示多少个标签，超过就隔几个显示一个，避免文字叠在一起。 */
const MAX_X_LABELS = 12;

type Props = {
  result: QueryResult;
  suggestion: ChartSuggestion | null;
};

type Point = {
  label: string;
  value: number;
};

/**
 * 按图表建议把结果画出来。
 *
 * 三条铁律：
 * 1. **只读** query_result.rows 和 chart_suggestion，不猜字段、不改数据；
 * 2. 任何一步对不上就安全降级为「只显示下方明细表」，绝不画一张编出来的图；
 * 3. 图表是明细表的补充，不是替代——表格始终在旁边，图看不了还有底稿。
 */
export function ResultChart({ result, suggestion }: Props) {
  const notice = evaluate(result, suggestion);

  if (notice.kind === "notice") {
    return (
      <div>
        <p className={styles.notice} data-tone="empty">
          <span className={styles.noticeTag}>提示</span>
          {notice.text}
        </p>
        {suggestion ? (
          <p className={styles.chartReason}>
            图表建议依据：{suggestion.reason}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div>
      <p className={styles.chartTitle}>{suggestion?.title}</p>
      <p className={styles.chartReason}>
        图表建议依据：{suggestion?.reason}
      </p>
      {notice.type === "line" ? (
        <LineChart points={notice.points} format={notice.format} />
      ) : (
        <BarChart points={notice.points} format={notice.format} />
      )}
    </div>
  );
}

type Decision =
  | { kind: "chart"; type: "line" | "bar"; points: Point[]; format: ValueFormat | null }
  | { kind: "notice"; text: string };

/**
 * 决定「画什么」或「为什么不画」。
 *
 * 单独抽成纯函数，是为了让每一层降级都能被单独推理：
 * 从上到下依次是「有没有建议 → 是不是要画 → 字段齐不齐 → 数据能不能转成数值」，
 * 任何一层不满足都退到明细表，而不是继续往下硬画。
 */
function evaluate(result: QueryResult, suggestion: ChartSuggestion | null): Decision {
  if (!suggestion) {
    return { kind: "notice", text: "没有收到图表建议，已改为只显示下方明细表。" };
  }

  if (suggestion.chart_type === "none") {
    return { kind: "notice", text: "本次查询没有可绘制的数据。" };
  }

  if (suggestion.chart_type === "table") {
    return {
      kind: "notice",
      text: "当前结果字段不满足受控图表规则，建议查看下方明细表。",
    };
  }

  const { x_field: xField, y_field: yField } = suggestion;

  // 没有维度或度量字段就没法定位坐标，不猜
  if (!xField || !yField) {
    return {
      kind: "notice",
      text: "图表建议没有指明维度或度量字段，已改为只显示下方明细表。",
    };
  }

  // 字段必须真实存在于结果列里，否则前端拿着一个不存在的键去取值只会画出一张空图
  if (!result.columns.includes(xField) || !result.columns.includes(yField)) {
    return {
      kind: "notice",
      text: "图表建议引用的字段不在本次查询结果中，已改为只显示下方明细表。",
    };
  }

  if (result.rows.length === 0) {
    return { kind: "notice", text: "本次查询没有返回数据行。" };
  }

  const points: Point[] = [];
  for (const row of result.rows) {
    const value = toFiniteNumber(row[yField]);
    if (value === null) {
      // 只要有一行的度量不是有限数值，就整张图不画。
      // 悄悄跳过那一行会让图看起来「少了一点」，而看图的人无从知道。
      return {
        kind: "notice",
        text: "结果中含有无法作为数值绘制的行，已改为只显示下方明细表。",
      };
    }
    points.push({ label: formatCategoryLabel(row[xField]), value });
  }

  if (suggestion.chart_type === "line") {
    return { kind: "chart", type: "line", points, format: suggestion.value_format };
  }

  // 柱状图以 0 为基线，负值画不出来。宁可降级也不画一张方向相反的图。
  if (points.some((point) => point.value < 0)) {
    return {
      kind: "notice",
      text: "结果中含有负值，当前柱状图不支持，已改为只显示下方明细表。",
    };
  }

  return { kind: "chart", type: "bar", points, format: suggestion.value_format };
}

/**
 * 折线图。
 *
 * 纵轴用**数据范围**而不是从 0 开始：趋势图的重点是「变化」，
 * 从 0 起会把 14 万到 37 万的差异压成一条直线，等于什么都没说。
 */
function LineChart({ points, format }: { points: Point[]; format: ValueFormat | null }) {
  const values = points.map((point) => point.value);
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const span = rawMax - rawMin;
  // 所有点相同时给一个固定留白，否则 max === min 会导致除零
  const breathing = span === 0 ? Math.max(Math.abs(rawMax) * 0.1, 1) : span * 0.08;
  const min = rawMin - breathing;
  const max = rawMax + breathing;

  const plotWidth = WIDTH - PAD.left - PAD.right;
  const plotHeight = HEIGHT - PAD.top - PAD.bottom;

  const xAt = (index: number) =>
    points.length === 1
      ? PAD.left + plotWidth / 2
      : PAD.left + (index / (points.length - 1)) * plotWidth;
  const yAt = (value: number) =>
    PAD.top + plotHeight - ((value - min) / (max - min)) * plotHeight;

  const polyline = points
    .map((point, index) => `${xAt(index)},${yAt(point.value)}`)
    .join(" ");

  const ticks = Array.from(
    { length: Y_TICK_COUNT },
    (_, index) => min + ((max - min) / (Y_TICK_COUNT - 1)) * index,
  );

  const labelEvery = Math.max(1, Math.ceil(points.length / MAX_X_LABELS));

  return (
    <svg
      className={styles.svgChart}
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      role="img"
      aria-label={`折线图，共 ${points.length} 个数据点，明细见下方表格`}
    >
      {ticks.map((tick) => (
        <g key={tick}>
          <line
            className={styles.gridLine}
            x1={PAD.left}
            x2={WIDTH - PAD.right}
            y1={yAt(tick)}
            y2={yAt(tick)}
          />
          <text
            className={styles.axisText}
            x={PAD.left - 10}
            y={yAt(tick) + 4}
            textAnchor="end"
          >
            {formatAxisValue(tick)}
          </text>
        </g>
      ))}

      <line
        className={styles.axisLine}
        x1={PAD.left}
        x2={WIDTH - PAD.right}
        y1={PAD.top + plotHeight}
        y2={PAD.top + plotHeight}
      />

      <polyline className={styles.linePath} points={polyline} />

      {points.map((point, index) => (
        <g key={`${index}-${point.label}`}>
          <circle
            className={styles.linePoint}
            cx={xAt(index)}
            cy={yAt(point.value)}
            r={3.5}
          >
            {/* SVG 原生 tooltip：鼠标悬停即可看到该点的准确数值 */}
            <title>{`${point.label}：${formatValue(point.value, format)}`}</title>
          </circle>
          {index % labelEvery === 0 ? (
            <text
              className={styles.axisText}
              x={xAt(index)}
              y={PAD.top + plotHeight + 18}
              textAnchor="middle"
            >
              {point.label}
            </text>
          ) : null}
        </g>
      ))}
    </svg>
  );
}

/**
 * 横向柱状图。
 *
 * 用 CSS 而不是 SVG：条形本身就是文本 + 宽度，天然可被读屏软件读到，
 * 长标签还能用 title 属性挂完整名称。
 */
function BarChart({ points, format }: { points: Point[]; format: ValueFormat | null }) {
  const max = Math.max(...points.map((point) => point.value));
  const base = max > 0 ? max : 1;

  return (
    <ul className={styles.barList}>
      {points.map((point, index) => (
        <li key={`${index}-${point.label}`} className={styles.barRow}>
          {/* title 保留完整名称，视觉上超长会被省略号截断 */}
          <span className={styles.barLabel} title={point.label}>
            {point.label}
          </span>
          <span className={styles.barTrack}>
            <span
              className={styles.barFill}
              style={{ width: `${(point.value / base) * 100}%` }}
            />
          </span>
          <span className={styles.barValue}>
            {formatValue(point.value, format)}
          </span>
        </li>
      ))}
    </ul>
  );
}
