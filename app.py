import zlib, base64
from p1 import DATA as A
from p2 import DATA as B
exec(compile(zlib.decompress(base64.b64decode(A + B)).decode(), 'app.py', 'exec'), globals())
