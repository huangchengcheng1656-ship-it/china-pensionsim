"""Map development-round directory names in retained fixtures to the public layout.

Some retained research fixtures name the original development directories
(``continuation_rNN``). This module rewrites those names in loaded JSON objects
so regression tests compare the corresponding public paths. It leaves numbers
and hashes unchanged. Release baselines regenerated after model fixes are
identified in the changelog and the relevant regression-test documentation.
"""
import re

LEGACY_TO_PUBLIC = {
    "continuation_r04": "extensions/mortality_wpp",
    "continuation_r51": "extensions/contribution_frontier",
    "continuation_r52": "extensions/monthly_bridge",
    "continuation_r53": "extensions/survival_valuation",
    "continuation_r95": "extensions/fixtures_routes",
    "continuation_r96": "extensions/fixtures_timing",
    "continuation_r97": "extensions/fixtures_installments",
    "continuation_r98": "extensions/continuation_valuation_base",
    "continuation_r99": "extensions/continuation_valuation",
    "continuation_r100": "extensions/fixtures_portfolio",
    "continuation_r103": "extensions/budget_solver",
}

_PATTERN = re.compile(
    r"\b(" + "|".join(sorted(LEGACY_TO_PUBLIC, key=len, reverse=True)) + r")(?=[/.\\])"
)


def _rewrite(text):
    def repl(match):
        public = LEGACY_TO_PUBLIC[match.group(1)]
        following = match.string[match.end()]
        return public if following in "/\\" else public.replace("/", ".")
    return _PATTERN.sub(repl, text)


def to_public(obj):
    """Return a copy of a JSON-like object with legacy directory names rewritten."""
    if isinstance(obj, dict):
        return {_rewrite(k): to_public(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_public(v) for v in obj]
    if isinstance(obj, str):
        return _rewrite(obj)
    return obj
