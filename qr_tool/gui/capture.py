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


def monitor_at_cursor():
    """鼠标所在显示器的物理矩形 (x, y, w, h)，取不到时退回主显示器"""
    u = ctypes.windll.user32

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", RECT),
                    ("rcWork", RECT), ("dwFlags", ctypes.c_ulong)]

    pt = POINT()
    u.GetCursorPos(ctypes.byref(pt))
    hmon = u.MonitorFromPoint(pt, 2)          # MONITOR_DEFAULTTONEAREST
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not u.GetMonitorInfoW(hmon, ctypes.byref(info)):
        return (0, 0, u.GetSystemMetrics(0), u.GetSystemMetrics(1))
    r = info.rcMonitor
    return (r.left, r.top, r.right - r.left, r.bottom - r.top)


def tk_to_phys_scale(root):
    """Tk 坐标 → 屏幕物理像素的换算系数（DPI 感知下通常为 1）"""
    sw = root.winfo_screenwidth()
    phys = ctypes.windll.user32.GetSystemMetrics(0)
    if not sw or not phys:
        return 1.0
    k = phys / sw
    return 1.0 if abs(k - 1.0) < 0.02 else k


def capture_region(app, owner=None):
    """区域截图：全屏遮罩拖拽框选 → 进剪贴板 → 解码器还原

    owner: 触发截图的大图预览弹窗，只用来给提示框定父窗口。
    框选期间弹窗保持显示不隐藏——用户要截的正是它显示的大图；
    遮罩半透明覆盖其上，遮罩销毁后 150ms 再抓屏，抓到的就是未变暗的画面。
    """
    vx, vy, vw, vh = virtual_screen()
    if vw <= 0 or vh <= 0:
        messagebox.showerror("错误", "无法获取屏幕尺寸",
                             parent=owner or app.root)
        return
    k = tk_to_phys_scale(app.root)

    # 上一次补片时可能解除了从属关系（为了让主窗口压到弹窗上面），
    # 这里恢复：遮罩与弹窗的层级要回到「弹窗在主窗口之上」
    if owner is not None and owner.winfo_exists() \
            and owner.transient() != str(app.root):
        owner.transient(app.root)
        owner.lift()

    top = tk.Toplevel(app.root)
    top.overrideredirect(True)
    top.attributes("-topmost", True)
    top.attributes("-alpha", 0.34)
    top.configure(bg="#000000")
    top.geometry(f"{int(vw / k)}x{int(vh / k)}{int(vx / k):+d}{int(vy / k):+d}")

    cv = tk.Canvas(top, bg="#000000", highlightthickness=0,
                   cursor="crosshair")
    cv.pack(fill="both", expand=True)

    # 遮罩按虚拟桌面铺满所有显示器；提示文字要居中在「鼠标所在显示器」上。
    # 若按虚拟桌面宽度居中，多屏时文字会正好压在屏幕接缝处，看起来被裁掉。
    mx, my, mw, mh = monitor_at_cursor()
    hint = cv.create_text(0, 28, text="拖拽框选二维码区域 · Esc / 右键取消",
                          fill="#ffffff", font=("Microsoft YaHei UI", 14))
    bx1, _, bx2, _ = cv.bbox(hint)
    half = (bx2 - bx1) // 2
    left = (mx - vx) / k
    right = left + mw / k
    # 再夹一次，保证整行文字都落在这块显示器内、左右各留 20px
    cx = min(max(left + (right - left) / 2, left + half + 20), right - half - 20)
    cv.coords(hint, cx, 28)

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


def _raise_root_above(owner, root):
    """把主窗口提到大图弹窗之上

    弹窗是主窗口的 owned window，从属关系还在时就永远压在主窗口上面，
    所以先临时解除 transient 再 lift 主窗口；下次从弹窗触发截图时会重新挂回，
    不会留下永久的断裂层级，也不用 -topmost 硬顶。
    """
    if owner is None or not owner.winfo_exists():
        return
    owner.transient("")
    root.lift()
    root.focus_force()


def _close_owner(owner):
    if owner is not None and owner.winfo_exists():
        owner.destroy()


def finish_region(app, px1, py1, px2, py2, owner=None):
    vx, vy, _, _ = virtual_screen()
    try:
        full = ImageGrab.grab(all_screens=True)
    except Exception as e:
        messagebox.showerror("错误", f"截图失败: {e}",
                             parent=owner or app.root)
        return
    # all_screens 的图左上角对应虚拟屏原点 (vx, vy)
    img = full.crop((px1 - vx, py1 - vy, px2 - vx, py2 - vy))

    try:
        copy_image_to_clipboard(img)
    except Exception as e:
        app.status.set(f"写入剪贴板失败: {e}")

    app.seg.set("解码器")
    app._show_page(1)
    outcome = app._scan_image(img)

    if outcome == "ok":
        # 一次收齐：关掉大图弹窗，主窗口回到最前显示还原文本
        _close_owner(owner)
        app.root.lift()
        app.root.focus_force()
    elif outcome == "partial":
        # 分片没收齐：弹窗留着继续补片，但要把主窗口提到它之上，
        # 否则「已收集 x/y · 缺 …」和补图提示会被弹窗挡住
        _raise_root_above(owner, app.root)
    elif outcome == "none":
        messagebox.showinfo("提示", "未识别到二维码，请重新框选",
                            parent=owner or app.root)
