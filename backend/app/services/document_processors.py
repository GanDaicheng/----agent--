"""知识文档文件处理器：把上传的字节统一提取成「可以切片的文本」。

## 为什么单独一层

在此之前只有 md / txt，它们本身就是纯文本，解码即可。docx / pdf 不一样：
它们是二进制容器，里面的文字带着**结构**（Word 的段落样式、PDF 的字号层级），
必须先把结构解析出来，否则拿到手的是一堆没有边界的长文本。

这一层只做一件事：**字节 → 文本**，并且保证输出的文本里带着标题层级。
之后切片、算向量、写库全部交给现有的入库服务，一行都不用改。

## 关键设计：上传类型 ≠ 切片类型

```
上传类型（用户能传的）：md / txt / docx / pdf
切片类型（切片器能切的）：md / txt
```

处理器负责把上传类型映射成「文本 + 切片类型」。**docx / pdf 的输出都是 Markdown**，
所以它们的切片类型固定是 `md`，直接复用 parse_markdown_text（按 `##` 切小节）。
这样 knowledge_chunking 和 knowledge_ingestion 完全不需要知道 docx/pdf 的存在。

## 为什么这里可以 import 第三方解析库

document_normalization 有个测试守着「只能用标准库」（它是给上传内容把第一道关的纯函数层）。
解析库不该塞进那里，也不该塞进切片器。这一层是**唯一**允许依赖 python-docx / pdfplumber 的地方，
边界因此很清楚：要换解析库，只动这个文件。

## 输出为什么是「带标题的文本」而不是结构化对象

因为下游切片器已经按 Markdown 标题切得很好了，重新设计一套「段落树 → 切片」的映射
等于把同一件事再做一遍。**把不同格式归一成 Markdown，是这里唯一需要解决的问题。**

本模块不碰数据库、不读配置、不调用模型——纯字节输入、文本输出。
"""

import io
import re
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

import pdfplumber
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.core.exceptions import AppError
from app.services.document_normalization import decode_document_bytes

MARKDOWN_UPLOAD_TYPE = "md"
PLAIN_TEXT_UPLOAD_TYPE = "txt"
DOCX_UPLOAD_TYPE = "docx"
PDF_UPLOAD_TYPE = "pdf"

# 用户能上传的类型。加新格式时改这一处，错误信息会同步更新。
SUPPORTED_UPLOAD_TYPES: tuple[str, ...] = (
    MARKDOWN_UPLOAD_TYPE,
    PLAIN_TEXT_UPLOAD_TYPE,
    DOCX_UPLOAD_TYPE,
    PDF_UPLOAD_TYPE,
)

# 处理器输出交给哪套切片策略。这两个值和 document_normalization.SUPPORTED_FILE_TYPES
# 是同一组——切片器只认它们。刻意各自定义而不是互相 import：这里表达的是
# 「我的输出是哪种文本」，不是「系统支持哪些类型」，含义不同。
MARKDOWN_CHUNK_TYPE = "md"
PLAIN_TEXT_CHUNK_TYPE = "txt"

# Word 内置标题样式的 styleId。中文 Word 里这些 id 仍然是英文
# （被本地化的是样式的显示名「标题 1」，不是 id），所以按 id 判断跨语言稳定。
_DOCX_TITLE_STYLE_IDS = frozenset({"Title"})
_DOCX_HEADING_STYLE_ID_PATTERN = re.compile(r"^Heading([1-9])$")
# 兜底：样式被本地化、或文档是自己建的样式时，再看显示名。
# 「标题 1」「Heading 1」「heading1」都认。
_DOCX_HEADING_NAME_PATTERN = re.compile(r"^(?:heading|标题)\s*([1-9])$", re.IGNORECASE)

# PDF 字号启发式的阈值。相对正文最大字号而言——
# 用相对值而不是绝对磅值，因为同一份文档可能整篇是 10pt 也可能是 14pt。
# 这两个数是**启发式**，不是规范：排版特殊的 PDF 会误判，
# 但错了只是标题层级不对，正文一个字都不会丢。
_PDF_TITLE_SIZE_RATIO = 1.35
_PDF_HEADING_SIZE_RATIO = 1.15

# 判定「这是新的一段」时，行间距要比常规行距大多少倍。
# 常规行距由文档自己算（取众数），所以不写死磅值。
_PDF_PARAGRAPH_GAP_RATIO = 1.4

# 行距众数的分桶精度（磅）。浮点行距直接统计众数几乎每个值都不一样，
# 按 0.5 磅归桶之后才统计得出「常规行距」。
_PDF_GAP_BUCKET = 0.5


class DocumentParseError(AppError):
    """文件结构解析失败：损坏、加密、或根本不是这个格式。"""


class NoExtractableTextError(AppError):
    """文件结构读得出来，但里面提取不到任何文字。

    和「文档是空的」不是一回事，用户看到的也应该是两句话：
    - 文档是空的 → 去检查那份文件是不是没写完；
    - 提取不到文字 → 文件里有内容，但内容是图片（典型是扫描件 PDF），
      必须换一份带文字层的文件，或者先做 OCR。

    混成一句「内容为空」的话，拿着扫描件的用户只会反复重试同一个文件。
    """


class UnsupportedUploadTypeError(AppError):
    """上传类型不在支持范围内，没有对应的文件处理器。

    单独一个类型（而不是复用 document_normalization 的 UnsupportedDocumentTypeError）：
    那一个是「切片器不支持这种文本」，这一个是「我们没有处理这种文件的处理器」。
    两者将来会分叉——比如新增一种最终也输出 Markdown 的格式时，上传类型会变、
    切片类型不会。路由只需按类别翻译成同一条 422 文案。
    """


def normalize_upload_type(file_type: str) -> str:
    """把各种写法的上传类型归一成 `md` / `txt` / `docx` / `pdf`。

    接受 `docx`、`.docx`、`DOCX` 三种写法——调用方可能从文件名后缀取（带点），
    也可能从表单字段取（不带点、大小写随意）。与 document_normalization 的
    normalize_file_type 是同一套约定，只是集合不同。

    不支持的类型**直接报错**，不猜默认值：把 docx 当成纯文本解码，
    出来的是一堆二进制乱码，而且会真的入库、真的算向量、真的被检索到。
    """
    if not isinstance(file_type, str):
        raise UnsupportedUploadTypeError(
            f"file_type 必须是字符串，当前是 {type(file_type).__name__}。"
        )

    normalized = file_type.strip().lower()
    if normalized.startswith("."):
        normalized = normalized[1:]

    if normalized not in SUPPORTED_UPLOAD_TYPES:
        supported = "、".join(SUPPORTED_UPLOAD_TYPES)
        raise UnsupportedUploadTypeError(
            f"不支持的文件类型：{file_type!r}。当前支持：{supported}。"
        )
    return normalized


@dataclass(frozen=True)
class ProcessedDocument:
    """一个文件的提取结果。

    text 是**提取后**的文本：md/txt 是解码原文，docx/pdf 是还原出来的 Markdown。
    chunk_type 是交给切片器的类型，只能是 "md" 或 "txt"。
    """

    text: str
    chunk_type: str


class DocumentProcessor(Protocol):
    """文件处理器：把某种格式的字节提取成文本，并声明它按哪套策略切片。"""

    upload_type: str
    chunk_type: str

    def extract(self, raw: bytes, *, source_file: str) -> str: ...


class MarkdownProcessor:
    """md 就是纯文本，解码即可。"""

    upload_type = MARKDOWN_UPLOAD_TYPE
    chunk_type = MARKDOWN_CHUNK_TYPE

    def extract(self, raw: bytes, *, source_file: str) -> str:
        return decode_document_bytes(raw, source_file=source_file)


class PlainTextProcessor:
    """txt 同样是纯文本。与 md 的实现一样，但切片策略不同——所以是两个处理器。"""

    upload_type = PLAIN_TEXT_UPLOAD_TYPE
    chunk_type = PLAIN_TEXT_CHUNK_TYPE

    def extract(self, raw: bytes, *, source_file: str) -> str:
        return decode_document_bytes(raw, source_file=source_file)


class DocxProcessor:
    """Word 文档 → Markdown。

    ## 标题层级怎么映射（这是本处理器最关键的决定）

    Markdown 的惯例是「H1 = 文档标题，H2 = 小节」，而 Word 的惯例是
    「标题 1 = 一级小节」。**如果照着级别一对一映射（标题 1 → `#`），
    一篇正常的 Word 文档会垮掉**：切片器只认第一个 `#` 当文档标题，
    后面那些标题 1 会掉进正文，整个文档只切出一个巨大的「文档元信息」切片。

    所以按「语义」对齐，而不是按「级别数字」对齐：

    | Word | Markdown | 切片里的角色 |
    | --- | --- | --- |
    | Title | `#` | 文档标题 |
    | 标题 1 | `##` | **小节边界（切片主边界）** |
    | 标题 2 及更深 | `###`… | 留在小节正文里 |

    这与 knowledge_seed/retail 下那 5 份 Markdown 的结构一致（H1 标题 + H2 小节 + H3 细节），
    所以 Word 文档和手写 Markdown 切出来的粒度是一样的。
    """

    upload_type = DOCX_UPLOAD_TYPE
    chunk_type = MARKDOWN_CHUNK_TYPE

    def extract(self, raw: bytes, *, source_file: str) -> str:
        try:
            document = Document(io.BytesIO(raw))
        except Exception as error:  # noqa: BLE001
            # python-docx 对坏文件抛的异常类型很杂（zipfile.BadZipFile、
            # lxml.etree.XMLSyntaxError、KeyError…），统一收口成一种，
            # 调用方只需要知道「这个文件解析不了」。
            raise DocumentParseError(
                f"{source_file} 无法作为 Word 文档解析，文件可能已损坏。"
            ) from error

        blocks: list[str] = []
        for block in _iter_docx_blocks(document):
            if isinstance(block, Table):
                # 表格内部的行用单个换行连着，不能空行——空行会把一张表拆成两段，
                # 而切片器是按空行分块的，拆开之后表头和表体就可能落到不同切片里。
                rendered_rows = _render_docx_table(block)
                if rendered_rows:
                    blocks.append("\n".join(rendered_rows))
            else:
                rendered = _render_docx_paragraph(block)
                if rendered:
                    blocks.append(rendered)

        # **用空行连接块，而不是单个换行。** Word 的每个段落本来就是天然的一段，
        # 用单换行连起来会让整节变成一坨没有空行的长文本，而切片器遇到超长小节时
        # 只能按空行二次切分——没有空行，一节就会变成一个撑满上百行的巨型切片。
        # 空段落直接跳过：它只是排版留白，段落边界由这个空行表达。
        return "\n\n".join(blocks)


class PdfProcessor:
    """PDF → Markdown。

    ## 只能做「有文字层」的 PDF

    扫描件（整页是图片）在 PDF 里没有文字对象，提取出来是空的。

    **为什么只有 PDF 在这里自己抛 NoExtractableTextError**：md / txt / docx 提取出空文本时
    一律原样返回，由入库服务统一判「内容为空」。PDF 之所以例外，是因为「提取不出文字」
    在 PDF 上有一个具体且可行动的原因——这是一份扫描件，里面有内容但内容是图片——
    用户该做的是换文件或先 OCR，而不是去检查文件是不是没写完。
    真的解法是 OCR，那是另一个量级的事情，本阶段不做，也**不假装能做**。

    ## 为什么按字号推标题

    PDF 里**没有「标题」这个概念**，只有一段段带坐标和字号的文字。
    想恢复层级只有三条路：读 PDF 自带的书签目录（多数文件没有）、
    按字号猜、或者交给模型。这里选按字号猜——它对「用 Word/LaTeX 导出」
    这类规整文档相当准，且完全离线、无成本。

    猜错的后果要说清楚：**只是标题层级不对，正文一个字都不会丢**。
    层级不对会影响切片边界（小节被切得过大或过小），所以字号阈值放在
    模块常量里，调它不需要改逻辑。
    """

    upload_type = PDF_UPLOAD_TYPE
    chunk_type = MARKDOWN_CHUNK_TYPE

    def extract(self, raw: bytes, *, source_file: str) -> str:
        lines = _extract_pdf_lines(raw, source_file=source_file)
        if not lines:
            raise NoExtractableTextError(
                f"{source_file} 里没有可提取的文字（是扫描件或纯图片 PDF？），"
                "需要 OCR 才能读取，本服务不做 OCR。"
            )
        return _pdf_lines_to_markdown(lines)


@dataclass(frozen=True)
class PdfLine:
    """PDF 里的一行：字号、文本、以及它在页面上的纵向位置。

    top 是必须留着的：判断「这两行之间是不是换段了」只能靠行间距，
    而间距是两个 top 之差。
    """

    size: float
    text: str
    top: float
    bottom: float


# 注册表：上传类型 → 处理器。新增格式只加一个处理器和这里一行。
_PROCESSORS: dict[str, DocumentProcessor] = {
    processor.upload_type: processor
    for processor in (
        MarkdownProcessor(),
        PlainTextProcessor(),
        DocxProcessor(),
        PdfProcessor(),
    )
}


def extract_document_text(
    raw: bytes, *, source_file: str, file_type: str
) -> ProcessedDocument:
    """按类型选处理器，把字节提取成「文本 + 切片类型」。

    file_type 应当已经过 normalize_upload_type 归一。不在这里归一，
    是为了不把「校验」和「提取」两件事混在一起——校验失败应该在
    任何解析动作之前发生，而不是解析完一半才发现类型不对。
    """
    processor = _PROCESSORS.get(file_type)
    if processor is None:
        # 理论上到不了：normalize_upload_type 已经把不支持的类型挡在门外。
        # 保留这一支是为了「传进来没归一过的类型」时立刻炸，而不是静默返回空文本。
        raise UnsupportedUploadTypeError(f"没有对应的文件处理器：{file_type!r}")

    return ProcessedDocument(
        text=processor.extract(raw, source_file=source_file),
        chunk_type=processor.chunk_type,
    )


# --------------------------------------------------------------------------
# docx
# --------------------------------------------------------------------------


def _iter_docx_blocks(document: Document):
    """按文档顺序产出段落与表格。

    `document.paragraphs` 和 `document.tables` 是**两个独立的列表**，
    分别遍历会把所有表格挪到文末。而「这份口径文档里那张字段表」
    插在哪个位置是有意义的——挪到末尾会让上下文错位。所以按 body 的
    XML 子元素顺序遍历。
    """
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            yield Paragraph(child, document)
        elif tag == "tbl":
            yield Table(child, document)


def _docx_heading_level(paragraph: Paragraph) -> int:
    """判断段落是几级标题，不是标题返回 0。

    先看 styleId（跨语言稳定），再退回样式显示名（文档自定义样式的情况）。
    """
    style = paragraph.style
    if style is None:
        return 0

    style_id = getattr(style, "style_id", None) or ""
    if style_id in _DOCX_TITLE_STYLE_IDS:
        return 1  # Title 视同一级，映射成 `#`

    matched = _DOCX_HEADING_STYLE_ID_PATTERN.match(style_id)
    if matched:
        # 标题 1 → 2（`##`），标题 2 → 3（`###`）……
        # 理由见 DocxProcessor 的说明：Word 的「标题 1」在语义上对应 Markdown 的 H2。
        return int(matched.group(1)) + 1

    name = getattr(style, "name", None) or ""
    matched = _DOCX_HEADING_NAME_PATTERN.match(name.strip())
    if matched:
        return int(matched.group(1)) + 1

    return 0


def _render_docx_paragraph(paragraph: Paragraph) -> str:
    """一个段落 → 一行 Markdown。空段落返回空串，由调用方跳过。"""
    text = paragraph.text.strip()
    level = _docx_heading_level(paragraph)

    # 空段落直接丢掉：它在 Word 里只是排版留白，
    # 而「两段之间有空行」这件事由调用方的块连接方式表达，不靠这里补。
    if not text:
        return ""

    if level == 0:
        return text

    # Markdown 最多 6 级标题，再深也压到 6——多出来的 # 会被
    # 切片器的标题正则当成普通文本，反而丢掉了「这是标题」的信息。
    hashes = "#" * min(level, 6)
    return f"{hashes} {text}"


def _render_docx_table(table: Table) -> list[str]:
    """表格 → Markdown 管道表。

    **为什么不跳过表格**：Word 里的字段说明、口径对照绝大多数是表格形式，
    跳过等于把文档最有信息量的部分丢掉，而且丢得无声无息——用户只会发现
    「问文档里明明写了的东西，它答不出来」。

    第一行当表头：Markdown 的表必须有表头行，而 Word 表格的约定俗成也是首行表头。
    这一条要写进文档里，因为「首行不是表头」的表格会被渲染成多一行数据。
    """
    rows = [
        [_clean_table_cell(cell.text) for cell in row.cells] for row in table.rows
    ]
    if not rows:
        return []

    width = max(len(row) for row in rows)
    lines = [
        "| " + " | ".join(rows[0] + [""] * (width - len(rows[0]))) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    for row in rows[1:]:
        padded = row + [""] * (width - len(row))
        lines.append("| " + " | ".join(padded) + " |")
    return lines


def _clean_table_cell(text: str) -> str:
    """单元格文本压成单行，并转义会破坏表格结构的竖线。"""
    collapsed = " ".join(text.split())
    return collapsed.replace("|", r"\|")


# --------------------------------------------------------------------------
# pdf
# --------------------------------------------------------------------------


def _extract_pdf_lines(raw: bytes, *, source_file: str) -> list[PdfLine]:
    """把 PDF 的每一页读成一行行带字号的文本。"""
    lines: list[PdfLine] = []

    try:
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            for page in pdf.pages:
                for line in page.extract_text_lines():
                    text = (line.get("text") or "").strip()
                    if not text:
                        continue
                    lines.append(
                        PdfLine(
                            size=_dominant_size(line),
                            text=text,
                            top=float(line["top"]),
                            bottom=float(line["bottom"]),
                        )
                    )
    except AppError:
        # 我们自己抛的异常原样上抛，不要被下面那条「统一收口」吞掉。
        # 按基类判断而不是列具体类型：以后加新的文档异常时不用回来补这里。
        raise
    except Exception as error:  # noqa: BLE001
        # pdfminer 的异常很杂（PDFSyntaxError、PDFPasswordIncorrect、
        # zlib.error…），统一收口。**加密 PDF 也会走到这里**，
        # 文案里提一句「或已加密」，否则用户拿着一个要密码的文件
        # 只会看到「文件可能损坏」，方向完全错了。
        raise DocumentParseError(
            f"{source_file} 无法作为 PDF 解析，文件可能已损坏或已加密。"
        ) from error

    return lines


def _dominant_size(line: dict) -> float:
    """一行里出现最多的那个字号。

    为什么不取平均：一行里混排（比如正文里夹一个上标）时平均值会得出
    一个文档里根本不存在的字号，之后再拿去和正文字号比就会误判。
    取众数得到的永远是真实存在的字号。
    """
    sizes = [round(float(char["size"]), 1) for char in line.get("chars") or []]
    if not sizes:
        return 0.0
    return Counter(sizes).most_common(1)[0][0]


def _pdf_lines_to_markdown(lines: list[PdfLine]) -> str:
    """带字号的行 → Markdown 文本（纯函数，可脱离 PDF 单独测）。

    三件事：定正文字号 → 按字号给标题层级 → 按行间距断段。
    """
    body_size = _body_size(lines)
    title_used = False
    out: list[str] = []
    previous: PdfLine | None = None
    normal_gap = _normal_gap(lines)

    for line in lines:
        if previous is not None and _is_paragraph_break(previous, line, normal_gap):
            # 段与段之间留空行。少了它，切片器遇到超长小节就无从下刀
            # （它只按空行分段），整节会变成一个撑满上百行的巨型切片。
            out.append("")

        ratio = line.size / body_size if body_size > 0 else 1.0
        text = line.text

        if ratio >= _PDF_TITLE_SIZE_RATIO and not title_used:
            out.append(f"# {text}")
            title_used = True
        elif ratio >= _PDF_HEADING_SIZE_RATIO:
            out.append(f"## {text}")
        else:
            out.append(text)

        previous = line

    return "\n".join(out)


def _body_size(lines: list[PdfLine]) -> float:
    """正文字号 = **覆盖字符最多**的那个字号。

    为什么用字符数而不是行数：行数在短文档里会打平（「3 行标题 vs 3 行正文」），
    而平局时谁赢只取决于谁先出现——同一份文档换个顺序就得出不同的正文字号，
    标题层级随之全变。字符数不会打平：标题通常是几个字，正文是几十个字一行。

    为什么不取平均：一份「标题很大、正文很小」的文档，平均值会落在两者之间，
    而那个字号在文档里根本不存在，拿它当基准比出来的层级全是错的。
    """
    weights: Counter[float] = Counter()
    for line in lines:
        if line.size > 0:
            weights[line.size] += len(line.text)
    if not weights:
        return 0.0
    return weights.most_common(1)[0][0]


def _normal_gap(lines: list[PdfLine]) -> float:
    """常规行距 = 相邻行间距的众数。

    为什么不写死磅值：同样是「一行接一行」，10pt 正文和 18pt 正文的行距
    差得远。让文档自己报出自己的常规行距，判断换段时才有共同基准。
    行距是浮点数，直接统计众数几乎每个值都不同，所以按 0.5 磅归桶后再统计。
    """
    gaps = [
        round((lines[index + 1].top - lines[index].bottom) / _PDF_GAP_BUCKET)
        * _PDF_GAP_BUCKET
        for index in range(len(lines) - 1)
    ]
    gaps = [gap for gap in gaps if gap > 0]
    if not gaps:
        return 0.0
    return Counter(gaps).most_common(1)[0][0]


def _is_paragraph_break(previous: PdfLine, current: PdfLine, normal_gap: float) -> bool:
    """两行之间是不是换段了。

    算不出常规行距时（只有一个空档、或所有空档都不为正）**一律不换段**：
    宁可少断几段，也不要因为一个瞎猜的阈值把一段话切成好几截。
    """
    if normal_gap <= 0:
        return False
    gap = current.top - previous.bottom
    return gap > normal_gap * _PDF_PARAGRAPH_GAP_RATIO
