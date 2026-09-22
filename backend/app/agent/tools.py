from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.tools import tool


@tool
def get_current_time(timezone: str = "Asia/Shanghai") -> str:
    """获取当前日期和时间。参数 timezone 为 IANA 时区名，默认 Asia/Shanghai。

    Windows 不自带时区库，ZoneInfo 依赖 requirements.txt 中的 tzdata 包。
    """
    try:
        now = datetime.now(ZoneInfo(timezone))
    except Exception:
        return f"未知时区：{timezone}"
    return now.strftime("%Y-%m-%d %H:%M:%S %Z")


# 工具注册表：后续业务工具（查库、查元数据、查指标口径等）加到这个列表即可，
# agent 会自动获得调用能力，无需改动其他代码。
TOOLS = [get_current_time]
