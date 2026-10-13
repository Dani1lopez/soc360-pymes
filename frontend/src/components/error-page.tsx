import { useRouter } from "@tanstack/react-router";
import { Button } from "@/components/ui/button";

type ErrorPageProps = {
  title?: string;
  message?: string;
};

/**
 * Error de una sección: el `errorComponent` de un grupo de rutas. No cierra
 * sesión ni habla de la sesión (para eso está `SessionErrorPage`): solo permite
 * volver a intentar la ruta.
 */
export function ErrorPage({
  title = "No se pudo cargar esta sección",
  message = "Vuelve a intentarlo. Si el problema continúa, puede ser un fallo temporal del servidor.",
}: ErrorPageProps) {
  const router = useRouter();
  return (
    <main className="space-y-4 bg-background p-6 text-foreground">
      <h1 className="text-2xl font-semibold">{title}</h1>
      <p className="text-muted-foreground">{message}</p>
      <Button onClick={() => void router.invalidate()}>Reintentar</Button>
    </main>
  );
}
