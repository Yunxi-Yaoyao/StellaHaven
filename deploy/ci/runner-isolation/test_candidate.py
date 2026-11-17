#!/usr/bin/env python3
"""Offline candidate contracts and mutations; no external state writes."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import os
import sys
import tempfile
import tomllib
import unittest
import yaml

HERE=Path(__file__).resolve().parent

def load(name):
    s=importlib.util.spec_from_file_location(name,HERE/(name+'.py'))
    assert s is not None and s.loader is not None
    m=importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m
r=load('render_candidate'); d=load('image_receipt')
_prewarm=load('test_prewarm')
PrewarmContract=_prewarm.PrewarmContract
PrewarmShellTests=_prewarm.PrewarmShellTests

class CandidateContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old=yaml.safe_load((r.ROOT/'.gitlab-ci.yml').read_text()); cls.ci=r.compile_ci(cls.old)

    def test_test_jobs_keep_commands_and_needs(self):
        for name in r.TESTS:
            self.assertEqual(self.ci[name]['script'],self.old[name]['script'])
            self.assertEqual(self.ci[name]['tags'],['stella-isolated-test'])
            self.assertNotIn('environment',self.ci[name]); self.assertEqual(self.ci[name]['cache'],[])
            self.assertIn('STELLA_PRODUCTION_SSH_KEY',self.ci[name]['before_script'][0])
        self.assertEqual(self.ci['build-images']['needs'],self.old['build-images']['needs'])

    def test_every_job_assigned_not_untagged(self):
        for name,job in self.ci.items():
            if isinstance(job,dict) and 'stage' in job:
                self.assertEqual(len(job['tags']),1,name)
                self.assertIn(job['tags'][0],['stella-isolated-'+x for x in r.LANES])

    def test_build_no_host_daemon_or_latest(self):
        b=self.ci['build-images']; self.assertEqual(b['image']['name'],r.BUILDKIT)
        self.assertNotIn('environment',b)
        s=(HERE/'build-rootless.sh').read_text()
        self.assertNotIn('docker build',s); self.assertNotIn('--network=host',s)
        self.assertNotIn('--oci-worker-no-process-sandbox',s)
        self.assertNotIn(':latest',s); self.assertIn('--metadata-file',s)
        self.assertIn('unset auth CI_REGISTRY_PASSWORD',s)
        self.assertLess(s.index('BLOCKED_SPACE'),s.index('CI_REGISTRY_USER:?'))
        self.assertIn('8388608',s)
        self.assertIn('--oci-worker-snapshotter=overlayfs',s)
        self.assertNotIn('--oci-worker-snapshotter=native',s)
        self.assertEqual(self.ci['build-image-receipt']['artifacts']['reports']['dotenv'],'production-image.env')

    def test_manual_matrix_always_fail_closed(self):
        j=self.ci['local-ha-production-app']; rules=j['rules']
        self.assertEqual([x['when'] for x in rules],['manual','never'])
        self.assertFalse(rules[0]['allow_failure']); self.assertIn('manual_confirmation',j)
        expected={'CI_COMMIT_BRANCH':'master','CI_COMMIT_REF_PROTECTED':'true','STELLA_DEPLOY_TARGET':'local-ha','STELLA_RUNNER_ISOLATION_READY':'true'}
        condition=rules[0]['if']
        def matches(env):
            return all(f'${key} == "{value}"' in condition and env.get(key)==value for key,value in expected.items())
        self.assertTrue(matches(expected))
        for key in expected:
            for wrong in (None,'false','','feature','k3s'):
                with self.subTest(key=key,wrong=wrong):
                    self.assertFalse(matches(dict(expected,**{key:wrong})))
        self.assertNotIn('STELLA_AUTO_DEPLOY',condition)
        self.assertEqual(j['resource_group'],'stella-production'); self.assertFalse(j['interruptible'])
        self.assertEqual(j['script'],self.old['local-ha-production-app']['script'])
        self.assertEqual(j['environment'],self.old['local-ha-production-app']['environment'])

    def test_other_release_paths_disabled(self):
        for name in r.DISABLED: self.assertEqual(self.ci[name]['rules'],[{'when':'never'}])
        self.assertNotIn('STELLA_RUNNER_ISOLATION_READY',self.ci.get('variables',{}))

    def test_toml_daemon_boundaries(self):
        for lane in r.LANES:
            cfg=tomllib.loads(r.runner_toml(lane,self.ci)); runner=cfg['runners'][0]; docker=runner['docker']
            self.assertEqual(cfg['concurrent'],1); self.assertEqual(runner['limit'],1)
            self.assertFalse(docker['privileged']); self.assertFalse(docker['services_privileged'])
            self.assertEqual(docker['volumes'],[]); self.assertEqual(docker['devices'],[])
            self.assertTrue(docker['disable_cache']); self.assertNotEqual(docker['network_mode'],'gitlab_default')
            self.assertEqual(docker['allowed_pull_policies'],['always'])
            self.assertNotIn('extra_hosts',docker)
            self.assertEqual(docker['dns'],['223.5.5.5','119.29.29.29'])
            self.assertTrue(all('@sha256:' in i for i in docker['allowed_images']))
            if lane=='build':
                self.assertEqual(docker['user'],'1000:1000'); self.assertEqual(docker['allowed_users'],['1000:1000'])
                self.assertEqual(docker['security_opt'],['seccomp=unconfined','systempaths=unconfined'])
            else: self.assertEqual(docker['security_opt'],[])

    def test_managers_never_treated_as_job_sandbox(self):
        c=r.compose()
        for lane in r.LANES:
            s=c['services']['runner-'+lane]
            self.assertEqual(s['profiles'],['operator-approved-isolation'])
            self.assertFalse(s['privileged']); self.assertEqual(s['restart'],'no')
            self.assertTrue(any(v['source']=='/var/run/docker.sock' for v in s['volumes']))
            self.assertFalse(c['networks']['stella-ci-'+lane]['enable_ipv6'])

    def test_api_payloads_paused_locked_project_scoped(self):
        p=r.registration(); self.assertTrue(p['not_executed'])
        self.assertFalse(p['project_update']['body']['shared_runners_enabled'])
        for item in p['new_runners']:
            body=item['body']; self.assertTrue(body['paused']); self.assertTrue(body['locked']); self.assertFalse(body['run_untagged'])
            self.assertEqual(body['runner_type'],'project_type'); self.assertEqual(body['project_id'],2)
        self.assertEqual(p['new_runners'][-1]['body']['access_level'],'ref_protected')

    def test_serialized_bundle_and_mutation_rejection(self):
        verifier=load('verify_bundle')
        with tempfile.TemporaryDirectory(prefix='runner-proposal-mutations-',dir=os.environ['TMPDIR']) as tmp:
            out=Path(tmp)
            subprocess.run([sys.executable,str(HERE/'render_candidate.py'),'--out',tmp],check=True,capture_output=True)
            self.assertEqual(verifier.verify(out)['status'],'PASS')
            mutations=[
                ('test.config.toml','privileged = false','privileged = true'),
                ('test.config.toml','volumes = []','volumes = ["/var/run/docker.sock:/var/run/docker.sock"]'),
                ('build.config.toml','user = "1000:1000"','user = "0"'),
                ('deploy.config.toml','network_mode = "stella-ci-deploy"','network_mode = "host"'),
                ('gitlab-change-payloads.json','"shared_runners_enabled": false','"shared_runners_enabled": true'),
                ('gitlab-change-payloads.json','"paused": true','"paused": false'),
                ('candidate.gitlab-ci.yml','when: manual','when: on_success'),
            ]
            for filename,before,after in mutations:
                with self.subTest(filename=filename,before=before):
                    path=out/filename; raw=path.read_text(); self.assertIn(before,raw)
                    path.write_text(raw.replace(before,after,1))
                    with self.assertRaises(AssertionError): verifier.verify(out)
                    path.write_text(raw)

    def test_rendered_build_needs_preserve_existing_experience_gate_contract(self):
        import re
        with tempfile.TemporaryDirectory(prefix='runner-experience-contract-',dir=os.environ['TMPDIR']) as tmp:
            subprocess.run([sys.executable,str(HERE/'render_candidate.py'),'--out',tmp],check=True,capture_output=True)
            raw=(Path(tmp)/'candidate.gitlab-ci.yml').read_text()
            block_match=re.search(r'^build-images:\n(.*?)(?=^\S)',raw,re.M|re.S)
            assert block_match is not None
            match=re.search(r'^  needs: (.+)$',block_match.group(1),re.M)
            self.assertIsNotNone(match,'existing fail-closed experience gate requires inline needs')
            assert match is not None
            self.assertEqual(json.loads(match.group(1)),self.ci['build-images']['needs'])
            self.assertIn('"experience-gate"',match.group(1))

    def test_shell_syntax(self):
        subprocess.run(['sh','-n',str(HERE/'build-rootless.sh')],check=True)

class MetadataContract(unittest.TestCase):
    def setUp(self):
        self.good={'containerimage.digest':'sha256:'+'a'*64,'containerimage.descriptor':{'digest':'sha256:'+'a'*64,'mediaType':'application/vnd.oci.image.manifest.v1+json'}}
    def test_valid(self): self.assertEqual(d.digest_from_metadata(json.dumps(self.good)),'sha256:'+'a'*64)
    def test_config_id_is_not_digest(self):
        v=copy.deepcopy(self.good); v['containerimage.config.digest']=v.pop('containerimage.digest')
        with self.assertRaises(ValueError): d.digest_from_metadata(json.dumps(v))
    def test_descriptor_mismatch(self):
        v=copy.deepcopy(self.good); v['containerimage.descriptor']['digest']='sha256:'+'b'*64
        with self.assertRaises(ValueError): d.digest_from_metadata(json.dumps(v))
    def test_digest_mutations(self):
        for value in ('latest','sha256:'+'A'*64,'sha256:'+'a'*63,'sha256:'+'a'*64+'\n',None):
            v=copy.deepcopy(self.good); v['containerimage.digest']=value
            with self.subTest(value=value),self.assertRaises(ValueError): d.digest_from_metadata(json.dumps(v))
    def test_duplicate_key(self):
        with self.assertRaises(ValueError): d.digest_from_metadata('{"containerimage.digest":"a","containerimage.digest":"b"}')
    def test_invalid_media_type(self):
        self.good['containerimage.descriptor']['mediaType']='application/vnd.oci.image.config.v1+json'
        with self.assertRaises(ValueError): d.digest_from_metadata(json.dumps(self.good))
    def test_size_budget(self):
        with self.assertRaises(ValueError): d.digest_from_metadata(' '*(1024*1024+1))

if __name__=='__main__': unittest.main(verbosity=2)
