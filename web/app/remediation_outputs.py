"""Strict JSON extraction without inventing repairs or accepting ambiguous plans."""
import json
import re


def _single_object(text):
    decoder = json.JSONDecoder()
    objects = []
    position = 0
    while True:
        start = text.find('{', position)
        if start < 0:
            break
        try:
            value, end = decoder.raw_decode(text, start)
        except ValueError as error:
            # Do not reinterpret a truncated JSON plan as one of its children.
            following = text[start + 1:].lstrip()
            if not following or following[0] in {'"', "'", '}'}:
                raise ValueError('Model response contains an incomplete or invalid JSON object.') from error
            position = start + 1
            continue
        objects.append(value)
        position = end
    if len(objects) != 1:
        raise ValueError('Model response must contain one unambiguous complete JSON object.')
    return objects[0]


def parse_json_response(content):
    try:
        result = json.loads(content)
    except (ValueError, TypeError):
        text = str(content or '')
        stripped = text.lstrip()
        if stripped.startswith(('[', '"')):
            raise ValueError('Model response is not complete valid JSON.')
        if stripped.startswith('{'):
            try:
                json.JSONDecoder().raw_decode(stripped)
            except ValueError as error:
                raise ValueError('Model response is not complete valid JSON.') from error
        fences = re.findall(r'```(?:json)?[ \t]*\r?\n(.*?)```', text, flags=re.S | re.I)
        # Explicit JSON fences separate the plan from quoted CSS in the prose.
        if fences:
            if len(fences) != 1:
                raise ValueError('Model response contains ambiguous JSON blocks.')
            fenced = fences[0].strip()
            try:
                result = json.loads(fenced)
            except json.JSONDecodeError:
                result, end = json.JSONDecoder().raw_decode(fenced)
                # One surplus closing brace after a complete fenced object has
                # no fields. Never repair truncation or discard a second value.
                if not isinstance(result, dict) or fenced[end:].strip() != '}':
                    raise ValueError('Model response contains an invalid JSON block.')
        else:
            result = _single_object(text)
    if not isinstance(result, dict):
        raise ValueError('Model response must be a JSON object')
    return result
