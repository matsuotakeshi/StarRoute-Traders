"""Deterministic integration demonstration; no production DB or wall-clock waiting."""
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from starroute.application import Application
from starroute.clock import ManualClock
from starroute.repository import SQLiteRepository


def main():
    with tempfile.TemporaryDirectory() as directory:
        clock = ManualClock(100)
        repository = SQLiteRepository(str(Path(directory) / "demo.db"), now=clock.now())
        try:
            app = Application(repository, clock)
            start = app.create_player("captain", "船長")["cash"]
            print(f"開始資金: {start} Cr")
            receipt = app.buy_goods("captain", "grain", 10)
            print(f"オーロラで星穀10を購入: {receipt['total']} Cr")
            app.depart("captain", "forge")
            clock.advance(2)
            receipt = app.sell_goods("captain", "grain", 10)
            print(f"フォージへ到着、星穀10を売却: {receipt['total']} Cr")
            end = app.get_player("captain")["cash"]
            assert end - start == 600
            print(f"終了資金: {end} Cr / 利益: +{end - start} Cr")
        finally:
            repository.close()


if __name__ == "__main__":
    main()
