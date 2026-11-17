import unittest
from scripts.telnet_confirmation import confirm_menu
from tests.test_bbs_ui import Backend
from starroute_bbs.menu import Menu
from starroute_bbs.terminal import Terminal, ANSI


class TelnetConfirmationTests(unittest.TestCase):
    def test_requoted_sale_is_confirmed_once_in_both_languages(self):
        for language in ('ja', 'en'):
            with self.subTest(language=language):
                backend = Backend()
                menu = Menu(Terminal(backend, language))
                menu.refresh()
                for key in ('4', '1', '1'):
                    menu.handle(key)
                original_request = menu.draft['request_id']
                backend.price = 200
                def command(line):
                    menu.handle(line)
                    return ANSI.sub('', '\n'.join(menu.render()))
                confirm_menu(command)
                self.assertEqual(menu.state, 'TEXT')
                self.assertEqual(len(backend.mutations), 1)
                self.assertEqual(backend.mutations[0][1]['expected_total'], 200)
                self.assertNotEqual(backend.mutations[0][2], original_request)

    def test_paging_then_requote_reviews_before_second_confirmation(self):
        calls = []
        frames = iter(['Use > to review the remaining details.', 'details',
                       'Price changed. Review the new total and confirm with Y.', 'done'])
        def command(line):
            calls.append(line)
            return next(frames)
        self.assertEqual(confirm_menu(command), 'done')
        self.assertEqual(calls, ['y', '>', 'y', 'y'])

    def test_unstable_quote_stops_instead_of_retrying_forever(self):
        calls = []
        def command(line):
            calls.append(line)
            return 'Price changed. Review the new total and confirm with Y.'
        with self.assertRaisesRegex(AssertionError, 'bounded'):
            confirm_menu(command, limit=2)
        self.assertEqual(calls, ['y', 'y', 'y'])

    def test_other_error_is_not_retried(self):
        calls = []
        def command(line):
            calls.append(line)
            return 'Insufficient stock'
        self.assertEqual(confirm_menu(command), 'Insufficient stock')
        self.assertEqual(calls, ['y'])
