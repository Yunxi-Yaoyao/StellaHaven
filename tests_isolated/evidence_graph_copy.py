"""Fresh exact-built-in cloning for the source-only response test dependency.

No loader bytes, reads, hashes, validations or assertions change. Each call walks
its input afresh. Only exact dict/list and immutable JSON scalars are handled;
custom types, non-string keys, non-finite floats and explicit memos delegate to
original deepcopy. No serialized data, persistent results or validation cache.
"""
import copy
from contextlib import contextmanager
import math
from unittest.mock import patch

_ORIGINAL = copy.deepcopy
_NONE_TYPE = type(None)

class _NotPlain(Exception):
    pass

def _clone(value, memo):
    kind = type(value)
    if kind is str or kind is int or kind is bool or kind is _NONE_TYPE:
        return value
    if kind is float:
        if not math.isfinite(value):
            raise _NotPlain
        return value
    if kind is not dict and kind is not list:
        raise _NotPlain
    identity = id(value)
    if identity in memo:
        return memo[identity]
    result = {} if kind is dict else []
    memo[identity] = result
    if kind is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise _NotPlain
            item_kind = type(item)
            if item_kind is str or item_kind is int or item_kind is bool or item_kind is _NONE_TYPE:
                result[key] = item
            elif item_kind is float and math.isfinite(item):
                result[key] = item
            else:
                result[key] = _clone(item, memo)
    else:
        for item in value:
            item_kind = type(item)
            if item_kind is str or item_kind is int or item_kind is bool or item_kind is _NONE_TYPE:
                result.append(item)
            elif item_kind is float and math.isfinite(item):
                result.append(item)
            else:
                result.append(_clone(item, memo))
    return result

def graph_copy(value, memo=None, *args, **kwargs):
    if memo is not None or args or kwargs:
        return _ORIGINAL(value, memo, *args, **kwargs)
    try:
        # Copy and exact-type validation are one fresh traversal. Nothing is
        # exposed on an unsafe graph: discard the private partial copy and use
        # original semantics, including any custom __deepcopy__/__reduce__.
        return _clone(value, {})
    except (_NotPlain, RecursionError):
        return _ORIGINAL(value, memo)

@contextmanager
def contract_copy_dependency():
    with patch.object(copy, 'deepcopy', graph_copy):
        yield
