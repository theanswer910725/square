"""Windows 剪贴板写入（纯平台逻辑，不依赖 Tk）。"""
import ctypes
import io

CF_DIB = 8


def copy_image_to_clipboard(img):
    """把 PIL 图片真正写进 Windows 剪贴板（CF_DIB）。

    Tk 的 clipboard_append(format="image") 并不会产生系统认识的图片格式，
    ImageGrab.grabclipboard() 读不到，所以这里直接走 Win32。
    """
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "BMP")
    dib = buf.getvalue()[14:]          # 去掉 14 字节 BMP 文件头

    u = ctypes.windll.user32
    k = ctypes.windll.kernel32
    k.GlobalAlloc.restype = ctypes.c_void_p
    k.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [ctypes.c_void_p]
    k.GlobalUnlock.argtypes = [ctypes.c_void_p]
    u.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]

    for _ in range(10):                # 剪贴板可能被其它程序占用，重试
        if u.OpenClipboard(None):
            break
        import time
        time.sleep(0.05)
    else:
        raise RuntimeError("剪贴板被其它程序占用")

    try:
        u.EmptyClipboard()
        h = k.GlobalAlloc(0x0002, len(dib))       # GMEM_MOVEABLE
        p = k.GlobalLock(h)
        ctypes.memmove(p, dib, len(dib))
        k.GlobalUnlock(h)
        u.SetClipboardData(CF_DIB, h)
    finally:
        u.CloseClipboard()
