# -*- coding: utf-8 -*-
"""摄像头录入面板（集成到训练器）。

功能：
  - 打开摄像头预览
  - 拍照并送 AI 识别牌面
  - 识别结果填入表单，用户校对后生成题目

设计原则：**识别结果必须人工确认**。识别只是省去打字的麻烦，
不承担正确性责任。这是与"实时对局辅助"的根本区别。
"""

import base64
import json

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QGroupBox, QMessageBox, QLineEdit, QTextEdit, QDialog, QFormLayout,
    QDialogButtonBox, QCheckBox,
)

import camera
from poker_core import parse_card, CardError, hand_to_string


class CaptureWorker(QThread):
    """后台线程：抓帧 + 调模型识别。"""

    finished_ok = pyqtSignal(list, list, str, str)   # 手牌, 公共牌, 置信, 说明
    failed = pyqtSignal(str)

    def __init__(self, frame, config):
        super().__init__()
        self.frame = frame
        self.config = config

    def run(self):
        try:
            import recognizer
            b64 = camera.frame_to_base64(self.frame)
            text, _ = recognizer.recognize(
                b64, {**self.config, "prompt": camera.CARD_RECOGNITION_PROMPT},
                image_format="JPEG",
            )
            hole, board, conf, notes = camera.parse_card_response(text)
            self.finished_ok.emit(hole, board, conf, notes)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class CameraPanel(QWidget):
    """摄像头预览 + 识别面板。"""

    cards_confirmed = pyqtSignal(list, list)   # 确认后的 手牌, 公共牌

    def __init__(self, config_provider, parent=None):
        super().__init__(parent)
        self.config_provider = config_provider
        self.stream = None
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_frame)
        self.latest_frame = None
        self.worker = None
        self._build_ui()
        self._check_availability()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 顶部控制
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("摄像头："))
        self.cam_combo = QComboBox()
        self.cam_combo.setMinimumWidth(110)
        ctrl.addWidget(self.cam_combo)

        self.btn_refresh = QPushButton("扫描")
        self.btn_refresh.clicked.connect(self._refresh_cameras)
        ctrl.addWidget(self.btn_refresh)

        self.btn_toggle = QPushButton("打开预览")
        self.btn_toggle.setMinimumWidth(100)
        self.btn_toggle.clicked.connect(self._toggle_stream)
        ctrl.addWidget(self.btn_toggle)
        ctrl.addStretch()
        layout.addLayout(ctrl)

        # 预览区
        self.preview = QLabel("摄像头未开启")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(300)
        self.preview.setStyleSheet(
            "background:#1e2228; color:#8892a0; border-radius:8px; font-size:13px;"
        )
        layout.addWidget(self.preview, stretch=1)

        # 抓拍按钮
        self.btn_capture = QPushButton("📸  抓拍并识别牌面")
        self.btn_capture.setMinimumHeight(44)
        self.btn_capture.setEnabled(False)
        self.btn_capture.clicked.connect(self._capture_and_recognize)
        layout.addWidget(self.btn_capture)

        # 识别结果
        result_box = QGroupBox("识别结果（需人工校对）")
        result_layout = QVBoxLayout(result_box)

        form = QFormLayout()
        self.hole_edit = QLineEdit()
        self.hole_edit.setPlaceholderText("如 As Kh")
        form.addRow("手牌：", self.hole_edit)

        self.board_edit = QLineEdit()
        self.board_edit.setPlaceholderText("如 Td 9c 2s（可留空）")
        form.addRow("公共牌：", self.board_edit)
        result_layout.addLayout(form)

        self.notes_label = QLabel("")
        self.notes_label.setWordWrap(True)
        self.notes_label.setStyleSheet("color:#7a8494; font-size:12px;")
        result_layout.addWidget(self.notes_label)

        btn_row = QHBoxLayout()
        self.btn_apply = QPushButton("确认并生成题目")
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self._apply_cards)
        btn_row.addWidget(self.btn_apply)

        self.btn_clear = QPushButton("清空")
        self.btn_clear.clicked.connect(self._clear_result)
        btn_row.addWidget(self.btn_clear)
        btn_row.addStretch()
        result_layout.addLayout(btn_row)

        self.warn_label = QLabel(
            "⚠ 识别可能出错（如把 K♠ 认成 K♥）。请务必核对后再生成题目。"
        )
        self.warn_label.setWordWrap(True)
        self.warn_label.setStyleSheet("color:#a5601a; font-size:12px;")
        result_layout.addWidget(self.warn_label)

        layout.addWidget(result_box)

    def _check_availability(self):
        if not camera.is_available():
            self.btn_toggle.setEnabled(False)
            self.btn_capture.setEnabled(False)
            self.btn_refresh.setEnabled(False)
            self.preview.setText(camera.unavailable_reason())
            self.preview.setStyleSheet(
                "background:#fdf6ec; color:#a5601a; border-radius:8px; "
                "padding:16px; font-size:13px;"
            )
        else:
            self._refresh_cameras()

    def _refresh_cameras(self):
        self.cam_combo.clear()
        cams = camera.list_cameras()
        if not cams:
            self.cam_combo.addItem("未检测到摄像头", None)
            self.btn_toggle.setEnabled(False)
            return
        for idx in cams:
            self.cam_combo.addItem(f"摄像头 {idx}", idx)
        self.btn_toggle.setEnabled(True)

    def _toggle_stream(self):
        if self.stream is None:
            self._start_stream()
        else:
            self._stop_stream()

    def _start_stream(self):
        idx = self.cam_combo.currentData()
        if idx is None:
            QMessageBox.warning(self, "提示", "没有可用的摄像头")
            return
        try:
            self.stream = camera.CameraStream(idx)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "打开失败", str(e))
            self.stream = None
            return
        self.timer.start(33)     # 约 30fps 预览
        self.btn_toggle.setText("关闭预览")
        self.btn_capture.setEnabled(True)

    def _stop_stream(self):
        self.timer.stop()
        if self.stream is not None:
            self.stream.release()
            self.stream = None
        self.preview.setText("摄像头未开启")
        self.preview.setStyleSheet(
            "background:#1e2228; color:#8892a0; border-radius:8px; font-size:13px;"
        )
        self.btn_toggle.setText("打开预览")
        self.btn_capture.setEnabled(False)
        self.latest_frame = None

    def _update_frame(self):
        if self.stream is None:
            return
        ok, frame = self.stream.read()
        if not ok:
            return
        self.latest_frame = frame
        self._show_frame(frame)

    def _show_frame(self, frame):
        import cv2
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        img = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(img).scaled(
            self.preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview.setPixmap(pix)

    def _capture_and_recognize(self):
        if self.latest_frame is None:
            QMessageBox.information(self, "提示", "请先打开摄像头预览")
            return
        config = self.config_provider()
        if not config.get("api_key") and "localhost" not in config.get("base_url", ""):
            QMessageBox.information(
                self, "提示",
                "识别需要配置 AI 接口。请先在「设置」中填写 API Key。"
            )
            return
        if self.worker is not None and self.worker.isRunning():
            return

        self.btn_capture.setEnabled(False)
        self.btn_capture.setText("识别中…")
        self.notes_label.setText("正在请求模型识别牌面，请稍候…")

        self.worker = CaptureWorker(self.latest_frame.copy(), config)
        self.worker.finished_ok.connect(self._on_recognized)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_recognized(self, hole, board, confidence, notes):
        self.btn_capture.setEnabled(True)
        self.btn_capture.setText("📸  抓拍并识别牌面")

        self.hole_edit.setText(" ".join(hole))
        self.board_edit.setText(" ".join(board))
        conf_label = {"high": "高", "medium": "中", "low": "低"}.get(confidence, confidence)
        self.notes_label.setText(
            f"模型置信度：{conf_label}　{notes}"
        )
        self.btn_apply.setEnabled(True)

        # 低置信度时额外提醒
        if confidence == "low" or "??" in hole or "??" in board:
            self.notes_label.setStyleSheet("color:#a52a2a; font-size:12px;")
            self.notes_label.setText(
                f"⚠ 置信度{conf_label}，存在识别不确定的牌。请仔细核对！{notes}"
            )
        else:
            self.notes_label.setStyleSheet("color:#7a8494; font-size:12px;")

    def _on_failed(self, message):
        self.btn_capture.setEnabled(True)
        self.btn_capture.setText("📸  抓拍并识别牌面")
        self.notes_label.setText(f"识别失败：{message}")
        self.notes_label.setStyleSheet("color:#a52a2a; font-size:12px;")
        QMessageBox.critical(self, "识别失败", message)

    def _clear_result(self):
        self.hole_edit.clear()
        self.board_edit.clear()
        self.notes_label.clear()
        self.btn_apply.setEnabled(False)

    def _apply_cards(self):
        """校验并确认牌面。"""
        hole = self.hole_edit.text().split()
        board = self.board_edit.text().split()

        # 校验
        try:
            for c in hole + board:
                parse_card(c)
        except CardError as e:
            QMessageBox.warning(self, "牌面格式错误", str(e))
            return

        if len(hole) != 2:
            QMessageBox.warning(self, "牌面错误", "手牌必须恰好 2 张")
            return
        if len(board) > 5:
            QMessageBox.warning(self, "牌面错误", "公共牌最多 5 张")
            return
        if len(set(hole + board)) != len(hole + board):
            QMessageBox.warning(self, "牌面错误", "存在重复的牌")
            return

        self.cards_confirmed.emit(hole, board)

    def shutdown(self):
        self.timer.stop()
        if self.stream is not None:
            self.stream.release()
            self.stream = None


class ManualEntryDialog(QDialog):
    """手动输入牌面对话框（无摄像头时的备选）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("手动输入牌面")
        self.setMinimumWidth(400)
        self.result_cards = None

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.hole_edit = QLineEdit()
        self.hole_edit.setPlaceholderText("如 As Kh")
        form.addRow("手牌（2 张）：", self.hole_edit)

        self.board_edit = QLineEdit()
        self.board_edit.setPlaceholderText("如 Td 9c 2s（可留空）")
        form.addRow("公共牌（0-5 张）：", self.board_edit)

        layout.addLayout(form)

        hint = QLabel(
            "牌面写法：点数(2-9,T,J,Q,K,A) + 花色(s黑桃/h红桃/d方块/c梅花)\n"
            "例如：As = 黑桃A，Th = 红桃10，2c = 梅花2"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#7a8494; font-size:12px;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate(self):
        hole = self.hole_edit.text().split()
        board = self.board_edit.text().split()
        try:
            for c in hole + board:
                parse_card(c)
        except CardError as e:
            QMessageBox.warning(self, "格式错误", str(e))
            return
        if len(hole) != 2:
            QMessageBox.warning(self, "错误", "手牌必须恰好 2 张")
            return
        if len(board) > 5:
            QMessageBox.warning(self, "错误", "公共牌最多 5 张")
            return
        if len(set(hole + board)) != len(hole + board):
            QMessageBox.warning(self, "错误", "存在重复的牌")
            return
        self.result_cards = (hole, board)
        self.accept()


if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication
    app = QApplication(sys.argv)

    def cfg():
        return {"api_key": "", "base_url": "", "model": ""}

    w = CameraPanel(cfg)
    w.show()
    print("摄像头面板构建 OK")
    print("可用性：", camera.is_available())
    w.shutdown()
