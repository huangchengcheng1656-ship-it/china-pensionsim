"""Map development-round directory names in sealed fixtures to the public layout.

The synthetic fixtures under ``extensions/`` are kept byte-identical to the
sealed R103 research release, so their recorded hashes stay valid. Those files
still name the original development directories (``continuation_rNN``). The
public release moved each directory to a descriptive name; this module rewrites
the old names inside a loaded JSON object so that regression tests compare like
with like. Numbers and hashes are never changed.
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
