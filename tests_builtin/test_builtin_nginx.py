"""Exercise candidate sub_filter against real nginx + loopback upstream."""
import gzip
import subprocess
import os
from pathlib import Path
import httpx
from fastapi import FastAPI, Request
from starlette.responses import Response
from tests_builtin.test_builtin_browser import local_server
from app.services import builtin_injection as builtin


def test_nginx_candidate_only_html_keeps_native_api_csp_compressed_asset(tmp_path):
    from socket import socket
    snippets=builtin.gallery_nginx_snippets()
    upstream=FastAPI()
    @upstream.get('/{path:path}')
    def get(path:str, request:Request):
        if path=='asset.js':
            body=b'window.upstreamAsset=true;';accept=request.headers.get('accept-encoding','')
            return Response(gzip.compress(body) if 'gzip' in accept else body,media_type='application/javascript',headers={'content-encoding':'gzip'} if 'gzip' in accept else {})
        if path=='api/mobile': return Response(b'{"mobile":"original"}',media_type='application/json',headers={'etag':'native-v1'})
        return Response(b'<html><head></head><body>gallery</body></html>',media_type='text/html',headers={'content-security-policy':"default-src 'self'; object-src 'none'",'x-test-encoding':request.headers.get('accept-encoding','')})
    with local_server(upstream) as upstream_origin:
        sock=socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
        scratch=Path(os.environ['TMPDIR']);case=scratch/('builtin-nginx-'+str(port));case.mkdir()
        conf=case/'nginx.conf'
        config='worker_processes 1;\npid '+str(case/'nginx.pid')+';\nerror_log '+str(case/'error.log')+';\nevents{worker_connections 64;}\nhttp{access_log off;'+snippets['http']+'server{listen 127.0.0.1:'+str(port)+';location /{proxy_pass '+upstream_origin+';'+snippets['location']+'}}}'
        # Test-owned scratch config, never a system/production nginx path.
        conf.write_text(config)
        check=subprocess.run(['nginx','-t','-p',str(case)+'/', '-c',str(conf)],capture_output=True,text=True)
        assert check.returncode==0,check.stderr
        proc=subprocess.Popen(['nginx','-p',str(case)+'/', '-c',str(conf),'-g','daemon off;'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            import time
            for _ in range(100):
                try:
                    r=httpx.get(f'http://127.0.0.1:{port}/',headers={'Accept':'text/html','Accept-Encoding':'gzip'})
                    break
                except httpx.ConnectError: time.sleep(.02)
            else: raise AssertionError('local nginx did not start')
            assert r.text.count('/integration-assets/gallery.js')==1
            assert 'data-stella-gallery-base' not in r.text
            assert '<style' not in r.text
            assert r.headers['content-security-policy']=="default-src 'self'; object-src 'none'"
            assert r.headers['x-test-encoding']==''
            with httpx.stream('GET',f'http://127.0.0.1:{port}/asset.js',headers={'Accept':'*/*','Accept-Encoding':'gzip'}) as r:
                assert r.headers['content-encoding']=='gzip'
                assert gzip.decompress(b''.join(r.iter_raw()))==b'window.upstreamAsset=true;'
            api=httpx.get(f'http://127.0.0.1:{port}/api/mobile')
            assert api.content==b'{"mobile":"original"}' and api.headers['etag']=='native-v1'
        finally:
            proc.terminate();proc.communicate(timeout=5)
