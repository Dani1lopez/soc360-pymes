import { useRouter } from "@tanstack/react-router";
import { Button } from "@/components/ui/button";
import { useSignOut } from "../hooks/use-sign-out";

export function SessionErrorPage() {
  const router = useRouter();
  const signOut = useSignOut();
  return (
    <main className="space-y-4 bg-background p-6 text-foreground">
      <h1 className="text-2xl font-semibold">No se pudo cargar tu sesión</h1>
      <p className="text-muted-foreground">
        Intenta nuevamente o cierra la sesión para volver a iniciar.
      </p>
      <div className="flex gap-3">
        <Button onClick={() => void router.invalidate()}>Reintentar</Button>
        <Button variant="outline" disabled={signOut.isPending} onClick={() => signOut.mutate()}>
          Cerrar sesión
        </Button>
      </div>
    </main>
  );
}
