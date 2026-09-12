#!/usr/bin/env bash
# ============================================================
#  GTO 助手 - 一键打包 APK（Linux / WSL2 / macOS 用）
#
#  用法：
#      chmod +x build_apk.sh
#      ./build_apk.sh
#
#  首次运行会自动安装系统依赖和 Buildozer，然后开始打包。
#  首次打包需下载 Android SDK/NDK（3-5 GB），耗时 20-60 分钟。
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[信息]${NC} $*"; }
warn()  { echo -e "${YELLOW}[注意]${NC} $*"; }
error() { echo -e "${RED}[错误]${NC} $*"; }

echo "============================================================"
echo "  GTO 助手 - APK 打包"
echo "============================================================"
echo

# ---------------------------------------------------------- 环境检查
if [[ "$(uname -s)" != "Linux" ]]; then
    error "Buildozer 只能在 Linux 上运行。"
    echo "  当前系统：$(uname -s)"
    echo
    echo "  Windows 用户请用以下方案："
    echo "    1) GitHub Actions 云端打包（见 .github/workflows/build-apk.yml）"
    echo "    2) 安装 WSL2：wsl --install -d Ubuntu"
    exit 1
fi

# ---------------------------------------------------------- 系统依赖
info "检查系统依赖..."

MISSING=()
command -v git    >/dev/null 2>&1 || MISSING+=(git)
command -v zip    >/dev/null 2>&1 || MISSING+=(zip)
command -v unzip  >/dev/null 2>&1 || MISSING+=(unzip)
command -v java   >/dev/null 2>&1 || MISSING+=(openjdk-17-jdk)
command -v cmake  >/dev/null 2>&1 || MISSING+=(cmake)
command -v autoconf >/dev/null 2>&1 || MISSING+=(autoconf)
command -v libtool  >/dev/null 2>&1 || MISSING+=(libtool)

if [ ${#MISSING[@]} -gt 0 ]; then
    warn "缺少依赖：${MISSING[*]}"
    echo
    read -r -p "是否现在安装？需要 sudo 权限 [y/N] " ans
    if [[ "$ans" =~ ^[Yy]$ ]]; then
        sudo apt-get update
        sudo apt-get install -y \
            git zip unzip openjdk-17-jdk \
            autoconf libtool pkg-config \
            zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo5 \
            cmake libffi-dev libssl-dev \
            python3-pip python3-setuptools
        info "系统依赖安装完成"
    else
        error "依赖不全，无法继续"
        exit 1
    fi
else
    info "系统依赖齐全"
fi

# Java 版本检查
JAVA_VER=$(java -version 2>&1 | head -n1 | grep -oP '"\K[0-9]+' || echo "0")
if [ "$JAVA_VER" -lt 11 ]; then
    warn "Java 版本为 $JAVA_VER，建议 17（openjdk-17-jdk）"
fi

# ---------------------------------------------------------- Buildozer
if ! command -v buildozer >/dev/null 2>&1; then
    info "安装 Buildozer 和 Cython..."
    pip3 install --user --upgrade buildozer cython==0.29.36
    export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v buildozer >/dev/null 2>&1; then
    error "Buildozer 安装后仍找不到，请把 ~/.local/bin 加入 PATH"
    exit 1
fi
info "Buildozer: $(command -v buildozer)"

# ---------------------------------------------------------- 字体
echo
info "检查中文字体..."
if [ ! -f "assets/chinese.ttf" ]; then
    warn "assets/chinese.ttf 不存在"
    echo
    echo "  下载开源的 Noto Sans SC（SIL OFL 1.1，可商用）..."
    mkdir -p assets
    curl -L --retry 3 -o assets/chinese.ttf \
        "https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/SC/NotoSansSC-Regular.otf" \
        || warn "下载失败，请手动放置字体到 assets/chinese.ttf"
fi

if [ -f "assets/chinese.ttf" ]; then
    FONT_SIZE=$(du -h assets/chinese.ttf | cut -f1)
    info "字体就绪：$FONT_SIZE"
fi

# ---------------------------------------------------------- 体检
echo
info "运行打包前体检..."
python3 preflight.py || {
    warn "体检发现问题，请查看上面的报告"
    echo
    read -r -p "是否仍要继续打包？[y/N] " ans
    [[ "$ans" =~ ^[Yy]$ ]] || exit 1
}

# ---------------------------------------------------------- 打包
echo
echo "============================================================"
info "开始打包（首次会下载 Android SDK/NDK，请耐心等待）"
echo "============================================================"
echo

buildozer -v android debug

# ---------------------------------------------------------- 结果
echo
echo "============================================================"
if ls bin/*.apk >/dev/null 2>&1; then
    info "打包成功！"
    echo
    for apk in bin/*.apk; do
        SIZE=$(du -h "$apk" | cut -f1)
        echo "  APK: $apk  ($SIZE)"
    done
    echo
    echo "  安装到手机："
    echo "    1) 把 apk 传到手机，点击安装（需允许未知来源）"
    echo "    2) 或开启 USB 调试后执行：adb install -r bin/*.apk"
else
    error "未找到生成的 apk，请检查上面的构建日志"
    exit 1
fi
echo "============================================================"
