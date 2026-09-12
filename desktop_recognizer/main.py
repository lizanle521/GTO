# -*- coding: utf-8 -*-
"""桌面识别软件 - 主界面。

功能：
  1. 一键截取屏幕（全部显示器 / 指定显示器 / 自定义区域）
  2. 预览截图
  3. 调用多模态大模型识别界面内容
  4. 展示识别结果、复制、保存
  5. 设置面板配置 API Key / 接口地址 / 模型 / 提示词
"""

import sys
import traceback
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QRect, QPoint
from PyQt6.QtGui import QPixmap, QImage, QGuiApplication, QAction, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTextEdit, QComboBox, QSplitter, QGroupBox, QMessageBox,
    QDialog, QFormLayout, QLineEdit, QSpinBox, QDoubleSpinBox, QCheckBox,
    QFileDialog, QStatusBar, QToolBar, QScrollArea, QDialogButtonBox,
)

from config import load_config, save_config
from capture import grab_fullscreen, grab_region, list_monitors, image_to_base64, save_screenshot
from recognizer import recognize, RecognizeError, PRESETS


# ---------------------------------------------------------------- 区域选择控件
class RegionSelector(QWidget):
    """半透明全屏遮罩，鼠标拖拽框选区域。"""

    region_selected = pyqtSignal(QRect)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)

        # 覆盖所有显示器的虚拟桌面范围
        virtual = QRect()
        for screen in QGuiApplication.screens():
            virtual = virtual.united(screen.geometry())
        self.virtual_geometry = virtual
        self.setGeometry(virtual)

        self.start_point = QPoint()
        self.end_point = QPoint()
        self.selecting = False
        self._drag_started = False

    def paintEvent(self, event):
        from PyQt6.QtGui import QPainter, QColor, QPen
        painter = QPainter(self)
        # 半透明黑色遮罩
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))

        # 已在拖拽则绘制清晰选区 + 边框
        if self.selecting:
            rect = QRect(self.start_point, self.end_point).normalized()
            # 恢复选区为透明（露出原屏）
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(rect, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

            pen = QPen(QColor(0, 160, 255), 2)
            painter.setPen(pen)
            painter.drawRect(rect)

            # 尺寸提示
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(rect.x(), max(rect.y() - 6, 14),
                             f"{rect.width()} × {rect.height()}")
        else:
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "拖拽鼠标框选识别区域，按 Esc 取消")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_point = event.position().toPoint()
            self.end_point = self.start_point
            self.selecting = True
            self._drag_started = True
            self.update()

    def mouseMoveEvent(self, event):
        if self.selecting:
            self.end_point = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.selecting:
            self.selecting = False
            rect = QRect(self.start_point, self.end_point).normalized()
            self.close()
            if rect.width() > 5 and rect.height() > 5:
                # 转换为屏幕绝对坐标
                abs_rect = QRect(
                    rect.x() + self.virtual_geometry.x(),
                    rect.y() + self.virtual_geometry.y(),
                    rect.width(),
                    rect.height(),
                )
                self.region_selected.emit(abs_rect)
            else:
                self.region_selected.emit(QRect())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            self.region_selected.emit(QRect())


# ---------------------------------------------------------------- 后台识别线程
class RecognizeWorker(QThread):
    """在后台线程调用模型，避免阻塞界面。"""

    finished_ok = pyqtSignal(str, dict)
    failed = pyqtSignal(str)

    def __init__(self, image_b64, config, image_format="PNG"):
        super().__init__()
        self.image_b64 = image_b64
        self.config = config
        self.image_format = image_format

    def run(self):
        try:
            text, usage = recognize(self.image_b64, self.config, self.image_format)
            self.finished_ok.emit(text, usage or {})
        except RecognizeError as e:
            self.failed.emit(str(e))
        except Exception:  # noqa: BLE001 - 兜底，避免线程静默崩溃
            self.failed.emit("未预期的错误：\n" + traceback.format_exc())


# ---------------------------------------------------------------- 设置对话框
class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = dict(config)
        self.setWindowTitle("设置")
        self.setMinimumWidth(560)
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # 服务商预设
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(PRESETS.keys()))
        self.preset_combo.currentTextChanged.connect(self._apply_preset)
        form.addRow("服务商预设：", self.preset_combo)

        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("https://api.openai.com/v1")
        form.addRow("接口地址：", self.base_url_edit)

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("sk-...")
        # 明文切换
        key_row = QHBoxLayout()
        key_row.addWidget(self.api_key_edit)
        self.show_key_btn = QPushButton("显示")
        self.show_key_btn.setCheckable(True)
        self.show_key_btn.setFixedWidth(56)
        self.show_key_btn.toggled.connect(self._toggle_key_visibility)
        key_row.addWidget(self.show_key_btn)
        key_widget = QWidget()
        key_widget.setLayout(key_row)
        form.addRow("API Key：", key_widget)

        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("gpt-4o-mini")
        form.addRow("模型名称：", self.model_edit)

        self.prompt_edit = QTextEdit()
        self.prompt_edit.setPlaceholderText("请输入识别提示词")
        self.prompt_edit.setFixedHeight(90)
        form.addRow("识别提示词：", self.prompt_edit)

        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(100, 32000)
        self.max_tokens_spin.setSingleStep(100)
        form.addRow("最大输出长度：", self.max_tokens_spin)

        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 2.0)
        self.temp_spin.setSingleStep(0.1)
        form.addRow("随机度 temperature：", self.temp_spin)

        self.save_check = QCheckBox("自动保存截图到本地")
        form.addRow("", self.save_check)

        self.dir_edit = QLineEdit()
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.dir_edit)
        browse_btn = QPushButton("浏览…")
        browse_btn.clicked.connect(self._browse_dir)
        dir_row.addWidget(browse_btn)
        dir_widget = QWidget()
        dir_widget.setLayout(dir_row)
        form.addRow("截图保存目录：", dir_widget)

        layout.addLayout(form)

        hint = QLabel(
            "提示：本软件使用 OpenAI 兼容接口，支持 OpenAI、通义千问、智谱、Kimi、"
            "DeepSeek、本地 Ollama 等。选择预设后仅需填写 API Key。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666; font-size:12px;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _toggle_key_visibility(self, checked):
        self.api_key_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )
        self.show_key_btn.setText("隐藏" if checked else "显示")

    def _apply_preset(self, name):
        preset = PRESETS.get(name)
        if not preset:
            return
        if name == "自定义":
            return
        # 应用预设时保留用户已填的 Key
        self.base_url_edit.setText(preset["base_url"])
        self.model_edit.setText(preset["model"])

    def _browse_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择截图保存目录", self.dir_edit.text())
        if path:
            self.dir_edit.setText(path)

    def _load(self):
        cfg = self.config
        self.base_url_edit.setText(cfg.get("base_url", ""))
        self.api_key_edit.setText(cfg.get("api_key", ""))
        self.model_edit.setText(cfg.get("model", ""))
        self.prompt_edit.setPlainText(cfg.get("prompt", ""))
        self.max_tokens_spin.setValue(int(cfg.get("max_tokens", 1500)))
        self.temp_spin.setValue(float(cfg.get("temperature", 0.3)))
        self.save_check.setChecked(bool(cfg.get("save_screenshots", True)))
        self.dir_edit.setText(cfg.get("screenshot_dir", ""))

        # 反向匹配预设
        for name, preset in PRESETS.items():
            if name == "自定义":
                continue
            if preset["base_url"] == cfg.get("base_url") and preset["model"] == cfg.get("model"):
                self.preset_combo.setCurrentText(name)
                break
        else:
            self.preset_combo.setCurrentText("自定义")

    def get_config(self):
        cfg = dict(self.config)
        cfg.update({
            "base_url": self.base_url_edit.text().strip(),
            "api_key": self.api_key_edit.text().strip(),
            "model": self.model_edit.text().strip(),
            "prompt": self.prompt_edit.toPlainText().strip(),
            "max_tokens": self.max_tokens_spin.value(),
            "temperature": self.temp_spin.value(),
            "save_screenshots": self.save_check.isChecked(),
            "screenshot_dir": self.dir_edit.text().strip(),
        })
        return cfg


# ---------------------------------------------------------------- 主窗口
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.current_image = None       # PIL.Image
        self.monitors = []
        self.worker = None

        self.setWindowTitle("桌面识别 - Desktop Recognizer")
        self.resize(1180, 760)
        self._build_ui()
        self._build_toolbar()
        self._refresh_monitors()
        self._update_status()

    # ------------------------------------------------ UI 构建
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 8)
        root.setSpacing(10)

        # ---- 顶部操作条
        top = QHBoxLayout()
        self.btn_capture = QPushButton("📷  截取屏幕")
        self.btn_capture.setMinimumHeight(38)
        self.btn_capture.clicked.connect(self.capture_full)
        top.addWidget(self.btn_capture)

        self.btn_region = QPushButton("🔲  框选区域")
        self.btn_region.setMinimumHeight(38)
        self.btn_region.clicked.connect(self.capture_region)
        top.addWidget(self.btn_region)

        top.addWidget(QLabel("显示器："))
        self.monitor_combo = QComboBox()
        self.monitor_combo.setMinimumWidth(150)
        self.monitor_combo.setMinimumHeight(38)
        top.addWidget(self.monitor_combo)

        self.btn_refresh = QPushButton("刷新")
        self.btn_refresh.clicked.connect(self._refresh_monitors)
        top.addWidget(self.btn_refresh)

        top.addStretch()

        self.btn_recognize = QPushButton("🚀  开始识别")
        self.btn_recognize.setMinimumHeight(38)
        self.btn_recognize.setMinimumWidth(130)
        self.btn_recognize.setEnabled(False)
        self.btn_recognize.clicked.connect(self.start_recognize)
        top.addWidget(self.btn_recognize)

        root.addLayout(top)

        # ---- 主区域：左图右文
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左：截图预览
        left_box = QGroupBox("截图预览")
        left_layout = QVBoxLayout(left_box)
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_label = QLabel("尚未截图\n\n点击上方「截取屏幕」或「框选区域」开始")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setStyleSheet("color:#888; background:#f7f7f7; border-radius:6px;")
        self.preview_scroll.setWidget(self.preview_label)
        left_layout.addWidget(self.preview_scroll)

        # 右：识别结果
        right_box = QGroupBox("识别结果")
        right_layout = QVBoxLayout(right_box)
        self.result_edit = QTextEdit()
        self.result_edit.setPlaceholderText("识别结果将显示在这里…")
        self.result_edit.setReadOnly(False)
        right_layout.addWidget(self.result_edit)

        result_btns = QHBoxLayout()
        self.btn_copy = QPushButton("复制结果")
        self.btn_copy.clicked.connect(self.copy_result)
        result_btns.addWidget(self.btn_copy)

        self.btn_save_txt = QPushButton("保存为文本")
        self.btn_save_txt.clicked.connect(self.save_result)
        result_btns.addWidget(self.btn_save_txt)

        self.btn_clear = QPushButton("清空")
        self.btn_clear.clicked.connect(self.clear_result)
        result_btns.addWidget(self.btn_clear)

        result_btns.addStretch()
        right_layout.addLayout(result_btns)

        splitter.addWidget(left_box)
        splitter.addWidget(right_box)
        splitter.setSizes([620, 560])
        root.addWidget(splitter, stretch=1)

        self.setStatusBar(QStatusBar())

    def _build_toolbar(self):
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        act_capture = QAction("截取屏幕", self)
        act_capture.setShortcut(QKeySequence("Ctrl+N"))
        act_capture.triggered.connect(self.capture_full)
        toolbar.addAction(act_capture)

        act_region = QAction("框选区域", self)
        act_region.setShortcut(QKeySequence("Ctrl+R"))
        act_region.triggered.connect(self.capture_region)
        toolbar.addAction(act_region)

        act_recognize = QAction("开始识别", self)
        act_recognize.setShortcut(QKeySequence("F5"))
        act_recognize.triggered.connect(self.start_recognize)
        toolbar.addAction(act_recognize)

        toolbar.addSeparator()

        act_settings = QAction("设置", self)
        act_settings.setShortcut(QKeySequence("Ctrl+,"))
        act_settings.triggered.connect(self.open_settings)
        toolbar.addAction(act_settings)

        act_about = QAction("关于", self)
        act_about.triggered.connect(self.show_about)
        toolbar.addAction(act_about)

    # ------------------------------------------------ 显示器
    def _refresh_monitors(self):
        try:
            self.monitors = list_monitors()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "错误", f"获取显示器信息失败：{e}")
            return
        self.monitor_combo.clear()
        for mon in self.monitors:
            self.monitor_combo.addItem(
                f"{mon['label']} ({mon['width']}×{mon['height']})", mon["index"]
            )

    # ------------------------------------------------ 截图
    def capture_full(self):
        index = self.monitor_combo.currentData()
        if index is None:
            index = 0
        try:
            self._set_busy(True, "正在截图…")
            self.current_image = grab_fullscreen(index)
        except Exception as e:  # noqa: BLE001
            self._set_busy(False)
            QMessageBox.critical(self, "截图失败", str(e))
            return
        self._on_image_ready(f"已截取 {self.current_image.width}×{self.current_image.height} 画面")
        self._set_busy(False)

    def capture_region(self):
        self._selector = RegionSelector()
        self._selector.region_selected.connect(self._on_region_selected)
        self.showMinimized()
        self._selector.showFullScreen()
        self._selector.raise_()
        self._selector.activateWindow()

    def _on_region_selected(self, rect: QRect):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        if rect.isNull() or rect.width() <= 0:
            self._update_status("已取消区域选择")
            return
        try:
            img = grab_region(rect.x(), rect.y(), rect.width(), rect.height())
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "截图失败", str(e))
            return
        self.current_image = img
        self._on_image_ready(f"已截取区域 {img.width}×{img.height}")

    def _on_image_ready(self, message):
        """截图完成后更新预览。"""
        qimg = QImage(
            self.current_image.tobytes(),
            self.current_image.width,
            self.current_image.height,
            self.current_image.width * 3,
            QImage.Format.Format_RGB888,
        )
        pixmap = QPixmap.fromImage(qimg)
        self.preview_label.setPixmap(
            pixmap.scaled(
                self.preview_scroll.viewport().size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.preview_label.setStyleSheet("background:#f7f7f7; border-radius:6px;")
        self.preview_label.adjustSize()
        self.btn_recognize.setEnabled(True)

        if self.config.get("save_screenshots"):
            try:
                path = save_screenshot(self.current_image, self.config.get("screenshot_dir"))
                message += f"　| 已保存：{path}"
            except Exception as e:  # noqa: BLE001
                message += f"　| 保存失败：{e}"
        self._update_status(message)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.current_image is not None:
            self._on_image_ready_preview_only()

    def _on_image_ready_preview_only(self):
        qimg = QImage(
            self.current_image.tobytes(),
            self.current_image.width,
            self.current_image.height,
            self.current_image.width * 3,
            QImage.Format.Format_RGB888,
        )
        pixmap = QPixmap.fromImage(qimg)
        self.preview_label.setPixmap(
            pixmap.scaled(
                self.preview_scroll.viewport().size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    # ------------------------------------------------ 识别
    def start_recognize(self):
        if self.current_image is None:
            QMessageBox.information(self, "提示", "请先截取屏幕")
            return
        if not self.config.get("api_key") and "localhost" not in self.config.get("base_url", ""):
            ret = QMessageBox.question(
                self, "尚未配置",
                "还没有配置 API Key，是否现在打开设置？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ret == QMessageBox.StandardButton.Yes:
                self.open_settings()
            return
        if self.worker is not None and self.worker.isRunning():
            return

        try:
            image_b64 = image_to_base64(self.current_image, max_width=1920)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "错误", f"图像处理失败：{e}")
            return

        self.result_edit.setPlainText("")
        self._set_busy(True, "正在请求模型识别，请稍候…")

        self.worker = RecognizeWorker(image_b64, self.config)
        self.worker.finished_ok.connect(self._on_recognize_ok)
        self.worker.failed.connect(self._on_recognize_failed)
        self.worker.start()

    def _on_recognize_ok(self, text, usage):
        self._set_busy(False)
        self.result_edit.setPlainText(text)
        info = "识别完成"
        if usage:
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            total = usage.get("total_tokens")
            parts = []
            if prompt_tokens is not None:
                parts.append(f"输入 {prompt_tokens}")
            if completion_tokens is not None:
                parts.append(f"输出 {completion_tokens}")
            if total is not None:
                parts.append(f"共计 {total} tokens")
            if parts:
                info += "　| " + "，".join(parts)
        self._update_status(info)

    def _on_recognize_failed(self, message):
        self._set_busy(False)
        self.result_edit.setPlainText(f"❌ 识别失败\n\n{message}")
        self._update_status("识别失败")
        QMessageBox.critical(self, "识别失败", message)

    # ------------------------------------------------ 结果操作
    def copy_result(self):
        text = self.result_edit.toPlainText()
        if not text:
            return
        QApplication.clipboard().setText(text)
        self._update_status("已复制到剪贴板")

    def save_result(self):
        text = self.result_edit.toPlainText()
        if not text:
            QMessageBox.information(self, "提示", "没有可保存的内容")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存识别结果", str(Path.home() / "识别结果.txt"), "文本文件 (*.txt)"
        )
        if path:
            try:
                Path(path).write_text(text, encoding="utf-8")
                self._update_status(f"已保存：{path}")
            except OSError as e:
                QMessageBox.critical(self, "保存失败", str(e))

    def clear_result(self):
        self.result_edit.clear()
        self._update_status("已清空结果")

    # ------------------------------------------------ 设置 / 关于
    def open_settings(self):
        dialog = SettingsDialog(self.config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.config = dialog.get_config()
            save_config(self.config)
            self._update_status("设置已保存")

    def show_about(self):
        QMessageBox.about(
            self, "关于",
            "<h3>桌面识别 Desktop Recognizer</h3>"
            "<p>截图并使用多模态大模型识别软件界面内容。</p>"
            "<p><b>快捷键：</b><br>"
            "Ctrl+N 截取屏幕　Ctrl+R 框选区域　F5 开始识别</p>"
            "<p style='color:#888'>基于 PyQt6 + OpenAI 兼容接口</p>",
        )

    # ------------------------------------------------ 辅助
    def _set_busy(self, busy, message=None):
        self.btn_recognize.setEnabled(not busy and self.current_image is not None)
        self.btn_capture.setEnabled(not busy)
        self.btn_region.setEnabled(not busy)
        if busy:
            self.btn_recognize.setText("识别中…")
            QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        else:
            self.btn_recognize.setText("🚀  开始识别")
            QApplication.restoreOverrideCursor()
        if message:
            self._update_status(message)

    def _update_status(self, message=""):
        key_state = "已配置" if self.config.get("api_key") else "未配置"
        model = self.config.get("model") or "未设置模型"
        base = f"模型：{model}　|　API Key：{key_state}"
        if message:
            base = f"{message}　||　{base}"
        self.statusBar().showMessage(base)

    def closeEvent(self, event):
        if self.worker is not None and self.worker.isRunning():
            self.worker.terminate()
            self.worker.wait(2000)
        super().closeEvent(event)


def main():
    # 高 DPI 适配
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Desktop Recognizer")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
