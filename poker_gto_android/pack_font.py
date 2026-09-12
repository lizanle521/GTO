# -*- coding: utf-8 -*-
"""把中文字体放进 assets/，供打包进 apk。

为什么需要：Kivy 默认字体不含中文字形，界面上的中文会显示成方块（豆腐块）。
解决办法是把一个中文字体随 apk 一起打包，程序启动时注册它。

用法（在项目目录下执行）：

    python pack_font.py

脚本会按下面的顺序找一个可用字体：
    1) 若 assets/chinese.ttf 已存在，直接确认，不覆盖
    2) 从网上下载 Noto Sans SC（开源，SIL OFL 1.1）—— 推荐，版权干净
    3) 找不到网络时，退回使用系统自带中文字体（仅限本机调试）

═══ 关于字体版权（重要）═══

Windows 自带的微软雅黑、宋体、黑体都是**商业字体**，
本机调试无妨，但**不能**随 apk 分发，否则有侵权风险。

可安全分发的开源中文字体（都是 SIL OFL 1.1 / 可商用）：
  · Noto Sans SC       —— 本脚本默认下载这个
  · 思源黑体 Source Han Sans
  · 霞鹜文楷 LXGW WenKai
  · 文泉驿微米黑 WenQuanYi Micro Hei

用 --system 参数可以强制使用系统字体（仅供本机调试）：

    python pack_font.py --system
"""

import argparse
import shutil
import sys
import urllib.request
from pathlib import Path

ASSETS = Path(__file__).parent / "assets"
TARGET = ASSETS / "chinese.ttf"

# Noto Sans SC Regular，SIL OFL 1.1，可免费商用
# 先用 Google Fonts 的 CSS 接口拿到当前有效的直链，避免直链过期
NOTO_CSS_URL = (
    "https://fonts.googleapis.com/css2"
    "?family=Noto+Sans+SC:wght@400&display=swap"
)
NOTO_FALLBACK_URL = (
    "https://github.com/notofonts/noto-cjk/raw/main/"
    "Sans/SubsetOTF/SC/NotoSansSC-Regular.otf"
)

# 系统字体（仅用于本机调试，勿分发）
SYSTEM_FONTS = [
    ("C:/Windows/Fonts/msyh.ttc", "微软雅黑（商业字体，勿分发）"),
    ("C:/Windows/Fonts/simhei.ttf", "黑体（商业字体，勿分发）"),
    ("/System/Library/Fonts/PingFang.ttc", "苹方（商业字体，勿分发）"),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "Noto CJK（开源）"),
    ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", "文泉驿微米黑（开源）"),
]

FONT_MAGIC = (b"\x00\x01\x00\x00", b"OTTO", b"true", b"ttcf")


def _download(url, dst):
    """下载到 dst，返回是否成功且内容像字体。"""
    import ssl
    ctx = ssl.create_default_context()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        tmp = dst.with_suffix(".part")
        with urllib.request.urlopen(req, timeout=90, context=ctx) as r:
            with open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
        with open(tmp, "rb") as f:
            head = f.read(4)
        if head not in FONT_MAGIC:
            tmp.unlink(missing_ok=True)
            return False
        tmp.replace(dst)
        return True
    except Exception as e:
        print(f"    下载失败：{type(e).__name__}: {e}")
        return False


def fetch_open_font():
    """下载开源中文字体。先走 Google Fonts（拿实时直链），失败再走 GitHub。"""
    print("[开源字体] 尝试下载 Noto Sans SC（SIL OFL 1.1，可商用）...")

    # 第一步：从 CSS 接口取当前有效的字体直链
    direct = None
    try:
        import re
        import ssl
        ctx = ssl.create_default_context()
        req = urllib.request.Request(NOTO_CSS_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            css = r.read().decode("utf-8", errors="replace")
        m = re.search(r"url\((https://[^)]+\.(?:ttf|otf|woff2))\)", css)
        if m:
            direct = m.group(1)
            print(f"    取得直链：{direct[:80]}...")
    except Exception as e:
        print(f"    获取直链失败：{type(e).__name__}")

    if direct and _download(direct, TARGET):
        return "Noto Sans SC（Google Fonts，SIL OFL 1.1）"

    # 第二步：回退到 GitHub 直链
    print("    尝试 GitHub 备用源...")
    if _download(NOTO_FALLBACK_URL, TARGET):
        return "Noto Sans SC（GitHub，SIL OFL 1.1）"

    return None


def fetch_system_font():
    """退回系统字体，仅用于本机调试。"""
    print("[系统字体] 查找本机中文字体...")
    for path, desc in SYSTEM_FONTS:
        p = Path(path)
        if p.exists():
            print(f"    找到：{p}  —— {desc}")
            shutil.copy2(p, TARGET)
            return desc
    return None


def main():
    ap = argparse.ArgumentParser(description="准备中文字体")
    ap.add_argument("--system", action="store_true",
                    help="强制使用系统字体（仅本机调试，勿用于发布）")
    ap.add_argument("--force", action="store_true",
                    help="即使已存在也重新获取")
    args = ap.parse_args()

    ASSETS.mkdir(parents=True, exist_ok=True)

    # 已存在且不强制刷新
    if TARGET.exists() and not args.force:
        size_mb = TARGET.stat().st_size / 1024 / 1024
        print(f"字体已存在：{TARGET}（{size_mb:.1f} MB）")
        with open(TARGET, "rb") as f:
            head = f.read(4)
        if head == b"ttcf":
            print()
            print("提示：这是 .ttc 字体集合，Kivy 支持有限。")
            print("      若界面中文显示异常，请用 --force 换成单个 .ttf/.otf。")
        print("如需替换，加 --force 参数重跑。")
        return 0

    source = None
    if not args.system:
        source = fetch_open_font()

    if source is None:
        print()
        source = fetch_system_font()

    if source is None:
        print()
        print("=" * 60)
        print("未能获取中文字体。")
        print()
        print("请手动下载一个开源中文字体（如思源黑体、Noto Sans SC），")
        print(f"重命名为 chinese.ttf 放到：{TARGET}")
        print("=" * 60)
        return 1

    size_mb = TARGET.stat().st_size / 1024 / 1024
    print()
    print(f"✓ 字体就绪：{TARGET}")
    print(f"   来源：{source}")
    print(f"   大小：{size_mb:.1f} MB")

    if "勿分发" in source or "商业字体" in source:
        print()
        print("⚠ 这是系统自带商业字体，只能本机调试。")
        print("  正式发布 apk 前，请执行：python pack_font.py --force")
        print("  以换成开源的 Noto Sans SC。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
