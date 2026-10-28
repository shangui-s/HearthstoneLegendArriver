# -*- coding: utf-8 -*-
"""环境自检：Python 版本判定、依赖缺失/版本不符的结论、requirements 覆盖度。"""

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import selfcheck

ROOT = Path(__file__).resolve().parent.parent


class PythonVersionTests(unittest.TestCase):
    def test_accepts_the_recommended_312_64bit(self):
        item = selfcheck.python_item(version=(3, 12, 14), bits=64)

        self.assertEqual(selfcheck.STATUS_OK, item["status"])
        self.assertIn("3.12.14", item["detail"])

    def test_rejects_311(self):
        item = selfcheck.python_item(version=(3, 11, 9), bits=64)

        self.assertEqual(selfcheck.STATUS_FAIL, item["status"])
        self.assertIn("3.12", item["hint"])

    def test_rejects_313_and_newer(self):
        for version in ((3, 13, 1), (3, 14, 0)):
            with self.subTest(version=version):
                item = selfcheck.python_item(version=version, bits=64)
                self.assertEqual(selfcheck.STATUS_FAIL, item["status"])

    def test_rejects_32bit_even_on_312(self):
        item = selfcheck.python_item(version=(3, 12, 14), bits=32)

        self.assertEqual(selfcheck.STATUS_FAIL, item["status"])
        self.assertIn("32 位", item["detail"])

    def test_running_interpreter_is_the_recommended_one(self):
        """本项目实测环境就是 3.12.x；这条挂了说明用了别的解释器跑测试。"""
        item = selfcheck.python_item()

        self.assertEqual(selfcheck.STATUS_OK, item["status"])
        self.assertEqual((3, 12), selfcheck.EXPECTED_PYTHON)


class DependencyManifestTests(unittest.TestCase):
    def test_requirements_pins_are_parsed(self):
        pins = selfcheck._requirements_pins()

        self.assertEqual("2.6.2", pins["paddlepaddle"])
        self.assertEqual("2.5.2", pins["numpy"])
        self.assertEqual("8.4.2", pins["click"])

    def test_manifest_covers_every_requirement(self):
        """requirements.txt 里每个包都要能在自检清单里看到（不许漏检）。"""
        pins = selfcheck._requirements_pins()
        covered = {selfcheck._normalize(dist)
                   for spec in selfcheck.DEPENDENCIES for dist in spec["dist"]}

        self.assertEqual(set(), set(pins) - covered)

    def test_manifest_only_lists_known_packages(self):
        pins = selfcheck._requirements_pins()
        listed = {selfcheck._normalize(dist)
                  for spec in selfcheck.DEPENDENCIES for dist in spec["dist"]}

        # opencv-python 是 opencv-python-headless 的合法替代实现，额外允许。
        self.assertEqual({"opencv-python"}, listed - set(pins))

    def test_python_312_specific_packages_are_checked(self):
        keys = {selfcheck._normalize(spec["dist"][0])
                for spec in selfcheck.DEPENDENCIES}

        for expected in ("paddlepaddle", "paddleocr", "pywin32", "numpy",
                         "opencv-python-headless", "pillow", "pynput",
                         "keyboard", "psutil", "requests"):
            self.assertIn(expected, keys)

    def test_requirements_parsing_tolerates_a_broken_file(self):
        pins = selfcheck._requirements_pins("# 注释\n随便写点什么\n\n")

        self.assertEqual({}, pins)


class DependencyItemTests(unittest.TestCase):
    def test_missing_package_fails_with_pip_hint(self):
        def importer(name):
            if name == "paddleocr":
                raise ImportError("No module named 'paddleocr'")
            return object()

        items = selfcheck.dependency_items(importer=importer,
                                          version_reader=lambda dists: "1.0",
                                          pins={})
        item = next(i for i in items if i["key"] == "paddleocr")

        self.assertEqual(selfcheck.STATUS_FAIL, item["status"])
        self.assertIn("ImportError", item["detail"])
        self.assertIn("pip install", item["hint"])

    def test_version_mismatch_warns_but_still_counts_as_usable(self):
        items = selfcheck.dependency_items(importer=lambda name: object(),
                                          version_reader=lambda dists: "9.9.9",
                                          pins={"numpy": "2.5.2"})
        item = next(i for i in items if i["key"] == "numpy")

        self.assertEqual(selfcheck.STATUS_WARN, item["status"])
        self.assertIn("2.5.2", item["detail"])
        self.assertTrue(item["required"])

    def test_click_is_checked_by_metadata_only(self):
        """仓库自带的 click.py 会遮蔽第三方 click，所以只认发行包元数据。"""
        items = selfcheck.dependency_items(importer=lambda name: object(),
                                          version_reader=lambda dists: None,
                                          pins={})
        item = next(i for i in items if i["key"] == "click")

        self.assertEqual(selfcheck.STATUS_FAIL, item["status"])
        self.assertIn("click", item["detail"])

    def test_optional_dependency_is_not_required(self):
        items = selfcheck.dependency_items(
            importer=lambda name: object(),
            version_reader=lambda dists: (None if "setuptools" in dists else "1.0"),
            pins={})
        item = next(i for i in items if i["key"] == "setuptools")

        self.assertEqual(selfcheck.STATUS_FAIL, item["status"])
        self.assertFalse(item["required"])
        self.assertIn("可选", item["hint"])

    def test_unreadable_version_is_only_a_warning(self):
        items = selfcheck.dependency_items(importer=lambda name: object(),
                                          version_reader=lambda dists: None,
                                          pins={})
        item = next(i for i in items if i["key"] == "numpy")

        self.assertEqual(selfcheck.STATUS_WARN, item["status"])


class RunChecksTests(unittest.TestCase):
    @staticmethod
    def _ok_environment():
        return [selfcheck._item("env", "测试环境项", selfcheck.STATUS_OK, "ok")]

    def _run(self, environment=None, **kwargs):
        kwargs.setdefault("importer", lambda name: object())
        kwargs.setdefault("version_reader", lambda dists: "1.0.0")
        kwargs.setdefault("pins", {})
        kwargs.setdefault("version", (3, 12, 14))
        kwargs.setdefault("bits", 64)
        if environment is None:
            kwargs.setdefault("environment_probe", self._ok_environment)
        elif callable(environment):
            kwargs.setdefault("environment_probe", environment)
        else:
            kwargs.setdefault("environment_probe", lambda: environment)
        return selfcheck.run_checks(**kwargs)

    def test_everything_present_is_ok(self):
        result = self._run()

        self.assertTrue(result["ok"])
        self.assertEqual(0, result["failed"])
        self.assertIn("全部达标", result["summary"])
        self.assertEqual(result["total"], len(result["items"]))

    def test_environment_failure_makes_the_check_fail(self):
        env = [selfcheck._item("admin", "管理员权限", selfcheck.STATUS_FAIL,
                               "当前不是管理员", "以管理员身份运行")]
        result = self._run(environment=env)

        self.assertFalse(result["ok"])
        self.assertEqual(1, result["failed"])
        self.assertIn("管理员权限", result["summary"])

    def test_probe_exception_is_contained_as_a_warning(self):
        def broken():
            raise RuntimeError("探测器炸了")

        result = self._run(environment=broken)

        self.assertTrue(result["ok"])
        item = next(i for i in result["items"] if i["key"] == "environment")
        self.assertEqual(selfcheck.STATUS_WARN, item["status"])
        self.assertIn("探测器炸了", item["detail"])

    def test_importer_exception_never_escapes(self):
        def importer(name):
            raise RuntimeError("boom")

        result = self._run(importer=importer)

        self.assertFalse(result["ok"])
        self.assertGreater(result["failed"], 0)

    def test_result_is_json_serializable_and_report_is_readable(self):
        result = self._run(environment=lambda: [
            selfcheck._item("admin", "管理员权限", selfcheck.STATUS_FAIL,
                            "当前不是管理员", "以管理员身份运行")])
        text = json.dumps(result, ensure_ascii=False)
        report = selfcheck.format_report(result)

        self.assertIn("管理员权限", text)
        self.assertIn("[自检]", report)
        self.assertIn("❌", report)
        self.assertIn("以管理员身份运行", report)

    def test_warning_summary_when_only_optional_items_differ(self):
        env = [selfcheck._item("hearthstone", "炉石窗口", selfcheck.STATUS_WARN,
                               "没找到", "", False)]
        result = self._run(environment=env)

        self.assertTrue(result["ok"])
        self.assertEqual(1, result["warned"])
        self.assertIn("提示", result["summary"])


class ResolutionRequirementTests(unittest.TestCase):
    """分辨率与显示缩放都是「推荐项」：不一致只给 ⚠️，不拦运行。"""

    CONFIG = SimpleNamespace(desktop_size=(1920, 1080), desktop_dpi=96)

    def _environment_items(self, size, dpi=96):
        def ok_item(key, label, required):
            return selfcheck._item(key, label, selfcheck.STATUS_OK, "", "",
                                   required)

        with mock.patch.object(selfcheck, "_is_admin", lambda: True), \
                mock.patch.object(selfcheck, "_current_screen_size",
                                  lambda: size), \
                mock.patch.object(selfcheck, "_current_dpi", lambda: dpi), \
                mock.patch.object(selfcheck, "_hearthstone_item",
                                  lambda: ok_item("hearthstone", "炉石窗口", False)), \
                mock.patch.object(selfcheck, "_log_dir_item",
                                  lambda: ok_item("log-root", "炉石日志目录", True)), \
                mock.patch.object(selfcheck, "_ocr_model_item",
                                  lambda: ok_item("ocr-model", "OCR 模型目录", False)):
            items = selfcheck.environment_items(self.CONFIG)
        return {item["key"]: item for item in items}

    def test_matching_resolution_is_ok_and_not_required(self):
        item = self._environment_items((1920, 1080))["resolution"]

        self.assertEqual(selfcheck.STATUS_OK, item["status"])
        self.assertFalse(item["required"])

    def test_sixteen_by_nine_screen_is_converted_to_ok(self):
        # 2560×1440 与基准同比例：按比例换算后视为达标，不再是提示项。
        item = self._environment_items((2560, 1440))["resolution"]

        self.assertEqual(selfcheck.STATUS_OK, item["status"])
        self.assertFalse(item["required"])
        self.assertIn("2560×1440", item["detail"])
        self.assertIn("1.3333", item["detail"])

    def test_non_sixteen_by_nine_screen_only_warns(self):
        # 16:10 这类不同比例：游戏会留黑边，只提示不拦运行。
        item = self._environment_items((2560, 1600))["resolution"]

        self.assertEqual(selfcheck.STATUS_WARN, item["status"])
        self.assertFalse(item["required"])
        self.assertIn("2560×1600", item["detail"])
        self.assertIn("1920×1080", item["hint"])

    def test_non_100_scaling_is_ok(self):
        # 缩放由坐标换算吸收，125%/150% 都是 OK（结论里会说明已按物理像素换算）。
        item = self._environment_items((1920, 1080), dpi=120)["dpi"]

        self.assertEqual(selfcheck.STATUS_OK, item["status"])
        self.assertFalse(item["required"])
        self.assertIn("125%", item["detail"])
        self.assertIn("DPI 感知", item["detail"])

    def test_matching_scaling_is_ok_and_not_required(self):
        item = self._environment_items((1920, 1080), dpi=96)["dpi"]

        self.assertEqual(selfcheck.STATUS_OK, item["status"])
        self.assertFalse(item["required"])

    def test_resolution_and_scaling_mismatch_do_not_block_the_run(self):
        env = [selfcheck._item("resolution", "屏幕分辨率", selfcheck.STATUS_WARN,
                               "2560×1440（脚本按 1920×1080 校准）", "提示", False),
               selfcheck._item("dpi", "显示缩放（DPI）", selfcheck.STATUS_WARN,
                               "120（125%，脚本按 100% 校准）", "提示", False)]

        result = selfcheck.run_checks(
            version=(3, 12, 14), bits=64, importer=lambda name: object(),
            version_reader=lambda dists: "1.0", pins={},
            environment_probe=lambda: env)

        self.assertTrue(result["ok"])
        self.assertEqual(0, result["failed"])
        self.assertEqual(2, result["warned"])


class RealEnvironmentTests(unittest.TestCase):
    """真跑一遍自检：确认依赖确实能 import，且解释器是 3.12。"""

    @classmethod
    def setUpClass(cls):
        cls.result = selfcheck.run_checks()

    def test_python_312_is_reported_ok(self):
        item = next(i for i in self.result["items"] if i["key"] == "python")

        self.assertEqual(selfcheck.STATUS_OK, item["status"])
        self.assertTrue(self.result["python"].startswith("3.12"))

    def test_all_declared_dependencies_are_importable(self):
        failing = [i["label"] for i in self.result["items"]
                   if i["key"] in {"pywin32", "opencv-python-headless", "numpy",
                                   "pillow", "paddleocr", "paddlepaddle"}
                   and i["status"] == selfcheck.STATUS_FAIL]

        self.assertEqual([], failing)

    def test_environment_items_are_present(self):
        keys = {i["key"] for i in self.result["items"]}

        self.assertLessEqual({"admin", "resolution", "dpi", "log-root"}, keys)


if __name__ == "__main__":
    unittest.main()
