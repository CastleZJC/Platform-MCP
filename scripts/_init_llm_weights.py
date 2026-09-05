"""本地生成模型权重离线校验（V3.0 M4.6，VNF-03 权重离线分发 / F-35）

Qwen3-4B-Instruct GGUF 权重经离线介质分发到部署机后，用本脚本在启动前校验：

1. settings.skill.llm_model_path 已配置且文件存在（默认读 settings.yml，--path 可显式覆盖）；
2. GGUF 魔数（前 4 字节 "GGUF"）与最小体积（>1MB，防误传残片）；
3. SHA-256 摘要计算（流式），--sha256 提供预期值时严格比对；
4. --probe 时尝试 llama-cpp-python 真实加载（Llama 实例构造成功即可推理）。

全程不联网（VNF-03：权重缺失/校验失败时平台自动降级确定性模板，不阻断服务）。
退出码：0 校验通过；1 校验失败（原因见输出）。

用法：
    python scripts/_init_llm_weights.py                       # 校验 settings 配置路径
    python scripts/_init_llm_weights.py --path /data/models/qwen3-4b-q4.gguf
    python scripts/_init_llm_weights.py --sha256 <expected>   # 摘要严格比对
    python scripts/_init_llm_weights.py --probe               # 附加真实加载探测
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

_MIN_SIZE_BYTES = 1024 * 1024  # 1MB：Qwen3-4B int4 量化约 2~4GB，残片/误传在此拦截
_CHUNK = 1024 * 1024


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def check_weights(path: Path, expected_sha256: str | None, probe: bool) -> bool:
    print(f"[1/4] 权重路径：{path}")
    if not str(path) or not path.exists():
        print(f"FAIL: 权重文件不存在：{path}")
        print("      请先经离线介质分发 GGUF 权重，并在 settings.yml 配置 skill.llm_model_path")
        return False
    if not path.is_file():
        print(f"FAIL: 路径不是文件：{path}")
        return False

    size = path.stat().st_size
    print(f"[2/4] 文件大小：{size / 1024 / 1024:.1f} MB")
    if size < _MIN_SIZE_BYTES:
        print("FAIL: 文件小于 1MB（疑似残片/误传）；完整 Qwen3-4B int4 GGUF 约 2~4GB")
        return False

    with path.open("rb") as fh:
        magic = fh.read(4)
    if magic != b"GGUF":
        print(f"FAIL: GGUF 魔数不匹配（实际 {magic!r}，期望 b'GGUF'）")
        return False
    print("[3/4] GGUF 魔数：OK")

    actual = sha256_of(path)
    print(f"      SHA-256：{actual}")
    if expected_sha256:
        if actual.lower() != expected_sha256.lower():
            print("FAIL: SHA-256 与预期不一致（权重损坏或版本不符）")
            return False
        print("      SHA-256 比对：OK")

    if probe:
        print("[4/4] llama-cpp-python 加载探测……")
        try:
            from llama_cpp import Llama

            Llama(model_path=str(path), n_ctx=512, verbose=False)
            print("      加载探测：OK（可推理）")
        except Exception as exc:  # noqa: BLE001 - 探测失败给出一站式原因
            print(f"FAIL: llama-cpp-python 加载失败：{exc}")
            print("      请确认 llama-cpp-python 已安装（pyproject model 组）且权重与库版本兼容")
            return False
    else:
        print("[4/4] 跳过加载探测（--probe 启用）")

    print("PASS: 权重离线校验通过；重启平台进程后 settings.skill.llm_model_path 生效（§19.5.2 静态配置）")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Qwen3-4B GGUF 权重离线校验（VNF-03，不联网）")
    parser.add_argument("--path", default="", help="GGUF 权重路径（缺省读 settings.skill.llm_model_path）")
    parser.add_argument("--sha256", default="", help="预期 SHA-256（提供则严格比对）")
    parser.add_argument("--probe", action="store_true", help="附加 llama-cpp-python 真实加载探测")
    args = parser.parse_args()

    model_path = args.path
    if not model_path:
        from platform_mcp.config import get_settings

        model_path = get_settings().skill.llm_model_path
        if not model_path:
            print("FAIL: settings.skill.llm_model_path 未配置（--path 可显式指定）")
            return 1

    ok = check_weights(Path(model_path), args.sha256 or None, args.probe)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
