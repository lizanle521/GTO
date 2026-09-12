# -*- coding: utf-8 -*-
"""屏幕截图模块：负责全屏 / 区域截屏，并转换为可发送给模型的 base64 图像。"""

import base64
import io
from datetime import datetime
from pathlib import Path

import mss
from PIL import Image


def grab_fullscreen(monitor_index=0):
    """截取屏幕。monitor_index=0 表示所有显示器拼合的整体画面。

    返回 PIL.Image 对象（RGB）。
    """
    with mss.mss() as sct:
        monitors = sct.monitors
        if monitor_index >= len(monitors):
            monitor_index = 0
        shot = sct.grab(monitors[monitor_index])
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        return img


def grab_region(left, top, width, height):
    """截取指定矩形区域。"""
    region = {"left": left, "top": top, "width": width, "height": height}
    with mss.mss() as sct:
        shot = sct.grab(region)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        return img


def list_monitors():
    """返回显示器列表信息，供界面展示。"""
    with mss.mss() as sct:
        result = []
        for i, mon in enumerate(sct.monitors):
            label = "全部显示器" if i == 0 else f"显示器 {i}"
            result.append({
                "index": i,
                "label": label,
                "width": mon["width"],
                "height": mon["height"],
            })
        return result


def image_to_base64(img, fmt="PNG", max_width=1920, quality=90):
    """将 PIL 图像转为 base64 字符串。

    为避免图片过大导致请求超时，超过 max_width 时会等比缩放。
    """
    if img.width > max_width:
        ratio = max_width / img.width
        new_size = (max_width, int(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    buffer = io.BytesIO()
    save_kwargs = {"format": fmt}
    if fmt.upper() in ("JPEG", "JPG"):
        save_kwargs["quality"] = quality
        if img.mode != "RGB":
            img = img.convert("RGB")
    img.save(buffer, **save_kwargs)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def save_screenshot(img, directory):
    """保存截图到指定目录，返回保存路径。"""
    out_dir = Path(directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = datetime.now().strftime("shot_%Y%m%d_%H%M%S.png")
    path = out_dir / filename
    img.save(path, "PNG")
    return str(path)
