"""Shared, non-consuming pattern and sequence rules for CG-02–05 and CG-11.

Database allocation and authorization belong to the calling service. This
module has no database, clock, configuration-cache or resource side effects.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal, localcontext
import re
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


TOKENS = frozenset({
    "YYYY", "YY", "MM", "DD", "DATE", "PARENT_AGGREGATION_NUMBER",
    "CLASSIFICATION_CODE", "CLASSIFICATION_SCHEME_CODE", "ORG_UNIT_CODE",
    "ROLE_CODE", "SERIAL",
})
SCOPES = frozenset({"generator", "parent_aggregation", "classification", "org_unit"})
RESETS = frozenset({"never", "yearly", "monthly"})
SCENARIOS = frozenset({
    "same_scope", "year_transition", "month_transition", "different_scopes", "combined",
})
WHITE_SPACE = "\t\n\v\f\r \u0085\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"


def is_blank_text(value: Any) -> bool:
    """Match the Unicode whitespace set used by resource_type_has_text."""
    return value is None or (isinstance(value, str) and not value.strip(WHITE_SPACE))


class CodeGenerationError(ValueError):
    def __init__(self, code: str, *, field: str | None = None, **parameters: Any):
        self.code = code
        self.field = field
        self.parameters = parameters
        super().__init__(code, field, parameters)


def invalid(field: str, **parameters: Any) -> CodeGenerationError:
    return CodeGenerationError("code_generator_invalid", field=field, **parameters)


def whole_number(value: Any, field: str, *, minimum: int = 0) -> Decimal:
    """Accept exact whole values, including PostgreSQL numeric results."""
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise invalid(field)
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value) is None:
        raise invalid(field)
    number = Decimal(value)
    if not number.is_finite() or number != number.to_integral_value() or number < minimum:
        raise invalid(field)
    return number


def serial_text(value: Any) -> str:
    # Decimal construction/formatting preserves integers beyond the browser's
    # safe range and Python's configurable int-to-string digit threshold.
    number = whole_number(value, "serial")
    return "0" if number.is_zero() else format(number, "f").split(".", 1)[0]


def add_serial(value: Any, increment: Any) -> Decimal:
    left = whole_number(value, "serial")
    right = whole_number(increment, "increment", minimum=1)
    with localcontext() as context:
        context.prec = max(len(serial_text(left)), len(serial_text(right))) + 1
        return left + right


@dataclass(frozen=True)
class PatternPart:
    text: str
    token: str | None = None


def parse_pattern(pattern: str) -> tuple[PatternPart, ...]:
    if not isinstance(pattern, str) or "\x00" in pattern:
        raise invalid("pattern")
    parts: list[PatternPart] = []
    literal: list[str] = []

    def flush() -> None:
        if literal:
            parts.append(PatternPart("".join(literal)))
            literal.clear()

    position = 0
    while position < len(pattern):
        pair = pattern[position:position + 2]
        if pair in {"{{", "}}"}:
            literal.append(pair[0])
            position += 2
        elif pattern[position] == "{":
            flush()
            end = pattern.find("}", position + 1)
            if end < 0:
                raise invalid("pattern")
            token = pattern[position + 1:end]
            if token not in TOKENS:
                raise invalid("pattern", placeholder=token)
            parts.append(PatternPart("", token))
            position = end + 1
        elif pattern[position] == "}":
            raise invalid("pattern")
        else:
            literal.append(pattern[position])
            position += 1
    flush()
    if sum(part.token == "SERIAL" for part in parts) != 1:
        raise invalid("pattern")
    return tuple(parts)


@dataclass(frozen=True)
class GeneratorConfig:
    name: str
    pattern: str
    parts: tuple[PatternPart, ...]
    start: Decimal
    increment: Decimal
    scope: str
    reset_frequency: str
    padding_width: int
    max_code_length: int

    @classmethod
    def from_mapping(
        cls, values: Mapping[str, Any], *, globally_unique_number: bool = False,
        field_max_length: int | None = None,
    ) -> GeneratorConfig:
        name = values.get("name")
        if not isinstance(name, str) or is_blank_text(name) or "\x00" in name:
            raise invalid("name")
        parts = parse_pattern(values.get("pattern"))
        start = whole_number(values.get("start", 1), "start")
        increment = whole_number(values.get("increment", 1), "increment", minimum=1)
        scope = values.get("scope", "generator")
        reset = values.get("reset_frequency", "never")
        if not isinstance(scope, str) or scope not in SCOPES:
            raise invalid("scope")
        if not isinstance(reset, str) or reset not in RESETS:
            raise invalid("reset_frequency")
        width = values.get("padding_width")
        width = 0 if width is None else width
        maximum = values.get("max_code_length")
        if type(width) is not int or width < 0:
            raise invalid("padding_width")
        if type(maximum) is not int or maximum <= 0:
            raise invalid("max_code_length")
        if field_max_length is not None and maximum > field_max_length:
            raise invalid("max_code_length", field_max_length=field_max_length)
        tokens = {part.token for part in parts}
        has_year = bool(tokens & {"YYYY", "YY", "DATE"})
        has_month = bool(tokens & {"MM", "DATE"})
        if reset == "yearly" and not has_year:
            raise invalid("reset_frequency")
        if reset == "monthly" and not (has_year and has_month):
            raise invalid("reset_frequency")
        required = {"ORG_UNIT_CODE"} if scope == "org_unit" else set()
        if globally_unique_number:
            if scope == "parent_aggregation":
                required.add("PARENT_AGGREGATION_NUMBER")
            elif scope == "classification":
                required.update({"CLASSIFICATION_SCHEME_CODE", "CLASSIFICATION_CODE"})
        if not required.issubset(tokens):
            raise invalid("scope", required_placeholders=sorted(required))
        sizes = {"YYYY": 4, "YY": 2, "MM": 2, "DD": 2, "DATE": 8,
                 "SERIAL": max(width, len(serial_text(start)))}
        minimum = sum(len(part.text) if part.token is None else sizes.get(part.token, 1)
                      for part in parts)
        if minimum > maximum:
            raise invalid("max_code_length", minimum_length=minimum)
        return cls(name, values["pattern"], parts, start, increment, scope, reset, width, maximum)

    @property
    def warnings(self) -> tuple[str, ...]:
        return ("two_digit_year_repeats",) if any(part.token == "YY" for part in self.parts) else ()


@dataclass(frozen=True)
class GenerationContext:
    instant: datetime
    working_timezone: str
    parent_aggregation_id: int | None = None
    parent_aggregation_number: str | None = None
    classification_id: int | None = None
    classification_code: str | None = None
    classification_scheme_code: str | None = None
    org_unit_id: int | None = None
    org_unit_code: str | None = None
    role_code: str | None = None

    @property
    def zone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.working_timezone)
        except (ZoneInfoNotFoundError, ValueError, TypeError) as error:
            raise invalid("working_timezone") from error

    @property
    def local_date(self) -> date:
        if not isinstance(self.instant, datetime) or self.instant.utcoffset() is None:
            raise invalid("instant")
        return self.instant.astimezone(self.zone).date()


@dataclass(frozen=True)
class CounterKey:
    scope_kind: str
    scope_id: int
    reset_frequency: str
    period_bucket: date


def counter_key(config: GeneratorConfig, context: GenerationContext) -> CounterKey:
    sources = {"parent_aggregation": context.parent_aggregation_id,
               "classification": context.classification_id, "org_unit": context.org_unit_id}
    scope_id = 0 if config.scope == "generator" else sources.get(config.scope)
    if config.scope != "generator" and (type(scope_id) is not int or scope_id <= 0):
        raise CodeGenerationError("code_generator_missing_context", field=config.scope)
    day = context.local_date
    bucket = (date(1, 1, 1) if config.reset_frequency == "never" else
              date(day.year, 1, 1) if config.reset_frequency == "yearly" else
              date(day.year, day.month, 1))
    return CounterKey(config.scope, scope_id, config.reset_frequency, bucket)


def _context_values(context: GenerationContext) -> dict[str, str | None]:
    day = context.local_date
    return {
        "YYYY": f"{day.year:04d}", "YY": f"{day.year % 100:02d}",
        "MM": f"{day.month:02d}", "DD": f"{day.day:02d}",
        "DATE": f"{day.year:04d}{day.month:02d}{day.day:02d}",
        "PARENT_AGGREGATION_NUMBER": context.parent_aggregation_number,
        "CLASSIFICATION_CODE": context.classification_code,
        "CLASSIFICATION_SCHEME_CODE": context.classification_scheme_code,
        "ORG_UNIT_CODE": context.org_unit_code, "ROLE_CODE": context.role_code,
    }


def code_affixes(
    config: GeneratorConfig, context: GenerationContext, *, serial_length: int = 1,
) -> tuple[str, str]:
    values = _context_values(context)
    prefix: list[str] = []
    suffix: list[str] = []
    destination = prefix
    for part in config.parts:
        if part.token is None:
            destination.append(part.text)
        elif part.token == "SERIAL":
            destination = suffix
        else:
            value = values[part.token]
            if not isinstance(value, str) or is_blank_text(value):
                raise CodeGenerationError("code_generator_missing_context", field=part.token)
            if "\x00" in value:
                raise invalid(part.token)
            destination.append(value)
    length = sum(map(len, prefix)) + sum(map(len, suffix)) + max(serial_length, config.padding_width)
    if length > config.max_code_length:
        raise CodeGenerationError("code_generator_length_exceeded", length=length,
                                  maximum=config.max_code_length)
    return "".join(prefix), "".join(suffix)


def render(config: GeneratorConfig, context: GenerationContext, serial: Any) -> str:
    digits = serial_text(serial)
    # Validate the complete length before allocating padding or joining values.
    prefix, suffix = code_affixes(config, context, serial_length=len(digits))
    return prefix + digits.zfill(config.padding_width) + suffix


def next_serial(
    config: GeneratorConfig, last_serial: Any | None, forward_next: Any | None = None,
) -> Decimal:
    if forward_next is not None:
        result = whole_number(forward_next, "next_number")
        if last_serial is not None and result <= whole_number(last_serial, "serial"):
            raise CodeGenerationError("code_generator_backward_adjustment")
        return result
    return config.start if last_serial is None else add_serial(last_serial, config.increment)


@dataclass(frozen=True)
class PreviewValue:
    value: str
    serial: str
    date: date
    scope_kind: str
    scope_id: int
    period_bucket: date
    reset: bool


def preview_sequence(
    config: GeneratorConfig, context_a: GenerationContext, context_b: GenerationContext,
    scenario: str = "same_scope", *, sample_date: date | None = None,
) -> tuple[PreviewValue, ...]:
    if not isinstance(scenario, str) or scenario not in SCENARIOS:
        raise invalid("scenario")
    base = sample_date or context_a.local_date
    if type(base) is not date:
        raise invalid("sample_date")
    contexts = [context_a] * 5
    dates = [base] * 5
    if scenario in {"different_scopes", "combined"}:
        contexts = [context_a, context_a, context_b, context_a, context_b]
    try:
        if scenario == "year_transition" or (scenario == "combined" and config.reset_frequency != "monthly"):
            dates = [date(base.year, 12, 31)] * 3 + [date(base.year + 1, 1, 1)] * 2
        elif scenario in {"month_transition", "combined"}:
            # Keep this scenario within one year, including a December input.
            month = min(base.month, 11)
            old_month = date(base.year, month, monthrange(base.year, month)[1])
            dates = [old_month] * 3 + [old_month + timedelta(days=1)] * 2
    except (ValueError, OverflowError) as error:
        raise invalid("sample_date") from error
    counters: dict[CounterKey, Decimal] = {}
    previous_period: dict[tuple[str, int], date] = {}
    results = []
    for source, day in zip(contexts, dates, strict=True):
        context = replace(source, working_timezone=context_a.working_timezone,
                          instant=datetime.combine(day, time(12), context_a.zone))
        key = counter_key(config, context)
        value = next_serial(config, counters.get(key))
        scope = (key.scope_kind, key.scope_id)
        reset = scope in previous_period and previous_period[scope] != key.period_bucket
        results.append(PreviewValue(render(config, context, value), serial_text(value), day,
                                    key.scope_kind, key.scope_id, key.period_bucket, reset))
        counters[key] = value
        previous_period[scope] = key.period_bucket
    return tuple(results)
