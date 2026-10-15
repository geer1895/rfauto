import base64
import sys

open(sys.argv[1], "wb").write(base64.b64decode(sys.argv[2]))
print("WROTE", len(base64.b64decode(sys.argv[2])), "->", sys.argv[1])
