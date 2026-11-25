export function PlaceholderPage({ title }: { title: string }) {
  return (
    <section className="space-y-3">
      <h1 className="text-2xl font-semibold">{title}</h1>
      <p className="text-muted-foreground">Esta sección estará disponible próximamente.</p>
    </section>
  );
}
