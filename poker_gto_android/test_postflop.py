# -*- coding: utf-8 -*-
"""翻后分析单元测试（听牌识别与建议生成）。

运行：python test_postflop.py
"""

import os
import sys

os.environ["KIVY_NO_ARGS"] = "1"
os.environ["KIVY_LOG_LEVEL"] = "error"

from kivy.config import Config
Config.set("graphics", "width", "100")
Config.set("graphics", "height", "100")
Config.set("graphics", "window_state", "hidden")

from poker_core import evaluate_best, categorize, describe_score
from main import analyze_draws, postflop_advice, is_overpair

FAILED = []


def check(desc, condition, detail=""):
    status = "✓" if condition else "✗"
    print(f"{status} {desc}")
    if detail:
        print(f"     {detail}")
    if not condition:
        FAILED.append(desc)


def test_draws():
    print("=" * 60)
    print("一、听牌识别")
    print("=" * 60)

    cases = [
        # (手牌, 公共牌, 期望特征, 不期望特征, 说明)
        (["As", "Ks"], ["Qs", "Js", "2h"], "同花听牌", None,
         "AKs 在 QsJs2h：同花听牌"),
        (["Ah", "Kd"], ["Qs", "Jc", "2h"], "卡顺听牌", "两头顺听牌",
         "AK 在 QJ2：只有 T 能补，必须是卡顺而非两头顺"),
        (["9h", "8h"], ["Ts", "7d", "2c"], "两头顺听牌", None,
         "98 在 T72：缺 J 或 6，真两头顺"),
        (["Th", "9d"], ["8s", "7c", "2h"], "两头顺听牌", None,
         "T9 在 872：缺 J 或 6，真两头顺"),
        (["5h", "4d"], ["8s", "7c", "2h"], "卡顺听牌", None,
         "54 在 872：只有 6 能补(45678)，卡顺"),
        (["Ah", "Ad"], ["Ks", "7c", "2h"], None, None,
         "AA 在 K72：超对不是听牌"),
        (["3h", "2d"], ["Ks", "Qd", "9c"], None, None,
         "32 在 KQ9：无任何听牌"),
        (["7h", "6d"], ["Ks", "Qd", "9c"], None, None,
         "76 在 KQ9：需两张才能成顺，不算听牌"),
        (["As", "Ks"], ["Qs", "Js", "2h", "3d", "4c"], None, None,
         "河牌：不存在听牌"),
    ]

    for hole, board, expect, not_expect, desc in cases:
        draws = analyze_draws(hole, board)
        joined = "、".join(draws) if draws else "无"
        cond = True
        if expect is not None:
            cond = cond and any(expect in d for d in draws)
        if not_expect is not None:
            cond = cond and not any(not_expect in d for d in draws)
        if expect is None and not_expect is None:
            cond = len(draws) == 0
        check(desc, cond, f"识别结果: {joined}")


def test_overpair():
    print()
    print("=" * 60)
    print("二、超对识别")
    print("=" * 60)

    cases = [
        (["Ah", "Ad"], ["Ks", "7c", "2h"], True, "AA 在 K72：超对"),
        (["Kh", "Kd"], ["Qs", "7c", "2h"], True, "KK 在 Q72：超对"),
        (["Kh", "Kd"], ["As", "7c", "2h"], False, "KK 在 A72：不是超对（A 更大）"),
        (["Ah", "Kd"], ["Qs", "7c", "2h"], False, "AK 不是对子"),
        (["7h", "7d"], ["Ks", "Qc", "9d"], False, "77 在 KQ9：不是超对"),
    ]
    for hole, board, expect, desc in cases:
        got = is_overpair(hole, board)
        check(desc, got == expect, f"期望 {expect}，实得 {got}")


def test_advice():
    print()
    print("=" * 60)
    print("三、建议生成")
    print("=" * 60)

    cases = [
        # 成牌顺子 -> 大注
        (["9h", "8h"], ["Ts", "7d", "6c"], "大注", "成牌顺子(T987 6)应大注"),
        # 成牌顺子（另一例）
        (["Ah", "Kd"], ["Qs", "Jc", "Td"], "大注", "AK 在 QJT：已成顺子"),
        # 葫芦
        (["Ah", "Ad"], ["As", "Kc", "Kd"], "大注", "AAA KK：葫芦"),
        # 强听牌 -> 半诈唬
        (["As", "Ks"], ["Qs", "Js", "2h"], "半诈唬", "AKs：同花+两头顺，半诈唬"),
        # 超对 -> 下注
        (["Ah", "Ad"], ["Ks", "7c", "2h"], "超对", "AA 在 K72：超对下注"),
        # 弱牌 -> 过牌
        (["3h", "2d"], ["Ks", "Qd", "9c"], "过牌", "32 在 KQ9：过牌"),
        # 卡顺 -> 小注或过牌
        (["5h", "4d"], ["8s", "7c", "2h"], "小注", "54 在 872 卡顺：小注或过牌"),
    ]

    for hole, board, expect, desc in cases:
        score, _ = evaluate_best(hole + board)
        cat = categorize(score)
        draws = analyze_draws(hole, board)
        advice = postflop_advice(cat, draws, board, hole)
        cat_name = describe_score(score)[0]
        check(desc, expect in advice,
              f"牌型={cat_name} 听牌={draws if draws else '无'} "
              f"→ {advice.splitlines()[0][:44]}")


def test_consistency():
    print()
    print("=" * 60)
    print("四、一致性检查（大量随机牌验证不崩溃且输出合理）")
    print("=" * 60)

    import random
    from poker_core import make_deck
    rng = random.Random(2024)

    errors = []
    for i in range(500):
        deck = make_deck()
        cards = rng.sample(deck, 2)
        rest = [c for c in deck if c not in cards]
        board_size = rng.choice([3, 4, 5])
        board = rng.sample(rest, board_size)

        try:
            draws = analyze_draws(cards, board)
            score, best = evaluate_best(cards + board)
            cat = categorize(score)
            advice = postflop_advice(cat, draws, board, cards)

            if not advice or not advice.strip():
                errors.append(f"建议为空: {cards} {board}")
            if len(board) == 5 and draws:
                errors.append(f"河牌不应有听牌: {cards} {board} -> {draws}")
            if not (0 <= cat <= 8):
                errors.append(f"牌型类别越界: {cat}")
            if len(best) != 5:
                errors.append(f"最佳组合不是 5 张: {best}")
        except Exception as e:
            errors.append(f"异常 {cards} {board}: {e}")

    check(f"500 组随机牌全部处理成功", not errors,
          f"错误 {len(errors)} 个" + (f"，示例: {errors[0]}" if errors else ""))


def main():
    test_draws()
    test_overpair()
    test_advice()
    test_consistency()

    print()
    print("=" * 60)
    if FAILED:
        print(f"测试失败 ✗　共 {len(FAILED)} 项未通过：")
        for f in FAILED:
            print(f"  · {f}")
        return 1
    print("全部测试通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
