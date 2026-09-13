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
source.exclude_patterns = test_*.py,*.md,*.bat,*.sh,pack_font.py,preflight.py,verify_core.py,build.log,_*.txt

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

# ------------------------------------------------------------
# 目标 CPU 架构
# ------------------------------------------------------------
# 先只打 arm64-v8a（现在市面上 99% 的手机都是这个）。
# 每多一个架构，numpy / pillow 就要用 NDK 重新交叉编译一遍，
# 构建时间和磁盘占用会直接翻倍——这是云端构建超时、磁盘写满
# 最常见的两个原因。等功能验证通过后，如果确实要兼容老机器，
# 再改成 "arm64-v8a, armeabi-v7a"（注意预留 2 倍时间）。
android.archs = arm64-v8a

# ------------------------------------------------------------
# 关键：自动接受 Android SDK 许可证
# ------------------------------------------------------------
# 这一行必须保留。buildozer 这个选项的默认值是 False，此时它会以交互方式
# 询问是否接受 SDK 许可证；在 CI（GitHub Actions）里没有终端可以输入，
# 于是 SDK 组件装不上，构建直接失败，报错通常是：
#   "Failed to install the following Android SDK packages as some licences
#    have not been accepted"
# 本地手动打包时可以删掉（那样会弹出提示让你确认），但在云端必须为 True。
android.accept_sdk_license = True

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
