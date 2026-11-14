import json, sys, os

path = sys.argv[1]
print("size:", os.path.getsize(path))
d = json.load(open(path, encoding="utf-8"))
print("type:", type(d).__name__)
if isinstance(d, dict):
    print("keys:", list(d))
    for k, v in d.items():
        print(f"  {k}: {type(v).__name__} len={len(v) if hasattr(v, '__len__') else '?'}")
elif isinstance(d, list):
    print("entries:", len(d))
    print("first keys:", list(d[0]) if isinstance(d[0], dict) else type(d[0]).__name__)
