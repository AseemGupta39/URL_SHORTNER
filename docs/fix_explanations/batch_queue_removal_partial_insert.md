# Design: Batch Queue Removal on Partial Insert

## What Was the Question?

When `batch_create()` uses `ON CONFLICT DO NOTHING`, some rows get skipped silently.
For example: 5 items sent, 4 already exist in the DB, only 1 actually gets inserted.
The question is — does the queue removal logic break in this case?

## Why This Matters

The batch worker uses a peek-then-remove pattern:
1. Peek at N items from the queue (does NOT remove them yet)
2. Insert to DB
3. Remove those N items from the queue only after DB succeeds

If the removal logic removes the wrong number of items, either:
- Items get stuck in the queue forever (if too few removed)
- Items get lost before DB insert (if removed too early)

## What the Code Actually Does

`batch_worker.py`, line 168:

```python
items_to_remove = len(items)  # Total items peeked
await queue.remove_first(items_to_remove)
```

It removes `len(items)` — ALL peeked items — not `inserted_count`.

`inserted_count` is only used for logging and metrics. It does not control queue removal.

## Why Removing All Items Is Correct

After `ON CONFLICT DO NOTHING` completes without error, every item in the batch is accounted for in the DB:
- Newly inserted rows → just written
- Skipped rows → already existed from a previous run

There is no item that is "missing" from the DB. So it is safe to remove all of them from the queue.

**Scenario walkthrough:**

| Scenario | Items peeked | inserted_count | Items removed from queue | Correct? |
|---|---|---|---|---|
| Clean run | 5 | 5 | 5 | Yes |
| Full reprocess (crash recovery) | 5 | 0 | 5 | Yes — all already in DB |
| Partial duplicates | 5 | 1 | 5 | Yes — 1 new + 4 already in DB |

## What Would Break

If the code removed only `inserted_count` items instead of `len(items)`:

- Partial duplicate case: 1 removed, 4 stuck in queue
- Next run: those 4 conflict again, `inserted_count = 0`, 0 removed
- They stay in the queue forever — infinite reprocess loop

This would be wrong.

## Known Limitations

On a full reprocess run, the log line shows:

```
"Batch INSERT successful" inserted=0
```

`inserted=0` looks alarming but is correct — all rows already existed, nothing was lost.
A future improvement is to add a `skipped_duplicates` field to this log line so ops can distinguish "nothing to insert" from "something went wrong".
