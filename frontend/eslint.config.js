// ESLint flat config（WS2 质量基线）
// 定位：把「运行时真问题」作为 error 阻断，把「存量类型债」作为 warn 持续可见、逐批收敛。
// `@typescript-eslint/no-explicit-any` 基线 217 处（2026-11-15），目标每批次只降不升。
import js from "@eslint/js";
import pluginVue from "eslint-plugin-vue";
import tseslint from "typescript-eslint";
import globals from "globals";

export default tseslint.config(
  { ignores: ["dist/**", "node_modules/**", "scripts/**", "*.cjs"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs["flat/essential"],
  {
    files: ["**/*.{ts,vue}"],
    languageOptions: {
      globals: { ...globals.browser },
      parserOptions: {
        parser: tseslint.parser,
        extraFileExtensions: [".vue"],
      },
    },
    rules: {
      // 存量类型债已清零（2026-11-15，WS2）：any/未使用变量直接阻断，防止新债回潮
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      // Vue 风格类规则不参与质量闸门（格式问题不阻断构建）
      "vue/multi-word-component-names": "off",
      "vue/no-v-html": "off",
    },
  },
);
