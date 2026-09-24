from __future__ import annotations

from typing import Any

import json

from sqlalchemy import text

ALLOWED_PREFERENCE_KEYS = {
    "currency_unit",
    "preferred_region",
    "preferred_chart",
    "report_style",
}
MEMORY_NAMESPACE = "business_analysis_preferences"


async def load_user_preferences(store: Any, user_id: str | None) -> dict[str, Any]:
    if not user_id:
        return {}
    preferences: dict[str, Any] = {}
    for key in ALLOWED_PREFERENCE_KEYS:
        item = await store.aget((MEMORY_NAMESPACE, user_id), key)
        if item is None:
            continue
        value = getattr(item, "value", item)
        if isinstance(value, dict) and "value" in value:
            value = value["value"]
        preferences[key] = value
    return preferences


async def save_user_preference(store: Any, user_id: str, key: str, value: Any) -> None:
    if key not in ALLOWED_PREFERENCE_KEYS:
        raise ValueError(f"不允许保存该用户偏好：{key}")
    if not user_id.strip():
        raise ValueError("user_id 不能为空白。")
    if not isinstance(value, (str, int, float, bool)):
        raise ValueError("用户偏好只能保存基础 JSON 值。")
    if isinstance(value, str) and len(value) > 128:
        raise ValueError("用户偏好文本过长。")
    await store.aput((MEMORY_NAMESPACE, user_id), key, {"value": value})


async def load_user_preferences_from_db(connection: Any, user_id: str) -> dict[str, Any]:
    result = await connection.execute(
        text(
            """
            SELECT memory_key, memory_value
            FROM business_analysis_memories
            WHERE user_id = :user_id
            """
        ),
        {"user_id": user_id},
    )
    preferences: dict[str, Any] = {}
    for row in result.mappings().all():
        key = row.get("memory_key")
        if key in ALLOWED_PREFERENCE_KEYS:
            value = row.get("memory_value")
            if isinstance(value, dict) and "value" in value:
                value = value["value"]
            preferences[key] = value
    return preferences


async def save_user_preference_to_db(
    connection: Any,
    user_id: str,
    key: str,
    value: Any,
) -> None:
    if key not in ALLOWED_PREFERENCE_KEYS:
        raise ValueError(f"不允许保存该用户偏好：{key}")
    if not user_id.strip() or not isinstance(value, (str, int, float, bool)):
        raise ValueError("用户偏好参数不合法。")
    if isinstance(value, str) and len(value) > 128:
        raise ValueError("用户偏好文本过长。")
    await connection.execute(
        text(
            """
            INSERT INTO business_analysis_memories (user_id, memory_key, memory_value)
            VALUES (:user_id, :memory_key, CAST(:memory_value AS JSONB))
            ON CONFLICT (user_id, memory_key)
            DO UPDATE SET memory_value = EXCLUDED.memory_value, updated_at = now()
            """
        ),
        {
            "user_id": user_id,
            "memory_key": key,
            "memory_value": json.dumps({"value": value}, ensure_ascii=False),
        },
    )
