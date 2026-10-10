import { useState, type FormEvent } from "react";
import { ShieldCheck } from "lucide-react";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { isApiError } from "@/api/errors";
import { Button } from "@/components/ui/button";
import { useCountdown } from "@/lib/use-countdown";
import { sanitizeRedirect } from "../lib/guards";
import { useLogin } from "../hooks/use-login";

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const mutation = useLogin();
  const countdown = useCountdown();
  const search = useSearch({ from: "/login" });
  const navigate = useNavigate();
  const error = mutation.error;
  const fields = isApiError(error) && error.kind === "validation" ? error.fieldErrors : [];
  const emailError = fields
    .filter((field) => field.field === "email")
    .map((field) => field.message)
    .join(" ");
  const passwordError = fields
    .filter((field) => field.field === "password")
    .map((field) => field.message)
    .join(" ");
  let message = error ? "No se pudo iniciar sesión." : null;
  if (isApiError(error)) {
    message = error.kind === "validation" ? "Revisa los campos del formulario." : error.message;
    if (error.kind === "rate_limited" && error.retryAfterSeconds !== null) {
      // Mientras corre la cuenta atrás se enseña el tiempo que queda de verdad.
      const remaining = countdown.remaining > 0 ? countdown.remaining : error.retryAfterSeconds;
      message = `Demasiados intentos. Vuelve a intentarlo en ${remaining} s.`;
    }
  }
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mutation.isPending) return;
    mutation.mutate(
      { email, password },
      {
        onError: (cause) => {
          // El 429 trae cuántos segundos hay que esperar: el botón se bloquea
          // hasta que pasen, en lugar de fallar otra vez contra el rate limit.
          if (
            isApiError(cause) &&
            cause.kind === "rate_limited" &&
            cause.retryAfterSeconds !== null
          ) {
            countdown.start(cause.retryAfterSeconds);
          }
        },
        onSuccess: () => {
          void navigate({ href: sanitizeRedirect(search.redirect) });
        },
      },
    );
  }
  const inputClass =
    "w-full rounded-md border border-input bg-background px-3 py-2 text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-6 text-foreground">
      <section
        aria-labelledby="login-heading"
        className="w-full max-w-sm rounded-lg border border-border bg-card p-6 shadow-sm"
      >
        <p className="mb-6 flex items-center gap-2 text-lg font-semibold tracking-tight">
          <ShieldCheck aria-hidden="true" className="size-7 text-primary" />
          SOC360 PyMEs
        </p>
        <h1 id="login-heading" className="mb-6 text-2xl font-semibold">
          Iniciar sesión
        </h1>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-2">
            <label htmlFor="login-email">Correo electrónico</label>
            <input
              id="login-email"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              aria-invalid={emailError ? true : undefined}
              aria-describedby={emailError ? "login-email-error" : undefined}
              className={inputClass}
            />
            {emailError && (
              <p id="login-email-error" className="text-sm text-destructive">
                {emailError}
              </p>
            )}
          </div>
          <div className="space-y-2">
            <label htmlFor="login-password">Contraseña</label>
            <input
              id="login-password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              aria-invalid={passwordError ? true : undefined}
              aria-describedby={passwordError ? "login-password-error" : undefined}
              className={inputClass}
            />
            {passwordError && (
              <p id="login-password-error" className="text-sm text-destructive">
                {passwordError}
              </p>
            )}
          </div>
          {message && (
            <p role="alert" className="text-sm text-destructive">
              {message}
            </p>
          )}
          <Button
            type="submit"
            disabled={mutation.isPending || countdown.remaining > 0}
            className="w-full"
          >
            {mutation.isPending
              ? "Entrando…"
              : countdown.remaining > 0
                ? `Espera ${countdown.remaining} s`
                : "Entrar"}
          </Button>
        </form>
      </section>
    </main>
  );
}
