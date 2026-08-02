import sys
import unittest
from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageDraw


SCRIPTS = (
    Path(__file__).resolve().parents[1]
    / ".agents"
    / "skills"
    / "xq-xscript-compiler"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

import xq_category_selector as selector  # noqa: E402


class FakeRect:
    def __init__(self, left=10, top=20, width=300, height=586):
        self.left = left
        self.top = top
        self.right = left + width
        self.bottom = top + height
        self._width = width
        self._height = height

    def width(self):
        return self._width

    def height(self):
        return self._height


class FakeHost:
    def __init__(self, image):
        self.image = image
        self.rect = FakeRect()

    def rectangle(self):
        return self.rect

    def client_rect(self):
        return FakeRect(left=0, top=0, width=300, height=500)

    def capture_as_image(self):
        return self.image


class FakePane:
    def __init__(self):
        self.rect = FakeRect(top=40, height=566)

    def rectangle(self):
        return self.rect


class FakeTree:
    def __init__(self):
        self.handle = 900
        self.focus_count = 0
        self.rect = FakeRect(left=10, top=50, width=300, height=500)
        self.image = Image.new("RGB", (300, 500), (255, 255, 255))
        draw = ImageDraw.Draw(self.image)
        draw.rectangle((10, 30, 150, 50), fill=(102, 182, 255))
        draw.rectangle((20, 36, 100, 43), fill=(0, 0, 0))

    def set_focus(self):
        self.focus_count += 1

    def rectangle(self):
        return self.rect

    def client_rect(self):
        return FakeRect(left=0, top=0, width=300, height=500)

    def capture_as_image(self):
        return self.image


class FakeItem:
    def __init__(self, text):
        self._text = text
        self.selected = False
        self.rect = FakeRect(left=10, top=30, width=140, height=20)

    def text(self):
        return self._text

    def select(self):
        self.selected = True

    def is_selected(self):
        return self.selected

    def rectangle(self):
        return self.rect

    def client_rect(self):
        return self.rect


class FakeCodex:
    def __init__(self, names):
        self.items = [FakeItem(name) for name in names]

    def children(self):
        return list(self.items)


class FakeWindow:
    def __init__(self, title="XScript 編輯器 - [Other(交易)]"):
        self.handle = 700
        self.title = title

    def window_text(self):
        return self.title


class XQCategorySelectorTests(unittest.TestCase):
    def config(self) -> dict:
        return {
            "ui_pacing": {"default_level": 5},
            "formula_category_switch": {
                "method": "screenshot_formula_tabs_v1",
                "automatic_switch_available": True,
                "pane_control_ids": {
                    "indicator": 1,
                    "screener": 4,
                    "alert": 2,
                    "autotrade": 7,
                    "function": 3,
                },
                "tab_order": [
                    "indicator", "screener", "alert", "autotrade", "function"
                ],
                "screenshot_detection": {
                    "minimum_tab_width_ratio": 0.1,
                    "maximum_tab_width_ratio": 0.22,
                    "maximum_gap_pixels": 4,
                    "boundary_tolerance_pixels": 3,
                    "required_stable_rows": 2,
                    "inactive_color_tolerance": 18,
                    "active_color_minimum_distance": 30,
                },
                "action_settle_seconds": 2.5,
                "poll_seconds": 0.25,
                "late_after_seconds": 4,
                "state_timeout_seconds": 15,
            },
        }

    def evidence(self, pane_id: int, codex_count: int = 1) -> dict:
        return {
            "visible_formula_pane_count": 1,
            "formula_pane_control_id": pane_id,
            "visible_tree_count": 1,
            "custom_root_count": 1,
            "codex_direct_child_count": codex_count,
        }

    def image(self, active_index: int) -> Image.Image:
        image = Image.new("RGB", (300, 586), (240, 240, 240))
        draw = ImageDraw.Draw(image)
        bounds = [(41, 83), (85, 127), (129, 171), (173, 221), (223, 265)]
        for index, (left, right) in enumerate(bounds):
            color = (237, 207, 110) if index == active_index else (255, 255, 255)
            draw.rectangle((left, 12, right, 18), fill=color)
        return image

    def context(self, window, pane_id, image, names=("Target",), codex_count=1):
        codex = FakeCodex(names) if codex_count == 1 else None
        return selector.FormulaContext(
            window=window,
            pane=FakePane(),
            host=FakeHost(image),
            tree=FakeTree(),
            custom_root=object(),
            codex_root=codex,
            evidence=self.evidence(pane_id, codex_count),
        )

    def test_contract_requires_screenshot_method_and_no_stored_coordinates(self) -> None:
        contract = selector.load_contract(self.config())
        self.assertEqual(contract.method, "screenshot_formula_tabs_v1")
        self.assertEqual(contract.tab_order, selector.TAB_ORDER)
        bad = self.config()
        bad["formula_category_switch"]["method"] = "manual_only"
        with self.assertRaisesRegex(selector.CategorySelectorError, "screenshot_formula_tabs_v1"):
            selector.load_contract(bad)
        self.assertNotIn("coordinates", self.config()["formula_category_switch"])
        self.assertNotIn("ratios", self.config()["formula_category_switch"])

    def test_screenshot_detects_five_stable_tabs_and_active_fill(self) -> None:
        result = selector.detect_formula_tabs(
            self.image(3), 20, 3, selector.load_contract(self.config())
        )
        self.assertEqual(len(result["relative_tab_bounds"]), 5)
        self.assertGreaterEqual(result["stable_row_count"], 2)
        self.assertEqual(result["visual_active_index"], 3)
        self.assertFalse(result["image_persisted"])
        self.assertFalse(result["fixed_screen_coordinates"])

    def test_screenshot_rejects_wrong_active_index_or_ambiguous_rows(self) -> None:
        contract = selector.load_contract(self.config())
        with self.assertRaisesRegex(selector.CategorySelectorError, "stable five-tab"):
            selector.detect_formula_tabs(self.image(3), 20, 2, contract)
        blank = Image.new("RGB", (300, 586), (240, 240, 240))
        with self.assertRaisesRegex(selector.CategorySelectorError, "stable five-tab"):
            selector.detect_formula_tabs(blank, 20, 3, contract)

    def test_already_active_category_sends_no_input(self) -> None:
        window = FakeWindow()
        context = self.context(window, 3, self.image(4))
        clicks = []
        result = selector.switch_category(
            window,
            "function",
            selector.load_contract(self.config()),
            foreground_guard=lambda _: (_ for _ in ()).throw(AssertionError("no guard")),
            clicker=lambda **kwargs: clicks.append(kwargs),
            inspect_context=lambda _: context,
        )
        self.assertFalse(result["category_switch_input_sent"])
        self.assertEqual(clicks, [])

    def test_cross_category_uses_one_screenshot_derived_click_then_readback(self) -> None:
        window = FakeWindow()
        initial = self.context(window, 7, self.image(3))
        final = self.context(window, 3, self.image(4))
        state = {"clicked": False}
        clicks = []

        def clicker(**kwargs):
            clicks.append(kwargs)
            state["clicked"] = True

        result = selector.switch_category(
            window,
            "function",
            selector.load_contract(self.config()),
            foreground_guard=lambda _: {"foreground_verified": True},
            clicker=clicker,
            inspect_context=lambda _: final if state["clicked"] else initial,
        )
        self.assertEqual(len(clicks), 1)
        self.assertTrue(result["category_switch_input_sent"])
        self.assertEqual(result["coordinate_mode"], "screenshot_derived_formula_host_local")
        self.assertFalse(result["screen_click_point_persisted"])
        self.assertEqual(result["active_type"], "function")

    def test_foreground_failure_stops_before_click(self) -> None:
        window = FakeWindow()
        initial = self.context(window, 7, self.image(3))
        clicks = []
        with self.assertRaisesRegex(RuntimeError, "foreground"):
            selector.switch_category(
                window,
                "function",
                selector.load_contract(self.config()),
                foreground_guard=lambda _: (_ for _ in ()).throw(RuntimeError("foreground refused")),
                clicker=lambda **kwargs: clicks.append(kwargs),
                inspect_context=lambda _: initial,
            )
        self.assertEqual(clicks, [])

    def test_timeout_sends_only_one_category_click(self) -> None:
        config = self.config()
        config["formula_category_switch"].update({
            "poll_seconds": 0.25,
            "late_after_seconds": 0.25,
            "state_timeout_seconds": 0.5,
        })
        contract = selector.load_contract(config)
        window = FakeWindow()
        initial = self.context(window, 7, self.image(3))
        clicks = []
        clock = [0.0]
        with self.assertRaises(selector.CategorySelectorWaitError):
            selector.switch_category(
                window,
                "function",
                contract,
                foreground_guard=lambda _: {"foreground_verified": True},
                clicker=lambda **kwargs: clicks.append(kwargs),
                inspect_context=lambda _: initial,
                clock=lambda: clock[0],
                sleeper=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
            )
        self.assertEqual(len(clicks), 1)

    def test_target_category_with_missing_codex_is_refused_after_readback(self) -> None:
        window = FakeWindow()
        initial = self.context(window, 7, self.image(3))
        final = self.context(window, 3, self.image(4), codex_count=0)
        state = {"clicked": False}
        with self.assertRaisesRegex(selector.CategorySelectorError, "codex_scope"):
            selector.switch_category(
                window,
                "function",
                selector.load_contract(self.config()),
                foreground_guard=lambda _: {"foreground_verified": True},
                clicker=lambda **_: state.__setitem__("clicked", True),
                inspect_context=lambda _: final if state["clicked"] else initial,
            )

    def test_existing_script_open_requires_unique_direct_codex_match(self) -> None:
        contract = selector.load_contract(self.config())
        window = FakeWindow()
        for names, expected in (((), "found 0"), (("Target", "Target"), "found 2")):
            context = self.context(window, 3, self.image(4), names=names)
            with self.assertRaisesRegex(selector.CategorySelectorError, expected):
                selector.open_existing_codex_script(
                    window,
                    "function",
                    "Target",
                    contract,
                    foreground_guard=lambda _: {"foreground_verified": True},
                    double_clicker=lambda **_: None,
                    inspect_context=lambda _, context=context: context,
                    verify_active=lambda *_: False,
                )

    def test_existing_script_open_uses_screenshot_double_click_and_exact_readback(self) -> None:
        contract = replace(selector.load_contract(self.config()), action_settle_seconds=0.01)
        window = FakeWindow("XScript 編輯器 - [Other(函數)]")
        context = self.context(window, 3, self.image(4), names=("Target",))
        state = {"opened": False}

        clicks = []

        def double_clicker(**kwargs):
            clicks.append(kwargs)
            state["opened"] = True
            window.title = "XScript 編輯器 - [Target(函數)]"

        result = selector.open_existing_codex_script(
            window,
            "function",
            "Target",
            contract,
            foreground_guard=lambda _: {"foreground_verified": True},
            double_clicker=double_clicker,
            point_to_screen=lambda _, x, y: (10 + x, 50 + y),
            inspect_context=lambda _: context,
            verify_active=lambda *_: state["opened"],
            sleeper=lambda _: None,
        )
        self.assertTrue(result["open_input_sent"])
        self.assertTrue(result["readback_verified"])
        self.assertTrue(context.codex_root.items[0].selected)
        self.assertEqual(len(clicks), 1)
        self.assertFalse(result["visual_target"]["image_persisted"])

    def test_tree_target_uses_only_the_visible_intersection_when_text_is_clipped(self) -> None:
        tree = FakeTree()
        item = FakeItem("LongTargetName")
        item.rect = FakeRect(left=88, top=30, width=240, height=20)
        result = selector.detect_tree_item_target(tree, item)
        self.assertTrue(result["item_was_partially_clipped"])
        self.assertEqual(result["relative_item_bounds"], [88, 30, 300, 50])
        self.assertGreaterEqual(result["relative_click_point"]["x"], 88)
        self.assertLess(result["relative_click_point"]["x"], 300)
        self.assertFalse(result["fixed_screen_coordinates"])

    def test_already_active_script_sends_no_open_input(self) -> None:
        window = FakeWindow("XScript 編輯器 - [Target(函數)]")
        result = selector.open_existing_codex_script(
            window,
            "function",
            "Target",
            selector.load_contract(self.config()),
            foreground_guard=lambda _: (_ for _ in ()).throw(AssertionError("no guard")),
            double_clicker=lambda **_: (_ for _ in ()).throw(AssertionError("no click")),
            verify_active=lambda *_: True,
        )
        self.assertFalse(result["open_input_sent"])

    def test_source_forbids_fixed_geometry_and_temporary_route_documents(self) -> None:
        source = (SCRIPTS / "xq_category_selector.py").read_text(encoding="utf-8").lower()
        for forbidden in (
            "wm_command",
            "showwindow(.*pane",
            "temporary routing document",
            "tab_center_x_ratios",
            "fixed_screen_coordinates\": true",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
