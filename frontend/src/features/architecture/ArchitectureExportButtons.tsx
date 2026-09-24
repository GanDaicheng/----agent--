"use client";

import { useState } from "react";

import { ARCHITECTURE_MODEL } from "./architecture-data";
import {
  ARCHITECTURE_PNG_FILENAME,
  ARCHITECTURE_SVG_FILENAME,
  buildArchitectureSvg,
} from "./architecture-export";

import styles from "./ArchitectureExportButtons.module.css";

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function ArchitectureExportButtons() {
  const [pngBusy, setPngBusy] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const downloadSvg = () => {
    setExportError(null);
    const svg = buildArchitectureSvg(ARCHITECTURE_MODEL);
    downloadBlob(new Blob([svg], { type: "image/svg+xml;charset=utf-8" }), ARCHITECTURE_SVG_FILENAME);
  };

  const downloadPng = async () => {
    setPngBusy(true);
    setExportError(null);
    let sourceUrl: string | null = null;
    try {
      const svg = buildArchitectureSvg(ARCHITECTURE_MODEL);
      sourceUrl = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml;charset=utf-8" }));
      const image = new Image();
      await new Promise<void>((resolve, reject) => {
        image.onload = () => resolve();
        image.onerror = () => reject(new Error("SVG 图像加载失败"));
        image.src = sourceUrl as string;
      });

      const canvas = document.createElement("canvas");
      canvas.width = 1920;
      canvas.height = 1080;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("浏览器无法创建 PNG 画布");
      context.drawImage(image, 0, 0, 1920, 1080);

      const png = await new Promise<Blob>((resolve, reject) => {
        canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("PNG 生成失败")), "image/png");
      });
      downloadBlob(png, ARCHITECTURE_PNG_FILENAME);
    } catch {
      setExportError("PNG 生成失败，请先导出 SVG，或更换浏览器后重试。");
    } finally {
      if (sourceUrl) URL.revokeObjectURL(sourceUrl);
      setPngBusy(false);
    }
  };

  return (
    <div className={styles.actions} aria-label="导出面试架构图">
      <button type="button" onClick={downloadSvg}>导出 SVG</button>
      <button type="button" disabled={pngBusy} onClick={downloadPng}>
        {pngBusy ? "正在生成…" : "导出 PNG · 1920×1080"}
      </button>
      {exportError ? <p className={styles.error} role="alert">{exportError}</p> : null}
    </div>
  );
}
