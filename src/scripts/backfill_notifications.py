from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path so this script can be run directly
# Add project root (two parents up from src/scripts)
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import argparse
import asyncio
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Iterable, List, Tuple

from src.database.crud.keys import get_all_keys
from src.database.crud.notifications import bulk_upsert_schedule, get_rules
from src.database.models import NotificationType


def parse_dt(value: str | None, default_end: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        # try date-only form YYYY-MM-DD
        try:
            dt = datetime.fromisoformat(value + "T00:00:00")
        except Exception:
            raise
    if dt.tzinfo is None:
        # normalize to UTC
        if default_end:
            dt = dt.replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
        else:
            dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def calc_planned_at(key_finish: datetime, rule) -> datetime:
    # rule.offset_days and offset_hours may be None
    offset = timedelta(days=rule.offset_days or 0, hours=rule.offset_hours or 0)
    planned = key_finish.astimezone(timezone.utc) + offset
    return planned


async def build_entries_for_type(
    event_type: NotificationType,
    from_dt: datetime | None,
    to_dt: datetime | None,
    strict: bool = False,
) -> List[Tuple[int, int, datetime, str]]:
    # load rules and keys
    rules = await get_rules(event_type, active_only=True)
    if not rules:
        print("No active rules for type", event_type)
        return []

    keys = await get_all_keys()
    # group keys by user for strict checks
    keys_by_user = defaultdict(list)
    for k in keys:
        keys_by_user[k.user_id].append(k)

    entries: List[Tuple[int, int, datetime, str]] = []

    # filter keys by event type
    def key_matches(k) -> bool:
        if event_type in (NotificationType.trial_expired, NotificationType.trial_expiring_soon):
            return bool(getattr(k, "is_test", False))
        if event_type in (NotificationType.paid_expired, NotificationType.paid_expiring_soon):
            return not bool(getattr(k, "is_test", False))
        # for other events include all keys
        return True

    for k in keys:
        if not key_matches(k):
            continue
        finish = k.finish
        if finish is None:
            continue
        if finish.tzinfo is None:
            finish = finish.replace(tzinfo=timezone.utc)
        else:
            finish = finish.astimezone(timezone.utc)

        if from_dt and finish < from_dt:
            continue
        if to_dt and finish > to_dt:
            continue

        # strict: exclude if user had paid (non-test) key active at planned_at
        for rule in rules:
            planned_at = calc_planned_at(finish, rule)
            if strict and event_type in (NotificationType.trial_expired, NotificationType.trial_expiring_soon):
                # check for any paid key for this user that overlaps planned_at or is active at that time
                user_keys = keys_by_user.get(k.user_id, [])
                has_paid_active = any((not getattr(uk, "is_test", False)) and getattr(uk, "finish", None) and (uk.finish.astimezone(timezone.utc) >= planned_at) for uk in user_keys)
                if has_paid_active:
                    # skip this rule for this key
                    continue

            dedup_key = f"{k.user_id}:{rule.id}:{int(planned_at.timestamp())}"
            entries.append((k.user_id, rule.id, planned_at, dedup_key))

    return entries


async def run_backfill(args):
    event_type = NotificationType(args.type)
    from_dt = parse_dt(args.from_dt) if args.from_dt else None
    to_dt = parse_dt(args.to_dt, default_end=True) if args.to_dt else None

    print("Loading entries for event type", event_type)
    entries = await build_entries_for_type(event_type, from_dt, to_dt, strict=args.strict)
    print(f"Collected {len(entries)} entries")

    if args.dry_run:
        print("Dry run - showing first 20 entries")
        for e in entries[:20]:
            print(e)
        return

    # bulk insert in batches
    batch = []
    written = 0
    for i, entry in enumerate(entries, 1):
        batch.append(entry)
        if len(batch) >= args.batch_size:
            await bulk_upsert_schedule(batch)
            written += len(batch)
            print(f"Inserted {written} entries so far...")
            batch = []
    if batch:
        await bulk_upsert_schedule(batch)
        written += len(batch)

    print(f"Backfill finished. Total inserted: {written}")


def main():
    parser = argparse.ArgumentParser(description="Backfill notification schedules from keys/events")
    parser.add_argument("--type", choices=[t.value for t in NotificationType], default=NotificationType.trial_expired.value, help="Notification event type")
    parser.add_argument("--from", dest="from_dt", help="Start ISO datetime (inclusive) e.g. 2025-01-01T00:00:00 or 2025-01-01")
    parser.add_argument("--to", dest="to_dt", help="End ISO datetime (inclusive) e.g. 2025-01-31T23:59:59 or 2025-01-31")
    parser.add_argument("--dry-run", action="store_true", help="Do not write to DB, just show summary")
    parser.add_argument("--batch-size", type=int, default=500, help="Batch size for DB upsert")
    parser.add_argument("--strict", action="store_true", help="Strict mode: exclude users who had paid key active at planned_at (only applies to trial_expired)")

    args = parser.parse_args()
    asyncio.run(run_backfill(args))


if __name__ == "__main__":
    main()
