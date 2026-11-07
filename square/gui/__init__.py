"""界面层：Tk / CustomTkinter。只依赖 core，不被 core 依赖。"""
from .app import SquareApp, run

__all__ = ["SquareApp", "run"]
