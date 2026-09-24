"""精排配置的单元测试。

**本文件不读真实密钥、不联网。** 所有字段都显式给值（见 make_settings），
所以结果不会随开发机 `.env` 漂移——这一点在本阶段尤其要紧：
本地 `.env` 里已经填了真实的百炼业务空间地址与 Key，测试必须完全绕开它们。

配置校验单独一个文件而不是塞进 test_embedding_config.py：
那个文件的主题是 embedding，混进来会让「哪一条测试在测什么」变模糊。
"""

import dataclasses

import pytest

from app.core.config import (
    RERANK_MAX_CANDIDATES,
    RERANK_MIN_CANDIDATES,
    RERANK_PATH,
    SUPPORTED_RERANK_PROVIDERS,
    RerankSettings,
    Settings,
)
from app.core.exceptions import ConfigurationError

# 明显的假值。断言它们不出现在任何错误信息或 repr 里。
FAKE_KEY = "sk-fake-rerank-key-for-tests-0123456789"
FAKE_BASE_URL = "https://fake-workspace-id.cn-beijing.maas.aliyuncs.com/compatible-api/v1"
FAKE_MODEL = "qwen3-rerank"


def make_settings(**overrides) -> Settings:
    """构造一份不受项目根 .env 影响的配置。

    所有 rerank 字段都显式给值，避免测试结果随开发机 .env 变化而漂移。
    `_env_file=None` 让 pydantic 连读都不读——本地 .env 里现在放着真实的
    百炼业务空间地址与 Key，测试不该以任何方式碰它们。
    """
    values = {
        "rerank_provider": "dashscope",
        "rerank_model": FAKE_MODEL,
        "rerank_api_key": FAKE_KEY,
        "rerank_base_url": FAKE_BASE_URL,
        "rerank_timeout_seconds": 10.0,
        "rag_rerank_enabled": True,
        "rag_retrieval_candidate_limit": 20,
        "rag_final_top_k": 5,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def make_settings_with_raw(**overrides) -> Settings:
    """先构造一份合法配置，再直接改属性。

    为什么要绕这一下：pydantic 在**构造时**就把 "20" 转成 20、把 1.5 直接拒掉，
    所以「校验方法自己也守一道」这件事根本走不到。属性是运行期可以改坏的
    （Settings 不是 frozen），校验方法不该假定它一定还是 int。
    """
    settings = make_settings()
    for name, value in overrides.items():
        setattr(settings, name, value)
    return settings


# --------------------------------------------------------------------------
# 正常路径
# --------------------------------------------------------------------------


def test_valid_settings_are_returned_as_a_typed_object():
    config = make_settings().require_rerank_settings()

    assert isinstance(config, RerankSettings)
    assert config.enabled is True
    assert config.provider == "dashscope"
    assert config.model == FAKE_MODEL
    assert config.api_key == FAKE_KEY
    assert config.base_url == FAKE_BASE_URL
    assert config.candidate_limit == 20
    assert config.final_top_k == 5
    assert config.timeout_seconds == pytest.approx(10.0)


def test_rerank_settings_is_frozen():
    config = make_settings().require_rerank_settings()

    assert dataclasses.is_dataclass(config)
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.final_top_k = 99


def test_the_candidate_limit_matches_the_fusion_layer():
    """★ 两个 20 必须是同一个 20。

    core 不能 import services（会成环），所以候选上限在两处各写了一个；
    漂开之后的表现是「融合给了 20 条、精排只收 10 条」这种安静的错。
    """
    from app.services.retrieval_fusion import MAX_CANDIDATE_LIMIT

    assert RERANK_MAX_CANDIDATES == MAX_CANDIDATE_LIMIT


def test_the_rerank_path_is_the_documented_one():
    """百炼 qwen3-rerank 走的是独立的 /reranks 路径。"""
    assert RERANK_PATH == "/reranks"


def test_dashscope_is_the_only_supported_provider_for_now():
    assert SUPPORTED_RERANK_PROVIDERS == ("dashscope",)


# --------------------------------------------------------------------------
# base_url 规范化
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [FAKE_BASE_URL, FAKE_BASE_URL + "/", FAKE_BASE_URL + "//"],
)
def test_trailing_slashes_are_removed(raw):
    """只去掉末尾的 /，否则拼出来会变成 //reranks。"""
    config = make_settings(rerank_base_url=raw).require_rerank_settings()

    assert config.base_url == FAKE_BASE_URL


def test_other_parts_of_the_url_are_left_alone():
    """带端口、带路径前缀的地址都要原样保留——顺手规整只会把填对的改坏。"""
    url = "https://host.invalid:8443/some/prefix/v1"

    config = make_settings(rerank_base_url=url).require_rerank_settings()

    assert config.base_url == url


def test_a_base_url_already_ending_with_the_path_is_rejected():
    """★ 已经带 /reranks 的地址会让最终地址拼成 /reranks/reranks。"""
    with pytest.raises(ConfigurationError) as error:
        make_settings(rerank_base_url=FAKE_BASE_URL + RERANK_PATH).require_rerank_settings()

    assert "RERANK_BASE_URL" in str(error.value)


# --------------------------------------------------------------------------
# 密钥与地址不进 repr
# --------------------------------------------------------------------------


def test_repr_hides_the_api_key():
    config = make_settings().require_rerank_settings()

    assert FAKE_KEY not in repr(config)
    assert "api_key" not in repr(config).replace("RerankSettings", "")


def test_repr_hides_the_base_url():
    """业务空间地址是租户标识，和密钥一样不该顺着日志漏出去。"""
    config = make_settings().require_rerank_settings()

    assert FAKE_BASE_URL not in repr(config)
    assert "fake-workspace-id" not in repr(config)


def test_repr_still_shows_the_harmless_fields():
    """屏蔽是为了藏敏感值，不是让对象变得不可读——排查问题还要靠它。"""
    rendered = repr(make_settings().require_rerank_settings())

    assert "dashscope" in rendered
    assert FAKE_MODEL in rendered
    assert "final_top_k=5" in rendered


# --------------------------------------------------------------------------
# 数值校验（关掉精排也要校验：它们定义的是检索链路的形状）
# --------------------------------------------------------------------------


@pytest.mark.parametrize("value", [RERANK_MIN_CANDIDATES, 5, RERANK_MAX_CANDIDATES])
def test_valid_candidate_limit_is_accepted(value):
    config = make_settings(
        rag_retrieval_candidate_limit=value, rag_final_top_k=1
    ).require_rerank_settings()

    assert config.candidate_limit == value


@pytest.mark.parametrize(
    "bad_value", [0, -1, RERANK_MAX_CANDIDATES + 1, 100, 10_000]
)
def test_out_of_range_candidate_limit_is_rejected(bad_value):
    with pytest.raises(ConfigurationError) as error:
        make_settings(rag_retrieval_candidate_limit=bad_value).require_rerank_settings()

    message = str(error.value)
    assert "RAG_RETRIEVAL_CANDIDATE_LIMIT" in message
    assert str(RERANK_MAX_CANDIDATES) in message


@pytest.mark.parametrize("bad_value", [1.5, "20", None, True])
def test_non_integer_candidate_limit_is_rejected(bad_value):
    with pytest.raises(ConfigurationError) as error:
        make_settings_with_raw(rag_retrieval_candidate_limit=bad_value).require_rerank_settings()

    assert "RAG_RETRIEVAL_CANDIDATE_LIMIT" in str(error.value)


@pytest.mark.parametrize("bad_value", [0, -1, 21, 100])
def test_final_top_k_out_of_range_is_rejected(bad_value):
    with pytest.raises(ConfigurationError) as error:
        make_settings(rag_final_top_k=bad_value).require_rerank_settings()

    assert "RAG_FINAL_TOP_K" in str(error.value)


def test_final_top_k_may_not_exceed_the_candidate_limit():
    """★ 最终上下文不可能比候选还多——那说明两个值配反了。"""
    with pytest.raises(ConfigurationError) as error:
        make_settings(
            rag_retrieval_candidate_limit=5, rag_final_top_k=6
        ).require_rerank_settings()

    message = str(error.value)
    assert "RAG_FINAL_TOP_K" in message
    assert "5" in message


def test_final_top_k_equal_to_the_candidate_limit_is_allowed():
    config = make_settings(
        rag_retrieval_candidate_limit=5, rag_final_top_k=5
    ).require_rerank_settings()

    assert config.final_top_k == 5


@pytest.mark.parametrize("bad_value", [1.5, "5", None, True])
def test_non_integer_final_top_k_is_rejected(bad_value):
    with pytest.raises(ConfigurationError) as error:
        make_settings_with_raw(rag_final_top_k=bad_value).require_rerank_settings()

    assert "RAG_FINAL_TOP_K" in str(error.value)


@pytest.mark.parametrize("bad_value", [0, -1, -10.5])
def test_non_positive_timeout_is_rejected(bad_value):
    with pytest.raises(ConfigurationError) as error:
        make_settings(rerank_timeout_seconds=bad_value).require_rerank_settings()

    assert "RERANK_TIMEOUT_SECONDS" in str(error.value)


def test_an_integer_timeout_is_accepted():
    """写 10 而不是 10.0 是很自然的，不该被拒。"""
    config = make_settings(rerank_timeout_seconds=10).require_rerank_settings()

    assert config.timeout_seconds == pytest.approx(10.0)
    assert isinstance(config.timeout_seconds, float)


@pytest.mark.parametrize("bad_value", ["十秒", None, True, [10]])
def test_non_numeric_timeout_is_rejected(bad_value):
    with pytest.raises(ConfigurationError) as error:
        make_settings_with_raw(rerank_timeout_seconds=bad_value).require_rerank_settings()

    assert "RERANK_TIMEOUT_SECONDS" in str(error.value)


# --------------------------------------------------------------------------
# 供应商相关字段：只在启用时校验
# --------------------------------------------------------------------------


def test_an_unsupported_provider_is_rejected():
    with pytest.raises(ConfigurationError) as error:
        make_settings(rerank_provider="cohere").require_rerank_settings()

    message = str(error.value)
    assert "RERANK_PROVIDER" in message
    assert "cohere" not in message  # 不回显填错的值


@pytest.mark.parametrize(
    ("field", "variable"),
    [
        ("rerank_api_key", "RERANK_API_KEY"),
        ("rerank_base_url", "RERANK_BASE_URL"),
        ("rerank_model", "RERANK_MODEL"),
    ],
)
def test_missing_required_field_is_reported_by_name(field, variable):
    with pytest.raises(ConfigurationError) as error:
        make_settings(**{field: "   "}).require_rerank_settings()

    assert variable in str(error.value)


def test_all_missing_fields_are_listed_together():
    """一次报全，省得改一个跑一次。"""
    with pytest.raises(ConfigurationError) as error:
        make_settings(
            rerank_api_key="", rerank_base_url="", rerank_model=""
        ).require_rerank_settings()

    message = str(error.value)
    for variable in ("RERANK_API_KEY", "RERANK_BASE_URL", "RERANK_MODEL"):
        assert variable in message


def test_the_missing_config_error_suggests_disabling_rerank():
    """关掉它是一个合理的临时选择，报错里就该说清楚这条路。"""
    with pytest.raises(ConfigurationError) as error:
        make_settings(rerank_api_key="").require_rerank_settings()

    assert "RAG_RERANK_ENABLED" in str(error.value)


def test_disabled_rerank_does_not_require_an_api_key():
    """★ 关掉精排时缺 Key 不能让服务起不来。

    「想临时关掉」不该变成一件麻烦事——那会让人干脆去填一个假 Key。
    """
    config = make_settings(
        rag_rerank_enabled=False,
        rerank_api_key="",
        rerank_base_url="",
        rerank_model="",
    ).require_rerank_settings()

    assert config.enabled is False


def test_disabled_rerank_does_not_validate_the_provider():
    config = make_settings(
        rag_rerank_enabled=False, rerank_provider="cohere"
    ).require_rerank_settings()

    assert config.enabled is False


def test_disabled_rerank_still_keeps_the_numbers():
    config = make_settings(
        rag_rerank_enabled=False, rag_retrieval_candidate_limit=8, rag_final_top_k=3
    ).require_rerank_settings()

    assert config.candidate_limit == 8
    assert config.final_top_k == 3


def test_disabled_rerank_still_rejects_a_bad_candidate_limit():
    """★ 候选上限和最终条数在精排关掉之后照样生效，配错就是配错。"""
    with pytest.raises(ConfigurationError):
        make_settings(
            rag_rerank_enabled=False, rag_retrieval_candidate_limit=0
        ).require_rerank_settings()

    with pytest.raises(ConfigurationError):
        make_settings(rag_rerank_enabled=False, rag_final_top_k=99).require_rerank_settings()


def test_disabled_rerank_keeps_the_raw_values_for_inspection():
    """关掉时原样带上配置值：排查问题时能一眼看到「当时配的是什么」。"""
    config = make_settings(
        rag_rerank_enabled=False, rerank_model="  qwen3-rerank  "
    ).require_rerank_settings()

    assert config.model == "qwen3-rerank"


# --------------------------------------------------------------------------
# 不泄露
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_values",
    [
        {"rerank_api_key": ""},
        {"rerank_base_url": ""},
        {"rerank_model": ""},
        {"rerank_provider": "cohere"},
        {"rerank_timeout_seconds": 0},
        {"rag_retrieval_candidate_limit": 99},
        {"rag_final_top_k": 99},
        {"rerank_base_url": FAKE_BASE_URL + RERANK_PATH},
    ],
)
def test_errors_never_contain_the_key_or_the_url(bad_values):
    """★ 报错只点名变量，不回显值。

    Key 一旦进了异常消息，就会顺着日志、接口响应、错误上报一路扩散，
    而那是最难回收的一类泄露。地址里的业务空间 ID 同理。
    """
    with pytest.raises(ConfigurationError) as error:
        make_settings(**bad_values).require_rerank_settings()

    message = str(error.value)
    assert FAKE_KEY not in message
    assert "sk-" not in message
    assert FAKE_BASE_URL not in message
    assert "fake-workspace-id" not in message


def test_error_messages_stay_short_and_named():
    """报错要能读懂：只说哪个变量、合法范围是什么。"""
    with pytest.raises(ConfigurationError) as error:
        make_settings(rag_retrieval_candidate_limit=99).require_rerank_settings()

    message = str(error.value)
    assert len(message) < 200
    assert "20" in message


# --------------------------------------------------------------------------
# 不建客户端
# --------------------------------------------------------------------------


def test_configuring_rerank_never_constructs_an_http_client(monkeypatch):
    """★ 读配置只该得到一组值，不该顺手建出网络客户端。

    把 AsyncClient 的构造换成一调用就炸的桩：真建了就会当场失败。
    否则「配置有没有填对」会和「连不连得上」缠在一起，排查时分不清。
    """
    import httpx

    def explode(*args, **kwargs):
        raise AssertionError("读配置不该建 HTTP 客户端")

    monkeypatch.setattr(httpx, "AsyncClient", explode)

    config = make_settings().require_rerank_settings()

    assert config.enabled is True


def test_the_reranker_module_creates_no_client_at_import_time():
    """import reranker 不该建客户端：任何一次导入（测试收集、脚本）都不该被牵连。"""
    import httpx

    from app.services import reranker

    for name, value in vars(reranker).items():
        assert not isinstance(value, httpx.AsyncClient), f"模块级客户端：{name}"
