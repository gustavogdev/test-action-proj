from app import db, server
from app._version import __version__
from app.updater import check_and_apply_update


def run():
    print(f"myapp {__version__}")
    db_path = db.init_version_db(__version__)
    server.run_server(db_path)


def main():
    check_and_apply_update()
    run()


if __name__ == "__main__":
    main()
