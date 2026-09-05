# encoding: utf-8
# @file: load_env.py
# @desc: 加载 .env 配置，返回 DeepSeek 大模型连接参数
import os
import dotenv

# .env 与本文件同目录（src/agent/）
_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def load_env() -> dict:
    """加载 .env，返回 DeepSeek 配置字典"""
    dotenv.load_dotenv(_ENV_PATH)
    return {
        "llm_model": os.getenv("llm_model", "deepseek-v4-flash"),
        "API_KEY": os.getenv("DEEPSEEK_API_KEY", ""),
        "base_url": os.getenv("base_url", "https://api.deepseek.com/v1"),
    }
