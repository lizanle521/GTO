# -*- coding: utf-8 -*-
"""AI 识别模块（安卓版）。

沿用 OpenAI 兼容协议，在手机端调用多模态模型识别牌面。
使用标准库 urllib 实现，避免引入额外依赖（安卓打包体积敏感）。
"""

import base64
import json
import re
import ssl
import urllib.error
import urllib.request


class RecognizeError(Exception):
    """识别过程中的可预期错误。"""


# 牌面识别的结构化提示词
#
# 设计原则（重要，改动前先读）：
#   这个模型只当"眼睛"，绝不当"大脑"。它唯一的工作是把画面翻译成一份
#   **事实清单**，不允许出现任何打法建议。原因：
#     1) 事实可校验（牌只有 52 张，能查重、能验合法性），意见不可校验；
#     2) 事实错了能定位（是它看错了牌，还是决策层算错了），意见错了说不清；
#     3) 决策必须可复现——同一手牌两次问它可能给不同下注尺度，那种建议
#        没法用来训练，也没法写测试。
#   因此下面这些字段全是"读出来"的，没有一个是"想出来"的。
#
# 字段扁平化也是刻意的：模型输出嵌套 JSON 的出错率明显更高，
# 扁平结构解析简单、容错也好做。
CARD_PROMPT = """你是德州扑克牌桌识别助手。你唯一的工作是读出画面里的事实，
绝对不要给出任何打法建议、不要评价牌力。

严格按以下 JSON 格式输出，不要输出任何其他文字：

{
  "street": "preflop",
  "hole_cards": ["As", "Kh"],
  "board_cards": [],
  "hero_position": "BTN",
  "num_players": 6,
  "effective_stack_bb": 100,
  "pot_bb": 1.5,
  "bet_to_call_bb": 0,
  "num_raisers": 0,
  "num_limpers": 0,
  "confidence": "high",
  "notes": "说明"
}

各字段含义：
- street：阶段，取值 preflop / flop / turn / river（对应公共牌 0/3/4/5 张）
- hole_cards：你自己的手牌，通常 2 张
- board_cards：公共牌，0-5 张
- hero_position：你的位置，取值 UTG / HJ / CO / BTN / SB / BB，看不出填 "unknown"
- num_players：这手牌参与的人数（含你自己），看不出填 null
- effective_stack_bb：有效筹码深度，单位是【大盲】，看不出填 null
- pot_bb：当前底池大小，单位是【大盲】，看不出填 null
- bet_to_call_bb：现在轮到你、需要跟注的金额，单位是【大盲】。
  没有人下注时填 0；看不出填 null
- num_raisers：在你之前【已经加注过】的人数（开池加注也算 1 个），没有填 0
- num_limpers：在你之前【只跟平大盲入池】的人数，没有填 0
- confidence：你对整张画面的把握，high / medium / low
- notes：一句话说明不确定的地方

牌面写法：点数(2-9,T,J,Q,K,A) + 花色(s黑桃,h红桃,d方块,c梅花)，例如 "As" "Td"。
看不清的牌填 "??"。
所有数字如果画面里看不出来，一律填 null，【不要猜测】。猜出来的数字比 null 更糟。
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


# ---------------------------------------------------------------- 解析
STREETS = ("preflop", "flop", "turn", "river")

# 公共牌张数 -> 街。
# 注意别用下标硬套：张数是 0/3/4/5，而不是 0/1/2/3，直接拿它当索引
# 会把"翻牌 3 张"算成河牌（这个坑踩过一次）。
# 另外 1-2 张公共牌在物理上不可能（翻牌一次发 3 张），出现这种情况
# 只可能是识别漏看了，仍按翻牌处理并留警告——若当作翻前处理，
# 后面整条决策都会错位，而且界面上完全看不出来。
def street_of_board(n_cards):
    if n_cards <= 0:
        return "preflop"
    if n_cards <= 3:
        return "flop"
    if n_cards == 4:
        return "turn"
    return "river"


# 场景字段的取值范围，用来把模型的胡说挡在门外。
# 模型偶尔会写出 "筹码深度 99999" 或 "底池 -3" 这类值，
# 与其让它们流进决策层，不如在这里直接判为无效。
SCENE_RANGES = {
    "num_players": (2, 10),
    "num_raisers": (0, 10),
    "num_limpers": (0, 10),
    "effective_stack_bb": (1.0, 1000.0),
    "pot_bb": (0.0, 10000.0),
    "bet_to_call_bb": (0.0, 10000.0),
}

_FLOAT_SCENE_FIELDS = ("effective_stack_bb", "pot_bb", "bet_to_call_bb")

# 决策必需、但模型不一定看得出来的字段。
# 这些取不到值时决策层要用默认值兜底，并在界面上告诉用户。
CRITICAL_SCENE_FIELDS = (
    "num_players", "effective_stack_bb", "pot_bb", "bet_to_call_bb",
)


def _to_number(raw):
    """把模型给的值尽量转成数字；转不了返回 None。

    模型很爱把数字写成 "$2.50" / "大约 100bb" / "2.5 BB" 这类形式，
    所以这里用正则把第一个数字抠出来，而不是要求它必须是纯数字。
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        m = re.search(r"-?\d+(?:\.\d+)?", raw)
        if not m:
            return None
        try:
            return float(m.group(0))
        except ValueError:
            return None
    return None


def _norm_int(raw, lo, hi):
    """归一化为整数；无法解析或超出范围时返回 None。"""
    v = _to_number(raw)
    if v is None:
        return None
    iv = int(round(v))
    return iv if lo <= iv <= hi else None


def _norm_float(raw, lo, hi):
    """归一化为保留两位的浮点；无法解析或超出范围时返回 None。"""
    v = _to_number(raw)
    if v is None or not (lo <= v <= hi):
        return None
    return round(v, 2)


def parse_cards(text):
    """解析模型返回的 JSON。

    返回 dict，同时含牌面字段与场景字段：
        street / hole_cards / board_cards / hero_position / confidence / notes
        num_players / effective_stack_bb / pot_bb / bet_to_call_bb /
        num_raisers / num_limpers
        warnings（列表，记录被纠正或被忽略的字段）

    解析失败抛 RecognizeError。

    场景字段取不到时给 None 而**不抛错**：识别不出筹码深度不该让整次
    识别失败，交给决策层用默认值兜底并在界面上提示即可。
    """
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
    if not isinstance(data, dict):
        raise RecognizeError(f"JSON 顶层不是对象：{text[:200]}")

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

    hole = norm("hole_cards")
    board = norm("board_cards")
    warnings = []

    # 公共牌超过 5 张一定是识别错了，截断并留痕
    if len(board) > 5:
        warnings.append(f"公共牌识别到 {len(board)} 张（最多 5 张），已只取前 5 张")
        board = board[:5]

    # 街：一律以公共牌张数为准。
    # 公共牌是能直接数出来的硬事实，模型自报的 street 只是参考。两者
    # 冲突时信公共牌——否则会出现"牌面 3 张、却按河牌给建议"这种
    # 会直接毁掉决策的矛盾，而且从界面上完全看不出来。
    street = street_of_board(len(board))
    if 0 < len(board) < 3:
        warnings.append(
            f"翻牌只识别到 {len(board)} 张（应为 3 张），牌面可能不完整"
        )
    claimed = str(data.get("street") or "").strip().lower()
    if claimed in STREETS and claimed != street:
        warnings.append(
            f"模型判断为 {claimed}，但公共牌有 {len(board)} 张，已按 {street} 处理"
        )

    result = {
        "street": street,
        "hole_cards": hole,
        "board_cards": board,
        "hero_position": str(data.get("hero_position", "unknown")).upper(),
        "confidence": str(data.get("confidence", "unknown")).lower(),
        "notes": str(data.get("notes", "")),
        "warnings": warnings,
    }

    for field, (lo, hi) in SCENE_RANGES.items():
        raw = data.get(field)
        if field in _FLOAT_SCENE_FIELDS:
            value = _norm_float(raw, lo, hi)
        else:
            value = _norm_int(raw, lo, hi)
        result[field] = value
        # 有值但被判为不可用 -> 说清楚，别让用户以为读到了
        if raw is not None and value is None:
            warnings.append(f"{field} 读到的值 {raw!r} 不可用，已忽略")

    return result


def missing_scene_fields(cards):
    """返回缺失的关键场景字段，供界面提示「需要手动确认」用。"""
    return [f for f in CRITICAL_SCENE_FIELDS if cards.get(f) is None]


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
            # 故意混入 "6 人" / "$100" 这类脏值，验证数字抠取
            resp = {"choices": [{"message": {"content":
                '{"street":"flop","hole_cards":["As","Kh"],'
                '"board_cards":["Td","9c","2s"],"hero_position":"BTN",'
                '"num_players":"6 人","effective_stack_bb":"$100",'
                '"pot_bb":"6.5 BB","bet_to_call_bb":0,'
                '"num_raisers":1,"num_limpers":0,'
                '"confidence":"high","notes":"清晰"}'}}],
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

    print("\n--- 场景字段 ---")
    assert cards["street"] == "flop", f"街判断错误：{cards['street']}"
    assert cards["num_players"] == 6, f"「6 人」应抠出 6，实得 {cards['num_players']}"
    assert cards["effective_stack_bb"] == 100.0, \
        f"「$100」应抠出 100，实得 {cards['effective_stack_bb']}"
    assert cards["pot_bb"] == 6.5, f"「6.5 BB」应抠出 6.5，实得 {cards['pot_bb']}"
    assert cards["bet_to_call_bb"] == 0.0, f"无人下注应为 0，实得 {cards['bet_to_call_bb']}"
    assert cards["num_raisers"] == 1
    print(f"  ✓ 脏值抠取正常：人数={cards['num_players']} "
          f"筹码={cards['effective_stack_bb']}bb 底池={cards['pot_bb']}bb "
          f"加注人数={cards['num_raisers']}")

    # 街的口径：模型自报与公共牌张数冲突时，必须信公共牌
    conflict = ('{"street":"river","hole_cards":["As","Kh"],'
                '"board_cards":["Td","9c","2s"],"confidence":"high"}')
    c_conflict = parse_cards(conflict)
    assert c_conflict["street"] == "flop", \
        f"街冲突时应以公共牌张数为准，实得 {c_conflict['street']}"
    assert c_conflict["warnings"], "街冲突应留下警告"
    print(f"  ✓ 街冲突以公共牌为准：{c_conflict['warnings'][0]}")

    # 离谱数值必须被拦下，不能流进决策层
    bogus = ('{"hole_cards":["As","Kh"],"board_cards":["Td","9c","2s"],'
             '"num_players":99,"pot_bb":-5,"effective_stack_bb":null}')
    c_bogus = parse_cards(bogus)
    assert c_bogus["num_players"] is None, "人数 99 应被判为无效"
    assert c_bogus["pot_bb"] is None, "负底池应被判为无效"
    assert c_bogus["effective_stack_bb"] is None
    missing = missing_scene_fields(c_bogus)
    assert "effective_stack_bb" in missing and "pot_bb" in missing
    print(f"  ✓ 离谱数值被拦下；缺失关键字段：{missing}")

    # 容错测试
    wrapped = '```json\n{"hole_cards":["Qh","Qs"],"board_cards":[],"confidence":"low"}\n```'
    cards2 = parse_cards(wrapped)
    assert cards2["hole_cards"] == ["Qh", "Qs"], "代码块包裹解析失败"
    assert cards2["street"] == "preflop", "无公共牌应为翻前"
    print("  ✓ 代码块包裹容错正常（旧格式缺场景字段也不崩）")

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
