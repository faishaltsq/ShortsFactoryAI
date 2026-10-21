// React 19 mengekspos act() dari "react" hanya pada build development; vitest
// me-resolve ESM lewat kondisi "development" di vitest.config.mts, dan file ini
// memastikan global IS_REACT_ACT_ENVIRONMENT dipasang sebelum render.
(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
