"""Source gates supplement, never replace, native PowerShell fixture tests."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def test_windows_identity_and_tasks_are_instance_scoped():
    script = (ROOT/'agent/install.ps1').read_text()
    assert 'function Get-StellaInstallationBinding' in script
    assert '/agent/identity' in script
    assert "'StellaAgent-' + $binding.instance_id" in script
    assert "'StellaHardwareSensors-' + $binding.instance_id" in script
    assert "instance.json" in script
    assert 'source_sha256' in script and 'source_size' in script
    assert r'Global\StellaInstall-' in script

def test_runtime_uninstall_has_ownership_guard_and_no_unscoped_fallback():
    script = (ROOT/'agent/stella_agent.py').read_text()
    assert 'def _installation_binding(' in script
    assert 'def _instance_uninstall_argv(' in script
    assert 'STELLA_INSTANCE_MANIFEST' in script
    assert "unscoped uninstall refused" in script
