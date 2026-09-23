"""文档内容标准化与「从内容切片」的测试。

**不连数据库、不调 embedding、不读 .env。** 这里测的都是纯函数。

为什么要单独一个文件：这一层是「上传入库」新增的入口，它的失败方式和
切片/入库都不同——它出问题时**不报错**，只是安静地把文档弄坏：

- BOM 没去掉 → `#` 一级标题认不出来 → 文档标题退化成文件名；
  而标题会进 content_for_embedding，直接影响检索质量，却没有任何报错。
- 换行符没统一 → 同一份内容在两台机器上传会算出不同的 hash →
  幂等判定失效，明明没改却重算一遍向量（真花钱）。

这两条都值得单独盯住。

第三件事是**字节解码**，它的失败方式相反：它**会**报错。纯文本之外的东西
（GBK 编码的中文、误传的图片）在解码这一步就撞墙，而不是被安静地弄坏。
这两类行为要分开守：安静的那类靠「结果对不对」断言，响的那类靠 raises 断言。
"""

import pathlib
import textwrap

import pytest

from app.services.document_normalization import (
    MARKDOWN_FILE_TYPE,
    PLAIN_TEXT_FILE_TYPE,
    SUPPORTED_FILE_TYPES,
    EmptyDocumentError,
    UndecodableDocumentError,
    UnsupportedDocumentTypeError,
    decode_document_bytes,
    normalize_document_content,
    normalize_file_type,
    title_from_source_file,
)
from app.services.knowledge_chunking import (
    PLAIN_TEXT_SECTION_TITLE,
    parse_document_text,
    parse_markdown_document,
    parse_markdown_text,
    parse_plain_text,
    split_oversized_section,
)

# ==========================================================================
# 1. 文件类型归一
# ==========================================================================


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("md", "md"),
        (".md", "md"),
        ("MD", "md"),
        ("  .MD  ", "md"),
        ("txt", "txt"),
        (".txt", "txt"),
        ("TXT", "txt"),
    ],
)
def test_file_type_variants_are_normalized(raw, expected):
    assert normalize_file_type(raw) == expected


@pytest.mark.parametrize("bad", ["markdown", "pdf", "docx", ".csv", "text", "", "  "])
def test_unsupported_file_types_are_rejected(bad):
    """不支持的类型**当场报错**，不猜默认值。

    把 .docx 当纯文本切，出来的是一堆二进制乱码，而且会真的入库、
    真的算向量、真的被检索到——宁可失败。
    """
    with pytest.raises(UnsupportedDocumentTypeError) as error:
        normalize_file_type(bad)

    # 错误信息要能自己说清支持什么，不用去翻源码
    assert "md" in str(error.value)
    assert "txt" in str(error.value)


@pytest.mark.parametrize("bad", [None, 3, b"md", ["md"]])
def test_non_string_file_types_are_rejected(bad):
    with pytest.raises(UnsupportedDocumentTypeError):
        normalize_file_type(bad)


def test_supported_types_constant_matches_the_documented_pair():
    assert SUPPORTED_FILE_TYPES == ("md", "txt")
    assert MARKDOWN_FILE_TYPE == "md"
    assert PLAIN_TEXT_FILE_TYPE == "txt"


# ==========================================================================
# 2. 内容归一
# ==========================================================================


def test_bom_is_stripped():
    """BOM 必须去掉——它会让 `# 标题` 认不出来。"""
    assert normalize_document_content("﻿# 标题") == "# 标题"


def test_bom_is_only_stripped_at_the_start():
    """正文中间出现同样的字符要保留：那是内容，不是 BOM。"""
    assert normalize_document_content("正文﻿中间") == "正文﻿中间"


def test_crlf_and_cr_are_unified_to_lf():
    assert normalize_document_content("a\r\nb\rc\nd") == "a\nb\nc\nd"


def test_crlf_is_not_double_counted():
    """先处理 \\r\\n 再处理单个 \\r——顺序反了 `\\r\\n` 会变成两个换行。"""
    assert normalize_document_content("a\r\nb") == "a\nb"


def test_normalization_changes_nothing_else():
    """空行、缩进、行尾空白都不动——那些是切片器的职责。

    同一件事分两处做，只会在某次改动后变得不一致。
    """
    original = "第一行\n\n\n  缩进的第二行   \n\n"

    assert normalize_document_content(original) == original


def test_normalization_is_idempotent():
    once = normalize_document_content("﻿a\r\nb")
    assert normalize_document_content(once) == once


@pytest.mark.parametrize("bad", [None, 3, b"bytes"])
def test_non_string_content_is_rejected(bad):
    """解码成文本是调用方的职责，本服务不猜编码。"""
    with pytest.raises(EmptyDocumentError):
        normalize_document_content(bad)


# ==========================================================================
# 3. 标题兜底
# ==========================================================================


@pytest.mark.parametrize(
    ("source_file", "expected"),
    [
        ("retail_metrics.md", "retail_metrics"),
        ("docs/规范.txt", "规范"),
        ("a/b/c/notes.txt", "notes"),
        ("no_extension", "no_extension"),
    ],
)
def test_title_falls_back_to_the_file_name(source_file, expected):
    assert title_from_source_file(source_file) == expected


# ==========================================================================
# 4. 从内容切片：Markdown
# ==========================================================================


def test_markdown_text_is_chunked_by_second_level_headings():
    text = textwrap.dedent(
        """
        # 订单口径

        ## 1. 订单数

        订单数用 COUNT(DISTINCT order_no)。

        ## 2. 客单价

        客单价 = 销售额 / 订单数。
        """
    ).lstrip()

    chunks = parse_markdown_text(text, source_file="orders.md")

    assert [chunk.section_title for chunk in chunks] == ["订单数", "客单价"]
    assert {chunk.document_title for chunk in chunks} == {"订单口径"}
    assert {chunk.source_file for chunk in chunks} == {"orders.md"}
    assert [chunk.chunk_index for chunk in chunks] == [0, 1]


def test_bom_free_text_gives_the_real_title():
    """BOM 去掉之后，一级标题才认得出来。

    这条是「为什么要归一化」的直接证据：同样的文本带 BOM 时，
    标题会退化成文件名。
    """
    text = "# 订单口径\n\n## 1. 订单数\n\n正文。"

    with_bom = parse_markdown_text("﻿" + text, source_file="orders.md")
    without_bom = parse_markdown_text(text, source_file="orders.md")

    assert with_bom[0].document_title == "orders"  # 退化成文件名
    assert without_bom[0].document_title == "订单口径"  # 正确


def test_explicit_title_overrides_the_h1():
    text = "# 文档里写的标题\n\n## 1. 小节\n\n正文。"

    chunks = parse_markdown_text(text, source_file="a.md", title="调用方给的标题")

    assert chunks[0].document_title == "调用方给的标题"


def test_explicit_title_does_not_leave_the_h1_in_the_body():
    """标题被覆盖了，但正文里那一行 H1 仍然是标题行，不该混进切片正文。"""
    text = "# 文档里写的标题\n\n## 1. 小节\n\n正文。"

    chunks = parse_markdown_text(text, source_file="a.md", title="调用方给的标题")

    assert "文档里写的标题" not in chunks[0].content


def test_missing_h1_falls_back_to_the_file_name():
    text = "## 1. 只有二级标题\n\n正文。"

    chunks = parse_markdown_text(text, source_file="docs/no_title.md")

    assert chunks[0].document_title == "no_title"


def test_markdown_text_without_chunks_returns_empty():
    for blank in ("", "   ", "\n\n\t\n"):
        assert parse_markdown_text(blank, source_file="a.md") == []


def test_parse_markdown_document_still_reads_files(tmp_path):
    """回归：老的「按路径切片」入口行为不变。"""
    path = tmp_path / "orders.md"
    path.write_text("# 订单口径\n\n## 1. 订单数\n\n正文。", encoding="utf-8")

    from_file = parse_markdown_document(path)
    from_text = parse_markdown_text(
        path.read_text(encoding="utf-8"), source_file="orders.md"
    )

    assert from_file == from_text
    assert from_file[0].source_file == "orders.md"


# ==========================================================================
# 5. 从内容切片：纯文本
# ==========================================================================


def test_plain_text_becomes_one_section_named_after_nothing():
    """纯文本没有内部结构，整篇算一个小节，标题固定为「正文」。

    不拿文件名当小节标题，是为了避免拼出
    「文档：盘点规范 / 小节：盘点规范」这种重复的上下文。
    """
    chunks = parse_plain_text("第一段。\n\n第二段。", source_file="盘点规范.txt")

    assert len(chunks) == 1
    assert chunks[0].section_title == PLAIN_TEXT_SECTION_TITLE
    assert chunks[0].document_title == "盘点规范"
    assert chunks[0].content == "第一段。\n\n第二段。"


def test_plain_text_title_can_be_overridden():
    chunks = parse_plain_text("正文。", source_file="a.txt", title="显式标题")

    assert chunks[0].document_title == "显式标题"


def test_plain_text_headings_are_not_treated_as_structure():
    """txt 里的 `#` 只是普通字符，不该被当成标题切分。"""
    text = "# 这不是标题\n\n## 也不是\n\n正文。"

    chunks = parse_plain_text(text, source_file="a.txt")

    assert len(chunks) == 1
    assert chunks[0].content == text


def test_long_plain_text_is_split_by_paragraphs():
    paragraph = "这是一段用于测试的正文内容。" * 15  # 约 210 字符
    text = "\n\n".join([paragraph] * 10)  # 远超 1200

    chunks = parse_plain_text(text, source_file="long.txt")

    assert len(chunks) > 1
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.section_title == PLAIN_TEXT_SECTION_TITLE for chunk in chunks)
    # 不丢内容：拼回去应当与原文等价
    assert "".join(chunk.content for chunk in chunks).replace("\n", "") == text.replace(
        "\n", ""
    )


def test_plain_text_splitting_reuses_the_same_oversized_rule():
    """分段规则和 Markdown 共用同一个函数——不该因为文件类型而不同。"""
    paragraph = "测试正文。" * 40
    text = "\n\n".join([paragraph] * 8)

    chunks = parse_plain_text(text, source_file="long.txt")

    assert [chunk.content for chunk in chunks] == split_oversized_section(text)


def test_plain_text_without_chunks_returns_empty():
    for blank in ("", "   ", "\n\t\n"):
        assert parse_plain_text(blank, source_file="a.txt") == []


# ==========================================================================
# 6. 按类型分发
# ==========================================================================


def test_document_text_dispatches_by_file_type():
    markdown = "# 标题\n\n## 1. 小节\n\n正文。"
    plain = "就是一段普通文本。"

    md_chunks = parse_document_text(markdown, source_file="a.md", file_type="md")
    txt_chunks = parse_document_text(plain, source_file="a.txt", file_type="txt")

    assert md_chunks[0].section_title == "小节"
    assert txt_chunks[0].section_title == PLAIN_TEXT_SECTION_TITLE


def test_unknown_file_type_raises_instead_of_returning_nothing():
    """分发器拿到没归一过的类型时要立刻炸，不能静默返回空列表。

    静默返回空会让「上传了一份 docx」表现得像「文档是空的」，
    排查方向完全错了。
    """
    with pytest.raises(ValueError):
        parse_document_text("x", source_file="a.docx", file_type="docx")


def test_document_text_passes_the_title_through():
    chunks = parse_document_text(
        "正文。", source_file="a.txt", file_type="txt", title="传进来的标题"
    )

    assert chunks[0].document_title == "传进来的标题"


def test_normalized_content_feeds_the_chunker_correctly():
    """端到端的小闭环：归一化 → 切片，BOM 与 CRLF 都不该影响结果。"""
    raw = "﻿# 订单口径\r\n\r\n## 1. 订单数\r\n\r\n正文。\r\n"

    chunks = parse_document_text(
        normalize_document_content(raw), source_file="orders.md", file_type="md"
    )

    assert chunks[0].document_title == "订单口径"
    assert "\r" not in chunks[0].content
    assert chunks[0].content == "正文。"


def test_real_documents_still_chunk_the_same_through_the_text_entry():
    """回归：真实知识文档走「文本入口」和走「路径入口」结果必须一致。"""
    docs_dir = pathlib.Path(__file__).resolve().parents[1] / "knowledge_seed" / "retail"

    for path in sorted(docs_dir.glob("*.md")):
        from_file = parse_markdown_document(path)
        from_text = parse_markdown_text(
            path.read_text(encoding="utf-8"), source_file=path.name
        )
        assert from_file == from_text, path.name


# ==========================================================================
# 7. 依赖边界
# ==========================================================================


def _imported_modules(path: pathlib.Path) -> set[str]:
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            modules.update(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def test_normalization_module_is_pure():
    """标准化模块必须是纯的：只有标准库 + 异常基类。

    它是给上传内容把第一道关的地方，一旦它够得着数据库或配置，
    「清洗文本」这件事就会莫名其妙地依赖运行环境。而且切片模块
    （knowledge_chunking）要 import 它——它不纯，切片模块也就不纯了。
    """
    import sys

    from app.services import document_normalization

    modules = _imported_modules(pathlib.Path(document_normalization.__file__))
    # 前缀匹配：_imported_modules 会把 `from x import Y` 记成 `x` 和 `x.Y` 两条
    allowed_project = ("app.core.exceptions",)

    unexpected = {
        module
        for module in modules
        if module.split(".")[0] not in sys.stdlib_module_names
        and not module.startswith(allowed_project)
    }
    assert not unexpected, f"标准化模块引入了未登记的依赖：{sorted(unexpected)}"


@pytest.mark.parametrize(
    "forbidden_prefix",
    ["openai", "sqlalchemy", "asyncpg", "app.core.config", "app.repositories", "httpx"],
)
def test_normalization_module_does_not_reach_for_external_systems(forbidden_prefix):
    from app.services import document_normalization

    modules = _imported_modules(pathlib.Path(document_normalization.__file__))
    offenders = [module for module in modules if module.startswith(forbidden_prefix)]

    assert not offenders, f"标准化模块不该依赖 {forbidden_prefix}：{offenders}"


# ==========================================================================
# 8. 字节解码
# ==========================================================================


def test_utf8_bytes_decode_to_text():
    assert decode_document_bytes("# 订单口径".encode(), source_file="a.md") == "# 订单口径"


def test_decoding_accepts_a_bytearray():
    """上传层拿到的可能是 bytearray（分块读取时用它是自然写法），不该因此失败。"""
    raw = bytearray("正文。".encode())

    assert decode_document_bytes(raw, source_file="a.txt") == "正文。"


def test_bom_survives_decoding_and_is_stripped_by_normalization():
    """分工的证据：解码只负责「字节 → 文本」，BOM 由归一化那一步去掉。

    两处都做同一件事，只会在某次改动之后变得不一致。UTF-8 的 BOM
    （EF BB BF）解码出来就是 U+FEFF，所以这一条同时验了两件事：
    解码没有偷偷剥它，归一化确实剥掉了它。
    """
    raw = "﻿# 标题".encode()

    decoded = decode_document_bytes(raw, source_file="a.md")

    assert decoded.startswith("﻿")
    assert normalize_document_content(decoded) == "# 标题"


def test_empty_bytes_decode_to_an_empty_string_not_an_error():
    """空字节不算解码错误——「内容为空」是另一层该判的事。

    在这里报错的话，上层就分不清「文件解不开」和「文件是空的」，
    而这两种情况给用户的提示完全不同（一个让他重新导出，一个让他检查文件）。
    """
    assert decode_document_bytes(b"", source_file="a.md") == ""


def test_gbk_bytes_are_rejected():
    """GBK 编码的中文解不出合法 UTF-8。

    这是最常见的一种「打开看着正常、传上来就乱码」：Windows 上另存为
    ANSI 就会得到这种字节。严格解码让它**当场失败**，而不是让用户
    拿到一个正文全是 `�` 的「入库成功」。
    """
    raw = "订单口径说明".encode("gbk")

    with pytest.raises(UndecodableDocumentError) as error:
        decode_document_bytes(raw, source_file="订单.md")

    # 提示要能指导下一步动作，而不是只说「失败了」
    assert "UTF-8" in str(error.value)
    assert "订单.md" in str(error.value)


def test_binary_content_is_rejected():
    """误传的二进制文件（图片、压缩包）会在这一步被挡住。"""
    png_header = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"

    with pytest.raises(UndecodableDocumentError):
        decode_document_bytes(png_header, source_file="logo.png")


def test_decode_error_does_not_leak_the_original_bytes():
    """异常消息里不带出错字节的原文与位置。

    那些字节用户改不了，写出来对他没有帮助，却是一段不好解释的内部细节。
    """
    raw = "订单口径".encode("gbk")

    with pytest.raises(UndecodableDocumentError) as error:
        decode_document_bytes(raw, source_file="a.md")

    message = str(error.value)
    assert "0x" not in message
    assert "position" not in message
    assert "byte" not in message.lower()


@pytest.mark.parametrize("bad", ["已经是字符串", None, 42, ["md"]])
def test_non_bytes_input_is_rejected(bad):
    """传进来的必须真的是字节；顺手把 str 当字节收下会掩盖调用方的 bug。"""
    with pytest.raises(UndecodableDocumentError):
        decode_document_bytes(bad, source_file="a.md")


def test_decoding_is_idempotent_when_re_encoded():
    """解码 → 编码 → 再解码，结果不变。上传重试时走的就是这条路径。"""
    original = "# 订单口径\r\n\r\n## 1. 订单数\r\n\r\n正文。"

    once = decode_document_bytes(original.encode(), source_file="a.md")
    twice = decode_document_bytes(once.encode(), source_file="a.md")

    assert once == twice == original
