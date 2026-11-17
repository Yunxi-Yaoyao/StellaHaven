"""Process-local, bounded pure source derivations; never cache validation/I/O.

Keys contain complete text (not filenames, timestamps or asserted digests) and
all parser/type identities. Values contain only nested tuples/scalars: even a
parser that retains and mutates its returned AST cannot poison a warm entry.
"""
import ast
from functools import lru_cache
import hashlib
from types import SimpleNamespace

MAX_TEXT = 512 * 1024


def _build_index(text, parser, types):
    classdef, functiondef, asyncdef, assign, name, annassign = types
    def index(nodes):
        rows = []
        for node in nodes:
            if isinstance(node, (classdef, functiondef, asyncdef)):
                names = (node.name,)
            elif isinstance(node, assign):
                names = tuple(t.id for t in node.targets if isinstance(t, name))
            elif isinstance(node, annassign) and isinstance(node.target, name):
                names = (node.target.id,)
            else:
                continue
            rows.append((names, (node.lineno, node.end_lineno, node.col_offset,
                                  node.end_col_offset), index(getattr(node, 'body', [])),
                         isinstance(node, functiondef)))
        return tuple(rows)
    return index(parser(text).body)


_cached_index = lru_cache(maxsize=8)(_build_index)


def symbol_range(text, parts, *, function_only=False):
    types = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef,
             ast.Assign, ast.Name, ast.AnnAssign)
    derive = _cached_index if len(text) <= MAX_TEXT else _build_index
    nodes = derive(text, ast.parse, types)
    assert parts, 'empty source path'
    for part in parts:
        found = [row for row in nodes if part in row[0] and
                 (not function_only or row[3])]
        assert len(found) == 1, (parts, part)
        _, coordinates, nodes, _ = found[0]
    return coordinates


def _segment(text, coordinates, segmenter):
    line, end, col, end_col = coordinates
    node = SimpleNamespace(lineno=line, end_lineno=end, col_offset=col,
                           end_col_offset=end_col)
    return hashlib.sha256(segmenter(text, node).encode()).hexdigest()


_cached_segment = lru_cache(maxsize=256)(_segment)


def symbol_digest(text, coordinates):
    derive = _cached_segment if len(text) <= MAX_TEXT else _segment
    return derive(text, coordinates, ast.get_source_segment)


# Only stdlib JSON's default decoder is memoized. Keys are complete exact bytes,
# values are immutable process-local encodings, never approval/validation results.
# 128 MiB total input+encoding payload and 32 entries bound the measured 17-body
# approval working set (about 106 MiB); every return is a fresh mutable graph.
import json
import marshal
from collections import OrderedDict

_JSON_LOADS = json.loads
_JSON_DECODER = json._default_decoder
JSON_CACHE_BYTES = 128 * 1024 * 1024
_json_entries = OrderedDict()


def json_body(body):
    if (type(body) is not bytes or json.loads is not _JSON_LOADS or
            json._default_decoder is not _JSON_DECODER):
        return json.loads(body)
    encoded = _json_entries.get(body)
    if encoded is not None:
        _json_entries.move_to_end(body)
        return marshal.loads(encoded)
    value = _JSON_LOADS(body)
    if len(body) > JSON_CACHE_BYTES:
        return value
    encoded = marshal.dumps(value)
    cost = len(body) + len(encoded)
    if cost <= JSON_CACHE_BYTES:
        while _json_entries and (len(_json_entries) >= 32 or
                sum(len(k)+len(v) for k,v in _json_entries.items())+cost > JSON_CACHE_BYTES):
            _json_entries.popitem(last=False)
        _json_entries[body] = encoded
    return value
