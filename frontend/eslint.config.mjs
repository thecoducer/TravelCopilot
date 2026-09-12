import nextPlugin from "eslint-config-next";

const eslintConfig = [
  ...nextPlugin,
  {
    ignores: [".next/**", "node_modules/**", "vitest.config.ts", "vitest.setup.ts"],
  },
];

export default eslintConfig;
