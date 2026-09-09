"""Destination scanner: preserve source formatting and never rewrite code spans."""
import re


def rewrite_markdown(body, resolve):
    protected = bytearray(len(body))
    fence = None
    offset = 0
    for line in body.splitlines(keepends=True):
        # Container prefixes are stripped only for detecting protected blocks.
        view = re.sub(r'^(?: {0,3}> ?)+', '', line)
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})', view)
        if fence:
            protected[offset:offset + len(line)] = b'\1' * len(line)
            if re.match(r'^ {0,3}' + re.escape(fence[0]) + '{' + str(len(fence)) + r',}\s*$', view):
                fence = None
        elif marker or view.startswith(('    ', '\t')):
            protected[offset:offset + len(line)] = b'\1' * len(line)
            if marker:
                fence = marker[1]
        offset += len(line)

    def escaped(i):
        start = i
        while i and body[i - 1] == '\\':
            i -= 1
        return (start - i) % 2 == 1

    # Match exact backtick runs, including spans crossing newlines.
    runs = list(re.finditer(r'`+', body))
    k = 0
    while k < len(runs):
        run = runs[k]
        if protected[run.start()] or escaped(run.start()):
            k += 1
            continue
        end = next((j for j in range(k + 1, len(runs))
                    if not protected[runs[j].start()] and len(runs[j][0]) == len(run[0])), None)
        if end is None:
            k += 1
        else:
            a, b = run.start(), runs[end].end()
            protected[a:b] = b'\1' * (b - a)
            k = end + 1

    def unescape(value):
        return re.sub(r'\\([!"#$%&\'()*+,\-./:;<=>?@\[\]\\^_`{|}~])', r'\1', value)

    def destination(start, inline):
        i = start
        while i < len(body) and body[i] in ' \t':
            i += 1
        if i == len(body):
            return None
        if body[i] == '<':
            end = i + 1
            while end < len(body) and body[end] not in '\r\n':
                if body[end] == '>' and not escaped(end):
                    return i + 1, end
                end += 1
            return None
        begin, depth = i, 0
        while i < len(body) and body[i] not in '\r\n':
            c = body[i]
            if c == '\\' and i + 1 < len(body):
                i += 2
                continue
            if c == '(':
                depth += 1
            elif c == ')':
                if depth == 0:
                    return (begin, i) if inline else None
                depth -= 1
            elif c in ' \t' and depth == 0:
                # Optional quoted title is not part of the destination.
                rest = body[i:]
                if re.match(r'''\s+["'][^\n]*["']\s*(?:\)|$)''', rest):
                    return begin, i
                if not inline:
                    return begin, i
            i += 1
        return (begin, i) if not inline and depth == 0 else None

    edits = []
    i = 0
    while i < len(body):
        if protected[i] or escaped(i) or body[i] != '[':
            i += 1
            continue
        if body.startswith('[[', i):
            end = body.find(']]', i + 2)
            if end != -1 and '\n' not in body[i:end] and not any(protected[i:end + 2]):
                raw, _, label = body[i + 2:end].partition('|')
                raw = raw.strip()
                result = resolve(raw)
                if result != raw:
                    label = (label or raw).replace('[', '\\[').replace(']', '\\]')
                    edits.append((i, end + 2, f'[{label}]({result})'))
                i = end + 2
                continue
        # Balanced labels, including escaped brackets and nested image labels.
        j, depth = i + 1, 1
        while j < len(body) and body[j] != '\n' and depth:
            if not escaped(j):
                if body[j] == '[': depth += 1
                elif body[j] == ']': depth -= 1
            j += 1
        if depth or j >= len(body):
            i += 1
            continue
        inline = body[j] == '('
        ref = body[j] == ':' and not body[body.rfind('\n', 0, i) + 1:i].strip()
        if inline or ref:
            bounds = destination(j + 1, inline)
            if bounds:
                a, b = bounds
                if b > a and not any(protected[i:b]):
                    raw = body[a:b]
                    result = resolve(unescape(raw))
                    if result != unescape(raw):
                        edits.append((a, b, result))
                    i = b
                    continue
        i = j
    output, cursor = [], 0
    for a, b, value in edits:
        output.extend((body[cursor:a], value))
        cursor = b
    output.append(body[cursor:])
    return ''.join(output)
