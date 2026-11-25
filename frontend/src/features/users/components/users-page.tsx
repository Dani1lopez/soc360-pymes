import { useState } from "react";
import { Plus } from "lucide-react";
import type { UserResponse } from "@/api/schema";
import { AsyncSection } from "@/components/async-section";
import { ConfirmButton } from "@/components/confirm-button";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ADMIN_ROLES, hasAnyRole, roleLabel, useCurrentUser } from "@/features/auth";
import { useTenants } from "@/features/tenants";
import { errorMessage } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { useUsers } from "../hooks/use-users";
import { useDeactivateUser, useReactivateUser } from "../hooks/use-user-mutations";
import { UserForm } from "./user-form";

type Editor = { user: UserResponse | null } | null;

export function UsersPage() {
  const [includeInactive, setIncludeInactive] = useState(false);
  const [tenantFilter, setTenantFilter] = useState("");
  const [editor, setEditor] = useState<Editor>(null);
  const { data: caller } = useCurrentUser();
  const tenants = useTenants({ enabled: caller?.is_superadmin ?? false });
  const query = useUsers({
    includeInactive,
    tenantId: tenantFilter === "" ? null : tenantFilter,
  });
  const deactivate = useDeactivateUser();
  const reactivate = useReactivateUser();

  const canWrite = hasAnyRole(caller, ADMIN_ROLES);
  const items = query.data ?? [];
  const actionError = deactivate.error ?? reactivate.error;

  function closeEditor() {
    setEditor(null);
  }

  return (
    <section className="space-y-6">
      <PageHeader
        title="Usuarios"
        description="Cuentas con acceso a la plataforma."
        actions={
          canWrite &&
          caller !== undefined && (
            <Button onClick={() => setEditor({ user: null })}>
              <Plus aria-hidden="true" className="size-4" />
              Nuevo usuario
            </Button>
          )
        }
      />

      <div className="flex flex-wrap items-end gap-4">
        <div className="flex items-center gap-2 pb-2">
          <input
            id="users-include-inactive"
            type="checkbox"
            checked={includeInactive}
            onChange={(event) => setIncludeInactive(event.target.checked)}
            className="size-4 rounded border-input"
          />
          <label htmlFor="users-include-inactive" className="text-sm font-medium">
            Mostrar inactivos
          </label>
        </div>
        {caller?.is_superadmin === true && (
          <div className="space-y-2">
            <label htmlFor="users-filter-tenant" className="text-sm font-medium">
              Organización
            </label>
            <Select
              id="users-filter-tenant"
              className="w-56"
              value={tenantFilter}
              onChange={(event) => setTenantFilter(event.target.value)}
            >
              <option value="">Todas las organizaciones</option>
              {(tenants.data ?? []).map((tenant) => (
                <option key={tenant.id} value={tenant.id}>
                  {tenant.name}
                </option>
              ))}
            </Select>
          </div>
        )}
      </div>

      <p className="text-xs text-muted-foreground">
        Desactivar quita el acceso al instante, pero no borra la cuenta ni su historial.
      </p>

      {caller !== undefined && caller.is_superadmin && caller.tenant_id === null && (
        <p className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
          Filtra por organización y crea la cuenta desde ahí: tu cuenta no pertenece a ninguna.
        </p>
      )}

      {actionError !== null && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(actionError)}
        </p>
      )}

      {editor !== null && caller !== undefined && (
        <UserForm user={editor.user} caller={caller} onCancel={closeEditor} onSaved={closeEditor} />
      )}

      <AsyncSection
        isPending={query.isPending}
        isFetching={query.isFetching}
        error={query.error}
        isEmpty={items.length === 0}
        emptyTitle="No hay usuarios"
        emptyMessage="Crea la primera cuenta para dar acceso a la plataforma."
        onRetry={() => void query.refetch()}
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nombre</TableHead>
              <TableHead>Correo</TableHead>
              <TableHead>Rol</TableHead>
              <TableHead>Estado</TableHead>
              <TableHead>Alta</TableHead>
              {canWrite && <TableHead>Acciones</TableHead>}
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((user) => (
              <TableRow key={user.id}>
                <TableCell className="font-medium">{user.full_name}</TableCell>
                <TableCell className="break-all text-muted-foreground">{user.email}</TableCell>
                <TableCell>{roleLabel(user.role)}</TableCell>
                <TableCell>{user.is_active ? "Activo" : "Inactivo"}</TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDateTime(user.created_at)}
                </TableCell>
                {canWrite && (
                  <TableCell>
                    <div className="flex flex-wrap items-center gap-2">
                      <Button variant="outline" size="sm" onClick={() => setEditor({ user })}>
                        Editar
                      </Button>
                      {/* Nadie se desactiva a sí mismo: perdería el acceso al instante. */}
                      {user.is_active && caller?.id !== user.id && (
                        <ConfirmButton
                          label="Desactivar"
                          confirmLabel="Quitar el acceso"
                          question="¿Quitar el acceso a esta cuenta?"
                          disabled={deactivate.isPending}
                          onConfirm={() => deactivate.mutate(user.id)}
                        />
                      )}
                      {!user.is_active && (
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={reactivate.isPending}
                          onClick={() => reactivate.mutate(user.id)}
                        >
                          Reactivar
                        </Button>
                      )}
                    </div>
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </AsyncSection>
    </section>
  );
}
