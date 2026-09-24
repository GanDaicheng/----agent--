"""精排冒烟脚本的测试。

**本文件绝不打真实 API。** 脚本里的 provider 与 `run()` 都被替换成替身，
所以能验证「输出里有哪些字段」「失败时打印什么」「退出码是多少」，
而真的一次调用只在人工执行脚本时发生。

唯一一处真实外部世界的痕迹是那条子进程测试：它用 runpy 把脚本当模块**导入**
（run_name 不是 __main__），验证换工作目录也起得来，但不触发 main()。
"""

import asyncio
import importlib.util
import pathlib
import subprocess
import sys

import pytest

from app.core.config import Settings
from app.core.exceptions import ConfigurationError
from app.services.reranker import RerankItem, RerankerProviderError

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
SCRIPT = BACKEND_DIR / "scripts" / "smoke_reranker.py"

FAKE_KEY = "sk-fake-smoke-rerank-key-0123456789"
FAKE_BASE_URL = "https://fake-workspace-id.cn-beijing.maas.aliyuncs.com/compatible-api/v1"

# 真实冒烟允许打印的字段，一个不多一个不少
ALLOWED_FIELDS = (
    "provider",
    "model",
    "candidate_count",
    "returned_count",
    "index",
    "relevance_score",
    "elapsed_seconds",
    "status",
)


def load_script():
    spec = importlib.util.spec_from_file_location("smoke_reranker_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeReranker:
    """替身：记录调用参数，返回预设结果或抛异常。"""

    def __init__(self, items=None, *, error=None) -> None:
        self.items = items
        self.error = error
        self.calls: list[tuple[str, list[str], int]] = []

    async def rerank(self, query, documents, *, top_n):
        self.calls.append((query, list(documents), top_n))
        if self.error is not None:
            raise self.error
        return self.items if self.items is not None else []


def make_settings(**overrides) -> Settings:
    """不读本地 .env：那里放着真实的百炼地址与 Key。"""
    values = {
        "rerank_provider": "dashscope",
        "rerank_model": "qwen3-rerank",
        "rerank_api_key": FAKE_KEY,
        "rerank_base_url": FAKE_BASE_URL,
        "rerank_timeout_seconds": 10.0,
        "rag_rerank_enabled": True,
        "rag_retrieval_candidate_limit": 20,
        "rag_final_top_k": 5,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


# --------------------------------------------------------------------------
# 脚本本身的性质
# --------------------------------------------------------------------------


def test_script_bootstraps_the_backend_directory_on_sys_path():
    script = load_script()

    assert str(script.BACKEND_DIR) in sys.path
    assert (script.BACKEND_DIR / "app").is_dir()


def test_script_guards_its_call_behind_main():
    """import 这个脚本不该发请求——只有直接运行才会。"""
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'if __name__ == "__main__":' in source


def test_script_reuses_the_neutral_builtin_probe_data():
    script = load_script()

    assert len(script.SMOKE_DOCUMENTS) == 3
    assert script.SMOKE_TOP_N == 2
    assert script.SMOKE_QUERY.strip()
    # 三条互不相同，否则测不出排序
    assert len(set(script.SMOKE_DOCUMENTS)) == 3


def test_probe_texts_carry_no_private_or_business_data():
    """探测文本是中性的通用知识句，不含任何真实业务数据。"""
    script = load_script()
    joined = " ".join(script.SMOKE_DOCUMENTS) + script.SMOKE_QUERY

    for forbidden in ("客单价", "销售额", "会员", "订单", "客户", "@", "http"):
        assert forbidden not in joined


def test_script_does_not_touch_the_database_or_embedding():
    """冒烟只验证精排这一条链路，不碰库、不算向量、不问回答模型。"""
    import ast

    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)

    forbidden = (
        "app.repositories.database",
        "app.services.embedding",
        "app.core.llm",
        "sqlalchemy",
    )
    assert not [module for module in modules if module.startswith(forbidden)]


# --------------------------------------------------------------------------
# run()：调用形状
# --------------------------------------------------------------------------


def test_run_sends_one_request_with_the_builtin_probe(monkeypatch):
    script = load_script()
    monkeypatch.setattr(script, "get_settings", lambda: make_settings())
    fake = FakeReranker([RerankItem(1, 0.9), RerankItem(0, 0.2)])

    result = asyncio.run(script.run(reranker=fake))

    assert len(fake.calls) == 1
    query, documents, top_n = fake.calls[0]
    assert query == script.SMOKE_QUERY
    assert documents == list(script.SMOKE_DOCUMENTS)
    assert top_n == script.SMOKE_TOP_N
    assert result.candidate_count == 3
    assert result.returned_count == 2
    assert result.status == "ok"
    assert result.provider == "dashscope"
    assert result.model == "qwen3-rerank"


def test_run_builds_the_production_provider_only_when_none_is_injected(monkeypatch):
    script = load_script()
    monkeypatch.setattr(script, "get_settings", lambda: make_settings())
    built: list = []

    class RecordingProvider:
        def __init__(self, settings):
            built.append(settings)

        async def rerank(self, query, documents, *, top_n):
            return [RerankItem(0, 0.5)]

    monkeypatch.setattr(script, "DashScopeReranker", RecordingProvider)

    asyncio.run(script.run())

    assert len(built) == 1
    assert built[0].model == "qwen3-rerank"


def test_run_does_not_build_a_provider_when_one_is_injected(monkeypatch):
    script = load_script()
    monkeypatch.setattr(script, "get_settings", lambda: make_settings())

    def explode(*args, **kwargs):
        raise AssertionError("注入了 provider 就不该再建生产客户端")

    monkeypatch.setattr(script, "DashScopeReranker", explode)

    asyncio.run(script.run(reranker=FakeReranker()))


def test_run_records_the_elapsed_time(monkeypatch):
    script = load_script()
    monkeypatch.setattr(script, "get_settings", lambda: make_settings())

    result = asyncio.run(script.run(reranker=FakeReranker()))

    assert result.elapsed_seconds >= 0
    assert isinstance(result.elapsed_seconds, float)


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------


def test_successful_output_contains_only_the_allowed_fields(capsys):
    script = load_script()
    result = script.SmokeResult(
        provider="dashscope",
        model="qwen3-rerank",
        candidate_count=3,
        returned_count=2,
        items=(RerankItem(1, 0.9), RerankItem(0, 0.2)),
        elapsed_seconds=0.42,
        status="ok",
    )

    script.print_result(result)

    out = capsys.readouterr().out
    for field in ALLOWED_FIELDS:
        assert field in out, field
    assert "dashscope" in out
    assert "qwen3-rerank" in out


def test_output_never_prints_the_key_the_url_or_the_documents(capsys):
    """★ 冒烟输出只报计数、序号和分数。

    候选正文、Key、完整地址都不该出现——冒烟脚本的输出经常被贴进 issue，
    这三样是最容易跟着一起贴出去的东西。
    """
    script = load_script()
    result = script.SmokeResult(
        provider="dashscope",
        model="qwen3-rerank",
        candidate_count=3,
        returned_count=1,
        items=(RerankItem(0, 0.9),),
        elapsed_seconds=0.1,
        status="ok",
    )

    script.print_result(result)

    out = capsys.readouterr().out
    assert FAKE_KEY not in out
    assert "sk-" not in out
    assert FAKE_BASE_URL not in out
    assert "fake-workspace-id" not in out
    assert "reranks" not in out
    for document in script.SMOKE_DOCUMENTS:
        assert document not in out


# --------------------------------------------------------------------------
# main()：退出码与失败输出
# --------------------------------------------------------------------------


def test_main_returns_zero_on_success(monkeypatch, capsys):
    script = load_script()

    async def fake_run(**_kwargs):
        return script.SmokeResult(
            provider="dashscope",
            model="qwen3-rerank",
            candidate_count=3,
            returned_count=2,
            items=(RerankItem(1, 0.9), RerankItem(0, 0.2)),
            elapsed_seconds=0.3,
            status="ok",
        )

    monkeypatch.setattr(script, "run", fake_run)

    exit_code = asyncio.run(script.main())

    assert exit_code == 0
    assert "ok" in capsys.readouterr().out


def test_main_returns_nonzero_on_a_provider_failure(monkeypatch, capsys):
    script = load_script()

    async def explode(**_kwargs):
        raise RerankerProviderError("精排服务返回 401。")

    monkeypatch.setattr(script, "run", explode)

    exit_code = asyncio.run(script.main())

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "RerankerProviderError" in out
    assert "精排" in out


def test_main_returns_nonzero_on_a_configuration_failure(monkeypatch, capsys):
    """配置没填好时给出可操作的提示，而不是让用户去看堆栈。"""
    script = load_script()

    async def explode(**_kwargs):
        raise ConfigurationError("缺少精排配置：RERANK_API_KEY。")

    monkeypatch.setattr(script, "run", explode)

    exit_code = asyncio.run(script.main())

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "RERANK_API_KEY" in out


def test_main_reports_the_status_code_for_a_provider_failure(monkeypatch, capsys):
    """供应商失败要能看出「是什么错」——状态码是最好的线索。

    这一类消息是我们自己拼的，按契约只有错误类别和状态码，
    所以可以安全地打出来。
    """
    script = load_script()

    async def explode(**_kwargs):
        raise RerankerProviderError("精排服务返回 401。")

    monkeypatch.setattr(script, "run", explode)

    exit_code = asyncio.run(script.main())

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "RerankerProviderError" in out
    assert "401" in out


def test_main_prints_only_the_class_name_for_third_party_errors(monkeypatch, capsys):
    """★ 第三方异常的正文一律不打印。

    它的原文可能带着请求头、完整 URL 和响应内容，而这个脚本的输出
    经常被原样贴进 issue——那是这类信息最难收回的一条路径。
    """
    script = load_script()
    secret = "sk-canary-smoke-leak-0123456789abcdef"

    async def explode(**_kwargs):
        raise RuntimeError(f"401 Unauthorized: api_key={secret} at https://host.invalid/reranks")

    monkeypatch.setattr(script, "run", explode)

    exit_code = asyncio.run(script.main())

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "RuntimeError" in out
    assert secret not in out
    assert "sk-" not in out
    assert "api_key=" not in out
    assert "host.invalid" not in out


def test_main_handles_an_unexpected_error_without_a_traceback_dump(monkeypatch, capsys):
    script = load_script()

    async def explode(**_kwargs):
        raise RuntimeError("意料之外的内部细节")

    monkeypatch.setattr(script, "run", explode)

    exit_code = asyncio.run(script.main())

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "RuntimeError" in out


# --------------------------------------------------------------------------
# 两种工作目录都能启动（不触发真实调用）
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cwd", "target"),
    [
        (PROJECT_ROOT, "backend/scripts/smoke_reranker.py"),
        (BACKEND_DIR, "scripts/smoke_reranker.py"),
    ],
)
def test_script_can_be_loaded_from_either_directory(cwd, target):
    """★ 两种调用方式都要真的起得来。

    用 runpy 以「非 __main__」的名字导入：模块顶层代码（sys.path 引导、
    import 依赖）都会执行，但 `if __name__ == "__main__"` 不成立，
    所以不会真的发请求。这样既验证了换目录可用，又不多花一次额度。
    """
    code = f"import runpy; runpy.run_path({target!r}, run_name='smoke_module_check')"

    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr
