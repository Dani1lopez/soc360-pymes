/**
 * Descarga un texto como fichero desde el navegador. El bearer vive en memoria,
 * así que un enlace directo a la API no sirve: el contenido se pide con
 * `apiFetch` y aquí solo se materializa la descarga.
 */
export function downloadTextFile(contents: string, filename: string, mimeType = "text/csv"): void {
  const blob = new Blob([contents], { type: `${mimeType};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
