from __future__ import annotations
import asyncio
from typing import Dict, Any

async def run(cb_out: Dict[str, Any], vc_out: Dict[str, Any]) -> Dict[str, Any]:
    """
    Detect implied claims.
    """
    await asyncio.sleep(0.5)
    return {
        "implied_claims": []
    }
