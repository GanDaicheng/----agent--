"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import { Notice } from "@/components/ui/Notice";
import { isAbortError } from "@/lib/api/http";
import {
  createAnonymousUserId,
  loadAnalysisThread,
  loadAnalysisThreads,
  loadUserPreferences,
  runBusinessAnalysis,
  type BusinessAnalysisEvent,
} from "@/lib/api/business-analysis";

import { AnalysisEventTimeline } from "@/components/business-analysis/AnalysisEventTimeline";
import { AnalysisMessageList } from "@/components/business-analysis/AnalysisMessageList";
import { AnalysisReportPanel } from "@/components/business-analysis/AnalysisReportPanel";
import { AnalysisThreadList } from "@/components/business-analysis/AnalysisThreadList";
import styles from "./business-analysis.module.css";

type Phase = "idle" | "running" | "done" | "cancelled" | "failed";
type Message = { role: "user" | "assistant"; content: string };
type Thread = { id: string; title: string; updatedAt: string };

const EXAMPLES = [
  "分析华东地区第三季度销售下降原因，找出影响最大的品类，并结合促销规则给出建议。",
  "对比华东和华南的会员复购率，解释差异并给出提升建议。",
  "分析今年销售额的季节性变化，结合促销日历判断可能原因。",
];

function newThread(): Thread {
  return {
    id: crypto.randomUUID(),
    title: "新的经营分析",
    updatedAt: new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }),
  };
}

export function BusinessAnalysisWorkspace() {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [activeThread, setActiveThread] = useState<Thread>(() => newThread());
  const [messages, setMessages] = useState<Message[]>([]);
  const [events, setEvents] = useState<BusinessAnalysisEvent[]>([]);
  const [report, setReport] = useState("");
  const [question, setQuestion] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [preferenceHint, setPreferenceHint] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const userId = useMemo(() => createAnonymousUserId(), []);

  useEffect(() => () => abortRef.current?.abort(), []);

  useEffect(() => {
    void loadUserPreferences(userId)
      .then((preferences) => {
        const region = preferences.preferred_region;
        if (typeof region === "string" && region) setPreferenceHint(`已加载偏好：${region}`);
      })
      .catch(() => undefined);
  }, [userId]);

  useEffect(() => {
    void loadAnalysisThreads(userId)
      .then((items) => {
        setThreads(items.map((item) => ({
          id: item.thread_id,
          title: item.title,
          updatedAt: item.updated_at
            ? new Date(item.updated_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })
            : "历史会话",
        })));
      })
      .catch(() => undefined);
  }, [userId]);

  const handleEvent = useCallback((event: BusinessAnalysisEvent) => {
    setEvents((current) => [...current, event]);
    if (event.type === "report_delta") setReport((current) => current + event.content);
    if (event.type === "error") {
      setError("经营分析没有完成，请查看执行过程或稍后重试。");
      setPhase("failed");
    }
    if (event.type === "run_completed") setPhase("done");
  }, []);

  const submit = useCallback(async () => {
    const message = question.trim();
    if (!message || phase === "running") return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setPhase("running");
    setError(null);
    setReport("");
    setEvents([]);
    setMessages((current) => [...current, { role: "user", content: message }]);
    setQuestion("");
    const thread = { ...activeThread, title: message.slice(0, 28), updatedAt: new Date().toLocaleTimeString("zh-CN") };
    setActiveThread(thread);
    setThreads((current) => [thread, ...current.filter((item) => item.id !== thread.id)]);
    try {
      await runBusinessAnalysis(
        { threadId: thread.id, message, userId },
        controller.signal,
        handleEvent,
      );
      setMessages((current) => [...current, { role: "assistant", content: "分析任务已完成，请查看右侧报告。" }]);
    } catch (requestError) {
      if (isAbortError(requestError)) setPhase("cancelled");
      else {
        setPhase("failed");
        setError(requestError instanceof Error ? requestError.message : "经营分析请求失败。");
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
    }
  }, [activeThread, handleEvent, phase, question, userId]);

  const selectThread = useCallback(async (thread: Thread) => {
    if (phase === "running") return;
    setActiveThread(thread);
    setMessages([]);
    setEvents([]);
    setReport("");
    setError(null);
    setPhase("idle");
    try {
      const runs = await loadAnalysisThread(thread.id);
      if (runs.length > 0) {
        const latest = runs[0];
        const restoredReport = latest.report?.summary;
        if (typeof restoredReport === "string" && restoredReport) setReport(restoredReport);
        setMessages([
          { role: "user", content: latest.title },
          {
            role: "assistant",
            content: `已恢复该会话，共 ${runs.length} 次分析任务；最近一次状态：${latest.status}。`,
          },
        ]);
      }
    } catch {
      setError("历史会话读取失败，但仍可继续发起新的分析。");
    }
  }, [phase]);

  const cancel = useCallback(() => abortRef.current?.abort(), []);
  const startNew = useCallback(() => {
    abortRef.current?.abort();
    setActiveThread(newThread());
    setMessages([]);
    setEvents([]);
    setReport("");
    setQuestion("");
    setError(null);
    setPhase("idle");
  }, []);

  return (
    <section className={styles.workspace} aria-label="AI 经营分析工作台">
      <AnalysisThreadList
        threads={threads}
        activeId={activeThread.id}
        onNew={startNew}
        onSelect={(thread) => void selectThread(thread)}
      />
      <div className={styles.mainColumn}>
        <div className={styles.promptCard}>
          <label htmlFor="business-analysis-question">经营分析目标</label>
          <textarea
            id="business-analysis-question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if ((event.ctrlKey || event.metaKey) && event.key === "Enter") void submit();
            }}
            placeholder="例如：分析华东第三季度销售下降原因，并结合促销规则给出建议"
            rows={3}
            disabled={phase === "running"}
          />
          <div className={styles.promptActions}>
            <button type="button" onClick={() => void submit()} disabled={!question.trim() || phase === "running"}>
              {phase === "running" ? "分析中…" : "开始分析"}
            </button>
            {phase === "running" ? <button type="button" className={styles.secondaryButton} onClick={cancel}>停止</button> : null}
          </div>
          <div className={styles.exampleRow}>
            {EXAMPLES.map((example) => <button key={example} type="button" onClick={() => setQuestion(example)}>{example.slice(0, 18)}…</button>)}
          </div>
        </div>

        {error ? <Notice tone="danger" tag="分析失败">{error}</Notice> : null}
        {phase === "cancelled" ? <Notice tone="neutral" tag="已停止">本次分析已停止，可以修改问题后重新提交。</Notice> : null}
        {messages.length === 0 && phase === "idle" ? <EmptyState title="还没有经营分析任务">输入一个需要多步拆解的业务问题，Agent 会自主调用数据和知识工具。</EmptyState> : null}
        <AnalysisMessageList messages={messages} />
        {report ? <AnalysisReportPanel report={report} /> : null}
      </div>
      <aside className={styles.sideColumn}>
        <div className={styles.sideHeader}><span>Agent 执行过程</span><span className={styles.eventCount}>{events.length} 个事件</span></div>
        <AnalysisEventTimeline events={events} />
        <div className={styles.sideNote}>数据查询由现有安全问数工作流执行，知识规则来自 pgvector 知识库。{preferenceHint ? ` ${preferenceHint}` : ""}</div>
      </aside>
    </section>
  );
}
