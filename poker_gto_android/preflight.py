# -*- coding: utf-8 -*-
"""APK 打包前体检。

在真正开始打包之前，把容易踩的坑先查一遍。打包一次动辄几十分钟，
提前发现问题能省很多时间。

用法（在 poker_gto_android 目录下）：

    python preflight.py
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
OK, WARN, FAIL = "OK  ", "WARN", "FAIL"
_results = []


def check(name, status, detail=""):
    _results.append((status, name, detail))
    icon = {"OK  ": "✓", "WARN": "!", "FAIL": "✗"}[status]
    print(f"  [{icon}] {name}")
    if detail:
        for line in str(detail).splitlines():
            print(f"        {line}")


def main():
    print("=" * 62)
    print("  GTO 助手 - APK 打包前体检")
    print("=" * 62)

    # ---------------------------------------------------------- 源文件
    print("\n【1】必需源文件")
    required = [
        "main.py", "poker_core.py", "ranges.py", "trainer.py",
        "stats.py", "recognizer.py", "realtime.py", "config.py",
        "buildozer.spec",
    ]
    missing = [f for f in required if not (HERE / f).exists()]
    if missing:
        check("源文件完整性", FAIL, "缺失：" + ", ".join(missing))
    else:
        check("源文件完整性", OK, f"{len(required)} 个必需文件都在")

    # ---------------------------------------------------------- 字体
    print("\n【2】中文字体")
    font = HERE / "assets" / "chinese.ttf"
    if not font.exists():
        check("中文字体", FAIL,
              "assets/chinese.ttf 不存在。\n"
              "没有它，界面中文会显示成方块。\n"
              "解决：运行 python pack_font.py")
    else:
        size_mb = font.stat().st_size / 1024 / 1024
        with open(font, "rb") as f:
            head = f.read(4)
        is_ttc = head == b"ttcf"
        is_otf = head[:4] in (b"OTTO", b"\x00\x01\x00\x00", b"true")
        if size_mb < 1:
            check("中文字体", FAIL, f"文件过小（{size_mb:.2f} MB），可能不完整")
        elif is_ttc:
            check("中文字体", WARN,
                  f"{size_mb:.1f} MB，但这是 .ttc 字体集合。\n"
                  "Kivy 对 .ttc 支持有限，若中文不显示请换成单个 .ttf/.otf\n"
                  "推荐：思源黑体 Source Han Sans SC（开源可商用）")
        elif is_otf:
            check("中文字体", OK, f"{size_mb:.1f} MB，格式正常")
        else:
            check("中文字体", OK, f"{size_mb:.1f} MB")

    # 版权提醒
    if font.exists():
        size_mb = font.stat().st_size / 1024 / 1024
        if 17 < size_mb < 21:
            check("字体版权", WARN,
                  "字体大小接近微软雅黑（约 19 MB）。\n"
                  "该字体为 Windows 商业字体，不可随 apk 分发。\n"
                  "发布前请换成开源字体（思源黑体 / 霞鹜文楷 / Noto Sans SC）")

    # ---------------------------------------------------------- buildozer.spec
    print("\n【3】buildozer.spec 配置")
    spec = HERE / "buildozer.spec"
    if spec.exists():
        text = spec.read_text(encoding="utf-8", errors="replace")

        if "kivy" in text.split("requirements")[1].split("\n")[0]:
            check("requirements", WARN,
                  "requirements 里写了 kivy。p4a 会自动注入，手写可能冲突，建议删掉")
        else:
            check("requirements", OK, "未手写 kivy，交给 p4a 自动注入")

        if "p4a.branch" in text:
            check("p4a 版本", OK, "已固定 p4a.branch，构建结果稳定")
        else:
            check("p4a 版本", WARN, "未固定 p4a.branch，不同时间构建可能不一致")

        if "source.include_exts" in text and "ttf" not in text:
            check("字体打包", FAIL, "source.include_exts 里没有 ttf，字体会被打包遗漏")
        else:
            check("字体打包", OK, "ttf 在 include_exts 中")

        perms = ""
        for line in text.splitlines():
            if line.startswith("android.permissions"):
                perms = line
        if "CAMERA" in perms:
            check("权限配置", OK, perms.strip())
        else:
            check("权限配置", FAIL, "缺少 CAMERA 权限，摄像头无法工作")
    else:
        check("buildozer.spec", FAIL, "文件不存在")

    # ---------------------------------------------------------- 语法与导入
    print("\n【4】代码可运行性")
    if shutil.which("python3") or shutil.which("python") or sys.executable:
        py = sys.executable
        bad = []
        for f in required:
            if not f.endswith(".py"):
                continue
            r = subprocess.run(
                [py, "-m", "py_compile", str(HERE / f)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            if r.returncode != 0:
                bad.append(f)
        if bad:
            check("语法检查", FAIL, "以下文件有语法错误：" + ", ".join(bad))
        else:
            check("语法检查", OK, "所有 .py 文件语法正确")
    else:
        check("语法检查", WARN, "未找到 Python，跳过")

    # ---------------------------------------------------------- 批处理文件编码
    # .bat 文件必须同时满足：纯 ASCII、CRLF 换行、无 BOM。
    # cmd.exe 在中文 Windows 上按 GBK 读批处理文件，UTF-8 中文会变成乱码
    # 并把命令从中间劈开；只给 LF 换行同样会让 cmd.exe 读错行。
    print("\n【4b】批处理文件编码（.bat）")
    bat_files = sorted(HERE.glob("*.bat"))
    if not bat_files:
        check("批处理文件", WARN, "未找到 .bat 文件")
    for bat in bat_files:
        raw = bat.read_bytes()
        problems = []
        bom = raw[:3] == b"\xef\xbb\xbf"
        if bom:
            problems.append("含 UTF-8 BOM")
        non_ascii = sum(1 for b in raw if b > 127)
        if non_ascii:
            problems.append(f"含 {non_ascii} 个非 ASCII 字节")
        crlf = raw.count(b"\r\n")
        lone_lf = raw.count(b"\n") - crlf
        if lone_lf:
            problems.append(f"含 {lone_lf} 个裸 LF 换行（应为 CRLF）")
        if problems:
            check(bat.name, FAIL,
                  "；".join(problems) + "\n"
                  "cmd.exe 会读成乱码并报一堆 'xxx 不是内部或外部命令'。\n"
                  "修复：保持文件为纯 ASCII，换行全部用 CRLF，不要加 BOM。")
        else:
            check(bat.name, OK, f"纯 ASCII + CRLF（{len(raw)} 字节）")

    # ---------------------------------------------------------- 打包环境
    print("\n【5】当前打包环境")
    import platform
    sysname = platform.system()
    if sysname == "Linux":
        check("操作系统", OK, f"{sysname} - 可以直接用 Buildozer 打包")
    elif sysname == "Darwin":
        check("操作系统", WARN, f"{sysname} - Buildozer 支持有限，建议用 Linux 或云端构建")
    else:
        check("操作系统", FAIL,
              f"{sysname} - Buildozer 不支持在 Windows 原生运行。\n"
              "请使用以下任一方式：\n"
              "  1) GitHub Actions 云端打包（推荐，见 .github/workflows/build-apk.yml）\n"
              "  2) 安装 WSL2 后在 Ubuntu 里打包\n"
              "  3) 找一台 Linux 机器")

    bz = shutil.which("buildozer")
    check("Buildozer", OK if bz else WARN,
          bz or "未安装（Linux 下执行：pip3 install --user buildozer cython）")

    jh = os.environ.get("JAVA_HOME")
    if shutil.which("java"):
        check("Java", OK, f"JAVA_HOME={jh or '(未设置)'}")
    else:
        check("Java", WARN, "未找到 java（Linux 打包需 openjdk-17-jdk）")

    # ---------------------------------------------------------- 空间
    print("\n【6】磁盘空间")
    try:
        total, used, free = shutil.disk_usage(str(HERE))
        free_gb = free / 2 ** 30
        if free_gb < 8:
            check("可用空间", FAIL, f"仅剩 {free_gb:.1f} GB，打包需至少 8 GB")
        else:
            check("可用空间", OK, f"剩余 {free_gb:.1f} GB（打包需约 5-8 GB）")
    except Exception as e:
        check("可用空间", WARN, str(e))

    # ---------------------------------------------------------- 汇总
    print("\n" + "=" * 62)
    fails = [r for r in _results if r[0] == FAIL]
    warns = [r for r in _results if r[0] == WARN]
    oks = [r for r in _results if r[0] == OK]
    print(f"  结果：{len(oks)} 项通过，{len(warns)} 项警告，{len(fails)} 项失败")
    print("=" * 62)

    if fails:
        print("\n必须先解决的问题：")
        for _, name, detail in fails:
            print(f"  ✗ {name}")
            if detail:
                print(f"      {detail}")
    if warns:
        print("\n建议处理（不阻塞打包）：")
        for _, name, detail in warns:
            print(f"  ! {name}")
            if detail:
                print(f"      {detail}")

    if not fails:
        print("\n一切就绪，可以开始打包：buildozer android debug")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
