"""大图预览弹窗（缩放 + 滚动条按视口动态显隐）。"""
import tkinter as tk

import customtkinter as ctk
from PIL import Image, ImageTk

from .theme import (ACCENT, ACCENT_HOVER, BG, BORDER, BTN, BTN_HOVER,
                    ON_ACCENT, RADIUS, SCROLL_THUMB, SCROLL_THUMB_HOVER,
                    SURFACE, TEXT, TRACK)
from .widgets import set_window_icon


def open_preview_popup(app):
    """弹出大图窗口，带缩放条"""
    win = ctk.CTkToplevel(app.root)
    set_window_icon(win)
    win.title("二维码大图预览")
    # 设为 root 的从属窗口：Windows 上 owned window 始终压在父窗口之上
    win.transient(app.root)
    pw = min(760, win.winfo_screenwidth() - 60)
    ph = min(620, win.winfo_screenheight() - 60)
    win.geometry(f"{pw}x{ph}")
    # 工具条完整排布所需的最小宽度：再窄会压缩按钮并截断文字
    win.minsize(500, 1)
    win.configure(fg_color=BG)
    win.grid_columnconfigure(0, weight=1)
    win.grid_rowconfigure(1, weight=1)

    puzzle = app._preview_puzzle

    # 工具条
    bar = ctk.CTkFrame(win, fg_color="transparent")
    bar.grid(row=0, column=0, sticky="ew", padx=10, pady=8)

    # 与工具条上的百分比、按钮文字同色，避免比次要文字更浅而读不清
    ctk.CTkLabel(bar, text="缩放", font=app.f_sm,
                 text_color=TEXT).pack(side="left")
    zoom_var = tk.DoubleVar(value=1.0)
    pct_var = tk.StringVar(value="100%")

    SB_W, SB_H = 16, 16   # 滚动条厚度(12) + 与画布的间距(4)

    # 缩放后的图片尺寸与 PhotoImage（留引用防止被回收）
    img_state = {"w": 0, "h": 0, "photo": None, "vbar": False, "hbar": False}

    def layout():
        """按视口大小决定两条滚动条显隐，并重排图片（不重新缩放图片）"""
        w, h = img_state["w"], img_state["h"]
        photo = img_state["photo"]
        if photo is None:
            return
        # 基准取 canvas_frame 自身的尺寸：它由窗口大小决定，
        # 不受滚动条显隐影响，所以显隐不会反过来改变判定、不会来回抖
        fw = canvas_frame.winfo_width()
        fh = canvas_frame.winfo_height()
        if fw <= 1 or fh <= 1:
            return
        # 竖条看「高」是否溢出、横条看「宽」是否溢出，两者互不影响。
        # 基准用 frame 尺寸而不是 canvas 尺寸：后者会被滚动条占位改变，
        # 用它会形成「显隐改尺寸 → 重新判定」的回环。
        want_v, want_h = h > fh, w > fw
        if want_v != img_state["vbar"]:
            img_state["vbar"] = want_v
            if want_v:
                sb_v.grid()
            else:
                sb_v.grid_remove()
        if want_h != img_state["hbar"]:
            img_state["hbar"] = want_h
            if want_h:
                sb_h.grid()
            else:
                sb_h.grid_remove()

        cw = fw - (SB_W if want_v else 0)
        ch = fh - (SB_H if want_h else 0)
        canvas.delete("all")
        # 居中绘制
        x = max(0, (cw - w) // 2)
        y = max(0, (ch - h) // 2)
        canvas.create_image(x, y, anchor="nw", image=photo)
        # 只有装不下时才设 scrollregion
        if want_v or want_h:
            canvas.configure(scrollregion=(0, 0, max(cw, w), max(ch, h)))
        else:
            canvas.configure(scrollregion="")
            canvas.xview_moveto(0)
            canvas.yview_moveto(0)

    def refresh():
        z = zoom_var.get()
        pct_var.set(f"{int(z * 100)}%")
        img_state["w"] = max(1, int(puzzle.width * z))
        img_state["h"] = max(1, int(puzzle.height * z))
        scaled = puzzle.resize((img_state["w"], img_state["h"]),
                               Image.LANCZOS)
        img_state["photo"] = ImageTk.PhotoImage(scaled)
        layout()

    def on_scale(val):
        zoom_var.set(float(val))
        refresh()

    def fit():
        win.update_idletasks()
        fw = canvas_frame.winfo_width()
        fh = canvas_frame.winfo_height()
        if fw <= 1 or fh <= 1:      # 还没完成布局，稍后再试
            win.after(50, fit)
            return
        # 按「两条滚动条都隐藏」时的最大可视区算，且向下取整，
        # 避免适应窗口后刚好溢出又把滚动条显示回来
        z = min(fw / puzzle.width, fh / puzzle.height, 1.0)
        z = max(0.05, min(1.0, int(z * 100) / 100))
        zoom_var.set(z)
        refresh()

    ctk.CTkSlider(bar, from_=0.05, to=2.0, variable=zoom_var,
                  command=on_scale, width=150, height=16,
                  fg_color=TRACK, progress_color=ACCENT,
                  button_color=ACCENT,
                  button_hover_color=ACCENT_HOVER).pack(side="left", padx=6)
    ctk.CTkLabel(bar, textvariable=pct_var, width=44, font=app.f_sm,
                 text_color=TEXT).pack(side="left")
    ctk.CTkButton(bar, text="适应窗口", command=fit, width=64, height=26,
                  font=app.f_sm, corner_radius=RADIUS, fg_color=BTN,
                  hover_color=BTN_HOVER, text_color=TEXT,
                  border_width=1, border_color=BORDER).pack(side="left", padx=4)
    # 右侧按钮组：先 pack 保存原图占住最右端，再 pack 截图识别到它左侧，
    # 两者同宽同高、间距 4px；弹性空白只留在「适应窗口」与这一组之间
    ctk.CTkButton(bar, text="保存原图",
                  command=lambda: app._on_save_image(parent=win),
                  width=84, height=26, font=app.f_sm, corner_radius=RADIUS,
                  fg_color=BTN, hover_color=BTN_HOVER, text_color=TEXT,
                  border_width=1, border_color=BORDER).pack(side="right")
    ctk.CTkButton(bar, text="截图识别",
                  command=lambda: app._on_capture_region(win),
                  width=84, height=26, font=app.f_sm, corner_radius=RADIUS,
                  fg_color=ACCENT, hover_color=ACCENT_HOVER,
                  text_color=ON_ACCENT).pack(side="right", padx=(0, 4))

    # 画布 + 滚动条：两条滚动条都放在同一个 frame 里，
    # 这样「视口基准」= frame 自身尺寸，与滚动条是否显示无关，
    # 显隐不会改变下一次判定的基准（避免经典的两边互相挤出又缩回）
    canvas_frame = ctk.CTkFrame(win, fg_color=SURFACE, corner_radius=0)
    canvas_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
    canvas_frame.grid_columnconfigure(0, weight=1)
    canvas_frame.grid_rowconfigure(0, weight=1)

    canvas = tk.Canvas(canvas_frame, bg=SURFACE, highlightthickness=0)
    canvas.grid(row=0, column=0, sticky="nsew")

    sb_v = ctk.CTkScrollbar(canvas_frame, command=canvas.yview, width=12,
                            fg_color=TRACK, button_color=SCROLL_THUMB,
                            button_hover_color=SCROLL_THUMB_HOVER)
    sb_v.grid(row=0, column=1, sticky="ns", padx=(4, 0))
    canvas.configure(yscrollcommand=sb_v.set)

    sb_h = ctk.CTkScrollbar(canvas_frame, command=canvas.xview, height=12,
                            orientation="horizontal", fg_color=TRACK,
                            button_color=SCROLL_THUMB,
                            button_hover_color=SCROLL_THUMB_HOVER)
    sb_h.grid(row=1, column=0, sticky="ew", pady=(4, 0))
    canvas.configure(xscrollcommand=sb_h.set)

    # 先收起来，由 layout() 按实际视口决定是否显示（与 img_state 初值一致）
    sb_v.grid_remove()
    sb_h.grid_remove()

    # 改变弹窗尺寸后重新判断两条滚动条
    canvas_frame.bind("<Configure>", lambda e: layout())

    # 鼠标滚轮缩放：向上滚放大，向下滚缩小。
    # 只按符号判方向、一律走固定步长 0.1，兼容 ±120（常规滚轮）
    # 与 ±1 等不同粒度的触控板/高精度滚轮事件，不会因绝对值大小而跳变
    def _wheel(e):
        delta = 0.1 if e.delta > 0 else -0.1
        new = max(0.05, min(2.0, zoom_var.get() + delta))
        zoom_var.set(round(new, 2))
        refresh()

    canvas.bind("<MouseWheel>", _wheel)

    # 初始 fit
    win.after(100, fit)

    # CTkToplevel 初始化时会为了改标题栏颜色 withdraw → deiconify，
    # 重新 show 出来不带激活，容易落到主窗口后面；等它折腾完再抬一次
    def bring_front():
        if not win.winfo_exists():
            return
        win.lift()
        win.focus_force()

    win.after(30, bring_front)
