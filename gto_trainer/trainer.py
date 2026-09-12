# -*- coding: utf-8 -*-
"""训练器核心：出题、判分、讲解。

题库覆盖三个训练模块：
  1. 翻前开池（给定位置与手牌，问应该 open 还是 fold）
  2. 翻前应对开池（给定位置、手牌、对手开池位，问 3bet / call / fold）
  3. 翻后决策（给定手牌、公共牌、位置，问下注策略）

每个题目返回统一结构，便于界面渲染与统计。
"""

import random
from dataclasses import dataclass, field

import ranges
from poker_core import (
    make_deck, hand_notation, hand_to_string, evaluate_best,
    categorize, describe_score, CAT_PAIR, CAT_TWO_PAIR, CAT_TRIPS,
    CAT_STRAIGHT, CAT_FLUSH, CAT_FULL_HOUSE, CAT_QUADS, CAT_STRAIGHT_FLUSH,
    RANK_VALUE, RANKS,
)

# 动作枚举
ACTION_OPEN = "open"
ACTION_FOLD = "fold"
ACTION_3BET = "3bet"
ACTION_CALL = "call"
ACTION_CHECK = "check"
ACTION_BET_SMALL = "bet_small"
ACTION_BET_BIG = "bet_big"

ACTION_LABELS = {
    ACTION_OPEN: "开池加注",
    ACTION_FOLD: "弃牌",
    ACTION_3BET: "3-Bet",
    ACTION_CALL: "跟注",
    ACTION_CHECK: "过牌",
    ACTION_BET_SMALL: "小注（约 1/3 池）",
    ACTION_BET_BIG: "大注（约 3/4 池）",
}


@dataclass
class Question:
    """一道训练题。"""
    module: str                       # preflop_open / preflop_vs_open / postflop
    prompt: str                       # 题干描述
    options: list                     # 可选动作 [(动作值, 显示名), ...]
    correct_action: str               # 正确答案动作值
    correct_freq: float               # 正确动作的频率
    explanation: str                  # 讲解
    hand_cards: list = field(default_factory=list)   # 具体手牌
    board_cards: list = field(default_factory=list)  # 公共牌
    position: str = ""                # 我方位置
    extra: dict = field(default_factory=dict)        # 附加信息（对手位置等）


# ---------------------------------------------------------------- 翻前开池
OPEN_POSITIONS = ["UTG", "HJ", "CO", "BTN", "SB"]


def gen_preflop_open(rng=None):
    """生成一道翻前开池题。"""
    rng = rng or random.Random()
    position = rng.choice(OPEN_POSITIONS)

    # 出题策略：一半概率出"边缘牌"（最容易答错的区域），
    # 一半概率完全随机，保证训练覆盖面
    if rng.random() < 0.6:
        notation = _sample_interesting_notation(position, rng)
    else:
        notation = rng.choice(_all_notations())

    cards = _notation_to_cards(notation, rng)
    action, freq, desc = ranges.get_open_action(notation, position)

    prompt = (
        f"你在 {ranges.POSITION_NAMES[position]}，手牌 {hand_to_string(cards)}"
        f"（{notation}），前面的人都弃牌。\n你应该怎么做？"
    )

    if action == ACTION_OPEN:
        explanation = (
            f"{notation} 属于 {ranges.POSITION_NAMES[position]} 的开池范围（{desc}）。\n\n"
            f"该位置标准开池范围宽度约 {ranges.range_width(position):.1%}。"
            f"在这个位置用这手牌加注入池能直接拿下盲注，同时在被跟注后也有可玩性。"
        )
    else:
        explanation = (
            f"{notation} 不在 {ranges.POSITION_NAMES[position]} 的开池范围内，应当弃牌。\n\n"
            f"位置越靠前，后面未行动的玩家越多，被更强的牌统治（dominated）的风险越大，"
            f"因此范围必须收紧。该位置标准开池范围宽度约 {ranges.range_width(position):.1%}。"
        )

    return Question(
        module="preflop_open",
        prompt=prompt,
        options=[(ACTION_OPEN, ACTION_LABELS[ACTION_OPEN]),
                 (ACTION_FOLD, ACTION_LABELS[ACTION_FOLD])],
        correct_action=action,
        correct_freq=freq,
        explanation=explanation,
        hand_cards=cards,
        position=position,
    )


# ---------------------------------------------------------------- 翻前应对开池
def gen_preflop_vs_open(rng=None):
    """生成一道"面对开池如何应对"的题。"""
    rng = rng or random.Random()
    opener = rng.choice(["UTG", "HJ", "CO", "BTN", "SB"])

    # 我方位置必须在开池者之后
    order = ["UTG", "HJ", "CO", "BTN", "SB", "BB"]
    candidates = order[order.index(opener) + 1:]
    if not candidates:
        return gen_preflop_open(rng)
    hero = rng.choice(candidates)

    notation = _sample_interesting_notation(f"vs_{opener}", rng)
    cards = _notation_to_cards(notation, rng)
    action, freq, desc = ranges.get_vs_open_action(notation, opener)

    hero_name = ranges.POSITION_NAMES.get(hero, hero)
    opener_name = ranges.POSITION_NAMES[opener]

    prompt = (
        f"{opener_name} 开池加注，其他人都弃牌。\n"
        f"你在 {hero_name}，手牌 {hand_to_string(cards)}（{notation}）。\n你应该怎么做？"
    )

    if action == ACTION_3BET:
        explanation = (
            f"面对 {opener_name} 的开池，{notation} 应当 3-Bet（{desc}）。\n\n"
            f"3-Bet 的价值在于：① 用强牌做大底池；② 不给后位玩家便宜的跟注机会；"
            f"③ 迫使开池者放弃其范围中的弱牌。\n"
            f"注意 A5s-A2s 这类牌常被用作 3-Bet 诈唬——它们有 A 阻断对手的 AA/AK，"
            f"同时有同花和轮子顺的潜力。"
        )
    elif action == ACTION_CALL:
        explanation = (
            f"面对 {opener_name} 的开池，{notation} 应当跟注（{desc}）。\n\n"
            f"跟注与 3-Bet 的分工：弱于 3-Bet 范围、但强于弃牌线的牌用于跟注。"
            f"这类牌适合看翻牌，但直接 3-Bet 会赶走对手更弱的牌、只被更强的牌跟注。"
        )
    else:
        explanation = (
            f"{notation} 不在对抗 {opener_name} 开池的防守范围内，应当弃牌。\n\n"
            f"对抗靠前位置的开池要格外谨慎：对手范围本就偏强，"
            f"用边缘牌跟注会陷入被统治（dominated）的困境——"
            f"翻牌后即使击中也被压制。"
        )

    return Question(
        module="preflop_vs_open",
        prompt=prompt,
        options=[
            (ACTION_3BET, ACTION_LABELS[ACTION_3BET]),
            (ACTION_CALL, ACTION_LABELS[ACTION_CALL]),
            (ACTION_FOLD, ACTION_LABELS[ACTION_FOLD]),
        ],
        correct_action=action,
        correct_freq=freq,
        explanation=explanation,
        hand_cards=cards,
        position=hero,
        extra={"opener": opener},
    )


# ---------------------------------------------------------------- 翻后决策
POSTFLOP_SCENARIOS = [
    # (场景名, 公共牌数量, 说明)
    ("flop", 3, "翻牌"),
    ("turn", 4, "转牌"),
    ("river", 5, "河牌"),
]


def gen_postflop(rng=None):
    """生成一道翻后决策题。

    使用简化的启发式规则判断下注策略：
      - 牌力越强，越倾向大注
      - 听牌（同花/顺子听）倾向半诈唬
      - 空气牌视牌面纹理决定是否持续下注
    """
    rng = rng or random.Random()
    deck = make_deck()

    hero = rng.choice(["UTG", "HJ", "CO", "BTN"])
    opponit = "BB"

    # 给英雄发一手"合理"的牌（避免完全随机导致大量垃圾牌）
    notation = _sample_playable_notation(rng)
    hero_cards = _notation_to_cards(notation, rng)

    # 生成公共牌
    remaining = [c for c in deck if c not in hero_cards]
    board_size = rng.choice([3, 3, 3, 4, 5])   # 翻牌为主
    board = rng.sample(remaining, board_size)

    strength, made_category, draw_info = _assess_postflop(hero_cards, board)
    action, reasoning = _decide_postflop(
        strength, made_category, draw_info, board, board_size, rng
    )

    street = {3: "翻牌", 4: "转牌", 5: "河牌"}[board_size]
    cat_name = describe_score(evaluate_best(hero_cards + board)[0])[0]

    prompt = (
        f"你在 {ranges.POSITION_NAMES.get(hero, hero)}，手牌 {hand_to_string(hero_cards)}"
        f"（{notation}）。\n"
        f"{street}：{hand_to_string(board)}\n"
        f"你面对大盲位，单挑底池。你率先行动，应该怎么做？"
    )

    explanation = (
        f"牌力评估：你的最佳牌型是【{cat_name}】"
        f"{'，' + draw_info if draw_info else ''}。\n\n"
        f"{reasoning}\n\n"
        f"翻后决策的核心是权衡：① 价值——能获得多少更差牌的跟注；"
        f"② 保护——需要阻止对手免费看到下一张吗；"
        f"③ 弃牌率——对手在不击中时会不会弃牌。"
    )

    return Question(
        module="postflop",
        prompt=prompt,
        options=[
            (ACTION_CHECK, ACTION_LABELS[ACTION_CHECK]),
            (ACTION_BET_SMALL, ACTION_LABELS[ACTION_BET_SMALL]),
            (ACTION_BET_BIG, ACTION_LABELS[ACTION_BET_BIG]),
        ],
        correct_action=action,
        correct_freq=1.0,
        explanation=explanation,
        hand_cards=hero_cards,
        board_cards=board,
        position=hero,
        extra={"strength": strength, "category": made_category},
    )


def _assess_postflop(hero_cards, board):
    """评估翻后牌力，返回 (强度分类, 牌型类别, 听牌描述)。"""
    all_cards = hero_cards + board
    score, _ = evaluate_best(all_cards)
    category = categorize(score)

    # 听牌检测
    draw_parts = []
    draw_strength = 0.0
    if len(board) < 5:
        from itertools import combinations
        from poker_core import _straight_high
        # 同花听牌
        suit_counts = {}
        for c in all_cards:
            suit_counts[c[1]] = suit_counts.get(c[1], 0) + 1
        if max(suit_counts.values()) == 4:
            draw_parts.append("同花听牌")
            draw_strength += 0.5
        # 顺子听牌（简判：5 张里已经有 4 张连牌）
        vset = sorted({RANK_VALUE[c[0]] for c in all_cards})
        best_run = 1
        run = 1
        for i in range(1, len(vset)):
            if vset[i] - vset[i - 1] == 1:
                run += 1
                best_run = max(best_run, run)
            else:
                run = 1
        if best_run == 4:
            draw_parts.append("顺子听牌")
            draw_strength += 0.4

    if category >= CAT_STRAIGHT:
        strength = "很强"
    elif category in (CAT_TRIPS, CAT_TWO_PAIR, CAT_FULL_HOUSE,
                      CAT_QUADS, CAT_STRAIGHT_FLUSH):
        strength = "强"
    elif category == CAT_PAIR:
        # 判断成对的是哪张牌，以及它相对公共牌的位置
        board_ranks = [RANK_VALUE[c[0]] for c in board]
        hero_ranks = [RANK_VALUE[c[0]] for c in hero_cards]
        top_board = max(board_ranks)

        # 手中的对子点数：与公共牌点数相同的那些手牌点数
        paired_hero = [r for r in hero_ranks if r in board_ranks]
        if paired_hero:
            pair_rank = max(paired_hero)
            if pair_rank == top_board:
                strength = "中强（顶对）"
            elif board_ranks.count(pair_rank) >= 1 and \
                    pair_rank > sorted(board_ranks)[len(board_ranks) // 2]:
                strength = "中（中对）"
            else:
                strength = "中弱（底对）"
        else:
            # 手牌本身成对（口袋对子），且大于公共牌
            pair_rank = hero_ranks[0]
            if pair_rank > top_board:
                strength = "中强（超对）"
            else:
                strength = "中弱（小口袋对）"
    else:
        strength = "弱（高牌）"

    if draw_parts:
        draw_info = "、".join(draw_parts)
    else:
        draw_info = ""

    return strength, category, draw_info


def _decide_postflop(strength, category, draw_info, board, board_size, rng):
    """根据牌力启发式决定下注动作。"""
    board_ranks = [RANK_VALUE[c[0]] for c in board]
    board_high = max(board_ranks)

    if "很强" in strength or "强" in strength and category >= CAT_TWO_PAIR:
        return ACTION_BET_BIG, (
            f"你持有【{strength}】的成牌，应当下大注（约 3/4 池）建立价值。\n"
            f"下大注的理由：对手范围中仍有大量更差的成牌和听牌会跟注，"
            f"此时做大底池能最大化期望收益。慢玩会损失价值。"
        )

    if draw_info and strength in ("弱（高牌）", "中弱（底对）"):
        return ACTION_BET_SMALL, (
            f"你持有【{strength}】配 {draw_info}，适合用半诈唬小注（约 1/3 池）。\n"
            f"半诈唬的好处是双赢：对手弃牌你立刻拿下底池；"
            f"对手跟注你仍有听牌可以反超。小注能以较低成本实现这两条路径。"
        )

    if "顶对" in strength or "中强" in strength:
        if board_high >= RANK_VALUE["Q"] and board_size == 3:
            return ACTION_BET_SMALL, (
                f"你持有【{strength}】，但牌面偏高（{hand_to_string(board)}），"
                f"对手范围中击中两对以上的概率上升。\n"
                f"建议小注（约 1/3 池）：既能从更差的对子获取价值，"
                f"又能在被加注时以较低成本脱身。"
            )
        return ACTION_BET_BIG, (
            f"你持有【{strength}】，牌面对你有利，应当下大注（约 3/4 池）。\n"
            f"顶对在多数牌面都是价值牌，需要从对手的中对、底对、听牌中榨取价值。"
        )

    return ACTION_CHECK, (
        f"你持有【{strength}】{'、' + draw_info if draw_info else ''}，"
        f"此时过牌是更好的选择。\n"
        f"用弱牌下注如果被跟注或加注，你将陷入被动；"
        f"过牌可以控制底池大小，并保留听牌免费看下一张的机会。"
    )


# ---------------------------------------------------------------- 辅助函数
def _all_notations():
    from poker_core import all_hand_notations
    return all_hand_notations()


def _sample_interesting_notation(position, rng):
    """采样"边缘牌"——范围边界附近的牌最容易答错，训练价值最高。

    position 可以是位置名（UTG 等）或 "vs_XXX"。
    """
    if position.startswith("vs_"):
        key = position
        pool = set(ranges.THREE_BET_RANGES.get(key, {})) | \
            set(ranges.CALL_RANGES.get(key, {}))
        pool = list(pool)
        if not pool:
            return rng.choice(_all_notations())
        # 70% 从范围边缘采样，30% 从范围外采样（练"该弃牌"的判断）
        if rng.random() < 0.7:
            return rng.choice(pool)
        outside = [n for n in _all_notations() if n not in pool]
        # 取范围外但排名较靠前的牌（最容易被误用）
        return rng.choice(outside[:60])

    rng_table = ranges.OPEN_RANGES.get(position, {})
    pool = list(rng_table)
    if not pool:
        return rng.choice(_all_notations())
    if rng.random() < 0.7:
        return rng.choice(pool)
    outside = [n for n in _all_notations() if n not in rng_table]
    return rng.choice(outside[:60])


def _sample_playable_notation(rng):
    """采样一手有一定可玩性的牌，避免翻后题目全是垃圾牌。"""
    pool = [
        "AA", "KK", "QQ", "JJ", "TT", "99", "88", "77", "66", "55", "44", "33", "22",
        "AKs", "AQs", "AJs", "ATs", "A9s", "A5s", "A4s", "A3s", "A2s",
        "KQs", "KJs", "KTs", "QJs", "QTs", "JTs", "T9s", "98s", "87s", "76s", "65s",
        "AKo", "AQo", "AJo", "ATo", "KQo", "KJo", "QJo",
    ]
    notation = rng.choice(pool)
    return notation


def _notation_to_cards(notation, rng):
    """把起手牌记号转换为两张具体牌。"""
    deck = make_deck()
    if len(notation) == 2:                # 对子
        rank = notation[0]
        suits = rng.sample(list("shdc"), 2)
        return [f"{rank}{suits[0]}", f"{rank}{suits[1]}"]

    high, low, suffix = notation[0], notation[1], notation[2]
    if suffix == "s":
        suit = rng.choice(list("shdc"))
        # 顺序随机化，避免总是大牌在前（实则无影响，但更自然）
        cards = [f"{high}{suit}", f"{low}{suit}"]
    else:
        suits = rng.sample(list("shdc"), 2)
        cards = [f"{high}{suits[0]}", f"{low}{suits[1]}"]
    if rng.random() < 0.5:
        cards.reverse()
    return cards


def generate_question(module="mixed", rng=None):
    """按模块生成题目。

    module 取值：preflop_open / preflop_vs_open / postflop / mixed
    """
    rng = rng or random.Random()
    if module == "mixed":
        module = rng.choice(["preflop_open", "preflop_vs_open", "postflop",
                             "preflop_open", "preflop_vs_open"])

    if module == "preflop_open":
        return gen_preflop_open(rng)
    if module == "preflop_vs_open":
        return gen_preflop_vs_open(rng)
    if module == "postflop":
        return gen_postflop(rng)
    raise ValueError(f"未知模块：{module}")


if __name__ == "__main__":
    print("=== 出题引擎自检 ===\n")
    rng = random.Random(42)
    ok = True

    for module in ["preflop_open", "preflop_vs_open", "postflop"]:
        print(f"--- {module} ---")
        for _ in range(3):
            q = generate_question(module, rng)
            print(f"  [{q.module}] {q.prompt.splitlines()[0][:52]}…")
            print(f"    手牌={q.hand_cards} 公共牌={q.board_cards or '无'} "
                  f"位置={q.position}")
            print(f"    正确动作={ACTION_LABELS[q.correct_action]} "
                  f"(频率 {q.correct_freq:.0%})")
            assert q.correct_action in dict(q.options), "正确答案必须在选项内"
            assert q.explanation.strip(), "讲解不能为空"
        print()

    # 批量生成测试稳定性
    print("--- 批量生成 300 题稳定性测试 ---")
    counts = {}
    for _ in range(300):
        q = generate_question("mixed", rng)
        counts[q.module] = counts.get(q.module, 0) + 1
        assert q.correct_action in dict(q.options)
    print(f"  模块分布：{counts}")
    print("  ✓ 300 题全部生成成功，答案均在选项内")

    # 检查已知答案正确性
    print("\n--- 答案正确性抽查 ---")
    checks = [
        ("preflop_open", "AA", "UTG", ACTION_OPEN),
        ("preflop_open", "72o", "UTG", ACTION_FOLD),
    ]
    for module, notation, pos, expected in checks:
        action, freq, desc = ranges.get_open_action(notation, pos)
        status = "✓" if action == expected else "✗"
        if action != expected:
            ok = False
        print(f"  {status} {notation} @ {pos} -> {action}（期望 {expected}）")

    print("\n全部自检通过 ✓" if ok else "\n存在失败项 ✗")
