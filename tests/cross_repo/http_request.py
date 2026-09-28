"""Bounded HTTP bridge invoked by docker exec inside the private test network."""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

request = json.loads(sys.argv[1])
url = urllib.parse.urlsplit(request["url"])
if (
    url.scheme != "http"
    or url.netloc not in {"api:8000", "edge:8091", "proxy:8090"}
    or request["method"] not in {"GET", "POST"}
    or len(request["body"]) > 65536
):
    raise SystemExit("invalid internal test request")
client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
# Scheme and exact internal authority are allowlisted above.
message = urllib.request.Request(  # noqa: S310
    request["url"],
    data=request["body"].encode() if request["body"] else None,
    headers={"Content-Type": "application/json"},
    method=request["method"],
)
try:
    response = client.open(message, timeout=6)
except urllib.error.HTTPError as error:
    response = error
with response:
    body = response.read(1048577)
    if len(body) > 1048576:
        raise SystemExit("response limit exceeded")
    print(json.dumps({"status": response.status, "body": body.decode()}))
