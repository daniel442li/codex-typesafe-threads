from __future__ import annotations

import argparse
import objc
import os
import threading
from subprocess import run

from AppKit import (
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyRegular,
    NSAppearance,
    NSAttributedString,
    NSBackingStoreBuffered,
    NSButton,
    NSColor,
    NSEvent,
    NSFlagsChangedMask,
    NSFloatingWindowLevel,
    NSFont,
    NSFontAttributeName,
    NSForegroundColorAttributeName,
    NSImage,
    NSImageView,
    NSImageScaleProportionallyUpOrDown,
    NSKeyDownMask,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSScreen,
    NSStatusBar,
    NSTextField,
    NSVariableStatusItemLength,
    NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectMaterialHUDWindow,
    NSVisualEffectStateActive,
    NSVisualEffectView,
    NSWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskFullSizeContentView,
)
from Foundation import NSObject
from Quartz import kCGEventFlagMaskSecondaryFn

from .cli import load_dotenv, project_root
from .codex_open import open_codex_prompt
from .feed import evaluate_threads_parallel, noul_from_record
from .threads import load_threads

OTHER_MODIFIERS = 0x000E0000  # shift, control, option (AppKit/NX bits)
HUD_WIDTH = 620
HUD_HEIGHT = 92


def _rgba(r, g, b, a=1.0):
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a)


def _font(size, weight=None):
    if weight is None:
        return NSFont.systemFontOfSize_(size)
    try:
        return NSFont.systemFontOfSize_weight_(size, weight)
    except Exception:
        return NSFont.systemFontOfSize_(size)


def _label(frame, text, size=12, color=None):
    field = NSTextField.alloc().initWithFrame_(frame)
    field.setBezeled_(False)
    field.setBordered_(False)
    field.setDrawsBackground_(False)
    field.setEditable_(False)
    field.setSelectable_(False)
    field.setFont_(_font(size))
    field.setTextColor_(color or _rgba(0.72, 0.74, 0.78, 1.0))
    field.setStringValue_(text)
    return field


class HudWindow(NSWindow):
    def canBecomeKeyWindow(self):
        return True

    def canBecomeMainWindow(self):
        return True


class FieldDelegate(NSObject):
    controller = None

    def control_textView_doCommandBySelector_(self, control, textView, selector):
        name = str(selector)
        if name in ("insertNewline:", "insertNewlineIgnoringFieldEditor:"):
            self.controller.submit_scan(str(control.stringValue() or "").strip())
            return True
        if name == "cancelOperation:":
            self.controller.hide()
            return True
        return False

    def controlTextDidEndEditing_(self, notification):
        return None


class PopupController(NSObject):
    def init(self):
        self = objc.super(PopupController, self).init()
        if self is None:
            return None
        self._visible = False
        self._fn_down = False
        self._scan_thread = None
        self._status = None
        self._field = None
        self._window = None
        self._delegate = None
        self._status_item = None
        self._build()
        self._install_status_item()
        return self

    def _build(self):
        screen = NSScreen.mainScreen().visibleFrame()
        x = screen.origin.x + (screen.size.width - HUD_WIDTH) / 2
        y = screen.origin.y + screen.size.height * 0.64
        window = HudWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, HUD_WIDTH, HUD_HEIGHT),
            NSWindowStyleMaskBorderless | NSWindowStyleMaskFullSizeContentView,
            NSBackingStoreBuffered,
            False,
        )
        window.setTitle_("")
        window.setLevel_(NSFloatingWindowLevel)
        window.setReleasedWhenClosed_(False)
        window.setHidesOnDeactivate_(False)
        window.setOpaque_(False)
        window.setBackgroundColor_(NSColor.clearColor())
        window.setHasShadow_(True)
        window.setMovableByWindowBackground_(True)
        window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        window.setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua"))
        window.setAnimationBehavior_(2)  # NSWindowAnimationBehaviorUtilityWindow

        chrome = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, HUD_WIDTH, HUD_HEIGHT))
        chrome.setMaterial_(NSVisualEffectMaterialHUDWindow)
        chrome.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
        chrome.setState_(NSVisualEffectStateActive)
        chrome.setWantsLayer_(True)
        chrome.layer().setCornerRadius_(18)
        chrome.layer().setMasksToBounds_(True)
        chrome.layer().setBorderWidth_(1.0)
        chrome.layer().setBorderColor_(_rgba(1.0, 1.0, 1.0, 0.14).CGColor())
        window.setContentView_(chrome)

        icon = NSImageView.alloc().initWithFrame_(NSMakeRect(22, 42, 26, 26))
        symbol = NSImage.imageWithSystemSymbolName_accessibilityDescription_("sparkle.magnifyingglass", None)
        if symbol is None:
            symbol = NSImage.imageWithSystemSymbolName_accessibilityDescription_("magnifyingglass", None)
        if symbol is not None:
            symbol.setTemplate_(True)
            icon.setImage_(symbol)
            icon.setImageScaling_(NSImageScaleProportionallyUpOrDown)
        chrome.addSubview_(icon)

        field = NSTextField.alloc().initWithFrame_(NSMakeRect(56, 40, HUD_WIDTH - 168, 32))
        field.setEditable_(True)
        field.setSelectable_(True)
        field.setEnabled_(True)
        field.setBezeled_(False)
        field.setBordered_(False)
        field.setDrawsBackground_(False)
        field.setFocusRingType_(1)
        field.setFont_(_font(22, 0.23))
        field.setTextColor_(_rgba(0.96, 0.97, 0.99, 1.0))
        placeholder = NSAttributedString.alloc().initWithString_attributes_(
            "Find a Codex thread…",
            {
                NSForegroundColorAttributeName: _rgba(0.55, 0.58, 0.64, 1.0),
                NSFontAttributeName: _font(22, 0.23),
            },
        )
        field.setPlaceholderAttributedString_(placeholder)
        delegate = FieldDelegate.alloc().init()
        delegate.controller = self
        field.setDelegate_(delegate)
        chrome.addSubview_(field)

        send = NSButton.alloc().initWithFrame_(NSMakeRect(HUD_WIDTH - 102, 42, 80, 28))
        send.setTitle_("Open ↩")
        send.setBordered_(False)
        send.setFont_(_font(13, 0.4))
        send.setContentTintColor_(_rgba(0.62, 0.78, 1.0, 1.0))
        send.setKeyEquivalent_("\r")
        send.setTarget_(self)
        send.setAction_("sendClicked:")
        chrome.addSubview_(send)
        window.setDefaultButtonCell_(send.cell())

        status = _label(
            NSMakeRect(56, 14, HUD_WIDTH - 80, 16),
            "Return opens the closest match",
            size=11,
            color=_rgba(0.52, 0.55, 0.60, 1.0),
        )
        chrome.addSubview_(status)

        self._window = window
        self._field = field
        self._status = status
        self._delegate = delegate

    def _install_status_item(self):
        item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        button = item.button()
        symbol = NSImage.imageWithSystemSymbolName_accessibilityDescription_("sparkle.magnifyingglass", None)
        if symbol is None:
            symbol = NSImage.imageWithSystemSymbolName_accessibilityDescription_("magnifyingglass", None)
        if symbol is not None:
            symbol.setTemplate_(True)
            button.setImage_(symbol)
        else:
            button.setTitle_("Codex")
        menu = NSMenu.alloc().init()
        show = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Ask Codex…", "showFromMenu:", "")
        show.setTarget_(self)
        quit_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit", "terminate:", "q")
        quit_item.setTarget_(NSApp)
        menu.addItem_(show)
        menu.addItem_(quit_item)
        item.setMenu_(menu)
        self._status_item = item

    def setStatus_(self, text):
        self._status.setStringValue_(str(text))

    def showFromMenu_(self, _sender):
        self.show()

    def sendClicked_(self, _sender):
        self.submit_scan(str(self._field.stringValue() or ""))

    def finishScan_(self, message):
        self.setStatus_(message)
        self.hide()

    def show(self):
        self._visible = True
        self.setStatus_("Return opens the closest match")
        NSApp.activateIgnoringOtherApps_(True)
        self._window.center()
        self._window.orderFrontRegardless()
        self._window.makeKeyAndOrderFront_(None)
        self._window.makeFirstResponder_(self._field)
        print("popup shown", flush=True)

    def hide(self):
        self._visible = False
        self._window.orderOut_(None)

    def toggle(self):
        if self._visible and self._window.isVisible():
            self.hide()
        else:
            self.show()

    def submit_scan(self, query: str):
        query = (query or str(self._field.stringValue() or "")).strip()
        print(f"submit_scan query={query!r}", flush=True)
        if not query:
            self.setStatus_("Type something first")
            return
        if self._scan_thread and self._scan_thread.is_alive():
            self.setStatus_("Scan already running…")
            return
        self.setStatus_("Scanning Codex threads…")

        def work():
            load_dotenv(project_root() / ".env")
            if not os.environ.get("TYPESAFE_API_KEY"):
                self.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "setStatus:", "TYPESAFE_API_KEY missing", True
                )
                return
            threads = load_threads(limit=20)

            def progress(done, total):
                self.performSelectorOnMainThread_withObject_waitUntilDone_(
                    "setStatus:", f"Scanning {done}/{total}…", True
                )

            records = evaluate_threads_parallel(threads, query, on_progress=progress)
            ranked = []
            for record in records:
                score = noul_from_record(record)
                thread_id = record.get("thread_id")
                if score is None or not thread_id or thread_id == "error":
                    continue
                ranked.append((score, thread_id))
            ranked.sort(reverse=True)
            if ranked:
                run(["open", f"codex://threads/{ranked[0][1]}"], check=False)
                message = f"Opened {ranked[0][1]} ({ranked[0][0]:.2f})"
            else:
                open_codex_prompt(query)
                message = "No scored threads; sent query to new Codex chat"
            self.performSelectorOnMainThread_withObject_waitUntilDone_("finishScan:", message, True)

        self._scan_thread = threading.Thread(target=work, daemon=True)
        self._scan_thread.start()


def main() -> None:
    parser = argparse.ArgumentParser(description="Codex Fn popup")
    parser.add_argument("--show", action="store_true", help="Open the HUD immediately")
    args = parser.parse_args()

    load_dotenv(project_root() / ".env")
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
    controller = PopupController.alloc().init()
    print("Codex popup running. Use the menu bar 'Codex' item, Fn, or Control-Shift-Space.", flush=True)

    def flags_handler(event):
        flags = int(event.modifierFlags())
        down = bool(flags & kCGEventFlagMaskSecondaryFn)
        extras = flags & OTHER_MODIFIERS
        if down and not controller._fn_down and not extras:
            print("Fn detected", flush=True)
            controller.toggle()
        controller._fn_down = down

    def key_handler(event):
        flags = int(event.modifierFlags())
        if event.keyCode() == 49 and (flags & (1 << 18)) and (flags & (1 << 17)):
            print("Control-Shift-Space", flush=True)
            controller.toggle()
            return None
        return event

    NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(NSFlagsChangedMask, flags_handler)
    NSEvent.addLocalMonitorForEventsMatchingMask_handler_(NSFlagsChangedMask, lambda e: (flags_handler(e), e)[1])
    NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(NSKeyDownMask, key_handler)
    NSEvent.addLocalMonitorForEventsMatchingMask_handler_(NSKeyDownMask, key_handler)
    controller.show()
    app.run()


if __name__ == "__main__":
    main()
