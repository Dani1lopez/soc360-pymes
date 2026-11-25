import { expect, test } from "vitest";
import { roleLabel } from "./roles";

test.each([
  ["viewer", "Lector"],
  ["analyst", "Analista"],
  ["ingestor", "Ingesta"],
  ["admin", "Administrador"],
  ["superadmin", "Superadministrador"],
] as const)("labels %s", (role, label) => expect(roleLabel(role)).toBe(label));
