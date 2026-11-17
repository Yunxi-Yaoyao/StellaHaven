"""Opt-in pytest/CLI import and network fence for offline contract checks.

Load with -p tests_isolated.api_response_guard, never from whole-app conftest.
"""
import sys


class NoProductionImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'main', 'app.config', 'app.database'}:
            raise AssertionError('Forbidden production import: ' + fullname)


sys.meta_path.insert(0, NoProductionImports())


def audit(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo'}:
        raise AssertionError('No network permitted in response-contract checks: ' + event)


sys.addaudithook(audit)
