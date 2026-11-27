"""Collect named progress points for the isolated Telnet fixture's guild-to-main step."""
import json
import time
from pathlib import Path

READS = ('status', 'flight', 'map', 'ui_info')
EVENTS = {'input-main', 'input-main-other-screen', 'handler-done', 'draw-main', 'draw-other-screen', 'flushed'}
EVENTS.update(f'{op}-{phase}' for op in READS for phase in ('begin', 'end'))


def install(path):
    # This process hosts only the private acceptance Door. Runtime packages never import this module.
    from starroute.local_door import LocalDoor
    from starroute_bbs.menu import Menu

    path = Path(path)
    armed = path.with_suffix('.armed')
    handle, call, draw = Menu.handle, LocalDoor.call, Menu.draw
    watching = False

    def mark(event):
        with path.open('a', encoding='ascii') as stream:
            stream.write(f'{time.monotonic_ns()} {event}\n')

    def handle_input(menu, line):
        nonlocal watching
        if line.lower() == 'm' and armed.is_file():
            watching = True
            mark('input-main' if (menu.state, menu.action) == ('TEXT', 'result') else 'input-main-other-screen')
        result = handle(menu, line)
        if watching:
            mark('handler-done')
        return result

    def read_backend(door, operation, *args, **kwargs):
        tracked = watching and operation in READS
        if tracked:
            mark(operation+'-begin')
        result = call(door, operation, *args, **kwargs)
        if tracked:
            mark(operation+'-end')
        return result

    def draw_frame(menu, *args, **kwargs):
        nonlocal watching
        if watching:
            mark('draw-main' if menu.state == 'MAIN' else 'draw-other-screen')
        result = draw(menu, *args, **kwargs)
        if watching:
            mark('flushed')
            watching = False
        return result

    Menu.handle, LocalDoor.call, Menu.draw = handle_input, read_backend, draw_frame


def report(path, started_ns, received, error):
    """Emit only fixed labels, relative times and byte counts before the private fixture is removed."""
    progress = []
    try:
        with path.open('r', encoding='ascii') as stream:
            for line in stream:
                fields = line.split()
                if len(fields) == 2 and fields[0].isdigit() and fields[1] in EVENTS:
                    progress.append([fields[1], (int(fields[0])-started_ns)//1_000_000])
    except (OSError, ValueError):
        pass
    result = {'step': 'guild-return', 'error': type(error).__name__, 'door_progress_ms': progress,
              'wait_ms': (time.monotonic_ns()-started_ns)//1_000_000, 'buffered_bytes': len(received),
              'received_frame_start': b'\x1b[2J' in received}
    print('SRT_TELNET_STEP '+json.dumps(result), flush=True)

