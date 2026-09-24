"""元数据回填脚本的测试。

**本文件不连接 PostgreSQL、不调真实模型。** 脚本的数据库读写被替换成记录器：
- `fetch_chunks` 换成返回预设行的假函数；
- `write_batch` 换成记录器（否则它会去开真事务）；
- 提取器通过 backfill(extractor=...) 注入替身。

脚本本身被刻意切成「纯函数 + 可替换的 I/O」两部分，就是为了让这些断言不必依赖
一个真库：判断「还没处理过」的规则、限流、筛选、汇总都是纯函数，可以逐条断言。

另有一条测试真的用子进程跑一次 --help，验证两种调用方式（项目根 / backend 目录）
都能启动——这个检查只有真起一个进程才算数，importlib 加载证明不了它。

保持项目约定：pytest 不需要 PostgreSQL。
"""

import asyncio
import dataclasses
import importlib.util
import pathlib
import subprocess
import sys

import pytest

from app.services.knowledge_metadata import (
    KnowledgeSearchMetadata,
    build_base_search_text,
    build_enriched_search_text,
)

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
SCRIPT = BACKEND_DIR / "scripts" / "backfill_knowledge_metadata.py"

FAKE_KEY = "sk-fake-backfill-key-for-tests-0123456789"

TITLE = "指标口径说明"
SECTION = "订单数"
BODY = "订单数用 COUNT(DISTINCT order_no) 计算。"


def load_script():
    spec = importlib.util.spec_from_file_location("backfill_knowledge_metadata_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------
# 替身
# --------------------------------------------------------------------------


class FakeExtractor:
    """记录每个被问到的切片，返回可辨识的元数据。"""

    def __init__(self, *, error=None, succeeded: bool = True, tag: str = "关键词") -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.error = error
        self.succeeded = succeeded
        self.tag = tag

    @property
    def call_count(self) -> int:
        return len(self.calls)

    async def __call__(self, document_title, section_title, content):
        self.calls.append((document_title, section_title, content))

        if self.error is not None:
            raise self.error

        if not self.succeeded:
            return KnowledgeSearchMetadata(
                keywords=(),
                aliases=(),
                search_text=build_base_search_text(document_title, section_title, content),
                extraction_succeeded=False,
            )

        keywords = (f"{self.tag}甲",)
        aliases = (f"{self.tag}乙",)
        return KnowledgeSearchMetadata(
            keywords=keywords,
            aliases=aliases,
            search_text=build_enriched_search_text(
                document_title, section_title, content, keywords, aliases
            ),
            extraction_succeeded=True,
        )


class ScriptEnv:
    """把脚本的数据库读写换掉，并记录写入了什么。"""

    def __init__(self, monkeypatch, rows) -> None:
        self.script = load_script()
        self.rows = list(rows)
        self.write_batches: list[list] = []
        self.requested_source_files: list = []

        async def fetch_chunks(*, source_file=None):
            self.requested_source_files.append(source_file)
            return list(self.rows)

        async def write_batch(entries):
            self.write_batches.append(list(entries))

        monkeypatch.setattr(self.script, "fetch_chunks", fetch_chunks)
        monkeypatch.setattr(self.script, "write_batch", write_batch)

    @property
    def written_entries(self) -> list[tuple[int, KnowledgeSearchMetadata]]:
        return [entry for batch in self.write_batches for entry in batch]

    @property
    def written_ids(self) -> list[int]:
        return [chunk_id for chunk_id, _ in self.written_entries]

    @property
    def batch_sizes(self) -> list[int]:
        return [len(batch) for batch in self.write_batches]

    def run(self, **kwargs):
        kwargs.setdefault("extractor", FakeExtractor())
        return asyncio.run(self.script.backfill(**kwargs))


def make_row(
    *,
    chunk_id: int,
    source_file: str = "a.md",
    document_title: str = TITLE,
    section_title: str = SECTION,
    content: str = BODY,
    search_text: str | None = None,
):
    """构造一行候选。search_text 不给就默认是基础版本（= 待处理）。"""
    script = load_script()
    return script.PendingChunk(
        chunk_id=chunk_id,
        source_file=source_file,
        document_title=document_title,
        section_title=section_title,
        content=content,
        search_text=(
            build_base_search_text(document_title, section_title, content)
            if search_text is None
            else search_text
        ),
    )


def enriched_text(
    document_title: str = TITLE,
    section_title: str = SECTION,
    content: str = BODY,
    keywords=(),
    aliases=(),
) -> str:
    return build_enriched_search_text(
        document_title, section_title, content, keywords, aliases
    )


# --------------------------------------------------------------------------
# 判断「还没处理过」
# --------------------------------------------------------------------------


def test_a_chunk_still_holding_the_base_text_is_pending():
    row = make_row(chunk_id=1)

    assert row.is_pending is True
    assert row.search_text == row.base_search_text


def test_a_chunk_holding_the_enriched_text_is_not_pending():
    row = make_row(chunk_id=1, search_text=enriched_text(keywords=("甲",)))

    assert row.is_pending is False


def test_an_enriched_chunk_with_empty_lists_is_not_pending():
    """★ 提取成功但两个数组都是空的，也是「处理过了」。

    这正是不能用 `keywords = [] AND aliases = []` 当判据的原因：
    那种切片是合法结果，用空数组判断会让它每次都被重复处理。
    """
    row = make_row(chunk_id=1, search_text=enriched_text(keywords=(), aliases=()))

    assert row.is_pending is False


def test_default_run_only_touches_pending_chunks(monkeypatch):
    env = ScriptEnv(
        monkeypatch,
        [
            make_row(chunk_id=1),
            make_row(chunk_id=2, search_text=enriched_text(keywords=("甲",))),
        ],
    )
    extractor = FakeExtractor()

    summary = env.run(extractor=extractor)

    assert summary.scanned == 2
    assert summary.pending == 1
    assert summary.updated == 1
    assert summary.skipped == 1
    assert env.written_ids == [1]
    assert extractor.call_count == 1


def test_default_run_never_overwrites_enriched_data(monkeypatch):
    """★ 没有 --refresh 时，已处理的切片一个字都不能被改写。"""
    original = enriched_text(keywords=("原来的关键词",))
    env = ScriptEnv(monkeypatch, [make_row(chunk_id=1, search_text=original)])

    summary = env.run(extractor=FakeExtractor(tag="新的"))

    assert summary.updated == 0
    assert env.write_batches == []


def test_refresh_reprocesses_everything_in_scope(monkeypatch):
    env = ScriptEnv(
        monkeypatch,
        [
            make_row(chunk_id=1, search_text=enriched_text(keywords=("旧",))),
            make_row(chunk_id=2),
        ],
    )
    extractor = FakeExtractor()

    summary = env.run(refresh=True, extractor=extractor)

    assert summary.pending == 2
    assert summary.updated == 2
    assert summary.skipped == 0
    assert extractor.call_count == 2
    assert env.written_ids == [1, 2]


def test_select_targets_is_a_pure_function():
    script = load_script()
    rows = [make_row(chunk_id=1), make_row(chunk_id=2, search_text=enriched_text())]

    assert [row.chunk_id for row in script.select_targets(rows, refresh=False, limit=None)] == [1]
    assert [row.chunk_id for row in script.select_targets(rows, refresh=True, limit=None)] == [1, 2]


# --------------------------------------------------------------------------
# 限流与筛选
# --------------------------------------------------------------------------


def test_limit_caps_the_number_of_processed_chunks(monkeypatch):
    env = ScriptEnv(monkeypatch, [make_row(chunk_id=i) for i in range(1, 6)])

    summary = env.run(limit=2)

    assert summary.pending == 2
    assert env.written_ids == [1, 2]


def test_limit_applies_to_pending_rows_not_to_the_first_rows(monkeypatch):
    """★ --limit 的语义是「处理 N 条待处理的」，不是「在前 N 条里挑待处理的」。

    反过来写在前面堆着已处理的行时，--limit 5 可能一条也处理不到——
    用户以为限制了花费，实际什么都没做。
    """
    env = ScriptEnv(
        monkeypatch,
        [
            make_row(chunk_id=1, search_text=enriched_text()),
            make_row(chunk_id=2, search_text=enriched_text()),
            make_row(chunk_id=3, search_text=enriched_text()),
            make_row(chunk_id=4),
            make_row(chunk_id=5),
        ],
    )

    summary = env.run(limit=2)

    assert summary.pending == 2
    assert env.written_ids == [4, 5]


def test_source_file_is_passed_through_to_the_query(monkeypatch):
    env = ScriptEnv(monkeypatch, [make_row(chunk_id=1, source_file="retail_metrics.md")])

    env.run(source_file="retail_metrics.md")

    assert env.requested_source_files == ["retail_metrics.md"]


def test_source_file_filter_is_an_exact_match():
    """★ 只动指定那一份文档：不做 LIKE、不做前缀匹配。"""
    script = load_script()

    filtered = str(script._chunk_query(source_file="retail_metrics.md"))
    unfiltered = str(script._chunk_query(source_file=None))

    assert "knowledge_documents.source_file = " in filtered
    assert "source_file" not in unfiltered.split("FROM")[1]
    assert "LIKE" not in filtered.upper()
    assert "retail_metrics.md" not in filtered  # 值走绑定参数，不拼进语句


@pytest.mark.parametrize("value", ["0", "-1", "-100", "abc", "1.5", ""])
def test_invalid_limit_is_rejected(value):
    with pytest.raises(SystemExit) as error:
        load_script().parse_args(["--limit", value])

    assert error.value.code == 2  # argparse 的用法错误退出码


@pytest.mark.parametrize("value", ["1", "5", "100"])
def test_valid_limit_is_accepted(value):
    assert load_script().parse_args(["--limit", value]).limit == int(value)


def test_batch_size_must_be_positive_too():
    with pytest.raises(SystemExit):
        load_script().parse_args(["--batch-size", "0"])


# --------------------------------------------------------------------------
# dry-run
# --------------------------------------------------------------------------


def test_dry_run_calls_no_model(monkeypatch):
    env = ScriptEnv(monkeypatch, [make_row(chunk_id=1), make_row(chunk_id=2)])
    extractor = FakeExtractor()

    summary = env.run(dry_run=True, extractor=extractor)

    assert summary.dry_run is True
    assert extractor.call_count == 0


def test_dry_run_writes_nothing(monkeypatch):
    env = ScriptEnv(monkeypatch, [make_row(chunk_id=1)])

    summary = env.run(dry_run=True)

    assert summary.updated == 0
    assert env.write_batches == []


def test_dry_run_reports_pending_counts_by_source_file(monkeypatch, capsys):
    env = ScriptEnv(
        monkeypatch,
        [
            make_row(chunk_id=1, source_file="a.md"),
            make_row(chunk_id=2, source_file="a.md"),
            make_row(chunk_id=3, source_file="b.md"),
            make_row(chunk_id=4, source_file="b.md", search_text=enriched_text()),
        ],
    )
    args = env.script.parse_args(["--dry-run"])

    summary = env.run(dry_run=True)
    env.script.print_summary(summary, args=args)

    out = capsys.readouterr().out
    assert "待处理切片 3 条，分布在 2 份文档" in out
    assert "a.md" in out
    assert "b.md" in out
    assert "dry-run" in out
    assert "没有调用模型" in out


def test_dry_run_output_never_prints_the_content(monkeypatch, capsys):
    """dry-run 只报计数和文件名，不打印正文，也不打印密钥。"""
    env = ScriptEnv(monkeypatch, [make_row(chunk_id=1)])
    args = env.script.parse_args(["--dry-run"])

    env.script.print_summary(env.run(dry_run=True), args=args)

    out = capsys.readouterr().out
    assert BODY not in out
    assert "COUNT(DISTINCT" not in out
    assert "sk-" not in out


# --------------------------------------------------------------------------
# 写入：主键、参数化、只改三列
# --------------------------------------------------------------------------


def make_metadata() -> KnowledgeSearchMetadata:
    return KnowledgeSearchMetadata(
        keywords=("甲", "乙"),
        aliases=("丙",),
        search_text="文档：标题\n小节：小节\n关键词：甲、乙\n同义表达：丙\n\n正文：\n正文内容",
        extraction_succeeded=True,
    )


def test_update_statement_targets_a_single_primary_key():
    statement = str(load_script()._update_statement(42, make_metadata()))

    assert "UPDATE knowledge_chunks" in statement
    assert "WHERE knowledge_chunks.id = " in statement


def test_update_statement_is_parameterized():
    """★ 值必须走绑定参数：语句文本里不该出现任何数据本身。"""
    statement = load_script()._update_statement(42, make_metadata())

    rendered = str(statement)
    assert "甲" not in rendered
    assert "正文内容" not in rendered

    params = statement.compile().params
    assert params["keywords"] == ["甲", "乙"]
    assert params["aliases"] == ["丙"]
    assert "正文内容" in params["search_text"]
    assert any(key.startswith("id") and value == 42 for key, value in params.items())


def test_update_statement_only_writes_the_three_metadata_columns():
    """★ 正文、hash、向量一个都不能碰。"""
    statement = str(load_script()._update_statement(42, make_metadata()))

    assert "keywords" in statement
    assert "aliases" in statement
    assert "search_text" in statement
    for forbidden in (
        "content_for_embedding",
        "content_hash",
        "embedding",
        "document_id",
        "chunk_index",
        "estimated_token_count",
        "char_count",
    ):
        assert forbidden not in statement


def test_jsonb_values_are_written_as_lists():
    """keywords / aliases 传 list 给 JSONB 列，由列类型自己序列化。"""
    params = load_script()._update_statement(42, make_metadata()).compile().params

    assert isinstance(params["keywords"], list)
    assert isinstance(params["aliases"], list)


# --------------------------------------------------------------------------
# 失败处理
# --------------------------------------------------------------------------


def test_a_raising_extractor_leaves_that_row_untouched(monkeypatch):
    """★ 单条失败保持原值，下次运行还能重试。"""
    env = ScriptEnv(monkeypatch, [make_row(chunk_id=1), make_row(chunk_id=2)])

    class HalfFailingExtractor(FakeExtractor):
        async def __call__(self, document_title, section_title, content):
            self.calls.append((document_title, section_title, content))
            if len(self.calls) == 2:
                raise RuntimeError("boom")
            keywords = ("甲",)
            return KnowledgeSearchMetadata(
                keywords=keywords,
                aliases=(),
                search_text=build_enriched_search_text(
                    document_title, section_title, content, keywords, ()
                ),
                extraction_succeeded=True,
            )

    summary = env.run(extractor=HalfFailingExtractor())

    assert summary.updated == 1
    assert summary.failed == 1
    assert env.written_ids == [1]  # 失败那条没有被写
    assert summary.pending == 2


def test_a_degraded_extraction_is_counted_as_failed_and_not_written(monkeypatch):
    """模型没给出可用结果时也不写。

    写进去的 search_text 等于原值，等于什么都没做，却会让下次运行
    以为这条已经处理完了——那才是真正的坏结果。
    """
    env = ScriptEnv(monkeypatch, [make_row(chunk_id=1)])

    summary = env.run(extractor=FakeExtractor(succeeded=False))

    assert summary.updated == 0
    assert summary.failed == 1
    assert env.write_batches == []


def test_failure_log_records_only_the_exception_class(monkeypatch, caplog):
    import logging

    secret = "sk-canary-backfill-leak-0123456789abcdef"
    env = ScriptEnv(monkeypatch, [make_row(chunk_id=1)])

    with caplog.at_level(logging.WARNING):
        env.run(extractor=FakeExtractor(error=RuntimeError(f"401 api_key={secret}")))

    assert "RuntimeError" in caplog.text
    assert secret not in caplog.text
    assert "sk-" not in caplog.text
    assert BODY not in caplog.text


def test_a_failed_row_is_still_pending_on_the_next_run(monkeypatch):
    """失败 → 原值不动 → 下次运行仍会重试它。"""
    rows = [make_row(chunk_id=1)]
    env = ScriptEnv(monkeypatch, rows)

    first = env.run(extractor=FakeExtractor(error=RuntimeError("boom")))
    assert first.failed == 1

    second = env.run(extractor=FakeExtractor())
    assert second.pending == 1
    assert second.updated == 1


# --------------------------------------------------------------------------
# 幂等
# --------------------------------------------------------------------------


def test_a_second_run_has_nothing_left_to_do(monkeypatch):
    """★ 幂等的核心：第一次写进去的是 enriched，第二次就认得出「已处理」。

    这里把写出去的结果应用回内存行，模拟真实库的第二次运行。
    """
    rows = [make_row(chunk_id=1), make_row(chunk_id=2)]
    env = ScriptEnv(monkeypatch, rows)

    first = env.run(extractor=FakeExtractor())
    assert first.updated == 2
    assert first.pending == 2

    written = {chunk_id: metadata for chunk_id, metadata in env.written_entries}
    env.rows = [
        dataclasses.replace(row, search_text=written[row.chunk_id].search_text)
        for row in rows
    ]
    batches_after_first_run = len(env.write_batches)

    extractor = FakeExtractor()
    second = env.run(extractor=extractor)

    assert second.pending == 0
    assert second.updated == 0
    assert second.skipped == 2
    assert extractor.call_count == 0
    # 第二次运行没有再写入任何批次
    assert len(env.write_batches) == batches_after_first_run


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------


def test_summary_lines_report_the_five_required_fields(monkeypatch):
    env = ScriptEnv(monkeypatch, [make_row(chunk_id=1), make_row(chunk_id=2, search_text=enriched_text())])

    summary = env.run()

    names = [name for name, _ in summary.as_lines()]
    assert names == ["scanned", "updated", "skipped", "failed", "elapsed_seconds"]

    values = dict(summary.as_lines())
    assert values["scanned"] == "2"
    assert values["updated"] == "1"
    assert values["skipped"] == "1"
    assert values["failed"] == "0"


def test_printed_summary_shows_the_counts_and_the_failure_note(monkeypatch, capsys):
    env = ScriptEnv(monkeypatch, [make_row(chunk_id=1)])
    args = env.script.parse_args([])

    summary = env.run(extractor=FakeExtractor(error=RuntimeError("boom")))
    env.script.print_summary(summary, args=args)

    out = capsys.readouterr().out
    assert f"{'scanned':<20} 1" in out
    assert f"{'updated':<20} 0" in out
    assert f"{'failed':<20} 1" in out
    assert "elapsed_seconds" in out
    assert "下次运行会重试" in out


def test_printed_summary_says_nothing_to_do_when_idempotent(monkeypatch, capsys):
    env = ScriptEnv(monkeypatch, [make_row(chunk_id=1, search_text=enriched_text())])
    args = env.script.parse_args([])

    env.script.print_summary(env.run(), args=args)

    assert "没有待处理项" in capsys.readouterr().out


# --------------------------------------------------------------------------
# 启动方式
# --------------------------------------------------------------------------


def test_script_bootstraps_the_backend_directory_on_sys_path():
    """sys.path 里必须有 backend/，否则 `import app` 会失败。"""
    script = load_script()

    assert str(script.BACKEND_DIR) in sys.path
    assert (script.BACKEND_DIR / "app").is_dir()


def test_script_runs_from_both_the_project_root_and_the_backend_directory():
    """★ 两种调用方式都要真的能启动。

    这个只能用子进程验证：importlib 加载能证明模块写得对，
    证明不了「换个工作目录还跑得起来」。--help 不碰数据库、不调模型。
    """
    invocations = [
        (PROJECT_ROOT, "backend/scripts/backfill_knowledge_metadata.py"),
        (BACKEND_DIR, "scripts/backfill_knowledge_metadata.py"),
    ]

    for cwd, target in invocations:
        result = subprocess.run(
            [sys.executable, target, "--help"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, f"{cwd} 下启动失败：{result.stderr}"
        assert "--dry-run" in result.stdout
        assert "--source-file" in result.stdout
        assert "--refresh" in result.stdout


def test_script_failure_message_redacts_the_api_key(monkeypatch, capsys):
    script = load_script()
    secret = FAKE_KEY

    monkeypatch.setattr(script, "known_secret", lambda: secret)

    async def explode(**kwargs):
        raise RuntimeError(f"upstream rejected api_key={secret} with 401")

    async def noop():
        return None

    monkeypatch.setattr(script, "backfill", explode)
    monkeypatch.setattr(script, "dispose_engine", noop)

    exit_code = asyncio.run(script.main(["--dry-run"]))

    out = capsys.readouterr().out
    assert exit_code == 1
    assert secret not in out
    assert "sk-" not in out
    assert "知识切片元数据回填失败" in out
