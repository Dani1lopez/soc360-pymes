import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import { defineConfig, globalIgnores } from "eslint/config";

export default defineConfig([
  globalIgnores(["dist/**", "node_modules/**", "src/api/types.ts", "src/routeTree.gen.ts"]),
  {
    files: ["**/*.{ts,tsx}"],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      ecmaVersion: "latest",
    },
  },
  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: {
      globals: globals.browser,
    },
  },
  {
    files: ["vite.config.ts", "vitest.config.ts", "eslint.config.js"],
    languageOptions: {
      globals: globals.node,
    },
  },
  {
    files: ["src/features/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@/app", "@/app/*", "@/routes", "@/routes/*"],
              message: "Features must not depend on app composition or routes.",
            },
            {
              group: ["@/features/*/*"],
              message: "Import feature public indexes; use relative imports within a feature.",
            },
            {
              group: ["@/api/types"],
              message: "Import API types from @/api/schema, not generated types.",
            },
          ],
        },
      ],
    },
  },
  {
    files: ["src/api/**/*.{ts,tsx}", "src/components/**/*.{ts,tsx}", "src/lib/**/*.{ts,tsx}"],
    ignores: ["src/api/schema.ts"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@/features*", "@/app*", "@/routes*"],
              message: "Shared code must not depend on features, app composition, or routes.",
            },
            {
              group: ["@/api/types"],
              message: "Import API types from @/api/schema, not generated types.",
            },
          ],
        },
      ],
    },
  },
  {
    files: ["src/api/schema.ts"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@/features*", "@/app*", "@/routes*"],
              message: "Shared code must not depend on features, app composition, or routes.",
            },
          ],
        },
      ],
    },
  },
  {
    files: ["src/routes/**/*.{ts,tsx}", "src/app/**/*.{ts,tsx}"],
    ignores: ["src/app/**/*.test.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@/features/*/*"],
              message: "App and routes must import features through their public indexes.",
            },
            {
              group: ["@/api/types"],
              message: "Import API types from @/api/schema, not generated types.",
            },
          ],
        },
      ],
    },
  },
  {
    files: ["src/test/**/*.{ts,tsx}"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["@/app*", "@/routes*"],
              message: "Test helpers must not depend on app composition or routes.",
            },
            {
              group: ["@/features/*/*"],
              message: "Test helpers must import features through their public indexes.",
            },
            {
              group: ["@/api/types"],
              message: "Import API types from @/api/schema, not generated types.",
            },
          ],
        },
      ],
    },
  },
  {
    files: ["src/components/ui/**/*.{ts,tsx}"],
    rules: {
      "react-refresh/only-export-components": "off",
    },
  },
]);
