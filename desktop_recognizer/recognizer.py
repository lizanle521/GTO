# -*- coding: utf-8 -*-
"""AI 识别模块：把截图发送给多模态大模型，返回识别结果。

统一使用 OpenAI 兼容协议（/chat/completions），因此可选：
官方 OpenAI、通义千问(DashScope 兼容模式)、智谱 GLM、DeepSeek、
Kimi(Moonshot)、本地 Ollama、vLLM、One-API 等任意兼容端点。
"""

import base64
import json
import urllib.error
import urllib.request


class RecognizeError(Exception):
    """识别过程中的可预期错误（网络、鉴权、格式等）。"""


def build_messages(image_b64, prompt, image_format="PNG"):
    """构造 OpenAI 兼容的多模态 messages 结构。"""
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/{image_format.lower()};base64,{image_b64}"
                    },
                },
            ],
        }
    ]


def recognize(image_b64, config, image_format="PNG", timeout=120):
    """调用模型识别图像。

    参数:
        image_b64: base64 编码的图像字符串（不含 data URI 前缀）
        config:    配置字典，需含 api_key / base_url / model / prompt 等
        timeout:   请求超时秒数

    返回:
        模型返回的纯文本内容

    异常:
        RecognizeError: 参数缺失、网络错误、接口报错等
    """
    api_key = (config.get("api_key") or "").strip()
    base_url = (config.get("base_url") or "").strip().rstrip("/")
    model = (config.get("model") or "").strip()
    prompt = (config.get("prompt") or "").strip()

    if not base_url:
        raise RecognizeError("未配置接口地址（base_url）")
    if not model:
        raise RecognizeError("未配置模型名称（model）")
    if not prompt:
        raise RecognizeError("未配置识别提示词（prompt）")
    # 本地端点（Ollama 等）通常不需要 Key
    is_local = any(h in base_url for h in ("localhost", "127.0.0.1", "0.0.0.0"))
    if not api_key and not is_local:
        raise RecognizeError("未配置 API Key，请先在「设置」中填写")

    url = f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "messages": build_messages(image_b64, prompt, image_format),
        "max_tokens": int(config.get("max_tokens", 1500)),
        "temperature": float(config.get("temperature", 0.3)),
        "stream": False,
    }

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            msg = parsed.get("error", {}).get("message") or detail
        except (json.JSONDecodeError, AttributeError):
            msg = detail
        raise RecognizeError(f"接口返回错误 {e.code}：{msg[:500]}") from e
    except urllib.error.URLError as e:
        raise RecognizeError(f"网络请求失败：{e.reason}") from e
    except TimeoutError as e:
        raise RecognizeError(f"请求超时（{timeout}s），可尝试缩小截图比例或换更快的模型") from e

    try:
        result = json.loads(body)
    except json.JSONDecodeError as e:
        raise RecognizeError(f"接口返回内容无法解析：{body[:300]}") from e

    if "error" in result:
        err = result["error"]
        msg = err.get("message") if isinstance(err, dict) else str(err)
        raise RecognizeError(f"接口返回错误：{msg}")

    try:
        choices = result["choices"]
        content = choices[0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RecognizeError(f"接口返回结构异常：{body[:300]}") from e

    # 部分模型返回 content 为数组（分段），拼接其中的 text
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            elif isinstance(item, str):
                parts.append(item)
        content = "".join(parts)

    if not content or not str(content).strip():
        raise RecognizeError("模型返回了空内容，请重试或更换模型")

    usage = result.get("usage") or {}
    return str(content).strip(), usage


# 常用服务商预设，方便界面一键切换
PRESETS = {
    "OpenAI": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
    "阿里云通义千问": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-vl-max",
    },
    "智谱 GLM": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4v-flash",
    },
    "Kimi (Moonshot)": {
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k-vision-preview",
    },
    "DeepSeek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "本地 Ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "llama3.2-vision",
    },
    "自定义": {
        "base_url": "",
        "model": "",
    },
}
