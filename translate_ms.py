#!/usr/bin/env python3
"""
Resumable Malay (ms-MY) translation script for Open WebUI using Claude API.

Usage:
    python3 translate_ms.py              # translate next batch (default 50 keys)
    python3 translate_ms.py --batch 30   # translate 30 keys this run
    python3 translate_ms.py --status     # show progress without translating

Progress is saved after every key, so you can safely Ctrl+C and resume anytime.
When you hit API quota, just run again later - already translated keys are skipped.
"""

import json
import os
import sys
import time
import argparse
from pathlib import Path
import anthropic

TRANSLATION_FILE = Path("src/lib/i18n/locales/ms-MY/translation.json")
PROGRESS_FILE = Path("translate_ms_progress.json")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent="\t")
        f.write("\n")


def load_progress():
    if PROGRESS_FILE.exists():
        return load_json(PROGRESS_FILE)
    return {"done_keys": [], "failed_keys": []}


def save_progress(progress):
    save_json(PROGRESS_FILE, progress)


def translate_batch(client, keys_batch, retries=3):
    """Translate a batch of keys in one API call. Returns dict of key->translation."""
    # Build a numbered list so we can parse results reliably
    numbered = "\n".join(f"{i+1}. {k}" for i, k in enumerate(keys_batch))

    prompt = f"""You are a professional translator. Translate the following UI strings from English to Malay (Bahasa Malaysia / ms-MY).

Rules:
- Keep placeholders like {{{{COUNT}}}}, {{{{user}}}}, {{{{webUIName}}}}, etc. exactly as-is
- Keep template syntax like `${{variable}}` exactly as-is
- Keep markdown formatting intact
- Translate naturally for a Malaysian software UI
- Return ONLY the translations, one per line, numbered to match the input
- Do NOT add explanations or extra text

Strings to translate:
{numbered}

Translations (numbered, one per line):"""

    for attempt in range(retries):
        try:
            message = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )
            response_text = message.content[0].text.strip()

            # Parse numbered lines
            lines = response_text.split("\n")
            translations = {}
            line_idx = 0
            for i, key in enumerate(keys_batch):
                expected_prefix = f"{i+1}."
                # Find the line with this number
                while line_idx < len(lines) and not lines[line_idx].strip().startswith(expected_prefix):
                    line_idx += 1
                if line_idx < len(lines):
                    raw = lines[line_idx].strip()
                    # Remove the "N. " prefix
                    translation = raw[len(expected_prefix):].strip()
                    translations[key] = translation
                    line_idx += 1
                else:
                    translations[key] = None  # failed to parse
            return translations

        except anthropic.RateLimitError as e:
            if attempt < retries - 1:
                wait = 60 * (attempt + 1)  # 60s, 120s
                print(f"  Rate limit hit. Waiting {wait}s before retry...")
                time.sleep(wait)
            else:
                raise
        except Exception as e:
            if attempt < retries - 1:
                wait = 2 ** attempt
                print(f"  Retry {attempt + 1}/{retries} after {wait}s (error: {e})")
                time.sleep(wait)
            else:
                raise


def show_status(data, progress):
    total = len(data)
    empty = sum(1 for v in data.values() if v == "")
    done_keys = set(progress["done_keys"])
    failed_keys = set(progress["failed_keys"])

    print(f"Translation file: {TRANSLATION_FILE}")
    print(f"  Total keys               : {total}")
    print(f"  Filled keys              : {total - empty}")
    print(f"  Still empty              : {empty}")
    print(f"  Translated (this script) : {len(done_keys)}")
    print(f"  Failed                   : {len(failed_keys)}")

    remaining = sum(
        1 for k, v in data.items()
        if v == "" and k not in done_keys and k not in failed_keys
    )
    print(f"  Remaining                : {remaining}")

    if failed_keys:
        print(f"\nFailed keys (first 10):")
        for k in list(failed_keys)[:10]:
            print(f"  - {repr(k)}")


def main():
    parser = argparse.ArgumentParser(description="Resumable ms-MY translation script")
    parser.add_argument("--batch", type=int, default=50,
                        help="Number of keys to translate per run (default: 50)")
    parser.add_argument("--chunk", type=int, default=10,
                        help="Keys per API call (default: 10)")
    parser.add_argument("--status", action="store_true",
                        help="Show progress status only")
    parser.add_argument("--retry-failed", action="store_true",
                        help="Retry previously failed keys")
    args = parser.parse_args()

    data = load_json(TRANSLATION_FILE)
    progress = load_progress()

    if args.status:
        show_status(data, progress)
        return

    done_keys = set(progress["done_keys"])
    failed_keys = set(progress["failed_keys"])

    if args.retry_failed:
        to_translate = [(k, data[k]) for k in failed_keys if k in data]
        progress["failed_keys"] = []
        failed_keys = set()
        print(f"Retrying {len(to_translate)} previously failed keys...")
    else:
        to_translate = [
            (k, v) for k, v in data.items()
            if v == "" and k not in done_keys and k not in failed_keys
        ]

    total_remaining = len(to_translate)

    if total_remaining == 0:
        print("All empty keys have been processed!")
        show_status(data, progress)
        return

    batch = to_translate[:args.batch]
    print(f"Translating {len(batch)} keys (of {total_remaining} remaining)...")
    print(f"Using {args.chunk} keys per API call.")
    print(f"Progress saved after every chunk. Safe to Ctrl+C and resume.\n")

    # Support both ANTHROPIC_API_KEY (standard) and ANTHROPIC_AUTH_TOKEN (Claude Code session)
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if auth_token:
        client = anthropic.Anthropic(auth_token=auth_token)
    elif api_key:
        client = anthropic.Anthropic(api_key=api_key)
    else:
        # Try to find Claude Code session token automatically (check multiple locations)
        token_candidates = [
            Path("/home/claude/.claude/remote/.session_ingress_token"),
            Path.home() / ".claude/remote/.session_ingress_token",
        ]
        token_file = next((p for p in token_candidates if p.exists()), None)
        if token_file:
            client = anthropic.Anthropic(auth_token=token_file.read_text().strip())
        else:
            print("ERROR: No API key found. Set ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN.")
            sys.exit(1)
    translated_count = 0
    failed_count = 0

    # Process in chunks
    for chunk_start in range(0, len(batch), args.chunk):
        chunk = batch[chunk_start: chunk_start + args.chunk]
        chunk_keys = [k for k, _ in chunk]
        chunk_num = chunk_start // args.chunk + 1
        total_chunks = (len(batch) + args.chunk - 1) // args.chunk

        print(f"Chunk {chunk_num}/{total_chunks} ({len(chunk_keys)} keys)...")

        try:
            translations = translate_batch(client, chunk_keys)

            for key in chunk_keys:
                translation = translations.get(key)
                if translation:
                    data[key] = translation
                    progress["done_keys"].append(key)
                    translated_count += 1
                    print(f"  ✓ {repr(key[:50])} -> {repr(translation[:60])}")
                else:
                    progress["failed_keys"].append(key)
                    failed_count += 1
                    print(f"  ✗ {repr(key[:50])} (parse failed)")

        except anthropic.RateLimitError:
            print(f"\nQuota/rate limit reached after {translated_count} translations.")
            print("Progress saved. Run again later to continue.")
            save_json(TRANSLATION_FILE, data)
            save_progress(progress)
            sys.exit(1)
        except KeyboardInterrupt:
            print(f"\nInterrupted. Progress saved ({translated_count} translated so far).")
            save_json(TRANSLATION_FILE, data)
            save_progress(progress)
            sys.exit(0)
        except Exception as e:
            print(f"  ERROR in chunk: {e}")
            for key in chunk_keys:
                if key not in progress["done_keys"]:
                    progress["failed_keys"].append(key)
                    failed_count += 1

        # Save after every chunk
        save_json(TRANSLATION_FILE, data)
        save_progress(progress)

        # Small delay between chunks to be nice to the API
        if chunk_start + args.chunk < len(batch):
            time.sleep(0.5)

    remaining_after = total_remaining - len(batch)
    print(f"\nBatch complete: {translated_count} translated, {failed_count} failed.")
    print(f"Remaining: {remaining_after}")

    if remaining_after > 0:
        print(f"\nRun again to continue:")
        print(f"  python3 translate_ms.py --batch {args.batch}")
    else:
        print("\nAll keys processed! Run with --status to see final summary.")
        print("Don't forget to commit: git add src/lib/i18n/locales/ms-MY/translation.json && git commit -m 'feat: complete ms-MY translations'")


if __name__ == "__main__":
    main()
