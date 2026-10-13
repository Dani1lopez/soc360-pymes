import { useEffect, useState } from "react";

/**
 * Cuenta atrás en segundos para bloquear una acción temporalmente (por ejemplo
 * el botón de entrar tras un 429). `start` la arranca; al llegar a 0 queda
 * libre otra vez.
 *
 * El estado solo se actualiza desde el temporizador, nunca desde el cuerpo del
 * efecto: así lo pide la regla react-hooks/set-state-in-effect.
 */
export function useCountdown() {
  const [deadline, setDeadline] = useState<number | null>(null);
  const [remaining, setRemaining] = useState(0);

  useEffect(() => {
    if (deadline === null) return;
    const id = window.setInterval(() => {
      const left = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
      setRemaining(left);
      if (left === 0) setDeadline(null);
    }, 1000);
    return () => window.clearInterval(id);
  }, [deadline]);

  function start(seconds: number): void {
    if (seconds <= 0) return;
    setDeadline(Date.now() + seconds * 1000);
    setRemaining(seconds);
  }

  return { remaining, start };
}
