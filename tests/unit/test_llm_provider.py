"""单元测试 — 本地生成模型栈（V3.0 M4.1，架构 §19.5.6 / 计划 M4.1、F-35、VNF-01、VNF-03）

覆盖：
- 常量口径（generated_by 值域 / 性能提示文案，M4.4）；
- QwenLlamaCppProvider：依赖缺失/权重不可用降级（VNF-03 绝不联网）、正常加载与生成、
  空输出/空 choices 拒绝、超时兜底（VNF-01 asyncio.wait_for）、推理异常包装、
  参数透传（max_tokens/temperature）、线程层串行（同一 Llama 实例不并发推理）、
  事件循环层单槽跨 loop 自动重建（pytest-asyncio 每用例独立 loop 的设计动机回归）；
- get_llm_provider / reset_llm_provider / llm_available / llm_generate：进程级单例与
  「不可用」结论缓存、无配置返回 None、reset 后重新选定。

用 sys.modules 注入伪 llama_cpp（Llama 假实现），不依赖真实权重 / llama-cpp-python 安装。
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
import types
from unittest.mock import MagicMock, patch

import pytest

from platform_mcp.skills.llm import (
    GENERATED_BY_EXTERNAL,
    GENERATED_BY_MODEL,
    PERFORMANCE_HINT_EN,
    PERFORMANCE_HINT_ZH,
    LlmGenerationError,
    QwenLlamaCppProvider,
    get_llm_provider,
    llm_available,
    llm_generate,
    reset_llm_provider,
)


class FakeLlama:
    """伪 llama_cpp.Llama：记录调用 / 可编程延迟、异常、回复与并发计数。"""

    instances: list["FakeLlama"] = []

    def __init__(self, model_path: str = "", n_ctx: int = 0, verbose: bool = False, **kw) -> None:
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.verbose = verbose
        self.init_kwargs = kw
        self.delay = 0.0
        self.calls: list[dict] = []
        self.raise_on_call: Exception | None = None
        self.reply: dict | None = {"choices": [{"message": {"content": " 模型输出 "}}]}
        self._active = 0
        self.max_active = 0
        self._counter_lock = threading.Lock()
        FakeLlama.instances.append(self)

    def create_chat_completion(self, *, messages=None, max_tokens=None, temperature=None, **kw):
        with self._counter_lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        try:
            self.calls.append(
                {"messages": messages, "max_tokens": max_tokens, "temperature": temperature}
            )
            if self.delay:
                time.sleep(self.delay)
            if self.raise_on_call is not None:
                raise self.raise_on_call
            return self.reply
        finally:
            with self._counter_lock:
                self._active -= 1


@pytest.fixture(autouse=True)
def _fake_llama_cpp():
    """sys.modules 注入伪 llama_cpp；用例内构造的 Provider 均走假实现。"""
    FakeLlama.instances.clear()
    module = types.ModuleType("llama_cpp")
    module.Llama = FakeLlama  # type: ignore[attr-defined]
    with patch.dict(sys.modules, {"llama_cpp": module}):
        yield
    FakeLlama.instances.clear()


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_llm_provider()
    yield
    reset_llm_provider()


def _provider(**kw) -> tuple[QwenLlamaCppProvider, FakeLlama]:
    p = QwenLlamaCppProvider("Z:/weights/qwen3-4b.gguf", **kw)
    assert p.available is True
    return p, FakeLlama.instances[-1]


# ==================== 常量口径（M4.4）====================


class TestConstants:
    def test_generated_by值域(self):
        assert GENERATED_BY_MODEL == "model"
        assert GENERATED_BY_EXTERNAL == "external"

    def test_性能提示文案(self):
        assert "本地模型" in PERFORMANCE_HINT_ZH and "外部大模型" in PERFORMANCE_HINT_ZH
        assert "external large model" in PERFORMANCE_HINT_EN.lower()


# ==================== Provider 构造 / 降级（VNF-03）====================


class TestProviderConstruction:
    def test_权重不存在降级不可用(self):
        # 权重加载抛 FileNotFoundError → available=False，不抛异常（降级不阻断，VNF-03）
        def _raise_init(self, *args, **kwargs):
            raise FileNotFoundError("Z:/nope.gguf")

        with patch.object(FakeLlama, "__init__", _raise_init):
            p = QwenLlamaCppProvider("Z:/nope.gguf")
        assert p.available is False

    def test_llama_cpp导入失败降级(self):
        # 模块缺 Llama 属性 → from llama_cpp import Llama 抛 ImportError → 降级
        with patch.dict(sys.modules, {"llama_cpp": types.SimpleNamespace()}):
            p = QwenLlamaCppProvider("Z:/weights/qwen3-4b.gguf")
        assert p.available is False
        with pytest.raises(LlmGenerationError, match="不可用"):
            asyncio.run(p.generate("x"))

    def test_正常加载记录参数(self):
        p, fake = _provider(n_ctx=4096)
        assert p.name == "qwen3-llama-cpp"
        assert fake.model_path == "Z:/weights/qwen3-4b.gguf"
        assert fake.n_ctx == 4096


# ==================== 生成路径（VNF-01 超时兜底 / 串行）====================


class TestGenerate:
    async def test_正常生成去空白(self):
        p, _ = _provider()
        text = await p.generate("写报告")
        assert text == "模型输出"

    async def test_不可用时拒绝生成(self):
        def _raise_init(self, *args, **kwargs):
            raise FileNotFoundError("Z:/nope.gguf")

        with patch.object(FakeLlama, "__init__", _raise_init):
            p = QwenLlamaCppProvider("Z:/nope.gguf")
        with pytest.raises(LlmGenerationError, match="不可用"):
            await p.generate("x")

    async def test_参数透传max_tokens与temperature(self):
        p, fake = _provider(max_tokens=77)
        await p.generate("x", max_tokens=88)
        call = fake.calls[-1]
        assert call["max_tokens"] == 88
        assert call["temperature"] == pytest.approx(0.3)
        assert call["messages"] == [{"role": "user", "content": "x"}]

    async def test_空choices抛错(self):
        p, fake = _provider()
        fake.reply = {"choices": []}
        with pytest.raises(LlmGenerationError, match="choices"):
            await p.generate("x")

    async def test_空输出抛错(self):
        p, fake = _provider()
        fake.reply = {"choices": [{"message": {"content": "   "}}]}
        with pytest.raises(LlmGenerationError, match="空输出"):
            await p.generate("x")

    async def test_超时兜底抛错(self):
        p, fake = _provider()
        fake.delay = 0.3
        with pytest.raises(LlmGenerationError, match="超时"):
            await p.generate("x", timeout_seconds=0.05)

    async def test_推理异常包装为LlmGenerationError(self):
        p, fake = _provider()
        fake.raise_on_call = RuntimeError("segfault")
        with pytest.raises(LlmGenerationError, match="本地生成失败"):
            await p.generate("x")

    async def test_并发生成线程层串行(self):
        p, fake = _provider()
        fake.delay = 0.05
        results = await asyncio.gather(p.generate("a"), p.generate("b"), p.generate("c"))
        assert results == ["模型输出"] * 3
        assert fake.max_active == 1  # 同一 Llama 实例从未被并发推理

    async def test_单槽排队保持调用顺序(self):
        p, fake = _provider()
        fake.delay = 0.02
        await asyncio.gather(p.generate("a"), p.generate("b"))
        assert [c["messages"][0]["content"] for c in fake.calls] == ["a", "b"]

    def test_跨loop信号量自动重建(self):
        """同一 Provider 实例先后在两个事件循环上生成 —— 无「Semaphore 绑定旧 loop」异常。"""
        p, _ = _provider()

        async def _once():
            return await p.generate("x")

        loop1 = asyncio.new_event_loop()
        try:
            assert loop1.run_until_complete(_once()) == "模型输出"
        finally:
            loop1.close()
        loop2 = asyncio.new_event_loop()
        try:
            assert loop2.run_until_complete(_once()) == "模型输出"
        finally:
            loop2.close()


# ==================== 进程级单例 / 选定（get_llm_provider）====================


def _mock_settings(model_path: str) -> MagicMock:
    settings = MagicMock()
    settings.skill.llm_model_path = model_path
    settings.skill.llm_model_name = "Qwen3-4B-Instruct-GGUF"
    settings.skill.llm_n_ctx = 8192
    settings.skill.llm_timeout_seconds = 60
    settings.skill.llm_max_tokens = 1024
    return settings


class TestProviderSingleton:
    def test_无配置返回None(self):
        with patch("platform_mcp.skills.llm.get_settings", return_value=_mock_settings("")):
            assert get_llm_provider() is None
            assert llm_available() is False

    async def test_无配置llm_generate抛错(self):
        with patch("platform_mcp.skills.llm.get_settings", return_value=_mock_settings("")):
            with pytest.raises(LlmGenerationError, match="未配置"):
                await llm_generate("x")

    def test_加载失败缓存不可用结论(self):
        calls = []

        def _ctor(path, **kw):
            calls.append(path)
            m = MagicMock()
            m.available = False
            return m

        with patch("platform_mcp.skills.llm.get_settings", return_value=_mock_settings("Z:/w.gguf")), \
                patch("platform_mcp.skills.llm.QwenLlamaCppProvider", side_effect=_ctor):
            assert get_llm_provider() is None
            assert get_llm_provider() is None  # 二次调用命中缓存
        assert calls == ["Z:/w.gguf"]

    def test_就绪后单例复用(self):
        provider = MagicMock()
        provider.available = True
        provider.name = "qwen3-llama-cpp"
        with patch("platform_mcp.skills.llm.get_settings", return_value=_mock_settings("Z:/w.gguf")), \
                patch("platform_mcp.skills.llm.QwenLlamaCppProvider", return_value=provider):
            assert get_llm_provider() is provider
            assert get_llm_provider() is provider
            assert llm_available() is True

    def test_reset后重新选定(self):
        provider = MagicMock()
        provider.available = True
        with patch("platform_mcp.skills.llm.get_settings", return_value=_mock_settings("Z:/w.gguf")), \
                patch("platform_mcp.skills.llm.QwenLlamaCppProvider", return_value=provider) as ctor:
            get_llm_provider()
            reset_llm_provider()
            get_llm_provider()
        assert ctor.call_count == 2
