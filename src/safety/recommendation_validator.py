"""Validate recommendation evidence immediately before execution."""

import screen_scale

from src.recommendation_config import RecommendationConfig
from src.recommendation_models import ValidationResult


class ConsumedActionStore:
    def __init__(self):
        self._keys = set()

    @staticmethod
    def key_for(proposed, adapted):
        return (
            proposed.turn_number, proposed.log_revision,
            proposed.normalized_instruction, adapted.source_entity_id,
            adapted.target_entity_id,
        )

    def contains(self, key):
        return key in self._keys

    def mark_consumed(self, key):
        self._keys.add(key)


class RecommendationValidator:
    def __init__(self, config=None):
        self.config = config or RecommendationConfig()

    def validate(self, proposed, adapted, stable_frame, current_frame,
                 current_ocr, state, log_revision,
                 flow_state, consumed, stopped):
        # State/identity freshness must be checked before frame/control gates.
        if proposed.turn_number != state.game_num_turns_in_play:
            return ValidationResult.reject("turn_changed")
        if proposed.log_revision != log_revision:
            return ValidationResult.reject("revision_changed")
        if proposed.ocr_confidence < self.config.min_ocr_confidence:
            return ValidationResult.reject("ocr_confidence")
        if proposed.semantic_confidence < 1.0:
            return ValidationResult.reject("semantic_confidence")
        if not getattr(state, "is_my_turn", False):
            return ValidationResult.reject("not_player_turn")
        if stable_frame.frame_id != proposed.frame_id:
            return ValidationResult.reject("stale_frame")
        if current_ocr.frame_id != current_frame.frame_id:
            return ValidationResult.reject("current_ocr_frame")
        if current_ocr.normalized_text != proposed.normalized_instruction:
            return ValidationResult.reject("recommendation_changed")
        # 帧尺寸只校验"是基准帧(1920×1080)或当前物理屏"：分辨率与缩放已由
        # screen_scale 统一换算，高 DPI / 2K 屏不再被当成异常拒绝。
        try:
            allowed_sizes = {tuple(self.config.desktop_size),
                             tuple(screen_scale.screen_size())}
        except Exception:
            allowed_sizes = {tuple(self.config.desktop_size)}
        if tuple(current_frame.desktop_size) not in allowed_sizes:
            return ValidationResult.reject("desktop_size")
        if not current_frame.window_handle or not current_frame.foreground:
            return ValidationResult.reject("window")
        if not current_frame.panel_visible:
            return ValidationResult.reject("recommendation_panel")
        if stopped:
            return ValidationResult.reject("stopped")
        if flow_state != "PLAYER_TURN":
            return ValidationResult.reject("flow_state")
        key = consumed.key_for(proposed, adapted)
        if consumed.contains(key):
            return ValidationResult.reject("already_consumed")
        return ValidationResult.allow((adapted, key))
