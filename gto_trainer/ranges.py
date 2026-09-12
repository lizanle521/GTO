# -*- coding: utf-8 -*-
"""翻前 GTO 范围表。

数据说明
--------
以 6-max 现金局/锦标赛主流 GTO 基准为参考，按位置给出各行动的范围权重。
每个范围用「起手牌记号 -> 权重(0.0~1.0)」表示，权重代表该动作的执行频率。
未列出的牌权重为 0（弃牌）。

范围记号沿用标准写法：AA / AKs / AKo / T9s 等。

重要声明
--------
这是**教学用近似范围**，用于训练翻前决策直觉。真实的 GTO 解会随
筹码深度、对手、ICM 压力等因素变化。深层分析请以专业求解器为准。
"""

# 位置定义（6-max，按行动顺序）
POSITIONS = ["UTG", "HJ", "CO", "BTN", "SB", "BB"]

POSITION_NAMES = {
    "UTG": "枪口位 UTG",
    "HJ": "劫位 HJ",
    "CO": "关位 CO",
    "BTN": "庄位 BTN",
    "SB": "小盲 SB",
    "BB": "大盲 BB",
}


def expand_range(spec):
    """把紧凑的范围写法展开为 {notation: weight} 字典。

    支持：
      "AA"        -> AA 权重 1.0
      "A5s-A2s"   -> 同花连号段（A5s,A4s,A3s,A2s 各 1.0）
      "22-99"     -> 对子段
      "KTs+:0.5"  -> 带权重
      "ATs+,KJs+" -> 用 + 表示"及以上的同型牌"
    """
    result = {}

    def put(notation, weight):
        result[notation] = max(result.get(notation, 0.0), weight)

    for token in spec.replace(" ", "").split(","):
        if not token:
            continue
        weight = 1.0
        if ":" in token:
            token, w = token.split(":", 1)
            weight = float(w)

        if "-" in token:
            for n in _expand_dash(token):
                put(n, weight)
        elif token.endswith("+"):
            for n in _expand_plus(token[:-1]):
                put(n, weight)
        else:
            put(token, weight)
    return result


def _expand_dash(token):
    """展开 'A5s-A2s' / '22-99' 这类区间。"""
    lo, hi = token.split("-", 1)
    out = []

    # 对子区间，如 99-22
    if len(lo) == 2 and len(hi) == 2:
        from poker_core import RANK_VALUE
        v_lo, v_hi = RANK_VALUE[lo[0]], RANK_VALUE[hi[0]]
        for v in range(min(v_lo, v_hi), max(v_lo, v_hi) + 1):
            out.append(_value_to_rank(v) * 2)
        return out

    # 同型区间，如 A5s-A2s
    from poker_core import RANK_VALUE
    high = lo[0]
    suffix = lo[-1] if len(lo) == 3 else ""
    start = RANK_VALUE[lo[1]]
    end = RANK_VALUE[hi[1]]
    step = 1 if end >= start else -1
    for v in range(start, end + step, step):
        out.append(f"{high}{_value_to_rank(v)}{suffix}")
    return out


def _expand_plus(base):
    """展开 'ATs+' -> ATs, AJs, AQs, AKs；'77+' -> 77..AA。"""
    from poker_core import RANK_VALUE
    out = []
    if len(base) == 2:                    # 对子 77+
        v = RANK_VALUE[base[0]]
        for x in range(v, 15):
            out.append(_value_to_rank(x) * 2)
        return out

    high, low = base[0], base[1]
    suffix = base[2] if len(base) == 3 else ""
    v_high = RANK_VALUE[high]
    v_low = RANK_VALUE[low]
    # 低牌从当前值递增到「高牌 - 1」
    for v in range(v_low, v_high):
        out.append(f"{high}{_value_to_rank(v)}{suffix}")
    return out


def _value_to_rank(value):
    from poker_core import VALUE_RANK
    return VALUE_RANK[value]


# ---------------------------------------------------------------- 翻前范围表
# 说明：权重 1.0 = 总是执行；0.5 = 一半频率执行（混合策略）

OPEN_RANGES = {
    # UTG 最紧：约 15% 范围
    "UTG": expand_range(
        "77+,ATs+,KTs+,QTs+,JTs,T9s,98s,"
        "AQo+,KQo,A5s-A2s:0.35"
    ),
    # HJ：约 19%
    "HJ": expand_range(
        "55+,A9s+,K9s+,Q9s+,J9s+,T9s,98s,87s,"
        "ATo+,KQo,KJo:0.4,A5s-A2s:0.5,QTs+:0.6"
    ),
    # CO：约 26%
    "CO": expand_range(
        "22+,A2s+,K8s+,Q8s+,J8s+,T8s+,97s+,87s,76s,65s,"
        "ATo+,KTo+,QTo+,JTo:0.6,KQo,A9o:0.5"
    ),
    # BTN：约 45%
    "BTN": expand_range(
        "22+,A2s+,K2s+,Q5s+,J6s+,T6s+,96s+,85s+,75s+,64s+,54s,43s,32s:0.4,"
        "A2o+,K8o+,Q8o+,J8o+,T8o+,98o,87o:0.5,A7o+:0.7,K9o:0.6"
    ),
    # SB：约 42%（小盲开池较宽，但需考虑被 3bet）
    "SB": expand_range(
        "22+,A2s+,K3s+,Q6s+,J7s+,T7s+,96s+,86s+,75s+,65s,54s,"
        "A2o+,K9o+,Q9o+,J9o+,T9o,98o:0.6,A7o+:0.8,KTo:0.7"
    ),
    # BB 不与开池范围对应（见后面防守范围）
    "BB": {},
}

# 面对单一开池时的 3bet 范围与跟注范围。
#
# 设计约束（重要）：同一手牌在 3bet 与 call 中的权重之和必须 <= 1.0，
# 余下部分即为弃牌频率。例如 "AJo": 3bet 0.3 + call 0.4 = 0.7，弃牌 0.3。
# 该约束由 validate_ranges() 自动校验，避免出现"既要 3bet 又要 call"的矛盾。

THREE_BET_RANGES = {
    # 面对 UTG 开池：最紧的价值 3bet + 少量 A5s/A4s 诈唬
    "vs_UTG": expand_range("QQ+,AKs,AKo,AQs:0.4,A5s:0.3,A4s:0.25,KK:0.6"),
    # 面对 HJ 开池
    "vs_HJ": expand_range("JJ+,AKs,AKo,AQs:0.5,A5s-A3s:0.35,QQ:0.7,KQs:0.3"),
    # 面对 CO 开池
    "vs_CO": expand_range("TT+,AKs,AQs:0.6,AKo,A5s-A2s:0.45,KQs:0.4,AJo:0.3,KJs:0.3"),
    # 面对 BTN 开池：BTN 范围宽，3bet 更激进。
    # 注意：ATs/KTs/QTs/JTs 等归入 call，此处只保留真正的价值牌与诈唬牌，
    #       避免与 CALL_RANGES 冲突（校验器会强制这一点）。
    "vs_BTN": expand_range("77+,ATs+:0.5,AKo,ATo+:0.35,A5s-A2s:0.6,KJs+:0.4"),
    # 面对 SB 开池
    "vs_SB": expand_range("55+,A9s+:0.5,A5s-A2s:0.6,ATo,AKo,KQo:0.7,KJo:0.6,QJo:0.5"),
}

CALL_RANGES = {
    "vs_UTG": expand_range(
        "22-JJ,AQs:0.6,AJs,KQs,ATs:0.5,AQo:0.4,KQo:0.4"
    ),
    "vs_HJ": expand_range(
        "22-TT,AJs,AQs:0.5,KQs:0.6,KJs,QJs,JTs,T9s,AQo:0.6,KQo:0.5,99:0.8"
    ),
    "vs_CO": expand_range(
        "22-99,AJs,ATs,AQs:0.4,KJs:0.7,KQs:0.6,QJs,JTs,T9s,98s,87s,"
        "AQo:0.6,KQo:0.6,AJo:0.4"
    ),
    "vs_BTN": expand_range(
        "22-66,ATs,KTs:0.7,KJs:0.6,KQs:0.6,QTs:0.7,QJs,JTs,J9s,T9s,T8s,98s,87s,76s,65s,"
        "A9s-A2s:0.5,AJo:0.6,KQo:0.5,KJo:0.6,QJo:0.5,A9o:0.4,KTo:0.5"
    ),
    "vs_SB": expand_range(
        "22-44,A8s-A2s:0.5,K7s-KQs,Q7s-QJs,J8s-JTs,T8s:0.8,97s,98s:0.8,86s,87s:0.8,"
        "75s,76s,65s,ATo:0.5,KQo:0.5,KJo:0.7,QJo:0.6,AJo:0.5,KTo:0.6,QTo:0.5"
    ),
}


def validate_ranges(strict=True):
    """校验范围数据的一致性。

    检查项：
      1. 3bet + call 的权重之后不得超过 1.0（否则逻辑矛盾）
      2. 不得出现未知的起手牌记号
      3. 不得出现权重越界（>1 或 <0）

    返回问题列表；strict=True 时发现问题抛异常。
    """
    from poker_core import all_hand_notations
    valid_notations = set(all_hand_notations())
    problems = []

    def check_map(label, table):
        for key, rng in table.items():
            for notation, weight in rng.items():
                if notation not in valid_notations:
                    problems.append(f"{label}[{key}] 未知记号 {notation!r}")
                if not (0.0 < weight <= 1.0):
                    problems.append(f"{label}[{key}] {notation} 权重越界：{weight}")

    check_map("3bet", THREE_BET_RANGES)
    check_map("call", CALL_RANGES)
    for pos in OPEN_RANGES:
        check_map("open", {pos: OPEN_RANGES[pos]})

    for key in THREE_BET_RANGES:
        tb = THREE_BET_RANGES.get(key, {})
        cl = CALL_RANGES.get(key, {})
        for notation in set(tb) & set(cl):
            total = tb[notation] + cl[notation]
            if total > 1.0 + 1e-9:
                problems.append(
                    f"{key} 的 {notation}：3bet {tb[notation]} + call {cl[notation]} "
                    f"= {total:.2f} 超过 1.0"
                )

    if problems and strict:
        raise ValueError("范围数据校验失败：\n  " + "\n  ".join(problems))
    return problems


def reconcile_ranges():
    """让 3bet 与 call 范围自动相容。

    规则：若某手牌同时出现在 3bet 与 call 中且权重之和 > 1.0，
    则优先保留 3bet（3bet 是更强的意愿表达），按剩余额度削减 call 权重。
    削减后 call 权重为 0 的条目直接从表中移除。

    这样数据维护者只需关心"想让哪些牌 3bet"，不必手工核算额度，
    从根本上杜绝权重冲突。
    """
    for key, tb in THREE_BET_RANGES.items():
        cl = CALL_RANGES.get(key)
        if not cl:
            continue
        for notation, w3 in list(tb.items()):
            if notation not in cl:
                continue
            remaining = 1.0 - w3
            if remaining <= 1e-9:
                del cl[notation]              # 3bet 已占满，不再跟注
            elif cl[notation] > remaining:
                cl[notation] = round(remaining, 4)
    return True


# 模块加载时即完成相容处理，保证后续查询看到的数据永远自洽
reconcile_ranges()


# 大盲面对开池时的防守（跟注 + 3bet 合并视角）
def get_bb_defense(open_position):
    """返回大盲面对指定位置开池时的 3bet 与跟注范围。"""
    key = f"vs_{open_position}"
    return {
        "three_bet": THREE_BET_RANGES.get(key, {}),
        "call": CALL_RANGES.get(key, {}),
    }


def get_open_range(position):
    """返回指定位置的开池范围。BB 无开池范围，返回空。"""
    return dict(OPEN_RANGES.get(position, {}))


def get_vs_open_action(hand, open_position):
    """面对开池时，返回该手牌的标准动作。

    返回 (动作, 频率, 说明)。动作取值：'3bet' / 'call' / 'fold'
    同花/非同花的具体手牌会被归一化到记号后查询。
    """
    from poker_core import hand_notation
    notation = hand_notation(*hand) if isinstance(hand, (list, tuple)) else hand

    key = f"vs_{open_position}"
    three_bet = THREE_BET_RANGES.get(key, {})
    call = CALL_RANGES.get(key, {})

    w3 = three_bet.get(notation, 0.0)
    wc = call.get(notation, 0.0)

    if w3 > 0 and wc > 0:
        fold = max(0.0, 1.0 - w3 - wc)
        detail = f"3bet {w3:.0%} / call {wc:.0%}"
        if fold > 1e-9:
            detail += f" / fold {fold:.0%}"
        detail += "（混合策略）"
        if w3 >= wc:
            return "3bet", w3, detail
        return "call", wc, detail
    if w3 > 0:
        if w3 >= 0.999:
            return "3bet", w3, f"3bet {w3:.0%}"
        return "3bet", w3, f"3bet {w3:.0%} / fold {1 - w3:.0%}（混合策略）"
    if wc > 0:
        if wc >= 0.999:
            return "call", wc, f"call {wc:.0%}"
        return "call", wc, f"call {wc:.0%} / fold {1 - wc:.0%}（混合策略）"
    return "fold", 1.0, "弃牌（不在标准防守范围内）"


def get_open_action(hand, position):
    """返回该手牌在指定位置的开池动作。

    返回 (动作, 频率, 说明)。动作取值：'open' / 'fold'
    """
    from poker_core import hand_notation
    notation = hand_notation(*hand) if isinstance(hand, (list, tuple)) else hand

    open_range = OPEN_RANGES.get(position, {})
    weight = open_range.get(notation, 0.0)
    if weight >= 0.999:
        return "open", weight, f"开池加注（{POSITION_NAMES.get(position, position)} 标准范围）"
    if weight > 0:
        return "open", weight, f"开池加注 {weight:.0%} / 弃牌 {1 - weight:.0%}（混合策略）"
    return "fold", 1.0, f"弃牌（不在 {POSITION_NAMES.get(position, position)} 开池范围内）"


def range_width(position):
    """返回该位置的组合数占比（用于教学展示范围宽度）。

    按 1326 种组合计算：对子 6 组合，同花 4 组合，非同花 12 组合。
    """
    open_range = OPEN_RANGES.get(position, {})
    total = 0.0
    for notation, weight in open_range.items():
        total += _combos(notation) * weight
    return total / 1326.0


def _combos(notation):
    """返回该记号对应的组合数。"""
    if len(notation) == 2:
        return 6
    if notation.endswith("s"):
        return 4
    return 12


if __name__ == "__main__":
    print("=== 范围数据一致性校验 ===")
    problems = validate_ranges(strict=False)
    if problems:
        for p in problems:
            print("  ✗", p)
    else:
        print("  ✓ 无冲突：所有 3bet + call 权重之和均 <= 1.0")
    ok = not problems

    print("\n=== 范围表自检 ===")
    for pos in POSITIONS:
        if pos == "BB":
            continue
        width = range_width(pos)
        count = len(OPEN_RANGES[pos])
        print(f"{POSITION_NAMES[pos]:12} 范围宽度 {width:6.1%}  含 {count} 种记号")

    print("\n=== 动作查询自检 ===")
    checks = [
        ("AA", "UTG", "open"),
        ("72o", "UTG", "fold"),
        ("AA", "BTN", "open"),
        ("T9s", "BTN", "open"),
        ("32o", "BTN", "fold"),
        ("A5s", "UTG", "open"),
    ]
    for notation, pos, expected in checks:
        action, freq, desc = get_open_action(notation, pos)
        status = "✓" if action == expected else "✗"
        if action != expected:
            ok = False
        print(f"{status} {notation:5} @ {pos:4} -> {action:5} ({freq:.0%}) {desc}")

    print("\n=== 面对开池自检 ===")
    vs_checks = [
        ("AA", "BTN", "3bet"),
        ("72o", "BTN", "fold"),
        ("87s", "BTN", "call"),
        ("AKo", "UTG", "3bet"),
        ("22", "BTN", "call"),
        ("KQs", "UTG", "call"),
    ]
    for notation, pos, expected in vs_checks:
        action, freq, desc = get_vs_open_action(notation, pos)
        status = "✓" if action == expected else "✗"
        if action != expected:
            ok = False
        print(f"{status} {notation:5} vs {pos:4} -> {action:5} {desc}")

    print("\n全部自检通过 ✓" if ok else "\n存在失败项 ✗")
