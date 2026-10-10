import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Charts } from "./Charts";
import { palettes, severities, theme, type Mode, type Severity } from "./palettes";
import "./preview.css";

const findings: {
  name: string;
  asset: string;
  severity: Severity;
  status: string;
  tone: Severity;
}[] = [
  {
    name: "Ejecución remota de código",
    asset: "servidor-demo-01",
    severity: "critical",
    status: "Abierta",
    tone: "critical",
  },
  {
    name: "Credenciales de prueba expuestas",
    asset: "portal-demo",
    severity: "high",
    status: "Abierta",
    tone: "high",
  },
  {
    name: "Biblioteca ficticia desactualizada",
    asset: "api-demo-02",
    severity: "medium",
    status: "Riesgo aceptado",
    tone: "medium",
  },
  {
    name: "Configuración TLS débil",
    asset: "pasarela-demo",
    severity: "medium",
    status: "Corregida",
    tone: "ok",
  },
  {
    name: "Cabecera de seguridad ausente",
    asset: "web-demo-03",
    severity: "low",
    status: "Falso positivo",
    tone: "info",
  },
  {
    name: "Versión de servicio visible",
    asset: "correo-demo",
    severity: "info",
    status: "Corregida",
    tone: "ok",
  },
];
function Badge({ tone, children }: { tone: Severity; children: React.ReactNode }) {
  return (
    <span
      className="preview-badge"
      style={{ background: `var(--sev-${tone}-tint)`, color: `var(--sev-${tone}-foreground)` }}
    >
      {children}
    </span>
  );
}

export function Preview() {
  const [mode, setMode] = useState<Mode>("dark");
  const [palette, setPalette] = useState(0);
  return (
    <div className={`preview ${mode === "dark" ? "dark" : ""}`} style={theme(palette, mode)}>
      <aside className="preview-sidebar">
        <div className="preview-brand">
          <span>◈</span> SOC360 PyMEs
        </div>
        <p className="preview-eyebrow">Centro de operaciones</p>
        <nav aria-label="Navegación de muestra">
          {[
            "Dashboard",
            "Assets",
            "Escaneos",
            "Vulnerabilidades",
            "Informes",
            "Usuarios",
            "Configuración",
          ].map((item, index) => (
            <button key={item} type="button" aria-current={index === 0 ? "page" : undefined}>
              <span aria-hidden="true">{["▦", "▣", "◎", "◇", "▤", "♙", "⚙"][index]}</span>
              {item}
            </button>
          ))}
        </nav>
        <div className="preview-sidebar-note">
          <Badge tone="ok">Entorno de muestra</Badge>
          <p>Sin conexión a sistemas reales.</p>
        </div>
      </aside>
      <main className="preview-main">
        <header className="preview-header">
          <div>
            <p className="preview-eyebrow">Vista previa de paleta</p>
            <h1>Dashboard de seguridad</h1>
          </div>
          <div className="preview-controls">
            <div role="group" aria-label="Modo de color">
              {(["dark", "light"] as const).map((value) => (
                <Button
                  key={value}
                  size="sm"
                  variant={mode === value ? "default" : "ghost"}
                  aria-pressed={mode === value}
                  onClick={() => setMode(value)}
                >
                  {value === "dark" ? "Oscuro" : "Claro"}
                </Button>
              ))}
            </div>
            <div role="group" aria-label="Paleta">
              {palettes.map((p, index) => (
                <Button
                  key={p.name}
                  size="sm"
                  variant={palette === index ? "secondary" : "ghost"}
                  aria-pressed={palette === index}
                  onClick={() => setPalette(index)}
                >
                  {p.name}
                </Button>
              ))}
            </div>
            <div className="preview-user">
              <span>DM</span>
              <div>
                Demo Martínez<small>Analista ficticia</small>
              </div>
            </div>
          </div>
        </header>
        <div className="preview-notice">
          Prototipo desechable · Todos los datos son ficticios · No representa el estado de ningún
          sistema
        </div>
        <section className="preview-metrics" aria-label="Métricas ficticias">
          {[
            ["Assets monitorizados", "248", "+16 este mes", "info"],
            ["Críticas abiertas", "12", "−4 esta semana", "critical"],
            ["Cobertura 24 h", "98,6 %", "Objetivo: 95 %", "ok"],
            ["Escaneos correctos 30 d", "99,2 %", "1.482 ejecuciones", "ok"],
          ].map(([label, value, note, tone]) => (
            <article className="preview-card" key={label}>
              <p className="preview-muted">{label}</p>
              <strong className="preview-metric" style={{ color: `var(--sev-${tone})` }}>
                {value}
              </strong>
              <p className="preview-muted">{note}</p>
            </article>
          ))}
        </section>
        <Charts />
        <section className="preview-card preview-table-card">
          <div className="preview-section-heading">
            <div>
              <h2>Hallazgos prioritarios</h2>
              <p className="preview-muted">Inventario de ejemplo · 6 vulnerabilidades ficticias</p>
            </div>
            <Badge tone="info">Solo demostración</Badge>
          </div>
          <div className="preview-table-scroll">
            <table>
              <thead>
                <tr>
                  {["Vulnerabilidad", "Asset de ejemplo", "Severidad", "Estado"].map((label) => (
                    <th key={label} scope="col">
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {findings.map((row) => (
                  <tr key={row.name}>
                    <td>{row.name}</td>
                    <td className="preview-muted">{row.asset}</td>
                    <td>
                      <Badge tone={row.severity}>
                        {severities.find((s) => s.key === row.severity)?.label}
                      </Badge>
                    </td>
                    <td>
                      <Badge tone={row.tone}>{row.status}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <section className="preview-card">
          <h2>Componentes y estados</h2>
          <p className="preview-muted">Variantes, tamaños y validación de muestra</p>
          <div className="preview-samples">
            <Button>Principal</Button>
            <Button variant="destructive">Destructivo</Button>
            <Button variant="outline">Contorno</Button>
            <Button variant="secondary">Secundario</Button>
            <Button variant="ghost">Discreto</Button>
            <Button variant="link">Enlace</Button>
            <Button size="sm">Pequeño</Button>
            <Button size="default">Normal</Button>
            <Button size="lg">Grande</Button>
            <Button size="icon" aria-label="Añadir ejemplo">
              +
            </Button>
          </div>
          <div className="preview-field">
            <label htmlFor="preview-email">Correo de notificación</label>
            <input
              id="preview-email"
              defaultValue="correo-de-ejemplo"
              aria-invalid="true"
              aria-describedby="preview-email-error"
            />
            <p id="preview-email-error">
              Introduce un correo válido. Error de ejemplo, no se envían datos.
            </p>
          </div>
        </section>
        <footer className="preview-muted">
          SOC360 PyMEs · Laboratorio visual · {(palettes[palette] ?? palettes[0]).name} /{" "}
          {mode === "dark" ? "Oscuro" : "Claro"}
        </footer>
      </main>
    </div>
  );
}
