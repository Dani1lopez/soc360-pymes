import { severities } from "./palettes";

export function Charts() {
  return (
    <div className="preview-charts">
      <section className="preview-card">
        <h2>Vulnerabilidades abiertas</h2>
        <p className="preview-muted">Distribución por severidad · datos ficticios</p>
        <div className="preview-bars">
          {severities
            .filter((s) => s.key !== "ok")
            .map((s) => (
              <div className="preview-bar-row" key={s.key}>
                <span>{s.label}</span>
                <div className="preview-track">
                  <div style={{ width: `${s.count * 2}%`, background: `var(--sev-${s.key})` }} />
                </div>
                <strong>{s.count}</strong>
              </div>
            ))}
        </div>
      </section>
      <section className="preview-card">
        <h2>Tendencia de los últimos 30 días</h2>
        <p className="preview-muted">Hallazgos abiertos · −32 % en este periodo ficticio</p>
        <svg
          className="preview-chart"
          viewBox="0 0 500 180"
          role="img"
          aria-label="Tendencia ficticia: los hallazgos bajan de 166 a 113 en 30 días"
        >
          <defs>
            <linearGradient id="preview-area" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--primary)" stopOpacity="0.3" />
              <stop offset="100%" stopColor="var(--primary)" stopOpacity="0" />
            </linearGradient>
          </defs>
          {[30, 80, 130].map((y) => (
            <path key={y} d={`M0 ${y} H500`} stroke="var(--border)" strokeDasharray="4 6" />
          ))}
          <path
            d="M0 35 L45 48 L90 40 L135 70 L180 62 L225 95 L270 83 L315 112 L360 105 L405 125 L450 119 L500 145 V170 H0 Z"
            fill="url(#preview-area)"
          />
          <path
            d="M0 35 L45 48 L90 40 L135 70 L180 62 L225 95 L270 83 L315 112 L360 105 L405 125 L450 119 L500 145"
            fill="none"
            stroke="var(--primary)"
            strokeWidth="3"
            strokeLinejoin="round"
          />
        </svg>
        <div className="preview-chart-labels">
          <span>Día 1</span>
          <span>Día 15</span>
          <span>Día 30</span>
        </div>
      </section>
    </div>
  );
}
