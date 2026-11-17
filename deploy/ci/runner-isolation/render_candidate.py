#!/usr/bin/env python3
"""Offline candidate compiler. Writes files only, never contacts GitLab/Docker.
Current .gitlab-ci.yml is deliberately NOT changed or included by this package.
"""
import argparse
import copy
import difflib
import hashlib
import json
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[3]
BUILDKIT = 'moby/buildkit@sha256:65eca3c01cd1180c8f64565c4e3c5983af5145818b0e6fa863385d099eb73855'
RUNNER = 'gitlab/gitlab-runner@sha256:af0325804248aee217e055e753add77ccaaba6c8f5e2143b01108fd401165ef3'
LANES = ('test','build','deploy')
TESTS = ('backend-test','frontend-build','experience-gate','local-ha-contract')
DISABLED = ('deploy-k3s','local-ha-preview','local-ha-live-readonly')
BACKEND_BROWSER_SETUP = '. deploy/ci/runner-isolation/prepare-backend-browser.sh'
DOCUMENTATION_COMMAND = ('STELLA_CHROMIUM="$CHROME_BIN" STELLA_DOC_SKIP_BUILD=1 '
                         'STELLA_DOC_OUTPUT="$CI_PROJECT_DIR/frontend/node_modules/.cache/documentation" '
                         'npm run test:documentation')

def compile_ci(original):
    ci=copy.deepcopy(original)
    for name, job in ci.items():
        if not isinstance(job,dict) or 'stage' not in job: continue
        job['tags']=['stella-isolated-'+('test' if name in TESTS else 'build' if name=='build-images' else 'deploy')]
        job['cache']=[]
        job['before_script']=[x for x in job.get('before_script',[]) if x!='sh deploy/ci/local-registry-hosts.sh']
    # The Python image's Node executable alone cannot run ESM Playwright tests.
    # Keep this idempotent when compiling the already activated CI.
    backend_before = ci['backend-test']['before_script']
    if BACKEND_BROWSER_SETUP not in backend_before:
        backend_before.append(BACKEND_BROWSER_SETUP)
    # Reuse the same job's mandatory fresh build; never replace an old command.
    frontend_script = ci['frontend-build']['script']
    assert 'npm run build' in frontend_script, 'documentation gate requires the existing build'
    if DOCUMENTATION_COMMAND not in frontend_script:
        frontend_script.append(DOCUMENTATION_COMMAND)
    build=ci['build-images']
    build['image']={'name':BUILDKIT,'entrypoint':['']}
    build['timeout']='30m'
    build['before_script']=[original['build-images']['before_script'][0]]
    build['script']=['sh deploy/ci/runner-isolation/build-rootless.sh']
    build['artifacts']={'paths':['.ci-build-receipt/app.json','.ci-build-receipt/pg.json'],'expire_in':'7 days'}
    # Keep all test gates and feature/MR coverage; do not use legacy latest tags.
    ci['build-image-receipt']={
        'extends':'.branch-validation','stage':'build','timeout':'2m',
        'tags':['stella-isolated-test'], 'cache':[],
        'image':original['backend-test']['image'],
        'needs':[{'job':'build-images','artifacts':True}],
        'before_script':[original['build-images']['before_script'][0]],
        'script':['python3 deploy/ci/runner-isolation/image_receipt.py'],
        'artifacts':{'reports':{'dotenv':'production-image.env'},'paths':['production-image.env'],'expire_in':'7 days'}}
    prod=ci['local-ha-production-app']
    prod['needs']=[{'job':'build-image-receipt','artifacts':True}]
    prod['rules']=[{'if':'$CI_COMMIT_BRANCH == "master" && $CI_COMMIT_REF_PROTECTED == "true" && $STELLA_DEPLOY_TARGET == "local-ha" && $STELLA_RUNNER_ISOLATION_READY == "true"', 'when':'manual','allow_failure':False},{'when':'never'}]
    prod['manual_confirmation']='Deploy the separately approved immutable image after edge-first and runner-isolation acceptance?'
    for name in DISABLED: ci[name]['rules']=[{'when':'never'}]
    # No READY value here: only an operator can enable the MANUAL entry after acceptance.
    return ci

def runner_toml(lane,ci):
    names=TESTS+('build-image-receipt',) if lane=='test' else ('build-images',) if lane=='build' else ('local-ha-production-app',)
    images=sorted({ci[n]['image'] if isinstance(ci[n]['image'],str) else ci[n]['image']['name'] for n in names})
    service=ci['backend-test']['services'][0]['name']
    docker={
        'image':images[0],'privileged':False,'services_privileged':False,
        'disable_cache':True,'volumes':[], 'devices':[],
        'network_mode':'stella-ci-'+lane, 'pull_policy':['always'], 'allowed_pull_policies':['always'],
        'allowed_images':images,'allowed_services':[service] if lane=='test' else ['invalid.invalid/no-services:denied'],
        'services_limit':1 if lane=='test' else 0,
        # Use canonical public DNS: private ingress is JWT-only and rejects new lanes.
        # Public HTTPS is already allowed; do not expand host ingress/ACLs.
        'dns':['223.5.5.5','119.29.29.29'],
        'memory':'3g' if lane!='deploy' else '512m','cpus':'2' if lane!='deploy' else '1',
        'pids_limit':512,'shm_size':268435456,'service_memory':'512m','service_cpus':'1',
        'security_opt':['seccomp=unconfined','systempaths=unconfined'] if lane=='build' else [],
        'services_security_opt':[],
        # Default Docker capability profile retained for package/sudo fixtures;
        # build user is enforced by manager, cannot be overridden by job YAML.
        'cap_drop':['NET_RAW'], 'user':'1000:1000' if lane=='build' else '0',
        'allowed_users':['1000:1000'] if lane=='build' else ['0'],
    }
    lines=['concurrent = 1','check_interval = 3','','[[runners]]',f'name = "stella-isolated-{lane}"',
           'url = "https://gitlab.xiya.live"','clone_url = "https://gitlab.xiya.live"',
           f'token = "<OPERATOR_RUNNER_AUTH_TOKEN_{lane.upper()}>"','executor = "docker"','limit = 1',
           'request_concurrency = 1','output_limit = 16384','', '[runners.feature_flags]',
           'FF_NETWORK_PER_BUILD = false','FF_DISABLE_UMASK_FOR_DOCKER_EXECUTOR = true','', '[runners.docker]']
    lines += [k+' = '+json.dumps(v) for k,v in docker.items()]
    return '\n'.join(lines)+'\n'

def compose():
    # Explicit profiles prevent accidental `compose up` enabling any new manager.
    services={}; networks={}
    for i,lane in enumerate(LANES):
        name='stella-ci-'+lane
        services['runner-'+lane]={
            'image':RUNNER,'profiles':['operator-approved-isolation'],
            'restart':'no','read_only':True,'privileged':False,
            'security_opt':['no-new-privileges:true'], 'cap_drop':['ALL'],
            'mem_limit':'256m','cpus':0.5,'pids_limit':128,
            'tmpfs':['/tmp:rw,noexec,nosuid,nodev,size=16m'],
            # Manager is the trusted host-control plane; NEVER propagate these
            # mounts into runners.docker.volumes. Config token stays outside Git.
            'volumes':[
                {'type':'bind','source':f'/opt/stella-ci-runners/{lane}','target':'/etc/gitlab-runner','read_only':False},
                {'type':'bind','source':'/var/run/docker.sock','target':'/var/run/docker.sock','read_only':False}],
            # Canonical public HTTPS; no private ingress/ACL expansion.
            'dns':['223.5.5.5','119.29.29.29'],
            'networks':[name], 'command':['run','--config','/etc/gitlab-runner/config.toml']}
        networks[name]={'name':name,'driver':'bridge','enable_ipv6':False,
                        'driver_opts':{'com.docker.network.bridge.name':'stci-'+lane},
                        'ipam':{'config':[{'subnet':f'172.16.{240+i}.0/28','gateway':f'172.16.{240+i}.1'}]}}
    return {'name':'stella-ci-isolation','services':services,'networks':networks}

def registration():
    return {'not_executed':True,'project_update':{'endpoint':'PUT /api/v4/projects/2',
        'body':{'shared_runners_enabled':False,'group_runners_enabled':False,'auto_devops_enabled':False,
                'ci_pipeline_variables_minimum_override_role':'no_one_allowed'}},
        'new_runners':[{'endpoint':'POST /api/v4/user/runners','body':{
            'runner_type':'project_type','project_id':2,'description':'stella-isolated-'+lane,
            'tag_list':['stella-isolated-'+lane],'run_untagged':False,'locked':True,
            'access_level':'ref_protected' if lane=='deploy' else 'not_protected',
            'paused':True,'maximum_timeout':1200 if lane=='test' else 1800}} for lane in LANES],
        'readback':{'project_id':2,'old_runner_1_must_remain_unchanged':True,
                    'protected_master_merge_push_access_level':40,
                    'new_runner_ids':'<RETURNED_IDS_RECORDED_PRIVATELY_AFTER_APPROVAL>',
                    'production_variables':'retain protected+production scope; no value reads',
                    'ready_flag':'do not create/set until real runner acceptance; value is non-secret true, protected, scope=*'}}

def main():
    p=argparse.ArgumentParser(); p.add_argument('--out',type=Path,required=True); a=p.parse_args()
    raw=(ROOT/'.gitlab-ci.yml').read_text(); original=yaml.safe_load(raw); ci=compile_ci(original)
    a.out.mkdir(parents=True,exist_ok=True)
    rendered=yaml.safe_dump(ci,sort_keys=False,allow_unicode=True,width=120)
    # Preserve the existing experience gate's fail-closed inline-needs contract.
    # This changes serialization only; every mandatory dependency stays exact.
    needs=ci['build-images']['needs']
    block='  needs:\n'+''.join('  - '+name+'\n' for name in needs)
    assert rendered.count(block)==1, 'ambiguous build needs serialization'
    rendered=rendered.replace(block,'  needs: '+json.dumps(needs)+'\n',1)
    (a.out/'candidate.gitlab-ci.yml').write_text(rendered)
    (a.out/'candidate-ci.patch').write_text(''.join(difflib.unified_diff(raw.splitlines(True),rendered.splitlines(True),fromfile='a/.gitlab-ci.yml',tofile='b/.gitlab-ci.yml')))
    for lane in LANES: (a.out/f'{lane}.config.toml').write_text(runner_toml(lane,ci))
    (a.out/'managers.compose.yml').write_text(yaml.safe_dump(compose(),sort_keys=False))
    (a.out/'gitlab-change-payloads.json').write_text(json.dumps(registration(),indent=2)+'\n')
    (a.out/'source-binding.json').write_text(json.dumps({'baseline_ci_sha256':hashlib.sha256(raw.encode()).hexdigest(),
        'candidate_ci_sha256':hashlib.sha256(rendered.encode()).hexdigest(),'active_ci_modified':False,
        'helper_sha256':{f:hashlib.sha256((ROOT/'deploy/local-ha'/f).read_bytes()).hexdigest() for f in ['production_release.py','node_production.py']},
        'rootless_script_sha256':{f:hashlib.sha256((Path(__file__).parent/f).read_bytes()).hexdigest() for f in ['build-rootless.sh','prewarm-before-build.sh']},
        'backend_browser_sha256':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in ['deploy/ci/run-backend-shard.py','deploy/ci/runner-isolation/backend_dependencies.py','deploy/ci/runner-isolation/prepare-backend-browser.sh','deploy/ci/owned_inventory.py','deploy/ci/owned_pg.py','deploy/ci/owned_pytest.py','deploy/ci/run-owned-suite.py','deploy/ci/unified_ci.py','deploy/ci/unified-nodeids.json','deploy/ci/create-test-db.py','deploy/ci/owned-timings.json','deploy/ci/ci178-backend-timings.json','deploy/ci/ci182-backend-timings.json','deploy/ci/copy-capacity-timings.json','deploy/ci/capacity_successor.py','deploy/ci/v23-capacity-timings.json','deploy/ci/derivation-capacity-timings.json','deploy/ci/servers-audit-capacity-sources.json','qa/native_nav_pg_guard.py']},
        'frontend_browser_sha256':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in ['deploy/ci/runner-isolation/browser_dependencies.py']},
        'buildkit':BUILDKIT,'runner':RUNNER},indent=2)+'\n')
    print(json.dumps({'status':'generated-offline','output':str(a.out),'active_ci_modified':False}))
if __name__=='__main__': main()
