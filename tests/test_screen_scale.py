# -*- coding: utf-8 -*-
"""坐标适配层：基准 1920×1080 → 物理像素的换算、居中偏移、边界裁剪。"""

import unittest

import screen_scale


class ScaleTests(unittest.TestCase):
    def tearDown(self):
        screen_scale.set_screen_size(None)

    def test_reference_screen_is_identity(self):
        screen_scale.set_screen_size((1920, 1080))

        m = screen_scale.metrics()

        self.assertTrue(m.is_identity)
        self.assertAlmostEqual(1.0, screen_scale.scale())
        self.assertEqual((960, 600), screen_scale.to_screen(960, 600))
        self.assertEqual((7, 200, 202, 500),
                         screen_scale.to_screen_box((7, 200, 202, 500)))

    def test_2560_by_1440_scales_by_four_thirds(self):
        screen_scale.set_screen_size((2560, 1440))

        m = screen_scale.metrics()

        self.assertAlmostEqual(4 / 3, m.factor, places=6)
        self.assertEqual((0, 0), (m.offset_x, m.offset_y))
        self.assertEqual((1280, 800), screen_scale.to_screen(960, 600))
        self.assertEqual((93, 80), screen_scale.to_screen(70, 60))
        self.assertEqual((9, 267, 269, 667),
                         screen_scale.to_screen_box((7, 200, 202, 500), clamp=False))

    def test_sixteen_by_ten_screen_centres_with_offsets(self):
        # 2560×1600：按宽度缩放 4/3 后只有 1440 高，上下各留 80 像素黑边
        screen_scale.set_screen_size((2560, 1600))

        m = screen_scale.metrics()

        self.assertAlmostEqual(4 / 3, m.factor, places=6)
        self.assertEqual((0, 80), (m.offset_x, m.offset_y))
        self.assertEqual((1280, 880), screen_scale.to_screen(960, 600))

    def test_box_is_clamped_into_the_screen(self):
        screen_scale.set_screen_size((2560, 1440))

        # 右下角越界的 ROI 被裁进屏幕，免得 ImageGrab 返回黑块
        self.assertEqual((2533, 1387, 2560, 1440),
                         screen_scale.to_screen_box((1900, 1040, 1990, 1120)))

    def test_box_roundtrip_keeps_reference_coordinates(self):
        screen_scale.set_screen_size((2560, 1440))
        box = (860, 810, 1060, 890)

        self.assertEqual(box, screen_scale.to_ref_box(
            screen_scale.to_screen_box(box)))

    def test_small_screen_shrinks_coordinates(self):
        screen_scale.set_screen_size((1280, 720))

        self.assertAlmostEqual(2 / 3, screen_scale.scale(), places=6)
        self.assertEqual((640, 400), screen_scale.to_screen(960, 600))

    def test_describe_mentions_scale_and_reference(self):
        screen_scale.set_screen_size((2560, 1440))

        text = screen_scale.describe()

        self.assertIn("2560×1440", text)
        self.assertIn("1.3333", text)
        self.assertEqual(133, screen_scale.metrics().percent)

    def test_zero_screen_size_falls_back_to_reference(self):
        screen_scale.set_screen_size((0, 0))

        self.assertAlmostEqual(1.0, screen_scale.scale())
        self.assertEqual((960, 600), screen_scale.to_screen(960, 600))

    def test_override_can_be_cleared(self):
        screen_scale.set_screen_size((2560, 1440))
        self.assertAlmostEqual(4 / 3, screen_scale.scale(), places=6)

        screen_scale.set_screen_size(None)
        width, height = screen_scale.screen_size()
        m = screen_scale.metrics()

        self.assertEqual((width, height), (m.screen_w, m.screen_h))
        self.assertGreater(width, 0)


if __name__ == "__main__":
    unittest.main()
