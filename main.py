from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from functools import lru_cache
from urllib.parse import quote_plus

# Chromium's low-end mode reduces memory pressure when many tabs are open.
# Keep hardware acceleration enabled: disabling it can make this laptop slower.
_CHROMIUM_FLAGS = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").strip()
_LOW_END_FLAG = "--enable-low-end-device-mode"
if _LOW_END_FLAG not in _CHROMIUM_FLAGS:
    _CHROMIUM_FLAGS = f"{_CHROMIUM_FLAGS} {_LOW_END_FLAG}".strip()
# Avoid starting optional Chromium features that are not needed for normal browsing.
# Keep GPU acceleration and the Chromium sandbox enabled for speed and security.
for _flag in ("--disable-features=Translate,MediaRouter", "--disable-logging"):
    _flag_name = _flag.split("=", 1)[0]
    if _flag_name not in _CHROMIUM_FLAGS:
        _CHROMIUM_FLAGS = f"{_CHROMIUM_FLAGS} {_flag}".strip()
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = _CHROMIUM_FLAGS

from PySide6.QtCore import Qt, QUrl, QStandardPaths, QTimer, Signal, QSize, QByteArray
from PySide6.QtGui import QAction, QKeySequence, QFont, QIcon, QColor, QShortcut, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QToolButton, QTabWidget, QLabel, QMenu, QMessageBox, QFileDialog,
    QDialog, QListWidget, QListWidgetItem, QPushButton, QFormLayout, QComboBox,
    QCheckBox, QDialogButtonBox, QColorDialog, QFrame, QStatusBar, QProgressBar,
    QInputDialog, QTabBar, QSizePolicy
)
from PySide6.QtWebEngineCore import (
    QWebEngineProfile, QWebEnginePage, QWebEngineSettings,
    QWebEngineDownloadRequest, QWebEngineScript
)
from PySide6.QtWebEngineWidgets import QWebEngineView

APP_NAME = "Virel Browser"
APP_DIR = (Path(os.environ.get("APPDATA", str(Path.home()))) / "VirelBrowser") if os.name == "nt" else (Path.home() / ".local" / "share" / "virel-browser")
ASSET_DIR = Path(__file__).resolve().parent / "assets"
START_PAGE = ASSET_DIR / "start.html"
DEFAULT_ACCENT = "#8B5CF6"
DEFAULT_SEARCH = "Google"
_PRIVATE_WINDOWS = []  # Keep private top-level windows alive even if the normal window closes.

SEARCH_ENGINES = {
    "Google": "https://www.google.com/search?q={}",
    "DuckDuckGo": "https://duckduckgo.com/?q={}",
    "Bing": "https://www.bing.com/search?q={}",
}


def ensure_app_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)


def install_webauthn_guard(profile: QWebEngineProfile) -> None:
    """Reject passkey/security-key WebAuthn requests before they open OS prompts.

    Password sign-in and other site sign-in methods remain available. This is a
    convenience workaround for the Windows Security USB-key dialog, not an
    authentication bypass.
    """
    script = QWebEngineScript()
    script.setName("VirelBlockPasskeyPrompts")
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
    script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
    script.setRunsOnSubFrames(True)
    script.setSourceCode(r"""(() => {
  try {
    const credentials = navigator.credentials;
    if (!credentials) return;
    const proto = Object.getPrototypeOf(credentials);
    if (!proto || proto.__virelWebAuthnGuard) return;
    Object.defineProperty(proto, "__virelWebAuthnGuard", { value: true });
    for (const methodName of ["get", "create"]) {
      const original = proto[methodName];
      if (typeof original !== "function") continue;
      Object.defineProperty(proto, methodName, {
        configurable: true,
        writable: true,
        value: function(options) {
          if (options && options.publicKey) {
            return Promise.reject(new DOMException(
              "Passkey/security-key sign-in is disabled in Virel Browser.",
              "NotAllowedError"
            ));
          }
          return Reflect.apply(original, this, arguments);
        }
      });
    }
  } catch (_) {}
})();
""")
    profile.scripts().insert(script)


def read_json(path: Path, fallback):
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError, TypeError):
        return fallback


def write_json(path: Path, value) -> None:
    ensure_app_dir()
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
        temp.replace(path)
    except OSError:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def is_probable_url(text: str) -> bool:
    text = text.strip()
    if not text or " " in text:
        return False
    if text.startswith(("localhost", "127.0.0.1")):
        return True
    if text.startswith(("http://", "https://", "file://", "about:", "data:")):
        return True
    # Treat common hostnames/IPs as addresses; bare words are searched.
    return "." in text or text.startswith("localhost:")


def normalized_target(text: str, search_engine: str) -> QUrl:
    text = text.strip()
    if not text:
        return QUrl.fromLocalFile(str(START_PAGE.resolve()))
    if is_probable_url(text):
        if "://" not in text and not text.startswith(("about:", "data:")):
            text = "https://" + text
        return QUrl.fromUserInput(text)
    template = SEARCH_ENGINES.get(search_engine, SEARCH_ENGINES[DEFAULT_SEARCH])
    return QUrl(template.format(quote_plus(text)))


def safe_name_from_url(url: QUrl) -> str:
    name = Path(url.fileName()).name
    return name or "download"


# Hand-drawn, crisp SVG icons keep the browser chrome consistent across Windows themes.
_ICON_MARKUP = {
    "back": '<path d="M14.5 5.5 8 12l6.5 6.5"/>',
    "forward": '<path d="m9.5 5.5 6.5 6.5-6.5 6.5"/>',
    "reload": '<path d="M20 7v5h-5"/><path d="M4.7 9A7.8 7.8 0 0 1 18.8 7L20 12"/><path d="M4 17v-5h5"/><path d="M19.3 15A7.8 7.8 0 0 1 5.2 17L4 12"/>',
    "home": '<path d="m3.5 10.5 8.5-7 8.5 7"/><path d="M5.5 9.5V21h13V9.5"/><path d="M9.5 21v-7h5v7"/>',
    "bookmark": '<path d="M7 3.75h10A1.75 1.75 0 0 1 18.75 5.5V21L12 16.7 5.25 21V5.5A1.75 1.75 0 0 1 7 3.75Z"/>',
    "bookmark_filled": '<path d="M7 3.75h10A1.75 1.75 0 0 1 18.75 5.5V21L12 16.7 5.25 21V5.5A1.75 1.75 0 0 1 7 3.75Z" fill="{color}"/>',
    "menu": '<circle cx="5" cy="12" r="1.45" fill="{color}"/><circle cx="12" cy="12" r="1.45" fill="{color}"/><circle cx="19" cy="12" r="1.45" fill="{color}"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "close": '<path d="m6.5 6.5 11 11m0-11-11 11"/>',
    "find_up": '<path d="m6.5 14.5 5.5-5 5.5 5"/>',
    "find_down": '<path d="m6.5 9.5 5.5 5 5.5-5"/>',
}


def _render_svg_icon(name: str, color: str, size: int = 64) -> QPixmap:
    inner = _ICON_MARKUP[name].format(color=color)
    is_filled = name == "bookmark_filled"
    stroke = "none" if is_filled else color
    stroke_width = "0" if is_filled else "1.8"
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
        f'<g fill="none" stroke="{stroke}" stroke-width="{stroke_width}" '
        f'stroke-linecap="round" stroke-linejoin="round">{inner}</g></svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


@lru_cache(maxsize=64)
def svg_icon(name: str) -> QIcon:
    """Build a state-aware vector icon; hover/disabled states are deliberately subtle."""
    icon = QIcon()
    icon.addPixmap(_render_svg_icon(name, "#D9D0EF"), QIcon.Mode.Normal, QIcon.State.Off)
    icon.addPixmap(_render_svg_icon(name, "#FFFFFF"), QIcon.Mode.Active, QIcon.State.Off)
    icon.addPixmap(_render_svg_icon(name, "#6D637D"), QIcon.Mode.Disabled, QIcon.State.Off)
    return icon


def accent_styles(accent: str) -> str:
    # The chosen accent is a hex color from the settings dialog.
    color = QColor(accent)
    if not color.isValid():
        color = QColor(DEFAULT_ACCENT)
    accent = color.name()
    return f"""
    * {{ font-family: 'Segoe UI', 'Arial'; font-size: 10pt; }}
    QMainWindow, QDialog {{ background: #15121f; color: #f3efff; }}
    QWidget {{ color: #f3efff; }}
    QToolBar {{ background: #1c1728; border: none; spacing: 6px; padding: 8px 10px; }}
    QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 9px; padding: 7px 10px; color: #ddd5f2; }}
    QToolButton:hover {{ background: #2a223b; border-color: #3a2e52; }}
    QToolButton:pressed {{ background: {accent}; color: white; }}
    QToolButton#TabCloseButton {{ background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 0; margin: 0; }}
    QToolButton#TabCloseButton:hover {{ background: #3A294C; border-color: #65427E; }}
    QToolButton#TabCloseButton:pressed {{ background: #6D315C; border-color: #A85C9B; }}
    QToolButton#NewTabButton {{ background: transparent; border: 1px solid transparent; border-radius: 9px; padding: 0; margin: 4px 5px 0 5px; }}
    QToolButton#NewTabButton:hover {{ background: #302440; border-color: #4A3761; }}
    QToolButton#NewTabButton:pressed {{ background: {accent}; }}
    QLineEdit {{ background: #211a30; color: #fcfaff; border: 1px solid #352747; border-radius: 13px; padding: 9px 15px; selection-background-color: {accent}; min-height: 20px; }}
    QLineEdit:focus {{ border: 1px solid {accent}; background: #241c35; }}
    QTabWidget::pane {{ border: 0; background: #15121f; }}
    QTabBar {{ background: #171320; }}
    QTabBar::tab {{ background: #211a2f; color: #bfb4d6; padding: 7px 14px; margin: 4px 3px 0 3px; border: 1px solid #2d243d; border-bottom: none; border-top-left-radius: 10px; border-top-right-radius: 10px; min-width: 92px; max-width: 220px; }}
    QTabBar::tab:selected {{ background: #302344; color: #ffffff; border-color: {accent}; border-bottom: 2px solid {accent}; }}
    QTabBar::tab:hover:!selected {{ background: #292039; }}
    QMenu {{ background: #211a30; color: #f3efff; border: 1px solid #403052; padding: 6px; }}
    QMenu::item {{ padding: 8px 28px 8px 12px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {accent}; color: white; }}
    QPushButton {{ background: #292039; border: 1px solid #413254; border-radius: 9px; padding: 8px 14px; color: #f3efff; }}
    QPushButton:hover {{ background: #382950; border-color: {accent}; }}
    QPushButton:default {{ background: {accent}; border-color: {accent}; color: white; font-weight: 600; }}
    QComboBox {{ background: #211a30; border: 1px solid #413254; border-radius: 8px; padding: 7px 10px; min-width: 160px; }}
    QComboBox QAbstractItemView {{ background: #211a30; selection-background-color: {accent}; }}
    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{ width: 17px; height: 17px; border: 1px solid #59456e; border-radius: 5px; background: #211a30; }}
    QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}
    QListWidget {{ background: #1b1627; border: 1px solid #352747; border-radius: 9px; padding: 5px; outline: 0; }}
    QListWidget::item {{ padding: 9px; border-radius: 6px; }}
    QListWidget::item:selected {{ background: {accent}; color: white; }}
    QStatusBar {{ background: #1c1728; color: #b9accf; border-top: 1px solid #30243f; }}
    QProgressBar {{ border: 0; background: #2a2239; height: 3px; }}
    QProgressBar::chunk {{ background: {accent}; }}
    QFrame#FindBar {{ background: #211a30; border: 1px solid #3b2d50; border-radius: 10px; }}
    QLabel#muted {{ color: #a99abb; }}
    """


class BrowserPage(QWebEnginePage):
    """A web page that sends target=_blank links back to the tab manager."""
    def __init__(self, profile: QWebEngineProfile, parent, new_tab_callback):
        super().__init__(profile, parent)
        self._new_tab_callback = new_tab_callback

    def createWindow(self, _window_type):
        return self._new_tab_callback()


class BrowserView(QWebEngineView):
    def __init__(self, parent=None):
        super().__init__(parent)

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        menu.addSeparator()
        reload_action = menu.addAction("Reload page")
        copy_url_action = menu.addAction("Copy page address")
        chosen = menu.exec(event.globalPos())
        if chosen == reload_action:
            self.reload()
        elif chosen == copy_url_action:
            QApplication.clipboard().setText(self.url().toString())
        menu.deleteLater()


class BrowserTab(QWidget):
    title_changed = Signal(str)
    url_changed = Signal(QUrl)
    load_progress = Signal(int)
    load_finished = Signal(bool)

    def __init__(self, profile: QWebEngineProfile, new_tab_callback, parent=None):
        super().__init__(parent)
        self.view = BrowserView(self)
        self.pending_url: QUrl | None = None
        self._managed_by_window = False
        self.page = BrowserPage(profile, self.view, new_tab_callback)
        self.view.setPage(self.page)
        self.view.setMinimumSize(320, 240)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)

        settings = self.page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ErrorPageEnabled, True)
        # Prefer responsive direct scrolling over extra compositor animation on low-end GPUs.
        try:
            settings.setAttribute(QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled, False)
        except AttributeError:
            pass

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        self.view.titleChanged.connect(self._title_updated)
        self.view.urlChanged.connect(self.url_changed.emit)
        self.view.loadProgress.connect(self.load_progress.emit)
        self.view.loadFinished.connect(self.load_finished.emit)

    def _title_updated(self, title: str):
        title = title.strip() or "New tab"
        self.title_changed.emit(title[:80])

    def go_home(self, url: QUrl | None = None):
        self.view.setUrl(url or QUrl.fromLocalFile(str(START_PAGE.resolve())))


class LinkListDialog(QDialog):
    def __init__(self, parent, title: str, entries: list, empty_text: str, remove_enabled=True):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(680, 440)
        self.entries = entries
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        layout.addWidget(self.list, 1)
        for entry in entries:
            label = entry.get("title") or entry.get("url", "")
            url = entry.get("url", "")
            item = QListWidgetItem(f"{label}\n{url}")
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self.list.addItem(item)
        if not entries:
            self.list.addItem(QListWidgetItem(empty_text))
        row = QHBoxLayout()
        self.open_btn = QPushButton("Open")
        self.remove_btn = QPushButton("Remove selected")
        self.clear_btn = QPushButton("Clear all")
        close_btn = QPushButton("Close")
        row.addWidget(self.open_btn)
        row.addWidget(self.remove_btn)
        row.addWidget(self.clear_btn)
        row.addStretch(1)
        row.addWidget(close_btn)
        layout.addLayout(row)
        self.open_btn.clicked.connect(self.accept)
        close_btn.clicked.connect(self.reject)
        self.remove_btn.setEnabled(remove_enabled)
        self.clear_btn.setEnabled(remove_enabled)
        self.remove_btn.clicked.connect(self.remove_selected)
        self.clear_btn.clicked.connect(self.clear_all)
        self.list.itemDoubleClicked.connect(lambda _item: self.accept())

    def remove_selected(self):
        row = self.list.currentRow()
        if row < 0 or row >= len(self.entries):
            return
        del self.entries[row]
        self.list.takeItem(row)

    def clear_all(self):
        self.entries.clear()
        self.list.clear()

    def selected_entry(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None


class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Virel Browser — Settings")
        self.setMinimumWidth(480)
        self.settings = dict(settings)
        outer = QVBoxLayout(self)
        heading = QLabel("Make Virel yours")
        heading.setStyleSheet("font-size: 19pt; font-weight: 700; color: #ffffff;")
        subtitle = QLabel("Appearance, search and startup preferences")
        subtitle.setObjectName("muted")
        outer.addWidget(heading)
        outer.addWidget(subtitle)
        form = QFormLayout()
        form.setVerticalSpacing(14)
        self.search = QComboBox()
        self.search.addItems(list(SEARCH_ENGINES))
        self.search.setCurrentText(settings.get("search_engine", DEFAULT_SEARCH))
        form.addRow("Default search engine", self.search)

        self.accent = settings.get("accent", DEFAULT_ACCENT)
        self.accent_button = QPushButton("Choose accent colour  ●")
        self._update_accent_button()
        self.accent_button.clicked.connect(self.choose_accent)
        form.addRow("Accent colour", self.accent_button)

        self.restore = QCheckBox("Restore my regular tabs when Virel starts")
        self.restore.setChecked(bool(settings.get("restore_session", False)))
        form.addRow("Startup", self.restore)
        self.confirm_close = QCheckBox("Ask before closing a window with multiple tabs")
        self.confirm_close.setChecked(bool(settings.get("confirm_close", True)))
        form.addRow("Tabs", self.confirm_close)
        outer.addLayout(form)

        note = QLabel("Tip: fewer open tabs help Virel run more comfortably on PCs with 4 GB RAM.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        outer.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def _update_accent_button(self):
        self.accent_button.setStyleSheet(
            f"QPushButton {{ background: #292039; border: 1px solid {self.accent}; border-radius: 8px; padding: 8px; }}"
        )

    def choose_accent(self):
        color = QColorDialog.getColor(QColor(self.accent), self, "Choose Virel accent colour")
        if color.isValid():
            self.accent = color.name()
            self._update_accent_button()

    def result_settings(self):
        return {
            "search_engine": self.search.currentText(),
            "accent": self.accent,
            "restore_session": self.restore.isChecked(),
            "confirm_close": self.confirm_close.isChecked(),
        }


class VirelWindow(QMainWindow):
    def __init__(self, private=False, shared_profile=None):
        super().__init__()
        self.private = private
        ensure_app_dir()
        self.settings_path = APP_DIR / "settings.json"
        self.bookmarks_path = APP_DIR / "bookmarks.json"
        self.history_path = APP_DIR / "history.json"
        self.session_path = APP_DIR / "session.json"
        self.settings = read_json(self.settings_path, {
            "search_engine": DEFAULT_SEARCH,
            "accent": DEFAULT_ACCENT,
            "restore_session": False,
            "confirm_close": True,
        })
        self.bookmarks = read_json(self.bookmarks_path, []) if not private else []
        self.history = read_json(self.history_path, []) if not private else []
        self._history_last_seen = {}
        self._history_save_timer = QTimer(self)
        self._history_save_timer.setSingleShot(True)
        self._history_save_timer.setInterval(900)
        self._history_save_timer.timeout.connect(lambda: write_json(self.history_path, self.history))
        self._lifecycle_timer = QTimer(self)
        self._lifecycle_timer.setSingleShot(True)
        self._lifecycle_timer.setInterval(1400)
        self._lifecycle_timer.timeout.connect(self._freeze_background_tabs)
        self._recent_closed = []
        self._downloads: list[dict] = []
        self._is_restoring = False
        self._private_profile_owner = None

        if shared_profile is not None:
            self.profile = shared_profile
        elif private:
            self.profile = QWebEngineProfile(self)
            self._private_profile_owner = self.profile
        else:
            profile_dir = APP_DIR / "profile"
            cache_dir = APP_DIR / "cache"
            profile_dir.mkdir(parents=True, exist_ok=True)
            cache_dir.mkdir(parents=True, exist_ok=True)
            self.profile = QWebEngineProfile("VirelProfile", self)
            self.profile.setPersistentStoragePath(str(profile_dir))
            self.profile.setCachePath(str(cache_dir))
            self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
            self.profile.setPersistentCookiesPolicy(
                QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
            )
            # Bound the on-disk HTTP cache; cookies and bookmarks remain persistent.
            self.profile.setHttpCacheMaximumSize(96 * 1024 * 1024)
        install_webauthn_guard(self.profile)
        self.profile.downloadRequested.connect(self.handle_download)

        self.setWindowTitle("Virel Browser — Private" if private else APP_NAME)
        self.setMinimumSize(760, 540)
        self.resize(1240, 800)
        icon_path = Path(__file__).resolve().parent / "virel.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setStyleSheet(accent_styles(self.settings.get("accent", DEFAULT_ACCENT)))

        self._build_ui()
        self._build_actions()
        self._apply_shortcuts()
        self._update_bookmark_button()
        self._update_private_badge()

        if not private and self.settings.get("restore_session"):
            urls = read_json(self.session_path, [])
            valid_urls = [url for url in urls if isinstance(url, str) and url]
            if valid_urls:
                self._is_restoring = True
                for index, url in enumerate(valid_urls[:12]):
                    self.add_tab(QUrl(url), switch=(index == 0), defer_load=(index != 0))
                self._is_restoring = False
        if self.tabs.count() == 0:
            self.add_tab(self.start_page_url(), switch=True)

    def start_page_url(self) -> QUrl:
        url = QUrl.fromLocalFile(str(START_PAGE.resolve()))
        url.setQuery("engine=" + quote_plus(self.settings.get("search_engine", DEFAULT_SEARCH)))
        return url

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.nav = QWidget()
        nav_layout = QHBoxLayout(self.nav)
        nav_layout.setContentsMargins(12, 9, 12, 9)
        nav_layout.setSpacing(6)
        self.back_btn = self._tool_button("", "Back", self.go_back, "back")
        self.forward_btn = self._tool_button("", "Forward", self.go_forward, "forward")
        self.reload_btn = self._tool_button("", "Reload page (Ctrl+R)", self.reload_page, "reload")
        self.home_btn = self._tool_button("", "Virel start page", self.go_home, "home")
        for button in (self.back_btn, self.forward_btn, self.reload_btn, self.home_btn):
            button.setFixedSize(38, 38)
            button.setIconSize(QSize(19, 19))
            nav_layout.addWidget(button)

        self.address = QLineEdit()
        self.address.setPlaceholderText(f"Search {self.settings.get('search_engine', DEFAULT_SEARCH)} or enter a web address")
        self.address.setClearButtonEnabled(True)
        self.address.setMinimumHeight(38)
        self.address.returnPressed.connect(self.navigate_from_address)
        self.address.setToolTip("Enter a website address or search terms (Ctrl+L)")
        nav_layout.addWidget(self.address, 1)

        self.bookmark_btn = self._tool_button("", "Bookmark this page (Ctrl+D)", self.toggle_bookmark, "bookmark")
        self.bookmark_btn.setFixedSize(38, 38)
        self.bookmark_btn.setIconSize(QSize(19, 19))
        nav_layout.addWidget(self.bookmark_btn)
        self.menu_btn = self._tool_button("", "Virel menu", self.show_app_menu, "menu")
        self.menu_btn.setFixedSize(38, 38)
        self.menu_btn.setIconSize(QSize(19, 19))
        nav_layout.addWidget(self.menu_btn)
        outer.addWidget(self.nav)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(3)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        outer.addWidget(self.progress)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        # Use a custom vector close button instead of the platform's orange square.
        self.tabs.setTabsClosable(False)
        self.tabs.currentChanged.connect(self.current_tab_changed)
        self.tabs.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
        new_tab_button = QToolButton()
        new_tab_button.setObjectName("NewTabButton")
        new_tab_button.setIcon(svg_icon("plus"))
        new_tab_button.setIconSize(QSize(16, 16))
        new_tab_button.setToolTip("New tab (Ctrl+T)")
        new_tab_button.setFixedSize(28, 24)
        new_tab_button.setCursor(Qt.CursorShape.PointingHandCursor)
        new_tab_button.clicked.connect(lambda: self.add_tab(self.start_page_url(), True))
        self.tabs.setCornerWidget(new_tab_button, Qt.Corner.TopLeftCorner)
        outer.addWidget(self.tabs, 1)

        self.find_frame = QFrame()
        self.find_frame.setObjectName("FindBar")
        find_layout = QHBoxLayout(self.find_frame)
        find_layout.setContentsMargins(10, 5, 6, 5)
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Find on page…")
        self.find_input.setMaximumWidth(300)
        self.find_input.textChanged.connect(self.find_text)
        self.find_input.returnPressed.connect(lambda: self.find_text(self.find_input.text(), forward=True))
        find_layout.addWidget(self.find_input)
        self.find_count = QLabel("")
        self.find_count.setObjectName("muted")
        find_layout.addWidget(self.find_count)
        find_prev = self._tool_button("", "Previous match", lambda: self.find_text(self.find_input.text(), forward=False), "find_up")
        find_next = self._tool_button("", "Next match", lambda: self.find_text(self.find_input.text(), forward=True), "find_down")
        find_close = self._tool_button("", "Close find bar (Esc)", self.hide_find_bar, "close")
        for button in (find_prev, find_next, find_close):
            button.setFixedSize(30, 30)
            button.setIconSize(QSize(16, 16))
        find_layout.addWidget(find_prev)
        find_layout.addWidget(find_next)
        find_layout.addWidget(find_close)
        self.find_frame.hide()
        outer.addWidget(self.find_frame)

        self.status = QStatusBar()
        self.status.showMessage("Ready · Virel Browser", 3500)
        self.setStatusBar(self.status)

    def _tool_button(self, text: str, tooltip: str, callback, icon_name: str | None = None):
        button = QToolButton()
        button.setText(text)
        if icon_name:
            button.setIcon(svg_icon(icon_name))
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.clicked.connect(callback)
        return button

    def _set_custom_tab_close(self, tab: BrowserTab) -> None:
        index = self.tabs.indexOf(tab)
        if index < 0:
            return
        # QTabBar places its right-side button almost flush against the tab edge.
        # A wrapper with right-side layout padding gives the X intentional breathing room.
        close_host = QWidget(self.tabs.tabBar())
        close_host.setObjectName("TabCloseHost")
        close_host.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        close_layout = QHBoxLayout(close_host)
        close_layout.setContentsMargins(2, 0, 7, 0)
        close_layout.setSpacing(0)
        close_button = QToolButton(close_host)
        close_button.setObjectName("TabCloseButton")
        close_button.setIcon(svg_icon("close"))
        close_button.setIconSize(QSize(12, 12))
        close_button.setFixedSize(18, 18)
        close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        close_button.setToolTip("Close tab")
        close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close_button.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        close_button.clicked.connect(lambda _checked=False, t=tab: self.close_tab(self.tabs.indexOf(t)))
        close_layout.addWidget(close_button)
        close_host.setFixedHeight(21)
        self.tabs.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, close_host)

    def _build_actions(self):
        self.actions = {}
        definitions = [
            ("new_tab", "New tab", "Ctrl+T", lambda: self.add_tab(self.start_page_url(), True)),
            ("close_tab", "Close tab", "Ctrl+W", self.close_current_tab),
            ("reopen_tab", "Reopen closed tab", "Ctrl+Shift+T", self.reopen_closed_tab),
            ("focus_address", "Focus address bar", "Ctrl+L", self.focus_address),
            ("reload", "Reload", "Ctrl+R", self.reload_page),
            ("home", "Home", "Alt+Home", self.go_home),
            ("back", "Back", "Alt+Left", self.go_back),
            ("forward", "Forward", "Alt+Right", self.go_forward),
            ("find", "Find on page", "Ctrl+F", self.show_find_bar),
            ("history", "History", "Ctrl+H", self.show_history),
            ("downloads", "Downloads", "Ctrl+J", self.show_downloads),
            ("bookmark", "Bookmark this page", "Ctrl+D", self.toggle_bookmark),
            ("private", "New private window", "Ctrl+Shift+N", self.open_private_window),
            ("settings", "Settings", "", self.show_settings),
        ]
        for key, text, shortcut, callback in definitions:
            action = QAction(text, self)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
            self.addAction(action)
            self.actions[key] = action

    def _apply_shortcuts(self):
        # Escape closes the find bar without interfering with page navigation.
        shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        shortcut.activated.connect(self.hide_find_bar)

    def _update_private_badge(self):
        if self.private:
            self.status.showMessage("Private window · history and bookmarks won't be saved", 9000)

    def add_tab(self, url: QUrl | None = None, switch=True, defer_load=False):
        tab = BrowserTab(self.profile, self._open_target_blank_tab, self.tabs)
        tab.pending_url = url or self.start_page_url()
        index = self.tabs.addTab(tab, "New tab")
        self.tabs.setTabToolTip(index, "New tab")
        self._set_custom_tab_close(tab)
        tab.title_changed.connect(lambda title, t=tab: self._tab_title_changed(t, title))
        tab.url_changed.connect(lambda qurl, t=tab: self._tab_url_changed(t, qurl))
        tab.load_progress.connect(lambda value, t=tab: self._tab_progress(t, value))
        tab.load_finished.connect(lambda ok, t=tab: self._tab_load_finished(t, ok))
        tab.view.iconChanged.connect(lambda icon, t=tab: self._tab_icon_changed(t, icon))
        tab._managed_by_window = True
        if switch:
            self.tabs.setCurrentIndex(index)
        # Restored background tabs are placeholders until the user selects them.
        if not defer_load or tab is self.current_tab() or self.tabs.count() == 1:
            self._load_pending_tab(tab)
        return tab

    def _load_pending_tab(self, tab: BrowserTab) -> None:
        target = tab.pending_url
        if target is None:
            return
        tab.pending_url = None
        tab.view.setUrl(target)

    def _schedule_background_freeze(self) -> None:
        # A delay avoids freezing a page while the user is quickly switching tabs.
        if hasattr(self, "_lifecycle_timer"):
            self._lifecycle_timer.start()

    def _freeze_background_tabs(self) -> None:
        """Suspend idle background pages to reduce CPU use without interrupting active audio."""
        lifecycle = getattr(QWebEnginePage, "LifecycleState", None)
        if lifecycle is None:
            return
        active_state = getattr(lifecycle, "Active", None)
        frozen_state = getattr(lifecycle, "Frozen", None)
        if active_state is None or frozen_state is None or not hasattr(self, "tabs"):
            return
        current = self.current_tab()
        for index in range(self.tabs.count()):
            tab = self.tabs.widget(index)
            if not isinstance(tab, BrowserTab):
                continue
            page = tab.page
            try:
                if tab is current:
                    if page.lifecycleState() != active_state:
                        page.setLifecycleState(active_state)
                    continue
                if tab.pending_url is not None or page.isLoading():
                    continue
                # Recommended state remains Active for pages where freezing would interrupt
                # audible media or other activity that Chromium considers important.
                if page.recommendedState() != active_state and page.lifecycleState() != frozen_state:
                    page.setLifecycleState(frozen_state)
            except (AttributeError, RuntimeError):
                # Keep browsing functional if an older Qt WebEngine build lacks lifecycle support.
                continue

    def _open_target_blank_tab(self):
        tab = self.add_tab(self.start_page_url(), True)
        return tab.page

    def current_tab(self) -> BrowserTab | None:
        widget = self.tabs.currentWidget() if hasattr(self, "tabs") else None
        return widget if isinstance(widget, BrowserTab) else None

    def current_tab_changed(self, _index):
        tab = self.current_tab()
        if tab is None:
            return
        if getattr(tab, "_managed_by_window", False):
            self._load_pending_tab(tab)
            try:
                lifecycle = getattr(QWebEnginePage, "LifecycleState", None)
                active_state = getattr(lifecycle, "Active", None) if lifecycle is not None else None
                if active_state is not None and tab.page.lifecycleState() != active_state:
                    tab.page.setLifecycleState(active_state)
            except (AttributeError, RuntimeError):
                pass
        url = tab.view.url()
        if url.isLocalFile() and Path(url.toLocalFile()).resolve() == START_PAGE.resolve():
            self.address.setText("")
        else:
            self.address.setText(url.toString() if url.isValid() else "")
        self.address.setCursorPosition(0)
        self._update_navigation_buttons()
        self._update_bookmark_button()
        self.progress.setValue(0)
        self.find_count.setText("")
        self._schedule_background_freeze()

    def _tab_title_changed(self, tab: BrowserTab, title: str):
        index = self.tabs.indexOf(tab)
        if index >= 0:
            short = title if len(title) <= 24 else title[:22] + "…"
            if tab.view.url().isLocalFile() and Path(tab.view.url().toLocalFile()).resolve() == START_PAGE.resolve():
                short = "Virel Home"
            self.tabs.setTabText(index, short)
            self.tabs.setTabToolTip(index, title)
            if not self.private:
                page_url = tab.view.url().toString()
                for entry in self.history:
                    if entry.get("url") == page_url:
                        entry["title"] = title
                        self._history_save_timer.start()
                        break
            if tab is self.current_tab():
                self.setWindowTitle(("Virel Browser — Private" if self.private else APP_NAME) + f" · {title}")

    def _tab_url_changed(self, tab: BrowserTab, url: QUrl):
        if tab is self.current_tab():
            if url.isLocalFile() and Path(url.toLocalFile()).resolve() == START_PAGE.resolve():
                self.address.setText("")
            else:
                self.address.setText(url.toString())
            self._update_navigation_buttons()
            self._update_bookmark_button()
        if not self.private and url.isValid() and url.scheme() in ("http", "https"):
            self._record_history(url, tab.view.title())

    def _tab_progress(self, tab: BrowserTab, value: int):
        if tab is self.current_tab():
            self.progress.setValue(value)
            if value == 100:
                QTimer.singleShot(500, lambda: self.progress.setValue(0) if self.progress.value() == 100 else None)

    def _tab_load_finished(self, tab: BrowserTab, ok: bool):
        if tab is self.current_tab():
            self.status.showMessage("Page loaded" if ok else "The page could not be loaded", 3000)
            self._update_navigation_buttons()
        self._schedule_background_freeze()

    def _tab_icon_changed(self, tab: BrowserTab, icon: QIcon):
        index = self.tabs.indexOf(tab)
        if index >= 0 and not icon.isNull():
            self.tabs.setTabIcon(index, icon)

    def _update_navigation_buttons(self):
        tab = self.current_tab()
        self.back_btn.setEnabled(bool(tab and tab.view.history().canGoBack()))
        self.forward_btn.setEnabled(bool(tab and tab.view.history().canGoForward()))

    def navigate_from_address(self):
        text = self.address.text()
        target = self.start_page_url() if not text.strip() else normalized_target(text, self.settings.get("search_engine", DEFAULT_SEARCH))
        tab = self.current_tab()
        if tab is None:
            tab = self.add_tab(target, True)
        else:
            tab.view.setUrl(target)
        self.address.clearFocus()

    def go_back(self):
        tab = self.current_tab()
        if tab and tab.view.history().canGoBack():
            tab.view.back()

    def go_forward(self):
        tab = self.current_tab()
        if tab and tab.view.history().canGoForward():
            tab.view.forward()

    def reload_page(self):
        tab = self.current_tab()
        if tab:
            tab.view.reload()

    def go_home(self):
        tab = self.current_tab()
        if tab:
            tab.go_home(self.start_page_url())

    def focus_address(self):
        self.address.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.address.selectAll()

    def close_tab(self, index: int):
        if self.tabs.count() <= 1:
            tab = self.current_tab()
            if tab:
                tab.go_home(self.start_page_url())
            return
        tab = self.tabs.widget(index)
        if isinstance(tab, BrowserTab):
            url = tab.view.url().toString()
            if not self.private and url and not url.startswith("file:"):
                self._recent_closed.append(url)
                self._recent_closed = self._recent_closed[-10:]
        self.tabs.removeTab(index)
        if tab:
            tab.deleteLater()
        self._update_navigation_buttons()

    def close_current_tab(self):
        self.close_tab(self.tabs.currentIndex())

    def reopen_closed_tab(self):
        if self._recent_closed:
            url = self._recent_closed.pop()
            self.add_tab(QUrl(url), True)
        else:
            self.add_tab(self.start_page_url(), True)

    def _record_history(self, url: QUrl, title: str):
        value = url.toString()
        now_key = value
        # Avoid a history write for every tiny same-page URL update.
        if self._history_last_seen.get(now_key) == title:
            return
        self._history_last_seen[now_key] = title
        self.history.insert(0, {"title": title or value, "url": value})
        self.history = self.history[:1000]
        self._history_save_timer.start()

    def _is_bookmarked(self, url: str) -> bool:
        return any(item.get("url") == url for item in self.bookmarks)

    def _update_bookmark_button(self):
        tab = self.current_tab()
        url = tab.view.url().toString() if tab else ""
        bookmarked = bool(url and self._is_bookmarked(url))
        self.bookmark_btn.setIcon(svg_icon("bookmark_filled" if bookmarked else "bookmark"))
        self.bookmark_btn.setToolTip("Remove bookmark (Ctrl+D)" if bookmarked else "Bookmark this page (Ctrl+D)")

    def toggle_bookmark(self):
        if self.private:
            self.status.showMessage("Bookmarks are disabled in private windows", 3000)
            return
        tab = self.current_tab()
        if tab is None:
            return
        url = tab.view.url().toString()
        if not url or url.startswith(("file:", "about:")):
            self.status.showMessage("Open a website before bookmarking it", 3000)
            return
        if self._is_bookmarked(url):
            self.bookmarks = [item for item in self.bookmarks if item.get("url") != url]
            self.status.showMessage("Bookmark removed", 2500)
        else:
            title = tab.view.title() or url
            self.bookmarks.insert(0, {"title": title, "url": url})
            self.bookmarks = self.bookmarks[:1000]
            self.status.showMessage("Added to bookmarks", 2500)
        write_json(self.bookmarks_path, self.bookmarks)
        self._update_bookmark_button()

    def show_history(self):
        if self.private:
            QMessageBox.information(self, "Private window", "Browsing history is not available in a private window.")
            return
        dialog = LinkListDialog(self, "Virel — History", self.history, "No history yet")
        dialog.clear_btn.setText("Clear history")
        result = dialog.exec()
        if result == QDialog.DialogCode.Accepted:
            entry = dialog.selected_entry()
            if entry:
                self.add_tab(QUrl(entry.get("url", "")), True)
        write_json(self.history_path, self.history)

    def show_bookmarks(self):
        if self.private:
            QMessageBox.information(self, "Private window", "Bookmarks are not available in a private window.")
            return
        dialog = LinkListDialog(self, "Virel — Bookmarks", self.bookmarks, "No bookmarks yet")
        dialog.clear_btn.setText("Clear bookmarks")
        result = dialog.exec()
        if result == QDialog.DialogCode.Accepted:
            entry = dialog.selected_entry()
            if entry:
                self.add_tab(QUrl(entry.get("url", "")), True)
        write_json(self.bookmarks_path, self.bookmarks)
        self._update_bookmark_button()

    def show_downloads(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Virel — Downloads")
        dialog.resize(720, 430)
        layout = QVBoxLayout(dialog)
        listing = QListWidget()
        for entry in self._downloads:
            status = entry.get("status", "Waiting")
            listing.addItem(f"{entry.get('name', 'download')}  —  {status}\n{entry.get('path', '')}")
        if not self._downloads:
            listing.addItem("No downloads in this window yet.")
        layout.addWidget(listing, 1)
        row = QHBoxLayout()
        open_folder = QPushButton("Open downloads folder")
        close = QPushButton("Close")
        row.addWidget(open_folder)
        row.addStretch(1)
        row.addWidget(close)
        layout.addLayout(row)
        open_folder.clicked.connect(lambda: self._open_download_folder())
        close.clicked.connect(dialog.accept)
        dialog.exec()

    def _open_download_folder(self):
        folder = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation))
        folder.mkdir(parents=True, exist_ok=True)
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def handle_download(self, download: QWebEngineDownloadRequest):
        suggested = download.downloadFileName() or "download"
        base_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation))
        base_dir.mkdir(parents=True, exist_ok=True)
        default_path = str(base_dir / suggested)
        path, _ = QFileDialog.getSaveFileName(self, "Save download", default_path, "All files (*)")
        if not path:
            download.cancel()
            self.status.showMessage("Download cancelled", 2500)
            return
        target = Path(path)
        download.setDownloadDirectory(str(target.parent))
        download.setDownloadFileName(target.name)
        name = target.name
        record = {"name": name, "path": str(target), "status": "Downloading…"}
        self._downloads.insert(0, record)
        self.status.showMessage(f"Downloading {name}…", 4000)
        download.stateChanged.connect(lambda state, item=record, req=download: self._download_state_changed(item, req, state))
        download.accept()

    def _download_state_changed(self, record: dict, request: QWebEngineDownloadRequest, state):
        if state == QWebEngineDownloadRequest.DownloadState.DownloadCompleted:
            record["status"] = "Completed"
            self.status.showMessage(f"Download completed: {record['name']}", 5000)
        elif state == QWebEngineDownloadRequest.DownloadState.DownloadCancelled:
            record["status"] = "Cancelled"
        elif state == QWebEngineDownloadRequest.DownloadState.DownloadInterrupted:
            record["status"] = "Interrupted"
            record["error"] = request.interruptReasonString()
        elif state == QWebEngineDownloadRequest.DownloadState.DownloadInProgress:
            record["status"] = "Downloading…"

    def show_find_bar(self):
        self.find_frame.show()
        self.find_input.setFocus()
        self.find_input.selectAll()

    def hide_find_bar(self):
        if self.find_frame.isVisible():
            tab = self.current_tab()
            if tab:
                tab.page.findText("")
            self.find_frame.hide()
            self.find_count.setText("")
            if tab:
                tab.view.setFocus()

    def find_text(self, text: str, forward=True):
        tab = self.current_tab()
        if not tab:
            return
        flags = QWebEnginePage.FindFlag(0)
        if not forward:
            flags |= QWebEnginePage.FindFlag.FindBackward
        tab.page.findText(text, flags, lambda found: self.find_count.setText("Found" if found else "No match"))

    def show_settings(self):
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.settings.update(dialog.result_settings())
            write_json(self.settings_path, self.settings)
            self.setStyleSheet(accent_styles(self.settings.get("accent", DEFAULT_ACCENT)))
            self.address.setPlaceholderText(f"Search {self.settings.get('search_engine', DEFAULT_SEARCH)} or enter a web address")
            self.status.showMessage("Settings saved", 2500)

    def show_app_menu(self):
        menu = QMenu(self)
        if self.private:
            private_label = QAction("● Private browsing", self)
            private_label.setEnabled(False)
            menu.addAction(private_label)
            menu.addSeparator()
        menu.addAction(self.actions["new_tab"])
        menu.addAction(self.actions["reopen_tab"])
        menu.addSeparator()
        if not self.private:
            menu.addAction("Bookmarks", self.show_bookmarks)
            menu.addAction(self.actions["history"])
        menu.addAction(self.actions["downloads"])
        menu.addAction(self.actions["find"])
        menu.addSeparator()
        menu.addAction(self.actions["private"])
        menu.addAction(self.actions["settings"])
        menu.addSeparator()
        menu.addAction("Clear browsing data…", self.clear_browsing_data)
        menu.addAction("About Virel Browser", self.show_about)
        menu.exec(self.menu_btn.mapToGlobal(self.menu_btn.rect().bottomLeft()))

    def clear_browsing_data(self):
        choice, ok = QInputDialog.getItem(
            self, "Clear browsing data", "Choose what to clear:",
            ["History", "Cookies and cached files", "History, cookies and cached files"], 2, False
        )
        if not ok:
            return
        if choice in ("History", "History, cookies and cached files") and not self.private:
            self.history.clear()
            self._history_last_seen.clear()
            write_json(self.history_path, self.history)
        if choice in ("Cookies and cached files", "History, cookies and cached files"):
            self.profile.cookieStore().deleteAllCookies()
            self.profile.clearHttpCache()
            self.profile.clearAllVisitedLinks()
        self.status.showMessage("Selected browsing data cleared", 3500)

    def open_private_window(self):
        window = VirelWindow(private=True)
        _PRIVATE_WINDOWS.append(window)
        window.show()

    def show_about(self):
        QMessageBox.about(
            self, "About Virel Browser",
            "<h2 style='color:#a78bfa'>Virel Browser</h2>"
            "<p>A personal browser with a violet soul.</p>"
            "<p>Built with Python, PySide6 and Qt WebEngine.</p>"
            "<p style='color:#9b8bad'>An independent project. Not affiliated with Google or other browser vendors.</p>"
        )

    def closeEvent(self, event):
        if self.tabs.count() > 1 and self.settings.get("confirm_close", True):
            answer = QMessageBox.question(
                self, "Close Virel Browser?",
                f"Close this window with {self.tabs.count()} open tabs?",
                QMessageBox.StandardButton.Close | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Close,
            )
            if answer != QMessageBox.StandardButton.Close:
                event.ignore()
                return
        if not self.private:
            if self._history_save_timer.isActive():
                self._history_save_timer.stop()
                write_json(self.history_path, self.history)
            urls = []
            for i in range(self.tabs.count()):
                tab = self.tabs.widget(i)
                if isinstance(tab, BrowserTab):
                    url = tab.view.url().toString()
                    if url and not (tab.view.url().isLocalFile() and Path(tab.view.url().toLocalFile()).resolve() == START_PAGE.resolve()):
                        urls.append(url)
            write_json(self.session_path, urls[-12:])
            write_json(self.bookmarks_path, self.bookmarks)
            write_json(self.history_path, self.history)
            write_json(self.settings_path, self.settings)
        else:
            try:
                _PRIVATE_WINDOWS.remove(self)
            except ValueError:
                pass
        event.accept()


def main():
    # Leave the Chromium sandbox enabled; don't set QTWEBENGINE_DISABLE_SANDBOX.
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("Virel")
    app.setApplicationDisplayName(APP_NAME)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    icon_path = Path(__file__).resolve().parent / "virel.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = VirelWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
