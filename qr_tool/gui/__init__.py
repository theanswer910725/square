"""界面层：Tk / CustomTkinter。只依赖 core，不被 core 依赖。"""
from .app import QRToolApp, run

__all__ = ["QRToolApp", "run"]
