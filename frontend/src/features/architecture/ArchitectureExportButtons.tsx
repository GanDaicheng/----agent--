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

  const downloadSvg = () => {
    const svg = buildArchitectureSvg(ARCHITECTURE_MODEL);
    downloadBlob(new Blob([svg], { type: "image/svg+xml;charset=utf-8" }), ARCHITECTURE_SVG_FILENAME);
  };

  const downloadPng = async () => {
    setPngBusy(true);
    try {
      const svg = buildArchitectureSvg(ARCHITECTURE_MODEL);
      const sourceUrl = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml;charset=utf-8" }));
      const image = new Image();
      image.decoding = "async";
      image.src = sourceUrl;
      await image.decode();

      const canvas = document.createElement("canvas");
      canvas.width = 1920;
      canvas.height = 1080;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("浏览器无法创建 PNG 画布");
      context.drawImage(image, 0, 0, 1920, 1080);
      URL.revokeObjectURL(sourceUrl);

      const png = await new Promise<Blob>((resolve, reject) => {
        canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("PNG 生成失败")), "image/png");
      });
      downloadBlob(png, ARCHITECTURE_PNG_FILENAME);
    } finally {
      setPngBusy(false);
    }
  };

  return (
    <div className={styles.actions} aria-label="导出面试架构图">
      <button type="button" onClick={downloadSvg}>导出 SVG</button>
      <button type="button" disabled={pngBusy} onClick={downloadPng}>
        {pngBusy ? "正在生成…" : "导出 PNG · 1920×1080"}
      </button>
    </div>
  );
}

