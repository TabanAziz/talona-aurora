/**
 * The address a printed label points at.
 *
 * A phone scans the label away from the laptop that printed it, so the address has to be absolute. When the deploy
 * knows its public URL it wins; otherwise the origin of the page that printed the label is the best guess.
 *
 * @param {string} sheet
 * @param {string} revision
 * @param {string | undefined} publicUrl
 * @param {string} origin
 * @returns {string}
 */
export function labelUrl(sheet, revision, publicUrl, origin) {
  const base = (publicUrl || origin).replace(/\/+$/, "");
  return `${base}/sheet/${encodeURIComponent(sheet)}/${encodeURIComponent(revision)}`;
}
