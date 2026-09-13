# -*- coding: utf-8 -*-
"""牌力计算与胜率估算的正确性验证（对照数学精确值）。

为什么要单独有这个文件
----------------------
单元测试只能验证"我想到的那几种情况"是对的，验证不了"我没想到的情况"。
而 hand evaluator 一旦有细微的比牌错误，表现是所有建议的可信度整体下降，
但在界面上完全看不出来——单看某一手牌的建议，你没法发现它错了。

所以这里用两个**精确对照**来做金标准验证：

【1】穷举全部 C(52,5)=2598960 种五张牌组合，统计牌型分布。
     牌型分布是扑克数学的标准结果（精确值，不是估算），
     九项必须逐项相等。这一关过了，说明分类逻辑完全正确。

【2】拿一个转牌圈场景做完全穷举（对手手牌 × 河牌 = 45540 种），
     得到精确胜率，再和蒙特卡洛的结果对照。
     这一关过了，说明抽样实现没有系统性偏差。

用法：
    python verify_core.py          # 全部跑，约 40 秒
    python verify_core.py --quick  # 只跑第 1 部分，约 12 秒

注意：这两个验证都**不进**常规测试流程（太慢），改完 poker_core 后手动跑一次。
"""

import sys
import time
from itertools import combinations

from poker_core import (
    CATEGORY_NAMES, estimate_equity, evaluate_best, evaluate_five,
    categorize, make_deck,
)

# 五张牌牌型分布的理论值（精确整数，可查证）
THEORY_DISTRIBUTION = {
    "同花顺": 40,
    "四条": 624,
    "葫芦": 3744,
    "同花": 5108,
    "顺子": 10200,
    "三条": 54912,
    "两对": 123552,
    "一对": 1098240,
    "高牌": 1302540,
}
TOTAL_COMBOS = 2598960


def verify_distribution():
    """穷举所有五张牌组合，对照理论分布。"""
    print("【1】穷举 C(52,5) 全部组合，对照牌型分布")
    print("-" * 58)

    t0 = time.time()
    counts = {}
    for combo in combinations(make_deck(), 5):
        cat = categorize(evaluate_five(combo))
        counts[cat] = counts.get(cat, 0) + 1
    elapsed = time.time() - t0

    total = sum(counts.values())
    ok = total == TOTAL_COMBOS

    print(f"{'牌型':<8}{'实测':>11}{'理论':>11}{'差异':>9}")
    for cat, name in CATEGORY_NAMES.items():
        got = counts.get(cat, 0)
        want = THEORY_DISTRIBUTION[name]
        if got != want:
            ok = False
        print(f"{name:<8}{got:>11d}{want:>11d}{got - want:>+9d}")

    print(f"{'合计':<8}{total:>11d}{TOTAL_COMBOS:>11d}"
          f"{total - TOTAL_COMBOS:>+9d}")
    print(f"耗时 {elapsed:.1f}s")
    print("结论：" + ("分类完全正确，九项逐项吻合" if ok else "存在分类错误"))
    return ok


def verify_monte_carlo():
    """穷举转牌圈，得到精确胜率，对照蒙特卡洛。"""
    hole = ["7c", "2d"]
    board = ["Ks", "Qh", "Jd", "9c"]

    print()
    print("【2】穷举转牌圈场景，对照蒙特卡洛")
    print("-" * 58)
    print(f"手牌 {' '.join(hole)}   公共牌 {' '.join(board)}   对手 1 名")

    known = set(hole) | set(board)
    deck = [c for c in make_deck() if c not in known]

    t0 = time.time()
    wins = ties = total = 0
    for opp in combinations(deck, 2):
        rest = [c for c in deck if c not in opp]
        for river in rest:
            full = board + [river]
            me = evaluate_best(hole + full)[0]
            them = evaluate_best(list(opp) + full)[0]
            total += 1
            if me > them:
                wins += 1
            elif me == them:
                ties += 1
    elapsed = time.time() - t0

    w_exact, t_exact = wins / total, ties / total
    print(f"穷举 {total} 种组合（精确值，无抽样误差），耗时 {elapsed:.1f}s")
    print(f"  精确胜率 {w_exact:.2%}   精确平局率 {t_exact:.2%}")

    print()
    print(f"{'模拟次数':>10}{'胜率':>10}{'平局率':>10}{'偏差':>10}")
    ok = True
    for iters in (200, 600, 2000, 20000):
        w, t = estimate_equity(hole, board, num_opponents=1,
                               iterations=iters, seed=2024)
        print(f"{iters:>10}{w:>10.2%}{t:>10.2%}{w - w_exact:>+10.2%}")

    # 多随机种子的均值应收敛到精确值——单看一个种子可能是碰巧
    vals = [estimate_equity(hole, board, num_opponents=1,
                            iterations=2000, seed=s)[0] for s in range(8)]
    mean = sum(vals) / len(vals)
    drift = abs(mean - w_exact)
    print()
    print(f"8 个种子各 2000 次的均值：{mean:.2%}"
          f"（精确值 {w_exact:.2%}，偏差 {mean - w_exact:+.2%}）")
    if drift > 0.01:
        ok = False
        print("结论：抽样存在系统性偏差（偏差超过 1%）")
    else:
        print("结论：抽样无系统性偏差，蒙特卡洛实现正确")

    # 顺带说明一个容易搞混的点
    print()
    print("注：多数资料里 72o 翻前的 \"34.6%\" 是**含平局折半**的 equity，")
    print("    而 estimate_equity() 返回的是**纯胜率**（平局单独统计）。")
    print("    两者相差的正是平局率的一半，不要拿前者来对本函数的结果。")
    return ok


def main():
    quick = "--quick" in sys.argv
    print("=" * 58)
    print("  牌力计算与胜率估算 — 精确对照验证")
    print("=" * 58)

    ok = verify_distribution()
    if not quick:
        ok = verify_monte_carlo() and ok
    else:
        print("\n（--quick：已跳过蒙特卡洛对照）")

    print()
    print("=" * 58)
    print("总体结论：" + ("全部通过" if ok else "存在失败项"))
    print("=" * 58)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
