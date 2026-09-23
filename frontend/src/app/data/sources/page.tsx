import type { Metadata } from "next";

import { PageHeader } from "@/components/ui/PageHeader";
import { getSection, RETAIL_DATA_NOTE } from "@/features/platform/platform-config";

import { DataCollectionWorkspace } from "./DataCollectionWorkspace";

const SECTION_ID = "data";

export const metadata: Metadata = {
  title: "数据采集",
  description: "上传知识文档，切片向量化后写入 RAG 知识库，并查看已入库的文档。",
};

/**
 * 数据采集页面。
 *
 * 路由文件刻意保持很薄：只负责页头、边界说明这些静态内容，
 * 交互与取数全部交给 DataCollectionWorkspace（客户端组件）。
 * 这样绝大部分内容仍然是服务端渲染的。
 *
 * 它目前只覆盖「知识文档 → RAG 知识库」这一条链路，因此是独立静态路由，
 * 而不是由通用模块页模板渲染的说明页。
 * 「业务数据文件（Excel / CSV）→ 数据仓库」是另一条链路，尚未开始——
 * 两者在页面上会分成两个区域，因为背后是两套完全不同的处理方式：
 * 文档做切片与语义检索，表格数据要做类型推断、建表、再用 SQL 查。
 */
export default function Page() {
  const section = getSection(SECTION_ID);

  return (
    <article>
      <PageHeader
        sectionName={section?.name ?? "数据中台"}
        title="数据采集"
        subtitle="把知识文档汇入 RAG 知识库：自动切片、向量化，之后在「知识问答」里可被检索。页面上会列出已入库的文档，便于核对导入结果。"
        boundary={
          <>
            <p>
              支持 Markdown（.md）、纯文本（.txt）、Word（.docx）与 PDF（.pdf），
              单个文件不超过 10 MiB。上传会真实调用 embedding 服务，并写入本地知识库。
            </p>
            <p>
              只有 md / txt 需要是 UTF-8 编码；docx / pdf 是二进制格式，由后端解析出
              标题层级后还原成文本再切片。PDF 只支持带文字层的文件——扫描件（整页是图片）
              提取不出内容，那需要 OCR，本阶段不做。
              <strong>原始文件不落盘保存，只保存切片后的文本。</strong>
            </p>
            <p>
              业务数据文件（Excel / CSV）导入为数据仓库表是另一条链路，尚未开始。
            </p>
            <p>
              {RETAIL_DATA_NOTE}
              目前知识库里的文档是零售业务文档，换成其它行业的文档同样可用——
              这里不区分行业，只按标题层级切片。
            </p>
          </>
        }
      />

      <DataCollectionWorkspace />
    </article>
  );
}
