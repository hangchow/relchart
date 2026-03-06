from __future__ import annotations

from dataclasses import dataclass
import re

MAX_SYMBOLS = 5
YF_EXACT_CALENDAR_HINTS = {
    "GC=F": "XNYS",
    "SI=F": "XNYS",
}


@dataclass(frozen=True)
class StockSymbol:
    raw: str
    market: str
    code: str
    canonical: str
    storage_key: str
    yahoo_symbol: str
    calendar_name: str


def parse_symbol(raw: str) -> StockSymbol:
    text = raw.strip().upper()
    if not text:
        raise ValueError("empty stock code")
    if "." not in text:
        raise ValueError(f"invalid stock code: {raw}")

    market, code = text.split(".", 1)
    if market not in {"US", "HK", "YF"}:
        raise ValueError(f"unsupported market prefix in stock code: {raw}")

    if market == "US":
        normalized_code = code.replace("-", ".")
        if not normalized_code:
            raise ValueError(f"invalid US stock code: {raw}")
        canonical = f"US.{normalized_code}"
        yahoo_symbol = normalized_code.replace(".", "-")
        calendar_name = "XNYS"
        return StockSymbol(
            raw=raw,
            market=market,
            code=normalized_code,
            canonical=canonical,
            storage_key=canonical.lower(),
            yahoo_symbol=yahoo_symbol,
            calendar_name=calendar_name,
        )

    if market == "YF":
        yahoo_symbol = code.strip().upper()
        if not yahoo_symbol:
            raise ValueError(f"invalid Yahoo Finance symbol: {raw}")
        canonical = f"YF.{yahoo_symbol}"
        return StockSymbol(
            raw=raw,
            market=market,
            code=yahoo_symbol,
            canonical=canonical,
            storage_key=f"yf.{_storage_slug(yahoo_symbol)}",
            yahoo_symbol=yahoo_symbol,
            calendar_name=_calendar_name_for_yf_symbol(yahoo_symbol),
        )

    digits = "".join(ch for ch in code if ch.isdigit())
    if not digits:
        raise ValueError(f"invalid HK stock code: {raw}")
    canonical_code = digits.zfill(5)
    yahoo_code = digits.lstrip("0").zfill(4)
    canonical = f"HK.{canonical_code}"
    return StockSymbol(
        raw=raw,
        market=market,
        code=canonical_code,
        canonical=canonical,
        storage_key=canonical.lower(),
        yahoo_symbol=f"{yahoo_code}.HK",
        calendar_name="XHKG",
    )


def parse_symbols(raw: str) -> list[StockSymbol]:
    symbols = [parse_symbol(part) for part in raw.split(",") if part.strip()]
    if not symbols:
        raise ValueError("no valid stock codes provided")
    if len(symbols) > MAX_SYMBOLS:
        raise ValueError(f"at most {MAX_SYMBOLS} stocks are supported")
    return symbols


def _calendar_name_for_yf_symbol(yahoo_symbol: str) -> str:
    if yahoo_symbol in YF_EXACT_CALENDAR_HINTS:
        return YF_EXACT_CALENDAR_HINTS[yahoo_symbol]
    if yahoo_symbol.endswith("=X"):
        return "24/5"
    if yahoo_symbol.endswith("-USD"):
        return "24/7"
    if yahoo_symbol.endswith("=F"):
        return "XNYS"
    if yahoo_symbol.startswith("^"):
        return "XNYS"
    return "24/5"


def _storage_slug(value: str) -> str:
    slug = value.lower()
    slug = slug.replace("^", "idx_")
    slug = slug.replace("=", "_eq_")
    slug = slug.replace("-", "_dash_")
    slug = slug.replace(".", "_dot_")
    slug = slug.replace("/", "_slash_")
    slug = re.sub(r"[^a-z0-9_]+", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "symbol"
