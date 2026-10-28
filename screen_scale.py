# -*- coding: utf-8 -*-
"""屏幕坐标适配层：让所有硬编码坐标继续按 1920×1080 写，运行时换算到真实屏幕。

为什么需要它
------------
项目里所有坐标（点击点、截图 ROI、状态判定点像素位置）都是 1920×1080 实测值。
换成 2560×1440 这类同比例（16:9）屏幕后，只要在**边界处**做一次线性换算即可，
不必重新量任何坐标：

    参考坐标（1920×1080） --to_screen--> 物理像素坐标（2560×1440）

三个关键点
----------
1. **必须先声明 DPI 感知**：进程不声明时，Windows 会把 125% 缩放的 2560×1440
   屏"虚拟"成 2048×1152 报给程序，而游戏实际渲染在 2560×1440 —— 截图尺寸、
   鼠标坐标全都差 1.25 倍。enable_dpi_awareness() 在启动最早期调用一次。
2. **缩放系数 s = min(屏宽/1920, 屏高/1080)**：16:9 屏幕 s 就是 屏宽/1920
   （2560×1440 → 1.3333）；非 16:9（如 16:10）会留黑边，多出的部分用
   offset_x / offset_y 居中，游戏画面仍然能被正确映射。
3. **只有边界才换算**：截图裁 ROI 前乘 s、发送鼠标前乘 s、画预览框时乘 s。
   业务代码里的坐标保持 1920×1080 不变，改屏幕分辨率不需要动任何数值。

测试/模拟：set_screen_size((1920, 1080)) 可以把换算固定成"恒等"，
这样单元测试不依赖当前机器分辨率；用完 set_screen_size(None) 恢复。
"""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
from typing import Optional, Sequence

# 参考坐标系：所有硬编码坐标使用的基准分辨率。
REF_W, REF_H = 1920, 1080

_override_size: Optional[tuple[int, int]] = None
_metrics_cache: Optional["Metrics"] = None
_dpi_aware: Optional[bool] = None


@dataclass(frozen=True)
class Metrics:
    """当前屏幕的换算参数（factor 与居中偏移）。"""

    screen_w: int
    screen_h: int
    factor: float
    offset_x: int
    offset_y: int

    @property
    def is_identity(self) -> bool:
        return (self.screen_w, self.screen_h) == (REF_W, REF_H)

    @property
    def content_size(self) -> tuple[int, int]:
        """游戏画面在屏幕上实际占据的像素尺寸（非 16:9 时小于整屏）。"""
        return (int(round(REF_W * self.factor)),
                int(round(REF_H * self.factor)))

    @property
    def percent(self) -> int:
        return int(round(self.factor * 100))

    def describe(self) -> str:
        if self.is_identity:
            return f"{self.screen_w}×{self.screen_h}（基准分辨率，坐标原样使用）"
        text = (f"{self.screen_w}×{self.screen_h}，按基准 1920×1080 换算 "
                f"×{self.factor:.4f}（{self.percent}%）")
        if self.offset_x or self.offset_y:
            text += f"，居中偏移 ({self.offset_x}, {self.offset_y})"
        return text

    def as_dict(self) -> dict:
        return {"screen_w": self.screen_w, "screen_h": self.screen_h,
                "factor": round(self.factor, 6),
                "percent": self.percent,
                "offset_x": self.offset_x, "offset_y": self.offset_y,
                "reference": [REF_W, REF_H],
                "description": self.describe()}


# ---------------------------------------------------------------- DPI 感知
def enable_dpi_awareness() -> bool:
    """声明进程 DPI 感知（per-monitor），让截图与坐标都落在物理像素上。

    幂等：重复调用只生效一次。必须在创建任何窗口/截图/取屏幕尺寸之前调用，
    所以放在 web_ui.py / main.py 的最顶部（import pywin32、PIL 之前）。
    """
    global _dpi_aware
    if _dpi_aware is not None:
        return _dpi_aware
    try:
        # 2 = PROCESS_PER_MONITOR_DPI_AWARE（Win8.1+）
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        _dpi_aware = True
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
            _dpi_aware = True
        except Exception:
            _dpi_aware = False
    return _dpi_aware


def is_dpi_aware() -> Optional[bool]:
    """返回 DPI 感知的声明结果（None = 还没调用过 enable_dpi_awareness）。"""
    return _dpi_aware


# ---------------------------------------------------------------- 屏幕尺寸
def _read_screen_size() -> tuple[int, int]:
    try:
        user32 = ctypes.windll.user32
        return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
    except Exception:
        return (REF_W, REF_H)


def screen_size() -> tuple[int, int]:
    """当前屏幕的物理像素尺寸（已声明 DPI 感知时才是真实分辨率）。"""
    if _override_size is not None:
        return _override_size
    width, height = _read_screen_size()
    if width <= 0 or height <= 0:
        return (REF_W, REF_H)
    return (width, height)


def set_screen_size(size: Optional[Sequence[int]]) -> None:
    """覆盖屏幕尺寸（测试/模拟用）；传 None 恢复读取真实屏幕。"""
    global _override_size, _metrics_cache
    if size is None:
        _override_size = None
    else:
        width, height = int(size[0]), int(size[1])
        _override_size = (width, height)
    _metrics_cache = None


# ---------------------------------------------------------------- 换算
def metrics() -> Metrics:
    """当前换算参数（按屏幕尺寸缓存，屏幕变了会自动重算）。"""
    global _metrics_cache
    width, height = screen_size()
    if width <= 0 or height <= 0:      # 读不到屏幕尺寸时退回基准帧
        width, height = REF_W, REF_H
    if _metrics_cache is not None and (
            _metrics_cache.screen_w, _metrics_cache.screen_h) == (width, height):
        return _metrics_cache
    factor = min(width / float(REF_W), height / float(REF_H))
    if factor <= 0:
        factor = 1.0
    offset_x = int(round((width - REF_W * factor) / 2.0))
    offset_y = int(round((height - REF_H * factor) / 2.0))
    _metrics_cache = Metrics(width, height, factor, offset_x, offset_y)
    return _metrics_cache


def scale() -> float:
    """参考坐标 → 物理像素的比例（1920×1080 屏幕为 1.0）。"""
    return metrics().factor


def to_screen(x: float, y: float) -> tuple[int, int]:
    """参考坐标 → 物理像素坐标（鼠标点击前必须过这一层）。"""
    m = metrics()
    return (int(round(float(x) * m.factor)) + m.offset_x,
            int(round(float(y) * m.factor)) + m.offset_y)


def to_ref(x: float, y: float) -> tuple[int, int]:
    """物理像素坐标 → 参考坐标（反向换算，主要用于调试/日志）。"""
    m = metrics()
    return (int(round((float(x) - m.offset_x) / m.factor)),
            int(round((float(y) - m.offset_y) / m.factor)))


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def to_screen_box(box: Sequence[int],
                  clamp: bool = True) -> tuple[int, int, int, int]:
    """把参考坐标 ROI (left, top, right, bottom) 换算成物理像素 ROI。

    clamp=True 时把结果裁进屏幕范围：ImageGrab 拿到越界 bbox 会返回黑块，
    宁可截小一点，也不要喂一整块黑色给 OCR。
    """
    left, top, right, bottom = (int(v) for v in box)
    m = metrics()
    x0 = int(round(left * m.factor)) + m.offset_x
    y0 = int(round(top * m.factor)) + m.offset_y
    x1 = int(round(right * m.factor)) + m.offset_x
    y1 = int(round(bottom * m.factor)) + m.offset_y
    if clamp:
        x0 = _clamp(x0, 0, m.screen_w)
        x1 = _clamp(x1, 0, m.screen_w)
        y0 = _clamp(y0, 0, m.screen_h)
        y1 = _clamp(y1, 0, m.screen_h)
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    return (x0, y0, x1, y1)


def to_ref_box(box: Sequence[int]) -> tuple[int, int, int, int]:
    """物理像素 ROI → 参考坐标 ROI（与 to_screen_box 互为逆运算）。"""
    left, top, right, bottom = (int(v) for v in box)
    x0, y0 = to_ref(left, top)
    x1, y1 = to_ref(right, bottom)
    return (x0, y0, x1, y1)


def describe() -> str:
    """一行人类可读的换算说明（自检/日志/网页展示用）。"""
    return metrics().describe()
