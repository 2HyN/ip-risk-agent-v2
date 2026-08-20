export interface LocalArtifactIdentity {
  deviceId: string;
  mountId: string;
  relativePath: string;
}

const SEPARATOR = "\u001f";

export function decodeLocalArtifactId(sourceArtifactId: string): LocalArtifactIdentity {
  let raw: string;
  try {
    raw = Buffer.from(sourceArtifactId, "base64url").toString("utf8");
  } catch {
    throw new Error("malformed local artifact identity");
  }
  const parts = raw.split(SEPARATOR);
  if (parts.length !== 3 || parts.some((part) => part.length === 0)) {
    throw new Error("malformed local artifact identity");
  }
  const [deviceId, mountId, relativePath] = parts;
  if (deviceId === undefined || mountId === undefined || relativePath === undefined) {
    throw new Error("malformed local artifact identity");
  }
  return { deviceId, mountId, relativePath };
}
