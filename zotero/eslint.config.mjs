// @ts-check Let TS check this config file

import zotero from "@zotero-plugin/eslint-config";
import globals from "globals";

export default zotero({
  overrides: [
    {
      files: ["**/*.ts"],
      rules: {
        "@typescript-eslint/no-unused-vars": "off",
      },
    },
    {
      // dev/ holds node-side tooling (mock server, launchers), not plugin code.
      files: ["dev/**/*.{js,mjs,cjs}"],
      languageOptions: {
        globals: { ...globals.node },
      },
    },
  ],
});
