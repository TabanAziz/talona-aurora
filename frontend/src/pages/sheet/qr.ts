import qrcode from "qrcode-generator";

/** The QR specification asks for a light border of four modules so a scanner can find the code's edges. */
export const QUIET_ZONE = 4;

export interface QrCode {
  /** Modules per side of the code itself, without the quiet zone. */
  modules: number;
  /** Modules per side of the drawing, the viewBox, including the quiet zone on both sides. */
  size: number;
  /** One path that draws every dark module, offset by the quiet zone. */
  path: string;
}

/** A QR code drawn in this browser: the label works with no network and no outside service. */
export function qrCode(value: string): QrCode {
  const code = qrcode(0, "M");
  code.addData(value);
  code.make();
  const modules = code.getModuleCount();
  const size = modules + QUIET_ZONE * 2;
  let path = "";
  for (let row = 0; row < modules; row += 1) {
    for (let col = 0; col < modules; col += 1) {
      if (code.isDark(row, col)) path += `M${col + QUIET_ZONE} ${row + QUIET_ZONE}h1v1h-1z`;
    }
  }
  return { modules, size, path };
}
