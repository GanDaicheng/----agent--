"""文件处理器（字节 → 文本）的测试。

**不连数据库、不调模型、不读网络。** 被测的是纯函数与本地解析，
docx / pdf 的输入由 tests/document_fixtures.py 现场生成。

这个文件要守住的核心是一条**架构约定**：
`document_processors` 只能把字节变成文本，不许碰数据库、配置和模型。
它一破例，「提取文本」这件事就会莫名其妙地依赖运行环境。有 AST 测试盯着。
"""

import pathlib
import sys

import pytest

from app.services.document_normalization import UndecodableDocumentError
from app.services.document_processors import (
    DOCX_UPLOAD_TYPE,
    MARKDOWN_CHUNK_TYPE,
    MARKDOWN_UPLOAD_TYPE,
    PDF_UPLOAD_TYPE,
    PLAIN_TEXT_CHUNK_TYPE,
    PLAIN_TEXT_UPLOAD_TYPE,
    SUPPORTED_UPLOAD_TYPES,
    DocumentParseError,
    NoExtractableTextError,
    PdfLine,
    UnsupportedUploadTypeError,
    _body_size,
    _is_paragraph_break,
    _normal_gap,
    _pdf_lines_to_markdown,
    extract_document_text,
    normalize_upload_type,
)

from .document_fixtures import (
    BODY,
    HEADING1,
    HEADING2,
    TABLE,
    TITLE,
    build_docx,
    build_docx_with_font_sized_paragraphs,
    build_pdf,
)

# ==========================================================================
# 1. 上传类型归一
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
        ("docx", "docx"),
        (".DOCX", "docx"),
        ("  .Docx  ", "docx"),
        ("pdf", "pdf"),
        (".pdf", "pdf"),
        ("PDF", "pdf"),
    ],
)
def test_upload_type_variants_are_normalized(raw, expected):
    assert normalize_upload_type(raw) == expected


@pytest.mark.parametrize("bad", ["xlsx", "csv", ".pptx", "doc", "markdown", "", "  "])
def test_unsupported_upload_types_are_rejected(bad):
    """不支持的类型当场报错，不猜默认值。

    把 docx 当纯文本解码，出来的是一堆二进制乱码，而且会真的入库、
    真的算向量、真的被检索到——宁可失败。
    """
    with pytest.raises(UnsupportedUploadTypeError) as error:
        normalize_upload_type(bad)

    # 错误信息要能自己说清支持什么，不用去翻源码
    for supported in SUPPORTED_UPLOAD_TYPES:
        assert supported in str(error.value)


@pytest.mark.parametrize("bad", [None, 3, b"pdf", ["pdf"]])
def test_non_string_upload_types_are_rejected(bad):
    with pytest.raises(UnsupportedUploadTypeError):
        normalize_upload_type(bad)


def test_supported_upload_types_is_the_documented_set():
    """上传类型比切片类型多两个——这正是本次扩展的全部内容。"""
    assert SUPPORTED_UPLOAD_TYPES == ("md", "txt", "docx", "pdf")


# ==========================================================================
# 2. 分发：每个处理器声明自己的切片类型
# ==========================================================================


@pytest.mark.parametrize(
    ("upload_type", "expected_chunk_type"),
    [
        (MARKDOWN_UPLOAD_TYPE, MARKDOWN_CHUNK_TYPE),
        (PLAIN_TEXT_UPLOAD_TYPE, PLAIN_TEXT_CHUNK_TYPE),
        # docx / pdf 被还原成 Markdown，所以按 Markdown 切片——
        # 这是「不重写切片与入库逻辑」的关键。
        (DOCX_UPLOAD_TYPE, MARKDOWN_CHUNK_TYPE),
        (PDF_UPLOAD_TYPE, MARKDOWN_CHUNK_TYPE),
    ],
)
def test_each_processor_declares_its_chunk_type(upload_type, expected_chunk_type):
    raw = (
        build_docx([(BODY, "正文")])
        if upload_type == DOCX_UPLOAD_TYPE
        else build_pdf([(11.0, 14.0, "body line")])
        if upload_type == PDF_UPLOAD_TYPE
        else "正文。".encode()
    )

    processed = extract_document_text(
        raw, source_file=f"a.{upload_type}", file_type=upload_type
    )

    assert processed.chunk_type == expected_chunk_type


def test_unknown_type_raises_instead_of_returning_empty_text():
    """分发器拿到没归一过的类型要立刻炸，不能静默返回空文本。

    静默返回空会让「传了一份 pptx」表现得像「文档是空的」，排查方向完全错了。
    """
    with pytest.raises(UnsupportedUploadTypeError):
        extract_document_text(b"x", source_file="a.pptx", file_type="pptx")


# ==========================================================================
# 3. md / txt：解码即提取
# ==========================================================================


def test_markdown_is_decoded_not_parsed():
    processed = extract_document_text(
        "# 订单口径\n\n## 1. 订单数\n\n正文。".encode(),
        source_file="orders.md",
        file_type=MARKDOWN_UPLOAD_TYPE,
    )

    assert processed.text == "# 订单口径\n\n## 1. 订单数\n\n正文。"


def test_bom_survives_extraction_and_is_stripped_later():
    """分工的证据：提取只负责「字节 → 文本」，BOM 由归一化那一步去掉。

    这一层要是顺手把 BOM 剥了，就会和 normalize_document_content 做同一件事，
    两处规则早晚不一致。
    """
    processed = extract_document_text(
        "﻿# 标题".encode(), source_file="a.md", file_type=MARKDOWN_UPLOAD_TYPE
    )

    assert processed.text.startswith("﻿")


def test_gbk_bytes_are_rejected_for_md():
    """GBK 编码的中文解不出合法 UTF-8，当场报错而不是塞一堆乱码进库。"""
    with pytest.raises(UndecodableDocumentError):
        extract_document_text(
            "订单口径".encode("gbk"),
            source_file="订单.md",
            file_type=MARKDOWN_UPLOAD_TYPE,
        )


def test_text_extraction_does_not_touch_content_otherwise():
    """提取不改行内内容：缩进、空行、行尾空格都原样保留。

    那些是切片器 clean_markdown_body 的职责，两处都做只会在某次改动后不一致。
    """
    original = "第一行\n\n\n  缩进的第二行   \n"

    processed = extract_document_text(
        original.encode(), source_file="a.txt", file_type=PLAIN_TEXT_UPLOAD_TYPE
    )

    assert processed.text == original


# ==========================================================================
# 4. docx：样式 → Markdown 标题层级
# ==========================================================================


def test_docx_maps_title_and_headings_to_the_right_levels():
    """本次最关键的一条映射。

    Word 的「标题 1」在语义上对应 Markdown 的 H2，不是 H1：
    切片器只认第一个 `#` 当文档标题，若把每个标题 1 都写成 `#`，
    整篇 Word 文档会退化成只有一个巨大的「文档元信息」切片。
    """
    raw = build_docx(
        [
            (TITLE, "零售指标口径说明"),
            (BODY, "本文档定义核心指标口径。"),
            (HEADING1, "销售额"),
            (BODY, "销售额 = SUM(orders.net_amount)"),
            (HEADING2, "下钻维度"),
            (BODY, "日期、区域、商品。"),
        ]
    )

    processed = extract_document_text(raw, source_file="spec.docx", file_type=DOCX_UPLOAD_TYPE)

    assert processed.text == (
        "# 零售指标口径说明"
        "\n\n"
        "本文档定义核心指标口径。"
        "\n\n"
        "## 销售额"
        "\n\n"
        "销售额 = SUM(orders.net_amount)"
        "\n\n"
        "### 下钻维度"
        "\n\n"
        "日期、区域、商品。"
    )


def test_docx_paragraphs_are_separated_by_blank_lines():
    """段落之间必须有空行。

    没有空行的话，切片器遇到超长小节时无从下刀（它只按空行分段），
    整节会变成一个撑满上百行的巨型切片——检索质量会明显变差。
    """
    raw = build_docx([(BODY, "第一段。"), (BODY, "第二段。"), (BODY, "第三段。")])

    processed = extract_document_text(raw, source_file="a.docx", file_type=DOCX_UPLOAD_TYPE)

    assert processed.text == "第一段。\n\n第二段。\n\n第三段。"


def test_docx_heading_style_wins_over_font_size():
    """判定只看样式，不看字号。

    正文样式的段落哪怕调成 28 磅也不算标题——字号是排版，
    样式才是作者表达的「这是标题」。按字号猜是 PDF 才不得不做的事。
    """
    raw = build_docx_with_font_sized_paragraphs()

    processed = extract_document_text(raw, source_file="a.docx", file_type=DOCX_UPLOAD_TYPE)

    assert processed.text == "看起来像标题，但样式是正文"


def test_docx_table_becomes_a_markdown_table():
    """表格必须保留：Word 里的字段说明、口径对照绝大多数是表格形式。

    跳过表格等于把最有信息量的部分丢掉，而且丢得无声无息——
    用户只会发现「问文档里明明写了的东西，它答不出来」。
    """
    raw = build_docx(
        [
            (HEADING1, "订单事实表"),
            (
                TABLE,
                [["字段", "说明"], ["net_amount", "实付金额"], ["gross_amount", "应收金额"]],
            ),
        ]
    )

    processed = extract_document_text(raw, source_file="a.docx", file_type=DOCX_UPLOAD_TYPE)

    assert processed.text == (
        "## 订单事实表"
        "\n\n"
        "| 字段 | 说明 |\n"
        "| --- | --- |\n"
        "| net_amount | 实付金额 |\n"
        "| gross_amount | 应收金额 |"
    )


def test_docx_table_rows_are_not_split_by_blank_lines():
    """表格内部不能有空行。

    切片器按空行分块，一张表被空行拆开，表头和表体就可能落进不同切片。
    """
    raw = build_docx([(TABLE, [["字段", "说明"], ["a", "b"], ["c", "d"]])])

    processed = extract_document_text(raw, source_file="a.docx", file_type=DOCX_UPLOAD_TYPE)

    assert "\n\n" not in processed.text
    assert len(processed.text.splitlines()) == 4


def test_docx_table_keeps_its_position_in_the_document():
    """表格要留在它在文档里的位置，不能被挪到末尾。

    python-docx 的 document.paragraphs 与 document.tables 是两个独立列表，
    分开遍历会把所有表格排到最后——那样「这张表属于哪一节」的上下文就错位了。
    """
    raw = build_docx(
        [
            (HEADING1, "第一节"),
            (TABLE, [["甲", "乙"]]),
            (HEADING1, "第二节"),
        ]
    )

    processed = extract_document_text(raw, source_file="a.docx", file_type=DOCX_UPLOAD_TYPE)

    assert processed.text.index("## 第一节") < processed.text.index("| 甲") < processed.text.index("## 第二节")


def test_docx_table_cells_escape_pipes():
    """单元格里的竖线必须转义，否则会把表格结构撑坏。"""
    raw = build_docx([(TABLE, [["表达式"], ["a | b"]])])

    processed = extract_document_text(raw, source_file="a.docx", file_type=DOCX_UPLOAD_TYPE)

    assert r"a \| b" in processed.text


def test_docx_empty_document_extracts_to_empty_text():
    """空 docx 提取出空文本，交给下游判「内容为空」——本层不替它做决定。"""
    processed = extract_document_text(
        build_docx([]), source_file="a.docx", file_type=DOCX_UPLOAD_TYPE
    )

    assert processed.text == ""


def test_docx_corrupt_bytes_raise_a_parse_error():
    """坏文件统一收口成 DocumentParseError，不把底层异常类型漏出去。"""
    with pytest.raises(DocumentParseError) as error:
        extract_document_text(
            b"this is definitely not a docx", source_file="a.docx", file_type=DOCX_UPLOAD_TYPE
        )

    assert "a.docx" in str(error.value)


def test_docx_parse_error_does_not_leak_library_internals():
    """错误文案是给用户看的，不带库的内部细节。"""
    with pytest.raises(DocumentParseError) as error:
        extract_document_text(b"\x00\x01\x02", source_file="a.docx", file_type=DOCX_UPLOAD_TYPE)

    message = str(error.value)
    assert "zipfile" not in message
    assert "lxml" not in message
    assert "Traceback" not in message


# ==========================================================================
# 5. pdf：字号启发式（纯函数，逐条钉住规则）
# ==========================================================================


def make_lines(entries: list[tuple[float, float, str]]) -> list[PdfLine]:
    """把 (字号, top, 文本) 拼成 PdfLine；bottom 按「top + 字号」估算。"""
    return [
        PdfLine(size=size, text=text, top=top, bottom=top + size)
        for size, top, text in entries
    ]


def test_body_size_is_the_size_covering_the_most_text():
    """正文字号按覆盖的字符数定，不取平均。

    一份「标题很大、正文很小」的文档，平均值会落在两者之间，
    而那个字号在文档里根本不存在，拿它当基准比出来的层级全是错的。
    """
    lines = make_lines(
        [
            (20.0, 0.0, "标题"),
            (11.0, 30.0, "这是第一行正文，比较长。"),
            (11.0, 45.0, "这是第二行正文，也比较长。"),
        ]
    )

    assert _body_size(lines) == 11.0


def test_body_size_breaks_line_count_ties_by_text_length():
    """行数打平时按字符数决出胜负——结果不能依赖谁先出现。

    短文档里「2 行标题 vs 2 行正文」在行数上是平手。若按行数取众数，
    平局时谁赢只取决于插入顺序，同一份文档换个顺序就得出不同的正文字号，
    标题层级随之全变。字符数不会打平：标题是几个字，正文是几十个字一行。
    """
    headings = [(16.0, 0.0, "第一章"), (16.0, 20.0, "第二章")]
    bodies = [
        (11.0, 40.0, "这是一行比较长的正文内容，用来拉开差距。"),
        (11.0, 55.0, "这是另一行比较长的正文内容，也用来拉开差距。"),
    ]

    assert _body_size(make_lines(headings + bodies)) == 11.0
    assert _body_size(make_lines(bodies + headings)) == 11.0


def test_body_size_of_size_less_lines_is_zero():
    """取不到字号时返回 0，由调用方降级处理，不抛异常。"""
    assert _body_size([PdfLine(size=0.0, text="x", top=0.0, bottom=0.0)]) == 0.0
    assert _body_size([]) == 0.0


def test_pdf_biggest_line_becomes_the_document_title():
    lines = make_lines(
        [
            (22.0, 0.0, "Big Title"),
            (11.0, 40.0, "This is the body text of the document."),
            (11.0, 55.0, "And a second body line right here."),
        ]
    )

    assert _pdf_lines_to_markdown(lines).splitlines()[0] == "# Big Title"


def test_pdf_medium_line_becomes_a_section_heading():
    """比正文大、但没到标题级别的，是小节——这是切片的主边界。

    14 磅夹在两个阈值之间：14/11 = 1.27，够 1.15（小节）但不够 1.35（标题）。
    """
    lines = make_lines(
        [
            (11.0, 0.0, "body one is here"),
            (14.0, 20.0, "Section"),
            (11.0, 40.0, "body two is here"),
        ]
    )

    markdown = _pdf_lines_to_markdown(lines)
    # 按行判断层级：`## Section` 里含 "# " 这个子串，数子串会误判
    titles = [line for line in markdown.splitlines() if line.startswith("# ")]

    assert "## Section" in markdown
    assert titles == []


def test_pdf_body_lines_get_no_markup():
    lines = make_lines([(11.0, 0.0, "plain body line")])

    assert _pdf_lines_to_markdown(lines) == "plain body line"


def test_pdf_only_the_first_big_line_becomes_the_title():
    """第二个大字号行降级成小节。

    Markdown 只允许一个文档标题（切片器只认第一个 `#`），
    出现两个大标题时把第二个也写成 `#`，它就会掉进正文里丢掉结构。
    """
    lines = make_lines(
        [
            (22.0, 0.0, "First Big"),
            (11.0, 40.0, "body line number one"),
            (11.0, 55.0, "body line number two"),
            (22.0, 70.0, "Second Big"),
        ]
    )

    markdown = _pdf_lines_to_markdown(lines)
    # 只数一级标题：`## Second Big` 里也含 "# " 这个子串，不能直接数子串
    titles = [line for line in markdown.splitlines() if line.startswith("# ")]

    assert titles == ["# First Big"]
    assert "## Second Big" in markdown


def test_pdf_normal_gap_is_the_mode_of_the_gaps():
    """常规行距由文档自己算，不写死磅值——10pt 和 18pt 正文的行距差得远。"""
    lines = make_lines(
        [(11.0, 0.0, "a"), (11.0, 14.0, "b"), (11.0, 28.0, "c"), (11.0, 70.0, "d")]
    )

    # 空档是 3、3、31（top 差减去上一行高度），众数是 3
    assert _normal_gap(lines) == 3.0


def test_pdf_gap_without_enough_data_returns_zero():
    """行数不够就算不出常规行距，返回 0 让调用方放弃断段。"""
    assert _normal_gap(make_lines([(11.0, 0.0, "only")])) == 0.0


def test_paragraph_break_needs_a_gap_bigger_than_normal_leading():
    normal = 3.0
    tight = (
        PdfLine(size=11.0, text="a", top=0.0, bottom=11.0),
        PdfLine(size=11.0, text="b", top=14.0, bottom=25.0),
    )
    loose = (
        PdfLine(size=11.0, text="a", top=0.0, bottom=11.0),
        PdfLine(size=11.0, text="b", top=40.0, bottom=51.0),
    )

    assert _is_paragraph_break(*tight, normal) is False
    assert _is_paragraph_break(*loose, normal) is True


def test_paragraph_break_is_off_when_leading_cannot_be_calibrated():
    """算不出常规行距时一律不断段。

    宁可少断几段，也不要因为一个瞎猜的阈值把一整段话切成好几截。
    """
    previous = PdfLine(size=11.0, text="a", top=0.0, bottom=11.0)
    current = PdfLine(size=11.0, text="b", top=500.0, bottom=511.0)

    assert _is_paragraph_break(previous, current, 0.0) is False


# ==========================================================================
# 6. pdf：真实字节 → Markdown
# ==========================================================================


def test_pdf_bytes_are_extracted_into_markdown():
    raw = build_pdf(
        [
            (22.0, 40.0, "Retail Metrics Specification"),
            (11.0, 14.0, "First paragraph line one."),
            (11.0, 14.0, "First paragraph line two."),
            (11.0, 30.0, "First paragraph line three."),
            (15.0, 20.0, "Section One"),
            (11.0, 14.0, "Body after the heading."),
        ]
    )

    processed = extract_document_text(raw, source_file="spec.pdf", file_type=PDF_UPLOAD_TYPE)

    assert processed.chunk_type == MARKDOWN_CHUNK_TYPE
    assert processed.text == (
        "# Retail Metrics Specification"
        "\n\n"
        "First paragraph line one.\n"
        "First paragraph line two.\n"
        "First paragraph line three."
        "\n\n"
        "## Section One"
        "\n\n"
        "Body after the heading."
    )


def test_pdf_without_a_text_layer_is_reported_as_no_text():
    """扫描件（整页是图片）在 PDF 里没有文字对象。

    这**不是**「文档是空的」——文件里有内容，内容是图片。两种情况用户该做的事不同：
    一个是去检查文件写完了没有，一个是换文件或先 OCR。所以是两种异常。
    """
    with pytest.raises(NoExtractableTextError) as error:
        extract_document_text(
            build_pdf([]), source_file="scan.pdf", file_type=PDF_UPLOAD_TYPE
        )

    message = str(error.value)
    assert "scan.pdf" in message
    assert "扫描件" in message
    assert "OCR" in message


def test_pdf_corrupt_bytes_raise_a_parse_error():
    with pytest.raises(DocumentParseError) as error:
        extract_document_text(
            b"%PDF-1.4\nthis is not really a pdf", source_file="a.pdf", file_type=PDF_UPLOAD_TYPE
        )

    assert "a.pdf" in str(error.value)


def test_pdf_parse_error_mentions_encryption():
    """加密的 PDF 也走这条分支，文案里要提一句，否则用户查错方向。"""
    with pytest.raises(DocumentParseError) as error:
        extract_document_text(b"\x00\x01\x02", source_file="a.pdf", file_type=PDF_UPLOAD_TYPE)

    assert "加密" in str(error.value)
    assert "pdfminer" not in str(error.value)


# ==========================================================================
# 7. 依赖边界：这一层只做文本提取
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


@pytest.mark.parametrize(
    "forbidden_prefix",
    [
        "app.repositories",  # 数据库
        "app.core.config",  # 配置
        "app.core.llm",  # 模型
        "app.api",  # HTTP 层
        "sqlalchemy",
        "asyncpg",
        "openai",
        "httpx",
    ],
)
def test_processors_do_not_reach_for_external_systems(forbidden_prefix):
    """处理器只做「字节 → 文本」。

    它一旦够得着数据库或配置，「提取文本」就会莫名其妙地依赖运行环境，
    而且这一层将被上传接口直接调用，多一个依赖就多一条启动期的失败路径。
    """
    from app.services import document_processors

    modules = _imported_modules(pathlib.Path(document_processors.__file__))
    offenders = [module for module in modules if module.startswith(forbidden_prefix)]

    assert not offenders, f"文件处理器不该依赖 {forbidden_prefix}：{offenders}"


def test_processors_may_depend_on_the_normalization_layer():
    """反向确认：它**应该**复用 document_normalization 的解码，而不是自己写一份。"""
    from app.services import document_processors

    modules = _imported_modules(pathlib.Path(document_processors.__file__))

    assert any(module.startswith("app.services.document_normalization") for module in modules)


def test_processors_only_use_third_party_libraries_for_parsing():
    """允许的第三方依赖就是那两个解析库，别的都不许进来。"""
    from app.services import document_processors

    modules = _imported_modules(pathlib.Path(document_processors.__file__))
    third_party = {
        module.split(".")[0]
        for module in modules
        if module.split(".")[0] not in sys.stdlib_module_names
        and not module.startswith("app")
    }

    assert third_party <= {"docx", "pdfplumber"}, f"多出来的依赖：{third_party}"
