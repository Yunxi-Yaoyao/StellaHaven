"""One post-validation configuration budget for every native Nav admission."""
import json
from fastapi import HTTPException

MAX_CONFIG_BYTES = 2 * 1024**2


def canonical(value):
    # JSON has one number type; browsers serialize 4.0 as 4.
    def numbers(v):
        if isinstance(v, float) and v.is_integer(): return int(v)
        if isinstance(v, dict): return {k: numbers(x) for k, x in v.items()}
        if isinstance(v, list): return [numbers(x) for x in v]
        return v
    return json.dumps(numbers(value), ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def check_config_budget(data):
    """Call only on default-expanded, validated NavData (after asset rebinding)."""
    if len(canonical(data).encode('utf-8')) > MAX_CONFIG_BYTES:
        raise HTTPException(413, '导航配置超过 2 MiB；未写入')
