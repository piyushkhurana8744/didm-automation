"""Lead rows from the Leads sheet, and the rules for who can be called next.

These rules match the Queue sheet formula that Make uses today:
- Call column says YES and the phone is filled in
- the number never said do-not-call (on any row)
- either never called, or the last call did not reach a real conversation
  (not connected, no conversation, voicemail), with fewer than MAX_ATTEMPTS
  attempts and at least RETRY_GAP_MINUTES since the last call
- never-called leads go first
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

# 0-based column positions in the Leads sheet (A = 0)
COL = {
    "name": 0, "phone": 1, "course": 2, "source": 3, "city": 4, "call": 5,
    "status": 6, "called_at": 7, "attempt_id": 8, "outcome": 9, "program": 10,
    "mode": 11, "centre": 12, "goal": 13, "callback": 14, "summary": 15,
    "duration": 16, "row": 17, "note": 18, "attempts": 19, "email": 20, "followup": 21,
}
RETRY_OUTCOMES = {"no_conversation", "voicemail_left"}
BLOCK_OUTCOMES = ("do_not_call", "wrong_number")


def digits_only(phone: str) -> str:
    return "".join(ch for ch in str(phone or "") if ch.isdigit())


def to_e164(phone: str) -> str | None:
    """Indian numbers: 10 digits get +91. 11 to 12 digits are kept (with leading 0 dropped)."""
    d = digits_only(phone)
    if len(d) == 11 and d.startswith("0"):
        d = d[1:]
    if len(d) == 10:
        return "+91" + d
    if len(d) == 12 and d.startswith("91"):
        return "+" + d
    return None


@dataclass
class Lead:
    row: int
    name: str = ""
    phone: str = ""
    course: str = ""
    source: str = ""
    city: str = ""
    call: str = ""
    status: str = ""
    called_at: str = ""
    outcome: str = ""
    note: str = ""
    attempts: int = 0
    followup: str = ""

    @classmethod
    def from_row(cls, row_number: int, values: list) -> "Lead":
        def g(key):
            i = COL[key]
            return str(values[i]).strip() if i < len(values) and values[i] is not None else ""
        try:
            attempts = int(float(g("attempts") or 0))
        except ValueError:
            attempts = 0
        return cls(row=row_number, name=g("name"), phone=g("phone"), course=g("course"),
                   source=g("source"), city=g("city"), call=g("call"), status=g("status"),
                   called_at=g("called_at"), outcome=g("outcome"), note=g("note"),
                   attempts=attempts, followup=g("followup"))


def parse_called_at(text: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(text.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


def blocked_numbers(leads: list[Lead]) -> set[str]:
    return {to_e164(l.phone) for l in leads
            if l.outcome.lower().startswith(BLOCK_OUTCOMES) and to_e164(l.phone)}


def is_eligible(lead: Lead, now_local: datetime, blocked: set[str],
                max_attempts: int, retry_gap: timedelta) -> bool:
    if lead.call.upper() != "YES" or not lead.phone:
        return False
    e164 = to_e164(lead.phone)
    if not e164 or e164 in blocked:
        return False
    if lead.status == "":
        return True
    needs_retry = ((lead.status.startswith("Done:") and lead.status != "Done: connected")
                   or lead.outcome in RETRY_OUTCOMES)
    if not needs_retry or lead.attempts >= max_attempts:
        return False
    last = parse_called_at(lead.called_at)
    return last is None or now_local - last >= retry_gap


def pick_next(leads: list[Lead], now_local: datetime, max_attempts: int, retry_gap: timedelta,
              exclude_rows: set[int] = frozenset(), exclude_phones: set[str] = frozenset(),
              min_row: int | None = None, max_row: int | None = None) -> Lead | None:
    blocked = blocked_numbers(leads)
    candidates = [l for l in leads
                  if l.row not in exclude_rows
                  and to_e164(l.phone) not in exclude_phones
                  and (min_row is None or l.row >= min_row)
                  and (max_row is None or l.row <= max_row)
                  and is_eligible(l, now_local, blocked, max_attempts, retry_gap)]
    candidates.sort(key=lambda l: (l.status != "", l.row))
    return candidates[0] if candidates else None
