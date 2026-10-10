import { useState } from "react";
import { AsyncSection } from "@/components/async-section";
import { FormField } from "@/components/form-field";
import { PageHeader } from "@/components/page-header";
import { Select } from "@/components/ui/select";
import { useCurrentUser } from "@/features/auth";
import { useTenant, useTenants, useUpdateTenant } from "@/features/tenants";
import { PasswordForm } from "./password-form";
import { TenantForm } from "./tenant-form";

function Organization({ id, canEdit }: { id: string; canEdit: boolean }) {
  const query = useTenant(id);
  const mutation = useUpdateTenant();
  return (
    <AsyncSection
      isPending={query.isPending}
      isFetching={query.isFetching}
      error={query.error}
      onRetry={() => void query.refetch()}
    >
      {query.data !== undefined && (
        <TenantForm
          tenant={query.data}
          canEdit={canEdit}
          isPending={mutation.isPending}
          error={mutation.error}
          saved={mutation.isSuccess}
          onSave={(input) => mutation.mutate({ id, input })}
        />
      )}
    </AsyncSection>
  );
}

function OrganizationSelector() {
  const query = useTenants();
  const [selected, setSelected] = useState("");
  const tenants = query.data ?? [];
  const id = tenants.some((tenant) => tenant.id === selected) ? selected : tenants[0]?.id;
  return (
    <AsyncSection
      isPending={query.isPending}
      error={query.error}
      isEmpty={tenants.length === 0}
      emptyTitle="No hay organizaciones"
      onRetry={() => void query.refetch()}
    >
      <FormField id="settings-tenant" label="Organización">
        <Select
          id="settings-tenant"
          value={id ?? ""}
          onChange={(event) => setSelected(event.target.value)}
        >
          {tenants.map((tenant) => (
            <option key={tenant.id} value={tenant.id}>
              {tenant.name}
            </option>
          ))}
        </Select>
      </FormField>
      {id !== undefined && <Organization key={id} id={id} canEdit />}
    </AsyncSection>
  );
}

export function SettingsPage() {
  const query = useCurrentUser();
  const user = query.data;
  return (
    <section className="space-y-6">
      <PageHeader title="Configuración" description="Organización y seguridad de tu cuenta." />
      <AsyncSection
        isPending={query.isPending}
        error={query.error}
        onRetry={() => void query.refetch()}
      >
        {user?.is_superadmin ? (
          <OrganizationSelector />
        ) : user?.tenant_id ? (
          <Organization key={user.tenant_id} id={user.tenant_id} canEdit={false} />
        ) : (
          <p className="text-sm text-muted-foreground">
            Tu cuenta no tiene una organización asociada.
          </p>
        )}
      </AsyncSection>
      <PasswordForm />
    </section>
  );
}
