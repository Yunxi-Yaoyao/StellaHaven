"""Host facade must delegate to instance installer; no actual host mutations."""
import ast
from pathlib import Path
from unittest.mock import patch
import pytest
ROOT = Path(__file__).resolve().parents[1]

def host():
    tree = ast.parse((ROOT/'app/services/host.py').read_text())
    functions = [n for n in tree.body if
                 (isinstance(n, ast.FunctionDef) and n.name in ('supports_local_install', 'install_host', 'uninstall_host'))
                 or (isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'HOST_INSTANCE' for t in n.targets))]
    import subprocess
    from types import SimpleNamespace
    # Only OS discovery is synthetic; execute all real installer admission code.
    class HostPath(type(Path())):
        def exists(self):
            if str(self) in ('/.dockerenv', '/run/.containerenv'):
                return False
            return super().exists()
    ns = dict(__file__=str(ROOT/'app/services/host.py'), Path=HostPath,
              os=SimpleNamespace(environ={}, geteuid=lambda: 0), subprocess=subprocess,
              platform=SimpleNamespace(system=lambda: 'Linux'),
              shutil=SimpleNamespace(which=lambda name: '/fixture/bin/' + name))
    exec(compile(ast.Module(body=functions,type_ignores=[]),'real-host-facade','exec'),ns)
    return ns

def test_unscoped_host_uninstall_refuses_before_any_host_call():
    ns = host()
    with patch('subprocess.run',side_effect=AssertionError('host mutation')):
        with pytest.raises(ValueError,match='instance'): ns['uninstall_host']()

def test_local_install_uses_instance_script_with_token_only_in_environment():
    ns = host(); calls = []
    def run(argv,**kw):
        calls.append((argv,kw)); return type('Result',(),dict(returncode=0,stdout='安装完成：stella-agent-'+'a'*24,stderr=''))()
    with patch('subprocess.run',run): result = ns['install_host']('fixture-token','https://center.invalid')
    assert result['installed'] is True
    argv,kw = calls[0]
    assert argv[-1] == '--no-deps' and 'fixture-token' not in argv
    assert kw['env']['STELLA_TOKEN'] == 'fixture-token'
    assert str(ROOT/'agent/install.sh') in argv
