"""
Author: Lin。
Date: 2026-11-10 18:32:53

Windows DPI 兼容层。

两个职责：
1. 开启进程 DPI 感知：Win10 1703+ 用 Per-Monitor V2，Win8.1 用 shcore，Win7 只剩
   Vista 时代的 SetProcessDPIAware。必须在创建 Tk 之前调用。
2. 给 CustomTkinter 的 ScalingTracker 兜底：它无条件调用
   shcore.SetProcessDpiAwareness / shcore.GetDpiForMonitor，而 Win7 根本没有
   shcore.dll，创建窗口时会直接抛 OSError。这里换成 GDI 的 GetDeviceCaps。
"""
import ctypes


def shcore_available():
    """shcore.dll 是否存在（Win8.1+）。Win7 上访问 ctypes.windll.shcore 会抛 OSError"""
    try:
        ctypes.windll.shcore
        return True
    except OSError:
        return False


def system_dpi_scaling():
    """系统 DPI 缩放比（96 DPI → 1.0，120 DPI → 1.25）。Win7 可用的 GDI 取值路径"""
    try:
        u = ctypes.windll.user32
        g = ctypes.windll.gdi32
        hdc = u.GetDC(0)
        if not hdc:
            return 1.0
        try:
            dpi = g.GetDeviceCaps(hdc, 88)      # LOGPIXELSX
        finally:
            u.ReleaseDC(0, hdc)
        return (dpi or 96) / 96
    except Exception:
        return 1.0


def apply_dpi_awareness():
    """逐级回退开启 DPI 感知，返回命中的级别：v2 / per-monitor / system / none

    Win7 没有 SetProcessDpiAwarenessContext，也没有 shcore，
    只有 SetProcessDPIAware（Vista+），不补这一级就会静默退化成 DPI 不感知。
    """
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(
                ctypes.c_void_p(-4)):          # PER_MONITOR_AWARE_V2
            return "v2"
    except Exception:
        pass
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:   # S_OK
            return "per-monitor"
    except Exception:
        pass
    try:
        if ctypes.windll.user32.SetProcessDPIAware():
            return "system"
    except Exception:
        pass
    return "none"


def patch_ctk_scaling():
    """shcore 缺失时替换 CTk 的缩放实现，让界面仍按系统 DPI 缩放

    必须在 ctk.CTk() 之前调用。返回是否打了补丁。
    依赖 CTk 的内部类路径，升级 CTk 后需重新确认（见 docs/win7-support-plan.md）。
    """
    if shcore_available():
        return False
    from customtkinter.windows.widgets.scaling.scaling_tracker import (
        ScalingTracker,
    )
    # 进程级 DPI 感知已由 apply_dpi_awareness 处理，这里不能再让 CTk 碰 shcore
    ScalingTracker.activate_high_dpi_awareness = classmethod(lambda cls: None)
    ScalingTracker.get_window_dpi_scaling = classmethod(
        lambda cls, window: system_dpi_scaling())
    return True
