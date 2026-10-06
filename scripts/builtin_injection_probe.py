"""Read only public HTML; output counts/hashes, never source/config/credentials.

Run from repo root: python -m scripts.builtin_injection_probe --site drive --url URL
No private upstream setting API, filesystem, backup or write is accessed.
"""
import argparse
import json
import httpx
from app.services.builtin_injection import probe_public_html


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site',choices=['drive','gallery'],required=True)
    parser.add_argument('--url',required=True)
    args=parser.parse_args()
    with httpx.Client(timeout=15,follow_redirects=False,trust_env=False) as client:
        with client.stream('GET',args.url,headers={'Accept':'text/html'}) as response:
            if response.status_code!=200 or response.headers.get('content-type','').split(';')[0]!='text/html':
                print(json.dumps({'site':args.site,'status':response.status_code,'html':False}));return 1
            content=bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content)>2*1024*1024: raise ValueError('public HTML exceeds 2MiB')
    report=probe_public_html(content.decode('utf-8'),args.site)
    print(json.dumps({'status':200,'readonly':True,'credentials_sent':False,**report},indent=2))
    return 0

if __name__=='__main__': raise SystemExit(main())
