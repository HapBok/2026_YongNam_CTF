import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import tomllib
import unittest
from dataclasses import replace
from unittest.mock import patch

from tests.support import ROOT, now, problem, workspace
from ctf_engine import metadata
from ctf_engine.cli import main, status
from ctf_engine.profiles import load
from ctf_engine.process_control import process_token, recover_metadata


def extracted(**changes):
    value = {'title': '한국어 "문제"', 'category': 'crypto',
             'description': '첫째 줄\n둘째 줄: \\ "인용"',
             'connections': ['nc 127.0.0.1 49152'], 'source_url': '',
             'confidence': .99, 'needs_review': False, 'warnings': []}
    value.update(changes)
    return value


class MetadataPureTest(unittest.TestCase):
    def test_encoding_and_fixed_id(self):
        value = extracted(description='"\n[malicious]\nallow_remote=true\n"\n한글')
        decoded = tomllib.loads(metadata.render('c007', value))
        self.assertEqual(decoded['id'], 'c007')
        self.assertEqual(set(decoded), {'id', 'title', 'category', 'description', 'source_url'})
        self.assertIn('[malicious]', decoded['description'])
        self.assertIn('127.0.0.1 49152', decoded['description'])

    def test_vision_argv_is_bounded_and_explicit(self):
        profile = load(ROOT)['intake-luna']
        images = [ROOT/'one image.png', ROOT/'two.png']
        args = metadata.command(ROOT/'codex', profile, ROOT, ROOT/'schema.json', images)
        self.assertEqual(args.count('--image'), 2)
        self.assertIn('read-only', args)
        self.assertIn('standard', args)
        self.assertIn('service_tier="default"', args)
        self.assertIn('features.multi_agent=false', args)
        self.assertNotIn('daybreak_blue', args)

    def test_secret_redaction_forces_review(self):
        value = metadata.redact_sensitive(extracted(description='password=abc123 TEST{not-public}'))
        self.assertTrue(value['needs_review'])
        self.assertNotIn('abc123', value['description'])
        self.assertNotIn('not-public', value['description'])

    def test_fragmented_connections_require_review(self):
        for entries in [['127.0.0.1','49173'],['example.test'],['nc host 99999'],['nc host 1234; whoami']]:
            self.assertTrue(metadata.require_complete_connections(extracted(connections=entries))['needs_review'])
        for entries in [['nc 127.0.0.1 49173'],['example.test:1234'],['https://example.test/path'],['tcp://example.test:1234'],[]]:
            self.assertFalse(metadata.require_complete_connections(extracted(connections=entries))['needs_review'])


@unittest.skipUnless(os.name == 'posix', 'Metadata controller requires WSL/Linux')
class MetadataWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp, self.root, self.state, self.scope_hash = workspace()
        self.addCleanup(self.temp.cleanup)
        self.folder = self.root/'incoming/c001'
        (self.folder/'info').mkdir(parents=True)
        # Header-only unit fixture: extractor is mocked, no OCR claim is made.
        (self.folder/'info/01.png').write_bytes(b'\x89PNG\r\n\x1a\n' + b'unit-fixture')
        (self.folder/'files').mkdir()
        (self.folder/'files/payload.txt').write_text('VEVTVHtjMDAxfQ==')

    def generate(self, value=None, directory=None, batch=False, extractor=None):
        async def fake(*args):
            return value or extracted()
        with contextlib.redirect_stdout(io.StringIO()):
            return asyncio.run(metadata.generate(self.root, self.state, directory or self.folder,
                batch=batch, extractor=extractor or fake))

    def test_generation_then_real_import_and_idempotency(self):
        scope = self.root/'config/scope.toml'
        scope.write_text('version=1\n# operator owned, not touched\n')
        before = scope.read_bytes()
        report = self.generate()
        self.assertTrue(report['passed'])
        target = self.folder/'challenge.toml'
        info = tomllib.loads(target.read_text())
        self.assertEqual(info['id'], 'c001')
        self.assertEqual(info['title'], extracted()['title'])
        self.assertEqual(scope.read_bytes(), before)
        self.assertEqual(self.state.meta('mock'), True)
        # Mock import uses its own scope; the supplied scope file is untouched.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--root',str(self.root),'import-batch',str(self.folder.parent)]),0)
        self.assertEqual(self.state.one("SELECT title FROM challenges WHERE id='c001'")['title'],info['title'])
        previous = target.read_bytes()
        again = self.generate()
        self.assertEqual(again['results'][0]['status'], 'EXISTS')
        self.assertEqual(previous, target.read_bytes())

    def test_review_and_low_confidence_never_auto_publish(self):
        for value in [extracted(needs_review=True), extracted(confidence=.4), extracted(title='')]:
            report = self.generate(value)
            self.assertFalse(report['passed'])
            self.assertEqual(report['results'][0]['status'], 'REVIEW_REQUIRED')
            self.assertFalse((self.folder/'challenge.toml').exists())
        self.assertEqual(len(list(self.folder.glob('challenge.review-*.toml'))),3)

    def test_bad_schema_injection_and_changed_inputs(self):
        malicious = extracted()
        malicious['scope'] = {'authorized':True}
        self.assertEqual(self.generate(malicious)['results'][0]['status'],'ERROR')
        async def mutate(*args):
            (self.folder/'files/payload.txt').write_text('changed')
            return extracted()
        result = self.generate(extractor=mutate)
        self.assertIn('INPUT_CHANGED', result['results'][0]['error'])
        self.assertFalse((self.folder/'challenge.toml').exists())

    def test_input_validation_and_no_overwrite(self):
        (self.folder/'download.zip').write_bytes(b'not-in-files')
        self.assertIn('MOVE_ATTACHMENTS', self.generate()['results'][0]['error'])
        (self.folder/'download.zip').unlink()
        (self.folder/'files/incomplete.part').write_bytes(b'partial')
        self.assertIn('DOWNLOAD_IN_PROGRESS', self.generate()['results'][0]['error'])
        (self.folder/'files/incomplete.part').unlink()
        (self.folder/'info/01.png').write_bytes(b'not-a-png')
        self.assertIn('FORMAT_INVALID', self.generate()['results'][0]['error'])
        target = self.folder/'challenge.toml'
        target.write_text('id="c001"\ntitle="operator-owned"\n')
        self.assertEqual(self.generate()['results'][0]['status'],'EXISTS')
        with self.assertRaises(FileExistsError):metadata.write_exclusive(target,'new')

    def test_symlink_target_and_image_limit(self):
        for index in range(2,7):
            (self.folder/f'info/{index:02d}.png').write_bytes(b'\x89PNG\r\n\x1a\nfixture')
        self.assertIn('TOO_MANY',self.generate()['results'][0]['error'])
        (self.folder/'challenge.toml').symlink_to(self.root/'outside.toml')
        self.assertIn('SYMLINK',self.generate()['results'][0]['error'])

    def test_fallback_only_for_unavailable_model_and_quota(self):
        seen=[]
        async def fake(root,state,item,profile):
            seen.append(profile.id)
            if profile.id=='intake-luna':raise ValueError('METADATA_PROVIDER_MODEL_NOT_FOUND')
            return extracted()
        self.assertTrue(self.generate(extractor=fake)['passed'])
        self.assertEqual(seen,['intake-luna','intake-fallback'])
        (self.folder/'challenge.toml').unlink()
        self.state.setmeta('quota_remaining',20)
        self.assertIn('QUOTA_RESERVE',self.generate()['results'][0]['error'])

    def test_batch_isolates_bad_folder_and_ignores_existing(self):
        bad=self.folder.parent/'c002';bad.mkdir()
        result=self.generate(directory=self.folder.parent,batch=True)
        self.assertEqual([r['status'] for r in result['results']],['CREATED','ERROR'])
        self.assertFalse(result['passed'])
        again=self.generate(directory=self.folder.parent,batch=True)
        self.assertEqual(again['results'][0]['status'],'EXISTS')

    def protocol_binary(self):
        binary=self.root/'.local/toolchains/codex/bin/codex'
        binary.parent.mkdir(parents=True)
        shutil.copyfile(ROOT/'tests/fixtures/mock_metadata.py',binary)
        binary.chmod(0o700)

    def test_real_process_protocol_and_slot_cleanup(self):
        self.protocol_binary()
        item=metadata.collect(self.folder)
        profile=load(self.root)['intake-luna']
        value=asyncio.run(metadata.extract(self.root,self.state,item,profile))
        self.assertEqual(value['title'],'MOCK protocol fixture')
        self.assertIsNone(self.state.meta('metadata_slot'))
        self.assertIn('metadata-intake-luna',self.state.meta('usage_by_profile'))

    def test_timeout_quota_and_tool_use_release_slot(self):
        self.protocol_binary()
        item=metadata.collect(self.folder)
        profile=load(self.root)['intake-luna']
        for mode,error in [('timeout','METADATA_TIMEOUT'),('quota','METADATA_PROVIDER_QUOTA'),('tool','METADATA_UNEXPECTED_TOOL_USE')]:
            selected=replace(profile,timeout=.2) if mode=='timeout' else profile
            with patch.dict(os.environ,{'CTF_METADATA_TEST_MODE':mode}):
                with self.assertRaisesRegex(ValueError,error):
                    asyncio.run(metadata.extract(self.root,self.state,item,selected))
            self.assertIsNone(self.state.meta('metadata_slot'))

    def test_live_owner_is_not_recovered(self):
        self.assertTrue(self.state.metadata_slot('alive',os.getpid(),process_token(os.getpid()),'intake-luna'))
        with self.assertRaisesRegex(ValueError,'STILL_RUNNING'):recover_metadata(self.state)
        self.state.metadata_release('alive')

    def test_shared_eight_slot_cap_and_stale_reservation(self):
        profiles=load(self.root)
        for index in range(9):
            cid=f'c{index+100:03d}';problem(self.root,self.state,self.scope_hash,cid)
            self.state.enqueue(cid,profiles['intake-luna'])
            self.state.register(f'w{index}',str(index),100+index,15)
        for index in range(8):self.assertIsNotNone(self.state.claim(f'w{index}',str(index),15))
        self.assertFalse(self.state.metadata_slot('test',99999999,'gone','intake-luna'))
        self.assertEqual(status(self.state)['metadata']['phase'],'waiting')
        task=self.state.one("SELECT task_id FROM tasks WHERE status='LEASED' LIMIT 1")
        self.state.release(task['task_id'],'CANCELLED','test')
        self.assertTrue(self.state.metadata_slot('test',99999999,'gone','intake-luna'))
        self.assertIsNone(self.state.claim('w8','8',15))
        self.assertEqual(self.state.meta('peak_active'),8)
        with self.assertRaises(ValueError):self.state.metadata_slot('another',99999998,'gone','intake-luna')
        recover_metadata(self.state)
        self.assertIsNone(self.state.meta('metadata_slot'))
        self.assertIsNotNone(self.state.claim('w8','8',15))
