"""Native window embedding the click-counter page, so the app shows up in
the Dock/taskbar with the UI itself instead of running headless or sending
the user out to their system browser."""
import webview
from webview.menu import Menu, MenuAction

from app.updater import run_manual_check


def run_gui(httpd, port):
    url = f"http://127.0.0.1:{port}/"
    window = webview.create_window("myapp", url)
    menu = [Menu("myapp", [MenuAction("Check for Updates", lambda: run_manual_check(window))])]
    webview.start(menu=menu)
    httpd.shutdown()
    httpd.server_close()
