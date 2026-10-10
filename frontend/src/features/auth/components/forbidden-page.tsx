import { Link } from "@tanstack/react-router";

export function ForbiddenPage() {
  return (
    <main>
      <h1>Acceso denegado</h1>
      <p>No tienes permisos para acceder a esta página.</p>
      <Link to="/">Volver al inicio</Link>
    </main>
  );
}
