import os
import re
import subprocess
from pathlib import Path

def main():
    repo_root = Path(__file__).resolve().parent.parent
    tracked = subprocess.check_output(['git', 'ls-files'], cwd=str(repo_root)).decode('utf-8').splitlines()

    PATTERNS = [
        (re.compile(r'([0-9]{8,11}:[a-zA-Z0-9_-]{35})'), 'Telegram Bot Token'),
        (re.compile(r'AIzaSy[a-zA-Z0-9_-]{33}'), 'Google Gemini API Key'),
        (re.compile(r're_[a-zA-Z0-9]{24,}'), 'Resend API Key'),
        (re.compile(r'ghp_[a-zA-Z0-9]{36}'), 'GitHub Token'),
    ]

    found = []
    for rel_path in tracked:
        fpath = repo_root / rel_path
        if not fpath.exists():
            continue
        if str(fpath).endswith(('.png', '.jpg', '.ico', '.woff', '.woff2')):
            continue
        try:
            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                for pattern, name in PATTERNS:
                    matches = pattern.findall(content)
                    for m in matches:
                        val = m[0] if isinstance(m, tuple) else m
                        if any(dummy in str(val).lower() for dummy in ['example', 'placeholder', 'your_', 'test_', 'mock', 'dummy']):
                            continue
                        found.append((rel_path, name, str(val)[:4] + '...' + str(val)[-4:]))
        except Exception:
            pass

    print(f'Scan completed over {len(tracked)} tracked files. Potential leaks found: {len(found)}')
    for rel_path, name, preview in found:
        print(f'  [!] {rel_path} -> {name}: {preview}')

if __name__ == '__main__':
    main()
