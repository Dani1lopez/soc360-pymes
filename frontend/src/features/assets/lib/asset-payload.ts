import type { AssetCreateInput, AssetType } from "@/api/schema";

/**
 * Construye el cuerpo de creación. El contrato es una unión discriminada por
 * `type`, así que el objeto hay que armarlo caso por caso para que TypeScript
 * conserve el literal exacto de cada rama.
 */
export function createAssetInput(
  tenantId: string,
  type: AssetType,
  value: string,
): AssetCreateInput {
  switch (type) {
    case "ip":
      return { tenant_id: tenantId, type: "ip", value };
    case "domain":
      return { tenant_id: tenantId, type: "domain", value };
    case "hostname":
      return { tenant_id: tenantId, type: "hostname", value };
    case "web_app":
      return { tenant_id: tenantId, type: "web_app", value };
    case "subnet":
      return { tenant_id: tenantId, type: "subnet", value };
    case "cloud_resource":
      return { tenant_id: tenantId, type: "cloud_resource", value };
  }
}
