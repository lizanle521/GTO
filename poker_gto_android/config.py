# -*- coding: utf-8 -*-
"""配置读写（安卓版）。

安卓上使用 app 私有目录存储，桌面调试时用用户主目录。
"""

import json
import os
from pathlib import Path


def _config_dir():
    """确定配置目录：安卓用私有目录，桌面用主目录。

    可用环境变量 POKER_GTO_CONFIG_DIR 覆盖（测试隔离用）。
    """
    override = os.environ.get("POKER_GTO_CONFIG_DIR")
    if override:
        return Path(override)
    # Kivy 在安卓下会提供 ANDROID_ARGUMENT 环境变量
    if "ANDROID_ARGUMENT" in os.environ or "ANDROID_PRIVATE" in os.environ:
        base = os.environ.get("ANDROID_PRIVATE") or os.getcwd()
        return Path(base)
    return Path.home() / ".poker_gto"


def _config_path():
    d = _config_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / "config.json"


DEFAULT_CONFIG = {
    "api_key": "",
    "base_url": "https://open.bigmodel.cn/api/paas/v4",
    "model": "glm-4v-flash",
    "preset": "智谱 GLM（免费）",
    "max_tokens": 800,
    "temperature": 0.2,
    # 摄像头抽帧识别参数
    "capture_interval": 3.0,      # 秒，每次识别的最小间隔（控制 API 成本）
    "confidence_threshold": 0.08,  # 画面变化率阈值，低于此值不送识别
                                   # 牌局发牌只改变小区域，阈值需偏敏感
    "auto_save_captures": True,
}


def load_config():
    """读取配置，缺失字段用默认值补齐。"""
    path = _config_path()
    config = dict(DEFAULT_CONFIG)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                config.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
        except (json.JSONDecodeError, OSError):
            pass
    return config


def save_config(config):
    """保存配置。"""
    path = _config_path()
    try:
        path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return True, str(path)
    except OSError as e:
        return False, str(e)


def reset_config():
    """重置为默认配置。"""
    return save_config(dict(DEFAULT_CONFIG))


if __name__ == "__main__":
    print("=== 配置模块自检 ===")

    # 自检必须在隔离目录里跑：真实配置可能已被用户/测试改过，
    # 直接断言磁盘上的值会误报失败。
    import tempfile
    _saved = os.environ.get("POKER_GTO_CONFIG_DIR")
    _tmp = tempfile.mkdtemp(prefix="poker_gto_selftest_")
    os.environ["POKER_GTO_CONFIG_DIR"] = _tmp

    try:
        print(f"配置路径：{_config_path()}")

        cfg = load_config()
        print(f"默认模型：{cfg['model']}")
        print(f"默认接口：{cfg['base_url']}")
        assert cfg["model"] == "glm-4v-flash", f"默认模型异常：{cfg['model']}"
        assert "max_tokens" in cfg

        # 保存回环测试
        cfg["api_key"] = "sk-test-12345"
        cfg["capture_interval"] = 2.5
        ok, msg = save_config(cfg)
        assert ok, f"保存失败：{msg}"
        print("✓ 保存成功")

        reloaded = load_config()
        assert reloaded["api_key"] == "sk-test-12345", "Key 未正确保存"
        assert reloaded["capture_interval"] == 2.5, "数值字段未正确保存"
        print("✓ 读取回环一致")

        # 未知字段应被忽略（防止配置文件被污染）
        path = _config_path()
        data = json.loads(path.read_text(encoding="utf-8"))
        data["malicious_field"] = "x"
        path.write_text(json.dumps(data), encoding="utf-8")
        clean = load_config()
        assert "malicious_field" not in clean, "未知字段未被过滤"
        print("✓ 未知字段已过滤")

        # 重置功能
        reset_config()
        assert load_config()["api_key"] == "", "重置未生效"
        print("✓ 重置为默认配置")

        print("\n自检通过 ✓")
    finally:
        if _saved is None:
            os.environ.pop("POKER_GTO_CONFIG_DIR", None)
        else:
            os.environ["POKER_GTO_CONFIG_DIR"] = _saved
        import shutil
        shutil.rmtree(_tmp, ignore_errors=True)
