"""File storage ordering: unpublished staging → durable unique object → DB commit.

A commit error may be an unknown outcome; never compensate by unlinking a final
object. Such failures leave an explicit log receipt for conservative reconciliation.
"""
import os
import tempfile


def publish(storage, object_id, data):
    storage.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.notes-upload-', dir=storage, delete=False) as stream:
            temporary = stream.name
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # Hard link publishes without replacing any prior generation/key.
        os.link(temporary, storage / str(object_id))
        os.unlink(temporary)
        temporary = None
        directory = os.open(storage, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None:
            os.unlink(temporary)
