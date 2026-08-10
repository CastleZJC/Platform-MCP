"""tool_wrapper 单元测试 — format_tool_result"""

import json

from platform_mcp.mcp_server.tool_wrapper import format_tool_result


class TestFormatToolResult:
    def test_success_result_format(self):
        result = format_tool_result(data={"key": "value"}, trace_id="trace-123")
        parsed = json.loads(result)
        assert parsed["code"] == 0
        assert parsed["message"] == "success"
        assert parsed["data"] == {"key": "value"}
        assert parsed["trace_id"] == "trace-123"
        assert "timestamp" in parsed

    def test_error_result_format(self):
        result = format_tool_result(trace_id="t-1", error_code=10001, error_message="执行失败")
        parsed = json.loads(result)
        assert parsed["code"] == 10001
        assert parsed["message"] == "执行失败"
        assert parsed["data"] is None

    def test_default_values(self):
        result = format_tool_result()
        parsed = json.loads(result)
        assert parsed["code"] == 0
        assert parsed["message"] == "success"
        assert parsed["data"] is None
        assert parsed["trace_id"] == ""

    def test_complex_data_serialization(self):
        data = {"list": [1, 2, 3], "nested": {"a": True}}
        result = format_tool_result(data=data, trace_id="t")
        parsed = json.loads(result)
        assert parsed["data"] == data

    def test_timestamp_is_milliseconds(self):
        result = format_tool_result(trace_id="t")
        parsed = json.loads(result)
        ts = parsed["timestamp"]
        assert isinstance(ts, int)
        assert ts > 1_700_000_000_000
