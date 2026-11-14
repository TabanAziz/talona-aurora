export interface Vector3Like { x: number; y: number; z: number }

/** Fit every box corner to the perspective frustum, including its depth toward the camera. */
export function perspectiveFitDistance(corners: Vector3Like[], target: Vector3Like, backward: Vector3Like, verticalFov: number, aspect: number): number {
  const length = Math.hypot(backward.x, backward.y, backward.z) || 1;
  const back = { x: backward.x / length, y: backward.y / length, z: backward.z / length };
  const horizontal = Math.hypot(back.x, back.z);
  const right = horizontal > 1e-9 ? { x: back.z / horizontal, y: 0, z: -back.x / horizontal } : { x: 1, y: 0, z: 0 };
  const up = { x: back.y * right.z, y: back.z * right.x - back.x * right.z, z: -back.y * right.x };
  const tanVertical = Math.tan(verticalFov * Math.PI / 360);
  const tanHorizontal = tanVertical * Math.max(aspect, 0.05);
  let distance = 0.1;
  for (const point of corners) {
    const x = point.x - target.x, y = point.y - target.y, z = point.z - target.z;
    const depth = x * back.x + y * back.y + z * back.z;
    distance = Math.max(distance,
      Math.abs(x * right.x + z * right.z) / tanHorizontal + depth,
      Math.abs(x * up.x + y * up.y + z * up.z) / tanVertical + depth);
  }
  return distance * 1.14;
}
