import os
import requests

def write_file(path, content):

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    with open(path,"w",encoding="utf-8") as f:
        f.write(content)

    return {"saved":path}


def http_get(url):

    r = requests.get(url,timeout=20)

    return {
        "status":r.status_code,
        "text":r.text[:20000]
    }


TOOLS = {
    "write_file":write_file,
    "http_get":http_get
}