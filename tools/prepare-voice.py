#!/usr/bin/env python3
"""Prepare pinned V1 runtime/model assets. No mutable model API or runtime downloads."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('voice_download', ROOT / 'tools/voice-p0/prepare.py')
download = importlib.util.module_from_spec(spec)
spec.loader.exec_module(download)
parser = argparse.ArgumentParser()
parser.add_argument('--with-model', choices=['true', 'false'], default='true')
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
cache = Path.home() / '.cache/fcitx5-voice-p0'
manifest = json.loads((ROOT / 'tools/voice-p0/artifacts.json').read_text())
import shutil
shutil.rmtree(args.output / 'assets', ignore_errors=True)
files = []
for item in manifest['artifacts']:
    name = item['path']
    runtime = name.endswith('.aar')
    if not runtime and args.with_model == 'false':
        continue
    if not runtime and not (name.endswith('.onnx') or name.startswith('tokenizer/')):
        continue
    source = cache / (name if runtime else 'model/' + name)
    download.download(item, source)
    # Recheck even cached artifacts; never ship unverified native code or weights.
    digest = hashlib.file_digest(source.open('rb'), 'sha256').hexdigest()
    if digest != item['sha256']:
        raise RuntimeError('SHA-256 mismatch: ' + name)
    target = args.output / ('runtime/' + name if runtime else 'assets/voice/' + name)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    try:
        os.link(source, target)
    except OSError:
        import shutil
        shutil.copyfile(source, target)
    if not runtime:
        files.append({key: item[key] for key in ('path', 'size', 'sha256')})
(args.output / 'assets/voice').mkdir(parents=True, exist_ok=True)
(args.output / 'assets/voice/files.json').write_text(json.dumps(files, indent=2) + '\n')
