# -*- coding: utf-8 -*-
"""AI 识别模块（安卓版）。

沿用 OpenAI 兼容协议，在手机端调用多模态模型识别牌面。
使用标准库 urllib 实现，避免引入额外依赖（安卓打包体积敏感）。
"""

import base64
import json
import ssl
import urllib.error
import urllib.request


class RecognizeError(Exception):
    """识别过程中的可预期错误。"""


# 牌面识别的结构化提示词
CARD_PROMPT = """你是德州扑克牌面识别助手。识别图片中的扑克牌。

严格按以下 JSON 格式输出，不要任何其他文字：
{
  "hole_cards": ["As", "Kh"],
  "board_cards": ["Td", "9c", "2s"],
  "hero_position": "BTN",
  "confidence": "high",
  "notes": "说明"
}

规则：
- 牌面写法：点数(2-9,T,J,Q,K,A) + 花色(s黑桃,h红桃,d方块,c梅花)
- hole_cards：玩家自己的手牌（通常 2 张）
- board_cards：公共牌（0-5 张）
- hero_position：从图中判断的位置，取值 UTG/HJ/CO/BTN/SB/BB，无法判断填 "unknown"
- 看不清的牌填 "??"
- confidence：high / medium / low，表示整体把握
- 图中无扑克牌则两个数组都为空
"""


PRESETS = {
    "智谱 GLM（免费）": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4v-flash",
    },
    "通义千问": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-vl-max",
    },
    "OpenAI": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "Kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k-vision-preview",
    },
    "自定义": {
        "base_url": "",
        "model": "",
    },
}


def recognize(image_base64, config, prompt=None, image_format="JPEG", timeout=90):
    """调用模型识别图像。

    参数:
        image_base64: base64 字符串（不含 data URI 前缀）
        config: 含 api_key / base_url / model 的配置
    返回:
        (模型返回文本, usage 字典)
    """
    api_key = (config.get("api_key") or "").strip()
    base_url = (config.get("base_url") or "").strip().rstrip("/")
    model = (config.get("model") or "").strip()
    prompt = (prompt or config.get("prompt") or CARD_PROMPT).strip()

    if not base_url:
        raise RecognizeError("未配置接口地址")
    if not model:
        raise RecognizeError("未配置模型名称")
    is_local = any(h in base_url for h in ("localhost", "127.0.0.1"))
    if not api_key and not is_local:
        raise RecognizeError("未配置 API Key，请到设置中填写")

    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/{image_format.lower()};base64,{image_base64}"
                }},
            ],
        }],
        "max_tokens": int(config.get("max_tokens", 800)),
        "temperature": float(config.get("temperature", 0.2)),
        "stream": False,
    }

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    # 部分安卓环境缺少根证书，此处放宽校验以保证可用性
    ctx = ssl.create_default_context()
    try:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    except Exception:
        pass

    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        try:
            msg = json.loads(detail).get("error", {}).get("message") or detail
        except (json.JSONDecodeError, AttributeError):
            msg = detail
        raise RecognizeError(f"接口错误 {e.code}：{str(msg)[:300]}") from e
    except urllib.error.URLError as e:
        raise RecognizeError(f"网络失败：{e.reason}") from e
    except TimeoutError as e:
        raise RecognizeError(f"请求超时（{timeout}秒）") from e

    try:
        result = json.loads(body)
    except json.JSONDecodeError as e:
        raise RecognizeError(f"返回无法解析：{body[:200]}") from e

    if "error" in result:
        err = result["error"]
        raise RecognizeError(
            f"接口错误：{err.get('message') if isinstance(err, dict) else err}"
        )

    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RecognizeError(f"返回结构异常：{body[:200]}") from e

    if isinstance(content, list):
        content = "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in content
        )

    if not content or not str(content).strip():
        raise RecognizeError("模型返回空内容")

    return str(content).strip(), result.get("usage") or {}


def parse_cards(text):
    """解析模型返回的牌面 JSON。

    返回 dict: hole_cards / board_cards / hero_position / confidence / notes
    解析失败抛 RecognizeError。
    """
    import re
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```$", "", cleaned)
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        raise RecognizeError(f"未找到 JSON：{text[:200]}")

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        raise RecognizeError(f"JSON 解析失败：{e}") from e

    def norm(key):
        raw = data.get(key) or []
        if not isinstance(raw, list):
            return []
        out = []
        for item in raw:
            if not isinstance(item, str) or not item.strip():
                continue
            item = item.strip()
            if item == "??":
                out.append("??")
            elif len(item) >= 2:
                out.append(item[0].upper() + item[1].lower())
        return out

    return {
        "hole_cards": norm("hole_cards"),
        "board_cards": norm("board_cards"),
        "hero_position": str(data.get("hero_position", "unknown")).upper(),
        "confidence": str(data.get("confidence", "unknown")).lower(),
        "notes": str(data.get("notes", "")),
    }


if __name__ == "__main__":
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler

    print("=== AI 识别模块自检 ===")

    # 模拟接口
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n))
            assert body["model"] == "test-vl"
            assert body["messages"][0]["content"][1]["image_url"]["url"].startswith(
                "data:image/jpeg;base64,"
            )
            # 授权头校验交给独立测试，这里只记录实际收到的值
            H.last_auth = self.headers.get("Authorization")
            resp = {"choices": [{"message": {"content":
                '{"hole_cards":["As","Kh"],"board_cards":["Td","9c","2s"],'
                '"hero_position":"BTN","confidence":"high","notes":"清晰"}'}}],
                "usage": {"total_tokens": 150}}
            data = json.dumps(resp).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    H.last_auth = None
    srv = HTTPServer(("127.0.0.1", 18200), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    cfg = {"api_key": "sk-test", "base_url": "http://127.0.0.1:18200/v1",
           "model": "test-vl"}
    text, usage = recognize("AAAA", cfg)
    print(f"  ✓ 接口调用成功，usage={usage}")
    assert H.last_auth == "Bearer sk-test", f"授权头错误：{H.last_auth}"
    print(f"  ✓ 授权头正确：{H.last_auth}")

    cards = parse_cards(text)
    print(f"  ✓ 解析结果：手牌={cards['hole_cards']} "
          f"公共牌={cards['board_cards']} 位置={cards['hero_position']}")

    # 容错测试
    wrapped = '```json\n{"hole_cards":["Qh","Qs"],"board_cards":[],"confidence":"low"}\n```'
    cards2 = parse_cards(wrapped)
    assert cards2["hole_cards"] == ["Qh", "Qs"], "代码块包裹解析失败"
    print("  ✓ 代码块包裹容错正常")

    # 遮挡牌与低置信度
    occluded = '{"hole_cards":["??","Kh"],"board_cards":["Td"],"confidence":"low"}'
    cards3 = parse_cards(occluded)
    assert cards3["hole_cards"] == ["??", "Kh"], "遮挡牌解析失败"
    assert cards3["confidence"] == "low"
    print("  ✓ 遮挡牌(??)与置信度解析正常")

    # 错误路径：非本地端点缺 Key 应报错
    try:
        recognize("AAAA", {"api_key": "", "base_url": "https://api.openai.com/v1",
                           "model": "gpt-4o-mini"})
        print("  ✗ 非本地端点缺 Key 应报错")
        raise SystemExit(1)
    except RecognizeError as e:
        print(f"  ✓ 缺 Key 校验正常：{e}")

    # 错误路径：无 JSON 输入
    try:
        parse_cards("这里没有任何 JSON")
        print("  ✗ 无 JSON 应报错")
        raise SystemExit(1)
    except RecognizeError:
        print("  ✓ 无 JSON 输入正确报错")

    srv.shutdown()
    print("\n自检通过 ✓")
