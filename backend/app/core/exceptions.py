class AppError(Exception):
    """项目内可预期异常的基类。"""


class ConfigurationError(AppError, RuntimeError):
    """配置缺失或非法，例如没有填 OPENAI_API_KEY。"""
