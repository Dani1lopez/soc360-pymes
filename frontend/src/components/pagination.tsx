import { Button } from "@/components/ui/button";

type PaginationProps = {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
};

/**
 * Paginación por `offset`/`limit` como la expone la API. `onChange` recibe el
 * desplazamiento siguiente, nunca un número de página.
 */
export function Pagination({ total, limit, offset, onChange }: PaginationProps) {
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + limit, total);
  const hasPrevious = offset > 0;
  const hasNext = offset + limit < total;
  return (
    <nav aria-label="Paginación" className="flex flex-wrap items-center justify-between gap-3">
      <p role="status" className="text-sm text-muted-foreground">
        {`Mostrando ${from}–${to} de ${total}`}
      </p>
      <div className="flex gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={!hasPrevious}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          Anterior
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={!hasNext}
          onClick={() => onChange(offset + limit)}
        >
          Siguiente
        </Button>
      </div>
    </nav>
  );
}
