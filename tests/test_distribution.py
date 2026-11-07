"""Source-only release and relocation checks; never call models or online TTS."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import package_repo


class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='distribution-test-')
        self.root = Path(self.temp.name) / 'source with spaces'
        self.root.mkdir()
        for source in package_repo.source_files():
            target = self.root / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def tearDown(self):
        self.temp.cleanup()

    def test_required_first_run_files(self):
        self.assertEqual(package_repo.audit(self.root)[1], [])
        (self.root / '首次安装.cmd').unlink()
        self.assertIn('MISSING: 首次安装.cmd', package_repo.audit(self.root)[1])
        with self.assertRaises(ValueError):
            package_repo.build_archive(self.root)

    def test_archive_excludes_private_data_and_has_exact_hashes(self):
        private = ['.env', '.codex/auth.json', '.git/config', '.venv/pyvenv.cfg',
                   'inbox/private-paper.pdf', 'outputs/podcast.mp3', '_local_archive/backup.txt',
                   '.runtime/service.log', 'config/voice.local.yaml', 'tests/screenshots/private.png']
        for name in private:
            file = self.root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text('private-fixture-do-not-share', encoding='utf-8')
        archive, checksum, digest = package_repo.build_archive(self.root)
        self.assertEqual(digest, hashlib.sha256(archive.read_bytes()).hexdigest())
        self.assertEqual(checksum.read_text().strip(), digest + '  ' + archive.name)
        with zipfile.ZipFile(archive) as bundle:
            prefix = 'paper-dialogue-studio/'
            manifest = json.loads(bundle.read(prefix + 'SOURCE-MANIFEST.json'))
            self.assertEqual(set(bundle.namelist()), {prefix + name for name in manifest} | {prefix + 'SOURCE-MANIFEST.json'})
            for name, expected in manifest.items():
                self.assertEqual(expected, hashlib.sha256(bundle.read(prefix + name)).hexdigest())
            for name in private:
                self.assertNotIn(prefix + name, bundle.namelist())
            self.assertIn('首次安装.cmd', manifest)
            self.assertIn('.agents/skills/paper-dialogue-podcast/SKILL.md', manifest)
        second, _, _ = package_repo.build_archive(self.root)
        self.assertNotEqual(archive, second)

    def test_suspected_secret_in_source_blocks_release_without_echo(self):
        marker = 'ntn_' + 'x' * 40  # Fake pattern only; not a credential.
        (self.root / 'docs/leak.md').write_text(marker, encoding='utf-8')
        issues = package_repo.audit(self.root)[1]
        self.assertIn('docs/leak.md', issues)
        self.assertNotIn(marker, str(issues))
        with self.assertRaises(ValueError):
            package_repo.build_archive(self.root)

    def test_unpacked_copy_starts_empty_and_codex_claim_uses_new_root(self):
        archive, _, _ = package_repo.build_archive(self.root)
        destination = Path(self.temp.name) / 'another user folder'
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(destination)
        relocated = destination / 'paper-dialogue-studio'
        environment = os.environ.copy()
        for key in list(environment):
            if key.startswith(('PAPER_DIALOGUE_', 'LLM_', 'MOONSHOT_', 'OPENAI_', 'NOTION_')) or key == 'PYTHONPATH':
                environment.pop(key)
        code = '''
import json
from pathlib import Path
from web import app as site
root = Path.cwd().resolve()
assert site.AUDIO_PROJECT_DIR == root
client = site.app.test_client()
assert client.get('/').status_code == 200
assert client.get('/api/health').json['audio_project_ready']
assert client.get('/api/jobs').json['jobs'] == []
assert not client.get('/api/settings').json['key_configured']
created = client.post('/api/jobs', data={'source_type':'html', 'html':'<p>Relocation software fixture, not research.</p>', 'synthesize_audio':'false'})
assert created.status_code == 202, created.json
job_id = created.json['job_id']
assert (root/'inbox'/job_id/'request.json').is_file()
print(json.dumps({'job_id': job_id}))
'''
        run = subprocess.run([sys.executable, '-B', '-c', code], cwd=relocated, env=environment,
                             capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        job_id = json.loads(run.stdout)['job_id']
        claim = subprocess.run([sys.executable, '-B', '.agents/skills/paper-dialogue-podcast/scripts/inbox_job.py',
                                'next', '--claim', '--job-id', job_id], cwd=relocated, env=environment,
                               capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(claim.returncode, 0, claim.stderr)
        status = json.loads((relocated/'inbox'/job_id/'status.json').read_text(encoding='utf-8'))
        self.assertEqual(status['phase'], 'claimed')
        self.assertEqual(list((self.root/'inbox').iterdir()), [self.root/'inbox/.gitkeep'])


if __name__ == '__main__':
    unittest.main()
