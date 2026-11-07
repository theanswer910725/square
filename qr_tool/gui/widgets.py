"""界面小部件：截图图标与悬停提示。"""
import tkinter as tk

from PIL import Image, ImageDraw


def make_scan_icon(size=16, scale=4, color="#1f2328"):
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
        tk.Label(tip, text=self.text, bg="#2b2f36", fg="#ffffff",
                 font=("Microsoft YaHei UI", 12), padx=6, pady=2).pack()
        tip.geometry(f"+{x}+{y}")
        self.tip = tip

    def _hide(self, _=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None
