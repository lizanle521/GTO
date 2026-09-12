# -*- coding: utf-8 -*-
"""摄像头辅助录入模块。

定位说明（重要）
----------------
本模块用于**辅助录入**训练场景，不是实时对局辅助工具。
由于视觉识别牌面存在误差，所有识别结果都必须经过人工校对后才能使用，
请勿将其用于任何真实牌局的实时决策。

依赖：opencv-python（可选）。未安装时界面会给出提示，其余功能不受影响。
"""

import base64
import io

_IMPORT_ERROR = None
try:
    import cv2
except ImportError as e:  # pragma: no cover
    cv2 = None
    _IMPORT_ERROR = str(e)


AVAILABLE = cv2 is not None


def is_available():
    """摄像头功能是否可用。"""
    return AVAILABLE


def unavailable_reason():
    """返回不可用的原因说明。"""
    if AVAILABLE:
        return ""
    return (
        "未安装 opencv-python，摄像头功能不可用。\n"
        "安装命令：pip install opencv-python"
    )


def list_cameras(max_check=5):
    """探测可用的摄像头索引。"""
    if not AVAILABLE:
        return []
    found = []
    for i in range(max_check):
        cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
        if cap.isOpened():
            ok, _ = cap.read()
            if ok:
                found.append(i)
        cap.release()
    return found


class CameraStream:
    """摄像头视频流封装。"""

    def __init__(self, index=0, width=1280, height=720):
        if not AVAILABLE:
            raise RuntimeError(unavailable_reason())
        self.index = index
        self.cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            raise RuntimeError(f"无法打开摄像头 {index}")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    def read(self):
        """读取一帧。返回 (成功, BGR 帧)。"""
        if self.cap is None:
            return False, None
        return self.cap.read()

    def release(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def __del__(self):
        try:
            self.release()
        except Exception:
            pass


def frame_to_base64(frame, jpeg_quality=85, max_width=1280):
    """把 BGR 帧编码为 base64 JPEG 字符串。"""
    if not AVAILABLE:
        raise RuntimeError(unavailable_reason())
    h, w = frame.shape[:2]
    if w > max_width:
        ratio = max_width / w
        frame = cv2.resize(frame, (max_width, int(h * ratio)))

    ok, buf = cv2.imencode(".jpg", frame,
                           [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality])
    if not ok:
        raise RuntimeError("图像编码失败")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def crop_region(frame, x, y, w, h):
    """裁剪指定区域。"""
    if not AVAILABLE:
        raise RuntimeError(unavailable_reason())
    fh, fw = frame.shape[:2]
    x = max(0, min(x, fw - 1))
    y = max(0, min(y, fh - 1))
    w = max(1, min(w, fw - x))
    h = max(1, min(h, fh - y))
    return frame[y:y + h, x:x + w]


# 识别提示词：要求模型输出结构化结果，便于解析与校对
CARD_RECOGNITION_PROMPT = """你是一个扑克牌识别助手。请识别图片中的扑克牌。

请严格按以下 JSON 格式输出，不要添加任何其他文字：
{
  "hole_cards": ["As", "Kh"],
  "board_cards": ["Td", "9c", "2s"],
  "confidence": "high",
  "notes": "识别说明"
}

规则：
- 牌面用 2 字符表示：点数(2-9,T,J,Q,K,A) + 花色(s=黑桃,h=红桃,d=方块,c=梅花)
- hole_cards 是玩家手牌（通常 2 张）
- board_cards 是公共牌（0-5 张）
- 如果看不清某张牌，在该位置填 "??"
- confidence 取值 high / medium / low，反映你的整体把握
- 如果图中没有扑克牌，两个数组都返回空
"""


def parse_card_response(text):
    """解析模型返回的牌面识别结果。

    返回 (手牌列表, 公共牌列表, 置信度, 说明)。解析失败时抛出 ValueError。
    """
    import json
    import re

    # 容错：从返回文本中提取 JSON 块
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise ValueError(f"未找到 JSON 结构：{text[:200]}")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 解析失败：{e}") from e

    def norm_list(key):
        raw = data.get(key) or []
        if not isinstance(raw, list):
            return []
        out = []
        for item in raw:
            if not isinstance(item, str):
                continue
            item = item.strip()
            if not item or item == "??":
                out.append("??")
                continue
            # 规范化：点数大写、花色小写
            if len(item) >= 2:
                out.append(item[0].upper() + item[1].lower())
        return out

    hole = norm_list("hole_cards")
    board = norm_list("board_cards")
    confidence = str(data.get("confidence", "unknown")).lower()
    notes = str(data.get("notes", ""))
    return hole, board, confidence, notes


if __name__ == "__main__":
    print("=== 摄像头模块自检 ===")
    print(f"opencv 可用：{is_available()}")
    if not is_available():
        print(unavailable_reason())
    else:
        import cv2 as _cv2
        print(f"opencv 版本：{_cv2.__version__}")
        cams = list_cameras()
        print(f"检测到的摄像头：{cams if cams else '无'}")

    print("\n=== 响应解析自检 ===")
    samples = [
        '{"hole_cards":["As","Kh"],"board_cards":["Td","9c","2s"],'
        '"confidence":"high","notes":"清晰"}',
        '```json\n{"hole_cards": ["Qh", "Qs"], "board_cards": [], '
        '"confidence": "medium", "notes": ""}\n```',
        '识别结果：{"hole_cards":["??","Kh"],"board_cards":["Td"],'
        '"confidence":"low","notes":"有遮挡"}',
    ]
    ok = True
    for s in samples:
        try:
            hole, board, conf, notes = parse_card_response(s)
            print(f"  ✓ 手牌={hole} 公共牌={board} 置信={conf}")
        except ValueError as e:
            ok = False
            print(f"  ✗ {e}")

    # 错误处理
    try:
        parse_card_response("这里没有任何 JSON")
        ok = False
        print("  ✗ 应当对无 JSON 的输入报错")
    except ValueError:
        print("  ✓ 无 JSON 输入正确报错")

    print("\n自检通过 ✓" if ok else "\n存在失败项 ✗")
