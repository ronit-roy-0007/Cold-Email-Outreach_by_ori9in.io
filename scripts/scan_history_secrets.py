import subprocess
import re
from pathlib import Path

def main():
    repo_root = Path(__file__).resolve().parent.parent
    PATTERNS = [
        (re.compile(r'([0-9]{8,11}:[a-zA-Z0-9_-]{35})'), 'Telegram Bot Token'),
        (re.compile(r'AIzaSy[a-zA-Z0-9_-]{33}'), 'Google Gemini API Key'),
        (re.compile(r're_[a-zA-Z0-9]{24,}'), 'Resend API Key'),
        (re.compile(r'ghp_[a-zA-Z0-9]{36}'), 'GitHub Token'),
    ]

    p = subprocess.Popen(
        ['git', 'log', '-p', '--all'],
        cwd=str(repo_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    found = []
    current_commit = None
    for raw_line in p.stdout:
        line = raw_line.decode('utf-8', errors='ignore')
        if line.startswith('commit '):
            current_commit = line.split()[1][:8]
        if line.startswith('+') and not line.startswith('+++'):
            for pattern, name in PATTERNS:
                matches = pattern.findall(line)
                for m in matches:
                    val = m[0] if isinstance(m, tuple) else m
                    if any(dummy in str(val).lower() for dummy in ['example', 'placeholder', 'your_', 'test_', 'mock', 'dummy']):
                        continue
                    found.append((current_commit, name, str(val)[:4] + '...' + str(val)[-4:]))

    print(f'Git history scan complete. Discovered potential history credentials: {len(found)}')
    for commit, name, preview in found[:20]:
        print(f'  Commit {commit}: {name} ({preview})')

if __name__ == '__main__':
    main()
