#!/usr/bin/env python3
"""Validate only generated proposal files; never read a live Runner config/token."""
import argparse
import hashlib
import importlib.util
import json
import runpy
from pathlib import Path
import tomllib
import yaml

def module(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
    assert spec and spec.loader
    m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
r=module('render_candidate'); d=module('image_receipt')

def verify(directory):
    directory=Path(directory)
    old=(r.ROOT/'.gitlab-ci.yml').read_bytes()
    binding=json.loads((directory/'source-binding.json').read_text())
    assert binding['baseline_ci_sha256']==hashlib.sha256(old).hexdigest(), 'source drift: rerender/review'
    expected=r.compile_ci(yaml.safe_load(old))
    raw=(directory/'candidate.gitlab-ci.yml').read_bytes()
    assert binding['candidate_ci_sha256']==hashlib.sha256(raw).hexdigest(), 'candidate hash mismatch'
    assert yaml.safe_load(raw)==expected, 'candidate differs from compiler contract'
    for lane in r.LANES:
        actual=tomllib.loads((directory/f'{lane}.config.toml').read_text())
        assert actual==tomllib.loads(r.runner_toml(lane,expected)), f'{lane} runner boundary drift'
    assert yaml.safe_load((directory/'managers.compose.yml').read_text())==r.compose(), 'manager/profile/network drift'
    assert json.loads((directory/'gitlab-change-payloads.json').read_text())==r.registration(), 'scope/runner eligibility drift'
    assert set(binding['rootless_script_sha256'])=={'build-rootless.sh','prewarm-before-build.sh'}, 'rootless script binding incomplete'
    for name,sha in binding['rootless_script_sha256'].items():
        assert hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()==sha, 'rootless script changed: rerender/review'
    assert set(binding.get('backend_browser_sha256', {}))=={'deploy/ci/run-backend-shard.py','deploy/ci/runner-isolation/backend_dependencies.py','deploy/ci/runner-isolation/prepare-backend-browser.sh','deploy/ci/owned_inventory.py','deploy/ci/owned_pg.py','deploy/ci/owned_pytest.py','deploy/ci/run-owned-suite.py','deploy/ci/unified_ci.py','deploy/ci/unified-nodeids.json','deploy/ci/create-test-db.py','deploy/ci/owned-timings.json','deploy/ci/ci178-backend-timings.json','deploy/ci/ci182-backend-timings.json','deploy/ci/copy-capacity-timings.json','deploy/ci/capacity_successor.py','deploy/ci/v23-capacity-timings.json','deploy/ci/derivation-capacity-timings.json','deploy/ci/servers-audit-capacity-sources.json','qa/native_nav_pg_guard.py'}, 'backend browser binding incomplete'
    for name,sha in binding['backend_browser_sha256'].items():
        assert hashlib.sha256((r.ROOT/name).read_bytes()).hexdigest()==sha, 'backend browser plan/setup changed: rerender/review'
    runpy.run_path(str(r.ROOT/'deploy/ci/capacity_successor.py'))['validate_sources'](r.ROOT)
    assert set(binding.get('frontend_browser_sha256', {}))=={'deploy/ci/runner-isolation/browser_dependencies.py'}, 'frontend browser binding incomplete'
    for name,sha in binding['frontend_browser_sha256'].items():
        assert hashlib.sha256((r.ROOT/name).read_bytes()).hexdigest()==sha, 'frontend browser setup changed: rerender/review'
    for name,sha in binding['helper_sha256'].items():
        assert hashlib.sha256((r.ROOT/'deploy/local-ha'/name).read_bytes()).hexdigest()==sha, 'strict controller changed'
    return {'status':'PASS','scope':'offline-proposal-only','online_runner_isolation_closed':False}

def main():
    p=argparse.ArgumentParser(); p.add_argument('config_dir',type=Path); p.add_argument('--smoke-metadata',type=Path); a=p.parse_args()
    receipt=verify(a.config_dir)
    if a.smoke_metadata:
        receipt['actual_oci_export_digest']=d.digest_from_metadata(a.smoke_metadata.read_text())
        receipt['registry_push_verified']=False
    print(json.dumps(receipt,indent=2))
if __name__=='__main__': main()
