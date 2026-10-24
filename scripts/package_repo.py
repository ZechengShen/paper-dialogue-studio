"""Build a source-only GitHub handoff; private inputs, credentials and media are excluded."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP_FILES = {'.gitignore', '.gitattributes', '.env.example', 'AGENTS.md', 'README.md', 'WORKFLOW.md', 'DESIGN.md',
             'requirements.txt', 'setup.ps1', 'run.ps1', 'start-web.ps1', '启动论文开讲.cmd', 'LICENSE'}
TREES = ('scripts', 'web', 'assets', 'config', 'docs', 'tests', '.github', '.agents/skills/paper-dialogue-podcast', 'examples/research-v3')
SUFFIXES = {'.py', '.js', '.cjs', '.html', '.css', '.json', '.yaml', '.yml', '.md', '.txt', '.ps1'}
PRIVATE_PARTS = {'__pycache__', 'screenshots', '.cache', '.runtime', 'node_modules'}


def source_files(root=ROOT):
    files = [root/name for name in TOP_FILES if (root/name).is_file()]
    for tree in TREES:
        for path in (root/tree).rglob('*'):
            relative = path.relative_to(root)
            if not path.is_file() or any(p in PRIVATE_PARTS or '-test-' in p for p in relative.parts):
                continue
            if path.suffix not in SUFFIXES or path.name.endswith(('.local.yaml', '.local.json')):
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError('Refusing external link: ' + relative.as_posix())
            files.append(path)
    files += [root/f'{name}/.gitkeep' for name in ('inbox', 'outputs') if (root/f'{name}/.gitkeep').is_file()]
    return sorted(set(files))


def audit(root=ROOT):
    files = source_files(root)
    issues = []
    patterns = [r'(?<![\w-])sk-[A-Za-z0-9_-]{20,}', r'gh[pousr]_[A-Za-z0-9]{30,}',
                r'github_pat_[A-Za-z0-9_]{30,}', r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
                r'(?i)[A-Z]:[\\/]+Users[\\/]+[^\s\\/"\']+[\\/]', r'/' + 'Users' + r'/[^/\s]+/']
    for path in files:
        text = path.read_text(encoding='utf-8-sig')
        if any(re.search(pattern, text) for pattern in patterns):
            issues.append(path.relative_to(root).as_posix())  # Never print matched secrets.
    return files, issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Only audit source candidates; no archive')
    args = parser.parse_args()
    files, issues = audit()
    if issues:
        print(json.dumps({'ok': False, 'files_requiring_review': issues}, ensure_ascii=False))
        return 1
    report = {'ok': True, 'source_files': len(files), 'excluded': ['.env', 'inbox materials', 'outputs', 'logs', 'media', 'venv', 'model weights', '.git'],
              'note': 'Automated pattern scan is not a guarantee. Review the archive before publishing.'}
    if not args.check:
        target = ROOT/'dist'/('paper-dialogue-studio-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'.zip')
        target.parent.mkdir(exist_ok=True)
        manifest = {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
        with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
            for path in files:
                archive.write(path, 'paper-dialogue-studio/'+path.relative_to(ROOT).as_posix())
            archive.writestr('paper-dialogue-studio/SOURCE-MANIFEST.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        report['archive'] = str(target)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
