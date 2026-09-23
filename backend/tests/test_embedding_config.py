"""embedding 配置与服务的单元测试。

**本文件绝不调用真实百炼 API。** 所有涉及网络的地方都通过 monkeypatch 注入假客户端，
与 test_data_query_graph.py 注入假分类器是同一套做法：把外部依赖换成替身，
测试因此不依赖任何 Key、网络或余额。

另外一个贯穿全文件的目标：确认敏感信息不会从错误路径漏出去。

异步调用按项目既有约定处理：本文件不装 pytest-asyncio，改用 asyncio.run 包一层。
理由见 test_data_query_graph.py 的说明——测试入口本身不在事件循环里，
同步测试里调用 asyncio.run 是安全的，也不会把事件循环细节散落到每处。
"""

import asyncio

import pytest

from app.core.config import EmbeddingSettings, Settings
from app.core.exceptions import ConfigurationError
from app.services import embedding

# 一个明显的假密钥。测试断言它不出现在任何错误消息里。
FAKE_KEY = "sk-fake-key-for-tests-only-0123456789"
FAKE_BASE_URL = "https://example.invalid/compatible-mode/v1"

DIMENSION = 1024


def make_settings(**overrides) -> Settings:
    """构造一份不受项目根 .env 影响的配置。

    所有 embedding 字段都显式给值，避免测试结果随开发机 .env 变化而漂移。
    """
    values = {
        "embedding_provider": "dashscope",
        "embedding_model": "text-embedding-v4",
        "embedding_dimension": DIMENSION,
        "embedding_api_key": FAKE_KEY,
        "embedding_base_url": FAKE_BASE_URL,
    }
    values.update(overrides)
    return Settings(**values)


def make_embedding_settings(**overrides) -> EmbeddingSettings:
    values = {
        "provider": "dashscope",
        "model": "text-embedding-v4",
        "dimension": DIMENSION,
        "base_url": FAKE_BASE_URL,
        "api_key": FAKE_KEY,
    }
    values.update(overrides)
    return EmbeddingSettings(**values)


# --------------------------------------------------------------------------
# 假客户端：形状对齐 openai SDK 的 embeddings.create 返回值
# --------------------------------------------------------------------------


class _FakeItem:
    def __init__(self, embedding, index):
        self.embedding = embedding
        self.index = index


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeEmbeddingsResource:
    """记录每次调用参数，并按 index 生成可辨识的向量。"""

    def __init__(self, dimension, *, reverse_response=False):
        self.dimension = dimension
        self.reverse_response = reverse_response
        self.calls: list[dict] = []

    async def create(self, *, model, input, dimensions):
        self.calls.append({"model": model, "input": list(input), "dimensions": dimensions})
        # 第 i 条向量的首个分量就是 i，便于断言顺序
        items = [
            _FakeItem([float(index)] + [0.5] * (self.dimension - 1), index)
            for index in range(len(input))
        ]
        if self.reverse_response:
            items.reverse()
        return _FakeResponse(items)


class _FakeClient:
    def __init__(self, embeddings):
        self.embeddings = embeddings


@pytest.fixture
def fake_embedding(monkeypatch):
    """把 _get_client 换成假客户端，并返回 (资源, 配置) 供断言。"""

    def install(*, dimension: int = DIMENSION, reverse_response: bool = False, settings=None):
        resource = _FakeEmbeddingsResource(dimension, reverse_response=reverse_response)
        config = settings or make_embedding_settings()
        monkeypatch.setattr(embedding, "_get_client", lambda: (_FakeClient(resource), config))
        return resource

    return install


# --------------------------------------------------------------------------
# 配置校验
# --------------------------------------------------------------------------


def test_require_embedding_settings_returns_typed_values():
    config = make_settings().require_embedding_settings()

    assert config.provider == "dashscope"
    assert config.model == "text-embedding-v4"
    assert config.base_url == FAKE_BASE_URL
    assert config.api_key == FAKE_KEY


def test_dimension_is_read_as_int():
    """维度必须是 int：建表时写 vector(1024)，字符串会一路错到 SQL 层。"""
    config = make_settings(embedding_dimension="1024").require_embedding_settings()

    assert isinstance(config.dimension, int)
    assert config.dimension == DIMENSION
    assert not isinstance(config.dimension, bool)  # bool 是 int 的子类，排除掉


@pytest.mark.parametrize("bad_dimension", [0, -1, -1024])
def test_non_positive_dimension_is_rejected(bad_dimension):
    with pytest.raises(ConfigurationError) as error:
        make_settings(embedding_dimension=bad_dimension).require_embedding_settings()

    assert "EMBEDDING_DIMENSION" in str(error.value)


@pytest.mark.parametrize(
    ("missing_field", "expected_name"),
    [
        ("embedding_api_key", "EMBEDDING_API_KEY"),
        ("embedding_base_url", "EMBEDDING_BASE_URL"),
        ("embedding_model", "EMBEDDING_MODEL"),
    ],
)
def test_missing_required_setting_is_reported_by_name(missing_field, expected_name):
    with pytest.raises(ConfigurationError) as error:
        make_settings(**{missing_field: "   "}).require_embedding_settings()

    assert expected_name in str(error.value)


def test_missing_setting_error_does_not_leak_the_api_key():
    """报错要点名「哪个变量缺了」，但不能把其它变量的值顺手带出来。"""
    with pytest.raises(ConfigurationError) as error:
        make_settings(embedding_base_url="").require_embedding_settings()

    message = str(error.value)
    assert "EMBEDDING_BASE_URL" in message
    assert FAKE_KEY not in message
    assert "sk-" not in message


def test_embedding_settings_repr_hides_the_api_key():
    """dataclass 默认 repr 会打印全部字段——用 repr=False 把密钥挡掉。"""
    config = make_embedding_settings()

    assert FAKE_KEY not in repr(config)
    assert "api_key" not in repr(config).replace("EmbeddingSettings", "")


# --------------------------------------------------------------------------
# 服务行为（全部走假客户端，不发网络请求）
# --------------------------------------------------------------------------


def test_module_does_not_create_a_client_at_import_time():
    """import 阶段不许建客户端，否则任何一次导入都会被配置缺失牵连。"""
    from openai import AsyncOpenAI

    for name, value in vars(embedding).items():
        assert not isinstance(value, AsyncOpenAI), f"发现模块级客户端：{name}"


def test_embed_text_returns_a_vector_of_the_configured_dimension(fake_embedding):
    fake_embedding()

    vector, config = asyncio.run(embedding.embed_text("客单价等于销售额除以订单数"))

    assert len(vector) == DIMENSION
    assert all(isinstance(value, float) for value in vector)
    assert config.dimension == DIMENSION


def test_embed_texts_passes_model_and_dimensions_to_the_api(fake_embedding):
    resource = fake_embedding()

    asyncio.run(embedding.embed_texts(["第一句", "第二句"]))

    assert len(resource.calls) == 1
    call = resource.calls[0]
    assert call["model"] == "text-embedding-v4"
    assert call["dimensions"] == DIMENSION
    assert call["input"] == ["第一句", "第二句"]


def test_vectors_follow_the_input_order_even_if_the_api_reverses_them(fake_embedding):
    """按 index 排序再取，不依赖服务端返回顺序。"""
    fake_embedding(reverse_response=True)

    vectors, _ = asyncio.run(embedding.embed_texts(["a", "b", "c"]))

    assert [vector[0] for vector in vectors] == [0.0, 1.0, 2.0]


def test_dimension_mismatch_raises_without_leaking_the_key(fake_embedding):
    """服务端给了 8 维、配置写了 1024 维时必须报错，且错误里不能有密钥。"""
    fake_embedding(dimension=8)

    with pytest.raises(embedding.EmbeddingDimensionError) as error:
        asyncio.run(embedding.embed_text("维度故意对不上"))

    message = str(error.value)
    assert "8" in message
    assert str(DIMENSION) in message
    assert FAKE_KEY not in message


def test_blank_text_is_rejected_before_any_request(fake_embedding):
    resource = fake_embedding()

    with pytest.raises(embedding.EmbeddingError):
        asyncio.run(embedding.embed_texts(["正常文本", "   "]))

    assert resource.calls == []  # 一次请求都没发出去


def test_empty_input_is_rejected(fake_embedding):
    resource = fake_embedding()

    with pytest.raises(embedding.EmbeddingError):
        asyncio.run(embedding.embed_texts([]))

    assert resource.calls == []


def test_generated_vectors_are_usable_as_pgvector_literals(fake_embedding):
    """冒烟之外的护栏：向量要能直接拼成 pgvector 认的字面量。"""
    fake_embedding()

    vector, _ = asyncio.run(embedding.embed_text("可入库检查"))
    literal = "[" + ",".join(str(value) for value in vector) + "]"

    assert literal.startswith("[")
    assert literal.count(",") == DIMENSION - 1


# --------------------------------------------------------------------------
# 输出清洗
# --------------------------------------------------------------------------


def test_redact_secret_replaces_the_key():
    text = f"request failed with api_key={FAKE_KEY} at {FAKE_BASE_URL}"

    cleaned = embedding.redact_secret(text, FAKE_KEY)

    assert FAKE_KEY not in cleaned
    assert embedding.REDACTED in cleaned


def test_redact_secret_is_a_noop_for_empty_secret():
    assert embedding.redact_secret("原文", "") == "原文"


def test_summarize_vector_does_not_print_the_whole_vector():
    summary = embedding.summarize_vector([0.123456] * DIMENSION)

    assert f"共 {DIMENSION} 维" in summary
    assert summary.count(",") <= 3  # 只有前几个值
