"""pywebview 导航白名单：外部链接交给系统浏览器，不留在账本窗口里。"""
import sys
import webbrowser
from urllib.parse import urlsplit


def allowed(url, origin):
    parts = urlsplit(str(url))
    return parts.scheme + "://" + parts.netloc == origin and parts.path in ("/", "/index.html", "/desktop-start")


def external(url, origin):
    parts = urlsplit(str(url))
    if parts.scheme in ("http", "https") and parts.hostname and not parts.username and not parts.password:
        if parts.scheme + "://" + parts.netloc != origin:
            webbrowser.open(str(url))


def install_navigation_guard(origin):
    if sys.platform == "darwin":
        from webview.platforms import cocoa

        class LedgerNavigationDelegate(cocoa.BrowserView.BrowserDelegate):
            def webView_decidePolicyForNavigationAction_decisionHandler_(self, view, action, handler):
                url = str(action.request().URL().absoluteString())
                if allowed(url, origin):
                    handler(1)
                else:
                    handler(0)
                    if action.navigationType() == 0:
                        external(url, origin)

            def webView_createWebViewWithConfiguration_forNavigationAction_windowFeatures_(self, view, config, action, features):
                external(str(action.request().URL().absoluteString()), origin)
                return None

        cocoa.BrowserView.BrowserDelegate = LedgerNavigationDelegate
        return "cocoa"
    if sys.platform == "win32":
        from webview import guilib
        guilib.forced_gui_ = "edgechromium"
        from webview.platforms import winforms
        if winforms.renderer != "edgechromium":
            raise RuntimeError("webview2_missing")
        from webview.platforms.edgechromium import EdgeChrome
        original = EdgeChrome.on_navigation_start

        def navigation(self, sender, args):
            url = str(args.Uri)
            if not allowed(url, origin):
                args.Cancel = True
                if args.IsUserInitiated:
                    external(url, origin)
                return
            original(self, sender, args)

        def new_window(self, sender, args):
            args.Handled = True
            external(str(args.Uri), origin)

        EdgeChrome.on_navigation_start = navigation
        EdgeChrome.on_new_window_request = new_window
        return "edgechromium"
    raise RuntimeError("unsupported_platform")
