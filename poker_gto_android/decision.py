# -*- coding: utf-8 -*-
"""翻前 / 翻后决策引擎。

输入是一份"事实清单"（recognizer 解析出来的牌面与场景信息），
输出是一个 Decision。

设计原则
--------
1. **纯逻辑、不依赖 Kivy**：可以脱离界面单独测试，也能放心放进后台线程。
   翻后要跑蒙特卡洛，放在主线程会卡住界面。
2. **可复现**：同一份输入永远得到同一个输出。唯一的随机来源是胜率
   模拟，它通过 seed 参数外部可控，测试时可以固定。
3. **每个结论都要能追溯到依据**：界面里要连依据一起显示（范围表怎么写的、
   胜率多少、底池赔率要求多少），而不是只丢一句"建议加注"。

两条边界要守住
--------------
· 决策完全在本地完成，不调用任何大模型；
· 信息不足时**降级**到不依赖该信息的规则，并在 warnings 里说清楚，
  宁可提示"这里的信息是假设的"，也不要编一个看起来很专业的建议。
"""

from dataclasses import dataclass, field

import ranges
from recognizer import street_of_board

STREET_NAMES = {
    "preflop": "翻前",
    "flop": "翻牌圈",
    "turn": "转牌圈",
    "river": "河牌圈",
}

# 信息识别不到时的兜底假设。每一条被用上时都会往 warnings 里写一句，
# 界面上必须能让用户看到"这个结论建立在什么假设之上"。
DEFAULT_STACK_BB = 100.0
DEFAULT_OPPONENTS = 1          # 认不出人数时按单挑算（偏乐观，要提示）
DEFAULT_OPEN_SIZE_BB = 2.5

# 胜率是对**随机范围**算出来的，比真实对手范围乐观。
# 因此拿它跟底池赔率比较时，要多留出这点余量才敢跟注。
EQUITY_SAFETY_MARGIN = 0.05


@dataclass
class Decision:
    """一次决策的结果。

    action   : 简短动作名，如 "开池加注" / "跟注"
    headline : 主结论，界面大标题用它
    detail   : 详细说明行（列表）
    equity   : 胜率（翻后才有）
    pot_odds : 跟注所需的最低胜率（面对下注时才有）
    source   : 依据来源，明确告诉用户结论是怎么来的
    warnings : 信息缺失或做了假设时的提示
    """
    street: str
    action: str
    headline: str
    detail: list = field(default_factory=list)
    equity: float = None
    pot_odds: float = None
    source: str = ""
    warnings: list = field(default_factory=list)

    @property
    def detail_text(self):
        return "\n".join(self.detail)


# ---------------------------------------------------------------- 听牌分析
def analyze_draws(hole, board):
    """分析听牌（仅真正的"等一张成牌"结构）。

    返回听牌描述列表。注意：**超对等已成牌不属于听牌**，
    它们由 postflop_advice 依据成牌类型单独处理。

    覆盖：同花听牌、两头顺听牌、卡顺听牌。
    """
    from poker_core import RANK_VALUE

    draws = []
    if len(board) >= 5:
        return draws          # 河牌已无后续，不存在听牌

    all_cards = list(hole) + list(board)

    # --- 同花听牌：某一花色恰好 4 张
    suit_counts = {}
    for c in all_cards:
        s = c[1].lower()
        suit_counts[s] = suit_counts.get(s, 0) + 1
    if suit_counts and max(suit_counts.values()) == 4:
        draws.append("同花听牌（9 张出路）")

    # --- 顺子听牌：4 张参与某条顺子、只差 1 张
    #
    # 判定要点：区分两头顺/卡顺，要看**补牌点的个数**，不是看单张补牌
    # 能凑出几条顺子。
    #   · AK 在 QJ2：只有 T 能补（TJQKA）→ 1 个补牌点 → 卡顺（4 出路）
    #   · 98 在 T72：补 J 成 789TJ、补 6 成 6789T → 2 个补牌点 → 两头顺（8 出路）
    # 之前的实现按"单张补牌新增的顺子条数"判断，会把上面第二种情况
    # 的两个补牌各自看成都只新增 1 条，从而误判为卡顺。
    #
    # 另外必须排除已成顺的情况（current_straights 非空即已成型），
    # 否则补牌会误判成听牌。
    rs = {RANK_VALUE[c[0]] for c in all_cards}
    if 14 in rs:
        rs.add(1)

    def straights_with(rank_set):
        """返回 rank_set 能构成的所有顺子的最高牌集合。"""
        found = set()
        for start in range(1, 11):
            window = set(range(start, start + 5))
            if window <= rank_set:
                found.add(max(window))
        return found

    current_straights = straights_with(rs)
    if not current_straights:                   # 已成型则不算听牌
        outs = set()
        for candidate in range(1, 15):
            if candidate in rs:
                continue
            for high in (straights_with(rs | {candidate}) - current_straights):
                window = set(range(high - 4, high + 1))
                # 参与该顺子的牌恰好 4 张 -> 真正"差一张"的听牌结构
                if len(window & rs) == 4:
                    outs.add(candidate)
                    break
        if 14 in outs:
            outs.discard(1)                     # A 以 1/14 重复出现，去重
        if len(outs) >= 2:
            draws.append("两头顺听牌（8 张出路）")
        elif len(outs) == 1:
            draws.append("卡顺听牌（4 张出路）")

    return draws


def is_overpair(hole, board):
    """判断是否持有超对（口袋对子且大于公共牌最大牌）。"""
    from poker_core import RANK_VALUE
    if len(hole) != 2:
        return False
    r1, r2 = hole
    if r1[0].upper() != r2[0].upper():
        return False                            # 不是对子
    if not board:
        return False
    hole_rank = RANK_VALUE[r1[0].upper()]
    board_max = max(RANK_VALUE[c[0].upper()] for c in board)
    return hole_rank > board_max


def _has_strong_draw(draws):
    """是否持有强听牌（同花听牌或两头顺）。"""
    return any(("同花听牌" in d) or ("两头顺听牌" in d) for d in draws)


# ---------------------------------------------------------------- 翻后建议
def _postflop_bet_action(category, draws, board, hole):
    """无人下注时的建议：下注多大 / 过牌。

    返回 (动作, 主结论, 详细行列表)。
    """
    from poker_core import (
        CAT_HIGH_CARD, CAT_PAIR, CAT_TWO_PAIR, CAT_TRIPS, CAT_STRAIGHT,
        CAT_FULL_HOUSE, CAT_QUADS, CAT_STRAIGHT_FLUSH, RANK_VALUE,
    )

    if isinstance(category, str):
        raise TypeError(
            f"postflop_advice 需要整数类别号（CAT_*），收到字符串 {category!r}；"
            "请改用 poker_core.categorize(score) 的返回值。"
        )
    if not isinstance(category, int) or not (CAT_HIGH_CARD <= category <= CAT_STRAIGHT_FLUSH):
        raise ValueError(f"非法牌型类别号：{category!r}")

    board_ranks = [RANK_VALUE[c[0]] for c in board]
    board_high = max(board_ranks) if board_ranks else 0
    board_size = len(board)

    # ---- 已成强牌（优先判断，不受听牌干扰）
    if category >= CAT_STRAIGHT:
        return "下注（大）", "持有顺子及以上的成牌，下大注获取价值", [
            "下注尺度：约 3/4 池。",
            "对手的成牌与听牌都会跟注，做大底池能最大化期望收益。",
        ]

    if category in (CAT_TWO_PAIR, CAT_TRIPS, CAT_FULL_HOUSE, CAT_QUADS):
        return "下注（大）", "持有两对以上的强牌，下大注建池", [
            "下注尺度：约 3/4 池。",
            "此时慢玩会损失价值——对手的顶对、听牌都愿意跟注。",
        ]

    # ---- 超对（属于成牌，不是听牌）
    if hole and is_overpair(hole, board):
        return "下注（中）", "持有超对，下注获取价值", [
            "下注尺度：约 1/2 到 3/4 池。",
            "超对通常领先对手的整个范围，从更差的对子与听牌中榨取价值。",
        ]

    # ---- 强听牌（半诈唬）
    if draws:
        if _has_strong_draw(draws):
            return "下注（半诈唬）", "持有强听牌，半诈唬下注", [
                "下注尺度：约 1/2 到 3/4 池。",
                "半诈唬双赢：对手弃牌直接拿下底池；被跟注你仍有约 1/3 概率反超。",
                "强听牌比弱成牌更适合下注，因为它同时具备弃牌率与反超潜力。",
            ]
        return "下注（小）", "持有弱听牌（卡顺），小注或过牌", [
            "下注尺度：约 1/3 池，也可以直接过牌。",
            "卡顺仅有约 4 张出路，弃牌率与反超潜力都不足，不宜投入过多筹码。",
        ]

    # ---- 顶对
    if category == CAT_PAIR and hole:
        hole_ranks = [RANK_VALUE[c[0]] for c in hole]
        paired = [r for r in hole_ranks if r in board_ranks]

        if paired and max(paired) == board_high:
            if board_size == 3 and board_high >= RANK_VALUE["Q"]:
                return "下注（小）", "持有顶对但牌面偏高，小注控池", [
                    "下注尺度：约 1/3 池。",
                    "牌面偏高时对手范围里两对以上的概率上升，",
                    "小注既能从更差的对子拿价值，被加注时也能低成本脱身。",
                ]
            return "下注（中）", "持有顶对，下注获取价值", [
                "下注尺度：约 1/2 到 3/4 池。",
            ]
        if paired:
            return "过牌", "持有中对或底对，过牌或小注控制底池", [
                "这类牌不足以承受大注，也不适合在被跟注时做大底池。",
            ]

    # ---- 弱牌
    return "过牌", "牌力较弱，过牌控制底池", [
        "用弱牌下注若被跟注或加注会陷入被动；过牌可保留免费看下一张的机会。",
    ]


def _postflop_face_bet_action(category, draws, board, hole,
                              equity, pot_odds_needed, bet_to_call):
    """面对下注时的建议：加注 / 跟注 / 弃牌。

    返回 (动作, 主结论, 详细行列表)。
    """
    from poker_core import CAT_PAIR, CAT_TWO_PAIR, CAT_TRIPS, CAT_STRAIGHT, \
        CAT_FULL_HOUSE, CAT_QUADS

    # 成牌很硬的时候，跟注不如加注把底池做大
    if category >= CAT_STRAIGHT:
        return "加注", "持有顺子及以上的强牌，面对下注应当加注", [
            "用强牌跟注会让底池停在原地；加注能从对手的成牌与听牌那里多榨一轮价值。",
        ]
    if category in (CAT_TWO_PAIR, CAT_TRIPS, CAT_FULL_HOUSE, CAT_QUADS):
        return "加注", "持有两对以上的强牌，面对下注应当加注", [
            "你在这个牌面几乎总是领先，加注是最直接的增值方式。",
        ]

    # 没有胜率信息时退回牌力规则
    if equity is None:
        if _has_strong_draw(draws):
            return "跟注", "持有强听牌，跟注看下一张", [
                "强听牌有约 8-9 张出路，配合底池赔率通常值得继续。",
            ]
        if category == CAT_PAIR:
            return "跟注", "持有一对，跟注控制成本", [
                "一对有一定摊牌价值，但不足以加注，跟注是常见选择。",
            ]
        return "弃牌", "牌力不足，建议弃牌", [
            "面对下注时，没有成牌也没有强听牌，继续投入的期望为负。",
        ]

    # ---- 有胜率：按底池赔率决策
    if pot_odds_needed is not None:
        margin = equity - pot_odds_needed
        if margin >= EQUITY_SAFETY_MARGIN + 0.10:
            return "跟注", "胜率明显高于底池赔率要求，跟注", [
                f"胜率 {equity:.1%}，底池赔率只要求 {pot_odds_needed:.1%}，"
                f"富余 {margin:.1%}。",
                "注意胜率是按对手随机范围算的，实际对手范围更强，"
                "所以要看富余量而不是只看是否达标。",
            ]
        if margin >= EQUITY_SAFETY_MARGIN:
            return "跟注", "胜率高于底池赔率要求，可以跟注", [
                f"胜率 {equity:.1%}，底池赔率要求 {pot_odds_needed:.1%}，"
                f"富余 {margin:.1%}。",
            ]
        if margin >= 0:
            return "跟注（边缘）", "胜率刚够本，属于边缘跟注", [
                f"胜率 {equity:.1%}，底池赔率要求 {pot_odds_needed:.1%}，"
                f"只富余 {margin:.1%}。",
                "扣掉对手范围比随机范围更强这个因素后，实际很可能是亏的。",
                "如果对手下注尺度偏大或位置不利，直接弃牌也不亏。",
            ]
        return "弃牌", "胜率低于底池赔率要求，跟注长期亏钱", [
            f"胜率 {equity:.1%}，但底池赔率要求 {pot_odds_needed:.1%}，"
            f"差 {abs(margin):.1%}。",
            "这里跟注长期是负期望，应当弃牌。",
        ]

    # ---- 有胜率但没底池大小（认不出底池）：用绝对阈值
    if equity >= 0.55:
        return "跟注", "胜率过半，跟注", [
            f"胜率 {equity:.1%}。（未识别到底池大小，无法算精确赔率）",
        ]
    if equity >= 0.38 and _has_strong_draw(draws):
        return "跟注", "持有强听牌且胜率尚可，跟注", [
            f"胜率 {equity:.1%}，且持有强听牌。（未识别到底池大小）",
        ]
    return "弃牌", "胜率不足，建议弃牌", [
        f"胜率仅 {equity:.1%}。（未识别到底池大小，这里用的是经验阈值）",
    ]


def postflop_advice(category, draws, board, hole=None, *,
                    equity=None, pot_odds_needed=None, bet_to_call=None):
    """翻后建议（文本形式，兼容旧接口）。

    category         必须是 poker_core 的整数类别号（CAT_*，0-8），
                     不是 describe_score 返回的中文名。传错会在比较时抛
                     TypeError，因此内部先做显式校验。
    equity           胜率（可选）。传了就能给出带赔率依据的结论。
    pot_odds_needed  跟注所需的最低胜率（可选）。
    bet_to_call      需要跟注的金额（可选）。> 0 表示面对下注。

    不传后三个参数时，行为与旧版完全一致（只按牌力与听牌给方向性建议）。
    """
    if bet_to_call and bet_to_call > 0:
        _, headline, lines = _postflop_face_bet_action(
            category, draws, board, hole, equity, pot_odds_needed, bet_to_call
        )
    else:
        _, headline, lines = _postflop_bet_action(category, draws, board, hole)
    return "\n".join([headline] + lines)


# ---------------------------------------------------------------- 翻前决策
def _decide_preflop(hole, position, stack_bb, num_raisers, num_limpers,
                    raiser_position, warnings):
    """翻前决策。返回 Decision。"""
    from poker_core import all_hand_notations, hand_notation

    notation = hand_notation(*hole)
    pos_name = ranges.POSITION_NAMES.get(position, position)
    raisers = num_raisers or 0
    limpers = num_limpers or 0
    depth = ranges.depth_note(stack_bb)

    def _detail(lines):
        return [ln for ln in lines if ln]

    # ---------------------------------------------------- 大盲且无人加注
    # 大盲这时候已经投了 1bb，不存在"开池"这个说法：要么过牌免费看牌，
    # 要么加注施压。这是范围表覆盖不到的情形，单独处理。
    if position == "BB" and raisers == 0:
        ranking = all_hand_notations()
        idx = ranking.index(notation) if notation in ranking else len(ranking)
        pct = (idx + 1) / len(ranking)

        if pct <= 0.12:
            return Decision(
                street="preflop", action="加注",
                headline=f"翻前：加注施压（{notation}）",
                detail=_detail([
                    f"你在 {pos_name}，前面没有人加注。",
                    f"{notation} 属于最强的前 {pct:.0%} 起手牌。",
                    "无人入池时加注既能直接拿下底池，也能把弱牌赶走、避免多人混战。",
                    f"加注尺度：约 3bb。{depth}",
                ]),
                source="起手牌强度排名（大盲无开池范围）",
                warnings=warnings,
            )
        return Decision(
            street="preflop", action="过牌",
            headline=f"翻前：过牌看翻牌（{notation}）",
            detail=_detail([
                f"你在 {pos_name}，前面没有人加注，可以免费看翻牌。",
                f"{notation} 的强度排在前 {pct:.0%}，属于中等或偏弱。",
                "这时候加注只会赶走更差的牌、留下更强的牌，过牌更划算。",
                depth,
            ]),
            source="起手牌强度排名（大盲无开池范围）",
            warnings=warnings,
        )

    # ---------------------------------------------------- 面对 3bet 及以上
    if raisers >= 2:
        action, freq, desc = ranges.get_vs_3bet_action(hole, position, stack_bb)
        detail = _detail([
            f"你以 {pos_name} 开池后被 3bet。",
            f"{notation} 在这种情况下：{desc}",
            depth,
        ])
        if action == "4bet":
            detail.append("4bet 尺度：有位置时约为 3bet 的 2.2 倍，无位置时 2.5-3 倍。")
            return Decision(
                street="preflop", action="4bet",
                headline=f"翻前：4bet（{notation}）",
                detail=detail,
                source=f"面对 3bet 范围表（{position} 开池）",
                warnings=warnings,
            )
        if action == "call":
            detail.append("跟注后进入翻牌圈，注意自己的位置和底池大小。")
            return Decision(
                street="preflop", action="跟注",
                headline=f"翻前：跟注（{notation}）",
                detail=detail,
                source=f"面对 3bet 范围表（{position} 开池）",
                warnings=warnings,
            )
        return Decision(
            street="preflop", action="弃牌",
            headline=f"翻前：弃牌（{notation}）",
            detail=_detail([
                f"你以 {pos_name} 开池后被 3bet。",
                f"{notation} 不在继续范围内。",
                "3bet 代表对手范围已经很窄很强，继续投入通常无利可图。",
                depth,
            ]),
            source=f"面对 3bet 范围表（{position} 开池）",
            warnings=warnings,
        )

    # ---------------------------------------------------- 面对单一开池
    if raisers == 1:
        opener = raiser_position
        if opener not in ranges.POSITIONS:
            opener = "CO"
            warnings.append(
                "未识别到加注者的位置，暂按 CO（关位）估算。"
                "实际应对要按开池位置调整：开池位置越靠前，你的继续范围越要紧。"
            )
        action, freq, desc = ranges.get_vs_open_action(hole, opener, stack_bb)
        opener_name = ranges.POSITION_NAMES.get(opener, opener)

        detail = _detail([
            f"前面有 {opener_name} 开池加注。",
            f"{notation} 面对该位置开池：{desc}",
            depth,
        ])
        if action == "3bet":
            detail.append("3bet 尺度：有位置时约为开池的 3 倍，无位置时 4 倍。")
            return Decision(
                street="preflop", action="3bet",
                headline=f"翻前：3bet（{notation}）",
                detail=detail,
                source=f"面对开池范围表（vs {opener}）",
                warnings=warnings,
            )
        if action == "call":
            detail.append(
                "跟注时要意识到：后面还没行动的人可能加注，位置越差风险越大。"
            )
            return Decision(
                street="preflop", action="跟注",
                headline=f"翻前：跟注（{notation}）",
                detail=detail,
                source=f"面对开池范围表（vs {opener}）",
                warnings=warnings,
            )
        return Decision(
            street="preflop", action="弃牌",
            headline=f"翻前：弃牌（{notation}）",
            detail=_detail([
                f"前面有 {opener_name} 开池加注。",
                f"{notation} 不在面对该位置的防守范围内。",
                "前面位置弃牌、等待更好的机会更有利可图。",
                depth,
            ]),
            source=f"面对开池范围表（vs {opener}）",
            warnings=warnings,
        )

    # ---------------------------------------------------- 有 limper
    if limpers > 0:
        # 没有专门的"面对 limper"范围表，用本位置的开池范围近似。
        # 理由：limp 通常代表很弱且被动的范围，隔离加注需要的范围
        # 与开池范围基本相当。这属于简化处理。
        action, freq, desc = ranges.get_open_action(hole, position, stack_bb)
        size = round(3 + 1 * min(limpers, 3), 1)
        if action == "open":
            return Decision(
                street="preflop", action="隔离加注",
                headline=f"翻前：隔离加注（{notation}）",
                detail=_detail([
                    f"前面有 {limpers} 人跟平入池，还没有人加注。",
                    f"{notation} 在 {pos_name} 的可玩范围内：{desc}",
                    f"建议加注到约 {size}bb——比标准开池大，"
                    "目的是把 limper 赶走，避免多人混战摊牌。",
                    depth,
                ]),
                source=f"开池范围表（{position}，面对 limper 的近似）",
                warnings=warnings,
            )
        return Decision(
            street="preflop", action="弃牌",
            headline=f"翻前：弃牌（{notation}）",
            detail=_detail([
                f"前面有 {limpers} 人跟平入池。",
                f"{notation} 不在 {pos_name} 的可玩范围内。",
                "不要因为「别人都进来了，我也便宜跟一下」而玩弱牌——"
                "便宜跟注长期是亏的。",
                depth,
            ]),
            source=f"开池范围表（{position}，面对 limper 的近似）",
            warnings=warnings,
        )

    # ---------------------------------------------------- 无人入池：开池
    action, freq, desc = ranges.get_open_action(hole, position, stack_bb)
    if action == "open":
        width = ranges.range_width(position)
        return Decision(
            street="preflop", action="开池加注",
            headline=f"翻前：开池加注（{notation}）",
            detail=_detail([
                f"你在 {pos_name}，前面的人都弃牌了。",
                f"{notation} 在标准开池范围内：{desc}",
                f"建议加注到约 {DEFAULT_OPEN_SIZE_BB}bb。",
                f"该位置的标准范围宽度约 {width:.1%}。",
                depth,
            ]),
            source=f"开池范围表（{position}）",
            warnings=warnings,
        )
    return Decision(
        street="preflop", action="弃牌",
        headline=f"翻前：弃牌（{notation}）",
        detail=_detail([
            f"你在 {pos_name}，前面的人都弃牌了。",
            f"{notation} 不在 {pos_name} 的开池范围内。",
            "前面位置弃牌、等待更好的机会更有利可图。",
            depth,
        ]),
        source=f"开池范围表（{position}）",
        warnings=warnings,
    )


# ---------------------------------------------------------------- 翻后决策
def _decide_postflop(hole, board, position, pot_bb, bet_to_call_bb,
                     stack_bb, num_players, iterations, seed, warnings):
    """翻后决策。返回 Decision。"""
    from poker_core import (
        categorize, describe_score, estimate_equity, evaluate_best,
        hand_to_string, pot_odds,
    )

    street = street_of_board(len(board))
    street_name = STREET_NAMES[street]

    score, best = evaluate_best(hole + board)
    cat_name, cat_detail = describe_score(score)
    cat_num = categorize(score)
    draws = analyze_draws(hole, board)

    # 对手数量：认不出来就按单挑算，并明确告知——多人局实际胜率低得多
    opponents = DEFAULT_OPPONENTS
    if num_players and num_players >= 2:
        opponents = num_players - 1
    else:
        warnings.append(
            f"未识别到入池人数，胜率按 {opponents + 1} 人（{opponents} 名对手）"
            "估算。多人局的真实胜率会明显更低。"
        )

    equity, tie = estimate_equity(
        hole, board, num_opponents=opponents,
        iterations=iterations or 600, seed=seed,
    )

    base_lines = [
        f"最佳五张：{hand_to_string(best)}",
        f"牌型：{cat_name}（{cat_detail}）",
    ]
    if draws:
        base_lines.append("听牌：" + "、".join(draws))
    base_lines.append(
        f"胜率：{equity:.1%}（对 {opponents} 名对手的随机范围，平局 {tie:.1%}）"
    )

    facing_bet = bool(bet_to_call_bb and bet_to_call_bb > 0)

    if facing_bet:
        # ---- 面对下注：核心是底池赔率
        needed = None
        if pot_bb is not None and pot_bb > 0:
            pot_before = max(0.0, pot_bb - bet_to_call_bb)
            needed = pot_odds(bet_to_call_bb, pot_before)
            base_lines.append(
                f"底池 {pot_bb:.1f}bb，对手下注 {bet_to_call_bb:.1f}bb，"
                f"你跟注需要达到 {needed:.1%} 胜率才不亏。"
            )
        else:
            warnings.append(
                "未识别到底池大小，无法计算底池赔率，改用胜率经验阈值判断。"
            )

        action, headline, lines = _postflop_face_bet_action(
            cat_num, draws, board, hole, equity, needed, bet_to_call_bb
        )
        detail = base_lines + [""] + lines
        if needed is not None:
            detail.append(
                "提示：胜率是按对手「随机两张牌」算的，真实对手范围更强，"
                "所以判断跟注时留了安全余量。"
            )
        return Decision(
            street=street, action=action,
            headline=f"{street_name}：{headline}",
            detail=detail,
            equity=equity,
            pot_odds=needed,
            source="蒙特卡洛胜率 + 底池赔率",
            warnings=warnings,
        )

    # ---- 无人下注：主动下注还是过牌
    action, headline, lines = _postflop_bet_action(cat_num, draws, board, hole)
    detail = base_lines + [""] + lines

    if pot_bb and pot_bb > 0:
        # 把"占底池百分比"换算成具体筹码量，比"3/4 池"更直观。
        # 这里必须看 action 而不是 headline——"持有超对，下注获取价值"
        # 这句里根本没有"大/中"字样，拿它做判断会一律落到最小尺度。
        fraction = 0.75 if "大" in action else (
            0.5 if ("中" in action or "半诈唬" in action) else 0.33
        )
        size = round(pot_bb * fraction, 1)
        detail.append(f"参考：底池 {pot_bb:.1f}bb，下注约 {size}bb。")
    else:
        detail.append("（未识别到底池大小，下注尺度按经验比例给出）")

    return Decision(
        street=street, action=action,
        headline=f"{street_name}：{headline}",
        detail=detail,
        equity=equity,
        source="蒙特卡洛胜率 + 牌力与听牌评估",
        warnings=warnings,
    )


# ---------------------------------------------------------------- 主入口
def decide(hole, board, hero_position="unknown", num_players=None,
           effective_stack_bb=None, pot_bb=None, bet_to_call_bb=None,
           num_raisers=0, num_limpers=0, raiser_position="unknown",
           iterations=None, seed=None):
    """根据牌面与场景给出决策。

    参数全部来自 recognizer.parse_cards() 的结果，缺什么就降级处理，
    并把降级情况写进 Decision.warnings。

    返回 Decision。手牌不完整时抛 ValueError。
    """
    hole = list(hole or [])
    board = list(board or [])

    if len(hole) != 2:
        raise ValueError(f"需要 2 张手牌才能决策，收到 {len(hole)} 张")
    if any(c == "??" for c in hole):
        raise ValueError("手牌中有无法确定的牌（??），请先手动校对")

    warnings = []
    # 只保留能确定的花色点数，牌面不完整时按已看到的牌算
    board = [c for c in board if c != "??"]

    position = hero_position if hero_position in ranges.POSITIONS else ""
    if not position:
        position = "BTN"
        warnings.append(
            f"位置「{hero_position}」无法识别，暂按 BTN（庄位）估算。"
            "位置会显著影响决策，建议手动指定。"
        )

    stack_bb = effective_stack_bb
    if stack_bb is None:
        stack_bb = DEFAULT_STACK_BB
        warnings.append(f"未识别到筹码深度，暂按 {DEFAULT_STACK_BB:.0f}bb 计算。")

    street = street_of_board(len(board))

    if street == "preflop":
        return _decide_preflop(
            hole, position, stack_bb, num_raisers, num_limpers,
            raiser_position, warnings,
        )
    return _decide_postflop(
        hole, board, position, pot_bb, bet_to_call_bb, stack_bb,
        num_players, iterations, seed, warnings,
    )


def decide_from_cards(cards, iterations=None, seed=None):
    """直接用 recognizer.parse_cards() 的结果做决策，省得手动拆字段。"""
    return decide(
        hole=cards.get("hole_cards") or [],
        board=cards.get("board_cards") or [],
        hero_position=cards.get("hero_position") or "unknown",
        num_players=cards.get("num_players"),
        effective_stack_bb=cards.get("effective_stack_bb"),
        pot_bb=cards.get("pot_bb"),
        bet_to_call_bb=cards.get("bet_to_call_bb"),
        num_raisers=cards.get("num_raisers") or 0,
        num_limpers=cards.get("num_limpers") or 0,
        raiser_position=cards.get("raiser_position") or "unknown",
        iterations=iterations, seed=seed,
    )


if __name__ == "__main__":
    print("=== 决策引擎自检 ===")
    ok = True

    def show(title, d):
        print(f"\n--- {title} ---")
        print(f"【{d.action}】{d.headline}")
        for line in d.detail:
            if line:
                print(f"    {line}")
        if d.source:
            print(f"    依据：{d.source}")
        for w in d.warnings:
            print(f"    ! {w}")

    # ---------------------------------------------- 翻前：无人入池
    d = decide(["As", "Ks"], [], hero_position="BTN", num_players=6,
               effective_stack_bb=100, num_raisers=0, num_limpers=0)
    show("翻前 BTN，AKs，无人入池", d)
    if d.action != "开池加注":
        print("  ✗ 期望开池加注"); ok = False

    d = decide(["7c", "2d"], [], hero_position="UTG", num_players=6,
               effective_stack_bb=100)
    show("翻前 UTG，72o，无人入池", d)
    if d.action != "弃牌":
        print("  ✗ 期望弃牌"); ok = False

    # ---------------------------------------------- 翻前：面对开池
    d = decide(["Ah", "Ad"], [], hero_position="BB", num_players=6,
               effective_stack_bb=100, num_raisers=1, raiser_position="BTN")
    show("翻前 BB，AA，面对 BTN 开池", d)
    if d.action != "3bet":
        print("  ✗ 期望 3bet"); ok = False

    d = decide(["8h", "7h"], [], hero_position="BB", num_players=6,
               effective_stack_bb=100, num_raisers=1, raiser_position="BTN")
    show("翻前 BB，87s，面对 BTN 开池", d)
    if d.action != "跟注":
        print("  ✗ 期望跟注"); ok = False

    # 加注者位置未知时应降级并提示
    d_unknown = decide(["Ah", "Ad"], [], hero_position="BB",
                       effective_stack_bb=100, num_raisers=1)
    if not any("加注者的位置" in w for w in d_unknown.warnings):
        print("  ✗ 加注者位置未知时应给出提示"); ok = False
    else:
        print("\n  ✓ 加注者位置未知时正确降级并提示")

    # ---------------------------------------------- 翻前：面对 3bet
    d = decide(["Ah", "Ad"], [], hero_position="BTN", num_players=6,
               effective_stack_bb=100, num_raisers=2)
    show("翻前 BTN，AA，开池后被 3bet", d)
    if d.action != "4bet":
        print("  ✗ 期望 4bet"); ok = False

    d = decide(["9h", "8h"], [], hero_position="BTN", num_players=6,
               effective_stack_bb=100, num_raisers=2)
    show("翻前 BTN，98s，开池后被 3bet", d)
    if d.action != "跟注":
        print("  ✗ 期望跟注（有位置的同花连张可以跟注看翻牌）"); ok = False

    d = decide(["7c", "2d"], [], hero_position="BTN", num_players=6,
               effective_stack_bb=100, num_raisers=2)
    show("翻前 BTN，72o，开池后被 3bet", d)
    if d.action != "弃牌":
        print("  ✗ 期望弃牌"); ok = False

    # ---------------------------------------------- 翻前：大盲无人加注
    d = decide(["Ah", "Ad"], [], hero_position="BB", num_players=2,
               effective_stack_bb=100, num_raisers=0, num_limpers=1)
    show("翻前 BB，AA，只有 SB 跟平", d)
    if d.action != "加注":
        print("  ✗ 期望加注"); ok = False

    # ---------------------------------------------- 翻前：面对 limper
    d = decide(["Kh", "Qh"], [], hero_position="CO", num_players=6,
               effective_stack_bb=100, num_limpers=2)
    show("翻前 CO，KQs，面对 2 个 limper", d)
    if d.action != "隔离加注":
        print("  ✗ 期望隔离加注"); ok = False

    # ---------------------------------------------- 翻后：无人下注
    d = decide(["9h", "8h"], ["Ts", "7d", "6c"], hero_position="BTN",
               num_players=2, effective_stack_bb=100, pot_bb=8.0,
               bet_to_call_bb=0, iterations=800, seed=42)
    show("翻牌圈，98 在 T76（已成顺）", d)
    if d.equity is None or d.equity < 0.75:
        print(f"  ✗ 成顺的胜率应很高，实得 {d.equity}"); ok = False

    # ---------------------------------------------- 翻后：面对下注
    # 顺子面对下注 -> 加注
    d = decide(["9h", "8h"], ["Ts", "7d", "6c"], hero_position="BTN",
               num_players=2, effective_stack_bb=100, pot_bb=12.0,
               bet_to_call_bb=4.0, iterations=800, seed=42)
    show("翻牌圈，98 在 T76，面对 4bb 下注", d)
    if d.action != "加注":
        print("  ✗ 期望加注"); ok = False

    # 弱牌面对大注 -> 弃牌
    d = decide(["3h", "2d"], ["Ks", "Qd", "9c"], hero_position="BTN",
               num_players=2, effective_stack_bb=100, pot_bb=20.0,
               bet_to_call_bb=15.0, iterations=800, seed=42)
    show("翻牌圈，32 在 KQ9，面对 15bb 大注", d)
    if d.action != "弃牌":
        print("  ✗ 期望弃牌"); ok = False

    # 强听牌面对小注 -> 跟注
    d = decide(["As", "Ks"], ["Qs", "Js", "2h"], hero_position="BTN",
               num_players=2, effective_stack_bb=100, pot_bb=8.0,
               bet_to_call_bb=2.0, iterations=800, seed=42)
    show("翻牌圈，AKs 同花+两头顺，面对 2bb 小注", d)
    if d.action not in ("跟注", "跟注（边缘）"):
        print(f"  ✗ 期望跟注，实得 {d.action}"); ok = False

    # ---------------------------------------------- 信息缺失的降级
    d = decide(["Ah", "Ad"], ["Ks", "7c", "2h"], hero_position="unknown",
               iterations=400, seed=1)
    show("翻牌圈，AA 超对，所有场景信息都缺失", d)
    warn_text = " ".join(d.warnings)
    for must in ("位置", "筹码深度", "入池人数"):
        if must not in warn_text:
            print(f"  ✗ 缺少关于「{must}」的提示"); ok = False
    if d.action != "下注（中）":
        print(f"  ✗ 超对应下注，实得 {d.action}"); ok = False
    print("\n  ✓ 场景信息全缺失时逐项降级并提示")

    # ---------------------------------------------- 边界
    for bad, label in [
        ((["As"], [], "手牌只有 1 张"), "手牌只有 1 张"),
        ((["As", "??"], [], "手牌有遮挡"), "手牌有 ?? "),
    ]:
        try:
            decide(bad[0], bad[1])
            print(f"  ✗ {label} 应报错"); ok = False
        except ValueError:
            pass
    print("  ✓ 手牌不完整时正确报错")

    # ---------------------------------------------- 一致性
    import random
    from poker_core import make_deck
    rng = random.Random(2024)
    errors = []
    for _ in range(120):
        deck = make_deck()
        hole = rng.sample(deck, 2)
        rest = [c for c in deck if c not in hole]
        board = rng.sample(rest, rng.choice([0, 3, 4, 5]))
        kwargs = dict(
            hero_position=rng.choice(ranges.POSITIONS),
            num_players=rng.choice([2, 3, 6]),
            effective_stack_bb=rng.choice([15, 40, 100, 200]),
            num_raisers=rng.choice([0, 1, 2]),
            num_limpers=rng.choice([0, 0, 1, 2]),
        )
        if board:
            kwargs["pot_bb"] = rng.uniform(2, 30)
            kwargs["bet_to_call_bb"] = rng.choice([0, 0, 2, 5, 12])
        try:
            d = decide(hole, board, iterations=120, seed=7, **kwargs)
            if not d.headline or not d.action:
                errors.append(f"结论为空 {hole} {board}")
            if board and d.equity is None:
                errors.append(f"翻后应有胜率 {hole} {board}")
            if not board and d.equity is not None:
                errors.append(f"翻前不该算胜率 {hole}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{hole} {board} {kwargs} -> {type(e).__name__}: {e}")
    if errors:
        ok = False
        print(f"\n  ✗ 120 组随机场景出现 {len(errors)} 个问题")
        for e in errors[:5]:
            print("     ", e)
    else:
        print("\n  ✓ 120 组随机场景全部正常（不崩溃、字段完整）")

    print("\n全部自检通过 ✓" if ok else "\n存在失败项 ✗")
