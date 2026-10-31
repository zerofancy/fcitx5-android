#!/usr/bin/env python3
"""P0 window metrics plus reference error rates; never infer quality from throughput."""
import collections
import hashlib
import json
from pathlib import Path
import re
from analyze import summarize, distribution

HERE = Path(__file__).resolve().parent


def units(text, language):
    if language == 'zh':
        return [c.lower() for c in text if c.isalnum()]
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", text.lower().replace('’', "'").replace('‘', "'"))


def error_rate(reference, hypothesis):
    # Each cell stores total edits, substitutions, deletions, insertions.
    row = [(i, 0, 0, i) for i in range(len(hypothesis) + 1)]
    for i, a in enumerate(reference):
        next_row = [(i + 1, 0, i + 1, 0)]
        for j, b in enumerate(hypothesis):
            if a == b:
                next_row.append(row[j])
            else:
                sub, delete, insert = row[j], row[j + 1], next_row[j]
                next_row.append(min((sub[0]+1, sub[1]+1, sub[2], sub[3]),
                    (delete[0]+1, delete[1], delete[2]+1, delete[3]),
                    (insert[0]+1, insert[1], insert[2], insert[3]+1), key=lambda x: x[0]))
        row = next_row
    cost, sub, delete, insert = row[-1]
    return {'rate': cost / max(1, len(reference)), 'reference_units': len(reference),
            'hypothesis_units': len(hypothesis), 'substitutions': sub, 'deletions': delete, 'insertions': insert}


def main():
    inputs = json.loads((Path.home() / '.cache/fcitx5-voice-p0/window-inputs-private.json').read_text())
    fixtures = {x['file']: x for x in inputs}
    output = []
    for path in sorted((HERE / 'results').glob('win-*.jsonl')):
        events = [json.loads(line) for line in path.read_text().splitlines() if line]
        item = summarize(path)
        config = next((x for x in events if x['event'] == 'config'), {})
        item['config'] = {k: v for k, v in config.items() if k not in ['event', 'time_ms']}
        if not item['success']:
            memory = [x for x in events if x['event'] == 'memory']
            load = next((x for x in events if x['event'] == 'load_start'), {})
            item['peak_pss_mib'] = max((x['pss_kib']/1024 for x in memory), default=None)
            item['baseline_pss_mib'] = memory[0]['pss_kib']/1024 if memory else None
            item['memory_mode'] = load.get('memory_mode')
            item['threads'] = load.get('threads')
            start = next((x['start_ms'] for x in events if x['event'] == 'trial_start'), None)
            failure = next((x['time_ms'] for x in events if x['event'] == 'failure'), None)
            item['failure_since_start_ms'] = failure - start if failure and start else None
        windows = [x for x in events if x['event'] == 'window']
        item['max_window_seconds'] = max(((x['end_sample'] - x['left_sample']) / 16000 for x in windows), default=0)
        item['backlog_ms'] = distribution([x['backlog_ms'] for x in windows])
        closed = [x for x in events if x['event'] == 'seam' and x['kind'] in ['segment', 'final'] and x['segment_sample'] > 0]
        item['closed_seams'] = dict(collections.Counter(x['match'] for x in closed))
        coverage = []
        for ending in (x for x in events if x['event'] == 'trial_end' and 'total_samples' in x):
            position = 0
            contiguous = True
            for w in windows:
                if w['trial'] == ending['trial'] and w['kind'] in ['segment', 'final']:
                    contiguous &= w['core_start_sample'] == position
                    position = w['end_sample']
            coverage.append({'trial': ending['trial'], 'accepted_samples': ending['total_samples'],
                'processed_samples': position, 'contiguous': contiguous and position == ending['total_samples']})
        item['audio_coverage'] = coverage
        item['quality'] = []
        fixture = fixtures.get(config.get('wave'))
        if fixture and config['seconds'] % fixture['seconds'] == 0:
            reference = fixture['reference'] * (config['seconds'] // fixture['seconds'])
            texts = [x['text'] for x in events if (x['event'] == 'display' and x['kind'] == 'final') or
                (x['event'] == 'decoded' and x['kind'] == 'offline')]
            for text in texts:
                item['quality'].append(error_rate(units(reference, fixture['language']), units(text, fixture['language'])))
            item['error_metric'] = 'CER' if fixture['language'] == 'zh' else 'WER'
        start = next((x['start_ms'] for x in events if x['event'] == 'trial_start'), None)
        end = max((x['time_ms'] for x in events if x['event'] == 'trial_end'), default=float('inf'))
        bins = collections.defaultdict(list)
        native_bins = collections.defaultdict(list)
        if start is not None:
            for event in events:
                if event['event'] == 'memory' and start <= event['time_ms'] <= end:
                    bins[int((event['time_ms'] - start) / 30000)].append(event['pss_kib'] / 1024)
                    native_bins[int((event['time_ms'] - start) / 30000)].append(event['native_heap_bytes'] / 1024**2)
        item['pss_30s_bins_mib'] = {str(k): distribution(v) for k, v in sorted(bins.items())}
        item['native_heap_30s_bins_mib'] = {str(k): distribution(v) for k, v in sorted(native_bins.items())}
        item['audio_ring_capacity_samples'] = next((x['audio_ring_capacity_samples'] for x in events
            if x['event'] == 'trial_start' and 'audio_ring_capacity_samples' in x), None)
        item['capture_stop'] = [x for x in events if x['event'] == 'capture_stop']
        if item.get('trials'):
            item['trials'] = [{k: v for k, v in t.items() if k not in ['last_held_text', 'final_text']} |
                {'final_text_sha256': hashlib.sha256(t['final_text'].encode()).hexdigest()} for t in item['trials']]
        output.append(item)
        print(path.stem, json.dumps({k: item.get(k) for k in ['success', 'held_changed_update_gap_ms',
            'final_wait_ms', 'peak_pss_mib', 'max_window_seconds', 'closed_seams', 'quality']}, ensure_ascii=False))
    (HERE / 'results/window-summary.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
