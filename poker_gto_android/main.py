# -*- coding: utf-8 -*-
"""GTO 助手 - 安卓 App 主程序（Kivy）。

界面分三个页面：
  1. 实时识别页：摄像头预览 + 实时抽帧识别 + GTO 推荐
  2. 训练页：GTO 刷题训练
  3. 设置页：配置 AI 接口

设计说明
--------
本 App 的 GTO 推荐基于**内置的翻前范围表**（免费、离线、无需联网）。
AI 识别仅用于把牌面"读"进来，所有识别结果都需人工校对。
本工具面向学习与训练，请勿用于真实牌局的实时决策。
"""

import os
import threading

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.core.text import LabelBase
from kivy.lang import Builder
from kivy.metrics import dp, sp
from kivy.properties import (
    BooleanProperty, ListProperty, NumericProperty, ObjectProperty, StringProperty,
)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.utils import platform

import config as cfg_mod
import ranges
from poker_core import hand_to_string, parse_card, CardError
from trainer import (
    generate_question, ACTION_LABELS,
    ACTION_OPEN, ACTION_FOLD, ACTION_3BET, ACTION_CALL,
    ACTION_CHECK, ACTION_BET_SMALL, ACTION_BET_BIG,
)
import stats as stats_mod
import realtime
import recognizer

# ---------------------------------------------------------------- 中文字体
# Kivy 默认字体不含中文，需要注册中文字体。
# 优先级：随 apk 打包的自带字体 > 系统字体。
# 自带字体用 pack_font.py 生成，这样即便设备字体缺失也能正常显示。
_HERE = os.path.dirname(os.path.abspath(__file__))
_CJK_FONT_CANDIDATES = [
    # 随包分发（app 私有目录 / assets）
    os.path.join(_HERE, "assets", "chinese.ttf"),
    os.path.join(_HERE, "chinese.ttf"),
    # 安卓系统字体
    "/system/fonts/NotoSansCJK-Regular.ttc",
    "/system/fonts/NotoSansSC-Regular.otf",
    "/system/fonts/DroidSansFallback.ttf",
    # Windows
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    # Linux
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]

FONT_NAME = "AppCJK"


def register_cjk_font():
    """注册中文字体，返回是否成功。"""
    for path in _CJK_FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                LabelBase.register(name=FONT_NAME, fn_regular=path)
                return True, path
            except Exception:
                continue
    return False, None


_FONT_OK, _FONT_PATH = register_cjk_font()


# ---------------------------------------------------------------- 设计常量
COLOR_BG = (0.96, 0.97, 0.98, 1)
COLOR_CARD_BG = (1, 1, 1, 1)
COLOR_PRIMARY = (0.10, 0.37, 0.71, 1)
COLOR_GREEN = (0.18, 0.62, 0.27, 1)
COLOR_RED = (0.84, 0.27, 0.27, 1)
COLOR_GRAY = (0.48, 0.52, 0.58, 1)
COLOR_DARK = (0.16, 0.20, 0.25, 1)
COLOR_AMBER = (0.78, 0.47, 0.13, 1)


def F(size):
    """带字体名的字号快捷方式。"""
    return sp(size) if _FONT_OK else sp(size)


KV = """
#:import dp kivy.metrics.dp
#:import sp kivy.metrics.sp

<CardLabel@Label>:
    font_name: "AppCJK" if app.font_ok else "Roboto"
    color: 0.16, 0.20, 0.25, 1

<SectionTitle@Label>:
    font_name: "AppCJK" if app.font_ok else "Roboto"
    font_size: sp(15)
    bold: True
    color: 0.10, 0.37, 0.71, 1
    size_hint_y: None
    height: dp(28)
    halign: "left"
    text_size: self.size

<BodyLabel@Label>:
    font_name: "AppCJK" if app.font_ok else "Roboto"
    color: 0.16, 0.20, 0.25, 1
    font_size: sp(14)
    size_hint_y: None
    text_size: self.width, None
    halign: "left"
    valign: "top"

<AppActionButton@Button>:
    font_name: "AppCJK" if app.font_ok else "Roboto"
    font_size: sp(15)
    bold: True
    background_normal: ""
    background_color: 0.10, 0.37, 0.71, 1
    color: 1, 1, 1, 1
    size_hint_y: None
    height: dp(46)

<ChoiceButton@Button>:
    font_name: "AppCJK" if app.font_ok else "Roboto"
    font_size: sp(15)
    bold: True
    background_normal: ""
    background_color: 0.93, 0.95, 0.97, 1
    color: 0.16, 0.20, 0.25, 1
    size_hint_y: None
    height: dp(50)
"""


class PlayCard(BoxLayout):
    """单张牌的图形化展示（用 canvas 绘制）。

    注意：card 属性可能在 Widget 尚未完成初始化时被赋值
    （Kivy 属性回调早于 __init__ 结束触发），因此绘制前必须
    检查 canvas 是否可用，否则会抛 AttributeError。
    """

    card = StringProperty("")
    # _label 必须是类级属性（ObjectProperty），因为 Kivy 的 kv 规则
    # 会在 __init__ 内部就被应用，届时实例属性尚未赋值
    _label = ObjectProperty(None, allownone=True)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.size_hint = (None, None)
        self.size = (dp(46), dp(64))
        # 构造完成后再绘制一次，确保 canvas 已就绪
        self._redraw()

    def on_card(self, *args):
        self._redraw()

    def on_size(self, *args):
        if self.canvas is not None:
            self._redraw()

    def on_pos(self, *args):
        if self.canvas is not None:
            self._redraw()

    def _redraw(self):
        from kivy.graphics import Color, RoundedRectangle, Line
        # canvas 在 Widget.__init__ 完成前为 None，此时跳过绘制
        if self.canvas is None:
            return
        self.canvas.clear()

        if not self.card:
            with self.canvas:
                Color(0.94, 0.95, 0.97, 1)
                RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(6)])
            self._sync_label(None, None, None)
            return

        try:
            rank, suit = parse_card(self.card)
        except CardError:
            return

        is_red = suit in ("h", "d")
        color = (0.84, 0.16, 0.16, 1) if is_red else (0.10, 0.10, 0.12, 1)
        symbol = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}[suit]

        with self.canvas:
            Color(1, 1, 1, 1)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(6)])
            Color(0.78, 0.80, 0.84, 1)
            Line(rounded_rectangle=(self.x, self.y, self.width, self.height,
                                    dp(6)), width=1.0)

        self._sync_label(rank, symbol, color)

    def _sync_label(self, rank, symbol, color):
        """同步叠加的文字层。"""
        if self._label is not None:
            try:
                self.remove_widget(self._label)
            except Exception:
                pass
            self._label = None

        if rank is None:
            return

        from kivy.uix.label import Label as KLabel
        lbl = KLabel(
            text=f"{rank}\n{symbol}",
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(17),
            color=color,
            halign="center",
            valign="middle",
        )
        lbl.bind(size=lambda *a: setattr(lbl, "text_size", lbl.size))
        self._label = lbl
        self.add_widget(lbl)


class CardRow(BoxLayout):
    """一排牌。"""

    cards = ListProperty([])
    slots = NumericProperty(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.spacing = dp(6)
        self.size_hint_y = None
        self.height = dp(64)
        self.bind(cards=self._rebuild, slots=self._rebuild)

    def _rebuild(self, *args):
        # 属性回调可能早于初始化完成，此时跳过
        if self.canvas is None:
            return
        self.clear_widgets()
        n = self.slots or len(self.cards)
        for i in range(n):
            c = self.cards[i] if i < len(self.cards) else ""
            self.add_widget(PlayCard(card=c))
        self.add_widget(BoxLayout())


# ---------------------------------------------------------------- 翻后分析
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


def postflop_advice(category, draws, board, hole=None):
    """根据成牌类型、听牌与超对情况给出下注建议。

    category 必须是 poker_core 的整数类别号（CAT_*，0-8），
    不是 describe_score 返回的中文名。传错会导致比较运算抛 TypeError，
    因此这里先做显式校验。
    """
    from poker_core import (
        CAT_HIGH_CARD, CAT_PAIR, CAT_TWO_PAIR, CAT_TRIPS, CAT_STRAIGHT,
        CAT_FLUSH, CAT_FULL_HOUSE, CAT_QUADS, CAT_STRAIGHT_FLUSH, RANK_VALUE,
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
        return (
            "持有【顺子及以上】成牌，下大注（约 3/4 池）获取价值。\n"
            "对手的成牌与听牌都会跟注，此时做大底池能最大化期望收益。"
        )

    if category in (CAT_TWO_PAIR, CAT_TRIPS, CAT_FULL_HOUSE, CAT_QUADS):
        return (
            "持有【两对以上】强牌，下大注（约 3/4 池）建池。\n"
            "此时慢玩会损失价值，对手的顶对、听牌都愿意跟注。"
        )

    # ---- 超对（属于成牌，不是听牌）
    if hole and is_overpair(hole, board):
        return (
            "持有【超对】，下注（约 1/2-3/4 池）获取价值。\n"
            "超对通常领先对手的整个范围，从更差的对子与听牌中榨取价值。"
        )

    # ---- 强听牌（半诈唬）
    if draws:
        has_flush_draw = any("同花听牌" in d for d in draws)
        has_oesd = any("两头顺听牌" in d for d in draws)
        if has_flush_draw or has_oesd:
            return (
                "持有【强听牌】（同花或两头顺），建议半诈唬下注（约 1/2-3/4 池）。\n"
                "半诈唬双赢：对手弃牌直接拿下底池；被跟注你仍有约 1/3 概率反超。\n"
                "强听牌比弱成牌更适合下注，因为它同时具备弃牌率与反超潜力。"
            )
        return (
            "持有【弱听牌】（卡顺），建议小注（约 1/3 池）或过牌。\n"
            "卡顺仅有约 4 张出路，弃牌率与反超潜力都不足，不宜投入过多筹码。"
        )

    # ---- 顶对
    if category == CAT_PAIR and hole:
        hole_ranks = [RANK_VALUE[c[0]] for c in hole]
        paired = [r for r in hole_ranks if r in board_ranks]

        if paired and max(paired) == board_high:
            if board_size == 3 and board_high >= RANK_VALUE["Q"]:
                return (
                    "持有【顶对】，但牌面偏高，对手范围中两对以上概率上升。\n"
                    "建议小注（约 1/3 池）：从更差的对子获取价值，"
                    "被加注时以较低成本脱身。"
                )
            return "持有【顶对】，建议下注（约 1/2-3/4 池）获取价值。"
        if paired:
            return (
                "持有【中对或底对】，建议过牌或小注控制底池。\n"
                "这类牌不足以承受大注，也不适合在被跟注时做大底池。"
            )

    # ---- 弱牌
    return (
        "牌力较弱，建议过牌控制底池。\n"
        "用弱牌下注若被跟注或加注会陷入被动；过牌可保留免费看下一张的机会。"
    )


# ---------------------------------------------------------------- 实时识别页
class RealtimeScreen(Screen):
    status_text = StringProperty("摄像头未开启")
    recommendation = StringProperty("")
    rec_detail = StringProperty("")
    is_running = BooleanProperty(False)
    auto_recognition = BooleanProperty(False)
    stats_text = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.app_ref = None
        self.camera = None
        self.rt = None
        self.current_hole = []
        self.current_board = []
        self._build()

    # ---------------------------------------- UI
    def _build(self):
        from kivy.uix.scrollview import ScrollView

        root = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))

        # 标题
        title = Label(
            text="实时牌面识别",
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(19), bold=True,
            color=COLOR_DARK,
            size_hint_y=None, height=dp(34),
        )
        root.add_widget(title)

        # 预览区
        self.preview_wrap = BoxLayout(
            size_hint_y=None, height=dp(230),
            padding=dp(2),
        )
        self.preview = Label(
            text="点击下方「开启摄像头」开始",
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(14),
            color=(0.55, 0.58, 0.63, 1),
            halign="center", valign="middle",
        )
        self.preview.bind(size=lambda *a: setattr(self.preview, "text_size",
                                                  self.preview.size))
        self.preview_wrap.add_widget(self.preview)
        root.add_widget(self.preview_wrap)

        # 摄像头控制
        cam_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        self.btn_cam = Button(
            text="开启摄像头",
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(15), bold=True,
            background_normal="", background_color=COLOR_PRIMARY,
            color=(1, 1, 1, 1),
        )
        self.btn_cam.bind(on_release=self.toggle_camera)
        cam_row.add_widget(self.btn_cam)

        self.btn_snap = Button(
            text="抓拍识别",
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(15), bold=True,
            background_normal="", background_color=(0.35, 0.40, 0.48, 1),
            color=(1, 1, 1, 1),
            disabled=True,
        )
        self.btn_snap.bind(on_release=self.snap_recognize)
        cam_row.add_widget(self.btn_snap)
        root.add_widget(cam_row)

        # 实时开关
        rt_row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        self.btn_auto = Button(
            text="开启实时识别",
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(15), bold=True,
            background_normal="", background_color=(0.30, 0.34, 0.40, 1),
            color=(1, 1, 1, 1),
        )
        self.btn_auto.bind(on_release=self.toggle_auto)
        rt_row.add_widget(self.btn_auto)

        self.btn_edit = Button(
            text="手动输入",
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(15), bold=True,
            background_normal="", background_color=(0.30, 0.34, 0.40, 1),
            color=(1, 1, 1, 1),
        )
        self.btn_edit.bind(on_release=self.manual_input)
        rt_row.add_widget(self.btn_edit)
        root.add_widget(rt_row)

        # 状态
        self.lbl_status = Label(
            text=self.status_text,
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(12),
            color=COLOR_GRAY,
            size_hint_y=None, height=dp(24),
            halign="left",
        )
        self.lbl_status.bind(size=lambda *a: setattr(self.lbl_status, "text_size",
                                                     self.lbl_status.size))
        root.add_widget(self.lbl_status)

        # 滚动区：牌面 + 推荐
        scroll = ScrollView()
        content = BoxLayout(orientation="vertical", spacing=dp(8),
                            size_hint_y=None, padding=(0, dp(4)))
        content.bind(minimum_height=content.setter("height"))

        # 识别到的牌面
        card_box = BoxLayout(orientation="vertical", size_hint_y=None,
                             height=dp(150), spacing=dp(4))
        card_box.add_widget(Label(
            text="识别到的牌面", font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(13), bold=True, color=COLOR_GRAY,
            size_hint_y=None, height=dp(22), halign="left",
        ))
        hole_row = BoxLayout(size_hint_y=None, height=dp(26))
        hole_row.add_widget(Label(
            text="手牌", font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(12), color=COLOR_GRAY, size_hint_x=None, width=dp(48),
        ))
        self.hole_cards = CardRow()
        hole_row.add_widget(self.hole_cards)
        card_box.add_widget(hole_row)

        board_row = BoxLayout(size_hint_y=None, height=dp(26))
        board_row.add_widget(Label(
            text="公共牌", font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(12), color=COLOR_GRAY, size_hint_x=None, width=dp(48),
        ))
        self.board_cards = CardRow()
        board_row.add_widget(self.board_cards)
        card_box.add_widget(board_row)
        card_box.add_widget(BoxLayout())
        content.add_widget(card_box)

        # GTO 推荐
        rec_title = Label(
            text="GTO 推荐", font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(15), bold=True, color=COLOR_PRIMARY,
            size_hint_y=None, height=dp(26), halign="left",
        )
        content.add_widget(rec_title)

        self.lbl_rec = Label(
            text="识别牌面后，这里会显示 GTO 推荐",
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(16), bold=True,
            color=COLOR_GRAY,
            size_hint_y=None, halign="left", valign="top",
        )
        self.lbl_rec.bind(
            size=lambda *a: setattr(self.lbl_rec, "text_size",
                                    (self.lbl_rec.width, None)),
            texture_size=lambda *a: setattr(self.lbl_rec, "height",
                                            self.lbl_rec.texture_size[1] + dp(6)),
        )
        content.add_widget(self.lbl_rec)

        self.lbl_detail = Label(
            text="",
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(13),
            color=COLOR_DARK,
            size_hint_y=None, halign="left", valign="top",
        )
        self.lbl_detail.bind(
            size=lambda *a: setattr(self.lbl_detail, "text_size",
                                    (self.lbl_detail.width, None)),
            texture_size=lambda *a: setattr(self.lbl_detail, "height",
                                            self.lbl_detail.texture_size[1] + dp(6)),
        )
        content.add_widget(self.lbl_detail)

        # 统计
        self.lbl_stats = Label(
            text="", font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(11), color=COLOR_GRAY,
            size_hint_y=None, height=dp(40), halign="left", valign="top",
        )
        self.lbl_stats.bind(size=lambda *a: setattr(self.lbl_stats, "text_size",
                                                    self.lbl_stats.size))
        content.add_widget(self.lbl_stats)

        scroll.add_widget(content)
        root.add_widget(scroll)
        self.add_widget(root)

    # ---------------------------------------- 摄像头
    def toggle_camera(self, *args):
        if self.camera is None:
            self._start_camera()
        else:
            self._stop_camera()

    def _start_camera(self):
        try:
            from kivy.uix.camera import Camera
            cam_idx = self.app_ref.config.get("camera_index", 0)
            self.camera = Camera(
                play=True,
                resolution=(1280, 720),
                index=cam_idx,
            )
            self.preview_wrap.clear_widgets()
            self.preview_wrap.add_widget(self.camera)
            self.btn_cam.text = "关闭摄像头"
            self.btn_cam.background_color = COLOR_RED
            self.btn_snap.disabled = False
            self._set_status("摄像头已开启")

            # 启动帧采集（用于实时识别）
            Clock.schedule_interval(self._grab_frame, 1 / 15)
        except Exception as e:
            self._set_status(f"无法开启摄像头：{e}")
            self.camera = None

    def _stop_camera(self):
        Clock.unschedule(self._grab_frame)
        if self.rt:
            self.rt.set_enabled(False)
        if self.camera is not None:
            self.preview_wrap.clear_widgets()
            self.preview_wrap.add_widget(self.preview)
            self.camera = None
        self.btn_cam.text = "开启摄像头"
        self.btn_cam.background_color = COLOR_PRIMARY
        self.btn_snap.disabled = True
        self.btn_auto.text = "开启实时识别"
        self.btn_auto.background_color = (0.30, 0.34, 0.40, 1)
        self.auto_recognition = False
        self._set_status("摄像头已关闭")

    def _grab_frame(self, dt):
        """定时从摄像头纹理抓取帧，交给实时识别器。"""
        if self.camera is None or self.rt is None:
            return
        if not self.rt.enabled:
            return
        try:
            frame = self._capture_texture()
            if frame is not None:
                self.rt.submit_frame(frame)
                self._update_stats()
        except Exception:
            pass

    def _capture_texture(self):
        """把摄像头纹理转为 numpy 数组（RGB）。"""
        import numpy as np
        cam = self.camera
        if cam is None or cam.texture is None:
            return None
        tex = cam.texture
        w, h = tex.size
        # Kivy 纹理是 RGBA，且上下翻转
        buf = bytes(tex.pixels)
        arr = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4)
        arr = arr[::-1]                       # 翻转
        return np.ascontiguousarray(arr[:, :, :3])

    def snap_recognize(self, *args):
        """抓拍单帧并识别。"""
        if self.camera is None:
            return
        frame = self._capture_texture()
        if frame is None:
            self._set_status("无法抓取画面")
            return
        self._set_status("正在识别…")
        self.btn_snap.disabled = True

        cfg = self.app_ref.config

        def worker():
            try:
                b64 = realtime.frame_to_base64(frame)
                text, _ = recognizer.recognize(b64, cfg)
                cards = recognizer.parse_cards(text)
                Clock.schedule_once(lambda dt: self._on_cards(cards), 0)
            except Exception as e:
                Clock.schedule_once(
                    lambda dt: self._on_error(str(e)), 0)

        threading.Thread(target=worker, daemon=True).start()

    @mainthread
    def _on_cards(self, cards):
        self.btn_snap.disabled = False
        self._apply_cards(cards)

    @mainthread
    def _on_error(self, msg):
        self.btn_snap.disabled = False
        self._set_status(f"识别失败：{msg}")

    def _apply_cards(self, cards):
        """应用识别结果并生成推荐。"""
        hole = [c for c in cards.get("hole_cards", []) if c != "??"]
        board = [c for c in cards.get("board_cards", []) if c != "??"]
        conf = cards.get("confidence", "unknown")
        uncertain = ("??" in cards.get("hole_cards", []) or
                     "??" in cards.get("board_cards", []))

        self.current_hole = hole
        self.current_board = board
        self.hole_cards.cards = hole
        self.board_cards.cards = board

        conf_label = {"high": "高", "medium": "中", "low": "低"}.get(conf, conf)
        note = f"识别置信度：{conf_label}"
        if uncertain:
            note += "（有无法确定的牌，请手动校对）"
        self._set_status(note)

        self._make_recommendation(hole, board, cards.get("hero_position", ""))

    def _make_recommendation(self, hole, board, hero_pos):
        """根据牌面生成 GTO 推荐。"""
        if len(hole) != 2:
            self.lbl_rec.text = "手牌不完整，无法给出推荐"
            self.lbl_rec.color = COLOR_GRAY
            self.lbl_detail.text = "请确保识别到 2 张手牌，或使用「手动输入」。"
            return

        try:
            position = hero_pos if hero_pos in ranges.POSITIONS else "BTN"
            if not board:
                # 翻前
                action, freq, desc = ranges.get_open_action(hole, position)
                notation = __import__("poker_core").hand_notation(*hole)
                if action == ACTION_OPEN:
                    self.lbl_rec.text = f"翻前：开池加注（{notation}）"
                    self.lbl_rec.color = COLOR_GREEN
                    self.lbl_detail.text = (
                        f"{ranges.POSITION_NAMES[position]} 用 {notation} 标准打法是加注入池。\n"
                        f"频率：{desc}\n\n"
                        f"该位置标准范围宽度约 {ranges.range_width(position):.1%}。"
                    )
                else:
                    self.lbl_rec.text = f"翻前：弃牌（{notation}）"
                    self.lbl_rec.color = COLOR_RED
                    self.lbl_detail.text = (
                        f"{notation} 不在 {ranges.POSITION_NAMES[position]} 的开池范围内。\n"
                        f"前面位置弃牌、等待更好机会更有利可图。"
                    )
            else:
                # 翻后
                from poker_core import evaluate_best, describe_score, categorize
                score, best = evaluate_best(hole + board)
                cat_name, detail = describe_score(score)
                cat_num = categorize(score)     # postflop_advice 需要整数类别号
                street = {3: "翻牌", 4: "转牌", 5: "河牌"}.get(len(board), "翻后")

                # 听牌分析：翻后决策中听牌权重极高，必须单独评估
                draws = analyze_draws(hole, board)

                self.lbl_rec.text = f"{street}：最佳牌型【{cat_name}】"
                self.lbl_rec.color = COLOR_PRIMARY

                draw_text = ""
                if draws:
                    draw_text = "听牌：" + "、".join(draws) + "\n"

                # 根据成牌强度与听牌给出建议
                advice = postflop_advice(cat_num, draws, board, hole)

                self.lbl_detail.text = (
                    f"最佳五张：{hand_to_string(best)}\n"
                    f"牌型：{cat_name}（{detail}）\n"
                    f"{draw_text}\n"
                    f"建议：{advice}\n\n"
                    f"翻后决策要点：\n"
                    f"· 强牌（两对以上）→ 下大注获取价值\n"
                    f"· 听牌 → 可考虑半诈唬，兼顾弃牌率与反超\n"
                    f"· 弱牌 → 过牌控制底池，避免被加注"
                )
        except Exception as e:
            self.lbl_rec.text = "无法生成推荐"
            self.lbl_rec.color = COLOR_RED
            self.lbl_detail.text = str(e)

    # ---------------------------------------- 实时识别
    def toggle_auto(self, *args):
        if self.camera is None:
            self._set_status("请先开启摄像头")
            return
        if self.rt is None:
            self.rt = realtime.RealtimeRecognizer(
                config_provider=lambda: self.app_ref.config,
                on_result=self._rt_result,
                on_error=self._rt_error,
                on_status=self._rt_status,
            )
        new_state = not self.auto_recognition
        self.rt.set_enabled(new_state)
        self.auto_recognition = new_state

        if new_state:
            self.btn_auto.text = "关闭实时识别"
            self.btn_auto.background_color = COLOR_GREEN
        else:
            self.btn_auto.text = "开启实时识别"
            self.btn_auto.background_color = (0.30, 0.34, 0.40, 1)

    @mainthread
    def _rt_result(self, cards, frame):
        self._apply_cards(cards)
        self._update_stats()

    @mainthread
    def _rt_error(self, msg):
        self._set_status(f"识别出错：{msg}")
        self._update_stats()

    @mainthread
    def _rt_status(self, msg):
        self._set_status(msg)

    def _update_stats(self):
        if self.rt is None:
            return
        s = self.rt.get_stats()
        self.lbl_stats.text = (
            f"采集 {s['frames']} 帧　识别 {s['recognized']} 次　"
            f"跳过(无变化) {s['skipped_unchanged']}　"
            f"节流 {s['throttled']}　失败 {s['errors']}"
        )

    # ---------------------------------------- 手动输入
    def manual_input(self, *args):
        content = BoxLayout(orientation="vertical", spacing=dp(8),
                            padding=dp(12))

        content.add_widget(Label(
            text="牌面写法：点数(2-9,T,J,Q,K,A) + 花色(s/h/d/c)",
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(12), color=COLOR_GRAY,
            size_hint_y=None, height=dp(24),
        ))
        content.add_widget(Label(
            text="例：As = 黑桃A，Th = 红桃10，2c = 梅花2",
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(12), color=COLOR_GRAY,
            size_hint_y=None, height=dp(24),
        ))

        hole_input = TextInput(
            text=" ".join(self.current_hole),
            hint_text="手牌，如 As Kh",
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(15), multiline=False,
            size_hint_y=None, height=dp(44),
        )
        content.add_widget(hole_input)

        board_input = TextInput(
            text=" ".join(self.current_board),
            hint_text="公共牌（可留空），如 Td 9c 2s",
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(15), multiline=False,
            size_hint_y=None, height=dp(44),
        )
        content.add_widget(board_input)

        pos_spinner = Spinner(
            text="BTN",
            values=("UTG", "HJ", "CO", "BTN", "SB", "BB"),
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(15),
            size_hint_y=None, height=dp(44),
        )
        content.add_widget(pos_spinner)

        btn_row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        btn_ok = Button(
            text="确认",
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(15), bold=True,
            background_normal="", background_color=COLOR_GREEN,
            color=(1, 1, 1, 1),
        )
        btn_cancel = Button(
            text="取消",
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(15), bold=True,
            background_normal="", background_color=(0.55, 0.58, 0.63, 1),
            color=(1, 1, 1, 1),
        )
        btn_row.add_widget(btn_ok)
        btn_row.add_widget(btn_cancel)
        content.add_widget(btn_row)

        popup = Popup(
            title="手动输入牌面",
            title_font=FONT_NAME if _FONT_OK else "Roboto",
            content=content,
            size_hint=(0.9, 0.62),
        )

        def on_ok(*a):
            hole = hole_input.text.split()
            board = board_input.text.split()
            try:
                for c in hole + board:
                    parse_card(c)
            except CardError as e:
                self._set_status(f"牌面格式错误：{e}")
                return
            if len(hole) != 2:
                self._set_status("手牌必须恰好 2 张")
                return
            if len(board) > 5:
                self._set_status("公共牌最多 5 张")
                return
            if len(set(hole + board)) != len(hole + board):
                self._set_status("存在重复的牌")
                return
            popup.dismiss()
            self._apply_cards({
                "hole_cards": hole, "board_cards": board,
                "hero_position": pos_spinner.text,
                "confidence": "high",
            })

        btn_ok.bind(on_release=on_ok)
        btn_cancel.bind(on_release=popup.dismiss)
        popup.open()

    def _set_status(self, text):
        self.status_text = text
        self.lbl_status.text = text

    def on_leave(self, *args):
        """离开页面时停止摄像头，省电。"""
        if self.camera is not None:
            self._stop_camera()


# ---------------------------------------------------------------- 训练页
class TrainScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.app_ref = None
        self.session = stats_mod.Session()
        self.current_q = None
        self.answered = False
        self.option_btns = []
        self._build()
        # 立即生成首题，不依赖 App 的延迟调度（避免出现空题目状态）
        self.next_question()

    def _build(self):
        from kivy.uix.scrollview import ScrollView

        root = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))

        # 顶部：模块选择 + 统计
        top = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        self.module_spinner = Spinner(
            text="混合模式",
            values=("混合模式", "翻前开池", "翻前应对", "翻后决策"),
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(14),
        )
        self.module_spinner.bind(text=self._on_module_change)
        top.add_widget(self.module_spinner)

        self.lbl_score = Label(
            text="0 题",
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(13), bold=True, color=COLOR_PRIMARY,
            size_hint_x=None, width=dp(110),
        )
        top.add_widget(self.lbl_score)
        root.add_widget(top)

        # 滚动内容
        scroll = ScrollView()
        content = BoxLayout(orientation="vertical", spacing=dp(8),
                            size_hint_y=None, padding=(0, dp(4)))
        content.bind(minimum_height=content.setter("height"))

        # 场景
        self.lbl_scene = Label(
            text="", font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(13), bold=True, color=COLOR_PRIMARY,
            size_hint_y=None, halign="left", valign="top",
            padding=(dp(8), dp(8)),
        )
        self.lbl_scene.bind(
            size=lambda *a: setattr(self.lbl_scene, "text_size",
                                    (self.lbl_scene.width, None)),
            texture_size=lambda *a: setattr(self.lbl_scene, "height",
                                            self.lbl_scene.texture_size[1] + dp(12)),
        )
        content.add_widget(self.lbl_scene)

        # 牌面
        hand_row = BoxLayout(size_hint_y=None, height=dp(68), spacing=dp(6))
        hand_row.add_widget(Label(
            text="手牌", font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(12), color=COLOR_GRAY,
            size_hint_x=None, width=dp(46),
        ))
        self.q_hand = CardRow()
        hand_row.add_widget(self.q_hand)
        content.add_widget(hand_row)

        self.board_row_wrap = BoxLayout(size_hint_y=None, height=dp(68),
                                        spacing=dp(6))
        self.board_row_wrap.add_widget(Label(
            text="公共牌", font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(12), color=COLOR_GRAY,
            size_hint_x=None, width=dp(46),
        ))
        self.q_board = CardRow()
        self.board_row_wrap.add_widget(self.q_board)
        content.add_widget(self.board_row_wrap)

        # 题干
        self.lbl_prompt = Label(
            text="", font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(15), color=COLOR_DARK,
            size_hint_y=None, halign="left", valign="top",
        )
        self.lbl_prompt.bind(
            size=lambda *a: setattr(self.lbl_prompt, "text_size",
                                    (self.lbl_prompt.width, None)),
            texture_size=lambda *a: setattr(self.lbl_prompt, "height",
                                            self.lbl_prompt.texture_size[1] + dp(8)),
        )
        content.add_widget(self.lbl_prompt)

        # 选项按钮容器
        self.options_box = BoxLayout(orientation="vertical", spacing=dp(8),
                                     size_hint_y=None)
        self.options_box.bind(minimum_height=self.options_box.setter("height"))
        content.add_widget(self.options_box)

        # 判定与讲解
        self.lbl_verdict = Label(
            text="", font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(15), bold=True, color=COLOR_GRAY,
            size_hint_y=None, halign="left", valign="top",
            padding=(dp(10), dp(10)),
        )
        self.lbl_verdict.bind(
            size=lambda *a: setattr(self.lbl_verdict, "text_size",
                                    (self.lbl_verdict.width, None)),
            texture_size=lambda *a: setattr(self.lbl_verdict, "height",
                                            self.lbl_verdict.texture_size[1] + dp(16)),
        )
        content.add_widget(self.lbl_verdict)

        self.lbl_explain = Label(
            text="", font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(13), color=COLOR_DARK,
            size_hint_y=None, halign="left", valign="top",
        )
        self.lbl_explain.bind(
            size=lambda *a: setattr(self.lbl_explain, "text_size",
                                    (self.lbl_explain.width, None)),
            texture_size=lambda *a: setattr(self.lbl_explain, "height",
                                            self.lbl_explain.texture_size[1] + dp(8)),
        )
        content.add_widget(self.lbl_explain)

        scroll.add_widget(content)
        root.add_widget(scroll)

        # 底部：下一题
        self.btn_next = Button(
            text="下一题",
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(16), bold=True,
            background_normal="", background_color=COLOR_PRIMARY,
            color=(1, 1, 1, 1),
            size_hint_y=None, height=dp(48),
        )
        self.btn_next.bind(on_release=self.next_question)
        root.add_widget(self.btn_next)

        self.add_widget(root)

    def _on_module_change(self, spinner, text):
        mapping = {
            "混合模式": "mixed",
            "翻前开池": "preflop_open",
            "翻前应对": "preflop_vs_open",
            "翻后决策": "postflop",
        }
        self.session = stats_mod.Session()
        self._update_score()
        self.next_question()

    def next_question(self, *args):
        mapping = {
            "混合模式": "mixed",
            "翻前开池": "preflop_open",
            "翻前应对": "preflop_vs_open",
            "翻后决策": "postflop",
        }
        module = mapping.get(self.module_spinner.text, "mixed")
        self.current_q = generate_question(module)
        self.answered = False
        q = self.current_q

        # 场景
        if q.module == "preflop_open":
            scene = f"位置：{ranges.POSITION_NAMES.get(q.position, q.position)}　·　前面全部弃牌"
        elif q.module == "preflop_vs_open":
            scene = (f"对手：{ranges.POSITION_NAMES.get(q.extra.get('opener',''), '')}"
                     f"　·　我方：{ranges.POSITION_NAMES.get(q.position, q.position)}")
        else:
            scene = f"位置：{ranges.POSITION_NAMES.get(q.position, q.position)}　·　对手：大盲"
        self.lbl_scene.text = scene

        # 牌面
        self.q_hand.cards = q.hand_cards
        if q.board_cards:
            self.board_row_wrap.height = dp(68)
            self.q_board.cards = q.board_cards
            self.q_board.opacity = 1
        else:
            self.q_board.cards = []
            self.board_row_wrap.height = 0
            self.q_board.opacity = 0

        self.lbl_prompt.text = q.prompt

        # 选项
        self.options_box.clear_widgets()
        self.option_btns = []
        for i, (value, label) in enumerate(q.options):
            btn = Button(
                text=f"{i+1}.  {label}",
                font_name=FONT_NAME if _FONT_OK else "Roboto",
                font_size=sp(15), bold=True,
                background_normal="",
                background_color=(0.93, 0.95, 0.97, 1),
                color=COLOR_DARK,
                size_hint_y=None, height=dp(50),
                halign="left",
            )
            btn.bind(size=lambda b, *a: setattr(b, "text_size", (b.width - dp(20), None)))
            btn.bind(on_release=lambda b, idx=i: self.answer(idx))
            self.options_box.add_widget(btn)
            self.option_btns.append(btn)

        self.lbl_verdict.text = "请选择你的行动"
        self.lbl_verdict.color = COLOR_GRAY
        self.lbl_verdict.canvas.before.clear()
        self.lbl_explain.text = ""

    def answer(self, index):
        if self.answered:
            return
        q = self.current_q
        if index >= len(q.options):
            return
        self.answered = True

        chosen_value, chosen_label = q.options[index]
        correct_value = q.correct_action
        is_correct = chosen_value == correct_value

        self.session.record(
            module=q.module, correct=is_correct,
            chosen=chosen_label,
            correct_label=ACTION_LABELS.get(correct_value, correct_value),
        )

        # 按钮着色
        for i, btn in enumerate(self.option_btns):
            value = q.options[i][0]
            btn.disabled = True
            if value == correct_value:
                btn.background_color = (0.85, 0.95, 0.88, 1)
                btn.color = (0.11, 0.42, 0.20, 1)
            elif i == index and not is_correct:
                btn.background_color = (0.98, 0.90, 0.89, 1)
                btn.color = (0.62, 0.16, 0.16, 1)

        if is_correct:
            freq_note = ""
            if q.correct_freq < 0.999:
                freq_note = f"（混合策略，标准频率约 {q.correct_freq:.0%}）"
            self.lbl_verdict.text = (
                f"✓ 正确　{ACTION_LABELS.get(correct_value, '')}{freq_note}"
            )
            self.lbl_verdict.color = COLOR_GREEN
        else:
            self.lbl_verdict.text = (
                f"✗ 答错　你选了「{chosen_label}」\n"
                f"GTO 推荐「{ACTION_LABELS.get(correct_value, '')}」"
            )
            self.lbl_verdict.color = COLOR_RED

        # 讲解
        text = q.explanation
        if q.board_cards:
            from poker_core import evaluate_best, describe_score
            score, best = evaluate_best(q.hand_cards + q.board_cards)
            cat, detail = describe_score(score)
            text += (f"\n\n最佳五张：{hand_to_string(best)}\n牌型：{cat}（{detail}）")
        self.lbl_explain.text = text

        self._update_score()

    def _update_score(self):
        s = self.session
        if s.total == 0:
            self.lbl_score.text = "0 题"
        else:
            self.lbl_score.text = f"{s.correct}/{s.total}　{s.accuracy:.0%}"


# ---------------------------------------------------------------- 设置页
class SettingsScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.app_ref = None
        self._build()

    def _build(self):
        from kivy.uix.scrollview import ScrollView

        scroll = ScrollView()
        root = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10),
                         size_hint_y=None)
        root.bind(minimum_height=root.setter("height"))

        title = Label(
            text="设置", font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(19), bold=True, color=COLOR_DARK,
            size_hint_y=None, height=dp(36), halign="left",
        )
        root.add_widget(title)

        # 服务商预设
        root.add_widget(self._section("AI 服务商"))
        self.preset_spinner = Spinner(
            text="智谱 GLM（免费）",
            values=list(recognizer.PRESETS.keys()),
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(15),
            size_hint_y=None, height=dp(46),
        )
        self.preset_spinner.bind(text=self._on_preset)
        root.add_widget(self.preset_spinner)

        root.add_widget(self._section("接口地址"))
        self.base_url_input = TextInput(
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(13), multiline=False,
            size_hint_y=None, height=dp(46),
        )
        root.add_widget(self.base_url_input)

        root.add_widget(self._section("API Key"))
        self.api_key_input = TextInput(
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(13), multiline=False,
            password=True,
            size_hint_y=None, height=dp(46),
        )
        root.add_widget(self.api_key_input)

        root.add_widget(self._section("模型名称"))
        self.model_input = TextInput(
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(13), multiline=False,
            size_hint_y=None, height=dp(46),
        )
        root.add_widget(self.model_input)

        # 识别参数
        root.add_widget(self._section("识别参数"))
        row1 = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        row1.add_widget(Label(
            text="识别间隔(秒)", font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(13), color=COLOR_DARK, size_hint_x=None, width=dp(120),
            halign="left",
        ))
        self.interval_input = TextInput(
            text="3.0", font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(13), multiline=False, input_filter="float",
        )
        row1.add_widget(self.interval_input)
        root.add_widget(row1)

        row2 = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        row2.add_widget(Label(
            text="变化阈值", font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(13), color=COLOR_DARK, size_hint_x=None, width=dp(120),
            halign="left",
        ))
        self.threshold_input = TextInput(
            text="0.08", font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(13), multiline=False, input_filter="float",
        )
        row2.add_widget(self.threshold_input)
        root.add_widget(row2)

        hint = Label(
            text="识别间隔：两次识别的最小时间间隔，越大越省 API 费用。\n"
                 "变化阈值：画面变化超过该比例才送识别（0.08 较敏感）。",
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(11), color=COLOR_GRAY,
            size_hint_y=None, halign="left", valign="top",
        )
        hint.bind(size=lambda *a: setattr(hint, "text_size", (hint.width, None)))
        hint.bind(texture_size=lambda *a: setattr(hint, "height",
                                                  hint.texture_size[1] + dp(8)))
        root.add_widget(hint)

        # 保存按钮
        btn_save = Button(
            text="保存设置",
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(16), bold=True,
            background_normal="", background_color=COLOR_GREEN,
            color=(1, 1, 1, 1),
            size_hint_y=None, height=dp(50),
        )
        btn_save.bind(on_release=self.save)
        root.add_widget(btn_save)

        # 免责声明
        warn = Label(
            text="⚠ 本工具用于学习与训练。GTO 推荐基于内置范围表，"
                 "识别结果需人工校对。请勿用于真实牌局的实时决策，"
                 "多数赛事规则禁止此类工具。",
            font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(11), color=COLOR_AMBER,
            size_hint_y=None, halign="left", valign="top",
        )
        warn.bind(size=lambda *a: setattr(warn, "text_size", (warn.width, None)))
        warn.bind(texture_size=lambda *a: setattr(warn, "height",
                                                  warn.texture_size[1] + dp(10)))
        root.add_widget(warn)

        scroll.add_widget(root)
        self.add_widget(scroll)

    def _section(self, text):
        lbl = Label(
            text=text, font_name=FONT_NAME if _FONT_OK else "Roboto",
            font_size=sp(14), bold=True, color=COLOR_PRIMARY,
            size_hint_y=None, height=dp(28), halign="left", valign="bottom",
        )
        lbl.bind(size=lambda *a: setattr(lbl, "text_size", (lbl.width, None)))
        return lbl

    def _on_preset(self, spinner, text):
        preset = recognizer.PRESETS.get(text)
        if preset and text != "自定义":
            self.base_url_input.text = preset["base_url"]
            self.model_input.text = preset["model"]

    def load_config(self):
        cfg = self.app_ref.config
        self.preset_spinner.text = cfg.get("preset", "智谱 GLM（免费）")
        self.base_url_input.text = cfg.get("base_url", "")
        self.api_key_input.text = cfg.get("api_key", "")
        self.model_input.text = cfg.get("model", "")
        self.interval_input.text = str(cfg.get("capture_interval", 3.0))
        self.threshold_input.text = str(cfg.get("confidence_threshold", 0.08))

    def save(self, *args):
        def to_float(text, default):
            try:
                return float(text)
            except (ValueError, TypeError):
                return default

        cfg = self.app_ref.config
        cfg["preset"] = self.preset_spinner.text
        cfg["base_url"] = self.base_url_input.text.strip()
        cfg["api_key"] = self.api_key_input.text.strip()
        cfg["model"] = self.model_input.text.strip()
        cfg["capture_interval"] = max(1.0, to_float(self.interval_input.text, 3.0))
        cfg["confidence_threshold"] = min(
            1.0, max(0.01, to_float(self.threshold_input.text, 0.08))
        )

        ok, msg = cfg_mod.save_config(cfg)
        if ok:
            self._toast("设置已保存")
        else:
            self._toast(f"保存失败：{msg}")

    def _toast(self, text):
        popup = Popup(
            title="提示",
            title_font=FONT_NAME if _FONT_OK else "Roboto",
            content=Label(
                text=text, font_name=FONT_NAME if _FONT_OK else "Roboto",
                font_size=sp(15),
            ),
            size_hint=(0.7, 0.25),
        )
        popup.open()
        Clock.schedule_once(lambda dt: popup.dismiss(), 1.4)


# ---------------------------------------------------------------- App
class GTOTrainerApp(App):
    font_ok = BooleanProperty(_FONT_OK)

    def build(self):
        self.title = "GTO 助手"
        self.config = cfg_mod.load_config()
        self.font_ok = _FONT_OK

        Builder.load_string(KV)

        sm = ScreenManager()
        self.realtime_screen = RealtimeScreen(name="realtime")
        self.realtime_screen.app_ref = self
        self.train_screen = TrainScreen(name="train")
        self.train_screen.app_ref = self
        self.settings_screen = SettingsScreen(name="settings")
        self.settings_screen.app_ref = self

        sm.add_widget(self.realtime_screen)
        sm.add_widget(self.train_screen)
        sm.add_widget(self.settings_screen)

        # 底部导航
        nav = BoxLayout(size_hint_y=None, height=dp(54), spacing=dp(1))
        tabs = [
            ("实时识别", "realtime"),
            ("训练", "train"),
            ("设置", "settings"),
        ]
        self.nav_buttons = {}
        for label, name in tabs:
            btn = Button(
                text=label,
                font_name=FONT_NAME if _FONT_OK else "Roboto",
                font_size=sp(14), bold=True,
                background_normal="",
                background_color=COLOR_CARD_BG,
                color=COLOR_GRAY,
            )
            btn.bind(on_release=lambda b, n=name: self.switch_tab(n))
            nav.add_widget(btn)
            self.nav_buttons[name] = btn

        root = BoxLayout(orientation="vertical")
        root.add_widget(sm)
        root.add_widget(nav)
        self.sm = sm

        Clock.schedule_once(lambda dt: self._on_start(), 0.3)
        return root

    def _on_start(self):
        self.switch_tab("realtime")
        # 训练页已在 __init__ 中生成首题，这里只需确保有题
        if self.train_screen.current_q is None:
            self.train_screen.next_question()
        self.settings_screen.load_config()
        if not _FONT_OK:
            self.realtime_screen._set_status(
                "提示：未找到中文字体，界面中文可能显示异常"
            )

    def switch_tab(self, name):
        self.sm.current = name
        for n, btn in self.nav_buttons.items():
            if n == name:
                btn.background_color = (0.93, 0.95, 0.99, 1)
                btn.color = COLOR_PRIMARY
            else:
                btn.background_color = COLOR_CARD_BG
                btn.color = COLOR_GRAY
        if name == "settings":
            self.settings_screen.load_config()

    def on_stop(self):
        """退出时保存训练成绩并释放摄像头。"""
        try:
            stats_mod.save_session(self.train_screen.session)
        except Exception:
            pass
        try:
            self.realtime_screen.on_leave()
        except Exception:
            pass


if __name__ == "__main__":
    GTOTrainerApp().run()
