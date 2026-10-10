import unittest
from datetime import datetime
from log_downloader import select_log, select_logs


class SelectionTests(unittest.TestCase):
    def test_time_intervals(self):
        names = ['tasks_manager_info_20260922-092747.4060',
                 'tasks_manager_info_20260922-103000.4061', 'tasks_manager.INFO']
        self.assertEqual(select_log(names, 'tasks_manager', datetime(2026, 9, 22, 10)), names[0])
        self.assertEqual(select_log(names, 'tasks_manager', datetime(2026, 9, 22, 10, 30)), names[1])
        self.assertIsNone(select_log(names, 'tasks_manager', datetime(2026, 9, 21)))
        self.assertEqual(select_log(names, 'tasks_manager', None), names[2])

    def test_invalid_and_missing(self):
        self.assertIsNone(select_log(['node_info_20269922-092747.1', 'node.WARNING'], 'node', datetime.now()))
        self.assertIsNone(select_log([], 'node', None))

    def test_latest_names_differ_from_directory(self):
        """Directories need not share the basename of their INFO links."""
        self.assertEqual(select_logs(['dcn.INFO', 'dcn.WARNING'], 'dynamic_controller', None), ['dcn.INFO', 'dcn.WARNING'])
        self.assertEqual(select_logs(['b.INFO', 'a.INFO', 'a_info_20260922-092747.1'], 'node', None), ['a.INFO', 'b.INFO'])
        self.assertEqual(select_logs([], 'node', None), [])

    def test_historical_different_basename(self):
        """Historical timestamp matching also accepts a different node basename."""
        names = ['dcn_info_20260922-092747.1', 'dcn_info_20260922-103000.2']
        self.assertEqual(select_logs(names, 'dynamic_controller', datetime(2026, 9, 22, 10)), [names[0]])

    def test_warning_and_error_logs(self):
        names = ['dcn.INFO', 'dcn.ERROR', 'dcn.WARNING', 'dcn_warn_20261009-200342.3605',
                 'dcn_error_20261009-210000.1']
        self.assertEqual(select_logs(names, 'dynamic_controller', None), ['dcn.ERROR', 'dcn.INFO', 'dcn.WARNING'])
        selected = select_logs(names, 'dynamic_controller', datetime(2026, 10, 9, 20, 30))
        self.assertEqual(selected, ['dcn_warn_20261009-200342.3605'])


if __name__ == '__main__':
    unittest.main()
