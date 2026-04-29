"""Import CSV/JSON archive exports into the local data store used by `engine.memory`.

Reads `archive/transcripts_rows.csv`, `archive/conversation_logs_rows.csv`,
and `archive/user_profiles_rows.csv` (if present) and writes them into the
local `data/` fallback used by the app. This makes old conversations available
to Samantha via the existing memory helpers.

Run as a script or import `import_archives()` from other tooling.
"""
import csv
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

from engine import memory


ARCHIVE_DIR = Path("archive")


def _parse_maybe_json(s: Optional[str]):
    if not s:
        return None
    s = s.strip()
    try:
        # Some CSV exports include JSON-encoded strings (with doubled quotes)
        return json.loads(s)
    except Exception:
        # Fallback: try to fix double-double-quotes
        try:
            return json.loads(s.replace('""', '"'))
        except Exception:
            return s


def import_transcripts(csv_path: Path) -> int:
    if not csv_path.exists():
        return 0
    count = 0
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            session_id = row.get('session_id') or row.get('id')
            user_name = row.get('user_name') or row.get('name') or 'unknown'
            messages_raw = row.get('messages') or row.get('transcript') or ''
            messages = _parse_maybe_json(messages_raw)
            # Normalize messages to list of dicts
            if isinstance(messages, str):
                try:
                    messages = json.loads(messages)
                except Exception:
                    messages = [{"role": "user", "content": messages}]
            if not isinstance(messages, list):
                messages = [messages]

            memory.save_full_transcript(None, user_name, session_id, messages)
            count += 1
    return count


def import_conversation_logs(csv_path: Path) -> int:
    if not csv_path.exists():
        return 0
    count = 0
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            user_name = row.get('user_name') or row.get('name') or 'unknown'
            session_id = row.get('session_id')
            summary = row.get('summary') or ''
            memory.save_session_log(None, user_name, session_id or '', summary or '')
            count += 1
    return count


def import_user_profiles(csv_path: Path) -> int:
    if not csv_path.exists():
        return 0
    count = 0
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get('name') or row.get('user_name')
            if not name:
                continue
            # Build a profile dict from CSV columns where possible
            profile = {}
            for key in ['occupation','location','age','relationship_status','notes','nicknames','last_seen']:
                v = row.get(key)
                if v:
                    profile[key] = v
            # Attempt to parse JSON fields stored as strings
            for arr_field in ['insecurities','soft_spots','boasts']:
                raw = row.get(arr_field)
                if raw:
                    parsed = _parse_maybe_json(raw)
                    if isinstance(parsed, list):
                        profile[arr_field] = parsed
            # deep_profile may be a JSON string
            deep = row.get('deep_profile')
            if deep:
                try:
                    profile['deep_profile'] = json.loads(deep)
                except Exception:
                    profile['deep_profile'] = deep

            # Persist via memory.update_profile which will write to local fallback
            memory.update_profile(None, name, profile)
            count += 1
    return count


def import_archives(archive_dir: Path = ARCHIVE_DIR) -> dict:
    archive_dir = Path(archive_dir)
    results = {}
    transcripts_csv = archive_dir / 'transcripts_rows.csv'
    conv_csv = archive_dir / 'conversation_logs_rows.csv'
    profiles_csv = archive_dir / 'user_profiles_rows.csv'

    results['transcripts_imported'] = import_transcripts(transcripts_csv)
    results['logs_imported'] = import_conversation_logs(conv_csv)
    results['profiles_imported'] = import_user_profiles(profiles_csv)

    return results


if __name__ == '__main__':
    print('Importing archive to local data store...')
    res = import_archives()
    print('Done:', res)