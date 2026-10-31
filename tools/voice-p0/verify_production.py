#!/usr/bin/env python3
"""NX888J end-to-end lab: actual space gesture, microphone, production IME and host composing.
Requires the voice APK, lab APK and window-fast12.wav fixture already installed/prepared.
The production space-long-press preference must explicitly be set to VoiceInput first.
"""
import argparse
import hashlib
import json
import re
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--serial', required=True)
parser.add_argument('--id', default='v1-prod-' + str(int(time.time())))
parser.add_argument('--case', choices=['full', 'target-switch'], default='full')
parser.add_argument('--space-x', type=int, default=700)
parser.add_argument('--space-y', type=int, default=2610)
args = parser.parse_args()
assert re.fullmatch('[A-Za-z0-9_-]+', args.id)
adb = ['adb', '-s', args.serial]
pkg = 'org.fcitx.fcitx5.android.debug'
ime = pkg + '/org.fcitx.fcitx5.android.input.FcitxInputMethodService'
result = Path(__file__).resolve().parent / 'results'
result.mkdir(exist_ok=True)
prefix = result / args.id
events, samples = [], []
sampling = threading.Event()

def call(*parts):
    return subprocess.check_output(adb + list(parts), text=True).strip()

def mark(name):
    t = float(call('shell', 'cat', '/proc/uptime').split()[0]) * 1000
    events.append({'name': name, 'device_ms': t})
    print(name, round(t), flush=True)

def touch(kind):
    call('shell', 'input', 'motionevent', kind, str(args.space_x), str(args.space_y))

def hold(seconds):
    mark('down'); touch('DOWN'); time.sleep(seconds); touch('UP'); mark('release')

def sampler():
    while not sampling.is_set():
        out = call('shell', 'dumpsys', 'meminfo', pkg)
        m = re.search(r'TOTAL PSS:\s*(\d+)', out)
        if m:
            samples.append({'wall': time.time(), 'pss_kib': int(m[1])})
        sampling.wait(1)

def second_target():
    # A continuously changing editor never satisfies UIAutomator's idle criterion.
    # Geometry comes from the lab host, while the click still traverses Android's real input path.
    rows = [json.loads(line) for line in call('shell', 'cat', remote).splitlines()]
    state = next(x for x in reversed(rows) if x['event'] == 'host_state')
    x0, y0, x1, y1 = state['second_bounds']
    assert y0 < args.space_y - 500, 'Second editor must be above the keyboard'
    touch('UP')
    mark('switch_release')
    call('shell', 'input', 'tap', str((x0+x1)//2), str((y0+y1)//2))

remote = '/sdcard/Android/data/org.fcitx.voicep0/files/' + args.id + '.jsonl'
assert not prefix.with_suffix('.jsonl').exists(), 'Use a fresh ID'
assert subprocess.run(adb + ['shell', 'test', '-e', remote]).returncode != 0, 'Remote ID exists'
prefs = call('shell', 'run-as', pkg, 'cat', 'shared_prefs/' + pkg + '_preferences.xml')
assert ET.fromstring(prefs).find("string[@name='space_long_press_behavior']").text == 'VoiceInput'
previous_ime = call('shell', 'settings', 'get', 'secure', 'default_input_method')
previous_enabled = call('shell', 'settings', 'get', 'secure', 'enabled_input_methods')
volume = int(re.search(r'volume is (\d+)', call('shell', 'cmd', 'media_session', 'volume', '--stream', '3', '--get'))[1])
try:
    call('shell', 'ime', 'enable', ime); call('shell', 'ime', 'set', ime)
    call('shell', 'cmd', 'media_session', 'volume', '--stream', '3', '--set', '8')
    call('shell', 'am', 'force-stop', 'org.fcitx.voicep0')
    call('shell', 'am', 'start', '-n', 'org.fcitx.voicep0/.BenchActivity', '--es', 'id', args.id,
         '--es', 'mode', 'production-host', '--ei', 'stimulus_seconds', '110')
    time.sleep(2)
    call('shell', 'input', 'tap', '500', '300'); time.sleep(1)
    thread = threading.Thread(target=sampler, daemon=True); thread.start()
    if args.case == 'full':
        mark('short_tap'); touch('DOWN'); time.sleep(.05); touch('UP'); time.sleep(.5)
        mark('cold_begin'); hold(24); time.sleep(6); mark('cold_done')
        mark('warm_begin'); hold(12); time.sleep(6); mark('warm_done')
        mark('cancel_begin'); touch('DOWN'); time.sleep(8)
        call('shell', 'input', 'keyevent', '4'); mark('back_cancel'); time.sleep(2)
        touch('UP'); time.sleep(2); mark('cancel_done')
        call('shell', 'input', 'tap', '500', '300'); time.sleep(1)
    mark('switch_begin'); touch('DOWN'); time.sleep(8)
    second_target(); mark('target_switched'); time.sleep(4)
    time.sleep(2); mark('switch_done')
finally:
    sampling.set()
    call('shell', 'cmd', 'media_session', 'volume', '--stream', '3', '--set', str(volume))
    call('shell', 'am', 'force-stop', 'org.fcitx.voicep0')
    call('shell', 'ime', 'set', previous_ime)
    if ime not in previous_enabled.split(':'):
        call('shell', 'ime', 'disable', ime)
    raw = call('shell', 'cat', remote)
    prefix.with_suffix('.jsonl').write_text(raw + '\n')
    Path(str(prefix) + '-driver.json').write_text(json.dumps({'id': args.id, 'events': events,
        'memory': samples, 'host_jsonl_sha256': hashlib.sha256((raw+'\n').encode()).hexdigest()}, indent=2) + '\n')
    print('SAVED', args.id, flush=True)
