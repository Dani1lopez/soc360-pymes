import { useParams } from "@tanstack/react-router";
import { ScanDetailPage } from "./scan-detail-page";

/**
 * Adaptador de la ruta de detalle: resuelve el parámetro tipado y se lo pasa a
 * la página, que así se puede probar con un id cualquiera. Vive aquí y no en el
 * fichero de ruta porque ese fichero solo puede exportar la ruta (react-refresh).
 */
export function ScanDetailRoute() {
  const { id } = useParams({ from: "/_authenticated/_reader/scans/$id" });
  return <ScanDetailPage scanId={id} />;
}
