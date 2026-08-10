"""ResponseBase / PageResult 单元测试"""

from platform_mcp.common.response import ResponseBase, PageResult


class TestResponseBase:
    def test_default_values(self):
        r = ResponseBase()
        assert r.code == 0
        assert r.message == "success"
        assert r.data is None
        assert r.timestamp > 0

    def test_with_data(self):
        r = ResponseBase(data={"key": "val"})
        assert r.data == {"key": "val"}

    def test_error_response(self):
        r = ResponseBase(code=11001, message="认证失败")
        assert r.code == 11001
        assert r.message == "认证失败"

    def test_model_dump(self):
        r = ResponseBase(code=0, message="ok", data=[1, 2])
        d = r.model_dump()
        assert d["code"] == 0
        assert d["data"] == [1, 2]


class TestPageResult:
    def test_create_calculates_total_pages(self):
        pr = PageResult.create(items=[1, 2, 3], total=25, page=1, page_size=10)
        assert pr.total_pages == 3

    def test_create_single_page(self):
        pr = PageResult.create(items=[1], total=1, page=1, page_size=10)
        assert pr.total_pages == 1

    def test_create_zero_items(self):
        pr = PageResult.create(items=[], total=0, page=1, page_size=10)
        assert pr.total_pages == 0
        assert pr.items == []
