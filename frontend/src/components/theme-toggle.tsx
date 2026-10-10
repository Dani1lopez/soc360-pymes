import { Button } from "@/components/ui/button";
import { useTheme, type ThemePreference } from "@/lib/theme";

const labels = {
  light: { name: "claro", text: "Claro", next: "dark" },
  dark: { name: "oscuro", text: "Oscuro", next: "system" },
  system: { name: "según el sistema", text: "Sistema", next: "light" },
} satisfies Record<ThemePreference, { name: string; text: string; next: ThemePreference }>;

export function ThemeToggle() {
  const { preference, setPreference } = useTheme();
  const label = labels[preference];
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      aria-label={`Tema: ${label.name}`}
      onClick={() => setPreference(label.next)}
    >
      {label.text}
    </Button>
  );
}
