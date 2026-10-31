#!/usr/bin/env python3
"""Fetch pinned P0 inputs outside Git, checking LFS SHA-256 or Git blob SHA-1."""
import concurrent.futures
import array
import hashlib
import json
import os
from pathlib import Path
import shutil
import random
import subprocess
import time
import urllib.request
import wave

CACHE = Path.home() / '.cache/fcitx5-voice-p0'
MODEL = 'csukuangfj2/sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25'
REV = '68818b2313fe77bd06f6a7c5068ff3ef59d02b8a'
AAR = {
    'path': 'sherpa-onnx-2.0.1.aar', 'size': 49441341,
    'sha256': 'a8d09d1d32f3eb8520482c6d3d43fae674681c5b050385967c70a3c2c9bf0ee7',
    'url': 'https://github.com/k2-fsa/sherpa-onnx/releases/download/v2.0.1/sherpa-onnx-2.0.1.aar',
}


def fetch(url):
    with urllib.request.urlopen(url, timeout=45) as r:
        return r.read()


def valid(path, item):
    if not path.exists() or path.stat().st_size != item['size']:
        return False
    data = path.read_bytes()
    if item.get('sha256'):
        return hashlib.sha256(data).hexdigest() == item['sha256']
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == item['git_blob']


def download(item, dest):
    parts = dest.with_name(dest.name + '.parts')
    if valid(dest, item):
        shutil.rmtree(parts, ignore_errors=True)
        print('Verified cached', item['path'], flush=True)
        return
    parts.mkdir(parents=True, exist_ok=True)
    size = item['size']
    step = 4 * 1024 * 1024
    count = (size + step - 1) // step

    def part(i):
        lo, hi = i * step, min(size, (i + 1) * step) - 1
        p = parts / str(i)
        if p.exists() and p.stat().st_size == hi - lo + 1:
            return i
        for attempt in range(5):
            try:
                sep = '&' if '?' in item['url'] else '?'
                req = urllib.request.Request(item['url'] + sep + f'p0part={i}',
                    headers={'Range': f'bytes={lo}-{hi}', 'User-Agent': 'fcitx5-voice-p0'})
                with urllib.request.urlopen(req, timeout=60) as r:
                    if size > step:
                        assert r.status == 206, (r.status, item['path'])
                        assert r.headers['Content-Range'].startswith(f'bytes {lo}-{hi}/')
                    with p.open('wb') as out:
                        while b := r.read(128 * 1024):
                            out.write(b)
                assert p.stat().st_size == hi - lo + 1
                return i
            except Exception:
                p.unlink(missing_ok=True)
                if attempt == 4:
                    raise
                time.sleep(attempt + 1)

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        for n, _ in enumerate(pool.map(part, range(count)), 1):
            if n % 8 == 0 or n == count:
                print(item['path'], f'{n}/{count} blocks', flush=True)
    tmp = dest.with_name(dest.name + '.download')
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tmp.open('wb') as out:
        for i in range(count):
            with (parts / str(i)).open('rb') as src:
                while b := src.read(1024 * 1024):
                    out.write(b)
    if not valid(tmp, item):
        raise RuntimeError(f'Hash mismatch: {item["path"]}')
    os.replace(tmp, dest)
    shutil.rmtree(parts)
    print('Verified', item['path'], flush=True)


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    tree = json.loads(fetch(f'https://huggingface.co/api/models/{MODEL}/tree/{REV}?recursive=true'))
    wanted = ['conv_frontend.onnx', 'encoder.int8.onnx', 'decoder.int8.onnx',
              'tokenizer/merges.txt', 'tokenizer/vocab.json', 'tokenizer/tokenizer_config.json',
              'test_wavs/fast1.wav', 'test_wavs/f1_noise.wav', 'test_wavs/noise1-en.wav',
              'test_wavs/raokouling.wav', 'test_wavs/transcript.txt', 'README.md']
    items = []
    for path in wanted:
        entry = next(x for x in tree if x['path'] == path)
        items.append({'path': path, 'size': entry['size'], 'git_blob': entry['oid'],
            'sha256': entry.get('lfs', {}).get('oid'),
            'url': f'https://huggingface.co/{MODEL}/resolve/{REV}/{path}'})
    # AAR and the model file set use independent public distribution channels.
    jobs = [(AAR, CACHE / AAR['path'])] + [(x, CACHE / 'model' / x['path']) for x in items]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda job: download(*job), jobs))
    for item, path in jobs:
        item['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {'model_repository': MODEL, 'model_revision': REV,
        'runtime_repository': 'https://github.com/k2-fsa/sherpa-onnx',
        'runtime_tag': 'v2.0.1', 'runtime_source_revision': 'af2d8d81dbfa61c4cea4c568da78f3982edca005',
        'artifacts': [x for x, _ in jobs]}
    fixtures = CACHE / 'fixtures'
    fixtures.mkdir(exist_ok=True)
    manifest['fixtures'] = []
    for src in (CACHE / 'model/test_wavs').glob('*.wav'):
        dest = fixtures / (src.stem + '-16k.wav')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(src), '-ar', '16000',
                        '-ac', '1', '-c:a', 'pcm_s16le', str(dest)], check=True)
        with wave.open(str(dest)) as w:
            duration = w.getnframes() / w.getframerate()
        manifest['fixtures'].append({'path': str(dest.relative_to(CACHE)),
            'sha256': hashlib.sha256(dest.read_bytes()).hexdigest(), 'seconds': duration,
            'derived_from': str(src.relative_to(CACHE))})
    rng = random.Random(20261031)
    for name, values in [('silence-16k.wav', [0] * 48000),
                         ('noise-16k.wav', [rng.randint(-1000, 1000) for _ in range(48000)])]:
        dest = fixtures / name
        pcm = array.array('h', values)
        if __import__('sys').byteorder != 'little':
            pcm.byteswap()
        with wave.open(str(dest), 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(pcm.tobytes())
        manifest['fixtures'].append({'path': str(dest.relative_to(CACHE)),
            'sha256': hashlib.sha256(dest.read_bytes()).hexdigest(), 'seconds': 3,
            'derived_from': 'generated PCM; noise seed 20261031, uniform integer [-1000,1000]'})
    (CACHE / 'artifacts.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
