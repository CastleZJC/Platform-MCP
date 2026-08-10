"""Tool 参数校验与统一返回结构格式化"""

from __future__ import annotations

import json
import time
from typing import Any


def format_tool_result(
    data: Any = None,
    trace_id: str = "",
    error_code: int = 0,
    error_message: str | None = None,
) -> str:
    """将 Tool 执行结果格式化为统一 JSON 字符串（TextContent.text）。

    成功: {"code": 0, "message": "success", "data": ..., "trace_id": "...", "timestamp": ...}
    失败: {"code": 10xxx, "message": "...", "data": null, "trace_id": "...", "timestamp": ...}
    """
    message = "success" if error_code == 0 else (error_message or "unknown error")
    result = {
        "code": error_code,
        "message": message,
        "data": data if error_code == 0 else None,
        "trace_id": trace_id,
        "timestamp": int(time.time() * 1000),
    }
    return json.dumps(result, ensure_ascii=False, default=str)
