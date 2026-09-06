from __future__ import annotations
import asyncio
from typing import Dict, Any

async def run(cb_out: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate scene descriptions from context units.
    """
    await asyncio.sleep(0.5)
    return {
        "visual_descriptions": [
            {
                "frame_id": "kf_01",
                "description": "Flooded street with partially submerged vehicles, heavy rainfall."
            }
        ],
        "visual_context": "Flooded street, partially submerged vehicles, heavy rainfall."
    }
