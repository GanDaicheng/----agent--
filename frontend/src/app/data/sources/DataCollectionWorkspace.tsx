"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button, LinkButton } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { LoadingIndicator } from "@/components/ui/LoadingIndicator";
import { Notice } from "@/components/ui/Notice";
import {
  RAG_DOCUMENT_SUPPORTED_EXTENSIONS,
  RAG_DOCUMENT_TITLE_MAX_LENGTH,
  RagDocumentsError,
  describeUploadRejection,
  fileExtension,
  listDocuments,
  uploadDocument,
  type RagDocumentSummary,
  type RagDocumentUploadResult,
} from "@/lib/api/rag-documents";
import { isAbortError } from "@/lib/api/http";

import styles from "./data-collection.module.css";

/** 一次上传的完整状态。用有限状态而不是几个布尔量，避免出现「既在上传又已完成」。 */
type UploadPhase = "idle" | "uploading" | "done" | "cancelled" | "failed";

/** 文档列表的状态。与上传是两条独立的异步流程，所以分开管。 */
type ListPhase = "idle" | "loading" | "done" | "failed";

const FALLBACK_UPLOAD_ERROR = "上传失败，请稍后重试。";
const FALLBACK_LIST_ERROR = "无法获取文档列表，请稍后重试。";

/** 格式筛选里代表「不限」的取值。 */
const ALL_FORMATS = "all";

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
 * 从文件名推导出的格式标签。
 *
 * **这是前端的展示值，不是后端确认过的类型。** 后端真正认的类型是它自己按文件名
 * 判断出来的，判断不了会以 422 返回一句面向用户的说明。这里推导只是为了在用户
 * 选完文件后立刻给个反馈，不代表这个文件一定能被入库。
 */
function formatLabelFromName(name: string): string {
  const ext = fileExtension(name);
  return ext ? ext.slice(1).toUpperCase() : "未知格式";
}

/**
 * 把入库结果说成人话。
 *
 * skip 这一支尤其要讲清楚：用户看到「什么都没发生」时的第一反应是
 * 「是不是没成功」，而真相是幂等生效、一分钱都没多花。
 * switch 覆盖了全部三种 action，将来后端加新动作时 TypeScript 会在这里报缺分支。
 *
 * 注意这里只用响应里真实存在的字段。响应**没有** document_title 和 file_type，
 * 所以不能在这句话里提「标题」或「格式」——那只能靠猜。
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
 * 上传成功后会自动刷新一次（那是用户上传操作的延续，不算自动请求）。
 */
export function DataCollectionWorkspace() {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [dragging, setDragging] = useState(false);
  /** 拖入多个文件时的提示。接口一次只收一个文件，多拖的会被忽略。 */
  const [dropNote, setDropNote] = useState<string | null>(null);

  const [uploadPhase, setUploadPhase] = useState<UploadPhase>("idle");
  const [uploadResult, setUploadResult] = useState<RagDocumentUploadResult | null>(null);
  const [uploadError, setUploadError] = useState<{ kind: string; message: string } | null>(
    null,
  );

  const [listPhase, setListPhase] = useState<ListPhase>("idle");
  const [documents, setDocuments] = useState<RagDocumentSummary[]>([]);
  const [listError, setListError] = useState<string | null>(null);

  /** 列表加载完成后的本地筛选条件。不触发任何请求。 */
  const [searchText, setSearchText] = useState("");
  const [formatFilter, setFormatFilter] = useState<string>(ALL_FORMATS);

  const fileInputRef = useRef<HTMLInputElement>(null);
  /** 在途请求的取消句柄。上传与列表各一个，互不干扰。 */
  const uploadAbortRef = useRef<AbortController | null>(null);
  const listAbortRef = useRef<AbortController | null>(null);

  const uploading = uploadPhase === "uploading";

  /**
   * 读取文档列表。
   *
   * 只在用户点击、或上传成功之后调用——**页面打开时不自动读**。
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
      // 换了一批数据，上一次的筛选条件可能筛出空结果，顺手重置回「不限」
      setFormatFilter(ALL_FORMATS);
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

  /**
   * 选中一个文件。
   *
   * 换文件时把上一次的上传结果清掉：留着会让人以为那是刚选这个文件的结果。
   */
  const selectFile = useCallback((picked: File | null) => {
    setFile(picked);
    setDropNote(null);
    setUploadPhase("idle");
    setUploadResult(null);
    setUploadError(null);
  }, []);

  const handlePick = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      selectFile(event.target.files?.[0] ?? null);
      // 清掉 input 的值，否则用户再选同一个文件时 change 事件不会触发
      event.target.value = "";
    },
    [selectFile],
  );

  const handleDragOver = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    // 不拦住默认行为，浏览器不会允许 drop
    event.preventDefault();
    setDragging(true);
  }, []);

  const handleDragLeave = useCallback((event: React.DragEvent<HTMLDivElement>) => {
    // 在子元素之间移动也会触发 dragleave，用 relatedTarget 判断是不是真的离开了整块区域
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
    setDragging(false);
  }, []);

  const handleDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      setDragging(false);

      const dropped = Array.from(event.dataTransfer.files);
      if (dropped.length === 0) return;

      selectFile(dropped[0]);
      // 接口一次只收一个文件，多拖的不静默丢弃，明说
      if (dropped.length > 1) {
        setDropNote(
          `一次只能上传一个文件，已选中「${dropped[0].name}」，其余 ${dropped.length - 1} 个被忽略。`,
        );
      }
    },
    [selectFile],
  );

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

  /** 列表里实际出现过的格式。没有文档时是空的，筛选器也就不渲染。 */
  const availableFormats = useMemo(() => {
    const seen = new Set<string>();
    for (const document of documents) {
      const ext = fileExtension(document.source_file);
      if (ext) seen.add(ext.slice(1).toLowerCase());
    }
    return Array.from(seen).sort();
  }, [documents]);

  /**
   * 本地筛选。搜索同时匹配文档标题与文件名——
   * 用户记得住的往往是其中一个，只搜标题会让「我记得文件名」的人搜不到。
   */
  const filteredDocuments = useMemo(() => {
    const keyword = searchText.trim().toLowerCase();

    return documents.filter((document) => {
      if (formatFilter !== ALL_FORMATS) {
        const ext = fileExtension(document.source_file).slice(1).toLowerCase();
        if (ext !== formatFilter) return false;
      }
      if (!keyword) return true;
      return (
        document.document_title.toLowerCase().includes(keyword) ||
        document.source_file.toLowerCase().includes(keyword)
      );
    });
  }, [documents, searchText, formatFilter]);

  /** 统计只从**本次真实加载到的列表**算出来，不写死、不估算。 */
  const totalChunks = useMemo(
    () => documents.reduce((sum, document) => sum + document.chunk_count, 0),
    [documents],
  );

  const filtering = searchText.trim() !== "" || formatFilter !== ALL_FORMATS;

  return (
    <div className={styles.page}>
      <section className={styles.card}>
        <h2 className={styles.cardTitle}>导入知识文档</h2>
        <p className={styles.cardCaption}>
          支持 {RAG_DOCUMENT_SUPPORTED_EXTENSIONS.join(" / ")}，单个文件不超过 10 MiB。
          系统会自动提取文本、按标题层级切片、计算向量并写入知识库，
          之后就能在「知识问答」里被检索到。
        </p>

        {/* 拖拽与点击选文件是同一个入口的两种操作方式：label 保证键盘可达，
            拖拽只是给鼠标用户的便利，不替代前者。 */}
        <div
          className={styles.dropZone}
          data-dragging={dragging}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <p className={styles.dropHint}>
            把文件拖到这里，或
            <label className={styles.fileLabel} htmlFor="knowledge-file">
              选择文件
            </label>
          </p>
          <input
            ref={fileInputRef}
            id="knowledge-file"
            className={styles.visuallyHidden}
            type="file"
            accept={RAG_DOCUMENT_SUPPORTED_EXTENSIONS.join(",")}
            onChange={handlePick}
            disabled={uploading}
          />
          <p className={styles.dropNote}>
            一次只能上传一个文件。扫描版 PDF（整页是图片、没有文字层）需要 OCR，
            本服务不做，会以「文件内容为空」被拒。
          </p>
        </div>

        {dropNote ? (
          <Notice tone="warning" tag="已忽略多余文件">
            {dropNote}
          </Notice>
        ) : null}

        {file ? (
          <div className={styles.pickedBox}>
            <span className={styles.pickedLabel}>已选择</span>
            <span className={styles.fileName}>{file.name}</span>
            <span className={styles.pickedMeta}>
              格式 {formatLabelFromName(file.name)} · {formatFileSize(file.size)}
            </span>
          </div>
        ) : null}

        {localRejection ? (
          <Notice tone="warning" tag="不能上传" role="alert">
            {localRejection}
          </Notice>
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
          <Button
            variant="primary"
            onClick={() => {
              void handleUpload();
            }}
            disabled={!canUpload}
          >
            {uploading ? "正在入库…" : "上传并入库"}
          </Button>
        </div>

        {uploading ? (
          <LoadingIndicator
            message="正在上传并处理文档…"
            note="后端会解析文件、切片并计算向量。文件越大耗时越久，这个过程没有进度接口，所以不显示百分比。"
            onCancel={handleCancel}
          />
        ) : null}

        {uploadPhase === "cancelled" ? (
          <Notice tone="neutral" tag="已取消">
            已停止等待本次上传的响应。<strong>后端可能仍在处理这个文件</strong>
            ，稍后点「刷新」看列表就能确认它有没有入库。
          </Notice>
        ) : null}

        {uploadPhase === "done" && uploadResult ? (
          <Notice tone="success" tag="入库完成">
            <strong>{uploadResult.source_file}</strong>：{describeAction(uploadResult)}
            <div className={styles.noticeActions}>
              <LinkButton href="/applications/knowledge-qa" variant="secondary">
                前往知识问答验证
              </LinkButton>
            </div>
          </Notice>
        ) : null}

        {uploadPhase === "failed" && uploadError ? (
          <Notice
            // 「文件被拒绝」是用户自己能修的，用琥珀色；服务故障才是红色。
            // 两种都带文字标签，不靠颜色单独表达。
            tone={uploadError.kind === "rejected" ? "warning" : "danger"}
            tag={uploadError.kind === "rejected" ? "文件未通过检查" : "入库失败"}
            role="alert"
          >
            {uploadError.message}
          </Notice>
        ) : null}
      </section>

      <section className={styles.card}>
        <div className={styles.cardHead}>
          <h2 className={styles.cardTitle}>知识库文档</h2>
          <Button
            variant="secondary"
            onClick={() => {
              void refreshList();
            }}
            disabled={listPhase === "loading"}
          >
            {listPhase === "idle" ? "读取列表" : "刷新"}
          </Button>
        </div>
        <p className={styles.cardCaption}>
          当前知识库里已有的文档。列表只显示文档级信息，不显示切片正文。
        </p>

        {listPhase === "idle" ? (
          <EmptyState title="还没有读取文档列表">
            点上面的「读取列表」查看知识库里已经有哪些文档。
            上传成功后列表会自动刷新，不必手动点。
          </EmptyState>
        ) : null}

        {listPhase === "loading" ? (
          <LoadingIndicator message="正在读取文档列表…" />
        ) : null}

        {listPhase === "failed" && listError ? (
          <Notice tone="danger" tag="读取失败" role="alert">
            {listError}
          </Notice>
        ) : null}

        {listPhase === "done" && documents.length === 0 ? (
          <EmptyState title="知识库还是空的">
            在上面选一份 {RAG_DOCUMENT_SUPPORTED_EXTENSIONS.join(" / ")} 文件上传，
            它就会出现在这里。
          </EmptyState>
        ) : null}

        {listPhase === "done" && documents.length > 0 ? (
          <>
            <div className={styles.listSummary}>
              <span>
                已入库文档 <strong>{documents.length}</strong> 份，合计{" "}
                <strong>{totalChunks}</strong> 个切片
              </span>
              <span className={styles.summaryNote}>
                列表接口当前返回全部文档，没有分页，所以这就是知识库的完整清单。
              </span>
            </div>

            {/* 筛选是纯本地的，不发请求：列表已经拿在手里了，再问一次后端没有意义 */}
            <div className={styles.filters}>
              <label className={styles.hint} htmlFor="doc-search">
                在已加载的列表中搜索
              </label>
              <input
                id="doc-search"
                className={styles.textInput}
                type="search"
                value={searchText}
                onChange={(event) => setSearchText(event.target.value)}
                placeholder="按文档标题或文件名筛选"
              />

              {availableFormats.length > 1 ? (
                <div className={styles.formatFilter}>
                  <span className={styles.hint}>格式</span>
                  <div className={styles.chipRow} role="group" aria-label="按格式筛选">
                    <button
                      type="button"
                      className={styles.chip}
                      data-active={formatFilter === ALL_FORMATS}
                      aria-pressed={formatFilter === ALL_FORMATS}
                      onClick={() => setFormatFilter(ALL_FORMATS)}
                    >
                      全部
                    </button>
                    {availableFormats.map((format) => (
                      <button
                        key={format}
                        type="button"
                        className={styles.chip}
                        data-active={formatFilter === format}
                        aria-pressed={formatFilter === format}
                        onClick={() => setFormatFilter(format)}
                      >
                        {format.toUpperCase()}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>

            {filteredDocuments.length === 0 ? (
              <EmptyState title="没有匹配的文档">
                当前筛选条件下没有文档。换个关键词，或者把格式切回「全部」。
              </EmptyState>
            ) : (
              <>
                {filtering ? (
                  <p className={styles.filterResult}>
                    筛选出 {filteredDocuments.length} / {documents.length} 份文档
                  </p>
                ) : null}

                <ul className={styles.docList}>
                  {filteredDocuments.map((document) => (
                    <li key={document.source_file} className={styles.docItem}>
                      <div className={styles.docHead}>
                        <span className={styles.docTitle}>
                          {document.document_title}
                        </span>
                        <span className={styles.docFile}>{document.source_file}</span>
                      </div>
                      <div className={styles.docMeta}>
                        <span>
                          <span className={styles.chunkBadge}>
                            {document.chunk_count}
                          </span>{" "}
                          个切片
                        </span>
                        <span className={styles.timestamp}>
                          更新于 {formatTimestamp(document.updated_at)}
                        </span>
                        {document.created_at !== document.updated_at ? (
                          <span className={styles.timestamp}>
                            创建于 {formatTimestamp(document.created_at)}
                          </span>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </>
        ) : null}
      </section>
    </div>
  );
}
