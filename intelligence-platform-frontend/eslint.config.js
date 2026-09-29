import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import { defineConfig, globalIgnores } from "eslint/config";

export default defineConfig([
  globalIgnores(["dist"]),
  {
    files: ["**/*.{js,jsx}"],
    extends: [
      js.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    rules: {
      // This codebase's standard pattern is async data loading initiated from
      // useEffect (state setters run after `await`); the strict new rule flags
      // that pattern wholesale, which is a false positive for data fetching.
      "react-hooks/set-state-in-effect": "off",
      // Context providers intentionally co-export their hooks (useAuth,
      // useToast) alongside the provider component.
      "react-refresh/only-export-components": "off",
    },
  },
]);
