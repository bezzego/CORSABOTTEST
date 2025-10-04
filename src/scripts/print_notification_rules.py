from __future__ import annotations

import sys
from pathlib import Path
import asyncio

# ensure project root on sys.path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.database.crud.notifications import get_rules
from src.database.models import NotificationType


async def main():
    for t in NotificationType:
        rules = await get_rules(t, active_only=True)
        print(f"Type: {t} -> {len(rules)} active rules")
        for r in rules:
            print(f"  #{r.id} name={r.name} offset_days={r.offset_days} offset_hours={r.offset_hours} repeat_days={r.repeat_every_days} repeat_hours={r.repeat_every_hours}")


if __name__ == "__main__":
    asyncio.run(main())
