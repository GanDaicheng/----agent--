"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  RAG_DEFAULT_TOP_K,
  RagAnswerError,
  askKnowledge,
  isAbortError,
  type RagAnswerResponse,
} from "@/lib/api/rag-answer";

import { KnowledgeAnswerPanel } from "./KnowledgeAnswerPanel";
import { KnowledgeQuestionInput } from "./KnowledgeQuestionInput";
import styles from "./knowledge-qa.module.css";

/** 一次提问的完整状态。用有限状态而不是几个布尔量，避免出现「既在加载又已出错」。 */
type Phase = "idle" | "loading" | "done" | "cancelled" | "failed";

const FALLBACK_ERROR = "知识库问答请求失败，请稍后重试。";

type Props = {
  /** 示例问题由页面（服务端组件）传入，保持它可序列化。 */
  examples: readonly string[];
};

/**
 * 知识库问答工作台：本页唯一持有状态的组件。
 *
 * 它是「use client」的边界——输入区、加载态、回答区都在客户端这棵树里，
 * 而页头、边界说明、示例清单这些静态内容留在服务端组件里，不进客户端包。
 *
 * 页面首次打开**不发起任何请求**：没有任何 effect 会去调接口，
 * 只有用户点击「提问」才会发出去。这一点对本页比对问数页更重要——
 * 每次提问都要花一次 embedding 调用和一次模型调用。
 */
export function KnowledgeQaWorkspace({ examples }: Props) {
  const [question, setQuestion] = useState("");
  const [topK, setTopK] = useState<number>(RAG_DEFAULT_TOP_K);
  const [phase, setPhase] = useState<Phase>("idle");
  const [result, setResult] = useState<RagAnswerResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  /** 在途请求的取消句柄。同一时刻只允许有一个请求。 */
  const abortRef = useRef<AbortController | null>(null);

  // 组件卸载时取消在途请求：否则请求回来时还对着已卸载的组件写状态
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const busy = phase === "loading";

  const handleSubmit = useCallback(async () => {
    const trimmed = question.trim();

    // 按钮在空白/超长时本来就是禁用的，这里再判一次是纵深防御：
    // 键盘快捷键和按钮走的是同一条路径，不能只靠 disabled 属性把关
    if (trimmed.length === 0) {
      return;
    }

    // 上一笔还没回来就再点一次：先取消旧的，避免两个响应互相覆盖
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setPhase("loading");
    setResult(null);
    setErrorMessage(null);

    try {
      const response = await askKnowledge(trimmed, topK, controller.signal);
      setResult(response);
      setPhase("done");
    } catch (error) {
      if (isAbortError(error)) {
        // 取消是用户的正常操作，不是错误：不进红色报警分支
        setPhase("cancelled");
        return;
      }
      setErrorMessage(
        error instanceof RagAnswerError ? error.message : FALLBACK_ERROR,
      );
      setPhase("failed");
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
      }
    }
  }, [question, topK]);

  const handleCancel = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const handleClear = useCallback(() => {
    // 清空是「回到刚打开页面」的状态：输入、结果、错误、加载全部重置
    setQuestion("");
    setResult(null);
    setErrorMessage(null);
    setPhase("idle");
  }, []);

  return (
    <div className={styles.page}>
      <KnowledgeQuestionInput
        value={question}
        onChange={setQuestion}
        onSubmit={() => {
          void handleSubmit();
        }}
        onClear={handleClear}
        busy={busy}
        topK={topK}
        onTopKChange={setTopK}
        examples={examples}
      />

      {busy ? (
        <div className={styles.loading} role="status" aria-live="polite">
          <span className={styles.spinner} aria-hidden="true" />
          <span>正在检索知识库并生成回答…</span>
          <button
            type="button"
            className={`${styles.button} ${styles.secondary}`}
            onClick={handleCancel}
          >
            取消
          </button>
        </div>
      ) : null}

      {phase === "cancelled" ? (
        <p className={styles.notice} data-tone="cancelled" role="status">
          <span className={styles.noticeTag}>已取消</span>
          本次提问已取消。可以修改问题后重新提交。
        </p>
      ) : null}

      {phase === "failed" && errorMessage ? (
        <p className={styles.notice} data-tone="error" role="alert">
          <span className={styles.noticeTag}>请求失败</span>
          {errorMessage}
        </p>
      ) : null}

      {/* 初始态：还没提问过。刻意不自动填示例、也不自动提交 */}
      {phase === "idle" ? (
        <div className={styles.empty}>
          <p className={styles.emptyTitle}>还没有提问</p>
          <p className={styles.emptyText}>
            输入一个业务口径、指标定义或规则类问题，或者点上面的示例填进输入框。
            <br />
            回答只依据知识库文档；资料不足时会明确说明，不会编造。
          </p>
        </div>
      ) : null}

      {result ? <KnowledgeAnswerPanel result={result} /> : null}
    </div>
  );
}
