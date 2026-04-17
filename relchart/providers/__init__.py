from .sina import SinaProvider
from .yahoo import YahooProvider


def create_provider(name: str):
    normalized = name.strip().lower()
    if normalized == "sina":
        return SinaProvider()
    if normalized == "yahoo":
        return YahooProvider()
    raise ValueError(f"unsupported provider: {name}")


__all__ = ["SinaProvider", "YahooProvider", "create_provider"]
