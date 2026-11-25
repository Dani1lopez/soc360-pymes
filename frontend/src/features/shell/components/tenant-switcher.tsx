import { Select } from "@/components/ui/select";
import { useCurrentUser } from "@/features/auth";
import { useTenants } from "@/features/tenants";
import { setActiveTenantId, useActiveTenantId } from "@/lib/active-tenant";

export function TenantSwitcher() {
  const { data: user } = useCurrentUser();
  const isSuperadmin = user?.is_superadmin === true;
  const tenants = useTenants({ enabled: isSuperadmin });
  const tenantId = useActiveTenantId();

  if (!isSuperadmin) return null;

  return (
    <Select
      aria-label="Organización"
      value={tenantId ?? ""}
      onChange={(event) => setActiveTenantId(event.target.value || null)}
    >
      <option value="">Selecciona una organización</option>
      {tenants.data?.map((tenant) => (
        <option key={tenant.id} value={tenant.id}>
          {tenant.name}
        </option>
      ))}
    </Select>
  );
}
