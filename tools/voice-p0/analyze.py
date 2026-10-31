#!/usr/bin/env python3
"""Summarize successful experiments; retain sample counts and timing definitions."""
import json
import hashlib
import math
from pathlib import Path
import re
import statistics


def distribution(values):
    values = sorted(values)
    if not values:
        return None
    return {'n': len(values), 'median': statistics.median(values),
            'p95_nearest_rank': values[math.ceil(len(values) * .95) - 1],
            'min': values[0], 'max': values[-1]}


def summarize(path):
    events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not any(x['event'] == 'complete' and not x['cancelled'] for x in events):
        return {'id': path.stem, 'success': False,
                'errors': [x for x in events if x['event'] == 'failure']}
    config = next(x for x in events if x['event'] == 'config')
    load = next(x for x in events if x['event'] == 'load_start')
    memories = [x for x in events if x['event'] == 'memory']
    decoded = [x for x in events if x['event'] == 'decoded']
    starts = [x for x in events if x['event'] in ['trial_start', 'capture_start']]
    firsts, gaps, ages, waits, terminal_gaps, trials, mic_stops = [], [], [], [], [], [], []
    for start in starts:
        trial = start['trial']
        displays = [x for x in events if x['event'] == 'display' and x['trial'] == trial]
        partials = [x for x in displays if x['kind'] == 'partial' and x['ok'] and x['text']]
        if partials:
            firsts.append(partials[0]['time_ms'] - start['start_ms'])
        changes = []
        previous = ''
        for display in partials:
            if display['time_ms'] <= start['release_ms'] and display['text'] != previous:
                changes.append(display)
                previous = display['text']
        gaps += [b['time_ms'] - a['time_ms'] for a, b in zip(changes, changes[1:])]
        terminal_gap = max(0, start['release_ms'] - (changes[-1]['time_ms'] if changes else start['start_ms']))
        terminal_gaps.append(terminal_gap)
        ages += [x['age_ms'] for x in partials]
        end = next((x for x in events if x['event'] == 'trial_end' and x['trial'] == trial), None)
        if end:
            waits.append(end['final_wait_ms'])
        trials.append({'trial': trial, 'visible_changes_while_held': len(changes),
            'last_held_text': changes[-1]['text'] if changes else '',
            'terminal_stale_ms': terminal_gap,
            'final_text': next((x['text'] for x in reversed(displays) if x['kind'] == 'final'), '')})
    mic_stops = [x['after_release_ms'] for x in events if x['event'] == 'capture_stop']
    cat = path.with_name(path.stem + '-logcat.txt')
    warnings = [line.strip() for line in cat.read_text(errors='replace').splitlines()
                if 'Truncating audio' in line or 'Result is truncated' in line or 'model limit' in line] if cat.exists() else []
    metadata_path = path.with_name(path.stem + '-device.json')
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    dump = metadata.get('meminfo_after', '')
    total_pss = re.search(r'TOTAL PSS:\s*(\d+)', dump)
    realtime = re.search(r'Realtime:\s*(\d+)', dump)
    released = next((x['time_ms'] for x in reversed(events) if x['event'] == 'released'), None)
    return {'id': path.stem, 'success': True, 'config': config, 'threads': load['threads'],
        'memory_mode': load.get('memory_mode', 'default'),
        'load_ms': [x['load_ms'] for x in events if x['event'] == 'loaded'],
        'decode_ms': distribution([x['decode_ms'] for x in decoded]),
        'decoded_empty_count': sum(not x['text'] for x in decoded),
        'decoded_literal_language_count': sum(x['text'].strip() == 'language' for x in decoded),
        'decoded_chars': distribution([len(x['text']) for x in decoded]),
        'decode_text_sha256': sorted({hashlib.sha256(x['text'].encode()).hexdigest() for x in decoded}),
        'first_nonempty_from_audio_start_ms': distribution(firsts),
        'held_changed_update_gap_ms': distribution(gaps), 'partial_audio_age_ms': distribution(ages),
        'final_wait_ms': distribution(waits), 'last_update_to_release_ms': distribution(terminal_gaps),
        'capture_stop_after_deadline_ms': distribution(mic_stops),
        'capture_trials': [{k: v for k, v in x.items() if k in ['trial', 'captured_seconds', 'rms']}
                           for x in events if x['event'] == 'trial_end' and 'rms' in x],
        'peak_pss_mib': max(x['pss_kib'] for x in memories) / 1024,
        'baseline_pss_mib': memories[0]['pss_kib'] / 1024,
        'peak_rss_mib': max(x['hwm_kib'] for x in memories) / 1024,
        'after_release_pss_mib': next((x['pss_kib'] / 1024 for x in reversed(memories)
            if x['phase'] == 'after_gc'), None),
        'idle_pss_mib': int(total_pss[1]) / 1024 if total_pss else None,
        'idle_sample_after_release_ms': float(realtime[1]) - released if realtime and released else None,
        'peak_thermal_status': max(x['thermal_status'] for x in memories),
        'trial_end_pss_mib': [x['pss_kib'] / 1024 for x in memories if x['phase'] == 'trial_end'],
        'display_failures': sum(x['event'] == 'display' and not x['ok'] for x in events),
        'composing_observed_in_host': any(x['event'] == 'host_text' and x['composing_start'] >= 0 for x in events),
        'context_warnings': warnings, 'trials': trials}


def main():
    results = Path(__file__).parent / 'results'
    data = [summarize(p) for p in sorted(results.glob('*.jsonl'))]
    (results / 'summary.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    for item in data:
        print(item['id'], json.dumps({k: item[k] for k in ['success', 'decode_ms',
            'first_nonempty_from_audio_start_ms', 'held_changed_update_gap_ms', 'final_wait_ms',
            'peak_pss_mib', 'display_failures'] if k in item}, ensure_ascii=False))


if __name__ == '__main__':
    main()
