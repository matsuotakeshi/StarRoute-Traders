"""Bounded receive-only waits for isolated Telnet acceptance tests."""
import socket
import sys
import time


def wait_prompt(client, marker=b'Select > ', timeout=30, *, clock=time.monotonic):
    """Keep partial frames; never resend an input after an uncertain outcome."""
    if timeout <= 0 or not marker:
        raise ValueError('positive timeout and nonempty marker required')
    deadline = clock() + timeout
    original = client.sock.gettimeout()
    try:
        while marker not in client.buf:
            remaining = deadline - clock()
            if remaining <= 0:
                raise TimeoutError(f'Telnet prompt deadline exceeded ({timeout}s)')
            client.sock.settimeout(min(1, remaining))
            try:
                client.receive()
            except socket.timeout:
                pass
        result, client.buf = client.buf.split(marker, 1)
        return result + marker
    finally:
        client.sock.settimeout(original)


def close_servers(servers):
    """Report cleanup errors without replacing an in-flight test exception."""
    primary = sys.exc_info()[0] is not None
    first = None
    for server in servers:
        try:
            server.close()
        except Exception as exc:
            print('TELNET cleanup failed: ' + type(exc).__name__, flush=True)
            if first is None:
                first = exc
    if first is not None and not primary:
        raise first
