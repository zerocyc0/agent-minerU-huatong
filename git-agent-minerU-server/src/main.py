# encoding: utf-8
# @author: yuxh
# @file: main.py
# @desc: 程序入口。基于 PyQt5 的 WebSocket 文件分析 Agent（MinerU + DeepSeek V4）
import os
import sys

# ============================================================================
# OpenBLAS / OMP / MKL 线程限制：必须在 import numpy/torch（MinerU、pdfplumber 等）
# 之前设置。MinerU 底层 torch+OpenBLAS 会为每个 CPU 线程预分配内存，Windows 内存
# 受限环境下线程数过多会报：
#   "OpenBLAS error: Memory allocation still failed after 10 retries, giving up."
# 限制为单线程可大幅降低内存峰值。
# ============================================================================
for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
             "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_var, "1")

# 将 src/ 加入 sys.path，保证包内导入在任意 cwd 下均可用
_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

from wsocket.view.ws_main_app import MainWindow
from PyQt5.QtWidgets import QApplication

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
