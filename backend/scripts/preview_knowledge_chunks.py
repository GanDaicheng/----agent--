"""切片预览：把知识库文档切一遍，打印每个 chunk 的摘要，供人工检查切片质量。

用法（在 backend/ 或项目根目录下执行都可以）：

    python backend/scripts/preview_knowledge_chunks.py
    cd backend && python scripts/preview_knowledge_chunks.py

这是**纯预览**：只读 Markdown 文件、只打印结果。
不调用 embedding 接口、不连接数据库、不写任何文件、不产生任何费用。
可以放心反复运行——切片策略调一次、跑一次看效果，正是它存在的意义。

输出只给每个 chunk 的前 80 个字符和 8 位 hash，不打印完整正文：
整篇文档打在终端里既看不清结构，也没法横向比较切片长度的分布。
"""

import re
import sys
from pathlib import Path

# 直接以 `python scripts/preview_knowledge_chunks.py` 运行时，sys.path[0] 是 scripts/
# 而不是 backend/，会导致 `import app` 失败。与 seed 脚本用同一种处理方式。
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.paths import BACKEND_DIR as _BACKEND_DIR  # noqa: E402
from app.services.knowledge_chunking import (  # noqa: E402
    MAX_SECTION_CHARS,
    KnowledgeChunk,
    knowledge_document_paths,
    load_knowledge_chunks,
)

DEFAULT_DIRECTORY = _BACKEND_DIR / "knowledge_seed"

# 预览长度。80 个字符足够看出这是什么内容，又不至于把终端刷爆。
PREVIEW_CHARS = 80
HASH_PREFIX = 8


def preview_text(content: str, limit: int = PREVIEW_CHARS) -> str:
    """把正文压成一行短预览：换行和连续空白都收成一个空格。"""
    flattened = re.sub(r"\s+", " ", content).strip()
    if len(flattened) <= limit:
        return flattened
    return flattened[:limit] + "…"


def print_chunk(chunk: KnowledgeChunk) -> None:
    print(
        f"[{chunk.source_file}] #{chunk.chunk_index}  {chunk.section_title}"
    )
    print(
        f"     字符 {chunk.char_count:>5}   估算 token {chunk.estimated_token_count:>5}"
        f"   hash {chunk.content_hash[:HASH_PREFIX]}"
    )
    print(f"     预览: {preview_text(chunk.content)}")


def main() -> int:
    directory = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIRECTORY

    if not directory.is_dir():
        print(f"目录不存在：{directory}")
        return 1

    paths = knowledge_document_paths(directory)
    if not paths:
        print(f"目录下没有 Markdown 文件：{directory}")
        return 1

    chunks = load_knowledge_chunks(directory)

    print("知识文档切片预览")
    print("=" * 64)
    print(f"扫描目录    {directory}")
    print(f"文档数量    {len(paths)}")
    print(f"chunk 总数  {len(chunks)}")
    print(f"切片上限    {MAX_SECTION_CHARS} 字符（超过才按段落二次切分）")

    print("-" * 64)
    print("每个文件的 chunk 数：")
    for path in paths:
        file_chunks = [chunk for chunk in chunks if chunk.source_file == path.name]
        total_chars = sum(chunk.char_count for chunk in file_chunks)
        average = total_chars // len(file_chunks) if file_chunks else 0
        print(
            f"  {path.name:<30} {len(file_chunks):>3} chunks"
            f"   平均 {average:>5} 字符"
        )

    print("-" * 64)
    print("逐条明细：")
    print()
    for chunk in chunks:
        print_chunk(chunk)

    oversized = [chunk for chunk in chunks if chunk.char_count > MAX_SECTION_CHARS]
    print("=" * 64)
    if oversized:
        print(f"⚠ 超过 {MAX_SECTION_CHARS} 字符的 chunk 有 {len(oversized)} 个：")
        for chunk in oversized:
            print(
                f"    [{chunk.source_file}] #{chunk.chunk_index} {chunk.section_title}"
                f"  {chunk.char_count} 字符"
            )
    else:
        print(f"没有超过 {MAX_SECTION_CHARS} 字符的 chunk。")

    longest = max(chunks, key=lambda item: item.char_count)
    print(
        f"最长的 chunk：[{longest.source_file}] #{longest.chunk_index} "
        f"{longest.section_title}  {longest.char_count} 字符 / "
        f"估算 {longest.estimated_token_count} token"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
