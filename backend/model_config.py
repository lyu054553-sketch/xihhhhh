"""后端模型配置入口；读取配置不代表已接入模型调用。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Literal

from dotenv import dotenv_values
from pydantic import BaseModel, SecretStr


ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = {
    "deepseek": ("DEEPSEEK", "https://api.deepseek.com"),
    "qwen": ("QWEN", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    "minimax": ("MINIMAX", "https://api.minimax.cn/v1"),
}
ProviderName = Literal["", "deepseek", "qwen", "minimax"]


class ProviderConfig(BaseModel):
    api_key: SecretStr
    base_url: str
    model: str
    vision_model: str


class ModelConfig(BaseModel):
    text_provider: ProviderName = ""
    vision_provider: ProviderName = ""
    providers: Dict[str, ProviderConfig]
    # 本次开发与比赛已确认不设 API 总费用上限。
    api_budget_limit_cny: None = None


def load_model_config() -> ModelConfig:
    # 环境变量优先；不展开变量引用，不修改进程中其他业务配置。
    values = {**dotenv_values(ROOT / ".env", interpolate=False), **os.environ}

    def value(name: str, default: str = "") -> str:
        return (values.get(name) or default).strip()

    text_provider = value("AGENT_MODEL_PROVIDER").lower()
    vision_provider = value("AGENT_VISION_PROVIDER").lower()
    for name, provider in (
        ("AGENT_MODEL_PROVIDER", text_provider),
        ("AGENT_VISION_PROVIDER", vision_provider),
    ):
        if provider and provider not in PROVIDERS:
            # 不回显配置原值，避免误将粘贴到错误字段的密钥写进日志。
            raise ValueError(f"{name} 仅支持 deepseek、qwen、minimax 或留空")

    return ModelConfig(
        text_provider=text_provider,
        vision_provider=vision_provider,
        providers={
            name: ProviderConfig(
                api_key=SecretStr(value(f"{prefix}_API_KEY")),
                base_url=value(f"{prefix}_BASE_URL", base_url),
                model=value(f"{prefix}_MODEL"),
                vision_model=value(f"{prefix}_VISION_MODEL"),
            )
            for name, (prefix, base_url) in PROVIDERS.items()
        },
    )
