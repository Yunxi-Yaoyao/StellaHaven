#!/usr/bin/env python3
"""Validate BuildKit exporter identity, not daemon image/config IDs."""
import json
import os
from pathlib import Path
import re

REGISTRY='gitlab-registry.xiya.live/yaoyao/stellahaven'

def digest_from_metadata(raw):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result: raise ValueError('duplicate metadata key')
            result[key]=value
        return result
    if len(raw)>1024*1024: raise ValueError('metadata exceeds 1MiB')
    metadata=json.loads(raw,object_pairs_hook=unique)
    value=metadata.get('containerimage.digest')
    if not isinstance(value,str) or not re.fullmatch('sha256:[0-9a-f]{64}',value):
        raise ValueError('immutable registry exporter digest required')
    descriptor=metadata.get('containerimage.descriptor')
    if not isinstance(descriptor,dict) or descriptor.get('digest')!=value:
        raise ValueError('exporter descriptor/digest mismatch')
    if descriptor.get('mediaType') not in {'application/vnd.oci.image.manifest.v1+json','application/vnd.oci.image.index.v1+json','application/vnd.docker.distribution.manifest.v2+json','application/vnd.docker.distribution.manifest.list.v2+json'}:
        raise ValueError('unsupported image descriptor')
    return value

def main():
    if not re.fullmatch('[0-9a-f]{40}',os.environ.get('CI_COMMIT_SHA','')): raise ValueError('full source SHA required')
    image=digest_from_metadata(Path('.ci-build-receipt/app.json').read_text())
    digest_from_metadata(Path('.ci-build-receipt/pg.json').read_text())
    Path('production-image.env').write_text(f'STELLA_PRODUCTION_IMAGE={REGISTRY}@{image}\n')
if __name__=='__main__': main()
