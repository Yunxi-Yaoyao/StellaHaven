import os
from pathlib import Path
import subprocess


def test_private_production_build_and_types(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    node = os.environ.get('STELLA_CI_NODE', '/root/.local/share/fnm/node-versions/v23.11.1/installation/bin/node')
    evidence = Path(os.environ['NODE_FILES_EVIDENCE'])
    environment = {k:v for k,v in os.environ.items() if k != 'NODE_ENV'}
    commands = [
        [node, str(repo / 'frontend/node_modules/vue-tsc/bin/vue-tsc.js'), '-b', str(repo / 'frontend/tsconfig.json')],
        [node, str(repo / 'tests_node_files/build.mjs'), str(tmp_path / 'built')],
    ]
    logs=[]
    for argv in commands:
        result = subprocess.run(argv, cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=180)
        logs.append({'argv': argv, 'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
        import json
        (evidence / 'F2-build-log.json').write_text(json.dumps(logs, ensure_ascii=False, indent=2))
        assert result.returncode == 0, result.stdout + result.stderr
