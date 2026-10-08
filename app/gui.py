"""Native window embedding the click-counter page, so the app shows up in
the Dock/taskbar with the UI itself instead of running headless or sending
the user out to their system browser."""
import webview


def run_gui(httpd, port):
    url = f"http://127.0.0.1:{port}/"
    webview.create_window("myapp", url)
    webview.start()
    httpd.shutdown()
    httpd.server_close()
