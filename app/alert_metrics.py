"""Pure alert contracts/calculator. No DB, settings, tasks or notification imports.

Deliberately one explicit observation interface. Latest rates and strict fixed
volume only: no implicit all-interface aggregation or invented legacy coverage.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import math
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Capacity(Strict):
    mode: Literal['independent', 'shared'] = 'independent'
    source: Literal['manual_contract'] = 'manual_contract'
    in_bps: int | None = Field(None, gt=0, le=10**15)
    out_bps: int | None = Field(None, gt=0, le=10**15)
    shared_bps: int | None = Field(None, gt=0, le=10**15)

    @model_validator(mode='after')
    def valid_mode(self):
        if self.mode == 'shared':
            if not self.shared_bps or self.in_bps or self.out_bps:
                raise ValueError('共享容量需明确填写，不能混用独立双向容量')
        elif self.shared_bps:
            raise ValueError('独立双向不能配置共享容量')
        return self


class Latest(Strict):
    kind: Literal['latest'] = 'latest'


class Fixed(Strict):
    kind: Literal['fixed']
    start: datetime
    end: datetime
    timezone: str

    @model_validator(mode='after')
    def valid_range(self):
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('需要有效 IANA 时区') from None
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError('日期必须包含明确 UTC 偏移')
        # Endpoint offsets define absolute instants; IANA zone is display metadata,
        # not a second interpretation of local wall time (including DST folds).
        seconds = (self.end.astimezone(timezone.utc) - self.start.astimezone(timezone.utc)).total_seconds()
        if not 0 < seconds <= 31 * 86400:
            raise ValueError('日期范围需大于零且不超过31天；结束时刻不包含')
        return self


class Condition(Strict):
    metric: Literal['cpu', 'memory', 'root_disk', 'network.rate', 'network.utilization', 'network.volume']
    interface: str | None = Field(None, min_length=1, max_length=32)
    direction: Literal['in', 'out', 'total', 'any'] | None = None
    window: Latest | Fixed = Field(default_factory=Latest, discriminator='kind')
    threshold: str = Field(max_length=64)
    capacity: Capacity | None = None

    @model_validator(mode='after')
    def semantic(self):
        try:
            threshold = Decimal(self.threshold)
        except Exception:
            raise ValueError('阈值必须为有限非负数') from None
        if not threshold.is_finite() or threshold < 0 or threshold > Decimal('1e30'):
            raise ValueError('阈值必须为有限非负数且不超过10^30')
        if threshold and threshold.as_tuple().exponent < -12:
            raise ValueError('阈值最多支持12位小数')
        canonical = format(threshold, 'f') if threshold else '0'
        self.threshold = canonical.rstrip('0').rstrip('.') if '.' in canonical else canonical
        network = self.metric.startswith('network.')
        if network != bool(self.interface) or network != bool(self.direction):
            raise ValueError('网络指标必须明确选择单一计量接口和方向；系统指标不接受这些字段')
        if self.metric == 'network.volume':
            if not isinstance(self.window, Fixed) or threshold != threshold.to_integral_value():
                raise ValueError('累计流量需要固定日期和整数字节阈值')
        elif not isinstance(self.window, Latest):
            raise ValueError('此指标仅支持最新有效样本')
        if self.metric != 'network.utilization':
            if self.capacity or self.direction == 'any':
                raise ValueError('容量和任一方向仅用于带宽利用率')
        else:
            if self.capacity is None:
                raise ValueError('百分比需先填写用户配置的线路容量')
            c = self.capacity
            if c.mode == 'independent':
                if self.direction == 'total':
                    raise ValueError('独立双向没有合计饱和度，请选入站、出站或任一方向')
                if self.direction in ('in', 'any') and not c.in_bps or self.direction in ('out', 'any') and not c.out_bps:
                    raise ValueError('缺少所选方向的线路容量')
            elif self.direction == 'any':
                raise ValueError('共享容量请选入站、出站或合计')
        if not network and threshold > 100:
            raise ValueError('系统百分比阈值应在0至100之间')
        return self


def result(condition, *, value=None, lower=None, upper=None, quality='unknown', reason='', watermark=None):
    threshold = Decimal(condition.threshold)
    bad = None
    if value is not None:
        bad = Decimal(str(value)) >= threshold
    elif lower is not None and Decimal(str(lower)) >= threshold:
        bad = True
    elif upper is not None and Decimal(str(upper)) < threshold:
        bad = False
    return dict(value=None if value is None else str(value), lower=None if lower is None else str(lower),
                upper=None if upper is None else str(upper), quality=quality, reason=reason, bad=bad,
                unit='byte' if condition.metric == 'network.volume' else 'bit/s' if condition.metric == 'network.rate' else '%',
                watermark=watermark.isoformat() if watermark else None,
                normalized_condition=condition.model_dump(mode='json'))


def _valid(p):
    start, end, elapsed = p.get('interval_start'), p.get('ts'), p.get('elapsed_seconds')
    return (p.get('quality') == 'valid' and start is not None and end is not None
            and end > start
            and elapsed is not None and math.isfinite(elapsed) and 0 < elapsed <= 300
            and abs((end-start).total_seconds()-elapsed) <= max(0.1, elapsed * 0.02)
            and p.get('rx_delta', -1) >= 0 and p.get('tx_delta', -1) >= 0)


def volume_result(c, lower, upper, watermark, reason=''):
    exact = upper is not None and lower == upper
    return result(c, value=lower if exact else None, lower=lower, upper=upper,
                  quality='valid' if exact else 'partial', reason=reason or ('' if exact else 'boundary_or_gap'), watermark=watermark)


def evaluate(c: Condition, points: list[dict], now: datetime) -> dict:
    if isinstance(c.window, Fixed) and now <= c.window.start:
        return result(c, reason='scheduled')
    if not points:
        return result(c, reason='history_missing')
    points = sorted(points, key=lambda p: p['ts'])
    p = points[-1]
    if c.metric == 'network.volume':
        start, end = c.window.start, min(c.window.end, now)
        lower = upper = 0
        cursor = start
        complete = True
        seen = set()
        previous = None
        relevant = []
        for p in points:
            if p['ts'] in seen:
                continue
            seen.add(p['ts'])
            a, b = p.get('interval_start'), p['ts']
            if b <= start or b > end + timedelta(seconds=300) or a is not None and a >= end:
                continue
            relevant.append(p)
            if previous is not None and a is not None and a < previous:
                return result(c, reason='overlapping_intervals')
            if previous is not None and a != previous:
                complete = False
            previous = b
            if not _valid(p):
                complete = False
                continue
            assert a is not None  # established by _valid
            if a > cursor:
                complete = False
            cursor=max(cursor,b)
            n = p['rx_delta'] if c.direction == 'in' else p['tx_delta'] if c.direction == 'out' else p['rx_delta']+p['tx_delta']
            upper += n
            if a >= start and b <= end:
                lower += n
        if not relevant:
            return result(c, reason='history_missing')
        return volume_result(c,lower,upper if complete and cursor >= end else None,relevant[-1]['ts'])
    eligible = [point for point in points if point['ts'] <= now + timedelta(seconds=5)]
    if not eligible:
        return result(c, reason='clock_skew', watermark=p['ts'])
    quarantined = len(eligible) != len(points)
    p = eligible[-1]
    age=(now-p['ts']).total_seconds()
    if age < -5 or age > (180 if not c.metric.startswith('network.') else 45):
        return result(c, reason='clock_skew' if age < -5 else 'stale', watermark=p['ts'])
    if not c.metric.startswith('network.'):
        v=p.get({'cpu':'cpu_pct','memory':'mem_pct','root_disk':'disk_pct'}[c.metric])
        if v is None or not math.isfinite(v) or not 0 <= v <= 100:
            return result(c, reason='metric_missing',watermark=p['ts'])
    else:
        if not _valid(p):
            return result(c, reason='legacy_interval' if not p.get('interval_start') else 'invalid_interval',watermark=p['ts'])
        rx=Decimal(p['rx_delta'])*8/Decimal(str(p['elapsed_seconds']))
        tx=Decimal(p['tx_delta'])*8/Decimal(str(p['elapsed_seconds']))
        v=rx if c.direction=='in' else tx if c.direction=='out' else rx+tx
        if c.metric=='network.utilization':
            cap=c.capacity
            if cap.mode=='shared':
                v=v*100/cap.shared_bps
            elif c.direction=='any':
                v=max(rx/cap.in_bps,tx/cap.out_bps)*100
            else:
                v=v*100/(cap.in_bps if c.direction=='in' else cap.out_bps)
    return result(c,value=v,quality='valid',reason='future_clock_quarantined' if quarantined else '',watermark=p['ts'])
