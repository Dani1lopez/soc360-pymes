// Política de refresco de los escaneos (decisión D5 del estudio F4). Vive en
// funciones puras para poder probarla sin temporizadores ni React.

export const SCAN_POLL_BASE_MS = 5_000;
export const SCAN_POLL_MAX_MS = 30_000;

const ACTIVE_STATUSES = new Set(["pending", "running"]);

/** Un escaneo está abierto mientras el backend pueda cambiarlo solo. */
export function isActiveScan(status: string): boolean {
  return ACTIVE_STATUSES.has(status);
}

/** ¿Hay algún escaneo abierto en esta página? */
export function hasActiveScans(scans: { status: string }[] | undefined): boolean {
  return (scans ?? []).some((scan) => isActiveScan(scan.status));
}

/** Backoff exponencial con techo: 5 s, 10 s, 20 s, 30 s, 30 s… */
export function nextPollDelay(current: number): number {
  return Math.min(current * 2, SCAN_POLL_MAX_MS);
}

/**
 * Intervalo de `refetchInterval` para la página actual: `false` detiene el
 * sondeo en estado terminal. Las pestañas ocultas ya no sondean porque
 * `refetchIntervalInBackground` se deja en su valor por defecto (`false`).
 */
export function pollingInterval(
  scans: { status: string }[] | undefined,
  current: number,
): number | false {
  return hasActiveScans(scans) ? current : false;
}
