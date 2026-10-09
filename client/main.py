try:
    from webui import JavaScriptBridge, WebviewWindow
except ImportError:
    from .webui import JavaScriptBridge, WebviewWindow


def main() -> None:
    bridge = JavaScriptBridge()
    window = WebviewWindow(bridge)
    window.run()


if __name__ == "__main__":
    main()
