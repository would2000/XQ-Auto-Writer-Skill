import sys
import unittest
from pathlib import Path


SCRIPTS = (
    Path(__file__).resolve().parents[1]
    / ".agents"
    / "skills"
    / "xq-xscript-compiler"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

import xq_codex_scope as scope  # noqa: E402


class FakeControl:
    def __init__(
        self,
        control_id=0,
        text="",
        *,
        visible=True,
        enabled=True,
        control_type="",
        on_click=None,
        on_right_click=None,
        on_invoke=None,
    ):
        self._control_id = control_id
        self._text = text
        self._visible = visible
        self._enabled = enabled
        self.control_type = control_type
        self.on_click = on_click
        self.on_right_click = on_right_click
        self.on_invoke = on_invoke
        self._descendants = []
        self._children = []
        self._roots = []
        self._selected = False
        self.click_count = 0
        self.right_click_count = 0

    def control_id(self):
        return self._control_id

    def is_visible(self):
        return self._visible

    def is_enabled(self):
        return self._enabled

    def descendants(self, **selector):
        items = list(self._descendants)
        control_type = selector.get("control_type")
        if control_type:
            items = [item for item in items if item.control_type == control_type]
        return items

    def window_text(self):
        return self._text

    def set_edit_text(self, value):
        self._text = value
        if self.on_click:
            self.on_click()

    def click(self):
        self.click_count += 1
        if self.on_click:
            self.on_click()

    def click_input(self, *, button):
        self.right_click_count += 1
        if button != "right":
            raise AssertionError("Only a semantic right-click is expected")
        if self.on_right_click:
            self.on_right_click()

    def invoke(self):
        if self.on_invoke:
            self.on_invoke()

    def select(self):
        self._selected = True

    def is_selected(self):
        return self._selected

    def roots(self):
        return list(self._roots)

    def children(self):
        return list(self._children)

    def text(self):
        return self._text


class FakeWindow(FakeControl):
    def __init__(self, title, class_name, *, process_id=99, visible=True):
        super().__init__(text=title, visible=visible)
        self.class_name = class_name
        self._process_id = process_id

    def process_id(self):
        return self._process_id


class FakeDesktop:
    def __init__(self, windows):
        self._windows = windows

    def windows(self, class_name=None, visible_only=False):
        return [
            item for item in self._windows
            if (class_name is None or item.class_name == class_name)
            and (not visible_only or item.is_visible())
        ]


class XQCodexScopeTests(unittest.TestCase):
    def contract_config(self) -> dict:
        return {
            "codex_scope": {
                "folder_name": "CODEX",
                "action_settle_seconds": 2,
                "state_timeout_seconds": 15,
                "script_types": {
                    "function": {
                        "expected_location": "自訂/CODEX/",
                        "category_selector": {
                            "title": "函數",
                            "control_type": "Button",
                        },
                        "folder_selector": {
                            "title": "CODEX",
                            "control_type": "TreeItem",
                        },
                        "location_readback_selector": {
                            "title": "自訂/CODEX/",
                            "control_type": "Text",
                        },
                    }
                },
            }
        }

    def storage_config(self) -> dict:
        return {
            "new_script_storage_scope": {
                "folder_name": "CODEX",
                "expected_location": "自訂/CODEX/",
                "storage_control_id": 30023,
                "folder_button_control_id": 30003,
                "action_settle_seconds": 1,
                "poll_seconds": 0.25,
                "dialog_timeout_seconds": 2,
                "folder_dialog": {
                    "title": "選擇資料夾",
                    "class_name": "#32770",
                    "tree_control_id": 30065,
                    "custom_root_title": "自訂",
                    "confirm_control_id": 30002,
                    "cancel_control_id": 30003,
                },
                "context_menu": {
                    "class_name": "#32768",
                    "new_folder_title": "新增資料夾",
                },
                "creation_dialog": {
                    "title": "新增資料夾",
                    "class_name": "#32770",
                    "name_control_id": 30021,
                    "confirm_control_id": 30002,
                    "cancel_control_id": 30003,
                },
            }
        }

    def storage_environment(self, codex_count: int):
        clock = [0.0]

        def sleeper(seconds):
            clock[0] += seconds

        storage = FakeControl(30023, "自訂/")
        folder_dialog = FakeWindow("選擇資料夾", "#32770", visible=False)
        popup = FakeWindow("", "#32768", visible=False)
        creation_dialog = FakeWindow("新增資料夾", "#32770", visible=False)

        custom_root = FakeControl(text="自訂")
        custom_root._children = [
            FakeControl(text="CODEX") for _ in range(codex_count)
        ]
        tree = FakeControl(30065)
        tree._roots = [custom_root]
        folder_confirm = FakeControl(30002)
        folder_cancel = FakeControl(
            30003,
            on_click=lambda: setattr(folder_dialog, "_visible", False),
        )
        folder_confirm.on_click = lambda: (
            setattr(storage, "_text", "自訂/CODEX/"),
            setattr(folder_dialog, "_visible", False),
        )
        folder_dialog._descendants = [tree, folder_confirm, folder_cancel]

        folder_button = FakeControl(
            30003,
            on_click=lambda: setattr(folder_dialog, "_visible", True),
        )
        new_script = FakeWindow("新增腳本", "#32770")
        new_script._descendants = [storage, folder_button]

        custom_root.on_right_click = lambda: setattr(popup, "_visible", True)
        new_folder_item = FakeControl(
            text="新增資料夾",
            control_type="MenuItem",
            on_invoke=lambda: (
                setattr(popup, "_visible", False),
                setattr(creation_dialog, "_visible", True),
            ),
        )
        popup._descendants = [new_folder_item]

        creation_confirm = FakeControl(30002, enabled=False)
        name_control = FakeControl(
            30021,
            on_click=lambda: setattr(creation_confirm, "_enabled", True),
        )

        def create_folder():
            custom_root._children.append(FakeControl(text="CODEX"))
            creation_dialog._visible = False

        creation_confirm.on_click = create_folder
        creation_cancel = FakeControl(
            30003,
            on_click=lambda: setattr(creation_dialog, "_visible", False),
        )
        creation_dialog._descendants = [
            name_control,
            creation_confirm,
            creation_cancel,
        ]
        desktop_win32 = FakeDesktop([folder_dialog, creation_dialog])
        desktop_uia = FakeDesktop([popup])
        return {
            "new_script": new_script,
            "custom_root": custom_root,
            "folder_button": folder_button,
            "desktop_win32": desktop_win32,
            "desktop_uia": desktop_uia,
            "sleeper": sleeper,
            "monotonic": lambda: clock[0],
        }

    def test_missing_scope_calibration_fails_before_xq(self) -> None:
        with self.assertRaisesRegex(scope.CodexScopeError, "refusing to touch XQ"):
            scope.load_script_scope_contract({}, "function")

    def test_scope_requires_exact_folder_location_and_slow_wait(self) -> None:
        contract = scope.load_script_scope_contract(self.contract_config(), "function")
        self.assertEqual(contract.folder_name, "CODEX")
        self.assertEqual(contract.expected_location, "自訂/CODEX/")
        self.assertGreaterEqual(contract.action_settle_seconds, 1)
        bad = self.contract_config()
        bad["codex_scope"]["script_types"]["function"]["expected_location"] = "自訂/"
        with self.assertRaisesRegex(scope.CodexScopeError, "expected_location"):
            scope.load_script_scope_contract(bad, "function")

    def test_storage_contract_requires_exact_location_and_timing(self) -> None:
        contract = scope.load_new_script_storage_contract(self.storage_config())
        self.assertEqual(contract.expected_location, "自訂/CODEX/")
        self.assertEqual(contract.folder_tree_control_id, 30065)
        self.assertGreaterEqual(contract.action_settle_seconds, 1)
        bad = self.storage_config()
        bad["new_script_storage_scope"]["expected_location"] = "自訂/"
        with self.assertRaisesRegex(scope.CodexScopeError, "expected_location"):
            scope.load_new_script_storage_contract(bad)

    def test_storage_contract_applies_requested_pace_without_bypassing_floor(self) -> None:
        config = self.storage_config()
        config["new_script_storage_scope"]["action_settle_seconds"] = 2.5
        config["new_script_storage_scope"]["dialog_timeout_seconds"] = 3
        config["ui_pacing"] = {"default_level": 7}
        contract = scope.load_new_script_storage_contract(config)
        self.assertEqual(contract.ui_pacing.level, 7)
        self.assertAlmostEqual(contract.action_settle_seconds, 2.5 / 1.5)

    def test_existing_storage_codex_is_selected_without_creation(self) -> None:
        environment = self.storage_environment(codex_count=1)
        result = scope.ensure_new_script_codex_storage(
            environment["new_script"],
            scope.load_new_script_storage_contract(self.storage_config()),
            desktop_win32=environment["desktop_win32"],
            desktop_uia=environment["desktop_uia"],
            sleeper=environment["sleeper"],
            monotonic=environment["monotonic"],
        )
        self.assertFalse(result["created_folder"])
        self.assertEqual(result["location"], "自訂/CODEX/")
        self.assertEqual(environment["custom_root"].right_click_count, 0)

    def test_missing_storage_codex_is_created_and_selected(self) -> None:
        environment = self.storage_environment(codex_count=0)
        result = scope.ensure_new_script_codex_storage(
            environment["new_script"],
            scope.load_new_script_storage_contract(self.storage_config()),
            desktop_win32=environment["desktop_win32"],
            desktop_uia=environment["desktop_uia"],
            sleeper=environment["sleeper"],
            monotonic=environment["monotonic"],
        )
        self.assertTrue(result["created_folder"])
        self.assertEqual(result["codex_direct_child_count"], 1)
        self.assertEqual(len(environment["custom_root"].children()), 1)
        self.assertEqual(environment["custom_root"].right_click_count, 1)

    def test_dry_run_missing_storage_codex_is_not_created(self) -> None:
        environment = self.storage_environment(codex_count=0)
        result = scope.ensure_new_script_codex_storage(
            environment["new_script"],
            scope.load_new_script_storage_contract(self.storage_config()),
            create_missing=False,
            desktop_win32=environment["desktop_win32"],
            desktop_uia=environment["desktop_uia"],
            sleeper=environment["sleeper"],
            monotonic=environment["monotonic"],
        )
        self.assertFalse(result["created_folder"])
        self.assertTrue(result["would_create_folder"])
        self.assertFalse(result["readback_verified"])
        self.assertEqual(result["codex_direct_child_count"], 0)
        self.assertEqual(len(environment["custom_root"].children()), 0)
        self.assertEqual(environment["custom_root"].right_click_count, 0)
        self.assertFalse(environment["desktop_win32"]._windows[0].is_visible())

    def test_duplicate_storage_codex_is_refused(self) -> None:
        environment = self.storage_environment(codex_count=2)
        with self.assertRaisesRegex(scope.CodexScopeError, "at most one"):
            scope.ensure_new_script_codex_storage(
                environment["new_script"],
                scope.load_new_script_storage_contract(self.storage_config()),
                desktop_win32=environment["desktop_win32"],
                desktop_uia=environment["desktop_uia"],
                sleeper=environment["sleeper"],
                monotonic=environment["monotonic"],
            )

    def test_non_timeout_cleanup_closes_unique_folder_dialog(self) -> None:
        environment = self.storage_environment(codex_count=2)
        contract = scope.load_new_script_storage_contract(self.storage_config())
        with self.assertRaisesRegex(scope.CodexScopeError, "at most one"):
            scope.ensure_new_script_codex_storage(
                environment["new_script"],
                contract,
                desktop_win32=environment["desktop_win32"],
                desktop_uia=environment["desktop_uia"],
                sleeper=environment["sleeper"],
                monotonic=environment["monotonic"],
            )
        closed = scope.cancel_new_script_storage_dialogs(
            environment["new_script"],
            contract,
            desktop_win32=environment["desktop_win32"],
            sleeper=environment["sleeper"],
        )
        self.assertEqual(closed, ["type-scoped folder dialog"])
        self.assertFalse(environment["desktop_win32"]._windows[0].is_visible())

    def test_folder_dialog_timeout_stops_after_one_input(self) -> None:
        environment = self.storage_environment(codex_count=0)
        environment["folder_button"].on_click = None
        with self.assertRaisesRegex(scope.CodexScopeWaitError, "Timed out"):
            scope.ensure_new_script_codex_storage(
                environment["new_script"],
                scope.load_new_script_storage_contract(self.storage_config()),
                desktop_win32=environment["desktop_win32"],
                desktop_uia=environment["desktop_uia"],
                sleeper=environment["sleeper"],
                monotonic=environment["monotonic"],
            )
        self.assertEqual(environment["folder_button"].click_count, 1)
        self.assertEqual(environment["custom_root"].right_click_count, 0)

    def test_private_root_location_is_never_authorized_for_cleanup(self) -> None:
        record = {
            "created": True,
            "name": "CodexDoc",
            "script_type": "function",
            "type_readback": "function",
            "storage_location": "自訂/CODEX/",
        }
        self.assertTrue(scope.authorize_manifest_document(
            record,
            readback_name="CodexDoc",
            readback_type="function",
            readback_location="自訂/CODEX/",
        ))
        self.assertFalse(scope.authorize_manifest_document(
            record,
            readback_name="CodexDoc",
            readback_type="function",
            readback_location="自訂/",
        ))
        changed = dict(record, storage_location="自訂/")
        self.assertFalse(scope.authorize_manifest_document(
            changed,
            readback_name="CodexDoc",
            readback_type="function",
            readback_location="自訂/CODEX/",
        ))


if __name__ == "__main__":
    unittest.main()
