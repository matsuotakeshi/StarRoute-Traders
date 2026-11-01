import argparse
import sqlite3
import sys
from .application import Application
from .catalog import Catalog, identifier
from .clock import SystemClock
from .repository import SQLiteRepository
from .model import GameError
from .adapters.cli import CLI
from .presentation import Presentation
from .settings import Settings


def main():
    parser = argparse.ArgumentParser(description="StarRoute Traders trusted local CLI")
    parser.add_argument("--db", default="starroute.db", help="shared local SQLite path")
    parser.add_argument("--player", required=True, help="trusted local player ID, not authentication")
    parser.add_argument("--config", help="JSON catalog for a new world")
    parser.add_argument("--command", help="execute a single command, then exit")
    parser.add_argument("--lang", choices=("ja","en"), help="session language override; use language command to save")
    parser.add_argument("--settings", help="runtime settings JSON; paths resolve relative to this file")
    args = parser.parse_args()
    view = None
    repository = None
    try:
        settings = Settings.load(args.settings)
        view = Presentation(args.lang or settings.default_language, files=settings.language_files)
        identifier(args.player)
        clock = SystemClock()
        catalog = Catalog.load(args.config) if args.config else None
        repository = SQLiteRepository(args.db, catalog, clock.now(), default_catalog_path=settings.game_file)
        cli = CLI(Application(repository, clock, settings.default_language), args.player, language=args.lang, language_files=settings.language_files)
        view = cli.view
        if args.command is not None:
            return cli.safe_execute(args.command)[1]
        cli.run()
        return 0
    except GameError as exc:
        print(view.error(exc.code) if view else "Configuration error: " + exc.code, file=sys.stderr)
        return 1
    except (sqlite3.Error, OSError):
        print(view.text("db_open") if view else "Cannot read configuration.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        if repository:
            repository.close()


if __name__ == "__main__":
    raise SystemExit(main())
