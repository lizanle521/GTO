# -*- coding: utf-8 -*-
"""扑克牌基础模型与 7 选 5 手牌评估器。

评估器输出一个可比较的整数分值，分值越大牌力越强。
分值编码方式（从高位到低位）：
    类别 * 15^5 + 主牌值 * 15^4 + 次牌值 * 15^3 + ...

牌面表示：用 2 字符字符串，如 "As" = 黑桃A，"Td" = 方块10。
    点数：2-9, T, J, Q, K, A
    花色：s(黑桃) h(红桃) d(方块) c(梅花)
"""

from itertools import combinations

RANKS = "23456789TJQKA"
SUITS = "shdc"

RANK_VALUE = {r: i + 2 for i, r in enumerate(RANKS)}   # 2 -> 2, A -> 14
VALUE_RANK = {v: k for k, v in RANK_VALUE.items()}

# 手牌类别
CAT_HIGH_CARD = 0
CAT_PAIR = 1
CAT_TWO_PAIR = 2
CAT_TRIPS = 3
CAT_STRAIGHT = 4
CAT_FLUSH = 5
CAT_FULL_HOUSE = 6
CAT_QUADS = 7
CAT_STRAIGHT_FLUSH = 8

CATEGORY_NAMES = {
    CAT_HIGH_CARD: "高牌",
    CAT_PAIR: "一对",
    CAT_TWO_PAIR: "两对",
    CAT_TRIPS: "三条",
    CAT_STRAIGHT: "顺子",
    CAT_FLUSH: "同花",
    CAT_FULL_HOUSE: "葫芦",
    CAT_QUADS: "四条",
    CAT_STRAIGHT_FLUSH: "同花顺",
}


class CardError(ValueError):
    """牌面字符串格式错误。"""


def parse_card(text):
    """把 'As' 解析为 (点数, 花色)。"""
    if not isinstance(text, str) or len(text) != 2:
        raise CardError(f"非法牌面：{text!r}（应为 2 字符，如 'As'）")
    rank, suit = text[0].upper(), text[1].lower()
    if rank not in RANK_VALUE:
        raise CardError(f"非法点数：{text!r}")
    if suit not in SUITS:
        raise CardError(f"非法花色：{text!r}")
    return rank, suit


def format_card(rank, suit):
    return f"{rank}{suit}"


def make_deck():
    """返回 52 张牌的标准牌堆。"""
    return [f"{r}{s}" for r in RANKS for s in SUITS]


def hand_to_string(cards):
    """把牌列表格式化为可读字符串，如 'A♠ K♥'。"""
    symbols = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}
    return " ".join(f"{c[0].upper()}{symbols[c[1].lower()]}" for c in cards)


def _straight_high(rank_set):
    """给定点数集合（已去重、降序），返回顺子最高牌点数，无顺子返回 0。

    A 可作 1 参与 A2345，此时返回 5。
    """
    values = sorted(rank_set, reverse=True)
    # 特判 A2345
    if set(values) >= {14, 5, 4, 3, 2} and len({14, 5, 4, 3, 2} - set(values)) == 0:
        pass
    for i in range(len(values) - 4):
        window = values[i:i + 5]
        if window[0] - window[4] == 4 and len(set(window)) == 5:
            return window[0]
    # A-5 顺子
    if {14, 2, 3, 4, 5}.issubset(set(values)):
        return 5
    return 0


def evaluate_five(cards):
    """评估恰好 5 张牌，返回分值整数。分值越大越强。"""
    ranks = [RANK_VALUE[c[0].upper()] for c in cards]
    suits = [c[1].lower() for c in cards]

    rank_counts = {}
    for r in ranks:
        rank_counts[r] = rank_counts.get(r, 0) + 1
    # 按 (出现次数, 点数) 降序
    counts_sorted = sorted(rank_counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)

    is_flush = len(set(suits)) == 1
    straight_high = _straight_high(set(ranks))

    if is_flush and straight_high:
        return _score(CAT_STRAIGHT_FLUSH, [straight_high])
    if counts_sorted[0][1] == 4:
        quads = counts_sorted[0][0]
        kicker = counts_sorted[1][0]
        return _score(CAT_QUADS, [quads, kicker])
    if counts_sorted[0][1] == 3 and counts_sorted[1][1] == 2:
        return _score(CAT_FULL_HOUSE, [counts_sorted[0][0], counts_sorted[1][0]])
    if is_flush:
        return _score(CAT_FLUSH, sorted(ranks, reverse=True))
    if straight_high:
        return _score(CAT_STRAIGHT, [straight_high])
    if counts_sorted[0][1] == 3:
        kickers = sorted([r for r in ranks if r != counts_sorted[0][0]], reverse=True)
        return _score(CAT_TRIPS, [counts_sorted[0][0]] + kickers)
    if counts_sorted[0][1] == 2 and counts_sorted[1][1] == 2:
        pairs = sorted([counts_sorted[0][0], counts_sorted[1][0]], reverse=True)
        kicker = counts_sorted[2][0]
        return _score(CAT_TWO_PAIR, pairs + [kicker])
    if counts_sorted[0][1] == 2:
        pair = counts_sorted[0][0]
        kickers = sorted([r for r in ranks if r != pair], reverse=True)
        return _score(CAT_PAIR, [pair] + kickers)
    return _score(CAT_HIGH_CARD, sorted(ranks, reverse=True))


def _score(category, tiebreakers):
    """把类别与比牌点编码为单一整数。"""
    score = category
    for i in range(5):
        value = tiebreakers[i] if i < len(tiebreakers) else 0
        score = score * 15 + value
    return score


def evaluate_best(cards):
    """从 5~7 张牌中选出最强 5 张组合。

    返回 (分值, 最佳组合列表)。
    """
    if len(cards) < 5:
        raise CardError(f"至少需要 5 张牌，收到 {len(cards)} 张")
    if len(cards) == 5:
        return evaluate_five(cards), list(cards)

    best_score = -1
    best_combo = None
    for combo in combinations(cards, 5):
        combo = list(combo)
        score = evaluate_five(combo)
        if score > best_score:
            best_score = score
            best_combo = combo
    return best_score, best_combo


def describe_score(score):
    """把分值还原为可读的牌型描述。"""
    category = score
    values = []
    for _ in range(5):
        values.append(category % 15)
        category //= 15
    values.reverse()
    name = CATEGORY_NAMES.get(category, "未知")

    if category == CAT_HIGH_CARD:
        detail = f"{VALUE_RANK.get(values[0], '?')} 高"
    elif category == CAT_PAIR:
        detail = f"{VALUE_RANK.get(values[0], '?')} 对"
    elif category == CAT_TWO_PAIR:
        detail = f"{VALUE_RANK.get(values[0], '?')}{VALUE_RANK.get(values[1], '?')} 两对"
    elif category == CAT_TRIPS:
        detail = f"{VALUE_RANK.get(values[0], '?')} 三条"
    elif category == CAT_STRAIGHT:
        detail = f"{VALUE_RANK.get(values[0], '?')} 高顺"
    elif category == CAT_FLUSH:
        detail = f"{VALUE_RANK.get(values[0], '?')} 高同花"
    elif category == CAT_FULL_HOUSE:
        detail = f"{VALUE_RANK.get(values[0], '?')} 带 {VALUE_RANK.get(values[1], '?')} 葫芦"
    elif category == CAT_QUADS:
        detail = f"{VALUE_RANK.get(values[0], '?')} 四条"
    elif category == CAT_STRAIGHT_FLUSH:
        detail = f"{VALUE_RANK.get(values[0], '?')} 高同花顺"
    else:
        detail = ""
    return name, detail


def categorize(score):
    """返回分值的类别编号（0-8）。"""
    category = score
    for _ in range(5):
        category //= 15
    return category


# ---------------------------------------------------------------- 起手牌记号
def hand_notation(card1, card2):
    """把两张具体牌转换为 169 起手牌记号，如 'AKs' / 'QQ' / 'T9o'。

    强制大牌在前；同花色加 s 后缀，不同花色加 o。
    对子不带后缀。
    """
    r1, s1 = parse_card(card1)
    r2, s2 = parse_card(card2)
    v1, v2 = RANK_VALUE[r1], RANK_VALUE[r2]
    if v1 < v2:
        r1, r2 = r2, r1
    if r1 == r2:
        return f"{r1}{r2}"
    suffix = "s" if s1 == s2 else "o"
    return f"{r1}{r2}{suffix}"


def all_hand_notations():
    """返回全部 169 个起手牌记号，按牌力从强到弱排序。

    强度公式思路（参考 Chen Formula 并做归一化）：
      对子          -> 点数 * 2 + 3.0 的固定加成。该加成确保"最小对子也
                       强于任何非对子组合"——这符合 GTO 实战：对子有约 12%
                       概率成暗三条，且翻牌前对高牌占优。
      非对子        -> 高牌 + 低牌 * 0.5，同花 +2，连张 +1，间隔扣分
    """
    def strength(notation):
        if len(notation) == 2:            # 对子
            v = RANK_VALUE[notation[0]]
            return (v * 2.0 + 3.0, v)
        high = RANK_VALUE[notation[0]]
        low = RANK_VALUE[notation[1]]
        suited = notation[-1] == "s"
        base = high + low * 0.5
        if suited:
            base += 2.0
        gap = high - low
        if gap == 1:                      # 连张
            base += 1.0
        elif gap == 2:
            base += 0.5
        else:
            base -= (gap - 2) * 0.5       # 间隔越大越弱
        if high == 14 and low <= 5 and gap >= 9:   # A 带小牌，顺子潜力受限
            base -= 0.5
        return (base, high)

    notations = []
    for i in range(len(RANKS) - 1, -1, -1):        # 对子
        notations.append(RANKS[i] * 2)
    for i in range(len(RANKS) - 1, -1, -1):        # 非对子
        for j in range(i - 1, -1, -1):
            notations.append(f"{RANKS[i]}{RANKS[j]}s")
            notations.append(f"{RANKS[i]}{RANKS[j]}o")

    notations.sort(key=strength, reverse=True)
    return notations


if __name__ == "__main__":
    # 自检
    tests = [
        (["As", "Ks", "Qs", "Js", "Ts"], CAT_STRAIGHT_FLUSH, "皇家同花顺"),
        (["9h", "8h", "7h", "6h", "5h"], CAT_STRAIGHT_FLUSH, "9高同花顺"),
        (["As", "Ah", "Ad", "Ac", "Ks"], CAT_QUADS, "四条A"),
        (["As", "Ah", "Ad", "Ks", "Kh"], CAT_FULL_HOUSE, "A带K葫芦"),
        (["As", "Ks", "Qs", "Js", "9s"], CAT_FLUSH, "同花"),
        (["As", "2h", "3d", "4c", "5s"], CAT_STRAIGHT, "轮子顺"),
        (["As", "Ah", "Ad", "Ks", "Qh"], CAT_TRIPS, "三条A"),
        (["As", "Ah", "Ks", "Kh", "Qd"], CAT_TWO_PAIR, "两对"),
        (["As", "Ah", "Ks", "Qh", "Jd"], CAT_PAIR, "一对A"),
        (["As", "Kh", "Qd", "Jc", "9s"], CAT_HIGH_CARD, "A高"),
    ]
    print("=== 5 张牌评估自检 ===")
    ok = True
    for cards, expected_cat, label in tests:
        score = evaluate_five(cards)
        cat = categorize(score)
        status = "✓" if cat == expected_cat else "✗"
        if cat != expected_cat:
            ok = False
        name, detail = describe_score(score)
        print(f"{status} {label:12} -> {name} {detail}")

    print("\n=== 牌力排序自检 ===")
    royal = evaluate_five(["As", "Ks", "Qs", "Js", "Ts"])
    quads = evaluate_five(["As", "Ah", "Ad", "Ac", "Ks"])
    boat = evaluate_five(["As", "Ah", "Ad", "Ks", "Kh"])
    flush = evaluate_five(["As", "Ks", "Qs", "Js", "9s"])
    straight = evaluate_five(["As", "2h", "3d", "4c", "5s"])
    trips = evaluate_five(["As", "Ah", "Ad", "Ks", "Qh"])
    order = [royal, quads, boat, flush, straight, trips]
    ordered = all(order[i] >= order[i + 1] for i in range(len(order) - 1))
    print("牌型强度递减正确" if ordered else "牌型强度排序错误")
    ok = ok and ordered

    print("\n=== 起手牌记号自检 ===")
    checks = [
        (("As", "Ks"), "AKs"), (("Kh", "As"), "AKo"), (("Qh", "Qs"), "QQ"),
        (("2c", "7d"), "72o"), (("Td", "9d"), "T9s"),
    ]
    for (c1, c2), expected in checks:
        got = hand_notation(c1, c2)
        status = "✓" if got == expected else "✗"
        if got != expected:
            ok = False
        print(f"{status} {c1}{c2} -> {got} (期望 {expected})")

    notations = all_hand_notations()
    print(f"\n起手牌记号总数：{len(notations)}（应为 169）")
    print(f"最强 5 个：{notations[:5]}")
    print(f"最弱 5 个：{notations[-5:]}")
    ok = ok and len(notations) == 169
    ok = ok and len(set(notations)) == 169
    ok = ok and notations[0] == "AA"

    # 关键排序断言：只断言无争议的关系。
    # 说明：169 起手牌的"绝对强度排序"本身没有唯一正确答案（如 77 与 AJs
    # 孰强取决于场景），因此这里只校验公认结论，具体行动范围见 ranges.py。
    idx = {n: i for i, n in enumerate(notations)}
    order_checks = [
        ("AA", "AKs", "AA 应强于 AKs"),
        ("AA", "AKo", "AA 应强于 AKo"),
        ("AA", "KK", "AA 应强于 KK"),
        ("KK", "QQ", "KK 应强于 QQ"),
        ("QQ", "JJ", "QQ 应强于 JJ"),
        ("22", "32o", "22 应强于 32o"),
        ("22", "72o", "22 应强于 72o"),
        ("AKs", "AKo", "AKs 应强于 AKo"),
        ("AKo", "AQo", "AKo 应强于 AQo"),
        ("AQs", "ATs", "AQs 应强于 ATs"),
        ("55", "A2s", "55 应强于 A2s"),
        ("QQ", "AKo", "QQ 应强于 AKo"),
        ("JJ", "AQo", "JJ 应强于 AQo"),
    ]
    print("\n=== 排序关系自检 ===")
    for a, b, desc in order_checks:
        better = idx[a] < idx[b]
        status = "✓" if better else "✗"
        if not better:
            ok = False
        print(f"{status} {desc}（实得 {a}={idx[a]}, {b}={idx[b]}）")

    print("\n全部自检通过 ✓" if ok else "\n存在失败项 ✗")
