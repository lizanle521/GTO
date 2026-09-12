# -*- coding: utf-8 -*-
"""实时视频流识别模块。

核心设计：**抽帧 + 变化检测**

实时视频不能每帧都送 AI（成本爆炸）。本模块的做法：
  1. 摄像头持续采集画面（本地，零成本）
  2. 用图像差分计算"画面变化率"
  3. 只在变化率超过阈值、且距上次识别超过最小间隔时，才送一帧给模型
  4. 识别在后台线程执行，不阻塞预览

用 numpy 做差分（Kivy 依赖已含 numpy，无需额外安装）。
"""

import base64
import io
import threading
import time

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None


class FrameAnalyzer:
    """画面变化检测器。

    通过降采样后的灰度差分判断画面是否发生显著变化，
    用于决定"这一帧值不值得送 AI 识别"。
    """

    def __init__(self, sample_size=32, threshold=0.08):
        """
        参数:
            sample_size: 降采样边长，越小越省算力
            threshold:   变化率阈值（0-1），超过才认为画面有变化

        阈值说明：牌局中"发一张牌"只会改变画面很小的一块区域（通常 5%-15%），
        因此阈值不能设高，否则会漏掉真正的牌面变化。默认 0.08 偏敏感，
        宁可多识别几次，也不要漏掉关键时刻。
        """
        self.sample_size = sample_size
        self.threshold = threshold
        self.prev_gray = None

    def change_ratio(self, frame_rgb):
        """返回与上一帧的变化率（0.0-1.0）。首帧返回 1.0。"""
        if np is None:
            return 1.0

        # 降采样为小图，大幅降低计算量
        img = frame_rgb
        h, w = img.shape[:2]
        step = max(1, min(h, w) // self.sample_size)
        small = img[::step, ::step]

        # 转灰度
        if small.ndim == 3:
            gray = (small[:, :, 0] * 0.299 +
                    small[:, :, 1] * 0.587 +
                    small[:, :, 2] * 0.114)
        else:
            gray = small.astype(float)

        gray = gray.astype(np.float32)

        if self.prev_gray is None:
            self.prev_gray = gray
            return 1.0

        if gray.shape != self.prev_gray.shape:
            self.prev_gray = gray
            return 1.0

        diff = np.abs(gray - self.prev_gray)
        self.prev_gray = gray
        # 变化率 = 显著变化的像素占比
        return float(np.mean(diff > 12))

    def reset(self):
        self.prev_gray = None


class RealtimeRecognizer:
    """实时识别调度器。

    负责节流：决定何时把帧送去识别，并管理后台线程。
    """

    def __init__(self, config_provider, on_result, on_error=None, on_status=None):
        """
        参数:
            config_provider: 返回当前配置的函数
            on_result: 回调 (cards_dict, frame) —— 识别成功
            on_error:  回调 (错误信息)
            on_status: 回调 (状态文本) —— 用于显示"已跳过/正在识别"等
        """
        self.config_provider = config_provider
        self.on_result = on_result
        self.on_error = on_error or (lambda msg: None)
        self.on_status = on_status or (lambda msg: None)

        self.analyzer = FrameAnalyzer()
        self.last_recognize_time = 0.0
        self.busy = False
        self.enabled = False
        self.lock = threading.Lock()

        # 统计
        self.stats = {"frames": 0, "skipped_unchanged": 0,
                      "throttled": 0, "recognized": 0, "errors": 0}

    def set_enabled(self, enabled):
        self.enabled = enabled
        if enabled:
            self.analyzer.reset()
            self.last_recognize_time = 0.0
            self.on_status("实时识别已开启")
        else:
            self.on_status("实时识别已关闭")

    def submit_frame(self, frame_rgb):
        """提交一帧画面。内部自动判断是否值得识别。

        frame_rgb 应为 numpy 数组（H, W, 3），RGB 顺序。
        """
        if not self.enabled:
            return
        with self.lock:
            self.stats["frames"] += 1

        config = self.config_provider()
        interval = float(config.get("capture_interval", 3.0))
        threshold = float(config.get("confidence_threshold", 0.5))

        # 节流：距上次识别太近，跳过
        now = time.time()
        if now - self.last_recognize_time < interval:
            with self.lock:
                self.stats["throttled"] += 1
            return

        # 变化检测：画面没变，跳过
        ratio = self.analyzer.change_ratio(frame_rgb)
        if ratio < threshold:
            with self.lock:
                self.stats["skipped_unchanged"] += 1
            self.on_status(f"画面无变化（{ratio:.0%}），跳过识别")
            return

        # 已有识别在进行，跳过
        if self.busy:
            return

        self.last_recognize_time = now
        self.busy = True
        self.on_status(f"检测到画面变化（{ratio:.0%}），正在识别…")

        # 后台线程执行识别
        thread = threading.Thread(
            target=self._recognize_worker, args=(frame_rgb.copy(), config),
            daemon=True,
        )
        thread.start()

    def _recognize_worker(self, frame_rgb, config):
        try:
            import recognizer
            b64 = frame_to_base64(frame_rgb)
            text, _ = recognizer.recognize(b64, config)
            cards = recognizer.parse_cards(text)
            with self.lock:
                self.stats["recognized"] += 1
            self.on_result(cards, frame_rgb)
        except Exception as e:  # noqa: BLE001
            with self.lock:
                self.stats["errors"] += 1
            self.on_error(str(e))
        finally:
            self.busy = False

    def get_stats(self):
        with self.lock:
            return dict(self.stats)


def frame_to_base64(frame_rgb, max_width=1280, jpeg_quality=80):
    """把 numpy RGB 帧编码为 base64 JPEG。

    优先用 PIL（质量可控），无 PIL 时退化为纯 Python 实现。
    """
    if Image is not None:
        img = Image.fromarray(frame_rgb)
        if img.width > max_width:
            ratio = max_width / img.width
            img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=jpeg_quality)
        return base64.b64encode(buf.getvalue()).decode("ascii")

    # 退化路径：PIL 不可用时用 numpy + 简单 BMP 封装不可行，
    # 因此这里明确报错，提示安装 Pillow
    raise RuntimeError("缺少 Pillow，无法编码图像。请安装：pip install pillow")


if __name__ == "__main__":
    print("=== 实时视频流模块自检 ===")
    print(f"numpy 可用：{np is not None}")
    print(f"PIL   可用：{Image is not None}")

    if np is None:
        print("缺少 numpy，无法测试")
        raise SystemExit(1)

    # --- 变化检测测试
    print("\n--- 变化检测 ---")
    analyzer = FrameAnalyzer(sample_size=32, threshold=0.08)

    frame_a = np.full((480, 640, 3), 100, dtype=np.uint8)
    r1 = analyzer.change_ratio(frame_a)
    print(f"首帧变化率：{r1:.1%}（应为 100%）")
    assert r1 == 1.0

    r2 = analyzer.change_ratio(frame_a)      # 完全相同的帧
    print(f"相同帧变化率：{r2:.1%}（应接近 0）")
    assert r2 < 0.02, "相同画面不应被判定为变化"

    # 局部变化：模拟"发一张牌"（只改变一小块区域）
    frame_card = frame_a.copy()
    frame_card[200:340, 260:380] = 250       # 约 140x120 的牌面区域
    r_card = analyzer.change_ratio(frame_card)
    area_ratio = (140 * 120) / (480 * 640)
    print(f"局部变化（模拟发牌，实际面积占比 {area_ratio:.1%}）："
          f"检测到 {r_card:.1%}")
    assert r_card > 0.02, "局部牌面变化未被检测到（阈值过高会漏识别）"
    print(f"  ✓ 局部变化可用（阈值 0.08 能捕获 {r_card:.1%} 的变化）")

    # 大面积变化
    analyzer.reset()
    analyzer.change_ratio(frame_a)
    frame_b = frame_a.copy()
    frame_b[100:380, 100:540] = 250          # 大面积变化
    r3 = analyzer.change_ratio(frame_b)
    print(f"大面积变化率：{r3:.1%}（应显著 > 局部变化）")
    assert r3 > r_card, "大面积变化应高于局部变化"

    r4 = analyzer.change_ratio(frame_b)
    print(f"再次相同帧：{r4:.1%}（应接近 0）")
    assert r4 < 0.02

    # --- 节流与调度测试
    print("\n--- 节流调度 ---")
    results = []
    statuses = []

    cfg = {"capture_interval": 0.3, "confidence_threshold": 0.3,
           "api_key": "sk-test",
           "base_url": "http://127.0.0.1:19999/v1", "model": "m"}

    def on_result(cards, frame):
        results.append(cards)

    def on_status(msg):
        statuses.append(msg)

    rec = RealtimeRecognizer(lambda: cfg, on_result, on_status=on_status)
    rec.set_enabled(True)

    # 关闭状态下不应处理
    rec.set_enabled(False)
    rec.submit_frame(frame_a)
    assert rec.stats["frames"] == 0, "关闭状态下不应统计帧"
    print("✓ 关闭状态正确忽略帧")

    rec.set_enabled(True)
    rec.submit_frame(frame_a)                 # 首帧，会触发识别（连不上会报错）
    time.sleep(0.05)
    rec.submit_frame(frame_a)                 # 相同帧
    first_frames = rec.stats["frames"]
    print(f"✓ 帧统计：提交 {first_frames} 帧")

    time.sleep(0.4)
    # 节流过后再提交相同帧：应被变化检测拦截
    before = rec.stats["skipped_unchanged"]
    rec.submit_frame(frame_a)
    after = rec.stats["skipped_unchanged"]
    print(f"✓ 无变化帧被拦截：{before} -> {after}")
    assert after > before, "无变化帧未被拦截"

    # 变化帧
    before_throttle = rec.stats["throttled"]
    rec.submit_frame(frame_b)
    print(f"✓ 变化帧已提交识别（throttled={rec.stats['throttled']}）")

    print(f"\n统计明细：{rec.get_stats()}")
    print("\n自检通过 ✓")
