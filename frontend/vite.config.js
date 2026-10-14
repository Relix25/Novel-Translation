import { defineConfig } from 'vite';
export default defineConfig({
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('/node_modules/@mantine/')) return 'mantine';
          if (id.includes('/node_modules/')) return 'vendor';
        },
      },
      onwarn(warning, warn) {
        if (warning.code === 'MODULE_LEVEL_DIRECTIVE' && warning.message.includes('use client'))
          return;
        warn(warning);
      },
    },
  },
});
