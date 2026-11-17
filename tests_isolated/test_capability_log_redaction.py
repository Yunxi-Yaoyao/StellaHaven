"""Exercise the real installed filter without importing keys, config or databases."""
import ast
import io
import logging
from pathlib import Path
import sys

import pytest
from uvicorn.logging import AccessFormatter

ROOT = Path(__file__).resolve().parents[1]
CAP = 'SYNTHETIC_ONLY_NOT_A_REAL_CAPABILITY_12345678'


@pytest.fixture
def redaction():
    source = ast.parse((ROOT / 'app/security.py').read_text())
    node = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == 'install_log_redaction')
    ns = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'security-filter', 'exec'), ns)
    names = ('uvicorn.access', 'uvicorn.error', 'stella')
    loggers = [logging.getLogger(name) for name in names]
    saved = [(logger, list(logger.filters)) for logger in loggers]
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root.handlers = [handler]
    for logger in loggers:
        logger.filters.clear()
    ns['install_log_redaction']()
    try:
        yield ns['install_log_redaction'], handler, stream
    finally:
        root.handlers = saved_handlers
        for logger, filters in saved:
            logger.filters[:] = filters
        handler.close()


def render(record, formatter=None):
    logging.getLogger(record.name).filter(record)
    return (formatter or logging.Formatter('%(levelname)s %(message)s')).format(record)


@pytest.mark.parametrize('prefix', ['/p/', '/%70/'])
def test_access_formatter_redacts_cap_and_query(redaction, prefix):
    record = logging.LogRecord('uvicorn.access', logging.INFO, 'fixture', 1,
                               '%s - "%s %s HTTP/%s" %d',
                               ('127.0.0.1:1234', 'GET', prefix + CAP + '/index.html?token=QUERY_SECRET', '1.1', 200), None)
    output = render(record, AccessFormatter('%(request_line)s %(status_code)s', use_colors=False))
    assert CAP not in output and 'QUERY_SECRET' not in output
    assert 'GET ' + prefix + '[redacted]/index.html HTTP/1.1' in output
    assert '200' in output
    assert len(record.args) == 5


@pytest.mark.parametrize('message', [
    'failed https://pages.example/p/' + CAP + '/index.html',
    'GET /%70/' + CAP + '/index.html',
    'capability=' + CAP,
    '{"cap": "' + CAP + '"}',
])
def test_formatted_messages_hide_paths_and_capability_fields(redaction, message):
    record = logging.LogRecord('stella', logging.ERROR, 'fixture', 1, 'failure: %s', (message,), None)
    output = render(record)
    assert CAP not in output
    assert 'failure:' in output and '[redacted]' in output


@pytest.mark.parametrize('mode', ['exc_info', 'exc_text', 'stack_info'])
def test_candidate_exception_formats_redact_at_formatter_boundary(redaction, mode):
    record = logging.LogRecord('uvicorn.error', logging.ERROR, 'fixture', 1, 'operation failed', (), None)
    message = 'failed /p/' + CAP + '/file capability=' + CAP
    if mode == 'exc_info':
        try:
            raise RuntimeError(message)
        except RuntimeError:
            record.exc_info = sys.exc_info()
        # A preceding handler may already have cached unsafe exception text.
        record.exc_text = 'cached ' + message
    else:
        setattr(record, mode, message)
    output = render(record)
    assert CAP not in output
    assert 'operation failed' in output and '[redacted]' in output
    if mode == 'exc_info':
        assert 'RuntimeError' in output and 'Traceback' in output
    # The record remains safe when formatted again by a second handler.
    assert CAP not in logging.Formatter().format(record)


def test_install_is_idempotent_and_root_handler_covers_children(redaction):
    install, handler, stream = redaction
    install()
    assert len(handler.filters) == 1
    for name in ('uvicorn.access', 'uvicorn.error', 'stella'):
        assert len(logging.getLogger(name).filters) == 1
    record = logging.LogRecord('stella.child', logging.ERROR, 'fixture', 1, 'failed /p/%s/file', (CAP,), None)
    handler.handle(record)
    assert CAP not in stream.getvalue()
    assert '[redacted]' in stream.getvalue()


@pytest.mark.parametrize('mode', ['message', 'exc_info', 'exc_text', 'stack_info'])
def test_existing_secret_and_query_rules_also_cover_exceptions(redaction, mode):
    message = ('password=PASSWORD_SECRET client_secret=CLIENT_SECRET '
               'https://service.invalid/path?state=QUERY_SECRET '
               '/oauth/authorize?code=OAUTH_SECRET')
    record = logging.LogRecord('stella', logging.ERROR, 'fixture', 1, 'failure', (), None)
    if mode == 'message':
        record.msg = message
    elif mode == 'exc_info':
        try:
            raise ValueError(message)
        except ValueError:
            record.exc_info = sys.exc_info()
    else:
        setattr(record, mode, message)
    output = render(record)
    for secret in ('PASSWORD_SECRET', 'CLIENT_SECRET', 'QUERY_SECRET', 'OAUTH_SECRET'):
        assert secret not in output
    assert '[redacted]' in output


def test_child_logger_without_root_handlers_is_redacted(redaction):
    install, handler, stream = redaction
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_last = logging.lastResort
    fallback_stream = io.StringIO()
    fallback = logging.StreamHandler(fallback_stream)
    try:
        root.handlers = []
        logging.lastResort = fallback
        install()
        logging.getLogger('stella.child').warning('capability=%s', CAP)
        assert CAP not in fallback_stream.getvalue()
        assert '[redacted]' in fallback_stream.getvalue()
        install()
        assert len(fallback.filters) == 1
    finally:
        root.handlers = saved_handlers
        logging.lastResort = saved_last
        fallback.close()


@pytest.mark.parametrize('logger_name', ['uvicorn.error', 'stella.relative_query_child'])
@pytest.mark.parametrize('prefix', ['/p/', '/%70/'])
@pytest.mark.parametrize('mode', ['message', 'exc_info', 'exc_text', 'stack_info'])
def test_relative_pages_queries_are_redacted_in_all_log_carriers(redaction, logger_name, prefix, mode):
    install, _, _ = redaction
    root = logging.getLogger()
    saved_handlers, saved_last = list(root.handlers), logging.lastResort
    stream = io.StringIO()
    fallback = logging.StreamHandler(stream)
    try:
        root.handlers = []
        logging.lastResort = fallback
        install()
        message = prefix + CAP + '/file?secret=QUERY_CANARY&state=STATE_CANARY'
        record = logging.LogRecord(logger_name, logging.ERROR, 'fixture', 1, 'operation failed', (), None)
        if mode == 'message':
            record.msg, record.args = 'failure: %s', (message,)
        elif mode == 'exc_info':
            try:
                raise RuntimeError(message)
            except RuntimeError:
                record.exc_info = sys.exc_info()
            record.exc_text = 'cached ' + message
        else:
            setattr(record, mode, message)
        logging.getLogger(logger_name).handle(record)
        output = stream.getvalue()
        assert output, 'the actual error/fallback handler must emit a log'
        assert CAP not in output
        assert 'QUERY_CANARY' not in output and 'STATE_CANARY' not in output
        assert prefix + '[redacted]/file?[redacted]' in output
        assert 'operation failed' in output or 'failure:' in output
        assert not any(secret in logging.Formatter().format(record)
                       for secret in (CAP, 'QUERY_CANARY', 'STATE_CANARY'))
    finally:
        root.handlers = saved_handlers
        logging.lastResort = saved_last
        fallback.close()
