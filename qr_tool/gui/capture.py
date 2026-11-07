"""区域截图：全屏遮罩框选 → 真实屏幕像素 → 剪贴板 → 解码器。"""
import ctypes
import tkinter as tk
from tkinter import messagebox

from PIL import ImageGrab

from ..core.clipboard import copy_image_to_clipboard


def virtual_screen():
    """虚拟桌面矩形（物理像素，可跨多显示器，含负坐标）"""
    u = ctypes.windll.user32
    return (u.GetSystemMetrics(76), u.GetSystemMetrics(77),
            u.GetSystemMetrics(78), u.GetSystemMetrics(79))


def tk_to_phys_scale(root):
    """Tk 坐标 → 屏幕物理像素的换算系数（DPI 感知下通常为 1）"""
    sw = root.winfo_screenwidth()
    phys = ctypes.windll.user32.GetSystemMetrics(0)
    if not sw or not phys:
        return 1.0
    k = phys / sw
    return 1.0 if abs(k - 1.0) < 0.02 else k


def restore_owner(owner):
    """恢复框选期间临时隐藏的大图弹窗，并保持它在主窗口之上"""
    if owner is None or not owner.winfo_exists():
        return
    owner.deiconify()
    owner.lift()


def capture_region(app, owner=None):
    """区域截图：全屏遮罩拖拽框选 → 进剪贴板 → 解码器还原

    owner: 触发截图的大图预览弹窗。框选/抓屏期间临时隐藏，
    结束后恢复——既不让它挡住所框区域，也不让它被截进图里。
    """
    vx, vy, vw, vh = virtual_screen()
    if vw <= 0 or vh <= 0:
        messagebox.showerror("错误", "无法获取屏幕尺寸",
                             parent=owner or app.root)
        return
    k = tk_to_phys_scale(app.root)

    if owner is not None:
        owner.withdraw()

    top = tk.Toplevel(app.root)
    top.overrideredirect(True)
    top.attributes("-topmost", True)
    top.attributes("-alpha", 0.34)
    top.configure(bg="#000000")
    top.geometry(f"{int(vw / k)}x{int(vh / k)}{int(vx / k):+d}{int(vy / k):+d}")

    cv = tk.Canvas(top, bg="#000000", highlightthickness=0,
                   cursor="crosshair")
    cv.pack(fill="both", expand=True)
    cv.create_text(int(vw / k) // 2, 28,
                   text="拖拽框选二维码区域 · Esc / 右键取消",
                   fill="#ffffff", font=("Microsoft YaHei UI", 14))

    state = {"sx": None, "sy": None, "closed": False}

    def on_press(e):
        if state["closed"]:
            return
        state["sx"], state["sy"] = e.x, e.y
        cv.delete("sel")

    def on_move(e):
        if state["closed"] or state["sx"] is None:
            return
        cv.delete("sel")
        cv.create_rectangle(state["sx"], state["sy"], e.x, e.y,
                            outline="#ffffff", width=2, dash=(4, 3),
                            tags="sel")
        cv.create_text(e.x + 12, e.y + 12, anchor="nw",
                       text=f"{int(abs(e.x - state['sx']) * k)}"
                            f"×{int(abs(e.y - state['sy']) * k)}",
                       fill="#ffffff", font=("Microsoft YaHei UI", 12),
                       tags="sel")

    def cancel(_=None):
        # Esc / 右键同一条取消路径；closed 保证连点多次也只关一次
        if state["closed"]:
            return
        state["closed"] = True
        top.destroy()          # 遮罩销毁，绑定随控件一起释放，不留监听
        restore_owner(owner)
        app.status.set("已取消截图")

    def on_release(e):
        # 拖拽中右键取消后，左键松开不能再触发截图
        if state["closed"] or state["sx"] is None:
            return
        state["closed"] = True
        x1, x2 = sorted((state["sx"], e.x))
        y1, y2 = sorted((state["sy"], e.y))
        px1 = int(round(vx + x1 * k))
        py1 = int(round(vy + y1 * k))
        px2 = int(round(vx + x2 * k))
        py2 = int(round(vy + y2 * k))
        top.destroy()
        if px2 - px1 < 24 or py2 - py1 < 24:
            restore_owner(owner)
            messagebox.showinfo("提示", "框选区域太小，请重新框选",
                                parent=owner or app.root)
            return
        # 遮罩已销毁，留一点时间给桌面重绘，再抓真实像素
        app.root.after(150, lambda: finish_region(
            app, px1, py1, px2, py2, owner))

    cv.bind("<ButtonPress-1>", on_press)
    cv.bind("<B1-Motion>", on_move)
    cv.bind("<ButtonRelease-1>", on_release)
    cv.bind("<Button-3>", cancel)      # 右键等价 Esc；拖拽中也能取消
    top.bind("<Escape>", cancel)
    top.focus_force()
    cv.focus_set()


def finish_region(app, px1, py1, px2, py2, owner=None):
    vx, vy, _, _ = virtual_screen()
    try:
        full = ImageGrab.grab(all_screens=True)
    except Exception as e:
        restore_owner(owner)
        messagebox.showerror("错误", f"截图失败: {e}",
                             parent=owner or app.root)
        return
    # 像素已经抓完，这时才把弹窗放回来，保证它没被截进图里
    restore_owner(owner)
    # all_screens 的图左上角对应虚拟屏原点 (vx, vy)
    img = full.crop((px1 - vx, py1 - vy, px2 - vx, py2 - vy))

    try:
        copy_image_to_clipboard(img)
    except Exception as e:
        app.status.set(f"写入剪贴板失败: {e}")

    app.seg.set("解码器")
    app._show_page(1)
    if app._scan_image(img) == 0:
        messagebox.showinfo("提示", "未识别到二维码，请重新框选",
                            parent=owner or app.root)
