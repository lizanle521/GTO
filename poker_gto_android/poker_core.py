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


# ---------------------------------------------------------------- 胜率估算
def estimate_equity(hole, board, num_opponents=1, iterations=600, seed=None):
    """用蒙特卡洛模拟估算当前牌力的胜率。

    参数:
        hole: 自己的 2 张手牌，如 ["As", "Kh"]
        board: 公共牌，0-5 张
        num_opponents: 假设的对手数量
        iterations: 模拟次数。越大越准也越慢
        seed: 固定随机种子，用于测试时复现结果

    返回:
        (胜率, 平局率)，均为 0.0-1.0；胜率不含平局。

    关于「对手随机」这件事必须说清楚：这里的对手拿到的是**任意两张牌**，
    不是 GTO 意义上的对手范围。所以这个数字的含义是「对随机范围的胜率」,
    它是一个乐观的参考值（真实对手的范围通常比随机更强），
    不能直接当成 GTO 权益来用。界面文案里要标明这一点。

    性能：每次迭代要评估 (1 + num_opponents) 手 7 选 5 的牌。
    600 次在手机上约 0.3-0.8 秒，足够放进后台线程。
    """
    import random

    hole = list(hole)
    board = list(board)
    known = hole + board

    for c in known:
        parse_card(c)                      # 格式不对立刻报错，别拖进模拟循环
    if len(hole) != 2:
        raise CardError(f"手牌应为 2 张，收到 {len(hole)} 张")
    if len(board) > 5:
        raise CardError(f"公共牌最多 5 张，收到 {len(board)} 张")
    if len(set(known)) != len(known):
        raise CardError(f"手牌与公共牌存在重复：{known}")
    if num_opponents < 1:
        raise ValueError("对手数量至少为 1")
    if iterations < 1:
        raise ValueError("模拟次数至少为 1")

    deck = [c for c in make_deck() if c not in known]
    need_board = 5 - len(board)
    draw = need_board + 2 * num_opponents
    if draw > len(deck):
        raise ValueError(f"剩余 {len(deck)} 张牌不足以模拟 {num_opponents} 个对手")

    rng = random.Random(seed)
    wins = ties = 0

    for _ in range(iterations):
        pick = rng.sample(deck, draw)
        extra_board = pick[:need_board]
        opp_pool = pick[need_board:]
        full_board = board + extra_board

        my_score, _ = evaluate_best(hole + full_board)

        # 只要不输给任何一个对手，就算赢或平
        best_opp = -1
        for i in range(num_opponents):
            opp = opp_pool[2 * i: 2 * i + 2]
            score, _ = evaluate_best(opp + full_board)
            if score > best_opp:
                best_opp = score

        if my_score > best_opp:
            wins += 1
        elif my_score == best_opp:
            ties += 1

    return wins / iterations, ties / iterations


def pot_odds(bet_to_call, pot_before_bet):
    """计算底池赔率：需要的最低胜率才能让跟注不亏。

    bet_to_call: 需要跟注的金额
    pot_before_bet: 对手下注**之前**的底池（不含他的下注）

    对手下注后底池变成 pot_before_bet + bet_to_call，你跟注后底池变成
    pot_before_bet + 2 * bet_to_call。因此：
        需要的胜率 = 跟注额 / (底池 + 跟注额)
                   = bet / (pot_before + 2 * bet)
    """
    if bet_to_call <= 0:
        return 0.0
    if pot_before_bet < 0:
        raise ValueError("底池不能为负")
    return bet_to_call / (pot_before_bet + 2.0 * bet_to_call)


def equity_against_range(hole, board, opponent_range, num_opponents=1,
                         iterations=600, seed=None):
    """估算对**指定范围**的胜率（比 estimate_equity 的随机范围更贴近实战）。

    opponent_range: {起手牌记号: 权重}，如 {"AA": 1.0, "AKs": 0.8}。
                    直接用 ranges.expand_range() 的结果即可。
    权重只影响抽样概率，不影响最终计算方式。
    """
    import random

    if not opponent_range:
        return estimate_equity(hole, board, num_opponents, iterations, seed)

    board = list(board)
    hole = list(hole)
    known = set(hole + board)

    # 预先把范围展开成具体两张牌的组合（剔除与已知牌冲突的）
    combos = []
    weights = []
    for notation, weight in opponent_range.items():
        for combo in _notation_combos(notation):
            if any(c in known for c in combo):
                continue
            combos.append(combo)
            weights.append(weight)
    if not combos:
        return estimate_equity(hole, board, num_opponents, iterations, seed)

    rng = random.Random(seed)
    deck = [c for c in make_deck() if c not in known]
    need_board = 5 - len(board)
    wins = ties = done = 0

    for _ in range(iterations):
        # 每个对手重新按权重抽一手牌；抽到与已知牌冲突的就整次作废
        used = set(known)
        opps = []
        ok = True
        for _ in range(num_opponents):
            combo = rng.choices(combos, weights=weights, k=1)[0]
            if any(c in used for c in combo):
                ok = False
                break
            used.update(combo)
            opps.append(combo)
        if not ok:
            continue

        pool = [c for c in deck if c not in used]
        if len(pool) < need_board:
            continue
        full_board = board + rng.sample(pool, need_board)

        my_score, _ = evaluate_best(hole + full_board)
        best_opp = max(evaluate_best(o + full_board)[0] for o in opps)

        done += 1
        if my_score > best_opp:
            wins += 1
        elif my_score == best_opp:
            ties += 1

    # 分母用**实际完成的模拟次数**，不是 iterations。
    # 抽到冲突组合的那些轮次被 continue 跳过了，它们既不算赢也不算输；
    # 若拿 iterations 当分母，胜率会被系统性地压低（对手范围越窄越明显）。
    if done == 0:
        return 0.0, 0.0
    return wins / done, ties / done


def _notation_combos(notation):
    """把一个起手牌记号展开为具体两张牌的组合列表。

    AA -> 6 种；AKs -> 4 种；AKo -> 12 种。
    """
    notation = notation.strip()
    if not notation:
        return []

    suit_pairs = [(s1, s2) for s1 in SUITS for s2 in SUITS]

    if len(notation) == 2:                       # 对子
        r = notation[0].upper()
        return [[f"{r}{a}", f"{r}{b}"] for i, a in enumerate(SUITS)
                for b in SUITS[i + 1:]]

    r1, r2 = notation[0].upper(), notation[1].upper()
    suited = notation[-1].lower() == "s"
    out = []
    for a, b in suit_pairs:
        if a == b and not suited:
            continue
        if a != b and suited:
            continue
        out.append([f"{r1}{a}", f"{r2}{b}"])
    return out



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

    # ---------------------------------------------------------- 胜率估算
    import time as _time

    print("\n=== 胜率估算自检（对照理论值）===")
    t0 = _time.time()
    eq_aa, tie_aa = estimate_equity(["As", "Ah"], [], num_opponents=1,
                                    iterations=600, seed=42)
    dt = _time.time() - t0
    print(f"AA 翻前 vs 1 个随机对手：胜率 {eq_aa:.1%} 平局 {tie_aa:.1%}"
          f"（理论约 85%，600 次耗时 {dt * 1000:.0f} ms）")
    ok = ok and 0.80 <= eq_aa <= 0.90

    eq_aa3, _ = estimate_equity(["As", "Ah"], [], num_opponents=3,
                                iterations=400, seed=42)
    print(f"AA 翻前 vs 3 个随机对手：胜率 {eq_aa3:.1%}（理论约 64%）")
    ok = ok and 0.55 <= eq_aa3 <= 0.72

    eq_72, _ = estimate_equity(["7c", "2d"], [], num_opponents=1,
                               iterations=600, seed=42)
    print(f"72o 翻前 vs 1 个随机对手：胜率 {eq_72:.1%}（实测约 32%）")
    # 注意别拿常被引用的 "72o ≈ 34.6%" 来对：那个数是**含平局折半**的
    # equity（胜率 + 平局率/2），而本函数返回的是纯胜率，平局单独统计。
    # 两者差的那 2 个多点，正是平局率的一半。
    ok = ok and 0.28 <= eq_72 <= 0.36

    # 坚果牌：对手不可能赢，只能是 100%
    eq_nuts, _ = estimate_equity(["As", "Ah"], ["Ad", "Ac", "2s"],
                                 num_opponents=1, iterations=300, seed=42)
    print(f"四条 A 在 A-A-2 牌面：胜率 {eq_nuts:.1%}（应为 100%）")
    ok = ok and eq_nuts >= 0.999

    # 平局必须单独统计，不能算进胜率——这是最容易写错的地方
    eq_royal, tie_royal = estimate_equity(
        ["2c", "3d"], ["As", "Ks", "Qs", "Js", "Ts"],
        num_opponents=1, iterations=200, seed=42)
    print(f"公共牌即皇家同花顺：胜率 {eq_royal:.1%} 平局 {tie_royal:.1%}"
          f"（应全部平局）")
    ok = ok and tie_royal >= 0.999 and eq_royal <= 0.001

    # 参数校验
    for bad_call, label in [
        (lambda: estimate_equity(["As"], [], iterations=10), "手牌只有 1 张"),
        (lambda: estimate_equity(["As", "As"], [], iterations=10), "重复的牌"),
        (lambda: estimate_equity(["As", "Ah"], [], num_opponents=0,
                                 iterations=10), "对手数为 0"),
    ]:
        try:
            bad_call()
            print(f"✗ {label} 应报错")
            ok = False
        except (CardError, ValueError):
            pass
    print("  ✓ 非法参数正确报错（1 张手牌 / 重复牌 / 0 个对手）")

    print("\n=== 底池赔率自检 ===")
    odds_a = pot_odds(50, 100)
    print(f"底池 100、对手下注 50 -> 需要 {odds_a:.1%} 胜率才不亏（应为 25%）")
    ok = ok and abs(odds_a - 0.25) < 1e-9

    odds_b = pot_odds(100, 100)
    print(f"底池 100、对手下注 100 -> 需要 {odds_b:.1%}（应为 33.3%）")
    ok = ok and abs(odds_b - 1 / 3) < 1e-9

    print(f"无人下注 -> {pot_odds(0, 100):.1%}（应为 0%）")
    ok = ok and pot_odds(0, 100) == 0.0

    print("\n=== 对指定范围的胜率自检 ===")
    eq_kk, _ = equity_against_range(["Ks", "Kh"], [], {"AA": 1.0},
                                    num_opponents=1, iterations=400, seed=7)
    print(f"KK 翻前对「只有 AA」的范围：胜率 {eq_kk:.1%}（理论约 18%）")
    ok = ok and 0.10 <= eq_kk <= 0.26

    eq_wide, _ = equity_against_range(
        ["Ks", "Kh"], [], {"AA": 1.0, "QQ": 1.0, "AKs": 0.5},
        num_opponents=1, iterations=400, seed=7)
    print(f"KK 对「AA+QQ+部分 AKs」：胜率 {eq_wide:.1%}（应明显高于只对 AA）")
    ok = ok and eq_wide > eq_kk

    print("\n全部自检通过 ✓" if ok else "\n存在失败项 ✗")
