#!/usr/bin/env python3
"""Deterministic whole-utterance fixtures with silence padding and upstream references."""
import hashlib
import json
from pathlib import Path
import re
import wave

CACHE = Path.home() / '.cache/fcitx5-voice-p0'


def main():
    references, current = {}, None
    for line in (CACHE / 'model/test_wavs/transcript.txt').read_text().splitlines():
        match = re.match(r'^(\S+\.wav)\s+(.+)$', line)
        if match:
            current = match[1]
            references[current] = match[2]
        elif current and line.strip():
            references[current] += ' ' + line.strip()
    manifest = json.loads((Path(__file__).parent / 'artifacts.json').read_text())
    inputs = []
    for name, original, seconds, lang in [
        ('window-fast12.wav', 'fast1', 12, 'zh'),
        ('window-zh21.wav', 'raokouling', 21, 'zh'),
        ('window-en90.wav', 'noise1-en', 90, 'en'),
    ]:
        src = CACHE / f'fixtures/{original}-16k.wav'
        expected = next(x['sha256'] for x in manifest['fixtures'] if x['path'] == f'fixtures/{src.name}')
        assert hashlib.sha256(src.read_bytes()).hexdigest() == expected
        with wave.open(str(src)) as r:
            assert r.getframerate() == 16000 and r.getnchannels() == 1 and r.getsampwidth() == 2
            frames = r.readframes(r.getnframes())
        frames += b'\0' * (seconds * 32000 - len(frames))
        dest = CACHE / 'fixtures' / name
        with wave.open(str(dest), 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(frames)
        ref = references[original + '.wav']
        inputs.append({'file': 'fixtures/' + name, 'sha256': hashlib.sha256(dest.read_bytes()).hexdigest(),
            'seconds': seconds, 'language': lang, 'reference': ref,
            'reference_sha256': hashlib.sha256(ref.encode()).hexdigest(),
            'source': f'fixtures/{src.name}', 'source_sha256': expected})
    (CACHE / 'window-inputs-private.json').write_text(json.dumps(inputs, ensure_ascii=False, indent=2) + '\n')
    public = [{k: v for k, v in x.items() if k != 'reference'} for x in inputs]
    (Path(__file__).parent / 'window-inputs.json').write_text(json.dumps(public, indent=2) + '\n')
    print('Prepared', [(x['file'], x['seconds']) for x in inputs])


if __name__ == '__main__':
    main()
