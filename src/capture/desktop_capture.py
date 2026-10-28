"""Read-only desktop capture for the visible HSAng recommendation panel."""

from __future__ import annotations

import ctypes
import hashlib
from pathlib import Path
import time
import uuid
from typing import Callable, Optional

import cv2
import numpy as np
from PIL import ImageGrab

from src.recommendation_config import RecommendationConfig
from src.recommendation_models import FrameEvidence

import screen_scale


class CaptureEnvironmentError(RuntimeError):
    """The visible desktop cannot safely produce a current recommendation."""


def _default_screen_grabber() -> np.ndarray:
    """Full-desktop grabber, kept for injected/test compatibility."""
    rgb = np.asarray(ImageGrab.grab(all_screens=False))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _roi_screen_grabber(bbox) -> Callable[[], np.ndarray]:
    """Grab only the recommendation panel ROI instead of the whole desktop.

    bbox 是**物理像素**（调用方已按 screen_scale 换算）；截这一小块能省掉
    整屏 88% 的搬运与色彩转换。
    """
    def grab() -> np.ndarray:
        rgb = np.asarray(ImageGrab.grab(bbox=bbox, all_screens=False))
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    return grab


def _default_dpi_reader() -> int:
    try:
        return int(ctypes.windll.user32.GetDpiForSystem())
    except Exception:
        return 0


def _default_process_checker() -> bool:
    try:
        import psutil
        names = {
            (process.info.get("name") or "").lower()
            for process in psutil.process_iter(["name"])
        }
        return "hearthstone.exe" in names and "hsang.exe" in names
    except Exception:
        return False


def _default_window_reader() -> tuple[int, bool]:
    try:
        import win32gui
        from get_screen import get_HS_hwnd, is_allowed_hearthstone_foreground
        hwnd = int(get_HS_hwnd())
        return hwnd, bool(hwnd and is_allowed_hearthstone_foreground(
            hwnd, win32gui.GetForegroundWindow()))
    except Exception:
        return 0, False


class DesktopCapture:
    def __init__(
        self,
        config: RecommendationConfig,
        screen_grabber: Optional[Callable[[], np.ndarray]] = None,
        dpi_reader: Callable[[], int] = _default_dpi_reader,
        process_checker: Callable[[], bool] = _default_process_checker,
        window_reader: Callable[[], tuple[int, bool]] = _default_window_reader,
        clock: Callable[[], float] = time.time,
    ):
        self.config = config
        self.screen_grabber = (screen_grabber
                               or _roi_screen_grabber(
                                   screen_scale.to_screen_box(
                                       config.recommendation_roi)))
        self.dpi_reader = dpi_reader
        self.process_checker = process_checker
        self.window_reader = window_reader
        self.clock = clock

    @property
    def _roi_size(self) -> tuple[int, int]:
        """ROI 在**物理像素**下的 (宽, 高)——与 ROI 抓图输出一致。"""
        left, top, right, bottom = screen_scale.to_screen_box(
            self.config.recommendation_roi)
        return (bottom - top, right - left)

    def _is_roi_frame(self, width: int, height: int) -> bool:
        roi_height, roi_width = self._roi_size
        return (width, height) == (roi_width, roi_height)

    def from_file(self, path: Path | str) -> FrameEvidence:
        data = np.fromfile(str(path), dtype=np.uint8)
        pixels = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if pixels is None:
            raise CaptureEnvironmentError("frame_decode_failed")
        return self.from_array(pixels, validate_environment=False)

    def capture(self, ocr_panel_ok: bool = False) -> FrameEvidence:
        if not self.process_checker():
            raise CaptureEnvironmentError("required_process_missing")
        hwnd, foreground = self.window_reader()
        if not hwnd:
            raise CaptureEnvironmentError("hearthstone_window_missing")
        if not foreground:
            raise CaptureEnvironmentError("hearthstone_not_foreground")
        pixels = self.screen_grabber()
        try:
            return self.from_array(
                pixels, validate_environment=True, dpi=self.dpi_reader(),
                window_handle=hwnd, foreground=foreground)
        except CaptureEnvironmentError as exc:
            if "recommendation_panel_missing" not in str(exc):
                raise
            if not ocr_panel_ok:
                raise
            # 换牌面板的红头判定并不可靠；交由 OCR 证据裁定：
            # 识别出"打法参考A"（stable_reader.required_headers）即确认
            # 面板在，否则由 reader 置零置信度拒绝，安全兜底。
            return self.from_array(
                pixels, validate_environment=False, dpi=self.dpi_reader(),
                window_handle=hwnd, foreground=foreground)


    def from_array(
        self,
        pixels: np.ndarray,
        *,
        validate_environment: bool,
        dpi: Optional[int] = None,
        window_handle: int = 0,
        foreground: bool = True,
    ) -> FrameEvidence:
        if pixels is None or pixels.ndim != 3 or pixels.shape[2] < 3:
            raise CaptureEnvironmentError("invalid_frame")
        height, width = pixels.shape[:2]
        roi_frame = self._is_roi_frame(width, height)
        if validate_environment:
            if roi_frame:
                # ROI 抓图：尺寸已经由 screen_scale 换算校验过，桌面尺寸按当前屏幕记。
                desktop_width, desktop_height = screen_scale.screen_size()
            else:
                desktop_width, desktop_height = width, height
                # 整屏帧必须是"基准帧(1920×1080)"或"当前物理屏"之一：
                # 两者都按 screen_scale 换算，坐标才成立；其它尺寸说明分辨率/缩放
                # 在运行中变了，直接拒绝比点偏安全。
                allowed = {tuple(self.config.desktop_size),
                           tuple(screen_scale.screen_size())}
                if (width, height) not in allowed:
                    raise CaptureEnvironmentError(
                        f"desktop_size_mismatch:{width}x{height}")
        else:
            desktop_width, desktop_height = width, height
        # DPI 不再作为门槛：截图与点击都由 screen_scale 换算到物理像素，
        # 125%/150% 缩放一样能用，这里只如实记录。
        effective_dpi = self.config.desktop_dpi if dpi is None else int(dpi)

        roi = (pixels[:, :, :3] if roi_frame
               else self._crop_array(pixels))
        panel_visible = self._panel_is_visible(roi)
        if validate_environment and not panel_visible:
            raise CaptureEnvironmentError("recommendation_panel_missing")
        exact_hash = hashlib.sha256(roi.tobytes()).hexdigest()
        perceptual_hash = self._perceptual_hash(roi)
        return FrameEvidence(
            frame_id=f"frame-{uuid.uuid4()}", captured_at=self.clock(),
            desktop_size=(desktop_width, desktop_height), dpi=effective_dpi,
            window_handle=window_handle, foreground=foreground,
            recommendation_roi=self.config.recommendation_roi,
            exact_hash=exact_hash, perceptual_hash=perceptual_hash,
            panel_visible=panel_visible, pixels=pixels,
        )

    def crop_recommendation(self, frame: FrameEvidence) -> np.ndarray:
        height, width = frame.pixels.shape[:2]
        if self._is_roi_frame(width, height):
            return frame.pixels[:, :, :3].copy()
        return self._crop_array(frame.pixels).copy()

    def _crop_array(self, pixels: np.ndarray) -> np.ndarray:
        # 配置里的 ROI 是 1920×1080 基准坐标，整屏帧可能是 2560×1440：先换算再裁。
        left, top, right, bottom = screen_scale.to_screen_box(
            self.config.recommendation_roi)
        height, width = pixels.shape[:2]
        if left < 0 or top < 0 or right > width or bottom > height:
            raise CaptureEnvironmentError("recommendation_roi_out_of_bounds")
        return pixels[top:bottom, left:right, :3]

    @staticmethod
    def _panel_is_visible(roi: np.ndarray) -> bool:
        if roi.size == 0 or float(np.std(roi)) < 8.0:
            return False
        # HSAng uses a dark red header at the top of this fixed panel.
        header = roi[:45]
        b, g, r = cv2.split(header)
        red_dark = (r > g * 1.25) & (r > b * 1.15) & (r < 140)
        return float(np.mean(red_dark)) > 0.08

    @staticmethod
    def _perceptual_hash(roi: np.ndarray) -> str:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray, (16, 16), interpolation=cv2.INTER_AREA)
        bits = resized >= float(np.mean(resized))
        return "".join(f"{value:02x}" for value in np.packbits(bits))
