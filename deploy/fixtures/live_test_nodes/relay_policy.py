"""Fail-closed TLS ClientHello SNI gate; never decrypts HTTP or changes trust."""
HOST = b'stella-dev.p.xiya.live'
MAX_HELLO = 8192

def allowed_client_hello(record):
    try:
        if len(record) < 9 or record[0] != 22 or record[5] != 1:
            return False
        size = int.from_bytes(record[3:5], 'big')
        if size > MAX_HELLO or len(record) != size + 5:
            return False
        length = int.from_bytes(record[6:9], 'big')
        body = record[9:]
        if len(body) != length:
            return False
        pos = 34
        pos += 1 + body[pos]  # session id
        pos += 2 + int.from_bytes(body[pos:pos+2], 'big')  # cipher suites
        pos += 1 + body[pos]  # compression methods
        total = int.from_bytes(body[pos:pos+2], 'big'); pos += 2
        if pos + total != len(body):
            return False
        end = pos + total
        while pos + 4 <= end:
            kind = int.from_bytes(body[pos:pos+2], 'big')
            length = int.from_bytes(body[pos+2:pos+4], 'big'); pos += 4
            value = body[pos:pos+length]; pos += length
            if pos > end:
                return False
            if kind == 0:
                # Exactly one DNS server name; no duplicate/ambiguous names.
                return (len(value) == len(HOST) + 5 and value[2] == 0 and
                        int.from_bytes(value[:2], 'big') == len(value)-2 and
                        int.from_bytes(value[3:5], 'big') == len(HOST) and value[5:] == HOST)
        return False
    except (IndexError, TypeError):
        return False


def read_client_hello(sock):
    def exact(size):
        data = b''
        while len(data) < size:
            chunk = sock.recv(size-len(data))
            if not chunk:
                raise OSError('incomplete client hello')
            data += chunk
        return data
    sock.settimeout(3)
    header = exact(5)
    size = int.from_bytes(header[3:5], 'big')
    if size > MAX_HELLO:
        raise OSError('oversized client hello')
    record = header + exact(size)
    if not allowed_client_hello(record):
        raise OSError('only exact preview TLS SNI is permitted')
    sock.settimeout(5)
    return record
