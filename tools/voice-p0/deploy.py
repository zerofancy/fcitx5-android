#!/usr/bin/env python3
"""Build the isolated harness and place verified fixtures in its private files directory."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tarfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--serial', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    project = Path(__file__).resolve().parent
    cache = Path.home() / '.cache/fcitx5-voice-p0'
    env = os.environ.copy()
    env.setdefault('ANDROID_HOME', str(Path.home() / 'Android/Sdk'))
    subprocess.run([str(root / 'gradlew'), '-p', str(project), 'assembleDebug', '--console=plain'],
                   check=True, env=env)
    adb = ['adb', '-s', args.serial]
    app = 'org.fcitx.voicep0'
    subprocess.run(adb + ['install', '-r', str(project / 'build/outputs/apk/debug/fcitx5-voice-p0-debug.apk')], check=True)
    subprocess.run(adb + ['shell', 'pm', 'grant', app, 'android.permission.RECORD_AUDIO'], check=True)
    subprocess.run(adb + ['shell', 'run-as', app, 'mkdir', '-p', 'files'], check=True)
    proc = subprocess.Popen(adb + ['exec-in', 'run-as', app, 'tar', '-xf', '-', '-C', 'files'], stdin=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=proc.stdin, mode='w|') as archive:
            def only_inputs(info):
                return None if '.parts' in info.name.split('/') or info.name.endswith('.parts') else info
            for directory in ['model', 'fixtures']:
                archive.add(cache / directory, arcname=directory, filter=only_inputs)
        proc.stdin.close()
        assert proc.wait(timeout=180) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
    manifest = json.loads((cache / 'artifacts.json').read_text())
    checks = [(f'model/{x["path"]}', x['sha256']) for x in manifest['artifacts'] if not x['path'].endswith('.aar')]
    checks += [(x['path'], x['sha256']) for x in manifest['fixtures']]
    for name, expected in checks:
        actual = subprocess.check_output(adb + ['shell', 'run-as', app, 'sha256sum', 'files/' + name], text=True).split()[0]
        assert actual == expected, name
        print('Verified on device:', name, flush=True)


if __name__ == '__main__':
    main()
