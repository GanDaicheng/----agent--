"""文档内容标准化：把「上传来的字节」整理成切片器能稳定处理的文本。

## 为什么单独一个模块

切片（knowledge_chunking）关心的是「怎么把一段文本切成语义完整的片段」；
本模块关心的是「这段文本本身干不干净」。两件事的失败方式完全不同：
切错了是片段质量差，输入没洗干净则会让**切片器判断失误**——比如 BOM
会让 `#` 一级标题认不出来，整篇文档的标题就悄悄退化成文件名。

## 三件事，按数据流的先后

1. **把字节解码成文本**（`decode_document_bytes`）。上传接口手里是 `bytes`，
   而下游全部只认 `str`。严格按 UTF-8 解码，失败就当场报错——
   用 `errors="replace"` 会把一串 `�` 静默塞进正文，一路进切片、进向量库，
   之后完全无法回溯是哪一步坏掉的。宁可让用户重新导出一次文件。

2. **去掉 BOM**（`﻿`）。Windows 的记事本、不少编辑器另存为 UTF-8 时
   会在开头写一个 BOM。它肉眼看不见，但会让 `^#\\s+` 匹配不上——
   于是文档标题变成文件名（`retail_metrics` 而不是「零售核心指标口径说明」），
   而**文档标题会进 content_for_embedding**，直接影响检索质量。
   这种故障没有任何报错，只有召回变差，很难追。

3. **统一换行符为 `\\n`**。上传的文件可能来自 Windows（`\\r\\n`）或老 Mac（`\\r`）。
   切片器用 `splitlines()` 能应付，但正文里残留的 `\\r` 会进 content，
   进而进 content_hash、进向量——同一份文档在两台机器上传会算出不同的 hash，
   幂等判定就失效了（明明内容一样，却被判成「变了」要重算向量，白花钱）。

除此之外**什么都不做**：不去首尾空白、不压缩空行、不动行内内容。
那些是切片器 `clean_markdown_body` 的职责，放在两处做同一件事，
只会在某次改动后变得不一致。本模块只保证「文本是干净的 UTF-8、换行统一」。
"""

from pathlib import Path

from app.core.exceptions import AppError

MARKDOWN_FILE_TYPE = "md"
PLAIN_TEXT_FILE_TYPE = "txt"

# 第一版支持的类型。加新类型时改这一处，normalize_file_type 的错误信息会同步更新。
SUPPORTED_FILE_TYPES: tuple[str, ...] = (MARKDOWN_FILE_TYPE, PLAIN_TEXT_FILE_TYPE)

# 唯一接受的编码。知识文档里的中文、符号、公式都靠它，
# 换成 GBK 之类会随平台漂移的编码，同一份文件在不同机器上就是两种结果。
_ENCODING = "utf-8"

# UTF-8 BOM。用转义写法而不是把那个字符直接贴在源码里——
# 它不可见，直写的话读代码的人根本看不出这里有什么。
_BOM = "﻿"

# 换行符统一成 \n。顺序有讲究：先处理 \r\n 再处理单个 \r，
# 否则 \r\n 会被拆成两个 \n。
_CRLF = "\r\n"
_CR = "\r"
_LF = "\n"


class UnsupportedDocumentTypeError(AppError):
    """文件类型不在支持范围内。"""


class EmptyDocumentError(AppError):
    """文档内容为空（或只有空白），没法切片。"""


class UndecodableDocumentError(AppError):
    """字节不是合法的 UTF-8，解不出文本来。"""


def decode_document_bytes(raw: bytes, *, source_file: str) -> str:
    """把上传来的字节解码成文本。**严格 UTF-8**，解不开就报错。

    为什么不用 `errors="replace"` 硬解？那会把解不出来的字节换成 `�`
    继续往下走：切片照切、向量照算、库照写，用户看到的是「上传成功」，
    而正文里已经混进了一串无法复原的乱码。等到检索质量变差才发现，
    那时原文早就不在手里了。**解码失败是唯一能当场确认真相的时刻**，
    宁可在这里失败，让用户把文件另存为 UTF-8 再传一次。

    为什么不用 `utf-8-sig`？BOM 由 normalize_document_content 处理。
    两处都做同一件事，只会在某次改动后变得不一致——而且 `utf-8-sig`
    只在**开头**剥 BOM，正文中间出现的 BOM 它一样不管。
    """
    if not isinstance(raw, (bytes, bytearray)):
        raise UndecodableDocumentError(
            f"待解码的内容必须是字节，当前是 {type(raw).__name__}。"
        )

    try:
        return bytes(raw).decode(_ENCODING)
    except UnicodeDecodeError as error:
        # 不把 error 的原文拼进来：它会带上出错的字节位置与原始字节值，
        # 对用户没有帮助（他改不了那几个字节），却是一段不好解释的内部细节。
        raise UndecodableDocumentError(
            f"{source_file} 不是合法的 {_ENCODING.upper()} 文本，无法解码。"
            "请把文件另存为 UTF-8 编码后重新上传。"
        ) from error


def normalize_file_type(file_type: str) -> str:
    """把各种写法的类型名归一成 `md` / `txt`。

    接受 `md`、`.md`、`MD` 三种写法——调用方可能从文件名后缀取（带点），
    也可能从表单字段取（不带点、大小写随意），不该逼它们先自己整理。

    不支持的类型**直接报错**，不做「猜一个默认值」这种事：
    把 .docx 当成纯文本切，出来的是一堆二进制乱码，而且会真的入库、
    真的算向量、真的被检索到。宁可当场失败。
    """
    if not isinstance(file_type, str):
        raise UnsupportedDocumentTypeError(
            f"file_type 必须是字符串，当前是 {type(file_type).__name__}。"
        )

    normalized = file_type.strip().lower()
    if normalized.startswith("."):
        normalized = normalized[1:]

    if normalized not in SUPPORTED_FILE_TYPES:
        supported = "、".join(SUPPORTED_FILE_TYPES)
        raise UnsupportedDocumentTypeError(
            f"不支持的文件类型：{file_type!r}。当前支持：{supported}。"
        )
    return normalized


def normalize_document_content(content: str) -> str:
    """去掉 BOM、把换行统一成 `\\n`。理由见模块说明。"""
    if not isinstance(content, str):
        raise EmptyDocumentError(
            f"文档内容必须已经是字符串，当前是 {type(content).__name__}。"
            "解码成文本是调用方的职责——本服务不猜编码。"
        )

    if content.startswith(_BOM):
        content = content[len(_BOM) :]

    return content.replace(_CRLF, _LF).replace(_CR, _LF)


def title_from_source_file(source_file: str) -> str:
    """从 source_file 推出一个兜底标题（去掉目录和后缀）。

    `retail_metrics.md` → `retail_metrics`；`docs/规范.txt` → `规范`。

    只是个兜底：文档自己有一级标题（md）、或者调用方显式传了 title 时都用不上它。
    但兜底必须存在——没有标题的文档不该卡住入库，而文件名已经是个可用的标识。
    """
    name = Path(source_file).name or source_file
    stem = Path(name).stem
    # 形如 ".txt" 的文件名，Path.stem 会得到 ".txt"，去掉点还是空，那就退回原名
    return stem.lstrip(".") or name
