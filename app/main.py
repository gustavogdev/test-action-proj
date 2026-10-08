import threading

from app import db, gui, server
from app._version import __version__
from app.updater import check_and_apply_update


def run():
    print(f"myapp {__version__}")
    db_path = db.init_version_db(__version__)
    port = 8765
    httpd = server.create_server(db_path, port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    gui.run_gui(httpd, port)


def main():
    check_and_apply_update()
    run()


if __name__ == "__main__":
    main()
