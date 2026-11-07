"""界面小部件：截图图标、窗口图标、字体挑选与悬停提示。"""
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageTk

from .theme import (ARROW_BG, ARROW_BG_HOVER, ARROW_BG_OPEN, BORDER, CARD,
                    DIVIDER, DIVIDER_HOVER, DIVIDER_OPEN, FIELD, FIELD_HOVER,
                    FIELD_OPEN, FONT_STACK, MENU_HOVER, MUTED, RADIUS,
                    SELECT_BG, SELECT_FG, TEXT, TOOLTIP_BG, TOOLTIP_FG)

# CustomTkinter 官方仓库自带的 Windows 图标（256×256，含透明通道）
ICON_ICO = Path(__file__).with_name("assets") / "CustomTkinter_icon_Windows.ico"


def pick_font_family(root):
    """按 FONT_STACK 顺序取第一个系统里存在的字体。

    Win11 有 Segoe UI Variable Text；Win10 只有 Segoe UI，再不行回退雅黑。
    """
    families = set(tkfont.families(root))
    return next((f for f in FONT_STACK if f in families),
                next((f for f in ("Segoe UI", "Microsoft YaHei UI")
                      if f in families), "TkDefaultFont"))


def fix_textbox_selection(tb):
    """把 CTkTextbox 内部 Tk Text 的选中色改成色板色。

    CTkTextbox 没有开放 selectbackground，只能落到内部 `_textbox` 上改；
    不改的话选中文字会跳出 Tk 默认的深蓝，与色板冲突。
    """
    try:
        tb._textbox.configure(selectbackground=SELECT_BG,
                              selectforeground=SELECT_FG)
    except Exception:
        pass


def set_window_icon(win):
    """设置窗口/任务栏图标。

    必须在窗口首次显示之前调用：Windows 任务栏按钮会缓存窗口第一次映射时的
    图标，窗口显示后再改通常不刷新，仍旧显示 python 默认图标。
    """
    try:
        win.iconbitmap(str(ICON_ICO))
    except Exception:
        pass


def make_scan_icon(size=16, scale=4, color=TEXT):
    """极简线性「截图」图标：四角取景框。按 scale 倍绘制，缩小后边缘干净。"""
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    w = max(1, int(round(1.4 * scale)))
    m = int(round(1.5 * scale))
    ln = int(round(size * scale * 0.34))
    hi = s - m - 1
    for x, y, dx, dy in ((m, m, 1, 1), (hi, m, -1, 1),
                         (m, hi, 1, -1), (hi, hi, -1, -1)):
        d.line([(x, y), (x + dx * ln, y)], fill=color, width=w)
        d.line([(x, y), (x, y + dy * ln)], fill=color, width=w)
    return img


class Tooltip:
    """轻量悬停提示（CTk 本身没有 tooltip）"""

    def __init__(self, widget, text):
        self.widget, self.text, self.tip = widget, text, None
        self.font = (pick_font_family(widget.winfo_toplevel()), 12)
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _show(self, _=None):
        if self.tip or not self.widget.winfo_ismapped():
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2 - 26
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        tip = tk.Toplevel(self.widget)
        tip.overrideredirect(True)
        tip.attributes("-topmost", True)
        tk.Label(tip, text=self.text, bg=TOOLTIP_BG, fg=TOOLTIP_FG,
                 font=self.font, padx=6, pady=2).pack()
        tip.geometry(f"+{x}+{y}")
        self.tip = tip

    def _hide(self, _=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class SelectBox(tk.Canvas):
    """只读下拉框：整条框、箭头、展开菜单全部自绘。

    CTkOptionMenu / CTkComboBox 把右侧箭头区做成独立绘制分区，该分区外圈的
    1px 用的是 button_color 而不是 border_color，所以「白色箭头格 + 完整
    #e5e5e5 描边」在它们身上无法同时成立。这里整条控件一次画完，不分段。
    """

    _active = None      # 当前展开的实例，保证同一时刻只有一个菜单
    _KEY = "#ff00fe"    # 菜单窗口抠色用的哑色，正常内容里不会出现
    _ROW_H = 28         # 菜单行高（逻辑像素）
    _PAD = 4            # 菜单内边距（逻辑像素）

    def __init__(self, master, variable, values, font=None, height=30,
                 surface=CARD, command=None):
        try:
            dpi = master.winfo_fpixels("1i") / 96.0
        except Exception:
            dpi = 1.0
        self._dpi = dpi
        super().__init__(master, height=int(round(height * dpi)), bd=0,
                         highlightthickness=0, bg=surface, takefocus=True)
        self._var = variable
        self._values = list(values)
        self._font = font or tkfont.nametofont("TkDefaultFont")
        self._surface = surface
        self._command = command

        self._alive = True
        self._hover = False
        self._is_open = False
        # 三态背景图按尺寸缓存；状态切换只换 item 的图，不跑 PIL
        self._geom = None            # (w, h, ss)
        self._photos = {}
        self._state_now = None
        self._img_item = None
        self._text_item = None
        self._cell_w = self._p(30)

        self._menu = None
        self._menu_cv = None
        self._menu_bg = None
        self._menu_hl = None
        self._menu_hl_item = None
        self._menu_hover = -1
        self._menu_geom = None
        self._menu_pos = None
        self._transparent = False
        self._outside_id = None

        self.bind("<Configure>", lambda e: self._render())
        self.bind("<Map>", lambda e: self._render())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", lambda e: self._toggle())
        self.bind("<Return>", lambda e: self._confirm())
        self.bind("<space>", lambda e: self._confirm())
        self.bind("<Down>", lambda e: self._move(1))
        self.bind("<Up>", lambda e: self._move(-1))
        self.bind("<Escape>", lambda e: self._close_menu())
        self.bind("<Destroy>", self._on_destroy)
        self._trace = variable.trace_add("write", lambda *a: self._update_text())

    # ---------- 绘制 ----------
    def _p(self, value):
        """逻辑像素 → 物理像素（跟随系统 DPI）"""
        return int(round(value * self._dpi))

    def _scale(self):
        """超采样倍率：3 倍起步，高 DPI 时提高一档，保证圆弧和线条不糊"""
        try:
            return max(2, min(4, int(round(3 * self._dpi))))
        except Exception:
            return 3

    def _state(self):
        if self._is_open:
            return "open"
        return "hover" if self._hover else "normal"

    def _render(self):
        """尺寸变化才重建三态背景图；状态/文本变化只改 item"""
        if not self._alive:
            return
        try:
            w, h = self.winfo_width(), self.winfo_height()
        except tk.TclError:
            return
        if w < 12 or h < 8:
            return

        # 窗口跨显示器拖动时 DPI 会变，按当前 tk scaling 重算线宽与圆角
        try:
            self._dpi = self.winfo_fpixels("1i") / 96.0
        except tk.TclError:
            pass

        ss = self._scale()
        if (w, h, ss) != self._geom:
            self._geom = (w, h, ss)
            self._cell_w = self._p(30)
            self._build_photos(w, h, ss)
            if self._img_item is None:
                self._img_item = self.create_image(0, 0, anchor="nw")
                self._text_item = self.create_text(
                    self._p(10), h / 2, anchor="w", font=self._font,
                    fill=TEXT)
            else:
                self.coords(self._text_item, self._p(10), h / 2)
            self._state_now = None

        state = self._state()
        if state != self._state_now:
            self._state_now = state
            self.itemconfigure(self._img_item, image=self._photos[state])
        self._update_text(w)

    def _update_text(self, w=None):
        """只改 text item：变量写入、尺寸变化都不重画背景"""
        if self._text_item is None:
            return
        if w is None:
            try:
                w = self.winfo_width()
            except tk.TclError:
                return
        self.itemconfigure(
            self._text_item,
            text=self._fit_text(w - self._cell_w - self._p(18)))

    def _build_photos(self, w, h, ss):
        """三态背景图一次性预生成，之后 hover/展开只换图"""
        self._photos = {
            "normal": self._photo_for(w, h, ss, FIELD, ARROW_BG, DIVIDER),
            "hover": self._photo_for(w, h, ss, FIELD_HOVER,
                                     ARROW_BG_HOVER, DIVIDER_HOVER),
            "open": self._photo_for(w, h, ss, FIELD_OPEN,
                                    ARROW_BG_OPEN, DIVIDER_OPEN),
        }

    def _photo_for(self, w, h, ss, fill, cell, sep):
        radius = self._p(RADIUS)
        cell_w = self._p(30)
        cell_left = w - cell_w

        img = Image.new("RGB", (w * ss, h * ss), self._surface)
        d = ImageDraw.Draw(img)

        # 1. 整条外框填充
        d.rounded_rectangle((0, 0, w * ss - 1, h * ss - 1),
                            radius=radius * ss, fill=fill)

        # 2. 箭头区：把外框路径向内缩 1px 当作蒙版再贴底色。
        #    左两角是直角（本来就被分隔线切断），右两角跟着外框收成 8px 弧，
        #    因此不可能有方角戳到圆角外面。
        mask = Image.new("L", (w * ss, h * ss), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (cell_left * ss, ss, (w - 1) * ss - 1, (h - 1) * ss - 1),
            radius=max(0, radius - 1) * ss, fill=255,
            corners=(False, True, True, False))
        img.paste(cell, mask=mask)

        # 3. 箭头区左侧 1px 分隔竖线，只以内缩后的高度为准，两端不碰外框弧
        d.rectangle((cell_left * ss, ss,
                     cell_left * ss + ss - 1, (h - 1) * ss - 1), fill=sep)

        # 4. 整条 1px 外描边最后画，压在全部填充之上
        d.rounded_rectangle((0, 0, w * ss - 1, h * ss - 1),
                            radius=radius * ss, outline=BORDER, width=ss)

        # chevron 在箭头区内水平居中，颜色保持次级文字色
        cx, cy = cell_left + cell_w / 2, h / 2
        dx, dy = self._p(4.5), self._p(2.5)
        d.line([(cx - dx) * ss, (cy - dy) * ss,
                cx * ss, (cy + dy) * ss,
                (cx + dx) * ss, (cy - dy) * ss],
               fill=MUTED, width=max(2, int(round(1.6 * self._dpi * ss))),
               joint="curve")

        # 用 BOX 而不是 LANCZOS：LANCZOS 的滤波核更宽，会把白底混进 1px
        # 描边里，边线变浅（229→231）；BOX 恰好是 ss×ss 方块平均，
        # 直边颜色严格保持，圆角处仍然是抗锯齿的渐变
        img = img.resize((w, h), Image.BOX)
        return ImageTk.PhotoImage(img, master=self)

    def _fit_text(self, avail):
        text = self._var.get()
        try:
            if avail <= 0 or self._font.measure(text) <= avail:
                return text
            cut = text
            while cut and self._font.measure(cut + "…") > avail:
                cut = cut[:-1]
            return (cut + "…") if cut else "…"
        except Exception:
            return text

    # ---------- 控件交互 ----------
    def _on_enter(self, _=None):
        if not self._hover:
            self._hover = True
            self._render()

    def _on_leave(self, _=None):
        if self._hover:
            self._hover = False
            self._render()

    def _confirm(self):
        """回车/空格：展开时确认高亮项，收起时展开"""
        if self._is_open:
            return self._pick(self._menu_hover if self._menu_hover >= 0
                              else self._index())
        return self._toggle()

    def _toggle(self):
        if self._is_open:
            self._close_menu()
        else:
            self._open_menu()
        return "break"

    def _on_destroy(self, event):
        if event.widget is not self:
            return
        self._close_menu()
        if self._menu is not None:
            try:
                self._menu.destroy()
            except Exception:
                pass
            self._menu = None
        self._menu_cv = None
        self._menu_bg = None
        self._menu_hl = None
        self._menu_hl_item = None
        self._alive = False
        try:
            self._var.trace_remove("write", self._trace)
        except Exception:
            pass

    # ---------- 展开菜单 ----------
    def _ensure_menu(self):
        """菜单窗口只建一次：创建 Toplevel 约 35ms，每次重建就是卡顿主因"""
        row_h, pad = self._p(self._ROW_H), self._p(self._PAD)
        mw = max(self.winfo_width(), self._p(120))
        try:
            mw = max(mw, max(self._font.measure(v) for v in self._values)
                     + self._p(36))
        except Exception:
            pass
        mh = len(self._values) * row_h + pad * 2
        key = (mw, mh, row_h, pad)
        if self._menu is not None:
            if key == self._menu_geom:
                return
            try:                     # 尺寸/DPI 变了：重建一次
                self._menu.destroy()
            except Exception:
                pass
            self._menu = None
        self._menu_geom = key
        self._menu_pos = None

        top = tk.Toplevel(self)
        top.withdraw()
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(bg=self._KEY)
        self._transparent = False
        try:
            # 只让圆角外的像素透明；配合下面的硬边蒙版，不会出现彩色描边
            top.attributes("-transparentcolor", self._KEY)
            self._transparent = True
        except tk.TclError:
            pass

        cv = tk.Canvas(top, width=mw, height=mh, bg=self._KEY,
                       bd=0, highlightthickness=0)
        cv.pack(fill="both", expand=True)

        self._menu = top
        self._menu_cv = cv
        self._menu_bg = self._menu_background(mw, mh)
        cv.create_image(0, 0, anchor="nw", image=self._menu_bg)
        self._menu_hl = self._highlight_image(mw)
        self._menu_hl_item = cv.create_image(
            pad, pad, anchor="nw", image=self._menu_hl, state="hidden")
        for i, value in enumerate(self._values):
            cv.create_text(self._p(12), pad + i * row_h + row_h / 2,
                           anchor="w", text=value, font=self._font, fill=TEXT)

        cv.bind("<Motion>", lambda e: self._hover_row(
            (e.y - self._menu_geom[3]) // self._menu_geom[2]))
        cv.bind("<Leave>", lambda e: self._hover_row(-1))
        # 选中放在「抬起」：按下时菜单还在，抬起由菜单自己吃掉；
        # 若在按下时就销毁菜单，抬起会落到下方「生成二维码」按钮上
        # （CTkButton 的命令绑在 ButtonRelease-1，等于替用户点了生成）
        cv.bind("<Button-1>", lambda e: "break")
        cv.bind("<ButtonRelease-1>", lambda e: self._pick(
            (e.y - self._menu_geom[3]) // self._menu_geom[2]))
        top.bind("<Down>", lambda e: self._move(1))
        top.bind("<Up>", lambda e: self._move(-1))
        top.bind("<Return>", lambda e: self._pick(
            self._menu_hover if self._menu_hover >= 0 else self._index()))
        top.bind("<Escape>", lambda e: self._close_menu())

    def _open_menu(self):
        if self._is_open or not self._values or not self._alive:
            return "break"
        if SelectBox._active is not None and SelectBox._active is not self:
            SelectBox._active._close_menu()
        SelectBox._active = self
        self._is_open = True
        self._menu_hover = -1
        self._render()
        self._ensure_menu()
        mw, mh = self._menu_geom[0], self._menu_geom[1]

        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + 2
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        if y + mh > sh - 4:
            y = max(4, self.winfo_rooty() - mh - 2)
        if x + mw > sw - 4:
            x = max(4, sw - mw - 4)
        top = self._menu
        # 收起时整窗内容是抠色（全透明且点击穿透），展开先把内容放回来
        if self._transparent:
            self._menu_cv.itemconfigure("all", state="normal")
            self._menu_cv.itemconfigure(self._menu_hl_item, state="hidden")
        # 位置没变就不碰窗口：挪窗要排队生效，紧跟的鼠标事件会落在旧位置，
        # 点菜单等于点空气；而强制刷新（update_idletasks）一次约 5~7ms
        if (x, y) != self._menu_pos:
            top.geometry(f"{mw}x{mh}+{x}+{y}")
            if not top.winfo_ismapped():
                top.deiconify()
            top.update_idletasks()
            self._menu_pos = (x, y)
        top.lift()
        # 焦点留在下拉框本身：抢焦点（focus_force）一次要 12~17ms，
        # 键盘导航继续走控件上的 Down/Up/Return 绑定
        self.focus_set()

        # overrideredirect 的窗口在 Windows 上经常收不到 FocusOut，
        # 点应用内别处空白时靠这条窗口级点击绑定兜底关闭
        self._outside_id = self.winfo_toplevel().bind(
            "<Button-1>", self._on_outside_click, add="+")
        return "break"

    def _on_outside_click(self, event):
        node = event.widget
        while node is not None:
            # 点在下拉框上：开/关交给它自己的 _toggle。
            # 控件绑定先于窗口绑定执行，若这里再收一次，刚展开的菜单
            # 会被同一次按下立刻关掉（快速切换时表现为点了没反应）
            if isinstance(node, SelectBox):
                return
            if node is self._menu or node is self._menu_cv:
                return
            node = getattr(node, "master", None)
        self._close_menu()

    def _close_menu(self):
        if not self._is_open:
            return
        self._is_open = False
        self._menu_hover = -1
        if self._outside_id is not None:
            try:
                self.winfo_toplevel().unbind("<Button-1>", self._outside_id)
            except Exception:
                pass
            self._outside_id = None
        # 收起不销毁也不 withdraw（withdraw 一次约 25ms）：
        # 把画布内容全部藏起来，整窗只剩抠色 → 全透明且点击穿透
        if self._menu_cv is not None:
            try:
                if self._transparent:
                    self._menu_cv.itemconfigure("all", state="hidden")
                else:                  # 抠色不可用：退回挪到屏幕外
                    self._menu.geometry(
                        f"+{self.winfo_screenwidth() + 2000}"
                        f"+{self.winfo_screenheight() + 2000}")
                    self._menu_pos = None
            except Exception:
                pass
        if SelectBox._active is self:
            SelectBox._active = None
        self._render()

    def _menu_background(self, mw, mh):
        """白底 + 1px 描边的圆角菜单背景，圆角外一律压成哑色（硬边，无彩边）"""
        ss = self._scale()
        radius = self._p(RADIUS)
        img = Image.new("RGB", (mw * ss, mh * ss), CARD)
        ImageDraw.Draw(img).rounded_rectangle(
            (0, 0, mw * ss - 1, mh * ss - 1), radius=radius * ss,
            fill=CARD, outline=BORDER, width=ss)
        img = img.resize((mw, mh), Image.BOX)

        # 蒙版只有 0/255：不做边缘半透明，避免和哑色混出绿边/紫边
        mask = Image.new("L", (mw, mh), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, mw - 1, mh - 1), radius=radius, fill=255)
        # 抗锯齿缩回后外圈会变浅，压回纯描边色，保证一圈不断
        edge = ImageChops.subtract(mask, mask.filter(ImageFilter.MinFilter(3)))
        img.paste(BORDER, mask=edge)

        key = tuple(int(self._KEY[i:i + 2], 16) for i in (1, 3, 5))
        img = Image.composite(img, Image.new("RGB", (mw, mh), key), mask)
        return ImageTk.PhotoImage(img, master=self)

    def _highlight_image(self, mw):
        """选项悬停底：白底上画浅灰圆角块，边缘抗锯齿也不会出现彩边"""
        ss = self._scale()
        w = mw - self._p(self._PAD) * 2
        h = self._p(self._ROW_H) - 2
        img = Image.new("RGB", (w * ss, h * ss), CARD)
        ImageDraw.Draw(img).rounded_rectangle(
            (0, 0, w * ss - 1, h * ss - 1), radius=self._p(4) * ss,
            fill=MENU_HOVER)
        return ImageTk.PhotoImage(img.resize((w, h), Image.BOX), master=self)

    def _hover_row(self, i):
        if not self._is_open or self._menu_cv is None:
            return
        if i < 0 or i >= len(self._values):
            self._menu_hover = -1
            self._menu_cv.itemconfigure(self._menu_hl_item, state="hidden")
            return
        self._menu_hover = i
        self._menu_cv.coords(self._menu_hl_item, self._p(self._PAD),
                             self._p(self._PAD) + i * self._p(self._ROW_H) + 1)
        self._menu_cv.itemconfigure(self._menu_hl_item, state="normal")

    def _index(self):
        try:
            return self._values.index(self._var.get())
        except ValueError:
            return -1

    def _move(self, step):
        if not self._is_open:
            return self._open_menu()
        n = len(self._values)
        cur = self._menu_hover if self._menu_hover >= 0 else self._index()
        if cur < 0:
            cur = 0 if step > 0 else n - 1
        else:
            cur = (cur + step) % n
        self._hover_row(cur)
        return "break"

    def _pick(self, i):
        if not self._is_open:
            return "break"
        if not (0 <= i < len(self._values)):
            self._close_menu()        # 在菜单外抬起：只收起，不改值
            return "break"
        value = self._values[i]
        self._close_menu()
        self._var.set(value)          # 变量写入会触发重绘
        if self._command is not None:
            self._command(value)
        return "break"

    # ---------- 取值 ----------
    def get(self):
        return self._var.get()

    def set(self, value):
        self._var.set(value)
