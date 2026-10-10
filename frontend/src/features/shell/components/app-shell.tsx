import { useState } from "react";
import { Link, Outlet } from "@tanstack/react-router";
import { roleLabel, useCurrentUser, useSignOut } from "@/features/auth";
import { Button } from "@/components/ui/button";
import { navigationFor } from "../lib/navigation";

export function AppShell() {
  const { data: user } = useCurrentUser();
  const signOut = useSignOut();
  const [menuOpen, setMenuOpen] = useState(false);
  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-border bg-card p-4">
        <span className="font-semibold">SOC360 PyMEs</span>
        <Button
          variant="outline"
          className="md:hidden"
          aria-expanded={menuOpen}
          aria-controls="primary-navigation"
          onClick={() => setMenuOpen(!menuOpen)}
        >
          Menú
        </Button>
        <div className="flex items-center gap-4">
          {user && (
            <div>
              <span>{user.full_name}</span>
              <span className="ml-2 text-muted-foreground">{roleLabel(user.role)}</span>
            </div>
          )}
          <Button variant="outline" disabled={signOut.isPending} onClick={() => signOut.mutate()}>
            Cerrar sesión
          </Button>
        </div>
      </header>
      <div className="md:flex">
        <aside
          className={`${menuOpen ? "block" : "hidden"} border-border bg-card p-4 md:block md:min-h-screen md:w-64 md:border-r`}
        >
          <nav
            id="primary-navigation"
            aria-label="Navegación principal"
            className="flex flex-col gap-2"
          >
            {user &&
              navigationFor(user).map((item) => (
                <Link
                  key={item.to}
                  to={item.to}
                  activeOptions={{ exact: true }}
                  className="rounded-md px-3 py-2 hover:bg-accent hover:text-accent-foreground"
                  activeProps={{
                    "aria-current": "page",
                    className: "bg-accent text-accent-foreground",
                  }}
                  onClick={() => setMenuOpen(false)}
                >
                  {item.label}
                </Link>
              ))}
          </nav>
        </aside>
        <main className="min-w-0 flex-1 p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
