import socket
import unittest
from scripts.telnet_wait import wait_prompt, close_servers


class Client:
    def __init__(self, events):
        self.events = iter(events)
        self.buf = b''
        self.sock = self
        self.timeout = 10
        self.now = 0
        self.receives = 0
    def gettimeout(self): return self.timeout
    def settimeout(self, value): self.timeout = value
    def receive(self):
        self.receives += 1
        self.now += self.timeout
        event = next(self.events)
        if isinstance(event, Exception): raise event
        self.buf += event
    def send(self, value): raise AssertionError('must not resend mutation')


class TelnetWaitTests(unittest.TestCase):
    def test_delayed_fragmented_prompt_preserves_tail_without_resend(self):
        c = Client([socket.timeout()] * 11 + [b'result Se', b'lect > tail'])
        self.assertEqual(wait_prompt(c, clock=lambda: c.now), b'result Select > ')
        self.assertEqual(c.buf, b'tail')
        self.assertEqual(c.timeout, 10)
        self.assertGreater(c.now, 10)

    def test_silent_and_trickling_peers_stop_at_total_deadline(self):
        for events in ([socket.timeout()] * 5, [b'.'] * 5):
            c = Client(events)
            with self.assertRaisesRegex(TimeoutError, 'deadline'):
                wait_prompt(c, timeout=3, clock=lambda: c.now)
            self.assertEqual(c.receives, 3)
            self.assertEqual(c.timeout, 10)

    def test_disconnect_is_not_retried(self):
        c = Client([ConnectionResetError('closed')])
        with self.assertRaises(ConnectionResetError):
            wait_prompt(c, clock=lambda: c.now)
        self.assertEqual(c.receives, 1)
        self.assertEqual(c.timeout, 10)

    def test_existing_prompt_does_not_read(self):
        c = Client([]); c.buf = b'Select > next'
        self.assertEqual(wait_prompt(c), b'Select > ')
        self.assertEqual(c.receives, 0)
        self.assertEqual(c.buf, b'next')

    def test_cleanup_keeps_primary_error_and_closes_remaining_servers(self):
        calls = []
        class Server:
            def close(self):
                calls.append(1)
                raise TimeoutError('cleanup')
        with self.assertRaisesRegex(ValueError, 'primary'):
            try: raise ValueError('primary')
            finally: close_servers([Server(), Server()])
        self.assertEqual(len(calls), 2)
        with self.assertRaisesRegex(TimeoutError, 'cleanup'):
            close_servers([Server()])
