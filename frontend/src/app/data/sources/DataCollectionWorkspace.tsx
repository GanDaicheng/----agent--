"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  RAG_DOCUMENT_SUPPORTED_EXTENSIONS,
  RAG_DOCUMENT_TITLE_MAX_LENGTH,
  RagDocumentsError,
  describeUploadRejection,
  isAbortError,
  listDocuments,
  uploadDocument,
  type RagDocumentSummary,
  type RagDocumentUploadResult,
} from "@/lib/api/rag-documents";

import styles from "./data-collection.module.css";

/** 一次上传的完整状态。用有限状态而不是几个布尔量，避免出现「既在上传又已完成」。 */
type UploadPhase = "idle" | "uploading" | "done" | "cancelled" | "failed";

/** 文档列表的状态。与上传是两条独立的异步流程，所以分开管。 */
type ListPhase = "idle" | "loading" | "done" | "failed";

const FALLBACK_UPLOAD_ERROR = "上传失败，请稍后重试。";
const FALLBACK_LIST_ERROR = "无法获取文档列表，请稍后重试。";

/**
 * 时间戳格式化。
 *
 * 解析不了就**原样显示**字符串，绝不显示 "Invalid Date"——那会让人以为
 * 数据坏了；原样显示至少还能看出后端给的是什么。
 */
const timestampFormatter = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

function formatTimestamp(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return timestampFormatter.format(parsed);
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

/**
 * 把入库结果说成人话。
 *
 * skip 这一支尤其要讲清楚：用户看到「什么都没发生」时的第一反应是
 * 「是不是没成功」，而真相是幂等生效、一分钱都没多花。
 * switch 覆盖了全部三种 action，将来后端加新动作时 TypeScript 会在这里报缺分支。
 */
function describeAction(result: RagDocumentUploadResult): string {
  switch (result.action) {
    case "insert":
      return `已作为新文档入库，切出 ${result.chunk_count} 个切片，本次计算了 ${result.embedded_chunks} 条向量。`;
    case "update":
      return `内容有变化，已更新为 ${result.chunk_count} 个切片，其中 ${result.embedded_chunks} 条重算了向量。`;
    case "skip":
      return `与库中已有内容完全一致，没有重复入库（${result.chunk_count} 个切片，未消耗向量计算）。`;
  }
}

/**
 * 数据采集工作台：本页唯一持有状态的组件。
 *
 * 它是「use client」的边界——上传区、状态提示、文档列表都在客户端这棵树里，
 * 而页头、边界说明这些静态内容留在服务端组件里，不进客户端包。
 *
 * **页面打开时不发任何请求**，与「智能问数」「知识问答」两页保持同一约定：
 * 什么时候读、什么时候写，都由用户的动作决定。文档列表要点「读取列表」，
 * 上传成功后会自动刷新一次。
 */
export function DataCollectionWorkspace() {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");

  const [uploadPhase, setUploadPhase] = useState<UploadPhase>("idle");
  const [uploadResult, setUploadResult] = useState<RagDocumentUploadResult | null>(null);
  const [uploadError, setUploadError] = useState<{ kind: string; message: string } | null>(
    null,
  );

  const [listPhase, setListPhase] = useState<ListPhase>("idle");
  const [documents, setDocuments] = useState<RagDocumentSummary[]>([]);
  const [listError, setListError] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  /** 在途请求的取消句柄。上传与列表各一个，互不干扰。 */
  const uploadAbortRef = useRef<AbortController | null>(null);
  const listAbortRef = useRef<AbortController | null>(null);

  const uploading = uploadPhase === "uploading";

  /**
   * 读取文档列表。
   *
   * 只在用户点击、或上传成功之后调用——**页面打开时不自动读**。
   * 这与「智能问数」「知识问答」两页是同一条约定：进页面不产生任何网络请求，
   * 什么时候读由用户决定。
   */
  const refreshList = useCallback(async () => {
    listAbortRef.current?.abort();
    const controller = new AbortController();
    listAbortRef.current = controller;

    setListPhase("loading");
    setListError(null);

    try {
      const response = await listDocuments(controller.signal);
      setDocuments(response.documents);
      setListPhase("done");
    } catch (error) {
      if (isAbortError(error)) {
        // 取消不是失败：不写错误状态，保持原样
        return;
      }
      setListError(
        error instanceof RagDocumentsError ? error.message : FALLBACK_LIST_ERROR,
      );
      setListPhase("failed");
    } finally {
      if (listAbortRef.current === controller) {
        listAbortRef.current = null;
      }
    }
  }, []);

  // 这个 effect 只做一件事：卸载时取消在途请求，
  // 否则响应回来时还对着已卸载的组件写状态。
  useEffect(() => {
    return () => {
      listAbortRef.current?.abort();
      uploadAbortRef.current?.abort();
    };
  }, []);

  const handlePick = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    const picked = event.target.files?.[0] ?? null;
    setFile(picked);
    // 清掉 input 的值，否则用户再选同一个文件时 change 事件不会触发
    event.target.value = "";

    // 换了文件就把上一次的结果清掉：留着会让人以为那是刚选这个文件的结果
    setUploadPhase("idle");
    setUploadResult(null);
    setUploadError(null);
  }, []);

  const handleUpload = useCallback(async () => {
    if (!file) return;

    // 本地校验在按钮禁用之外再判一次：快捷键和程序化触发走的是同一条路径
    const rejection = describeUploadRejection(file);
    if (rejection) return;

    uploadAbortRef.current?.abort();
    const controller = new AbortController();
    uploadAbortRef.current = controller;

    setUploadPhase("uploading");
    setUploadResult(null);
    setUploadError(null);

    try {
      const result = await uploadDocument(file, title, controller.signal);
      setUploadResult(result);
      setUploadPhase("done");
      // 入库改变了库里的内容，列表必须重新拉一次才对得上
      await refreshList();
    } catch (error) {
      if (isAbortError(error)) {
        setUploadPhase("cancelled");
        return;
      }
      setUploadError(
        error instanceof RagDocumentsError
          ? { kind: error.kind, message: error.message }
          : { kind: "server", message: FALLBACK_UPLOAD_ERROR },
      );
      setUploadPhase("failed");
    } finally {
      if (uploadAbortRef.current === controller) {
        uploadAbortRef.current = null;
      }
    }
  }, [file, title, refreshList]);

  const handleCancel = useCallback(() => {
    uploadAbortRef.current?.abort();
  }, []);

  const localRejection = file ? describeUploadRejection(file) : null;
  const canUpload = Boolean(file) && !uploading && !localRejection;
  const titleTooLong = title.length > RAG_DOCUMENT_TITLE_MAX_LENGTH;

  return (
    <div className={styles.page}>
      <section className={styles.card}>
        <h2 className={styles.cardTitle}>导入知识文档</h2>
        <p className={styles.cardCaption}>
          选择一份 {RAG_DOCUMENT_SUPPORTED_EXTENSIONS.join(" / ")} 文件，
          系统会自动提取文本、切片、向量化并写入 RAG 知识库，
          之后就能在「知识问答」里被检索到。
          <br />
          docx / pdf 会先被还原成带标题层级的文本再切片，效果与手写 Markdown 一致。
          同一份文件重复上传是安全的：内容没变时不会重复入库，也不会重复消耗向量计算。
        </p>

        <div className={styles.fileRow}>
          <label className={styles.fileLabel} htmlFor="knowledge-file">
            选择文件
          </label>
          <input
            ref={fileInputRef}
            id="knowledge-file"
            className={styles.visuallyHidden}
            type="file"
            accept={RAG_DOCUMENT_SUPPORTED_EXTENSIONS.join(",")}
            onChange={handlePick}
            disabled={uploading}
          />

          {file ? (
            <span className={styles.picked}>
              <span className={styles.fileName}>{file.name}</span>
              <span className={styles.fileSize}>{formatFileSize(file.size)}</span>
            </span>
          ) : (
            <span className={styles.picked}>还没有选择文件</span>
          )}
        </div>

        {localRejection ? (
          <p className={styles.validation} role="alert">
            {localRejection}
          </p>
        ) : null}

        <div className={styles.field}>
          <label className={styles.hint} htmlFor="knowledge-title">
            文档标题（可不填）
          </label>
          <input
            id="knowledge-title"
            className={styles.textInput}
            type="text"
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            placeholder="留空则使用文档自身的一级标题；仍没有就退回文件名"
            maxLength={RAG_DOCUMENT_TITLE_MAX_LENGTH + 50}
            disabled={uploading}
          />
          <div className={styles.inputMeta}>
            <span>标题会参与检索上下文，写清楚一点召回更准。</span>
            <span className={styles.counter} data-over={titleTooLong}>
              {title.length} / {RAG_DOCUMENT_TITLE_MAX_LENGTH}
            </span>
          </div>
        </div>

        <div className={styles.actions}>
          <button
            type="button"
            className={`${styles.button} ${styles.primary}`}
            onClick={() => {
              void handleUpload();
            }}
            disabled={!canUpload}
          >
            {uploading ? "正在入库…" : "上传并入库"}
          </button>
          {uploading ? (
            <button
              type="button"
              className={`${styles.button} ${styles.secondary}`}
              onClick={handleCancel}
            >
              取消
            </button>
          ) : null}
        </div>

        {uploading ? (
          <div className={styles.loading} role="status" aria-live="polite">
            <span className={styles.spinner} aria-hidden="true" />
            <span>正在切片、计算向量并写入知识库，请稍候…</span>
          </div>
        ) : null}

        {uploadPhase === "cancelled" ? (
          <p className={styles.notice} data-tone="cancelled" role="status">
            <span className={styles.noticeTag}>已取消</span>
            本次上传已取消。已入库的部分不会留下半截记录，可以重新选择文件再试。
          </p>
        ) : null}

        {uploadPhase === "done" && uploadResult ? (
          <p className={styles.notice} data-tone="success" role="status">
            <span className={styles.noticeTag}>入库完成</span>
            <span>
              <strong>{uploadResult.source_file}</strong>：{describeAction(uploadResult)}
            </span>
          </p>
        ) : null}

        {uploadPhase === "failed" && uploadError ? (
          <p
            className={styles.notice}
            // 「文件被拒绝」是用户自己能修的，用琥珀色；服务故障才是红色。
            // 两种都带文字标签，不靠颜色单独表达。
            data-tone={uploadError.kind === "rejected" ? "rejected" : "error"}
            role="alert"
          >
            <span className={styles.noticeTag}>
              {uploadError.kind === "rejected" ? "文件未通过检查" : "入库失败"}
            </span>
            {uploadError.message}
          </p>
        ) : null}
      </section>

      <section className={styles.card}>
        <div className={styles.cardHead}>
          <h2 className={styles.cardTitle}>知识库文档</h2>
          <button
            type="button"
            className={`${styles.button} ${styles.secondary}`}
            onClick={() => {
              void refreshList();
            }}
            disabled={listPhase === "loading"}
          >
            {listPhase === "idle" ? "读取列表" : "刷新"}
          </button>
        </div>
        <p className={styles.cardCaption}>
          当前知识库里已有的文档。列表只显示文档级信息，不显示切片正文。
        </p>

        {listPhase === "idle" ? (
          <div className={styles.empty}>
            <p className={styles.emptyTitle}>还没有读取文档列表</p>
            <p className={styles.emptyText}>
              点上面的「读取列表」查看知识库里已经有哪些文档。
              <br />
              上传成功后列表会自动刷新，不必手动点。
            </p>
          </div>
        ) : null}

        {listPhase === "loading" ? (
          <div className={styles.loading} role="status" aria-live="polite">
            <span className={styles.spinner} aria-hidden="true" />
            <span>正在读取文档列表…</span>
          </div>
        ) : null}

        {listPhase === "failed" && listError ? (
          <p className={styles.notice} data-tone="error" role="alert">
            <span className={styles.noticeTag}>读取失败</span>
            {listError}
          </p>
        ) : null}

        {listPhase === "done" && documents.length === 0 ? (
          <div className={styles.empty}>
            <p className={styles.emptyTitle}>知识库还是空的</p>
            <p className={styles.emptyText}>
              在上面选一份 Markdown 或纯文本文件上传，它就会出现在这里。
              <br />
              入库后可以到「知识问答」页提问，验证它是否真的能被检索到。
            </p>
          </div>
        ) : null}

        {documents.length > 0 ? (
          <ul className={styles.docList}>
            {documents.map((document) => (
              <li key={document.source_file} className={styles.docItem}>
                <div className={styles.docHead}>
                  <span className={styles.docTitle}>{document.document_title}</span>
                  <span className={styles.docFile}>{document.source_file}</span>
                </div>
                <div className={styles.docMeta}>
                  <span>
                    <span className={styles.chunkBadge}>{document.chunk_count}</span> 个切片
                  </span>
                  <span className={styles.timestamp}>
                    更新于 {formatTimestamp(document.updated_at)}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    </div>
  );
}
