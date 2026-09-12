# -*- coding: utf-8 -*-
"""GTO 训练器界面（PyQt6）。

主界面分四个区域：
  左侧：题目卡片（牌面图形化展示 + 题干）
  右侧：选项按钮区 + 讲解面板
  顶部：模块选择、开始/下一题
  底部：正确率统计
"""

import random
import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QPainterPath, QAction, QKeySequence,
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QTextEdit, QGroupBox, QFrame, QSizePolicy,
    QMessageBox, QStatusBar, QToolBar, QScrollArea, QProgressBar, QSplitter,
)

from poker_core import parse_card, hand_to_string, RANK_VALUE
from trainer import (
    generate_question, ACTION_LABELS,
    ACTION_OPEN, ACTION_FOLD, ACTION_3BET, ACTION_CALL,
    ACTION_CHECK, ACTION_BET_SMALL, ACTION_BET_BIG,
)
import stats


# ---------------------------------------------------------------- 牌面控件
class CardWidget(QFrame):
    """单张扑克牌的图形化展示。"""

    WIDTH = 68
    HEIGHT = 96

    def __init__(self, card=None, face_down=False, parent=None):
        super().__init__(parent)
        self.card = card
        self.face_down = face_down
        self.setFixedSize(self.WIDTH, self.HEIGHT)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(1, 1, -1, -1)
        radius = 8

        path = QPainterPath()
        path.addRoundedRect(float(rect.x()), float(rect.y()),
                            float(rect.width()), float(rect.height()),
                            float(radius), float(radius))
        painter.fillPath(path, QColor("#ffffff"))
        pen = QPen(QColor("#c8ccd4"), 1.5)
        painter.setPen(pen)
        painter.drawPath(path)

        # 空位
        if self.card is None:
            painter.setPen(QPen(QColor("#dde1e7"), 1.5, Qt.PenStyle.DashLine))
            painter.drawPath(path)
            return

        if self.face_down:
            painter.fillPath(path, QColor("#3a6ea5"))
            painter.setPen(QPen(QColor("#2a5580"), 2))
            painter.drawPath(path)
            painter.setPen(QColor("#ffffff"))
            f = QFont("Segoe UI", 22)
            painter.setFont(f)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "?")
            return

        rank, suit = parse_card(self.card)
        is_red = suit in ("h", "d")
        color = QColor("#d62828") if is_red else QColor("#1a1a1a")
        suit_symbol = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}[suit]

        # 左上角点数与花色
        painter.setPen(color)
        f = QFont("Segoe UI", 15, QFont.Weight.Bold)
        painter.setFont(f)
        painter.drawText(rect.adjusted(7, 4, 0, 0),
                         Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, rank)
        f2 = QFont("Segoe UI", 12)
        painter.setFont(f2)
        painter.drawText(rect.adjusted(8, 22, 0, 0),
                         Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft, suit_symbol)

        # 中央大花色
        f3 = QFont("Segoe UI", 30)
        painter.setFont(f3)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, suit_symbol)

        # 右下角（旋转 180 度）
        painter.save()
        painter.translate(rect.center())
        painter.rotate(180)
        painter.translate(-rect.center())
        painter.setPen(color)
        f4 = QFont("Segoe UI", 13, QFont.Weight.Bold)
        painter.setFont(f4)
        painter.drawText(rect.adjusted(0, 0, -7, -4),
                         Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight, rank)
        painter.restore()


class HandDisplay(QWidget):
    """展示一组牌（手牌或公共牌）。"""

    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self.title = title
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(
            "color:#5a6472; font-size:12px; font-weight:600; letter-spacing:0.5px;"
        )
        self.title_label.setVisible(bool(title))
        layout.addWidget(self.title_label)

        self.cards_row = QHBoxLayout()
        self.cards_row.setSpacing(8)
        self.cards_row.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(self.cards_row)

        self.card_widgets = []

    def set_cards(self, cards, max_slots=None):
        """更新显示的牌。max_slots 用于公共牌占位。"""
        while self.cards_row.count():
            item = self.cards_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.card_widgets = []

        n = max_slots if max_slots is not None else len(cards)
        for i in range(n):
            card = cards[i] if i < len(cards) else None
            w = CardWidget(card)
            self.cards_row.addWidget(w)
            self.card_widgets.append(w)
        self.cards_row.addStretch()


# ---------------------------------------------------------------- 主窗口
class TrainerWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_question = None
        self.answered = False
        self.session = stats.Session()
        self.rng = random.Random()

        self.setWindowTitle("GTO 训练器 - 德州扑克翻前/翻后决策")
        self.resize(1240, 820)
        self._build_ui()
        self._build_toolbar()
        self._new_question()

    # ------------------------------------------------ UI
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        central.setStyleSheet("""
            QWidget#central { background: #f4f6f9; }
            QGroupBox {
                background: #ffffff; border: 1px solid #e2e6ec;
                border-radius: 10px; margin-top: 12px; padding-top: 10px;
                font-weight: 600; color: #2a3240;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 14px; padding: 0 6px;
                color: #2a3240;
            }
        """)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 10, 14, 8)
        root.setSpacing(12)

        # ---- 顶部控制条
        top = QHBoxLayout()
        top.addWidget(QLabel("训练模块："))
        self.module_combo = QComboBox()
        self.module_combo.addItem("混合模式（推荐）", "mixed")
        self.module_combo.addItem("翻前开池决策", "preflop_open")
        self.module_combo.addItem("翻前应对开池", "preflop_vs_open")
        self.module_combo.addItem("翻后下注决策", "postflop")
        self.module_combo.setMinimumHeight(34)
        self.module_combo.setMinimumWidth(190)
        self.module_combo.currentIndexChanged.connect(self._on_module_changed)
        top.addWidget(self.module_combo)

        top.addSpacing(16)
        self.btn_new = QPushButton("下一题")
        self.btn_new.setMinimumHeight(34)
        self.btn_new.setMinimumWidth(100)
        self.btn_new.clicked.connect(self._new_question)
        top.addWidget(self.btn_new)

        top.addStretch()

        self.stats_label = QLabel()
        self.stats_label.setStyleSheet(
            "color:#2a3240; font-size:13px; font-weight:600; "
            "background:#ffffff; border:1px solid #e2e6ec; border-radius:8px; "
            "padding:6px 14px;"
        )
        top.addWidget(self.stats_label)
        root.addLayout(top)

        # ---- 主体：左题右解
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # -------- 左：题目区
        left = QGroupBox("题目")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(18, 18, 18, 18)
        left_layout.setSpacing(16)

        # 场景标签（位置等）
        self.scene_label = QLabel()
        self.scene_label.setStyleSheet(
            "background:#eef4fd; color:#1a5fb4; border-radius:6px; "
            "padding:8px 14px; font-size:13px; font-weight:600;"
        )
        self.scene_label.setWordWrap(True)
        left_layout.addWidget(self.scene_label)

        # 手牌
        self.hand_display = HandDisplay("我的手牌")
        left_layout.addWidget(self.hand_display)

        # 公共牌
        self.board_display = HandDisplay("公共牌")
        left_layout.addWidget(self.board_display)

        left_layout.addSpacing(6)

        self.prompt_label = QLabel()
        self.prompt_label.setWordWrap(True)
        self.prompt_label.setStyleSheet(
            "color:#2a3240; font-size:15px; line-height:170%;"
        )
        left_layout.addWidget(self.prompt_label)

        left_layout.addStretch()

        # 选项按钮
        self.options_group = QGroupBox("你的选择")
        self.options_layout = QVBoxLayout(self.options_group)
        self.options_layout.setSpacing(9)
        self.option_buttons = []
        left_layout.addWidget(self.options_group)

        # -------- 右：结果区
        right = QGroupBox("结果与讲解")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(18, 18, 18, 18)
        right_layout.setSpacing(12)

        self.verdict_label = QLabel("请先作答")
        self.verdict_label.setStyleSheet(
            "background:#f0f2f5; color:#7a8494; border-radius:8px; "
            "padding:14px; font-size:16px; font-weight:700;"
        )
        self.verdict_label.setWordWrap(True)
        self.verdict_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(self.verdict_label)

        self.explanation_view = QTextEdit()
        self.explanation_view.setReadOnly(True)
        self.explanation_view.setPlaceholderText(
            "作答后这里会显示 GTO 讲解：为什么这样打、背后的逻辑是什么。"
        )
        self.explanation_view.setStyleSheet(
            "QTextEdit { background:#fbfcfd; border:1px solid #e8ecf2; "
            "border-radius:8px; padding:12px; color:#2a3240; font-size:14px; }"
        )
        right_layout.addWidget(self.explanation_view, stretch=1)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([640, 580])
        root.addWidget(splitter, stretch=1)

        # ---- 进度条
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setStyleSheet("""
            QProgressBar { background:#e6eaf0; border:none; border-radius:3px; }
            QProgressBar::chunk { background:#1a5fb4; border-radius:3px; }
        """)
        root.addWidget(self.progress)

        self.setStatusBar(QStatusBar())
        self._update_stats_display()

    def _build_toolbar(self):
        tb = QToolBar("主工具栏")
        tb.setMovable(False)
        self.addToolBar(tb)

        act_new = QAction("下一题", self)
        act_new.setShortcut(QKeySequence("Space"))
        act_new.triggered.connect(self._new_question)
        tb.addAction(act_new)

        tb.addSeparator()

        for i, key in enumerate(["1", "2", "3"], start=1):
            act = QAction(f"选项 {i}", self)
            act.setShortcut(QKeySequence(str(i)))
            act.triggered.connect(lambda checked=False, idx=i - 1: self._pick(idx))
            tb.addAction(act)

        tb.addSeparator()
        act_stat = QAction("训练统计", self)
        act_stat.triggered.connect(self._show_stats)
        tb.addAction(act_stat)

        act_about = QAction("说明", self)
        act_about.triggered.connect(self._show_about)
        tb.addAction(act_about)

    # ------------------------------------------------ 出题
    def _on_module_changed(self):
        self.session = stats.Session()
        self._update_stats_display()
        self._new_question()

    def _new_question(self):
        module = self.module_combo.currentData()
        self.current_question = generate_question(module, self.rng)
        self.answered = False

        q = self.current_question

        # 场景
        scene_parts = []
        if q.module == "preflop_open":
            scene_parts.append(f"位置：{ranges_name(q.position)}")
            scene_parts.append("前面全部弃牌")
        elif q.module == "preflop_vs_open":
            scene_parts.append(f"对手位置：{ranges_name(q.extra.get('opener', ''))}")
            scene_parts.append(f"我方位置：{ranges_name(q.position)}")
        else:
            scene_parts.append(f"位置：{ranges_name(q.position)}")
            scene_parts.append(f"对手：大盲位")
        self.scene_label.setText("　·　".join(scene_parts))

        # 牌面
        self.hand_display.set_cards(q.hand_cards)
        if q.board_cards:
            self.board_display.set_cards(q.board_cards)
            self.board_display.setVisible(True)
        else:
            self.board_display.set_cards([])
            self.board_display.setVisible(False)

        # 题干
        self.prompt_label.setText(q.prompt)

        # 选项按钮
        while self.options_layout.count():
            item = self.options_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.option_buttons = []
        for i, (value, label) in enumerate(q.options):
            btn = QPushButton(f"{i + 1}.　{label}")
            btn.setMinimumHeight(46)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet("""
                QPushButton {
                    background:#ffffff; border:2px solid #d5dce6; border-radius:8px;
                    color:#2a3240; font-size:14px; font-weight:600; text-align:left;
                    padding-left:18px;
                }
                QPushButton:hover { border-color:#1a5fb4; background:#f7faff; }
                QPushButton:disabled { color:#8a94a4; }
            """)
            btn.clicked.connect(lambda checked=False, idx=i: self._pick(idx))
            self.options_layout.addWidget(btn)
            self.option_buttons.append(btn)

        self.verdict_label.setText("请先作答")
        self.verdict_label.setStyleSheet(
            "background:#f0f2f5; color:#7a8494; border-radius:8px; "
            "padding:14px; font-size:16px; font-weight:700;"
        )
        self.explanation_view.clear()
        self.progress.setValue(0)

        self._update_status(f"新题目已生成（{self._module_name()}）")

    def _pick(self, index):
        if self.answered:
            return
        q = self.current_question
        if index >= len(q.options):
            return

        chosen_value, chosen_label = q.options[index]
        correct_value = q.correct_action
        is_correct = (chosen_value == correct_value)
        self.answered = True

        # 记录成绩
        self.session.record(
            module=q.module,
            correct=is_correct,
            chosen=chosen_label,
            correct_label=ACTION_LABELS.get(correct_value, correct_value),
        )

        # 按钮着色
        for i, btn in enumerate(self.option_buttons):
            value = q.options[i][0]
            btn.setEnabled(False)
            if value == correct_value:
                btn.setStyleSheet("""
                    QPushButton {
                        background:#e7f6ec; border:2px solid #2f9e44; border-radius:8px;
                        color:#1b6b32; font-size:14px; font-weight:700; text-align:left;
                        padding-left:18px;
                    }
                """)
            elif i == index and not is_correct:
                btn.setStyleSheet("""
                    QPushButton {
                        background:#fdeceb; border:2px solid #d64545; border-radius:8px;
                        color:#a52a2a; font-size:14px; font-weight:700; text-align:left;
                        padding-left:18px;
                    }
                """)

        # 判定
        if is_correct:
            freq_note = ""
            if q.correct_freq < 0.999:
                freq_note = f"（这是混合策略，标准频率约 {q.correct_freq:.0%}）"
            self.verdict_label.setText(f"✓ 正确　{ACTION_LABELS.get(correct_value, '')}{freq_note}")
            self.verdict_label.setStyleSheet(
                "background:#e7f6ec; color:#1b6b32; border-radius:8px; "
                "padding:14px; font-size:16px; font-weight:700;"
            )
        else:
            self.verdict_label.setText(
                f"✗ 答错了　你选了「{chosen_label}」，"
                f"GTO 推荐「{ACTION_LABELS.get(correct_value, '')}」"
            )
            self.verdict_label.setStyleSheet(
                "background:#fdeceb; color:#a52a2a; border-radius:8px; "
                "padding:14px; font-size:16px; font-weight:700;"
            )

        # 讲解
        parts = [q.explanation]
        if q.board_cards:
            from poker_core import evaluate_best, describe_score
            score, best = evaluate_best(q.hand_cards + q.board_cards)
            cat, detail = describe_score(score)
            parts.append(
                f"\n\n——————\n最佳五张组合：{hand_to_string(best)}\n"
                f"牌型：{cat}（{detail}）"
            )
        self.explanation_view.setPlainText("\n".join(parts))
        self.progress.setValue(100)

        self._update_stats_display()
        self._update_status(
            f"本题{'答对' if is_correct else '答错'}　→　"
            f"正确答案：{ACTION_LABELS.get(correct_value, '')}　（按空格进入下一题）"
        )

    # ------------------------------------------------ 统计
    def _update_stats_display(self):
        s = self.session
        if s.total == 0:
            self.stats_label.setText("本次训练：0 题")
        else:
            self.stats_label.setText(
                f"本次训练：{s.correct}/{s.total} 题　正确率 {s.accuracy:.0%}"
            )

    def _show_stats(self):
        s = self.session
        if s.total == 0:
            QMessageBox.information(self, "训练统计", "还没有作答记录。")
            return
        lines = [f"<h3>本次训练统计</h3>",
                 f"<p>总题数：<b>{s.total}</b>　"
                 f"答对：<b>{s.correct}</b>　"
                 f"正确率：<b>{s.accuracy:.1%}</b></p>"]
        lines.append("<p><b>分模块表现：</b></p><ul>")
        for module, (c, t) in sorted(s.by_module.items()):
            lines.append(
                f"<li>{_MODULE_NAMES.get(module, module)}：{c}/{t} "
                f"（{c / t:.0%}）</li>"
            )
        lines.append("</ul>")

        weak = s.weakest_module()
        if weak and weak[1] < 0.7:
            lines.append(
                f"<p style='color:#a52a2a'><b>建议：</b>"
                f"{_MODULE_NAMES.get(weak[0], weak[0])} 模块正确率仅 {weak[1]:.0%}，"
                f"建议专门练习该模块。</p>"
            )
        QMessageBox.information(self, "训练统计", "".join(lines))

    # ------------------------------------------------ 辅助
    def _module_name(self):
        return self.module_combo.currentText()

    def _update_status(self, message=""):
        base = f"模块：{self._module_name()}"
        if message:
            base = f"{message}　||　{base}"
        self.statusBar().showMessage(base)

    def _show_about(self):
        QMessageBox.about(
            self, "关于 GTO 训练器",
            "<h3>GTO 训练器</h3>"
            "<p>德州扑克翻前与翻后决策训练工具，用于建立 GTO 直觉。</p>"
            "<p><b>训练模块：</b><br>"
            "· 翻前开池：不同位置该用什么范围加注<br>"
            "· 翻前应对开池：该 3-Bet、跟注还是弃牌<br>"
            "· 翻后下注：大注、小注还是过牌</p>"
            "<p><b>快捷键：</b>空格 下一题　1/2/3 选择选项</p>"
            "<p style='color:#7a8494; font-size:12px'>"
            "注意：范围数据为教学用近似值，深层分析请使用专业求解器。</p>"
        )


_MODULE_NAMES = {
    "preflop_open": "翻前开池",
    "preflop_vs_open": "翻前应对开池",
    "postflop": "翻后下注",
}


def ranges_name(position):
    try:
        import ranges
        return ranges.POSITION_NAMES.get(position, position)
    except Exception:
        return position


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("GTO Trainer")
    w = TrainerWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
