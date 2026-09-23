"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/Button";
import { probeHealth, type HealthState } from "@/lib/api/health";
import { isAbortError } from "@/lib/api/http";

import styles from "./ServiceHealthCheck.module.css";

/** 一次探测的状态。unchecked 是页面刚打开、还没点过按钮。 */
type Phase = "unchecked" | "checking" | HealthState;

/**
 * 每种状态对应的文案。
 *
 * **必须是文字，不能只用颜色**：这套状态里有四种「不好」的程度，
 * 红/黄/灰在色觉障碍或黑白打印下分不开，而它们要做的事完全不同
 * （后端没启动 / 数据库没起来 / 端口被别的进程占了）。
 */
const STATE_TEXT: Record<Phase, string> = {
  unchecked: "尚未检测",
  checking: "正在检测…",
  ok: "后端与数据库正常",
  "database-unavailable": "后端正常，数据库不可用",
  unreachable: "无法连接后端",
  unexpected: "响应不符合预期",
};

/** 视觉语气。语义与文案分离，是为了让「加一种状态」只动这两张表。 */
const STATE_TONE: Record<Phase, string> = {
  unchecked: "idle",
  checking: "idle",
  ok: "ok",
  "database-unavailable": "warn",
  unreachable: "bad",
  unexpected: "bad",
};

const timeFormatter = new Intl.DateTimeFormat("zh-CN", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

/**
 * 服务连通性检查。
 *
 * 三件事是刻意这么做的：
 * 1. **只在用户点击时才探测**，不做轮询、不在页面打开时自动探。要不要知道后端活没活着，
 *    由用户决定；持续轮询会把一个「确认一下」变成一个常驻的后台流量和一堆状态闪烁。
 * 2. **探测结果不等于全平台健康**。这个接口只回后端进程与 PostgreSQL 连接两件事，
 *    模型服务和 embedding 服务是外部供应商，后端不探它们。所以文案写「后端与数据库」，
 *    并在 aria-describedby 里把没覆盖到的部分说清楚——不能让人以为这个是「系统全绿」。
 * 3. **503 不是探测失败**，而是探测成功、结果为「数据库不可用」。这一点在
 *    lib/api/health.ts 里已经处理成正常返回值，这里照着显示即可。
 *
 * 另外，这个状态与左侧导航里的「已完成 / 建设中 / 待接入」是两回事：
 * 那是**功能建设进度**（人工维护的配置），这是**本次运行的连通性**（真实探测）。
 * 两者视觉上也刻意做得不一样，避免被当成同一种东西。
 */
export function ServiceHealthCheck() {
  const [phase, setPhase] = useState<Phase>("unchecked");
  const [checkedAt, setCheckedAt] = useState<Date | null>(null);
  const [detail, setDetail] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  // 卸载时取消在途探测，避免响应回来时对着已卸载的组件写状态
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const handleCheck = useCallback(async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setPhase("checking");
    setDetail(null);

    try {
      const probe = await probeHealth(controller.signal);
      setPhase(probe.state);
      setDetail(probe.detail);
      setCheckedAt(new Date());
    } catch (error) {
      if (isAbortError(error)) {
        // 用户又点了一次：让新的那次探测去写状态，这里什么都不做
        return;
      }
      setPhase("unreachable");
      setCheckedAt(new Date());
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
      }
    }
  }, []);

  const checking = phase === "checking";

  return (
    <div className={styles.health}>
      <span className={styles.label} id="health-label">
        后端与数据库
      </span>

      <span
        className={styles.state}
        data-tone={STATE_TONE[phase]}
        role="status"
        aria-live="polite"
        aria-labelledby="health-label"
        aria-describedby="health-scope"
      >
        <span className={styles.dot} aria-hidden="true" />
        {STATE_TEXT[phase]}
      </span>

      {detail ? <span className={styles.detail}>{detail}</span> : null}

      {checkedAt ? (
        <span className={styles.time}>
          检测于 {timeFormatter.format(checkedAt)}
        </span>
      ) : null}

      <Button
        variant="secondary"
        onClick={() => {
          void handleCheck();
        }}
        disabled={checking}
        className={styles.action}
      >
        {checking ? "检测中…" : checkedAt ? "重新检测" : "检查服务"}
      </Button>

      {/* 读屏用户需要知道这次检测的边界；视觉上这句太长，放顶栏会挤爆 */}
      <span className={styles.srOnly} id="health-scope">
        此项只检测后端进程与 PostgreSQL 连接是否可用，不包含模型服务与 embedding
        服务——那两个是外部供应商提供的，后端不检测它们。检测结果也不代表各模块的建设进度。
      </span>
    </div>
  );
}
