import { useState, type FormEvent } from "react";
import type { AssetResponse, AssetType } from "@/api/schema";
import { FormField } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { errorMessage, fieldError } from "@/lib/errors";
import { createAssetInput } from "../lib/asset-payload";
import {
  ASSET_TYPES,
  assetTypeLabel,
  assetValueHint,
  describeAssetError,
} from "../lib/asset-types";
import { validateAssetValue } from "../lib/asset-validation";
import { useCreateAsset, useUpdateAsset } from "../hooks/use-asset-mutations";

type AssetFormProps = {
  /** null al crear; el activo editado en caso contrario. */
  asset: AssetResponse | null;
  /** Organización del usuario; el backend la exige al crear. */
  tenantId: string | null;
  onSaved: () => void;
  onCancel: () => void;
};

export function AssetForm({ asset, tenantId, onSaved, onCancel }: AssetFormProps) {
  const isEdit = asset !== null;
  const [type, setType] = useState<AssetType>(asset?.type ?? "ip");
  const [value, setValue] = useState(asset?.value ?? "");
  const [localError, setLocalError] = useState<string | null>(null);
  const create = useCreateAsset();
  const update = useUpdateAsset();
  const mutation = isEdit ? update : create;

  const serverFieldError = fieldError(mutation.error, "value");
  const valueError = localError ?? serverFieldError;
  const generalError =
    mutation.error !== null && serverFieldError === undefined
      ? describeAssetError(errorMessage(mutation.error))
      : null;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mutation.isPending) return;
    const validation = validateAssetValue(type, value);
    setLocalError(validation);
    if (validation !== null) return;
    const trimmed = value.trim();
    if (asset === null) {
      if (tenantId === null) return;
      create.mutate(createAssetInput(tenantId, type, trimmed), { onSuccess: onSaved });
    } else {
      update.mutate({ id: asset.id, input: { type, value: trimmed } }, { onSuccess: onSaved });
    }
  }

  return (
    <section
      aria-labelledby="asset-form-heading"
      className="space-y-4 rounded-lg border border-border bg-card p-6"
    >
      <h2 id="asset-form-heading" className="text-lg font-semibold">
        {isEdit ? "Editar activo" : "Nuevo activo"}
      </h2>
      {/* noValidate: los mensajes en español los pone la validación propia. */}
      <form onSubmit={handleSubmit} noValidate className="space-y-4">
        <FormField id="asset-type" label="Tipo">
          <Select
            id="asset-type"
            value={type}
            onChange={(event) => {
              setType(event.target.value as AssetType);
              setLocalError(null);
            }}
          >
            {ASSET_TYPES.map((option) => (
              <option key={option} value={option}>
                {assetTypeLabel(option)}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField id="asset-value" label="Valor" hint={assetValueHint(type)} error={valueError}>
          <Input
            id="asset-value"
            required
            maxLength={255}
            value={value}
            onChange={(event) => {
              setValue(event.target.value);
              setLocalError(null);
            }}
            aria-invalid={valueError !== undefined ? true : undefined}
            aria-describedby={valueError !== undefined ? "asset-value-error" : undefined}
          />
        </FormField>
        {generalError !== null && (
          <p role="alert" className="text-sm text-destructive">
            {generalError}
          </p>
        )}
        <div className="flex gap-2">
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Guardando…" : isEdit ? "Guardar cambios" : "Crear activo"}
          </Button>
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancelar
          </Button>
        </div>
      </form>
    </section>
  );
}
