import unittest

import flet as ft
import main


class FakeStorage:
    def get(self, key):
        return None

    def set(self, key, value):
        pass


class FakePage:
    def __init__(self, platform):
        self.platform = platform
        self.overlay = []
        self.controls = []
        self.client_storage = FakeStorage()
        self.scroll = "not-initialized"

    def add(self, *controls):
        self.controls.extend(controls)

    def update(self):
        pass

    def open(self, control):
        pass

    def close(self, control):
        pass


class MobileLayoutTests(unittest.TestCase):
    def test_android_tabs_have_bounded_expanded_content(self):
        page = FakePage(ft.PagePlatform.ANDROID)
        main.main(page)

        self.assertIsNone(page.scroll)
        self.assertEqual(len(page.controls), 1)
        root = page.controls[0]
        self.assertIsInstance(root, ft.Column)
        self.assertTrue(root.expand)

        tabs = root.controls[0]
        self.assertIsInstance(tabs, ft.Tabs)
        self.assertTrue(tabs.expand)
        self.assertEqual(len(tabs.tabs), 3)
        self.assertTrue(all(tab.content is not None for tab in tabs.tabs))

        gallery = tabs.tabs[2].content
        grid = next(control for control in gallery.controls if isinstance(control, ft.GridView))
        self.assertLessEqual(grid.child_aspect_ratio, 0.52)
        self.assertGreaterEqual(grid.height, 650)
        self.assertGreaterEqual(grid.max_extent, 200)

        for tab in tabs.tabs:
            self.assertIsInstance(tab.content, ft.Column)
            self.assertEqual(tab.content.scroll, ft.ScrollMode.AUTO)

    def test_windows_layout_uses_same_tab_container(self):
        page = FakePage(ft.PagePlatform.WINDOWS)
        main.main(page)
        root = page.controls[0]
        self.assertIsInstance(root, ft.Column)
        self.assertTrue(root.expand)
        self.assertIsInstance(root.controls[0], ft.Tabs)
        self.assertEqual(len(root.controls[0].tabs), 3)


if __name__ == "__main__":
    unittest.main()
