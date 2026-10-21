"""A successful runner exit alone must not pass the target-compiler check."""
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/check_plex_sandbox.py'
SPEC = importlib.util.spec_from_file_location('sandbox_check', SCRIPT)
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class ReportTests(unittest.TestCase):
    def run_check(self, transform):
        def runner(command, input, **kwargs):
            payload = json.loads(input)
            report = {'negativeControlRejectedYield': True,
                      'files': [{'file': name, 'compiled': True}
                                for name in payload['sources']]}
            report = transform(report)
            return SimpleNamespace(returncode=0, stdout=json.dumps(report) if report else '', stderr='')

        with patch.object(CHECK.subprocess, 'run', runner), redirect_stdout(io.StringIO()):
            with patch('sys.argv', [str(SCRIPT), '--libraries', '/example', '--', 'runtime']):
                return CHECK.main()

    def test_missing_report_fails_even_when_runner_exits_zero(self):
        self.assertNotEqual(self.run_check(lambda report: None), 0)

    def test_missing_module_fails(self):
        def omit_module(report):
            report['files'].pop()
            return report
        self.assertNotEqual(self.run_check(omit_module), 0)

    def test_accepted_negative_control_fails(self):
        def accept_yield(report):
            report['negativeControlRejectedYield'] = False
            return report
        self.assertNotEqual(self.run_check(accept_yield), 0)

    def test_complete_successful_report_passes(self):
        self.assertEqual(self.run_check(lambda report: report), 0)


if __name__ == '__main__':
    unittest.main()
