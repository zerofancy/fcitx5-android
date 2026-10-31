#!/usr/bin/env python3
"""Run one device experiment. Temporarily selected test IME is always restored."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time

APP = 'org.fcitx.voicep0'
IME = APP + '/.BenchIme'
REMOTE = f'/sdcard/Android/data/{APP}/files'


def main():
    p = argparse.ArgumentParser()
    p.add_argument('id')
    p.add_argument('--mode', choices=['offline', 'replay', 'ime-replay', 'ime-mic', 'ime-window', 'ime-window-mic'], default='offline')
    p.add_argument('--seconds', type=int, default=3)
    p.add_argument('--threads', type=int, default=3)
    p.add_argument('--repeats', type=int, default=1)
    p.add_argument('--total-len', type=int, default=512)
    p.add_argument('--memory-mode', choices=['default', 'no-arena', 'no-prepack', 'compact', 'basic'], default='default')
    p.add_argument('--core-ms', type=int, default=2000)
    p.add_argument('--overlap-ms', type=int, default=1000)
    p.add_argument('--hop-ms', type=int, default=500)
    p.add_argument('--deadline-aware', action='store_true')
    p.add_argument('--wave', default='fixtures/fast1-16k.wav')
    p.add_argument('--serial', default=os.environ.get('ANDROID_SERIAL'))
    p.add_argument('--timeout', type=int, default=600)
    args = p.parse_args()
    assert re.fullmatch(r'[A-Za-z0-9_-]+', args.id)
    assert re.fullmatch(r'[A-Za-z0-9_./-]+', args.wave)
    assert args.seconds >= 1 and 1 <= args.repeats <= 30
    assert args.mode.startswith('ime-window') or args.seconds <= 60
    assert 500 <= args.core_ms <= 8000 and 0 <= args.overlap_ms <= args.core_ms
    assert args.hop_ms >= 100
    base = ['adb'] + (['-s', args.serial] if args.serial else [])

    def adb(*cmd, check=True):
        return subprocess.run(base + list(cmd), capture_output=True, text=True, check=check, timeout=20).stdout.strip()

    results = Path(__file__).parent / 'results'
    results.mkdir(exist_ok=True)
    if (results / f'{args.id}.jsonl').exists():
        p.error('Experiment id already exists; choose a fresh id to preserve evidence')
    remote_exists = subprocess.run(base + ['shell', 'test', '-e', f'{REMOTE}/{args.id}.jsonl'],
        capture_output=True, timeout=20).returncode
    if remote_exists == 0:
        p.error('Experiment id exists on the device; choose a fresh id')
    if remote_exists != 1:
        raise RuntimeError('Cannot check device evidence directory')
    old_ime = adb('shell', 'settings', 'get', 'secure', 'default_input_method')
    was_enabled = IME in adb('shell', 'ime', 'list', '-s').splitlines()
    metadata = {'id': args.id, 'arguments': vars(args), 'previous_ime': old_ime,
        'fingerprint': adb('shell', 'getprop', 'ro.build.fingerprint'),
        'soc': adb('shell', 'getprop', 'ro.soc.model'),
        'pagesize': adb('shell', 'getconf', 'PAGESIZE'),
        'meminfo_before': adb('shell', 'cat', '/proc/meminfo'),
        'thermal_before': adb('shell', 'dumpsys', 'thermalservice'),
        'battery_before': adb('shell', 'dumpsys', 'battery')}
    media_volume = None
    if args.mode in ['ime-mic', 'ime-window-mic']:
        output = adb('shell', 'cmd', 'media_session', 'volume', '--stream', '3', '--get')
        match = re.search(r'volume is (\d+) in range \[\d+\.\.(\d+)\]', output)
        if match:
            media_volume = (int(match[1]), int(match[2]))
        metadata['media_volume_before'] = output
    installed_apk = adb('shell', 'pm', 'path', APP).splitlines()[0].removeprefix('package:')
    metadata['apk_sha256'] = adb('shell', 'sha256sum', installed_apk).split()[0]
    (results / f'{args.id}-device.json').write_text(json.dumps(metadata, indent=2) + '\n')
    logcat = None
    catfile = (results / f'{args.id}-logcat.txt').open('w')
    try:
        adb('shell', 'am', 'force-stop', APP)
        if args.mode.startswith('ime-'):
            adb('shell', 'ime', 'enable', IME)
            adb('shell', 'ime', 'set', IME)
        print(adb('shell', 'am', 'start', '-W', '-n', APP + '/.BenchActivity',
            '--es', 'id', args.id, '--es', 'mode', args.mode,
            '--ei', 'seconds', str(args.seconds), '--ei', 'threads', str(args.threads),
            '--ei', 'repeats', str(args.repeats), '--es', 'wave', args.wave,
            '--ei', 'total_len', str(args.total_len), '--es', 'memory_mode', args.memory_mode,
            '--ei', 'core_ms', str(args.core_ms), '--ei', 'overlap_ms', str(args.overlap_ms),
            '--ei', 'hop_ms', str(args.hop_ms), '--ez', 'deadline_aware', str(args.deadline_aware).lower()), flush=True)
        pid = adb('shell', 'pidof', APP)
        if pid:
            logcat = subprocess.Popen(base + ['logcat', '--pid=' + pid, '-v', 'threadtime', '-T', '1'],
                stdout=catfile, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + args.timeout
        raw = ''
        while time.monotonic() < deadline:
            raw = adb('shell', 'cat', f'{REMOTE}/{args.id}.jsonl', check=False)
            lines = []
            for line in raw.splitlines():
                try:
                    lines.append(json.loads(line))
                except ValueError:
                    pass
            if any(x['event'] in ['complete', 'failure'] for x in lines):
                break
            if not adb('shell', 'pidof', APP):
                raise RuntimeError('Benchmark process exited unexpectedly')
            time.sleep(2)
        else:
            raise TimeoutError('Benchmark deadline exceeded; raw data retained')
        time.sleep(1)
        raw = adb('shell', 'cat', f'{REMOTE}/{args.id}.jsonl', check=False)
        (results / f'{args.id}.jsonl').write_text(raw + '\n')
        lines = [json.loads(x) for x in raw.splitlines()]
        for event in lines:
            if event['event'] in ['loaded', 'decoded', 'trial_end', 'failure', 'complete']:
                print(json.dumps(event, ensure_ascii=False), flush=True)
        if any(x['event'] == 'failure' for x in lines):
            raise RuntimeError('Device reported failure')
        if any(x['event'] == 'complete' and x['cancelled'] for x in lines):
            raise RuntimeError('Device run was cancelled')
    finally:
        raw = adb('shell', 'cat', f'{REMOTE}/{args.id}.jsonl', check=False)
        (results / f'{args.id}.jsonl').write_text(raw + '\n')
        metadata['thermal_after'] = adb('shell', 'dumpsys', 'thermalservice')
        metadata['battery_after'] = adb('shell', 'dumpsys', 'battery')
        metadata['meminfo_after'] = adb('shell', 'dumpsys', 'meminfo', APP)
        (results / f'{args.id}-device.json').write_text(json.dumps(metadata, indent=2) + '\n')
        if media_volume:
            output = adb('shell', 'cmd', 'media_session', 'volume', '--stream', '3', '--get')
            match = re.search(r'volume is (\d+)', output)
            if match and int(match[1]) == max(media_volume[0], min(8, media_volume[1])):
                adb('shell', 'cmd', 'media_session', 'volume', '--stream', '3', '--set', str(media_volume[0]))
        if args.mode.startswith('ime-'):
            adb('shell', 'ime', 'set', old_ime)
            if not was_enabled:
                adb('shell', 'ime', 'disable', IME)
        adb('shell', 'am', 'force-stop', APP)
        if logcat:
            logcat.terminate()
            logcat.wait(timeout=10)
        catfile.close()


if __name__ == '__main__':
    main()
