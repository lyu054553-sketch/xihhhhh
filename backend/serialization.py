"""One JSON boundary for money, persisted payloads and HTTP responses."""
from datetime import date, datetime
from decimal import Decimal
from functools import wraps
import inspect
import json
import math

def json_value(value):
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("金额必须为有限数值")
        return float(value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("数值不能为 NaN 或 Infinity")
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def dumps(value):
    return json.dumps(json_value(value), ensure_ascii=False, allow_nan=False)


def numeric_response(endpoint):
    @wraps(endpoint)
    def respond(*args, **kwargs):
        return json_value(endpoint(*args, **kwargs))
    # Resolve annotations in the endpoint's module, rather than this wrapper.
    respond.__signature__ = inspect.signature(endpoint, eval_str=True)
    return respond
