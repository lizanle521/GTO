# -*- coding: utf-8 -*-
"""配置管理模块：负责读写用户配置（API Key、模型、接口地址等）。"""

import json
import os
from pathlib import Path

# 配置目录：用户主目录下的 .desktop_recognizer
CONFIG_DIR = Path.home() / ".desktop_recognizer"
CONFIG_FILE = CONFIG_DIR / "config.json"

# 默认配置
DEFAULT_CONFIG = {
    "api_key": "",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o-mini",
    "prompt": "请识别并描述这张截图中的软件界面内容。",
    "max_tokens": 1500,
    "temperature": 0.3,
    "save_screenshots": True,
    "screenshot_dir": str(Path.home() / "Pictures" / "DesktopRecognizer"),
}


def ensure_config_dir():
    """确保配置目录存在。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config():
    """加载配置，缺失的键用默认值补齐。"""
    ensure_config_dir()
    config = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                config.update(saved)
        except (json.JSONDecodeError, OSError):
            # 配置损坏时回退到默认值，不阻塞启动
            pass
    return config


def save_config(config):
    """保存配置到磁盘。"""
    ensure_config_dir()
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
