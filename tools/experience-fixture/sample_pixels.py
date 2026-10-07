"""Sample actual composited screenshot pixels, not computed-style evidence."""
import json
import sys
from PIL import Image
image = Image.open(sys.argv[1]).convert('RGB')
points = json.loads(sys.argv[2])
pixels = []
for x, y in points:
    pixel = image.getpixel((round(x), round(y)))
    assert isinstance(pixel, tuple)
    pixels.append(list(pixel))
print(json.dumps({'size': image.size, 'pixels': pixels}))
