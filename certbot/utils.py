import json


def json_dumpb(obj, **kwargs):
    return json.dumps(obj, **kwargs).encode('utf-8')
