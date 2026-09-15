import io

def test_short_reads_are_reassembled_into_fixed_chunks(db):
    from app.services.blob_store import put,read_range,CHUNK_SIZE
    class ShortReader(io.BytesIO):
        def read(self,n=-1):return super().read(min(n,13))
    payload=b'x'*(CHUNK_SIZE+73)
    put(db,'short/read',ShortReader(payload),'text/plain',len(payload))
    assert b''.join(read_range(db,'short/read',0,len(payload)))==payload

# Reuse this module's isolated fixture without importing real data.
from tests_ha.test_blob_store import db
