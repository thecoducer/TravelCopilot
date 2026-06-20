"""Real FX conversion tool stub. (H)"""

from __future__ import annotations

from typing import Any


class CurrencyConvertTool:
    name = "currency_convert"
    description = "Real currency conversion via FX rate provider (live rates, cached 12h)."

    async def run(self, **kwargs: object) -> dict[str, Any]:
        raise NotImplementedError("CurrencyConvertTool requires FX_API_KEY — implement in Phase 5.")
