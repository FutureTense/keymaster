import { defineConfig } from 'vitest/config';

export default defineConfig({
    test: {
        environment: 'happy-dom',
        include: ['lovelace_strategy/**/*.test.ts'],
        coverage: {
            provider: 'v8',
            include: ['lovelace_strategy/**/*.ts'],
            exclude: ['lovelace_strategy/**/*.test.ts', 'lovelace_strategy/ha_type_stubs.ts'],
        },
    },
});
