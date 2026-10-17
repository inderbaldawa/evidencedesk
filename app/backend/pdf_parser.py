"""One bounded PDF parser process. No network or model operations."""
import json
import sys
import resource

def main():
    resource.setrlimit(resource.RLIMIT_CPU,(10,10))
    # Linux/Cloud Run enforces the address-space cap. macOS RLIMIT_AS is unreliable.
    if sys.platform.startswith('linux'):
        resource.setrlimit(resource.RLIMIT_AS,(384*1024*1024,384*1024*1024))
    from .documents import parse_pdf,MAX_BYTES
    data=sys.stdin.buffer.read(MAX_BYTES+1)
    result={'error':'PDF exceeds 5 MB.'} if len(data)>MAX_BYTES else parse_pdf(data)
    sys.stdout.write(json.dumps(result))

if __name__=='__main__':main()
