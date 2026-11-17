"""Read-only public projection of persisted metric alerts; never repairs storage.

Condition is the shared semantic contract, not Intent/save: reading an ended
fixed window must not rerun live inventory or current-time admission checks.
"""
import json
import math
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, ValidationError, field_validator, model_validator
from app.alert_metrics import Capacity, Condition, Fixed, Latest, Strict


def _fields(value, model):
    if not isinstance(value, dict):
        raise ValueError('expected stored object')
    return {key: item for key, item in value.items() if key in model.model_fields}


def stored_condition(value):
    """Whitelist nested fields, then use the existing strict semantic contract."""
    data = _fields(value, Condition)
    if data.get('window') is not None:
        window = data['window']
        # Unknown discriminator still fails Condition validation.
        model = Latest if isinstance(window, dict) and window.get('kind') == 'latest' else Fixed
        data['window'] = _fields(window, model)
    if data.get('capacity') is not None:
        data['capacity'] = _fields(data['capacity'], Capacity)
    return Condition.model_validate_json(json.dumps(data, allow_nan=False), strict=True)


DecimalText = Annotated[str, Field(max_length=128,
    pattern=r'^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$')]


class PublicMetricPreview(Strict):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)
    value: DecimalText | None
    lower: DecimalText | None
    upper: DecimalText | None
    quality: Literal['valid', 'partial', 'unknown']
    reason: Literal['', 'target_missing', 'interface_missing', 'scheduled',
        'query_unavailable', 'query_budget', 'history_missing', 'overlapping_intervals',
        'evaluation_lag', 'boundary_or_gap', 'clock_skew', 'stale', 'metric_missing',
        'legacy_interval', 'invalid_interval', 'future_clock_quarantined']
    bad: bool | None
    unit: Literal['byte', 'bit/s', '%']
    watermark: Annotated[str, Field(pattern=r'^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})$', json_schema_extra={'format': 'date-time'})] | None
    normalized_condition: Condition

    @field_validator('value', 'lower', 'upper')
    @classmethod
    def finite_decimal(cls, value):
        if value is not None:
            try:
                valid = Decimal(value) >= 0 and math.isfinite(float(value))
            except (InvalidOperation, OverflowError):
                valid = False
            if not valid:
                raise ValueError('expected finite nonnegative observation')
        return value

    @field_validator('watermark')
    @classmethod
    def aware_timestamp(cls, value):
        if value is not None and datetime.fromisoformat(value).tzinfo is None:
            raise ValueError('expected offset timestamp')
        return value

    @model_validator(mode='after')
    def writer_shape(self):
        c = self.normalized_condition
        expected_unit = 'byte' if c.metric == 'network.volume' else 'bit/s' if c.metric == 'network.rate' else '%'
        if self.quality == 'valid' and self.reason not in ('', 'future_clock_quarantined'):
            raise ValueError('valid observation has unknown-data reason')
        if self.quality == 'partial' and self.reason != 'boundary_or_gap':
            raise ValueError('partial observation lacks boundary reason')
        if self.quality == 'unknown' and self.reason in ('boundary_or_gap', 'future_clock_quarantined'):
            raise ValueError('unknown observation has valid-data reason')
        if self.unit != expected_unit:
            raise ValueError('unit mismatch')
        value, lower, upper = (Decimal(v) if v is not None else None for v in (self.value, self.lower, self.upper))
        if lower is not None and upper is not None and lower > upper:
            raise ValueError('inverted bounds')
        if self.quality == 'unknown':
            if any(v is not None for v in (value, lower, upper, self.bad)):
                raise ValueError('unknown observation has a value')
        else:
            if self.watermark is None:
                raise ValueError('observation lacks watermark')
            if self.quality == 'valid' and value is None:
                raise ValueError('valid observation lacks value')
            if self.quality == 'partial' and (value is not None or lower is None or c.metric != 'network.volume'):
                raise ValueError('invalid partial observation')
            if c.metric == 'network.volume':
                if self.quality == 'valid' and not (value == lower == upper):
                    raise ValueError('exact volume lacks equal bounds')
                if any(v is not None and v != v.to_integral_value() for v in (value, lower, upper)):
                    raise ValueError('volume is not whole bytes')
            elif lower is not None or upper is not None:
                raise ValueError('latest sample has volume bounds')
            if c.metric in ('cpu', 'memory', 'root_disk') and value is not None and value > 100:
                raise ValueError('system percentage outside range')
        threshold = Decimal(c.threshold)
        expected_bad = (value >= threshold if value is not None else True if lower is not None and lower >= threshold
                        else False if upper is not None and upper < threshold else None)
        if self.bad is not expected_bad:
            raise ValueError('threshold result mismatch')
        return self


class AlertReadProjection(Strict):
    state: Literal['incomplete'] = 'incomplete'
    invalid_fields: list[Literal['condition', 'preview', 'node_id', 'severity', 'state']]


class PublicMetricRule(Strict):
    id: int
    node_id: int | None
    label: str
    condition: Condition | None
    severity: Literal['warning', 'critical'] | None
    debounce: int
    repeat_minutes: int
    email: bool
    enabled: bool
    revision: int
    state: Literal['ok', 'firing', 'unknown']
    preview: PublicMetricPreview | None
    evaluated_at: datetime | None
    projection: AlertReadProjection | None = None


def public_metric_rule(rule, state):
    """Validate each JSON slot independently and retain real identity/state."""
    invalid = []
    try:
        condition = stored_condition(rule.condition)
    except (ValueError, TypeError, ValidationError):
        condition = None
        invalid.append('condition')
    preview = None
    if state is not None and state.preview is not None:
        try:
            data = _fields(state.preview, PublicMetricPreview)
            data['normalized_condition'] = stored_condition(data.get('normalized_condition'))
            preview = PublicMetricPreview.model_validate(data)
            if condition is None or preview.normalized_condition != condition:
                raise ValueError('preview condition mismatch')
        except (ValueError, TypeError, ValidationError):
            preview = None
            invalid.append('preview')
    node_id = int(rule.target) if isinstance(rule.target, str) and rule.target.isascii() and rule.target.isdecimal() else None
    if node_id is None or node_id <= 0:
        node_id = None
        invalid.append('node_id')
    severity = rule.severity if rule.severity in ('warning', 'critical') else None
    if severity is None:
        invalid.append('severity')
    current_state = state.state if state else 'ok'
    if current_state not in ('ok', 'firing'):
        current_state = 'unknown'
        invalid.append('state')
    if state is None and invalid:
        current_state = 'unknown'
    output = PublicMetricRule(id=rule.id, node_id=node_id, label=rule.label,
        condition=condition, severity=severity, debounce=rule.debounce,
        repeat_minutes=rule.repeat_minutes, email=rule.email, enabled=rule.enabled,
        revision=rule.revision, state=current_state, preview=preview,
        evaluated_at=state.evaluated_at if state else None).model_dump(mode='python')
    if invalid:
        output['projection'] = AlertReadProjection(invalid_fields=invalid).model_dump()
    else:
        output.pop('projection')
    # Condition's writer uses JSON mode for fixed-window datetimes too.
    if condition is not None:
        output['condition'] = condition.model_dump(mode='json')
    if preview is not None:
        output['preview'] = preview.model_dump(mode='json')
    return output
