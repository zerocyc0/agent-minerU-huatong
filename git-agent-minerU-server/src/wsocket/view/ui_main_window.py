# encoding: utf-8
# @file: ui_main_window.py
# @desc: 主窗口 UI 布局（手工编写，等价于 Qt Designer 生成的 Ui_MainWindow）
from PyQt5 import QtCore, QtWidgets


class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        MainWindow.setWindowTitle("华通线缆文件分析智能体服务（服务运行中请勿随意关闭！！！）")
        MainWindow.resize(820, 600)

        self.central = QtWidgets.QWidget(MainWindow)
        self.central.setObjectName("centralwidget")
        self.grid = QtWidgets.QGridLayout(self.central)

        # ---- 服务参数区 ----
        self.group_param = QtWidgets.QGroupBox("服务参数", self.central)
        self.form = QtWidgets.QFormLayout(self.group_param)
        self.line_host = QtWidgets.QLineEdit("127.0.0.1")
        self.spin_port = QtWidgets.QSpinBox()
        self.spin_port.setRange(1, 65535)
        self.spin_port.setValue(8765)
        self.form.addRow("监听地址:", self.line_host)
        self.form.addRow("监听端口:", self.spin_port)
        self.grid.addWidget(self.group_param, 0, 0, 1, 2)

        # ---- 控制按钮区 ----
        self.group_ctrl = QtWidgets.QGroupBox("控制", self.central)
        self.hbox_ctrl = QtWidgets.QHBoxLayout(self.group_ctrl)
        self.btn_start = QtWidgets.QPushButton("启动服务", self.group_ctrl)
        self.btn_stop = QPushButton_disabled(self.group_ctrl, "停止服务")
        self.btn_clear_log = QtWidgets.QPushButton("清空日志", self.group_ctrl)
        self.hbox_ctrl.addWidget(self.btn_start)
        self.hbox_ctrl.addWidget(self.btn_stop)
        self.hbox_ctrl.addWidget(self.btn_clear_log)
        self.grid.addWidget(self.group_ctrl, 1, 0, 1, 2)

        # ---- 状态区 ----
        self.group_status = QtWidgets.QGroupBox("运行状态", self.central)
        self.hbox_status = QtWidgets.QHBoxLayout(self.group_status)
        self.lbl_status_text = QtWidgets.QLabel("状态: 未运行", self.group_status)
        self.lbl_status_text.setStyleSheet("color: gray; font-weight: bold;")
        self.lbl_client_count = QtWidgets.QLabel("在线客户端: 0", self.group_status)
        self.hbox_status.addWidget(self.lbl_status_text)
        self.hbox_status.addStretch(1)
        self.hbox_status.addWidget(self.lbl_client_count)
        self.grid.addWidget(self.group_status, 2, 0, 1, 2)

        # ---- 日志区 ----
        self.group_log = QtWidgets.QGroupBox("运行日志", self.central)
        self.vbox_log = QtWidgets.QVBoxLayout(self.group_log)
        self.text_log = QtWidgets.QTextEdit(self.group_log)
        self.text_log.setReadOnly(True)
        self.lbl_tip = QtWidgets.QLabel("（日志每日零点自动清除）", self.group_log)
        self.lbl_tip.setStyleSheet("color: gray;")
        self.vbox_log.addWidget(self.text_log)
        self.vbox_log.addWidget(self.lbl_tip)
        self.grid.addWidget(self.group_log, 3, 0, 1, 2)

        self.grid.setRowStretch(3, 1)
        MainWindow.setCentralWidget(self.central)

        # 初始按钮状态
        self.btn_stop.setEnabled(False)


def QPushButton_disabled(parent, text):
    btn = QtWidgets.QPushButton(text, parent)
    btn.setEnabled(False)
    return btn
