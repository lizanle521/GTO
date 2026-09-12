[app]

# ============================================================
#  GTO 助手 - Buildozer 打包配置
#
#  用途：把本项目打包成安卓 apk。
#
#  重要：Buildozer 只能在 Linux/macOS 上运行，Windows 原生不支持。
#        Windows 用户推荐用 GitHub Actions 云端打包（见 .github/workflows/）。
#
#  本地打包命令（Linux 环境）：
#      buildozer android debug
#
#  首次打包会下载 Android SDK/NDK（约 3-5 GB），耗时较长。
# ============================================================

title = GTO 助手
package.name = gtohelper
package.domain = com.gtohelper

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,ttf,otf,json,txt

# 只打包运行必需的文件，测试与文档不进包
source.exclude_dirs = tests,bin,.buildozer,__pycache__,.git,.github,assets/raw
source.exclude_patterns = test_*.py,*.md,*.bat,_probe.py,pack_font.py

version = 0.1.0

# ------------------------------------------------------------
# 依赖
# ------------------------------------------------------------
# 注意：不要在这里写 kivy。python-for-android 会自动注入正确版本的
# kivy，手写容易和自动注入的冲突，导致构建报错或版本错乱。
# pillow：图像处理（帧转 base64）
# numpy：画面差分，变化检测用
requirements = python3,pillow,numpy

# 固定 p4a 版本，避免不同时间构建结果不一致
p4a.branch = v2024.01.21

# ------------------------------------------------------------
# 安卓配置
# ------------------------------------------------------------
# 摄像头预览 + 调用识别 API。
# 不申请存储权限：配置与成绩都写在 App 私有目录，无需外部存储。
android.permissions = CAMERA,INTERNET

# 摄像头在部分设备上需要声明为可选特性，否则会被判定为"必须"
android.features = android.hardware.camera

android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a, armeabi-v7a

android.allow_backup = True
android.wakelock = True

# 摄像头 / 屏幕方向
android.orientation = portrait

# 中文字体已在 assets/chinese.ttf，会被 source.include_exts 带走
# 图标与启动图（可选，放了就用）
# icon.filename = %(source.dir)s/assets/icon.png
# presplash.filename = %(source.dir)s/assets/presplash.png

# ------------------------------------------------------------
# 日志级别
# ------------------------------------------------------------
log_level = 2

[buildozer]

log_level = 2
warn_on_root = 0
