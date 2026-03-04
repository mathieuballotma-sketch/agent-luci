# test_hud_minimal.py
import objc
from PyObjCTools import AppHelper
import AppKit
from AppKit import (
    NSApplication, NSPanel, NSRect, NSMakeRect, NSScreen,
    NSHUDWindowMask, NSClosableWindowMask, NSResizableWindowMask,
    NSFloatingWindowLevel, NSColor, NSObject
)

class MinimalHUD(NSObject):
    def init(self):
        self = objc.super(MinimalHUD, self).init()
        if self is None:
            return None
        self.window = None
        return self

    def create_window(self):
        screen = NSScreen.mainScreen()
        screen_rect = screen.visibleFrame()
        rect = NSMakeRect(100, 100, 400, 300)

        style_mask = NSHUDWindowMask | NSClosableWindowMask | NSResizableWindowMask
        self.window = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style_mask, AppKit.NSBackingStoreBuffered, False
        )
        self.window.setTitle_("Test HUD Minimal")
        self.window.setFloatingPanel_(True)
        self.window.setLevel_(NSFloatingWindowLevel)
        self.window.setHidesOnDeactivate_(False)
        self.window.setAlphaValue_(0.95)
        self.window.setBackgroundColor_(NSColor.darkGrayColor())
        self.window.makeKeyAndOrderFront_(None)

    def start(self):
        self.create_window()
        AppHelper.runConsoleEventLoop()

if __name__ == "__main__":
    hud = MinimalHUD.alloc().init()
    hud.start()