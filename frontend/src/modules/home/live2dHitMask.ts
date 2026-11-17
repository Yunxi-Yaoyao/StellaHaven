// A native hit surface, derived from the same framebuffer as the visible-content zones.
// Rectangular row runs retain holes between hair/arms. No click replay or rectangular shield.
export function createLive2dHitMask(pixels: Uint8Array, width: number, height: number, resolution: number) {
  const paths: string[] = [];
  let minX = width, minY = height, maxX = 0, maxY = 0;
  for (let y = 0; y < height; y++) {
    const row = (height - 1 - y) * width * 4;
    let start = -1;
    for (let x = 0; x <= width; x++) {
      const opaque = x < width && pixels[row + x * 4 + 3]! > 60;
      if (opaque && start < 0) start = x;
      if (!opaque && start >= 0) {
        paths.push(`M${start / resolution} ${y / resolution}h${(x - start) / resolution}v${1 / resolution}h${(start - x) / resolution}Z`);
        minX = Math.min(minX, start); maxX = Math.max(maxX, x);
        minY = Math.min(minY, y); maxY = Math.max(maxY, y + 1);
        start = -1;
      }
    }
  }
  return {
    path: paths.length ? `path('${paths.join('')}')` : 'inset(100%)',
    box: { x: minX / resolution, y: minY / resolution, w: (maxX - minX) / resolution, h: (maxY - minY) / resolution },
    contains(x: number, y: number) {
      const px = Math.floor(x * resolution), py = Math.floor(y * resolution);
      return px >= 0 && px < width && py >= 0 && py < height && pixels[((height - 1 - py) * width + px) * 4 + 3]! > 60;
    },
  };
}
