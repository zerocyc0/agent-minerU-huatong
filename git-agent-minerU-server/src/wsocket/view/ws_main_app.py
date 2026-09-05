# encoding: utf-8
# @file: ws_main_app.py
# @desc: 主窗口逻辑，绑定 WebSocket 处理器信号与按钮事件，含每日零点日志自动清除
import sys
import time
from PyQt5.QtWidgets import QApplication, QMainWindow
from PyQt5.QtCore import QTimer, QDateTime, QTime
from wsocket.view.ui_main_window import Ui_MainWindow
from wsocket.websocket_handler import WebSocketHandler


class MainWindow(QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        # 初始化 WebSocket 处理器
        self.ws_handler = WebSocketHandler()

        # 绑定信号
        self.ws_handler.log_signal.connect(self.append_log)
        self.ws_handler.status_signal.connect(self.update_status_label)
        self.ws_handler.client_count_signal.connect(self.update_client_label)

        # 绑定按钮事件
        self.btn_start.clicked.connect(self.on_start)
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_clear_log.clicked.connect(self.on_clear_log)

        # 每日零点自动清除日志的定时器（单次触发，触发后重新调度到次日零点）
        self.midnight_timer = QTimer(self)
        self.midnight_timer.setSingleShot(True)
        self.midnight_timer.timeout.connect(self.on_midnight_clear)
        self._schedule_midnight_clear()

    def _schedule_midnight_clear(self):
        """计算距下一个零点的毫秒数并启动定时器"""
        now = QDateTime.currentDateTime()
        next_midnight = QDateTime(now.date().addDays(1), QTime(0, 0, 0))
        self.midnight_timer.start(max(1000, now.msecsTo(next_midnight)))

    def on_midnight_clear(self):
        self.text_log.clear()
        self.append_log("每日零点日志已自动清除，明日零点将再次清除")
        self._schedule_midnight_clear()

    def on_clear_log(self):
        self.text_log.clear()
        self.append_log("日志已手动清除")

    def append_log(self, message):
        self.text_log.append(message)
        scrollbar = self.text_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def update_status_label(self, text):
        self.lbl_status_text.setText(f"状态: {text}")
        if "运行中" in text:
            self.lbl_status_text.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.lbl_status_text.setStyleSheet("color: gray; font-weight: bold;")

    def update_client_label(self, count):
        self.lbl_client_count.setText(f"在线客户端: {count}")

    def on_start(self):
        host = self.line_host.text().strip() or "0.0.0.0"
        port = self.spin_port.value()

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.line_host.setEnabled(False)
        self.spin_port.setEnabled(False)

        self.ws_handler.start_server(host, port)

    def on_stop(self):
        self.ws_handler.stop_server()

        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.line_host.setEnabled(True)
        self.spin_port.setEnabled(True)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
