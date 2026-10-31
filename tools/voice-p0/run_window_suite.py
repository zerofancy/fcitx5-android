#!/usr/bin/env python3
"""Replay the saved experiment plan with fresh IDs, preserving earlier evidence."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--serial', required=True)
    parser.add_argument('--suffix', required=True)
    parser.add_argument('--case', action='append', help='Saved id; repeat for selected cases, otherwise run all')
    args = parser.parse_args()
    assert re.fullmatch(r'[A-Za-z0-9_-]+', args.suffix)
    here = Path(__file__).resolve().parent
    cases = json.loads((here / 'window-experiments.json').read_text())
    known = {case['id'] for case in cases}
    if args.case and not set(args.case) <= known:
        parser.error('Unknown cases: ' + ', '.join(sorted(set(args.case) - known)))
    failed = []
    for case in cases:
        if args.case and case['id'] not in args.case:
            continue
        cmd = [sys.executable, str(here / 'run.py'), case['id'] + '-' + args.suffix,
               '--serial', args.serial]
        for key, value in case.items():
            if key == 'id':
                continue
            flag = '--' + key.replace('_', '-')
            if isinstance(value, bool):
                if value:
                    cmd.append(flag)
            else:
                cmd += [flag, str(value)]
        print('RUN', case['id'], flush=True)
        if subprocess.run(cmd).returncode:
            failed.append(case['id'])
    print('Failed runs:', failed)
    raise SystemExit(bool(failed))


if __name__ == '__main__':
    main()
